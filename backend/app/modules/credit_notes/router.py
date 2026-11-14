from __future__ import annotations

from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.core.db import UowDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.credit_notes.schemas import (
    CnTypeUpdateIn,
    CreditNoteCancelIn,
    CreditNoteCreateIn,
    CreditNoteDetailOut,
    CreditNoteIssueIn,
    CreditNoteListItemOut,
    CreditNotePrintOut,
    CreditNoteWorkQueueOut,
    GstCheckIn,
    PartyDocumentVerifyIn,
    RateVerificationIn,
    RateVerificationResultOut,
    RmCnDecisionIn,
    RmCnDecisionOut,
    RmCnDecisionPrefillOut,
)
from app.modules.credit_notes.service import CreditNotesService

router = APIRouter(tags=["credit-notes"])

ViewUser = Annotated[CurrentUser, Depends(require("credit_notes", "view"))]
CreateUser = Annotated[CurrentUser, Depends(require("credit_notes", "create"))]
EditUser = Annotated[CurrentUser, Depends(require("credit_notes", "edit"))]
ApproveUser = Annotated[CurrentUser, Depends(require("credit_notes", "approve"))]


# =============================================================================
# RM CN Decision Endpoints
# =============================================================================


@router.get(
    "/gs/{id}/cn-decision",
    response_model=RmCnDecisionPrefillOut,
    summary="Get RM CN decision prefill & current decision status",
)
def get_cn_decision_prefill(
    id: UUID,
    user: ViewUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> RmCnDecisionPrefillOut:
    service = CreditNotesService(uow)
    return service.get_cn_decision_prefill(id, user, perms)


@router.post(
    "/gs/{id}/cn-decision",
    response_model=RmCnDecisionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record RM Step-7 CN decision (ALLOW_CN / DENY_CN_SEND_REPLACEMENT)",
)
def record_cn_decision(
    id: UUID,
    payload: RmCnDecisionIn,
    user: ApproveUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> RmCnDecisionOut:
    service = CreditNotesService(uow)
    return service.record_cn_decision(id, payload, user, perms)


# =============================================================================
# Credit Note Endpoints
# =============================================================================


@router.get(
    "/credit-notes/work-queue",
    response_model=CreditNoteWorkQueueOut,
    summary="Get Accounts credit note work queue (pending GS and active notes)",
)
def get_work_queue(
    user: ViewUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> CreditNoteWorkQueueOut:
    service = CreditNotesService(uow)
    return service.get_work_queue(user, perms)


@router.post(
    "/credit-notes",
    response_model=CreditNoteDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="Draft a new Credit Note from allowed CN quantities (G-13)",
)
def create_credit_note(
    payload: CreditNoteCreateIn,
    user: CreateUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> CreditNoteDetailOut:
    service = CreditNotesService(uow)
    return service.create_credit_note(payload, user, perms)


@router.get(
    "/credit-notes",
    response_model=list[CreditNoteListItemOut],
    summary="List credit notes with status, type, and party filters",
)
def list_credit_notes(
    user: ViewUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
    gs_id: UUID | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    cn_type_code: str | None = None,
    party_search: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CreditNoteListItemOut]:
    service = CreditNotesService(uow)
    return service.list_credit_notes(
        user=user,
        perms=perms,
        gs_id=gs_id,
        status=status_filter,
        cn_type_code=cn_type_code,
        party_search=party_search,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/credit-notes/{id}",
    response_model=CreditNoteDetailOut,
    summary="Get detailed Credit Note with lines, rate verifications, and linked documents",
)
def get_credit_note(
    id: UUID,
    user: ViewUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> CreditNoteDetailOut:
    service = CreditNotesService(uow)
    return service.get_credit_note(id, user, perms)


@router.patch(
    "/credit-notes/{id}/party-document",
    response_model=CreditNoteDetailOut,
    summary="Accounts verification of party document (Invoice, Debit Note, or none)",
)
def verify_party_document(
    id: UUID,
    payload: PartyDocumentVerifyIn,
    user: EditUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> CreditNoteDetailOut:
    service = CreditNotesService(uow)
    return service.verify_party_document(id, payload, user, perms)


@router.patch(
    "/credit-notes/{id}/gst-check",
    response_model=CreditNoteDetailOut,
    summary="Accounts verification of GST portal return reflection (GSTR-1/GSTR-2B)",
)
def verify_gst_check(
    id: UUID,
    payload: GstCheckIn,
    user: EditUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> CreditNoteDetailOut:
    service = CreditNotesService(uow)
    return service.verify_gst_check(id, payload, user, perms)


@router.patch(
    "/credit-notes/{id}/type",
    response_model=CreditNoteDetailOut,
    summary="Set or update Credit Note type (GST_CN, GENERAL_CN, JV_ONLY)",
)
def update_cn_type(
    id: UUID,
    payload: CnTypeUpdateIn,
    user: EditUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> CreditNoteDetailOut:
    service = CreditNotesService(uow)
    return service.update_cn_type(id, payload, user, perms)


@router.post(
    "/credit-notes/{id}/split",
    response_model=dict[str, Any],
    summary="Automatically split a mixed Credit Note (Good vs Repaired) into separate CN records",
)
def split_credit_note(
    id: UUID,
    user: EditUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> dict[str, Any]:
    service = CreditNotesService(uow)
    return service.split_credit_note(id, user, perms)


@router.post(
    "/credit-note-lines/{id}/rate-verifications",
    response_model=RateVerificationResultOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record historical sales or purchase rate verification for a CN line (G-14, DEC-24)",
)
def verify_rate(
    id: UUID,
    payload: RateVerificationIn,
    user: EditUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> RateVerificationResultOut:
    service = CreditNotesService(uow)
    return service.verify_rate(id, payload, user, perms)


@router.post(
    "/credit-notes/{id}/issue",
    response_model=CreditNoteDetailOut,
    summary="Issue Credit Note or Journal Voucher with accounting system voucher numbers (DEC-22)",
)
def issue_credit_note(
    id: UUID,
    payload: CreditNoteIssueIn,
    user: ApproveUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> CreditNoteDetailOut:
    service = CreditNotesService(uow)
    return service.issue_credit_note(id, payload, user, perms)


@router.post(
    "/credit-notes/{id}/cancel",
    response_model=CreditNoteDetailOut,
    summary="Cancel an issued or draft Credit Note with reason",
)
def cancel_credit_note(
    id: UUID,
    payload: CreditNoteCancelIn,
    user: ApproveUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> CreditNoteDetailOut:
    service = CreditNotesService(uow)
    return service.cancel_credit_note(id, payload, user, perms)


@router.get(
    "/credit-notes/{id}/print",
    response_model=CreditNotePrintOut,
    summary="Get printable Credit Note Summary note (CN_SUMMARY)",
)
def get_credit_note_print(
    id: UUID,
    user: ViewUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> CreditNotePrintOut:
    service = CreditNotesService(uow)
    return service.get_credit_note_print(id, user, perms)
