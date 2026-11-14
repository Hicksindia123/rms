"""Pydantic I/O for the workflow task inbox (prompt P2-02)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class MyTaskOut(BaseModel):
    id: UUID
    gs_id: UUID
    step_code: str
    step_label: str | None
    assigned_role_code: str | None
    assigned_role_name: str | None
    status: str
    due_at: datetime | None
    created_at: datetime
    gs_no: str
    gs_status: str
    box_count: int  # deprecated mirror of carton_count (AMD-03)
    carton_count: int
    missing_documentation: bool
    party_name: str | None
    station_name: str | None
