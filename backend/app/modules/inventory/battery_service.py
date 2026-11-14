"""P3-02 Battery Inventory Service (master plan §2.2 Stage-3, DEC-15, BR-24, G-10)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.security import CurrentUser
from app.modules.inventory import ledger_service
from app.modules.inventory.battery_schemas import (
    BatteryAdjustmentApproveIn,
    BatteryAdjustmentIn,
    BatteryAdjustmentOut,
    BatteryAdjustmentRejectIn,
    BatteryBalanceOut,
    BatteryMovementOut,
    BatteryReceiptIn,
    BatteryReceiptOut,
    BatteryTypeOut,
)
from app.modules.notifications import service as notifications

BATTERY_STORE_CODE = "BATTERY_STORE"
LOW_STOCK_SETTING = "battery_low_stock_threshold"


def get_battery_store_location(session: Session) -> dict[str, Any]:
    stmt = text(
        """
        select id, code, name, location_class
        from public.inventory_locations
        where code = :code
        """
    )
    row = session.execute(stmt, {"code": BATTERY_STORE_CODE}).mappings().one_or_none()
    if not row:
        raise NotFound(f"Location {BATTERY_STORE_CODE} not found")
    return dict(row)


def list_battery_types(session: Session) -> list[BatteryTypeOut]:
    stmt = text(
        """
        select id, code, name, is_active
        from public.battery_types
        where is_active = true
        order by code asc
        """
    )
    rows = session.execute(stmt).mappings().all()
    return [BatteryTypeOut(**dict(r)) for r in rows]


def resolve_battery_type(session: Session, identifier: str) -> dict[str, Any]:
    try:
        uid = UUID(identifier)
        stmt = text("select id, code, name, is_active from public.battery_types where id = :val")
        row = session.execute(stmt, {"val": uid}).mappings().one_or_none()
    except ValueError:
        stmt = text("select id, code, name, is_active from public.battery_types where code = :val")
        row = session.execute(stmt, {"val": identifier.strip().upper()}).mappings().one_or_none()

    if not row:
        raise NotFound(f"Battery type '{identifier}' not found", code="BATTERY_TYPE_NOT_FOUND")
    return dict(row)


def get_or_create_battery_stock_lot(
    session: Session, battery_type_id: UUID, created_by: UUID | None = None
) -> tuple[UUID, UUID]:
    """Find or create canonical stock item and lot for item_kind BATTERY at BATTERY_STORE."""
    # 1. stock item
    stmt = text(
        """
        select id from public.stock_items
        where item_kind = 'BATTERY' and battery_type_id = :bt_id
        limit 1
        """
    )
    item_id = session.execute(stmt, {"bt_id": battery_type_id}).scalar_one_or_none()
    if not item_id:
        item_id = ledger_service.create_stock_item(
            session,
            item_kind="BATTERY",
            battery_type_id=battery_type_id,
            created_by=created_by,
        )

    # 2. stock lot (gs_id is null for general battery stock)
    lot_stmt = text(
        """
        select id from public.stock_lots
        where stock_item_id = :item_id and condition_class = 'FUNCTIONAL_GOOD'
        limit 1
        """
    )
    lot_id = session.execute(lot_stmt, {"item_id": item_id}).scalar_one_or_none()
    if not lot_id:
        insert_lot = text(
            """
            insert into public.stock_lots (stock_item_id, condition_class, created_by)
            values (:stock_item_id, 'FUNCTIONAL_GOOD', :created_by)
            returning id
            """
        )
        res = session.execute(
            insert_lot, {"stock_item_id": item_id, "created_by": created_by}
        ).scalar_one()
        lot_id = UUID(str(res))

    return UUID(str(item_id)), UUID(str(lot_id))


def receive_batteries(
    session: Session,
    *,
    user: CurrentUser,
    payload: BatteryReceiptIn,
    idempotency_key: str,
) -> BatteryReceiptOut:
    """Record receipt of batteries into BATTERY_STORE (SPARE_PARTS_MANAGER or admin)."""
    if (
        not user.is_super_admin
        and "SPARE_PARTS_MANAGER" not in user.role_codes
        and "ADMIN" not in user.role_codes
    ):
        raise PermissionDenied(
            "Only Spare Parts Manager or Admin may receive batteries",
            code="NOT_SPARE_PARTS_MANAGER",
        )

    btype = resolve_battery_type(session, payload.battery_type)
    battery_store = get_battery_store_location(session)
    _, lot_id = get_or_create_battery_stock_lot(session, btype["id"], created_by=user.id)

    # Check for existing receipt under idempotency key
    check_stmt = text(
        """
        select r.id, r.battery_type_id, bt.code as battery_type_code, bt.name as battery_type_name,
               r.qty, r.reference_no, r.received_by, p.full_name as received_by_name,
               r.received_at, r.notes
        from public.battery_receipts r
        join public.battery_types bt on bt.id = r.battery_type_id
        join public.profiles p on p.id = r.received_by
        join public.stock_movements sm on sm.id = r.stock_movement_id
        where sm.idempotency_key = :idem_key
        """
    )
    existing = session.execute(check_stmt, {"idem_key": idempotency_key}).mappings().one_or_none()
    if existing:
        return BatteryReceiptOut(**dict(existing))

    # Move stock into BATTERY_STORE
    movement_id = ledger_service.move_stock(
        session,
        lot_id=lot_id,
        from_location_id=None,
        to_location_id=battery_store["id"],
        qty=payload.qty,
        movement_type="RECEIPT",
        reference_type="BATTERY_RECEIPT",
        reference_id=None,
        idempotency_key=idempotency_key,
        actor_id=user.id,
        reason=f"Battery receipt ref {payload.ref}",
    )

    # Insert battery_receipts record
    insert_stmt = text(
        """
        insert into public.battery_receipts (
          battery_type_id, qty, reference_no, received_by, stock_movement_id, notes
        ) values (
          :battery_type_id, :qty, :ref, :received_by, :stock_movement_id, :notes
        )
        returning id, received_at
        """
    )
    res = (
        session.execute(
            insert_stmt,
            {
                "battery_type_id": btype["id"],
                "qty": payload.qty,
                "ref": payload.ref.strip(),
                "received_by": user.id,
                "stock_movement_id": movement_id,
                "notes": payload.notes.strip() if payload.notes else None,
            },
        )
        .mappings()
        .one()
    )

    return BatteryReceiptOut(
        id=UUID(str(res["id"])),
        battery_type_id=btype["id"],
        battery_type_code=btype["code"],
        battery_type_name=btype["name"],
        qty=payload.qty,
        reference_no=payload.ref.strip(),
        received_by=user.id,
        received_by_name=user.full_name,
        received_at=res["received_at"],
        notes=payload.notes.strip() if payload.notes else None,
    )


def request_adjustment(
    session: Session,
    *,
    user: CurrentUser,
    payload: BatteryAdjustmentIn,
) -> BatteryAdjustmentOut:
    """Request an adjustment with mandatory reason (requires approval)."""
    if (
        not user.is_super_admin
        and "SPARE_PARTS_MANAGER" not in user.role_codes
        and "ADMIN" not in user.role_codes
    ):
        raise PermissionDenied(
            "Only Spare Parts Manager or Admin may request battery adjustments",
            code="NOT_SPARE_PARTS_MANAGER",
        )

    if payload.qty == 0:
        raise ValidationFailed("Adjustment quantity cannot be zero", code="QTY_CANNOT_BE_ZERO")

    btype = resolve_battery_type(session, payload.battery_type)
    reason = payload.reason.strip()
    if not reason:
        raise ValidationFailed("Adjustment reason is required", code="REASON_REQUIRED")

    stmt = text(
        """
        insert into public.battery_adjustments (
          battery_type_id, qty, reason, status, requested_by
        ) values (
          :battery_type_id, :qty, :reason, 'PENDING', :requested_by
        )
        returning id, requested_at
        """
    )
    res = (
        session.execute(
            stmt,
            {
                "battery_type_id": btype["id"],
                "qty": payload.qty,
                "reason": reason,
                "requested_by": user.id,
            },
        )
        .mappings()
        .one()
    )

    return BatteryAdjustmentOut(
        id=UUID(str(res["id"])),
        battery_type_id=btype["id"],
        battery_type_code=btype["code"],
        battery_type_name=btype["name"],
        qty=payload.qty,
        reason=reason,
        status="PENDING",
        requested_by=user.id,
        requested_by_name=user.full_name,
        requested_at=res["requested_at"],
        approved_by=None,
        approved_by_name=None,
        approved_at=None,
        approval_notes=None,
    )


def approve_adjustment(
    session: Session,
    *,
    user: CurrentUser,
    adjustment_id: UUID,
    payload: BatteryAdjustmentApproveIn,
    idempotency_key: str,
) -> BatteryAdjustmentOut:
    """Approve a battery adjustment and execute the stock movement."""
    if (
        not user.is_super_admin
        and "ADMIN" not in user.role_codes
        and "REPLACEMENT_MANAGER" not in user.role_codes
    ):
        raise PermissionDenied(
            "Only Admin or Replacement Manager may approve battery adjustments",
            code="NOT_ADJUSTMENT_APPROVER",
        )

    stmt = text(
        """
        select a.id, a.battery_type_id, bt.code as battery_type_code, bt.name as battery_type_name,
               a.qty, a.reason, a.status, a.requested_by, p_req.full_name as requested_by_name,
               a.requested_at, a.approved_by, p_app.full_name as approved_by_name,
               a.approved_at, a.approval_notes, a.stock_movement_id
        from public.battery_adjustments a
        join public.battery_types bt on bt.id = a.battery_type_id
        join public.profiles p_req on p_req.id = a.requested_by
        left join public.profiles p_app on p_app.id = a.approved_by
        where a.id = :id
        for update of a
        """
    )
    row = session.execute(stmt, {"id": adjustment_id}).mappings().one_or_none()
    if not row:
        raise NotFound("Adjustment not found", code="ADJUSTMENT_NOT_FOUND")

    if row["status"] == "APPROVED":
        return BatteryAdjustmentOut(**dict(row))
    if row["status"] != "PENDING":
        raise Conflict(
            f"Adjustment is already {row['status']}",
            code="ADJUSTMENT_NOT_PENDING",
            details={"status": row["status"]},
        )

    battery_store = get_battery_store_location(session)
    _, lot_id = get_or_create_battery_stock_lot(session, row["battery_type_id"], created_by=user.id)

    qty = row["qty"]
    if qty > 0:
        from_loc = None
        to_loc = battery_store["id"]
        move_qty = qty
    else:
        from_loc = battery_store["id"]
        to_loc = None
        move_qty = abs(qty)

    movement_id = ledger_service.move_stock(
        session,
        lot_id=lot_id,
        from_location_id=from_loc,
        to_location_id=to_loc,
        qty=move_qty,
        movement_type="ADJUST",
        reference_type="BATTERY_ADJUSTMENT",
        reference_id=adjustment_id,
        idempotency_key=idempotency_key,
        actor_id=user.id,
        reason=f"Approved adjustment: {row['reason']}",
    )

    if row["qty"] < 0:
        check_low_stock(session, row["battery_type_id"], consumed=-int(row["qty"]))

    approval_notes = payload.approval_notes.strip() if payload.approval_notes else None
    update_stmt = text(
        """
        update public.battery_adjustments
        set status = 'APPROVED',
            approved_by = :approved_by,
            approved_at = now(),
            approval_notes = :notes,
            stock_movement_id = :movement_id
        where id = :id
        returning approved_at
        """
    )
    app_res = (
        session.execute(
            update_stmt,
            {
                "id": adjustment_id,
                "approved_by": user.id,
                "notes": approval_notes,
                "movement_id": movement_id,
            },
        )
        .mappings()
        .one()
    )

    return BatteryAdjustmentOut(
        id=row["id"],
        battery_type_id=row["battery_type_id"],
        battery_type_code=row["battery_type_code"],
        battery_type_name=row["battery_type_name"],
        qty=row["qty"],
        reason=row["reason"],
        status="APPROVED",
        requested_by=row["requested_by"],
        requested_by_name=row["requested_by_name"],
        requested_at=row["requested_at"],
        approved_by=user.id,
        approved_by_name=user.full_name,
        approved_at=app_res["approved_at"],
        approval_notes=approval_notes,
    )


def reject_adjustment(
    session: Session,
    *,
    user: CurrentUser,
    adjustment_id: UUID,
    payload: BatteryAdjustmentRejectIn,
) -> BatteryAdjustmentOut:
    """Reject a battery adjustment."""
    if (
        not user.is_super_admin
        and "ADMIN" not in user.role_codes
        and "REPLACEMENT_MANAGER" not in user.role_codes
    ):
        raise PermissionDenied(
            "Only Admin or Replacement Manager may reject battery adjustments",
            code="NOT_ADJUSTMENT_APPROVER",
        )

    stmt = text(
        """
        select a.id, a.battery_type_id, bt.code as battery_type_code, bt.name as battery_type_name,
               a.qty, a.reason, a.status, a.requested_by, p_req.full_name as requested_by_name,
               a.requested_at
        from public.battery_adjustments a
        join public.battery_types bt on bt.id = a.battery_type_id
        join public.profiles p_req on p_req.id = a.requested_by
        where a.id = :id
        for update of a
        """
    )
    row = session.execute(stmt, {"id": adjustment_id}).mappings().one_or_none()
    if not row:
        raise NotFound("Adjustment not found", code="ADJUSTMENT_NOT_FOUND")

    if row["status"] != "PENDING":
        raise Conflict(
            f"Adjustment is already {row['status']}",
            code="ADJUSTMENT_NOT_PENDING",
            details={"status": row["status"]},
        )

    reason = payload.reason.strip()
    update_stmt = text(
        """
        update public.battery_adjustments
        set status = 'REJECTED',
            approved_by = :approved_by,
            approved_at = now(),
            approval_notes = :notes
        where id = :id
        returning approved_at
        """
    )
    app_res = (
        session.execute(
            update_stmt,
            {
                "id": adjustment_id,
                "approved_by": user.id,
                "notes": reason,
            },
        )
        .mappings()
        .one()
    )

    return BatteryAdjustmentOut(
        id=row["id"],
        battery_type_id=row["battery_type_id"],
        battery_type_code=row["battery_type_code"],
        battery_type_name=row["battery_type_name"],
        qty=row["qty"],
        reason=row["reason"],
        status="REJECTED",
        requested_by=row["requested_by"],
        requested_by_name=row["requested_by_name"],
        requested_at=row["requested_at"],
        approved_by=user.id,
        approved_by_name=user.full_name,
        approved_at=app_res["approved_at"],
        approval_notes=reason,
    )


def list_adjustments(session: Session, status: str | None = None) -> list[BatteryAdjustmentOut]:
    stmt = text(
        """
        select a.id, a.battery_type_id, bt.code as battery_type_code, bt.name as battery_type_name,
               a.qty, a.reason, a.status, a.requested_by, p_req.full_name as requested_by_name,
               a.requested_at, a.approved_by, p_app.full_name as approved_by_name,
               a.approved_at, a.approval_notes
        from public.battery_adjustments a
        join public.battery_types bt on bt.id = a.battery_type_id
        join public.profiles p_req on p_req.id = a.requested_by
        left join public.profiles p_app on p_app.id = a.approved_by
        where (cast(:status as text) is null or a.status = cast(:status as text))
        order by a.created_at desc
        """
    )
    rows = session.execute(stmt, {"status": status.upper() if status else None}).mappings().all()
    return [BatteryAdjustmentOut(**dict(r)) for r in rows]


def get_battery_balances(session: Session) -> list[BatteryBalanceOut]:
    """Return balance and movement summary per active battery type in BATTERY_STORE."""
    battery_store = get_battery_store_location(session)
    stmt = text(
        """
        select bt.id as battery_type_id,
               bt.code,
               bt.name,
               coalesce(bal.qty, 0) as balance,
               coalesce(rec.total_received, 0) as total_received,
               coalesce(con.total_consumed, 0) as total_consumed,
               coalesce(adj.total_adjusted, 0) as total_adjusted
        from public.battery_types bt
        left join public.stock_items si on si.item_kind = 'BATTERY' and si.battery_type_id = bt.id
        left join public.stock_lots sl
          on sl.stock_item_id = si.id and sl.condition_class = 'FUNCTIONAL_GOOD'
        left join public.stock_balances bal on bal.lot_id = sl.id and bal.location_id = :loc_id
        left join (
            select r.battery_type_id, sum(r.qty) as total_received
            from public.battery_receipts r
            group by r.battery_type_id
        ) rec on rec.battery_type_id = bt.id
        left join (
            select rec_inner.battery_type_id, sum(rec_inner.batteries_installed) as total_consumed
            from public.technician_receiving_records rec_inner
            where rec_inner.battery_check_code = 'BATTERY_REPLACED'
            group by rec_inner.battery_type_id
        ) con on con.battery_type_id = bt.id
        left join (
            select a.battery_type_id, sum(a.qty) as total_adjusted
            from public.battery_adjustments a
            where a.status = 'APPROVED'
            group by a.battery_type_id
        ) adj on adj.battery_type_id = bt.id
        where bt.is_active = true
        order by bt.code asc
        """
    )
    rows = session.execute(stmt, {"loc_id": battery_store["id"]}).mappings().all()
    return [BatteryBalanceOut(**dict(r)) for r in rows]


def list_battery_movements(session: Session) -> list[BatteryMovementOut]:
    """Return consumption and movement history for item_kind BATTERY."""
    stmt = text(
        """
        select sm.id,
               bt.id as battery_type_id,
               bt.code as battery_type_code,
               bt.name as battery_type_name,
               sm.movement_type,
               sm.qty,
               loc_from.name as from_location,
               loc_to.name as to_location,
               sm.reference_type,
               sm.reference_id,
               sm.created_at,
               p.full_name as created_by_name
        from public.stock_movements sm
        join public.stock_lots sl on sl.id = sm.lot_id
        join public.stock_items si on si.id = sl.stock_item_id
        join public.battery_types bt on bt.id = si.battery_type_id
        left join public.inventory_locations loc_from on loc_from.id = sm.from_location_id
        left join public.inventory_locations loc_to on loc_to.id = sm.to_location_id
        left join public.profiles p on p.id = sm.created_by
        where si.item_kind = 'BATTERY'
        order by sm.created_at desc
        """
    )
    rows = session.execute(stmt).mappings().all()
    return [BatteryMovementOut(**dict(r)) for r in rows]


def battery_store_balance(session: Session, battery_type_id: UUID) -> dict[str, Any] | None:
    """Current Battery Store balance (good battery lots) of one battery type."""
    store = get_battery_store_location(session)
    row = (
        session.execute(
            text(
                """
                select bt.id, bt.code, bt.name,
                       coalesce(sum(bal.qty), 0)::int as balance
                  from public.battery_types bt
                  left join public.stock_items si
                    on si.item_kind = 'BATTERY' and si.battery_type_id = bt.id
                  left join public.stock_lots sl
                    on sl.stock_item_id = si.id and sl.condition_class = 'FUNCTIONAL_GOOD'
                  left join public.stock_balances bal
                    on bal.lot_id = sl.id and bal.location_id = :loc
                 where bt.id = :bt
                 group by bt.id, bt.code, bt.name
                """
            ),
            {"loc": store["id"], "bt": battery_type_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def check_low_stock(session: Session, battery_type_id: UUID, *, consumed: int) -> bool:
    """P4-03 item 6: publish BATTERY_LOW_STOCK when a deduction of `consumed` pieces took the
    Battery Store balance from >= threshold to below it (once per crossing, not on every use).
    The threshold is the `battery_low_stock_threshold` setting (0 disables). BR-24, DEC-15."""
    raw = session.execute(
        text("select value from public.system_settings where key = :k"), {"k": LOW_STOCK_SETTING}
    ).scalar()
    try:
        threshold = int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        threshold = 0
    if threshold <= 0 or consumed <= 0:
        return False
    info = battery_store_balance(session, battery_type_id)
    if info is None:
        return False
    balance = int(info["balance"])
    if not (balance < threshold <= balance + consumed):
        return False
    notifications.publish(
        session,
        "BATTERY_LOW_STOCK",
        title=f"Battery stock low: {info['name']} ({balance} left)",
        body=(
            f"{info['code']} fell below the low-stock threshold of {threshold} piece(s) in the "
            "Battery Store. Arrange a battery receipt."
        ),
        entity_type="battery_type",
        entity_id=battery_type_id,
        data={"battery_type": str(info["code"]), "balance": balance, "threshold": threshold},
    )
    return True
