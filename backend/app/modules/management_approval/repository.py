"""SQL for Management approval and the e-approval stamp (Phase P10; DEC-70; Q17, Q18).
SQL only: the business rules live in the service and in the DB guards (migration
20261123000300_p10_management_approval.sql)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

# Goods slips Management may open "between analysis and Accounts" (P11 adds the Accounts states).
# DEC-71: Management also finds goods slips at Accounts or on hold (it may still change them).
OPEN_STATUSES = ("ANALYSIS_COMPLETED", "ACCOUNTS_PENDING", "NOT_ALLOWED_HOLD")


def _rows(session: Session, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(r) for r in session.execute(text(sql), params).mappings().all()]


def _row(session: Session, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
    row = session.execute(text(sql), params).mappings().first()
    return dict(row) if row else None


# --- goods slip -------------------------------------------------------------------------------


def get_gs(session: Session, gs_id: UUID, *, lock: bool = False) -> dict[str, Any] | None:
    lock_sql = " for update of g" if lock else ""
    return _row(
        session,
        f"""
        select g.id, g.gs_no, g.status, g.item_field_profile_version_id,
               rms_private.gs_on_store_flow(g.id) as on_store_flow,
               pa.name as party_name, st.name as station_name
          from public.goods_slips g
          left join public.parties pa on pa.id = g.party_id
          left join public.stations st on st.id = g.station_id
         where g.id = :gs_id{lock_sql}
        """,  # noqa: S608 - lock_sql is one of two literals, never user input
        {"gs_id": gs_id},
    )


def queue(session: Session, statuses: tuple[str, ...], q: str | None) -> list[dict[str, Any]]:
    """Goods slips with an OPEN request (any status) or between analysis and Accounts, newest
    request first, then oldest analysed. `q` filters on GS no. / party / station."""
    return _rows(
        session,
        """
        select g.id as gs_id, g.gs_no, g.status, pa.name as party_name, st.name as station_name,
               coalesce((select max(h."at") from public.gs_status_history h
                          where h.gs_id = g.id and h.to_status = g.status), g.created_at) as since,
               r.id as request_id, r.reason as request_reason,
               r.store_name_snapshot as request_store_name, r.requested_at,
               pr.full_name as requested_by_name,
               rms_private.gs_management_approval_state(g.id) as approval_state,
               exists (select 1 from public.rm_item_actions a
                         join public.gs_items gi on gi.id = a.gs_item_id
                        where gi.gs_id = g.id and a.is_current and a.action_code = 'ISSUE_CN')
                 as has_issue_cn,
               coalesce((select array_agg(p.store_code order by p.store_code)
                           from rms_private.gs_store_analysis_progress(g.id) p
                          where p.analysis_status <> 'SUBMITTED'), '{}') as waiting_store_codes
          from public.goods_slips g
          left join public.gs_management_approval_requests r on r.gs_id = g.id and r.status = 'OPEN'
          left join public.profiles pr on pr.id = r.requested_by
          left join public.parties pa on pa.id = g.party_id
          left join public.stations st on st.id = g.station_id
         where (r.id is not null or g.status = any(:statuses))
           and (cast(:q as text) is null
                or g.gs_no ilike :like or pa.name ilike :like or st.name ilike :like)
         order by (r.id is null), r.requested_at desc nulls last, since, g.gs_no
         limit 200
        """,
        {"statuses": list(statuses), "q": q, "like": f"%{q}%" if q else None},
    )


# --- stores + decisions -------------------------------------------------------------------------


def store_progress(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    return _rows(
        session,
        """
        select p.store_id, p.store_code, p.store_name, p.routing_status, p.analysis_status,
               p.submitted_at, pr.full_name as submitted_by_name, a.remarks
          from rms_private.gs_store_analysis_progress(:gs_id) p
          left join public.gs_store_analyses a on a.gs_id = :gs_id and a.store_id = p.store_id
          left join public.profiles pr on pr.id = p.submitted_by
          left join public.intermediate_stores s on s.id = p.store_id
         order by s.sort_order, p.store_code
        """,
        {"gs_id": gs_id},
    )


def groups(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    """G-21 groups of the store flow (item + current condition): qty to decide + decided."""
    return _rows(
        session,
        """
        select g.store_id, s.code as store_code, s.name as store_name,
               g.gs_item_id, g.line_no, g.product_id, g.condition_field_id, g.condition_code,
               g.condition_label, g.sort_order, g.available_qty, g.actioned_qty, gi.received_qty,
               coalesce(gi.product_code_snapshot, pr.code) as product_code,
               coalesce(gi.product_name_snapshot, pr.name, g.item_name) as product_name
          from rms_private.store_analysis_groups(:gs_id) g
          join public.gs_items gi on gi.id = g.gs_item_id
          left join public.products pr on pr.id = g.product_id
          left join public.intermediate_stores s on s.id = g.store_id
         order by g.line_no, g.sort_order, g.condition_label nulls first
        """,
        {"gs_id": gs_id},
    )


def allowed_actions(
    session: Session, product_id: UUID, version_id: UUID | None
) -> list[dict[str, Any]]:
    """The product's resolved ACTION group (Phase 4 resolver, GS profile version; G-18)."""
    return _rows(
        session,
        """
        select code, label, requires_cn, requires_challan, sort_order
          from rms_private.resolve_item_field_profile(:product_id, :version_id)
         where field_group = 'ACTION'
         order by sort_order, code
        """,
        {"product_id": product_id, "version_id": version_id},
    )


def current_actions(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    return _rows(
        session,
        """
        select ra.gs_item_id, ra.condition_field_id, ra.action_code,
               coalesce(ra.action_label, ra.action_code) as label, ra.qty
          from public.rm_item_actions ra
          join public.gs_items gi on gi.id = ra.gs_item_id
         where gi.gs_id = :gs_id and ra.is_current and ra.round_no = 1
         order by gi.line_no, ra.action_code
        """,
        {"gs_id": gs_id},
    )


def max_revision(session: Session, gs_id: UUID) -> int:
    return int(
        session.execute(
            text(
                """
                select coalesce(max(ra.revision_no), 0)
                  from public.rm_item_actions ra
                  join public.gs_items gi on gi.id = ra.gs_item_id
                 where gi.gs_id = :gs_id
                """
            ),
            {"gs_id": gs_id},
        ).scalar_one()
    )


def retire_group(session: Session, gs_item_id: UUID, condition_field_id: UUID | None) -> None:
    session.execute(
        text(
            """
            update public.rm_item_actions
               set is_current = false
             where is_current and round_no = 1 and gs_item_id = :item
               and condition_field_id is not distinct from cast(:cond as uuid)
            """
        ),
        {"item": gs_item_id, "cond": condition_field_id},
    )


def insert_action(
    session: Session,
    *,
    gs_item_id: UUID,
    revision_no: int,
    condition_field_id: UUID | None,
    action_code: str,
    qty: int,
    reason: str,
    decided_by: UUID,
) -> None:
    # G-18 snapshots by trigger: action_label and the condition code / label (DEC-57).
    session.execute(
        text(
            """
            insert into public.rm_item_actions
                   (gs_item_id, revision_no, round_no, condition_field_id, action_code, qty,
                    is_current, reason, decided_by)
            values (:item, :rev, 1, :cond, :code, :qty, true, :reason, :by)
            """
        ),
        {
            "item": gs_item_id,
            "rev": revision_no,
            "cond": condition_field_id,
            "code": action_code,
            "qty": qty,
            "reason": reason,
            "by": decided_by,
        },
    )


def validate_store_analysis(session: Session, gs_id: UUID) -> None:
    """DB G-21 check of the store flow (the deferred trigger checks again at commit)."""
    session.execute(text("select rms_private.validate_store_analysis(:gs_id)"), {"gs_id": gs_id})


# --- Management history -------------------------------------------------------------------------


def insert_revision(
    session: Session, *, gs_id: UUID, revision_no: int, changes: list[dict[str, Any]]
) -> None:
    # The guard (DEC-70) checks Management, the status and a reason per change; stamps the author.
    session.execute(
        text(
            """
            insert into public.gs_management_revisions (gs_id, revision_no, changes)
            values (:gs_id, :rev, cast(:changes as jsonb))
            """
        ),
        {"gs_id": gs_id, "rev": revision_no, "changes": json.dumps(changes)},
    )


def list_revisions(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    return _rows(
        session,
        """
        select m.revision_no, m.changes, m.made_at, pr.full_name as made_by_name
          from public.gs_management_revisions m
          left join public.profiles pr on pr.id = m.made_by
         where m.gs_id = :gs_id
         order by m.revision_no desc
        """,
        {"gs_id": gs_id},
    )


def has_revisions(session: Session, gs_id: UUID) -> bool:
    return bool(
        session.execute(
            text("select exists (select 1 from public.gs_management_revisions where gs_id = :g)"),
            {"g": gs_id},
        ).scalar()
    )


# --- requests -----------------------------------------------------------------------------------


def list_requests(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    return _rows(
        session,
        """
        select r.id, r.store_id, r.store_name_snapshot as store_name, r.reason, r.status,
               r.requested_at, pr.full_name as requested_by_name, r.requested_by,
               r.resolved_at, rp.full_name as resolved_by_name, r.approval_id
          from public.gs_management_approval_requests r
          left join public.profiles pr on pr.id = r.requested_by
          left join public.profiles rp on rp.id = r.resolved_by
         where r.gs_id = :gs_id
         order by r.requested_at desc
        """,
        {"gs_id": gs_id},
    )


# --- approvals ----------------------------------------------------------------------------------


def insert_approval(session: Session, *, gs_id: UUID, remarks: str | None) -> UUID:
    # The guard (DEC-70) computes the snapshot + SHA-256, the approver / role snapshots and the
    # number, links and resolves the open request; the placeholders below are replaced by it.
    return UUID(
        str(
            session.execute(
                text(
                    """
                    insert into public.gs_management_approvals
                           (gs_id, approval_no, approver_name_snapshot, approver_role_snapshot,
                            revision_no, snapshot, snapshot_sha256, remarks)
                    values (:gs_id, 1, '-', '-', 0, '{}'::jsonb, repeat('0', 64), :remarks)
                    returning id
                    """
                ),
                {"gs_id": gs_id, "remarks": remarks},
            ).scalar_one()
        )
    )


_APPROVAL_COLS = """
        a.id, a.gs_id, a.approval_no, a.request_id, a.approver_name_snapshot as approver_name,
        a.approver_role_snapshot as approver_role, a.approved_at, a.revision_no,
        a.snapshot_sha256, a.has_issue_cn, a.remarks,
        a.snapshot::text as snapshot_text,
        rms_private.management_snapshot_sha256(a.snapshot) as stored_snapshot_sha256"""


def list_approvals(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    return _rows(
        session,
        f"""
        select {_APPROVAL_COLS}
          from public.gs_management_approvals a
         where a.gs_id = :gs_id
         order by a.approval_no desc
        """,  # noqa: S608 - constant column list
        {"gs_id": gs_id},
    )


def latest_approval(session: Session, gs_id: UUID) -> dict[str, Any] | None:
    return _row(
        session,
        f"""
        select {_APPROVAL_COLS}
          from public.gs_management_approvals a
         where a.gs_id = :gs_id
         order by a.approval_no desc
         limit 1
        """,  # noqa: S608 - constant column list
        {"gs_id": gs_id},
    )


def current_snapshot(session: Session, gs_id: UUID) -> tuple[str, str]:
    """The canonical snapshot text of the GS now and its DB SHA-256."""
    row = session.execute(
        text(
            """
            select s::text as snapshot_text, rms_private.management_snapshot_sha256(s) as sha
              from rms_private.gs_management_snapshot(:gs_id) s
            """
        ),
        {"gs_id": gs_id},
    ).one()
    return str(row.snapshot_text), str(row.sha)


def approval_state(session: Session, gs_id: UUID) -> str:
    return str(
        session.execute(
            text("select rms_private.gs_management_approval_state(:g)"), {"g": gs_id}
        ).scalar_one()
    )


def gate_problem(session: Session, gs_id: UUID) -> str | None:
    value = session.execute(
        text("select rms_private.gs_management_gate_problem(:g)"), {"g": gs_id}
    ).scalar()
    return str(value) if value is not None else None


def store_role_codes(session: Session, gs_id: UUID) -> list[str]:
    """Roles of the Intermediate Stores with goods on the GS (context recipients)."""
    rows = session.execute(
        text(
            """
            select distinct r.code
              from rms_private.gs_store_analysis_progress(:g) p
              join public.intermediate_stores s on s.id = p.store_id
              join public.roles r on r.id = s.role_id
            """
        ),
        {"g": gs_id},
    ).scalars()
    return sorted(str(r) for r in rows)


def get_setting(session: Session, key: str) -> Any:
    return session.execute(
        text("select value from public.system_settings where key = :key"), {"key": key}
    ).scalar()
