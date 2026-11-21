"""Transfer slip SQL (Phase P5, DEC-65). SQL only, no business rules."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

TEMPLATE_CODE = "TRANSFER_SLIP"
NUMBER_SERIES = "TRANSFER_SLIP"
STAGING = "INWARD_STAGING"
LIVE = ("GENERATED", "ACKNOWLEDGED")


def _ids(values: Sequence[UUID]) -> list[str]:
    return [str(v) for v in values]


def _rows(session: Session, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(r) for r in session.execute(text(sql), params).mappings().all()]


def _row(session: Session, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
    row = session.execute(text(sql), params).mappings().first()
    return dict(row) if row else None


# --- settings / numbering / template ---------------------------------------------------------
def get_setting(session: Session, key: str) -> Any:
    return session.execute(
        text("select value from public.system_settings where key = :key"), {"key": key}
    ).scalar()


def next_slip_no(session: Session, on_date: date, store_code: str) -> str:
    return str(
        session.execute(
            text("select rms_private.next_number(:code, :d, :scope)"),
            {"code": NUMBER_SERIES, "d": on_date, "scope": store_code},
        ).scalar_one()
    )


def published_template(session: Session) -> dict[str, Any] | None:
    return _row(
        session,
        """
        select code, name, version_no, coalesce(snapshot, layout) as layout
          from public.print_templates
         where code = :code and status = 'PUBLISHED'
        """,
        {"code": TEMPLATE_CODE},
    )


# --- goods slips pending a transfer slip -----------------------------------------------------
_GS_HEADER = """
    select g.id as gs_id, g.gs_no, g.status, g.category_code, g.party_id,
           pa.name as party_name, st.name as station_name, sn.name as state_name,
           coalesce(g.carton_count, g.box_count) as cartons,
           coalesce(g.gate_entry_date, (g.created_at at time zone :tz)::date) as received_date,
           g.categorisation_locked_at as locked_at
      from public.goods_slips g
      left join public.parties pa on pa.id = g.party_id
      left join public.stations st on st.id = g.station_id
      left join public.states sn on sn.id = g.state_id
"""


def pending_goods_slips(
    session: Session,
    *,
    tz: str,
    party_id: UUID | None,
    date_from: date | None,
    date_to: date | None,
    store_id: UUID | None,
) -> list[dict[str, Any]]:
    return _rows(
        session,
        _GS_HEADER  # noqa: S608 - constant SQL fragments, values are bound
        + """
     where g.status = 'PENDING_TRANSFER_SLIP'
       and (cast(:party as uuid) is null or g.party_id = cast(:party as uuid))
       and (cast(:dfrom as date) is null
            or (g.categorisation_locked_at at time zone :tz)::date >= cast(:dfrom as date))
       and (cast(:dto as date) is null
            or (g.categorisation_locked_at at time zone :tz)::date <= cast(:dto as date))
       and (cast(:store as uuid) is null or exists (
             select 1 from public.gs_items gi
              where gi.gs_id = g.id and gi.removed_at is null and gi.received_qty > 0
                and rms_private.store_for_product(gi.product_id) = cast(:store as uuid)))
     order by g.categorisation_locked_at nulls last, g.gs_no
        """,
        {
            "tz": tz,
            "party": str(party_id) if party_id else None,
            "dfrom": date_from,
            "dto": date_to,
            "store": str(store_id) if store_id else None,
        },
    )


def goods_slip_headers(
    session: Session, gs_ids: Sequence[UUID], *, tz: str
) -> list[dict[str, Any]]:
    if not gs_ids:
        return []
    return _rows(
        session,
        _GS_HEADER + " where g.id = any(cast(:ids as uuid[])) order by g.gs_no",
        {"ids": _ids(gs_ids), "tz": tz},
    )


def physical_items(session: Session, gs_ids: Sequence[UUID]) -> list[dict[str, Any]]:
    """Live lines (not removed) of the GSs, with the product's current store (DEC-61)."""
    if not gs_ids:
        return []
    return _rows(
        session,
        """
        select gi.id, gi.gs_id, gi.line_no, gi.product_id, gi.documented_qty, gi.received_qty,
               coalesce(gi.product_code_snapshot, p.code) as product_code,
               coalesce(gi.product_name_snapshot, p.name) as product_name,
               s.id as store_id, s.code as store_code, s.name as store_name,
               s.sort_order as store_sort
          from public.gs_items gi
          join public.products p on p.id = gi.product_id
          left join public.intermediate_stores s
                 on s.id = rms_private.store_for_product(gi.product_id)
         where gi.gs_id = any(cast(:ids as uuid[])) and gi.removed_at is null
         order by gi.gs_id, gi.line_no
        """,
        {"ids": _ids(gs_ids)},
    )


def buckets_for_items(session: Session, item_ids: Sequence[UUID]) -> list[dict[str, Any]]:
    if not item_ids:
        return []
    return _rows(
        session,
        """
        select b.gs_item_id, b.field_id, b.field_code, b.label_snapshot, b.qty,
               coalesce(l.sort_order, 0) as sort_order
          from public.gs_item_buckets b
          left join public.item_field_library l on l.id = b.field_id
         where b.gs_item_id = any(cast(:ids as uuid[])) and b.qty > 0
         order by b.gs_item_id, coalesce(l.sort_order, 0), b.field_code
        """,
        {"ids": _ids(item_ids)},
    )


def live_coverage(session: Session, item_ids: Sequence[UUID]) -> list[dict[str, Any]]:
    """Items already on a live slip (relevant lines), with that slip's store."""
    if not item_ids:
        return []
    return _rows(
        session,
        """
        select distinct l.gs_item_id, s.id as slip_id, s.slip_no, s.store_id,
               s.store_name_snapshot as store_name
          from public.transfer_slip_lines l
          join public.transfer_slips s on s.id = l.slip_id
         where l.gs_item_id = any(cast(:ids as uuid[])) and l.is_relevant
           and s.status in ('GENERATED', 'ACKNOWLEDGED')
        """,
        {"ids": _ids(item_ids)},
    )


def staging_lots(session: Session, item_ids: Sequence[UUID]) -> list[dict[str, Any]]:
    """Lots of the item lines with a positive balance in Inward Staging (booked at the lock)."""
    if not item_ids:
        return []
    return _rows(
        session,
        """
        select lot.id as lot_id, lot.gs_item_id, b.qty
          from public.stock_lots lot
          join public.stock_balances b on b.lot_id = lot.id
          join public.inventory_locations loc on loc.id = b.location_id and loc.code = :staging
         where lot.gs_item_id = any(cast(:ids as uuid[])) and b.qty > 0
         order by lot.gs_item_id, lot.created_at
        """,
        {"ids": _ids(item_ids), "staging": STAGING},
    )


def open_edit_requests(session: Session, gs_ids: Sequence[UUID]) -> list[dict[str, Any]]:
    if not gs_ids:
        return []
    return _rows(
        session,
        _REQUEST_SELECT + " where r.gs_id = any(cast(:ids as uuid[])) and r.status = 'OPEN'",
        {"ids": _ids(gs_ids)},
    )


# --- stores ----------------------------------------------------------------------------------
def stores_by_ids(session: Session, store_ids: Sequence[UUID]) -> list[dict[str, Any]]:
    if not store_ids:
        return []
    return _rows(
        session,
        """
        select s.id, s.code, s.name, s.sort_order, s.is_active, s.location_id,
               l.code as location_code, r.code as role_code
          from public.intermediate_stores s
          join public.inventory_locations l on l.id = s.location_id
          join public.roles r on r.id = s.role_id
         where s.id = any(cast(:ids as uuid[]))
         order by s.sort_order, s.code
        """,
        {"ids": _ids(store_ids)},
    )


# --- slips -----------------------------------------------------------------------------------
def insert_slip(
    session: Session,
    *,
    slip_no: str,
    store_id: UUID,
    custody_transfer_id: UUID,
    relevant_qty: int,
    grand_total_qty: int,
    template_version_no: int,
    content: dict[str, Any],
) -> UUID:
    return UUID(
        str(
            session.execute(
                text(
                    """
                    insert into public.transfer_slips
                      (slip_no, store_id, store_code_snapshot, store_name_snapshot,
                       custody_transfer_id, relevant_qty, grand_total_qty, template_version_no,
                       content)
                    values (:no, :store, '', '', :ct, :rel, :grand, :tv, :content)
                    returning id
                    """
                ).bindparams(bindparam("content", type_=JSONB)),
                {
                    "no": slip_no,
                    "store": store_id,
                    "ct": custody_transfer_id,
                    "rel": relevant_qty,
                    "grand": grand_total_qty,
                    "tv": template_version_no,
                    "content": content,
                },
            ).scalar_one()
        )
    )


def insert_slip_gs(
    session: Session, *, slip_id: UUID, gs: dict[str, Any], relevant_qty: int, total_qty: int
) -> None:
    session.execute(
        text(
            """
            insert into public.transfer_slip_gs
              (slip_id, gs_id, gs_no_snapshot, party_name_snapshot, station_name_snapshot,
               state_name_snapshot, cartons, received_date, relevant_qty, total_qty)
            values (:slip, :gs, '', :party, :station, :state, :cartons, :received, :rel, :total)
            """
        ),
        {
            "slip": slip_id,
            "gs": gs["gs_id"],
            "party": gs.get("party_name"),
            "station": gs.get("station_name"),
            "state": gs.get("state_name"),
            "cartons": gs.get("cartons"),
            "received": gs.get("received_date"),
            "rel": relevant_qty,
            "total": total_qty,
        },
    )


def insert_slip_line(session: Session, *, slip_id: UUID, line: dict[str, Any]) -> None:
    session.execute(
        text(
            """
            insert into public.transfer_slip_lines
              (slip_id, gs_id, gs_item_id, line_no_snapshot, product_id, product_code_snapshot,
               product_name_snapshot, bucket_field_id, bucket_code_snapshot, bucket_label_snapshot,
               qty, is_relevant, belongs_store_id, belongs_store_name_snapshot)
            values (:slip, :gs, :item, :line_no, :product, :pcode, :pname, :bfield, :bcode,
                    :blabel, :qty, :relevant, :store, :store_name)
            """
        ),
        {"slip": slip_id, **line},
    )


_SLIP_SELECT = """
    select s.id, s.slip_no, s.store_id, s.store_code_snapshot as store_code,
           s.store_name_snapshot as store_name, s.custody_transfer_id, s.status,
           s.relevant_qty, s.grand_total_qty, s.template_version_no, s.content,
           s.generated_by, gp.full_name as generated_by_name, s.generated_at,
           s.acknowledged_at, ap.full_name as acknowledged_by_name,
           s.voided_at, s.void_reason,
           (select count(*) from public.transfer_slip_gs g where g.slip_id = s.id) as gs_count,
           coalesce((select array_agg(g.gs_no_snapshot order by g.gs_no_snapshot)
                       from public.transfer_slip_gs g where g.slip_id = s.id), '{}') as gs_nos
      from public.transfer_slips s
      left join public.profiles gp on gp.id = s.generated_by
      left join public.profiles ap on ap.id = s.acknowledged_by
"""


def get_slip(session: Session, slip_id: UUID, *, for_update: bool = False) -> dict[str, Any] | None:
    lock = " for update of s" if for_update else ""
    return _row(session, _SLIP_SELECT + " where s.id = :id" + lock, {"id": slip_id})


def slips_by_ids(session: Session, slip_ids: Sequence[UUID]) -> list[dict[str, Any]]:
    if not slip_ids:
        return []
    return _rows(
        session,
        _SLIP_SELECT + " where s.id = any(cast(:ids as uuid[])) order by s.store_code_snapshot",
        {"ids": _ids(slip_ids)},
    )


def list_slips(
    session: Session,
    *,
    status: str | None,
    store_id: UUID | None,
    gs_no: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    where = """
     where (cast(:status as text) is null or s.status = cast(:status as text))
       and (cast(:store as uuid) is null or s.store_id = cast(:store as uuid))
       and (cast(:gs as text) is null or s.slip_no ilike '%' || cast(:gs as text) || '%'
            or exists (select 1 from public.transfer_slip_gs g
                        where g.slip_id = s.id
                          and g.gs_no_snapshot ilike '%' || cast(:gs as text) || '%'))
    """
    params = {
        "status": status,
        "store": str(store_id) if store_id else None,
        "gs": gs_no,
        "limit": limit,
        "offset": offset,
    }
    total = int(
        session.execute(
            text("select count(*) from public.transfer_slips s" + where),  # noqa: S608
            params,
        ).scalar_one()
    )
    rows = _rows(
        session,
        _SLIP_SELECT
        + where
        + " order by s.generated_at desc, s.slip_no limit :limit offset :offset",
        params,
    )
    return rows, total


def slip_goods_slips(session: Session, slip_id: UUID) -> list[dict[str, Any]]:
    return _rows(
        session,
        """
        select gs_id, gs_no_snapshot as gs_no, party_name_snapshot as party_name,
               station_name_snapshot as station_name, state_name_snapshot as state_name,
               cartons, received_date, relevant_qty, total_qty
          from public.transfer_slip_gs
         where slip_id = :id
         order by gs_no_snapshot
        """,
        {"id": slip_id},
    )


def slip_lines(session: Session, slip_id: UUID) -> list[dict[str, Any]]:
    return _rows(
        session,
        """
        select l.id, l.gs_id, l.gs_item_id, l.line_no_snapshot as line_no,
               l.product_code_snapshot as product_code, l.product_name_snapshot as product_name,
               l.bucket_label_snapshot as bucket_label, l.qty, l.is_relevant,
               l.belongs_store_name_snapshot as belongs_store_name
          from public.transfer_slip_lines l
          left join public.item_field_library f on f.id = l.bucket_field_id
         where l.slip_id = :id
         order by l.is_relevant desc, l.gs_id, l.line_no_snapshot, coalesce(f.sort_order, 0),
                  l.bucket_code_snapshot
        """,
        {"id": slip_id},
    )


def live_slip_ids_for_gs(session: Session, gs_id: UUID) -> list[UUID]:
    rows = session.execute(
        text(
            """
            select s.id
              from public.transfer_slips s
              join public.transfer_slip_gs g on g.slip_id = s.id
             where g.gs_id = :gs and s.status in ('GENERATED', 'ACKNOWLEDGED')
             order by s.slip_no
               for update of s
            """
        ),
        {"gs": gs_id},
    ).scalars()
    return [UUID(str(r)) for r in rows]


def slips_for_gs(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    return _rows(
        session,
        _SLIP_SELECT  # noqa: S608 - constant SQL fragments, values are bound
        + """
         where exists (select 1 from public.transfer_slip_gs g
                        where g.slip_id = s.id and g.gs_id = :gs)
         order by s.generated_at desc, s.slip_no
        """,
        {"gs": gs_id},
    )


def gs_ids_on_slip(session: Session, slip_id: UUID) -> list[UUID]:
    rows = session.execute(
        text("select gs_id from public.transfer_slip_gs where slip_id = :id order by gs_id"),
        {"id": slip_id},
    ).scalars()
    return [UUID(str(r)) for r in rows]


def set_voided(session: Session, slip_id: UUID, *, by: UUID, reason: str) -> None:
    session.execute(
        text(
            """
            update public.transfer_slips
               set status = 'VOIDED', voided_by = :by, voided_at = now(), void_reason = :reason
             where id = :id
            """
        ),
        {"id": slip_id, "by": by, "reason": reason},
    )


def gaps(session: Session, gs_id: UUID) -> int:
    return int(
        session.execute(
            text("select rms_private.gs_transfer_slip_gaps(:gs)"), {"gs": gs_id}
        ).scalar_one()
    )


# --- edit requests ---------------------------------------------------------------------------
_REQUEST_SELECT = """
    select r.id, r.gs_id, g.gs_no, pa.name as party_name, r.reason, r.status,
           r.requested_by, rq.full_name as requested_by_name, r.requested_at,
           rs.full_name as resolved_by_name, r.resolved_at, r.resolution_note
      from public.gs_edit_requests r
      join public.goods_slips g on g.id = r.gs_id
      left join public.parties pa on pa.id = g.party_id
      left join public.profiles rq on rq.id = r.requested_by
      left join public.profiles rs on rs.id = r.resolved_by
"""


def insert_edit_request(session: Session, *, gs_id: UUID, reason: str) -> UUID:
    return UUID(
        str(
            session.execute(
                text(
                    "insert into public.gs_edit_requests (gs_id, reason) values (:gs, :reason) "
                    "returning id"
                ),
                {"gs": gs_id, "reason": reason},
            ).scalar_one()
        )
    )


def get_edit_request(
    session: Session, request_id: UUID, *, for_update: bool = False
) -> dict[str, Any] | None:
    lock = " for update of r" if for_update else ""
    return _row(session, _REQUEST_SELECT + " where r.id = :id" + lock, {"id": request_id})


def edit_requests(session: Session, *, status: str | None) -> list[dict[str, Any]]:
    return _rows(
        session,
        _REQUEST_SELECT
        + """
         where (cast(:status as text) is null or r.status = cast(:status as text))
         order by r.requested_at desc
         limit 500
        """,
        {"status": status},
    )


def edit_requests_for_gs(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    return _rows(
        session,
        _REQUEST_SELECT + " where r.gs_id = :gs order by r.requested_at desc",
        {"gs": gs_id},
    )


def resolve_edit_request(
    session: Session, request_id: UUID, *, status: str, by: UUID, note: str | None
) -> None:
    session.execute(
        text(
            """
            update public.gs_edit_requests
               set status = :status, resolved_by = :by, resolved_at = now(),
                   resolution_note = :note
             where id = :id
            """
        ),
        {"id": request_id, "status": status, "by": by, "note": note},
    )


def edited_since(session: Session, gs_id: UUID, since: Any) -> bool:
    """A post-lock edit (DEC-64 d revision LOCKED_*) was recorded after the request."""
    return bool(
        session.execute(
            text(
                """
                select exists (select 1 from public.rm_review_revisions v
                                where v.gs_id = :gs and v.action like 'LOCKED\\_%'
                                  and v.created_at >= :since)
                """
            ),
            {"gs": gs_id, "since": since},
        ).scalar_one()
    )


def super_admin_ids(session: Session) -> list[UUID]:
    rows = session.execute(
        text("select id from public.profiles where is_super_admin and is_active order by id")
    ).scalars()
    return [UUID(str(r)) for r in rows]
