from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app import __version__
from app.core.config import Settings, get_settings
from app.core.db import get_session_factory
from app.modules.health.schemas import HealthResponse, ReadinessResponse

log = structlog.get_logger("rms.health")

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    """Liveness probe. Does not touch the database."""
    return HealthResponse(status="ok", version=__version__, env=settings.app_env)


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
def readiness(
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> JSONResponse:
    """Readiness probe (production audit 2026-11-14): the API can reach its database.

    Returns 503 when the database is unreachable. It never returns connection details: the
    error is logged server-side only.
    """
    try:
        with session_factory() as session:
            session.execute(text("select 1"))
    except SQLAlchemyError as exc:
        log.error("readiness_db_failed", error_type=type(exc).__name__)
        body = ReadinessResponse(status="unavailable", version=__version__, database="error")
        return JSONResponse(status_code=503, content=body.model_dump())
    body = ReadinessResponse(status="ok", version=__version__, database="ok")
    return JSONResponse(status_code=200, content=body.model_dump())
