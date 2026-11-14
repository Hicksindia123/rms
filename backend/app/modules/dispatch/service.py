"""Service layer for Replacement Dispatch (P3-05).

Master plan references: BR-19, BR-31, BR-32, DEC-26, DEC-33, §8.6.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import UnitOfWork
from app.core.errors import NotFound, SystemGuardViolation, ValidationFailed
from app.core.permissions import EffectivePermissions
from app.core.security import CurrentUser
from app.modules.closure import service as closure_service
from app.modules.dispatch import repository as repo
from app.modules.dispatch.schemas import (
    DispatchCandidateLotOut,
    DispatchQueueItemOut,
    ReplacementDispatchCreateRequest,
    ReplacementDispatchLineOut,
    ReplacementDispatchOut,
)
from app.modules.inventory import ledger_service
from app.modules.notifications import service as notif_service

VALID_DISPATCH_TYPES = {"SEND_NEW", "SEND_REPAIRED"}


class ReplacementDispatchService:
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

    def get_dispatch_queue(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> list[DispatchQueueItemOut]:
        with self._uow.transaction(user.id) as session:
            rows = repo.get_dispatch_queue(session)
            return [
                DispatchQueueItemOut(
                    gs_id=r["gs_id"],
                    gs_no=r["gs_no"],
                    party_id=r["party_id"],
                    party_name=r["party_name"],
                    gs_item_id=r["gs_item_id"],
                    line_no=r["line_no"],
                    product_id=r["product_id"],
                    product_code=r["product_code"],
                    product_name=r["product_name"],
                    action_code=r["action_code"],
                    planned_qty=int(r["planned_qty"]),
                    dispatched_qty=int(r["dispatched_qty"]),
                    pending_qty=int(r["pending_qty"]),
                    available_repaired_qty=int(r["available_repaired_qty"]),
                )
                for r in rows
            ]

    def get_candidate_lots(
        self,
        product_id: UUID | None = None,
        gs_item_id: UUID | None = None,
        user: CurrentUser | None = None,
        perms: EffectivePermissions | None = None,
    ) -> list[DispatchCandidateLotOut]:
        with self._uow.transaction(user.id if user else None) as session:
            rows = repo.get_candidate_lots_for_dispatch(
                session, product_id=product_id, gs_item_id=gs_item_id
            )
            return [
                DispatchCandidateLotOut(
                    lot_id=r["lot_id"],
                    stock_item_id=r["stock_item_id"],
                    product_id=r["product_id"],
                    product_code=r["product_code"],
                    product_name=r["product_name"],
                    location_id=r["location_id"],
                    location_code=r["location_code"],
                    condition_class=r["condition_class"],
                    available_qty=int(r["available_qty"]),
                    gs_id=r["gs_id"],
                    gs_no=r["gs_no"],
                )
                for r in rows
            ]

    def create_dispatch(
        self,
        payload: ReplacementDispatchCreateRequest,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> ReplacementDispatchOut:
        if payload.dispatch_type not in VALID_DISPATCH_TYPES:
            raise ValidationFailed(
                f"Invalid dispatch_type {payload.dispatch_type}; must be SEND_NEW or SEND_REPAIRED"
            )
        if not payload.lines:
            raise ValidationFailed("At least one line item is required for dispatch")

        with self._uow.transaction(user.id) as session:
            # Check goods slip exists
            gs_stmt = text("select id, gs_no, status from public.goods_slips where id = :id")
            gs = session.execute(gs_stmt, {"id": payload.gs_id}).mappings().first()
            if not gs:
                raise NotFound(f"Goods slip {payload.gs_id} not found")
            # AMD-19 / G-22: on the A/c Actions flow goods ship only against the Dispatch Slip
            # (the DB trigger replacement_dispatches_amd_flow_guard enforces the same).
            if repo.is_on_final_action_flow(session, payload.gs_id):
                raise SystemGuardViolation(
                    "G-22",
                    f"G-22: goods slip {gs['gs_no']} is on the A/c Actions flow; dispatch it "
                    "against its Dispatch Slip (AMD-19)",
                )

            dispatched_loc = self._get_location_by_code(session, "DISPATCHED")

            # Validate each line against RM actions
            validated_movements: list[dict[str, Any]] = []
            for line in payload.lines:
                if line.qty <= 0:
                    raise ValidationFailed("Line quantity must be greater than zero")

                actions = repo.get_item_actions_for_dispatch(session, line.gs_item_id)
                action_map = {a["action_code"]: a["qty"] for a in actions}

                planned_qty = action_map.get(payload.dispatch_type, 0)
                already_disp = repo.get_already_dispatched_qty_for_item(
                    session, line.gs_item_id, payload.dispatch_type
                )
                available_to_dispatch = max(0, planned_qty - already_disp)

                # DEC-33: lines in NOT_ALLOWED or over-dispatch require override_reason
                over = available_to_dispatch == 0 or line.qty > available_to_dispatch
                if over and not (payload.override_reason and payload.override_reason.strip()):
                    raise ValidationFailed(
                        f"DEC-33: Dispatch quantity {line.qty} exceeds planned "
                        f"{available_to_dispatch} (planned: {planned_qty}, already dispatched: "
                        f"{already_disp}) for item {line.gs_item_id}. "
                        "RM override_reason is required."
                    )

                if payload.dispatch_type == "SEND_REPAIRED":
                    if not line.lot_id:
                        raise ValidationFailed("lot_id is required for SEND_REPAIRED dispatches")

                    lot = repo.get_lot_for_dispatch(session, line.lot_id)
                    if not lot:
                        raise NotFound(f"Lot {line.lot_id} not found in Intermediate or Main Store")

                    if lot["condition_class"] != "FUNCTIONAL_REPAIRED":
                        raise SystemGuardViolation(
                            "G-04",
                            "Only FUNCTIONAL_REPAIRED lots can be dispatched as repaired "
                            f"replacements (lot is {lot['condition_class']})",
                        )

                    if lot["balance_qty"] < line.qty:
                        raise ValidationFailed(
                            f"Insufficient stock for lot {line.lot_id}: "
                            f"available {lot['balance_qty']}, requested {line.qty}"
                        )

                    validated_movements.append(
                        {
                            "lot_id": line.lot_id,
                            "from_location_id": lot["location_id"],
                            "to_location_id": dispatched_loc["id"],
                            "qty": line.qty,
                        }
                    )
                else:
                    # SEND_NEW (DEC-26)
                    if line.lot_id is not None:
                        raise ValidationFailed(
                            "DEC-26: SEND_NEW dispatches are sourced outside the RMS "
                            "returned-goods ledger; lot_id must be null"
                        )

            dispatch_no = session.execute(
                text("select rms_private.next_number('DISPATCH')")
            ).scalar_one()

            doc_date = None
            if payload.ref_doc_date:
                try:
                    doc_date = date.fromisoformat(payload.ref_doc_date)
                except ValueError:
                    doc_date = None

            dispatch_id = repo.insert_dispatch(
                session,
                dispatch_no=dispatch_no,
                gs_id=payload.gs_id,
                dispatch_type=payload.dispatch_type,
                transporter=payload.transporter,
                docket_no=payload.docket_no,
                vehicle_no=payload.vehicle_no,
                ref_doc_no=payload.ref_doc_no,
                ref_doc_date=doc_date,
                override_reason=payload.override_reason,
                notes=payload.notes,
                dispatched_by=user.id,
            )

            # Insert lines and perform movements
            for line in payload.lines:
                repo.insert_dispatch_line(
                    session,
                    dispatch_id=dispatch_id,
                    gs_item_id=line.gs_item_id,
                    lot_id=line.lot_id,
                    qty=line.qty,
                )

            for idx, m in enumerate(validated_movements):
                ledger_service.move_stock(
                    session,
                    lot_id=m["lot_id"],
                    from_location_id=m["from_location_id"],
                    to_location_id=m["to_location_id"],
                    qty=m["qty"],
                    movement_type="DISPATCH",
                    reference_type="REPLACEMENT_DISPATCH",
                    reference_id=dispatch_id,
                    idempotency_key=f"dispatch:{dispatch_id}:{m['lot_id']}:{idx}",
                    actor_id=user.id,
                    reason=f"Replacement dispatch {dispatch_no}",
                )

            # P3-07 / §6.5: a completed replacement dispatch can finish the commercial work.
            closure_service.sync_status(session, payload.gs_id, user.id)

            # Notify RM
            notif_service.publish(
                session,
                "DISPATCHED",
                role_codes=["REPLACEMENT_MANAGER"],
                notification_type="DISPATCH_RECORDED",
                title=f"Replacement Dispatched: {dispatch_no}",
                body=(
                    f"Dispatched {payload.dispatch_type} for GS {gs['gs_no']} "
                    f"via {payload.transporter}."
                ),
                entity_type="replacement_dispatches",
                entity_id=dispatch_id,
                gs_id=payload.gs_id,
                data={"gs_no": gs["gs_no"]},
                priority="NORMAL",
            )

        return self.get_dispatch(dispatch_id, user, perms)

    def get_dispatch(
        self,
        dispatch_id: UUID,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> ReplacementDispatchOut:
        with self._uow.transaction(user.id) as session:
            disp = repo.get_dispatch(session, dispatch_id)
            if not disp:
                raise NotFound(f"Replacement dispatch {dispatch_id} not found")

            lines = repo.get_dispatch_lines(session, dispatch_id)
            line_models = [
                ReplacementDispatchLineOut(
                    id=ln["id"],
                    dispatch_id=ln["dispatch_id"],
                    gs_item_id=ln["gs_item_id"],
                    lot_id=ln["lot_id"],
                    qty=ln["qty"],
                    product_code=ln["product_code"],
                    product_name=ln["product_name"],
                    condition_class=ln["condition_class"],
                )
                for ln in lines
            ]
            total_qty = sum(ln.qty for ln in line_models)

            return ReplacementDispatchOut(
                id=disp["id"],
                dispatch_no=disp["dispatch_no"],
                gs_id=disp["gs_id"],
                gs_no=disp["gs_no"],
                party_name=disp["party_name"],
                dispatch_type=disp["dispatch_type"],
                transporter=disp["transporter"],
                docket_no=disp["docket_no"],
                vehicle_no=disp["vehicle_no"],
                ref_doc_no=disp["ref_doc_no"],
                ref_doc_date=str(disp["ref_doc_date"]) if disp["ref_doc_date"] else None,
                status=disp["status"],
                dispatched_at=disp["dispatched_at"],
                dispatched_by=disp["dispatched_by"],
                dispatched_by_name=disp["dispatched_by_name"],
                override_reason=disp["override_reason"],
                notes=disp["notes"],
                total_qty=total_qty,
                lines=line_models,
            )

    def list_dispatches(
        self,
        *,
        gs_id: UUID | None = None,
        dispatch_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> list[ReplacementDispatchOut]:
        with self._uow.transaction(user.id) as session:
            rows = repo.list_dispatches(
                session, gs_id=gs_id, dispatch_type=dispatch_type, limit=limit, offset=offset
            )
            results: list[ReplacementDispatchOut] = []
            for r in rows:
                lines = repo.get_dispatch_lines(session, r["id"])
                line_models = [
                    ReplacementDispatchLineOut(
                        id=ln["id"],
                        dispatch_id=ln["dispatch_id"],
                        gs_item_id=ln["gs_item_id"],
                        lot_id=ln["lot_id"],
                        qty=ln["qty"],
                        product_code=ln["product_code"],
                        product_name=ln["product_name"],
                        condition_class=ln["condition_class"],
                    )
                    for ln in lines
                ]
                results.append(
                    ReplacementDispatchOut(
                        id=r["id"],
                        dispatch_no=r["dispatch_no"],
                        gs_id=r["gs_id"],
                        gs_no=r["gs_no"],
                        party_name=r["party_name"],
                        dispatch_type=r["dispatch_type"],
                        transporter=r["transporter"],
                        docket_no=r["docket_no"],
                        vehicle_no=r["vehicle_no"],
                        ref_doc_no=r["ref_doc_no"],
                        ref_doc_date=str(r["ref_doc_date"]) if r["ref_doc_date"] else None,
                        status=r["status"],
                        dispatched_at=r["dispatched_at"],
                        dispatched_by=r["dispatched_by"],
                        dispatched_by_name=r["dispatched_by_name"],
                        override_reason=r["override_reason"],
                        notes=r["notes"],
                        total_qty=int(r["total_qty"]),
                        lines=line_models,
                    )
                )
            return results
