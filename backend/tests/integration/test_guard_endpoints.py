"""Integration tests for system guard test endpoints (prompt P2-01).

Guarantees that every non-bypassable guard G-01..G-18 returns a 422 envelope
with code 'G-xx' through the test endpoint when APP_ENV=test.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.parametrize(
    "guard_code",
    [f"G-{i:02d}" for i in range(1, 19)],
)
async def test_every_system_guard_returns_422_envelope(
    client: AsyncClient,
    guard_code: str,
) -> None:
    """Every guard returns a 422 envelope with code 'G-xx' through the test endpoint."""
    resp = await client.post(f"/api/v1/test/guards/{guard_code}")
    assert resp.status_code == 422, (
        f"Expected 422 for {guard_code}, got {resp.status_code}: {resp.text}"
    )

    data = resp.json()
    assert "error" in data, f"Envelope missing 'error' key: {data}"
    err = data["error"]
    assert err["code"] == guard_code, f"Expected error.code={guard_code}, got {err['code']}"
    assert err["details"]["guard"] == guard_code
    assert err["message"], "Error message should not be empty"


async def test_invalid_guard_code_returns_400(
    client: AsyncClient,
) -> None:
    """Invalid guard code syntax is rejected with 400 Bad Request."""
    resp = await client.post("/api/v1/test/guards/G-99")
    assert resp.status_code == 400
    data = resp.json()
    assert data["error"]["code"] == "BAD_REQUEST"
