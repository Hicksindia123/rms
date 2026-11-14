"""HTTP routes for RM Final Actions and the "Replacement Slip - A/c Actions" (change plan
2026-11-12 Phase 7; AMD-16, AMD-17; DEC-41; G-21). No SQL here (rule g)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.db import UowDep
from app.core.idempotency import IdempotencyKeyDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.final_actions.schemas import (
    AcSlipPrintOut,
    FinalActionsState,
    FinaliseFinalActionsIn,
    SaveFinalActionsIn,
)
from app.modules.final_actions.service import FinalActionsService
from app.shared.storage import StorageService, get_storage

router = APIRouter(prefix="/gs/{gs_id}/final-actions", tags=["final-actions"])

ViewUser = Annotated[CurrentUser, Depends(require("final_actions", "view"))]
EditUser = Annotated[CurrentUser, Depends(require("final_actions", "edit"))]
ApproveUser = Annotated[CurrentUser, Depends(require("final_actions", "approve"))]
ExportUser = Annotated[CurrentUser, Depends(require("final_actions", "export"))]
StorageDep = Annotated[StorageService, Depends(get_storage)]


@router.get("", response_model=FinalActionsState)
def get_final_actions(
    gs_id: UUID, user: ViewUser, perms: EffectivePermissionsDep, uow: UowDep
) -> FinalActionsState:
    """Per item: counted, at departments, available for action, outcome heads, allowed actions
    (resolved profile), current split, revisions and slip versions (AMD-16 / AMD-17)."""
    return FinalActionsService(uow).get_state(gs_id, user, perms)


@router.put("", response_model=FinalActionsState)
def save_final_actions(
    gs_id: UUID,
    payload: SaveFinalActionsIn,
    user: EditUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
    idem: IdempotencyKeyDep,
) -> JSONResponse:
    """AMD-16 / G-21: save a new revision of the split (Σ action qty = qty available for action).
    Revising finalised actions needs `reason` and supersedes the current slip.
    `Idempotency-Key` required (G-16)."""
    return FinalActionsService(uow).save(gs_id, payload, user, perms, idem).to_response()


@router.post("/finalise", response_model=FinalActionsState)
def finalise_final_actions(
    gs_id: UUID,
    payload: FinaliseFinalActionsIn,
    user: ApproveUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
    idem: IdempotencyKeyDep,
    storage: StorageDep,
) -> JSONResponse:
    """AMD-17 / DEC-41: finalise the actions, generate and store the A/c Actions slip PDF (new
    version) and notify Accounts. `Idempotency-Key` required (G-16)."""
    return (
        FinalActionsService(uow).finalise(gs_id, payload, user, perms, idem, storage).to_response()
    )


@router.post("/slips/{slip_id}/print", response_model=AcSlipPrintOut)
def print_ac_slip(
    gs_id: UUID, slip_id: UUID, user: ExportUser, uow: UowDep, storage: StorageDep
) -> AcSlipPrintOut:
    """AMD-17: print / re-print any slip version. Logged in print_logs; returns a short-lived
    download URL of the stored PDF."""
    return FinalActionsService(uow).print_slip(gs_id, slip_id, user, storage)
