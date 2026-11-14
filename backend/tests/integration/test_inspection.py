"""Integration tests for Step-3 inspection and extraction reconciliation
(prompt P2-05; master plan §2.2, §3.2 DD r21-r43, BR-11..BR-17, G-04..G-07).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import get_session_factory
from app.core.middleware import limiter
from app.modules.inventory import ledger_service
from app.shared.storage import get_storage
from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, build_test_app
from tests.integration.test_gate_inward import Masters, _auth
from tests.integration.test_itemization import add_line, categorize, key
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


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
async def client(session_factory: sessionmaker[Session], storage: FakeStorage) -> Any:
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
class TriProducts:
    dmt: str
    prismatic: str
    eo: str


@pytest.fixture
def tri_products(db_conn: Connection) -> TriProducts:
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

    return TriProducts(dmt=make("DMT"), prismatic=make("PRISMATIC"), eo=make("ENCLOSED_OVAL"))


async def inspection_ready_gs(
    client: AsyncClient,
    storage: FakeStorage,
    a: Actors,
    m: Masters,
    prod_items: list[tuple[str, int, int]],  # (product_id, doc_qty, recv_qty)
) -> str:
    """Creates a GS, walks it through Gate and Unboxing to Itemization, and categorizes as RO."""
    gs_id = await started_gs(client, a, m)
    await upload_videos(client, storage, a.aman, gs_id)
    photo = await upload(client, storage, a.aman, gs_id, "DOC_PHOTO", "image/jpeg")
    assert (await classify(client, a.aman, gs_id, photo["id"], INVOICE)).status_code == 201
    assert (await complete(client, a.aman, gs_id)).status_code == 200

    for prod_id, doc_qty, recv_qty in prod_items:
        res = await add_line(client, a.aman, gs_id, prod_id, doc_qty, recv_qty)
        assert res.status_code == 201, res.text

    cat_res = await categorize(client, a.aman, gs_id, "RO")
    assert cat_res.status_code == 200, cat_res.text
    return gs_id


@pytest.mark.asyncio
async def test_condition_catalog_exact_counts(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    tri_products: TriProducts,
) -> None:
    """DMT has exactly 8 statuses, Prismatic 3, Enclosed Oval 4 (labels verbatim from DB)."""
    gs_id = await inspection_ready_gs(
        client,
        storage,
        actors,
        masters,
        [(tri_products.dmt, 10, 10), (tri_products.prismatic, 5, 5), (tri_products.eo, 8, 8)],
    )

    res = await client.get(f"/api/v1/gs/{gs_id}/inspection", headers=_auth(actors.aman))
    assert res.status_code == 200, res.text
    data = res.json()
    assert len(data["lines"]) == 3

    lines_by_cat = {line["category_code"]: line for line in data["lines"]}

    # DMT: exactly 8 statuses
    dmt_opts = lines_by_cat["DMT"]["condition_options"]
    assert len(dmt_opts) == 8
    dmt_codes = {o["code"] for o in dmt_opts}
    assert dmt_codes == {
        "DMT_OK_PACKED",
        "DMT_OK_PKG_DAMAGED",
        "DMT_OTHER_BRANDS",
        "DMT_SHORT_QTY",
        "DMT_SCRATCHED",
        "DMT_DIRTY",
        "DMT_BROKEN_BODY",
        "DMT_DISPLAY_ISSUE",
    }
    # Verbatim labels check from DB
    opt_labels = {o["code"]: o["label"] for o in dmt_opts}
    assert opt_labels["DMT_OK_PACKED"] == "VISUALLY OKAY and PACKED"
    assert opt_labels["DMT_OTHER_BRANDS"] == "OTHER BRANDS"
    assert opt_labels["DMT_BROKEN_BODY"] == "BROKEN / BODY DAMAGE"

    # PRISMATIC: exactly 3 statuses
    prs_opts = lines_by_cat["PRISMATIC"]["condition_options"]
    assert len(prs_opts) == 3
    prs_codes = {o["code"] for o in prs_opts}
    assert prs_codes == {"PRS_OK", "PRS_BULB_BROKEN_NO_HG", "PRS_BROKEN_WITH_HG"}

    # ENCLOSED_OVAL: exactly 4 statuses
    eo_opts = lines_by_cat["ENCLOSED_OVAL"]["condition_options"]
    assert len(eo_opts) == 4
    eo_codes = {o["code"] for o in eo_opts}
    assert eo_codes == {
        "EO_OK",
        "EO_INNER_CAPILLARY_BROKEN",
        "EO_BODY_BROKEN_HG",
        "EO_BULB_BROKEN_NO_HG",
    }


@pytest.mark.asyncio
async def test_g06_enclosed_oval_guard(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    tri_products: TriProducts,
) -> None:
    """An EO line cannot be graded without full opening confirmed (G-06, BR-14)."""
    gs_id = await inspection_ready_gs(client, storage, actors, masters, [(tri_products.eo, 10, 10)])
    insp_res = await client.get(f"/api/v1/gs/{gs_id}/inspection", headers=_auth(actors.aman))
    eo_line = insp_res.json()["lines"][0]
    gs_item_id = eo_line["gs_item_id"]

    # 1. Attempt to save condition allocations with full_opening_confirmed=False -> 422 G-06
    fail_res = await client.put(
        f"/api/v1/gs-items/{gs_item_id}/inspection",
        json={
            "full_opening_confirmed": False,
            "allocations": [{"condition_code": "EO_OK", "qty": 10}],
            "extraction": {
                "primary_type": "PACKAGING_EXTRACTED",
                "packaging_qty": 10,
                "container_qty": 0,
            },
        },
        headers=_auth(actors.aman),
    )
    assert fail_res.status_code in (409, 422), fail_res.text
    err = fail_res.json()
    assert "G-06" in (err.get("guard") or err.get("message", "") or str(err))

    # 2. Saving with full_opening_confirmed=True succeeds
    ok_res = await client.put(
        f"/api/v1/gs-items/{gs_item_id}/inspection",
        json={
            "full_opening_confirmed": True,
            "allocations": [{"condition_code": "EO_OK", "qty": 10}],
            "extraction": {
                "primary_type": "PACKAGING_EXTRACTED",
                "packaging_qty": 10,
                "container_qty": 0,
            },
        },
        headers=_auth(actors.aman),
    )
    assert ok_res.status_code == 200, ok_res.text
    assert ok_res.json()["full_opening_confirmed"] is True


@pytest.mark.asyncio
async def test_g07_sum_and_extraction_reconciliation_guards(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    tri_products: TriProducts,
) -> None:
    """Finalise fails when condition sum != received_qty or extraction != target (G-07)."""
    gs_id = await inspection_ready_gs(
        client, storage, actors, masters, [(tri_products.dmt, 10, 10)]
    )
    insp_res = await client.get(f"/api/v1/gs/{gs_id}/inspection", headers=_auth(actors.aman))
    gs_item_id = insp_res.json()["lines"][0]["gs_item_id"]

    # 1. Condition sum = 8 (< 10)
    await client.put(
        f"/api/v1/gs-items/{gs_item_id}/inspection",
        json={
            "full_opening_confirmed": True,
            "allocations": [{"condition_code": "DMT_OK_PACKED", "qty": 8}],
            "extraction": {
                "primary_type": "PACKAGING_EXTRACTED",
                "packaging_qty": 10,
                "container_qty": 0,
            },
        },
        headers=_auth(actors.aman),
    )
    res_fail1 = await client.post(
        f"/api/v1/gs-items/{gs_item_id}/inspection/finalise",
        headers=_auth(actors.aman, key()),
    )
    assert res_fail1.status_code in (409, 422), res_fail1.text
    assert "G-07" in str(res_fail1.json())

    # 2. Condition sum = 10, but extraction sum = 7 (!= 10)
    await client.put(
        f"/api/v1/gs-items/{gs_item_id}/inspection",
        json={
            "full_opening_confirmed": True,
            "allocations": [
                {"condition_code": "DMT_OK_PACKED", "qty": 7},
                {"condition_code": "DMT_DIRTY", "qty": 3},
            ],
            "extraction": {
                "primary_type": "CONTAINER_EXTRACTED",
                "packaging_qty": 0,
                "container_qty": 7,
            },
        },
        headers=_auth(actors.aman),
    )
    res_fail2 = await client.post(
        f"/api/v1/gs-items/{gs_item_id}/inspection/finalise",
        headers=_auth(actors.aman, key()),
    )
    assert res_fail2.status_code in (409, 422), res_fail2.text
    assert "G-07" in str(res_fail2.json())

    # 3. DMT_SHORT_QTY does NOT consume received pieces (DEC-09):
    # Graded allocations: 7 OK + 3 DIRTY = 10. SHORT_QTY = 2 (discrepancy only). Extraction = 10.
    await client.put(
        f"/api/v1/gs-items/{gs_item_id}/inspection",
        json={
            "full_opening_confirmed": True,
            "allocations": [
                {"condition_code": "DMT_OK_PACKED", "qty": 7},
                {"condition_code": "DMT_DIRTY", "qty": 3},
                {"condition_code": "DMT_SHORT_QTY", "qty": 2},
            ],
            "extraction": {
                "primary_type": "PACKAGING_EXTRACTED",
                "packaging_qty": 8,
                "container_qty": 2,
            },
        },
        headers=_auth(actors.aman),
    )
    res_ok = await client.post(
        f"/api/v1/gs-items/{gs_item_id}/inspection/finalise",
        headers=_auth(actors.aman, key()),
    )
    assert res_ok.status_code == 200, res_ok.text
    assert res_ok.json()["status"] == "FINAL"


@pytest.mark.asyncio
async def test_hazard_segregation_and_alerts(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    tri_products: TriProducts,
    session_factory: sessionmaker[Session],
) -> None:
    """Mercury hazard pieces quarantined in HAZARD_QUARANTINE, and alert sent."""
    gs_id = await inspection_ready_gs(
        client, storage, actors, masters, [(tri_products.prismatic, 10, 10)]
    )
    insp_res = await client.get(f"/api/v1/gs/{gs_id}/inspection", headers=_auth(actors.aman))
    gs_item_id = insp_res.json()["lines"][0]["gs_item_id"]

    # Grade 8 OK, 2 BROKEN WITH MERCURY (HAZARD)
    draft_res = await client.put(
        f"/api/v1/gs-items/{gs_item_id}/inspection",
        json={
            "full_opening_confirmed": True,
            "allocations": [
                {"condition_code": "PRS_OK", "qty": 8},
                {"condition_code": "PRS_BROKEN_WITH_HG", "qty": 2},
            ],
            "extraction": {
                "primary_type": "PACKAGING_EXTRACTED",
                "packaging_qty": 10,
                "container_qty": 0,
            },
        },
        headers=_auth(actors.aman),
    )
    assert draft_res.status_code == 200

    fin_res = await client.post(
        f"/api/v1/gs-items/{gs_item_id}/inspection/finalise",
        headers=_auth(actors.aman, key()),
    )
    assert fin_res.status_code == 200, fin_res.text
    fin_data = fin_res.json()
    assert len(fin_data["rejections"]) == 1
    assert fin_data["rejections"][0]["disposition"] == "HAZARD_QUARANTINE"
    assert fin_data["rejections"][0]["hazard"] is True

    # Check database ledger state
    with session_factory() as session:
        # Check GS flags
        gs = (
            session.execute(
                text("select has_hazard, has_rejections from public.goods_slips where id = :id"),
                {"id": gs_id},
            )
            .mappings()
            .one()
        )
        assert gs["has_hazard"] is True
        assert gs["has_rejections"] is True

        # Check stock balances: hazard lot should be in HAZARD_QUARANTINE
        q_hazard = (
            "select id from public.stock_lots where gs_item_id = :id and condition_class = 'HAZARD'"
        )
        hazard_lot = session.execute(text(q_hazard), {"id": gs_item_id}).scalar_one()
        hazard_loc = session.execute(
            text("select id from public.inventory_locations where code = 'HAZARD_QUARANTINE'")
        ).scalar_one()
        intermediate_loc = session.execute(
            text("select id from public.inventory_locations where code = 'INTERMEDIATE_STORE'")
        ).scalar_one()

        bal = ledger_service.get_balance(session, hazard_lot, hazard_loc)
        assert bal == 2

        # DOWNSTREAM GUARD CHECK: Moving hazard lot to INTERMEDIATE_STORE must fail G-04/G-05
        with pytest.raises(Exception) as exc_info:
            ledger_service.move_stock(
                session,
                lot_id=hazard_lot,
                from_location_id=hazard_loc,
                to_location_id=intermediate_loc,
                qty=1,
                movement_type="TRANSFER_OUT",
                idempotency_key=key(),
            )
        assert any(g in str(exc_info.value) for g in ("G-04", "G-05"))
        session.rollback()

        # Notification check: verify Pratham (RM) has a high-priority hazard notification
        q_notif = (
            "select count(*) from public.notifications "
            "where priority = 'HIGH' and type = 'MERCURY_HAZARD_ALERT'"
        )
        notifs = session.execute(text(q_notif)).scalar_one()
        assert notifs >= 1


@pytest.mark.asyncio
async def test_dispositions_and_routing_table(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    tri_products: TriProducts,
    session_factory: sessionmaker[Session],
) -> None:
    """Test lot reclassification, dispositions and condition routing table."""
    # 1. DMT with Other Brands (3 pcs) + Broken Body (2 pcs) + OK Packed (5 pcs)
    gs_id = await inspection_ready_gs(
        client,
        storage,
        actors,
        masters,
        [(tri_products.dmt, 10, 10), (tri_products.eo, 6, 6)],
    )
    insp_res = await client.get(f"/api/v1/gs/{gs_id}/inspection", headers=_auth(actors.aman))
    dmt_item_id = insp_res.json()["lines"][0]["gs_item_id"]
    eo_item_id = insp_res.json()["lines"][1]["gs_item_id"]

    await client.put(
        f"/api/v1/gs-items/{dmt_item_id}/inspection",
        json={
            "full_opening_confirmed": True,
            "allocations": [
                {"condition_code": "DMT_OK_PACKED", "qty": 5},
                {"condition_code": "DMT_OTHER_BRANDS", "qty": 3},
                {"condition_code": "DMT_BROKEN_BODY", "qty": 2},
            ],
            "extraction": {
                "primary_type": "PACKAGING_EXTRACTED",
                "packaging_qty": 5,
                "container_qty": 5,
            },
        },
        headers=_auth(actors.aman),
    )
    fin_dmt = await client.post(
        f"/api/v1/gs-items/{dmt_item_id}/inspection/finalise",
        headers=_auth(actors.aman, key()),
    )
    assert fin_dmt.status_code == 200, fin_dmt.text

    # 2. EO with Inner Capillary Broken (2 pcs) + OK (4 pcs)
    await client.put(
        f"/api/v1/gs-items/{eo_item_id}/inspection",
        json={
            "full_opening_confirmed": True,
            "allocations": [
                {"condition_code": "EO_OK", "qty": 4},
                {"condition_code": "EO_INNER_CAPILLARY_BROKEN", "qty": 2},
            ],
            "extraction": {
                "primary_type": "PACKAGING_EXTRACTED",
                "packaging_qty": 6,
                "container_qty": 0,
            },
        },
        headers=_auth(actors.aman),
    )
    fin_eo = await client.post(
        f"/api/v1/gs-items/{eo_item_id}/inspection/finalise",
        headers=_auth(actors.aman, key()),
    )
    assert fin_eo.status_code == 200, fin_eo.text
    assert fin_eo.json()["is_gs_finalised"] is True
    assert fin_eo.json()["next_status"] == "RM_REVIEW"

    # Verify stock locations and flags in DB
    with session_factory() as session:
        rejected_loc = session.execute(
            text("select id from public.inventory_locations where code = 'REJECTED_HOLD'")
        ).scalar_one()
        non_func_loc = session.execute(
            text("select id from public.inventory_locations where code = 'NON_FUNCTIONAL_STORE'")
        ).scalar_one()

        # Other brands in REJECTED_HOLD
        q_ob = (
            "select id from public.stock_lots "
            "where gs_item_id = :id and source_condition_code = 'DMT_OTHER_BRANDS'"
        )
        ob_lot = session.execute(text(q_ob), {"id": dmt_item_id}).scalar_one()
        assert ledger_service.get_balance(session, ob_lot, rejected_loc) == 3

        # Broken body in NON_FUNCTIONAL_STORE
        q_bb = (
            "select id from public.stock_lots "
            "where gs_item_id = :id and source_condition_code = 'DMT_BROKEN_BODY'"
        )
        bb_lot = session.execute(text(q_bb), {"id": dmt_item_id}).scalar_one()
        assert ledger_service.get_balance(session, bb_lot, non_func_loc) == 2

        # EO Inner Capillary Broken has requires_evaluation=True and routing_hint='EVALUATE'
        q_eo = (
            "select requires_evaluation, routing_hint from public.stock_lots "
            "where gs_item_id = :id and source_condition_code = 'EO_INNER_CAPILLARY_BROKEN'"
        )
        eo_cap_lot = session.execute(text(q_eo), {"id": eo_item_id}).mappings().one()
        assert eo_cap_lot["requires_evaluation"] is True
        assert eo_cap_lot["routing_hint"] == "EVALUATE"


@pytest.mark.asyncio
async def test_reopen_inspection_with_compensating_movements(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    tri_products: TriProducts,
    session_factory: sessionmaker[Session],
) -> None:
    """Reopening an inspection reverses movements and returns GS to INSPECTION."""
    gs_id = await inspection_ready_gs(
        client, storage, actors, masters, [(tri_products.dmt, 10, 10)]
    )
    insp_res = await client.get(f"/api/v1/gs/{gs_id}/inspection", headers=_auth(actors.aman))
    gs_item_id = insp_res.json()["lines"][0]["gs_item_id"]

    await client.put(
        f"/api/v1/gs-items/{gs_item_id}/inspection",
        json={
            "full_opening_confirmed": True,
            "allocations": [
                {"condition_code": "DMT_OK_PACKED", "qty": 7},
                {"condition_code": "DMT_OTHER_BRANDS", "qty": 3},
            ],
            "extraction": {
                "primary_type": "PACKAGING_EXTRACTED",
                "packaging_qty": 10,
                "container_qty": 0,
            },
        },
        headers=_auth(actors.aman),
    )
    fin_res = await client.post(
        f"/api/v1/gs-items/{gs_item_id}/inspection/finalise",
        headers=_auth(actors.aman, key()),
    )
    assert fin_res.status_code == 200
    assert fin_res.json()["next_status"] == "RM_REVIEW"

    # Aman (verifier) cannot reopen -> 403
    fail_reopen = await client.post(
        f"/api/v1/gs-items/{gs_item_id}/inspection/reopen",
        json={"reason": "Need to re-grade"},
        headers=_auth(actors.aman),
    )
    assert fail_reopen.status_code == 403

    # Pratham (RM) reopens with valid reason -> 200
    ok_reopen = await client.post(
        f"/api/v1/gs-items/{gs_item_id}/inspection/reopen",
        json={"reason": "Party clarified brand origin; reopening line for re-check"},
        headers=_auth(actors.rm),
    )
    assert ok_reopen.status_code == 200, ok_reopen.text
    assert ok_reopen.json()["status"] == "DRAFT"

    # Check that GS transitioned back to INSPECTION
    with session_factory() as session:
        gs = session.execute(
            text("select status from public.goods_slips where id = :id"),
            {"id": gs_id},
        ).scalar_one()
        assert gs == "INSPECTION"

        inward_loc = session.execute(
            text("select id from public.inventory_locations where code = 'INWARD_STAGING'")
        ).scalar_one()
        q_init = (
            "select id from public.stock_lots "
            "where gs_item_id = :id and source_condition_code is null"
        )
        initial_lot = session.execute(text(q_init), {"id": gs_item_id}).scalar_one()

        # Balance should be returned to initial lot
        bal = ledger_service.get_balance(session, initial_lot, inward_loc)
        assert bal == 10
