"""Transfer slip I/O models (Phase P5, DEC-65)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class StoreRefOut(_Out):
    id: UUID
    code: str
    name: str


class PendingBucketOut(_Out):
    field_code: str | None
    label: str
    qty: int


class PendingLineOut(_Out):
    item_id: UUID
    line_no: int
    product_code: str | None
    product_name: str
    documented_qty: int
    received_qty: int
    store: StoreRefOut | None
    buckets: list[PendingBucketOut]
    # Already on a live slip (the GS came back after a void of another store's slip).
    on_slip_no: str | None = None


class EditRequestOut(_Out):
    id: UUID
    gs_id: UUID
    gs_no: str
    party_name: str | None = None
    reason: str
    status: str
    requested_by_name: str | None
    requested_at: datetime
    resolved_by_name: str | None = None
    resolved_at: datetime | None = None
    resolution_note: str | None = None


class PendingGsOut(_Out):
    gs_id: UUID
    gs_no: str
    party_id: UUID | None
    party_name: str | None
    station_name: str | None
    state_name: str | None
    cartons: int | None
    received_date: date | None
    locked_at: datetime | None
    stores: list[StoreRefOut]
    physical_qty: int
    lines: list[PendingLineOut]
    open_edit_request: EditRequestOut | None = None
    # Some lines are already on a live slip; generation covers only the others.
    partially_on_slips: bool = False


class GenerateIn(BaseModel):
    gs_ids: list[UUID] = Field(min_length=1, max_length=200)

    @field_validator("gs_ids")
    @classmethod
    def _unique(cls, v: list[UUID]) -> list[UUID]:
        if len(set(v)) != len(v):
            raise ValueError("Each goods slip may be selected once")
        return v


class SlipSummaryOut(_Out):
    id: UUID
    slip_no: str
    store: StoreRefOut
    status: str
    gs_count: int
    gs_nos: list[str]
    relevant_qty: int
    grand_total_qty: int
    generated_by_name: str | None
    generated_at: datetime
    voided_at: datetime | None = None
    void_reason: str | None = None


class GenerateOut(_Out):
    slips: list[SlipSummaryOut]
    goods_slip_ids: list[UUID]


class SlipGsOut(_Out):
    gs_id: UUID
    gs_no: str
    party_name: str | None
    station_name: str | None
    state_name: str | None
    cartons: int | None
    received_date: date | None
    relevant_qty: int
    total_qty: int


class SlipLineOut(_Out):
    id: UUID
    gs_id: UUID
    gs_item_id: UUID
    line_no: int
    product_code: str | None
    product_name: str
    bucket_label: str | None
    qty: int
    is_relevant: bool
    belongs_store_name: str


class SlipDetailOut(SlipSummaryOut):
    custody_transfer_id: UUID
    goods_slips: list[SlipGsOut]
    lines: list[SlipLineOut]
    acknowledged_by_name: str | None = None
    acknowledged_at: datetime | None = None


class SlipPage(_Out):
    items: list[SlipSummaryOut]
    total: int


class EditRequestIn(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)

    @field_validator("reason")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Give a reason (at least 3 characters)")
        return v


class ResolveEditRequestIn(BaseModel):
    outcome: Literal["EDITED", "REJECTED"]
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("note")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return v.strip() or None if v is not None else None


class GsTransferSlipsOut(_Out):
    """Slips and edit requests of one GS (GS screens)."""

    gs_id: UUID
    slips: list[SlipSummaryOut]
    edit_requests: list[EditRequestOut]
    open_edit_request: EditRequestOut | None
