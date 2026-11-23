"""Step-2 unboxing evidence (prompt P2-03; BR-03..BR-06, G-02, G-17, DEC-03, DEC-04, DEC-05).

Storage is replaced by an in-memory fake (tests only): `FakeStorage.put` plays the client upload,
so path / size / MIME mismatches can be produced deliberately. The DB is the real local Supabase
Postgres (rolled back per test).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import UnitOfWork, get_session_factory
from app.core.middleware import limiter
from app.modules.attachments.service import AttachmentService
from app.shared.storage import (
    Bucket,
    ObjectInfo,
    ResumableUpload,
    SignedUpload,
    get_storage,
)
from tests.conftest import JwtFactory
from tests.integration.conftest import (
    Override,
    UserFactory,
    as_admin,
    build_test_app,
    fetch_all,
)
from tests.integration.test_gate_inward import Masters, _auth, _create, _values

MB = 1024 * 1024


# --- fake storage --------------------------------------------------------------------------------
@dataclass
class FakeStorage:
    objects: dict[tuple[str, str], tuple[int, str]] = field(default_factory=dict)
    deleted: list[tuple[str, str]] = field(default_factory=list)
    signed_urls: list[tuple[str, str, int]] = field(default_factory=list)
    uploads: dict[tuple[str, str], bytes] = field(default_factory=dict)

    def put(self, bucket: str, path: str, size: int, content_type: str) -> None:
        self.objects[(bucket, path)] = (size, content_type)

    def upload(self, bucket: Bucket, path: str, data: bytes, content_type: str) -> None:
        """Server-side upload of a generated PDF (e.g. the DEC-71 Replacement Slip at the
        Accounts gate, reached from the store-analysis / Management tests)."""
        self.uploads[(bucket.value, path)] = data
        self.put(bucket.value, path, len(data), content_type)

    def create_signed_upload_url(self, bucket: Bucket, path: str) -> SignedUpload:
        return SignedUpload(bucket.value, path, f"http://storage.test/up/{path}?token=t", "tok")

    def create_resumable_upload(self, bucket: Bucket, path: str) -> ResumableUpload:
        return ResumableUpload(
            "http://storage.test/storage/v1/upload/resumable/sign", bucket.value, path, "tok"
        )

    def create_signed_url(self, bucket: Bucket, path: str, ttl_seconds: int | None = None) -> str:
        self.signed_urls.append((bucket.value, path, int(ttl_seconds or 0)))
        return f"http://storage.test/sign/{path}?token=dl&ttl={ttl_seconds}"

    def object_info(self, bucket: Bucket, path: str) -> ObjectInfo:
        found = self.objects.get((bucket.value, path))
        if not found:
            return ObjectInfo(exists=False, size=None)
        return ObjectInfo(True, found[0], found[1], path, bucket.value)

    def delete(self, bucket: Bucket, path: str) -> None:
        self.objects.pop((bucket.value, path), None)
        self.deleted.append((bucket.value, path))


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
    limiter.reset()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    limiter.reset()


@pytest.fixture
def masters(db_conn: Connection) -> Masters:
    return Masters(db_conn)


@dataclass
class Actors:
    gate: str
    aman: str
    aman_id: uuid.UUID
    rm: str
    rm_id: uuid.UUID
    accounts: str
    accounts_id: uuid.UUID
    admin: str


@pytest.fixture
def actors(users: UserFactory, make_token: JwtFactory) -> Actors:
    aman_id = users.create(roles=["INWARD_VERIFIER"], full_name="Aman")
    rm_id = users.create(roles=["REPLACEMENT_MANAGER"], full_name="Pratham")
    acc_id = users.create(roles=["ACCOUNTS"], full_name="Deepak")
    return Actors(
        gate=make_token(users.create(roles=["GATE_INWARD"], full_name="Anuj")),
        aman=make_token(aman_id),
        aman_id=aman_id,
        rm=make_token(rm_id),
        rm_id=rm_id,
        accounts=make_token(acc_id),
        accounts_id=acc_id,
        admin=make_token(users.create(super_admin=True, full_name="Admin")),
    )


# --- helpers -------------------------------------------------------------------------------------
async def new_gs(client: AsyncClient, a: Actors, m: Masters, doc: str = "INVOICE") -> str:
    res = await _create(client, a.gate, m, _values(doc=doc))
    assert res.status_code == 201, res.text
    return str(res.json()["goods_slip"]["id"])


async def started_gs(client: AsyncClient, a: Actors, m: Masters, doc: str = "INVOICE") -> str:
    gs_id = await new_gs(client, a, m, doc)
    res = await client.post(f"/api/v1/gs/{gs_id}/unboxing/start", headers=_auth(a.aman))
    assert res.status_code == 200, res.text
    assert res.json()["goods_slip"]["status"] == "UNBOXING"
    return gs_id


async def upload(
    client: AsyncClient,
    storage: FakeStorage,
    token: str,
    gs_id: str,
    kind: str,
    mime: str,
    size: int = 2048,
    *,
    stored_size: int | None = None,
    stored_mime: str | None = None,
    confirm: bool = True,
    **extra: Any,
) -> dict[str, Any]:
    res = await client.post(
        f"/api/v1/gs/{gs_id}/attachments/upload-url",
        json={"kind": kind, "mime_type": mime, "size_bytes": size, **extra},
        headers=_auth(token),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    up = body["upload"]
    storage.put(up["bucket"], up["object_path"], stored_size or size, stored_mime or mime)
    if not confirm:
        return body
    res = await client.post(
        f"/api/v1/attachments/{body['attachment']['id']}/confirm", json={}, headers=_auth(token)
    )
    assert res.status_code == 200, res.text
    return dict(res.json())


async def upload_videos(
    client: AsyncClient, storage: FakeStorage, token: str, gs_id: str
) -> list[dict[str, Any]]:
    """G-02 / Requirement B (2026-11-10): every box needs its own confirmed UNBOXING_VIDEO.

    Uploads one video tagged with `box_no` for each box the unboxing checklist still reports in
    `boxes_missing_video`, so callers satisfy the guard whatever the GS box count is. The guard
    itself is never relaxed; this helper only supplies the evidence it demands."""
    res = await client.get(f"/api/v1/gs/{gs_id}/unboxing", headers=_auth(token))
    assert res.status_code == 200, res.text
    boxes = res.json()["checklist"]["boxes_missing_video"]
    assert boxes, "expected at least one box without a video"
    return [
        await upload(client, storage, token, gs_id, "UNBOXING_VIDEO", "video/mp4", box_no=box)
        for box in boxes
    ]


INVOICE = {
    "doc_classification": "INVOICE",
    "invoice_no": "INV-501",
    "invoice_date": "2026-10-30",
    "buyer_gstin": "09AAACH7409R1ZZ",
    "seller_gstin": "07aaacb1234c1z5",
    "items_verified": True,
}


async def classify(
    client: AsyncClient, token: str, gs_id: str, att_id: str, values: dict[str, Any]
) -> Any:
    return await client.post(
        f"/api/v1/gs/{gs_id}/documents",
        json={"attachment_id": att_id, "values": values},
        headers=_auth(token),
    )


async def complete(client: AsyncClient, token: str, gs_id: str) -> Any:
    return await client.post(f"/api/v1/gs/{gs_id}/unboxing/complete", headers=_auth(token))


# --- start ---------------------------------------------------------------------------------------
async def test_start_unboxing_rules(client: AsyncClient, actors: Actors, masters: Masters) -> None:
    gs_id = await new_gs(client, actors, masters)
    # Anuj (gate) is not an S1_UNBOX performer.
    res = await client.post(f"/api/v1/gs/{gs_id}/unboxing/start", headers=_auth(actors.gate))
    assert res.status_code == 403
    res = await client.post(f"/api/v1/gs/{gs_id}/unboxing/start", headers=_auth(actors.aman))
    assert res.status_code == 200, res.text
    state = res.json()
    assert state["goods_slip"]["status"] == "UNBOXING"
    assert state["checklist"]["ready"] is False
    assert state["permissions"]["can_perform"] is True
    assert {f["control_type"] for f in state["form_snapshot"]["fields"]}.isdisjoint({"file"})
    # Repeat is a no-op.
    res = await client.post(f"/api/v1/gs/{gs_id}/unboxing/start", headers=_auth(actors.aman))
    assert res.status_code == 200


# --- upload-url validation matrix ----------------------------------------------------------------
@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"kind": "OTHER", "mime_type": "image/png", "size_bytes": 10}, 422, "VALIDATION_FAILED"),
        (
            {"kind": "UNBOXING_VIDEO", "mime_type": "image/png", "size_bytes": 10},
            422,
            "FILE_NOT_ALLOWED",
        ),
        (
            {"kind": "UNBOXING_VIDEO", "mime_type": "video/x-msvideo", "size_bytes": 10},
            422,
            "FILE_NOT_ALLOWED",
        ),
        (
            {"kind": "DOC_PHOTO", "mime_type": "image/gif", "size_bytes": 10},
            422,
            "FILE_NOT_ALLOWED",
        ),
        (
            {"kind": "DOC_PHOTO", "mime_type": "text/html", "size_bytes": 10},
            422,
            "FILE_NOT_ALLOWED",
        ),
        (
            {"kind": "PARCEL_PHOTO", "mime_type": "application/pdf", "size_bytes": 10},
            422,
            "FILE_NOT_ALLOWED",
        ),
        (
            {"kind": "DOC_PHOTO", "mime_type": "image/png", "size_bytes": 10, "file_name": "x.exe"},
            422,
            "FILE_NOT_ALLOWED",
        ),
        (
            {"kind": "DOC_PHOTO", "mime_type": "image/png", "size_bytes": 26 * MB},
            422,
            "FILE_NOT_ALLOWED",
        ),
        (
            {"kind": "UNBOXING_VIDEO", "mime_type": "video/mp4", "size_bytes": 1025 * MB},
            422,
            "FILE_NOT_ALLOWED",
        ),
        (
            {"kind": "DOC_PHOTO", "mime_type": "image/png", "size_bytes": 0},
            422,
            "VALIDATION_FAILED",
        ),
        (
            {"kind": "UNBOXING_VIDEO", "mime_type": "video/mp4", "size_bytes": 10, "box_no": 9},
            422,
            "FILE_NOT_ALLOWED",
        ),
        (
            {"kind": "DOC_PHOTO", "mime_type": "image/png", "size_bytes": 10, "object_path": "x"},
            422,
            "VALIDATION_FAILED",
        ),
    ],
)
async def test_upload_url_rejects(
    client: AsyncClient,
    actors: Actors,
    masters: Masters,
    body: dict[str, Any],
    status: int,
    code: str,
) -> None:
    gs_id = await started_gs(client, actors, masters)
    res = await client.post(
        f"/api/v1/gs/{gs_id}/attachments/upload-url", json=body, headers=_auth(actors.aman)
    )
    assert res.status_code == status, res.text
    assert res.json()["error"]["code"] == code


@pytest.mark.parametrize(
    ("kind", "mime", "file_name", "ext"),
    [
        ("UNBOXING_VIDEO", "video/mp4", "clip.MP4", "mp4"),
        ("UNBOXING_VIDEO", "video/quicktime", "IMG_0001.MOV", "mov"),
        ("DOC_PHOTO", "image/jpeg", "invoice.jpeg", "jpg"),
        ("DOC_PHOTO", "image/png", None, "png"),
        ("DOC_PHOTO", "image/heic", "IMG_0002.HEIC", "heic"),
        ("DOC_PHOTO", "application/pdf", "challan.pdf", "pdf"),
        ("PARCEL_PHOTO", "image/jpeg", "box.jpg", "jpg"),
    ],
)
async def test_upload_url_accepts_allow_list(
    client: AsyncClient,
    actors: Actors,
    masters: Masters,
    kind: str,
    mime: str,
    file_name: str | None,
    ext: str,
) -> None:
    gs_id = await started_gs(client, actors, masters)
    res = await client.post(
        f"/api/v1/gs/{gs_id}/attachments/upload-url",
        json={"kind": kind, "mime_type": mime, "size_bytes": 4096, "file_name": file_name},
        headers=_auth(actors.aman),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    path = body["upload"]["object_path"]
    # §8.8: server-generated path, never the client's file name.
    assert path.startswith(f"gs/{gs_id}/{kind.lower()}/") and path.endswith(f".{ext}")
    assert body["attachment"]["status"] == "PENDING_UPLOAD"
    assert body["upload"]["bucket"] == (
        "rms-videos" if kind == "UNBOXING_VIDEO" else "rms-documents"
    )
    assert body["attachment"]["preview_unsupported"] is (mime == "image/heic")


async def test_large_video_gets_resumable_tus(
    client: AsyncClient, actors: Actors, masters: Masters
) -> None:
    gs_id = await started_gs(client, actors, masters)
    res = await client.post(
        f"/api/v1/gs/{gs_id}/attachments/upload-url",
        json={"kind": "UNBOXING_VIDEO", "mime_type": "video/mp4", "size_bytes": 300 * MB},
        headers=_auth(actors.aman),
    )
    assert res.status_code == 201, res.text
    up = res.json()["upload"]
    assert up["method"] == "TUS" and up["chunk_size"] == 6 * MB and up["token"]
    assert up["endpoint"].endswith("/upload/resumable/sign")
    small = await client.post(
        f"/api/v1/gs/{gs_id}/attachments/upload-url",
        json={"kind": "UNBOXING_VIDEO", "mime_type": "video/mp4", "size_bytes": 5 * MB},
        headers=_auth(actors.aman),
    )
    assert small.json()["upload"]["method"] == "SIGNED_PUT"


async def test_upload_requires_unboxing_status_and_step_actor(
    client: AsyncClient,
    actors: Actors,
    masters: Masters,
    users: UserFactory,
    make_token: JwtFactory,
) -> None:
    gs_id = await new_gs(client, actors, masters)
    body = {"kind": "DOC_PHOTO", "mime_type": "image/png", "size_bytes": 10}
    res = await client.post(
        f"/api/v1/gs/{gs_id}/attachments/upload-url", json=body, headers=_auth(actors.aman)
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "GS_NOT_UNBOXING"
    await client.post(f"/api/v1/gs/{gs_id}/unboxing/start", headers=_auth(actors.aman))
    # Gate user holds attachments.create but is not an S1_UNBOX performer.
    res = await client.post(
        f"/api/v1/gs/{gs_id}/attachments/upload-url", json=body, headers=_auth(actors.gate)
    )
    assert res.status_code == 403 and res.json()["error"]["code"] == "NOT_STEP_ACTOR"


async def test_upload_url_is_rate_limited(
    client: AsyncClient, actors: Actors, masters: Masters
) -> None:
    gs_id = await new_gs(client, actors, masters)  # not UNBOXING → quick 409s still count
    body = {"kind": "DOC_PHOTO", "mime_type": "image/png", "size_bytes": 10}
    codes = []
    for _ in range(61):
        res = await client.post(
            f"/api/v1/gs/{gs_id}/attachments/upload-url", json=body, headers=_auth(actors.aman)
        )
        codes.append(res.status_code)
    assert codes[:60] == [409] * 60
    assert codes[60] == 429


# --- confirm -------------------------------------------------------------------------------------
async def test_confirm_checks_object(
    client: AsyncClient, actors: Actors, masters: Masters, storage: FakeStorage, db_conn: Connection
) -> None:
    gs_id = await started_gs(client, actors, masters)
    # Not uploaded yet.
    pending = await upload(
        client, storage, actors.aman, gs_id, "DOC_PHOTO", "image/png", confirm=False
    )
    att_id = pending["attachment"]["id"]
    storage.objects.clear()
    res = await client.post(f"/api/v1/attachments/{att_id}/confirm", headers=_auth(actors.aman))
    assert res.status_code == 409 and res.json()["error"]["code"] == "OBJECT_NOT_UPLOADED"

    # Client reports a different object path → rejected without touching the row.
    path = pending["upload"]["object_path"]
    storage.put("rms-documents", path, 2048, "image/png")
    other = f"gs/{gs_id}/doc_photo/{uuid.uuid4()}.png"
    res = await client.post(
        f"/api/v1/attachments/{att_id}/confirm",
        json={"object_path": other},
        headers=_auth(actors.aman),
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "OBJECT_PATH_MISMATCH"
    res = await client.post(
        f"/api/v1/attachments/{att_id}/confirm",
        json={"object_path": f"rms-documents/{path}"},
        headers=_auth(actors.aman),
    )
    assert res.status_code == 200 and res.json()["status"] == "CONFIRMED"
    res = await client.post(f"/api/v1/attachments/{att_id}/confirm", headers=_auth(actors.aman))
    assert res.status_code == 200  # repeat confirmation

    # Size mismatch → 422, row REJECTED, object removed.
    bad = await upload(
        client,
        storage,
        actors.aman,
        gs_id,
        "DOC_PHOTO",
        "image/png",
        stored_size=999,
        confirm=False,
    )
    bad_id = bad["attachment"]["id"]
    res = await client.post(f"/api/v1/attachments/{bad_id}/confirm", headers=_auth(actors.aman))
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "UPLOAD_MISMATCH"
    assert "size_bytes" in res.json()["error"]["details"]
    assert ("rms-documents", bad["upload"]["object_path"]) in storage.deleted
    row = fetch_all(db_conn, "select status from public.attachments where id = :id", id=bad_id)
    assert row[0]["status"] == "REJECTED"

    # MIME mismatch (declared PNG, stored HTML).
    bad2 = await upload(
        client,
        storage,
        actors.aman,
        gs_id,
        "DOC_PHOTO",
        "image/png",
        stored_mime="text/html",
        confirm=False,
    )
    res = await client.post(
        f"/api/v1/attachments/{bad2['attachment']['id']}/confirm", headers=_auth(actors.aman)
    )
    assert res.status_code == 422 and "mime_type" in res.json()["error"]["details"]


# --- G-02 ----------------------------------------------------------------------------------------
async def test_g02_complete_requires_a_video_per_carton_only(
    client: AsyncClient,
    actors: Actors,
    masters: Masters,
    storage: FakeStorage,
    db_conn: Connection,
) -> None:
    """G-02 after DEC-63 (user Q8 + Q25): one confirmed video per carton, nothing else."""
    gs_id = await started_gs(client, actors, masters)

    res = await complete(client, actors.aman, gs_id)
    assert res.status_code == 422, res.text
    err = res.json()["error"]
    assert err["code"] == "G-02"
    # With no video at all, every carton is also reported as missing its video.
    assert set(err["details"]["missing"]) == {"UNBOXING_VIDEO", "VIDEO_PER_CARTON"}

    # Requirement B (2026-11-10): one video for box 1 of 3 is not enough; every box needs its own.
    await upload(
        client, storage, actors.aman, gs_id, "UNBOXING_VIDEO", "video/mp4", 9 * MB, box_no=1
    )
    res = await complete(client, actors.aman, gs_id)
    assert res.status_code == 422, res.text
    err = res.json()["error"]
    assert err["code"] == "G-02"
    assert err["details"]["missing"] == ["VIDEO_PER_CARTON"]
    assert err["details"]["checklist"]["boxes_missing_video"] == [2, 3]
    # A Super Admin cannot bypass G-02 either.
    res = await complete(client, actors.admin, gs_id)
    assert res.status_code == 422 and res.json()["error"]["code"] == "G-02"

    # Legacy DOC_PHOTO classification still works (existing data stays usable) ...
    photo = await upload(client, storage, actors.aman, gs_id, "DOC_PHOTO", "image/jpeg")
    res = await classify(client, actors.aman, gs_id, photo["id"], INVOICE)
    assert res.status_code == 201, res.text
    doc = res.json()
    assert doc["classification_label"] == "Invoice"
    assert doc["seller_gstin"] == "07AAACB1234C1Z5"  # normalised before validation
    assert doc["doc_no"] == "INV-501" and doc["items_verified"] is True
    # ... but an unclassified photo no longer blocks (DEC-63 b).
    await upload(client, storage, actors.aman, gs_id, "DOC_PHOTO", "application/pdf")

    await upload_videos(client, storage, actors.aman, gs_id)
    state = (await client.get(f"/api/v1/gs/{gs_id}/unboxing", headers=_auth(actors.aman))).json()
    assert state["checklist"]["ready"] is True and state["checklist"]["missing"] == []
    assert "can_approve_exception" not in state["permissions"]
    res = await complete(client, actors.aman, gs_id)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["goods_slip"]["status"] == "ITEMIZATION"
    assert out["notified_user_count"] >= 1
    tasks = fetch_all(
        db_conn,
        "select step_code, status from public.workflow_tasks where gs_id = :g order by created_at",
        g=gs_id,
    )
    assert [t["step_code"] for t in tasks if t["status"] == "OPEN"] == ["S1_ITEMIZE"]
    assert {"S1_UNBOX"} <= {t["step_code"] for t in tasks if t["status"] == "DONE"}
    notes = fetch_all(
        db_conn,
        "select title, body from public.notifications where user_id = :u and entity_id = :g "
        "order by created_at",
        u=actors.accounts_id,
        g=gs_id,
    )
    # Two Accounts alerts: the gate-time GS_DOCUMENT_FOUND alert for the Invoice declared at the
    # gate (2026-11-10; per document row since AMD-05), then the evidence-completed alert (BR-06).
    assert len(notes) == 2
    evidence = [n for n in notes if n["title"].startswith("Documents received for GS ")]
    assert len(evidence) == 1
    assert "Invoice" in evidence[0]["body"]
    # AMD-05: the gate alert is per document row and asks Accounts for the GST input check.
    assert "GST input" in next(n for n in notes if n not in evidence)["body"]

    # Documents are frozen once the GS has left UNBOXING; evidence cannot be deleted.
    res = await client.patch(
        f"/api/v1/gs/{gs_id}/documents/{doc['id']}",
        json={"values": {**INVOICE, "invoice_no": "X"}},
        headers=_auth(actors.aman),
    )
    assert res.status_code == 409
    res = await client.delete(f"/api/v1/attachments/{photo['id']}", headers=_auth(actors.aman))
    assert res.status_code == 409


async def test_g02_db_trigger_blocks_direct_status_change(
    client: AsyncClient, actors: Actors, masters: Masters, db_conn: Connection
) -> None:
    gs_id = await started_gs(client, actors, masters)
    conn = as_admin(db_conn)
    with pytest.raises(DBAPIError, match="G-02"), conn.begin_nested():
        conn.execute(
            text("update public.goods_slips set status = 'ITEMIZATION' where id = :id"),
            {"id": gs_id},
        )
    gs2 = await new_gs(client, actors, masters)
    with pytest.raises(DBAPIError, match="G-02"), conn.begin_nested():
        conn.execute(
            text("update public.goods_slips set status = 'INSPECTION' where id = :id"),
            {"id": gs2},
        )


# --- classification (DD r12-r15, BR-05) ----------------------------------------------------------
@pytest.mark.parametrize(
    ("values", "field"),
    [
        ({**INVOICE, "buyer_gstin": ""}, "buyer_gstin"),
        ({**INVOICE, "seller_gstin": "BAD-GSTIN"}, "seller_gstin"),
        ({**INVOICE, "items_verified": False}, "items_verified"),
        ({**INVOICE, "invoice_no": None}, "invoice_no"),
        ({"doc_classification": "DEBIT_NOTE", "dn_number": "DN-1"}, "dn_amount"),
        ({"doc_classification": "DEBIT_NOTE", "dn_amount": 10}, "dn_number"),
        ({"doc_classification": "DELIVERY_CHALLAN"}, "challan_qty_matched"),
        (
            {"doc_classification": "DELIVERY_CHALLAN", "challan_qty_matched": False},
            "challan_remarks",
        ),
        ({"doc_classification": "HANDWRITTEN_SLIP", "party_claim_text": " "}, "party_claim_text"),
        ({"doc_classification": "NO_DOCUMENT"}, "doc_classification"),
    ],
)
async def test_classification_conditional_fields(
    client: AsyncClient,
    actors: Actors,
    masters: Masters,
    storage: FakeStorage,
    values: dict[str, Any],
    field: str,
) -> None:
    gs_id = await started_gs(client, actors, masters)
    photo = await upload(client, storage, actors.aman, gs_id, "DOC_PHOTO", "image/png")
    res = await classify(client, actors.aman, gs_id, photo["id"], values)
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "FORM_VALIDATION_FAILED"
    assert field in res.json()["error"]["details"]


async def test_classification_valid_types_and_edit(
    client: AsyncClient, actors: Actors, masters: Masters, storage: FakeStorage
) -> None:
    gs_id = await started_gs(client, actors, masters)
    cases = [
        {"doc_classification": "DELIVERY_CHALLAN", "challan_qty_matched": True},
        {
            "doc_classification": "DELIVERY_CHALLAN",
            "challan_qty_matched": False,
            "challan_remarks": "2 pcs short against challan",
        },
        {"doc_classification": "HANDWRITTEN_SLIP", "party_claim_text": "3 thermometers broken"},
    ]
    docs = []
    for values in cases:
        photo = await upload(client, storage, actors.aman, gs_id, "DOC_PHOTO", "image/png")
        res = await classify(client, actors.aman, gs_id, photo["id"], values)
        assert res.status_code == 201, res.text
        docs.append(res.json())
    assert docs[1]["qty_matched"] is False and docs[1]["remarks"] == "2 pcs short against challan"
    # The same photo cannot be classified twice.
    res = await classify(client, actors.aman, gs_id, docs[0]["attachment_id"], cases[0])
    assert res.status_code == 409
    # A video cannot be classified as a document.
    video = await upload(client, storage, actors.aman, gs_id, "UNBOXING_VIDEO", "video/mp4")
    res = await classify(client, actors.aman, gs_id, video["id"], cases[0])
    assert res.status_code == 422 and res.json()["error"]["code"] == "NOT_A_DOCUMENT_PHOTO"
    # Edit (re-validated against the stored form version, G-18).
    res = await client.patch(
        f"/api/v1/gs/{gs_id}/documents/{docs[2]['id']}",
        json={"values": {**INVOICE}},
        headers=_auth(actors.aman),
    )
    assert res.status_code == 200, res.text
    assert res.json()["classification_code"] == "INVOICE"
    assert res.json()["party_claim_text"] is None


# --- DEC-03 missing documentation ----------------------------------------------------------------
async def test_missing_documentation_gs_completes_on_videos_only(
    client: AsyncClient,
    actors: Actors,
    masters: Masters,
    storage: FakeStorage,
    db_conn: Connection,
) -> None:
    """DEC-63 (user Q8): no RM Missing Document Exception. A GS flagged "No Documents From Party"
    leaves UNBOXING on a video per carton alone; the flag and the Accounts alert stay."""
    gs_id = await started_gs(client, actors, masters, doc="NO_DOCUMENT")
    res = await complete(client, actors.aman, gs_id)
    assert res.status_code == 422
    assert set(res.json()["error"]["details"]["missing"]) == {"UNBOXING_VIDEO", "VIDEO_PER_CARTON"}

    # The exception endpoints are gone (request, decision, RM queue).
    parcel = await upload(client, storage, actors.aman, gs_id, "PARCEL_PHOTO", "image/jpeg")
    res = await client.post(
        f"/api/v1/gs/{gs_id}/missing-doc-exception",
        json={"parcel_attachment_id": parcel["id"], "remark": "No papers in the box"},
        headers=_auth(actors.aman),
    )
    assert res.status_code in (404, 405)
    res = await client.get("/api/v1/missing-doc-exceptions/pending", headers=_auth(actors.rm))
    assert res.status_code in (404, 405)

    for box in (1, 2, 3):
        await upload(
            client, storage, actors.aman, gs_id, "UNBOXING_VIDEO", "video/quicktime", box_no=box
        )
    res = await complete(client, actors.aman, gs_id)
    assert res.status_code == 200, res.text
    assert res.json()["goods_slip"]["missing_documentation"] is True  # BR-03 flag kept
    notes = fetch_all(
        db_conn,
        "select priority, body from public.notifications where user_id = :u and entity_id = :g "
        "and type = 'GS_DOCUMENTS_RECEIVED'",
        u=actors.accounts_id,
        g=gs_id,
    )
    assert notes and notes[0]["priority"] == "HIGH"
    assert "No documents from party" in notes[0]["body"]
    assert "Exception" not in notes[0]["body"]
    rm_notes = fetch_all(
        db_conn,
        "select type from public.notifications where user_id = :u and entity_id = :g",
        u=actors.rm_id,
        g=gs_id,
    )
    assert not any(n["type"].startswith("MISSING_DOC_EXCEPTION") for n in rm_notes)


async def test_legacy_gs_blocked_on_exception_is_released(
    client: AsyncClient,
    actors: Actors,
    masters: Masters,
    storage: FakeStorage,
    db_conn: Connection,
) -> None:
    """DEC-63 / migration 20261120000300: a GS that waited for a REQUESTED exception completes on
    its carton videos; the exception row stays as read-only history and can no longer change."""
    gs_id = await started_gs(client, actors, masters, doc="NO_DOCUMENT")
    parcel = await upload(client, storage, actors.aman, gs_id, "PARCEL_PHOTO", "image/jpeg")
    conn = as_admin(db_conn)
    conn.execute(
        text(
            "alter table public.missing_doc_exceptions disable trigger missing_doc_exceptions_guard"
        )
    )
    conn.execute(
        text(
            "insert into public.missing_doc_exceptions (gs_id, parcel_attachment_id, remark) "
            "values (:g, :a, 'No papers (before DEC-63)')"
        ),
        {"g": gs_id, "a": parcel["id"]},
    )
    conn.execute(
        text(
            "alter table public.missing_doc_exceptions enable trigger missing_doc_exceptions_guard"
        )
    )
    with pytest.raises(DBAPIError, match="DEC-63"), conn.begin_nested():
        conn.execute(
            text(
                "update public.missing_doc_exceptions set status = 'REJECTED', "
                "decided_by = :u, decided_at = now(), decision_remarks = 'x' where gs_id = :g"
            ),
            {"u": actors.rm_id, "g": gs_id},
        )
    await upload_videos(client, storage, actors.aman, gs_id)
    state = (await client.get(f"/api/v1/gs/{gs_id}/unboxing", headers=_auth(actors.aman))).json()
    assert [e["status"] for e in state["exceptions"]] == ["REQUESTED"]
    assert state["checklist"]["ready"] is True
    res = await complete(client, actors.aman, gs_id)
    assert res.status_code == 200, res.text


# --- downloads -----------------------------------------------------------------------------------
async def test_download_url_permission_ttl_and_audit(
    client: AsyncClient,
    actors: Actors,
    masters: Masters,
    storage: FakeStorage,
    users: UserFactory,
    make_token: JwtFactory,
    db_conn: Connection,
) -> None:
    gs_id = await started_gs(client, actors, masters)
    photo = await upload(client, storage, actors.aman, gs_id, "DOC_PHOTO", "image/png")
    url = f"/api/v1/attachments/{photo['id']}/download-url"

    as_admin(db_conn).execute(
        text("update public.system_settings set value = '120' where key = 'signed_url_ttl_seconds'")
    )
    res = await client.get(url, headers=_auth(actors.aman))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["expires_in"] == 120 and body["mime_type"] == "image/png"
    assert storage.signed_urls[-1] == ("rms-documents", photo_path(db_conn, photo["id"]), 120)
    audit = fetch_all(
        db_conn,
        "select actor_id, new from public.audit_log where table_name = 'public.attachments' "
        "and action = 'ACCESS' and row_id = :r",
        r=photo["id"],
    )
    assert len(audit) == 1 and audit[0]["actor_id"] == actors.aman_id
    assert (
        audit[0]["new"]["event"] == "DOWNLOAD_URL_ISSUED" and audit[0]["new"]["ttl_seconds"] == 120
    )

    # Accounts (goods_slips.view all) may view.
    assert (await client.get(url, headers=_auth(actors.accounts))).status_code == 200
    # A Technician has no attachments.view → 403.
    tech = make_token(users.create(roles=["TECHNICIAN"]))
    assert (await client.get(url, headers=_auth(tech))).status_code == 403
    # attachments.view but goods_slips.view denied → 403 GS_ACCESS_DENIED.
    no_gs = make_token(
        users.create(roles=["INWARD_VERIFIER"], overrides=[Override("goods_slips", "view", "deny")])
    )
    res = await client.get(url, headers=_auth(no_gs))
    assert res.status_code == 403
    # Pending uploads have no download URL.
    pending = await upload(
        client, storage, actors.aman, gs_id, "DOC_PHOTO", "image/png", confirm=False
    )
    res = await client.get(
        f"/api/v1/attachments/{pending['attachment']['id']}/download-url",
        headers=_auth(actors.aman),
    )
    assert res.status_code == 409


def photo_path(conn: Connection, att_id: str) -> str:
    return str(
        fetch_all(conn, "select object_path from public.attachments where id = :i", i=att_id)[0][
            "object_path"
        ]
    )


# --- delete --------------------------------------------------------------------------------------
async def test_delete_rules(
    client: AsyncClient,
    actors: Actors,
    masters: Masters,
    storage: FakeStorage,
    users: UserFactory,
    make_token: JwtFactory,
    db_conn: Connection,
) -> None:
    gs_id = await started_gs(client, actors, masters)
    other = make_token(users.create(roles=["INWARD_VERIFIER"], full_name="Other verifier"))
    photo = await upload(client, storage, actors.aman, gs_id, "DOC_PHOTO", "image/png")
    res = await client.delete(f"/api/v1/attachments/{photo['id']}", headers=_auth(other))
    assert res.status_code == 403 and res.json()["error"]["code"] == "NOT_UPLOADER"
    await classify(client, actors.aman, gs_id, photo["id"], INVOICE)
    path = photo_path(db_conn, photo["id"])
    res = await client.delete(f"/api/v1/attachments/{photo['id']}", headers=_auth(actors.aman))
    assert res.status_code == 204
    assert ("rms-documents", path) in storage.deleted
    # The classification went with the photo (cascade); the delete is audited with a reason.
    assert not fetch_all(db_conn, "select 1 from public.gs_documents where gs_id = :g", g=gs_id)
    audit = fetch_all(
        db_conn,
        "select reason from public.audit_log where table_name = 'public.attachments' "
        "and action = 'DELETE' and row_id = :r",
        r=photo["id"],
    )
    assert audit and audit[0]["reason"]
    # Another performer may discard a PENDING upload.
    pending = await upload(
        client, storage, actors.aman, gs_id, "DOC_PHOTO", "image/png", confirm=False
    )
    res = await client.delete(
        f"/api/v1/attachments/{pending['attachment']['id']}", headers=_auth(other)
    )
    assert res.status_code == 204


# --- Accounts queue (BR-06, DEC-05) --------------------------------------------------------------
async def test_accounts_queue_and_acknowledge(
    client: AsyncClient, actors: Actors, masters: Masters, storage: FakeStorage
) -> None:
    gs_id = await started_gs(client, actors, masters)
    await upload_videos(client, storage, actors.aman, gs_id)
    photo = await upload(client, storage, actors.aman, gs_id, "DOC_PHOTO", "image/jpeg")
    await classify(client, actors.aman, gs_id, photo["id"], INVOICE)

    def ids(res: Any) -> set[str]:
        return {i["gs_id"] for i in res.json()["items"]}

    queue = "/api/v1/accounts/document-queue"
    # Not listed while still UNBOXING.
    assert gs_id not in ids(await client.get(queue, headers=_auth(actors.accounts)))
    assert (await complete(client, actors.aman, gs_id)).status_code == 200

    res = await client.get(queue, headers=_auth(actors.accounts))
    assert res.status_code == 200 and gs_id in ids(res)
    item = next(i for i in res.json()["items"] if i["gs_id"] == gs_id)
    assert item["documents"][0]["classification_code"] == "INVOICE"
    assert item["documents"][0]["buyer_gstin"] == INVOICE["buyer_gstin"]
    assert gs_id in ids(
        await client.get(
            queue, params={"classification": "INVOICE"}, headers=_auth(actors.accounts)
        )
    )
    assert gs_id not in ids(
        await client.get(
            queue, params={"classification": "DEBIT_NOTE"}, headers=_auth(actors.accounts)
        )
    )
    opts = await client.get(f"{queue}/classifications", headers=_auth(actors.accounts))
    assert [o["code"] for o in opts.json()] == [
        "INVOICE",
        "DEBIT_NOTE",
        "DELIVERY_CHALLAN",
        "HANDWRITTEN_SLIP",
    ]
    # Aman cannot see the Accounts queue; RM (credit_notes.view) can see but not acknowledge.
    assert (await client.get(queue, headers=_auth(actors.aman))).status_code == 403
    ack = f"{queue}/{gs_id}/acknowledge"
    assert (await client.post(ack, headers=_auth(actors.rm))).status_code == 403
    res = await client.post(ack, headers=_auth(actors.accounts))
    assert res.status_code == 200 and res.json()["acknowledged"] == 1
    assert gs_id not in ids(await client.get(queue, headers=_auth(actors.accounts)))
    assert (await client.post(ack, headers=_auth(actors.accounts))).status_code == 409

    # The bell API lists the alert for Accounts and marks it read.
    mine = await client.get("/api/v1/notifications/mine", headers=_auth(actors.accounts))
    assert mine.status_code == 200
    note = next(n for n in mine.json()["items"] if n["entity_id"] == gs_id)
    assert mine.json()["unread_count"] >= 1
    res = await client.post(
        f"/api/v1/notifications/{note['id']}/read", headers=_auth(actors.accounts)
    )
    assert res.json() == {"updated": 1}
    # Someone else's notification cannot be marked.
    res = await client.post(f"/api/v1/notifications/{note['id']}/read", headers=_auth(actors.rm))
    assert res.json() == {"updated": 0}


# --- DEC-04 per-box video toggle -----------------------------------------------------------------
async def test_video_per_box_setting(
    client: AsyncClient, actors: Actors, masters: Masters, storage: FakeStorage, db_conn: Connection
) -> None:
    as_admin(db_conn).execute(
        text(
            "update public.system_settings set value = 'true' where key = 'unboxing_video_per_box'"
        )
    )
    gs_id = await started_gs(client, actors, masters)  # 3 boxes
    await upload(client, storage, actors.aman, gs_id, "UNBOXING_VIDEO", "video/mp4", box_no=1)
    photo = await upload(client, storage, actors.aman, gs_id, "DOC_PHOTO", "image/png")
    await classify(client, actors.aman, gs_id, photo["id"], INVOICE)
    res = await complete(client, actors.aman, gs_id)
    assert res.status_code == 422
    assert res.json()["error"]["details"]["missing"] == ["VIDEO_PER_CARTON"]
    assert res.json()["error"]["details"]["checklist"]["boxes_missing_video"] == [2, 3]


# --- worker: stale PENDING_UPLOAD cleanup --------------------------------------------------------
async def test_cleanup_stale_pending_uploads(
    client: AsyncClient,
    actors: Actors,
    masters: Masters,
    storage: FakeStorage,
    session_factory: sessionmaker[Session],
    db_conn: Connection,
) -> None:
    gs_id = await started_gs(client, actors, masters)
    old = await upload(client, storage, actors.aman, gs_id, "DOC_PHOTO", "image/png", confirm=False)
    fresh = await upload(
        client, storage, actors.aman, gs_id, "DOC_PHOTO", "image/png", confirm=False
    )
    kept = await upload(client, storage, actors.aman, gs_id, "DOC_PHOTO", "image/png")
    as_admin(db_conn).execute(
        text(
            "update public.attachments set created_at = now() - interval '25 hours' "
            "where id = any(:ids)"
        ),
        {"ids": [old["attachment"]["id"], kept["id"]]},
    )
    service = AttachmentService(UnitOfWork(session_factory), storage)  # type: ignore[arg-type]
    assert service.cleanup_stale_pending(now=datetime.now(UTC) + timedelta(minutes=1)) == 1
    left = {
        r["id"]
        for r in fetch_all(
            db_conn, "select id::text from public.attachments where gs_id = :g", g=gs_id
        )
    }
    assert old["attachment"]["id"] not in left
    assert {fresh["attachment"]["id"], kept["id"]} <= left
    assert ("rms-documents", old["upload"]["object_path"]) in storage.deleted
