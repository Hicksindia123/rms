"""Fixtures for the P2-08 Phase 2 gate suites (guards, config safety, integrity, performance)."""

from __future__ import annotations

import uuid
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
from tests.integration.phase2_gate.helpers import Admin, Products
from tests.integration.test_gate_inward import Masters
from tests.integration.test_unboxing import Actors, FakeStorage


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


@pytest.fixture
def admin(users: UserFactory, make_token: JwtFactory) -> Admin:
    uid = users.create(super_admin=True, full_name="Super Admin")
    return Admin(uid, make_token(uid))


@pytest.fixture
def actors(users: UserFactory, make_token: JwtFactory, admin: Admin) -> Actors:
    aman_id = users.create(roles=["INWARD_VERIFIER"], full_name="Aman")
    rm_id = users.create(roles=["REPLACEMENT_MANAGER"], full_name="Pratham")
    acc_id = users.create(roles=["ACCOUNTS"], full_name="Deepak")
    return Actors(
        gate=make_token(users.create(roles=["GATE_INWARD"], full_name="Anuj")),
        aman=make_token(aman_id),
        aman_id=aman_id,
        rm=make_token(rm_id),
        rm_id=rm_id,
        accounts=make_token(acc_id),
        accounts_id=acc_id,
        admin=admin.token,
    )


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
                    "code": f"GR-{category}-{tag}",
                    "name": f"Guard {category} {tag}",
                    "cat": category,
                },
            ).scalar_one()
        )

    return Products(dmt=make("DMT"), prismatic=make("PRISMATIC"), eo=make("ENCLOSED_OVAL"))
