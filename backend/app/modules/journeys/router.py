"""Role journey HTTP API (change plan Phase 10, AMD-22)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.core.db import UowDep
from app.core.permissions import EffectivePermissionsDep, require
from app.core.security import CurrentUser, CurrentUserDep
from app.modules.journeys.schemas import (
    JourneyConfigOut,
    JourneyQueueOut,
    JourneyStepOut,
    JourneyStepUpdate,
    MyJourneyOut,
    RoleJourneyOut,
    RoleJourneyUpdate,
)
from app.modules.journeys.service import JourneyService

router = APIRouter(tags=["journeys"])

CodePath = Annotated[str, Path(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=40)]


def get_service(uow: UowDep) -> JourneyService:
    return JourneyService(uow)


ServiceDep = Annotated[JourneyService, Depends(get_service)]


@router.get("/me/journey", response_model=MyJourneyOut)
def my_journey(
    user: CurrentUserDep, perms: EffectivePermissionsDep, service: ServiceDep
) -> MyJourneyOut:
    """The caller's menu in journey order, with the count and next GS per step."""
    return service.my_journey(user, perms)


@router.get("/me/journey/{code}", response_model=JourneyQueueOut)
def my_journey_queue(
    code: CodePath, user: CurrentUserDep, perms: EffectivePermissionsDep, service: ServiceDep
) -> JourneyQueueOut:
    """The goods slips waiting at one of the caller's journey steps, oldest first."""
    return service.queue(user, perms, code)


@router.get("/config/journeys", response_model=JourneyConfigOut)
def journey_config(
    user: Annotated[CurrentUser, Depends(require("config", "view"))], service: ServiceDep
) -> JourneyConfigOut:
    return service.config(user)


@router.put("/config/journeys/roles/{role_code}", response_model=RoleJourneyOut)
def set_role_journey(
    role_code: CodePath,
    payload: RoleJourneyUpdate,
    user: Annotated[CurrentUser, Depends(require("config", "configure"))],
    service: ServiceDep,
) -> RoleJourneyOut:
    return service.set_role_journey(user, role_code, payload)


@router.put("/config/journeys/steps/{code}", response_model=JourneyStepOut)
def update_journey_step(
    code: CodePath,
    payload: JourneyStepUpdate,
    user: Annotated[CurrentUser, Depends(require("config", "configure"))],
    service: ServiceDep,
) -> JourneyStepOut:
    return service.update_step(user, code, payload)
