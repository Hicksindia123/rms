"""Integration tests for gap plan 2026-11-17 Phase G4 — final actions per condition (DEC-57;
Q9-Q12; G-15, G-20, G-21, G-22).

1. Final actions are split per item + current condition (DEC-56); the G-21 total holds per
   condition; the A/c Actions slip and the Accounts lines carry the condition.
2. Where the pieces go when a round settles: Send New's old piece -> Non-Functional Store, Not
   Allowed -> Rejected Hold (accounted by the closure checklist), Pending -> Pending Hold.
3. Pending pieces keep the goods slip open; the RM re-actions them in a follow-up round with its own
   A/c Actions slip, Accounts entry and settlement (user decision 2026-11-18), only after the
   previous round is completed and dispatched. When nothing is Pending the closure engine moves on.
4. The DB guards reject the same violations directly (CLAUDE.md rule c).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import get_session_factory
from app.core.middleware import limiter
from app.modules.journeys import repository as journeys_repo
from app.shared.storage import get_storage
from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, build_test_app
from tests.integration.test_ac_entry_dispatch import TODAY, _balances, _gs_status
from tests.integration.test_department_routing import (
    _add_buckets,
    _seed_gs_held_at_intermediate_store,
)
from tests.integration.test_final_actions import PdfStorage
from tests.integration.test_gate_inward import _auth

pytestmark = pytest.mark.asyncio


@pytest.fixture
def storage() -> PdfStorage:
    return PdfStorage()


@pytest.fixture
async def client(
    session_factory: sessionmaker[Session], storage: PdfStorage
) -> AsyncIterator[AsyncClient]:
    app = build_test_app()
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_storage] = lambda: storage
    limiter.reset()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    limiter.reset()


@pytest.fixture
def actors(users: UserFactory, make_token: JwtFactory) -> dict[str, Any]:
    rm_id = users.create(roles=["REPLACEMENT_MANAGER"], full_name="Pratham")
    acc_id = users.create(roles=["ACCOUNTS"], full_name="Deepak")
    disp_id = users.create(roles=["DISPATCH"], full_name="Vikas")
    return {
        "rm": make_token(rm_id),
        "rm_id": str(rm_id),
        "accounts": make_token(acc_id),
        "dispatch": make_token(disp_id),
    }


def _key() -> str:
    return f"test-g4-{uuid.uuid4().hex}"


def _group(item_id: str, cond: str | None, **qty: int) -> dict[str, Any]:
    return {
        "gs_item_id": item_id,
        "condition_field_id": cond,
        "actions": [{"action_code": c, "qty": q} for c, q in qty.items()],
    }


async def _fa_state(client: AsyncClient, actors: dict[str, Any], gs_id: str) -> dict[str, Any]:
    res = await client.get(f"/api/v1/gs/{gs_id}/final-actions", headers=_auth(actors["rm"]))
    assert res.status_code == 200, res.text
    return dict(res.json())


async def _save(
    client: AsyncClient, actors: dict[str, Any], gs_id: str, lines: list[dict[str, Any]]
) -> Any:
    return await client.put(
        f"/api/v1/gs/{gs_id}/final-actions",
        headers=_auth(actors["rm"], _key()),
        json={"lines": lines},
    )


async def _finalise(client: AsyncClient, actors: dict[str, Any], gs_id: str) -> dict[str, Any]:
    res = await client.post(
        f"/api/v1/gs/{gs_id}/final-actions/finalise",
        headers=_auth(actors["rm"], _key()),
        json={},
    )
    assert res.status_code == 200, res.text
    return dict(res.json())


async def _ac_state(client: AsyncClient, actors: dict[str, Any], gs_id: str) -> dict[str, Any]:
    res = await client.get(f"/api/v1/ac-entry/gs/{gs_id}", headers=_auth(actors["accounts"]))
    assert res.status_code == 200, res.text
    return dict(res.json())


async def _ac_fill_and_complete(
    client: AsyncClient, actors: dict[str, Any], gs_id: str
) -> dict[str, Any]:
    state = await _ac_state(client, actors, gs_id)
    lines = []
    for ln in state["lines"]:
        body: dict[str, Any] = {"line_id": ln["id"]}
        if ln["requires_cn"]:
            body |= {"cn_no": f"CN-G4-{uuid.uuid4().hex[:6]}", "cn_date": TODAY, "cn_value": "99"}
        if ln["requires_challan"]:
            body |= {"challan_no": f"CH-{ln['action_code']}", "challan_date": TODAY}
        lines.append(body)
    if lines:
        saved = await client.put(
            f"/api/v1/ac-entry/gs/{gs_id}/lines",
            headers=_auth(actors["accounts"], _key()),
            json={"ac_action_slip_id": state["ac_action_slip_id"], "lines": lines},
        )
        assert saved.status_code == 200, saved.text
    done = await client.post(
        f"/api/v1/ac-entry/gs/{gs_id}/complete",
        headers=_auth(actors["accounts"], _key()),
        json={"ac_action_slip_id": state["ac_action_slip_id"]},
    )
    assert done.status_code == 200, done.text
    return dict(done.json())


async def _dispatch(client: AsyncClient, actors: dict[str, Any], dslip_id: str) -> None:
    res = await client.post(
        f"/api/v1/dispatch-slips/{dslip_id}/dispatch",
        headers=_auth(actors["dispatch"], _key()),
        json={"dispatch_date": TODAY, "transporter": "Blue Dart", "docket_no": "G4-1"},
    )
    assert res.status_code == 200, res.text


async def _checklist(client: AsyncClient, actors: dict[str, Any], gs_id: str) -> dict[str, Any]:
    res = await client.get(f"/api/v1/gs/{gs_id}/closure", headers=_auth(actors["rm"]))
    assert res.status_code == 200, res.text
    return {i["code"]: i for i in res.json()["items"]}


def _in_final_actions_queue(db_conn: Connection, gs_id: str) -> bool:
    """The FINAL_ACTIONS work-queue fragment (journeys) contains the goods slip."""
    sql = journeys_repo._QUEUES["FINAL_ACTIONS"]
    found = (
        as_admin(db_conn)
        .execute(
            text(f"select count(*) from ({sql}) q where q.gs_id = cast(:g as uuid)"),  # noqa: S608
            {"g": gs_id},
        )
        .scalar_one()
    )
    return bool(found)


def _fixture_with_split(db_conn: Connection) -> dict[str, Any]:
    """Held GS, one item of 10 pcs split 7 (condition A) + 3 (condition B)."""
    fx = _seed_gs_held_at_intermediate_store(db_conn)
    fx["cond_a"], fx["cond_b"] = _add_buckets(db_conn, fx["item_id"], {0: 7, 1: 3})
    return fx


# =================================================================================================


async def test_g4_actions_per_condition_and_g21_per_group(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    """DEC-57 Q9: groups per item + condition; G-21 per group; the condition is required."""
    fx = _fixture_with_split(db_conn)
    gs_id, item = fx["gs_id"], fx["item_id"]

    state = await _fa_state(client, actors, gs_id)
    assert state["round_no"] == 1
    groups = {g["condition_field_id"]: g for g in state["lines"][0]["groups"]}
    assert {k: g["available_qty"] for k, g in groups.items()} == {fx["cond_a"]: 7, fx["cond_b"]: 3}
    allowed = {a["code"]: a["label"] for a in state["lines"][0]["allowed_actions"]}
    assert allowed["PENDING_BP"] == "Pending"  # G4 relabel; code unchanged

    # An item with a split is actioned per condition (no "whole item" group).
    res = await _save(client, actors, gs_id, [_group(item, None, SEND_NEW=10)])
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "CONDITION_NOT_IN_ITEM"

    # Item total right (10) but condition A over-allocated: G-21 per condition.
    res = await _save(
        client,
        actors,
        gs_id,
        [_group(item, fx["cond_a"], SEND_NEW=8), _group(item, fx["cond_b"], SEND_NEW=2)],
    )
    assert res.status_code == 409, res.text
    assert "G-21" in res.json()["error"]["message"]

    res = await _save(
        client,
        actors,
        gs_id,
        [
            _group(item, fx["cond_a"], SEND_NEW=5, PENDING_BP=2),
            _group(item, fx["cond_b"], NOT_ALLOWED=2, PENDING_BP=1),
        ],
    )
    assert res.status_code == 200, res.text
    line = res.json()["lines"][0]
    assert line["is_balanced"] is True
    assert {a["action_code"]: a["qty"] for a in line["current_actions"]} == {
        "SEND_NEW": 5,
        "PENDING_BP": 3,
        "NOT_ALLOWED": 2,
    }

    fin = await _finalise(client, actors, gs_id)
    slip = fin["current_slip"]
    assert (slip["round_no"], slip["version_no"], slip["total_qty"]) == (1, 1, 10)
    content = (
        as_admin(db_conn)
        .execute(
            text("select content from public.ac_action_slips where id = cast(:s as uuid)"),
            {"s": slip["id"]},
        )
        .scalar_one()
    )
    labels = {(ln["condition_label"], ln["action_code"]): ln["qty"] for ln in content["lines"]}
    assert len(labels) == 4 and all(lbl for lbl, _ in labels)

    ac = await _ac_state(client, actors, gs_id)
    assert ac["round_no"] == 1
    assert all(ln["condition_label"] for ln in ac["lines"])
    assert sorted(ln["qty"] for ln in ac["lines"]) == [1, 2, 2, 5]


async def test_g4_pending_round_trip_keeps_gs_open_until_reactioned(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    """DEC-57 Q10-Q12: settlement destinations, Pending re-action rounds, closure."""
    fx = _fixture_with_split(db_conn)
    gs_id, item, a, b = fx["gs_id"], fx["item_id"], fx["cond_a"], fx["cond_b"]
    res = await _save(
        client,
        actors,
        gs_id,
        [
            _group(item, a, SEND_NEW=5, PENDING_BP=2),
            _group(item, b, NOT_ALLOWED=2, PENDING_BP=1),
        ],
    )
    assert res.status_code == 200, res.text
    await _finalise(client, actors, gs_id)

    # Round 1 Accounts: Send New ships -> Dispatch Slip; stock moves only at dispatch.
    done = await _ac_fill_and_complete(client, actors, gs_id)
    dslip = done["dispatch_slip"]
    assert dslip is not None and dslip["status"] == "READY"

    # Not settled yet: the re-action round waits for the dispatch.
    state = await _fa_state(client, actors, gs_id)
    assert (state["round_no"], state["waiting_for_previous_round"]) == (2, True)
    assert state["can_edit"] is False
    assert _in_final_actions_queue(db_conn, gs_id) is False
    early = await _save(client, actors, gs_id, [_group(item, a, ISSUE_CN=2)])
    assert early.status_code == 409, early.text
    assert early.json()["error"]["code"] in ("ROUND_NOT_SETTLED", "INVALID_GS_STATUS")

    await _dispatch(client, actors, dslip["id"])
    # Q12 old piece -> Non-Functional Store; Q11 Not Allowed -> Rejected Hold; Q10 -> Pending Hold.
    assert _balances(db_conn, gs_id) == {
        "NON_FUNCTIONAL_STORE": 5,
        "REJECTED_HOLD": 2,
        "PENDING_HOLD": 3,
    }
    assert _gs_status(db_conn, gs_id) == "IN_PROCESS"
    items = await _checklist(client, actors, gs_id)
    assert items["STOCK_ACCOUNTED"]["passed"] is True  # Rejected Hold via the A/c flow counts
    assert items["STOCK_NOT_IN_TRANSIT"]["passed"] is False  # Pending Hold
    assert items["NO_PENDING_REACTION"]["passed"] is False
    assert items["NO_PENDING_REACTION"]["details"]["pending_qty"] == 3

    # The GS is back in the RM's Final Actions queue (My Work) for the re-action.
    assert _in_final_actions_queue(db_conn, gs_id) is True

    # Round 2: only the Pending pieces, per condition.
    state = await _fa_state(client, actors, gs_id)
    assert (state["round_no"], state["pending_from_previous_round"]) == (2, 3)
    assert state["can_edit"] is True and state["is_finalised"] is False
    groups = {g["condition_field_id"]: g["available_qty"] for g in state["lines"][0]["groups"]}
    assert groups == {a: 2, b: 1}

    wrong = await _save(client, actors, gs_id, [_group(item, a, ISSUE_CN=1), _group(item, b)])
    assert wrong.status_code == 409 and "G-21" in wrong.json()["error"]["message"]
    res = await _save(
        client, actors, gs_id, [_group(item, a, ISSUE_CN=2), _group(item, b, PENDING_BP=1)]
    )
    assert res.status_code == 200, res.text
    fin2 = await _finalise(client, actors, gs_id)
    slip2 = fin2["current_slip"]
    assert (slip2["round_no"], slip2["version_no"], slip2["status"]) == (2, 2, "CURRENT")
    v1 = next(s for s in fin2["slips"] if s["version_no"] == 1)
    assert (v1["status"], v1["is_completed"]) == ("CURRENT", True)  # round 1 not superseded

    ac2 = await _ac_state(client, actors, gs_id)
    assert ac2["round_no"] == 2 and ac2["version_no"] == 2
    assert {ln["action_code"]: ln["qty"] for ln in ac2["lines"]} == {"ISSUE_CN": 2, "PENDING_BP": 1}
    done2 = await _ac_fill_and_complete(client, actors, gs_id)
    assert done2["dispatch_slip"] is None  # nothing ships: settles at completion
    assert _balances(db_conn, gs_id) == {
        "NON_FUNCTIONAL_STORE": 5,
        "REJECTED_HOLD": 2,
        "CREDITED": 2,
        "PENDING_HOLD": 1,
    }
    assert _gs_status(db_conn, gs_id) == "IN_PROCESS"  # 1 pc still Pending (Q10)

    # Round 3: the last Pending piece is Not Allowed -> Rejected Hold; the GS moves on.
    state = await _fa_state(client, actors, gs_id)
    assert state["round_no"] == 3
    res = await _save(client, actors, gs_id, [_group(item, b, NOT_ALLOWED=1)])
    assert res.status_code == 200, res.text
    await _finalise(client, actors, gs_id)
    await _ac_fill_and_complete(client, actors, gs_id)
    assert _balances(db_conn, gs_id) == {
        "NON_FUNCTIONAL_STORE": 5,
        "REJECTED_HOLD": 3,
        "CREDITED": 2,
    }
    items = await _checklist(client, actors, gs_id)
    for code in ("STOCK_NOT_IN_TRANSIT", "STOCK_ACCOUNTED", "NO_PENDING_REACTION"):
        assert items[code]["passed"] is True, items[code]
    assert items["AC_ENTRY_COMPLETE"]["passed"] is True
    # Round 2 entered a CN, so the prior party notification is what remains (BR-38).
    assert _gs_status(db_conn, gs_id) == "AWAITING_NOTIFICATION"

    final = await _fa_state(client, actors, gs_id)
    assert final["round_no"] == 3 and final["is_completed"] is True
    assert final["can_edit"] is False
    assert _in_final_actions_queue(db_conn, gs_id) is False


async def test_g4_db_guards_reject_direct_writes(
    client: AsyncClient, db_conn: Connection, actors: dict[str, Any]
) -> None:
    """CLAUDE.md rule c: the DB rejects what the service rejects (G-21, DEC-57)."""
    fx = _fixture_with_split(db_conn)
    admin = as_admin(db_conn)

    def insert(round_no: int, cond: str | None, code: str, qty: int) -> None:
        admin.execute(
            text(
                """
                insert into public.rm_item_actions
                  (gs_item_id, revision_no, round_no, condition_field_id, action_code, qty,
                   is_current, decided_by)
                values (cast(:i as uuid), 1, :r, cast(:c as uuid), :code, :q, true,
                        cast(:by as uuid))
                """
            ),
            {
                "i": fx["item_id"],
                "r": round_no,
                "c": cond,
                "code": code,
                "q": qty,
                "by": actors["rm_id"],
            },
        )

    def rejected(fn: Any, needle: str) -> None:
        sp = db_conn.begin_nested()
        with pytest.raises(DBAPIError) as exc:
            fn()
        sp.rollback()
        assert needle in str(exc.value), str(exc.value)

    # Item with a split: an action without a condition is rejected.
    rejected(lambda: insert(1, None, "SEND_NEW", 10), "names its condition")
    # A condition the item does not have.
    other = admin.execute(
        text(
            "select id::text from public.item_field_library where field_group = 'CATEGORISATION'"
            " and id not in (cast(:a as uuid), cast(:b as uuid)) limit 1"
        ),
        {"a": fx["cond_a"], "b": fx["cond_b"]},
    ).scalar_one()
    rejected(lambda: insert(1, other, "SEND_NEW", 1), "current condition split")
    # A re-action round before round 1 was completed / settled.
    rejected(lambda: insert(2, fx["cond_a"], "ISSUE_CN", 1), "G-21")

    # Per-condition G-21 in the split check: 8 + 2 matches the item total, not the conditions.
    sp = db_conn.begin_nested()
    insert(1, fx["cond_a"], "SEND_NEW", 8)
    insert(1, fx["cond_b"], "SEND_NEW", 2)
    with pytest.raises(DBAPIError) as exc:
        admin.execute(
            text("select rms_private.validate_final_action_split(cast(:g as uuid), false)"),
            {"g": fx["gs_id"]},
        )
    sp.rollback()
    assert "exceeds the qty available in that condition" in str(exc.value)

    # Snapshot: a valid row gets the condition code / label from the item's split (G-18).
    sp = db_conn.begin_nested()
    insert(1, fx["cond_a"], "SEND_NEW", 7)
    row = (
        admin.execute(
            text(
                "select condition_code, condition_label from public.rm_item_actions"
                " where gs_item_id = cast(:i as uuid) and is_current"
            ),
            {"i": fx["item_id"]},
        )
        .mappings()
        .one()
    )
    sp.rollback()
    assert row["condition_code"] and row["condition_label"]
