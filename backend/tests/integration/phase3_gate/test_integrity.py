"""P3-08 · Phase 3 gate: extended integrity checks (scripts/integrity_check.sql IC-01, IC-09..12).

Faults are planted directly in the tables inside the rolled-back test transaction (user triggers
off, as a data-repair script or a bug would leave them), and every new check must report its
fault — so no check can pass vacuously. The lifecycle E2E (frontend/tests/e2e/lifecycle.spec.ts)
runs the same SQL file after every scenario and requires zero violations; the P2-08 suite runs it
over the whole local database.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import Connection, text

from tests.integration.conftest import as_admin
from tests.integration.phase2_gate.test_integrity import run_integrity
from tests.integration.phase3_gate.conftest import loc, seed_lot


def _replica(conn: Connection) -> Connection:
    c = as_admin(conn)
    c.execute(text("set local session_replication_role = replica"))
    return c


def _move(c: Connection, lot: Any, src: Any, dst: Any, qty: int, kind: str, ref: str = "x") -> Any:
    return c.execute(
        text(
            """insert into public.stock_movements (lot_id, from_location_id, to_location_id, qty,
                   movement_type, reference_type, idempotency_key)
               values (:l, :f, :t, :q, :k, :r, :key) returning id"""
        ),
        {"l": lot, "f": src, "t": dst, "q": qty, "k": kind, "r": ref, "key": uuid.uuid4().hex},
    ).scalar_one()


def _samples(report: dict[str, dict[str, Any]], code: str) -> list[str]:
    return list(report[code]["samples"])


def test_ic01_counts_dismantled_units_and_catches_a_leak(db_conn: Connection) -> None:
    ok = seed_lot(db_conn, location="NON_FUNCTIONAL_STORE", condition_class="NON_GOOD", qty=5)
    leak = seed_lot(db_conn, location="NON_FUNCTIONAL_STORE", condition_class="NON_GOOD", qty=5)
    c = _replica(db_conn)
    nf = loc(db_conn, "NON_FUNCTIONAL_STORE")
    # 2 units dismantled through the ledger (balance 3 + 2 consumed = 5 received): no violation.
    _move(c, ok["lot_id"], nf, None, 2, "DISMANTLE_IN")
    c.execute(
        text("update public.stock_balances set qty = qty - 2 where lot_id = :l"),
        {"l": ok["lot_id"]},
    )
    # 1 unit vanishes from the balance with no movement: a leak.
    c.execute(
        text("update public.stock_balances set qty = qty - 1 where lot_id = :l"),
        {"l": leak["lot_id"]},
    )
    report = run_integrity(db_conn)
    gs_nos = dict(
        c.execute(
            text("select id, gs_no from public.goods_slips where id = any(:ids)"),
            {"ids": [ok["gs_id"], leak["gs_id"]]},
        ).all()
    )
    # The committed local data is clean (see the last test), so the leak is the only violation.
    ic01 = " ".join(_samples(report, "IC-01"))
    assert report["IC-01"]["violations"] == 1, ic01
    assert gs_nos[leak["gs_id"]] in ic01
    assert gs_nos[ok["gs_id"]] not in ic01


def test_ic09_battery_consumption_must_match_batteries_installed(db_conn: Connection) -> None:
    battery = seed_lot(
        db_conn,
        location="BATTERY_STORE",
        condition_class="AS_RECEIVED",
        qty=10,
        with_gs=False,
    )
    c = _replica(db_conn)
    store = loc(db_conn, "BATTERY_STORE")
    # (a) a receiving record claims 3 batteries installed but has no CONSUME movement
    c.execute(
        text(
            """insert into public.technician_receiving_records (batch_id, batch_line_id,
                   qty_received, battery_check_code, pieces_checked, batteries_installed,
                   battery_type_id, functional_good_qty, entry_by)
               values (:b, :l, 3, 'BATTERY_REPLACED', 3, 3, :t, 3, :u)"""
        ),
        {"b": uuid.uuid4(), "l": uuid.uuid4(), "t": uuid.uuid4(), "u": uuid.uuid4()},
    )
    # (b) a CONSUME of a technician receive with no receiving record behind it
    _move(c, battery["lot_id"], store, None, 2, "CONSUME", ref="TECH_BATCH_RECEIVE")
    report = run_integrity(db_conn)
    text_ = " ".join(_samples(report, "IC-09"))
    assert report["IC-09"]["violations"] >= 2
    assert "batteries_installed 3, consumed 0" in text_
    assert "has no receiving record" in text_


def test_ic10_functional_locations_hold_only_functional_classes(db_conn: Connection) -> None:
    lot = seed_lot(db_conn, location="NON_FUNCTIONAL_STORE", condition_class="NON_SELLABLE", qty=1)
    c = _replica(db_conn)
    for code in ("INTERMEDIATE_STORE", "MAIN_STORE"):
        c.execute(
            text("insert into public.stock_balances (lot_id, location_id, qty) values (:l, :x, 1)"),
            {"l": lot["lot_id"], "x": loc(db_conn, code)},
        )
    report = run_integrity(db_conn)
    text_ = " ".join(_samples(report, "IC-10"))
    assert "INTERMEDIATE_STORE (FUNCTIONAL)" in text_
    assert "MAIN_STORE (MAIN_STORE)" in text_


def test_ic11_ic12_closed_gs_needs_snapshot_and_no_open_stock(db_conn: Connection) -> None:
    lot = seed_lot(db_conn, location="INWARD_STAGING", condition_class="AS_RECEIVED", qty=2)
    other = seed_lot(db_conn, location="INWARD_STAGING", condition_class="AS_RECEIVED", qty=1)
    c = _replica(db_conn)
    # A GS forced to CLOSED with no closure record, its stock still in inward staging.
    c.execute(
        text("update public.goods_slips set status = 'CLOSED' where id = :g"), {"g": lot["gs_id"]}
    )
    # A GS whose frozen snapshot records a failing item.
    c.execute(
        text("update public.goods_slips set status = 'CLOSED' where id = :g"),
        {"g": other["gs_id"]},
    )
    c.execute(
        text(
            """insert into public.gs_closures (gs_id, closure_type, checklist_snapshot, closed_by)
               values (:g, 'RO_CLOSED', cast(:snap as jsonb), :u)"""
        ),
        {
            "g": other["gs_id"],
            "u": uuid.uuid4(),
            "snap": '{"items": [{"code": "PRIOR_NOTIFICATION", "applicable": true,'
            ' "passed": false}]}',
        },
    )
    report = run_integrity(db_conn)
    ic11 = " ".join(_samples(report, "IC-11"))
    assert "CLOSED without a closure record" in ic11
    assert "snapshot has failing items PRIOR_NOTIFICATION" in ic11
    assert report["IC-12"]["violations"] >= 2
    assert "INWARD_STAGING" in " ".join(_samples(report, "IC-12"))


@pytest.mark.parametrize("code", [f"IC-{i:02d}" for i in range(1, 13)])
def test_whole_local_database_is_consistent(db_conn: Connection, code: str) -> None:
    """Committed local data (E2E lifecycle runs included) has no violation of any check."""
    report = run_integrity(db_conn)
    assert report[code]["violations"] == 0, report[code]["samples"]
