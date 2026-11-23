"""SQL for RM Final Actions and the A/c Actions slip (change plan 2026-11-12 Phase 7; AMD-16,
AMD-17; G-20; G-21). SQL only: the business rules live in the service and in the DB guards."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

AC_SLIP_TEMPLATE = "AC_ACTIONS_SLIP"
AC_SLIP_SERIES = "AC_ACTION_SLIP"
AC_SLIP_ENTITY = "ac_action_slips"


def _rows(session: Session, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(r) for r in session.execute(text(sql), params).mappings().all()]


def _row(session: Session, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
    row = session.execute(text(sql), params).mappings().first()
    return dict(row) if row else None


# --- goods slip ---------------------------------------------------------------------------------


def get_gs_header(session: Session, gs_id: UUID, *, lock: bool = False) -> dict[str, Any] | None:
    lock_sql = " for update of gs" if lock else ""
    return _row(
        session,
        f"""
        select gs.id, gs.gs_no, gs.status, gs.created_at, gs.carton_count,
               gs.return_type_code, rt.label as return_type_label,
               gs.gate_entry_no, gs.gate_entry_date, gs.missing_documentation,
               gs.item_field_profile_version_id, gs.transfer_slip_id,
               p.name as party_name, p.code as party_code,
               st.name as station_name, s.name as state_name
          from public.goods_slips gs
          left join public.parties p on p.id = gs.party_id
          left join public.stations st on st.id = gs.station_id
          left join public.states s on s.id = gs.state_id
          left join public.option_sets os on os.code = 'RETURN_TYPE'
          left join public.option_items rt
                 on rt.option_set_id = os.id and rt.code = gs.return_type_code
         where gs.id = :gs_id{lock_sql}
        """,  # noqa: S608 - lock_sql is one of two literals, never user input
        {"gs_id": gs_id},
    )


def is_on_final_action_flow(session: Session, gs_id: UUID) -> bool:
    return bool(
        session.execute(
            text("select rms_private.gs_on_final_action_flow(:gs_id)"), {"gs_id": gs_id}
        ).scalar()
    )


def list_gate_documents(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    return _rows(
        session,
        """
        select doc_type_code, doc_type_label, doc_no, doc_date
          from public.gs_gate_documents
         where gs_id = :gs_id
         order by sort_order, created_at
        """,
        {"gs_id": gs_id},
    )


# --- items, quantities, profile -----------------------------------------------------------------


def item_quantities(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    """G-21 quantities per item from the DB function (counted, at departments, available,
    actioned), with the product code / name snapshot."""
    return _rows(
        session,
        """
        select q.gs_item_id, q.line_no, q.item_name, q.product_id, q.counted_qty, q.at_dept_qty,
               q.available_qty, q.actioned_qty,
               coalesce(gi.product_code_snapshot, pr.code) as product_code,
               coalesce(gi.product_name_snapshot, pr.name, q.item_name) as product_name
          from rms_private.final_action_item_quantities(:gs_id) q
          join public.gs_items gi on gi.id = q.gs_item_id
          left join public.products pr on pr.id = q.product_id
         order by q.line_no
        """,
        {"gs_id": gs_id},
    )


def outcome_breakdown(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    """Qty booked into terminal outcome heads per item (DEC-43; re-route heads excluded)."""
    return _rows(
        session,
        """
        select rl.gs_item_id, rcl.outcome_code, rcl.outcome_label, rcl.is_wastage,
               sum(rcl.quantity)::int as qty
          from public.department_receipt_lines rcl
          join public.department_routing_lines rl on rl.id = rcl.routing_line_id
          join public.department_routings r on r.id = rl.routing_id
         where r.gs_id = :gs_id
           and not rcl.returns_to_routing
         group by rl.gs_item_id, rcl.outcome_code, rcl.outcome_label, rcl.is_wastage
         order by rcl.outcome_label
        """,
        {"gs_id": gs_id},
    )


def condition_quantities(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    """DEC-57: round-1 G-21 quantities per item + current condition (NULL = item without split)."""
    return _rows(
        session,
        """
        select gs_item_id, line_no, condition_field_id, condition_code, condition_label,
               current_qty, at_dept_qty, available_qty, actioned_qty
          from rms_private.final_action_condition_quantities(:gs_id)
        """,
        {"gs_id": gs_id},
    )


def action_groups(
    session: Session, gs_id: UUID, round_no: int, action_code: str
) -> list[dict[str, Any]]:
    """Current qty of one action in one round, per item + condition (DEC-57: Pending pieces)."""
    return _rows(
        session,
        """
        select ra.gs_item_id, gi.line_no, ra.condition_field_id,
               max(ra.condition_code) as condition_code,
               max(ra.condition_label) as condition_label,
               sum(ra.qty)::int as qty
          from public.rm_item_actions ra
          join public.gs_items gi on gi.id = ra.gs_item_id
         where gi.gs_id = :gs_id and ra.is_current and ra.round_no = :round
           and ra.action_code = :code
         group by ra.gs_item_id, gi.line_no, ra.condition_field_id
         order by gi.line_no, max(ra.condition_label)
        """,
        {"gs_id": gs_id, "round": round_no, "code": action_code},
    )


def max_round(session: Session, gs_id: UUID) -> int:
    return int(
        session.execute(
            text(
                """
                select coalesce(max(ra.round_no), 0)
                  from public.rm_item_actions ra
                  join public.gs_items gi on gi.id = ra.gs_item_id
                 where gi.gs_id = :gs_id and ra.is_current
                """
            ),
            {"gs_id": gs_id},
        ).scalar_one()
    )


def round_settled(session: Session, gs_id: UUID, round_no: int) -> bool:
    return bool(
        session.execute(
            text("select rms_private.final_action_round_settled(:gs_id, :round)"),
            {"gs_id": gs_id, "round": round_no},
        ).scalar()
    )


def current_conditions(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    """DEC-56: current condition split per item (counting split until the first receipt)."""
    return _rows(
        session,
        """
        select gi.id as gs_item_id, c.field_code, c.field_label, c.original_qty, c.current_qty
          from public.gs_items gi
          cross join lateral rms_private.item_current_conditions(gi.id) c
         where gi.gs_id = :gs_id
         order by gi.line_no, c.sort_order, c.field_label
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
        """,
        {"product_id": product_id, "version_id": version_id},
    )


def action_library_labels(session: Session) -> dict[str, dict[str, Any]]:
    rows = _rows(
        session,
        """
        select code, label, requires_cn, requires_challan, sort_order
          from public.item_field_library
         where field_group = 'ACTION'
        """,
        {},
    )
    return {r["code"]: r for r in rows}


# --- RM action rows -----------------------------------------------------------------------------


def current_actions(session: Session, gs_id: UUID, round_no: int) -> list[dict[str, Any]]:
    """Current action rows of one round (DEC-57), with their condition snapshot."""
    return _rows(
        session,
        """
        select ra.gs_item_id, ra.action_code, coalesce(ra.action_label, ra.action_code) as label,
               ra.qty, ra.revision_no, ra.decided_by, ra.decided_at, ra.round_no,
               ra.condition_field_id, ra.condition_code, ra.condition_label
          from public.rm_item_actions ra
          join public.gs_items gi on gi.id = ra.gs_item_id
          left join public.item_field_library cl on cl.id = ra.condition_field_id
         where gi.gs_id = :gs_id and ra.is_current and ra.round_no = :round
         order by gi.line_no, coalesce(cl.sort_order, 0), ra.condition_label nulls first,
                  ra.action_code
        """,
        {"gs_id": gs_id, "round": round_no},
    )


def revision_rows(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    return _rows(
        session,
        """
        select ra.revision_no, ra.round_no, ra.reason, ra.decided_at,
               pr.full_name as decided_by_name,
               gi.line_no, ra.action_code, coalesce(ra.action_label, ra.action_code) as label,
               ra.condition_label, ra.qty
          from public.rm_item_actions ra
          join public.gs_items gi on gi.id = ra.gs_item_id
          left join public.profiles pr on pr.id = ra.decided_by
         where gi.gs_id = :gs_id
         order by ra.revision_no desc, gi.line_no, ra.condition_label nulls first, ra.action_code
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


def retire_current_actions(session: Session, gs_id: UUID, round_no: int) -> None:
    session.execute(
        text(
            """
            update public.rm_item_actions
               set is_current = false
             where is_current and round_no = :round
               and gs_item_id in (select id from public.gs_items where gs_id = :gs_id)
            """
        ),
        {"gs_id": gs_id, "round": round_no},
    )


def insert_action(
    session: Session,
    *,
    gs_item_id: UUID,
    revision_no: int,
    round_no: int,
    condition_field_id: UUID | None,
    action_code: str,
    qty: int,
    reason: str | None,
    decided_by: UUID,
) -> None:
    # G-18 snapshots by trigger: action_label (rm_item_actions_label_snapshot) and the condition
    # code / label (rm_item_actions_final_guard, DEC-57).
    session.execute(
        text(
            """
            insert into public.rm_item_actions
                   (gs_item_id, revision_no, round_no, condition_field_id, action_code, qty,
                    is_current, reason, decided_by)
            values (:item, :rev, :round, :cond, :code, :qty, true, :reason, :by)
            """
        ),
        {
            "item": gs_item_id,
            "rev": revision_no,
            "round": round_no,
            "cond": condition_field_id,
            "code": action_code,
            "qty": qty,
            "reason": reason,
            "by": decided_by,
        },
    )


def validate_split(session: Session, gs_id: UUID, *, complete: bool) -> None:
    """DB G-21 check now (the deferred trigger checks again at commit)."""
    session.execute(
        text("select rms_private.validate_final_action_split(:gs_id, :complete)"),
        {"gs_id": gs_id, "complete": complete},
    )


def validate_reconciliation(session: Session, gs_id: UUID) -> None:
    """DB G-20 check (raises a 'G-20: …' DB error on violation)."""
    session.execute(
        text("select rms_private.validate_department_reconciliation(:gs_id)"), {"gs_id": gs_id}
    )


# --- slips --------------------------------------------------------------------------------------

_SLIP_SELECT = """
    select s.id, s.gs_id, s.slip_no, s.version_no, s.revision_no, s.round_no, s.status,
           s.attachment_id,
           exists (select 1 from public.ac_entry_completions c
                    where c.ac_action_slip_id = s.id) as is_completed,
           s.template_version_no, s.totals, s.remarks, s.finalised_at, s.superseded_at,
           s.supersede_reason, fb.full_name as finalised_by_name,
           sb.full_name as superseded_by_name,
           a.bucket, a.object_path,
           (select count(*)::int from public.print_logs pl
             where pl.template_code = :template and pl.entity_type = :entity
               and pl.entity_id = s.id) as print_count
      from public.ac_action_slips s
      join public.attachments a on a.id = s.attachment_id
      left join public.profiles fb on fb.id = s.finalised_by
      left join public.profiles sb on sb.id = s.superseded_by
"""


def list_slips(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    return _rows(
        session,
        _SLIP_SELECT + " where s.gs_id = :gs_id order by s.version_no desc",
        {"gs_id": gs_id, "template": AC_SLIP_TEMPLATE, "entity": AC_SLIP_ENTITY},
    )


def get_slip(session: Session, gs_id: UUID, slip_id: UUID) -> dict[str, Any] | None:
    return _row(
        session,
        _SLIP_SELECT + " where s.gs_id = :gs_id and s.id = :slip_id",
        {
            "gs_id": gs_id,
            "slip_id": slip_id,
            "template": AC_SLIP_TEMPLATE,
            "entity": AC_SLIP_ENTITY,
        },
    )


def current_slip(session: Session, gs_id: UUID, round_no: int) -> dict[str, Any] | None:
    """The CURRENT slip of one final-action round (DEC-57: one per round)."""
    return _row(
        session,
        _SLIP_SELECT + " where s.gs_id = :gs_id and s.round_no = :round and s.status = 'CURRENT'",
        {
            "gs_id": gs_id,
            "round": round_no,
            "template": AC_SLIP_TEMPLATE,
            "entity": AC_SLIP_ENTITY,
        },
    )


def latest_slip_identity(session: Session, gs_id: UUID) -> dict[str, Any] | None:
    return _row(
        session,
        """
        select slip_no, version_no from public.ac_action_slips
         where gs_id = :gs_id order by version_no desc limit 1
        """,
        {"gs_id": gs_id},
    )


def next_number(session: Session, series_code: str) -> str:
    return str(
        session.execute(
            text("select rms_private.next_number(:code)"), {"code": series_code}
        ).scalar_one()
    )


def supersede_slip(session: Session, slip_id: UUID, *, by: UUID, reason: str) -> None:
    session.execute(
        text(
            """
            update public.ac_action_slips
               set status = 'SUPERSEDED', superseded_at = now(), superseded_by = :by,
                   supersede_reason = :reason
             where id = :id and status = 'CURRENT'
            """
        ),
        {"id": slip_id, "by": by, "reason": reason},
    )


def insert_generated_pdf(
    session: Session,
    *,
    gs_id: UUID,
    entity_id: UUID,
    bucket: str,
    object_path: str,
    size_bytes: int,
    by: UUID,
) -> UUID:
    return UUID(
        str(
            session.execute(
                text(
                    """
                    insert into public.attachments
                           (gs_id, entity_type, entity_id, kind, bucket, object_path, mime_type,
                            size_bytes, status, uploaded_by, confirmed_by, confirmed_at)
                    values (:gs_id, :entity, :entity_id, 'GENERATED_PDF', :bucket, :path,
                            'application/pdf', :size, 'CONFIRMED', :by, :by, now())
                    returning id
                    """
                ),
                {
                    "gs_id": gs_id,
                    "entity": AC_SLIP_ENTITY,
                    "entity_id": entity_id,
                    "bucket": bucket,
                    "path": object_path,
                    "size": size_bytes,
                    "by": by,
                },
            ).scalar_one()
        )
    )


def insert_slip(
    session: Session,
    *,
    slip_id: UUID,
    gs_id: UUID,
    slip_no: str,
    version_no: int,
    revision_no: int,
    round_no: int,
    attachment_id: UUID,
    template_version_no: int,
    content: dict[str, Any],
    totals: dict[str, Any],
    sha256: str,
    remarks: str | None,
    by: UUID,
) -> None:
    session.execute(
        text(
            """
            insert into public.ac_action_slips
                   (id, gs_id, slip_no, version_no, revision_no, round_no, attachment_id,
                    template_code, template_version_no, content, totals, sha256, remarks,
                    finalised_by)
            values (:id, :gs_id, :slip_no, :version_no, :revision_no, :round_no, :attachment_id,
                    :template, :template_version_no, cast(:content as jsonb),
                    cast(:totals as jsonb), :sha256, :remarks, :by)
            """
        ),
        {
            "id": slip_id,
            "gs_id": gs_id,
            "slip_no": slip_no,
            "version_no": version_no,
            "revision_no": revision_no,
            "round_no": round_no,
            "attachment_id": attachment_id,
            "template": AC_SLIP_TEMPLATE,
            "template_version_no": template_version_no,
            "content": json.dumps(content, default=str),
            "totals": json.dumps(totals),
            "sha256": sha256,
            "remarks": remarks,
            "by": by,
        },
    )


def insert_print_log(
    session: Session, *, slip_id: UUID, version_no: int, by: UUID, metadata: dict[str, Any]
) -> None:
    session.execute(
        text(
            """
            insert into public.print_logs
                   (template_code, entity_type, entity_id, revision_no, printed_by, metadata)
            values (:template, :entity, :id, :version_no, :by, cast(:meta as jsonb))
            """
        ),
        {
            "template": AC_SLIP_TEMPLATE,
            "entity": AC_SLIP_ENTITY,
            "id": slip_id,
            "version_no": version_no,
            "by": by,
            "meta": json.dumps(metadata, default=str),
        },
    )


# --- config -------------------------------------------------------------------------------------


def published_template(session: Session, code: str) -> dict[str, Any] | None:
    return _row(
        session,
        """
        select code, name, version_no, coalesce(snapshot, layout) as layout
          from public.print_templates
         where code = :code and status = 'PUBLISHED'
        """,
        {"code": code},
    )


def get_setting(session: Session, key: str) -> Any:
    return session.execute(
        text("select value from public.system_settings where key = :key"), {"key": key}
    ).scalar()


# --- DEC-69 (Phase P9): analysis by the Intermediate Store user ---------------------------------


def store_analysis_progress(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    """Per store on the GS: routing progress (P7/P8) and analysis state, with the submitter."""
    return _rows(
        session,
        """
        select p.store_id, p.store_code, p.store_name, p.routing_status, p.analysis_status,
               p.submitted_at, pr.full_name as submitted_by_name, a.remarks, a.total_qty
          from rms_private.gs_store_analysis_progress(:gs_id) p
          left join public.gs_store_analyses a on a.gs_id = :gs_id and a.store_id = p.store_id
          left join public.profiles pr on pr.id = p.submitted_by
          left join public.intermediate_stores s on s.id = p.store_id
         order by s.sort_order, p.store_code
        """,
        {"gs_id": gs_id},
    )


def store_analysis_groups(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    """G-21 groups of the store flow (item + current condition) with the store of the item."""
    return _rows(
        session,
        """
        select g.store_id, s.code as store_code, s.name as store_name,
               g.gs_item_id, g.line_no, g.product_id, g.condition_field_id, g.condition_code,
               g.condition_label, g.sort_order, g.current_qty, g.at_dept_qty, g.available_qty,
               g.actioned_qty, gi.received_qty,
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


def get_store(session: Session, store_id: UUID) -> dict[str, Any] | None:
    return _row(
        session,
        """
        select s.id, s.code, s.name, s.role_id, r.code as role_code
          from public.intermediate_stores s
          left join public.roles r on r.id = s.role_id
         where s.id = :id
        """,
        {"id": store_id},
    )


def user_store_ids(session: Session, user_id: UUID) -> list[UUID]:
    """Stores whose own role the user holds (Management is not a store user, DEC-66)."""
    rows = session.execute(
        text(
            """
            select s.id from public.intermediate_stores s
              join public.user_roles ur on ur.role_id = s.role_id
             where ur.user_id = :uid
            """
        ),
        {"uid": user_id},
    ).scalars()
    return [UUID(str(r)) for r in rows]


def user_acts_for_store(session: Session, user_id: UUID, store_id: UUID) -> bool:
    return bool(
        session.execute(
            text("select rms_private.user_acts_for_store(:u, :s)"), {"u": user_id, "s": store_id}
        ).scalar_one()
    )


def insert_store_analysis(
    session: Session,
    *,
    gs_id: UUID,
    store_id: UUID,
    totals: list[dict[str, Any]],
    remarks: str | None,
) -> None:
    # The guard (DEC-69) checks the store, the status and G-21, and stamps the snapshots,
    # revision, total and submitter; the placeholders below are overwritten by it.
    session.execute(
        text(
            """
            insert into public.gs_store_analyses
                   (gs_id, store_id, store_code_snapshot, store_name_snapshot, revision_no,
                    total_qty, totals, remarks)
            values (:gs_id, :store_id, '-', '-', 1, 1, cast(:totals as jsonb), :remarks)
            """
        ),
        {"gs_id": gs_id, "store_id": store_id, "totals": json.dumps(totals), "remarks": remarks},
    )


def gs_store_analysis_complete(session: Session, gs_id: UUID) -> bool:
    return bool(
        session.execute(
            text("select rms_private.gs_store_analysis_complete(:gs_id)"), {"gs_id": gs_id}
        ).scalar()
    )


def validate_store_analysis(session: Session, gs_id: UUID) -> None:
    """DB G-21 check of the store flow (the deferred trigger checks again at commit)."""
    session.execute(text("select rms_private.validate_store_analysis(:gs_id)"), {"gs_id": gs_id})


def store_analysis_queue(session: Session, statuses: tuple[str, ...]) -> list[dict[str, Any]]:
    """Goods slips in the store analysis stage (party-wise), oldest first."""
    return _rows(
        session,
        """
        select g.id as gs_id, g.gs_no, g.status, pa.name as party_name, st.name as station_name,
               coalesce((select max(h."at") from public.gs_status_history h
                          where h.gs_id = g.id and h.to_status = g.status), g.created_at) as since,
               exists (select 1 from public.gs_management_approval_requests r
                        where r.gs_id = g.id and r.status = 'OPEN') as approval_requested
          from public.goods_slips g
          left join public.parties pa on pa.id = g.party_id
          left join public.stations st on st.id = g.station_id
         where g.status = any(:statuses)
         order by since, g.gs_no
        """,
        {"statuses": list(statuses)},
    )


def list_approval_requests(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    return _rows(
        session,
        """
        select r.id, r.store_id, r.store_name_snapshot as store_name, r.reason, r.status,
               r.requested_at, pr.full_name as requested_by_name
          from public.gs_management_approval_requests r
          left join public.profiles pr on pr.id = r.requested_by
         where r.gs_id = :gs_id
         order by r.requested_at desc
        """,
        {"gs_id": gs_id},
    )


def insert_approval_request(session: Session, *, gs_id: UUID, store_id: UUID, reason: str) -> UUID:
    # The guard (DEC-69) checks the store user and the status and stamps the snapshot.
    return UUID(
        str(
            session.execute(
                text(
                    """
                    insert into public.gs_management_approval_requests
                           (gs_id, store_id, store_name_snapshot, reason)
                    values (:gs_id, :store_id, '-', :reason)
                    returning id
                    """
                ),
                {"gs_id": gs_id, "store_id": store_id, "reason": reason},
            ).scalar_one()
        )
    )
