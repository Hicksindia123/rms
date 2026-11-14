"""Repository for RM item-wise actions, print templates, and replacement slips.

Master plan references: WF r6, BR-19, BR-20, G-08, DEC-12, DEC-13, DEC-33.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def get_goods_slip(session: Session, gs_id: UUID) -> dict[str, Any] | None:
    stmt = text(
        """
        select gs.id, gs.gs_no, gs.status, gs.category_code, gs.party_id,
               gs.has_open_pendency, gs.has_discrepancy, gs.has_hazard,
               gs.created_at, gs.created_by,
               p.name as party_name, p.code as party_code,
               st.name as station_name, s.name as state_name
          from public.goods_slips gs
          left join public.parties p on p.id = gs.party_id
          left join public.stations st on st.id = gs.station_id
          left join public.states s on s.id = gs.state_id
         where gs.id = :gs_id
        """
    )
    res = session.execute(stmt, {"gs_id": gs_id}).mappings().first()
    return dict(res) if res else None


def is_on_final_action_flow(session: Session, gs_id: UUID) -> bool:
    """Change plan Phase 7: the DB definition of a GS on the AMD-13 final-action flow."""
    return bool(
        session.execute(
            text("select rms_private.gs_on_final_action_flow(:gs_id)"), {"gs_id": gs_id}
        ).scalar()
    )


def get_gs_items(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    stmt = text(
        """
        select gi.id, gi.gs_id, gi.line_no, gi.product_id, gi.received_qty,
               p.code as product_code, p.name as product_name
          from public.gs_items gi
          join public.products p on p.id = gi.product_id
         where gi.gs_id = :gs_id
         order by gi.line_no asc
        """
    )
    return [dict(r) for r in session.execute(stmt, {"gs_id": gs_id}).mappings().all()]


def get_inspection_allocations_for_gs(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    stmt = text(
        """
        select insp.gs_item_id, ia.condition_code, ia.qty,
               oi.label as condition_label, oi.allowed_status, oi.system_behavior
          from public.inspection_allocations ia
          join public.inspections insp on insp.id = ia.inspection_id
          join public.gs_items gi on gi.id = insp.gs_item_id
          left join public.option_items oi on oi.code = ia.condition_code
         where gi.gs_id = :gs_id
         order by ia.condition_code asc
        """
    )
    return [dict(r) for r in session.execute(stmt, {"gs_id": gs_id}).mappings().all()]


def get_rejections_for_gs(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    stmt = text(
        """
        select r.id, r.gs_item_id, r.condition_code, r.qty, r.disposition, r.hazard,
               oi.label as condition_label, oi.rule_text as reason
          from public.rejections r
          join public.gs_items gi on gi.id = r.gs_item_id
          left join public.option_items oi on oi.code = r.condition_code
         where gi.gs_id = :gs_id
         order by r.created_at asc
        """
    )
    return [dict(r) for r in session.execute(stmt, {"gs_id": gs_id}).mappings().all()]


def get_rm_action_options(session: Session) -> list[dict[str, Any]]:
    stmt = text(
        """
        -- AMD-16: the ACTION group of the item field library is the action catalogue (codes
        -- immutable, labels admin-editable). Rule texts still come from the workbook option row.
        select l.code, l.label, coalesce(oi.allowed_status, 'YES') as allowed_status,
               oi.rule_text, oi.next_action_text, l.sort_order
          from public.item_field_library l
          left join public.option_items oi on oi.id = l.source_option_item_id
         where l.field_group = 'ACTION'
           and l.is_active = true
         order by l.sort_order asc, l.code asc
        """
    )
    return [dict(r) for r in session.execute(stmt).mappings().all()]


def get_current_rm_actions_for_gs(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    stmt = text(
        """
        select ra.id, ra.gs_item_id, ra.revision_no, ra.action_code, ra.qty,
               ra.is_current, ra.reason, ra.decided_by, ra.decided_at,
               ra.action_label  -- G-18 label snapshot
          from public.rm_item_actions ra
          join public.gs_items gi on gi.id = ra.gs_item_id
         where gi.gs_id = :gs_id
           and ra.is_current = true
         order by ra.action_code asc
        """
    )
    return [dict(r) for r in session.execute(stmt, {"gs_id": gs_id}).mappings().all()]


def get_max_revision_no(session: Session, gs_id: UUID) -> int:
    stmt = text(
        """
        select coalesce(max(ra.revision_no), 0) as max_rev
          from public.rm_item_actions ra
          join public.gs_items gi on gi.id = ra.gs_item_id
         where gi.gs_id = :gs_id
        """
    )
    row = session.execute(stmt, {"gs_id": gs_id}).mappings().first()
    return int(row["max_rev"]) if row else 0


def get_all_rm_action_revisions_for_gs(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    stmt = text(
        """
        select ra.id, ra.gs_item_id, ra.revision_no, ra.action_code, ra.qty,
               ra.is_current, ra.reason, ra.decided_by, ra.decided_at,
               p.full_name as decided_by_name,
               ra.action_label, gi.line_no  -- G-18 label snapshot
          from public.rm_item_actions ra
          join public.gs_items gi on gi.id = ra.gs_item_id
          left join public.profiles p on p.id = ra.decided_by
         where gi.gs_id = :gs_id
         order by ra.revision_no asc, gi.line_no asc
        """
    )
    rows = [dict(r) for r in session.execute(stmt, {"gs_id": gs_id}).mappings().all()]
    # Group by revision_no
    revisions: dict[int, dict[str, Any]] = {}
    for r in rows:
        rev_no = r["revision_no"]
        if rev_no not in revisions:
            revisions[rev_no] = {
                "revision_no": rev_no,
                "decided_by": r["decided_by"],
                "decided_by_name": r["decided_by_name"] or "RM",
                "decided_at": r["decided_at"],
                "reason": r["reason"],
                "lines": [],
            }
        revisions[rev_no]["lines"].append(
            {
                "gs_item_id": r["gs_item_id"],
                "line_no": r["line_no"],
                "action_code": r["action_code"],
                "action_label": r["action_label"] or r["action_code"],
                "qty": r["qty"],
            }
        )
    return list(revisions.values())


def retire_current_rm_actions(session: Session, gs_id: UUID) -> None:
    stmt = text(
        """
        update public.rm_item_actions
           set is_current = false
         where gs_item_id in (select id from public.gs_items where gs_id = :gs_id)
           and is_current = true
        """
    )
    session.execute(stmt, {"gs_id": gs_id})


def insert_rm_item_action(
    session: Session,
    gs_item_id: UUID,
    revision_no: int,
    action_code: str,
    qty: int,
    is_current: bool,
    reason: str | None,
    decided_by: UUID,
) -> None:
    stmt = text(
        """
        insert into public.rm_item_actions (
          gs_item_id, revision_no, action_code, qty, is_current, reason, decided_by
        ) values (
          :gs_item_id, :revision_no, :action_code, :qty, :is_current, :reason, :decided_by
        )
        """
    )
    session.execute(
        stmt,
        {
            "gs_item_id": gs_item_id,
            "revision_no": revision_no,
            "action_code": action_code,
            "qty": qty,
            "is_current": is_current,
            "reason": reason,
            "decided_by": decided_by,
        },
    )


def create_pendency(
    session: Session,
    gs_id: UUID,
    gs_item_id: UUID,
    qty: int,
    reason: str,
    sent_to: str,
    blocks_gs: bool,
    lot_id: UUID | None,
    stock_movement_id: UUID | None,
    opened_by: UUID,
) -> UUID:
    stmt = text(
        """
        insert into public.pendencies (
          gs_id, gs_item_id, qty, reason, sent_to, blocks_gs, status,
          lot_id, stock_movement_id, opened_by
        ) values (
          :gs_id, :gs_item_id, :qty, :reason, :sent_to, :blocks_gs, 'OPEN',
          :lot_id, :stock_movement_id, :opened_by
        ) returning id
        """
    )
    row = (
        session.execute(
            stmt,
            {
                "gs_id": gs_id,
                "gs_item_id": gs_item_id,
                "qty": qty,
                "reason": reason,
                "sent_to": sent_to,
                "blocks_gs": blocks_gs,
                "lot_id": lot_id,
                "stock_movement_id": stock_movement_id,
                "opened_by": opened_by,
            },
        )
        .mappings()
        .first()
    )
    if not row:
        raise RuntimeError("Failed to create pendency record")
    return UUID(str(row["id"]))


def get_open_pendencies_for_item(session: Session, gs_item_id: UUID) -> list[dict[str, Any]]:
    stmt = text(
        """
        select id, gs_id, gs_item_id, qty, reason, sent_to, blocks_gs, status,
               lot_id, stock_movement_id, opened_by, opened_at
          from public.pendencies
         where gs_item_id = :gs_item_id
           and status = 'OPEN'
        """
    )
    return [dict(r) for r in session.execute(stmt, {"gs_item_id": gs_item_id}).mappings().all()]


def count_open_pendencies_for_gs(session: Session, gs_id: UUID) -> int:
    stmt = text(
        """
        select count(*)::integer as open_count
          from public.pendencies
         where gs_id = :gs_id
           and status = 'OPEN'
        """
    )
    row = session.execute(stmt, {"gs_id": gs_id}).mappings().first()
    return int(row["open_count"]) if row else 0


def update_gs_pendency_flag(session: Session, gs_id: UUID, has_open_pendency: bool) -> None:
    stmt = text(
        """
        update public.goods_slips
           set has_open_pendency = :has_open_pendency
         where id = :gs_id
        """
    )
    session.execute(stmt, {"gs_id": gs_id, "has_open_pendency": has_open_pendency})


def get_system_setting_value(session: Session, key: str, default: Any = None) -> Any:
    stmt = text("select value from public.system_settings where key = :key")
    row = session.execute(stmt, {"key": key}).mappings().first()
    if not row or row["value"] is None:
        return default
    val = row["value"]
    if isinstance(val, (int, float, bool, dict, list)):
        return val
    if isinstance(val, str):
        if val.lower() == "true":
            return True
        if val.lower() == "false":
            return False
    return val


def get_published_print_template(session: Session, code: str) -> dict[str, Any] | None:
    stmt = text(
        """
        select id, code, name, version_no, coalesce(snapshot, layout) as layout
          from public.print_templates
         where code = :code
           and status = 'PUBLISHED'
        """
    )
    res = session.execute(stmt, {"code": code}).mappings().first()
    return dict(res) if res else None


def get_print_logs_count(session: Session, template_code: str, entity_id: UUID) -> int:
    stmt = text(
        """
        select count(*)::integer as print_cnt
          from public.print_logs
         where template_code = :template_code
           and entity_id = :entity_id
        """
    )
    row = (
        session.execute(stmt, {"template_code": template_code, "entity_id": entity_id})
        .mappings()
        .first()
    )
    return int(row["print_cnt"]) if row else 0


def insert_print_log(
    session: Session,
    template_code: str,
    entity_id: UUID,
    revision_no: int,
    actor_id: UUID,
    metadata: dict[str, Any] | None = None,
) -> None:
    meta = metadata or {}
    stmt = text(
        """
        insert into public.print_logs (
          template_code, entity_type, entity_id, revision_no, printed_by, metadata
        ) values (
          :template_code, 'goods_slips', :entity_id, :revision_no, :actor_id, :metadata
        )
        """
    )
    import json

    session.execute(
        stmt,
        {
            "template_code": template_code,
            "entity_id": entity_id,
            "revision_no": revision_no,
            "actor_id": actor_id,
            "metadata": json.dumps(meta),
        },
    )

    # Also log into audit_log
    audit_stmt = text(
        """
        insert into public.audit_log (
          table_name, row_id, action, new, actor_id
        ) values (
          'goods_slips', :entity_id, 'PRINT', :new_data, :actor_id
        )
        """
    )
    session.execute(
        audit_stmt,
        {
            "entity_id": str(entity_id),
            "new_data": json.dumps({"template": template_code, "revision_no": revision_no, **meta}),
            "actor_id": actor_id,
        },
    )


def get_profile_name(session: Session, user_id: UUID | None) -> str | None:
    if not user_id:
        return None
    stmt = text("select full_name from public.profiles where id = :user_id")
    row = session.execute(stmt, {"user_id": user_id}).mappings().first()
    return str(row["full_name"]) if row and row["full_name"] else None


def set_goods_slip_status(
    session: Session, gs_id: UUID, new_status: str, actor_id: UUID, reason: str | None = None
) -> None:
    hist_stmt = text(
        """
        insert into public.gs_status_history (
          gs_id, from_status, to_status, step_code, "by", reason
        ) values (
          :gs_id,
          (select status from public.goods_slips where id = :gs_id),
          :to_status,
          'S1A_RM_ACTION',
          :actor_id,
          :reason
        )
        """
    )
    session.execute(
        hist_stmt,
        {
            "gs_id": gs_id,
            "to_status": new_status,
            "actor_id": actor_id,
            "reason": reason,
        },
    )

    update_stmt = text(
        """
        update public.goods_slips
           set status = :new_status,
               updated_at = now()
         where id = :gs_id
        """
    )
    session.execute(update_stmt, {"gs_id": gs_id, "new_status": new_status})


def complete_workflow_task(session: Session, gs_id: UUID, step_code: str) -> None:
    stmt = text(
        """
        update public.workflow_tasks
           set status = 'DONE'
         where gs_id = :gs_id
           and step_code = :step_code
           and status = 'OPEN'
        """
    )
    session.execute(stmt, {"gs_id": gs_id, "step_code": step_code})


def create_workflow_task(session: Session, gs_id: UUID, step_code: str, role_code: str) -> None:
    stmt = text(
        """
        insert into public.workflow_tasks (
          gs_id, step_code, assigned_role_id, status
        )
        select :gs_id, :step_code, r.id, 'OPEN'
          from public.roles r
         where r.code = :role_code
        """
    )
    session.execute(stmt, {"gs_id": gs_id, "step_code": step_code, "role_code": role_code})


def get_resolution_board_data(session: Session, gs_id: UUID) -> dict[str, Any]:
    """Fetch raw outcomes, dispatches, and store issues for resolution board."""
    # 1. Tech receiving records
    tech_stmt = text(
        """
        select
            sl.gs_item_id,
            coalesce(sum(trr.functional_good_qty), 0) as tech_good,
            coalesce(sum(trr.functional_repaired_qty), 0) as tech_repaired,
            coalesce(sum(trr.non_good_qty), 0) as tech_non_good,
            coalesce(sum(trr.non_sellable_qty), 0) as tech_non_sellable
        from public.technician_receiving_records trr
        join public.technician_batch_lines tbl on tbl.id = trr.batch_line_id
        join public.stock_lots sl on sl.id = tbl.lot_id
        where sl.gs_id = :gs_id
        group by sl.gs_item_id
        """
    )
    tech_rows = session.execute(tech_stmt, {"gs_id": gs_id}).mappings().all()
    tech_by_item = {r["gs_item_id"]: dict(r) for r in tech_rows}

    # 2. Lot conditions (current balances or lots originating from this gs_item)
    lots_simple_stmt = text(
        """
        select
            sl.gs_item_id,
            sl.condition_class,
            coalesce(sum(sb.qty), 0) as balance_qty
        from public.stock_lots sl
        left join public.stock_balances sb on sb.lot_id = sl.id
        where sl.gs_id = :gs_id and sl.gs_item_id is not null
        group by sl.gs_item_id, sl.condition_class
        """
    )
    lot_rows = session.execute(lots_simple_stmt, {"gs_id": gs_id}).mappings().all()

    # 3. Rejections
    rej_stmt = text(
        """
        select
            r.gs_item_id,
            coalesce(sum(r.qty), 0) as rejected_qty
        from public.rejections r
        join public.gs_items gi on gi.id = r.gs_item_id
        where gi.gs_id = :gs_id
        group by r.gs_item_id
        """
    )
    rej_rows = session.execute(rej_stmt, {"gs_id": gs_id}).mappings().all()
    rej_by_item = {r["gs_item_id"]: int(r["rejected_qty"]) for r in rej_rows}

    # 4. Replacement Dispatches
    disp_stmt = text(
        """
        select
            rdl.gs_item_id,
            rd.dispatch_type,
            coalesce(sum(rdl.qty), 0) as qty
        from public.replacement_dispatch_lines rdl
        join public.replacement_dispatches rd on rd.id = rdl.dispatch_id
        where rd.gs_id = :gs_id
        group by rdl.gs_item_id, rd.dispatch_type
        """
    )
    disp_rows = session.execute(disp_stmt, {"gs_id": gs_id}).mappings().all()

    # 5. Store Issues
    issue_stmt = text(
        """
        select
            sl.gs_item_id,
            coalesce(sum(sil.qty), 0) as qty
        from public.store_issue_lines sil
        join public.stock_lots sl on sl.id = sil.lot_id
        join public.store_issues si on si.id = sil.issue_id
        where sl.gs_id = :gs_id and sl.gs_item_id is not null
        group by sl.gs_item_id
        """
    )
    issue_rows = session.execute(issue_stmt, {"gs_id": gs_id}).mappings().all()
    issue_by_item = {r["gs_item_id"]: int(r["qty"]) for r in issue_rows}

    return {
        "tech_by_item": tech_by_item,
        "lot_rows": [dict(r) for r in lot_rows],
        "rej_by_item": rej_by_item,
        "disp_rows": [dict(r) for r in disp_rows],
        "issue_by_item": issue_by_item,
    }
