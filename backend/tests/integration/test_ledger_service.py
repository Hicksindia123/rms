"""Integration tests for authoritative ledger service (master plan §8.5, prompt P2-01)."""

from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import IdempotencyConflict, SystemGuardViolation
from app.modules.inventory import ledger_service


@pytest.fixture
def ledger_test_fixture(session_factory: sessionmaker[Session]) -> dict[str, UUID]:
    """Seed test product, category, locations, and goods slip for ledger testing."""
    with session_factory() as s:
        # Category
        cat_id = s.execute(
            text(
                """
                insert into public.product_categories (code, name)
                values ('LEDGER_CAT', 'Ledger Test Category')
                on conflict (code) do update set name = excluded.name
                returning id
                """
            )
        ).scalar_one()

        # Product
        prod_id = s.execute(
            text(
                """
                insert into public.products (category_id, code, name)
                values (:c, 'PROD_LEDGER', 'Ledger Test Product')
                on conflict (code) do update set name = excluded.name
                returning id
                """
            ),
            {"c": cat_id},
        ).scalar_one()

        # Workflow version
        wv_id = s.execute(
            text(
                """
                select v.id from public.workflow_versions v
                join public.workflow_definitions d on d.id = v.workflow_definition_id
                where d.code = 'RMS_STANDARD' and v.status = 'PUBLISHED'
                limit 1
                """
            )
        ).scalar_one()

        # Goods slip
        gs_id = s.execute(
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
            {"gs_no": f"GS-TEST-{uuid.uuid4().hex[:8].upper()}", "wv": wv_id},
        ).scalar_one()

        # Inventory locations
        # P3-01 (G-09): stock enters TRANSIT only through a custody transfer, so the generic ledger
        # moves use INWARD_STAGING; TRANSIT is kept for the G-08 pending-lot assertion.
        loc_staging = s.execute(
            text("select id from public.inventory_locations where code = 'INWARD_STAGING'")
        ).scalar_one()
        loc_transit = s.execute(
            text(
                "select id from public.inventory_locations where location_class = 'TRANSIT' limit 1"
            )
        ).scalar_one()
        loc_functional = s.execute(
            text(
                "select id from public.inventory_locations "
                "where location_class = 'FUNCTIONAL' limit 1"
            )
        ).scalar_one()
        loc_hazard = s.execute(
            text(
                "select id from public.inventory_locations "
                "where location_class = 'HAZARD_QUARANTINE' limit 1"
            )
        ).scalar_one()
        loc_scrap = s.execute(
            text(
                "select id from public.inventory_locations "
                "where location_class = 'SCRAP_DISPOSED' limit 1"
            )
        ).scalar_one()

        # Stock item
        item_id = ledger_service.create_stock_item(
            s,
            item_kind="FINISHED_GOOD",
            product_id=UUID(str(prod_id)),
        )

        s.commit()

        return {
            "category_id": UUID(str(cat_id)),
            "product_id": UUID(str(prod_id)),
            "workflow_version_id": UUID(str(wv_id)),
            "gs_id": UUID(str(gs_id)),
            "loc_staging": UUID(str(loc_staging)),
            "loc_transit": UUID(str(loc_transit)),
            "loc_functional": UUID(str(loc_functional)),
            "loc_hazard": UUID(str(loc_hazard)),
            "loc_scrap": UUID(str(loc_scrap)),
            "stock_item_id": item_id,
        }


def test_receipt_and_transfer_movement(
    session_factory: sessionmaker[Session],
    ledger_test_fixture: dict[str, UUID],
) -> None:
    """Test initial inward receipt and transfer between locations."""
    fix = ledger_test_fixture
    with session_factory() as s:
        lot_id = ledger_service.create_stock_lot(
            s,
            stock_item_id=fix["stock_item_id"],
            gs_id=fix["gs_id"],
            condition_class="AS_RECEIVED",
        )

        # 1. Inward 10 units to INWARD_STAGING
        idem1 = f"move-inward-{uuid.uuid4()}"
        m1 = ledger_service.move_stock(
            s,
            lot_id=lot_id,
            from_location_id=None,
            to_location_id=fix["loc_staging"],
            qty=10,
            movement_type="INWARD",
            idempotency_key=idem1,
            reason="Initial inward parcel",
        )
        assert isinstance(m1, UUID)

        # Check balance
        bal_staging = ledger_service.get_balance(s, lot_id, fix["loc_staging"])
        assert bal_staging == 10

        # 2. Idempotent replay returns same movement ID
        m1_replay = ledger_service.move_stock(
            s,
            lot_id=lot_id,
            from_location_id=None,
            to_location_id=fix["loc_staging"],
            qty=10,
            movement_type="INWARD",
            idempotency_key=idem1,
        )
        assert m1_replay == m1

        # 3. Transfer 4 units from INWARD_STAGING to FUNCTIONAL
        idem2 = f"move-transfer-{uuid.uuid4()}"
        m2 = ledger_service.move_stock(
            s,
            lot_id=lot_id,
            from_location_id=fix["loc_staging"],
            to_location_id=fix["loc_functional"],
            qty=4,
            movement_type="TRANSFER_OUT",
            idempotency_key=idem2,
            reason="Grading completed",
        )
        assert isinstance(m2, UUID)

        # Check balances
        assert ledger_service.get_balance(s, lot_id, fix["loc_staging"]) == 6
        assert ledger_service.get_balance(s, lot_id, fix["loc_functional"]) == 4

        # Balances by lot
        lot_bals = ledger_service.get_balances_by_lot(s, lot_id)
        assert len(lot_bals) == 2

        # Balances by GS
        gs_bals = ledger_service.get_balances_by_gs(s, fix["gs_id"])
        assert len(gs_bals) == 2


def test_idempotency_parameter_conflict(
    session_factory: sessionmaker[Session],
    ledger_test_fixture: dict[str, UUID],
) -> None:
    """Replaying an idempotency key with differing parameters raises IdempotencyConflict."""
    fix = ledger_test_fixture
    with session_factory() as s:
        lot_id = ledger_service.create_stock_lot(
            s,
            stock_item_id=fix["stock_item_id"],
            gs_id=fix["gs_id"],
            condition_class="AS_RECEIVED",
        )

        idem = f"idem-conflict-{uuid.uuid4()}"
        ledger_service.move_stock(
            s,
            lot_id=lot_id,
            from_location_id=None,
            to_location_id=fix["loc_staging"],
            qty=5,
            movement_type="INWARD",
            idempotency_key=idem,
        )

        # Replay with qty=10 -> raises IdempotencyConflict
        with pytest.raises(IdempotencyConflict) as exc:
            ledger_service.move_stock(
                s,
                lot_id=lot_id,
                from_location_id=None,
                to_location_id=fix["loc_staging"],
                qty=10,
                movement_type="INWARD",
                idempotency_key=idem,
            )
        assert "idempotency conflict" in str(exc.value).lower()
        assert exc.value.code == "IDEMPOTENCY_CONFLICT"


def test_reclassify_lot(
    session_factory: sessionmaker[Session],
    ledger_test_fixture: dict[str, UUID],
) -> None:
    """Test reclassifying stock from AS_RECEIVED to FUNCTIONAL_GOOD."""
    fix = ledger_test_fixture
    with session_factory() as s:
        source_lot = ledger_service.create_stock_lot(
            s,
            stock_item_id=fix["stock_item_id"],
            gs_id=fix["gs_id"],
            condition_class="AS_RECEIVED",
        )
        target_lot = ledger_service.create_stock_lot(
            s,
            stock_item_id=fix["stock_item_id"],
            gs_id=fix["gs_id"],
            condition_class="FUNCTIONAL_GOOD",
        )

        # Inward 5 units to FUNCTIONAL
        ledger_service.move_stock(
            s,
            lot_id=source_lot,
            from_location_id=None,
            to_location_id=fix["loc_functional"],
            qty=5,
            movement_type="RECEIPT",
            idempotency_key=f"inward-{uuid.uuid4()}",
        )

        # Reclassify 3 units to target lot
        moves = ledger_service.reclassify_lot(
            s,
            source_lot_id=source_lot,
            target_lot_id=target_lot,
            location_id=fix["loc_functional"],
            qty=3,
            idempotency_key=f"reclass-{uuid.uuid4()}",
            reason="Visual inspection passed",
        )
        assert len(moves) == 2  # Movement pair: consume + receive

        assert ledger_service.get_balance(s, source_lot, fix["loc_functional"]) == 2
        assert ledger_service.get_balance(s, target_lot, fix["loc_functional"]) == 3


def test_guard_g16_insufficient_balance(
    session_factory: sessionmaker[Session],
    ledger_test_fixture: dict[str, UUID],
) -> None:
    """G-16: Insufficient stock balance raises SystemGuardViolation(guard='G-16')."""
    fix = ledger_test_fixture
    with session_factory() as s:
        empty_lot = ledger_service.create_stock_lot(
            s,
            stock_item_id=fix["stock_item_id"],
            gs_id=fix["gs_id"],
            condition_class="AS_RECEIVED",
        )
        with pytest.raises(SystemGuardViolation) as exc:
            ledger_service.move_stock(
                s,
                lot_id=empty_lot,
                from_location_id=fix["loc_staging"],
                to_location_id=fix["loc_scrap"],
                qty=1,
                movement_type="TRANSFER_OUT",
                idempotency_key=f"fail-g16-{uuid.uuid4()}",
            )
        assert exc.value.guard == "G-16"


def test_guard_g04_not_allowed_lot_to_functional(
    session_factory: sessionmaker[Session],
    ledger_test_fixture: dict[str, UUID],
) -> None:
    """G-04: Not Allowed stock cannot enter functional location."""
    fix = ledger_test_fixture
    with session_factory() as s:
        not_allowed_lot = ledger_service.create_stock_lot(
            s,
            stock_item_id=fix["stock_item_id"],
            gs_id=fix["gs_id"],
            condition_class="NOT_ALLOWED",
        )
        with pytest.raises(SystemGuardViolation) as exc:
            ledger_service.move_stock(
                s,
                lot_id=not_allowed_lot,
                from_location_id=None,
                to_location_id=fix["loc_functional"],
                qty=1,
                movement_type="RECEIPT",
                idempotency_key=f"fail-g04-{uuid.uuid4()}",
            )
        assert exc.value.guard == "G-04"


def test_guard_g05_hazard_lot_to_functional(
    session_factory: sessionmaker[Session],
    ledger_test_fixture: dict[str, UUID],
) -> None:
    """G-05: Hazard lot can only move to HAZARD_QUARANTINE or SCRAP_DISPOSED."""
    fix = ledger_test_fixture
    with session_factory() as s:
        hazard_lot = ledger_service.create_stock_lot(
            s,
            stock_item_id=fix["stock_item_id"],
            gs_id=fix["gs_id"],
            condition_class="HAZARD",
        )
        with pytest.raises(SystemGuardViolation) as exc:
            ledger_service.move_stock(
                s,
                lot_id=hazard_lot,
                from_location_id=None,
                to_location_id=fix["loc_staging"],
                qty=1,
                movement_type="RECEIPT",
                idempotency_key=f"fail-g05-{uuid.uuid4()}",
            )
        assert exc.value.guard == "G-05"


def test_guard_g08_pending_lot_to_transit(
    session_factory: sessionmaker[Session],
    ledger_test_fixture: dict[str, UUID],
) -> None:
    """G-08: Pending lot cannot move to TRANSIT or FUNCTIONAL."""
    fix = ledger_test_fixture
    with session_factory() as s:
        pending_lot = ledger_service.create_stock_lot(
            s,
            stock_item_id=fix["stock_item_id"],
            gs_id=fix["gs_id"],
            condition_class="AS_RECEIVED",
            is_pending=True,
        )
        with pytest.raises(SystemGuardViolation) as exc:
            ledger_service.move_stock(
                s,
                lot_id=pending_lot,
                from_location_id=None,
                to_location_id=fix["loc_transit"],
                qty=1,
                movement_type="RECEIPT",
                idempotency_key=f"fail-g08-{uuid.uuid4()}",
            )
        assert exc.value.guard == "G-08"


def test_guard_g12_intermediate_store_rejects_non_good(
    session_factory: sessionmaker[Session],
    ledger_test_fixture: dict[str, UUID],
) -> None:
    """G-12: Intermediate Store (FUNCTIONAL) rejects non-functional lots."""
    fix = ledger_test_fixture
    with session_factory() as s:
        salvaged_lot = ledger_service.create_stock_lot(
            s,
            stock_item_id=fix["stock_item_id"],
            gs_id=fix["gs_id"],
            condition_class="SALVAGED",
        )
        with pytest.raises(SystemGuardViolation) as exc:
            ledger_service.move_stock(
                s,
                lot_id=salvaged_lot,
                from_location_id=None,
                to_location_id=fix["loc_functional"],
                qty=1,
                movement_type="RECEIPT",
                idempotency_key=f"fail-g12-{uuid.uuid4()}",
            )
        assert exc.value.guard == "G-12"
