"""FastAPI router for Replacement Dispatch (P3-05).

Master plan references: BR-19, BR-31, BR-32, DEC-26, DEC-33, §8.6.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.db import UowDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.dispatch.schemas import (
    DispatchCandidateLotOut,
    DispatchQueueItemOut,
    ReplacementDispatchCreateRequest,
    ReplacementDispatchOut,
)
from app.modules.dispatch.service import ReplacementDispatchService

router = APIRouter(prefix="/dispatches", tags=["dispatch"])

ViewUser = Annotated[CurrentUser, Depends(require("dispatch", "view"))]
EditUser = Annotated[CurrentUser, Depends(require("dispatch", "create"))]


@router.get(
    "/queue",
    response_model=list[DispatchQueueItemOut],
    summary="Get pending replacement dispatch queue items",
)
def get_dispatch_queue(
    user: ViewUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> list[DispatchQueueItemOut]:
    service = ReplacementDispatchService(uow)
    return service.get_dispatch_queue(user, perms)


@router.get(
    "/candidate-lots",
    response_model=list[DispatchCandidateLotOut],
    summary="Get candidate functional repaired lots available for replacement dispatch",
)
def get_candidate_lots(
    user: ViewUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
    product_id: Annotated[UUID | None, Query()] = None,
    gs_item_id: Annotated[UUID | None, Query()] = None,
) -> list[DispatchCandidateLotOut]:
    service = ReplacementDispatchService(uow)
    return service.get_candidate_lots(
        product_id=product_id, gs_item_id=gs_item_id, user=user, perms=perms
    )


@router.post(
    "",
    response_model=ReplacementDispatchOut,
    summary="Record a replacement dispatch (SEND_NEW or SEND_REPAIRED)",
)
def create_dispatch(
    payload: ReplacementDispatchCreateRequest,
    user: EditUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> ReplacementDispatchOut:
    service = ReplacementDispatchService(uow)
    return service.create_dispatch(payload, user, perms)


@router.get(
    "",
    response_model=list[ReplacementDispatchOut],
    summary="List replacement dispatches",
)
def list_dispatches(
    user: ViewUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
    gs_id: Annotated[UUID | None, Query()] = None,
    dispatch_type: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ReplacementDispatchOut]:
    service = ReplacementDispatchService(uow)
    return service.list_dispatches(
        gs_id=gs_id, dispatch_type=dispatch_type, limit=limit, offset=offset, user=user, perms=perms
    )


@router.get(
    "/{id}",
    response_model=ReplacementDispatchOut,
    summary="Get replacement dispatch details by ID",
)
def get_dispatch(
    id: UUID,
    user: ViewUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> ReplacementDispatchOut:
    service = ReplacementDispatchService(uow)
    return service.get_dispatch(id, user, perms)
