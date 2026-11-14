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


# ---------------------------------------------------------------------------
# Dispatch / Routing
# ---------------------------------------------------------------------------
class DepartmentRoutingLineIn(BaseModel):
    gs_item_id: UUID
    source_bucket_field_id: UUID | None = None
    qty_sent: int = Field(gt=0, description="Quantity to dispatch to department")
    notes: str | None = None


class CreateDepartmentRoutingIn(BaseModel):
    gs_id: UUID
    department_field_id: UUID
    lines: list[DepartmentRoutingLineIn] = Field(min_length=1)
    remarks: str | None = None


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
    lines: list[DepartmentRoutingLineOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Receiving
# ---------------------------------------------------------------------------
class DepartmentReceiptLineIn(BaseModel):
    routing_line_id: UUID
    outcome_head_id: UUID
    quantity: int = Field(gt=0, description="Quantity received under this outcome head")
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
