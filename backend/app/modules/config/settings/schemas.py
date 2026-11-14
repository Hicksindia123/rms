"""Pydantic schemas for system settings, provisional business rules, and branding (prompt P1-08)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SystemSettingOut(BaseModel):
    id: UUID
    key: str
    value: Any
    category: str
    description: str | None = None
    source_ref: str | None = None
    created_at: datetime
    updated_at: datetime


class SystemSettingUpdate(BaseModel):
    value: Any
    reason: str | None = Field(None, description="Reason for configuration change")


class PublicSettingsOut(BaseModel):
    app_name: str = "Replacement Management System"
    company_name: str | None = None
    timezone: str = "Asia/Kolkata"
    date_format: str = "DD-MM-YYYY"
    branding_primary_color: str = "#0f172a"
    branding_logo_url: str | None = None


class ContrastCheckRequest(BaseModel):
    foreground_color: str = Field(..., pattern=r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
    background_color: str = Field(..., pattern=r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class ContrastCheckOut(BaseModel):
    contrast_ratio: float
    normal_text_aa: bool
    normal_text_aaa: bool
    large_text_aa: bool
    large_text_aaa: bool


class LogoUploadUrlRequest(BaseModel):
    extension: str = Field("png", pattern=r"^(png|jpg|jpeg|svg|webp)$")


class LogoUploadUrlOut(BaseModel):
    upload_url: str
    public_url: str
    path: str
