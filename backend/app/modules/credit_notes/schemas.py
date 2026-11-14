from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# RM CN Decision Schemas
# =============================================================================


class RmCnDecisionLineIn(BaseModel):
    gs_item_id: UUID
    qty: int = Field(gt=0)
    decision: Literal["ALLOW_CN", "DENY_CN_SEND_REPLACEMENT"]


class RmCnDecisionIn(BaseModel):
    lines: list[RmCnDecisionLineIn] = Field(min_length=1)
    deviation_reason: str | None = None


class RmCnDecisionLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    gs_item_id: UUID
    line_no: int
    product_code: str
    product_name: str
    decision_code: str
    decision_label: str
    qty: int


class RmCnDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    gs_id: UUID
    gs_no: str
    party_name: str
    decision_by: UUID
    decision_by_name: str
    decision_at: datetime
    deviation_reason: str | None = None
    is_current: bool
    lines: list[RmCnDecisionLineOut]


class RmCnDecisionPrefillLine(BaseModel):
    gs_item_id: UUID
    line_no: int
    product_code: str
    product_name: str
    received_qty: int
    planned_action_code: str
    planned_action_label: str
    planned_qty: int
    default_decision_code: str
    allowed_qty: int


class RmCnDecisionPrefillOut(BaseModel):
    gs_id: UUID
    gs_no: str
    party_name: str
    is_csr: bool
    has_existing_decision: bool
    current_decision: RmCnDecisionOut | None = None
    prefill_lines: list[RmCnDecisionPrefillLine]


# =============================================================================
# Credit Note Line & Verification Schemas
# =============================================================================


class RateVerificationIn(BaseModel):
    reference_code: Literal["RATE_SALES", "RATE_PURCHASE"]
    ref_doc_no: str = Field(min_length=1)
    ref_doc_date: date
    rate: Decimal = Field(gt=0)
    notes: str | None = None


class RateVerificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    credit_note_line_id: UUID
    reference_code: str
    reference_label: str
    ref_doc_no: str
    ref_doc_date: date
    rate: Decimal
    notes: str | None = None
    verified_by: UUID
    verified_by_name: str
    verified_at: datetime


class RateVerificationResultOut(BaseModel):
    verification: RateVerificationOut
    sales_rate: Decimal | None = None
    purchase_rate: Decimal | None = None
    variance_percent: Decimal | None = None
    has_variance_warning: bool = False
    variance_warning_message: str | None = None


class CreditNoteLineIn(BaseModel):
    gs_item_id: UUID
    qty: int = Field(gt=0)
    lot_id: UUID | None = None


class CreditNoteLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    credit_note_id: UUID
    gs_item_id: UUID
    line_no: int
    product_code: str
    product_name: str
    lot_id: UUID | None = None
    condition_class: str | None = None
    qty: int
    rate: Decimal
    tax_rate: Decimal
    taxable_amount: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    total_amount: Decimal
    rate_verifications: list[RateVerificationOut] = []
    is_rate_verified: bool = False


# =============================================================================
# Credit Note Header & Lifecycle Schemas
# =============================================================================


class CreditNoteCreateIn(BaseModel):
    gs_id: UUID
    cn_type_code: Literal["GST_CN", "GENERAL_CN", "JV_ONLY"] = "GENERAL_CN"
    gst_portal_code: Literal["GST_REFLECTED", "GST_NOT_REFLECTED"] | None = None
    lines: list[CreditNoteLineIn] = Field(min_length=1)


class PartyDocumentVerifyIn(BaseModel):
    party_doc_code: Literal["PARTY_INVOICE", "PARTY_DEBIT_NOTE", "PARTY_NO_DOC"]
    doc_no: str | None = None
    doc_date: date | None = None
    amount: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None


class GstCheckIn(BaseModel):
    gst_portal_code: Literal["GST_REFLECTED", "GST_NOT_REFLECTED"]
    return_type: Literal["GSTR-1", "GSTR-2B"] | None = None
    return_period: str | None = None
    checked_on: date
    evidence_attachment_id: UUID | None = None


class CnTypeUpdateIn(BaseModel):
    cn_type_code: Literal["GST_CN", "GENERAL_CN", "JV_ONLY"]


class CreditNoteIssueIn(BaseModel):
    cn_no: str | None = None
    cn_date: date | None = None
    jv_no: str | None = None
    jv_date: date | None = None


class CreditNoteCancelIn(BaseModel):
    reason: str = Field(min_length=3)


class CreditNoteListItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    gs_id: UUID
    gs_no: str
    party_id: UUID
    party_name: str
    cn_type_code: str
    cn_type_label: str
    status: str
    party_doc_code: str | None = None
    party_doc_label: str | None = None
    gst_portal_code: str | None = None
    gst_portal_label: str | None = None
    cn_no: str | None = None
    cn_date: date | None = None
    jv_no: str | None = None
    jv_date: date | None = None
    total_qty: int
    taxable_value: Decimal
    total_value: Decimal
    created_at: datetime
    issued_at: datetime | None = None


class LinkedStep2Document(BaseModel):
    id: UUID
    document_type_code: str
    document_type_label: str
    doc_no: str | None = None
    doc_date: date | None = None
    amount: Decimal | None = None
    attachment_id: UUID | None = None
    file_name: str | None = None
    download_url: str | None = None


class CreditNoteDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    gs_id: UUID
    gs_no: str
    party_id: UUID
    party_name: str
    party_gstin: str | None = None
    party_state: str | None = None
    cn_type_code: str
    cn_type_label: str
    status: str
    party_doc_code: str | None = None
    party_doc_label: str | None = None
    party_doc_no: str | None = None
    party_doc_date: date | None = None
    party_doc_amount: Decimal | None = None
    party_doc_notes: str | None = None
    gst_portal_code: str | None = None
    gst_portal_label: str | None = None
    gst_return_type: str | None = None
    gst_return_period: str | None = None
    gst_checked_on: date | None = None
    gst_evidence_attachment_id: UUID | None = None
    cn_no: str | None = None
    cn_date: date | None = None
    jv_no: str | None = None
    jv_date: date | None = None
    taxable_value: Decimal
    cgst_rate: Decimal
    cgst_amount: Decimal
    sgst_rate: Decimal
    sgst_amount: Decimal
    igst_rate: Decimal
    igst_amount: Decimal
    total_value: Decimal
    is_inter_state: bool
    created_by: UUID
    created_by_name: str
    created_at: datetime
    issued_by: UUID | None = None
    issued_by_name: str | None = None
    issued_at: datetime | None = None
    cancelled_by_name: str | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None
    lines: list[CreditNoteLineOut]
    linked_step2_documents: list[LinkedStep2Document] = []


class CreditNoteWorkQueueItem(BaseModel):
    gs_id: UUID
    gs_no: str
    party_id: UUID
    party_name: str
    allowed_cn_qty: int
    draft_cn_qty: int
    issued_cn_qty: int
    pending_to_credit_qty: int
    rm_decision_date: datetime
    active_credit_notes_count: int


class CreditNoteWorkQueueOut(BaseModel):
    pending_gs: list[CreditNoteWorkQueueItem]
    active_notes: list[CreditNoteListItemOut]


class PrintSignatureBlock(BaseModel):
    label: str
    name: str
    role: str


class CreditNotePrintOut(BaseModel):
    credit_note_id: UUID
    gs_id: UUID
    gs_no: str
    party_name: str
    party_gstin: str | None = None
    party_station: str | None = None
    party_state: str | None = None
    cn_type_code: str
    cn_type_label: str
    voucher_no: str
    voucher_date: date
    voucher_type_name: str
    party_doc_type: str | None = None
    party_doc_no: str | None = None
    party_doc_date: date | None = None
    gst_portal_status: str | None = None
    gst_return_period: str | None = None
    taxable_value: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    total_value: Decimal
    is_inter_state: bool
    lines: list[dict[str, Any]]
    signature_blocks: list[PrintSignatureBlock]
