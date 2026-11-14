"""Production hardening (docs/PRODUCTION_AUDIT.md, Phase 1, 2026-11-14).

* API docs / OpenAPI schema are not served when APP_ENV=prod.
* Liveness `/health` is served at the root and under /api/v1.
* Readiness `/health/ready` reports the database and returns 503, without connection details,
  when the database is unreachable.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app.core.config import Settings, get_settings
from app.core.db import get_session_factory
from app.main import create_app


def _client(app: Any) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
async def test_api_docs_are_not_served_in_prod(path: str) -> None:
    app = create_app(get_settings().model_copy(update={"app_env": "prod"}))
    async with _client(app) as client:
        response = await client.get(path)
    assert response.status_code == 404


@pytest.mark.parametrize("path", ["/docs", "/openapi.json"])
async def test_api_docs_are_served_outside_prod(path: str) -> None:
    app = create_app(get_settings().model_copy(update={"app_env": "local"}))
    async with _client(app) as client:
        response = await client.get(path)
    assert response.status_code == 200


@pytest.mark.parametrize("path", ["/health", "/api/v1/health"])
async def test_liveness_is_served_at_root_and_api_prefix(path: str) -> None:
    app = create_app(get_settings().model_copy(update={"app_env": "prod"}))
    async with _client(app) as client:
        response = await client.get(path)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


class _FakeSession:
    def __init__(self, error: Exception | None) -> None:
        self.error = error
        self.statements: list[str] = []

    def execute(self, statement: Any) -> None:
        self.statements.append(str(statement))
        if self.error is not None:
            raise self.error


def _factory(error: Exception | None) -> Any:
    @contextmanager
    def make() -> Iterator[_FakeSession]:
        yield _FakeSession(error)

    return make


@pytest.mark.parametrize("path", ["/health/ready", "/api/v1/health/ready"])
async def test_readiness_ok_when_database_answers(path: str) -> None:
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: _factory(None)
    async with _client(app) as client:
        response = await client.get(path)
    assert response.status_code == 200
    assert response.json()["database"] == "ok"


async def test_readiness_503_without_connection_details_when_database_fails() -> None:
    # Fake DSN (not a credential): proves connection details never reach the response.
    fake_dsn = "postgresql://rms_api:s3cret-pw@db.example.invalid:5432/postgres"
    error = OperationalError("select 1", {}, Exception(f"could not connect to {fake_dsn}"))
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: _factory(error)
    async with _client(app) as client:
        response = await client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body == {"status": "unavailable", "version": body["version"], "database": "error"}
    assert "s3cret" not in response.text and "example.invalid" not in response.text


_DB = "postgresql://rms_api.ref:pw@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"


@pytest.mark.parametrize("url", [_DB, f"{_DB}?sslmode=prefer", f"{_DB}?sslmode=disable"])
def test_prod_refuses_a_database_url_without_enforced_tls(url: str) -> None:
    with pytest.raises(ValidationError, match="sslmode"):
        Settings(app_env="prod", database_url=url, cors_origins="https://rms.example.test")  # type: ignore[call-arg]


@pytest.mark.parametrize("mode", ["require", "verify-ca", "verify-full"])
def test_prod_accepts_enforced_tls(mode: str) -> None:
    s = Settings(  # type: ignore[call-arg]
        app_env="prod",
        database_url=f"{_DB}?sslmode={mode}",
        cors_origins="https://rms.example.test",
    )
    assert s.app_env == "prod"


def test_local_does_not_require_tls() -> None:
    assert Settings(app_env="local", database_url=_DB).app_env == "local"  # type: ignore[call-arg]
