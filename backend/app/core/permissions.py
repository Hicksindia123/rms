"""Effective permissions, the `require(module, action)` dependency and step-actor checks (§9.3).

effective permissions = role permissions + grant overrides - deny overrides
  * deny wins over every grant;
  * an override whose `expires_at` has passed is ignored (both grant and deny);
  * when several roles grant the same permission, the widest scope wins (own < department < all);
  * a grant override carries scope `all` (overrides have no scope column; docs/DECISIONS.md).

Super Admin (`profiles.is_super_admin`) passes every permission and step-actor check, but NOT the
system guards G-01…G-18: those raise `SystemGuardError` from services and DB triggers, and no code
in this module catches or bypasses them.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core import identity_repository as repo
from app.core.db import UowDep
from app.core.errors import PermissionDenied, SystemGuardError, ValidationFailed
from app.core.identity_repository import OverrideRow, RolePermissionRow
from app.core.security import CurrentUser, CurrentUserDep

__all__ = [
    "EffectivePermissions",
    "SystemGuardError",
    "assert_step_actor",
    "compute_effective_permissions",
    "effective_permissions",
    "get_effective_permissions",
    "require",
    "step_codes_for",
]

Scope = Literal["own", "department", "all"]
AssignmentType = Literal["PERFORM", "APPROVE", "VIEW"]
PermissionKey = tuple[str, str]  # (module_code, action)

_SCOPE_RANK: dict[str, int] = {"own": 0, "department": 1, "all": 2}
_ASSIGNMENT_TYPES = frozenset({"PERFORM", "APPROVE", "VIEW"})


@dataclass(frozen=True, slots=True)
class EffectivePermissions:
    is_super_admin: bool
    grants: Mapping[PermissionKey, str] = field(default_factory=dict)

    def allows(self, module_code: str, action: str) -> bool:
        return self.is_super_admin or (module_code, action) in self.grants

    def scope(self, module_code: str, action: str) -> str | None:
        if self.is_super_admin:
            return "all"
        return self.grants.get((module_code, action))


def compute_effective_permissions(
    role_permissions: Iterable[RolePermissionRow],
    overrides: Iterable[OverrideRow],
    *,
    now: datetime,
) -> dict[PermissionKey, str]:
    """Pure function: role permissions + live grants - live denies, widest scope per key."""
    granted: dict[PermissionKey, str] = {}

    def add(key: PermissionKey, scope: str) -> None:
        current = granted.get(key)
        if current is None or _SCOPE_RANK[scope] > _SCOPE_RANK[current]:
            granted[key] = scope

    for rp in role_permissions:
        add((rp.module_code, rp.action), rp.scope)

    live = [o for o in overrides if o.expires_at is None or o.expires_at > now]
    for o in live:
        if o.effect == "grant":
            add((o.module_code, o.action), "all")
    for o in live:
        if o.effect == "deny":
            granted.pop((o.module_code, o.action), None)
    return granted


def effective_permissions(
    session: Session,
    user_id: UUID,
    *,
    is_super_admin: bool,
    now: datetime | None = None,
) -> EffectivePermissions:
    if is_super_admin:
        catalogue = repo.list_permission_catalogue(session)
        return EffectivePermissions(True, {key: "all" for key in catalogue})
    grants = compute_effective_permissions(
        repo.get_role_permissions(session, user_id),
        repo.get_permission_overrides(session, user_id),
        now=now or datetime.now(UTC),
    )
    return EffectivePermissions(False, grants)


def get_effective_permissions(
    request: Request, user: CurrentUserDep, uow: UowDep
) -> EffectivePermissions:
    """Per-request cache: computed at most once per request and user."""
    cache: dict[UUID, EffectivePermissions] | None = getattr(
        request.state, "effective_permissions_cache", None
    )
    if cache is None:
        cache = {}
        request.state.effective_permissions_cache = cache
    cached = cache.get(user.id)
    if cached is None:
        with uow.transaction(user.id) as session:
            cached = effective_permissions(session, user.id, is_super_admin=user.is_super_admin)
        cache[user.id] = cached
    return cached


EffectivePermissionsDep = Annotated[EffectivePermissions, Depends(get_effective_permissions)]


def require(module_code: str, action: str) -> Callable[..., CurrentUser]:
    """Dependency factory: `Depends(require("users", "view"))` returns the authorised user."""

    def dependency(user: CurrentUserDep, perms: EffectivePermissionsDep) -> CurrentUser:
        if not perms.allows(module_code, action):
            raise PermissionDenied(
                f"Missing permission {module_code}.{action}",
                details={"module": module_code, "action": action},
            )
        return user

    dependency.__name__ = f"require_{module_code}_{action}"
    return dependency


def step_codes_for(
    session: Session, user: CurrentUser, assignment_type: AssignmentType = "PERFORM"
) -> list[str]:
    """Workflow step codes the user is assigned to (Super Admin: every published step)."""
    if user.is_super_admin:
        return repo.list_published_step_codes(session)
    return repo.list_assigned_step_codes(session, user.id, assignment_type)


def assert_step_actor(
    session: Session,
    user: CurrentUser,
    step_code: str,
    assignment_type: AssignmentType = "PERFORM",
) -> None:
    """Raise PermissionDenied unless step_assignments lets the user act on the step."""
    if assignment_type not in _ASSIGNMENT_TYPES:
        raise ValidationFailed(f"Unknown assignment type {assignment_type!r}")
    if user.is_super_admin:
        return
    if step_code not in repo.list_assigned_step_codes(session, user.id, assignment_type):
        raise PermissionDenied(
            f"You are not assigned to {assignment_type} step {step_code}",
            code="NOT_STEP_ACTOR",
            details={"step_code": step_code, "assignment_type": assignment_type},
        )
