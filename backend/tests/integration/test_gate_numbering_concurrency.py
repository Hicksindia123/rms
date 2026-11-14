"""20 concurrent gate creates → 20 unique, gap-free sequential GS numbers (P2-02, BR-01, DEC-01).

Unlike the other integration tests, each create runs in its own committed transaction on its own
connection (as in production), so the row lock in rms_private.next_number is really contended.
The created GS rows are deleted and the GS counters restored afterwards, so later runs (and the
04_numbering pgTAP file) see the same numbering state; the test user and party stay (profiles are
never hard-deleted, P1-02).
"""

from __future__ import annotations

import concurrent.futures
import json
import re
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, event, text
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker

from app.core.db import UnitOfWork
from app.core.idempotency import IdempotencyKey
from app.core.security import CurrentUser
from app.modules.goods_slips.schemas import GateDocumentIn, GateInwardIn
from app.modules.goods_slips.service import GateInwardService

N = 20
SEQ = re.compile(r"(\d+)$")


@pytest.fixture
def committed_setup(db_engine: Engine) -> Iterator[dict[str, Any]]:
    tag = uuid.uuid4().hex[:8]
    user_id = uuid.uuid4()
    with db_engine.begin() as conn:
        conn.execute(text("grant rms_api to current_user with set true"))
        conn.execute(
            text(
                """insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data)
                   values (:id, :email, cast(:app as jsonb), cast(:meta as jsonb))"""
            ),
            {
                "id": user_id,
                "email": f"concurrency-{tag}@example.test",
                "app": json.dumps({"rms_activate": True}),
                "meta": json.dumps({"full_name": "Concurrency Gate User"}),
            },
        )
        conn.execute(
            text(
                """insert into public.user_roles (user_id, role_id)
                   select :uid, id from public.roles where code = 'GATE_INWARD'"""
            ),
            {"uid": user_id},
        )
        state = conn.execute(
            text("insert into public.states (name) values (:n) returning id"),
            {"n": f"Concurrency State {tag}"},
        ).scalar_one()
        station = conn.execute(
            text("insert into public.stations (state_id, name) values (:s, 'C') returning id"),
            {"s": state},
        ).scalar_one()
        party = conn.execute(
            text(
                """insert into public.parties (code, name, state_id, station_id)
                   values (:c, :c, :s, :st) returning id"""
            ),
            {"c": f"CONC-{tag}", "s": state, "st": station},
        ).scalar_one()
        counters = [
            dict(r)
            for r in conn.execute(
                text(
                    """select c.period_key, c.last_value from public.number_series_counters c
                         join public.number_series s on s.id = c.series_id where s.code = 'GS'"""
                )
            ).mappings()
        ]
    created: list[uuid.UUID] = []
    yield {"user_id": user_id, "party_id": party, "created": created}
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """delete from public.number_series_counters
                    where series_id = (select id from public.number_series where code = 'GS')"""
            )
        )
        for c in counters:
            conn.execute(
                text(
                    """insert into public.number_series_counters (series_id, period_key, last_value)
                       select id, :p, :v from public.number_series where code = 'GS'"""
                ),
                {"p": c["period_key"], "v": c["last_value"]},
            )
        if created:
            # Since 2026-11-10 each gate create publishes outbox events (GS_CREATED / Accounts
            # gate-doc alert). The outbox is append-only (P4-03 guard), so deleting the GS (FK
            # `on delete set null`) would be rejected. Test TEARDOWN only: purge exactly this
            # test's events and their fan-out rows with triggers off (superuser, as in
            # conftest.force_gs_status), then delete the GS rows normally.
            conn.execute(text("set local session_replication_role = replica"))
            events = "select id from public.notification_events where gs_id = any(:ids)"
            for table in (
                "public.notification_deliveries",
                "public.notifications",
                "public.workflow_task_escalations",
            ):
                conn.execute(
                    text(f"delete from {table} where event_id in ({events})"),  # noqa: S608
                    {"ids": created},
                )
            conn.execute(
                text("delete from public.notification_events where gs_id = any(:ids)"),
                {"ids": created},
            )
            conn.execute(text("set local session_replication_role = origin"))
            conn.execute(
                text("delete from public.form_responses where entity_id = any(:ids)"),
                {"ids": created},
            )
            conn.execute(
                text("delete from public.goods_slips where id = any(:ids)"), {"ids": created}
            )
        conn.execute(
            text("delete from rms_private.idempotency_keys where user_id = :uid"),
            {"uid": user_id},
        )


def _factory(engine: Engine) -> sessionmaker[Session]:
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    @event.listens_for(factory, "after_begin")
    def _run_as_rms_api(_s: Session, _t: SessionTransaction, connection: Connection) -> None:
        connection.execute(text("set local role rms_api"))

    return factory


def test_20_concurrent_creates_get_unique_sequential_numbers(
    db_engine: Engine, committed_setup: dict[str, Any]
) -> None:
    user = CurrentUser(
        id=committed_setup["user_id"],
        email=None,
        full_name="Concurrency Gate User",
        employee_code=None,
        phone=None,
        is_super_admin=False,
        department=None,
        roles=(),
    )
    service = GateInwardService(UnitOfWork(_factory(db_engine), request_id="concurrency"))
    payload = GateInwardIn(
        party_id=committed_setup["party_id"],
        # Form v2: E-Commerce has no gate entry number (DEC-39), so 20 identical payloads are valid.
        values={
            "return_type": "ECOMMERCE_RETURN",
            "carton_count": 1,
            "delivery_mode": "COURIER_PARCEL",
            "courier_name": "DTDC",
            "docket_no": "D-1",
            "no_document": False,
        },
        documents=[GateDocumentIn(doc_type_code="HANDWRITTEN_SLIP", remarks="slip")],
    )

    def create(i: int) -> dict[str, Any]:
        key = IdempotencyKey(
            key=f"conc-{uuid.uuid4()}", endpoint="POST /api/v1/gs", request_hash=f"h{i}"
        )
        result = service.create(user, payload, key)
        assert result.status_code == 201
        body: dict[str, Any] = result.body
        # Record each committed GS at once (list.append is atomic), so the teardown removes it
        # even when another worker fails; otherwise leftover rows collide with the restored
        # counter and break every later gate create in the session.
        committed_setup["created"].append(uuid.UUID(body["goods_slip"]["id"]))
        return body["goods_slip"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=N) as pool:
        slips = list(pool.map(create, range(N)))

    numbers = [s["gs_no"] for s in slips]
    assert len(set(numbers)) == N
    seqs = sorted(int(m.group(1)) for n in numbers if (m := SEQ.search(n)))
    assert len(seqs) == N
    assert seqs == list(range(seqs[0], seqs[0] + N)), seqs  # gap-free
