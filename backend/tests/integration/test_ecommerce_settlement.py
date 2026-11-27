"""E-Commerce settlement (DEC-76; user spec 2026-11-26): the E-Commerce Executive's portal
resolution, unboxing into a per-platform action sheet, stock, store acknowledgement, repair,
credit note by E-Commerce Accounts, closing, and the DB guards behind every step.

Uses the HTTP helpers of test_ecommerce_returns (FakeStorage uploads, Idempotency-Key headers).
The DB is the local Supabase Postgres, rolled back per test.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, fetch_all
from tests.integration.test_ecommerce_returns import (
    BASE,
    TICKETS,
    _h,
    _key,
    _payload,
    _submitted,
    client,  # noqa: F401 - fixture
    product,  # noqa: F401 - fixture
    storage,  # noqa: F401 - fixture
)
from tests.integration.test_unboxing import FakeStorage

SETTLE = "/api/v1/ecommerce-settlement"


@dataclass
class Team:
    gate: str
    gate_id: uuid.UUID
    exec: str
    exec_id: uuid.UUID
    unboxer: str
    unboxer_id: uuid.UUID
    store: str
    store_id: uuid.UUID
    other_store: str
    accounts: str
    accounts_id: uuid.UUID
    mgmt: str
    mgmt_id: uuid.UUID
    store_row: dict[str, Any]


@pytest.fixture
def team(
    users: UserFactory,
    make_token: JwtFactory,
    db_conn: Connection,
    product: dict[str, Any],  # noqa: F811 - fixture
) -> Team:
    store = fetch_all(
        as_admin(db_conn),
        """
        select s.id, s.name, s.location_id, r.code as role_code
          from public.intermediate_stores s join public.roles r on r.id = s.role_id
         where s.id = rms_private.store_for_product(cast(:pid as uuid))
        """,
        pid=str(product["id"]),
    )
    assert store, "the seed product has no Intermediate Store"
    other = fetch_all(
        as_admin(db_conn),
        """
        select r.code from public.intermediate_stores s join public.roles r on r.id = s.role_id
         where s.id <> cast(:sid as uuid) and s.is_active order by s.sort_order limit 1
        """,
        sid=str(store[0]["id"]),
    )
    ids = {
        "gate": users.create(roles=["ECOM_GATE"], full_name="Ecom Gate"),
        "exec": users.create(roles=["TICKET_HANDLER"], full_name="Ecom Executive"),
        "unboxer": users.create(roles=["INWARD_VERIFIER"], full_name="Unboxer"),
        "store": users.create(roles=[store[0]["role_code"]], full_name="Store User"),
        "other": users.create(roles=[other[0]["code"]], full_name="Other Store"),
        "accounts": users.create(roles=["ECOM_ACCOUNTS"], full_name="Ecom Accounts"),
        "mgmt": users.create(roles=["MANAGEMENT"], full_name="Mgmt"),
    }
    return Team(
        gate=make_token(ids["gate"]),
        gate_id=ids["gate"],
        exec=make_token(ids["exec"]),
        exec_id=ids["exec"],
        unboxer=make_token(ids["unboxer"]),
        unboxer_id=ids["unboxer"],
        store=make_token(ids["store"]),
        store_id=ids["store"],
        other_store=make_token(ids["other"]),
        accounts=make_token(ids["accounts"]),
        accounts_id=ids["accounts"],
        mgmt=make_token(ids["mgmt"]),
        mgmt_id=ids["mgmt"],
        store_row=store[0],
    )


async def _ticket_return(
    client: AsyncClient,  # noqa: F811
    storage: FakeStorage,  # noqa: F811
    team: Team,
    product: dict[str, Any] | None,  # noqa: F811
    resolution: dict[str, Any],
    **over: Any,
) -> dict[str, Any]:
    """Gate entry (ticket route) → raised → claim received → closed with the resolution."""
    body = await _submitted(client, storage, team.gate, _payload(product, **over))
    tid = body["ticket"]["id"]
    res = await client.post(f"{TICKETS}/{tid}/raise", headers=_h(team.exec, _key()))
    assert res.status_code == 200, res.text
    res = await client.post(
        f"{TICKETS}/{tid}/response",
        json={"response_code": "CLAIM_RECEIVED", "claim_amount": "250.00"},
        headers=_h(team.exec, _key()),
    )
    assert res.status_code == 200, res.text
    res = await client.post(
        f"{TICKETS}/{tid}/close", json=resolution, headers=_h(team.exec, _key())
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "PENDING_UNBOXING"
    return dict(res.json())


async def _portal_return(
    client: AsyncClient,  # noqa: F811
    storage: FakeStorage,  # noqa: F811
    team: Team,
    product: dict[str, Any] | None,  # noqa: F811
    resolution: dict[str, Any],
    **over: Any,
) -> dict[str, Any]:
    """Gate entry without a ticket → the executive's portal check."""
    body = await _submitted(
        client, storage, team.gate, _payload(product, qc_routing_code="ISSUE_TO_CHECKING", **over)
    )
    assert body["status"] == "IN_CHECKING"
    res = await client.post(
        f"{TICKETS}/portal-checks/{body['id']}", json=resolution, headers=_h(team.exec, _key())
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "PENDING_UNBOXING"
    return dict(res.json())


def _balance(conn: Connection, return_id: str, location_id: Any) -> int:
    rows = fetch_all(
        as_admin(conn),
        """
        select coalesce(sum(b.qty), 0) as qty
          from public.stock_balances b join public.stock_lots l on l.id = b.lot_id
         where l.ecommerce_return_id = cast(:rid as uuid) and b.location_id = cast(:loc as uuid)
        """,
        rid=return_id,
        loc=str(location_id),
    )
    return int(rows[0]["qty"])


def _commit_checks(conn: Connection) -> None:
    """Fire the deferred (commit-time) constraint triggers now: the test transaction is rolled
    back, so without this they would never run (DEC-73 ticket presence, DEC-76 unboxing
    completeness / non-empty sheet)."""
    conn.execute(text("set constraints all immediate"))
    conn.execute(text("set constraints all deferred"))


def _location(conn: Connection, code: str) -> Any:
    return fetch_all(
        as_admin(conn), "select id from public.inventory_locations where code = :c", c=code
    )[0]["id"]


# --- executive ---------------------------------------------------------------------------------
async def test_portal_check_and_follow_ups(
    client: AsyncClient,  # noqa: F811
    storage: FakeStorage,  # noqa: F811
    team: Team,
    product: dict[str, Any],  # noqa: F811
) -> None:
    body = await _submitted(
        client, storage, team.gate, _payload(product, qc_routing_code="ISSUE_TO_CHECKING")
    )
    queue = await client.get(f"{TICKETS}/portal-checks", headers=_h(team.exec))
    assert queue.status_code == 200
    assert {o["code"] for o in queue.json()["resolution_options"]} >= {"FREE_REPLACEMENT", "REFUND"}
    assert any(r["return_id"] == body["id"] for r in queue.json()["rows"])
    # Only the executive records it; the qty is at most the received qty.
    res = await client.post(
        f"{TICKETS}/portal-checks/{body['id']}",
        json={"resolution_code": "REFUND", "resolution_qty": 1},
        headers=_h(team.gate, _key()),
    )
    assert res.status_code == 403
    res = await client.post(
        f"{TICKETS}/portal-checks/{body['id']}",
        json={"resolution_code": "REFUND", "resolution_qty": 5},
        headers=_h(team.exec, _key()),
    )
    assert res.status_code == 422 and "resolution_qty" in res.json()["error"]["details"]
    res = await client.post(
        f"{TICKETS}/portal-checks/{body['id']}",
        json={"resolution_code": "FREE_REPLACEMENT", "resolution_qty": 2, "resolution_note": "FR"},
        headers=_h(team.exec, _key()),
    )
    assert res.status_code == 200, res.text
    assert res.json()["resolution_label"] == "Free Replacement"
    # Done once.
    res = await client.post(
        f"{TICKETS}/portal-checks/{body['id']}",
        json={"resolution_code": "REFUND", "resolution_qty": 1},
        headers=_h(team.exec, _key()),
    )
    assert res.status_code == 409

    # Follow-ups on a raised ticket.
    t = await _submitted(client, storage, team.gate, _payload(product, order_id="171-2222222-3"))
    tid = t["ticket"]["id"]
    res = await client.post(
        f"{TICKETS}/{tid}/follow-up", json={"note": "Chased"}, headers=_h(team.exec, _key())
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "ECOM_TICKET_NOT_RAISED"
    await client.post(f"{TICKETS}/{tid}/raise", headers=_h(team.exec, _key()))
    next_on = (date.today() + timedelta(days=2)).isoformat()
    res = await client.post(
        f"{TICKETS}/{tid}/follow-up",
        json={"note": "Called seller support", "next_follow_up_on": next_on},
        headers=_h(team.exec, _key()),
    )
    assert res.status_code == 200, res.text
    assert res.json()["ticket"]["follow_up_count"] == 1
    assert res.json()["ticket"]["next_follow_up_on"] == next_on
    assert res.json()["events"][-1]["event_code"] == "TICKET_FOLLOW_UP"
    res = await client.post(
        f"{TICKETS}/{tid}/follow-up",
        json={"note": "past date", "next_follow_up_on": "2020-01-01"},
        headers=_h(team.exec, _key()),
    )
    assert res.status_code == 422


# --- the whole flow ----------------------------------------------------------------------------
async def test_unboxing_sheet_store_repair_accounts_close(
    client: AsyncClient,  # noqa: F811
    storage: FakeStorage,  # noqa: F811
    team: Team,
    product: dict[str, Any],  # noqa: F811
    db_conn: Connection,
) -> None:
    refund = await _ticket_return(
        client,
        storage,
        team,
        product,
        {"resolution_code": "REFUND", "resolution_qty": 2},
        order_id="408-1111111-1111111",
        qty=3,
    )
    replace = await _portal_return(
        client,
        storage,
        team,
        product,
        {"resolution_code": "FREE_REPLACEMENT", "resolution_qty": 1},
        order_id="408-2222222-2222222",
        qty=1,
    )
    other = await _portal_return(
        client,
        storage,
        team,
        None,  # a different product: nothing is stocked
        {"resolution_code": "REFUND", "resolution_qty": 1},
        order_id="408-3333333-3333333",
        qty=1,
    )
    flip = await _portal_return(
        client,
        storage,
        team,
        product,
        {"resolution_code": "REFUND", "resolution_qty": 1},
        platform_code="FLIPKART",
        order_id="OD1234567890",
        qty=1,
    )

    queue = await client.get(f"{SETTLE}/unboxing", headers=_h(team.unboxer))
    assert queue.status_code == 200, queue.text
    q = queue.json()
    rows = {r["return_id"]: r for r in q["rows"]}
    assert {refund["id"], replace["id"], other["id"], flip["id"]} <= set(rows)
    assert rows[refund["id"]]["cn_qty"] == 2 and rows[replace["id"]]["cn_qty"] == 0
    assert rows[refund["id"]]["store_name"] == team.store_row["name"]
    assert rows[other["id"]]["is_company_product"] is False
    repair_loc = next(loc for loc in q["repair_locations"] if loc["code"] == "DEPT_REPACKAGING")
    assert {b["code"] for b in q["buckets"]} == {"TO_STORE", "TO_REPAIR", "WASTAGE"}

    good_lines = [
        {
            "return_id": refund["id"],
            "good_qty": 1,
            "repair_qty": 1,
            "wastage_qty": 1,
            "repair_location_id": repair_loc["id"],
            "note": "one dirty, one broken",
        },
        {"return_id": replace["id"], "good_qty": 1, "repair_qty": 0, "wastage_qty": 0},
        {"return_id": other["id"], "good_qty": 0, "repair_qty": 0, "wastage_qty": 1},
    ]

    # Permission, platform, totals, product and department rules.
    res = await client.post(
        f"{SETTLE}/unboxing",
        json={"platform_code": "AMAZON", "lines": good_lines},
        headers=_h(team.gate, _key()),
    )
    assert res.status_code == 403
    bad = [
        *good_lines,
        {"return_id": flip["id"], "good_qty": 1, "repair_qty": 0, "wastage_qty": 0},
    ]
    res = await client.post(
        f"{SETTLE}/unboxing",
        json={"platform_code": "AMAZON", "lines": bad},
        headers=_h(team.unboxer, _key()),
    )
    assert res.status_code == 422 and "lines.3.return_id" in res.json()["error"]["details"]
    res = await client.post(
        f"{SETTLE}/unboxing",
        json={
            "platform_code": "AMAZON",
            "lines": [
                {**good_lines[0], "wastage_qty": 0},
                {**good_lines[2], "good_qty": 1, "wastage_qty": 0},
                {**good_lines[1], "repair_qty": 0, "repair_location_id": repair_loc["id"]},
            ],
        },
        headers=_h(team.unboxer, _key()),
    )
    assert res.status_code == 422
    details = res.json()["error"]["details"]
    assert "lines.0.qty" in details and "lines.1.good_qty" in details
    assert "lines.2.repair_location_id" in details

    key = _key()
    res = await client.post(
        f"{SETTLE}/unboxing",
        json={"platform_code": "AMAZON", "lines": good_lines},
        headers=_h(team.unboxer, key),
    )
    assert res.status_code == 201, res.text
    sheet = res.json()
    assert sheet["sheet_no"].startswith("EAS/") and sheet["platform_label"] == "Amazon"
    assert sheet["status"] == "PENDING_ACCOUNTS"
    assert sheet["total_received"] == 5 and sheet["total_cn_qty"] == 3
    lines = {ln["return_id"]: ln for ln in sheet["lines"]}
    assert lines[refund["id"]]["cn_qty"] == 2 and lines[refund["id"]]["qty_received"] == 3
    assert lines[replace["id"]]["cn_qty"] == 0
    assert lines[other["id"]]["cn_qty"] == 1
    again = await client.post(
        f"{SETTLE}/unboxing",
        json={"platform_code": "AMAZON", "lines": good_lines},
        headers=_h(team.unboxer, key),
    )
    assert again.status_code == 201 and again.headers.get("Idempotency-Replayed") == "true"

    # Stock: good → receipt location, repair → department, wastage → wastage location.
    inward = _location(db_conn, "INWARD_STAGING")
    wastage = _location(db_conn, "REJECTED_HOLD")
    assert _balance(db_conn, refund["id"], inward) == 1
    assert _balance(db_conn, refund["id"], repair_loc["id"]) == 1
    assert _balance(db_conn, refund["id"], wastage) == 1
    assert _balance(db_conn, other["id"], wastage) == 0  # not our product: not stocked

    # An unboxed return is not voided.
    res = await client.post(
        f"{BASE}/{refund['id']}/void", json={"reason": "late"}, headers=_h(team.mgmt, _key())
    )
    assert res.status_code == 409

    # Store receipts: only the product's store acknowledges.
    rec = await client.get(f"{SETTLE}/store-receipts", headers=_h(team.store))
    assert rec.status_code == 200, rec.text
    mine = [r for r in rec.json()["rows"] if r["return_id"] in (refund["id"], replace["id"])]
    assert len(mine) == 2 and all(r["can_acknowledge"] for r in mine)
    ids = [r["id"] for r in mine]
    res = await client.post(
        f"{SETTLE}/store-receipts/acknowledge",
        json={"receipt_ids": ids},
        headers=_h(team.other_store, _key()),
    )
    assert res.status_code == 403
    res = await client.post(
        f"{SETTLE}/store-receipts/acknowledge",
        json={"receipt_ids": ids},
        headers=_h(team.store, _key()),
    )
    assert res.status_code == 200, res.text
    assert all(r["status"] == "ACKNOWLEDGED" for r in res.json()["rows"])
    store_loc = team.store_row["location_id"]
    assert _balance(db_conn, refund["id"], store_loc) == 1
    assert _balance(db_conn, refund["id"], inward) == 0
    assert _balance(db_conn, replace["id"], store_loc) == 1

    # Repair back: 1 sent → 1 ok (to the store after acknowledgement).
    queue = await client.get(f"{SETTLE}/unboxing", headers=_h(team.unboxer))
    repair = next(r for r in queue.json()["repairs"] if r["return_id"] == refund["id"])
    res = await client.post(
        f"{SETTLE}/repairs/{repair['repair_id']}/return",
        json={"qty_ok": 2, "qty_scrap": 0},
        headers=_h(team.unboxer, _key()),
    )
    assert res.status_code == 422
    res = await client.post(
        f"{SETTLE}/repairs/{repair['repair_id']}/return",
        json={"qty_ok": 1, "qty_scrap": 0, "note": "Repacked"},
        headers=_h(team.unboxer, _key()),
    )
    assert res.status_code == 200, res.text
    assert res.json()["repair"]["status"] == "RETURNED"

    # Accounts: CN required for Qty Issue CN > 0; only E-Commerce Accounts.
    sid = sheet["id"]
    res = await client.post(
        f"{SETTLE}/action-sheets/{sid}/complete", json={}, headers=_h(team.unboxer, _key())
    )
    assert res.status_code == 403
    res = await client.post(
        f"{SETTLE}/action-sheets/{sid}/complete", json={}, headers=_h(team.accounts, _key())
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "ECOM_CN_REQUIRED"
    future = (date.today() + timedelta(days=3)).isoformat()
    res = await client.post(
        f"{SETTLE}/action-sheets/{sid}/complete",
        json={"cn_no": "CN-77", "cn_date": future, "cn_value": "999.00"},
        headers=_h(team.accounts, _key()),
    )
    assert res.status_code == 422 and "cn_date" in res.json()["error"]["details"]
    res = await client.post(
        f"{SETTLE}/action-sheets/{sid}/complete",
        json={
            "cn_no": "CN-77",
            "cn_date": date.today().isoformat(),
            "cn_value": "999.00",
            "remarks": "Amazon refunds",
        },
        headers=_h(team.accounts, _key()),
    )
    assert res.status_code == 200, res.text
    done = res.json()
    assert done["status"] == "COMPLETED" and done["cn_no"] == "CN-77"

    # The different product (all wastage) and the free replacement (store acknowledged) are
    # settled; the refund still waits for the repaired piece.
    status = {ln["return_id"]: ln["status"] for ln in done["lines"]}
    assert status[other["id"]] == "CLOSED" and status[replace["id"]] == "CLOSED"
    assert status[refund["id"]] == "UNBOXED"

    rec = await client.get(f"{SETTLE}/store-receipts", headers=_h(team.store))
    repaired = [
        r for r in rec.json()["rows"] if r["return_id"] == refund["id"] and r["source"] == "REPAIR"
    ]
    assert len(repaired) == 1 and repaired[0]["qty"] == 1
    res = await client.post(
        f"{SETTLE}/store-receipts/acknowledge",
        json={"receipt_ids": [repaired[0]["id"]]},
        headers=_h(team.store, _key()),
    )
    assert res.status_code == 200, res.text
    assert _balance(db_conn, refund["id"], store_loc) == 2
    assert _balance(db_conn, refund["id"], repair_loc["id"]) == 0

    detail = await client.get(f"{BASE}/{refund['id']}", headers=_h(team.mgmt))
    d = detail.json()
    assert d["status"] == "CLOSED" and d["closed_at"]
    assert d["settlement"]["sheet_no"] == sheet["sheet_no"]
    assert d["settlement"]["cn_qty"] == 2 and d["settlement"]["repair"]["qty_ok"] == 1
    codes = [e["event_code"] for e in d["events"]]
    assert codes[-6:] == [
        "UNBOXED",
        "STORE_RECEIVED",
        "REPAIR_RETURNED",
        "CN_ISSUED",
        "STORE_RECEIVED",
        "CLOSED",
    ]

    # The sheet list shows it completed; a completed sheet is final.
    lst = await client.get(f"{SETTLE}/action-sheets", headers=_h(team.accounts))
    assert any(r["id"] == sid and r["status"] == "COMPLETED" for r in lst.json()["rows"])
    res = await client.post(
        f"{SETTLE}/action-sheets/{sid}/complete",
        json={"cn_no": "X", "cn_date": date.today().isoformat(), "cn_value": "1"},
        headers=_h(team.accounts, _key()),
    )
    assert res.status_code == 409

    _commit_checks(db_conn)

    # The stock ledger reconciles to the balances for these lots (IC-03).
    drift = fetch_all(
        as_admin(db_conn),
        """
        with mv as (
          select m.lot_id, loc, sum(q) as q from (
            select lot_id, to_location_id as loc, qty as q from public.stock_movements
             where to_location_id is not null
            union all
            select lot_id, from_location_id, -qty from public.stock_movements
             where from_location_id is not null) m(lot_id, loc, q)
          group by 1, 2)
        select count(*) as n
          from mv join public.stock_lots l on l.id = mv.lot_id
          left join public.stock_balances b on b.lot_id = mv.lot_id and b.location_id = mv.loc
         where l.ecommerce_return_id is not null and mv.q <> coalesce(b.qty, 0)
        """,
    )
    assert drift[0]["n"] == 0


async def test_free_replacement_sheet_completes_without_accounts(
    client: AsyncClient,  # noqa: F811
    storage: FakeStorage,  # noqa: F811
    team: Team,
    product: dict[str, Any],  # noqa: F811
    db_conn: Connection,
) -> None:
    ret = await _portal_return(
        client,
        storage,
        team,
        product,
        {"resolution_code": "FREE_REPLACEMENT", "resolution_qty": 2},
        qty=2,
    )
    res = await client.post(
        f"{SETTLE}/unboxing",
        json={
            "platform_code": "AMAZON",
            "lines": [{"return_id": ret["id"], "good_qty": 0, "repair_qty": 0, "wastage_qty": 2}],
        },
        headers=_h(team.unboxer, _key()),
    )
    assert res.status_code == 201, res.text
    sheet = res.json()
    # Qty Issue CN = 0 (free replacement): no credit note, the sheet completes at once.
    assert sheet["total_cn_qty"] == 0 and sheet["status"] == "COMPLETED"
    assert sheet["lines"][0]["status"] == "CLOSED"
    # A no-ticket return closed without a ticket passes the commit-time checks.
    _commit_checks(db_conn)
    res = await client.post(
        f"{SETTLE}/action-sheets/{sheet['id']}/complete",
        json={},
        headers=_h(team.accounts, _key()),
    )
    assert res.status_code == 409


# --- DB guards (non-bypassable, rule c) ---------------------------------------------------------
def _pending_unboxing(conn: Connection, users: UserFactory, team: Team) -> uuid.UUID:
    """A PENDING_UNBOXING return (different product, qty 2, REFUND 2) built in SQL as each role."""
    users.set_actor(team.gate_id)
    rid = uuid.UUID(
        str(
            conn.execute(
                text(
                    """
                    insert into public.ecommerce_returns
                      (return_no, entry_date, platform_code, platform_label, order_id,
                       product_type_code, product_type_label, different_product_desc, qty,
                       qc_routing_code, qc_routing_label)
                    values (:no, current_date, 'AMAZON', 'Amazon', 'ORDER9', 'DIFFERENT_PRODUCT',
                            'Different Product', 'Other thing', 2, 'ISSUE_TO_CHECKING', 'x')
                    returning id
                    """
                ),
                {"no": f"T-{uuid.uuid4().hex[:8]}"},
            ).scalar_one()
        )
    )
    mid = conn.execute(
        text(
            """
            insert into public.ecommerce_return_media (return_id, kind, bucket, object_path,
              mime_type, size_bytes)
            values (:rid, 'PACKAGE_VIDEO', 'rms-videos', :path, 'video/mp4', 10) returning id
            """
        ),
        {"rid": rid, "path": f"ecom/{rid}/package_video/{uuid.uuid4()}.mp4"},
    ).scalar_one()
    conn.execute(
        text(
            "update public.ecommerce_return_media set status='CONFIRMED', confirmed_at=now() "
            "where id=:id"
        ),
        {"id": mid},
    )
    conn.execute(
        text(
            "update public.ecommerce_returns set status='IN_CHECKING', submitted_at=now(), "
            "submitted_by=:u where id=:id"
        ),
        {"id": rid, "u": team.gate_id},
    )
    resolve = text(
        """
        update public.ecommerce_returns
           set status='PENDING_UNBOXING', resolution_code=:code, resolution_label='x',
               resolution_qty=2, resolved_at=now(), resolved_by=:u
         where id=:id
        """
    )
    # Only the executive; only an active resolution option.
    with pytest.raises(DBAPIError, match="ECOM_FORBIDDEN"), conn.begin_nested():
        conn.execute(resolve, {"id": rid, "u": team.gate_id, "code": "REFUND"})
    users.set_actor(team.exec_id)
    with pytest.raises(DBAPIError, match="ECOM_RESOLUTION_REQUIRED"), conn.begin_nested():
        conn.execute(resolve, {"id": rid, "u": team.exec_id, "code": "MAYBE"})
    conn.execute(resolve, {"id": rid, "u": team.exec_id, "code": "REFUND"})
    return rid


def test_db_guards_settlement(db_conn: Connection, users: UserFactory, team: Team) -> None:
    conn = as_admin(db_conn)
    rid = _pending_unboxing(conn, users, team)

    # The resolution is written once.
    with pytest.raises(DBAPIError, match="ECOM_RETURN_IMMUTABLE"), conn.begin_nested():
        conn.execute(
            text("update public.ecommerce_returns set resolution_qty=1 where id=:id"), {"id": rid}
        )

    unbox = text(
        """
        update public.ecommerce_returns
           set status='UNBOXED', action_sheet_id=:sheet, good_qty=0, repair_qty=0, wastage_qty=2,
               cn_qty=:cn, unboxed_at=now(), unboxed_by=:u
         where id=:id
        """
    )
    users.set_actor(team.unboxer_id)
    sheet = conn.execute(
        text(
            "insert into public.ecommerce_action_sheets (sheet_no, platform_code, platform_label) "
            "values (:no, 'AMAZON', 'Amazon') returning id"
        ),
        {"no": f"S-{uuid.uuid4().hex[:8]}"},
    ).scalar_one()
    # CN rule: a REFUND of 2 must carry Qty Issue CN 2 (CHECK ecommerce_returns_cn_qty_rule).
    with pytest.raises(DBAPIError, match="ecommerce_returns_cn_qty_rule"), conn.begin_nested():
        conn.execute(unbox, {"id": rid, "sheet": sheet, "cn": 0, "u": team.unboxer_id})
    # A different product cannot send pieces to the store (CHECK on the unboxing shape).
    with pytest.raises(DBAPIError, match="ecommerce_returns_unboxing_shape"), conn.begin_nested():
        conn.execute(
            text(
                """
                update public.ecommerce_returns
                   set status='UNBOXED', action_sheet_id=:sheet, good_qty=2, repair_qty=0,
                       wastage_qty=0, cn_qty=2, unboxed_at=now(), unboxed_by=:u
                 where id=:id
                """
            ),
            {"id": rid, "sheet": sheet, "u": team.unboxer_id},
        )
    # Only the unboxing user unboxes.
    users.set_actor(team.exec_id)
    with pytest.raises(DBAPIError, match="ECOM_FORBIDDEN"), conn.begin_nested():
        conn.execute(unbox, {"id": rid, "sheet": sheet, "cn": 2, "u": team.exec_id})
    users.set_actor(team.unboxer_id)
    conn.execute(unbox, {"id": rid, "sheet": sheet, "cn": 2, "u": team.unboxer_id})

    # The unboxing result is final; an unboxed return is not voided.
    with pytest.raises(DBAPIError, match="ECOM_RETURN_IMMUTABLE"), conn.begin_nested():
        conn.execute(
            text("update public.ecommerce_returns set wastage_qty=1, good_qty=1 where id=:id"),
            {"id": rid},
        )
    users.set_actor(team.mgmt_id)
    with pytest.raises(DBAPIError, match="ECOM_INVALID_STATE"), conn.begin_nested():
        conn.execute(
            text(
                "update public.ecommerce_returns set status='VOIDED', voided_at=now(), "
                "voided_by=:u, void_reason='abc' where id=:id"
            ),
            {"id": rid, "u": team.mgmt_id},
        )
    # Not closed before its sheet is completed.
    with pytest.raises(DBAPIError, match="ECOM_NOT_SETTLED"), conn.begin_nested():
        conn.execute(
            text(
                "update public.ecommerce_returns set status='CLOSED', closed_at=now() where id=:id"
            ),
            {"id": rid},
        )
    complete = text(
        """
        update public.ecommerce_action_sheets
           set status='COMPLETED', cn_no=:no, cn_date=current_date, cn_value=:v,
               completed_at=now(), completed_by=:u
         where id=:id
        """
    )
    # Qty Issue CN 2: only E-Commerce Accounts, and only with the credit note.
    users.set_actor(team.unboxer_id)
    with pytest.raises(DBAPIError, match="ECOM_FORBIDDEN"), conn.begin_nested():
        conn.execute(complete, {"id": sheet, "no": "CN1", "v": 10, "u": team.unboxer_id})
    users.set_actor(team.accounts_id)
    with pytest.raises(DBAPIError, match="ECOM_CN_REQUIRED"), conn.begin_nested():
        conn.execute(complete, {"id": sheet, "no": None, "v": None, "u": team.accounts_id})
    conn.execute(complete, {"id": sheet, "no": "CN1", "v": 10, "u": team.accounts_id})
    with pytest.raises(DBAPIError, match="ECOM_SHEET_COMPLETED"), conn.begin_nested():
        conn.execute(
            text("update public.ecommerce_action_sheets set remarks='x' where id=:id"),
            {"id": sheet},
        )
    with pytest.raises(DBAPIError, match="ECOM_RETURN_IMMUTABLE"), conn.begin_nested():
        conn.execute(text("delete from public.ecommerce_action_sheets where id=:id"), {"id": sheet})
    conn.execute(
        text("update public.ecommerce_returns set status='CLOSED', closed_at=now() where id=:id"),
        {"id": rid},
    )
    users.set_actor(None)


def test_db_guard_sheet_needs_its_own_unboxing_and_one_platform(
    db_conn: Connection, users: UserFactory, team: Team
) -> None:
    conn = as_admin(db_conn)
    rid = _pending_unboxing(conn, users, team)
    users.set_actor(team.gate_id)
    with pytest.raises(DBAPIError, match="ECOM_FORBIDDEN"), conn.begin_nested():
        conn.execute(
            text(
                "insert into public.ecommerce_action_sheets (sheet_no, platform_code, "
                "platform_label) values ('S-X', 'AMAZON', 'Amazon')"
            )
        )
    users.set_actor(team.unboxer_id)
    sheet = conn.execute(
        text(
            "insert into public.ecommerce_action_sheets (sheet_no, platform_code, platform_label) "
            "values (:no, 'FLIPKART', 'Flipkart') returning id"
        ),
        {"no": f"S-{uuid.uuid4().hex[:8]}"},
    ).scalar_one()
    with pytest.raises(DBAPIError, match="ECOM_SHEET_PLATFORM"), conn.begin_nested():
        conn.execute(
            text(
                """
                update public.ecommerce_returns
                   set status='UNBOXED', action_sheet_id=:sheet, good_qty=0, repair_qty=0,
                       wastage_qty=2, cn_qty=2, unboxed_at=now(), unboxed_by=:u
                 where id=:id
                """
            ),
            {"id": rid, "sheet": sheet, "u": team.unboxer_id},
        )
    users.set_actor(None)


def test_db_guard_ticket_close_needs_resolution(
    db_conn: Connection, users: UserFactory, team: Team
) -> None:
    """Closing the ticket alone leaves the return TICKET_RAISED: refused at commit."""
    conn = as_admin(db_conn)
    users.set_actor(team.gate_id)
    rid = conn.execute(
        text(
            """
            insert into public.ecommerce_returns
              (return_no, entry_date, platform_code, platform_label, order_id, product_type_code,
               product_type_label, different_product_desc, qty, qc_routing_code, qc_routing_label)
            values (:no, current_date, 'AMAZON', 'Amazon', 'ORDER7', 'DIFFERENT_PRODUCT',
                    'Different Product', 'Other', 1, 'TICKET_RAISE', 'x')
            returning id
            """
        ),
        {"no": f"T-{uuid.uuid4().hex[:8]}"},
    ).scalar_one()
    mid = conn.execute(
        text(
            "insert into public.ecommerce_return_media (return_id, kind, bucket, object_path, "
            "mime_type, size_bytes) values (:rid, 'PACKAGE_VIDEO', 'rms-videos', :p, "
            "'video/mp4', 10) returning id"
        ),
        {"rid": rid, "p": f"ecom/{rid}/package_video/{uuid.uuid4()}.mp4"},
    ).scalar_one()
    conn.execute(
        text(
            "update public.ecommerce_return_media set status='CONFIRMED', confirmed_at=now() "
            "where id=:id"
        ),
        {"id": mid},
    )
    conn.execute(
        text(
            "update public.ecommerce_returns set status='PENDING_TICKET', submitted_at=now() "
            "where id=:id"
        ),
        {"id": rid},
    )
    conn.execute(
        text("insert into public.ecommerce_tickets (return_id, sla_due_at) values (:id, now())"),
        {"id": rid},
    )
    users.set_actor(team.exec_id)
    conn.execute(
        text(
            "update public.ecommerce_tickets set raised_at=now(), assigned_handler_id=:u, "
            "response_code='REJECTED', response_label='Rejected', rejection_remark='Not covered', "
            "responded_at=now() where return_id=:id"
        ),
        {"id": rid, "u": team.exec_id},
    )
    with pytest.raises(DBAPIError, match="ECOM_RESOLUTION_REQUIRED"), conn.begin_nested():
        conn.execute(
            text(
                "update public.ecommerce_tickets set closed_at=now(), closed_by=:u "
                "where return_id=:id"
            ),
            {"id": rid, "u": team.exec_id},
        )
        conn.execute(text("set constraints all immediate"))
    users.set_actor(None)


async def test_store_receipt_guard_only_store_user_with_movement(
    client: AsyncClient,  # noqa: F811
    storage: FakeStorage,  # noqa: F811
    team: Team,
    product: dict[str, Any],  # noqa: F811
    db_conn: Connection,
    users: UserFactory,
) -> None:
    ret = await _portal_return(
        client,
        storage,
        team,
        product,
        {"resolution_code": "FREE_REPLACEMENT", "resolution_qty": 1},
        qty=1,
    )
    res = await client.post(
        f"{SETTLE}/unboxing",
        json={
            "platform_code": "AMAZON",
            "lines": [{"return_id": ret["id"], "good_qty": 1, "repair_qty": 0, "wastage_qty": 0}],
        },
        headers=_h(team.unboxer, _key()),
    )
    assert res.status_code == 201, res.text
    conn = as_admin(db_conn)
    receipt = fetch_all(
        conn,
        "select id from public.ecommerce_store_receipts where return_id = cast(:r as uuid)",
        r=ret["id"],
    )[0]["id"]
    ack = text(
        """
        update public.ecommerce_store_receipts
           set status='ACKNOWLEDGED', acknowledged_at=now(), acknowledged_by=:u,
               movement_id=(select id from public.stock_movements limit 1)
         where id=:id
        """
    )
    # The unboxing user is not a store user.
    users.set_actor(team.unboxer_id)
    with pytest.raises(DBAPIError, match="ECOM_FORBIDDEN"), conn.begin_nested():
        conn.execute(ack, {"id": receipt, "u": team.unboxer_id})
    # A store user needs the real movement into the store.
    users.set_actor(team.store_id)
    with pytest.raises(DBAPIError, match="ECOM_MOVEMENT_MISMATCH"), conn.begin_nested():
        conn.execute(ack, {"id": receipt, "u": team.store_id})
    with pytest.raises(DBAPIError, match="ECOM_RETURN_IMMUTABLE"), conn.begin_nested():
        conn.execute(
            text("update public.ecommerce_store_receipts set qty=5 where id=:id"), {"id": receipt}
        )
    users.set_actor(None)


# --- work queues (menu badges / My Work) --------------------------------------------------------
async def test_settlement_steps_have_work_queues(
    client: AsyncClient,  # noqa: F811
    storage: FakeStorage,  # noqa: F811
    team: Team,
    product: dict[str, Any],  # noqa: F811
) -> None:
    async def count(token: str, code: str) -> int:
        res = await client.get("/api/v1/me/journey", headers=_h(token))
        assert res.status_code == 200, res.text
        entry = next(e for e in res.json()["entries"] if e["code"] == code)
        return int(entry["count"])

    portal0 = await count(team.exec, "ECOM_PORTAL_CHECK")
    unbox0 = await count(team.unboxer, "ECOM_UNBOXING")
    store0 = await count(team.store, "ECOM_STORE_RECEIPTS")
    sheets0 = await count(team.accounts, "ECOM_ACTION_SHEETS")

    body = await _submitted(
        client, storage, team.gate, _payload(product, qc_routing_code="ISSUE_TO_CHECKING", qty=1)
    )
    assert await count(team.exec, "ECOM_PORTAL_CHECK") == portal0 + 1
    res = await client.post(
        f"{TICKETS}/portal-checks/{body['id']}",
        json={"resolution_code": "REFUND", "resolution_qty": 1},
        headers=_h(team.exec, _key()),
    )
    assert res.status_code == 200, res.text
    assert await count(team.exec, "ECOM_PORTAL_CHECK") == portal0
    assert await count(team.unboxer, "ECOM_UNBOXING") == unbox0 + 1
    res = await client.post(
        f"{SETTLE}/unboxing",
        json={
            "platform_code": "AMAZON",
            "lines": [{"return_id": body["id"], "good_qty": 1, "repair_qty": 0, "wastage_qty": 0}],
        },
        headers=_h(team.unboxer, _key()),
    )
    assert res.status_code == 201, res.text
    assert await count(team.unboxer, "ECOM_UNBOXING") == unbox0
    assert await count(team.store, "ECOM_STORE_RECEIPTS") == store0 + 1
    assert await count(team.accounts, "ECOM_ACTION_SHEETS") == sheets0 + 1
