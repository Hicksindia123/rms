"""User administration service (master plan prompt P1-05; production audit finding B10).

Rules (enforced here first; the DB triggers of migration 20261114000500 repeat 2-4):
 1. Only an active Super Admin can grant/revoke Super Admin (flag + SUPER_ADMIN marker role) or
    change, deactivate, reactivate or reset the password of a Super Admin.
 2. Nobody can deactivate themselves or remove their own Super Admin rights.
 3. The last active Super Admin can be neither deactivated nor demoted.
 4. Nobody changes their own roles or permission overrides through the admin API (no
    self-escalation).
 5. Every change is recorded in config_change_log with actor (transaction context) and reason;
    the generic audit trigger (G-17) records the row changes as well.

Auth (Supabase GoTrue) calls happen inside the DB transaction, after the DB checks: when the
sign-in service fails, the transaction rolls back. User creation is the exception (the profile
row is created by the auth trigger), so every check runs before the auth user is created.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from app.core.db import UnitOfWork
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.permissions import effective_permissions
from app.core.security import CurrentUser
from app.modules.users import repository as repo
from app.modules.users.schemas import (
    ChangeOwnPasswordIn,
    DepartmentCreate,
    DepartmentOut,
    DepartmentRef,
    DepartmentUpdate,
    EffectivePermissionOut,
    EffectivePermissionsOut,
    OverrideOut,
    OverridesReplaceIn,
    ReasonIn,
    ResetPasswordIn,
    RoleRef,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.shared.auth_admin import AuthAdmin
from app.shared.change_log import log_change
from app.shared.pagination import Page

log = structlog.get_logger("rms.users")

SUPER_ADMIN_ROLE = "SUPER_ADMIN"


def _to_out(row: dict[str, Any]) -> UserOut:
    dept = (
        DepartmentRef(
            id=row["department_id"], code=row["department_code"], name=row["department_name"]
        )
        if row["department_id"]
        else None
    )
    return UserOut(
        id=row["id"],
        email=row["email"],
        full_name=row["full_name"],
        employee_code=row["employee_code"],
        phone=row["phone"],
        department=dept,
        is_active=row["is_active"],
        is_super_admin=row["is_super_admin"],
        must_change_password=row["must_change_password"],
        roles=[RoleRef(**r) for r in row["roles"]],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "full_name": row["full_name"],
        "employee_code": row["employee_code"],
        "phone": row["phone"],
        "department_id": row["department_id"],
        "is_active": row["is_active"],
        "is_super_admin": row["is_super_admin"],
        "roles": sorted(r["code"] for r in row["roles"]),
    }


class UserAdminService:
    def __init__(self, uow: UnitOfWork, auth_admin: AuthAdmin | None = None) -> None:
        self._uow = uow
        self._auth_admin = auth_admin

    @property
    def _auth(self) -> AuthAdmin:
        if self._auth_admin is None:  # pragma: no cover - wiring error, not a user error
            raise RuntimeError("UserAdminService needs an AuthAdmin for this command")
        return self._auth_admin

    # --- helpers ------------------------------------------------------------------------------

    @staticmethod
    def _require_super_admin(actor: CurrentUser, what: str) -> None:
        if not actor.is_super_admin:
            raise PermissionDenied(f"Only a Super Admin can {what}", code="SUPER_ADMIN_REQUIRED")

    @staticmethod
    def _load(session: Session, user_id: UUID, *, for_update: bool = False) -> dict[str, Any]:
        row = repo.get_user(session, user_id, for_update=for_update)
        if row is None:
            raise NotFound("User not found", code="USER_NOT_FOUND")
        return row

    def _guard_target(self, actor: CurrentUser, target: dict[str, Any], what: str) -> None:
        if target["is_super_admin"]:
            self._require_super_admin(actor, f"{what} a Super Admin")

    @staticmethod
    def _resolve_roles(session: Session, codes: Sequence[str]) -> list[dict[str, Any]]:
        wanted = sorted({c.strip().upper() for c in codes if c.strip()})
        if SUPER_ADMIN_ROLE in wanted:
            raise ValidationFailed(
                "Super Admin is granted with the Super Admin switch, not as a role",
                code="SUPER_ADMIN_ROLE_VIA_FLAG",
                details={"field": "role_codes"},
            )
        found = repo.roles_by_codes(session, wanted)
        missing = sorted(set(wanted) - {r["code"] for r in found})
        if missing:
            raise ValidationFailed(
                "Unknown role code(s)", code="UNKNOWN_ROLE", details={"role_codes": missing}
            )
        return found

    @staticmethod
    def _check_department(session: Session, department_id: UUID | None) -> None:
        if department_id is None:
            return
        state = repo.department_active(session, department_id)
        if state is None:
            raise ValidationFailed("Department not found", code="UNKNOWN_DEPARTMENT")
        if not state:
            raise ValidationFailed("Department is inactive", code="DEPARTMENT_INACTIVE")

    @staticmethod
    def _role_ids_with_flag(
        session: Session, roles: list[dict[str, Any]], is_super_admin: bool
    ) -> list[UUID]:
        ids = [r["id"] for r in roles]
        if is_super_admin:
            ids += [r["id"] for r in repo.roles_by_codes(session, [SUPER_ADMIN_ROLE])]
        return ids

    # --- queries ------------------------------------------------------------------------------

    def list_users(
        self,
        actor: CurrentUser,
        *,
        search: str | None,
        role_code: str | None,
        department_id: UUID | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> Page[UserOut]:
        active = {"active": True, "inactive": False}.get(status or "")
        with self._uow.transaction(actor.id) as session:
            rows, total = repo.list_users(
                session,
                search=(search or "").strip() or None,
                role_code=role_code,
                department_id=department_id,
                active=active,
                limit=page_size,
                offset=(page - 1) * page_size,
            )
        return Page(items=[_to_out(r) for r in rows], total=total, page=page, page_size=page_size)

    def get_user(self, actor: CurrentUser, user_id: UUID) -> UserOut:
        with self._uow.transaction(actor.id) as session:
            return _to_out(self._load(session, user_id))

    def effective_permissions(self, actor: CurrentUser, user_id: UUID) -> EffectivePermissionsOut:
        with self._uow.transaction(actor.id) as session:
            target = self._load(session, user_id)
            perms = effective_permissions(session, user_id, is_super_admin=target["is_super_admin"])
        return EffectivePermissionsOut(
            user_id=user_id,
            is_super_admin=perms.is_super_admin,
            permissions=[
                EffectivePermissionOut(module_code=m, action=a, scope=s)
                for (m, a), s in sorted(perms.grants.items())
            ],
        )

    def list_overrides(self, actor: CurrentUser, user_id: UUID) -> list[OverrideOut]:
        with self._uow.transaction(actor.id) as session:
            self._load(session, user_id)
            return [OverrideOut(**r) for r in repo.list_overrides(session, user_id)]

    # --- commands -----------------------------------------------------------------------------

    def create_user(self, actor: CurrentUser, payload: UserCreate) -> UserOut:
        if payload.is_super_admin:
            self._require_super_admin(actor, "create a Super Admin")
        # 1. Every check before the auth user exists.
        with self._uow.transaction(actor.id) as session:
            if repo.email_taken(session, payload.email):
                raise Conflict("A user with this email already exists", code="EMAIL_TAKEN")
            if payload.employee_code and repo.employee_code_taken(session, payload.employee_code):
                raise Conflict("This employee code is already used", code="EMPLOYEE_CODE_TAKEN")
            self._check_department(session, payload.department_id)
            self._resolve_roles(session, payload.role_codes)

        # 2. Auth user (the auth trigger creates the ACTIVE profile).
        created = self._auth.create_user(
            email=payload.email,
            password=payload.initial_password,
            user_metadata={"full_name": payload.full_name},
        )

        # 3. Profile details, roles, flags, change log.
        try:
            with self._uow.transaction(actor.id) as session:
                roles = self._resolve_roles(session, payload.role_codes)
                repo.update_profile(
                    session,
                    created.id,
                    {
                        "full_name": payload.full_name,
                        "employee_code": payload.employee_code,
                        "phone": payload.phone,
                        "department_id": payload.department_id,
                    },
                )
                repo.set_flags(
                    session,
                    created.id,
                    is_active=True,
                    is_super_admin=payload.is_super_admin,
                    must_change_password=payload.must_change_password,
                )
                repo.replace_user_roles(
                    session,
                    created.id,
                    self._role_ids_with_flag(session, roles, payload.is_super_admin),
                )
                row = self._load(session, created.id)
                log_change(
                    session,
                    entity_type="user",
                    entity_id=created.id,
                    action="USER_CREATED",
                    before=None,
                    after=_snapshot(row),
                    reason=None,
                )
        except Exception:
            # The auth user exists but its profile setup failed: leave a clear trail for the admin
            # (the profile is visible in the user list and can be completed or deactivated).
            log.error("user_create_profile_setup_failed", user_id=str(created.id), exc_info=True)
            raise
        log.info("user_created", user_id=str(created.id), by=str(actor.id))
        return _to_out(row)

    def update_user(self, actor: CurrentUser, user_id: UUID, payload: UserUpdate) -> UserOut:
        sent = payload.model_fields_set
        with self._uow.transaction(actor.id) as session:
            target = self._load(session, user_id, for_update=True)
            before = _snapshot(target)
            self._guard_target(actor, target, "change")
            if user_id == actor.id and ("role_codes" in sent or "is_super_admin" in sent):
                raise PermissionDenied(
                    "You cannot change your own roles or Super Admin rights",
                    code="SELF_CHANGE_FORBIDDEN",
                )

            fields: dict[str, Any] = {}
            if "full_name" in sent and payload.full_name:
                fields["full_name"] = payload.full_name
            if "employee_code" in sent:
                if payload.employee_code and repo.employee_code_taken(
                    session, payload.employee_code, exclude_id=user_id
                ):
                    raise Conflict("This employee code is already used", code="EMPLOYEE_CODE_TAKEN")
                fields["employee_code"] = payload.employee_code
            if "phone" in sent:
                fields["phone"] = payload.phone
            if "department_id" in sent:
                self._check_department(session, payload.department_id)
                fields["department_id"] = payload.department_id
            repo.update_profile(session, user_id, fields)

            new_flag = target["is_super_admin"]
            if (
                "is_super_admin" in sent
                and payload.is_super_admin is not None
                and payload.is_super_admin != target["is_super_admin"]
            ):
                self._require_super_admin(actor, "grant or revoke Super Admin")
                if (
                    not payload.is_super_admin
                    and target["is_active"]
                    and repo.other_active_super_admins(session, user_id) == 0
                ):
                    raise Conflict(
                        "The last active Super Admin cannot be demoted",
                        code="LAST_SUPER_ADMIN",
                    )
                new_flag = payload.is_super_admin
                repo.set_flags(session, user_id, is_super_admin=new_flag)

            if ("role_codes" in sent and payload.role_codes is not None) or (
                new_flag != target["is_super_admin"]
            ):
                codes = (
                    payload.role_codes
                    if payload.role_codes is not None
                    else [r["code"] for r in target["roles"] if r["code"] != SUPER_ADMIN_ROLE]
                )
                roles = self._resolve_roles(session, codes)
                repo.replace_user_roles(
                    session, user_id, self._role_ids_with_flag(session, roles, new_flag)
                )

            row = self._load(session, user_id)
            after = _snapshot(row)
            if after != before:
                log_change(
                    session,
                    entity_type="user",
                    entity_id=user_id,
                    action="USER_UPDATED",
                    before=before,
                    after=after,
                    reason=payload.reason,
                )
        return _to_out(row)

    def deactivate(self, actor: CurrentUser, user_id: UUID, payload: ReasonIn) -> UserOut:
        if user_id == actor.id:
            raise PermissionDenied(
                "You cannot deactivate your own account", code="SELF_CHANGE_FORBIDDEN"
            )
        with self._uow.transaction(actor.id) as session:
            target = self._load(session, user_id, for_update=True)
            self._guard_target(actor, target, "deactivate")
            if not target["is_active"]:
                return _to_out(target)
            if target["is_super_admin"] and repo.other_active_super_admins(session, user_id) == 0:
                raise Conflict(
                    "The last active Super Admin cannot be deactivated", code="LAST_SUPER_ADMIN"
                )
            repo.set_flags(session, user_id, is_active=False)
            # Revokes sign-in (refresh) for the session; API calls are already 403 via is_active.
            self._auth.set_banned(user_id, True)
            row = self._load(session, user_id)
            log_change(
                session,
                entity_type="user",
                entity_id=user_id,
                action="USER_DEACTIVATED",
                before={"is_active": True},
                after={"is_active": False},
                reason=payload.reason,
            )
        log.info("user_deactivated", user_id=str(user_id), by=str(actor.id))
        return _to_out(row)

    def reactivate(self, actor: CurrentUser, user_id: UUID, payload: ReasonIn) -> UserOut:
        with self._uow.transaction(actor.id) as session:
            target = self._load(session, user_id, for_update=True)
            self._guard_target(actor, target, "reactivate")
            if target["is_active"]:
                return _to_out(target)
            repo.set_flags(session, user_id, is_active=True)
            self._auth.set_banned(user_id, False)
            row = self._load(session, user_id)
            log_change(
                session,
                entity_type="user",
                entity_id=user_id,
                action="USER_REACTIVATED",
                before={"is_active": False},
                after={"is_active": True},
                reason=payload.reason,
            )
        log.info("user_reactivated", user_id=str(user_id), by=str(actor.id))
        return _to_out(row)

    def reset_password(
        self, actor: CurrentUser, user_id: UUID, payload: ResetPasswordIn
    ) -> UserOut:
        if user_id == actor.id:
            raise PermissionDenied(
                "Change your own password from your profile", code="SELF_CHANGE_FORBIDDEN"
            )
        with self._uow.transaction(actor.id) as session:
            target = self._load(session, user_id, for_update=True)
            self._guard_target(actor, target, "reset the password of")
            repo.set_flags(session, user_id, must_change_password=True)
            self._auth.set_password(user_id, payload.temporary_password)
            row = self._load(session, user_id)
            log_change(
                session,
                entity_type="user",
                entity_id=user_id,
                action="PASSWORD_RESET",
                before=None,
                after={"must_change_password": True},
                reason=payload.reason,
            )
        log.info("user_password_reset", user_id=str(user_id), by=str(actor.id))
        return _to_out(row)

    def replace_overrides(
        self, actor: CurrentUser, user_id: UUID, payload: OverridesReplaceIn
    ) -> list[OverrideOut]:
        if user_id == actor.id:
            raise PermissionDenied(
                "You cannot change your own permission overrides", code="SELF_CHANGE_FORBIDDEN"
            )
        now = datetime.now(UTC)
        with self._uow.transaction(actor.id) as session:
            target = self._load(session, user_id, for_update=True)
            self._guard_target(actor, target, "change overrides of")
            catalogue = repo.permission_ids(session)
            seen: set[tuple[str, str]] = set()
            rows: list[dict[str, Any]] = []
            for o in payload.overrides:
                key = (o.module_code, o.action)
                if key not in catalogue:
                    raise ValidationFailed(
                        "Unknown permission",
                        code="UNKNOWN_PERMISSION",
                        details={"module_code": o.module_code, "action": o.action},
                    )
                if key in seen:
                    raise ValidationFailed(
                        "Duplicate permission in overrides",
                        code="DUPLICATE_OVERRIDE",
                        details={"module_code": o.module_code, "action": o.action},
                    )
                if o.expires_at is not None and o.expires_at <= now:
                    raise ValidationFailed(
                        "Expiry must be in the future",
                        code="OVERRIDE_EXPIRED",
                        details={"module_code": o.module_code, "action": o.action},
                    )
                seen.add(key)
                rows.append(
                    {
                        "pid": catalogue[key],
                        "effect": o.effect,
                        "reason": o.reason.strip(),
                        "expires_at": o.expires_at,
                    }
                )
            before = repo.list_overrides(session, user_id)
            repo.replace_overrides(session, user_id, rows)
            after = repo.list_overrides(session, user_id)
            log_change(
                session,
                entity_type="user_overrides",
                entity_id=user_id,
                action="OVERRIDES_REPLACED",
                before={"overrides": [_override_key(r) for r in before]},
                after={"overrides": [_override_key(r) for r in after]},
                reason="; ".join(sorted({o.reason.strip() for o in payload.overrides})) or None,
            )
        return [OverrideOut(**r) for r in after]

    def change_own_password(self, actor: CurrentUser, payload: ChangeOwnPasswordIn) -> None:
        with self._uow.transaction(actor.id) as session:
            self._load(session, actor.id, for_update=True)
            repo.set_flags(session, actor.id, must_change_password=False)
            self._auth.set_password(actor.id, payload.new_password)
            log_change(
                session,
                entity_type="user",
                entity_id=actor.id,
                action="PASSWORD_CHANGED",
                before=None,
                after={"must_change_password": False},
                reason="self-service",
            )
        log.info("user_password_changed", user_id=str(actor.id))

    # --- departments --------------------------------------------------------------------------

    def list_departments(self, actor: CurrentUser) -> list[DepartmentOut]:
        with self._uow.transaction(actor.id) as session:
            return [DepartmentOut(**r) for r in repo.list_departments(session)]

    def create_department(self, actor: CurrentUser, payload: DepartmentCreate) -> DepartmentOut:
        with self._uow.transaction(actor.id) as session:
            if repo.department_code_taken(session, payload.code):
                raise Conflict("A department with this code exists", code="DEPARTMENT_CODE_TAKEN")
            dept_id = repo.insert_department(session, payload.code, payload.name)
            log_change(
                session,
                entity_type="department",
                entity_id=dept_id,
                action="DEPARTMENT_CREATED",
                before=None,
                after={"code": payload.code, "name": payload.name},
                reason=None,
            )
            row = repo.get_department(session, dept_id)
        assert row is not None  # noqa: S101 - just inserted in this transaction
        return DepartmentOut(**row)

    def update_department(
        self, actor: CurrentUser, department_id: UUID, payload: DepartmentUpdate
    ) -> DepartmentOut:
        with self._uow.transaction(actor.id) as session:
            before = repo.get_department(session, department_id)
            if before is None:
                raise NotFound("Department not found", code="DEPARTMENT_NOT_FOUND")
            name = payload.name.strip() if payload.name else None
            repo.update_department(session, department_id, name=name, is_active=payload.is_active)
            after = repo.get_department(session, department_id)
            assert after is not None  # noqa: S101
            log_change(
                session,
                entity_type="department",
                entity_id=department_id,
                action="DEPARTMENT_UPDATED",
                before={"name": before["name"], "is_active": before["is_active"]},
                after={"name": after["name"], "is_active": after["is_active"]},
                reason=None,
            )
        return DepartmentOut(**after)


def _override_key(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "permission": f"{row['module_code']}.{row['action']}",
        "effect": row["effect"],
        "expires_at": row["expires_at"],
    }
