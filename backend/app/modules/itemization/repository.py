"""Itemisation repository: SQL only, no business rules (prompt P2-04)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

_ITEM_COLUMNS = """
  i.id, i.gs_id, i.line_no, i.product_id, i.category_id, i.product_code_snapshot,
  i.product_name_snapshot, i.category_code_snapshot, pc.name as category_name,
  i.documented_qty, i.received_qty, i.short_qty, i.excess_qty, i.remarks,
  i.created_at, i.updated_at
"""
_ITEM_FROM = """
  from public.gs_items i
  join public.product_categories pc on pc.id = i.category_id
"""
_DECISION_COLUMNS = """
  c.id, c.gs_id, c.decision_code, c.remarks, c.is_current, c.is_admin_action, c.labels_snapshot,
  c.form_version_id, c.decided_by, db.full_name as decided_by_name, c.decided_at,
  c.reopened_by, rb.full_name as reopened_by_name, c.reopened_at, c.reopen_reason
"""
_DECISION_FROM = """
  from public.csr_approvals c
  left join public.profiles db on db.id = c.decided_by
  left join public.profiles rb on rb.id = c.reopened_by
"""
_CORRECTION_COLUMNS = """
  k.id, k.gs_id, g.gs_no, k.gs_item_id, i.line_no, i.product_name_snapshot as product_name,
  k.old_documented_qty, k.old_received_qty, k.new_documented_qty, k.new_received_qty, k.reason,
  k.status, k.requested_by, rq.full_name as requested_by_name, k.requested_at, k.decided_by,
  dc.full_name as decided_by_name, k.decided_at, k.decision_remarks, k.applied_at,
  k.stock_movement_id
"""
_CORRECTION_FROM = """
  from public.gs_item_corrections k
  join public.goods_slips g on g.id = k.gs_id
  join public.gs_items i on i.id = k.gs_item_id
  left join public.profiles rq on rq.id = k.requested_by
  left join public.profiles dc on dc.id = k.decided_by
"""


def get_setting(session: Session, key: str) -> Any:
    return session.execute(
        text("select value from public.system_settings where key = :key"), {"key": key}
    ).scalar()


def get_published_form(session: Session, form_code: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select v.id, v.version_no, v.snapshot
                  from public.form_versions v
                  join public.form_definitions d on d.id = v.form_definition_id
                 where d.code = :code and v.status = 'PUBLISHED'
                """
            ),
            {"code": form_code},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def categorization_info(session: Session, gs_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select g.categorized_by, p.full_name as categorized_by_name,
                       g.category_labels_snapshot, g.category_form_version_id
                  from public.goods_slips g
                  left join public.profiles p on p.id = g.categorized_by
                 where g.id = :id
                """
            ),
            {"id": gs_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def set_transaction_setting(session: Session, key: str, value: str | None) -> None:
    session.execute(text("select set_config(:k, :v, true)"), {"k": key, "v": value or ""})


# --- products ---------------------------------------------------------------------------------
_PRODUCT_COLUMNS = """
  p.id, p.code, p.name, p.uom, p.category_id, pc.code as category_code,
  pc.name as category_name, pc.condition_option_set_id
"""


def search_products(
    session: Session,
    q: str | None,
    limit: int,
    *,
    category_id: UUID | None = None,
    subcategory_id: UUID | None = None,
) -> list[dict[str, Any]]:
    """Active products by name / code / category / sub-category text, optionally filtered by
    category and sub-category (AMD-07 hierarchy; counting search, change plan Phase 3)."""
    rows = session.execute(
        text(
            f"""
            select {_PRODUCT_COLUMNS}, p.subcategory_id, ps.name as subcategory_name
              from public.products p
              join public.product_categories pc on pc.id = p.category_id
              left join public.product_subcategories ps on ps.id = p.subcategory_id
             where p.is_active and pc.is_active
               and (cast(:cat as uuid) is null or p.category_id = cast(:cat as uuid))
               and (cast(:sub as uuid) is null or p.subcategory_id = cast(:sub as uuid))
               and (cast(:q as text) is null or p.name ilike '%' || cast(:q as text) || '%'
                    or p.code ilike '%' || cast(:q as text) || '%'
                    or pc.name ilike '%' || cast(:q as text) || '%'
                    or ps.name ilike '%' || cast(:q as text) || '%')
             order by p.name
             limit :limit
            """  # noqa: S608
        ),
        {"q": q or None, "limit": limit, "cat": category_id, "sub": subcategory_id},
    ).mappings()
    return [dict(r) for r in rows]


def product_categories_with_subcategories(session: Session) -> list[dict[str, Any]]:
    """Active categories and their active sub-categories (counting filters)."""
    rows = session.execute(
        text(
            """
            select pc.id, pc.code, pc.name,
                   coalesce((select jsonb_agg(jsonb_build_object('id', ps.id, 'code', ps.code,
                                                                 'name', ps.name)
                                              order by ps.name)
                               from public.product_subcategories ps
                              where ps.category_id = pc.id and ps.is_active), '[]'::jsonb)
                     as subcategories
              from public.product_categories pc
             where pc.is_active
             order by pc.name
            """
        )
    ).mappings()
    return [dict(r) for r in rows]


def get_product(session: Session, product_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                f"""
                select {_PRODUCT_COLUMNS}, p.is_active and pc.is_active as is_active
                  from public.products p
                  join public.product_categories pc on pc.id = p.category_id
                 where p.id = :id
                """  # noqa: S608
            ),
            {"id": product_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def short_qty_category_ids(session: Session) -> set[UUID]:
    """Categories whose condition option set has an option with system_behavior SHORT_QTY."""
    rows = session.execute(
        text(
            """
            select distinct pc.id
              from public.product_categories pc
              join public.option_items oi on oi.option_set_id = pc.condition_option_set_id
             where oi.system_behavior = 'SHORT_QTY' and oi.is_active
            """
        )
    ).scalars()
    return {UUID(str(r)) for r in rows}


# --- item lines -------------------------------------------------------------------------------
def list_items(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(f"select {_ITEM_COLUMNS} {_ITEM_FROM} where i.gs_id = :gs order by i.line_no"),
        {"gs": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def get_item(session: Session, item_id: UUID, *, for_update: bool = False) -> dict[str, Any] | None:
    lock = " for update of i" if for_update else ""
    row = (
        session.execute(
            text(f"select {_ITEM_COLUMNS} {_ITEM_FROM} where i.id = :id{lock}"), {"id": item_id}
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def insert_item(
    session: Session,
    *,
    gs_id: UUID,
    product: dict[str, Any],
    documented_qty: int,
    received_qty: int,
    remarks: str | None,
    by: UUID,
) -> UUID:
    return UUID(
        str(
            session.execute(
                text(
                    """
                    insert into public.gs_items (
                      gs_id, line_no, product_id, category_id, product_code_snapshot,
                      product_name_snapshot, category_code_snapshot, documented_qty,
                      received_qty, remarks, created_by
                    )
                    select :gs, coalesce(max(line_no), 0) + 1, :pid, :cid, :pcode, :pname,
                           :ccode, :dq, :rq, :remarks, :by
                      from public.gs_items where gs_id = :gs
                    returning id
                    """
                ),
                {
                    "gs": gs_id,
                    "pid": product["id"],
                    "cid": product["category_id"],
                    "pcode": product["code"],
                    "pname": product["name"],
                    "ccode": product["category_code"],
                    "dq": documented_qty,
                    "rq": received_qty,
                    "remarks": remarks,
                    "by": by,
                },
            ).scalar_one()
        )
    )


def update_item(session: Session, item_id: UUID, fields: dict[str, Any]) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    session.execute(
        text(f"update public.gs_items set {sets}, updated_at = now() where id = :id"),  # noqa: S608
        {**fields, "id": item_id},
    )


def delete_item(session: Session, item_id: UUID) -> None:
    session.execute(text("delete from public.gs_items where id = :id"), {"id": item_id})


# --- CSR decisions ----------------------------------------------------------------------------
def current_decision(session: Session, gs_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                f"select {_DECISION_COLUMNS} {_DECISION_FROM} where c.gs_id = :gs and c.is_current"
            ),
            {"gs": gs_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def list_decisions(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            f"select {_DECISION_COLUMNS} {_DECISION_FROM} where c.gs_id = :gs order by c.decided_at"
        ),
        {"gs": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def insert_decision(
    session: Session,
    *,
    gs_id: UUID,
    decision_code: str,
    remarks: str | None,
    form_version_id: UUID,
    labels_snapshot: dict[str, Any],
    by: UUID,
) -> UUID:
    return UUID(
        str(
            session.execute(
                text(
                    """
                    insert into public.csr_approvals (
                      gs_id, decision_code, remarks, form_version_id, labels_snapshot, decided_by
                    ) values (:gs, :code, :remarks, :fv, cast(:labels as jsonb), :by)
                    returning id
                    """
                ),
                {
                    "gs": gs_id,
                    "code": decision_code,
                    "remarks": remarks,
                    "fv": form_version_id,
                    "labels": json.dumps(labels_snapshot, default=str),
                    "by": by,
                },
            ).scalar_one()
        )
    )


def reopen_decision(session: Session, decision_id: UUID, *, reason: str, by: UUID) -> None:
    session.execute(
        text(
            """
            update public.csr_approvals
               set is_current = false, reopened_by = :by, reopened_at = now(),
                   reopen_reason = :reason
             where id = :id
            """
        ),
        {"id": decision_id, "by": by, "reason": reason},
    )


def user_assigned_to_step(
    session: Session, user_id: UUID, workflow_version_id: UUID, step_code: str, kind: str
) -> bool:
    return bool(
        session.execute(
            text("select rms_private.user_assigned_to_step(:u, :v, :s, :k)"),
            {"u": user_id, "v": workflow_version_id, "s": step_code, "k": kind},
        ).scalar()
    )


def pending_csr_gs_ids(session: Session, limit: int) -> list[UUID]:
    rows = session.execute(
        text(
            """
            select g.id from public.goods_slips g
             where g.status = 'CSR_APPROVAL_PENDING'
             order by g.categorized_at nulls last, g.created_at
             limit :limit
            """
        ),
        {"limit": limit},
    ).scalars()
    return [UUID(str(r)) for r in rows]


def has_inspections(session: Session, gs_id: UUID) -> bool:
    return bool(
        session.execute(
            text(
                """
                select exists (select 1 from public.inspections s
                                 join public.gs_items i on i.id = s.gs_item_id
                                where i.gs_id = :gs)
                """
            ),
            {"gs": gs_id},
        ).scalar()
    )


def item_has_final_inspection(session: Session, item_id: UUID) -> bool:
    return bool(
        session.execute(
            text(
                "select exists (select 1 from public.inspections "
                "where gs_item_id = :i and status = 'FINAL')"
            ),
            {"i": item_id},
        ).scalar()
    )


# --- line corrections -------------------------------------------------------------------------
def insert_correction(
    session: Session,
    *,
    gs_id: UUID,
    item: dict[str, Any],
    new_documented_qty: int,
    new_received_qty: int,
    reason: str,
    by: UUID,
) -> UUID:
    return UUID(
        str(
            session.execute(
                text(
                    """
                    insert into public.gs_item_corrections (
                      gs_id, gs_item_id, old_documented_qty, old_received_qty,
                      new_documented_qty, new_received_qty, reason, requested_by
                    ) values (:gs, :item, :od, :orq, :nd, :nr, :reason, :by)
                    returning id
                    """
                ),
                {
                    "gs": gs_id,
                    "item": item["id"],
                    "od": item["documented_qty"],
                    "orq": item["received_qty"],
                    "nd": new_documented_qty,
                    "nr": new_received_qty,
                    "reason": reason,
                    "by": by,
                },
            ).scalar_one()
        )
    )


def get_correction(
    session: Session, correction_id: UUID, *, for_update: bool = False
) -> dict[str, Any] | None:
    lock = " for update of k" if for_update else ""
    row = (
        session.execute(
            text(f"select {_CORRECTION_COLUMNS} {_CORRECTION_FROM} where k.id = :id{lock}"),
            {"id": correction_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def list_corrections(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            f"select {_CORRECTION_COLUMNS} {_CORRECTION_FROM} where k.gs_id = :gs "
            "order by k.requested_at"
        ),
        {"gs": gs_id},
    ).mappings()
    return [dict(r) for r in rows]


def pending_corrections(session: Session, limit: int) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            f"select {_CORRECTION_COLUMNS} {_CORRECTION_FROM} where k.status = 'REQUESTED' "
            "order by k.requested_at limit :limit"
        ),
        {"limit": limit},
    ).mappings()
    return [dict(r) for r in rows]


def open_correction_for_item(session: Session, item_id: UUID) -> bool:
    return bool(
        session.execute(
            text(
                "select exists (select 1 from public.gs_item_corrections "
                "where gs_item_id = :i and status = 'REQUESTED')"
            ),
            {"i": item_id},
        ).scalar()
    )


def decide_correction(
    session: Session, correction_id: UUID, *, status: str, by: UUID, remarks: str | None
) -> None:
    session.execute(
        text(
            """
            update public.gs_item_corrections
               set status = :s, decided_by = :by, decided_at = now(), decision_remarks = :r
             where id = :id
            """
        ),
        {"id": correction_id, "s": status, "by": by, "r": remarks},
    )


def mark_correction_applied(
    session: Session, correction_id: UUID, movement_id: UUID | None
) -> None:
    session.execute(
        text(
            """
            update public.gs_item_corrections
               set applied_at = now(), stock_movement_id = :m
             where id = :id
            """
        ),
        {"id": correction_id, "m": movement_id},
    )


# --- packaging checks (DEC-27) ----------------------------------------------------------------
def insert_packaging_check(
    session: Session, *, lot_id: UUID, result_code: str, qty: int, remarks: str | None, by: UUID
) -> UUID:
    return UUID(
        str(
            session.execute(
                text(
                    """
                    insert into public.packaging_replacements
                      (lot_id, result_code, qty, remarks, "by", "at")
                    values (:lot, :res, :qty, :remarks, :by, clock_timestamp())
                    returning id
                    """
                ),
                {"lot": lot_id, "res": result_code, "qty": qty, "remarks": remarks, "by": by},
            ).scalar_one()
        )
    )


def packaging_checks_for_lots(session: Session, lot_ids: list[UUID]) -> list[dict[str, Any]]:
    if not lot_ids:
        return []
    rows = session.execute(
        text(
            """
            select r.id, r.lot_id, r.result_code, r.qty as qty_replaced, r.remarks, r."by",
                   p.full_name as by_name, r."at"
              from public.packaging_replacements r
              left join public.profiles p on p.id = r."by"
             where r.lot_id = any(:ids)
             order by r."at"
            """
        ),
        {"ids": lot_ids},
    ).mappings()
    return [dict(r) for r in rows]


def get_packaging_check(session: Session, check_id: UUID) -> dict[str, Any] | None:
    rows = session.execute(
        text(
            """
            select r.id, r.lot_id, r.result_code, r.qty as qty_replaced, r.remarks, r."by",
                   p.full_name as by_name, r."at"
              from public.packaging_replacements r
              left join public.profiles p on p.id = r."by"
             where r.id = :id
            """
        ),
        {"id": check_id},
    ).mappings()
    row = rows.first()
    return dict(row) if row else None


def user_has_role_id(session: Session, user_id: UUID, role_id: UUID | None) -> bool:
    if role_id is None:
        return False
    return bool(
        session.execute(
            text(
                "select exists (select 1 from public.user_roles "
                "where user_id = :u and role_id = :r)"
            ),
            {"u": user_id, "r": role_id},
        ).scalar()
    )


# --- Phase 5: Item buckets & counts (AMD-09, AMD-11, AMD-12) ----------------------------------
def set_counted_by(session: Session, gs_id: UUID, user_id: UUID) -> None:
    session.execute(
        text("update public.goods_slips set counted_by = :u where id = :gs"),
        {"u": user_id, "gs": gs_id},
    )


def get_counted_by_info(session: Session, gs_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select g.counted_by, p.full_name as counted_by_name
                  from public.goods_slips g
                  left join public.profiles p on p.id = g.counted_by
                 where g.id = :id
                """
            ),
            {"id": gs_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def resolve_profile_for_product(
    session: Session, product_id: UUID, version_id: UUID | None = None
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select profile_version_id, profile_version_no, field_group, field_id,
                   code, label, sort_order, source_scope_type, source_scope_id,
                   is_wastage, returns_to_routing, requires_cn, requires_challan,
                   system_behavior
              from rms_private.resolve_item_field_profile(
                     cast(:pid as uuid), cast(:vid as uuid)
                   )
            """
        ),
        {"pid": product_id, "vid": version_id},
    ).mappings()
    return [dict(r) for r in rows]


def get_profile_version_id(session: Session, gs_id: UUID) -> UUID | None:
    """The item-field profile version stamped on the GS (null until it leaves CATEGORISATION)."""
    value = session.execute(
        text("select item_field_profile_version_id from public.goods_slips where id = :id"),
        {"id": gs_id},
    ).scalar_one_or_none()
    return UUID(str(value)) if value else None


def get_item_buckets(session: Session, item_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select b.id, b.gs_item_id, b.field_id, b.field_code, b.label_snapshot,
                   b.qty, b.created_at, b.updated_at
              from public.gs_item_buckets b
             where b.gs_item_id = :item_id
             order by b.created_at
            """
        ),
        {"item_id": item_id},
    ).mappings()
    return [dict(r) for r in rows]


def get_buckets_for_items(session: Session, item_ids: list[UUID]) -> list[dict[str, Any]]:
    if not item_ids:
        return []
    rows = session.execute(
        text(
            """
            select b.id, b.gs_item_id, b.field_id, b.field_code, b.label_snapshot,
                   b.qty, b.created_at, b.updated_at
              from public.gs_item_buckets b
             where b.gs_item_id = any(:ids)
             order by b.gs_item_id, b.created_at
            """
        ),
        {"ids": item_ids},
    ).mappings()
    return [dict(r) for r in rows]


def upsert_item_bucket(session: Session, item_id: UUID, field_id: UUID, qty: int, by: UUID) -> UUID:
    res = session.execute(
        text(
            """
            insert into public.gs_item_buckets (gs_item_id, field_id, qty, created_by)
            values (:item_id, :field_id, :qty, :by)
            on conflict (gs_item_id, field_id) do update
               set qty = excluded.qty, updated_at = now()
            returning id
            """
        ),
        {"item_id": item_id, "field_id": field_id, "qty": qty, "by": by},
    ).scalar_one()
    return UUID(str(res))


def delete_item_buckets(session: Session, item_id: UUID) -> None:
    session.execute(
        text("delete from public.gs_item_buckets where gs_item_id = :item_id"),
        {"item_id": item_id},
    )


def get_item_counts(session: Session, item_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select c.id, c.gs_item_id, c.field_id, c.field_code, c.label_snapshot,
                   c.qty, c.created_at, c.updated_at
              from public.gs_item_counts c
             where c.gs_item_id = :item_id
             order by c.created_at
            """
        ),
        {"item_id": item_id},
    ).mappings()
    return [dict(r) for r in rows]


def get_counts_for_items(session: Session, item_ids: list[UUID]) -> list[dict[str, Any]]:
    if not item_ids:
        return []
    rows = session.execute(
        text(
            """
            select c.id, c.gs_item_id, c.field_id, c.field_code, c.label_snapshot,
                   c.qty, c.created_at, c.updated_at
              from public.gs_item_counts c
             where c.gs_item_id = any(:ids)
             order by c.gs_item_id, c.created_at
            """
        ),
        {"ids": item_ids},
    ).mappings()
    return [dict(r) for r in rows]


def upsert_item_count(session: Session, item_id: UUID, field_id: UUID, qty: int, by: UUID) -> UUID:
    res = session.execute(
        text(
            """
            insert into public.gs_item_counts (gs_item_id, field_id, qty, created_by)
            values (:item_id, :field_id, :qty, :by)
            on conflict (gs_item_id, field_id) do update
               set qty = excluded.qty, updated_at = now()
            returning id
            """
        ),
        {"item_id": item_id, "field_id": field_id, "qty": qty, "by": by},
    ).scalar_one()
    return UUID(str(res))


def delete_item_counts(session: Session, item_id: UUID) -> None:
    session.execute(
        text("delete from public.gs_item_counts where gs_item_id = :item_id"),
        {"item_id": item_id},
    )


def complete_open_tasks(session: Session, gs_id: UUID) -> int:
    res = session.execute(
        text(
            """
            update public.workflow_tasks
               set status = 'DONE', completed_at = now()
             where gs_id = :gs_id and status = 'OPEN'
            """
        ),
        {"gs_id": gs_id},
    )
    return int(getattr(res, "rowcount", 0))
