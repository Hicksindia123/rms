"""Integration tests for Phase 5 (AMD-08, AMD-09, AMD-11, AMD-12, AMD-13, G-19).

1. Categorisation (INWARD_VERIFIER, same user who counted): per item, the resolved categorisation
   buckets as qty inputs + Packaging / Container / User Manual counts.
   Guard G-19: sum(bucket qty) = counted qty per item.
2. RM Review (REPLACEMENT_MANAGER): one-screen GS at a glance — header, documents, cartons/videos,
   every item with counted qty and qty per bucket; RM can approve, edit any qty/bucket/item
   (audit + revision kept), or send back with a remark.
3. On approval: auto-generate a Transfer Slip (TRF/...) handing goods to INTERMEDIATE_STORE_MANAGER.
4. Intermediate store accepts the transfer (qty check per line)
   -> GS status "HELD_AT_INTERMEDIATE_STORE".
   All stock moves via rms_move_stock, idempotent.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import get_session_factory
from app.core.middleware import limiter
from app.shared.storage import get_storage
from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, build_test_app
from tests.integration.test_gate_inward import Masters, _auth
from tests.integration.test_itemization import (
    Actors,
    FakeStorage,
    Products,
    add_line,
    itemizing_gs,
    key,
    submit_counting,
)


# --- fixtures ------------------------------------------------------------------------------------
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


@pytest.fixture
def products(db_conn: Connection) -> Products:
    c = as_admin(db_conn)
    tag = uuid.uuid4().hex[:6].upper()

    # Enable ITEM_COUNT fields for DMT category so Packaging/Container/User Manual counts work
    c.execute(
        text(
            """
            insert into public.item_field_assignments (
                field_id, field_group, scope_type, category_id, is_included
            )
            select l.id, l.field_group, 'CATEGORY', c.id, true
              from public.item_field_library l
              join public.product_categories c on c.code = 'DMT'
             where l.field_group = 'ITEM_COUNT'
            on conflict do nothing
            """
        )
    )

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
def other_verifier(users: UserFactory, make_token: JwtFactory) -> str:
    """Another inward verifier (not the one who counted)."""
    return make_token(users.create(roles=["INWARD_VERIFIER"], full_name="Other Verifier"))


@pytest.fixture
def sahil(users: UserFactory, make_token: JwtFactory) -> str:
    """Intermediate Store Manager."""
    return make_token(users.create(roles=["INTERMEDIATE_STORE_MANAGER"], full_name="Sahil"))


@pytest.mark.asyncio
async def test_categorisation_any_verifier_and_g19_conservation(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    other_verifier: str,
    masters: Masters,
    products: Products,
) -> None:
    """AMD-08 / AMD-11 / G-19:
    - DEC-51: any eligible verifier may categorise (not only the one who counted).
    - G-19: sum(bucket qty) must equal received_qty; mismatch returns G-19 violation.
    - Conserved submit transitions GS to RM_REVIEW and creates revision 1 (SUBMITTED).
    """
    gs_id = await itemizing_gs(client, storage, actors, masters)
    add_res = await add_line(client, actors.aman, gs_id, products.dmt, doc=10, recv=10)
    assert add_res.status_code == 201, add_res.text
    item_id = add_res.json()["id"]

    # Submit counting -> moves to CATEGORISATION, records counted_by = Aman
    count_sub = await submit_counting(client, actors.aman, gs_id)
    assert count_sub.status_code == 200, count_sub.text
    assert count_sub.json()["goods_slip"]["status"] == "CATEGORISATION"

    # Get categorisation state
    cat_state_res = await client.get(
        f"/api/v1/gs/{gs_id}/categorisation",
        headers=_auth(actors.aman),
    )
    assert cat_state_res.status_code == 200, cat_state_res.text
    cat_data = cat_state_res.json()
    assert cat_data["status"] == "CATEGORISATION"
    assert cat_data["is_same_user_who_counted"] is True
    assert cat_data["all_conserved"] is False
    assert len(cat_data["items"]) == 1
    allowed_buckets = cat_data["items"][0]["allowed_buckets"]
    assert len(allowed_buckets) > 0
    bucket_code = allowed_buckets[0]["field_code"]

    # DEC-51: another eligible verifier may categorise a GS counted by Aman (no same-user lock).
    other_state = await client.get(
        f"/api/v1/gs/{gs_id}/categorisation", headers=_auth(other_verifier)
    )
    assert other_state.status_code == 200, other_state.text
    assert other_state.json()["is_same_user_who_counted"] is False  # informational only
    other_save = await client.put(
        f"/api/v1/gs/{gs_id}/items/{item_id}/categorisation",
        json={"buckets": [{"field_code": bucket_code, "qty": 3}], "counts": []},
        headers=_auth(other_verifier, key()),
    )
    assert other_save.status_code == 200, other_save.text

    # Aman saves partial bucket quantity (5 out of 10) -> total != 10
    save_res = await client.put(
        f"/api/v1/gs/{gs_id}/items/{item_id}/categorisation",
        json={
            "buckets": [{"field_code": bucket_code, "qty": 5}],
            "counts": [{"count_type": "PACKAGING", "count_value": 10}],
        },
        headers=_auth(actors.aman, key()),
    )
    assert save_res.status_code == 200, save_res.text

    # Aman attempts to submit categorisation with mismatch (5 != 10) -> G-19 violation
    sub_mismatch = await client.post(
        f"/api/v1/gs/{gs_id}/categorisation/submit",
        json={"category_code": "REGULAR_RETURN"},
        headers=_auth(actors.aman, key()),
    )
    assert sub_mismatch.status_code in (409, 422), sub_mismatch.text
    err_body = sub_mismatch.json()
    assert "G-19" in str(err_body)

    # Aman fixes bucket quantity: 10 out of 10
    save_fixed = await client.put(
        f"/api/v1/gs/{gs_id}/items/{item_id}/categorisation",
        json={
            "buckets": [{"field_code": bucket_code, "qty": 10}],
            "counts": [{"count_type": "PACKAGING", "count_value": 10}],
        },
        headers=_auth(actors.aman, key()),
    )
    assert save_fixed.status_code == 200, save_fixed.text

    # DEC-51: the other verifier submits the GS Aman counted -> SUCCESS, moves to RM_REVIEW
    sub_ok = await client.post(
        f"/api/v1/gs/{gs_id}/categorisation/submit",
        json={"category_code": "REGULAR_RETURN", "remarks": "Counted by Aman, sorted by Other"},
        headers=_auth(other_verifier, key()),
    )
    assert sub_ok.status_code == 200, sub_ok.text
    assert sub_ok.json()["status"] == "RM_REVIEW"


@pytest.mark.asyncio
async def test_rm_review_one_screen_edit_send_back_and_approval_flow(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    sahil: str,
    masters: Masters,
    products: Products,
) -> None:
    """AMD-12 / AMD-13:
    1. RM Review one-screen GET returns GS at a glance
       (header, docs, carton videos, items with buckets).
    2. RM can edit item quantities/buckets (enforcing G-19, records RM_EDIT revision).
    3. RM can send back to CATEGORISATION with a remark (records RM_SENT_BACK revision).
    4. Resubmitted by inward verifier -> back to RM_REVIEW.
    5. RM approves: auto-generates Transfer Slip (TRF/...) handing goods to INTERMEDIATE_STORE.
    6. Intermediate Store Manager accepts transfer
       -> GS status becomes "HELD_AT_INTERMEDIATE_STORE".
    """
    gs_id = await itemizing_gs(client, storage, actors, masters)
    add_res = await add_line(client, actors.aman, gs_id, products.dmt, doc=8, recv=8)
    assert add_res.status_code == 201, add_res.text
    item_id = add_res.json()["id"]

    await submit_counting(client, actors.aman, gs_id)

    cat_state = (
        await client.get(f"/api/v1/gs/{gs_id}/categorisation", headers=_auth(actors.aman))
    ).json()
    bucket_code = cat_state["items"][0]["allowed_buckets"][0]["field_code"]

    # Save 8 to bucket
    await client.put(
        f"/api/v1/gs/{gs_id}/items/{item_id}/categorisation",
        json={"buckets": [{"field_code": bucket_code, "qty": 8}], "counts": []},
        headers=_auth(actors.aman, key()),
    )

    # Submit categorisation -> RM_REVIEW
    sub_init = await client.post(
        f"/api/v1/gs/{gs_id}/categorisation/submit",
        json={"category_code": "REGULAR_RETURN", "remarks": "Initial submission"},
        headers=_auth(actors.aman, key()),
    )
    assert sub_init.status_code == 200, sub_init.text

    # 1. RM views one-screen GS at a glance
    rm_view = await client.get(
        f"/api/v1/gs/{gs_id}/rm-review",
        headers=_auth(actors.rm),
    )
    assert rm_view.status_code == 200, rm_view.text
    data = rm_view.json()
    assert data["goods_slip"]["status"] == "RM_REVIEW"
    assert len(data["items"]) == 1
    assert data["items"][0]["received_qty"] == 8
    assert data["items"][0]["is_conserved"] is True
    assert len(data["revisions"]) >= 1
    assert data["revisions"][0]["action"] == "SUBMITTED"

    # 2. RM edits item line: sets received_qty = 6, bucket = 6
    edit_res = await client.put(
        f"/api/v1/gs/{gs_id}/items/{item_id}/rm-edit",
        json={
            "documented_qty": 8,
            "received_qty": 6,
            "buckets": [{"field_code": bucket_code, "qty": 6}],
            "remarks": "RM adjusted count from 8 to 6 due to 2 items belonging to another batch",
        },
        headers=_auth(actors.rm, key()),
    )
    assert edit_res.status_code == 200, edit_res.text

    # Verify revision was recorded
    rm_view_after_edit = (
        await client.get(f"/api/v1/gs/{gs_id}/rm-review", headers=_auth(actors.rm))
    ).json()
    assert rm_view_after_edit["items"][0]["received_qty"] == 6
    assert rm_view_after_edit["items"][0]["total_bucket_qty"] == 6
    assert any(r["action"] == "RM_EDIT" for r in rm_view_after_edit["revisions"])

    # 3. RM sends back with remark
    send_back_res = await client.post(
        f"/api/v1/gs/{gs_id}/rm-send-back",
        json={"remarks": "Please verify packaging condition for remaining pieces"},
        headers=_auth(actors.rm, key()),
    )
    assert send_back_res.status_code == 200, send_back_res.text
    assert send_back_res.json()["status"] == "CATEGORISATION"

    # Inward verifier verifies status is CATEGORISATION
    gs_detail = (await client.get(f"/api/v1/gs/{gs_id}", headers=_auth(actors.aman))).json()
    assert gs_detail["goods_slip"]["status"] == "CATEGORISATION"

    # 4. Inward verifier resubmits categorisation -> moves back to RM_REVIEW
    resub_res = await client.post(
        f"/api/v1/gs/{gs_id}/categorisation/submit",
        json={"category_code": "REGULAR_RETURN", "remarks": "Packaging verified and approved"},
        headers=_auth(actors.aman, key()),
    )
    assert resub_res.status_code == 200, resub_res.text
    assert resub_res.json()["status"] == "RM_REVIEW"

    # 5. RM approves goods slip -> auto-generates custody transfer slip to INTERMEDIATE_STORE
    approve_res = await client.post(
        f"/api/v1/gs/{gs_id}/rm-approve",
        json={"remarks": "All pieces verified. Approved for Intermediate Store handover."},
        headers=_auth(actors.rm, key()),
    )
    assert approve_res.status_code == 200, approve_res.text
    app_data = approve_res.json()
    assert "transfer_id" in app_data
    assert "transfer_no" in app_data
    transfer_id = app_data["transfer_id"]
    transfer_no = app_data["transfer_no"]
    assert transfer_no.startswith("TRF/")

    # Check Transfer slip summary in RM Review
    rm_view_after_app = (
        await client.get(f"/api/v1/gs/{gs_id}/rm-review", headers=_auth(actors.rm))
    ).json()
    assert rm_view_after_app["transfer_slip"] is not None
    assert rm_view_after_app["transfer_slip"]["transfer_no"] == transfer_no
    assert rm_view_after_app["transfer_slip"]["to_location_code"] == "INTERMEDIATE_STORE"
    assert rm_view_after_app["transfer_slip"]["total_qty"] == 6

    # 6. Intermediate Store Manager accepts transfer
    # First get transfer lines to know the lot_id
    transfer_detail = (
        await client.get(f"/api/v1/custody/transfers/{transfer_id}", headers=_auth(sahil))
    ).json()
    lines_to_count = [
        {"lot_id": ln["lot_id"], "qty_counted": ln["qty_sent"]} for ln in transfer_detail["lines"]
    ]

    accept_res = await client.post(
        f"/api/v1/custody/transfers/{transfer_id}/accept",
        json={
            "lines": lines_to_count,
            "acceptance_code": "ACCEPTED_VERIFIED",
            "notes": "Count verified at intermediate store",
        },
        headers=_auth(sahil, key()),
    )
    assert accept_res.status_code == 200, accept_res.text
    assert accept_res.json()["status"] == "ACCEPTED"

    # Verify GS status is now "HELD_AT_INTERMEDIATE_STORE" (AMD-13)
    final_gs = (await client.get(f"/api/v1/gs/{gs_id}", headers=_auth(actors.rm))).json()
    assert final_gs["goods_slip"]["status"] == "HELD_AT_INTERMEDIATE_STORE"


# --- categorisation API contract (regression: `allowed_counts is not iterable`) ------------------
# The screen iterates allowed_buckets / allowed_counts / buckets / counts of every item. The GET
# must always return them as lists with the documented field names, and the save endpoint must
# accept exactly the codes the GET offers (AMD-09 / AMD-11 / Phase 4 profile resolution).

RESOLVED_FIELD_KEYS = {"field_id", "field_code", "field_label", "sort_order"}


@pytest.fixture
def eo_product(db_conn: Connection) -> dict[str, str]:
    """An Enclosed Oval product (the category of ITM-00180) without an ITEM_COUNT assignment."""
    c = as_admin(db_conn)
    tag = uuid.uuid4().hex[:6].upper()
    row = (
        c.execute(
            text(
                """insert into public.products (code, name, category_id)
                   select :code, :name, id from public.product_categories
                    where code = 'ENCLOSED_OVAL'
                   returning id, code, name"""
            ),
            {"code": f"T-EO-{tag}", "name": f"Test Enclosed Oval Thermometer {tag}"},
        )
        .mappings()
        .one()
    )
    return {"id": str(row["id"]), "code": row["code"], "name": row["name"]}


def _profile_codes(db_conn: Connection, product_id: str, group: str) -> list[str]:
    rows = db_conn.execute(
        text(
            "select code from rms_private.resolve_item_field_profile(cast(:p as uuid), null) "
            "where field_group = :g order by sort_order"
        ),
        {"p": product_id, "g": group},
    ).scalars()
    return list(rows)


def _library_codes(db_conn: Connection, group: str) -> list[str]:
    rows = db_conn.execute(
        text(
            "select code from public.item_field_library where field_group = :g and is_active "
            "order by sort_order, code"
        ),
        {"g": group},
    ).scalars()
    return list(rows)


def _assert_item_contract(it: dict[str, Any]) -> None:
    for key_ in ("allowed_buckets", "allowed_counts", "buckets", "counts"):
        assert isinstance(it[key_], list), f"{key_} must be a list, got {it[key_]!r}"
    for f in [*it["allowed_buckets"], *it["allowed_counts"]]:
        assert set(f) == RESOLVED_FIELD_KEYS, f
    for k in ("item_id", "line_no", "documented_qty", "received_qty", "sku_code", "sku_name"):
        assert it[k] not in (None, ""), k


async def _cat_state(client: AsyncClient, token: str, gs_id: str) -> dict[str, Any]:
    res = await client.get(f"/api/v1/gs/{gs_id}/categorisation", headers=_auth(token))
    assert res.status_code == 200, res.text
    data: dict[str, Any] = res.json()
    return data


async def _save(
    client: AsyncClient,
    token: str,
    gs_id: str,
    item_id: str,
    buckets: dict[str, int],
    counts: dict[str, int] | None = None,
) -> Response:
    return await client.put(
        f"/api/v1/gs/{gs_id}/items/{item_id}/categorisation",
        json={
            "buckets": [{"field_code": c, "qty": q} for c, q in buckets.items()],
            "counts": [{"count_type": c, "count_value": v} for c, v in (counts or {}).items()],
        },
        headers=_auth(token, key()),
    )


async def _submit(client: AsyncClient, token: str, gs_id: str) -> Response:
    return await client.post(
        f"/api/v1/gs/{gs_id}/categorisation/submit",
        json={"remarks": "categorised"},
        headers=_auth(token, key()),
    )


@pytest.mark.asyncio
async def test_categorisation_contract_exact_match_6_of_6(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    eo_product: dict[str, str],
    db_conn: Connection,
) -> None:
    """Scenario 1 (GS/2026-27/00001 shape): Enclosed Oval, documented 6, received 6.
    Counting completes and the categorisation state loads with every list the UI iterates."""
    gs_id = await itemizing_gs(client, storage, actors, masters)
    add = await add_line(client, actors.aman, gs_id, eo_product["id"], doc=6, recv=6)
    assert add.status_code == 201, add.text
    item_id = add.json()["id"]
    assert (await submit_counting(client, actors.aman, gs_id)).status_code == 200

    data = await _cat_state(client, actors.aman, gs_id)
    assert data["status"] == "CATEGORISATION"
    assert data["counted_by_name"] == "Aman"  # was always null (wrong column key)
    assert data["can_submit"] is True and data["all_conserved"] is False
    it = data["items"][0]
    _assert_item_contract(it)
    assert (it["line_no"], it["documented_qty"], it["received_qty"]) == (1, 6, 6)
    assert (it["sku_code"], it["sku_name"]) == (eo_product["code"], eo_product["name"])
    assert it["category_name"] == "ENCLOSED OVAL"
    # Buckets = the Enclosed Oval profile (Phase 4 resolver), not the whole library.
    bucket_codes = [b["field_code"] for b in it["allowed_buckets"]]
    assert bucket_codes == _profile_codes(db_conn, eo_product["id"], "CATEGORISATION")
    assert bucket_codes and all(c.startswith("EO_") for c in bucket_codes)
    # The Enclosed Oval profile enables no ITEM_COUNT field: allowed_counts is an empty LIST
    # (the DB guard G-18 would reject any count for this product, so none is offered).
    assert _profile_codes(db_conn, eo_product["id"], "ITEM_COUNT") == []
    assert _library_codes(db_conn, "ITEM_COUNT")  # the library has counts, but not enabled here
    assert it["allowed_counts"] == []

    # Every offered code is accepted by the save; codes the profile does not enable are refused
    # by the service with a clear 422 (before the DB guard would answer with a 409).
    first, second = bucket_codes[0], bucket_codes[1]
    saved = await _save(client, actors.aman, gs_id, item_id, {first: 4, second: 2})
    assert saved.status_code == 200, saved.text
    wrong = await _save(client, actors.aman, gs_id, item_id, {"DMT_OK_PACKED": 6})
    assert wrong.status_code == 422, wrong.text
    assert wrong.json()["error"]["code"] == "INVALID_FIELD"
    no_count = await _save(client, actors.aman, gs_id, item_id, {first: 6}, {"PACKAGING": 1})
    assert no_count.status_code == 422, no_count.text
    assert no_count.json()["error"]["code"] == "INVALID_COUNT_TYPE"

    data = await _cat_state(client, actors.aman, gs_id)
    it = data["items"][0]
    _assert_item_contract(it)
    assert it["total_bucket_qty"] == 6 and it["is_conserved"] is True  # rejected saves rolled back
    assert data["all_conserved"] is True
    assert it["counts"] == []

    sub = await _submit(client, actors.aman, gs_id)
    assert sub.status_code == 200, sub.text
    assert sub.json()["status"] == "RM_REVIEW"

    # RM review (next step) carries the same contract and real product names.
    rm = await client.get(f"/api/v1/gs/{gs_id}/rm-review", headers=_auth(actors.rm))
    assert rm.status_code == 200, rm.text
    rm_item = rm.json()["items"][0]
    assert rm_item["sku_name"] == eo_product["name"]
    assert rm_item["allowed_counts"] == []
    assert [b["field_code"] for b in rm_item["allowed_buckets"]] == bucket_codes
    assert rm.json()["revisions"][0]["items_snapshot"][0]["sku_code"] == eo_product["code"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("documented", "received"), [(6, 4), (6, 8)])
async def test_categorisation_partial_and_excess_conserve_the_received_qty(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    eo_product: dict[str, str],
    documented: int,
    received: int,
) -> None:
    """Scenarios 2 and 3: G-19 conserves against the physically received qty (BR / DEC-28),
    so the documented qty is neither required nor accepted as the bucket total."""
    gs_id = await itemizing_gs(client, storage, actors, masters)
    add = await add_line(client, actors.aman, gs_id, eo_product["id"], documented, received)
    assert add.status_code == 201, add.text
    item_id = add.json()["id"]
    assert (await submit_counting(client, actors.aman, gs_id)).status_code == 200

    it = (await _cat_state(client, actors.aman, gs_id))["items"][0]
    _assert_item_contract(it)
    assert (it["documented_qty"], it["received_qty"]) == (documented, received)
    code = it["allowed_buckets"][0]["field_code"]

    # Bucket total = documented qty is a G-19 violation (it is not what was counted).
    assert (await _save(client, actors.aman, gs_id, item_id, {code: documented})).status_code == 200
    rejected = await _submit(client, actors.aman, gs_id)
    assert rejected.status_code in (409, 422), rejected.text
    assert "G-19" in rejected.text
    assert f"Line 1 ({eo_product['code']})" in rejected.text

    assert (await _save(client, actors.aman, gs_id, item_id, {code: received})).status_code == 200
    ok = await _submit(client, actors.aman, gs_id)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "RM_REVIEW"


@pytest.mark.asyncio
async def test_categorisation_multi_product_gets_per_product_fields(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    eo_product: dict[str, str],
    db_conn: Connection,
) -> None:
    """Scenario 4: one GS with three products of different categories and quantities; each item
    gets its own profile's buckets and counts, and only those are accepted for that item."""
    gs_id = await itemizing_gs(client, storage, actors, masters)
    lines = [(products.dmt, 6, 6), (products.prismatic, 6, 4), (eo_product["id"], 6, 8)]
    ids = []
    for pid, d, r in lines:
        res = await add_line(client, actors.aman, gs_id, pid, d, r)
        assert res.status_code == 201, res.text
        ids.append(res.json()["id"])
    assert (await submit_counting(client, actors.aman, gs_id)).status_code == 200

    items = (await _cat_state(client, actors.aman, gs_id))["items"]
    assert [i["item_id"] for i in items] == ids
    assert [i["received_qty"] for i in items] == [6, 4, 8]
    for it, (pid, _d, _r) in zip(items, lines, strict=True):
        _assert_item_contract(it)
        assert [b["field_code"] for b in it["allowed_buckets"]] == _profile_codes(
            db_conn, pid, "CATEGORISATION"
        )
    dmt, prs, eo = items
    assert {b["field_code"] for b in dmt["allowed_buckets"]}.isdisjoint(
        {b["field_code"] for b in prs["allowed_buckets"]}
    )
    # DMT has ITEM_COUNT assigned on its category (fixture): its counts come from the profile.
    assert [c["field_code"] for c in dmt["allowed_counts"]] == _profile_codes(
        db_conn, products.dmt, "ITEM_COUNT"
    )

    # A DMT bucket on the Prismatic line is rejected (codes offered = codes accepted).
    dmt_code = dmt["allowed_buckets"][0]["field_code"]
    bad = await _save(client, actors.aman, gs_id, prs["item_id"], {dmt_code: 4})
    assert bad.status_code == 422, bad.text

    dmt_counts = {c["field_code"]: 2 for c in dmt["allowed_counts"]}
    assert dmt_counts, "fixture enables ITEM_COUNT on DMT"
    for it in items:
        code = it["allowed_buckets"][0]["field_code"]
        counts = dmt_counts if it is dmt else None
        res = await _save(
            client, actors.aman, gs_id, it["item_id"], {code: it["received_qty"]}, counts
        )
        assert res.status_code == 200, res.text
    data = await _cat_state(client, actors.aman, gs_id)
    assert data["all_conserved"] is True
    assert [i["total_bucket_qty"] for i in data["items"]] == [6, 4, 8]
    saved_counts = data["items"][0]["counts"]
    assert {c["count_type"]: c["count_value"] for c in saved_counts} == dmt_counts
    assert all(c["field_label"] for c in saved_counts)
    assert data["items"][1]["counts"] == [] and data["items"][2]["counts"] == []
    assert eo["item_id"] == data["items"][2]["item_id"]
    ok = await _submit(client, actors.aman, gs_id)
    assert ok.status_code == 200, ok.text
