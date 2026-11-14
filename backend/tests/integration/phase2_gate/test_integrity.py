"""P2-08 · Phase 2 gate: data-integrity checks (scripts/integrity_check.sql, master plan §17).

The same SQL file a developer runs with psql is executed here:
1. after driving every Phase-2 path through the real API (all DMT / Prismatic / EO conditions,
   hazard, rejections, short quantity, CSR approve, CSR reject → RO, Pending (BP) open + clear),
   it must report zero violations;
2. faults planted directly in the tables (inside the rolled-back test transaction) must be
   reported, so a check can never pass vacuously;
3. on the whole local database as it stands (E2E data included), it must report zero violations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, Engine, text

from tests.integration.conftest import as_admin, fetch_all
from tests.integration.phase2_gate.helpers import (
    Admin,
    Products,
    finalise,
    grade,
    gs_at,
)
from tests.integration.test_gate_inward import Masters, _auth
from tests.integration.test_itemization import decide
from tests.integration.test_unboxing import Actors, FakeStorage

pytestmark = pytest.mark.asyncio

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "integrity_check.sql"
DMT_ALL_EIGHT = {
    "DMT_OK_PACKED": 2,
    "DMT_OK_PKG_DAMAGED": 1,
    "DMT_OTHER_BRANDS": 1,
    "DMT_SCRATCHED": 1,
    "DMT_DIRTY": 1,
    "DMT_BROKEN_BODY": 1,
    "DMT_DISPLAY_ISSUE": 1,
    "DMT_SHORT_QTY": 2,  # DEC-09 marker: does not consume received pieces
}


def run_integrity(conn: Connection) -> dict[str, dict[str, Any]]:
    sql = SCRIPT.read_text(encoding="utf-8")
    rows = as_admin(conn).execute(text(sql)).mappings().all()
    return {r["code"]: dict(r) for r in rows}


def violations(report: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    return {code: r["samples"] for code, r in report.items() if r["violations"]}


async def drive_phase2_paths(
    client: AsyncClient, storage: FakeStorage, a: Actors, m: Masters, p: Products
) -> dict[str, Any]:
    """Every Phase-2 stock path, through the API, as the demo roles would do it."""
    # RO: DMT with all 8 conditions (documented 10, received 8), Prismatic (3), EO (4, opened).
    ro, items = await gs_at(
        client, storage, a, m, [(p.dmt, 10, 8), (p.prismatic, 3, 3), (p.eo, 4, 4)]
    )
    graded = [
        (items[0], DMT_ALL_EIGHT, 8),
        (items[1], {"PRS_OK": 1, "PRS_BULB_BROKEN_NO_HG": 1, "PRS_BROKEN_WITH_HG": 1}, 3),
        (
            items[2],
            {
                "EO_OK": 1,
                "EO_INNER_CAPILLARY_BROKEN": 1,
                "EO_BODY_BROKEN_HG": 1,
                "EO_BULB_BROKEN_NO_HG": 1,
            },
            4,
        ),
    ]
    for item_id, allocations, received in graded:
        res = await grade(client, a.aman, item_id, allocations, packaging=received - 1, container=1)
        assert res.status_code == 200, res.text
        assert (await finalise(client, a.aman, item_id)).status_code == 200
    # RM: 2 of the DMT OK pieces Pending (BP), then cleared.
    res = await client.put(
        f"/api/v1/gs/{ro}/rm-actions",
        json={
            "lines": [
                {
                    "gs_item_id": items[0],
                    "actions": [
                        {"action_code": "SEND_NEW", "qty": 4},
                        {"action_code": "PENDING_BP", "qty": 2},
                        {"action_code": "NOT_ALLOWED", "qty": 2},
                    ],
                },
                {
                    "gs_item_id": items[1],
                    "actions": [
                        {"action_code": "ISSUE_CN", "qty": 1},
                        {"action_code": "NOT_ALLOWED", "qty": 2},
                    ],
                },
                {
                    "gs_item_id": items[2],
                    "actions": [
                        {"action_code": "SEND_REPAIRED", "qty": 2},
                        {"action_code": "NOT_ALLOWED", "qty": 2},
                    ],
                },
            ],
            "pendency_details": {
                items[0]: {"reason": "Repair Team check", "sent_to": "Repair Team"}
            },
        },
        headers=_auth(a.rm),
    )
    assert res.status_code == 200, res.text

    # CSR approved (transfer initiated) and CSR rejected → RO → inspected.
    csr_ok, _ = await gs_at(client, storage, a, m, [(p.dmt, 5, 5)], category="CSR")
    assert (await decide(client, a.rm, csr_ok, "CSR_APPROVED", "full return")).status_code == 200
    csr_no, csr_items = await gs_at(client, storage, a, m, [(p.prismatic, 2, 2)], category="CSR")
    assert (await decide(client, a.rm, csr_no, "CSR_REJECTED_TO_RO", "mixed")).status_code == 200
    res = await grade(client, a.aman, csr_items[0], {"PRS_OK": 2}, packaging=2)
    assert res.status_code == 200, res.text
    assert (await finalise(client, a.aman, csr_items[0])).status_code == 200
    return {"ro": ro, "items": items, "csr_ok": csr_ok, "csr_no": csr_no}


async def test_integrity_checks_pass_after_every_phase2_path(
    client: AsyncClient,
    db_conn: Connection,
    storage: FakeStorage,
    actors: Actors,
    admin: Admin,
    masters: Masters,
    products: Products,
) -> None:
    ctx = await drive_phase2_paths(client, storage, actors, masters, products)
    report = run_integrity(db_conn)
    assert set(report) == {f"IC-{i:02d}" for i in range(1, 13)}  # IC-09..IC-12 added in P3-08
    assert violations(report) == {}

    # Clearing the pendency keeps every invariant.
    pend = fetch_all(
        db_conn,
        "select id from public.pendencies where gs_id = :g and status = 'OPEN'",
        g=ctx["ro"],
    )
    assert len(pend) == 1
    res = await client.post(
        f"/api/v1/pendencies/{pend[0]['id']}/clear",
        json={"resolution_action": "SEND_REPAIRED", "notes": "Repaired by Repair Team"},
        headers=_auth(actors.rm),
    )
    assert res.status_code == 200, res.text
    assert violations(run_integrity(db_conn)) == {}

    # Planted faults are detected (proves no check passes vacuously).
    c = as_admin(db_conn)
    c.execute(text("set local session_replication_role = replica"))
    c.execute(
        text(
            """update public.stock_balances set qty = qty + 1
                where (lot_id, location_id) = (
                  select b.lot_id, b.location_id from public.stock_balances b
                    join public.stock_lots l on l.id = b.lot_id
                   where l.gs_item_id = :i and l.condition_class = 'AS_RECEIVED' and b.qty > 0
                   limit 1)"""
        ),
        {"i": ctx["items"][0]},
    )
    c.execute(
        text(
            """update public.stock_lots set source_condition_code = null
                where gs_item_id = :i and source_condition_code = 'DMT_DIRTY'"""
        ),
        {"i": ctx["items"][0]},
    )
    c.execute(
        text("update public.rejections set stock_movement_id = null where gs_item_id = :i"),
        {"i": ctx["items"][1]},
    )
    c.execute(
        text(
            """update public.stock_balances b set location_id =
                 (select id from public.inventory_locations where code = 'INTERMEDIATE_STORE')
                from public.stock_lots l
               where l.id = b.lot_id and l.gs_item_id = :i and l.condition_class = 'HAZARD'"""
        ),
        {"i": ctx["items"][2]},
    )
    c.execute(text("set local session_replication_role = origin"))
    found = violations(run_integrity(db_conn))
    assert {"IC-01", "IC-03", "IC-04", "IC-05", "IC-06"} <= set(found), found


async def test_integrity_checks_pass_on_the_local_database(db_engine: Engine) -> None:
    """The committed local data (seed + demo + E2E runs) must be consistent too."""
    with db_engine.connect() as conn:
        report = run_integrity(conn)
    assert violations(report) == {}
