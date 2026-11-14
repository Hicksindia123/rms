"""Workflow task inbox HTTP API ("My Work", prompt P2-02)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.db import UowDep
from app.core.security import CurrentUserDep
from app.modules.tasks.schemas import MyTaskOut
from app.modules.tasks.service import TaskService
from app.shared.pagination import Page, PageParamsDep

router = APIRouter(prefix="/tasks", tags=["tasks"])


def get_service(uow: UowDep) -> TaskService:
    return TaskService(uow)


@router.get("/mine", response_model=Page[MyTaskOut])
def my_tasks(
    user: CurrentUserDep,
    service: Annotated[TaskService, Depends(get_service)],
    params: PageParamsDep,
    status: Annotated[str, Query(max_length=20)] = "OPEN",
    step_code: Annotated[str | None, Query(max_length=40)] = None,
) -> Page[MyTaskOut]:
    """Tasks for the caller's roles (or assigned directly); a Super Admin sees every task."""
    return service.my_tasks(user, params, status=status, step_code=step_code)
