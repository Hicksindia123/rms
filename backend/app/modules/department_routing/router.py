"""FastAPI router for Department Routing, Receiving and G-20 Reconciliation.
(Change plan 2026-11-12 Phase 6; AMD-10, AMD-14, AMD-15; DEC-42, DEC-43; Guard G-20).
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.core.db import UowDep
from app.core.errors import ValidationFailed
from app.core.idempotency import IdempotencyKeyDep
from app.core.permissions import require
from app.core.security import CurrentUser
from app.modules.department_routing.schemas import (
    CreateDepartmentReceiptIn,
    CreateDepartmentRoutingIn,
    DepartmentLegOut,
    DepartmentOutcomeHeadOut,
    DepartmentReceiptOut,
    DepartmentRoutingOut,
    GsReconciliationOut,
    ReceivingQueueItemOut,
    RmRoutingQueueItemOut,
)
from app.modules.department_routing.service import department_routing_service

router = APIRouter(prefix="/department-routing", tags=["department-routing"])

ViewUser = Annotated[CurrentUser, Depends(require("department_routing", "view"))]
CreateUser = Annotated[CurrentUser, Depends(require("department_routing", "create"))]
EditUser = Annotated[CurrentUser, Depends(require("department_routing", "edit"))]


@router.get("/outcome-heads", response_model=list[DepartmentOutcomeHeadOut])
def list_outcome_heads(
    user: ViewUser,
    uow: UowDep,
    active_only: bool = Query(default=True),
) -> list[DepartmentOutcomeHeadOut]:
    """List available department receipt outcome heads."""
    with uow.transaction(user.id) as session:
        return department_routing_service.list_outcome_heads(session, active_only=active_only)


@router.get("/queue", response_model=list[RmRoutingQueueItemOut])
def get_rm_routing_queue(
    user: ViewUser,
    uow: UowDep,
) -> list[RmRoutingQueueItemOut]:
    """AMD-10: List all Goods Slips held at intermediate store awaiting or in department routing."""
    with uow.transaction(user.id) as session:
        return department_routing_service.get_rm_routing_queue(session)


@router.get("/gs/{gs_id}/state", response_model=dict[str, Any])
def get_gs_routing_state(
    gs_id: UUID,
    user: ViewUser,
    uow: UowDep,
) -> dict[str, Any]:
    """Routing state for a GS: items, resolved departments, buckets and available store qty."""
    with uow.transaction(user.id) as session:
        return department_routing_service.get_gs_routing_state(session, gs_id)


@router.post("/dispatch", response_model=DepartmentRoutingOut)
def dispatch_department_routing(
    payload: CreateDepartmentRoutingIn,
    user: CreateUser,
    uow: UowDep,
    idem: IdempotencyKeyDep,
) -> JSONResponse:
    """AMD-10 / DEC-42: RM dispatches items to departments allowed by the product's resolved
    profile. Stock-moving command: `Idempotency-Key` required (G-16)."""
    return department_routing_service.dispatch_department_routing(
        uow, actor=user, payload=payload, idem=idem
    ).to_response()


@router.get("/receiving-queue", response_model=list[ReceivingQueueItemOut])
def list_receiving_queue(
    user: ViewUser,
    uow: UowDep,
) -> list[ReceivingQueueItemOut]:
    """AMD-14 / DEC-42: List routings pending department receipt."""
    with uow.transaction(user.id) as session:
        return department_routing_service.list_receiving_queue(session)


@router.get("/{routing_id}", response_model=DepartmentRoutingOut)
def get_routing(
    routing_id: UUID,
    user: ViewUser,
    uow: UowDep,
) -> DepartmentRoutingOut:
    """Get single routing document detail (for viewing or printing DIN)."""
    with uow.transaction(user.id) as session:
        return department_routing_service.get_routing(session, routing_id)


@router.post("/{routing_id}/receive", response_model=DepartmentReceiptOut)
def receive_department_routing(
    routing_id: UUID,
    payload: CreateDepartmentReceiptIn,
    user: EditUser,
    uow: UowDep,
    idem: IdempotencyKeyDep,
) -> JSONResponse:
    """AMD-14 / DEC-42 / DEC-43: Receive department routing lines back into outcome heads.
    Stock-moving command: `Idempotency-Key` required (G-16)."""
    if payload.routing_id != routing_id:
        raise ValidationFailed(
            "routing_id in the body does not match the URL", code="ROUTING_ID_MISMATCH"
        )
    return department_routing_service.receive_department_routing(
        uow, actor=user, payload=payload, idem=idem
    ).to_response()


@router.get("/gs/{gs_id}/reconciliation", response_model=GsReconciliationOut)
def get_gs_reconciliation(
    gs_id: UUID,
    user: ViewUser,
    uow: UowDep,
) -> GsReconciliationOut:
    """AMD-15 / Guard G-20: Return per-item quantity conservation reconciliation data."""
    with uow.transaction(user.id) as session:
        return department_routing_service.get_gs_reconciliation(session, gs_id)


@router.get("/gs/{gs_id}/legs", response_model=list[DepartmentLegOut])
def get_gs_department_legs(
    gs_id: UUID,
    user: ViewUser,
    uow: UowDep,
) -> list[DepartmentLegOut]:
    """AMD-10: GS timeline legs showing dispatched, received, and pending per department."""
    with uow.transaction(user.id) as session:
        return department_routing_service.get_gs_department_legs(session, gs_id)
