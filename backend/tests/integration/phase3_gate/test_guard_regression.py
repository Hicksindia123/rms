"""P3-08 · Phase 3 gate: system-guard regression G-09..G-15 (master plan §4.2, CLAUDE.md rule c).

Every guard is attacked with a VALID Super Admin token through the public API and, where the API
cannot even express the forbidden action, directly against the locked tables / functions under the
API's own `rms_api` role with the Super Admin as the acting user. Every attempt must be rejected
and leave the data unchanged. Configuration (settings, roles, Super Admin status) cannot disable
any of them.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from tests.integration.conftest import as_admin, fetch_all
from tests.integration.phase2_gate.helpers import db_attempt, move_as_super_admin
from tests.integration.phase3_gate.conftest import Gate, auth, balance, loc, seed_lot
from tests.integration.test_closure import _build_gs

pytestmark = pytest.mark.anyio


def rejected(res: Response, guard: str) -> None:
    """The response is an error envelope that names the guard (code or message)."""
    assert res.status_code in (403, 409, 422), f"{guard} not enforced: {res.status_code} {res.text}"
    err = res.json()["error"]
    assert guard in f"{err['code']} {err['message']}", res.text


def db_rejected(factory: sessionmaker[Session], gate: Gate, guard: str, sql: str, **p: Any) -> None:
    with pytest.raises(DBAPIError, match=guard):
        db_attempt(factory, gate.admin_id, sql, **p)


# --- G-09 two-phase custody ----------------------------------------------------------------------
async def test_g09_custody_is_two_phase_and_a_discrepancy_freezes_it(
    client: AsyncClient,
    db_conn: Connection,
    session_factory: sessionmaker[Session],
    gate: Gate,
) -> None:
    lot = seed_lot(db_conn, location="INWARD_STAGING", condition_class="AS_RECEIVED", qty=4)
    res = await client.post(
        "/api/v1/custody/transfers",
        json={
            "from_location_code": "INWARD_STAGING",
            "to_location_code": "INTERMEDIATE_STORE",
            "gs_id": str(lot["gs_id"]),
            "lines": [{"lot_id": str(lot["lot_id"]), "qty": 4}],
        },
        headers=auth(gate.admin, idem=True),
    )
    assert res.status_code == 201, res.text
    transfer = res.json()["id"]
    # Phase 1 only: the stock is in TRANSIT, the receiver is not credited yet.
    assert balance(db_conn, lot["lot_id"], "TRANSIT") == 4
    assert balance(db_conn, lot["lot_id"], "INTERMEDIATE_STORE") == 0

    # A short count reports a discrepancy: the transfer freezes, nothing is credited.
    res = await client.post(
        f"/api/v1/custody/transfers/{transfer}/accept",
        json={
            "lines": [{"lot_id": str(lot["lot_id"]), "qty_counted": 3}],
            "acceptance_code": "DISCREPANCY",
            "notes": "one piece missing",
        },
        headers=auth(gate.sahil, idem=True),
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "DISCREPANCY"
    assert balance(db_conn, lot["lot_id"], "INTERMEDIATE_STORE") == 0

    # Super Admin bypass attempts: accept again via the API, force ACCEPTED in the DB, or move
    # the stock out of TRANSIT without the transfer.
    res = await client.post(
        f"/api/v1/custody/transfers/{transfer}/accept",
        json={
            "lines": [{"lot_id": str(lot["lot_id"]), "qty_counted": 4}],
            "acceptance_code": "ACCEPTED_VERIFIED",
        },
        headers=auth(gate.admin, idem=True),
    )
    assert res.status_code == 409, res.text
    db_rejected(
        session_factory,
        gate,
        "G-09",
        "update public.custody_transfers set status = 'ACCEPTED' where id = :t",
        t=transfer,
    )
    with pytest.raises(DBAPIError, match="G-09"):
        move_as_super_admin(
            session_factory,
            gate.admin_id,
            lot=lot["lot_id"],
            src=loc(db_conn, "TRANSIT"),
            dst=loc(db_conn, "INTERMEDIATE_STORE"),
            qty=4,
        )
    assert balance(db_conn, lot["lot_id"], "TRANSIT") == 4
    assert balance(db_conn, lot["lot_id"], "INTERMEDIATE_STORE") == 0


# --- G-10 battery replaced + G-16 idempotent consumption ----------------------------------------
async def _batch(client: AsyncClient, gate: Gate, lot_id: Any, qty: int) -> dict[str, Any]:
    res = await client.post(
        "/api/v1/servicing/batches",
        json={"technician_id": str(gate.tech_id), "lines": [{"lot_id": str(lot_id), "qty": qty}]},
        headers=auth(gate.admin, idem=True),
    )
    assert res.status_code == 201, res.text
    return dict(res.json())


async def _lr44(client: AsyncClient, gate: Gate) -> tuple[str, int]:
    types = (await client.get("/api/v1/inventory/batteries/types", headers=auth(gate.spm))).json()
    bals = (await client.get("/api/v1/inventory/batteries/balances", headers=auth(gate.spm))).json()
    type_id = next(t["id"] for t in types if t["code"] == "LR44")
    return type_id, next((b["balance"] for b in bals if b["code"] == "LR44"), 0)


async def test_g10_battery_replaced_needs_counts_and_stock_and_is_consumed_once(
    client: AsyncClient,
    db_conn: Connection,
    session_factory: sessionmaker[Session],
    gate: Gate,
) -> None:
    lot = seed_lot(
        db_conn,
        location="INTERMEDIATE_STORE",
        condition_class="AS_RECEIVED",
        source_condition="DMT_DISPLAY_ISSUE",
        qty=4,
    )
    batch = await _batch(client, gate, lot["lot_id"], 4)
    line_id = batch["lines"][0]["id"]
    type_id, before = await _lr44(client, gate)

    def receive(qty: int, installed: int) -> dict[str, Any]:
        return {
            "lines": [
                {
                    "batch_line_id": line_id,
                    "qty_receiving": qty,
                    "battery_check_code": "BATTERY_REPLACED",
                    "pieces_checked": qty,
                    "batteries_installed": installed,
                    "battery_type_id": type_id,
                    "allocations": {"FUNCTIONAL_REPAIRED": qty},
                }
            ]
        }

    url = f"/api/v1/servicing/batches/{batch['id']}/receive"
    # G-10 through the API, as Super Admin: no batteries installed.
    rejected(await client.post(url, json=receive(2, 0), headers=auth(gate.admin, True)), "G-10")
    # G-10 / G-16: more batteries than the store holds never makes the stock negative.
    res = await client.post(url, json=receive(2, before + 1), headers=auth(gate.admin, True))
    assert res.status_code == 409, res.text
    assert (await _lr44(client, gate))[1] == before

    # The DB check stands even for a direct insert by the Super Admin.
    db_rejected(
        session_factory,
        gate,
        "g10_battery_counts_check",
        """insert into public.technician_receiving_records (batch_id, batch_line_id,
               qty_received, battery_check_code, pieces_checked, batteries_installed,
               battery_type_id, functional_repaired_qty, entry_by)
           values (:b, :l, 1, 'BATTERY_REPLACED', 1, 0, :t, 1, :u)""",
        b=batch["id"],
        l=line_id,
        t=type_id,
        u=gate.admin_id,
    )

    # G-16: a retried receive with the same Idempotency-Key returns the original result and
    # consumes the batteries ONCE (2 of 4 received, so a re-run would have been possible).
    res = await client.post(
        "/api/v1/inventory/batteries/receipts",
        json={"battery_type": "LR44", "qty": 10, "ref": f"P308-{uuid.uuid4().hex[:6]}"},
        headers=auth(gate.admin, True),
    )
    assert res.status_code == 201, res.text
    key = auth(gate.admin, True)
    first = await client.post(url, json=receive(2, 2), headers=key)
    assert first.status_code == 200, first.text
    replay = await client.post(url, json=receive(2, 2), headers=key)
    assert replay.status_code == 200, replay.text
    assert replay.headers.get("Idempotency-Replayed") == "true"
    assert replay.json() == first.json()
    assert (await _lr44(client, gate))[1] == before + 10 - 2
    received = fetch_all(
        db_conn,
        "select qty_received from public.technician_receiving_records where batch_id = :b",
        b=batch["id"],
    )
    assert [r["qty_received"] for r in received] == [2]


# --- G-11 PCB model + supplier -------------------------------------------------------------------
async def test_g11_pcb_needs_model_and_supplier(
    client: AsyncClient,
    db_conn: Connection,
    session_factory: sessionmaker[Session],
    gate: Gate,
) -> None:
    lot = seed_lot(db_conn, location="NON_FUNCTIONAL_STORE", condition_class="NON_GOOD", qty=2)
    res = await client.post(
        "/api/v1/dismantling/batches",
        json={
            "inputs": [{"lot_id": str(lot["lot_id"]), "qty": 2}],
            "storage_method_code": "DEDICATED_CONTAINERS",
        },
        headers=auth(gate.admin, True),
    )
    assert res.status_code == 201, res.text
    batch = res.json()["id"]
    pcb_box = (
        as_admin(db_conn)
        .execute(
            text(
                "select id from public.storage_containers where dedicated_part_type = 'PCB' limit 1"
            )
        )
        .scalar_one()
    )
    for missing in ({"pcb_model_id": None}, {"pcb_supplier_id": None}):
        model = (
            as_admin(db_conn)
            .execute(text("select id, supplier_id from public.pcb_models limit 1"))
            .one()
        )
        part = {
            "part_type": "PCB",
            "qty": 2,
            "container_id": str(pcb_box),
            "pcb_model_id": str(model.id),
            "pcb_supplier_id": str(model.supplier_id),
            **missing,
        }
        res = await client.post(
            f"/api/v1/dismantling/batches/{batch}/recover",
            json={"units_dismantled": 2, "parts": [part]},
            headers=auth(gate.admin, True),
        )
        rejected(res, "G-11")
    assert not fetch_all(
        db_conn, "select 1 from public.recovered_parts where batch_id = :b", b=batch
    )
    db_rejected(
        session_factory,
        gate,
        "recovered_parts_pcb_guard",
        """insert into public.recovered_parts (batch_id, part_type, qty, container_id)
           values (:b, 'PCB', 1, :c)""",
        b=batch,
        c=pcb_box,
    )


# --- G-12 functional location rejects non-functional stock --------------------------------------
async def test_g12_intermediate_store_rejects_non_functional_stock(
    client: AsyncClient,
    db_conn: Connection,
    session_factory: sessionmaker[Session],
    gate: Gate,
) -> None:
    parts = seed_lot(db_conn, location="SPARE_PARTS_STORE", condition_class="SALVAGED", qty=3)
    with pytest.raises(DBAPIError, match="G-12"):
        move_as_super_admin(
            session_factory,
            gate.admin_id,
            lot=parts["lot_id"],
            src=loc(db_conn, "SPARE_PARTS_STORE"),
            dst=loc(db_conn, "INTERMEDIATE_STORE"),
            qty=1,
        )
    # Through the API (custody assignment), as Super Admin.
    res = await client.post(
        "/api/v1/inventory/custody-assignment",
        json={"lot_id": str(parts["lot_id"]), "qty": 1, "assignment_code": "CUST_FUNCTIONAL_GOOD"},
        headers=auth(gate.admin, True),
    )
    rejected(res, "G-12")
    # An in-place condition edit cannot turn store stock non-functional either.
    store = seed_lot(db_conn, location="INTERMEDIATE_STORE", condition_class="AS_RECEIVED", qty=2)
    db_rejected(
        session_factory,
        gate,
        "G-12",
        "update public.stock_lots set condition_class = 'SALVAGED' where id = :l",
        l=store["lot_id"],
    )
    # (non-functional classes are refused as G-04 by the same trigger)
    db_rejected(
        session_factory,
        gate,
        "G-04",
        "update public.stock_lots set condition_class = 'NON_SELLABLE' where id = :l",
        l=store["lot_id"],
    )
    assert balance(db_conn, parts["lot_id"], "INTERMEDIATE_STORE") == 0
    assert balance(db_conn, parts["lot_id"], "SPARE_PARTS_STORE") == 3


# --- G-13 CN needs ALLOW_CN; GST CN needs the portal ---------------------------------------------
async def test_g13_credit_note_needs_allow_cn_and_gst_reflection(
    client: AsyncClient,
    db_conn: Connection,
    session_factory: sessionmaker[Session],
    gate: Gate,
) -> None:
    no_decision = _build_gs(
        db_conn, gate.admin_id, with_decision=False, issue_cn=False, dispatch=False
    )
    res = await client.post(
        "/api/v1/credit-notes",
        json={
            "gs_id": str(no_decision["gs_id"]),
            "lines": [{"gs_item_id": str(no_decision["item_id"]), "qty": 1}],
        },
        headers=auth(gate.admin, True),
    )
    rejected(res, "G-13")
    db_rejected(
        session_factory,
        gate,
        "G-13",
        "insert into public.credit_notes (gs_id, cn_type_code, created_by) "
        "values (:g, 'GENERAL_CN', :u)",
        g=no_decision["gs_id"],
        u=gate.admin_id,
    )

    gs = _build_gs(db_conn, gate.admin_id, issue_cn=False, dispatch=False)  # ALLOW 2 / DENY 2
    res = await client.post(
        "/api/v1/credit-notes",
        json={"gs_id": str(gs["gs_id"]), "lines": [{"gs_item_id": str(gs["item_id"]), "qty": 3}]},
        headers=auth(gate.admin, True),
    )
    assert res.status_code >= 400, "crediting more than ALLOW_CN must fail"
    res = await client.post(
        "/api/v1/credit-notes",
        json={"gs_id": str(gs["gs_id"]), "lines": [{"gs_item_id": str(gs["item_id"]), "qty": 2}]},
        headers=auth(gate.admin, True),
    )
    assert res.status_code == 201, res.text
    cn = res.json()["id"]
    res = await client.patch(
        f"/api/v1/credit-notes/{cn}/gst-check",
        json={"gst_portal_code": "GST_NOT_REFLECTED", "checked_on": "2026-11-05"},
        headers=auth(gate.admin),
    )
    assert res.status_code == 200, res.text
    assert res.json()["cn_type_code"] == "JV_ONLY"
    for forbidden in ("GST_CN", "GENERAL_CN"):
        res = await client.patch(
            f"/api/v1/credit-notes/{cn}/type",
            json={"cn_type_code": forbidden},
            headers=auth(gate.admin),
        )
        rejected(res, "G-13")
        db_rejected(
            session_factory,
            gate,
            "G-13",
            "update public.credit_notes set cn_type_code = :t where id = :id",
            t=forbidden,
            id=cn,
        )


# --- G-14 rate verification per line ------------------------------------------------------------
async def test_g14_credit_note_needs_rate_verification_per_line(
    client: AsyncClient,
    db_conn: Connection,
    session_factory: sessionmaker[Session],
    gate: Gate,
) -> None:
    gs = _build_gs(db_conn, gate.admin_id, issue_cn=False, dispatch=False)
    res = await client.post(
        "/api/v1/credit-notes",
        json={"gs_id": str(gs["gs_id"]), "lines": [{"gs_item_id": str(gs["item_id"]), "qty": 2}]},
        headers=auth(gate.admin, True),
    )
    assert res.status_code == 201, res.text
    cn = res.json()["id"]
    res = await client.post(
        f"/api/v1/credit-notes/{cn}/issue",
        json={"cn_no": f"CN-P308-{uuid.uuid4().hex[:6]}", "cn_date": "2026-11-05"},
        headers=auth(gate.admin, True),
    )
    rejected(res, "G-14")
    db_rejected(
        session_factory,
        gate,
        "G-14",
        "update public.credit_notes set status = 'ISSUED', cn_no = :n, cn_date = current_date "
        "where id = :id",
        n=f"CN-P308-{uuid.uuid4().hex[:6]}",
        id=cn,
    )
    status = as_admin(db_conn).execute(
        text("select status from public.credit_notes where id = :id"), {"id": cn}
    )
    assert status.scalar_one() == "DRAFT"


# --- G-15 closure ---------------------------------------------------------------------------------
async def test_g15_gs_cannot_close_with_open_conditions(
    client: AsyncClient,
    db_conn: Connection,
    session_factory: sessionmaker[Session],
    gate: Gate,
) -> None:
    gs = _build_gs(db_conn, gate.admin_id)  # CN issued, the party not yet notified (BR-38)
    res = await client.post(
        f"/api/v1/gs/{gs['gs_id']}/close", json={}, headers=auth(gate.admin, True)
    )
    rejected(res, "G-15")
    assert "PRIOR_NOTIFICATION" in res.text
    db_rejected(
        session_factory,
        gate,
        "G-15",
        "update public.goods_slips set status = 'CLOSED', closure_type = 'RO_CLOSED', "
        "closed_at = now() where id = :g",
        g=gs["gs_id"],
    )
    # Stock left in TRANSIT also blocks closure, whoever asks (a real phase-1 transfer: G-09
    # refuses any other way into TRANSIT).
    transit = seed_lot(db_conn, location="INWARD_STAGING", condition_class="AS_RECEIVED", qty=1)
    res = await client.post(
        "/api/v1/custody/transfers",
        json={
            "from_location_code": "INWARD_STAGING",
            "to_location_code": "INTERMEDIATE_STORE",
            "gs_id": str(transit["gs_id"]),
            "lines": [{"lot_id": str(transit["lot_id"]), "qty": 1}],
        },
        headers=auth(gate.admin, idem=True),
    )
    assert res.status_code == 201, res.text
    res = await client.post(
        f"/api/v1/gs/{transit['gs_id']}/close", json={}, headers=auth(gate.admin, True)
    )
    rejected(res, "G-15")
    assert "STOCK_NOT_IN_TRANSIT" in res.text
    status = as_admin(db_conn).execute(
        text("select status from public.goods_slips where id = :g"), {"g": gs["gs_id"]}
    )
    assert status.scalar_one() != "CLOSED"
