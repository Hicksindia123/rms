"""Intermediate Stores HTTP API (Phase P1, DEC-61).

Permissions: intermediate_stores.view (admin list + mapping), .create (add a store), .edit (rename,
activate / deactivate, default), .configure (category mapping). `GET /intermediate-stores/mine`
needs only a signed-in user. HTTP, auth and Pydantic I/O only.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.core.db import UowDep
from app.core.permissions import require
from app.core.security import CurrentUser, CurrentUserDep
from app.modules.intermediate_stores.schemas import (
    StoreBrief,
    StoreCreate,
    StoreMappingIn,
    StoreMappingOut,
    StoreOut,
    StoreUpdate,
)
from app.modules.intermediate_stores.service import IntermediateStoreService

admin_router = APIRouter(prefix="/admin/intermediate-stores", tags=["intermediate-stores"])
router = APIRouter(prefix="/intermediate-stores", tags=["intermediate-stores"])


def get_service(uow: UowDep) -> IntermediateStoreService:
    return IntermediateStoreService(uow)


ServiceDep = Annotated[IntermediateStoreService, Depends(get_service)]
ViewUser = Annotated[CurrentUser, Depends(require("intermediate_stores", "view"))]
CreateUser = Annotated[CurrentUser, Depends(require("intermediate_stores", "create"))]
EditUser = Annotated[CurrentUser, Depends(require("intermediate_stores", "edit"))]
ConfigureUser = Annotated[CurrentUser, Depends(require("intermediate_stores", "configure"))]


@admin_router.get("", response_model=list[StoreOut])
def list_stores(user: ViewUser, service: ServiceDep) -> list[StoreOut]:
    return service.list_stores(user)


@admin_router.post("", response_model=StoreOut, status_code=status.HTTP_201_CREATED)
def create_store(user: CreateUser, payload: StoreCreate, service: ServiceDep) -> StoreOut:
    return service.create_store(user, payload)


@admin_router.patch("/{store_id}", response_model=StoreOut)
def update_store(
    store_id: UUID, user: EditUser, payload: StoreUpdate, service: ServiceDep
) -> StoreOut:
    return service.update_store(user, store_id, payload)


@admin_router.get("/{store_id}/mapping", response_model=StoreMappingOut)
def get_mapping(store_id: UUID, user: ViewUser, service: ServiceDep) -> StoreMappingOut:
    return service.get_mapping(user, store_id)


@admin_router.put("/{store_id}/mapping", response_model=StoreMappingOut)
def replace_mapping(
    store_id: UUID, user: ConfigureUser, payload: StoreMappingIn, service: ServiceDep
) -> StoreMappingOut:
    return service.replace_mapping(user, store_id, payload)


@router.get("/mine", response_model=list[StoreBrief])
def my_stores(user: CurrentUserDep, service: ServiceDep) -> list[StoreBrief]:
    return service.my_stores(user)
