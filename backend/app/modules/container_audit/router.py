"""Daily DMT Container Audit HTTP API (prompt P2-06, BR-18, DEC-08)."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.db import UowDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.container_audit import service
from app.modules.container_audit.schemas import (
    CalendarSummaryOut,
    ConfirmAuditIn,
    SaveLinesIn,
    TodayAuditOut,
)

router = APIRouter(prefix="/container-audits", tags=["container-audit"])

ViewUser = Annotated[CurrentUser, Depends(require("container_audit", "view"))]
EditUser = Annotated[CurrentUser, Depends(require("container_audit", "edit"))]


@router.get("/today", response_model=TodayAuditOut)
def get_today_audit(
    user: ViewUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> TodayAuditOut:
    with uow.transaction(user.id) as session:
        return service.get_today_audit(session, user, perms)


@router.get("/{audit_date}", response_model=TodayAuditOut)
def get_audit_for_date(
    audit_date: date,
    user: ViewUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> TodayAuditOut:
    """The register for a chosen (past) date: late entries are counted against that day."""
    with uow.transaction(user.id) as session:
        return service.get_audit_for_date(session, audit_date, user, perms)


@router.put("/{audit_date}/lines", response_model=TodayAuditOut)
def save_audit_lines(
    audit_date: date,
    payload: SaveLinesIn,
    user: EditUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> TodayAuditOut:
    with uow.transaction(user.id) as session:
        return service.save_audit_lines(session, audit_date, payload, user, perms)


@router.post("/{audit_date}/confirm", response_model=TodayAuditOut)
def confirm_audit(
    audit_date: date,
    payload: ConfirmAuditIn,
    user: EditUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
) -> TodayAuditOut:
    with uow.transaction(user.id) as session:
        return service.confirm_audit(session, audit_date, payload, user, perms)


@router.get("", response_model=CalendarSummaryOut)
def get_audit_calendar(
    user: ViewUser,
    perms: EffectivePermissionsDep,
    uow: UowDep,
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
) -> CalendarSummaryOut:
    with uow.transaction(user.id) as session:
        return service.get_calendar(session, from_date, to_date, user, perms)
