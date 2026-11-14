"""Pydantic schemas for Replacement Dispatch (P3-05).

Master plan references: BR-19, BR-31, BR-32, DEC-26, DEC-33, §8.6.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ReplacementDispatchLineInput(BaseModel):
    gs_item_id: UUID
    qty: int = Field(..., gt=0, description="Quantity to dispatch")
    lot_id: UUID | None = Field(
        None,
        description=(
            "Required for SEND_REPAIRED (FUNCTIONAL_REPAIRED lot); must be null for SEND_NEW "
            "(DEC-26)"
        ),
    )


class ReplacementDispatchCreateRequest(BaseModel):
    gs_id: UUID
    dispatch_type: str = Field(..., description="SEND_NEW or SEND_REPAIRED")
    lines: list[ReplacementDispatchLineInput] = Field(..., min_length=1)
    transporter: str = Field(..., min_length=1, description="Transporter or courier name")
    docket_no: str | None = None
    vehicle_no: str | None = None
    ref_doc_no: str | None = None
    ref_doc_date: str | None = None
    override_reason: str | None = Field(
        None,
        description=(
            "Mandatory when dispatching more than planned RM action or dispatching "
            "rejected/NOT_ALLOWED items (DEC-33)"
        ),
    )
    notes: str | None = None


class ReplacementDispatchLineOut(BaseModel):
    id: UUID
    dispatch_id: UUID
    gs_item_id: UUID
    lot_id: UUID | None = None
    qty: int
    product_code: str
    product_name: str
    condition_class: str | None = None


class ReplacementDispatchOut(BaseModel):
    id: UUID
    dispatch_no: str
    gs_id: UUID
    gs_no: str
    party_name: str
    dispatch_type: str
    transporter: str
    docket_no: str | None = None
    vehicle_no: str | None = None
    ref_doc_no: str | None = None
    ref_doc_date: str | None = None
    status: str
    dispatched_at: datetime
    dispatched_by: UUID
    dispatched_by_name: str
    override_reason: str | None = None
    notes: str | None = None
    total_qty: int = 0
    lines: list[ReplacementDispatchLineOut] = Field(default_factory=list)


class DispatchQueueItemOut(BaseModel):
    gs_id: UUID
    gs_no: str
    party_id: UUID | None = None
    party_name: str
    gs_item_id: UUID
    line_no: int
    product_id: UUID
    product_code: str
    product_name: str
    action_code: str
    planned_qty: int
    dispatched_qty: int
    pending_qty: int
    available_repaired_qty: int = 0


class DispatchCandidateLotOut(BaseModel):
    lot_id: UUID
    stock_item_id: UUID
    product_id: UUID
    product_code: str
    product_name: str
    location_id: UUID
    location_code: str
    condition_class: str
    available_qty: int
    gs_id: UUID | None = None
    gs_no: str | None = None
