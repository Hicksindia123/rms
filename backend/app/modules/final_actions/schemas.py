"""Schemas for RM Final Actions and the "Replacement Slip - A/c Actions" (change plan 2026-11-12
Phase 7; AMD-16, AMD-17; DEC-41; G-21)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

ACTION_CODE_PATTERN = r"^[A-Z][A-Z0-9_]*$"


class FinalActionOption(BaseModel):
    """An action allowed by the product's resolved ACTION profile (AMD-10 / AMD-16)."""

    code: str
    label: str
    requires_cn: bool = False
    requires_challan: bool = False
    sort_order: int = 0


class FinalActionAllocation(BaseModel):
    action_code: str
    label: str
    qty: int


class OutcomeQty(BaseModel):
    """Qty booked back from departments into a terminal outcome head (DEC-43)."""

    outcome_code: str
    outcome_label: str
    is_wastage: bool
    qty: int


class FinalActionLine(BaseModel):
    gs_item_id: UUID
    line_no: int
    product_id: UUID
    product_code: str | None = None
    product_name: str
    counted_qty: int
    at_departments_qty: int
    available_qty: int = Field(description="G-21: counted - at departments")
    actioned_qty: int
    is_balanced: bool = Field(description="G-21: Σ current action qty = available qty")
    outcomes: list[OutcomeQty] = Field(default_factory=list)
    allowed_actions: list[FinalActionOption] = Field(default_factory=list)
    current_actions: list[FinalActionAllocation] = Field(default_factory=list)


class FinalActionRevisionLine(BaseModel):
    line_no: int
    action_code: str
    action_label: str
    qty: int


class FinalActionRevision(BaseModel):
    revision_no: int
    decided_by_name: str | None = None
    decided_at: datetime
    reason: str | None = None
    lines: list[FinalActionRevisionLine] = Field(default_factory=list)


class AcSlipActionTotal(BaseModel):
    action_code: str
    action_label: str
    qty: int


class AcSlipVersion(BaseModel):
    id: UUID
    slip_no: str
    version_no: int
    revision_no: int
    status: str
    finalised_at: datetime
    finalised_by_name: str | None = None
    superseded_at: datetime | None = None
    superseded_by_name: str | None = None
    supersede_reason: str | None = None
    remarks: str | None = None
    total_qty: int = 0
    action_totals: list[AcSlipActionTotal] = Field(default_factory=list)
    print_count: int = 0


class FinalActionsState(BaseModel):
    gs_id: UUID
    gs_no: str
    status: str
    party_name: str | None = None
    on_final_action_flow: bool
    can_edit: bool
    can_finalise: bool
    finalise_blockers: list[str] = Field(default_factory=list)
    current_revision_no: int
    is_finalised: bool
    current_slip: AcSlipVersion | None = None
    lines: list[FinalActionLine] = Field(default_factory=list)
    revisions: list[FinalActionRevision] = Field(default_factory=list)
    slips: list[AcSlipVersion] = Field(default_factory=list)


class FinalActionInput(BaseModel):
    action_code: str = Field(..., min_length=1, max_length=64, pattern=ACTION_CODE_PATTERN)
    qty: int = Field(..., ge=0, le=1_000_000)


class FinalActionLineInput(BaseModel):
    gs_item_id: UUID
    actions: list[FinalActionInput] = Field(default_factory=list, max_length=50)


class SaveFinalActionsIn(BaseModel):
    lines: list[FinalActionLineInput] = Field(..., min_length=1, max_length=500)
    reason: str | None = Field(
        None,
        max_length=500,
        description="Required when revising finalised actions (the current slip is superseded).",
    )


class FinaliseFinalActionsIn(BaseModel):
    remarks: str | None = Field(None, max_length=500)


class AcSlipPrintOut(BaseModel):
    slip_id: UUID
    slip_no: str
    version_no: int
    status: str
    url: str
    expires_in: int
    print_count: int
