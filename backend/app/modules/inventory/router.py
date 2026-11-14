"""Custody segregation & inventory HTTP API (prompt P3-04). HTTP, auth, Pydantic I/O only.

Stock-moving commands (custody assignment, adjustment approval) require an `Idempotency-Key`
header (G-16); a replay returns the original response with `Idempotency-Replayed: true`.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse, Response

from app.core.db import UowDep
from app.core.idempotency import IdempotencyKeyDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.inventory.schemas import (
    AdjustmentDecisionIn,
    AdjustmentIn,
    AdjustmentOut,
    AdjustmentPage,
    AdjustmentRejectIn,
    AdjustmentStatus,
    AssignmentIn,
    AssignmentOut,
    InventoryLookupsOut,
    SegregationCheckOut,
    StockCardOut,
    StockPage,
    StockView,
)
from app.modules.inventory.service import InventoryService, StockFilters

router = APIRouter(prefix="/inventory", tags=["inventory"])


def get_service(uow: UowDep) -> InventoryService:
    return InventoryService(uow)


ServiceDep = Annotated[InventoryService, Depends(get_service)]
ViewUser = Annotated[CurrentUser, Depends(require("inventory", "view"))]
EditUser = Annotated[CurrentUser, Depends(require("inventory", "edit"))]
ExportUser = Annotated[CurrentUser, Depends(require("inventory", "export"))]


def stock_filters(
    product_id: UUID | None = None,
    condition_class: Annotated[str | None, Query(pattern="^[A-Z_]{2,30}$")] = None,
    gs_id: UUID | None = None,
    location_id: UUID | None = None,
    part_type: Annotated[str | None, Query(pattern="^(TIP|BODY|WIRE|PCB)$")] = None,
    pcb_model_id: UUID | None = None,
    pcb_supplier_id: UUID | None = None,
    container_id: UUID | None = None,
    partition_id: UUID | None = None,
    battery_type_id: UUID | None = None,
    q: Annotated[str | None, Query(max_length=60)] = None,
    min_age_days: Annotated[int | None, Query(ge=0, le=3650)] = None,
    max_age_days: Annotated[int | None, Query(ge=0, le=3650)] = None,
) -> StockFilters:
    return StockFilters(
        product_id=product_id,
        condition_class=condition_class,
        gs_id=gs_id,
        location_id=location_id,
        part_type=part_type,
        pcb_model_id=pcb_model_id,
        pcb_supplier_id=pcb_supplier_id,
        container_id=container_id,
        partition_id=partition_id,
        battery_type_id=battery_type_id,
        q=q.strip() if q else None,
        min_age_days=min_age_days,
        max_age_days=max_age_days,
    )


FiltersDep = Annotated[StockFilters, Depends(stock_filters)]


@router.get("/lookups", response_model=InventoryLookupsOut)
def lookups(
    user: ViewUser, perms: EffectivePermissionsDep, service: ServiceDep
) -> InventoryLookupsOut:
    """Filter values, the DD r63-66 custody assignment options and the caller's abilities."""
    return service.lookups(user, perms)


@router.get("/stock", response_model=StockPage)
def stock(
    user: ViewUser,
    service: ServiceDep,
    filters: FiltersDep,
    view: StockView,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> StockPage:
    """One custody-segregated stock view (BR-30). SPARE_PARTS → 403 unless the caller's role is in
    `spare_parts_ledger_view_roles`; salvaged parts never appear in the other views."""
    return service.stock(user, view, filters, page=page, page_size=page_size)


@router.get("/stock/export", response_class=Response)
def export_stock(
    user: ExportUser, service: ServiceDep, filters: FiltersDep, view: StockView
) -> Response:
    """The same view as CSV (all matching rows, up to 10,000)."""
    body = service.export_csv(user, view, filters)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="inventory-{view.lower()}.csv"'},
    )


@router.get("/lots/{lot_id}/stock-card", response_model=StockCardOut)
def stock_card(lot_id: UUID, user: ViewUser, service: ServiceDep) -> StockCardOut:
    """Full movement history of a lot, back to the GS inward through its reclassifications."""
    return service.stock_card(user, lot_id)


@router.post(
    "/custody-assignment",
    response_model=AssignmentOut,
    status_code=status.HTTP_201_CREATED,
)
def custody_assignment(
    payload: AssignmentIn,
    user: EditUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """DD r63-66 custody assignment. A contradictory request → 422 G-04 / G-05 / G-12. When the lot
    is elsewhere, a custody transfer to the assigned custodian is initiated (G-09)."""
    return service.assign(user, perms, payload, idem).to_response()


@router.get("/segregation-check", response_model=SegregationCheckOut)
def segregation_check(user: ViewUser, service: ServiceDep) -> SegregationCheckOut:
    """On-demand integrity check (expected: zero violations) plus the last nightly run."""
    return service.segregation_check(user)


@router.get("/adjustments", response_model=AdjustmentPage)
def list_adjustments(
    user: ViewUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
    status_: Annotated[AdjustmentStatus | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> AdjustmentPage:
    return service.list_adjustments(user, perms, status=status_, page=page, page_size=page_size)


@router.post("/adjustments", response_model=AdjustmentOut, status_code=status.HTTP_201_CREATED)
def request_adjustment(
    payload: AdjustmentIn, user: EditUser, perms: EffectivePermissionsDep, service: ServiceDep
) -> AdjustmentOut:
    """A physical count difference, requested by the location's custodian (reason mandatory)."""
    return service.request_adjustment(user, perms, payload)


@router.post("/adjustments/{adjustment_id}/approve", response_model=AdjustmentOut)
def approve_adjustment(
    adjustment_id: UUID,
    payload: AdjustmentDecisionIn,
    user: ViewUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """RM / admin approval → ADJUST movement (never the requester)."""
    return service.approve_adjustment(user, perms, adjustment_id, payload, idem).to_response()


@router.post("/adjustments/{adjustment_id}/reject", response_model=AdjustmentOut)
def reject_adjustment(
    adjustment_id: UUID,
    payload: AdjustmentRejectIn,
    user: ViewUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
) -> AdjustmentOut:
    return service.reject_adjustment(user, perms, adjustment_id, payload)
