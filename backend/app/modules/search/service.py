"""Service for Global Search (P4-04)."""

from __future__ import annotations

import re
import time

from app.core.db import UnitOfWork
from app.core.permissions import EffectivePermissions
from app.core.security import CurrentUser
from app.modules.search import repository as repo
from app.modules.search.schemas import (
    SearchResponse,
    SearchResultGroup,
    SearchResultItem,
)

UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class SearchService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def search(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        query: str,
        *,
        limit: int = 5,
    ) -> SearchResponse:
        start_time = time.perf_counter()
        q = query.strip()
        if not q:
            return SearchResponse(
                query="", total=0, is_qr_match=False, direct_route=None, groups=[], took_ms=0.0
            )

        pattern = f"%{q}%"
        groups: list[SearchResultGroup] = []
        is_qr = False
        direct_route: str | None = None

        with self._uow.transaction(user.id) as session:
            # 1. Check for QR Code / Barcode Direct Match
            # Check if query is formatted like a GS QR scan e.g. gs:<id>, or full URL /#/gs/<id>
            qr_gs_id = None
            if q.lower().startswith("gs:"):
                raw_id = q[3:].strip()
                if UUID_PATTERN.match(raw_id):
                    qr_gs_id = raw_id
            elif "/#/gs/" in q:
                parts = q.split("/#/gs/")
                if len(parts) > 1 and UUID_PATTERN.match(parts[1].split("?")[0].strip()):
                    qr_gs_id = parts[1].split("?")[0].strip()
            elif UUID_PATTERN.match(q):
                qr_gs_id = q

            if qr_gs_id:
                gs_match = repo.exact_match_goods_slip(session, qr_gs_id)
                if gs_match:
                    is_qr = True
                    direct_route = f"/gs/{gs_match['id']}"

            # Check if query is an exact GS No
            if not direct_route and q.upper().startswith("GS/"):
                gs_match = repo.exact_match_goods_slip(session, q.upper())
                if gs_match:
                    is_qr = True
                    direct_route = f"/gs/{gs_match['id']}"

            # Check if query is an exact Container Barcode
            if not direct_route:
                cont_match = repo.exact_match_container_barcode(session, q)
                if cont_match:
                    is_qr = True
                    direct_route = f"/inventory?view=SPARE_PARTS&search={cont_match['code']}"

            # 2. Query Groups with Permission Filtering
            # Goods Slips (requires goods_slips.view)
            if perms.allows("goods_slips", "view"):
                gs_rows = repo.search_goods_slips(session, pattern, limit)
                if gs_rows:
                    items = [
                        SearchResultItem(
                            id=str(r["id"]),
                            type="goods_slip",
                            title=r["gs_no"],
                            subtitle=f"Party: {r['party_name'] or '—'} · Status: {r['status']}",
                            badge=r["status"],
                            badge_variant="success" if r["status"] == "CLOSED" else "info",
                            route=f"/gs/{r['id']}",
                            details={
                                "docket_no": r["docket_no"],
                                "vehicle_no": r["vehicle_no"],
                                "gate_doc_no": r["gate_doc_no"],
                                "gate_entry_no": (
                                    str(r["gate_entry_no"]) if r["gate_entry_no"] else None
                                ),
                            },
                        )
                        for r in gs_rows
                    ]
                    groups.append(
                        SearchResultGroup(
                            type="goods_slip",
                            label="Goods Slips",
                            count=len(items),
                            items=items,
                        )
                    )

            # Parties (requires masters.view or goods_slips.create)
            if perms.allows("masters", "view") or perms.allows("goods_slips", "create"):
                party_rows = repo.search_parties(session, pattern, limit)
                if party_rows:
                    items = [
                        SearchResultItem(
                            id=str(r["id"]),
                            type="party",
                            title=r["name"],
                            subtitle=(
                                f"GSTIN: {r['gstin'] or '—'} · Station: {r['station_name'] or '—'}"
                            ),
                            badge=r["code"],
                            badge_variant="neutral",
                            route=f"/gs?party_id={r['id']}",
                            details={"phone": r["phone"], "contact_name": r["contact_name"]},
                        )
                        for r in party_rows
                    ]
                    groups.append(
                        SearchResultGroup(
                            type="party",
                            label="Parties",
                            count=len(items),
                            items=items,
                        )
                    )

            # Inward Documents (requires goods_slips.view or accounts.view)
            if perms.allows("goods_slips", "view") or perms.allows("accounts", "view"):
                doc_rows = repo.search_documents(session, pattern, limit)
                if doc_rows:
                    items = [
                        SearchResultItem(
                            id=str(r["id"]),
                            type="document",
                            title=f"Doc: {r['doc_no']}",
                            subtitle=f"Type: {r['classification_code']} · GS: {r['gs_no']}",
                            badge=r["classification_code"],
                            badge_variant="info",
                            route=f"/gs/{r['gs_id']}?tab=overview",
                            details={"amount": float(r["amount"]) if r["amount"] else None},
                        )
                        for r in doc_rows
                    ]
                    groups.append(
                        SearchResultGroup(
                            type="document",
                            label="Consignment Documents",
                            count=len(items),
                            items=items,
                        )
                    )

            # Credit Notes / Vouchers (requires credit_notes.view or accounts.view)
            if perms.allows("credit_notes", "view") or perms.allows("accounts", "view"):
                cn_rows = repo.search_credit_notes(session, pattern, limit)
                if cn_rows:
                    items = [
                        SearchResultItem(
                            id=str(r["id"]),
                            type="credit_note",
                            title=(f"Voucher: {r['cn_no'] or r['jv_no'] or ''}"),
                            subtitle=(f"Type: {r['cn_type_code']} · Status: {r['status']}"),
                            badge=r["status"],
                            badge_variant="success" if r["status"] == "ISSUED" else "warning",
                            route=f"/credit-notes/workspace/{r['id']}",
                            details={
                                "total_value": float(r["total_value"]) if r["total_value"] else None
                            },
                        )
                        for r in cn_rows
                    ]
                    groups.append(
                        SearchResultGroup(
                            type="credit_note",
                            label="Credit Notes & JVs",
                            count=len(items),
                            items=items,
                        )
                    )

            # Custody Transfers (requires custody.view or inventory.view)
            if perms.allows("custody", "view") or perms.allows("inventory", "view"):
                transfer_rows = repo.search_transfers(session, pattern, limit)
                if transfer_rows:
                    items = [
                        SearchResultItem(
                            id=str(r["id"]),
                            type="transfer",
                            title=r["transfer_no"],
                            subtitle=f"{r['from_location_name']} → {r['to_location_name']}",
                            badge=r["status"],
                            badge_variant="info",
                            route=f"/custody/transfers/{r['id']}",
                            details={"gs_id": str(r["gs_id"]) if r["gs_id"] else None},
                        )
                        for r in transfer_rows
                    ]
                    groups.append(
                        SearchResultGroup(
                            type="transfer",
                            label="Custody Transfers",
                            count=len(items),
                            items=items,
                        )
                    )

            # Store Issues (requires store_issue.view or inventory.view)
            if perms.allows("store_issue", "view") or perms.allows("inventory", "view"):
                issue_rows = repo.search_store_issues(session, pattern, limit)
                if issue_rows:
                    items = [
                        SearchResultItem(
                            id=str(r["id"]),
                            type="store_issue",
                            title=r["issue_no"],
                            subtitle=f"Type: {r['issue_type_code']} · Status: {r['status']}",
                            badge=r["status"],
                            badge_variant="success" if r["status"] == "ACKNOWLEDGED" else "info",
                            route="/store-issues",
                            details={},
                        )
                        for r in issue_rows
                    ]
                    groups.append(
                        SearchResultGroup(
                            type="store_issue",
                            label="Store Issues",
                            count=len(items),
                            items=items,
                        )
                    )

            # Replacement Dispatches (requires dispatch.view or inventory.view)
            if perms.allows("dispatch", "view") or perms.allows("inventory", "view"):
                dispatch_rows = repo.search_dispatches(session, pattern, limit)
                if dispatch_rows:
                    items = [
                        SearchResultItem(
                            id=str(r["id"]),
                            type="dispatch",
                            title=r["dispatch_no"],
                            subtitle=f"Type: {r['dispatch_type']} · GS: {r['gs_no'] or '—'}",
                            badge=r["status"],
                            badge_variant="success" if r["status"] == "DISPATCHED" else "info",
                            route="/dispatch",
                            details={
                                "docket_no": r["docket_no"],
                                "vehicle_no": r["vehicle_no"],
                            },
                        )
                        for r in dispatch_rows
                    ]
                    groups.append(
                        SearchResultGroup(
                            type="dispatch",
                            label="Replacement Dispatches",
                            count=len(items),
                            items=items,
                        )
                    )

            # Batches (technician & dismantle)
            if (
                perms.allows("servicing", "view")
                or perms.allows("dismantling", "view")
                or perms.allows("inventory", "view")
            ):
                batch_rows = repo.search_batches(session, pattern, limit)
                if batch_rows:
                    items = [
                        SearchResultItem(
                            id=str(r["id"]),
                            type="batch",
                            title=r["batch_no"],
                            subtitle=f"Kind: {r['batch_kind']} · Status: {r['status']}",
                            badge=r["status"],
                            badge_variant="info",
                            route="/servicing"
                            if r["batch_kind"] == "TECHNICIAN"
                            else "/dismantling",
                            details={},
                        )
                        for r in batch_rows
                    ]
                    groups.append(
                        SearchResultGroup(
                            type="batch",
                            label="Processing Batches",
                            count=len(items),
                            items=items,
                        )
                    )

            # Containers & Partitions (requires inventory.view)
            if perms.allows("inventory", "view"):
                cont_rows = repo.search_containers(session, pattern, limit)
                if cont_rows:
                    items = [
                        SearchResultItem(
                            id=str(r["id"]),
                            type="container",
                            title=f"{r['name']} ({r['code']})",
                            subtitle=(
                                f"Barcode: {r['barcode'] or '—'} · Type: {r['container_type']}"
                            ),
                            badge=r["code"],
                            badge_variant="neutral",
                            route=f"/inventory?view=SPARE_PARTS&search={r['code']}",
                            details={"barcode": r["barcode"]},
                        )
                        for r in cont_rows
                    ]
                    groups.append(
                        SearchResultGroup(
                            type="container",
                            label="Storage Containers",
                            count=len(items),
                            items=items,
                        )
                    )

        total_matches = sum(g.count for g in groups)
        took_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        return SearchResponse(
            query=q,
            total=total_matches,
            is_qr_match=is_qr,
            direct_route=direct_route,
            groups=groups,
            took_ms=took_ms,
        )
