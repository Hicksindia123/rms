"""HTTP routes for Management approval and the e-approval stamp (Phase P10; DEC-70; Q17, Q18).
No SQL here (rule g)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.core.db import UowDep
from app.core.idempotency import IdempotencyKeyDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.management_approval.schemas import (
    ApproveIn,
    ChangesIn,
    ManagementGsOut,
    QueueRowOut,
    StampOut,
    VerifyOut,
)
from app.modules.management_approval.service import ManagementApprovalService

router = APIRouter(prefix="/management-approval", tags=["management-approval"])

ViewUser = Annotated[CurrentUser, Depends(require("management_approval", "view"))]
ApproveUser = Annotated[CurrentUser, Depends(require("management_approval", "approve"))]
# The stamp is shown wherever the goods slip is shown (GS detail page).
GsViewUser = Annotated[CurrentUser, Depends(require("goods_slips", "view"))]


@router.get("/queue", response_model=list[QueueRowOut])
def get_queue(
    user: ViewUser,
    uow: UowDep,
    q: str | None = Query(default=None, max_length=100),
) -> list[QueueRowOut]:
    """Goods slips sent for Management approval (open request first) and every goods slip between
    analysis and Accounts; `q` searches GS no. / party / station."""
    return ManagementApprovalService(uow).queue(user, q)


@router.get("/gs/{gs_id}", response_model=ManagementGsOut)
def get_gs(
    gs_id: UUID, user: ViewUser, perms: EffectivePermissionsDep, uow: UowDep
) -> ManagementGsOut:
    """Every item + condition with its decisions and options (incl. Issue CN), the stores'
    progress, requests, change history, approvals, stamp and the Accounts gate (DEC-70)."""
    return ManagementApprovalService(uow).get_gs(user, perms, gs_id)


@router.post("/gs/{gs_id}/changes", response_model=ManagementGsOut)
def save_changes(
    gs_id: UUID,
    payload: ChangesIn,
    user: ApproveUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
    idem: IdempotencyKeyDep,
) -> JSONResponse:
    """DEC-70: replace the decisions of the listed item + condition groups (any action, incl.
    ISSUE_CN; a reason per change; G-21 totals). One revision, one transaction. Invalidates a
    previous approval. `Idempotency-Key` required (G-16)."""
    return (
        ManagementApprovalService(uow).save_changes(user, perms, gs_id, payload, idem).to_response()
    )


@router.post("/gs/{gs_id}/approve", response_model=ManagementGsOut)
def approve(
    gs_id: UUID,
    payload: ApproveIn,
    user: ApproveUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
    idem: IdempotencyKeyDep,
) -> JSONResponse:
    """DEC-70 (Q17): record the e-approval (DB-computed SHA-256 of the GS lines + decisions,
    append-only) and resolve the open request. `Idempotency-Key` required (G-16)."""
    return ManagementApprovalService(uow).approve(user, perms, gs_id, payload, idem).to_response()


@router.get("/gs/{gs_id}/stamp", response_model=StampOut)
def get_stamp(gs_id: UUID, user: GsViewUser, uow: UowDep) -> StampOut:
    """The latest approval and its state (NONE / VALID / CHANGED) with the stamp text."""
    return ManagementApprovalService(uow).stamp(user, gs_id)


@router.get("/gs/{gs_id}/verify", response_model=VerifyOut)
def verify(gs_id: UUID, user: GsViewUser, uow: UowDep) -> VerifyOut:
    """Recompute the SHA-256 now: VALID (intact and unchanged) or CHANGED."""
    return ManagementApprovalService(uow).verify(user, gs_id)
