"""E-Commerce settlement repository (DEC-76): SQL only, no business rules. Functions take the
caller's Session (the service owns the transaction). Stock movements are NOT written here: they go
through rms_private.rms_move_stock via the inventory ledger service (rule f)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def _one(session: Session, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
    row = session.execute(text(sql), params).mappings().first()
    return dict(row) if row else None


def _all(session: Session, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [dict(r) for r in session.execute(text(sql), params or {}).mappings()]


# --- configuration -----------------------------------------------------------------------------
def get_setting(session: Session, key: str) -> Any:
    return session.execute(
        text("select value from public.system_settings where key = :key"), {"key": key}
    ).scalar()


def business_today(session: Session) -> date:
    return cast(date, session.execute(text("select rms_private.business_today()")).scalar_one())


def options(
    session: Session, set_code: str, *, include_inactive: bool = False
) -> list[dict[str, Any]]:
    return _all(
        session,
        """
        select oi.code, oi.label
          from public.option_items oi
          join public.option_sets os on os.id = oi.option_set_id
         where os.code = :set_code and (oi.is_active or :all)
         order by oi.sort_order, oi.label
        """,
        {"set_code": set_code, "all": include_inactive},
    )


def locations_by_codes(session: Session, codes: list[str]) -> list[dict[str, Any]]:
    if not codes:
        return []
    return _all(
        session,
        """
        select l.id, l.code, l.name, l.location_class, l.is_active
          from public.inventory_locations l
         where l.code = any(:codes)
        """,
        {"codes": codes},
    )


def next_sheet_no(session: Session, on_date: date) -> str:
    return str(
        session.execute(
            text("select rms_private.next_number('ECOM_ACTION_SHEET', :d)"), {"d": on_date}
        ).scalar_one()
    )


# --- stores ------------------------------------------------------------------------------------
def store_for_product(session: Session, product_id: UUID) -> dict[str, Any] | None:
    return _one(
        session,
        """
        select s.id, s.name, s.location_id
          from public.intermediate_stores s
         where s.id = rms_private.store_for_product(:pid)
        """,
        {"pid": product_id},
    )


def user_store_ids(session: Session, user_id: UUID) -> set[UUID]:
    rows = session.execute(
        text("select id from rms_private.user_store_ids(:uid) as id"), {"uid": user_id}
    ).scalars()
    return {cast(UUID, r) for r in rows}


def user_acts_for_store(session: Session, user_id: UUID, store_id: UUID) -> bool:
    return bool(
        session.execute(
            text("select rms_private.user_acts_for_store(:uid, :sid)"),
            {"uid": user_id, "sid": store_id},
        ).scalar()
    )


# --- returns -----------------------------------------------------------------------------------
_PRODUCT_TEXT = """
    case when r.product_id is not null
         then r.product_name_snapshot || ' (' || r.product_code_snapshot || ')'
         else r.different_product_desc end
"""


def unboxing_rows(session: Session, *, limit: int) -> list[dict[str, Any]]:
    return _all(
        session,
        f"""
        select r.id as return_id, r.return_no, r.entry_date, r.platform_code, r.platform_label,
               r.order_id, {_PRODUCT_TEXT} as product_text,
               r.product_id is not null as is_company_product,
               r.qty, r.qc_routing_label, r.resolution_code, r.resolution_label, r.resolution_qty,
               r.resolution_note, r.resolved_at,
               (select s.name from public.intermediate_stores s
                 where r.product_id is not null
                   and s.id = rms_private.store_for_product(r.product_id))
                 as store_name
          from public.ecommerce_returns r
         where r.status = 'PENDING_UNBOXING'
         order by r.platform_label, r.entry_date, r.resolved_at
         limit :limit
        """,  # noqa: S608 - constant fragments only
        {"limit": limit},
    )


def lock_returns(session: Session, ids: list[UUID]) -> list[dict[str, Any]]:
    return _all(
        session,
        """
        select r.id, r.return_no, r.status, r.platform_code, r.product_id, r.qty,
               r.resolution_code, r.resolution_qty, r.action_sheet_id
          from public.ecommerce_returns r
         where r.id = any(:ids)
         order by r.id
           for update
        """,
        {"ids": ids},
    )


def get_return_brief(
    session: Session, return_id: UUID, *, for_update: bool = False
) -> dict[str, Any] | None:
    lock = " for update" if for_update else ""
    return _one(
        session,
        f"""
        select r.id, r.return_no, r.status, r.platform_code, r.product_id, r.qty, r.good_qty,
               r.repair_qty, r.action_sheet_id
          from public.ecommerce_returns r
         where r.id = :id{lock}
        """,  # noqa: S608 - constant fragments only
        {"id": return_id},
    )


def set_return_unboxed(session: Session, return_id: UUID, fields: dict[str, Any]) -> None:
    session.execute(
        text(
            """
            update public.ecommerce_returns
               set status = 'UNBOXED', action_sheet_id = :sheet_id, good_qty = :good_qty,
                   repair_qty = :repair_qty, wastage_qty = :wastage_qty, cn_qty = :cn_qty,
                   repair_location_id = :repair_location_id, unbox_note = :note,
                   unboxed_at = now(), unboxed_by = :by
             where id = :id
            """
        ),
        {"id": return_id, **fields},
    )


def return_settled(session: Session, return_id: UUID) -> bool:
    return bool(
        session.execute(
            text("select rms_private.ecom_return_settled(:id)"), {"id": return_id}
        ).scalar()
    )


def close_return(session: Session, return_id: UUID) -> None:
    session.execute(
        text(
            "update public.ecommerce_returns set status = 'CLOSED', closed_at = now() "
            "where id = :id"
        ),
        {"id": return_id},
    )


def insert_event(
    session: Session,
    return_id: UUID,
    event_code: str,
    *,
    from_status: str | None,
    to_status: str | None,
    details: dict[str, Any] | None = None,
) -> None:
    session.execute(
        text(
            """
            insert into public.ecommerce_return_events
              (return_id, event_code, from_status, to_status, details, created_at)
            values (:id, :code, :from_status, :to_status, cast(:details as jsonb),
                    clock_timestamp())
            """
        ),
        {
            "id": return_id,
            "code": event_code,
            "from_status": from_status,
            "to_status": to_status,
            "details": json.dumps(details or {}, default=str),
        },
    )


# --- action sheets -----------------------------------------------------------------------------
def insert_sheet(
    session: Session, *, sheet_no: str, platform_code: str, platform_label: str
) -> UUID:
    return cast(
        UUID,
        session.execute(
            text(
                """
                insert into public.ecommerce_action_sheets (sheet_no, platform_code, platform_label)
                values (:no, :code, :label)
                returning id
                """
            ),
            {"no": sheet_no, "code": platform_code, "label": platform_label},
        ).scalar_one(),
    )


_SHEET_COLUMNS = """
    s.id, s.sheet_no, s.platform_code, s.platform_label, s.status, s.cn_no, s.cn_date, s.cn_value,
    s.remarks, s.created_at, s.completed_at,
    cb.full_name as created_by_name, kb.full_name as completed_by_name,
    (select count(*) from public.ecommerce_returns r where r.action_sheet_id = s.id) as orders,
    (select coalesce(sum(r.qty), 0) from public.ecommerce_returns r where r.action_sheet_id = s.id)
      as total_received,
    (select coalesce(sum(r.cn_qty), 0) from public.ecommerce_returns r
      where r.action_sheet_id = s.id)
      as total_cn_qty
"""
_SHEET_JOINS = """
    left join public.profiles cb on cb.id = s.created_by
    left join public.profiles kb on kb.id = s.completed_by
"""


def get_sheet(
    session: Session, sheet_id: UUID, *, for_update: bool = False
) -> dict[str, Any] | None:
    if for_update:
        session.execute(
            text("select 1 from public.ecommerce_action_sheets where id = :id for update"),
            {"id": sheet_id},
        )
    return _one(
        session,
        f"select {_SHEET_COLUMNS} from public.ecommerce_action_sheets s "  # noqa: S608
        f"{_SHEET_JOINS} where s.id = :id",
        {"id": sheet_id},
    )


def list_sheets(session: Session, *, status: str | None, limit: int) -> list[dict[str, Any]]:
    return _all(
        session,
        f"""
        select {_SHEET_COLUMNS}
          from public.ecommerce_action_sheets s {_SHEET_JOINS}
         where cast(:status as text) is null or s.status = cast(:status as text)
         order by case s.status when 'PENDING_ACCOUNTS' then 0 else 1 end, s.created_at desc
         limit :limit
        """,  # noqa: S608 - constant fragments only
        {"status": status, "limit": limit},
    )


def sheet_lines(session: Session, sheet_id: UUID) -> list[dict[str, Any]]:
    return _all(
        session,
        f"""
        select r.id as return_id, r.return_no, r.entry_date, r.order_id,
               {_PRODUCT_TEXT} as product_text,
               r.qty as qty_received, r.resolution_code, r.resolution_label, r.resolution_qty,
               r.cn_qty, r.good_qty, r.repair_qty, r.wastage_qty, r.status
          from public.ecommerce_returns r
         where r.action_sheet_id = :id
         order by r.entry_date, r.order_id, r.return_no
        """,  # noqa: S608 - constant fragments only
        {"id": sheet_id},
    )


def sheet_return_ids(session: Session, sheet_id: UUID) -> list[UUID]:
    return [
        cast(UUID, r)
        for r in session.execute(
            text("select id from public.ecommerce_returns where action_sheet_id = :id order by id"),
            {"id": sheet_id},
        ).scalars()
    ]


def complete_sheet(
    session: Session,
    sheet_id: UUID,
    *,
    cn_no: str | None,
    cn_date: date | None,
    cn_value: Decimal | None,
    remarks: str | None,
    by: UUID,
) -> None:
    session.execute(
        text(
            """
            update public.ecommerce_action_sheets
               set status = 'COMPLETED', cn_no = :cn_no, cn_date = :cn_date, cn_value = :cn_value,
                   remarks = :remarks, completed_at = now(), completed_by = :by
             where id = :id
            """
        ),
        {
            "id": sheet_id,
            "cn_no": cn_no,
            "cn_date": cn_date,
            "cn_value": cn_value,
            "remarks": remarks,
            "by": by,
        },
    )


# --- repairs -----------------------------------------------------------------------------------
def insert_repair(
    session: Session, *, return_id: UUID, location_id: UUID, lot_id: UUID, qty: int
) -> UUID:
    return cast(
        UUID,
        session.execute(
            text(
                """
                insert into public.ecommerce_repairs (return_id, location_id, lot_id, qty_sent)
                values (:rid, :loc, :lot, :qty)
                returning id
                """
            ),
            {"rid": return_id, "loc": location_id, "lot": lot_id, "qty": qty},
        ).scalar_one(),
    )


def open_repairs(session: Session, *, limit: int) -> list[dict[str, Any]]:
    return _all(
        session,
        f"""
        select p.id as repair_id, r.id as return_id, r.return_no, r.platform_label, r.order_id,
               {_PRODUCT_TEXT} as product_text, l.name as location_name, p.qty_sent,
               p.created_at as sent_at
          from public.ecommerce_repairs p
          join public.ecommerce_returns r on r.id = p.return_id
          join public.inventory_locations l on l.id = p.location_id
         where p.status = 'AT_DEPARTMENT'
         order by p.created_at
         limit :limit
        """,  # noqa: S608 - constant fragments only
        {"limit": limit},
    )


def get_repair(
    session: Session, repair_id: UUID, *, for_update: bool = False
) -> dict[str, Any] | None:
    lock = " for update" if for_update else ""
    return _one(
        session,
        f"""
        select p.id, p.return_id, p.location_id, p.lot_id, p.qty_sent, p.status
          from public.ecommerce_repairs p
         where p.id = :id{lock}
        """,  # noqa: S608 - constant fragments only
        {"id": repair_id},
    )


def set_repair_returned(
    session: Session, repair_id: UUID, *, qty_ok: int, qty_scrap: int, note: str | None, by: UUID
) -> None:
    session.execute(
        text(
            """
            update public.ecommerce_repairs
               set status = 'RETURNED', qty_ok = :ok, qty_scrap = :scrap, return_note = :note,
                   returned_at = now(), returned_by = :by
             where id = :id
            """
        ),
        {"id": repair_id, "ok": qty_ok, "scrap": qty_scrap, "note": note, "by": by},
    )


# --- store receipts ----------------------------------------------------------------------------
def insert_receipt(
    session: Session,
    *,
    return_id: UUID,
    source: str,
    store_id: UUID,
    lot_id: UUID,
    from_location_id: UUID,
    qty: int,
) -> UUID:
    return cast(
        UUID,
        session.execute(
            text(
                """
                insert into public.ecommerce_store_receipts
                  (return_id, source, store_id, lot_id, from_location_id, qty)
                values (:rid, :src, :store, :lot, :loc, :qty)
                returning id
                """
            ),
            {
                "rid": return_id,
                "src": source,
                "store": store_id,
                "lot": lot_id,
                "loc": from_location_id,
                "qty": qty,
            },
        ).scalar_one(),
    )


_RECEIPT_COLUMNS = """
    x.id, x.return_id, r.return_no, r.platform_label, r.order_id,
    r.product_code_snapshot as product_code, r.product_name_snapshot as product_name,
    x.source, x.store_id, st.name as store_name, st.location_id as store_location_id,
    fl.name as from_location_name, x.from_location_id, x.lot_id, x.qty, x.status, x.created_at,
    x.acknowledged_at, ab.full_name as acknowledged_by_name
"""
_RECEIPT_JOINS = """
    join public.ecommerce_returns r on r.id = x.return_id
    join public.intermediate_stores st on st.id = x.store_id
    join public.inventory_locations fl on fl.id = x.from_location_id
    left join public.profiles ab on ab.id = x.acknowledged_by
"""


def list_receipts(
    session: Session, *, state: str, store_ids: set[UUID] | None, limit: int
) -> list[dict[str, Any]]:
    return _all(
        session,
        f"""
        select {_RECEIPT_COLUMNS}
          from public.ecommerce_store_receipts x {_RECEIPT_JOINS}
         where (cast(:state as text) = 'ALL' or x.status = cast(:state as text))
           and (cast(:all_stores as boolean) or x.store_id = any(:store_ids))
         order by x.status desc, x.created_at
         limit :limit
        """,  # noqa: S608 - constant fragments only
        {
            "state": state,
            "all_stores": store_ids is None,
            "store_ids": list(store_ids or []),
            "limit": limit,
        },
    )


def lock_receipts(session: Session, ids: list[UUID]) -> list[dict[str, Any]]:
    session.execute(
        text(
            "select 1 from public.ecommerce_store_receipts where id = any(:ids) "
            "order by id for update"
        ),
        {"ids": ids},
    )
    return _all(
        session,
        f"select {_RECEIPT_COLUMNS} from public.ecommerce_store_receipts x {_RECEIPT_JOINS} "  # noqa: S608
        "where x.id = any(:ids) order by x.created_at, x.id",
        {"ids": ids},
    )


def acknowledge_receipt(session: Session, receipt_id: UUID, *, movement_id: UUID, by: UUID) -> None:
    session.execute(
        text(
            """
            update public.ecommerce_store_receipts
               set status = 'ACKNOWLEDGED', movement_id = :mid, acknowledged_at = now(),
                   acknowledged_by = :by
             where id = :id
            """
        ),
        {"id": receipt_id, "mid": movement_id, "by": by},
    )


# --- per-return read ---------------------------------------------------------------------------
def return_settlement(session: Session, return_id: UUID) -> dict[str, Any] | None:
    return _one(
        session,
        """
        select r.action_sheet_id, s.sheet_no, s.status as sheet_status, r.good_qty, r.repair_qty,
               r.wastage_qty, r.cn_qty, r.unbox_note, r.unboxed_at, ub.full_name as unboxed_by_name,
               rl.name as repair_location_name
          from public.ecommerce_returns r
          join public.ecommerce_action_sheets s on s.id = r.action_sheet_id
          left join public.profiles ub on ub.id = r.unboxed_by
          left join public.inventory_locations rl on rl.id = r.repair_location_id
         where r.id = :id
        """,
        {"id": return_id},
    )


def repair_for_return(session: Session, return_id: UUID) -> dict[str, Any] | None:
    return _one(
        session,
        """
        select p.id, l.name as location_name, p.status, p.qty_sent, p.qty_ok, p.qty_scrap,
               p.return_note, p.returned_at, rb.full_name as returned_by_name
          from public.ecommerce_repairs p
          join public.inventory_locations l on l.id = p.location_id
          left join public.profiles rb on rb.id = p.returned_by
         where p.return_id = :id
        """,
        {"id": return_id},
    )


def receipts_for_return(session: Session, return_id: UUID) -> list[dict[str, Any]]:
    return _all(
        session,
        """
        select x.id, x.source, st.name as store_name, x.qty, x.status, x.acknowledged_at,
               ab.full_name as acknowledged_by_name
          from public.ecommerce_store_receipts x
          join public.intermediate_stores st on st.id = x.store_id
          left join public.profiles ab on ab.id = x.acknowledged_by
         where x.return_id = :id
         order by x.created_at
        """,
        {"id": return_id},
    )
