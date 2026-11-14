"""P3-02 Servicing repository (pure SQL operations)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.inventory import ledger_service


def list_technicians(session: Session) -> list[dict[str, Any]]:
    stmt = text(
        """
        select id, display_name, is_active
        from public.technicians
        where is_active = true
        order by display_name asc
        """
    )
    return [dict(r) for r in session.execute(stmt).mappings().all()]


def get_technician(session: Session, technician_id: UUID) -> dict[str, Any] | None:
    stmt = text(
        """
        select id, display_name, is_active, profile_id
        from public.technicians
        where id = :id
        """
    )
    row = session.execute(stmt, {"id": technician_id}).mappings().one_or_none()
    return dict(row) if row else None


def get_intermediate_store_location(session: Session) -> dict[str, Any]:
    stmt = text(
        """
        select id, code, name, location_class
        from public.inventory_locations
        where code = 'INTERMEDIATE_STORE'
        """
    )
    row = session.execute(stmt).mappings().one()
    return dict(row)


def get_technician_bench_location(session: Session) -> dict[str, Any]:
    stmt = text(
        """
        select id, code, name, location_class
        from public.inventory_locations
        where code = 'TECHNICIAN_BENCH'
        """
    )
    row = session.execute(stmt).mappings().one()
    return dict(row)


def get_non_functional_store_location(session: Session) -> dict[str, Any]:
    stmt = text(
        """
        select id, code, name, location_class
        from public.inventory_locations
        where code = 'NON_FUNCTIONAL_STORE'
        """
    )
    row = session.execute(stmt).mappings().one()
    return dict(row)


def get_intermediate_lots(session: Session) -> list[dict[str, Any]]:
    """Return lots in INTERMEDIATE_STORE with balance > 0."""
    stmt = text(
        """
        select sl.id as lot_id,
               sl.stock_item_id,
               sl.gs_id,
               gs.gs_no,
               si.product_id,
               p.name as product_name,
               p.code as product_code,
               pc.code as category_code,
               pc.supports_battery,
               sl.condition_class,
               sl.source_condition_code,
               sl.routing_hint,
               sl.requires_evaluation,
               sb.qty as balance
        from public.stock_balances sb
        join public.inventory_locations loc on loc.id = sb.location_id
        join public.stock_lots sl on sl.id = sb.lot_id
        join public.goods_slips gs on gs.id = sl.gs_id
        join public.stock_items si on si.id = sl.stock_item_id
        join public.products p on p.id = si.product_id
        join public.product_categories pc on pc.id = p.category_id
        where loc.code = 'INTERMEDIATE_STORE' and sb.qty > 0
        order by gs.created_at desc, p.name asc
        """
    )
    return [dict(r) for r in session.execute(stmt).mappings().all()]


def insert_batch(
    session: Session,
    *,
    batch_no: str,
    technician_id: UUID,
    entry_by: UUID,
    transfer_id: UUID | None,
    notes: str | None,
) -> dict[str, Any]:
    stmt = text(
        """
        insert into public.technician_batches (
          batch_no, technician_id, entry_by, status, transfer_id, notes, created_by
        ) values (
          :batch_no, :technician_id, :entry_by, 'ALLOTTED', :transfer_id, :notes, :created_by
        )
        returning id, batch_no, technician_id, entry_by,
                    status, transfer_id, allotted_at, completed_at, notes
        """
    )
    row = (
        session.execute(
            stmt,
            {
                "batch_no": batch_no,
                "technician_id": technician_id,
                "entry_by": entry_by,
                "transfer_id": transfer_id,
                "notes": notes,
                "created_by": entry_by,
            },
        )
        .mappings()
        .one()
    )
    return dict(row)


def insert_batch_line(
    session: Session,
    *,
    batch_id: UUID,
    lot_id: UUID,
    qty_allotted: int,
    requires_evaluation: bool = False,
) -> dict[str, Any]:
    stmt = text(
        """
        insert into public.technician_batch_lines (
          batch_id, lot_id, qty_allotted, qty_received, status, requires_evaluation
        ) values (
          :batch_id, :lot_id, :qty_allotted, 0, 'PENDING', :requires_evaluation
        )
        returning id, batch_id, lot_id, qty_allotted, qty_received,
                    status, requires_evaluation, evaluation_notes
        """
    )
    row = (
        session.execute(
            stmt,
            {
                "batch_id": batch_id,
                "lot_id": lot_id,
                "qty_allotted": qty_allotted,
                "requires_evaluation": requires_evaluation,
            },
        )
        .mappings()
        .one()
    )
    return dict(row)


def get_batch(session: Session, batch_id: UUID, for_update: bool = False) -> dict[str, Any] | None:
    base_sql = """
        select tb.id, tb.batch_no, tb.technician_id, t.display_name as technician_name,
               tb.entry_by, p.full_name as entry_by_name, tb.status, tb.transfer_id,
               tb.allotted_at, tb.completed_at, tb.notes
        from public.technician_batches tb
        join public.technicians t on t.id = tb.technician_id
        join public.profiles p on p.id = tb.entry_by
        where tb.id = :id
    """
    if for_update:
        base_sql += " for update of tb"  # lock only this row (P3-08: deadlock)
    row = session.execute(text(base_sql), {"id": batch_id}).mappings().one_or_none()
    return dict(row) if row else None


def get_batch_lines(session: Session, batch_id: UUID) -> list[dict[str, Any]]:
    stmt = text(
        """
        select tbl.id, tbl.batch_id, tbl.lot_id,
               p.name as product_name, p.code as product_code,
               pc.code as category_code, pc.supports_battery,
               sl.source_condition_code, sl.routing_hint,
               tbl.requires_evaluation, tbl.evaluation_notes,
               tbl.qty_allotted, tbl.qty_received, tbl.status
        from public.technician_batch_lines tbl
        join public.stock_lots sl on sl.id = tbl.lot_id
        join public.stock_items si on si.id = sl.stock_item_id
        join public.products p on p.id = si.product_id
        join public.product_categories pc on pc.id = p.category_id
        where tbl.batch_id = :batch_id
        order by tbl.created_at asc
        """
    )
    return [dict(r) for r in session.execute(stmt, {"batch_id": batch_id}).mappings().all()]


def get_batch_line(
    session: Session, line_id: UUID, for_update: bool = False
) -> dict[str, Any] | None:
    base_sql = """
        select tbl.id, tbl.batch_id, tbl.lot_id,
               tbl.qty_allotted, tbl.qty_received, tbl.status,
               tbl.requires_evaluation, tbl.evaluation_notes,
               sl.stock_item_id, sl.gs_id, sl.gs_item_id, sl.condition_class,
               sl.source_condition_code, sl.routing_hint,
               p.id as product_id, p.name as product_name, p.code as product_code,
               pc.code as category_code, pc.supports_battery
        from public.technician_batch_lines tbl
        join public.stock_lots sl on sl.id = tbl.lot_id
        join public.stock_items si on si.id = sl.stock_item_id
        join public.products p on p.id = si.product_id
        join public.product_categories pc on pc.id = p.category_id
        where tbl.id = :id
    """
    if for_update:
        base_sql += " for update of tbl"  # lock only this row (P3-08: deadlock)
    row = session.execute(text(base_sql), {"id": line_id}).mappings().one_or_none()
    return dict(row) if row else None


def update_batch_line(
    session: Session,
    line_id: UUID,
    *,
    qty_received: int,
    status: str,
    evaluation_notes: str | None = None,
) -> None:
    stmt = text(
        """
        update public.technician_batch_lines
        set qty_received = :qty_received,
            status = :status,
            evaluation_notes = coalesce(:eval_notes, evaluation_notes),
            updated_at = now()
        where id = :id
        """
    )
    session.execute(
        stmt,
        {
            "id": line_id,
            "qty_received": qty_received,
            "status": status,
            "eval_notes": evaluation_notes,
        },
    )


def update_batch_status(
    session: Session,
    batch_id: UUID,
    *,
    status: str,
    completed: bool = False,
) -> None:
    if completed:
        sql = """
            update public.technician_batches
            set status = :status, completed_at = now(), updated_at = now()
            where id = :id
        """
    else:
        sql = """
            update public.technician_batches
            set status = :status, updated_at = now()
            where id = :id
        """
    session.execute(text(sql), {"id": batch_id, "status": status})


def insert_receiving_record(
    session: Session,
    *,
    batch_id: UUID,
    batch_line_id: UUID,
    qty_received: int,
    battery_check_code: str | None,
    pieces_checked: int | None,
    batteries_installed: int | None,
    battery_type_id: UUID | None,
    cleaning_code: str | None,
    functional_good_qty: int,
    functional_repaired_qty: int,
    non_good_qty: int,
    non_sellable_qty: int,
    evaluation_notes: str | None,
    technician_remarks: str | None,
    entry_by: UUID,
    battery_stock_movement_id: UUID | None,
    functional_transfer_id: UUID | None,
    non_good_transfer_id: UUID | None,
    non_sellable_transfer_id: UUID | None,
    idempotency_key: str | None = None,
) -> UUID:
    stmt = text(
        """
        insert into public.technician_receiving_records (
          batch_id, batch_line_id, qty_received, battery_check_code, pieces_checked,
          batteries_installed, battery_type_id, cleaning_code, functional_good_qty,
          functional_repaired_qty, non_good_qty, non_sellable_qty, evaluation_notes,
          technician_remarks, entry_by, battery_stock_movement_id, functional_transfer_id,
          non_good_transfer_id, non_sellable_transfer_id, idempotency_key
        ) values (
          :batch_id, :batch_line_id, :qty_received, :battery_check_code, :pieces_checked,
          :batteries_installed, :battery_type_id, :cleaning_code, :functional_good_qty,
          :functional_repaired_qty, :non_good_qty, :non_sellable_qty, :evaluation_notes,
          :technician_remarks, :entry_by, :battery_stock_movement_id, :functional_transfer_id,
          :non_good_transfer_id, :non_sellable_transfer_id, :idempotency_key
        )
        returning id
        """
    )
    res = session.execute(
        stmt,
        {
            "batch_id": batch_id,
            "batch_line_id": batch_line_id,
            "qty_received": qty_received,
            "battery_check_code": battery_check_code,
            "pieces_checked": pieces_checked,
            "batteries_installed": batteries_installed,
            "battery_type_id": battery_type_id,
            "cleaning_code": cleaning_code,
            "functional_good_qty": functional_good_qty,
            "functional_repaired_qty": functional_repaired_qty,
            "non_good_qty": non_good_qty,
            "non_sellable_qty": non_sellable_qty,
            "evaluation_notes": evaluation_notes,
            "technician_remarks": technician_remarks,
            "entry_by": entry_by,
            "battery_stock_movement_id": battery_stock_movement_id,
            "functional_transfer_id": functional_transfer_id,
            "non_good_transfer_id": non_good_transfer_id,
            "non_sellable_transfer_id": non_sellable_transfer_id,
            "idempotency_key": idempotency_key,
        },
    ).scalar_one()
    return UUID(str(res))


def get_receiving_records(session: Session, batch_id: UUID) -> list[dict[str, Any]]:
    stmt = text(
        """
        select trr.id, trr.batch_id, trr.batch_line_id, trr.qty_received,
               trr.battery_check_code, trr.pieces_checked, trr.batteries_installed,
               bt.name as battery_type_name, trr.cleaning_code,
               trr.functional_good_qty, trr.functional_repaired_qty,
               trr.non_good_qty, trr.non_sellable_qty,
               trr.evaluation_notes, trr.technician_remarks,
               p.full_name as entry_by_name, trr.received_at
        from public.technician_receiving_records trr
        join public.profiles p on p.id = trr.entry_by
        left join public.battery_types bt on bt.id = trr.battery_type_id
        where trr.batch_id = :batch_id
        order by trr.received_at asc
        """
    )
    return [dict(r) for r in session.execute(stmt, {"batch_id": batch_id}).mappings().all()]


def list_batches(
    session: Session,
    *,
    status: str | None = None,
    technician_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    stmt = text(
        """
        select tb.id, tb.batch_no, t.display_name as technician_name,
               p.full_name as entry_by_name, tb.status,
               greatest(0,
                 floor(extract(epoch from (now() - tb.allotted_at)) / 86400)::int
                ) as age_days,
               tb.allotted_at,
               coalesce(sum(tbl.qty_allotted), 0)::int as total_qty_allotted,
               coalesce(sum(tbl.qty_received), 0)::int as total_qty_received,
               count(tbl.id)::int as line_count
        from public.technician_batches tb
        join public.technicians t on t.id = tb.technician_id
        join public.profiles p on p.id = tb.entry_by
        left join public.technician_batch_lines tbl on tbl.batch_id = tb.id
        where (cast(:status as text) is null or tb.status = cast(:status as text))
          and (cast(:tech_id as uuid) is null or tb.technician_id = cast(:tech_id as uuid))
        group by tb.id, tb.batch_no, t.display_name, p.full_name, tb.status, tb.allotted_at
        order by tb.created_at desc
        limit :limit offset :offset
        """
    )
    return [
        dict(r)
        for r in session.execute(
            stmt,
            {
                "status": status.upper() if status else None,
                "tech_id": technician_id,
                "limit": limit,
                "offset": offset,
            },
        )
        .mappings()
        .all()
    ]


def get_lot(session: Session, lot_id: UUID, for_update: bool = False) -> dict[str, Any] | None:
    sql = """
        select sl.id, sl.stock_item_id, sl.gs_id, sl.gs_item_id, sl.condition_class,
               sl.source_condition_code, sl.routing_hint, sl.requires_evaluation
        from public.stock_lots sl
        where sl.id = :id
    """
    if for_update:
        sql += " for update of sl"  # lock only this row (P3-08: deadlock)
    row = session.execute(text(sql), {"id": lot_id}).mappings().one_or_none()
    return dict(row) if row else None


def find_or_create_target_lot(
    session: Session,
    *,
    stock_item_id: UUID,
    gs_id: UUID,
    gs_item_id: UUID | None,
    condition_class: str,
    source_condition_code: str | None,
    routing_hint: str | None,
    created_by: UUID | None,
) -> UUID:
    """Find existing lot or create new lot with desired condition class."""
    find_stmt = text(
        """
        select id from public.stock_lots
        where stock_item_id = :stock_item_id
          and gs_id = :gs_id
          and condition_class = :condition_class
          and (source_condition_code is not distinct from :source_cond)
        limit 1
        """
    )
    existing_id = session.execute(
        find_stmt,
        {
            "stock_item_id": stock_item_id,
            "gs_id": gs_id,
            "condition_class": condition_class,
            "source_cond": source_condition_code,
        },
    ).scalar_one_or_none()

    if existing_id:
        if routing_hint:
            session.execute(
                text("update public.stock_lots set routing_hint = :hint where id = :id"),
                {"hint": routing_hint, "id": existing_id},
            )
        return UUID(str(existing_id))

    # Lots are created only by the inventory ledger module (test_ledger_architecture, rule f).
    return ledger_service.create_stock_lot(
        session,
        stock_item_id=stock_item_id,
        gs_id=gs_id,
        gs_item_id=gs_item_id,
        condition_class=condition_class,
        source_condition_code=source_condition_code,
        routing_hint=routing_hint,
        created_by=created_by,
    )


def get_battery_reconciliation_summary(
    session: Session,
    *,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> dict[str, Any]:
    """Query data for battery reconciliation (WF r8)."""
    # 1. Receiving records aggregate
    rec_stmt = text(
        """
        select coalesce(sum(pieces_checked), 0)::int as total_pieces_checked,
               coalesce(sum(case when battery_check_code = 'BATTERY_REPLACED'
                          then qty_received else 0 end), 0)::int as pieces_battery_replaced,
               coalesce(sum(batteries_installed), 0)::int as total_batteries_installed
        from public.technician_receiving_records
        where (cast(:from_dt as timestamptz) is null
                 or received_at >= cast(:from_dt as timestamptz))
          and (cast(:to_dt as timestamptz) is null
                 or received_at <= cast(:to_dt as timestamptz))
        """
    )
    rec_agg = dict(
        session.execute(rec_stmt, {"from_dt": from_date, "to_dt": to_date}).mappings().one()
    )

    # 2. Battery stock consumption aggregate from ledger movements
    mov_stmt = text(
        """
        select coalesce(sum(sm.qty), 0)::int as total_stock_consumed
        from public.stock_movements sm
        join public.stock_lots sl on sl.id = sm.lot_id
        join public.stock_items si on si.id = sl.stock_item_id
        join public.inventory_locations loc on loc.id = sm.from_location_id
        where sm.movement_type = 'CONSUME'
          and loc.code = 'BATTERY_STORE'
          and si.item_kind = 'BATTERY'
          and (cast(:from_dt as timestamptz) is null
                 or sm.created_at >= cast(:from_dt as timestamptz))
          and (cast(:to_dt as timestamptz) is null
                 or sm.created_at <= cast(:to_dt as timestamptz))
        """
    )
    mov_agg = session.execute(mov_stmt, {"from_dt": from_date, "to_dt": to_date}).scalar_one()

    # 3. Per battery type breakdown
    breakdown_stmt = text(
        """
        select bt.id as battery_type_id,
               bt.code as battery_type_code,
               bt.name as battery_type_name,
               coalesce(rec.installed, 0)::int as batteries_installed,
               coalesce(mov.consumed, 0)::int as battery_stock_movements
        from public.battery_types bt
        left join (
            select trr.battery_type_id, sum(trr.batteries_installed) as installed
            from public.technician_receiving_records trr
            where trr.battery_check_code = 'BATTERY_REPLACED'
              and (cast(:from_dt as timestamptz) is null
                     or trr.received_at >= cast(:from_dt as timestamptz))
              and (cast(:to_dt as timestamptz) is null
                     or trr.received_at <= cast(:to_dt as timestamptz))
            group by trr.battery_type_id
        ) rec on rec.battery_type_id = bt.id
        left join (
            select si.battery_type_id, sum(sm.qty) as consumed
            from public.stock_movements sm
            join public.stock_lots sl on sl.id = sm.lot_id
            join public.stock_items si on si.id = sl.stock_item_id
            join public.inventory_locations loc on loc.id = sm.from_location_id
            where sm.movement_type = 'CONSUME'
              and loc.code = 'BATTERY_STORE'
              and si.item_kind = 'BATTERY'
              and (cast(:from_dt as timestamptz) is null
                     or sm.created_at >= cast(:from_dt as timestamptz))
              and (cast(:to_dt as timestamptz) is null
                     or sm.created_at <= cast(:to_dt as timestamptz))
            group by si.battery_type_id
        ) mov on mov.battery_type_id = bt.id
        where bt.is_active = true
        order by bt.code asc
        """
    )
    type_rows = [
        dict(r)
        for r in session.execute(breakdown_stmt, {"from_dt": from_date, "to_dt": to_date})
        .mappings()
        .all()
    ]

    return {
        "pieces_checked": rec_agg["total_pieces_checked"],
        "pieces_battery_replaced": rec_agg["pieces_battery_replaced"],
        "batteries_installed": rec_agg["total_batteries_installed"],
        "battery_stock_movements": int(mov_agg or 0),
        "by_battery_type": type_rows,
    }
