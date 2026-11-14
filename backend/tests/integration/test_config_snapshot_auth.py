"""Config snapshot endpoints require an active signed-in user (docs/PRODUCTION_AUDIT.md §6,
Phase 1, 2026-11-14). They expose business configuration (forms, option lists, workflow, print
templates), so anonymous and inactive callers are rejected; any active user may read them
because every operational role renders these snapshots."""

import pytest
from httpx import AsyncClient

from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory

ENDPOINTS = [
    ("GET", "/api/v1/config/forms/S1_GATE_INWARD/published"),
    ("GET", "/api/v1/config/workflow/RMS_STANDARD/published"),
    ("GET", "/api/v1/config/templates/AC_ACTIONS_SLIP/published"),
    ("POST", "/api/v1/config/forms/S1_GATE_INWARD/validate-submission"),
]


async def _call(client: AsyncClient, method: str, path: str, headers: dict[str, str]) -> int:
    if method == "POST":
        res = await client.post(path, json={"values": {}}, headers=headers)
    else:
        res = await client.get(path, headers=headers)
    return res.status_code


@pytest.mark.parametrize(("method", "path"), ENDPOINTS)
async def test_anonymous_caller_is_rejected(client: AsyncClient, method: str, path: str) -> None:
    assert await _call(client, method, path, {}) == 401


@pytest.mark.parametrize(("method", "path"), ENDPOINTS)
async def test_inactive_user_is_rejected(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, method: str, path: str
) -> None:
    token = make_token(users.create(active=False))
    assert await _call(client, method, path, {"Authorization": f"Bearer {token}"}) == 403


@pytest.mark.parametrize(("method", "path"), ENDPOINTS)
async def test_any_active_user_is_allowed(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, method: str, path: str
) -> None:
    token = make_token(users.create())  # no roles: these snapshots need no specific permission
    assert await _call(client, method, path, {"Authorization": f"Bearer {token}"}) == 200


async def test_public_settings_stay_public(client: AsyncClient) -> None:
    """The login screen needs branding before sign-in: intentionally unauthenticated."""
    assert (await client.get("/api/v1/config/settings/public")).status_code == 200
