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
    DepartmentReceiptOut,
    DepartmentRoutingOut,
    GsReconciliationOut,
    IssueQueueGroupOut,
    ReceivingQueueItemOut,
    RmRoutingQueueItemOut,
    RoutingPlanLineOut,
    RoutingPlanOut,
    StoreIssueIn,
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
# DEC-55 Q16: department code -> its own inventory location code (configuration).
LOCATION_BY_CODE_SETTING = "department.location_by_code"
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
        repo.lock_goods_slip(session, header["gs_id"])
        routing = repo.get_routing(session, payload.routing_id)
        if not routing:
            raise NotFound(f"Routing {payload.routing_id} not found", code="ROUTING_NOT_FOUND")
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
            self._check_condition_after_work(r_line, line.condition_field_id)
            # DEC-56 Q8 / Q17: the head's destination must exist before anything is booked.
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
            routing_id=payload.routing_id,
            received_by=actor.id,
            remarks=payload.remarks,
            lines=lines_to_create,
        )

        # 5. Stock per line to the destination the DB snapshotted (DEC-56): wastage ->
        #    SCRAP_DISPOSED, Mercury Extracted -> NON_FUNCTIONAL_STORE, otherwise back to the
        #    INTERMEDIATE_STORE (Q8: no Store Manager acceptance).
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
