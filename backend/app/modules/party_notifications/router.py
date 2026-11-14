"""Prior party notification endpoints (P3-07, BR-38, DD r79, DEC-25)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.core.db import UowDep
from app.core.idempotency import IdempotencyKeyDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.party_notifications.email_service import PartyEmailService
from app.modules.party_notifications.schemas import (
    PartyEmailOut,
    PartyEmailPreviewIn,
    PartyEmailPreviewOut,
    PartyEmailSendIn,
    PartyEmailSettingsIn,
    PartyEmailSettingsOut,
    PartyNotificationIn,
    PartyNotificationOut,
    PartyNotificationStateOut,
)
from app.modules.party_notifications.service import PartyNotificationService

router = APIRouter(tags=["party-notifications"])

ViewUser = Annotated[CurrentUser, Depends(require("goods_slips", "view"))]
CreateUser = Annotated[CurrentUser, Depends(require("credit_notes", "create"))]
ConfigViewUser = Annotated[CurrentUser, Depends(require("notifications", "view"))]
ConfigureUser = Annotated[CurrentUser, Depends(require("notifications", "configure"))]


@router.get("/gs/{gs_id}/party-notifications", response_model=PartyNotificationStateOut)
def notification_state(
    gs_id: UUID, user: ViewUser, perms: EffectivePermissionsDep, uow: UowDep
) -> PartyNotificationStateOut:
    """Recipient prefilled from the party master, an auto-built message per issued CN / JV
    (CN No., Date, items, dispatch details) and the notifications already recorded."""
    return PartyNotificationService(uow).get_state(user, perms, gs_id)


@router.post(
    "/gs/{gs_id}/party-notifications",
    response_model=PartyNotificationOut,
    status_code=status.HTTP_201_CREATED,
)
def record_notification(
    gs_id: UUID,
    payload: PartyNotificationIn,
    user: CreateUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    uow: UowDep,
) -> JSONResponse:
    """S6_NOTIFY (Accounts): record PRIOR_INFO_SENT for an issued CN / JV (BR-38). The message
    snapshot is built by the server; on the A/c Actions flow it holds the Accounts values
    (AMD-20)."""
    return PartyNotificationService(uow).record(user, perms, gs_id, payload, idem).to_response()


# --- Phase 9 / AMD-20: party email --------------------------------------------------------------


@router.post(
    "/gs/{gs_id}/party-emails",
    response_model=PartyEmailOut,
    status_code=status.HTTP_201_CREATED,
)
def send_party_email(
    gs_id: UUID,
    payload: PartyEmailSendIn,
    user: CreateUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    uow: UowDep,
) -> JSONResponse:
    """S6_NOTIFY (Accounts): email the party the CN / Challan / Dispatch values Accounts entered
    (AMD-20). Logged in party_emails; a SENT email records PRIOR_INFO_SENT (BR-38). Idempotent."""
    return PartyEmailService(uow).send(user, perms, gs_id, payload, idem).to_response()


@router.post(
    "/gs/{gs_id}/party-emails/{email_id}/resend",
    response_model=PartyEmailOut,
    status_code=status.HTTP_201_CREATED,
)
def resend_party_email(
    gs_id: UUID,
    email_id: UUID,
    user: CreateUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    uow: UowDep,
) -> JSONResponse:
    """Send a logged party email again, as a new logged email (AMD-20)."""
    return PartyEmailService(uow).resend(user, perms, gs_id, email_id, idem).to_response()


@router.get("/party-email/settings", response_model=PartyEmailSettingsOut)
def party_email_settings(user: ConfigViewUser, uow: UowDep) -> PartyEmailSettingsOut:
    """Template + delivery configuration (settings party_email.template / party_email.delivery)."""
    return PartyEmailService(uow).settings(user)


@router.put("/party-email/settings", response_model=PartyEmailSettingsOut)
def update_party_email_settings(
    payload: PartyEmailSettingsIn, user: ConfigureUser, uow: UowDep
) -> PartyEmailSettingsOut:
    """Admin: change the template and auto-send mode (DEC-48). Placeholders are validated; every
    change goes to the config history."""
    return PartyEmailService(uow).update_settings(user, payload)


@router.post("/party-email/settings/preview", response_model=PartyEmailPreviewOut)
def preview_party_email(
    payload: PartyEmailPreviewIn, user: ConfigViewUser, uow: UowDep
) -> PartyEmailPreviewOut:
    """Render a draft template with sample values (nothing is saved or sent)."""
    return PartyEmailService(uow).preview(user, payload.template)
