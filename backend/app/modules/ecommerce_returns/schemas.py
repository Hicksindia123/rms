"""Pydantic I/O models for E-Commerce Returns (DEC-73). Request models forbid unknown fields."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.attachments.schemas import SignedPutUpload, TusUpload
from app.modules.ecommerce_settlement.schemas import ReturnSettlementOut

# DEC-76 adds PENDING_UNBOXING (executive finished) and UNBOXED (on an action sheet).
ReturnStatus = Literal[
    "DRAFT",
    "IN_CHECKING",
    "PENDING_TICKET",
    "TICKET_RAISED",
    "PENDING_UNBOXING",
    "UNBOXED",
    "CLOSED",
    "VOIDED",
]
ProductTypeCode = Literal["COMPANY_PRODUCT", "DIFFERENT_PRODUCT"]
QcRoutingCode = Literal["TICKET_RAISE", "ISSUE_TO_CHECKING"]
ResponseCode = Literal["REJECTED", "CLAIM_RECEIVED", "PENDING"]
MediaKind = Literal["PACKAGE_VIDEO", "IMAGE"]
SlaState = Literal["ON_TIME", "OVERDUE", "RAISED_ON_TIME", "RAISED_LATE"]


# --- form configuration ------------------------------------------------------------------------
class OptionOut(BaseModel):
    code: str
    label: str


class VideoRuleOut(BaseModel):
    mime_types: list[str]
    extensions: list[str]
    max_bytes: int


class ImageRuleOut(BaseModel):
    mime_types: list[str]
    extensions: list[str]
    max_bytes_each: int
    max_total_bytes: int


class FormConfigOut(BaseModel):
    """Everything the E-Commerce gate form needs; labels and limits come from configuration."""

    return_types: list[OptionOut]
    platforms: list[OptionOut]
    product_types: list[OptionOut]
    qc_routings: list[OptionOut]
    business_today: date
    min_entry_date: date | None
    order_id_pattern: str
    video: VideoRuleOut
    images: ImageRuleOut
    ticket_sla_hours: int


class ProductLookupOut(BaseModel):
    id: UUID
    code: str
    name: str


class OrderMatchOut(BaseModel):
    id: UUID
    return_no: str
    entry_date: date
    platform_label: str
    status: ReturnStatus
    status_label: str


# --- create / media ----------------------------------------------------------------------------
class MediaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mime_type: str = Field(min_length=3, max_length=100)
    size_bytes: int = Field(gt=0)
    file_name: str | None = Field(default=None, max_length=255)


class ReturnCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_date: date
    platform_code: str = Field(min_length=1, max_length=50)
    order_id: str = Field(min_length=1, max_length=60)
    product_type_code: ProductTypeCode
    product_id: UUID | None = None
    different_product_desc: str | None = Field(default=None, max_length=500)
    qty: int = Field(ge=1, le=100000)
    qc_routing_code: QcRoutingCode
    video: MediaIn
    images: list[MediaIn] = Field(default_factory=list, max_length=30)


class MediaOut(BaseModel):
    id: UUID
    kind: MediaKind
    mime_type: str
    size_bytes: int
    file_name: str | None
    status: Literal["PENDING_UPLOAD", "CONFIRMED", "REJECTED"]
    confirmed_at: datetime | None


class MediaUploadOut(BaseModel):
    media: MediaOut
    upload: SignedPutUpload | TusUpload = Field(discriminator="method")


class ConfirmMediaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_path: str | None = Field(default=None, max_length=300)


class DownloadOut(BaseModel):
    url: str
    expires_in: int
    mime_type: str


# --- return ------------------------------------------------------------------------------------
class TicketOut(BaseModel):
    id: UUID
    sla_due_at: datetime
    sla_state: SlaState
    minutes_to_due: int | None
    assigned_handler_id: UUID | None
    assigned_handler_name: str | None
    raised_at: datetime | None
    response_code: ResponseCode | None
    response_label: str | None
    rejection_remark: str | None
    claim_amount: Decimal | None
    responded_at: datetime | None
    responded_by_name: str | None
    closed_at: datetime | None
    closed_by_name: str | None
    follow_up_count: int = 0
    last_follow_up_at: datetime | None = None
    next_follow_up_on: date | None = None


class EventOut(BaseModel):
    event_code: str
    from_status: str | None
    to_status: str | None
    details: dict[str, Any]
    actor_name: str | None
    created_at: datetime


class ReturnOut(BaseModel):
    id: UUID
    return_no: str
    entry_date: date
    platform_code: str
    platform_label: str
    order_id: str
    product_type_code: ProductTypeCode
    product_type_label: str
    product_id: UUID | None
    product_code: str | None
    product_name: str | None
    different_product_desc: str | None
    qty: int
    qc_routing_code: QcRoutingCode
    qc_routing_label: str
    status: ReturnStatus
    status_label: str
    created_at: datetime
    created_by_name: str | None
    submitted_at: datetime | None
    void_reason: str | None
    voided_at: datetime | None
    closed_at: datetime | None
    # DEC-76: the E-Commerce Executive's portal resolution and the settlement after unboxing.
    resolution_code: str | None
    resolution_label: str | None
    resolution_qty: int | None
    resolution_note: str | None
    resolved_at: datetime | None
    resolved_by_name: str | None
    settlement: ReturnSettlementOut | None
    media: list[MediaOut]
    ticket: TicketOut | None
    events: list[EventOut]


class CreateOut(BaseModel):
    ecommerce_return: ReturnOut
    uploads: list[MediaUploadOut]


class ReturnRowOut(BaseModel):
    id: UUID
    return_no: str
    entry_date: date
    platform_label: str
    order_id: str
    product_text: str
    qty: int
    qc_routing_code: QcRoutingCode
    qc_routing_label: str
    status: ReturnStatus
    status_label: str
    created_at: datetime
    ticket: TicketOut | None


class ReturnListOut(BaseModel):
    status_options: list[OptionOut]
    rows: list[ReturnRowOut]


class VoidIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)


# --- tickets -----------------------------------------------------------------------------------
class TicketResponseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response_code: ResponseCode
    rejection_remark: str | None = Field(default=None, max_length=1000)
    claim_amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)


class TicketRowOut(BaseModel):
    return_id: UUID
    return_no: str
    entry_date: date
    platform_label: str
    order_id: str
    product_text: str
    qty: int
    status: ReturnStatus
    status_label: str
    ticket: TicketOut


class TicketQueueOut(BaseModel):
    response_options: list[OptionOut]
    resolution_options: list[OptionOut]
    rows: list[TicketRowOut]


# --- DEC-76: the E-Commerce Executive's resolution and follow-ups --------------------------------
class ResolutionIn(BaseModel):
    """What the portal shows for the order (ECOM_PORTAL_RESOLUTION code) and its qty."""

    model_config = ConfigDict(extra="forbid")

    resolution_code: str = Field(min_length=1, max_length=50)
    resolution_qty: int = Field(ge=1, le=100000)
    resolution_note: str | None = Field(default=None, max_length=200)


class FollowUpIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=3, max_length=300)
    next_follow_up_on: date | None = None


class PortalCheckRowOut(BaseModel):
    return_id: UUID
    return_no: str
    entry_date: date
    platform_label: str
    order_id: str
    product_text: str
    qty: int
    submitted_at: datetime | None


class PortalCheckQueueOut(BaseModel):
    resolution_options: list[OptionOut]
    rows: list[PortalCheckRowOut]
