"""Phase P11 (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-71 (Q19 PROVISIONAL; Q21, Q22).

A store-flow goods slip reaches Accounts only when every store with goods on it submitted its
analysis, no Management approval is pending and the Issue CN guard passes (DEC-70). At that moment
one Replacement Slip (ac_action_slips, versioned) is created. Accounts enters ONE Challan No. + Date
(only if goods ship) and ONE CN No. + Date + Value (only if the GS has Issue CN) per goods slip;
completion generates the Dispatch Slip (DISPATCH_PENDING) or, with nothing to ship, settles the
pieces and hands the GS to closure. Everything Not Allowed → NOT_ALLOWED_HOLD (Q21), never at
Accounts. Guards in the service and the DB.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, fetch_all
from tests.integration.gate_v4.test_gate_v4 import Actors
from tests.integration.gate_v4.test_p5_transfer_slips import (
    _pdf_text,
    _status,
    _stock_by_location,
    mgmt,
    products,
    rm,
)
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
    _analysed,
    _approve,
    _change,
    _changes,
    _gs,
    _mitem,
    _slips,
)
from tests.integration.test_gate_inward import Masters, _auth
from tests.integration.test_itemization import key
from tests.integration.test_unboxing import FakeStorage

pytestmark = pytest.mark.gate_v4

# fixtures re-used from the P5 / P7 tests
__all__ = ["dec59", "mgmt", "products", "rm", "routing_products", "stores"]

AC = "/api/v1/ac-entry"
TODAY = date.today().isoformat()


async def _dt_submit(client: AsyncClient, st: StoreUsers, r: Ready, **cond: dict[str, int]) -> None:
    dt = _item((await _state(client, st.dt, r.gs_id)).json(), "DT")
    res = await _submit(
        client,
        st.dt,
        r.gs_id,
        r.dt_store,
        [_decide(dt, 0, **cond["a"]), _decide(dt, 1, **cond["b"])],
    )
    assert res.status_code == 200, res.text


async def _op_submit(client: AsyncClient, st: StoreUsers, r: Ready, **qty: int) -> Any:
    await _op_back(client, st, r)
    op = _item((await _state(client, st.op, r.gs_id)).json(), "OP")
    res = await _submit(client, st.op, r.gs_id, r.op_store, [_decide(op, 0, **qty)])
    assert res.status_code == 200, res.text
    return res.json()


async def _entry(client: AsyncClient, token: str, gs_id: str) -> Any:
    return await client.get(f"{AC}/gs/{gs_id}", headers=_auth(token))


async def _save(
    client: AsyncClient, token: str, gs_id: str, slip_id: str, idem: str | None = None, **f: Any
) -> Any:
    return await client.put(
        f"{AC}/gs/{gs_id}/entry",
        json={"ac_action_slip_id": slip_id, **f},
        headers=_auth(token, idem or key()),
    )


async def _complete(client: AsyncClient, token: str, gs_id: str, slip_id: str) -> Any:
    return await client.post(
        f"{AC}/gs/{gs_id}/complete",
        json={"ac_action_slip_id": slip_id, "remarks": "entered"},
        headers=_auth(token, key()),
    )


def _queue_ids(rows: list[dict[str, Any]]) -> set[str]:
    return {q["gs_id"] for q in rows}


def _replacement_pdf(conn: Connection, storage: FakeStorage, gs_id: str) -> str:
    path = (
        as_admin(conn)
        .execute(
            text(
                "select a.object_path from public.ac_action_slips s"
                " join public.attachments a on a.id = s.attachment_id"
                " where s.gs_id = :g and s.status = 'CURRENT'"
            ),
            {"g": gs_id},
        )
        .scalar_one()
    )
    return _pdf_text(next(data for (_, p), data in storage.uploads.items() if p == path))


@pytest.fixture
def accounts(users: UserFactory, make_token: JwtFactory) -> str:
    return make_token(users.create(roles=["ACCOUNTS"], full_name="Acc User"))


@pytest.fixture
def dispatcher(users: UserFactory, make_token: JwtFactory) -> str:
    return make_token(users.create(roles=["DISPATCH"], full_name="Dispatch User"))


# --- challan only: gate, Replacement Slip, entry, Dispatch Slip, dispatch + stock ---------------
async def test_challan_only_goods_slip_to_dispatch(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    routing_products: dict[str, str],
    rm: str,
    stores: StoreUsers,
    accounts: str,
    dispatcher: str,
    db_conn: Connection,
) -> None:
    r = await _ready(client, storage, actors, masters, routing_products, rm, stores)
    await _dt_submit(client, stores, r, a={"SEND_NEW": 2}, b={"NOT_ALLOWED": 1})
    # Blocked while one store (OP) is still pending: no Replacement Slip, not in the queue.
    assert _status(db_conn, r.gs_id) == "STORE_PROCESSING"
    assert _slips(db_conn, r.gs_id) == []
    pending = (await client.get(f"{AC}/queue", headers=_auth(accounts))).json()
    assert r.gs_id not in _queue_ids(pending)

    done = await _op_submit(client, stores, r, SEND_REPAIRED=1)
    assert done["status"] == "ACCOUNTS_PENDING"
    assert _slips(db_conn, r.gs_id) == [(1, "CURRENT")]
    queue = (await client.get(f"{AC}/queue", headers=_auth(accounts))).json()
    row = next(q for q in queue if q["gs_id"] == r.gs_id)
    assert (row["per_gs"], row["requires_challan"], row["requires_cn"]) == (True, True, False)
    assert (row["lines_needing_data"], row["lines_complete"]) == (1, 0)
    # Accounts in-app alert (rule AC_ACTIONS_SLIP_READY → ACCOUNTS; email deferred, Q22).
    events = fetch_all(
        as_admin(db_conn),
        "select payload from public.notification_events where gs_id = :g"
        " and event_type = 'AC_ACTIONS_SLIP_READY'",
        g=r.gs_id,
    )
    assert len(events) == 1 and "Replacement Slip" in str(events[0]["payload"])
    # The Replacement Slip PDF: store + condition + action lines, totals; no stamp (no approval).
    pdf = _replacement_pdf(db_conn, storage, r.gs_id)
    assert "Replacement Slip" in pdf and "Totals by Action" in pdf
    assert "Send New Pieces to Party" in pdf and "Not Allowed" in pdf
    assert "Digitally approved" not in pdf

    state = (await _entry(client, accounts, r.gs_id)).json()
    assert state["per_gs"] is True and state["slip_title"] == "Replacement Slip"
    entry = state["gs_entry"]
    assert (entry["requires_challan"], entry["requires_cn"]) == (True, False)
    assert state["can_edit"] is True and state["can_complete"] is False
    slip = state["ac_action_slip_id"]

    async def refused(**f: Any) -> tuple[int, str]:
        res = await _save(client, accounts, r.gs_id, slip, **f)
        return res.status_code, res.json()["error"]["code"]

    # Hidden fields are not taken (no Issue CN on this GS); groups together; no future dates.
    assert await refused(cn_no="CN-1", cn_date=TODAY, cn_value="10") == (409, "G-22")
    assert await refused(challan_no="CH-1") == (422, "CHALLAN_FIELDS_INCOMPLETE")
    future = (date.today() + timedelta(days=2)).isoformat()
    assert await refused(challan_no="CH-1", challan_date=future) == (422, "DATE_IN_FUTURE")
    # The per-line entry is refused for a store-flow GS.
    line = state["lines"][0]
    per_line = await client.put(
        f"{AC}/gs/{r.gs_id}/lines",
        json={"ac_action_slip_id": slip, "lines": [{"line_id": line["id"], "challan_no": "X"}]},
        headers=_auth(accounts, key()),
    )
    assert per_line.status_code == 409 and per_line.json()["error"]["code"] == "PER_GS_ENTRY"
    # Not complete yet.
    early = await _complete(client, accounts, r.gs_id, slip)
    assert early.status_code == 409 and early.json()["error"]["code"] == "G-22"

    idem = key()
    ok = await _save(
        client, accounts, r.gs_id, slip, idem, challan_no=" CH-77 ", challan_date=TODAY
    )
    assert ok.status_code == 200, ok.text
    replay = await _save(
        client, accounts, r.gs_id, slip, idem, challan_no=" CH-77 ", challan_date=TODAY
    )
    assert replay.headers.get("Idempotency-Replayed") == "true"
    saved = ok.json()
    assert saved["gs_entry"]["challan_no"] == "CH-77" and saved["can_complete"] is True

    stock_before = _stock_by_location(db_conn, r.gs_id)
    assert stock_before == {"ISTORE_DT": 3, "ISTORE_OP": 1}
    res = await _complete(client, accounts, r.gs_id, slip)
    assert res.status_code == 200, res.text
    completed = res.json()
    assert completed["is_completed"] is True and completed["gs_status"] == "DISPATCH_PENDING"
    dslip = completed["dispatch_slip"]
    assert dslip["status"] == "READY" and dslip["total_qty"] == 3
    # Nothing moves before dispatch.
    assert _stock_by_location(db_conn, r.gs_id) == stock_before
    lines = fetch_all(
        as_admin(db_conn),
        "select action_code, qty, challan_no from public.dispatch_slip_lines"
        " where dispatch_slip_id = :d order by action_code",
        d=dslip["id"],
    )
    assert [(x["action_code"], x["qty"], x["challan_no"]) for x in lines] == [
        ("SEND_NEW", 2, "CH-77"),
        ("SEND_REPAIRED", 1, "CH-77"),
    ]
    # A completed entry is frozen; Management can no longer reopen the goods slip.
    again = await _save(client, accounts, r.gs_id, slip, challan_no="CH-78", challan_date=TODAY)
    assert again.status_code == 409

    res = await client.post(
        f"/api/v1/dispatch-slips/{dslip['id']}/dispatch",
        json={"dispatch_date": TODAY, "transporter": "Blue Dart", "docket_no": "D-1"},
        headers=_auth(dispatcher, key()),
    )
    assert res.status_code == 200, res.text
    # DEC-57 destinations, from each item's store location: Dispatch New → old piece to the
    # Non-Functional Store, Not Allowed → Rejected Hold, Dispatch Repaired → dispatched.
    assert _stock_by_location(db_conn, r.gs_id) == {
        "NON_FUNCTIONAL_STORE": 2,
        "REJECTED_HOLD": 1,
        "DISPATCHED": 1,
    }
    assert _status(db_conn, r.gs_id) not in {"ACCOUNTS_PENDING", "DISPATCH_PENDING"}


# --- Issue CN only, and both; CN unique across goods slips -------------------------------------
async def test_cn_only_and_both(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    routing_products: dict[str, str],
    rm: str,
    mgmt: str,
    stores: StoreUsers,
    accounts: str,
    db_conn: Connection,
) -> None:
    # GS 1: Management turns DT into Issue CN; OP stays Not Allowed → CN only.
    one = await _analysed(client, storage, actors, masters, routing_products, rm, stores)
    # Blocked while the store's request is open (and Issue CN not approved).
    assert _status(db_conn, one.gs_id) == "ANALYSIS_COMPLETED" and _slips(db_conn, one.gs_id) == []
    dtm = _mitem((await _gs(client, mgmt, one.gs_id)).json(), "DT")
    res = await _changes(
        client,
        mgmt,
        one.gs_id,
        [_change(dtm, 0, "credit", ISSUE_CN=2), _change(dtm, 1, "credit", ISSUE_CN=1)],
    )
    assert res.status_code == 200, res.text
    assert _status(db_conn, one.gs_id) == "ANALYSIS_COMPLETED"
    approved = await _approve(client, mgmt, one.gs_id)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "ACCOUNTS_PENDING"
    pdf = _replacement_pdf(db_conn, storage, one.gs_id)
    assert "Digitally approved by Management" in pdf and "Issue CN" in pdf

    state = (await _entry(client, accounts, one.gs_id)).json()
    assert (state["gs_entry"]["requires_challan"], state["gs_entry"]["requires_cn"]) == (
        False,
        True,
    )
    assert state["management_stamp"].startswith("Digitally approved by Management")
    slip = state["ac_action_slip_id"]
    ch = await _save(client, accounts, one.gs_id, slip, challan_no="CH-1", challan_date=TODAY)
    assert ch.status_code == 409 and ch.json()["error"]["code"] == "G-22"
    bad = await _save(client, accounts, one.gs_id, slip, cn_no="CN-9", cn_date=TODAY, cn_value="0")
    assert bad.status_code == 422
    ok = await _save(
        client, accounts, one.gs_id, slip, cn_no="cn-p11-1", cn_date=TODAY, cn_value="1250.50"
    )
    assert ok.status_code == 200, ok.text
    done = await _complete(client, accounts, one.gs_id, slip)
    assert done.status_code == 200, done.text
    body = done.json()
    # Nothing ships: no Dispatch Slip; the pieces are settled at completion, GS to closure.
    assert body["dispatch_slip"] is None
    assert body["gs_status"] not in {"ACCOUNTS_PENDING", "DISPATCH_PENDING"}
    assert _stock_by_location(db_conn, one.gs_id) == {"CREDITED": 3, "REJECTED_HOLD": 1}

    # GS 2: one condition Issue CN, the other Dispatch New → Challan and CN both required.
    two = await _analysed(client, storage, actors, masters, routing_products, rm, stores)
    dtm = _mitem((await _gs(client, mgmt, two.gs_id)).json(), "DT")
    assert (
        await _changes(client, mgmt, two.gs_id, [_change(dtm, 0, "credit note", ISSUE_CN=2)])
    ).status_code == 200
    assert (await _approve(client, mgmt, two.gs_id)).status_code == 200
    state = (await _entry(client, accounts, two.gs_id)).json()
    assert (state["gs_entry"]["requires_challan"], state["gs_entry"]["requires_cn"]) == (True, True)
    slip = state["ac_action_slip_id"]
    # DEC-22: the CN No. of GS 1 (case-insensitive) is refused on GS 2.
    dup = await _save(
        client,
        accounts,
        two.gs_id,
        slip,
        challan_no="CH-2",
        challan_date=TODAY,
        cn_no=" CN-P11-1 ",
        cn_date=TODAY,
        cn_value="10",
    )
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "VOUCHER_NUMBER_TAKEN"
    half = await _save(client, accounts, two.gs_id, slip, challan_no="CH-2", challan_date=TODAY)
    assert half.status_code == 200 and half.json()["can_complete"] is False
    full = await _save(
        client,
        accounts,
        two.gs_id,
        slip,
        challan_no="CH-2",
        challan_date=TODAY,
        cn_no="CN-P11-2",
        cn_date=TODAY,
        cn_value="99",
    )
    assert full.status_code == 200 and full.json()["can_complete"] is True
    res = await _complete(client, accounts, two.gs_id, slip)
    assert res.status_code == 200, res.text
    assert res.json()["gs_status"] == "DISPATCH_PENDING"
    content = (
        as_admin(db_conn)
        .execute(
            text("select content from public.dispatch_slips where gs_id = :g"), {"g": two.gs_id}
        )
        .scalar_one()
    )
    assert (content["challan_no"], content["cn_no"], content["cn_value"]) == (
        "CH-2",
        "CN-P11-2",
        "99.00",
    )
    assert content["management_stamp"].startswith("Digitally approved by Management")


# --- all Not Allowed → hold (Q21); Management change reopens it ---------------------------------
async def test_all_not_allowed_stays_on_hold(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    routing_products: dict[str, str],
    rm: str,
    mgmt: str,
    stores: StoreUsers,
    accounts: str,
    db_conn: Connection,
) -> None:
    r = await _ready(client, storage, actors, masters, routing_products, rm, stores)
    await _dt_submit(client, stores, r, a={"NOT_ALLOWED": 2}, b={"NOT_ALLOWED": 1})
    done = await _op_submit(client, stores, r, NOT_ALLOWED=1)
    assert done["status"] == "NOT_ALLOWED_HOLD"
    assert _slips(db_conn, r.gs_id) == []
    queue = (await client.get(f"{AC}/queue?status=all", headers=_auth(accounts))).json()
    assert r.gs_id not in _queue_ids(queue)
    hold = (await client.get(f"{AC}/hold", headers=_auth(accounts))).json()
    row = next(h for h in hold if h["gs_id"] == r.gs_id)
    assert (row["gs_status"], row["total_qty"]) == ("NOT_ALLOWED_HOLD", 4)
    # No stock moves on hold; the store keeps the pieces.
    assert _stock_by_location(db_conn, r.gs_id) == {"ISTORE_DT": 3, "ISTORE_OP": 1}

    # Management may change it: the change reopens the GS, the approval sends it to Accounts.
    view = (await _gs(client, mgmt, r.gs_id)).json()
    assert view["can_edit"] is True and "on hold" in view["reopen_notice"]
    assert view["can_approve"] is False
    res = await _changes(
        client, mgmt, r.gs_id, [_change(_mitem(view, "OP"), 0, "repairable", SEND_REPAIRED=1)]
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "ANALYSIS_COMPLETED"
    ok = await _approve(client, mgmt, r.gs_id)
    assert ok.status_code == 200 and ok.json()["status"] == "ACCOUNTS_PENDING"
    assert _slips(db_conn, r.gs_id) == [(1, "CURRENT")]


# --- DB guards (non-bypassable) -----------------------------------------------------------------
async def test_db_refuses_accounts_bypass(
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
    await _dt_submit(client, stores, r, a={"SEND_NEW": 2}, b={"NOT_ALLOWED": 1})
    c = as_admin(db_conn)

    def status(to: str) -> None:
        c.execute(
            text("update public.goods_slips set status = :s where id = :g"), {"s": to, "g": r.gs_id}
        )

    # A store still pending: no Accounts, no hold.
    for to in ("ACCOUNTS_PENDING", "NOT_ALLOWED_HOLD", "DISPATCH_PENDING"):
        with pytest.raises(DBAPIError, match="G-03"), c.begin_nested():
            status(to)

    await _op_submit(client, stores, r, SEND_REPAIRED=1)
    assert _status(db_conn, r.gs_id) == "ACCOUNTS_PENDING"
    entry = c.execute(
        text(
            "select e.id, e.ac_action_slip_id from public.ac_gs_entries e"
            " join public.ac_action_slips s on s.id = e.ac_action_slip_id"
            " where e.gs_id = :g and s.status = 'CURRENT'"
        ),
        {"g": r.gs_id},
    ).one()

    def entry_set(sql: str) -> None:
        c.execute(text(f"update public.ac_gs_entries set {sql} where id = :i"), {"i": entry[0]})  # noqa: S608

    # Hidden fields refused (no Issue CN), future dates refused, never deleted.
    with pytest.raises(DBAPIError, match=r"no Issue CN|cn_only_if_required"), c.begin_nested():
        entry_set("cn_no = 'X', cn_date = current_date, cn_value = 1")
    with pytest.raises(DBAPIError, match="future"), c.begin_nested():
        entry_set("challan_no = 'X', challan_date = current_date + 3")
    with pytest.raises(DBAPIError, match="never deleted"), c.begin_nested():
        c.execute(text("delete from public.ac_gs_entries where id = :i"), {"i": entry[0]})
    # Completion without the Challan refused; leaving Accounts before completion refused.
    with pytest.raises(DBAPIError, match="still needs its Challan"), c.begin_nested():
        c.execute(
            text(
                "insert into public.ac_entry_completions (gs_id, ac_action_slip_id, completed_by)"
                " values (:g, :s, :u)"
            ),
            {"g": r.gs_id, "s": entry[1], "u": actors.rm_id},
        )
    with pytest.raises(DBAPIError, match="must complete the Replacement Slip"), c.begin_nested():
        status("IN_PROCESS")
    # Reopen (back to analysis) only after the Replacement Slip is withdrawn.
    with pytest.raises(DBAPIError, match="must be withdrawn"), c.begin_nested():
        status("ANALYSIS_COMPLETED")
    # A goods slip at Accounts keeps a CURRENT Replacement Slip (checked at commit).
    with pytest.raises(DBAPIError, match="CURRENT Replacement Slip"), c.begin_nested():
        c.execute(
            text(
                "update public.ac_action_slips set status = 'SUPERSEDED', superseded_at = now(),"
                " superseded_by = :u, supersede_reason = 'bypass' where id = :s"
            ),
            {"s": entry[1], "u": actors.rm_id},
        )
        c.execute(text("set constraints all immediate"))
    assert _status(db_conn, r.gs_id) == "ACCOUNTS_PENDING"


# --- Q36 with the gate: the last store submits and sends for approval in one step ---------------
async def test_last_store_submits_with_a_management_request(
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
    await _dt_submit(client, stores, r, a={"SEND_NEW": 2}, b={"SEND_NEW": 1})
    await _op_back(client, stores, r)
    op = _item((await _state(client, stores.op, r.gs_id)).json(), "OP")
    res = await client.post(
        f"/api/v1/store-analysis/gs/{r.gs_id}/submit",
        json={
            "store_id": r.op_store,
            "lines": [_decide(op, 0, SEND_REPAIRED=1)],
            "management_lines": [
                {
                    "gs_item_id": op["gs_item_id"],
                    "condition_field_id": op["groups"][0]["condition_field_id"],
                    "from_action_code": "SEND_REPAIRED",
                    "proposed_action_code": "ISSUE_CN",
                    "qty": 1,
                }
            ],
            "management_approval_reason": "Party wants a credit note instead",
        },
        headers=_auth(stores.op, key()),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    # The request is recorded before the gate: the GS waits for Management, no Replacement Slip.
    assert body["status"] == "ANALYSIS_COMPLETED"
    assert body["open_approval_request"]["reason"].endswith(
        "Note: Party wants a credit note instead"
    )
    assert body["request_lines"][0]["proposed_action_code"] == "ISSUE_CN"
    assert _slips(db_conn, r.gs_id) == []
