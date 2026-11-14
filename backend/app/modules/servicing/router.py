"""P3-02 Servicing router (master plan §2.2 Stage-3, BR-23..BR-25, G-10, DEC-14..DEC-17, DEC-34)."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.core.db import UowDep
from app.core.idempotency import IdempotencyKeyDep, run_idempotent
from app.core.permissions import require
from app.core.security import CurrentUser, get_current_user
from app.modules.servicing import service as svc
from app.modules.servicing.schemas import (
    AllotBatchIn,
    BatchDetailOut,
    BatchSummaryOut,
    BatteryReconciliationOut,
    IntermediateLotOut,
    ReceiveBatchIn,
    TechnicianOut,
)

# Every read needs an authenticated user with servicing.view (§9); P3-08 found them open.
ViewDep = Depends(require("servicing", "view"))

router = APIRouter(prefix="/servicing", tags=["servicing"])


@router.get("/technicians", response_model=list[TechnicianOut], dependencies=[ViewDep])
def list_technicians(uow: UowDep) -> list[TechnicianOut]:
    with uow.transaction() as session:
        return svc.list_technicians(session)


@router.get("/intermediate-lots", response_model=list[IntermediateLotOut], dependencies=[ViewDep])
def get_intermediate_lots(uow: UowDep) -> list[IntermediateLotOut]:
    with uow.transaction() as session:
        return svc.get_intermediate_lots(session)


@router.get("/batches", response_model=list[BatchSummaryOut], dependencies=[ViewDep])
def list_batches(
    uow: UowDep,
    status: Annotated[str | None, Query()] = None,
    technician_id: Annotated[UUID | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[BatchSummaryOut]:
    with uow.transaction() as session:
        return svc.list_batches(
            session,
            status=status,
            technician_id=technician_id,
            page=page,
            page_size=page_size,
        )


@router.get("/batches/{id}", response_model=BatchDetailOut, dependencies=[ViewDep])
def get_batch(id: UUID, uow: UowDep) -> BatchDetailOut:
    with uow.transaction() as session:
        return svc.get_batch_detail(session, id)


@router.post("/batches", response_model=BatchDetailOut, status_code=201)
def allot_batch(
    payload: AllotBatchIn,
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
                svc.allot_batch(
                    session,
                    user=user,
                    payload=payload,
                    idempotency_key=idem.key,
                ),
            ),
        )
    return result.to_response()


@router.post("/batches/{id}/receive", response_model=BatchDetailOut)
def receive_batch(
    id: UUID,
    payload: ReceiveBatchIn,
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
                svc.receive_batch(
                    session,
                    user=user,
                    batch_id=id,
                    payload=payload,
                    idempotency_key=idem.key,
                ),
            ),
        )
    return result.to_response()


@router.get(
    "/battery-reconciliation",
    response_model=BatteryReconciliationOut,
    # Battery stock report (BR-24) shown on the Spare Parts Manager's Battery Stock page.
    dependencies=[Depends(require("inventory", "view"))],
)
def get_battery_reconciliation(
    uow: UowDep,
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
) -> BatteryReconciliationOut:
    with uow.transaction() as session:
        return svc.get_battery_reconciliation(session, from_date=from_date, to_date=to_date)
