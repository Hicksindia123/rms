"""P2-08 · Phase 2 gate: GS list performance smoke (master plan §17 "Performance").

A test-only bulk factory seeds 5,000 goods slips inside the rolled-back test transaction (numbers
from the real GS series, so G-01 / DEC-01 hold). The GS list API must answer in < 1 s of server
time for the common list views, and the page query the API actually ran is EXPLAINed to prove it
is served by an index (no sequential scan + sort of goods_slips for the default page).
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, event, text

from tests.integration.conftest import as_admin
from tests.integration.phase2_gate.helpers import (
    Admin,
)
from tests.integration.test_gate_inward import Masters, _auth

pytestmark = pytest.mark.asyncio

N = 5_000
BUDGET_SECONDS = 1.0
STATUSES = ["GATE_CREATED", "UNBOXING", "ITEMIZATION", "INSPECTION", "RM_REVIEW", "IN_PROCESS"]


def bulk_goods_slips(conn: Connection, masters: Masters, created_by: Any, n: int = N) -> None:
    """Test-only bulk factory (never used by production code paths, rule j)."""
    c = as_admin(conn)
    wf = c.execute(
        text(
            """select v.id from public.workflow_versions v
                 join public.workflow_definitions d on d.id = v.workflow_definition_id
                where d.code = 'RMS_STANDARD' and v.status = 'PUBLISHED'"""
        )
    ).scalar_one()
    c.execute(
        text(
            """
            insert into public.goods_slips (
              gs_no, workflow_version_id, party_id, state_id, station_id,
              delivery_mode_code, courier_name, docket_no, box_count,
              gate_document_code, gate_doc_no, gate_doc_date, status, created_by, created_at
            )
            select rms_private.next_number('GS'), :wf, :party, :state, :station,
                   'COURIER_PARCEL', 'BlueDart', 'PERF-' || g, 1 + g % 5,
                   'INVOICE', 'INV-PERF-' || g, current_date, 'GATE_CREATED', :by,
                   now() - make_interval(mins => g)
              from generate_series(1, :n) g
            """
        ),
        {
            "wf": wf,
            "party": masters.party,
            "state": masters.state_a,
            "station": masters.station_a,
            "by": created_by,
            "n": n,
        },
    )
    # Spread statuses and flags like a live register (test data only; lifecycle triggers off).
    c.execute(text("set local session_replication_role = replica"))
    c.execute(
        text(
            """update public.goods_slips
                  set status = (cast(:statuses as text[]))[1 + (substr(docket_no, 6)::int % 6)],
                      has_hazard = substr(docket_no, 6)::int % 50 = 0
                where docket_no like 'PERF-%'"""
        ),
        {"statuses": STATUSES},
    )
    c.execute(text("set local session_replication_role = origin"))
    c.execute(text("analyze public.goods_slips"))


async def timed_get(client: AsyncClient, token: str, path: str) -> tuple[float, dict[str, Any]]:
    start = time.perf_counter()
    res = await client.get(path, headers=_auth(token))
    elapsed = time.perf_counter() - start
    assert res.status_code == 200, res.text
    return elapsed, res.json()


async def test_gs_list_with_5000_goods_slips_under_one_second(
    client: AsyncClient,
    db_conn: Connection,
    admin: Admin,
    masters: Masters,
) -> None:
    bulk_goods_slips(db_conn, masters, admin.id)

    captured: list[tuple[str, Any]] = []

    def capture(_c: Any, _cur: Any, statement: str, params: Any, _ctx: Any, _many: bool) -> None:
        if "from public.goods_slips g" in statement and "limit" in statement:
            captured.append((statement, params))

    event.listen(db_conn, "before_cursor_execute", capture)
    try:
        await timed_get(client, admin.token, "/api/v1/gs?page_size=25")  # warm-up
        views = {
            "default page": "/api/v1/gs?page=1&page_size=25",
            "deep page": "/api/v1/gs?page=150&page_size=25",
            "status filter": "/api/v1/gs?status=INSPECTION&page_size=25",
            "party filter": f"/api/v1/gs?party_id={masters.party}&page_size=25",
            "flag filter": "/api/v1/gs?flag=has_hazard&page_size=25",
            "search (party name)": "/api/v1/gs?q=Test%20Party&page_size=25",
            "sort by gs_no": "/api/v1/gs?sort=gs_no&page_size=100",
        }
        timings: dict[str, float] = {}
        for name, path in views.items():
            elapsed, body = await timed_get(client, admin.token, path)
            timings[name] = elapsed
            assert body["total"] >= (
                N if name in ("default page", "deep page", "search (party name)") else 1
            ), name
    finally:
        event.remove(db_conn, "before_cursor_execute", capture)

    print("\nGS list server time with", N, "GS:", json.dumps(timings, indent=2))
    slow = {k: v for k, v in timings.items() if v >= BUDGET_SECONDS}
    assert not slow, slow

    # EXPLAIN the default page query exactly as the API ran it.
    statement, params = captured[1]
    plan = (
        as_admin(db_conn)
        .exec_driver_sql("explain (analyze, format json) " + statement, params)
        .scalar_one()
    )
    plan_text = json.dumps(plan)
    print("Default page plan:", plan[0]["Plan"]["Node Type"], plan[0]["Execution Time"], "ms")
    assert "goods_slips_created_at_idx" in plan_text, plan_text
    assert plan[0]["Execution Time"] < BUDGET_SECONDS * 1000
