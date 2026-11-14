"""Record rejected system-guard attempts (prompt P4-01: Admin "guard violations attempted").

Called by the exception handlers (app/core/errors.py) for every G-01…G-18 rejection, whether it was
raised by a service (SystemGuardViolation) or by a DB trigger. The request's own transaction has
already rolled back, so the event is written in a separate short transaction.

Recording is best-effort by design: a failure to write the event is logged with context at ERROR
and the client still receives the original guard error (the guard itself is never weakened).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from app.core.context import get_request_id
from app.core.db import get_session_factory

log = structlog.get_logger("rms.guards")

_INSERT = text(
    """
    insert into public.system_guard_events
           (guard_code, source, http_method, path, user_id, request_id)
    values (:g, :src, :m, :p, :u, :rid)
    """
)


def _session_factory(request: Request) -> sessionmaker[Session]:
    # Honour the test override of get_session_factory (rolled-back test connection).
    provider: Any = request.app.dependency_overrides.get(get_session_factory, get_session_factory)
    factory: sessionmaker[Session] = provider()
    return factory


def record_guard_event(request: Request, guard: str, source: str) -> None:
    user_id = getattr(request.state, "user_id", None)
    params = {
        "g": guard,
        "src": source,
        "m": request.method,
        "p": request.url.path[:300],
        "u": user_id if isinstance(user_id, UUID) else None,
        "rid": get_request_id(request),
    }
    try:
        with _session_factory(request)() as session, session.begin():
            session.execute(_INSERT, params)
    except SQLAlchemyError as exc:
        log.error(
            "guard_event_not_recorded",
            guard=guard,
            source=source,
            path=params["p"],
            error=str(exc),
            exc_info=exc,
        )
