"""Attachments HTTP API (prompt P2-03): signed upload / download URLs. HTTP, auth, Pydantic only."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from app.core.db import UowDep
from app.core.middleware import limiter
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.attachments.schemas import (
    AttachmentOut,
    ConfirmIn,
    DownloadUrlOut,
    GateDocFileUploadIn,
    ProofUploadIn,
    UploadUrlIn,
    UploadUrlOut,
)
from app.modules.attachments.service import AttachmentService
from app.shared.storage import StorageService, get_storage

router = APIRouter(tags=["attachments"])

# §9.7: upload endpoints are rate-limited (per client address).
UPLOAD_RATE_LIMIT = "60/minute"


def get_service(
    uow: UowDep, storage: Annotated[StorageService, Depends(get_storage)]
) -> AttachmentService:
    return AttachmentService(uow, storage)


ServiceDep = Annotated[AttachmentService, Depends(get_service)]
CreateUser = Annotated[CurrentUser, Depends(require("attachments", "create"))]
ViewUser = Annotated[CurrentUser, Depends(require("attachments", "view"))]


@router.post(
    "/gs/{gs_id}/attachments/upload-url",
    response_model=UploadUrlOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(UPLOAD_RATE_LIMIT)
def request_upload_url(
    request: Request,
    gs_id: UUID,
    payload: UploadUrlIn,
    user: CreateUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
) -> UploadUrlOut:
    """Step-2 (S1_UNBOX PERFORM, GS in UNBOXING): validate kind / MIME / size, create a
    PENDING_UPLOAD row with a server path and return a signed PUT or TUS (videos > threshold)."""
    return service.request_upload(user, perms, gs_id, payload)


@router.post(
    "/gs/{gs_id}/attachments/notification-proof/upload-url",
    response_model=UploadUrlOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(UPLOAD_RATE_LIMIT)
def request_proof_upload_url(
    request: Request,
    gs_id: UUID,
    payload: ProofUploadIn,
    user: CreateUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
) -> UploadUrlOut:
    """P3-07 / DEC-25 (S6_NOTIFY PERFORM): signed upload for a party-notification proof
    (image or PDF). Confirm it with POST /attachments/{id}/confirm, then cite it in the
    party notification."""
    return service.request_proof_upload(user, perms, gs_id, payload)


@router.post(
    "/gs/{gs_id}/gate-documents/{document_id}/files/upload-url",
    response_model=UploadUrlOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(UPLOAD_RATE_LIMIT)
def request_gate_doc_upload_url(
    request: Request,
    gs_id: UUID,
    document_id: UUID,
    payload: GateDocFileUploadIn,
    user: CreateUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
) -> UploadUrlOut:
    """AMD-04 (S1_GATE PERFORM, GS at the gate): signed upload for one file (image / PDF) of a
    gate document row. Confirm it with POST /attachments/{id}/confirm."""
    return service.request_gate_doc_upload(user, perms, gs_id, document_id, payload)


@router.post("/attachments/{attachment_id}/confirm", response_model=AttachmentOut)
@limiter.limit(UPLOAD_RATE_LIMIT)
def confirm_upload(
    request: Request,
    attachment_id: UUID,
    user: CreateUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
    payload: ConfirmIn | None = None,
) -> AttachmentOut:
    """Check the stored object (path, size, MIME) and mark the attachment CONFIRMED."""
    return service.confirm(user, perms, attachment_id, payload or ConfirmIn())


@router.get("/attachments/{attachment_id}/download-url", response_model=DownloadUrlOut)
def download_url(
    attachment_id: UUID, user: ViewUser, perms: EffectivePermissionsDep, service: ServiceDep
) -> DownloadUrlOut:
    """Short-lived signed URL after the per-GS view check; the issuance is audited."""
    return service.download_url(user, perms, attachment_id)


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_attachment(
    attachment_id: UUID, user: CreateUser, perms: EffectivePermissionsDep, service: ServiceDep
) -> Response:
    """PENDING uploads, or your own CONFIRMED file while the GS is still UNBOXING."""
    service.delete(user, perms, attachment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
