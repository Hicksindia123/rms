"""Closure engine endpoints (P3-07: G-15, BR-38, BR-39, §6.5)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.db import UowDep
from app.core.idempotency import IdempotencyKeyDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.closure.schemas import CloseIn, ClosureStateOut, ReopenIn
from app.modules.closure.service import ClosureService

router = APIRouter(tags=["closure"])

ViewUser = Annotated[CurrentUser, Depends(require("goods_slips", "view"))]


@router.get("/gs/{gs_id}/closure", response_model=ClosureStateOut)
def closure_state(
    gs_id: UUID, user: ViewUser, perms: EffectivePermissionsDep, uow: UowDep
) -> ClosureStateOut:
    """Live closure checklist (pass/fail + explanation + fix link), closure record, lifecycle
    stage durations and the data of the closure certificate."""
    return ClosureService(uow).get_state(user, perms, gs_id)


@router.post("/gs/{gs_id}/close", response_model=ClosureStateOut)
def close_gs(
    gs_id: UUID,
    payload: CloseIn,
    user: ViewUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    uow: UowDep,
) -> JSONResponse:
    """S6_CLOSE (roles: setting `gs_closure_roles`, default RM / Accounts). Re-evaluates the
    checklist under row locks; any failing item → 422 `G-15` with `details.failed_items`."""
    return ClosureService(uow).close(user, perms, gs_id, payload, idem).to_response()


@router.post("/gs/{gs_id}/reopen", response_model=ClosureStateOut)
def reopen_gs(
    gs_id: UUID, payload: ReopenIn, user: ViewUser, perms: EffectivePermissionsDep, uow: UowDep
) -> ClosureStateOut:
    """Super Admin only, with a reason: CLOSED → COMMERCIAL_RESOLUTION (audited)."""
    return ClosureService(uow).reopen(user, perms, gs_id, payload)
