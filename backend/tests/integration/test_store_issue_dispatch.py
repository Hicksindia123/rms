"""P3-05 store issue, replacement dispatch, and RM resolution board (integration).

Master plan references: BR-19, BR-31, BR-32, DEC-13, DEC-21, DEC-26, DEC-33, §8.6.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text

from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory
from tests.integration.test_gate_inward import _auth

pytestmark = pytest.mark.anyio


@dataclass
class Actors:
    sahil: str
    sahil_id: uuid.UUID
    dispatch_user: str
    dispatch_id: uuid.UUID
    rm: str
    rm_id: uuid.UUID
    admin: str
    admin_id: uuid.UUID


@pytest.fixture
def actors(users: UserFactory, make_token: JwtFactory) -> Actors:
    sahil = users.create(roles=["INTERMEDIATE_STORE_MANAGER"], full_name="Sahil")
    dispatch_user = users.create(roles=["DISPATCH"], full_name="Dispatch Officer")
    rm = users.create(roles=["REPLACEMENT_MANAGER"], full_name="Replacement Manager")
    admin = users.create(super_admin=True, full_name="Admin")
    return Actors(
        sahil=make_token(sahil),
        sahil_id=sahil,
        dispatch_user=make_token(dispatch_user),
        dispatch_id=dispatch_user,
        rm=make_token(rm),
        rm_id=rm,
        admin=make_token(admin),
        admin_id=admin,
    )


def _location_id(conn: Connection, code: str) -> uuid.UUID:
    return conn.execute(
        text("select id from public.inventory_locations where code = :code"),
        {"code": code},
    ).scalar_one()


def _setup_fixtures(conn: Connection, actor_id: uuid.UUID) -> dict[str, Any]:
    wf_id = conn.execute(text("select id from public.workflow_versions limit 1")).scalar_one()

    # Product category & product
    cat_id = conn.execute(
        text("select id from public.product_categories where code = 'DMT'")
    ).scalar_one()

    prod_id = uuid.uuid4()
    conn.execute(
        text(
            "insert into public.products (id, code, name, category_id) "
            "values (:id, :code, :name, :cat_id)"
        ),
        {
            "id": prod_id,
            "code": f"PRD_{prod_id.hex[:6]}",
            "name": "P305 Test Fan",
            "cat_id": cat_id,
        },
    )

    # Party
    party_id = uuid.uuid4()
    conn.execute(
        text("insert into public.parties (id, code, name) values (:id, :code, :name)"),
        {"id": party_id, "code": f"PRTY_{party_id.hex[:6]}", "name": "P305 Dealer"},
    )

    # Goods slip
    gs_id = uuid.uuid4()
    gs_no = f"GS-P305-{gs_id.hex[:6]}"
    conn.execute(
        text(
            """
            insert into public.goods_slips (
                id, gs_no, party_id, workflow_version_id, status,
                delivery_mode_code, courier_name, docket_no,
                category_code, original_category_code, box_count, created_by
            ) values (
                :id, :gs_no, :party_id, :wf_id, 'ITEMIZATION',
                'COURIER_PARCEL', 'BlueDart', 'DKT-1234',
                'CSR', 'CSR', 1, :actor_id
            )
            """
        ),
        {"id": gs_id, "gs_no": gs_no, "party_id": party_id, "wf_id": wf_id, "actor_id": actor_id},
    )

    # GS item
    gs_item_id = uuid.uuid4()
    conn.execute(
        text(
            """
            insert into public.gs_items (
                id, gs_id, line_no, product_id, category_id, received_qty, created_by
            ) values (
                :id, :gs_id, 1, :product_id, :cat_id, 10, :actor_id
            )
            """
        ),
        {
            "id": gs_item_id,
            "gs_id": gs_id,
            "product_id": prod_id,
            "cat_id": cat_id,
            "actor_id": actor_id,
        },
    )

    # Advance status to CSR_APPROVAL_PENDING, insert CSR approval, then advance to IN_PROCESS
    # AMD-08 (change plan Phase 3): the count is submitted (ITEMIZATION -> CATEGORISATION) first.
    conn.execute(
        text("update public.goods_slips set status = 'CATEGORISATION' where id = :gs_id"),
        {"gs_id": gs_id},
    )
    conn.execute(
        text("update public.goods_slips set status = 'CSR_APPROVAL_PENDING' where id = :gs_id"),
        {"gs_id": gs_id},
    )
    conn.execute(
        text(
            """
            insert into public.csr_approvals (gs_id, decision_code, decided_by, is_current)
            values (:gs_id, 'CSR_APPROVED', :actor_id, true)
            """
        ),
        {"gs_id": gs_id, "actor_id": actor_id},
    )
    conn.execute(
        text("update public.goods_slips set status = 'IN_PROCESS' where id = :gs_id"),
        {"gs_id": gs_id},
    )

    # Stock items & lots
    stock_item_id = uuid.uuid4()
    conn.execute(
        text(
            "insert into public.stock_items (id, item_kind, product_id) "
            "values (:id, 'FINISHED_GOOD', :prod_id)"
        ),
        {"id": stock_item_id, "prod_id": prod_id},
    )

    inter_store_id = _location_id(conn, "INTERMEDIATE_STORE")
    non_func_store_id = _location_id(conn, "NON_FUNCTIONAL_STORE")

    def _create_lot(condition: str, qty: int) -> uuid.UUID:
        lid = uuid.uuid4()
        conn.execute(
            text(
                """
                insert into public.stock_lots
                       (id, stock_item_id, gs_id, gs_item_id, condition_class, created_by)
                values (:id, :si_id, :gs_id, :gi_id, :cond, :actor_id)
                """
            ),
            {
                "id": lid,
                "si_id": stock_item_id,
                "gs_id": gs_id,
                "gi_id": gs_item_id,
                "cond": condition,
                "actor_id": actor_id,
            },
        )
        dest_loc = (
            inter_store_id
            if condition in ("FUNCTIONAL_GOOD", "FUNCTIONAL_REPAIRED")
            else non_func_store_id
        )
        conn.execute(
            text(
                """
                select rms_private.rms_move_stock(
                    p_lot := cast(:lot as uuid),
                    p_from := cast(null as uuid),
                    p_to := cast(:to as uuid),
                    p_qty := cast(:qty as integer),
                    p_type := 'INWARD',
                    p_ref_type := 'GOODS_SLIP',
                    p_ref_id := cast(:gs_id as uuid),
                    p_idem_key := cast(:key as text),
                    p_actor := cast(:actor as uuid),
                    p_reason := 'P3-05 fixture setup'
                )
                """
            ),
            {
                "lot": lid,
                "to": dest_loc,
                "qty": qty,
                "gs_id": gs_id,
                "key": f"p305-setup:{lid}",
                "actor": actor_id,
            },
        )
        return lid

    # Functional Good lot (balance 5)
    fg_lot_id = _create_lot("FUNCTIONAL_GOOD", 5)

    # Functional Repaired lot (balance 3)
    fr_lot_id = _create_lot("FUNCTIONAL_REPAIRED", 3)

    # Non-Good lot (balance 2)
    ng_lot_id = _create_lot("NON_GOOD", 2)

    # Initial RM Actions: SEND_REPAIRED=3, SEND_NEW=4, NOT_ALLOWED=3 (total 10)
    for code, qty in [("SEND_REPAIRED", 3), ("SEND_NEW", 4), ("NOT_ALLOWED", 3)]:
        conn.execute(
            text(
                """
                insert into public.rm_item_actions (
                    gs_item_id, revision_no, action_code, qty, is_current, decided_by
                ) values (
                    :gi_id, 1, :code, :qty, true, :actor_id
                )
                """
            ),
            {"gi_id": gs_item_id, "code": code, "qty": qty, "actor_id": actor_id},
        )

    return {
        "gs_id": gs_id,
        "gs_no": gs_no,
        "gs_item_id": gs_item_id,
        "prod_id": prod_id,
        "fg_lot_id": fg_lot_id,
        "fr_lot_id": fr_lot_id,
        "ng_lot_id": ng_lot_id,
    }


async def test_rm_resolution_board(client: AsyncClient, actors: Actors, db_conn: Connection):
    fixtures = _setup_fixtures(db_conn, actors.admin_id)
    gs_id = fixtures["gs_id"]

    resp = await client.get(f"/api/v1/gs/{gs_id}/resolution-board", headers=_auth(actors.rm))
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["gs_id"] == str(gs_id)
    assert len(data["lines"]) == 1
    line = data["lines"][0]
    assert line["gs_item_id"] == str(fixtures["gs_item_id"])
    assert line["received_qty"] == 10

    # Current RM actions
    act_map = {a["action_code"]: a["qty"] for a in line["current_actions"]}
    assert act_map["SEND_REPAIRED"] == 3
    assert act_map["SEND_NEW"] == 4
    assert act_map["NOT_ALLOWED"] == 3

    # Outcomes
    assert line["outcomes"]["functional_good_qty"] == 5
    assert line["outcomes"]["functional_repaired_qty"] == 3
    assert line["outcomes"]["non_good_qty"] == 2


async def test_store_issue_candidate_lots_and_g04_guard(
    client: AsyncClient, actors: Actors, db_conn: Connection
):
    fixtures = _setup_fixtures(db_conn, actors.admin_id)
    fg_lot_id = fixtures["fg_lot_id"]
    ng_lot_id = fixtures["ng_lot_id"]

    # 1. Candidate lots endpoint should list functional lots, not non-good
    resp = await client.get("/api/v1/store-issues/candidate-lots", headers=_auth(actors.sahil))
    assert resp.status_code == 200
    candidate_lots = resp.json()
    lot_ids = [c["lot_id"] for c in candidate_lots]
    assert str(fg_lot_id) in lot_ids
    assert str(ng_lot_id) not in lot_ids

    # 2. Attempting to issue NON_GOOD lot to Main Store fails with G-04
    bad_payload = {
        "issue_type_code": "ISSUE_MAIN_STORE",
        "lines": [{"lot_id": str(ng_lot_id), "qty": 1}],
    }
    resp_bad = await client.post(
        "/api/v1/store-issues", json=bad_payload, headers=_auth(actors.sahil)
    )
    assert resp_bad.status_code in (400, 409), resp_bad.text
    assert "G-04" in resp_bad.text or "functional" in resp_bad.text.lower()


async def test_store_issue_flow_and_print(client: AsyncClient, actors: Actors, db_conn: Connection):
    fixtures = _setup_fixtures(db_conn, actors.admin_id)
    fg_lot_id = fixtures["fg_lot_id"]

    # Issue 2 pieces of FUNCTIONAL_GOOD to Main Store
    payload = {
        "issue_type_code": "ISSUE_MAIN_STORE",
        "notes": "P3-05 integration test issue",
        "lines": [{"lot_id": str(fg_lot_id), "qty": 2}],
    }
    resp = await client.post("/api/v1/store-issues", json=payload, headers=_auth(actors.sahil))
    assert resp.status_code == 200, resp.text
    issue = resp.json()

    assert issue["issue_no"].startswith("SI/") or "SI" in issue["issue_no"]
    assert issue["status"] == "ACKNOWLEDGED"  # Auto-acknowledged per DEC-21
    assert issue["total_qty"] == 2
    issue_id = issue["id"]

    # Printable note
    print_resp = await client.get(
        f"/api/v1/store-issues/{issue_id}/print", headers=_auth(actors.sahil)
    )
    assert print_resp.status_code == 200
    print_data = print_resp.json()
    assert print_data["issue_no"] == issue["issue_no"]
    assert print_data["total_qty"] == 2
    assert len(print_data["signature_blocks"]) == 2


async def test_replacement_dispatch_send_new_dec26(
    client: AsyncClient, actors: Actors, db_conn: Connection
):
    fixtures = _setup_fixtures(db_conn, actors.admin_id)
    gs_id = fixtures["gs_id"]
    gs_item_id = fixtures["gs_item_id"]
    fg_lot_id = fixtures["fg_lot_id"]

    # 1. SEND_NEW with lot_id violates DEC-26
    bad_payload = {
        "gs_id": str(gs_id),
        "dispatch_type": "SEND_NEW",
        "transporter": "DTDC Express",
        "lines": [{"gs_item_id": str(gs_item_id), "qty": 2, "lot_id": str(fg_lot_id)}],
    }
    resp_bad = await client.post(
        "/api/v1/dispatches", json=bad_payload, headers=_auth(actors.dispatch_user)
    )
    assert resp_bad.status_code in (400, 422), resp_bad.text
    assert "DEC-26" in resp_bad.text or "lot" in resp_bad.text.lower()

    # 2. SEND_NEW without lot_id succeeds
    good_payload = {
        "gs_id": str(gs_id),
        "dispatch_type": "SEND_NEW",
        "transporter": "DTDC Express",
        "docket_no": "DKT-9988",
        "lines": [{"gs_item_id": str(gs_item_id), "qty": 2, "lot_id": None}],
    }
    resp_good = await client.post(
        "/api/v1/dispatches", json=good_payload, headers=_auth(actors.dispatch_user)
    )
    assert resp_good.status_code == 200, resp_good.text
    disp = resp_good.json()
    assert disp["dispatch_type"] == "SEND_NEW"
    assert disp["total_qty"] == 2


async def test_replacement_dispatch_send_repaired_and_overdispatch(
    client: AsyncClient, actors: Actors, db_conn: Connection
):
    fixtures = _setup_fixtures(db_conn, actors.admin_id)
    gs_id = fixtures["gs_id"]
    gs_item_id = fixtures["gs_item_id"]
    fr_lot_id = fixtures["fr_lot_id"]
    fg_lot_id = fixtures["fg_lot_id"]

    # 1. Candidate lots for dispatch
    cand_resp = await client.get(
        "/api/v1/dispatches/candidate-lots", headers=_auth(actors.dispatch_user)
    )
    assert cand_resp.status_code == 200
    candidate_lots = cand_resp.json()
    assert any(c["lot_id"] == str(fr_lot_id) for c in candidate_lots)

    # 2. SEND_REPAIRED with FUNCTIONAL_GOOD lot fails with G-04 (must be FUNCTIONAL_REPAIRED)
    resp_bad_lot = await client.post(
        "/api/v1/dispatches",
        json={
            "gs_id": str(gs_id),
            "dispatch_type": "SEND_REPAIRED",
            "transporter": "SafeXpress",
            "lines": [{"gs_item_id": str(gs_item_id), "qty": 1, "lot_id": str(fg_lot_id)}],
        },
        headers=_auth(actors.dispatch_user),
    )
    assert resp_bad_lot.status_code in (400, 409, 422), resp_bad_lot.text
    assert "FUNCTIONAL_REPAIRED" in resp_bad_lot.text or "G-04" in resp_bad_lot.text

    # 3. Over-dispatch (planned: 3, requesting 5) without override fails (DEC-33)
    resp_over = await client.post(
        "/api/v1/dispatches",
        json={
            "gs_id": str(gs_id),
            "dispatch_type": "SEND_REPAIRED",
            "transporter": "SafeXpress",
            "lines": [{"gs_item_id": str(gs_item_id), "qty": 5, "lot_id": str(fr_lot_id)}],
        },
        headers=_auth(actors.dispatch_user),
    )
    assert resp_over.status_code in (400, 422), resp_over.text
    assert "override_reason" in resp_over.text or "DEC-33" in resp_over.text

    # 4. Valid SEND_REPAIRED within planned qty (2 of 3)
    resp_valid = await client.post(
        "/api/v1/dispatches",
        json={
            "gs_id": str(gs_id),
            "dispatch_type": "SEND_REPAIRED",
            "transporter": "SafeXpress",
            "docket_no": "DOCK-111",
            "lines": [{"gs_item_id": str(gs_item_id), "qty": 2, "lot_id": str(fr_lot_id)}],
        },
        headers=_auth(actors.dispatch_user),
    )
    assert resp_valid.status_code == 200, resp_valid.text
    disp = resp_valid.json()
    assert disp["dispatch_type"] == "SEND_REPAIRED"
    assert disp["total_qty"] == 2
