"""Fixtures for the P3-08 Phase 3 gate suites (rolled-back transaction per test)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import get_session_factory
from app.core.middleware import limiter
from app.shared.storage import get_storage
from tests.conftest import JwtFactory
from tests.integration.conftest import UserFactory, as_admin, build_test_app
from tests.integration.test_unboxing import FakeStorage


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
async def client(
    session_factory: sessionmaker[Session], storage: FakeStorage
) -> AsyncIterator[AsyncClient]:
    app = build_test_app()
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_storage] = lambda: storage
    limiter.reset()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    limiter.reset()


@dataclass
class Gate:
    """A Super Admin (every bypass attempt) and the role holders of Phase 3."""

    admin_id: uuid.UUID
    admin: str
    rm_id: uuid.UUID
    rm: str
    accounts: str
    sahil_id: uuid.UUID
    sahil: str
    spm: str
    spt: str
    tech_id: uuid.UUID


@pytest.fixture
def gate(users: UserFactory, make_token: JwtFactory) -> Gate:
    admin = users.create(super_admin=True, full_name="P308 Super Admin")
    rm = users.create(roles=["REPLACEMENT_MANAGER"], full_name="P308 RM")
    acc = users.create(roles=["ACCOUNTS"], full_name="P308 Accounts")
    sahil = users.create(
        roles=["INTERMEDIATE_STORE_MANAGER", "TECHNICIAN_COORDINATOR"], full_name="P308 Sahil"
    )
    spm = users.create(roles=["SPARE_PARTS_MANAGER"], full_name="P308 SPM")
    spt = users.create(roles=["SPARE_PARTS_TECHNICIAN"], full_name="P308 SPT")
    # The technician master (DEC-34): the seeded technician the coordinators allot to.
    tech = (
        as_admin(users.conn)
        .execute(
            text("select id from public.technicians where is_active order by display_name limit 1")
        )
        .scalar_one()
    )
    return Gate(
        admin_id=admin,
        admin=make_token(admin),
        rm_id=rm,
        rm=make_token(rm),
        accounts=make_token(acc),
        sahil_id=sahil,
        sahil=make_token(sahil),
        spm=make_token(spm),
        spt=make_token(spt),
        tech_id=tech,
    )


def auth(token: str, idem: bool = False) -> dict[str, str]:
    h = {"Authorization": f"Bearer {token}"}
    if idem:
        h["Idempotency-Key"] = f"p308-{uuid.uuid4().hex}"
    return h


def loc(conn: Connection, code: str) -> uuid.UUID:
    return uuid.UUID(
        str(
            as_admin(conn)
            .execute(text("select id from public.inventory_locations where code = :c"), {"c": code})
            .scalar_one()
        )
    )


def seed_lot(
    conn: Connection,
    *,
    location: str,
    condition_class: str,
    qty: int,
    category: str = "DMT",
    source_condition: str | None = None,
    with_gs: bool = True,
    item_kind: str = "FINISHED_GOOD",
) -> dict[str, Any]:
    """A GS line + lot holding `qty` in `location`, credited through the locked ledger function."""
    c = as_admin(conn)
    tag = uuid.uuid4().hex[:8].upper()
    product = c.execute(
        text(
            """insert into public.products (code, name, category_id)
               select :code, :name, id from public.product_categories where code = :cat
               returning id, category_id"""
        ),
        {"code": f"P308-{tag}", "name": f"P308 {category} {tag}", "cat": category},
    ).one()
    gs_id = item_id = None
    if with_gs:
        wv = c.execute(
            text(
                "select id from public.workflow_versions where status = 'PUBLISHED' "
                "order by version_no desc limit 1"
            )
        ).scalar_one()
        gs_id = c.execute(
            text(
                """insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code,
                       courier_name, docket_no, box_count, status, category_code,
                       original_category_code)
                   values (:no, :wv, 'COURIER_PARCEL', 'BlueDart', :d, 1, 'ITEMIZATION', 'RO', 'RO')
                   returning id"""
            ),
            {"no": f"GS-P308-{tag}", "wv": wv, "d": f"DKT-{tag}"},
        ).scalar_one()
        item_id = c.execute(
            text(
                """insert into public.gs_items (gs_id, line_no, product_id, category_id,
                       documented_qty, received_qty)
                   values (:g, 1, :p, :c, :q, :q) returning id"""
            ),
            {"g": gs_id, "p": product.id, "c": product.category_id, "q": qty},
        ).scalar_one()
        # Walk the GS through the guarded statuses as tests/test_closure._build_gs does (G-07
        # needs a finalised inspection before RM_REVIEW).
        actor = c.execute(text("select id from public.profiles limit 1")).scalar_one_or_none()
        if not actor:
            actor = uuid.uuid4()
            c.execute(
                text("insert into auth.users (id, email) values (:id, :e) on conflict do nothing"),
                {"id": actor, "e": f"actor_{actor.hex[:6]}@example.com"},
            )
            c.execute(
                text(
                    "insert into public.profiles (id, email, full_name) "
                    "values (:id, :e, 'Actor') on conflict do nothing"
                ),
                {"id": actor, "e": f"actor_{actor.hex[:6]}@example.com"},
            )
        # AMD-08 (change plan Phase 3): the count is submitted (ITEMIZATION -> CATEGORISATION).
        for status in ("CATEGORISATION", "INSPECTION", "RM_REVIEW", "IN_PROCESS"):
            if status == "RM_REVIEW":
                c.execute(
                    text(
                        "insert into public.inspections (gs_item_id, status, inspected_by, "
                        "inspected_at) values (:i, 'FINAL', :a, now())"
                    ),
                    {"i": item_id, "a": actor},
                )
            c.execute(
                text("update public.goods_slips set status = :s where id = :g"),
                {"s": status, "g": gs_id},
            )
    stock_item = c.execute(
        text("insert into public.stock_items (item_kind, product_id) values (:k, :p) returning id"),
        {"k": item_kind, "p": product.id},
    ).scalar_one()
    lot = c.execute(
        text(
            """insert into public.stock_lots (stock_item_id, gs_id, gs_item_id, condition_class,
                   source_condition_code)
               values (:s, :g, :i, :c, :src) returning id"""
        ),
        {
            "s": stock_item,
            "g": gs_id,
            "i": item_id,
            "c": condition_class,
            "src": source_condition,
        },
    ).scalar_one()
    c.execute(
        text(
            """select rms_private.rms_move_stock(
                 p_lot => :lot, p_from => null, p_to => :to, p_qty => :q, p_type => 'INWARD',
                 p_ref_type => 'p308_fixture', p_ref_id => null, p_idem_key => :k,
                 p_actor => null, p_reason => 'P3-08 fixture')"""
        ),
        {"lot": lot, "to": loc(conn, location), "q": qty, "k": f"p308-fx-{uuid.uuid4().hex}"},
    )
    return {
        "lot_id": lot,
        "gs_id": gs_id,
        "item_id": item_id,
        "product_id": product.id,
        "stock_item_id": stock_item,
    }


def balance(conn: Connection, lot_id: Any, location: str) -> int:
    return int(
        as_admin(conn)
        .execute(
            text(
                """select coalesce(sum(b.qty), 0) from public.stock_balances b
                     join public.inventory_locations l on l.id = b.location_id
                    where b.lot_id = :lot and l.code = :code"""
            ),
            {"lot": lot_id, "code": location},
        )
        .scalar_one()
    )
