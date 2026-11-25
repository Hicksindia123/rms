"""Phase P10 (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-70 (Q17 CONFIRMED, Q18 PROVISIONAL).

Once every Intermediate Store submitted its analysis (ANALYSIS_COMPLETED), Management changes any
decision of an item + condition to any other (incl. ISSUE_CN and back; reason per change; G-21
totals) and approves: the DB stores an append-only e-approval with the SHA-256 of the canonical
snapshot of the GS lines + decisions. Any later change makes it CHANGED (new approval needed).
Verify recomputes the hash. Accounts gate (Q18): no open request, Issue CN only with a VALID
approval, no unapproved Management change (service + DB). Only Management / Super Admin sets
ISSUE_CN.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import JwtFactory
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
from tests.integration.test_gate_inward import Masters, _auth
from tests.integration.test_itemization import key
from tests.integration.test_unboxing import FakeStorage

pytestmark = pytest.mark.gate_v4

# fixtures re-used from the P5 / P7 tests
__all__ = ["dec59", "mgmt", "products", "rm", "routing_products", "stores"]

BASE = "/api/v1/management-approval"


async def _analysed(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: dict[str, str],
    rm: str,
    st: StoreUsers,
    *,
    request: bool = True,
) -> Ready:
    """DT (3 pcs: 2 + 1 per condition) and OP (1 pc) analysed; DT sent it for approval."""
    r = await _ready(client, storage, actors, masters, products, rm, st)
    dt = _item((await _state(client, st.dt, r.gs_id)).json(), "DT")
    res = await _submit(
        client, st.dt, r.gs_id, r.dt_store, [_decide(dt, 0, SEND_NEW=2), _decide(dt, 1, SEND_NEW=1)]
    )
    assert res.status_code == 200, res.text
    if request:
        res = await client.post(
            f"/api/v1/store-analysis/gs/{r.gs_id}/management-approval",
            json=_send_body(dt, "Party asks for a credit note"),
            headers=_auth(st.dt, key()),
        )
        assert res.status_code == 200, res.text
    await _op_back(client, st, r)
    op = _item((await _state(client, st.op, r.gs_id)).json(), "OP")
    res = await _submit(client, st.op, r.gs_id, r.op_store, [_decide(op, 0, NOT_ALLOWED=1)])
    assert res.status_code == 200, res.text
    # DEC-71 (P11): without an open request the gate passes and the GS goes on to Accounts.
    assert res.json()["status"] == ("ANALYSIS_COMPLETED" if request else "ACCOUNTS_PENDING")
    return r


def _send_body(dt: dict[str, Any], reason: str) -> dict[str, Any]:
    """DEC-75: DT sends 1 of its "Send New" pieces (first condition) to Management for Issue CN."""
    g = dt["groups"][0]
    return {
        "lines": [
            {
                "gs_item_id": dt["gs_item_id"],
                "condition_field_id": g["condition_field_id"],
                "from_action_code": "SEND_NEW",
                "proposed_action_code": "ISSUE_CN",
                "qty": 1,
            }
        ],
        "reason": reason,
    }


async def _gs(client: AsyncClient, token: str, gs_id: str) -> Any:
    return await client.get(f"{BASE}/gs/{gs_id}", headers=_auth(token))


def _change(item: dict[str, Any], group: int, reason: str, **qty: int) -> dict[str, Any]:
    g = item["groups"][group]
    return {
        "gs_item_id": item["gs_item_id"],
        "condition_field_id": g["condition_field_id"],
        "decisions": [{"action_code": c, "qty": q} for c, q in qty.items()],
        "reason": reason,
    }


def _mitem(view: dict[str, Any], store: str) -> dict[str, Any]:
    return next(i for i in view["items"] if i["store_code"] == store)


async def _changes(
    client: AsyncClient,
    token: str,
    gs_id: str,
    changes: list[dict[str, Any]],
    idem: str | None = None,
) -> Any:
    return await client.post(
        f"{BASE}/gs/{gs_id}/changes",
        json={"changes": changes},
        headers=_auth(token, idem or key()),
    )


async def _approve(client: AsyncClient, token: str, gs_id: str, idem: str | None = None) -> Any:
    return await client.post(
        f"{BASE}/gs/{gs_id}/approve", json={"remarks": "ok"}, headers=_auth(token, idem or key())
    )


def _actions(conn: Connection, gs_id: str) -> list[tuple[str, str]]:
    rows = fetch_all(
        conn,
        """select s.code as store, a.action_code, a.qty
             from public.rm_item_actions a join public.gs_items gi on gi.id = a.gs_item_id
             join public.intermediate_stores s on s.id = rms_private.gs_item_store(gi.id)
            where gi.gs_id = :g and a.is_current
            order by 1, 2, 3""",
        g=gs_id,
    )
    return [(r["store"], f"{r['action_code']}:{r['qty']}") for r in rows]


def _slips(conn: Connection, gs_id: str) -> list[tuple[int, str]]:
    rows = fetch_all(
        as_admin(conn),
        "select version_no, status from public.ac_action_slips where gs_id = :g order by 1",
        g=gs_id,
    )
    return [(r["version_no"], r["status"]) for r in rows]


# --- happy path: any-to-any, approve, verify, change after approval invalidates -----------------
async def test_management_changes_approves_and_verifies(
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
    # Before every store submitted: Management sees the GS but cannot change it.
    dt = _item((await _state(client, stores.dt, r.gs_id)).json(), "DT")
    await _submit(
        client,
        stores.dt,
        r.gs_id,
        r.dt_store,
        [_decide(dt, 0, SEND_NEW=2), _decide(dt, 1, SEND_NEW=1)],
    )
    sent = await client.post(
        f"/api/v1/store-analysis/gs/{r.gs_id}/management-approval",
        json=_send_body(dt, "Party asks for a credit note"),
        headers=_auth(stores.dt, key()),
    )
    assert sent.status_code == 200, sent.text
    early = (await _gs(client, mgmt, r.gs_id)).json()
    assert early["can_edit"] is False and "OP" in early["blocked_reason"]
    assert early["open_request"]["reason"].endswith("Note: Party asks for a credit note")
    assert early["requested_qty"] == 1
    blocked = await _changes(
        client, mgmt, r.gs_id, [_change(_mitem(early, "DT"), 0, "credit", ISSUE_CN=2)]
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "INVALID_GS_STATUS"
    # The request is in Management's queue and My Work already.
    queue = (await client.get(f"{BASE}/queue", headers=_auth(mgmt))).json()
    row = next(q for q in queue if q["gs_id"] == r.gs_id)
    assert row["request_reason"].endswith("Note: Party asks for a credit note")
    assert (row["requested_qty"], row["waiting_store_codes"]) == (1, ["OP"])
    work = (await client.get("/api/v1/me/journey/MANAGEMENT_APPROVAL", headers=_auth(mgmt))).json()
    assert r.gs_id in {i["gs_id"] for i in work["items"]}

    await _op_back(client, stores, r)
    op = _item((await _state(client, stores.op, r.gs_id)).json(), "OP")
    done = await _submit(client, stores.op, r.gs_id, r.op_store, [_decide(op, 0, NOT_ALLOWED=1)])
    assert done.json()["status"] == "ANALYSIS_COMPLETED"

    view = (await _gs(client, mgmt, r.gs_id)).json()
    assert view["can_edit"] and view["can_approve"] and view["blocked_reason"] is None
    codes = {o["code"] for o in _mitem(view, "DT")["options"]}
    assert "ISSUE_CN" in codes and "PENDING_BP" not in codes
    assert view["stamp"]["state"] == "NONE"
    assert view["accounts_gate"] == {
        "passes": False,
        "problem": "DEC-70: the goods slip waits for Management approval (sent by a store)",
    }
    # GS search: by GS no.
    found = await client.get(f"{BASE}/queue", params={"q": view["gs_no"]}, headers=_auth(mgmt))
    assert [q["gs_id"] for q in found.json()] == [r.gs_id]

    # Any-to-any: DT condition 1 → 1 new + 1 Issue CN (a line added), OP Not Allowed → Repaired.
    dtm, opm = _mitem(view, "DT"), _mitem(view, "OP")
    stock_before = _stock_by_location(db_conn, r.gs_id)
    changes = [
        _change(dtm, 0, "Party credit for one piece", SEND_NEW=1, ISSUE_CN=1),
        _change(opm, 0, "Repairable after all", SEND_REPAIRED=1),
    ]
    idem = key()
    res = await _changes(client, mgmt, r.gs_id, changes, idem)
    assert res.status_code == 200, res.text
    replay = await _changes(client, mgmt, r.gs_id, changes, idem)
    assert replay.headers.get("Idempotency-Replayed") == "true" and replay.json() == res.json()
    body = res.json()
    assert _actions(db_conn, r.gs_id) == [
        ("DT", "ISSUE_CN:1"),
        ("DT", "SEND_NEW:1"),
        ("DT", "SEND_NEW:1"),
        ("OP", "SEND_REPAIRED:1"),
    ]
    rev = body["revisions"][0]
    assert rev["made_by_name"] == "Mgmt" and len(rev["changes"]) == 2
    first = next(c for c in rev["changes"] if c["reason"] == "Party credit for one piece")
    assert [(d["action_code"], d["qty"]) for d in first["before"]] == [("SEND_NEW", 2)]
    assert sorted((d["action_code"], d["qty"]) for d in first["after"]) == [
        ("ISSUE_CN", 1),
        ("SEND_NEW", 1),
    ]
    # No stock moves (DEC-69: settled by Accounts / dispatch, P11).
    assert _stock_by_location(db_conn, r.gs_id) == stock_before

    # Approve: DB snapshot + SHA-256; the request is resolved; the gate passes.
    ok = await _approve(client, mgmt, r.gs_id)
    assert ok.status_code == 200, ok.text
    approved = ok.json()
    appr = approved["approvals"][0]
    assert (appr["approval_no"], appr["has_issue_cn"], appr["approver_role"]) == (
        1,
        True,
        "Management",
    )
    snap = (
        as_admin(db_conn)
        .execute(
            text("select snapshot::text from public.gs_management_approvals where id = :i"),
            {"i": appr["id"]},
        )
        .scalar_one()
    )
    assert hashlib.sha256(snap.encode()).hexdigest() == appr["snapshot_sha256"]
    assert appr["short_ref"] == appr["snapshot_sha256"][:12]
    stamp = approved["stamp"]
    assert stamp["state"] == "VALID"
    assert stamp["stamp_text"].startswith("Digitally approved by Management — Mgmt, ")
    assert stamp["stamp_text"].endswith(f"ref {appr['short_ref']}")
    assert approved["open_request"] is None
    assert approved["requests"][0]["status"] == "RESOLVED"
    assert approved["requests"][0]["approval_id"] == appr["id"]
    assert approved["accounts_gate"] == {"passes": True, "problem": None}
    events = fetch_all(
        as_admin(db_conn),
        "select event_type from public.notification_events where gs_id = :g"
        " and event_type = 'GS_MANAGEMENT_APPROVED'",
        g=r.gs_id,
    )
    assert len(events) == 1
    # DEC-71 (P11): the approval routed the GS to Accounts with Replacement Slip v1.
    assert _status(db_conn, r.gs_id) == "ACCOUNTS_PENDING"
    assert _slips(db_conn, r.gs_id) == [(1, "CURRENT")]
    again = await _approve(client, mgmt, r.gs_id)
    assert again.status_code == 409 and again.json()["error"]["code"] == "INVALID_GS_STATUS"

    # Verify (any GS viewer, e.g. the store user): VALID, integrity intact.
    ver = (await client.get(f"{BASE}/gs/{r.gs_id}/verify", headers=_auth(stores.dt))).json()
    assert (ver["result"], ver["integrity_ok"]) == ("VALID", True)
    assert ver["stored_sha256"] == ver["current_sha256"] == appr["snapshot_sha256"]
    store_stamp = await client.get(f"{BASE}/gs/{r.gs_id}/stamp", headers=_auth(stores.dt))
    assert store_stamp.status_code == 200 and store_stamp.json()["state"] == "VALID"

    # Back from Issue CN (the GS is at Accounts): the change withdraws the Replacement Slip and
    # reopens the GS (DEC-71); the approval is CHANGED; the gate needs a new approval.
    res = await _changes(
        client, mgmt, r.gs_id, [_change(dtm, 0, "Party withdrew the CN request", SEND_NEW=2)]
    )
    assert res.status_code == 200, res.text
    changed = res.json()
    assert changed["stamp"]["state"] == "CHANGED" and changed["stamp"]["stamp_text"] is None
    assert changed["accounts_gate"]["passes"] is False
    assert "changed after its Management approval" in changed["accounts_gate"]["problem"]
    assert changed["status"] == "ANALYSIS_COMPLETED"
    assert _slips(db_conn, r.gs_id) == [(1, "SUPERSEDED")]
    ver = (await client.get(f"{BASE}/gs/{r.gs_id}/verify", headers=_auth(mgmt))).json()
    assert (ver["result"], ver["integrity_ok"]) == ("CHANGED", True)
    assert ver["stored_sha256"] != ver["current_sha256"]
    re = await _approve(client, mgmt, r.gs_id)
    assert re.status_code == 200, re.text
    assert re.json()["approvals"][0]["approval_no"] == 2
    assert re.json()["approvals"][0]["has_issue_cn"] is False
    assert re.json()["stamp"]["state"] == "VALID"
    # The new approval routes it again: Replacement Slip v2 (same number).
    assert _status(db_conn, r.gs_id) == "ACCOUNTS_PENDING"
    assert _slips(db_conn, r.gs_id) == [(1, "SUPERSEDED"), (2, "CURRENT")]


# --- guards (service) ---------------------------------------------------------------------------
async def test_management_change_guards(
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
    r = await _analysed(
        client, storage, actors, masters, routing_products, rm, stores, request=False
    )
    view = (await _gs(client, mgmt, r.gs_id)).json()
    dtm = _mitem(view, "DT")
    ok = _change(dtm, 0, "credit", ISSUE_CN=2)

    # Only Management changes and approves (store users, the RM: no management_approval).
    for token in (stores.dt, rm):
        assert (await _changes(client, token, r.gs_id, [ok])).status_code == 403
        assert (await _approve(client, token, r.gs_id)).status_code == 403
        assert (await _gs(client, token, r.gs_id)).status_code == 403

    async def refused(changes: list[dict[str, Any]]) -> tuple[int, str]:
        res = await _changes(client, mgmt, r.gs_id, changes)
        return res.status_code, res.json()["error"]["code"]

    # G-21: the item + condition still totals its pieces.
    assert await refused([_change(dtm, 0, "credit", ISSUE_CN=1)]) == (409, "G-21")
    assert await refused([_change(dtm, 0, "credit", ISSUE_CN=3)]) == (409, "G-21")
    # Pending is not used on the store flow (DEC-69).
    assert await refused([_change(dtm, 0, "credit", PENDING_BP=2)]) == (409, "G-21")
    # A reason per change; unchanged / duplicate lines refused.
    assert (await refused([_change(dtm, 0, "  ", ISSUE_CN=2)]))[0] == 422
    assert await refused([_change(dtm, 0, "same", SEND_NEW=2)]) == (422, "NO_CHANGES")
    assert await refused([ok, ok]) == (422, "DUPLICATE_LINE")
    # Nothing was written (the GS is still at Accounts, DEC-71: a refused change reopens nothing).
    assert (
        fetch_all(
            as_admin(db_conn),
            "select 1 from public.gs_management_revisions where gs_id = :g",
            g=r.gs_id,
        )
        == []
    )
    assert _status(db_conn, r.gs_id) == "ACCOUNTS_PENDING"
    assert _slips(db_conn, r.gs_id) == [(1, "CURRENT")]
    # Approval is for analysed goods slips; this one already passed the gate.
    late = await _approve(client, mgmt, r.gs_id)
    assert late.status_code == 409 and late.json()["error"]["code"] == "INVALID_GS_STATUS"


# --- DB guards (non-bypassable) -----------------------------------------------------------------
async def test_db_refuses_management_bypass(
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
    r = await _analysed(client, storage, actors, masters, routing_products, rm, stores)
    mgmt_id = users.create(roles=["MANAGEMENT"], full_name="DB Mgmt")
    view = (await _gs(client, make_token(mgmt_id), r.gs_id)).json()
    dtm = _mitem(view, "DT")
    item, cond = dtm["gs_item_id"], dtm["groups"][0]["condition_field_id"]
    c = as_admin(db_conn)

    def retire() -> None:
        c.execute(
            text(
                "update public.rm_item_actions set is_current = false"
                " where gs_item_id = :i and condition_field_id = :c and is_current"
            ),
            {"i": item, "c": cond},
        )

    def action(code: str, qty: int, reason: str | None) -> None:
        c.execute(
            text(
                "insert into public.rm_item_actions"
                " (gs_item_id, revision_no, round_no, condition_field_id, action_code, qty, reason)"
                " values (:i, 99, 1, :c, :a, :q, :r)"
            ),
            {"i": item, "c": cond, "a": code, "q": qty, "r": reason},
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

    def to_accounts() -> None:
        c.execute(
            text("update public.goods_slips set status = 'IN_PROCESS' where id = :g"),
            {"g": r.gs_id},
        )

    # After the analysis a store user (or the RM) can neither retire nor set Issue CN.
    for actor in (stores.dt_id, actors.rm_id):
        users.set_actor(actor)
        with (
            pytest.raises(DBAPIError, match="DEC-70: after the analysis only Management"),
            c.begin_nested(),
        ):
            action("ISSUE_CN", 2, "credit")
        with (
            pytest.raises(DBAPIError, match="DEC-70: after the analysis only Management"),
            c.begin_nested(),
        ):
            retire()
        with pytest.raises(DBAPIError, match="DEC-70: only Management approves"), c.begin_nested():
            approval()

    users.set_actor(mgmt_id)
    with c.begin_nested():
        retire()
        with pytest.raises(DBAPIError, match="carries a reason"), c.begin_nested():
            action("ISSUE_CN", 2, None)
        action("ISSUE_CN", 2, "credit note for the party")
        # Q18: the open request and the unapproved Issue CN keep the GS from Accounts.
        with pytest.raises(DBAPIError, match="waits for Management approval"), c.begin_nested():
            to_accounts()
        approval()
        snap = c.execute(
            text(
                "select snapshot_sha256, rms_private.management_snapshot_sha256(snapshot),"
                " has_issue_cn, approver_name_snapshot from public.gs_management_approvals"
                " where gs_id = :g"
            ),
            {"g": r.gs_id},
        ).one()
        # The DB replaced the caller's placeholders with the real snapshot + hash.
        assert snap[0] == snap[1] and snap[0] != "0" * 64 and snap[2] is True
        assert snap[3] == "DB Mgmt"
        assert (
            c.execute(
                text("select rms_private.gs_management_approval_state(:g)"), {"g": r.gs_id}
            ).scalar_one()
            == "VALID"
        )
        # Append-only.
        with pytest.raises(DBAPIError, match="immutable"), c.begin_nested():
            c.execute(
                text("update public.gs_management_approvals set remarks = 'x' where gs_id = :g"),
                {"g": r.gs_id},
            )
        with pytest.raises(DBAPIError, match="immutable"), c.begin_nested():
            c.execute(
                text("delete from public.gs_management_approvals where gs_id = :g"), {"g": r.gs_id}
            )
        # With a valid approval the Management gate passes (P11 adds the Accounts exit itself).
        with (
            pytest.raises(DBAPIError, match="ANALYSIS_COMPLETED goes to Accounts"),
            c.begin_nested(),
        ):
            to_accounts()
        # A later change invalidates it; Issue CN without a valid approval is blocked again.
        retire()
        action("ISSUE_CN", 1, "one piece only")
        action("SEND_NEW", 1, "one piece only")
        assert (
            c.execute(
                text("select rms_private.gs_management_approval_state(:g)"), {"g": r.gs_id}
            ).scalar_one()
            == "CHANGED"
        )
        with (
            pytest.raises(DBAPIError, match=r"DEC-70 \(Q18\): the goods slip has Issue CN"),
            c.begin_nested(),
        ):
            to_accounts()
    users.set_actor(None)
    assert _status(db_conn, r.gs_id) == "ANALYSIS_COMPLETED"
