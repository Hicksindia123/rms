"""Integration tests for Step-3 a) RM item-wise actions, Pendency register & Replacement Slip.

Master plan references: WF r6, WF r7 col K, BR-19, BR-20, G-08, DEC-12, DEC-13, DEC-33.
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
from app.shared.storage import get_storage
from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, build_test_app
from tests.integration.test_gate_inward import Masters
from tests.integration.test_itemization import add_line, categorize
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


@pytest.fixture
def products(db_conn: Connection) -> TriProducts:
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
                {
                    "code": f"P-{category}-{tag}",
                    "name": f"Product {category} {tag}",
                    "cat": category,
                },
            ).scalar_one()
        )

    return TriProducts(dmt=make("DMT"), prismatic=make("PRISMATIC"))


async def rm_ready_gs(
    client: AsyncClient,
    storage: FakeStorage,
    a: Actors,
    m: Masters,
    prod_items: list[tuple[str, int, int]],  # (product_id, doc_qty, recv_qty)
) -> tuple[str, list[str]]:
    """Creates a GS, itemizes, inspects lines (some allowed/rejected), and moves to RM_REVIEW."""
    gs_id = await started_gs(client, a, m)
    await upload_videos(client, storage, a.aman, gs_id)
    photo = await upload(client, storage, a.aman, gs_id, "DOC_PHOTO", "image/jpeg")
    assert (await classify(client, a.aman, gs_id, photo["id"], INVOICE)).status_code == 201
    assert (await complete(client, a.aman, gs_id)).status_code == 200

    item_ids: list[str] = []
    for prod_id, doc_qty, recv_qty in prod_items:
        res = await add_line(client, a.aman, gs_id, prod_id, doc_qty, recv_qty)
        assert res.status_code == 201, res.text
        item_ids.append(res.json()["id"])

    cat_res = await categorize(client, a.aman, gs_id, "RO")
    assert cat_res.status_code == 200, cat_res.text

    return gs_id, item_ids


@pytest.mark.asyncio
async def test_rm_actions_get_and_option_catalogue(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: TriProducts,
) -> None:
    """1. GET /gs/{id}/rm-actions returns inspection breakdown, options & default allocations."""
    gs_id, item_ids = await rm_ready_gs(
        client,
        storage,
        actors,
        masters,
        [(products.dmt, 10, 10)],
    )

    # Inspect line: 8 OK, 2 broken body (not allowed)
    insp_res = await client.put(
        f"/api/v1/gs-items/{item_ids[0]}/inspection",
        headers={"Authorization": f"Bearer {actors.aman}"},
        json={
            "allocations": [
                {"condition_code": "DMT_OK_PACKED", "qty": 8},
                {"condition_code": "DMT_BROKEN_BODY", "qty": 2},
            ],
            "extraction": {
                "primary_type": "PACKAGING_EXTRACTED",
                "packaging_qty": 10,
                "container_qty": 0,
            },
        },
    )
    assert insp_res.status_code == 200, insp_res.text

    fin_res = await client.post(
        f"/api/v1/gs-items/{item_ids[0]}/inspection/finalise",
        headers={"Authorization": f"Bearer {actors.aman}"},
    )
    assert fin_res.status_code == 200, fin_res.text

    # Now GS is in RM_REVIEW
    get_res = await client.get(
        f"/api/v1/gs/{gs_id}/rm-actions",
        headers={"Authorization": f"Bearer {actors.rm}"},
    )
    assert get_res.status_code == 200, get_res.text
    data = get_res.json()

    assert data["gs_id"] == gs_id
    assert data["status"] == "RM_REVIEW"
    assert data["current_revision_no"] == 0
    assert len(data["options"]) == 5
    option_codes = [o["code"] for o in data["options"]]
    assert option_codes == ["SEND_NEW", "SEND_REPAIRED", "ISSUE_CN", "NOT_ALLOWED", "PENDING_BP"]

    assert len(data["lines"]) == 1
    line = data["lines"][0]
    assert line["received_qty"] == 10
    assert line["allowed_qty"] == 8
    assert line["not_allowed_qty"] == 2
    # Default current actions should pre-fill NOT_ALLOWED with 2
    cur_acts = {a["action_code"]: a["qty"] for a in line["current_actions"]}
    assert cur_acts["NOT_ALLOWED"] == 2


@pytest.mark.asyncio
async def test_rm_actions_reconciliation_and_dec33_override(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: TriProducts,
) -> None:
    """2. PUT /gs/{id}/rm-actions enforces sum == received_qty (BR-19) and DEC-33 override."""
    gs_id, item_ids = await rm_ready_gs(
        client,
        storage,
        actors,
        masters,
        [(products.dmt, 10, 10)],
    )

    # Inspect line: 8 OK, 2 broken body
    await client.put(
        f"/api/v1/gs-items/{item_ids[0]}/inspection",
        headers={"Authorization": f"Bearer {actors.aman}"},
        json={
            "allocations": [
                {"condition_code": "DMT_OK_PACKED", "qty": 8},
                {"condition_code": "DMT_BROKEN_BODY", "qty": 2},
            ],
            "extraction": {
                "primary_type": "PACKAGING_EXTRACTED",
                "packaging_qty": 10,
                "container_qty": 0,
            },
        },
    )
    await client.post(
        f"/api/v1/gs-items/{item_ids[0]}/inspection/finalise",
        headers={"Authorization": f"Bearer {actors.aman}"},
    )

    # Mismatched sum: 5 + 2 = 7 != 10 -> 422
    bad_sum = await client.put(
        f"/api/v1/gs/{gs_id}/rm-actions",
        headers={"Authorization": f"Bearer {actors.rm}"},
        json={
            "lines": [
                {
                    "gs_item_id": item_ids[0],
                    "actions": [
                        {"action_code": "SEND_NEW", "qty": 5},
                        {"action_code": "NOT_ALLOWED", "qty": 2},
                    ],
                }
            ]
        },
    )
    assert bad_sum.status_code == 422
    assert "must equal received quantity" in bad_sum.text

    # DEC-33: allocating below the 2 rejected pieces without override -> 422
    no_override = await client.put(
        f"/api/v1/gs/{gs_id}/rm-actions",
        headers={"Authorization": f"Bearer {actors.rm}"},
        json={
            "lines": [
                {
                    "gs_item_id": item_ids[0],
                    "actions": [
                        {"action_code": "SEND_NEW", "qty": 9},
                        {"action_code": "NOT_ALLOWED", "qty": 1},  # rejected was 2!
                    ],
                }
            ]
        },
    )
    assert no_override.status_code == 422
    assert "override reason" in no_override.text

    # With override_reason -> succeeds!
    with_override = await client.put(
        f"/api/v1/gs/{gs_id}/rm-actions",
        headers={"Authorization": f"Bearer {actors.rm}"},
        json={
            "override_reason": "Special commercial exception for 1 broken piece",
            "lines": [
                {
                    "gs_item_id": item_ids[0],
                    "actions": [
                        {"action_code": "SEND_NEW", "qty": 9},
                        {"action_code": "NOT_ALLOWED", "qty": 1},
                    ],
                }
            ],
        },
    )
    assert with_override.status_code == 200, with_override.text
    assert with_override.json()["current_revision_no"] == 1


@pytest.mark.asyncio
async def test_pendency_hold_ledger_g08_and_clearance(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: TriProducts,
    session_factory: sessionmaker[Session],
) -> None:
    """3 & 4. PENDING_BP qty creates pendency, moves stock (G-08 enforced), and clear restores."""
    gs_id, item_ids = await rm_ready_gs(
        client,
        storage,
        actors,
        masters,
        [(products.dmt, 10, 10)],
    )

    # Inspect line: all 10 OK
    await client.put(
        f"/api/v1/gs-items/{item_ids[0]}/inspection",
        headers={"Authorization": f"Bearer {actors.aman}"},
        json={
            "allocations": [{"condition_code": "DMT_OK_PACKED", "qty": 10}],
            "extraction": {
                "primary_type": "PACKAGING_EXTRACTED",
                "packaging_qty": 10,
                "container_qty": 0,
            },
        },
    )
    await client.post(
        f"/api/v1/gs-items/{item_ids[0]}/inspection/finalise",
        headers={"Authorization": f"Bearer {actors.aman}"},
    )

    # Save RM actions: Send New = 5, Send Repaired = 3, Pending (BP) = 2
    save_res = await client.put(
        f"/api/v1/gs/{gs_id}/rm-actions",
        headers={"Authorization": f"Bearer {actors.rm}"},
        json={
            "lines": [
                {
                    "gs_item_id": item_ids[0],
                    "actions": [
                        {"action_code": "SEND_NEW", "qty": 5},
                        {"action_code": "SEND_REPAIRED", "qty": 3},
                        {"action_code": "PENDING_BP", "qty": 2},
                        {"action_code": "NOT_ALLOWED", "qty": 0},
                        {"action_code": "ISSUE_CN", "qty": 0},
                    ],
                }
            ],
            "pendency_details": {
                item_ids[0]: {
                    "reason": "Battery leakage suspicious, checking with Repair Team",
                    "sent_to": "Repair Team",
                }
            },
        },
    )
    assert save_res.status_code == 200, save_res.text
    data = save_res.json()
    assert data["has_open_pendency"] is True
    assert data["current_revision_no"] == 1
    assert data["lines"][0]["pending_qty"] == 2

    # Verify ledger balance: 2 pieces are in PENDING_HOLD
    with session_factory() as s:
        q_pend = "select id from public.inventory_locations where code = 'PENDING_HOLD'"
        pend_loc = s.execute(text(q_pend)).scalar_one()
        q_trans = "select id from public.inventory_locations where code = 'TRANSIT'"
        transit_loc = s.execute(text(q_trans)).scalar_one()
        pend_row = (
            s.execute(
                text("select id, lot_id, qty, status from public.pendencies where gs_id = :gs_id"),
                {"gs_id": gs_id},
            )
            .mappings()
            .first()
        )
        assert pend_row is not None
        assert pend_row["status"] == "OPEN"
        assert pend_row["qty"] == 2
        pending_lot_id = pend_row["lot_id"]

        bal = s.execute(
            text(
                "select qty from public.stock_balances where lot_id = :lot and location_id = :loc"
            ),
            {"lot": pending_lot_id, "loc": pend_loc},
        ).scalar_one()
        assert bal == 2

        # Guard G-08: Attempting to move this pending lot directly to TRANSIT must fail!
        with pytest.raises(Exception, match="G-08"):
            s.execute(
                text(
                    """
                    select rms_private.rms_move_stock(
                      p_lot => :lot,
                      p_from => :pend_loc,
                      p_to => :transit_loc,
                      p_qty => 2,
                      p_type => 'TRANSFER_OUT',
                      p_ref_type => 'test',
                      p_ref_id => :gs_id,
                      p_idem_key => 'test:g08_violation',
                      p_actor => :actor,
                      p_reason => 'Illegal transfer of pending lot'
                    )
                    """
                ),
                {
                    "lot": pending_lot_id,
                    "pend_loc": pend_loc,
                    "transit_loc": transit_loc,
                    "gs_id": gs_id,
                    "actor": actors.rm_id,
                },
            )

    # 4. Check Pendency Register
    reg_res = await client.get(
        "/api/v1/pendencies",
        headers={"Authorization": f"Bearer {actors.rm}"},
        params={"gs_id": gs_id, "status": "OPEN"},
    )
    assert reg_res.status_code == 200, reg_res.text
    pends = reg_res.json()
    assert len(pends) == 1
    pend_id = pends[0]["id"]
    assert pends[0]["qty"] == 2
    assert pends[0]["sent_to"] == "Repair Team"

    # Unauthorized user (Accounts) cannot clear pendency
    unauth = await client.post(
        f"/api/v1/pendencies/{pend_id}/clear",
        headers={"Authorization": f"Bearer {actors.accounts}"},
        json={"resolution_action": "SEND_REPAIRED", "notes": "Repaired battery wire"},
    )
    assert unauth.status_code in (403, 422)

    # Clear pendency as RM (DEC-12)
    clear_res = await client.post(
        f"/api/v1/pendencies/{pend_id}/clear",
        headers={"Authorization": f"Bearer {actors.rm}"},
        json={
            "resolution_action": "SEND_REPAIRED",
            "notes": "Repair Team replaced battery connector",
        },
    )
    assert clear_res.status_code == 200, clear_res.text
    cleared_data = clear_res.json()
    assert cleared_data["status"] == "CLEARED"
    assert cleared_data["resolution_action"] == "SEND_REPAIRED"
    assert cleared_data["clearance_notes"] == "Repair Team replaced battery connector"

    # Verify GS open pendency is false and revision bumped to 2
    gs_check = await client.get(
        f"/api/v1/gs/{gs_id}/rm-actions",
        headers={"Authorization": f"Bearer {actors.rm}"},
    )
    assert gs_check.status_code == 200
    gs_data = gs_check.json()
    assert gs_data["has_open_pendency"] is False
    assert gs_data["current_revision_no"] == 2

    # In Revision 2: SEND_REPAIRED increased by 2 (3 + 2 = 5), PENDING_BP is 0
    cur_actions_rev2 = {a["action_code"]: a["qty"] for a in gs_data["lines"][0]["current_actions"]}
    assert cur_actions_rev2["SEND_NEW"] == 5
    assert cur_actions_rev2["SEND_REPAIRED"] == 5
    assert cur_actions_rev2.get("PENDING_BP", 0) == 0


@pytest.mark.asyncio
async def test_guard_g08_toggle_blocks_entire_gs(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: TriProducts,
    session_factory: sessionmaker[Session],
) -> None:
    """5. Guard G-08: pending_blocks_entire_gs toggle behavior."""
    gs_id, item_ids = await rm_ready_gs(
        client,
        storage,
        actors,
        masters,
        [(products.dmt, 10, 10)],
    )

    await client.put(
        f"/api/v1/gs-items/{item_ids[0]}/inspection",
        headers={"Authorization": f"Bearer {actors.aman}"},
        json={
            "allocations": [{"condition_code": "DMT_OK_PACKED", "qty": 10}],
            "extraction": {
                "primary_type": "PACKAGING_EXTRACTED",
                "packaging_qty": 10,
                "container_qty": 0,
            },
        },
    )
    await client.post(
        f"/api/v1/gs-items/{item_ids[0]}/inspection/finalise",
        headers={"Authorization": f"Bearer {actors.aman}"},
    )

    # Put 2 pieces into Pending (BP)
    await client.put(
        f"/api/v1/gs/{gs_id}/rm-actions",
        headers={"Authorization": f"Bearer {actors.rm}"},
        json={
            "lines": [
                {
                    "gs_item_id": item_ids[0],
                    "actions": [
                        {"action_code": "SEND_NEW", "qty": 8},
                        {"action_code": "PENDING_BP", "qty": 2},
                    ],
                }
            ]
        },
    )

    # CASE A: Default setting pending_blocks_entire_gs = false
    # Finalise should succeed even with open pendency (non-pending pieces move to Stage-2 handover)
    fin_ok = await client.post(
        f"/api/v1/gs/{gs_id}/rm-actions/finalise",
        headers={"Authorization": f"Bearer {actors.rm}"},
    )
    assert fin_ok.status_code == 200, fin_ok.text
    assert fin_ok.json()["status"] == "IN_PROCESS"

    # CASE B: Turn toggle pending_blocks_entire_gs = true
    with session_factory() as s:
        s.execute(
            text(
                "update public.system_settings "
                "set value = 'true'::jsonb where key = 'pending_blocks_entire_gs'"
            )
        )
        s.commit()

    # Create another GS in RM_REVIEW with pending piece
    gs2_id, gs2_items = await rm_ready_gs(
        client,
        storage,
        actors,
        masters,
        [(products.dmt, 10, 10)],
    )
    await client.put(
        f"/api/v1/gs-items/{gs2_items[0]}/inspection",
        headers={"Authorization": f"Bearer {actors.aman}"},
        json={
            "allocations": [{"condition_code": "DMT_OK_PACKED", "qty": 10}],
            "extraction": {
                "primary_type": "PACKAGING_EXTRACTED",
                "packaging_qty": 10,
                "container_qty": 0,
            },
        },
    )
    await client.post(
        f"/api/v1/gs-items/{gs2_items[0]}/inspection/finalise",
        headers={"Authorization": f"Bearer {actors.aman}"},
    )

    await client.put(
        f"/api/v1/gs/{gs2_id}/rm-actions",
        headers={"Authorization": f"Bearer {actors.rm}"},
        json={
            "lines": [
                {
                    "gs_item_id": gs2_items[0],
                    "actions": [
                        {"action_code": "SEND_NEW", "qty": 8},
                        {"action_code": "PENDING_BP", "qty": 2},
                    ],
                }
            ]
        },
    )

    # Now finalise MUST fail with 422 Guard G-08 violation!
    fin_blocked = await client.post(
        f"/api/v1/gs/{gs2_id}/rm-actions/finalise",
        headers={"Authorization": f"Bearer {actors.rm}"},
    )
    assert fin_blocked.status_code == 409 or fin_blocked.status_code == 422
    assert "G-08" in fin_blocked.text

    # Reset toggle to false for remaining tests
    with session_factory() as s:
        s.execute(
            text(
                "update public.system_settings "
                "set value = 'false'::jsonb where key = 'pending_blocks_entire_gs'"
            )
        )
        s.commit()


@pytest.mark.asyncio
async def test_replacement_slip_generation_and_print_logging(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: TriProducts,
) -> None:
    """7. GET /gs/{id}/replacement-slip returns slip data, logs prints, and reflects revisions."""
    gs_id, item_ids = await rm_ready_gs(
        client,
        storage,
        actors,
        masters,
        [(products.dmt, 10, 10)],
    )

    await client.put(
        f"/api/v1/gs-items/{item_ids[0]}/inspection",
        headers={"Authorization": f"Bearer {actors.aman}"},
        json={
            "allocations": [
                {"condition_code": "DMT_OK_PACKED", "qty": 7},
                {"condition_code": "DMT_BROKEN_BODY", "qty": 3},
            ],
            "extraction": {
                "primary_type": "PACKAGING_EXTRACTED",
                "packaging_qty": 10,
                "container_qty": 0,
            },
        },
    )
    await client.post(
        f"/api/v1/gs-items/{item_ids[0]}/inspection/finalise",
        headers={"Authorization": f"Bearer {actors.aman}"},
    )

    # Save Revision 1: Send New = 4, Issue CN = 3, Not Allowed = 3
    await client.put(
        f"/api/v1/gs/{gs_id}/rm-actions",
        headers={"Authorization": f"Bearer {actors.rm}"},
        json={
            "lines": [
                {
                    "gs_item_id": item_ids[0],
                    "actions": [
                        {"action_code": "SEND_NEW", "qty": 4},
                        {"action_code": "ISSUE_CN", "qty": 3},
                        {"action_code": "NOT_ALLOWED", "qty": 3},
                    ],
                }
            ]
        },
    )

    # First print: print_count = 1, is_reprint = False
    slip_1 = await client.get(
        f"/api/v1/gs/{gs_id}/replacement-slip",
        headers={"Authorization": f"Bearer {actors.rm}"},
    )
    assert slip_1.status_code == 200, slip_1.text
    s1 = slip_1.json()
    assert s1["gs_id"] == gs_id
    assert s1["revision_no"] == 1
    assert s1["print_count"] == 1
    assert s1["is_reprint"] is False
    assert s1["totals"]["received_qty"] == 10
    assert s1["totals"]["send_new_qty"] == 4
    assert s1["totals"]["issue_cn_qty"] == 3
    assert s1["totals"]["not_allowed_qty"] == 3
    assert s1["totals"]["rejected_qty"] == 3
    assert len(s1["signature_blocks"]) == 2

    # Second print: print_count = 2, is_reprint = True -> watermark REPRINT
    slip_2 = await client.get(
        f"/api/v1/gs/{gs_id}/replacement-slip",
        headers={"Authorization": f"Bearer {actors.rm}"},
    )
    assert slip_2.status_code == 200
    s2 = slip_2.json()
    assert s2["print_count"] == 2
    assert s2["is_reprint"] is True
    assert s2["watermark"] == "REPRINT"

    # Revise to Revision 2: Send New = 7, Not Allowed = 3
    await client.put(
        f"/api/v1/gs/{gs_id}/rm-actions",
        headers={"Authorization": f"Bearer {actors.rm}"},
        json={
            "reason": "Party requested replacement instead of credit note",
            "lines": [
                {
                    "gs_item_id": item_ids[0],
                    "actions": [
                        {"action_code": "SEND_NEW", "qty": 7},
                        {"action_code": "NOT_ALLOWED", "qty": 3},
                    ],
                }
            ],
        },
    )

    # Print after revision: revision_no = 2, watermark = REVISION 2
    slip_rev2 = await client.get(
        f"/api/v1/gs/{gs_id}/replacement-slip",
        headers={"Authorization": f"Bearer {actors.rm}"},
    )
    assert slip_rev2.status_code == 200
    sr2 = slip_rev2.json()
    assert sr2["revision_no"] == 2
    assert sr2["watermark"] == "REVISION 2"
    assert sr2["totals"]["send_new_qty"] == 7
    assert sr2["totals"]["issue_cn_qty"] == 0
