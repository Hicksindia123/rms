"""Role & permission administration SQL (P1-05). SQL only, no business rules (rule g)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

_ROLE_SELECT = """
select r.id, r.code, r.name, r.description, r.is_system,
       (select count(*) from public.user_roles ur where ur.role_id = r.id) as user_count,
       (select count(*) from public.role_permissions rp where rp.role_id = r.id) as permission_count
  from public.roles r
"""

# Tables (other than user_roles / role_permissions) whose rows keep a role in use.
_ROLE_REFERENCES = (
    "inventory_locations where custodian_role_id",
    "report_column_prefs where role_id",
    "step_assignments where role_id",
    "escalation_rules where notify_role_id",
    "workflow_tasks where assigned_role_id",
    "role_dashboard_layouts where role_id",
    "role_journey_steps where role_id",
    "intermediate_stores where role_id",  # DEC-61: a store role is never deleted
)


def list_roles(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(text(f"{_ROLE_SELECT} order by r.is_system desc, r.name")).mappings().all()
    return [dict(r) for r in rows]


def get_role(db: Session, role_id: UUID) -> dict[str, Any] | None:
    row = db.execute(text(f"{_ROLE_SELECT} where r.id = :id"), {"id": role_id}).mappings().first()
    return dict(row) if row else None


def role_code_taken(db: Session, code: str) -> bool:
    return bool(
        db.execute(
            text("select exists (select 1 from public.roles where code = :c)"), {"c": code}
        ).scalar_one()
    )


def insert_role(db: Session, code: str, name: str, description: str | None) -> UUID:
    return UUID(
        str(
            db.execute(
                text(
                    "insert into public.roles (code, name, description, is_system)"
                    " values (:c, :n, :d, false) returning id"
                ),
                {"c": code, "n": name, "d": description},
            ).scalar_one()
        )
    )


def update_role(db: Session, role_id: UUID, fields: dict[str, Any]) -> None:
    allowed = {"name", "description"}
    if set(fields) - allowed:
        raise ValueError(f"not updatable: {sorted(set(fields) - allowed)}")
    if not fields:
        return
    assignments = ", ".join(f"{col} = :{col}" for col in sorted(fields))
    db.execute(
        text(f"update public.roles set {assignments}, updated_at = now() where id = :id"),  # noqa: S608
        {**fields, "id": role_id},
    )


def role_reference_count(db: Session, role_id: UUID) -> int:
    parts = [f"(select count(*) from public.{ref} = :id)" for ref in _ROLE_REFERENCES]  # noqa: S608
    sql = "select " + " + ".join(parts)  # fixed fragments from _ROLE_REFERENCES
    return int(db.execute(text(sql), {"id": role_id}).scalar_one())


def delete_role(db: Session, role_id: UUID) -> None:
    db.execute(text("delete from public.role_permissions where role_id = :id"), {"id": role_id})
    db.execute(text("delete from public.roles where id = :id"), {"id": role_id})


def permission_catalogue(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            text(
                "select module_code, action, description from public.permissions"
                " order by module_code, action"
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def permission_ids(db: Session) -> dict[tuple[str, str], UUID]:
    rows = db.execute(text("select id, module_code, action from public.permissions")).all()
    return {(r.module_code, r.action): r.id for r in rows}


def role_permissions(db: Session, role_id: UUID) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            text(
                """
                select p.module_code, p.action, rp.scope
                  from public.role_permissions rp
                  join public.permissions p on p.id = rp.permission_id
                 where rp.role_id = :id
                 order by p.module_code, p.action
                """
            ),
            {"id": role_id},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def replace_role_permissions(db: Session, role_id: UUID, rows: Sequence[tuple[UUID, str]]) -> None:
    """rows = (permission_id, scope). Unchanged rows are kept (preserving created_at/by)."""
    ids = [str(pid) for pid, _ in rows]
    db.execute(
        text(
            "delete from public.role_permissions where role_id = :rid"
            " and not (permission_id = any(cast(:ids as uuid[])))"
        ),
        {"rid": role_id, "ids": ids},
    )
    for pid, scope in rows:
        db.execute(
            text(
                """
                insert into public.role_permissions (role_id, permission_id, scope)
                values (:rid, :pid, :scope)
                on conflict (role_id, permission_id)
                do update set scope = excluded.scope, updated_at = now()
                 where public.role_permissions.scope is distinct from excluded.scope
                """
            ),
            {"rid": role_id, "pid": pid, "scope": scope},
        )


def actor_holds_role(db: Session, user_id: UUID, role_id: UUID) -> bool:
    return bool(
        db.execute(
            text(
                "select exists (select 1 from public.user_roles"
                " where user_id = :uid and role_id = :rid)"
            ),
            {"uid": user_id, "rid": role_id},
        ).scalar_one()
    )
