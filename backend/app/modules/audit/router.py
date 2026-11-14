"""Router for Audit Explorer, GS Activity Timeline and User Activity (P4-04)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.db import UowDep
from app.core.permissions import EffectivePermissions, get_effective_permissions
from app.core.security import CurrentUserDep
from app.modules.audit.schemas import (
    AuditLogResponse,
    GsActivityResponse,
    UserActivityResponse,
)
from app.modules.audit.service import AuditService

router = APIRouter(tags=["audit"])


def get_service(uow: UowDep) -> AuditService:
    return AuditService(uow)


ServiceDep = Annotated[AuditService, Depends(get_service)]
PermsDep = Annotated[EffectivePermissions, Depends(get_effective_permissions)]


@router.get("/audit", response_model=AuditLogResponse)
def list_audit_log(
    user: CurrentUserDep,
    perms: PermsDep,
    service: ServiceDep,
    table_name: Annotated[str | None, Query(max_length=60)] = None,
    row_id: Annotated[str | None, Query(max_length=60)] = None,
    actor_id: Annotated[UUID | None, Query()] = None,
    action: Annotated[Literal["INSERT", "UPDATE", "DELETE"] | None, Query()] = None,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
    request_id: Annotated[str | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> AuditLogResponse:
    """Retrieve audit log records with filtering (requires audit.view or Super Admin)."""
    return service.list_audit_log(
        user,
        perms,
        table_name=table_name,
        row_id=row_id,
        actor_id=actor_id,
        action=action,
        date_from=date_from,
        date_to=date_to,
        request_id=request_id,
        limit=limit,
        offset=offset,
    )


@router.get("/audit/tables", response_model=list[str])
def list_audit_tables(
    user: CurrentUserDep,
    perms: PermsDep,
    service: ServiceDep,
) -> list[str]:
    """List all distinct tables recorded in the audit log."""
    return service.get_distinct_tables(user, perms)


@router.get("/audit/export")
def export_audit_log(
    user: CurrentUserDep,
    perms: PermsDep,
    service: ServiceDep,
    table_name: Annotated[str | None, Query(max_length=60)] = None,
    row_id: Annotated[str | None, Query(max_length=60)] = None,
    actor_id: Annotated[UUID | None, Query()] = None,
    action: Annotated[Literal["INSERT", "UPDATE", "DELETE"] | None, Query()] = None,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
    request_id: Annotated[str | None, Query(max_length=120)] = None,
) -> StreamingResponse:
    """Export audit log as CSV stream (requires audit.export or Super Admin)."""
    stream = service.export_audit_log_csv(
        user,
        perms,
        table_name=table_name,
        row_id=row_id,
        actor_id=actor_id,
        action=action,
        date_from=date_from,
        date_to=date_to,
        request_id=request_id,
    )
    filename = f"audit_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        stream,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/gs/{gs_id}/activity", response_model=GsActivityResponse)
def get_gs_activity_timeline(
    gs_id: UUID,
    user: CurrentUserDep,
    perms: PermsDep,
    service: ServiceDep,
    category: Annotated[
        Literal["STATUS", "STOCK", "DOCUMENT", "COMMERCIAL", "NOTIFICATION", "AUDIT"] | None,
        Query(description="Filter by activity category"),
    ] = None,
) -> GsActivityResponse:
    """Unified activity timeline for a GS (Status, Stock, Docs, Commercial, Notifications)."""
    return service.get_gs_activity_timeline(user, perms, gs_id, category_filter=category)


@router.get("/users/{user_id}/activity", response_model=UserActivityResponse)
def list_user_activity(
    user_id: UUID,
    user: CurrentUserDep,
    perms: PermsDep,
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> UserActivityResponse:
    """Retrieve activity log for a user (sign-ins, session actions)."""
    return service.list_user_activity(user, perms, user_id, limit=limit, offset=offset)
