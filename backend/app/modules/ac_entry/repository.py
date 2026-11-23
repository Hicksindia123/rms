"""SQL for the Accounts entry and the Dispatch Slip (change plan 2026-11-12 Phase 8; AMD-18,
AMD-19; G-22). SQL only: the business rules live in the service and in the DB guards."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

DISPATCH_SLIP_TEMPLATE = "DISPATCH_SLIP"
DISPATCH_SLIP_SERIES = "DISPATCH_SLIP"
DISPATCH_SLIP_ENTITY = "dispatch_slips"
AC_SLIP_ENTITY = "ac_action_slips"


def _rows(session: Session, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(r) for r in session.execute(text(sql), params).mappings().all()]


def _row(session: Session, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
    row = session.execute(text(sql), params).mappings().first()
    return dict(row) if row else None


# --- goods slip / A/c Actions slip --------------------------------------------------------------


def get_gs_header(session: Session, gs_id: UUID, *, lock: bool = False) -> dict[str, Any] | None:
    lock_sql = " for update of gs" if lock else ""
    return _row(
        session,
        f"""
        select gs.id, gs.gs_no, gs.status, gs.created_at,
               p.name as party_name, p.code as party_code,
               st.name as station_name, s.name as state_name
          from public.goods_slips gs
          left join public.parties p on p.id = gs.party_id
          left join public.stations st on st.id = gs.station_id
          left join public.states s on s.id = gs.state_id
         where gs.id = :gs_id{lock_sql}
        """,  # noqa: S608 - lock_sql is one of two literals, never user input
        {"gs_id": gs_id},
    )


def current_ac_slip(session: Session, gs_id: UUID) -> dict[str, Any] | None:
    return _row(
        session,
        """
        select id, gs_id, slip_no, version_no, round_no, finalised_at
          from public.ac_action_slips
         where gs_id = :gs_id and status = 'CURRENT'
         order by round_no desc
         limit 1
        """,
        {"gs_id": gs_id},
    )


def get_ac_slip(session: Session, slip_id: UUID) -> dict[str, Any] | None:
    return _row(
        session,
        "select id, gs_id, slip_no, version_no, round_no, status from public.ac_action_slips "
        "where id = :id",
        {"id": slip_id},
    )


def list_queue(session: Session, *, completed: bool | None) -> list[dict[str, Any]]:
    """GS with a CURRENT A/c Actions slip (AMD-17), with Accounts progress per slip."""
    return _rows(
        session,
        """
        select gs.id as gs_id, gs.gs_no, gs.status as gs_status, p.name as party_name,
               s.id as ac_action_slip_id, s.slip_no, s.version_no, s.round_no, s.finalised_at,
               coalesce(e.lines_total, 0)::int as lines_total,
               -- DEC-71: a store-flow goods slip has one Accounts entry for the whole GS.
               case when ge.id is not null then 1
                    else coalesce(e.lines_needing_data, 0)::int end as lines_needing_data,
               case when ge.id is not null
                    then (case when rms_private.ac_gs_entry_complete(ge) then 1 else 0 end)
                    else coalesce(e.lines_complete, 0)::int end as lines_complete,
               ge.id is not null as per_gs,
               coalesce(ge.requires_challan, false) as requires_challan,
               coalesce(ge.requires_cn, false) as requires_cn,
               c.id is not null as is_completed, c.completed_at,
               d.slip_no as dispatch_slip_no, d.status as dispatch_status
          from public.ac_action_slips s
          join public.goods_slips gs on gs.id = s.gs_id
          left join public.parties p on p.id = gs.party_id
          left join lateral (
            select count(*) as lines_total,
                   count(*) filter (where el.requires_cn or el.requires_challan)
                     as lines_needing_data,
                   count(*) filter (where (el.requires_cn or el.requires_challan)
                                      and rms_private.ac_entry_line_complete(el)) as lines_complete
              from public.ac_entry_lines el
             where el.ac_action_slip_id = s.id
          ) e on true
          left join public.ac_gs_entries ge on ge.ac_action_slip_id = s.id
          left join public.ac_entry_completions c on c.ac_action_slip_id = s.id
          left join public.dispatch_slips d on d.ac_action_slip_id = s.id
         where s.status = 'CURRENT'
           and gs.status <> 'CANCELLED'
           and (cast(:completed as boolean) is null
                or (c.id is not null) = cast(:completed as boolean))
         order by (c.id is not null), s.finalised_at asc
         limit 500
        """,
        {"completed": completed},
    )


# --- entry lines --------------------------------------------------------------------------------


def entry_lines(session: Session, ac_slip_id: UUID) -> list[dict[str, Any]]:
    return _rows(
        session,
        """
        select e.id, e.gs_item_id, e.line_no, e.action_code, e.action_label,
               e.condition_label, e.qty,
               e.requires_cn, e.requires_challan, e.cn_no, e.cn_date, e.cn_value,
               e.challan_no, e.challan_date, e.entered_at,
               rms_private.ac_entry_line_complete(e) as is_complete,
               coalesce(gi.product_code_snapshot, pr.code) as product_code,
               coalesce(gi.product_name_snapshot, pr.name, 'Item') as product_name,
               pf.full_name as entered_by_name,
               lib.sort_order as action_sort
          from public.ac_entry_lines e
          join public.gs_items gi on gi.id = e.gs_item_id
          left join public.products pr on pr.id = gi.product_id
          left join public.profiles pf on pf.id = e.entered_by
          left join public.item_field_library lib
                 on lib.field_group = 'ACTION' and lib.code = e.action_code
         where e.ac_action_slip_id = :slip_id
         order by e.line_no, e.condition_label nulls first, coalesce(lib.sort_order, 0),
                  e.action_code
        """,
        {"slip_id": ac_slip_id},
    )


def update_entry_line(
    session: Session,
    *,
    line_id: UUID,
    cn_no: str | None,
    cn_date: date | None,
    cn_value: Decimal | None,
    challan_no: str | None,
    challan_date: date | None,
    by: UUID,
) -> None:
    session.execute(
        text(
            """
            update public.ac_entry_lines
               set cn_no = :cn_no, cn_date = :cn_date, cn_value = :cn_value,
                   challan_no = :challan_no, challan_date = :challan_date,
                   entered_by = :by, entered_at = now()
             where id = :id
            """
        ),
        {
            "id": line_id,
            "cn_no": cn_no,
            "cn_date": cn_date,
            "cn_value": cn_value,
            "challan_no": challan_no,
            "challan_date": challan_date,
            "by": by,
        },
    )


def cn_no_taken_elsewhere(session: Session, *, cn_no: str, gs_id: UUID) -> str | None:
    """DEC-22: the GS number / 'credit note' already holding this CN No., or None."""
    return session.execute(
        text(
            """
            select coalesce(
              (select g.gs_no from public.ac_entry_lines e
                 join public.goods_slips g on g.id = e.gs_id
                where upper(btrim(e.cn_no)) = upper(btrim(:cn_no)) and e.gs_id <> :gs_id
                limit 1),
              (select g.gs_no from public.ac_gs_entries e
                 join public.goods_slips g on g.id = e.gs_id
                where upper(btrim(e.cn_no)) = upper(btrim(:cn_no)) and e.gs_id <> :gs_id
                limit 1),
              (select 'credit note ' || coalesce(cn.cn_no, '') from public.credit_notes cn
                where upper(btrim(cn.cn_no)) = upper(btrim(:cn_no))
                limit 1))
            """
        ),
        {"cn_no": cn_no, "gs_id": gs_id},
    ).scalar()


# --- completion ---------------------------------------------------------------------------------


def get_completion(session: Session, ac_slip_id: UUID) -> dict[str, Any] | None:
    return _row(
        session,
        """
        select c.id, c.completed_at, c.remarks, pf.full_name as completed_by_name
          from public.ac_entry_completions c
          left join public.profiles pf on pf.id = c.completed_by
         where c.ac_action_slip_id = :slip_id
        """,
        {"slip_id": ac_slip_id},
    )


def insert_completion(
    session: Session, *, gs_id: UUID, ac_slip_id: UUID, by: UUID, remarks: str | None
) -> UUID:
    return UUID(
        str(
            session.execute(
                text(
                    """
                    insert into public.ac_entry_completions
                           (gs_id, ac_action_slip_id, completed_by, remarks)
                    values (:gs_id, :slip_id, :by, :remarks)
                    returning id
                    """
                ),
                {"gs_id": gs_id, "slip_id": ac_slip_id, "by": by, "remarks": remarks},
            ).scalar_one()
        )
    )


# --- dispatch slips -----------------------------------------------------------------------------

_DSLIP_SELECT = """
    select d.id, d.gs_id, d.ac_action_slip_id, d.slip_no, d.status, d.attachment_id,
           d.template_version_no, d.content, d.generated_at, d.dispatch_date, d.transporter,
           d.docket_no, d.vehicle_no, d.dispatch_remarks, d.dispatched_at,
           gb.full_name as generated_by_name, db.full_name as dispatched_by_name,
           gs.gs_no, gs.status as gs_status, p.name as party_name,
           s.slip_no as ac_slip_no, s.version_no as ac_version_no, s.round_no as ac_round_no,
           a.bucket, a.object_path,
           (select coalesce(sum(l.qty), 0)::int from public.dispatch_slip_lines l
             where l.dispatch_slip_id = d.id) as total_qty,
           (select count(*)::int from public.print_logs pl
             where pl.template_code = :template and pl.entity_type = :entity
               and pl.entity_id = d.id) as print_count
      from public.dispatch_slips d
      join public.goods_slips gs on gs.id = d.gs_id
      join public.ac_action_slips s on s.id = d.ac_action_slip_id
      join public.attachments a on a.id = d.attachment_id
      left join public.parties p on p.id = gs.party_id
      left join public.profiles gb on gb.id = d.generated_by
      left join public.profiles db on db.id = d.dispatched_by
"""

_DSLIP_PARAMS = {"template": DISPATCH_SLIP_TEMPLATE, "entity": DISPATCH_SLIP_ENTITY}


def get_dispatch_slip(session: Session, slip_id: UUID) -> dict[str, Any] | None:
    return _row(session, _DSLIP_SELECT + " where d.id = :id", {**_DSLIP_PARAMS, "id": slip_id})


def get_dispatch_slip_for_ac_slip(session: Session, ac_slip_id: UUID) -> dict[str, Any] | None:
    return _row(
        session,
        _DSLIP_SELECT + " where d.ac_action_slip_id = :ac",
        {**_DSLIP_PARAMS, "ac": ac_slip_id},
    )


def lock_dispatch_slip(session: Session, slip_id: UUID) -> dict[str, Any] | None:
    return _row(
        session,
        "select id, gs_id, ac_action_slip_id, slip_no, status from public.dispatch_slips "
        "where id = :id for update",
        {"id": slip_id},
    )


def list_dispatch_slips(session: Session, *, status: str | None) -> list[dict[str, Any]]:
    return _rows(
        session,
        _DSLIP_SELECT
        + """
         where (cast(:status as text) is null or d.status = cast(:status as text))
         order by (d.status = 'DISPATCHED'), d.generated_at asc
         limit 500
        """,
        {**_DSLIP_PARAMS, "status": status},
    )


def dispatch_slip_lines(session: Session, slip_id: UUID) -> list[dict[str, Any]]:
    return _rows(
        session,
        """
        select l.id, l.gs_item_id, l.line_no, l.action_code, l.action_label, l.qty,
               l.challan_no, l.challan_date, e.condition_label,
               coalesce(gi.product_code_snapshot, pr.code) as product_code,
               coalesce(gi.product_name_snapshot, pr.name, 'Item') as product_name
          from public.dispatch_slip_lines l
          join public.ac_entry_lines e on e.id = l.ac_entry_line_id
          join public.gs_items gi on gi.id = l.gs_item_id
          left join public.products pr on pr.id = gi.product_id
         where l.dispatch_slip_id = :id
         order by l.line_no, e.condition_label nulls first, l.action_code
        """,
        {"id": slip_id},
    )


def insert_dispatch_slip(
    session: Session,
    *,
    slip_id: UUID,
    gs_id: UUID,
    ac_slip_id: UUID,
    slip_no: str,
    attachment_id: UUID,
    template_version_no: int,
    content: dict[str, Any],
    sha256: str,
    by: UUID,
) -> None:
    session.execute(
        text(
            """
            insert into public.dispatch_slips
                   (id, gs_id, ac_action_slip_id, slip_no, attachment_id, template_code,
                    template_version_no, content, sha256, generated_by)
            values (:id, :gs_id, :ac, :slip_no, :att, :template, :tv, cast(:content as jsonb),
                    :sha, :by)
            """
        ),
        {
            "id": slip_id,
            "gs_id": gs_id,
            "ac": ac_slip_id,
            "slip_no": slip_no,
            "att": attachment_id,
            "template": DISPATCH_SLIP_TEMPLATE,
            "tv": template_version_no,
            "content": json.dumps(content, default=str),
            "sha": sha256,
            "by": by,
        },
    )


def insert_dispatch_slip_line(session: Session, *, slip_id: UUID, entry: dict[str, Any]) -> None:
    session.execute(
        text(
            """
            insert into public.dispatch_slip_lines
                   (dispatch_slip_id, ac_entry_line_id, gs_item_id, line_no, action_code,
                    action_label, qty, challan_no, challan_date)
            values (:slip, :entry, :item, :line_no, :code, :label, :qty, :challan_no,
                    :challan_date)
            """
        ),
        {
            "slip": slip_id,
            "entry": entry["id"],
            "item": entry["gs_item_id"],
            "line_no": entry["line_no"],
            "code": entry["action_code"],
            "label": entry["action_label"],
            "qty": entry["qty"],
            "challan_no": entry["challan_no"],
            "challan_date": entry["challan_date"],
        },
    )


def mark_dispatched(
    session: Session,
    *,
    slip_id: UUID,
    dispatch_date: date,
    transporter: str,
    docket_no: str | None,
    vehicle_no: str | None,
    remarks: str | None,
    by: UUID,
) -> None:
    session.execute(
        text(
            """
            update public.dispatch_slips
               set status = 'DISPATCHED', dispatch_date = :dd, transporter = :tr,
                   docket_no = :docket, vehicle_no = :vehicle, dispatch_remarks = :remarks,
                   dispatched_by = :by, dispatched_at = now()
             where id = :id and status = 'READY'
            """
        ),
        {
            "id": slip_id,
            "dd": dispatch_date,
            "tr": transporter,
            "docket": docket_no,
            "vehicle": vehicle_no,
            "remarks": remarks,
            "by": by,
        },
    )


# --- stock helpers ------------------------------------------------------------------------------


def find_lot_for_item(session: Session, gs_item_id: UUID) -> UUID | None:
    """The GS item's own lot (AS_RECEIVED from Phase 5, else its oldest lot)."""
    value = session.execute(
        text(
            """
            select id from public.stock_lots
             where gs_item_id = :item
             order by (condition_class = 'AS_RECEIVED') desc, created_at asc
             limit 1
            """
        ),
        {"item": gs_item_id},
    ).scalar()
    return UUID(str(value)) if value else None


# --- attachments / print / config ---------------------------------------------------------------


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
                    "entity": DISPATCH_SLIP_ENTITY,
                    "entity_id": entity_id,
                    "bucket": bucket,
                    "path": object_path,
                    "size": size_bytes,
                    "by": by,
                },
            ).scalar_one()
        )
    )


def insert_print_log(
    session: Session, *, slip_id: UUID, by: UUID, metadata: dict[str, Any]
) -> None:
    session.execute(
        text(
            """
            insert into public.print_logs
                   (template_code, entity_type, entity_id, revision_no, printed_by, metadata)
            values (:template, :entity, :id, 1, :by, cast(:meta as jsonb))
            """
        ),
        {
            "template": DISPATCH_SLIP_TEMPLATE,
            "entity": DISPATCH_SLIP_ENTITY,
            "id": slip_id,
            "by": by,
            "meta": json.dumps(metadata, default=str),
        },
    )


def next_number(session: Session, series_code: str) -> str:
    return str(
        session.execute(
            text("select rms_private.next_number(:code)"), {"code": series_code}
        ).scalar_one()
    )


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


# =================================================================================================
# DEC-71 (Phase P11): Accounts gate, Replacement Slip per goods slip, one Challan / CN per GS
# =================================================================================================

AC_SLIP_TEMPLATE = "AC_ACTIONS_SLIP"
AC_SLIP_SERIES = "AC_ACTION_SLIP"


def _flag(session: Session, sql: str, gs_id: UUID) -> bool:
    return bool(session.execute(text(sql), {"g": gs_id}).scalar())


def gs_on_store_flow(session: Session, gs_id: UUID) -> bool:
    return _flag(session, "select rms_private.gs_on_store_flow(:g)", gs_id)


def gs_needs_accounts(session: Session, gs_id: UUID) -> bool:
    return _flag(session, "select rms_private.gs_needs_accounts(:g)", gs_id)


def gs_store_analysis_complete(session: Session, gs_id: UUID) -> bool:
    return _flag(session, "select rms_private.gs_store_analysis_complete(:g)", gs_id)


def get_gs_print_header(session: Session, gs_id: UUID) -> dict[str, Any] | None:
    return _row(
        session,
        """
        select gs.id, gs.gs_no, gs.status, gs.created_at, gs.carton_count,
               gs.return_type_code, rt.label as return_type_label,
               gs.gate_entry_no, gs.gate_entry_date, gs.missing_documentation,
               p.name as party_name, p.code as party_code,
               st.name as station_name, s.name as state_name
          from public.goods_slips gs
          left join public.parties p on p.id = gs.party_id
          left join public.stations st on st.id = gs.station_id
          left join public.states s on s.id = gs.state_id
          left join public.option_sets os on os.code = 'RETURN_TYPE'
          left join public.option_items rt
                 on rt.option_set_id = os.id and rt.code = gs.return_type_code
         where gs.id = :gs_id
        """,
        {"gs_id": gs_id},
    )


def list_gate_documents(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    return _rows(
        session,
        """
        select doc_type_label, doc_no, doc_date
          from public.gs_gate_documents
         where gs_id = :gs_id
         order by sort_order, created_at
        """,
        {"gs_id": gs_id},
    )


def store_flow_slip_lines(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    """Current decisions of a store-flow goods slip per item + condition + action (DEC-69/70),
    with the item's store, product snapshot and the ACTION library flags / order (AMD-18)."""
    return _rows(
        session,
        """
        select gi.id as gs_item_id, gi.line_no, gi.received_qty,
               coalesce(gi.product_code_snapshot, pr.code) as product_code,
               coalesce(gi.product_name_snapshot, pr.name, 'Item') as product_name,
               s.code as store_code, s.name as store_name,
               a.condition_code, a.condition_label, a.action_code,
               coalesce(a.action_label, lib.label, a.action_code) as action_label, a.qty,
               coalesce(lib.requires_cn, false) as requires_cn,
               coalesce(lib.requires_challan, false) as requires_challan,
               coalesce(lib.sort_order, 0) as action_sort
          from public.rm_item_actions a
          join public.gs_items gi on gi.id = a.gs_item_id
          left join public.products pr on pr.id = gi.product_id
          left join public.intermediate_stores s on s.id = rms_private.gs_item_store(gi.id)
          left join public.item_field_library cl on cl.id = a.condition_field_id
          left join public.item_field_library lib
                 on lib.field_group = 'ACTION' and lib.code = a.action_code
         where gi.gs_id = :gs_id and a.is_current and a.qty > 0
         order by gi.line_no, coalesce(cl.sort_order, 0), a.condition_label nulls first,
                  coalesce(lib.sort_order, 0), a.action_code
        """,
        {"gs_id": gs_id},
    )


def max_revision(session: Session, gs_id: UUID) -> int:
    return int(
        session.execute(
            text(
                """
                select coalesce(max(a.revision_no), 0)
                  from public.rm_item_actions a
                  join public.gs_items gi on gi.id = a.gs_item_id
                 where gi.gs_id = :gs_id
                """
            ),
            {"gs_id": gs_id},
        ).scalar_one()
    )


def latest_slip_identity(session: Session, gs_id: UUID) -> dict[str, Any] | None:
    return _row(
        session,
        "select slip_no, version_no from public.ac_action_slips where gs_id = :gs_id "
        "order by version_no desc limit 1",
        {"gs_id": gs_id},
    )


def insert_slip_pdf(
    session: Session,
    *,
    gs_id: UUID,
    entity_id: UUID,
    bucket: str,
    object_path: str,
    size_bytes: int,
    by: UUID,
) -> UUID:
    """The Replacement Slip PDF (entity ac_action_slips), confirmed at once."""
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


def insert_ac_slip(
    session: Session,
    *,
    slip_id: UUID,
    gs_id: UUID,
    slip_no: str,
    version_no: int,
    revision_no: int,
    attachment_id: UUID,
    template_version_no: int,
    content: dict[str, Any],
    totals: dict[str, Any],
    sha256: str,
    by: UUID,
) -> None:
    session.execute(
        text(
            """
            insert into public.ac_action_slips
                   (id, gs_id, slip_no, version_no, revision_no, round_no, attachment_id,
                    template_code, template_version_no, content, totals, sha256, finalised_by)
            values (:id, :gs_id, :slip_no, :version_no, :revision_no, 1, :attachment_id,
                    :template, :template_version_no, cast(:content as jsonb),
                    cast(:totals as jsonb), :sha256, :by)
            """
        ),
        {
            "id": slip_id,
            "gs_id": gs_id,
            "slip_no": slip_no,
            "version_no": version_no,
            "revision_no": revision_no,
            "attachment_id": attachment_id,
            "template": AC_SLIP_TEMPLATE,
            "template_version_no": template_version_no,
            "content": json.dumps(content, default=str),
            "totals": json.dumps(totals),
            "sha256": sha256,
            "by": by,
        },
    )


def supersede_ac_slip(session: Session, slip_id: UUID, *, by: UUID, reason: str) -> None:
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


def ac_slip_file(session: Session, gs_id: UUID, slip_id: UUID) -> dict[str, Any] | None:
    return _row(
        session,
        """
        select s.id, s.slip_no, s.version_no, s.status, a.bucket, a.object_path,
               (select count(*)::int from public.print_logs pl
                 where pl.template_code = :template and pl.entity_type = :entity
                   and pl.entity_id = s.id) as print_count
          from public.ac_action_slips s
          join public.attachments a on a.id = s.attachment_id
         where s.gs_id = :gs_id and s.id = :id
        """,
        {"gs_id": gs_id, "id": slip_id, "template": AC_SLIP_TEMPLATE, "entity": AC_SLIP_ENTITY},
    )


def insert_ac_slip_print_log(
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


def get_gs_entry(session: Session, ac_slip_id: UUID) -> dict[str, Any] | None:
    return _row(
        session,
        """
        select e.id, e.requires_challan, e.requires_cn, e.challan_no, e.challan_date,
               e.cn_no, e.cn_date, e.cn_value, e.entered_at,
               rms_private.ac_gs_entry_complete(e) as is_complete,
               pf.full_name as entered_by_name
          from public.ac_gs_entries e
          left join public.profiles pf on pf.id = e.entered_by
         where e.ac_action_slip_id = :slip_id
        """,
        {"slip_id": ac_slip_id},
    )


def update_gs_entry(
    session: Session,
    *,
    ac_slip_id: UUID,
    challan_no: str | None,
    challan_date: date | None,
    cn_no: str | None,
    cn_date: date | None,
    cn_value: Decimal | None,
    by: UUID,
) -> None:
    session.execute(
        text(
            """
            update public.ac_gs_entries
               set challan_no = :challan_no, challan_date = :challan_date,
                   cn_no = :cn_no, cn_date = :cn_date, cn_value = :cn_value,
                   entered_by = :by, entered_at = now()
             where ac_action_slip_id = :slip_id
            """
        ),
        {
            "slip_id": ac_slip_id,
            "challan_no": challan_no,
            "challan_date": challan_date,
            "cn_no": cn_no,
            "cn_date": cn_date,
            "cn_value": cn_value,
            "by": by,
        },
    )


def item_store_locations(session: Session, gs_id: UUID) -> dict[UUID, str]:
    """DEC-71: per GS item, the inventory location code of its Intermediate Store (where its
    returned pieces wait until the Accounts / dispatch settlement)."""
    rows = _rows(
        session,
        """
        select gi.id as gs_item_id, loc.code as location_code
          from public.gs_items gi
          join public.intermediate_stores s on s.id = rms_private.gs_item_store(gi.id)
          join public.inventory_locations loc on loc.id = s.location_id
         where gi.gs_id = :gs_id
        """,
        {"gs_id": gs_id},
    )
    return {r["gs_item_id"]: str(r["location_code"]) for r in rows}


def list_hold(session: Session) -> list[dict[str, Any]]:
    """DEC-71 (Q21): goods slips on hold because every decision is Not Allowed."""
    return _rows(
        session,
        """
        select g.id as gs_id, g.gs_no, g.status as gs_status, p.name as party_name,
               coalesce((select max(h."at") from public.gs_status_history h
                          where h.gs_id = g.id and h.to_status = g.status), g.created_at)
                 as since,
               (select coalesce(sum(a.qty), 0)::int from public.rm_item_actions a
                  join public.gs_items gi on gi.id = a.gs_item_id
                 where gi.gs_id = g.id and a.is_current) as total_qty
          from public.goods_slips g
          left join public.parties p on p.id = g.party_id
         where g.status = 'NOT_ALLOWED_HOLD'
         order by since
         limit 500
        """,
        {},
    )
