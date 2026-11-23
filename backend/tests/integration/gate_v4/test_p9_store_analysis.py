"""Phase P9 (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-69 (PROVISIONAL; Q15, Q16).

Once its goods of a GS are back from the departments (or had no work), a user of the Intermediate
Store decides per item + current condition: Dispatch New Piece (SEND_NEW), Dispatch Repaired Piece
(SEND_REPAIRED) or Not Allowed (NOT_ALLOWED), and submits its part in one transaction with an
Idempotency-Key (G-16). Each store submits independently; the last one moves the GS to
ANALYSIS_COMPLETED. Guards (service and DB): only a user of the item's store decides, ISSUE_CN and
PENDING_BP are refused to stores (Issue CN = Management, DEC-70), the split must total the qty
(G-21), a submission is final. Any store user may send the GS for Management approval (reason).
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
    _ack,
    _dt_acked,
    _line,
    _route,
    _view,
    dec59,
    routing_products,
    stores,
)
from tests.integration.gate_v4.test_p8_store_receiving import _din_line, _heads, _receive, _rl
from tests.integration.test_gate_inward import Masters, _auth
from tests.integration.test_itemization import key
from tests.integration.test_unboxing import FakeStorage

pytestmark = pytest.mark.gate_v4

# fixtures re-used from the P5 / P7 tests
__all__ = ["dec59", "mgmt", "products", "rm", "routing_products", "stores"]

BASE = "/api/v1/store-analysis"


class Ready:
    """A GS whose DT part (3 pcs: conditions 2 + 1, both "Issue to Store") is ready for analysis
    and whose OP part (1 pc) is at Grading."""

    def __init__(
        self, gs_id: str, slips: dict[str, dict[str, Any]], op_item: dict[str, Any], din: Any
    ) -> None:
        self.gs_id = gs_id
        self.dt_store = str(slips["DT"]["store"]["id"])
        self.op_store = str(slips["OP"]["store"]["id"])
        self.op_item = op_item
        self.op_din = din


async def _ready(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: dict[str, str],
    rm: str,
    st: StoreUsers,
) -> Ready:
    gs_id, _, slips = await _dt_acked(client, storage, actors, masters, products, rm, st)
    view = (await _view(client, st.dt, gs_id)).json()
    dt_item = next(i for i in view["items"] if i["store"]["code"] == "DT")
    res = await _route(
        client,
        st.dt,
        gs_id,
        slips["DT"]["store"]["id"],
        [_line(dt_item, 0, "STORE", 2), _line(dt_item, 1, "STORE", 1)],
    )
    assert res.status_code == 200, res.text
    await _ack(client, st.op, slips["OP"]["id"])
    op_view = (await _view(client, st.op, gs_id)).json()
    op_item = next(i for i in op_view["items"] if i["store"]["code"] == "OP")
    res = await _route(
        client, st.op, gs_id, slips["OP"]["store"]["id"], [_line(op_item, 0, "GRADING", 1)]
    )
    assert res.status_code == 200, res.text
    return Ready(gs_id, slips, op_item, res.json()["dins"][0])


async def _state(client: AsyncClient, token: str, gs_id: str) -> Any:
    return await client.get(f"{BASE}/gs/{gs_id}", headers=_auth(token))


async def _submit(
    client: AsyncClient,
    token: str,
    gs_id: str,
    store_id: str,
    lines: list[dict[str, Any]],
    idem: str | None = None,
) -> Any:
    return await client.post(
        f"{BASE}/gs/{gs_id}/submit",
        json={"store_id": store_id, "lines": lines, "remarks": "checked"},
        headers=_auth(token, idem or key()),
    )


def _decide(item: dict[str, Any], group: int, **qty: int) -> dict[str, Any]:
    g = item["groups"][group]
    return {
        "gs_item_id": item["gs_item_id"],
        "condition_field_id": g["condition_field_id"],
        "decisions": [{"action_code": c, "qty": q} for c, q in qty.items()],
    }


def _item(state: dict[str, Any], store: str) -> dict[str, Any]:
    return next(i for i in state["items"] if i["store_code"] == store)


def _tasks(conn: Connection, gs_id: str, step: str) -> list[str]:
    rows = fetch_all(
        conn,
        """select r.code from public.workflow_tasks t
             join public.roles r on r.id = t.assigned_role_id
            where t.gs_id = :g and t.step_code = :s and t.status = 'OPEN'
            order by r.code""",
        g=gs_id,
        s=step,
    )
    return [r["code"] for r in rows]


def _actions(conn: Connection, gs_id: str) -> list[tuple[str, str | None, int]]:
    rows = fetch_all(
        conn,
        """select a.action_code, a.condition_label, a.qty
             from public.rm_item_actions a join public.gs_items gi on gi.id = a.gs_item_id
            where gi.gs_id = :g and a.is_current
            order by gi.line_no, a.condition_label, a.action_code""",
        g=gs_id,
    )
    return [(r["action_code"], r["condition_label"], r["qty"]) for r in rows]


async def _op_back(client: AsyncClient, st: StoreUsers, r: Ready) -> None:
    heads = await _heads(client, st.op)
    line = await _din_line(client, st.op, r.op_din["id"])
    cond = r.op_item["conditions"][0]["field_id"]
    res = await _receive(client, st.op, r.op_din["id"], [_rl(line, heads["REPAIRED"], 1, cond)])
    assert res.status_code == 200, res.text
    assert res.json()["store"]["status"] == "READY_FOR_ANALYSIS"


# --- happy path: each store submits, the last one completes the GS ------------------------------
async def test_stores_analyse_and_complete_the_gs(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    routing_products: dict[str, str],
    rm: str,
    stores: StoreUsers,
    db_conn: Connection,
) -> None:
    r = await _ready(client, storage, actors, masters, routing_products, rm, stores)
    assert _tasks(db_conn, r.gs_id, "STORE_ANALYSIS") == ["ISTORE_DT"]

    res = await _state(client, stores.dt, r.gs_id)
    assert res.status_code == 200, res.text
    state = res.json()
    assert sorted(
        (s["store_code"], s["analysis_status"], s["is_mine"]) for s in state["stores"]
    ) == [("DT", "PENDING", True), ("OP", "NOT_READY", False)]
    assert state["submittable_store_ids"] == [r.dt_store]
    dt = _item(state, "DT")
    assert dt["is_mine"] and [g["qty"] for g in dt["groups"]] == [2, 1]
    # Q15: the store options; Issue CN and Pending are not offered.
    codes = {o["code"] for o in dt["options"]}
    assert {"SEND_NEW", "SEND_REPAIRED", "NOT_ALLOWED"} <= codes
    assert not codes & {"ISSUE_CN", "PENDING_BP"}
    assert not _item(state, "OP")["is_mine"]

    # My Work: "Analysis" lists the GS for DT only.
    mine = (await client.get("/api/v1/me/journey/STORE_ANALYSIS", headers=_auth(stores.dt))).json()
    assert r.gs_id in {i["gs_id"] for i in mine["items"]}
    op_work = (
        await client.get("/api/v1/me/journey/STORE_ANALYSIS", headers=_auth(stores.op))
    ).json()
    assert r.gs_id not in {i["gs_id"] for i in op_work["items"]}
    queue = (await client.get(f"{BASE}/queue", headers=_auth(stores.dt))).json()
    assert r.gs_id in {q["gs_id"] for q in queue}

    # DT submits (idempotent replay).
    lines = [_decide(dt, 0, SEND_NEW=1, NOT_ALLOWED=1), _decide(dt, 1, SEND_REPAIRED=1)]
    idem = key()
    first = await _submit(client, stores.dt, r.gs_id, r.dt_store, lines, idem)
    assert first.status_code == 200, first.text
    body = first.json()
    replay = await _submit(client, stores.dt, r.gs_id, r.dt_store, lines, idem)
    assert replay.status_code == 200 and replay.headers.get("Idempotency-Replayed") == "true"
    assert replay.json() == body
    dt_part = next(s for s in body["stores"] if s["store_code"] == "DT")
    assert (dt_part["analysis_status"], dt_part["total_qty"]) == ("SUBMITTED", 3)
    assert body["status"] == "STORE_PROCESSING" and body["submittable_store_ids"] == []
    cond_a, cond_b = (g["condition_label"] for g in dt["groups"])
    assert sorted(_actions(db_conn, r.gs_id)) == sorted(
        [("SEND_NEW", cond_a, 1), ("NOT_ALLOWED", cond_a, 1), ("SEND_REPAIRED", cond_b, 1)]
    )
    assert _tasks(db_conn, r.gs_id, "STORE_ANALYSIS") == []
    # No stock moves at analysis (settled by Accounts / dispatch, P11).
    assert _stock_by_location(db_conn, r.gs_id)["ISTORE_DT"] == 3
    # A submission is final.
    again = await _submit(client, stores.dt, r.gs_id, r.dt_store, lines)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "ANALYSIS_ALREADY_SUBMITTED"
    # Q32: the "Issue to Store" lines of an analysed item can no longer be undone.
    plan = (await _view(client, stores.dt, r.gs_id)).json()
    dt_view = next(i for i in plan["items"] if i["store"]["code"] == "DT")
    assert dt_view["undoable_line_ids"] == []
    undo = await client.post(
        f"/api/v1/department-routing/store/plan-lines/{dt_view['routed'][0]['id']}/undo",
        json={"reason": "mistake"},
        headers=_auth(stores.dt),
    )
    assert undo.status_code == 409 and undo.json()["error"]["code"] == "G-21"

    # OP: back from Grading, then submits; the GS is ANALYSIS_COMPLETED.
    await _op_back(client, stores, r)
    assert _tasks(db_conn, r.gs_id, "STORE_ANALYSIS") == ["ISTORE_OP"]
    op = _item((await _state(client, stores.op, r.gs_id)).json(), "OP")
    done = await _submit(client, stores.op, r.gs_id, r.op_store, [_decide(op, 0, NOT_ALLOWED=1)])
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "ANALYSIS_COMPLETED"
    assert _status(db_conn, r.gs_id) == "ANALYSIS_COMPLETED"
    assert _tasks(db_conn, r.gs_id, "STORE_ANALYSIS") == []
    events = {
        e["event_type"]
        for e in fetch_all(
            as_admin(db_conn),
            "select event_type from public.notification_events where gs_id = :g",
            g=r.gs_id,
        )
    }
    assert {"STORE_ANALYSIS_SUBMITTED", "GS_ANALYSIS_COMPLETED"} <= events
    # The completed GS stays visible (All) but is no longer pending.
    pending = (await client.get(f"{BASE}/queue", headers=_auth(stores.op))).json()
    assert r.gs_id not in {q["gs_id"] for q in pending}
    every = (await client.get(f"{BASE}/queue?pending_only=false", headers=_auth(stores.op))).json()
    assert r.gs_id in {q["gs_id"] for q in every}


# --- guards (service) -------------------------------------------------------------------------
async def test_store_analysis_guards(
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
    r = await _ready(client, storage, actors, masters, routing_products, rm, stores)
    state = (await _state(client, stores.dt, r.gs_id)).json()
    dt, op = _item(state, "DT"), _item(state, "OP")
    ok = [_decide(dt, 0, SEND_NEW=2), _decide(dt, 1, SEND_NEW=1)]

    async def refused(token: str, store: str, lines: list[dict[str, Any]]) -> tuple[int, str]:
        res = await _submit(client, token, r.gs_id, store, lines)
        return res.status_code, res.json()["error"]["code"]

    # Who: RM, Management (no store_analysis.create), another store, the RE.
    assert (await refused(rm, r.dt_store, ok))[0] == 403
    assert (await refused(mgmt, r.dt_store, ok))[0] == 403
    assert (await refused(actors.aman, r.dt_store, ok))[0] == 403
    assert await refused(stores.op, r.dt_store, ok) == (403, "NOT_STORE_USER")
    # OP's goods are still at Grading.
    assert await refused(stores.op, r.op_store, [_decide(op, 0, NOT_ALLOWED=1)]) == (
        409,
        "NOT_READY_FOR_ANALYSIS",
    )
    # Another store's item.
    assert await refused(stores.dt, r.dt_store, [*ok, _decide(op, 0, NOT_ALLOWED=1)]) == (
        403,
        "ITEM_OF_OTHER_STORE",
    )
    # Q15 / DEC-70: Issue CN and Pending are not store options.
    assert await refused(
        stores.dt, r.dt_store, [_decide(dt, 0, ISSUE_CN=2), _decide(dt, 1, SEND_NEW=1)]
    ) == (403, "ACTION_RESERVED")
    assert await refused(
        stores.dt, r.dt_store, [_decide(dt, 0, PENDING_BP=2), _decide(dt, 1, SEND_NEW=1)]
    ) == (403, "ACTION_RESERVED")
    # G-21: the split totals the qty of each item + condition; every group decided once.
    assert await refused(
        stores.dt, r.dt_store, [_decide(dt, 0, SEND_NEW=1), _decide(dt, 1, SEND_NEW=1)]
    ) == (409, "G-21")
    assert await refused(
        stores.dt, r.dt_store, [_decide(dt, 0, SEND_NEW=3), _decide(dt, 1, SEND_NEW=0)]
    ) == (409, "G-21")
    assert await refused(stores.dt, r.dt_store, [_decide(dt, 0, SEND_NEW=2)]) == (
        422,
        "LINES_MISSING",
    )
    assert await refused(stores.dt, r.dt_store, [*ok, ok[0]]) == (422, "DUPLICATE_LINE")
    # Nothing was written.
    assert _actions(db_conn, r.gs_id) == []
    assert _status(db_conn, r.gs_id) == "STORE_PROCESSING"


# --- send for Management approval -------------------------------------------------------------
async def test_send_for_management_approval(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    routing_products: dict[str, str],
    rm: str,
    stores: StoreUsers,
    db_conn: Connection,
) -> None:
    r = await _ready(client, storage, actors, masters, routing_products, rm, stores)
    url = f"{BASE}/gs/{r.gs_id}/management-approval"

    async def send(token: str, store: str, reason: str, idem: str | None = None) -> Any:
        return await client.post(
            url, json={"store_id": store, "reason": reason}, headers=_auth(token, idem or key())
        )

    assert (await send(rm, r.dt_store, "Please check")).status_code == 403
    assert (await send(stores.op, r.dt_store, "Please check")).status_code == 403
    assert (await send(stores.dt, r.dt_store, "ab")).status_code == 422

    # OP may send it although its goods are still at a department (any store on the GS).
    res = await send(stores.op, r.op_store, "Party asks for a credit note")
    assert res.status_code == 200, res.text
    body = res.json()
    req = body["open_approval_request"]
    assert (req["store_id"], req["reason"], req["status"]) == (
        r.op_store,
        "Party asks for a credit note",
        "OPEN",
    )
    assert body["can_request_approval"] is False
    again = await send(stores.dt, r.dt_store, "Another reason")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "APPROVAL_ALREADY_REQUESTED"
    events = fetch_all(
        as_admin(db_conn),
        "select event_type from public.notification_events where gs_id = :g"
        " and event_type = 'MANAGEMENT_APPROVAL_REQUESTED'",
        g=r.gs_id,
    )
    assert len(events) == 1
    # The DT view shows the open request too.
    dt_state = (await _state(client, stores.dt, r.gs_id)).json()
    assert dt_state["open_approval_request"]["id"] == req["id"]


# --- DB guards (non-bypassable) ---------------------------------------------------------------
async def test_db_refuses_store_analysis_bypass(
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
    r = await _ready(client, storage, actors, masters, routing_products, rm, stores)
    state = (await _state(client, stores.dt, r.gs_id)).json()
    dt, op = _item(state, "DT"), _item(state, "OP")
    c = as_admin(db_conn)

    def action(item: dict[str, Any], group: int, code: str, qty: int) -> None:
        c.execute(
            text(
                "insert into public.rm_item_actions"
                " (gs_item_id, revision_no, round_no, condition_field_id, action_code, qty)"
                " values (:i, 1, 1, :c, :a, :q)"
            ),
            {
                "i": item["gs_item_id"],
                "c": item["groups"][group]["condition_field_id"],
                "a": code,
                "q": qty,
            },
        )

    def submission(store: str) -> None:
        c.execute(
            text(
                "insert into public.gs_store_analyses"
                " (gs_id, store_id, store_code_snapshot, store_name_snapshot, revision_no,"
                "  total_qty) values (:g, :s, '-', '-', 1, 1)"
            ),
            {"g": r.gs_id, "s": store},
        )

    # Another store's user, the RM and no actor cannot decide DT's goods.
    for actor in (stores.op_id, actors.rm_id, None):
        users.set_actor(actor)
        with pytest.raises(DBAPIError, match="DEC-69"), c.begin_nested():
            action(dt, 0, "SEND_NEW", 2)
    # The store itself: Issue CN / Pending refused; a goods slip part not ready refused.
    users.set_actor(stores.dt_id)
    for code in ("ISSUE_CN", "PENDING_BP"):
        with pytest.raises(DBAPIError, match="not a store analysis option"), c.begin_nested():
            action(dt, 0, code, 2)
    users.set_actor(stores.op_id)
    with pytest.raises(DBAPIError, match="not ready for analysis"), c.begin_nested():
        action(op, 0, "NOT_ALLOWED", 1)
    with pytest.raises(DBAPIError, match="no goods ready for analysis"), c.begin_nested():
        submission(r.op_store)

    # G-21: a partial decision cannot be submitted, nor committed (deferred check).
    users.set_actor(stores.dt_id)
    with c.begin_nested():
        action(dt, 0, "SEND_NEW", 2)
        with pytest.raises(DBAPIError, match="G-21"), c.begin_nested():
            submission(r.dt_store)
        with pytest.raises(DBAPIError, match="G-21"), c.begin_nested():
            c.execute(text("set constraints rm_item_actions_g21 immediate"))
        c.execute(text("set constraints rm_item_actions_g21 deferred"))
        # Complete: then the submission is accepted and becomes history.
        action(dt, 1, "NOT_ALLOWED", 1)
        submission(r.dt_store)
        c.execute(text("set constraints rm_item_actions_g21 immediate"))
        c.execute(text("set constraints rm_item_actions_g21 deferred"))
        snap = c.execute(
            text(
                "select store_code_snapshot, total_qty, submitted_by from public.gs_store_analyses"
                " where gs_id = :g"
            ),
            {"g": r.gs_id},
        ).one()
        assert (snap[0], snap[1], str(snap[2])) == ("DT", 3, str(stores.dt_id))
        with pytest.raises(DBAPIError, match="kept as history"), c.begin_nested():
            c.execute(text("delete from public.gs_store_analyses where gs_id = :g"), {"g": r.gs_id})
        # After the submission the store's decisions are frozen.
        with pytest.raises(DBAPIError, match="submitted its analysis"), c.begin_nested():
            action(dt, 1, "SEND_NEW", 1)
        # Approval request: a store user of the GS only; one OPEN per GS; history only.
        users.set_actor(actors.rm_id)
        with pytest.raises(DBAPIError, match="DEC-69"), c.begin_nested():
            c.execute(
                text(
                    "insert into public.gs_management_approval_requests"
                    " (gs_id, store_id, store_name_snapshot, reason) values (:g, :s, '-', 'why')"
                ),
                {"g": r.gs_id, "s": r.dt_store},
            )
    users.set_actor(None)
    assert _status(db_conn, r.gs_id) == "STORE_PROCESSING"
