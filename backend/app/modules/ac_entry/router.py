"""HTTP routes for the Accounts entry and the Dispatch Slip (change plan 2026-11-12 Phase 8;
AMD-18, AMD-19; DEC-26; G-22). No SQL here (rule g)."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.core.db import UowDep
from app.core.idempotency import IdempotencyKeyDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.ac_entry.schemas import (
    AcEntryQueueItem,
    AcEntryState,
    CompleteAcEntryIn,
    DispatchIn,
    DispatchSlipOut,
    DispatchSlipPrintOut,
    SaveAcEntryIn,
)
from app.modules.ac_entry.service import AcEntryService, DispatchSlipService
from app.shared.storage import StorageService, get_storage

router = APIRouter(prefix="/ac-entry", tags=["ac-entry"])
dispatch_slips_router = APIRouter(prefix="/dispatch-slips", tags=["dispatch-slips"])

ViewUser = Annotated[CurrentUser, Depends(require("ac_entry", "view"))]
EditUser = Annotated[CurrentUser, Depends(require("ac_entry", "edit"))]
ExportUser = Annotated[CurrentUser, Depends(require("ac_entry", "export"))]
DispatchViewUser = Annotated[CurrentUser, Depends(require("dispatch", "view"))]
DispatchUser = Annotated[CurrentUser, Depends(require("dispatch", "create"))]
StorageDep = Annotated[StorageService, Depends(get_storage)]


@router.get("/queue", response_model=list[AcEntryQueueItem])
def get_queue(
    user: ViewUser,
    uow: UowDep,
    status: Annotated[Literal["pending", "completed", "all"], Query()] = "pending",
) -> list[AcEntryQueueItem]:
    """AMD-18: goods slips with a CURRENT A/c Actions slip and their Accounts progress."""
    completed = {"pending": False, "completed": True, "all": None}[status]
    return AcEntryService(uow).queue(user, completed=completed)


@router.get("/gs/{gs_id}", response_model=AcEntryState)
def get_entry(
    gs_id: UUID, user: ViewUser, perms: EffectivePermissionsDep, uow: UowDep
) -> AcEntryState:
    """Per action line: the fields its flags require (AMD-18), entered values and completeness."""
    return AcEntryService(uow).get_state(gs_id, user, perms)


@router.put("/gs/{gs_id}/lines", response_model=AcEntryState)
def save_entry(
    gs_id: UUID,
    payload: SaveAcEntryIn,
    user: EditUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
    idem: IdempotencyKeyDep,
) -> JSONResponse:
    """AMD-18 / G-22: save CN / Challan data (partial saves allowed). `Idempotency-Key` required
    (G-16)."""
    return AcEntryService(uow).save(gs_id, payload, user, perms, idem).to_response()


@router.post("/gs/{gs_id}/complete", response_model=AcEntryState)
def complete_entry(
    gs_id: UUID,
    payload: CompleteAcEntryIn,
    user: EditUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
    idem: IdempotencyKeyDep,
    storage: StorageDep,
) -> JSONResponse:
    """AMD-19 / G-22: complete the entry; generates the Dispatch Slip PDF when a line ships goods
    and notifies DISPATCH, else hands the goods slip to the closure engine. `Idempotency-Key`
    required (G-16)."""
    return AcEntryService(uow).complete(gs_id, payload, user, perms, idem, storage).to_response()


@dispatch_slips_router.get("", response_model=list[DispatchSlipOut])
def list_dispatch_slips(
    user: DispatchViewUser,
    uow: UowDep,
    status: Annotated[Literal["READY", "DISPATCHED"] | None, Query()] = None,
) -> list[DispatchSlipOut]:
    """AMD-19: Dispatch Slips (READY first)."""
    return DispatchSlipService(uow).list_slips(user, status=status)


@dispatch_slips_router.get("/{slip_id}", response_model=DispatchSlipOut)
def get_dispatch_slip(slip_id: UUID, user: DispatchViewUser, uow: UowDep) -> DispatchSlipOut:
    return DispatchSlipService(uow).get_slip(slip_id, user)


@dispatch_slips_router.post("/{slip_id}/dispatch", response_model=DispatchSlipOut)
def dispatch_slip(
    slip_id: UUID, payload: DispatchIn, user: DispatchUser, uow: UowDep, idem: IdempotencyKeyDep
) -> JSONResponse:
    """AMD-19 / DEC-26: issue the goods (rms_move_stock) and mark the slip dispatched with date,
    transporter and docket / vehicle; the goods slip moves on to closure (G-15).
    `Idempotency-Key` required (G-16)."""
    return DispatchSlipService(uow).dispatch(slip_id, payload, user, idem).to_response()


@dispatch_slips_router.post("/{slip_id}/print", response_model=DispatchSlipPrintOut)
def print_dispatch_slip(
    slip_id: UUID, user: ExportUser, uow: UowDep, storage: StorageDep
) -> DispatchSlipPrintOut:
    """Print / re-print the stored Dispatch Slip PDF (logged in print_logs)."""
    return DispatchSlipService(uow).print_slip(slip_id, user, storage)
