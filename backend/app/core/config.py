"""Application settings from the environment / backend/.env (master plan §12.4).

Required values have no default: a missing one raises at startup (fail fast) instead of failing on
the first request. Secrets are `SecretStr`, so they never appear in reprs or logs (rule i).
"""

from functools import lru_cache
from typing import Annotated, Literal, Self
from urllib.parse import parse_qs, urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

AppEnv = Literal["local", "test", "dev", "prod"]

# Environments where the HS256 shared-secret fallback and stack traces in error details are allowed.
LOCAL_ENVS: frozenset[str] = frozenset({"local", "test"})

# libpq sslmodes that refuse an unencrypted connection (required when APP_ENV=prod).
_SECURE_SSLMODES: frozenset[str] = frozenset({"require", "verify-ca", "verify-full"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: AppEnv = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    tz: str = "Asia/Kolkata"
    port: int = Field(default=8000, alias="PORT")

    # --- Database (rms_api role, §9.4) ---------------------------------------------------------
    database_url: SecretStr
    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=20, ge=0)
    db_pool_timeout_seconds: float = Field(default=30, gt=0)
    db_connect_timeout_seconds: int = Field(default=10, ge=1)
    db_pool_recycle_seconds: int = Field(default=1800, ge=-1)
    db_statement_timeout_ms: int = Field(default=30_000, ge=0)

    # --- Supabase -------------------------------------------------------------------------------
    supabase_url: str
    # Backend only (storage.py and the users admin service). Never exposed to the frontend.
    supabase_service_role_key: SecretStr | None = None
    # HS256 fallback; honoured only when APP_ENV is local/test.
    supabase_jwt_secret: SecretStr | None = None
    # Defaults to {SUPABASE_URL}/auth/v1/.well-known/jwks.json when empty.
    supabase_jwks_url: str | None = None
    # Defaults to {SUPABASE_URL}/auth/v1 (the `iss` claim Supabase Auth writes) when empty.
    supabase_jwt_issuer: str | None = None
    supabase_jwt_audience: str = "authenticated"
    jwks_cache_ttl_seconds: int = Field(default=600, ge=30)

    # --- HTTP -----------------------------------------------------------------------------------
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    rate_limit_enabled: bool = True
    page_size_default: int = Field(default=25, ge=1)
    page_size_max: int = Field(default=100, ge=1)

    # --- Storage --------------------------------------------------------------------------------
    signed_url_ttl_seconds: int = Field(default=600, ge=1)

    # --- Optional email channel (Phase 4) -------------------------------------------------------
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_use_tls: bool = True
    # Implicit TLS (SMTPS, usually port 465) instead of STARTTLS.
    smtp_ssl: bool = False
    smtp_timeout_seconds: float = Field(default=15, gt=0)
    # Base URL of the web app, used for deep links in emails (e.g. http://localhost:5173).
    app_public_url: str = "http://localhost:5173"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [o.strip().rstrip("/") for o in value.split(",") if o.strip()]
        return value

    @field_validator("supabase_url")
    @classmethod
    def _strip_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("SUPABASE_URL must be an http(s) URL")
        return value

    @field_validator(
        "supabase_jwks_url",
        "supabase_jwt_issuer",
        "smtp_host",
        "smtp_user",
        "smtp_from",
        mode="before",
    )
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator(
        "supabase_service_role_key", "supabase_jwt_secret", "smtp_password", mode="before"
    )
    @classmethod
    def _empty_secret_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value().strip()
        if not raw:
            raise ValueError("DATABASE_URL is required")
        # Accept plain postgres URLs (as printed by `supabase start`) and pin the psycopg 3 driver.
        for prefix in ("postgresql://", "postgres://"):
            if raw.startswith(prefix):
                raw = "postgresql+psycopg://" + raw[len(prefix) :]
        if not raw.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must be a postgresql:// URL")
        return SecretStr(raw)

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        if self.page_size_default > self.page_size_max:
            raise ValueError("PAGE_SIZE_DEFAULT must not exceed PAGE_SIZE_MAX")
        if self.app_env == "prod" and "*" in self.cors_origins:
            raise ValueError("CORS_ORIGINS must be an explicit allow-list in prod")
        if self.app_env == "prod":
            # Production audit Phase 2: never fall back to plaintext (libpq default is "prefer").
            query = parse_qs(urlsplit(self.database_url.get_secret_value()).query)
            if query.get("sslmode", [""])[-1] not in _SECURE_SSLMODES:
                raise ValueError(
                    "DATABASE_URL must set sslmode=require (or verify-ca / verify-full) in prod"
                )
        return self

    @property
    def is_local(self) -> bool:
        return self.app_env in LOCAL_ENVS

    @property
    def jwks_url(self) -> str:
        return self.supabase_jwks_url or f"{self.supabase_url}/auth/v1/.well-known/jwks.json"

    @property
    def jwt_issuer(self) -> str:
        return self.supabase_jwt_issuer or f"{self.supabase_url}/auth/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # required values come from the environment
