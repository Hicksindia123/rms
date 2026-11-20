"""Phase P1 (docs/RMS_PHASE_PROMPTS_20-11-2026.md): Intermediate Stores, DEC-60 / DEC-61.

1. Admin list: seeded OP / DT / RI, own role + location, users holding each store role.
2. Permissions: writes need intermediate_stores.create / edit / configure (Super Admin); MANAGEMENT
   reads only; other roles get 403.
3. Create a store = role + FUNCTIONAL location + store in one transaction; the role copies the
   default store's grants and menu. Duplicate code / name rejected.
4. Rename (role + location follow), default store rules (exactly one, cannot be deactivated).
5. Category mapping: tree, conflicts, reassign.
6. GET /intermediate-stores/mine: store role -> that store; MANAGEMENT -> all; others -> none.
7. Guard STORE_MAPPING_MISSING (service + DB) when no store resolves.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import UowDep, get_session_factory
from app.core.errors import Conflict
from app.core.security import CurrentUserDep
from app.modules.intermediate_stores import repository as store_repo
from app.modules.intermediate_stores.service import require_stores_for_products
from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, build_test_app

API = "/api/v1"
ADMIN = f"{API}/admin/intermediate-stores"


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _stores(client: AsyncClient, token: str) -> dict[str, dict[str, Any]]:
    res = await client.get(ADMIN, headers=_h(token))
    assert res.status_code == 200, res.text
    return {s["code"]: s for s in res.json()}


def _category_id(conn: Connection, code: str) -> str:
    return str(
        as_admin(conn)
        .execute(text("select id from public.product_categories where code = :c"), {"c": code})
        .scalar_one()
    )


# --- 1. list ------------------------------------------------------------------------------------


async def test_admin_lists_seeded_stores_with_role_location_and_users(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    admin = make_token(users.create(super_admin=True))
    dt_user = users.create(roles=["ISTORE_DT"], full_name="DT Store User")
    stores = await _stores(client, admin)
    assert [c for c in stores if c in {"OP", "DT", "RI"}] == ["OP", "DT", "RI"]
    assert stores["RI"]["is_default"] is True
    assert [s["code"] for s in stores.values() if s["is_default"]] == ["RI"]
    assert stores["DT"]["role"]["code"] == "ISTORE_DT"
    assert stores["DT"]["location"]["code"] == "ISTORE_DT"
    assert stores["OP"]["category_count"] == 2
    assert str(dt_user) in {u["id"] for u in stores["DT"]["users"]}
    assert str(dt_user) not in {u["id"] for u in stores["OP"]["users"]}


# --- 2. permissions -----------------------------------------------------------------------------


async def test_management_reads_but_cannot_write_and_others_are_denied(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    mgmt = make_token(users.create(roles=["MANAGEMENT"]))
    gate = make_token(users.create(roles=["GATE_INWARD"]))
    stores = await _stores(client, mgmt)
    dt = stores["DT"]["id"]

    assert (await client.get(f"{ADMIN}/{dt}/mapping", headers=_h(mgmt))).status_code == 200
    denied = [
        await client.post(ADMIN, json={"code": "QQ", "name": "Q store"}, headers=_h(mgmt)),
        await client.patch(f"{ADMIN}/{dt}", json={"name": "X"}, headers=_h(mgmt)),
        await client.put(f"{ADMIN}/{dt}/mapping", json={}, headers=_h(mgmt)),
        await client.get(ADMIN, headers=_h(gate)),
        await client.get(f"{ADMIN}/{dt}/mapping", headers=_h(gate)),
    ]
    assert [r.status_code for r in denied] == [403] * 5
    assert denied[0].json()["error"]["code"] == "PERMISSION_DENIED"


# --- 3. create ----------------------------------------------------------------------------------


async def test_create_store_creates_role_and_location_copying_the_default_role(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    admin = make_token(users.create(super_admin=True))
    res = await client.post(
        ADMIN,
        json={"code": "xy", "name": "  Intermediate   Store XY ", "sort_order": 40},
        headers=_h(admin),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["code"] == "XY"
    assert body["name"] == "Intermediate Store XY"
    assert body["is_default"] is False
    assert body["role"]["code"] == "ISTORE_XY"
    assert body["location"]["code"] == "ISTORE_XY"

    conn = as_admin(db_conn)
    loc = conn.execute(
        text(
            "select l.location_class, r.code from public.inventory_locations l"
            " join public.roles r on r.id = l.custodian_role_id where l.code = 'ISTORE_XY'"
        )
    ).one()
    assert tuple(loc) == ("FUNCTIONAL", "ISTORE_XY")

    def grants(role: str) -> set[tuple[str, str]]:
        rows = conn.execute(
            text(
                "select p.module_code, p.action from public.role_permissions rp"
                " join public.permissions p on p.id = rp.permission_id"
                " join public.roles r on r.id = rp.role_id where r.code = :r"
            ),
            {"r": role},
        ).all()
        return {(m, a) for m, a in rows}

    assert grants("ISTORE_XY") == grants("ISTORE_RI")
    assert grants("ISTORE_XY")  # the template role is not empty
    log = conn.execute(
        text(
            "select count(*) from public.config_change_log"
            " where entity_type = 'intermediate_store' and action = 'INTERMEDIATE_STORE_CREATED'"
            " and entity_id = :id"
        ),
        {"id": body["id"]},
    ).scalar_one()
    assert log == 1

    dup_code = await client.post(ADMIN, json={"code": "XY", "name": "Other"}, headers=_h(admin))
    assert dup_code.status_code == 409
    assert dup_code.json()["error"]["code"] == "STORE_CODE_TAKEN"
    dup_name = await client.post(
        ADMIN, json={"code": "XZ", "name": "intermediate store xy"}, headers=_h(admin)
    )
    assert dup_name.status_code == 409
    assert dup_name.json()["error"]["code"] == "STORE_NAME_TAKEN"
    bad = await client.post(ADMIN, json={"code": "1-bad", "name": "Bad"}, headers=_h(admin))
    assert bad.status_code == 422


# --- 4. rename + default rules ------------------------------------------------------------------


async def test_rename_follows_role_and_location_and_default_rules(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    admin = make_token(users.create(super_admin=True))
    stores = await _stores(client, admin)
    op, dt, ri = stores["OP"]["id"], stores["DT"]["id"], stores["RI"]["id"]

    renamed = await client.patch(
        f"{ADMIN}/{op}", json={"name": "OP Store (Ovals)", "reason": "UAT"}, headers=_h(admin)
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["role"]["name"] == "OP Store (Ovals)"
    assert renamed.json()["location"]["name"] == "OP Store (Ovals)"
    assert renamed.json()["code"] == "OP"

    off = await client.patch(f"{ADMIN}/{ri}", json={"is_active": False}, headers=_h(admin))
    assert off.status_code == 409
    assert off.json()["error"]["code"] == "STORE_IS_DEFAULT"
    unset = await client.patch(f"{ADMIN}/{ri}", json={"is_default": False}, headers=_h(admin))
    assert unset.status_code == 422
    assert unset.json()["error"]["code"] == "STORE_DEFAULT_REQUIRED"

    moved = await client.patch(f"{ADMIN}/{dt}", json={"is_default": True}, headers=_h(admin))
    assert moved.status_code == 200, moved.text
    after = await _stores(client, admin)
    assert [c for c, s in after.items() if s["is_default"]] == ["DT"]
    # RI is no longer the default, so it can now be deactivated.
    ri_off = await client.patch(f"{ADMIN}/{ri}", json={"is_active": False}, headers=_h(admin))
    assert ri_off.status_code == 200
    assert ri_off.json()["is_active"] is False
    # An inactive store cannot become the default.
    back = await client.patch(f"{ADMIN}/{ri}", json={"is_default": True}, headers=_h(admin))
    assert back.status_code == 409
    assert back.json()["error"]["code"] == "STORE_IS_DEFAULT"


# --- 5. mapping -----------------------------------------------------------------------------------


async def test_mapping_tree_conflicts_and_reassign(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory, db_conn: Connection
) -> None:
    admin = make_token(users.create(super_admin=True))
    stores = await _stores(client, admin)
    dt, op = stores["DT"]["id"], stores["OP"]["id"]
    dmt, prismatic = _category_id(db_conn, "DMT"), _category_id(db_conn, "PRISMATIC")

    got = await client.get(f"{ADMIN}/{dt}/mapping", headers=_h(admin))
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["category_ids"] == [dmt]
    assert body["default_store"]["code"] == "RI"
    by_code = {c["code"]: c for c in body["tree"]}
    assert by_code["PRISMATIC"]["store"]["code"] == "OP"
    assert by_code["DMT"]["store"]["code"] == "DT"

    clash = await client.put(
        f"{ADMIN}/{dt}/mapping",
        json={"category_ids": [dmt, prismatic]},
        headers=_h(admin),
    )
    assert clash.status_code == 409
    err = clash.json()["error"]
    assert err["code"] == "STORE_MAPPING_CONFLICT"
    assert [(c["code"], c["store_code"]) for c in err["details"]["conflicts"]] == [
        ("PRISMATIC", "OP")
    ]

    moved = await client.put(
        f"{ADMIN}/{dt}/mapping",
        json={"category_ids": [dmt, prismatic], "reassign": True, "reason": "UAT move"},
        headers=_h(admin),
    )
    assert moved.status_code == 200, moved.text
    assert sorted(moved.json()["category_ids"]) == sorted([dmt, prismatic])
    op_map = (await client.get(f"{ADMIN}/{op}/mapping", headers=_h(admin))).json()
    assert prismatic not in op_map["category_ids"]

    unknown = await client.put(
        f"{ADMIN}/{dt}/mapping", json={"category_ids": [str(uuid.uuid4())]}, headers=_h(admin)
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "UNKNOWN_CATEGORY"

    cleared = await client.put(f"{ADMIN}/{dt}/mapping", json={}, headers=_h(admin))
    assert cleared.status_code == 200
    assert cleared.json()["category_ids"] == []


# --- 6. mine ------------------------------------------------------------------------------------


async def test_mine_returns_the_stores_of_the_user(
    client: AsyncClient, users: UserFactory, make_token: JwtFactory
) -> None:
    async def mine(token: str) -> list[str]:
        res = await client.get(f"{API}/intermediate-stores/mine", headers=_h(token))
        assert res.status_code == 200, res.text
        return [s["code"] for s in res.json()]

    seeded = {"OP", "DT", "RI"}
    assert await mine(make_token(users.create(roles=["ISTORE_DT"]))) == ["DT"]
    assert seeded <= set(await mine(make_token(users.create(roles=["MANAGEMENT"]))))
    assert seeded <= set(await mine(make_token(users.create(super_admin=True))))
    assert await mine(make_token(users.create(roles=["GATE_INWARD"]))) == []
    assert await mine(make_token(users.create(roles=["MANAGEMENT_VIEWER"]))) == []


# --- 7. guard STORE_MAPPING_MISSING ------------------------------------------------------------


def _products(conn: Connection) -> dict[str, uuid.UUID]:
    rows = (
        as_admin(conn)
        .execute(
            text(
                """
            select distinct on (c.code) c.code, p.id
              from public.products p join public.product_categories c on c.id = p.category_id
             where c.code in ('DMT', 'GENERAL') and p.is_active
             order by c.code, p.code
            """
            )
        )
        .all()
    )
    found = {code: pid for code, pid in rows}
    assert set(found) == {"DMT", "GENERAL"}, "seed needs a DMT and a GENERAL product"
    return found


def _drop_default_store(conn: Connection) -> None:
    """Force the state the DB normally forbids (no default store), triggers off."""
    conn = as_admin(conn)
    conn.execute(text("set local session_replication_role = replica"))
    conn.execute(text("update public.intermediate_stores set is_default = false"))
    conn.execute(text("set local session_replication_role = origin"))


def test_require_stores_for_products_resolves_and_rejects(
    db_conn: Connection, session_factory: sessionmaker[Session]
) -> None:
    products = _products(db_conn)
    with session_factory() as session, session.begin():
        stores = require_stores_for_products(session, list(products.values()))
        codes = dict(
            session.execute(text("select id, code from public.intermediate_stores")).all()
        )
        assert codes[stores[products["DMT"]]] == "DT"
        assert codes[stores[products["GENERAL"]]] == "RI"

    # GENERAL is mapped to RI, so only an unmapped category loses its store without a default.
    as_admin(db_conn).execute(
        text(
            "delete from public.intermediate_store_category_map"
            " where category_id = (select id from public.product_categories where code = 'GENERAL')"
        )
    )
    _drop_default_store(db_conn)
    with session_factory() as session, session.begin():
        with pytest.raises(Conflict) as exc:
            require_stores_for_products(session, list(products.values()))
        assert exc.value.code == "STORE_MAPPING_MISSING"
        assert exc.value.details is not None
        assert exc.value.details["product_codes"] == [
            as_admin(db_conn)
            .execute(
                text("select code from public.products where id = :id"), {"id": products["GENERAL"]}
            )
            .scalar_one()
        ]
        # A mapped product still resolves.
        assert products["DMT"] in require_stores_for_products(session, [products["DMT"]])


async def test_db_guard_store_mapping_missing_returns_409(
    db_conn: Connection,
    session_factory: sessionmaker[Session],
    users: UserFactory,
    make_token: JwtFactory,
) -> None:
    products = _products(db_conn)
    app = build_test_app()

    @app.post("/api/v1/test/p1/assert-store/{product_id}")
    def probe(product_id: uuid.UUID, user: CurrentUserDep, uow: UowDep) -> dict[str, bool]:
        # The DB guard alone (no service check), as a P5 transfer-slip transaction would hit it.
        with uow.transaction(user.id) as session:
            store_repo.assert_store_for_products(session, [product_id])
        return {"ok": True}

    app.dependency_overrides[get_session_factory] = lambda: session_factory
    token = make_token(users.create(roles=["GATE_INWARD"]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ok = await c.post(f"{API}/test/p1/assert-store/{products['GENERAL']}", headers=_h(token))
        assert ok.status_code == 200, ok.text

        as_admin(db_conn).execute(
            text(
                "delete from public.intermediate_store_category_map where category_id ="
                " (select id from public.product_categories where code = 'GENERAL')"
            )
        )
        _drop_default_store(db_conn)
        res = await c.post(f"{API}/test/p1/assert-store/{products['GENERAL']}", headers=_h(token))
    assert res.status_code == 409, res.text
    err = res.json()["error"]
    assert err["code"] == "STORE_MAPPING_MISSING"
    assert err["request_id"]
