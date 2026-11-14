"""P3-04 custody segregation, functional inventory & spare-parts ledger (integration).

Master plan §2.2 Stage-5, DD r63-r66, BR-30, G-04, G-05, G-09, G-12, G-16.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.modules.inventory import service as inventory_service
from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, fetch_all
from tests.integration.test_gate_inward import _auth

pytestmark = pytest.mark.anyio

API = "/api/v1/inventory"


@dataclass
class Actors:
    ism: str
    ism_id: uuid.UUID
    spm: str
    spm_id: uuid.UUID
    spm2: str
    rm: str
    rm_id: uuid.UUID
    mgmt: str
    gate: str
    admin: str


@pytest.fixture
def actors(users: UserFactory, make_token: JwtFactory) -> Actors:
    ism = users.create(roles=["INTERMEDIATE_STORE_MANAGER"], full_name="Store Manager")
    spm = users.create(roles=["SPARE_PARTS_MANAGER"], full_name="Spare Parts Manager")
    spm2 = users.create(roles=["SPARE_PARTS_MANAGER"], full_name="Spare Parts Manager 2")
    rm = users.create(roles=["REPLACEMENT_MANAGER"], full_name="Replacement Manager")
    mgmt = users.create(roles=["MANAGEMENT_VIEWER"], full_name="Management")
    gate = users.create(roles=["GATE_INWARD"], full_name="Gate")
    admin = users.create(super_admin=True, full_name="Admin")
    return Actors(
        ism=make_token(ism),
        ism_id=ism,
        spm=make_token(spm),
        spm_id=spm,
        spm2=make_token(spm2),
        rm=make_token(rm),
        rm_id=rm,
        mgmt=make_token(mgmt),
        gate=make_token(gate),
        admin=make_token(admin),
    )


def _key() -> str:
    return f"test-{uuid.uuid4()}"


def _location(conn: Connection, code: str) -> uuid.UUID:
    return (
        as_admin(conn)
        .execute(text("select id from public.inventory_locations where code = :c"), {"c": code})
        .scalar_one()
    )


def _move(
    conn: Connection,
    lot: uuid.UUID,
    *,
    to: str | None,
    qty: int,
    frm: str | None = None,
    type_: str = "INWARD",
) -> None:
    c = as_admin(conn)
    c.execute(
        text(
            """
            select rms_private.rms_move_stock(
              p_lot := cast(:lot as uuid), p_from := cast(:frm as uuid),
              p_to := cast(:to as uuid), p_qty := cast(:qty as integer),
              p_type := cast(:type as text), p_ref_type := cast(null as text),
              p_ref_id := cast(null as uuid), p_idem_key := cast(:key as text),
              p_actor := cast(null as uuid), p_reason := 'P3-04 test setup'::text)
            """
        ),
        {
            "lot": lot,
            "frm": _location(conn, frm) if frm else None,
            "to": _location(conn, to) if to else None,
            "qty": qty,
            "type": type_,
            "key": f"p304-setup:{uuid.uuid4()}",
        },
    )


def _lot(
    conn: Connection,
    *,
    condition: str,
    location: str,
    qty: int,
    item_kind: str = "FINISHED_GOOD",
    part_type: str | None = None,
) -> uuid.UUID:
    """A lot of a fresh test product (or spare part) with `qty` at `location`."""
    c = as_admin(conn)
    tag = uuid.uuid4().hex[:8].upper()
    product_id = None
    if item_kind == "FINISHED_GOOD":
        cat = c.execute(
            text("insert into public.product_categories (code, name) values (:c, :n) returning id"),
            {"c": f"P304_CAT_{tag}", "n": f"P304 category {tag}"},
        ).scalar_one()
        product_id = c.execute(
            text(
                "insert into public.products (code, name, category_id) "
                "values (:c, :n, :cat) returning id"
            ),
            {"c": f"P304-{tag}", "n": f"P304 product {tag}", "cat": cat},
        ).scalar_one()
    item = c.execute(
        text(
            "insert into public.stock_items (item_kind, product_id, part_type) "
            "values (:k, :p, :pt) returning id"
        ),
        {"k": item_kind, "p": product_id, "pt": part_type},
    ).scalar_one()
    lot = c.execute(
        text(
            "insert into public.stock_lots (stock_item_id, condition_class) "
            "values (:i, :c) returning id"
        ),
        {"i": item, "c": condition},
    ).scalar_one()
    _move(conn, lot, to=location, qty=qty, type_="RECEIPT" if part_type else "INWARD")
    return uuid.UUID(str(lot))


def _balance(conn: Connection, lot: uuid.UUID, location: str) -> int:
    value = (
        as_admin(conn)
        .execute(
            text(
                "select coalesce(sum(b.qty), 0) from public.stock_balances b "
                "join public.inventory_locations l on l.id = b.location_id "
                "where b.lot_id = :lot and l.code = :code"
            ),
            {"lot": lot, "code": location},
        )
        .scalar_one()
    )
    return int(value)


async def _assign(
    client: AsyncClient, token: str, lot: uuid.UUID, qty: int, code: str, key: str | None = None
) -> Any:
    return await client.post(
        f"{API}/custody-assignment",
        json={"lot_id": str(lot), "qty": qty, "assignment_code": code},
        headers=_auth(token, key or _key()),
    )


# =============================================================================================
# Custody assignment (DD r63-66)
# =============================================================================================
async def test_assignment_rejects_contradictory_requests(
    client: AsyncClient, actors: Actors, db_conn: Connection
) -> None:
    """NON_GOOD → functional = G-04; salvaged → functional = G-12; hazard = G-05; others 422."""
    non_good = _lot(db_conn, condition="NON_GOOD", location="NON_FUNCTIONAL_STORE", qty=3)
    res = await _assign(client, actors.spm, non_good, 1, "CUST_FUNCTIONAL_GOOD")
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "G-04"

    parts = _lot(
        db_conn,
        condition="SALVAGED",
        location="SPARE_PARTS_STORE",
        qty=4,
        item_kind="SPARE_PART",
        part_type="TIP",
    )
    res = await _assign(client, actors.spm, parts, 1, "CUST_FUNCTIONAL_REPAIRED")
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "G-12"

    hazard = _lot(db_conn, condition="HAZARD", location="HAZARD_QUARANTINE", qty=1)
    res = await _assign(client, actors.admin, hazard, 1, "CUST_NON_FUNCTIONAL")
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "G-05"

    good = _lot(db_conn, condition="FUNCTIONAL_GOOD", location="INTERMEDIATE_STORE", qty=2)
    res = await _assign(client, actors.ism, good, 1, "CUST_NON_FUNCTIONAL")
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "CUSTODY_ASSIGNMENT_MISMATCH"
    assert res.json()["error"]["details"]["valid_codes"] == ["CUST_FUNCTIONAL_GOOD"]

    raw = _lot(db_conn, condition="AS_RECEIVED", location="INTERMEDIATE_STORE", qty=2)
    res = await _assign(client, actors.ism, raw, 1, "CUST_FUNCTIONAL_GOOD")
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "CUSTODY_ASSIGNMENT_NEEDS_CLASSIFICATION"

    # Nothing moved, nothing recorded.
    assert _balance(db_conn, non_good, "NON_FUNCTIONAL_STORE") == 3
    assert not fetch_all(
        db_conn,
        "select id from public.custody_assignments where lot_id = any(:ids)",
        ids=[non_good, parts, hazard, good, raw],
    )


async def test_assignment_db_guard_rejects_contradiction(
    actors: Actors, db_conn: Connection, session_factory: sessionmaker[Session]
) -> None:
    """The custody_assignments trigger repeats G-04 (no service involved, as rms_api)."""
    non_good = _lot(db_conn, condition="NON_GOOD", location="NON_FUNCTIONAL_STORE", qty=1)
    store = _location(db_conn, "INTERMEDIATE_STORE")
    nfs = _location(db_conn, "NON_FUNCTIONAL_STORE")
    with session_factory() as s, pytest.raises(DBAPIError, match="G-04"), s.begin():
        s.execute(
            text(
                """
                insert into public.custody_assignments (lot_id, qty, assignment_code,
                  condition_class, from_location_id, to_location_id, outcome)
                values (:lot, 1, 'CUST_FUNCTIONAL_GOOD', 'NON_GOOD', :f, :t, 'TRANSFER_INITIATED')
                """
            ),
            {"lot": non_good, "f": nfs, "t": store},
        )


async def test_assignment_in_place_is_recorded_and_idempotent(
    client: AsyncClient, actors: Actors, db_conn: Connection
) -> None:
    good = _lot(db_conn, condition="FUNCTIONAL_GOOD", location="INTERMEDIATE_STORE", qty=5)
    key = _key()
    res = await _assign(client, actors.ism, good, 5, "CUST_FUNCTIONAL_GOOD", key)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["outcome"] == "ALREADY_IN_PLACE"
    assert body["transfer_id"] is None
    assert body["to_location_code"] == "INTERMEDIATE_STORE"
    label = fetch_all(
        db_conn,
        "select oi.label from public.option_items oi join public.option_sets os "
        "on os.id = oi.option_set_id where os.code = 'CUSTODY_ASSIGNMENT' "
        "and oi.code = 'CUST_FUNCTIONAL_GOOD'",
    )[0]["label"]
    assert body["assignment_label"] == label  # G-18 label snapshot from the published form

    replay = await _assign(client, actors.ism, good, 5, "CUST_FUNCTIONAL_GOOD", key)
    assert replay.status_code == 201
    assert replay.headers.get("Idempotency-Replayed") == "true"
    assert replay.json()["id"] == body["id"]
    rows = fetch_all(
        db_conn,
        "select form_version_id from public.custody_assignments where lot_id = :l",
        l=good,
    )
    assert len(rows) == 1 and rows[0]["form_version_id"] is not None

    # Only the custodian (or a custody override role) assigns: Sahil cannot touch SPM stock.
    non_good = _lot(db_conn, condition="NON_GOOD", location="NON_FUNCTIONAL_STORE", qty=1)
    res = await _assign(client, actors.ism, non_good, 1, "CUST_NON_FUNCTIONAL")
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "NOT_LOCATION_CUSTODIAN"


async def test_assignment_moves_through_custody_engine(
    client: AsyncClient, actors: Actors, db_conn: Connection
) -> None:
    """A lot outside its custodian's location goes there by a two-phase transfer (G-09)."""
    # Salvaged parts parked in the battery store (SPM) belong in the spare parts ledger.
    parts = _lot(
        db_conn,
        condition="SALVAGED",
        location="BATTERY_STORE",
        qty=6,
        item_kind="SPARE_PART",
        part_type="BODY",
    )
    res = await _assign(client, actors.spm, parts, 6, "CUST_SALVAGED_PARTS")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["outcome"] == "TRANSFER_INITIATED"
    assert body["transfer_no"]
    assert _balance(db_conn, parts, "BATTERY_STORE") == 0
    assert _balance(db_conn, parts, "TRANSIT") == 6  # nobody holds it until accepted (G-09)

    accept = await client.post(
        f"/api/v1/custody/transfers/{body['transfer_id']}/accept",
        json={
            "lines": [{"lot_id": str(parts), "qty_counted": 6}],
            "acceptance_code": "ACCEPTED_VERIFIED",
        },
        headers=_auth(actors.spm2, _key()),
    )
    assert accept.status_code == 200, accept.text
    assert _balance(db_conn, parts, "SPARE_PARTS_STORE") == 6

    # Non-sellable stock left at the technician bench → Spare Parts Manager (admin corrects it).
    stray = _lot(db_conn, condition="NON_SELLABLE", location="TECHNICIAN_BENCH", qty=2)
    res = await _assign(client, actors.admin, stray, 2, "CUST_NON_FUNCTIONAL")
    assert res.status_code == 201, res.text
    assert res.json()["to_location_code"] == "NON_FUNCTIONAL_STORE"
    assert _balance(db_conn, stray, "TRANSIT") == 2


# =============================================================================================
# Segregation check
# =============================================================================================
async def test_segregation_check_finds_injected_violation(
    client: AsyncClient,
    actors: Actors,
    db_conn: Connection,
    session_factory: sessionmaker[Session],
) -> None:
    good = _lot(db_conn, condition="FUNCTIONAL_GOOD", location="INTERMEDIATE_STORE", qty=3)

    res = await client.get(f"{API}/segregation-check", headers=_auth(actors.ism))
    assert res.status_code == 200
    assert not [v for v in res.json()["violations"] if v["lot_id"] == str(good)]

    # The new trigger closes the in-place gap: as rms_api the condition cannot become NON_GOOD
    # while the lot sits in the Intermediate Store (G-04 is checked before G-12).
    with session_factory() as s, pytest.raises(DBAPIError, match="G-04"), s.begin():
        s.execute(
            text("update public.stock_lots set condition_class = 'NON_GOOD' where id = :id"),
            {"id": good},
        )

    # Raw SQL bypass (superuser, triggers off) injects the violation the guards prevent.
    c = as_admin(db_conn)
    c.execute(text("set local session_replication_role = replica"))
    try:
        c.execute(
            text("update public.stock_lots set condition_class = 'NON_GOOD' where id = :id"),
            {"id": good},
        )
    finally:
        c.execute(text("set local session_replication_role = origin"))

    res = await client.get(f"{API}/segregation-check", headers=_auth(actors.ism))
    found = [v for v in res.json()["violations"] if v["lot_id"] == str(good)]
    assert {(v["rule_code"], v["guard_ref"]) for v in found} >= {
        ("NON_FUNCTIONAL_IN_FUNCTIONAL", "G-12")
    }
    assert res.json()["violation_count"] >= 1

    # The Intermediate Store view still never shows it (BR-30 acceptance).
    view = await client.get(
        f"{API}/stock", params={"view": "FUNCTIONAL", "page_size": 100}, headers=_auth(actors.ism)
    )
    assert str(good) not in {r["lot_id"] for r in view.json()["items"]}

    # Nightly job: records the run and alerts the RM.
    with session_factory() as s, s.begin():
        count = inventory_service.run_nightly_segregation_check(s)
    assert count >= 1
    run = fetch_all(
        db_conn,
        "select violation_count from public.segregation_check_runs "
        "where trigger_code = 'NIGHTLY' order by run_at desc limit 1",
    )[0]
    assert run["violation_count"] == count
    alerts = fetch_all(
        db_conn,
        "select priority from public.notifications where user_id = :u "
        "and type = 'SEGREGATION_VIOLATION'",
        u=actors.rm_id,
    )
    assert alerts and alerts[0]["priority"] == "HIGH"


# =============================================================================================
# Views, visibility, export, stock card
# =============================================================================================
async def test_views_routing_text_and_parts_visibility(
    client: AsyncClient, actors: Actors, db_conn: Connection
) -> None:
    good = _lot(db_conn, condition="FUNCTIONAL_GOOD", location="INTERMEDIATE_STORE", qty=2)
    repaired = _lot(db_conn, condition="FUNCTIONAL_REPAIRED", location="INTERMEDIATE_STORE", qty=1)
    parts = _lot(
        db_conn,
        condition="SALVAGED",
        location="SPARE_PARTS_STORE",
        qty=9,
        item_kind="SPARE_PART",
        part_type="WIRE",
    )
    texts = {
        r["code"]: r["next_action_text"]
        for r in fetch_all(
            db_conn,
            "select oi.code, oi.next_action_text from public.option_items oi "
            "join public.option_sets os on os.id = oi.option_set_id "
            "where os.code = 'CUSTODY_ASSIGNMENT'",
        )
    }

    res = await client.get(
        f"{API}/stock", params={"view": "FUNCTIONAL", "page_size": 100}, headers=_auth(actors.ism)
    )
    assert res.status_code == 200
    rows = {r["lot_id"]: r for r in res.json()["items"]}
    assert rows[str(good)]["next_action_text"] == texts["CUST_FUNCTIONAL_GOOD"]
    assert rows[str(good)]["assignment_codes"] == ["CUST_FUNCTIONAL_GOOD"]
    assert rows[str(repaired)]["next_action_text"] == texts["CUST_FUNCTIONAL_REPAIRED"]
    assert all(
        r["condition_class"] in {"AS_RECEIVED", "FUNCTIONAL_GOOD", "FUNCTIONAL_REPAIRED"}
        and r["location_class"] == "FUNCTIONAL"
        for r in res.json()["items"]
    )

    # Salvaged parts: only the Spare Parts Manager's ledger (+ management / admin), BR-30.
    for token, expected in ((actors.ism, 403), (actors.spm, 200), (actors.mgmt, 200)):
        res = await client.get(
            f"{API}/stock",
            params={"view": "SPARE_PARTS", "part_type": "WIRE", "page_size": 100},
            headers=_auth(token),
        )
        assert res.status_code == expected, res.text
    ledger = {r["lot_id"] for r in res.json()["items"]}
    assert str(parts) in ledger
    card = await client.get(f"{API}/lots/{parts}/stock-card", headers=_auth(actors.ism))
    assert card.status_code == 403
    lookups = await client.get(f"{API}/lookups", headers=_auth(actors.ism))
    assert "SPARE_PARTS" not in lookups.json()["views"]

    # CSV export needs inventory.export.
    csv_res = await client.get(
        f"{API}/stock/export", params={"view": "FUNCTIONAL"}, headers=_auth(actors.ism)
    )
    assert csv_res.status_code == 200
    assert csv_res.headers["content-type"].startswith("text/csv")
    assert csv_res.text.splitlines()[0].startswith("GS No.,Line,Product code")
    denied = await client.get(
        f"{API}/stock/export", params={"view": "FUNCTIONAL"}, headers=_auth(actors.gate)
    )
    assert denied.status_code == 403


async def test_stock_card_reconstructs_path(
    client: AsyncClient, actors: Actors, db_conn: Connection
) -> None:
    """A reclassified lot's card starts at its parent lot's inward (lineage via RECLASSIFY)."""
    parent = _lot(db_conn, condition="AS_RECEIVED", location="INTERMEDIATE_STORE", qty=5)
    c = as_admin(db_conn)
    item = c.execute(
        text("select stock_item_id from public.stock_lots where id = :id"), {"id": parent}
    ).scalar_one()
    child = c.execute(
        text(
            "insert into public.stock_lots (stock_item_id, condition_class) "
            "values (:i, 'FUNCTIONAL_GOOD') returning id"
        ),
        {"i": item},
    ).scalar_one()
    c.execute(
        text(
            """
            select rms_private.rms_reclassify_lot(
              p_source_lot := cast(:s as uuid), p_target_lot := cast(:t as uuid),
              p_location := cast(:loc as uuid), p_qty := 3, p_ref_type := 'test',
              p_ref_id := cast(null as uuid), p_idem_key := cast(:k as text))
            """
        ),
        {"s": parent, "t": child, "loc": _location(db_conn, "INTERMEDIATE_STORE"), "k": _key()},
    )

    res = await client.get(f"{API}/lots/{child}/stock-card", headers=_auth(actors.ism))
    assert res.status_code == 200, res.text
    card = res.json()
    assert card["lineage"] == [str(child), str(parent)]
    steps = [(m["movement_type"], m["is_ancestor"], m["qty"]) for m in card["movements"]]
    assert steps == [("INWARD", True, 5), ("RECLASSIFY", True, 3), ("RECLASSIFY", False, 3)]
    assert card["balances"] == [
        {
            "location_id": str(_location(db_conn, "INTERMEDIATE_STORE")),
            "location_code": "INTERMEDIATE_STORE",
            "location_name": card["balances"][0]["location_name"],
            "location_class": "FUNCTIONAL",
            "qty": 3,
        }
    ]


# =============================================================================================
# Stock adjustments
# =============================================================================================
async def test_adjustment_request_and_approval(
    client: AsyncClient, actors: Actors, db_conn: Connection
) -> None:
    good = _lot(db_conn, condition="FUNCTIONAL_GOOD", location="INTERMEDIATE_STORE", qty=10)
    store = _location(db_conn, "INTERMEDIATE_STORE")
    req = {
        "lot_id": str(good),
        "location_id": str(store),
        "counted_qty": 8,
        "reason": "Cycle count",
    }

    # Only the location's custodian requests; a reason is mandatory.
    res = await client.post(f"{API}/adjustments", json=req, headers=_auth(actors.spm))
    assert res.status_code == 403
    res = await client.post(
        f"{API}/adjustments", json={**req, "reason": "  "}, headers=_auth(actors.ism)
    )
    assert res.status_code == 422

    res = await client.post(f"{API}/adjustments", json=req, headers=_auth(actors.ism))
    assert res.status_code == 201, res.text
    adj = res.json()
    assert (adj["status"], adj["system_qty"], adj["delta"]) == ("REQUESTED", 10, -2)
    dup = await client.post(f"{API}/adjustments", json=req, headers=_auth(actors.ism))
    assert dup.status_code == 409

    # The custodian cannot approve; the RM (stock_adjustment_approver_roles) can.
    res = await client.post(
        f"{API}/adjustments/{adj['id']}/approve", json={}, headers=_auth(actors.ism, _key())
    )
    assert res.status_code == 403
    res = await client.post(
        f"{API}/adjustments/{adj['id']}/approve",
        json={"remarks": "Verified"},
        headers=_auth(actors.rm, _key()),
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "APPROVED"
    assert _balance(db_conn, good, "INTERMEDIATE_STORE") == 8
    moves = fetch_all(
        db_conn,
        "select movement_type, qty, from_location_id, to_location_id, reason "
        "from public.stock_movements where reference_id = :id",
        id=uuid.UUID(adj["id"]),
    )
    assert len(moves) == 1
    assert moves[0]["movement_type"] == "ADJUST" and moves[0]["qty"] == 2
    assert moves[0]["from_location_id"] == store and moves[0]["to_location_id"] is None
    assert "Cycle count" in moves[0]["reason"]
    again = await client.post(
        f"{API}/adjustments/{adj['id']}/approve", json={}, headers=_auth(actors.rm, _key())
    )
    assert again.status_code == 409

    # Positive difference, then a stale count (stock moved after the count) → 409.
    res = await client.post(
        f"{API}/adjustments",
        json={**req, "counted_qty": 9, "reason": "Found one"},
        headers=_auth(actors.ism),
    )
    adj2 = res.json()
    _move(db_conn, good, to="INTERMEDIATE_STORE", qty=1)
    res = await client.post(
        f"{API}/adjustments/{adj2['id']}/approve", json={}, headers=_auth(actors.rm, _key())
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "STOCK_CHANGED_SINCE_COUNT"
    res = await client.post(
        f"{API}/adjustments/{adj2['id']}/reject", json={"remarks": ""}, headers=_auth(actors.rm)
    )
    assert res.status_code == 422
    res = await client.post(
        f"{API}/adjustments/{adj2['id']}/reject",
        json={"remarks": "Recount"},
        headers=_auth(actors.rm),
    )
    assert res.status_code == 200 and res.json()["status"] == "REJECTED"
    assert _balance(db_conn, good, "INTERMEDIATE_STORE") == 9


async def test_adjustment_segregation_of_duties(
    client: AsyncClient,
    users: UserFactory,
    make_token: JwtFactory,
    db_conn: Connection,
    session_factory: sessionmaker[Session],
) -> None:
    """A user who is both custodian and approver never decides their own count (service + DB)."""
    both_id = users.create(roles=["INTERMEDIATE_STORE_MANAGER", "REPLACEMENT_MANAGER"])
    both = make_token(both_id)
    good = _lot(db_conn, condition="FUNCTIONAL_GOOD", location="INTERMEDIATE_STORE", qty=4)
    store = _location(db_conn, "INTERMEDIATE_STORE")
    res = await client.post(
        f"{API}/adjustments",
        json={"lot_id": str(good), "location_id": str(store), "counted_qty": 3, "reason": "x"},
        headers=_auth(both),
    )
    adj_id = res.json()["id"]
    assert res.json()["can_decide"] is False
    res = await client.post(
        f"{API}/adjustments/{adj_id}/approve", json={}, headers=_auth(both, _key())
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "SEGREGATION_OF_DUTIES"
    with (
        session_factory() as s,
        pytest.raises(DBAPIError, match="SEGREGATION_OF_DUTIES"),
        s.begin(),
    ):
        s.execute(
            text(
                "update public.stock_adjustments set status = 'REJECTED', decided_by = :u, "
                "decided_at = now(), decision_remarks = 'self' where id = :id"
            ),
            {"u": both_id, "id": adj_id},
        )
