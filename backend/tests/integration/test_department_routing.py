"""Integration tests for Phase 6 (Change plan 2026-11-12; AMD-10, AMD-14, AMD-15; DEC-42,
DEC-43; Guard G-20).

1. RM routing queue: all GSs held at intermediate store; per item/bucket RM sends qty to
   departments allowed by resolved profile (Phase 4). One routing document per department
   (printable DIN issue note), stock moved via rms_move_stock.
2. Department receiving (INWARD_VERIFIER default, DEC-42): receive back per routing line into
   outcome
   heads (Repaired, Not Repaired, Wastage, Send to Mercury Extraction, Re-route); partial receipts
   allowed; lines with returns_to_routing=true return to RM routing queue (DEC-43).
3. Reconciliation guard (G-20): for every GS item,
   counted = in_store + at_departments + outcome_heads + actioned.
   Enforced in DB + service, with a per-GS reconciliation panel.
4. GS timeline shows each department leg (sent / received / pending).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import get_session_factory
from app.core.middleware import limiter
from app.shared.storage import get_storage
from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, build_test_app
from tests.integration.test_gate_inward import Masters, _auth
from tests.integration.test_itemization import FakeStorage


def _key() -> str:
    """A fresh Idempotency-Key (G-16) for one stock-moving command."""
    return f"test-ph6-{uuid.uuid4().hex}"


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


@pytest.fixture
def actors(users: UserFactory, make_token: JwtFactory) -> dict[str, Any]:
    aman_id = users.create(roles=["INWARD_VERIFIER"], full_name="Aman")
    rm_id = users.create(roles=["REPLACEMENT_MANAGER"], full_name="Pratham")
    store_id = users.create(roles=["INTERMEDIATE_STORE_MANAGER"], full_name="Sanjay")
    tech_id = users.create(roles=["TECHNICIAN"], full_name="Ramesh")
    return {
        "aman": make_token(aman_id),
        "aman_id": str(aman_id),
        "rm": make_token(rm_id),
        "rm_id": str(rm_id),
        "store": make_token(store_id),
        "store_id": str(store_id),
        "tech": make_token(tech_id),
        "tech_id": str(tech_id),
        "admin": make_token(users.create(super_admin=True, full_name="Admin")),
    }


def _seed_gs_held_at_intermediate_store(conn: Connection) -> dict[str, Any]:
    """Helper: insert a GS directly into HELD_AT_INTERMEDIATE_STORE with 1 item of 10 pcs."""
    c = as_admin(conn)
    c.execute(text("set session_replication_role = 'replica'"))
    tag = uuid.uuid4().hex[:6].upper()

    # Get product with resolved department profile
    prod_row = (
        c.execute(
            text(
                """
            insert into public.products (code, name, category_id)
            select :code, :name, id from public.product_categories where code = 'DMT'
            returning id, category_id
            """
            ),
            {"code": f"PROD-PH6-{tag}", "name": f"Ph6 Test Thermometer {tag}"},
        )
        .mappings()
        .first()
    )
    assert prod_row is not None
    product_id = str(prod_row["id"])
    category_id = str(prod_row["category_id"])

    # Ensure profile has REPAIR and MERCURY_EXTRACTION departments for this category
    repair_dept_id = c.execute(
        text(
            "select id from public.item_field_library"
            " where field_group = 'DEPARTMENT' and code = 'REPAIR'"
        )
    ).scalar_one()

    c.execute(
        text(
            """
            insert into public.item_field_assignments
              (field_id, field_group, scope_type, category_id, is_included)
            values (:field_id, 'DEPARTMENT', 'CATEGORY', :cat_id, true)
            on conflict do nothing
            """
        ),
        {"field_id": repair_dept_id, "cat_id": category_id},
    )

    # Insert GS in HELD_AT_INTERMEDIATE_STORE
    gs_id = str(uuid.uuid4())
    gs_no = f"GS-PH6-{tag}"
    c.execute(
        text(
            """
            insert into public.goods_slips (
              id, gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no,
              carton_count, box_count, status
            )
            select
              cast(:gs_id as uuid), :gs_no, v.id, 'COURIER_PARCEL', 'Test Courier', '123', 1, 1,
              'HELD_AT_INTERMEDIATE_STORE'
              from public.workflow_versions v
              join public.workflow_definitions d
                on d.id = v.workflow_definition_id and d.code = 'RMS_STANDARD'
             where v.status = 'PUBLISHED'
             limit 1
            """
        ),
        {"gs_id": gs_id, "gs_no": gs_no},
    )

    # Insert item with 10 pcs
    item_id = str(uuid.uuid4())
    c.execute(
        text(
            """
            insert into public.gs_items (
              id, gs_id, line_no, product_id, category_id, documented_qty, received_qty,
              product_name_snapshot, product_code_snapshot
            ) values (
              cast(:item_id as uuid), cast(:gs_id as uuid), 1, cast(:prod_id as uuid),
              cast(:cat_id as uuid), 10, 10, 'Ph6 Test Thermometer', :sku
            )
            """
        ),
        {
            "item_id": item_id,
            "gs_id": gs_id,
            "prod_id": product_id,
            "cat_id": category_id,
            "sku": f"PROD-PH6-{tag}",
        },
    )

    # Insert inventory lot in INTERMEDIATE_STORE with 10 pcs
    intermediate_loc_id = c.execute(
        text("select id from public.inventory_locations where code = 'INTERMEDIATE_STORE'")
    ).scalar_one()

    stock_item_id = str(uuid.uuid4())
    c.execute(
        text(
            """
            insert into public.stock_items (id, item_kind, product_id)
            values (cast(:sid as uuid), 'FINISHED_GOOD', cast(:prod_id as uuid))
            """
        ),
        {"sid": stock_item_id, "prod_id": product_id},
    )

    lot_id = str(uuid.uuid4())
    c.execute(
        text(
            """
            insert into public.stock_lots (id, stock_item_id, gs_id, gs_item_id, condition_class)
            values (cast(:lot_id as uuid), cast(:sid as uuid), cast(:gs_id as uuid),
                    cast(:item_id as uuid), 'AS_RECEIVED')
            """
        ),
        {"lot_id": lot_id, "sid": stock_item_id, "gs_id": gs_id, "item_id": item_id},
    )

    c.execute(
        text(
            """
            insert into public.stock_balances (lot_id, location_id, qty)
            values (cast(:lot_id as uuid), :loc_id, 10)
            """
        ),
        {"lot_id": lot_id, "loc_id": intermediate_loc_id},
    )

    c.execute(text("set session_replication_role = 'origin'"))

    return {
        "gs_id": gs_id,
        "gs_no": gs_no,
        "item_id": item_id,
        "product_id": product_id,
        "repair_dept_id": str(repair_dept_id),
        "lot_id": lot_id,
    }


# =================================================================================================
# Test Suites
# =================================================================================================


@pytest.mark.asyncio
async def test_rm_routing_queue_and_state(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    """1. RM routing queue lists GSs held at intermediate store; state returns items + depts."""
    fixture = _seed_gs_held_at_intermediate_store(db_conn)
    gs_id = fixture["gs_id"]

    # RM checks routing queue
    res = await client.get("/api/v1/department-routing/queue", headers=_auth(actors["rm"]))
    assert res.status_code == 200, res.text
    queue = res.json()
    assert any(q["gs_id"] == gs_id for q in queue)

    gs_entry = next(q for q in queue if q["gs_id"] == gs_id)
    assert gs_entry["total_counted_qty"] == 10
    assert gs_entry["in_store_qty"] == 10
    assert gs_entry["at_departments_qty"] == 0

    # Get GS routing state
    res_state = await client.get(
        f"/api/v1/department-routing/gs/{gs_id}/state", headers=_auth(actors["rm"])
    )
    assert res_state.status_code == 200, res_state.text
    state = res_state.json()
    assert state["id"] == gs_id
    assert len(state["items"]) == 1
    assert state["items"][0]["counted_qty"] == 10
    assert state["items"][0]["in_store_qty"] == 10
    assert any(d["code"] == "REPAIR" for d in state["items"][0]["allowed_departments"])


@pytest.mark.asyncio
async def test_department_routing_dispatch_and_guard_g20(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    """2. RM dispatches items to allowed department; rejects over-dispatch (Guard G-20)."""
    fixture = _seed_gs_held_at_intermediate_store(db_conn)
    gs_id = fixture["gs_id"]
    item_id = fixture["item_id"]
    repair_dept_id = fixture["repair_dept_id"]

    # Over-dispatch: attempt to send 15 pcs when only 10 counted (G-20 guard violation)
    res_over = await client.post(
        "/api/v1/department-routing/dispatch",
        headers=_auth(actors["rm"], _key()),
        json={
            "gs_id": gs_id,
            "department_field_id": repair_dept_id,
            "lines": [{"gs_item_id": item_id, "qty_sent": 15}],
        },
    )
    assert res_over.status_code in (409, 422), res_over.text
    assert "G-20" in res_over.text

    # Valid dispatch: send 6 pcs to REPAIR
    res_dispatch = await client.post(
        "/api/v1/department-routing/dispatch",
        headers=_auth(actors["rm"], _key()),
        json={
            "gs_id": gs_id,
            "department_field_id": repair_dept_id,
            "lines": [{"gs_item_id": item_id, "qty_sent": 6, "notes": "Check heating element"}],
            "remarks": "Dispatched for initial heating test",
        },
    )
    assert res_dispatch.status_code == 200, res_dispatch.text
    routing = res_dispatch.json()
    assert routing["routing_no"].startswith("DIN/")
    assert routing["status"] == "DISPATCHED"
    assert routing["department_code"] == "REPAIR"
    assert len(routing["lines"]) == 1
    assert routing["lines"][0]["qty_sent"] == 6
    assert routing["lines"][0]["qty_received"] == 0
    assert routing["lines"][0]["qty_pending"] == 6

    # G-20 conservation verified: 4 in store + 6 at dept = 10
    res_recon = await client.get(
        f"/api/v1/department-routing/gs/{gs_id}/reconciliation", headers=_auth(actors["rm"])
    )
    assert res_recon.status_code == 200
    recon = res_recon.json()
    assert recon["is_fully_reconciled"] is True
    assert recon["total_counted"] == 10
    assert recon["total_in_store"] == 4
    assert recon["total_at_departments"] == 6
    assert recon["total_outcomes"] == 0

    # Over-dispatch second leg: only 4 left in store, try to send 5
    res_over2 = await client.post(
        "/api/v1/department-routing/dispatch",
        headers=_auth(actors["rm"], _key()),
        json={
            "gs_id": gs_id,
            "department_field_id": repair_dept_id,
            "lines": [{"gs_item_id": item_id, "qty_sent": 5}],
        },
    )
    assert res_over2.status_code in (409, 422)
    assert "G-20" in res_over2.text


@pytest.mark.asyncio
async def test_department_receiving_and_outcome_heads(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    """3. Department receiving: partial receipt, wastage, re-route return, auto-completion and
    G-20 conservation."""
    fixture = _seed_gs_held_at_intermediate_store(db_conn)
    gs_id = fixture["gs_id"]
    item_id = fixture["item_id"]
    repair_dept_id = fixture["repair_dept_id"]

    # Dispatch 6 pcs to REPAIR
    res_dispatch = await client.post(
        "/api/v1/department-routing/dispatch",
        headers=_auth(actors["rm"], _key()),
        json={
            "gs_id": gs_id,
            "department_field_id": repair_dept_id,
            "lines": [{"gs_item_id": item_id, "qty_sent": 6}],
        },
    )
    assert res_dispatch.status_code == 200
    routing = res_dispatch.json()
    routing_id = routing["id"]
    routing_line_id = routing["lines"][0]["id"]

    # Check receiving queue
    res_queue = await client.get(
        "/api/v1/department-routing/receiving-queue", headers=_auth(actors["aman"])
    )
    assert res_queue.status_code == 200
    queue = res_queue.json()
    assert any(q["routing_id"] == routing_id for q in queue)

    # Get outcome heads
    res_heads = await client.get(
        "/api/v1/department-routing/outcome-heads", headers=_auth(actors["aman"])
    )
    assert res_heads.status_code == 200
    heads = {h["code"]: h for h in res_heads.json()}
    assert "REPAIRED" in heads
    assert "WASTAGE" in heads
    assert "RE_ROUTE" in heads

    # Over-receive attempt: try to receive 8 pcs when only 6 were sent
    res_over_rec = await client.post(
        f"/api/v1/department-routing/{routing_id}/receive",
        headers=_auth(actors["aman"], _key()),
        json={
            "routing_id": routing_id,
            "lines": [
                {
                    "routing_line_id": routing_line_id,
                    "outcome_head_id": heads["REPAIRED"]["id"],
                    "quantity": 8,
                }
            ],
        },
    )
    assert res_over_rec.status_code == 422
    assert "OVER_RECEIVE" in res_over_rec.text

    # Partial receipt: receive 4 pcs as REPAIRED
    res_rec1 = await client.post(
        f"/api/v1/department-routing/{routing_id}/receive",
        headers=_auth(actors["aman"], _key()),
        json={
            "routing_id": routing_id,
            "lines": [
                {
                    "routing_line_id": routing_line_id,
                    "outcome_head_id": heads["REPAIRED"]["id"],
                    "quantity": 4,
                    "remarks": "4 calibrated & fixed",
                }
            ],
            "remarks": "Batch 1 partial receipt",
        },
    )
    assert res_rec1.status_code == 200, res_rec1.text
    rec1 = res_rec1.json()
    assert rec1["receipt_no"].startswith("DRN/")
    assert len(rec1["lines"]) == 1
    assert rec1["lines"][0]["quantity"] == 4

    # Check routing status is now PARTIALLY_RECEIVED
    res_r_check = await client.get(
        f"/api/v1/department-routing/{routing_id}", headers=_auth(actors["aman"])
    )
    assert res_r_check.status_code == 200
    r_detail = res_r_check.json()
    assert r_detail["status"] == "PARTIALLY_RECEIVED"
    assert r_detail["lines"][0]["qty_received"] == 4
    assert r_detail["lines"][0]["qty_pending"] == 2

    # Check G-20: 4 store + 2 at dept + 4 outcome = 10
    res_recon1 = await client.get(
        f"/api/v1/department-routing/gs/{gs_id}/reconciliation", headers=_auth(actors["rm"])
    )
    recon1 = res_recon1.json()
    assert recon1["is_fully_reconciled"] is True
    assert recon1["total_in_store"] == 4
    assert recon1["total_at_departments"] == 2
    assert recon1["total_outcomes"] == 4

    # Final receipt: receive remaining 2 pcs: 1 as WASTAGE, 1 as RE_ROUTE (DEC-43)
    res_rec2 = await client.post(
        f"/api/v1/department-routing/{routing_id}/receive",
        headers=_auth(actors["aman"], _key()),
        json={
            "routing_id": routing_id,
            "lines": [
                {
                    "routing_line_id": routing_line_id,
                    "outcome_head_id": heads["WASTAGE"]["id"],
                    "quantity": 1,
                    "remarks": "Glass cracked",
                },
                {
                    "routing_line_id": routing_line_id,
                    "outcome_head_id": heads["RE_ROUTE"]["id"],
                    "quantity": 1,
                    "remarks": "Needs Mercury extraction",
                },
            ],
            "remarks": "Final leg receipt",
        },
    )
    assert res_rec2.status_code == 200, res_rec2.text

    # Routing is now COMPLETED
    res_r_final = await client.get(
        f"/api/v1/department-routing/{routing_id}", headers=_auth(actors["aman"])
    )
    r_final = res_r_final.json()
    assert r_final["status"] == "COMPLETED"
    assert r_final["lines"][0]["qty_received"] == 6
    assert r_final["lines"][0]["qty_pending"] == 0

    # G-20 conservation tie-out:
    # Counted = 10
    # At dept = 0
    # Outcomes (terminal: 4 repaired + 1 wastage) = 5
    # In store = 4 initial + 1 re-route (returns_to_routing=true) = 5
    # Sum: 5 + 0 + 5 = 10
    res_recon2 = await client.get(
        f"/api/v1/department-routing/gs/{gs_id}/reconciliation", headers=_auth(actors["rm"])
    )
    recon2 = res_recon2.json()
    assert recon2["is_fully_reconciled"] is True
    assert recon2["total_counted"] == 10
    assert recon2["total_in_store"] == 5
    assert recon2["total_at_departments"] == 0
    assert recon2["total_outcomes"] == 5
    assert recon2["items"][0]["in_store_qty"] == 5

    # Timeline legs: check timeline includes dispatched, receipts, and outcomes
    res_legs = await client.get(
        f"/api/v1/department-routing/gs/{gs_id}/legs", headers=_auth(actors["rm"])
    )
    assert res_legs.status_code == 200
    legs = res_legs.json()
    assert len(legs) == 1
    assert legs[0]["routing_no"] == routing["routing_no"]
    assert legs[0]["qty_sent"] == 6
    assert legs[0]["qty_received"] == 6
    assert legs[0]["qty_pending"] == 0
    assert len(legs[0]["receipts"]) == 2


# =================================================================================================
# Phase 6 hardening (migration 20261113001000): G-16 idempotency, DEC-42 receiver setting,
# no routing without a stock movement, inactive outcome heads.
# =================================================================================================


def _balance(conn: Connection, lot_id: str, location_code: str) -> int:
    value = (
        as_admin(conn)
        .execute(
            text(
                """
            select coalesce(sum(b.qty), 0)::int from public.stock_balances b
              join public.inventory_locations l on l.id = b.location_id
             where b.lot_id = cast(:lot as uuid) and l.code = :loc
            """
            ),
            {"lot": lot_id, "loc": location_code},
        )
        .scalar_one()
    )
    return int(value)


def _routing_count(conn: Connection, gs_id: str) -> int:
    return int(
        as_admin(conn)
        .execute(
            text("select count(*) from public.department_routings where gs_id = cast(:g as uuid)"),
            {"g": gs_id},
        )
        .scalar_one()
    )


def _head_id(conn: Connection, code: str) -> str:
    return str(
        as_admin(conn)
        .execute(
            text("select id from public.department_outcome_heads where code = :c"), {"c": code}
        )
        .scalar_one()
    )


async def _dispatch(
    client: AsyncClient, token: str, fixture: dict[str, Any], qty: int, key: str | None
) -> Any:
    return await client.post(
        "/api/v1/department-routing/dispatch",
        headers=_auth(token, key),
        json={
            "gs_id": fixture["gs_id"],
            "department_field_id": fixture["repair_dept_id"],
            "lines": [{"gs_item_id": fixture["item_id"], "qty_sent": qty}],
        },
    )


async def _receive(
    client: AsyncClient,
    token: str,
    routing: dict[str, Any],
    head_id: str,
    qty: int,
    key: str | None,
) -> Any:
    return await client.post(
        f"/api/v1/department-routing/{routing['id']}/receive",
        headers=_auth(token, key),
        json={
            "routing_id": routing["id"],
            "lines": [
                {
                    "routing_line_id": routing["lines"][0]["id"],
                    "outcome_head_id": head_id,
                    "quantity": qty,
                }
            ],
        },
    )


@pytest.mark.asyncio
async def test_dispatch_and_receive_require_idempotency_key(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    """G-16 / CLAUDE.md rule f: stock-moving commands reject a missing Idempotency-Key."""
    fixture = _seed_gs_held_at_intermediate_store(db_conn)

    res = await _dispatch(client, actors["rm"], fixture, 2, None)
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert _routing_count(db_conn, fixture["gs_id"]) == 0
    assert _balance(db_conn, fixture["lot_id"], "INTERMEDIATE_STORE") == 10

    ok = await _dispatch(client, actors["rm"], fixture, 2, _key())
    assert ok.status_code == 200, ok.text
    res_rec = await _receive(
        client, actors["aman"], ok.json(), _head_id(db_conn, "REPAIRED"), 1, None
    )
    assert res_rec.status_code == 422, res_rec.text
    assert res_rec.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


@pytest.mark.asyncio
async def test_dispatch_and_receive_replay_move_stock_once(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    """G-16: the same key replays the original result; stock and documents are booked once."""
    fixture = _seed_gs_held_at_intermediate_store(db_conn)
    key = _key()

    first = await _dispatch(client, actors["rm"], fixture, 3, key)
    assert first.status_code == 200, first.text
    replay = await _dispatch(client, actors["rm"], fixture, 3, key)
    assert replay.status_code == 200, replay.text
    assert replay.headers.get("Idempotency-Replayed") == "true"
    assert replay.json()["id"] == first.json()["id"]
    assert _routing_count(db_conn, fixture["gs_id"]) == 1
    assert _balance(db_conn, fixture["lot_id"], "INTERMEDIATE_STORE") == 7
    assert _balance(db_conn, fixture["lot_id"], "TECHNICIAN_BENCH") == 3

    # Same key, different body -> 409 IDEMPOTENCY_CONFLICT, nothing booked.
    conflict = await _dispatch(client, actors["rm"], fixture, 1, key)
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert _routing_count(db_conn, fixture["gs_id"]) == 1

    routing = first.json()
    rkey = _key()
    repaired = _head_id(db_conn, "REPAIRED")
    rec1 = await _receive(client, actors["aman"], routing, repaired, 2, rkey)
    assert rec1.status_code == 200, rec1.text
    rec2 = await _receive(client, actors["aman"], routing, repaired, 2, rkey)
    assert rec2.status_code == 200, rec2.text
    assert rec2.headers.get("Idempotency-Replayed") == "true"
    assert rec2.json()["id"] == rec1.json()["id"]

    detail = await client.get(
        f"/api/v1/department-routing/{routing['id']}", headers=_auth(actors["rm"])
    )
    assert detail.json()["lines"][0]["qty_received"] == 2
    assert _balance(db_conn, fixture["lot_id"], "TECHNICIAN_BENCH") == 1
    assert _balance(db_conn, fixture["lot_id"], "INTERMEDIATE_STORE") == 9

    # Stock movements reference the routing / receipt documents, not the GS.
    refs = (
        as_admin(db_conn)
        .execute(
            text(
                """
                select reference_type, count(*)::int as n from public.stock_movements
                 where lot_id = cast(:lot as uuid)
                   and reference_id in (cast(:r as uuid), cast(:rc as uuid))
                 group by reference_type order by reference_type
                """
            ),
            {"lot": fixture["lot_id"], "r": routing["id"], "rc": rec1.json()["id"]},
        )
        .mappings()
        .all()
    )
    assert [(r["reference_type"], r["n"]) for r in refs] == [
        ("department_receipts", 1),
        ("department_routings", 1),
    ]


@pytest.mark.asyncio
async def test_receiver_role_comes_from_setting_dec42(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    """DEC-42: only the role in `department.receiving_role` receives; bad setting is reported."""
    fixture = _seed_gs_held_at_intermediate_store(db_conn)
    res = await _dispatch(client, actors["rm"], fixture, 2, _key())
    assert res.status_code == 200, res.text
    routing = res.json()
    repaired = _head_id(db_conn, "REPAIRED")

    # Dispatch names the configured receiving role (INWARD_VERIFIER by default) as recipients.
    notified = (
        as_admin(db_conn)
        .execute(
            text(
                """
                select count(*) from public.notification_events
                 where event_type = 'DEPT_ROUTING_DISPATCHED'
                   and entity_id = cast(:r as uuid)
                   and cast(:u as uuid) = any(context_user_ids)
                """
            ),
            {"r": routing["id"], "u": actors["aman_id"]},
        )
        .scalar_one()
    )
    assert notified == 1

    admin = as_admin(db_conn)
    admin.execute(
        text(
            "update public.system_settings set value = '\"TECHNICIAN\"' "
            "where key = 'department.receiving_role'"
        )
    )
    denied = await _receive(client, actors["aman"], routing, repaired, 1, _key())
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "NOT_DEPARTMENT_RECEIVER"

    admin.execute(
        text(
            "update public.system_settings set value = '42' where key = 'department.receiving_role'"
        )
    )
    broken = await _receive(client, actors["aman"], routing, repaired, 1, _key())
    assert broken.status_code == 409, broken.text
    assert broken.json()["error"]["code"] == "SETTING_INVALID"

    admin.execute(
        text(
            "update public.system_settings set value = '\"INWARD_VERIFIER\"' "
            "where key = 'department.receiving_role'"
        )
    )
    accepted = await _receive(client, actors["aman"], routing, repaired, 1, _key())
    assert accepted.status_code == 200, accepted.text


@pytest.mark.asyncio
async def test_dispatch_without_stock_lot_fails_loudly(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    """A routing is never recorded without its stock movement (rule f, G-20)."""
    fixture = _seed_gs_held_at_intermediate_store(db_conn)
    admin = as_admin(db_conn)
    admin.execute(text("set session_replication_role = 'replica'"))
    admin.execute(
        text("delete from public.stock_balances where lot_id = cast(:l as uuid)"),
        {"l": fixture["lot_id"]},
    )
    admin.execute(
        text("delete from public.stock_lots where id = cast(:l as uuid)"), {"l": fixture["lot_id"]}
    )
    admin.execute(text("set session_replication_role = 'origin'"))

    res = await _dispatch(client, actors["rm"], fixture, 2, _key())
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "LOT_NOT_FOUND"
    assert _routing_count(db_conn, fixture["gs_id"]) == 0


@pytest.mark.asyncio
async def test_inactive_outcome_head_and_routing_id_mismatch_rejected(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    """DEC-43: inactive outcome heads cannot be booked; body/URL routing ids must match."""
    fixture = _seed_gs_held_at_intermediate_store(db_conn)
    res = await _dispatch(client, actors["rm"], fixture, 2, _key())
    assert res.status_code == 200, res.text
    routing = res.json()

    as_admin(db_conn).execute(
        text("update public.department_outcome_heads set is_active = false where code = 'CLEANED'")
    )
    res_inactive = await _receive(
        client, actors["aman"], routing, _head_id(db_conn, "CLEANED"), 1, _key()
    )
    assert res_inactive.status_code == 422, res_inactive.text
    assert res_inactive.json()["error"]["code"] == "OUTCOME_HEAD_INACTIVE"

    res_mismatch = await client.post(
        f"/api/v1/department-routing/{routing['id']}/receive",
        headers=_auth(actors["aman"], _key()),
        json={
            "routing_id": str(uuid.uuid4()),
            "lines": [
                {
                    "routing_line_id": routing["lines"][0]["id"],
                    "outcome_head_id": _head_id(db_conn, "REPAIRED"),
                    "quantity": 1,
                }
            ],
        },
    )
    assert res_mismatch.status_code == 422, res_mismatch.text
    assert res_mismatch.json()["error"]["code"] == "ROUTING_ID_MISMATCH"
