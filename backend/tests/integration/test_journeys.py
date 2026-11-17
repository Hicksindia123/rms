"""Integration tests for change plan 2026-11-12 Phase 10 (AMD-22, DEC-49; AMD-21 / DEC-44).

1. Each role sees only its own menu, in journey order (STEPs first, then TOOLs), from DB config.
2. My Work counts per step and the next GS (the one waiting longest) per queue.
3. Entries are filtered by the user's effective permissions and by `features.on_hold`.
4. The step queue endpoint only serves steps on the caller's menu.
5. Admin: reorder a role's journey and relabel a step (config change log); codes are immutable.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, fetch_all, force_gs_status
from tests.integration.test_gate_inward import Masters, _auth, _create, _values


@pytest.fixture
def masters(db_conn: Connection) -> Masters:
    return Masters(db_conn)


async def _journey(client: AsyncClient, token: str) -> dict[str, Any]:
    res = await client.get("/api/v1/me/journey", headers=_auth(token))
    assert res.status_code == 200, res.text
    body: dict[str, Any] = res.json()
    return body


def _codes(body: dict[str, Any]) -> list[str]:
    return [e["code"] for e in body["entries"]]


def _entry(body: dict[str, Any], code: str) -> dict[str, Any]:
    return next(e for e in body["entries"] if e["code"] == code)


async def _new_gs(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, masters: Masters
) -> str:
    gate = make_token(users.create(roles=["GATE_INWARD"]))
    res = await _create(client, gate, masters, _values())
    assert res.status_code == 201, res.text
    gs_id: str = res.json()["goods_slip"]["id"]
    return gs_id


# --- 1. role menus in journey order (AMD-22) -----------------------------------------------------


async def test_gate_user_sees_only_the_gate_journey(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    body = await _journey(client, make_token(users.create(roles=["GATE_INWARD"])))
    assert _codes(body) == ["GATE_ENTRY", "GS_LIST"]
    gate = _entry(body, "GATE_ENTRY")
    assert gate["kind"] == "STEP" and gate["screen_key"] == "gs-new"
    assert gate["count"] is None  # a start step has no queue


async def test_inward_verifier_journey_order_steps_then_tools(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    body = await _journey(client, make_token(users.create(roles=["INWARD_VERIFIER"])))
    assert _codes(body) == [
        "CARTON_OPENING",
        "COUNTING",  # DEC-53: Counting & Categorisation, one entry
        "INSPECTION",
        "DEPT_RECEIVING",
        "CONTAINER_AUDIT",
        "GS_LIST",
        "REPORTS",
    ]
    assert all(isinstance(e["count"], int) for e in body["entries"] if e["kind"] == "STEP")


async def test_menu_follows_db_config_not_code(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    """Reordering role_journey_steps reorders the menu (rule e: config, not hard-code)."""
    as_admin(db_conn).execute(
        text(
            """update public.role_journey_steps rjs set sort_order = 1
                 from public.roles r, public.journey_steps s
                where r.id = rjs.role_id and s.id = rjs.journey_step_id
                  and r.code = 'INWARD_VERIFIER' and s.code = 'INSPECTION'"""
        )
    )
    body = await _journey(client, make_token(users.create(roles=["INWARD_VERIFIER"])))
    assert _codes(body)[:3] == ["INSPECTION", "CARTON_OPENING", "COUNTING"]


async def test_multi_role_user_gets_the_union_without_duplicates(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    uid = users.create(roles=["GATE_INWARD", "INWARD_VERIFIER"])
    codes = _codes(await _journey(client, make_token(uid)))
    assert len(codes) == len(set(codes))
    assert {"GATE_ENTRY", "CARTON_OPENING", "GS_LIST"} <= set(codes)
    assert codes.index("CARTON_OPENING") < codes.index("GS_LIST")  # steps before tools


# --- 2. counts and the next GS -------------------------------------------------------------------


async def test_counts_and_next_gs_follow_the_gs_through_the_steps(
    client: AsyncClient,
    users: UserFactory,
    make_token: JwtFactory,
    masters: Masters,
    db_conn: Connection,
) -> None:
    iv = make_token(users.create(roles=["INWARD_VERIFIER"]))
    before = await _journey(client, iv)
    gs_id = await _new_gs(client, users, make_token, masters)

    after = await _journey(client, iv)
    assert _entry(after, "CARTON_OPENING")["count"] == _entry(before, "CARTON_OPENING")["count"] + 1
    queue = (await client.get("/api/v1/me/journey/CARTON_OPENING", headers=_auth(iv))).json()
    assert gs_id in [i["gs_id"] for i in queue["items"]]
    assert queue["item_screen_key"] == "gs-unboxing"
    item = next(i for i in queue["items"] if i["gs_id"] == gs_id)
    assert item["target_id"] == gs_id and item["since"] is not None

    # DEC-53: a slip sent back to CATEGORISATION is listed under Counting & Categorisation.
    force_gs_status(db_conn, gs_id, "CATEGORISATION")
    moved = await _journey(client, iv)
    assert _entry(moved, "CARTON_OPENING")["count"] == _entry(before, "CARTON_OPENING")["count"]
    assert _entry(moved, "COUNTING")["count"] == _entry(before, "COUNTING")["count"] + 1
    cat = (await client.get("/api/v1/me/journey/COUNTING", headers=_auth(iv))).json()
    assert gs_id in [i["gs_id"] for i in cat["items"]]


async def test_next_gs_is_the_one_waiting_longest(
    client: AsyncClient,
    users: UserFactory,
    make_token: JwtFactory,
    masters: Masters,
    db_conn: Connection,
) -> None:
    first = await _new_gs(client, users, make_token, masters)
    second = await _new_gs(client, users, make_token, masters)
    for gs_id, ago in ((first, "3 days"), (second, "1 day")):
        force_gs_status(db_conn, gs_id, "ITEMIZATION")
        as_admin(db_conn).execute(
            text(
                """insert into public.gs_status_history
                          (gs_id, from_status, to_status, step_code, "at")
                   values (:g, 'UNBOXING', 'ITEMIZATION', 'S1_UNBOX',
                           now() - cast(:ago as interval))"""
            ),
            {"g": gs_id, "ago": ago},
        )
    iv = make_token(users.create(roles=["INWARD_VERIFIER"]))
    queue = (await client.get("/api/v1/me/journey/COUNTING", headers=_auth(iv))).json()
    ids = [i["gs_id"] for i in queue["items"]]
    assert ids.index(first) < ids.index(second)
    nxt = _entry(await _journey(client, iv), "COUNTING")["next"]
    if queue["items"][0]["gs_id"] == first:  # nothing older waiting in this database
        assert nxt["gs_id"] == first


# --- 3. permissions and the feature hold (AMD-21, DEC-44) ----------------------------------------


async def test_on_hold_modules_are_hidden_until_released(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    spm = make_token(users.create(roles=["SPARE_PARTS_MANAGER"]))
    body = await _journey(client, spm)
    assert "INVENTORY" in _codes(body)
    assert not {"DISMANTLING", "SCRAP", "BATTERIES"} & set(_codes(body))
    assert {"dismantling", "battery"} <= set(body["hidden_features"])

    as_admin(db_conn).execute(
        text(
            "update public.system_settings set value = cast(:v as jsonb)"
            " where key = 'features.on_hold'"
        ),
        {"v": json.dumps([])},
    )
    released = await _journey(client, spm)
    assert {"DISMANTLING", "SCRAP", "BATTERIES"} <= set(_codes(released))
    assert released["hidden_features"] == []


async def test_entry_needs_its_permission_even_when_assigned(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    """GATE_INWARD has no audit.view: an AUDIT entry assigned by config is still not shown."""
    as_admin(db_conn).execute(
        text(
            """insert into public.role_journey_steps (role_id, journey_step_id, sort_order)
               select r.id, s.id, 500 from public.roles r, public.journey_steps s
                where r.code = 'GATE_INWARD' and s.code = 'AUDIT'"""
        )
    )
    body = await _journey(client, make_token(users.create(roles=["GATE_INWARD"])))
    assert "AUDIT" not in _codes(body)


async def test_queue_of_a_step_not_on_the_menu_is_404(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    gate = make_token(users.create(roles=["GATE_INWARD"]))
    res = await client.get("/api/v1/me/journey/COUNTING", headers=_auth(gate))
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "JOURNEY_STEP_NOT_FOUND"
    unauth = await client.get("/api/v1/me/journey")
    assert unauth.status_code == 401


async def test_super_admin_sees_the_active_catalogue_except_on_hold(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    as_admin(db_conn).execute(
        text("update public.journey_steps set is_active = false where code = 'PENDENCIES'")
    )
    body = await _journey(client, make_token(users.create(super_admin=True)))
    codes = _codes(body)
    assert codes[0] == "GATE_ENTRY" and "PARTY_EMAIL" in codes
    assert "PENDENCIES" not in codes and "DISMANTLING" not in codes
    kinds = [e["kind"] for e in body["entries"]]
    assert kinds == sorted(kinds, key=lambda k: k == "TOOL")


# --- 4. admin configuration ----------------------------------------------------------------------


async def test_admin_reorders_a_role_journey_and_it_is_logged(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    admin = make_token(users.create(super_admin=True))
    cfg = await client.get("/api/v1/config/journeys", headers=_auth(admin))
    assert cfg.status_code == 200, cfg.text
    roles = {r["role_code"]: r["step_codes"] for r in cfg.json()["roles"]}
    assert roles["GATE_INWARD"] == ["GATE_ENTRY", "GS_LIST"]
    assert "SUPER_ADMIN" not in roles

    res = await client.put(
        "/api/v1/config/journeys/roles/GATE_INWARD",
        json={"step_codes": ["GS_LIST", "GATE_ENTRY", "REPORTS"], "reason": "test reorder"},
        headers=_auth(admin),
    )
    assert res.status_code == 200, res.text
    gate = make_token(users.create(roles=["GATE_INWARD"]))
    # REPORTS is assigned but GATE_INWARD has no reports.view: still hidden.
    assert _codes(await _journey(client, gate)) == ["GATE_ENTRY", "GS_LIST"]
    log = fetch_all(
        db_conn,
        """select before, after from public.config_change_log
            where entity_type = 'role_journey' and entity_id = 'GATE_INWARD'
            order by changed_at desc limit 1""",
    )
    assert log[0]["before"]["step_codes"] == ["GATE_ENTRY", "GS_LIST"]
    assert log[0]["after"]["step_codes"] == ["GS_LIST", "GATE_ENTRY", "REPORTS"]


async def test_admin_journey_update_rejects_bad_input_and_non_admins(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    admin = make_token(users.create(super_admin=True))
    url = "/api/v1/config/journeys/roles/GATE_INWARD"
    dup = await client.put(
        url, json={"step_codes": ["GS_LIST", "GS_LIST"], "reason": "dup"}, headers=_auth(admin)
    )
    assert dup.status_code == 422 and dup.json()["error"]["code"] == "DUPLICATE_STEP"
    unknown = await client.put(
        url, json={"step_codes": ["NOT_A_STEP"], "reason": "bad"}, headers=_auth(admin)
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "UNKNOWN_JOURNEY_STEP"
    missing_role = await client.put(
        "/api/v1/config/journeys/roles/NO_SUCH_ROLE",
        json={"step_codes": [], "reason": "bad role"},
        headers=_auth(admin),
    )
    assert missing_role.status_code == 404
    gate = make_token(users.create(roles=["GATE_INWARD"]))
    denied = await client.put(
        url, json={"step_codes": [], "reason": "not allowed"}, headers=_auth(gate)
    )
    assert denied.status_code == 403
    assert (await client.get("/api/v1/config/journeys", headers=_auth(gate))).status_code == 403


async def test_admin_relabels_a_step_and_codes_stay_immutable(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    admin = make_token(users.create(super_admin=True))
    res = await client.put(
        "/api/v1/config/journeys/steps/CARTON_OPENING",
        json={"label": "Open Cartons", "hint": "Video per carton", "reason": "rename"},
        headers=_auth(admin),
    )
    assert res.status_code == 200, res.text
    assert res.json()["label"] == "Open Cartons"
    iv = make_token(users.create(roles=["INWARD_VERIFIER"]))
    assert _entry(await _journey(client, iv), "CARTON_OPENING")["label"] == "Open Cartons"

    conn = as_admin(db_conn)
    conn.execute(text("savepoint s"))
    with pytest.raises(DBAPIError, match="immutable"):
        conn.execute(
            text(
                "update public.journey_steps set code = 'OPEN_CARTONS'"
                " where code = 'CARTON_OPENING'"
            )
        )
    conn.execute(text("rollback to savepoint s"))


async def test_catalogue_rejects_unknown_screens_and_queues(db_conn: Connection) -> None:
    """Configuration can never point the menu at a screen or counter that does not exist."""
    conn = as_admin(db_conn)
    for screen, queue in (("no-such-screen", None), ("journey-queue", "NO_SUCH_QUEUE")):
        conn.execute(text("savepoint s"))
        with pytest.raises(DBAPIError):
            conn.execute(
                text(
                    """insert into public.journey_steps
                         (code, label, kind, screen_key, item_screen_key, queue_code, perm_module)
                       values (:c, 'X', 'STEP', :sc, 'gs-detail', :q, 'goods_slips')"""
                ),
                {"c": f"T_{uuid.uuid4().hex[:8].upper()}", "sc": screen, "q": queue},
            )
        conn.execute(text("rollback to savepoint s"))
