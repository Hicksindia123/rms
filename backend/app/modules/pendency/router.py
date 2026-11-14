"""FastAPI router for Pendency register and operations.

Master plan references: WF r7 col K, BR-20, DEC-12, G-08.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.db import UowDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.pendency.schemas import ClearPendencyRequest, PendencyOut
from app.modules.pendency.service import PendencyService

router = APIRouter(tags=["pendency"])

ViewUser = Annotated[CurrentUser, Depends(require("goods_slips", "view"))]
EditUser = Annotated[CurrentUser, Depends(require("goods_slips", "edit"))]


@router.get(
    "/pendencies",
    response_model=list[PendencyOut],
    summary="List pendencies with optional status, goods slip, or date range filters",
)
def list_pendencies(
    user: ViewUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
    status: Annotated[str | None, Query(description="OPEN, CLEARED, or ALL")] = None,
    gs_id: Annotated[UUID | None, Query(description="Filter by goods slip id")] = None,
    from_date: Annotated[date | None, Query(description="Filter from opened date")] = None,
    to_date: Annotated[date | None, Query(description="Filter to opened date")] = None,
) -> list[PendencyOut]:
    service = PendencyService(uow)
    return service.list_pendencies(status, gs_id, from_date, to_date, user, perms)


@router.post(
    "/pendencies/{id}/clear",
    response_model=PendencyOut,
    summary="Clear an open pendency with resolution action and notes",
)
def clear_pendency(
    id: UUID,
    payload: ClearPendencyRequest,
    user: EditUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> PendencyOut:
    service = PendencyService(uow)
    return service.clear_pendency(id, payload, user, perms)
