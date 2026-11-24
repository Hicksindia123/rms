"""E-Commerce Returns (DEC-73): gate entry, media, ticket lifecycle, roles and DB guards.

Storage is the in-memory FakeStorage of test_unboxing (`put` plays the browser upload). The DB is
the local Supabase Postgres, rolled back per test.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import get_session_factory
from app.core.middleware import limiter
from app.shared.storage import get_storage
from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, build_test_app, fetch_all
from tests.integration.test_unboxing import FakeStorage

MB = 1024 * 1024
BASE = "/api/v1/ecommerce-returns"
TICKETS = "/api/v1/ecommerce-tickets"


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


@dataclass
class Actors:
    gate: str
    gate_id: uuid.UUID
    handler: str
    handler_id: uuid.UUID
    mgmt: str
    mgmt_id: uuid.UUID
    offline_gate: str


@pytest.fixture
def actors(users: UserFactory, make_token: JwtFactory) -> Actors:
    gate_id = users.create(roles=["ECOM_GATE"], full_name="Ecom Gate")
    handler_id = users.create(roles=["TICKET_HANDLER"], full_name="Ticket Handler")
    mgmt_id = users.create(roles=["MANAGEMENT"], full_name="Mgmt")
    return Actors(
        gate=make_token(gate_id),
        gate_id=gate_id,
        handler=make_token(handler_id),
        handler_id=handler_id,
        mgmt=make_token(mgmt_id),
        mgmt_id=mgmt_id,
        offline_gate=make_token(users.create(roles=["GATE_INWARD"], full_name="Offline Gate")),
    )


@pytest.fixture
def product(db_conn: Connection) -> dict[str, Any]:
    rows = fetch_all(
        as_admin(db_conn),
        """
        select p.id, p.code, p.name from public.products p
          join public.product_categories pc on pc.id = p.category_id
         where p.is_active and pc.is_active order by p.code limit 1
        """,
    )
    assert rows, "the seed has no active product"
    return rows[0]


def _h(token: str, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key:
        headers["Idempotency-Key"] = key
    return headers


def _key() -> str:
    return f"ecom-{uuid.uuid4()}"


def _payload(product: dict[str, Any] | None = None, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "entry_date": date.today().isoformat(),
        "platform_code": "AMAZON",
        "order_id": "408-1234567-7654321",
        "product_type_code": "COMPANY_PRODUCT" if product else "DIFFERENT_PRODUCT",
        "product_id": str(product["id"]) if product else None,
        "different_product_desc": None if product else "A blue plastic toy car",
        "qty": 2,
        "qc_routing_code": "TICKET_RAISE",
        "video": {"mime_type": "video/mp4", "size_bytes": 5 * MB, "file_name": "open.mp4"},
        "images": [],
    }
    base.update(over)
    return base


async def _create(client: AsyncClient, token: str, payload: dict[str, Any]) -> Any:
    return await client.post(BASE, json=payload, headers=_h(token, _key()))


def _upload_all(storage: FakeStorage, created: dict[str, Any]) -> None:
    for up in created["uploads"]:
        storage.put(
            up["upload"]["bucket"],
            up["upload"]["object_path"],
            up["media"]["size_bytes"],
            up["media"]["mime_type"],
        )


async def _confirm_all(client: AsyncClient, token: str, created: dict[str, Any]) -> None:
    rid = created["ecommerce_return"]["id"]
    for up in created["uploads"]:
        res = await client.post(
            f"{BASE}/{rid}/media/{up['media']['id']}/confirm",
            json={"object_path": up["upload"]["object_path"]},
            headers=_h(token),
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "CONFIRMED"


async def _submitted(
    client: AsyncClient, storage: FakeStorage, token: str, payload: dict[str, Any]
) -> dict[str, Any]:
    res = await _create(client, token, payload)
    assert res.status_code == 201, res.text
    created = res.json()
    _upload_all(storage, created)
    await _confirm_all(client, token, created)
    res = await client.post(
        f"{BASE}/{created['ecommerce_return']['id']}/submit", headers=_h(token, _key())
    )
    assert res.status_code == 200, res.text
    return dict(res.json())


# --- form + permissions -----------------------------------------------------------------------
async def test_form_config_comes_from_configuration(client: AsyncClient, actors: Actors) -> None:
    res = await client.get(f"{BASE}/form-config", headers=_h(actors.gate))
    assert res.status_code == 200, res.text
    body = res.json()
    assert [p["code"] for p in body["platforms"]] == ["AMAZON", "FLIPKART", "WEBSITE"]
    assert {o["code"] for o in body["return_types"]} >= {"OFFLINE_RETURN", "ECOMMERCE_RETURN"}
    assert [o["code"] for o in body["qc_routings"]] == ["TICKET_RAISE", "ISSUE_TO_CHECKING"]
    assert body["images"]["max_total_bytes"] == 50 * MB
    assert body["video"]["mime_types"] == ["video/mp4", "video/quicktime"]
    assert body["ticket_sla_hours"] == 2
    # The offline gate user does not record e-commerce returns (DEC-73 Q: new ECOM_GATE role).
    res = await client.get(f"{BASE}/form-config", headers=_h(actors.offline_gate))
    assert res.status_code == 403


async def test_admin_added_platform_is_accepted(
    client: AsyncClient, actors: Actors, db_conn: Connection
) -> None:
    as_admin(db_conn).execute(
        text(
            """
            insert into public.option_items (option_set_id, code, label, sort_order)
            select id, 'MEESHO', 'Meesho', 40 from public.option_sets where code = 'ECOM_PLATFORM'
            """
        )
    )
    res = await _create(client, actors.gate, _payload(platform_code="MEESHO"))
    assert res.status_code == 201, res.text
    assert res.json()["ecommerce_return"]["platform_label"] == "Meesho"


# --- validation -------------------------------------------------------------------------------
async def test_validation_errors_name_the_fields(client: AsyncClient, actors: Actors) -> None:
    tomorrow = (date.today() + timedelta(days=3)).isoformat()
    res = await _create(
        client,
        actors.gate,
        _payload(
            entry_date=tomorrow,
            platform_code="EBAY",
            order_id="bad id!",
            different_product_desc="  ",
            video={"mime_type": "video/webm", "size_bytes": MB, "file_name": "a.webm"},
            images=[
                {"mime_type": "image/gif", "size_bytes": MB, "file_name": "a.gif"},
                {"mime_type": "image/jpeg", "size_bytes": 30 * MB, "file_name": "b.jpg"},
            ],
        ),
    )
    assert res.status_code == 422, res.text
    details = res.json()["error"]["details"]
    for field in (
        "entry_date",
        "platform_code",
        "order_id",
        "different_product_desc",
        "video",
        "images.0",
        "images.1",
    ):
        assert field in details, (field, details)


async def test_company_product_requires_the_product(client: AsyncClient, actors: Actors) -> None:
    res = await _create(
        client,
        actors.gate,
        _payload(product_type_code="COMPANY_PRODUCT", product_id=None, different_product_desc="x"),
    )
    assert res.status_code == 422
    assert "product_id" in res.json()["error"]["details"]


async def test_images_combined_limit_is_50_mb(client: AsyncClient, actors: Actors) -> None:
    images = [
        {"mime_type": "image/jpeg", "size_bytes": 20 * MB, "file_name": f"{i}.jpg"}
        for i in range(3)
    ]
    res = await _create(client, actors.gate, _payload(images=images))
    assert res.status_code == 422
    assert "images" in res.json()["error"]["details"]
    res = await _create(client, actors.gate, _payload(images=images[:2]))
    assert res.status_code == 201, res.text


async def test_video_is_mandatory(client: AsyncClient, actors: Actors) -> None:
    payload = _payload()
    del payload["video"]
    res = await _create(client, actors.gate, payload)
    assert res.status_code == 422


# --- ticket path ------------------------------------------------------------------------------
async def test_ticket_path_end_to_end(
    client: AsyncClient,
    actors: Actors,
    storage: FakeStorage,
    product: dict[str, Any],
    db_conn: Connection,
) -> None:
    images = [
        {"mime_type": "image/png", "size_bytes": 2 * MB, "file_name": f"{i}.png"} for i in range(2)
    ]
    res = await _create(client, actors.gate, _payload(product, images=images))
    assert res.status_code == 201, res.text
    created = res.json()
    ret = created["ecommerce_return"]
    rid = ret["id"]
    assert ret["status"] == "DRAFT" and ret["return_no"].startswith("ECR/")
    assert ret["product_code"] == product["code"] and ret["different_product_desc"] is None
    assert len(created["uploads"]) == 3
    assert {u["media"]["kind"] for u in created["uploads"]} == {"PACKAGE_VIDEO", "IMAGE"}

    # Submit is refused until the video is uploaded and confirmed.
    res = await client.post(f"{BASE}/{rid}/submit", headers=_h(actors.gate, _key()))
    assert res.status_code == 409 and res.json()["error"]["code"] == "ECOM_VIDEO_REQUIRED"

    _upload_all(storage, created)
    await _confirm_all(client, actors.gate, created)
    res = await client.post(f"{BASE}/{rid}/submit", headers=_h(actors.gate, _key()))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "PENDING_TICKET"
    ticket = body["ticket"]
    assert ticket["raised_at"] is None and ticket["sla_state"] == "ON_TIME"
    due = datetime.fromisoformat(ticket["sla_due_at"])
    assert timedelta(minutes=110) < due - datetime.now(UTC) <= timedelta(hours=2, minutes=1)
    tid = ticket["id"]

    # Only a Ticket Handler works the ticket.
    res = await client.post(f"{TICKETS}/{tid}/raise", headers=_h(actors.gate, _key()))
    assert res.status_code == 403
    queue = await client.get(TICKETS, headers=_h(actors.handler))
    assert queue.status_code == 200
    assert any(r["ticket"]["id"] == tid for r in queue.json()["rows"])

    # Response before raising is refused.
    res = await client.post(
        f"{TICKETS}/{tid}/response",
        json={"response_code": "PENDING"},
        headers=_h(actors.handler, _key()),
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "ECOM_TICKET_NOT_RAISED"

    res = await client.post(f"{TICKETS}/{tid}/raise", headers=_h(actors.handler, _key()))
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "TICKET_RAISED"
    assert res.json()["ticket"]["assigned_handler_name"] == "Ticket Handler"
    assert res.json()["ticket"]["sla_state"] == "RAISED_ON_TIME"

    res = await client.post(f"{TICKETS}/{tid}/close", headers=_h(actors.handler, _key()))
    assert res.status_code == 409 and res.json()["error"]["code"] == "ECOM_TICKET_NO_RESPONSE"

    res = await client.post(
        f"{TICKETS}/{tid}/response",
        json={"response_code": "PENDING"},
        headers=_h(actors.handler, _key()),
    )
    assert res.status_code == 200 and res.json()["ticket"]["response_code"] == "PENDING"
    res = await client.post(f"{TICKETS}/{tid}/close", headers=_h(actors.handler, _key()))
    assert res.status_code == 409 and res.json()["error"]["code"] == "ECOM_TICKET_PENDING"

    res = await client.post(
        f"{TICKETS}/{tid}/response",
        json={"response_code": "REJECTED"},
        headers=_h(actors.handler, _key()),
    )
    assert res.status_code == 422 and "rejection_remark" in res.json()["error"]["details"]
    res = await client.post(
        f"{TICKETS}/{tid}/response",
        json={"response_code": "CLAIM_RECEIVED"},
        headers=_h(actors.handler, _key()),
    )
    assert res.status_code == 422 and "claim_amount" in res.json()["error"]["details"]

    res = await client.post(
        f"{TICKETS}/{tid}/response",
        json={"response_code": "CLAIM_RECEIVED", "claim_amount": "1499.50"},
        headers=_h(actors.handler, _key()),
    )
    assert res.status_code == 200, res.text
    assert res.json()["ticket"]["claim_amount"] == "1499.50"

    close_key = _key()
    res = await client.post(f"{TICKETS}/{tid}/close", headers=_h(actors.handler, close_key))
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "CLOSED" and res.json()["closed_at"]
    # G-16 pattern: the same key replays the original result.
    again = await client.post(f"{TICKETS}/{tid}/close", headers=_h(actors.handler, close_key))
    assert again.status_code == 200 and again.headers.get("Idempotency-Replayed") == "true"

    detail = await client.get(f"{BASE}/{rid}", headers=_h(actors.mgmt))
    events = [e["event_code"] for e in detail.json()["events"]]
    assert events == [
        "CREATED",
        "TICKET_QUEUED",
        "TICKET_RAISED",
        "TICKET_RESPONSE",
        "TICKET_RESPONSE",
        "TICKET_CLOSED",
    ]
    # A closed return cannot be voided.
    res = await client.post(
        f"{BASE}/{rid}/void", json={"reason": "late void"}, headers=_h(actors.mgmt, _key())
    )
    assert res.status_code == 409
    # G-17: audited.
    audited = fetch_all(
        as_admin(db_conn),
        "select count(*) as n from public.audit_log where table_name = 'public.ecommerce_tickets' "
        "and row_id::text = cast(:id as text)",
        id=tid,
    )
    assert audited[0]["n"] >= 4


async def test_rejected_ticket_closes_with_remark(
    client: AsyncClient, actors: Actors, storage: FakeStorage
) -> None:
    body = await _submitted(client, storage, actors.gate, _payload())
    tid = body["ticket"]["id"]
    await client.post(f"{TICKETS}/{tid}/raise", headers=_h(actors.handler, _key()))
    res = await client.post(
        f"{TICKETS}/{tid}/response",
        json={"response_code": "REJECTED", "rejection_remark": "Customer damage, not covered"},
        headers=_h(actors.handler, _key()),
    )
    assert res.status_code == 200, res.text
    res = await client.post(f"{TICKETS}/{tid}/close", headers=_h(actors.handler, _key()))
    assert res.status_code == 200 and res.json()["status"] == "CLOSED"
    res = await client.post(
        f"{TICKETS}/{tid}/response",
        json={"response_code": "PENDING"},
        headers=_h(actors.handler, _key()),
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "ECOM_TICKET_CLOSED"


# --- checking path + void ---------------------------------------------------------------------
async def test_issue_to_checking_stays_open_and_can_be_voided(
    client: AsyncClient, actors: Actors, storage: FakeStorage
) -> None:
    body = await _submitted(
        client, storage, actors.gate, _payload(qc_routing_code="ISSUE_TO_CHECKING")
    )
    assert body["status"] == "IN_CHECKING" and body["ticket"] is None
    assert body["different_product_desc"] == "A blue plastic toy car"
    res = await client.post(
        f"{BASE}/{body['id']}/void",
        json={"reason": "Entered twice"},
        headers=_h(actors.gate, _key()),
    )
    assert res.status_code == 403
    res = await client.post(
        f"{BASE}/{body['id']}/void",
        json={"reason": "Entered twice"},
        headers=_h(actors.mgmt, _key()),
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "VOIDED" and res.json()["void_reason"] == "Entered twice"


# --- media ------------------------------------------------------------------------------------
async def test_upload_mismatch_is_rejected_and_video_can_be_replaced(
    client: AsyncClient, actors: Actors, storage: FakeStorage
) -> None:
    res = await _create(client, actors.gate, _payload())
    created = res.json()
    rid = created["ecommerce_return"]["id"]
    up = created["uploads"][0]
    storage.put(up["upload"]["bucket"], up["upload"]["object_path"], 123, "video/mp4")
    res = await client.post(
        f"{BASE}/{rid}/media/{up['media']['id']}/confirm", json={}, headers=_h(actors.gate)
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "UPLOAD_MISMATCH"
    assert (up["upload"]["bucket"], up["upload"]["object_path"]) in storage.deleted

    res = await client.post(
        f"{BASE}/{rid}/media?kind=PACKAGE_VIDEO",
        json={"mime_type": "video/quicktime", "size_bytes": 3 * MB, "file_name": "open.mov"},
        headers=_h(actors.gate),
    )
    assert res.status_code == 201, res.text
    new = res.json()
    storage.put(new["upload"]["bucket"], new["upload"]["object_path"], 3 * MB, "video/quicktime")
    res = await client.post(
        f"{BASE}/{rid}/media/{new['media']['id']}/confirm", json={}, headers=_h(actors.gate)
    )
    assert res.status_code == 200
    res = await client.post(f"{BASE}/{rid}/submit", headers=_h(actors.gate, _key()))
    assert res.status_code == 200 and res.json()["status"] == "PENDING_TICKET"


async def test_failed_image_blocks_submit_until_removed(
    client: AsyncClient, actors: Actors, storage: FakeStorage
) -> None:
    images = [{"mime_type": "image/jpeg", "size_bytes": MB, "file_name": "a.jpg"}]
    res = await _create(client, actors.gate, _payload(images=images))
    created = res.json()
    rid = created["ecommerce_return"]["id"]
    video, image = created["uploads"]
    storage.put(video["upload"]["bucket"], video["upload"]["object_path"], 5 * MB, "video/mp4")
    await client.post(
        f"{BASE}/{rid}/media/{video['media']['id']}/confirm", json={}, headers=_h(actors.gate)
    )
    res = await client.post(f"{BASE}/{rid}/submit", headers=_h(actors.gate, _key()))
    assert res.status_code == 409 and res.json()["error"]["code"] == "ECOM_MEDIA_PENDING"
    res = await client.post(
        f"{BASE}/{rid}/media/{image['media']['id']}/upload-url", headers=_h(actors.gate)
    )
    assert res.status_code == 200
    res = await client.post(
        f"{BASE}/{rid}/media/{image['media']['id']}/discard", headers=_h(actors.gate)
    )
    assert res.status_code == 200 and res.json()["status"] == "REJECTED"
    res = await client.post(f"{BASE}/{rid}/submit", headers=_h(actors.gate, _key()))
    assert res.status_code == 200, res.text


async def test_order_check_lists_earlier_returns(client: AsyncClient, actors: Actors) -> None:
    res = await _create(client, actors.gate, _payload(order_id="OD12345ABC"))
    assert res.status_code == 201
    res = await client.get(
        f"{BASE}/order-check",
        params={"platform_code": "AMAZON", "order_id": "od12345abc"},
        headers=_h(actors.gate),
    )
    assert res.status_code == 200
    assert [m["return_no"] for m in res.json()] == [
        (await client.get(BASE, params={"q": "OD12345ABC"}, headers=_h(actors.gate))).json()[
            "rows"
        ][0]["return_no"]
    ]
    # Repeats are allowed (DEC-73 Q2).
    assert (await _create(client, actors.gate, _payload(order_id="OD12345ABC"))).status_code == 201


# --- DB guards (service bypassed) -------------------------------------------------------------
def _db_return(conn: Connection, users: UserFactory, actor: uuid.UUID, routing: str) -> uuid.UUID:
    users.set_actor(actor)
    rid = conn.execute(
        text(
            """
            insert into public.ecommerce_returns
              (return_no, entry_date, platform_code, platform_label, order_id, product_type_code,
               product_type_label, different_product_desc, qty, qc_routing_code, qc_routing_label)
            values (:no, current_date, 'AMAZON', 'Amazon', 'ORDER1', 'DIFFERENT_PRODUCT',
                    'Different Product', 'Something else', 1, :routing, 'x')
            returning id
            """
        ),
        {"no": f"T-{uuid.uuid4().hex[:8]}", "routing": routing},
    ).scalar_one()
    return uuid.UUID(str(rid))


def _confirmed_video(conn: Connection, rid: uuid.UUID) -> None:
    mid = conn.execute(
        text(
            """
            insert into public.ecommerce_return_media (return_id, kind, bucket, object_path,
              mime_type, size_bytes)
            values (:rid, 'PACKAGE_VIDEO', 'rms-videos', :path, 'video/mp4', 10) returning id
            """
        ),
        {"rid": rid, "path": f"ecom/{rid}/package_video/{uuid.uuid4()}.mp4"},
    ).scalar_one()
    conn.execute(
        text(
            "update public.ecommerce_return_media set status='CONFIRMED', confirmed_at=now() "
            "where id=:id"
        ),
        {"id": mid},
    )


def test_db_guards_refuse_forbidden_changes(
    db_conn: Connection, users: UserFactory, actors: Actors
) -> None:
    conn = as_admin(db_conn)
    rid = _db_return(conn, users, actors.gate_id, "TICKET_RAISE")

    # Leaving DRAFT without the confirmed video.
    with pytest.raises(DBAPIError, match="ECOM_VIDEO_REQUIRED"), conn.begin_nested():
        conn.execute(
            text(
                "update public.ecommerce_returns set status='PENDING_TICKET', submitted_at=now() "
                "where id=:id"
            ),
            {"id": rid},
        )
    # The gate entry is never edited.
    with pytest.raises(DBAPIError, match="ECOM_RETURN_IMMUTABLE"), conn.begin_nested():
        conn.execute(
            text("update public.ecommerce_returns set order_id='OTHER' where id=:id"), {"id": rid}
        )

    _confirmed_video(conn, rid)
    conn.execute(
        text(
            "update public.ecommerce_returns set status='PENDING_TICKET', submitted_at=now() "
            "where id=:id"
        ),
        {"id": rid},
    )
    conn.execute(
        text("insert into public.ecommerce_tickets (return_id, sla_due_at) values (:id, now())"),
        {"id": rid},
    )
    tid = conn.execute(
        text("select id from public.ecommerce_tickets where return_id=:id"), {"id": rid}
    ).scalar_one()

    # A non-handler cannot work the ticket.
    with pytest.raises(DBAPIError, match="ECOM_FORBIDDEN"), conn.begin_nested():
        conn.execute(
            text(
                "update public.ecommerce_tickets set raised_at=now(), assigned_handler_id=:u "
                "where id=:id"
            ),
            {"id": tid, "u": actors.gate_id},
        )
    users.set_actor(actors.handler_id)
    conn.execute(
        text(
            "update public.ecommerce_tickets set raised_at=now(), assigned_handler_id=:u where "
            "id=:id"
        ),
        {"id": tid, "u": actors.handler_id},
    )
    assert (
        conn.execute(
            text("select status from public.ecommerce_returns where id=:id"), {"id": rid}
        ).scalar_one()
        == "TICKET_RAISED"
    )

    # Rejected without a remark / claim without an amount (CHECKs).
    with pytest.raises(DBAPIError, match="ecommerce_tickets_rejection_remark"), conn.begin_nested():
        conn.execute(
            text(
                "update public.ecommerce_tickets set response_code='REJECTED', "
                "response_label='Rejected', responded_at=now() where id=:id"
            ),
            {"id": tid},
        )
    with pytest.raises(DBAPIError, match="ecommerce_tickets_claim_amount"), conn.begin_nested():
        conn.execute(
            text(
                "update public.ecommerce_tickets set response_code='CLAIM_RECEIVED', "
                "response_label='C', responded_at=now() where id=:id"
            ),
            {"id": tid},
        )
    # Never closed while PENDING.
    conn.execute(
        text(
            "update public.ecommerce_tickets set response_code='PENDING', "
            "response_label='Pending', responded_at=now() where id=:id"
        ),
        {"id": tid},
    )
    with pytest.raises(DBAPIError, match="ECOM_TICKET_PENDING"), conn.begin_nested():
        conn.execute(
            text("update public.ecommerce_tickets set closed_at=now(), closed_by=:u where id=:id"),
            {"id": tid, "u": actors.handler_id},
        )
    # The return cannot be closed past its ticket.
    with pytest.raises(DBAPIError, match="ECOM_INVALID_TRANSITION"), conn.begin_nested():
        conn.execute(
            text(
                "update public.ecommerce_returns set status='CLOSED', closed_at=now() where id=:id"
            ),
            {"id": rid},
        )
    # The SLA cannot be moved.
    with pytest.raises(DBAPIError, match="ECOM_RETURN_IMMUTABLE"), conn.begin_nested():
        conn.execute(
            text(
                "update public.ecommerce_tickets set sla_due_at = sla_due_at + interval '1 day' "
                "where id=:id"
            ),
            {"id": tid},
        )
    # History is append-only.
    conn.execute(
        text(
            "insert into public.ecommerce_return_events (return_id, event_code) values (:id, 'X')"
        ),
        {"id": rid},
    )
    with pytest.raises(DBAPIError, match="ECOM_RETURN_IMMUTABLE"), conn.begin_nested():
        conn.execute(
            text("delete from public.ecommerce_return_events where return_id=:id"), {"id": rid}
        )
    users.set_actor(None)


def test_db_guard_in_checking_has_no_exit_and_only_managers_void(
    db_conn: Connection, users: UserFactory, actors: Actors
) -> None:
    conn = as_admin(db_conn)
    rid = _db_return(conn, users, actors.gate_id, "ISSUE_TO_CHECKING")
    _confirmed_video(conn, rid)
    with pytest.raises(DBAPIError, match="ECOM_INVALID_TRANSITION"), conn.begin_nested():
        conn.execute(
            text(
                "update public.ecommerce_returns set status='PENDING_TICKET', submitted_at=now() "
                "where id=:id"
            ),
            {"id": rid},
        )
    conn.execute(
        text(
            "update public.ecommerce_returns set status='IN_CHECKING', submitted_at=now() where "
            "id=:id"
        ),
        {"id": rid},
    )
    # Extension point: no exit from IN_CHECKING yet.
    with pytest.raises(DBAPIError, match="ECOM_INVALID_TRANSITION"), conn.begin_nested():
        conn.execute(
            text(
                "update public.ecommerce_returns set status='CLOSED', closed_at=now() where id=:id"
            ),
            {"id": rid},
        )
    # No ticket on the checking route.
    with pytest.raises(DBAPIError, match="ECOM_INVALID_STATE"), conn.begin_nested():
        conn.execute(
            text(
                "insert into public.ecommerce_tickets (return_id, sla_due_at) values (:id, now())"
            ),
            {"id": rid},
        )
    # The gate user cannot void.
    with pytest.raises(DBAPIError, match="ECOM_FORBIDDEN"), conn.begin_nested():
        conn.execute(
            text(
                "update public.ecommerce_returns set status='VOIDED', voided_at=now(), "
                "voided_by=:u, void_reason='abc' where id=:id"
            ),
            {"id": rid, "u": actors.gate_id},
        )
    users.set_actor(actors.mgmt_id)
    conn.execute(
        text(
            "update public.ecommerce_returns set status='VOIDED', voided_at=now(), voided_by=:u, "
            "void_reason='abc' where id=:id"
        ),
        {"id": rid, "u": actors.mgmt_id},
    )
    # No new media on a non-DRAFT return; nothing is deleted.
    users.set_actor(actors.gate_id)
    with pytest.raises(DBAPIError, match="ECOM_INVALID_STATE"), conn.begin_nested():
        _confirmed_video(conn, rid)
    with pytest.raises(DBAPIError, match="ECOM_RETURN_IMMUTABLE"), conn.begin_nested():
        conn.execute(text("delete from public.ecommerce_returns where id=:id"), {"id": rid})
    users.set_actor(None)


def test_db_guard_images_total_cap(db_conn: Connection, users: UserFactory, actors: Actors) -> None:
    conn = as_admin(db_conn)
    rid = _db_return(conn, users, actors.gate_id, "TICKET_RAISE")
    sql = text(
        """
        insert into public.ecommerce_return_media (return_id, kind, bucket, object_path,
          mime_type, size_bytes)
        values (:rid, 'IMAGE', 'rms-documents', :path, 'image/jpeg', :size)
        """
    )
    conn.execute(sql, {"rid": rid, "path": f"ecom/{rid}/image/{uuid.uuid4()}.jpg", "size": 40 * MB})
    with pytest.raises(DBAPIError, match="ECOM_IMAGES_TOO_LARGE"), conn.begin_nested():
        conn.execute(
            sql, {"rid": rid, "path": f"ecom/{rid}/image/{uuid.uuid4()}.jpg", "size": 11 * MB}
        )
    users.set_actor(None)
