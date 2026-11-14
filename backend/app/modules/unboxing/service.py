"""Step-2 Unboxing (master plan §2.2 Step-2, DD r11-r16, BR-03..BR-06, G-02, DEC-03..DEC-05).

* start: GATE_CREATED → UNBOXING (S1_UNBOX PERFORM); the S1_UNBOX task opened at the gate stays.
* documents: each confirmed DOC_PHOTO gets exactly one classification, validated against the
  published S1_UNBOXING form (re-validated on edit against the version it was created under,
  G-18) plus BR-05 (Invoice items verified). DB CHECKs mirror DD r12-r15.
* missing-document exception (DEC-03): only for a GS flagged missing documentation; a confirmed
  PARCEL_PHOTO + mandatory remark, decided by a holder of unboxing.approve (Replacement Manager).
* complete: G-02 (service check → 422 `G-02` with what is missing; the workflow engine guard and
  the DB trigger `goods_slips_g02_guard` re-check) → ITEMIZATION, S1_ITEMIZE task, Accounts alert.
* Accounts queue (WF r3 "Dashboard and Alert system for Accounts team", BR-06, DEC-05).
* Change plan 2026-11-12 Phase 3 (AMD-08 "Carton Opening"): one confirmed video per carton
  (G-02, AMD-03) with carton-wise progress; more document rows can be added while the GS is
  UNBOXING (gs_gate_documents, stage S1_UNBOX, AMD-04), and an Invoice / Debit Note row alerts
  Accounts at once (AMD-05; never twice for the same document).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from app.core.db import UnitOfWork
from app.core.errors import (
    Conflict,
    NotFound,
    PermissionDenied,
    SystemGuardUnmet,
    ValidationFailed,
)
from app.core.idempotency import IdempotencyKey, IdempotentResult, run_idempotent
from app.core.permissions import EffectivePermissions, assert_step_actor, step_codes_for
from app.core.security import CurrentUser
from app.modules.attachments import service as attachments
from app.modules.attachments.allowlist import SIZE_SETTING_FOR_KIND
from app.modules.config.forms.validator import validate_submission
from app.modules.goods_slips import service as gs_service
from app.modules.goods_slips.schemas import GateDocumentIn, GateDocumentOut
from app.modules.notifications import service as notifications
from app.modules.unboxing import repository as repo
from app.modules.unboxing.schemas import (
    AcknowledgeOut,
    CartonDocumentIn,
    Checklist,
    CompleteOut,
    DocumentIn,
    DocumentOut,
    DocumentPatchIn,
    ExceptionDecisionIn,
    ExceptionIn,
    ExceptionOut,
    OptionOut,
    QueueDocument,
    QueueItem,
    UnboxingGs,
    UnboxingPermissions,
    UnboxingStateOut,
    UploadLimits,
)
from app.shared.guards import g02_missing_evidence
from app.shared.pagination import Page, PageParams

log = structlog.get_logger("rms.unboxing")

FORM_CODE = "S1_UNBOXING"
CLASSIFICATION_SET = "RECEIVED_DOC_CLASSIFICATION"  # DD r12-r15
UNBOX_STEP = "S1_UNBOX"
ITEMIZE_STEP = "S1_ITEMIZE"
ENTITY_TYPE = "goods_slip"
# DEC-05: Step-2 document alerts go to the Accounts team; DEC-03 requests to the RM.
ACCOUNTS_ALERT_ROLES = ["ACCOUNTS"]
EXCEPTION_APPROVER_ROLES = ["REPLACEMENT_MANAGER"]

# S1_UNBOXING form field → gs_documents column, per classification code (DD r12-r15).
_COMMON_FIELDS = {"doc_classification": "classification_code"}
_FIELDS_BY_CLASS: dict[str, dict[str, str]] = {
    "INVOICE": {
        "invoice_no": "doc_no",
        "invoice_date": "doc_date",
        "buyer_gstin": "buyer_gstin",
        "seller_gstin": "seller_gstin",
        "items_verified": "items_verified",
    },
    "DEBIT_NOTE": {"dn_number": "doc_no", "dn_amount": "amount"},
    "DELIVERY_CHALLAN": {"challan_qty_matched": "qty_matched", "challan_remarks": "remarks"},
    "HANDWRITTEN_SLIP": {"party_claim_text": "party_claim_text"},
}
_GSTIN_FIELDS = ("buyer_gstin", "seller_gstin")


# --- pure helpers (unit-tested) ----------------------------------------------------------------
def classification_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """The S1_UNBOXING form without its file fields: files are validated by the attachments
    endpoints, the classification card submits only the document fields."""
    return {
        **snapshot,
        "fields": [f for f in snapshot.get("fields") or [] if f.get("control_type") != "file"],
    }


def resolve_document(
    snapshot: dict[str, Any], raw_values: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Validate a classification against the form snapshot → (columns, values, labels).

    Raises ValidationFailed(FORM_VALIDATION_FAILED) with per-field errors.
    """
    values = dict(raw_values)
    for key in _GSTIN_FIELDS:
        if isinstance(values.get(key), str):
            values[key] = values[key].replace(" ", "").upper()
    form = classification_snapshot(snapshot)
    result = validate_submission(form, values)
    errors = {k: list(v) for k, v in result.errors.items()}
    clean = dict(result.sanitized_values)
    code = clean.get("doc_classification")

    columns: dict[str, Any] = {"classification_code": code}
    mapping = _FIELDS_BY_CLASS.get(str(code), {}) if code else {}
    for field_key, column in mapping.items():
        columns[column] = clean.get(field_key)

    if code == "INVOICE" and clean.get("items_verified") is not True:
        # BR-05: invoice photos require item verification.
        errors.setdefault("items_verified", []).append(
            "Verify the item details against the invoice (BR-05)"
        )
    if code == "DELIVERY_CHALLAN" and not isinstance(clean.get("challan_qty_matched"), bool):
        errors.setdefault("challan_qty_matched", []).append("Answer whether the quantity matched")
    raw_date = columns.get("doc_date")
    if isinstance(raw_date, str) and raw_date.strip():
        try:
            columns["doc_date"] = date.fromisoformat(raw_date.strip()[:10])
        except ValueError:
            errors.setdefault("invoice_date", []).append("Enter a valid date (YYYY-MM-DD)")
    if columns.get("amount") is not None:
        try:
            columns["amount"] = Decimal(str(columns["amount"]))
            if columns["amount"] < 0:
                raise InvalidOperation
        except InvalidOperation:
            errors.setdefault("dn_amount", []).append("Enter an amount of 0 or more")
    for col in ("doc_no", "buyer_gstin", "seller_gstin", "party_claim_text", "remarks"):
        if isinstance(columns.get(col), str):
            columns[col] = columns[col].strip() or None
    if errors:
        raise ValidationFailed(
            "The document classification has errors",
            code="FORM_VALIDATION_FAILED",
            details=errors,
        )
    return columns, clean, labels_snapshot(form, clean)


def labels_snapshot(snapshot: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """G-18 / rule e: field and option labels as shown when the document was classified."""
    out: dict[str, Any] = {}
    for field in snapshot.get("fields") or []:
        key = field.get("field_key")
        if key not in values:
            continue
        entry: dict[str, Any] = {"label": field.get("label", key), "value": values[key]}
        options = {o.get("code"): o.get("label") for o in field.get("option_items") or []}
        if options:
            entry["value_label"] = options.get(values[key], values[key])
        out[key] = entry
    return out


def _classification_label(labels: dict[str, Any], code: str) -> str:
    entry = labels.get("doc_classification") if isinstance(labels, dict) else None
    if isinstance(entry, dict) and entry.get("value_label"):
        return str(entry["value_label"])
    return code


def _doc_values(labels: dict[str, Any]) -> dict[str, Any]:
    return {k: v.get("value") for k, v in labels.items() if isinstance(v, dict)}


def _doc_out(row: dict[str, Any]) -> DocumentOut:
    labels = dict(row.get("labels_snapshot") or {})
    return DocumentOut(
        **{k: row[k] for k in DocumentOut.model_fields if k in row and k != "values"},
        classification_label=_classification_label(labels, row["classification_code"]),
        values=_doc_values(labels),
    )


def _exc_out(row: dict[str, Any]) -> ExceptionOut:
    return ExceptionOut(**{k: row[k] for k in ExceptionOut.model_fields})


def _gs_out(gs: dict[str, Any]) -> UnboxingGs:
    return UnboxingGs.model_validate({k: gs.get(k) for k in UnboxingGs.model_fields})


class UnboxingService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    # ---------------------------------------------------------------- reads ------------------
    def state(
        self, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID
    ) -> UnboxingStateOut:
        with self._uow.transaction(user.id) as session:
            gs = gs_service.get_visible_goods_slip(session, user, perms, gs_id)
            return self._state(session, user, perms, gs)

    def pending_exceptions(
        self, user: CurrentUser, perms: EffectivePermissions, limit: int
    ) -> list[ExceptionOut]:
        with self._uow.transaction(user.id) as session:
            rows = repo.list_exceptions_by_status(session, "REQUESTED", limit)
            visible: list[ExceptionOut] = []
            for row in rows:
                try:
                    gs_service.get_visible_goods_slip(session, user, perms, row["gs_id"])
                except (NotFound, PermissionDenied):
                    continue
                visible.append(_exc_out(row))
            return visible

    # ---------------------------------------------------------------- commands ---------------
    def start(
        self, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID
    ) -> UnboxingStateOut:
        with self._uow.transaction(user.id) as session:
            gs = self._lock_for_step(session, user, perms, gs_id)
            if gs["status"] == "GATE_CREATED":
                gs_service.change_status_within_step(
                    session,
                    gs_id=gs_id,
                    from_status="GATE_CREATED",
                    to_status="UNBOXING",
                    step_code=UNBOX_STEP,
                    reason="Step-2 unboxing started",
                    by=user.id,
                )
            elif gs["status"] != "UNBOXING":
                raise Conflict(
                    "Unboxing can only start for a GS at the gate (GATE_CREATED)",
                    code="GS_NOT_AT_GATE",
                    details={"status": gs["status"]},
                )
            view = gs_service.get_visible_goods_slip(session, user, perms, gs_id)
            return self._state(session, user, perms, view)

    def classify(
        self, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID, payload: DocumentIn
    ) -> DocumentOut:
        with self._uow.transaction(user.id) as session:
            self._lock_unboxing(session, user, perms, gs_id)
            att = attachments.get_attachment(session, payload.attachment_id)
            if not att or att["gs_id"] != gs_id:
                raise NotFound("Document photo not found on this GS")
            if att["kind"] != "DOC_PHOTO" or att["status"] != "CONFIRMED":
                raise ValidationFailed(
                    "Only a confirmed document photo can be classified (DD r16)",
                    code="NOT_A_DOCUMENT_PHOTO",
                    details={"attachment_id": [f"{att['kind']} / {att['status']}"]},
                )
            if repo.document_for_attachment(session, payload.attachment_id):
                raise Conflict(
                    "This photo is already classified; edit the existing classification",
                    code="DOCUMENT_ALREADY_CLASSIFIED",
                )
            form = repo.get_published_form(session, FORM_CODE)
            if not form or not form.get("snapshot"):
                raise NotFound(f"No published {FORM_CODE} form", code="FORM_NOT_PUBLISHED")
            columns, _values, labels = resolve_document(dict(form["snapshot"]), payload.values)
            doc_id = repo.insert_document(
                session,
                gs_id=gs_id,
                attachment_id=payload.attachment_id,
                columns=columns,
                form_version_id=form["id"],
                labels_snapshot=labels,
                by=user.id,
            )
            row = repo.get_document(session, doc_id)
            if not row:
                raise NotFound("Document could not be loaded after classification")
            return _doc_out(row)

    def update_classification(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        doc_id: UUID,
        payload: DocumentPatchIn,
    ) -> DocumentOut:
        with self._uow.transaction(user.id) as session:
            self._lock_unboxing(session, user, perms, gs_id)
            doc = repo.get_document(session, doc_id, for_update=True)
            if not doc or doc["gs_id"] != gs_id:
                raise NotFound("Document classification not found on this GS")
            # G-18: re-validate against the form version the document was classified under.
            snapshot = (
                repo.get_form_snapshot(session, doc["form_version_id"])
                if doc["form_version_id"]
                else None
            )
            if not snapshot:
                raise NotFound("Form version for this document not found")
            columns, _values, labels = resolve_document(snapshot, payload.values)
            repo.update_document(
                session, doc_id, columns=columns, labels_snapshot=labels, by=user.id
            )
            row = repo.get_document(session, doc_id)
            if not row:
                raise NotFound("Document could not be loaded after the update")
            return _doc_out(row)

    def request_exception(
        self, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID, payload: ExceptionIn
    ) -> ExceptionOut:
        remark = payload.remark.strip()
        if not remark:
            raise ValidationFailed(
                "A remark is required",
                code="FORM_VALIDATION_FAILED",
                details={"remark": ["Required"]},
            )
        with self._uow.transaction(user.id) as session:
            gs = self._lock_unboxing(session, user, perms, gs_id)
            if not gs["missing_documentation"]:
                raise Conflict(
                    "A Missing Document Exception applies only to a GS flagged "
                    "'No Document Attached' at the gate (DEC-03)",
                    code="NOT_MISSING_DOCUMENTATION",
                )
            att = attachments.get_attachment(session, payload.parcel_attachment_id)
            if (
                not att
                or att["gs_id"] != gs_id
                or att["kind"] != "PARCEL_PHOTO"
                or att["status"] != "CONFIRMED"
            ):
                raise ValidationFailed(
                    "Attach a confirmed photo of the parcel label / outer box first (DEC-03)",
                    code="PARCEL_PHOTO_REQUIRED",
                    details={"parcel_attachment_id": ["Not a confirmed parcel photo of this GS"]},
                )
            if repo.live_exception_id(session, gs_id):
                raise Conflict(
                    "A Missing Document Exception is already pending or approved for this GS",
                    code="EXCEPTION_EXISTS",
                )
            exc_id = repo.insert_exception(
                session,
                gs_id=gs_id,
                parcel_attachment_id=payload.parcel_attachment_id,
                remark=remark,
                by=user.id,
            )
            notifications.publish(
                session,
                "MISSING_DOC_EXCEPTION_REQUESTED",
                role_codes=EXCEPTION_APPROVER_ROLES,
                notification_type="MISSING_DOC_EXCEPTION_REQUESTED",
                title=f"{gs['gs_no']}: Missing Document Exception requested",
                body=f"{user.full_name}: {remark}",
                entity_type=ENTITY_TYPE,
                entity_id=gs_id,
                gs_id=gs_id,
                priority="HIGH",
            )
            row = repo.get_exception(session, exc_id)
            if not row:
                raise NotFound("Exception could not be loaded after creation")
            return _exc_out(row)

    def decide_exception(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        exc_id: UUID,
        payload: ExceptionDecisionIn,
    ) -> ExceptionOut:
        remarks = (payload.remarks or "").strip() or None
        if payload.decision == "REJECT" and not remarks:
            raise ValidationFailed(
                "A reason is required to reject the exception",
                code="FORM_VALIDATION_FAILED",
                details={"remarks": ["Required when rejecting"]},
            )
        with self._uow.transaction(user.id) as session:
            gs = gs_service.lock_goods_slip(session, gs_id)
            gs_service.get_visible_goods_slip(session, user, perms, gs_id)
            if gs["status"] != "UNBOXING":
                raise Conflict(
                    "The exception can only be decided while the GS is UNBOXING",
                    code="GS_NOT_UNBOXING",
                    details={"status": gs["status"]},
                )
            exc = repo.get_exception(session, exc_id, for_update=True)
            if not exc or exc["gs_id"] != gs_id:
                raise NotFound("Missing Document Exception not found on this GS")
            if exc["status"] != "REQUESTED":
                raise Conflict(
                    f"The exception was already {exc['status'].lower()}",
                    code="EXCEPTION_ALREADY_DECIDED",
                )
            status = "APPROVED" if payload.decision == "APPROVE" else "REJECTED"
            repo.decide_exception(session, exc_id, status=status, by=user.id, remarks=remarks)
            row = repo.get_exception(session, exc_id)
            if not row:
                raise NotFound("Exception could not be loaded after the decision")
            if exc["requested_by"]:
                notifications.publish(
                    session,
                    "MISSING_DOC_EXCEPTION_DECIDED",
                    user_ids=[exc["requested_by"]],
                    notification_type=f"MISSING_DOC_EXCEPTION_{status}",
                    title=f"{gs['gs_no']}: Missing Document Exception {status.lower()}",
                    body=remarks,
                    entity_type=ENTITY_TYPE,
                    entity_id=gs_id,
                    gs_id=gs_id,
                    priority="NORMAL" if status == "APPROVED" else "HIGH",
                )
            return _exc_out(row)

    def complete(self, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID) -> CompleteOut:
        with self._uow.transaction(user.id) as session:
            gs = self._lock_unboxing(session, user, perms, gs_id)
            checklist, ctx = self._checklist(session, gs)
            if checklist.missing:
                raise SystemGuardUnmet(
                    "G-02",
                    "Unboxing evidence is incomplete: "
                    + ", ".join(checklist.missing).replace("_", " ").lower(),
                    details={"missing": checklist.missing, "checklist": checklist.model_dump()},
                )
            gs_service.transition_gs(
                session,
                gs_id=gs_id,
                to_status="ITEMIZATION",
                step_code=ITEMIZE_STEP,
                user=gs_service.workflow_user(user),
                reason="Step-2 unboxing evidence complete (G-02)",
                context_overrides=ctx,
            )
            notified = self._alert_accounts(session, gs)
            view = gs_service.get_visible_goods_slip(session, user, perms, gs_id)
            tasks = gs_service.open_task_ids(session, gs_id)
        log.info("unboxing_completed", gs_id=str(gs_id), notified=notified)
        return CompleteOut(goods_slip=_gs_out(view), task_ids=tasks, notified_user_count=notified)

    # ---------------------------------------------------------------- Accounts queue ---------
    def accounts_queue(
        self, user: CurrentUser, params: PageParams, classification: str | None
    ) -> Page[QueueItem]:
        with self._uow.transaction(user.id) as session:
            rows, total = repo.accounts_queue(
                session, classification=classification, limit=params.page_size, offset=params.offset
            )
            docs = repo.unacknowledged_documents(session, [r["gs_id"] for r in rows])
        by_gs: dict[UUID, list[QueueDocument]] = {}
        for d in docs:
            labels = dict(d.get("labels_snapshot") or {})
            by_gs.setdefault(d["gs_id"], []).append(
                QueueDocument(
                    **{k: d[k] for k in QueueDocument.model_fields if k in d},
                    classification_label=_classification_label(labels, d["classification_code"]),
                )
            )
        return Page[QueueItem](
            items=[QueueItem(**r, documents=by_gs.get(r["gs_id"], [])) for r in rows],
            total=total,
            page=params.page,
            page_size=params.page_size,
        )

    def classification_options(self, user: CurrentUser) -> list[OptionOut]:
        """Labels for the queue filter come from the RECEIVED_DOC_CLASSIFICATION option set."""
        with self._uow.transaction(user.id) as session:
            return [OptionOut(**o) for o in repo.option_items(session, CLASSIFICATION_SET)]

    def acknowledge(self, user: CurrentUser, gs_id: UUID) -> AcknowledgeOut:
        with self._uow.transaction(user.id) as session:
            gs = gs_service.lock_goods_slip(session, gs_id)
            if gs["status"] in ("GATE_CREATED", "UNBOXING", "CANCELLED"):
                raise Conflict(
                    "Documents can be acknowledged once unboxing is complete",
                    code="GS_NOT_UNBOXED",
                    details={"status": gs["status"]},
                )
            count = repo.acknowledge_documents(session, gs_id, by=user.id)
            if count == 0:
                raise Conflict(
                    "No unacknowledged documents on this GS", code="NOTHING_TO_ACKNOWLEDGE"
                )
        return AcknowledgeOut(gs_id=gs_id, acknowledged=count)

    # ---------------------------------------------------------------- internals --------------
    # ---------------------------------------------------------------- carton documents -------
    def add_carton_document(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: CartonDocumentIn,
        idem: IdempotencyKey,
    ) -> IdempotentResult:
        """AMD-04 / AMD-05: a document row found in a carton (Idempotency-Key, G-16)."""
        with self._uow.transaction(user.id) as session:
            return run_idempotent(
                session,
                idem,
                user.id,
                lambda: (201, self._add_carton_document(session, user, perms, gs_id, payload)),
            )

    def _add_carton_document(
        self,
        session: Session,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        payload: CartonDocumentIn,
    ) -> GateDocumentOut:
        gs = self._lock_carton_documents(session, user, perms, gs_id)
        row = gs_service.validate_document_row(session, GateDocumentIn(**payload.model_dump()))
        doc_id = gs_service.add_document_row(
            session, gs_id, row, source_step=gs_service.CARTON_DOC_STEP
        )
        gs_service.alert_accounts_for_documents(
            session,
            gs_id=gs_id,
            gs_no=gs["gs_no"],
            party_name=self._party_name(session, user, perms, gs_id),
            doc_ids=[doc_id],
        )
        log.info("carton_document_added", gs_id=str(gs_id), doc_type=row["doc_type_code"])
        return self._doc_row_out(session, gs_id, doc_id)

    def update_carton_document(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        doc_id: UUID,
        payload: CartonDocumentIn,
    ) -> GateDocumentOut:
        with self._uow.transaction(user.id) as session:
            gs = self._lock_carton_documents(session, user, perms, gs_id)
            doc = self._carton_row(session, gs_id, doc_id)
            row = gs_service.validate_document_row(session, GateDocumentIn(**payload.model_dump()))
            if gs_service.update_document_row(session, doc, row):
                gs_service.alert_accounts_for_documents(
                    session,
                    gs_id=gs_id,
                    gs_no=gs["gs_no"],
                    party_name=self._party_name(session, user, perms, gs_id),
                    doc_ids=[doc_id],
                )
            return self._doc_row_out(session, gs_id, doc_id)

    def delete_carton_document(
        self, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID, doc_id: UUID
    ) -> None:
        with self._uow.transaction(user.id) as session:
            self._lock_carton_documents(session, user, perms, gs_id)
            self._carton_row(session, gs_id, doc_id)
            gs_service.set_audit_reason(session, "Carton-opening document row removed")
            gs_service.delete_document_row(session, doc_id)
            gs_service.set_audit_reason(session, None)

    def _lock_carton_documents(
        self, session: Session, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID
    ) -> dict[str, Any]:
        gs = self._lock_unboxing(session, user, perms, gs_id)
        if gs["missing_documentation"]:
            # DEC-03: "no document" is resolved through the Missing Document Exception path.
            raise Conflict(
                "This goods slip is flagged 'no document'; use the missing-document exception",
                code="GS_NO_DOCUMENT",
            )
        return gs

    def _carton_row(self, session: Session, gs_id: UUID, doc_id: UUID) -> dict[str, Any]:
        doc = gs_service.get_document_row(session, gs_id, doc_id)
        if doc["source_step"] != gs_service.CARTON_DOC_STEP:
            raise Conflict(
                "Gate document rows are corrected through the gate edit, not at carton opening",
                code="NOT_A_CARTON_DOCUMENT",
            )
        return doc

    def _party_name(
        self, session: Session, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID
    ) -> str | None:
        view = gs_service.get_visible_goods_slip(session, user, perms, gs_id)
        name = view.get("party_name")
        return str(name) if name else None

    def _doc_row_out(self, session: Session, gs_id: UUID, doc_id: UUID) -> GateDocumentOut:
        doc = next((d for d in gs_service.documents_out(session, gs_id) if d.id == doc_id), None)
        if doc is None:
            raise NotFound("Document could not be loaded after saving")
        return doc

    def _lock_for_step(
        self, session: Session, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID
    ) -> dict[str, Any]:
        gs = gs_service.lock_goods_slip(session, gs_id)
        gs_service.get_visible_goods_slip(session, user, perms, gs_id)
        assert_step_actor(session, user, UNBOX_STEP, "PERFORM")
        return gs

    def _lock_unboxing(
        self, session: Session, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID
    ) -> dict[str, Any]:
        gs = self._lock_for_step(session, user, perms, gs_id)
        if gs["status"] != "UNBOXING":
            raise Conflict(
                "Start unboxing first (the GS must be UNBOXING)",
                code="GS_NOT_UNBOXING",
                details={"status": gs["status"]},
            )
        return gs

    def _checklist(self, session: Session, gs: dict[str, Any]) -> tuple[Checklist, dict[str, Any]]:
        counts = attachments.evidence_counts(session, gs["id"])
        # G-02 / AMD-03 (was Requirement B per box): one confirmed video per carton
        # (1..carton_count); a single-carton GS accepts a video without a carton number. The DB
        # trigger rms_private.goods_slips_g02_guard enforces the same rule.
        per_box = True
        cartons = int(gs["carton_count"])
        have = {int(b) for b in counts["video_boxes"] or []}
        if cartons == 1 and int(counts["video_count"]) > 0 and 1 not in have:
            have.add(1)
        boxes_missing = [b for b in range(1, cartons + 1) if b not in have]
        approved = repo.has_approved_exception(session, gs["id"])
        ctx: dict[str, Any] = {
            "video_count": int(counts["video_count"]),
            "doc_photo_count": int(counts["doc_photo_count"]),
            "classified_doc_photo_count": int(counts["classified_doc_photo_count"]),
            "missing_documentation": bool(gs["missing_documentation"]),
            "approved_exception": approved,
            "boxes_missing_video": boxes_missing,
        }
        missing = g02_missing_evidence(ctx)
        doc_photos = ctx["doc_photo_count"]
        classified = ctx["classified_doc_photo_count"]
        missing_doc = ctx["missing_documentation"]
        checklist = Checklist(
            video_ok=ctx["video_count"] > 0 and not boxes_missing,
            documents_ok=(approved if missing_doc else doc_photos > 0),
            classified_ok=classified == doc_photos and (missing_doc or classified > 0),
            video_count=ctx["video_count"],
            doc_photo_count=doc_photos,
            classified_doc_photo_count=classified,
            parcel_photo_count=int(counts["parcel_photo_count"]),
            missing_documentation=missing_doc,
            exception_approved=approved,
            video_per_box_required=per_box,
            carton_count=cartons,
            cartons_with_video=cartons - len(boxes_missing),
            boxes_missing_video=boxes_missing,
            missing=missing,
            ready=not missing,
        )
        return checklist, ctx

    def _state(
        self,
        session: Session,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs: dict[str, Any],
    ) -> UnboxingStateOut:
        form = repo.get_published_form(session, FORM_CODE)
        if not form or not form.get("snapshot"):
            raise NotFound(f"No published {FORM_CODE} form", code="FORM_NOT_PUBLISHED")
        checklist, _ctx = self._checklist(session, gs)
        perform = UNBOX_STEP in step_codes_for(session, user, "PERFORM")
        limits = UploadLimits(
            max_video_bytes=_int(
                repo.get_setting(session, SIZE_SETTING_FOR_KIND["UNBOXING_VIDEO"])
            ),
            max_document_bytes=_int(repo.get_setting(session, SIZE_SETTING_FOR_KIND["DOC_PHOTO"])),
            resumable_threshold_bytes=_int(
                repo.get_setting(session, "upload_resumable_threshold_bytes")
            ),
        )
        return UnboxingStateOut(
            goods_slip=_gs_out(gs),
            checklist=checklist,
            attachments=[
                attachments.to_out(a) for a in attachments.attachments_for_gs(session, gs["id"])
            ],
            documents=[_doc_out(d) for d in repo.list_documents(session, gs["id"])],
            exceptions=[_exc_out(e) for e in repo.list_exceptions(session, gs["id"])],
            form_version_id=form["id"],
            form_snapshot=classification_snapshot(dict(form["snapshot"])),
            limits=limits,
            permissions=UnboxingPermissions(
                can_perform=perform and perms.allows("unboxing", "create"),
                can_approve_exception=perms.allows("unboxing", "approve"),
            ),
            gate_documents=gs_service.documents_out(session, gs["id"]),
            document_types=gs_service.document_types_out(session),
        )

    def _alert_accounts(self, session: Session, gs: dict[str, Any]) -> int:
        """DEC-05: in-app alert to Accounts with the document types (setting
        `accounts_alert_on_doc_classified`); the queue lists the GS regardless."""
        if repo.get_setting(session, "accounts_alert_on_doc_classified") is False:
            return 0
        docs = repo.list_documents(session, gs["id"])
        counts: dict[str, int] = {}
        for d in docs:
            label = _classification_label(
                dict(d["labels_snapshot"] or {}), d["classification_code"]
            )
            counts[label] = counts.get(label, 0) + 1
        types = ", ".join(f"{label} x{n}" if n > 1 else label for label, n in counts.items())
        if gs["missing_documentation"]:
            body = "No documents received; Missing Document Exception approved (DEC-03)."
            if types:
                body = f"{types}. {body}"
        else:
            body = types
        return notifications.publish(
            session,
            "EVIDENCE_COMPLETED",
            role_codes=ACCOUNTS_ALERT_ROLES,
            notification_type="GS_DOCUMENTS_RECEIVED",
            title=f"Documents received for GS {gs['gs_no']}",
            body=body or None,
            entity_type=ENTITY_TYPE,
            entity_id=gs["id"],
            gs_id=gs["id"],
            priority="HIGH" if gs["missing_documentation"] else "NORMAL",
        )


def _int(value: Any) -> int:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0
