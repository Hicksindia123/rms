"""Party email built from the Accounts values (change plan 2026-11-12 Phase 9; AMD-20, BR-38,
DD r79, DEC-25, DEC-48; G-15, G-16, G-18).

* Source: the CURRENT "Replacement Slip - A/c Actions" after Accounts completed it (AMD-18):
  CN No. / Date / Value and Challan No. / Date per action line, plus the Dispatch Slip's DEC-26
  tracking data once it is dispatched (AMD-19). The structured `snapshot` is built here (G-18).
* Text: the `party_email.template` setting (subject, body and one template per CN / challan /
  dispatch line; rule e). A body line whose placeholders are all empty is left out.
* Send (Accounts, S6_NOTIFY PERFORM): preview -> send. The email is committed QUEUED (idempotent on
  `Idempotency-Key`, G-16), then delivered right after the commit; the worker retries what is still
  QUEUED with backoff and marks it FAILED after `notification_max_attempts`. Resend repeats a logged
  email as a new email. Every email is logged in `party_emails` (never deleted).
* A SENT email records the BR-38 PRIOR_INFO_SENT notification (delivery_mode EMAIL_SENT), which the
  closure checklist (G-15) needs on this flow.
* Auto-send: `party_email.delivery.auto_send` is OFF until an admin enables it (AMD-20). When
  on, the Accounts completion / dispatch command queues the email in its own transaction (DEC-48).
* SMTP comes from the backend env only (rule i). Without it a manual send is refused and an
  auto-send is logged SKIPPED / SMTP_NOT_CONFIGURED: never silently dropped.

The DB trigger `party_emails_guard` repeats the source / frozen-content / final-status rules.
"""

from __future__ import annotations

import re
import smtplib
import string
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol
from uuid import UUID

import structlog
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import UnitOfWork
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.idempotency import IdempotencyKey, IdempotentResult, run_idempotent
from app.core.permissions import EffectivePermissions, assert_step_actor, step_codes_for
from app.core.security import CurrentUser
from app.modules.closure import service as closure_service
from app.modules.config.settings.schemas import SystemSettingUpdate
from app.modules.config.settings.service import SystemSettingsService
from app.modules.goods_slips import service as gs_service
from app.modules.notifications.email import OutgoingEmail, SmtpSender, email_status
from app.modules.party_notifications import repository as repo
from app.modules.party_notifications.schemas import (
    PartyEmailDelivery,
    PartyEmailOut,
    PartyEmailPreviewOut,
    PartyEmailSendIn,
    PartyEmailSettingsIn,
    PartyEmailSettingsOut,
    PartyEmailStateOut,
    PartyEmailTemplate,
)

log = structlog.get_logger("rms.party_email")

NOTIFY_STEP = "S6_NOTIFY"
CLOSE_STEP = "S6_CLOSE"
FORM_CODE = "S6_PARTY_NOTIFY"
STATUS_SET = "PARTY_NOTIFICATION_STATUS"  # DD r79
STATUS_CODE = "PRIOR_INFO_SENT"
TEMPLATE_SETTING = "party_email.template"
DELIVERY_SETTING = "party_email.delivery"
AUTO_SEND_MODES: tuple[str, ...] = ("OFF", "ON_AC_COMPLETION", "ON_DISPATCH")
FINAL_GS_STATUSES = frozenset({"CLOSED", "CANCELLED"})
EMAIL_BATCH = 20
DEFAULT_MAX_ATTEMPTS = 5

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_FORMATTER = string.Formatter()

# DEC-48: placeholders each template part may use (an unknown one is rejected on save).
PLACEHOLDERS: dict[str, tuple[str, ...]] = {
    "subject": (
        "party_name",
        "party_code",
        "gs_no",
        "ac_slip_no",
        "cn_total_value",
    ),
    "body": (
        "party_name",
        "party_code",
        "gs_no",
        "ac_slip_no",
        "cn_lines",
        "cn_total_value",
        "challan_lines",
        "dispatch_details",
    ),
    "cn_line": (
        "line_no",
        "product_code",
        "product_name",
        "action_label",
        "qty",
        "cn_no",
        "cn_date",
        "cn_value",
    ),
    "challan_line": (
        "line_no",
        "product_code",
        "product_name",
        "action_label",
        "qty",
        "challan_no",
        "challan_date",
    ),
    "dispatch_line": (
        "dispatch_slip_no",
        "dispatch_date",
        "transporter",
        "docket_no",
        "vehicle_no",
        "total_qty",
    ),
}

# Admin preview only (never sent): shows every placeholder filled.
SAMPLE_SNAPSHOT: dict[str, Any] = {
    "gs_no": "GS/2026-27/00042",
    "party_name": "Sample Distributor",
    "party_code": "PTY-0001",
    "ac_slip_no": "RSA/2026-27/00007 v1",
    "cn_lines": [
        {
            "line_no": 1,
            "product_code": "ITM-0001",
            "product_name": "Sample product",
            "action_label": "Issue CN",
            "qty": 2,
            "cn_no": "CN-1234",
            "cn_date": "2026-11-14",
            "cn_value": "1250.50",
        }
    ],
    "challan_lines": [
        {
            "line_no": 1,
            "product_code": "ITM-0001",
            "product_name": "Sample product",
            "action_label": "Send New",
            "qty": 3,
            "challan_no": "CH-5678",
            "challan_date": "2026-11-14",
        }
    ],
    "cn_total_value": "1250.50",
    "dispatch": {
        "slip_no": "DS/2026-27/00003",
        "status": "DISPATCHED",
        "dispatch_date": "2026-11-15",
        "transporter": "Sample Courier",
        "docket_no": "DKT-998877",
        "vehicle_no": None,
        "total_qty": 3,
    },
}


class MailSender(Protocol):
    def send(self, mail: OutgoingEmail) -> None: ...


SenderFactory = Callable[[Settings], AbstractContextManager[MailSender]]


class _Blank(dict[str, str]):
    """format_map mapping: an unknown placeholder renders as empty text."""

    def __missing__(self, key: str) -> str:
        return ""


# --- pure helpers (unit-tested) -----------------------------------------------------------------


def valid_email(value: str) -> bool:
    return bool(EMAIL_RE.fullmatch(value.strip()))


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value else None


def build_snapshot(
    *,
    gs_no: str,
    party: Mapping[str, Any],
    slip: Mapping[str, Any],
    lines: list[dict[str, Any]],
    dispatch: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """AMD-20 / DD r79: the Accounts values the email is built from, JSON-safe (G-18)."""
    cn_lines = [ln for ln in lines if ln["cn_no"] is not None]
    challan_lines = [ln for ln in lines if ln["challan_no"] is not None]
    total = sum((Decimal(ln["cn_value"]) for ln in cn_lines), Decimal("0"))

    def base(ln: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "line_no": ln["line_no"],
            "product_code": ln["product_code"],
            "product_name": ln["product_name"],
            "action_code": ln["action_code"],
            "action_label": ln["action_label"],
            "qty": ln["qty"],
        }

    return {
        "gs_no": gs_no,
        "party_name": party.get("party_name"),
        "party_code": party.get("party_code"),
        "ac_action_slip_id": str(slip["id"]),
        "ac_slip_no": f"{slip['slip_no']} v{slip['version_no']}",
        "cn_lines": [
            base(ln)
            | {
                "cn_no": ln["cn_no"],
                "cn_date": _iso(ln["cn_date"]),
                "cn_value": str(ln["cn_value"]),
            }
            for ln in cn_lines
        ],
        "challan_lines": [
            base(ln) | {"challan_no": ln["challan_no"], "challan_date": _iso(ln["challan_date"])}
            for ln in challan_lines
        ],
        "cn_total_value": str(total) if cn_lines else None,
        # Tracking data only once the goods actually left (DEC-26).
        "dispatch": (
            {
                "slip_no": dispatch["slip_no"],
                "status": dispatch["status"],
                "dispatch_date": _iso(dispatch["dispatch_date"]),
                "transporter": dispatch["transporter"],
                "docket_no": dispatch["docket_no"],
                "vehicle_no": dispatch["vehicle_no"],
                "total_qty": dispatch["total_qty"],
            }
            if dispatch and dispatch["status"] == "DISPATCHED"
            else None
        ),
    }


def _fields(template: str) -> list[str]:
    """Placeholder names of a template; ValueError on a malformed one (stray brace)."""
    return [name for _, name, _, _ in _FORMATTER.parse(template) if name is not None]


def validate_template(template: PartyEmailTemplate) -> None:
    """DEC-48: every part parses and only uses its own placeholders (positional ones forbidden)."""
    errors: dict[str, list[str]] = {}
    for part, allowed in PLACEHOLDERS.items():
        text_ = str(getattr(template, part))
        try:
            names = _fields(text_)
        except ValueError as exc:
            errors[part] = [f"Not a valid template: {exc}"]
            continue
        unknown = sorted({n for n in names if n not in allowed})
        if unknown:
            errors[part] = [
                "Unknown placeholder(s): "
                + ", ".join("{" + n + "}" for n in unknown)
                + ". Allowed: "
                + ", ".join("{" + n + "}" for n in allowed)
            ]
    if errors:
        raise ValidationFailed(
            "The party email template has errors", code="TEMPLATE_INVALID", details=errors
        )


def _fmt_date(iso: str | None, fmt: str) -> str:
    return date.fromisoformat(iso).strftime(fmt) if iso else ""


def _fmt_money(value: str | None) -> str:
    if value is None:
        return ""
    try:
        return f"{Decimal(value):,.2f}"
    except InvalidOperation:
        return value


def _fill(template: str, values: Mapping[str, Any]) -> str:
    return template.format_map(_Blank({k: "" if v is None else str(v) for k, v in values.items()}))


def _fill_lines(template: str, values: Mapping[str, Any]) -> str:
    """Fill a multi-line template; a line whose placeholders are all empty is left out."""
    filled = _Blank({k: "" if v is None else str(v) for k, v in values.items()})
    out: list[str] = []
    for line in template.splitlines():
        names = _fields(line)
        if names and all(not filled[n] for n in names):
            continue
        out.append(line.format_map(filled).rstrip())
    # A dropped section must not leave a run of blank lines behind.
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def render_email(
    template: PartyEmailTemplate, snapshot: Mapping[str, Any], date_fmt: str
) -> tuple[str, str]:
    """Subject and body from the configured template (rule e). Raises TEMPLATE_INVALID."""
    try:
        cn_lines = "".join(
            "\n"
            + _fill(
                template.cn_line,
                ln
                | {
                    "cn_date": _fmt_date(ln.get("cn_date"), date_fmt),
                    "cn_value": _fmt_money(ln.get("cn_value")),
                },
            )
            for ln in snapshot.get("cn_lines") or []
        )
        challan_lines = "".join(
            "\n"
            + _fill(
                template.challan_line,
                ln | {"challan_date": _fmt_date(ln.get("challan_date"), date_fmt)},
            )
            for ln in snapshot.get("challan_lines") or []
        )
        disp = snapshot.get("dispatch")
        dispatch = (
            "\n"
            + _fill(
                template.dispatch_line,
                {
                    "dispatch_slip_no": disp.get("slip_no"),
                    "dispatch_date": _fmt_date(disp.get("dispatch_date"), date_fmt),
                    "transporter": disp.get("transporter"),
                    "docket_no": disp.get("docket_no"),
                    "vehicle_no": disp.get("vehicle_no"),
                    "total_qty": disp.get("total_qty"),
                },
            )
            if disp
            else ""
        )
        values = {
            "party_name": snapshot.get("party_name"),
            "party_code": snapshot.get("party_code"),
            "gs_no": snapshot.get("gs_no"),
            "ac_slip_no": snapshot.get("ac_slip_no"),
            "cn_lines": cn_lines,
            "cn_total_value": _fmt_money(snapshot.get("cn_total_value")),
            "challan_lines": challan_lines,
            "dispatch_details": dispatch,
        }
        subject = " ".join(_fill(template.subject, values).split())
        body = _fill_lines(template.body, values)
    except (ValueError, IndexError, AttributeError, KeyError) as exc:
        raise Conflict(
            f"The setting {TEMPLATE_SETTING} is not a valid template: {exc}",
            code="TEMPLATE_INVALID",
        ) from exc
    return subject, body


def _backoff_seconds(attempt: int) -> int:
    """1, 2, 4, 8 … minutes, capped at one hour (same as P4-03 email)."""
    return int(min(3600, 60 * 2 ** max(0, attempt - 1)))


# --- configuration --------------------------------------------------------------------------------


def _date_fmt(session: Session) -> str:
    raw = str(repo.get_setting(session, "date_format") or "DD-MM-YYYY")
    return raw.replace("YYYY", "%Y").replace("MM", "%m").replace("DD", "%d")


def load_template(session: Session) -> PartyEmailTemplate:
    raw = repo.get_setting(session, TEMPLATE_SETTING)
    try:
        return PartyEmailTemplate.model_validate(raw)
    except ValidationError as exc:
        log.error("party_email_template_invalid", error=str(exc))
        raise Conflict(
            f"The setting {TEMPLATE_SETTING} is missing or invalid",
            code="TEMPLATE_INVALID",
            details={"key": TEMPLATE_SETTING},
        ) from exc


def load_delivery(session: Session) -> PartyEmailDelivery:
    """Invalid configuration means OFF (AMD-20: no auto-send unless clearly enabled); logged."""
    raw = repo.get_setting(session, DELIVERY_SETTING)
    try:
        return PartyEmailDelivery.model_validate(raw if raw is not None else {})
    except ValidationError as exc:
        log.error("party_email_delivery_setting_invalid", error=str(exc), value=raw)
        return PartyEmailDelivery()


def _max_attempts(session: Session) -> int:
    value = repo.get_setting(session, "notification_max_attempts")
    try:
        return max(1, int(value)) if value is not None else DEFAULT_MAX_ATTEMPTS
    except (TypeError, ValueError):
        log.warning("invalid_setting", key="notification_max_attempts", value=value)
        return DEFAULT_MAX_ATTEMPTS


# --- shared with the manual record path (service.py) ---------------------------------------------


def after_notification(session: Session, gs: Mapping[str, Any], by: UUID | None) -> None:
    """Once the closure checklist's PRIOR_NOTIFICATION passes: S6_NOTIFY done, S6_CLOSE opened
    (WF r11). The status automation runs first (§6.5)."""
    closure_service.sync_status(session, gs["id"], by)
    items = {i["code"]: i for i in closure_service.evaluate(session, gs["id"])}
    if items["PRIOR_NOTIFICATION"]["passed"]:
        gs_service.complete_step_tasks(session, gs["id"], NOTIFY_STEP)
        if not gs_service.has_open_step_task(session, gs["id"], CLOSE_STEP):
            gs_service.open_step_tasks(session, dict(gs), CLOSE_STEP)


def ac_context(
    session: Session, gs: Mapping[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    """(current slip, snapshot, blocker). The snapshot exists only when the email can be built:
    CURRENT A/c Actions slip completed by Accounts and the GS not closed (AMD-20)."""
    slip = repo.current_ac_slip(session, gs["id"])
    if gs["status"] in FINAL_GS_STATUSES:
        return slip, None, f"The goods slip is {gs['status']}."
    if slip is None:
        return None, None, "The Replacement Manager is revising the A/c Actions slip."
    if not slip["completed"]:
        return slip, None, "Accounts has not completed the CN / Challan entry of this slip yet."
    party = repo.party_contact(session, gs["id"]) or {}
    snapshot = build_snapshot(
        gs_no=str(gs["gs_no"]),
        party=party,
        slip=slip,
        lines=repo.ac_value_lines(session, slip["id"]),
        dispatch=repo.dispatch_slip(session, slip["id"]),
    )
    return slip, snapshot, None


def ac_draft_message(session: Session, snapshot: Mapping[str, Any]) -> str:
    """The email body, reused as the manual-record message on this flow (Conflict if invalid)."""
    return render_email(load_template(session), snapshot, _date_fmt(session))[1]


def _email_out(row: Mapping[str, Any]) -> PartyEmailOut:
    return PartyEmailOut(
        **{k: row[k] for k in PartyEmailOut.model_fields if k in row},
    )


def _clean_cc(values: list[str]) -> list[str]:
    cc: list[str] = []
    for raw in values:
        addr = raw.strip()
        if addr and addr.lower() not in {c.lower() for c in cc}:
            cc.append(addr)
    bad = [c for c in cc if not valid_email(c)]
    if bad:
        raise ValidationFailed(
            "Enter valid e-mail addresses to copy",
            code="FORM_VALIDATION_FAILED",
            details={"cc": [f"Not a valid e-mail address: {b}" for b in bad]},
        )
    return cc


# --- delivery (inline after commit, and the worker) -----------------------------------------------


def deliver(
    uow: UnitOfWork,
    email_id: UUID,
    *,
    settings: Settings | None = None,
    sender_factory: SenderFactory | None = None,
) -> str | None:
    """Try to send one QUEUED party email. Returns its new status (None: not QUEUED / locked).

    One transaction: on success the email is SENT and the PRIOR_INFO_SENT notification is
    recorded (BR-38); an SMTP failure is retried with backoff, then FAILED (never dropped)."""
    settings = settings or get_settings()
    sender_factory = sender_factory or SmtpSender
    smtp = email_status(settings)
    with uow.transaction() as session:
        row = repo.lock_queued_email(session, email_id)
        if row is None:
            return None
        if not smtp.enabled:
            repo.mark_email_skipped(session, email_id, "SMTP_NOT_CONFIGURED")
            log.warning("party_email_skipped", email_id=str(email_id), reason="SMTP_NOT_CONFIGURED")
            return "SKIPPED"
        gs = gs_service.lock_goods_slip(session, row["gs_id"])
        if gs["status"] in FINAL_GS_STATUSES:
            repo.mark_email_attempt_failed(
                session,
                email_id,
                error=f"The goods slip is {gs['status']}; the email was not sent",
                final=True,
                backoff_seconds=0,
            )
            log.warning("party_email_gs_final", email_id=str(email_id), gs_status=gs["status"])
            return "FAILED"
        mail = OutgoingEmail(
            to=str(row["email_to"]),
            subject=str(row["subject"]),
            body=str(row["body"]),
            cc=tuple(row["cc"] or ()),
        )
        try:
            with sender_factory(settings) as sender:
                sender.send(mail)
        except (smtplib.SMTPException, OSError) as exc:
            attempts = int(row["attempts"]) + 1
            final = attempts >= _max_attempts(session)
            error = str(exc) or exc.__class__.__name__
            repo.mark_email_attempt_failed(
                session,
                email_id,
                error=error,
                final=final,
                backoff_seconds=_backoff_seconds(attempts),
            )
            log.warning(
                "party_email_send_failed",
                email_id=str(email_id),
                attempts=attempts,
                final=final,
                error=error,
            )
            return "FAILED" if final else "QUEUED"
        repo.mark_email_sent(session, email_id)
        notification_id = repo.insert_notification(
            session,
            gs_id=row["gs_id"],
            credit_note_id=None,
            status_label=repo.option_label(session, STATUS_SET, STATUS_CODE),
            channel_code="EMAIL",
            recipient=str(row["email_to"]),
            message=f"{row['subject']}\n\n{row['body']}",
            snapshot=dict(row["snapshot"]),
            proof_attachment_id=None,
            form_version_id=repo.published_form_version_id(session, FORM_CODE),
            by=row["requested_by"],
            delivery_mode="EMAIL_SENT",
            party_email_id=email_id,
        )
        after_notification(session, gs, row["requested_by"])
        log.info(
            "party_email_sent",
            email_id=str(email_id),
            gs_id=str(row["gs_id"]),
            notification_id=str(notification_id),
        )
        return "SENT"


def deliver_due(
    uow: UnitOfWork,
    *,
    settings: Settings | None = None,
    sender_factory: SenderFactory | None = None,
    now: datetime | None = None,
) -> int:
    """Worker job `party_email`: deliver QUEUED party emails whose retry time has come."""
    with uow.transaction() as session:
        ids = repo.due_email_ids(session, now=now or datetime.now(UTC), limit=EMAIL_BATCH)
    sent = 0
    for email_id in ids:
        if deliver(uow, email_id, settings=settings, sender_factory=sender_factory) == "SENT":
            sent += 1
    return sent


# --- auto-send hook (called by ac_entry inside its own transaction) -------------------------------


def queue_auto(
    session: Session,
    gs_id: UUID,
    *,
    stage: Literal["AC_COMPLETED", "DISPATCHED"],
    has_dispatch_slip: bool,
    by: UUID,
) -> UUID | None:
    """AMD-20: queue the party email when `party_email.delivery.auto_send` asks for this stage.

    OFF (default): nothing. ON_AC_COMPLETION: at Accounts completion. ON_DISPATCH: when the
    Dispatch Slip is dispatched, or at completion when nothing ships. A missing address, an invalid
    template or missing SMTP is logged as a SKIPPED email (Accounts then sends manually)."""
    delivery = load_delivery(session)
    mode = delivery.auto_send
    wanted = (mode == "ON_AC_COMPLETION" and stage == "AC_COMPLETED") or (
        mode == "ON_DISPATCH"
        and (stage == "DISPATCHED" or (stage == "AC_COMPLETED" and not has_dispatch_slip))
    )
    if not wanted:
        return None
    gs = gs_service.lock_goods_slip(session, gs_id)
    slip, snapshot, blocker = ac_context(session, gs)
    if slip is None or snapshot is None:
        # The caller just completed / dispatched this slip, so this means inconsistent state.
        log.error("party_email_auto_not_ready", gs_id=str(gs_id), blocker=blocker)
        return None
    party = repo.party_contact(session, gs_id) or {}
    email_to = (party.get("email") or "").strip() or None
    template_raw = repo.get_setting(session, TEMPLATE_SETTING)
    subject = body = ""
    skip: str | None = None
    try:
        subject, body = render_email(load_template(session), snapshot, _date_fmt(session))
    except Conflict as exc:
        log.error("party_email_auto_template_invalid", gs_id=str(gs_id), error=exc.message)
        skip = "TEMPLATE_INVALID"
    if skip is None and (email_to is None or not valid_email(email_to)):
        skip = "NO_EMAIL_ADDRESS"
    if skip is None and not email_status(get_settings()).enabled:
        skip = "SMTP_NOT_CONFIGURED"
    email_id = repo.insert_party_email(
        session,
        gs_id=gs_id,
        ac_slip_id=slip["id"],
        trigger_code="AUTO",
        resend_of_id=None,
        email_to=email_to,
        cc=list(delivery.cc),
        subject=subject,
        body=body,
        snapshot=snapshot,
        template_snapshot=template_raw if isinstance(template_raw, dict) else {},
        status="SKIPPED" if skip else "QUEUED",
        skip_reason=skip,
        by=by,
    )
    log.info(
        "party_email_auto_queued" if skip is None else "party_email_auto_skipped",
        gs_id=str(gs_id),
        email_id=str(email_id),
        stage=stage,
        mode=mode,
        skip_reason=skip,
    )
    return email_id


# --- service ---------------------------------------------------------------------------------


class PartyEmailService:
    def __init__(
        self,
        uow: UnitOfWork,
        *,
        settings: Settings | None = None,
        sender_factory: SenderFactory | None = None,
    ) -> None:
        self._uow = uow
        self._settings = settings
        self._sender_factory = sender_factory

    def _smtp(self) -> Any:
        return email_status(self._settings or get_settings())

    # ---------------------------------------------------------------- read --------------------
    def state(
        self,
        session: Session,
        user: CurrentUser,
        gs: Mapping[str, Any],
        perms: EffectivePermissions,
    ) -> PartyEmailStateOut | None:
        """The email panel (None when the GS is not on the A/c Actions flow)."""
        if not repo.has_ac_slip(session, gs["id"]):
            return None
        smtp = self._smtp()
        delivery = load_delivery(session)
        _, snapshot, blocker = ac_context(session, gs)
        subject = body = template_error = None
        if snapshot is not None:
            try:
                subject, body = render_email(load_template(session), snapshot, _date_fmt(session))
            except Conflict as exc:
                log.error("party_email_template_invalid", gs_id=str(gs["id"]), error=exc.message)
                template_error = exc.message
        party = repo.party_contact(session, gs["id"]) or {}
        can_act = perms.allows("credit_notes", "create") and (
            NOTIFY_STEP in step_codes_for(session, user, "PERFORM")
        )
        return PartyEmailStateOut(
            ready=snapshot is not None,
            blocker=blocker,
            smtp_enabled=smtp.enabled,
            smtp_reason=smtp.reason,
            auto_send=delivery.auto_send,
            can_send=can_act and snapshot is not None and smtp.enabled and template_error is None,
            to=party.get("email"),
            cc=list(delivery.cc),
            subject=subject,
            body=body,
            template_error=template_error,
            snapshot=snapshot,
            emails=[_email_out(r) for r in repo.list_party_emails(session, gs["id"])],
        )

    # ---------------------------------------------------------------- commands ----------------
    def send(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: PartyEmailSendIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        to = payload.to.strip()
        if not valid_email(to):
            raise ValidationFailed(
                "Enter a valid e-mail address",
                code="FORM_VALIDATION_FAILED",
                details={"to": ["Not a valid e-mail address"]},
            )
        cc = _clean_cc(payload.cc)
        smtp = self._smtp()
        with self._uow.transaction(user.id) as session:

            def command() -> tuple[int, Any]:
                gs = gs_service.lock_goods_slip(session, gs_id)
                gs_service.get_visible_goods_slip(session, user, perms, gs_id)
                assert_step_actor(session, user, NOTIFY_STEP, "PERFORM")
                if not smtp.enabled:
                    raise Conflict(
                        "E-mail is not configured on the server; send the message yourself and "
                        "record it as a manual notification",
                        code="EMAIL_NOT_CONFIGURED",
                        details={"reason": smtp.reason},
                    )
                slip, snapshot, blocker = ac_context(session, gs)
                if slip is None or snapshot is None:
                    raise Conflict(
                        f"AMD-20: the party email is built from the completed Accounts entry. "
                        f"{blocker}",
                        code="PARTY_EMAIL_NOT_READY",
                        details={"status": gs["status"]},
                    )
                template = load_template(session)
                subject, body = render_email(template, snapshot, _date_fmt(session))
                subject = " ".join((payload.subject or "").split()) or subject
                body = (payload.body or "").strip() or body
                email_id = repo.insert_party_email(
                    session,
                    gs_id=gs_id,
                    ac_slip_id=slip["id"],
                    trigger_code="MANUAL",
                    resend_of_id=None,
                    email_to=to,
                    cc=cc,
                    subject=subject,
                    body=body,
                    snapshot=snapshot,
                    template_snapshot=template.model_dump(),
                    status="QUEUED",
                    skip_reason=None,
                    by=user.id,
                )
                log.info("party_email_queued", gs_id=str(gs_id), email_id=str(email_id))
                return 201, {"id": str(email_id)}

            result = run_idempotent(session, idem, user.id, command)
        return self._deliver_and_report(user, result)

    def resend(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        email_id: UUID,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        smtp = self._smtp()
        with self._uow.transaction(user.id) as session:

            def command() -> tuple[int, Any]:
                gs = gs_service.lock_goods_slip(session, gs_id)
                gs_service.get_visible_goods_slip(session, user, perms, gs_id)
                assert_step_actor(session, user, NOTIFY_STEP, "PERFORM")
                source = repo.get_party_email(session, email_id)
                if source is None or source["gs_id"] != gs_id:
                    raise NotFound("Party email not found", code="PARTY_EMAIL_NOT_FOUND")
                if source["status"] == "QUEUED":
                    raise Conflict(
                        "This email is still being sent; wait for it to finish",
                        code="PARTY_EMAIL_IN_PROGRESS",
                    )
                if not source["email_to"] or not source["body"].strip():
                    raise Conflict(
                        "This email has no recipient or text; send a new email instead",
                        code="PARTY_EMAIL_NOT_RESENDABLE",
                    )
                if not smtp.enabled:
                    raise Conflict(
                        "E-mail is not configured on the server",
                        code="EMAIL_NOT_CONFIGURED",
                        details={"reason": smtp.reason},
                    )
                slip, snapshot, blocker = ac_context(session, gs)
                if slip is None or snapshot is None or slip["id"] != source["ac_action_slip_id"]:
                    raise Conflict(
                        f"AMD-20: the email can only be re-sent for the completed Accounts entry "
                        f"of the current slip. {blocker or ''}".strip(),
                        code="PARTY_EMAIL_NOT_READY",
                    )
                new_id = repo.insert_party_email(
                    session,
                    gs_id=gs_id,
                    ac_slip_id=slip["id"],
                    trigger_code="RESEND",
                    resend_of_id=email_id,
                    email_to=source["email_to"],
                    cc=list(source["cc"] or []),
                    subject=source["subject"],
                    body=source["body"],
                    snapshot=dict(source["snapshot"]),
                    template_snapshot=dict(source["template_snapshot"]),
                    status="QUEUED",
                    skip_reason=None,
                    by=user.id,
                )
                log.info(
                    "party_email_resend_queued",
                    gs_id=str(gs_id),
                    email_id=str(new_id),
                    resend_of=str(email_id),
                )
                return 201, {"id": str(new_id)}

            result = run_idempotent(session, idem, user.id, command)
        return self._deliver_and_report(user, result)

    def _deliver_and_report(self, user: CurrentUser, result: IdempotentResult) -> IdempotentResult:
        """After the commit: try delivery now (a replay finds it already final), then return
        the email as it stands. The worker retries a QUEUED one."""
        email_id = UUID(str(result.body["id"]))
        deliver(
            self._uow,
            email_id,
            settings=self._settings,
            sender_factory=self._sender_factory,
        )
        with self._uow.transaction(user.id) as session:
            row = repo.get_party_email(session, email_id)
        if row is None:  # committed above; only a broken DB would get here
            raise NotFound("Party email not found", code="PARTY_EMAIL_NOT_FOUND")
        return IdempotentResult(
            result.status_code, jsonable_encoder(_email_out(row)), result.replayed
        )

    # ---------------------------------------------------------------- admin settings ----------
    def settings(self, user: CurrentUser) -> PartyEmailSettingsOut:
        with self._uow.transaction(user.id) as session:
            template = load_template(session)
            delivery = load_delivery(session)
        smtp = self._smtp()
        return PartyEmailSettingsOut(
            template=template,
            delivery=delivery,
            auto_send_modes=list(AUTO_SEND_MODES),
            placeholders={k: list(v) for k, v in PLACEHOLDERS.items()},
            smtp_enabled=smtp.enabled,
            smtp_reason=smtp.reason,
        )

    def update_settings(
        self, user: CurrentUser, payload: PartyEmailSettingsIn
    ) -> PartyEmailSettingsOut:
        validate_template(payload.template)
        delivery = payload.delivery.model_copy(update={"cc": _clean_cc(payload.delivery.cc)})
        reason = (payload.reason or "").strip() or "Party email settings updated (AMD-20)"
        # Service-to-service: the settings module owns system_settings and the config history.
        settings_service = SystemSettingsService(self._uow)
        settings_service.update_setting(
            user,
            TEMPLATE_SETTING,
            SystemSettingUpdate(value=payload.template.model_dump(), reason=reason),
        )
        settings_service.update_setting(
            user, DELIVERY_SETTING, SystemSettingUpdate(value=delivery.model_dump(), reason=reason)
        )
        log.info("party_email_settings_updated", auto_send=delivery.auto_send, cc=len(delivery.cc))
        return self.settings(user)

    def preview(self, user: CurrentUser, template: PartyEmailTemplate) -> PartyEmailPreviewOut:
        validate_template(template)
        with self._uow.transaction(user.id) as session:
            fmt = _date_fmt(session)
        subject, body = render_email(template, SAMPLE_SNAPSHOT, fmt)
        return PartyEmailPreviewOut(subject=subject, body=body)
