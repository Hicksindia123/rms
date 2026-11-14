"""Central notification system: event → rule → recipients → channel (prompt P4-03; §8.7, §10).

Publishing (service-to-service, inside the caller's business transaction):

    notifications.publish(session, "EVIDENCE_COMPLETED", title=..., entity_type="goods_slip",
                          entity_id=gs_id, gs_id=gs_id, role_codes=[...])

1. A row is written to the `notification_events` OUTBOX in the caller's transaction: if the business
   change rolls back, so does the event (no phantom notifications).
2. The event is dispatched immediately inside a SAVEPOINT of the same transaction: active
   `notification_rules` resolve the recipients (the publisher's *context* recipients, assignees of
   the GS's open step, roles, users) and the channels. IN_APP rows appear with the business change,
   exactly as before P4-03. If dispatch fails, only the savepoint rolls back; the event stays
   PENDING and the worker retries it (no lost notifications).
3. `notification_deliveries` has one row per (event, user, channel) → exactly once. Email
   deliveries are sent by the worker after commit (`send_due_emails`, `send_digests`).

`context recipients` (user_ids + active holders of role_codes at publish time) reproduce what each
module notified before P4-03; the seeded rules (seed.sql) address them on IN_APP.
"""

from __future__ import annotations

import smtplib
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import UnitOfWork
from app.core.errors import DomainError, ValidationFailed
from app.core.security import CurrentUser
from app.modules.notifications import repository as repo
from app.modules.notifications.email import (
    OutgoingEmail,
    SmtpSender,
    email_status,
    entity_path,
    render,
)
from app.modules.notifications.schemas import (
    EmailStatusOut,
    NotificationListOut,
    NotificationOut,
    PreferenceItemOut,
    PreferencesIn,
    PreferencesOut,
)

log = structlog.get_logger("rms.notifications")

PRIORITY_RANK = {"LOW": 0, "NORMAL": 1, "HIGH": 2}
DEFAULT_MAX_ATTEMPTS = 5
OUTBOX_BATCH = 100
EMAIL_BATCH = 50
ESCALATION_BATCH = 500
DEFAULT_DIGEST_HOUR = 9


# =============================================================================================
# Publishing
# =============================================================================================


def publish(
    session: Session,
    event_type: str,
    *,
    title: str,
    body: str | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    gs_id: UUID | None = None,
    user_ids: Iterable[UUID | None] = (),
    role_codes: Iterable[str] = (),
    priority: str | None = None,
    notification_type: str | None = None,
    data: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> int:
    """Publish a domain event in the caller's transaction. Returns the number of in-app
    notifications created (0 when deduplicated or when dispatch is deferred to the worker).

    `user_ids` / `role_codes` are the event's context recipients (who the business step names).
    `notification_type` is the in-app `type` (defaults to the event code; pre-P4-03 types are kept
    so the bell's deep links keep working).
    """
    etype = repo.get_event_type(session, event_type)
    if etype is None:
        raise ValidationFailed(
            f"Unknown notification event type {event_type}", code="UNKNOWN_EVENT_TYPE"
        )
    if priority is not None and priority not in PRIORITY_RANK:
        raise ValidationFailed(f"Invalid priority {priority}", code="INVALID_PRIORITY")
    roles = sorted({c for c in role_codes if c})
    context = list(
        dict.fromkeys([u for u in user_ids if u] + repo.active_user_ids_with_roles(session, roles))
    )
    payload: dict[str, Any] = {
        "title": title,
        "body": body,
        "notification_type": notification_type or event_type,
        "data": data or {},
    }
    event_id = repo.insert_event(
        session,
        event_type=event_type,
        dedupe_key=dedupe_key,
        entity_type=entity_type,
        entity_id=entity_id,
        gs_id=gs_id,
        payload=payload,
        context_user_ids=context,
        priority=priority or str(etype["default_priority"]),
    )
    if event_id is None:
        log.info("notification_event_deduplicated", event_type=event_type, dedupe_key=dedupe_key)
        return 0
    return _dispatch_inline(session, event_id, event_type)


def _dispatch_inline(session: Session, event_id: UUID, event_type: str) -> int:
    try:
        with session.begin_nested():
            return dispatch_event(session, event_id, skip_locked=False)
    except (SQLAlchemyError, DomainError) as exc:
        # Only the savepoint is rolled back; the outbox row commits with the business change and
        # the worker retries it (process_outbox).
        log.warning(
            "notification_inline_dispatch_failed",
            event_id=str(event_id),
            event_type=event_type,
            error=str(exc),
            exc_info=exc,
        )
        repo.mark_event_retry(
            session,
            event_id,
            error=str(exc),
            max_attempts=_max_attempts(session),
            backoff_seconds=0,
        )
        return 0


# =============================================================================================
# Rule evaluation & fan-out
# =============================================================================================


def plan_recipients(
    session: Session, event: dict[str, Any]
) -> dict[tuple[UUID, str], tuple[list[UUID], str]]:
    """(user, channel) → (matching rule ids, highest priority) for the event's active rules."""
    plan: dict[tuple[UUID, str], tuple[list[UUID], str]] = {}
    context = [UUID(str(u)) for u in event.get("context_user_ids") or []]
    for rule in repo.active_rules_for(session, str(event["event_type"])):
        users: list[UUID] = []
        if rule["include_context_recipients"]:
            users += context
        if rule["include_step_assignees"] and event.get("gs_id"):
            users += repo.open_task_assignee_ids(session, UUID(str(event["gs_id"])))
        users += repo.active_user_ids_with_roles(session, list(rule["recipient_role_codes"] or []))
        users += repo.active_user_ids(
            session, [UUID(str(u)) for u in rule["recipient_user_ids"] or []]
        )
        prio = str(rule["priority"] or event["priority"])
        rule_id = UUID(str(rule["id"]))
        for uid in dict.fromkeys(users):
            for channel in rule["channels"]:
                rules, current = plan.get((uid, channel), ([], "LOW"))
                best = prio if PRIORITY_RANK[prio] > PRIORITY_RANK[current] else current
                plan[(uid, channel)] = ([*rules, rule_id], best)
    return plan


def dispatch_event(
    session: Session, event_id: UUID, *, skip_locked: bool, settings: Settings | None = None
) -> int:
    """Fan one PENDING event out to its deliveries. Returns the in-app notifications created."""
    event = repo.lock_event(session, event_id, skip_locked=skip_locked)
    if event is None or event["status"] != "PENDING":
        return 0
    plan = plan_recipients(session, event)
    done = repo.delivered_pairs(session, event_id)
    smtp_enabled = email_status(settings or get_settings()).enabled
    email_users = sorted({u for (u, ch) in plan if ch == "EMAIL"}, key=str)
    contacts = repo.user_contacts(session, email_users)
    mandatory = bool(event["is_mandatory"])
    opted_out = (
        set() if mandatory else repo.email_opt_outs(session, email_users, str(event["event_type"]))
    )
    payload = dict(event["payload"] or {})
    in_app = 0
    for (uid, channel), (rule_ids, prio) in sorted(
        plan.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])
    ):
        if (uid, channel) in done:
            continue
        if channel == "IN_APP":
            nid = repo.insert_in_app(
                session,
                event_id=event_id,
                user_id=uid,
                type_=str(payload.get("notification_type") or event["event_type"]),
                title=str(payload.get("title") or event["event_label"]),
                body=payload.get("body"),
                entity_type=event["entity_type"],
                entity_id=event["entity_id"],
                priority=prio,
            )
            repo.insert_delivery(
                session,
                event_id=event_id,
                user_id=uid,
                channel="IN_APP",
                rule_ids=rule_ids,
                priority=prio,
                status="SENT",
                notification_id=nid,
            )
            in_app += 1
            continue
        contact = contacts.get(uid) or {}
        address = contact.get("email")
        status, reason = "PENDING", None
        if not smtp_enabled:
            status, reason = "SKIPPED", "SMTP_NOT_CONFIGURED"
        elif not address:
            status, reason = "SKIPPED", "NO_EMAIL_ADDRESS"
        elif uid in opted_out:
            status, reason = "SKIPPED", "OPTED_OUT"
        elif not mandatory and contact.get("email_mode") == "DAILY_DIGEST":
            status = "DIGEST"
        repo.insert_delivery(
            session,
            event_id=event_id,
            user_id=uid,
            channel="EMAIL",
            rule_ids=rule_ids,
            priority=prio,
            status=status,
            skip_reason=reason,
            email_to=address,
        )
    repo.mark_event_dispatched(session, event_id)
    return in_app


def process_outbox(uow: UnitOfWork, *, now: datetime | None = None) -> int:
    """Worker: dispatch PENDING events (deferred or failed inline). One transaction per event."""
    now = now or datetime.now(UTC)
    with uow.transaction() as session:
        ids = repo.due_event_ids(session, now=now, limit=OUTBOX_BATCH)
    dispatched = 0
    for event_id in ids:
        with uow.transaction() as session:
            max_attempts = _max_attempts(session)
            try:
                with session.begin_nested():
                    event = repo.lock_event(session, event_id, skip_locked=True)
                    if event is None or event["status"] != "PENDING":
                        continue
                    dispatch_event(session, event_id, skip_locked=True)
                dispatched += 1
            except (SQLAlchemyError, DomainError) as exc:
                status = repo.mark_event_retry(
                    session,
                    event_id,
                    error=str(exc),
                    max_attempts=max_attempts,
                    backoff_seconds=_backoff_seconds(1),
                )
                log.error(
                    "notification_dispatch_failed",
                    event_id=str(event_id),
                    status=status,
                    error=str(exc),
                    exc_info=exc,
                )
    return dispatched


# =============================================================================================
# Email delivery (worker)
# =============================================================================================


class MailSender(Protocol):
    def send(self, mail: OutgoingEmail) -> None: ...


SenderFactory = Callable[[Settings], AbstractContextManager[MailSender]]


def _template_context(
    session: Session, row: dict[str, Any], settings: Settings, cache: dict[str, Any]
) -> dict[str, Any]:
    if "app_name" not in cache:
        cache["app_name"] = repo.get_setting(session, "app_name") or "RMS"
        cache["tz"] = repo.get_setting(session, "timezone") or settings.tz
    payload = dict(row.get("payload") or {})
    data = {
        k: v for k, v in (payload.get("data") or {}).items() if isinstance(v, str | int | float)
    }
    created = row.get("event_at")
    created_txt = (
        created.astimezone(ZoneInfo(str(cache["tz"]))).strftime("%d-%m-%Y %H:%M")
        if isinstance(created, datetime)
        else ""
    )
    return {
        **data,
        "app_name": cache["app_name"],
        "recipient_name": row.get("recipient_name") or "",
        "title": payload.get("title") or row.get("event_label") or "",
        "body": payload.get("body") or "",
        "event_label": row.get("event_label") or "",
        "event_type": row.get("event_type") or "",
        "priority": row.get("priority") or "",
        "link": settings.app_public_url.rstrip("/")
        + entity_path(row.get("entity_type"), row.get("entity_id"), row.get("gs_id")),
        "gs_no": data.get("gs_no", ""),
        "created_at": created_txt,
    }


def compose_email(
    session: Session, row: dict[str, Any], settings: Settings, cache: dict[str, Any]
) -> OutgoingEmail:
    key = f"tpl:{row['event_type']}"
    if key not in cache:
        cache[key] = repo.published_template(session, str(row["event_type"]))
    template = cache[key]
    ctx = _template_context(session, row, settings, cache)
    if template is None:  # every event has a seeded v1; defensive only
        subject, body = "[{app_name}] {title}", "{title}\n\n{body}\n\n{link}"
    else:
        subject, body = str(template["subject"]), str(template["body"])
    return OutgoingEmail(
        to=str(row["email_to"]), subject=render(subject, ctx), body=render(body, ctx)
    )


def send_due_emails(
    uow: UnitOfWork,
    *,
    settings: Settings | None = None,
    sender_factory: SenderFactory = SmtpSender,
    now: datetime | None = None,
) -> int:
    """Worker: send PENDING email deliveries. Failures are retried with backoff, then FAILED."""
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    status = email_status(settings)
    sent: list[UUID] = []
    with uow.transaction() as session:
        rows = repo.lock_due_emails(session, now=now, limit=EMAIL_BATCH)
        if not rows:
            return 0
        ids = [UUID(str(r["id"])) for r in rows]
        if not status.enabled:
            # SMTP was switched off after these were queued: record it, never drop silently.
            repo.mark_delivery_skipped(session, ids, "SMTP_NOT_CONFIGURED")
            log.warning("notification_email_disabled", skipped=len(ids))
            return 0
        max_attempts = _max_attempts(session)
        cache: dict[str, Any] = {}
        failures: dict[UUID, str] = {}
        try:
            with sender_factory(settings) as sender:
                for row in rows:
                    rid = UUID(str(row["id"]))
                    try:
                        sender.send(compose_email(session, row, settings, cache))
                        sent.append(rid)
                    except (smtplib.SMTPException, OSError) as exc:
                        failures[rid] = str(exc) or exc.__class__.__name__
        except (smtplib.SMTPException, OSError) as exc:
            # Connection / login failure: everything not yet sent is retried.
            for rid in ids:
                if rid not in sent:
                    failures.setdefault(rid, str(exc) or exc.__class__.__name__)
            log.error("notification_smtp_failed", error=str(exc), exc_info=exc)
        if sent:
            repo.mark_delivery_sent(session, sent, digest_key=None)
        for rid, err in failures.items():
            attempts = next(int(r["attempts"]) for r in rows if UUID(str(r["id"])) == rid)
            repo.mark_delivery_retry(
                session,
                [rid],
                error=err,
                max_attempts=max_attempts,
                backoff_seconds=_backoff_seconds(attempts + 1),
            )
            log.warning("notification_email_retry", delivery_id=str(rid), error=err)
    return len(sent)


def send_digests(
    uow: UnitOfWork,
    *,
    settings: Settings | None = None,
    sender_factory: SenderFactory = SmtpSender,
    now: datetime | None = None,
) -> int:
    """Worker (hourly): one daily digest email per DAILY_DIGEST user, after the digest hour."""
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    status = email_status(settings)
    with uow.transaction() as session:
        tz = ZoneInfo(str(repo.get_setting(session, "timezone") or settings.tz))
        hour = _int_setting(session, "notification_digest_hour", DEFAULT_DIGEST_HOUR)
        users = repo.digest_user_ids(session)
    local = now.astimezone(tz)
    if local.hour < hour or not users:
        return 0
    digest_key = f"DIGEST:{local.date().isoformat()}"
    sent_count = 0
    for uid in users:
        with uow.transaction() as session:
            if repo.digest_sent(session, uid, digest_key):
                continue
            items = repo.lock_digest_items(session, uid)
            if not items:
                continue
            ids = [UUID(str(i["id"])) for i in items]
            if not status.enabled:
                repo.mark_delivery_skipped(session, ids, "SMTP_NOT_CONFIGURED")
                log.warning(
                    "notification_digest_email_disabled", user_id=str(uid), skipped=len(ids)
                )
                continue
            address = repo.user_email(session, uid)
            if not address:
                repo.mark_delivery_skipped(session, ids, "NO_EMAIL_ADDRESS")
                continue
            mail = compose_digest(session, items, address, settings, local)
            try:
                with sender_factory(settings) as sender:
                    sender.send(mail)
            except (smtplib.SMTPException, OSError) as exc:
                repo.mark_delivery_retry(
                    session,
                    ids,
                    error=str(exc) or exc.__class__.__name__,
                    max_attempts=_max_attempts(session),
                    backoff_seconds=0,
                )
                log.error(
                    "notification_digest_failed", user_id=str(uid), error=str(exc), exc_info=exc
                )
                continue
            repo.mark_delivery_sent(session, ids, digest_key=digest_key)
            sent_count += 1
    return sent_count


def compose_digest(
    session: Session,
    items: list[dict[str, Any]],
    address: str,
    settings: Settings,
    local_now: datetime,
) -> OutgoingEmail:
    cache: dict[str, Any] = {}
    lines: list[str] = []
    name = ""
    app_name = ""
    for item in items:
        ctx = _template_context(session, item, settings, cache)
        name = name or str(ctx["recipient_name"])
        app_name = str(ctx["app_name"])
        lines.append(f"- {ctx['created_at']}  [{ctx['priority']}] {ctx['title']}")
        if ctx["body"]:
            lines.append(f"  {ctx['body']}")
        lines.append(f"  {ctx['link']}")
    subject = (
        f"[{app_name}] Daily digest {local_now.strftime('%d-%m-%Y')}: {len(items)} notification(s)"
    )
    body = (
        f"Hello {name},\n\nYour notifications since the last digest:\n\n"
        + "\n".join(lines)
        + f"\n\n— {app_name} (daily digest; change it under Notification preferences)"
    )
    return OutgoingEmail(to=address, subject=subject, body=body)


# =============================================================================================
# SLA escalations (DEC-30)
# =============================================================================================


def run_escalations(session: Session, *, now: datetime) -> int:
    """Notify the targets of every active escalation level an OPEN task has reached, once per
    level (unique task x rule), and stamp workflow_tasks.escalated_at. `now` is injectable so tests
    run with frozen time."""
    tz = ZoneInfo(str(repo.get_setting(session, "timezone") or get_settings().tz))
    escalated = 0
    for row in repo.due_escalations(session, now=now, limit=ESCALATION_BATCH):
        task_id = UUID(str(row["task_id"]))
        rule_id = UUID(str(row["rule_id"]))
        key = f"sla:{task_id}:{rule_id}"
        due: datetime = row["due_at"]
        level = int(row["level_no"])
        publish(
            session,
            "SLA_ESCALATION",
            title=f"{row['gs_no']}: {row['step_label']} overdue — escalation level {level}",
            body=(
                f"The task was due {due.astimezone(tz).strftime('%d-%m-%Y %H:%M')} "
                f"and is still open {float(row['after_hours']):g} h after the SLA breach (DEC-30)."
            ),
            entity_type="goods_slip",
            entity_id=UUID(str(row["gs_id"])),
            gs_id=UUID(str(row["gs_id"])),
            user_ids=[UUID(str(row["notify_user_id"]))] if row["notify_user_id"] else [],
            role_codes=[str(row["notify_role_code"])] if row["notify_role_code"] else [],
            data={
                "gs_no": str(row["gs_no"]),
                "step_code": str(row["step_code"]),
                "level": level,
                "task_id": str(task_id),
            },
            dedupe_key=key,
        )
        inserted = repo.insert_task_escalation(
            session,
            task_id=task_id,
            rule_id=rule_id,
            level_no=level,
            due_at=due,
            now=now,
            event_id=repo.event_id_by_dedupe_key(session, key),
        )
        if inserted:
            repo.mark_task_escalated(session, task_id, now)
            escalated += 1
            log.info("sla_escalated", task_id=str(task_id), level=level, gs_no=row["gs_no"])
    return escalated


# =============================================================================================
# Helpers
# =============================================================================================


def _int_setting(session: Session, key: str, default: int) -> int:
    value = repo.get_setting(session, key)
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        log.warning("invalid_setting", key=key, value=value)
        return default


def _max_attempts(session: Session) -> int:
    return max(1, _int_setting(session, "notification_max_attempts", DEFAULT_MAX_ATTEMPTS))


def _backoff_seconds(attempt: int) -> int:
    """1, 2, 4, 8 … minutes, capped at one hour."""
    return int(min(3600, 60 * 2 ** max(0, attempt - 1)))


def active_user_ids_with_roles(session: Session, role_codes: list[str]) -> list[UUID]:
    """Service-to-service: active users holding any of the roles (to merge recipient lists)."""
    return repo.active_user_ids_with_roles(session, role_codes)


def email_status_out(settings: Settings | None = None) -> EmailStatusOut:
    st = email_status(settings or get_settings())
    return EmailStatusOut(
        enabled=st.enabled,
        host=st.host,
        port=st.port,
        sender=st.sender,
        security=st.security,
        reason=st.reason,
    )


# =============================================================================================
# User-facing API (bell, notification centre, preferences)
# =============================================================================================


class NotificationService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def mine(
        self,
        user: CurrentUser,
        *,
        unread_only: bool,
        limit: int,
        offset: int = 0,
        event_type: str | None = None,
        priority: str | None = None,
    ) -> NotificationListOut:
        with self._uow.transaction(user.id) as session:
            rows = repo.list_for_user(
                session,
                user.id,
                unread_only=unread_only,
                limit=limit,
                offset=offset,
                event_type=event_type,
                priority=priority,
            )
            total = repo.count_for_user(
                session,
                user.id,
                unread_only=unread_only,
                event_type=event_type,
                priority=priority,
            )
            unread = repo.unread_count(session, user.id)
        return NotificationListOut(
            items=[NotificationOut(**r) for r in rows], unread_count=unread, total=total
        )

    def mark_read(self, user: CurrentUser, notification_id: UUID | None) -> int:
        with self._uow.transaction(user.id) as session:
            return repo.mark_read(session, user.id, notification_id)

    def preferences(self, user: CurrentUser) -> PreferencesOut:
        with self._uow.transaction(user.id) as session:
            return self._preferences(session, user.id)

    def update_preferences(self, user: CurrentUser, payload: PreferencesIn) -> PreferencesOut:
        with self._uow.transaction(user.id) as session:
            types = {t["code"]: t for t in repo.list_event_types(session)}
            for code, enabled in payload.email.items():
                etype = types.get(code)
                if etype is None:
                    raise ValidationFailed(
                        f"Unknown notification event {code}", code="UNKNOWN_EVENT_TYPE"
                    )
                if etype["is_mandatory"] and not enabled:
                    raise ValidationFailed(
                        f"'{etype['label']}' is mandatory and cannot be switched off",
                        code="MANDATORY_EVENT",
                        details={"event_type": code},
                    )
                repo.upsert_email_preference(session, user.id, code, enabled)
            if payload.email_mode is not None:
                repo.upsert_email_mode(session, user.id, payload.email_mode)
            return self._preferences(session, user.id)

    def _preferences(self, session: Session, user_id: UUID) -> PreferencesOut:
        prefs = repo.user_email_preferences(session, user_id)
        email_rules = {
            str(r["event_type"])
            for r in repo.list_rules(session)
            if r["is_active"] and "EMAIL" in (r["channels"] or [])
        }
        items = [
            PreferenceItemOut(
                event_type=str(t["code"]),
                label=str(t["label"]),
                description=t["description"],
                category=str(t["category"]),
                is_mandatory=bool(t["is_mandatory"]),
                email_enabled=True if t["is_mandatory"] else prefs.get(str(t["code"]), True),
                email_rule_active=str(t["code"]) in email_rules,
            )
            for t in repo.list_event_types(session)
        ]
        return PreferencesOut(
            email_channel=email_status_out(),
            email_address=repo.user_email(session, user_id),
            email_mode="DAILY_DIGEST"
            if repo.user_email_mode(session, user_id) == "DAILY_DIGEST"
            else "IMMEDIATE",
            items=items,
        )
