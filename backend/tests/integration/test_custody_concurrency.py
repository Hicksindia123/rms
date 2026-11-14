"""Concurrent acceptance of one custody transfer (prompt P3-01, G-09, G-16).

Two receivers accept the same dispatched transfer at the same time with different Idempotency-Keys.
The transfer row lock (`SELECT … FOR UPDATE`) serialises them: exactly one succeeds, the other gets
409 TRANSFER_NOT_AWAITING_ACCEPTANCE, and the stock is credited to the Intermediate Store once.

Real concurrency needs committed rows on separate connections, so this test commits its fixture
and removes it afterwards (as tests/integration/test_ledger_concurrency.py does).
"""

# Teardown SQL below is assembled only from static fragments (no input): S608 does not apply.
# ruff: noqa: S608

from __future__ import annotations

import concurrent.futures
import json
import threading
import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import UnitOfWork
from app.core.errors import Conflict
from app.core.idempotency import IdempotencyKey
from app.core.permissions import effective_permissions
from app.core.security import CurrentUser, Role
from app.modules.custody import service as custody
from app.modules.custody.schemas import AcceptIn, CountLineIn, TransferLineIn
from app.modules.inventory import ledger_service

TAG = "custconc"


_GS = "select id from public.goods_slips where gs_no like 'GS-CUSTCONC-%'"
_LOTS = "select id from public.stock_lots where gs_id in (" + _GS + ")"
_TRANSFERS = (
    "select distinct transfer_id from public.custody_transfer_lines where lot_id in (" + _LOTS + ")"
)
_USERS = "select id from auth.users where email like 'custconc-%@example.test'"
_PURGE = (
    "delete from public.notifications where entity_id in (" + _TRANSFERS + ")",
    "delete from public.custody_transfers where id in (" + _TRANSFERS + ")",
    "delete from public.stock_movements where lot_id in (" + _LOTS + ")",
    "delete from public.stock_balances where lot_id in (" + _LOTS + ")",
    "delete from public.custody_transfer_lines where lot_id in (" + _LOTS + ")",
    "delete from public.stock_lots where gs_id in (" + _GS + ")",
    "delete from public.stock_items si using public.products p "
    "where p.id = si.product_id and p.code = 'CUSTCONC_PROD'",
    "delete from public.goods_slips where gs_no like 'GS-CUSTCONC-%'",
    "delete from public.products where code = 'CUSTCONC_PROD'",
    "delete from rms_private.idempotency_keys where key like 'custconc-%'",
    "delete from public.user_roles where user_id in (" + _USERS + ")",
    "delete from public.profiles where id in (" + _USERS + ")",
    "delete from auth.users where email like 'custconc-%@example.test'",
)


def _purge(db_engine: Engine) -> None:
    """Teardown as the test superuser with user triggers (incl. FK triggers) off."""
    with db_engine.begin() as conn:
        conn.execute(text("set local session_replication_role = replica"))
        for stmt in _PURGE:
            conn.execute(text(stmt))


def _user(conn: Any, role: str, name: str) -> CurrentUser:
    user_id = uuid.uuid4()
    conn.execute(
        text(
            """insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data)
               values (:id, :email, cast(:app as jsonb), cast(:meta as jsonb))"""
        ),
        {
            "id": user_id,
            "email": f"{TAG}-{user_id.hex[:12]}@example.test",
            "app": json.dumps({"rms_activate": True}),
            "meta": json.dumps({"full_name": name}),
        },
    )
    role_row = conn.execute(
        text("select id, code, name from public.roles where code = :c"), {"c": role}
    ).one()
    conn.execute(
        text("insert into public.user_roles (user_id, role_id) values (:u, :r)"),
        {"u": user_id, "r": role_row.id},
    )
    return CurrentUser(
        id=user_id,
        email=None,
        full_name=name,
        employee_code=None,
        phone=None,
        is_super_admin=False,
        department=None,
        roles=(Role(id=role_row.id, code=role_row.code, name=role_row.name),),
    )


def test_concurrent_accept_credits_the_receiver_once(db_engine: Engine) -> None:
    _purge(db_engine)
    try:
        _scenario(db_engine)
    finally:
        _purge(db_engine)


def _scenario(db_engine: Engine) -> None:
    factory = sessionmaker(bind=db_engine, expire_on_commit=False, autoflush=False)
    with db_engine.begin() as conn:
        aman = _user(conn, "INWARD_VERIFIER", "Aman (concurrency)")
        sahil_a = _user(conn, "INTERMEDIATE_STORE_MANAGER", "Sahil A (concurrency)")
        sahil_b = _user(conn, "INTERMEDIATE_STORE_MANAGER", "Sahil B (concurrency)")

    with factory() as s:
        wv = s.execute(
            text(
                """select wv.id from public.workflow_versions wv
                     join public.workflow_definitions wd on wd.id = wv.workflow_definition_id
                    where wd.code = 'RMS_STANDARD' and wv.status = 'PUBLISHED' limit 1"""
            )
        ).scalar_one()
        gs_id = s.execute(
            text(
                """insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code,
                       courier_name, docket_no, box_count, status)
                   values (:no, :wv, 'COURIER_PARCEL', 'BlueDart', 'BD1', 1, 'GATE_CREATED')
                   returning id"""
            ),
            {"no": f"GS-CUSTCONC-{uuid.uuid4().hex[:8].upper()}", "wv": wv},
        ).scalar_one()
        product = s.execute(
            text(
                """insert into public.products (code, name, category_id)
                   select 'CUSTCONC_PROD', 'Concurrency product', id
                     from public.product_categories where code = 'DMT' returning id"""
            )
        ).scalar_one()
        item = ledger_service.create_stock_item(
            s, item_kind="FINISHED_GOOD", product_id=UUID(str(product))
        )
        lot = ledger_service.create_stock_lot(
            s, stock_item_id=item, gs_id=UUID(str(gs_id)), condition_class="AS_RECEIVED"
        )
        staging = ledger_service.get_location_by_code(s, "INWARD_STAGING")
        assert staging
        ledger_service.move_stock(
            s,
            lot_id=lot,
            from_location_id=None,
            to_location_id=staging["id"],
            qty=5,
            movement_type="INWARD",
            idempotency_key=f"{TAG}-inward-{uuid.uuid4()}",
        )
        transfer_id = custody.initiate_transfer(
            s,
            actor=aman,
            from_location_code="INWARD_STAGING",
            to_location_code="INTERMEDIATE_STORE",
            lines=[TransferLineIn(lot_id=lot, qty=5)],
        )
        s.commit()

    barrier = threading.Barrier(2)

    def accept(user: CurrentUser) -> str:
        with factory() as s:
            perms = effective_permissions(s, user.id, is_super_admin=False)
        service = custody.CustodyService(UnitOfWork(factory, request_id=f"{TAG}-{user.id}"))
        k = f"{TAG}-{uuid.uuid4()}"
        idem = IdempotencyKey(key=k, endpoint="POST /accept", request_hash=k)
        barrier.wait()
        try:
            service.accept(
                user,
                perms,
                transfer_id,
                AcceptIn(
                    lines=[CountLineIn(lot_id=lot, qty_counted=5)],
                    acceptance_code="ACCEPTED_VERIFIED",
                ),
                idem,
            )
            return "ok"
        except Conflict as exc:
            return exc.code

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(accept, [sahil_a, sahil_b]))
    assert results == ["TRANSFER_NOT_AWAITING_ACCEPTANCE", "ok"]

    with Session(db_engine) as s:
        balances = dict(
            s.execute(
                text(
                    """select l.code, b.qty from public.stock_balances b
                         join public.inventory_locations l on l.id = b.location_id
                        where b.lot_id = :lot"""
                ),
                {"lot": lot},
            ).all()
        )
        assert balances == {"INWARD_STAGING": 0, "TRANSIT": 0, "INTERMEDIATE_STORE": 5}
        status = s.execute(
            text("select status from public.custody_transfers where id = :t"), {"t": transfer_id}
        ).scalar_one()
        assert status == "ACCEPTED"
