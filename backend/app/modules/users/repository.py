"""User administration SQL (P1-05). Repository layer: SQL only, no business rules (rule g)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

_USER_SELECT = """
select p.id, p.email::text as email, p.full_name, p.employee_code, p.phone,
       p.is_active, p.is_super_admin, p.must_change_password, p.created_at, p.updated_at,
       d.id as department_id, d.code as department_code, d.name as department_name,
       coalesce(
         (select jsonb_agg(jsonb_build_object('id', r.id, 'code', r.code, 'name', r.name)
                           order by r.code)
            from public.user_roles ur join public.roles r on r.id = ur.role_id
           where ur.user_id = p.id),
         '[]'::jsonb) as roles
  from public.profiles p
  left join public.departments d on d.id = p.department_id
"""

# Columns the service may change through update_profile (allow-list: no client text reaches SQL).
_UPDATABLE = frozenset({"full_name", "employee_code", "phone", "department_id"})


def list_users(
    db: Session,
    *,
    search: str | None,
    role_code: str | None,
    department_id: UUID | None,
    active: bool | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    where = ["true"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if search:
        where.append("(p.full_name ilike :q or p.email::text ilike :q or p.employee_code ilike :q)")
        params["q"] = f"%{search}%"
    if role_code:
        where.append(
            "exists (select 1 from public.user_roles ur join public.roles r on r.id = ur.role_id"
            " where ur.user_id = p.id and r.code = :role_code)"
        )
        params["role_code"] = role_code
    if department_id:
        where.append("p.department_id = :dept")
        params["dept"] = department_id
    if active is not None:
        where.append("p.is_active = :active")
        params["active"] = active
    clause = " and ".join(where)
    total = int(
        db.execute(
            text(f"select count(*) from public.profiles p where {clause}"),  # noqa: S608
            params,
        ).scalar_one()
    )
    rows = (
        db.execute(
            # clause is built from fixed fragments above; values are bind parameters.
            text(
                f"{_USER_SELECT} where {clause} order by p.is_active desc, lower(p.full_name), p.id"
                " limit :limit offset :offset"
            ),
            params,
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows], total


def get_user(db: Session, user_id: UUID, *, for_update: bool = False) -> dict[str, Any] | None:
    lock = " for update of p" if for_update else ""
    row = (
        db.execute(text(f"{_USER_SELECT} where p.id = :id{lock}"), {"id": user_id})
        .mappings()
        .first()
    )
    return dict(row) if row else None


def email_taken(db: Session, email: str) -> bool:
    return bool(
        db.execute(
            text("select exists (select 1 from public.profiles where email = :e)"), {"e": email}
        ).scalar_one()
    )


def employee_code_taken(db: Session, code: str, *, exclude_id: UUID | None = None) -> bool:
    return bool(
        db.execute(
            text(
                "select exists (select 1 from public.profiles where employee_code = :c"
                " and (cast(:x as uuid) is null or id <> cast(:x as uuid)))"
            ),
            {"c": code, "x": str(exclude_id) if exclude_id else None},
        ).scalar_one()
    )


def roles_by_codes(db: Session, codes: Sequence[str]) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            text("select id, code, name from public.roles where code = any(:codes)"),
            {"codes": list(codes)},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def department_active(db: Session, department_id: UUID) -> bool | None:
    """True/False for an existing department, None when it does not exist."""
    value = db.execute(
        text("select is_active from public.departments where id = :id"), {"id": department_id}
    ).scalar_one_or_none()
    return None if value is None else bool(value)


def update_profile(db: Session, user_id: UUID, fields: dict[str, Any]) -> None:
    unknown = set(fields) - _UPDATABLE
    if unknown:
        raise ValueError(f"not updatable: {sorted(unknown)}")
    if not fields:
        return
    assignments = ", ".join(f"{col} = :{col}" for col in sorted(fields))
    db.execute(
        text(f"update public.profiles set {assignments}, updated_at = now() where id = :id"),  # noqa: S608
        {**fields, "id": user_id},
    )


def set_flags(
    db: Session,
    user_id: UUID,
    *,
    is_active: bool | None = None,
    is_super_admin: bool | None = None,
    must_change_password: bool | None = None,
) -> None:
    db.execute(
        text(
            """
            update public.profiles
               set is_active            = coalesce(:active, is_active),
                   is_super_admin       = coalesce(:sa, is_super_admin),
                   must_change_password = coalesce(:mcp, must_change_password),
                   updated_at           = now()
             where id = :id
            """
        ),
        {"id": user_id, "active": is_active, "sa": is_super_admin, "mcp": must_change_password},
    )


def replace_user_roles(db: Session, user_id: UUID, role_ids: Sequence[UUID]) -> None:
    ids = [str(r) for r in role_ids]
    db.execute(
        text(
            "delete from public.user_roles where user_id = :uid"
            " and not (role_id = any(cast(:ids as uuid[])))"
        ),
        {"uid": user_id, "ids": ids},
    )
    db.execute(
        text(
            """
            insert into public.user_roles (user_id, role_id)
            select :uid, x from unnest(cast(:ids as uuid[])) as x
            on conflict (user_id, role_id) do nothing
            """
        ),
        {"uid": user_id, "ids": ids},
    )


def other_active_super_admins(db: Session, user_id: UUID) -> int:
    return int(
        db.execute(
            text(
                "select count(*) from public.profiles"
                " where id <> :id and is_active and is_super_admin"
            ),
            {"id": user_id},
        ).scalar_one()
    )


# --- Overrides -------------------------------------------------------------------------------


def list_overrides(db: Session, user_id: UUID) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            text(
                """
                select o.id, p.module_code, p.action, o.effect, o.reason, o.expires_at,
                       (o.expires_at is not null and o.expires_at <= now()) as is_expired,
                       o.created_at
                  from public.user_permission_overrides o
                  join public.permissions p on p.id = o.permission_id
                 where o.user_id = :uid
                 order by p.module_code, p.action
                """
            ),
            {"uid": user_id},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def permission_ids(db: Session) -> dict[tuple[str, str], UUID]:
    rows = db.execute(text("select id, module_code, action from public.permissions")).all()
    return {(r.module_code, r.action): r.id for r in rows}


def replace_overrides(db: Session, user_id: UUID, rows: Sequence[dict[str, Any]]) -> None:
    db.execute(
        text("delete from public.user_permission_overrides where user_id = :uid"), {"uid": user_id}
    )
    for row in rows:
        db.execute(
            text(
                """
                insert into public.user_permission_overrides
                       (user_id, permission_id, effect, reason, expires_at)
                values (:uid, :pid, :effect, :reason, :expires_at)
                """
            ),
            {"uid": user_id, **row},
        )


# --- Departments -----------------------------------------------------------------------------


def list_departments(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            text(
                """
                select d.id, d.code, d.name, d.is_active,
                       (select count(*) from public.profiles p
                         where p.department_id = d.id) as user_count
                  from public.departments d
                 order by d.is_active desc, d.name
                """
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def get_department(db: Session, department_id: UUID) -> dict[str, Any] | None:
    for row in list_departments(db):
        if row["id"] == department_id:
            return row
    return None


def department_code_taken(db: Session, code: str) -> bool:
    return bool(
        db.execute(
            text("select exists (select 1 from public.departments where code = :c)"), {"c": code}
        ).scalar_one()
    )


def insert_department(db: Session, code: str, name: str) -> UUID:
    return UUID(
        str(
            db.execute(
                text("insert into public.departments (code, name) values (:c, :n) returning id"),
                {"c": code, "n": name},
            ).scalar_one()
        )
    )


def update_department(
    db: Session, department_id: UUID, *, name: str | None, is_active: bool | None
) -> None:
    db.execute(
        text(
            """
            update public.departments
               set name = coalesce(:name, name),
                   is_active = coalesce(:active, is_active),
                   updated_at = now()
             where id = :id
            """
        ),
        {"id": department_id, "name": name, "active": is_active},
    )
