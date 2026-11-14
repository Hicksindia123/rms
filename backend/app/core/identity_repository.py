"""SQL for the identity / RBAC tables used by the core auth layer (master plan §8.1, §9.3).

Repository layer: SQL only, no business rules (CLAUDE.md rule g). The permission arithmetic lives
in app/core/permissions.py.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class ProfileRow:
    id: UUID
    email: str | None
    full_name: str
    employee_code: str | None
    phone: str | None
    is_active: bool
    is_super_admin: bool
    department_id: UUID | None
    department_code: str | None
    department_name: str | None
    must_change_password: bool = False


@dataclass(frozen=True, slots=True)
class RoleRow:
    id: UUID
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class RolePermissionRow:
    module_code: str
    action: str
    scope: str


@dataclass(frozen=True, slots=True)
class OverrideRow:
    module_code: str
    action: str
    effect: str
    expires_at: datetime | None


def get_profile(session: Session, user_id: UUID) -> ProfileRow | None:
    row = (
        session.execute(
            text(
                """
            select p.id, p.email::text as email, p.full_name, p.employee_code, p.phone,
                   p.is_active, p.is_super_admin, p.department_id,
                   d.code as department_code, d.name as department_name,
                   p.must_change_password
              from public.profiles p
              left join public.departments d on d.id = p.department_id
             where p.id = :uid
            """
            ),
            {"uid": user_id},
        )
        .mappings()
        .first()
    )
    return ProfileRow(**row) if row else None


def get_roles(session: Session, user_id: UUID) -> list[RoleRow]:
    rows = session.execute(
        text(
            """
            select r.id, r.code, r.name
              from public.user_roles ur
              join public.roles r on r.id = ur.role_id
             where ur.user_id = :uid
             order by r.code
            """
        ),
        {"uid": user_id},
    ).mappings()
    return [RoleRow(**r) for r in rows]


def get_role_permissions(session: Session, user_id: UUID) -> list[RolePermissionRow]:
    rows = session.execute(
        text(
            """
            select p.module_code, p.action, rp.scope
              from public.user_roles ur
              join public.role_permissions rp on rp.role_id = ur.role_id
              join public.permissions p on p.id = rp.permission_id
             where ur.user_id = :uid
            """
        ),
        {"uid": user_id},
    ).mappings()
    return [RolePermissionRow(**r) for r in rows]


def get_permission_overrides(session: Session, user_id: UUID) -> list[OverrideRow]:
    rows = session.execute(
        text(
            """
            select p.module_code, p.action, o.effect, o.expires_at
              from public.user_permission_overrides o
              join public.permissions p on p.id = o.permission_id
             where o.user_id = :uid
            """
        ),
        {"uid": user_id},
    ).mappings()
    return [OverrideRow(**r) for r in rows]


def list_permission_catalogue(session: Session) -> list[tuple[str, str]]:
    rows = session.execute(
        text("select module_code, action from public.permissions order by module_code, action")
    )
    return [(r.module_code, r.action) for r in rows]


# Step assignments are read from the PUBLISHED version of each active workflow definition only
# (G-18: drafts and retired versions never authorise anyone).
_PUBLISHED_STEPS = """
    from public.workflow_steps ws
    join public.workflow_versions wv on wv.id = ws.workflow_version_id and wv.status = 'PUBLISHED'
    join public.workflow_definitions wd on wd.id = wv.workflow_definition_id and wd.is_active
   where ws.is_active
"""


def list_assigned_step_codes(session: Session, user_id: UUID, assignment_type: str) -> list[str]:
    rows = session.execute(
        text(
            f"""
            select distinct ws.code
            {_PUBLISHED_STEPS}
               and exists (
                 select 1 from public.step_assignments sa
                  where sa.workflow_step_id = ws.id
                    and sa.assignment_type = :atype
                    and (sa.user_id = :uid
                         or sa.role_id in (select ur.role_id from public.user_roles ur
                                            where ur.user_id = :uid))
               )
             order by ws.code
            """  # noqa: S608 - fixed SQL fragment, all values are bound parameters
        ),
        {"uid": user_id, "atype": assignment_type},
    )
    return [r.code for r in rows]


def list_published_step_codes(session: Session) -> list[str]:
    rows = session.execute(text(f"select distinct ws.code {_PUBLISHED_STEPS} order by ws.code"))
    return [r.code for r in rows]
