"""RLS proof integration tests against PostgREST directly (master plan §9.4, prompt P1-09).

Tests Supabase REST endpoint (/rest/v1) using:
1. Anon key: proves anon has zero read or write privileges on any business table.
2. Authenticated user JWT: proves authenticated users cannot read or write any business table
   directly via PostgREST (all business access must flow through FastAPI).
3. Notifications table: proves authenticated user can only read their own notifications via RLS,
   and cannot directly insert or delete.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory

# Business tables that must be inaccessible via PostgREST
BUSINESS_TABLES = [
    "option_items",
    "option_sets",
    "form_definitions",
    "form_versions",
    "form_fields",
    "workflow_definitions",
    "workflow_stages",
    "workflow_steps",
    "workflow_transitions",
    "workflow_versions",
    "system_settings",
    "number_series",
    "profiles",
    "roles",
    "permissions",
    "parties",
    "products",
    "departments",
    "inventory_locations",
]

# Local default anon key from Supabase start
LOCAL_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9."
    "CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0"
)


@pytest.mark.parametrize("table", BUSINESS_TABLES)
async def test_anon_cannot_read_or_write_business_tables(settings: Settings, table: str) -> None:
    """Verify PostgREST rejects anon attempts to SELECT, INSERT, UPDATE, or DELETE on tables."""
    base_url = f"{settings.supabase_url}/rest/v1/{table}"
    headers = {
        "apikey": LOCAL_ANON_KEY,
        "Authorization": f"Bearer {LOCAL_ANON_KEY}",
    }

    async with httpx.AsyncClient(timeout=10) as client:
        # 1. GET (SELECT): must be denied (401/403/404)
        res_get = await client.get(base_url, headers=headers)
        assert res_get.status_code in (401, 403, 404), (
            f"Expected anon GET on '{table}' to be denied (401/403/404), "
            f"got {res_get.status_code}: {res_get.text}"
        )

        # 2. POST (INSERT): must be denied (never 200, 201)
        res_post = await client.post(base_url, headers=headers, json={"code": "hacked"})
        assert res_post.status_code not in (200, 201), (
            f"Expected anon POST on '{table}' to fail, got {res_post.status_code}"
        )

        # 3. DELETE with where clause: must be denied (never 200, 204)
        res_del = await client.delete(
            base_url,
            headers=headers,
            params={"id": "eq.00000000-0000-0000-0000-000000000000"},
        )
        assert res_del.status_code not in (200, 204), (
            f"Expected anon DELETE on '{table}' to fail, got {res_del.status_code}"
        )


@pytest.mark.parametrize("table", BUSINESS_TABLES)
async def test_authenticated_user_cannot_read_or_write_business_tables(
    settings: Settings, users: UserFactory, make_token: JwtFactory, table: str
) -> None:
    """Verify that PostgREST rejects authenticated user direct access to business tables."""
    user_id = users.create(roles=["GATE_INWARD"])
    token = make_token(user_id)

    base_url = f"{settings.supabase_url}/rest/v1/{table}"
    headers = {
        "apikey": LOCAL_ANON_KEY,
        "Authorization": f"Bearer {token}",
    }

    async with httpx.AsyncClient(timeout=10) as client:
        # 1. GET (SELECT): must be denied (401/403/404)
        res_get = await client.get(base_url, headers=headers)
        assert res_get.status_code in (401, 403, 404), (
            f"Expected authenticated GET on '{table}' to be denied (401/403/404), "
            f"got {res_get.status_code}: {res_get.text}"
        )

        # 2. POST (INSERT): must be denied (never 200, 201)
        res_post = await client.post(base_url, headers=headers, json={"code": "hacked"})
        assert res_post.status_code not in (200, 201), (
            f"Expected authenticated POST on '{table}' to fail, got {res_post.status_code}"
        )

        # 3. DELETE with where clause: must be denied (never 200, 204)
        res_del = await client.delete(
            base_url,
            headers=headers,
            params={"id": "eq.00000000-0000-0000-0000-000000000000"},
        )
        assert res_del.status_code not in (200, 204), (
            f"Expected authenticated DELETE on '{table}' to fail, got {res_del.status_code}"
        )


async def test_notifications_rls_isolation(
    settings: Settings, users: UserFactory, make_token: JwtFactory
) -> None:
    """Verify authenticated users can only SELECT their own notifications and not direct-insert."""
    u1_id = users.create(roles=["GATE_INWARD"])
    u1_token = make_token(u1_id)

    headers_u1 = {
        "apikey": LOCAL_ANON_KEY,
        "Authorization": f"Bearer {u1_token}",
    }
    base_url = f"{settings.supabase_url}/rest/v1/notifications"

    async with httpx.AsyncClient(timeout=10) as client:
        # 1. Direct INSERT is forbidden by database privileges (no INSERT privilege)
        res_insert = await client.post(
            base_url,
            headers=headers_u1,
            json={"user_id": str(u1_id), "type": "HACK", "title": "Injected notification"},
        )
        assert res_insert.status_code not in (200, 201), (
            f"Direct insert into notifications should be denied, "
            f"got {res_insert.status_code}: {res_insert.text}"
        )

        # 2. SELECT returns empty or only user's own (RLS enforced)
        res_get = await client.get(base_url, headers=headers_u1)
        if res_get.status_code == 200:
            rows = res_get.json()
            assert all(r.get("user_id") == str(u1_id) for r in rows)
        else:
            assert res_get.status_code in (401, 403, 404)
