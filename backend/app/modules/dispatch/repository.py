"""Repository for Replacement Dispatch (P3-05).

Master plan references: BR-19, BR-31, BR-32, DEC-26, DEC-33, §8.6.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def get_dispatch_queue(session: Session) -> list[dict[str, Any]]:
    stmt = text(
        """
        select
            gs.id as gs_id,
            gs.gs_no,
            gs.party_id,
            coalesce(p.name, 'Unknown Party') as party_name,
            gi.id as gs_item_id,
            gi.line_no,
            prod.id as product_id,
            prod.code as product_code,
            prod.name as product_name,
            ra.action_code,
            ra.qty as planned_qty,
            coalesce(disp.dispatched_qty, 0) as dispatched_qty,
            (ra.qty - coalesce(disp.dispatched_qty, 0)) as pending_qty,
            coalesce(rep_stock.available_qty, 0) as available_repaired_qty
        from public.rm_item_actions ra
        join public.gs_items gi on gi.id = ra.gs_item_id
        join public.goods_slips gs on gs.id = gi.gs_id
        join public.products prod on prod.id = gi.product_id
        left join public.parties p on p.id = gs.party_id
        left join (
            select rdl.gs_item_id, rd.dispatch_type, sum(rdl.qty) as dispatched_qty
            from public.replacement_dispatch_lines rdl
            join public.replacement_dispatches rd on rd.id = rdl.dispatch_id
            group by rdl.gs_item_id, rd.dispatch_type
        ) disp on disp.gs_item_id = gi.id and disp.dispatch_type = ra.action_code
        left join (
            select sl.gs_item_id, sum(sb.qty) as available_qty
            from public.stock_balances sb
            join public.stock_lots sl on sl.id = sb.lot_id
            join public.inventory_locations loc on loc.id = sb.location_id
            where loc.code in ('INTERMEDIATE_STORE', 'MAIN_STORE')
              and sl.condition_class = 'FUNCTIONAL_REPAIRED'
            group by sl.gs_item_id
        ) rep_stock on rep_stock.gs_item_id = gi.id
        where ra.is_current = true
          and ra.action_code in ('SEND_NEW', 'SEND_REPAIRED')
          and ra.qty > coalesce(disp.dispatched_qty, 0)
          and gs.status not in ('CLOSED', 'CANCELLED')
          -- AMD-19 / G-22: goods slips on the A/c Actions flow ship against their Dispatch Slip.
          and not rms_private.gs_on_final_action_flow(gs.id)
        order by gs.created_at asc, gi.line_no asc
        """
    )
    return [dict(r) for r in session.execute(stmt).mappings().all()]


def get_candidate_lots_for_dispatch(
    session: Session,
    product_id: UUID | None = None,
    gs_item_id: UUID | None = None,
) -> list[dict[str, Any]]:
    where_parts = [
        "loc.code in ('INTERMEDIATE_STORE', 'MAIN_STORE')",
        "sl.condition_class = 'FUNCTIONAL_REPAIRED'",
        "sb.qty > 0",
    ]
    params: dict[str, Any] = {}
    if product_id:
        where_parts.append("prod.id = :product_id")
        params["product_id"] = product_id
    if gs_item_id:
        where_parts.append("sl.gs_item_id = :gs_item_id")
        params["gs_item_id"] = gs_item_id

    where_sql = " and ".join(where_parts)  # constant clause strings; values are bound
    stmt = text(
        f"""
        select
            sb.lot_id,
            sl.stock_item_id,
            prod.id as product_id,
            prod.code as product_code,
            prod.name as product_name,
            loc.id as location_id,
            loc.code as location_code,
            sl.condition_class,
            sb.qty as available_qty,
            sl.gs_id,
            gs.gs_no
        from public.stock_balances sb
        join public.stock_lots sl on sl.id = sb.lot_id
        join public.stock_items si on si.id = sl.stock_item_id
        join public.products prod on prod.id = si.product_id
        join public.inventory_locations loc on loc.id = sb.location_id
        left join public.goods_slips gs on gs.id = sl.gs_id
        where {where_sql}
        order by prod.code, sl.created_at asc
        """  # noqa: S608 - fixed SQL fragments, all values are bound parameters
    )
    return [dict(r) for r in session.execute(stmt, params).mappings().all()]


def get_item_actions_for_dispatch(
    session: Session,
    gs_item_id: UUID,
) -> list[dict[str, Any]]:
    stmt = text(
        """
        select action_code, qty, is_current
        from public.rm_item_actions
        where gs_item_id = :gs_item_id and is_current = true
        """
    )
    return [dict(r) for r in session.execute(stmt, {"gs_item_id": gs_item_id}).mappings().all()]


def get_already_dispatched_qty_for_item(
    session: Session,
    gs_item_id: UUID,
    dispatch_type: str,
) -> int:
    stmt = text(
        """
        select coalesce(sum(rdl.qty), 0)
        from public.replacement_dispatch_lines rdl
        join public.replacement_dispatches rd on rd.id = rdl.dispatch_id
        where rdl.gs_item_id = :gs_item_id
          and rd.dispatch_type = :dispatch_type
        """
    )
    return int(
        session.execute(
            stmt, {"gs_item_id": gs_item_id, "dispatch_type": dispatch_type}
        ).scalar_one()
    )


def get_lot_for_dispatch(
    session: Session,
    lot_id: UUID,
) -> dict[str, Any] | None:
    stmt = text(
        """
        select
            sl.id as lot_id,
            sl.stock_item_id,
            sl.condition_class,
            sl.gs_id,
            sl.gs_item_id,
            sb.location_id,
            loc.code as location_code,
            coalesce(sb.qty, 0) as balance_qty
        from public.stock_lots sl
        join public.stock_balances sb on sb.lot_id = sl.id and sb.qty > 0
        join public.inventory_locations loc on loc.id = sb.location_id
        where sl.id = :lot_id and loc.code in ('INTERMEDIATE_STORE', 'MAIN_STORE')
        limit 1
        """
    )
    row = session.execute(stmt, {"lot_id": lot_id}).mappings().first()
    return dict(row) if row else None


def insert_dispatch(
    session: Session,
    *,
    dispatch_no: str,
    gs_id: UUID,
    dispatch_type: str,
    transporter: str,
    docket_no: str | None,
    vehicle_no: str | None,
    ref_doc_no: str | None,
    ref_doc_date: Any,
    override_reason: str | None,
    notes: str | None,
    dispatched_by: UUID,
) -> UUID:
    stmt = text(
        """
        insert into public.replacement_dispatches (
            dispatch_no, gs_id, dispatch_type, transporter,
            docket_no, vehicle_no, ref_doc_no, ref_doc_date,
            override_reason, notes, status, dispatched_by
        ) values (
            :dispatch_no, :gs_id, :dispatch_type, :transporter,
            :docket_no, :vehicle_no, :ref_doc_no, :ref_doc_date,
            :override_reason, :notes, 'DISPATCHED', :dispatched_by
        )
        returning id
        """
    )
    res = session.execute(
        stmt,
        {
            "dispatch_no": dispatch_no,
            "gs_id": gs_id,
            "dispatch_type": dispatch_type,
            "transporter": transporter,
            "docket_no": docket_no,
            "vehicle_no": vehicle_no,
            "ref_doc_no": ref_doc_no,
            "ref_doc_date": ref_doc_date,
            "override_reason": override_reason,
            "notes": notes,
            "dispatched_by": dispatched_by,
        },
    ).scalar_one()
    return UUID(str(res))


def insert_dispatch_line(
    session: Session,
    *,
    dispatch_id: UUID,
    gs_item_id: UUID,
    lot_id: UUID | None,
    qty: int,
) -> UUID:
    stmt = text(
        """
        insert into public.replacement_dispatch_lines (
            dispatch_id, gs_item_id, lot_id, qty
        ) values (
            :dispatch_id, :gs_item_id, :lot_id, :qty
        )
        returning id
        """
    )
    res = session.execute(
        stmt,
        {
            "dispatch_id": dispatch_id,
            "gs_item_id": gs_item_id,
            "lot_id": lot_id,
            "qty": qty,
        },
    ).scalar_one()
    return UUID(str(res))


def get_dispatch(session: Session, dispatch_id: UUID) -> dict[str, Any] | None:
    stmt = text(
        """
        select
            rd.id,
            rd.dispatch_no,
            rd.gs_id,
            gs.gs_no,
            coalesce(p.name, 'Unknown Party') as party_name,
            rd.dispatch_type,
            rd.transporter,
            rd.docket_no,
            rd.vehicle_no,
            rd.ref_doc_no,
            rd.ref_doc_date,
            rd.status,
            rd.dispatched_at,
            rd.dispatched_by,
            coalesce(prof.full_name, 'System') as dispatched_by_name,
            rd.override_reason,
            rd.notes
        from public.replacement_dispatches rd
        join public.goods_slips gs on gs.id = rd.gs_id
        left join public.parties p on p.id = gs.party_id
        left join public.profiles prof on prof.id = rd.dispatched_by
        where rd.id = :dispatch_id
        """
    )
    row = session.execute(stmt, {"dispatch_id": dispatch_id}).mappings().first()
    return dict(row) if row else None


def get_dispatch_lines(session: Session, dispatch_id: UUID) -> list[dict[str, Any]]:
    stmt = text(
        """
        select
            rdl.id,
            rdl.dispatch_id,
            rdl.gs_item_id,
            rdl.lot_id,
            rdl.qty,
            prod.code as product_code,
            prod.name as product_name,
            sl.condition_class
        from public.replacement_dispatch_lines rdl
        join public.gs_items gi on gi.id = rdl.gs_item_id
        join public.products prod on prod.id = gi.product_id
        left join public.stock_lots sl on sl.id = rdl.lot_id
        where rdl.dispatch_id = :dispatch_id
        order by gi.line_no asc
        """
    )
    return [dict(r) for r in session.execute(stmt, {"dispatch_id": dispatch_id}).mappings().all()]


def list_dispatches(
    session: Session,
    *,
    gs_id: UUID | None = None,
    dispatch_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    where_parts = ["1=1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if gs_id:
        where_parts.append("rd.gs_id = :gs_id")
        params["gs_id"] = gs_id
    if dispatch_type:
        where_parts.append("rd.dispatch_type = :dispatch_type")
        params["dispatch_type"] = dispatch_type

    where_sql = " and ".join(where_parts)  # constant clause strings; values are bound
    stmt = text(
        f"""
        select
            rd.id,
            rd.dispatch_no,
            rd.gs_id,
            gs.gs_no,
            coalesce(p.name, 'Unknown Party') as party_name,
            rd.dispatch_type,
            rd.transporter,
            rd.docket_no,
            rd.vehicle_no,
            rd.ref_doc_no,
            rd.ref_doc_date,
            rd.status,
            rd.dispatched_at,
            rd.dispatched_by,
            coalesce(prof.full_name, 'System') as dispatched_by_name,
            rd.override_reason,
            rd.notes,
            coalesce(sum(rdl.qty), 0) as total_qty
        from public.replacement_dispatches rd
        join public.goods_slips gs on gs.id = rd.gs_id
        left join public.parties p on p.id = gs.party_id
        left join public.profiles prof on prof.id = rd.dispatched_by
        left join public.replacement_dispatch_lines rdl on rdl.dispatch_id = rd.id
        where {where_sql}
        group by rd.id, gs.gs_no, p.name, prof.full_name
        order by rd.dispatched_at desc
        limit :limit offset :offset
        """  # noqa: S608 - fixed SQL fragments, all values are bound parameters
    )
    return [dict(r) for r in session.execute(stmt, params).mappings().all()]


def is_on_final_action_flow(session: Session, gs_id: UUID) -> bool:
    """AMD-13/17 flow marker (DB function, same as the G-21 / G-22 triggers use)."""
    return bool(
        session.execute(
            text("select rms_private.gs_on_final_action_flow(:gs_id)"), {"gs_id": gs_id}
        ).scalar()
    )
