"""FastAPI router for Department Routing, Receiving and G-20 Reconciliation.
(Change plan 2026-11-12 Phase 6; AMD-10, AMD-14, AMD-15; DEC-42, DEC-43; Guard G-20;
gap plan G2 / DEC-55: RM routing plan -> Store Manager issue).

Permissions (T4 — the real `department_routing` actions):
  view    queues, state, documents, reconciliation
  create  RM plans the routing / cancels an un-issued plan line (DEC-55)
  approve Store Manager issues planned lines to a department and prints the DIN (DEC-55)
  edit    receive goods back from a department (DEC-42 role check in the service)
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
    CancelPlanLineIn,
    CreateDepartmentReceiptIn,
    CreateRoutingPlanIn,
    DepartmentLegOut,
    DepartmentOutcomeHeadOut,
    DepartmentReceiptOut,
    DepartmentRoutingOut,
    GsReconciliationOut,
    IssueQueueGroupOut,
    ReceivingQueueItemOut,
    RmRoutingQueueItemOut,
    RoutingPlanLineOut,
    RoutingPlanOut,
    StoreIssueIn,
)
from app.modules.department_routing.service import department_routing_service

router = APIRouter(prefix="/department-routing", tags=["department-routing"])

ViewUser = Annotated[CurrentUser, Depends(require("department_routing", "view"))]
CreateUser = Annotated[CurrentUser, Depends(require("department_routing", "create"))]
EditUser = Annotated[CurrentUser, Depends(require("department_routing", "edit"))]
IssueUser = Annotated[CurrentUser, Depends(require("department_routing", "approve"))]


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
    """Routing state for a GS: items, resolved departments, condition buckets with the qty still
    free to plan, store quantities and the routing plan lines (DEC-55)."""
    with uow.transaction(user.id) as session:
        return department_routing_service.get_gs_routing_state(session, gs_id)


@router.get("/gs/{gs_id}/plan", response_model=list[RoutingPlanLineOut])
def get_gs_plan_lines(
    gs_id: UUID,
    user: ViewUser,
    uow: UowDep,
) -> list[RoutingPlanLineOut]:
    """DEC-55: every routing plan line of a GS (planned, issued, no-work, cancelled)."""
    with uow.transaction(user.id) as session:
        return department_routing_service.get_plan_lines(session, gs_id)


@router.post("/plan", response_model=RoutingPlanOut)
def plan_routing(
    payload: CreateRoutingPlanIn,
    user: CreateUser,
    uow: UowDep,
    idem: IdempotencyKeyDep,
) -> JSONResponse:
    """DEC-55: RM plans the routing per item + condition. No stock moves; the Store Manager is
    alerted to issue. `Idempotency-Key` required (G-16) so a double click never plans twice."""
    return department_routing_service.plan_routing(
        uow, actor=user, payload=payload, idem=idem
    ).to_response()


@router.post("/plan-lines/{plan_line_id}/cancel", response_model=RoutingPlanLineOut)
def cancel_plan_line(
    plan_line_id: UUID,
    payload: CancelPlanLineIn,
    user: CreateUser,
    uow: UowDep,
) -> RoutingPlanLineOut:
    """DEC-55: RM withdraws a planned (not yet issued) or no-work plan line, with a reason."""
    return department_routing_service.cancel_plan_line(
        uow, actor=user, plan_line_id=plan_line_id, reason=payload.reason
    )


@router.get("/issue-queue", response_model=list[IssueQueueGroupOut])
def list_issue_queue(
    user: ViewUser,
    uow: UowDep,
) -> list[IssueQueueGroupOut]:
    """DEC-55: planned lines waiting for the Store issue, one group per GS + department."""
    with uow.transaction(user.id) as session:
        return department_routing_service.list_issue_queue(session)


@router.post("/issue", response_model=DepartmentRoutingOut)
def issue_to_department(
    payload: StoreIssueIn,
    user: IssueUser,
    uow: UowDep,
    idem: IdempotencyKeyDep,
) -> JSONResponse:
    """DEC-55: Store Manager issues planned lines to one department (DIN); stock moves from the
    Intermediate Store to the department's location. Stock-moving: `Idempotency-Key` (G-16)."""
    return department_routing_service.issue_to_department(
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
