"""Supabase Auth (GoTrue) admin API client (P1-05 user administration).

* Backend only: uses the service-role key (CLAUDE.md rule i). Besides Storage, this is the only
  place the key is used at request time.
* Nothing returned to API callers comes from GoTrue error bodies; they are logged server-side.
* Passwords are never logged.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol
from uuid import UUID

import httpx
import structlog

from app.core.config import Settings, get_settings
from app.core.errors import Conflict, ServiceUnavailable, ValidationFailed

log = structlog.get_logger("rms.auth_admin")

# Supabase bans for this long when an account is deactivated ("forever" in practice); the backend
# also rejects every request of an inactive profile immediately (403 ACCOUNT_INACTIVE).
DEACTIVATED_BAN_DURATION = "876000h"


@dataclass(frozen=True, slots=True)
class CreatedAuthUser:
    id: UUID


class AuthAdmin(Protocol):
    def create_user(
        self, *, email: str, password: str, user_metadata: dict[str, Any]
    ) -> CreatedAuthUser: ...

    def set_password(self, user_id: UUID, password: str) -> None: ...

    def set_banned(self, user_id: UUID, banned: bool) -> None: ...


class SupabaseAuthAdmin:
    def __init__(self, settings: Settings) -> None:
        if settings.supabase_service_role_key is None:
            raise ServiceUnavailable(
                "User administration is not configured (SUPABASE_SERVICE_ROLE_KEY)",
                code="AUTH_ADMIN_DISABLED",
            )
        key = settings.supabase_service_role_key.get_secret_value()
        self._base = f"{settings.supabase_url}/auth/v1/admin/users"
        self._headers = {"apikey": key, "Authorization": f"Bearer {key}"}

    def _request(self, method: str, url: str, op: str, json: dict[str, Any]) -> httpx.Response:
        try:
            with httpx.Client(timeout=15) as client:
                return client.request(method, url, headers=self._headers, json=json)
        except httpx.HTTPError as exc:
            log.error("auth_admin_unreachable", op=op, error_type=type(exc).__name__)
            raise ServiceUnavailable(
                "The authentication service is unavailable", code="AUTH_UNAVAILABLE"
            ) from exc

    @staticmethod
    def _fail(op: str, res: httpx.Response) -> Exception:
        body = res.text[:500]
        log.error("auth_admin_error", op=op, status=res.status_code, body=body)
        lowered = body.lower()
        if res.status_code == 422 and ("already" in lowered and "regist" in lowered):
            return Conflict("A user with this email already exists", code="EMAIL_TAKEN")
        if res.status_code in (400, 422) and "password" in lowered:
            return ValidationFailed(
                "The password does not meet the sign-in service's requirements",
                code="WEAK_PASSWORD",
            )
        return ServiceUnavailable("The authentication service rejected the request")

    def create_user(
        self, *, email: str, password: str, user_metadata: dict[str, Any]
    ) -> CreatedAuthUser:
        payload = {
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": user_metadata,
            # The profile trigger creates the profile ACTIVE only for admin-created users.
            "app_metadata": {"provider": "email", "providers": ["email"], "rms_activate": True},
        }
        res = self._request("POST", self._base, "create_user", payload)
        if res.status_code not in (200, 201):
            raise self._fail("create_user", res)
        return CreatedAuthUser(id=UUID(str(res.json()["id"])))

    def set_password(self, user_id: UUID, password: str) -> None:
        res = self._request(
            "PUT", f"{self._base}/{user_id}", "set_password", {"password": password}
        )
        if res.status_code != 200:
            raise self._fail("set_password", res)

    def set_banned(self, user_id: UUID, banned: bool) -> None:
        duration = DEACTIVATED_BAN_DURATION if banned else "none"
        res = self._request(
            "PUT", f"{self._base}/{user_id}", "set_banned", {"ban_duration": duration}
        )
        if res.status_code != 200:
            raise self._fail("set_banned", res)


@lru_cache
def _default_auth_admin() -> SupabaseAuthAdmin:
    return SupabaseAuthAdmin(get_settings())


def get_auth_admin() -> AuthAdmin:
    """FastAPI dependency (lazy; tests override it with a fake)."""
    return _default_auth_admin()
