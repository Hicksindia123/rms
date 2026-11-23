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


class ItemConditionQty(BaseModel):
    """DEC-56: one condition of the item's current split (original = counting split)."""

    field_code: str
    field_label: str
    original_qty: int
    current_qty: int


class FinalActionGroup(BaseModel):
    """DEC-57 (Q9): the unit the RM actions: one item + one current condition (DEC-56). Items
    without a condition split have one group with no condition. In a Pending re-action round the
    group's available qty is what the previous round left Pending."""

    condition_field_id: UUID | None = None
    condition_code: str | None = None
    condition_label: str | None = None
    current_qty: int = Field(description="Pieces in the condition now (round 1)")
    at_departments_qty: int = 0
    available_qty: int = Field(description="G-21: to be actioned in this group")
    actioned_qty: int
    is_balanced: bool
    current_actions: list[FinalActionAllocation] = Field(default_factory=list)


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
    # DEC-56: condition split after department work (shown to the RM).
    current_conditions: list[ItemConditionQty] = Field(default_factory=list)
    allowed_actions: list[FinalActionOption] = Field(default_factory=list)
    # Line total per action (all groups of the round).
    current_actions: list[FinalActionAllocation] = Field(default_factory=list)
    # DEC-57: what the RM allocates, per condition.
    groups: list[FinalActionGroup] = Field(default_factory=list)


class FinalActionRevisionLine(BaseModel):
    line_no: int
    action_code: str
    action_label: str
    condition_label: str | None = None
    qty: int


class FinalActionRevision(BaseModel):
    revision_no: int
    round_no: int = 1
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
    round_no: int = 1
    status: str
    is_completed: bool = Field(False, description="Accounts completed this slip (G-22)")
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
    # DEC-57: 1 = the first decision; 2+ = re-action of the pieces still Pending.
    round_no: int = 1
    # Pieces the previous round left Pending (round_no > 1), now in the Pending Hold.
    pending_from_previous_round: int = 0
    # The current round waits for Accounts / dispatch of the previous round.
    waiting_for_previous_round: bool = False
    is_finalised: bool
    # Accounts completed the current round's slip (G-22: frozen).
    is_completed: bool = False
    current_slip: AcSlipVersion | None = None
    lines: list[FinalActionLine] = Field(default_factory=list)
    revisions: list[FinalActionRevision] = Field(default_factory=list)
    slips: list[AcSlipVersion] = Field(default_factory=list)


class FinalActionInput(BaseModel):
    action_code: str = Field(..., min_length=1, max_length=64, pattern=ACTION_CODE_PATTERN)
    qty: int = Field(..., ge=0, le=1_000_000)


class FinalActionLineInput(BaseModel):
    """One item + condition group (DEC-57). `condition_field_id` is omitted / null only for items
    without a condition split."""

    gs_item_id: UUID
    condition_field_id: UUID | None = None
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


# --- DEC-69 (Phase P9): analysis by the Intermediate Store user ---------------------------------


class StoreAnalysisStoreOut(BaseModel):
    """One Intermediate Store's part of a GS: routing progress (P7/P8) and analysis state."""

    store_id: UUID
    store_code: str
    store_name: str
    # AWAITING_ACKNOWLEDGEMENT | ROUTING_PENDING | AT_DEPARTMENTS | READY_FOR_ANALYSIS
    routing_status: str
    # NOT_READY | PENDING | SUBMITTED (computed, not configurable)
    analysis_status: str
    submitted_at: datetime | None = None
    submitted_by_name: str | None = None
    remarks: str | None = None
    total_qty: int | None = None
    # The signed-in user acts for this store (may analyse its lines).
    is_mine: bool = False


class StoreAnalysisGroupOut(BaseModel):
    """DEC-57 group: one item + one current condition (no condition = item without a split)."""

    condition_field_id: UUID | None = None
    condition_code: str | None = None
    condition_label: str | None = None
    qty: int = Field(description="G-21: pieces to decide in this group")
    decisions: list[FinalActionAllocation] = Field(default_factory=list)


class StoreAnalysisItemOut(BaseModel):
    gs_item_id: UUID
    line_no: int
    product_code: str | None = None
    product_name: str
    received_qty: int
    store_id: UUID | None = None
    store_code: str | None = None
    store_name: str | None = None
    is_mine: bool = False
    outcomes: list[OutcomeQty] = Field(default_factory=list)
    # Q15: the store's options (the product's resolved ACTION profile without Issue CN / Pending).
    options: list[FinalActionOption] = Field(default_factory=list)
    groups: list[StoreAnalysisGroupOut] = Field(default_factory=list)


class ManagementApprovalRequestOut(BaseModel):
    id: UUID
    store_id: UUID
    store_name: str
    reason: str
    status: str
    requested_at: datetime
    requested_by_name: str | None = None


class StoreAnalysisGsOut(BaseModel):
    gs_id: UUID
    gs_no: str
    status: str
    party_name: str | None = None
    station_name: str | None = None
    stores: list[StoreAnalysisStoreOut] = Field(default_factory=list)
    items: list[StoreAnalysisItemOut] = Field(default_factory=list)
    # The user's stores whose part may be submitted now.
    submittable_store_ids: list[UUID] = Field(default_factory=list)
    # The user's stores on this GS that submitted their analysis (Q36: they may send it for
    # Management approval).
    approval_store_ids: list[UUID] = Field(default_factory=list)
    can_request_approval: bool = False
    open_approval_request: ManagementApprovalRequestOut | None = None
    approval_requests: list[ManagementApprovalRequestOut] = Field(default_factory=list)


class StoreAnalysisQueueRowOut(BaseModel):
    gs_id: UUID
    gs_no: str
    status: str
    party_name: str | None = None
    station_name: str | None = None
    since: datetime | None = None
    approval_requested: bool = False
    stores: list[StoreAnalysisStoreOut] = Field(default_factory=list)


class StoreAnalysisLineIn(BaseModel):
    """One item + condition group of the store's part (DEC-57). `condition_field_id` is omitted
    only for items without a condition split."""

    gs_item_id: UUID
    condition_field_id: UUID | None = None
    decisions: list[FinalActionInput] = Field(default_factory=list, max_length=10)


class StoreAnalysisSubmitIn(BaseModel):
    store_id: UUID
    lines: list[StoreAnalysisLineIn] = Field(..., min_length=1, max_length=500)
    remarks: str | None = Field(None, max_length=500)
    # DEC-71 (P11) / Q36: "Submit and send for Management approval" in one transaction. The last
    # store's submission routes the goods slip to Accounts at once, so its request must be recorded
    # with the submission (after it, before the Accounts gate).
    management_approval_reason: str | None = Field(None, min_length=3, max_length=500)


class ManagementApprovalRequestIn(BaseModel):
    store_id: UUID = Field(description="The user's store on this GS that sends the request")
    reason: str = Field(..., min_length=3, max_length=500)
