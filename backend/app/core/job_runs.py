"""Record background job runs in public.job_runs (prompt P4-01: Admin "failed jobs" widget).

Written in its own transaction after the job's transaction finished (committed or rolled back), so
a failed job is still recorded. A failure to record is logged with context at ERROR; it never stops
the scheduler and never hides the job's own error (which the worker logs separately).
"""

from __future__ import annotations

from datetime import datetime

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import UnitOfWork, get_session_factory

log = structlog.get_logger("rms.worker")

_INSERT = text(
    """
    insert into public.job_runs (job_code, status, started_at, result_count, error_message)
    values (:job, :status, :started, :n, :err)
    """
)


def record_job_run(
    job_code: str,
    *,
    started_at: datetime,
    status: str,
    result_count: int | None,
    error_message: str | None,
) -> None:
    try:
        with UnitOfWork(get_session_factory()).transaction() as session:
            session.execute(
                _INSERT,
                {
                    "job": job_code,
                    "status": status,
                    "started": started_at,
                    "n": result_count,
                    "err": error_message[:2000] if error_message else None,
                },
            )
    except SQLAlchemyError as exc:
        log.error("job_run_not_recorded", job=job_code, status=status, error=str(exc), exc_info=exc)
