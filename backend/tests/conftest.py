"""Shared test configuration.

The environment is fixed here, BEFORE the app is imported, so `get_settings()` (cached) sees test
values: APP_ENV=test, a per-run random HS256 secret (the "local JWT secret" the JWT factory signs
with), and the local Supabase URLs. backend/.env is not needed to run the tests.

Integration tests use TEST_DATABASE_URL (a superuser / postgres URL of a LOCAL database that has
the supabase/migrations applied). See tests/integration/conftest.py.
"""

import os
import secrets
import time
import uuid
from collections.abc import Callable
from typing import Any

import jwt
import pytest

DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres"
TEST_JWT_SECRET = os.environ.setdefault("RMS_TEST_JWT_SECRET", secrets.token_urlsafe(48))

os.environ["APP_ENV"] = "test"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["SUPABASE_JWT_SECRET"] = TEST_JWT_SECRET
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:54321")
os.environ.setdefault("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
os.environ.setdefault("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
# The storage helper is exercised with a fake client; never a real key in tests.
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = ""

from app.core.config import Settings, get_settings  # noqa: E402

JwtFactory = Callable[..., str]


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
def make_token(settings: Settings) -> JwtFactory:
    """JWT factory: signs Supabase-shaped access tokens with the local (test) JWT secret."""

    def factory(
        user_id: uuid.UUID | str,
        *,
        email: str | None = None,
        expires_in: int = 3600,
        audience: str | None = None,
        issuer: str | None = None,
        secret: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "sub": str(user_id),
            "aud": audience or settings.supabase_jwt_audience,
            "iss": issuer or settings.jwt_issuer,
            "iat": now,
            "exp": now + expires_in,
            "role": "authenticated",
            "email": email,
            "session_id": str(uuid.uuid4()),
            **(extra or {}),
        }
        return jwt.encode(claims, secret or TEST_JWT_SECRET, algorithm="HS256")

    return factory
