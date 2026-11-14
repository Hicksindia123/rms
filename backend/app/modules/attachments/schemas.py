"""Attachments API schemas (prompt P2-03)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.attachments.allowlist import UploadKind


class UploadUrlIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: UploadKind
    mime_type: str = Field(min_length=3, max_length=100)
    size_bytes: int = Field(gt=0)
    box_no: int | None = Field(default=None, ge=1)
    # Only cross-checked against the MIME allow-list; never used in the object path (§8.8).
    file_name: str | None = Field(default=None, max_length=255)


class ProofUploadIn(BaseModel):
    """DEC-25: a party-notification proof (kind NOTIFICATION_PROOF is implied)."""

    model_config = ConfigDict(extra="forbid")

    mime_type: str = Field(min_length=3, max_length=100)
    size_bytes: int = Field(gt=0)
    file_name: str | None = Field(default=None, max_length=255)


class GateDocFileUploadIn(BaseModel):
    """AMD-04: a file (image or PDF) of a gate document row (kind GATE_DOC is implied)."""

    model_config = ConfigDict(extra="forbid")

    mime_type: str = Field(min_length=3, max_length=100)
    size_bytes: int = Field(gt=0)
    file_name: str | None = Field(default=None, max_length=255)


class AttachmentOut(BaseModel):
    id: UUID
    gs_id: UUID
    kind: str
    mime_type: str
    size_bytes: int
    box_no: int | None
    status: str
    uploaded_by: UUID | None
    uploaded_by_name: str | None
    created_at: datetime
    confirmed_at: datetime | None
    preview_unsupported: bool
    gate_document_id: UUID | None = None


class SignedPutUpload(BaseModel):
    """Single-request upload: `PUT url` with the file as body and `Content-Type: mime_type`."""

    method: Literal["SIGNED_PUT"] = "SIGNED_PUT"
    url: str
    bucket: str
    object_path: str


class TusUpload(BaseModel):
    """Supabase resumable (TUS 1.0.0) upload. Send `x-signature: token` on every request and the
    metadata below (base64 per TUS); chunks must be `chunk_size` bytes (Supabase requires 6 MB)."""

    method: Literal["TUS"] = "TUS"
    endpoint: str
    token: str
    bucket: str
    object_path: str
    content_type: str
    chunk_size: int


class UploadUrlOut(BaseModel):
    attachment: AttachmentOut
    upload: SignedPutUpload | TusUpload = Field(discriminator="method")


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Optional: the object key the client reports (e.g. from the upload response). When given it
    # must equal the server-generated path; it is never used to locate the object.
    object_path: str | None = Field(default=None, max_length=300)


class DownloadUrlOut(BaseModel):
    url: str
    expires_in: int
    expires_at: datetime
    mime_type: str
