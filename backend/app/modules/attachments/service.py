"""Step-2 evidence uploads (master plan §8.8, §9.6, DD r11 / r16, BR-04, G-02, DEC-04, P2-03).

* Private buckets only; the backend issues a signed upload (single PUT) or a signed resumable TUS
  upload for videos above `upload_resumable_threshold_bytes` (DEC-04: large mobile uploads).
* Object paths are generated here (`gs/{gs_id}/{kind}/{uuid}.{ext}`) and are never taken from
  the client; confirmation re-reads the object from Storage and checks path, size and MIME.
* Downloads: per-GS view permission, short-lived signed URL (TTL from `signed_url_ttl_seconds`),
  every issuance audited (G-17 'ACCESS').
* Uploads / confirmations only while the GS is UNBOXING, by an S1_UNBOX performer (DB trigger
  `attachments_guard` mirrors the status rule; confirmed evidence is never deleted after Step-2).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import structlog
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import UnitOfWork
from app.core.errors import (
    Conflict,
    NotFound,
    PermissionDenied,
    ServiceUnavailable,
    ValidationFailed,
)
from app.core.permissions import EffectivePermissions, assert_step_actor
from app.core.security import CurrentUser
from app.modules.attachments import repository as repo
from app.modules.attachments.allowlist import (
    GATE_DOC_KIND,
    PROOF_KIND,
    SIZE_SETTING_FOR_KIND,
    UPLOAD_KINDS,
    FileRejectedError,
    check_file,
    check_size,
    normalise_mime,
)
from app.modules.attachments.schemas import (
    AttachmentOut,
    ConfirmIn,
    DownloadUrlOut,
    GateDocFileUploadIn,
    ProofUploadIn,
    SignedPutUpload,
    TusUpload,
    UploadUrlIn,
    UploadUrlOut,
)
from app.modules.goods_slips import service as gs_service
from app.shared.storage import Bucket, StorageService, build_object_path

log = structlog.get_logger("rms.attachments")

UNBOX_STEP = "S1_UNBOX"
UNBOXING = "UNBOXING"
# P3-07 / DEC-25: notification proofs are uploaded by the S6_NOTIFY performer (Accounts) while the
# GS is in its commercial stages (the attachments_guard trigger only restricts Step-2 kinds).
NOTIFY_STEP = "S6_NOTIFY"
PROOF_STATUSES = frozenset({"IN_PROCESS", "COMMERCIAL_RESOLUTION", "AWAITING_NOTIFICATION"})
# AMD-04: gate document files are uploaded by the S1_GATE performer right after the GS is created
# (still accepted if unboxing already started); the attachments_guard trigger mirrors this.
GATE_STEP = "S1_GATE"
GATE_DOC_STATUSES = frozenset({"GATE_CREATED", "UNBOXING"})
# Change plan Phase 3 (AMD-04): rows added at Carton Opening (stage S1_UNBOX) take their files from
# the S1_UNBOX performer while the GS is UNBOXING; the attachments_guard trigger mirrors this.
CARTON_DOC_STEP = "S1_UNBOX"


def gate_doc_rules(stage: str | None) -> tuple[str, frozenset[str], frozenset[str]]:
    """(performing step, statuses to add / confirm files, statuses to delete confirmed files)
    for a GATE_DOC file, by the stage of its document row."""
    if stage == CARTON_DOC_STEP:
        return CARTON_DOC_STEP, frozenset({UNBOXING}), frozenset({UNBOXING})
    return GATE_STEP, GATE_DOC_STATUSES, frozenset({"GATE_CREATED"})


# Supabase resumable uploads require 6 MB chunks (except the last one).
TUS_CHUNK_SIZE = 6 * 1024 * 1024
DEFAULT_RESUMABLE_THRESHOLD = 6 * 1024 * 1024
DEFAULT_PENDING_RETENTION_HOURS = 24
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def _int_setting(session: Session, key: str, default: int) -> int:
    value = repo.get_setting(session, key)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return default
    return int(value)


def signed_url_ttl(session: Session) -> int:
    """`signed_url_ttl_seconds` (system setting) with the env value as fallback."""
    return _int_setting(session, "signed_url_ttl_seconds", get_settings().signed_url_ttl_seconds)


def expected_path_pattern(gs_id: UUID, kind: str) -> re.Pattern[str]:
    return re.compile(rf"^gs/{gs_id}/{kind.lower()}/{_UUID}\.[a-z0-9]{{1,8}}$")


def to_out(row: dict[str, Any]) -> AttachmentOut:
    return AttachmentOut(**{k: row[k] for k in AttachmentOut.model_fields})


def _rejected(exc: FileRejectedError) -> ValidationFailed:
    return ValidationFailed(
        exc.message, code="FILE_NOT_ALLOWED", details={exc.field: [exc.message]}
    )


# --- service-to-service API (used by the unboxing module) -------------------------------------
def attachments_for_gs(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    return repo.list_for_gs(session, gs_id, list(UPLOAD_KINDS))


def get_attachment(session: Session, attachment_id: UUID) -> dict[str, Any] | None:
    return repo.get_attachment(session, attachment_id)


def evidence_counts(session: Session, gs_id: UUID) -> dict[str, Any]:
    return repo.evidence_counts(session, gs_id)


class AttachmentService:
    def __init__(self, uow: UnitOfWork, storage: StorageService) -> None:
        self._uow = uow
        self._storage = storage

    # ---------------------------------------------------------------- upload -----------------
    def request_upload(
        self, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID, payload: UploadUrlIn
    ) -> UploadUrlOut:
        with self._uow.transaction(user.id) as session:
            gs = gs_service.lock_goods_slip(session, gs_id)
            gs_service.get_visible_goods_slip(session, user, perms, gs_id)
            assert_step_actor(session, user, UNBOX_STEP, "PERFORM")
            if gs["status"] != UNBOXING:
                raise Conflict(
                    "Evidence can only be uploaded while the GS is being unboxed",
                    code="GS_NOT_UNBOXING",
                    details={"status": gs["status"]},
                )
            # AMD-03: box_no carries the carton number (1..carton_count).
            if payload.box_no is not None and payload.box_no > int(gs["carton_count"]):
                raise ValidationFailed(
                    f"Carton {payload.box_no} does not exist "
                    f"(the GS has {gs['carton_count']} cartons)",
                    code="FILE_NOT_ALLOWED",
                    details={"box_no": ["Carton number exceeds the GS carton count"]},
                )
            return self._issue_upload(
                session,
                user,
                gs_id,
                kind=payload.kind,
                mime_type=payload.mime_type,
                size_bytes=payload.size_bytes,
                file_name=payload.file_name,
                box_no=payload.box_no,
            )

    def request_proof_upload(
        self, user: CurrentUser, perms: EffectivePermissions, gs_id: UUID, payload: ProofUploadIn
    ) -> UploadUrlOut:
        """DEC-25: signed upload for a party-notification proof (S6_NOTIFY PERFORM)."""
        with self._uow.transaction(user.id) as session:
            gs = gs_service.lock_goods_slip(session, gs_id)
            gs_service.get_visible_goods_slip(session, user, perms, gs_id)
            assert_step_actor(session, user, NOTIFY_STEP, "PERFORM")
            if gs["status"] not in PROOF_STATUSES:
                raise Conflict(
                    "Notification proof can only be uploaded while the GS awaits closure",
                    code="GS_NOT_IN_COMMERCIAL_STAGE",
                    details={"status": gs["status"]},
                )
            return self._issue_upload(
                session,
                user,
                gs_id,
                kind=PROOF_KIND,
                mime_type=payload.mime_type,
                size_bytes=payload.size_bytes,
                file_name=payload.file_name,
                box_no=None,
            )

    def request_gate_doc_upload(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        gs_id: UUID,
        document_id: UUID,
        payload: GateDocFileUploadIn,
    ) -> UploadUrlOut:
        """AMD-04: signed upload for one file of a document row (gate row: S1_GATE performer;
        carton-opening row: S1_UNBOX performer while UNBOXING)."""
        with self._uow.transaction(user.id) as session:
            gs = gs_service.lock_goods_slip(session, gs_id)
            gs_service.get_visible_goods_slip(session, user, perms, gs_id)
            doc = repo.get_gate_document(session, gs_id, document_id)
            if doc is None:
                raise NotFound("Gate document not found on this goods slip")
            step, add_statuses, _ = gate_doc_rules(doc["source_step"])
            assert_step_actor(session, user, step, "PERFORM")
            if gs["status"] not in add_statuses:
                raise Conflict(
                    "Files of this document can no longer be added",
                    code="GS_NOT_AT_GATE" if step == GATE_STEP else "GS_NOT_UNBOXING",
                    details={"status": gs["status"]},
                )
            return self._issue_upload(
                session,
                user,
                gs_id,
                kind=GATE_DOC_KIND,
                mime_type=payload.mime_type,
                size_bytes=payload.size_bytes,
                file_name=payload.file_name,
                box_no=None,
                gate_document_id=document_id,
            )

    def _issue_upload(
        self,
        session: Session,
        user: CurrentUser,
        gs_id: UUID,
        *,
        kind: str,
        mime_type: str,
        size_bytes: int,
        file_name: str | None,
        box_no: int | None,
        gate_document_id: UUID | None = None,
    ) -> UploadUrlOut:
        """Validate the file, create the PENDING_UPLOAD row (server path) and sign the upload."""
        try:
            allowed = check_file(kind, mime_type, file_name)
            max_bytes = _int_setting(session, SIZE_SETTING_FOR_KIND[kind], 1)
            check_size(size_bytes, max_bytes)
        except FileRejectedError as exc:
            raise _rejected(exc) from exc
        path = build_object_path(gs_id, allowed.kind.lower(), allowed.ext)
        attachment_id = repo.insert_attachment(
            session,
            gs_id=gs_id,
            kind=allowed.kind,
            bucket=allowed.bucket.value,
            object_path=path,
            mime_type=allowed.mime_type,
            size_bytes=size_bytes,
            box_no=box_no,
            uploaded_by=user.id,
            gate_document_id=gate_document_id,
        )
        threshold = _int_setting(
            session, "upload_resumable_threshold_bytes", DEFAULT_RESUMABLE_THRESHOLD
        )
        upload: SignedPutUpload | TusUpload
        if allowed.bucket is Bucket.VIDEOS and size_bytes > threshold:
            tus = self._storage.create_resumable_upload(allowed.bucket, path)
            upload = TusUpload(
                endpoint=tus.endpoint,
                token=tus.token,
                bucket=tus.bucket,
                object_path=path,
                content_type=allowed.mime_type,
                chunk_size=TUS_CHUNK_SIZE,
            )
        else:
            signed = self._storage.create_signed_upload_url(allowed.bucket, path)
            upload = SignedPutUpload(url=signed.signed_url, bucket=signed.bucket, object_path=path)
        row = repo.get_attachment(session, attachment_id)
        if not row:
            raise NotFound("Attachment could not be loaded after creation")
        log.info(
            "upload_url_issued",
            attachment_id=str(attachment_id),
            gs_id=str(gs_id),
            kind=allowed.kind,
            method=upload.method,
            size_bytes=size_bytes,
        )
        return UploadUrlOut(attachment=to_out(row), upload=upload)

    # ---------------------------------------------------------------- confirm ----------------
    def confirm(
        self,
        user: CurrentUser,
        perms: EffectivePermissions,
        attachment_id: UUID,
        payload: ConfirmIn,
    ) -> AttachmentOut:
        mismatch: ValidationFailed | None = None
        remove_path: tuple[Bucket, str] | None = None
        with self._uow.transaction(user.id) as session:
            att = self._load(session, attachment_id)
            gs = gs_service.lock_goods_slip(session, att["gs_id"])
            gs_service.get_visible_goods_slip(session, user, perms, att["gs_id"])
            is_proof = att["kind"] == PROOF_KIND
            is_gate_doc = att["kind"] == GATE_DOC_KIND
            doc_step, doc_add, _ = gate_doc_rules(self._doc_stage(session, att))
            step = NOTIFY_STEP if is_proof else doc_step if is_gate_doc else UNBOX_STEP
            assert_step_actor(session, user, step, "PERFORM")
            att = self._load(session, attachment_id, for_update=True)
            if att["status"] == "CONFIRMED":
                return to_out(att)  # repeat confirmation: same result
            if att["status"] != "PENDING_UPLOAD":
                raise Conflict("This upload was rejected", code="ATTACHMENT_REJECTED")
            if is_proof and gs["status"] not in PROOF_STATUSES:
                raise Conflict(
                    "Notification proof can only be confirmed while the GS awaits closure",
                    code="GS_NOT_IN_COMMERCIAL_STAGE",
                    details={"status": gs["status"]},
                )
            if is_gate_doc and gs["status"] not in doc_add:
                raise Conflict(
                    "Files of this document can no longer be confirmed",
                    code="GS_NOT_AT_GATE" if doc_step == GATE_STEP else "GS_NOT_UNBOXING",
                    details={"status": gs["status"]},
                )
            if not is_proof and not is_gate_doc and gs["status"] != UNBOXING:
                raise Conflict(
                    "Evidence can only be confirmed while the GS is being unboxed",
                    code="GS_NOT_UNBOXING",
                    details={"status": gs["status"]},
                )
            path: str = att["object_path"]
            bucket = Bucket(att["bucket"])
            if payload.object_path is not None and payload.object_path.strip().lstrip("/") not in (
                path,
                f"{bucket.value}/{path}",
            ):
                raise ValidationFailed(
                    "The uploaded object is not at the expected path",
                    code="OBJECT_PATH_MISMATCH",
                    details={"object_path": ["Does not match the server-generated path"]},
                )
            if not expected_path_pattern(att["gs_id"], att["kind"]).fullmatch(path):
                raise ValidationFailed(
                    "The attachment path is outside gs/{gs_id}/{kind}/",
                    code="OBJECT_PATH_MISMATCH",
                )
            info = self._storage.object_info(bucket, path)
            if not info.exists:
                raise Conflict(
                    "The file has not been uploaded yet (or the upload is incomplete)",
                    code="OBJECT_NOT_UPLOADED",
                )
            problems: dict[str, list[str]] = {}
            if info.name is not None and info.name != path:
                problems["object_path"] = ["Stored object name differs from the expected path"]
            if info.bucket is not None and info.bucket != bucket.value:
                problems["bucket"] = ["Stored object is in a different bucket"]
            if info.size is None or info.size != int(att["size_bytes"]):
                problems["size_bytes"] = [
                    f"Declared {att['size_bytes']} bytes, uploaded {info.size} bytes"
                ]
            if normalise_mime(info.content_type or "") != att["mime_type"]:
                problems["mime_type"] = [
                    f"Declared {att['mime_type']}, uploaded {info.content_type or 'unknown'}"
                ]
            if problems:
                # The row is kept as REJECTED (audited) and the object removed after commit.
                repo.mark_rejected(session, attachment_id)
                remove_path = (bucket, path)
                mismatch = ValidationFailed(
                    "The uploaded file does not match what was declared",
                    code="UPLOAD_MISMATCH",
                    details=problems,
                )
            else:
                repo.mark_confirmed(
                    session, attachment_id, by=user.id, size_bytes=int(info.size or 0)
                )
                confirmed = self._load(session, attachment_id)
        if mismatch is not None:
            if remove_path:
                self._remove_object(*remove_path, attachment_id=attachment_id)
            log.info("upload_rejected", attachment_id=str(attachment_id), problems=list(problems))
            raise mismatch
        log.info("upload_confirmed", attachment_id=str(attachment_id), kind=att["kind"])
        return to_out(confirmed)

    # ---------------------------------------------------------------- download ---------------
    def download_url(
        self, user: CurrentUser, perms: EffectivePermissions, attachment_id: UUID
    ) -> DownloadUrlOut:
        with self._uow.transaction(user.id) as session:
            att = self._load(session, attachment_id)
            gs_service.get_visible_goods_slip(session, user, perms, att["gs_id"])
            if att["status"] != "CONFIRMED":
                raise Conflict("The file is not confirmed yet", code="ATTACHMENT_NOT_CONFIRMED")
            ttl = signed_url_ttl(session)
            url = self._storage.create_signed_url(Bucket(att["bucket"]), att["object_path"], ttl)
            expires_at = datetime.now(UTC) + timedelta(seconds=ttl)
            repo.insert_access_audit(
                session,
                attachment_id=attachment_id,
                details={
                    "event": "DOWNLOAD_URL_ISSUED",
                    "gs_id": att["gs_id"],
                    "kind": att["kind"],
                    "ttl_seconds": ttl,
                    "expires_at": expires_at.isoformat(),
                },
            )
        # The URL embeds a token: it is returned to the caller but never logged.
        log.info(
            "signed_url_issued",
            attachment_id=str(attachment_id),
            gs_id=str(att["gs_id"]),
            ttl_seconds=ttl,
        )
        return DownloadUrlOut(
            url=url, expires_in=ttl, expires_at=expires_at, mime_type=att["mime_type"]
        )

    # ---------------------------------------------------------------- delete -----------------
    def delete(self, user: CurrentUser, perms: EffectivePermissions, attachment_id: UUID) -> None:
        with self._uow.transaction(user.id) as session:
            att = self._load(session, attachment_id)
            gs = gs_service.lock_goods_slip(session, att["gs_id"])
            gs_service.get_visible_goods_slip(session, user, perms, att["gs_id"])
            att = self._load(session, attachment_id, for_update=True)
            own = att["uploaded_by"] == user.id
            doc_step, _, doc_delete = gate_doc_rules(self._doc_stage(session, att))
            if att["status"] == "CONFIRMED":
                if not own:
                    raise PermissionDenied(
                        "Only the uploader can delete a confirmed file", code="NOT_UPLOADER"
                    )
                if att["kind"] == GATE_DOC_KIND:
                    if gs["status"] not in doc_delete:
                        raise Conflict(
                            "A confirmed document file cannot be deleted at this stage",
                            code="GS_NOT_AT_GATE" if doc_step == GATE_STEP else "GS_NOT_UNBOXING",
                            details={"status": gs["status"]},
                        )
                elif gs["status"] != UNBOXING:
                    raise Conflict(
                        "Confirmed evidence cannot be deleted once the GS has left UNBOXING",
                        code="GS_NOT_UNBOXING",
                        details={"status": gs["status"]},
                    )
            elif not own:
                assert_step_actor(
                    session,
                    user,
                    doc_step if att["kind"] == GATE_DOC_KIND else UNBOX_STEP,
                    "PERFORM",
                )
            if repo.is_referenced_by_exception(session, attachment_id):
                raise Conflict(
                    "This parcel photo is part of a Missing Document Exception",
                    code="ATTACHMENT_IN_USE",
                )
            repo.set_audit_reason(
                session,
                "Gate document file removed at the gate"
                if att["kind"] == GATE_DOC_KIND
                else "Step-2 evidence deleted before unboxing completed",
            )
            repo.delete_attachment(session, attachment_id)
            repo.set_audit_reason(session, None)
        self._remove_object(Bucket(att["bucket"]), att["object_path"], attachment_id=attachment_id)
        log.info("attachment_deleted", attachment_id=str(attachment_id), kind=att["kind"])

    # ---------------------------------------------------------------- cleanup (worker) -------
    def cleanup_stale_pending(self, *, now: datetime | None = None, batch: int = 200) -> int:
        """Delete PENDING_UPLOAD rows older than `pending_upload_retention_hours` and their
        objects (worker job). Runs as the system (no acting user)."""
        removed = 0
        with self._uow.transaction(None) as session:
            hours = _int_setting(
                session, "pending_upload_retention_hours", DEFAULT_PENDING_RETENTION_HOURS
            )
            cutoff = (now or datetime.now(UTC)) - timedelta(hours=hours)
            stale = repo.list_stale_pending(session, cutoff, batch)
            repo.set_audit_reason(session, f"Unconfirmed upload older than {hours} h")
            for row in stale:
                repo.delete_attachment(session, row["id"])
            repo.set_audit_reason(session, None)
        for row in stale:
            if self._remove_object(
                Bucket(row["bucket"]), row["object_path"], attachment_id=row["id"]
            ):
                removed += 1
        if stale:
            log.info("pending_uploads_cleaned", rows=len(stale), objects_removed=removed)
        return len(stale)

    # ---------------------------------------------------------------- internals --------------
    def _doc_stage(self, session: Session, att: dict[str, Any]) -> str | None:
        """Stage (source_step) of the document row a GATE_DOC file belongs to."""
        if att["kind"] != GATE_DOC_KIND or att.get("gate_document_id") is None:
            return None
        doc = repo.get_gate_document(session, att["gs_id"], att["gate_document_id"])
        return str(doc["source_step"]) if doc else None

    def _load(
        self, session: Session, attachment_id: UUID, *, for_update: bool = False
    ) -> dict[str, Any]:
        att = repo.get_attachment(session, attachment_id, for_update=for_update)
        if not att:
            raise NotFound("Attachment not found")
        return att

    def _remove_object(self, bucket: Bucket, path: str, *, attachment_id: UUID) -> bool:
        """Best effort after the DB change committed; a failure is logged with context (the row
        is already gone or REJECTED, so the object is an orphan for manual cleanup)."""
        try:
            self._storage.delete(bucket, path)
        except (ServiceUnavailable, httpx.HTTPError) as exc:
            log.error(
                "storage_object_delete_failed",
                attachment_id=str(attachment_id),
                bucket=bucket.value,
                error=str(exc),
            )
            return False
        return True
