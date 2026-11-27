"""Pydantic I/O models for the E-Commerce settlement (DEC-76). Request models forbid unknown
fields."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SheetStatus = Literal["PENDING_ACCOUNTS", "COMPLETED"]
ReceiptSource = Literal["UNBOXING", "REPAIR"]
ReceiptStatus = Literal["PENDING", "ACKNOWLEDGED"]
RepairStatus = Literal["AT_DEPARTMENT", "RETURNED"]


class SOptionOut(BaseModel):
    code: str
    label: str


class LocationOut(BaseModel):
    id: UUID
    code: str
    name: str


# --- unboxing -----------------------------------------------------------------------------------
class UnboxingRowOut(BaseModel):
    return_id: UUID
    return_no: str
    entry_date: date
    platform_code: str
    platform_label: str
    order_id: str
    product_text: str
    is_company_product: bool
    qty: int
    qc_routing_label: str
    resolution_code: str
    resolution_label: str
    resolution_qty: int
    resolution_note: str | None
    resolved_at: datetime
    cn_qty: int
    store_name: str | None


class RepairRowOut(BaseModel):
    repair_id: UUID
    return_id: UUID
    return_no: str
    platform_label: str
    order_id: str
    product_text: str
    location_name: str
    qty_sent: int
    sent_at: datetime


class UnboxingQueueOut(BaseModel):
    platforms: list[SOptionOut]
    buckets: list[SOptionOut]
    repair_locations: list[LocationOut]
    rows: list[UnboxingRowOut]
    repairs: list[RepairRowOut]


class UnboxLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    return_id: UUID
    good_qty: int = Field(ge=0, le=100000)
    repair_qty: int = Field(ge=0, le=100000)
    wastage_qty: int = Field(ge=0, le=100000)
    repair_location_id: UUID | None = None
    note: str | None = Field(default=None, max_length=300)


class UnboxBatchIn(BaseModel):
    """One platform per batch: the batch becomes one action sheet."""

    model_config = ConfigDict(extra="forbid")

    platform_code: str = Field(min_length=1, max_length=50)
    lines: list[UnboxLineIn] = Field(min_length=1, max_length=200)


class RepairReturnIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qty_ok: int = Field(ge=0, le=100000)
    qty_scrap: int = Field(ge=0, le=100000)
    note: str | None = Field(default=None, max_length=300)


# --- store receipts -----------------------------------------------------------------------------
class StoreReceiptRowOut(BaseModel):
    id: UUID
    return_id: UUID
    return_no: str
    platform_label: str
    order_id: str
    product_code: str | None
    product_name: str | None
    source: ReceiptSource
    source_label: str
    store_id: UUID
    store_name: str
    from_location_name: str
    qty: int
    status: ReceiptStatus
    created_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by_name: str | None
    can_acknowledge: bool


class StoreReceiptsOut(BaseModel):
    rows: list[StoreReceiptRowOut]


class AcknowledgeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_ids: list[UUID] = Field(min_length=1, max_length=200)


# --- action sheets ------------------------------------------------------------------------------
class ActionSheetLineOut(BaseModel):
    return_id: UUID
    return_no: str
    entry_date: date
    order_id: str
    product_text: str
    qty_received: int
    resolution_code: str
    resolution_label: str
    resolution_qty: int
    cn_qty: int
    good_qty: int
    repair_qty: int
    wastage_qty: int
    status: str
    status_label: str


class ActionSheetOut(BaseModel):
    id: UUID
    sheet_no: str
    platform_code: str
    platform_label: str
    status: SheetStatus
    status_label: str
    created_at: datetime
    created_by_name: str | None
    total_received: int
    total_cn_qty: int
    cn_no: str | None
    cn_date: date | None
    cn_value: Decimal | None
    remarks: str | None
    completed_at: datetime | None
    completed_by_name: str | None
    company_name: str | None
    business_today: date
    lines: list[ActionSheetLineOut]


class ActionSheetRowOut(BaseModel):
    id: UUID
    sheet_no: str
    platform_label: str
    status: SheetStatus
    status_label: str
    created_at: datetime
    orders: int
    total_received: int
    total_cn_qty: int
    cn_no: str | None


class ActionSheetListOut(BaseModel):
    status_options: list[SOptionOut]
    rows: list[ActionSheetRowOut]


class CompleteSheetIn(BaseModel):
    """The credit note (same data as the offline Accounts entry, DEC-71): number, date, value."""

    model_config = ConfigDict(extra="forbid")

    cn_no: str | None = Field(default=None, max_length=60)
    cn_date: date | None = None
    cn_value: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    remarks: str | None = Field(default=None, max_length=1000)


# --- per return (shown on the E-Commerce Return detail) -----------------------------------------
class ReturnRepairOut(BaseModel):
    id: UUID
    location_name: str
    status: RepairStatus
    qty_sent: int
    qty_ok: int | None
    qty_scrap: int | None
    return_note: str | None
    returned_at: datetime | None
    returned_by_name: str | None


class ReturnReceiptOut(BaseModel):
    id: UUID
    source: ReceiptSource
    store_name: str
    qty: int
    status: ReceiptStatus
    acknowledged_at: datetime | None
    acknowledged_by_name: str | None


class ReturnSettlementOut(BaseModel):
    action_sheet_id: UUID
    sheet_no: str
    sheet_status: SheetStatus
    good_qty: int
    repair_qty: int
    wastage_qty: int
    cn_qty: int
    unbox_note: str | None
    unboxed_at: datetime
    unboxed_by_name: str | None
    repair_location_name: str | None
    repair: ReturnRepairOut | None
    receipts: list[ReturnReceiptOut]
