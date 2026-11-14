"""P3-02 Servicing schemas (master plan §2.2 Stage-3, BR-23..BR-25, G-10, DEC-14..DEC-17)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TechnicianOut(BaseModel):
    id: UUID
    display_name: str
    is_active: bool


class IntermediateLotOut(BaseModel):
    lot_id: UUID
    gs_id: UUID
    gs_no: str
    product_id: UUID
    product_name: str
    product_code: str
    category_code: str
    supports_battery: bool
    condition_class: str
    source_condition_code: str | None = None
    routing_hint: str | None = None
    requires_evaluation: bool = False
    balance: int


class AllotLineIn(BaseModel):
    lot_id: UUID
    qty: int = Field(gt=0)


class AllotBatchIn(BaseModel):
    technician_id: UUID
    entry_by: UUID | None = None
    notes: str | None = None
    lines: list[AllotLineIn] = Field(min_length=1)


class LineReceiveIn(BaseModel):
    batch_line_id: UUID
    qty_receiving: int = Field(gt=0)
    battery_check_code: str | None = None  # BATTERY_OK, BATTERY_REPLACED
    pieces_checked: int | None = None
    batteries_installed: int | None = None
    battery_type_id: UUID | None = None
    cleaning_code: str | None = None  # CLEANED_SELLABLE, PERMANENT_SCRATCHES
    allocations: dict[str, int]  # FUNCTIONAL_GOOD, FUNCTIONAL_REPAIRED, NON_GOOD, NON_SELLABLE
    evaluation_notes: str | None = None
    technician_remarks: str | None = None


class ReceiveBatchIn(BaseModel):
    lines: list[LineReceiveIn] = Field(min_length=1)


class BatchLineOut(BaseModel):
    id: UUID
    batch_id: UUID
    lot_id: UUID
    product_name: str
    product_code: str
    category_code: str
    supports_battery: bool
    source_condition_code: str | None = None
    routing_hint: str | None = None
    requires_evaluation: bool = False
    evaluation_notes: str | None = None
    qty_allotted: int
    qty_received: int
    status: str


class ReceivingRecordOut(BaseModel):
    id: UUID
    batch_id: UUID
    batch_line_id: UUID
    qty_received: int
    battery_check_code: str | None = None
    pieces_checked: int | None = None
    batteries_installed: int | None = None
    battery_type_name: str | None = None
    cleaning_code: str | None = None
    functional_good_qty: int
    functional_repaired_qty: int
    non_good_qty: int
    non_sellable_qty: int
    evaluation_notes: str | None = None
    technician_remarks: str | None = None
    entry_by_name: str
    received_at: datetime


class BatchDetailOut(BaseModel):
    id: UUID
    batch_no: str
    technician_id: UUID
    technician_name: str
    entry_by: UUID
    entry_by_name: str
    status: str
    transfer_id: UUID | None = None
    allotted_at: datetime
    completed_at: datetime | None = None
    notes: str | None = None
    total_qty_allotted: int
    total_qty_received: int
    lines: list[BatchLineOut]
    receiving_records: list[ReceivingRecordOut]


class BatchSummaryOut(BaseModel):
    id: UUID
    batch_no: str
    technician_name: str
    entry_by_name: str
    status: str
    age_days: int
    allotted_at: datetime
    total_qty_allotted: int
    total_qty_received: int
    line_count: int


class BatteryReconciliationTypeRow(BaseModel):
    battery_type_id: UUID
    battery_type_code: str
    battery_type_name: str
    batteries_installed: int
    battery_stock_movements: int
    discrepancy: int
    ties_out: bool


class BatteryReconciliationOut(BaseModel):
    pieces_checked: int
    pieces_with_battery_replaced: int
    batteries_installed: int
    battery_stock_movements: int
    discrepancy: int
    ties_out: bool
    by_battery_type: list[BatteryReconciliationTypeRow]
