"""Custody transfer engine & Step-4 handover (prompt P3-01).

Master plan references: §2.2 Stage-2, DD r44-r46, BR-20..BR-22, G-08, G-09, G-16, DEC-12, DEC-14,
DEC-27. Real local Supabase Postgres, rolled back per test (tests/integration/conftest.py).
"""

from __future__ import annotations

import uuid
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
from tests.integration.test_itemization import add_line, categorize, decide
from tests.integration.test_unboxing import (
    INVOICE,
    FakeStorage,
    classify,
    complete,
    started_gs,
    upload,
    upload_videos,
)
from tests.integration.test_unboxing import Actors as BaseActors


# --- fixtures ------------------------------------------------------------------------------------
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


@dataclass
class Actors(BaseActors):
    sahil: str
    sahil_id: uuid.UUID
    both: str  # holds the Inward Verifier AND Intermediate Store Manager roles (SoD test)


@pytest.fixture
def actors(users: UserFactory, make_token: JwtFactory) -> Actors:
    aman_id = users.create(roles=["INWARD_VERIFIER"], full_name="Aman")
    rm_id = users.create(roles=["REPLACEMENT_MANAGER"], full_name="Pratham")
    acc_id = users.create(roles=["ACCOUNTS"], full_name="Deepak")
    sahil_id = users.create(roles=["INTERMEDIATE_STORE_MANAGER"], full_name="Sahil")
    both_id = users.create(
        roles=["INWARD_VERIFIER", "INTERMEDIATE_STORE_MANAGER"], full_name="Dual Role"
    )
    return Actors(
        gate=make_token(users.create(roles=["GATE_INWARD"], full_name="Anuj")),
        aman=make_token(aman_id),
        aman_id=aman_id,
        rm=make_token(rm_id),
        rm_id=rm_id,
        accounts=make_token(acc_id),
        accounts_id=acc_id,
        admin=make_token(users.create(super_admin=True, full_name="Admin")),
        sahil=make_token(sahil_id),
        sahil_id=sahil_id,
        both=make_token(both_id),
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
                {
                    "code": f"P-{category}-{tag}",
                    "name": f"Product {category} {tag}",
                    "cat": category,
                },
            ).scalar_one()
        )

    return Products(dmt=make("DMT"), prismatic=make("PRISMATIC"))


def key() -> str:
    return f"test-{uuid.uuid4()}"


# --- helpers -------------------------------------------------------------------------------------
async def inspect(
    client: AsyncClient, token: str, item_id: str, allocations: list[tuple[str, int]]
) -> None:
    total = sum(q for _, q in allocations)
    res = await client.put(
        f"/api/v1/gs-items/{item_id}/inspection",
        headers=_auth(token),
        json={
            "allocations": [{"condition_code": c, "qty": q} for c, q in allocations],
            "extraction": {
                "primary_type": "PACKAGING_EXTRACTED",
                "packaging_qty": total,
                "container_qty": 0,
            },
        },
    )
    assert res.status_code == 200, res.text
    res = await client.post(
        f"/api/v1/gs-items/{item_id}/inspection/finalise", headers=_auth(token, key())
    )
    assert res.status_code == 200, res.text


async def ro_in_process(
    client: AsyncClient,
    storage: FakeStorage,
    a: Actors,
    m: Masters,
    p: Products,
    *,
    pending: int = 2,
) -> tuple[str, str, str]:
    """RO GS at IN_PROCESS (RM actions finalised). DMT line 10: OK packed 6, dirty 2, other brands
    1 (not allowed → REJECTED_HOLD), broken body 1 (→ NON_FUNCTIONAL); `pending` of the OK pieces
    are Pending (BP). Prismatic line 4: OK 3, broken with mercury 1 (→ HAZARD_QUARANTINE)."""
    gs_id = await started_gs(client, a, m)
    await upload_videos(client, storage, a.aman, gs_id)
    photo = await upload(client, storage, a.aman, gs_id, "DOC_PHOTO", "image/jpeg")
    assert (await classify(client, a.aman, gs_id, photo["id"], INVOICE)).status_code == 201
    assert (await complete(client, a.aman, gs_id)).status_code == 200
    dmt = (await add_line(client, a.aman, gs_id, p.dmt, 10, 10)).json()["id"]
    prs = (await add_line(client, a.aman, gs_id, p.prismatic, 4, 4)).json()["id"]
    assert (await categorize(client, a.aman, gs_id, "RO")).status_code == 200
    await inspect(
        client,
        a.aman,
        dmt,
        [("DMT_OK_PACKED", 6), ("DMT_DIRTY", 2), ("DMT_OTHER_BRANDS", 1), ("DMT_BROKEN_BODY", 1)],
    )
    await inspect(client, a.aman, prs, [("PRS_OK", 3), ("PRS_BROKEN_WITH_HG", 1)])
    dmt_actions = [
        {"action_code": "SEND_NEW", "qty": 8 - pending},
        {"action_code": "NOT_ALLOWED", "qty": 2},
    ]
    if pending:
        dmt_actions.append({"action_code": "PENDING_BP", "qty": pending})
    body: dict[str, Any] = {
        "lines": [
            {"gs_item_id": dmt, "actions": dmt_actions},
            {
                "gs_item_id": prs,
                "actions": [
                    {"action_code": "SEND_NEW", "qty": 3},
                    {"action_code": "NOT_ALLOWED", "qty": 1},
                ],
            },
        ]
    }
    if pending:
        body["pendency_details"] = {
            dmt: {"reason": "Checking with Repair Team", "sent_to": "Repair"}
        }
    res = await client.put(f"/api/v1/gs/{gs_id}/rm-actions", headers=_auth(a.rm), json=body)
    assert res.status_code == 200, res.text
    res = await client.post(f"/api/v1/gs/{gs_id}/rm-actions/finalise", headers=_auth(a.rm))
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "IN_PROCESS"
    return gs_id, dmt, prs


def location_qty(conn: Connection, gs_id: str) -> dict[str, int]:
    rows = fetch_all(
        conn,
        """select l.code, sum(b.qty)::int as qty from public.stock_balances b
             join public.stock_lots lot on lot.id = b.lot_id
             join public.inventory_locations l on l.id = b.location_id
            where lot.gs_id = :g and b.qty > 0 group by l.code""",
        g=gs_id,
    )
    return {r["code"]: r["qty"] for r in rows}


def tasks(conn: Connection, gs_id: str) -> list[tuple[str, str | None, str]]:
    rows = fetch_all(
        conn,
        """select t.step_code, r.code as role, t.status from public.workflow_tasks t
             left join public.roles r on r.id = t.assigned_role_id
            where t.gs_id = :g and t.step_code = 'S2_HANDOVER' order by t.created_at""",
        g=gs_id,
    )
    # Tasks of one transaction share created_at: compare as a sorted list.
    return sorted((r["step_code"], r["role"], r["status"]) for r in rows)


def notified(conn: Connection, user_id: uuid.UUID, type_: str) -> int:
    return int(
        as_admin(conn)
        .execute(
            text("select count(*) from public.notifications where user_id = :u and type = :t"),
            {"u": user_id, "t": type_},
        )
        .scalar_one()
    )


async def handover(client: AsyncClient, token: str, gs_id: str, **body: Any) -> Any:
    return await client.post(f"/api/v1/gs/{gs_id}/handover", headers=_auth(token, key()), json=body)


async def accept(
    client: AsyncClient,
    token: str,
    transfer: dict[str, Any],
    counts: dict[str, int] | None = None,
    code: str = "ACCEPTED_VERIFIED",
    notes: str | None = None,
    idem: str | None = None,
) -> Any:
    lines = [
        {"lot_id": ln["lot_id"], "qty_counted": (counts or {}).get(ln["lot_id"], ln["qty_sent"])}
        for ln in transfer["lines"]
    ]
    return await client.post(
        f"/api/v1/custody/transfers/{transfer['id']}/accept",
        headers=_auth(token, idem or key()),
        json={"lines": lines, "acceptance_code": code, "notes": notes},
    )


async def reconcile(client: AsyncClient, token: str, transfer_id: str, **body: Any) -> Any:
    return await client.post(
        f"/api/v1/custody/transfers/{transfer_id}/reconcile",
        headers=_auth(token, key()),
        json=body,
    )


async def discrepancy(
    client: AsyncClient, a: Actors, storage: FakeStorage, m: Masters, p: Products
) -> tuple[str, dict[str, Any]]:
    """A dispatched RO handover whose first line Sahil counted one short."""
    gs_id, _, _ = await ro_in_process(client, storage, a, m, p, pending=0)
    transfer = (await handover(client, a.aman, gs_id)).json()
    first = transfer["lines"][0]
    res = await accept(
        client,
        a.sahil,
        transfer,
        counts={first["lot_id"]: first["qty_sent"] - 1},
        code="DISCREPANCY",
        notes="One piece missing from the carton",
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "DISCREPANCY"
    return gs_id, res.json()


# --- tests ---------------------------------------------------------------------------------------
async def test_handover_exclusions_clean_accept_and_idempotency(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    db_conn: Connection,
) -> None:
    """BR-20/BR-22/G-09: exclusions with reasons; in transit after initiation; clean accept."""
    gs_id, dmt, prs = await ro_in_process(client, storage, actors, masters, products)
    assert tasks(db_conn, gs_id) == [("S2_HANDOVER", "INWARD_VERIFIER", "OPEN")]

    preview = (await client.get(f"/api/v1/gs/{gs_id}/handover", headers=_auth(actors.aman))).json()
    assert preview["blocked"] is None and preview["can_initiate"] is True
    assert (preview["from_location_code"], preview["to_location_code"]) == (
        "INWARD_STAGING",
        "INTERMEDIATE_STORE",
    )
    eligible = {(e["gs_item_id"], e["condition_code"]): e["qty"] for e in preview["eligible"]}
    # 6 OK packed + 2 dirty - 2 pending on DMT; 3 OK on Prismatic.
    assert sum(q for (i, _), q in eligible.items() if i == dmt) == 6
    assert eligible[(prs, "PRS_OK")] == 3
    reasons = sorted((x["reason_code"], x["qty"]) for x in preview["excluded"])
    assert reasons == [("HAZARD", 1), ("NOT_ALLOWED", 1), ("NOT_ALLOWED", 1), ("PENDING_BP", 2)]
    pend = next(x for x in preview["excluded"] if x["reason_code"] == "PENDING_BP")
    # G4 (DEC-57): PENDING_BP is labelled "Pending" (code unchanged).
    assert pend["reason_label"] == "Pending" and "Repair Team" in (pend["detail"] or "")
    hazard = next(x for x in preview["excluded"] if x["reason_code"] == "HAZARD")
    assert hazard["location_code"] == "HAZARD_QUARANTINE" and hazard["condition_label"]

    # Sahil cannot initiate from Aman's location.
    res = await handover(client, actors.sahil, gs_id)
    assert res.status_code == 403 and res.json()["error"]["code"] == "NOT_LOCATION_CUSTODIAN"

    res = await handover(client, actors.aman, gs_id)
    assert res.status_code == 201, res.text
    transfer = res.json()
    assert transfer["status"] == "INITIATED" and transfer["stock_moved"] is True
    assert transfer["transfer_no"].startswith("TRF/")
    assert transfer["mode_code"] == "PHYSICAL_AND_DIGITAL" and transfer["mode_label"]
    assert transfer["total_qty"] == 9 and transfer["permissions"]["can_cancel"] is True
    # In transit: neither Aman's nor Sahil's custody.
    q = location_qty(db_conn, gs_id)
    assert q.get("TRANSIT") == 9 and "INWARD_STAGING" not in q and "INTERMEDIATE_STORE" not in q
    assert q["PENDING_HOLD"] == 2 and q["HAZARD_QUARANTINE"] == 1
    # Sahil has a task and a notification; Aman's Step-4 task is done.
    assert tasks(db_conn, gs_id) == [
        ("S2_HANDOVER", "INTERMEDIATE_STORE_MANAGER", "OPEN"),
        ("S2_HANDOVER", "INWARD_VERIFIER", "DONE"),
    ]
    assert notified(db_conn, actors.sahil_id, "TRANSFER_INITIATED") == 1
    gs = fetch_all(db_conn, "select status from public.goods_slips where id = :g", g=gs_id)
    assert gs == [{"status": "IN_PROCESS"}]

    mine = (
        await client.get(
            "/api/v1/custody/transfers",
            params={"mine_to_accept": "true"},
            headers=_auth(actors.sahil),
        )
    ).json()
    assert [t["id"] for t in mine["items"]] == [transfer["id"]]
    not_mine = (
        await client.get(
            "/api/v1/custody/transfers",
            params={"mine_to_accept": "true"},
            headers=_auth(actors.aman),
        )
    ).json()
    assert not_mine["total"] == 0

    # Aman (no custody.approve) cannot accept.
    assert (await accept(client, actors.aman, transfer)).status_code == 403

    idem = key()
    res = await accept(client, actors.sahil, transfer, idem=idem)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "ACCEPTED" and body["acceptance_code"] == "ACCEPTED_VERIFIED"
    assert body["acceptance_label"] == "Accepted - Quantity & Lots Verified"
    assert all(ln["qty_accepted"] == ln["qty_sent"] for ln in body["lines"])
    q = location_qty(db_conn, gs_id)
    assert q.get("INTERMEDIATE_STORE") == 9 and "TRANSIT" not in q
    assert ("S2_HANDOVER", "INTERMEDIATE_STORE_MANAGER", "DONE") in tasks(db_conn, gs_id)
    assert notified(db_conn, actors.aman_id, "TRANSFER_ACCEPTED") == 1

    # Double accept: the same key replays the original response; a new key is refused.
    replay = await accept(client, actors.sahil, transfer, idem=idem)
    assert replay.status_code == 200 and replay.headers.get("Idempotency-Replayed") == "true"
    assert replay.json()["status"] == "ACCEPTED"
    again = await accept(client, actors.sahil, transfer)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "TRANSFER_NOT_AWAITING_ACCEPTANCE"
    moved_in = fetch_all(
        db_conn,
        """select count(*)::int as n from public.stock_movements
            where reference_type = 'custody_transfer' and reference_id = :t
              and movement_type = 'TRANSFER_IN'""",
        t=transfer["id"],
    )
    assert moved_in == [{"n": len(transfer["lines"])}]

    # Nothing left to hand over (pending pieces stay held).
    preview = (await client.get(f"/api/v1/gs/{gs_id}/handover", headers=_auth(actors.aman))).json()
    assert preview["blocked"]["code"] == "NOTHING_TO_HAND_OVER"
    res = await handover(client, actors.aman, gs_id)
    assert res.status_code == 409 and res.json()["error"]["code"] == "NOTHING_TO_HAND_OVER"


async def test_segregation_of_duties_and_custodian_checks(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    db_conn: Connection,
) -> None:
    gs_id, _, _ = await ro_in_process(client, storage, actors, masters, products, pending=0)
    res = await handover(client, actors.both, gs_id)
    assert res.status_code == 201, res.text
    transfer = res.json()
    assert transfer["permissions"]["can_accept"] is False
    res = await accept(client, actors.both, transfer)
    assert res.status_code == 403 and res.json()["error"]["code"] == "SEGREGATION_OF_DUTIES"
    # The RM holds custody.approve but is not the custodian of the Intermediate Store.
    res = await accept(client, actors.rm, transfer)
    assert res.status_code == 403 and res.json()["error"]["code"] == "NOT_LOCATION_CUSTODIAN"
    # DB backstop: the trigger refuses initiator = acceptor while the setting is on.
    conn = as_admin(db_conn)
    with pytest.raises(DBAPIError, match="SEGREGATION_OF_DUTIES"), conn.begin_nested():
        conn.execute(
            text(
                """update public.custody_transfers
                      set status = 'ACCEPTED', acceptance_code = 'ACCEPTED_VERIFIED',
                          accepted_by = initiated_by, accepted_at = now()
                    where id = :t"""
            ),
            {"t": transfer["id"]},
        )
    # With the setting off the same user may accept.
    conn.execute(
        text(
            "update public.system_settings set value = 'false' "
            "where key = 'segregation_of_duties_transfer'"
        )
    )
    res = await accept(client, actors.both, transfer)
    assert res.status_code == 200, res.text


async def test_mismatch_halts_and_two_signature_loss_needs_rm(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    db_conn: Connection,
) -> None:
    """BR-21 / G-09: a mismatched count never reaches the Intermediate Store until reconciled."""
    gs_id, _, _ = await ro_in_process(client, storage, actors, masters, products, pending=0)
    transfer = (await handover(client, actors.aman, gs_id)).json()
    first = transfer["lines"][0]
    short = {first["lot_id"]: first["qty_sent"] - 1}

    res = await accept(client, actors.sahil, transfer, counts=short)
    assert res.status_code == 422 and res.json()["error"]["code"] == "TRANSFER_COUNT_MISMATCH"
    res = await accept(client, actors.sahil, transfer, counts=short, code="DISCREPANCY")
    assert res.status_code == 422
    assert "discrepancy_reason" in res.json()["error"]["details"]
    res = await accept(client, actors.sahil, transfer, code="DISCREPANCY", notes="x")
    assert res.status_code == 422 and res.json()["error"]["code"] == "TRANSFER_NO_DISCREPANCY"

    res = await accept(
        client, actors.sahil, transfer, counts=short, code="DISCREPANCY", notes="1 missing"
    )
    assert res.status_code == 200, res.text
    halted = res.json()
    assert halted["status"] == "DISCREPANCY" and halted["discrepancy_notes"] == "1 missing"
    q = location_qty(db_conn, gs_id)
    assert q.get("TRANSIT") == 11 and "INTERMEDIATE_STORE" not in q
    gs = fetch_all(db_conn, "select has_discrepancy from public.goods_slips where id = :g", g=gs_id)
    assert gs == [{"has_discrepancy": True}]
    assert notified(db_conn, actors.aman_id, "TRANSFER_DISCREPANCY") == 1
    assert notified(db_conn, actors.rm_id, "TRANSFER_DISCREPANCY") == 1
    # Frozen: cannot be accepted or cancelled now.
    assert (await accept(client, actors.sahil, transfer)).status_code == 409
    res = await client.post(
        f"/api/v1/custody/transfers/{transfer['id']}/cancel",
        headers=_auth(actors.aman, key()),
        json={"reason": "undo"},
    )
    assert res.status_code == 409

    # Two signatures: Aman proposes a write-off, Sahil co-signs, the RM approves the loss.
    body = {
        "resolution_code": "ACCEPT_COUNTED_WITH_ADJUSTMENT",
        "difference_disposition": "WRITE_OFF_LOSS",
        "notes": "Piece lost in handling",
    }
    res = await reconcile(client, actors.aman, transfer["id"], **body)
    assert res.status_code == 200, res.text
    (recon,) = res.json()["reconciliations"]
    assert recon["status"] == "PROPOSED" and recon["initiator_signed_by_name"] == "Aman"
    assert recon["requires_rm_approval"] is True
    again = await reconcile(client, actors.aman, transfer["id"], **body)
    assert (
        again.status_code == 409
        and again.json()["error"]["code"] == "RECONCILIATION_ALREADY_SIGNED"
    )
    assert (await reconcile(client, actors.accounts, transfer["id"], **body)).status_code == 403
    res = await reconcile(client, actors.sahil, transfer["id"], **body)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "DISCREPANCY"
    assert res.json()["reconciliations"][0]["status"] == "AWAITING_RM_APPROVAL"
    assert location_qty(db_conn, gs_id).get("TRANSIT") == 11

    approve = f"/api/v1/custody/transfers/{transfer['id']}/reconcile/approve"
    res = await client.post(approve, headers=_auth(actors.sahil, key()), json={"reason": "ok"})
    assert res.status_code == 403
    res = await client.post(
        approve, headers=_auth(actors.rm, key()), json={"reason": "Loss accepted, CCTV checked"}
    )
    assert res.status_code == 200, res.text
    done = res.json()
    assert done["status"] == "RECONCILED"
    assert done["resolution_code"] == "ACCEPT_COUNTED_WITH_ADJUSTMENT"
    line = next(ln for ln in done["lines"] if ln["lot_id"] == first["lot_id"])
    assert (line["qty_accepted"], line["qty_adjusted"]) == (first["qty_sent"] - 1, -1)
    q = location_qty(db_conn, gs_id)
    assert q.get("INTERMEDIATE_STORE") == 10 and "TRANSIT" not in q
    loss = fetch_all(
        db_conn,
        """select qty, reason from public.stock_movements
            where reference_id = :t and movement_type = 'ADJUST'""",
        t=transfer["id"],
    )
    assert loss == [{"qty": 1, "reason": "Loss accepted, CCTV checked"}]
    gs = fetch_all(db_conn, "select has_discrepancy from public.goods_slips where id = :g", g=gs_id)
    assert gs == [{"has_discrepancy": False}]


async def test_counter_proposal_and_return_to_source(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    db_conn: Connection,
) -> None:
    gs_id, halted = await discrepancy(client, actors, storage, masters, products)
    res = await reconcile(
        client, actors.sahil, halted["id"], resolution_code="CANCEL_RETURN", notes="Send again"
    )
    assert res.status_code == 200, res.text
    res = await reconcile(
        client,
        actors.aman,
        halted["id"],
        resolution_code="ACCEPT_COUNTED_WITH_ADJUSTMENT",
        difference_disposition="RETURN_TO_SOURCE",
        notes="The missing piece is still on my table",
    )
    recons = res.json()["reconciliations"]
    assert [r["status"] for r in recons] == ["SUPERSEDED", "PROPOSED"]
    assert recons[1]["requires_rm_approval"] is False
    res = await reconcile(
        client,
        actors.sahil,
        halted["id"],
        resolution_code="ACCEPT_COUNTED_WITH_ADJUSTMENT",
        difference_disposition="RETURN_TO_SOURCE",
        notes="Agreed",
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "RECONCILED"
    q = location_qty(db_conn, gs_id)
    assert (q.get("INTERMEDIATE_STORE"), q.get("INWARD_STAGING"), q.get("TRANSIT")) == (10, 1, None)
    # The returned piece is eligible again: Aman's Step-4 task re-opened, second handover works.
    assert ("S2_HANDOVER", "INWARD_VERIFIER", "OPEN") in tasks(db_conn, gs_id)
    second = await handover(client, actors.aman, gs_id)
    assert second.status_code == 201 and second.json()["total_qty"] == 1
    assert (await accept(client, actors.sahil, second.json())).status_code == 200
    q = location_qty(db_conn, gs_id)
    assert q.get("INTERMEDIATE_STORE") == 11 and "TRANSIT" not in q and "INWARD_STAGING" not in q


async def test_rm_override_resend_corrected(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    db_conn: Connection,
) -> None:
    gs_id, halted = await discrepancy(client, actors, storage, masters, products)
    body = {"resolution_code": "RESEND_CORRECTED", "notes": "Resend as counted", "override": True}
    res = await reconcile(client, actors.sahil, halted["id"], **body)
    assert res.status_code == 403 and res.json()["error"]["code"] == "OVERRIDE_NOT_ALLOWED"
    res = await reconcile(client, actors.rm, halted["id"], **body)
    assert res.status_code == 200, res.text
    done = res.json()
    assert done["status"] == "RECONCILED"
    (recon,) = done["reconciliations"]
    assert recon["is_rm_override"] is True and recon["rm_approved_by_name"] == "Pratham"
    resend_id = recon["resend_transfer_id"]
    assert resend_id
    audit = fetch_all(
        db_conn,
        """select reason from public.audit_log
            where table_name = 'public.custody_reconciliations'
              and reason like 'RM OVERRIDE%' limit 1""",
    )
    assert audit and "Resend as counted" in audit[0]["reason"]
    resend = (
        await client.get(f"/api/v1/custody/transfers/{resend_id}", headers=_auth(actors.aman))
    ).json()
    assert resend["supersedes_transfer_id"] == halted["id"]
    assert resend["status"] == "INITIATED" and resend["initiated_by_name"] == "Aman"
    assert resend["total_qty"] == 10  # the counted quantities
    q = location_qty(db_conn, gs_id)
    assert (q.get("TRANSIT"), q.get("INWARD_STAGING")) == (10, 1)
    res = await accept(client, actors.sahil, resend)
    assert res.status_code == 200, res.text
    q = location_qty(db_conn, gs_id)
    assert (q.get("INTERMEDIATE_STORE"), q.get("INWARD_STAGING"), q.get("TRANSIT")) == (10, 1, None)


async def test_cancel_by_initiator_only(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    db_conn: Connection,
) -> None:
    gs_id, _, _ = await ro_in_process(client, storage, actors, masters, products, pending=0)
    transfer = (await handover(client, actors.aman, gs_id)).json()
    url = f"/api/v1/custody/transfers/{transfer['id']}/cancel"
    res = await client.post(url, headers=_auth(actors.sahil, key()), json={"reason": "no"})
    assert res.status_code == 403 and res.json()["error"]["code"] == "NOT_TRANSFER_INITIATOR"
    res = await client.post(url, headers=_auth(actors.aman, key()), json={"reason": "Wrong carton"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "CANCELLED" and res.json()["cancel_reason"] == "Wrong carton"
    q = location_qty(db_conn, gs_id)
    assert q.get("INWARD_STAGING") == 11 and "TRANSIT" not in q
    assert tasks(db_conn, gs_id) == [
        ("S2_HANDOVER", "INTERMEDIATE_STORE_MANAGER", "CANCELLED"),
        ("S2_HANDOVER", "INWARD_VERIFIER", "DONE"),
        ("S2_HANDOVER", "INWARD_VERIFIER", "OPEN"),
    ]
    res = await client.post(url, headers=_auth(actors.aman, key()), json={"reason": "again"})
    assert res.status_code == 409


async def test_g08_pending_never_on_a_transfer(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    db_conn: Connection,
) -> None:
    gs_id, _, _ = await ro_in_process(client, storage, actors, masters, products)
    pending_lot = fetch_all(
        db_conn,
        "select id::text from public.stock_lots l where gs_id = :g and is_pending",
        g=gs_id,
    )[0]
    # Generic engine endpoint.
    res = await client.post(
        "/api/v1/custody/transfers",
        headers=_auth(actors.aman, key()),
        json={
            "from_location_code": "PENDING_HOLD",
            "to_location_code": "INTERMEDIATE_STORE",
            "lines": [{"lot_id": pending_lot["id"], "qty": 1}],
            "gs_id": gs_id,
        },
    )
    assert res.status_code in (403, 422)
    res = await client.post(
        "/api/v1/custody/transfers",
        headers=_auth(actors.admin, key()),
        json={
            "from_location_code": "PENDING_HOLD",
            "to_location_code": "INTERMEDIATE_STORE",
            "lines": [{"lot_id": pending_lot["id"], "qty": 1}],
        },
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "G-08"  # Super Admin too
    # Handover with explicit lines.
    res = await handover(
        client, actors.aman, gs_id, lines=[{"lot_id": pending_lot["id"], "qty": 1}]
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "G-08"
    # DB: a pending lot cannot be put on a transfer line.
    transfer = (await handover(client, actors.aman, gs_id)).json()
    conn = as_admin(db_conn)
    with pytest.raises(DBAPIError, match="G-08"), conn.begin_nested():
        conn.execute(
            text(
                "insert into public.custody_transfer_lines (transfer_id, lot_id, qty_sent) "
                "values (:t, :l, 1)"
            ),
            {"t": transfer["id"], "l": pending_lot["id"]},
        )
    assert all(ln["lot_id"] != pending_lot["id"] for ln in transfer["lines"])


async def test_pending_blocks_entire_gs_toggle(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    db_conn: Connection,
) -> None:
    """DEC-12 column K: with pending_blocks_entire_gs on, handover waits for the pendencies."""
    gs_id, _, _ = await ro_in_process(client, storage, actors, masters, products)
    as_admin(db_conn).execute(
        text(
            "update public.system_settings set value = 'true' "
            "where key = 'pending_blocks_entire_gs'"
        )
    )
    preview = (await client.get(f"/api/v1/gs/{gs_id}/handover", headers=_auth(actors.aman))).json()
    assert preview["blocked"]["code"] == "G-08" and preview["can_initiate"] is False
    res = await handover(client, actors.aman, gs_id)
    assert res.status_code == 422 and res.json()["error"]["code"] == "G-08"


async def test_g09_database_guards(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    db_conn: Connection,
) -> None:
    """G-09 cannot be bypassed below the API: state machine and TRANSIT movements."""
    gs_id, _, _ = await ro_in_process(client, storage, actors, masters, products, pending=0)
    transfer = (await handover(client, actors.aman, gs_id)).json()
    lot = transfer["lines"][0]["lot_id"]
    conn = as_admin(db_conn)
    ids = {
        r["code"]: r["id"]
        for r in fetch_all(
            conn,
            "select code, id from public.inventory_locations "
            "where code in ('TRANSIT','INTERMEDIATE_STORE','INWARD_STAGING')",
        )
    }

    def raises(sql: str, **params: Any) -> None:
        with pytest.raises(DBAPIError, match="G-09"), conn.begin_nested():
            conn.execute(text(sql), params)

    move = """select rms_private.rms_move_stock(:lot, :src, :dst, 1, :type, :rt, :rid, :k)"""
    # Out of TRANSIT to the receiver while INITIATED (not accepted).
    raises(
        move,
        lot=lot,
        src=ids["TRANSIT"],
        dst=ids["INTERMEDIATE_STORE"],
        type="TRANSFER_IN",
        rt="custody_transfer",
        rid=transfer["id"],
        k=key(),
    )
    # Into TRANSIT without a transfer.
    raises(move, lot=lot, src=None, dst=ids["TRANSIT"], type="RECEIPT", rt=None, rid=None, k=key())
    # Accepted with a count that differs from the quantity sent.
    raises(
        """update public.custody_transfers set status = 'ACCEPTED',
                  acceptance_code = 'ACCEPTED_VERIFIED', accepted_by = :u, accepted_at = now()
            where id = :t""",
        t=transfer["id"],
        u=actors.sahil_id,
    )
    # Reconciled without an applied reconciliation; INITIATED → RECONCILED is not a transition.
    raises(
        "update public.custody_transfers set status = 'RECONCILED' where id = :t", t=transfer["id"]
    )
    # Lines frozen once dispatched.
    raises(
        "update public.custody_transfer_lines set qty_sent = qty_sent + 1 where transfer_id = :t",
        t=transfer["id"],
    )
    # Accepted is terminal.
    assert (await accept(client, actors.sahil, transfer)).status_code == 200
    raises(
        "update public.custody_transfers set status = 'INITIATED' where id = :t", t=transfer["id"]
    )
    raises(
        move,
        lot=lot,
        src=ids["INTERMEDIATE_STORE"],
        dst=ids["TRANSIT"],
        type="TRANSFER_OUT",
        rt="custody_transfer",
        rid=transfer["id"],
        k=key(),
    )


async def test_csr_proposal_taken_over_and_packaging_check(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    db_conn: Connection,
) -> None:
    """P2-04 CSR "forward to Sahil with packaging" proposal completed through the engine."""
    gs_id = await started_gs(client, actors, masters)
    await upload_videos(client, storage, actors.aman, gs_id)
    photo = await upload(client, storage, actors.aman, gs_id, "DOC_PHOTO", "image/jpeg")
    assert (await classify(client, actors.aman, gs_id, photo["id"], INVOICE)).status_code == 201
    assert (await complete(client, actors.aman, gs_id)).status_code == 200
    await add_line(client, actors.aman, gs_id, products.dmt, 12, 12)
    assert (await categorize(client, actors.aman, gs_id, "CSR")).status_code == 200
    assert (await decide(client, actors.rm, gs_id, "CSR_APPROVED")).status_code == 200
    (proposal,) = fetch_all(
        db_conn,
        "select id::text, stock_moved, initiated_by from public.custody_transfers where gs_id = :g",
        g=gs_id,
    )
    assert proposal["stock_moved"] is False and proposal["initiated_by"] == actors.rm_id

    preview = (await client.get(f"/api/v1/gs/{gs_id}/handover", headers=_auth(actors.aman))).json()
    assert preview["proposal_transfer_id"] == proposal["id"] and preview["blocked"] is None
    assert [e["qty"] for e in preview["eligible"]] == [12]
    lot = preview["eligible"][0]["lot_id"]
    res = await handover(client, actors.aman, gs_id, lines=[{"lot_id": lot, "qty": 5}])
    assert res.status_code == 422 and res.json()["error"]["code"] == "CSR_TRANSFER_FIXED"
    res = await handover(client, actors.aman, gs_id)
    assert res.status_code == 201, res.text
    transfer = res.json()
    assert transfer["id"] == proposal["id"] and transfer["with_packaging"] is True
    assert transfer["stock_moved"] is True and transfer["initiated_by_name"] == "Aman"
    assert location_qty(db_conn, gs_id) == {"TRANSIT": 12}
    assert (await accept(client, actors.sahil, transfer)).status_code == 200
    assert location_qty(db_conn, gs_id) == {"INTERMEDIATE_STORE": 12}

    # DEC-27: Sahil records the packaging check on the received lot.
    stock = (
        await client.get(
            "/api/v1/custody/intermediate-store/stock",
            params={"gs_id": gs_id},
            headers=_auth(actors.sahil),
        )
    ).json()
    assert stock["can_check_packaging"] is True
    (row,) = stock["rows"]
    assert row["next_step"] == "AWAITING_TECHNICIAN" and row["can_classify"] is False
    res = await client.post(
        f"/api/v1/lots/{row['lot_id']}/packaging-check",
        headers=_auth(actors.sahil, key()),
        json={"result": "REPLACED", "qty_replaced": 2, "remarks": "Two boxes torn"},
    )
    assert res.status_code in (200, 201), res.text
    stock = (
        await client.get(
            "/api/v1/custody/intermediate-store/stock",
            params={"gs_id": gs_id},
            headers=_auth(actors.sahil),
        )
    ).json()
    assert stock["rows"][0]["last_packaging_check"]["result_code"] == "REPLACED"


async def test_direct_classification_stock_view_and_transfer_note(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    db_conn: Connection,
) -> None:
    """DEC-14: SELLABLE-routed lots → Functional Good by Sahil; others await the technician."""
    gs_id, _, _ = await ro_in_process(client, storage, actors, masters, products, pending=0)
    transfer = (await handover(client, actors.aman, gs_id)).json()
    assert (await accept(client, actors.sahil, transfer)).status_code == 200

    url = "/api/v1/custody/intermediate-store/stock"
    stock = (await client.get(url, params={"gs_id": gs_id}, headers=_auth(actors.sahil))).json()
    by_code = {r["condition_code"]: r for r in stock["rows"]}
    assert by_code["DMT_OK_PACKED"]["next_step"] == "DIRECT_CLASSIFICATION"
    assert by_code["DMT_OK_PACKED"]["routing_hint"] == "SELLABLE"
    assert by_code["DMT_OK_PACKED"]["can_classify"] is True
    assert by_code["DMT_DIRTY"]["next_step"] == "AWAITING_TECHNICIAN"
    assert by_code["DMT_DIRTY"]["routing_hint"] == "TO_TECHNICIAN"
    filtered = (
        await client.get(url, params={"routing_hint": "SELLABLE"}, headers=_auth(actors.sahil))
    ).json()
    assert {r["routing_hint"] for r in filtered["rows"]} == {"SELLABLE"}
    aman_view = (await client.get(url, params={"gs_id": gs_id}, headers=_auth(actors.aman))).json()
    assert aman_view["can_classify"] is False

    ok_lot = by_code["DMT_OK_PACKED"]["lot_id"]
    cls = f"/api/v1/custody/lots/{ok_lot}/classify"
    res = await client.post(cls, headers=_auth(actors.aman, key()), json={"qty": 1})
    assert res.status_code == 403
    res = await client.post(cls, headers=_auth(actors.sahil, key()), json={"qty": 99})
    assert res.status_code == 422 and res.json()["error"]["code"] == "CLASSIFY_QTY_INVALID"
    idem = key()
    res = await client.post(cls, headers=_auth(actors.sahil, idem), json={"qty": 4})
    assert res.status_code == 201, res.text
    assert res.json()["condition_class"] == "FUNCTIONAL_GOOD"
    replay = await client.post(cls, headers=_auth(actors.sahil, idem), json={"qty": 4})
    assert replay.headers.get("Idempotency-Replayed") == "true"
    res = await client.post(
        f"/api/v1/custody/lots/{by_code['DMT_DIRTY']['lot_id']}/classify",
        headers=_auth(actors.sahil, key()),
        json={"qty": 1},
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "NOT_DIRECTLY_CLASSIFIABLE"
    stock = (await client.get(url, params={"gs_id": gs_id}, headers=_auth(actors.sahil))).json()
    classified = [r for r in stock["rows"] if r["condition_class"] == "FUNCTIONAL_GOOD"]
    assert [(r["qty"], r["next_step"]) for r in classified] == [(4, "CLASSIFIED")]
    assert location_qty(db_conn, gs_id)["INTERMEDIATE_STORE"] == 11

    # Transfer Note (TRANSFER_NOTE template): previews have no side effect, every print is logged.
    note_url = f"/api/v1/custody/transfers/{transfer['id']}/transfer-note"
    preview = (await client.get(note_url, headers=_auth(actors.sahil))).json()
    assert (preview["print_count"], preview["is_reprint"], preview["watermark"]) == (0, False, None)
    assert preview["layout"]["header_title"] == "CUSTODY TRANSFER NOTE"
    assert preview["transfer"]["transfer_no"] == transfer["transfer_no"]
    first = (await client.post(f"{note_url}/print", headers=_auth(actors.sahil))).json()
    assert first["print_count"] == 1 and first["is_reprint"] is False
    again = (await client.get(note_url, headers=_auth(actors.aman))).json()
    assert again["print_count"] == 1 and again["watermark"] == "REPRINT #1"
    second = (await client.post(f"{note_url}/print", headers=_auth(actors.aman))).json()
    assert second["print_count"] == 2 and second["watermark"] == "REPRINT #1"
    logs = fetch_all(
        db_conn,
        "select count(*)::int as n from public.print_logs where entity_id = :t",
        t=transfer["id"],
    )
    assert logs == [{"n": 2}]


async def test_blind_count_hides_quantities_from_receiver(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
    db_conn: Connection,
) -> None:
    gs_id, _, _ = await ro_in_process(client, storage, actors, masters, products, pending=0)
    as_admin(db_conn).execute(
        text("update public.system_settings set value = 'true' where key = 'transfer_blind_count'")
    )
    transfer = (await handover(client, actors.aman, gs_id)).json()
    assert transfer["total_qty"] == 11 and transfer["blind_count"] is False  # the sender sees it
    detail_url = f"/api/v1/custody/transfers/{transfer['id']}"
    blind = (await client.get(detail_url, headers=_auth(actors.sahil))).json()
    assert blind["blind_count"] is True and blind["total_qty"] is None
    assert all(ln["qty_sent"] is None and ln["qty_counted"] is None for ln in blind["lines"])
    lookups = (await client.get("/api/v1/custody/lookups", headers=_auth(actors.sahil))).json()
    assert lookups["blind_count"] is True
    assert [o["code"] for o in lookups["acceptance_options"]] == [
        "ACCEPTED_VERIFIED",
        "DISCREPANCY",
    ]
    assert [o["code"] for o in lookups["mode_options"]] == ["PHYSICAL_AND_DIGITAL"]
    assert (await accept(client, actors.sahil, transfer)).status_code == 200
    after = (await client.get(detail_url, headers=_auth(actors.sahil))).json()
    assert after["blind_count"] is False and after["total_qty"] == 11


async def test_list_filters_and_unknown_status(
    client: AsyncClient,
    storage: FakeStorage,
    actors: Actors,
    masters: Masters,
    products: Products,
) -> None:
    gs_id, _, _ = await ro_in_process(client, storage, actors, masters, products, pending=0)
    transfer = (await handover(client, actors.aman, gs_id)).json()
    url = "/api/v1/custody/transfers"
    res = await client.get(
        url, params={"gs_id": gs_id, "status": "INITIATED"}, headers=_auth(actors.rm)
    )
    assert [t["id"] for t in res.json()["items"]] == [transfer["id"]]
    res = await client.get(
        url, params={"gs_id": gs_id, "status": "ACCEPTED"}, headers=_auth(actors.rm)
    )
    assert res.json()["total"] == 0
    res = await client.get(
        url,
        params={
            "gs_id": gs_id,
            "from_location": "INWARD_STAGING",
            "to_location": "INTERMEDIATE_STORE",
        },
        headers=_auth(actors.rm),
    )
    assert res.json()["total"] == 1
    res = await client.get(url, params={"status": "BOGUS"}, headers=_auth(actors.rm))
    assert res.status_code == 422
    # Accounts has no custody.view.
    assert (await client.get(url, headers=_auth(actors.accounts))).status_code == 403
