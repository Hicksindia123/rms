"""Service layer for daily DMT container audit (P2-06, BR-18, DEC-08)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.orm import Session

from app.core.errors import Conflict, PermissionDenied, ValidationFailed
from app.core.permissions import EffectivePermissions
from app.core.security import CurrentUser
from app.modules.container_audit import repository as repo
from app.modules.container_audit.schemas import (
    CalendarDayOut,
    CalendarSummaryOut,
    ConfirmAuditIn,
    ContainerAuditDayOut,
    ContainerAuditLineOut,
    SaveLinesIn,
    TodayAuditOut,
)
from app.modules.notifications import service as notifications_service

log = structlog.get_logger("rms.container_audit")
TZ_KOLKATA = ZoneInfo("Asia/Kolkata")


def get_today_ist() -> date:
    return datetime.now(TZ_KOLKATA).date()


def _assert_can_edit(user: CurrentUser, perms: EffectivePermissions) -> None:
    if user.is_super_admin:
        return
    if "INWARD_VERIFIER" in user.role_codes:
        return
    if perms.allows("container_audit", "edit"):
        return
    raise PermissionDenied("You do not have permission to edit container audits")


def _assert_can_view(user: CurrentUser, perms: EffectivePermissions) -> None:
    if user.is_super_admin:
        return
    allowed_roles = {"INWARD_VERIFIER", "REPLACEMENT_MANAGER", "MANAGEMENT_VIEWER"}
    if user.role_codes.intersection(allowed_roles):
        return
    if perms.allows("container_audit", "view"):
        return
    raise PermissionDenied("You do not have permission to view container audits")


def get_audit_by_date(
    session: Session,
    audit_date: date,
    user: CurrentUser,
    perms: EffectivePermissions,
) -> TodayAuditOut:
    _assert_can_view(user, perms)
    day_before = audit_date - timedelta(days=1)

    day_row = repo.get_or_create_day(session, audit_date)
    containers = repo.get_active_dmt_containers(session)
    existing_lines = {
        item["container_id"]: item for item in repo.get_lines_for_day(session, day_row["id"])
    }
    yesterday_counts = repo.get_yesterday_counts(session, day_before)

    lines_out: list[ContainerAuditLineOut] = []
    for c in containers:
        line = existing_lines.get(c["id"])
        y_counts = yesterday_counts.get(c["id"])
        lines_out.append(
            ContainerAuditLineOut(
                id=line["id"] if line else None,
                container_id=c["id"],
                container_code=c["code"],
                container_barcode=c["barcode"],
                container_name=c["name"],
                counted_qty=line["counted_qty"] if line else 0,
                sellable_packaging_qty=line["sellable_packaging_qty"] if line else 0,
                remarks=line["remarks"] if line else None,
                yesterday_counted_qty=y_counts[0] if y_counts else None,
                yesterday_sellable_packaging_qty=y_counts[1] if y_counts else None,
            )
        )

    can_edit = (
        user.is_super_admin
        or "INWARD_VERIFIER" in user.role_codes
        or perms.allows("container_audit", "edit")
    )
    can_confirm = can_edit and not day_row["confirmed"]
    checkbox_label = repo.get_checkbox_label(session)

    day_out = ContainerAuditDayOut(
        id=day_row["id"],
        audit_date=day_row["audit_date"],
        status=day_row["status"],
        is_late=day_row["is_late"],
        late_reason=day_row["late_reason"],
        confirmed=day_row["confirmed"],
        confirmed_by=day_row["confirmed_by"],
        confirmed_by_name=day_row.get("confirmed_by_name"),
        confirmed_at=day_row["confirmed_at"],
        remarks=day_row["remarks"],
        created_at=day_row["created_at"],
    )

    return TodayAuditOut(
        day=day_out,
        containers=lines_out,
        checkbox_label=checkbox_label,
        can_edit=can_edit,
        can_confirm=can_confirm,
    )


def get_today_audit(
    session: Session,
    user: CurrentUser,
    perms: EffectivePermissions,
) -> TodayAuditOut:
    return get_audit_by_date(session, get_today_ist(), user, perms)


def get_audit_for_date(
    session: Session,
    audit_date: date,
    user: CurrentUser,
    perms: EffectivePermissions,
) -> TodayAuditOut:
    """Register for a chosen date (P2-08 fix: the date picker used to always show today)."""
    if audit_date > get_today_ist():
        raise ValidationFailed("Cannot audit a future date")
    return get_audit_by_date(session, audit_date, user, perms)


def save_audit_lines(
    session: Session,
    audit_date: date,
    payload: SaveLinesIn,
    user: CurrentUser,
    perms: EffectivePermissions,
) -> TodayAuditOut:
    _assert_can_edit(user, perms)
    day_row = repo.get_or_create_day(session, audit_date)
    if day_row["confirmed"] and not user.is_super_admin:
        raise Conflict("Audit for this date has already been confirmed and cannot be modified")

    repo.upsert_lines(
        session,
        day_row["id"],
        [item.model_dump() for item in payload.lines],
    )
    return get_audit_by_date(session, audit_date, user, perms)


def confirm_audit(
    session: Session,
    audit_date: date,
    payload: ConfirmAuditIn,
    user: CurrentUser,
    perms: EffectivePermissions,
) -> TodayAuditOut:
    _assert_can_edit(user, perms)

    if not payload.confirmed:
        raise ValidationFailed("Confirmation checkbox must be checked")

    today = get_today_ist()
    if audit_date > today:
        raise ValidationFailed("Cannot audit a future date")

    is_late = audit_date < today
    if is_late and (not payload.late_reason or not payload.late_reason.strip()):
        raise ValidationFailed("Late entry for a past date requires a reason")

    day_row = repo.get_or_create_day(session, audit_date)
    if day_row["confirmed"] and not user.is_super_admin:
        raise Conflict("Audit for this date has already been confirmed")

    # If lines provided in payload, upsert them first
    if payload.lines:
        repo.upsert_lines(
            session,
            day_row["id"],
            [item.model_dump() for item in payload.lines],
        )

    # Acceptance Criteria BR-18: Cannot confirm without counting every active DMT container
    active_containers = repo.get_active_dmt_containers(session)
    existing_lines = repo.get_lines_for_day(session, day_row["id"])
    counted_container_ids = {item["container_id"] for item in existing_lines}

    missing_containers = [c for c in active_containers if c["id"] not in counted_container_ids]
    if missing_containers:
        missing_names = ", ".join(c["code"] for c in missing_containers)
        raise ValidationFailed(
            f"Cannot confirm: all active DMT containers must be counted. Missing: {missing_names}"
        )

    repo.confirm_day(
        session,
        day_row["id"],
        confirmed_by=user.id,
        is_late=is_late,
        late_reason=payload.late_reason.strip() if payload.late_reason else None,
        remarks=payload.remarks,
    )

    return get_audit_by_date(session, audit_date, user, perms)


def get_calendar(
    session: Session,
    from_date: date,
    to_date: date,
    user: CurrentUser,
    perms: EffectivePermissions,
) -> CalendarSummaryOut:
    _assert_can_view(user, perms)
    if from_date > to_date:
        raise ValidationFailed("from_date must not be after to_date")

    rows = repo.get_calendar_range(session, from_date, to_date)
    today = get_today_ist()
    today_row = repo.get_day_by_date(session, today)
    today_status = today_row["status"] if today_row else "PENDING"

    days_out = [
        CalendarDayOut(
            audit_date=r["audit_date"],
            status=r["status"],
            is_late=bool(r["is_late"]),
            confirmed=bool(r["confirmed"]),
            confirmed_at=r["confirmed_at"],
            total_containers_counted=int(r["total_containers_counted"]),
            total_sellable_packaging_qty=int(r["total_sellable_packaging_qty"]),
            remarks=r["remarks"],
        )
        for r in rows
    ]

    return CalendarSummaryOut(
        from_date=from_date,
        to_date=to_date,
        days=days_out,
        today_status=today_status,
    )


# -------------------------------------------------------------------------
# Worker jobs (Prompt P2-06 requirements)
# -------------------------------------------------------------------------


def run_evening_alert(session: Session) -> int:
    """Run at 18:00 IST: if today's audit is not confirmed -> notify Inward Verifier and RM."""
    today = get_today_ist()
    day_row = repo.get_day_by_date(session, today)
    if not day_row or not day_row["confirmed"]:
        log.info("container_audit_evening_alert_dispatching", date=str(today))
        if not day_row:
            day_row = repo.get_or_create_day(session, today)

        return notifications_service.publish(
            session,
            "CONTAINER_AUDIT_REMINDER",
            role_codes=["INWARD_VERIFIER", "REPLACEMENT_MANAGER"],
            notification_type="CONTAINER_AUDIT_REMINDER",
            title="Daily DMT Container Audit Pending",
            body=f"Today's ({today}) DMT container audit is pending confirmation.",
            entity_type="container_audit_day",
            entity_id=day_row["id"],
            priority="HIGH",
        )
    return 0


def run_morning_missed_transition(session: Session) -> int:
    """Run at 09:00 IST: mark unconfirmed past days as MISSED and notify Inward Verifier and RM."""
    today = get_today_ist()
    missed_days = repo.mark_missed_days(session, today)
    if not missed_days:
        return 0

    log.info(
        "container_audit_marked_missed",
        count=len(missed_days),
        days=[str(d["audit_date"]) for d in missed_days],
    )
    dates_str = ", ".join(str(d["audit_date"]) for d in missed_days)
    first_id = missed_days[0]["id"]

    return notifications_service.publish(
        session,
        "DAILY_AUDIT_MISSED",
        role_codes=["INWARD_VERIFIER", "REPLACEMENT_MANAGER"],
        notification_type="CONTAINER_AUDIT_MISSED",
        title="DMT Container Audit MISSED",
        body=(
            f"Daily container audit was missed for date(s): {dates_str}. "
            "Please complete late confirmation."
        ),
        entity_type="container_audit_day",
        entity_id=first_id,
        priority="HIGH",
    )
