"""Custody transfer engine (master plan §2.2 Stage-2, §8.5, DD r44-r46, prompts P2-04 / P3-01).

Two-phase custody transfer used for every custody move from Phase 3 on (BR-21, G-09):

* **initiate** — the custodian of the source puts lots on a transfer; the quantities move to the
  TRANSIT location (TRANSFER_OUT) in the same transaction. Neither party holds them now. The
  receiver gets a task and a (Realtime) notification. Pending (BP) lots are refused (G-08, 422).
* **accept** — the custodian of the destination counts every line. `ACCEPTED_VERIFIED` (DD r45)
  needs every count = qty sent → TRANSFER_IN to the destination. Any mismatch is `DISCREPANCY`
  (DD r46): the stock stays frozen in TRANSIT (G-09) and the initiator + RM are alerted.
* **reconcile** — initiator and receiver both sign the same resolution (two signatures), or an RM
  overrides (audited). CANCEL_RETURN / RESEND_CORRECTED / ACCEPT_COUNTED_WITH_ADJUSTMENT. Any
  ADJUST movement (loss write-off, excess) needs the RM's approval with a reason.
* **cancel** — the initiator only, while INITIATED → back to the source.

Segregation of duties (`segregation_of_duties_transfer`, §9.3): the initiator never accepts.
The database repeats every G-09 rule (migration 20261104000100). Stock only moves through
`ledger_service` (rms_move_stock) with deterministic per-transfer idempotency keys (G-16).

P2-04's minimal functions (`propose_transfer`, `cancel_proposal`) stay: a CSR "forward to Sahil
with packaging" proposal is taken over by the Step-4 handover (`stock_moved` false → true).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import UnitOfWork
from app.core.errors import (
    Conflict,
    NotFound,
    PermissionDenied,
    SystemGuardUnmet,
    SystemGuardViolation,
    ValidationFailed,
)
from app.core.idempotency import IdempotencyKey, IdempotentResult, run_idempotent
from app.core.permissions import EffectivePermissions
from app.core.security import CurrentUser
from app.modules.closure import service as closure_service
from app.modules.custody import repository as repo
from app.modules.custody.schemas import (
    AcceptIn,
    ApproveAdjustmentIn,
    BlockOut,
    CancelIn,
    ClassifyIn,
    ClassifyOut,
    ExcludedOut,
    HandoverIn,
    HandoverLineOut,
    HandoverPreviewOut,
    InitiateIn,
    LookupsOut,
    OptionOut,
    ReconcileIn,
    ReconciliationOut,
    StoreStockOut,
    StoreStockRow,
    TransferDetailOut,
    TransferLineIn,
    TransferLineOut,
    TransferNoteOut,
    TransferPage,
    TransferPermissions,
    TransferSummaryOut,
)
from app.modules.goods_slips import service as gs_service
from app.modules.inventory import ledger_service
from app.modules.notifications import service as notifications
from app.shared.guards import guard_g04, guard_g05, guard_g08, guard_g12
from app.shared.pagination import Page

log = structlog.get_logger(__name__)

DEFAULT_MODE = "PHYSICAL_AND_DIGITAL"  # DD r44 option code
DEFAULT_TIMEZONE = "Asia/Kolkata"

# Stable codes (§3.2 / §8.5). Business logic keys off codes, never labels (CLAUDE.md rule e).
ACCEPTED_VERIFIED = "ACCEPTED_VERIFIED"  # DD r45
DISCREPANCY = "DISCREPANCY"  # DD r46
STAGING = "INWARD_STAGING"
INTERMEDIATE_STORE = "INTERMEDIATE_STORE"
TRANSIT_CLASS = "TRANSIT"
HANDOVER_STEP = "S2_HANDOVER"
HANDOVER_PURPOSE = "STEP4_HANDOVER"
CSR_PURPOSE = "CSR_WITH_PACKAGING"
INITIATE_FORM, MODE_FIELD = "S2_HANDOVER_INITIATE", "transfer_mode"
ACCEPT_FORM, ACCEPT_FIELD, DISCREPANCY_FIELD = (
    "S2_HANDOVER_ACCEPT",
    "acceptance_status",
    "discrepancy_reason",
)
ENTITY = "custody_transfer"
STATUSES = ["INITIATED", "ACCEPTED", "DISCREPANCY", "RECONCILED", "CANCELLED"]
LIVE_STATUSES = frozenset({"INITIATED", "DISCREPANCY"})
FUNCTIONAL_CONDITIONS = frozenset({"AS_RECEIVED", "FUNCTIONAL_GOOD", "FUNCTIONAL_REPAIRED"})
SELLABLE = "SELLABLE"  # DEC-14 routing destination (condition_routing_table)

# Engine resolution / disposition codes (system codes of the reconciliation workflow, like the
# transfer statuses; not workbook dropdowns — see docs/DECISIONS.md P3-01).
RESOLUTIONS: dict[str, tuple[str, str]] = {
    "RESEND_CORRECTED": (
        "Resend corrected",
        "Every piece returns to the sender, who dispatches a corrected transfer.",
    ),
    "ACCEPT_COUNTED_WITH_ADJUSTMENT": (
        "Accept counted quantity",
        "The counted pieces are accepted; the difference returns to the sender or is written "
        "off as a loss (RM approval with reason).",
    ),
    "CANCEL_RETURN": (
        "Cancel and return",
        "The transfer is cancelled and every piece returns to the sender.",
    ),
}
DISPOSITIONS: dict[str, str] = {
    "RETURN_TO_SOURCE": "Return the difference to the sender",
    "WRITE_OFF_LOSS": "Write off the difference as a loss (RM approval)",
}


# =============================================================================================
# P2-04 minimal functions (kept unchanged in behaviour)
# =============================================================================================
@dataclass(frozen=True, slots=True)
class ProposedLine:
    lot_id: UUID
    qty: int


def propose_transfer(
    session: Session,
    *,
    gs_id: UUID | None,
    from_location_code: str,
    to_location_code: str,
    lines: list[ProposedLine],
    purpose_code: str | None,
    with_packaging: bool,
    notes: str | None,
    by: UUID,
) -> UUID:
    """Record a transfer proposal (status INITIATED, stock not yet moved).

    Every line must be covered by the lot's balance at the source and must not be Pending (G-08).
    The stock itself only moves when the engine dispatches the transfer (`take_over_proposal`).
    """
    if not lines:
        raise ValidationFailed("A transfer needs at least one line", code="TRANSFER_EMPTY")
    source = ledger_service.get_location_by_code(session, from_location_code)
    target = ledger_service.get_location_by_code(session, to_location_code)
    if not source or not target:
        raise NotFound("Transfer location not configured", code="LOCATION_NOT_FOUND")
    for line in lines:
        lot = ledger_service.get_lot(session, line.lot_id)
        if not lot or (gs_id is not None and lot["gs_id"] != gs_id):
            raise NotFound("Lot not found on this goods slip")
        if lot["is_pending"]:
            raise SystemGuardViolation("G-08", "Pending (BP) quantity cannot be transferred")
        balance = ledger_service.get_balance(session, line.lot_id, source["id"])
        if line.qty <= 0 or line.qty > balance:
            raise ValidationFailed(
                f"Lot holds {balance} at {source['code']}; cannot propose {line.qty}",
                code="TRANSFER_QTY_INVALID",
            )
    transfer_id = repo.insert_transfer(
        session,
        transfer_no=_next_transfer_no(session),
        gs_id=gs_id,
        from_location_id=source["id"],
        to_location_id=target["id"],
        mode_code=DEFAULT_MODE,
        purpose_code=purpose_code,
        with_packaging=with_packaging,
        notes=notes,
        by=by,
    )
    for line in lines:
        repo.insert_line(session, transfer_id=transfer_id, lot_id=line.lot_id, qty_sent=line.qty)
    return transfer_id


def cancel_proposal(session: Session, transfer_id: UUID, *, reason: str) -> None:
    """Withdraw a proposal whose stock never moved (e.g. an admin reopened the CSR decision)."""
    transfer = repo.get_transfer(session, transfer_id, for_update=True)
    if not transfer:
        raise NotFound("Transfer not found")
    if transfer["status"] != "INITIATED" or transfer["stock_moved"]:
        raise Conflict(
            "Only an initiated transfer whose stock has not moved can be withdrawn",
            code="TRANSFER_IN_PROGRESS",
            details={"transfer_no": transfer["transfer_no"], "status": transfer["status"]},
        )
    repo.set_status(session, transfer_id, "CANCELLED", reason)


def transfers_for_gs(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    """Transfers of a GS with their lines (read model for the GS screens)."""
    transfers = repo.transfers_for_gs(session, gs_id)
    lines = repo.lines_for_transfers(session, [t["id"] for t in transfers])
    for t in transfers:
        t["lines"] = [ln for ln in lines if ln["transfer_id"] == t["id"]]
    return transfers


# =============================================================================================
# P3-01 · engine (service-to-service API: every function runs inside the caller's transaction)
# =============================================================================================
def is_custodian(session: Session, user: CurrentUser, location: dict[str, Any]) -> bool:
    """Custodian = the location's custodian user or a holder of its custodian role (§8.2)."""
    if user.is_super_admin or location.get("custodian_user_id") == user.id:
        return True
    return repo.user_has_role_id(session, user.id, location.get("custodian_role_id"))


def may_override(session: Session, user: CurrentUser, perms: EffectivePermissions) -> bool:
    """RM override / adjustment approval: `custody.approve` + a role in `custody_override_roles`."""
    if not perms.allows("custody", "approve"):
        return False
    if user.is_super_admin:
        return True
    roles = repo.get_setting(session, "custody_override_roles")
    return bool(set(roles if isinstance(roles, list) else []) & user.role_codes)


def initiate_transfer(
    session: Session,
    *,
    actor: CurrentUser,
    from_location_code: str,
    to_location_code: str,
    lines: list[TransferLineIn],
    mode_code: str = DEFAULT_MODE,
    gs_id: UUID | None = None,
    purpose_code: str | None = None,
    with_packaging: bool = False,
    notes: str | None = None,
    check_custodian: bool = True,
    initiated_by: UUID | None = None,
    supersedes_transfer_id: UUID | None = None,
    task_step_code: str = HANDOVER_STEP,
) -> UUID:
    """Create a transfer and dispatch its quantities to TRANSIT (one transaction)."""
    source = _location(session, from_location_code)
    target = _location(session, to_location_code)
    transit = _transit(session)
    if TRANSIT_CLASS in (source["location_class"], target["location_class"]):
        raise ValidationFailed(
            "TRANSIT is the engine's own location; choose a real source and destination",
            code="TRANSFER_LOCATION_INVALID",
        )
    if source["id"] == target["id"]:
        raise ValidationFailed(
            "Source and destination must differ", code="TRANSFER_LOCATION_INVALID"
        )
    if check_custodian and not is_custodian(session, actor, source):
        raise PermissionDenied(
            f"Only the custodian of {source['name']} may initiate this transfer",
            code="NOT_LOCATION_CUSTODIAN",
            details={"location_code": source["code"]},
        )
    if not lines:
        raise ValidationFailed("A transfer needs at least one line", code="TRANSFER_EMPTY")
    mode = _form_option(session, INITIATE_FORM, MODE_FIELD, mode_code)
    seen: set[UUID] = set()
    for line in lines:
        if line.lot_id in seen:
            raise ValidationFailed(
                "Each lot may appear only once on a transfer",
                code="TRANSFER_DUPLICATE_LOT",
                details={"lot_id": str(line.lot_id)},
            )
        seen.add(line.lot_id)
        lot = repo.lot_detail(session, line.lot_id, for_update=True)
        if not lot or (gs_id is not None and lot["gs_id"] != gs_id):
            raise NotFound("Lot not found on this goods slip", code="LOT_NOT_FOUND")
        _assert_lot_may_move(lot, transit, target)
        balance = ledger_service.get_balance(session, line.lot_id, source["id"])
        if line.qty > balance:
            raise ValidationFailed(
                f"The lot holds {balance} at {source['name']}; cannot send {line.qty}",
                code="TRANSFER_QTY_INVALID",
                details={"lot_id": str(line.lot_id), "available": balance, "qty": line.qty},
            )
    transfer_id = repo.insert_transfer(
        session,
        transfer_no=_next_transfer_no(session),
        gs_id=gs_id,
        from_location_id=source["id"],
        to_location_id=target["id"],
        mode_code=mode["code"],
        purpose_code=purpose_code,
        with_packaging=with_packaging,
        notes=_clean(notes),
        by=initiated_by or actor.id,
        supersedes_transfer_id=supersedes_transfer_id,
        initiate_form_version_id=mode["form_version_id"],
        labels_snapshot={MODE_FIELD: mode["snapshot"]},
    )
    for line in lines:
        repo.insert_line(session, transfer_id=transfer_id, lot_id=line.lot_id, qty_sent=line.qty)
    _dispatch(session, transfer_id, actor_id=actor.id, task_step_code=task_step_code)
    return transfer_id


def take_over_proposal(
    session: Session,
    transfer_id: UUID,
    *,
    actor: CurrentUser,
    mode_code: str,
    notes: str | None,
) -> None:
    """P2-04 CSR proposal → engine flow: the sender becomes the initiator and the proposed
    quantities move to TRANSIT now (BR-09 "forward to Sahil with packaging")."""
    transfer = _locked(session, transfer_id)
    if transfer["status"] != "INITIATED" or transfer["stock_moved"]:
        raise Conflict(
            "This transfer has already been dispatched",
            code="TRANSFER_ALREADY_DISPATCHED",
            details={"transfer_no": transfer["transfer_no"], "status": transfer["status"]},
        )
    source = _location(session, transfer["from_location_code"])
    target = _location(session, transfer["to_location_code"])
    if not is_custodian(session, actor, source):
        raise PermissionDenied(
            f"Only the custodian of {source['name']} may dispatch this transfer",
            code="NOT_LOCATION_CUSTODIAN",
        )
    transit = _transit(session)
    for line in repo.lines_for_transfers(session, [transfer_id]):
        lot = repo.lot_detail(session, line["lot_id"], for_update=True)
        if not lot:
            raise NotFound("Lot not found", code="LOT_NOT_FOUND")
        _assert_lot_may_move(lot, transit, target)
    mode = _form_option(session, INITIATE_FORM, MODE_FIELD, mode_code)
    repo.take_over_proposal(
        session,
        transfer_id,
        by=actor.id,
        mode_code=mode["code"],
        form_version_id=mode["form_version_id"],
        labels={MODE_FIELD: mode["snapshot"]},
        notes=_clean(notes),
    )
    _dispatch(session, transfer_id, actor_id=actor.id, task_step_code=HANDOVER_STEP)


def auto_transfer(
    session: Session,
    *,
    actor: CurrentUser,
    from_location_code: str,
    to_location_code: str,
    lines: list[TransferLineIn],
    purpose_code: str,
    notes: str | None = None,
    gs_id: UUID | None = None,
    accepted_on_behalf_of: str | None = None,
) -> UUID:
    """Execute an atomic custody transfer with immediate auto-acceptance (DEC-34).
    Dispatches source -> TRANSIT -> target in a single transaction."""
    transfer_id = initiate_transfer(
        session,
        actor=actor,
        from_location_code=from_location_code,
        to_location_code=to_location_code,
        lines=lines,
        purpose_code=purpose_code,
        notes=notes,
        gs_id=gs_id,
        check_custodian=False,
    )
    transfer = _locked(session, transfer_id)
    accept_opt = _form_option(session, ACCEPT_FORM, ACCEPT_FIELD, ACCEPTED_VERIFIED)

    for ln in lines:
        repo.set_line_count(session, transfer_id, ln.lot_id, ln.qty)

    labels: dict[str, Any] = {ACCEPT_FIELD: accept_opt["snapshot"]}
    repo.set_received(
        session,
        transfer_id,
        status="ACCEPTED",
        acceptance_code=ACCEPTED_VERIFIED,
        by=actor.id,
        discrepancy_notes=None,
        accept_form_version_id=accept_opt["form_version_id"],
        labels=labels,
    )
    if accepted_on_behalf_of:
        session.execute(
            text(
                "update public.custody_transfers "
                "set accepted_on_behalf_of = :on_behalf where id = :id"
            ),
            {"on_behalf": accepted_on_behalf_of, "id": transfer_id},
        )
    transfer_lines = repo.lines_for_transfers(session, [transfer_id])
    for tln in transfer_lines:
        _move(
            session,
            transfer,
            tln,
            "accept",
            to=transfer["to_location_id"],
            qty=tln["qty_sent"],
            actor=actor.id,
        )
        repo.add_line_outcome(session, transfer_id, tln["lot_id"], accepted=tln["qty_sent"])
    _close_receiver_task(session, transfer)
    _sync_closure(session, transfer_id)
    return transfer_id


def accept_transfer(
    session: Session,
    *,
    user: CurrentUser,
    perms: EffectivePermissions,
    transfer_id: UUID,
    payload: AcceptIn,
) -> None:
    transfer = _locked(session, transfer_id)
    if transfer["status"] != "INITIATED" or not transfer["stock_moved"]:
        raise Conflict(
            "This transfer is not waiting for acceptance",
            code="TRANSFER_NOT_AWAITING_ACCEPTANCE",
            details={"transfer_no": transfer["transfer_no"], "status": transfer["status"]},
        )
    target = _location(session, transfer["to_location_code"])
    if not perms.allows("custody", "approve") or not is_custodian(session, user, target):
        raise PermissionDenied(
            f"Only the custodian of {target['name']} may count and accept this transfer",
            code="NOT_LOCATION_CUSTODIAN",
        )
    _assert_segregation(session, transfer, user)
    lines = repo.lines_for_transfers(session, [transfer_id])
    counts = {c.lot_id: c.qty_counted for c in payload.lines}
    if len(counts) != len(payload.lines) or set(counts) != {ln["lot_id"] for ln in lines}:
        raise ValidationFailed(
            "Count every line of the transfer exactly once", code="TRANSFER_COUNT_LINES"
        )
    option = _form_option(session, ACCEPT_FORM, ACCEPT_FIELD, payload.acceptance_code)
    mismatches = [
        {"lot_id": str(ln["lot_id"]), "line_no": ln["line_no"], "qty_counted": counts[ln["lot_id"]]}
        for ln in lines
        if counts[ln["lot_id"]] != ln["qty_sent"]
    ]
    notes = _clean(payload.notes)
    if option["code"] == ACCEPTED_VERIFIED:
        if mismatches:
            # G-09 / DD r45: a mismatched count can never be accepted; it halts the transfer.
            raise ValidationFailed(
                "The physical count differs from the transfer; report a discrepancy instead",
                code="TRANSFER_COUNT_MISMATCH",
                details={"lines": mismatches},
            )
    elif option["code"] == DISCREPANCY:
        if not mismatches:
            raise ValidationFailed(
                "Every count matches the transfer; accept it instead",
                code="TRANSFER_NO_DISCREPANCY",
            )
        if not notes:
            raise ValidationFailed(
                "Describe the discrepancy",
                code="FORM_VALIDATION_FAILED",
                details={DISCREPANCY_FIELD: ["Required when a discrepancy is reported"]},
            )
    else:
        raise ValidationFailed(
            "This acceptance status is not handled by the custody engine",
            code="ACCEPTANCE_CODE_UNSUPPORTED",
            details={"acceptance_code": option["code"]},
        )
    for ln in lines:
        repo.set_line_count(session, transfer_id, ln["lot_id"], counts[ln["lot_id"]])
    labels: dict[str, Any] = {ACCEPT_FIELD: option["snapshot"]}
    if notes:
        labels[DISCREPANCY_FIELD] = {
            "label": _field_label(option["form_snapshot"], DISCREPANCY_FIELD),
            "value": notes,
        }
    accepted = option["code"] == ACCEPTED_VERIFIED
    repo.set_received(
        session,
        transfer_id,
        status="ACCEPTED" if accepted else "DISCREPANCY",
        acceptance_code=option["code"],
        by=user.id,
        discrepancy_notes=None if accepted else notes,
        accept_form_version_id=option["form_version_id"],
        labels=labels,
    )
    if accepted:
        for ln in lines:
            _move(
                session, transfer, ln, "accept", to=transfer["to_location_id"], qty=ln["qty_sent"]
            )
            repo.add_line_outcome(session, transfer_id, ln["lot_id"], accepted=ln["qty_sent"])
        _close_receiver_task(session, transfer)
        notifications.publish(
            session,
            "TRANSFER_ACCEPTED",
            user_ids=[transfer["initiated_by"]],
            notification_type="TRANSFER_ACCEPTED",
            title=f"{transfer['transfer_no']} accepted by {user.full_name}",
            body=f"Received in {transfer['to_location_name']}",
            entity_type=ENTITY,
            entity_id=transfer_id,
        )
        # Phase 5 (AMD-13): Intermediate store accepts transfer
        # -> GS status "HELD_AT_INTERMEDIATE_STORE"
        if transfer.get("gs_id") and transfer.get("to_location_code") == "INTERMEDIATE_STORE":
            gs = gs_service.lock_goods_slip(session, transfer["gs_id"])
            if gs and gs.get("status") == "RM_REVIEW":
                gs_service.change_status_within_step(
                    session,
                    gs_id=transfer["gs_id"],
                    from_status=gs["status"],
                    to_status="HELD_AT_INTERMEDIATE_STORE",
                    step_code="S1_ITEMIZE",
                    reason=f"Accepted at Intermediate Store by {user.full_name} (AMD-13)",
                    by=user.id,
                )
    else:
        # DD r46 / G-09: halt — the stock stays frozen in TRANSIT until reconciled.
        _notify(
            session,
            transfer,
            user_ids=[transfer["initiated_by"], *_override_user_ids(session)],
            type_="TRANSFER_DISCREPANCY",
            title=f"{transfer['transfer_no']}: discrepancy reported",
            body=notes,
            priority="HIGH",
        )
    _after_change(session, transfer)
    log.info(
        "custody_transfer_counted",
        transfer_id=str(transfer_id),
        outcome=option["code"],
        mismatched_lines=len(mismatches),
    )


def reconcile_transfer(
    session: Session,
    *,
    user: CurrentUser,
    perms: EffectivePermissions,
    transfer_id: UUID,
    payload: ReconcileIn,
) -> None:
    transfer = _locked(session, transfer_id)
    if transfer["status"] != "DISCREPANCY":
        raise Conflict(
            "Only a transfer with a reported discrepancy can be reconciled",
            code="TRANSFER_NOT_IN_DISCREPANCY",
            details={"transfer_no": transfer["transfer_no"], "status": transfer["status"]},
        )
    lines = repo.lines_for_transfers(session, [transfer_id])
    disposition, resend_lines = _validate_resolution(payload, lines)
    requires_rm = _requires_rm_approval(payload.resolution_code, disposition, lines)
    notes = payload.notes.strip()
    current = repo.open_reconciliation(session, transfer_id)

    if payload.override:
        if not may_override(session, user, perms):
            raise PermissionDenied(
                "Only the Replacement Manager may override a reconciliation",
                code="OVERRIDE_NOT_ALLOWED",
            )
        if current:
            repo.set_reconciliation_status(session, current["id"], "SUPERSEDED")
        # G-17: the override and its reason are on every audit row of this transaction.
        gs_service.set_audit_reason(session, f"RM OVERRIDE (custody reconciliation): {notes}")
        recon_id = repo.insert_reconciliation(
            session,
            transfer_id=transfer_id,
            resolution_code=payload.resolution_code,
            difference_disposition=disposition,
            resend_lines=resend_lines,
            notes=notes,
            requires_rm_approval=requires_rm,
            by=user.id,
        )
        repo.rm_approve_reconciliation(session, recon_id, by=user.id, reason=notes, override=True)
        _apply_reconciliation(session, user, transfer, recon_id)
        gs_service.set_audit_reason(session, None)
        log.info("custody_reconciliation_override", transfer_id=str(transfer_id))
        return

    side = party_side(session, user, transfer)
    if side is None:
        raise PermissionDenied(
            "Only the initiator and the receiver of this transfer may reconcile it",
            code="NOT_TRANSFER_PARTY",
        )
    same = current is not None and _same_proposal(
        current, payload.resolution_code, disposition, resend_lines
    )
    if current is not None and not same:
        repo.set_reconciliation_status(session, current["id"], "SUPERSEDED")
        current = None
    if current is None:
        recon_id = repo.insert_reconciliation(
            session,
            transfer_id=transfer_id,
            resolution_code=payload.resolution_code,
            difference_disposition=disposition,
            resend_lines=resend_lines,
            notes=notes,
            requires_rm_approval=requires_rm,
            by=user.id,
        )
    else:
        recon_id = current["id"]
        signed_by = current["initiator_signed_by" if side == "INITIATOR" else "receiver_signed_by"]
        if signed_by is not None:
            raise Conflict(
                "Your side has already signed this resolution; waiting for the other party",
                code="RECONCILIATION_ALREADY_SIGNED",
            )
        other = current["receiver_signed_by" if side == "INITIATOR" else "initiator_signed_by"]
        if other == user.id:
            raise PermissionDenied(
                "The same person cannot sign for both parties", code="SEGREGATION_OF_DUTIES"
            )
    repo.sign_reconciliation(session, recon_id, side=side, by=user.id)
    recon = _reconciliation(session, transfer_id, recon_id)
    if recon["initiator_signed_by"] and recon["receiver_signed_by"]:
        if recon["requires_rm_approval"] and not recon["rm_approved_by"]:
            repo.set_reconciliation_status(session, recon_id, "AWAITING_RM_APPROVAL")
            _notify(
                session,
                transfer,
                user_ids=_override_user_ids(session),
                type_="TRANSFER_ADJUSTMENT_APPROVAL",
                title=f"{transfer['transfer_no']}: stock adjustment needs your approval",
                body=notes,
                priority="HIGH",
            )
        else:
            _apply_reconciliation(session, user, transfer, recon_id)
    else:
        counterpart = (
            _custodian_ids(session, transfer["to_location_id"])
            if side == "INITIATOR"
            else [transfer["initiated_by"]]
        )
        _notify(
            session,
            transfer,
            user_ids=[u for u in counterpart if u != user.id],
            type_="TRANSFER_RECONCILIATION_PROPOSED",
            title=f"{transfer['transfer_no']}: confirm the reconciliation",
            body=f"{RESOLUTIONS[payload.resolution_code][0]} — {notes}",
        )


def approve_adjustment(
    session: Session,
    *,
    user: CurrentUser,
    perms: EffectivePermissions,
    transfer_id: UUID,
    payload: ApproveAdjustmentIn,
) -> None:
    transfer = _locked(session, transfer_id)
    if not may_override(session, user, perms):
        raise PermissionDenied(
            "Only the Replacement Manager approves custody stock adjustments",
            code="OVERRIDE_NOT_ALLOWED",
        )
    current = repo.open_reconciliation(session, transfer_id)
    if (
        transfer["status"] != "DISCREPANCY"
        or not current
        or current["status"] != "AWAITING_RM_APPROVAL"
    ):
        raise Conflict(
            "No signed reconciliation is waiting for approval",
            code="NO_ADJUSTMENT_PENDING",
        )
    reason = payload.reason.strip()
    gs_service.set_audit_reason(session, f"Custody adjustment approved: {reason}")
    repo.rm_approve_reconciliation(
        session, current["id"], by=user.id, reason=reason, override=False
    )
    _apply_reconciliation(session, user, transfer, current["id"])
    gs_service.set_audit_reason(session, None)


def cancel_transfer(session: Session, *, user: CurrentUser, transfer_id: UUID, reason: str) -> None:
    transfer = _locked(session, transfer_id)
    if transfer["status"] != "INITIATED":
        raise Conflict(
            "Only a transfer that has not been counted can be cancelled",
            code="TRANSFER_NOT_CANCELLABLE",
            details={"transfer_no": transfer["transfer_no"], "status": transfer["status"]},
        )
    if transfer["initiated_by"] != user.id:
        raise PermissionDenied(
            "Only the initiator may cancel this transfer", code="NOT_TRANSFER_INITIATOR"
        )
    reason = reason.strip()
    repo.set_cancelled(session, transfer_id, by=user.id, reason=reason)
    if transfer["stock_moved"]:
        for ln in repo.lines_for_transfers(session, [transfer_id]):
            _move(
                session, transfer, ln, "cancel", to=transfer["from_location_id"], qty=ln["qty_sent"]
            )
            repo.add_line_outcome(session, transfer_id, ln["lot_id"], returned=ln["qty_sent"])
    _close_receiver_task(session, transfer, cancelled=True)
    _notify(
        session,
        transfer,
        user_ids=_custodian_ids(session, transfer["to_location_id"]),
        type_="TRANSFER_CANCELLED",
        title=f"{transfer['transfer_no']} cancelled by {user.full_name}",
        body=reason,
    )
    _after_change(session, transfer)


def party_side(session: Session, user: CurrentUser, transfer: dict[str, Any]) -> str | None:
    """INITIATOR (the sender or another custodian of the source) or RECEIVER (a custodian of the
    destination who is not the initiator)."""
    if user.id == transfer["initiated_by"]:
        return "INITIATOR"
    to_loc = {
        "custodian_user_id": transfer["to_custodian_user_id"],
        "custodian_role_id": transfer["to_custodian_role_id"],
    }
    if is_custodian(session, user, to_loc):
        return "RECEIVER"
    from_loc = {
        "custodian_user_id": transfer["from_custodian_user_id"],
        "custodian_role_id": transfer["from_custodian_role_id"],
    }
    if is_custodian(session, user, from_loc):
        return "INITIATOR"
    return None


# --- engine internals --------------------------------------------------------------------------
def _dispatch(session: Session, transfer_id: UUID, *, actor_id: UUID, task_step_code: str) -> None:
    """Phase 1: every line from the source into TRANSIT; receiver task + notification."""
    transit = _transit(session)
    repo.mark_dispatched(session, transfer_id, transit["id"])
    transfer = _locked(session, transfer_id)
    for ln in repo.lines_for_transfers(session, [transfer_id]):
        _move(
            session, transfer, ln, "dispatch", to=transit["id"], qty=ln["qty_sent"], actor=actor_id
        )
    if transfer["gs_id"]:
        task_id = gs_service.open_task(
            session,
            gs_id=transfer["gs_id"],
            step_code=task_step_code,
            role_id=transfer["to_custodian_role_id"],
            user_id=None if transfer["to_custodian_role_id"] else transfer["to_custodian_user_id"],
        )
        repo.set_receiver_task(session, transfer_id, task_id)
    _notify(
        session,
        transfer,
        user_ids=_custodian_ids(session, transfer["to_location_id"]),
        type_="TRANSFER_INITIATED",
        title=f"{transfer['transfer_no']}: goods in transit to {transfer['to_location_name']}",
        body=(
            f"From {transfer['from_location_name']}"
            + (f" · GS {transfer['gs_no']}" if transfer["gs_no"] else "")
            + " — count and accept"
        ),
    )
    _after_change(session, transfer)
    log.info("custody_transfer_dispatched", transfer_id=str(transfer_id))


def _apply_reconciliation(
    session: Session, user: CurrentUser, transfer: dict[str, Any], recon_id: UUID
) -> None:
    recon = _reconciliation(session, transfer["id"], recon_id)
    repo.set_reconciliation_status(session, recon_id, "APPLIED")
    repo.set_reconciled(session, transfer["id"], recon["resolution_code"])
    lines = repo.lines_for_transfers(session, [transfer["id"]])
    code = recon["resolution_code"]
    resend_id: UUID | None = None
    if code in ("CANCEL_RETURN", "RESEND_CORRECTED"):
        for ln in lines:
            _move(
                session, transfer, ln, "return", to=transfer["from_location_id"], qty=ln["qty_sent"]
            )
            repo.add_line_outcome(session, transfer["id"], ln["lot_id"], returned=ln["qty_sent"])
        if code == "RESEND_CORRECTED" and recon["resend_lines"]:
            resend_id = initiate_transfer(
                session,
                actor=user,
                from_location_code=transfer["from_location_code"],
                to_location_code=transfer["to_location_code"],
                lines=[TransferLineIn.model_validate(x) for x in recon["resend_lines"]],
                mode_code=transfer["mode_code"],
                gs_id=transfer["gs_id"],
                purpose_code=transfer["purpose_code"],
                with_packaging=transfer["with_packaging"],
                notes=f"Corrected resend of {transfer['transfer_no']}: {recon['notes']}",
                check_custodian=False,
                initiated_by=transfer["initiated_by"],
                supersedes_transfer_id=transfer["id"],
            )
            repo.set_reconciliation_status(
                session, recon_id, "APPLIED", resend_transfer_id=resend_id
            )
    else:  # ACCEPT_COUNTED_WITH_ADJUSTMENT
        reason = recon["rm_reason"] or recon["notes"]
        for ln in lines:
            sent, counted = ln["qty_sent"], ln["qty_counted"]
            accepted = min(sent, counted)
            if accepted:
                _move(session, transfer, ln, "accept", to=transfer["to_location_id"], qty=accepted)
                repo.add_line_outcome(session, transfer["id"], ln["lot_id"], accepted=accepted)
            short = sent - accepted
            if short and recon["difference_disposition"] == "RETURN_TO_SOURCE":
                _move(session, transfer, ln, "return", to=transfer["from_location_id"], qty=short)
                repo.add_line_outcome(session, transfer["id"], ln["lot_id"], returned=short)
            elif short:
                _move(
                    session, transfer, ln, "loss", to=None, qty=short, type_="ADJUST", reason=reason
                )
                repo.add_line_outcome(session, transfer["id"], ln["lot_id"], adjusted=-short)
            excess = counted - sent
            if excess > 0:
                ledger_service.move_stock(
                    session,
                    lot_id=ln["lot_id"],
                    from_location_id=None,
                    to_location_id=transfer["to_location_id"],
                    qty=excess,
                    movement_type="ADJUST",
                    reference_type=ENTITY,
                    reference_id=transfer["id"],
                    idempotency_key=f"custody:{transfer['id']}:{ln['lot_id']}:excess",
                    actor_id=user.id,
                    reason=f"Excess counted on {transfer['transfer_no']} (RM approved): {reason}",
                )
                repo.add_line_outcome(session, transfer["id"], ln["lot_id"], adjusted=excess)
    _close_receiver_task(session, transfer)
    parties = [transfer["initiated_by"], *_custodian_ids(session, transfer["to_location_id"])]
    _notify(
        session,
        transfer,
        user_ids=parties,
        type_="TRANSFER_RECONCILED",
        title=f"{transfer['transfer_no']} reconciled: {RESOLUTIONS[code][0]}",
        body=recon["notes"],
    )
    _after_change(session, transfer)
    log.info(
        "custody_transfer_reconciled",
        transfer_id=str(transfer["id"]),
        resolution=code,
        rm_override=bool(recon["is_rm_override"]),
        resend_transfer_id=str(resend_id) if resend_id else None,
    )


def _move(
    session: Session,
    transfer: dict[str, Any],
    line: dict[str, Any],
    event: str,
    *,
    to: UUID | None,
    qty: int,
    type_: str | None = None,
    reason: str | None = None,
    actor: UUID | None = None,
) -> None:
    """One ledger movement of a transfer line. The key is deterministic per transfer + lot +
    event, so a replay can never move the stock twice (G-16)."""
    if qty <= 0:
        return
    dispatch = event == "dispatch"
    ledger_service.move_stock(
        session,
        lot_id=line["lot_id"],
        from_location_id=transfer["from_location_id"]
        if dispatch
        else transfer["transit_location_id"],
        to_location_id=to,
        qty=qty,
        movement_type=type_ or ("TRANSFER_OUT" if dispatch else "TRANSFER_IN"),
        reference_type=ENTITY,
        reference_id=transfer["id"],
        idempotency_key=f"custody:{transfer['id']}:{line['lot_id']}:{event}",
        actor_id=actor,
        reason=reason or f"{transfer['transfer_no']} {event}",
    )


def _assert_lot_may_move(
    lot: dict[str, Any], transit: dict[str, Any], target: dict[str, Any]
) -> None:
    """Service half of the location guards; rms_move_stock repeats them (G-04/G-05/G-08/G-12)."""
    ctx = {
        "condition_class": lot["condition_class"],
        "source_condition_code": lot["source_condition_code"],
        "is_pending": lot["is_pending"],
    }
    if lot["is_pending"] or not guard_g08(
        SimpleNamespace(context={**ctx, "target_location_class": transit["location_class"]}), None
    ):
        raise SystemGuardUnmet(
            "G-08",
            "Quantities marked Pending (BP) cannot be added to a custody transfer",
            details={"lot_id": str(lot["id"])},
        )
    entity = SimpleNamespace(context={**ctx, "target_location_class": target["location_class"]})
    for guard_id, check in (("G-05", guard_g05), ("G-04", guard_g04), ("G-12", guard_g12)):
        if not check(entity, None):
            raise SystemGuardUnmet(
                guard_id,
                f"A {lot['condition_class']} lot cannot be transferred to {target['name']}",
                details={"lot_id": str(lot["id"]), "location_code": target["code"]},
            )


def _assert_segregation(session: Session, transfer: dict[str, Any], user: CurrentUser) -> None:
    sod = repo.get_setting(session, "segregation_of_duties_transfer")
    if sod is not False and transfer["initiated_by"] == user.id:
        raise PermissionDenied(
            "Segregation of duties: the initiator cannot accept their own transfer",
            code="SEGREGATION_OF_DUTIES",
        )


def _validate_resolution(
    payload: ReconcileIn, lines: list[dict[str, Any]]
) -> tuple[str | None, list[dict[str, Any]]]:
    if payload.resolution_code == "ACCEPT_COUNTED_WITH_ADJUSTMENT":
        if payload.difference_disposition is None and any(
            ln["qty_counted"] < ln["qty_sent"] for ln in lines
        ):
            raise ValidationFailed(
                "Choose what happens to the pieces that were not counted",
                code="FORM_VALIDATION_FAILED",
                details={"difference_disposition": ["Required"]},
            )
        disposition = payload.difference_disposition or "RETURN_TO_SOURCE"
    else:
        disposition = None
    if payload.resolution_code != "RESEND_CORRECTED":
        if payload.resend_lines:
            raise ValidationFailed(
                "Corrected lines apply only to a resend", code="FORM_VALIDATION_FAILED"
            )
        return disposition, []
    lot_ids = {ln["lot_id"] for ln in lines}
    chosen = payload.resend_lines
    if chosen is None:
        chosen = [
            TransferLineIn(lot_id=ln["lot_id"], qty=ln["qty_counted"])
            for ln in lines
            if ln["qty_counted"] > 0
        ]
    if not chosen:
        raise ValidationFailed(
            "A corrected resend needs at least one line; use Cancel and return instead",
            code="TRANSFER_EMPTY",
        )
    if len({c.lot_id for c in chosen}) != len(chosen) or any(
        c.lot_id not in lot_ids for c in chosen
    ):
        raise ValidationFailed(
            "A corrected resend may only contain the lots of this transfer, once each",
            code="TRANSFER_DUPLICATE_LOT",
        )
    resend = [{"lot_id": str(c.lot_id), "qty": c.qty} for c in chosen]
    return None, sorted(resend, key=lambda x: str(x["lot_id"]))


def _requires_rm_approval(code: str, disposition: str | None, lines: list[dict[str, Any]]) -> bool:
    if code != "ACCEPT_COUNTED_WITH_ADJUSTMENT":
        return False
    loss = disposition == "WRITE_OFF_LOSS" and any(
        ln["qty_counted"] < ln["qty_sent"] for ln in lines
    )
    excess = any(ln["qty_counted"] > ln["qty_sent"] for ln in lines)
    return loss or excess


def _same_proposal(
    current: dict[str, Any], code: str, disposition: str | None, resend: list[dict[str, Any]]
) -> bool:
    stored = sorted(
        [{"lot_id": str(x["lot_id"]), "qty": int(x["qty"])} for x in current["resend_lines"] or []],
        key=lambda x: str(x["lot_id"]),
    )
    return (
        current["resolution_code"] == code
        and current["difference_disposition"] == disposition
        and stored == resend
    )


def _after_change(session: Session, transfer: dict[str, Any]) -> None:
    _after_change_gs(session, transfer)
    _sync_closure(session, transfer["id"])


def _sync_closure(session: Session, transfer_id: UUID) -> None:
    """P3-07 / §6.5: a custody command can complete the stock dispositions of a GS."""
    for gs_id in repo.gs_ids_for_transfer(session, transfer_id):
        closure_service.sync_status(session, gs_id, None)


def _after_change_gs(session: Session, transfer: dict[str, Any]) -> None:
    """GS bookkeeping after any custody command: `has_discrepancy` flag (§6.5) and the sender's
    Step-4 task (open while eligible stock waits in INWARD_STAGING)."""
    gs_id = transfer["gs_id"]
    if not gs_id:
        return
    gs_service.set_discrepancy_flag(session, gs_id, repo.gs_has_discrepancy(session, gs_id))
    staging = _location(session, STAGING)
    if transfer["from_location_id"] != staging["id"]:
        return
    gs = gs_service.lock_goods_slip(session, gs_id)
    plan = _handover_plan(session, gs)
    gs_service.sync_step_task(
        session,
        gs_id=gs_id,
        step_code=HANDOVER_STEP,
        role_id=staging["custodian_role_id"],
        needed=gs["status"] == "IN_PROCESS" and bool(plan.eligible or plan.proposal_id),
    )


def _close_receiver_task(
    session: Session, transfer: dict[str, Any], *, cancelled: bool = False
) -> None:
    task_id = repo.get_transfer(session, transfer["id"]) or {}
    if task_id.get("receiver_task_id"):
        gs_service.close_task(session, task_id["receiver_task_id"], cancelled=cancelled)


def _notify(
    session: Session,
    transfer: dict[str, Any],
    *,
    user_ids: list[UUID],
    type_: str,
    title: str,
    body: str | None,
    priority: str = "NORMAL",
) -> None:
    unique = list(dict.fromkeys(u for u in user_ids if u))
    if unique:
        notifications.publish(
            session,
            type_,  # custody notification types are the event codes (P4-03)
            user_ids=unique,
            notification_type=type_,
            title=title,
            body=body,
            entity_type=ENTITY,
            entity_id=transfer["id"],
            priority=priority,
        )


def _custodian_ids(session: Session, location_id: UUID) -> list[UUID]:
    return repo.custodian_user_ids(session, location_id)


def _override_user_ids(session: Session) -> list[UUID]:
    roles = repo.get_setting(session, "custody_override_roles")
    codes = [str(r) for r in roles] if isinstance(roles, list) else []
    return notifications.active_user_ids_with_roles(session, codes)


def _locked(session: Session, transfer_id: UUID) -> dict[str, Any]:
    transfer = repo.get_transfer(session, transfer_id, for_update=True)
    if not transfer:
        raise NotFound("Transfer not found", code="TRANSFER_NOT_FOUND")
    return transfer


def _reconciliation(session: Session, transfer_id: UUID, recon_id: UUID) -> dict[str, Any]:
    recon = next(
        (r for r in repo.reconciliations_for(session, transfer_id) if r["id"] == recon_id), None
    )
    if not recon:
        raise NotFound("Reconciliation not found")
    return recon


def _location(session: Session, code: str) -> dict[str, Any]:
    loc = ledger_service.get_location_by_code(session, code)
    if not loc or not loc["is_active"]:
        raise NotFound(f"Inventory location {code} is not configured", code="LOCATION_NOT_FOUND")
    return loc


def _transit(session: Session) -> dict[str, Any]:
    transit = repo.location_by_class(session, TRANSIT_CLASS)
    if not transit:
        raise NotFound("No active TRANSIT location is configured", code="LOCATION_NOT_FOUND")
    return transit


def _next_transfer_no(session: Session) -> str:
    tz = repo.get_setting(session, "timezone")
    return repo.next_transfer_no(session, tz if isinstance(tz, str) else DEFAULT_TIMEZONE)


def _form(session: Session, code: str) -> dict[str, Any]:
    form = repo.get_published_form(session, code)
    if not form or not form.get("snapshot"):
        raise NotFound(f"No published {code} form", code="FORM_NOT_PUBLISHED")
    return form


def _field(snapshot: dict[str, Any], key: str) -> dict[str, Any]:
    return next((f for f in snapshot.get("fields") or [] if f.get("field_key") == key), {})


def _field_label(snapshot: dict[str, Any], key: str) -> str:
    return str(_field(snapshot, key).get("label") or key)


def _form_options(session: Session, form_code: str, field_key: str) -> list[OptionOut]:
    snapshot = dict(_form(session, form_code)["snapshot"])
    return [
        OptionOut(code=o["code"], label=o["label"], description=o.get("next_action_text"))
        for o in _field(snapshot, field_key).get("option_items") or []
        if o.get("is_active", True)
    ]


def _form_option(session: Session, form_code: str, field_key: str, code: str) -> dict[str, Any]:
    """Validate an option code against the published form (G-18: version + label snapshot)."""
    form = _form(session, form_code)
    snapshot = dict(form["snapshot"])
    field = _field(snapshot, field_key)
    option = next(
        (
            o
            for o in field.get("option_items") or []
            if o.get("code") == code and o.get("is_active", True)
        ),
        None,
    )
    if option is None:
        raise ValidationFailed(
            f"Unknown or inactive option {code!r}",
            code="FORM_VALIDATION_FAILED",
            details={field_key: [f"Choose one of the configured options (got {code!r})"]},
        )
    return {
        "code": option["code"],
        "label": option["label"],
        "form_version_id": form["id"],
        "form_snapshot": snapshot,
        "snapshot": {
            "label": str(field.get("label") or field_key),
            "value": option["code"],
            "value_label": option["label"],
        },
    }


# Service-to-service (P3-04 custody assignment): published-form option lookup with G-18 pinning.
form_option = _form_option
form_options = _form_options


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


# =============================================================================================
# Step-4 handover builder (BR-20, BR-22, WF r7 col K, DEC-12)
# =============================================================================================
@dataclass(slots=True)
class HandoverPlan:
    eligible: list[HandoverLineOut]
    excluded: list[ExcludedOut]
    proposal_id: UUID | None


def _handover_plan(session: Session, gs: dict[str, Any]) -> HandoverPlan:
    """Eligible = allowed, non-pending stock of the GS in INWARD_STAGING; everything held back is
    listed with the reason (Pending (BP), Not Allowed, Hazard, RM 'Not Allowed' action)."""
    gs_id = gs["id"]
    positions = repo.gs_lot_positions(session, gs_id)
    cond_labels = repo.condition_labels(
        session,
        sorted({p["source_condition_code"] for p in positions if p["source_condition_code"]}),
    )
    action_labels = repo.item_field_labels(session, "ACTION")  # AMD-16 action library
    pend_by_lot = {p["lot_id"]: p for p in repo.open_pendencies(session, gs_id) if p["lot_id"]}
    eligible: list[HandoverLineOut] = []
    excluded: list[ExcludedOut] = []

    def exclude(p: dict[str, Any], reason: str, label: str | None, detail: str | None) -> None:
        excluded.append(
            ExcludedOut(
                lot_id=p["lot_id"],
                gs_item_id=p["gs_item_id"],
                line_no=p["line_no"],
                product_name=p["product_name"],
                qty=int(p["qty"]),
                reason_code=reason,
                reason_label=label or reason,
                condition_label=cond_labels.get(p["source_condition_code"] or ""),
                location_code=p["location_code"],
                location_name=p["location_name"],
                detail=detail,
            )
        )

    rejected_by_item: dict[UUID, int] = {}
    for p in positions:
        cond = p["condition_class"]
        if p["is_pending"] or p["location_class"] == "PENDING_HOLD":
            pend = pend_by_lot.get(p["lot_id"])
            detail = " · ".join(x for x in (pend["reason"], pend["sent_to"]) if x) if pend else None
            exclude(p, "PENDING_BP", action_labels.get("PENDING_BP"), detail)
        elif cond == "HAZARD":
            exclude(p, "HAZARD", p["location_name"], None)
        elif cond not in FUNCTIONAL_CONDITIONS:
            exclude(p, "NOT_ALLOWED", action_labels.get("NOT_ALLOWED"), None)
        elif p["location_code"] == STAGING:
            eligible.append(
                HandoverLineOut(
                    lot_id=p["lot_id"],
                    gs_item_id=p["gs_item_id"],
                    line_no=p["line_no"],
                    product_code=p["product_code"],
                    product_name=p["product_name"],
                    condition_code=p["source_condition_code"],
                    condition_label=cond_labels.get(p["source_condition_code"] or ""),
                    routing_hint=p["routing_hint"],
                    qty=int(p["qty"]),
                )
            )
        if cond in ("NOT_ALLOWED", "HAZARD") and p["gs_item_id"]:
            rejected_by_item[p["gs_item_id"]] = rejected_by_item.get(p["gs_item_id"], 0) + int(
                p["qty"]
            )

    # WF r6: pieces the RM marked Not Allowed beyond the inspection rejections stay in staging.
    for item_id, na_qty in repo.rm_action_qty(session, gs_id, "NOT_ALLOWED").items():
        extra = na_qty - rejected_by_item.get(item_id, 0)
        for line in [e for e in eligible if e.gs_item_id == item_id]:
            if extra <= 0:
                break
            take = min(extra, line.qty)
            extra -= take
            line.qty -= take
            excluded.append(
                ExcludedOut(
                    lot_id=line.lot_id,
                    gs_item_id=item_id,
                    line_no=line.line_no,
                    product_name=line.product_name,
                    qty=take,
                    reason_code="RM_NOT_ALLOWED",
                    reason_label=action_labels.get("NOT_ALLOWED") or "NOT_ALLOWED",
                    condition_label=line.condition_label,
                    location_code=STAGING,
                    location_name=None,
                    detail="Replacement Manager action (Step-3 a)",
                )
            )
    eligible = [e for e in eligible if e.qty > 0]

    proposal_id = next(
        (
            t["id"]
            for t in repo.transfers_for_gs(session, gs_id)
            if t["status"] == "INITIATED" and not t["stock_moved"]
        ),
        None,
    )
    return HandoverPlan(eligible=eligible, excluded=excluded, proposal_id=proposal_id)


def _handover_block(session: Session, gs: dict[str, Any], plan: HandoverPlan) -> BlockOut | None:
    if gs["status"] != "IN_PROCESS":
        return BlockOut(
            code="HANDOVER_NOT_READY",
            message="Handover starts after the RM actions are finalised (or a CSR is approved)",
        )
    if repo.get_setting(session, "pending_blocks_entire_gs") is True and repo.open_pendencies(
        session, gs["id"]
    ):
        return BlockOut(
            code="G-08",
            message="Open Pending (BP) pendencies block the whole GS (pending_blocks_entire_gs)",
        )
    if not plan.eligible and not plan.proposal_id:
        return BlockOut(code="NOTHING_TO_HAND_OVER", message="No eligible stock waits in staging")
    return None


# =============================================================================================
# HTTP-facing service (one transaction per command)
# =============================================================================================
class CustodyService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    # ------------------------------------------------------------------ reads -----------------
    def lookups(self, user: CurrentUser) -> LookupsOut:
        with self._uow.transaction(user.id) as session:
            return LookupsOut(
                acceptance_options=_form_options(session, ACCEPT_FORM, ACCEPT_FIELD),
                mode_options=_form_options(session, INITIATE_FORM, MODE_FIELD),
                resolution_options=[
                    OptionOut(code=c, label=v[0], description=v[1]) for c, v in RESOLUTIONS.items()
                ],
                disposition_options=[OptionOut(code=c, label=v) for c, v in DISPOSITIONS.items()],
                blind_count=repo.get_setting(session, "transfer_blind_count") is True,
                statuses=STATUSES,
            )

    def list_transfers(
        self,
        user: CurrentUser,
        *,
        status: str | None,
        from_location_code: str | None,
        to_location_code: str | None,
        gs_id: UUID | None,
        mine_to_accept: bool,
        page: int,
        page_size: int,
    ) -> TransferPage:
        if status is not None and status not in STATUSES:
            raise ValidationFailed(f"Unknown status {status!r}", code="FILTER_INVALID")
        with self._uow.transaction(user.id) as session:
            rows, total = repo.list_transfers(
                session,
                status=status,
                from_location_code=from_location_code,
                to_location_code=to_location_code,
                gs_id=gs_id,
                to_accept_by=user.id if mine_to_accept else None,
                all_locations=user.is_super_admin,
                limit=page_size,
                offset=(page - 1) * page_size,
            )
            ctx = self._label_ctx(session)
            return Page[TransferSummaryOut](
                items=[self._summary(session, user, r, ctx) for r in rows],
                total=total,
                page=page,
                page_size=page_size,
            )

    def detail(
        self, user: CurrentUser, perms: EffectivePermissions, transfer_id: UUID
    ) -> TransferDetailOut:
        with self._uow.transaction(user.id) as session:
            return self._detail(session, user, perms, transfer_id)

    def transfer_note(
        self, user: CurrentUser, perms: EffectivePermissions, transfer_id: UUID
    ) -> TransferNoteOut:
        """Preview of the Transfer Note (no side effect); `print_transfer_note` logs a print."""
        with self._uow.transaction(user.id) as session:
            return self._note(session, user, perms, transfer_id, log_print=False)

    def print_transfer_note(
        self, user: CurrentUser, perms: EffectivePermissions, transfer_id: UUID
    ) -> TransferNoteOut:
        with self._uow.transaction(user.id) as session:
            return self._note(session, user, perms, transfer_id, log_print=True)

    def _note(
        self,
        session: Session,
        user: CurrentUser,
        perms: EffectivePermissions,
        transfer_id: UUID,
        *,
        log_print: bool,
    ) -> TransferNoteOut:
        detail = self._detail(session, user, perms, transfer_id)
        template = repo.get_published_template(session, "TRANSFER_NOTE")
        if not template:
            raise NotFound(
                "No published TRANSFER_NOTE print template", code="TEMPLATE_NOT_PUBLISHED"
            )
        if log_print:
            count = repo.insert_print_log(
                session,
                template_code="TRANSFER_NOTE",
                entity_id=transfer_id,
                actor_id=user.id,
                metadata={"status": detail.status, "template_version": template["version_no"]},
            )
        else:
            count = repo.print_count(session, "TRANSFER_NOTE", transfer_id)
        # The copy being printed now is a reprint when an earlier print exists.
        reprint = count > 1 if log_print else count >= 1
        return TransferNoteOut(
            transfer=detail,
            layout=dict(template["layout"] or {}),
            template_version=int(template["version_no"]),
            print_count=count,
            is_reprint=reprint,
            watermark=f"REPRINT #{count - 1 if log_print else count}" if reprint else None,
        )

    def handover_preview(
        self, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID
    ) -> HandoverPreviewOut:
        with self._uow.transaction(user.id) as session:
            gs = gs_service.get_visible_goods_slip(session, user, perms, gs_id)
            plan = _handover_plan(session, gs)
            block = _handover_block(session, gs, plan)
            staging = _location(session, STAGING)
            store = _location(session, INTERMEDIATE_STORE)
            ctx = self._label_ctx(session)
            live = [
                self._summary(
                    session,
                    user,
                    t
                    | {
                        "line_count": len(t["lines"]),
                        "total_qty": sum(ln["qty_sent"] for ln in t["lines"]),
                    },
                    ctx,
                )
                for t in transfers_for_gs(session, gs_id)
                if t["status"] in LIVE_STATUSES
            ]
            if plan.proposal_id:
                # The CSR proposal's lines are fixed (complete return, with packaging; BR-09).
                eligible = self._proposal_lines(session, plan.proposal_id)
            else:
                eligible = plan.eligible
            modes = _form_options(session, INITIATE_FORM, MODE_FIELD)
            return HandoverPreviewOut(
                gs_id=gs_id,
                gs_no=gs["gs_no"],
                gs_status=gs["status"],
                category_code=gs.get("category_code"),
                from_location_code=staging["code"],
                from_location_name=staging["name"],
                to_location_code=store["code"],
                to_location_name=store["name"],
                eligible=eligible,
                excluded=plan.excluded,
                blocked=block,
                proposal_transfer_id=plan.proposal_id,
                live_transfers=live,
                can_initiate=block is None
                and perms.allows("custody", "create")
                and is_custodian(session, user, staging),
                mode_options=modes,
                default_mode_code=DEFAULT_MODE
                if any(m.code == DEFAULT_MODE for m in modes)
                else None,
            )

    def intermediate_store_stock(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        *,
        gs_id: UUID | None,
        q: str | None,
        condition_class: str | None,
        routing_hint: str | None,
    ) -> StoreStockOut:
        with self._uow.transaction(user.id) as session:
            store = _location(session, INTERMEDIATE_STORE)
            custodian = is_custodian(session, user, store) and perms.allows("inventory", "edit")
            direct = repo.get_setting(session, "skip_technician_for_sellable") is not False
            rows = repo.location_stock(
                session,
                store["id"],
                gs_id=gs_id,
                product_q=_clean(q),
                condition_class=condition_class,
                routing_hint=routing_hint,
            )
            labels = repo.condition_labels(
                session,
                sorted({r["source_condition_code"] for r in rows if r["source_condition_code"]}),
            )
            out = []
            for r in rows:
                step = _next_step(r, direct)
                out.append(
                    StoreStockRow(
                        lot_id=r["lot_id"],
                        qty=int(r["qty"]),
                        gs_id=r["gs_id"],
                        gs_no=r["gs_no"],
                        gs_item_id=r["gs_item_id"],
                        line_no=r["line_no"],
                        product_code=r["product_code"],
                        product_name=r["product_name"],
                        condition_class=r["condition_class"],
                        condition_code=r["source_condition_code"],
                        condition_label=labels.get(r["source_condition_code"] or ""),
                        routing_hint=r["routing_hint"],
                        requires_evaluation=bool(r["requires_evaluation"]),
                        last_packaging_check=r["last_packaging_check"],
                        next_step=step,
                        can_classify=custodian and step == "DIRECT_CLASSIFICATION",
                    )
                )
            return StoreStockOut(
                location_code=store["code"],
                location_name=store["name"],
                rows=out,
                can_classify=custodian and direct,
                can_check_packaging=custodian,
            )

    # ------------------------------------------------------------------ commands --------------
    def initiate(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        payload: InitiateIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        with self._uow.transaction(user.id) as session:

            def command() -> tuple[int, Any]:
                if payload.gs_id:
                    gs_service.get_visible_goods_slip(session, user, perms, payload.gs_id)
                transfer_id = initiate_transfer(
                    session,
                    actor=user,
                    from_location_code=payload.from_location_code,
                    to_location_code=payload.to_location_code,
                    lines=payload.lines,
                    mode_code=payload.mode_code,
                    gs_id=payload.gs_id,
                    notes=payload.notes,
                )
                return 201, self._detail(session, user, perms, transfer_id)

            return run_idempotent(session, idem, user.id, command)

    def handover(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: HandoverIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        with self._uow.transaction(user.id) as session:

            def command() -> tuple[int, Any]:
                gs = gs_service.lock_goods_slip(session, gs_id)
                gs_service.get_visible_goods_slip(session, user, perms, gs_id)
                from app.modules.itemization import service as itemization_service

                itemization_service.assert_csr_decided_for(session, gs)  # G-03
                staging = _location(session, STAGING)
                if not is_custodian(session, user, staging):
                    raise PermissionDenied(
                        f"Only the custodian of {staging['name']} hands goods over",
                        code="NOT_LOCATION_CUSTODIAN",
                    )
                plan = _handover_plan(session, gs)
                self._assert_handover_lines(payload, plan)
                block = _handover_block(session, gs, plan)
                if block is not None:
                    if block.code == "G-08":
                        raise SystemGuardUnmet("G-08", block.message)
                    raise Conflict(block.message, code=block.code, details={"status": gs["status"]})
                if plan.proposal_id:
                    take_over_proposal(
                        session,
                        plan.proposal_id,
                        actor=user,
                        mode_code=payload.mode_code,
                        notes=payload.notes,
                    )
                    transfer_id = plan.proposal_id
                else:
                    lines = payload.lines or [
                        TransferLineIn(lot_id=e.lot_id, qty=e.qty) for e in plan.eligible
                    ]
                    transfer_id = initiate_transfer(
                        session,
                        actor=user,
                        from_location_code=STAGING,
                        to_location_code=INTERMEDIATE_STORE,
                        lines=lines,
                        mode_code=payload.mode_code,
                        gs_id=gs_id,
                        purpose_code=HANDOVER_PURPOSE,
                        notes=payload.notes,
                    )
                return 201, self._detail(session, user, perms, transfer_id)

            return run_idempotent(session, idem, user.id, command)

    def accept(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        transfer_id: UUID,
        payload: AcceptIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        return self._command(
            user,
            perms,
            transfer_id,
            idem,
            lambda s: accept_transfer(
                s, user=user, perms=perms, transfer_id=transfer_id, payload=payload
            ),
        )

    def reconcile(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        transfer_id: UUID,
        payload: ReconcileIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        return self._command(
            user,
            perms,
            transfer_id,
            idem,
            lambda s: reconcile_transfer(
                s, user=user, perms=perms, transfer_id=transfer_id, payload=payload
            ),
        )

    def approve(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        transfer_id: UUID,
        payload: ApproveAdjustmentIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        return self._command(
            user,
            perms,
            transfer_id,
            idem,
            lambda s: approve_adjustment(
                s, user=user, perms=perms, transfer_id=transfer_id, payload=payload
            ),
        )

    def cancel(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        transfer_id: UUID,
        payload: CancelIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        return self._command(
            user,
            perms,
            transfer_id,
            idem,
            lambda s: cancel_transfer(s, user=user, transfer_id=transfer_id, reason=payload.reason),
        )

    def classify(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        lot_id: UUID,
        payload: ClassifyIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        """DEC-14: Sahil classifies a SELLABLE-routed lot in the Intermediate Store directly as
        Functional Good (reclassification in place); every other lot awaits the technician."""
        with self._uow.transaction(user.id) as session:

            def command() -> tuple[int, Any]:
                store = _location(session, INTERMEDIATE_STORE)
                if not perms.allows("inventory", "edit") or not is_custodian(session, user, store):
                    raise PermissionDenied(
                        "Only the Intermediate Store in-charge classifies stock directly",
                        code="NOT_LOCATION_CUSTODIAN",
                    )
                lot = repo.lot_detail(session, lot_id, for_update=True)
                if not lot:
                    raise NotFound("Lot not found", code="LOT_NOT_FOUND")
                gs_service.get_visible_goods_slip(session, user, perms, lot["gs_id"])
                direct = repo.get_setting(session, "skip_technician_for_sellable") is not False
                if not direct or _next_step(lot, direct) != "DIRECT_CLASSIFICATION":
                    raise ValidationFailed(
                        "Only visually-OK lots routed SELLABLE can be classified without the "
                        "technician (DEC-14)",
                        code="NOT_DIRECTLY_CLASSIFIABLE",
                        details={
                            "routing_hint": lot["routing_hint"],
                            "condition_class": lot["condition_class"],
                        },
                    )
                balance = ledger_service.get_balance(session, lot_id, store["id"])
                if payload.qty > balance:
                    raise ValidationFailed(
                        f"The Intermediate Store holds {balance} of this lot",
                        code="CLASSIFY_QTY_INVALID",
                        details={"available": balance},
                    )
                target_id = repo.find_classified_lot(
                    session, source=lot, condition_class="FUNCTIONAL_GOOD"
                ) or ledger_service.create_stock_lot(
                    session,
                    stock_item_id=lot["stock_item_id"],
                    gs_id=lot["gs_id"],
                    gs_item_id=lot["gs_item_id"],
                    condition_class="FUNCTIONAL_GOOD",
                    source_condition_code=lot["source_condition_code"],
                    routing_hint=lot["routing_hint"],
                    created_by=user.id,
                )
                ledger_service.reclassify_lot(
                    session,
                    source_lot_id=lot_id,
                    target_lot_id=target_id,
                    location_id=store["id"],
                    qty=payload.qty,
                    reference_type="intermediate_classification",
                    reference_id=lot_id,
                    idempotency_key=f"classify:{idem.key}",
                    actor_id=user.id,
                    reason=_clean(payload.remarks)
                    or "Visually OK (DEC-14): classified Functional Good in the Intermediate Store",
                )
                return 201, ClassifyOut(
                    source_lot_id=lot_id,
                    target_lot_id=target_id,
                    qty=payload.qty,
                    condition_class="FUNCTIONAL_GOOD",
                )

            return run_idempotent(session, idem, user.id, command)

    # ------------------------------------------------------------------ internals -------------
    def _command(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        transfer_id: UUID,
        idem: IdempotencyKey,
        action: Any,
    ) -> IdempotentResult:
        with self._uow.transaction(user.id) as session:

            def command() -> tuple[int, Any]:
                self._assert_visible(session, user, perms, transfer_id)
                action(session)
                return 200, self._detail(session, user, perms, transfer_id)

            return run_idempotent(session, idem, user.id, command)

    @staticmethod
    def _assert_handover_lines(payload: HandoverIn, plan: HandoverPlan) -> None:
        if payload.lines is None:
            return
        if plan.proposal_id:
            raise ValidationFailed(
                "An approved Complete Sales Return is handed over in full, as proposed",
                code="CSR_TRANSFER_FIXED",
            )
        available = {e.lot_id: e.qty for e in plan.eligible}
        held = {x.lot_id: x for x in plan.excluded if x.lot_id}
        for line in payload.lines:
            if line.lot_id in available:
                if line.qty > available[line.lot_id]:
                    raise ValidationFailed(
                        f"Only {available[line.lot_id]} of this lot can be handed over",
                        code="TRANSFER_QTY_INVALID",
                        details={"lot_id": str(line.lot_id), "available": available[line.lot_id]},
                    )
                continue
            reason = held.get(line.lot_id)
            if reason is not None and reason.reason_code == "PENDING_BP":
                raise SystemGuardUnmet(
                    "G-08",
                    "Quantities marked Pending (BP) cannot be added to a custody transfer",
                    details={"lot_id": str(line.lot_id)},
                )
            raise ValidationFailed(
                "This lot is not eligible for handover",
                code="LOT_NOT_ELIGIBLE",
                details={
                    "lot_id": str(line.lot_id),
                    "reason_code": reason.reason_code if reason else None,
                },
            )

    def _assert_visible(
        self, session: Session, user: CurrentUser, perms: EffectivePermissions, transfer_id: UUID
    ) -> dict[str, Any]:
        transfer = repo.get_transfer(session, transfer_id)
        if not transfer:
            raise NotFound("Transfer not found", code="TRANSFER_NOT_FOUND")
        if transfer["gs_id"]:
            gs_service.get_visible_goods_slip(session, user, perms, transfer["gs_id"])
        return transfer

    def _proposal_lines(self, session: Session, transfer_id: UUID) -> list[HandoverLineOut]:
        lines = repo.lines_for_transfers(session, [transfer_id])
        labels = repo.condition_labels(
            session,
            sorted({ln["source_condition_code"] for ln in lines if ln["source_condition_code"]}),
        )
        return [
            HandoverLineOut(
                lot_id=ln["lot_id"],
                gs_item_id=ln["gs_item_id"],
                line_no=ln["line_no"],
                product_code=ln["product_code"],
                product_name=ln["product_name"],
                condition_code=ln["source_condition_code"],
                condition_label=labels.get(ln["source_condition_code"] or ""),
                routing_hint=ln["routing_hint"],
                qty=ln["qty_sent"],
            )
            for ln in lines
        ]

    def _label_ctx(self, session: Session) -> dict[str, Any]:
        return {
            "modes": repo.option_labels(session, "CUSTODY_TRANSFER_MODE"),
            "acceptance": repo.option_labels(session, "TRANSFER_ACCEPTANCE"),
            "blind": repo.get_setting(session, "transfer_blind_count") is True,
        }

    def _blind_for(
        self, session: Session, user: CurrentUser, t: dict[str, Any], ctx: dict[str, Any]
    ) -> bool:
        """[IMP] Blind count: the receiver does not see the quantities until the count is in."""
        if not ctx["blind"] or t["status"] != "INITIATED":
            return False
        return party_side(session, user, t) != "INITIATOR"

    def _summary(
        self, session: Session, user: CurrentUser, t: dict[str, Any], ctx: dict[str, Any]
    ) -> TransferSummaryOut:
        labels = t.get("labels_snapshot") or {}
        blind = self._blind_for(session, user, t, ctx)
        return TransferSummaryOut(
            id=t["id"],
            transfer_no=t["transfer_no"],
            gs_id=t["gs_id"],
            gs_no=t["gs_no"],
            status=t["status"],
            purpose_code=t["purpose_code"],
            with_packaging=t["with_packaging"],
            stock_moved=t["stock_moved"],
            mode_code=t["mode_code"],
            mode_label=(labels.get(MODE_FIELD) or {}).get("value_label")
            or ctx["modes"].get(t["mode_code"]),
            from_location_code=t["from_location_code"],
            from_location_name=t["from_location_name"],
            to_location_code=t["to_location_code"],
            to_location_name=t["to_location_name"],
            initiated_by=t["initiated_by"],
            initiated_by_name=t["initiated_by_name"],
            initiated_at=t["initiated_at"],
            accepted_by_name=t["accepted_by_name"],
            accepted_at=t["accepted_at"],
            acceptance_code=t["acceptance_code"],
            acceptance_label=(labels.get(ACCEPT_FIELD) or {}).get("value_label")
            or ctx["acceptance"].get(t["acceptance_code"] or ""),
            line_count=int(t.get("line_count") or 0),
            total_qty=None if blind else int(t.get("total_qty") or 0),
            created_at=t["created_at"],
        )

    def _detail(
        self, session: Session, user: CurrentUser, perms: EffectivePermissions, transfer_id: UUID
    ) -> TransferDetailOut:
        t = self._assert_visible(session, user, perms, transfer_id)
        lines = repo.lines_for_transfers(session, [transfer_id])
        ctx = self._label_ctx(session)
        blind = self._blind_for(session, user, t, ctx)
        summary = self._summary(
            session,
            user,
            t | {"line_count": len(lines), "total_qty": sum(ln["qty_sent"] for ln in lines)},
            ctx,
        )
        labels = repo.condition_labels(
            session,
            sorted({ln["source_condition_code"] for ln in lines if ln["source_condition_code"]}),
        )
        recons = repo.reconciliations_for(session, transfer_id)
        open_recon = next(
            (r for r in recons if r["status"] in ("PROPOSED", "AWAITING_RM_APPROVAL")), None
        )
        status = t["status"]
        target = {
            "custodian_user_id": t["to_custodian_user_id"],
            "custodian_role_id": t["to_custodian_role_id"],
        }
        sod = repo.get_setting(session, "segregation_of_duties_transfer") is not False
        override = may_override(session, user, perms)
        permissions = TransferPermissions(
            can_accept=status == "INITIATED"
            and t["stock_moved"]
            and perms.allows("custody", "approve")
            and is_custodian(session, user, target)
            and not (sod and t["initiated_by"] == user.id),
            can_cancel=status == "INITIATED" and t["initiated_by"] == user.id,
            can_print=perms.allows("custody", "view"),
            reconcile_side=party_side(session, user, t) if status == "DISCREPANCY" else None,
            can_override=status == "DISCREPANCY" and override,
            can_approve_adjustment=bool(
                open_recon and open_recon["status"] == "AWAITING_RM_APPROVAL" and override
            ),
        )
        counted = status != "INITIATED"
        return TransferDetailOut(
            **summary.model_dump(),
            notes=t["notes"],
            discrepancy_notes=t["discrepancy_notes"],
            cancel_reason=t["cancel_reason"],
            cancelled_at=t["cancelled_at"],
            resolution_code=t["resolution_code"],
            reconciled_at=t["reconciled_at"],
            supersedes_transfer_id=t["supersedes_transfer_id"],
            blind_count=blind,
            lines=[
                TransferLineOut(
                    lot_id=ln["lot_id"],
                    gs_item_id=ln["gs_item_id"],
                    line_no=ln["line_no"],
                    product_code=ln["product_code"],
                    product_name=ln["product_name"],
                    condition_class=ln["condition_class"],
                    condition_code=ln["source_condition_code"],
                    condition_label=labels.get(ln["source_condition_code"] or ""),
                    routing_hint=ln["routing_hint"],
                    qty_sent=None if blind else ln["qty_sent"],
                    qty_counted=ln["qty_counted"] if counted else None,
                    qty_accepted=ln["qty_accepted"],
                    qty_returned=ln["qty_returned"],
                    qty_adjusted=ln["qty_adjusted"],
                )
                for ln in lines
            ],
            reconciliations=[_recon_out(r) for r in recons],
            permissions=permissions,
        )


def _recon_out(r: dict[str, Any]) -> ReconciliationOut:
    return ReconciliationOut(
        id=r["id"],
        resolution_code=r["resolution_code"],
        resolution_label=RESOLUTIONS.get(r["resolution_code"], (r["resolution_code"], ""))[0],
        difference_disposition=r["difference_disposition"],
        resend_lines=list(r["resend_lines"] or []),
        notes=r["notes"],
        status=r["status"],
        requires_rm_approval=r["requires_rm_approval"],
        proposed_by_name=r["proposed_by_name"],
        proposed_at=r["proposed_at"],
        initiator_signed_by_name=r["initiator_signed_by_name"],
        initiator_signed_at=r["initiator_signed_at"],
        receiver_signed_by_name=r["receiver_signed_by_name"],
        receiver_signed_at=r["receiver_signed_at"],
        is_rm_override=r["is_rm_override"],
        rm_approved_by_name=r["rm_approved_by_name"],
        rm_approved_at=r["rm_approved_at"],
        rm_reason=r["rm_reason"],
        applied_at=r["applied_at"],
        resend_transfer_id=r["resend_transfer_id"],
    )


def _next_step(lot: dict[str, Any], direct_enabled: bool) -> str:
    """DEC-14 routing in the Intermediate Store."""
    if lot["condition_class"] in ("FUNCTIONAL_GOOD", "FUNCTIONAL_REPAIRED"):
        return "CLASSIFIED"
    if (
        direct_enabled
        and lot["condition_class"] == "AS_RECEIVED"
        and lot["routing_hint"] == SELLABLE
        and not lot.get("requires_evaluation")
    ):
        return "DIRECT_CLASSIFICATION"
    return "AWAITING_TECHNICIAN"
