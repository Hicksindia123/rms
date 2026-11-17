"""RM Review schemas (Change plan 2026-11-12 Phase 5, AMD-12, AMD-13, G-19)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.modules.itemization.schemas import (
    ItemBucketIn,
    ItemBucketOut,
    ItemCountIn,
    ItemCountOut,
    ResolvedBucketField,
)


class RmReviewHeaderOut(BaseModel):
    id: UUID
    gs_no: str
    status: str
    party_id: UUID | None = None
    party_name: str | None = None
    station_name: str | None = None
    doc_type: str | None = None
    doc_no: str | None = None
    doc_date: date | None = None
    transporter_name: str | None = None
    docket_no: str | None = None
    carton_count: int = 0
    counted_by: UUID | None = None
    counted_by_name: str | None = None
    category_code: str | None = None
    created_at: datetime


class RmReviewDocumentOut(BaseModel):
    id: UUID
    document_type: str
    document_number: str | None = None
    document_date: date | None = None
    file_url: str | None = None
    file_name: str | None = None


class RmReviewCartonVideoOut(BaseModel):
    id: UUID
    carton_no: int | None = None
    file_url: str
    file_name: str
    created_at: datetime


class RmReviewItemOut(BaseModel):
    item_id: UUID
    product_id: UUID
    sku_code: str
    sku_name: str
    documented_qty: int
    received_qty: int
    short_qty: int
    excess_qty: int
    allowed_buckets: list[ResolvedBucketField]
    allowed_counts: list[ResolvedBucketField]  # AMD-11, same resolution as categorisation
    buckets: list[ItemBucketOut]
    total_bucket_qty: int
    is_conserved: bool  # G-19: total_bucket_qty == received_qty
    counts: list[ItemCountOut]


class RmReviewRevisionOut(BaseModel):
    id: UUID
    revision_no: int
    action: str  # SUBMITTED, RM_EDIT, RM_SENT_BACK, RM_APPROVED
    items_snapshot: list[dict[str, Any]]
    remarks: str | None = None
    created_by: UUID
    created_by_name: str | None = None
    created_at: datetime


class TransferSlipSummaryOut(BaseModel):
    id: UUID
    transfer_no: str
    status: str
    from_location_code: str
    to_location_code: str
    total_lines: int
    total_qty: int


class RmReviewDataOut(BaseModel):
    goods_slip: RmReviewHeaderOut
    documents: list[RmReviewDocumentOut]
    carton_videos: list[RmReviewCartonVideoOut]
    items: list[RmReviewItemOut]
    revisions: list[RmReviewRevisionOut]
    transfer_slip: TransferSlipSummaryOut | None = None
    all_conserved: bool
    can_review: bool


class RmEditItemIn(BaseModel):
    documented_qty: int | None = None
    received_qty: int | None = None
    buckets: list[ItemBucketIn]
    counts: list[ItemCountIn] = Field(default_factory=list)
    remarks: str | None = None


class RmAddLineIn(BaseModel):
    product_id: UUID
    documented_qty: int = Field(default=0, ge=0)
    received_qty: int = Field(default=0, ge=0)
    buckets: list[ItemBucketIn]
    counts: list[ItemCountIn] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def check_reason(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Reason cannot be empty or whitespace only")
        return s


class RmRemoveLineIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def check_reason(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Reason cannot be empty or whitespace only")
        return s


class RmChangeProductIn(BaseModel):
    product_id: UUID
    documented_qty: int | None = Field(default=None, ge=0)
    received_qty: int | None = Field(default=None, ge=0)
    buckets: list[ItemBucketIn]
    counts: list[ItemCountIn] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def check_reason(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Reason cannot be empty or whitespace only")
        return s


class RmSendBackIn(BaseModel):
    remarks: str = Field(min_length=3, max_length=2000)


class RmApproveIn(BaseModel):
    remarks: str | None = None


class RmApproveOut(BaseModel):
    goods_slip_id: UUID
    status: str
    transfer_id: UUID
    transfer_no: str
    message: str
