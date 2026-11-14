"""Integration tests for P4-04: Global Search, Advanced Filters, Audit Trail & Activity
(master plan §8.7; BR-40, G-17).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text

from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory

API = "/api/v1"


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(users: UserFactory, make_token: JwtFactory) -> dict[str, str]:
    admin_user = users.create(super_admin=True, full_name="Super Admin")
    token = make_token(admin_user)
    return _h(token)


@pytest.mark.asyncio
async def test_search_endpoint(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    # 1. Search for generic keyword
    res = await client.get(f"{API}/search?q=GS", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert "query" in data
    assert "total" in data
    assert "groups" in data
    assert "took_ms" in data
    assert data["took_ms"] < 500  # fast trigram search

    # 2. Search for QR code format: gs:<id> or container barcode
    res_qr = await client.get(f"{API}/search?q=CONT-A-01", headers=admin_headers)
    assert res_qr.status_code == 200
    data_qr = res_qr.json()
    assert "is_qr_match" in data_qr


@pytest.mark.asyncio
async def test_saved_views_crud(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    # 1. Create a saved view
    view_payload = {
        "view_code": "goods_slips",
        "name": f"Test View {uuid.uuid4().hex[:6]}",
        "filters": [{"field": "status", "op": "eq", "value": "UNBOXING_PENDING"}],
        "columns": ["gs_no", "status", "created_at"],
        "is_default": True,
    }
    create_res = await client.post(
        f"{API}/saved-views",
        json=view_payload,
        headers=admin_headers,
    )
    assert create_res.status_code == 201
    created = create_res.json()
    view_id = created["id"]
    assert created["name"] == view_payload["name"]
    assert created["is_default"] is True

    # 2. List saved views for resource
    list_res = await client.get(
        f"{API}/saved-views?view_code=goods_slips",
        headers=admin_headers,
    )
    assert list_res.status_code == 200
    views = list_res.json()
    assert any(v["id"] == view_id for v in views)

    # 3. Create another view as default and verify trigger resets the first view
    view_payload_2 = {
        "view_code": "goods_slips",
        "name": f"Test View 2 {uuid.uuid4().hex[:6]}",
        "filters": [{"field": "status", "op": "eq", "value": "INSPECTION_PENDING"}],
        "is_default": True,
    }
    create_res_2 = await client.post(
        f"{API}/saved-views",
        json=view_payload_2,
        headers=admin_headers,
    )
    assert create_res_2.status_code == 201

    # Check that view_1 is no longer default
    list_res_after = await client.get(
        f"{API}/saved-views?view_code=goods_slips",
        headers=admin_headers,
    )
    views_after = {v["id"]: v for v in list_res_after.json()}
    assert views_after[view_id]["is_default"] is False

    # 4. Delete saved view
    del_res = await client.delete(
        f"{API}/saved-views/{view_id}",
        headers=admin_headers,
    )
    assert del_res.status_code == 204


@pytest.mark.asyncio
async def test_audit_log_api(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    # 1. Fetch distinct audit tables
    tables_res = await client.get(f"{API}/audit/tables", headers=admin_headers)
    assert tables_res.status_code == 200
    tables = tables_res.json()
    assert isinstance(tables, list)

    # 2. Query audit log entries
    log_res = await client.get(f"{API}/audit?limit=10", headers=admin_headers)
    assert log_res.status_code == 200
    log_data = log_res.json()
    assert "total" in log_data
    assert "items" in log_data

    # 3. Test CSV export endpoint
    export_res = await client.get(f"{API}/audit/export?limit=10", headers=admin_headers)
    assert export_res.status_code == 200
    assert "text/csv" in export_res.headers.get("content-type", "")
    assert "timestamp" in export_res.text.lower()


@pytest.mark.asyncio
async def test_gs_activity_timeline(
    client: AsyncClient,
    admin_headers: dict[str, str],
    db_conn: Connection,
) -> None:
    # Find any existing goods slip
    res = db_conn.execute(text("select id from public.goods_slips limit 1")).fetchone()
    if not res:
        pytest.skip("No goods slip found in db")
    gs_id = str(res[0])

    activity_res = await client.get(f"{API}/gs/{gs_id}/activity", headers=admin_headers)
    assert activity_res.status_code == 200
    data = activity_res.json()
    assert data["gs_id"] == gs_id
    assert "total" in data
    assert "items" in data
    assert isinstance(data["items"], list)


@pytest.mark.asyncio
async def test_user_activity_api(
    client: AsyncClient,
    admin_headers: dict[str, str],
    users: UserFactory,
    make_token: JwtFactory,
) -> None:
    # Create a user and fetch their activity
    user = users.create(roles=["REPLACEMENT_MANAGER"], full_name="Activity User")
    user_token = make_token(user)
    user_headers = _h(user_token)

    # Calling /me automatically logs a SIGN_IN user_activity
    me_res = await client.get(f"{API}/me", headers=user_headers)
    assert me_res.status_code == 200

    # Query user activity via admin
    act_res = await client.get(f"{API}/users/{user}/activity", headers=admin_headers)
    assert act_res.status_code == 200
    data = act_res.json()
    assert data["user_id"] == str(user)
    assert data["total"] >= 1
    assert any(item["activity_type"] == "SIGN_IN" for item in data["items"])


def test_audit_log_immutability(db_conn: Connection) -> None:
    """G-17 / BR-40: Direct attempt to UPDATE or DELETE audit_log rows must raise 42501."""
    with pytest.raises(Exception) as exc_update:
        db_conn.execute(text("update public.audit_log set actor_id = null"))
    assert (
        "not allowed" in str(exc_update.value).lower()
        or "insufficientprivilege" in str(exc_update.value).lower()
        or "42501" in str(exc_update.value)
    )
    db_conn.rollback()

    with pytest.raises(Exception) as exc_delete:
        db_conn.execute(text("delete from public.audit_log"))
    assert (
        "not allowed" in str(exc_delete.value).lower()
        or "insufficientprivilege" in str(exc_delete.value).lower()
        or "42501" in str(exc_delete.value)
    )
    db_conn.rollback()
