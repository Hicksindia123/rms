"""Database repository for daily DMT container audit (P2-06)."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def get_day_by_date(session: Session, audit_date: date) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
            select d.id, d.audit_date, d.status, d.is_late, d.late_reason,
                   d.confirmed, d.confirmed_by, d.confirmed_at, d.remarks, d.created_at,
                   p.full_name as confirmed_by_name
            from public.container_audit_days d
            left join public.profiles p on p.id = d.confirmed_by
            where d.audit_date = :audit_date
            """
            ),
            {"audit_date": audit_date},
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def get_or_create_day(session: Session, audit_date: date) -> dict[str, Any]:
    existing = get_day_by_date(session, audit_date)
    if existing:
        return existing

    session.execute(
        text(
            """
            insert into public.container_audit_days (audit_date, status, confirmed)
            values (:audit_date, 'PENDING', false)
            on conflict (audit_date) do nothing
            """
        ),
        {"audit_date": audit_date},
    )
    res = get_day_by_date(session, audit_date)
    if res is None:
        raise RuntimeError(f"Failed to get or create container audit day for {audit_date}")
    return res


def get_active_dmt_containers(session: Session) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            text(
                """
            select id, code, barcode, name
            from public.storage_containers
            where container_type = 'DMT_RETURN'
              and is_active = true
            order by code asc
            """
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def get_lines_for_day(session: Session, audit_day_id: UUID) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            text(
                """
            select l.id, l.container_id, l.counted_qty, l.sellable_packaging_qty, l.remarks,
                   c.code as container_code, c.barcode as container_barcode,
                   c.name as container_name
            from public.container_audit_lines l
            join public.storage_containers c on c.id = l.container_id
            where l.audit_day_id = :audit_day_id
            order by c.code asc
            """
            ),
            {"audit_day_id": audit_day_id},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def get_yesterday_counts(session: Session, yesterday_date: date) -> dict[UUID, tuple[int, int]]:
    """Return map of container_id -> (counted_qty, sellable_packaging_qty) for yesterday."""
    rows = (
        session.execute(
            text(
                """
            select l.container_id, l.counted_qty, l.sellable_packaging_qty
            from public.container_audit_lines l
            join public.container_audit_days d on d.id = l.audit_day_id
            where d.audit_date = :yesterday_date
            """
            ),
            {"yesterday_date": yesterday_date},
        )
        .mappings()
        .all()
    )
    return {r["container_id"]: (r["counted_qty"], r["sellable_packaging_qty"]) for r in rows}


def upsert_lines(
    session: Session,
    audit_day_id: UUID,
    lines: list[dict[str, Any]],
) -> None:
    for line in lines:
        session.execute(
            text(
                """
                insert into public.container_audit_lines (
                    audit_day_id, container_id, counted_qty, sellable_packaging_qty, remarks
                ) values (
                    :audit_day_id, :container_id, :counted_qty, :sellable_packaging_qty, :remarks
                )
                on conflict (audit_day_id, container_id) do update set
                    counted_qty = excluded.counted_qty,
                    sellable_packaging_qty = excluded.sellable_packaging_qty,
                    remarks = excluded.remarks
                """
            ),
            {
                "audit_day_id": audit_day_id,
                "container_id": line["container_id"],
                "counted_qty": line["counted_qty"],
                "sellable_packaging_qty": line.get("sellable_packaging_qty", 0),
                "remarks": line.get("remarks"),
            },
        )


def confirm_day(
    session: Session,
    audit_day_id: UUID,
    *,
    confirmed_by: UUID,
    is_late: bool,
    late_reason: str | None,
    remarks: str | None,
) -> None:
    status = "LATE" if is_late else "CONFIRMED"
    session.execute(
        text(
            """
            update public.container_audit_days
            set confirmed = true,
                confirmed_by = :confirmed_by,
                confirmed_at = now(),
                status = :status,
                is_late = :is_late,
                late_reason = :late_reason,
                remarks = coalesce(:remarks, remarks)
            where id = :audit_day_id
            """
        ),
        {
            "audit_day_id": audit_day_id,
            "confirmed_by": confirmed_by,
            "status": status,
            "is_late": is_late,
            "late_reason": late_reason,
            "remarks": remarks,
        },
    )


def mark_missed_days(session: Session, before_date: date) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            text(
                """
            -- BR-18 / DEC-08: a day nobody opened has no row; record it as MISSED too (every day
            -- since the first recorded audit), otherwise a skipped audit is never flagged (P2-08).
            with gaps as (
              insert into public.container_audit_days (audit_date, status)
              select d::date, 'MISSED'
                from generate_series((select min(audit_date) from public.container_audit_days),
                                     cast(:before_date as date) - 1, interval '1 day') d
               where not exists (select 1 from public.container_audit_days x
                                  where x.audit_date = d::date)
              on conflict (audit_date) do nothing
              returning id, audit_date
            ), flipped as (
              update public.container_audit_days
                 set status = 'MISSED'
               where audit_date < :before_date
                 and confirmed = false
                 and status = 'PENDING'
              returning id, audit_date
            )
            select id, audit_date from gaps
            union all
            select id, audit_date from flipped
            order by audit_date
            """
            ),
            {"before_date": before_date},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def get_calendar_range(session: Session, from_date: date, to_date: date) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            text(
                """
            select d.audit_date, d.status, d.is_late, d.confirmed, d.confirmed_at, d.remarks,
                   coalesce(sum(l.counted_qty), 0) as total_containers_counted,
                   coalesce(sum(l.sellable_packaging_qty), 0) as total_sellable_packaging_qty
            from public.container_audit_days d
            left join public.container_audit_lines l on l.audit_day_id = d.id
            where d.audit_date between :from_date and :to_date
            group by d.id, d.audit_date, d.status, d.is_late, d.confirmed, d.confirmed_at, d.remarks
            order by d.audit_date asc
            """
            ),
            {"from_date": from_date, "to_date": to_date},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def get_checkbox_label(session: Session) -> str:
    row = session.execute(
        text(
            """
            select oi.label
            from public.option_items oi
            join public.option_sets os on os.id = oi.option_set_id
            where os.code = 'DAILY_CONTAINER_AUDIT'
              and oi.code = 'DAILY_AUDIT_DONE'
            limit 1
            """
        )
    ).scalar_one_or_none()
    return row or "Containers Checked & Counted Daily"
