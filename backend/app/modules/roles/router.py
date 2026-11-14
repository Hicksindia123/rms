"""Role & permission administration HTTP API (master plan prompt P1-05).

Permissions: roles.view (read), roles.create, roles.edit, roles.delete, roles.configure
(permission matrix). HTTP, auth and Pydantic I/O only.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.core.db import UowDep
from app.core.permissions import require
from app.core.security import CurrentUser
from app.modules.roles.schemas import (
    PermissionCatalogueOut,
    RoleCreate,
    RoleOut,
    RolePermissionOut,
    RolePermissionsReplaceIn,
    RoleUpdate,
)
from app.modules.roles.service import RoleAdminService

router = APIRouter(prefix="/admin", tags=["roles"])


def get_service(uow: UowDep) -> RoleAdminService:
    return RoleAdminService(uow)


ServiceDep = Annotated[RoleAdminService, Depends(get_service)]
ViewUser = Annotated[CurrentUser, Depends(require("roles", "view"))]
CreateUser = Annotated[CurrentUser, Depends(require("roles", "create"))]
EditUser = Annotated[CurrentUser, Depends(require("roles", "edit"))]
DeleteUser = Annotated[CurrentUser, Depends(require("roles", "delete"))]
ConfigureUser = Annotated[CurrentUser, Depends(require("roles", "configure"))]


@router.get("/roles", response_model=list[RoleOut])
def list_roles(user: ViewUser, service: ServiceDep) -> list[RoleOut]:
    return service.list_roles(user)


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
def create_role(user: CreateUser, payload: RoleCreate, service: ServiceDep) -> RoleOut:
    return service.create_role(user, payload)


@router.patch("/roles/{role_id}", response_model=RoleOut)
def update_role(role_id: UUID, user: EditUser, payload: RoleUpdate, service: ServiceDep) -> RoleOut:
    return service.update_role(user, role_id, payload)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(role_id: UUID, user: DeleteUser, service: ServiceDep) -> Response:
    service.delete_role(user, role_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/permissions", response_model=list[PermissionCatalogueOut])
def permission_catalogue(user: ViewUser, service: ServiceDep) -> list[PermissionCatalogueOut]:
    return service.catalogue(user)


@router.get("/roles/{role_id}/permissions", response_model=list[RolePermissionOut])
def role_permissions(role_id: UUID, user: ViewUser, service: ServiceDep) -> list[RolePermissionOut]:
    return service.role_permissions(user, role_id)


@router.put("/roles/{role_id}/permissions", response_model=list[RolePermissionOut])
def replace_role_permissions(
    role_id: UUID, user: ConfigureUser, payload: RolePermissionsReplaceIn, service: ServiceDep
) -> list[RolePermissionOut]:
    return service.replace_permissions(user, role_id, payload)
