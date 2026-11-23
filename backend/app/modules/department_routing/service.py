"""Domain service for Department Routing, Receiving and Guard G-20 Reconciliation
(Change plan 2026-11-12 Phase 6; AMD-10, AMD-14, AMD-15; DEC-42, DEC-43; Guard G-20;
gap plan G2 / DEC-55: RM routing plan -> Store Manager issue).

Step 7 (DEC-55): the RM plans per item + condition (no stock move); the Intermediate Store
Manager issues the planned lines to one department at a time (DIN), moving stock from the
Intermediate Store to that department's own location. STORE ("no work") lines are never issued.

Step 8 (DEC-56, gap plan G3): the receiving role records per line the qty, the outcome and the
condition the pieces came back in; the item's current condition split is updated in the DB
(counting split kept as history) and planning works from the current split. Stock goes where the
outcome head says (Mercury Extracted -> Non-Functional Store, wastage -> scrap, otherwise back to
the Intermediate Store with no Store Manager acceptance).

Commands (plan, issue, receive) run in ONE transaction each, are idempotent on the
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
    CreateRoutingPlanIn,
    DepartmentLegOut,
    DepartmentOutcomeHeadOut,
    DepartmentReceiptLineIn,
    DepartmentReceiptOut,
    DepartmentRoutingOut,
    GsReconciliationOut,
    IssueQueueGroupOut,
    ReceivingQueueItemOut,
    RmRoutingQueueItemOut,
    RoutingPlanLineOut,
    RoutingPlanOut,
    StoreDinOut,
    StoreIssueIn,
    StoreProgressOut,
    StoreReceiptIn,
    StoreReceiptResultOut,
    StoreReceivingDinOut,
    StoreReceivingGsOut,
    StoreRefOut,
    StoreRoutingConditionOut,
    StoreRoutingDepartmentOut,
    StoreRoutingGsOut,
    StoreRoutingIn,
    StoreRoutingItemOut,
    StoreRoutingQueueRowOut,
    StoreRoutingResultOut,
)
from app.modules.goods_slips import service as gs_service
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
# DEC-55 Q16: department code -> its own inventory location code (configuration).
LOCATION_BY_CODE_SETTING = "department.location_by_code"
_ROLE_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")

# DEC-67 (Phase P7): a store routes while the GS is on its stores (Q29: after ITS acknowledgement).
STORE_ROUTING_STATUSES = ("TRANSFER_SLIP_GENERATED", "STORE_ACKNOWLEDGED", "STORE_PROCESSING")
PROCESSING_STATUS = "STORE_PROCESSING"
ROUTING_TASK_STEP = "STORE_ROUTING"  # DEC-66: task per GS and store, opened at acknowledgement
ANALYSIS_TASK_STEP = "STORE_ANALYSIS"  # DEC-69: task per GS and store while ready for analysis
READY_FOR_ANALYSIS = "READY_FOR_ANALYSIS"
ROUTING_PENDING = "ROUTING_PENDING"


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

    def get_plan_lines(self, session: Session, gs_id: UUID) -> list[RoutingPlanLineOut]:
        return [
            RoutingPlanLineOut.model_validate(r) for r in repo.list_plan_lines(session, gs_id=gs_id)
        ]

    def planned_qty_by_item(self, session: Session, gs_id: UUID) -> dict[UUID, int]:
        """DEC-55: pieces planned for a department but not issued yet, per GS item (used by the
        final actions finalise check, G-21)."""
        return repo.planned_qty_by_item(session, gs_id)

    def list_issue_queue(self, session: Session) -> list[IssueQueueGroupOut]:
        """DEC-55: planned lines waiting for the Store issue, per GS + department."""
        return [IssueQueueGroupOut.model_validate(g) for g in repo.list_issue_queue(session)]

    def plan_routing(
        self,
        uow: UnitOfWork,
        *,
        actor: CurrentUser,
        payload: CreateRoutingPlanIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        """DEC-55: RM plans the routing per item + condition. No stock moves (Q5: the Store
        Manager issues). STORE lines are "no work" and need no issue (Q4)."""
        with uow.transaction(actor.id) as session:
            return run_idempotent(
                session, idem, actor.id, lambda: (200, self._plan(session, actor, payload))
            )

    def cancel_plan_line(
        self, uow: UnitOfWork, *, actor: CurrentUser, plan_line_id: UUID, reason: str
    ) -> RoutingPlanLineOut:
        """DEC-55: the RM withdraws a plan line that the store has not issued yet."""
        with uow.transaction(actor.id) as session:
            lines = repo.list_plan_lines(session, ids=[plan_line_id], for_update=True)
            if not lines:
                raise NotFound(
                    f"Routing plan line {plan_line_id} not found", code="PLAN_LINE_NOT_FOUND"
                )
            line = lines[0]
            repo.lock_goods_slip(session, line["gs_id"])
            if line["status"] not in ("PLANNED", "NO_WORK"):
                raise Conflict(
                    f"Plan line is {line['status']}; only planned or no-work lines can be "
                    "cancelled",
                    code="PLAN_LINE_NOT_OPEN",
                )
            repo.cancel_plan_line(
                session, plan_line_id=plan_line_id, cancelled_by=actor.id, reason=reason.strip()
            )
            log.info(
                "dept_plan_line_cancelled", plan_line_id=str(plan_line_id), gs_id=str(line["gs_id"])
            )
            return RoutingPlanLineOut.model_validate(
                repo.list_plan_lines(session, ids=[plan_line_id])[0]
            )

    def issue_to_department(
        self,
        uow: UnitOfWork,
        *,
        actor: CurrentUser,
        payload: StoreIssueIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        """DEC-55: the Store Manager issues planned lines to one department (DIN). Stock moves
        Intermediate Store -> the department's location through rms_move_stock (G-16, rule f)."""
        with uow.transaction(actor.id) as session:
            return run_idempotent(
                session, idem, actor.id, lambda: (200, self._issue(session, actor, payload))
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

    @staticmethod
    def _check_condition_after_work(
        r_line: dict[str, Any], condition_field_id: UUID | None
    ) -> None:
        """DEC-56 Q7: pieces routed from a condition come back with a condition from the
        product's categorisation list; pieces routed without one are received without one."""
        if r_line["source_bucket_field_id"] is None:
            if condition_field_id is not None:
                raise ValidationFailed(
                    f"Item #{r_line['line_no']} was routed without a condition; "
                    "do not record a condition after work",
                    code="CONDITION_NOT_APPLICABLE",
                )
            return
        if condition_field_id is None:
            raise ValidationFailed(
                f"Record the condition item #{r_line['line_no']} ({r_line['item_name']}) "
                "came back in (DEC-56)",
                code="CONDITION_REQUIRED",
            )
        allowed = {o["field_id"] for o in r_line.get("condition_options", [])}
        if condition_field_id not in allowed:
            raise ValidationFailed(
                f"The condition is not in the categorisation list of item #{r_line['line_no']}",
                code="CONDITION_NOT_ALLOWED",
            )

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

    def _department_location(self, session: Session, dept_code: str) -> UUID:
        """DEC-55 Q16: the department's own stock location, from `department.location_by_code`.
        A work department without a configured, active location is reported, never guessed."""
        mapping = repo.get_setting(session, LOCATION_BY_CODE_SETTING)
        loc_code = mapping.get(dept_code) if isinstance(mapping, dict) else None
        if not isinstance(loc_code, str) or not loc_code:
            log.error(
                "dept_location_setting_missing",
                key=LOCATION_BY_CODE_SETTING,
                department_code=dept_code,
            )
            raise Conflict(
                f"No stock location is configured for department {dept_code} "
                f"(system setting '{LOCATION_BY_CODE_SETTING}', DEC-55)",
                code="SETTING_INVALID",
                details={"key": LOCATION_BY_CODE_SETTING, "department_code": dept_code},
            )
        loc = ledger_service.get_location_by_code(session, loc_code)
        if not loc or not loc["is_active"]:
            log.error("dept_location_not_found", location_code=loc_code, department_code=dept_code)
            raise Conflict(
                f"Inventory location {loc_code} for department {dept_code} is not configured",
                code="LOCATION_NOT_FOUND",
                details={"location_code": loc_code, "department_code": dept_code},
            )
        return UUID(str(loc["id"]))

    def _require_held(self, session: Session, gs_id: UUID) -> dict[str, Any]:
        gs = repo.lock_goods_slip(session, gs_id)
        if not gs:
            raise NotFound(f"Goods slip {gs_id} not found", code="GS_NOT_FOUND")
        if gs["status"] != HELD_STATUS:
            raise ValidationFailed(
                f"Goods slip {gs['gs_no']} must be held at the intermediate store "
                f"(current: {gs['status']})",
                code="INVALID_GS_STATUS",
            )
        return gs

    def _plan(
        self, session: Session, actor: CurrentUser, payload: CreateRoutingPlanIn
    ) -> RoutingPlanOut:
        # 1. Lock the GS (G-20: plans / issues / receipts for one GS are serialised).
        gs = self._require_held(session, payload.gs_id)
        if repo.has_current_ac_slip(session, payload.gs_id):
            raise SystemGuardViolation(
                "G-21",
                f"G-21: final actions of {gs['gs_no']} are finalised; revise them before "
                "planning new routing",
            )

        recon = repo.get_gs_reconciliation(session, payload.gs_id)
        unplanned = {it["gs_item_id"]: it["unplanned_qty"] for it in recon["items"]}
        bucket_free: dict[tuple[UUID, UUID | None], int] = {}
        dept_cache: dict[UUID, dict[str, Any]] = {}
        planned_work = 0

        # 2. Validate every line before writing anything (Q6: per item + condition).
        for line in payload.lines:
            item = repo.get_gs_item(session, payload.gs_id, line.gs_item_id)
            if not item:
                raise ValidationFailed(
                    f"Item {line.gs_item_id} does not belong to Goods Slip {gs['gs_no']}",
                    code="ITEM_NOT_IN_GS",
                )
            dept = dept_cache.get(line.department_field_id)
            if dept is None:
                found = repo.get_department_field(session, line.department_field_id)
                if not found or not found["is_active"]:
                    raise ValidationFailed(
                        f"Department field {line.department_field_id} is not an active department",
                        code="INVALID_DEPARTMENT",
                    )
                dept = {**found, "no_work": repo.department_is_no_work(session, found["code"])}
                if not dept["no_work"]:
                    # Fail now, not at the Store issue: a work department needs its location.
                    self._department_location(session, found["code"])
                dept_cache[line.department_field_id] = dept
            if not repo.is_department_allowed(session, item["product_id"], dept["id"]):
                raise ValidationFailed(
                    f"Department '{dept['label']}' is not allowed by the resolved profile for "
                    f"item #{item['line_no']} ({item['item_name']})",
                    code="DEPARTMENT_NOT_ALLOWED",
                )

            # DEC-56: plan from the item's CURRENT condition split (G-20 checks it in the DB too).
            conditions = {
                c["field_id"]: c for c in repo.get_item_condition_balances(session, line.gs_item_id)
            }
            if conditions and line.source_bucket_field_id is None:
                raise ValidationFailed(
                    f"Item #{item['line_no']} is split by condition; choose the condition "
                    "for each routing line (DEC-55)",
                    code="CONDITION_REQUIRED",
                )
            if (
                line.source_bucket_field_id is not None
                and line.source_bucket_field_id not in conditions
            ):
                raise ValidationFailed(
                    f"The chosen condition is not part of item #{item['line_no']}'s split",
                    code="CONDITION_NOT_IN_ITEM",
                )

            key = (line.gs_item_id, line.source_bucket_field_id)
            if key not in bucket_free and line.source_bucket_field_id is not None:
                bucket_free[key] = conditions[line.source_bucket_field_id]["free_qty"]
            if line.source_bucket_field_id is not None and bucket_free[key] < line.qty:
                cond = conditions[line.source_bucket_field_id]
                raise SystemGuardViolation(
                    "G-20",
                    f"G-20: item #{item['line_no']} condition '{cond['field_label']}': only "
                    f"{max(bucket_free[key], 0)} pc(s) left to route, {line.qty} requested.",
                )
            avail = unplanned.get(line.gs_item_id, 0)
            if avail < line.qty:
                raise SystemGuardViolation(
                    "G-20",
                    f"G-20: Cannot plan {line.qty} pcs of item #{item['line_no']}: only "
                    f"{avail} pcs in the intermediate store are not yet planned.",
                )
            unplanned[line.gs_item_id] = avail - line.qty  # several lines in one payload
            if line.source_bucket_field_id is not None:
                bucket_free[key] -= line.qty
            if not dept["no_work"]:
                planned_work += line.qty

        # 3. Write the plan (the DB guard snapshots labels and sets PLANNED / NO_WORK).
        for line in payload.lines:
            repo.insert_plan_line(
                session,
                gs_id=payload.gs_id,
                gs_item_id=line.gs_item_id,
                source_bucket_field_id=line.source_bucket_field_id,
                department_field_id=line.department_field_id,
                qty=line.qty,
                notes=line.notes,
                planned_by=actor.id,
            )
        repo.validate_reconciliation(session, payload.gs_id)

        # 4. Q5: the Store Manager is alerted to issue (recipients from the notification rule).
        if planned_work:
            depts = sorted({d["label"] for d in dept_cache.values() if not d["no_work"]})
            notifications.publish(
                session,
                "DEPT_ROUTING_PLANNED",
                title=f"Goods slip {gs['gs_no']}: {planned_work} pc(s) to issue to departments",
                body=f"The Replacement Manager planned routing to {', '.join(depts)}.",
                entity_type="goods_slips",
                entity_id=payload.gs_id,
                gs_id=payload.gs_id,
            )
        log.info(
            "dept_routing_planned",
            gs_id=str(payload.gs_id),
            lines=len(payload.lines),
            planned_work_qty=planned_work,
        )
        return RoutingPlanOut(
            gs_id=payload.gs_id,
            lines=[
                RoutingPlanLineOut.model_validate(r)
                for r in repo.list_plan_lines(session, gs_id=payload.gs_id)
            ],
        )

    def _issue(
        self, session: Session, actor: CurrentUser, payload: StoreIssueIn
    ) -> DepartmentRoutingOut:
        # 1. Lock the GS, then the plan lines (G-20 serialisation).
        gs = self._require_held(session, payload.gs_id)
        ids = list(dict.fromkeys(payload.plan_line_ids))
        plan_lines = repo.list_plan_lines(session, ids=ids, for_update=True)
        if len(plan_lines) != len(ids):
            raise NotFound(
                "One or more routing plan lines were not found", code="PLAN_LINE_NOT_FOUND"
            )
        for pl in plan_lines:
            if (
                pl["gs_id"] != payload.gs_id
                or pl["department_field_id"] != payload.department_field_id
            ):
                raise ValidationFailed(
                    "Every issued line must belong to this goods slip and department",
                    code="PLAN_LINE_MISMATCH",
                )
            if pl["status"] != "PLANNED":
                raise Conflict(
                    f"Plan line for item #{pl['line_no']} is {pl['status']}, not waiting for issue",
                    code="PLAN_LINE_NOT_OPEN",
                )

        dept = repo.get_department_field(session, payload.department_field_id)
        if not dept or not dept["is_active"]:
            raise ValidationFailed(
                f"Department field {payload.department_field_id} is not an active department",
                code="INVALID_DEPARTMENT",
            )
        dept_label = dept["label"]
        dept_location = self._department_location(session, dept["code"])
        locs = self._locations(session, INTERMEDIATE_LOCATION)
        receiving_role = self._receiving_role(session)

        lines_to_create: list[dict[str, Any]] = [
            {
                "plan_line_id": pl["id"],
                "gs_item_id": pl["gs_item_id"],
                "source_bucket_field_id": pl["source_bucket_field_id"],
                "lot_id": self._lot_for_item(session, pl["gs_item_id"]),
                "qty_sent": pl["qty"],
                "notes": pl["notes"],
            }
            for pl in plan_lines
        ]

        # 2. DIN document first, so stock movements reference it; then link the plan lines.
        routing_no = repo.next_number(session, "DEPT_ROUTING")
        routing = repo.create_department_routing(
            session,
            routing_no=routing_no,
            gs_id=payload.gs_id,
            department_field_id=dept["id"],
            department_code=dept["code"],
            department_label=dept_label,
            dispatched_by=actor.id,
            location_id=dept_location,
            remarks=payload.remarks,
            lines=lines_to_create,
        )
        for ld in lines_to_create:
            repo.mark_plan_line_issued(
                session,
                plan_line_id=ld["plan_line_id"],
                routing_id=routing["id"],
                routing_line_id=ld["id"],
                issued_by=actor.id,
            )

        # 3. Stock: INTERMEDIATE_STORE -> department location per line (same transaction).
        for idx, ld in enumerate(lines_to_create, start=1):
            ledger_service.move_stock(
                session,
                lot_id=ld["lot_id"],
                from_location_id=locs[INTERMEDIATE_LOCATION],
                to_location_id=dept_location,
                qty=ld["qty_sent"],
                movement_type="ISSUE",
                reference_type="department_routings",
                reference_id=routing["id"],
                idempotency_key=f"dept-routing:{routing['id']}:{idx}",
                actor_id=actor.id,
                reason=f"Issued to department {dept_label}",
            )

        # 4. G-20 again after every write (the DB triggers check it too).
        repo.validate_reconciliation(session, payload.gs_id)

        notifications.publish(
            session,
            "DEPT_ROUTING_DISPATCHED",
            role_codes=[receiving_role],
            title=f"Department Issue Note {routing_no}: goods issued to {dept_label}",
            body=(
                f"Goods slip {gs['gs_no']}: {sum(ld['qty_sent'] for ld in lines_to_create)} pc(s) "
                f"issued to {dept_label}. Receive them back when the work is done."
            ),
            entity_type="department_routings",
            entity_id=routing["id"],
            gs_id=payload.gs_id,
        )
        log.info(
            "dept_routing_issued",
            routing_no=routing_no,
            gs_id=str(payload.gs_id),
            lines=len(lines_to_create),
        )
        return DepartmentRoutingOut.model_validate(repo.get_routing(session, routing["id"]))

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
        if header["store_id"] is not None:
            # DEC-68: an Intermediate Store receives its own DINs back (store endpoint).
            raise Conflict(
                "This Department Issue Note belongs to an Intermediate Store; its store user "
                "receives the goods back (Receive from Departments)",
                code="STORE_ROUTING_RECEIPT",
            )
        repo.lock_goods_slip(session, header["gs_id"])
        receipt, routing = self._book_receipt(
            session, actor, header, payload.lines, payload.remarks
        )
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
        return receipt

    def _book_receipt(
        self,
        session: Session,
        actor: CurrentUser,
        header: dict[str, Any],
        payload_lines: list[DepartmentReceiptLineIn],
        remarks: str | None,
    ) -> tuple[DepartmentReceiptOut, dict[str, Any]]:
        """DEC-56 receipt of one routing (the caller checked the actor and locked routing + GS):
        validate the lines, write the receipt (the DB guards snapshot the outcome, move the
        pieces to their condition after work and pick the destination), move the stock per line
        and check G-20. Returns the receipt and the routing as it was before the receipt."""
        routing_id = header["id"]
        routing = repo.get_routing(session, routing_id)
        if not routing:
            raise NotFound(f"Routing {routing_id} not found", code="ROUTING_NOT_FOUND")
        if routing["status"] not in OPEN_ROUTING_STATUSES:
            raise ValidationFailed(
                f"Routing {routing['routing_no']} cannot be received (status: {routing['status']})",
                code="INVALID_ROUTING_STATUS",
            )

        locs = self._locations(session, TECHNICIAN_LOCATION)
        # DEC-55: stock comes back from the location the Store issued it to (legacy: bench).
        from_location = header["location_id"] or locs[TECHNICIAN_LOCATION]
        pending = {ln["id"]: ln["qty_sent"] - ln["qty_received"] for ln in routing["lines"]}
        line_items = {ln["id"]: ln for ln in routing["lines"]}

        # 3. Validate lines: belongs to routing, qty <= pending, outcome head active (DEC-43),
        #    condition after work (DEC-56 Q7). The DB guard re-checks all of it.
        lines_to_create: list[dict[str, Any]] = []
        for line in payload_lines:
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
            self._check_condition_after_work(r_line, line.condition_field_id)
            # DEC-56 Q8 / Q17: the head's destination must exist before anything is booked
            # (DEC-68: "back to the store" of a store routing is that store's location, which
            # the store master guarantees).
            if not (
                header["store_id"] is not None
                and head["destination_location_code"] == INTERMEDIATE_LOCATION
            ):
                self._locations(session, head["destination_location_code"])
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
                    "condition_field_id": line.condition_field_id,
                    "lot_id": self._lot_for_item(session, r_line["gs_item_id"]),
                }
            )

        # 4. Receipt document first (DB triggers update qty_received / status, move the pieces to
        #    their condition after work, snapshot the destination and check G-20).
        receipt_no = repo.next_number(session, "DEPT_RECEIPT")
        receipt = repo.create_department_receipt(
            session,
            receipt_no=receipt_no,
            routing_id=routing_id,
            received_by=actor.id,
            remarks=remarks,
            lines=lines_to_create,
        )

        # 5. Stock per line to the destination the DB snapshotted (DEC-56): wastage ->
        #    SCRAP_DISPOSED, Mercury Extracted -> NON_FUNCTIONAL_STORE, otherwise back to the
        #    INTERMEDIATE_STORE (Q8: no Store Manager acceptance) or, for a store routing, to
        #    that Intermediate Store's own location (DEC-68).
        for idx, ld in enumerate(lines_to_create, start=1):
            dest_code = ld["destination_location_code"]
            dest = self._locations(session, dest_code)[dest_code]
            to_scrap = dest_code == SCRAP_LOCATION
            ledger_service.move_stock(
                session,
                lot_id=ld["lot_id"],
                from_location_id=from_location,
                to_location_id=dest,
                qty=ld["quantity"],
                movement_type="DISPOSE" if to_scrap else "RECEIPT",
                reference_type="department_receipts",
                reference_id=receipt["id"],
                idempotency_key=f"dept-receipt:{receipt['id']}:{idx}",
                actor_id=actor.id,
                reason=f"Department outcome: {ld['outcome_label']}"
                + (" (wastage)" if ld["is_wastage"] else ""),
            )

        repo.validate_reconciliation(session, routing["gs_id"])
        log.info(
            "dept_routing_received",
            receipt_no=receipt_no,
            routing_no=routing["routing_no"],
            store_id=str(header["store_id"]) if header["store_id"] else None,
            lines=len(lines_to_create),
        )
        return DepartmentReceiptOut.model_validate(receipt), routing

    # --- DEC-67 (Phase P7): department routing by the Intermediate Store user ----------------
    #
    # After its own transfer slip is acknowledged (P6, Q29) a store routes ITS lines of a GS per
    # item + current condition. Saving the routing IS the issue: plan lines are written and, for
    # work departments, issued in the same transaction (one DIN per department, stock store
    # location -> department location through rms_move_stock). "Issue to Store" (no-work) lines
    # move no stock and are ready for analysis (P9). The DB enforces the same rules (migration
    # 20261121000300); the checks here give the clear 4xx answers first.

    @staticmethod
    def _store_scope(session: Session, actor: CurrentUser) -> set[UUID] | None:
        """Stores whose goods the user sees. None = every store (Super Admin and viewers without
        a store role: RM, Management); a store user sees only the stores whose role they hold."""
        if actor.is_super_admin:
            return None
        return set(repo.user_store_role_ids(session, actor.id)) or None

    @staticmethod
    def _acts_for(
        session: Session, actor: CurrentUser, cache: dict[UUID, bool], store_id: UUID
    ) -> bool:
        if store_id not in cache:
            cache[store_id] = repo.user_acts_for_store(session, actor.id, store_id)
        return cache[store_id]

    @staticmethod
    def _sync_store_tasks(
        session: Session, *, gs_id: UUID, role_id: UUID | None, status: str
    ) -> None:
        """The store's open work on a GS follows its progress: a STORE_ROUTING task while it has
        goods to route (DEC-67/68) and a STORE_ANALYSIS task once everything is back or had no
        work (DEC-69). Analysis happens only once nothing can change any more (Q32: the undo of
        an analysed item is refused), so the analysis task is closed by the submission."""
        gs_service.sync_step_task(
            session,
            gs_id=gs_id,
            step_code=ROUTING_TASK_STEP,
            role_id=role_id,
            needed=status == ROUTING_PENDING,
        )
        gs_service.sync_step_task(
            session,
            gs_id=gs_id,
            step_code=ANALYSIS_TASK_STEP,
            role_id=role_id,
            needed=status == READY_FOR_ANALYSIS,
        )

    def store_analysis_progress(
        self, session: Session, actor: CurrentUser, gs_id: UUID
    ) -> list[StoreProgressOut]:
        """DEC-69: the routing progress of every store on a GS (for the store analysis)."""
        return self._progress(session, actor, gs_id, {})

    def _progress(
        self, session: Session, actor: CurrentUser, gs_id: UUID, cache: dict[UUID, bool]
    ) -> list[StoreProgressOut]:
        return [
            StoreProgressOut.model_validate(
                {**p, "is_mine": self._acts_for(session, actor, cache, p["store_id"])}
            )
            for p in repo.store_progress(session, gs_id)
        ]

    def store_queue(
        self, session: Session, actor: CurrentUser, *, pending_only: bool
    ) -> list[StoreRoutingQueueRowOut]:
        """DEC-67: goods slips on the Intermediate Stores, one row per GS with the progress of
        each store the user sees. `pending_only`: a visible store still has goods to route."""
        scope = self._store_scope(session, actor)
        cache: dict[UUID, bool] = {}
        out: list[StoreRoutingQueueRowOut] = []
        for row in repo.store_routing_queue(session, STORE_ROUTING_STATUSES):
            stores = [
                p
                for p in self._progress(session, actor, row["gs_id"], cache)
                if scope is None or p.store_id in scope
            ]
            if not stores:
                continue
            if pending_only and not any(p.status == ROUTING_PENDING for p in stores):
                continue
            out.append(StoreRoutingQueueRowOut.model_validate({**row, "stores": stores}))
        return out

    def store_gs(self, session: Session, actor: CurrentUser, gs_id: UUID) -> StoreRoutingGsOut:
        """DEC-67: the routing view of one GS. Every line carries its store; `is_mine` marks the
        lines the user may route (the UI shows the others read-only behind a toggle)."""
        gs = repo.get_routing_gs(session, gs_id)
        if not gs:
            raise NotFound(f"Goods slip {gs_id} not found", code="GS_NOT_FOUND")
        cache: dict[UUID, bool] = {}
        stores = self._progress(session, actor, gs_id, cache)
        scope = self._store_scope(session, actor)
        if not stores or (scope is not None and not any(p.store_id in scope for p in stores)):
            # A store user sees only goods slips its store has goods of (as for slips, DEC-66).
            raise NotFound(
                f"Goods slip {gs['gs_no']} has no goods at your Intermediate Store",
                code="GS_NOT_AT_STORE",
            )
        routable_status = gs["status"] in STORE_ROUTING_STATUSES
        finalised = repo.has_current_ac_slip(session, gs_id)
        lines_by_item: dict[UUID, list[RoutingPlanLineOut]] = {}
        for pl in repo.list_plan_lines(session, gs_id=gs_id):
            if pl["status"] != "CANCELLED":
                lines_by_item.setdefault(pl["gs_item_id"], []).append(
                    RoutingPlanLineOut.model_validate(pl)
                )
        depts_by_product: dict[UUID, list[StoreRoutingDepartmentOut]] = {}
        items: list[StoreRoutingItemOut] = []
        for it in repo.routing_items(session, gs_id):
            mine = it["store_id"] is not None and self._acts_for(
                session, actor, cache, it["store_id"]
            )
            if it["product_id"] not in depts_by_product:
                depts_by_product[it["product_id"]] = [
                    StoreRoutingDepartmentOut.model_validate(d)
                    for d in repo.allowed_departments(
                        session, it["product_id"], gs["item_field_profile_version_id"]
                    )
                ]
            item_free = it["routable_qty"] if it["acknowledged"] and routable_status else 0
            routed = lines_by_item.get(it["item_id"], [])
            undoable = (
                [ln.id for ln in routed if ln.status == "NO_WORK" and ln.store_id == it["store_id"]]
                if mine
                and routable_status
                and not finalised
                and not repo.item_has_current_action(session, it["item_id"])
                else []
            )
            conditions = [
                StoreRoutingConditionOut.model_validate(
                    {**c, "routable_qty": max(min(c["free_qty"], item_free), 0)}
                )
                for c in repo.get_item_condition_balances(session, it["item_id"])
                if c["current_qty"] > 0
            ]
            items.append(
                StoreRoutingItemOut(
                    item_id=it["item_id"],
                    line_no=it["line_no"],
                    item_name=it["item_name"],
                    sku_code=it["sku_code"],
                    store=(
                        StoreRefOut(id=it["store_id"], code=it["store_code"], name=it["store_name"])
                        if it["store_id"]
                        else None
                    ),
                    is_mine=mine,
                    acknowledged=it["acknowledged"],
                    received_qty=it["received_qty"],
                    routable_qty=item_free,
                    at_departments_qty=it["at_departments_qty"],
                    conditions=conditions,
                    allowed_departments=depts_by_product[it["product_id"]],
                    routed=routed,
                    undoable_line_ids=undoable,
                )
            )
        return StoreRoutingGsOut(
            gs_id=gs["id"],
            gs_no=gs["gs_no"],
            status=gs["status"],
            party_name=gs["party_name"],
            station_name=gs["station_name"],
            stores=stores,
            items=items,
            dins=[StoreDinOut.model_validate(d) for d in repo.list_gs_dins(session, gs_id)],
            can_route=any(i.is_mine and i.routable_qty > 0 for i in items),
        )

    def undo_store_line(
        self, uow: UnitOfWork, *, actor: CurrentUser, plan_line_id: UUID, reason: str
    ) -> StoreRoutingGsOut:
        """Q32 (user 2026-11-21): a store undoes its own "Issue to Store" line until the piece is
        analysed (P9); issued pieces come back through receiving (P8). The pieces are free to
        route again and the store's routing task reopens. The DB checks the same rules."""
        with uow.transaction(actor.id) as session:
            lines = repo.list_plan_lines(session, ids=[plan_line_id])
            if not lines:
                raise NotFound("Routing line not found", code="PLAN_LINE_NOT_FOUND")
            gs_id = lines[0]["gs_id"]
            gs_service.lock_goods_slip(session, gs_id)
            line = repo.list_plan_lines(session, ids=[plan_line_id], for_update=True)[0]
            if line["store_id"] is None:
                raise Conflict(
                    "This line belongs to the Replacement Manager's routing plan",
                    code="NOT_STORE_LINE",
                )
            store = repo.get_store(session, line["store_id"])
            if not store or not repo.user_acts_for_store(session, actor.id, store["id"]):
                raise PermissionDenied(
                    "Only a user of the Intermediate Store undoes its routing (DEC-67)",
                    code="NOT_STORE_USER",
                )
            if line["status"] != "NO_WORK":
                raise Conflict(
                    f'Item #{line["line_no"]}: only an "Issue to Store" line can be undone; '
                    "pieces at a department come back through receiving",
                    code="LINE_NOT_UNDOABLE",
                )
            gs = repo.get_routing_gs(session, gs_id)
            if not gs or gs["status"] not in STORE_ROUTING_STATUSES:
                raise Conflict(
                    "The routing of this goods slip can no longer be undone",
                    code="INVALID_GS_STATUS",
                )
            if repo.has_current_ac_slip(session, gs_id) or repo.item_has_current_action(
                session, line["gs_item_id"]
            ):
                raise SystemGuardViolation(
                    "G-21", "G-21: the item is analysed; its routing can no longer be undone"
                )
            repo.cancel_plan_line(
                session, plan_line_id=plan_line_id, cancelled_by=actor.id, reason=reason.strip()
            )
            cache: dict[UUID, bool] = {}
            progress = next(
                p for p in self._progress(session, actor, gs_id, cache) if p.store_id == store["id"]
            )
            self._sync_store_tasks(
                session, gs_id=gs_id, role_id=store["role_id"], status=progress.status
            )
            log.info(
                "store_routing_undone",
                gs_id=str(gs_id),
                store=store["code"],
                plan_line_id=str(plan_line_id),
                qty=line["qty"],
            )
            return self.store_gs(session, actor, gs_id)

    def route_store_goods(
        self,
        uow: UnitOfWork,
        *,
        actor: CurrentUser,
        gs_id: UUID,
        payload: StoreRoutingIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        """DEC-67: one transaction; a duplicate Idempotency-Key returns the first result (G-16)."""
        with uow.transaction(actor.id) as session:
            return run_idempotent(
                session,
                idem,
                actor.id,
                lambda: (
                    200,
                    self._route_store(session, actor, gs_id, payload).model_dump(mode="json"),
                ),
            )

    def _route_store(
        self, session: Session, actor: CurrentUser, gs_id: UUID, payload: StoreRoutingIn
    ) -> StoreRoutingResultOut:
        # 1. Lock the GS (G-20 serialisation; P6 acknowledgements lock it too).
        gs_service.lock_goods_slip(session, gs_id)
        gs = repo.get_routing_gs(session, gs_id)
        if not gs:  # pragma: no cover - locked just above
            raise NotFound(f"Goods slip {gs_id} not found", code="GS_NOT_FOUND")
        if gs["status"] not in STORE_ROUTING_STATUSES:
            raise Conflict(
                f"Goods slip {gs['gs_no']} is not at its Intermediate Stores (status "
                f"{gs['status']}); it cannot be routed (DEC-67)",
                code="INVALID_GS_STATUS",
            )
        store = repo.get_store(session, payload.store_id)
        if not store:
            raise NotFound("Intermediate Store not found", code="STORE_NOT_FOUND")
        if not repo.user_acts_for_store(session, actor.id, store["id"]):
            raise PermissionDenied(
                f"Only a user of {store['name']} routes its goods (DEC-67)",
                code="NOT_STORE_USER",
                details={"store_code": store["code"]},
            )
        if repo.has_current_ac_slip(session, gs_id):
            raise SystemGuardViolation(
                "G-21",
                f"G-21: final actions of {gs['gs_no']} are finalised; nothing can be routed",
            )

        # 2. Validate every line before writing anything.
        items = {it["item_id"]: it for it in repo.routing_items(session, gs_id)}
        version = gs["item_field_profile_version_id"]
        allowed: dict[UUID, set[UUID]] = {}
        depts: dict[UUID, dict[str, Any]] = {}
        conditions: dict[UUID, dict[UUID, dict[str, Any]]] = {}
        cond_left: dict[tuple[UUID, UUID], int] = {}
        item_left: dict[UUID, int] = {}
        for line in payload.lines:
            it = items.get(line.gs_item_id)
            if not it:
                raise ValidationFailed(
                    f"Item {line.gs_item_id} is not a physical line of goods slip {gs['gs_no']}",
                    code="ITEM_NOT_IN_GS",
                )
            label = f"item #{it['line_no']} ({it['item_name']})"
            if it["store_id"] != store["id"]:
                raise PermissionDenied(
                    f"{label.capitalize()} belongs to "
                    f"{it['store_name'] or 'no Intermediate Store'}; only that store routes it "
                    "(DEC-67)",
                    code="ITEM_OF_OTHER_STORE",
                    details={"store_code": it["store_code"]},
                )
            if not it["acknowledged"]:
                raise Conflict(
                    f"{label.capitalize()} is not acknowledged by {store['name']} yet",
                    code="ITEM_NOT_ACKNOWLEDGED",
                )
            dept = depts.get(line.department_field_id)
            if dept is None:
                found = repo.get_department_field(session, line.department_field_id)
                if not found or not found["is_active"]:
                    raise ValidationFailed(
                        f"Department field {line.department_field_id} is not an active department",
                        code="INVALID_DEPARTMENT",
                    )
                dept = {**found, "no_work": repo.department_is_no_work(session, found["code"])}
                if not dept["no_work"]:
                    dept["location_id"] = self._department_location(session, found["code"])
                depts[line.department_field_id] = dept
            if it["product_id"] not in allowed:
                allowed[it["product_id"]] = {
                    d["field_id"]
                    for d in repo.allowed_departments(session, it["product_id"], version)
                }
            if dept["id"] not in allowed[it["product_id"]]:
                raise ValidationFailed(
                    f"Department '{dept['label']}' is not allowed for {label} (DEC-59, the goods "
                    "slip's profile version)",
                    code="DEPARTMENT_NOT_ALLOWED",
                )
            if line.gs_item_id not in conditions:
                conditions[line.gs_item_id] = {
                    c["field_id"]: c
                    for c in repo.get_item_condition_balances(session, line.gs_item_id)
                }
                item_left[line.gs_item_id] = int(it["routable_qty"])
            conds = conditions[line.gs_item_id]
            if line.source_bucket_field_id is None:
                if any(c["current_qty"] > 0 for c in conds.values()):
                    raise ValidationFailed(
                        f"{label.capitalize()} is split by condition; choose the condition of "
                        "each routing line",
                        code="CONDITION_REQUIRED",
                    )
            else:
                cond = conds.get(line.source_bucket_field_id)
                if cond is None or cond["current_qty"] <= 0:
                    raise ValidationFailed(
                        f"The chosen condition is not part of {label}'s split",
                        code="CONDITION_NOT_IN_ITEM",
                    )
                key = (line.gs_item_id, line.source_bucket_field_id)
                left = cond_left.setdefault(key, int(cond["free_qty"]))
                if line.qty > left:
                    raise SystemGuardViolation(
                        "G-20",
                        f"G-20: {label} condition '{cond['field_label']}': only {max(left, 0)} "
                        f"pc(s) left to route, {line.qty} requested.",
                    )
                cond_left[key] = left - line.qty
            if line.qty > item_left[line.gs_item_id]:
                raise SystemGuardViolation(
                    "G-20",
                    f"G-20: {label}: only {item_left[line.gs_item_id]} pc(s) left to route at "
                    f"{store['name']}, {line.qty} requested.",
                )
            item_left[line.gs_item_id] -= line.qty

        # 3. Write: one plan line per payload line (NO_WORK for "Issue to Store"), then one DIN
        #    per work department: routing lines, plan lines ISSUED, stock store -> department.
        groups: dict[UUID, list[dict[str, Any]]] = {}
        no_work_qty = 0
        for line in payload.lines:
            plan_line_id = repo.insert_plan_line(
                session,
                gs_id=gs_id,
                gs_item_id=line.gs_item_id,
                source_bucket_field_id=line.source_bucket_field_id,
                department_field_id=line.department_field_id,
                qty=line.qty,
                notes=line.notes,
                planned_by=actor.id,
                store_id=store["id"],
            )
            if depts[line.department_field_id]["no_work"]:
                no_work_qty += line.qty
                continue
            groups.setdefault(line.department_field_id, []).append(
                {
                    "plan_line_id": plan_line_id,
                    "gs_item_id": line.gs_item_id,
                    "source_bucket_field_id": line.source_bucket_field_id,
                    "lot_id": self._lot_for_item(session, line.gs_item_id),
                    "qty_sent": line.qty,
                    "notes": line.notes,
                }
            )
        routing_ids: list[UUID] = []
        for dept_id, lines_to_create in groups.items():
            dept = depts[dept_id]
            routing_no = repo.next_number(session, "DEPT_ROUTING")
            routing = repo.create_department_routing(
                session,
                routing_no=routing_no,
                gs_id=gs_id,
                department_field_id=dept["id"],
                department_code=dept["code"],
                department_label=dept["label"],
                dispatched_by=actor.id,
                location_id=dept["location_id"],
                remarks=payload.remarks,
                lines=lines_to_create,
                store_id=store["id"],
            )
            routing_ids.append(routing["id"])
            for ld in lines_to_create:
                repo.mark_plan_line_issued(
                    session,
                    plan_line_id=ld["plan_line_id"],
                    routing_id=routing["id"],
                    routing_line_id=ld["id"],
                    issued_by=actor.id,
                )
            for idx, ld in enumerate(lines_to_create, start=1):
                ledger_service.move_stock(
                    session,
                    lot_id=ld["lot_id"],
                    from_location_id=store["location_id"],
                    to_location_id=dept["location_id"],
                    qty=ld["qty_sent"],
                    movement_type="ISSUE",
                    reference_type="department_routings",
                    reference_id=routing["id"],
                    idempotency_key=f"dept-routing:{routing['id']}:{idx}",
                    actor_id=actor.id,
                    reason=f"{store['name']}: issued to department {dept['label']} (DEC-67)",
                )

        # 4. G-20 after every write (the DB triggers check it too).
        repo.validate_reconciliation(session, gs_id)

        # 5. The first routing of any store moves the GS on (Q29: other stores may still be
        #    acknowledging); the store's routing task stays open while it has goods to route.
        status = gs["status"]
        if status != PROCESSING_STATUS:
            gs_service.change_status_within_step(
                session,
                gs_id=gs_id,
                from_status=status,
                to_status=PROCESSING_STATUS,
                step_code=ROUTING_TASK_STEP,
                reason=f"Department routing started by {store['name']} (DEC-67)",
                by=actor.id,
            )
            status = PROCESSING_STATUS
        cache: dict[UUID, bool] = {}
        progress = next(
            p for p in self._progress(session, actor, gs_id, cache) if p.store_id == store["id"]
        )
        self._sync_store_tasks(
            session, gs_id=gs_id, role_id=store["role_id"], status=progress.status
        )
        log.info(
            "store_routing_saved",
            gs_id=str(gs_id),
            store=store["code"],
            lines=len(payload.lines),
            dins=len(routing_ids),
            no_work_qty=no_work_qty,
        )
        return StoreRoutingResultOut(
            gs_id=gs_id,
            gs_status=status,
            store=progress,
            dins=[
                StoreDinOut.model_validate(d)
                for d in repo.list_gs_dins(session, gs_id)
                if d["id"] in routing_ids
            ],
            no_work_qty=no_work_qty,
        )

    # --- DEC-68 (Phase P8): receiving back from departments by the Intermediate Store user ----
    #
    # The store that routed the goods (department_routings.store_id) receives its DINs back per GS
    # and department: sent vs received qty, outcome, condition after work (DEC-56 rules, partial
    # receipts). Stock goes back to that store's location (or scrap / Non-Functional Store per
    # outcome head). Outcomes that "return to routing" make the pieces routable again and reopen
    # the store's STORE_ROUTING task. Once nothing of the store is at a department or still to
    # route, its progress is READY_FOR_ANALYSIS (P9). The DB checks the same rules (migration
    # 20261121000500).

    def store_receiving(
        self, session: Session, actor: CurrentUser, *, gs_id: UUID | None = None
    ) -> list[StoreReceivingGsOut]:
        """DEC-68: goods slips (party-wise) with open DINs of the stores the user sees, each with
        its DINs per department. A store user sees only its own stores' DINs."""
        scope = self._store_scope(session, actor)
        cache: dict[UUID, bool] = {}
        by_gs: dict[UUID, dict[str, Any]] = {}
        for d in repo.store_receiving_dins(session, gs_id=gs_id):
            if scope is not None and d["store_id"] not in scope:
                continue
            row = by_gs.setdefault(
                d["gs_id"],
                {
                    "gs_id": d["gs_id"],
                    "gs_no": d["gs_no"],
                    "status": d["gs_status"],
                    "party_name": d["party_name"],
                    "station_name": d["station_name"],
                    "since": d["dispatched_at"],
                    "dins": [],
                },
            )
            row["dins"].append(
                StoreReceivingDinOut.model_validate(
                    {**d, "is_mine": self._acts_for(session, actor, cache, d["store_id"])}
                )
            )
        out: list[StoreReceivingGsOut] = []
        for row in by_gs.values():
            stores = [
                p
                for p in self._progress(session, actor, row["gs_id"], cache)
                if scope is None or p.store_id in scope
            ]
            out.append(StoreReceivingGsOut.model_validate({**row, "stores": stores}))
        return out

    def receive_store_din(
        self,
        uow: UnitOfWork,
        *,
        actor: CurrentUser,
        routing_id: UUID,
        payload: StoreReceiptIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        """DEC-68: one transaction; a duplicate Idempotency-Key returns the first result (G-16)."""
        with uow.transaction(actor.id) as session:
            return run_idempotent(
                session,
                idem,
                actor.id,
                lambda: (
                    200,
                    self._receive_store(session, actor, routing_id, payload).model_dump(
                        mode="json"
                    ),
                ),
            )

    def _receive_store(
        self, session: Session, actor: CurrentUser, routing_id: UUID, payload: StoreReceiptIn
    ) -> StoreReceiptResultOut:
        # 1. Lock the routing, then the GS (G-20 serialisation, same order as the legacy path).
        header = repo.lock_routing_header(session, routing_id)
        if not header:
            raise NotFound(f"Routing {routing_id} not found", code="ROUTING_NOT_FOUND")
        if header["store_id"] is None:
            raise Conflict(
                "This Department Issue Note was issued by the legacy Intermediate Store; it is "
                "received in Department Receiving (DEC-42)",
                code="NOT_STORE_ROUTING",
            )
        store = repo.get_store(session, header["store_id"])
        if not store:  # pragma: no cover - FK
            raise NotFound("Intermediate Store not found", code="STORE_NOT_FOUND")
        if not repo.user_acts_for_store(session, actor.id, store["id"]):
            raise PermissionDenied(
                f"Only a user of {store['name']} receives its goods back from departments (DEC-68)",
                code="NOT_STORE_USER",
                details={"store_code": store["code"]},
            )
        gs_service.lock_goods_slip(session, header["gs_id"])
        gs = repo.get_routing_gs(session, header["gs_id"])
        if not gs or gs["status"] != PROCESSING_STATUS:
            raise Conflict(
                "Goods are received back while the goods slip is in store processing "
                f"(status {gs['status'] if gs else 'missing'})",
                code="INVALID_GS_STATUS",
            )

        # 2. The shared DEC-56 receipt: lines, receipt, stock back to the store / outcome, G-20.
        receipt, routing = self._book_receipt(
            session, actor, header, payload.lines, payload.remarks
        )

        # 3. The store's progress: pieces back with a "return to routing" outcome reopen its
        #    routing task; everything back (or no work) = ready for analysis (P9).
        cache: dict[UUID, bool] = {}
        progress = next(
            p for p in self._progress(session, actor, gs["id"], cache) if p.store_id == store["id"]
        )
        self._sync_store_tasks(
            session, gs_id=gs["id"], role_id=store["role_id"], status=progress.status
        )
        din = repo.store_receiving_dins(session, routing_id=routing_id)[0]
        if din["status"] == "COMPLETED":
            ready = progress.status == READY_FOR_ANALYSIS
            notifications.publish(
                session,
                "DEPT_ROUTING_COMPLETED",
                user_ids=[routing["dispatched_by"]],
                role_codes=[store["role_code"]] if store["role_code"] else [],
                title=f"Department Issue Note {routing['routing_no']} received back",
                body=(
                    f"{gs['gs_no']}: everything sent to {routing['department_label']} is back at "
                    f"{store['name']}."
                    + (" The store's part is ready for analysis." if ready else "")
                ),
                entity_type="department_routings",
                entity_id=routing["id"],
                gs_id=gs["id"],
            )
        log.info(
            "store_receipt_saved",
            gs_id=str(gs["id"]),
            store=store["code"],
            routing_no=routing["routing_no"],
            receipt_no=receipt.receipt_no,
            store_status=progress.status,
        )
        return StoreReceiptResultOut(
            gs_id=gs["id"],
            receipt=receipt,
            din=StoreReceivingDinOut.model_validate({**din, "is_mine": True}),
            store=progress,
        )


department_routing_service = DepartmentRoutingService()
