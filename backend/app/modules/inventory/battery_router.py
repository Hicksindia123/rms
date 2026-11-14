"""P3-02 Battery router (master plan §2.2 Stage-3, DEC-15, BR-24, G-10)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.core.db import UowDep
from app.core.idempotency import IdempotencyKeyDep, run_idempotent
from app.core.permissions import require
from app.core.security import CurrentUser, get_current_user
from app.modules.inventory import battery_service as svc
from app.modules.inventory.battery_schemas import (
    BatteryAdjustmentApproveIn,
    BatteryAdjustmentIn,
    BatteryAdjustmentOut,
    BatteryAdjustmentRejectIn,
    BatteryBalanceOut,
    BatteryMovementOut,
    BatteryReceiptIn,
    BatteryReceiptOut,
    BatteryTypeOut,
)

# Every read needs an authenticated user with inventory.view (§9); P3-08 found them open.
ViewDep = Depends(require("inventory", "view"))

router = APIRouter(prefix="/inventory/batteries", tags=["inventory:batteries"])


@router.get("/types", response_model=list[BatteryTypeOut], dependencies=[ViewDep])
def list_types(uow: UowDep) -> list[BatteryTypeOut]:
    with uow.transaction() as session:
        return svc.list_battery_types(session)


@router.get("/balances", response_model=list[BatteryBalanceOut], dependencies=[ViewDep])
def get_balances(uow: UowDep) -> list[BatteryBalanceOut]:
    with uow.transaction() as session:
        return svc.get_battery_balances(session)


@router.get("/movements", response_model=list[BatteryMovementOut], dependencies=[ViewDep])
def list_movements(uow: UowDep) -> list[BatteryMovementOut]:
    with uow.transaction() as session:
        return svc.list_battery_movements(session)


@router.post("/receipts", response_model=BatteryReceiptOut, status_code=201)
def receive_batteries(
    payload: BatteryReceiptIn,
    uow: UowDep,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    idem: IdempotencyKeyDep,
) -> JSONResponse:
    with uow.transaction(user.id) as session:
        result = run_idempotent(
            session,
            idem,
            user.id,
            lambda: (
                201,
                svc.receive_batteries(
                    session, user=user, payload=payload, idempotency_key=idem.key
                ),
            ),
        )
    return result.to_response()


@router.get("/adjustments", response_model=list[BatteryAdjustmentOut], dependencies=[ViewDep])
def list_adjustments(
    uow: UowDep,
    status: Annotated[str | None, Query()] = None,
) -> list[BatteryAdjustmentOut]:
    with uow.transaction() as session:
        return svc.list_adjustments(session, status=status)


@router.post("/adjustments", response_model=BatteryAdjustmentOut, status_code=201)
def request_adjustment(
    payload: BatteryAdjustmentIn,
    uow: UowDep,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> BatteryAdjustmentOut:
    with uow.transaction(user.id) as session:
        return svc.request_adjustment(session, user=user, payload=payload)


@router.post("/adjustments/{id}/approve", response_model=BatteryAdjustmentOut)
def approve_adjustment(
    id: UUID,
    payload: BatteryAdjustmentApproveIn,
    uow: UowDep,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    idem: IdempotencyKeyDep,
) -> JSONResponse:
    with uow.transaction(user.id) as session:
        result = run_idempotent(
            session,
            idem,
            user.id,
            lambda: (
                200,
                svc.approve_adjustment(
                    session,
                    user=user,
                    adjustment_id=id,
                    payload=payload,
                    idempotency_key=idem.key,
                ),
            ),
        )
    return result.to_response()


@router.post("/adjustments/{id}/reject", response_model=BatteryAdjustmentOut)
def reject_adjustment(
    id: UUID,
    payload: BatteryAdjustmentRejectIn,
    uow: UowDep,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> BatteryAdjustmentOut:
    with uow.transaction(user.id) as session:
        return svc.reject_adjustment(
            session,
            user=user,
            adjustment_id=id,
            payload=payload,
        )
