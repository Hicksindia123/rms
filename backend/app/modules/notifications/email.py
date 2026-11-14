"""Email channel for notifications (prompt P4-03 item 4).

* SMTP settings come from the backend environment only (`SMTP_*`, CLAUDE.md rule i), never from
  the database. Without `SMTP_HOST` and `SMTP_FROM` the channel is disabled: email deliveries are
  recorded as SKIPPED / SMTP_NOT_CONFIGURED (never silently dropped) and the UI says so.
* Templates are plain text with `{placeholder}` fields. Unknown placeholders are left as written
  (so a template typo is visible in the preview, not an error at send time).
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any

from app.core.config import Settings

# Placeholders always available to templates (docs/NOTIFICATIONS.md).
PLACEHOLDERS: tuple[str, ...] = (
    "app_name",
    "recipient_name",
    "title",
    "body",
    "event_label",
    "event_type",
    "priority",
    "link",
    "gs_no",
    "created_at",
)

SAMPLE_CONTEXT: dict[str, str] = {
    "app_name": "RMS",
    "recipient_name": "Sample User",
    "title": "GS-2026-00042: sample notification title",
    "body": "Sample notification body text.",
    "event_label": "Sample event",
    "event_type": "SAMPLE_EVENT",
    "priority": "NORMAL",
    "link": "http://localhost:5173/#/gs/00000000-0000-0000-0000-000000000000",
    "gs_no": "GS-2026-00042",
    "created_at": "06-11-2026 10:30",
}


class _KeepMissing(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render(template: str, context: dict[str, Any]) -> str:
    """Fill `{placeholder}` fields; unknown ones stay as written. Braces can be doubled ({{ }})."""
    safe = _KeepMissing({k: "" if v is None else str(v) for k, v in context.items()})
    try:
        return template.format_map(safe)
    except (ValueError, IndexError, AttributeError):
        # A stray single brace or attribute access ({x.y}) in an admin template: show it raw
        # rather than failing the delivery.
        return template


def entity_path(entity_type: str | None, entity_id: Any, gs_id: Any) -> str:
    """Hash-route deep link of the web app for an event's entity (mirrors the bell's routing)."""
    if entity_type == "custody_transfer" and entity_id:
        return f"/#/custody/transfers/{entity_id}"
    if entity_type in ("container_audit_day",):
        return "/#/container-audit"
    if entity_type == "goods_slip" and entity_id:
        return f"/#/gs/{entity_id}"
    if gs_id:
        return f"/#/gs/{gs_id}"
    return "/#/notifications"


@dataclass(frozen=True)
class EmailStatus:
    enabled: bool
    host: str | None
    port: int
    sender: str | None
    security: str  # STARTTLS | SSL | NONE
    reason: str | None


def email_status(settings: Settings) -> EmailStatus:
    enabled = bool(settings.smtp_host and settings.smtp_from)
    security = "SSL" if settings.smtp_ssl else ("STARTTLS" if settings.smtp_use_tls else "NONE")
    return EmailStatus(
        enabled=enabled,
        host=settings.smtp_host,
        port=settings.smtp_port,
        sender=settings.smtp_from,
        security=security,
        reason=None if enabled else "SMTP_HOST and SMTP_FROM are not both set in backend/.env",
    )


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    body: str
    # Phase 9 (AMD-20): party emails may copy configured addresses (party_email.delivery.cc).
    cc: tuple[str, ...] = ()


def build_message(settings: Settings, mail: OutgoingEmail) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from or ""
    msg["To"] = mail.to
    if mail.cc:
        msg["Cc"] = ", ".join(mail.cc)
    # Header injection: subjects are single-line.
    msg["Subject"] = " ".join(mail.subject.splitlines()).strip()[:300]
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="rms.local")
    msg.set_content(mail.body)
    return msg


class SmtpSender:
    """One SMTP connection per batch. Raises `smtplib.SMTPException` / `OSError` on failure."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._conn: smtplib.SMTP | None = None

    def __enter__(self) -> SmtpSender:
        s = self._settings
        host = s.smtp_host or ""
        if s.smtp_ssl:
            self._conn = smtplib.SMTP_SSL(
                host,
                s.smtp_port,
                timeout=s.smtp_timeout_seconds,
                context=ssl.create_default_context(),
            )
        else:
            self._conn = smtplib.SMTP(host, s.smtp_port, timeout=s.smtp_timeout_seconds)
            if s.smtp_use_tls:
                self._conn.starttls(context=ssl.create_default_context())
        if s.smtp_user and s.smtp_password:
            self._conn.login(s.smtp_user, s.smtp_password.get_secret_value())
        return self

    def send(self, mail: OutgoingEmail) -> None:
        if self._conn is None:
            raise RuntimeError("SmtpSender used outside its context manager")
        self._conn.send_message(build_message(self._settings, mail))

    def __exit__(self, *exc: object) -> None:
        if self._conn is not None:
            try:
                self._conn.quit()
            except (smtplib.SMTPException, OSError):
                self._conn.close()
            self._conn = None
