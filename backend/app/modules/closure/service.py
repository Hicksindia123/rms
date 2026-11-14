"""GS closure engine (P3-07; master plan §6.5, G-15, BR-38, BR-39, DD r79-r80, WF r11).

* `evaluate` runs the single closure checklist (`rms_private.gs_closure_checklist`); the
  G-15 trigger on goods_slips re-runs the same function, so no role, setting or Super Admin
  status can close a GS the checklist rejects (CLAUDE.md rule c).
* `sync_status` is the §6.5 status automation: IN_PROCESS -> COMMERCIAL_RESOLUTION once every piece
  is in a terminal / accounted state; COMMERCIAL_RESOLUTION -> AWAITING_NOTIFICATION once the CN /
  dispatch work is complete but a prior party notification (BR-38) is outstanding. Other modules
  call it (service-to-service) after the commands that can complete that work.
* `close` (S6_CLOSE; roles from the `gs_closure_roles` setting) re-evaluates under row locks and
  writes gs_closures with a frozen checklist snapshot; failures -> 422 G-15 listing every failed
  item. `reopen` is Super Admin only, with a reason, and is audited.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from app.core.db import UnitOfWork
from app.core.errors import Conflict, NotFound, PermissionDenied, SystemGuardUnmet
from app.core.idempotency import IdempotencyKey, IdempotentResult, run_idempotent
from app.core.permissions import EffectivePermissions
from app.core.security import CurrentUser
from app.modules.closure import repository as repo
from app.modules.closure.schemas import (
    ChecklistFix,
    ChecklistItemOut,
    CloseIn,
    ClosureCreditNoteOut,
    ClosureDispatchOut,
    ClosureLineOut,
    ClosureNotificationOut,
    ClosureRecordOut,
    ClosureStateOut,
    ReopenIn,
    StageDurationOut,
)
from app.modules.goods_slips import service as gs_service
from app.modules.notifications import service as notif_service

log = structlog.get_logger("rms.closure")

CLOSE_STEP = "S6_CLOSE"
NOTIFY_STEP = "S6_NOTIFY"
CN_DECISION_STEP = "S6_CN_DECISION"
CLOSABLE = frozenset({"IN_PROCESS", "COMMERCIAL_RESOLUTION", "AWAITING_NOTIFICATION"})
REOPEN_TO = "COMMERCIAL_RESOLUTION"  # §6.5 / P3-07: a reopened GS returns to commercial resolution
CSR_CLOSED = "CSR_CLOSED"
CSR_FINAL_STATUS_SET = "CSR_FINAL_STATUS"  # DD r80 option set (label comes from configuration)
DEFAULT_CLOSURE_ROLES = ["REPLACEMENT_MANAGER", "ACCOUNTS"]

# Checklist groups driving the §6.5 status automation.
STOCK_CODES = ("STOCK_NOT_IN_TRANSIT", "STOCK_ACCOUNTED", "NO_OPEN_PENDENCY", "NO_OPEN_DISCREPANCY")
COMMERCIAL_CODES = (
    "CN_DECISION_RECORDED",
    "ALLOW_CN_COVERED",
    "DENY_QTY_DISPATCHED",
    # Change plan Phase 8 (AMD-18, AMD-19): the A/c Actions flow.
    "AC_ENTRY_COMPLETE",
    "DISPATCH_SLIP_DISPATCHED",
)


def _fix(code: str, gs_id: UUID) -> ChecklistFix | None:
    """Link to the screen where a failing item is fixed (hash routes of the SPA)."""
    gs = f"/gs/{gs_id}"
    links: dict[str, tuple[str, str]] = {
        "GS_STATUS": ("Open goods slip", gs),
        "STOCK_NOT_IN_TRANSIT": ("Custody transfers", "/custody"),
        "STOCK_ACCOUNTED": ("Store issue", "/store-issues"),
        "NO_OPEN_PENDENCY": ("Pendency register", "/pendencies"),
        "NO_OPEN_DISCREPANCY": ("Custody transfers", "/custody"),
        "CN_DECISION_RECORDED": ("RM CN decision", f"{gs}/cn-decision"),
        "ALLOW_CN_COVERED": ("Credit notes", "/credit-notes"),
        "DENY_QTY_DISPATCHED": ("Replacement dispatch", "/dispatch"),
        "PRIOR_NOTIFICATION": ("Notify party", f"{gs}/party-notification"),
        "CSR_PACKAGING_HANDOVER": ("Handover", f"{gs}/handover"),
        "CSR_PACKAGING_CHECK": ("Handover", f"{gs}/handover"),
        "CSR_CN_ISSUED": ("Credit notes", "/credit-notes"),
        "AC_ENTRY_COMPLETE": ("Accounts entry", f"/accounts-entry/{gs_id}"),
        "DISPATCH_SLIP_DISPATCHED": ("Dispatch slips", "/dispatch-slips"),
    }
    entry = links.get(code)
    return ChecklistFix(label=entry[0], path=entry[1]) if entry else None


def evaluate(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    """The closure checklist (G-15 / BR-38 / BR-39), one row per item."""
    return repo.checklist(session, gs_id)


def failed_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [i for i in items if i["applicable"] and not i["passed"]]


def _ok(items: dict[str, dict[str, Any]], codes: tuple[str, ...]) -> bool:
    return all(items[c]["passed"] or not items[c]["applicable"] for c in codes)


def sync_status(session: Session, gs_id: UUID, by: UUID | None) -> str | None:
    """§6.5 status automation (P3-07 item 5). Returns the new status, or None if unchanged.

    Never forces a transition the DB guards would reject: every precondition the G-08 / G-15
    triggers check is part of the evaluated checklist.
    """
    gs = gs_service.lock_goods_slip(session, gs_id)
    status = str(gs["status"])
    if status not in ("IN_PROCESS", "COMMERCIAL_RESOLUTION"):
        return None
    by = by or repo.current_actor(session)
    items = {i["code"]: i for i in evaluate(session, gs_id)}
    changed: str | None = None
    if status == "IN_PROCESS" and _ok(items, STOCK_CODES) and repo.lot_count(session, gs_id) > 0:
        gs_service.change_status(
            session,
            gs_id=gs_id,
            from_status=status,
            to_status="COMMERCIAL_RESOLUTION",
            step_code=CN_DECISION_STEP,
            reason="All stock dispositions done (§6.5)",
            by=by,
        )
        status = changed = "COMMERCIAL_RESOLUTION"
        # P4-03: CN_DECISION_REQUIRED (BR-32; rule seeded inactive). Context: the roles that
        # perform the CN decision step of the GS's pinned workflow.
        notif_service.publish(
            session,
            "CN_DECISION_REQUIRED",
            role_codes=gs_service.step_role_codes(session, gs, CN_DECISION_STEP, "PERFORM"),
            title=f"{gs['gs_no']}: CN decision required",
            body="All stock dispositions are done; record the credit note decision (§6.5).",
            entity_type="goods_slip",
            entity_id=gs_id,
            gs_id=gs_id,
            data={"gs_no": str(gs["gs_no"])},
        )
    notification = items["PRIOR_NOTIFICATION"]
    if (
        status == "COMMERCIAL_RESOLUTION"
        and _ok(items, COMMERCIAL_CODES)
        and notification["applicable"]
        and not notification["passed"]
    ):
        gs_service.change_status(
            session,
            gs_id=gs_id,
            from_status=status,
            to_status="AWAITING_NOTIFICATION",
            step_code=NOTIFY_STEP,
            reason="CN / dispatch work complete; prior party notification outstanding (BR-38)",
            by=by,
        )
        if not gs_service.has_open_step_task(session, gs_id, NOTIFY_STEP):
            gs_service.open_step_tasks(session, gs, NOTIFY_STEP)
        # P4-03: NOTIFICATION_PENDING (BR-38; rule seeded inactive). Context: the roles that
        # perform the party notification step of the GS's pinned workflow.
        notif_service.publish(
            session,
            "NOTIFICATION_PENDING",
            role_codes=gs_service.step_role_codes(session, gs, NOTIFY_STEP, "PERFORM"),
            title=f"{gs['gs_no']}: prior party notification pending",
            body="CN / dispatch work is complete; inform the party before closure (BR-38).",
            entity_type="goods_slip",
            entity_id=gs_id,
            gs_id=gs_id,
            data={"gs_no": str(gs["gs_no"])},
        )
        changed = "AWAITING_NOTIFICATION"
    elif (
        status == "COMMERCIAL_RESOLUTION"
        and not failed_items(list(items.values()))
        and not gs_service.has_open_step_task(session, gs_id, CLOSE_STEP)
    ):
        # Nothing left but the closure itself (e.g. replacement-only path): S6_CLOSE task (WF r11).
        gs_service.open_step_tasks(session, gs, CLOSE_STEP)
    if changed:
        log.info("gs_status_synced", gs_id=str(gs_id), from_status=gs["status"], to_status=changed)
    return changed


def _role_codes(value: Any) -> set[str]:
    if isinstance(value, list):
        return {str(v) for v in value}
    return set(DEFAULT_CLOSURE_ROLES)


class ClosureService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    # ---------------------------------------------------------------- read -------------------
    def get_state(
        self, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID
    ) -> ClosureStateOut:
        with self._uow.transaction(user.id) as session:
            gs_service.get_visible_goods_slip(session, user, perms, gs_id)
            return self._state(session, user, gs_id)

    # ---------------------------------------------------------------- close ------------------
    def close(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: CloseIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        # Status automation first, in its own transaction: it is system bookkeeping that must
        # persist even when the closure itself is then rejected with the failed items.
        with self._uow.transaction(user.id) as session:
            gs_service.get_visible_goods_slip(session, user, perms, gs_id)
            self._assert_closer(session, user)
            sync_status(session, gs_id, user.id)

        with self._uow.transaction(user.id) as session:

            def command() -> tuple[int, Any]:
                gs = gs_service.lock_goods_slip(session, gs_id)
                if gs["status"] == "CLOSED":
                    raise Conflict("This goods slip is already closed", code="GS_ALREADY_CLOSED")
                repo.lock_closure_inputs(session, gs_id)
                items = evaluate(session, gs_id)
                failed = failed_items(items)
                if failed:
                    raise SystemGuardUnmet(
                        "G-15",
                        f"The goods slip cannot be closed: {len(failed)} checklist item(s) failed",
                        details={
                            "failed_items": [
                                {
                                    "code": i["code"],
                                    "rule_ref": i["rule_ref"],
                                    "explanation": i["explanation"],
                                }
                                for i in failed
                            ]
                        },
                    )
                closure_type = repo.closure_type(session, gs_id)
                label = (
                    repo.option_label(session, CSR_FINAL_STATUS_SET, closure_type)
                    if closure_type == CSR_CLOSED
                    else None
                )
                snapshot = self._snapshot(session, gs, items, closure_type, label)
                existing = repo.get_closure(session, gs_id, for_update=True)
                write = repo.update_closure_for_reclose if existing else repo.insert_closure
                write(
                    session,
                    gs_id=gs_id,
                    closure_type=closure_type,
                    closure_label=label,
                    snapshot=snapshot,
                    remarks=(payload.remarks or "").strip() or None,
                    by=user.id,
                )
                gs_service.close_goods_slip(
                    session,
                    gs_id=gs_id,
                    from_status=str(gs["status"]),
                    closure_type=closure_type,
                    by=user.id,
                    reason=label or f"Closed as {closure_type}",
                )
                notif_service.publish(
                    session,
                    "GS_CLOSED",
                    role_codes=sorted(_role_codes(repo.get_setting(session, "gs_closure_roles"))),
                    notification_type="GS_CLOSED",
                    title=f"GS {gs['gs_no']} closed",
                    body=label or f"Closed as {closure_type}",
                    entity_type="goods_slip",
                    entity_id=gs_id,
                    gs_id=gs_id,
                    data={"gs_no": gs["gs_no"]},
                )
                log.info("gs_closed", gs_id=str(gs_id), closure_type=closure_type)
                return 200, self._state(session, user, gs_id)

            return run_idempotent(session, idem, user.id, command)

    # ---------------------------------------------------------------- reopen -----------------
    def reopen(
        self, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID, payload: ReopenIn
    ) -> ClosureStateOut:
        if not user.is_super_admin:
            raise PermissionDenied(
                "Only a Super Admin can reopen a closed goods slip", code="SUPER_ADMIN_REQUIRED"
            )
        reason = payload.reason.strip()
        with self._uow.transaction(user.id) as session:
            gs = gs_service.lock_goods_slip(session, gs_id)
            gs_service.get_visible_goods_slip(session, user, perms, gs_id)
            if gs["status"] != "CLOSED":
                raise Conflict(
                    "Only a closed goods slip can be reopened",
                    code="GS_NOT_CLOSED",
                    details={"status": gs["status"]},
                )
            if not repo.get_closure(session, gs_id, for_update=True):
                raise NotFound("The closure record of this goods slip is missing")
            gs_service.set_audit_reason(session, f"GS reopened: {reason}")
            repo.record_reopen(session, gs_id=gs_id, by=user.id, reason=reason)
            gs_service.reopen_goods_slip(
                session, gs=gs, to_status=REOPEN_TO, by=user.id, reason=f"Reopened: {reason}"
            )
            gs_service.set_audit_reason(session, None)
            log.info("gs_reopened", gs_id=str(gs_id))
            return self._state(session, user, gs_id)

    # ---------------------------------------------------------------- internals --------------
    def _can_close(self, session: Session, user: CurrentUser) -> bool:
        if user.is_super_admin:
            return True
        roles = _role_codes(repo.get_setting(session, "gs_closure_roles"))
        return bool(roles & set(user.role_codes))

    def _assert_closer(self, session: Session, user: CurrentUser) -> None:
        if not self._can_close(session, user):
            raise PermissionDenied(
                "Your role may not close goods slips (setting gs_closure_roles)",
                code="NOT_CLOSURE_ROLE",
            )

    def _snapshot(
        self,
        session: Session,
        gs: dict[str, Any],
        items: list[dict[str, Any]],
        closure_type: str,
        label: str | None,
    ) -> dict[str, Any]:
        """The frozen checklist (P3-07 item 3), JSON-safe."""
        return {
            "evaluated_at": datetime.now(UTC).isoformat(),
            "gs_no": gs["gs_no"],
            "status_before": gs["status"],
            "closure_type": closure_type,
            "closure_label": label,
            "items": [
                {
                    "code": i["code"],
                    "rule_ref": i["rule_ref"],
                    "applicable": i["applicable"],
                    "passed": i["passed"],
                    "explanation": i["explanation"],
                    "details": i["details"],
                }
                for i in items
            ],
            "credit_notes": [
                {
                    "id": str(c["id"]),
                    "cn_type_code": c["cn_type_code"],
                    "voucher_no": c["cn_no"] or c["jv_no"],
                    "voucher_date": (c["cn_date"] or c["jv_date"]).isoformat()
                    if (c["cn_date"] or c["jv_date"])
                    else None,
                    "total_value": str(c["total_value"]),
                }
                for c in repo.issued_credit_notes(session, gs["id"])
            ],
            "notifications": [
                {
                    "id": str(n["id"]),
                    "credit_note_id": str(n["credit_note_id"]) if n["credit_note_id"] else None,
                    "channel_code": n["channel_code"],
                    "recipient": n["recipient"],
                    "sent_at": n["sent_at"].isoformat(),
                }
                for n in repo.notifications(session, gs["id"])
            ],
            "dispatches": [
                {"dispatch_no": d["dispatch_no"], "qty": d["qty"]}
                for d in repo.dispatches(session, gs["id"])
            ],
        }

    def _state(self, session: Session, user: CurrentUser, gs_id: UUID) -> ClosureStateOut:
        head = repo.gs_header(session, gs_id)
        if not head:
            raise NotFound("Goods slip not found")
        items = evaluate(session, gs_id)
        all_passed = not failed_items(items)
        expected = repo.closure_type(session, gs_id)
        closure = repo.get_closure(session, gs_id)
        lifecycle, total = _lifecycle(gs_service.status_history(session, gs_id))
        return ClosureStateOut(
            gs_id=head["id"],
            gs_no=head["gs_no"],
            status=head["status"],
            category_code=head["category_code"],
            party_name=head["party_name"],
            state_name=head["state_name"],
            station_name=head["station_name"],
            created_at=head["created_at"],
            closed_at=head["closed_at"],
            expected_closure_type=expected,
            expected_closure_label=(
                repo.option_label(session, CSR_FINAL_STATUS_SET, expected)
                if expected == CSR_CLOSED
                else None
            ),
            items=[
                ChecklistItemOut(
                    code=i["code"],
                    rule_ref=i["rule_ref"],
                    applicable=i["applicable"],
                    passed=i["passed"],
                    explanation=i["explanation"],
                    details=i["details"] or {},
                    fix=None if i["passed"] else _fix(i["code"], gs_id),
                )
                for i in items
            ],
            all_passed=all_passed,
            can_close=head["status"] in CLOSABLE and self._can_close(session, user),
            can_reopen=head["status"] == "CLOSED" and user.is_super_admin,
            closure=ClosureRecordOut(**closure) if closure else None,
            lifecycle=lifecycle,
            total_duration_seconds=total,
            lines=[ClosureLineOut(**r) for r in repo.gs_lines(session, gs_id)],
            credit_notes=[
                ClosureCreditNoteOut(
                    id=c["id"],
                    cn_type_code=c["cn_type_code"],
                    cn_type_label=c["cn_type_label"],
                    voucher_no=c["cn_no"] or c["jv_no"],
                    voucher_date=c["cn_date"] or c["jv_date"],
                    total_value=c["total_value"],
                    issued_at=c["issued_at"],
                )
                for c in repo.issued_credit_notes(session, gs_id)
            ],
            dispatches=[ClosureDispatchOut(**d) for d in repo.dispatches(session, gs_id)],
            notifications=[ClosureNotificationOut(**n) for n in repo.notifications(session, gs_id)],
        )


def _lifecycle(history: list[dict[str, Any]]) -> tuple[list[StageDurationOut], int]:
    """Stage durations from the status history (time spent in each status, in order)."""
    now = datetime.now(UTC)
    stages: list[StageDurationOut] = []
    for idx, h in enumerate(history):
        entered: datetime = h["at"]
        left: datetime | None = history[idx + 1]["at"] if idx + 1 < len(history) else None
        end = left or (entered if h["to_status"] in ("CLOSED", "CANCELLED") else now)
        stages.append(
            StageDurationOut(
                status=h["to_status"],
                entered_at=entered,
                left_at=left,
                duration_seconds=max(int((end - entered).total_seconds()), 0),
                by_name=h["by_name"],
            )
        )
    total = 0
    if history:
        first: datetime = history[0]["at"]
        last = history[-1]
        end = last["at"] if last["to_status"] in ("CLOSED", "CANCELLED") else now
        total = max(int((end - first).total_seconds()), 0)
    return stages, total
