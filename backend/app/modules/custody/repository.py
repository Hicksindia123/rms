"""Custody transfer repository: SQL only, no business rules (P2-04; extended by P3-01)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

_TRANSFER_COLUMNS = """
  t.id, t.transfer_no, t.gs_id, g.gs_no, t.purpose_code, t.with_packaging, t.stock_moved,
  t.stock_moved_at, t.status, t.mode_code, t.notes, t.from_location_id,
  fl.code as from_location_code,
  fl.name as from_location_name, fl.custodian_role_id as from_custodian_role_id,
  fl.custodian_user_id as from_custodian_user_id, t.to_location_id, tl.code as to_location_code,
  tl.name as to_location_name, tl.custodian_role_id as to_custodian_role_id,
  tl.custodian_user_id as to_custodian_user_id, t.transit_location_id, t.initiated_by,
  ib.full_name as initiated_by_name, t.initiated_at, t.accepted_by,
  ab.full_name as accepted_by_name,
  t.accepted_at, t.acceptance_code, t.discrepancy_notes, t.supersedes_transfer_id,
  t.initiate_form_version_id, t.accept_form_version_id, t.labels_snapshot, t.receiver_task_id,
  t.cancelled_by, t.cancelled_at, t.cancel_reason, t.resolution_code, t.reconciled_at, t.created_at
"""
_TRANSFER_FROM = """
  from public.custody_transfers t
  join public.inventory_locations fl on fl.id = t.from_location_id
  join public.inventory_locations tl on tl.id = t.to_location_id
  left join public.goods_slips g on g.id = t.gs_id
  left join public.profiles ib on ib.id = t.initiated_by
  left join public.profiles ab on ab.id = t.accepted_by
"""


def next_transfer_no(session: Session, timezone: str) -> str:
    return str(
        session.execute(
            text(
                "select rms_private.next_number('TRANSFER', "
                "(now() at time zone cast(:tz as text))::date)"
            ),
            {"tz": timezone},
        ).scalar_one()
    )


def get_setting(session: Session, key: str) -> Any:
    return session.execute(
        text("select value from public.system_settings where key = :key"), {"key": key}
    ).scalar()


def insert_transfer(
    session: Session,
    *,
    transfer_no: str,
    gs_id: UUID | None,
    from_location_id: UUID,
    to_location_id: UUID,
    mode_code: str,
    purpose_code: str | None,
    with_packaging: bool,
    notes: str | None,
    by: UUID,
    supersedes_transfer_id: UUID | None = None,
    initiate_form_version_id: UUID | None = None,
    labels_snapshot: dict[str, Any] | None = None,
) -> UUID:
    return UUID(
        str(
            session.execute(
                text(
                    """
                    insert into public.custody_transfers (
                      transfer_no, gs_id, from_location_id, to_location_id, mode_code,
                      purpose_code, with_packaging, notes, status, stock_moved, initiated_by,
                      supersedes_transfer_id, initiate_form_version_id, labels_snapshot
                    ) values (
                      :no, :gs, :from_id, :to_id, :mode, :purpose, :pkg, :notes,
                      'INITIATED', false, :by, :supersedes, :form_version, :labels
                    ) returning id
                    """
                ).bindparams(bindparam("labels", type_=JSONB)),
                {
                    "no": transfer_no,
                    "gs": gs_id,
                    "from_id": from_location_id,
                    "to_id": to_location_id,
                    "mode": mode_code,
                    "purpose": purpose_code,
                    "pkg": with_packaging,
                    "notes": notes,
                    "by": by,
                    "supersedes": supersedes_transfer_id,
                    "form_version": initiate_form_version_id,
                    "labels": labels_snapshot or {},
                },
            ).scalar_one()
        )
    )


def insert_line(session: Session, *, transfer_id: UUID, lot_id: UUID, qty_sent: int) -> None:
    session.execute(
        text(
            "insert into public.custody_transfer_lines (transfer_id, lot_id, qty_sent) "
            "values (:t, :l, :q)"
        ),
        {"t": transfer_id, "l": lot_id, "q": qty_sent},
    )


def get_transfer(
    session: Session, transfer_id: UUID, *, for_update: bool = False
) -> dict[str, Any] | None:
    lock = " for update of t" if for_update else ""
    row = (
        session.execute(
            text(f"select {_TRANSFER_COLUMNS} {_TRANSFER_FROM} where t.id = :id{lock}"),
            {"id": transfer_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def transfer_slip_no(session: Session, transfer_id: UUID) -> str | None:
    """DEC-66: the Transfer Slip a custody transfer backs (None for any other transfer)."""
    value = session.execute(
        text("select slip_no from public.transfer_slips where custody_transfer_id = :id"),
        {"id": transfer_id},
    ).scalar()
    return str(value) if value is not None else None


def transfers_for_gs(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            f"select {_TRANSFER_COLUMNS} {_TRANSFER_FROM} where t.gs_id = :gs order by t.created_at"
        ),
        {"gs": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def lines_for_transfers(session: Session, transfer_ids: list[UUID]) -> list[dict[str, Any]]:
    if not transfer_ids:
        return []
    rows = session.execute(
        text(
            """
            select cl.transfer_id, cl.lot_id, cl.qty_sent, cl.qty_counted, cl.qty_accepted,
                   cl.qty_returned, cl.qty_adjusted, lot.gs_item_id, lot.condition_class,
                   lot.source_condition_code, lot.routing_hint, lot.is_pending,
                   gi.line_no, gi.product_name_snapshot as product_name,
                   gi.product_code_snapshot as product_code
              from public.custody_transfer_lines cl
              join public.stock_lots lot on lot.id = cl.lot_id
              left join public.gs_items gi on gi.id = lot.gs_item_id
             where cl.transfer_id = any(:ids)
             order by gi.line_no nulls last, lot.created_at, lot.id
            """
        ),
        {"ids": transfer_ids},
    ).mappings()
    return [dict(r) for r in rows]


def set_status(session: Session, transfer_id: UUID, status: str, notes: str | None) -> None:
    session.execute(
        text(
            """
            update public.custody_transfers
               set status = :s, notes = coalesce(:n, notes), updated_at = now()
             where id = :id
            """
        ),
        {"id": transfer_id, "s": status, "n": notes},
    )


# =============================================================================================
# P3-01 · two-phase custody engine
# =============================================================================================
def mark_dispatched(session: Session, transfer_id: UUID, transit_location_id: UUID) -> None:
    session.execute(
        text(
            """
            update public.custody_transfers
               set transit_location_id = :transit, stock_moved = true, stock_moved_at = now(),
                   updated_at = now()
             where id = :id
            """
        ),
        {"id": transfer_id, "transit": transit_location_id},
    )


def set_receiver_task(session: Session, transfer_id: UUID, task_id: UUID | None) -> None:
    session.execute(
        text("update public.custody_transfers set receiver_task_id = :task where id = :id"),
        {"id": transfer_id, "task": task_id},
    )


def set_line_count(session: Session, transfer_id: UUID, lot_id: UUID, qty_counted: int) -> None:
    session.execute(
        text(
            "update public.custody_transfer_lines set qty_counted = :q "
            "where transfer_id = :t and lot_id = :l"
        ),
        {"t": transfer_id, "l": lot_id, "q": qty_counted},
    )


def add_line_outcome(
    session: Session,
    transfer_id: UUID,
    lot_id: UUID,
    *,
    accepted: int = 0,
    returned: int = 0,
    adjusted: int = 0,
) -> None:
    session.execute(
        text(
            """
            update public.custody_transfer_lines
               set qty_accepted = qty_accepted + :a, qty_returned = qty_returned + :r,
                   qty_adjusted = qty_adjusted + :j
             where transfer_id = :t and lot_id = :l
            """
        ),
        {"t": transfer_id, "l": lot_id, "a": accepted, "r": returned, "j": adjusted},
    )


def set_received(
    session: Session,
    transfer_id: UUID,
    *,
    status: str,
    acceptance_code: str,
    by: UUID,
    discrepancy_notes: str | None,
    accept_form_version_id: UUID | None,
    labels: dict[str, Any],
) -> None:
    session.execute(
        text(
            """
            update public.custody_transfers
               set status = :s, acceptance_code = :code, accepted_by = :by, accepted_at = now(),
                   discrepancy_notes = :notes, accept_form_version_id = :fv,
                   labels_snapshot = labels_snapshot || :labels, updated_at = now()
             where id = :id
            """
        ).bindparams(bindparam("labels", type_=JSONB)),
        {
            "id": transfer_id,
            "s": status,
            "code": acceptance_code,
            "by": by,
            "notes": discrepancy_notes,
            "fv": accept_form_version_id,
            "labels": labels,
        },
    )


def set_cancelled(session: Session, transfer_id: UUID, *, by: UUID, reason: str) -> None:
    session.execute(
        text(
            """
            update public.custody_transfers
               set status = 'CANCELLED', cancelled_by = :by, cancelled_at = now(),
                   cancel_reason = :reason, updated_at = now()
             where id = :id
            """
        ),
        {"id": transfer_id, "by": by, "reason": reason},
    )


def set_reconciled(session: Session, transfer_id: UUID, resolution_code: str) -> None:
    session.execute(
        text(
            """
            update public.custody_transfers
               set status = 'RECONCILED', resolution_code = :code, reconciled_at = now(),
                   updated_at = now()
             where id = :id
            """
        ),
        {"id": transfer_id, "code": resolution_code},
    )


def location_by_id(session: Session, location_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select l.id, l.code, l.name, l.location_class, l.custodian_role_id,
                       r.code as custodian_role_code, l.custodian_user_id, l.is_active
                  from public.inventory_locations l
                  left join public.roles r on r.id = l.custodian_role_id
                 where l.id = :id
                """
            ),
            {"id": location_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def location_by_class(session: Session, location_class: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select id, code, name, location_class, is_active
                  from public.inventory_locations
                 where location_class = :c and is_active
                 order by code limit 1
                """
            ),
            {"c": location_class},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def user_has_role_id(session: Session, user_id: UUID, role_id: UUID | None) -> bool:
    if role_id is None:
        return False
    return bool(
        session.execute(
            text(
                "select exists (select 1 from public.user_roles "
                "where user_id = :u and role_id = :r)"
            ),
            {"u": user_id, "r": role_id},
        ).scalar()
    )


def custodian_user_ids(session: Session, location_id: UUID) -> list[UUID]:
    """Active users who hold custody of a location (its custodian user or role)."""
    rows = session.execute(
        text(
            """
            select distinct p.id
              from public.inventory_locations l
              join public.profiles p on p.is_active
             where l.id = :loc
               and (p.id = l.custodian_user_id
                    or exists (select 1 from public.user_roles ur
                                where ur.user_id = p.id and ur.role_id = l.custodian_role_id))
            """
        ),
        {"loc": location_id},
    ).scalars()
    return [UUID(str(r)) for r in rows]


def lot_detail(
    session: Session, lot_id: UUID, *, for_update: bool = False
) -> dict[str, Any] | None:
    lock = " for update of lot" if for_update else ""
    row = (
        session.execute(
            text(
                f"""
                select lot.id, lot.stock_item_id, lot.gs_id, lot.gs_item_id, lot.condition_class,
                       lot.source_condition_code, lot.routing_hint, lot.requires_evaluation,
                       lot.is_pending
                  from public.stock_lots lot where lot.id = :id{lock}
                """  # noqa: S608 - fixed SQL fragment, all values are bound parameters
            ),
            {"id": lot_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def gs_lot_positions(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    """Every positive balance of the GS's lots with its location and line (handover builder)."""
    rows = session.execute(
        text(
            """
            select lot.id as lot_id, lot.gs_item_id, lot.condition_class, lot.source_condition_code,
                   lot.routing_hint, lot.is_pending, gi.line_no,
                   gi.product_name_snapshot as product_name,
                   gi.product_code_snapshot as product_code,
                   l.id as location_id, l.code as location_code, l.name as location_name,
                   l.location_class, b.qty
              from public.stock_balances b
              join public.stock_lots lot on lot.id = b.lot_id
              join public.inventory_locations l on l.id = b.location_id
              left join public.gs_items gi on gi.id = lot.gs_item_id
             where lot.gs_id = :gs and b.qty > 0
             order by gi.line_no nulls last, lot.created_at, lot.id, l.code
            """
        ),
        {"gs": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def rm_action_qty(session: Session, gs_id: UUID, action_code: str) -> dict[UUID, int]:
    rows = session.execute(
        text(
            """
            select a.gs_item_id, sum(a.qty)::int as qty
              from public.rm_item_actions a
              join public.gs_items gi on gi.id = a.gs_item_id
             where gi.gs_id = :gs and a.is_current and a.action_code = :code
             group by a.gs_item_id
            """
        ),
        {"gs": gs_id, "code": action_code},
    ).mappings()
    return {UUID(str(r["gs_item_id"])): int(r["qty"]) for r in rows}


def open_pendencies(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select id, gs_item_id, lot_id, qty, reason, sent_to, blocks_gs
              from public.pendencies where gs_id = :gs and status = 'OPEN'
             order by opened_at
            """
        ),
        {"gs": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def option_labels(session: Session, set_code: str) -> dict[str, str]:
    rows = session.execute(
        text(
            """
            select oi.code, oi.label from public.option_items oi
              join public.option_sets os on os.id = oi.option_set_id
             where os.code = :set
            """
        ),
        {"set": set_code},
    ).mappings()
    return {r["code"]: r["label"] for r in rows}


def item_field_labels(session: Session, field_group: str) -> dict[str, str]:
    """Code -> current label of an item field library group (AMD-10/16; e.g. ACTION)."""
    rows = session.execute(
        text("select code, label from public.item_field_library where field_group = :g"),
        {"g": field_group},
    ).mappings()
    return {r["code"]: r["label"] for r in rows}


def condition_labels(session: Session, codes: list[str]) -> dict[str, str]:
    if not codes:
        return {}
    rows = session.execute(
        text("select code, label from public.option_items where code = any(:codes)"),
        {"codes": codes},
    ).mappings()
    return {r["code"]: r["label"] for r in rows}


def get_published_form(session: Session, code: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select fv.id, fv.version_no, fv.snapshot
                  from public.form_versions fv
                  join public.form_definitions fd on fd.id = fv.form_definition_id
                 where fd.code = :code and fv.status = 'PUBLISHED'
                 order by fv.version_no desc limit 1
                """
            ),
            {"code": code},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_published_template(session: Session, code: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select id, code, name, version_no, coalesce(snapshot, layout) as layout
                  from public.print_templates where code = :code and status = 'PUBLISHED'
                """
            ),
            {"code": code},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def insert_print_log(
    session: Session,
    *,
    template_code: str,
    entity_id: UUID,
    actor_id: UUID,
    metadata: dict[str, Any],
) -> int:
    session.execute(
        text(
            """
            insert into public.print_logs
                   (template_code, entity_type, entity_id, printed_by, metadata)
            values (:code, 'custody_transfers', :id, :by, :meta)
            """
        ).bindparams(bindparam("meta", type_=JSONB)),
        {"code": template_code, "id": entity_id, "by": actor_id, "meta": metadata},
    )
    return print_count(session, template_code, entity_id)


def print_count(session: Session, template_code: str, entity_id: UUID) -> int:
    return int(
        session.execute(
            text(
                "select count(*) from public.print_logs where template_code = :code "
                "and entity_type = 'custody_transfers' and entity_id = :id"
            ),
            {"code": template_code, "id": entity_id},
        ).scalar_one()
    )


def list_transfers(
    session: Session,
    *,
    status: str | None,
    from_location_code: str | None,
    to_location_code: str | None,
    gs_id: UUID | None,
    to_accept_by: UUID | None,
    all_locations: bool,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """Transfers, newest first. `to_accept_by`: dispatched transfers waiting for that user's count
    (custodian of the destination; every destination when `all_locations`)."""
    where = """
     where (cast(:status as text) is null or t.status = cast(:status as text))
       and (cast(:from_code as text) is null or fl.code = cast(:from_code as text))
       and (cast(:to_code as text) is null or tl.code = cast(:to_code as text))
       and (cast(:gs as uuid) is null or t.gs_id = cast(:gs as uuid))
       and (cast(:me as uuid) is null or (
             t.status = 'INITIATED' and t.stock_moved
             and (:all_locations or tl.custodian_user_id = cast(:me as uuid)
                  or exists (select 1 from public.user_roles ur
                              where ur.user_id = cast(:me as uuid)
                                and ur.role_id = tl.custodian_role_id))))
    """
    params = {
        "status": status,
        "from_code": from_location_code,
        "to_code": to_location_code,
        "gs": gs_id,
        "me": to_accept_by,
        "all_locations": all_locations,
        "limit": limit,
        "offset": offset,
    }
    total = int(
        session.execute(text(f"select count(*) {_TRANSFER_FROM} {where}"), params).scalar_one()
    )
    rows = session.execute(
        text(
            f"""
            select {_TRANSFER_COLUMNS},
                   (select count(*) from public.custody_transfer_lines cl
                     where cl.transfer_id = t.id)::int as line_count,
                   (select coalesce(sum(cl.qty_sent), 0) from public.custody_transfer_lines cl
                     where cl.transfer_id = t.id)::int as total_qty
            {_TRANSFER_FROM} {where}
            order by t.created_at desc, t.transfer_no desc
            limit :limit offset :offset
            """  # noqa: S608 - fixed SQL fragments, all values are bound parameters
        ),
        params,
    ).mappings()
    return [dict(r) for r in rows], total


def gs_has_discrepancy(session: Session, gs_id: UUID) -> bool:
    return bool(
        session.execute(
            text(
                "select exists (select 1 from public.custody_transfers "
                "where gs_id = :gs and status = 'DISCREPANCY')"
            ),
            {"gs": gs_id},
        ).scalar()
    )


# --- reconciliations ---------------------------------------------------------------------------
_RECON_COLUMNS = """
  r.id, r.transfer_id, r.resolution_code, r.difference_disposition, r.resend_lines, r.notes,
  r.status, r.requires_rm_approval, r.proposed_by, pb.full_name as proposed_by_name, r.proposed_at,
  r.initiator_signed_by, isb.full_name as initiator_signed_by_name, r.initiator_signed_at,
  r.receiver_signed_by, rsb.full_name as receiver_signed_by_name, r.receiver_signed_at,
  r.is_rm_override, r.rm_approved_by, rab.full_name as rm_approved_by_name, r.rm_approved_at,
  r.rm_reason, r.applied_at, r.resend_transfer_id
"""
_RECON_FROM = """
  from public.custody_reconciliations r
  left join public.profiles pb on pb.id = r.proposed_by
  left join public.profiles isb on isb.id = r.initiator_signed_by
  left join public.profiles rsb on rsb.id = r.receiver_signed_by
  left join public.profiles rab on rab.id = r.rm_approved_by
"""


def reconciliations_for(session: Session, transfer_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            f"select {_RECON_COLUMNS} {_RECON_FROM} where r.transfer_id = :t order by r.proposed_at"
        ),
        {"t": transfer_id},
    ).mappings()
    return [dict(r) for r in rows]


def open_reconciliation(session: Session, transfer_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                f"""
                select {_RECON_COLUMNS} {_RECON_FROM}
                 where r.transfer_id = :t and r.status in ('PROPOSED','AWAITING_RM_APPROVAL')
                   for update of r
                """
            ),
            {"t": transfer_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def insert_reconciliation(
    session: Session,
    *,
    transfer_id: UUID,
    resolution_code: str,
    difference_disposition: str | None,
    resend_lines: list[dict[str, Any]],
    notes: str,
    requires_rm_approval: bool,
    by: UUID,
) -> UUID:
    return UUID(
        str(
            session.execute(
                text(
                    """
                    insert into public.custody_reconciliations (
                      transfer_id, resolution_code, difference_disposition, resend_lines, notes,
                      requires_rm_approval, proposed_by
                    ) values (:t, :code, :disp, :lines, :notes, :rm, :by) returning id
                    """
                ).bindparams(bindparam("lines", type_=JSONB)),
                {
                    "t": transfer_id,
                    "code": resolution_code,
                    "disp": difference_disposition,
                    "lines": resend_lines,
                    "notes": notes,
                    "rm": requires_rm_approval,
                    "by": by,
                },
            ).scalar_one()
        )
    )


def sign_reconciliation(session: Session, recon_id: UUID, *, side: str, by: UUID) -> None:
    column = "initiator" if side == "INITIATOR" else "receiver"
    session.execute(
        text(
            f"""
            update public.custody_reconciliations
               set {column}_signed_by = :by, {column}_signed_at = now(), updated_at = now()
             where id = :id
            """  # noqa: S608 - column is one of two fixed names
        ),
        {"id": recon_id, "by": by},
    )


def rm_approve_reconciliation(
    session: Session, recon_id: UUID, *, by: UUID, reason: str, override: bool
) -> None:
    session.execute(
        text(
            """
            update public.custody_reconciliations
               set rm_approved_by = :by, rm_approved_at = now(), rm_reason = :reason,
                   is_rm_override = is_rm_override or :override, updated_at = now()
             where id = :id
            """
        ),
        {"id": recon_id, "by": by, "reason": reason, "override": override},
    )


def set_reconciliation_status(
    session: Session, recon_id: UUID, status: str, *, resend_transfer_id: UUID | None = None
) -> None:
    session.execute(
        text(
            """
            update public.custody_reconciliations
               set status = :s,
                   applied_at = case when :s = 'APPLIED' then now() else applied_at end,
                   resend_transfer_id = coalesce(:resend, resend_transfer_id), updated_at = now()
             where id = :id
            """
        ),
        {"id": recon_id, "s": status, "resend": resend_transfer_id},
    )


# --- Intermediate Store stock view & direct classification (DEC-14, DEC-27) -------------------
def location_stock(
    session: Session,
    location_id: UUID,
    *,
    gs_id: UUID | None,
    product_q: str | None,
    condition_class: str | None,
    routing_hint: str | None,
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select b.lot_id, b.qty, lot.gs_id, g.gs_no, lot.gs_item_id, gi.line_no,
                   gi.product_code_snapshot as product_code,
                   gi.product_name_snapshot as product_name,
                   lot.condition_class, lot.source_condition_code, lot.routing_hint,
                   lot.requires_evaluation,
                   (select jsonb_build_object('result_code', pr.result_code, 'qty', pr.qty,
                                              'at', pr."at")
                      from public.packaging_replacements pr
                     where pr.lot_id = lot.id order by pr."at" desc limit 1) as last_packaging_check
              from public.stock_balances b
              join public.stock_lots lot on lot.id = b.lot_id
              join public.goods_slips g on g.id = lot.gs_id
              left join public.gs_items gi on gi.id = lot.gs_item_id
             where b.location_id = :loc and b.qty > 0
               and (cast(:gs as uuid) is null or lot.gs_id = cast(:gs as uuid))
               and (cast(:cond as text) is null or lot.condition_class = cast(:cond as text))
               and (cast(:hint as text) is null or lot.routing_hint = cast(:hint as text))
               and (cast(:q as text) is null
                    or gi.product_name_snapshot ilike '%' || cast(:q as text) || '%'
                    or gi.product_code_snapshot ilike '%' || cast(:q as text) || '%'
                    or g.gs_no ilike '%' || cast(:q as text) || '%')
             order by g.gs_no, gi.line_no nulls last, lot.created_at
            """
        ),
        {
            "loc": location_id,
            "gs": gs_id,
            "cond": condition_class,
            "hint": routing_hint,
            "q": product_q,
        },
    ).mappings()
    return [dict(r) for r in rows]


def find_classified_lot(
    session: Session, *, source: dict[str, Any], condition_class: str
) -> UUID | None:
    value = session.execute(
        text(
            """
            select id from public.stock_lots
             where gs_id = :gs and gs_item_id is not distinct from :item
               and stock_item_id = :si and condition_class = :cond and not is_pending
               and source_condition_code is not distinct from :src
             order by created_at limit 1
            """
        ),
        {
            "gs": source["gs_id"],
            "item": source["gs_item_id"],
            "si": source["stock_item_id"],
            "cond": condition_class,
            "src": source["source_condition_code"],
        },
    ).scalar()
    return UUID(str(value)) if value else None


def take_over_proposal(
    session: Session,
    transfer_id: UUID,
    *,
    by: UUID,
    mode_code: str,
    form_version_id: UUID,
    labels: dict[str, Any],
    notes: str | None,
) -> None:
    """The P2-04 proposal becomes an engine transfer: the sender is its initiator from now on."""
    session.execute(
        text(
            """
            update public.custody_transfers
               set initiated_by = :by, initiated_at = now(), mode_code = :mode,
                   initiate_form_version_id = :fv, labels_snapshot = labels_snapshot || :labels,
                   notes = coalesce(:notes, notes), updated_at = now()
             where id = :id
            """
        ).bindparams(bindparam("labels", type_=JSONB)),
        {
            "id": transfer_id,
            "by": by,
            "mode": mode_code,
            "fv": form_version_id,
            "labels": labels,
            "notes": notes,
        },
    )


def gs_ids_for_transfer(session: Session, transfer_id: UUID) -> list[UUID]:
    """Every GS whose stock is on the transfer (P3-07 closure status automation)."""
    rows = session.execute(
        text(
            """
            select distinct lot.gs_id
              from public.custody_transfer_lines cl
              join public.stock_lots lot on lot.id = cl.lot_id
             where cl.transfer_id = :id and lot.gs_id is not null
             order by lot.gs_id
            """
        ),
        {"id": transfer_id},
    ).scalars()
    return [UUID(str(r)) for r in rows]
