"""Domain service for Department Routing, Receiving and Guard G-20 Reconciliation
(Change plan 2026-11-12 Phase 6; AMD-10, AMD-14, AMD-15; DEC-42, DEC-43; Guard G-20).

Commands (dispatch, receive) run in ONE transaction each, are idempotent on the
`Idempotency-Key` header (G-16, CLAUDE.md rule f) and move stock only through
`rms_private.rms_move_stock` (via `ledger_service.move_stock`), so any failure rolls back the
routing / receipt documents and every stock movement together.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from app.core.db import UnitOfWork
from app.core.errors import (
    Conflict,
    NotFound,
    PermissionDenied,
    SystemGuardViolation,
    ValidationFailed,
)
from app.core.idempotency import IdempotencyKey, IdempotentResult, run_idempotent
from app.core.security import CurrentUser
from app.modules.department_routing import repository as repo
from app.modules.department_routing.schemas import (
    CreateDepartmentReceiptIn,
    CreateDepartmentRoutingIn,
    DepartmentLegOut,
    DepartmentOutcomeHeadOut,
    DepartmentReceiptOut,
    DepartmentRoutingOut,
    GsReconciliationOut,
    ReceivingQueueItemOut,
    RmRoutingQueueItemOut,
)
from app.modules.inventory import ledger_service
from app.modules.notifications import service as notifications

log = structlog.get_logger("rms.dept_routing")

INTERMEDIATE_LOCATION = "INTERMEDIATE_STORE"
TECHNICIAN_LOCATION = "TECHNICIAN_BENCH"
SCRAP_LOCATION = "SCRAP_DISPOSED"
HELD_STATUS = "HELD_AT_INTERMEDIATE_STORE"
OPEN_ROUTING_STATUSES = ("DISPATCHED", "PARTIALLY_RECEIVED")

# DEC-42 (PROVISIONAL): the role that receives goods back from departments is configuration.
RECEIVING_ROLE_SETTING = "department.receiving_role"
_ROLE_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class DepartmentRoutingService:
    # --- queries ----------------------------------------------------------------------------------

    def list_outcome_heads(
        self, session: Session, *, active_only: bool = True
    ) -> list[DepartmentOutcomeHeadOut]:
        heads = repo.list_outcome_heads(session, active_only=active_only)
        return [DepartmentOutcomeHeadOut.model_validate(h) for h in heads]

    def get_rm_routing_queue(self, session: Session) -> list[RmRoutingQueueItemOut]:
        items = repo.list_rm_routing_queue(session)
        return [RmRoutingQueueItemOut.model_validate(it) for it in items]

    def get_gs_routing_state(self, session: Session, gs_id: UUID) -> dict[str, Any]:
        state = repo.get_gs_routing_state(session, gs_id)
        if not state:
            raise NotFound(f"Goods slip {gs_id} not found", code="GS_NOT_FOUND")
        return state

    def list_receiving_queue(self, session: Session) -> list[ReceivingQueueItemOut]:
        rows = repo.list_receiving_queue(session)
        return [ReceivingQueueItemOut.model_validate(r) for r in rows]

    def get_routing(self, session: Session, routing_id: UUID) -> DepartmentRoutingOut:
        r = repo.get_routing(session, routing_id)
        if not r:
            raise NotFound(f"Department routing {routing_id} not found", code="ROUTING_NOT_FOUND")
        return DepartmentRoutingOut.model_validate(r)

    def get_gs_reconciliation(self, session: Session, gs_id: UUID) -> GsReconciliationOut:
        """AMD-15 / Guard G-20: per-GS reconciliation panel showing where every piece is now."""
        recon = repo.get_gs_reconciliation(session, gs_id)
        return GsReconciliationOut.model_validate(recon)

    def get_gs_department_legs(self, session: Session, gs_id: UUID) -> list[DepartmentLegOut]:
        """GS timeline legs showing sent / received / pending per department."""
        legs = repo.get_gs_department_legs(session, gs_id)
        return [DepartmentLegOut.model_validate(leg) for leg in legs]

    # --- commands ---------------------------------------------------------------------------------

    def dispatch_department_routing(
        self,
        uow: UnitOfWork,
        *,
        actor: CurrentUser,
        payload: CreateDepartmentRoutingIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        """AMD-10: RM dispatches items to departments allowed by the product's resolved profile."""
        with uow.transaction(actor.id) as session:
            return run_idempotent(
                session, idem, actor.id, lambda: (200, self._dispatch(session, actor, payload))
            )

    def receive_department_routing(
        self,
        uow: UnitOfWork,
        *,
        actor: CurrentUser,
        payload: CreateDepartmentReceiptIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        """AMD-14 / DEC-42 / DEC-43: receive items back per routing line into outcome heads."""
        with uow.transaction(actor.id) as session:
            return run_idempotent(
                session, idem, actor.id, lambda: (200, self._receive(session, actor, payload))
            )

    # --- internals --------------------------------------------------------------------------------

    def _receiving_role(self, session: Session) -> str:
        """DEC-42: configured receiver role. A broken setting is reported, never guessed."""
        value = repo.get_setting(session, RECEIVING_ROLE_SETTING)
        if not isinstance(value, str) or not _ROLE_CODE.match(value):
            log.error(
                "dept_receiving_role_setting_invalid", key=RECEIVING_ROLE_SETTING, value=value
            )
            raise Conflict(
                f"System setting '{RECEIVING_ROLE_SETTING}' must be a role code (DEC-42)",
                code="SETTING_INVALID",
                details={"key": RECEIVING_ROLE_SETTING},
            )
        return value

    def _lot_for_item(self, session: Session, gs_item_id: UUID) -> UUID:
        lot_id = ledger_service.find_inward_lot(session, gs_item_id) or repo.find_any_lot_for_item(
            session, gs_item_id
        )
        if lot_id is None:
            # Never record a routing / receipt without its stock movement (rule f, G-20).
            raise ValidationFailed(
                f"No stock lot found for GS item {gs_item_id}; stock cannot be moved",
                code="LOT_NOT_FOUND",
                details={"gs_item_id": str(gs_item_id)},
            )
        return lot_id

    def _locations(self, session: Session, *codes: str) -> dict[str, UUID]:
        found: dict[str, UUID] = {}
        for code in codes:
            loc = ledger_service.get_location_by_code(session, code)
            if not loc:
                raise ValidationFailed(
                    f"Inventory location {code} is not configured", code="LOCATION_NOT_FOUND"
                )
            found[code] = loc["id"]
        return found

    def _dispatch(
        self, session: Session, actor: CurrentUser, payload: CreateDepartmentRoutingIn
    ) -> DepartmentRoutingOut:
        # 1. Lock the GS (G-20: concurrent dispatches / receipts for one GS are serialised).
        gs = repo.lock_goods_slip(session, payload.gs_id)
        if not gs:
            raise NotFound(f"Goods slip {payload.gs_id} not found", code="GS_NOT_FOUND")
        if gs["status"] != HELD_STATUS:
            raise ValidationFailed(
                f"Goods slip {gs['gs_no']} must be held at the intermediate store "
                f"(current: {gs['status']})",
                code="INVALID_GS_STATUS",
            )

        # 2. Destination department: an active DEPARTMENT field (AMD-10).
        dept = repo.get_department_field(session, payload.department_field_id)
        if not dept or not dept["is_active"]:
            raise ValidationFailed(
                f"Department field {payload.department_field_id} is not an active department",
                code="INVALID_DEPARTMENT",
            )
        dept_label = dept["label"]

        locs = self._locations(session, INTERMEDIATE_LOCATION, TECHNICIAN_LOCATION)
        receiving_role = self._receiving_role(session)

        # 3. Validate each line against the resolved profile and the store quantity (G-20).
        recon = repo.get_gs_reconciliation(session, payload.gs_id)
        in_store = {it["gs_item_id"]: it["in_store_qty"] for it in recon["items"]}
        lines_to_create: list[dict[str, Any]] = []
        for line in payload.lines:
            item = repo.get_gs_item(session, payload.gs_id, line.gs_item_id)
            if not item:
                raise ValidationFailed(
                    f"Item {line.gs_item_id} does not belong to Goods Slip {payload.gs_id}",
                    code="ITEM_NOT_IN_GS",
                )
            if not repo.is_department_allowed(session, item["product_id"], dept["id"]):
                raise ValidationFailed(
                    f"Department '{dept_label}' is not allowed by the resolved profile for "
                    f"item #{item['line_no']} ({item['item_name']})",
                    code="DEPARTMENT_NOT_ALLOWED",
                )
            avail = in_store.get(line.gs_item_id, 0)
            if avail < line.qty_sent:
                raise SystemGuardViolation(
                    "G-20",
                    f"G-20: Cannot dispatch {line.qty_sent} pcs of item #{item['line_no']}: "
                    f"only {avail} pcs available in intermediate store.",
                )
            in_store[line.gs_item_id] = avail - line.qty_sent  # duplicate lines in one payload
            lines_to_create.append(
                {
                    "gs_item_id": line.gs_item_id,
                    "source_bucket_field_id": line.source_bucket_field_id,
                    "lot_id": self._lot_for_item(session, line.gs_item_id),
                    "qty_sent": line.qty_sent,
                    "notes": line.notes,
                }
            )

        # 4. Routing document first, so stock movements reference it.
        routing_no = repo.next_number(session, "DEPT_ROUTING")
        routing = repo.create_department_routing(
            session,
            routing_no=routing_no,
            gs_id=payload.gs_id,
            department_field_id=dept["id"],
            department_code=dept["code"],
            department_label=dept_label,
            dispatched_by=actor.id,
            remarks=payload.remarks,
            lines=lines_to_create,
        )

        # 5. Stock: INTERMEDIATE_STORE -> TECHNICIAN_BENCH per line (rms_move_stock, same txn).
        for idx, line_data in enumerate(lines_to_create, start=1):
            ledger_service.move_stock(
                session,
                lot_id=line_data["lot_id"],
                from_location_id=locs[INTERMEDIATE_LOCATION],
                to_location_id=locs[TECHNICIAN_LOCATION],
                qty=line_data["qty_sent"],
                movement_type="ISSUE",
                reference_type="department_routings",
                reference_id=routing["id"],
                idempotency_key=f"dept-routing:{routing['id']}:{idx}",
                actor_id=actor.id,
                reason=f"Dispatched to department {dept_label}",
            )

        # 6. G-20 again after every write (the DB triggers check it too).
        repo.validate_reconciliation(session, payload.gs_id)

        notifications.publish(
            session,
            "DEPT_ROUTING_DISPATCHED",
            role_codes=[receiving_role],
            title=f"Department Routing Note {routing_no} dispatched to {dept_label}",
            body=(
                f"Goods slip {gs['gs_no']} has {len(lines_to_create)} lines dispatched to "
                f"{dept_label}."
            ),
            entity_type="department_routings",
            entity_id=routing["id"],
            gs_id=payload.gs_id,
        )
        log.info(
            "dept_routing_dispatched",
            routing_no=routing_no,
            gs_id=str(payload.gs_id),
            lines=len(lines_to_create),
        )
        return DepartmentRoutingOut.model_validate(routing)

    def _receive(
        self, session: Session, actor: CurrentUser, payload: CreateDepartmentReceiptIn
    ) -> DepartmentReceiptOut:
        # 1. DEC-42: only the configured receiving role (or Super Admin) books receipts.
        receiving_role = self._receiving_role(session)
        if not actor.is_super_admin and receiving_role not in actor.role_codes:
            raise PermissionDenied(
                f"Only the {receiving_role} role receives goods back from departments (DEC-42)",
                code="NOT_DEPARTMENT_RECEIVER",
                details={"required_role": receiving_role},
            )

        # 2. Lock routing and GS (G-20 serialisation), then re-read the routing with its lines.
        header = repo.lock_routing_header(session, payload.routing_id)
        if not header:
            raise NotFound(f"Routing {payload.routing_id} not found", code="ROUTING_NOT_FOUND")
        repo.lock_goods_slip(session, header["gs_id"])
        routing = repo.get_routing(session, payload.routing_id)
        if not routing:
            raise NotFound(f"Routing {payload.routing_id} not found", code="ROUTING_NOT_FOUND")
        if routing["status"] not in OPEN_ROUTING_STATUSES:
            raise ValidationFailed(
                f"Routing {routing['routing_no']} cannot be received (status: {routing['status']})",
                code="INVALID_ROUTING_STATUS",
            )

        locs = self._locations(session, INTERMEDIATE_LOCATION, TECHNICIAN_LOCATION, SCRAP_LOCATION)
        pending = {ln["id"]: ln["qty_sent"] - ln["qty_received"] for ln in routing["lines"]}
        line_items = {ln["id"]: ln for ln in routing["lines"]}

        # 3. Validate lines: belongs to routing, qty <= pending, outcome head active (DEC-43).
        lines_to_create: list[dict[str, Any]] = []
        for line in payload.lines:
            r_line = line_items.get(line.routing_line_id)
            if not r_line:
                raise ValidationFailed(
                    f"Routing line {line.routing_line_id} does not belong to routing "
                    f"{routing['routing_no']}",
                    code="LINE_NOT_IN_ROUTING",
                )
            if line.quantity > pending[line.routing_line_id]:
                raise ValidationFailed(
                    f"Quantity {line.quantity} exceeds pending quantity "
                    f"{pending[line.routing_line_id]} for item {r_line['item_name']}",
                    code="OVER_RECEIVE",
                )
            head = repo.get_outcome_head_by_id(session, line.outcome_head_id)
            if not head:
                raise ValidationFailed(
                    f"Outcome head {line.outcome_head_id} not found", code="OUTCOME_HEAD_NOT_FOUND"
                )
            if not head["is_active"]:
                raise ValidationFailed(
                    f"Outcome head {head['label']} is inactive", code="OUTCOME_HEAD_INACTIVE"
                )
            pending[line.routing_line_id] -= line.quantity  # duplicate lines in one payload
            lines_to_create.append(
                {
                    "routing_line_id": line.routing_line_id,
                    "gs_item_id": r_line["gs_item_id"],
                    "outcome_head_id": head["id"],
                    "outcome_code": head["code"],
                    "outcome_label": head["label"],
                    "is_wastage": head["is_wastage"],
                    "returns_to_routing": head["returns_to_routing"],
                    "quantity": line.quantity,
                    "remarks": line.remarks,
                    "lot_id": self._lot_for_item(session, r_line["gs_item_id"]),
                }
            )

        # 4. Receipt document first (DB triggers update qty_received / status and check G-20).
        receipt_no = repo.next_number(session, "DEPT_RECEIPT")
        receipt = repo.create_department_receipt(
            session,
            receipt_no=receipt_no,
            routing_id=payload.routing_id,
            received_by=actor.id,
            remarks=payload.remarks,
            lines=lines_to_create,
        )

        # 5. Stock per line: wastage -> SCRAP_DISPOSED, everything else back to INTERMEDIATE_STORE.
        for idx, ld in enumerate(lines_to_create, start=1):
            to_scrap = bool(ld["is_wastage"])
            ledger_service.move_stock(
                session,
                lot_id=ld["lot_id"],
                from_location_id=locs[TECHNICIAN_LOCATION],
                to_location_id=locs[SCRAP_LOCATION] if to_scrap else locs[INTERMEDIATE_LOCATION],
                qty=ld["quantity"],
                movement_type="DISPOSE" if to_scrap else "RECEIPT",
                reference_type="department_receipts",
                reference_id=receipt["id"],
                idempotency_key=f"dept-receipt:{receipt['id']}:{idx}",
                actor_id=actor.id,
                reason=(
                    f"Department outcome: {ld['outcome_label']}"
                    + (" (wastage)" if to_scrap else "")
                ),
            )

        repo.validate_reconciliation(session, routing["gs_id"])

        updated = repo.get_routing(session, payload.routing_id)
        if updated and updated["status"] == "COMPLETED":
            notifications.publish(
                session,
                "DEPT_ROUTING_COMPLETED",
                user_ids=[routing["dispatched_by"]],
                role_codes=["REPLACEMENT_MANAGER"],
                title=f"Department Routing Note {routing['routing_no']} completed",
                body=(
                    f"All items for routing {routing['routing_no']} "
                    f"({routing['department_label']}) have been received."
                ),
                entity_type="department_routings",
                entity_id=routing["id"],
                gs_id=routing["gs_id"],
            )
        log.info(
            "dept_routing_received",
            receipt_no=receipt_no,
            routing_no=routing["routing_no"],
            lines=len(lines_to_create),
        )
        return DepartmentReceiptOut.model_validate(receipt)


department_routing_service = DepartmentRoutingService()
