"""FastAPI router for system settings, provisional business rules, and branding (prompt P1-08)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.db import UowDep
from app.core.permissions import require
from app.core.security import CurrentUser
from app.modules.config.settings.schemas import (
    ContrastCheckOut,
    ContrastCheckRequest,
    LogoUploadUrlOut,
    LogoUploadUrlRequest,
    PublicSettingsOut,
    SystemSettingOut,
    SystemSettingUpdate,
)
from app.modules.config.settings.service import SystemSettingsService

router = APIRouter(prefix="/config/settings", tags=["config-settings"])


def get_service(uow: UowDep) -> SystemSettingsService:
    return SystemSettingsService(uow)


ServiceDep = Annotated[SystemSettingsService, Depends(get_service)]


@router.get("/public", response_model=PublicSettingsOut)
def get_public_settings(
    service: ServiceDep,
) -> PublicSettingsOut:
    """Public settings (app name, branding color, logo, date format) required by UI shell."""
    return service.get_public_settings()


@router.get("", response_model=list[SystemSettingOut])
def list_settings(
    user: Annotated[CurrentUser, Depends(require("config", "view"))],
    service: ServiceDep,
    category: Annotated[
        str | None, Query(description="Filter by category (e.g. provisional, branding, general)")
    ] = None,
) -> list[SystemSettingOut]:
    return service.list_settings(user, category=category)


@router.put("/{key}", response_model=SystemSettingOut)
def update_setting(
    key: str,
    payload: SystemSettingUpdate,
    user: Annotated[CurrentUser, Depends(require("config", "configure"))],
    service: ServiceDep,
) -> SystemSettingOut:
    return service.update_setting(user, key, payload)


@router.post("/branding/contrast-check", response_model=ContrastCheckOut)
def check_contrast(
    payload: ContrastCheckRequest,
    user: Annotated[CurrentUser, Depends(require("config", "view"))],
    service: ServiceDep,
) -> ContrastCheckOut:
    return service.check_contrast(payload)


@router.post("/branding/upload-url", response_model=LogoUploadUrlOut)
def get_logo_upload_url(
    payload: LogoUploadUrlRequest,
    user: Annotated[CurrentUser, Depends(require("config", "configure"))],
    service: ServiceDep,
) -> LogoUploadUrlOut:
    return service.generate_logo_upload_url(user, payload.extension)
