"""Prior party notification (P3-07; BR-38, DD r79, G-15, DEC-25).

* Accounts (S6_NOTIFY PERFORM) records that the party was told the CN / JV No., Date and items
  (plus replacement dispatch details where relevant) **before** closure. Status PRIOR_INFO_SENT.
* The structured `message_snapshot` is always built here from the issued CN / dispatch records;
  the human text uses the `party_notification_message_template` setting (CLAUDE.md rule e).
* DEC-25: channel, recipient, timestamp, snapshot and an optional proof attachment
  (NOTIFICATION_PROOF) are stored. Records made here are "Recorded manually".
* Phase 9 (AMD-20): on the A/c Actions flow the draft is built from the values Accounts entered
  (CN / Challan / Dispatch) once Accounts completed the entry; the party email itself (preview,
  send, log, resend, auto-send) lives in `email_service.py`, where a SENT email records
  PRIOR_INFO_SENT.
* The DB trigger `party_notifications_guard` repeats the ISSUED-CN / proof / append-only rules.
"""

from __future__ import annotations

import re
import string
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from app.core.db import UnitOfWork
from app.core.errors import Conflict, ValidationFailed
from app.core.idempotency import IdempotencyKey, IdempotentResult, run_idempotent
from app.core.permissions import EffectivePermissions, assert_step_actor, step_codes_for
from app.core.security import CurrentUser
from app.modules.goods_slips import service as gs_service
from app.modules.party_notifications import email_service
from app.modules.party_notifications import repository as repo
from app.modules.party_notifications.schemas import (
    CHANNEL_CODES,
    NotificationDraftOut,
    PartyNotificationIn,
    PartyNotificationOut,
    PartyNotificationStateOut,
    RecipientSuggestion,
)

log = structlog.get_logger("rms.party_notifications")

NOTIFY_STEP = "S6_NOTIFY"
FORM_CODE = "S6_PARTY_NOTIFY"
STATUS_SET = "PARTY_NOTIFICATION_STATUS"  # DD r79
STATUS_CODE = "PRIOR_INFO_SENT"
RECORDABLE = frozenset({"IN_PROCESS", "COMMERCIAL_RESOLUTION", "AWAITING_NOTIFICATION"})
TEMPLATE_KEY = "party_notification_message_template"
_FORMATTER = string.Formatter()
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE = re.compile(r"^\+?[0-9][0-9 \-]{6,18}[0-9]$")


class _Blank(dict[str, str]):
    """format_map mapping: an unknown placeholder renders as empty text (admin-edited template)."""

    def __missing__(self, key: str) -> str:
        return ""


def _fmt_date(value: date | None) -> str:
    return value.strftime("%d-%m-%Y") if value else ""


def _fmt_money(value: Decimal | None) -> str:
    return f"{value:,.2f}" if value is not None else ""


def build_snapshot(
    *,
    gs_no: str,
    party_name: str | None,
    credit_note: dict[str, Any] | None,
    items: list[dict[str, Any]],
    dispatches: list[dict[str, Any]],
) -> dict[str, Any]:
    """BR-38 / DD r79: CN No. + CN Date + items (+ dispatch details where relevant), JSON-safe."""
    cn_out: dict[str, Any] | None = None
    if credit_note:
        voucher_date = credit_note["cn_date"] or credit_note["jv_date"]
        cn_out = {
            "id": str(credit_note["id"]),
            "cn_type_code": credit_note["cn_type_code"],
            "cn_type_label": credit_note["cn_type_label"],
            "voucher_no": credit_note["cn_no"] or credit_note["jv_no"],
            "voucher_date": voucher_date.isoformat() if voucher_date else None,
            "total_value": str(credit_note["total_value"]),
        }
    return {
        "gs_no": gs_no,
        "party_name": party_name,
        "credit_note": cn_out,
        "items": [
            {
                "line_no": i["line_no"],
                "product_code": i["product_code"],
                "product_name": i["product_name"],
                "qty": i["qty"],
            }
            for i in items
        ],
        "dispatches": [
            {
                "dispatch_no": d["dispatch_no"],
                "dispatch_type": d["dispatch_type"],
                "transporter": d["transporter"],
                "docket_no": d["docket_no"],
                "vehicle_no": d["vehicle_no"],
                "qty": d["qty"],
                "dispatched_at": d["dispatched_at"].isoformat() if d["dispatched_at"] else None,
            }
            for d in dispatches
        ],
    }


def render_message(template: str, snapshot: dict[str, Any]) -> str:
    """Fill the configured template (setting `party_notification_message_template`)."""
    cn = snapshot.get("credit_note") or {}
    voucher_date = cn.get("voucher_date")
    items = "\n".join(
        " ".join(str(x) for x in (f"{i['line_no']}.", i["product_code"], i["product_name"]) if x)
        + f" - {i['qty']} pcs"
        for i in snapshot.get("items") or []
    )
    dispatch = "\n".join(
        f"Replacement dispatch {d['dispatch_no']}: {d['qty']} pcs via {d['transporter']}"
        + (f" (docket {d['docket_no']})" if d.get("docket_no") else "")
        for d in snapshot.get("dispatches") or []
    )
    values = _Blank(
        party_name=snapshot.get("party_name") or "",
        gs_no=snapshot.get("gs_no") or "",
        voucher_label=cn.get("cn_type_label") or cn.get("cn_type_code") or "",
        voucher_no=cn.get("voucher_no") or "",
        voucher_date=_fmt_date(date.fromisoformat(voucher_date)) if voucher_date else "",
        items=items,
        total_value=_fmt_money(Decimal(cn["total_value"])) if cn.get("total_value") else "",
        dispatch_details=dispatch,
    )
    out: list[str] = []
    try:
        for line in template.splitlines():
            names = [f for _, f, _, _ in _FORMATTER.parse(line) if f]
            # A line whose placeholders are all empty (e.g. "Total value: " on a dispatch-only
            # notice) is left out.
            if names and all(not values[n] for n in names):
                continue
            out.append(line.format_map(values).rstrip())
    except (ValueError, IndexError) as exc:
        raise Conflict(
            f"The setting {TEMPLATE_KEY} is not a valid message template: {exc}",
            code="TEMPLATE_INVALID",
        ) from exc
    return "\n".join(out).strip()


def _check_recipient(channel: str, recipient: str) -> None:
    if channel == "EMAIL" and not _EMAIL.fullmatch(recipient):
        raise ValidationFailed(
            "Enter a valid e-mail address for an e-mail notification",
            code="FORM_VALIDATION_FAILED",
            details={"recipient": ["Not a valid e-mail address"]},
        )
    if channel in ("WHATSAPP", "PHONE") and not _PHONE.fullmatch(recipient):
        raise ValidationFailed(
            "Enter a valid phone number for a WhatsApp / phone notification",
            code="FORM_VALIDATION_FAILED",
            details={"recipient": ["Not a valid phone number"]},
        )


class PartyNotificationService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def get_state(
        self, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID
    ) -> PartyNotificationStateOut:
        with self._uow.transaction(user.id) as session:
            gs = gs_service.get_visible_goods_slip(session, user, perms, gs_id)
            contact = repo.party_contact(session, gs_id) or {}
            _, ac_snapshot, _ = email_service.ac_context(session, gs)
            drafts = self._drafts(session, gs, contact.get("party_name"), ac_snapshot)
            return PartyNotificationStateOut(
                gs_id=gs_id,
                gs_no=gs["gs_no"],
                status=gs["status"],
                can_record=(gs["status"] in RECORDABLE or ac_snapshot is not None)
                and NOTIFY_STEP in step_codes_for(session, user, "PERFORM"),
                status_label=repo.option_label(session, STATUS_SET, STATUS_CODE),
                channels=list(CHANNEL_CODES),
                recipient=RecipientSuggestion(
                    party_name=contact.get("party_name"),
                    contact_name=contact.get("contact_name"),
                    email=contact.get("email"),
                    phone=contact.get("phone"),
                ),
                drafts=drafts,
                notifications=[
                    PartyNotificationOut(**n) for n in repo.list_notifications(session, gs_id)
                ],
                party_email=email_service.PartyEmailService(self._uow).state(
                    session, user, gs, perms
                ),
            )

    def record(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: PartyNotificationIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        recipient = payload.recipient.strip()
        _check_recipient(payload.channel, recipient)
        with self._uow.transaction(user.id) as session:

            def command() -> tuple[int, Any]:
                gs = gs_service.lock_goods_slip(session, gs_id)
                view = gs_service.get_visible_goods_slip(session, user, perms, gs_id)
                assert_step_actor(session, user, NOTIFY_STEP, "PERFORM")
                # AMD-20: on the A/c Actions flow the party can be told as soon as Accounts
                # completed the entry (the GS may still be held at the intermediate store).
                _, ac_snapshot, _ = email_service.ac_context(session, gs)
                if gs["status"] not in RECORDABLE and ac_snapshot is None:
                    raise Conflict(
                        "A party notification can only be recorded before the GS is closed",
                        code="GS_NOT_IN_COMMERCIAL_STAGE",
                        details={"status": gs["status"]},
                    )
                credit_note: dict[str, Any] | None = None
                if payload.credit_note_id is not None:
                    credit_note = next(
                        (
                            c
                            for c in repo.issued_credit_notes(session, gs_id)
                            if c["id"] == payload.credit_note_id
                        ),
                        None,
                    )
                    if credit_note is None:
                        cn = repo.get_credit_note(session, payload.credit_note_id)
                        raise ValidationFailed(
                            "BR-38: the party is notified of an ISSUED credit note / JV of this GS",
                            code="CREDIT_NOTE_NOT_ISSUED",
                            details={
                                "credit_note_id": [
                                    "Not an issued credit note of this goods slip"
                                    if cn is None or cn["gs_id"] != gs_id
                                    else f"Credit note status is {cn['status']}"
                                ]
                            },
                        )
                dispatches = repo.dispatches(session, gs_id)
                if credit_note is None and not dispatches and ac_snapshot is None:
                    raise ValidationFailed(
                        "Choose the issued credit note / JV the party is being told about",
                        code="NOTHING_TO_NOTIFY",
                        details={"credit_note_id": ["Required: no dispatch details to send"]},
                    )
                if payload.proof_attachment_id is not None:
                    att = repo.get_attachment(session, payload.proof_attachment_id)
                    if (
                        not att
                        or att["gs_id"] != gs_id
                        or att["kind"] != "NOTIFICATION_PROOF"
                        or att["status"] != "CONFIRMED"
                    ):
                        raise ValidationFailed(
                            "DEC-25: the proof must be a confirmed notification-proof upload",
                            code="PROOF_NOT_CONFIRMED",
                            details={"proof_attachment_id": ["Upload and confirm the proof first"]},
                        )
                contact = repo.party_contact(session, gs_id) or {}
                snapshot: dict[str, Any]
                if credit_note is None and ac_snapshot is not None:
                    # AMD-20: the Accounts values of the completed A/c Actions slip.
                    snapshot = ac_snapshot
                    message = (payload.message or "").strip() or (
                        email_service.ac_draft_message(session, ac_snapshot)
                    )
                else:
                    snapshot = build_snapshot(
                        gs_no=gs["gs_no"],
                        party_name=contact.get("party_name"),
                        credit_note=credit_note,
                        items=(
                            repo.credit_note_items(session, credit_note["id"])
                            if credit_note
                            else []
                        ),
                        dispatches=dispatches,
                    )
                    message = (payload.message or "").strip() or render_message(
                        str(repo.get_setting(session, TEMPLATE_KEY) or ""), snapshot
                    )
                if not message:
                    raise ValidationFailed(
                        "The notification message is empty",
                        code="FORM_VALIDATION_FAILED",
                        details={"message": ["Required"]},
                    )
                notification_id = repo.insert_notification(
                    session,
                    gs_id=gs_id,
                    credit_note_id=credit_note["id"] if credit_note else None,
                    status_label=repo.option_label(session, STATUS_SET, STATUS_CODE),
                    channel_code=payload.channel,
                    recipient=recipient,
                    message=message,
                    snapshot=snapshot,
                    proof_attachment_id=payload.proof_attachment_id,
                    form_version_id=repo.published_form_version_id(session, FORM_CODE),
                    by=user.id,
                )
                email_service.after_notification(session, view, user.id)
                log.info(
                    "party_notification_recorded",
                    gs_id=str(gs_id),
                    notification_id=str(notification_id),
                    channel=payload.channel,
                    has_proof=payload.proof_attachment_id is not None,
                )
                row = next(
                    n for n in repo.list_notifications(session, gs_id) if n["id"] == notification_id
                )
                return 201, PartyNotificationOut(**row)

            return run_idempotent(session, idem, user.id, command)

    # ---------------------------------------------------------------- internals --------------
    def _drafts(
        self,
        session: Session,
        gs: dict[str, Any],
        party_name: str | None,
        ac_snapshot: dict[str, Any] | None,
    ) -> list[NotificationDraftOut]:
        template = str(repo.get_setting(session, TEMPLATE_KEY) or "")
        dispatches = repo.dispatches(session, gs["id"])
        notified = {n["credit_note_id"] for n in repo.list_notifications(session, gs["id"])}
        drafts: list[NotificationDraftOut] = []
        if ac_snapshot is not None:
            # AMD-20: one draft from the Accounts values. An invalid template is reported on the
            # email panel (template_error); the draft text is then empty for the user to write.
            try:
                message = email_service.ac_draft_message(session, ac_snapshot)
            except Conflict as exc:
                log.error("party_email_template_invalid", gs_id=str(gs["id"]), error=exc.message)
                message = ""
            cn_nos = sorted({ln["cn_no"] for ln in ac_snapshot["cn_lines"]})
            total = ac_snapshot["cn_total_value"]
            drafts.append(
                NotificationDraftOut(
                    source="AC_ACTIONS",
                    credit_note_id=None,
                    cn_type_code=None,
                    cn_type_label=None,
                    voucher_no=", ".join(cn_nos) or None,
                    voucher_date=None,
                    total_value=Decimal(total) if total is not None else None,
                    notified=None in notified,
                    message=message,
                    snapshot=ac_snapshot,
                )
            )
        for cn in repo.issued_credit_notes(session, gs["id"]):
            snapshot = build_snapshot(
                gs_no=gs["gs_no"],
                party_name=party_name,
                credit_note=cn,
                items=repo.credit_note_items(session, cn["id"]),
                dispatches=dispatches,
            )
            drafts.append(
                NotificationDraftOut(
                    source="CREDIT_NOTE",
                    credit_note_id=cn["id"],
                    cn_type_code=cn["cn_type_code"],
                    cn_type_label=cn["cn_type_label"],
                    voucher_no=cn["cn_no"] or cn["jv_no"],
                    voucher_date=cn["cn_date"] or cn["jv_date"],
                    total_value=cn["total_value"],
                    notified=cn["id"] in notified,
                    message=render_message(template, snapshot),
                    snapshot=snapshot,
                )
            )
        if not drafts and dispatches:
            snapshot = build_snapshot(
                gs_no=gs["gs_no"],
                party_name=party_name,
                credit_note=None,
                items=[],
                dispatches=dispatches,
            )
            drafts.append(
                NotificationDraftOut(
                    source="DISPATCH",
                    credit_note_id=None,
                    cn_type_code=None,
                    cn_type_label=None,
                    voucher_no=None,
                    voucher_date=None,
                    total_value=None,
                    notified=None in notified,
                    message=render_message(template, snapshot),
                    snapshot=snapshot,
                )
            )
        return drafts
