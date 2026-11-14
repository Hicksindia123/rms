"""Workflow task inbox SQL (master plan §8.4 workflow_tasks). SQL only, no business rules."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def list_tasks_for_user(
    session: Session,
    *,
    user_id: UUID,
    all_tasks: bool,
    status: str,
    step_code: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """Tasks assigned to the user directly or to one of the user's roles (all for Super Admin)."""
    base = """
        from public.workflow_tasks t
        join public.goods_slips g on g.id = t.gs_id
        left join public.roles r on r.id = t.assigned_role_id
        left join public.parties p on p.id = g.party_id
        left join public.stations st on st.id = g.station_id
        left join public.workflow_steps ws
               on ws.workflow_version_id = g.workflow_version_id and ws.code = t.step_code
       where t.status = :status
         and (cast(:step as text) is null or t.step_code = cast(:step as text))
         and (:all_tasks
              or t.assigned_user_id = :uid
              or exists (select 1 from public.user_roles ur
                          where ur.user_id = :uid and ur.role_id = t.assigned_role_id))
    """
    params = {
        "status": status,
        "step": step_code,
        "uid": user_id,
        "all_tasks": all_tasks,
        "limit": limit,
        "offset": offset,
    }
    total = int(session.execute(text("select count(*) " + base), params).scalar_one())
    rows = session.execute(
        text(
            f"""
            select t.id, t.gs_id, t.step_code, ws.label as step_label,
                   r.code as assigned_role_code, r.name as assigned_role_name,
                   t.status, t.due_at, t.created_at,
                   g.gs_no, g.status as gs_status, g.box_count, g.carton_count,
                   g.missing_documentation,
                   p.name as party_name, st.name as station_name
            {base}
            order by t.due_at nulls last, t.created_at
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings()
    return [dict(r) for r in rows], total
