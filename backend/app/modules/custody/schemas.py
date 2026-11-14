"""Custody transfer engine API models (prompt P3-01; master plan §8.5, DD r44-r46, BR-20..BR-22)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.shared.pagination import Page

ResolutionCode = Literal["RESEND_CORRECTED", "ACCEPT_COUNTED_WITH_ADJUSTMENT", "CANCEL_RETURN"]
DifferenceDisposition = Literal["RETURN_TO_SOURCE", "WRITE_OFF_LOSS"]


# --- inputs ------------------------------------------------------------------------------------
class TransferLineIn(BaseModel):
    lot_id: UUID
    qty: int = Field(gt=0, le=1_000_000)


class InitiateIn(BaseModel):
    """Generic two-phase transfer between custody locations (system location codes)."""

    from_location_code: str = Field(min_length=1, max_length=60)
    to_location_code: str = Field(min_length=1, max_length=60)
    lines: list[TransferLineIn] = Field(min_length=1, max_length=500)
    mode_code: str = Field(default="PHYSICAL_AND_DIGITAL", max_length=60)  # DD r44
    gs_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=1000)


class HandoverIn(BaseModel):
    """Step-4 handover. `lines` omitted = every eligible quantity of the GS."""

    lines: list[TransferLineIn] | None = Field(default=None, max_length=500)
    mode_code: str = Field(default="PHYSICAL_AND_DIGITAL", max_length=60)
    notes: str | None = Field(default=None, max_length=1000)


class CountLineIn(BaseModel):
    lot_id: UUID
    qty_counted: int = Field(ge=0, le=1_000_000)


class AcceptIn(BaseModel):
    lines: list[CountLineIn] = Field(min_length=1, max_length=500)
    acceptance_code: str = Field(min_length=1, max_length=60)  # DD r45 / r46
    notes: str | None = Field(default=None, max_length=2000)


class ReconcileIn(BaseModel):
    resolution_code: ResolutionCode
    notes: str = Field(min_length=1, max_length=2000)
    difference_disposition: DifferenceDisposition | None = None
    resend_lines: list[TransferLineIn] | None = Field(default=None, max_length=500)
    override: bool = False


class ApproveAdjustmentIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class CancelIn(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class ClassifyIn(BaseModel):
    qty: int = Field(gt=0, le=1_000_000)
    remarks: str | None = Field(default=None, max_length=1000)


# --- outputs -----------------------------------------------------------------------------------
class OptionOut(BaseModel):
    code: str
    label: str
    description: str | None = None


class TransferLineOut(BaseModel):
    lot_id: UUID
    gs_item_id: UUID | None
    line_no: int | None
    product_code: str | None
    product_name: str | None
    condition_class: str
    condition_code: str | None
    condition_label: str | None
    routing_hint: str | None
    # None while a blind count hides the quantity sent from the receiver.
    qty_sent: int | None
    qty_counted: int | None
    qty_accepted: int
    qty_returned: int
    qty_adjusted: int


class ReconciliationOut(BaseModel):
    id: UUID
    resolution_code: str
    resolution_label: str
    difference_disposition: str | None
    resend_lines: list[dict[str, Any]]
    notes: str
    status: str
    requires_rm_approval: bool
    proposed_by_name: str | None
    proposed_at: datetime
    initiator_signed_by_name: str | None
    initiator_signed_at: datetime | None
    receiver_signed_by_name: str | None
    receiver_signed_at: datetime | None
    is_rm_override: bool
    rm_approved_by_name: str | None
    rm_approved_at: datetime | None
    rm_reason: str | None
    applied_at: datetime | None
    resend_transfer_id: UUID | None


class TransferPermissions(BaseModel):
    can_accept: bool = False
    can_cancel: bool = False
    can_print: bool = False
    # INITIATOR | RECEIVER when the user may sign a reconciliation for that party.
    reconcile_side: str | None = None
    can_override: bool = False
    can_approve_adjustment: bool = False


class TransferSummaryOut(BaseModel):
    id: UUID
    transfer_no: str
    gs_id: UUID | None
    gs_no: str | None
    status: str
    purpose_code: str | None
    with_packaging: bool
    stock_moved: bool
    mode_code: str
    mode_label: str | None
    from_location_code: str
    from_location_name: str
    to_location_code: str
    to_location_name: str
    initiated_by: UUID
    initiated_by_name: str | None
    initiated_at: datetime
    accepted_by_name: str | None
    accepted_at: datetime | None
    acceptance_code: str | None
    acceptance_label: str | None
    line_count: int
    total_qty: int | None
    created_at: datetime


class TransferDetailOut(TransferSummaryOut):
    notes: str | None
    discrepancy_notes: str | None
    cancel_reason: str | None
    cancelled_at: datetime | None
    resolution_code: str | None
    reconciled_at: datetime | None
    supersedes_transfer_id: UUID | None
    blind_count: bool
    lines: list[TransferLineOut]
    reconciliations: list[ReconciliationOut]
    permissions: TransferPermissions


TransferPage = Page[TransferSummaryOut]


class HandoverLineOut(BaseModel):
    lot_id: UUID
    gs_item_id: UUID | None
    line_no: int | None
    product_code: str | None
    product_name: str | None
    condition_code: str | None
    condition_label: str | None
    routing_hint: str | None
    qty: int


class ExcludedOut(BaseModel):
    lot_id: UUID | None
    gs_item_id: UUID | None
    line_no: int | None
    product_name: str | None
    qty: int
    reason_code: str  # PENDING_BP | NOT_ALLOWED | HAZARD | RM_NOT_ALLOWED
    reason_label: str
    condition_label: str | None
    location_code: str | None
    location_name: str | None
    detail: str | None


class BlockOut(BaseModel):
    code: str
    message: str


class HandoverPreviewOut(BaseModel):
    gs_id: UUID
    gs_no: str
    gs_status: str
    category_code: str | None
    from_location_code: str
    from_location_name: str
    to_location_code: str
    to_location_name: str
    eligible: list[HandoverLineOut]
    excluded: list[ExcludedOut]
    blocked: BlockOut | None
    proposal_transfer_id: UUID | None
    live_transfers: list[TransferSummaryOut]
    can_initiate: bool
    mode_options: list[OptionOut]
    default_mode_code: str | None


class LookupsOut(BaseModel):
    acceptance_options: list[OptionOut]
    mode_options: list[OptionOut]
    resolution_options: list[OptionOut]
    disposition_options: list[OptionOut]
    blind_count: bool
    statuses: list[str]


class StoreStockRow(BaseModel):
    lot_id: UUID
    qty: int
    gs_id: UUID
    gs_no: str
    gs_item_id: UUID | None
    line_no: int | None
    product_code: str | None
    product_name: str | None
    condition_class: str
    condition_code: str | None
    condition_label: str | None
    routing_hint: str | None
    requires_evaluation: bool
    last_packaging_check: dict[str, Any] | None
    # DIRECT_CLASSIFICATION (DEC-14 SELLABLE) | AWAITING_TECHNICIAN (P3-02) | CLASSIFIED
    next_step: str
    can_classify: bool


class StoreStockOut(BaseModel):
    location_code: str
    location_name: str
    rows: list[StoreStockRow]
    can_classify: bool
    can_check_packaging: bool


class ClassifyOut(BaseModel):
    source_lot_id: UUID
    target_lot_id: UUID
    qty: int
    condition_class: str


class TransferNoteOut(BaseModel):
    transfer: TransferDetailOut
    layout: dict[str, Any]
    template_version: int
    print_count: int
    is_reprint: bool
    watermark: str | None
