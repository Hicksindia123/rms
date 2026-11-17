"""Step-3 Itemisation & GS-wise categorisation, CSR approval, line corrections, packaging check
(master plan §2.2 Step-3, DD r17-r20, WF r4, BR-07..BR-10, G-01, G-03, G-16, DEC-06, DEC-09,
DEC-27, DEC-28).

* Lines (S1_ITEMIZE PERFORM, status ITEMIZATION): product (label snapshots), documented / received
  qty; short / excess are generated columns. DEC-09: a short line is flagged for every category
  (setting `track_short_qty_all_categories`; when false only categories whose condition set has a
  SHORT_QTY option are flagged — the shortage itself is always recorded).
* Counting (change plan 2026-11-12 Phase 3, AMD-08): lines are a saved draft while the GS is
  ITEMIZATION (labelled Counting); submit-counting (Idempotency-Key) needs >= 1 line and moves the
  GS to CATEGORISATION on the same S1_ITEMIZE step (lines frozen from then on, gs_items_guard; the
  G-03 trigger only lets ITEMIZATION go to CATEGORISATION).
* DEC-53 (Counting & Categorisation merged): a line is saved with its condition split (buckets)
  and item counts while the GS is ITEMIZATION; the bucket total must equal the physical qty
  (G-19 at line level). submit-itemization runs ITEMIZATION -> CATEGORISATION -> RM_REVIEW in one
  transaction (or CATEGORISATION -> RM_REVIEW after an RM send-back, split-only).
* categorize (Idempotency-Key, status CATEGORISATION): one category per GS (BR-07, DEC-06).
  Per line with received > 0, in the same transaction: a FINISHED_GOOD / AS_RECEIVED lot and
  an INWARD movement into INWARD_STAGING with the deterministic key `{gs_item_id}:inward`
  (G-16). Short qty is never stocked.
  The pinned workflow routes the GS (RO → S1_INSPECT, CSR → S1_CSR_APPROVAL for the RM).
* csr-decision (Idempotency-Key, G-03): only the S1_CSR_APPROVAL approver (or a Super Admin,
  flagged as an admin action) decides, once. Rejected → RO, original category kept, INSPECTION.
  Approved → IN_PROCESS, Step-7 CSR flag, and a custody transfer proposal INWARD_STAGING →
  INTERMEDIATE_STORE "with packaging" (custody service, completed by P3-01). An admin reopen
  (reason) supersedes a decision while nothing downstream has happened.
* corrections: post-categorisation line edits need a reason and an RM approval; the approval adjusts
  the stock with an ADJUST movement (`{correction_id}:adjust`) — audited.
* packaging check (WF r4, BR-10, DEC-27): OK / REPLACED + qty by the Intermediate Store custodian;
  recorded, never blocking.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import UnitOfWork
from app.core.errors import (
    Conflict,
    NotFound,
    PermissionDenied,
    SystemGuardViolation,
    ValidationFailed,
)
from app.core.idempotency import IdempotencyKey, IdempotentResult, run_idempotent
from app.core.permissions import EffectivePermissions, assert_step_actor, step_codes_for
from app.core.security import CurrentUser
from app.modules.attachments import service as attachments
from app.modules.custody import service as custody
from app.modules.goods_slips import service as gs_service
from app.modules.inventory import ledger_service
from app.modules.itemization import repository as repo
from app.modules.itemization.schemas import (
    CategorisationStateOut,
    CategorizeIn,
    CategorizeOut,
    CategoryLookup,
    CategoryOption,
    CorrectionDecisionIn,
    CorrectionIn,
    CorrectionOut,
    CsrApprovalCard,
    CsrDecisionIn,
    DecisionOut,
    ItemBucketIn,
    ItemBucketOut,
    ItemCategorisationDetail,
    ItemCountIn,
    ItemCountOut,
    ItemFieldsOut,
    ItemIn,
    ItemizationGs,
    ItemizationPermissions,
    ItemizationStateOut,
    ItemizationTotals,
    ItemOut,
    ItemPatchIn,
    LotOut,
    PackagingCheckIn,
    PackagingCheckOut,
    ProductLookup,
    ReopenIn,
    ResolvedBucketField,
    SaveItemCategorisationIn,
    SubmitCategorisationIn,
    SubmitItemizationIn,
    TransferOut,
    option_out,
)
from app.modules.notifications import service as notifications
from app.shared.rules_engine import evaluate_rule

log = structlog.get_logger("rms.itemization")

ITEMIZE_STEP = "S1_ITEMIZE"
CSR_STEP = "S1_CSR_APPROVAL"
ITEMIZE_FORM = "S1_ITEMIZE"
CSR_FORM = "S1_CSR_APPROVAL"
CATEGORY_FIELD = "return_category"  # RETURN_CATEGORY, DD r17-r18
CATEGORY_NOTES_FIELD = "item_notes"
DECISION_FIELD = "csr_approval"  # CSR_APPROVAL, DD r19-r20
DECISION_NOTES_FIELD = "rm_approval_notes"
CSR = "CSR"
RO = "RO"
CSR_APPROVED = "CSR_APPROVED"
CSR_REJECTED = "CSR_REJECTED_TO_RO"
INWARD_LOCATION = "INWARD_STAGING"
CSR_TARGET_LOCATION = "INTERMEDIATE_STORE"
CSR_TRANSFER_PURPOSE = "CSR_WITH_PACKAGING"
ENTITY_TYPE = "goods_slip"
# §6.5 system statuses entered by each workflow step (labels are configurable, statuses are not).
CATEGORISATION = "CATEGORISATION"  # AMD-08: counting submitted, category not yet chosen
STATUS_FOR_STEP = {
    "S1_CSR_APPROVAL": "CSR_APPROVAL_PENDING",
    "S1_INSPECT": "INSPECTION",
    "S2_HANDOVER": "IN_PROCESS",
}
ADMIN_ACTION_REASON = (
    "ADMIN ACTION: Super Admin recorded the CSR decision without the S1_CSR_APPROVAL assignment"
)


# --- pure helpers (unit-tested) ----------------------------------------------------------------
def form_field_options(snapshot: dict[str, Any], field_key: str) -> list[CategoryOption]:
    """Active options of a dropdown field in a published form snapshot (labels from config)."""
    field = next((f for f in snapshot.get("fields") or [] if f.get("field_key") == field_key), None)
    return [
        option_out(o)
        for o in (field or {}).get("option_items") or []
        if o.get("is_active", True) and o.get("code")
    ]


def field_label(snapshot: dict[str, Any], field_key: str) -> str:
    field = next((f for f in snapshot.get("fields") or [] if f.get("field_key") == field_key), None)
    return str((field or {}).get("label") or field_key)


# --- item field profile for categorisation (AMD-09 buckets, AMD-11 counts) ----------------------
CATEGORISATION_GROUP = "CATEGORISATION"
ITEM_COUNT_GROUP = "ITEM_COUNT"


@dataclass(frozen=True)
class ResolvedItemFields:
    """The fields a GS item may be categorised with. One resolution serves the categorisation
    screen, its save validation and RM review, so the codes offered = the codes accepted."""

    buckets: list[ResolvedBucketField]
    counts: list[ResolvedBucketField]
    profile_version_id: UUID | None
    profile_version_no: int | None

    def bucket_ids(self) -> dict[str, UUID]:
        return {f.field_code: f.field_id for f in self.buckets}

    def count_ids(self) -> dict[str, UUID]:
        return {f.field_code: f.field_id for f in self.counts}


def _to_fields(rows: list[dict[str, Any]]) -> list[ResolvedBucketField]:
    return [
        ResolvedBucketField(
            field_id=r["field_id"],
            field_code=r["code"],
            field_label=r["label"],
            sort_order=r["sort_order"],
        )
        for r in rows
    ]


def resolve_item_fields(
    session: Session, product_id: UUID, version_id: UUID | None
) -> ResolvedItemFields:
    """Phase 4 resolver (rms_private.resolve_item_field_profile) at the GS's stamped profile
    version (current version while unstamped). This is exactly the set the DB guards
    gs_item_buckets_guard / gs_item_counts_guard (G-18) accept, so it has no library fallback:
    a field the profile does not enable would be rejected by the database anyway. A product whose
    profile enables no bucket gets an empty list (shown as a configuration problem in the UI)."""
    rows = repo.resolve_profile_for_product(session, product_id, version_id)
    first = rows[0] if rows else None
    return ResolvedItemFields(
        buckets=_to_fields([r for r in rows if r.get("field_group") == CATEGORISATION_GROUP]),
        counts=_to_fields([r for r in rows if r.get("field_group") == ITEM_COUNT_GROUP]),
        profile_version_id=first.get("profile_version_id") if first else None,
        profile_version_no=first.get("profile_version_no") if first else None,
    )


def item_display(item: dict[str, Any]) -> tuple[str, str]:
    """(code, name) of a GS item line from its G-18 product snapshots (repository columns)."""
    return (
        str(item.get("product_code_snapshot") or ""),
        str(item.get("product_name_snapshot") or ""),
    )


def is_short(item: dict[str, Any], *, all_categories: bool, short_categories: set[UUID]) -> bool:
    """DEC-09: documented > received is a shortage (all categories unless configured off)."""
    return int(item["short_qty"]) > 0 and (
        all_categories or item["category_id"] in short_categories
    )


def route_step(snapshot: dict[str, Any], from_step: str, context: dict[str, Any]) -> str:
    """The step the pinned workflow routes to from `from_step` for this context (highest priority
    transition whose condition holds)."""
    transitions = sorted(
        (t for t in snapshot.get("transitions") or [] if t.get("from_step_code") == from_step),
        key=lambda t: -(t.get("priority") or 0),
    )
    target = next(
        (t for t in transitions if evaluate_rule(t.get("condition"), context, context)), None
    )
    if target is None or target.get("to_step_code") not in STATUS_FOR_STEP:
        raise Conflict(
            f"The workflow has no route out of {from_step} for this decision",
            code="WORKFLOW_MISCONFIGURED",
            details={"from_step": from_step, "context": context},
        )
    return str(target["to_step_code"])


def _decision_out(row: dict[str, Any], options: list[CategoryOption]) -> DecisionOut:
    labels = dict(row.get("labels_snapshot") or {})
    entry = labels.get(DECISION_FIELD) if isinstance(labels.get(DECISION_FIELD), dict) else None
    label = (entry or {}).get("value_label") or next(
        (o.label for o in options if o.code == row["decision_code"]), row["decision_code"]
    )
    return DecisionOut(
        **{k: row[k] for k in DecisionOut.model_fields if k in row}, decision_label=str(label)
    )


def _gs_out(gs: dict[str, Any]) -> ItemizationGs:
    return ItemizationGs.model_validate({k: gs.get(k) for k in ItemizationGs.model_fields})


def _correction_out(row: dict[str, Any]) -> CorrectionOut:
    return CorrectionOut(**{k: row[k] for k in CorrectionOut.model_fields})


def _check_out(row: dict[str, Any]) -> PackagingCheckOut:
    return PackagingCheckOut(**{k: row[k] for k in PackagingCheckOut.model_fields})


class ItemizationService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    # ---------------------------------------------------------------- reads ------------------
    def state(
        self, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID
    ) -> ItemizationStateOut:
        with self._uow.transaction(user.id) as session:
            gs = gs_service.get_visible_goods_slip(session, user, perms, gs_id)
            return self._state(session, user, perms, gs)

    def products(
        self,
        user: CurrentUser,
        q: str | None,
        limit: int,
        *,
        category_id: UUID | None = None,
        subcategory_id: UUID | None = None,
    ) -> list[ProductLookup]:
        with self._uow.transaction(user.id) as session:
            return [
                ProductLookup(**{k: r[k] for k in ProductLookup.model_fields})
                for r in repo.search_products(
                    session,
                    (q or "").strip() or None,
                    limit,
                    category_id=category_id,
                    subcategory_id=subcategory_id,
                )
            ]

    def categories(self, user: CurrentUser) -> list[CategoryLookup]:
        """Category -> Sub-Category filters for the counting product search (AMD-07)."""
        with self._uow.transaction(user.id) as session:
            return [
                CategoryLookup.model_validate(r)
                for r in repo.product_categories_with_subcategories(session)
            ]

    def product_fields(self, user: CurrentUser, product_id: UUID) -> ItemFieldsOut:
        """DEC-53: buckets / counts the line editor offers for a product (current profile; the
        GS is stamped only when it leaves CATEGORISATION, so this is what the save accepts)."""
        with self._uow.transaction(user.id) as session:
            self._product(session, product_id)
            fields = resolve_item_fields(session, product_id, None)
            return ItemFieldsOut(
                product_id=product_id,
                allowed_buckets=fields.buckets,
                allowed_counts=fields.counts,
            )

    def pending_csr(
        self, user: CurrentUser, perms: EffectivePermissions, limit: int
    ) -> list[CsrApprovalCard]:
        """Replacement Manager inbox: GS waiting for the CSR decision (G-03)."""
        with self._uow.transaction(user.id) as session:
            form = self._form(session, CSR_FORM)
            options = form_field_options(form["snapshot"], DECISION_FIELD)
            cat_options = form_field_options(
                self._form(session, ITEMIZE_FORM)["snapshot"], CATEGORY_FIELD
            )
            cards: list[CsrApprovalCard] = []
            for gs_id in repo.pending_csr_gs_ids(session, limit):
                try:
                    gs = gs_service.get_visible_goods_slip(session, user, perms, gs_id)
                except (NotFound, PermissionDenied):
                    continue
                items = self._items(session, gs_id)
                info = repo.categorization_info(session, gs_id) or {}
                cards.append(
                    CsrApprovalCard(
                        goods_slip=_gs_out(gs),
                        items=items,
                        totals=_totals(items),
                        category_label=_category_label(gs, cat_options, info),
                        categorized_by_name=info.get("categorized_by_name"),
                        evidence=self._evidence(session, gs_id),
                        decision_options=options,
                    )
                )
            return cards

    def pending_corrections(
        self, user: CurrentUser, perms: EffectivePermissions, limit: int
    ) -> list[CorrectionOut]:
        with self._uow.transaction(user.id) as session:
            out: list[CorrectionOut] = []
            for row in repo.pending_corrections(session, limit):
                try:
                    gs_service.get_visible_goods_slip(session, user, perms, row["gs_id"])
                except (NotFound, PermissionDenied):
                    continue
                out.append(_correction_out(row))
            return out

    # ---------------------------------------------------------------- lines ------------------
    def add_item(
        self, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID, payload: ItemIn
    ) -> ItemOut:
        with self._uow.transaction(user.id) as session:
            self._lock_itemization(session, user, perms, gs_id)
            product = self._product(session, payload.product_id)
            _require_quantity(payload.documented_qty, payload.received_qty)
            item_id = repo.insert_item(
                session,
                gs_id=gs_id,
                product=product,
                documented_qty=payload.documented_qty,
                received_qty=payload.received_qty,
                remarks=_clean(payload.remarks),
                by=user.id,
            )
            if payload.buckets is not None or payload.counts is not None:
                item = self._own_item(session, gs_id, item_id)
                self._write_line_split(
                    session, gs_id, item, payload.buckets, payload.counts, user.id
                )
            return self._item_out(session, item_id)

    def update_item(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        item_id: UUID,
        payload: ItemPatchIn,
    ) -> ItemOut:
        with self._uow.transaction(user.id) as session:
            self._lock_itemization(session, user, perms, gs_id)
            item = self._own_item(session, gs_id, item_id)
            fields: dict[str, Any] = {}
            if payload.product_id is not None and payload.product_id != item["product_id"]:
                product = self._product(session, payload.product_id)
                fields.update(
                    product_id=product["id"],
                    category_id=product["category_id"],
                    product_code_snapshot=product["code"],
                    product_name_snapshot=product["name"],
                    category_code_snapshot=product["category_code"],
                )
            if payload.documented_qty is not None:
                fields["documented_qty"] = payload.documented_qty
            if payload.received_qty is not None:
                fields["received_qty"] = payload.received_qty
            if "remarks" in payload.model_fields_set:
                fields["remarks"] = _clean(payload.remarks)
            _require_quantity(
                fields.get("documented_qty", item["documented_qty"]),
                fields.get("received_qty", item["received_qty"]),
            )
            repo.update_item(session, item_id, fields)
            if "product_id" in fields:
                # DEC-53: the split belongs to the old product's profile; it is re-entered.
                repo.delete_item_buckets(session, item_id)
                repo.delete_item_counts(session, item_id)
            if payload.buckets is not None or payload.counts is not None:
                item = self._own_item(session, gs_id, item_id)
                self._write_line_split(
                    session, gs_id, item, payload.buckets, payload.counts, user.id
                )
            return self._item_out(session, item_id)

    def _write_line_split(
        self,
        session: Session,
        gs_id: UUID,
        item: dict[str, Any],
        buckets: list[ItemBucketIn] | None,
        counts: list[ItemCountIn] | None,
        by: UUID,
    ) -> None:
        """DEC-53: replace a line's condition split (buckets) and / or item counts at counting.
        Only codes the product's resolved profile enables are accepted (the DB guard G-18 would
        refuse anything else) and the bucket total must equal the physical qty (G-19)."""
        fields = resolve_item_fields(
            session, item["product_id"], repo.get_profile_version_id(session, gs_id)
        )
        received = int(item["received_qty"])
        if buckets is not None:
            if not fields.buckets and received > 0:
                raise ValidationFailed(
                    "No condition buckets are configured for this product; ask an admin to "
                    "enable them in Item Field Profiles",
                    code="NO_CATEGORISATION_FIELDS",
                    details={"product_id": str(item["product_id"])},
                )
            cat_map = fields.bucket_ids()
            seen: set[str] = set()
            for b in buckets:
                if b.field_code not in cat_map:
                    raise ValidationFailed(
                        f"Bucket {b.field_code} is not enabled in this product's item field "
                        "profile",
                        code="INVALID_FIELD",
                    )
                if b.field_code in seen:
                    raise ValidationFailed(
                        f"Bucket {b.field_code} is entered twice", code="DUPLICATE_FIELD"
                    )
                seen.add(b.field_code)
            total = sum(b.qty for b in buckets)
            if total != received:
                raise ValidationFailed(
                    f"The condition split ({total}) must equal the physical quantity "
                    f"({received}) (G-19)",
                    code="BUCKET_TOTAL_MISMATCH",
                    details={
                        "buckets": [f"Split total {total} must equal physical qty {received}"],
                        "received_qty": received,
                        "bucket_total": total,
                    },
                )
            repo.delete_item_buckets(session, item["id"])
            for b in buckets:
                if b.qty > 0:
                    repo.upsert_item_bucket(session, item["id"], cat_map[b.field_code], b.qty, by)
        if counts is not None:
            count_map = fields.count_ids()
            for c in counts:
                if c.count_type not in count_map:
                    raise ValidationFailed(
                        f"Count {c.count_type} is not enabled in this product's item field profile",
                        code="INVALID_COUNT_TYPE",
                    )
            repo.delete_item_counts(session, item["id"])
            for c in counts:
                repo.upsert_item_count(
                    session, item["id"], count_map[c.count_type], c.count_value, by
                )

    def delete_item(
        self, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID, item_id: UUID
    ) -> None:
        with self._uow.transaction(user.id) as session:
            self._lock_itemization(session, user, perms, gs_id)
            self._own_item(session, gs_id, item_id)
            repo.delete_item(session, item_id)

    # ---------------------------------------------------------------- counting ---------------
    def submit_counting(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        """AMD-08: Counting (ITEMIZATION) -> CATEGORISATION. Needs >= 1 line (G-01, BR-07)."""
        with self._uow.transaction(user.id) as session:
            return run_idempotent(
                session,
                idem,
                user.id,
                lambda: (200, self._submit_counting(session, user, perms, gs_id)),
            )

    def _submit_counting(
        self, session: Session, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID
    ) -> ItemizationStateOut:
        gs = self._lock_itemization(
            session, user, perms, gs_id, conflict_code="COUNTING_ALREADY_SUBMITTED"
        )
        if not repo.list_items(session, gs_id):
            raise ValidationFailed(
                "Add at least one item before submitting the count (BR-07)",
                code="ITEMS_REQUIRED",
                details={"items": ["At least one line is required"]},
            )
        gs_service.change_status_within_step(
            session,
            gs_id=gs_id,
            from_status=gs["status"],
            to_status=CATEGORISATION,
            step_code=ITEMIZE_STEP,
            reason="Counting submitted (AMD-08)",
            by=user.id,
        )
        repo.set_counted_by(session, gs_id, user.id)
        log.info("gs_counting_submitted", gs_id=str(gs_id), counted_by=str(user.id))
        view = gs_service.get_visible_goods_slip(session, user, perms, gs_id)
        return self._state(session, user, perms, view)

    # ------------------------------------- DEC-53: Counting & Categorisation -> RM Review ------
    def submit_itemization(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: SubmitItemizationIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        """DEC-53: one submit, one transaction (G-16 Idempotency-Key). From ITEMIZATION it runs
        the counting submit (-> CATEGORISATION, G-01 / BR-07) and then the categorisation submit
        (G-19 per line, inward into INWARD_STAGING, revision, -> RM_REVIEW, RM notified); after
        an RM send-back (CATEGORISATION) only the latter. Any failure rolls back both."""
        with self._uow.transaction(user.id) as session:
            return run_idempotent(
                session,
                idem,
                user.id,
                lambda: (200, self._submit_itemization(session, user, perms, gs_id, payload)),
            )

    def _submit_itemization(
        self,
        session: Session,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: SubmitItemizationIn,
    ) -> dict[str, Any]:
        gs = gs_service.lock_goods_slip(session, gs_id)
        if gs["status"] == "ITEMIZATION":
            self._submit_counting(session, user, perms, gs_id)
        elif gs["status"] == CATEGORISATION:
            self._lock_categorisation(session, user, perms, gs_id)
        else:
            raise Conflict(
                "This goods slip is not at Counting & Categorisation",
                code="GS_NOT_ITEMIZATION",
                details={"status": gs["status"]},
            )
        return self._submit_categorisation(
            session, user, perms, gs_id, SubmitCategorisationIn(remarks=payload.remarks)
        )

    # ---------------------------------------------------------------- categorise -------------
    def categorize(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: CategorizeIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        with self._uow.transaction(user.id) as session:
            return run_idempotent(
                session,
                idem,
                user.id,
                lambda: (200, self._categorize(session, user, perms, gs_id, payload)),
            )

    def _categorize(
        self,
        session: Session,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: CategorizeIn,
    ) -> CategorizeOut:
        gs = self._lock_categorisation(session, user, perms, gs_id)
        form = self._form(session, ITEMIZE_FORM)
        snapshot = form["snapshot"]
        options = form_field_options(snapshot, CATEGORY_FIELD)
        option = next((o for o in options if o.code == payload.category), None)
        if option is None:
            raise ValidationFailed(
                "Choose a return category",
                code="FORM_VALIDATION_FAILED",
                details={CATEGORY_FIELD: [f"Unknown or inactive category {payload.category!r}"]},
            )
        items = repo.list_items(session, gs_id)
        if not items:
            raise ValidationFailed(
                "Add at least one item line before categorising (BR-07)",
                code="ITEMS_REQUIRED",
                details={"items": ["At least one line is required"]},
            )
        if any(int(i["received_qty"]) < 0 for i in items):
            raise ValidationFailed("Received quantities must be 0 or more", code="ITEMS_INVALID")

        # Inward of the physically received quantity, one lot per line (DEC-28); short qty is not
        # stocked. Deterministic keys make a retried command a no-op on the ledger (G-16).
        inward = self._location(session, INWARD_LOCATION)
        for item in items:
            if int(item["received_qty"]) > 0:
                self._inward_line(session, gs_id, item, inward["id"], user.id)

        notes = _clean(payload.remarks)
        labels: dict[str, Any] = {
            CATEGORY_FIELD: {
                "label": field_label(snapshot, CATEGORY_FIELD),
                "value": option.code,
                "value_label": option.label,
            }
        }
        if notes:
            labels[CATEGORY_NOTES_FIELD] = {
                "label": field_label(snapshot, CATEGORY_NOTES_FIELD),
                "value": notes,
            }
        gs_service.set_category(
            session,
            gs_id,
            category_code=option.code,
            by=user.id,
            form_version_id=form["id"],
            labels_snapshot=labels,
        )
        wf = gs_service.pinned_workflow_snapshot(session, gs)
        step = route_step(wf, ITEMIZE_STEP, {"category_code": option.code})
        gs_service.transition_gs(
            session,
            gs_id=gs_id,
            to_status=STATUS_FOR_STEP[step],
            step_code=step,
            user=gs_service.workflow_user(user),
            reason=f"Step-3 categorised: {option.label}" + (f" — {notes}" if notes else ""),
            actor_step_code=ITEMIZE_STEP,
        )
        notified = 0
        if step == CSR_STEP:
            notified = notifications.publish(
                session,
                "CSR_APPROVAL_REQUIRED",
                role_codes=gs_service.step_role_codes(session, gs, CSR_STEP, "APPROVE"),
                notification_type="CSR_APPROVAL_REQUIRED",
                title=f"{gs['gs_no']}: {option.label} needs your approval",
                body=option.next_action_text or option.rule_text,
                entity_type=ENTITY_TYPE,
                entity_id=gs_id,
                gs_id=gs_id,
                priority="HIGH",
            )
        view = gs_service.get_visible_goods_slip(session, user, perms, gs_id)
        log.info("gs_categorized", gs_id=str(gs_id), category=option.code, step=step)
        return CategorizeOut(
            state=self._state(session, user, perms, view),
            task_ids=gs_service.open_task_ids(session, gs_id),
            notified_user_count=notified,
        )

    # ------------------------------------------------ Phase 5 item categorisation (AMD-09/11) -
    def get_categorisation_state(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
    ) -> CategorisationStateOut:
        with self._uow.transaction(user.id) as session:
            gs = gs_service.get_visible_goods_slip(session, user, perms, gs_id)
            items = repo.list_items(session, gs_id)
            item_ids = [i["id"] for i in items]
            buckets = repo.get_buckets_for_items(session, item_ids)
            counts = repo.get_counts_for_items(session, item_ids)
            counted_info = repo.get_counted_by_info(session, gs_id)
            counted_by_id = counted_info.get("counted_by") if counted_info else None
            counted_by_name = counted_info.get("counted_by_name") if counted_info else None

            # Informational only (DEC-51): any eligible user may categorise, not just the counter.
            is_same = user.is_super_admin or counted_by_id is None or counted_by_id == user.id
            can_submit = (
                gs["status"] == CATEGORISATION
                # Same permission the submit endpoint requires (router CreateUser). There is no
                # "perform" action in the permission vocabulary, so the flag was never true for
                # a verifier.
                and perms.allows("itemization", "create")
            )

            b_by_item: dict[UUID, list[ItemBucketOut]] = {iid: [] for iid in item_ids}
            for b in buckets:
                b_by_item.setdefault(b["gs_item_id"], []).append(
                    ItemBucketOut(
                        id=b["id"],
                        item_id=b["gs_item_id"],
                        field_code=b["field_code"],
                        field_label=b.get("label_snapshot") or b["field_code"],
                        qty=b["qty"],
                    )
                )

            c_by_item: dict[UUID, list[ItemCountOut]] = {iid: [] for iid in item_ids}
            for c in counts:
                c_by_item.setdefault(c["gs_item_id"], []).append(
                    ItemCountOut(
                        id=c["id"],
                        item_id=c["gs_item_id"],
                        count_type=c["field_code"],
                        field_label=c.get("label_snapshot") or c["field_code"],
                        count_value=c["qty"],
                    )
                )

            details: list[ItemCategorisationDetail] = []
            all_conserved = bool(items)
            version_id = repo.get_profile_version_id(session, gs_id)
            for item in items:
                fields = resolve_item_fields(session, item["product_id"], version_id)

                b_list = b_by_item.get(item["id"], [])
                tot_b = sum(b.qty for b in b_list)
                is_cons = tot_b == item["received_qty"]
                if not is_cons:
                    all_conserved = False

                sku_code, sku_name = item_display(item)
                details.append(
                    ItemCategorisationDetail(
                        item_id=item["id"],
                        line_no=item["line_no"],
                        product_id=item["product_id"],
                        sku_code=sku_code,
                        sku_name=sku_name,
                        category_name=item.get("category_name"),
                        documented_qty=item["documented_qty"],
                        received_qty=item["received_qty"],
                        profile_id=fields.profile_version_id,
                        profile_name=(
                            f"Profile v{fields.profile_version_no}"
                            if fields.profile_version_no is not None
                            else None
                        ),
                        allowed_buckets=fields.buckets,
                        allowed_counts=fields.counts,
                        buckets=b_list,
                        total_bucket_qty=tot_b,
                        is_conserved=is_cons,
                        counts=c_by_item.get(item["id"], []),
                    )
                )

            return CategorisationStateOut(
                goods_slip_id=gs_id,
                gs_no=gs["gs_no"],
                status=gs["status"],
                counted_by=counted_by_id,
                counted_by_name=counted_by_name,
                is_same_user_who_counted=is_same,
                can_submit=can_submit,
                all_conserved=all_conserved,
                items=details,
            )

    def save_item_categorisation(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        item_id: UUID,
        payload: SaveItemCategorisationIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        with self._uow.transaction(user.id) as session:
            return run_idempotent(
                session,
                idem,
                user.id,
                lambda: (
                    200,
                    self._save_item_categorisation(session, user, perms, gs_id, item_id, payload),
                ),
            )

    def _save_item_categorisation(
        self,
        session: Session,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        item_id: UUID,
        payload: SaveItemCategorisationIn,
    ) -> dict[str, Any]:
        gs = gs_service.lock_goods_slip(session, gs_id)
        if gs["status"] not in (CATEGORISATION, "RM_REVIEW"):
            raise Conflict(
                "Item categorisation is editable only in CATEGORISATION or RM_REVIEW",
                code="INVALID_STATUS",
            )

        # DEC-51: no "same user who counted" restriction. Any user holding the itemization
        # permission (router) may categorise any GS at this step, whoever did the count.

        item = repo.get_item(session, item_id)
        if not item or item["gs_id"] != gs_id:
            raise NotFound(f"Item {item_id} not found on goods slip {gs_id}", code="ITEM_NOT_FOUND")

        # Same resolution as the categorisation screen: only the offered codes are accepted.
        fields = resolve_item_fields(
            session, item["product_id"], repo.get_profile_version_id(session, gs_id)
        )
        cat_map = fields.bucket_ids()
        count_map = fields.count_ids()

        for b in payload.buckets:
            field_id = cat_map.get(b.field_code)
            if not field_id:
                raise ValidationFailed(
                    f"Bucket {b.field_code} is not enabled in this product's item field profile",
                    code="INVALID_FIELD",
                )
            repo.upsert_item_bucket(session, item_id, field_id, b.qty, user.id)

        for c in payload.counts:
            field_id = count_map.get(c.count_type)
            if not field_id:
                raise ValidationFailed(
                    f"Count {c.count_type} is not enabled in this product's item field profile",
                    code="INVALID_COUNT_TYPE",
                )
            repo.upsert_item_count(session, item_id, field_id, c.count_value, user.id)

        return {"item_id": str(item_id), "status": "SAVED"}

    def submit_categorisation(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: SubmitCategorisationIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        with self._uow.transaction(user.id) as session:
            return run_idempotent(
                session,
                idem,
                user.id,
                lambda: (200, self._submit_categorisation(session, user, perms, gs_id, payload)),
            )

    def _submit_categorisation(
        self,
        session: Session,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: SubmitCategorisationIn,
    ) -> dict[str, Any]:
        gs = gs_service.lock_goods_slip(session, gs_id)
        if gs["status"] != CATEGORISATION:
            raise Conflict("Goods slip must be in CATEGORISATION to submit", code="INVALID_STATUS")

        # DEC-51: any eligible user (itemization.create, router) may submit, whoever counted.

        items = repo.list_items(session, gs_id)
        if not items:
            raise ValidationFailed("At least one item is required (BR-07)", code="ITEMS_REQUIRED")

        item_ids = [i["id"] for i in items]
        buckets = repo.get_buckets_for_items(session, item_ids)
        b_sum_by_item: dict[UUID, int] = {iid: 0 for iid in item_ids}
        for b in buckets:
            b_sum_by_item[b["gs_item_id"]] = b_sum_by_item.get(b["gs_item_id"], 0) + b["qty"]

        # Enforce G-19: sum(bucket qty) = received_qty for every item
        for item in items:
            recv = item["received_qty"]
            b_sum = b_sum_by_item.get(item["id"], 0)
            if b_sum != recv:
                raise SystemGuardViolation(
                    "G-19",
                    f"Line {item['line_no']} ({item_display(item)[0]}) bucket total ({b_sum}) "
                    f"does not match counted quantity ({recv}) (G-19)",
                    details={
                        "item_id": str(item["id"]),
                        "received_qty": recv,
                        "bucket_total": b_sum,
                    },
                )

        # DEC-54 (Q1): inward stock booking moved from categorisation submit to RM approval.
        # Nothing is booked into INWARD_STAGING during review.

        # Record revision (SUBMITTED) in rm_review_revisions
        items_snapshot = [
            {
                "item_id": str(i["id"]),
                "sku_code": item_display(i)[0],
                "sku_name": item_display(i)[1],
                "documented_qty": i["documented_qty"],
                "received_qty": i["received_qty"],
                "buckets": [
                    {"code": b["field_code"], "label": b["label_snapshot"], "qty": b["qty"]}
                    for b in buckets
                    if b["gs_item_id"] == i["id"]
                ],
            }
            for i in items
        ]
        next_rev = int(
            session.execute(
                text(
                    "select coalesce(max(revision_no), 0) + 1 "
                    "from public.rm_review_revisions where gs_id = :gs_id"
                ),
                {"gs_id": gs_id},
            ).scalar_one()
        )
        session.execute(
            text(
                """
                insert into public.rm_review_revisions (
                    gs_id, revision_no, action, items_snapshot, remarks, created_by
                ) values (:gs_id, :rev_no, 'SUBMITTED', cast(:snapshot as jsonb), :remarks, :by)
                """
            ),
            {
                "gs_id": gs_id,
                "rev_no": next_rev,
                "snapshot": json.dumps(items_snapshot),
                "remarks": payload.remarks,
                "by": user.id,
            },
        )

        rem_suffix = f": {payload.remarks}" if payload.remarks else ""
        # Transition GS to RM_REVIEW
        gs_service.change_status_within_step(
            session,
            gs_id=gs_id,
            from_status=gs["status"],
            to_status="RM_REVIEW",
            step_code=ITEMIZE_STEP,
            reason=f"Categorisation submitted for RM Review (AMD-11){rem_suffix}",
            by=user.id,
        )

        # Close open itemize tasks
        repo.complete_open_tasks(session, gs_id)

        # Notify RM
        notifications.publish(
            session,
            "RM_REVIEW_REQUIRED",
            role_codes=["REPLACEMENT_MANAGER"],
            notification_type="RM_REVIEW_REQUIRED",
            title=f"{gs['gs_no']}: Categorisation submitted for RM Review",
            body=(
                f"Goods slip {gs['gs_no']} categorisation was completed "
                "and is ready for your review."
            ),
            entity_type="goods_slips",
            entity_id=gs_id,
            gs_id=gs_id,
            priority="HIGH",
        )

        return {
            "goods_slip_id": str(gs_id),
            "status": "RM_REVIEW",
            "message": "Categorisation submitted for RM Review",
        }

    def _inward_line(
        self, session: Session, gs_id: UUID, item: dict[str, Any], inward_id: UUID, by: UUID
    ) -> UUID:
        lot_id = ledger_service.find_inward_lot(session, item["id"])
        if lot_id is None:
            stock_item = ledger_service.finished_good_item(session, item["product_id"], by)
            lot_id = ledger_service.create_stock_lot(
                session,
                stock_item_id=stock_item,
                gs_id=gs_id,
                gs_item_id=item["id"],
                condition_class="AS_RECEIVED",
                created_by=by,
            )
            ledger_service.move_stock(
                session,
                lot_id=lot_id,
                from_location_id=None,
                to_location_id=inward_id,
                qty=int(item["received_qty"]),
                movement_type="INWARD",
                reference_type="gs_item",
                reference_id=item["id"],
                idempotency_key=f"{item['id']}:inward",
                actor_id=by,
                reason="Step-3 inward as received",
            )
        return lot_id

    # ---------------------------------------------------------------- CSR decision -----------
    def decide(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: CsrDecisionIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        with self._uow.transaction(user.id) as session:
            return run_idempotent(
                session,
                idem,
                user.id,
                lambda: (200, self._decide(session, user, perms, gs_id, payload)),
            )

    def _decide(
        self,
        session: Session,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: CsrDecisionIn,
    ) -> ItemizationStateOut:
        gs = gs_service.lock_goods_slip(session, gs_id)
        gs_service.get_visible_goods_slip(session, user, perms, gs_id)
        assert_step_actor(session, user, CSR_STEP, "APPROVE")
        current = repo.current_decision(session, gs_id)
        if current is not None:
            raise Conflict(
                "The Complete Sales Return was already decided; an admin must reopen it first",
                code="CSR_ALREADY_DECIDED",
                details={"decision": current["decision_code"]},
            )
        if gs["status"] != "CSR_APPROVAL_PENDING":
            raise Conflict(
                "This GS is not waiting for a CSR decision",
                code="GS_NOT_PENDING_CSR",
                details={"status": gs["status"]},
            )
        form = self._form(session, CSR_FORM)
        snapshot = form["snapshot"]
        options = form_field_options(snapshot, DECISION_FIELD)
        option = next((o for o in options if o.code == payload.decision), None)
        if option is None:
            raise ValidationFailed(
                "Choose Approve or Reject",
                code="FORM_VALIDATION_FAILED",
                details={DECISION_FIELD: [f"Unknown or inactive decision {payload.decision!r}"]},
            )
        remarks = _clean(payload.remarks)
        if option.code == CSR_REJECTED and not remarks:
            raise ValidationFailed(
                "A reason is required to reject the Complete Sales Return",
                code="FORM_VALIDATION_FAILED",
                details={DECISION_NOTES_FIELD: ["Required when rejecting"]},
            )
        assigned = repo.user_assigned_to_step(
            session, user.id, gs["workflow_version_id"], CSR_STEP, "APPROVE"
        )
        if not assigned:
            # Only a Super Admin passes assert_step_actor without the assignment (§9.3).
            gs_service.set_audit_reason(session, ADMIN_ACTION_REASON)
        labels: dict[str, Any] = {
            DECISION_FIELD: {
                "label": field_label(snapshot, DECISION_FIELD),
                "value": option.code,
                "value_label": option.label,
            }
        }
        if remarks:
            labels[DECISION_NOTES_FIELD] = {
                "label": field_label(snapshot, DECISION_NOTES_FIELD),
                "value": remarks,
            }
        repo.insert_decision(
            session,
            gs_id=gs_id,
            decision_code=option.code,
            remarks=remarks,
            form_version_id=form["id"],
            labels_snapshot=labels,
            by=user.id,
        )
        wf = gs_service.pinned_workflow_snapshot(session, gs)
        step = route_step(wf, CSR_STEP, {"csr_decision": option.code})
        history = (option.remarks or option.label) + (f" — {remarks}" if remarks else "")
        g03_ctx = {
            "csr_decision": option.code,
            "csr_decision_authorized": True,
            "original_category_code": CSR,
        }
        if option.code == CSR_REJECTED:
            # BR-08 / DD r20: reclassify to RO (original category kept) → inspection & grading.
            gs_service.convert_category(session, gs_id, RO)
            g03_ctx["category_code"] = RO
        else:
            # BR-09 / DD r19: forward to Sahil with packaging; flagged for Step-7 (CN, closure).
            gs_service.set_csr_commercial_path(session, gs_id, True)
            g03_ctx["category_code"] = CSR
        gs_service.transition_gs(
            session,
            gs_id=gs_id,
            to_status=STATUS_FOR_STEP[step],
            step_code=step,
            user=gs_service.workflow_user(user),
            reason=history,
            context_overrides=g03_ctx,
            actor_step_code=CSR_STEP,
            actor_assignment_type="APPROVE",
        )
        if option.code == CSR_APPROVED:
            self._propose_csr_transfer(session, gs, option, user.id)
        if not assigned:
            gs_service.set_audit_reason(session, None)
        info = repo.categorization_info(session, gs_id) or {}
        if info.get("categorized_by"):
            notifications.publish(
                session,
                "CSR_DECIDED",
                user_ids=[info["categorized_by"]],
                notification_type="CSR_DECIDED",
                title=f"{gs['gs_no']}: {option.label}",
                body=remarks or option.next_action_text,
                entity_type=ENTITY_TYPE,
                entity_id=gs_id,
                gs_id=gs_id,
                priority="NORMAL" if option.code == CSR_APPROVED else "HIGH",
            )
        log.info(
            "csr_decided",
            gs_id=str(gs_id),
            decision=option.code,
            admin_action=not assigned,
            step=step,
        )
        view = gs_service.get_visible_goods_slip(session, user, perms, gs_id)
        return self._state(session, user, perms, view)

    def _propose_csr_transfer(
        self, session: Session, gs: dict[str, Any], option: CategoryOption, by: UUID
    ) -> UUID | None:
        """INWARD_STAGING → INTERMEDIATE_STORE "with packaging" for every stocked line (BR-09)."""
        inward = self._location(session, INWARD_LOCATION)
        lines = [
            custody.ProposedLine(lot_id=lot["lot_id"], qty=qty)
            for lot in ledger_service.lots_for_gs(session, gs["id"])
            if (qty := _qty_at(lot, inward["code"])) > 0
        ]
        if not lines:
            log.info("csr_transfer_skipped_no_stock", gs_id=str(gs["id"]))
            return None
        transfer_id = custody.propose_transfer(
            session,
            gs_id=gs["id"],
            from_location_code=INWARD_LOCATION,
            to_location_code=CSR_TARGET_LOCATION,
            lines=lines,
            purpose_code=CSR_TRANSFER_PURPOSE,
            with_packaging=True,
            notes=option.next_action_text,
            by=by,
        )
        target = self._location(session, CSR_TARGET_LOCATION)
        if target.get("custodian_role_code"):
            notifications.publish(
                session,
                "TRANSFER_PROPOSED",
                role_codes=[str(target["custodian_role_code"])],
                notification_type="TRANSFER_PROPOSED",
                title=f"{gs['gs_no']}: Complete Sales Return coming with packaging",
                body=option.next_action_text,
                entity_type=ENTITY_TYPE,
                entity_id=gs["id"],
                gs_id=gs["id"],
            )
        return transfer_id

    def reopen(
        self, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID, payload: ReopenIn
    ) -> ItemizationStateOut:
        reason = payload.reason.strip()
        if not gs_service.is_gs_admin(user, perms):
            raise PermissionDenied("Only an admin may reopen a CSR decision", code="ADMIN_REQUIRED")
        with self._uow.transaction(user.id) as session:
            gs = gs_service.lock_goods_slip(session, gs_id)
            gs_service.get_visible_goods_slip(session, user, perms, gs_id)
            current = repo.current_decision(session, gs_id)
            if current is None:
                raise Conflict("There is no CSR decision to reopen", code="NO_CSR_DECISION")
            gs_service.set_audit_reason(session, f"Reopen CSR decision: {reason}")
            if current["decision_code"] == CSR_APPROVED:
                if gs["status"] != "IN_PROCESS":
                    raise Conflict(
                        "The approved CSR has moved on and cannot be reopened",
                        code="CSR_NOT_REOPENABLE",
                        details={"status": gs["status"]},
                    )
                for t in custody.transfers_for_gs(session, gs_id):
                    if t["purpose_code"] == CSR_TRANSFER_PURPOSE and t["status"] != "CANCELLED":
                        custody.cancel_proposal(session, t["id"], reason=f"CSR reopened: {reason}")
                gs_service.set_csr_commercial_path(session, gs_id, False)
                category = None
            else:
                if gs["status"] != "INSPECTION" or repo.has_inspections(session, gs_id):
                    raise Conflict(
                        "Inspection has started; the rejection cannot be reopened",
                        code="CSR_NOT_REOPENABLE",
                        details={"status": gs["status"]},
                    )
                category = CSR
            repo.reopen_decision(session, current["id"], reason=reason, by=user.id)
            gs_service.reroute_to_step(
                session,
                gs_id=gs_id,
                from_status=gs["status"],
                to_status="CSR_APPROVAL_PENDING",
                step_code=CSR_STEP,
                reason=f"CSR decision reopened by admin: {reason}",
                by=user.id,
                category_code=category,
            )
            gs_service.set_audit_reason(session, None)
            notifications.publish(
                session,
                "CSR_APPROVAL_REQUIRED",
                role_codes=gs_service.step_role_codes(session, gs, CSR_STEP, "APPROVE"),
                notification_type="CSR_APPROVAL_REQUIRED",
                title=f"{gs['gs_no']}: CSR decision reopened",
                body=reason,
                entity_type=ENTITY_TYPE,
                entity_id=gs_id,
                gs_id=gs_id,
                priority="HIGH",
            )
            view = gs_service.get_visible_goods_slip(session, user, perms, gs_id)
            return self._state(session, user, perms, view)

    # ---------------------------------------------------------------- corrections ------------
    def request_correction(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        item_id: UUID,
        payload: CorrectionIn,
    ) -> CorrectionOut:
        reason = payload.reason.strip()
        with self._uow.transaction(user.id) as session:
            gs = gs_service.lock_goods_slip(session, gs_id)
            gs_service.get_visible_goods_slip(session, user, perms, gs_id)
            if not self._may_request_correction(session, user, perms):
                raise PermissionDenied(
                    "You may not request item line corrections", code="NOT_STEP_ACTOR"
                )
            _require_correctable(gs)
            item = self._own_item(session, gs_id, item_id)
            if repo.item_has_final_inspection(session, item_id):
                raise Conflict("This line is already graded", code="LINE_GRADED")
            if repo.open_correction_for_item(session, item_id):
                raise Conflict(
                    "A correction for this line is already waiting for approval",
                    code="CORRECTION_PENDING",
                )
            if (
                payload.documented_qty == item["documented_qty"]
                and payload.received_qty == item["received_qty"]
            ):
                raise ValidationFailed(
                    "The correction does not change any quantity", code="CORRECTION_NO_CHANGE"
                )
            _require_quantity(payload.documented_qty, payload.received_qty)
            cid = repo.insert_correction(
                session,
                gs_id=gs_id,
                item=item,
                new_documented_qty=payload.documented_qty,
                new_received_qty=payload.received_qty,
                reason=reason,
                by=user.id,
            )
            notifications.publish(
                session,
                "ITEM_CORRECTION_REQUESTED",
                role_codes=gs_service.step_role_codes(session, gs, CSR_STEP, "APPROVE"),
                notification_type="ITEM_CORRECTION_REQUESTED",
                title=f"{gs['gs_no']} line {item['line_no']}: correction requested",
                body=reason,
                entity_type=ENTITY_TYPE,
                entity_id=gs_id,
                gs_id=gs_id,
            )
            row = repo.get_correction(session, cid)
            if not row:
                raise NotFound("Correction could not be loaded after creation")
            return _correction_out(row)

    def decide_correction(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        correction_id: UUID,
        payload: CorrectionDecisionIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        with self._uow.transaction(user.id) as session:
            return run_idempotent(
                session,
                idem,
                user.id,
                lambda: (
                    200,
                    self._decide_correction(session, user, perms, gs_id, correction_id, payload),
                ),
            )

    def _decide_correction(
        self,
        session: Session,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        correction_id: UUID,
        payload: CorrectionDecisionIn,
    ) -> CorrectionOut:
        remarks = _clean(payload.remarks)
        if payload.decision == "REJECT" and not remarks:
            raise ValidationFailed(
                "A reason is required to reject the correction",
                code="FORM_VALIDATION_FAILED",
                details={"remarks": ["Required when rejecting"]},
            )
        gs = gs_service.lock_goods_slip(session, gs_id)
        gs_service.get_visible_goods_slip(session, user, perms, gs_id)
        corr = repo.get_correction(session, correction_id, for_update=True)
        if not corr or corr["gs_id"] != gs_id:
            raise NotFound("Line correction not found on this GS")
        if corr["status"] != "REQUESTED":
            raise Conflict(
                f"The correction was already {corr['status'].lower()}",
                code="CORRECTION_ALREADY_DECIDED",
            )
        _require_correctable(gs)
        if payload.decision == "REJECT":
            repo.decide_correction(
                session, correction_id, status="REJECTED", by=user.id, remarks=remarks
            )
        else:
            self._apply_correction(session, gs, corr, user.id, remarks)
        notifications.publish(
            session,
            "ITEM_CORRECTION_DECIDED",
            user_ids=[corr["requested_by"]],
            notification_type="ITEM_CORRECTION_"
            + ("APPROVED" if payload.decision == "APPROVE" else "REJECTED"),
            title=f"{gs['gs_no']} line {corr['line_no']}: correction "
            + ("approved" if payload.decision == "APPROVE" else "rejected"),
            body=remarks,
            entity_type=ENTITY_TYPE,
            entity_id=gs_id,
            gs_id=gs_id,
        )
        row = repo.get_correction(session, correction_id)
        if not row:
            raise NotFound("Correction could not be loaded after the decision")
        return _correction_out(row)

    def _apply_correction(
        self,
        session: Session,
        gs: dict[str, Any],
        corr: dict[str, Any],
        by: UUID,
        remarks: str | None,
    ) -> None:
        """Approve + apply in one transaction: line quantities (DB lets them change only for this
        approved correction) and an ADJUST movement for the received delta (G-16, G-17)."""
        if repo.item_has_final_inspection(session, corr["gs_item_id"]):
            raise Conflict("This line is already graded", code="LINE_GRADED")
        repo.decide_correction(session, corr["id"], status="APPROVED", by=by, remarks=remarks)
        gs_service.set_audit_reason(session, f"Line correction: {corr['reason']}")
        repo.set_transaction_setting(session, "app.item_correction_id", str(corr["id"]))
        repo.update_item(
            session,
            corr["gs_item_id"],
            {
                "documented_qty": corr["new_documented_qty"],
                "received_qty": corr["new_received_qty"],
            },
        )
        repo.set_transaction_setting(session, "app.item_correction_id", None)
        delta = int(corr["new_received_qty"]) - int(corr["old_received_qty"])
        movement_id: UUID | None = None
        if delta != 0:
            inward = self._location(session, INWARD_LOCATION)
            lot_id = ledger_service.find_inward_lot(session, corr["gs_item_id"])
            if lot_id is None:
                item = repo.get_item(session, corr["gs_item_id"])
                if not item or delta < 0:
                    raise Conflict("The line has no stock to reduce", code="NO_STOCK_FOR_LINE")
                stock_item = ledger_service.finished_good_item(session, item["product_id"], by)
                lot_id = ledger_service.create_stock_lot(
                    session,
                    stock_item_id=stock_item,
                    gs_id=gs["id"],
                    gs_item_id=item["id"],
                    condition_class="AS_RECEIVED",
                    created_by=by,
                )
            movement_id = ledger_service.move_stock(
                session,
                lot_id=lot_id,
                from_location_id=None if delta > 0 else inward["id"],
                to_location_id=inward["id"] if delta > 0 else None,
                qty=abs(delta),
                movement_type="ADJUST",
                reference_type="gs_item_correction",
                reference_id=corr["id"],
                idempotency_key=f"{corr['id']}:adjust",
                actor_id=by,
                reason=f"Line correction: {corr['reason']}",
            )
        repo.mark_correction_applied(session, corr["id"], movement_id)
        gs_service.set_audit_reason(session, None)

    # ---------------------------------------------------------------- packaging check --------
    def packaging_check(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        lot_id: UUID,
        payload: PackagingCheckIn,
    ) -> PackagingCheckOut:
        with self._uow.transaction(user.id) as session:
            lot = ledger_service.get_lot(session, lot_id)
            if not lot:
                raise NotFound("Lot not found")
            gs = gs_service.get_visible_goods_slip(session, user, perms, lot["gs_id"])
            # G-03: nothing happens to the goods of an undecided CSR (handover comes after it).
            gs_service.assert_csr_decided(gs, repo.current_decision(session, lot["gs_id"]))
            if not self._may_check_packaging(session, user, perms):
                raise PermissionDenied(
                    "Only the Intermediate Store in-charge records packaging checks (WF r4)",
                    code="NOT_LOCATION_CUSTODIAN",
                )
            qty = payload.qty_replaced
            if payload.result == "OK" and qty != 0:
                raise ValidationFailed(
                    "Packaging OK means nothing was replaced",
                    code="FORM_VALIDATION_FAILED",
                    details={"qty_replaced": ["Must be 0 when the packaging is OK"]},
                )
            if payload.result == "REPLACED" and not 0 < qty <= int(lot["total_qty"]):
                raise ValidationFailed(
                    f"Enter the replaced quantity (1-{lot['total_qty']})",
                    code="FORM_VALIDATION_FAILED",
                    details={"qty_replaced": [f"Between 1 and {lot['total_qty']}"]},
                )
            check_id = repo.insert_packaging_check(
                session,
                lot_id=lot_id,
                result_code=payload.result,
                qty=qty,
                remarks=_clean(payload.remarks),
                by=user.id,
            )
            row = repo.get_packaging_check(session, check_id)
            if not row:
                raise NotFound("Packaging check could not be loaded after creation")
            return _check_out(row)

    # ---------------------------------------------------------------- internals --------------
    def _lock_itemization(
        self,
        session: Session,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        *,
        conflict_code: str = "GS_NOT_ITEMIZATION",
    ) -> dict[str, Any]:
        gs = gs_service.lock_goods_slip(session, gs_id)
        gs_service.get_visible_goods_slip(session, user, perms, gs_id)
        assert_step_actor(session, user, ITEMIZE_STEP, "PERFORM")
        if gs["status"] != "ITEMIZATION":
            raise Conflict(
                "Item lines can only be changed while the GS is at itemisation; "
                "use a line correction after categorisation",
                code=conflict_code,
                details={"status": gs["status"], "category_code": gs.get("category_code")},
            )
        return gs

    def _lock_categorisation(
        self, session: Session, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID
    ) -> dict[str, Any]:
        """AMD-08: the GS-wise category is chosen after counting was submitted."""
        gs = gs_service.lock_goods_slip(session, gs_id)
        gs_service.get_visible_goods_slip(session, user, perms, gs_id)
        assert_step_actor(session, user, ITEMIZE_STEP, "PERFORM")
        if gs["status"] != CATEGORISATION:
            code = (
                "COUNTING_NOT_SUBMITTED"
                if gs["status"] == "ITEMIZATION"
                else ("GS_ALREADY_CATEGORIZED")
            )
            raise Conflict(
                "Submit the count first; the category is chosen in categorisation"
                if code == "COUNTING_NOT_SUBMITTED"
                else "This goods slip is not in categorisation",
                code=code,
                details={"status": gs["status"], "category_code": gs.get("category_code")},
            )
        return gs

    def _may_request_correction(
        self, session: Session, user: CurrentUser, perms: EffectivePermissions
    ) -> bool:
        if perms.allows("itemization", "approve"):
            return True
        return perms.allows("itemization", "edit") and ITEMIZE_STEP in step_codes_for(
            session, user, "PERFORM"
        )

    def _may_check_packaging(
        self, session: Session, user: CurrentUser, perms: EffectivePermissions
    ) -> bool:
        """WF r4: the Intermediate Store in-charge = custodian (role / user) of that location."""
        if not perms.allows("inventory", "edit"):
            return False
        store = self._location(session, CSR_TARGET_LOCATION)
        return bool(
            user.is_super_admin
            or store.get("custodian_user_id") == user.id
            or repo.user_has_role_id(session, user.id, store.get("custodian_role_id"))
        )

    def _form(self, session: Session, code: str) -> dict[str, Any]:
        form = repo.get_published_form(session, code)
        if not form or not form.get("snapshot"):
            raise NotFound(f"No published {code} form", code="FORM_NOT_PUBLISHED")
        return {**form, "snapshot": dict(form["snapshot"])}

    def _location(self, session: Session, code: str) -> dict[str, Any]:
        loc = ledger_service.get_location_by_code(session, code)
        if not loc or not loc["is_active"]:
            raise NotFound(
                f"Inventory location {code} is not configured", code="LOCATION_NOT_FOUND"
            )
        return loc

    def _product(self, session: Session, product_id: UUID) -> dict[str, Any]:
        product = repo.get_product(session, product_id)
        if not product or not product["is_active"]:
            raise ValidationFailed(
                "Product not found or inactive",
                code="FORM_VALIDATION_FAILED",
                details={"product_id": ["Choose an active product"]},
            )
        return product

    def _own_item(self, session: Session, gs_id: UUID, item_id: UUID) -> dict[str, Any]:
        item = repo.get_item(session, item_id, for_update=True)
        if not item or item["gs_id"] != gs_id:
            raise NotFound("Item line not found on this GS")
        return item

    def _short_rule(self, session: Session) -> tuple[bool, set[UUID]]:
        all_categories = repo.get_setting(session, "track_short_qty_all_categories") is not False
        return all_categories, set() if all_categories else repo.short_qty_category_ids(session)

    def _items(self, session: Session, gs_id: UUID) -> list[ItemOut]:
        all_categories, short_categories = self._short_rule(session)
        lots = {
            lot["gs_item_id"]: lot
            for lot in ledger_service.lots_for_gs(session, gs_id)
            if lot["condition_class"] == "AS_RECEIVED" and lot["gs_item_id"]
        }
        rows = repo.list_items(session, gs_id)
        splits = _splits(session, [r["id"] for r in rows])
        return [
            _item_out(row, all_categories, short_categories, lots.get(row["id"]), splits)
            for row in rows
        ]

    def _item_out(self, session: Session, item_id: UUID) -> ItemOut:
        row = repo.get_item(session, item_id)
        if not row:
            raise NotFound("Item line could not be loaded")
        all_categories, short_categories = self._short_rule(session)
        return _item_out(row, all_categories, short_categories, None, _splits(session, [item_id]))

    def _evidence(self, session: Session, gs_id: UUID) -> list[Any]:
        return [
            attachments.to_out(a)
            for a in attachments.attachments_for_gs(session, gs_id)
            if a["status"] == "CONFIRMED"
        ]

    def _state(
        self,
        session: Session,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs: dict[str, Any],
    ) -> ItemizationStateOut:
        gs_id = gs["id"]
        cat_options = form_field_options(
            self._form(session, ITEMIZE_FORM)["snapshot"], CATEGORY_FIELD
        )
        dec_options = form_field_options(self._form(session, CSR_FORM)["snapshot"], DECISION_FIELD)
        items = self._items(session, gs_id)
        decisions = [_decision_out(d, dec_options) for d in repo.list_decisions(session, gs_id)]
        current = next((d for d in decisions if d.is_current), None)
        lot_rows = ledger_service.lots_for_gs(session, gs_id)
        checks = repo.packaging_checks_for_lots(session, [r["lot_id"] for r in lot_rows])
        lots = [
            LotOut(
                **{k: r[k] for k in LotOut.model_fields if k not in ("packaging_checks",)},
                packaging_checks=[_check_out(c) for c in checks if c["lot_id"] == r["lot_id"]],
            )
            for r in lot_rows
        ]
        status = gs["status"]
        perform = ITEMIZE_STEP in step_codes_for(session, user, "PERFORM")
        approve = CSR_STEP in step_codes_for(session, user, "APPROVE")
        may_perform = perform and perms.allows("itemization", "create")
        edit_lines = status == "ITEMIZATION" and may_perform
        info = repo.categorization_info(session, gs_id) or {}
        return ItemizationStateOut(
            goods_slip=_gs_out(gs),
            items=items,
            totals=_totals(items),
            category_options=cat_options,
            category_label=_category_label(gs, cat_options, info),
            decision_options=dec_options,
            current_decision=current,
            decisions=decisions,
            lots=lots,
            transfers=[
                TransferOut.model_validate(t) for t in custody.transfers_for_gs(session, gs_id)
            ],
            corrections=[_correction_out(c) for c in repo.list_corrections(session, gs_id)],
            evidence=self._evidence(session, gs_id),
            permissions=ItemizationPermissions(
                can_edit_lines=edit_lines,
                can_submit_counting=edit_lines and bool(items),
                can_categorize=status == CATEGORISATION and may_perform,
                can_submit_to_rm=status in ("ITEMIZATION", CATEGORISATION)
                and may_perform
                and bool(items)
                and all(i.is_balanced for i in items),
                can_decide=status == "CSR_APPROVAL_PENDING"
                and current is None
                and approve
                and perms.allows("itemization", "approve"),
                can_reopen=current is not None and gs_service.is_gs_admin(user, perms),
                can_request_correction=_correctable(status)
                and self._may_request_correction(session, user, perms),
                can_decide_correction=perms.allows("itemization", "approve"),
                can_check_packaging=bool(lots)
                and self._may_check_packaging(session, user, perms)
                and (
                    current is not None
                    or "CSR" not in (gs.get("category_code"), gs.get("original_category_code"))
                ),
            ),
        )


# --- module helpers ------------------------------------------------------------------------------
def _clean(value: str | None) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _require_quantity(documented: int, received: int) -> None:
    if documented <= 0 and received <= 0:
        raise ValidationFailed(
            "Enter the quantity as per document or the quantity physically received",
            code="FORM_VALIDATION_FAILED",
            details={"documented_qty": ["Either quantity must be more than 0"]},
        )


def _correctable(status: str) -> bool:
    # Mirrors rms_private.gs_item_correctable_status (after categorisation, before grading).
    return status in ("CSR_APPROVAL_PENDING", "INSPECTION")


def _require_correctable(gs: dict[str, Any]) -> None:
    if not _correctable(gs["status"]):
        raise Conflict(
            "Line corrections are possible after categorisation and before grading",
            code="GS_NOT_CORRECTABLE",
            details={"status": gs["status"]},
        )


def _qty_at(lot: dict[str, Any], location_code: str) -> int:
    return sum(
        int(b["qty"]) for b in lot.get("balances") or [] if b.get("location_code") == location_code
    )


Splits = tuple[dict[UUID, list[ItemBucketOut]], dict[UUID, list[ItemCountOut]]]


def _splits(session: Session, item_ids: list[UUID]) -> Splits:
    """DEC-53: condition split (buckets) and item counts per line, with G-18 label snapshots."""
    buckets: dict[UUID, list[ItemBucketOut]] = {}
    for b in repo.get_buckets_for_items(session, item_ids):
        buckets.setdefault(b["gs_item_id"], []).append(
            ItemBucketOut(
                id=b["id"],
                item_id=b["gs_item_id"],
                field_code=b["field_code"],
                field_label=b.get("label_snapshot") or b["field_code"],
                qty=b["qty"],
            )
        )
    counts: dict[UUID, list[ItemCountOut]] = {}
    for c in repo.get_counts_for_items(session, item_ids):
        counts.setdefault(c["gs_item_id"], []).append(
            ItemCountOut(
                id=c["id"],
                item_id=c["gs_item_id"],
                count_type=c["field_code"],
                field_label=c.get("label_snapshot") or c["field_code"],
                count_value=c["qty"],
            )
        )
    return buckets, counts


def _item_out(
    row: dict[str, Any],
    all_categories: bool,
    short_categories: set[UUID],
    lot: dict[str, Any] | None,
    splits: Splits | None = None,
) -> ItemOut:
    b_list = (splits[0] if splits else {}).get(row["id"], [])
    c_list = (splits[1] if splits else {}).get(row["id"], [])
    bucket_total = sum(b.qty for b in b_list)
    return ItemOut(
        id=row["id"],
        gs_id=row["gs_id"],
        line_no=row["line_no"],
        product_id=row["product_id"],
        product_code=row["product_code_snapshot"],
        product_name=row["product_name_snapshot"],
        category_id=row["category_id"],
        category_code=row["category_code_snapshot"],
        category_name=row["category_name"],
        documented_qty=row["documented_qty"],
        received_qty=row["received_qty"],
        short_qty=row["short_qty"],
        excess_qty=row["excess_qty"],
        is_short=is_short(row, all_categories=all_categories, short_categories=short_categories),
        remarks=row["remarks"],
        lot_id=lot["lot_id"] if lot else None,
        stocked_qty=int(lot["total_qty"]) if lot else None,
        buckets=b_list,
        counts=c_list,
        bucket_total=bucket_total,
        is_balanced=bucket_total == int(row["received_qty"]),
    )


def _totals(items: list[ItemOut]) -> ItemizationTotals:
    def total(key: Callable[[ItemOut], int]) -> int:
        return sum(key(i) for i in items)

    return ItemizationTotals(
        lines=len(items),
        documented_qty=total(lambda i: i.documented_qty),
        received_qty=total(lambda i: i.received_qty),
        short_qty=total(lambda i: i.short_qty),
        excess_qty=total(lambda i: i.excess_qty),
    )


def _category_label(
    gs: dict[str, Any], options: list[CategoryOption], info: dict[str, Any]
) -> str | None:
    code = gs.get("category_code")
    if not code:
        return None
    labels = dict(info.get("category_labels_snapshot") or {})
    entry = labels.get(CATEGORY_FIELD)
    if isinstance(entry, dict) and entry.get("value") == code and entry.get("value_label"):
        return str(entry["value_label"])
    return next((o.label for o in options if o.code == code), code)


def assert_csr_decided_for(session: Session, gs: dict[str, Any]) -> None:
    """G-03 for downstream modules (custody handover, Stage-6): service-to-service entry point."""
    gs_service.assert_csr_decided(gs, repo.current_decision(session, gs["id"]))
