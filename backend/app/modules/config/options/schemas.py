"""Schemas for option sets and option items (master plan §3.2, §8.3, §10)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

AllowedStatus = Literal["YES", "NO", "CONDITIONAL"]
SystemBehavior = Literal[
    "SELLABLE",
    "REPACK_OR_TECHNICIAN",
    "TO_TECHNICIAN",
    "TO_SPARE_PARTS",
    "REJECT_HOLD",
    "REJECT_RECORD",
    "HAZARD",
    "SHORT_QTY",
]


class OptionItemBase(BaseModel):
    label: str = Field(..., min_length=1)
    allowed_status: AllowedStatus = "YES"
    rule_text: str | None = None
    next_action_text: str | None = None
    remarks: str | None = None
    system_behavior: SystemBehavior | None = None
    required_fields: list[str] = Field(default_factory=list)
    sort_order: int = 0
    is_active: bool = True


class OptionItemCreate(OptionItemBase):
    code: str = Field(..., pattern=r"^[A-Z][A-Z0-9_]*$")
    source_ref: str | None = None


class OptionItemUpdate(BaseModel):
    label: str | None = Field(None, min_length=1)
    allowed_status: AllowedStatus | None = None
    rule_text: str | None = None
    next_action_text: str | None = None
    remarks: str | None = None
    system_behavior: SystemBehavior | None = None
    required_fields: list[str] | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    reason: str | None = None  # Mandatory when changing allowed_status from NO to YES/CONDITIONAL


class OptionItemOut(OptionItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    option_set_id: UUID
    code: str
    source_ref: str | None = None
    created_at: datetime
    updated_at: datetime


class OptionSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    description: str | None = None
    control_type: str
    source_kind: str
    master_ref_type: str | None = None
    source_ref: str | None = None
    is_system: bool
    is_active: bool
    items: list[OptionItemOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class OptionUsageOut(BaseModel):
    code: str
    usage_count: int
