"""Pydantic schemas for Step-6 Store Issues (P3-05).

Master plan references: BR-19, BR-31, DEC-21, G-04.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class StoreIssueLineInput(BaseModel):
    lot_id: UUID
    qty: int = Field(..., gt=0, description="Quantity of functional units to issue")


class StoreIssueCreateRequest(BaseModel):
    lines: list[StoreIssueLineInput] = Field(..., min_length=1)
    issue_type_code: str = Field(
        "ISSUE_MAIN_STORE", description="Issue type, e.g. ISSUE_MAIN_STORE"
    )
    notes: str | None = None


class StoreIssueLineOut(BaseModel):
    id: UUID
    issue_id: UUID
    lot_id: UUID
    qty: int
    product_code: str
    product_name: str
    condition_class: str
    gs_id: UUID | None = None
    gs_no: str | None = None


class StoreIssueOut(BaseModel):
    id: UUID
    issue_no: str
    issue_type_code: str
    from_location_id: UUID
    from_location_name: str
    to_location_id: UUID
    to_location_name: str
    status: str
    custody_transfer_id: UUID | None = None
    notes: str | None = None
    created_at: datetime
    created_by: UUID
    created_by_name: str
    acknowledged_at: datetime | None = None
    acknowledged_by: UUID | None = None
    acknowledged_by_name: str | None = None
    total_qty: int = 0
    lines: list[StoreIssueLineOut] = Field(default_factory=list)


class StoreIssueCandidateLotOut(BaseModel):
    lot_id: UUID
    stock_item_id: UUID
    product_id: UUID
    product_code: str
    product_name: str
    condition_class: str
    available_qty: int
    gs_id: UUID | None = None
    gs_no: str | None = None


class StoreIssuePrintLine(BaseModel):
    line_no: int
    product_code: str
    product_name: str
    condition_class: str
    gs_no: str | None = None
    qty: int


class StoreIssuePrintResponse(BaseModel):
    issue_no: str
    issue_date: str
    issue_type_code: str
    from_location: str
    to_location: str
    issued_by_name: str
    acknowledged_by_name: str | None = None
    status: str
    total_qty: int
    notes: str | None = None
    lines: list[StoreIssuePrintLine]
    signature_blocks: list[dict[str, Any]]
