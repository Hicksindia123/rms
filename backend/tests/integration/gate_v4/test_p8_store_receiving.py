"""Phase P8 (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-68 (PROVISIONAL).

The Intermediate Store that routed the goods (DEC-67) receives them back from the departments per
GS and department: sent vs received qty, outcome, condition after work (DEC-56), partial receipts.
Stock goes department -> THAT store's location (or scrap / Non-Functional per outcome head) through
rms_move_stock in one transaction with an Idempotency-Key (G-16). A "return to routing" outcome
makes the pieces routable again and reopens the store's routing task; everything back (or no
work) = READY_FOR_ANALYSIS. Guards (service and DB): only a user of the routing's store receives,
no over-receipt (G-20), condition required when routed from a condition.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from tests.integration.conftest import UserFactory, as_admin, fetch_all
from tests.integration.gate_v4.test_gate_v4 import Actors
from tests.integration.gate_v4.test_p5_transfer_slips import (
    _status,
    _stock_by_location,
    mgmt,
    products,
    rm,
)
from tests.integration.gate_v4.test_p7_store_routing import (
    StoreUsers,
    _dt_acked,
    _line,
    _open_tasks,
    _route,
    _view,
    dec59,
    routing_products,
    stores,
)
from tests.integration.test_gate_inward import Masters, _auth
from tests.integration.test_itemization import key
from tests.integration.test_unboxing import FakeStorage

pytestmark = pytest.mark.gate_v4

# fixtures re-used from the P5 / P7 tests
__all__ = ["dec59", "mgmt", "products", "rm", "routing_products", "stores"]


async def _routed_to_cleaning(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: dict[str, str],
    rm: str,
    st: StoreUsers,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """GS with a DT line of 3 (conditions 2 + 1) and an OP line of 1. DT acknowledged and routed
    condition 1 (2 pcs) to Cleaning, condition 2 (1 pc) "Issue to Store". Returns the GS, the DT
    item of the routing view and the Cleaning DIN."""
    gs_id, _, slips = await _dt_acked(client, storage, actors, masters, products, rm, st)
    view = (await _view(client, st.dt, gs_id)).json()
    dt_item = next(i for i in view["items"] if i["store"]["code"] == "DT")
    res = await _route(
        client,
        st.dt,
        gs_id,
        slips["DT"]["store"]["id"],
        [_line(dt_item, 0, "CLEANING", 2), _line(dt_item, 1, "STORE", 1)],
    )
    assert res.status_code == 200, res.text
    din = res.json()["dins"][0]
    assert din["department_code"] == "CLEANING"
    return gs_id, dt_item, din


async def _heads(client: AsyncClient, token: str) -> dict[str, str]:
    res = await client.get("/api/v1/department-routing/outcome-heads", headers=_auth(token))
    assert res.status_code == 200, res.text
    return {h["code"]: h["id"] for h in res.json()}


async def _din_line(client: AsyncClient, token: str, din_id: str) -> dict[str, Any]:
    res = await client.get(f"/api/v1/department-routing/{din_id}", headers=_auth(token))
    assert res.status_code == 200, res.text
    line: dict[str, Any] = res.json()["lines"][0]
    return line


async def _receive(
    client: AsyncClient,
    token: str,
    din_id: str,
    lines: list[dict[str, Any]],
    idem: str | None = None,
) -> Any:
    return await client.post(
        f"/api/v1/department-routing/store/routings/{din_id}/receive",
        json={"lines": lines},
        headers=_auth(token, idem or key()),
    )


def _rl(line: dict[str, Any], head: str, qty: int, cond: str | None) -> dict[str, Any]:
    return {
        "routing_line_id": line["id"],
        "outcome_head_id": head,
        "quantity": qty,
        "condition_field_id": cond,
    }


def _current_conditions(conn: Connection, item_id: str) -> dict[str, int]:
    rows = fetch_all(
        conn,
        "select field_label, current_qty from rms_private.item_current_conditions(:i)",
        i=item_id,
    )
    return {r["field_label"]: r["current_qty"] for r in rows if r["current_qty"] > 0}


# --- happy path: partial, then full ------------------------------------------------------------
async def test_store_receives_partial_then_full(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    routing_products: dict[str, str],
    rm: str,
    stores: StoreUsers,
    db_conn: Connection,
) -> None:
    gs_id, dt_item, din = await _routed_to_cleaning(
        client, storage, actors, masters, routing_products, rm, stores
    )
    assert _stock_by_location(db_conn, gs_id) == {
        "ISTORE_DT": 1,
        "DEPT_CLEANING": 2,
        "TRANSIT": 1,
    }
    cond_a, cond_b = dt_item["conditions"][0], dt_item["conditions"][1]

    # The queue: the DT user sees the GS (party-wise) with its Cleaning DIN; OP does not.
    queue = await client.get("/api/v1/department-routing/store/receiving", headers=_auth(stores.dt))
    assert queue.status_code == 200, queue.text
    row = next(r for r in queue.json() if r["gs_id"] == gs_id)
    assert [
        (d["routing_no"], d["qty_sent"], d["qty_pending"], d["is_mine"]) for d in row["dins"]
    ] == [(din["routing_no"], 2, 2, True)]
    assert [(s["store_code"], s["status"]) for s in row["stores"]] == [("DT", "AT_DEPARTMENTS")]
    op_queue = (
        await client.get("/api/v1/department-routing/store/receiving", headers=_auth(stores.op))
    ).json()
    assert gs_id not in {r["gs_id"] for r in op_queue}
    # My Work: "Receive from Departments" for DT; the legacy RE queue does not list store DINs.
    mine = (
        await client.get("/api/v1/me/journey/STORE_DEPT_RECEIVING", headers=_auth(stores.dt))
    ).json()
    assert gs_id in {i["gs_id"] for i in mine["items"]}
    legacy = (
        await client.get("/api/v1/department-routing/receiving-queue", headers=_auth(actors.aman))
    ).json()
    assert din["id"] not in {r["routing_id"] for r in legacy}

    heads = await _heads(client, stores.dt)
    line = await _din_line(client, stores.dt, din["id"])
    assert line["qty_pending"] == 2 and line["source_bucket_field_id"] == cond_a["field_id"]

    # Partial: 1 pc cleaned, came back in the other condition. Idempotent replay.
    idem = key()
    first = await _receive(
        client, stores.dt, din["id"], [_rl(line, heads["CLEANED"], 1, cond_b["field_id"])], idem
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["din"]["status"] == "PARTIALLY_RECEIVED" and body["din"]["qty_pending"] == 1
    assert body["store"]["status"] == "AT_DEPARTMENTS"
    assert body["receipt"]["lines"][0]["destination_location_code"] == "ISTORE_DT"
    replay = await _receive(
        client, stores.dt, din["id"], [_rl(line, heads["CLEANED"], 1, cond_b["field_id"])], idem
    )
    assert replay.status_code == 200 and replay.headers.get("Idempotency-Replayed") == "true"
    assert replay.json() == body
    # Stock back to the DT store's location (not the legacy INTERMEDIATE_STORE); DEC-56 split.
    assert _stock_by_location(db_conn, gs_id) == {
        "ISTORE_DT": 2,
        "DEPT_CLEANING": 1,
        "TRANSIT": 1,
    }
    assert _current_conditions(db_conn, dt_item["item_id"]) == {
        cond_a["field_label"]: 1,
        cond_b["field_label"]: 2,
    }

    # Over-receipt refused (1 pending).
    over = await _receive(
        client, stores.dt, din["id"], [_rl(line, heads["CLEANED"], 2, cond_a["field_id"])]
    )
    assert over.status_code == 422 and over.json()["error"]["code"] == "OVER_RECEIVE"

    # Full: the last piece is wastage -> scrap. The store is ready for analysis (P9).
    last = await _receive(
        client, stores.dt, din["id"], [_rl(line, heads["WASTAGE"], 1, cond_a["field_id"])]
    )
    assert last.status_code == 200, last.text
    done = last.json()
    assert done["din"]["status"] == "COMPLETED" and done["din"]["qty_pending"] == 0
    assert done["store"]["status"] == "READY_FOR_ANALYSIS"
    stock = _stock_by_location(db_conn, gs_id)
    assert (stock.get("ISTORE_DT"), stock.get("DEPT_CLEANING")) == (2, None)
    assert _status(db_conn, gs_id) == "STORE_PROCESSING"
    assert _open_tasks(db_conn, gs_id) == []
    after = (
        await client.get("/api/v1/department-routing/store/receiving", headers=_auth(stores.dt))
    ).json()
    assert gs_id not in {r["gs_id"] for r in after}
    # Nothing more to receive on a completed DIN.
    closed = await _receive(
        client, stores.dt, din["id"], [_rl(line, heads["CLEANED"], 1, cond_a["field_id"])]
    )
    assert closed.status_code == 422 and closed.json()["error"]["code"] == "INVALID_ROUTING_STATUS"


# --- guards (service) -------------------------------------------------------------------------
async def test_store_receiving_guards(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    routing_products: dict[str, str],
    rm: str,
    mgmt: str,
    stores: StoreUsers,
    db_conn: Connection,
) -> None:
    gs_id, dt_item, din = await _routed_to_cleaning(
        client, storage, actors, masters, routing_products, rm, stores
    )
    heads = await _heads(client, stores.dt)
    line = await _din_line(client, stores.dt, din["id"])
    ok = [_rl(line, heads["CLEANED"], 1, dt_item["conditions"][0]["field_id"])]

    async def refused(token: str, lines: list[dict[str, Any]]) -> tuple[int, str]:
        res = await _receive(client, token, din["id"], lines)
        return res.status_code, res.json()["error"]["code"]

    # Who: another store, the RM, Management (no store_routing.edit) and the legacy receiver.
    assert await refused(stores.op, ok) == (403, "NOT_STORE_USER")
    assert (await refused(rm, ok))[0] == 403
    assert (await refused(mgmt, ok))[0] == 403
    assert (await refused(actors.aman, ok))[0] == 403
    legacy = await client.post(
        f"/api/v1/department-routing/{din['id']}/receive",
        json={"routing_id": din["id"], "lines": ok},
        headers=_auth(actors.aman, key()),
    )
    assert legacy.status_code == 409 and legacy.json()["error"]["code"] == "STORE_ROUTING_RECEIPT"
    # DEC-56: routed from a condition -> the condition after work is required and must be one
    # of the product's categorisation list.
    assert await refused(stores.dt, [_rl(line, heads["CLEANED"], 1, None)]) == (
        422,
        "CONDITION_REQUIRED",
    )
    assert await refused(stores.dt, [_rl(line, heads["CLEANED"], 1, heads["CLEANED"])]) == (
        422,
        "CONDITION_NOT_ALLOWED",
    )
    # Over-receipt across two rows of one line (2 pending).
    two = [*ok, _rl(line, heads["REPAIRED"], 2, dt_item["conditions"][0]["field_id"])]
    assert await refused(stores.dt, two) == (422, "OVER_RECEIVE")
    # Nothing was booked.
    assert _stock_by_location(db_conn, gs_id)["DEPT_CLEANING"] == 2


# --- return to routing -----------------------------------------------------------------------
async def test_return_to_routing_reopens_the_store_routing(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    routing_products: dict[str, str],
    rm: str,
    stores: StoreUsers,
    db_conn: Connection,
) -> None:
    gs_id, dt_item, din = await _routed_to_cleaning(
        client, storage, actors, masters, routing_products, rm, stores
    )
    assert _open_tasks(db_conn, gs_id) == []
    heads = await _heads(client, stores.dt)
    line = await _din_line(client, stores.dt, din["id"])
    cond_a = dt_item["conditions"][0]
    res = await _receive(
        client, stores.dt, din["id"], [_rl(line, heads["RE_ROUTE"], 2, cond_a["field_id"])]
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["store"]["status"], body["store"]["unrouted_qty"]) == ("ROUTING_PENDING", 2)
    assert _open_tasks(db_conn, gs_id) == ["ISTORE_DT"]  # the routing task reopens
    assert _stock_by_location(db_conn, gs_id)["ISTORE_DT"] == 3

    # The pieces are routed again (from the store's location).
    view = (await _view(client, stores.dt, gs_id)).json()
    item = next(i for i in view["items"] if i["store"]["code"] == "DT")
    assert item["routable_qty"] == 2
    again = await _route(
        client,
        stores.dt,
        gs_id,
        item["store"]["id"],
        [_line(item, 0, "REPACKAGING", 2)],
    )
    assert again.status_code == 200, again.text
    assert _stock_by_location(db_conn, gs_id)["DEPT_REPACKAGING"] == 2
    assert _open_tasks(db_conn, gs_id) == []


# --- DB guards (non-bypassable) ---------------------------------------------------------------
async def test_db_refuses_store_receipt_bypass(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    routing_products: dict[str, str],
    rm: str,
    stores: StoreUsers,
    users: UserFactory,
    db_conn: Connection,
) -> None:
    gs_id, dt_item, din = await _routed_to_cleaning(
        client, storage, actors, masters, routing_products, rm, stores
    )
    c = as_admin(db_conn)

    def receipt(no: str) -> None:
        c.execute(
            text(
                "insert into public.department_receipts (receipt_no, routing_id, received_by)"
                " values (:n, :r, :u)"
            ),
            {"n": no, "r": din["id"], "u": str(stores.dt_id)},
        )

    for actor in (stores.op_id, actors.rm_id, None):
        users.set_actor(actor)
        with pytest.raises(DBAPIError, match="DEC-68: only a user"), c.begin_nested():
            receipt("P8-RCPT-X")

    # The store's own user: the destination of a "back to the store" outcome is ITS location.
    users.set_actor(stores.dt_id)
    receipt("P8-RCPT-OK")
    head = c.execute(
        text("select id from public.department_outcome_heads where code = 'REPAIRED'")
    ).scalar_one()
    dest = c.execute(
        text(
            """insert into public.department_receipt_lines
                 (receipt_id, routing_line_id, outcome_head_id, outcome_code, outcome_label,
                  is_wastage, returns_to_routing, quantity, condition_field_id)
               select r.id, rl.id, :h, '-', '-', false, false, 1, :c
                 from public.department_receipts r
                 join public.department_routing_lines rl on rl.routing_id = r.routing_id
                where r.receipt_no = 'P8-RCPT-OK'
               returning destination_location_code"""
        ),
        {"h": head, "c": dt_item["conditions"][0]["field_id"]},
    ).scalar_one()
    assert dest == "ISTORE_DT"
    users.set_actor(None)
    assert _status(db_conn, gs_id) == "STORE_PROCESSING"
