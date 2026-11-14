"""FastAPI router for RM item-wise actions and Replacement Slip.

Master plan references: WF r6, BR-19, BR-20, G-08, DEC-12, DEC-13, DEC-33.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.db import UowDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.rm_actions.schemas import (
    ReplacementSlipResponse,
    ResolutionBoardResponse,
    RmActionsResponse,
    SaveRmActionsRequest,
)
from app.modules.rm_actions.service import RmActionsService

router = APIRouter(tags=["rm-actions"])

ViewUser = Annotated[CurrentUser, Depends(require("goods_slips", "view"))]
EditUser = Annotated[CurrentUser, Depends(require("goods_slips", "edit"))]


@router.get(
    "/gs/{id}/rm-actions",
    response_model=RmActionsResponse,
    summary="Get RM item-wise actions segregation state for a goods slip",
)
def get_rm_actions(
    id: UUID,
    user: ViewUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> RmActionsResponse:
    service = RmActionsService(uow)
    return service.get_rm_actions_data(id, user, perms)


@router.put(
    "/gs/{id}/rm-actions",
    response_model=RmActionsResponse,
    summary="Save RM item-wise actions segregation revision",
)
def save_rm_actions(
    id: UUID,
    payload: SaveRmActionsRequest,
    user: EditUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> RmActionsResponse:
    service = RmActionsService(uow)
    return service.save_rm_actions(id, payload, user, perms)


@router.post(
    "/gs/{id}/rm-actions/finalise",
    response_model=RmActionsResponse,
    summary="Finalise RM actions segregation and advance to Stage-2 Handover",
)
def finalise_rm_actions(
    id: UUID,
    user: EditUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> RmActionsResponse:
    service = RmActionsService(uow)
    return service.finalise_rm_actions(id, user, perms)


@router.get(
    "/gs/{id}/replacement-slip",
    response_model=ReplacementSlipResponse,
    summary="Get Replacement Slip print data (logged as document print)",
)
def get_replacement_slip(
    id: UUID,
    user: ViewUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> ReplacementSlipResponse:
    service = RmActionsService(uow)
    return service.get_replacement_slip(id, user, perms)


@router.get(
    "/gs/{id}/resolution-board",
    response_model=ResolutionBoardResponse,
    summary="Get RM Resolution Board comparing planned actions with actual outcomes",
)
def get_resolution_board(
    id: UUID,
    user: ViewUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> ResolutionBoardResponse:
    service = RmActionsService(uow)
    return service.get_resolution_board(id, user, perms)
