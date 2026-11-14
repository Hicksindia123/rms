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

import pytest
from httpx import ASGITransport, AsyncClient
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
async def test_categorisation_same_user_guard_and_g19_conservation(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    other_verifier: str,
    masters: Masters,
    products: Products,
) -> None:
    """AMD-08 / AMD-11 / G-19:
    - Same user who counted can submit categorisation (other verifier gets 403).
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

    # Other verifier attempts to save categorisation -> 403
    other_save = await client.put(
        f"/api/v1/gs/{gs_id}/items/{item_id}/categorisation",
        json={"buckets": [{"field_code": bucket_code, "qty": 10}], "counts": []},
        headers=_auth(other_verifier, key()),
    )
    assert other_save.status_code == 403, other_save.text

    # Other verifier attempts to submit categorisation -> 403
    other_sub = await client.post(
        f"/api/v1/gs/{gs_id}/categorisation/submit",
        json={"category_code": "REGULAR_RETURN"},
        headers=_auth(other_verifier, key()),
    )
    assert other_sub.status_code == 403, other_sub.text

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

    # Aman submits categorisation -> SUCCESS, moves to RM_REVIEW
    sub_ok = await client.post(
        f"/api/v1/gs/{gs_id}/categorisation/submit",
        json={"category_code": "REGULAR_RETURN", "remarks": "Counted and sorted by Aman"},
        headers=_auth(actors.aman, key()),
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
