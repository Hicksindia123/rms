"""Notifications I/O models (prompts P2-03, P4-03)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

Priority = Literal["LOW", "NORMAL", "HIGH"]
Channel = Literal["IN_APP", "EMAIL"]
EVENT_CODE = r"^[A-Z][A-Z0-9_]{1,59}$"


class NotificationOut(BaseModel):
    id: UUID
    type: str
    title: str
    body: str | None
    entity_type: str | None
    entity_id: UUID | None
    priority: str
    read_at: datetime | None
    created_at: datetime
    event_type: str | None = None
    gs_id: UUID | None = None


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    unread_count: int
    total: int = 0


class EmailStatusOut(BaseModel):
    """SMTP status (read-only). Never includes credentials."""

    enabled: bool
    host: str | None
    port: int
    sender: str | None
    security: str
    reason: str | None


class PreferenceItemOut(BaseModel):
    event_type: str
    label: str
    description: str | None
    category: str
    is_mandatory: bool
    email_enabled: bool
    # True when an active rule sends this event by email (otherwise the toggle has no effect yet).
    email_rule_active: bool


class PreferencesOut(BaseModel):
    email_channel: EmailStatusOut
    email_address: str | None
    email_mode: Literal["IMMEDIATE", "DAILY_DIGEST"]
    items: list[PreferenceItemOut]


class PreferencesIn(BaseModel):
    email_mode: Literal["IMMEDIATE", "DAILY_DIGEST"] | None = None
    # event code → email enabled
    email: dict[str, bool] = Field(default_factory=dict)


# --- admin ------------------------------------------------------------------------------------


class EventTypeOut(BaseModel):
    code: str
    label: str
    description: str | None
    category: str
    default_priority: str
    is_mandatory: bool
    source_ref: str | None
    sort_order: int


class EventTypeIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    default_priority: Priority
    is_mandatory: bool
    reason: str | None = Field(default=None, max_length=500)


class RuleIn(BaseModel):
    event_type: str = Field(pattern=EVENT_CODE)
    name: str = Field(min_length=1, max_length=120)
    include_context_recipients: bool = False
    include_step_assignees: bool = False
    recipient_role_codes: list[str] = Field(default_factory=list, max_length=20)
    recipient_user_ids: list[UUID] = Field(default_factory=list, max_length=50)
    channels: list[Channel] = Field(min_length=1, max_length=2)
    priority: Priority | None = None
    is_active: bool = True
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("channels")
    @classmethod
    def _unique_channels(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))

    @field_validator("recipient_role_codes")
    @classmethod
    def _unique_roles(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(v.strip() for v in value if v.strip()))


class RuleOut(BaseModel):
    id: UUID
    event_type: str
    event_label: str
    is_mandatory: bool
    name: str
    include_context_recipients: bool
    include_step_assignees: bool
    recipient_role_codes: list[str]
    recipient_user_ids: list[UUID]
    channels: list[str]
    priority: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ReasonIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class TemplateOut(BaseModel):
    id: UUID
    event_type: str
    event_label: str | None = None
    channel: str
    version_no: int
    subject: str
    body: str
    status: str
    change_reason: str | None
    published_at: datetime
    created_by: UUID | None


class TemplateIn(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)
    reason: str | None = Field(default=None, max_length=500)


class TemplatePreviewIn(BaseModel):
    event_type: str = Field(pattern=EVENT_CODE)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)


class TemplatePreviewOut(BaseModel):
    subject: str
    body: str
    placeholders: list[str]
    unknown_placeholders: list[str]


class EscalationRuleIn(BaseModel):
    workflow_step_id: UUID
    after_hours: float = Field(gt=0, le=10000)
    notify_role_code: str | None = None
    notify_user_id: UUID | None = None
    is_active: bool = False
    reason: str | None = Field(default=None, max_length=500)


class EscalationRuleOut(BaseModel):
    id: UUID
    workflow_step_id: UUID
    step_code: str
    step_label: str
    sla_hours: float | None
    workflow_code: str
    workflow_version_id: UUID
    workflow_version_no: int
    workflow_version_status: str
    after_hours: float
    level_no: int
    notify_role_code: str | None
    notify_role_name: str | None
    notify_user_id: UUID | None
    notify_user_name: str | None
    is_active: bool
    updated_at: datetime


class DeliveryOut(BaseModel):
    id: UUID
    event_id: UUID
    event_type: str
    event_label: str
    title: str
    user_id: UUID
    user_name: str
    channel: str
    status: str
    skip_reason: str | None
    attempts: int
    last_error: str | None
    email_to: str | None
    sent_at: datetime | None
    created_at: datetime


class DeliveryLogOut(BaseModel):
    items: list[DeliveryOut]
    outbox: dict[str, int]
    deliveries: dict[str, int]
    email_channel: EmailStatusOut


class LookupRole(BaseModel):
    code: str
    name: str


class LookupUser(BaseModel):
    id: UUID
    full_name: str
    email: str | None


class LookupStep(BaseModel):
    id: UUID
    code: str
    label: str
    sla_hours: float | None
    workflow_code: str
    version_no: int
    version_status: str


class AdminLookupsOut(BaseModel):
    roles: list[LookupRole]
    users: list[LookupUser]
    steps: list[LookupStep]
