"""Pydantic schemas for configuration audit history and static system guards (prompt P1-08)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ConfigChangeLogItem(BaseModel):
    id: int
    entity_type: str
    entity_id: str | None = None
    action: str
    before: Any = None
    after: Any = None
    reason: str | None = None
    changed_by: UUID | None = None
    actor_email: str | None = None
    actor_name: str | None = None
    request_id: str | None = None
    changed_at: datetime


class ConfigHistoryResponse(BaseModel):
    items: list[ConfigChangeLogItem]
    total: int
    page: int
    page_size: int


class SystemGuardItem(BaseModel):
    code: str = Field(..., pattern=r"^G-(0[1-9]|1[0-9]|2[0-2])$")  # G-19..G-22: 2026-11
    name: str
    statement: str
    enforcement_layer: str
    is_locked: bool = True
