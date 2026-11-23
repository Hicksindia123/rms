"""Pydantic I/O for the Accounts entry and the Dispatch Slip (change plan 2026-11-12 Phase 8;
AMD-18, AMD-19; DEC-22, DEC-26, DEC-47; G-22)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

# --- Accounts work queue / entry ----------------------------------------------------------------


class AcEntryQueueItem(BaseModel):
    gs_id: UUID
    gs_no: str
    gs_status: str
    party_name: str | None
    ac_action_slip_id: UUID
    slip_no: str
    version_no: int
    # DEC-57: 1 = first decision; 2+ = re-action of Pending pieces (follow-up round).
    round_no: int = 1
    finalised_at: datetime
    lines_total: int
    lines_needing_data: int
    lines_complete: int
    is_completed: bool
    completed_at: datetime | None
    dispatch_slip_no: str | None
    dispatch_status: str | None
    # DEC-71 (P11): store-flow goods slip = one Challan / CN for the whole GS.
    per_gs: bool = False
    requires_challan: bool = False
    requires_cn: bool = False


class AcHoldItem(BaseModel):
    """DEC-71 (Q21): a goods slip on hold, every decision Not Allowed (no Accounts entry)."""

    gs_id: UUID
    gs_no: str
    gs_status: str
    party_name: str | None
    since: datetime
    total_qty: int


class AcGsEntry(BaseModel):
    """DEC-71: the one Challan (goods ship) and the one Credit Note (Issue CN) of a goods slip."""

    requires_challan: bool
    requires_cn: bool
    challan_no: str | None
    challan_date: date | None
    cn_no: str | None
    cn_date: date | None
    cn_value: Decimal | None
    is_complete: bool
    entered_by_name: str | None
    entered_at: datetime | None


class AcEntryLine(BaseModel):
    id: UUID
    gs_item_id: UUID
    line_no: int
    product_code: str | None
    product_name: str
    action_code: str
    action_label: str
    # DEC-57: the condition of the pieces (snapshot; None for items without a split).
    condition_label: str | None = None
    qty: int
    # AMD-18: which fields this line needs comes from the action flags (snapshot, G-18).
    requires_cn: bool
    requires_challan: bool
    cn_no: str | None
    cn_date: date | None
    cn_value: Decimal | None
    challan_no: str | None
    challan_date: date | None
    is_complete: bool
    entered_by_name: str | None
    entered_at: datetime | None


class DispatchSlipSummary(BaseModel):
    id: UUID
    slip_no: str
    status: str
    generated_at: datetime
    dispatch_date: date | None
    transporter: str | None
    docket_no: str | None
    vehicle_no: str | None
    dispatched_at: datetime | None
    total_qty: int
    print_count: int


class AcEntryState(BaseModel):
    gs_id: UUID
    gs_no: str
    gs_status: str
    party_name: str | None
    party_code: str | None
    ac_action_slip_id: UUID | None
    slip_no: str | None
    version_no: int | None
    # DEC-57: the round of the slip shown (the latest round with a CURRENT slip).
    round_no: int = 1
    lines: list[AcEntryLine]
    lines_needing_data: int
    lines_complete: int
    shipping_lines: int
    is_completed: bool
    completed_by_name: str | None
    completed_at: datetime | None
    can_edit: bool
    can_complete: bool
    complete_blockers: list[str]
    dispatch_slip: DispatchSlipSummary | None
    # DEC-71 (P11): the store flow enters one Challan / CN per goods slip (lines are read-only).
    per_gs: bool = False
    gs_entry: AcGsEntry | None = None
    # Label of the slip from the print template (configuration, "Replacement Slip").
    slip_title: str | None = None
    # DEC-70: the Management e-approval stamp printed on the slips (VALID approval only).
    management_stamp: str | None = None


class AcEntryLineIn(BaseModel):
    line_id: UUID
    cn_no: str | None = Field(default=None, max_length=60)
    cn_date: date | None = None
    cn_value: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    challan_no: str | None = Field(default=None, max_length=60)
    challan_date: date | None = None


class SaveAcEntryIn(BaseModel):
    """Partial saves are allowed; completion is a separate command."""

    ac_action_slip_id: UUID
    lines: list[AcEntryLineIn] = Field(min_length=1, max_length=500)


class SaveGsEntryIn(BaseModel):
    """DEC-71: the goods slip's Challan (only if goods ship) and Credit Note (only if Issue CN).
    A group the goods slip does not need is not sent (null). Partial saves are allowed."""

    ac_action_slip_id: UUID
    challan_no: str | None = Field(default=None, max_length=60)
    challan_date: date | None = None
    cn_no: str | None = Field(default=None, max_length=60)
    cn_date: date | None = None
    cn_value: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)


class ReplacementSlipPrintOut(BaseModel):
    ac_action_slip_id: UUID
    slip_no: str
    version_no: int
    url: str
    expires_in: int
    print_count: int


class CompleteAcEntryIn(BaseModel):
    ac_action_slip_id: UUID
    remarks: str | None = Field(default=None, max_length=1000)


# --- Dispatch Slip ------------------------------------------------------------------------------


class DispatchSlipLine(BaseModel):
    id: UUID
    gs_item_id: UUID
    line_no: int
    product_code: str | None
    product_name: str
    action_code: str
    action_label: str
    condition_label: str | None = None
    qty: int
    challan_no: str
    challan_date: date


class DispatchSlipOut(DispatchSlipSummary):
    gs_id: UUID
    gs_no: str
    gs_status: str
    party_name: str | None
    ac_slip_no: str
    ac_version_no: int
    ac_round_no: int = 1
    dispatch_remarks: str | None
    generated_by_name: str | None
    dispatched_by_name: str | None
    lines: list[DispatchSlipLine]


class DispatchIn(BaseModel):
    """DEC-26 tracking data: date, transporter and a docket or vehicle number."""

    dispatch_date: date
    transporter: str = Field(min_length=1, max_length=120)
    docket_no: str | None = Field(default=None, max_length=60)
    vehicle_no: str | None = Field(default=None, max_length=30)
    remarks: str | None = Field(default=None, max_length=1000)


class DispatchSlipPrintOut(BaseModel):
    dispatch_slip_id: UUID
    slip_no: str
    url: str
    expires_in: int
    print_count: int
