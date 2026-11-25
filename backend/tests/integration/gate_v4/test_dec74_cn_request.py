"""DEC-74 (user request 2026-11-25): "Issue CN Request" from the Intermediate Store analysis.

A store user may not set Issue CN (DEC-69 / DEC-70), but may put pieces of an item + condition on
Issue CN Request (code ISSUE_CN_REQUEST) with a quantity. It is one more decision in the G-21
split. Submitting it opens a Management approval request (reason = the requested lines). Until
Management has decided every requested piece (Issue CN or another action):
  * the goods slip does not reach Accounts (gate: service + DB, G-03 exit / Replacement Slip), and
  * Management cannot approve it (service 409 + DB approvals guard).
Management never writes a request itself; the RM (legacy) flow never offers it. The option is
offered only while its library entry is active and the product has a credit-note action.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import JwtFactory
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
    Ready,
    _decide,
    _item,
    _op_back,
    _ready,
    _state,
    _submit,
)
from tests.integration.gate_v4.test_p10_management_approval import (
    _actions,
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

CN_REQ = "ISSUE_CN_REQUEST"
SA = "/api/v1/store-analysis"
MA = "/api/v1/management-approval"


async def _submit_cn(
    client: AsyncClient,
    token: str,
    gs_id: str,
    store_id: str,
    lines: list[dict[str, Any]],
    note: str | None = None,
) -> Any:
    return await client.post(
        f"{SA}/gs/{gs_id}/submit",
        json={
            "store_id": store_id,
            "lines": lines,
            "remarks": "checked",
            "management_approval_reason": note,
        },
        headers=_auth(token, key()),
    )


async def _cn_requested(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: dict[str, str],
    rm: str,
    st: StoreUsers,
) -> Ready:
    """DT requests CN for 2 of its 3 pcs (1 per condition); OP decides Not Allowed."""
    r = await _ready(client, storage, actors, masters, products, rm, st)
    dt = _item((await _state(client, st.dt, r.gs_id)).json(), "DT")
    res = await _submit_cn(
        client,
        st.dt,
        r.gs_id,
        r.dt_store,
        [_decide(dt, 0, SEND_NEW=1, **{CN_REQ: 1}), _decide(dt, 1, **{CN_REQ: 1})],
        note="Party insists on a credit note",
    )
    assert res.status_code == 200, res.text
    await _op_back(client, st, r)
    op = _item((await _state(client, st.op, r.gs_id)).json(), "OP")
    res = await _submit(client, st.op, r.gs_id, r.op_store, [_decide(op, 0, NOT_ALLOWED=1)])
    assert res.status_code == 200, res.text
    # Every store submitted, but the CN request keeps the goods slip away from Accounts.
    assert res.json()["status"] == "ANALYSIS_COMPLETED"
    return r


# --- happy path: store requests, Management decides, approves, Accounts -------------------------
async def test_store_cn_request_decided_by_management(
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
    opts = {o["code"]: o for o in _item(state, "DT")["options"]}
    # The store sees Issue CN Request (flagged, last), never Issue CN itself.
    assert opts[CN_REQ]["is_cn_request"] is True and opts[CN_REQ]["label"] == "Issue CN Request"
    assert "ISSUE_CN" not in opts and "PENDING_BP" not in opts
    assert list(opts)[-1] == CN_REQ
    assert not any(o["is_cn_request"] for c, o in opts.items() if c != CN_REQ)

    dt = _item(state, "DT")
    res = await _submit_cn(
        client,
        stores.dt,
        r.gs_id,
        r.dt_store,
        [_decide(dt, 0, SEND_NEW=1, **{CN_REQ: 1}), _decide(dt, 1, **{CN_REQ: 1})],
        note="Party insists on a credit note",
    )
    assert res.status_code == 200, res.text
    req = res.json()["open_approval_request"]
    assert req["reason"].startswith("Issue CN Request: #")
    assert req["reason"].count("1 pc(s)") == 2
    assert req["reason"].endswith("Note: Party insists on a credit note")
    assert sorted(
        (a[0], a[2]) for a in _actions_by_code(db_conn, r.gs_id)
    ) == [(CN_REQ, 1), (CN_REQ, 1), ("SEND_NEW", 1)]

    await _op_back(client, stores, r)
    op = _item((await _state(client, stores.op, r.gs_id)).json(), "OP")
    done = await _submit(client, stores.op, r.gs_id, r.op_store, [_decide(op, 0, NOT_ALLOWED=1)])
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "ANALYSIS_COMPLETED"

    # Management sees the requested pieces, but cannot pick the request itself.
    view = (await _gs(client, mgmt, r.gs_id)).json()
    assert view["cn_request_qty"] == 2
    dtm = _mitem(view, "DT")
    assert [g["cn_requested_qty"] for g in dtm["groups"]] == [1, 1]
    assert CN_REQ not in {o["code"] for o in dtm["options"]}
    assert "ISSUE_CN" in {o["code"] for o in dtm["options"]}
    assert any(d["is_cn_request"] for d in dtm["groups"][0]["decisions"])
    assert view["accounts_gate"]["passes"] is False
    assert view["accounts_gate"]["problem"].startswith("DEC-74")
    queue = (await client.get(f"{MA}/queue", headers=_auth(mgmt))).json()
    assert next(q for q in queue if q["gs_id"] == r.gs_id)["cn_request_qty"] == 2

    # Approve is refused while pieces are still requested.
    early = await _approve(client, mgmt, r.gs_id)
    assert early.status_code == 409, early.text
    assert early.json()["error"]["code"] == "CN_REQUEST_UNDECIDED"
    # Management cannot answer with the request code.
    bad = await _changes(
        client, mgmt, r.gs_id, [_change(dtm, 1, "keep asking", **{CN_REQ: 1})]
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "CN_REQUEST_NOT_MANAGEMENT"

    # Decide: grant the CN on condition 0, refuse it (Not Allowed) on condition 1.
    ok = await _changes(
        client,
        mgmt,
        r.gs_id,
        [
            _change(dtm, 0, "CN granted", SEND_NEW=1, ISSUE_CN=1),
            _change(dtm, 1, "No CN: wrong usage", NOT_ALLOWED=1),
        ],
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["cn_request_qty"] == 0
    first = next(c for c in body["revisions"][0]["changes"] if c["reason"] == "CN granted")
    assert sorted((d["action_code"], d["qty"]) for d in first["before"]) == [
        (CN_REQ, 1),
        ("SEND_NEW", 1),
    ]
    assert _actions(db_conn, r.gs_id) == [
        ("DT", "ISSUE_CN:1"),
        ("DT", "NOT_ALLOWED:1"),
        ("DT", "SEND_NEW:1"),
        ("OP", "NOT_ALLOWED:1"),
    ]

    approved = await _approve(client, mgmt, r.gs_id)
    assert approved.status_code == 200, approved.text
    out = approved.json()
    assert out["status"] == "ACCOUNTS_PENDING"
    assert out["approvals"][0]["has_issue_cn"] is True
    assert out["requests"][0]["status"] == "RESOLVED"


def _actions_by_code(conn: Connection, gs_id: str) -> list[tuple[str, str | None, int]]:
    rows = (
        as_admin(conn)
        .execute(
            text(
                "select a.action_code, a.action_label, a.qty from public.rm_item_actions a"
                " join public.gs_items gi on gi.id = a.gs_item_id"
                " where gi.gs_id = :g and a.is_current"
            ),
            {"g": gs_id},
        )
        .all()
    )
    return [(r[0], r[1], r[2]) for r in rows]


# --- a second store's request while one is open; option switched off ---------------------------
async def test_cn_request_without_new_request_and_option_off(
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
    dt = _item((await _state(client, stores.dt, r.gs_id)).json(), "DT")
    # DT submits normally and sends a plain request for approval.
    res = await _submit_cn(
        client,
        stores.dt,
        r.gs_id,
        r.dt_store,
        [_decide(dt, 0, SEND_NEW=2), _decide(dt, 1, SEND_NEW=1)],
        note="Please review",
    )
    assert res.status_code == 200, res.text
    assert res.json()["open_approval_request"]["reason"] == "Please review"

    # The option is switched off by Admin: the store no longer sees it and the API refuses it.
    c = as_admin(db_conn)
    c.execute(
        text(
            "update public.item_field_library set is_active = false"
            " where field_group = 'ACTION' and code = :c"
        ),
        {"c": CN_REQ},
    )
    await _op_back(client, stores, r)
    op = _item((await _state(client, stores.op, r.gs_id)).json(), "OP")
    assert CN_REQ not in {o["code"] for o in op["options"]}
    off = await _submit_cn(client, stores.op, r.gs_id, r.op_store, [_decide(op, 0, **{CN_REQ: 1})])
    assert off.status_code == 422 and off.json()["error"]["code"] == "CN_REQUEST_NOT_AVAILABLE"

    # Switched on again: OP requests CN while DT's request is open — no second request, the GS
    # still waits (the gate counts the requested pieces).
    c.execute(
        text(
            "update public.item_field_library set is_active = true"
            " where field_group = 'ACTION' and code = :c"
        ),
        {"c": CN_REQ},
    )
    on = await _submit_cn(client, stores.op, r.gs_id, r.op_store, [_decide(op, 0, **{CN_REQ: 1})])
    assert on.status_code == 200, on.text
    body = on.json()
    assert body["status"] == "ANALYSIS_COMPLETED"
    assert [q["status"] for q in body["approval_requests"]] == ["OPEN"]
    view = (await _gs(client, mgmt, r.gs_id)).json()
    assert view["cn_request_qty"] == 1


# --- DB guards (non-bypassable) -----------------------------------------------------------------
async def test_db_guards_cn_request(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    routing_products: dict[str, str],
    rm: str,
    stores: StoreUsers,
    users: UserFactory,
    make_token: JwtFactory,
    db_conn: Connection,
) -> None:
    r = await _cn_requested(client, storage, actors, masters, routing_products, rm, stores)
    mgmt_id = users.create(roles=["MANAGEMENT"], full_name="DB Mgmt")
    view = (await _gs(client, make_token(mgmt_id), r.gs_id)).json()
    dtm = _mitem(view, "DT")
    item, cond = dtm["gs_item_id"], dtm["groups"][1]["condition_field_id"]
    c = as_admin(db_conn)

    def retire() -> None:
        c.execute(
            text(
                "update public.rm_item_actions set is_current = false"
                " where gs_item_id = :i and condition_field_id = :c and is_current"
            ),
            {"i": item, "c": cond},
        )

    def action(code: str) -> None:
        c.execute(
            text(
                "insert into public.rm_item_actions"
                " (gs_item_id, revision_no, round_no, condition_field_id, action_code, qty, reason)"
                " values (:i, 99, 1, :c, :a, 1, 'db test')"
            ),
            {"i": item, "c": cond, "a": code},
        )

    def approval() -> None:
        c.execute(
            text(
                "insert into public.gs_management_approvals (gs_id, approval_no,"
                " approver_name_snapshot, approver_role_snapshot, revision_no, snapshot,"
                " snapshot_sha256) values (:g, 1, '-', '-', 0, '{}', repeat('0', 64))"
            ),
            {"g": r.gs_id},
        )

    users.set_actor(mgmt_id)
    # The gate names the open CN request first.
    problem = c.execute(
        text("select rms_private.gs_management_gate_problem(:g)"), {"g": r.gs_id}
    ).scalar()
    assert str(problem).startswith("DEC-74")
    # Approving with requested pieces is refused by the DB (not only by the service).
    with pytest.raises(DBAPIError, match="still an Issue CN Request"), c.begin_nested():
        approval()
    # Nor can the goods slip be moved on to Accounts.
    with pytest.raises(DBAPIError, match="Issue CN Request"), c.begin_nested():
        c.execute(
            text("update public.goods_slips set status = 'ACCOUNTS_PENDING' where id = :g"),
            {"g": r.gs_id},
        )
    # Management never writes the request code itself.
    with c.begin_nested():
        retire()
        with (
            pytest.raises(DBAPIError, match="DEC-74: Issue CN Request is raised by a store"),
            c.begin_nested(),
        ):
            action(CN_REQ)
        # Deciding every requested piece clears the DEC-74 block; approval now passes.
        action("ISSUE_CN")
        c.execute(
            text(
                "update public.rm_item_actions set is_current = false"
                " where gs_item_id = :i and condition_field_id = :c and is_current"
                " and action_code = :a"
            ),
            {"i": item, "c": dtm["groups"][0]["condition_field_id"], "a": CN_REQ},
        )
        c.execute(
            text(
                "insert into public.rm_item_actions"
                " (gs_item_id, revision_no, round_no, condition_field_id, action_code, qty, reason)"
                " values (:i, 99, 1, :c, 'NOT_ALLOWED', 1, 'db test')"
            ),
            {"i": item, "c": dtm["groups"][0]["condition_field_id"]},
        )
        assert (
            c.execute(
                text("select rms_private.gs_open_cn_request_qty(:g)"), {"g": r.gs_id}
            ).scalar()
            == 0
        )
        approval()


async def test_db_store_cn_request_only_when_available(
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

    def action(code: str) -> None:
        c.execute(
            text(
                "insert into public.rm_item_actions"
                " (gs_item_id, revision_no, round_no, condition_field_id, action_code, qty)"
                " values (:i, 50, 1, :c, :a, 1)"
            ),
            {"i": item, "c": cond, "a": code},
        )

    users.set_actor(stores.dt_id)
    # Issue CN stays Management's (DEC-69/70); the request is the store's option.
    with pytest.raises(DBAPIError, match="not a store analysis option"), c.begin_nested():
        action("ISSUE_CN")
    allowed = c.begin_nested()
    action(CN_REQ)
    label = c.execute(
        text(
            "select action_label from public.rm_item_actions"
            " where gs_item_id = :i and action_code = :a and is_current"
        ),
        {"i": item, "a": CN_REQ},
    ).scalar()
    assert label == "Issue CN Request"  # G-18 label snapshot
    allowed.rollback()
    c.execute(
        text(
            "update public.item_field_library set is_active = false"
            " where field_group = 'ACTION' and code = :c"
        ),
        {"c": CN_REQ},
    )
    with pytest.raises(DBAPIError, match="Issue CN Request is not available"), c.begin_nested():
        action(CN_REQ)


def test_db_refuses_cn_request_on_rm_flows(db_conn: Connection, users: UserFactory) -> None:
    """DEC-74: on a goods slip outside the store analysis (RM item actions, P2-07 / DEC-57), the
    request is never a decision, even written directly in the DB."""
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
            {"i": item, "a": CN_REQ},
        )
