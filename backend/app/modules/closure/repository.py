"""Closure engine repository: SQL only, no business rules (P3-07, CLAUDE.md rule g).

The checklist itself is `rms_private.gs_closure_checklist` (migration 20261105000300): the same
function the G-15 trigger on goods_slips re-runs, so the API and the database never disagree.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session


def checklist(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select sort_order, code, rule_ref, applicable, passed, explanation, details
              from rms_private.gs_closure_checklist(:gs)
             order by sort_order
            """
        ),
        {"gs": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def closure_type(session: Session, gs_id: UUID) -> str:
    return str(
        session.execute(text("select rms_private.gs_closure_type(:gs)"), {"gs": gs_id}).scalar_one()
    )


def lock_closure_inputs(session: Session, gs_id: UUID) -> None:
    """Row locks for the close command (the GS row is locked by the caller): the GS's stock
    balances, credit notes, pendencies and custody transfers cannot change until commit."""
    for sql in (
        """select 1 from public.stock_balances b join public.stock_lots l on l.id = b.lot_id
            where l.gs_id = :gs for update of b""",
        "select 1 from public.credit_notes where gs_id = :gs for update",
        "select 1 from public.pendencies where gs_id = :gs for update",
        "select 1 from public.custody_transfers where gs_id = :gs for update",
        "select 1 from public.replacement_dispatches where gs_id = :gs for update",
    ):
        session.execute(text(sql), {"gs": gs_id}).all()


def option_label(session: Session, set_code: str, item_code: str) -> str | None:
    row = session.execute(
        text(
            """
            select oi.label from public.option_items oi
              join public.option_sets os on os.id = oi.option_set_id
             where os.code = :s and oi.code = :c
            """
        ),
        {"s": set_code, "c": item_code},
    ).first()
    return str(row[0]) if row else None


def get_setting(session: Session, key: str) -> Any:
    row = session.execute(
        text("select value from public.system_settings where key = :k"), {"k": key}
    ).first()
    return row[0] if row else None


_CLOSURE_COLUMNS = """
    c.id, c.gs_id, c.closure_type, c.closure_label, c.checklist_snapshot, c.remarks,
    c.close_count, c.closed_by, pc.full_name as closed_by_name, c.closed_at,
    c.reopened_by, pr.full_name as reopened_by_name, c.reopened_at, c.reopen_reason,
    c.reopen_count
"""


def get_closure(
    session: Session, gs_id: UUID, *, for_update: bool = False
) -> dict[str, Any] | None:
    lock = " for update of c" if for_update else ""
    row = (
        session.execute(
            text(
                f"""
                select {_CLOSURE_COLUMNS}
                  from public.gs_closures c
                  left join public.profiles pc on pc.id = c.closed_by
                  left join public.profiles pr on pr.id = c.reopened_by
                 where c.gs_id = :gs{lock}
                """  # noqa: S608
            ),
            {"gs": gs_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


_SNAPSHOT = bindparam("snapshot", type_=JSONB)


def insert_closure(
    session: Session,
    *,
    gs_id: UUID,
    closure_type: str,
    closure_label: str | None,
    snapshot: dict[str, Any],
    remarks: str | None,
    by: UUID,
) -> None:
    session.execute(
        text(
            """
            insert into public.gs_closures (gs_id, closure_type, closure_label, checklist_snapshot,
                                            remarks, closed_by, closed_at)
            values (:gs, :ct, :label, :snapshot, :remarks, :by, clock_timestamp())
            """
        ).bindparams(_SNAPSHOT),
        {
            "gs": gs_id,
            "ct": closure_type,
            "label": closure_label,
            "snapshot": snapshot,
            "remarks": remarks,
            "by": by,
        },
    )


def update_closure_for_reclose(
    session: Session,
    *,
    gs_id: UUID,
    closure_type: str,
    closure_label: str | None,
    snapshot: dict[str, Any],
    remarks: str | None,
    by: UUID,
) -> None:
    """Close again after a reopen: the reopen fields stay; the audit log keeps the old values."""
    session.execute(
        text(
            """
            update public.gs_closures
               set closure_type = :ct, closure_label = :label, checklist_snapshot = :snapshot,
                   remarks = :remarks, closed_by = :by, closed_at = clock_timestamp(),
                   close_count = close_count + 1
             where gs_id = :gs
            """
        ).bindparams(_SNAPSHOT),
        {
            "gs": gs_id,
            "ct": closure_type,
            "label": closure_label,
            "snapshot": snapshot,
            "remarks": remarks,
            "by": by,
        },
    )


def record_reopen(session: Session, *, gs_id: UUID, by: UUID, reason: str) -> None:
    session.execute(
        text(
            """
            update public.gs_closures
               set reopened_by = :by, reopened_at = clock_timestamp(), reopen_reason = :reason,
                   reopen_count = reopen_count + 1
             where gs_id = :gs
            """
        ),
        {"gs": gs_id, "by": by, "reason": reason},
    )


# --- read models for the closure panel / certificate ------------------------------------------


def gs_header(session: Session, gs_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select g.id, g.gs_no, g.status, g.category_code, g.original_category_code,
                       g.created_at, g.closed_at, g.closure_type, g.box_count,
                       p.name as party_name, p.code as party_code,
                       st.name as state_name, sn.name as station_name
                  from public.goods_slips g
                  left join public.parties p on p.id = g.party_id
                  left join public.states st on st.id = g.state_id
                  left join public.stations sn on sn.id = g.station_id
                 where g.id = :gs
                """
            ),
            {"gs": gs_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def gs_lines(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select gi.line_no, coalesce(gi.product_code_snapshot, pr.code) as product_code,
                   coalesce(gi.product_name_snapshot, pr.name) as product_name,
                   gi.received_qty
              from public.gs_items gi
              join public.products pr on pr.id = gi.product_id
             where gi.gs_id = :gs
             order by gi.line_no
            """
        ),
        {"gs": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def issued_credit_notes(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select cn.id, cn.cn_type_code, oi.label as cn_type_label, cn.cn_no, cn.cn_date,
                   cn.jv_no, cn.jv_date, cn.total_value, cn.issued_at
              from public.credit_notes cn
              left join public.option_sets os on os.code = 'CN_TYPE'
              left join public.option_items oi on oi.option_set_id = os.id
                                              and oi.code = cn.cn_type_code
             where cn.gs_id = :gs and cn.status = 'ISSUED'
             order by cn.issued_at
            """
        ),
        {"gs": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def dispatches(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select rd.id, rd.dispatch_no, rd.dispatch_type, rd.transporter, rd.docket_no,
                   rd.vehicle_no, rd.dispatched_at,
                   coalesce((select sum(l.qty) from public.replacement_dispatch_lines l
                              where l.dispatch_id = rd.id), 0)::int as qty
              from public.replacement_dispatches rd
             where rd.gs_id = :gs and rd.status = 'DISPATCHED'
             order by rd.dispatched_at
            """
        ),
        {"gs": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def notifications(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select pn.id, pn.credit_note_id, pn.status_code, pn.status_label, pn.channel_code,
                   pn.recipient, pn.sent_at, p.full_name as sent_by_name
              from public.party_notifications pn
              left join public.profiles p on p.id = pn.sent_by
             where pn.gs_id = :gs
             order by pn.sent_at
            """
        ),
        {"gs": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def lot_count(session: Session, gs_id: UUID) -> int:
    return int(
        session.execute(
            text("select count(*) from public.stock_lots where gs_id = :gs"), {"gs": gs_id}
        ).scalar_one()
    )


def current_actor(session: Session) -> UUID | None:
    value = session.execute(text("select rms_private.current_actor()")).scalar_one()
    return UUID(str(value)) if value else None
