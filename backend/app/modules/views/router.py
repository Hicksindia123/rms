"""Router for Saved Views (P4-04)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.db import UowDep
from app.core.security import CurrentUserDep
from app.modules.views.schemas import SavedViewIn, SavedViewOut, SavedViewUpdateIn
from app.modules.views.service import SavedViewService

router = APIRouter(prefix="/saved-views", tags=["saved-views"])


def get_service(uow: UowDep) -> SavedViewService:
    return SavedViewService(uow)


ServiceDep = Annotated[SavedViewService, Depends(get_service)]


@router.get("", response_model=list[SavedViewOut])
def list_saved_views(
    user: CurrentUserDep,
    service: ServiceDep,
    view_code: Annotated[str | None, Query(max_length=60)] = None,
    resource_code: Annotated[str | None, Query(max_length=60)] = None,
) -> list[SavedViewOut]:
    """Retrieve saved views configured by the current user."""
    code = view_code or resource_code
    return service.list_views(user, view_code=code)


@router.post("", response_model=SavedViewOut, status_code=status.HTTP_201_CREATED)
def create_saved_view(
    payload: SavedViewIn,
    user: CurrentUserDep,
    service: ServiceDep,
) -> SavedViewOut:
    """Create a new saved view preset for the current user."""
    return service.create_view(user, payload)


@router.put("/{view_id}", response_model=SavedViewOut)
def update_saved_view(
    view_id: UUID,
    payload: SavedViewUpdateIn,
    user: CurrentUserDep,
    service: ServiceDep,
) -> SavedViewOut:
    """Update an existing saved view preset."""
    return service.update_view(user, view_id, payload)


@router.delete("/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved_view(
    view_id: UUID,
    user: CurrentUserDep,
    service: ServiceDep,
) -> Response:
    """Delete a saved view preset."""
    service.delete_view(user, view_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
