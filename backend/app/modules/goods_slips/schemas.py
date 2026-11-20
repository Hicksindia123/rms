"""Pydantic I/O for Step-1 gate inward & goods slips (master plan §2.2, §8.4, prompt P2-02)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProvisionalPartyIn(BaseModel):
    """DEC-02: an unknown party created at the gate for later admin review."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    state_id: UUID
    station_id: UUID


class GateDocumentIn(BaseModel):
    """AMD-04: one document row received with the consignment. `id` is sent back when an
    existing row is edited (PATCH /gs/{id}/gate); rows left out of an edit are removed."""

    model_config = ConfigDict(extra="forbid")

    id: UUID | None = None
    doc_type_code: str = Field(min_length=1, max_length=50)
    doc_no: str | None = Field(default=None, max_length=100)
    doc_date: date | None = None
    remarks: str | None = Field(default=None, max_length=1000)
    # DEC-62 (gate form v4): who sent it. Omitted = PARTY. Ignored by gate forms v1-v3.
    source: Literal["PARTY", "TRANSPORT"] | None = None


class GateInwardIn(BaseModel):
    """POST /gs body.

    `party_id` XOR `provisional_party`. `state_id` / `station_id` default to the party master
    (DEC-02) and may be overridden (audited). `values` holds the S1_GATE_INWARD form answers that
    are not master references (box_count, delivery_mode, courier_name, …, accompanying_doc, …).
    `transporter_id` optionally links a DIRECT_TRUCK transporter from the master; otherwise the
    free-text `values.transporter_name` is kept.
    """

    model_config = ConfigDict(extra="forbid")

    party_id: UUID | None = None
    provisional_party: ProvisionalPartyIn | None = None
    state_id: UUID | None = None
    station_id: UUID | None = None
    transporter_id: UUID | None = None
    values: dict[str, Any] = Field(default_factory=dict)
    # AMD-04 (form v2): document rows; empty when `values.no_document` is true (DEC-03).
    documents: list[GateDocumentIn] = Field(default_factory=list, max_length=20)


class GateEditIn(GateInwardIn):
    """PATCH /gs/{id}/gate: same fields as creation, plus the mandatory audit reason."""

    reason: str = Field(min_length=3, max_length=500)


class CancelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)


class GsWarning(BaseModel):
    code: str
    message: str


class GateDocumentFileOut(BaseModel):
    id: UUID
    mime_type: str
    size_bytes: int
    status: str
    preview_unsupported: bool
    created_at: datetime


class GateDocumentOut(BaseModel):
    """AMD-04: a gate document row with its files (attachments kind GATE_DOC)."""

    id: UUID
    doc_type_code: str
    doc_type_label: str
    doc_no: str | None
    doc_date: date | None
    remarks: str | None
    source_step: str
    # DEC-62: PARTY / TRANSPORT (gate v4), CARTON (P3); null = captured before gate v4.
    doc_source: str | None = None
    accounts_alerted_at: datetime | None
    files: list[GateDocumentFileOut] = Field(default_factory=list)


class StatusLabel(BaseModel):
    """AMD-08: display label of a goods-slip status code (GS_STATUS option set)."""

    code: str
    label: str


class GateDocumentTypeOut(BaseModel):
    code: str
    label: str
    required_fields: list[str]


class GoodsSlipOut(BaseModel):
    id: UUID
    gs_no: str
    status: str
    workflow_version_id: UUID
    party_id: UUID | None
    party_name: str | None
    party_is_provisional: bool | None
    state_id: UUID | None
    state_name: str | None
    station_id: UUID | None
    station_name: str | None
    state_station_overridden: bool
    delivery_mode_code: str
    delivery_mode_label: str | None
    courier_name: str | None
    docket_no: str | None
    vehicle_no: str | None
    transporter_id: UUID | None
    transporter_name: str | None
    rep_name: str | None
    rep_contact: str | None
    # AMD-03: carton_count is the business field; box_count is a deprecated mirror.
    carton_count: int
    box_count: int
    # AMD-01 / AMD-02 (NULL on GS created before 2026-11-13)
    return_type_code: str | None = None
    return_type_label: str | None = None
    gate_entry_date: date | None = None
    gate_entry_no: int | None = None
    # AMD-04: document rows (filled on detail / create responses)
    documents: list[GateDocumentOut] = Field(default_factory=list)
    gate_document_code: str | None
    gate_document_label: str | None
    gate_doc_no: str | None
    gate_doc_date: date | None
    gate_doc_remarks: str | None
    missing_documentation: bool
    category_code: str | None
    # P2-04: the Step-3 choice is kept when a rejected CSR is converted to RO (BR-08).
    original_category_code: str | None = None
    csr_commercial_path: bool = False
    categorized_at: datetime | None = None
    has_open_pendency: bool
    has_discrepancy: bool
    has_hazard: bool
    has_rejections: bool
    cancelled_at: datetime | None
    cancel_reason: str | None
    created_at: datetime
    created_by: UUID | None
    created_by_name: str | None
    updated_at: datetime


class GateInwardOut(BaseModel):
    goods_slip: GoodsSlipOut
    warnings: list[GsWarning]
    task_ids: list[UUID]
    notified_user_count: int


class GsListItem(BaseModel):
    id: UUID
    gs_no: str
    status: str
    party_name: str | None
    party_is_provisional: bool | None
    station_name: str | None
    carton_count: int
    box_count: int
    return_type_code: str | None = None
    gate_entry_no: int | None = None
    delivery_mode_code: str
    missing_documentation: bool
    has_open_pendency: bool
    has_discrepancy: bool
    has_hazard: bool
    has_rejections: bool
    created_at: datetime


class TimelineEntry(BaseModel):
    at: datetime
    kind: str  # STATUS | AUDIT
    title: str
    from_status: str | None = None
    to_status: str | None = None
    step_code: str | None = None
    reason: str | None = None
    changed_fields: list[str] | None = None
    by_user_id: UUID | None = None
    by_name: str | None = None


class TaskOut(BaseModel):
    id: UUID
    gs_id: UUID
    step_code: str
    step_label: str | None
    assigned_role_code: str | None
    assigned_user_id: UUID | None
    status: str
    due_at: datetime | None
    created_at: datetime
    completed_at: datetime | None


class AttachmentSummary(BaseModel):
    kind: str
    status: str
    count: int


class GoodsSlipDetailOut(BaseModel):
    goods_slip: GoodsSlipOut
    form_version_id: UUID | None
    form_values: dict[str, Any]
    labels_snapshot: dict[str, Any]
    timeline: list[TimelineEntry]
    tasks: list[TaskOut]
    attachments: list[AttachmentSummary]
    can_edit_gate: bool
    can_cancel: bool


class GateFormOut(BaseModel):
    """Published S1_GATE_INWARD snapshot + gate settings (no config permission needed)."""

    form_version_id: UUID
    snapshot: dict[str, Any]
    contact_phone_pattern: str | None
    party_state_station_autofill: bool
    # AMD-04 / DEC-38: document row types and gate entry date limits for the UI.
    document_types: list[GateDocumentTypeOut] = Field(default_factory=list)
    # DEC-62 (gate v4): "Documents From Transport" types (option set GATE_TRANSPORT_DOCUMENT).
    transport_document_types: list[GateDocumentTypeOut] = Field(default_factory=list)
    business_today: date | None = None
    max_backdate_days: int | None = None


class TagLabel(BaseModel):
    box_no: int  # carton number (AMD-03)
    box_count: int  # carton count (AMD-03)
    caption: str  # "Carton 1 of 3"


class TagField(BaseModel):
    key: str
    label: str
    value: str | None


class TagSection(BaseModel):
    id: str
    title: str
    fields: list[TagField]


class GsTagOut(BaseModel):
    template_code: str
    template_version: int
    layout: dict[str, Any]
    gs_id: UUID
    gs_no: str
    qr_payload: str
    party_name: str | None
    state_name: str | None
    station_name: str | None
    transporter: str | None
    carton_count: int
    box_count: int
    received_date: date
    sections: list[TagSection]
    labels: list[TagLabel]


class LookupItem(BaseModel):
    id: UUID
    name: str
    code: str | None = None
    state_id: UUID | None = None
    state_name: str | None = None
    station_id: UUID | None = None
    station_name: str | None = None
    is_provisional: bool | None = None


PartyFallback = Literal["STATE", "ALL", "NONE"]


class PartyLookupPage(BaseModel):
    """Distributor lookup by state + station (AMD-06, DEC-35).

    `scope` says which list was returned: STATION (parties of the station), STATE / ALL (the
    `gate.party_fallback` setting applied because the station has no parties) or NONE (fallback
    disabled). `fallback_applied` is true whenever the station had no parties.
    """

    items: list[LookupItem]
    total: int
    page: int
    page_size: int
    scope: Literal["STATION", "STATE", "ALL", "NONE"]
    fallback_applied: bool
    fallback_setting: PartyFallback
