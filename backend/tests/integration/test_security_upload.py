"""Upload and File Security Integration Suite (§8.8, §9.6, prompt P4-05).

Tests:
1. MIME spoofing prevention (disallowed MIME types, executable files).
2. Filename extension vs MIME mismatch prevention.
3. Path traversal immunity in client file names (paths are strictly server-generated).
4. Oversized file rejection (> system setting limit).
5. Signed URL TTL and short expiration.
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


def _create_unboxing_gs(conn: Connection, user_id: uuid.UUID) -> uuid.UUID:
    c = as_admin(conn)
    wf_id = c.execute(
        text("select id from public.workflow_versions where status = 'PUBLISHED' limit 1")
    ).scalar_one()
    station_id = c.execute(text("select id from public.stations limit 1")).scalar_one()

    return c.execute(
        text(
            """
            insert into public.goods_slips (
                gs_no, party_id, station_id, workflow_version_id, delivery_mode_code,
                transporter_name, vehicle_no, box_count, status, created_by
            ) values (
                'GS-UPLOAD-TEST', (select id from public.parties limit 1), :station_id, :wf_id,
                'DIRECT_TRUCK', 'Transporter', 'DL-01-AB-1234', 1, 'UNBOXING', :uid
            ) returning id
            """
        ),
        {"wf_id": wf_id, "station_id": station_id, "uid": user_id},
    ).scalar_one()


async def test_disallowed_mime_type_rejected(
    client: AsyncClient, db_conn: Connection, users: UserFactory, make_token: JwtFactory
) -> None:
    """Disallowed MIME types (e.g. text/html, application/x-msdos-program) are rejected."""
    uid = users.create(roles=["INWARD_VERIFIER"])
    token = make_token(uid)
    gs_id = _create_unboxing_gs(db_conn, uid)

    payload = {
        "kind": "DOC_PHOTO",
        "mime_type": "application/x-sh",
        "size_bytes": 1024,
        "file_name": "script.sh",
    }
    res = await client.post(
        f"/api/v1/gs/{gs_id}/attachments/upload-url", json=payload, headers=_auth(token)
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] in ("FILE_NOT_ALLOWED", "FILE_REJECTED")


async def test_mime_extension_mismatch_rejected(
    client: AsyncClient, db_conn: Connection, users: UserFactory, make_token: JwtFactory
) -> None:
    """Mismatched file extension (claiming to be image/jpeg but named shell.exe) is rejected."""
    uid = users.create(roles=["INWARD_VERIFIER"])
    token = make_token(uid)
    gs_id = _create_unboxing_gs(db_conn, uid)

    payload = {
        "kind": "PARCEL_PHOTO",
        "mime_type": "image/jpeg",
        "size_bytes": 1024,
        "file_name": "malware.exe",
    }
    res = await client.post(
        f"/api/v1/gs/{gs_id}/attachments/upload-url", json=payload, headers=_auth(token)
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] in ("FILE_NOT_ALLOWED", "FILE_REJECTED")


async def test_path_traversal_in_filename_neutralized(
    client: AsyncClient, db_conn: Connection, users: UserFactory, make_token: JwtFactory
) -> None:
    """Path traversal payload in filename does NOT affect server object path."""
    uid = users.create(roles=["INWARD_VERIFIER"])
    token = make_token(uid)
    gs_id = _create_unboxing_gs(db_conn, uid)

    payload = {
        "kind": "PARCEL_PHOTO",
        "mime_type": "image/jpeg",
        "size_bytes": 2048,
        "file_name": "../../../../etc/passwd.jpg",
    }
    res = await client.post(
        f"/api/v1/gs/{gs_id}/attachments/upload-url", json=payload, headers=_auth(token)
    )
    assert res.status_code == 201
    object_path = res.json()["upload"]["object_path"]

    # Verify path is server-generated and strictly scoped under gs/{gs_id}/
    assert ".." not in object_path
    assert "etc" not in object_path
    assert object_path.startswith(f"gs/{gs_id}/parcel_photo/")


async def test_oversized_file_rejected(
    client: AsyncClient, db_conn: Connection, users: UserFactory, make_token: JwtFactory
) -> None:
    """Files exceeding size limit (> 100 MB or configured limit) are rejected."""
    uid = users.create(roles=["INWARD_VERIFIER"])
    token = make_token(uid)
    gs_id = _create_unboxing_gs(db_conn, uid)

    payload = {
        "kind": "DOC_PHOTO",
        "mime_type": "image/jpeg",
        "size_bytes": 500 * 1024 * 1024,  # 500 MB (limit is typically 10-25 MB)
        "file_name": "huge.jpg",
    }
    res = await client.post(
        f"/api/v1/gs/{gs_id}/attachments/upload-url", json=payload, headers=_auth(token)
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] in ("FILE_NOT_ALLOWED", "FILE_REJECTED")


async def test_signed_url_ttl_enforced(
    client: AsyncClient, db_conn: Connection, users: UserFactory, make_token: JwtFactory
) -> None:
    """Signed download URLs have short TTL and audited issuance."""
    uid = users.create(roles=["INWARD_VERIFIER"])
    token = make_token(uid)
    gs_id = _create_unboxing_gs(db_conn, uid)
    conn = as_admin(db_conn)

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
        {"gs_id": gs_id, "obj_path": f"gs/{gs_id}/parcel_photo/{obj_uuid}.jpg", "uid": uid},
    ).scalar_one()

    res = await client.get(f"/api/v1/attachments/{att_id}/download-url", headers=_auth(token))
    assert res.status_code == 200
    data = res.json()
    assert "url" in data
    assert 0 < data["expires_in"] <= 3600  # Default is 300s
