"""P3-06 Credit Note workflow integration tests.

Master plan references: §2.2 (Step-7), §3.2 DD r68-r78, BR-32..BR-37, G-13, G-14,
DEC-13, DEC-22, DEC-23, DEC-24, DEC-33.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
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
    rm: str
    rm_id: uuid.UUID
    accounts: str
    accounts_id: uuid.UUID
    admin: str
    admin_id: uuid.UUID
    other_user: str
    other_id: uuid.UUID


@pytest.fixture
def actors(users: UserFactory, make_token: JwtFactory) -> Actors:
    rm = users.create(roles=["REPLACEMENT_MANAGER"], full_name="Replacement Manager")
    accounts = users.create(roles=["ACCOUNTS"], full_name="Deepak Ji Accounts")
    admin = users.create(super_admin=True, full_name="Admin User")
    other = users.create(roles=["TECHNICIAN"], full_name="Technician User")
    return Actors(
        rm=make_token(rm),
        rm_id=rm,
        accounts=make_token(accounts),
        accounts_id=accounts,
        admin=make_token(admin),
        admin_id=admin,
        other_user=make_token(other),
        other_id=other,
    )


def _setup_credit_notes_fixtures(
    conn: Connection,
    actor_id: uuid.UUID,
    party_state: str = "UP",
) -> dict[str, Any]:
    wf_id = conn.execute(text("select id from public.workflow_versions limit 1")).scalar_one()

    cat_id = conn.execute(
        text("select id from public.product_categories where code = 'DMT'")
    ).scalar_one()

    prod_id = uuid.uuid4()
    prod_code = f"PRD_{prod_id.hex[:6]}"
    conn.execute(
        text(
            "insert into public.products (id, code, name, category_id) "
            "values (:id, :code, :name, :cat_id)"
        ),
        {"id": prod_id, "code": prod_code, "name": "P306 Test Geyser", "cat_id": cat_id},
    )

    state_id = conn.execute(
        text("select id from public.states where code = :code"),
        {"code": party_state},
    ).scalar_one_or_none()

    party_id = uuid.uuid4()
    conn.execute(
        text(
            "insert into public.parties (id, code, name, state_id) "
            "values (:id, :code, :name, :state_id)"
        ),
        {
            "id": party_id,
            "code": f"PRTY_{party_id.hex[:6]}",
            "name": "P306 Test Agency",
            "state_id": state_id,
        },
    )

    gs_id = uuid.uuid4()
    gs_no = f"GS-P306-{gs_id.hex[:6]}"
    conn.execute(
        text(
            """
            insert into public.goods_slips (
                id, gs_no, party_id, workflow_version_id, status,
                delivery_mode_code, courier_name, docket_no,
                category_code, original_category_code,
                box_count, created_by
            ) values (
                :id, :gs_no, :party_id, :wf_id, 'ITEMIZATION',
                'COURIER_PARCEL', 'BlueDart', 'DKT-1234',
                'CSR', 'CSR', 1, :actor_id
            )
            """
        ),
        {"id": gs_id, "gs_no": gs_no, "party_id": party_id, "wf_id": wf_id, "actor_id": actor_id},
    )

    item1_id = uuid.uuid4()
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
            "id": item1_id,
            "gs_id": gs_id,
            "product_id": prod_id,
            "cat_id": cat_id,
            "actor_id": actor_id,
        },
    )

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

    # Insert RM actions (ISSUE_CN for 10 pcs)
    conn.execute(
        text(
            """
            insert into public.rm_item_actions (
                gs_item_id, revision_no, action_code, qty, is_current, decided_by
            ) values (
                :item1_id, 1, 'ISSUE_CN', 10, true, :actor_id
            )
            """
        ),
        {"item1_id": item1_id, "actor_id": actor_id},
    )

    # Insert stock item & lots for testing condition classes
    stock_item_id = uuid.uuid4()
    conn.execute(
        text(
            "insert into public.stock_items (id, item_kind, product_id) "
            "values (:id, 'FINISHED_GOOD', :prod_id)"
        ),
        {"id": stock_item_id, "prod_id": prod_id},
    )

    lot_good_id = uuid.uuid4()
    conn.execute(
        text(
            """
            insert into public.stock_lots (
                id, stock_item_id, gs_id, gs_item_id, condition_class, created_by
            ) values (
                :id, :stock_item_id, :gs_id, :gs_item_id, 'FUNCTIONAL_GOOD', :actor_id
            )
            """
        ),
        {
            "id": lot_good_id,
            "stock_item_id": stock_item_id,
            "gs_id": gs_id,
            "gs_item_id": item1_id,
            "actor_id": actor_id,
        },
    )

    lot_repaired_id = uuid.uuid4()
    conn.execute(
        text(
            """
            insert into public.stock_lots (
                id, stock_item_id, gs_id, gs_item_id, condition_class, created_by
            ) values (
                :id, :stock_item_id, :gs_id, :gs_item_id, 'FUNCTIONAL_REPAIRED', :actor_id
            )
            """
        ),
        {
            "id": lot_repaired_id,
            "stock_item_id": stock_item_id,
            "gs_id": gs_id,
            "gs_item_id": item1_id,
            "actor_id": actor_id,
        },
    )

    return {
        "gs_id": gs_id,
        "gs_no": gs_no,
        "party_id": party_id,
        "product_id": prod_id,
        "product_code": prod_code,
        "gs_item_id": item1_id,
        "lot_good_id": lot_good_id,
        "lot_repaired_id": lot_repaired_id,
    }


async def test_rm_cn_decision_prefill_and_deviation(
    client: AsyncClient,
    actors: Actors,
    db_conn: Connection,
) -> None:
    data = _setup_credit_notes_fixtures(db_conn, actors.rm_id)
    gs_id = data["gs_id"]
    item_id = data["gs_item_id"]

    # 1. Get prefill
    res = await client.get(
        f"/api/v1/gs/{gs_id}/cn-decision",
        headers=_auth(actors.rm),
    )
    assert res.status_code == 200, res.text
    prefill = res.json()
    assert prefill["gs_id"] == str(gs_id)
    assert len(prefill["prefill_lines"]) == 1
    assert prefill["prefill_lines"][0]["default_decision_code"] == "ALLOW_CN"
    assert prefill["prefill_lines"][0]["planned_qty"] == 10

    # 2. Submit diverging decision without deviation_reason -> 422 (DEC-13)
    res = await client.post(
        f"/api/v1/gs/{gs_id}/cn-decision",
        json={
            "lines": [
                {
                    "gs_item_id": str(item_id),
                    "decision": "DENY_CN_SEND_REPLACEMENT",
                    "qty": 10,
                }
            ],
            "deviation_reason": None,
        },
        headers=_auth(actors.rm),
    )
    assert res.status_code == 422
    assert "DEC-13" in res.json()["error"]["message"]

    # 3. Submit diverging decision with deviation_reason -> succeeds
    res = await client.post(
        f"/api/v1/gs/{gs_id}/cn-decision",
        json={
            "lines": [
                {
                    "gs_item_id": str(item_id),
                    "decision": "DENY_CN_SEND_REPLACEMENT",
                    "qty": 10,
                }
            ],
            "deviation_reason": "Replacement unit requested by party instead of credit note",
        },
        headers=_auth(actors.rm),
    )
    assert res.status_code == 201
    dec = res.json()
    assert dec["deviation_reason"] == "Replacement unit requested by party instead of credit note"
    assert dec["lines"][0]["decision_code"] == "DENY_CN_SEND_REPLACEMENT"

    # 4. Now submit ALLOW_CN decision (matching original plan) -> supersedes previous
    res = await client.post(
        f"/api/v1/gs/{gs_id}/cn-decision",
        json={
            "lines": [
                {
                    "gs_item_id": str(item_id),
                    "decision": "ALLOW_CN",
                    "qty": 10,
                }
            ],
        },
        headers=_auth(actors.rm),
    )
    assert res.status_code == 201
    dec = res.json()
    assert dec["is_current"] is True
    assert dec["lines"][0]["decision_code"] == "ALLOW_CN"


async def test_g13_draft_creation_guards(
    client: AsyncClient,
    actors: Actors,
    db_conn: Connection,
) -> None:
    data = _setup_credit_notes_fixtures(db_conn, actors.rm_id)
    gs_id = data["gs_id"]
    item_id = data["gs_item_id"]

    # 1. Attempt to create CN draft when NO ALLOW_CN decision exists yet -> 422 G-13
    res = await client.post(
        "/api/v1/credit-notes",
        json={
            "gs_id": str(gs_id),
            "cn_type_code": "GENERAL_CN",
            "lines": [{"gs_item_id": str(item_id), "qty": 5}],
        },
        headers=_auth(actors.accounts),
    )
    assert res.status_code == 422
    assert "G-13" in res.json()["error"]["message"]

    # 2. RM approves ALLOW_CN for 10 pcs
    res = await client.post(
        f"/api/v1/gs/{gs_id}/cn-decision",
        json={
            "lines": [{"gs_item_id": str(item_id), "decision": "ALLOW_CN", "qty": 10}],
        },
        headers=_auth(actors.rm),
    )
    assert res.status_code == 201

    # 3. Attempt to create CN draft requesting 15 pcs (> 10 allowed) -> 422 G-13
    res = await client.post(
        "/api/v1/credit-notes",
        json={
            "gs_id": str(gs_id),
            "cn_type_code": "GENERAL_CN",
            "lines": [{"gs_item_id": str(item_id), "qty": 15}],
        },
        headers=_auth(actors.accounts),
    )
    assert res.status_code == 422
    assert "G-13" in res.json()["error"]["message"]

    # 4. Create CN draft for 6 pcs -> succeeds
    res = await client.post(
        "/api/v1/credit-notes",
        json={
            "gs_id": str(gs_id),
            "cn_type_code": "GST_CN",
            "gst_portal_code": "GST_REFLECTED",
            "lines": [
                {
                    "gs_item_id": str(item_id),
                    "lot_id": str(data["lot_good_id"]),
                    "qty": 6,
                }
            ],
        },
        headers=_auth(actors.accounts),
    )
    assert res.status_code == 201
    cn = res.json()
    assert cn["status"] == "DRAFT"
    assert len(cn["lines"]) == 1
    assert cn["lines"][0]["qty"] == 6

    # 5. Attempt second CN draft for 5 pcs (6 + 5 = 11 > 10) -> 422 G-13 cumulative limit
    res = await client.post(
        "/api/v1/credit-notes",
        json={
            "gs_id": str(gs_id),
            "cn_type_code": "GST_CN",
            "gst_portal_code": "GST_REFLECTED",
            "lines": [{"gs_item_id": str(item_id), "qty": 5}],
        },
        headers=_auth(actors.accounts),
    )
    assert res.status_code == 422
    assert "G-13" in res.json()["error"]["message"]


async def test_party_document_and_gst_portal_verification(
    client: AsyncClient,
    actors: Actors,
    db_conn: Connection,
) -> None:
    data = _setup_credit_notes_fixtures(db_conn, actors.rm_id)
    gs_id = data["gs_id"]
    item_id = data["gs_item_id"]

    # RM approves ALLOW_CN
    await client.post(
        f"/api/v1/gs/{gs_id}/cn-decision",
        json={"lines": [{"gs_item_id": str(item_id), "decision": "ALLOW_CN", "qty": 10}]},
        headers=_auth(actors.rm),
    )

    # Accounts creates draft
    res = await client.post(
        "/api/v1/credit-notes",
        json={
            "gs_id": str(gs_id),
            "cn_type_code": "GENERAL_CN",
            "lines": [{"gs_item_id": str(item_id), "qty": 5}],
        },
        headers=_auth(actors.accounts),
    )
    assert res.status_code == 201
    cn_id = res.json()["id"]

    # Verify party document
    res = await client.patch(
        f"/api/v1/credit-notes/{cn_id}/party-document",
        json={
            "party_doc_code": "PARTY_INVOICE",
            "doc_no": "INV-DEALER-2026-99",
            "doc_date": str(date.today()),
            "amount": 25000.0,
            "notes": "Verified against dealer invoice scan",
        },
        headers=_auth(actors.accounts),
    )
    assert res.status_code == 200
    cn = res.json()
    assert cn["party_doc_code"] == "PARTY_INVOICE"
    assert cn["party_doc_no"] == "INV-DEALER-2026-99"

    # Step-2 linked documents returned in Credit Note detail for split-screen
    res = await client.get(
        f"/api/v1/credit-notes/{cn_id}",
        headers=_auth(actors.accounts),
    )
    assert res.status_code == 200
    detail = res.json()
    assert isinstance(detail["linked_step2_documents"], list)

    # Verify GST portal check - GST_NOT_REFLECTED
    res = await client.patch(
        f"/api/v1/credit-notes/{cn_id}/gst-check",
        json={
            "gst_portal_code": "GST_NOT_REFLECTED",
            "return_type": "GSTR-2B",
            "return_period": "102026",
            "checked_on": str(date.today()),
        },
        headers=_auth(actors.accounts),
    )
    assert res.status_code == 200
    cn = res.json()
    assert cn["gst_portal_code"] == "GST_NOT_REFLECTED"
    # Auto changed to JV_ONLY per DD r76!
    assert cn["cn_type_code"] == "JV_ONLY"

    # Attempting to change type to GST_CN while GST_NOT_REFLECTED fails G-13
    res = await client.patch(
        f"/api/v1/credit-notes/{cn_id}/type",
        json={"cn_type_code": "GST_CN"},
        headers=_auth(actors.accounts),
    )
    assert res.status_code in (409, 422)
    assert "G-13" in res.json()["error"]["message"]

    # Now verify GST portal check as GST_REFLECTED
    res = await client.patch(
        f"/api/v1/credit-notes/{cn_id}/gst-check",
        json={
            "gst_portal_code": "GST_REFLECTED",
            "return_type": "GSTR-1",
            "return_period": "102026",
            "checked_on": str(date.today()),
        },
        headers=_auth(actors.accounts),
    )
    assert res.status_code == 200
    assert res.json()["gst_portal_code"] == "GST_REFLECTED"

    # Can now set GST_CN
    res = await client.patch(
        f"/api/v1/credit-notes/{cn_id}/type",
        json={"cn_type_code": "GST_CN"},
        headers=_auth(actors.accounts),
    )
    assert res.status_code == 200
    assert res.json()["cn_type_code"] == "GST_CN"


async def test_cn_type_restrictions_and_split(
    client: AsyncClient,
    actors: Actors,
    db_conn: Connection,
) -> None:
    data = _setup_credit_notes_fixtures(db_conn, actors.rm_id)
    gs_id = data["gs_id"]
    item_id = data["gs_item_id"]

    await client.post(
        f"/api/v1/gs/{gs_id}/cn-decision",
        json={"lines": [{"gs_item_id": str(item_id), "decision": "ALLOW_CN", "qty": 10}]},
        headers=_auth(actors.rm),
    )

    # Create CN with a repaired lot
    res = await client.post(
        "/api/v1/credit-notes",
        json={
            "gs_id": str(gs_id),
            "cn_type_code": "GENERAL_CN",
            "lines": [
                {
                    "gs_item_id": str(item_id),
                    "lot_id": str(data["lot_repaired_id"]),
                    "qty": 4,
                }
            ],
        },
        headers=_auth(actors.accounts),
    )
    assert res.status_code == 201
    cn_id = res.json()["id"]

    # Mark GST reflected
    await client.patch(
        f"/api/v1/credit-notes/{cn_id}/gst-check",
        json={
            "gst_portal_code": "GST_REFLECTED",
            "return_type": "GSTR-1",
            "return_period": "102026",
            "checked_on": str(date.today()),
        },
        headers=_auth(actors.accounts),
    )

    # Attempt to change repaired line to GST_CN -> 422 (GST_CN only for FUNCTIONAL_GOOD)
    res = await client.patch(
        f"/api/v1/credit-notes/{cn_id}/type",
        json={"cn_type_code": "GST_CN"},
        headers=_auth(actors.accounts),
    )
    assert res.status_code == 422
    assert "FUNCTIONAL_GOOD" in res.json()["error"]["message"]


async def test_rate_verification_variance_and_issue_g14(
    client: AsyncClient,
    actors: Actors,
    db_conn: Connection,
) -> None:
    data = _setup_credit_notes_fixtures(db_conn, actors.rm_id)
    gs_id = data["gs_id"]
    item_id = data["gs_item_id"]

    # RM ALLOW_CN
    await client.post(
        f"/api/v1/gs/{gs_id}/cn-decision",
        json={"lines": [{"gs_item_id": str(item_id), "decision": "ALLOW_CN", "qty": 10}]},
        headers=_auth(actors.rm),
    )

    # Accounts drafts CN
    res = await client.post(
        "/api/v1/credit-notes",
        json={
            "gs_id": str(gs_id),
            "cn_type_code": "GST_CN",
            "gst_portal_code": "GST_REFLECTED",
            "lines": [
                {
                    "gs_item_id": str(item_id),
                    "lot_id": str(data["lot_good_id"]),
                    "qty": 5,
                }
            ],
        },
        headers=_auth(actors.accounts),
    )
    assert res.status_code == 201
    cn = res.json()
    cn_id = cn["id"]
    line_id = cn["lines"][0]["id"]

    # Mark GST reflected
    await client.patch(
        f"/api/v1/credit-notes/{cn_id}/gst-check",
        json={
            "gst_portal_code": "GST_REFLECTED",
            "return_type": "GSTR-1",
            "return_period": "102026",
            "checked_on": str(date.today()),
        },
        headers=_auth(actors.accounts),
    )

    # Update type to GST_CN
    await client.patch(
        f"/api/v1/credit-notes/{cn_id}/type",
        json={"cn_type_code": "GST_CN"},
        headers=_auth(actors.accounts),
    )

    # 1. Attempt to issue without rate verifications -> 422 G-14
    res = await client.post(
        f"/api/v1/credit-notes/{cn_id}/issue",
        json={
            "cn_no": "CN-2026-901",
            "cn_date": str(date.today()),
        },
        headers=_auth(actors.accounts),
    )
    assert res.status_code in (409, 422)
    assert "G-14" in res.json()["error"]["message"]

    # 2. Add purchase baseline rate (₹1,000)
    res = await client.post(
        f"/api/v1/credit-note-lines/{line_id}/rate-verifications",
        json={
            "reference_code": "RATE_PURCHASE",
            "ref_doc_no": "PO-1001",
            "ref_doc_date": str(date.today()),
            "rate": 1000.0,
            "notes": "Original PO rate",
        },
        headers=_auth(actors.accounts),
    )
    assert res.status_code == 201

    # 3. Add sales rate with >15% variance (₹1,300 -> 30% diff) -> advisory warning raised
    res = await client.post(
        f"/api/v1/credit-note-lines/{line_id}/rate-verifications",
        json={
            "reference_code": "RATE_SALES",
            "ref_doc_no": "INV-2001",
            "ref_doc_date": str(date.today()),
            "rate": 1300.0,
            "notes": "Sales invoice to party",
        },
        headers=_auth(actors.accounts),
    )
    assert res.status_code == 201
    rate_res = res.json()
    assert rate_res["has_variance_warning"] is True
    assert float(rate_res["variance_percent"]) == 30.0

    # 4. Check valuation: 5 qty * ₹1300 = ₹6,500 taxable value
    # Intra-state (UP to UP): 9% CGST + 9% SGST = 18% total = ₹1,170 tax -> total ₹7,670
    cn_res = await client.get(f"/api/v1/credit-notes/{cn_id}", headers=_auth(actors.accounts))
    assert cn_res.status_code == 200
    cn_data = cn_res.json()
    assert float(cn_data["taxable_value"]) == 6500.0
    assert float(cn_data["cgst_amount"]) == 585.0
    assert float(cn_data["sgst_amount"]) == 585.0
    assert float(cn_data["igst_amount"]) == 0.0
    assert float(cn_data["total_value"]) == 7670.0

    # 5. Successfully issue the credit note (DEC-22 entered from accounting system)
    res = await client.post(
        f"/api/v1/credit-notes/{cn_id}/issue",
        json={
            "cn_no": "CN-2026-901",
            "cn_date": str(date.today()),
        },
        headers=_auth(actors.accounts),
    )
    assert res.status_code == 200
    issued = res.json()
    assert issued["status"] == "ISSUED"
    assert issued["cn_no"] == "CN-2026-901"
    assert issued["issued_at"] is not None

    # 6. Verify print endpoint
    res = await client.get(f"/api/v1/credit-notes/{cn_id}/print", headers=_auth(actors.accounts))
    assert res.status_code == 200
    print_data = res.json()
    assert print_data["voucher_no"] == "CN-2026-901"
    assert float(print_data["taxable_value"]) == 6500.0
    assert len(print_data["signature_blocks"]) == 2


async def test_cn_cancel_and_work_queue(
    client: AsyncClient,
    actors: Actors,
    db_conn: Connection,
) -> None:
    data = _setup_credit_notes_fixtures(db_conn, actors.rm_id)
    gs_id = data["gs_id"]
    item_id = data["gs_item_id"]

    # RM ALLOW_CN
    await client.post(
        f"/api/v1/gs/{gs_id}/cn-decision",
        json={"lines": [{"gs_item_id": str(item_id), "decision": "ALLOW_CN", "qty": 10}]},
        headers=_auth(actors.rm),
    )

    # Accounts work queue should show this GS as pending CN drafting
    res = await client.get("/api/v1/credit-notes/work-queue", headers=_auth(actors.accounts))
    assert res.status_code == 200
    wq = res.json()
    pending_ids = [item["gs_id"] for item in wq["pending_gs"]]
    assert str(gs_id) in pending_ids

    # Create CN draft
    res = await client.post(
        "/api/v1/credit-notes",
        json={
            "gs_id": str(gs_id),
            "cn_type_code": "GENERAL_CN",
            "lines": [{"gs_item_id": str(item_id), "qty": 2}],
        },
        headers=_auth(actors.accounts),
    )
    assert res.status_code == 201
    cn_id = res.json()["id"]

    # Cancel CN
    res = await client.post(
        f"/api/v1/credit-notes/{cn_id}/cancel",
        json={"reason": "Entered in error, will re-draft"},
        headers=_auth(actors.accounts),
    )
    assert res.status_code == 200
    cancelled = res.json()
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "Entered in error, will re-draft"
