"""Pydantic I/O for Management approval and the e-approval stamp (Phase P10; DEC-70; Q17, Q18)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

# Computed by the system (rms_private.gs_management_approval_state), not configurable options.
ApprovalState = Literal["NONE", "VALID", "CHANGED"]


class ActionOptionOut(BaseModel):
    code: str
    label: str
    requires_cn: bool = False
    requires_challan: bool = False
    sort_order: int = 0


class DecisionOut(BaseModel):
    action_code: str
    label: str
    qty: int
    # DEC-74: the store's "Issue CN Request" (Management decides these pieces).
    is_cn_request: bool = False


class GroupOut(BaseModel):
    """DEC-57 group: one item + current condition (no condition = item without a split)."""

    condition_field_id: UUID | None = None
    condition_code: str | None = None
    condition_label: str | None = None
    qty: int = Field(description="G-21: pieces of this item + condition")
    decisions: list[DecisionOut] = Field(default_factory=list)
    cn_requested_qty: int = Field(0, description="DEC-74: pieces still on Issue CN Request")


class ItemOut(BaseModel):
    gs_item_id: UUID
    line_no: int
    product_code: str | None = None
    product_name: str
    received_qty: int
    store_code: str | None = None
    store_name: str | None = None
    # DEC-70: every option of the product's resolved ACTION profile (incl. Issue CN; Pending is
    # not used on the Intermediate Store flow, DEC-69).
    options: list[ActionOptionOut] = Field(default_factory=list)
    groups: list[GroupOut] = Field(default_factory=list)


class StoreProgressOut(BaseModel):
    store_id: UUID
    store_code: str
    store_name: str
    analysis_status: str
    submitted_at: datetime | None = None
    submitted_by_name: str | None = None
    remarks: str | None = None


class RequestOut(BaseModel):
    id: UUID
    store_id: UUID
    store_name: str
    reason: str
    status: str
    requested_at: datetime
    requested_by_name: str | None = None
    resolved_at: datetime | None = None
    resolved_by_name: str | None = None
    approval_id: UUID | None = None


class ChangeDecisionOut(BaseModel):
    action_code: str
    label: str
    qty: int


class ChangeOut(BaseModel):
    line_no: int
    product_name: str
    condition_label: str | None = None
    before: list[ChangeDecisionOut] = Field(default_factory=list)
    after: list[ChangeDecisionOut] = Field(default_factory=list)
    reason: str


class RevisionOut(BaseModel):
    revision_no: int
    made_at: datetime
    made_by_name: str | None = None
    changes: list[ChangeOut] = Field(default_factory=list)


class ApprovalOut(BaseModel):
    id: UUID
    approval_no: int
    approver_name: str
    approver_role: str
    approved_at: datetime
    revision_no: int
    snapshot_sha256: str
    short_ref: str = Field(description="First 12 hex characters of the SHA-256")
    has_issue_cn: bool
    remarks: str | None = None
    request_id: UUID | None = None


class StampOut(BaseModel):
    """DEC-70 (Q17): the e-approval stamp of a goods slip (latest approval) and its state."""

    gs_id: UUID
    gs_no: str
    state: ApprovalState
    approval: ApprovalOut | None = None
    # "Digitally approved by Management — <name>, <date time>, ref <short hash>" (VALID only).
    stamp_text: str | None = None
    disclaimer: str = (
        "System e-approval: non-official, non-legal; computed by RMS (no digital signature "
        "certificate)."
    )


class VerifyOut(BaseModel):
    """DEC-70: the hash recomputed now. VALID = the stored snapshot is intact and the goods slip
    still has exactly the approved lines + decisions."""

    gs_id: UUID
    result: ApprovalState
    approval: ApprovalOut | None = None
    stored_sha256: str | None = None
    current_sha256: str
    integrity_ok: bool = Field(description="The stored snapshot still hashes to the stored hash")
    checked_at: datetime


class AccountsGateOut(BaseModel):
    """DEC-70 / Q18 part of the Accounts gate (P11 adds the rest)."""

    passes: bool
    problem: str | None = None


class ManagementGsOut(BaseModel):
    gs_id: UUID
    gs_no: str
    status: str
    party_name: str | None = None
    station_name: str | None = None
    stores: list[StoreProgressOut] = Field(default_factory=list)
    items: list[ItemOut] = Field(default_factory=list)
    # DEC-74: pieces still on a store's Issue CN Request (approval refused while > 0).
    cn_request_qty: int = 0
    # The signed-in user may change decisions and approve now (ANALYSIS_COMPLETED + approve).
    can_edit: bool = False
    can_approve: bool = False
    # Why not (e.g. stores still to submit), shown on the page.
    blocked_reason: str | None = None
    open_request: RequestOut | None = None
    requests: list[RequestOut] = Field(default_factory=list)
    revisions: list[RevisionOut] = Field(default_factory=list)
    approvals: list[ApprovalOut] = Field(default_factory=list)
    stamp: StampOut
    accounts_gate: AccountsGateOut
    # DEC-71 (P11): set when saving a change reopens a goods slip at Accounts / on hold.
    reopen_notice: str | None = None


class QueueRowOut(BaseModel):
    gs_id: UUID
    gs_no: str
    status: str
    party_name: str | None = None
    station_name: str | None = None
    since: datetime | None = None
    request_id: UUID | None = None
    request_reason: str | None = None
    request_store_name: str | None = None
    requested_at: datetime | None = None
    requested_by_name: str | None = None
    approval_state: ApprovalState
    has_issue_cn: bool = False
    # DEC-74: pieces still on a store's Issue CN Request.
    cn_request_qty: int = 0
    waiting_store_codes: list[str] = Field(default_factory=list)


class DecisionIn(BaseModel):
    action_code: str = Field(..., min_length=1, max_length=64)
    qty: int = Field(..., ge=0, le=100000)


class ChangeIn(BaseModel):
    """The new decisions of one item + condition (replaces its current ones) and why."""

    gs_item_id: UUID
    condition_field_id: UUID | None = None
    decisions: list[DecisionIn] = Field(..., min_length=1, max_length=10)
    reason: str = Field(..., min_length=3, max_length=500)


class ChangesIn(BaseModel):
    changes: list[ChangeIn] = Field(..., min_length=1, max_length=500)


class ApproveIn(BaseModel):
    remarks: str | None = Field(None, max_length=500)
