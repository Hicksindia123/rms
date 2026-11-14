"""HTTP hardening (master plan §9.7): security headers, CORS and the slowapi limiter."""

from fastapi import FastAPI
from slowapi import Limiter
from slowapi.middleware import SlowAPIASGIMiddleware
from slowapi.util import get_remote_address
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings
from app.core.context import REQUEST_ID_HEADER
from app.core.idempotency import IDEMPOTENCY_HEADER, REPLAYED_HEADER

# Endpoints opt in with `@limiter.limit("…")` (auth-adjacent and upload-URL endpoints, §7).
# No global default limit is applied.
limiter = Limiter(key_func=get_remote_address, headers_enabled=False)

# Swagger UI / ReDoc load scripts from a CDN, so they get a relaxed policy; the API gets none.
_DOCS_PATHS = ("/docs", "/redoc")
_API_CSP = b"default-src 'none'; frame-ancestors 'none'"


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        is_docs = path.startswith(_DOCS_PATHS)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers += [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cross-origin-opener-policy", b"same-origin"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                ]
                if not is_docs:
                    headers.append((b"content-security-policy", _API_CSP))
                    headers.append((b"cache-control", b"no-store"))
                if self.hsts:
                    headers.append(
                        (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
                    )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


def install_http_middleware(app: FastAPI, settings: Settings) -> None:
    """Order (outermost first): request context → security headers → CORS → rate limiter."""
    limiter.enabled = settings.rate_limit_enabled
    app.state.limiter = limiter
    app.add_middleware(SlowAPIASGIMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,  # bearer tokens, no cookies
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", IDEMPOTENCY_HEADER, REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER, REPLAYED_HEADER],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.app_env == "prod")
    app.add_middleware(GZipMiddleware, minimum_size=1000)
