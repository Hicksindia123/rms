"""Concurrency and row-level locking test for inventory ledger (prompt P2-01).

Guarantees that parallel requests competing for stock balance are serialized
by PostgreSQL 'SELECT ... FOR UPDATE' row-level locks, preventing negative balances
and race conditions (master plan §8.5, prompt P2-01 requirement 4).
"""

from __future__ import annotations

import concurrent.futures
import uuid
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.errors import SystemGuardViolation
from app.modules.inventory import ledger_service


def _purge_concurrency_fixture(db_engine: Engine) -> None:
    """Remove the committed fixture rows (P2-08: they used to stay in the dev DB forever).

    The ledger is insert-only by trigger, so teardown runs as the test superuser with
    session_replication_role = replica (user triggers off) and deletes in FK order.
    """
    lots = """public.stock_lots l join public.stock_items si on si.id = l.stock_item_id
              join public.products p on p.id = si.product_id"""
    with db_engine.begin() as conn:
        conn.execute(text("set local session_replication_role = replica"))
        for stmt in (
            f"delete from public.stock_movements m using {lots} "  # noqa: S608 - static text
            "where m.lot_id = l.id and p.code = 'CONCUR_PROD'",
            f"delete from public.stock_balances b using {lots} "  # noqa: S608 - static text
            "where b.lot_id = l.id and p.code = 'CONCUR_PROD'",
            "delete from public.stock_lots l using public.stock_items si, public.products p "
            "where si.id = l.stock_item_id and p.id = si.product_id and p.code = 'CONCUR_PROD'",
            "delete from public.stock_items si using public.products p "
            "where p.id = si.product_id and p.code = 'CONCUR_PROD'",
            "delete from public.goods_slips where gs_no like 'GS-CONCUR-%'",
            "delete from public.products where code = 'CONCUR_PROD'",
            "delete from public.product_categories where code = 'CONCUR_CAT'",
            "delete from rms_private.idempotency_keys where key like 'concur-%'",
        ):
            conn.execute(text(stmt))


def test_concurrency_20_parallel_deductions_from_10_balance(
    db_engine: Engine,
) -> None:
    """20 parallel requests deducting 1 unit from a balance of 10.

    Exactly 10 must succeed, exactly 10 must fail with G-16, and final balance must be 0.
    """
    _purge_concurrency_fixture(db_engine)
    try:
        _run_concurrency_scenario(db_engine)
    finally:
        _purge_concurrency_fixture(db_engine)


def _run_concurrency_scenario(db_engine: Engine) -> None:
    # 1. Setup test fixture in its own connection
    with Session(db_engine) as session:
        session.execute(text("grant rms_api to current_user with set true"))
        session.commit()

        # Category & Product
        cat_id = session.execute(
            text(
                """
                insert into public.product_categories (code, name)
                values ('CONCUR_CAT', 'Concurrency Category')
                on conflict (code) do update set name = excluded.name
                returning id
                """
            )
        ).scalar_one()

        prod_id = session.execute(
            text(
                """
                insert into public.products (category_id, code, name)
                values (:c, 'CONCUR_PROD', 'Concurrency Product')
                on conflict (code) do update set name = excluded.name
                returning id
                """
            ),
            {"c": cat_id},
        ).scalar_one()

        wv_id = session.execute(
            text(
                """
                select v.id from public.workflow_versions v
                join public.workflow_definitions d on d.id = v.workflow_definition_id
                where d.code = 'RMS_STANDARD' and v.status = 'PUBLISHED'
                limit 1
                """
            )
        ).scalar_one()

        gs_id = session.execute(
            text(
                """
                insert into public.goods_slips (
                  gs_no, workflow_version_id, delivery_mode_code,
                  courier_name, docket_no, box_count, status
                ) values (
                  :gs_no, :wv, 'COURIER_PARCEL', 'BlueDart', 'BD123456', 1, 'GATE_CREATED'
                )
                returning id
                """
            ),
            {"gs_no": f"GS-CONCUR-{uuid.uuid4().hex[:8].upper()}", "wv": wv_id},
        ).scalar_one()

        # P3-01 (G-09): TRANSIT only holds custody-transfer stock; use INWARD_STAGING here.
        loc_transit = session.execute(
            text("select id from public.inventory_locations where code = 'INWARD_STAGING'")
        ).scalar_one()
        loc_functional = session.execute(
            text(
                "select id from public.inventory_locations "
                "where location_class = 'FUNCTIONAL' limit 1"
            )
        ).scalar_one()

        item_id = ledger_service.create_stock_item(
            session,
            item_kind="FINISHED_GOOD",
            product_id=UUID(str(prod_id)),
        )

        lot_id = ledger_service.create_stock_lot(
            session,
            stock_item_id=item_id,
            gs_id=UUID(str(gs_id)),
            condition_class="AS_RECEIVED",
        )

        # Inward 10 units to INWARD_STAGING
        ledger_service.move_stock(
            session,
            lot_id=lot_id,
            from_location_id=None,
            to_location_id=UUID(str(loc_transit)),
            qty=10,
            movement_type="INWARD",
            idempotency_key=f"concur-inward-{uuid.uuid4()}",
        )
        session.commit()

        initial_bal = ledger_service.get_balance(session, lot_id, UUID(str(loc_transit)))
        assert initial_bal == 10

    # 2. Worker function executed across 20 concurrent threads
    def _deduct_one(worker_idx: int) -> tuple[int, bool, str]:
        # Each thread uses a fresh Session and connection
        with Session(db_engine) as worker_session:
            worker_session.execute(text("set role rms_api"))
            idem_key = f"concur-deduct-{worker_idx}-{uuid.uuid4()}"
            try:
                ledger_service.move_stock(
                    worker_session,
                    lot_id=lot_id,
                    from_location_id=UUID(str(loc_transit)),
                    to_location_id=UUID(str(loc_functional)),
                    qty=1,
                    movement_type="TRANSFER_OUT",
                    idempotency_key=idem_key,
                )
                worker_session.commit()
                return (worker_idx, True, "OK")
            except SystemGuardViolation as exc:
                worker_session.rollback()
                return (worker_idx, False, exc.guard)
            except Exception as exc:  # noqa: BLE001
                worker_session.rollback()
                return (worker_idx, False, f"ERR: {exc}")

    # 3. Launch 20 concurrent workers
    results: list[tuple[int, bool, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(_deduct_one, i) for i in range(20)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    successes = [r for r in results if r[1] is True]
    failures = [r for r in results if r[1] is False]

    # 4. Assert concurrency outcomes
    assert len(successes) == 10, f"Expected exactly 10 successes, got {len(successes)}"
    assert len(failures) == 10, f"Expected exactly 10 failures, got {len(failures)}"

    for fail in failures:
        assert fail[2] == "G-16", f"Failure reason must be G-16, got {fail[2]}"

    # 5. Verify final balances in database
    with Session(db_engine) as check_session:
        final_transit = ledger_service.get_balance(check_session, lot_id, UUID(str(loc_transit)))
        final_functional = ledger_service.get_balance(
            check_session, lot_id, UUID(str(loc_functional))
        )
        assert final_transit == 0, f"Final transit balance must be 0, got {final_transit}"
        assert final_functional == 10, (
            f"Final functional balance must be 10, got {final_functional}"
        )
