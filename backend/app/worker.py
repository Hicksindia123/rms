"""Background worker (`uv run python -m app.worker`), started by scripts/dev.(ps1|sh).

Jobs:
* `cleanup_pending_uploads` (P2-03, every 30 min): deletes PENDING_UPLOAD attachments older than
  `pending_upload_retention_hours` (default 24 h) and their Storage objects.
* `container_audit_evening_alert` (P2-06, daily at 18:00 IST): if today's DMT container audit
  is not confirmed, dispatches notification to Inward Verifier and RM.
* `container_audit_morning_missed` (P2-06, daily at 09:00 IST): marks past unconfirmed
  audits as MISSED and dispatches high-priority alert.
* `inventory_segregation_check` (P3-04, daily at 02:00 IST): records a NIGHTLY segregation check
  run (BR-30, G-04/G-05/G-08/G-09/G-12) and alerts Super Admins + `segregation_alert_roles` on
  any violation.
* `notification_outbox` (P4-03, every 15 s): dispatches outbox events whose inline dispatch failed
  (retry with backoff, FAILED after `notification_max_attempts`).
* `notification_email` (P4-03, every 30 s): sends PENDING email deliveries over SMTP (env only);
  without SMTP they are recorded as SKIPPED / SMTP_NOT_CONFIGURED.
* `party_email` (Phase 9 / AMD-20, every 30 s): delivers QUEUED party emails (auto-send, or a
  send whose inline attempt failed) with backoff; FAILED after `notification_max_attempts`.
* `notification_digest` (P4-03, hourly): sends the daily digest after `notification_digest_hour`.
* `sla_escalation_check` (P4-03 / DEC-30, every 5 min): escalates OPEN workflow tasks past their
  SLA once per active escalation level.

Each job opens its own Unit of Work (one transaction, actor = system). A failing run is logged with
its stack and retried at the next interval; it never stops the scheduler. Every run (succeeded or
failed) is recorded in public.job_runs (P4-01, Admin dashboard).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import UTC, datetime

import structlog
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.db import UnitOfWork, dispose_engine, get_session_factory
from app.core.errors import DomainError
from app.core.job_runs import record_job_run
from app.core.logging import configure_logging
from app.modules.attachments.service import AttachmentService
from app.modules.container_audit import service as container_audit_service
from app.modules.inventory import service as inventory_service
from app.modules.notifications import service as notification_service
from app.modules.party_notifications import email_service as party_email_service
from app.shared.storage import get_storage

log = structlog.get_logger("rms.worker")

CLEANUP_INTERVAL_MINUTES = 30
OUTBOX_INTERVAL_SECONDS = 15
EMAIL_INTERVAL_SECONDS = 30
ESCALATION_INTERVAL_MINUTES = 5


def _tracked(job: str, run: Callable[[], int]) -> int:
    """Run one job, log a failure with its stack, and record the run in job_runs (P4-01)."""
    started = datetime.now(UTC)
    try:
        count = run()
    except (DomainError, SQLAlchemyError) as exc:
        log.error("job_failed", job=job, error=str(exc), exc_info=exc)
        record_job_run(
            job, started_at=started, status="FAILED", result_count=None, error_message=str(exc)
        )
        return 0
    record_job_run(
        job, started_at=started, status="SUCCEEDED", result_count=count, error_message=None
    )
    return count


def cleanup_pending_uploads() -> int:
    service = AttachmentService(UnitOfWork(get_session_factory()), get_storage())
    return _tracked("cleanup_pending_uploads", service.cleanup_stale_pending)


def container_audit_evening_alert() -> int:
    def run() -> int:
        with UnitOfWork(get_session_factory()).transaction() as session:
            return container_audit_service.run_evening_alert(session)

    return _tracked("container_audit_evening_alert", run)


def container_audit_morning_missed() -> int:
    def run() -> int:
        with UnitOfWork(get_session_factory()).transaction() as session:
            return container_audit_service.run_morning_missed_transition(session)

    return _tracked("container_audit_morning_missed", run)


def inventory_segregation_check() -> int:
    def run() -> int:
        with UnitOfWork(get_session_factory()).transaction() as session:
            return inventory_service.run_nightly_segregation_check(session)

    return _tracked("inventory_segregation_check", run)


def notification_outbox() -> int:
    uow = UnitOfWork(get_session_factory())
    return _tracked("notification_outbox", lambda: notification_service.process_outbox(uow))


def notification_email() -> int:
    uow = UnitOfWork(get_session_factory())
    return _tracked("notification_email", lambda: notification_service.send_due_emails(uow))


def party_email() -> int:
    uow = UnitOfWork(get_session_factory())
    return _tracked("party_email", lambda: party_email_service.deliver_due(uow))


def notification_digest() -> int:
    uow = UnitOfWork(get_session_factory())
    return _tracked("notification_digest", lambda: notification_service.send_digests(uow))


def sla_escalation_check() -> int:
    def run() -> int:
        with UnitOfWork(get_session_factory()).transaction() as session:
            return notification_service.run_escalations(session, now=datetime.now(UTC))

    return _tracked("sla_escalation_check", run)


JOBS: dict[str, Callable[[], int]] = {
    "cleanup_pending_uploads": cleanup_pending_uploads,
    "container_audit_evening_alert": container_audit_evening_alert,
    "container_audit_morning_missed": container_audit_morning_missed,
    "inventory_segregation_check": inventory_segregation_check,
    "notification_outbox": notification_outbox,
    "notification_email": notification_email,
    "party_email": party_email,
    "notification_digest": notification_digest,
    "sla_escalation_check": sla_escalation_check,
}


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone=get_settings().tz)
    scheduler.add_job(
        cleanup_pending_uploads,
        "interval",
        minutes=CLEANUP_INTERVAL_MINUTES,
        id="cleanup_pending_uploads",
        max_instances=1,
        coalesce=True,
    )
    # P2-06: 18:00 IST evening reminder
    scheduler.add_job(
        container_audit_evening_alert,
        "cron",
        hour=18,
        minute=0,
        id="container_audit_evening_alert",
        max_instances=1,
        coalesce=True,
    )
    # P2-06: 09:00 IST next day missed transition
    scheduler.add_job(
        container_audit_morning_missed,
        "cron",
        hour=9,
        minute=0,
        id="container_audit_morning_missed",
        max_instances=1,
        coalesce=True,
    )
    # P3-04: 02:00 IST nightly custody segregation integrity check
    scheduler.add_job(
        inventory_segregation_check,
        "cron",
        hour=2,
        minute=0,
        id="inventory_segregation_check",
        max_instances=1,
        coalesce=True,
    )
    # P4-03: notification delivery and SLA escalations
    for job, seconds in (
        (notification_outbox, OUTBOX_INTERVAL_SECONDS),
        (notification_email, EMAIL_INTERVAL_SECONDS),
        (party_email, EMAIL_INTERVAL_SECONDS),
    ):
        scheduler.add_job(
            job, "interval", seconds=seconds, id=job.__name__, max_instances=1, coalesce=True
        )
    scheduler.add_job(
        notification_digest,
        "cron",
        minute=5,
        id="notification_digest",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        sla_escalation_check,
        "interval",
        minutes=ESCALATION_INTERVAL_MINUTES,
        id="sla_escalation_check",
        max_instances=1,
        coalesce=True,
    )
    return scheduler


def main() -> None:
    configure_logging(get_settings())
    parser = argparse.ArgumentParser(description="RMS background worker")
    parser.add_argument(
        "--run-job",
        choices=sorted(JOBS),
        help="Run a single job immediately and exit",
    )
    args = parser.parse_args()

    if args.run_job:
        log.info("running_single_job", job=args.run_job)
        count = JOBS[args.run_job]()
        log.info("single_job_finished", job=args.run_job, result_count=count)
        dispose_engine()
        sys.exit(0)

    scheduler = build_scheduler()
    log.info("worker_started", jobs=[j.id for j in scheduler.get_jobs()])
    cleanup_pending_uploads()  # run once at start-up, then on the interval
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("worker_stopped")
    finally:
        dispose_engine()


if __name__ == "__main__":
    main()
