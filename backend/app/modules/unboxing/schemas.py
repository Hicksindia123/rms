"""Unboxing / document classification / Accounts queue API schemas (prompt P2-03)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.attachments.schemas import AttachmentOut
from app.modules.goods_slips.schemas import GateDocumentOut, GateDocumentTypeOut


class UnboxingGs(BaseModel):
    id: UUID
    gs_no: str
    status: str
    party_name: str | None
    station_name: str | None
    carton_count: int  # AMD-03
    box_count: int  # deprecated mirror of carton_count
    missing_documentation: bool
    gate_document_code: str | None
    gate_document_label: str | None


class Checklist(BaseModel):
    """Carton videos (G-02, DEC-63: one confirmed video per carton is the only requirement).
    `missing` lists the codes the backend would reject /unboxing/complete with. The document photo
    counts are informational (legacy DOC_PHOTO evidence)."""

    video_ok: bool
    video_count: int
    doc_photo_count: int
    classified_doc_photo_count: int
    parcel_photo_count: int
    missing_documentation: bool
    video_per_box_required: bool
    # AMD-03 / AMD-08: carton-wise progress (Carton n of N); box_* names kept for compatibility.
    carton_count: int
    cartons_with_video: int
    boxes_missing_video: list[int]
    missing: list[str]
    ready: bool


class DocumentOut(BaseModel):
    id: UUID
    gs_id: UUID
    attachment_id: UUID
    classification_code: str
    classification_label: str | None
    doc_no: str | None
    doc_date: date | None
    amount: Decimal | None
    buyer_gstin: str | None
    seller_gstin: str | None
    items_verified: bool | None
    qty_matched: bool | None
    party_claim_text: str | None
    remarks: str | None
    form_version_id: UUID | None
    values: dict[str, Any]
    labels_snapshot: dict[str, Any]
    verified_by_name: str | None
    verified_at: datetime | None
    accounts_acknowledged_by_name: str | None
    accounts_acknowledged_at: datetime | None


class ExceptionOut(BaseModel):
    """DEC-03 Missing Document Exception, read-only history (retired by DEC-63)."""

    id: UUID
    gs_id: UUID
    gs_no: str
    party_name: str | None
    parcel_attachment_id: UUID
    parcel_mime_type: str
    parcel_preview_unsupported: bool
    remark: str
    status: str
    requested_by_name: str | None
    requested_at: datetime
    decided_by_name: str | None
    decided_at: datetime | None
    decision_remarks: str | None


class UploadLimits(BaseModel):
    max_video_bytes: int
    max_document_bytes: int
    resumable_threshold_bytes: int


class UnboxingPermissions(BaseModel):
    can_perform: bool


class UnboxingStateOut(BaseModel):
    goods_slip: UnboxingGs
    checklist: Checklist
    attachments: list[AttachmentOut]
    documents: list[DocumentOut]
    exceptions: list[ExceptionOut]
    form_version_id: UUID
    form_snapshot: dict[str, Any]
    limits: UploadLimits
    permissions: UnboxingPermissions
    # AMD-04: document rows of the GS (gate + carton opening) and the configured row types.
    gate_documents: list[GateDocumentOut] = Field(default_factory=list)
    document_types: list[GateDocumentTypeOut] = Field(default_factory=list)


class CartonDocumentIn(BaseModel):
    """P3 / DEC-62: the document found while opening the cartons (stage S1_UNBOX, source CARTON):
    a type only, its photos are uploaded to the row. doc_no / doc_date / remarks are accepted by
    the schema only to answer with a clear 422 (not recorded); legacy rows still use them."""

    model_config = ConfigDict(extra="forbid")

    doc_type_code: str = Field(min_length=1, max_length=50)
    doc_no: str | None = Field(default=None, max_length=100)
    doc_date: date | None = None
    remarks: str | None = Field(default=None, max_length=1000)


class DocumentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attachment_id: UUID
    # Keyed by the S1_UNBOXING form field keys (doc_classification, invoice_no, buyer_gstin, …).
    values: dict[str, Any]


class DocumentPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any]


class CompleteOut(BaseModel):
    goods_slip: UnboxingGs
    task_ids: list[UUID]
    notified_user_count: int


class QueueDocument(BaseModel):
    id: UUID
    attachment_id: UUID
    classification_code: str
    classification_label: str | None
    doc_no: str | None
    doc_date: date | None
    amount: Decimal | None
    buyer_gstin: str | None
    seller_gstin: str | None
    items_verified: bool | None
    qty_matched: bool | None
    party_claim_text: str | None
    remarks: str | None
    mime_type: str
    preview_unsupported: bool
    verified_by_name: str | None
    verified_at: datetime | None


class QueueItem(BaseModel):
    gs_id: UUID
    gs_no: str
    status: str
    party_name: str | None
    station_name: str | None
    missing_documentation: bool
    unboxed_at: datetime | None
    documents: list[QueueDocument]


class OptionOut(BaseModel):
    code: str
    label: str


class AcknowledgeOut(BaseModel):
    gs_id: UUID
    acknowledged: int
