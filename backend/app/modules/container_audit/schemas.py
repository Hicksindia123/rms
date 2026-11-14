"""Schemas for daily DMT container audit (P2-06, BR-18, DEC-08)."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ContainerAuditLineIn(BaseModel):
    container_id: UUID
    counted_qty: int = Field(ge=0, description="Pieces counted inside this container")
    sellable_packaging_qty: int = Field(ge=0, default=0, description="Sellable packaging separated")
    remarks: str | None = Field(default=None, max_length=1000)


class ContainerAuditLineOut(BaseModel):
    id: UUID | None = None
    container_id: UUID
    container_code: str
    container_barcode: str
    container_name: str | None = None
    counted_qty: int = 0
    sellable_packaging_qty: int = 0
    remarks: str | None = None
    yesterday_counted_qty: int | None = None
    yesterday_sellable_packaging_qty: int | None = None


class ContainerAuditDayOut(BaseModel):
    id: UUID
    audit_date: date
    status: str
    is_late: bool
    late_reason: str | None = None
    confirmed: bool
    confirmed_by: UUID | None = None
    confirmed_by_name: str | None = None
    confirmed_at: datetime | None = None
    remarks: str | None = None
    created_at: datetime


class TodayAuditOut(BaseModel):
    day: ContainerAuditDayOut
    containers: list[ContainerAuditLineOut]
    checkbox_label: str
    can_edit: bool
    can_confirm: bool


class SaveLinesIn(BaseModel):
    lines: list[ContainerAuditLineIn]


class ConfirmAuditIn(BaseModel):
    confirmed: bool = Field(default=True, description="Containers Checked & Counted Daily")
    late_reason: str | None = Field(
        default=None, description="Mandatory if audit date is before today"
    )
    remarks: str | None = Field(default=None, max_length=1000)
    lines: list[ContainerAuditLineIn] | None = Field(
        default=None, description="Optional lines to save along with confirmation"
    )


class CalendarDayOut(BaseModel):
    audit_date: date
    status: str  # PENDING, CONFIRMED, LATE, MISSED
    is_late: bool
    confirmed: bool
    confirmed_at: datetime | None = None
    total_containers_counted: int = 0
    total_sellable_packaging_qty: int = 0
    remarks: str | None = None


class CalendarSummaryOut(BaseModel):
    from_date: date
    to_date: date
    days: list[CalendarDayOut]
    today_status: str
