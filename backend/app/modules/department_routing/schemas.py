"""Schemas for Department Routing, Receiving and Guard G-20 Reconciliation
(Change plan 2026-11-12 Phase 6; AMD-10, AMD-14, AMD-15; DEC-42, DEC-43; Guard G-20).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Outcome Heads
# ---------------------------------------------------------------------------
class DepartmentOutcomeHeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    label: str
    is_wastage: bool
    returns_to_routing: bool
    sort_order: int
    is_active: bool
    # DEC-56 Q8 / Q17: where the received pieces go (configuration; default wastage -> scrap,
    # otherwise back to the Intermediate Store).
    destination_location_code: str | None = None
    destination_location_name: str | None = None


class ConditionOptionOut(BaseModel):
    """DEC-56 Q7: one condition of the product's categorisation list."""

    model_config = ConfigDict(from_attributes=True)

    field_id: UUID
    code: str
    label: str


class ItemConditionOut(BaseModel):
    """DEC-56: one condition of a GS item's current split (original = counting split)."""

    model_config = ConfigDict(from_attributes=True)

    field_id: UUID
    field_code: str
    field_label: str
    original_qty: int
    current_qty: int


# ---------------------------------------------------------------------------
# DEC-55 (gap plan G2): RM routing plan + Store issue
# ---------------------------------------------------------------------------
class RoutingPlanLineIn(BaseModel):
    gs_item_id: UUID
    # The condition bucket the pieces come from (required when the item has buckets, Q6).
    source_bucket_field_id: UUID | None = None
    department_field_id: UUID
    qty: int = Field(gt=0, description="Pieces of this item + condition routed to the department")
    notes: str | None = Field(default=None, max_length=500)


class CreateRoutingPlanIn(BaseModel):
    gs_id: UUID
    lines: list[RoutingPlanLineIn] = Field(min_length=1)


class CancelPlanLineIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class RoutingPlanLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    gs_id: UUID
    gs_no: str
    gs_item_id: UUID
    line_no: int
    item_name: str
    sku_code: str | None = None
    source_bucket_field_id: UUID | None = None
    source_bucket_label: str | None = None
    department_field_id: UUID
    department_code: str
    department_label: str
    is_no_work: bool
    qty: int
    status: str
    notes: str | None = None
    planned_at: datetime
    planned_by_name: str | None = None
    routing_id: UUID | None = None
    routing_no: str | None = None
    issued_at: datetime | None = None
    issued_by_name: str | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None


class RoutingPlanOut(BaseModel):
    gs_id: UUID
    lines: list[RoutingPlanLineOut]


class StoreIssueIn(BaseModel):
    gs_id: UUID
    department_field_id: UUID
    plan_line_ids: list[UUID] = Field(min_length=1)
    remarks: str | None = Field(default=None, max_length=500)


class IssueQueueGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    gs_id: UUID
    gs_no: str
    party_name: str | None = None
    department_field_id: UUID
    department_code: str
    department_label: str
    planned_since: datetime
    total_qty: int
    lines: list[RoutingPlanLineOut]


class DepartmentRoutingLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    routing_id: UUID
    gs_item_id: UUID
    line_no: int
    item_name: str
    sku_code: str | None = None
    source_bucket_field_id: UUID | None = None
    source_bucket_code: str | None = None
    source_bucket_label: str | None = None
    qty_sent: int
    qty_received: int
    qty_pending: int
    notes: str | None = None
    # DEC-56 Q7: conditions the pieces may come back in (empty = routed without a condition).
    condition_options: list[ConditionOptionOut] = Field(default_factory=list)


class DepartmentRoutingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    routing_no: str
    gs_id: UUID
    gs_no: str
    department_field_id: UUID
    department_code: str
    department_label: str
    status: str
    dispatched_at: datetime
    dispatched_by: UUID | None = None
    dispatched_by_name: str | None = None
    remarks: str | None = None
    # DEC-55: where the Store issue moved the stock (legacy routings: Technician Bench).
    location_code: str | None = None
    location_name: str | None = None
    lines: list[DepartmentRoutingLineOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Receiving
# ---------------------------------------------------------------------------
class DepartmentReceiptLineIn(BaseModel):
    routing_line_id: UUID
    outcome_head_id: UUID
    quantity: int = Field(gt=0, description="Quantity received under this outcome head")
    # DEC-56 Q7: condition after work; required when the routing line came from a condition.
    condition_field_id: UUID | None = None
    remarks: str | None = None


class CreateDepartmentReceiptIn(BaseModel):
    routing_id: UUID
    lines: list[DepartmentReceiptLineIn] = Field(min_length=1)
    remarks: str | None = None


class DepartmentReceiptLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    receipt_id: UUID
    routing_line_id: UUID
    outcome_head_id: UUID
    outcome_code: str
    outcome_label: str
    is_wastage: bool
    returns_to_routing: bool
    quantity: int
    remarks: str | None = None
    created_at: datetime
    # DEC-56: condition before / after work and where the stock went (NULL before G3).
    source_condition_field_id: UUID | None = None
    condition_field_id: UUID | None = None
    condition_code: str | None = None
    condition_label: str | None = None
    destination_location_code: str | None = None


class DepartmentReceiptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    receipt_no: str
    routing_id: UUID
    received_by: UUID | None = None
    received_by_name: str | None = None
    received_at: datetime
    remarks: str | None = None
    lines: list[DepartmentReceiptLineOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Guard G-20 Reconciliation
# ---------------------------------------------------------------------------
class ItemReconciliationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    gs_item_id: UUID
    line_no: int
    item_name: str
    sku_code: str | None = None
    counted_qty: int
    in_store_qty: int
    at_departments_qty: int
    outcome_heads_qty: int
    actioned_qty: int
    # DEC-55: parts of in_store_qty — planned (waiting for the Store issue) and no-work (STORE).
    planned_qty: int = 0
    no_work_qty: int = 0
    unplanned_qty: int = 0
    is_conserved: bool


class GsReconciliationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    gs_id: UUID
    gs_no: str
    is_fully_reconciled: bool
    total_counted: int
    total_in_store: int
    total_at_departments: int
    total_outcomes: int
    total_actioned: int
    total_planned: int = 0
    total_no_work: int = 0
    total_unplanned: int = 0
    items: list[ItemReconciliationOut]


# ---------------------------------------------------------------------------
# Timeline Leg Out
# ---------------------------------------------------------------------------
class DepartmentLegOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    routing_id: UUID
    routing_no: str
    department_code: str
    department_label: str
    dispatched_at: datetime
    dispatched_by_name: str | None = None
    status: str
    qty_sent: int
    qty_received: int
    qty_pending: int
    lines: list[DepartmentRoutingLineOut] = Field(default_factory=list)
    receipts: list[DepartmentReceiptOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Queue items
# ---------------------------------------------------------------------------
class RmRoutingQueueItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    gs_id: UUID
    gs_no: str
    party_name: str | None = None
    item_count: int
    total_counted_qty: int
    in_store_qty: int
    at_departments_qty: int
    planned_qty: int = 0
    no_work_qty: int = 0
    unplanned_qty: int = 0
    active_routings_count: int
    held_since: datetime


class ReceivingQueueItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    routing_id: UUID
    routing_no: str
    gs_id: UUID
    gs_no: str
    department_code: str
    department_label: str
    status: str
    dispatched_at: datetime
    dispatched_by_name: str | None = None
    total_sent: int
    total_received: int
    total_pending: int
