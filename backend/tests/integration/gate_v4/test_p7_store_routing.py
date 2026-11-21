"""Phase P7 (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-67 (Q14 PROVISIONAL; Q29 / Q31 user).

After its own transfer slip is acknowledged (P6), an Intermediate Store user routes ITS lines of a
goods slip per item + current condition to departments. Saving the routing is the issue: one DIN
per work department, stock store location -> department location (rms_move_stock) in one
transaction with an Idempotency-Key (G-16); "Issue to Store" (no work) moves no stock. Allowed
departments come from the DEC-59 masters under the GS's PINNED profile version. Guards (service
and DB): store scoping, allowed department, qty <= the qty still to route at the store (G-20). The
first routing closes the DEC-64 edit window and moves the GS to STORE_PROCESSING.

The DEC-59 thermometer masters are applied by the tests themselves (a fresh reset keeps the
workbook masters), and their profile version is written before the GS is locked.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, fetch_all
from tests.integration.gate_v4.test_gate_v4 import Actors
from tests.integration.gate_v4.test_p5_transfer_slips import (
    _generate,
    _locked,
    _status,
    _stock_by_location,
    mgmt,
    products,
    rm,
)
from tests.integration.test_gate_inward import Masters, _auth
from tests.integration.test_itemization import key
from tests.integration.test_unboxing import FakeStorage

pytestmark = pytest.mark.gate_v4

__all__ = ["mgmt", "products", "rm"]  # fixtures re-used from the P5 tests

DMT_DEPARTMENTS = {"STORE", "REPACKAGING", "CLEANING", "WASTE_MANAGEMENT"}  # DEC-59 DIGITAL list
_VERSION_TRIGGERS = "item_field_library_version, item_field_assignments_version"


@pytest.fixture
def dec59(db_conn: Connection) -> None:
    """DEC-59 masters + their profile version now (the version trigger is deferred to commit,
    which a rolled-back test never reaches; the GS lock pins the latest version)."""
    c = as_admin(db_conn)
    assert c.execute(text("select rms_private.apply_thermometer_masters()")).scalar_one()
    c.execute(text(f"set constraints {_VERSION_TRIGGERS} immediate"))
    c.execute(text(f"set constraints {_VERSION_TRIGGERS} deferred"))


@pytest.fixture
def routing_products(dec59: None, products: dict[str, str]) -> dict[str, str]:
    return products


class StoreUsers:
    def __init__(self, users: UserFactory, make_token: JwtFactory) -> None:
        self.dt_id = users.create(roles=["ISTORE_DT"], full_name="Dinesh DT Store")
        self.op_id = users.create(roles=["ISTORE_OP"], full_name="Om OP Store")
        self.dt = make_token(self.dt_id)
        self.op = make_token(self.op_id)


@pytest.fixture
def stores(users: UserFactory, make_token: JwtFactory) -> StoreUsers:
    return StoreUsers(users, make_token)


async def _ack(client: AsyncClient, token: str, slip_id: str) -> None:
    res = await client.post(
        f"/api/v1/transfer-slips/{slip_id}/acknowledge", json={}, headers=_auth(token, key())
    )
    assert res.status_code == 200, res.text


async def _dt_acked(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: dict[str, str],
    rm: str,
    st: StoreUsers,
) -> tuple[str, list[str], dict[str, dict[str, Any]]]:
    """One GS: a DT line of 3 (split 2 + 1) and an OP line of 1, on two slips; DT acknowledged."""
    gs_id, items = await _locked(
        client, storage, actors, masters, [(products["DT"], 3), (products["OP"], 1)]
    )
    gen = await _generate(client, rm, [gs_id])
    assert gen.status_code == 201, gen.text
    slips = {s["store"]["code"]: s for s in gen.json()["slips"]}
    await _ack(client, st.dt, slips["DT"]["id"])
    return gs_id, items, slips


async def _view(client: AsyncClient, token: str, gs_id: str) -> Any:
    return await client.get(f"/api/v1/department-routing/store/gs/{gs_id}", headers=_auth(token))


async def _route(
    client: AsyncClient,
    token: str,
    gs_id: str,
    store_id: str,
    lines: list[dict[str, Any]],
    idem: str | None = None,
) -> Any:
    return await client.post(
        f"/api/v1/department-routing/store/gs/{gs_id}/route",
        json={"store_id": store_id, "lines": lines},
        headers=_auth(token, idem or key()),
    )


def _line(item: dict[str, Any], cond: int | None, dept: str, qty: int) -> dict[str, Any]:
    depts = {d["code"]: d["field_id"] for d in item["allowed_departments"]}
    return {
        "gs_item_id": item["item_id"],
        "source_bucket_field_id": None if cond is None else item["conditions"][cond]["field_id"],
        "department_field_id": depts[dept],
        "qty": qty,
    }


def _open_tasks(conn: Connection, gs_id: str) -> list[str]:
    rows = fetch_all(
        conn,
        """select r.code from public.workflow_tasks t
             join public.roles r on r.id = t.assigned_role_id
            where t.gs_id = :g and t.step_code = 'STORE_ROUTING' and t.status = 'OPEN'
            order by r.code""",
        g=gs_id,
    )
    return [r["code"] for r in rows]


def _store_id(conn: Connection, code: str) -> str:
    return str(
        as_admin(conn)
        .execute(text("select id from public.intermediate_stores where code = :c"), {"c": code})
        .scalar_one()
    )


# --- happy path -------------------------------------------------------------------------------
async def test_store_routes_its_own_goods(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    routing_products: dict[str, str],
    rm: str,
    stores: StoreUsers,
    db_conn: Connection,
) -> None:
    gs_id, _, slips = await _dt_acked(
        client, storage, actors, masters, routing_products, rm, stores
    )
    dt_store = slips["DT"]["store"]["id"]

    # The view: every line with its store; DT may route its own line, OP's line is read-only.
    res = await _view(client, stores.dt, gs_id)
    assert res.status_code == 200, res.text
    view = res.json()
    assert view["can_route"] is True and view["status"] == "TRANSFER_SLIP_GENERATED"
    by_store = {i["store"]["code"]: i for i in view["items"]}
    dt_item, op_item = by_store["DT"], by_store["OP"]
    assert (dt_item["is_mine"], dt_item["acknowledged"], dt_item["routable_qty"]) == (True, True, 3)
    assert (op_item["is_mine"], op_item["acknowledged"], op_item["routable_qty"]) == (
        False,
        False,
        0,
    )
    # DEC-59 departments of the DIGITAL (DMT) category, under the pinned profile version.
    assert {d["code"] for d in dt_item["allowed_departments"]} == DMT_DEPARTMENTS
    assert [c["current_qty"] for c in dt_item["conditions"]] == [2, 1]
    assert {(s["store_code"], s["status"], s["is_mine"]) for s in view["stores"]} == {
        ("DT", "ROUTING_PENDING", True),
        ("OP", "AWAITING_ACKNOWLEDGEMENT", False),
    }

    # My Work: the DT user has the GS in "Department Routing"; OP (not acknowledged) has not.
    dt_queue = (
        await client.get("/api/v1/me/journey/STORE_DEPT_ROUTING", headers=_auth(stores.dt))
    ).json()
    assert gs_id in {i["gs_id"] for i in dt_queue["items"]}
    op_queue = (
        await client.get("/api/v1/me/journey/STORE_DEPT_ROUTING", headers=_auth(stores.op))
    ).json()
    assert gs_id not in {i["gs_id"] for i in op_queue["items"]}
    store_queue = await client.get(
        "/api/v1/department-routing/store/queue", headers=_auth(stores.dt)
    )
    assert store_queue.status_code == 200, store_queue.text
    row = next(r for r in store_queue.json() if r["gs_id"] == gs_id)
    assert [s["store_code"] for s in row["stores"]] == ["DT"]  # a store user sees its own store

    # Route: condition 1 (2 pcs) split Cleaning 1 + Issue to Store 1, condition 2 -> Repackaging.
    lines = [
        _line(dt_item, 0, "CLEANING", 1),
        _line(dt_item, 0, "STORE", 1),
        _line(dt_item, 1, "REPACKAGING", 1),
    ]
    idem = key()
    first = await _route(client, stores.dt, gs_id, dt_store, lines, idem)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["gs_status"] == "STORE_PROCESSING" and body["no_work_qty"] == 1
    assert sorted(d["department_code"] for d in body["dins"]) == ["CLEANING", "REPACKAGING"]
    assert all(d["store_code"] == "DT" and d["qty_sent"] == 1 for d in body["dins"])
    assert (body["store"]["status"], body["store"]["unrouted_qty"]) == ("AT_DEPARTMENTS", 0)
    # G-16: the same key returns the first result.
    replay = await _route(client, stores.dt, gs_id, dt_store, lines, idem)
    assert replay.status_code == 200 and replay.headers.get("Idempotency-Replayed") == "true"
    assert replay.json() == body

    # Stock: store -> department locations; "Issue to Store" stays; OP still in transit.
    assert _stock_by_location(db_conn, gs_id) == {
        "ISTORE_DT": 1,
        "DEPT_CLEANING": 1,
        "DEPT_REPACKAGING": 1,
        "TRANSIT": 1,
    }
    plan = fetch_all(
        db_conn,
        """select p.department_code, p.status, s.code as store
             from public.department_routing_plan_lines p
             join public.intermediate_stores s on s.id = p.store_id
            where p.gs_id = :g order by p.department_code""",
        g=gs_id,
    )
    assert plan == [
        {"department_code": "CLEANING", "status": "ISSUED", "store": "DT"},
        {"department_code": "REPACKAGING", "status": "ISSUED", "store": "DT"},
        {"department_code": "STORE", "status": "NO_WORK", "store": "DT"},
    ]
    din = await client.get(
        f"/api/v1/department-routing/{body['dins'][0]['id']}", headers=_auth(stores.dt)
    )
    assert din.status_code == 200, din.text  # the DIN print opens for the store user
    assert din.json()["location_code"].startswith("DEPT_")

    # The GS moved on; DT's routing task is done (nothing left to route).
    assert _status(db_conn, gs_id) == "STORE_PROCESSING"
    assert _open_tasks(db_conn, gs_id) == []

    # Q29: OP acknowledges later; the GS stays in STORE_PROCESSING and OP gets its task.
    await _ack(client, stores.op, slips["OP"]["id"])
    assert _status(db_conn, gs_id) == "STORE_PROCESSING"
    assert _open_tasks(db_conn, gs_id) == ["ISTORE_OP"]
    op_view = (await _view(client, stores.op, gs_id)).json()
    op_item = next(i for i in op_view["items"] if i["store"]["code"] == "OP")
    assert op_item["is_mine"] and op_item["routable_qty"] == 1 and op_view["can_route"]
    after = await _route(
        client, stores.op, gs_id, slips["OP"]["store"]["id"], [_line(op_item, 0, "GRADING", 1)]
    )
    assert after.status_code == 200, after.text
    assert after.json()["store"]["status"] == "AT_DEPARTMENTS"
    assert [d["department_code"] for d in after.json()["dins"]] == ["GRADING"]
    assert _stock_by_location(db_conn, gs_id)["DEPT_GRADING"] == 1
    assert _open_tasks(db_conn, gs_id) == []


# --- guards (service) -------------------------------------------------------------------------
async def test_store_routing_guards(
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
    gs_id, _, slips = await _dt_acked(
        client, storage, actors, masters, routing_products, rm, stores
    )
    dt_store, op_store = slips["DT"]["store"]["id"], slips["OP"]["store"]["id"]
    view = (await _view(client, stores.dt, gs_id)).json()
    dt_item = next(i for i in view["items"] if i["store"]["code"] == "DT")
    op_item = next(i for i in view["items"] if i["store"]["code"] == "OP")
    ok_line = _line(dt_item, 1, "STORE", 1)

    async def refused(token: str, store: str, lines: list[dict[str, Any]]) -> tuple[int, str]:
        res = await _route(client, token, gs_id, store, lines)
        return res.status_code, res.json()["error"]["code"]

    # Who: the RM and Management see the progress but do not route (DEC-67).
    assert (await _view(client, rm, gs_id)).status_code == 200
    assert (await _view(client, mgmt, gs_id)).status_code == 200
    assert (await refused(rm, dt_store, [ok_line]))[0] == 403
    assert (await refused(mgmt, dt_store, [ok_line]))[0] == 403
    # Cross-store routing is refused.
    assert await refused(stores.op, dt_store, [ok_line]) == (403, "NOT_STORE_USER")
    assert await refused(stores.op, op_store, [ok_line]) == (403, "ITEM_OF_OTHER_STORE")
    # A store routes only after ITS acknowledgement.
    op_line = _line(op_item, 0, "GRADING", 1)
    assert await refused(stores.op, op_store, [op_line]) == (409, "ITEM_NOT_ACKNOWLEDGED")
    # Over-routing: a condition (2 pcs) and the item across lines.
    assert await refused(stores.dt, dt_store, [_line(dt_item, 0, "STORE", 3)]) == (409, "G-20")
    assert await refused(
        stores.dt, dt_store, [_line(dt_item, 0, "STORE", 2), _line(dt_item, 0, "CLEANING", 1)]
    ) == (409, "G-20")
    # The department must be allowed for the category (GRADING is OVAL / PRISMATIC, DEC-59).
    grading = fetch_all(
        db_conn,
        "select id::text from public.item_field_library"
        " where field_group = 'DEPARTMENT' and code = 'GRADING'",
    )[0]["id"]
    bad_dept = {**ok_line, "department_field_id": grading}
    assert await refused(stores.dt, dt_store, [bad_dept]) == (422, "DEPARTMENT_NOT_ALLOWED")
    # An item split by condition is routed per condition.
    no_cond = {**ok_line, "source_bucket_field_id": None}
    assert await refused(stores.dt, dt_store, [no_cond]) == (422, "CONDITION_REQUIRED")
    # Nothing was written by the refused commands.
    assert _status(db_conn, gs_id) == "TRANSFER_SLIP_GENERATED"
    assert _stock_by_location(db_conn, gs_id) == {"ISTORE_DT": 3, "TRANSIT": 1}

    # Everything "Issue to Store": no DIN, no stock move, the store is ready for analysis (P9).
    full = [_line(dt_item, 0, "STORE", 2), _line(dt_item, 1, "STORE", 1)]
    done = await _route(client, stores.dt, gs_id, dt_store, full)
    assert done.status_code == 200, done.text
    assert done.json()["dins"] == [] and done.json()["no_work_qty"] == 3
    assert done.json()["store"]["status"] == "READY_FOR_ANALYSIS"
    assert _stock_by_location(db_conn, gs_id) == {"ISTORE_DT": 3, "TRANSIT": 1}
    assert await refused(stores.dt, dt_store, [ok_line]) == (409, "G-20")


async def test_ri_store_user_does_not_see_other_stores_goods_slips(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    routing_products: dict[str, str],
    rm: str,
    stores: StoreUsers,
    users: UserFactory,
    make_token: JwtFactory,
) -> None:
    gs_id, _, _ = await _dt_acked(client, storage, actors, masters, routing_products, rm, stores)
    ri = make_token(users.create(roles=["ISTORE_RI"], full_name="Ravi RI Store"))
    res = await _view(client, ri, gs_id)
    assert res.status_code == 404 and res.json()["error"]["code"] == "GS_NOT_AT_STORE"
    queue = (await client.get("/api/v1/department-routing/store/queue", headers=_auth(ri))).json()
    assert gs_id not in {r["gs_id"] for r in queue}
    # The RM (a viewer without a store role) sees every store's progress.
    rm_queue = (
        await client.get(
            "/api/v1/department-routing/store/queue",
            params={"pending_only": "false"},
            headers=_auth(rm),
        )
    ).json()
    row = next(r for r in rm_queue if r["gs_id"] == gs_id)
    assert {s["store_code"] for s in row["stores"]} == {"OP", "DT"}


# --- edit window (DEC-64 d) -------------------------------------------------------------------
async def test_first_routing_closes_the_edit_window(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    routing_products: dict[str, str],
    rm: str,
    mgmt: str,
    stores: StoreUsers,
    users: UserFactory,
    db_conn: Connection,
) -> None:
    gs_id, items, slips = await _dt_acked(
        client, storage, actors, masters, routing_products, rm, stores
    )
    view = (await _view(client, stores.dt, gs_id)).json()
    dt_item = next(i for i in view["items"] if i["store"]["code"] == "DT")
    res = await _route(
        client, stores.dt, gs_id, slips["DT"]["store"]["id"], [_line(dt_item, 1, "STORE", 1)]
    )
    assert res.status_code == 200, res.text

    state = (await client.get(f"/api/v1/gs/{gs_id}/itemization", headers=_auth(mgmt))).json()
    assert state["permissions"]["edit_window_closed"] is True
    edit = await client.patch(
        f"/api/v1/gs/{gs_id}/locked/items/{items[0]}",
        json={
            "received_qty": 3,
            "buckets": [{"field_code": dt_item["conditions"][0]["field_code"], "qty": 3}],
            "reason": "late change",
        },
        headers=_auth(mgmt, key()),
    )
    assert edit.status_code == 409 and edit.json()["error"]["code"] == "EDIT_WINDOW_CLOSED"
    # The DB refuses it too (non-bypassable): the slip cannot be voided any more (Q10 path), and
    # the GS lines cannot change in STORE_PROCESSING.
    c = as_admin(db_conn)
    users.set_actor(users.create(roles=["MANAGEMENT"], full_name="P7 Mgmt"))
    with pytest.raises(DBAPIError, match="department routing has started"), c.begin_nested():
        c.execute(
            text(
                "update public.transfer_slips set status = 'VOIDED', voided_at = now(),"
                " void_reason = 'late change' where id = :s"
            ),
            {"s": slips["DT"]["id"]},
        )
    with pytest.raises(DBAPIError, match="after categorisation"), c.begin_nested():
        c.execute(
            text("update public.gs_items set documented_qty = 9 where id = :i"), {"i": items[0]}
        )
    users.set_actor(None)


# --- DB guards (non-bypassable) ---------------------------------------------------------------
async def test_db_refuses_store_routing_bypass(
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
    gs_id, items, _ = await _dt_acked(
        client, storage, actors, masters, routing_products, rm, stores
    )
    view = (await _view(client, stores.dt, gs_id)).json()
    dt_item = next(i for i in view["items"] if i["store"]["code"] == "DT")
    op_item = next(i for i in view["items"] if i["store"]["code"] == "OP")
    dt_store, op_store = _store_id(db_conn, "DT"), _store_id(db_conn, "OP")
    c = as_admin(db_conn)

    def plan(item: dict[str, Any], store: str, qty: int, dept: str = "STORE") -> None:
        line = _line(item, 0, dept, qty)
        c.execute(
            text(
                """insert into public.department_routing_plan_lines
                     (gs_id, gs_item_id, source_bucket_field_id, department_field_id,
                      department_code, department_label, qty, store_id)
                   values (:g, :i, :b, :d, '-', '-', :q, :s)"""
            ),
            {
                "g": gs_id,
                "i": item["item_id"],
                "b": line["source_bucket_field_id"],
                "d": line["department_field_id"],
                "q": qty,
                "s": store,
            },
        )

    # Another store's user, the RM: refused.
    users.set_actor(stores.op_id)
    with pytest.raises(DBAPIError, match="DEC-67: only a user"), c.begin_nested():
        plan(dt_item, dt_store, 1)
    users.set_actor(actors.rm_id)
    with pytest.raises(DBAPIError, match="DEC-67: only a user"), c.begin_nested():
        plan(dt_item, dt_store, 1)
    users.set_actor(stores.dt_id)
    # The DT user cannot route OP's line under the DT store, nor over-route its own.
    with pytest.raises(DBAPIError, match="belongs to another Intermediate Store"), c.begin_nested():
        plan(op_item, dt_store, 1, "GRADING")
    with pytest.raises(DBAPIError, match="G-20"), c.begin_nested():
        plan(dt_item, dt_store, 3)
    # OP's line is not acknowledged yet.
    users.set_actor(stores.op_id)
    with pytest.raises(DBAPIError, match="not acknowledged"), c.begin_nested():
        plan(op_item, op_store, 1, "GRADING")
    # A DIN of a store needs a user of that store.
    users.set_actor(stores.op_id)
    with pytest.raises(DBAPIError, match="DEC-67: only a user"), c.begin_nested():
        c.execute(
            text(
                """insert into public.department_routings
                     (routing_no, gs_id, department_field_id, department_code, department_label,
                      location_id, store_id)
                   select 'P7-DIN-X', cast(:g as uuid), l.id, '-', '-',
                          (select id from public.inventory_locations where code = 'DEPT_CLEANING'),
                          cast(:s as uuid)
                     from public.item_field_library l
                    where l.field_group = 'DEPARTMENT' and l.code = 'CLEANING'"""
            ),
            {"g": gs_id, "s": dt_store},
        )
    # STORE_PROCESSING only after a routing.
    with pytest.raises(DBAPIError, match="DEC-67: STORE_PROCESSING"), c.begin_nested():
        c.execute(
            text("update public.goods_slips set status = 'STORE_PROCESSING' where id = :g"),
            {"g": gs_id},
        )
    users.set_actor(None)
    assert items  # the GS lines exist; nothing was written above
