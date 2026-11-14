"""FastAPI router for number series configuration and preview (prompt P1-08)."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.db import UowDep
from app.core.permissions import require
from app.core.security import CurrentUser
from app.modules.config.numbering.schemas import (
    NumberPreviewOut,
    NumberSeriesOut,
    NumberSeriesUpdate,
)
from app.modules.config.numbering.service import NumberSeriesService

router = APIRouter(prefix="/config/numbering", tags=["config-numbering"])


def get_service(uow: UowDep) -> NumberSeriesService:
    return NumberSeriesService(uow)


ServiceDep = Annotated[NumberSeriesService, Depends(get_service)]


@router.get("", response_model=list[NumberSeriesOut])
def list_number_series(
    user: Annotated[CurrentUser, Depends(require("config", "view"))],
    service: ServiceDep,
) -> list[NumberSeriesOut]:
    return service.list_series(user)


@router.get("/{code}", response_model=NumberSeriesOut)
def get_number_series(
    code: str,
    user: Annotated[CurrentUser, Depends(require("config", "view"))],
    service: ServiceDep,
) -> NumberSeriesOut:
    return service.get_series(user, code)


@router.put("/{code}", response_model=NumberSeriesOut)
def update_number_series(
    code: str,
    payload: NumberSeriesUpdate,
    user: Annotated[CurrentUser, Depends(require("config", "configure"))],
    service: ServiceDep,
) -> NumberSeriesOut:
    return service.update_series(user, code, payload)


@router.get("/{code}/preview", response_model=NumberPreviewOut)
def preview_number_series(
    code: str,
    user: Annotated[CurrentUser, Depends(require("config", "view"))],
    service: ServiceDep,
    count: Annotated[int, Query(ge=1, le=10)] = 3,
    on_date: Annotated[
        date | None, Query(description="Target date for preview (YYYY-MM-DD)")
    ] = None,
) -> NumberPreviewOut:
    return service.preview_numbers(user, code, count=count, on_date=on_date)
