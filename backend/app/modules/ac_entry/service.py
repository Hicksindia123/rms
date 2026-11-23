"""Accounts entry per action line and the Dispatch Slip (change plan 2026-11-12 Phase 8;
AMD-18, AMD-19; DEC-22, DEC-26, DEC-41, DEC-47; G-15, G-16, G-18, G-22).

* Queue: goods slips with a CURRENT "Replacement Slip - A/c Actions" (Phase 7, AMD-17).
* Entry: the DB created one entry line per action line when the slip was finalised, with the
  action's `requires_cn` / `requires_challan` flags snapshotted (G-18). Accounts fills CN No. /
  Date / Value and Challan No. / Date only where a flag asks for it (AMD-18: no hard-coded action
  codes). CN No. is an external voucher (DEC-22): one goods slip only, never on a credit note.
* Complete: every line that needs data has it (G-22). The entries, the A/c Actions slip and the RM
  actions are frozen. If any line ships goods (`requires_challan`, DEC-47) a numbered Dispatch Slip
  PDF is generated (template DISPATCH_SLIP, DEC-41) and DISPATCH is notified (rule-driven);
  otherwise the goods slip settles its returned pieces and moves on to the closure engine.
* Dispatch: DISPATCH records date + transporter + docket / vehicle (DEC-26); the returned pieces
  are issued from the intermediate store through `rms_move_stock` (G-16) to the location the
  `dispatch.returned_goods_location_by_action` setting names per action code (DEC-47), the slip
  becomes DISPATCHED and the goods slip continues to the existing closure engine (G-15).
* Rounds (gap plan G4, DEC-57): pieces marked Pending go to the Pending Hold when their round
  settles; the RM re-actions them later in a follow-up round with its own A/c Actions slip, Accounts
  entry and (if goods ship) Dispatch Slip. Round 1 works while the goods slip is held at the
  intermediate store; later rounds while it is open after that stage, moving stock out of the
  Pending Hold. The screen shows the latest round's CURRENT slip.

Intermediate Store flow (Phase P11, DEC-71): when every store submitted its analysis and the
Management gate passes (DEC-70), `route_to_accounts` moves the goods slip to ACCOUNTS_PENDING with
one Replacement Slip (the A/c Actions slip, ac_action_slips round 1) - or to NOT_ALLOWED_HOLD when
no decision needs a Challan or a Credit Note (Q21). Accounts enters ONE Challan (goods ship) and ONE
Credit Note (Issue CN) per goods slip (ac_gs_entries). Completion generates the Dispatch Slip
(DISPATCH_PENDING) or settles the pieces and hands the goods slip to closure; the returned pieces
leave each item's Intermediate Store location. `reopen_for_management` withdraws the Replacement
Slip when Management changes a goods slip at Accounts (or on hold); its next approval routes it
again (Replacement Slip v+1).

Each command runs in one transaction and is idempotent on `Idempotency-Key` (G-16). The DB enforces
G-22 again with triggers, so no path can bypass it.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from sqlalchemy.orm import Session

from app.core.db import UnitOfWork
from app.core.errors import (
    Conflict,
    NotFound,
    ServiceUnavailable,
    SystemGuardViolation,
    ValidationFailed,
)
from app.core.idempotency import IdempotencyKey, IdempotentResult, run_idempotent
from app.core.permissions import EffectivePermissions
from app.core.security import CurrentUser
from app.modules.ac_entry import repository as repo
from app.modules.ac_entry.schemas import (
    AcEntryLine,
    AcEntryQueueItem,
    AcEntryState,
    AcGsEntry,
    AcHoldItem,
    CompleteAcEntryIn,
    DispatchIn,
    DispatchSlipLine,
    DispatchSlipOut,
    DispatchSlipPrintOut,
    DispatchSlipSummary,
    ReplacementSlipPrintOut,
    SaveAcEntryIn,
    SaveGsEntryIn,
)
from app.modules.attachments.service import signed_url_ttl
from app.modules.closure import service as closure_service
from app.modules.goods_slips import service as gs_service
from app.modules.inventory import ledger_service
from app.modules.management_approval import service as management_approval
from app.modules.notifications import service as notifications
from app.modules.party_notifications import email_service as party_email
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
from app.shared.storage import Bucket, StorageService, build_object_path

log = structlog.get_logger("rms.ac_entry")

HELD_STATUS = "HELD_AT_INTERMEDIATE_STORE"
CLOSURE_ENTRY_STATUS = "IN_PROCESS"
ACCOUNTS_STEP = "S6_ACCOUNTS_CN"
STORE_LOCATION = "INTERMEDIATE_STORE"
# DEC-57: re-action rounds take their pieces from the Pending Hold (where round N-1 put them).
PENDING_HOLD_LOCATION = "PENDING_HOLD"
# DEC-57: statuses in which a re-action round (round >= 2) is entered / completed / dispatched; the
# DB guards (G-22) check the same list.
OPEN_AFTER_HOLD = frozenset({"IN_PROCESS", "COMMERCIAL_RESOLUTION", "AWAITING_NOTIFICATION"})
RETURNED_GOODS_SETTING = "dispatch.returned_goods_location_by_action"
# DEC-71 (P11): Intermediate Store flow statuses.
ANALYSIS_DONE_STATUS = "ANALYSIS_COMPLETED"
ACCOUNTS_STATUS = "ACCOUNTS_PENDING"
HOLD_STATUS = "NOT_ALLOWED_HOLD"
DISPATCH_STATUS = "DISPATCH_PENDING"
TO_CLOSURE_FROM = frozenset({HELD_STATUS, ACCOUNTS_STATUS, DISPATCH_STATUS})
PDF_MIME = "application/pdf"

# rms_move_stock movement type per destination location class (stock_movements CHECK).
_MOVEMENT_TYPE = {
    "DISPATCHED": "DISPATCH",
    "CREDITED": "CREDIT",
    "SCRAP_DISPOSED": "DISPOSE",
}


# --- small helpers ------------------------------------------------------------------------------


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


def _fmt_date(value: date | datetime | None, fmt: str, tz: ZoneInfo) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(tz).strftime(fmt)
    return value.strftime(fmt)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _line_out(row: dict[str, Any]) -> AcEntryLine:
    return AcEntryLine(
        id=row["id"],
        gs_item_id=row["gs_item_id"],
        line_no=row["line_no"],
        product_code=row["product_code"],
        product_name=row["product_name"],
        action_code=row["action_code"],
        action_label=row["action_label"],
        condition_label=row.get("condition_label"),
        qty=row["qty"],
        requires_cn=row["requires_cn"],
        requires_challan=row["requires_challan"],
        cn_no=row["cn_no"],
        cn_date=row["cn_date"],
        cn_value=row["cn_value"],
        challan_no=row["challan_no"],
        challan_date=row["challan_date"],
        is_complete=bool(row["is_complete"]),
        entered_by_name=row["entered_by_name"],
        entered_at=row["entered_at"],
    )


def _dslip_summary(row: dict[str, Any]) -> DispatchSlipSummary:
    return DispatchSlipSummary(
        id=row["id"],
        slip_no=row["slip_no"],
        status=row["status"],
        generated_at=row["generated_at"],
        dispatch_date=row["dispatch_date"],
        transporter=row["transporter"],
        docket_no=row["docket_no"],
        vehicle_no=row["vehicle_no"],
        dispatched_at=row["dispatched_at"],
        total_qty=int(row["total_qty"] or 0),
        print_count=int(row["print_count"] or 0),
    )


def _dslip_out(session: Session, row: dict[str, Any]) -> DispatchSlipOut:
    return DispatchSlipOut(
        **_dslip_summary(row).model_dump(),
        gs_id=row["gs_id"],
        gs_no=row["gs_no"],
        gs_status=row["gs_status"],
        party_name=row["party_name"],
        ac_slip_no=row["ac_slip_no"],
        ac_version_no=row["ac_version_no"],
        ac_round_no=int(row.get("ac_round_no") or 1),
        dispatch_remarks=row["dispatch_remarks"],
        generated_by_name=row["generated_by_name"],
        dispatched_by_name=row["dispatched_by_name"],
        lines=[DispatchSlipLine(**ln) for ln in repo.dispatch_slip_lines(session, row["id"])],
    )


# --- shared commercial-completion steps (service-level; used by both services below) -----------


def _stage_ok(
    gs_status: str, round_no: int, *, per_gs: bool = False, dispatch: bool = False
) -> bool:
    """DEC-57: round 1 is handled while the goods slip is held at the intermediate store; a
    re-action round while it is open after that stage. DEC-71: a store-flow goods slip is entered
    while ACCOUNTS_PENDING and dispatched while DISPATCH_PENDING."""
    if per_gs:
        return gs_status == (DISPATCH_STATUS if dispatch else ACCOUNTS_STATUS)
    if round_no == 1:
        return gs_status == HELD_STATUS
    return gs_status in OPEN_AFTER_HOLD


def _stage_text(round_no: int, *, per_gs: bool = False, dispatch: bool = False) -> str:
    if per_gs:
        return "pending dispatch" if dispatch else "at Accounts"
    return (
        "held at the intermediate store"
        if round_no == 1
        else "open after the store stage (Pending re-action)"
    )


def _source_location(round_no: int) -> str:
    """Where a round's pieces wait: the intermediate store (round 1) or the Pending Hold."""
    return STORE_LOCATION if round_no == 1 else PENDING_HOLD_LOCATION


def _returned_goods_map(session: Session) -> dict[str, str]:
    """DEC-47 setting: action code -> inventory location code for the returned pieces."""
    value = repo.get_setting(session, RETURNED_GOODS_SETTING)
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        log.error("returned_goods_setting_invalid", key=RETURNED_GOODS_SETTING, value=value)
        raise Conflict(
            f"System setting '{RETURNED_GOODS_SETTING}' must map action codes to location codes",
            code="SETTING_INVALID",
            details={"key": RETURNED_GOODS_SETTING},
        )
    return value


def _settle_returned_goods(
    session: Session,
    *,
    ac_slip_id: UUID,
    source_code: str,
    lines: list[dict[str, Any]],
    reference_type: str,
    reference_id: UUID,
    reason: str,
    actor_id: UUID,
    source_by_item: dict[UUID, str] | None = None,
) -> list[dict[str, Any]]:
    """Move the returned pieces of each action line out of `source_code` (the intermediate store,
    or the Pending Hold for a re-action round) to the location the setting names (DEC-47, DEC-57:
    Pending -> Pending Hold, Not Allowed -> Rejected Hold, Send New -> Non-Functional Store).

    Lines whose pieces themselves leave (destination class DISPATCHED, e.g. Send Repaired) go first
    and must find their full qty at the source (rms_move_stock raises G-16 otherwise). Other lines
    move what is still there: pieces already in a terminal location (e.g. wastage in SCRAP_DISPOSED,
    Mercury Extracted in the Non-Functional Store) stay. A destination equal to the source is a
    no-op (Pending again in a re-action round). Idempotent per entry line (G-16).
    """
    mapping = _returned_goods_map(session)
    if not mapping:
        return []
    sources: dict[str, dict[str, Any]] = {}

    def source_of(ln: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        # DEC-71: on the store flow the pieces wait in their item's Intermediate Store location.
        code = (source_by_item or {}).get(ln["gs_item_id"], source_code)
        if code not in sources:
            loc = ledger_service.get_location_by_code(session, code)
            if not loc:
                raise Conflict(
                    f"Inventory location {code} is not configured", code="LOCATION_NOT_FOUND"
                )
            sources[code] = loc
        return code, sources[code]

    targets: dict[str, dict[str, Any]] = {}
    for ln in lines:
        loc_code = mapping.get(ln["action_code"])
        if loc_code and loc_code not in targets:
            loc = ledger_service.get_location_by_code(session, loc_code)
            if not loc:
                log.error("returned_goods_location_missing", location_code=loc_code)
                raise Conflict(
                    f"Setting '{RETURNED_GOODS_SETTING}' names unknown location {loc_code}",
                    code="SETTING_INVALID",
                    details={"key": RETURNED_GOODS_SETTING, "location_code": loc_code},
                )
            targets[loc_code] = loc

    def ships(ln: dict[str, Any]) -> bool:
        loc_code = mapping.get(ln["action_code"])
        return bool(loc_code) and targets[str(loc_code)]["location_class"] == "DISPATCHED"

    moves: list[dict[str, Any]] = []
    ordered = sorted(lines, key=lambda ln: (not ships(ln), ln["line_no"]))
    for ln in ordered:
        loc_code = mapping.get(ln["action_code"])
        from_code, store = source_of(ln)
        if not loc_code or loc_code == from_code:
            continue  # pieces stay where they are; the closure checklist shows them.
        target = targets[loc_code]
        lot_id = repo.find_lot_for_item(session, ln["gs_item_id"])
        strict = ships(ln)
        if lot_id is None:
            if strict:
                raise ValidationFailed(
                    f"Line {ln['line_no']}: no stock lot found for the returned goods",
                    code="LOT_NOT_FOUND",
                    details={"gs_item_id": str(ln["gs_item_id"])},
                )
            continue
        in_store = ledger_service.get_balance(session, lot_id, store["id"])
        qty = int(ln["qty"]) if strict else min(int(ln["qty"]), in_store)
        if qty <= 0:
            continue
        ledger_service.move_stock(
            session,
            lot_id=lot_id,
            from_location_id=store["id"],
            to_location_id=target["id"],
            qty=qty,
            movement_type=_MOVEMENT_TYPE.get(str(target["location_class"]), "ISSUE"),
            reference_type=reference_type,
            reference_id=reference_id,
            idempotency_key=f"acflow:{ac_slip_id}:{ln['id']}",
            actor_id=actor_id,
            reason=reason,
        )
        moves.append({"line_no": ln["line_no"], "to": loc_code, "qty": qty})
    return moves


def _to_closure(session: Session, gs: dict[str, Any], *, reason: str, by: UUID) -> str | None:
    """AMD-19 / G-15: the goods slip leaves the intermediate store stage for the closure engine,
    which decides the next status from its single checklist (DB guards still apply). DEC-57: after
    a re-action round the goods slip is already past the store stage; the engine re-evaluates."""
    if gs["status"] not in TO_CLOSURE_FROM:
        return closure_service.sync_status(session, gs["id"], by) or str(gs["status"])
    gs_service.change_status(
        session,
        gs_id=gs["id"],
        from_status=str(gs["status"]),
        to_status=CLOSURE_ENTRY_STATUS,
        step_code=ACCOUNTS_STEP,
        reason=reason,
        by=by,
    )
    return closure_service.sync_status(session, gs["id"], by) or CLOSURE_ENTRY_STATUS


# =================================================================================================
# DEC-71 (Phase P11): the Accounts gate and the Replacement Slip of a store-flow goods slip
# =================================================================================================


def _template_name(session: Session) -> str | None:
    template = repo.published_template(session, repo.AC_SLIP_TEMPLATE)
    return str(template["name"]) if template else None


def route_to_accounts(
    session: Session,
    gs_id: UUID,
    actor: CurrentUser,
    storage: StorageService,
    on_uploaded: Callable[[str], None],
) -> str | None:
    """DEC-71: a store-flow goods slip in ANALYSIS_COMPLETED reaches Accounts once every store
    submitted its analysis and the Management gate passes (DEC-70 / Q18). Called in the same
    transaction by the last store submission (P9) and by a Management approval (P10).

    Returns the new status (ACCOUNTS_PENDING with its Replacement Slip, or NOT_ALLOWED_HOLD when no
    decision needs a Challan or a Credit Note, Q21), or None while the gate does not pass yet. The
    DB checks the same on the status change (G-03) and on the slip insert."""
    gs = repo.get_gs_header(session, gs_id, lock=True)
    if not gs or gs["status"] != ANALYSIS_DONE_STATUS or not repo.gs_on_store_flow(session, gs_id):
        return None
    if not repo.gs_store_analysis_complete(session, gs_id):
        return None
    problem = management_approval.accounts_gate_problem(session, gs_id)
    if problem is not None:
        log.info("accounts_gate_waiting", gs_id=str(gs_id), problem=problem)
        return None
    management_approval.assert_accounts_gate(session, gs_id)  # DEC-70 / Q18 (service guard)

    if not repo.gs_needs_accounts(session, gs_id):
        gs_service.change_status(
            session,
            gs_id=gs_id,
            from_status=ANALYSIS_DONE_STATUS,
            to_status=HOLD_STATUS,
            step_code=ACCOUNTS_STEP,
            reason="Every decision is Not Allowed: no Challan, no Credit Note (DEC-71, Q21)",
            by=actor.id,
        )
        notifications.publish(
            session,
            "GS_NOT_ALLOWED_HOLD",
            title=f"{gs['gs_no']}: on hold - every decision Not Allowed",
            body=(
                f"{gs['party_name'] or 'Goods slip'}: nothing to ship and no credit note, so the "
                "goods slip stays open on hold (no Accounts entry). Management may change it."
            ),
            entity_type="goods_slips",
            entity_id=gs_id,
            gs_id=gs_id,
            data={"gs_no": gs["gs_no"]},
            dedupe_key=f"gs-not-allowed-hold:{gs_id}:{repo.max_revision(session, gs_id)}",
        )
        log.info("accounts_gate_hold", gs_id=str(gs_id))
        return HOLD_STATUS

    gs_service.change_status(
        session,
        gs_id=gs_id,
        from_status=ANALYSIS_DONE_STATUS,
        to_status=ACCOUNTS_STATUS,
        step_code=ACCOUNTS_STEP,
        reason="Every store analysed the goods slip; Management gate passed (DEC-71)",
        by=actor.id,
    )
    slip_id, slip_no, version_no = _create_replacement_slip(
        session, gs, actor, storage, on_uploaded
    )
    # Item 5: Accounts in-app alert (rule AC_ACTIONS_SLIP_READY → ACCOUNTS; email deferred, Q22).
    title = _template_name(session) or "Replacement Slip"
    notifications.publish(
        session,
        "AC_ACTIONS_SLIP_READY",
        title=f"{gs['gs_no']}: {title} {slip_no} v{version_no} at Accounts",
        body=(
            f"{gs['party_name'] or 'Goods slip'}: every Intermediate Store analysed it. Enter the "
            "Challan and / or the Credit Note of the goods slip."
        ),
        entity_type=repo.AC_SLIP_ENTITY,
        entity_id=slip_id,
        gs_id=gs_id,
        data={"gs_no": gs["gs_no"], "slip_no": slip_no, "version_no": version_no},
        dedupe_key=f"ac-slip-ready:{slip_id}",
    )
    log.info("accounts_gate_passed", gs_id=str(gs_id), slip_no=slip_no, version_no=version_no)
    return ACCOUNTS_STATUS


def reopen_for_management(session: Session, gs_id: UUID, actor: CurrentUser, reason: str) -> bool:
    """DEC-71: Management changes a goods slip at Accounts (entry not completed) or on hold. The
    current Replacement Slip is withdrawn (SUPERSEDED, Accounts told) and the goods slip returns to
    ANALYSIS_COMPLETED; the next approval routes it again (Replacement Slip v+1). Returns True when
    it reopened the goods slip. The DB refuses the same without a withdrawn slip (G-03) and never
    supersedes a completed one (G-22)."""
    gs = repo.get_gs_header(session, gs_id, lock=True)
    if not gs or gs["status"] not in (ACCOUNTS_STATUS, HOLD_STATUS):
        return False
    if gs["status"] == ACCOUNTS_STATUS:
        slip = repo.current_ac_slip(session, gs_id)
        if slip is not None:
            if repo.get_completion(session, slip["id"]) is not None:
                raise SystemGuardViolation(
                    "G-22",
                    f"G-22: Accounts completed {slip['slip_no']} v{slip['version_no']}; the goods "
                    "slip can no longer be changed",
                )
            repo.supersede_ac_slip(
                session, slip["id"], by=actor.id, reason=f"Management change: {reason}"
            )
            notifications.publish(
                session,
                "AC_ACTIONS_SLIP_SUPERSEDED",
                title=f"{gs['gs_no']}: {slip['slip_no']} v{slip['version_no']} withdrawn",
                body=(
                    f"{actor.full_name} (Management) is changing the goods slip: {reason}. "
                    "Accounts gets a new version after Management approves it."
                ),
                entity_type=repo.AC_SLIP_ENTITY,
                entity_id=slip["id"],
                gs_id=gs_id,
                data={"gs_no": gs["gs_no"], "slip_no": slip["slip_no"]},
                dedupe_key=f"ac-slip-superseded:{slip['id']}",
            )
    gs_service.change_status(
        session,
        gs_id=gs_id,
        from_status=str(gs["status"]),
        to_status=ANALYSIS_DONE_STATUS,
        step_code=ACCOUNTS_STEP,
        reason=f"Reopened for a Management change (DEC-71): {reason}",
        by=actor.id,
    )
    log.info("accounts_reopened_for_management", gs_id=str(gs_id), from_status=gs["status"])
    return True


def _create_replacement_slip(
    session: Session,
    gs: dict[str, Any],
    actor: CurrentUser,
    storage: StorageService,
    on_uploaded: Callable[[str], None],
) -> tuple[UUID, str, int]:
    """DEC-71 (Q19, Q20): the GS-wise Replacement Slip PDF (template AC_ACTIONS_SLIP, HICKS logo,
    GS details, lines with store + condition + action + qty, totals per action, Management stamp)
    stored as a new ac_action_slips version (the DB creates its lines and the per-GS entry)."""
    template = repo.published_template(session, repo.AC_SLIP_TEMPLATE)
    if not template:
        raise Conflict("No published AC_ACTIONS_SLIP print template", code="TEMPLATE_NOT_PUBLISHED")
    head = repo.get_gs_print_header(session, gs["id"])
    if head is None:
        raise NotFound(f"Goods slip {gs['id']} not found", code="GS_NOT_FOUND")
    tz = _tz(session)
    fmt = _date_fmt(session)
    prev = repo.latest_slip_identity(session, gs["id"])
    slip_no = str(prev["slip_no"]) if prev else repo.next_number(session, repo.AC_SLIP_SERIES)
    version_no = int(prev["version_no"]) + 1 if prev else 1
    revision_no = repo.max_revision(session, gs["id"])

    rows = repo.store_flow_slip_lines(session, gs["id"])
    lines = [
        {
            "line_no": r["line_no"],
            "product_code": r["product_code"] or "",
            "product_name": r["product_name"],
            "received_qty": r["received_qty"],
            "store_name": r["store_name"] or "",
            "condition_code": r["condition_code"],
            "condition_label": r["condition_label"],
            "action_code": r["action_code"],
            "action_label": r["action_label"],
            "qty": r["qty"],
            "requires_cn": bool(r["requires_cn"]),
            "requires_challan": bool(r["requires_challan"]),
        }
        for r in rows
    ]
    by_code: dict[str, dict[str, Any]] = {}
    for r in rows:
        t = by_code.setdefault(
            r["action_code"],
            {
                "action_code": r["action_code"],
                "action_label": r["action_label"],
                "qty": 0,
                "_sort": r["action_sort"],
            },
        )
        t["qty"] += int(r["qty"])
    by_action = [
        {k: v for k, v in t.items() if k != "_sort"}
        for t in sorted(by_code.values(), key=lambda t: (t["_sort"], t["action_code"]))
    ]
    received = {r["gs_item_id"]: int(r["received_qty"]) for r in rows}
    totals = {
        "total_qty": sum(int(t["qty"]) for t in by_action),
        "counted_qty": sum(received.values()),
        "by_action": by_action,
    }
    docs = [
        " ".join(
            x
            for x in (d["doc_type_label"], d["doc_no"] or "", _fmt_date(d["doc_date"], fmt, tz))
            if x
        )
        for d in repo.list_gate_documents(session, gs["id"])
    ]
    content: dict[str, Any] = {
        "slip_no": slip_no,
        "version_no": version_no,
        "revision_no": revision_no,
        "round_no": 1,
        "per_gs": True,
        "gs_no": head["gs_no"],
        "gs_date": _fmt_date(head["created_at"], fmt, tz),
        "return_type": head["return_type_label"] or head["return_type_code"] or "",
        "carton_count": head["carton_count"],
        "party_name": head["party_name"] or "",
        "party_code": head["party_code"] or "",
        "state_station": " / ".join(x for x in (head["state_name"], head["station_name"]) if x),
        "gate_entry_no": head["gate_entry_no"] or "",
        "gate_entry_date": _fmt_date(head["gate_entry_date"], fmt, tz),
        "gate_documents": docs
        or (["No document (missing documentation)"] if head["missing_documentation"] else []),
        "lines": lines,
        "totals": totals,
        "prepared_by": actor.full_name,
        "finalised_at": datetime.now(tz).strftime(f"{fmt} %H:%M"),
        # DEC-70: the Management e-approval stamp (VALID approval only) is printed and recorded.
        "management_stamp": management_approval.stamp_for_print(session, gs["id"]),
    }
    pdf = render_slip_pdf(_replacement_slip_document(session, template, content))
    digest = hashlib.sha256(pdf).hexdigest()
    slip_id = uuid.uuid4()
    path = build_object_path(gs["id"], "generated_pdf", "pdf")
    storage.upload(Bucket.DOCUMENTS, path, pdf, PDF_MIME)
    on_uploaded(path)
    attachment_id = repo.insert_slip_pdf(
        session,
        gs_id=gs["id"],
        entity_id=slip_id,
        bucket=Bucket.DOCUMENTS.value,
        object_path=path,
        size_bytes=len(pdf),
        by=actor.id,
    )
    repo.insert_ac_slip(
        session,
        slip_id=slip_id,
        gs_id=gs["id"],
        slip_no=slip_no,
        version_no=version_no,
        revision_no=revision_no,
        attachment_id=attachment_id,
        template_version_no=int(template["version_no"]),
        content=content,
        totals=totals,
        sha256=digest,
        by=actor.id,
    )
    log.info(
        "replacement_slip_generated",
        gs_id=str(gs["id"]),
        slip_no=slip_no,
        version_no=version_no,
        size=len(pdf),
    )
    return slip_id, slip_no, version_no


def _replacement_slip_document(
    session: Session, template: dict[str, Any], c: dict[str, Any]
) -> SlipDocument:
    """Map the published template layout (DEC-41: branding is configuration) + content."""
    layout: dict[str, Any] = template["layout"] or {}
    titles = {
        s.get("id"): s.get("title") for s in layout.get("sections", []) if isinstance(s, dict)
    }

    def title(section_id: str, fallback: str) -> str:
        return str(titles.get(section_id) or fallback)

    signatures = [
        SlipSignature(
            label=str(block.get("label", "")),
            role=str(block.get("role", "")),
            name=c["prepared_by"] if i == 0 else None,
        )
        for i, block in enumerate(layout.get("signature_blocks", []))
        if isinstance(block, dict)
    ]
    totals = c["totals"]
    return SlipDocument(
        title=str(layout.get("header_title") or template.get("name") or ""),
        subtitle=str(layout.get("header_subtitle") or template.get("name") or ""),
        document_ref=f"{c['slip_no']} · Version {c['version_no']} · {c['gs_no']}",
        stamp=c.get("management_stamp"),
        sections=[
            SlipSection(
                title("gs_header", "Goods Slip"),
                [
                    SlipField("GS No.", c["gs_no"]),
                    SlipField("GS Date", c["gs_date"]),
                    SlipField("Return Type", c["return_type"]),
                    SlipField("Cartons", str(c["carton_count"] or "")),
                    SlipField("Slip No.", f"{c['slip_no']} (v{c['version_no']})"),
                    SlipField("Decision Revision", str(c["revision_no"])),
                ],
            ),
            SlipSection(
                title("party", "Party"),
                [
                    SlipField("Party", c["party_name"]),
                    SlipField("Party Code", c["party_code"]),
                    SlipField("State / Station", c["state_station"]),
                ],
            ),
            SlipSection(
                title("gate_entry", "Gate Entry"),
                [
                    SlipField("Gate Entry No.", str(c["gate_entry_no"])),
                    SlipField("Gate Entry Date", c["gate_entry_date"]),
                    SlipField("Documents", "\n".join(c["gate_documents"])),
                ],
            ),
        ],
        tables=[
            SlipTable(
                title=title("items", "Item \u00d7 Condition \u00d7 Action"),
                columns=[
                    SlipColumn("#", 0.4, "right"),
                    SlipColumn("Code", 0.9),
                    SlipColumn("Product", 2.0),
                    SlipColumn("Store", 1.0),
                    SlipColumn("Condition", 1.2),
                    SlipColumn("Action", 1.4),
                    SlipColumn("Qty", 0.5, "right"),
                ],
                rows=[
                    [
                        str(ln["line_no"]),
                        ln["product_code"],
                        ln["product_name"],
                        ln["store_name"],
                        ln.get("condition_label") or "",
                        ln["action_label"],
                        str(ln["qty"]),
                    ]
                    for ln in c["lines"]
                ],
                total_row=["", "", "Total", "", "", "", str(totals["total_qty"])],
            ),
            SlipTable(
                title=title("totals", "Totals by Action"),
                columns=[SlipColumn("Action", 3), SlipColumn("Qty", 1, "right")],
                rows=[[t["action_label"], str(t["qty"])] for t in totals["by_action"]],
                total_row=["Total", str(totals["total_qty"])],
            ),
        ],
        signatures=signatures,
        signatures_title=title("signatures", "Signatures"),
        footer_text=str(layout.get("footer_text") or ""),
        generated_text=f"Generated {c['finalised_at']} by {c['prepared_by']}",
        brand_color=str(repo.get_setting(session, "branding_primary_color") or ""),
        paper_size=str(layout.get("paper_size") or "A4"),
        orientation=str(layout.get("orientation") or "portrait"),
        logo=template_logo(session, layout),  # DEC-65 / Q26
    )


# =================================================================================================
# Accounts entry
# =================================================================================================


class AcEntryService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    # === queries ===

    def queue(self, user: CurrentUser, *, completed: bool | None) -> list[AcEntryQueueItem]:
        with self._uow.transaction(user.id) as session:
            return [AcEntryQueueItem(**r) for r in repo.list_queue(session, completed=completed)]

    def get_state(
        self, gs_id: UUID, user: CurrentUser, perms: EffectivePermissions
    ) -> AcEntryState:
        with self._uow.transaction(user.id) as session:
            return self._state(session, gs_id, perms)

    def _state(self, session: Session, gs_id: UUID, perms: EffectivePermissions) -> AcEntryState:
        gs = repo.get_gs_header(session, gs_id)
        if not gs:
            raise NotFound(f"Goods slip {gs_id} not found", code="GS_NOT_FOUND")
        slip = repo.current_ac_slip(session, gs_id)
        rows = repo.entry_lines(session, slip["id"]) if slip else []
        lines = [_line_out(r) for r in rows]
        completion = repo.get_completion(session, slip["id"]) if slip else None
        dslip = repo.get_dispatch_slip_for_ac_slip(session, slip["id"]) if slip else None
        needing = [ln for ln in lines if ln.requires_cn or ln.requires_challan]
        round_no = int(slip["round_no"]) if slip else 1
        # DEC-71: a store-flow goods slip has one Accounts entry for the whole goods slip.
        entry = repo.get_gs_entry(session, slip["id"]) if slip else None
        per_gs = entry is not None or repo.gs_on_store_flow(session, gs_id)
        stage_ok = _stage_ok(str(gs["status"]), round_no, per_gs=per_gs)

        blockers: list[str] = []
        if slip is None:
            blockers.append(
                "No Replacement Slip at Accounts: the goods slip waits for the store analysis or "
                "Management approval."
                if per_gs
                else "No finalised A/c Actions slip: the Replacement Manager has not finalised the "
                "actions (or is revising them)."
            )
        elif completion is not None:
            blockers.append("The Accounts entry of this slip is already complete.")
        elif not stage_ok:
            blockers.append(f"The goods slip is not {_stage_text(round_no, per_gs=per_gs)}.")
        if entry is not None:
            if entry["requires_challan"] and entry["challan_no"] is None:
                blockers.append("Challan No. and Challan Date are missing.")
            if entry["requires_cn"] and entry["cn_no"] is None:
                blockers.append("CN No., CN Date and CN Value are missing.")
        for ln in needing if entry is None else []:
            if not ln.is_complete:
                missing = [
                    name
                    for flag, value, name in (
                        (ln.requires_cn, ln.cn_no, "CN No./Date/Value"),
                        (ln.requires_challan, ln.challan_no, "Challan No./Date"),
                    )
                    if flag and value is None
                ]
                blockers.append(
                    f"Line {ln.line_no} {ln.action_label}: {' and '.join(missing)} missing."
                )

        editable = slip is not None and completion is None and stage_ok
        return AcEntryState(
            gs_id=gs["id"],
            gs_no=gs["gs_no"],
            gs_status=gs["status"],
            party_name=gs["party_name"],
            party_code=gs["party_code"],
            ac_action_slip_id=slip["id"] if slip else None,
            slip_no=slip["slip_no"] if slip else None,
            version_no=slip["version_no"] if slip else None,
            round_no=round_no,
            lines=lines,
            lines_needing_data=len(needing),
            lines_complete=sum(1 for ln in needing if ln.is_complete),
            shipping_lines=sum(1 for ln in lines if ln.requires_challan),
            is_completed=completion is not None,
            completed_by_name=completion["completed_by_name"] if completion else None,
            completed_at=completion["completed_at"] if completion else None,
            can_edit=editable and perms.allows("ac_entry", "edit"),
            can_complete=editable and not blockers and perms.allows("ac_entry", "edit"),
            complete_blockers=blockers,
            dispatch_slip=_dslip_summary(dslip) if dslip else None,
            per_gs=per_gs,
            gs_entry=AcGsEntry(**{k: v for k, v in entry.items() if k != "id"}) if entry else None,
            slip_title=_template_name(session),
            management_stamp=management_approval.stamp_for_print(session, gs_id)
            if per_gs
            else None,
        )

    def _lock_current_slip(
        self, session: Session, gs_id: UUID, ac_slip_id: UUID
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        gs = repo.get_gs_header(session, gs_id, lock=True)
        if not gs:
            raise NotFound(f"Goods slip {gs_id} not found", code="GS_NOT_FOUND")
        slip = repo.current_ac_slip(session, gs_id)
        if slip is None or slip["id"] != ac_slip_id:
            raise Conflict(
                f"The A/c Actions slip of {gs['gs_no']} was revised; reload and enter the data "
                "on the current version",
                code="SLIP_NOT_CURRENT",
                details={"current_slip_id": str(slip["id"]) if slip else None},
            )
        if repo.get_completion(session, slip["id"]) is not None:
            raise SystemGuardViolation(
                "G-22",
                f"G-22: the Accounts entry of {slip['slip_no']} v{slip['version_no']} is complete "
                "and frozen",
            )
        round_no = int(slip["round_no"])
        per_gs = repo.gs_on_store_flow(session, gs_id)
        if not _stage_ok(str(gs["status"]), round_no, per_gs=per_gs):
            raise SystemGuardViolation(
                "G-22",
                "G-22: Accounts data changes only while the goods slip is "
                f"{_stage_text(round_no, per_gs=per_gs)} (status {gs['status']})",
            )
        slip["per_gs"] = per_gs
        return gs, slip

    # === save (partial allowed) ===

    def save(
        self,
        gs_id: UUID,
        payload: SaveAcEntryIn,
        user: CurrentUser,
        perms: EffectivePermissions,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        with self._uow.transaction(user.id) as session:
            return run_idempotent(
                session,
                idem,
                user.id,
                lambda: (200, self._save(session, gs_id, payload, user, perms)),
            )

    def _save(
        self,
        session: Session,
        gs_id: UUID,
        payload: SaveAcEntryIn,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> AcEntryState:
        _gs, slip = self._lock_current_slip(session, gs_id, payload.ac_action_slip_id)
        if slip["per_gs"]:
            raise Conflict(
                "This goods slip takes one Challan / Credit Note for the whole goods slip "
                "(DEC-71); use the goods-slip entry",
                code="PER_GS_ENTRY",
            )
        lines = {r["id"]: r for r in repo.entry_lines(session, slip["id"])}
        today = datetime.now(_tz(session)).date()

        seen: set[UUID] = set()
        for inp in payload.lines:
            row = lines.get(inp.line_id)
            if row is None:
                raise ValidationFailed(
                    f"Line {inp.line_id} is not on {slip['slip_no']} v{slip['version_no']}",
                    code="LINE_NOT_IN_SLIP",
                )
            if inp.line_id in seen:
                raise ValidationFailed(
                    f"Line {row['line_no']} {row['action_label']} is listed twice",
                    code="DUPLICATE_LINE",
                )
            seen.add(inp.line_id)
            label = f"Line {row['line_no']} {row['action_label']}"
            cn = (_clean(inp.cn_no), inp.cn_date, inp.cn_value)
            challan = (_clean(inp.challan_no), inp.challan_date)

            # AMD-18 / G-22: a field group only where the action's flag asks for it.
            if not row["requires_cn"] and any(v is not None for v in cn):
                raise SystemGuardViolation(
                    "G-22",
                    f"G-22: {label} does not take CN details (action flag requires_cn is off)",
                    details={"line_id": str(inp.line_id)},
                )
            if not row["requires_challan"] and any(v is not None for v in challan):
                raise SystemGuardViolation(
                    "G-22",
                    f"G-22: {label} does not take Challan details "
                    "(action flag requires_challan is off)",
                    details={"line_id": str(inp.line_id)},
                )
            if any(v is not None for v in cn) and not all(v is not None for v in cn):
                raise ValidationFailed(
                    f"{label}: CN No., CN Date and CN Value are entered together",
                    code="CN_FIELDS_INCOMPLETE",
                    details={"line_id": str(inp.line_id)},
                )
            if any(v is not None for v in challan) and not all(v is not None for v in challan):
                raise ValidationFailed(
                    f"{label}: Challan No. and Challan Date are entered together",
                    code="CHALLAN_FIELDS_INCOMPLETE",
                    details={"line_id": str(inp.line_id)},
                )
            for when, name in ((cn[1], "CN Date"), (challan[1], "Challan Date")):
                if when is not None and when > today:
                    raise ValidationFailed(
                        f"{label}: {name} cannot be in the future",
                        code="DATE_IN_FUTURE",
                        details={"line_id": str(inp.line_id)},
                    )
            # DEC-22 (credit_notes rule reused): an external voucher number is used once.
            if cn[0] is not None:
                holder = repo.cn_no_taken_elsewhere(session, cn_no=cn[0], gs_id=gs_id)
                if holder:
                    raise Conflict(
                        f"CN No. {cn[0]} is already recorded on {holder} (DEC-22)",
                        code="VOUCHER_NUMBER_TAKEN",
                        details={"cn_no": cn[0], "line_id": str(inp.line_id)},
                    )

            changed = cn != (row["cn_no"], row["cn_date"], row["cn_value"]) or challan != (
                row["challan_no"],
                row["challan_date"],
            )
            if changed:
                repo.update_entry_line(
                    session,
                    line_id=inp.line_id,
                    cn_no=cn[0],
                    cn_date=cn[1],
                    cn_value=cn[2],
                    challan_no=challan[0],
                    challan_date=challan[1],
                    by=user.id,
                )
        log.info("ac_entry_saved", gs_id=str(gs_id), slip_id=str(slip["id"]), lines=len(seen))
        return self._state(session, gs_id, perms)

    # === DEC-71: one Challan / Credit Note per goods slip (store flow) ===

    def save_gs_entry(
        self,
        gs_id: UUID,
        payload: SaveGsEntryIn,
        user: CurrentUser,
        perms: EffectivePermissions,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        with self._uow.transaction(user.id) as session:
            return run_idempotent(
                session,
                idem,
                user.id,
                lambda: (200, self._save_gs_entry(session, gs_id, payload, user, perms)),
            )

    def _save_gs_entry(
        self,
        session: Session,
        gs_id: UUID,
        payload: SaveGsEntryIn,
        user: CurrentUser,
        perms: EffectivePermissions,
    ) -> AcEntryState:
        gs, slip = self._lock_current_slip(session, gs_id, payload.ac_action_slip_id)
        entry = repo.get_gs_entry(session, slip["id"]) if slip["per_gs"] else None
        if entry is None:
            raise Conflict(
                f"{gs['gs_no']} takes Accounts data per action line, not per goods slip",
                code="NOT_PER_GS_ENTRY",
            )
        challan = (_clean(payload.challan_no), payload.challan_date)
        cn = (_clean(payload.cn_no), payload.cn_date, payload.cn_value)
        # DEC-71 / G-22: hidden fields are not sent: a group only where the goods slip needs it.
        if not entry["requires_challan"] and any(v is not None for v in challan):
            raise SystemGuardViolation(
                "G-22",
                f"G-22: {gs['gs_no']} ships no goods; it takes no Challan (DEC-71)",
            )
        if not entry["requires_cn"] and any(v is not None for v in cn):
            raise SystemGuardViolation(
                "G-22",
                f"G-22: {gs['gs_no']} has no Issue CN; it takes no Credit Note (DEC-71)",
            )
        if any(v is not None for v in challan) and not all(v is not None for v in challan):
            raise ValidationFailed(
                "Challan No. and Challan Date are entered together",
                code="CHALLAN_FIELDS_INCOMPLETE",
            )
        if any(v is not None for v in cn) and not all(v is not None for v in cn):
            raise ValidationFailed(
                "CN No., CN Date and CN Value are entered together", code="CN_FIELDS_INCOMPLETE"
            )
        today = datetime.now(_tz(session)).date()
        for when, name in ((challan[1], "Challan Date"), (cn[1], "CN Date")):
            if when is not None and when > today:
                raise ValidationFailed(f"{name} cannot be in the future", code="DATE_IN_FUTURE")
        if cn[0] is not None:
            holder = repo.cn_no_taken_elsewhere(session, cn_no=cn[0], gs_id=gs_id)
            if holder:
                raise Conflict(
                    f"CN No. {cn[0]} is already recorded on {holder} (DEC-22)",
                    code="VOUCHER_NUMBER_TAKEN",
                    details={"cn_no": cn[0]},
                )
        before = (
            (entry["challan_no"], entry["challan_date"]),
            (entry["cn_no"], entry["cn_date"], entry["cn_value"]),
        )
        if (challan, cn) != before:
            repo.update_gs_entry(
                session,
                ac_slip_id=slip["id"],
                challan_no=challan[0],
                challan_date=challan[1],
                cn_no=cn[0],
                cn_date=cn[1],
                cn_value=cn[2],
                by=user.id,
            )
        log.info("ac_gs_entry_saved", gs_id=str(gs_id), slip_id=str(slip["id"]))
        return self._state(session, gs_id, perms)

    def hold(self, user: CurrentUser) -> list[AcHoldItem]:
        """DEC-71 (Q21): goods slips on hold (every decision Not Allowed), read-only."""
        with self._uow.transaction(user.id) as session:
            return [AcHoldItem(**r) for r in repo.list_hold(session)]

    def print_replacement_slip(
        self, gs_id: UUID, user: CurrentUser, storage: StorageService
    ) -> ReplacementSlipPrintOut:
        """Print / re-print the CURRENT Replacement Slip PDF of a goods slip (logged)."""
        with self._uow.transaction(user.id) as session:
            current = repo.current_ac_slip(session, gs_id)
            slip = repo.ac_slip_file(session, gs_id, current["id"]) if current else None
            if not slip:
                raise NotFound(
                    f"Goods slip {gs_id} has no current Replacement Slip", code="SLIP_NOT_FOUND"
                )
            ttl = signed_url_ttl(session)
            url = storage.create_signed_url(Bucket(slip["bucket"]), slip["object_path"], ttl)
            repo.insert_ac_slip_print_log(
                session,
                slip_id=slip["id"],
                version_no=slip["version_no"],
                by=user.id,
                metadata={
                    "gs_id": str(gs_id),
                    "slip_no": slip["slip_no"],
                    "version_no": slip["version_no"],
                    "is_reprint": int(slip["print_count"]) > 0,
                },
            )
            return ReplacementSlipPrintOut(
                ac_action_slip_id=slip["id"],
                slip_no=slip["slip_no"],
                version_no=slip["version_no"],
                url=url,
                expires_in=ttl,
                print_count=int(slip["print_count"]) + 1,
            )

    # === complete ===

    def complete(
        self,
        gs_id: UUID,
        payload: CompleteAcEntryIn,
        user: CurrentUser,
        perms: EffectivePermissions,
        idem: IdempotencyKey,
        storage: StorageService,
    ) -> IdempotentResult:
        uploaded: list[str] = []
        try:
            with self._uow.transaction(user.id) as session:
                return run_idempotent(
                    session,
                    idem,
                    user.id,
                    lambda: (
                        200,
                        self._complete(
                            session, gs_id, payload, user, perms, storage, uploaded.append
                        ),
                    ),
                )
        except Exception:
            # The transaction rolled back, so the stored PDF has no row: remove it, then re-raise.
            for path in uploaded:
                try:
                    storage.delete(Bucket.DOCUMENTS, path)
                except ServiceUnavailable:
                    log.error("dispatch_slip_orphan_pdf_not_removed", gs_id=str(gs_id), path=path)
            raise

    def _complete(
        self,
        session: Session,
        gs_id: UUID,
        payload: CompleteAcEntryIn,
        user: CurrentUser,
        perms: EffectivePermissions,
        storage: StorageService,
        on_uploaded: Callable[[str], None],
    ) -> AcEntryState:
        gs, slip = self._lock_current_slip(session, gs_id, payload.ac_action_slip_id)
        lines = repo.entry_lines(session, slip["id"])
        if not lines:
            raise SystemGuardViolation("G-22", "G-22: the A/c Actions slip has no action lines")
        per_gs = bool(slip["per_gs"])
        entry = repo.get_gs_entry(session, slip["id"]) if per_gs else None
        if per_gs:
            # DEC-71: one Challan (goods ship) and one Credit Note (Issue CN) per goods slip.
            if entry is None or not entry["is_complete"]:
                raise SystemGuardViolation(
                    "G-22",
                    "G-22: the goods slip needs its Challan No. / Date (goods to ship) and / or "
                    "CN No. / Date / Value (Issue CN) before completion (DEC-71)",
                )
            # The goods slip's one Challan is the challan of every shipping line.
            lines = [
                {**ln, "challan_no": entry["challan_no"], "challan_date": entry["challan_date"]}
                if ln["requires_challan"]
                else ln
                for ln in lines
            ]
        open_lines = [] if per_gs else [ln for ln in lines if not ln["is_complete"]]
        if open_lines:
            raise SystemGuardViolation(
                "G-22",
                "G-22: every action line needs its Accounts data before completion; missing on "
                + ", ".join(f"line {ln['line_no']} {ln['action_label']}" for ln in open_lines),
                details={"line_ids": [str(ln["id"]) for ln in open_lines]},
            )
        remarks = _clean(payload.remarks)
        repo.insert_completion(
            session, gs_id=gs_id, ac_slip_id=slip["id"], by=user.id, remarks=remarks
        )

        shipping = [ln for ln in lines if ln["requires_challan"]]
        if shipping:
            dslip_no = self._generate_dispatch_slip(
                session, gs, slip, shipping, user, storage, on_uploaded, entry=entry
            )
            outcome = f"Dispatch Slip {dslip_no} generated for {len(shipping)} line(s)."
            if per_gs:
                # DEC-71: the goods slip moves to the Dispatch queue.
                gs_service.change_status(
                    session,
                    gs_id=gs_id,
                    from_status=ACCOUNTS_STATUS,
                    to_status=DISPATCH_STATUS,
                    step_code=ACCOUNTS_STEP,
                    reason=f"Accounts completed; Dispatch Slip {dslip_no} generated (DEC-71)",
                    by=user.id,
                )
        else:
            moves = _settle_returned_goods(
                session,
                ac_slip_id=slip["id"],
                source_code=_source_location(int(slip["round_no"])),
                lines=lines,
                reference_type=repo.AC_SLIP_ENTITY,
                reference_id=slip["id"],
                reason=f"Accounts completed {slip['slip_no']} v{slip['version_no']} (AMD-18)",
                actor_id=user.id,
                source_by_item=repo.item_store_locations(session, gs_id) if per_gs else None,
            )
            new_status = _to_closure(
                session,
                gs,
                reason="Accounts entry complete; no goods to ship (AMD-18)",
                by=user.id,
            )
            log.info("ac_flow_settled", gs_id=str(gs_id), moves=moves, status=new_status)
            outcome = "No line ships goods; the goods slip moves on to closure."

        notifications.publish(
            session,
            "AC_ENTRY_COMPLETED",
            title=f"{gs['gs_no']}: Accounts entry complete",
            body=f"{user.full_name} completed {slip['slip_no']} v{slip['version_no']}. {outcome}",
            entity_type=repo.AC_SLIP_ENTITY,
            entity_id=slip["id"],
            gs_id=gs_id,
            data={"gs_no": gs["gs_no"], "slip_no": slip["slip_no"]},
            dedupe_key=f"ac-entry-completed:{slip['id']}",
        )
        # Phase 9 (AMD-20): queue the party email if party_email.delivery.auto_send asks for it
        # (OFF by default); delivered by the worker after this transaction commits.
        party_email.queue_auto(
            session,
            gs_id,
            stage="AC_COMPLETED",
            has_dispatch_slip=bool(shipping),
            by=user.id,
        )
        log.info("ac_entry_completed", gs_id=str(gs_id), slip_id=str(slip["id"]))
        return self._state(session, gs_id, perms)

    def _generate_dispatch_slip(
        self,
        session: Session,
        gs: dict[str, Any],
        ac_slip: dict[str, Any],
        shipping: list[dict[str, Any]],
        user: CurrentUser,
        storage: StorageService,
        on_uploaded: Callable[[str], None],
        *,
        entry: dict[str, Any] | None = None,
    ) -> str:
        """AMD-19: numbered Dispatch Slip PDF of the goods-shipping lines (DEC-41 template).
        DEC-71: on the store flow `entry` is the goods slip's one Challan / Credit Note."""
        template = repo.published_template(session, repo.DISPATCH_SLIP_TEMPLATE)
        if not template:
            raise Conflict(
                "No published DISPATCH_SLIP print template", code="TEMPLATE_NOT_PUBLISHED"
            )
        tz = _tz(session)
        fmt = _date_fmt(session)
        slip_id = uuid.uuid4()
        slip_no = repo.next_number(session, repo.DISPATCH_SLIP_SERIES)
        content = {
            "slip_no": slip_no,
            "gs_no": gs["gs_no"],
            "ac_slip_no": ac_slip["slip_no"],
            "ac_version_no": ac_slip["version_no"],
            "party_name": gs["party_name"] or "",
            "party_code": gs["party_code"] or "",
            "state_station": " / ".join(x for x in (gs["state_name"], gs["station_name"]) if x),
            "generated_at": datetime.now(tz).strftime(f"{fmt} %H:%M"),
            "prepared_by": user.full_name,
            "lines": [
                {
                    "line_no": ln["line_no"],
                    "product_code": ln["product_code"] or "",
                    "product_name": ln["product_name"],
                    "action_code": ln["action_code"],
                    "action_label": ln["action_label"],
                    "condition_label": ln.get("condition_label"),
                    "qty": ln["qty"],
                    "challan_no": ln["challan_no"],
                    "challan_date": _fmt_date(ln["challan_date"], fmt, tz),
                }
                for ln in shipping
            ],
            "total_qty": sum(int(ln["qty"]) for ln in shipping),
            "ac_slip_title": _template_name(session),
        }
        if entry is not None:
            content["challan_no"] = entry["challan_no"] or ""
            content["challan_date"] = _fmt_date(entry["challan_date"], fmt, tz)
            if entry["cn_no"]:
                content["cn_no"] = entry["cn_no"]
                content["cn_date"] = _fmt_date(entry["cn_date"], fmt, tz)
                content["cn_value"] = str(entry["cn_value"])
        # DEC-70: the Management e-approval stamp (VALID approval only) is printed and recorded.
        content["management_stamp"] = management_approval.stamp_for_print(session, gs["id"])
        pdf = render_slip_pdf(self._slip_document(session, template, content))
        digest = hashlib.sha256(pdf).hexdigest()
        path = build_object_path(gs["id"], "generated_pdf", "pdf")
        storage.upload(Bucket.DOCUMENTS, path, pdf, PDF_MIME)
        on_uploaded(path)
        attachment_id = repo.insert_generated_pdf(
            session,
            gs_id=gs["id"],
            entity_id=slip_id,
            bucket=Bucket.DOCUMENTS.value,
            object_path=path,
            size_bytes=len(pdf),
            by=user.id,
        )
        repo.insert_dispatch_slip(
            session,
            slip_id=slip_id,
            gs_id=gs["id"],
            ac_slip_id=ac_slip["id"],
            slip_no=slip_no,
            attachment_id=attachment_id,
            template_version_no=int(template["version_no"]),
            content=content,
            sha256=digest,
            by=user.id,
        )
        for ln in shipping:
            repo.insert_dispatch_slip_line(session, slip_id=slip_id, entry=ln)
        # AMD-19: DISPATCH is told; recipients come from the notification rule, not code.
        # The body lists what to send per line (action label snapshot = new / repaired goods),
        # product, qty and the challan Accounts entered (AMD-18), so the team can act on it.
        to_send = "\n".join(
            f"• {ln['action_label']}: {ln['qty']} pc - "
            f"{' '.join(x for x in (ln['product_code'], ln['product_name']) if x)}"
            + (f" [{ln['condition_label']}]" if ln.get("condition_label") else "")
            + (
                f" (Challan {ln['challan_no']}"
                + (f" dt {ln['challan_date']}" if ln["challan_date"] else "")
                + ")"
                if ln["challan_no"]
                else ""
            )
            for ln in content["lines"]
        )
        destination = " / ".join(x for x in (content["party_name"], content["state_station"]) if x)
        notifications.publish(
            session,
            "DISPATCH_SLIP_READY",
            title=f"{gs['gs_no']}: Dispatch Slip {slip_no} ready - send {content['total_qty']} pc",
            body=(
                f"Ship to {destination or 'the party'}:\n{to_send}\n"
                f"Issue the goods against Dispatch Slip {slip_no}."
            ),
            entity_type=repo.DISPATCH_SLIP_ENTITY,
            entity_id=slip_id,
            gs_id=gs["id"],
            data={"gs_no": gs["gs_no"], "slip_no": slip_no},
            dedupe_key=f"dispatch-slip-ready:{slip_id}",
        )
        log.info("dispatch_slip_generated", gs_id=str(gs["id"]), slip_no=slip_no, size=len(pdf))
        return slip_no

    def _slip_document(
        self, session: Session, template: dict[str, Any], c: dict[str, Any]
    ) -> SlipDocument:
        """Map the published template layout (DEC-41: branding is configuration) + content."""
        layout: dict[str, Any] = template["layout"] or {}
        titles = {
            s.get("id"): s.get("title") for s in layout.get("sections", []) if isinstance(s, dict)
        }

        def title(section_id: str, fallback: str) -> str:
            return str(titles.get(section_id) or fallback)

        signatures = [
            SlipSignature(
                label=str(block.get("label", "")),
                role=str(block.get("role", "")),
                name=c["prepared_by"] if i == 0 else None,
            )
            for i, block in enumerate(layout.get("signature_blocks", []))
            if isinstance(block, dict)
        ]
        return SlipDocument(
            title=str(layout.get("header_title") or template.get("name") or ""),
            subtitle=str(layout.get("header_subtitle") or template.get("name") or ""),
            document_ref=f"{c['slip_no']} · {c['gs_no']}",
            stamp=c.get("management_stamp"),
            sections=[
                SlipSection(
                    title("header", "Dispatch Slip"),
                    [
                        SlipField("Dispatch Slip No.", c["slip_no"]),
                        SlipField("GS No.", c["gs_no"]),
                        SlipField(
                            str(c.get("ac_slip_title") or "A/c Actions Slip"),
                            f"{c['ac_slip_no']} (v{c['ac_version_no']})",
                        ),
                        SlipField("Generated", c["generated_at"]),
                        # DEC-71: the goods slip's one Challan / Credit Note.
                        *(
                            [SlipField("Challan", f"{c['challan_no']} dt {c['challan_date']}")]
                            if c.get("challan_no")
                            else []
                        ),
                        *(
                            [
                                SlipField(
                                    "Credit Note",
                                    f"{c['cn_no']} dt {c['cn_date']} · ₹ {c['cn_value']}",
                                )
                            ]
                            if c.get("cn_no")
                            else []
                        ),
                    ],
                ),
                SlipSection(
                    title("party", "Ship To"),
                    [
                        SlipField("Party", c["party_name"]),
                        SlipField("Party Code", c["party_code"]),
                        SlipField("State / Station", c["state_station"]),
                    ],
                ),
            ],
            tables=[
                SlipTable(
                    title=title("items", "Goods to Ship"),
                    columns=[
                        SlipColumn("#", 0.4, "right"),
                        SlipColumn("Code", 0.9),
                        SlipColumn("Product", 2.0),
                        SlipColumn("Condition", 1.1),
                        SlipColumn("Action", 1.1),
                        SlipColumn("Qty", 0.5, "right"),
                        SlipColumn("Challan No.", 1.1),
                        SlipColumn("Challan Date", 0.9),
                    ],
                    rows=[
                        [
                            str(ln["line_no"]),
                            ln["product_code"],
                            ln["product_name"],
                            ln.get("condition_label") or "",
                            ln["action_label"],
                            str(ln["qty"]),
                            ln["challan_no"],
                            ln["challan_date"],
                        ]
                        for ln in c["lines"]
                    ],
                    total_row=["", "", "Total", "", "", str(c["total_qty"]), "", ""],
                )
            ],
            signatures=signatures,
            signatures_title=title("signatures", "Signatures"),
            footer_text=str(layout.get("footer_text") or ""),
            generated_text=f"Generated {c['generated_at']} by {c['prepared_by']}",
            brand_color=str(repo.get_setting(session, "branding_primary_color") or ""),
            paper_size=str(layout.get("paper_size") or "A4"),
            orientation=str(layout.get("orientation") or "portrait"),
            logo=template_logo(session, layout),  # DEC-65 / Q26
        )


# =================================================================================================
# Dispatch Slip
# =================================================================================================


class DispatchSlipService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def list_slips(self, user: CurrentUser, *, status: str | None) -> list[DispatchSlipOut]:
        with self._uow.transaction(user.id) as session:
            rows = repo.list_dispatch_slips(session, status=status)
            return [_dslip_out(session, r) for r in rows]

    def get_slip(self, slip_id: UUID, user: CurrentUser) -> DispatchSlipOut:
        with self._uow.transaction(user.id) as session:
            row = repo.get_dispatch_slip(session, slip_id)
            if not row:
                raise NotFound(f"Dispatch Slip {slip_id} not found", code="DISPATCH_SLIP_NOT_FOUND")
            return _dslip_out(session, row)

    def dispatch(
        self,
        slip_id: UUID,
        payload: DispatchIn,
        user: CurrentUser,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        with self._uow.transaction(user.id) as session:
            return run_idempotent(
                session,
                idem,
                user.id,
                lambda: (200, self._dispatch(session, slip_id, payload, user)),
            )

    def _dispatch(
        self, session: Session, slip_id: UUID, payload: DispatchIn, user: CurrentUser
    ) -> DispatchSlipOut:
        locked = repo.lock_dispatch_slip(session, slip_id)
        if not locked:
            raise NotFound(f"Dispatch Slip {slip_id} not found", code="DISPATCH_SLIP_NOT_FOUND")
        if locked["status"] != "READY":
            raise Conflict(
                f"Dispatch Slip {locked['slip_no']} is already dispatched",
                code="ALREADY_DISPATCHED",
            )
        gs = repo.get_gs_header(session, locked["gs_id"], lock=True)
        if not gs:
            raise NotFound("Goods slip not found", code="GS_NOT_FOUND")
        ac_slip = repo.get_ac_slip(session, locked["ac_action_slip_id"])
        round_no = int(ac_slip["round_no"]) if ac_slip else 1
        per_gs = repo.gs_on_store_flow(session, gs["id"])  # DEC-71
        if not _stage_ok(str(gs["status"]), round_no, per_gs=per_gs, dispatch=True):
            raise Conflict(
                f"Goods slip {gs['gs_no']} is not "
                f"{_stage_text(round_no, per_gs=per_gs, dispatch=True)} (status {gs['status']})",
                code="INVALID_GS_STATUS",
            )
        today = datetime.now(_tz(session)).date()
        if payload.dispatch_date > today:
            raise ValidationFailed(
                "The dispatch date cannot be in the future", code="DATE_IN_FUTURE"
            )
        transporter = _clean(payload.transporter)
        docket = _clean(payload.docket_no)
        vehicle = _clean(payload.vehicle_no)
        if transporter is None:
            raise ValidationFailed("Transporter / courier is required (DEC-26)", code="TRACKING")
        if docket is None and vehicle is None:
            raise ValidationFailed(
                "A docket number or a vehicle number is required (DEC-26)", code="TRACKING"
            )

        # Store issue (AMD-19): returned pieces leave the intermediate store via rms_move_stock.
        lines = repo.entry_lines(session, locked["ac_action_slip_id"])
        moves = _settle_returned_goods(
            session,
            ac_slip_id=locked["ac_action_slip_id"],
            source_code=_source_location(round_no),
            lines=lines,
            reference_type=repo.DISPATCH_SLIP_ENTITY,
            reference_id=slip_id,
            reason=f"Dispatch Slip {locked['slip_no']} (AMD-19)",
            actor_id=user.id,
            source_by_item=repo.item_store_locations(session, gs["id"]) if per_gs else None,
        )
        repo.mark_dispatched(
            session,
            slip_id=slip_id,
            dispatch_date=payload.dispatch_date,
            transporter=transporter,
            docket_no=docket,
            vehicle_no=vehicle,
            remarks=_clean(payload.remarks),
            by=user.id,
        )
        new_status = _to_closure(
            session,
            gs,
            reason=f"Dispatch Slip {locked['slip_no']} dispatched (AMD-19)",
            by=user.id,
        )
        notifications.publish(
            session,
            "DISPATCH_SLIP_DISPATCHED",
            title=f"{gs['gs_no']}: Dispatch Slip {locked['slip_no']} dispatched",
            body=(
                f"{user.full_name} dispatched via {transporter}"
                f"{' docket ' + docket if docket else ''}"
                f"{' vehicle ' + vehicle if vehicle else ''}."
            ),
            entity_type=repo.DISPATCH_SLIP_ENTITY,
            entity_id=slip_id,
            gs_id=gs["id"],
            data={"gs_no": gs["gs_no"], "slip_no": locked["slip_no"]},
            dedupe_key=f"dispatch-slip-dispatched:{slip_id}",
        )
        # Phase 9 (AMD-20): auto-send mode ON_DISPATCH emails the party with the tracking data.
        party_email.queue_auto(
            session, gs["id"], stage="DISPATCHED", has_dispatch_slip=True, by=user.id
        )
        log.info(
            "dispatch_slip_dispatched",
            slip_id=str(slip_id),
            gs_id=str(gs["id"]),
            moves=moves,
            gs_status=new_status,
        )
        row = repo.get_dispatch_slip(session, slip_id)
        assert row is not None  # noqa: S101 - locked and updated above in this transaction
        return _dslip_out(session, row)

    def print_slip(
        self, slip_id: UUID, user: CurrentUser, storage: StorageService
    ) -> DispatchSlipPrintOut:
        """Print / re-print the stored PDF at any time; every print is logged."""
        with self._uow.transaction(user.id) as session:
            row = repo.get_dispatch_slip(session, slip_id)
            if not row:
                raise NotFound(f"Dispatch Slip {slip_id} not found", code="DISPATCH_SLIP_NOT_FOUND")
            ttl = signed_url_ttl(session)
            url = storage.create_signed_url(Bucket(row["bucket"]), row["object_path"], ttl)
            repo.insert_print_log(
                session,
                slip_id=slip_id,
                by=user.id,
                metadata={
                    "gs_id": str(row["gs_id"]),
                    "slip_no": row["slip_no"],
                    "status": row["status"],
                    "is_reprint": int(row["print_count"]) > 0,
                },
            )
            return DispatchSlipPrintOut(
                dispatch_slip_id=slip_id,
                slip_no=row["slip_no"],
                url=url,
                expires_in=ttl,
                print_count=int(row["print_count"]) + 1,
            )
