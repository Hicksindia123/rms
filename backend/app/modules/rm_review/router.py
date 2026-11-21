"""RM Review HTTP router (Change plan 2026-11-12 Phase 5, AMD-12, AMD-13, G-19)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.db import UowDep
from app.core.idempotency import IdempotencyKeyDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.rm_review.schemas import (
    RmApproveIn,
    RmApproveOut,
    RmReviewDataOut,
    RmSendBackIn,
)
from app.modules.rm_review.service import RmReviewService

router = APIRouter(tags=["rm-review"])


def get_service(uow: UowDep) -> RmReviewService:
    return RmReviewService(uow)


ServiceDep = Annotated[RmReviewService, Depends(get_service)]
ViewUser = Annotated[CurrentUser, Depends(require("itemization", "view"))]
ApproveUser = Annotated[CurrentUser, Depends(require("itemization", "approve"))]


@router.get("/gs/{gs_id}/rm-review", response_model=RmReviewDataOut)
def get_rm_review_data(
    gs_id: UUID,
    user: ViewUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
) -> RmReviewDataOut:
    """AMD-12: Fetch one-screen GS at a glance for RM review
    (header, docs, videos, items with buckets).
    """
    return service.get_review_data(user, perms, gs_id)


# DEC-64 (e), Q9: the RM's edits in review (DEC-54: edit qty / split, add / remove line, change
# product) are retired. GSs still in RM_REVIEW (legacy) keep the read view, send back and approve.
# Changes after the categorisation lock are made by Super Admin / Management
# (itemization router, /gs/{id}/locked/items).


@router.post("/gs/{gs_id}/rm-send-back")
def rm_send_back(
    gs_id: UUID,
    payload: RmSendBackIn,
    user: ApproveUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """AMD-12: RM sends GS back to categorisation with a remark."""
    return service.send_back(user, perms, gs_id, payload, idem).to_response()


@router.post("/gs/{gs_id}/rm-approve", response_model=RmApproveOut)
def rm_approve(
    gs_id: UUID,
    payload: RmApproveIn,
    user: ApproveUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """AMD-13: RM approves GS, auto-generating custody transfer slip to Intermediate Store."""
    return service.approve(user, perms, gs_id, payload, idem).to_response()
