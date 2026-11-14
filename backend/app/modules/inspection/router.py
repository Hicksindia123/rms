"""Step-3 Inspection HTTP API (prompt P2-05)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header

from app.core.db import UowDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.inspection import service
from app.modules.inspection.schemas import (
    FinaliseLineOut,
    InspectionDraftIn,
    InspectionGsOut,
    InspectionLineOut,
    ReopenIn,
    ReopenOut,
)

router = APIRouter(tags=["inspection"])

ViewUser = Annotated[CurrentUser, Depends(require("goods_slips", "view"))]
EditUser = Annotated[CurrentUser, Depends(require("goods_slips", "edit"))]
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key")]


@router.get("/gs/{gs_id}/inspection", response_model=InspectionGsOut)
def get_gs_inspection(
    gs_id: UUID,
    user: ViewUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> InspectionGsOut:
    """Lines with category, condition options, existing drafts, and totals."""
    with uow.transaction() as session:
        return service.get_gs_inspection(session, gs_id, user, perms)


@router.put("/gs-items/{gs_item_id}/inspection", response_model=InspectionLineOut)
def save_inspection_draft(
    gs_item_id: UUID,
    payload: InspectionDraftIn,
    user: EditUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> InspectionLineOut:
    """Save draft condition grading and extraction quantities (enforces G-06 for EO)."""
    with uow.transaction() as session:
        return service.save_draft_inspection(session, gs_item_id, payload, user, perms)


@router.post("/gs-items/{gs_item_id}/inspection/finalise", response_model=FinaliseLineOut)
def finalise_inspection(
    gs_item_id: UUID,
    user: EditUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
    idempotency_key: IdemKey = None,
) -> FinaliseLineOut:
    """Finalise line grading: reclassifies stock, moves hazard/rejected lots, creates rejections,
    and advances workflow to RM_REVIEW when all lines are finalised (enforces G-06 and G-07)."""
    with uow.transaction() as session:
        return service.finalise_line_inspection(
            session, gs_item_id, user, perms, idempotency_key=idempotency_key
        )


@router.post("/gs/{gs_id}/inspection/finalise-all", response_model=InspectionGsOut)
def finalise_all_lines(
    gs_id: UUID,
    user: EditUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
    idempotency_key: IdemKey = None,
) -> InspectionGsOut:
    """Finalise all draft lines for a goods slip in a single transaction."""
    with uow.transaction() as session:
        return service.finalise_all(session, gs_id, user, perms, idempotency_key=idempotency_key)


@router.post("/gs-items/{gs_item_id}/inspection/reopen", response_model=ReopenOut)
def reopen_inspection(
    gs_item_id: UUID,
    payload: ReopenIn,
    user: EditUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> ReopenOut:
    """Reopen a finalised inspection (RM permission, reason required): reverses movements."""
    with uow.transaction() as session:
        return service.reopen_inspection(session, gs_item_id, payload, user, perms)
