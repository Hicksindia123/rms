"""Dashboards HTTP API (prompt P4-01, master plan §10 "Dashboard widgets", §11)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status

from app.core.db import UowDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser
from app.modules.dashboards.schemas import (
    DashboardOut,
    LayoutIn,
    RoleLayoutOut,
    WidgetCatalogueItem,
    WidgetDataOut,
)
from app.modules.dashboards.service import DashboardService

router = APIRouter(tags=["dashboards"])

ViewUser = Annotated[CurrentUser, Depends(require("dashboards", "view"))]
ConfigureUser = Annotated[CurrentUser, Depends(require("dashboards", "configure"))]
ROLE_CODE = r"^[A-Z][A-Z0-9_]{1,59}$"
RoleCodePath = Annotated[str, Path(pattern=ROLE_CODE)]


def get_service(uow: UowDep) -> DashboardService:
    return DashboardService(uow)


ServiceDep = Annotated[DashboardService, Depends(get_service)]


@router.get("/dashboard", response_model=DashboardOut)
def my_dashboard(
    user: ViewUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
    role: Annotated[str | None, Query(pattern=ROLE_CODE, description="One of your roles")] = None,
) -> DashboardOut:
    """The landing dashboard of your primary role (or `role`); widgets you may not see are
    removed."""
    return service.dashboard(user, perms, role)


@router.get("/dashboard/widgets/{code}", response_model=WidgetDataOut)
def widget_data(
    code: str,
    request: Request,
    response: Response,
    user: ViewUser,
    perms: EffectivePermissionsDep,
    service: ServiceDep,
) -> WidgetDataOut:
    """One widget's data. Query parameters follow the widget's parameter schema (unknown → 422).
    403 `WIDGET_FORBIDDEN` when you lack the widget's permission."""
    out = service.widget_data(user, perms, code, dict(request.query_params))
    response.headers["Cache-Control"] = "private, no-store"
    return out


@router.get("/admin/dashboard-widgets", response_model=list[WidgetCatalogueItem])
def widget_catalogue(user: ConfigureUser, service: ServiceDep) -> list[WidgetCatalogueItem]:
    """Every widget with its permission requirement and parameter schema."""
    return service.catalogue(user)


@router.get("/admin/dashboard-layouts", response_model=list[RoleLayoutOut])
def list_layouts(user: ConfigureUser, service: ServiceDep) -> list[RoleLayoutOut]:
    return service.list_layouts(user)


@router.get("/admin/dashboard-layouts/{role_code}", response_model=RoleLayoutOut)
def get_layout(
    role_code: RoleCodePath,
    user: ConfigureUser,
    service: ServiceDep,
) -> RoleLayoutOut:
    return service.get_layout(user, role_code)


@router.put("/admin/dashboard-layouts/{role_code}", response_model=RoleLayoutOut)
def put_layout(
    role_code: RoleCodePath,
    payload: LayoutIn,
    user: ConfigureUser,
    service: ServiceDep,
) -> RoleLayoutOut:
    """Replace the role's ordered widget list (writes config_change_log)."""
    return service.put_layout(user, role_code, payload)


@router.delete("/admin/dashboard-layouts/{role_code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_layout(
    role_code: RoleCodePath,
    user: ConfigureUser,
    service: ServiceDep,
    reason: Annotated[str | None, Query(max_length=500)] = None,
) -> Response:
    """Remove the role's layout (its users then see an explicit empty dashboard)."""
    service.delete_layout(user, role_code, reason)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
