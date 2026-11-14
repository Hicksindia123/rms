"""User administration HTTP API (master plan prompt P1-05). HTTP, auth and Pydantic I/O only.

Permissions: users.view (read), users.create, users.edit (profile, roles, status, password,
overrides), users.configure (departments). Super-Admin-only rules live in the service.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.db import UowDep
from app.core.permissions import require
from app.core.security import CurrentUser, CurrentUserDep
from app.modules.users.schemas import (
    ChangeOwnPasswordIn,
    DepartmentCreate,
    DepartmentOut,
    DepartmentUpdate,
    EffectivePermissionsOut,
    OverrideOut,
    OverridesReplaceIn,
    ReasonIn,
    ResetPasswordIn,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.modules.users.service import UserAdminService
from app.shared.auth_admin import AuthAdmin, get_auth_admin
from app.shared.pagination import Page

router = APIRouter(prefix="/admin", tags=["users"])
me_router = APIRouter(tags=["users"])


def get_service(uow: UowDep) -> UserAdminService:
    return UserAdminService(uow)


def get_command_service(
    uow: UowDep, auth_admin: Annotated[AuthAdmin, Depends(get_auth_admin)]
) -> UserAdminService:
    return UserAdminService(uow, auth_admin)


ServiceDep = Annotated[UserAdminService, Depends(get_service)]
CommandServiceDep = Annotated[UserAdminService, Depends(get_command_service)]
ViewUser = Annotated[CurrentUser, Depends(require("users", "view"))]
CreateUser = Annotated[CurrentUser, Depends(require("users", "create"))]
EditUser = Annotated[CurrentUser, Depends(require("users", "edit"))]
ConfigureUser = Annotated[CurrentUser, Depends(require("users", "configure"))]


@router.get("/users", response_model=Page[UserOut])
def list_users(
    user: ViewUser,
    service: ServiceDep,
    search: Annotated[str | None, Query(max_length=100)] = None,
    role: Annotated[str | None, Query(max_length=60)] = None,
    department_id: UUID | None = None,
    status_filter: Annotated[Literal["active", "inactive"] | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> Page[UserOut]:
    return service.list_users(
        user,
        search=search,
        role_code=role,
        department_id=department_id,
        status=status_filter,
        page=page,
        page_size=page_size,
    )


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(user: CreateUser, payload: UserCreate, service: CommandServiceDep) -> UserOut:
    return service.create_user(user, payload)


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: UUID, user: ViewUser, service: ServiceDep) -> UserOut:
    return service.get_user(user, user_id)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: UUID, user: EditUser, payload: UserUpdate, service: ServiceDep) -> UserOut:
    return service.update_user(user, user_id, payload)


@router.post("/users/{user_id}/deactivate", response_model=UserOut)
def deactivate_user(
    user_id: UUID, user: EditUser, payload: ReasonIn, service: CommandServiceDep
) -> UserOut:
    return service.deactivate(user, user_id, payload)


@router.post("/users/{user_id}/reactivate", response_model=UserOut)
def reactivate_user(
    user_id: UUID, user: EditUser, payload: ReasonIn, service: CommandServiceDep
) -> UserOut:
    return service.reactivate(user, user_id, payload)


@router.post("/users/{user_id}/reset-password", response_model=UserOut)
def reset_password(
    user_id: UUID, user: EditUser, payload: ResetPasswordIn, service: CommandServiceDep
) -> UserOut:
    return service.reset_password(user, user_id, payload)


@router.get("/users/{user_id}/effective-permissions", response_model=EffectivePermissionsOut)
def get_effective_permissions(
    user_id: UUID, user: ViewUser, service: ServiceDep
) -> EffectivePermissionsOut:
    return service.effective_permissions(user, user_id)


@router.get("/users/{user_id}/overrides", response_model=list[OverrideOut])
def list_overrides(user_id: UUID, user: ViewUser, service: ServiceDep) -> list[OverrideOut]:
    return service.list_overrides(user, user_id)


@router.put("/users/{user_id}/overrides", response_model=list[OverrideOut])
def replace_overrides(
    user_id: UUID, user: EditUser, payload: OverridesReplaceIn, service: ServiceDep
) -> list[OverrideOut]:
    return service.replace_overrides(user, user_id, payload)


@router.get("/departments", response_model=list[DepartmentOut])
def list_departments(user: ViewUser, service: ServiceDep) -> list[DepartmentOut]:
    return service.list_departments(user)


@router.post("/departments", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
def create_department(
    user: ConfigureUser, payload: DepartmentCreate, service: ServiceDep
) -> DepartmentOut:
    return service.create_department(user, payload)


@router.patch("/departments/{department_id}", response_model=DepartmentOut)
def update_department(
    department_id: UUID, user: ConfigureUser, payload: DepartmentUpdate, service: ServiceDep
) -> DepartmentOut:
    return service.update_department(user, department_id, payload)


@me_router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_own_password(
    user: CurrentUserDep, payload: ChangeOwnPasswordIn, service: CommandServiceDep
) -> Response:
    """Set a new password (also clears an admin-issued temporary password flag, DEC-50)."""
    service.change_own_password(user, payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
