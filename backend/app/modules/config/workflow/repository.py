"""Repository for workflow configuration, versioning, and draft management (prompt P1-08)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

_DEF_COLUMNS = "id, code, name, is_active, created_at, updated_at"
_VER_COLUMNS = (
    "id, workflow_definition_id, version_no, status, snapshot, "
    "published_by, published_at, created_at, updated_at"
)


def list_workflow_definitions(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            f"""
            select d.{_DEF_COLUMNS},
                   (select v.version_no from public.workflow_versions v
                     where v.workflow_definition_id = d.id and v.status = 'PUBLISHED'
                     limit 1) as latest_published_version,
                   exists(select 1 from public.workflow_versions v
                           where v.workflow_definition_id = d.id and v.status = 'DRAFT'
                   ) as has_draft,
                   (select v.version_no from public.workflow_versions v
                     where v.workflow_definition_id = d.id and v.status = 'DRAFT'
                     limit 1) as draft_version_no
            from public.workflow_definitions d
            order by d.code asc
            """  # noqa: S608
        )
    ).mappings()
    return [dict(r) for r in rows]


def get_workflow_definition(session: Session, code_or_id: str | UUID) -> dict[str, Any] | None:
    is_uuid = False
    if isinstance(code_or_id, UUID):
        is_uuid = True
    else:
        try:
            UUID(str(code_or_id))
            is_uuid = True
        except ValueError:
            pass

    if is_uuid:
        sql = f"select {_DEF_COLUMNS} from public.workflow_definitions where id = :val"  # noqa: S608
    else:
        sql = f"select {_DEF_COLUMNS} from public.workflow_definitions where code = :val"  # noqa: S608

    row = session.execute(text(sql), {"val": str(code_or_id)}).mappings().first()
    if not row:
        return None

    res = dict(row)
    draft_row = session.execute(
        text(
            """
            select version_no from public.workflow_versions
            where workflow_definition_id = :did and status = 'DRAFT'
            limit 1
            """
        ),
        {"did": res["id"]},
    ).first()
    res["has_draft"] = draft_row is not None
    res["draft_version_no"] = draft_row[0] if draft_row else None

    pub_row = session.execute(
        text(
            """
            select version_no from public.workflow_versions
            where workflow_definition_id = :did and status = 'PUBLISHED'
            limit 1
            """
        ),
        {"did": res["id"]},
    ).first()
    res["latest_published_version"] = pub_row[0] if pub_row else None
    return res


def list_workflow_versions(session: Session, definition_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            f"""
            select {_VER_COLUMNS}
            from public.workflow_versions
            where workflow_definition_id = :def_id
            order by version_no desc
            """  # noqa: S608
        ),
        {"def_id": definition_id},
    ).mappings()
    return [dict(r) for r in rows]


def get_published_version(session: Session, definition_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                f"""
            select {_VER_COLUMNS}
            from public.workflow_versions
            where workflow_definition_id = :def_id and status = 'PUBLISHED'
            limit 1
            """  # noqa: S608
            ),
            {"def_id": definition_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_workflow_version(
    session: Session, definition_id: UUID, version_no: int
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                f"""
            select {_VER_COLUMNS}
            from public.workflow_versions
            where workflow_definition_id = :def_id and version_no = :vno
            limit 1
            """  # noqa: S608
            ),
            {"def_id": definition_id, "vno": version_no},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_draft_version(session: Session, definition_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                f"""
            select {_VER_COLUMNS}
            from public.workflow_versions
            where workflow_definition_id = :def_id and status = 'DRAFT'
            limit 1
            """  # noqa: S608
            ),
            {"def_id": definition_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_max_version_no(session: Session, definition_id: UUID) -> int:
    val = session.execute(
        text(
            """
            select coalesce(max(version_no), 0)
            from public.workflow_versions
            where workflow_definition_id = :did
            """
        ),
        {"did": definition_id},
    ).scalar()
    return int(val or 0)


def create_draft_version(session: Session, definition_id: UUID, version_no: int) -> dict[str, Any]:
    row = (
        session.execute(
            text(
                f"""
            insert into public.workflow_versions (workflow_definition_id, version_no, status)
            values (:did, :vno, 'DRAFT')
            returning {_VER_COLUMNS}
            """  # noqa: S608
            ),
            {"did": definition_id, "vno": version_no},
        )
        .mappings()
        .one()
    )
    return dict(row)


def list_stages(session: Session, version_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select id, workflow_version_id, code, label, sort_order, created_at, updated_at
            from public.workflow_stages
            where workflow_version_id = :vid
            order by sort_order asc, code asc
            """
        ),
        {"vid": version_id},
    ).mappings()
    return [dict(r) for r in rows]


def list_steps(session: Session, version_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select s.id, s.workflow_version_id, s.stage_id, stg.code as stage_code,
                   s.code, s.label, s.form_definition_id, fd.code as form_code,
                   s.sla_hours, s.requires_approval, s.sort_order, s.is_active,
                   s.created_at, s.updated_at
            from public.workflow_steps s
            left join public.workflow_stages stg on stg.id = s.stage_id
            left join public.form_definitions fd on fd.id = s.form_definition_id
            where s.workflow_version_id = :vid
            order by s.sort_order asc, s.code asc
            """
        ),
        {"vid": version_id},
    ).mappings()

    steps = [dict(r) for r in rows]
    # Fetch assignments for each step
    for step in steps:
        assign_rows = session.execute(
            text(
                """
                select a.id, a.role_id, r.code as role_code, a.user_id, a.assignment_type
                from public.step_assignments a
                left join public.roles r on r.id = a.role_id
                where a.workflow_step_id = :sid
                order by a.assignment_type asc
                """
            ),
            {"sid": step["id"]},
        ).mappings()
        step["assignments"] = [dict(a) for a in assign_rows]
    return steps


def list_transitions(session: Session, version_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select t.id, t.workflow_version_id, t.from_step_id, fs.code as from_step_code,
                   t.to_step_id, ts.code as to_step_code, t.condition, t.system_guards,
                   t.priority, t.created_at, t.updated_at
            from public.workflow_transitions t
            join public.workflow_steps fs on fs.id = t.from_step_id
            join public.workflow_steps ts on ts.id = t.to_step_id
            where t.workflow_version_id = :vid
            order by t.priority desc, t.id asc
            """
        ),
        {"vid": version_id},
    ).mappings()
    return [dict(r) for r in rows]


def retire_published_version(session: Session, definition_id: UUID) -> None:
    session.execute(
        text(
            """
            update public.workflow_versions
            set status = 'RETIRED', updated_at = now()
            where workflow_definition_id = :did and status = 'PUBLISHED'
            """
        ),
        {"did": definition_id},
    )


def publish_version(
    session: Session, version_id: UUID, snapshot: dict[str, Any], user_id: UUID
) -> dict[str, Any]:
    row = (
        session.execute(
            text(
                f"""
            update public.workflow_versions
            set status = 'PUBLISHED',
                snapshot = cast(:snap as jsonb),
                published_by = :uid,
                published_at = now(),
                updated_at = now()
            where id = :vid
            returning {_VER_COLUMNS}
            """  # noqa: S608
            ),
            {"vid": version_id, "snap": json.dumps(snapshot), "uid": user_id},
        )
        .mappings()
        .one()
    )
    return dict(row)
