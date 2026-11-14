"""Pydantic schemas for Pendency register and clearance.

Master plan references: WF r7 col K, BR-20, DEC-12, G-08.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ClearPendencyRequest(BaseModel):
    resolution_action: str = Field(
        ...,
        description="Action to assign: SEND_NEW, SEND_REPAIRED, ISSUE_CN, NOT_ALLOWED",
    )
    notes: str = Field(..., min_length=1, description="Clearance diagnostic notes")


class PendencyOut(BaseModel):
    id: UUID
    gs_id: UUID
    gs_no: str
    party_name: str
    gs_item_id: UUID | None
    line_no: int | None
    product_name: str | None
    qty: int
    reason: str
    sent_to: str | None
    blocks_gs: bool
    status: str
    opened_by: UUID
    opened_by_name: str
    opened_at: datetime
    cleared_by: UUID | None = None
    cleared_by_name: str | None = None
    cleared_at: datetime | None = None
    clearance_notes: str | None = None
    resolution_action: str | None = None
    age_days: int = 0
    age_hours: int = 0
