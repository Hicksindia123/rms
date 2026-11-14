"""Pydantic schemas for the inspection module (P2-05)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConditionOption(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    label: str
    allowed_status: str
    system_behavior: str | None = None
    rule_text: str | None = None
    next_action_text: str | None = None
    remarks: str | None = None
    sort_order: int = 0


class AllocationIn(BaseModel):
    condition_code: str
    qty: int = Field(ge=0)


class AllocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    condition_code: str
    qty: int
    allowed_status: str | None = None
    system_behavior: str | None = None
    label: str | None = None


class ExtractionIn(BaseModel):
    primary_type: Literal["PACKAGING_EXTRACTED", "CONTAINER_EXTRACTED"]
    packaging_qty: int = Field(ge=0, default=0)
    container_qty: int = Field(ge=0, default=0)


class ExtractionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    primary_type: str
    packaging_qty: int
    container_qty: int
    reconciled: bool = False


class InspectionDraftIn(BaseModel):
    full_opening_confirmed: bool = False
    allocations: list[AllocationIn] = Field(default_factory=list)
    extraction: ExtractionIn | None = None


class RejectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    condition_code: str
    qty: int
    disposition: str
    hazard: bool
    stock_movement_id: UUID | None = None


class InspectionLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    gs_item_id: UUID
    line_no: int
    product_id: UUID
    product_code: str
    product_name: str
    category_id: UUID
    category_code: str
    category_name: str
    documented_qty: int
    received_qty: int
    short_qty: int
    excess_qty: int
    requires_full_opening: bool
    full_opening_confirmed: bool
    inspection_id: UUID | None = None
    inspection_status: str = "PENDING"
    inspected_by: UUID | None = None
    inspected_by_name: str | None = None
    inspected_at: datetime | None = None
    reopened_at: datetime | None = None
    reopened_by_name: str | None = None
    reopen_reason: str | None = None
    condition_options: list[ConditionOption] = Field(default_factory=list)
    allocations: list[AllocationOut] = Field(default_factory=list)
    extraction: ExtractionOut | None = None
    rejections: list[RejectionOut] = Field(default_factory=list)


class InspectionTotals(BaseModel):
    lines_count: int
    lines_finalised: int
    total_received_qty: int
    total_graded_qty: int
    total_rejected_qty: int
    total_hazard_qty: int


class InspectionPermissions(BaseModel):
    can_inspect: bool
    can_finalise: bool
    can_reopen: bool


class InspectionGsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    gs_id: UUID
    gs_no: str
    status: str
    category_code: str | None = None
    has_hazard: bool
    has_rejections: bool
    lines: list[InspectionLineOut]
    totals: InspectionTotals
    permissions: InspectionPermissions


class FinaliseLineOut(BaseModel):
    gs_item_id: UUID
    status: str
    is_gs_finalised: bool
    next_status: str
    rejections: list[RejectionOut] = Field(default_factory=list)
    lots_created: list[dict[str, Any]] = Field(default_factory=list)


class ReopenIn(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


class ReopenOut(BaseModel):
    gs_item_id: UUID
    status: str
    reopened_at: datetime
