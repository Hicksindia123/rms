"""E-Commerce Returns repository (DEC-73): SQL only, no business rules. Functions take the caller's
Session (the service owns the transaction)."""

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


def options(session: Session, set_code: str) -> list[dict[str, Any]]:
    """Active items of an option set, in their configured order."""
    return _all(
        session,
        """
        select oi.code, oi.label
          from public.option_items oi
          join public.option_sets os on os.id = oi.option_set_id
         where os.code = :set_code and oi.is_active
         order by oi.sort_order, oi.label
        """,
        {"set_code": set_code},
    )


def next_return_no(session: Session, on_date: date) -> str:
    return str(
        session.execute(
            text("select rms_private.next_number('ECOM_RETURN', :d)"), {"d": on_date}
        ).scalar_one()
    )


def search_products(session: Session, q: str | None, limit: int) -> list[dict[str, Any]]:
    return _all(
        session,
        """
        select p.id, p.code, p.name
          from public.products p
          join public.product_categories pc on pc.id = p.category_id
         where p.is_active and pc.is_active
           and (cast(:q as text) is null or p.name ilike '%' || cast(:q as text) || '%'
                or p.code ilike '%' || cast(:q as text) || '%')
         order by p.name
         limit :limit
        """,
        {"q": q, "limit": limit},
    )


def get_active_product(session: Session, product_id: UUID) -> dict[str, Any] | None:
    return _one(
        session,
        "select id, code, name from public.products where id = :id and is_active",
        {"id": product_id},
    )


# --- returns -----------------------------------------------------------------------------------
_RETURN_COLUMNS = """
    r.id, r.return_no, r.entry_date, r.platform_code, r.platform_label, r.order_id,
    r.product_type_code, r.product_type_label, r.product_id,
    r.product_code_snapshot as product_code, r.product_name_snapshot as product_name,
    r.different_product_desc, r.qty, r.qc_routing_code, r.qc_routing_label, r.status,
    r.created_at, r.submitted_at, r.void_reason, r.voided_at, r.closed_at,
    cp.full_name as created_by_name
"""


def insert_return(session: Session, fields: dict[str, Any]) -> UUID:
    return cast(
        UUID,
        session.execute(
            text(
                """
                insert into public.ecommerce_returns
                  (return_no, entry_date, platform_code, platform_label, order_id,
                   product_type_code, product_type_label, product_id, product_code_snapshot,
                   product_name_snapshot, different_product_desc, qty, qc_routing_code,
                   qc_routing_label)
                values
                  (:return_no, :entry_date, :platform_code, :platform_label, :order_id,
                   :product_type_code, :product_type_label, :product_id, :product_code_snapshot,
                   :product_name_snapshot, :different_product_desc, :qty, :qc_routing_code,
                   :qc_routing_label)
                returning id
                """
            ),
            fields,
        ).scalar_one(),
    )


def get_return(
    session: Session, return_id: UUID, *, for_update: bool = False
) -> dict[str, Any] | None:
    lock = " for update of r" if for_update else ""
    return _one(
        session,
        f"""
        select {_RETURN_COLUMNS}
          from public.ecommerce_returns r
          left join public.profiles cp on cp.id = r.created_by
         where r.id = :id{lock}
        """,  # noqa: S608 - constant fragments only
        {"id": return_id},
    )


def list_returns(
    session: Session, *, q: str | None, status: str | None, limit: int
) -> list[dict[str, Any]]:
    return _all(
        session,
        f"""
        select {_RETURN_COLUMNS}
          from public.ecommerce_returns r
          left join public.profiles cp on cp.id = r.created_by
         where (cast(:status as text) is null or r.status = cast(:status as text))
           and (cast(:q as text) is null
                or r.return_no ilike '%' || cast(:q as text) || '%'
                or r.order_id ilike '%' || cast(:q as text) || '%'
                or r.platform_label ilike '%' || cast(:q as text) || '%'
                or coalesce(r.product_name_snapshot, r.different_product_desc)
                   ilike '%' || cast(:q as text) || '%')
         order by r.created_at desc
         limit :limit
        """,  # noqa: S608 - constant fragments only
        {"q": q, "status": status, "limit": limit},
    )


def returns_for_order(
    session: Session, platform_code: str, order_id: str, *, exclude_id: UUID | None = None
) -> list[dict[str, Any]]:
    return _all(
        session,
        """
        select r.id, r.return_no, r.entry_date, r.platform_label, r.status
          from public.ecommerce_returns r
         where r.platform_code = :platform and upper(r.order_id) = upper(:order_id)
           and (cast(:exclude as uuid) is null or r.id <> cast(:exclude as uuid))
         order by r.created_at desc
         limit 20
        """,
        {"platform": platform_code, "order_id": order_id, "exclude": exclude_id},
    )


def set_return_submitted(session: Session, return_id: UUID, *, status: str, by: UUID) -> None:
    session.execute(
        text(
            """
            update public.ecommerce_returns
               set status = :status, submitted_at = now(), submitted_by = :by
             where id = :id
            """
        ),
        {"id": return_id, "status": status, "by": by},
    )


def set_return_voided(session: Session, return_id: UUID, *, reason: str, by: UUID) -> None:
    session.execute(
        text(
            """
            update public.ecommerce_returns
               set status = 'VOIDED', void_reason = :reason, voided_at = now(), voided_by = :by
             where id = :id
            """
        ),
        {"id": return_id, "reason": reason, "by": by},
    )


# --- media -------------------------------------------------------------------------------------
_MEDIA_COLUMNS = (
    "m.id, m.return_id, m.kind, m.bucket, m.object_path, m.mime_type, m.size_bytes, m.file_name, "
    "m.status, m.confirmed_at, m.created_at"
)


def insert_media(session: Session, fields: dict[str, Any]) -> dict[str, Any]:
    row = session.execute(
        text(
            """
            insert into public.ecommerce_return_media
              (return_id, kind, bucket, object_path, mime_type, size_bytes, file_name)
            values (:return_id, :kind, :bucket, :object_path, :mime_type, :size_bytes, :file_name)
            returning id
            """
        ),
        fields,
    ).scalar_one()
    media = get_media(session, cast(UUID, row))
    assert media is not None  # noqa: S101 - just inserted in this transaction
    return media


def get_media(
    session: Session, media_id: UUID, *, for_update: bool = False
) -> dict[str, Any] | None:
    lock = " for update of m" if for_update else ""
    return _one(
        session,
        f"select {_MEDIA_COLUMNS} from public.ecommerce_return_media m where m.id = :id{lock}",  # noqa: S608
        {"id": media_id},
    )


def media_for_return(session: Session, return_id: UUID) -> list[dict[str, Any]]:
    return _all(
        session,
        f"""
        select {_MEDIA_COLUMNS} from public.ecommerce_return_media m
         where m.return_id = :id
         order by case m.kind when 'PACKAGE_VIDEO' then 0 else 1 end, m.created_at
        """,  # noqa: S608
        {"id": return_id},
    )


def live_image_bytes(session: Session, return_id: UUID) -> int:
    return int(
        session.execute(
            text(
                """
                select coalesce(sum(size_bytes), 0) from public.ecommerce_return_media
                 where return_id = :id and kind = 'IMAGE' and status <> 'REJECTED'
                """
            ),
            {"id": return_id},
        ).scalar_one()
    )


def set_media_status(session: Session, media_id: UUID, status: str) -> None:
    session.execute(
        text(
            """
            update public.ecommerce_return_media
               set status = :status,
                   confirmed_at = case when :status = 'CONFIRMED' then now() else null end
             where id = :id
            """
        ),
        {"id": media_id, "status": status},
    )


def stale_pending_media(
    session: Session, *, older_than_hours: int, limit: int
) -> list[dict[str, Any]]:
    return _all(
        session,
        f"""
        select {_MEDIA_COLUMNS} from public.ecommerce_return_media m
          join public.ecommerce_returns r on r.id = m.return_id
         where m.status = 'PENDING_UPLOAD' and r.status = 'DRAFT'
           and m.created_at < now() - make_interval(hours => :hours)
         order by m.created_at
         limit :limit
        """,  # noqa: S608
        {"hours": older_than_hours, "limit": limit},
    )


# --- tickets -----------------------------------------------------------------------------------
_TICKET_COLUMNS = """
    t.id, t.return_id, t.sla_due_at, t.assigned_handler_id, ah.full_name as assigned_handler_name,
    t.raised_at, t.response_code, t.response_label, t.rejection_remark, t.claim_amount,
    t.responded_at, rb.full_name as responded_by_name, t.closed_at, cb.full_name as closed_by_name
"""
_TICKET_JOINS = """
    left join public.profiles ah on ah.id = t.assigned_handler_id
    left join public.profiles rb on rb.id = t.responded_by
    left join public.profiles cb on cb.id = t.closed_by
"""


def insert_ticket(session: Session, return_id: UUID) -> None:
    # sla_due_at is computed by the DB trigger (queued time + ecommerce_ticket_sla_hours).
    session.execute(
        text("insert into public.ecommerce_tickets (return_id, sla_due_at) values (:id, now())"),
        {"id": return_id},
    )


def ticket_for_return(session: Session, return_id: UUID) -> dict[str, Any] | None:
    return _one(
        session,
        f"select {_TICKET_COLUMNS} from public.ecommerce_tickets t {_TICKET_JOINS} "  # noqa: S608
        "where t.return_id = :id",
        {"id": return_id},
    )


def tickets_for_returns(session: Session, return_ids: list[UUID]) -> list[dict[str, Any]]:
    if not return_ids:
        return []
    return _all(
        session,
        f"select {_TICKET_COLUMNS} from public.ecommerce_tickets t {_TICKET_JOINS} "  # noqa: S608
        "where t.return_id = any(:ids)",
        {"ids": return_ids},
    )


def get_ticket(
    session: Session, ticket_id: UUID, *, for_update: bool = False
) -> dict[str, Any] | None:
    if for_update:
        session.execute(
            text("select 1 from public.ecommerce_tickets where id = :id for update"),
            {"id": ticket_id},
        )
    return _one(
        session,
        f"select {_TICKET_COLUMNS} from public.ecommerce_tickets t {_TICKET_JOINS} "  # noqa: S608
        "where t.id = :id",
        {"id": ticket_id},
    )


def ticket_queue(session: Session, *, state: str, limit: int) -> list[dict[str, Any]]:
    """state: OPEN (not closed, return not voided), CLOSED, ALL. Unraised first by due time."""
    return _all(
        session,
        f"""
        select {_TICKET_COLUMNS},
               r.return_no, r.entry_date, r.platform_label, r.order_id, r.qty, r.status,
               coalesce(r.product_name_snapshot, r.different_product_desc) as product_text
          from public.ecommerce_tickets t
          join public.ecommerce_returns r on r.id = t.return_id
          {_TICKET_JOINS}
         where case cast(:state as text)
                 when 'OPEN' then t.closed_at is null and r.status <> 'VOIDED'
                 when 'CLOSED' then t.closed_at is not null
                 else true end
         order by (t.raised_at is not null), t.sla_due_at, t.created_at
         limit :limit
        """,  # noqa: S608
        {"state": state, "limit": limit},
    )


def mark_ticket_raised(session: Session, ticket_id: UUID, *, by: UUID) -> None:
    session.execute(
        text(
            """
            update public.ecommerce_tickets
               set raised_at = now(), assigned_handler_id = :by
             where id = :id
            """
        ),
        {"id": ticket_id, "by": by},
    )


def set_ticket_response(
    session: Session,
    ticket_id: UUID,
    *,
    code: str,
    label: str,
    remark: str | None,
    amount: Decimal | None,
    by: UUID,
) -> None:
    session.execute(
        text(
            """
            update public.ecommerce_tickets
               set response_code = :code, response_label = :label, rejection_remark = :remark,
                   claim_amount = :amount, responded_at = now(), responded_by = :by
             where id = :id
            """
        ),
        {
            "id": ticket_id,
            "code": code,
            "label": label,
            "remark": remark,
            "amount": amount,
            "by": by,
        },
    )


def close_ticket(session: Session, ticket_id: UUID, *, by: UUID) -> None:
    session.execute(
        text(
            "update public.ecommerce_tickets set closed_at = now(), closed_by = :by where id = :id"
        ),
        {"id": ticket_id, "by": by},
    )


# --- history -----------------------------------------------------------------------------------
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


def events_for_return(session: Session, return_id: UUID) -> list[dict[str, Any]]:
    return _all(
        session,
        """
        select e.event_code, e.from_status, e.to_status, e.details, p.full_name as actor_name,
               e.created_at
          from public.ecommerce_return_events e
          left join public.profiles p on p.id = e.actor_id
         where e.return_id = :id
         order by e.created_at, e.id
        """,
        {"id": return_id},
    )
