"""Integration harness against the local Supabase Postgres.

* `db_conn`: one connection per test with an outer transaction that is ALWAYS rolled back, so tests
  leave no data behind. The app's Unit of Work runs in SAVEPOINTs on that connection
  (`join_transaction_mode="create_savepoint"`), as the `rms_api` role (SET LOCAL ROLE), exactly like
  production. Fixture helpers switch back to the connecting superuser (RESET ROLE) for setup that
  needs auth.users.
* `client`: httpx AsyncClient over the ASGI app with the session factory overridden.
* `users`: factory that creates auth users (→ profiles via the P1-02 trigger) with roles,
  overrides, Super Admin and inactive variants.

The whole module is skipped (with the reason) when TEST_DATABASE_URL is unreachable or has no RMS
schema. For safety it refuses non-local hosts unless RMS_ALLOW_REMOTE_TEST_DB=1.
"""

import functools
import json
import os
import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection, Engine, create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.db import UowDep, get_session_factory
from app.core.errors import enforce_guard
from app.core.permissions import require
from app.core.security import CurrentUser, CurrentUserDep
from app.main import create_app
from app.modules._template.router import router as template_router

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


@functools.cache
def _probe_database(raw_url: str) -> str | None:
    """Return None when the DB is usable, otherwise the skip reason (probed once per run)."""
    url = make_url(raw_url)
    engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1 from public.profiles limit 0"))
            conn.execute(text("select 1 from rms_private.idempotency_keys limit 0"))
    except (OperationalError, ProgrammingError) as exc:
        reason = str(exc.orig).splitlines()[0] if exc.orig else str(exc)
        return f"integration DB unavailable at {url.render_as_string(hide_password=True)}: {reason}"
    finally:
        engine.dispose()
    return None


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    raw_url = os.environ["TEST_DATABASE_URL"]
    url = make_url(raw_url)
    if url.host not in _LOCAL_HOSTS and os.environ.get("RMS_ALLOW_REMOTE_TEST_DB") != "1":
        pytest.fail(f"TEST_DATABASE_URL host {url.host!r} is not local; refusing to run tests")
    reason = _probe_database(raw_url)
    if reason:
        pytest.skip(reason)
    engine = create_engine(url, poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def db_conn(db_engine: Engine) -> Iterator[Connection]:
    conn = db_engine.connect()
    outer = conn.begin()
    try:
        can_set = conn.execute(text("select pg_has_role(current_user, 'rms_api', 'SET')")).scalar()
        if not can_set:
            # Rolled back with the outer transaction.
            conn.execute(text("grant rms_api to current_user with set true"))
        yield conn
    finally:
        outer.rollback()
        conn.close()


def as_admin(conn: Connection) -> Connection:
    """Leave the rms_api role a previous app transaction set (SET LOCAL lasts to the outer end)."""
    conn.execute(text("reset role"))
    return conn


@pytest.fixture
def session_factory(db_conn: Connection) -> sessionmaker[Session]:
    factory = sessionmaker(
        bind=db_conn,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
        autoflush=False,
    )

    @event.listens_for(factory, "after_begin")
    def _run_as_rms_api(_s: Session, _t: SessionTransaction, connection: Connection) -> None:
        connection.execute(text("set local role rms_api"))

    return factory


# --- test-only routes (never mounted in app/main.py) -------------------------------------------
probe = APIRouter(prefix="/test", tags=["test"])


@probe.get("/users-view")
def users_view(user: Annotated[CurrentUser, Depends(require("users", "view"))]) -> dict[str, str]:
    return {"user_id": str(user.id)}


@probe.post("/guard/g16")
def service_guard(user: CurrentUserDep) -> None:
    # A service-level system guard: takes no user, so Super Admin cannot bypass it.
    enforce_guard(False, "G-16", "Stock balance would become negative")


@probe.post("/guard/g18/{version_id}")
def db_guard(version_id: uuid.UUID, user: CurrentUserDep, uow: UowDep) -> None:
    # A DB-level system guard: the G-18 trigger rejects edits to a PUBLISHED workflow version.
    with uow.transaction(user.id) as session:
        session.execute(
            text("update public.workflow_versions set snapshot = '{}'::jsonb where id = :id"),
            {"id": version_id},
        )


def build_test_app() -> FastAPI:
    test_app = create_app()
    test_app.include_router(template_router, prefix="/api/v1")
    test_app.include_router(probe, prefix="/api/v1")
    return test_app


@pytest.fixture
async def client(session_factory: sessionmaker[Session]) -> AsyncIterator[AsyncClient]:
    test_app = build_test_app()
    test_app.dependency_overrides[get_session_factory] = lambda: session_factory
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
        yield c


@dataclass(frozen=True)
class Override:
    module_code: str
    action: str
    effect: str  # 'grant' | 'deny'
    expires_at: datetime | None = None


class UserFactory:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def create(
        self,
        *,
        roles: Sequence[str] = (),
        active: bool = True,
        super_admin: bool = False,
        overrides: Sequence[Override] = (),
        full_name: str = "Test User",
    ) -> uuid.UUID:
        conn = as_admin(self.conn)
        user_id = uuid.uuid4()
        conn.execute(
            text(
                """
                insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data)
                values (:id, :email, cast(:app as jsonb), cast(:meta as jsonb))
                """
            ),
            {
                "id": user_id,
                "email": f"test-{user_id.hex[:12]}@example.test",
                "app": json.dumps({"rms_activate": active}),
                "meta": json.dumps({"full_name": full_name}),
            },
        )
        if super_admin:
            existing = conn.execute(
                text("select id from public.profiles where is_super_admin and is_active limit 1")
            ).scalar()
            # Only an active Super Admin may grant the flag (P1-02 guard), except the very first.
            self.set_actor(existing)
            conn.execute(
                text("update public.profiles set is_super_admin = true where id = :id"),
                {"id": user_id},
            )
            self.set_actor(None)
        if roles:
            inserted = conn.execute(
                text(
                    """
                    insert into public.user_roles (user_id, role_id)
                    select :uid, r.id from public.roles r where r.code = any(:codes)
                    """
                ),
                {"uid": user_id, "codes": list(roles)},
            ).rowcount
            assert inserted == len(set(roles)), f"unknown role code in {roles}"
        for o in overrides:
            inserted = conn.execute(
                text(
                    """
                    insert into public.user_permission_overrides
                           (user_id, permission_id, effect, reason, expires_at)
                    select :uid, p.id, :effect, 'test fixture', :expires_at
                      from public.permissions p
                     where p.module_code = :module and p.action = :action
                    """
                ),
                {
                    "uid": user_id,
                    "effect": o.effect,
                    "expires_at": o.expires_at,
                    "module": o.module_code,
                    "action": o.action,
                },
            ).rowcount
            assert inserted == 1, f"unknown permission {o.module_code}.{o.action}"
        return user_id

    def set_actor(self, actor: uuid.UUID | None) -> None:
        self.conn.execute(
            text("select set_config('app.user_id', :uid, true)"),
            {"uid": str(actor) if actor else ""},
        )


@pytest.fixture
def users(db_conn: Connection) -> UserFactory:
    return UserFactory(db_conn)


def publish_workflow(
    conn: Connection,
    *,
    step_code: str,
    user_id: uuid.UUID | None = None,
    role_code: str | None = None,
    assignment_type: str = "PERFORM",
) -> uuid.UUID:
    """Create a one-step workflow, assign the step, publish it (G-18: children while DRAFT)."""
    conn = as_admin(conn)
    suffix = uuid.uuid4().hex[:8].upper()
    def_id = conn.execute(
        text(
            "insert into public.workflow_definitions (code, name) values (:c, 'Test WF') "
            "returning id"
        ),
        {"c": f"TEST_WF_{suffix}"},
    ).scalar_one()
    ver_id = conn.execute(
        text(
            "insert into public.workflow_versions (workflow_definition_id, version_no) "
            "values (:d, 1) returning id"
        ),
        {"d": def_id},
    ).scalar_one()
    stage_id = conn.execute(
        text(
            "insert into public.workflow_stages (workflow_version_id, code, label) "
            "values (:v, 'STAGE_1', 'Stage 1') returning id"
        ),
        {"v": ver_id},
    ).scalar_one()
    step_id = conn.execute(
        text(
            "insert into public.workflow_steps (workflow_version_id, stage_id, code, label) "
            "values (:v, :s, :code, 'Step') returning id"
        ),
        {"v": ver_id, "s": stage_id, "code": step_code},
    ).scalar_one()
    conn.execute(
        text("""insert into public.step_assignments
                       (workflow_step_id, role_id, user_id, assignment_type)
                select :step, (select id from public.roles where code = :role), :uid, :atype"""),
        {"step": step_id, "role": role_code, "uid": user_id, "atype": assignment_type},
    )
    conn.execute(
        text(
            "update public.workflow_versions set status = 'PUBLISHED', "
            "snapshot = '{}'::jsonb, published_at = now() where id = :v"
        ),
        {"v": ver_id},
    )
    return ver_id


def fetch_all(conn: Connection, sql: str, **params: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in as_admin(conn).execute(text(sql), params).mappings()]


def force_gs_status(conn: Connection, gs_id: Any, status: str) -> None:
    """Test SETUP only: put a GS in `status` without walking the workflow.

    The G-02 trigger (P2-03) rightly rejects such jumps, so triggers are disabled for this single
    statement (`session_replication_role = replica`, superuser) and restored right after.
    """
    c = as_admin(conn)
    c.execute(text("set local session_replication_role = replica"))
    try:
        c.execute(
            text("update public.goods_slips set status = :s where id = :id"),
            {"s": status, "id": gs_id},
        )
    finally:
        c.execute(text("set local session_replication_role = origin"))
