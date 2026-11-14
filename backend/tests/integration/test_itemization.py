"""Step-3 itemisation, GS-wise categorisation, CSR approval, corrections, packaging check
(prompt P2-04; BR-07..BR-10, G-03, G-16, G-17, DEC-06, DEC-09, DEC-27, DEC-28).

The GS is walked through the real Step-1 / Step-2 APIs (storage faked as in test_unboxing) and the
real local Supabase Postgres (rolled back per test).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import get_session_factory
from app.core.middleware import limiter
from app.shared.storage import get_storage
from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, build_test_app, fetch_all
from tests.integration.test_gate_inward import Masters, _auth
from tests.integration.test_unboxing import (
    INVOICE,
    Actors,
    FakeStorage,
    classify,
    complete,
    started_gs,
    upload,
    upload_videos,
)


# --- fixtures (same shape as test_unboxing) ------------------------------------------------------
@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
async def client(
    session_factory: sessionmaker[Session], storage: FakeStorage
) -> AsyncIterator[AsyncClient]:
    app = build_test_app()
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_storage] = lambda: storage
    limiter.reset()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    limiter.reset()


@pytest.fixture
def masters(db_conn: Connection) -> Masters:
    return Masters(db_conn)


@pytest.fixture
def actors(users: UserFactory, make_token: JwtFactory) -> Actors:
    aman_id = users.create(roles=["INWARD_VERIFIER"], full_name="Aman")
    rm_id = users.create(roles=["REPLACEMENT_MANAGER"], full_name="Pratham")
    acc_id = users.create(roles=["ACCOUNTS"], full_name="Deepak")
    return Actors(
        gate=make_token(users.create(roles=["GATE_INWARD"], full_name="Anuj")),
        aman=make_token(aman_id),
        aman_id=aman_id,
        rm=make_token(rm_id),
        rm_id=rm_id,
        accounts=make_token(acc_id),
        accounts_id=acc_id,
        admin=make_token(users.create(super_admin=True, full_name="Admin")),
    )


@dataclass
class Products:
    dmt: str
    prismatic: str


@pytest.fixture
def products(db_conn: Connection) -> Products:
    c = as_admin(db_conn)
    tag = uuid.uuid4().hex[:6].upper()

    def make(category: str) -> str:
        return str(
            c.execute(
                text(
                    """insert into public.products (code, name, category_id)
                       select :code, :name, id from public.product_categories where code = :cat
                       returning id"""
                ),
                {"code": f"T-{category}-{tag}", "name": f"Test {category} {tag}", "cat": category},
            ).scalar_one()
        )

    return Products(dmt=make("DMT"), prismatic=make("PRISMATIC"))


@pytest.fixture
def sahil(users: UserFactory, make_token: JwtFactory) -> str:
    return make_token(users.create(roles=["INTERMEDIATE_STORE_MANAGER"], full_name="Sahil"))


def key() -> str:
    return f"test-{uuid.uuid4()}"


async def itemizing_gs(client: AsyncClient, storage: FakeStorage, a: Actors, m: Masters) -> str:
    """A GS walked through gate + unboxing (G-02 evidence) to ITEMIZATION."""
    gs_id = await started_gs(client, a, m)
    await upload_videos(client, storage, a.aman, gs_id)
    photo = await upload(client, storage, a.aman, gs_id, "DOC_PHOTO", "image/jpeg")
    assert (await classify(client, a.aman, gs_id, photo["id"], INVOICE)).status_code == 201
    res = await complete(client, a.aman, gs_id)
    assert res.status_code == 200, res.text
    assert res.json()["goods_slip"]["status"] == "ITEMIZATION"
    return gs_id


async def add_line(
    client: AsyncClient, token: str, gs_id: str, product: str, doc: int, recv: int
) -> Any:
    return await client.post(
        f"/api/v1/gs/{gs_id}/items",
        json={"product_id": product, "documented_qty": doc, "received_qty": recv},
        headers=_auth(token),
    )


async def submit_counting(client: AsyncClient, token: str, gs_id: str) -> Any:
    """AMD-08 (change plan Phase 3): Counting (ITEMIZATION) -> CATEGORISATION."""
    return await client.post(f"/api/v1/gs/{gs_id}/counting/submit", headers=_auth(token, key()))


async def categorize(
    client: AsyncClient,
    token: str,
    gs_id: str,
    category: str,
    idem: str | None = None,
    *,
    submit: bool = True,
) -> Any:
    """Categorise the GS; by default the count is submitted first (the required order since
    AMD-08). A count that is already submitted (409) is fine."""
    if submit:
        res = await submit_counting(client, token, gs_id)
        assert res.status_code in (200, 409, 422, 403), res.text
    return await client.post(
        f"/api/v1/gs/{gs_id}/categorize",
        json={"category": category},
        headers=_auth(token, idem or key()),
    )


async def decide(
    client: AsyncClient, token: str, gs_id: str, decision: str, remarks: str | None = None
) -> Any:
    return await client.post(
        f"/api/v1/gs/{gs_id}/csr-decision",
        json={"decision": decision, "remarks": remarks},
        headers=_auth(token, key()),
    )


async def gs_with_lines(
    client: AsyncClient,
    storage: FakeStorage,
    a: Actors,
    m: Masters,
    p: Products,
    lines: list[tuple[str, int, int]],
) -> tuple[str, list[dict[str, Any]]]:
    gs_id = await itemizing_gs(client, storage, a, m)
    out = []
    for product, doc, recv in lines:
        res = await add_line(client, a.aman, gs_id, product, doc, recv)
        assert res.status_code == 201, res.text
        out.append(res.json())
    return gs_id, out


def balances(conn: Connection, gs_id: str) -> dict[str, int]:
    """gs_item_id → qty in INWARD_STAGING."""
    rows = fetch_all(
        conn,
        """select lot.gs_item_id::text as item, b.qty
             from public.stock_balances b
             join public.stock_lots lot on lot.id = b.lot_id
             join public.inventory_locations l on l.id = b.location_id
            where lot.gs_id = :g and l.code = 'INWARD_STAGING'""",
        g=gs_id,
    )
    return {r["item"]: r["qty"] for r in rows}


def open_tasks(conn: Connection, gs_id: str) -> list[dict[str, Any]]:
    return fetch_all(
        conn,
        """select t.step_code, r.code as role_code from public.workflow_tasks t
             left join public.roles r on r.id = t.assigned_role_id
            where t.gs_id = :g and t.status = 'OPEN'""",
        g=gs_id,
    )


# --- lines (DEC-09) ------------------------------------------------------------------------------
async def test_line_crud_short_excess_and_permissions(
    client: AsyncClient, storage: FakeStorage, actors: Actors, masters: Masters, products: Products
) -> None:
    gs_id = await itemizing_gs(client, storage, actors, masters)
    res = await add_line(client, actors.aman, gs_id, products.dmt, 10, 8)
    assert res.status_code == 201, res.text
    line = res.json()
    assert (line["line_no"], line["short_qty"], line["excess_qty"]) == (1, 2, 0)
    assert line["is_short"] is True
    assert line["category_code"] == "DMT" and line["product_name"].startswith("Test DMT")

    # Prismatic shortage is flagged too (DEC-09: all categories).
    res = await add_line(client, actors.aman, gs_id, products.prismatic, 4, 3)
    assert res.json()["is_short"] is True and res.json()["line_no"] == 2

    res = await client.patch(
        f"/api/v1/gs/{gs_id}/items/{line['id']}",
        json={"received_qty": 12, "remarks": "  counted twice  "},
        headers=_auth(actors.aman),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["short_qty"], body["excess_qty"], body["is_short"]) == (0, 2, False)
    assert body["remarks"] == "counted twice"

    res = await add_line(client, actors.aman, gs_id, products.dmt, 0, 0)
    assert res.status_code == 422 and res.json()["error"]["code"] == "FORM_VALIDATION_FAILED"
    res = await add_line(client, actors.aman, gs_id, products.dmt, -1, 2)
    assert res.status_code == 422

    # The RM has no itemization.create; the gate user has no itemization access at all.
    assert (await add_line(client, actors.rm, gs_id, products.dmt, 1, 1)).status_code == 403
    assert (await add_line(client, actors.gate, gs_id, products.dmt, 1, 1)).status_code == 403

    res = await client.delete(f"/api/v1/gs/{gs_id}/items/{line['id']}", headers=_auth(actors.aman))
    assert res.status_code == 204
    state = (await client.get(f"/api/v1/gs/{gs_id}/itemization", headers=_auth(actors.aman))).json()
    assert [i["line_no"] for i in state["items"]] == [2]
    # AMD-08: in Counting the lines can be submitted; the category is chosen after that.
    assert state["permissions"]["can_submit_counting"] is True
    assert state["permissions"]["can_categorize"] is False
    assert {o["code"] for o in state["category_options"]} == {"CSR", "RO"}
    csr = next(o for o in state["category_options"] if o["code"] == "CSR")
    assert csr["allowed_status"] == "CONDITIONAL" and csr["rule_text"]


async def test_lines_only_while_itemization(
    client: AsyncClient, actors: Actors, masters: Masters, products: Products
) -> None:
    gs_id = await started_gs(client, actors, masters)  # still UNBOXING
    res = await add_line(client, actors.aman, gs_id, products.dmt, 1, 1)
    assert res.status_code == 409 and res.json()["error"]["code"] == "GS_NOT_ITEMIZATION"


async def test_dec09_setting_limits_short_flag_to_short_qty_categories(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    db_conn: Connection,
) -> None:
    gs_id, _ = await gs_with_lines(
        client,
        storage,
        actors,
        masters,
        products,
        [(products.dmt, 5, 4), (products.prismatic, 5, 4)],
    )
    as_admin(db_conn).execute(
        text(
            "update public.system_settings set value = 'false'::jsonb "
            "where key = 'track_short_qty_all_categories'"
        )
    )
    state = (await client.get(f"/api/v1/gs/{gs_id}/itemization", headers=_auth(actors.aman))).json()
    flags = {i["category_code"]: (i["is_short"], i["short_qty"]) for i in state["items"]}
    # DMT has the SHORT_QTY condition option; the shortage itself is recorded either way.
    assert flags == {"DMT": (True, 1), "PRISMATIC": (False, 1)}


# --- categorise (BR-07, G-16) --------------------------------------------------------------------
async def test_categorize_ro_inwards_received_qty_idempotently(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    db_conn: Connection,
) -> None:
    gs_id, lines = await gs_with_lines(
        client,
        storage,
        actors,
        masters,
        products,
        [(products.dmt, 10, 8), (products.prismatic, 5, 5), (products.dmt, 3, 0)],
    )
    idem = key()
    res = await categorize(client, actors.aman, gs_id, "RO", idem)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["state"]["goods_slip"]["status"] == "INSPECTION"
    assert out["state"]["goods_slip"]["category_code"] == "RO"
    assert out["state"]["goods_slip"]["original_category_code"] == "RO"
    assert out["state"]["category_label"] == "Replacement Only"
    assert out["notified_user_count"] == 0
    assert open_tasks(db_conn, gs_id) == [
        {"step_code": "S1_INSPECT", "role_code": "INWARD_VERIFIER"}
    ]

    # One AS_RECEIVED lot per line with received > 0, qty = received; the all-short line is not
    # stocked (its shortage stays recorded on the line).
    expected = {lines[0]["id"]: 8, lines[1]["id"]: 5}
    assert balances(db_conn, gs_id) == expected
    movements = fetch_all(
        db_conn,
        """select m.idempotency_key, m.movement_type, m.qty, m.from_location_id
             from public.stock_movements m join public.stock_lots lot on lot.id = m.lot_id
            where lot.gs_id = :g order by m.idempotency_key""",
        g=gs_id,
    )
    assert {(r["idempotency_key"], r["movement_type"], r["qty"]) for r in movements} == {
        (f"{lines[0]['id']}:inward", "INWARD", 8),
        (f"{lines[1]['id']}:inward", "INWARD", 5),
    }
    lots = fetch_all(
        db_conn,
        """select lot.condition_class, si.item_kind from public.stock_lots lot
             join public.stock_items si on si.id = lot.stock_item_id where lot.gs_id = :g""",
        g=gs_id,
    )
    assert lots == [{"condition_class": "AS_RECEIVED", "item_kind": "FINISHED_GOOD"}] * 2
    state = out["state"]
    assert state["totals"] == {
        "lines": 3,
        "documented_qty": 18,
        "received_qty": 13,
        "short_qty": 5,
        "excess_qty": 0,
    }
    history = fetch_all(
        db_conn,
        "select from_status, to_status, step_code, reason from public.gs_status_history "
        'where gs_id = :g order by "at" desc limit 1',
        g=gs_id,
    )
    assert history[0]["to_status"] == "INSPECTION" and history[0]["step_code"] == "S1_INSPECT"

    # Same key → original response, no second inward; another key → 409.
    res = await categorize(client, actors.aman, gs_id, "RO", idem)
    assert res.status_code == 200 and res.headers.get("Idempotency-Replayed") == "true"
    assert balances(db_conn, gs_id) == expected
    assert (
        len(
            fetch_all(
                db_conn,
                "select 1 from public.stock_movements m "
                "join public.stock_lots l on l.id = m.lot_id where l.gs_id = :g",
                g=gs_id,
            )
        )
        == 2
    )
    res = await categorize(client, actors.aman, gs_id, "RO")
    assert res.status_code == 409 and res.json()["error"]["code"] == "GS_ALREADY_CATEGORIZED"

    # Lines are frozen after categorisation (service and DB).
    assert (await add_line(client, actors.aman, gs_id, products.dmt, 1, 1)).status_code == 409
    conn = as_admin(db_conn)
    with pytest.raises(DBAPIError, match="approved line correction"), conn.begin_nested():
        conn.execute(
            text("update public.gs_items set received_qty = 99 where id = :i"),
            {"i": lines[0]["id"]},
        )
    with pytest.raises(DBAPIError, match="cannot be added or removed"), conn.begin_nested():
        conn.execute(text("delete from public.gs_items where id = :i"), {"i": lines[0]["id"]})


async def test_categorize_validation(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
) -> None:
    gs_id = await itemizing_gs(client, storage, actors, masters)
    # AMD-08: the count cannot be submitted empty, and the category waits for the submitted count.
    res = await submit_counting(client, actors.aman, gs_id)
    assert res.status_code == 422 and res.json()["error"]["code"] == "ITEMS_REQUIRED"
    res = await categorize(client, actors.aman, gs_id, "RO", submit=False)
    assert res.status_code == 409 and res.json()["error"]["code"] == "COUNTING_NOT_SUBMITTED"
    await add_line(client, actors.aman, gs_id, products.dmt, 1, 1)
    res = await categorize(client, actors.aman, gs_id, "MIXED")
    assert res.status_code == 422 and "return_category" in res.json()["error"]["details"]
    res = await client.post(
        f"/api/v1/gs/{gs_id}/categorize", json={"category": "RO"}, headers=_auth(actors.aman)
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert (await categorize(client, actors.rm, gs_id, "RO")).status_code == 403


# --- CSR decision (BR-08, BR-09, G-03) -----------------------------------------------------------
async def csr_pending(
    client: AsyncClient,
    storage: FakeStorage,
    a: Actors,
    m: Masters,
    p: Products,
) -> tuple[str, list[dict[str, Any]]]:
    gs_id, lines = await gs_with_lines(
        client, storage, a, m, p, [(p.dmt, 100, 100), (p.prismatic, 20, 18)]
    )
    res = await categorize(client, a.aman, gs_id, "CSR")
    assert res.status_code == 200, res.text
    assert res.json()["state"]["goods_slip"]["status"] == "CSR_APPROVAL_PENDING"
    return gs_id, lines


async def test_csr_routes_to_rm_and_aman_cannot_decide(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    db_conn: Connection,
) -> None:
    gs_id, lines = await csr_pending(client, storage, actors, masters, products)
    assert open_tasks(db_conn, gs_id) == [
        {"step_code": "S1_CSR_APPROVAL", "role_code": "REPLACEMENT_MANAGER"}
    ]
    notes = fetch_all(
        db_conn,
        "select type, priority from public.notifications where user_id = :u and entity_id = :g",
        u=actors.rm_id,
        g=gs_id,
    )
    assert {"type": "CSR_APPROVAL_REQUIRED", "priority": "HIGH"} in notes
    # Stock is already inwarded while the decision is pending.
    assert balances(db_conn, gs_id) == {lines[0]["id"]: 100, lines[1]["id"]: 18}

    # Aman (no itemization.approve) cannot decide; nor can he categorise again.
    res = await decide(client, actors.aman, gs_id, "CSR_APPROVED")
    assert res.status_code == 403
    assert (await categorize(client, actors.aman, gs_id, "RO")).status_code == 409

    inbox = await client.get("/api/v1/csr-approvals/pending", headers=_auth(actors.rm))
    assert inbox.status_code == 200
    card = next(c for c in inbox.json() if c["goods_slip"]["id"] == gs_id)
    assert card["category_label"] == "Complete Sales Return"
    assert card["totals"]["received_qty"] == 118 and len(card["items"]) == 2
    assert {e["kind"] for e in card["evidence"]} == {"UNBOXING_VIDEO", "DOC_PHOTO"}
    assert {o["code"] for o in card["decision_options"]} == {"CSR_APPROVED", "CSR_REJECTED_TO_RO"}
    assert (
        await client.get("/api/v1/csr-approvals/pending", headers=_auth(actors.aman))
    ).status_code == 403


async def test_csr_approved_creates_csr_path_and_initiated_transfer(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    db_conn: Connection,
) -> None:
    gs_id, lines = await csr_pending(client, storage, actors, masters, products)
    res = await decide(client, actors.rm, gs_id, "CSR_APPROVED", "All 2 items, full qty")
    assert res.status_code == 200, res.text
    state = res.json()
    gs = state["goods_slip"]
    assert (gs["status"], gs["category_code"], gs["csr_commercial_path"]) == (
        "IN_PROCESS",
        "CSR",
        True,
    )
    assert state["current_decision"]["decision_code"] == "CSR_APPROVED"
    assert state["current_decision"]["decision_label"] == "Approved - Complete Sales Return"
    assert state["current_decision"]["is_admin_action"] is False
    (transfer,) = state["transfers"]
    assert transfer["status"] == "INITIATED" and transfer["transfer_no"].startswith("TRF/")
    assert transfer["with_packaging"] is True and transfer["stock_moved"] is False
    assert (transfer["from_location_code"], transfer["to_location_code"]) == (
        "INWARD_STAGING",
        "INTERMEDIATE_STORE",
    )
    assert sorted(ln["qty_sent"] for ln in transfer["lines"]) == [18, 100]
    # Proposal only: the stock stays in INWARD_STAGING until the P3-01 engine moves it.
    assert balances(db_conn, gs_id) == {lines[0]["id"]: 100, lines[1]["id"]: 18}
    assert open_tasks(db_conn, gs_id) == [
        {"step_code": "S2_HANDOVER", "role_code": "INWARD_VERIFIER"}
    ]
    hist = fetch_all(
        db_conn,
        "select to_status, step_code from public.gs_status_history where gs_id = :g "
        'order by "at" desc limit 1',
        g=gs_id,
    )
    assert hist == [{"to_status": "IN_PROCESS", "step_code": "S2_HANDOVER"}]

    # Decided once: a second decision is refused.
    res = await decide(client, actors.rm, gs_id, "CSR_REJECTED_TO_RO", "changed my mind")
    assert res.status_code == 409 and res.json()["error"]["code"] == "CSR_ALREADY_DECIDED"
    conn = as_admin(db_conn)
    with pytest.raises(DBAPIError, match="G-03"), conn.begin_nested():
        conn.execute(
            text(
                "update public.csr_approvals set decision_code = 'CSR_REJECTED_TO_RO' "
                "where gs_id = :g"
            ),
            {"g": gs_id},
        )


async def test_csr_rejected_converts_to_ro_with_history(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    db_conn: Connection,
) -> None:
    gs_id, _ = await csr_pending(client, storage, actors, masters, products)
    res = await decide(client, actors.rm, gs_id, "CSR_REJECTED_TO_RO")
    assert res.status_code == 422  # a reason is required
    res = await decide(client, actors.rm, gs_id, "CSR_REJECTED_TO_RO", "Two pieces are damaged")
    assert res.status_code == 200, res.text
    gs = res.json()["goods_slip"]
    assert (gs["status"], gs["category_code"], gs["original_category_code"]) == (
        "INSPECTION",
        "RO",
        "CSR",
    )
    assert gs["csr_commercial_path"] is False and res.json()["transfers"] == []
    hist = fetch_all(
        db_conn,
        "select from_status, to_status, reason from public.gs_status_history where gs_id = :g "
        'order by "at" desc limit 1',
        g=gs_id,
    )
    assert hist[0]["from_status"] == "CSR_APPROVAL_PENDING" and hist[0]["to_status"] == "INSPECTION"
    assert hist[0]["reason"].startswith("Manager rejected sales return")
    assert open_tasks(db_conn, gs_id) == [
        {"step_code": "S1_INSPECT", "role_code": "INWARD_VERIFIER"}
    ]
    notes = fetch_all(
        db_conn,
        "select type from public.notifications where user_id = :u and entity_id = :g",
        u=actors.aman_id,
        g=gs_id,
    )
    assert {"type": "CSR_DECIDED"} in notes


async def test_g03_no_advance_without_decision(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    db_conn: Connection,
    sahil: str,
) -> None:
    gs_id, _ = await csr_pending(client, storage, actors, masters, products)
    conn = as_admin(db_conn)
    for target in ("INSPECTION", "IN_PROCESS", "RM_REVIEW", "COMMERCIAL_RESOLUTION", "CLOSED"):
        with pytest.raises(DBAPIError, match="G-03"), conn.begin_nested():
            conn.execute(
                text("update public.goods_slips set status = :s where id = :g"),
                {"s": target, "g": gs_id},
            )
    # Converting to RO without a rejection, or deciding as a non-approver directly in the DB.
    with pytest.raises(DBAPIError, match="G-03"), conn.begin_nested():
        conn.execute(
            text("update public.goods_slips set category_code = 'RO' where id = :g"), {"g": gs_id}
        )
    with pytest.raises(DBAPIError, match="G-03"), conn.begin_nested():
        conn.execute(
            text(
                "insert into public.csr_approvals (gs_id, decision_code, decided_by) "
                "values (:g, 'CSR_APPROVED', :u)"
            ),
            {"g": gs_id, "u": actors.aman_id},
        )
    # Any Stage-2+ action on its goods via the API → 422 G-03.
    state = (await client.get(f"/api/v1/gs/{gs_id}/itemization", headers=_auth(actors.rm))).json()
    lot_id = state["lots"][0]["lot_id"]
    res = await client.post(
        f"/api/v1/lots/{lot_id}/packaging-check", json={"result": "OK"}, headers=_auth(sahil)
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "G-03"
    res = await client.post(
        f"/api/v1/lots/{lot_id}/packaging-check", json={"result": "OK"}, headers=_auth(actors.admin)
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "G-03"  # not bypassable


async def test_super_admin_decision_is_flagged_admin_action(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    db_conn: Connection,
) -> None:
    gs_id, _ = await csr_pending(client, storage, actors, masters, products)
    res = await decide(client, actors.admin, gs_id, "CSR_APPROVED")
    assert res.status_code == 200, res.text
    assert res.json()["current_decision"]["is_admin_action"] is True
    audit = fetch_all(
        db_conn,
        """select reason from public.audit_log
            where table_name = 'public.csr_approvals' and action = 'INSERT'
              and "new" ->> 'gs_id' = :g""",
        g=gs_id,
    )
    assert audit and audit[0]["reason"].startswith("ADMIN ACTION")


async def test_admin_reopen_decision(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    db_conn: Connection,
) -> None:
    gs_id, _ = await csr_pending(client, storage, actors, masters, products)
    assert (await decide(client, actors.rm, gs_id, "CSR_APPROVED")).status_code == 200
    url = f"/api/v1/gs/{gs_id}/csr-decision/reopen"
    res = await client.post(url, json={"reason": "Wrong GS"}, headers=_auth(actors.rm))
    assert res.status_code == 403
    res = await client.post(
        url, json={"reason": "Approved the wrong GS"}, headers=_auth(actors.admin)
    )
    assert res.status_code == 200, res.text
    state = res.json()
    assert state["goods_slip"]["status"] == "CSR_APPROVAL_PENDING"
    assert state["goods_slip"]["csr_commercial_path"] is False
    assert state["current_decision"] is None
    assert state["decisions"][0]["reopen_reason"] == "Approved the wrong GS"
    assert state["transfers"][0]["status"] == "CANCELLED"
    assert open_tasks(db_conn, gs_id) == [
        {"step_code": "S1_CSR_APPROVAL", "role_code": "REPLACEMENT_MANAGER"}
    ]

    # Decided again (reject), then the rejection is reopened back to CSR.
    res = await decide(client, actors.rm, gs_id, "CSR_REJECTED_TO_RO", "Mixed goods")
    assert res.status_code == 200 and res.json()["goods_slip"]["category_code"] == "RO"
    res = await client.post(url, json={"reason": "Reconsider"}, headers=_auth(actors.admin))
    assert res.status_code == 200, res.text
    gs = res.json()["goods_slip"]
    assert (gs["status"], gs["category_code"]) == ("CSR_APPROVAL_PENDING", "CSR")
    assert len(res.json()["decisions"]) == 2


# --- line corrections (RM approved, ADJUST) ------------------------------------------------------
async def test_line_correction_requires_rm_and_adjusts_stock(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    db_conn: Connection,
) -> None:
    gs_id, lines = await gs_with_lines(
        client, storage, actors, masters, products, [(products.dmt, 10, 8), (products.dmt, 2, 0)]
    )
    assert (await categorize(client, actors.aman, gs_id, "RO")).status_code == 200
    item = lines[0]["id"]
    url = f"/api/v1/gs/{gs_id}/items/{item}/corrections"
    res = await client.post(
        url,
        json={"documented_qty": 10, "received_qty": 9, "reason": "Recount"},
        headers=_auth(actors.aman),
    )
    assert res.status_code == 201, res.text
    corr = res.json()
    assert corr["status"] == "REQUESTED" and corr["old_received_qty"] == 8
    res = await client.post(
        url,
        json={"documented_qty": 10, "received_qty": 7, "reason": "Again"},
        headers=_auth(actors.aman),
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "CORRECTION_PENDING"

    decision_url = f"/api/v1/gs/{gs_id}/item-corrections/{corr['id']}/decision"
    res = await client.post(
        decision_url, json={"decision": "APPROVE"}, headers=_auth(actors.aman, key())
    )
    assert res.status_code == 403  # Aman cannot approve
    res = await client.post(
        decision_url, json={"decision": "REJECT"}, headers=_auth(actors.rm, key())
    )
    assert res.status_code == 422  # a reason is required
    res = await client.post(
        decision_url, json={"decision": "APPROVE"}, headers=_auth(actors.rm, key())
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "APPROVED" and res.json()["applied_at"]
    assert balances(db_conn, gs_id)[item] == 9
    adjust = fetch_all(
        db_conn,
        "select movement_type, qty, to_location_id is not null as inbound "
        "from public.stock_movements "
        "where idempotency_key = :k",
        k=f"{corr['id']}:adjust",
    )
    assert adjust == [{"movement_type": "ADJUST", "qty": 1, "inbound": True}]

    # Reduce below the original, and stock a line that had nothing received.
    for target_item, doc, recv, expected in ((item, 10, 6, 6), (lines[1]["id"], 2, 2, 2)):
        res = await client.post(
            f"/api/v1/gs/{gs_id}/items/{target_item}/corrections",
            json={"documented_qty": doc, "received_qty": recv, "reason": "Recount"},
            headers=_auth(actors.rm),
        )
        assert res.status_code == 201, res.text
        res = await client.post(
            f"/api/v1/gs/{gs_id}/item-corrections/{res.json()['id']}/decision",
            json={"decision": "APPROVE", "remarks": "ok"},
            headers=_auth(actors.rm, key()),
        )
        assert res.status_code == 200, res.text
        assert balances(db_conn, gs_id)[target_item] == expected
    audit = fetch_all(
        db_conn,
        """select reason from public.audit_log
            where table_name = 'public.gs_items' and action = 'UPDATE'
             and "new" ->> 'id' = :i""",
        i=item,
    )
    assert audit and all(a["reason"] == "Line correction: Recount" for a in audit)


# --- packaging check (WF r4, BR-10, DEC-27) ------------------------------------------------------
async def test_packaging_check_by_intermediate_store(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    sahil: str,
) -> None:
    gs_id, _ = await csr_pending(client, storage, actors, masters, products)
    state = (await decide(client, actors.rm, gs_id, "CSR_APPROVED")).json()
    lot = next(lt for lt in state["lots"] if lt["total_qty"] == 100)
    url = f"/api/v1/lots/{lot['lot_id']}/packaging-check"

    res = await client.post(url, json={"result": "OK"}, headers=_auth(sahil))
    assert res.status_code == 201, res.text
    assert (res.json()["result_code"], res.json()["qty_replaced"]) == ("OK", 0)
    res = await client.post(
        url,
        json={"result": "REPLACED", "qty_replaced": 3, "remarks": "Torn boxes"},
        headers=_auth(sahil),
    )
    assert res.status_code == 201 and res.json()["qty_replaced"] == 3
    for bad in (
        {"result": "REPLACED", "qty_replaced": 101},
        {"result": "REPLACED"},
        {"result": "OK", "qty_replaced": 2},
    ):
        res = await client.post(url, json=bad, headers=_auth(sahil))
        assert res.status_code == 422, bad
    # Aman (no inventory.edit) and the RM (not the store custodian) cannot record it.
    assert (
        await client.post(url, json={"result": "OK"}, headers=_auth(actors.aman))
    ).status_code == 403
    state = (await client.get(f"/api/v1/gs/{gs_id}/itemization", headers=_auth(actors.rm))).json()
    checks = next(lt for lt in state["lots"] if lt["lot_id"] == lot["lot_id"])["packaging_checks"]
    assert [c["result_code"] for c in checks] == ["OK", "REPLACED"]
    # Not blocking: the GS stays where it was.
    assert state["goods_slip"]["status"] == "IN_PROCESS"
