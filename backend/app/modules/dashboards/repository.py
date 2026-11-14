"""Dashboard SQL (prompt P4-01). SQL only, no business rules.

Every widget aggregates in SQL (count / sum / group by), never by loading rows into Python. Each
query mirrors the WHERE clause of the list screen its widget links to, so the numbers match the list
totals (tests/integration/test_dashboards.py compares them):

    my_tasks_by_step      â†” GET /tasks/mine                       (tasks/repository.py)
    gs_*                  â†” GET /gs?status=â€¦&date_from=â€¦          (goods_slips/repository.py)
    csr_pending           â†” GET /csr-approvals/pending            (itemization/repository.py)
    open_pendencies       â†” GET /pendencies?status=OPEN           (pendency/repository.py)
    transfers_attention   â†” GET /custody/transfers?status=â€¦       (custody/repository.py)
    technician_wip        â†” GET /servicing/batches?status=â€¦       (servicing/repository.py)
    dismantling_queue     â†” GET /dismantling/queue                (dismantling/repository.py)
    cn_*                  â†” GET /credit-notes/work-queue, /credit-notes?status=â€¦
    accounts_queue        â†” GET /accounts/document-queue          (unboxing/repository.py)
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

# --- configuration ------------------------------------------------------------------------------


def get_setting(session: Session, key: str) -> Any:
    return session.execute(
        text("select value from public.system_settings where key = :k"), {"k": key}
    ).scalar()


def today_in(session: Session, timezone: str) -> date:
    """Today's date in the business timezone (as the GS list's date filters compute it)."""
    value = session.execute(
        text("select (now() at time zone :tz)::date"), {"tz": timezone}
    ).scalar_one()
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def widget_catalogue(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "select code, title, description, default_size, is_active "
            "from public.dashboard_widgets order by code"
        )
    ).mappings()
    return [dict(r) for r in rows]


def role_by_code(session: Session, code: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text("select id, code, name from public.roles where code = :c"), {"c": code}
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def list_roles(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(text("select id, code, name from public.roles order by name")).mappings()
    return [dict(r) for r in rows]


def user_roles_in_order(session: Session, user_id: UUID) -> list[dict[str, Any]]:
    """The user's roles, earliest assignment first (the provisional "primary role", P4-01)."""
    rows = session.execute(
        text(
            """
            select r.id, r.code, r.name
              from public.user_roles ur
              join public.roles r on r.id = ur.role_id
             where ur.user_id = :uid
             order by ur.created_at, r.code
            """
        ),
        {"uid": user_id},
    ).mappings()
    return [dict(r) for r in rows]


def layout_for_role(session: Session, role_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select l.widgets, l.updated_at, p.full_name as updated_by_name
                  from public.role_dashboard_layouts l
                  left join public.profiles p on p.id = l.updated_by
                 where l.role_id = :rid
                """
            ),
            {"rid": role_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def layout_for_update(session: Session, role_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "select widgets from public.role_dashboard_layouts where role_id = :rid for update"
            ),
            {"rid": role_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def upsert_layout(session: Session, role_id: UUID, widgets_json: str) -> None:
    session.execute(
        text(
            """
            insert into public.role_dashboard_layouts (role_id, widgets)
            values (:rid, cast(:w as jsonb))
            on conflict (role_id) do update set widgets = excluded.widgets
            """
        ),
        {"rid": role_id, "w": widgets_json},
    )


def delete_layout(session: Session, role_id: UUID) -> int:
    res = session.execute(
        text("delete from public.role_dashboard_layouts where role_id = :rid"), {"rid": role_id}
    )
    return int(getattr(res, "rowcount", 0))


def role_permission_keys(session: Session, role_id: UUID) -> set[tuple[str, str]]:
    rows = session.execute(
        text(
            """
            select p.module_code, p.action
              from public.role_permissions rp
              join public.permissions p on p.id = rp.permission_id
             where rp.role_id = :rid
            """
        ),
        {"rid": role_id},
    )
    return {(str(m), str(a)) for m, a in rows}


def insert_config_change(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    action: str,
    before_json: str | None,
    after_json: str | None,
    reason: str | None,
) -> None:
    session.execute(
        text(
            """
            insert into public.config_change_log
                   (entity_type, entity_id, action, before, after, reason)
            values (:et, :eid, :action, cast(:before as jsonb), cast(:after as jsonb), :reason)
            """
        ),
        {
            "et": entity_type,
            "eid": entity_id,
            "action": action,
            "before": before_json,
            "after": after_json,
            "reason": reason,
        },
    )


def option_labels(session: Session, set_code: str) -> dict[str, str]:
    rows = session.execute(
        text(
            """
            select oi.code, oi.label
              from public.option_items oi
              join public.option_sets os on os.id = oi.option_set_id
             where os.code = :s
             order by oi.sort_order, oi.code
            """
        ),
        {"s": set_code},
    )
    return {str(c): str(lbl) for c, lbl in rows}


# --- My tasks -----------------------------------------------------------------------------------


def my_tasks_by_step(session: Session, *, user_id: UUID, all_tasks: bool) -> list[dict[str, Any]]:
    """Open tasks per step: same visibility as tasks.repository.list_tasks_for_user."""
    rows = session.execute(
        text(
            """
            select t.step_code, max(ws.label) as step_label,
                   count(*)::int as count,
                   count(*) filter (where t.due_at is not null and t.due_at < now())::int
                     as overdue,
                   min(t.created_at) as oldest_created_at
              from public.workflow_tasks t
              join public.goods_slips g on g.id = t.gs_id
              left join public.workflow_steps ws
                     on ws.workflow_version_id = g.workflow_version_id and ws.code = t.step_code
             where t.status = 'OPEN'
               and (:all_tasks
                    or t.assigned_user_id = :uid
                    or exists (select 1 from public.user_roles ur
                                where ur.user_id = :uid and ur.role_id = t.assigned_role_id))
             group by t.step_code
             order by count(*) filter (where t.due_at is not null and t.due_at < now()) desc,
                      count(*) desc, t.step_code
            """
        ),
        {"uid": user_id, "all_tasks": all_tasks},
    ).mappings()
    return [dict(r) for r in rows]


# --- goods slips (scope-aware like goods_slips.repository.list_goods_slips) ---------------------


def _gs_scope(
    scope_created_by: UUID | None, scope_department_of: UUID | None
) -> tuple[str, dict[str, Any]]:
    if scope_created_by:
        return "g.created_by = :scope_uid", {"scope_uid": scope_created_by}
    if scope_department_of:
        return (
            "cb.department_id is not distinct from "
            "(select department_id from public.profiles where id = :scope_dept_uid)",
            {"scope_dept_uid": scope_department_of},
        )
    return "true", {}


_GS_FROM = """
  from public.goods_slips g
  left join public.profiles cb on cb.id = g.created_by
"""


def gs_pipeline(
    session: Session,
    *,
    open_statuses: list[str],
    scope_created_by: UUID | None,
    scope_department_of: UUID | None,
) -> list[dict[str, Any]]:
    scope_sql, params = _gs_scope(scope_created_by, scope_department_of)
    rows = session.execute(
        text(
            f"""
            select g.status, count(*)::int as count,
                   round((avg(extract(epoch from (now() - g.created_at))) / 86400)::numeric, 1)
                     as avg_age_days
            {_GS_FROM}
             where g.status = any(:statuses) and {scope_sql}
             group by g.status
            """  # noqa: S608 - fixed SQL fragments, values are bound parameters
        ),
        {**params, "statuses": open_statuses},
    ).mappings()
    return [dict(r) for r in rows]


def gs_created_on(
    session: Session,
    *,
    day: date,
    timezone: str,
    scope_created_by: UUID | None,
    scope_department_of: UUID | None,
) -> dict[str, Any]:
    scope_sql, params = _gs_scope(scope_created_by, scope_department_of)
    row = (
        session.execute(
            text(
                f"""
                select count(*)::int as count,
                       coalesce(sum(g.box_count), 0)::int as boxes,
                       count(*) filter (where g.missing_documentation)::int
                         as missing_documentation
                {_GS_FROM}
                 where (g.created_at at time zone :tz)::date = :day and {scope_sql}
                """
            ),
            {**params, "tz": timezone, "day": day},
        )
        .mappings()
        .one()
    )
    return dict(row)


def gs_in_statuses(
    session: Session,
    *,
    statuses: list[str],
    scope_created_by: UUID | None,
    scope_department_of: UUID | None,
) -> dict[str, Any]:
    scope_sql, params = _gs_scope(scope_created_by, scope_department_of)
    row = (
        session.execute(
            text(
                f"""
                select count(*)::int as count, min(g.created_at) as oldest_created_at
                {_GS_FROM}
                 where g.status = any(:statuses) and {scope_sql}
                """
            ),
            {**params, "statuses": statuses},
        )
        .mappings()
        .one()
    )
    return dict(row)


def gs_trend(
    session: Session,
    *,
    weeks: int,
    timezone: str,
    scope_created_by: UUID | None,
    scope_department_of: UUID | None,
) -> list[dict[str, Any]]:
    """Opened (created_at) and closed (closed_at) goods slips per ISO week, in the business tz."""
    scope_sql, params = _gs_scope(scope_created_by, scope_department_of)
    rows = session.execute(
        text(
            f"""
            with wk as (
              select generate_series(
                       date_trunc('week', (now() at time zone :tz))::date
                         - (:weeks - 1) * 7,
                       date_trunc('week', (now() at time zone :tz))::date,
                       interval '7 days')::date as week_start
            ),
            scoped as (
              select g.created_at, g.closed_at, g.status
              {_GS_FROM}
               where {scope_sql}
            )
            select wk.week_start,
                   (select count(*) from scoped s
                     where date_trunc('week', s.created_at at time zone :tz)::date
                           = wk.week_start)::int as opened,
                   (select count(*) from scoped s
                     where s.status = 'CLOSED' and s.closed_at is not null
                       and date_trunc('week', s.closed_at at time zone :tz)::date
                           = wk.week_start)::int as closed
              from wk
             order by wk.week_start
            """  # noqa: S608
        ),
        {**params, "tz": timezone, "weeks": weeks},
    ).mappings()
    return [dict(r) for r in rows]


def csr_pending(session: Session) -> dict[str, Any]:
    """Same set as itemization.repository.pending_csr_gs_ids (unscoped RM inbox)."""
    row = (
        session.execute(
            text(
                """
                select count(*)::int as count, min(g.created_at) as oldest_created_at
                  from public.goods_slips g
                 where g.status = 'CSR_APPROVAL_PENDING'
                """
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


# --- container audit ----------------------------------------------------------------------------


def container_audit_summary(
    session: Session, *, today: date, window_from: date, window_to: date
) -> dict[str, Any]:
    row = (
        session.execute(
            text(
                """
                select
                  (select d.status from public.container_audit_days d
                    where d.audit_date = :today) as today_status,
                  count(*) filter (where d.status = 'CONFIRMED')::int as confirmed_on_time,
                  count(*) filter (where d.status = 'LATE')::int as confirmed_late
                  from public.container_audit_days d
                 where d.audit_date between :wf and :wt
                """
            ),
            {"today": today, "wf": window_from, "wt": window_to},
        )
        .mappings()
        .one()
    )
    return dict(row)


# --- pendencies ---------------------------------------------------------------------------------


def open_pendencies(session: Session) -> dict[str, Any]:
    """Same set as GET /pendencies?status=OPEN (pendency.repository.list_pendencies)."""
    row = (
        session.execute(
            text(
                """
                select count(*)::int as open_count,
                       coalesce(sum(p.qty), 0)::int as open_qty,
                       count(*) filter (where p.blocks_gs)::int as blocking_count,
                       min(p.opened_at) as oldest_opened_at
                  from public.pendencies p
                  join public.goods_slips gs on gs.id = p.gs_id
                 where p.status = 'OPEN'
                """
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


# --- custody ------------------------------------------------------------------------------------


def transfers_attention(session: Session) -> dict[str, Any]:
    """Same sets as GET /custody/transfers?status=INITIATED and ?status=DISCREPANCY."""
    row = (
        session.execute(
            text(
                """
                select count(*) filter (where t.status = 'INITIATED')::int as awaiting_acceptance,
                       count(*) filter (where t.status = 'DISCREPANCY')::int as in_discrepancy,
                       min(t.initiated_at) filter (where t.status = 'INITIATED')
                         as oldest_awaiting_at
                  from public.custody_transfers t
                 where t.status in ('INITIATED', 'DISCREPANCY')
                """
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


# --- servicing ----------------------------------------------------------------------------------


def technician_wip(session: Session, *, statuses: list[str]) -> list[dict[str, Any]]:
    """Per status: batches, pieces still out (allotted - received) and age, as servicing lists."""
    rows = session.execute(
        text(
            """
            with b as (
              select tb.id, tb.status, tb.allotted_at,
                     coalesce(sum(tbl.qty_allotted), 0) - coalesce(sum(tbl.qty_received), 0)
                       as pieces_out
                from public.technician_batches tb
                join public.technicians t on t.id = tb.technician_id
                join public.profiles p on p.id = tb.entry_by
                left join public.technician_batch_lines tbl on tbl.batch_id = tb.id
               where tb.status = any(:statuses)
               group by tb.id, tb.status, tb.allotted_at
            )
            select b.status, count(*)::int as count,
                   coalesce(sum(b.pieces_out), 0)::int as pieces_out,
                   round((avg(extract(epoch from (now() - b.allotted_at))) / 86400)::numeric, 1)
                     as avg_age_days,
                   max(greatest(0, floor(extract(epoch from (now() - b.allotted_at)) / 86400)))::int
                     as oldest_age_days
              from b
             group by b.status
            """
        ),
        {"statuses": statuses},
    ).mappings()
    return [dict(r) for r in rows]


# --- batteries / dismantling --------------------------------------------------------------------


def batteries_installed_since(session: Session, *, since: datetime) -> int:
    """Battery consumption = batteries installed (IC-09), as battery balances count it."""
    return int(
        session.execute(
            text(
                """
                select coalesce(sum(r.batteries_installed), 0)
                  from public.technician_receiving_records r
                 where r.battery_check_code = 'BATTERY_REPLACED' and r.received_at >= :since
                """
            ),
            {"since": since},
        ).scalar_one()
    )


def dismantling_queue(session: Session) -> dict[str, Any]:
    """Same set as dismantling.repository.get_dismantling_queue_lots."""
    row = (
        session.execute(
            text(
                """
                select count(*)::int as queue_lots, coalesce(sum(b.qty), 0)::int as queue_qty
                  from public.stock_balances b
                  join public.stock_lots l on l.id = b.lot_id
                  join public.inventory_locations loc on loc.id = b.location_id
                  join public.stock_items si on si.id = l.stock_item_id
                 where loc.code = 'NON_FUNCTIONAL_STORE'
                   and b.qty > 0
                   and l.condition_class in ('NON_GOOD', 'NON_SELLABLE')
                """
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


def parts_recovered_since(session: Session, *, since: datetime) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select rp.part_type, coalesce(sum(rp.qty), 0)::int as qty
              from public.recovered_parts rp
             where rp.created_at >= :since
             group by rp.part_type
             order by rp.part_type
            """
        ),
        {"since": since},
    ).mappings()
    return [dict(r) for r in rows]


# --- credit notes -------------------------------------------------------------------------------


def cn_pipeline(session: Session, *, issued_since: datetime) -> dict[str, Any]:
    """awaiting_credit_gs mirrors credit_notes.repository.get_work_queue_pending_gs."""
    row = (
        session.execute(
            text(
                """
                with allowed as (
                  select d.gs_id, sum(dl.qty)::integer as allowed_qty
                    from public.rm_cn_decisions d
                    join public.rm_cn_decision_lines dl on dl.decision_id = d.id
                   where d.is_current = true and dl.decision_code = 'ALLOW_CN'
                   group by d.gs_id
                ),
                issued as (
                  select cn.gs_id, coalesce(sum(cl.qty), 0)::integer as issued_qty
                    from public.credit_notes cn
                    join public.credit_note_lines cl on cl.credit_note_id = cn.id
                   where cn.status = 'ISSUED'
                   group by cn.gs_id
                )
                select
                  (select count(*)
                     from allowed a
                     join public.goods_slips gs on gs.id = a.gs_id
                     join public.parties p on p.id = gs.party_id
                     left join issued i on i.gs_id = a.gs_id
                    where (a.allowed_qty - coalesce(i.issued_qty, 0)) > 0)::int
                    as awaiting_credit_gs,
                  (select count(*) from public.credit_notes where status = 'DRAFT')::int as draft,
                  (select count(*) from public.credit_notes where status = 'VERIFIED')::int
                    as verified,
                  (select count(*) from public.credit_notes
                    where status = 'ISSUED' and issued_at >= :since)::int as issued_30d
                """
            ),
            {"since": issued_since},
        )
        .mappings()
        .one()
    )
    return dict(row)


def cn_issued_by_month(session: Session, *, months: int, timezone: str) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select date_trunc('month', cn.issued_at at time zone :tz)::date as month,
                   cn.cn_type_code, count(*)::int as count,
                   coalesce(sum(cn.total_value), 0)::float8 as value
              from public.credit_notes cn
             where cn.status = 'ISSUED'
               and cn.issued_at is not null
               and (cn.issued_at at time zone :tz)
                   >= date_trunc('month', now() at time zone :tz)
                      - make_interval(months => :months - 1)
             group by 1, 2
             order by 1, 2
            """
        ),
        {"tz": timezone, "months": months},
    ).mappings()
    return [dict(r) for r in rows]


# --- accounts -----------------------------------------------------------------------------------


def accounts_doc_queue(session: Session) -> dict[str, Any]:
    """Same set as unboxing.repository.accounts_queue with no classification filter."""
    row = (
        session.execute(
            text(
                """
                select count(*)::int as count, min(g.created_at) as oldest_created_at
                  from public.goods_slips g
                 where g.status not in ('GATE_CREATED', 'UNBOXING', 'CANCELLED')
                   and exists (select 1 from public.gs_documents d
                                where d.gs_id = g.id and d.accounts_acknowledged_at is null)
                """
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


# --- admin --------------------------------------------------------------------------------------


def admin_health(session: Session, *, since: datetime) -> dict[str, Any]:
    row = (
        session.execute(
            text(
                """
                select
                  (select count(*) from public.profiles where is_active)::int as users_active,
                  (select count(*) from public.profiles where not is_active)::int
                    as users_inactive,
                  (select logins from rms_private.auth_login_stats(:since))::int as logins,
                  (select distinct_users from rms_private.auth_login_stats(:since))::int
                    as users_logged_in,
                  (select count(*) from public.config_change_log where changed_at >= :since)::int
                    as config_changes,
                  (select count(*) from public.system_guard_events where occurred_at >= :since)::int
                    as guard_violations,
                  (select count(*) from public.job_runs where finished_at >= :since)::int
                    as job_runs,
                  (select count(*) from public.job_runs
                    where finished_at >= :since and status = 'FAILED')::int as failed_jobs
                """
            ),
            {"since": since},
        )
        .mappings()
        .one()
    )
    return dict(row)


def guard_events_by_code(session: Session, *, since: datetime) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select guard_code, count(*)::int as count
              from public.system_guard_events
             where occurred_at >= :since
             group by guard_code
             order by count(*) desc, guard_code
            """
        ),
        {"since": since},
    ).mappings()
    return [dict(r) for r in rows]


def last_failed_job(session: Session, *, since: datetime) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select job_code, finished_at from public.job_runs
                 where status = 'FAILED' and finished_at >= :since
                 order by finished_at desc limit 1
                """
            ),
            {"since": since},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None
