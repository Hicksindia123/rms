"""Role & permission administration service (master plan prompt P1-05).

Rules:
 * System roles (seeded) keep their code; only non-system roles without users or other
   references can be deleted (the DB trigger roles_protect_system repeats the system rule).
 * The SUPER_ADMIN marker role always holds the whole catalogue: its matrix is read-only.
 * No self-escalation: a user who is not Super Admin cannot change the permissions of a role
   they hold themselves.
 * Every change is written to config_change_log with before/after.
"""

from __future__ import annotations

from uuid import UUID

import structlog

from app.core.db import UnitOfWork
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.security import CurrentUser
from app.modules.roles import repository as repo
from app.modules.roles.schemas import (
    PermissionCatalogueOut,
    RoleCreate,
    RoleOut,
    RolePermissionOut,
    RolePermissionsReplaceIn,
    RoleUpdate,
)
from app.shared.change_log import log_change

log = structlog.get_logger("rms.roles")

SUPER_ADMIN_ROLE = "SUPER_ADMIN"


class RoleAdminService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def list_roles(self, actor: CurrentUser) -> list[RoleOut]:
        with self._uow.transaction(actor.id) as session:
            return [RoleOut(**r) for r in repo.list_roles(session)]

    def catalogue(self, actor: CurrentUser) -> list[PermissionCatalogueOut]:
        with self._uow.transaction(actor.id) as session:
            return [PermissionCatalogueOut(**r) for r in repo.permission_catalogue(session)]

    def role_permissions(self, actor: CurrentUser, role_id: UUID) -> list[RolePermissionOut]:
        with self._uow.transaction(actor.id) as session:
            if repo.get_role(session, role_id) is None:
                raise NotFound("Role not found", code="ROLE_NOT_FOUND")
            return [RolePermissionOut(**r) for r in repo.role_permissions(session, role_id)]

    def create_role(self, actor: CurrentUser, payload: RoleCreate) -> RoleOut:
        with self._uow.transaction(actor.id) as session:
            if repo.role_code_taken(session, payload.code):
                raise Conflict("A role with this code exists", code="ROLE_CODE_TAKEN")
            description = (payload.description or "").strip() or None
            role_id = repo.insert_role(session, payload.code, payload.name, description)
            log_change(
                session,
                entity_type="role",
                entity_id=role_id,
                action="ROLE_CREATED",
                before=None,
                after={"code": payload.code, "name": payload.name, "description": description},
                reason=None,
            )
            row = repo.get_role(session, role_id)
        assert row is not None  # noqa: S101 - inserted in this transaction
        return RoleOut(**row)

    def update_role(self, actor: CurrentUser, role_id: UUID, payload: RoleUpdate) -> RoleOut:
        sent = payload.model_fields_set
        with self._uow.transaction(actor.id) as session:
            before = repo.get_role(session, role_id)
            if before is None:
                raise NotFound("Role not found", code="ROLE_NOT_FOUND")
            fields: dict[str, str | None] = {}
            if "name" in sent and payload.name is not None:
                name = payload.name.strip()
                if not name:
                    raise ValidationFailed("Name cannot be empty", details={"field": "name"})
                fields["name"] = name
            if "description" in sent:
                fields["description"] = (payload.description or "").strip() or None
            repo.update_role(session, role_id, fields)
            after = repo.get_role(session, role_id)
            assert after is not None  # noqa: S101
            if fields:
                log_change(
                    session,
                    entity_type="role",
                    entity_id=role_id,
                    action="ROLE_UPDATED",
                    before={"name": before["name"], "description": before["description"]},
                    after={"name": after["name"], "description": after["description"]},
                    reason=None,
                )
        return RoleOut(**after)

    def delete_role(self, actor: CurrentUser, role_id: UUID) -> None:
        with self._uow.transaction(actor.id) as session:
            role = repo.get_role(session, role_id)
            if role is None:
                raise NotFound("Role not found", code="ROLE_NOT_FOUND")
            if role["is_system"]:
                raise Conflict("System roles cannot be deleted", code="ROLE_IS_SYSTEM")
            if role["user_count"]:
                raise Conflict(
                    "Remove this role from its users before deleting it",
                    code="ROLE_IN_USE",
                    details={"user_count": role["user_count"]},
                )
            refs = repo.role_reference_count(session, role_id)
            if refs:
                raise Conflict(
                    "This role is still used by workflow steps, menus, tasks or settings",
                    code="ROLE_IN_USE",
                    details={"references": refs},
                )
            permissions = repo.role_permissions(session, role_id)
            repo.delete_role(session, role_id)
            log_change(
                session,
                entity_type="role",
                entity_id=role_id,
                action="ROLE_DELETED",
                before={
                    "code": role["code"],
                    "name": role["name"],
                    "permissions": [f"{p['module_code']}.{p['action']}" for p in permissions],
                },
                after=None,
                reason=None,
            )
        log.info("role_deleted", role=role["code"], by=str(actor.id))

    def replace_permissions(
        self, actor: CurrentUser, role_id: UUID, payload: RolePermissionsReplaceIn
    ) -> list[RolePermissionOut]:
        with self._uow.transaction(actor.id) as session:
            role = repo.get_role(session, role_id)
            if role is None:
                raise NotFound("Role not found", code="ROLE_NOT_FOUND")
            if role["code"] == SUPER_ADMIN_ROLE:
                raise Conflict(
                    "The Super Admin role always holds every permission",
                    code="ROLE_MATRIX_LOCKED",
                )
            if not actor.is_super_admin and repo.actor_holds_role(session, actor.id, role_id):
                raise PermissionDenied(
                    "You cannot change the permissions of a role you hold",
                    code="SELF_CHANGE_FORBIDDEN",
                )
            catalogue = repo.permission_ids(session)
            rows: list[tuple[UUID, str]] = []
            seen: set[tuple[str, str]] = set()
            for p in payload.permissions:
                key = (p.module_code, p.action)
                if key not in catalogue:
                    raise ValidationFailed(
                        "Unknown permission",
                        code="UNKNOWN_PERMISSION",
                        details={"module_code": p.module_code, "action": p.action},
                    )
                if key in seen:
                    raise ValidationFailed(
                        "Duplicate permission",
                        code="DUPLICATE_PERMISSION",
                        details={"module_code": p.module_code, "action": p.action},
                    )
                seen.add(key)
                rows.append((catalogue[key], p.scope))
            before = repo.role_permissions(session, role_id)
            repo.replace_role_permissions(session, role_id, rows)
            after = repo.role_permissions(session, role_id)
            if before != after:
                log_change(
                    session,
                    entity_type="role_permissions",
                    entity_id=role_id,
                    action="ROLE_PERMISSIONS_REPLACED",
                    before={"role": role["code"], "permissions": before},
                    after={"role": role["code"], "permissions": after},
                    reason=(payload.reason or "").strip() or None,
                )
        log.info("role_permissions_replaced", role=role["code"], count=len(after))
        return [RolePermissionOut(**r) for r in after]
