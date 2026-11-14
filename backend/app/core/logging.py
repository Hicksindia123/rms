"""Structured logging (structlog) and the request-id / access-log middleware (master plan §7).

* JSON lines in non-local environments, a console renderer when APP_ENV=local.
* stdlib loggers (uvicorn, sqlalchemy) are routed through the same processors.
* Tokens are never logged: headers are not logged at all, and a redaction processor masks any
  event field whose name looks sensitive (authorization, token, password, secret, key…).
"""

import json
import logging
import sys
import time
from collections.abc import MutableMapping
from typing import Any

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings
from app.core.context import REQUEST_ID_HEADER, accept_request_id, request_id_var
from app.core.errors import error_body, internal_error_details

_SENSITIVE_PARTS = ("authorization", "token", "password", "secret", "apikey", "api_key", "cookie")
REDACTED = "[REDACTED]"


def redact_sensitive(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        lowered = key.lower()
        if any(part in lowered for part in _SENSITIVE_PARTS):
            event_dict[key] = REDACTED
    return event_dict


def configure_logging(settings: Settings) -> None:
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_sensitive,
    ]
    renderer: Any = (
        structlog.dev.ConsoleRenderer()
        if settings.app_env == "local"
        else structlog.processors.JSONRenderer()
    )
    if settings.app_env != "local":
        shared.append(structlog.processors.format_exc_info)

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)

    for name in ("uvicorn", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = []
        uv_logger.propagate = True
    # RequestContextMiddleware writes the access log (with user id and duration); uvicorn's own
    # access log would duplicate it and includes query strings.
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False
    access.disabled = True


access_log = structlog.get_logger("rms.access")
error_log = structlog.get_logger("rms.errors")


class RequestContextMiddleware:
    """Pure ASGI middleware: request id, access log, and last-resort 500 envelope.

    * Accepts a well-formed incoming X-Request-ID or generates one, binds it to the log context and
      returns it in the response header.
    * Logs one access line per request: method, path (no query string), status, duration, user id.
    * Any exception that escaped the routers is logged with its stack and answered with the
      standard envelope (500 INTERNAL_ERROR); stack traces are only included when APP_ENV=local.
    """

    def __init__(self, app: ASGIApp, *, app_env: str) -> None:
        self.app = app
        self.app_env = app_env

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = None
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                incoming = value.decode("latin-1")
                break
        request_id = accept_request_id(incoming)
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        token = request_id_var.set(request_id)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        started = time.perf_counter()
        status_holder = {"status": 500, "started": False}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                status_holder["started"] = True
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.lower().encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            error_log.error("unhandled_exception", path=scope.get("path"), exc_info=exc)
            if status_holder["started"]:
                raise
            await self._send_500(send_wrapper, request_id, exc)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            user_id = state.get("user_id")
            access_log.info(
                "request",
                method=scope.get("method"),
                path=scope.get("path"),
                status=status_holder["status"],
                duration_ms=duration_ms,
                user_id=str(user_id) if user_id else None,
            )
            structlog.contextvars.clear_contextvars()
            request_id_var.reset(token)

    async def _send_500(self, send: Send, request_id: str, exc: Exception) -> None:
        body = json.dumps(
            error_body(
                "INTERNAL_ERROR",
                "An unexpected error occurred",
                details=internal_error_details(exc, app_env=self.app_env),
                request_id=request_id,
            )
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 500,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
