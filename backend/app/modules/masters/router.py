"""Masters HTTP API (change plan 2026-11-12 Phase 1, AMD-07). HTTP, auth and Pydantic I/O only."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse

from app.core.db import UowDep
from app.core.idempotency import IdempotencyKeyDep
from app.core.permissions import require
from app.core.security import CurrentUser
from app.modules.masters.schemas import (
    CategoryOut,
    ProductImportIn,
    ProductImportOut,
    ProductOut,
    ProductUpdate,
    SubCategoryCreate,
    SubCategoryOut,
    SubCategoryUpdate,
)
from app.modules.masters.service import MastersService
from app.shared.pagination import Page

router = APIRouter(prefix="/masters", tags=["masters"])


def get_service(uow: UowDep) -> MastersService:
    return MastersService(uow)


ServiceDep = Annotated[MastersService, Depends(get_service)]
ViewUser = Annotated[CurrentUser, Depends(require("masters", "view"))]
CreateUser = Annotated[CurrentUser, Depends(require("masters", "create"))]
EditUser = Annotated[CurrentUser, Depends(require("masters", "edit"))]


@router.get("/product-categories", response_model=list[CategoryOut])
def list_categories(user: ViewUser, service: ServiceDep) -> list[CategoryOut]:
    return service.list_categories(user)


@router.get("/product-subcategories", response_model=list[SubCategoryOut])
def list_subcategories(
    user: ViewUser,
    service: ServiceDep,
    category_id: UUID | None = None,
    include_inactive: bool = False,
) -> list[SubCategoryOut]:
    return service.list_subcategories(user, category_id, include_inactive)


@router.post(
    "/product-subcategories",
    response_model=SubCategoryOut,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "Duplicate code/name, inactive category or idempotency"}},
)
def create_subcategory(
    payload: SubCategoryCreate, user: CreateUser, idem: IdempotencyKeyDep, service: ServiceDep
) -> JSONResponse:
    """AMD-07: add a sub-category (`Idempotency-Key` required). The code is immutable."""
    return service.create_subcategory(user, payload, idem).to_response()


@router.patch("/product-subcategories/{subcategory_id}", response_model=SubCategoryOut)
def update_subcategory(
    subcategory_id: UUID, payload: SubCategoryUpdate, user: EditUser, service: ServiceDep
) -> SubCategoryOut:
    return service.update_subcategory(user, subcategory_id, payload)


@router.get("/products", response_model=Page[ProductOut])
def list_products(
    user: ViewUser,
    service: ServiceDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    category_id: UUID | None = None,
    subcategory_id: UUID | None = None,
    without_subcategory: bool = False,
    include_inactive: bool = True,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> Page[ProductOut]:
    return service.list_products(
        user,
        q=q,
        category_id=category_id,
        subcategory_id=subcategory_id,
        without_subcategory=without_subcategory,
        include_inactive=include_inactive,
        page=page,
        page_size=page_size,
    )


@router.patch("/products/{product_id}", response_model=ProductOut)
def update_product(
    product_id: UUID, payload: ProductUpdate, user: EditUser, service: ServiceDep
) -> ProductOut:
    """AMD-07: edit a product incl. Category -> Sub-Category (must belong to the category)."""
    return service.update_product(user, product_id, payload)


@router.post("/products/import/preview", response_model=ProductImportOut)
def preview_product_import(
    payload: ProductImportIn, user: CreateUser, service: ServiceDep
) -> ProductImportOut:
    """Dry run of a product CSV (Item Name, Category, Sub-Category): nothing is written."""
    return service.preview_import(user, payload)


@router.post("/products/import", response_model=ProductImportOut)
def run_product_import(
    payload: ProductImportIn, user: CreateUser, idem: IdempotencyKeyDep, service: ServiceDep
) -> JSONResponse:
    """Apply a product CSV in one transaction (`Idempotency-Key` required, G-16 pattern)."""
    return service.run_import(user, payload, idem).to_response()
