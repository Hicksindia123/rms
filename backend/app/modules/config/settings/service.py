"""Service for system settings, provisional business rules, and branding (prompt P1-08)."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from app.core.config import get_settings
from app.core.context import get_request_id
from app.core.db import UnitOfWork
from app.core.errors import NotFound
from app.core.security import CurrentUser
from app.modules.config.options import repository as options_repo
from app.modules.config.settings.schemas import (
    ContrastCheckOut,
    ContrastCheckRequest,
    LogoUploadUrlOut,
    PublicSettingsOut,
    SystemSettingOut,
    SystemSettingUpdate,
)
from app.shared.storage import Bucket, get_storage


def hex_to_relative_luminance(hex_str: str) -> float:
    """Calculate WCAG 2.1 relative luminance from a hex color string."""
    hex_clean = hex_str.lstrip("#")
    if len(hex_clean) == 3:
        hex_clean = "".join(c * 2 for c in hex_clean)
    r = int(hex_clean[0:2], 16) / 255.0
    g = int(hex_clean[2:4], 16) / 255.0
    b = int(hex_clean[4:6], 16) / 255.0

    def linearize(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r_lin = linearize(r)
    g_lin = linearize(g)
    b_lin = linearize(b)
    return 0.2126 * r_lin + 0.7152 * g_lin + 0.0722 * b_lin


def calculate_contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    l1 = hex_to_relative_luminance(fg_hex)
    l2 = hex_to_relative_luminance(bg_hex)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return round((lighter + 0.05) / (darker + 0.05), 2)


class SystemSettingsService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def list_settings(
        self, user: CurrentUser, category: str | None = None
    ) -> list[SystemSettingOut]:
        with self._uow.transaction(user.id) as session:
            if category:
                rows = session.execute(
                    text(
                        """
                        select id, key, value, category, description,
                               source_ref, created_at, updated_at
                        from public.system_settings
                        where category = :cat
                        order by source_ref asc nulls last, key asc
                        """
                    ),
                    {"cat": category},
                ).mappings()
            else:
                rows = session.execute(
                    text(
                        """
                        select id, key, value, category, description,
                               source_ref, created_at, updated_at
                        from public.system_settings
                        order by category asc, source_ref asc nulls last, key asc
                        """
                    )
                ).mappings()
            return [SystemSettingOut.model_validate(dict(r)) for r in rows]

    def get_public_settings(self) -> PublicSettingsOut:
        """Public settings endpoint readable without authentication for shell branding."""
        with self._uow.transaction() as session:
            rows = session.execute(
                text(
                    """
                    select key, value from public.system_settings
                    where key in (
                        'app_name', 'company_name', 'timezone', 'date_format',
                        'branding_primary_color', 'branding_logo_url'
                    )
                    """
                )
            ).mappings()
            data: dict[str, Any] = {}
            for r in rows:
                val = r["value"]
                data[r["key"]] = val

            return PublicSettingsOut(
                app_name=data.get("app_name", "Replacement Management System"),
                company_name=data.get("company_name"),
                timezone=data.get("timezone", "Asia/Kolkata"),
                date_format=data.get("date_format", "DD-MM-YYYY"),
                branding_primary_color=data.get("branding_primary_color", "#0f172a"),
                branding_logo_url=data.get("branding_logo_url"),
            )

    def update_setting(
        self, user: CurrentUser, key: str, payload: SystemSettingUpdate
    ) -> SystemSettingOut:
        with self._uow.transaction(user.id) as session:
            current_row = (
                session.execute(
                    text("select * from public.system_settings where key = :key"),
                    {"key": key},
                )
                .mappings()
                .first()
            )
            if not current_row:
                raise NotFound(f"Setting '{key}' not found")

            # Update value
            row = (
                session.execute(
                    text(
                        """
                    update public.system_settings
                    set value = cast(:val as jsonb), updated_at = now()
                    where key = :key
                    returning *
                    """
                    ),
                    {"key": key, "val": json.dumps(payload.value)},
                )
                .mappings()
                .first()
            )
            if not row:
                raise NotFound(f"Setting '{key}' not found after update")

            # Audit to config_change_log
            options_repo.log_config_change(
                session=session,
                entity_type="system_setting",
                entity_id=key,
                action="UPDATE_SETTING",
                before=dict(current_row),
                after=dict(row),
                reason=payload.reason or f"Updated setting {key}",
                request_id=get_request_id(),
            )

            return SystemSettingOut.model_validate(dict(row))

    def check_contrast(self, payload: ContrastCheckRequest) -> ContrastCheckOut:
        ratio = calculate_contrast_ratio(payload.foreground_color, payload.background_color)
        return ContrastCheckOut(
            contrast_ratio=ratio,
            normal_text_aa=(ratio >= 4.5),
            normal_text_aaa=(ratio >= 7.0),
            large_text_aa=(ratio >= 3.0),
            large_text_aaa=(ratio >= 4.5),
        )

    def generate_logo_upload_url(self, user: CurrentUser, extension: str) -> LogoUploadUrlOut:
        storage = get_storage()
        settings = get_settings()

        path = f"logo-{uuid4()}.{extension}"
        try:
            signed = storage.create_signed_upload_url(Bucket.BRANDING, path)
            upload_url = signed.signed_url
        except Exception:  # noqa: BLE001
            # Fallback for local environment without remote Supabase Storage server
            upload_url = f"{settings.supabase_url}/storage/v1/object/rms-branding/{path}"

        public_url = f"{settings.supabase_url}/storage/v1/object/public/rms-branding/{path}"
        return LogoUploadUrlOut(upload_url=upload_url, public_url=public_url, path=path)
