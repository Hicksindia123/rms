"""Reports & MIS (prompt P4-02, master plan §10 "Report columns").

* Registry ↔ catalogue consistency; every report runs and returns its declared columns/totals.
* Known totals on the local scenario data: each report's total equals the same quantity computed
  directly from the source tables (and the dashboard formulas where a widget shows it).
* R-14: zero exceptions on a healthy ledger; injected inconsistencies appear.
* Permissions: catalogue = what each role's grants allow; 403 for anything else; scope own /
  department / all; export needs reports.export.
* Validation, sorting, pagination, CSV / XLSX export (incl. 50,000 streamed rows), print payload,
  column preferences (user, role default + config_change_log) and saved filters.
"""

from __future__ import annotations

import csv
import io
import tracemalloc
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy import Connection, text

from app.modules.reports.registry import REGISTRY, REPORTS, Col, ReportDef
from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, fetch_all
from tests.integration.test_gate_inward import Masters, _payload, _values

API = "/api/v1"
TZ = "Asia/Kolkata"


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _get(client: AsyncClient, token: str, path: str, **params: Any) -> Any:
    res = await client.get(f"{API}{path}", headers=_h(token), params=params)
    assert res.status_code == 200, res.text
    return res.json()


async def _data(client: AsyncClient, token: str, code: str, **params: Any) -> dict[str, Any]:
    body: dict[str, Any] = await _get(client, token, f"/reports/{code}/data", **params)
    return body


def _scalar(conn: Connection, sql: str, **params: Any) -> Any:
    return as_admin(conn).execute(text(sql), params).scalar()


def _today(conn: Connection) -> date:
    value = _scalar(conn, "select (now() at time zone :tz)::date", tz=TZ)
    assert isinstance(value, date)
    return value


@pytest.fixture
def admin(users: UserFactory, make_token: JwtFactory) -> str:
    return make_token(users.create(super_admin=True, full_name="Report Admin"))


def _custom_role(conn: Connection, grants: dict[tuple[str, str], str]) -> str:
    """A non-system role with the given {(module, action): scope} grants; returns its code."""
    c = as_admin(conn)
    code = f"TEST_RPT_{uuid.uuid4().hex[:8].upper()}"
    role_id = c.execute(
        text("insert into public.roles (code, name) values (:c, :c) returning id"), {"c": code}
    ).scalar_one()
    for (module, action), scope in grants.items():
        c.execute(
            text(
                """insert into public.role_permissions (role_id, permission_id, scope)
                   select :r, p.id, :s from public.permissions p
                    where p.module_code = :m and p.action = :a"""
            ),
            {"r": role_id, "s": scope, "m": module, "a": action},
        )
    return code


# --- registry / catalogue ----------------------------------------------------------------------
def test_registry_matches_catalogue(db_conn: Connection) -> None:
    codes = {r["code"] for r in fetch_all(db_conn, "select code from public.report_definitions")}
    assert codes == set(REGISTRY) == {f"R-{n:02d}" for n in range(1, 19)}
    for defn in REPORTS:
        keys = [c.key for c in defn.columns]
        assert len(keys) == len(set(keys)), defn.code
        assert defn.column(defn.default_sort[0]) is not None, defn.code
        assert defn.column(defn.tiebreak) is not None, defn.code
        assert defn.default_columns, defn.code
        assert "{where}" in defn.sql, defn.code
        for f in defn.filters:
            if f.mode == "outer":
                assert defn.column(f.expr or f.key) is not None, (defn.code, f.key)
            if f.mode == "inner":
                assert f.expr, (defn.code, f.key)
            if f.mode == "param":
                assert f":p_{f.key}" in defn.sql, (defn.code, f.key)


@pytest.mark.parametrize("code", sorted(REGISTRY))
async def test_every_report_runs(client: AsyncClient, admin: str, code: str) -> None:
    defn = REGISTRY[code]
    definition = await _get(client, admin, f"/reports/{code}")
    assert [c["key"] for c in definition["columns"]] == [c.key for c in defn.columns]
    assert definition["visible_columns"] == defn.default_columns
    assert definition["column_source"] == "default"
    body = await _data(client, admin, code, page_size=5)
    assert body["total"] >= len(body["rows"])
    for row in body["rows"]:
        assert set(row) == {c.key for c in defn.columns} | {"_links"}
    for c in defn.columns:
        if c.total is not None:
            assert c.key in body["totals"], (code, c.key)
    # every sortable column sorts both ways without error
    for c in defn.columns:
        for direction in ("asc", "desc"):
            res = await client.get(
                f"{API}/reports/{code}/data",
                headers=_h(admin),
                params={"sort": c.key, "dir": direction, "page_size": 3},
            )
            assert res.status_code == 200, (code, c.key, res.text)


# --- known totals on the scenario data ---------------------------------------------------------
async def test_gs_register_and_lifecycle_totals(
    client: AsyncClient, db_conn: Connection, admin: str
) -> None:
    gs = _scalar(db_conn, "select count(*) from public.goods_slips")
    received = _scalar(db_conn, "select coalesce(sum(received_qty), 0) from public.gs_items")
    r03 = await _data(client, admin, "R-03", page_size=1)
    assert r03["total"] == gs
    assert r03["totals"]["received_qty"] == received
    r02 = await _data(client, admin, "R-02", page_size=1)
    assert r02["total"] == gs
    closed = _scalar(db_conn, "select count(*) from public.goods_slips where status = 'CLOSED'")
    assert (await _data(client, admin, "R-02", status="CLOSED", page_size=1))["total"] == closed


async def test_pending_work_matches_open_tasks(
    client: AsyncClient, db_conn: Connection, admin: str
) -> None:
    open_tasks = _scalar(
        db_conn,
        """select count(*) from public.workflow_tasks t
            join public.goods_slips g on g.id = t.gs_id where t.status = 'OPEN'""",
    )
    body = await _data(client, admin, "R-01", page_size=500)
    t = body["totals"]
    assert t["open_tasks"] == open_tasks
    assert t["age_0_1"] + t["age_1_3"] + t["age_3_7"] + t["age_over_7"] == open_tasks
    for row in body["rows"]:
        assert row["_links"]["step_label"] == f"/mywork?step={row['step_code']}"


async def test_inventory_position_matches_balances(
    client: AsyncClient, db_conn: Connection, admin: str
) -> None:
    all_qty = _scalar(db_conn, "select coalesce(sum(qty), 0) from public.stock_balances")
    live_qty = _scalar(
        db_conn,
        """select coalesce(sum(b.qty), 0) from public.stock_balances b
             join public.inventory_locations il on il.id = b.location_id
            where il.location_class not in ('DISPATCHED', 'CREDITED', 'SCRAP_DISPOSED')""",
    )
    today = _today(db_conn).isoformat()
    full = await _data(client, admin, "R-13", as_on=today, include_terminal="true", page_size=1)
    assert full["totals"]["qty"] == all_qty
    live = await _data(client, admin, "R-13", page_size=1)
    assert live["applied"]["as_on"] == today
    assert live["totals"]["qty"] == live_qty
    # As on a date before any movement: nothing.
    empty = await _data(client, admin, "R-13", as_on="2000-01-01", include_terminal="true")
    assert empty["total"] == 0


async def test_inventory_position_is_as_on_the_date(
    client: AsyncClient,
    db_conn: Connection,
    users: UserFactory,
    make_token: JwtFactory,
    admin: str,
) -> None:
    """A movement dated today is in today's position and not in yesterday's."""
    c = as_admin(db_conn)
    today = _today(db_conn)
    before_today = (
        await _data(client, admin, "R-13", as_on=today.isoformat(), include_terminal="true")
    )["totals"]["qty"] or 0
    before_yday = (
        await _data(
            client,
            admin,
            "R-13",
            as_on=(today - timedelta(days=1)).isoformat(),
            include_terminal="true",
        )
    )["totals"]["qty"] or 0
    battery_code = f"TB{uuid.uuid4().hex[:6].upper()}"
    c.execute(
        text("insert into public.battery_types (code, name) values (:c, 'Test cell')"),
        {"c": battery_code},
    )
    receiver = make_token(users.create(roles=["SPARE_PARTS_MANAGER"]))
    res = await client.post(
        f"{API}/inventory/batteries/receipts",
        json={"battery_type": battery_code, "qty": 7, "ref": "RPT-TEST"},
        headers={**_h(receiver), "Idempotency-Key": f"test-{uuid.uuid4()}"},
    )
    assert res.status_code == 201, res.text
    after_today = (
        await _data(client, admin, "R-13", as_on=today.isoformat(), include_terminal="true")
    )["totals"]["qty"]
    after_yday = (
        await _data(
            client,
            admin,
            "R-13",
            as_on=(today - timedelta(days=1)).isoformat(),
            include_terminal="true",
        )
    )["totals"]["qty"] or 0
    assert after_today == before_today + 7
    assert after_yday == before_yday


async def test_stock_reconciliation_zero_then_injected(
    client: AsyncClient, db_conn: Connection, admin: str
) -> None:
    clean = await _data(client, admin, "R-14")
    assert clean["total"] == 0, clean["rows"][:5]

    c = as_admin(db_conn)
    row = (
        c.execute(
            text(
                """select b.lot_id, b.location_id, il.code
                     from public.stock_balances b
                     join public.inventory_locations il on il.id = b.location_id
                     join public.stock_lots l on l.id = b.lot_id
                    where b.qty > 0 and l.gs_item_id is not null limit 1"""
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        pytest.skip("no GS stock balance in the local database to corrupt")
    # Corrupt the stored balance behind the ledger's back (test-only: triggers bypassed).
    c.execute(text("set local session_replication_role = replica"))
    try:
        c.execute(
            text(
                "update public.stock_balances set qty = qty + 5 "
                "where lot_id = :l and location_id = :loc"
            ),
            {"l": row["lot_id"], "loc": row["location_id"]},
        )
    finally:
        c.execute(text("set local session_replication_role = origin"))
    body = await _data(client, admin, "R-14", page_size=50)
    codes = {r["check_code"] for r in body["rows"]}
    assert {"IC-01", "IC-03"} <= codes
    ic03 = next(r for r in body["rows"] if r["check_code"] == "IC-03")
    assert ic03["difference"] == 5 and ic03["location_code"] == row["code"]
    only = await _data(client, admin, "R-14", check_code="IC-03")
    assert {r["check_code"] for r in only["rows"]} == {"IC-03"}


async def test_battery_reconciliation(client: AsyncClient, db_conn: Connection, admin: str) -> None:
    installed = _scalar(
        db_conn,
        "select coalesce(sum(batteries_installed), 0) from public.technician_receiving_records",
    )
    body = await _data(client, admin, "R-11", date_from="2000-01-01", page_size=100)
    t = body["totals"]
    assert t["batteries_installed"] == installed
    assert t["consumed_qty"] == installed  # IC-09 holds on a healthy ledger
    assert t["installed_minus_consumed"] == 0
    for r in body["rows"]:
        assert (
            r["closing_qty"]
            == (r["opening_qty"] + r["received_qty"] + r["adjusted_qty"] - r["consumed_qty"])
            or r["battery_code"] is None
        )


async def test_commercial_and_inspection_totals(
    client: AsyncClient, db_conn: Connection, admin: str
) -> None:
    cns = _scalar(db_conn, "select count(*) from public.credit_notes")
    value = _scalar(db_conn, "select coalesce(sum(total_value), 0) from public.credit_notes")
    r16 = await _data(client, admin, "R-16", page_size=1)
    assert r16["total"] == cns
    assert float(r16["totals"]["total_value"] or 0) == pytest.approx(float(value))
    graded = _scalar(
        db_conn,
        """select coalesce(sum(a.qty), 0) from public.inspection_allocations a
            join public.inspections i on i.id = a.inspection_id where i.status = 'FINAL'""",
    )
    r05 = await _data(client, admin, "R-05", page_size=500)
    assert r05["totals"]["qty"] == graded
    hazard = _scalar(db_conn, "select coalesce(sum(qty), 0) from public.rejections where hazard")
    r06 = await _data(client, admin, "R-06", hazard="true", page_size=1)
    assert r06["totals"]["qty"] == hazard


async def test_pendency_and_audit_match_dashboard_formulas(
    client: AsyncClient, db_conn: Connection, admin: str
) -> None:
    open_qty = _scalar(
        db_conn,
        """select coalesce(sum(p.qty), 0) from public.pendencies p
            join public.goods_slips g on g.id = p.gs_id where p.status = 'OPEN'""",
    )
    r08 = await _data(client, admin, "R-08", status="OPEN", page_size=1)
    assert r08["totals"]["qty"] == open_qty

    today = _today(db_conn)
    start, end = today - timedelta(days=30), today - timedelta(days=1)
    counts = (
        as_admin(db_conn)
        .execute(
            text(
                """select count(*) filter (where status = 'CONFIRMED') as on_time,
                          count(*) filter (where status = 'LATE') as late
                     from public.container_audit_days where audit_date between :f and :t"""
            ),
            {"f": start, "t": end},
        )
        .mappings()
        .one()
    )
    r07 = await _data(
        client, admin, "R-07", date_from=start.isoformat(), date_to=end.isoformat(), page_size=1
    )
    assert r07["total"] == 30  # one row per day, recorded or not
    assert r07["totals"]["on_time"] == counts["on_time"]
    assert r07["totals"]["late"] == counts["late"]


async def test_user_activity_totals(client: AsyncClient, db_conn: Connection, admin: str) -> None:
    events = _scalar(db_conn, "select count(*) from rms_reports.user_activity_events")
    body = await _data(client, admin, "R-18", date_from="2000-01-01", page_size=1)
    assert body["totals"]["actions"] == events


async def test_new_goods_slip_appears_with_drilldown(
    client: AsyncClient, db_conn: Connection, users: UserFactory, make_token: JwtFactory, admin: str
) -> None:
    masters = Masters(db_conn)
    party = _scalar(db_conn, "select name from public.parties where id = :p", p=masters.party)
    before = (await _data(client, admin, "R-03", page_size=1))["total"]
    gate = make_token(users.create(roles=["GATE_INWARD"]))
    res = await client.post(
        f"{API}/gs",
        json={"party_id": str(masters.party), **_payload(_values())},
        headers={**_h(gate), "Idempotency-Key": f"test-{uuid.uuid4()}"},
    )
    assert res.status_code == 201, res.text
    gs_id = res.json()["goods_slip"]["id"]
    assert (await _data(client, admin, "R-03", page_size=1))["total"] == before + 1
    mine = await _data(client, admin, "R-03", party=party)
    assert mine["total"] == 1
    row = mine["rows"][0]
    assert row["_links"]["gs_no"] == f"/gs/{gs_id}"
    assert row["status"] == "GATE_CREATED" and row["carton_count"] == 3
    station = await _data(client, admin, "R-03", station=str(masters.station_a), party=party)
    assert station["total"] == 1
    other = await _data(client, admin, "R-03", station=str(masters.station_b), party=party)
    assert other["total"] == 0


# --- permissions & scope -------------------------------------------------------------------------
def _role_grants(conn: Connection, role: str) -> set[tuple[str, str]]:
    return {
        (r["module_code"], r["action"])
        for r in fetch_all(
            conn,
            """select p.module_code, p.action from public.role_permissions rp
               join public.permissions p on p.id = rp.permission_id
               join public.roles r on r.id = rp.role_id where r.code = :c""",
            c=role,
        )
    }


def _expected_reports(grants: set[tuple[str, str]]) -> set[str]:
    if ("reports", "view") not in grants:
        return set()
    return {d.code for d in REPORTS if all(p in grants for p in d.requires)}


@pytest.mark.parametrize(
    "role",
    [
        "INWARD_VERIFIER",
        "REPLACEMENT_MANAGER",
        "INTERMEDIATE_STORE_MANAGER",
        "SPARE_PARTS_MANAGER",
        "ACCOUNTS",
        "MANAGEMENT_VIEWER",
        "TECHNICIAN",
    ],
)
async def test_catalogue_is_permission_filtered(
    client: AsyncClient, db_conn: Connection, users: UserFactory, make_token: JwtFactory, role: str
) -> None:
    grants = _role_grants(db_conn, role)
    token = make_token(users.create(roles=[role]))
    expected = _expected_reports(grants)
    res = await client.get(f"{API}/reports", headers=_h(token))
    if not expected:
        assert res.status_code == 403
        return
    assert res.status_code == 200, res.text
    listed = {r["code"] for g in res.json() for r in g["reports"]}
    assert listed == expected
    for code in sorted(set(REGISTRY) - expected)[:3]:
        denied = await client.get(f"{API}/reports/{code}/data", headers=_h(token))
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "REPORT_FORBIDDEN"
    export = await client.get(
        f"{API}/reports/{sorted(expected)[0]}/export", headers=_h(token), params={"format": "csv"}
    )
    assert export.status_code == (200 if ("reports", "export") in grants else 403)


async def test_own_scope(
    client: AsyncClient, db_conn: Connection, users: UserFactory, make_token: JwtFactory
) -> None:
    role = _custom_role(db_conn, {("reports", "view"): "own", ("inventory", "view"): "all"})
    # GATE_INWARD performs S1_GATE (and grants goods_slips.view); reports.view stays `own`.
    uid = users.create(roles=["GATE_INWARD", role])
    token = make_token(uid)
    groups = await _get(client, token, "/reports")
    listed = {r["code"] for g in groups for r in g["reports"]}
    assert "R-03" in listed
    assert "R-13" not in listed and "R-14" not in listed  # facility-wide: scope `all` only
    denied = await client.get(f"{API}/reports/R-13/data", headers=_h(token))
    assert denied.status_code == 403
    assert denied.json()["error"]["details"]["scope_required"] == "all"
    assert (await _data(client, token, "R-03"))["total"] == 0

    masters = Masters(db_conn)
    res = await client.post(
        f"{API}/gs",
        json={"party_id": str(masters.party), **_payload(_values())},
        headers={**_h(token), "Idempotency-Key": f"test-{uuid.uuid4()}"},
    )
    assert res.status_code == 201, res.text
    body = await _data(client, token, "R-03")
    assert body["total"] == 1
    assert body["rows"][0]["gs_no"] == res.json()["goods_slip"]["gs_no"]


async def test_department_scope(
    client: AsyncClient, db_conn: Connection, users: UserFactory, make_token: JwtFactory
) -> None:
    c = as_admin(db_conn)
    depts = [
        c.execute(
            text("insert into public.departments (code, name) values (:c, :c) returning id"),
            {"c": f"TD_{uuid.uuid4().hex[:6].upper()}"},
        ).scalar_one()
        for _ in range(2)
    ]
    creator = users.create(roles=["GATE_INWARD"])
    role = _custom_role(
        db_conn, {("reports", "view"): "department", ("goods_slips", "view"): "all"}
    )
    same, other = users.create(roles=[role]), users.create(roles=[role])
    for uid, dept in ((creator, depts[0]), (same, depts[0]), (other, depts[1])):
        c.execute(
            text("update public.profiles set department_id = :d where id = :u"),
            {"d": dept, "u": uid},
        )
    masters = Masters(db_conn)
    res = await client.post(
        f"{API}/gs",
        json={"party_id": str(masters.party), **_payload(_values())},
        headers={**_h(make_token(creator)), "Idempotency-Key": f"test-{uuid.uuid4()}"},
    )
    assert res.status_code == 201, res.text
    assert (await _data(client, make_token(same), "R-03"))["total"] == 1
    assert (await _data(client, make_token(other), "R-03"))["total"] == 0


async def test_no_reports_permission(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    token = make_token(users.create(roles=["GATE_INWARD"]))
    for path in ("/reports", "/reports/R-03", "/reports/R-03/data", "/reports/R-03/print"):
        res = await client.get(f"{API}{path}", headers=_h(token))
        assert res.status_code == 403, path


# --- validation, sorting, pagination -----------------------------------------------------------
@pytest.mark.parametrize(
    ("params", "loc"),
    [
        ({"nope": "1"}, "nope"),
        ({"status": "NOT_A_STATUS"}, "status"),
        ({"date_from": "2026-13-01"}, "date_from"),
        ({"date_from": "2026-02-01", "date_to": "2026-01-01"}, "date_from"),
        ({"state": "not-a-uuid"}, "state"),
        ({"sort": "nope"}, "sort"),
        ({"dir": "sideways"}, "dir"),
        ({"page_size": "1000"}, "page_size"),
    ],
)
async def test_invalid_params(
    client: AsyncClient, admin: str, params: dict[str, str], loc: str
) -> None:
    res = await client.get(f"{API}/reports/R-03/data", headers=_h(admin), params=params)
    assert res.status_code == 422, res.text
    err = res.json()["error"]
    assert err["code"] == "INVALID_REPORT_PARAMS"
    assert any(d["loc"] == [loc] for d in err["details"]), err


async def test_repeated_param_and_unknown_report(client: AsyncClient, admin: str) -> None:
    res = await client.get(
        f"{API}/reports/R-03/data?status=CLOSED&status=INSPECTION", headers=_h(admin)
    )
    assert res.status_code == 422
    assert (await client.get(f"{API}/reports/R-99/data", headers=_h(admin))).status_code == 404
    assert (await client.get(f"{API}/reports/X-01", headers=_h(admin))).status_code == 422
    too_long = await client.get(
        f"{API}/reports/R-07/data",
        headers=_h(admin),
        params={"date_from": "2024-01-01", "date_to": "2026-01-01"},
    )
    assert too_long.status_code == 422


async def test_sorting_and_pagination(client: AsyncClient, admin: str) -> None:
    first = await _data(client, admin, "R-03", sort="gs_no", dir="asc", page_size=3, page=1)
    second = await _data(client, admin, "R-03", sort="gs_no", dir="asc", page_size=3, page=2)
    if first["total"] < 6:
        pytest.skip("needs at least 6 goods slips")
    keys = [r["gs_no"] for r in first["rows"] + second["rows"]]
    assert keys == sorted(keys) and len(set(keys)) == 6
    desc = await _data(client, admin, "R-03", sort="received_qty", dir="desc", page_size=20)
    qty = [r["received_qty"] for r in desc["rows"]]
    assert qty == sorted(qty, reverse=True)
    assert desc["sort"] == {"key": "received_qty", "dir": "desc"}


# --- export --------------------------------------------------------------------------------------
async def test_csv_export(client: AsyncClient, db_conn: Connection, admin: str) -> None:
    res = await client.get(
        f"{API}/reports/R-03/export",
        headers=_h(admin),
        params={"format": "csv", "status": "CLOSED", "columns": "gs_no,party_name,received_qty"},
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/csv")
    assert 'filename="R-03-' in res.headers["content-disposition"]
    content = res.content.decode("utf-8")
    assert content.startswith("﻿")
    rows = list(csv.reader(io.StringIO(content.lstrip("﻿"))))
    assert rows[0] == ["GS No.", "Party", "Received qty"]
    closed = _scalar(db_conn, "select count(*) from public.goods_slips where status = 'CLOSED'")
    assert len(rows) - 1 == closed


async def test_xlsx_export_and_limits(client: AsyncClient, db_conn: Connection, admin: str) -> None:
    res = await client.get(
        f"{API}/reports/R-16/export", headers=_h(admin), params={"format": "xlsx"}
    )
    assert res.status_code == 200, res.text
    assert "spreadsheetml" in res.headers["content-type"]
    wb = load_workbook(io.BytesIO(res.content), read_only=True)
    ws = wb["Report"]
    rows = list(ws.iter_rows(values_only=True))
    labels = [c.label for c in REGISTRY["R-16"].columns if c.default]
    assert list(rows[0]) == labels
    assert len(rows) - 1 == _scalar(db_conn, "select count(*) from public.credit_notes")
    assert wb["Filters"]["A1"].value.startswith("R-16")

    as_admin(db_conn).execute(
        text("update public.system_settings set value = '1' where key = 'report_export_max_rows'")
    )
    big = await client.get(
        f"{API}/reports/R-03/export", headers=_h(admin), params={"format": "csv"}
    )
    assert big.status_code == 422
    assert big.json()["error"]["code"] == "EXPORT_TOO_LARGE"
    bad_cols = await client.get(
        f"{API}/reports/R-03/export",
        headers=_h(admin),
        params={"format": "csv", "columns": "gs_no,nope", "status": "GATE_CREATED"},
    )
    assert bad_cols.status_code == 422


_BIG = ReportDef(
    code="R-99",
    requires=(),
    sql=(
        "select g as n, 'row ' || g as label, (g * 1.25)::numeric(12, 2) as amount, "
        "now() - g * interval '1 minute' as at "
        "from generate_series(1, 50000) g where {where}"
    ),
    columns=(
        Col("n", "No.", "int"),
        Col("label", "Label"),
        Col("amount", "Amount", "money"),
        Col("at", "At", "datetime"),
    ),
    filters=(),
    default_sort=("n", "asc"),
    tiebreak="n",
    owner_expr=None,
)


@pytest.fixture
def big_report(db_conn: Connection, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    as_admin(db_conn).execute(
        text(
            """insert into public.report_definitions (code, group_code, group_title, title)
               values ('R-99', 'TEST', 'Test', '50k rows')"""
        )
    )
    monkeypatch.setitem(REGISTRY, "R-99", _BIG)
    yield "R-99"


async def test_xlsx_export_of_50000_rows_is_streamed(
    client: AsyncClient, admin: str, big_report: str
) -> None:
    tracemalloc.start()
    try:
        res = await client.get(
            f"{API}/reports/{big_report}/export", headers=_h(admin), params={"format": "xlsx"}
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert res.status_code == 200, res.text
    # Rows stream from a server-side cursor into openpyxl's write-only temp file: Python memory
    # stays far below what 50,000 materialised rows would take (measured ~10 MB incl. response).
    assert peak < 60 * 1024 * 1024, f"peak {peak / 1e6:.1f} MB"
    wb = load_workbook(io.BytesIO(res.content), read_only=True)
    ws = wb["Report"]
    count = sum(1 for _ in ws.iter_rows(min_row=2, values_only=True))
    assert count == 50_000
    csv_res = await client.get(
        f"{API}/reports/{big_report}/export", headers=_h(admin), params={"format": "csv"}
    )
    assert csv_res.status_code == 200
    assert csv_res.content.count(b"\r\n") == 50_001


# --- print ---------------------------------------------------------------------------------------
async def test_print_payload(client: AsyncClient, db_conn: Connection, admin: str) -> None:
    body = await _get(client, admin, "/reports/R-03/print", status="CLOSED")
    assert body["branding"]["app_name"]
    assert {"label": "Status", "value": "CLOSED"} in body["filters_used"]
    assert body["generated_by"] == "Report Admin"
    assert [c["key"] for c in body["columns"]] == REGISTRY["R-03"].default_columns
    assert body["printed_rows"] == len(body["rows"]) == body["total_rows"]
    assert body["truncated"] is False

    as_admin(db_conn).execute(
        text("update public.system_settings set value = '1' where key = 'report_print_max_rows'")
    )
    small = await _get(client, admin, "/reports/R-03/print")
    if small["total_rows"] > 1:
        assert small["truncated"] is True and len(small["rows"]) == 1


# --- column preferences --------------------------------------------------------------------------
async def test_column_preferences(
    client: AsyncClient,
    db_conn: Connection,
    users: UserFactory,
    make_token: JwtFactory,
    admin: str,
) -> None:
    token = make_token(users.create(roles=["ACCOUNTS"]))
    put = await client.put(
        f"{API}/reports/R-16/columns", headers=_h(token), json={"columns": ["voucher_no", "qty"]}
    )
    assert put.status_code == 200, put.text
    d = await _get(client, token, "/reports/R-16")
    assert d["visible_columns"] == ["voucher_no", "qty"] and d["column_source"] == "user"
    bad = await client.put(
        f"{API}/reports/R-16/columns", headers=_h(token), json={"columns": ["voucher_no", "x"]}
    )
    assert bad.status_code == 422
    # export without `columns` uses the saved choice
    exp = await client.get(
        f"{API}/reports/R-16/export", headers=_h(token), params={"format": "csv"}
    )
    assert exp.content.decode("utf-8").lstrip("﻿").splitlines()[0] == "CN / JV No.,Qty"

    # Admin default for the role applies once the user's own choice is reset.
    forbidden = await client.put(
        f"{API}/admin/report-column-defaults/R-16/ACCOUNTS",
        headers=_h(token),
        json={"columns": ["voucher_no"]},
    )
    assert forbidden.status_code == 403
    res = await client.put(
        f"{API}/admin/report-column-defaults/R-16/ACCOUNTS",
        headers=_h(admin),
        json={"columns": ["voucher_no", "total_value", "notified"], "reason": "Accounts view"},
    )
    assert res.status_code == 200, res.text
    reset = await client.delete(f"{API}/reports/R-16/columns", headers=_h(token))
    assert reset.json()["column_source"] == "role"
    d = await _get(client, token, "/reports/R-16")
    assert d["visible_columns"] == ["voucher_no", "total_value", "notified"]
    assert d["column_source_role"] == "ACCOUNTS"
    log = fetch_all(
        db_conn,
        """select action, reason from public.config_change_log
            where entity_type = 'report_column_defaults' and entity_id = 'R-16:ACCOUNTS'
            order by changed_at""",
    )
    assert log[-1] == {"action": "CREATE", "reason": "Accounts view"}
    roles = await _get(client, admin, "/admin/report-column-defaults/roles")
    assert {"code": "ACCOUNTS", "name": "Accounts Team"} in roles
    listed = await _get(client, admin, "/admin/report-column-defaults")
    assert any(r["report_code"] == "R-16" and r["role_code"] == "ACCOUNTS" for r in listed)
    gone = await client.delete(
        f"{API}/admin/report-column-defaults/R-16/ACCOUNTS",
        headers=_h(admin),
        params={"reason": "back to default"},
    )
    assert gone.status_code == 204
    d = await _get(client, token, "/reports/R-16")
    assert d["column_source"] == "default"


# --- saved filters -------------------------------------------------------------------------------
async def test_saved_filters(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, admin: str
) -> None:
    token = make_token(users.create(roles=["REPLACEMENT_MANAGER"]))
    url = f"{API}/reports/R-03/saved-filters"
    first = await client.post(
        url,
        headers=_h(token),
        json={"name": "Closed", "params": {"status": "CLOSED"}, "is_default": True},
    )
    assert first.status_code == 201, first.text
    dup = await client.post(url, headers=_h(token), json={"name": "closed", "params": {}})
    assert dup.status_code == 409
    invalid = await client.post(
        url, headers=_h(token), json={"name": "Bad", "params": {"status": "NOPE"}}
    )
    assert invalid.status_code == 422
    reserved = await client.post(
        url, headers=_h(token), json={"name": "Page", "params": {"page": "2"}}
    )
    assert reserved.status_code == 422
    second = await client.post(
        url,
        headers=_h(token),
        json={"name": "Open RO", "params": {"category": "RO"}, "is_default": True},
    )
    assert second.status_code == 201
    d = await _get(client, token, "/reports/R-03")
    saved = {s["name"]: s for s in d["saved_filters"]}
    assert saved["Open RO"]["is_default"] and not saved["Closed"]["is_default"]
    assert saved["Closed"]["params"] == {"status": "CLOSED"}
    # Another user cannot delete it.
    other = await client.delete(f"{url}/{first.json()['id']}", headers=_h(admin))
    assert other.status_code == 404
    mine = await client.delete(f"{url}/{first.json()['id']}", headers=_h(token))
    assert mine.status_code == 204
