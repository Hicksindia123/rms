"""Repository for Audit Explorer, GS Activity Timeline and User Activity (P4-04)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def query_audit_log(
    session: Session,
    *,
    table_name: str | None = None,
    row_id: str | None = None,
    actor_id: UUID | None = None,
    action: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    request_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    conditions: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    if table_name:
        conditions.append("a.table_name = :table_name")
        params["table_name"] = table_name.strip()
    if row_id:
        conditions.append("a.row_id = :row_id")
        params["row_id"] = row_id.strip()
    if actor_id:
        conditions.append("a.actor_id = :actor_id")
        params["actor_id"] = actor_id
    if action:
        conditions.append("a.action = :action")
        params["action"] = action.strip().upper()
    if date_from:
        conditions.append("a.at >= :date_from")
        params["date_from"] = date_from
    if date_to:
        conditions.append("a.at <= :date_to")
        params["date_to"] = date_to
    if request_id:
        conditions.append("a.request_id = :request_id")
        params["request_id"] = request_id.strip()

    where_clause = f"where {' and '.join(conditions)}" if conditions else ""

    count_sql = f"select count(*) from public.audit_log a {where_clause}"  # noqa: S608
    total = session.execute(text(count_sql), params).scalar() or 0

    data_sql = f"""
        select a.id, a.table_name, a.row_id, a.action, a.actor_id,
               p.full_name as actor_name, p.email as actor_email,
               a.request_id, a.db_user, a.at, a.changed_fields,
               a.old as old_values, a.new as new_values, a.reason
        from public.audit_log a
        left join public.profiles p on p.id = a.actor_id
        {where_clause}
        order by a.at desc
        limit :limit offset :offset
    """  # noqa: S608
    rows = session.execute(text(data_sql), params).mappings().all()
    return [dict(r) for r in rows], int(total)


def get_distinct_audit_tables(session: Session) -> list[str]:
    sql = "select distinct table_name from public.audit_log order by table_name asc"
    rows = session.execute(text(sql)).scalars().all()
    return list(rows)


def get_gs_status_history(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    sql = """
        select h.id, h.gs_id, h.from_status, h.to_status, h.step_code,
               h.reason as transition_reason,
               h.by as actor_id, p.full_name as actor_name, h.at
        from public.gs_status_history h
        left join public.profiles p on p.id = h.by
        where h.gs_id = :gid
        order by h.at asc
    """
    rows = session.execute(text(sql), {"gid": gs_id}).mappings().all()
    return [dict(r) for r in rows]


def get_gs_audit_entries(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    gid_str = str(gs_id)
    sql = """
        select a.id, a.table_name, a.row_id, a.action, a.actor_id,
               p.full_name as actor_name, a.request_id, a.at,
               a.changed_fields, a.old as old_values, a.new as new_values, a.reason
        from public.audit_log a
        left join public.profiles p on p.id = a.actor_id
        where a.row_id = :gid
           or (a.table_name = 'goods_slips' and a.row_id = :gid)
           or (a.new->>'goods_slip_id' = :gid or a.old->>'goods_slip_id' = :gid)
           or (a.new->>'gs_id' = :gid or a.old->>'gs_id' = :gid)
        order by a.at asc
    """
    rows = session.execute(text(sql), {"gid": gid_str}).mappings().all()
    return [dict(r) for r in rows]


def get_gs_stock_movements(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    sql = """
        select sm.id, sm.movement_type, sm.qty, sm.created_at as at,
               sm.created_by as actor_id, p.full_name as actor_name,
               fl.name as from_location_name, tl.name as to_location_name,
               sl.id as lot_id, sl.condition_class, si.item_kind
        from public.stock_movements sm
        join public.stock_lots sl on sl.id = sm.lot_id
        join public.stock_items si on si.id = sl.stock_item_id
        left join public.profiles p on p.id = sm.created_by
        left join public.inventory_locations fl on fl.id = sm.from_location_id
        left join public.inventory_locations tl on tl.id = sm.to_location_id
        where sl.gs_id = :gid
        order by sm.created_at asc
    """
    rows = session.execute(text(sql), {"gid": gs_id}).mappings().all()
    return [dict(r) for r in rows]


def get_gs_notification_events(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    sql = """
        select ne.id, ne.event_type, ne.priority, ne.payload,
               ne.created_at as at, ne.created_by as actor_id,
               p.full_name as actor_name
        from public.notification_events ne
        left join public.profiles p on p.id = ne.created_by
        where ne.gs_id = :gid
        order by ne.created_at asc
    """
    rows = session.execute(text(sql), {"gid": gs_id}).mappings().all()
    return [dict(r) for r in rows]


def insert_user_activity(
    session: Session,
    *,
    user_id: UUID,
    activity_type: str,
    session_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    sql = """
        insert into public.user_activity (
            user_id, activity_type, session_id, ip_address, user_agent,
            entity_type, entity_id, details, request_id
        ) values (
            :uid, :atype, :sid, :ip, :ua,
            :etype, :eid, cast(:details as jsonb), :rid
        )
        returning id, user_id, activity_type, session_id, ip_address, user_agent,
                  entity_type, entity_id, details, request_id, created_at
    """
    row = (
        session.execute(
            text(sql),
            {
                "uid": user_id,
                "atype": activity_type,
                "sid": session_id,
                "ip": ip_address,
                "ua": user_agent[:300] if user_agent else None,
                "etype": entity_type,
                "eid": entity_id,
                "details": json.dumps(details or {}),
                "rid": request_id,
            },
        )
        .mappings()
        .one()
    )
    return dict(row)


def list_user_activity(
    session: Session, user_id: UUID, limit: int = 50, offset: int = 0
) -> tuple[list[dict[str, Any]], int]:
    count_sql = "select count(*) from public.user_activity where user_id = :uid"
    total = session.execute(text(count_sql), {"uid": user_id}).scalar() or 0

    sql = """
        select id, user_id, activity_type, session_id, ip_address, user_agent,
               entity_type, entity_id, details, request_id, created_at
        from public.user_activity
        where user_id = :uid
        order by created_at desc
        limit :limit offset :offset
    """
    rows = (
        session.execute(text(sql), {"uid": user_id, "limit": limit, "offset": offset})
        .mappings()
        .all()
    )
    return [dict(r) for r in rows], int(total)
