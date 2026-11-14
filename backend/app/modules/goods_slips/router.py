"""Goods slip HTTP API: Step-1 gate inward (prompt P2-02). HTTP, auth and Pydantic I/O only."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse

from app.core.db import UowDep
from app.core.idempotency import IdempotencyKeyDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.goods_slips.schemas import (
    CancelIn,
    GateEditIn,
    GateFormOut,
    GateInwardIn,
    GateInwardOut,
    GoodsSlipDetailOut,
    GsListItem,
    GsTagOut,
    LookupItem,
    PartyLookupPage,
    StatusLabel,
)
from app.modules.goods_slips.service import GateInwardService
from app.shared.pagination import Page, PageParamsDep

router = APIRouter(prefix="/gs", tags=["goods-slips"])


def get_service(uow: UowDep) -> GateInwardService:
    return GateInwardService(uow)


ServiceDep = Annotated[GateInwardService, Depends(get_service)]
ViewUser = Annotated[CurrentUser, Depends(require("goods_slips", "view"))]
CreateUser = Annotated[CurrentUser, Depends(require("goods_slips", "create"))]


@router.get("/gate-form", response_model=GateFormOut)
def get_gate_form(user: CreateUser, service: ServiceDep) -> GateFormOut:
    """Published S1_GATE_INWARD form + gate settings (phone pattern, DEC-02 auto-fill)."""
    return service.gate_form(user)


@router.get("/lookups/parties", response_model=list[LookupItem])
def lookup_parties(
    user: ViewUser,
    service: ServiceDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[LookupItem]:
    return service.lookup_parties(user, q, limit)


@router.get("/lookups/parties/by-location", response_model=PartyLookupPage)
def lookup_parties_by_location(
    user: ViewUser,
    service: ServiceDep,
    state_id: UUID,
    station_id: UUID | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> PartyLookupPage:
    """AMD-06: parties of a state + station (paged, searchable) with the DEC-35 fallback."""
    return service.lookup_parties_by_location(
        user, state_id=state_id, station_id=station_id, q=q, page=page, page_size=page_size
    )


@router.get("/lookups/statuses", response_model=list[StatusLabel])
def lookup_statuses(user: ViewUser, service: ServiceDep) -> list[StatusLabel]:
    """AMD-08: goods-slip status labels (GS_STATUS option set; codes never change)."""
    return service.status_labels(user)


@router.get("/lookups/states", response_model=list[LookupItem])
def lookup_states(user: ViewUser, service: ServiceDep) -> list[LookupItem]:
    return service.lookup_states(user)


@router.get("/lookups/stations", response_model=list[LookupItem])
def lookup_stations(
    user: ViewUser, service: ServiceDep, state_id: UUID | None = None
) -> list[LookupItem]:
    return service.lookup_stations(user, state_id)


@router.get("/lookups/transporters", response_model=list[LookupItem])
def lookup_transporters(
    user: ViewUser,
    service: ServiceDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[LookupItem]:
    return service.lookup_transporters(user, q, limit)


@router.post(
    "",
    response_model=GateInwardOut,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "Idempotency conflict or system guard"}},
)
def create_goods_slip(
    payload: GateInwardIn,
    user: CreateUser,
    idem: IdempotencyKeyDep,
    service: ServiceDep,
) -> JSONResponse:
    """Step-1: create a GS at the gate (S1_GATE PERFORM; `Idempotency-Key` required)."""
    return service.create(user, payload, idem).to_response()


@router.get("", response_model=Page[GsListItem])
def list_goods_slips(
    user: ViewUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
    params: PageParamsDep,
    status_: Annotated[list[str] | None, Query(alias="status")] = None,
    party_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: Annotated[str | None, Query(max_length=100, description="GS no. or party")] = None,
    flag: Annotated[list[str] | None, Query(description="e.g. missing_documentation")] = None,
) -> Page[GsListItem]:
    return service.list_goods_slips(
        user,
        perms,
        params,
        statuses=status_,
        party_id=party_id,
        date_from=date_from,
        date_to=date_to,
        q=q,
        flags=flag or [],
    )


@router.get("/{gs_id}", response_model=GoodsSlipDetailOut)
def get_goods_slip(
    gs_id: UUID, user: ViewUser, perms: EffectivePermissionsDep, service: ServiceDep
) -> GoodsSlipDetailOut:
    return service.get_detail(user, perms, gs_id)


@router.patch("/{gs_id}/gate", response_model=GoodsSlipDetailOut)
def edit_gate_details(
    gs_id: UUID,
    payload: GateEditIn,
    user: ViewUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
) -> GoodsSlipDetailOut:
    """Edit gate details while GATE_CREATED (creator or admin; audited with reason)."""
    return service.edit_gate(user, perms, gs_id, payload)


@router.post("/{gs_id}/cancel", response_model=GoodsSlipDetailOut)
def cancel_goods_slip(
    gs_id: UUID,
    payload: CancelIn,
    user: ViewUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
) -> GoodsSlipDetailOut:
    """Admin-only cancellation before unboxing completes (reason mandatory)."""
    return service.cancel(user, perms, gs_id, payload.reason)


@router.get("/{gs_id}/tag", response_model=GsTagOut)
def get_gs_tag(
    gs_id: UUID, user: ViewUser, perms: EffectivePermissionsDep, service: ServiceDep
) -> GsTagOut:
    """BR-02: GS_TAG print data, one label per box."""
    return service.tag(user, perms, gs_id)
