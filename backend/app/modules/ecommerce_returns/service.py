"""E-Commerce Returns: gate entry, media, lifecycle and platform tickets (DEC-73; user 2026-11-24).

Gate Entry with Return Type = E-Commerce records an E-Commerce Return (own table and number series
ECOM_RETURN; the offline goods slips are untouched). The lifecycle is enforced here AND by the DB
triggers of migration 20261124000100 (`rms_private.ecommerce_*_guard`):

* create  → DRAFT with the declared media (package-opening video mandatory, gallery/file only;
            optional images, combined size ≤ `ecommerce_images_max_total_bytes`). Files are uploaded
            to signed URLs (same buckets / storage service as the offline attachments) and confirmed
            one by one against storage.
* submit  → needs the CONFIRMED video and no file still uploading; routes on QC status:
            ISSUE_TO_CHECKING → IN_CHECKING (open; `_issue_to_checking` is the extension point)
            TICKET_RAISE      → PENDING_TICKET + ticket queued for the Ticket Handlers, SLA due =
                                queued + `ecommerce_ticket_sla_hours` (2 h, computed by the DB).
* ticket  → raise (TICKET_RAISED) → follow-ups → response REJECTED (remark) / CLAIM_RECEIVED
            (amount) / PENDING (stays open) → close with the portal resolution (DEC-76) →
            PENDING_UNBOXING (never while PENDING or with missing data).
* portal  → DEC-76: a return without a ticket (IN_CHECKING, "Portal Check Pending") gets the
            executive's portal resolution (Free Replacement / Refund + qty + short note) →
            PENDING_UNBOXING. The unboxing, store receipts and credit note follow in
            app/modules/ecommerce_settlement.
* void    → Super Admin / Management (ecommerce_returns.delete), reason, any time before it is
            unboxed (DEC-76) or CLOSED.

DEC-51: no ownership lock; any Ticket Handler may work any ticket (the raiser is recorded).
Commands run in one transaction and are idempotent on `Idempotency-Key` (G-16 pattern).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
import structlog
from sqlalchemy.orm import Session

from app.core.db import UnitOfWork
from app.core.errors import (
    Conflict,
    NotFound,
    ServiceUnavailable,
    ValidationFailed,
)
from app.core.idempotency import IdempotencyKey, IdempotentResult, run_idempotent
from app.core.security import CurrentUser
from app.modules.attachments.allowlist import FileRejectedError, check_size, normalise_mime
from app.modules.attachments.schemas import SignedPutUpload, TusUpload
from app.modules.attachments.service import (
    DEFAULT_RESUMABLE_THRESHOLD,
    TUS_CHUNK_SIZE,
    signed_url_ttl,
)
from app.modules.ecommerce_returns import repository as repo
from app.modules.ecommerce_returns.schemas import (
    ConfirmMediaIn,
    CreateOut,
    DownloadOut,
    EventOut,
    FollowUpIn,
    FormConfigOut,
    ImageRuleOut,
    MediaIn,
    MediaOut,
    MediaUploadOut,
    OptionOut,
    OrderMatchOut,
    PortalCheckQueueOut,
    PortalCheckRowOut,
    ProductLookupOut,
    ResolutionIn,
    ReturnCreateIn,
    ReturnListOut,
    ReturnOut,
    ReturnRowOut,
    TicketOut,
    TicketQueueOut,
    TicketResponseIn,
    TicketRowOut,
    VideoRuleOut,
    VoidIn,
)
from app.modules.ecommerce_settlement.service import EcommerceSettlementService
from app.shared.storage import Bucket, StorageService

log = structlog.get_logger(__name__)

# Option sets (labels are configuration; logic keys off the codes, CLAUDE.md rule e).
SET_RETURN_TYPE = "RETURN_TYPE"
SET_PLATFORM = "ECOM_PLATFORM"
SET_PRODUCT_TYPE = "ECOM_PRODUCT_TYPE"
SET_QC_ROUTING = "ECOM_QC_ROUTING"
SET_RESPONSE = "ECOM_TICKET_RESPONSE"
SET_STATUS = "ECOM_RETURN_STATUS"
SET_RESOLUTION = "ECOM_PORTAL_RESOLUTION"  # DEC-76

COMPANY_PRODUCT = "COMPANY_PRODUCT"
DIFFERENT_PRODUCT = "DIFFERENT_PRODUCT"
TICKET_RAISE = "TICKET_RAISE"
ISSUE_TO_CHECKING = "ISSUE_TO_CHECKING"
REJECTED = "REJECTED"
CLAIM_RECEIVED = "CLAIM_RECEIVED"
PENDING = "PENDING"
FINAL_STATUSES = frozenset({"CLOSED", "VOIDED"})
NOT_VOIDABLE = FINAL_STATUSES | {"UNBOXED"}  # DEC-76: unboxed pieces are in stock

VIDEO = "PACKAGE_VIDEO"
IMAGE = "IMAGE"
# Allow-list (mirrors the DB CHECK ecommerce_return_media_mime).
# DEC-73 Q1: the offline video formats.
VIDEO_TYPES: dict[str, tuple[str, ...]] = {"video/mp4": ("mp4",), "video/quicktime": ("mov", "qt")}
IMAGE_TYPES: dict[str, tuple[str, ...]] = {
    "image/jpeg": ("jpg", "jpeg"),
    "image/png": ("png",),
    "image/heic": ("heic",),
    "image/heif": ("heif", "heic"),
}
BUCKET_FOR = {VIDEO: Bucket.VIDEOS, IMAGE: Bucket.DOCUMENTS}

DEFAULT_VIDEO_MAX = 1024 * 1024 * 1024
DEFAULT_IMAGE_MAX = 25 * 1024 * 1024
DEFAULT_IMAGES_TOTAL = 50 * 1024 * 1024
DEFAULT_SLA_HOURS = 2
DEFAULT_ORDER_PATTERN = r"^[A-Za-z0-9-]{3,40}$"
DEFAULT_PENDING_RETENTION_HOURS = 24
LIST_LIMIT = 300

_PATH = re.compile(r"^ecom/[0-9a-f-]{36}/(package_video|image)/[0-9a-f-]{36}\.[a-z0-9]{1,8}$")


# --- helpers ------------------------------------------------------------------------------------
def _int_setting(session: Session, key: str, default: int) -> int:
    value = repo.get_setting(session, key)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return default
    return int(value)


def _order_pattern(session: Session) -> str:
    value = repo.get_setting(session, "ecommerce_order_id_pattern")
    if not isinstance(value, str) or not value:
        return DEFAULT_ORDER_PATTERN
    try:
        re.compile(value)
    except re.error:
        log.error("ecommerce_order_id_pattern_invalid", value=value)
        raise ServiceUnavailable(
            "System setting ecommerce_order_id_pattern is not a valid pattern",
            code="SETTING_INVALID",
            details={"key": "ecommerce_order_id_pattern"},
        ) from None
    return value


def _min_entry_date(session: Session, today: date) -> date | None:
    """DEC-73 Q4: back-dating is limited like the gate entry date (DEC-38,
    gate.max_backdate_days)."""
    value = repo.get_setting(session, "gate.max_backdate_days")
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        return None
    return today - timedelta(days=int(value))


def _labels(session: Session, set_code: str) -> dict[str, str]:
    return {o["code"]: o["label"] for o in repo.options(session, set_code)}


def _object_path(return_id: UUID, kind: str, ext: str) -> str:
    return f"ecom/{return_id}/{kind.lower()}/{uuid.uuid4()}.{ext}"


def _check_media(kind: str, media: MediaIn, max_bytes: int, field: str) -> tuple[str, str]:
    """Validate MIME (+ extension of the file name) and size; returns (mime, ext)."""
    allowed = VIDEO_TYPES if kind == VIDEO else IMAGE_TYPES
    mime = normalise_mime(media.mime_type)
    exts = allowed.get(mime)
    what = "The package opening video" if kind == VIDEO else "An image"
    if exts is None:
        raise FileRejectedError(
            field, f"{what} must be {', '.join(sorted(allowed))} (got {mime or 'unknown'})"
        )
    if media.file_name and media.file_name.strip():
        name = media.file_name.strip().lower()
        ext = name.rsplit(".", 1)[1] if "." in name else ""
        if ext not in exts:
            raise FileRejectedError(
                field,
                f"File extension .{ext or '?'} does not match {mime} "
                f"(expected .{', .'.join(exts)})",
            )
    try:
        check_size(media.size_bytes, max_bytes)
    except FileRejectedError as exc:
        raise FileRejectedError(field, f"{what}: {exc.message}") from None
    return mime, exts[0]


def _sla(ticket: dict[str, Any], now: datetime) -> tuple[str, int | None]:
    due: datetime = ticket["sla_due_at"]
    raised: datetime | None = ticket["raised_at"]
    if raised is not None:
        return ("RAISED_LATE" if raised > due else "RAISED_ON_TIME"), None
    minutes = int((due - now).total_seconds() // 60)
    return ("OVERDUE" if now > due else "ON_TIME"), minutes


def _ticket_out(row: dict[str, Any], now: datetime) -> TicketOut:
    state, minutes = _sla(row, now)
    return TicketOut(
        id=row["id"],
        sla_due_at=row["sla_due_at"],
        sla_state=state,  # type: ignore[arg-type]
        minutes_to_due=minutes,
        assigned_handler_id=row["assigned_handler_id"],
        assigned_handler_name=row["assigned_handler_name"],
        raised_at=row["raised_at"],
        response_code=row["response_code"],
        response_label=row["response_label"],
        rejection_remark=row["rejection_remark"],
        claim_amount=row["claim_amount"],
        responded_at=row["responded_at"],
        responded_by_name=row["responded_by_name"],
        closed_at=row["closed_at"],
        closed_by_name=row["closed_by_name"],
        follow_up_count=int(row["follow_up_count"] or 0),
        last_follow_up_at=row["last_follow_up_at"],
        next_follow_up_on=row["next_follow_up_on"],
    )


def _media_out(row: dict[str, Any]) -> MediaOut:
    return MediaOut(
        id=row["id"],
        kind=row["kind"],
        mime_type=row["mime_type"],
        size_bytes=int(row["size_bytes"]),
        file_name=row["file_name"],
        status=row["status"],
        confirmed_at=row["confirmed_at"],
    )


def _product_text(row: dict[str, Any]) -> str:
    if row["product_type_code"] == COMPANY_PRODUCT:
        return f"{row['product_name']} ({row['product_code']})"
    return str(row["different_product_desc"])


class EcommerceReturnService:
    def __init__(self, uow: UnitOfWork, storage: StorageService | None = None) -> None:
        self._uow = uow
        self._storage = storage

    @property
    def storage(self) -> StorageService:
        if self._storage is None:  # pragma: no cover - wiring error
            raise ServiceUnavailable("Storage is not configured", code="STORAGE_ERROR")
        return self._storage

    # ================================================================ reads ==================
    def form_config(self, actor: CurrentUser) -> FormConfigOut:
        with self._uow.transaction(actor.id) as session:
            today = repo.business_today(session)
            return FormConfigOut(
                return_types=[OptionOut(**o) for o in repo.options(session, SET_RETURN_TYPE)],
                platforms=[OptionOut(**o) for o in repo.options(session, SET_PLATFORM)],
                product_types=[OptionOut(**o) for o in repo.options(session, SET_PRODUCT_TYPE)],
                qc_routings=[OptionOut(**o) for o in repo.options(session, SET_QC_ROUTING)],
                business_today=today,
                min_entry_date=_min_entry_date(session, today),
                order_id_pattern=_order_pattern(session),
                video=VideoRuleOut(
                    mime_types=sorted(VIDEO_TYPES),
                    extensions=sorted({e for v in VIDEO_TYPES.values() for e in v}),
                    max_bytes=_int_setting(session, "upload_max_video_bytes", DEFAULT_VIDEO_MAX),
                ),
                images=ImageRuleOut(
                    mime_types=sorted(IMAGE_TYPES),
                    extensions=sorted({e for v in IMAGE_TYPES.values() for e in v}),
                    max_bytes_each=_int_setting(
                        session, "upload_max_document_bytes", DEFAULT_IMAGE_MAX
                    ),
                    max_total_bytes=_int_setting(
                        session, "ecommerce_images_max_total_bytes", DEFAULT_IMAGES_TOTAL
                    ),
                ),
                ticket_sla_hours=_int_setting(
                    session, "ecommerce_ticket_sla_hours", DEFAULT_SLA_HOURS
                ),
            )

    def products(self, actor: CurrentUser, q: str | None) -> list[ProductLookupOut]:
        with self._uow.transaction(actor.id) as session:
            rows = repo.search_products(session, (q or "").strip() or None, 30)
        return [ProductLookupOut(**r) for r in rows]

    def order_check(
        self, actor: CurrentUser, platform_code: str, order_id: str
    ) -> list[OrderMatchOut]:
        """DEC-73 Q2: repeats are allowed; the form warns with the earlier entries."""
        with self._uow.transaction(actor.id) as session:
            labels = _labels(session, SET_STATUS)
            rows = repo.returns_for_order(session, platform_code, order_id.strip())
        return [OrderMatchOut(**r, status_label=labels.get(r["status"], r["status"])) for r in rows]

    def get(self, actor: CurrentUser, return_id: UUID) -> ReturnOut:
        with self._uow.transaction(actor.id) as session:
            return self._return_out(session, return_id)

    def list(self, actor: CurrentUser, q: str | None, status: str | None) -> ReturnListOut:
        now = datetime.now(UTC)
        with self._uow.transaction(actor.id) as session:
            options = repo.options(session, SET_STATUS)
            labels = {o["code"]: o["label"] for o in options}
            rows = repo.list_returns(
                session, q=(q or "").strip() or None, status=status, limit=LIST_LIMIT
            )
            tickets = {
                t["return_id"]: t
                for t in repo.tickets_for_returns(session, [r["id"] for r in rows])
            }
        items = [
            ReturnRowOut(
                id=r["id"],
                return_no=r["return_no"],
                entry_date=r["entry_date"],
                platform_label=r["platform_label"],
                order_id=r["order_id"],
                product_text=_product_text(r),
                qty=r["qty"],
                qc_routing_code=r["qc_routing_code"],
                qc_routing_label=r["qc_routing_label"],
                status=r["status"],
                status_label=labels.get(r["status"], r["status"]),
                created_at=r["created_at"],
                ticket=_ticket_out(tickets[r["id"]], now) if r["id"] in tickets else None,
            )
            for r in rows
        ]
        return ReturnListOut(status_options=[OptionOut(**o) for o in options], rows=items)

    def ticket_queue(self, actor: CurrentUser, state: str) -> TicketQueueOut:
        now = datetime.now(UTC)
        with self._uow.transaction(actor.id) as session:
            labels = _labels(session, SET_STATUS)
            responses = [OptionOut(**o) for o in repo.options(session, SET_RESPONSE)]
            resolutions = [OptionOut(**o) for o in repo.options(session, SET_RESOLUTION)]
            rows = repo.ticket_queue(session, state=state, limit=LIST_LIMIT)
        return TicketQueueOut(
            response_options=responses,
            resolution_options=resolutions,
            rows=[
                TicketRowOut(
                    return_id=r["return_id"],
                    return_no=r["return_no"],
                    entry_date=r["entry_date"],
                    platform_label=r["platform_label"],
                    order_id=r["order_id"],
                    product_text=r["product_text"],
                    qty=r["qty"],
                    status=r["status"],
                    status_label=labels.get(r["status"], r["status"]),
                    ticket=_ticket_out(r, now),
                )
                for r in rows
            ],
        )

    def download_url(self, actor: CurrentUser, media_id: UUID) -> DownloadOut:
        with self._uow.transaction(actor.id) as session:
            media = repo.get_media(session, media_id)
            if not media:
                raise NotFound("File not found")
            if media["status"] != "CONFIRMED":
                raise Conflict("This file has not been uploaded", code="MEDIA_NOT_CONFIRMED")
            ttl = signed_url_ttl(session)
        url = self.storage.create_signed_url(Bucket(media["bucket"]), media["object_path"], ttl)
        return DownloadOut(url=url, expires_in=ttl, mime_type=media["mime_type"])

    # ================================================================ create =================
    def create(
        self, actor: CurrentUser, payload: ReturnCreateIn, idem: IdempotencyKey
    ) -> IdempotentResult:
        with self._uow.transaction(actor.id) as session:
            return run_idempotent(
                session,
                idem,
                actor.id,
                lambda: (201, self._create(session, actor, payload).model_dump(mode="json")),
            )

    def _create(self, session: Session, actor: CurrentUser, payload: ReturnCreateIn) -> CreateOut:
        errors: dict[str, list[str]] = {}

        def fail(field: str, message: str) -> None:
            errors.setdefault(field, []).append(message)

        today = repo.business_today(session)
        if payload.entry_date > today:
            fail("entry_date", "The date cannot be later than today")
        min_date = _min_entry_date(session, today)
        if min_date is not None and payload.entry_date < min_date:
            fail("entry_date", f"The date can be at most {(today - min_date).days} days back")

        platforms = _labels(session, SET_PLATFORM)
        if payload.platform_code not in platforms:
            fail("platform_code", "Choose a platform from the list")

        order_id = payload.order_id.strip()
        if not re.fullmatch(_order_pattern(session), order_id):
            fail(
                "order_id",
                "Order ID must be letters and digits (a hyphen is allowed), 3 to 40 characters",
            )

        product_types = _labels(session, SET_PRODUCT_TYPE)
        product: dict[str, Any] | None = None
        desc: str | None = None
        if payload.product_type_code not in product_types:
            fail("product_type_code", "This product type is not available")
        # Only the field of the chosen product type counts; the other is ignored.
        if payload.product_type_code == COMPANY_PRODUCT:
            if payload.product_id is None:
                fail("product_id", "Choose the product")
            else:
                product = repo.get_active_product(session, payload.product_id)
                if product is None:
                    fail("product_id", "The product is not active in the product master")
        else:
            desc = (payload.different_product_desc or "").strip()
            if len(desc) < 3:
                fail(
                    "different_product_desc",
                    "Describe the item found in the packet (3+ characters)",
                )

        routings = _labels(session, SET_QC_ROUTING)
        if payload.qc_routing_code not in routings:
            fail("qc_routing_code", "This QC status is not available")

        video_max = _int_setting(session, "upload_max_video_bytes", DEFAULT_VIDEO_MAX)
        image_max = _int_setting(session, "upload_max_document_bytes", DEFAULT_IMAGE_MAX)
        images_total_max = _int_setting(
            session, "ecommerce_images_max_total_bytes", DEFAULT_IMAGES_TOTAL
        )
        checked: list[tuple[str, MediaIn, str, str]] = []
        try:
            mime, ext = _check_media(VIDEO, payload.video, video_max, "video")
            checked.append((VIDEO, payload.video, mime, ext))
        except FileRejectedError as exc:
            fail(exc.field, exc.message)
        for i, img in enumerate(payload.images):
            try:
                mime, ext = _check_media(IMAGE, img, image_max, f"images.{i}")
                checked.append((IMAGE, img, mime, ext))
            except FileRejectedError as exc:
                fail(exc.field, exc.message)
        total = sum(i.size_bytes for i in payload.images)
        if total > images_total_max:
            fail(
                "images",
                f"Images total {total // (1024 * 1024)} MB; the limit is "
                f"{images_total_max // (1024 * 1024)} MB together",
            )
        if errors:
            raise ValidationFailed(
                "Some fields need attention", code="VALIDATION_FAILED", details=errors
            )

        return_no = repo.next_return_no(session, payload.entry_date)
        return_id = repo.insert_return(
            session,
            {
                "return_no": return_no,
                "entry_date": payload.entry_date,
                "platform_code": payload.platform_code,
                "platform_label": platforms[payload.platform_code],
                "order_id": order_id,
                "product_type_code": payload.product_type_code,
                "product_type_label": product_types[payload.product_type_code],
                "product_id": product["id"] if product else None,
                "product_code_snapshot": product["code"] if product else None,
                "product_name_snapshot": product["name"] if product else None,
                "different_product_desc": desc
                if payload.product_type_code == DIFFERENT_PRODUCT
                else None,
                "qty": payload.qty,
                "qc_routing_code": payload.qc_routing_code,
                "qc_routing_label": routings[payload.qc_routing_code],
            },
        )
        repo.insert_event(
            session,
            return_id,
            "CREATED",
            from_status=None,
            to_status="DRAFT",
            details={"return_no": return_no, "qc_routing": payload.qc_routing_code},
        )
        uploads = [
            self._new_media(session, return_id, kind, media, mime, ext)
            for kind, media, mime, ext in checked
        ]
        log.info(
            "ecommerce_return_created",
            return_id=str(return_id),
            return_no=return_no,
            images=len(payload.images),
        )
        return CreateOut(ecommerce_return=self._return_out(session, return_id), uploads=uploads)

    def _new_media(
        self, session: Session, return_id: UUID, kind: str, media: MediaIn, mime: str, ext: str
    ) -> MediaUploadOut:
        row = repo.insert_media(
            session,
            {
                "return_id": return_id,
                "kind": kind,
                "bucket": BUCKET_FOR[kind].value,
                "object_path": _object_path(return_id, kind, ext),
                "mime_type": mime,
                "size_bytes": media.size_bytes,
                "file_name": (media.file_name or "").strip() or None,
            },
        )
        return MediaUploadOut(media=_media_out(row), upload=self._sign(session, row))

    def _sign(self, session: Session, media: dict[str, Any]) -> SignedPutUpload | TusUpload:
        bucket = Bucket(media["bucket"])
        path = media["object_path"]
        threshold = _int_setting(
            session, "upload_resumable_threshold_bytes", DEFAULT_RESUMABLE_THRESHOLD
        )
        if bucket is Bucket.VIDEOS and int(media["size_bytes"]) > threshold:
            tus = self.storage.create_resumable_upload(bucket, path)
            return TusUpload(
                endpoint=tus.endpoint,
                token=tus.token,
                bucket=tus.bucket,
                object_path=path,
                content_type=media["mime_type"],
                chunk_size=TUS_CHUNK_SIZE,
            )
        signed = self.storage.create_signed_upload_url(bucket, path)
        return SignedPutUpload(url=signed.signed_url, bucket=signed.bucket, object_path=path)

    # ================================================================ media ==================
    def _draft(self, session: Session, return_id: UUID) -> dict[str, Any]:
        ret = repo.get_return(session, return_id, for_update=True)
        if not ret:
            raise NotFound("E-Commerce Return not found")
        if ret["status"] != "DRAFT":
            raise Conflict(
                "Files can only change before the return is submitted",
                code="ECOM_INVALID_STATE",
                details={"status": ret["status"]},
            )
        return ret

    def _media_of(self, session: Session, return_id: UUID, media_id: UUID) -> dict[str, Any]:
        media = repo.get_media(session, media_id, for_update=True)
        if not media or media["return_id"] != return_id:
            raise NotFound("File not found on this E-Commerce Return")
        return media

    def add_media(
        self, actor: CurrentUser, return_id: UUID, kind: str, payload: MediaIn
    ) -> MediaUploadOut:
        """Add a file to a DRAFT (e.g. a new video after a failed / expired upload)."""
        with self._uow.transaction(actor.id) as session:
            self._draft(session, return_id)
            live = repo.media_for_return(session, return_id)
            if kind == VIDEO:
                if any(m["kind"] == VIDEO and m["status"] != "REJECTED" for m in live):
                    raise Conflict(
                        "This return already has a package opening video; remove it first",
                        code="ECOM_VIDEO_EXISTS",
                    )
                max_bytes = _int_setting(session, "upload_max_video_bytes", DEFAULT_VIDEO_MAX)
            else:
                max_bytes = _int_setting(session, "upload_max_document_bytes", DEFAULT_IMAGE_MAX)
            try:
                mime, ext = _check_media(kind, payload, max_bytes, "file")
            except FileRejectedError as exc:
                raise ValidationFailed(
                    exc.message, code="FILE_REJECTED", details={exc.field: [exc.message]}
                ) from exc
            if kind == IMAGE:
                cap = _int_setting(
                    session, "ecommerce_images_max_total_bytes", DEFAULT_IMAGES_TOTAL
                )
                if repo.live_image_bytes(session, return_id) + payload.size_bytes > cap:
                    raise ValidationFailed(
                        f"Images can total at most {cap // (1024 * 1024)} MB",
                        code="ECOM_IMAGES_TOO_LARGE",
                        details={"images": [f"Limit {cap // (1024 * 1024)} MB together"]},
                    )
            out = self._new_media(session, return_id, kind, payload, mime, ext)
            repo.insert_event(
                session,
                return_id,
                "MEDIA_ADDED",
                from_status="DRAFT",
                to_status="DRAFT",
                details={"kind": kind, "media_id": str(out.media.id)},
            )
            return out

    def upload_url(self, actor: CurrentUser, return_id: UUID, media_id: UUID) -> MediaUploadOut:
        """A fresh signed upload for a file still waiting (retry after a failed upload)."""
        with self._uow.transaction(actor.id) as session:
            self._draft(session, return_id)
            media = self._media_of(session, return_id, media_id)
            if media["status"] != "PENDING_UPLOAD":
                raise Conflict("This file is not waiting for an upload", code="MEDIA_NOT_PENDING")
            return MediaUploadOut(media=_media_out(media), upload=self._sign(session, media))

    def confirm(
        self, actor: CurrentUser, return_id: UUID, media_id: UUID, payload: ConfirmMediaIn
    ) -> MediaOut:
        mismatch: ValidationFailed | None = None
        remove: tuple[Bucket, str] | None = None
        confirmed: dict[str, Any] | None = None
        with self._uow.transaction(actor.id) as session:
            self._draft(session, return_id)
            media = self._media_of(session, return_id, media_id)
            if media["status"] == "CONFIRMED":
                return _media_out(media)  # repeat confirmation: same result
            if media["status"] != "PENDING_UPLOAD":
                raise Conflict("This file was removed", code="ATTACHMENT_REJECTED")
            path: str = media["object_path"]
            bucket = Bucket(media["bucket"])
            reported = (payload.object_path or "").strip().lstrip("/")
            if reported and reported not in (path, f"{bucket.value}/{path}"):
                raise ValidationFailed(
                    "The uploaded object is not at the expected path",
                    code="OBJECT_PATH_MISMATCH",
                    details={"object_path": ["Does not match the server-generated path"]},
                )
            if not _PATH.fullmatch(path) or not path.startswith(f"ecom/{return_id}/"):
                raise ValidationFailed(
                    "The file path is outside ecom/{return_id}/", code="OBJECT_PATH_MISMATCH"
                )
            info = self.storage.object_info(bucket, path)
            if not info.exists:
                raise Conflict(
                    "The file has not been uploaded yet (or the upload is incomplete)",
                    code="OBJECT_NOT_UPLOADED",
                )
            problems: dict[str, list[str]] = {}
            if info.size is None or info.size != int(media["size_bytes"]):
                problems["size_bytes"] = [
                    f"Declared {media['size_bytes']} bytes, uploaded {info.size} bytes"
                ]
            if normalise_mime(info.content_type or "") != media["mime_type"]:
                problems["mime_type"] = [
                    f"Declared {media['mime_type']}, uploaded {info.content_type or 'unknown'}"
                ]
            if problems:
                repo.set_media_status(session, media_id, "REJECTED")
                repo.insert_event(
                    session,
                    return_id,
                    "MEDIA_REJECTED",
                    from_status="DRAFT",
                    to_status="DRAFT",
                    details={"media_id": str(media_id), "problems": problems},
                )
                remove = (bucket, path)
                mismatch = ValidationFailed(
                    "The uploaded file does not match what was declared",
                    code="UPLOAD_MISMATCH",
                    details=problems,
                )
            else:
                repo.set_media_status(session, media_id, "CONFIRMED")
                confirmed = repo.get_media(session, media_id)
        if mismatch is not None:
            if remove:
                self._remove_object(*remove, media_id=media_id)
            log.info("ecommerce_upload_rejected", media_id=str(media_id))
            raise mismatch
        assert confirmed is not None  # noqa: S101 - set in the same transaction
        log.info("ecommerce_upload_confirmed", media_id=str(media_id), kind=media["kind"])
        return _media_out(confirmed)

    def discard(self, actor: CurrentUser, return_id: UUID, media_id: UUID) -> MediaOut:
        """Remove a file that is still waiting for its upload (e.g. an image that failed)."""
        with self._uow.transaction(actor.id) as session:
            self._draft(session, return_id)
            media = self._media_of(session, return_id, media_id)
            if media["status"] != "PENDING_UPLOAD":
                raise Conflict(
                    "Only a file that is still waiting for its upload can be removed",
                    code="MEDIA_NOT_PENDING",
                )
            repo.set_media_status(session, media_id, "REJECTED")
            repo.insert_event(
                session,
                return_id,
                "MEDIA_REMOVED",
                from_status="DRAFT",
                to_status="DRAFT",
                details={"kind": media["kind"], "media_id": str(media_id)},
            )
            row = repo.get_media(session, media_id)
        assert row is not None  # noqa: S101
        return _media_out(row)

    # ================================================================ lifecycle ==============
    def submit(self, actor: CurrentUser, return_id: UUID, idem: IdempotencyKey) -> IdempotentResult:
        return self._command(actor, idem, 200, lambda s: self._submit(s, actor, return_id))

    def _submit(self, session: Session, actor: CurrentUser, return_id: UUID) -> ReturnOut:
        ret = self._draft(session, return_id)
        media = repo.media_for_return(session, return_id)
        if not any(m["kind"] == VIDEO and m["status"] == "CONFIRMED" for m in media):
            raise Conflict(
                "Upload the package opening video before submitting",
                code="ECOM_VIDEO_REQUIRED",
            )
        pending = [str(m["id"]) for m in media if m["status"] == "PENDING_UPLOAD"]
        if pending:
            raise Conflict(
                "A file is still uploading; finish or remove it first",
                code="ECOM_MEDIA_PENDING",
                details={"media_ids": pending},
            )
        if ret["qc_routing_code"] == ISSUE_TO_CHECKING:
            self._issue_to_checking(session, actor, ret)
        else:
            repo.set_return_submitted(session, return_id, status="PENDING_TICKET", by=actor.id)
            repo.insert_ticket(session, return_id)
            ticket = repo.ticket_for_return(session, return_id)
            assert ticket is not None  # noqa: S101 - inserted above
            repo.insert_event(
                session,
                return_id,
                "TICKET_QUEUED",
                from_status="DRAFT",
                to_status="PENDING_TICKET",
                details={"sla_due_at": ticket["sla_due_at"]},
            )
        log.info("ecommerce_return_submitted", return_id=str(return_id))
        return self._return_out(session, return_id)

    def _issue_to_checking(self, session: Session, actor: CurrentUser, ret: dict[str, Any]) -> None:
        """EXTENSION POINT (DEC-73): QC status "Issue to Checking Department".

        Today the return only moves DRAFT → IN_CHECKING and stays OPEN: the Checking Department
        process is not defined yet, so nothing else happens and nothing is invented here. The next
        phase plugs in by
          1. adding its own commands (receive / result / close) to this service, and
          2. adding the exits from IN_CHECKING to `rms_private.ecommerce_returns_guard` (branch
             "IN_CHECKING") in a NEW migration,
        without changing the gate entry, the media or the ticket path.
        """
        repo.set_return_submitted(session, ret["id"], status="IN_CHECKING", by=actor.id)
        repo.insert_event(
            session, ret["id"], "ISSUED_TO_CHECKING", from_status="DRAFT", to_status="IN_CHECKING"
        )

    def void(
        self, actor: CurrentUser, return_id: UUID, payload: VoidIn, idem: IdempotencyKey
    ) -> IdempotentResult:
        def run(session: Session) -> ReturnOut:
            ret = repo.get_return(session, return_id, for_update=True)
            if not ret:
                raise NotFound("E-Commerce Return not found")
            if ret["status"] in NOT_VOIDABLE:
                raise Conflict(
                    f"A {ret['status'].lower()} return cannot be voided",
                    code="ECOM_INVALID_STATE",
                    details={"status": ret["status"]},
                )
            reason = payload.reason.strip()
            if len(reason) < 3:
                raise ValidationFailed(
                    "Give a reason (3+ characters)", details={"reason": ["Required"]}
                )
            repo.set_return_voided(session, return_id, reason=reason, by=actor.id)
            repo.insert_event(
                session,
                return_id,
                "VOIDED",
                from_status=ret["status"],
                to_status="VOIDED",
                details={"reason": reason},
            )
            log.info("ecommerce_return_voided", return_id=str(return_id))
            return self._return_out(session, return_id)

        return self._command(actor, idem, 200, run)

    # ================================================================ tickets ================
    def _ticket(self, session: Session, ticket_id: UUID) -> tuple[dict[str, Any], dict[str, Any]]:
        ticket = repo.get_ticket(session, ticket_id, for_update=True)
        if not ticket:
            raise NotFound("Ticket not found")
        ret = repo.get_return(session, ticket["return_id"], for_update=True)
        assert ret is not None  # noqa: S101 - FK
        if ret["status"] == "VOIDED":
            raise Conflict("The return was voided", code="ECOM_INVALID_STATE")
        if ticket["closed_at"] is not None:
            raise Conflict("This ticket is closed", code="ECOM_TICKET_CLOSED")
        return ticket, ret

    def raise_ticket(
        self, actor: CurrentUser, ticket_id: UUID, idem: IdempotencyKey
    ) -> IdempotentResult:
        def run(session: Session) -> ReturnOut:
            ticket, ret = self._ticket(session, ticket_id)
            if ticket["raised_at"] is not None:
                raise Conflict("This ticket was already raised", code="ECOM_TICKET_RAISED")
            repo.mark_ticket_raised(session, ticket_id, by=actor.id)  # DB moves the return
            now = datetime.now(UTC)
            repo.insert_event(
                session,
                ret["id"],
                "TICKET_RAISED",
                from_status=ret["status"],
                to_status="TICKET_RAISED",
                details={"sla_due_at": ticket["sla_due_at"], "late": now > ticket["sla_due_at"]},
            )
            return self._return_out(session, ret["id"])

        return self._command(actor, idem, 200, run)

    def respond(
        self, actor: CurrentUser, ticket_id: UUID, payload: TicketResponseIn, idem: IdempotencyKey
    ) -> IdempotentResult:
        def run(session: Session) -> ReturnOut:
            ticket, ret = self._ticket(session, ticket_id)
            if ticket["raised_at"] is None:
                raise Conflict(
                    "Raise the ticket on the platform first", code="ECOM_TICKET_NOT_RAISED"
                )
            labels = _labels(session, SET_RESPONSE)
            if payload.response_code not in labels:
                raise ValidationFailed(
                    "This response is not available",
                    details={"response_code": ["Not an active option"]},
                )
            remark: str | None = None
            amount: Decimal | None = None
            if payload.response_code == REJECTED:
                remark = (payload.rejection_remark or "").strip()
                if len(remark) < 3:
                    raise ValidationFailed(
                        "A rejection remark is required",
                        code="ECOM_REMARK_REQUIRED",
                        details={"rejection_remark": ["Required when the platform rejected"]},
                    )
            elif payload.response_code == CLAIM_RECEIVED:
                amount = payload.claim_amount
                if amount is None or amount <= 0:
                    raise ValidationFailed(
                        "The claim amount is required",
                        code="ECOM_CLAIM_AMOUNT_REQUIRED",
                        details={"claim_amount": ["Required when a claim was received"]},
                    )
            repo.set_ticket_response(
                session,
                ticket_id,
                code=payload.response_code,
                label=labels[payload.response_code],
                remark=remark,
                amount=amount,
                by=actor.id,
            )
            repo.insert_event(
                session,
                ret["id"],
                "TICKET_RESPONSE",
                from_status=ret["status"],
                to_status=ret["status"],
                details={
                    "response_code": payload.response_code,
                    "rejection_remark": remark,
                    "claim_amount": str(amount) if amount is not None else None,
                },
            )
            return self._return_out(session, ret["id"])

        return self._command(actor, idem, 200, run)

    def close_ticket(
        self, actor: CurrentUser, ticket_id: UUID, payload: ResolutionIn, idem: IdempotencyKey
    ) -> IdempotentResult:
        """DEC-76: closing the ticket finishes the executive's work on the return: the platform
        outcome AND the portal resolution, in one command → PENDING_UNBOXING."""

        def run(session: Session) -> ReturnOut:
            ticket, ret = self._ticket(session, ticket_id)
            code = ticket["response_code"]
            if ticket["raised_at"] is None or code is None:
                raise Conflict(
                    "Record the platform's response before closing",
                    code="ECOM_TICKET_NO_RESPONSE",
                )
            if code == PENDING:
                raise Conflict(
                    "The platform response is Pending; the ticket stays open",
                    code="ECOM_TICKET_PENDING",
                )
            if code == REJECTED and len((ticket["rejection_remark"] or "").strip()) < 3:
                raise Conflict("The rejection remark is missing", code="ECOM_REMARK_REQUIRED")
            if code == CLAIM_RECEIVED and not ticket["claim_amount"]:
                raise Conflict("The claim amount is missing", code="ECOM_CLAIM_AMOUNT_REQUIRED")
            resolution = self._resolution(session, ret, payload)
            repo.close_ticket(session, ticket_id, by=actor.id)
            repo.insert_event(
                session,
                ret["id"],
                "TICKET_CLOSED",
                from_status=ret["status"],
                to_status=ret["status"],
                details={"response_code": code},
            )
            self._record_resolution(session, actor, ret, resolution)
            log.info("ecommerce_ticket_closed", ticket_id=str(ticket_id), response=code)
            return self._return_out(session, ret["id"])

        return self._command(actor, idem, 200, run)

    def follow_up(
        self, actor: CurrentUser, ticket_id: UUID, payload: FollowUpIn, idem: IdempotencyKey
    ) -> IdempotentResult:
        """DEC-76: the executive chased the platform (note + optional next follow-up date)."""

        def run(session: Session) -> ReturnOut:
            ticket, ret = self._ticket(session, ticket_id)
            if ticket["raised_at"] is None:
                raise Conflict(
                    "Raise the ticket on the platform first", code="ECOM_TICKET_NOT_RAISED"
                )
            note = payload.note.strip()
            if len(note) < 3:
                raise ValidationFailed(
                    "Write the follow-up (3+ characters)", details={"note": ["Required"]}
                )
            next_on = payload.next_follow_up_on
            if next_on is not None and next_on < repo.business_today(session):
                raise ValidationFailed(
                    "The next follow-up cannot be in the past",
                    details={"next_follow_up_on": ["Today or later"]},
                )
            repo.add_ticket_follow_up(session, ticket_id, next_on=next_on)
            repo.insert_event(
                session,
                ret["id"],
                "TICKET_FOLLOW_UP",
                from_status=ret["status"],
                to_status=ret["status"],
                details={"note": note, "next_follow_up_on": next_on},
            )
            return self._return_out(session, ret["id"])

        return self._command(actor, idem, 200, run)

    # ================================================================ portal check (DEC-76) ===
    def portal_queue(self, actor: CurrentUser) -> PortalCheckQueueOut:
        with self._uow.transaction(actor.id) as session:
            resolutions = [OptionOut(**o) for o in repo.options(session, SET_RESOLUTION)]
            rows = repo.portal_check_queue(session, limit=LIST_LIMIT)
        return PortalCheckQueueOut(
            resolution_options=resolutions, rows=[PortalCheckRowOut(**r) for r in rows]
        )

    def portal_check(
        self, actor: CurrentUser, return_id: UUID, payload: ResolutionIn, idem: IdempotencyKey
    ) -> IdempotentResult:
        def run(session: Session) -> ReturnOut:
            ret = repo.get_return(session, return_id, for_update=True)
            if not ret:
                raise NotFound("E-Commerce Return not found")
            if ret["status"] != "IN_CHECKING":
                raise Conflict(
                    "This return is not waiting for a portal check",
                    code="ECOM_INVALID_STATE",
                    details={"status": ret["status"]},
                )
            resolution = self._resolution(session, ret, payload)
            self._record_resolution(session, actor, ret, resolution)
            return self._return_out(session, return_id)

        return self._command(actor, idem, 200, run)

    def _resolution(
        self, session: Session, ret: dict[str, Any], payload: ResolutionIn
    ) -> tuple[str, str, int, str | None]:
        labels = _labels(session, SET_RESOLUTION)
        errors: dict[str, list[str]] = {}
        if payload.resolution_code not in labels:
            errors["resolution_code"] = ["Choose Free Replacement or Refund"]
        if payload.resolution_qty > ret["qty"]:
            errors["resolution_qty"] = [f"At most the {ret['qty']} received"]
        if errors:
            raise ValidationFailed(
                "Record what the portal shows for this order",
                code="ECOM_RESOLUTION_REQUIRED",
                details=errors,
            )
        note = (payload.resolution_note or "").strip() or None
        code = payload.resolution_code
        return code, labels[code], payload.resolution_qty, note

    def _record_resolution(
        self,
        session: Session,
        actor: CurrentUser,
        ret: dict[str, Any],
        resolution: tuple[str, str, int, str | None],
    ) -> None:
        code, label, qty, note = resolution
        repo.set_return_resolved(
            session, ret["id"], code=code, label=label, qty=qty, note=note, by=actor.id
        )
        repo.insert_event(
            session,
            ret["id"],
            "RESOLUTION_RECORDED",
            from_status=ret["status"],
            to_status="PENDING_UNBOXING",
            details={"resolution_code": code, "qty": qty, "note": note},
        )
        log.info("ecommerce_resolution_recorded", return_id=str(ret["id"]), resolution=code)

    # ================================================================ worker =================
    def cleanup_stale_pending(self, *, batch: int = 200) -> int:
        """Worker job: files of a DRAFT still waiting for their upload after
        `pending_upload_retention_hours` are marked REJECTED and their objects removed (same rule
        as the offline attachments). The DRAFT stays; a new video can be added to it."""
        with self._uow.transaction(None) as session:
            hours = _int_setting(
                session, "pending_upload_retention_hours", DEFAULT_PENDING_RETENTION_HOURS
            )
            stale = repo.stale_pending_media(session, older_than_hours=hours, limit=batch)
            for m in stale:
                repo.set_media_status(session, m["id"], "REJECTED")
                repo.insert_event(
                    session,
                    m["return_id"],
                    "MEDIA_EXPIRED",
                    from_status="DRAFT",
                    to_status="DRAFT",
                    details={"media_id": str(m["id"]), "after_hours": hours},
                )
        for m in stale:
            self._remove_object(Bucket(m["bucket"]), m["object_path"], media_id=m["id"])
        if stale:
            log.info("ecommerce_pending_uploads_expired", rows=len(stale))
        return len(stale)

    # ================================================================ internals ==============
    def _command(
        self,
        actor: CurrentUser,
        idem: IdempotencyKey,
        status: int,
        work: Callable[[Session], ReturnOut],
    ) -> IdempotentResult:
        with self._uow.transaction(actor.id) as session:
            return run_idempotent(
                session, idem, actor.id, lambda: (status, work(session).model_dump(mode="json"))
            )

    def _return_out(self, session: Session, return_id: UUID) -> ReturnOut:
        ret = repo.get_return(session, return_id)
        if not ret:
            raise NotFound("E-Commerce Return not found")
        labels = _labels(session, SET_STATUS)
        ticket = repo.ticket_for_return(session, return_id)
        now = datetime.now(UTC)
        return ReturnOut(
            **{
                k: ret[k]
                for k in (
                    "id",
                    "return_no",
                    "entry_date",
                    "platform_code",
                    "platform_label",
                    "order_id",
                    "product_type_code",
                    "product_type_label",
                    "product_id",
                    "product_code",
                    "product_name",
                    "different_product_desc",
                    "qty",
                    "qc_routing_code",
                    "qc_routing_label",
                    "status",
                    "created_at",
                    "created_by_name",
                    "submitted_at",
                    "void_reason",
                    "voided_at",
                    "closed_at",
                    "resolution_code",
                    "resolution_label",
                    "resolution_qty",
                    "resolution_note",
                    "resolved_at",
                    "resolved_by_name",
                )
            },
            status_label=labels.get(ret["status"], ret["status"]),
            settlement=EcommerceSettlementService.settlement_for_return(session, return_id),
            media=[_media_out(m) for m in repo.media_for_return(session, return_id)],
            ticket=_ticket_out(ticket, now) if ticket else None,
            events=[EventOut(**e) for e in repo.events_for_return(session, return_id)],
        )

    def _remove_object(self, bucket: Bucket, path: str, *, media_id: UUID) -> None:
        """Best effort after the DB change committed; a failure is logged with context."""
        try:
            self.storage.delete(bucket, path)
        except (ServiceUnavailable, httpx.HTTPError) as exc:
            log.error(
                "storage_object_delete_failed",
                media_id=str(media_id),
                bucket=bucket.value,
                error=str(exc),
            )
