"""Permission arithmetic: role union, widest scope, grant/deny overrides, expiry (§9.3)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import PermissionDenied, SystemGuardError, SystemGuardViolation, enforce_guard
from app.core.identity_repository import OverrideRow, RolePermissionRow
from app.core.permissions import EffectivePermissions, compute_effective_permissions, require
from app.core.security import CurrentUser

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def rp(module: str, action: str, scope: str = "all") -> RolePermissionRow:
    return RolePermissionRow(module, action, scope)


def ov(module: str, action: str, effect: str, expires_at: datetime | None = None) -> OverrideRow:
    return OverrideRow(module, action, effect, expires_at)


def test_union_of_roles_keeps_widest_scope() -> None:
    result = compute_effective_permissions(
        [
            rp("goods_slips", "view", "own"),
            rp("goods_slips", "view", "department"),
            rp("reports", "view", "all"),
        ],
        [],
        now=NOW,
    )
    assert result == {("goods_slips", "view"): "department", ("reports", "view"): "all"}


def test_grant_override_adds_permission_with_all_scope() -> None:
    result = compute_effective_permissions([], [ov("users", "view", "grant")], now=NOW)
    assert result == {("users", "view"): "all"}


def test_deny_override_wins_over_role_and_grant() -> None:
    result = compute_effective_permissions(
        [rp("users", "view")],
        [ov("users", "view", "grant"), ov("users", "view", "deny")],
        now=NOW,
    )
    assert result == {}


def test_expired_overrides_are_ignored() -> None:
    past = NOW - timedelta(seconds=1)
    result = compute_effective_permissions(
        [rp("users", "view")],
        [ov("users", "view", "deny", past), ov("reports", "export", "grant", past)],
        now=NOW,
    )
    assert result == {("users", "view"): "all"}


def test_override_expiring_exactly_now_is_expired() -> None:
    result = compute_effective_permissions([], [ov("users", "view", "grant", NOW)], now=NOW)
    assert result == {}


def test_future_expiry_is_live() -> None:
    future = NOW + timedelta(hours=1)
    result = compute_effective_permissions(
        [rp("users", "view")], [ov("users", "view", "deny", future)], now=NOW
    )
    assert result == {}


def test_super_admin_allows_everything() -> None:
    perms = EffectivePermissions(is_super_admin=True)
    assert perms.allows("anything", "configure")
    assert perms.scope("anything", "configure") == "all"


def _user(super_admin: bool) -> CurrentUser:
    return CurrentUser(uuid.uuid4(), None, "T", None, None, super_admin, None, ())


def test_require_dependency_checks_effective_permissions() -> None:
    dep = require("users", "view")
    user = _user(False)
    assert dep(user, EffectivePermissions(False, {("users", "view"): "all"})) is user
    with pytest.raises(PermissionDenied) as exc:
        dep(user, EffectivePermissions(False, {}))
    assert exc.value.code == "PERMISSION_DENIED"
    admin = _user(True)
    assert dep(admin, EffectivePermissions(True)) is admin


def test_system_guards_are_not_permission_checks() -> None:
    # enforce_guard takes no user at all: there is nothing a Super Admin could short-circuit.
    with pytest.raises(SystemGuardError) as exc:
        enforce_guard(False, "G-04", "Not Allowed stock cannot enter a functional location")
    assert exc.value.code == "G-04"
    assert exc.value.status_code == 409
    assert SystemGuardError is SystemGuardViolation
    assert not issubclass(SystemGuardViolation, PermissionDenied)
    enforce_guard(True, "G-04", "ok")


def test_unknown_guard_code_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown system guard"):
        # G-19..G-22 are real (change-plan Phases 5-8); G-23 is the next unused code.
        SystemGuardViolation("G-23", "nope")
