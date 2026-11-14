"""GET /api/v1/me: 401 without/invalid token, 403 inactive, 200 with permissions (§9.2-9.3)."""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import Connection

from tests.conftest import JwtFactory
from tests.integration.conftest import Override, UserFactory, fetch_all, publish_workflow


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _perm_set(body: dict) -> set[tuple[str, str]]:  # type: ignore[type-arg]
    return {(p["module_code"], p["action"]) for p in body["permissions"]}


def _role_perms(conn: Connection, role_code: str) -> set[tuple[str, str]]:
    rows = fetch_all(
        conn,
        """select p.module_code, p.action from public.role_permissions rp
             join public.roles r on r.id = rp.role_id
             join public.permissions p on p.id = rp.permission_id
            where r.code = :code""",
        code=role_code,
    )
    return {(r["module_code"], r["action"]) for r in rows}


async def test_me_without_token_is_401(client: AsyncClient) -> None:
    res = await client.get("/api/v1/me")
    assert res.status_code == 401
    err = res.json()["error"]
    assert err["code"] == "UNAUTHENTICATED"
    assert err["request_id"] == res.headers["X-Request-ID"]
    assert res.headers["WWW-Authenticate"] == "Bearer"


async def test_me_with_bad_signature_is_401(client: AsyncClient, make_token: JwtFactory) -> None:
    token = make_token(uuid.uuid4(), secret="not-the-local-secret-" + "x" * 32)
    res = await client.get("/api/v1/me", headers=_auth(token))
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "INVALID_TOKEN"


async def test_me_with_expired_token_is_401(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    uid = users.create()
    res = await client.get("/api/v1/me", headers=_auth(make_token(uid, expires_in=-120)))
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "TOKEN_EXPIRED"


async def test_me_for_inactive_user_is_403(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    uid = users.create(active=False, roles=["GATE_INWARD"])
    res = await client.get("/api/v1/me", headers=_auth(make_token(uid)))
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "ACCOUNT_INACTIVE"


async def test_me_for_unknown_profile_is_403(client: AsyncClient, make_token: JwtFactory) -> None:
    res = await client.get("/api/v1/me", headers=_auth(make_token(uuid.uuid4())))
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "ACCOUNT_INACTIVE"


async def test_me_returns_profile_roles_and_role_permissions(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    uid = users.create(roles=["GATE_INWARD"], full_name="Gate Person")
    res = await client.get("/api/v1/me", headers=_auth(make_token(uid)))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["profile"]["id"] == str(uid)
    assert body["profile"]["full_name"] == "Gate Person"
    assert body["profile"]["is_super_admin"] is False
    assert [r["code"] for r in body["roles"]] == ["GATE_INWARD"]
    assert _perm_set(body) == _role_perms(db_conn, "GATE_INWARD")
    assert body["step_codes"] == ["S1_GATE"]


async def test_me_applies_grant_deny_and_expiry(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    role_perms = _role_perms(db_conn, "GATE_INWARD")
    denied = sorted(role_perms)[0]
    past = datetime.now(UTC) - timedelta(days=1)
    future = datetime.now(UTC) + timedelta(days=1)
    uid = users.create(
        roles=["GATE_INWARD"],
        overrides=[
            Override(*denied, "deny"),
            Override("reports", "export", "grant", expires_at=future),
            Override("audit", "export", "grant", expires_at=past),  # expired: ignored
        ],
    )
    res = await client.get("/api/v1/me", headers=_auth(make_token(uid)))
    perms = _perm_set(res.json())
    assert denied not in perms
    assert ("reports", "export") in perms
    assert ("audit", "export") not in perms or ("audit", "export") in role_perms
    assert perms == (role_perms - {denied}) | {("reports", "export")}


async def test_me_super_admin_gets_full_catalogue(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    uid = users.create(super_admin=True)
    res = await client.get("/api/v1/me", headers=_auth(make_token(uid)))
    body = res.json()
    catalogue = fetch_all(db_conn, "select module_code, action from public.permissions")
    assert body["profile"]["is_super_admin"] is True
    assert _perm_set(body) == {(r["module_code"], r["action"]) for r in catalogue}
    assert {p["scope"] for p in body["permissions"]} == {"all"}


async def test_me_step_codes_come_from_published_step_assignments(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    assigned = users.create(roles=["GATE_INWARD"])
    other = users.create(roles=["ACCOUNTS"])
    admin = users.create(super_admin=True)
    publish_workflow(db_conn, step_code="S1_GATE", user_id=assigned)

    async def codes(uid: uuid.UUID) -> list[str]:
        res = await client.get("/api/v1/me", headers=_auth(make_token(uid)))
        return list(res.json()["step_codes"])

    assert "S1_GATE" in await codes(assigned)
    assert "S1_GATE" not in await codes(other)
    assert "S1_GATE" in await codes(admin)
