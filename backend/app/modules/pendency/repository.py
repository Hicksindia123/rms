"""Repository for Pendency register and operations.

Master plan references: WF r7 col K, BR-20, DEC-12, G-08.
"""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def get_pendency(session: Session, pendency_id: UUID) -> dict[str, Any] | None:
    stmt = text(
        """
        select p.id, p.gs_id, p.gs_item_id, p.qty, p.reason, p.sent_to, p.blocks_gs,
               p.status, p.lot_id, p.stock_movement_id,
               p.opened_by, p.opened_at, p.cleared_by, p.cleared_at,
               p.clearance_notes, p.resolution_action,
               gs.gs_no, pt.name as party_name,
               gi.line_no, prod.name as product_name,
               op.full_name as opened_by_name,
               cp.full_name as cleared_by_name
          from public.pendencies p
          join public.goods_slips gs on gs.id = p.gs_id
          left join public.parties pt on pt.id = gs.party_id
          left join public.gs_items gi on gi.id = p.gs_item_id
          left join public.products prod on prod.id = gi.product_id
          left join public.profiles op on op.id = p.opened_by
          left join public.profiles cp on cp.id = p.cleared_by
         where p.id = :id
        """
    )
    row = session.execute(stmt, {"id": pendency_id}).mappings().first()
    return dict(row) if row else None


def list_pendencies(
    session: Session,
    status: str | None = None,
    gs_id: UUID | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[dict[str, Any]]:
    filter_status = None
    if status and status.upper() != "ALL":
        filter_status = status.upper()

    stmt = text(
        """
        select p.id, p.gs_id, p.gs_item_id, p.qty, p.reason, p.sent_to, p.blocks_gs,
               p.status, p.lot_id, p.stock_movement_id,
               p.opened_by, p.opened_at, p.cleared_by, p.cleared_at,
               p.clearance_notes, p.resolution_action,
               gs.gs_no, pt.name as party_name,
               gi.line_no, prod.name as product_name,
               op.full_name as opened_by_name,
               cp.full_name as cleared_by_name
          from public.pendencies p
          join public.goods_slips gs on gs.id = p.gs_id
          left join public.parties pt on pt.id = gs.party_id
          left join public.gs_items gi on gi.id = p.gs_item_id
          left join public.products prod on prod.id = gi.product_id
          left join public.profiles op on op.id = p.opened_by
          left join public.profiles cp on cp.id = p.cleared_by
         where (cast(:status as text) is null or p.status = :status)
           and (cast(:gs_id as uuid) is null or p.gs_id = :gs_id)
           and (cast(:from_date as date) is null or p.opened_at >= :from_date)
           and (cast(:to_date as date) is null or p.opened_at <= :to_date)
         order by p.opened_at desc
        """
    )
    params = {
        "status": filter_status,
        "gs_id": gs_id,
        "from_date": from_date,
        "to_date": to_date,
    }
    return [dict(r) for r in session.execute(stmt, params).mappings().all()]


def clear_pendency_db(
    session: Session,
    pendency_id: UUID,
    resolution_action: str,
    notes: str,
    actor_id: UUID,
) -> None:
    stmt = text(
        """
        update public.pendencies
           set status = 'CLEARED',
               resolution_action = :resolution_action,
               clearance_notes = :notes,
               cleared_by = :actor_id,
               cleared_at = now()
         where id = :id
        """
    )
    session.execute(
        stmt,
        {
            "id": pendency_id,
            "resolution_action": resolution_action,
            "notes": notes,
            "actor_id": actor_id,
        },
    )
