"""Schemas for Audit Explorer and Activity Timeline (P4-04)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AuditLogRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    table_name: str
    row_id: str
    action: str  # INSERT, UPDATE, DELETE
    actor_id: UUID | None
    actor_name: str | None = None
    actor_email: str | None = None
    request_id: str | None
    db_user: str | None
    at: datetime
    changed_fields: list[str] | None = None
    old_values: dict[str, Any] | None = None
    new_values: dict[str, Any] | None = None
    reason: str | None = None


class AuditLogResponse(BaseModel):
    items: list[AuditLogRow]
    total: int
    limit: int
    offset: int


class FieldDiff(BaseModel):
    field: str
    label: str
    old_value: Any
    new_value: Any


class GsActivityItem(BaseModel):
    id: str
    timestamp: datetime
    category: Literal["STATUS", "STOCK", "DOCUMENT", "COMMERCIAL", "NOTIFICATION", "AUDIT"]
    action: str
    title: str
    description: str | None = None
    actor_id: UUID | None = None
    actor_name: str | None = None
    actor_role: str | None = None
    request_id: str | None = None
    diffs: list[FieldDiff] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GsActivityResponse(BaseModel):
    gs_id: UUID
    gs_no: str
    total: int
    items: list[GsActivityItem]


class UserActivityItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    activity_type: str
    session_id: str | None
    ip_address: str | None
    user_agent: str | None
    entity_type: str | None
    entity_id: UUID | None
    details: dict[str, Any]
    request_id: str | None
    created_at: datetime


class UserActivityResponse(BaseModel):
    user_id: UUID
    total: int
    items: list[UserActivityItem]
