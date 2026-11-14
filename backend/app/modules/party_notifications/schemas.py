"""Party notification API schemas (P3-07, BR-38, DD r79, DEC-25)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# P3-07 / DEC-25: the notification channels (codes; the UI shows them humanised).
ChannelCode = Literal["EMAIL", "WHATSAPP", "PHONE", "LETTER", "OTHER"]
CHANNEL_CODES: tuple[ChannelCode, ...] = ("EMAIL", "WHATSAPP", "PHONE", "LETTER", "OTHER")


class PartyNotificationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credit_note_id: UUID | None = None
    channel: ChannelCode
    recipient: str = Field(min_length=3, max_length=300)
    # Optional edited text; the server-built message is used when omitted. The structured
    # message_snapshot (CN No., Date, items, dispatches) is always built by the server.
    message: str | None = Field(default=None, max_length=5000)
    proof_attachment_id: UUID | None = None


class RecipientSuggestion(BaseModel):
    party_name: str | None
    contact_name: str | None
    email: str | None
    phone: str | None


class NotificationDraftOut(BaseModel):
    # CREDIT_NOTE: an issued CN / JV (P3-07) · DISPATCH: P3-05 replacement dispatches ·
    # AC_ACTIONS: the values Accounts entered on the A/c Actions slip (Phase 9, AMD-20).
    source: Literal["CREDIT_NOTE", "DISPATCH", "AC_ACTIONS"]
    credit_note_id: UUID | None
    cn_type_code: str | None
    cn_type_label: str | None
    voucher_no: str | None
    voucher_date: date | None
    total_value: Decimal | None
    notified: bool
    message: str
    snapshot: dict[str, Any]


class PartyNotificationOut(BaseModel):
    id: UUID
    gs_id: UUID
    credit_note_id: UUID | None
    voucher_no: str | None
    status_code: str
    status_label: str | None
    channel_code: str
    recipient: str
    message: str
    message_snapshot: dict[str, Any]
    delivery_mode: str
    proof_attachment_id: UUID | None
    party_email_id: UUID | None = None
    sent_at: datetime
    sent_by_name: str | None


# --- Phase 9 / AMD-20: party email ---------------------------------------------------------------

AutoSendMode = Literal["OFF", "ON_AC_COMPLETION", "ON_DISPATCH"]


class PartyEmailSendIn(BaseModel):
    """Send the party email built from the Accounts values. Subject / body default to the
    server-rendered template; the structured snapshot is always built by the server (G-18)."""

    model_config = ConfigDict(extra="forbid")

    to: str = Field(min_length=3, max_length=300)
    cc: list[str] = Field(default_factory=list, max_length=10)
    subject: str | None = Field(default=None, max_length=300)
    body: str | None = Field(default=None, max_length=20000)


class PartyEmailOut(BaseModel):
    id: UUID
    gs_id: UUID
    ac_action_slip_id: UUID
    trigger_code: str
    resend_of_id: UUID | None
    email_to: str | None
    cc: list[str]
    subject: str
    body: str
    status: str
    skip_reason: str | None
    attempts: int
    next_attempt_at: datetime
    last_error: str | None
    sent_at: datetime | None
    requested_at: datetime
    requested_by_name: str | None
    party_notification_id: UUID | None


class PartyEmailStateOut(BaseModel):
    """The party email panel of a goods slip on the A/c Actions flow (AMD-20)."""

    ready: bool
    blocker: str | None
    smtp_enabled: bool
    smtp_reason: str | None
    auto_send: str
    can_send: bool
    to: str | None
    cc: list[str]
    subject: str | None
    body: str | None
    template_error: str | None
    snapshot: dict[str, Any] | None
    emails: list[PartyEmailOut]


class PartyNotificationStateOut(BaseModel):
    gs_id: UUID
    gs_no: str
    status: str
    can_record: bool
    status_label: str | None
    channels: list[str]
    recipient: RecipientSuggestion
    drafts: list[NotificationDraftOut]
    notifications: list[PartyNotificationOut]
    # None when the goods slip is not on the A/c Actions flow (Phase 7/8).
    party_email: PartyEmailStateOut | None = None


class PartyEmailTemplate(BaseModel):
    """Setting `party_email.template` (rule e). Placeholders: DEC-48."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)
    cn_line: str = Field(min_length=1, max_length=1000)
    challan_line: str = Field(min_length=1, max_length=1000)
    dispatch_line: str = Field(min_length=1, max_length=1000)


class PartyEmailDelivery(BaseModel):
    """Setting `party_email.delivery`: no auto-send until an admin enables it (AMD-20)."""

    model_config = ConfigDict(extra="forbid")

    auto_send: AutoSendMode = "OFF"
    cc: list[str] = Field(default_factory=list, max_length=10)


class PartyEmailSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: PartyEmailTemplate
    delivery: PartyEmailDelivery
    reason: str | None = Field(default=None, max_length=500)


class PartyEmailSettingsOut(BaseModel):
    template: PartyEmailTemplate
    delivery: PartyEmailDelivery
    auto_send_modes: list[str]
    placeholders: dict[str, list[str]]
    smtp_enabled: bool
    smtp_reason: str | None


class PartyEmailPreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: PartyEmailTemplate


class PartyEmailPreviewOut(BaseModel):
    subject: str
    body: str
