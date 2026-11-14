"""FastAPI router for configuration audit history and system guards (prompt P1-08)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.db import UowDep
from app.core.permissions import require
from app.core.security import CurrentUser
from app.modules.config.history.schemas import (
    ConfigHistoryResponse,
    SystemGuardItem,
)
from app.modules.config.history.service import ConfigHistoryService

router = APIRouter(tags=["config-history"])


def get_service(uow: UowDep) -> ConfigHistoryService:
    return ConfigHistoryService(uow)


ServiceDep = Annotated[ConfigHistoryService, Depends(get_service)]


@router.get("/config/history", response_model=ConfigHistoryResponse)
@router.get("/admin/config-history", response_model=ConfigHistoryResponse)
def get_config_history(
    user: Annotated[CurrentUser, Depends(require("config", "view"))],
    service: ServiceDep,
    entity_type: Annotated[
        str | None,
        Query(
            description="Filter by entity type (e.g. option_item, form_version, workflow_version)"
        ),
    ] = None,
    entity_id: Annotated[str | None, Query(description="Filter by entity ID")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ConfigHistoryResponse:
    return service.get_history(
        user,
        entity_type=entity_type,
        entity_id=entity_id,
        page=page,
        page_size=page_size,
    )


@router.get("/config/system-guards", response_model=list[SystemGuardItem])
@router.get("/admin/system-guards", response_model=list[SystemGuardItem])
def get_system_guards(
    user: Annotated[CurrentUser, Depends(require("config", "view"))],
    service: ServiceDep,
) -> list[SystemGuardItem]:
    """Returns the immutable system guards catalogue (G-01..G-18 from master plan §4.2)."""
    return service.get_system_guards()
