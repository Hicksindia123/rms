"""Authentication and Session Hardening Security Suite (§9.1, §9.2, prompt P4-05).

Tests:
1. Immediate lockout on deactivated users (403 ACCOUNT_INACTIVE).
2. Token expiry enforcement (401 TOKEN_EXPIRED).
3. Tampered signature rejection (401 INVALID_TOKEN).
4. Mandatory security response headers (X-Content-Type-Options, X-Frame-Options, CSP).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text

from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin

pytestmark = pytest.mark.asyncio


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_immediate_lockout_on_deactivated_user(
    client: AsyncClient, db_conn: Connection, users: UserFactory, make_token: JwtFactory
) -> None:
    """A user who is deactivated immediately receives 403 ACCOUNT_INACTIVE on their next request."""
    conn = as_admin(db_conn)
    user_id = users.create(roles=["GATE_INWARD"], active=True)
    token = make_token(user_id)

    # 1. While active, the request succeeds
    res_active = await client.get("/api/v1/gs/gate-form", headers=_auth(token))
    assert res_active.status_code == 200, res_active.text

    # 2. Deactivate the user profile directly (maintenance path: no actor). The shared test
    #    connection still carries the last request's SET LOCAL app.user_id = this user, which the
    #    P1-05 self-deactivation guard would (correctly) reject.
    users.set_actor(None)
    conn.execute(
        text("update public.profiles set is_active = false where id = :uid"),
        {"uid": user_id},
    )

    # 3. Next request with the exact same valid JWT is immediately locked out
    res_inactive = await client.get("/api/v1/gs/gate-form", headers=_auth(token))
    assert res_inactive.status_code == 403
    assert res_inactive.json()["error"]["code"] == "ACCOUNT_INACTIVE"


async def test_expired_token_rejected(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    """Expired access tokens are rejected with 401 TOKEN_EXPIRED."""
    user_id = users.create(roles=["GATE_INWARD"])
    expired_token = make_token(user_id, expires_in=-120)

    res = await client.get("/api/v1/gs/gate-form", headers=_auth(expired_token))
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "TOKEN_EXPIRED"


async def test_tampered_token_rejected(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    """Tokens signed with wrong secret or altered signatures are rejected with 401 INVALID_TOKEN."""
    user_id = users.create(roles=["GATE_INWARD"])
    wrong_token = make_token(
        user_id, secret="wrong-secret-key-that-does-not-match-at-all-1234567890"
    )

    res = await client.get("/api/v1/gs/gate-form", headers=_auth(wrong_token))
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "INVALID_TOKEN"


async def test_security_headers_present(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    """All API responses must include defensive security headers."""
    admin_id = users.create(super_admin=True)
    token = make_token(admin_id)

    res = await client.get("/api/v1/health", headers=_auth(token))
    assert res.status_code == 200

    headers = res.headers
    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("x-frame-options") == "DENY"
    assert "no-referrer" in headers.get("referrer-policy", "")
    assert "camera=()" in headers.get("permissions-policy", "")
    assert "default-src 'none'" in headers.get("content-security-policy", "")
