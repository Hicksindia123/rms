"""Stage-4 Dismantling & Parts Recovery API routers (BR-26..BR-29, G-11, DEC-18, DEC-19, DEC-11)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.core.db import UowDep
from app.core.idempotency import IdempotencyKeyDep, run_idempotent
from app.core.permissions import require
from app.core.security import CurrentUser, get_current_user
from app.modules.dismantling import service as svc
from app.modules.dismantling.schemas import (
    DismantleBatchCreateIn,
    DismantleBatchDetailOut,
    DismantleBatchSummaryOut,
    DismantleQueueResponse,
    DismantleRecoveryIn,
    PcbModelIn,
    PcbModelOut,
    PcbSupplierIn,
    PcbSupplierOut,
    ScrapDisposeIn,
    ScrapFromLotIn,
    ScrapRecordOut,
    StorageContainerOut,
)

# Every read needs an authenticated user with dismantling.view (§9); P3-08 found them open.
ViewDep = Depends(require("dismantling", "view"))

router = APIRouter(prefix="/dismantling", tags=["dismantling"])
scrap_router = APIRouter(prefix="/scrap", tags=["scrap"])


# -----------------------------------------------------------------------------
# Dismantling Queue & Batches
# -----------------------------------------------------------------------------


@router.get("/queue", response_model=DismantleQueueResponse, dependencies=[ViewDep])
def get_dismantling_queue(uow: UowDep) -> DismantleQueueResponse:
    with uow.transaction() as session:
        return svc.get_queue(session)


@router.get("/batches", response_model=list[DismantleBatchSummaryOut], dependencies=[ViewDep])
def list_batches(
    uow: UowDep,
    status: Annotated[str | None, Query()] = None,
    technician_profile_id: Annotated[UUID | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[DismantleBatchSummaryOut]:
    with uow.transaction() as session:
        return svc.list_batches(
            session,
            status=status,
            technician_profile_id=technician_profile_id,
            page=page,
            page_size=page_size,
        )


@router.post("/batches", response_model=DismantleBatchDetailOut, status_code=201)
def create_batch(
    payload: DismantleBatchCreateIn,
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
                svc.create_batch(
                    session,
                    user=user,
                    payload=payload,
                    idempotency_key=idem.key,
                ),
            ),
        )
    return result.to_response()


@router.get("/batches/{id}", response_model=DismantleBatchDetailOut, dependencies=[ViewDep])
def get_batch(id: UUID, uow: UowDep) -> DismantleBatchDetailOut:
    with uow.transaction() as session:
        return svc.get_batch_detail(session, id)


@router.post("/batches/{id}/recover", response_model=DismantleBatchDetailOut)
def recover_batch(
    id: UUID,
    payload: DismantleRecoveryIn,
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
                svc.recover_batch(
                    session,
                    user=user,
                    batch_id=id,
                    payload=payload,
                    idempotency_key=idem.key,
                ),
            ),
        )
    return result.to_response()


# -----------------------------------------------------------------------------
# Storage Containers & Masters Lookups
# -----------------------------------------------------------------------------


@router.get("/containers", response_model=list[StorageContainerOut], dependencies=[ViewDep])
def list_containers(
    uow: UowDep,
    storage_method: Annotated[str | None, Query()] = None,
    part_type: Annotated[str | None, Query()] = None,
) -> list[StorageContainerOut]:
    with uow.transaction() as session:
        return svc.list_containers(session, storage_method=storage_method, part_type=part_type)


@router.get("/pcb-models", response_model=list[PcbModelOut], dependencies=[ViewDep])
def list_pcb_models(uow: UowDep) -> list[PcbModelOut]:
    with uow.transaction() as session:
        return svc.list_pcb_models(session)


@router.post("/pcb-models", response_model=PcbModelOut, status_code=201)
def create_pcb_model(
    payload: PcbModelIn,
    uow: UowDep,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> PcbModelOut:
    with uow.transaction(user.id) as session:
        return svc.create_pcb_model(session, user=user, payload=payload)


@router.get("/pcb-suppliers", response_model=list[PcbSupplierOut], dependencies=[ViewDep])
def list_pcb_suppliers(uow: UowDep) -> list[PcbSupplierOut]:
    with uow.transaction() as session:
        return svc.list_pcb_suppliers(session)


@router.post("/pcb-suppliers", response_model=PcbSupplierOut, status_code=201)
def create_pcb_supplier(
    payload: PcbSupplierIn,
    uow: UowDep,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> PcbSupplierOut:
    with uow.transaction(user.id) as session:
        return svc.create_pcb_supplier(session, user=user, payload=payload)


# -----------------------------------------------------------------------------
# Scrap Register & Disposal
# -----------------------------------------------------------------------------


@scrap_router.get("", response_model=list[ScrapRecordOut], dependencies=[ViewDep])
def list_scrap(
    uow: UowDep,
    batch_id: Annotated[UUID | None, Query()] = None,
    disposal_status: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ScrapRecordOut]:
    with uow.transaction() as session:
        return svc.list_scrap_records(
            session,
            batch_id=batch_id,
            disposal_status=disposal_status,
            page=page,
            page_size=page_size,
        )


@scrap_router.post("/from-lot", response_model=ScrapRecordOut, status_code=201)
def mark_lot_for_disposal(
    payload: ScrapFromLotIn,
    uow: UowDep,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    idem: IdempotencyKeyDep,
) -> JSONResponse:
    """DEC-11 / DEC-18: mark quarantined hazard or non-dismantleable stock as scrap."""
    with uow.transaction(user.id) as session:
        result = run_idempotent(
            session,
            idem,
            user.id,
            lambda: (201, svc.mark_lot_for_disposal(session, user=user, payload=payload)),
        )
    return result.to_response()


@scrap_router.post("/{id}/dispose", response_model=ScrapRecordOut)
def dispose_scrap(
    id: UUID,
    payload: ScrapDisposeIn,
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
                svc.dispose_scrap(
                    session,
                    user=user,
                    scrap_id=id,
                    payload=payload,
                    idempotency_key=idem.key,
                ),
            ),
        )
    return result.to_response()
