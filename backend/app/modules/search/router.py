"""Router for Global Search (P4-04)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.db import UowDep
from app.core.permissions import EffectivePermissions, get_effective_permissions
from app.core.security import CurrentUserDep
from app.modules.search.schemas import SearchResponse
from app.modules.search.service import SearchService

router = APIRouter(prefix="/search", tags=["search"])


def get_service(uow: UowDep) -> SearchService:
    return SearchService(uow)


ServiceDep = Annotated[SearchService, Depends(get_service)]
PermsDep = Annotated[EffectivePermissions, Depends(get_effective_permissions)]


@router.get("", response_model=SearchResponse)
def global_search(
    user: CurrentUserDep,
    perms: PermsDep,
    service: ServiceDep,
    q: Annotated[
        str, Query(min_length=1, max_length=120, description="Search query string or barcode")
    ],
    limit: Annotated[int, Query(ge=1, le=25, description="Maximum matches per category group")] = 5,
) -> SearchResponse:
    """Execute global search across Goods Slips, parties, documents, vouchers and containers."""
    return service.search(user, perms, q, limit=limit)
