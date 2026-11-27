"""Authoritative Inventory Ledger Service (master plan §8.5, prompt P2-01).

All stock quantity changes MUST go through rms_private.rms_move_stock or
rms_private.rms_reclassify_lot. Direct INSERT/UPDATE/DELETE on stock_movements
or stock_balances from application code is strictly forbidden.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.errors import IdempotencyConflict, SystemGuardViolation

_GUARD_REGEX = re.compile(r"\b(G-(?:0[1-9]|1[0-9]|2[0-2]))\b")  # G-22: Phase 8


def _handle_db_error(exc: DBAPIError) -> None:
    orig = str(getattr(exc, "orig", exc))
    if "idempotency conflict" in orig.lower():
        first_line = orig.splitlines()[0] if orig else "Idempotency conflict"
        clean = first_line.replace("ERROR:", "").strip()
        raise IdempotencyConflict(clean) from exc
    match = _GUARD_REGEX.search(orig)
    if match:
        guard = match.group(1)
        first_line = orig.splitlines()[0] if orig else f"System guard {guard} violation"
        clean = first_line.replace("ERROR:", "").strip()
        raise SystemGuardViolation(guard=guard, message=clean) from exc
    raise exc


def create_stock_item(
    session: Session,
    *,
    item_kind: str,
    product_id: UUID | None = None,
    part_type: str | None = None,
    battery_type_id: UUID | None = None,
    pcb_model_id: UUID | None = None,
    pcb_supplier_id: UUID | None = None,
    created_by: UUID | None = None,
) -> UUID:
    """Create a catalog stock item."""
    stmt = text(
        """
        insert into public.stock_items (
          item_kind, product_id, part_type, battery_type_id,
          pcb_model_id, pcb_supplier_id, created_by
        ) values (
          :item_kind, :product_id, :part_type, :battery_type_id,
          :pcb_model_id, :pcb_supplier_id, :created_by
        )
        returning id
        """
    )
    res = session.execute(
        stmt,
        {
            "item_kind": item_kind,
            "product_id": product_id,
            "part_type": part_type,
            "battery_type_id": battery_type_id,
            "pcb_model_id": pcb_model_id,
            "pcb_supplier_id": pcb_supplier_id,
            "created_by": created_by,
        },
    ).scalar_one()
    return UUID(str(res))


def create_stock_lot(
    session: Session,
    *,
    stock_item_id: UUID,
    gs_id: UUID | None = None,
    condition_class: str,
    gs_item_id: UUID | None = None,
    source_condition_code: str | None = None,
    container_id: UUID | None = None,
    partition_id: UUID | None = None,
    is_pending: bool = False,
    requires_evaluation: bool = False,
    routing_hint: str | None = None,
    created_by: UUID | None = None,
    ecommerce_return_id: UUID | None = None,
) -> UUID:
    """Create a tracked stock lot associated with a goods slip, or (DEC-76) with an E-Commerce
    Return (no goods slip)."""
    stmt = text(
        """
        insert into public.stock_lots (
          stock_item_id, gs_id, gs_item_id, condition_class,
          source_condition_code, container_id, partition_id, is_pending,
          requires_evaluation, routing_hint, created_by, ecommerce_return_id
        ) values (
          :stock_item_id, :gs_id, :gs_item_id, :condition_class,
          :source_condition_code, :container_id, :partition_id, :is_pending,
          :requires_evaluation, :routing_hint, :created_by, :ecommerce_return_id
        )
        returning id
        """
    )
    res = session.execute(
        stmt,
        {
            "stock_item_id": stock_item_id,
            "gs_id": gs_id,
            "gs_item_id": gs_item_id,
            "condition_class": condition_class,
            "source_condition_code": source_condition_code,
            "container_id": container_id,
            "partition_id": partition_id,
            "is_pending": is_pending,
            "requires_evaluation": requires_evaluation,
            "routing_hint": routing_hint,
            "created_by": created_by,
            "ecommerce_return_id": ecommerce_return_id,
        },
    ).scalar_one()
    return UUID(str(res))


def move_stock(
    session: Session,
    *,
    lot_id: UUID,
    from_location_id: UUID | None,
    to_location_id: UUID | None,
    qty: int,
    movement_type: str,
    reference_type: str | None = None,
    reference_id: UUID | None = None,
    idempotency_key: str,
    actor_id: UUID | None = None,
    reason: str | None = None,
) -> UUID:
    """Execute a guarded stock movement through rms_private.rms_move_stock."""
    stmt = text(
        """
        select rms_private.rms_move_stock(
          p_lot := cast(:lot_id as uuid),
          p_from := cast(:from_loc as uuid),
          p_to := cast(:to_loc as uuid),
          p_qty := cast(:qty as integer),
          p_type := cast(:movement_type as text),
          p_ref_type := cast(:ref_type as text),
          p_ref_id := cast(:ref_id as uuid),
          p_idem_key := cast(:idem_key as text),
          p_actor := cast(:actor_id as uuid),
          p_reason := cast(:reason as text)
        ) as movement_id
        """
    )
    try:
        result = session.execute(
            stmt,
            {
                "lot_id": lot_id,
                "from_loc": from_location_id,
                "to_loc": to_location_id,
                "qty": qty,
                "movement_type": movement_type,
                "ref_type": reference_type,
                "ref_id": reference_id,
                "idem_key": idempotency_key,
                "actor_id": actor_id,
                "reason": reason,
            },
        ).scalar_one()
        return UUID(str(result))
    except DBAPIError as exc:
        _handle_db_error(exc)
        raise


def reclassify_lot(
    session: Session,
    *,
    source_lot_id: UUID,
    target_lot_id: UUID,
    location_id: UUID,
    qty: int,
    reference_type: str | None = None,
    reference_id: UUID | None = None,
    idempotency_key: str,
    actor_id: UUID | None = None,
    reason: str | None = None,
) -> list[UUID]:
    """Execute a guarded lot reclassification through rms_private.rms_reclassify_lot."""
    stmt = text(
        """
        select rms_private.rms_reclassify_lot(
          p_source_lot := cast(:source_lot as uuid),
          p_target_lot := cast(:target_lot as uuid),
          p_location := cast(:location_id as uuid),
          p_qty := cast(:qty as integer),
          p_ref_type := cast(:ref_type as text),
          p_ref_id := cast(:ref_id as uuid),
          p_idem_key := cast(:idem_key as text),
          p_actor := cast(:actor_id as uuid),
          p_reason := cast(:reason as text)
        ) as movement_ids
        """
    )
    try:
        result = session.execute(
            stmt,
            {
                "source_lot": source_lot_id,
                "target_lot": target_lot_id,
                "location_id": location_id,
                "qty": qty,
                "ref_type": reference_type,
                "ref_id": reference_id,
                "idem_key": idempotency_key,
                "actor_id": actor_id,
                "reason": reason,
            },
        ).scalar_one()
        if isinstance(result, list):
            return [UUID(str(m)) for m in result]
        return [UUID(str(result))]
    except DBAPIError as exc:
        _handle_db_error(exc)
        raise


def get_balance(session: Session, lot_id: UUID, location_id: UUID) -> int:
    """Return current stock quantity of a lot at a location, or 0 if no record exists."""
    stmt = text(
        """
        select coalesce(qty, 0)
        from public.stock_balances
        where lot_id = :lot_id and location_id = :location_id
        """
    )
    val = session.execute(stmt, {"lot_id": lot_id, "location_id": location_id}).scalar_one_or_none()
    return int(val) if val is not None else 0


def get_balances_by_lot(session: Session, lot_id: UUID) -> list[dict[str, Any]]:
    """Return all non-zero location balances for a specific lot."""
    stmt = text(
        """
        select
          b.lot_id,
          b.location_id,
          b.qty,
          b.updated_at,
          l.code as location_code,
          l.name as location_name,
          l.location_class
        from public.stock_balances b
        join public.inventory_locations l on l.id = b.location_id
        where b.lot_id = :lot_id and b.qty > 0
        order by l.code
        """
    )
    rows = session.execute(stmt, {"lot_id": lot_id}).mappings().all()
    return [dict(r) for r in rows]


def get_balances_by_location(session: Session, location_id: UUID) -> list[dict[str, Any]]:
    """Return all non-zero lot balances at a specific location."""
    stmt = text(
        """
        select
          b.lot_id,
          b.location_id,
          b.qty,
          b.updated_at,
          lot.stock_item_id,
          lot.gs_id,
          lot.condition_class,
          lot.is_pending
        from public.stock_balances b
        join public.stock_lots lot on lot.id = b.lot_id
        where b.location_id = :location_id and b.qty > 0
        order by lot.created_at
        """
    )
    rows = session.execute(stmt, {"location_id": location_id}).mappings().all()
    return [dict(r) for r in rows]


def get_balances_by_gs(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    """Return all non-zero balances for lots originating from a goods slip."""
    stmt = text(
        """
        select
          b.lot_id,
          b.location_id,
          b.qty,
          b.updated_at,
          l.code as location_code,
          l.location_class,
          lot.condition_class,
          lot.is_pending
        from public.stock_balances b
        join public.stock_lots lot on lot.id = b.lot_id
        join public.inventory_locations l on l.id = b.location_id
        where lot.gs_id = :gs_id and b.qty > 0
        order by l.code, lot.created_at
        """
    )
    rows = session.execute(stmt, {"gs_id": gs_id}).mappings().all()
    return [dict(r) for r in rows]


# --- P2-04 · helpers for Step-3 inward ---------------------------------------------------------
def get_location_by_code(session: Session, code: str) -> dict[str, Any] | None:
    """An inventory location (custody holder) by its system code, e.g. INWARD_STAGING."""
    row = (
        session.execute(
            text(
                """
                select l.id, l.code, l.name, l.location_class, l.custodian_role_id,
                       r.code as custodian_role_code, l.custodian_user_id, l.is_active
                  from public.inventory_locations l
                  left join public.roles r on r.id = l.custodian_role_id
                 where l.code = :code
                """
            ),
            {"code": code},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def finished_good_item(session: Session, product_id: UUID, created_by: UUID | None) -> UUID:
    """The FINISHED_GOOD stock item of a product (created on first inward)."""
    existing = session.execute(
        text(
            """
            select id from public.stock_items
             where item_kind = 'FINISHED_GOOD' and product_id = :p
             order by created_at limit 1
            """
        ),
        {"p": product_id},
    ).scalar()
    if existing:
        return UUID(str(existing))
    return create_stock_item(
        session, item_kind="FINISHED_GOOD", product_id=product_id, created_by=created_by
    )


def find_inward_lot(session: Session, gs_item_id: UUID) -> UUID | None:
    """The AS_RECEIVED lot created when the GS line was inwarded (one per line, DEC-28)."""
    value = session.execute(
        text(
            """
            select id from public.stock_lots
             where gs_item_id = :i and condition_class = 'AS_RECEIVED'
               and source_condition_code is null
             order by created_at limit 1
            """
        ),
        {"i": gs_item_id},
    ).scalar()
    return UUID(str(value)) if value else None


def lots_for_gs(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    """Every lot of a GS with its total stock and per-location balances (stock view)."""
    rows = session.execute(
        text(
            """
            select lot.id as lot_id, lot.gs_item_id, lot.condition_class, lot.is_pending,
                   coalesce(sum(b.qty), 0)::int as total_qty,
                   coalesce(jsonb_agg(jsonb_build_object(
                     'location_code', l.code, 'location_name', l.name, 'qty', b.qty)
                     order by l.code) filter (where b.qty > 0), '[]'::jsonb) as balances
              from public.stock_lots lot
              left join public.gs_items gi on gi.id = lot.gs_item_id
              left join public.stock_balances b on b.lot_id = lot.id
              left join public.inventory_locations l on l.id = b.location_id
             where lot.gs_id = :gs
             group by lot.id, gi.line_no
             -- Lots created in one transaction share created_at: order by GS line (P2-08 fix).
             order by gi.line_no nulls last, lot.created_at, lot.id
            """
        ),
        {"gs": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def get_lot(session: Session, lot_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select lot.id, lot.gs_id, lot.gs_item_id, lot.condition_class, lot.is_pending,
                       coalesce((select sum(qty) from public.stock_balances b
                                  where b.lot_id = lot.id), 0)::int as total_qty
                  from public.stock_lots lot where lot.id = :id
                """
            ),
            {"id": lot_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None
