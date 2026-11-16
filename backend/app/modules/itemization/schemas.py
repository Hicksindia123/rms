"""Step-3 itemisation / CSR approval I/O models (prompt P2-04)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.attachments.schemas import AttachmentOut


class ProductLookup(BaseModel):
    id: UUID
    code: str
    name: str
    uom: str
    category_id: UUID
    category_code: str
    category_name: str
    subcategory_id: UUID | None = None
    subcategory_name: str | None = None


class SubcategoryLookup(BaseModel):
    id: UUID
    code: str
    name: str


class CategoryLookup(BaseModel):
    """Counting search filters (AMD-07 Category -> Sub-Category)."""

    id: UUID
    code: str
    name: str
    subcategories: list[SubcategoryLookup]


class ItemIn(BaseModel):
    product_id: UUID
    # Change plan Phase 3: the documented qty is optional at counting (0 = no document qty).
    documented_qty: int = Field(default=0, ge=0, le=1_000_000, description="As per document")
    received_qty: int = Field(ge=0, le=1_000_000, description="Physically received")
    remarks: str | None = Field(default=None, max_length=1000)


class ItemPatchIn(BaseModel):
    product_id: UUID | None = None
    documented_qty: int | None = Field(default=None, ge=0, le=1_000_000)
    received_qty: int | None = Field(default=None, ge=0, le=1_000_000)
    remarks: str | None = Field(default=None, max_length=1000)


class ItemOut(BaseModel):
    id: UUID
    gs_id: UUID
    line_no: int
    product_id: UUID
    product_code: str | None
    product_name: str | None
    category_id: UUID
    category_code: str | None
    category_name: str | None
    documented_qty: int
    received_qty: int
    short_qty: int
    excess_qty: int
    # DEC-09: documented > received is flagged as short (line level, all categories by default).
    is_short: bool
    remarks: str | None
    lot_id: UUID | None = None
    stocked_qty: int | None = None


class CategoryOption(BaseModel):
    """A RETURN_CATEGORY / CSR_APPROVAL option as published in the step's form (labels and
    explanations come from the option set, never from code)."""

    code: str
    label: str
    allowed_status: str | None
    rule_text: str | None
    next_action_text: str | None
    remarks: str | None


class CategorizeIn(BaseModel):
    category: str = Field(min_length=1, max_length=40, description="RETURN_CATEGORY code")
    remarks: str | None = Field(default=None, max_length=2000)


class CsrDecisionIn(BaseModel):
    decision: str = Field(min_length=1, max_length=40, description="CSR_APPROVAL code")
    remarks: str | None = Field(default=None, max_length=2000)


class ReopenIn(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class DecisionOut(BaseModel):
    id: UUID
    gs_id: UUID
    decision_code: str
    decision_label: str
    remarks: str | None
    is_current: bool
    is_admin_action: bool
    decided_by: UUID
    decided_by_name: str | None
    decided_at: datetime
    reopened_by: UUID | None
    reopened_by_name: str | None
    reopened_at: datetime | None
    reopen_reason: str | None


class TransferLineOut(BaseModel):
    lot_id: UUID
    qty_sent: int
    line_no: int | None
    product_name: str | None


class TransferOut(BaseModel):
    id: UUID
    transfer_no: str
    status: str
    purpose_code: str | None
    with_packaging: bool
    stock_moved: bool
    from_location_code: str
    from_location_name: str
    to_location_code: str
    to_location_name: str
    initiated_by_name: str | None
    initiated_at: datetime
    notes: str | None
    lines: list[TransferLineOut]


class LotBalance(BaseModel):
    location_code: str
    location_name: str
    qty: int


class PackagingCheckOut(BaseModel):
    id: UUID
    lot_id: UUID
    result_code: Literal["OK", "REPLACED"]
    qty_replaced: int
    remarks: str | None
    by: UUID | None
    by_name: str | None
    at: datetime


class LotOut(BaseModel):
    lot_id: UUID
    gs_item_id: UUID | None
    condition_class: str
    is_pending: bool
    total_qty: int
    balances: list[LotBalance]
    packaging_checks: list[PackagingCheckOut]


class CorrectionIn(BaseModel):
    documented_qty: int = Field(ge=0, le=1_000_000)
    received_qty: int = Field(ge=0, le=1_000_000)
    reason: str = Field(min_length=3, max_length=2000)


class CorrectionDecisionIn(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    remarks: str | None = Field(default=None, max_length=2000)


class CorrectionOut(BaseModel):
    id: UUID
    gs_id: UUID
    gs_no: str
    gs_item_id: UUID
    line_no: int
    product_name: str | None
    old_documented_qty: int
    old_received_qty: int
    new_documented_qty: int
    new_received_qty: int
    reason: str
    status: str
    requested_by: UUID
    requested_by_name: str | None
    requested_at: datetime
    decided_by: UUID | None
    decided_by_name: str | None
    decided_at: datetime | None
    decision_remarks: str | None
    applied_at: datetime | None
    stock_movement_id: UUID | None


class PackagingCheckIn(BaseModel):
    result: Literal["OK", "REPLACED"]
    qty_replaced: int = Field(default=0, ge=0, le=1_000_000)
    remarks: str | None = Field(default=None, max_length=2000)


class ItemizationGs(BaseModel):
    id: UUID
    gs_no: str
    status: str
    party_name: str | None
    station_name: str | None
    carton_count: int  # AMD-03
    box_count: int  # deprecated mirror of carton_count
    missing_documentation: bool
    category_code: str | None
    original_category_code: str | None
    csr_commercial_path: bool
    categorized_at: datetime | None
    counted_by: UUID | None = None


class ItemBucketIn(BaseModel):
    field_code: str
    qty: int = Field(default=0, ge=0)


class ItemBucketOut(BaseModel):
    id: UUID
    item_id: UUID
    field_code: str
    field_label: str | None = None
    qty: int


class ItemCountIn(BaseModel):
    count_type: str  # PACKAGING, CONTAINER, USER_MANUAL
    count_value: int = Field(default=0, ge=0)


class ItemCountOut(BaseModel):
    id: UUID
    item_id: UUID
    count_type: str  # the ITEM_COUNT field code (PACKAGING, CONTAINER, USER_MANUAL …)
    field_label: str | None = None  # G-18 label snapshot
    count_value: int


class ResolvedBucketField(BaseModel):
    """One field of the product's resolved item-field profile (Phase 4), used for both the
    CATEGORISATION buckets and the ITEM_COUNT counts. Codes are stable; labels come from config."""

    field_id: UUID
    field_code: str
    field_label: str
    sort_order: int


class ItemCategorisationDetail(BaseModel):
    item_id: UUID
    line_no: int
    product_id: UUID
    sku_code: str
    sku_name: str
    category_name: str | None = None
    documented_qty: int
    received_qty: int
    profile_id: UUID | None
    profile_name: str | None
    # AMD-09: the qty buckets this product may be categorised into (always a list).
    allowed_buckets: list[ResolvedBucketField]
    # AMD-11: the Packaging / Container / User Manual counts enabled for this product (always a
    # list; empty when the profile enables none). The save endpoint accepts exactly these codes.
    allowed_counts: list[ResolvedBucketField]
    buckets: list[ItemBucketOut]
    total_bucket_qty: int
    is_conserved: bool  # AMD-11 / G-19: sum(bucket qty) == received_qty
    counts: list[ItemCountOut]


class CategorisationStateOut(BaseModel):
    goods_slip_id: UUID
    gs_no: str
    status: str
    counted_by: UUID | None
    counted_by_name: str | None
    is_same_user_who_counted: bool
    can_submit: bool
    all_conserved: bool
    items: list[ItemCategorisationDetail]


class SaveItemCategorisationIn(BaseModel):
    buckets: list[ItemBucketIn]
    counts: list[ItemCountIn] = Field(default_factory=list)


class SubmitCategorisationIn(BaseModel):
    category_code: str = Field(default="REGULAR_RETURN")
    remarks: str | None = None


class ItemizationTotals(BaseModel):
    lines: int
    documented_qty: int
    received_qty: int
    short_qty: int
    excess_qty: int


class ItemizationPermissions(BaseModel):
    can_edit_lines: bool  # Counting (status ITEMIZATION)
    can_submit_counting: bool  # Counting -> CATEGORISATION (AMD-08)
    can_categorize: bool  # status CATEGORISATION
    can_decide: bool
    can_reopen: bool
    can_request_correction: bool
    can_decide_correction: bool
    can_check_packaging: bool


class ItemizationStateOut(BaseModel):
    goods_slip: ItemizationGs
    items: list[ItemOut]
    totals: ItemizationTotals
    category_options: list[CategoryOption]
    category_label: str | None
    decision_options: list[CategoryOption]
    current_decision: DecisionOut | None
    decisions: list[DecisionOut]
    lots: list[LotOut]
    transfers: list[TransferOut]
    corrections: list[CorrectionOut]
    evidence: list[AttachmentOut]
    permissions: ItemizationPermissions


class CategorizeOut(BaseModel):
    state: ItemizationStateOut
    task_ids: list[UUID]
    notified_user_count: int


class CsrApprovalCard(BaseModel):
    """RM inbox card: GS summary, lines, evidence (mobile approval card)."""

    goods_slip: ItemizationGs
    items: list[ItemOut]
    totals: ItemizationTotals
    category_label: str | None
    categorized_by_name: str | None
    evidence: list[AttachmentOut]
    decision_options: list[CategoryOption]


def option_out(raw: dict[str, Any]) -> CategoryOption:
    return CategoryOption.model_validate({k: raw.get(k) for k in CategoryOption.model_fields})
