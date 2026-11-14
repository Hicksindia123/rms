"""Item field profiles API (change plan 2026-11-12 Phase 4; AMD-10, AMD-11, AMD-16; G-18).

View: `config:view`. Changes: `config:configure`. System guards are not configurable here.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse

from app.core.db import UowDep
from app.core.idempotency import IdempotencyKeyDep
from app.core.permissions import require
from app.core.security import CurrentUser
from app.modules.config.field_profiles.schemas import (
    FieldCreate,
    FieldGroup,
    FieldOut,
    FieldUpdate,
    OverrideIn,
    ResolvedProfileOut,
    ScopeIn,
    ScopeProfileOut,
    VersionOut,
)
from app.modules.config.field_profiles.service import FieldProfileService

router = APIRouter(prefix="/config/item-field-profiles", tags=["config-item-field-profiles"])


def get_service(uow: UowDep) -> FieldProfileService:
    return FieldProfileService(uow)


ServiceDep = Annotated[FieldProfileService, Depends(get_service)]
ViewUser = Annotated[CurrentUser, Depends(require("config", "view"))]
ConfigureUser = Annotated[CurrentUser, Depends(require("config", "configure"))]


@router.get("/fields", response_model=list[FieldOut])
def list_fields(
    user: ViewUser,
    service: ServiceDep,
    field_group: FieldGroup | None = None,
    include_inactive: bool = True,
) -> list[FieldOut]:
    return service.list_fields(user, field_group, include_inactive)


@router.post(
    "/fields",
    response_model=FieldOut,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "Duplicate code or idempotency conflict"}},
)
def create_field(
    payload: FieldCreate, user: ConfigureUser, idem: IdempotencyKeyDep, service: ServiceDep
) -> JSONResponse:
    """Add a library field (`Idempotency-Key` required). The code is immutable (G-18)."""
    return service.create_field(user, payload, idem).to_response()


@router.patch("/fields/{field_id}", response_model=FieldOut)
def update_field(
    field_id: UUID, payload: FieldUpdate, user: ConfigureUser, service: ServiceDep
) -> FieldOut:
    return service.update_field(user, field_id, payload)


@router.get("/scope", response_model=ScopeProfileOut)
def get_scope_profile(
    user: ViewUser,
    service: ServiceDep,
    category_id: UUID,
    subcategory_id: UUID | None = None,
    product_id: UUID | None = None,
) -> ScopeProfileOut:
    """Own assignments, inherited fields and effective fields per group for one scope."""
    scope = ScopeIn(category_id=category_id, subcategory_id=subcategory_id, product_id=product_id)
    return service.get_scope_profile(user, scope)


@router.put("/scope/{field_group}", response_model=ScopeProfileOut)
def set_scope_override(
    field_group: FieldGroup, payload: OverrideIn, user: ConfigureUser, service: ServiceDep
) -> ScopeProfileOut:
    """Replace this scope's fields for one group; an empty list restores inheritance.
    Idempotent: repeating the same body changes nothing."""
    return service.set_override(user, field_group, payload)


@router.get("/resolve/{product_id}", response_model=ResolvedProfileOut)
def resolve_product(
    product_id: UUID, user: ViewUser, service: ServiceDep, version_id: UUID | None = None
) -> ResolvedProfileOut:
    """Effective profile of a product (DB function), live or at a given version."""
    return service.resolve_product(user, product_id, version_id)


@router.get("/versions", response_model=list[VersionOut])
def list_versions(
    user: ViewUser, service: ServiceDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[VersionOut]:
    return service.list_versions(user, limit)
