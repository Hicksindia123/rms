"""HTTP routes for E-Commerce Returns and their platform tickets (DEC-73). No SQL here (rule g).

Permissions (checked here and again by the DB triggers):
* ecommerce_returns.create: E-Commerce gate user (record, upload, submit)
* ecommerce_returns.view:   list / detail / file download
* ecommerce_returns.delete: void (Super Admin / Management)
* ecommerce_tickets.view / .edit: E-Commerce Executive (role TICKET_HANDLER) queue / raise,
  follow up, respond, close with the portal resolution; portal check of returns without a ticket
  (DEC-76)
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse

from app.core.db import UowDep
from app.core.idempotency import IdempotencyKeyDep
from app.core.permissions import require
from app.core.security import CurrentUser
from app.modules.ecommerce_returns.schemas import (
    ConfirmMediaIn,
    CreateOut,
    DownloadOut,
    FollowUpIn,
    FormConfigOut,
    MediaIn,
    MediaOut,
    MediaUploadOut,
    OrderMatchOut,
    PortalCheckQueueOut,
    ProductLookupOut,
    ResolutionIn,
    ReturnCreateIn,
    ReturnListOut,
    ReturnOut,
    ReturnStatus,
    TicketQueueOut,
    TicketResponseIn,
    VoidIn,
)
from app.modules.ecommerce_returns.service import IMAGE, VIDEO, EcommerceReturnService
from app.shared.storage import StorageService, get_storage

router = APIRouter(prefix="/ecommerce-returns", tags=["ecommerce-returns"])
tickets_router = APIRouter(prefix="/ecommerce-tickets", tags=["ecommerce-returns"])

ViewUser = Annotated[CurrentUser, Depends(require("ecommerce_returns", "view"))]
CreateUser = Annotated[CurrentUser, Depends(require("ecommerce_returns", "create"))]
VoidUser = Annotated[CurrentUser, Depends(require("ecommerce_returns", "delete"))]
TicketViewUser = Annotated[CurrentUser, Depends(require("ecommerce_tickets", "view"))]
TicketUser = Annotated[CurrentUser, Depends(require("ecommerce_tickets", "edit"))]
StorageDep = Annotated[StorageService, Depends(get_storage)]


# --- gate entry --------------------------------------------------------------------------------
@router.get("/form-config", response_model=FormConfigOut)
def form_config(user: CreateUser, uow: UowDep) -> FormConfigOut:
    """Options (platforms, product types, QC status), date limits and file rules of the form."""
    return EcommerceReturnService(uow).form_config(user)


@router.get("/lookups/products", response_model=list[ProductLookupOut])
def products(
    user: CreateUser, uow: UowDep, q: str | None = Query(default=None, max_length=100)
) -> list[ProductLookupOut]:
    """Type-ahead over the active product master."""
    return EcommerceReturnService(uow).products(user, q)


@router.get("/order-check", response_model=list[OrderMatchOut])
def order_check(
    user: CreateUser,
    uow: UowDep,
    platform_code: str = Query(min_length=1, max_length=50),
    order_id: str = Query(min_length=1, max_length=60),
) -> list[OrderMatchOut]:
    """Earlier returns of the same platform + order id (a warning; repeats are allowed)."""
    return EcommerceReturnService(uow).order_check(user, platform_code, order_id)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CreateOut)
def create(
    payload: ReturnCreateIn,
    user: CreateUser,
    uow: UowDep,
    idem: IdempotencyKeyDep,
    storage: StorageDep,
) -> JSONResponse:
    """Record the return (DRAFT, new number) and its files; returns one signed upload per file.
    Upload, confirm each file, then submit. `Idempotency-Key` required."""
    return EcommerceReturnService(uow, storage).create(user, payload, idem).to_response()


@router.post(
    "/{return_id}/media", status_code=status.HTTP_201_CREATED, response_model=MediaUploadOut
)
def add_media(
    return_id: UUID,
    payload: MediaIn,
    user: CreateUser,
    uow: UowDep,
    storage: StorageDep,
    kind: Literal["PACKAGE_VIDEO", "IMAGE"] = Query(),
) -> MediaUploadOut:
    """Add a file to a DRAFT (a new video after a failed / expired upload, or another image)."""
    return EcommerceReturnService(uow, storage).add_media(
        user, return_id, VIDEO if kind == "PACKAGE_VIDEO" else IMAGE, payload
    )


@router.post("/{return_id}/media/{media_id}/upload-url", response_model=MediaUploadOut)
def upload_url(
    return_id: UUID, media_id: UUID, user: CreateUser, uow: UowDep, storage: StorageDep
) -> MediaUploadOut:
    """A fresh signed upload for a file that is still waiting (retry)."""
    return EcommerceReturnService(uow, storage).upload_url(user, return_id, media_id)


@router.post("/{return_id}/media/{media_id}/confirm", response_model=MediaOut)
def confirm_media(
    return_id: UUID,
    media_id: UUID,
    payload: ConfirmMediaIn,
    user: CreateUser,
    uow: UowDep,
    storage: StorageDep,
) -> MediaOut:
    """Check the uploaded object against what was declared (size, type, path)."""
    return EcommerceReturnService(uow, storage).confirm(user, return_id, media_id, payload)


@router.post("/{return_id}/media/{media_id}/discard", response_model=MediaOut)
def discard_media(
    return_id: UUID, media_id: UUID, user: CreateUser, uow: UowDep, storage: StorageDep
) -> MediaOut:
    """Remove a file that is still waiting for its upload."""
    return EcommerceReturnService(uow, storage).discard(user, return_id, media_id)


@router.post("/{return_id}/submit", response_model=ReturnOut)
def submit(return_id: UUID, user: CreateUser, uow: UowDep, idem: IdempotencyKeyDep) -> JSONResponse:
    """Needs the uploaded video. TICKET_RAISE → ticket queued (2 h SLA); ISSUE_TO_CHECKING → In
    Checking (open). `Idempotency-Key` required."""
    return EcommerceReturnService(uow).submit(user, return_id, idem).to_response()


# --- reading -----------------------------------------------------------------------------------
@router.get("", response_model=ReturnListOut)
def list_returns(
    user: ViewUser,
    uow: UowDep,
    q: str | None = Query(default=None, max_length=100),
    status_code: Annotated[ReturnStatus | None, Query(alias="status")] = None,
) -> ReturnListOut:
    return EcommerceReturnService(uow).list(user, q, status_code)


@router.get("/media/{media_id}/download-url", response_model=DownloadOut)
def download_url(media_id: UUID, user: ViewUser, uow: UowDep, storage: StorageDep) -> DownloadOut:
    return EcommerceReturnService(uow, storage).download_url(user, media_id)


@router.get("/{return_id}", response_model=ReturnOut)
def get_return(return_id: UUID, user: ViewUser, uow: UowDep) -> ReturnOut:
    """The return with its files, ticket (SLA) and history."""
    return EcommerceReturnService(uow).get(user, return_id)


@router.post("/{return_id}/void", response_model=ReturnOut)
def void(
    return_id: UUID, payload: VoidIn, user: VoidUser, uow: UowDep, idem: IdempotencyKeyDep
) -> JSONResponse:
    """Super Admin / Management: void with a reason (not once CLOSED)."""
    return EcommerceReturnService(uow).void(user, return_id, payload, idem).to_response()


# --- tickets -----------------------------------------------------------------------------------
@tickets_router.get("", response_model=TicketQueueOut)
def ticket_queue(
    user: TicketViewUser,
    uow: UowDep,
    state: Literal["OPEN", "CLOSED", "ALL"] = Query(default="OPEN"),
) -> TicketQueueOut:
    """Open tickets first by SLA due time (OVERDUE flagged), or closed / all."""
    return EcommerceReturnService(uow).ticket_queue(user, state)


@tickets_router.post("/{ticket_id}/raise", response_model=ReturnOut)
def raise_ticket(
    ticket_id: UUID, user: TicketUser, uow: UowDep, idem: IdempotencyKeyDep
) -> JSONResponse:
    """The ticket was raised on the platform (records the handler and time)."""
    return EcommerceReturnService(uow).raise_ticket(user, ticket_id, idem).to_response()


@tickets_router.post("/{ticket_id}/response", response_model=ReturnOut)
def respond(
    ticket_id: UUID,
    payload: TicketResponseIn,
    user: TicketUser,
    uow: UowDep,
    idem: IdempotencyKeyDep,
) -> JSONResponse:
    """REJECTED (remark required) / CLAIM_RECEIVED (amount required) / PENDING (stays open)."""
    return EcommerceReturnService(uow).respond(user, ticket_id, payload, idem).to_response()


@tickets_router.post("/{ticket_id}/follow-up", response_model=ReturnOut)
def follow_up(
    ticket_id: UUID,
    payload: FollowUpIn,
    user: TicketUser,
    uow: UowDep,
    idem: IdempotencyKeyDep,
) -> JSONResponse:
    """DEC-76: a follow-up with the platform (note, optional next follow-up date)."""
    return EcommerceReturnService(uow).follow_up(user, ticket_id, payload, idem).to_response()


@tickets_router.post("/{ticket_id}/close", response_model=ReturnOut)
def close_ticket(
    ticket_id: UUID,
    payload: ResolutionIn,
    user: TicketUser,
    uow: UowDep,
    idem: IdempotencyKeyDep,
) -> JSONResponse:
    """Close with a final response (never while PENDING) and the portal resolution (DEC-76:
    Free Replacement / Refund + qty); the return waits for unboxing."""
    return EcommerceReturnService(uow).close_ticket(user, ticket_id, payload, idem).to_response()


# --- portal check (DEC-76) ---------------------------------------------------------------------
@tickets_router.get("/portal-checks", response_model=PortalCheckQueueOut)
def portal_checks(user: TicketViewUser, uow: UowDep) -> PortalCheckQueueOut:
    """Returns without a ticket waiting for the executive's portal check (oldest first)."""
    return EcommerceReturnService(uow).portal_queue(user)


@tickets_router.post("/portal-checks/{return_id}", response_model=ReturnOut)
def portal_check(
    return_id: UUID,
    payload: ResolutionIn,
    user: TicketUser,
    uow: UowDep,
    idem: IdempotencyKeyDep,
) -> JSONResponse:
    """What the portal shows for the order (Free Replacement / Refund) and its qty."""
    return EcommerceReturnService(uow).portal_check(user, return_id, payload, idem).to_response()
