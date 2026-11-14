"""P3-04 inventory API models (master plan §2.2 Stage-5, DD r63-r66, BR-30)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

# The custody-segregated stock views (Step-6). Each maps to a location class + condition filter
# in the repository; SPARE_PARTS is the Spare Parts Manager's ledger (BR-30).
StockView = Literal[
    "FUNCTIONAL",
    "NON_FUNCTIONAL",
    "SPARE_PARTS",
    "BATTERIES",
    "REJECTED_HOLD",
    "HAZARD_QUARANTINE",
    "PENDING_HOLD",
    "IN_TRANSIT",
]

AssignmentCode = Literal[
    "CUST_FUNCTIONAL_GOOD",
    "CUST_FUNCTIONAL_REPAIRED",
    "CUST_NON_FUNCTIONAL",
    "CUST_SALVAGED_PARTS",
]


class OptionOut(BaseModel):
    code: str
    label: str
    description: str | None = None


class RefOut(BaseModel):
    id: UUID
    code: str | None = None
    name: str


class InventoryLookupsOut(BaseModel):
    """Filter values and the DD r63-66 assignment options (labels from the published form)."""

    assignment_options: list[OptionOut]
    views: list[StockView]
    products: list[RefOut]
    part_types: list[OptionOut]
    pcb_models: list[RefOut]
    pcb_suppliers: list[RefOut]
    containers: list[RefOut]
    partitions: list[RefOut]
    battery_types: list[RefOut]
    can_export: bool
    can_assign: bool
    can_request_adjustment: bool
    can_approve_adjustment: bool


class StockRowOut(BaseModel):
    lot_id: UUID
    location_id: UUID
    location_code: str
    location_name: str
    location_class: str
    qty: int
    condition_class: str
    source_condition_code: str | None
    is_pending: bool
    item_kind: str
    gs_id: UUID | None
    gs_no: str | None
    line_no: int | None
    product_id: UUID | None
    product_code: str | None
    product_name: str | None
    category_code: str | None
    part_type: str | None
    pcb_model_name: str | None
    pcb_supplier_name: str | None
    battery_type_code: str | None
    battery_type_name: str | None
    container_code: str | None
    partition_code: str | None
    received_at: datetime | None
    age_days: int | None
    transfer_id: UUID | None = None
    transfer_no: str | None = None
    transfer_to_name: str | None = None
    # DD r63-64 routing: next-action text of the matching assignment option (from configuration).
    next_action_code: str | None = None
    next_action_text: str | None = None
    # Assignment codes that are valid for this lot (only these are offered in the UI).
    assignment_codes: list[str] = Field(default_factory=list)


class StockPage(BaseModel):
    view: StockView
    items: list[StockRowOut]
    total: int
    total_qty: int
    page: int
    page_size: int


class BalanceOut(BaseModel):
    location_id: UUID
    location_code: str
    location_name: str
    location_class: str
    qty: int


class MovementOut(BaseModel):
    id: UUID
    lot_id: UUID
    lot_condition_class: str
    is_ancestor: bool
    movement_type: str
    qty: int
    from_location_code: str | None
    from_location_name: str | None
    to_location_code: str | None
    to_location_name: str | None
    reference_type: str | None
    reference_id: UUID | None
    reference_no: str | None
    reason: str | None
    created_at: datetime
    created_by_name: str | None


class StockCardOut(BaseModel):
    """The lot's full path: its own movements plus those of the lots it was reclassified from,
    back to the GS inward (BR-30 acceptance: stock card reconstructs the path)."""

    lot_id: UUID
    condition_class: str
    source_condition_code: str | None
    source_condition_label: str | None  # configured option label (rule e)
    is_pending: bool
    item_kind: str
    gs_id: UUID | None
    gs_no: str | None
    line_no: int | None
    product_code: str | None
    product_name: str | None
    part_type: str | None
    pcb_model_name: str | None
    pcb_supplier_name: str | None
    container_code: str | None
    partition_code: str | None
    lineage: list[UUID]
    balances: list[BalanceOut]
    movements: list[MovementOut]
    assignments: list[AssignmentOut]


class AssignmentIn(BaseModel):
    lot_id: UUID
    qty: int = Field(gt=0)
    assignment_code: AssignmentCode
    from_location_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=1000)


class AssignmentOut(BaseModel):
    id: UUID
    lot_id: UUID
    qty: int
    assignment_code: str
    assignment_label: str
    condition_class: str
    from_location_code: str
    to_location_code: str
    to_location_name: str
    outcome: Literal["ALREADY_IN_PLACE", "TRANSFER_INITIATED"]
    transfer_id: UUID | None
    transfer_no: str | None
    notes: str | None
    created_by_name: str | None
    created_at: datetime


class ViolationOut(BaseModel):
    rule_code: str
    guard_ref: str
    lot_id: UUID
    location_id: UUID
    location_code: str
    qty: int
    condition_class: str
    location_class: str
    detail: str
    gs_no: str | None
    product_name: str | None


class SegregationRunOut(BaseModel):
    id: UUID
    trigger_code: str
    run_at: datetime
    violation_count: int


class SegregationCheckOut(BaseModel):
    checked_at: datetime
    violation_count: int
    violations: list[ViolationOut]
    last_nightly_run: SegregationRunOut | None


AdjustmentStatus = Literal["REQUESTED", "APPROVED", "REJECTED"]


class AdjustmentIn(BaseModel):
    lot_id: UUID
    location_id: UUID
    counted_qty: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=1000)


class AdjustmentDecisionIn(BaseModel):
    remarks: str | None = Field(default=None, max_length=1000)


class AdjustmentRejectIn(BaseModel):
    remarks: str = Field(min_length=1, max_length=1000)


class AdjustmentOut(BaseModel):
    id: UUID
    lot_id: UUID
    location_id: UUID
    location_code: str
    location_name: str
    condition_class: str
    item_kind: str
    gs_no: str | None
    product_name: str | None
    part_type: str | None
    system_qty: int
    counted_qty: int
    delta: int
    current_qty: int
    reason: str
    status: AdjustmentStatus
    requested_by: UUID
    requested_by_name: str | None
    requested_at: datetime
    decided_by_name: str | None
    decided_at: datetime | None
    decision_remarks: str | None
    movement_id: UUID | None
    can_decide: bool = False


class AdjustmentPage(BaseModel):
    items: list[AdjustmentOut]
    total: int
    page: int
    page_size: int


StockCardOut.model_rebuild()
