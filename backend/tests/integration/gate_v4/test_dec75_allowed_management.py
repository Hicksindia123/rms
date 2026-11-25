"""DEC-75 (user request 2026-11-25): store analysis = Allowed / Not Allowed, then the Allowed
pieces split into "Send New Pieces to Party" / "Send Repaired Pieces to Party"; pieces are sent for
Management approval per item + condition + qty with a proposed action (Send New / Issue CN).

* The store only decides the configured verdict actions (setting store_analysis.verdicts); the
  retired DEC-74 "Issue CN Request" option and Issue CN are refused (service + DB).
* Nothing sent to Management = the goods slip goes straight to Accounts (Replacement Slip).
* Pieces sent (with the submission or later, until Accounts completes): request lines with the
  previous action and the proposal; Management sees them plus the store's own decisions, decides
  (final) and approves; the goods slip then reaches Accounts.
* Sending at Accounts (entry not completed) withdraws the Replacement Slip (DEC-71).
* DB guards: verdict guard, request lines append-only, store-only, free qty, proposals config.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from tests.integration.conftest import UserFactory, as_admin
from tests.integration.gate_v4.test_gate_v4 import Actors
from tests.integration.gate_v4.test_p5_transfer_slips import mgmt, products, rm
from tests.integration.gate_v4.test_p7_store_routing import (
    StoreUsers,
    dec59,
    routing_products,
    stores,
)
from tests.integration.gate_v4.test_p9_store_analysis import (
    _decide,
    _item,
    _op_back,
    _ready,
    _state,
    _submit,
)
from tests.integration.gate_v4.test_p10_management_approval import (
    _approve,
    _change,
    _changes,
    _gs,
    _mitem,
)
from tests.integration.test_gate_inward import Masters, _auth
from tests.integration.test_itemization import key
from tests.integration.test_unboxing import FakeStorage

pytestmark = pytest.mark.gate_v4

# fixtures re-used from the P5 / P7 tests
__all__ = ["dec59", "mgmt", "products", "rm", "routing_products", "stores"]

SA = "/api/v1/store-analysis"
MA = "/api/v1/management-approval"


def _line(item: dict[str, Any], group: int, frm: str, proposed: str, qty: int) -> dict[str, Any]:
    g = item["groups"][group]
    return {
        "gs_item_id": item["gs_item_id"],
        "condition_field_id": g["condition_field_id"],
        "from_action_code": frm,
        "proposed_action_code": proposed,
        "qty": qty,
    }


async def _submit_with(
    client: AsyncClient,
    token: str,
    gs_id: str,
    store_id: str,
    lines: list[dict[str, Any]],
    mlines: list[dict[str, Any]],
    note: str | None = None,
) -> Any:
    return await client.post(
        f"{SA}/gs/{gs_id}/submit",
        json={
            "store_id": store_id,
            "lines": lines,
            "management_lines": mlines,
            "management_approval_reason": note,
        },
        headers=_auth(token, key()),
    )


# --- options: verdicts only ----------------------------------------------------------------------
async def test_store_sees_verdicts_only(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    routing_products: dict[str, str],
    rm: str,
    stores: StoreUsers,
) -> None:
    r = await _ready(client, storage, actors, masters, routing_products, rm, stores)
    state = (await _state(client, stores.dt, r.gs_id)).json()
    assert state["verdicts"] == {
        "allowed": {"label": "Allowed", "actions": ["SEND_NEW", "SEND_REPAIRED"]},
        "not_allowed": {"label": "Not Allowed", "actions": ["NOT_ALLOWED"]},
    }
    assert [(p["code"], p["label"]) for p in state["proposals"]] == [
        ("SEND_NEW", "Send New Pieces to Party"),
        ("ISSUE_CN", "Issue CN"),
    ]
    dt = _item(state, "DT")
    labels = {o["code"]: o["label"] for o in dt["options"]}
    assert labels == {
        "SEND_NEW": "Send New Pieces to Party",
        "SEND_REPAIRED": "Send Repaired Pieces to Party",
        "NOT_ALLOWED": "Not Allowed",
    }
    # The retired DEC-74 option and Issue CN are refused.
    bad = await _submit(
        client,
        stores.dt,
        r.gs_id,
        r.dt_store,
        [_decide(dt, 0, ISSUE_CN_REQUEST=2), _decide(dt, 1, SEND_NEW=1)],
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "ACTION_NOT_A_VERDICT"
    cn = await _submit(
        client,
        stores.dt,
        r.gs_id,
        r.dt_store,
        [_decide(dt, 0, ISSUE_CN=2), _decide(dt, 1, SEND_NEW=1)],
    )
    assert cn.status_code == 403 and cn.json()["error"]["code"] == "ACTION_RESERVED"
    # A note alone sends nothing: pieces must be selected.
    note_only = await _submit_with(
        client,
        stores.dt,
        r.gs_id,
        r.dt_store,
        [_decide(dt, 0, SEND_NEW=2), _decide(dt, 1, SEND_NEW=1)],
        [],
        note="Please check",
    )
    assert note_only.status_code == 422
    assert note_only.json()["error"]["code"] == "MANAGEMENT_LINES_REQUIRED"


# --- nothing sent: straight to Accounts ------------------------------------------------------
async def test_nothing_sent_goes_to_accounts(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    routing_products: dict[str, str],
    rm: str,
    mgmt: str,
    stores: StoreUsers,
) -> None:
    r = await _ready(client, storage, actors, masters, routing_products, rm, stores)
    dt = _item((await _state(client, stores.dt, r.gs_id)).json(), "DT")
    res = await _submit(
        client,
        stores.dt,
        r.gs_id,
        r.dt_store,
        [_decide(dt, 0, SEND_NEW=1, SEND_REPAIRED=1), _decide(dt, 1, NOT_ALLOWED=1)],
    )
    assert res.status_code == 200, res.text
    await _op_back(client, stores, r)
    op = _item((await _state(client, stores.op, r.gs_id)).json(), "OP")
    done = await _submit(client, stores.op, r.gs_id, r.op_store, [_decide(op, 0, NOT_ALLOWED=1)])
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["status"] == "ACCOUNTS_PENDING"
    assert body["approval_requests"] == [] and body["request_lines"] == []
    queue = (await client.get(f"{MA}/queue", headers=_auth(mgmt))).json()
    assert all(q["request_id"] is None for q in queue if q["gs_id"] == r.gs_id)


# --- sent with the submission: Management sees, decides, approves ---------------------------------
async def test_pieces_sent_with_submission_decided_by_management(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    routing_products: dict[str, str],
    rm: str,
    mgmt: str,
    stores: StoreUsers,
) -> None:
    r = await _ready(client, storage, actors, masters, routing_products, rm, stores)
    dt = _item((await _state(client, stores.dt, r.gs_id)).json(), "DT")
    # DT: cond 0 = 2 pcs Not Allowed, cond 1 = 1 pc Send New. Sends 2 Not Allowed → Issue CN.
    bad = await _submit_with(
        client,
        stores.dt,
        r.gs_id,
        r.dt_store,
        [_decide(dt, 0, NOT_ALLOWED=2), _decide(dt, 1, SEND_NEW=1)],
        [_line(dt, 0, "NOT_ALLOWED", "SEND_REPAIRED", 1)],
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "PROPOSAL_NOT_ALLOWED"
    same = await _submit_with(
        client,
        stores.dt,
        r.gs_id,
        r.dt_store,
        [_decide(dt, 0, NOT_ALLOWED=2), _decide(dt, 1, SEND_NEW=1)],
        [_line(dt, 1, "SEND_NEW", "SEND_NEW", 1)],
    )
    assert same.status_code == 422 and same.json()["error"]["code"] == "PROPOSAL_UNCHANGED"
    over = await _submit_with(
        client,
        stores.dt,
        r.gs_id,
        r.dt_store,
        [_decide(dt, 0, NOT_ALLOWED=2), _decide(dt, 1, SEND_NEW=1)],
        [_line(dt, 0, "NOT_ALLOWED", "ISSUE_CN", 3)],
    )
    assert over.status_code == 422 and over.json()["error"]["code"] == "QTY_EXCEEDS_FREE"
    res = await _submit_with(
        client,
        stores.dt,
        r.gs_id,
        r.dt_store,
        [_decide(dt, 0, NOT_ALLOWED=2), _decide(dt, 1, SEND_NEW=1)],
        [_line(dt, 0, "NOT_ALLOWED", "ISSUE_CN", 2)],
        note="Party has a long-standing claim",
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["open_approval_request"]["reason"].endswith("Note: Party has a long-standing claim")
    g0 = _item(body, "DT")["groups"][0]
    assert [
        (m["from_action_label"], m["proposed_action_label"], m["qty"])
        for m in g0["management_lines"]
    ] == [("Not Allowed", "Issue CN", 2)]
    assert g0["sendable"] == [
        {"action_code": "NOT_ALLOWED", "label": "Not Allowed", "qty": 2, "free_qty": 0}
    ]

    await _op_back(client, stores, r)
    op = _item((await _state(client, stores.op, r.gs_id)).json(), "OP")
    done = await _submit(client, stores.op, r.gs_id, r.op_store, [_decide(op, 0, SEND_REPAIRED=1)])
    assert done.status_code == 200, done.text
    # The open request keeps the goods slip away from Accounts.
    assert done.json()["status"] == "ANALYSIS_COMPLETED"

    view = (await _gs(client, mgmt, r.gs_id)).json()
    assert view["requested_qty"] == 2
    dtm = _mitem(view, "DT")
    req = dtm["groups"][0]["requested"]
    assert [
        (x["from_action_code"], x["proposed_action_code"], x["qty"], x["request_status"])
        for x in req
    ] == [("NOT_ALLOWED", "ISSUE_CN", 2, "OPEN")]
    assert [(d["action_code"], d["qty"]) for d in dtm["groups"][0]["store_decisions"]] == [
        ("NOT_ALLOWED", 2)
    ]
    queue = (await client.get(f"{MA}/queue", headers=_auth(mgmt))).json()
    assert next(q for q in queue if q["gs_id"] == r.gs_id)["requested_qty"] == 2

    # Management's decision is final: it may decide differently from the proposal.
    ok = await _changes(
        client,
        mgmt,
        r.gs_id,
        [_change(dtm, 0, "One CN, one new piece", ISSUE_CN=1, SEND_NEW=1)],
    )
    assert ok.status_code == 200, ok.text
    after = _mitem(ok.json(), "DT")["groups"][0]
    # The store's original decision stays visible after the change.
    assert [(d["action_code"], d["qty"]) for d in after["store_decisions"]] == [("NOT_ALLOWED", 2)]
    approved = await _approve(client, mgmt, r.gs_id)
    assert approved.status_code == 200, approved.text
    out = approved.json()
    assert out["status"] == "ACCOUNTS_PENDING"
    assert out["requests"][0]["status"] == "RESOLVED"
    assert out["requested_qty"] == 0


# --- sent later, at Accounts: the Replacement Slip is withdrawn -----------------------------------
async def test_send_at_accounts_reopens(
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
    dt = _item((await _state(client, stores.dt, r.gs_id)).json(), "DT")
    await _submit(
        client,
        stores.dt,
        r.gs_id,
        r.dt_store,
        [_decide(dt, 0, SEND_NEW=2), _decide(dt, 1, SEND_REPAIRED=1)],
    )
    await _op_back(client, stores, r)
    op = _item((await _state(client, stores.op, r.gs_id)).json(), "OP")
    done = await _submit(client, stores.op, r.gs_id, r.op_store, [_decide(op, 0, SEND_NEW=1)])
    assert done.json()["status"] == "ACCOUNTS_PENDING"
    assert done.json()["can_send_to_management"] is True

    res = await client.post(
        f"{SA}/gs/{r.gs_id}/management-approval",
        json={"lines": [_line(dt, 1, "SEND_REPAIRED", "ISSUE_CN", 1)], "reason": "Late claim"},
        headers=_auth(stores.dt, key()),
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "ANALYSIS_COMPLETED"
    slips = (
        as_admin(db_conn)
        .execute(text("select status from public.ac_action_slips where gs_id = :g"), {"g": r.gs_id})
        .scalars()
        .all()
    )
    assert list(slips) == ["SUPERSEDED"]


# --- DB guards (non-bypassable) -----------------------------------------------------------------
async def test_db_guards_verdicts_and_request_lines(
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
    dt = _item((await _state(client, stores.dt, r.gs_id)).json(), "DT")
    item, cond = dt["gs_item_id"], dt["groups"][0]["condition_field_id"]
    c = as_admin(db_conn)
    users.set_actor(stores.dt_id)
    # Verdict guard: the retired DEC-74 code (and anything outside the verdicts) is refused.
    with pytest.raises(DBAPIError, match=r"DEC-7[45]"), c.begin_nested():
        c.execute(
            text(
                "insert into public.rm_item_actions"
                " (gs_item_id, revision_no, round_no, condition_field_id, action_code, qty)"
                " values (:i, 50, 1, :c, 'ISSUE_CN_REQUEST', 1)"
            ),
            {"i": item, "c": cond},
        )
    res = await _submit(
        client,
        stores.dt,
        r.gs_id,
        r.dt_store,
        [_decide(dt, 0, NOT_ALLOWED=2), _decide(dt, 1, SEND_NEW=1)],
    )
    assert res.status_code == 200, res.text
    req_id = c.execute(
        text(
            "insert into public.gs_management_approval_requests (gs_id, store_id,"
            " store_name_snapshot, reason) values (:g, :s, '-', 'db test') returning id"
        ),
        {"g": r.gs_id, "s": r.dt_store},
    ).scalar()

    def add(frm: str, prop: str, qty: int) -> None:
        c.execute(
            text(
                "insert into public.gs_management_request_lines (request_id, gs_id, gs_item_id,"
                " condition_field_id, store_id, from_action_code, from_action_label,"
                " proposed_action_code, proposed_action_label, qty)"
                " values (:r, :g, :i, :c, :s, :f, '-', :p, '-', :q)"
            ),
            {
                "r": req_id,
                "g": r.gs_id,
                "i": item,
                "c": cond,
                "s": r.dt_store,
                "f": frm,
                "p": prop,
                "q": qty,
            },
        )

    with pytest.raises(DBAPIError, match="not a proposal"), c.begin_nested():
        add("NOT_ALLOWED", "SEND_REPAIRED", 1)
    with pytest.raises(DBAPIError, match="free to send"), c.begin_nested():
        add("NOT_ALLOWED", "ISSUE_CN", 3)
    with pytest.raises(DBAPIError, match="no current"), c.begin_nested():
        add("SEND_NEW", "ISSUE_CN", 1)
    # Another store's user cannot send DT's pieces.
    users.set_actor(stores.op_id)
    with pytest.raises(DBAPIError, match="only a user of that store"), c.begin_nested():
        add("NOT_ALLOWED", "ISSUE_CN", 1)
    users.set_actor(stores.dt_id)
    add("NOT_ALLOWED", "ISSUE_CN", 2)
    label = c.execute(
        text(
            "select from_action_label from public.gs_management_request_lines where request_id = :r"
        ),
        {"r": req_id},
    ).scalar()
    assert label == "Not Allowed"  # snapshot stamped by the DB
    # Append-only.
    with pytest.raises(DBAPIError, match="append-only"), c.begin_nested():
        c.execute(
            text("update public.gs_management_request_lines set qty = 1 where request_id = :r"),
            {"r": req_id},
        )
    with pytest.raises(DBAPIError, match="append-only"), c.begin_nested():
        c.execute(
            text("delete from public.gs_management_request_lines where request_id = :r"),
            {"r": req_id},
        )


def test_db_refuses_cn_request_on_rm_flows(db_conn: Connection, users: UserFactory) -> None:
    """DEC-74 (kept): on a goods slip outside the store analysis (RM item actions, P2-07 /
    DEC-57), the request code is never a decision, even written directly in the DB."""
    c = as_admin(db_conn)
    rm_id = users.create(roles=["REPLACEMENT_MANAGER"], full_name="DB RM")
    item = c.execute(
        text(
            """
            with wv as (
              select v.id from public.workflow_versions v
                join public.workflow_definitions d on d.id = v.workflow_definition_id
               where d.code = 'RMS_STANDARD' and v.status = 'PUBLISHED' limit 1
            ), gs as (
              insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code,
                                              courier_name, docket_no, carton_count, status)
              select 'PYTEST-DEC74-RM', wv.id, 'COURIER_PARCEL', 'A', 'PYTEST-DEC74-RM', 1,
                     'GATE_CREATED'
                from wv
              returning id
            )
            insert into public.gs_items (gs_id, line_no, product_id, category_id,
                                         documented_qty, received_qty)
            select gs.id, 1, p.id, p.category_id, 1, 1
              from gs, (select id, category_id from public.products
                         where category_id is not null limit 1) p
            returning id
            """
        )
    ).scalar()
    users.set_actor(rm_id)
    with (
        pytest.raises(DBAPIError, match="used only by the Intermediate Store analysis"),
        c.begin_nested(),
    ):
        c.execute(
            text(
                "insert into public.rm_item_actions (gs_item_id, revision_no, action_code, qty)"
                " values (:i, 1, :a, 1)"
            ),
            {"i": item, "a": "ISSUE_CN_REQUEST"},
        )
