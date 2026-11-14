"""FastAPI router for Step-6 Store Issues (P3-05).

Master plan references: BR-19, BR-31, DEC-21, G-04.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.db import UowDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.store_issue.schemas import (
    StoreIssueCandidateLotOut,
    StoreIssueCreateRequest,
    StoreIssueOut,
    StoreIssuePrintResponse,
)
from app.modules.store_issue.service import StoreIssueService

router = APIRouter(prefix="/store-issues", tags=["store-issue"])

ViewUser = Annotated[CurrentUser, Depends(require("inventory", "view"))]
EditUser = Annotated[CurrentUser, Depends(require("inventory", "edit"))]


@router.get(
    "/candidate-lots",
    response_model=list[StoreIssueCandidateLotOut],
    summary="Get candidate functional lots in Intermediate Store available for Main Store issue",
)
def get_candidate_lots(
    user: ViewUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> list[StoreIssueCandidateLotOut]:
    service = StoreIssueService(uow)
    return service.get_candidate_lots(user, perms)


@router.post(
    "",
    response_model=StoreIssueOut,
    summary="Issue functional stock from Intermediate Store to Main Store",
)
def create_store_issue(
    payload: StoreIssueCreateRequest,
    user: EditUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> StoreIssueOut:
    service = StoreIssueService(uow)
    return service.create_store_issue(payload, user, perms)


@router.get(
    "",
    response_model=list[StoreIssueOut],
    summary="List store issues",
)
def list_store_issues(
    user: ViewUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[StoreIssueOut]:
    service = StoreIssueService(uow)
    return service.list_store_issues(
        status=status, limit=limit, offset=offset, user=user, perms=perms
    )


@router.get(
    "/{id}",
    response_model=StoreIssueOut,
    summary="Get store issue by ID",
)
def get_store_issue(
    id: UUID,
    user: ViewUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> StoreIssueOut:
    service = StoreIssueService(uow)
    return service.get_store_issue(id, user, perms)


@router.post(
    "/{id}/acknowledge",
    response_model=StoreIssueOut,
    summary="Acknowledge receipt of store issue by Main Store",
)
def acknowledge_store_issue(
    id: UUID,
    user: EditUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> StoreIssueOut:
    service = StoreIssueService(uow)
    return service.acknowledge_store_issue(id, user, perms)


@router.get(
    "/{id}/print",
    response_model=StoreIssuePrintResponse,
    summary="Get printable Store Issue note data",
)
def get_store_issue_print_data(
    id: UUID,
    user: ViewUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> StoreIssuePrintResponse:
    service = StoreIssueService(uow)
    return service.get_print_data(id, user, perms)
