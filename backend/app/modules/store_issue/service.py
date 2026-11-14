"""Service layer for Step-6 Store Issues (P3-05).

Master plan references: BR-19, BR-31, DEC-21, G-04.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import UnitOfWork
from app.core.errors import NotFound, SystemGuardViolation, ValidationFailed
from app.core.permissions import EffectivePermissions
from app.core.security import CurrentUser
from app.modules.custody import service as custody_service
from app.modules.custody.schemas import AcceptIn, CountLineIn, TransferLineIn
from app.modules.notifications import service as notifications
from app.modules.store_issue import repository as repo
from app.modules.store_issue.schemas import (
    StoreIssueCandidateLotOut,
    StoreIssueCreateRequest,
    StoreIssueLineOut,
    StoreIssueOut,
    StoreIssuePrintLine,
    StoreIssuePrintResponse,
)

FUNCTIONAL_CLASSES = {"FUNCTIONAL_GOOD", "FUNCTIONAL_REPAIRED"}


class StoreIssueService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def _get_location_by_code(self, session: Session, code: str) -> dict[str, Any]:
        stmt = text(
            "select id, code, name, location_class "
            "from public.inventory_locations where code = :code"
        )
        row = session.execute(stmt, {"code": code}).mappings().first()
        if not row:
            raise NotFound(f"Location {code} not found")
        return dict(row)

    def _is_auto_acknowledge_enabled(self, session: Session) -> bool:
        stmt = text(
            "select value from public.system_settings where key = 'store_issue.auto_acknowledge'"
        )
        row = session.execute(stmt).scalar()
        if row is None:
            return True
        if isinstance(row, bool):
            return row
        if isinstance(row, str):
            return row.strip().lower() in ("true", "1", "yes")
        return True

    def get_candidate_lots(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> list[StoreIssueCandidateLotOut]:
        with self._uow.transaction(user.id) as session:
            rows = repo.get_candidate_lots_for_store_issue(session)
            return [
                StoreIssueCandidateLotOut(
                    lot_id=r["lot_id"],
                    stock_item_id=r["stock_item_id"],
                    product_id=r["product_id"],
                    product_code=r["product_code"],
                    product_name=r["product_name"],
                    condition_class=r["condition_class"],
                    available_qty=int(r["available_qty"]),
                    gs_id=r["gs_id"],
                    gs_no=r["gs_no"],
                )
                for r in rows
            ]

    def create_store_issue(
        self,
        payload: StoreIssueCreateRequest,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> StoreIssueOut:
        if not payload.lines:
            raise ValidationFailed("At least one line item is required for store issue")

        with self._uow.transaction(user.id) as session:
            from_loc = self._get_location_by_code(session, "INTERMEDIATE_STORE")
            to_loc = self._get_location_by_code(session, "MAIN_STORE")

            # Validate each line
            transfer_lines: list[TransferLineIn] = []
            for line in payload.lines:
                lot = repo.get_lot_with_balance(session, line.lot_id, "INTERMEDIATE_STORE")
                if not lot:
                    raise NotFound(f"Lot {line.lot_id} not found in Intermediate Store")

                # G-04 guard
                if lot["condition_class"] not in FUNCTIONAL_CLASSES:
                    raise SystemGuardViolation(
                        "G-04",
                        f"Only functional lots ({', '.join(sorted(FUNCTIONAL_CLASSES))}) "
                        f"can be issued to Main Store. "
                        f"Lot {line.lot_id} is {lot['condition_class']}.",
                    )

                if lot["balance_qty"] < line.qty:
                    raise ValidationFailed(
                        f"Insufficient stock for lot {line.lot_id}: "
                        f"available {lot['balance_qty']}, requested {line.qty}"
                    )

                transfer_lines.append(TransferLineIn(lot_id=line.lot_id, qty=line.qty))

            issue_no = session.execute(
                text("select rms_private.next_number('STORE_ISSUE')")
            ).scalar_one()

            auto_ack = self._is_auto_acknowledge_enabled(session)

            if auto_ack:
                transfer_id = custody_service.auto_transfer(
                    session,
                    actor=user,
                    from_location_code="INTERMEDIATE_STORE",
                    to_location_code="MAIN_STORE",
                    lines=transfer_lines,
                    purpose_code="STORE_ISSUE",
                    notes=f"Store Issue {issue_no}: {payload.notes or ''}",
                    accepted_on_behalf_of="MAIN_STORE",
                )
                status = "ACKNOWLEDGED"
                ack_at: Any = datetime.now(UTC)
                ack_by = user.id
            else:
                transfer_id = custody_service.initiate_transfer(
                    session,
                    actor=user,
                    from_location_code="INTERMEDIATE_STORE",
                    to_location_code="MAIN_STORE",
                    lines=transfer_lines,
                    purpose_code="STORE_ISSUE",
                    notes=f"Store Issue {issue_no}: {payload.notes or ''}",
                )
                status = "ISSUED"
                ack_at = None
                ack_by = None

            issue_id = repo.insert_store_issue(
                session,
                issue_no=issue_no,
                issue_type_code=payload.issue_type_code,
                from_location_id=from_loc["id"],
                to_location_id=to_loc["id"],
                status=status,
                notes=payload.notes,
                created_by=user.id,
                transfer_id=transfer_id,
                acknowledged_at=ack_at,
                acknowledged_by=ack_by,
            )

            for line in payload.lines:
                repo.insert_store_issue_line(
                    session,
                    issue_id=issue_id,
                    lot_id=line.lot_id,
                    qty=line.qty,
                )

            # P4-03: STORE_ISSUED (BR-31; rule seeded inactive). Context: the Main Store role,
            # which acknowledges the inward entry.
            notifications.publish(
                session,
                "STORE_ISSUED",
                role_codes=["MAIN_STORE"],
                title=f"{issue_no}: {sum(ln.qty for ln in payload.lines)} pc(s) issued to "
                "Main Store",
                body=f"{len(payload.lines)} lot(s); status {status}; issued by {user.full_name}.",
                entity_type="store_issue",
                entity_id=issue_id,
                data={"issue_no": str(issue_no)},
            )

        return self.get_store_issue(issue_id, user, perms)

    def get_store_issue(
        self,
        issue_id: UUID,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> StoreIssueOut:
        with self._uow.transaction(user.id) as session:
            issue = repo.get_store_issue(session, issue_id)
            if not issue:
                raise NotFound(f"Store issue {issue_id} not found")

            lines = repo.get_store_issue_lines(session, issue_id)
            line_models = [
                StoreIssueLineOut(
                    id=ln["id"],
                    issue_id=ln["issue_id"],
                    lot_id=ln["lot_id"],
                    qty=ln["qty"],
                    product_code=ln["product_code"],
                    product_name=ln["product_name"],
                    condition_class=ln["condition_class"],
                    gs_id=ln["gs_id"],
                    gs_no=ln["gs_no"],
                )
                for ln in lines
            ]
            total_qty = sum(ln.qty for ln in line_models)

            return StoreIssueOut(
                id=issue["id"],
                issue_no=issue["issue_no"],
                issue_type_code=issue["issue_type_code"],
                from_location_id=issue["from_location_id"],
                from_location_name=issue["from_location_name"],
                to_location_id=issue["to_location_id"],
                to_location_name=issue["to_location_name"],
                status=issue["status"],
                custody_transfer_id=issue["transfer_id"],
                notes=issue["notes"],
                created_at=issue["created_at"],
                created_by=issue["created_by"],
                created_by_name=issue["created_by_name"],
                acknowledged_at=issue["acknowledged_at"],
                acknowledged_by=issue["acknowledged_by"],
                acknowledged_by_name=issue["acknowledged_by_name"],
                total_qty=total_qty,
                lines=line_models,
            )

    def list_store_issues(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> list[StoreIssueOut]:
        with self._uow.transaction(user.id) as session:
            rows = repo.list_store_issues(session, status=status, limit=limit, offset=offset)
            results: list[StoreIssueOut] = []
            for r in rows:
                lines = repo.get_store_issue_lines(session, r["id"])
                line_models = [
                    StoreIssueLineOut(
                        id=ln["id"],
                        issue_id=ln["issue_id"],
                        lot_id=ln["lot_id"],
                        qty=ln["qty"],
                        product_code=ln["product_code"],
                        product_name=ln["product_name"],
                        condition_class=ln["condition_class"],
                        gs_id=ln["gs_id"],
                        gs_no=ln["gs_no"],
                    )
                    for ln in lines
                ]
                results.append(
                    StoreIssueOut(
                        id=r["id"],
                        issue_no=r["issue_no"],
                        issue_type_code=r["issue_type_code"],
                        from_location_id=r["from_location_id"],
                        from_location_name=r["from_location_name"],
                        to_location_id=r["to_location_id"],
                        to_location_name=r["to_location_name"],
                        status=r["status"],
                        custody_transfer_id=r["transfer_id"],
                        notes=r["notes"],
                        created_at=r["created_at"],
                        created_by=r["created_by"],
                        created_by_name=r["created_by_name"],
                        acknowledged_at=r["acknowledged_at"],
                        acknowledged_by=r["acknowledged_by"],
                        acknowledged_by_name=r["acknowledged_by_name"],
                        total_qty=int(r["total_qty"]),
                        lines=line_models,
                    )
                )
            return results

    def acknowledge_store_issue(
        self,
        issue_id: UUID,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> StoreIssueOut:
        with self._uow.transaction(user.id) as session:
            issue = repo.get_store_issue(session, issue_id)
            if not issue:
                raise NotFound(f"Store issue {issue_id} not found")
            if issue["status"] == "ACKNOWLEDGED":
                return self.get_store_issue(issue_id, user, perms)

            if issue["transfer_id"]:
                # DEC-21 manual acknowledgement (auto-ack off): the Main Store accepts the issued
                # quantities of every line — phase 2 of the G-09 custody transfer.
                lines = repo.get_store_issue_lines(session, issue_id)
                custody_service.accept_transfer(
                    session,
                    user=user,
                    perms=perms,
                    transfer_id=issue["transfer_id"],
                    payload=AcceptIn(
                        lines=[
                            CountLineIn(lot_id=ln["lot_id"], qty_counted=int(ln["qty"]))
                            for ln in lines
                        ],
                        acceptance_code="ACCEPTED_VERIFIED",
                        notes=f"Main Store acknowledgement of {issue['issue_no']}",
                    ),
                )

            repo.acknowledge_store_issue(session, issue_id, user.id)

        return self.get_store_issue(issue_id, user, perms)

    def get_print_data(
        self,
        issue_id: UUID,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> StoreIssuePrintResponse:
        with self._uow.transaction(user.id) as session:
            issue = repo.get_store_issue(session, issue_id)
            if not issue:
                raise NotFound(f"Store issue {issue_id} not found")

            lines = repo.get_store_issue_lines(session, issue_id)
            print_lines = [
                StoreIssuePrintLine(
                    line_no=idx + 1,
                    product_code=ln["product_code"],
                    product_name=ln["product_name"],
                    condition_class=ln["condition_class"],
                    gs_no=ln["gs_no"],
                    qty=ln["qty"],
                )
                for idx, ln in enumerate(lines)
            ]
            total_qty = sum(ln.qty for ln in print_lines)

            signature_blocks = [
                {
                    "label": "Issued By",
                    "name": issue["created_by_name"],
                    "role": "Intermediate Store (Sahil)",
                },
                {
                    "label": "Received & Acknowledged By",
                    "name": issue["acknowledged_by_name"] or "Pending",
                    "role": "Main Store Manager",
                },
            ]

            return StoreIssuePrintResponse(
                issue_no=issue["issue_no"],
                issue_date=issue["created_at"].strftime("%d/%m/%Y %H:%M"),
                issue_type_code=issue["issue_type_code"],
                from_location=issue["from_location_name"],
                to_location=issue["to_location_name"],
                issued_by_name=issue["created_by_name"],
                acknowledged_by_name=issue["acknowledged_by_name"],
                status=issue["status"],
                total_qty=total_qty,
                notes=issue["notes"],
                lines=print_lines,
                signature_blocks=signature_blocks,
            )
