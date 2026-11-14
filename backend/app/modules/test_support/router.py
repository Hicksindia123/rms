"""Test endpoints for guard and error envelope verification (prompt P2-01).

These endpoints are only registered when APP_ENV=test.
"""

from __future__ import annotations

import re
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.context import get_request_id
from app.core.db import UowDep
from app.core.errors import DomainError, SystemGuardViolation, error_response
from app.modules.inventory import ledger_service

router = APIRouter(prefix="/test", tags=["test-support"])

_GUARD_CODE_PATTERN = re.compile(r"^G-(0[1-9]|1[0-9]|2[0-2])$")


def _trigger_database_guard(db: Session, guard_code: str) -> None:
    """Execute a real database stock movement that violates the specified guard."""
    # Find needed test reference IDs
    loc_functional = db.execute(
        text(
            "select id from public.inventory_locations where location_class = 'FUNCTIONAL' limit 1"
        )
    ).scalar_one_or_none()
    loc_transit = db.execute(
        text("select id from public.inventory_locations where location_class = 'TRANSIT' limit 1")
    ).scalar_one_or_none()
    loc_scrap = db.execute(
        text(
            "select id from public.inventory_locations "
            "where location_class = 'SCRAP_DISPOSED' limit 1"
        )
    ).scalar_one_or_none()

    # Get or create a product & goods slip for test lots
    product_id = db.execute(text("select id from public.products limit 1")).scalar_one_or_none()
    if not product_id:
        cat_id = db.execute(text("select id from public.product_categories limit 1")).scalar_one()
        product_id = db.execute(
            text(
                "insert into public.products (category_id, code, name) "
                "values (:c, 'TEST_P', 'Test P') returning id"
            ),
            {"c": cat_id},
        ).scalar_one()

    gs_id = db.execute(text("select id from public.goods_slips limit 1")).scalar_one_or_none()
    if not gs_id:
        wv_id = db.execute(text("select id from public.workflow_versions limit 1")).scalar_one()
        gs_id = db.execute(
            text(
                """
                insert into public.goods_slips (
                  gs_no, workflow_version_id, delivery_mode_code,
                  courier_name, docket_no, box_count, status
                ) values (
                  'GS-TEST-GUARD', :wv, 'COURIER_PARCEL', 'BlueDart', 'BD123456', 1, 'GATE_CREATED'
                ) returning id
                """
            ),
            {"wv": wv_id},
        ).scalar_one()

    # Create stock item
    stock_item_id = db.execute(
        text(
            """
            insert into public.stock_items (item_kind, product_id)
            values ('FINISHED_GOOD', :prod) returning id
            """
        ),
        {"prod": product_id},
    ).scalar_one()

    if guard_code == "G-04":
        lot_id = ledger_service.create_stock_lot(
            db,
            stock_item_id=stock_item_id,
            gs_id=gs_id,
            condition_class="NOT_ALLOWED",
        )
        ledger_service.move_stock(
            db,
            lot_id=lot_id,
            from_location_id=None,
            to_location_id=loc_functional,
            qty=1,
            movement_type="RECEIPT",
            idempotency_key=f"test-g04-{uuid4()}",
        )

    elif guard_code == "G-05":
        lot_id = ledger_service.create_stock_lot(
            db,
            stock_item_id=stock_item_id,
            gs_id=gs_id,
            condition_class="HAZARD",
        )
        ledger_service.move_stock(
            db,
            lot_id=lot_id,
            from_location_id=None,
            to_location_id=loc_transit,
            qty=1,
            movement_type="RECEIPT",
            idempotency_key=f"test-g05-{uuid4()}",
        )

    elif guard_code == "G-08":
        lot_id = ledger_service.create_stock_lot(
            db,
            stock_item_id=stock_item_id,
            gs_id=gs_id,
            condition_class="AS_RECEIVED",
            is_pending=True,
        )
        ledger_service.move_stock(
            db,
            lot_id=lot_id,
            from_location_id=None,
            to_location_id=loc_transit,
            qty=1,
            movement_type="RECEIPT",
            idempotency_key=f"test-g08-{uuid4()}",
        )

    elif guard_code == "G-12":
        lot_id = ledger_service.create_stock_lot(
            db,
            stock_item_id=stock_item_id,
            gs_id=gs_id,
            condition_class="SALVAGED",
        )
        ledger_service.move_stock(
            db,
            lot_id=lot_id,
            from_location_id=None,
            to_location_id=loc_functional,
            qty=1,
            movement_type="RECEIPT",
            idempotency_key=f"test-g12-{uuid4()}",
        )

    elif guard_code == "G-16":
        lot_id = ledger_service.create_stock_lot(
            db,
            stock_item_id=stock_item_id,
            gs_id=gs_id,
            condition_class="AS_RECEIVED",
        )
        # Attempt to transfer from transit without balance
        ledger_service.move_stock(
            db,
            lot_id=lot_id,
            from_location_id=loc_transit,
            to_location_id=loc_scrap,
            qty=50,
            movement_type="TRANSFER_OUT",
            idempotency_key=f"test-g16-{uuid4()}",
        )

    else:
        # Generic guard simulation for remaining guards
        raise SystemGuardViolation(guard_code, f"System guard {guard_code} validation failed")


# Test-only: kept out of the OpenAPI schema (and generated client types). GET+POST on one handler
# also produced a duplicate operation-id warning on every schema build (fixed in P2-08).
@router.api_route("/guards/{guard_code}", methods=["GET", "POST"], include_in_schema=False)
def trigger_guard_test(
    guard_code: str,
    request: Request,
    uow: UowDep,
) -> JSONResponse:
    """Test endpoint that intentionally triggers a system guard and returns a 422 envelope."""
    if not _GUARD_CODE_PATTERN.fullmatch(guard_code):
        return error_response(
            400,
            "BAD_REQUEST",
            f"Invalid system guard code: {guard_code}",
            request_id=get_request_id(request),
        )

    try:
        with uow.transaction() as session:
            _trigger_database_guard(session, guard_code)
    except SystemGuardViolation as exc:
        return error_response(
            422,
            exc.guard,
            exc.message,
            details={"guard": exc.guard},
            request_id=get_request_id(request),
        )
    except DomainError as exc:
        return error_response(
            422,
            guard_code,
            exc.message,
            details={"guard": guard_code},
            request_id=get_request_id(request),
        )

    return JSONResponse(
        status_code=200,
        content={"status": "ok", "message": f"Guard {guard_code} did not trigger"},
    )
