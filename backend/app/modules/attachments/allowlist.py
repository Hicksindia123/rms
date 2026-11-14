"""File allow-list for Step-2 evidence (master plan §9.6, §8.8, DD r11 / r16, prompt P2-03).

Pure functions (no I/O). The allow-list is a security control, mirrored by the
`attachments_mime_for_kind` CHECK and the bucket `allowed_mime_types` (20261102000600_storage.sql);
size limits are business configuration and come from `system_settings` (DEC-04).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.shared.storage import Bucket

UploadKind = Literal["UNBOXING_VIDEO", "DOC_PHOTO", "PARCEL_PHOTO"]
UPLOAD_KINDS: tuple[UploadKind, ...] = ("UNBOXING_VIDEO", "DOC_PHOTO", "PARCEL_PHOTO")
# P3-07 / DEC-25: proof of the prior party notification (screenshot, scanned letter, PDF).
PROOF_KIND = "NOTIFICATION_PROOF"
# AMD-04: files of a gate document row (invoice, courier slip, ...), uploaded at the gate.
GATE_DOC_KIND = "GATE_DOC"

# MIME type → accepted file extensions (the first one names the stored object).
_VIDEO = {"video/mp4": ("mp4",), "video/quicktime": ("mov", "qt")}  # DD r11: .mp4 / .mov
_IMAGES = {
    "image/jpeg": ("jpg", "jpeg"),
    "image/png": ("png",),
    # §9.6: HEIC is accepted and flagged (attachments.preview_unsupported).
    "image/heic": ("heic",),
    "image/heif": ("heif", "heic"),
}
_PDF = {"application/pdf": ("pdf",)}  # DD r16: .jpg / .png / .pdf

ALLOWED: dict[str, dict[str, tuple[str, ...]]] = {
    "UNBOXING_VIDEO": _VIDEO,
    "DOC_PHOTO": {**_IMAGES, **_PDF},
    "PARCEL_PHOTO": dict(_IMAGES),  # DEC-03: a photo of the parcel label / outer box
    PROOF_KIND: {**_IMAGES, **_PDF},  # DEC-25: notification proof
    GATE_DOC_KIND: {**_IMAGES, **_PDF},  # AMD-04: gate document files (mirrors the DB CHECK)
}

BUCKET_FOR_KIND: dict[str, Bucket] = {
    "UNBOXING_VIDEO": Bucket.VIDEOS,
    "DOC_PHOTO": Bucket.DOCUMENTS,
    "PARCEL_PHOTO": Bucket.DOCUMENTS,
    PROOF_KIND: Bucket.DOCUMENTS,
    GATE_DOC_KIND: Bucket.DOCUMENTS,
}

# system_settings key holding the size limit per kind (DEC-04).
SIZE_SETTING_FOR_KIND: dict[str, str] = {
    "UNBOXING_VIDEO": "upload_max_video_bytes",
    "DOC_PHOTO": "upload_max_document_bytes",
    "PARCEL_PHOTO": "upload_max_document_bytes",
    PROOF_KIND: "upload_max_document_bytes",
    GATE_DOC_KIND: "upload_max_document_bytes",
}


@dataclass(frozen=True, slots=True)
class AllowedFile:
    kind: str
    mime_type: str
    ext: str
    bucket: Bucket


class FileRejectedError(ValueError):
    """The file is not on the allow-list; `field` names the offending input."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def normalise_mime(mime_type: str) -> str:
    """'Video/MP4; codecs=avc1' → 'video/mp4'."""
    return mime_type.split(";", 1)[0].strip().lower()


def check_file(kind: str, mime_type: str, file_name: str | None = None) -> AllowedFile:
    """Validate kind + MIME (+ the extension of the client's file name, if given).

    The file name is only cross-checked: it never becomes part of the object path (§8.8).
    """
    allowed = ALLOWED.get(kind)
    if allowed is None:
        raise FileRejectedError("kind", f"Uploads of kind {kind!r} are not accepted here")
    mime = normalise_mime(mime_type)
    exts = allowed.get(mime)
    if exts is None:
        accepted = ", ".join(sorted(allowed))
        raise FileRejectedError(
            "mime_type", f"{mime or 'unknown'} is not allowed for {kind} ({accepted})"
        )
    if file_name is not None and file_name.strip():
        name = file_name.strip().lower()
        ext = name.rsplit(".", 1)[1] if "." in name else ""
        if ext not in exts:
            raise FileRejectedError(
                "file_name",
                f"File extension .{ext or '?'} does not match {mime} "
                f"(expected .{', .'.join(exts)})",
            )
    return AllowedFile(kind=kind, mime_type=mime, ext=exts[0], bucket=BUCKET_FOR_KIND[kind])


def check_size(size_bytes: int, max_bytes: int) -> None:
    if size_bytes <= 0:
        raise FileRejectedError("size_bytes", "The file is empty")
    if size_bytes > max_bytes:
        raise FileRejectedError(
            "size_bytes",
            f"The file is {size_bytes} bytes; the limit is {max_bytes} bytes "
            f"({max_bytes // (1024 * 1024)} MB)",
        )
