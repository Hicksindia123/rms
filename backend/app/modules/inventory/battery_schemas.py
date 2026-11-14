"""P3-02 Battery schemas for inventory ledger (master plan §2.2 Stage-3, DEC-15)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class BatteryTypeOut(BaseModel):
    id: UUID
    code: str
    name: str
    is_active: bool


class BatteryReceiptIn(BaseModel):
    battery_type: str = Field(min_length=1, description="Battery type code or UUID")
    qty: int = Field(gt=0, description="Quantity of batteries received")
    ref: str = Field(min_length=1, description="Supplier / Inward / Purchase reference")
    notes: str | None = None


class BatteryReceiptOut(BaseModel):
    id: UUID
    battery_type_id: UUID
    battery_type_code: str
    battery_type_name: str
    qty: int
    reference_no: str
    received_by: UUID
    received_by_name: str
    received_at: datetime
    notes: str | None


class BatteryAdjustmentIn(BaseModel):
    battery_type: str = Field(min_length=1, description="Battery type code or UUID")
    qty: int = Field(description="Adjustment quantity (positive or negative, non-zero)")
    reason: str = Field(min_length=1, description="Mandatory reason for adjustment")


class BatteryAdjustmentApproveIn(BaseModel):
    approval_notes: str | None = None


class BatteryAdjustmentRejectIn(BaseModel):
    reason: str = Field(min_length=1)


class BatteryAdjustmentOut(BaseModel):
    id: UUID
    battery_type_id: UUID
    battery_type_code: str
    battery_type_name: str
    qty: int
    reason: str
    status: str
    requested_by: UUID
    requested_by_name: str
    requested_at: datetime
    approved_by: UUID | None = None
    approved_by_name: str | None = None
    approved_at: datetime | None = None
    approval_notes: str | None = None


class BatteryBalanceOut(BaseModel):
    battery_type_id: UUID
    code: str
    name: str
    balance: int
    total_received: int
    total_consumed: int
    total_adjusted: int


class BatteryMovementOut(BaseModel):
    id: UUID
    battery_type_id: UUID
    battery_type_code: str
    battery_type_name: str
    movement_type: str
    qty: int
    from_location: str | None = None
    to_location: str | None = None
    reference_type: str | None = None
    reference_id: UUID | None = None
    created_at: datetime
    created_by_name: str | None = None
