"""Transfer slips (Phase P5, DEC-65; Q10 user, Q20 PROVISIONAL, Q26 user).

The Replacement Manager selects 1..N goods slips whose categorisation is locked (status
PENDING_TRANSFER_SLIP, DEC-64) and generates, in ONE transaction with an Idempotency-Key (G-16),
**one slip per Intermediate Store** that has lines on them: lines are grouped by the store of their
product (DEC-61, `store_for_product`), so a GS spanning 3 stores is on 3 slips, and each slip covers
every selected GS that has lines for its store. Each slip is backed by one custody transfer
INWARD_STAGING → TRANSIT → the store's location (G-09: stock enters TRANSIT only through a custody
transfer); the store acknowledges it in P6. Every slip also lists the other items of its GSs
greyed, with the store they belong to.

"Send Edit Request" (reason) notifies Management + Super Admin and keeps the GS off the slips until
the request is resolved (edited, or rejected with a note). When Super Admin / Management edit a GS
after its slips exist, the itemization service calls `void_live_slips_for_gs` first (Q10): the slips
are voided, their stock returns to Inward Staging, and their GSs wait for a new slip.

Every rule is repeated in the database (migration 20261121000100).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from sqlalchemy.orm import Session

from app.core.db import UnitOfWork
from app.core.errors import Conflict, NotFound, PermissionDenied, SystemGuardViolation
from app.core.idempotency import IdempotencyKey, IdempotentResult, run_idempotent
from app.core.permissions import EffectivePermissions
from app.core.security import CurrentUser
from app.modules.custody import service as custody_service
from app.modules.custody.schemas import TransferLineIn
from app.modules.goods_slips import service as gs_service
from app.modules.intermediate_stores import service as store_service
from app.modules.notifications import service as notifications
from app.modules.transfer_slips import repository as repo
from app.modules.transfer_slips.schemas import (
    EditRequestIn,
    EditRequestOut,
    GenerateIn,
    GenerateOut,
    GsTransferSlipsOut,
    PendingBucketOut,
    PendingGsOut,
    PendingLineOut,
    ResolveEditRequestIn,
    SlipDetailOut,
    SlipGsOut,
    SlipLineOut,
    SlipPage,
    SlipSummaryOut,
    StoreRefOut,
)
from app.shared.branding import template_logo
from app.shared.pdf import (
    SlipColumn,
    SlipDocument,
    SlipField,
    SlipSection,
    SlipSignature,
    SlipTable,
    render_slip_pdf,
)

log = structlog.get_logger("rms.transfer_slips")

PENDING = "PENDING_TRANSFER_SLIP"
GENERATED = "TRANSFER_SLIP_GENERATED"
STATUS_STEP = "TRANSFER_SLIP"  # gs_status_history step code of the slip transitions
STAGING = "INWARD_STAGING"
PURPOSE = "TRANSFER_SLIP"  # custody_transfers.purpose_code
GS_ENTITY = "goods_slips"
SLIP_ENTITY = "transfer_slips"
RO = "RO"


def _tz(session: Session) -> ZoneInfo:
    name = repo.get_setting(session, "timezone")
    try:
        return ZoneInfo(str(name)) if name else ZoneInfo("Asia/Kolkata")
    except ZoneInfoNotFoundError:
        log.error("timezone_setting_invalid", value=name)
        raise Conflict(
            "System setting 'timezone' is not a valid time zone",
            code="SETTING_INVALID",
            details={"key": "timezone"},
        ) from None


def _date_fmt(session: Session) -> str:
    raw = str(repo.get_setting(session, "date_format") or "DD-MM-YYYY")
    return raw.replace("YYYY", "%Y").replace("MM", "%m").replace("DD", "%d")


def _fmt(value: date | datetime | None, fmt: str, tz: ZoneInfo) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(tz).strftime(fmt)
    return value.strftime(fmt)


def _store_ref(row: dict[str, Any]) -> StoreRefOut | None:
    if not row.get("store_id"):
        return None
    return StoreRefOut(id=row["store_id"], code=row["store_code"], name=row["store_name"])


def _summary(row: dict[str, Any]) -> SlipSummaryOut:
    return SlipSummaryOut(
        id=row["id"],
        slip_no=row["slip_no"],
        store=StoreRefOut(id=row["store_id"], code=row["store_code"], name=row["store_name"]),
        status=row["status"],
        gs_count=int(row["gs_count"]),
        gs_nos=list(row["gs_nos"] or []),
        relevant_qty=int(row["relevant_qty"]),
        grand_total_qty=int(row["grand_total_qty"]),
        generated_by_name=row.get("generated_by_name"),
        generated_at=row["generated_at"],
        voided_at=row.get("voided_at"),
        void_reason=row.get("void_reason"),
    )


def _request_out(row: dict[str, Any]) -> EditRequestOut:
    return EditRequestOut.model_validate(row)


# =============================================================================================
# Service-to-service API (runs inside the caller's transaction)
# =============================================================================================
def void_live_slips_for_gs(
    session: Session, user: CurrentUser, gs_id: UUID, *, reason: str
) -> list[str]:
    """DEC-65 / Q10: before Super Admin / Management edit a locked GS, every live slip it is on is
    voided: the slip's stock returns from TRANSIT to Inward Staging (custody void) and each GS on
    the slip waits for a new slip (TRANSFER_SLIP_GENERATED → PENDING_TRANSFER_SLIP). Returns the
    voided slip numbers. The caller has checked the edit authority (itemization.configure)."""
    voided: list[str] = []
    for slip_id in repo.live_slip_ids_for_gs(session, gs_id):
        slip = repo.get_slip(session, slip_id, for_update=True)
        if slip is None:  # pragma: no cover - selected for update just above
            raise NotFound("Transfer slip not found", code="TRANSFER_SLIP_NOT_FOUND")
        if slip["status"] == "ACKNOWLEDGED":
            # P6 extends the void to acknowledged slips (stock back from the store's location).
            raise Conflict(
                f"Transfer slip {slip['slip_no']} is already acknowledged by the store",
                code="TRANSFER_SLIP_ACKNOWLEDGED",
                details={"slip_no": slip["slip_no"]},
            )
        why = f"Voided: goods slip changed after the lock (Q10). {reason.strip()}"
        repo.set_voided(session, slip_id, by=user.id, reason=why)
        custody_service.void_transfer(
            session, user=user, transfer_id=slip["custody_transfer_id"], reason=why
        )
        for other_gs in repo.gs_ids_on_slip(session, slip_id):
            gs = gs_service.lock_goods_slip(session, other_gs)
            if gs["status"] == GENERATED:
                gs_service.change_status_within_step(
                    session,
                    gs_id=other_gs,
                    from_status=GENERATED,
                    to_status=PENDING,
                    step_code=STATUS_STEP,
                    reason=f"Transfer slip {slip['slip_no']} voided (DEC-65, Q10)",
                    by=user.id,
                )
        # Recipients: the notification rule (RM). The store users already got the custody
        # TRANSFER_CANCELLED alert from the void above.
        notifications.publish(
            session,
            "TRANSFER_SLIP_VOIDED",
            title=f"Transfer slip {slip['slip_no']} voided - regenerate it",
            body=f"{user.full_name}: {reason.strip()}",
            entity_type=SLIP_ENTITY,
            entity_id=slip_id,
            gs_id=gs_id,
            priority="HIGH",
        )
        voided.append(str(slip["slip_no"]))
        log.info("transfer_slip_voided", slip_no=slip["slip_no"], gs_id=str(gs_id))
    return voided


@dataclass(slots=True)
class _Line:
    item: dict[str, Any]
    buckets: list[dict[str, Any]]
    store_id: UUID
    store_name: str


class TransferSlipService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    # ------------------------------------------------------------------ read ----------------
    def pending(
        self,
        user: CurrentUser,
        *,
        party_id: UUID | None,
        date_from: date | None,
        date_to: date | None,
        store_id: UUID | None,
    ) -> list[PendingGsOut]:
        with self._uow.transaction(user.id) as session:
            tz = _tz(session)
            headers = repo.pending_goods_slips(
                session,
                tz=str(tz),
                party_id=party_id,
                date_from=date_from,
                date_to=date_to,
                store_id=store_id,
            )
            gs_ids = [h["gs_id"] for h in headers]
            items = repo.physical_items(session, gs_ids)
            item_ids = [i["id"] for i in items]
            buckets = repo.buckets_for_items(session, item_ids)
            covered = {c["gs_item_id"]: c for c in repo.live_coverage(session, item_ids)}
            requests = {r["gs_id"]: r for r in repo.open_edit_requests(session, gs_ids)}
            b_by_item: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
            for b in buckets:
                b_by_item[b["gs_item_id"]].append(b)
            i_by_gs: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
            for it in items:
                i_by_gs[it["gs_id"]].append(it)

            out: list[PendingGsOut] = []
            for h in headers:
                lines: list[PendingLineOut] = []
                stores: dict[UUID, StoreRefOut] = {}
                for it in i_by_gs.get(h["gs_id"], []):
                    store = _store_ref(it)
                    if store and int(it["received_qty"]) > 0:
                        stores[store.id] = store
                    cov = covered.get(it["id"])
                    lines.append(
                        PendingLineOut(
                            item_id=it["id"],
                            line_no=it["line_no"],
                            product_code=it["product_code"],
                            product_name=it["product_name"],
                            documented_qty=it["documented_qty"],
                            received_qty=it["received_qty"],
                            store=store,
                            buckets=[
                                PendingBucketOut(
                                    field_code=b["field_code"],
                                    label=b["label_snapshot"] or b["field_code"],
                                    qty=b["qty"],
                                )
                                for b in b_by_item.get(it["id"], [])
                            ],
                            on_slip_no=cov["slip_no"] if cov else None,
                        )
                    )
                req = requests.get(h["gs_id"])
                out.append(
                    PendingGsOut(
                        gs_id=h["gs_id"],
                        gs_no=h["gs_no"],
                        party_id=h["party_id"],
                        party_name=h["party_name"],
                        station_name=h["station_name"],
                        state_name=h["state_name"],
                        cartons=h["cartons"],
                        received_date=h["received_date"],
                        locked_at=h["locked_at"],
                        stores=sorted(stores.values(), key=lambda s: s.code),
                        physical_qty=sum(int(i["received_qty"]) for i in i_by_gs[h["gs_id"]]),
                        lines=lines,
                        open_edit_request=_request_out(req) if req else None,
                        partially_on_slips=any(ln.on_slip_no for ln in lines),
                    )
                )
            return out

    def list_slips(
        self,
        user: CurrentUser,
        *,
        status: str | None,
        store_id: UUID | None,
        q: str | None,
        page: int,
        page_size: int,
    ) -> SlipPage:
        with self._uow.transaction(user.id) as session:
            rows, total = repo.list_slips(
                session,
                status=status,
                store_id=store_id,
                gs_no=(q or "").strip() or None,
                limit=page_size,
                offset=(page - 1) * page_size,
            )
            return SlipPage(items=[_summary(r) for r in rows], total=total)

    def detail(self, user: CurrentUser, slip_id: UUID) -> SlipDetailOut:
        with self._uow.transaction(user.id) as session:
            return self._detail(session, slip_id)

    def _detail(self, session: Session, slip_id: UUID) -> SlipDetailOut:
        row = repo.get_slip(session, slip_id)
        if not row:
            raise NotFound("Transfer slip not found", code="TRANSFER_SLIP_NOT_FOUND")
        base = _summary(row)
        return SlipDetailOut(
            **base.model_dump(),
            custody_transfer_id=row["custody_transfer_id"],
            goods_slips=[
                SlipGsOut.model_validate(g) for g in repo.slip_goods_slips(session, slip_id)
            ],
            lines=[SlipLineOut.model_validate(ln) for ln in repo.slip_lines(session, slip_id)],
            acknowledged_by_name=row.get("acknowledged_by_name"),
            acknowledged_at=row.get("acknowledged_at"),
        )

    def for_gs(
        self, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID
    ) -> GsTransferSlipsOut:
        with self._uow.transaction(user.id) as session:
            gs_service.get_visible_goods_slip(session, user, perms, gs_id)
            requests = [_request_out(r) for r in repo.edit_requests_for_gs(session, gs_id)]
            return GsTransferSlipsOut(
                gs_id=gs_id,
                slips=[_summary(r) for r in repo.slips_for_gs(session, gs_id)],
                edit_requests=requests,
                open_edit_request=next((r for r in requests if r.status == "OPEN"), None),
            )

    def edit_requests(self, user: CurrentUser, *, status: str | None) -> list[EditRequestOut]:
        with self._uow.transaction(user.id) as session:
            return [_request_out(r) for r in repo.edit_requests(session, status=status)]

    # ------------------------------------------------------------------ PDF -----------------
    def pdf(self, user: CurrentUser, slip_id: UUID) -> tuple[str, bytes]:
        """A4 PDF of the slip (Q20), rendered from its stored snapshots: the same slip always
        gives the same bytes (deterministic renderer)."""
        with self._uow.transaction(user.id) as session:
            detail = self._detail(session, slip_id)
            row = repo.get_slip(session, slip_id)
            template = repo.published_template(session)
            if not template or not row:
                raise Conflict(
                    "No published TRANSFER_SLIP print template", code="TEMPLATE_NOT_PUBLISHED"
                )
            doc = self._slip_document(session, template, detail, row)
            pdf = render_slip_pdf(doc)
            log.info("transfer_slip_pdf", slip_no=detail.slip_no, size=len(pdf))
            filename = detail.slip_no.replace("/", "-") + ".pdf"
            return filename, pdf

    def _slip_document(
        self,
        session: Session,
        template: dict[str, Any],
        d: SlipDetailOut,
        row: dict[str, Any],
    ) -> SlipDocument:
        layout: dict[str, Any] = template["layout"] or {}
        titles = {
            s.get("id"): s.get("title") for s in layout.get("sections", []) if isinstance(s, dict)
        }

        def title(section_id: str, fallback: str) -> str:
            return str(titles.get(section_id) or fallback)

        tz = _tz(session)
        fmt = _date_fmt(session)
        generated = _fmt(d.generated_at, f"{fmt} %H:%M", tz)
        content = row.get("content") or {}
        generated_by = str(content.get("generated_by_name") or d.generated_by_name or "")

        sections = [
            SlipSection(
                title("header", "Transfer Slip"),
                [
                    SlipField("Transfer Slip No.", d.slip_no),
                    SlipField("Intermediate Store", d.store.name),
                    SlipField("Date", generated),
                    SlipField("Generated by", generated_by),
                    *([SlipField("Status", d.status)] if d.status != "GENERATED" else []),
                ],
            )
        ]
        gs_title = title("goods_slips", "Goods Slip")
        for g in d.goods_slips:
            sections.append(
                SlipSection(
                    f"{gs_title} {g.gs_no}",
                    [
                        SlipField("Party", g.party_name or ""),
                        SlipField(
                            "Station / State",
                            " / ".join(x for x in (g.station_name, g.state_name) if x),
                        ),
                        SlipField("Cartons", "" if g.cartons is None else str(g.cartons)),
                        SlipField("Received", _fmt(g.received_date, fmt, tz)),
                    ],
                )
            )

        columns = [
            SlipColumn("#", 0.4, "right"),
            SlipColumn("Code", 0.9),
            SlipColumn("Product", 2.2),
            SlipColumn("Condition", 1.3),
            SlipColumn("Qty", 0.6, "right"),
        ]
        tables: list[SlipTable] = []
        rel_title = title("relevant", "Items for this store")
        gs_by_id = {g.gs_id: g for g in d.goods_slips}
        for g in d.goods_slips:
            rel = [ln for ln in d.lines if ln.is_relevant and ln.gs_id == g.gs_id]
            if not rel:
                continue
            tables.append(
                SlipTable(
                    title=f"{rel_title} · {g.gs_no} · {g.party_name or ''}".rstrip(" ·"),
                    columns=columns,
                    rows=[
                        [
                            str(ln.line_no),
                            ln.product_code or "",
                            ln.product_name,
                            ln.bucket_label or "",
                            str(ln.qty),
                        ]
                        for ln in rel
                    ],
                    total_row=["", "", f"Subtotal {g.gs_no}", "", str(g.relevant_qty)],
                )
            )
        others = [ln for ln in d.lines if not ln.is_relevant]
        if others:
            tables.append(
                SlipTable(
                    title=title("others", "Other items of these goods slips (other stores)"),
                    columns=[
                        SlipColumn("GS", 1.1),
                        SlipColumn("#", 0.4, "right"),
                        SlipColumn("Product", 2.0),
                        SlipColumn("Condition", 1.2),
                        SlipColumn("Qty", 0.5, "right"),
                        SlipColumn("Store", 1.2),
                    ],
                    rows=[
                        [
                            gs_by_id[ln.gs_id].gs_no if ln.gs_id in gs_by_id else "",
                            str(ln.line_no),
                            ln.product_name,
                            ln.bucket_label or "",
                            str(ln.qty),
                            ln.belongs_store_name,
                        ]
                        for ln in others
                    ],
                    muted=True,
                )
            )
        tables.append(
            SlipTable(
                title=title("totals", "Totals"),
                columns=[SlipColumn("", 3.0), SlipColumn("Qty", 1.0, "right")],
                rows=[
                    ["Total relevant qty (this store)", str(d.relevant_qty)],
                    ["Grand total (all items of included GSs)", str(d.grand_total_qty)],
                ],
            )
        )
        signatures = [
            SlipSignature(
                label=str(block.get("label", "")),
                role=str(block.get("role", "")),
                name=generated_by if i == 0 else None,
            )
            for i, block in enumerate(layout.get("signature_blocks", []))
            if isinstance(block, dict)
        ]
        return SlipDocument(
            title=str(layout.get("header_title") or template.get("name") or ""),
            subtitle=str(layout.get("header_subtitle") or template.get("name") or ""),
            document_ref=f"{d.slip_no} · {d.store.name}",
            sections=sections,
            tables=tables,
            signatures=signatures,
            signatures_title=title("signatures", "Signatures"),
            footer_text=str(layout.get("footer_text") or ""),
            generated_text=f"Generated {generated} by {generated_by}",
            brand_color=str(repo.get_setting(session, "branding_primary_color") or ""),
            paper_size=str(layout.get("paper_size") or "A4"),
            orientation=str(layout.get("orientation") or "portrait"),
            logo=template_logo(session, layout),
        )

    # ------------------------------------------------------------------ generate ------------
    def generate(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        payload: GenerateIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        with self._uow.transaction(user.id) as session:
            return run_idempotent(
                session,
                idem,
                user.id,
                lambda: (201, self._generate(session, user, perms, payload)),
            )

    def _generate(
        self,
        session: Session,
        user: CurrentUser,
        perms: EffectivePermissions,
        payload: GenerateIn,
    ) -> dict[str, Any]:
        if not perms.allows("transfer_slips", "create"):
            raise PermissionDenied("Only the Replacement Manager generates transfer slips (DEC-65)")
        tz = _tz(session)
        gs_ids = sorted(payload.gs_ids, key=str)  # fixed lock order (no deadlocks)
        for gs_id in gs_ids:
            gs_service.lock_goods_slip(session, gs_id)
            gs_service.get_visible_goods_slip(session, user, perms, gs_id)
        headers = {h["gs_id"]: h for h in repo.goods_slip_headers(session, gs_ids, tz=str(tz))}
        not_pending = [h["gs_no"] for h in headers.values() if h["status"] != PENDING]
        if not_pending:
            raise Conflict(
                "Only goods slips pending a transfer slip can be put on one",
                code="GS_NOT_PENDING_TRANSFER_SLIP",
                details={"gs_nos": sorted(not_pending)},
            )
        not_ro = [h["gs_no"] for h in headers.values() if h["category_code"] != RO]
        if not_ro:  # pragma: no cover - the lock requires Replacement (DB guard too)
            raise Conflict(
                "Only Replacement goods slips go on transfer slips",
                code="NOT_REPLACEMENT",
                details={"gs_nos": sorted(not_ro)},
            )
        requested = repo.open_edit_requests(session, gs_ids)
        if requested:
            raise Conflict(
                "A goods slip with an open edit request cannot go on a transfer slip",
                code="EDIT_REQUEST_OPEN",
                details={"gs_nos": sorted(r["gs_no"] for r in requested)},
            )

        items = [i for i in repo.physical_items(session, gs_ids) if int(i["received_qty"]) > 0]
        item_ids = [i["id"] for i in items]
        covered = {c["gs_item_id"]: c for c in repo.live_coverage(session, item_ids)}
        todo = [i for i in items if i["id"] not in covered]
        empty = [
            h["gs_no"] for gid, h in headers.items() if not any(i["gs_id"] == gid for i in todo)
        ]
        if empty:
            raise Conflict(
                "These goods slips have no physical quantity left to hand over",
                code="NOTHING_TO_TRANSFER",
                details={"gs_nos": sorted(empty)},
            )

        # DEC-61: every product resolves to a store (409 STORE_MAPPING_MISSING; DB check too).
        store_of = store_service.require_stores_for_products(
            session, sorted({i["product_id"] for i in todo}, key=str)
        )
        stores = {
            s["id"]: s for s in repo.stores_by_ids(session, sorted(set(store_of.values()), key=str))
        }
        inactive = [s["code"] for s in stores.values() if not s["is_active"]]
        if inactive:  # pragma: no cover - store_for_product resolves active stores only
            raise Conflict(
                "Intermediate Store is inactive",
                code="STORE_INACTIVE",
                details={"store_codes": inactive},
            )

        buckets: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
        for b in repo.buckets_for_items(session, [i["id"] for i in items]):
            buckets[b["gs_item_id"]].append(b)
        for it in todo:  # G-19 (the DB checks every slip line against the split as well)
            split = sum(int(b["qty"]) for b in buckets[it["id"]])
            if split != int(it["received_qty"]):
                raise SystemGuardViolation(
                    "G-19",
                    f"{headers[it['gs_id']]['gs_no']} line {it['line_no']}: the condition split "
                    f"({split}) must equal the physical quantity ({it['received_qty']}) (G-19)",
                    details={"item_id": str(it["id"])},
                )

        lots: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
        for lot in repo.staging_lots(session, [i["id"] for i in todo]):
            lots[lot["gs_item_id"]].append(lot)
        for it in todo:
            staged = sum(int(lt["qty"]) for lt in lots[it["id"]])
            if staged != int(it["received_qty"]):
                log.error(
                    "transfer_slip_stock_mismatch",
                    gs_no=headers[it["gs_id"]]["gs_no"],
                    line_no=it["line_no"],
                    staged=staged,
                    received=it["received_qty"],
                )
                raise Conflict(
                    f"{headers[it['gs_id']]['gs_no']} line {it['line_no']}: {staged} pc in "
                    f"Inward Staging, {it['received_qty']} expected",
                    code="STOCK_NOT_IN_STAGING",
                    details={
                        "item_id": str(it["id"]),
                        "staged": staged,
                        "received_qty": it["received_qty"],
                    },
                )

        template = repo.published_template(session)
        if not template:
            raise Conflict(
                "No published TRANSFER_SLIP print template", code="TEMPLATE_NOT_PUBLISHED"
            )

        # Every physical line of the selected GSs, with the store it belongs to (for the greyed
        # section): its live slip's store if it is already on one, else its product's store.
        lines_all: list[_Line] = []
        for it in items:
            if it["id"] in covered:
                sid, sname = covered[it["id"]]["store_id"], covered[it["id"]]["store_name"]
            else:
                sid = store_of[it["product_id"]]
                sname = stores[sid]["name"]
            lines_all.append(
                _Line(item=it, buckets=buckets[it["id"]], store_id=sid, store_name=sname)
            )

        by_store: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
        for it in todo:
            by_store[store_of[it["product_id"]]].append(it)

        today = datetime.now(tz).date()
        slip_ids: list[UUID] = []
        for store_id in sorted(
            by_store, key=lambda s: (stores[s]["sort_order"], stores[s]["code"])
        ):
            store = stores[store_id]
            rel_items = by_store[store_id]
            rel_ids = {i["id"] for i in rel_items}
            slip_gs = sorted({i["gs_id"] for i in rel_items}, key=lambda g: headers[g]["gs_no"])
            slip_no = repo.next_slip_no(session, today, store["code"])
            transfer_id = custody_service.initiate_transfer(
                session,
                actor=user,
                from_location_code=STAGING,
                to_location_code=store["location_code"],
                lines=[
                    TransferLineIn(lot_id=lt["lot_id"], qty=int(lt["qty"]))
                    for it in rel_items
                    for lt in lots[it["id"]]
                ],
                purpose_code=PURPOSE,
                notes=f"Transfer Slip {slip_no} to {store['name']} (DEC-65)",
                check_custodian=False,
                transfer_no=slip_no,
            )
            gs_lines = [ln for ln in lines_all if ln.item["gs_id"] in set(slip_gs)]
            relevant_qty = sum(int(i["received_qty"]) for i in rel_items)
            grand_total = sum(int(ln.item["received_qty"]) for ln in gs_lines)
            slip_id = repo.insert_slip(
                session,
                slip_no=slip_no,
                store_id=store_id,
                custody_transfer_id=transfer_id,
                relevant_qty=relevant_qty,
                grand_total_qty=grand_total,
                template_version_no=int(template["version_no"]),
                content={"generated_by_name": user.full_name, "source_ref": "DEC-65"},
            )
            for gid in slip_gs:
                mine = [ln for ln in gs_lines if ln.item["gs_id"] == gid]
                repo.insert_slip_gs(
                    session,
                    slip_id=slip_id,
                    gs=headers[gid],
                    relevant_qty=sum(
                        int(ln.item["received_qty"]) for ln in mine if ln.item["id"] in rel_ids
                    ),
                    total_qty=sum(int(ln.item["received_qty"]) for ln in mine),
                )
                for ln in mine:
                    relevant = ln.item["id"] in rel_ids
                    for b in ln.buckets or [None]:  # type: ignore[list-item]
                        repo.insert_slip_line(
                            session,
                            slip_id=slip_id,
                            line={
                                "gs": gid,
                                "item": ln.item["id"],
                                "line_no": ln.item["line_no"],
                                "product": ln.item["product_id"],
                                "pcode": ln.item["product_code"],
                                "pname": ln.item["product_name"],
                                "bfield": b["field_id"] if b else None,
                                "bcode": b["field_code"] if b else None,
                                "blabel": (b["label_snapshot"] or b["field_code"]) if b else None,
                                "qty": int(b["qty"]) if b else int(ln.item["received_qty"]),
                                "relevant": relevant,
                                "store": store_id if relevant else ln.store_id,
                                "store_name": store["name"] if relevant else ln.store_name,
                            },
                        )
            slip_ids.append(slip_id)
            log.info(
                "transfer_slip_generated",
                slip_no=slip_no,
                store=store["code"],
                gs_count=len(slip_gs),
                relevant_qty=relevant_qty,
            )

        for gs_id in gs_ids:
            if (
                repo.gaps(session, gs_id) != 0
            ):  # pragma: no cover - every uncovered line is on a slip
                raise Conflict("A goods slip is not fully covered", code="TRANSFER_SLIP_INCOMPLETE")
            gs_service.change_status_within_step(
                session,
                gs_id=gs_id,
                from_status=PENDING,
                to_status=GENERATED,
                step_code=STATUS_STEP,
                reason="Transfer slips generated (DEC-65)",
                by=user.id,
            )
        slips = repo.slips_by_ids(session, slip_ids)
        return GenerateOut(
            slips=[_summary(s) for s in slips], goods_slip_ids=list(gs_ids)
        ).model_dump(mode="json")

    # ------------------------------------------------------------------ edit requests -------
    @staticmethod
    def _request_row(session: Session, request_id: UUID) -> dict[str, Any]:
        row = repo.get_edit_request(session, request_id)
        if row is None:  # pragma: no cover - written in this transaction
            raise NotFound("Edit request not found", code="EDIT_REQUEST_NOT_FOUND")
        return _request_out(row).model_dump(mode="json")

    def request_edit(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: EditRequestIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        with self._uow.transaction(user.id) as session:
            return run_idempotent(
                session,
                idem,
                user.id,
                lambda: (201, self._request_edit(session, user, perms, gs_id, payload)),
            )

    def _request_edit(
        self,
        session: Session,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: EditRequestIn,
    ) -> dict[str, Any]:
        if not perms.allows("transfer_slips", "create"):
            raise PermissionDenied("Only the Replacement Manager sends edit requests (DEC-65)")
        gs = gs_service.lock_goods_slip(session, gs_id)
        gs_service.get_visible_goods_slip(session, user, perms, gs_id)
        if gs["status"] != PENDING:
            raise Conflict(
                "An edit request is sent for a goods slip pending its transfer slip",
                code="GS_NOT_PENDING_TRANSFER_SLIP",
                details={"status": gs["status"]},
            )
        if repo.open_edit_requests(session, [gs_id]):
            raise Conflict(
                "This goods slip already has an open edit request", code="EDIT_REQUEST_OPEN"
            )
        request_id = repo.insert_edit_request(session, gs_id=gs_id, reason=payload.reason)
        notifications.publish(
            session,
            "GS_EDIT_REQUESTED",
            user_ids=repo.super_admin_ids(session),
            title=f"{gs['gs_no']}: edit requested by {user.full_name}",
            body=payload.reason,
            entity_type=GS_ENTITY,
            entity_id=gs_id,
            gs_id=gs_id,
            priority="HIGH",
        )
        log.info("gs_edit_requested", gs_id=str(gs_id), request_id=str(request_id))
        return self._request_row(session, request_id)

    def resolve_edit(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        request_id: UUID,
        payload: ResolveEditRequestIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        with self._uow.transaction(user.id) as session:
            return run_idempotent(
                session,
                idem,
                user.id,
                lambda: (200, self._resolve_edit(session, user, perms, request_id, payload)),
            )

    def _resolve_edit(
        self,
        session: Session,
        user: CurrentUser,
        perms: EffectivePermissions,
        request_id: UUID,
        payload: ResolveEditRequestIn,
    ) -> dict[str, Any]:
        if not perms.allows("itemization", "configure"):
            raise PermissionDenied("Only Super Admin or Management resolve edit requests (DEC-65)")
        req = repo.get_edit_request(session, request_id, for_update=True)
        if not req:
            raise NotFound("Edit request not found", code="EDIT_REQUEST_NOT_FOUND")
        if req["status"] != "OPEN":
            raise Conflict("This edit request is already resolved", code="EDIT_REQUEST_RESOLVED")
        note = payload.note
        if payload.outcome == "REJECTED" and (note is None or len(note) < 3):
            raise Conflict(
                "Give a reason for rejecting the edit request",
                code="REJECT_REASON_REQUIRED",
                details={"note": ["Required"]},
            )
        if payload.outcome == "EDITED" and not repo.edited_since(
            session, req["gs_id"], req["requested_at"]
        ):
            raise Conflict(
                "Edit the goods slip first, then mark the request as edited",
                code="NO_EDIT_SINCE_REQUEST",
            )
        repo.resolve_edit_request(
            session, request_id, status=payload.outcome, by=user.id, note=note
        )
        verdict = "edited" if payload.outcome == "EDITED" else "rejected"
        notifications.publish(
            session,
            "GS_EDIT_REQUEST_RESOLVED",
            user_ids=[req["requested_by"]],
            title=f"{req['gs_no']}: edit request {verdict} by {user.full_name}",
            body=note,
            entity_type=GS_ENTITY,
            entity_id=req["gs_id"],
            gs_id=req["gs_id"],
        )
        log.info("gs_edit_request_resolved", request_id=str(request_id), outcome=payload.outcome)
        return self._request_row(session, request_id)
