"""Transfer slips HTTP API (Phase P5, DEC-65). HTTP, auth, permissions and Pydantic I/O only.

Permissions: transfer_slips.view (lists, detail, PDF), transfer_slips.create (generate, send an
edit request: Replacement Manager), itemization.configure (resolve an edit request: Super Admin /
Management), transfer_slips.approve (P6, DEC-66: acknowledge / report a discrepancy: the users of
the slip's Intermediate Store; the service and the DB check the store). Store users see only their
own store's slips (service). The GS view needs goods_slips.view + the GS visibility check.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response

from app.core.db import UowDep
from app.core.idempotency import IdempotencyKeyDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.transfer_slips.schemas import (
    AcknowledgeIn,
    DiscrepancyIn,
    EditRequestIn,
    EditRequestOut,
    GenerateIn,
    GenerateOut,
    GsTransferSlipsOut,
    PendingGsOut,
    ResolveEditRequestIn,
    SlipDetailOut,
    SlipPage,
)
from app.modules.transfer_slips.service import TransferSlipService

router = APIRouter(prefix="/transfer-slips", tags=["transfer-slips"])
gs_router = APIRouter(prefix="/gs", tags=["transfer-slips"])


def get_service(uow: UowDep) -> TransferSlipService:
    return TransferSlipService(uow)


ServiceDep = Annotated[TransferSlipService, Depends(get_service)]
ViewUser = Annotated[CurrentUser, Depends(require("transfer_slips", "view"))]
CreateUser = Annotated[CurrentUser, Depends(require("transfer_slips", "create"))]
AckUser = Annotated[CurrentUser, Depends(require("transfer_slips", "approve"))]
ConfigureUser = Annotated[CurrentUser, Depends(require("itemization", "configure"))]
GsViewUser = Annotated[CurrentUser, Depends(require("goods_slips", "view"))]


@router.get("/pending", response_model=list[PendingGsOut])
def pending(
    user: ViewUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
    party_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    store_id: UUID | None = None,
) -> list[PendingGsOut]:
    """Goods slips whose categorisation is locked and that wait for their transfer slips."""
    return service.pending(
        user, perms, party_id=party_id, date_from=date_from, date_to=date_to, store_id=store_id
    )


@router.post("", response_model=GenerateOut, status_code=201)
def generate(
    payload: GenerateIn,
    user: CreateUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """One slip per Intermediate Store for the selected goods slips (one transaction, G-16)."""
    return service.generate(user, perms, payload, idem).to_response()


@router.get("", response_model=SlipPage)
def list_slips(
    user: ViewUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
    status: Literal["GENERATED", "ACKNOWLEDGED", "VOIDED"] | None = None,
    store_id: UUID | None = None,
    q: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> SlipPage:
    return service.list_slips(
        user, perms, status=status, store_id=store_id, q=q, page=page, page_size=page_size
    )


@router.get("/edit-requests", response_model=list[EditRequestOut])
def edit_requests(
    user: ViewUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
    status: Literal["OPEN", "EDITED", "REJECTED"] | None = "OPEN",
) -> list[EditRequestOut]:
    return service.edit_requests(user, perms, status=status)


@router.post("/edit-requests/{request_id}/resolve", response_model=EditRequestOut)
def resolve_edit_request(
    request_id: UUID,
    payload: ResolveEditRequestIn,
    user: ConfigureUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """Management / Super Admin: the GS was edited (P4 rules), or the request is rejected."""
    return service.resolve_edit(user, perms, request_id, payload, idem).to_response()


@router.get("/{slip_id}", response_model=SlipDetailOut)
def detail(
    slip_id: UUID, user: ViewUser, perms: EffectivePermissionsDep, service: ServiceDep
) -> SlipDetailOut:
    return service.detail(user, perms, slip_id)


@router.post("/{slip_id}/acknowledge", response_model=SlipDetailOut)
def acknowledge(
    slip_id: UUID,
    payload: AcknowledgeIn,
    user: AckUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """DEC-66: the slip's store acknowledges receipt in full (stock TRANSIT -> store, G-16)."""
    return service.acknowledge(user, perms, slip_id, payload, idem).to_response()


@router.post("/{slip_id}/discrepancies", response_model=SlipDetailOut, status_code=201)
def report_discrepancy(
    slip_id: UUID,
    payload: DiscrepancyIn,
    user: AckUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """DEC-66 (Q13): remark only; alerts the RM + Management; the slip stays open."""
    return service.report_discrepancy(user, perms, slip_id, payload, idem).to_response()


@router.get("/{slip_id}/pdf", response_class=Response)
def pdf(
    slip_id: UUID, user: ViewUser, perms: EffectivePermissionsDep, service: ServiceDep
) -> Response:
    """A4 PDF of the slip (Q20), HICKS logo from the branding config (Q26)."""
    filename, data = service.pdf(user, perms, slip_id)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@gs_router.get("/{gs_id}/transfer-slips", response_model=GsTransferSlipsOut)
def for_gs(
    gs_id: UUID, user: GsViewUser, perms: EffectivePermissionsDep, service: ServiceDep
) -> GsTransferSlipsOut:
    """Slips and edit requests of one goods slip."""
    return service.for_gs(user, perms, gs_id)


@gs_router.post("/{gs_id}/edit-requests", response_model=EditRequestOut, status_code=201)
def request_edit(
    gs_id: UUID,
    payload: EditRequestIn,
    user: CreateUser,
    perms: EffectivePermissionsDep,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """Replacement Manager: "Send Edit Request" (reason) to Management + Super Admin."""
    return service.request_edit(user, perms, gs_id, payload, idem).to_response()
