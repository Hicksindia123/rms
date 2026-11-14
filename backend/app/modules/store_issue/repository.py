"""Repository for Step-6 Store Issues (P3-05).

Master plan references: BR-19, BR-31, DEC-21, G-04.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def get_candidate_lots_for_store_issue(session: Session) -> list[dict[str, Any]]:
    """Return functional lots available in INTERMEDIATE_STORE that can be issued to MAIN_STORE."""
    stmt = text(
        """
        select
            sb.lot_id,
            sl.stock_item_id,
            p.id as product_id,
            p.code as product_code,
            p.name as product_name,
            sl.condition_class,
            sb.qty as available_qty,
            sl.gs_id,
            gs.gs_no
        from public.stock_balances sb
        join public.stock_lots sl on sl.id = sb.lot_id
        join public.stock_items si on si.id = sl.stock_item_id
        join public.products p on p.id = si.product_id
        join public.inventory_locations loc on loc.id = sb.location_id
        left join public.goods_slips gs on gs.id = sl.gs_id
        where loc.code = 'INTERMEDIATE_STORE'
          and sl.condition_class in ('FUNCTIONAL_GOOD', 'FUNCTIONAL_REPAIRED')
          and sb.qty > 0
        order by p.code, sl.created_at
        """
    )
    return [dict(r) for r in session.execute(stmt).mappings().all()]


def get_lot_with_balance(
    session: Session,
    lot_id: UUID,
    location_code: str = "INTERMEDIATE_STORE",
) -> dict[str, Any] | None:
    stmt = text(
        """
        select
            sl.id as lot_id,
            sl.stock_item_id,
            sl.condition_class,
            sl.gs_id,
            coalesce(sb.qty, 0) as balance_qty,
            loc.id as location_id,
            loc.code as location_code
        from public.stock_lots sl
        join public.inventory_locations loc on loc.code = :location_code
        left join public.stock_balances sb on sb.lot_id = sl.id and sb.location_id = loc.id
        where sl.id = :lot_id
        """
    )
    row = (
        session.execute(stmt, {"lot_id": lot_id, "location_code": location_code}).mappings().first()
    )
    return dict(row) if row else None


def insert_store_issue(
    session: Session,
    *,
    issue_no: str,
    issue_type_code: str,
    from_location_id: UUID,
    to_location_id: UUID,
    status: str,
    notes: str | None,
    created_by: UUID,
    transfer_id: UUID | None = None,
    acknowledged_at: Any = None,
    acknowledged_by: UUID | None = None,
) -> UUID:
    stmt = text(
        """
        insert into public.store_issues (
            issue_no, issue_type_code, from_location_id, to_location_id,
            status, notes, created_by, transfer_id,
            acknowledged_at, acknowledged_by
        ) values (
            :issue_no, :issue_type_code, :from_location_id, :to_location_id,
            :status, :notes, :created_by, :transfer_id,
            :acknowledged_at, :acknowledged_by
        )
        returning id
        """
    )
    res = session.execute(
        stmt,
        {
            "issue_no": issue_no,
            "issue_type_code": issue_type_code,
            "from_location_id": from_location_id,
            "to_location_id": to_location_id,
            "status": status,
            "notes": notes,
            "created_by": created_by,
            "transfer_id": transfer_id,
            "acknowledged_at": acknowledged_at,
            "acknowledged_by": acknowledged_by,
        },
    ).scalar_one()
    return UUID(str(res))


def insert_store_issue_line(
    session: Session,
    *,
    issue_id: UUID,
    lot_id: UUID,
    qty: int,
) -> UUID:
    stmt = text(
        """
        insert into public.store_issue_lines (issue_id, lot_id, qty)
        values (:issue_id, :lot_id, :qty)
        returning id
        """
    )
    res = session.execute(
        stmt,
        {"issue_id": issue_id, "lot_id": lot_id, "qty": qty},
    ).scalar_one()
    return UUID(str(res))


def update_store_issue_transfer(
    session: Session,
    issue_id: UUID,
    transfer_id: UUID,
) -> None:
    stmt = text(
        """
        update public.store_issues
           set transfer_id = :transfer_id
         where id = :issue_id
        """
    )
    session.execute(stmt, {"issue_id": issue_id, "transfer_id": transfer_id})


def acknowledge_store_issue(
    session: Session,
    issue_id: UUID,
    actor_id: UUID,
) -> None:
    stmt = text(
        """
        update public.store_issues
           set status = 'ACKNOWLEDGED',
               acknowledged_at = now(),
               acknowledged_by = :actor_id
         where id = :issue_id
        """
    )
    session.execute(stmt, {"issue_id": issue_id, "actor_id": actor_id})


def get_store_issue(session: Session, issue_id: UUID) -> dict[str, Any] | None:
    stmt = text(
        """
        select
            si.id,
            si.issue_no,
            si.issue_type_code,
            si.from_location_id,
            floc.name as from_location_name,
            si.to_location_id,
            tloc.name as to_location_name,
            si.status,
            si.transfer_id,
            si.notes,
            si.created_at,
            si.created_by,
            coalesce(cp.full_name, 'System') as created_by_name,
            si.acknowledged_at,
            si.acknowledged_by,
            coalesce(ap.full_name, null) as acknowledged_by_name
        from public.store_issues si
        join public.inventory_locations floc on floc.id = si.from_location_id
        join public.inventory_locations tloc on tloc.id = si.to_location_id
        left join public.profiles cp on cp.id = si.created_by
        left join public.profiles ap on ap.id = si.acknowledged_by
        where si.id = :issue_id
        """
    )
    row = session.execute(stmt, {"issue_id": issue_id}).mappings().first()
    return dict(row) if row else None


def get_store_issue_lines(session: Session, issue_id: UUID) -> list[dict[str, Any]]:
    stmt = text(
        """
        select
            sil.id,
            sil.issue_id,
            sil.lot_id,
            sil.qty,
            p.code as product_code,
            p.name as product_name,
            sl.condition_class,
            sl.gs_id,
            gs.gs_no
        from public.store_issue_lines sil
        join public.stock_lots sl on sl.id = sil.lot_id
        join public.stock_items si on si.id = sl.stock_item_id
        join public.products p on p.id = si.product_id
        left join public.goods_slips gs on gs.id = sl.gs_id
        where sil.issue_id = :issue_id
        order by sil.created_at asc
        """
    )
    return [dict(r) for r in session.execute(stmt, {"issue_id": issue_id}).mappings().all()]


def list_store_issues(
    session: Session,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    where_clauses = ["1=1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if status:
        where_clauses.append("si.status = :status")
        params["status"] = status

    where_sql = " and ".join(where_clauses)  # constant clause strings; values are bound
    stmt = text(
        f"""
        select
            si.id,
            si.issue_no,
            si.issue_type_code,
            si.from_location_id,
            floc.name as from_location_name,
            si.to_location_id,
            tloc.name as to_location_name,
            si.status,
            si.transfer_id,
            si.notes,
            si.created_at,
            si.created_by,
            coalesce(cp.full_name, 'System') as created_by_name,
            si.acknowledged_at,
            si.acknowledged_by,
            coalesce(ap.full_name, null) as acknowledged_by_name,
            coalesce(sum(sil.qty), 0) as total_qty
        from public.store_issues si
        join public.inventory_locations floc on floc.id = si.from_location_id
        join public.inventory_locations tloc on tloc.id = si.to_location_id
        left join public.profiles cp on cp.id = si.created_by
        left join public.profiles ap on ap.id = si.acknowledged_by
        left join public.store_issue_lines sil on sil.issue_id = si.id
        where {where_sql}
        group by si.id, floc.name, tloc.name, cp.full_name, ap.full_name
        order by si.created_at desc
        limit :limit offset :offset
        """  # noqa: S608 - fixed SQL fragments, all values are bound parameters
    )
    return [dict(r) for r in session.execute(stmt, params).mappings().all()]
