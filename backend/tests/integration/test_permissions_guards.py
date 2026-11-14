"""require(module, action) and the Super Admin / system-guard boundary (§9.3, §4.2)."""

import uuid

from httpx import AsyncClient
from sqlalchemy import Connection
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import PermissionDenied
from app.core.permissions import assert_step_actor
from app.core.security import CurrentUser
from tests.conftest import JwtFactory
from tests.integration.conftest import (
    Override,
    UserFactory,
    fetch_all,
    publish_workflow,
)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_require_denies_user_without_permission(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    uid = users.create()  # no roles, no overrides
    res = await client.get("/api/v1/test/users-view", headers=_auth(make_token(uid)))
    assert res.status_code == 403
    err = res.json()["error"]
    assert err["code"] == "PERMISSION_DENIED"
    assert err["details"] == {"module": "users", "action": "view"}


async def test_require_allows_super_admin(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    uid = users.create(super_admin=True)
    res = await client.get("/api/v1/test/users-view", headers=_auth(make_token(uid)))
    assert res.status_code == 200
    assert res.json() == {"user_id": str(uid)}


async def test_require_honours_grant_override(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    uid = users.create(overrides=[Override("users", "view", "grant")])
    res = await client.get("/api/v1/test/users-view", headers=_auth(make_token(uid)))
    assert res.status_code == 200


async def test_super_admin_cannot_bypass_service_system_guard(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    uid = users.create(super_admin=True)
    res = await client.post("/api/v1/test/guard/g16", headers=_auth(make_token(uid)))
    assert res.status_code == 409
    err = res.json()["error"]
    assert err["code"] == "G-16"
    assert err["details"]["guard"] == "G-16"


async def test_super_admin_cannot_bypass_db_system_guard(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    uid = users.create(super_admin=True)
    version_id = publish_workflow(db_conn, step_code="S1_GATE", user_id=uid)
    res = await client.post(f"/api/v1/test/guard/g18/{version_id}", headers=_auth(make_token(uid)))
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "G-18"
    snapshot = fetch_all(
        db_conn, "select snapshot from public.workflow_versions where id = :id", id=version_id
    )
    assert snapshot == [{"snapshot": {}}]  # unchanged: the '{}' set at publish time


def _user(uid: uuid.UUID, *, super_admin: bool = False) -> CurrentUser:
    return CurrentUser(uid, None, "T", None, None, super_admin, None, ())


def test_assert_step_actor(
    users: UserFactory, db_conn: Connection, session_factory: sessionmaker[Session]
) -> None:
    actor = users.create(roles=["INWARD_VERIFIER"])
    outsider = users.create(roles=["INWARD_VERIFIER"])
    admin = users.create(super_admin=True)
    publish_workflow(db_conn, step_code="S1_UNBOX", role_code="INWARD_VERIFIER")
    publish_workflow(db_conn, step_code="S1_GATE", user_id=actor, assignment_type="APPROVE")

    with session_factory() as session, session.begin():
        assert_step_actor(session, _user(actor), "S1_UNBOX")  # via role
        assert_step_actor(session, _user(outsider), "S1_UNBOX")  # same role
        assert_step_actor(session, _user(actor), "S1_GATE", "APPROVE")  # direct user assignment
        assert_step_actor(session, _user(admin, super_admin=True), "S6_CLOSE")
        try:
            assert_step_actor(session, _user(outsider), "S1_GATE", "APPROVE")
        except PermissionDenied as exc:
            assert exc.code == "NOT_STEP_ACTOR"
        else:
            raise AssertionError("outsider must not be a step actor for S1_GATE/APPROVE")
