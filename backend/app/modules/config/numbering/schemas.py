"""Pydantic schemas for number series management and preview (prompt P1-08)."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class NumberSeriesUpdate(BaseModel):
    name: str | None = Field(None, min_length=1)
    prefix: str | None = None
    pattern: str = Field(
        ...,
        pattern=r"^.*\{SEQ(:[1-9][0-9]?)?\}.*$",
        description=(
            "Pattern containing tokens like {PREFIX}, {STORE}, {FY}, {YYYY}, {YY}, {MM}, {SEQ:n}"
        ),
    )
    reset_policy: str = Field(..., pattern="^(NEVER|YEARLY_FY|MONTHLY)$")
    fy_start_month: int = Field(4, ge=1, le=12)
    fy_format: str = Field("LONG", pattern="^(LONG|COMPACT|SHORT)$")
    start_value: int = Field(1, ge=1)
    is_active: bool = True
    reason: str | None = Field(None, description="Reason for configuration change")


class NumberSeriesOut(BaseModel):
    id: UUID
    code: str
    name: str
    prefix: str | None = None
    pattern: str
    reset_policy: str
    fy_start_month: int
    fy_format: str
    start_value: int
    is_active: bool
    is_provisional_gs: bool = False
    max_used_counter: int = 0
    created_at: datetime
    updated_at: datetime


class NumberPreviewRequest(BaseModel):
    count: int = Field(3, ge=1, le=10)
    on_date: date | None = None


class NumberPreviewOut(BaseModel):
    code: str
    pattern: str
    on_date: date
    fy_string: str
    period_key: str
    next_numbers: list[str]
