"""Router for option sets and option items (master plan §3.2, §8.3, §10, prompt P1-07)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.db import UowDep
from app.core.permissions import require
from app.core.security import CurrentUser
from app.modules.config.options.schemas import (
    OptionItemCreate,
    OptionItemOut,
    OptionItemUpdate,
    OptionSetOut,
    OptionUsageOut,
)
from app.modules.config.options.service import OptionService

router = APIRouter(prefix="/config", tags=["config-options"])


def get_service(uow: UowDep) -> OptionService:
    return OptionService(uow)


ServiceDep = Annotated[OptionService, Depends(get_service)]


@router.get("/option-sets", response_model=list[OptionSetOut])
def list_option_sets(
    user: Annotated[CurrentUser, Depends(require("config", "view"))],
    service: ServiceDep,
    include_inactive: bool = True,
) -> list[OptionSetOut]:
    return service.list_option_sets(user, include_inactive=include_inactive)


@router.get("/option-sets/{set_id_or_code}", response_model=OptionSetOut)
def get_option_set(
    set_id_or_code: str,
    user: Annotated[CurrentUser, Depends(require("config", "view"))],
    service: ServiceDep,
) -> OptionSetOut:
    return service.get_option_set(user, set_id_or_code)


@router.get("/option-items/{code}/usage", response_model=OptionUsageOut)
def get_option_item_usage(
    code: str,
    user: Annotated[CurrentUser, Depends(require("config", "view"))],
    service: ServiceDep,
) -> OptionUsageOut:
    return service.get_option_item_usage(user, code)


@router.post(
    "/option-sets/{option_set_id}/items",
    status_code=201,
    response_model=OptionItemOut,
)
def create_option_item(
    option_set_id: UUID,
    payload: OptionItemCreate,
    user: Annotated[CurrentUser, Depends(require("config", "configure"))],
    service: ServiceDep,
) -> OptionItemOut:
    return service.create_item(user, option_set_id, payload)


@router.put(
    "/option-sets/{option_set_id}/items/{item_id}",
    response_model=OptionItemOut,
)
def update_option_item(
    option_set_id: UUID,
    item_id: UUID,
    payload: OptionItemUpdate,
    user: Annotated[CurrentUser, Depends(require("config", "configure"))],
    service: ServiceDep,
) -> OptionItemOut:
    return service.update_item(user, option_set_id, item_id, payload)
