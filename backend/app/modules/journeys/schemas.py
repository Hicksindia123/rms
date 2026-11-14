"""Pydantic I/O for role journeys (change plan Phase 10, AMD-22)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

JourneyKind = Literal["STEP", "TOOL"]


class JourneyNext(BaseModel):
    """The GS waiting longest at a step (the next one to act on)."""

    gs_id: UUID
    gs_no: str
    party_name: str | None
    station_name: str | None
    target_id: UUID
    since: datetime | None


class JourneyEntry(BaseModel):
    code: str
    label: str
    hint: str | None
    kind: JourneyKind
    screen_key: str
    item_screen_key: str | None
    queue_code: str | None
    count: int | None = None
    next: JourneyNext | None = None


class MyJourneyOut(BaseModel):
    entries: list[JourneyEntry]
    hidden_features: list[str]


class JourneyQueueItem(BaseModel):
    gs_id: UUID
    gs_no: str
    party_name: str | None
    station_name: str | None
    target_id: UUID
    since: datetime | None


class JourneyQueueOut(BaseModel):
    code: str
    label: str
    hint: str | None
    item_screen_key: str | None
    items: list[JourneyQueueItem]
    total: int


# --- admin ---------------------------------------------------------------------------------------


class JourneyStepOut(BaseModel):
    code: str
    label: str
    hint: str | None
    kind: JourneyKind
    screen_key: str
    item_screen_key: str | None
    queue_code: str | None
    feature_code: str | None
    perm_module: str
    perm_action: str
    sort_order: int
    is_active: bool


class RoleJourneyOut(BaseModel):
    role_code: str
    role_name: str
    step_codes: list[str]


class JourneyConfigOut(BaseModel):
    steps: list[JourneyStepOut]
    roles: list[RoleJourneyOut]
    on_hold: list[str]


class RoleJourneyUpdate(BaseModel):
    """The role's menu in journey order (replaces the current list)."""

    step_codes: list[str] = Field(max_length=60)
    reason: str = Field(min_length=3, max_length=500)


class JourneyStepUpdate(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    hint: str | None = Field(default=None, max_length=200)
    is_active: bool = True
    reason: str = Field(min_length=3, max_length=500)
