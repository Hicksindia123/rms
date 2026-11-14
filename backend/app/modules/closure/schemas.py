"""Closure engine API schemas (P3-07: G-15, BR-38, BR-39, §6.5)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChecklistFix(BaseModel):
    """Where to go to fix a failing item (a hash route of the SPA)."""

    label: str
    path: str


class ChecklistItemOut(BaseModel):
    code: str
    rule_ref: str
    applicable: bool
    passed: bool
    explanation: str
    details: dict[str, Any]
    fix: ChecklistFix | None


class ClosureRecordOut(BaseModel):
    closure_type: str
    closure_label: str | None
    checklist_snapshot: dict[str, Any]
    remarks: str | None
    close_count: int
    closed_by_name: str | None
    closed_at: datetime
    reopened_by_name: str | None
    reopened_at: datetime | None
    reopen_reason: str | None
    reopen_count: int


class StageDurationOut(BaseModel):
    status: str
    entered_at: datetime
    left_at: datetime | None
    duration_seconds: int
    by_name: str | None


class ClosureLineOut(BaseModel):
    line_no: int
    product_code: str | None
    product_name: str | None
    received_qty: int


class ClosureCreditNoteOut(BaseModel):
    id: UUID
    cn_type_code: str
    cn_type_label: str | None
    voucher_no: str | None
    voucher_date: date | None
    total_value: Decimal
    issued_at: datetime | None


class ClosureDispatchOut(BaseModel):
    id: UUID
    dispatch_no: str
    dispatch_type: str
    transporter: str
    docket_no: str | None
    vehicle_no: str | None
    qty: int
    dispatched_at: datetime


class ClosureNotificationOut(BaseModel):
    id: UUID
    credit_note_id: UUID | None
    status_code: str
    status_label: str | None
    channel_code: str
    recipient: str
    sent_at: datetime
    sent_by_name: str | None


class ClosureStateOut(BaseModel):
    gs_id: UUID
    gs_no: str
    status: str
    category_code: str | None
    party_name: str | None
    state_name: str | None
    station_name: str | None
    created_at: datetime
    closed_at: datetime | None
    expected_closure_type: str
    expected_closure_label: str | None
    items: list[ChecklistItemOut]
    all_passed: bool
    can_close: bool
    can_reopen: bool
    closure: ClosureRecordOut | None
    lifecycle: list[StageDurationOut]
    total_duration_seconds: int
    lines: list[ClosureLineOut]
    credit_notes: list[ClosureCreditNoteOut]
    dispatches: list[ClosureDispatchOut]
    notifications: list[ClosureNotificationOut]


class CloseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    remarks: str | None = Field(default=None, max_length=2000)


class ReopenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=5, max_length=2000)
