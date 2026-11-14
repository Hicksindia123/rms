"""Dashboards & widgets (prompt P4-01, master plan §10 "Dashboard widgets", §11).

* Registry ↔ catalogue ↔ seeded layouts are consistent; every §3.3 role has a relevant layout.
* Widgets the caller lacks a permission for are never returned (layout and data endpoints).
* Widget numbers equal the totals of the list screens they link to (parity), on the seeded local
  scenario data, and move with a new goods slip created through the API (delta scenario).
* Caching, parameter validation, admin layout CRUD + config_change_log, guard-event recording.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text

from app.modules.dashboards.registry import REGISTRY, WIDGETS
from app.modules.dashboards.service import clear_widget_cache
from tests.conftest import JwtFactory
from tests.integration.conftest import Override, UserFactory, as_admin, fetch_all, publish_workflow
from tests.integration.test_gate_inward import Masters, _payload, _values

API = "/api/v1"
ALL_ROLES = [
    "SUPER_ADMIN",
    "GATE_INWARD",
    "INWARD_VERIFIER",
    "REPLACEMENT_MANAGER",
    "INTERMEDIATE_STORE_MANAGER",
    "TECHNICIAN_COORDINATOR",
    "TECHNICIAN",
    "SPARE_PARTS_TECHNICIAN",
    "SPARE_PARTS_MANAGER",
    "ACCOUNTS",
    "DISPATCH",
    "MAIN_STORE",
    "MANAGEMENT_VIEWER",
]


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    clear_widget_cache()
    yield
    clear_widget_cache()


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _get(client: AsyncClient, token: str, path: str, **params: Any) -> Any:
    res = await client.get(f"{API}{path}", headers=_h(token), params=params)
    assert res.status_code == 200, res.text
    return res.json()


async def _widget(client: AsyncClient, token: str, code: str, **params: Any) -> dict[str, Any]:
    body = await _get(client, token, f"/dashboard/widgets/{code}", **params)
    assert body["code"] == code
    data: dict[str, Any] = body["data"]
    return data


@pytest.fixture
def admin(users: UserFactory, make_token: JwtFactory) -> str:
    return make_token(users.create(super_admin=True, full_name="Dash Admin"))


# --- registry / catalogue / seeded layouts -----------------------------------------------------
def test_registry_matches_catalogue(db_conn: Connection) -> None:
    codes = {r["code"] for r in fetch_all(db_conn, "select code from public.dashboard_widgets")}
    assert codes == set(REGISTRY), (
        "dashboard_widgets and the widget registry must list the same codes"
    )
    assert len(WIDGETS) == len(REGISTRY) == 20


def test_every_role_has_a_layout_its_permissions_allow(db_conn: Connection) -> None:
    rows = fetch_all(
        db_conn,
        """select r.code, l.widgets from public.roles r
           left join public.role_dashboard_layouts l on l.role_id = r.id""",
    )
    layouts = {r["code"]: r["widgets"] for r in rows}
    for role in ALL_ROLES:
        widgets = layouts.get(role)
        assert widgets, f"role {role} has no seeded dashboard"
        grants = {
            (r["module_code"], r["action"])
            for r in fetch_all(
                db_conn,
                """select p.module_code, p.action from public.role_permissions rp
                   join public.permissions p on p.id = rp.permission_id
                   join public.roles r on r.id = rp.role_id where r.code = :c""",
                c=role,
            )
        }
        for entry in widgets:
            missing = REGISTRY[entry["code"]].missing(grants)
            assert not missing, f"{role} layout lists {entry['code']} but lacks {missing}"
        if role != "MANAGEMENT_VIEWER":
            # Operational roles land on their own task list first (§11 "task inbox first").
            first = widgets[0]["code"]
            assert first in {"MY_TASKS", "ADMIN_HEALTH"}, f"{role} starts with {first}"


def test_layout_trigger_rejects_unknown_widgets(db_conn: Connection) -> None:
    conn = as_admin(db_conn)
    sql = text(
        """update public.role_dashboard_layouts set widgets = cast(:w as jsonb)
            where role_id = (select id from public.roles where code = 'TECHNICIAN')"""
    )
    unknown = '[{"code":"NOPE","size":"S"}]'
    twice = '[{"code":"MY_TASKS","size":"S"},{"code":"MY_TASKS","size":"M"}]'
    with pytest.raises(Exception, match="unknown widgets"), conn.begin_nested():
        conn.execute(sql, {"w": unknown})
    with pytest.raises(Exception, match="more than once"), conn.begin_nested():
        conn.execute(sql, {"w": twice})


# --- permission filtering ----------------------------------------------------------------------
async def test_dashboard_lands_on_primary_role_and_hides_forbidden_widgets(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    token = make_token(users.create(roles=["ACCOUNTS"]))
    body = await _get(client, token, "/dashboard")
    assert body["role"]["code"] == "ACCOUNTS"
    codes = [w["code"] for w in body["widgets"]]
    assert codes == ["MY_TASKS", "ACCOUNTS_DOC_QUEUE", "CN_PIPELINE", "CN_ISSUED"]
    assert body["hidden_widget_count"] == 0
    assert body["poll_seconds"] == 60

    # Data of a widget outside the caller's permissions is never returned.
    for code in ("TECHNICIAN_WIP", "ADMIN_HEALTH", "FUNCTIONAL_STOCK", "CSR_APPROVALS_PENDING"):
        res = await client.get(f"{API}/dashboard/widgets/{code}", headers=_h(token))
        assert res.status_code == 403, code
        assert res.json()["error"]["code"] == "WIDGET_FORBIDDEN"


async def test_deny_override_removes_widgets_from_layout_and_data(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    uid = users.create(
        roles=["REPLACEMENT_MANAGER"], overrides=[Override("goods_slips", "view", "deny")]
    )
    token = make_token(uid)
    body = await _get(client, token, "/dashboard")
    codes = {w["code"] for w in body["widgets"]}
    gs_widgets = {w.code for w in WIDGETS if ("goods_slips", "view") in w.requires}
    assert not codes & gs_widgets
    assert body["hidden_widget_count"] >= 4  # pendencies, inspections, pipeline, trend
    res = await client.get(f"{API}/dashboard/widgets/GS_PIPELINE", headers=_h(token))
    assert res.status_code == 403


async def test_every_seeded_role_gets_only_permitted_widgets(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    for role in ALL_ROLES:
        if role == "SUPER_ADMIN":
            continue
        token = make_token(users.create(roles=[role]))
        body = await _get(client, token, "/dashboard")
        assert body["role"]["code"] == role
        assert body["widgets"], f"{role} landed on an empty dashboard"
        assert body["hidden_widget_count"] == 0, role
        for w in body["widgets"]:
            res = await client.get(f"{API}/dashboard/widgets/{w['code']}", headers=_h(token))
            assert res.status_code == 200, f"{role}/{w['code']}: {res.text}"


async def test_role_switcher_for_multi_role_users(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    token = make_token(users.create(roles=["INWARD_VERIFIER", "TECHNICIAN_COORDINATOR"]))
    body = await _get(client, token, "/dashboard")
    assert {r["code"] for r in body["available_roles"]} == {
        "INWARD_VERIFIER",
        "TECHNICIAN_COORDINATOR",
    }
    other = next(r["code"] for r in body["available_roles"] if r["code"] != body["role"]["code"])
    switched = await _get(client, token, "/dashboard", role=other)
    assert switched["role"]["code"] == other
    res = await client.get(f"{API}/dashboard", headers=_h(token), params={"role": "ACCOUNTS"})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "ROLE_NOT_HELD"


async def test_super_admin_lands_on_admin_dashboard(client: AsyncClient, admin: str) -> None:
    body = await _get(client, admin, "/dashboard")
    assert body["role"]["code"] == "SUPER_ADMIN"
    assert body["widgets"][0]["code"] == "ADMIN_HEALTH"


async def test_dashboards_require_a_token_and_view_permission(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    assert (await client.get(f"{API}/dashboard")).status_code == 401
    token = make_token(
        users.create(roles=["TECHNICIAN"], overrides=[Override("dashboards", "view", "deny")])
    )
    assert (await client.get(f"{API}/dashboard", headers=_h(token))).status_code == 403
    res = await client.get(f"{API}/dashboard/widgets/MY_TASKS", headers=_h(token))
    assert res.status_code == 403


# --- parity with the list screens (seeded local scenario data) ---------------------------------
async def test_widget_counts_match_list_totals(client: AsyncClient, admin: str) -> None:
    pipeline = await _widget(client, admin, "GS_PIPELINE")
    for row in pipeline["by_status"]:
        page = await _get(client, admin, "/gs", status=row["status"], page_size=1)
        assert row["count"] == page["total"], row["status"]
    assert pipeline["total_open"] == sum(r["count"] for r in pipeline["by_status"])

    today = await _widget(client, admin, "GATE_INWARDS_TODAY")
    page = await _get(
        client, admin, "/gs", date_from=today["date"], date_to=today["date"], page_size=1
    )
    assert today["count"] == page["total"]

    evidence = await _widget(client, admin, "EVIDENCE_PENDING")
    page = await _get(client, admin, "/gs", status=["GATE_CREATED", "UNBOXING"], page_size=1)
    assert evidence["count"] == page["total"]

    inspections = await _widget(client, admin, "INSPECTIONS_PENDING")
    page = await _get(client, admin, "/gs", status="INSPECTION", page_size=1)
    assert inspections["count"] == page["total"]

    csr = await _widget(client, admin, "CSR_APPROVALS_PENDING")
    if csr["count"] <= 100:
        cards = await _get(client, admin, "/csr-approvals/pending", limit=100)
        assert csr["count"] == len(cards)

    pend = await _widget(client, admin, "OPEN_PENDENCIES")
    rows = await _get(client, admin, "/pendencies", status="OPEN")
    assert pend["open_count"] == len(rows)
    assert pend["open_qty"] == sum(r["qty"] for r in rows)

    tr = await _widget(client, admin, "TRANSFERS_ATTENTION")
    for status, key in (("INITIATED", "awaiting_acceptance"), ("DISCREPANCY", "in_discrepancy")):
        page = await _get(client, admin, "/custody/transfers", status=status, page_size=1)
        assert tr[key] == page["total"], status

    wip = await _widget(client, admin, "TECHNICIAN_WIP")
    listed = 0
    pieces = 0
    for status in ("ALLOTTED", "IN_PROGRESS", "PARTIALLY_RECEIVED"):
        batches = await _get(client, admin, "/servicing/batches", status=status, page_size=100)
        listed += len(batches)
        pieces += sum(b["total_qty_allotted"] - b["total_qty_received"] for b in batches)
    assert wip["open_batches"] == listed
    assert wip["pieces_with_technicians"] == pieces

    bat = await _widget(client, admin, "BATTERY_STOCK")
    balances = await _get(client, admin, "/inventory/batteries/balances")
    assert bat["total_balance"] == sum(int(b["balance"]) for b in balances)

    dis = await _widget(client, admin, "DISMANTLING")
    queue = await _get(client, admin, "/dismantling/queue")
    lots = queue["dismantleable_lots"] + queue["disposal_required_lots"]
    assert dis["queue_lots"] == len(lots)
    assert (
        dis["queue_qty"] == queue["total_dismantleable_qty"] + queue["total_disposal_required_qty"]
    )

    fn = await _widget(client, admin, "FUNCTIONAL_STOCK")
    page = await _get(client, admin, "/inventory/stock", view="FUNCTIONAL", page_size=1)
    assert (fn["total_rows"], fn["total_qty"]) == (page["total"], page["total_qty"])
    for c in fn["by_condition"]:
        page = await _get(
            client,
            admin,
            "/inventory/stock",
            view="FUNCTIONAL",
            condition_class=c["key"],
            page_size=1,
        )
        assert (c["rows"], c["qty"]) == (page["total"], page["total_qty"]), c["key"]

    for code, view in (("HAZARD_QUARANTINE", "HAZARD_QUARANTINE"),):
        hz = await _widget(client, admin, code)
        page = await _get(client, admin, "/inventory/stock", view=view, page_size=1)
        assert (hz["rows"], hz["qty"]) == (page["total"], page["total_qty"])

    nf = await _widget(client, admin, "NON_FUNCTIONAL_STOCK")
    page = await _get(client, admin, "/inventory/stock", view="NON_FUNCTIONAL", page_size=1)
    assert (nf["non_functional_rows"], nf["non_functional_qty"]) == (
        page["total"],
        page["total_qty"],
    )
    page = await _get(client, admin, "/inventory/stock", view="SPARE_PARTS", page_size=1)
    assert nf["spare_parts_visible"] is True
    assert (nf["spare_parts_rows"], nf["spare_parts_qty"]) == (page["total"], page["total_qty"])

    cn = await _widget(client, admin, "CN_PIPELINE")
    wq = await _get(client, admin, "/credit-notes/work-queue")
    assert cn["awaiting_credit_gs"] == len(wq["pending_gs"])
    for status in ("DRAFT", "VERIFIED"):
        notes = await _get(client, admin, "/credit-notes", status=status, limit=200)
        if len(notes) < 200:
            assert cn[status.lower()] == len(notes), status

    acc = await _widget(client, admin, "ACCOUNTS_DOC_QUEUE")
    page = await _get(client, admin, "/accounts/document-queue", page_size=1)
    assert acc["count"] == page["total"]

    audit = await _widget(client, admin, "CONTAINER_AUDIT")
    cal = await _get(
        client,
        admin,
        "/container-audits",
        **{"from": audit["window_from"], "to": audit["window_to"]},
    )
    statuses = [d["status"] for d in cal["days"]]
    assert audit["confirmed_on_time"] == statuses.count("CONFIRMED")
    assert audit["confirmed_late"] == statuses.count("LATE")
    assert audit["today_status"] == cal["today_status"]
    assert 0 <= audit["compliance_pct"] <= 100


async def test_my_tasks_matches_inbox(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    for roles in (["INWARD_VERIFIER"], ["REPLACEMENT_MANAGER"], ["ACCOUNTS"]):
        token = make_token(users.create(roles=roles))
        tasks = await _widget(client, token, "MY_TASKS")
        inbox = await _get(client, token, "/tasks/mine", status="OPEN", page_size=1)
        assert tasks["total"] == inbox["total"], roles
        for step in tasks["by_step"]:
            page = await _get(
                client,
                token,
                "/tasks/mine",
                status="OPEN",
                step_code=step["step_code"],
                page_size=1,
            )
            assert step["count"] == page["total"], step["step_code"]


async def test_own_scope_gs_widgets_match_scoped_list(
    client: AsyncClient, db_conn: Connection, users: UserFactory, make_token: JwtFactory
) -> None:
    """A role with goods_slips.view at scope `own` sees the same (scoped) numbers as its list."""
    conn = as_admin(db_conn)
    code = f"TEST_OWN_{uuid.uuid4().hex[:6].upper()}"
    role_id = conn.execute(
        text("insert into public.roles (code, name) values (:c, :c) returning id"), {"c": code}
    ).scalar_one()
    conn.execute(
        text(
            """insert into public.role_permissions (role_id, permission_id, scope)
               select :r, p.id, case when p.module_code = 'goods_slips' then 'own' else 'all' end
                 from public.permissions p
                where (p.module_code, p.action)
                      in (('goods_slips','view'), ('dashboards','view'))"""
        ),
        {"r": role_id},
    )
    token = make_token(users.create(roles=[code]))
    pipeline = await _widget(client, token, "GS_PIPELINE")
    page = await _get(client, token, "/gs", status=[r["status"] for r in pipeline["by_status"]])
    assert pipeline["total_open"] == page["total"] == 0  # this user created no goods slips


async def test_new_goods_slip_moves_the_widgets(
    client: AsyncClient, db_conn: Connection, users: UserFactory, make_token: JwtFactory
) -> None:
    """Delta scenario: one GS created at the gate shows up in every widget that should count it."""
    masters = Masters(db_conn)
    gate_token = make_token(users.create(roles=["GATE_INWARD"]))
    verifier = make_token(users.create(roles=["INWARD_VERIFIER"]))
    admin_token = make_token(users.create(super_admin=True))

    async def snapshot() -> dict[str, int]:
        clear_widget_cache()
        return {
            "today": (await _widget(client, admin_token, "GATE_INWARDS_TODAY"))["count"],
            "evidence": (await _widget(client, admin_token, "EVIDENCE_PENDING"))["count"],
            "open": (await _widget(client, admin_token, "GS_PIPELINE"))["total_open"],
            "tasks": (await _widget(client, verifier, "MY_TASKS"))["total"],
        }

    before = await snapshot()
    res = await client.post(
        f"{API}/gs",
        json={"party_id": str(masters.party), **_payload(_values())},
        headers={**_h(gate_token), "Idempotency-Key": f"test-{uuid.uuid4()}"},
    )
    assert res.status_code == 201, res.text
    after = await snapshot()
    assert after == {k: v + 1 for k, v in before.items()}

    trend = await _widget(client, admin_token, "GS_TREND", weeks=4)
    assert len(trend["rows"]) == 4
    assert trend["rows"][-1]["opened"] >= 1


# --- caching / params --------------------------------------------------------------------------
async def test_aggregate_widgets_are_cached_but_tasks_are_live(
    client: AsyncClient, admin: str
) -> None:
    first = await _get(client, admin, "/dashboard/widgets/GS_PIPELINE")
    second = await _get(client, admin, "/dashboard/widgets/GS_PIPELINE")
    assert first["cached"] is False and second["cached"] is True
    assert second["data"] == first["data"]
    t1 = await _get(client, admin, "/dashboard/widgets/MY_TASKS")
    t2 = await _get(client, admin, "/dashboard/widgets/MY_TASKS")
    assert t1["cached"] is False and t2["cached"] is False


async def test_widget_params_are_validated(client: AsyncClient, admin: str) -> None:
    for code, params in (
        ("GS_TREND", {"weeks": "2"}),
        ("GS_TREND", {"weeks": "abc"}),
        ("CN_ISSUED", {"months": "13"}),
        ("GS_PIPELINE", {"unexpected": "1"}),
    ):
        res = await client.get(f"{API}/dashboard/widgets/{code}", headers=_h(admin), params=params)
        assert res.status_code == 422, (code, params)
        assert res.json()["error"]["code"] == "INVALID_WIDGET_PARAMS"
    res = await client.get(f"{API}/dashboard/widgets/NOPE", headers=_h(admin))
    assert res.status_code == 404
    cn = await _widget(client, admin, "CN_ISSUED", months=3)
    assert cn["months"] == 3
    assert [t["code"] for t in cn["types"]] == ["GST_CN", "GENERAL_CN", "JV_ONLY"]
    assert cn["types"][0]["label"] == "GST CREDIT NOTE"  # label from the CN_TYPE option set


# --- admin layout CRUD -------------------------------------------------------------------------
async def test_admin_layout_crud_writes_config_change_log(
    client: AsyncClient, db_conn: Connection, admin: str, users: UserFactory, make_token: JwtFactory
) -> None:
    catalogue = await _get(client, admin, "/admin/dashboard-widgets")
    assert {w["code"] for w in catalogue} == set(REGISTRY)
    trend = next(w for w in catalogue if w["code"] == "GS_TREND")
    assert trend["requires"] == [{"module": "goods_slips", "action": "view"}]
    assert "weeks" in trend["params_schema"]["properties"]

    current = await _get(client, admin, "/admin/dashboard-layouts/TECHNICIAN")
    assert [w["code"] for w in current["widgets"]] == ["MY_TASKS", "TECHNICIAN_WIP"]

    body = {
        "widgets": [
            {"code": "TECHNICIAN_WIP", "size": "L"},
            {"code": "MY_TASKS", "size": "S"},
            {"code": "CN_ISSUED", "size": "M"},
        ],
        "reason": "Technicians start with their batches",
    }
    res = await client.put(
        f"{API}/admin/dashboard-layouts/TECHNICIAN", json=body, headers=_h(admin)
    )
    assert res.status_code == 200, res.text
    saved = res.json()
    assert [w["code"] for w in saved["widgets"]] == ["TECHNICIAN_WIP", "MY_TASKS", "CN_ISSUED"]
    cn = saved["widgets"][2]
    assert cn["allowed_for_role"] is False
    assert cn["missing"] == [{"module": "credit_notes", "action": "view"}]

    log = fetch_all(
        db_conn,
        """select action, before, after, reason from public.config_change_log
            where entity_type = 'role_dashboard_layout' and entity_id = 'TECHNICIAN'
            order by id desc limit 1""",
    )[0]
    assert log["action"] == "UPDATE"
    assert [w["code"] for w in log["before"]] == ["MY_TASKS", "TECHNICIAN_WIP"]
    assert [w["code"] for w in log["after"]] == ["TECHNICIAN_WIP", "MY_TASKS", "CN_ISSUED"]
    assert log["reason"] == "Technicians start with their batches"

    # A technician sees the new order, without the widget their permissions do not allow.
    tech = make_token(users.create(roles=["TECHNICIAN"]))
    landing = await _get(client, tech, "/dashboard")
    assert [w["code"] for w in landing["widgets"]] == ["TECHNICIAN_WIP", "MY_TASKS"]
    assert landing["widgets"][0]["size"] == "L"
    assert landing["hidden_widget_count"] == 1

    for bad, code in (
        ({"widgets": [{"code": "NOPE", "size": "S"}]}, "UNKNOWN_WIDGET"),
        (
            {"widgets": [{"code": "MY_TASKS", "size": "S"}, {"code": "MY_TASKS", "size": "M"}]},
            "DUPLICATE_WIDGET",
        ),
    ):
        res = await client.put(
            f"{API}/admin/dashboard-layouts/TECHNICIAN", json=bad, headers=_h(admin)
        )
        assert res.status_code == 422, res.text
        assert res.json()["error"]["code"] == code
    res = await client.put(
        f"{API}/admin/dashboard-layouts/TECHNICIAN",
        json={"widgets": [{"code": "MY_TASKS", "size": "XL"}]},
        headers=_h(admin),
    )
    assert res.status_code == 422
    res = await client.put(
        f"{API}/admin/dashboard-layouts/NO_SUCH_ROLE", json=body, headers=_h(admin)
    )
    assert res.status_code == 404

    res = await client.delete(
        f"{API}/admin/dashboard-layouts/TECHNICIAN", headers=_h(admin), params={"reason": "reset"}
    )
    assert res.status_code == 204
    gone = await _get(client, admin, "/admin/dashboard-layouts/TECHNICIAN")
    assert gone["has_layout"] is False and gone["widgets"] == []
    empty = await _get(client, tech, "/dashboard")
    assert empty["widgets"] == [] and empty["role"]["code"] == "TECHNICIAN"
    actions = [
        r["action"]
        for r in fetch_all(
            db_conn,
            """select action from public.config_change_log
                where entity_type = 'role_dashboard_layout' and entity_id = 'TECHNICIAN'
                order by id desc limit 2""",
        )
    ]
    assert actions == ["DELETE", "UPDATE"]

    all_layouts = await _get(client, admin, "/admin/dashboard-layouts")
    assert {r["role"]["code"] for r in all_layouts} >= set(ALL_ROLES)


async def test_layout_admin_requires_configure(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    token = make_token(users.create(roles=["REPLACEMENT_MANAGER"]))
    for method, path in (
        ("GET", "/admin/dashboard-widgets"),
        ("GET", "/admin/dashboard-layouts"),
        ("PUT", "/admin/dashboard-layouts/TECHNICIAN"),
        ("DELETE", "/admin/dashboard-layouts/TECHNICIAN"),
    ):
        res = await client.request(
            method,
            f"{API}{path}",
            headers=_h(token),
            json={"widgets": []} if method == "PUT" else None,
        )
        assert res.status_code == 403, (method, path)


# --- admin health: guard violations, jobs, logins, config changes ------------------------------
async def test_admin_health_counts_guard_attempts_and_failed_jobs(
    client: AsyncClient, db_conn: Connection, admin: str, users: UserFactory, make_token: JwtFactory
) -> None:
    before = await _widget(client, admin, "ADMIN_HEALTH")

    # A service-level guard (G-16) and a DB-trigger guard (G-18), each rejected and recorded.
    actor = users.create(roles=["TECHNICIAN"])
    token = make_token(actor)
    res = await client.post(f"{API}/test/guard/g16", headers=_h(token))
    assert res.status_code == 409 and res.json()["error"]["code"] == "G-16"
    version_id = publish_workflow(db_conn, step_code="S1_GATE", role_code="GATE_INWARD")
    res = await client.post(f"{API}/test/guard/g18/{version_id}", headers=_h(token))
    assert res.status_code == 409 and res.json()["error"]["code"] == "G-18"

    events = fetch_all(
        db_conn,
        "select guard_code, source, user_id, path from public.system_guard_events "
        "where user_id = :u order by id",
        u=actor,
    )
    assert [(e["guard_code"], e["source"]) for e in events] == [("G-16", "SERVICE"), ("G-18", "DB")]
    assert events[0]["path"] == f"{API}/test/guard/g16"

    as_admin(db_conn).execute(
        text(
            """insert into public.job_runs (job_code, status, started_at, error_message)
               values ('inventory_segregation_check', 'FAILED',
                       now() - interval '1 minute', 'boom')"""
        )
    )
    clear_widget_cache()
    after = await _widget(client, admin, "ADMIN_HEALTH")
    assert after["guard_violations"] == before["guard_violations"] + 2
    by_code = {g["guard_code"]: g["count"] for g in after["guard_violations_by_code"]}
    assert by_code["G-16"] >= 1 and by_code["G-18"] >= 1
    assert after["failed_jobs"] == before["failed_jobs"] + 1
    assert after["last_failed_job"] == "inventory_segregation_check"
    assert after["users_active"] >= before["users_active"]
    assert after["window_days"] == 7
    assert after["logins"] >= 0 and after["users_logged_in"] <= after["logins"]


async def test_guard_logs_are_append_only(db_conn: Connection) -> None:
    conn = db_conn
    conn.execute(text("set local role rms_api"))
    for table in ("system_guard_events", "job_runs"):
        with pytest.raises(Exception, match="permission denied"), conn.begin_nested():
            conn.execute(text(f"delete from public.{table}"))  # noqa: S608 - fixed table names
    as_admin(conn)


def test_container_compliance_window_is_configurable(db_conn: Connection) -> None:
    row = fetch_all(
        db_conn,
        "select value from public.system_settings where key = 'container_audit_compliance_days'",
    )
    assert row and row[0]["value"] == 30
    assert timedelta(days=row[0]["value"]).days == 30
