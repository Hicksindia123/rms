"""Custody transfer engine & Step-4 handover HTTP API (prompt P3-01). HTTP, auth, Pydantic I/O only.

Stock-moving commands require an `Idempotency-Key` header (G-16); a replay returns the original
response with `Idempotency-Replayed: true`.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse

from app.core.db import UowDep
from app.core.idempotency import IdempotencyKeyDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.custody.schemas import (
    AcceptIn,
    ApproveAdjustmentIn,
    CancelIn,
    ClassifyIn,
    ClassifyOut,
    HandoverIn,
    HandoverPreviewOut,
    InitiateIn,
    LookupsOut,
    ReconcileIn,
    StoreStockOut,
    TransferDetailOut,
    TransferNoteOut,
    TransferPage,
)
from app.modules.custody.service import CustodyService

router = APIRouter(tags=["custody"])


def get_service(uow: UowDep) -> CustodyService:
    return CustodyService(uow)


ServiceDep = Annotated[CustodyService, Depends(get_service)]
ViewUser = Annotated[CurrentUser, Depends(require("custody", "view"))]
CreateUser = Annotated[CurrentUser, Depends(require("custody", "create"))]
ApproveUser = Annotated[CurrentUser, Depends(require("custody", "approve"))]
InventoryEditUser = Annotated[CurrentUser, Depends(require("inventory", "edit"))]


@router.get("/custody/lookups", response_model=LookupsOut)
def lookups(user: ViewUser, service: ServiceDep) -> LookupsOut:
    """Acceptance (DD r45-r46) and mode (DD r44) options from the published forms, resolution
    options and the blind-count setting."""
    return service.lookups(user)


@router.get("/custody/transfers", response_model=TransferPage)
def list_transfers(
    user: ViewUser,
    service: ServiceDep,
    status_: Annotated[str | None, Query(alias="status", max_length=20)] = None,
    from_location: Annotated[str | None, Query(max_length=60)] = None,
    to_location: Annotated[str | None, Query(max_length=60)] = None,
    gs_id: UUID | None = None,
    mine_to_accept: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> TransferPage:
    return service.list_transfers(
        user,
        status=status_,
        from_location_code=from_location,
        to_location_code=to_location,
        gs_id=gs_id,
        mine_to_accept=mine_to_accept,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/custody/transfers",
    response_model=TransferDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def initiate(
    payload: InitiateIn,
    user: CreateUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """Phase 1 (G-09): the source custodian sends lots; the quantities move to TRANSIT.
    Pending (BP) lots → 422 G-08."""
    return service.initiate(user, perms, payload, idem).to_response()


@router.get("/custody/transfers/{transfer_id}", response_model=TransferDetailOut)
def detail(
    transfer_id: UUID, user: ViewUser, perms: EffectivePermissionsDep, service: ServiceDep
) -> TransferDetailOut:
    return service.detail(user, perms, transfer_id)


@router.post("/custody/transfers/{transfer_id}/accept", response_model=TransferDetailOut)
def accept(
    transfer_id: UUID,
    payload: AcceptIn,
    user: ApproveUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """Phase 2 (BR-21): ACCEPTED_VERIFIED when every count matches, else DISCREPANCY (frozen)."""
    return service.accept(user, perms, transfer_id, payload, idem).to_response()


@router.post("/custody/transfers/{transfer_id}/reconcile", response_model=TransferDetailOut)
def reconcile(
    transfer_id: UUID,
    payload: ReconcileIn,
    user: ViewUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """Sign a resolution (initiator + receiver) or, with `override`, apply it as the RM."""
    return service.reconcile(user, perms, transfer_id, payload, idem).to_response()


@router.post("/custody/transfers/{transfer_id}/reconcile/approve", response_model=TransferDetailOut)
def approve_adjustment(
    transfer_id: UUID,
    payload: ApproveAdjustmentIn,
    user: ApproveUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """RM approval (with reason) of a signed resolution that adjusts stock (loss / excess)."""
    return service.approve(user, perms, transfer_id, payload, idem).to_response()


@router.post("/custody/transfers/{transfer_id}/cancel", response_model=TransferDetailOut)
def cancel(
    transfer_id: UUID,
    payload: CancelIn,
    user: CreateUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """The initiator withdraws an uncounted transfer; the stock returns to the source."""
    return service.cancel(user, perms, transfer_id, payload, idem).to_response()


@router.get("/custody/transfers/{transfer_id}/transfer-note", response_model=TransferNoteOut)
def transfer_note(
    transfer_id: UUID, user: ViewUser, perms: EffectivePermissionsDep, service: ServiceDep
) -> TransferNoteOut:
    """Transfer Note preview (TRANSFER_NOTE template, print count so far; no side effect)."""
    return service.transfer_note(user, perms, transfer_id)


@router.post("/custody/transfers/{transfer_id}/transfer-note/print", response_model=TransferNoteOut)
def print_transfer_note(
    transfer_id: UUID, user: ViewUser, perms: EffectivePermissionsDep, service: ServiceDep
) -> TransferNoteOut:
    """Log a print of the Transfer Note (print_logs) and return it with the reprint watermark."""
    return service.print_transfer_note(user, perms, transfer_id)


@router.get("/gs/{gs_id}/handover", response_model=HandoverPreviewOut)
def handover_preview(
    gs_id: UUID, user: ViewUser, perms: EffectivePermissionsDep, service: ServiceDep
) -> HandoverPreviewOut:
    """Step-4: eligible INWARD_STAGING lots and everything held back, with the reason."""
    return service.handover_preview(user, perms, gs_id)


@router.post(
    "/gs/{gs_id}/handover",
    response_model=TransferDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def handover(
    gs_id: UUID,
    payload: HandoverIn,
    user: CreateUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """Step-4 handover Aman → Sahil (INWARD_STAGING → INTERMEDIATE_STORE via TRANSIT). Takes over
    an approved CSR's "forward with packaging" proposal."""
    return service.handover(user, perms, gs_id, payload, idem).to_response()


@router.get("/custody/intermediate-store/stock", response_model=StoreStockOut)
def intermediate_store_stock(
    user: ViewUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
    gs_id: UUID | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    condition_class: Annotated[str | None, Query(max_length=40)] = None,
    routing_hint: Annotated[str | None, Query(max_length=40)] = None,
) -> StoreStockOut:
    return service.intermediate_store_stock(
        user, perms, gs_id=gs_id, q=q, condition_class=condition_class, routing_hint=routing_hint
    )


@router.post(
    "/custody/lots/{lot_id}/classify",
    response_model=ClassifyOut,
    status_code=status.HTTP_201_CREATED,
)
def classify(
    lot_id: UUID,
    payload: ClassifyIn,
    user: InventoryEditUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """DEC-14: a SELLABLE-routed lot is classified Functional Good in the Intermediate Store."""
    return service.classify(user, perms, lot_id, payload, idem).to_response()
