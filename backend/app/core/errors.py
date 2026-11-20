"""Exception hierarchy and the standard error envelope (master plan §9.7, CLAUDE.md rule j).

Every error response has the shape {"error": {"code", "message", "details", "request_id"}}.
Stack traces are only included (in `details`) when APP_ENV=local.
"""

import re
import traceback
from collections.abc import Mapping
from typing import Any, ClassVar

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import DBAPIError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import get_request_id
from app.core.guard_events import record_guard_event

log = structlog.get_logger("rms.errors")

_GUARD_CODE = re.compile(r"^G-(0[1-9]|1[0-9]|2[0-2])$")
_GUARD_IN_DB_MESSAGE = re.compile(r"\b(G-(?:0[1-9]|1[0-9]|2[0-2]))\b")  # G-22: Phase 8
# Coded DB rule errors that are not numbered guards; returned as 409 with that code.
# STORE_MAPPING_MISSING: rms_private.assert_store_for_products (DEC-61, Phase P1).
_CODED_DB_MESSAGE = re.compile(r"\b(STORE_MAPPING_MISSING):")


class DomainError(Exception):
    """Base class for expected, client-facing errors. Subclasses fix the HTTP status."""

    status_code: ClassVar[int] = 400
    default_code: ClassVar[str] = "BAD_REQUEST"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: Mapping[str, Any] | list[Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code
        self.details = details


class ValidationFailed(DomainError):
    status_code = 422
    default_code = "VALIDATION_FAILED"


class Unauthenticated(DomainError):
    status_code = 401
    default_code = "UNAUTHENTICATED"


class PermissionDenied(DomainError):
    status_code = 403
    default_code = "PERMISSION_DENIED"


class NotFound(DomainError):
    status_code = 404
    default_code = "NOT_FOUND"


class Conflict(DomainError):
    status_code = 409
    default_code = "CONFLICT"


class IdempotencyConflict(Conflict):
    default_code = "IDEMPOTENCY_CONFLICT"


class SystemGuardViolation(Conflict):
    """A non-bypassable system guard G-01…G-18 (§4.2) rejected the action.

    No role, permission override, setting or Super Admin status can suppress this error: nothing in
    the permission layer catches it, and the error code is always the guard id.
    """

    def __init__(
        self,
        guard: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        if not _GUARD_CODE.fullmatch(guard):
            raise ValueError(f"unknown system guard code: {guard!r}")
        super().__init__(message, code=guard, details={"guard": guard, **(details or {})})
        self.guard = guard


# Name used by the permission layer and services (P1-03 spec): the same class.
SystemGuardError = SystemGuardViolation


class SystemGuardUnmet(SystemGuardViolation):
    """A system guard whose precondition the request has not met yet (422, e.g. G-02 evidence
    missing). Same non-bypassable semantics as SystemGuardViolation; `details` say what is missing.
    """

    status_code = 422


class ServiceUnavailable(DomainError):
    status_code = 503
    default_code = "SERVICE_UNAVAILABLE"


def enforce_guard(condition: bool, guard: str, message: str) -> None:
    """Raise SystemGuardViolation unless `condition` holds. Deliberately takes no user argument."""
    if not condition:
        raise SystemGuardViolation(guard, message)


def error_body(
    code: str,
    message: str,
    *,
    details: Any = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": jsonable_encoder(details) if details is not None else None,
            "request_id": request_id,
        }
    }


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    details: Any = None,
    request_id: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_body(code, message, details=details, request_id=request_id),
        headers=dict(headers) if headers else None,
    )


def internal_error_details(exc: BaseException, *, app_env: str) -> dict[str, Any] | None:
    """Stack traces only ever leave the process when APP_ENV=local."""
    if app_env != "local":
        return None
    return {
        "exception": f"{type(exc).__name__}: {exc}",
        "traceback": traceback.format_exception(exc),
    }


_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    406: "NOT_ACCEPTABLE",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_FAILED",
    429: "RATE_LIMITED",
}


def _validation_details(exc: RequestValidationError) -> list[dict[str, Any]]:
    # `input` is dropped on purpose: it can echo request bodies (passwords, tokens) back.
    return [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors()
    ]


def register_exception_handlers(app: FastAPI, *, app_env: str) -> None:
    async def handle_domain(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, DomainError)  # noqa: S101 - registered for DomainError only
        emit = log.warning if exc.status_code >= 500 else log.info
        emit("domain_error", code=exc.code, status=exc.status_code, error_type=type(exc).__name__)
        if isinstance(exc, SystemGuardViolation):
            # P4-01: every rejected guard attempt is counted on the Admin dashboard.
            await run_in_threadpool(record_guard_event, request, exc.guard, "SERVICE")
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return error_response(
            exc.status_code,
            exc.code,
            exc.message,
            details=exc.details,
            request_id=get_request_id(request),
            headers=headers,
        )

    async def handle_validation(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, RequestValidationError)  # noqa: S101
        return error_response(
            422,
            "VALIDATION_FAILED",
            "Request validation failed",
            details=_validation_details(exc),
            request_id=get_request_id(request),
        )

    async def handle_http(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, StarletteHTTPException)  # noqa: S101
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ").title()
        return error_response(
            exc.status_code,
            code,
            message,
            request_id=get_request_id(request),
            headers=exc.headers,
        )

    async def handle_rate_limit(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, RateLimitExceeded)  # noqa: S101
        log.warning("rate_limited", limit=str(exc.detail))
        return error_response(
            429,
            "RATE_LIMITED",
            "Too many requests; please retry later",
            details={"limit": str(exc.detail)},
            request_id=get_request_id(request),
        )

    async def handle_db(request: Request, exc: Exception) -> JSONResponse:
        """DB-level guard triggers raise messages that name the guard (e.g. 'G-18: …').

        They are surfaced as the same SystemGuardViolation envelope the services use. Any other
        database error is unexpected: it is logged with its stack and returned as a 500.
        """
        assert isinstance(exc, DBAPIError)  # noqa: S101
        orig = str(getattr(exc, "orig", exc))
        match = _GUARD_IN_DB_MESSAGE.search(orig)
        if match:
            guard = match.group(1)
            log.info("system_guard_db", guard=guard)
            await run_in_threadpool(record_guard_event, request, guard, "DB")
            first_line = orig.splitlines()[0] if orig else guard
            return error_response(
                409,
                guard,
                first_line,
                details={"guard": guard},
                request_id=get_request_id(request),
            )
        coded = _CODED_DB_MESSAGE.search(orig)
        if coded:
            log.info("db_rule_rejected", code=coded.group(1))
            return error_response(
                409,
                coded.group(1),
                orig.splitlines()[0],
                request_id=get_request_id(request),
            )
        log.error("database_error", exc_info=exc)
        return error_response(
            500,
            "INTERNAL_ERROR",
            "An unexpected database error occurred",
            details=internal_error_details(exc, app_env=app_env),
            request_id=get_request_id(request),
        )

    app.add_exception_handler(DomainError, handle_domain)
    app.add_exception_handler(RequestValidationError, handle_validation)
    app.add_exception_handler(StarletteHTTPException, handle_http)
    app.add_exception_handler(RateLimitExceeded, handle_rate_limit)
    app.add_exception_handler(DBAPIError, handle_db)
