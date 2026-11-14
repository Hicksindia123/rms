"""Database access layer for Department Routing, Receiving and G-20 Reconciliation.
(Change plan 2026-11-12 Phase 6; AMD-10, AMD-14, AMD-15; DEC-42, DEC-43; Guard G-20).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def list_outcome_heads(session: Session, *, active_only: bool = True) -> list[dict[str, Any]]:
    stmt = text(
        """
        select id, code, label, is_wastage, returns_to_routing, sort_order, is_active
          from public.department_outcome_heads
         where (not :active_only or is_active)
         order by sort_order asc, label asc
        """
    )
    rows = session.execute(stmt, {"active_only": active_only}).mappings().all()
    return [dict(r) for r in rows]


# --- Command helpers (SQL only; business rules live in the service) -------------------------------


def get_setting(session: Session, key: str) -> Any:
    return session.execute(
        text("select value from public.system_settings where key = :key"), {"key": key}
    ).scalar()


def lock_goods_slip(session: Session, gs_id: UUID) -> dict[str, Any] | None:
    """Row-lock the GS for the rest of the transaction (G-20 serialisation)."""
    row = (
        session.execute(
            text("select id, gs_no, status from public.goods_slips where id = :id for update"),
            {"id": gs_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def lock_routing_header(session: Session, routing_id: UUID) -> dict[str, Any] | None:
    """Row-lock the routing header (concurrent receipts against one routing are serialised)."""
    row = (
        session.execute(
            text(
                "select id, gs_id, status from public.department_routings where id = :id for update"
            ),
            {"id": routing_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_department_field(session: Session, field_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select id, code, label, is_active from public.item_field_library
                 where id = :id and field_group = 'DEPARTMENT'
                """
            ),
            {"id": field_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def get_gs_item(session: Session, gs_id: UUID, item_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select gi.id, gi.gs_id, gi.line_no, gi.product_id,
                       coalesce(gi.product_name_snapshot, pr.name, 'Item') as item_name
                  from public.gs_items gi
                  left join public.products pr on pr.id = gi.product_id
                 where gi.id = :item_id and gi.gs_id = :gs_id
                """
            ),
            {"item_id": item_id, "gs_id": gs_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def is_department_allowed(session: Session, product_id: UUID, department_field_id: UUID) -> bool:
    """Phase 4 resolver: is the department in the product's effective DEPARTMENT group?"""
    return bool(
        session.execute(
            text(
                """
                select 1 from rms_private.resolve_item_field_profile(:product_id)
                 where field_group = 'DEPARTMENT' and field_id = :dept_id
                """
            ),
            {"product_id": product_id, "dept_id": department_field_id},
        ).scalar()
    )


def find_any_lot_for_item(session: Session, gs_item_id: UUID) -> UUID | None:
    value = session.execute(
        text(
            "select id from public.stock_lots where gs_item_id = :item_id"
            " order by created_at limit 1"
        ),
        {"item_id": gs_item_id},
    ).scalar()
    return UUID(str(value)) if value else None


def next_number(session: Session, series_code: str) -> str:
    return str(
        session.execute(
            text("select rms_private.next_number(:code)"), {"code": series_code}
        ).scalar_one()
    )


def validate_reconciliation(session: Session, gs_id: UUID) -> None:
    """Run the DB G-20 check (raises a 'G-20: …' DB error on violation)."""
    session.execute(
        text("select rms_private.validate_department_reconciliation(:gs_id)"), {"gs_id": gs_id}
    )


def get_outcome_head_by_id(session: Session, head_id: UUID) -> dict[str, Any] | None:
    stmt = text(
        """
        select id, code, label, is_wastage, returns_to_routing, sort_order, is_active
          from public.department_outcome_heads
         where id = :id
        """
    )
    row = session.execute(stmt, {"id": head_id}).mappings().first()
    return dict(row) if row else None


def list_rm_routing_queue(session: Session) -> list[dict[str, Any]]:
    """Return all GSs held at intermediate store for the RM routing queue."""
    stmt = text(
        """
        select
          gs.id as gs_id,
          gs.gs_no,
          p.name as party_name,
          count(distinct gi.id)::int as item_count,
          coalesce(sum(gi.received_qty), 0)::int as total_counted_qty,
          gs.updated_at as held_since,
          coalesce((
            select count(*)::int
              from public.department_routings dr
             where dr.gs_id = gs.id and dr.status in ('DISPATCHED', 'PARTIALLY_RECEIVED')
          ), 0) as active_routings_count
        from public.goods_slips gs
        left join public.parties p on p.id = gs.party_id
        left join public.gs_items gi on gi.gs_id = gs.id
        where gs.status = 'HELD_AT_INTERMEDIATE_STORE'
        group by gs.id, gs.gs_no, p.name, gs.updated_at
        order by gs.updated_at desc
        """
    )
    rows = session.execute(stmt).mappings().all()
    results: list[dict[str, Any]] = []

    for r in rows:
        row_dict = dict(r)
        # Compute in_store and at_departments for summary
        gs_id = row_dict["gs_id"]
        recon = get_gs_reconciliation(session, gs_id)
        row_dict["in_store_qty"] = recon["total_in_store"]
        row_dict["at_departments_qty"] = recon["total_at_departments"]
        results.append(row_dict)

    return results


def get_gs_routing_state(session: Session, gs_id: UUID) -> dict[str, Any] | None:
    """Fetch GS routing state: header, items with bucket breakdown, available quantities and
    resolved departments."""
    stmt_header = text(
        """
        select gs.id, gs.gs_no, gs.status, p.name as party_name, gs.created_at, gs.updated_at
          from public.goods_slips gs
          left join public.parties p on p.id = gs.party_id
         where gs.id = :gs_id
        """
    )
    header_row = session.execute(stmt_header, {"gs_id": gs_id}).mappings().first()
    if not header_row:
        return None

    header = dict(header_row)

    # Fetch items with products
    stmt_items = text(
        """
        select
          gi.id as item_id,
          gi.line_no,
          coalesce(gi.product_name_snapshot, pr.name, 'Item') as item_name,
          coalesce(gi.product_code_snapshot, pr.code) as sku_code,
          gi.product_id,
          gi.received_qty as counted_qty
        from public.gs_items gi
        left join public.products pr on pr.id = gi.product_id
        where gi.gs_id = :gs_id
        order by gi.line_no asc
        """
    )
    item_rows = session.execute(stmt_items, {"gs_id": gs_id}).mappings().all()

    items: list[dict[str, Any]] = []
    for ir in item_rows:
        it = dict(ir)
        item_id = it["item_id"]
        prod_id = it["product_id"]

        # Resolved departments for product
        stmt_depts = text(
            """
            select field_id, code, label, sort_order
              from rms_private.resolve_item_field_profile(:product_id)
             where field_group = 'DEPARTMENT'
             order by sort_order asc, label asc
            """
        )
        depts = [
            dict(d) for d in session.execute(stmt_depts, {"product_id": prod_id}).mappings().all()
        ]
        it["allowed_departments"] = depts

        # Categorisation buckets for item
        stmt_buckets = text(
            """
            select
              b.id,
              b.field_id,
              l.code as field_code,
              l.label as field_label,
              b.qty
            from public.gs_item_buckets b
            join public.item_field_library l on l.id = b.field_id
            where b.gs_item_id = :item_id
            order by l.sort_order asc, l.label asc
            """
        )
        buckets = [
            dict(b) for b in session.execute(stmt_buckets, {"item_id": item_id}).mappings().all()
        ]
        it["buckets"] = buckets

        # Quantities breakdown
        item_recon = get_item_reconciliation(
            session, item_id, it["counted_qty"], it["line_no"], it["item_name"], it["sku_code"]
        )
        it["in_store_qty"] = item_recon["in_store_qty"]
        it["at_departments_qty"] = item_recon["at_departments_qty"]
        it["outcome_heads_qty"] = item_recon["outcome_heads_qty"]
        it["actioned_qty"] = item_recon["actioned_qty"]
        items.append(it)

    header["items"] = items
    return header


def get_item_reconciliation(
    session: Session,
    item_id: UUID,
    counted_qty: int,
    line_no: int,
    item_name: str,
    sku_code: str | None,
) -> dict[str, Any]:
    """Compute quantity conservation for a single GS item (G-20)."""
    # 1. At departments
    stmt_dept = text(
        """
        select coalesce(sum(rl.qty_sent - rl.qty_received), 0)::int as at_dept
          from public.department_routing_lines rl
          join public.department_routings r on r.id = rl.routing_id
         where rl.gs_item_id = :item_id
           and r.status in ('DISPATCHED', 'PARTIALLY_RECEIVED')
        """
    )
    at_dept = session.execute(stmt_dept, {"item_id": item_id}).scalar() or 0

    # 2. Terminal outcome heads (where returns_to_routing is false)
    stmt_outcomes = text(
        """
        select coalesce(sum(rcl.quantity), 0)::int as outcomes
          from public.department_receipt_lines rcl
          join public.department_routing_lines rl on rl.id = rcl.routing_line_id
         where rl.gs_item_id = :item_id
           and not rcl.returns_to_routing
        """
    )
    outcomes = session.execute(stmt_outcomes, {"item_id": item_id}).scalar() or 0

    # 3. Actioned by RM
    stmt_actioned = text(
        """
        select coalesce(sum(act.qty), 0)::int as actioned
          from public.rm_item_actions act
         where act.gs_item_id = :item_id
           and act.is_current = true
        """
    )
    actioned = session.execute(stmt_actioned, {"item_id": item_id}).scalar() or 0

    # 4. In store. Phase 7 (AMD-16, G-20 fix-forward, same rule as the DB function): RM final
    # actions cover pieces in outcome heads first, then pieces in store, so a returned piece that is
    # actioned is not counted twice. outcome_heads = outcome qty not yet actioned.
    outcomes = max(outcomes - actioned, 0)
    in_store = counted_qty - at_dept - outcomes - actioned

    is_conserved = (in_store >= 0) and ((in_store + at_dept + outcomes + actioned) == counted_qty)

    return {
        "gs_item_id": item_id,
        "line_no": line_no,
        "item_name": item_name,
        "sku_code": sku_code,
        "counted_qty": counted_qty,
        "in_store_qty": in_store,
        "at_departments_qty": at_dept,
        "outcome_heads_qty": outcomes,
        "actioned_qty": actioned,
        "is_conserved": is_conserved,
    }


def get_gs_reconciliation(session: Session, gs_id: UUID) -> dict[str, Any]:
    """Compute full G-20 reconciliation panel data for a GS."""
    stmt_gs = text("select id, gs_no from public.goods_slips where id = :gs_id")
    gs_row = session.execute(stmt_gs, {"gs_id": gs_id}).mappings().first()
    gs_no = gs_row["gs_no"] if gs_row else ""

    stmt_items = text(
        """
        select
          gi.id as item_id,
          gi.line_no,
          coalesce(gi.product_name_snapshot, pr.name, 'Item') as item_name,
          coalesce(gi.product_code_snapshot, pr.code) as sku_code,
          gi.received_qty as counted_qty
        from public.gs_items gi
        left join public.products pr on pr.id = gi.product_id
        where gi.gs_id = :gs_id
        order by gi.line_no asc
        """
    )
    items_data: list[dict[str, Any]] = []
    tot_counted = 0
    tot_in_store = 0
    tot_at_dept = 0
    tot_outcomes = 0
    tot_actioned = 0
    fully_reconciled = True

    for r in session.execute(stmt_items, {"gs_id": gs_id}).mappings().all():
        it_recon = get_item_reconciliation(
            session,
            r["item_id"],
            r["counted_qty"],
            r["line_no"],
            r["item_name"],
            r["sku_code"],
        )
        tot_counted += it_recon["counted_qty"]
        tot_in_store += it_recon["in_store_qty"]
        tot_at_dept += it_recon["at_departments_qty"]
        tot_outcomes += it_recon["outcome_heads_qty"]
        tot_actioned += it_recon["actioned_qty"]
        if not it_recon["is_conserved"]:
            fully_reconciled = False
        items_data.append(it_recon)

    return {
        "gs_id": gs_id,
        "gs_no": gs_no,
        "is_fully_reconciled": fully_reconciled,
        "total_counted": tot_counted,
        "total_in_store": tot_in_store,
        "total_at_departments": tot_at_dept,
        "total_outcomes": tot_outcomes,
        "total_actioned": tot_actioned,
        "items": items_data,
    }


def create_department_routing(
    session: Session,
    *,
    routing_no: str,
    gs_id: UUID,
    department_field_id: UUID,
    department_code: str,
    department_label: str,
    dispatched_by: UUID,
    remarks: str | None = None,
    lines: list[dict[str, Any]],
) -> dict[str, Any]:
    """Insert a new department routing header and lines."""
    stmt_ins = text(
        """
        insert into public.department_routings (
          routing_no, gs_id, department_field_id, department_code, department_label,
          status, dispatched_by, notes
        ) values (
          :routing_no, :gs_id, :dept_field_id, :dept_code, :dept_label,
          'DISPATCHED', :dispatched_by, :notes
        )
        returning id, routing_no, gs_id, department_field_id, department_code, department_label,
                  status, dispatched_at, dispatched_by, notes as remarks
        """
    )
    routing_row = (
        session.execute(
            stmt_ins,
            {
                "routing_no": routing_no,
                "gs_id": gs_id,
                "dept_field_id": department_field_id,
                "dept_code": department_code,
                "dept_label": department_label,
                "dispatched_by": dispatched_by,
                "notes": remarks,
            },
        )
        .mappings()
        .one()
    )

    routing_id = routing_row["id"]

    stmt_line = text(
        """
        insert into public.department_routing_lines (
          routing_id, gs_item_id, source_bucket_field_id, lot_id, qty_sent, qty_received, notes
        ) values (
          :routing_id, :gs_item_id, :source_bucket_field_id, :lot_id, :qty_sent, 0, :notes
        )
        returning id
        """
    )
    for line in lines:
        session.execute(
            stmt_line,
            {
                "routing_id": routing_id,
                "gs_item_id": line["gs_item_id"],
                "source_bucket_field_id": line.get("source_bucket_field_id"),
                "lot_id": line.get("lot_id"),
                "qty_sent": line["qty_sent"],
                "notes": line.get("notes"),
            },
        )

    return get_routing(session, routing_id) or {}


def get_routing(session: Session, routing_id: UUID) -> dict[str, Any] | None:
    """Fetch routing detail including lines, items, and dispatched user name."""
    stmt = text(
        """
        select
          r.id,
          r.routing_no,
          r.gs_id,
          gs.gs_no,
          r.department_field_id,
          r.department_code,
          r.department_label,
          r.status,
          r.dispatched_at,
          r.dispatched_by,
          u.full_name as dispatched_by_name,
          r.notes as remarks
        from public.department_routings r
        join public.goods_slips gs on gs.id = r.gs_id
        left join public.profiles u on u.id = r.dispatched_by
        where r.id = :id
        """
    )
    r_row = session.execute(stmt, {"id": routing_id}).mappings().first()
    if not r_row:
        return None

    routing = dict(r_row)

    # Lines
    stmt_lines = text(
        """
        select
          rl.id,
          rl.routing_id,
          rl.gs_item_id,
          gi.line_no,
          coalesce(gi.product_name_snapshot, pr.name, 'Item') as item_name,
          coalesce(gi.product_code_snapshot, pr.code) as sku_code,
          rl.source_bucket_field_id,
          bl.code as source_bucket_code,
          bl.label as source_bucket_label,
          rl.qty_sent,
          rl.qty_received,
          (rl.qty_sent - rl.qty_received)::int as qty_pending,
          rl.notes
        from public.department_routing_lines rl
        join public.gs_items gi on gi.id = rl.gs_item_id
        left join public.products pr on pr.id = gi.product_id
        left join public.item_field_library bl on bl.id = rl.source_bucket_field_id
        where rl.routing_id = :id
        order by gi.line_no asc
        """
    )
    lines = [dict(row) for row in session.execute(stmt_lines, {"id": routing_id}).mappings().all()]
    routing["lines"] = lines
    return routing


def list_receiving_queue(session: Session) -> list[dict[str, Any]]:
    """List routings waiting to be received (DISPATCHED or PARTIALLY_RECEIVED)."""
    stmt = text(
        """
        select
          r.id as routing_id,
          r.routing_no,
          r.gs_id,
          gs.gs_no,
          r.department_code,
          r.department_label,
          r.status,
          r.dispatched_at,
          u.full_name as dispatched_by_name,
          coalesce(sum(rl.qty_sent), 0)::int as total_sent,
          coalesce(sum(rl.qty_received), 0)::int as total_received,
          coalesce(sum(rl.qty_sent - rl.qty_received), 0)::int as total_pending
        from public.department_routings r
        join public.goods_slips gs on gs.id = r.gs_id
        join public.department_routing_lines rl on rl.routing_id = r.id
        left join public.profiles u on u.id = r.dispatched_by
        where r.status in ('DISPATCHED', 'PARTIALLY_RECEIVED')
        group by r.id, r.routing_no, r.gs_id, gs.gs_no, r.department_code, r.department_label,
                 r.status, r.dispatched_at, u.full_name
        order by r.dispatched_at asc
        """
    )
    rows = session.execute(stmt).mappings().all()
    return [dict(r) for r in rows]


def create_department_receipt(
    session: Session,
    *,
    receipt_no: str,
    routing_id: UUID,
    received_by: UUID,
    remarks: str | None = None,
    lines: list[dict[str, Any]],
) -> dict[str, Any]:
    """Insert a receipt header and receipt outcome breakdown lines."""
    stmt_ins = text(
        """
        insert into public.department_receipts (
          receipt_no, routing_id, received_by, remarks
        ) values (
          :receipt_no, :routing_id, :received_by, :remarks
        )
        returning id, receipt_no, routing_id, received_by, received_at, remarks
        """
    )
    rec_row = (
        session.execute(
            stmt_ins,
            {
                "receipt_no": receipt_no,
                "routing_id": routing_id,
                "received_by": received_by,
                "remarks": remarks,
            },
        )
        .mappings()
        .one()
    )

    receipt_id = rec_row["id"]

    stmt_line = text(
        """
        insert into public.department_receipt_lines (
          receipt_id, routing_line_id, outcome_head_id, outcome_code, outcome_label,
          is_wastage, returns_to_routing, quantity, remarks
        ) values (
          :receipt_id, :routing_line_id, :outcome_head_id, :outcome_code, :outcome_label,
          :is_wastage, :returns_to_routing, :quantity, :remarks
        )
        """
    )
    for line in lines:
        session.execute(
            stmt_line,
            {
                "receipt_id": receipt_id,
                "routing_line_id": line["routing_line_id"],
                "outcome_head_id": line["outcome_head_id"],
                "outcome_code": line["outcome_code"],
                "outcome_label": line["outcome_label"],
                "is_wastage": line["is_wastage"],
                "returns_to_routing": line["returns_to_routing"],
                "quantity": line["quantity"],
                "remarks": line.get("remarks"),
            },
        )

    return get_receipt(session, receipt_id) or {}


def get_receipt(session: Session, receipt_id: UUID) -> dict[str, Any] | None:
    """Fetch receipt details with outcome lines."""
    stmt = text(
        """
        select
          rc.id,
          rc.receipt_no,
          rc.routing_id,
          rc.received_by,
          u.full_name as received_by_name,
          rc.received_at,
          rc.remarks
        from public.department_receipts rc
        left join public.profiles u on u.id = rc.received_by
        where rc.id = :id
        """
    )
    rc_row = session.execute(stmt, {"id": receipt_id}).mappings().first()
    if not rc_row:
        return None

    receipt = dict(rc_row)

    stmt_lines = text(
        """
        select
          rcl.id,
          rcl.receipt_id,
          rcl.routing_line_id,
          rcl.outcome_head_id,
          rcl.outcome_code,
          rcl.outcome_label,
          rcl.is_wastage,
          rcl.returns_to_routing,
          rcl.quantity,
          rcl.remarks,
          rcl.created_at
        from public.department_receipt_lines rcl
        where rcl.receipt_id = :id
        order by rcl.created_at asc
        """
    )
    receipt["lines"] = [
        dict(r) for r in session.execute(stmt_lines, {"id": receipt_id}).mappings().all()
    ]
    return receipt


def get_gs_department_legs(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    """Return all department legs (dispatches, receipts, lines) for a GS timeline."""
    stmt_routings = text(
        """
        select
          r.id as routing_id,
          r.routing_no,
          r.department_code,
          r.department_label,
          r.status,
          r.dispatched_at,
          u.full_name as dispatched_by_name,
          coalesce(sum(rl.qty_sent), 0)::int as qty_sent,
          coalesce(sum(rl.qty_received), 0)::int as qty_received,
          coalesce(sum(rl.qty_sent - rl.qty_received), 0)::int as qty_pending
        from public.department_routings r
        left join public.profiles u on u.id = r.dispatched_by
        join public.department_routing_lines rl on rl.routing_id = r.id
        where r.gs_id = :gs_id
        group by r.id, r.routing_no, r.department_code, r.department_label, r.status,
                 r.dispatched_at, u.full_name
        order by r.dispatched_at asc
        """
    )
    legs: list[dict[str, Any]] = []
    for r in session.execute(stmt_routings, {"gs_id": gs_id}).mappings().all():
        leg = dict(r)
        routing_id = leg["routing_id"]

        # Detail lines
        r_detail = get_routing(session, routing_id)
        leg["lines"] = r_detail.get("lines", []) if r_detail else []

        # Receipts
        stmt_rc = text(
            """
            select id from public.department_receipts
             where routing_id = :routing_id order by received_at asc
            """
        )
        rc_ids = [row[0] for row in session.execute(stmt_rc, {"routing_id": routing_id}).fetchall()]
        receipts = []
        for rc_id in rc_ids:
            rc_detail = get_receipt(session, rc_id)
            if rc_detail:
                receipts.append(rc_detail)
        leg["receipts"] = receipts
        legs.append(leg)

    return legs
