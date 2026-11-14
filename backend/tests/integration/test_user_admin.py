"""User, role & permission administration (master plan prompt P1-05; production audit B10).

The Supabase Auth admin API is replaced by a fake that writes auth.users on the test connection,
so the real profile trigger (rms_activate) runs. Everything else is the real stack.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import get_session_factory
from app.shared.auth_admin import CreatedAuthUser, get_auth_admin
from tests.conftest import JwtFactory
from tests.integration.conftest import Override, UserFactory, as_admin, build_test_app

API = "/api/v1"
PASSWORD = "Start1234"  # noqa: S105 - test-only initial password


class FakeAuthAdmin:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn
        self.calls: list[tuple[str, Any]] = []

    def create_user(
        self, *, email: str, password: str, user_metadata: dict[str, Any]
    ) -> CreatedAuthUser:
        user_id = uuid.uuid4()
        as_admin(self.conn).execute(
            text(
                "insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data)"
                " values (:id, :email, cast(:app as jsonb), cast(:meta as jsonb))"
            ),
            {
                "id": user_id,
                "email": email,
                "app": json.dumps({"rms_activate": True}),
                "meta": json.dumps(user_metadata),
            },
        )
        self.calls.append(("create_user", email))
        return CreatedAuthUser(id=user_id)

    def set_password(self, user_id: uuid.UUID, password: str) -> None:
        self.calls.append(("set_password", user_id))

    def set_banned(self, user_id: uuid.UUID, banned: bool) -> None:
        self.calls.append(("set_banned", (user_id, banned)))


@pytest.fixture
def fake_auth(db_conn: Connection) -> FakeAuthAdmin:
    return FakeAuthAdmin(db_conn)


@pytest.fixture
async def api(
    session_factory: sessionmaker[Session], fake_auth: FakeAuthAdmin
) -> AsyncIterator[AsyncClient]:
    app = build_test_app()
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_auth_admin] = lambda: fake_auth
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _user_admin(users: UserFactory, *, extra: tuple[str, ...] = ()) -> uuid.UUID:
    """A non-Super-Admin user administrator (permissions via grant overrides)."""
    grants = [("users", a) for a in ("view", "create", "edit", "configure")] + [
        ("roles", a) for a in extra
    ]
    return users.create(overrides=[Override(m, a, "grant") for m, a in grants])


def _new_user(email: str, **kw: Any) -> dict[str, Any]:
    return {
        "email": email,
        "full_name": "New Person",
        "role_codes": ["GATE_INWARD"],
        "initial_password": PASSWORD,
        **kw,
    }


# --- create / login / forced password change ------------------------------------------------


async def test_admin_creates_user_who_must_change_password_first(
    api: AsyncClient, users: UserFactory, make_token: JwtFactory, fake_auth: FakeAuthAdmin
) -> None:
    admin = make_token(users.create(super_admin=True))
    res = await api.post(
        f"{API}/admin/users",
        json=_new_user("new.person@example.test", employee_code="EMP-9001"),
        headers=_h(admin),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["is_active"] is True
    assert body["must_change_password"] is True
    assert [r["code"] for r in body["roles"]] == ["GATE_INWARD"]
    assert fake_auth.calls[0] == ("create_user", "new.person@example.test")

    token = make_token(body["id"])
    me = await api.get(f"{API}/me", headers=_h(token))
    assert me.status_code == 200
    assert me.json()["profile"]["must_change_password"] is True

    blocked = await api.get(f"{API}/me/journey", headers=_h(token))
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"

    weak = await api.post(f"{API}/me/password", json={"new_password": "short"}, headers=_h(token))
    assert weak.status_code == 422

    changed = await api.post(
        f"{API}/me/password", json={"new_password": "Better12345"}, headers=_h(token)
    )
    assert changed.status_code == 204
    assert (await api.get(f"{API}/me/journey", headers=_h(token))).status_code == 200


async def test_duplicate_email_and_unknown_role_are_rejected(
    api: AsyncClient, users: UserFactory, make_token: JwtFactory, fake_auth: FakeAuthAdmin
) -> None:
    admin = make_token(users.create(super_admin=True))
    first = await api.post(
        f"{API}/admin/users", json=_new_user("dup@example.test"), headers=_h(admin)
    )
    assert first.status_code == 201
    dup = await api.post(
        f"{API}/admin/users", json=_new_user("DUP@example.test"), headers=_h(admin)
    )
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "EMAIL_TAKEN"
    bad = await api.post(
        f"{API}/admin/users",
        json=_new_user("other@example.test", role_codes=["NOPE"]),
        headers=_h(admin),
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "UNKNOWN_ROLE"
    via_role = await api.post(
        f"{API}/admin/users",
        json=_new_user("sa@example.test", role_codes=["SUPER_ADMIN"]),
        headers=_h(admin),
    )
    assert via_role.status_code == 422
    # Only the first request reached the auth service.
    assert [c for c in fake_auth.calls if c[0] == "create_user"] == [
        ("create_user", "dup@example.test")
    ]


# --- deactivate / reactivate -----------------------------------------------------------------


async def test_deactivation_blocks_api_immediately_and_reactivation_restores(
    api: AsyncClient, users: UserFactory, make_token: JwtFactory, fake_auth: FakeAuthAdmin
) -> None:
    admin = make_token(users.create(super_admin=True))
    target = users.create(roles=["GATE_INWARD"])
    target_token = make_token(target)
    assert (await api.get(f"{API}/me", headers=_h(target_token))).status_code == 200

    no_reason = await api.post(f"{API}/admin/users/{target}/deactivate", json={}, headers=_h(admin))
    assert no_reason.status_code == 422

    res = await api.post(
        f"{API}/admin/users/{target}/deactivate", json={"reason": "left company"}, headers=_h(admin)
    )
    assert res.status_code == 200 and res.json()["is_active"] is False
    assert ("set_banned", (target, True)) in fake_auth.calls
    denied = await api.get(f"{API}/me", headers=_h(target_token))
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "ACCOUNT_INACTIVE"

    res = await api.post(
        f"{API}/admin/users/{target}/reactivate", json={"reason": "rejoined"}, headers=_h(admin)
    )
    assert res.status_code == 200 and res.json()["is_active"] is True
    assert ("set_banned", (target, False)) in fake_auth.calls
    assert (await api.get(f"{API}/me", headers=_h(target_token))).status_code == 200


async def test_change_log_records_actor_and_reason(
    api: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    admin_id = users.create(super_admin=True)
    target = users.create(roles=["GATE_INWARD"])
    res = await api.post(
        f"{API}/admin/users/{target}/deactivate",
        json={"reason": "audit me"},
        headers=_h(make_token(admin_id)),
    )
    assert res.status_code == 200
    row = (
        as_admin(db_conn)
        .execute(
            text(
                "select changed_by, reason, action from public.config_change_log"
                " where entity_type = 'user' and entity_id = :id order by id desc limit 1"
            ),
            {"id": str(target)},
        )
        .one()
    )
    assert row.changed_by == admin_id and row.reason == "audit me"
    assert row.action == "USER_DEACTIVATED"


async def test_self_protection(
    api: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    admin_id = users.create(super_admin=True)
    admin = make_token(admin_id)
    deact = await api.post(
        f"{API}/admin/users/{admin_id}/deactivate", json={"reason": "oops"}, headers=_h(admin)
    )
    assert deact.status_code == 403
    assert deact.json()["error"]["code"] == "SELF_CHANGE_FORBIDDEN"
    demote = await api.patch(
        f"{API}/admin/users/{admin_id}", json={"is_super_admin": False}, headers=_h(admin)
    )
    assert demote.status_code == 403
    ua = _user_admin(users)
    own = await api.put(
        f"{API}/admin/users/{ua}/overrides",
        json={
            "overrides": [
                {
                    "module_code": "roles",
                    "action": "configure",
                    "effect": "grant",
                    "reason": "escalate",
                }
            ]
        },
        headers=_h(make_token(ua)),
    )
    assert own.status_code == 403
    assert own.json()["error"]["code"] == "SELF_CHANGE_FORBIDDEN"


# --- Super Admin only ------------------------------------------------------------------------


async def test_only_super_admin_grants_or_touches_super_admin(
    api: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    ua = make_token(_user_admin(users))
    create_sa = await api.post(
        f"{API}/admin/users",
        json=_new_user("wannabe@example.test", is_super_admin=True),
        headers=_h(ua),
    )
    assert create_sa.status_code == 403
    assert create_sa.json()["error"]["code"] == "SUPER_ADMIN_REQUIRED"

    sa_target = users.create(super_admin=True)
    for method, path, body in (
        ("post", f"/admin/users/{sa_target}/deactivate", {"reason": "nope"}),
        ("patch", f"/admin/users/{sa_target}", {"full_name": "Renamed"}),
        (
            "post",
            f"/admin/users/{sa_target}/reset-password",
            {"temporary_password": "Temp12345", "reason": "nope"},
        ),
    ):
        res = await getattr(api, method)(f"{API}{path}", json=body, headers=_h(ua))
        assert res.status_code == 403, (path, res.text)

    plain = users.create(roles=["GATE_INWARD"])
    promote = await api.patch(
        f"{API}/admin/users/{plain}", json={"is_super_admin": True}, headers=_h(ua)
    )
    assert promote.status_code == 403

    sa = make_token(users.create(super_admin=True))
    ok = await api.patch(
        f"{API}/admin/users/{plain}", json={"is_super_admin": True}, headers=_h(sa)
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["is_super_admin"] is True
    assert "SUPER_ADMIN" in [r["code"] for r in ok.json()["roles"]]


async def test_non_admin_gets_403_on_every_admin_endpoint(
    api: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    token = make_token(users.create(roles=["GATE_INWARD"]))
    some = uuid.uuid4()
    calls = [
        ("get", "/admin/users", None),
        ("post", "/admin/users", _new_user("x@example.test")),
        ("get", f"/admin/users/{some}", None),
        ("patch", f"/admin/users/{some}", {"full_name": "X"}),
        ("post", f"/admin/users/{some}/deactivate", {"reason": "xxx"}),
        ("post", f"/admin/users/{some}/reactivate", {"reason": "xxx"}),
        (
            "post",
            f"/admin/users/{some}/reset-password",
            {"temporary_password": "Temp12345", "reason": "xxx"},
        ),
        ("get", f"/admin/users/{some}/effective-permissions", None),
        ("get", f"/admin/users/{some}/overrides", None),
        ("put", f"/admin/users/{some}/overrides", {"overrides": []}),
        ("get", "/admin/departments", None),
        ("post", "/admin/departments", {"code": "X_DEPT", "name": "X"}),
        ("patch", f"/admin/departments/{some}", {"name": "X"}),
        ("get", "/admin/roles", None),
        ("post", "/admin/roles", {"code": "X_ROLE", "name": "X"}),
        ("patch", f"/admin/roles/{some}", {"name": "X"}),
        ("delete", f"/admin/roles/{some}", None),
        ("get", "/admin/permissions", None),
        ("get", f"/admin/roles/{some}/permissions", None),
        ("put", f"/admin/roles/{some}/permissions", {"permissions": []}),
    ]
    for method, path, body in calls:
        kwargs: dict[str, Any] = {"headers": _h(token)}
        if body is not None:
            kwargs["json"] = body
        res = await getattr(api, method)(f"{API}{path}", **kwargs)
        assert res.status_code == 403, (method, path, res.status_code)


# --- overrides / matrix ----------------------------------------------------------------------


async def test_deny_override_beats_role_grant_and_expired_override_is_ignored(
    api: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    admin = make_token(users.create(super_admin=True))
    target = users.create(roles=["GATE_INWARD"])

    def perms(body: dict[str, Any]) -> set[str]:
        return {f"{p['module_code']}.{p['action']}" for p in body["permissions"]}

    base = await api.get(f"{API}/admin/users/{target}/effective-permissions", headers=_h(admin))
    assert "goods_slips.create" in perms(base.json())

    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    rejected = await api.put(
        f"{API}/admin/users/{target}/overrides",
        json={
            "overrides": [
                {
                    "module_code": "reports",
                    "action": "view",
                    "effect": "grant",
                    "reason": "temp",
                    "expires_at": past,
                }
            ]
        },
        headers=_h(admin),
    )
    assert rejected.status_code == 422

    res = await api.put(
        f"{API}/admin/users/{target}/overrides",
        json={
            "overrides": [
                {
                    "module_code": "goods_slips",
                    "action": "create",
                    "effect": "deny",
                    "reason": "suspended from gate entry",
                }
            ]
        },
        headers=_h(admin),
    )
    assert res.status_code == 200, res.text
    after = await api.get(f"{API}/admin/users/{target}/effective-permissions", headers=_h(admin))
    assert "goods_slips.create" not in perms(after.json())

    # An override that expired after it was saved is ignored.
    expired = users.create(
        roles=["GATE_INWARD"],
        overrides=[
            Override("goods_slips", "create", "deny", datetime.now(UTC) - timedelta(hours=1))
        ],
    )
    still = await api.get(f"{API}/admin/users/{expired}/effective-permissions", headers=_h(admin))
    assert "goods_slips.create" in perms(still.json())
    listed = await api.get(f"{API}/admin/users/{expired}/overrides", headers=_h(admin))
    assert listed.json()[0]["is_expired"] is True


async def test_role_matrix_update_changes_backend_enforcement(
    api: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    admin = make_token(users.create(super_admin=True))
    created = await api.post(
        f"{API}/admin/roles",
        json={"code": "REPORT_READER", "name": "Report Reader"},
        headers=_h(admin),
    )
    assert created.status_code == 201, created.text
    role_id = created.json()["id"]
    member = users.create(roles=["REPORT_READER"])
    member_token = make_token(member)
    assert (await api.get(f"{API}/admin/departments", headers=_h(member_token))).status_code == 403

    res = await api.put(
        f"{API}/admin/roles/{role_id}/permissions",
        json={
            "permissions": [{"module_code": "users", "action": "view", "scope": "all"}],
            "reason": "test",
        },
        headers=_h(admin),
    )
    assert res.status_code == 200, res.text
    assert (await api.get(f"{API}/admin/departments", headers=_h(member_token))).status_code == 200

    in_use = await api.delete(f"{API}/admin/roles/{role_id}", headers=_h(admin))
    assert in_use.status_code == 409


async def test_role_rules(api: AsyncClient, users: UserFactory, make_token: JwtFactory) -> None:
    admin = make_token(users.create(super_admin=True))
    roles = {r["code"]: r for r in (await api.get(f"{API}/admin/roles", headers=_h(admin))).json()}
    locked = await api.put(
        f"{API}/admin/roles/{roles['SUPER_ADMIN']['id']}/permissions",
        json={"permissions": []},
        headers=_h(admin),
    )
    assert locked.status_code == 409
    system = await api.delete(f"{API}/admin/roles/{roles['GATE_INWARD']['id']}", headers=_h(admin))
    assert system.status_code == 409
    assert system.json()["error"]["code"] == "ROLE_IS_SYSTEM"

    # No self-escalation through a role one holds.
    holder = users.create(
        roles=["GATE_INWARD"],
        overrides=[Override("roles", "configure", "grant"), Override("roles", "view", "grant")],
    )
    own_role = await api.put(
        f"{API}/admin/roles/{roles['GATE_INWARD']['id']}/permissions",
        json={"permissions": [{"module_code": "users", "action": "edit"}]},
        headers=_h(make_token(holder)),
    )
    assert own_role.status_code == 403

    tmp = await api.post(
        f"{API}/admin/roles", json={"code": "TEMP_ROLE", "name": "Temp"}, headers=_h(admin)
    )
    gone = await api.delete(f"{API}/admin/roles/{tmp.json()['id']}", headers=_h(admin))
    assert gone.status_code == 204


async def test_reset_password_and_departments(
    api: AsyncClient, users: UserFactory, make_token: JwtFactory, fake_auth: FakeAuthAdmin
) -> None:
    admin = make_token(users.create(super_admin=True))
    target = users.create(roles=["GATE_INWARD"])
    res = await api.post(
        f"{API}/admin/users/{target}/reset-password",
        json={"temporary_password": "Temp12345", "reason": "forgot"},
        headers=_h(admin),
    )
    assert res.status_code == 200 and res.json()["must_change_password"] is True
    assert ("set_password", target) in fake_auth.calls

    dept = await api.post(
        f"{API}/admin/departments",
        json={"code": "quality_lab", "name": "Quality Lab"},
        headers=_h(admin),
    )
    assert dept.status_code == 201 and dept.json()["code"] == "QUALITY_LAB"
    dup = await api.post(
        f"{API}/admin/departments", json={"code": "QUALITY_LAB", "name": "Again"}, headers=_h(admin)
    )
    assert dup.status_code == 409
    moved = await api.patch(
        f"{API}/admin/users/{target}", json={"department_id": dept.json()["id"]}, headers=_h(admin)
    )
    assert moved.json()["department"]["code"] == "QUALITY_LAB"
    off = await api.patch(
        f"{API}/admin/departments/{dept.json()['id']}",
        json={"is_active": False},
        headers=_h(admin),
    )
    assert off.json()["is_active"] is False

    listed = await api.get(
        f"{API}/admin/users", params={"search": "test-", "status": "active"}, headers=_h(admin)
    )
    assert listed.status_code == 200 and listed.json()["total"] >= 1
