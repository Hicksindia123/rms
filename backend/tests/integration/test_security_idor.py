"""Insecure Direct Object Reference (IDOR) & Object Isolation security suite (§9.3, §9.4).

Verifies that users cannot access, mutate or delete resources belonging to other
users, departments, or entities without explicit authorization.

Scenarios tested:
1. Saved Views IDOR: User B cannot fetch, update, or delete User A's saved view.
2. Attachment IDOR: User B cannot delete a confirmed attachment uploaded by User A.
3. Task Inbox Isolation: User B's inbox does not expose tasks assigned specifically to User A.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import get_session_factory
from app.shared.storage import get_storage
from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, build_test_app
from tests.integration.test_unboxing import FakeStorage

pytestmark = pytest.mark.asyncio


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
async def client(
    session_factory: sessionmaker[Session], storage: FakeStorage
) -> AsyncIterator[AsyncClient]:
    app = build_test_app()
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_storage] = lambda: storage
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_saved_view_idor_protection(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    """User B cannot view, modify, or delete User A's private saved view."""
    user_a = users.create(roles=["MANAGEMENT_VIEWER"], full_name="User Alpha")
    user_b = users.create(roles=["MANAGEMENT_VIEWER"], full_name="User Bravo")

    token_a = make_token(user_a)
    token_b = make_token(user_b)

    # 1. User A creates a private saved view
    create_payload = {
        "view_code": "goods_slips",
        "name": "Alpha Custom View",
        "filters": [{"field": "status", "op": "eq", "value": "GATE_CREATED"}],
        "columns": ["gs_no", "status", "created_at"],
        "sort_by": "created_at",
        "sort_dir": "desc",
        "is_default": False,
    }
    res_create = await client.post(
        "/api/v1/saved-views", json=create_payload, headers=_auth(token_a)
    )
    assert res_create.status_code == 201, res_create.text
    view_id = res_create.json()["id"]

    # 2. User B lists views - User A's view must NOT appear in User B's list
    res_list_b = await client.get(
        "/api/v1/saved-views?view_code=goods_slips", headers=_auth(token_b)
    )
    assert res_list_b.status_code == 200
    b_view_ids = [v["id"] for v in res_list_b.json()]
    assert view_id not in b_view_ids

    # 3. User B attempts to update User A's view -> 404 (IDOR blocked, no existence leakage)
    update_payload = {"name": "Hacked View"}
    res_update = await client.put(
        f"/api/v1/saved-views/{view_id}", json=update_payload, headers=_auth(token_b)
    )
    assert res_update.status_code == 404
    assert res_update.json()["error"]["code"] == "SAVED_VIEW_NOT_FOUND"

    # 4. User B attempts to delete User A's view -> 404 (Deletion prevented)
    res_delete = await client.delete(f"/api/v1/saved-views/{view_id}", headers=_auth(token_b))
    assert res_delete.status_code == 404
    assert res_delete.json()["error"]["code"] == "SAVED_VIEW_NOT_FOUND"

    # 5. User A can still delete their own view
    res_delete_a = await client.delete(f"/api/v1/saved-views/{view_id}", headers=_auth(token_a))
    assert res_delete_a.status_code == 204


async def test_attachment_delete_idor_protection(
    client: AsyncClient, db_conn: Connection, users: UserFactory, make_token: JwtFactory
) -> None:
    """User B cannot delete a confirmed attachment uploaded by User A."""
    conn = as_admin(db_conn)
    user_a = users.create(roles=["INWARD_VERIFIER"], full_name="Verifier Alpha")
    user_b = users.create(roles=["INWARD_VERIFIER"], full_name="Verifier Bravo")

    token_a = make_token(user_a)
    token_b = make_token(user_b)

    # Setup: create a GS in UNBOXING
    wf_id = conn.execute(
        text("select id from public.workflow_versions where status = 'PUBLISHED' limit 1")
    ).scalar_one()

    station_id = conn.execute(text("select id from public.stations limit 1")).scalar_one()

    gs_id = conn.execute(
        text(
            """
            insert into public.goods_slips (
                gs_no, party_id, station_id, workflow_version_id, delivery_mode_code, transporter_name, vehicle_no,
                box_count, status, created_by
            ) values (
                'GS-IDOR-TEST-01', (select id from public.parties limit 1), :station_id, :wf_id,
                'DIRECT_TRUCK', 'Transporter', 'DL-01-AB-1234', 1, 'UNBOXING', :uid
            ) returning id
            """
        ),
        {"wf_id": wf_id, "station_id": station_id, "uid": user_a},
    ).scalar_one()

    # Create confirmed attachment owned by User A
    obj_uuid = str(uuid.uuid4())
    att_id = conn.execute(
        text(
            """
            insert into public.attachments (
                gs_id, kind, bucket, object_path, mime_type, size_bytes,
                status, uploaded_by, confirmed_at
            ) values (
                :gs_id, 'PARCEL_PHOTO', 'rms-documents', :obj_path, 'image/jpeg', 1024,
                'CONFIRMED', :uid, now()
            ) returning id
            """
        ),
        {"gs_id": gs_id, "obj_path": f"gs/{gs_id}/parcel_photo/{obj_uuid}.jpg", "uid": user_a},
    ).scalar_one()

    # User B attempts to DELETE User A's confirmed attachment -> 403 NOT_UPLOADER
    res_del_b = await client.delete(f"/api/v1/attachments/{att_id}", headers=_auth(token_b))
    assert res_del_b.status_code == 403
    assert res_del_b.json()["error"]["code"] == "NOT_UPLOADER"


async def test_task_inbox_cross_user_isolation(
    client: AsyncClient, db_conn: Connection, users: UserFactory, make_token: JwtFactory
) -> None:
    """User B does not see tasks assigned specifically to User A."""
    conn = as_admin(db_conn)
    user_a = users.create(roles=["TECHNICIAN"], full_name="Tech Alpha")
    user_b = users.create(roles=["TECHNICIAN"], full_name="Tech Bravo")

    token_a = make_token(user_a)
    token_b = make_token(user_b)

    # Insert a task directly assigned to User A
    wf_id = conn.execute(
        text("select id from public.workflow_versions where status = 'PUBLISHED' limit 1")
    ).scalar_one()

    station_id = conn.execute(text("select id from public.stations limit 1")).scalar_one()

    gs_id = conn.execute(
        text(
            """
            insert into public.goods_slips (
                gs_no, party_id, station_id, workflow_version_id, delivery_mode_code, transporter_name, vehicle_no,
                box_count, status, created_by
            ) values (
                'GS-IDOR-TASK-01', (select id from public.parties limit 1), :station_id, :wf_id,
                'DIRECT_TRUCK', 'Transporter', 'DL-01-AB-1234', 1, 'IN_PROCESS', :uid
            ) returning id
            """
        ),
        {"wf_id": wf_id, "station_id": station_id, "uid": user_a},
    ).scalar_one()

    task_id = conn.execute(
        text(
            """
            insert into public.workflow_tasks (
                gs_id, step_code, status, assigned_user_id
            ) values (
                :gs_id, 'S3_TECH_ALLOT', 'OPEN', :uid
            ) returning id
            """
        ),
        {"gs_id": gs_id, "uid": user_a},
    ).scalar_one()

    # User A sees the task
    res_a = await client.get("/api/v1/tasks/mine?status=OPEN", headers=_auth(token_a))
    assert res_a.status_code == 200
    a_task_ids = [t["id"] for t in res_a.json()["items"]]
    assert str(task_id) in a_task_ids

    # User B's inbox does not contain User A's task
    res_b = await client.get("/api/v1/tasks/mine?status=OPEN", headers=_auth(token_b))
    assert res_b.status_code == 200
    b_task_ids = [t["id"] for t in res_b.json()["items"]]
    assert str(task_id) not in b_task_ids
