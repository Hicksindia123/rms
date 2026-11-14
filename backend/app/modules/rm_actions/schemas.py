"""Pydantic schemas for Step-3 a) RM item-wise actions and Replacement Slip.

Master plan references: WF r6, BR-19, BR-20, G-08, DEC-12, DEC-13, DEC-33.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class RmActionItem(BaseModel):
    action_code: str = Field(
        ..., description="SEND_NEW, SEND_REPAIRED, ISSUE_CN, NOT_ALLOWED, PENDING_BP"
    )
    qty: int = Field(..., ge=0, description="Allocated quantity for this action")


class RmLineActionInput(BaseModel):
    gs_item_id: UUID
    actions: list[RmActionItem]


class PendencyDetailInput(BaseModel):
    reason: str = Field(..., min_length=1, description="Reason for marking piece(s) Pending (BP)")
    sent_to: str = Field("Repair Team", description="Department or team piece(s) sent to")


class SaveRmActionsRequest(BaseModel):
    lines: list[RmLineActionInput]
    reason: str | None = Field(
        None, description="Reason for revision (mandatory when revising after handover)"
    )
    override_reason: str | None = Field(
        None, description="RM override reason when allocating SEND_*/CN to rejected pieces (DEC-33)"
    )
    pendency_details: dict[str, PendencyDetailInput] | None = Field(
        None, description="Keyed by gs_item_id str for lines where PENDING_BP > 0"
    )


class FinaliseRmActionsRequest(BaseModel):
    notes: str | None = None


class RmActionOptionOut(BaseModel):
    code: str
    label: str
    allowed_status: str
    rule_text: str | None = None
    next_action_text: str | None = None
    sort_order: int


class RmActionAllocationOut(BaseModel):
    action_code: str
    label: str
    qty: int
    reason: str | None = None


class RmActionLineOut(BaseModel):
    gs_item_id: UUID
    line_no: int
    product_id: UUID
    product_code: str
    product_name: str
    received_qty: int
    allowed_qty: int
    not_allowed_qty: int
    allocations: list[dict[str, Any]] = Field(default_factory=list)
    rejections: list[dict[str, Any]] = Field(default_factory=list)
    current_actions: list[RmActionAllocationOut] = Field(default_factory=list)
    pending_qty: int = 0


class RmActionRevisionOut(BaseModel):
    revision_no: int
    decided_by: UUID
    decided_by_name: str
    decided_at: datetime
    reason: str | None = None
    lines: list[dict[str, Any]] = Field(default_factory=list)


class RmActionsResponse(BaseModel):
    gs_id: UUID
    gs_no: str
    status: str
    current_step_code: str | None = None
    current_revision_no: int
    has_open_pendency: bool
    can_revise: bool
    requires_reason_for_revision: bool
    lines: list[RmActionLineOut]
    revision_history: list[RmActionRevisionOut]
    options: list[RmActionOptionOut]


class ReplacementSlipLine(BaseModel):
    line_no: int
    product_code: str
    product_name: str
    received_qty: int
    send_new_qty: int
    send_repaired_qty: int
    issue_cn_qty: int
    not_allowed_qty: int
    pending_bp_qty: int
    rejected_qty: int
    rejection_reasons: list[str] = Field(default_factory=list)
    pending_qty: int
    remarks: str | None = None


class ReplacementSlipResponse(BaseModel):
    gs_id: UUID
    gs_no: str
    party_name: str
    party_code: str | None = None
    station_name: str | None = None
    state_name: str | None = None
    date: str
    revision_no: int
    rm_name: str
    prepared_by: str
    print_count: int
    is_reprint: bool
    watermark: str | None = None
    signature_blocks: list[dict[str, Any]]
    lines: list[ReplacementSlipLine]
    totals: dict[str, int]
    layout: dict[str, Any]


class LineOutcomeDetail(BaseModel):
    functional_good_qty: int = 0
    functional_repaired_qty: int = 0
    non_good_qty: int = 0
    non_sellable_qty: int = 0
    rejected_qty: int = 0


class LineDispatchedDetail(BaseModel):
    dispatched_new_qty: int = 0
    dispatched_repaired_qty: int = 0
    issued_main_store_qty: int = 0


class ResolutionBoardLineOut(BaseModel):
    gs_item_id: UUID
    line_no: int
    product_id: UUID
    product_code: str
    product_name: str
    received_qty: int
    current_actions: list[RmActionAllocationOut] = Field(default_factory=list)
    outcomes: LineOutcomeDetail
    dispatched: LineDispatchedDetail
    suggested_adjustments: list[str] = Field(default_factory=list)
    has_mismatch: bool = False


class ResolutionBoardResponse(BaseModel):
    gs_id: UUID
    gs_no: str
    status: str
    current_step_code: str | None = None
    current_revision_no: int
    lines: list[ResolutionBoardLineOut]
    summary_notes: list[str] = Field(default_factory=list)
