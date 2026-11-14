"""P3-07 party notification & GS closure engine integration tests.

Master plan references: §6.5, BR-09, BR-38, BR-39, G-08, G-15, DEC-25, DD r79-r80, WF r11.

Each closure checklist item is made to fail on its own (everything else complete), the RO and
CSR happy paths close with RO_CLOSED / CSR_CLOSED, reopen is Super Admin only and audited, and the
database guards (G-15 trigger, append-only notifications) reject direct SQL.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
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
from tests.integration.conftest import UserFactory, as_admin, build_test_app
from tests.integration.test_gate_inward import _auth
from tests.integration.test_unboxing import FakeStorage

pytestmark = pytest.mark.anyio


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
async def client(
    session_factory: sessionmaker[Session], storage: FakeStorage
) -> AsyncIterator[AsyncClient]:
    """The app with the in-memory storage fake (notification-proof uploads, DEC-25)."""
    app = build_test_app()
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_storage] = lambda: storage
    limiter.reset()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    limiter.reset()


@dataclass
class Actors:
    rm: str
    rm_id: uuid.UUID
    accounts: str
    accounts_id: uuid.UUID
    admin: str
    admin_id: uuid.UUID
    tech: str


@pytest.fixture
def actors(users: UserFactory, make_token: JwtFactory) -> Actors:
    rm = users.create(roles=["REPLACEMENT_MANAGER"], full_name="P307 Replacement Manager")
    accounts = users.create(roles=["ACCOUNTS"], full_name="P307 Accounts")
    admin = users.create(super_admin=True, full_name="P307 Super Admin")
    tech = users.create(roles=["TECHNICIAN"], full_name="P307 Technician")
    return Actors(
        rm=make_token(rm),
        rm_id=rm,
        accounts=make_token(accounts),
        accounts_id=accounts,
        admin=make_token(admin),
        admin_id=admin,
        tech=make_token(tech),
    )


def _loc(conn: Connection, code: str) -> uuid.UUID:
    return conn.execute(
        text("select id from public.inventory_locations where code = :c"), {"c": code}
    ).scalar_one()


def _inward(
    conn: Connection,
    *,
    gs_id: uuid.UUID,
    item_id: uuid.UUID,
    stock_item_id: uuid.UUID,
    condition: str,
    location: str,
    qty: int,
    actor: uuid.UUID,
) -> uuid.UUID:
    """A lot of the GS with `qty` pieces at `location` (through rms_move_stock, rule f)."""
    conn = as_admin(conn)
    lot_id = uuid.uuid4()
    conn.execute(
        text(
            """
            insert into public.stock_lots (id, stock_item_id, gs_id, gs_item_id, condition_class,
                                           created_by)
            values (:id, :si, :gs, :item, :cond, :actor)
            """
        ),
        {
            "id": lot_id,
            "si": stock_item_id,
            "gs": gs_id,
            "item": item_id,
            "cond": condition,
            "actor": actor,
        },
    )
    conn.execute(
        text(
            """
            select rms_private.rms_move_stock(
              p_lot := cast(:lot as uuid), p_from := cast(null as uuid),
              p_to := cast(:to as uuid), p_qty := cast(:qty as integer), p_type := 'INWARD',
              p_ref_type := 'GOODS_SLIP', p_ref_id := cast(:gs as uuid),
              p_idem_key := cast(:key as text), p_actor := cast(:actor as uuid),
              p_reason := 'P3-07 fixture')
            """
        ),
        {
            "lot": lot_id,
            "to": _loc(conn, location),
            "qty": qty,
            "gs": gs_id,
            "key": f"p307:{lot_id}",
            "actor": actor,
        },
    )
    return lot_id


def _build_gs(
    conn: Connection,
    actor: uuid.UUID,
    *,
    csr: bool = False,
    status: str = "IN_PROCESS",
    with_decision: bool = True,
    issue_cn: bool = True,
    dispatch: bool = True,
    csr_handover: bool = True,
    csr_packaging_check: bool = True,
) -> dict[str, Any]:
    """A GS whose stock is in the Main Store with every closure precondition met except the prior
    party notification (recorded through the API by the tests).

    RO: 4 pcs, RM actions ISSUE_CN 2 + SEND_NEW 2, CN decision ALLOW 2 / DENY 2, GENERAL_CN of 2
    issued, replacement of 2 dispatched. CSR: 4 pcs approved CSR, ALLOW 4, CN of 4 issued,
    handover with packaging accepted, packaging check recorded.
    """
    conn = as_admin(conn)
    wf_id = conn.execute(
        text(
            "select id from public.workflow_versions where status = 'PUBLISHED' "
            "order by version_no desc limit 1"
        )
    ).scalar_one()
    cat_id = conn.execute(
        text("select id from public.product_categories where code = 'DMT'")
    ).scalar_one()
    prod_id = uuid.uuid4()
    conn.execute(
        text("insert into public.products (id, code, name, category_id) values (:id,:c,:n,:cat)"),
        {"id": prod_id, "c": f"P307_{prod_id.hex[:6]}", "n": "P307 Iron", "cat": cat_id},
    )
    party_id = uuid.uuid4()
    conn.execute(
        text(
            """
            insert into public.parties (id, code, name, contact_name, phone, email)
            values (:id, :c, 'P307 Traders', 'Ravi', '+91 98100 00000', 'ravi@p307.example')
            """
        ),
        {"id": party_id, "c": f"PTY_{party_id.hex[:6]}"},
    )
    gs_id = uuid.uuid4()
    gs_no = f"GS-P307-{gs_id.hex[:6]}"
    category = "CSR" if csr else "RO"
    conn.execute(
        text(
            """
            insert into public.goods_slips (id, gs_no, party_id, workflow_version_id, status,
                delivery_mode_code, courier_name, docket_no, category_code,
                original_category_code, csr_commercial_path, box_count, created_by)
            values (:id, :no, :party, :wf, 'ITEMIZATION', 'COURIER_PARCEL', 'BlueDart',
                    'DKT-307', :cat, :cat, :csr, 1, :actor)
            """
        ),
        {
            "id": gs_id,
            "no": gs_no,
            "party": party_id,
            "wf": wf_id,
            "cat": category,
            "csr": csr,
            "actor": actor,
        },
    )
    item_id = uuid.uuid4()
    conn.execute(
        text(
            """
            insert into public.gs_items (id, gs_id, line_no, product_id, category_id,
                                         documented_qty, received_qty, created_by,
                                         product_code_snapshot, product_name_snapshot,
                                         category_code_snapshot)
            values (:id, :gs, 1, :prod, :cat, 4, 4, :actor, :pcode, 'P307 Iron', 'DMT')
            """
        ),
        {
            "id": item_id,
            "gs": gs_id,
            "prod": prod_id,
            "cat": cat_id,
            "actor": actor,
            "pcode": f"P307_{prod_id.hex[:6]}",
        },
    )
    set_status = text("update public.goods_slips set status = :s where id = :id")
    # AMD-08 (change plan Phase 3): the count is submitted (ITEMIZATION -> CATEGORISATION) first.
    conn.execute(set_status, {"s": "CATEGORISATION", "id": gs_id})
    if csr:
        conn.execute(set_status, {"s": "CSR_APPROVAL_PENDING", "id": gs_id})
        conn.execute(
            text(
                "insert into public.csr_approvals (gs_id, decision_code, decided_by, is_current) "
                "values (:gs, 'CSR_APPROVED', :actor, true)"
            ),
            {"gs": gs_id, "actor": actor},
        )
    else:
        # RO: G-03 → INSPECTION, G-07 → every line inspected (FINAL) before RM_REVIEW.
        conn.execute(set_status, {"s": "INSPECTION", "id": gs_id})
        conn.execute(
            text(
                "insert into public.inspections (gs_item_id, status, inspected_by, inspected_at) "
                "values (:item, 'FINAL', :actor, now())"
            ),
            {"item": item_id, "actor": actor},
        )
        conn.execute(set_status, {"s": "RM_REVIEW", "id": gs_id})
    if status != "RM_REVIEW":
        conn.execute(set_status, {"s": status, "id": gs_id})
    if not csr:
        for code in ("ISSUE_CN", "SEND_NEW"):
            conn.execute(
                text(
                    "insert into public.rm_item_actions (gs_item_id, action_code, qty, decided_by) "
                    "values (:item, :code, 2, :actor)"
                ),
                {"item": item_id, "code": code, "actor": actor},
            )
    stock_item_id = uuid.uuid4()
    conn.execute(
        text(
            "insert into public.stock_items (id, item_kind, product_id) "
            "values (:id, 'FINISHED_GOOD', :prod)"
        ),
        {"id": stock_item_id, "prod": prod_id},
    )
    lot_id = _inward(
        conn,
        gs_id=gs_id,
        item_id=item_id,
        stock_item_id=stock_item_id,
        condition="FUNCTIONAL_GOOD",
        location="MAIN_STORE",
        qty=4,
        actor=actor,
    )

    allow_qty, deny_qty = (4, 0) if csr else (2, 2)
    cn_id: uuid.UUID | None = None
    if with_decision:
        dec_id = uuid.uuid4()
        conn.execute(
            text("insert into public.rm_cn_decisions (id, gs_id, decision_by) values (:id,:gs,:a)"),
            {"id": dec_id, "gs": gs_id, "a": actor},
        )
        for code, qty in (("ALLOW_CN", allow_qty), ("DENY_CN_SEND_REPLACEMENT", deny_qty)):
            if qty:
                conn.execute(
                    text(
                        "insert into public.rm_cn_decision_lines "
                        "(decision_id, gs_item_id, decision_code, qty) values (:d,:i,:c,:q)"
                    ),
                    {"d": dec_id, "i": item_id, "c": code, "q": qty},
                )
        if issue_cn:
            cn_id = uuid.uuid4()
            conn.execute(
                text(
                    "insert into public.credit_notes (id, gs_id, cn_type_code, total_value, "
                    "created_by) values (:id, :gs, 'GENERAL_CN', 1180.00, :a)"
                ),
                {"id": cn_id, "gs": gs_id, "a": actor},
            )
            line_id = uuid.uuid4()
            conn.execute(
                text(
                    "insert into public.credit_note_lines (id, credit_note_id, gs_item_id, "
                    "line_no, qty, rate) values (:id, :cn, :item, 1, :q, 500)"
                ),
                {"id": line_id, "cn": cn_id, "item": item_id, "q": allow_qty},
            )
            conn.execute(
                text(
                    "insert into public.rate_verifications (credit_note_line_id, reference_code, "
                    "ref_doc_no, ref_doc_date, rate, verified_by) "
                    "values (:l, 'RATE_PURCHASE', 'PO-307', current_date, 500, :a)"
                ),
                {"l": line_id, "a": actor},
            )
            conn.execute(
                text(
                    "update public.credit_notes set status = 'ISSUED', cn_no = :no, "
                    "cn_date = :d, issued_by = :a, issued_at = now() where id = :id"
                ),
                {"id": cn_id, "no": f"CN-{gs_id.hex[:6]}", "d": date(2026, 11, 5), "a": actor},
            )
        if deny_qty and dispatch:
            disp_id = uuid.uuid4()
            conn.execute(
                text(
                    "insert into public.replacement_dispatches (id, dispatch_no, gs_id, "
                    "dispatch_type, transporter, docket_no, dispatched_by) "
                    "values (:id, :no, :gs, 'SEND_NEW', 'DTDC', 'DK-307', :a)"
                ),
                {"id": disp_id, "no": f"DSP-{gs_id.hex[:6]}", "gs": gs_id, "a": actor},
            )
            conn.execute(
                text(
                    "insert into public.replacement_dispatch_lines (dispatch_id, gs_item_id, qty) "
                    "values (:d, :i, :q)"
                ),
                {"d": disp_id, "i": item_id, "q": deny_qty},
            )
    if csr and csr_handover:
        # The custody engine (P3-01, tested there) produces this ACCEPTED transfer; the fixture
        # records the end state directly with triggers suspended for this one statement block.
        conn.execute(text("set local session_replication_role = replica"))
        conn.execute(
            text(
                """
                insert into public.custody_transfers (transfer_no, from_location_id,
                    to_location_id, status, initiated_by, accepted_by, accepted_at,
                    acceptance_code, gs_id, purpose_code, with_packaging, stock_moved)
                values (:no, :f, :t, 'ACCEPTED', :a, :a, now(), 'ACCEPTED_VERIFIED', :gs,
                        'CSR_WITH_PACKAGING', true, true)
                """
            ),
            {
                "no": f"TR-{gs_id.hex[:8]}",
                "f": _loc(conn, "INWARD_STAGING"),
                "t": _loc(conn, "INTERMEDIATE_STORE"),
                "a": actor,
                "gs": gs_id,
            },
        )
        conn.execute(text("set local session_replication_role = origin"))
    if csr and csr_packaging_check:
        conn.execute(
            text(
                'insert into public.packaging_replacements (lot_id, qty, result_code, "by") '
                "values (:lot, 0, 'OK', :a)"
            ),
            {"lot": lot_id, "a": actor},
        )
    return {
        "gs_id": gs_id,
        "gs_no": gs_no,
        "item_id": item_id,
        "stock_item_id": stock_item_id,
        "lot_id": lot_id,
        "cn_id": cn_id,
    }


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": f"p307-{uuid.uuid4().hex}"}


async def _notify(client: AsyncClient, actors: Actors, gs: dict[str, Any]) -> dict[str, Any]:
    res = await client.post(
        f"/api/v1/gs/{gs['gs_id']}/party-notifications",
        json={
            "credit_note_id": str(gs["cn_id"]),
            "channel": "WHATSAPP",
            "recipient": "+91 98100 00000",
        },
        headers={**_auth(actors.accounts), **_idem()},
    )
    assert res.status_code == 201, res.text
    return dict(res.json())


async def _close(client: AsyncClient, token: str, gs_id: uuid.UUID) -> Any:
    return await client.post(
        f"/api/v1/gs/{gs_id}/close", json={}, headers={**_auth(token), **_idem()}
    )


def _failed_codes(res: Any) -> list[str]:
    body = res.json()["error"]
    assert body["code"] == "G-15", body
    return [i["code"] for i in body["details"]["failed_items"]]


def _status(conn: Connection, gs_id: uuid.UUID) -> str:
    return str(
        as_admin(conn)
        .execute(text("select status from public.goods_slips where id = :id"), {"id": gs_id})
        .scalar_one()
    )


# ------------------------------------------------------------------------------------------------
# Party notification (BR-38, DEC-25)
# ------------------------------------------------------------------------------------------------


async def test_notification_state_and_record(
    client: AsyncClient, actors: Actors, db_conn: Connection
) -> None:
    gs = _build_gs(db_conn, actors.rm_id)
    res = await client.get(
        f"/api/v1/gs/{gs['gs_id']}/party-notifications", headers=_auth(actors.accounts)
    )
    assert res.status_code == 200, res.text
    state = res.json()
    assert state["can_record"] is True
    assert state["recipient"]["email"] == "ravi@p307.example"
    assert state["recipient"]["phone"] == "+91 98100 00000"
    assert state["status_label"] == "Prior Information Sent with CN Details"  # DD r79
    draft = state["drafts"][0]
    assert draft["credit_note_id"] == str(gs["cn_id"]) and draft["notified"] is False
    assert f"CN-{gs['gs_id'].hex[:6]}" in draft["message"]
    assert "05-11-2026" in draft["message"]
    assert "Replacement dispatch DSP-" in draft["message"]  # dispatch details where relevant

    note = await _notify(client, actors, gs)
    assert note["status_code"] == "PRIOR_INFO_SENT"
    assert note["delivery_mode"] == "RECORDED_MANUALLY"
    snap = note["message_snapshot"]
    assert snap["credit_note"]["voucher_no"] == f"CN-{gs['gs_id'].hex[:6]}"
    assert snap["credit_note"]["voucher_date"] == "2026-11-05"
    assert snap["items"][0]["qty"] == 2
    assert snap["dispatches"][0]["qty"] == 2

    # Only the S6_NOTIFY performer (Accounts) records it.
    res = await client.post(
        f"/api/v1/gs/{gs['gs_id']}/party-notifications",
        json={"credit_note_id": str(gs["cn_id"]), "channel": "PHONE", "recipient": "9810000000"},
        headers={**_auth(actors.rm), **_idem()},
    )
    assert res.status_code == 403, res.text


async def test_notification_validation(
    client: AsyncClient, actors: Actors, db_conn: Connection
) -> None:
    gs = _build_gs(db_conn, actors.rm_id)
    url = f"/api/v1/gs/{gs['gs_id']}/party-notifications"
    hdr = _auth(actors.accounts)
    # Invalid e-mail for the EMAIL channel.
    res = await client.post(
        url,
        json={"credit_note_id": str(gs["cn_id"]), "channel": "EMAIL", "recipient": "not-mail"},
        headers={**hdr, **_idem()},
    )
    assert res.status_code == 422 and res.json()["error"]["details"]["recipient"]
    # A credit note of another GS / unknown → 422.
    res = await client.post(
        url,
        json={"credit_note_id": str(uuid.uuid4()), "channel": "OTHER", "recipient": "Courier"},
        headers={**hdr, **_idem()},
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "CREDIT_NOTE_NOT_ISSUED"
    # A proof that is not a confirmed NOTIFICATION_PROOF → 422.
    res = await client.post(
        url,
        json={
            "credit_note_id": str(gs["cn_id"]),
            "channel": "LETTER",
            "recipient": "P307 Traders, Delhi",
            "proof_attachment_id": str(uuid.uuid4()),
        },
        headers={**hdr, **_idem()},
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "PROOF_NOT_CONFIRMED"
    # Missing Idempotency-Key → 422 (commercial command).
    res = await client.post(
        url,
        json={"credit_note_id": str(gs["cn_id"]), "channel": "OTHER", "recipient": "Courier"},
        headers=hdr,
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


async def test_notification_with_confirmed_proof(
    client: AsyncClient, actors: Actors, db_conn: Connection
) -> None:
    gs = _build_gs(db_conn, actors.rm_id)
    att_id = uuid.uuid4()
    as_admin(db_conn).execute(
        text(
            """
            insert into public.attachments (id, gs_id, kind, bucket, object_path, mime_type,
                                            size_bytes, status, confirmed_at, uploaded_by)
            values (:id, :gs, 'NOTIFICATION_PROOF', 'rms-documents', :path, 'image/png', 1024,
                    'CONFIRMED', now(), :by)
            """
        ),
        {
            "id": att_id,
            "gs": gs["gs_id"],
            "path": f"gs/{gs['gs_id']}/notification_proof/{uuid.uuid4()}.png",
            "by": actors.accounts_id,
        },
    )
    res = await client.post(
        f"/api/v1/gs/{gs['gs_id']}/party-notifications",
        json={
            "credit_note_id": str(gs["cn_id"]),
            "channel": "EMAIL",
            "recipient": "ravi@p307.example",
            "message": "Edited text: CN details attached.",
            "proof_attachment_id": str(att_id),
        },
        headers={**_auth(actors.accounts), **_idem()},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["proof_attachment_id"] == str(att_id)
    assert body["message"] == "Edited text: CN details attached."


async def test_proof_upload_confirm_and_notify(
    client: AsyncClient, actors: Actors, db_conn: Connection, storage: FakeStorage
) -> None:
    """DEC-25: proof upload (signed URL) → confirm → cited by the notification."""
    gs = _build_gs(db_conn, actors.rm_id)
    body = {"mime_type": "application/pdf", "size_bytes": 2048, "file_name": "proof.pdf"}
    url = f"/api/v1/gs/{gs['gs_id']}/attachments/notification-proof/upload-url"
    res = await client.post(url, json=body, headers=_auth(actors.tech))
    assert res.status_code == 403, res.text
    res = await client.post(
        url, json={**body, "mime_type": "video/mp4"}, headers=_auth(actors.accounts)
    )
    assert res.status_code == 422, res.text
    res = await client.post(url, json=body, headers=_auth(actors.accounts))
    assert res.status_code == 201, res.text
    ticket = res.json()
    att = ticket["attachment"]
    assert att["kind"] == "NOTIFICATION_PROOF" and att["status"] == "PENDING_UPLOAD"
    path = ticket["upload"]["object_path"]
    assert path.startswith(f"gs/{gs['gs_id']}/notification_proof/")

    # Citing an unconfirmed proof is rejected.
    res = await client.post(
        f"/api/v1/gs/{gs['gs_id']}/party-notifications",
        json={
            "credit_note_id": str(gs["cn_id"]),
            "channel": "EMAIL",
            "recipient": "ravi@p307.example",
            "proof_attachment_id": att["id"],
        },
        headers={**_auth(actors.accounts), **_idem()},
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "PROOF_NOT_CONFIRMED"

    storage.put(ticket["upload"]["bucket"], path, 2048, "application/pdf")
    res = await client.post(
        f"/api/v1/attachments/{att['id']}/confirm", json={}, headers=_auth(actors.accounts)
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "CONFIRMED"

    res = await client.post(
        f"/api/v1/gs/{gs['gs_id']}/party-notifications",
        json={
            "credit_note_id": str(gs["cn_id"]),
            "channel": "EMAIL",
            "recipient": "ravi@p307.example",
            "proof_attachment_id": att["id"],
        },
        headers={**_auth(actors.accounts), **_idem()},
    )
    assert res.status_code == 201, res.text
    assert res.json()["proof_attachment_id"] == att["id"]


async def test_notification_db_guards(
    client: AsyncClient, actors: Actors, db_conn: Connection
) -> None:
    gs = _build_gs(db_conn, actors.rm_id)
    note = await _notify(client, actors, gs)
    conn = as_admin(db_conn)
    # Append-only (BR-38 evidence).
    with pytest.raises(DBAPIError, match="append-only"), conn.begin_nested():
        conn.execute(
            text("update public.party_notifications set recipient = 'x' where id = :id"),
            {"id": note["id"]},
        )
    # A DRAFT credit note cannot be notified.
    draft_id = uuid.uuid4()
    conn.execute(
        text(
            "insert into public.credit_notes (id, gs_id, cn_type_code, created_by) "
            "values (:id, :gs, 'GENERAL_CN', :a)"
        ),
        {"id": draft_id, "gs": gs["gs_id"], "a": actors.rm_id},
    )
    with pytest.raises(DBAPIError, match="BR-38"), conn.begin_nested():
        conn.execute(
            text(
                """
                    insert into public.party_notifications (gs_id, credit_note_id, channel_code,
                        recipient, message, message_snapshot, sent_by)
                    values (:gs, :cn, 'OTHER', 'x', 'x', '{}'::jsonb, :a)
                    """
            ),
            {"gs": gs["gs_id"], "cn": draft_id, "a": actors.accounts_id},
        )


# ------------------------------------------------------------------------------------------------
# Closure happy paths (BR-38, BR-39)
# ------------------------------------------------------------------------------------------------


async def test_ro_close_happy_path(
    client: AsyncClient, actors: Actors, db_conn: Connection
) -> None:
    gs = _build_gs(db_conn, actors.rm_id)

    # A CN-path GS cannot close without the prior notification; the status automation moves
    # it to AWAITING_NOTIFICATION on the way (§6.5).
    res = await _close(client, actors.rm, gs["gs_id"])
    assert res.status_code == 422, res.text
    assert _failed_codes(res) == ["PRIOR_NOTIFICATION"]
    assert _status(db_conn, gs["gs_id"]) == "AWAITING_NOTIFICATION"

    await _notify(client, actors, gs)
    state = (await client.get(f"/api/v1/gs/{gs['gs_id']}/closure", headers=_auth(actors.rm))).json()
    assert state["all_passed"] is True and state["can_close"] is True
    assert state["expected_closure_type"] == "RO_CLOSED"

    # Roles outside gs_closure_roles cannot close.
    res = await _close(client, actors.tech, gs["gs_id"])
    assert res.status_code == 403, res.text

    key = _idem()
    res = await client.post(
        f"/api/v1/gs/{gs['gs_id']}/close",
        json={"remarks": "All settled"},
        headers={**_auth(actors.accounts), **key},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "CLOSED"
    assert body["closure"]["closure_type"] == "RO_CLOSED"
    snap = body["closure"]["checklist_snapshot"]
    assert snap["status_before"] == "AWAITING_NOTIFICATION"
    assert all(i["passed"] or not i["applicable"] for i in snap["items"])
    assert snap["notifications"][0]["channel_code"] == "WHATSAPP"
    assert [s["status"] for s in body["lifecycle"]][-2:] == ["AWAITING_NOTIFICATION", "CLOSED"]
    assert body["can_reopen"] is False

    # G-16 idempotency: the same key returns the original result.
    again = await client.post(
        f"/api/v1/gs/{gs['gs_id']}/close",
        json={"remarks": "All settled"},
        headers={**_auth(actors.accounts), **key},
    )
    assert again.status_code == 200 and again.headers.get("Idempotency-Replayed") == "true"

    conn = as_admin(db_conn)
    row = conn.execute(
        text("select status, closure_type, closed_at from public.goods_slips where id = :id"),
        {"id": gs["gs_id"]},
    ).one()
    assert row.status == "CLOSED" and row.closure_type == "RO_CLOSED" and row.closed_at
    open_tasks = conn.execute(
        text("select count(*) from public.workflow_tasks where gs_id = :id and status = 'OPEN'"),
        {"id": gs["gs_id"]},
    ).scalar_one()
    assert open_tasks == 0
    # Closing twice → 409.
    res = await _close(client, actors.rm, gs["gs_id"])
    assert res.status_code == 409 and res.json()["error"]["code"] == "GS_ALREADY_CLOSED"


async def test_csr_close_happy_path(
    client: AsyncClient, actors: Actors, db_conn: Connection
) -> None:
    gs = _build_gs(db_conn, actors.rm_id, csr=True)
    await _notify(client, actors, gs)
    res = await _close(client, actors.rm, gs["gs_id"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["closure"]["closure_type"] == "CSR_CLOSED"
    # DD r80 label comes from the CSR_FINAL_STATUS option set.
    assert (
        body["closure"]["closure_label"]
        == "Inward to Inventory with Packaging + CN Issued + Prior Party Info"
    )
    codes = {i["code"]: i for i in body["closure"]["checklist_snapshot"]["items"]}
    for code in ("CSR_PACKAGING_HANDOVER", "CSR_PACKAGING_CHECK", "CSR_CN_ISSUED"):
        assert codes[code]["applicable"] and codes[code]["passed"]


# ------------------------------------------------------------------------------------------------
# Each checklist item failing on its own (G-15)
# ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("build", "expected"),
    [
        ({"status": "RM_REVIEW"}, "GS_STATUS"),
        ({"with_decision": False}, "CN_DECISION_RECORDED"),
        ({"issue_cn": False}, "ALLOW_CN_COVERED"),
        ({"dispatch": False}, "DENY_QTY_DISPATCHED"),
    ],
)
async def test_single_failing_item_from_build(
    client: AsyncClient,
    actors: Actors,
    db_conn: Connection,
    build: dict[str, Any],
    expected: str,
) -> None:
    gs = _build_gs(db_conn, actors.rm_id, **build)
    if gs["cn_id"] and build.get("status") is None:
        await _notify(client, actors, gs)
    if build.get("status") == "RM_REVIEW":
        # Notification cannot be recorded outside the commercial stages; record it in SQL.
        as_admin(db_conn).execute(
            text(
                """
                insert into public.party_notifications (gs_id, credit_note_id, channel_code,
                    recipient, message, message_snapshot, sent_by)
                values (:gs, :cn, 'OTHER', 'x', 'x', '{}'::jsonb, :a)
                """
            ),
            {"gs": gs["gs_id"], "cn": gs["cn_id"], "a": actors.accounts_id},
        )
    res = await _close(client, actors.rm, gs["gs_id"])
    assert res.status_code == 422, res.text
    assert _failed_codes(res) == [expected]


@pytest.mark.parametrize(
    "perturb",
    ["transit", "not_terminal", "hold_without_disposition", "pendency", "discrepancy"],
)
async def test_single_failing_item_from_state(
    client: AsyncClient, actors: Actors, db_conn: Connection, perturb: str
) -> None:
    gs = _build_gs(db_conn, actors.rm_id)
    await _notify(client, actors, gs)
    conn = as_admin(db_conn)
    extra = {
        "gs_id": gs["gs_id"],
        "item_id": gs["item_id"],
        "stock_item_id": gs["stock_item_id"],
        "actor": actors.rm_id,
        "qty": 1,
    }
    expected = {
        "transit": "STOCK_NOT_IN_TRANSIT",
        "not_terminal": "STOCK_ACCOUNTED",
        "hold_without_disposition": "STOCK_ACCOUNTED",
        "pendency": "NO_OPEN_PENDENCY",
        "discrepancy": "NO_OPEN_DISCREPANCY",
    }[perturb]
    if perturb == "transit":
        _inward(conn, condition="AS_RECEIVED", location="INWARD_STAGING", **extra)
    elif perturb == "not_terminal":
        _inward(conn, condition="FUNCTIONAL_GOOD", location="INTERMEDIATE_STORE", **extra)
    elif perturb == "hold_without_disposition":
        _inward(conn, condition="NOT_ALLOWED", location="REJECTED_HOLD", **extra)
    elif perturb == "pendency":
        conn.execute(
            text(
                "insert into public.pendencies (gs_id, gs_item_id, qty, reason, opened_by) "
                "values (:gs, :item, 1, 'Waiting for party', :a)"
            ),
            {"gs": gs["gs_id"], "item": gs["item_id"], "a": actors.rm_id},
        )
    else:
        conn.execute(
            text("update public.goods_slips set has_discrepancy = true where id = :id"),
            {"id": gs["gs_id"]},
        )
    res = await _close(client, actors.rm, gs["gs_id"])
    assert res.status_code == 422, res.text
    assert _failed_codes(res) == [expected]


@pytest.mark.parametrize(
    ("build", "expected"),
    [
        ({"csr_handover": False}, "CSR_PACKAGING_HANDOVER"),
        ({"csr_packaging_check": False}, "CSR_PACKAGING_CHECK"),
    ],
)
async def test_csr_failing_items(
    client: AsyncClient,
    actors: Actors,
    db_conn: Connection,
    build: dict[str, Any],
    expected: str,
) -> None:
    gs = _build_gs(db_conn, actors.rm_id, csr=True, **build)
    await _notify(client, actors, gs)
    res = await _close(client, actors.rm, gs["gs_id"])
    assert res.status_code == 422, res.text
    assert _failed_codes(res) == [expected]


async def test_csr_without_cn_lists_every_failure(
    client: AsyncClient, actors: Actors, db_conn: Connection
) -> None:
    """BR-39: no CN → CSR_CN_ISSUED fails (with the uncovered ALLOW_CN qty); all failures listed."""
    gs = _build_gs(db_conn, actors.rm_id, csr=True, issue_cn=False, csr_packaging_check=False)
    res = await _close(client, actors.rm, gs["gs_id"])
    assert res.status_code == 422, res.text
    assert _failed_codes(res) == ["ALLOW_CN_COVERED", "CSR_PACKAGING_CHECK", "CSR_CN_ISSUED"]


# ------------------------------------------------------------------------------------------------
# Reopen (Super Admin + reason, audited) and the DB half of G-15
# ------------------------------------------------------------------------------------------------


async def test_reopen_super_admin_only_and_audited(
    client: AsyncClient, actors: Actors, db_conn: Connection
) -> None:
    gs = _build_gs(db_conn, actors.rm_id)
    await _notify(client, actors, gs)
    assert (await _close(client, actors.rm, gs["gs_id"])).status_code == 200
    url = f"/api/v1/gs/{gs['gs_id']}/reopen"

    res = await client.post(url, json={"reason": "Party disputes"}, headers=_auth(actors.rm))
    assert res.status_code == 403 and res.json()["error"]["code"] == "SUPER_ADMIN_REQUIRED"
    res = await client.post(url, json={"reason": "x"}, headers=_auth(actors.admin))
    assert res.status_code == 422

    res = await client.post(
        url, json={"reason": "Party disputes the CN amount"}, headers=_auth(actors.admin)
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "COMMERCIAL_RESOLUTION"
    assert body["closure"]["reopen_reason"] == "Party disputes the CN amount"
    assert body["closure"]["reopened_by_name"] == "P307 Super Admin"
    assert body["closure"]["reopen_count"] == 1

    conn = as_admin(db_conn)
    audit = conn.execute(
        text(
            "select count(*) from public.audit_log where table_name = 'public.gs_closures' "
            "and reason like 'GS reopened:%'"
        )
    ).scalar_one()
    assert audit >= 1
    hist = conn.execute(
        text(
            "select reason from public.gs_status_history where gs_id = :id "
            "and from_status = 'CLOSED' and to_status = 'COMMERCIAL_RESOLUTION'"
        ),
        {"id": gs["gs_id"]},
    ).scalar_one()
    assert "Party disputes" in hist

    # Close again: the record keeps the reopen fields and counts the closures.
    res = await _close(client, actors.rm, gs["gs_id"])
    assert res.status_code == 200, res.text
    assert res.json()["closure"]["close_count"] == 2
    assert res.json()["closure"]["reopen_reason"] == "Party disputes the CN amount"


async def test_g15_db_guard_rejects_direct_close(
    client: AsyncClient, actors: Actors, db_conn: Connection
) -> None:
    """G-15 is enforced in the database: no API, role or Super Admin is involved here."""
    gs = _build_gs(db_conn, actors.rm_id)  # notification missing
    conn = as_admin(db_conn)
    with pytest.raises(DBAPIError, match="G-15"), conn.begin_nested():
        conn.execute(
            text(
                "update public.goods_slips set status = 'CLOSED', closure_type = 'RO_CLOSED', "
                "closed_at = now() where id = :id"
            ),
            {"id": gs["gs_id"]},
        )
    await _notify(client, actors, gs)
    conn = as_admin(db_conn)
    # Checklist passes, but there is no closure record yet → still rejected.
    with pytest.raises(DBAPIError, match="closure record"), conn.begin_nested():
        conn.execute(
            text(
                "update public.goods_slips set status = 'CLOSED', closure_type = 'RO_CLOSED', "
                "closed_at = now() where id = :id"
            ),
            {"id": gs["gs_id"]},
        )
    assert (await _close(client, actors.rm, gs["gs_id"])).status_code == 200
    conn = as_admin(db_conn)
    # A CLOSED GS cannot be moved out without a recorded reopen.
    with pytest.raises(DBAPIError, match="G-15"), conn.begin_nested():
        conn.execute(
            text("update public.goods_slips set status = 'IN_PROCESS' where id = :id"),
            {"id": gs["gs_id"]},
        )
    # A reopen recorded by a non-Super-Admin is rejected by gs_closures_guard.
    with pytest.raises(DBAPIError, match="Super Admin"), conn.begin_nested():
        conn.execute(
            text(
                "update public.gs_closures set reopened_by = :u, "
                "reopened_at = clock_timestamp(), reopen_reason = 'test' where gs_id = :id"
            ),
            {"id": gs["gs_id"], "u": actors.rm_id},
        )
