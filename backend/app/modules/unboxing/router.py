"""Step-2 unboxing HTTP API (prompt P2-03). HTTP, auth dependencies and Pydantic I/O only."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import JSONResponse

from app.core.db import UowDep
from app.core.idempotency import IdempotencyKeyDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.goods_slips.schemas import GateDocumentOut
from app.modules.unboxing.schemas import (
    AcknowledgeOut,
    CartonDocumentIn,
    CompleteOut,
    DocumentIn,
    DocumentOut,
    DocumentPatchIn,
    OptionOut,
    QueueItem,
    UnboxingStateOut,
)
from app.modules.unboxing.service import UnboxingService
from app.shared.pagination import Page, PageParamsDep

router = APIRouter(tags=["unboxing"])


def get_service(uow: UowDep) -> UnboxingService:
    return UnboxingService(uow)


ServiceDep = Annotated[UnboxingService, Depends(get_service)]
ViewUser = Annotated[CurrentUser, Depends(require("goods_slips", "view"))]
PerformUser = Annotated[CurrentUser, Depends(require("unboxing", "create"))]
# Accounts document queue: the Accounts team's default grants (docs/DECISIONS.md, P2-03).
QueueUser = Annotated[CurrentUser, Depends(require("credit_notes", "view"))]
AckUser = Annotated[CurrentUser, Depends(require("credit_notes", "edit"))]


@router.get("/gs/{gs_id}/unboxing", response_model=UnboxingStateOut)
def unboxing_state(
    gs_id: UUID, user: ViewUser, perms: EffectivePermissionsDep, service: ServiceDep
) -> UnboxingStateOut:
    """Checklist (G-02), evidence, classifications, exceptions, form and upload limits."""
    return service.state(user, perms, gs_id)


@router.post("/gs/{gs_id}/unboxing/start", response_model=UnboxingStateOut)
def start_unboxing(
    gs_id: UUID, user: PerformUser, perms: EffectivePermissionsDep, service: ServiceDep
) -> UnboxingStateOut:
    """GATE_CREATED → UNBOXING (S1_UNBOX PERFORM). Repeating it on an UNBOXING GS is a no-op."""
    return service.start(user, perms, gs_id)


@router.post(
    "/gs/{gs_id}/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED
)
def classify_document(
    gs_id: UUID,
    payload: DocumentIn,
    user: PerformUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
) -> DocumentOut:
    """Link a confirmed DOC_PHOTO to a classification (DD r12-r15, BR-05)."""
    return service.classify(user, perms, gs_id, payload)


@router.patch("/gs/{gs_id}/documents/{doc_id}", response_model=DocumentOut)
def update_document(
    gs_id: UUID,
    doc_id: UUID,
    payload: DocumentPatchIn,
    user: PerformUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
) -> DocumentOut:
    return service.update_classification(user, perms, gs_id, doc_id, payload)


@router.post(
    "/gs/{gs_id}/carton-documents",
    response_model=GateDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
def add_carton_document(
    gs_id: UUID,
    payload: CartonDocumentIn,
    user: PerformUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """P3 / DEC-62: the one optional document found in a carton (GS UNBOXING, S1_UNBOX
    performer): a type (active GATE_DOCUMENT, not NO_DOCUMENT), no number / date / remarks; a
    second one → 409 CARTON_DOCUMENT_EXISTS. Allowed on a GS flagged "No Documents From Party".
    Invoice / GST Debit Note alert Accounts at once (AMD-05). Photos: POST
    /gs/{gs_id}/gate-documents/{document_id}/files/upload-url."""
    return service.add_carton_document(user, perms, gs_id, payload, idem).to_response()


@router.patch("/gs/{gs_id}/carton-documents/{doc_id}", response_model=GateDocumentOut)
def update_carton_document(
    gs_id: UUID,
    doc_id: UUID,
    payload: CartonDocumentIn,
    user: PerformUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
) -> GateDocumentOut:
    return service.update_carton_document(user, perms, gs_id, doc_id, payload)


@router.delete("/gs/{gs_id}/carton-documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_carton_document(
    gs_id: UUID,
    doc_id: UUID,
    user: PerformUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
) -> Response:
    service.delete_carton_document(user, perms, gs_id, doc_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# DEC-63 (user Q8, 2026-11-20): the RM Missing Document Exception (DEC-03) is retired. Its request,
# decision and pending-queue endpoints are removed; existing rows stay readable in GET
# /gs/{gs_id}/unboxing (`exceptions`, history only).


@router.post("/gs/{gs_id}/unboxing/complete", response_model=CompleteOut)
def complete_unboxing(
    gs_id: UUID, user: PerformUser, perms: EffectivePermissionsDep, service: ServiceDep
) -> CompleteOut:
    """ "Next": G-02 (one confirmed video per carton, DEC-63) → ITEMIZATION, S1_ITEMIZE task,
    Accounts alert (DEC-05). 422 `G-02` lists what is missing."""
    return service.complete(user, perms, gs_id)


@router.get("/accounts/document-queue", response_model=Page[QueueItem])
def accounts_document_queue(
    user: QueueUser,
    service: ServiceDep,
    params: PageParamsDep,
    classification: Annotated[
        str | None, Query(max_length=40, description="e.g. INVOICE, DEBIT_NOTE")
    ] = None,
) -> Page[QueueItem]:
    """GS with classified Step-2 documents not yet acknowledged by Accounts (WF r3, BR-06)."""
    return service.accounts_queue(user, params, classification)


@router.get("/accounts/document-queue/classifications", response_model=list[OptionOut])
def queue_classifications(user: QueueUser, service: ServiceDep) -> list[OptionOut]:
    return service.classification_options(user)


@router.post("/accounts/document-queue/{gs_id}/acknowledge", response_model=AcknowledgeOut)
def acknowledge_documents(gs_id: UUID, user: AckUser, service: ServiceDep) -> AcknowledgeOut:
    return service.acknowledge(user, gs_id)
