"""HTTP routes for RM Final Actions and the "Replacement Slip - A/c Actions" (change plan
2026-11-12 Phase 7; AMD-16, AMD-17; DEC-41; G-21). No SQL here (rule g)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.core.db import UowDep
from app.core.idempotency import IdempotencyKeyDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.final_actions.schemas import (
    AcSlipPrintOut,
    FinalActionsState,
    FinaliseFinalActionsIn,
    ManagementApprovalRequestIn,
    SaveFinalActionsIn,
    StoreAnalysisGsOut,
    StoreAnalysisQueueRowOut,
    StoreAnalysisSubmitIn,
)
from app.modules.final_actions.service import FinalActionsService, StoreAnalysisService
from app.shared.storage import StorageService, get_storage

router = APIRouter(prefix="/gs/{gs_id}/final-actions", tags=["final-actions"])
# DEC-69 (Phase P9): analysis by the Intermediate Store user.
store_analysis_router = APIRouter(prefix="/store-analysis", tags=["store-analysis"])

ViewUser = Annotated[CurrentUser, Depends(require("final_actions", "view"))]
EditUser = Annotated[CurrentUser, Depends(require("final_actions", "edit"))]
ApproveUser = Annotated[CurrentUser, Depends(require("final_actions", "approve"))]
ExportUser = Annotated[CurrentUser, Depends(require("final_actions", "export"))]
StorageDep = Annotated[StorageService, Depends(get_storage)]
AnalysisViewUser = Annotated[CurrentUser, Depends(require("store_analysis", "view"))]
AnalysisUser = Annotated[CurrentUser, Depends(require("store_analysis", "create"))]


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


@store_analysis_router.get("/queue", response_model=list[StoreAnalysisQueueRowOut])
def get_store_analysis_queue(
    user: AnalysisViewUser,
    uow: UowDep,
    pending_only: bool = Query(default=True),
) -> list[StoreAnalysisQueueRowOut]:
    """DEC-69: goods slips in the store analysis stage with each store's analysis state. A store
    user sees only its own stores; `pending_only` keeps the rows its store may submit now."""
    return StoreAnalysisService(uow).queue(user, pending_only=pending_only)


@store_analysis_router.get("/gs/{gs_id}", response_model=StoreAnalysisGsOut)
def get_store_analysis_gs(gs_id: UUID, user: AnalysisViewUser, uow: UowDep) -> StoreAnalysisGsOut:
    """DEC-69: per item + current condition of every store: qty to decide, the store options
    (Dispatch New / Dispatch Repaired / Not Allowed), decisions and the stores' progress."""
    return StoreAnalysisService(uow).get_gs(user, gs_id)


@store_analysis_router.post("/gs/{gs_id}/submit", response_model=StoreAnalysisGsOut)
def submit_store_analysis(
    gs_id: UUID,
    payload: StoreAnalysisSubmitIn,
    user: AnalysisUser,
    uow: UowDep,
    idem: IdempotencyKeyDep,
) -> JSONResponse:
    """DEC-69 / G-21: submit the store's decisions for its part of the GS (every item + condition
    exactly; Issue CN and Pending are refused). The last store moves the GS to
    ANALYSIS_COMPLETED. `Idempotency-Key` required (G-16)."""
    return StoreAnalysisService(uow).submit(user, gs_id, payload, idem).to_response()


@store_analysis_router.post("/gs/{gs_id}/management-approval", response_model=StoreAnalysisGsOut)
def request_management_approval(
    gs_id: UUID,
    payload: ManagementApprovalRequestIn,
    user: AnalysisUser,
    uow: UowDep,
    idem: IdempotencyKeyDep,
) -> JSONResponse:
    """DEC-69 (target flow step 9): a store user sends the GS for Management approval with a
    reason (one open request per GS; Management resolves it, P10). `Idempotency-Key` required."""
    return StoreAnalysisService(uow).request_approval(user, gs_id, payload, idem).to_response()
