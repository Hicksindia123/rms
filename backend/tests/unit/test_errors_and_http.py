"""Error envelope, request-id round trip, security headers and rate-limit wiring (no DB)."""

from typing import Annotated

import pytest
from fastapi import APIRouter, FastAPI, Query, Request
from httpx import ASGITransport, AsyncClient
from psycopg.errors import RaiseException
from sqlalchemy.exc import DBAPIError

from app.core.config import Settings
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.middleware import limiter
from app.main import create_app

router = APIRouter(prefix="/api/v1/t")


@router.get("/not-found")
def not_found() -> None:
    raise NotFound("Goods slip not found", details={"id": "x"})


@router.get("/conflict")
def conflict() -> None:
    raise Conflict("Already closed", code="GS_CLOSED")


@router.get("/validation")
def validation(n: Annotated[int, Query(ge=1)]) -> dict[str, int]:
    return {"n": n}


@router.get("/domain-validation")
def domain_validation() -> None:
    raise ValidationFailed("Quantity mismatch", details=[{"field": "qty"}])


@router.get("/boom")
def boom() -> None:
    raise RuntimeError("secret internals")


@router.get("/db-guard")
def db_guard() -> None:
    raise DBAPIError("update ...", {}, RaiseException("G-18: published workflow v1 is immutable"))


@router.get("/limited")
@limiter.limit("2/minute")
def limited(request: Request) -> dict[str, bool]:
    return {"ok": True}


def make_client(app_env: str = "test") -> AsyncClient:
    settings = Settings(app_env=app_env)  # type: ignore[call-arg]
    app: FastAPI = create_app(settings)
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def client() -> AsyncClient:
    async with make_client() as c:
        yield c  # type: ignore[misc]


def _envelope_ok(res_json: dict, code: str) -> dict:  # type: ignore[type-arg]
    assert set(res_json) == {"error"}
    err = res_json["error"]
    assert set(err) == {"code", "message", "details", "request_id"}
    assert err["code"] == code
    return err  # type: ignore[no-any-return]


async def test_domain_errors_use_the_envelope(client: AsyncClient) -> None:
    res = await client.get("/api/v1/t/not-found")
    assert res.status_code == 404
    err = _envelope_ok(res.json(), "NOT_FOUND")
    assert err["details"] == {"id": "x"}
    assert err["request_id"] == res.headers["X-Request-ID"]

    res = await client.get("/api/v1/t/conflict")
    assert res.status_code == 409
    _envelope_ok(res.json(), "GS_CLOSED")

    res = await client.get("/api/v1/t/domain-validation")
    assert res.status_code == 422
    _envelope_ok(res.json(), "VALIDATION_FAILED")


async def test_request_validation_maps_to_422_envelope(client: AsyncClient) -> None:
    res = await client.get("/api/v1/t/validation", params={"n": 0})
    assert res.status_code == 422
    err = _envelope_ok(res.json(), "VALIDATION_FAILED")
    assert err["details"][0]["loc"] == ["query", "n"]
    assert "input" not in err["details"][0]


async def test_unknown_route_uses_envelope(client: AsyncClient) -> None:
    res = await client.get("/api/v1/nope")
    assert res.status_code == 404
    _envelope_ok(res.json(), "NOT_FOUND")


async def test_unhandled_exception_is_500_without_stack_outside_local() -> None:
    async with make_client("test") as c:
        res = await c.get("/api/v1/t/boom")
    assert res.status_code == 500
    err = _envelope_ok(res.json(), "INTERNAL_ERROR")
    assert err["details"] is None
    assert "secret internals" not in res.text
    assert err["request_id"] == res.headers["X-Request-ID"]


async def test_unhandled_exception_includes_stack_only_in_local() -> None:
    async with make_client("local") as c:
        res = await c.get("/api/v1/t/boom")
    assert res.status_code == 500
    err = _envelope_ok(res.json(), "INTERNAL_ERROR")
    assert "RuntimeError: secret internals" in err["details"]["exception"]


async def test_db_guard_message_maps_to_guard_code(client: AsyncClient) -> None:
    res = await client.get("/api/v1/t/db-guard")
    assert res.status_code == 409
    err = _envelope_ok(res.json(), "G-18")
    assert err["details"] == {"guard": "G-18"}


async def test_request_id_is_generated(client: AsyncClient) -> None:
    res = await client.get("/api/v1/health")
    rid = res.headers["X-Request-ID"]
    assert len(rid) == 32 and int(rid, 16) >= 0


async def test_request_id_round_trip(client: AsyncClient) -> None:
    res = await client.get("/api/v1/t/not-found", headers={"X-Request-ID": "abc-123.DEF"})
    assert res.headers["X-Request-ID"] == "abc-123.DEF"
    assert res.json()["error"]["request_id"] == "abc-123.DEF"


async def test_malformed_request_id_is_replaced(client: AsyncClient) -> None:
    res = await client.get("/api/v1/health", headers={"X-Request-ID": "bad id\twith spaces"})
    assert res.headers["X-Request-ID"] != "bad id\twith spaces"
    assert len(res.headers["X-Request-ID"]) == 32


async def test_security_headers(client: AsyncClient) -> None:
    res = await client.get("/api/v1/health")
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"
    assert res.headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'none'" in res.headers["Content-Security-Policy"]
    assert res.headers["Cache-Control"] == "no-store"
    assert "Strict-Transport-Security" not in res.headers  # prod only


async def test_cors_allows_configured_origin_only(client: AsyncClient) -> None:
    preflight = {
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,idempotency-key",
    }
    ok = await client.options("/api/v1/health", headers=preflight)
    assert ok.status_code == 200
    assert ok.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert "X-Request-ID" in ok.headers

    bad = await client.options(
        "/api/v1/health", headers={**preflight, "Origin": "https://evil.test"}
    )
    assert "Access-Control-Allow-Origin" not in bad.headers


async def test_rate_limit_returns_429_envelope(client: AsyncClient) -> None:
    limiter.reset()
    codes = [(await client.get("/api/v1/t/limited")).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    res = await client.get("/api/v1/t/limited")
    _envelope_ok(res.json(), "RATE_LIMITED")
    limiter.reset()
