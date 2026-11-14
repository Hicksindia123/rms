"""Notifications repository: SQL only (prompts P2-03, P4-03). No business rules here."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

_COLUMNS = (
    "n.id, n.type, n.title, n.body, n.entity_type, n.entity_id, n.priority, n.read_at, "
    "n.created_at, e.event_type, e.gs_id"
)


# =============================================================================================
# Recipients
# =============================================================================================


def active_user_ids_with_roles(session: Session, role_codes: list[str]) -> list[UUID]:
    if not role_codes:
        return []
    rows = session.execute(
        text(
            """
            select distinct p.id
              from public.profiles p
              join public.user_roles ur on ur.user_id = p.id
              join public.roles r on r.id = ur.role_id
             where p.is_active and r.code = any(:codes)
            """
        ),
        {"codes": role_codes},
    ).scalars()
    return [UUID(str(r)) for r in rows]


def active_user_ids(session: Session, user_ids: list[UUID]) -> list[UUID]:
    if not user_ids:
        return []
    rows = session.execute(
        text("select id from public.profiles where is_active and id = any(cast(:ids as uuid[]))"),
        {"ids": [str(u) for u in user_ids]},
    ).scalars()
    return [UUID(str(r)) for r in rows]


def open_task_assignee_ids(session: Session, gs_id: UUID) -> list[UUID]:
    """Users assigned to (or holding the role of) an OPEN workflow task of the GS."""
    rows = session.execute(
        text(
            """
            select t.assigned_user_id as id
              from public.workflow_tasks t
              join public.profiles p on p.id = t.assigned_user_id and p.is_active
             where t.gs_id = :gs and t.status = 'OPEN'
            union
            select ur.user_id
              from public.workflow_tasks t
              join public.user_roles ur on ur.role_id = t.assigned_role_id
              join public.profiles p on p.id = ur.user_id and p.is_active
             where t.gs_id = :gs and t.status = 'OPEN' and t.assigned_user_id is null
            """
        ),
        {"gs": gs_id},
    ).scalars()
    return [UUID(str(r)) for r in rows]


def user_contacts(session: Session, user_ids: list[UUID]) -> dict[UUID, dict[str, Any]]:
    if not user_ids:
        return {}
    rows = session.execute(
        text(
            """
            select p.id, p.email::text as email, p.full_name, p.is_active,
                   coalesce(s.email_mode, 'IMMEDIATE') as email_mode
              from public.profiles p
              left join public.notification_user_settings s on s.user_id = p.id
             where p.id = any(cast(:ids as uuid[]))
            """
        ),
        {"ids": [str(u) for u in user_ids]},
    ).mappings()
    return {UUID(str(r["id"])): dict(r) for r in rows}


def email_opt_outs(session: Session, user_ids: list[UUID], event_type: str) -> set[UUID]:
    if not user_ids:
        return set()
    rows = session.execute(
        text(
            """
            select user_id from public.notification_preferences
             where channel = 'EMAIL' and notification_type = :et and not is_enabled
               and user_id = any(cast(:ids as uuid[]))
            """
        ),
        {"et": event_type, "ids": [str(u) for u in user_ids]},
    ).scalars()
    return {UUID(str(r)) for r in rows}


# =============================================================================================
# Settings
# =============================================================================================


def get_setting(session: Session, key: str) -> Any:
    return session.execute(
        text("select value from public.system_settings where key = :k"), {"k": key}
    ).scalar()


# =============================================================================================
# Event catalogue
# =============================================================================================


def list_event_types(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select code, label, description, category, default_priority, is_mandatory,
                   source_ref, sort_order, updated_at
              from public.notification_event_types
             order by sort_order, code
            """
        )
    ).mappings()
    return [dict(r) for r in rows]


_EVENT_TYPE_SQL = (
    "select code, label, description, category, default_priority, is_mandatory, "
    "source_ref, sort_order, updated_at from public.notification_event_types where code = :c"
)


def get_event_type(
    session: Session, code: str, *, for_update: bool = False
) -> dict[str, Any] | None:
    sql = _EVENT_TYPE_SQL + " for update" if for_update else _EVENT_TYPE_SQL
    row = session.execute(text(sql), {"c": code}).mappings().first()
    return dict(row) if row else None


def update_event_type(session: Session, code: str, values: dict[str, Any]) -> None:
    session.execute(
        text(
            """
            update public.notification_event_types
               set label = :label, description = :description,
                   default_priority = :default_priority, is_mandatory = :is_mandatory
             where code = :code
            """
        ),
        {**values, "code": code},
    )


# =============================================================================================
# Outbox
# =============================================================================================


def insert_event(
    session: Session,
    *,
    event_type: str,
    dedupe_key: str | None,
    entity_type: str | None,
    entity_id: UUID | None,
    gs_id: UUID | None,
    payload: dict[str, Any],
    context_user_ids: list[UUID],
    priority: str,
) -> UUID | None:
    """Insert one outbox row. Returns None when `dedupe_key` was already published."""
    row = session.execute(
        text(
            """
            insert into public.notification_events
                   (event_type, dedupe_key, entity_type, entity_id, gs_id, payload,
                    context_user_ids, priority)
            values (:et, :dk, :ent, :eid, :gs, cast(:payload as jsonb),
                    cast(:ctx as uuid[]), :priority)
            on conflict (dedupe_key) do nothing
            returning id
            """
        ),
        {
            "et": event_type,
            "dk": dedupe_key,
            "ent": entity_type,
            "eid": entity_id,
            "gs": gs_id,
            "payload": json.dumps(payload, default=str),
            "ctx": [str(u) for u in context_user_ids],
            "priority": priority,
        },
    ).scalar()
    return UUID(str(row)) if row else None


_LOCK_EVENT_SQL = """
    select e.id, e.event_type, e.entity_type, e.entity_id, e.gs_id, e.payload,
           e.context_user_ids, e.priority, e.status, e.attempts, e.created_at,
           t.label as event_label, t.is_mandatory
      from public.notification_events e
      join public.notification_event_types t on t.code = e.event_type
     where e.id = :id
     for update of e
"""


def lock_event(session: Session, event_id: UUID, *, skip_locked: bool) -> dict[str, Any] | None:
    sql = _LOCK_EVENT_SQL + " skip locked" if skip_locked else _LOCK_EVENT_SQL
    row = session.execute(text(sql), {"id": event_id}).mappings().first()
    return dict(row) if row else None


def due_event_ids(session: Session, *, now: datetime, limit: int) -> list[UUID]:
    rows = session.execute(
        text(
            """
            select id from public.notification_events
             where status = 'PENDING' and next_attempt_at <= :now
             order by next_attempt_at, created_at
             limit :limit
            """
        ),
        {"now": now, "limit": limit},
    ).scalars()
    return [UUID(str(r)) for r in rows]


def mark_event_dispatched(session: Session, event_id: UUID) -> None:
    session.execute(
        text(
            "update public.notification_events set status = 'DISPATCHED', "
            "dispatched_at = now(), last_error = null where id = :id"
        ),
        {"id": event_id},
    )


def mark_event_retry(
    session: Session, event_id: UUID, *, error: str, max_attempts: int, backoff_seconds: int
) -> str:
    """Record a failed dispatch attempt; FAILED once `max_attempts` is reached."""
    return str(
        session.execute(
            text(
                """
                update public.notification_events
                   set attempts = attempts + 1,
                       last_error = left(:err, 2000),
                       status = case when attempts + 1 >= :max then 'FAILED' else 'PENDING' end,
                       next_attempt_at = now() + make_interval(secs => :backoff)
                 where id = :id
                returning status
                """
            ),
            {"id": event_id, "err": error, "max": max_attempts, "backoff": backoff_seconds},
        ).scalar_one()
    )


def active_rules_for(session: Session, event_type: str) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select id, include_context_recipients, include_step_assignees, recipient_role_codes,
                   recipient_user_ids, channels, priority
              from public.notification_rules
             where event_type = :et and is_active
             order by created_at, id
            """
        ),
        {"et": event_type},
    ).mappings()
    return [dict(r) for r in rows]


def insert_in_app(
    session: Session,
    *,
    event_id: UUID,
    user_id: UUID,
    type_: str,
    title: str,
    body: str | None,
    entity_type: str | None,
    entity_id: UUID | None,
    priority: str,
) -> UUID:
    return UUID(
        str(
            session.execute(
                text(
                    """
                    insert into public.notifications (user_id, type, title, body, entity_type,
                                                      entity_id, priority, event_id)
                    values (:uid, :type, :title, :body, :et, :eid, :priority, :ev)
                    returning id
                    """
                ),
                {
                    "uid": user_id,
                    "type": type_,
                    "title": title,
                    "body": body,
                    "et": entity_type,
                    "eid": entity_id,
                    "priority": priority,
                    "ev": event_id,
                },
            ).scalar_one()
        )
    )


def insert_delivery(
    session: Session,
    *,
    event_id: UUID,
    user_id: UUID,
    channel: str,
    rule_ids: list[UUID],
    priority: str,
    status: str,
    skip_reason: str | None = None,
    notification_id: UUID | None = None,
    email_to: str | None = None,
) -> bool:
    res = session.execute(
        text(
            """
            insert into public.notification_deliveries
                   (event_id, user_id, channel, rule_ids, priority, status, skip_reason,
                    notification_id, email_to, sent_at)
            values (:ev, :uid, :ch, cast(:rules as uuid[]), :priority, :status, :skip,
                    :nid, :email, case when :status = 'SENT' then now() end)
            on conflict (event_id, user_id, channel) do nothing
            """
        ),
        {
            "ev": event_id,
            "uid": user_id,
            "ch": channel,
            "rules": [str(r) for r in rule_ids],
            "priority": priority,
            "status": status,
            "skip": skip_reason,
            "nid": notification_id,
            "email": email_to,
        },
    )
    return bool(getattr(res, "rowcount", 0))


def delivered_pairs(session: Session, event_id: UUID) -> set[tuple[UUID, str]]:
    rows = session.execute(
        text("select user_id, channel from public.notification_deliveries where event_id = :ev"),
        {"ev": event_id},
    ).all()
    return {(UUID(str(u)), str(c)) for u, c in rows}


# =============================================================================================
# Email deliveries
# =============================================================================================

_EMAIL_DELIVERY_COLUMNS = """
    d.id, d.event_id, d.user_id, d.priority, d.status, d.attempts, d.email_to,
    e.event_type, e.entity_type, e.entity_id, e.gs_id, e.payload, e.created_at as event_at,
    t.label as event_label, p.full_name as recipient_name
"""


def lock_due_emails(session: Session, *, now: datetime, limit: int) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            f"""
            select {_EMAIL_DELIVERY_COLUMNS}
              from public.notification_deliveries d
              join public.notification_events e on e.id = d.event_id
              join public.notification_event_types t on t.code = e.event_type
              join public.profiles p on p.id = d.user_id
             where d.channel = 'EMAIL' and d.status = 'PENDING' and d.next_attempt_at <= :now
             order by d.next_attempt_at, d.created_at
             limit :limit
             for update of d skip locked
            """  # noqa: S608 - fixed columns
        ),
        {"now": now, "limit": limit},
    ).mappings()
    return [dict(r) for r in rows]


def mark_delivery_sent(
    session: Session, delivery_ids: list[UUID], *, digest_key: str | None
) -> None:
    session.execute(
        text(
            """
            update public.notification_deliveries
               set status = 'SENT', sent_at = now(), attempts = attempts + 1,
                   last_error = null, digest_key = coalesce(:dk, digest_key)
             where id = any(cast(:ids as uuid[]))
            """
        ),
        {"ids": [str(i) for i in delivery_ids], "dk": digest_key},
    )


def mark_delivery_skipped(session: Session, delivery_ids: list[UUID], reason: str) -> None:
    session.execute(
        text(
            """
            update public.notification_deliveries
               set status = 'SKIPPED', skip_reason = :reason
             where id = any(cast(:ids as uuid[]))
            """
        ),
        {"ids": [str(i) for i in delivery_ids], "reason": reason},
    )


def mark_delivery_retry(
    session: Session,
    delivery_ids: list[UUID],
    *,
    error: str,
    max_attempts: int,
    backoff_seconds: int,
) -> None:
    session.execute(
        text(
            """
            update public.notification_deliveries
               set attempts = attempts + 1,
                   last_error = left(:err, 2000),
                   status = case when attempts + 1 >= :max then 'FAILED' else status end,
                   next_attempt_at = now() + make_interval(secs => :backoff)
             where id = any(cast(:ids as uuid[]))
            """
        ),
        {
            "ids": [str(i) for i in delivery_ids],
            "err": error,
            "max": max_attempts,
            "backoff": backoff_seconds,
        },
    )


def digest_user_ids(session: Session) -> list[UUID]:
    rows = session.execute(
        text("select distinct user_id from public.notification_deliveries where status = 'DIGEST'")
    ).scalars()
    return [UUID(str(r)) for r in rows]


def digest_sent(session: Session, user_id: UUID, digest_key: str) -> bool:
    return bool(
        session.execute(
            text(
                "select exists (select 1 from public.notification_deliveries "
                "where user_id = :u and digest_key = :k)"
            ),
            {"u": user_id, "k": digest_key},
        ).scalar()
    )


def lock_digest_items(session: Session, user_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            f"""
            select {_EMAIL_DELIVERY_COLUMNS}
              from public.notification_deliveries d
              join public.notification_events e on e.id = d.event_id
              join public.notification_event_types t on t.code = e.event_type
              join public.profiles p on p.id = d.user_id
             where d.user_id = :u and d.status = 'DIGEST'
             order by e.created_at
             for update of d skip locked
            """  # noqa: S608 - fixed columns
        ),
        {"u": user_id},
    ).mappings()
    return [dict(r) for r in rows]


# =============================================================================================
# Templates
# =============================================================================================


def published_template(session: Session, event_type: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select id, event_type, channel, version_no, subject, body, status, change_reason,
                       published_at, created_by
                  from public.notification_templates
                 where event_type = :et and channel = 'EMAIL' and status = 'PUBLISHED'
                """
            ),
            {"et": event_type},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def list_published_templates(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select tp.id, tp.event_type, tp.channel, tp.version_no, tp.subject, tp.body,
                   tp.status, tp.change_reason, tp.published_at, tp.created_by,
                   t.label as event_label
              from public.notification_templates tp
              join public.notification_event_types t on t.code = tp.event_type
             where tp.status = 'PUBLISHED'
             order by t.sort_order, t.code
            """
        )
    ).mappings()
    return [dict(r) for r in rows]


def template_versions(session: Session, event_type: str) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select id, event_type, channel, version_no, subject, body, status, change_reason,
                   published_at, created_by
              from public.notification_templates
             where event_type = :et and channel = 'EMAIL'
             order by version_no desc
            """
        ),
        {"et": event_type},
    ).mappings()
    return [dict(r) for r in rows]


def lock_published_template(session: Session, event_type: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select id, version_no, subject, body
                  from public.notification_templates
                 where event_type = :et and channel = 'EMAIL' and status = 'PUBLISHED'
                 for update
                """
            ),
            {"et": event_type},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def max_template_version(session: Session, event_type: str) -> int:
    return int(
        session.execute(
            text(
                "select coalesce(max(version_no), 0) from public.notification_templates "
                "where event_type = :et and channel = 'EMAIL'"
            ),
            {"et": event_type},
        ).scalar_one()
    )


def retire_template(session: Session, template_id: UUID) -> None:
    session.execute(
        text("update public.notification_templates set status = 'RETIRED' where id = :id"),
        {"id": template_id},
    )


def insert_template(
    session: Session,
    *,
    event_type: str,
    version_no: int,
    subject: str,
    body: str,
    reason: str | None,
) -> dict[str, Any]:
    row = (
        session.execute(
            text(
                """
                insert into public.notification_templates
                       (event_type, channel, version_no, subject, body, status, change_reason)
                values (:et, 'EMAIL', :v, :subject, :body, 'PUBLISHED', :reason)
                returning id, event_type, channel, version_no, subject, body, status,
                          change_reason, published_at, created_by
                """
            ),
            {"et": event_type, "v": version_no, "subject": subject, "body": body, "reason": reason},
        )
        .mappings()
        .one()
    )
    return dict(row)


# =============================================================================================
# Rules
# =============================================================================================

_RULE_COLUMNS = """
    r.id, r.event_type, r.name, r.include_context_recipients, r.include_step_assignees,
    r.recipient_role_codes, r.recipient_user_ids, r.channels, r.priority, r.is_active,
    r.created_at, r.updated_at, t.label as event_label, t.is_mandatory
"""


def list_rules(session: Session, event_type: str | None = None) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            f"""
            select {_RULE_COLUMNS}
              from public.notification_rules r
              join public.notification_event_types t on t.code = r.event_type
             where (cast(:et as text) is null or r.event_type = cast(:et as text))
             order by t.sort_order, r.event_type, r.created_at, r.id
            """  # noqa: S608 - fixed columns
        ),
        {"et": event_type},
    ).mappings()
    return [dict(r) for r in rows]


def get_rule(session: Session, rule_id: UUID, *, for_update: bool = False) -> dict[str, Any] | None:
    lock = " for update of r" if for_update else ""
    row = (
        session.execute(
            text(
                f"select {_RULE_COLUMNS} from public.notification_rules r "  # noqa: S608
                "join public.notification_event_types t on t.code = r.event_type "
                f"where r.id = :id{lock}"
            ),
            {"id": rule_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def insert_rule(session: Session, values: dict[str, Any]) -> UUID:
    return UUID(
        str(
            session.execute(
                text(
                    """
                    insert into public.notification_rules
                           (event_type, name, include_context_recipients, include_step_assignees,
                            recipient_role_codes, recipient_user_ids, channels, priority, is_active)
                    values (:event_type, :name, :include_context_recipients,
                            :include_step_assignees, cast(:recipient_role_codes as text[]),
                            cast(:recipient_user_ids as uuid[]), cast(:channels as text[]),
                            :priority, :is_active)
                    returning id
                    """
                ),
                _rule_params(values),
            ).scalar_one()
        )
    )


def update_rule(session: Session, rule_id: UUID, values: dict[str, Any]) -> None:
    session.execute(
        text(
            """
            update public.notification_rules
               set event_type = :event_type, name = :name,
                   include_context_recipients = :include_context_recipients,
                   include_step_assignees = :include_step_assignees,
                   recipient_role_codes = cast(:recipient_role_codes as text[]),
                   recipient_user_ids = cast(:recipient_user_ids as uuid[]),
                   channels = cast(:channels as text[]), priority = :priority,
                   is_active = :is_active
             where id = :id
            """
        ),
        {**_rule_params(values), "id": rule_id},
    )


def delete_rule(session: Session, rule_id: UUID) -> int:
    res = session.execute(
        text("delete from public.notification_rules where id = :id"), {"id": rule_id}
    )
    return int(getattr(res, "rowcount", 0))


def _rule_params(values: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_type": values["event_type"],
        "name": values["name"],
        "include_context_recipients": values["include_context_recipients"],
        "include_step_assignees": values["include_step_assignees"],
        "recipient_role_codes": list(values["recipient_role_codes"]),
        "recipient_user_ids": [str(u) for u in values["recipient_user_ids"]],
        "channels": list(values["channels"]),
        "priority": values["priority"],
        "is_active": values["is_active"],
    }


def existing_role_codes(session: Session, codes: list[str]) -> set[str]:
    if not codes:
        return set()
    rows = session.execute(
        text("select code from public.roles where code = any(:c)"), {"c": codes}
    ).scalars()
    return {str(r) for r in rows}


def existing_user_ids(session: Session, ids: list[UUID]) -> set[UUID]:
    if not ids:
        return set()
    rows = session.execute(
        text("select id from public.profiles where id = any(cast(:ids as uuid[]))"),
        {"ids": [str(i) for i in ids]},
    ).scalars()
    return {UUID(str(r)) for r in rows}


# =============================================================================================
# Escalations (DEC-30)
# =============================================================================================

_ESCALATION_COLUMNS = """
    er.id, er.workflow_step_id, er.after_hours, er.notify_role_id, er.notify_user_id,
    er.is_active, er.created_at, er.updated_at,
    ws.code as step_code, ws.label as step_label, ws.sla_hours,
    wv.id as workflow_version_id, wv.version_no as workflow_version_no,
    wv.status as workflow_version_status, wd.code as workflow_code,
    ro.code as notify_role_code, ro.name as notify_role_name,
    pr.full_name as notify_user_name
"""
_ESCALATION_FROM = """
      from public.escalation_rules er
      join public.workflow_steps ws on ws.id = er.workflow_step_id
      join public.workflow_versions wv on wv.id = ws.workflow_version_id
      join public.workflow_definitions wd on wd.id = wv.workflow_definition_id
      left join public.roles ro on ro.id = er.notify_role_id
      left join public.profiles pr on pr.id = er.notify_user_id
"""


def list_escalation_rules(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            f"select {_ESCALATION_COLUMNS} {_ESCALATION_FROM} "
            "order by wd.code, wv.version_no desc, ws.sort_order, er.after_hours, er.id"
        )
    ).mappings()
    return [dict(r) for r in rows]


def get_escalation_rule(
    session: Session, rule_id: UUID, *, for_update: bool = False
) -> dict[str, Any] | None:
    lock = " for update of er" if for_update else ""
    row = (
        session.execute(
            text(f"select {_ESCALATION_COLUMNS} {_ESCALATION_FROM} where er.id = :id{lock}"),
            {"id": rule_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def workflow_step(session: Session, step_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text("select id, code, label, sla_hours from public.workflow_steps where id = :id"),
            {"id": step_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def role_id_by_code(session: Session, code: str) -> UUID | None:
    row = session.execute(text("select id from public.roles where code = :c"), {"c": code}).scalar()
    return UUID(str(row)) if row else None


def insert_escalation_rule(session: Session, values: dict[str, Any]) -> UUID:
    return UUID(
        str(
            session.execute(
                text(
                    """
                    insert into public.escalation_rules
                           (workflow_step_id, after_hours, notify_role_id, notify_user_id,
                            is_active)
                    values (:step, :after, :role, :user, :active)
                    returning id
                    """
                ),
                values,
            ).scalar_one()
        )
    )


def update_escalation_rule(session: Session, rule_id: UUID, values: dict[str, Any]) -> None:
    session.execute(
        text(
            """
            update public.escalation_rules
               set workflow_step_id = :step, after_hours = :after, notify_role_id = :role,
                   notify_user_id = :user, is_active = :active
             where id = :id
            """
        ),
        {**values, "id": rule_id},
    )


def escalation_rule_used(session: Session, rule_id: UUID) -> bool:
    return bool(
        session.execute(
            text(
                "select exists (select 1 from public.workflow_task_escalations "
                "where escalation_rule_id = :id)"
            ),
            {"id": rule_id},
        ).scalar()
    )


def delete_escalation_rule(session: Session, rule_id: UUID) -> int:
    res = session.execute(
        text("delete from public.escalation_rules where id = :id"), {"id": rule_id}
    )
    return int(getattr(res, "rowcount", 0))


def due_escalations(session: Session, *, now: datetime, limit: int) -> list[dict[str, Any]]:
    """OPEN tasks past due + after_hours of an active escalation level they have not had yet.

    Due = task.due_at, else task.created_at + the step's sla_hours in the GS's pinned workflow
    version (G-18). Level = rank of the rule among the step's active rules by after_hours.
    """
    rows = session.execute(
        text(
            """
            with levels as (
              select er.*, row_number() over (partition by er.workflow_step_id
                                              order by er.after_hours, er.id) as level_no
                from public.escalation_rules er
               where er.is_active
            ), candidates as (
              select t.id as task_id, t.gs_id, t.step_code, t.assigned_role_id, t.assigned_user_id,
                     coalesce(t.due_at, t.created_at + ws.sla_hours * interval '1 hour') as due_at,
                     ws.label as step_label, ws.sla_hours, g.gs_no,
                     l.id as rule_id, l.after_hours, l.notify_role_id, l.notify_user_id, l.level_no
                from public.workflow_tasks t
                join public.goods_slips g on g.id = t.gs_id
                join public.workflow_steps ws
                  on ws.workflow_version_id = g.workflow_version_id and ws.code = t.step_code
                join levels l on l.workflow_step_id = ws.id
               where t.status = 'OPEN'
                 and (t.due_at is not null or ws.sla_hours is not null)
            )
            select c.*, ro.code as notify_role_code
              from candidates c
              left join public.roles ro on ro.id = c.notify_role_id
             where c.due_at + c.after_hours * interval '1 hour' <= :now
               and not exists (select 1 from public.workflow_task_escalations x
                                where x.task_id = c.task_id and x.escalation_rule_id = c.rule_id)
             order by c.due_at, c.level_no
             limit :limit
            """
        ),
        {"now": now, "limit": limit},
    ).mappings()
    return [dict(r) for r in rows]


def insert_task_escalation(
    session: Session,
    *,
    task_id: UUID,
    rule_id: UUID,
    level_no: int,
    due_at: datetime,
    now: datetime,
    event_id: UUID | None,
) -> UUID | None:
    row = session.execute(
        text(
            """
            insert into public.workflow_task_escalations
                   (task_id, escalation_rule_id, level_no, due_at, escalated_at, event_id)
            values (:t, :r, :lvl, :due, :now, :ev)
            on conflict (task_id, escalation_rule_id) do nothing
            returning id
            """
        ),
        {"t": task_id, "r": rule_id, "lvl": level_no, "due": due_at, "now": now, "ev": event_id},
    ).scalar()
    return UUID(str(row)) if row else None


def event_id_by_dedupe_key(session: Session, dedupe_key: str) -> UUID | None:
    row = session.execute(
        text("select id from public.notification_events where dedupe_key = :k"), {"k": dedupe_key}
    ).scalar()
    return UUID(str(row)) if row else None


def mark_task_escalated(session: Session, task_id: UUID, now: datetime) -> None:
    session.execute(
        text("update public.workflow_tasks set escalated_at = :now where id = :id"),
        {"id": task_id, "now": now},
    )


# =============================================================================================
# Config change log
# =============================================================================================


def insert_config_change(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    reason: str | None,
) -> None:
    session.execute(
        text(
            """
            insert into public.config_change_log
                   (entity_type, entity_id, action, before, after, reason)
            values (:et, :eid, :action, cast(:before as jsonb), cast(:after as jsonb), :reason)
            """
        ),
        {
            "et": entity_type,
            "eid": entity_id,
            "action": action,
            "before": json.dumps(before, default=str) if before is not None else None,
            "after": json.dumps(after, default=str) if after is not None else None,
            "reason": reason,
        },
    )


# =============================================================================================
# User-facing notification list & preferences
# =============================================================================================


def list_for_user(
    session: Session,
    user_id: UUID,
    *,
    unread_only: bool,
    limit: int,
    offset: int = 0,
    event_type: str | None = None,
    priority: str | None = None,
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            f"select {_COLUMNS} from public.notifications n "  # noqa: S608 - fixed columns
            "left join public.notification_events e on e.id = n.event_id "
            "where n.user_id = :uid and (not :unread or n.read_at is null) "
            "and (cast(:et as text) is null or e.event_type = cast(:et as text) "
            "     or n.type = cast(:et as text)) "
            "and (cast(:prio as text) is null or n.priority = cast(:prio as text)) "
            "order by n.created_at desc, n.id desc limit :limit offset :offset"
        ),
        {
            "uid": user_id,
            "unread": unread_only,
            "limit": limit,
            "offset": offset,
            "et": event_type,
            "prio": priority,
        },
    ).mappings()
    return [dict(r) for r in rows]


def count_for_user(
    session: Session,
    user_id: UUID,
    *,
    unread_only: bool,
    event_type: str | None = None,
    priority: str | None = None,
) -> int:
    return int(
        session.execute(
            text(
                "select count(*) from public.notifications n "
                "left join public.notification_events e on e.id = n.event_id "
                "where n.user_id = :uid and (not :unread or n.read_at is null) "
                "and (cast(:et as text) is null or e.event_type = cast(:et as text) "
                "     or n.type = cast(:et as text)) "
                "and (cast(:prio as text) is null or n.priority = cast(:prio as text))"
            ),
            {"uid": user_id, "unread": unread_only, "et": event_type, "prio": priority},
        ).scalar_one()
    )


def unread_count(session: Session, user_id: UUID) -> int:
    return int(
        session.execute(
            text(
                "select count(*) from public.notifications where user_id = :uid and read_at is null"
            ),
            {"uid": user_id},
        ).scalar_one()
    )


def mark_read(session: Session, user_id: UUID, notification_id: UUID | None) -> int:
    """Own notifications only; `None` marks every unread one."""
    res = session.execute(
        text(
            """
            update public.notifications set read_at = now()
             where user_id = :uid and read_at is null
               and (cast(:nid as uuid) is null or id = cast(:nid as uuid))
            """
        ),
        {"uid": user_id, "nid": str(notification_id) if notification_id else None},
    )
    return int(getattr(res, "rowcount", 0))


def user_email_mode(session: Session, user_id: UUID) -> str:
    row = session.execute(
        text("select email_mode from public.notification_user_settings where user_id = :u"),
        {"u": user_id},
    ).scalar()
    return str(row) if row else "IMMEDIATE"


def upsert_email_mode(session: Session, user_id: UUID, mode: str) -> None:
    session.execute(
        text(
            """
            insert into public.notification_user_settings (user_id, email_mode)
            values (:u, :m)
            on conflict (user_id) do update set email_mode = excluded.email_mode
            """
        ),
        {"u": user_id, "m": mode},
    )


def user_email_preferences(session: Session, user_id: UUID) -> dict[str, bool]:
    rows = session.execute(
        text(
            "select notification_type, is_enabled from public.notification_preferences "
            "where user_id = :u and channel = 'EMAIL'"
        ),
        {"u": user_id},
    ).all()
    return {str(t): bool(e) for t, e in rows}


def upsert_email_preference(
    session: Session, user_id: UUID, event_type: str, enabled: bool
) -> None:
    session.execute(
        text(
            """
            insert into public.notification_preferences (user_id, notification_type, channel,
                                                         is_enabled)
            values (:u, :t, 'EMAIL', :e)
            on conflict (user_id, notification_type, channel)
            do update set is_enabled = excluded.is_enabled, updated_at = now()
            """
        ),
        {"u": user_id, "t": event_type, "e": enabled},
    )


def user_email(session: Session, user_id: UUID) -> str | None:
    row = session.execute(
        text("select email::text from public.profiles where id = :u"), {"u": user_id}
    ).scalar()
    return str(row) if row else None


# =============================================================================================
# Admin delivery log
# =============================================================================================


def list_deliveries(
    session: Session, *, status: str | None, channel: str | None, limit: int, offset: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select d.id, d.event_id, e.event_type, t.label as event_label, d.user_id,
                   p.full_name as user_name, d.channel, d.status, d.skip_reason, d.attempts,
                   d.last_error, d.email_to, d.sent_at, d.created_at,
                   coalesce(e.payload->>'title', '') as title
              from public.notification_deliveries d
              join public.notification_events e on e.id = d.event_id
              join public.notification_event_types t on t.code = e.event_type
              join public.profiles p on p.id = d.user_id
             where (cast(:st as text) is null or d.status = cast(:st as text))
               and (cast(:ch as text) is null or d.channel = cast(:ch as text))
             order by d.created_at desc, d.id
             limit :limit offset :offset
            """
        ),
        {"st": status, "ch": channel, "limit": limit, "offset": offset},
    ).mappings()
    return [dict(r) for r in rows]


def outbox_summary(session: Session) -> dict[str, int]:
    rows = session.execute(
        text("select status, count(*) from public.notification_events group by status")
    ).all()
    out = {"PENDING": 0, "DISPATCHED": 0, "FAILED": 0}
    out.update({str(s): int(c) for s, c in rows})
    return out


def delivery_summary(session: Session) -> dict[str, int]:
    rows = session.execute(
        text(
            "select channel || ':' || status, count(*) from public.notification_deliveries "
            "group by channel, status"
        )
    ).all()
    return {str(k): int(c) for k, c in rows}


# =============================================================================================
# Admin lookups (rule / escalation editors)
# =============================================================================================


def lookup_roles(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(text("select code, name from public.roles order by name")).mappings()
    return [dict(r) for r in rows]


def lookup_users(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "select id, full_name, email::text as email from public.profiles "
            "where is_active order by full_name"
        )
    ).mappings()
    return [dict(r) for r in rows]


def lookup_steps(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select ws.id, ws.code, ws.label, ws.sla_hours, wd.code as workflow_code,
                   wv.version_no, wv.status as version_status
              from public.workflow_steps ws
              join public.workflow_versions wv on wv.id = ws.workflow_version_id
              join public.workflow_definitions wd on wd.id = wv.workflow_definition_id
             where wv.status in ('PUBLISHED', 'DRAFT')
             order by wd.code, wv.version_no desc, ws.sort_order
            """
        )
    ).mappings()
    return [dict(r) for r in rows]
