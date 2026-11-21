"""Phase P4 (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-64 (Q9 PROVISIONAL; Q10-Q12 user).

Items (doc qty + physical qty) → popup Replacement / Complete Sales Return → categorisation (split
per line, G-19) → Lock (inward stock booked into INWARD_STAGING once, Q12) → edits after the lock
by Super Admin / Management only, with a reason, a revision and the stock corrected in the same
transaction, until the first routing. Replaces the DEC-53 "submit to RM review" tests.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, fetch_all
from tests.integration.gate_v4.test_gate_v4 import Actors
from tests.integration.gate_v4.test_unboxing_p3 import _complete, _unboxing_gs, _videos
from tests.integration.test_gate_inward import Masters, _auth
from tests.integration.test_itemization import key
from tests.integration.test_unboxing import FakeStorage

pytestmark = pytest.mark.gate_v4


@pytest.fixture
def mgmt(users: UserFactory, make_token: JwtFactory) -> str:
    return make_token(users.create(roles=["MANAGEMENT"], full_name="Mgmt"))


@pytest.fixture
def rm(users: UserFactory, make_token: JwtFactory) -> str:
    return make_token(users.create(roles=["REPLACEMENT_MANAGER"], full_name="RM"))


@pytest.fixture
def product_ids(db_conn: Connection) -> list[str]:
    """Two products of the DMT category (its default profile has condition buckets)."""
    c = as_admin(db_conn)
    tag = uuid.uuid4().hex[:6].upper()
    ids = []
    for n in (1, 2):
        ids.append(
            str(
                c.execute(
                    text(
                        """insert into public.products (code, name, category_id)
                           select :code, :name, id from public.product_categories where code = 'DMT'
                           returning id"""
                    ),
                    {"code": f"P4-{tag}-{n}", "name": f"P4 product {n} {tag}"},
                ).scalar_one()
            )
        )
    return ids


async def _items_gs(
    client: AsyncClient, storage: FakeStorage, a: Actors, m: Masters, **kw: Any
) -> str:
    gs_id = await _unboxing_gs(client, a, m, **kw)
    await _videos(client, storage, a.aman, gs_id, (1, 2))
    res = await _complete(client, a.aman, gs_id)
    assert res.status_code == 200, res.text
    return gs_id


async def _line(
    client: AsyncClient, token: str, gs_id: str, product: str, doc: int, recv: int
) -> str:
    res = await client.post(
        f"/api/v1/gs/{gs_id}/items",
        json={"product_id": product, "documented_qty": doc, "received_qty": recv},
        headers=_auth(token),
    )
    assert res.status_code == 201, res.text
    return str(res.json()["id"])


async def _bucket_codes(client: AsyncClient, token: str, product: str) -> list[str]:
    res = await client.get(
        f"/api/v1/itemization/lookups/products/{product}/fields", headers=_auth(token)
    )
    assert res.status_code == 200, res.text
    return [b["field_code"] for b in res.json()["allowed_buckets"]]


async def _split(
    client: AsyncClient, token: str, gs_id: str, item: str, buckets: dict[str, int]
) -> Any:
    return await client.patch(
        f"/api/v1/gs/{gs_id}/items/{item}",
        json={"buckets": [{"field_code": c, "qty": q} for c, q in buckets.items()]},
        headers=_auth(token),
    )


async def _choose(
    client: AsyncClient, token: str, gs_id: str, code: str, idem: str | None = None
) -> Any:
    return await client.post(
        f"/api/v1/gs/{gs_id}/itemization/return-choice",
        json={"category_code": code},
        headers=_auth(token, idem or key()),
    )


async def _lock(client: AsyncClient, token: str, gs_id: str, idem: str | None = None) -> Any:
    return await client.post(
        f"/api/v1/gs/{gs_id}/categorisation/lock", json={}, headers=_auth(token, idem or key())
    )


def _inward_stock(conn: Connection, gs_id: str) -> dict[str, int]:
    """Per line: stock at INWARD_STAGING (all lots of the line)."""
    rows = fetch_all(
        conn,
        """select l.gs_item_id::text as item, coalesce(sum(b.qty), 0)::int as qty
             from public.stock_lots l
             join public.stock_balances b on b.lot_id = l.id
             join public.inventory_locations loc
               on loc.id = b.location_id and loc.code = 'INWARD_STAGING'
            where l.gs_id = :g group by l.gs_item_id""",
        g=gs_id,
    )
    return {r["item"]: r["qty"] for r in rows}


async def _locked_gs(
    client: AsyncClient,
    storage: FakeStorage,
    a: Actors,
    m: Masters,
    products: list[str],
) -> tuple[str, list[str], str]:
    gs_id = await _items_gs(client, storage, a, m)
    i1 = await _line(client, a.aman, gs_id, products[0], 5, 4)
    i2 = await _line(client, a.aman, gs_id, products[1], 0, 2)
    assert (await _choose(client, a.aman, gs_id, "RO")).status_code == 200
    code = (await _bucket_codes(client, a.aman, products[0]))[0]
    assert (await _split(client, a.aman, gs_id, i1, {code: 4})).status_code == 200
    assert (await _split(client, a.aman, gs_id, i2, {code: 2})).status_code == 200
    res = await _lock(client, a.aman, gs_id)
    assert res.status_code == 200, res.text
    return gs_id, [i1, i2], code


# --- popup (DEC-64 a, b) --------------------------------------------------------------------------
async def test_popup_replacement_goes_to_categorisation(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    product_ids: list[str],
) -> None:
    gs_id = await _items_gs(client, storage, actors, masters)
    # No lines → refused.
    res = await _choose(client, actors.aman, gs_id, "RO")
    assert res.status_code == 422 and res.json()["error"]["code"] == "ITEMS_REQUIRED"
    await _line(client, actors.aman, gs_id, product_ids[0], 3, 3)
    state = (await client.get(f"/api/v1/gs/{gs_id}/itemization", headers=_auth(actors.aman))).json()
    assert state["permissions"]["can_choose_return"] is True
    assert [c["code"] for c in state["return_choices"]] == ["RO", "CSR"]
    assert state["return_choices"][0]["label"] == "Replacement"  # from configuration
    # Unknown / inactive codes → 422 (validated against the option set).
    for bad in ("REPLACEMENT", "XX"):
        res = await _choose(client, actors.aman, gs_id, bad)
        assert res.status_code == 422, res.text
    idem = key()
    first = await _choose(client, actors.aman, gs_id, "RO", idem)
    replay = await _choose(client, actors.aman, gs_id, "RO", idem)
    assert first.status_code == replay.status_code == 200, first.text
    assert replay.headers.get("Idempotency-Replayed") == "true"
    gs = first.json()["state"]["goods_slip"]
    assert (gs["status"], gs["category_code"], gs["original_category_code"]) == (
        "CATEGORISATION",
        "RO",
        "RO",
    )
    assert first.json()["state"]["category_label"] == "Replacement"
    # The choice is final.
    res = await _choose(client, actors.aman, gs_id, "CSR")
    assert res.status_code == 409 and res.json()["error"]["code"] == "RETURN_ALREADY_CHOSEN"


async def test_popup_complete_sales_return_parks_the_gs(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    product_ids: list[str],
    db_conn: Connection,
) -> None:
    gs_id = await _items_gs(client, storage, actors, masters)
    await _line(client, actors.aman, gs_id, product_ids[0], 3, 3)
    res = await _choose(client, actors.aman, gs_id, "CSR")
    assert res.status_code == 200, res.text
    state = res.json()["state"]
    assert state["goods_slip"]["status"] == "SALES_RETURN_HOLD"
    assert state["goods_slip"]["category_code"] == "CSR"
    assert state["permissions"]["can_edit_lines"] is False
    assert state["permissions"]["can_lock"] is False
    assert state["lots"] == []  # nothing is booked (Q11)
    open_tasks = fetch_all(
        db_conn,
        "select 1 from public.workflow_tasks where gs_id = :g and status = 'OPEN'",
        g=gs_id,
    )
    assert open_tasks == []
    notes = fetch_all(
        db_conn,
        "select 1 from public.notifications where entity_id = :g and type = 'SALES_RETURN_HOLD'",
        g=gs_id,
    )
    assert notes, "RM / Management are told about the parked GS"
    res = await _line_add_refused(client, actors.aman, gs_id, product_ids[0])
    assert res.status_code == 409


async def _line_add_refused(client: AsyncClient, token: str, gs_id: str, product: str) -> Any:
    return await client.post(
        f"/api/v1/gs/{gs_id}/items",
        json={"product_id": product, "documented_qty": 1, "received_qty": 1},
        headers=_auth(token),
    )


# --- lock (DEC-64 c, Q12) -------------------------------------------------------------------------
async def test_lock_books_stock_exactly_once(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    product_ids: list[str],
    db_conn: Connection,
) -> None:
    gs_id = await _items_gs(client, storage, actors, masters)
    i1 = await _line(client, actors.aman, gs_id, product_ids[0], 5, 4)
    i2 = await _line(client, actors.aman, gs_id, product_ids[1], 0, 2)
    # Lock before the popup → refused.
    res = await _lock(client, actors.aman, gs_id)
    assert res.status_code == 409, res.text
    assert (await _choose(client, actors.aman, gs_id, "RO")).status_code == 200
    code = (await _bucket_codes(client, actors.aman, product_ids[0]))[0]
    assert (await _split(client, actors.aman, gs_id, i1, {code: 4})).status_code == 200
    # Line 2 not split → G-19, nothing booked.
    res = await _lock(client, actors.aman, gs_id)
    assert res.status_code == 409 and res.json()["error"]["code"] == "G-19", res.text
    assert _inward_stock(db_conn, gs_id) == {}
    # A split total that is not the physical qty is refused when saved.
    bad = await _split(client, actors.aman, gs_id, i2, {code: 1})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "BUCKET_TOTAL_MISMATCH"
    assert (await _split(client, actors.aman, gs_id, i2, {code: 2})).status_code == 200

    idem = key()
    first = await _lock(client, actors.aman, gs_id, idem)
    replay = await _lock(client, actors.aman, gs_id, idem)
    assert first.status_code == replay.status_code == 200, first.text
    assert replay.headers.get("Idempotency-Replayed") == "true"
    gs = first.json()["state"]["goods_slip"]
    assert gs["status"] == "PENDING_TRANSFER_SLIP"
    assert gs["categorisation_locked_at"] is not None
    assert _inward_stock(db_conn, gs_id) == {i1: 4, i2: 2}
    movements = fetch_all(
        db_conn,
        """select count(*)::int as n from public.stock_movements m
             join public.stock_lots l on l.id = m.lot_id where l.gs_id = :g""",
        g=gs_id,
    )
    assert movements == [{"n": 2}]  # one INWARD per line, not repeated by the replay
    again = await _lock(client, actors.aman, gs_id)
    assert again.status_code == 409
    assert _inward_stock(db_conn, gs_id) == {i1: 4, i2: 2}
    revs = fetch_all(
        db_conn,
        "select action from public.rm_review_revisions where gs_id = :g order by revision_no",
        g=gs_id,
    )
    assert [r["action"] for r in revs] == ["CATEGORISATION_LOCKED"]
    notes = fetch_all(
        db_conn,
        "select 1 from public.notifications where entity_id = :g "
        "and type = 'CATEGORISATION_LOCKED'",
        g=gs_id,
    )
    assert notes, "the RM is told the GS waits for its transfer slip"


# --- edits after the lock (DEC-64 d) -------------------------------------------------------------
async def test_only_management_edits_after_the_lock(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    product_ids: list[str],
    mgmt: str,
    rm: str,
    db_conn: Connection,
) -> None:
    gs_id, (i1, i2), code = await _locked_gs(client, storage, actors, masters, product_ids)
    # The RE's line endpoints and the RE / RM on the locked endpoints are refused.
    res = await client.patch(
        f"/api/v1/gs/{gs_id}/items/{i1}", json={"received_qty": 3}, headers=_auth(actors.aman)
    )
    assert res.status_code == 409
    body = {"received_qty": 3, "buckets": [{"field_code": code, "qty": 3}], "reason": "recount"}
    for token in (actors.aman, rm):
        res = await client.patch(
            f"/api/v1/gs/{gs_id}/locked/items/{i1}", json=body, headers=_auth(token, key())
        )
        assert res.status_code == 403, res.text
    state = (await client.get(f"/api/v1/gs/{gs_id}/itemization", headers=_auth(mgmt))).json()
    assert state["permissions"]["can_edit_locked"] is True

    # Validation: reason, split with a changed qty.
    res = await client.patch(
        f"/api/v1/gs/{gs_id}/locked/items/{i1}",
        json={"received_qty": 3, "buckets": [{"field_code": code, "qty": 3}], "reason": " "},
        headers=_auth(mgmt, key()),
    )
    assert res.status_code == 422
    res = await client.patch(
        f"/api/v1/gs/{gs_id}/locked/items/{i1}",
        json={"received_qty": 3, "reason": "recount"},
        headers=_auth(mgmt, key()),
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "SPLIT_REQUIRED"

    # Qty 4 → 3: stock corrected in the same transaction, revision with the reason.
    res = await client.patch(
        f"/api/v1/gs/{gs_id}/locked/items/{i1}", json=body, headers=_auth(mgmt, key())
    )
    assert res.status_code == 200, res.text
    assert res.json()["revision_no"] == 2
    assert _inward_stock(db_conn, gs_id) == {i1: 3, i2: 2}

    # Product change: the old lot is emptied, a new lot carries the qty.
    res = await client.patch(
        f"/api/v1/gs/{gs_id}/locked/items/{i2}",
        json={
            "product_id": product_ids[0],
            "received_qty": 2,
            "buckets": [{"field_code": code, "qty": 2}],
            "reason": "wrong product picked",
        },
        headers=_auth(mgmt, key()),
    )
    assert res.status_code == 200, res.text
    lots = fetch_all(
        db_conn,
        """select l.id, coalesce(sum(b.qty), 0)::int as qty from public.stock_lots l
             left join public.stock_balances b on b.lot_id = l.id
            where l.gs_item_id = :i group by l.id order by l.created_at""",
        i=i2,
    )
    assert sorted(r["qty"] for r in lots) == [0, 2]  # old lot emptied, new lot carries 2

    # Add a line (stock booked) and remove one (kept with qty 0, stock out).
    add = await client.post(
        f"/api/v1/gs/{gs_id}/locked/items",
        json={
            "product_id": product_ids[1],
            "documented_qty": 0,
            "received_qty": 1,
            "buckets": [{"field_code": code, "qty": 1}],
            "reason": "found later in carton 2",
        },
        headers=_auth(mgmt, key()),
    )
    assert add.status_code == 201, add.text
    new_line = next(i["id"] for i in add.json()["state"]["items"] if i["id"] not in (i1, i2))
    assert _inward_stock(db_conn, gs_id)[new_line] == 1
    rem = await client.post(
        f"/api/v1/gs/{gs_id}/locked/items/{i1}/remove",
        json={"reason": "belongs to another party"},
        headers=_auth(mgmt, key()),
    )
    assert rem.status_code == 200, rem.text
    kept = next(i for i in rem.json()["state"]["items"] if i["id"] == i1)
    assert (kept["documented_qty"], kept["received_qty"]) == (0, 0)
    assert kept["removed_at"] is not None and kept["removal_reason"] == "belongs to another party"
    again = await client.patch(
        f"/api/v1/gs/{gs_id}/locked/items/{i1}", json=body, headers=_auth(mgmt, key())
    )
    assert again.status_code == 409 and again.json()["error"]["code"] == "LINE_ALREADY_REMOVED"
    assert _inward_stock(db_conn, gs_id)[i1] == 0
    actions = [
        r["action"]
        for r in fetch_all(
            db_conn,
            "select action from public.rm_review_revisions where gs_id = :g order by revision_no",
            g=gs_id,
        )
    ]
    assert actions == [
        "CATEGORISATION_LOCKED",
        "LOCKED_EDIT",
        "LOCKED_CHANGE_PRODUCT",
        "LOCKED_ADD_LINE",
        "LOCKED_REMOVE_LINE",
    ]
    assert fetch_all(
        db_conn,
        "select 1 from public.notifications where entity_id = :g and type = 'LOCKED_GS_EDITED'",
        g=gs_id,
    )


async def test_edit_window_closes_at_the_first_routing(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    product_ids: list[str],
    mgmt: str,
    db_conn: Connection,
) -> None:
    gs_id, (i1, _i2), code = await _locked_gs(client, storage, actors, masters, product_ids)
    c = as_admin(db_conn)
    c.execute(text("set local session_replication_role = replica"))  # setup: a routing row
    c.execute(
        text(
            """insert into public.department_routings
                      (routing_no, gs_id, department_field_id, department_code, department_label)
               select 'P4-DIN-' || left(:g, 8), cast(:g as uuid),
                      (select id from public.item_field_library limit 1),
                      'DEPT_X', 'Dept X'"""
        ),
        {"g": gs_id},
    )
    c.execute(text("set local session_replication_role = origin"))
    state = (await client.get(f"/api/v1/gs/{gs_id}/itemization", headers=_auth(mgmt))).json()
    assert state["permissions"]["can_edit_locked"] is False
    assert state["permissions"]["edit_window_closed"] is True
    res = await client.patch(
        f"/api/v1/gs/{gs_id}/locked/items/{i1}",
        json={"received_qty": 3, "buckets": [{"field_code": code, "qty": 3}], "reason": "late"},
        headers=_auth(mgmt, key()),
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "EDIT_WINDOW_CLOSED"
    # The DB refuses it too (non-bypassable).
    with pytest.raises(DBAPIError, match="routing has started"), c.begin_nested():
        c.execute(text("update public.gs_items set documented_qty = 9 where id = :i"), {"i": i1})
