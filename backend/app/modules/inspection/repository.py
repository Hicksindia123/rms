"""Inspection repository: SQL only, no business rules (P2-05)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

_SELECT_GS = """
select id, gs_no, status, category_code, original_category_code,
       workflow_version_id, has_hazard, has_rejections, has_open_pendency
from public.goods_slips
where id = :gs_id
"""


def get_goods_slip(
    session: Session,
    gs_id: UUID,
    *,
    for_update: bool = False,
) -> dict[str, Any] | None:
    query = f"{_SELECT_GS} for update" if for_update else _SELECT_GS
    stmt = text(query)
    row = session.execute(stmt, {"gs_id": gs_id}).mappings().first()
    return dict(row) if row else None


def get_gs_items(session: Session, gs_id: UUID) -> list[dict[str, Any]]:
    stmt = text(
        """
        select gi.id as gs_item_id, gi.gs_id, gi.line_no, gi.product_id, gi.category_id,
               gi.product_code_snapshot as product_code, gi.product_name_snapshot as product_name,
               gi.category_code_snapshot as category_code, pc.name as category_name,
               gi.documented_qty, gi.received_qty, gi.short_qty, gi.excess_qty,
               pc.requires_full_opening, pc.condition_option_set_id
        from public.gs_items gi
        join public.product_categories pc on pc.id = gi.category_id
        where gi.gs_id = :gs_id
        order by gi.line_no
        """
    )
    rows = session.execute(stmt, {"gs_id": gs_id}).mappings().all()
    return [dict(r) for r in rows]


def get_gs_item(session: Session, gs_item_id: UUID) -> dict[str, Any] | None:
    stmt = text(
        """
        select gi.id as gs_item_id, gi.gs_id, gi.line_no, gi.product_id, gi.category_id,
               gi.product_code_snapshot as product_code, gi.product_name_snapshot as product_name,
               gi.category_code_snapshot as category_code, pc.name as category_name,
               gi.documented_qty, gi.received_qty, gi.short_qty, gi.excess_qty,
               pc.requires_full_opening, pc.condition_option_set_id
        from public.gs_items gi
        join public.product_categories pc on pc.id = gi.category_id
        where gi.id = :gs_item_id
        """
    )
    row = session.execute(stmt, {"gs_item_id": gs_item_id}).mappings().first()
    return dict(row) if row else None


def get_condition_options(session: Session, option_set_id: UUID | None) -> list[dict[str, Any]]:
    if not option_set_id:
        return []
    stmt = text(
        """
        select id, code, label, allowed_status, system_behavior,
               rule_text, next_action_text, remarks, sort_order
        from public.option_items
        where option_set_id = :option_set_id and is_active = true
        order by sort_order, code
        """
    )
    rows = session.execute(stmt, {"option_set_id": option_set_id}).mappings().all()
    return [dict(r) for r in rows]


def get_option_item_by_code(
    session: Session,
    option_set_id: UUID,
    code: str,
) -> dict[str, Any] | None:
    stmt = text(
        """
        select id, code, label, allowed_status, system_behavior,
               rule_text, next_action_text, remarks
        from public.option_items
        where option_set_id = :option_set_id and code = :code
        """
    )
    row = session.execute(stmt, {"option_set_id": option_set_id, "code": code}).mappings().first()
    return dict(row) if row else None


def get_inspection_details(session: Session, gs_item_id: UUID) -> dict[str, Any] | None:
    stmt = text(
        """
        select i.id as inspection_id, i.gs_item_id, i.form_version_id,
               i.full_opening_confirmed, i.status as inspection_status,
               i.inspected_by, p_ins.full_name as inspected_by_name, i.inspected_at,
               i.reopened_by, p_reop.full_name as reopened_by_name, i.reopened_at, i.reopen_reason
        from public.inspections i
        left join public.profiles p_ins on p_ins.id = i.inspected_by
        left join public.profiles p_reop on p_reop.id = i.reopened_by
        where i.gs_item_id = :gs_item_id
        """
    )
    row = session.execute(stmt, {"gs_item_id": gs_item_id}).mappings().first()
    return dict(row) if row else None


def get_allocations_for_inspection(session: Session, inspection_id: UUID) -> list[dict[str, Any]]:
    stmt = text(
        """
        select ia.id, ia.inspection_id, ia.condition_code, ia.qty,
               coalesce(ia.allowed_status_snapshot, oi.allowed_status) as allowed_status,
               coalesce(ia.system_behavior_snapshot, oi.system_behavior) as system_behavior,
               coalesce(ia.label_snapshot, oi.label) as label
        from public.inspection_allocations ia
        left join public.option_items oi on oi.id = ia.option_item_id
        where ia.inspection_id = :inspection_id
        order by ia.condition_code
        """
    )
    rows = session.execute(stmt, {"inspection_id": inspection_id}).mappings().all()
    return [dict(r) for r in rows]


def get_extraction_for_item(session: Session, gs_item_id: UUID) -> dict[str, Any] | None:
    stmt = text(
        """
        select id, gs_item_id, primary_type, packaging_qty, container_qty, reconciled
        from public.extraction_records
        where gs_item_id = :gs_item_id
        """
    )
    row = session.execute(stmt, {"gs_item_id": gs_item_id}).mappings().first()
    return dict(row) if row else None


def get_rejections_for_item(session: Session, gs_item_id: UUID) -> list[dict[str, Any]]:
    stmt = text(
        """
        select id, gs_item_id, condition_code, qty, disposition, hazard, stock_movement_id
        from public.rejections
        where gs_item_id = :gs_item_id
        order by created_at
        """
    )
    rows = session.execute(stmt, {"gs_item_id": gs_item_id}).mappings().all()
    return [dict(r) for r in rows]


def get_published_inspection_form_version(
    session: Session, condition_option_set_id: UUID | None
) -> UUID | None:
    """The published Step-3 inspection form whose fields use this category's condition set."""
    if condition_option_set_id is None:
        return None
    res = session.execute(
        text(
            """
            select v.id
              from public.form_versions v
              join public.form_definitions d on d.id = v.form_definition_id
              join public.form_fields f on f.form_version_id = v.id
             where d.step_code = 'S1_INSPECT'
               and v.status = 'PUBLISHED'
               and f.option_set_id = :set_id
             order by v.published_at desc nulls last
             limit 1
            """
        ),
        {"set_id": condition_option_set_id},
    ).scalar_one_or_none()
    return UUID(str(res)) if res else None


def get_form_version_option_labels(
    session: Session, form_version_id: UUID, condition_option_set_id: UUID | None
) -> dict[str, str]:
    """Option labels frozen in a form version snapshot for the given option set (G-18)."""
    rows = session.execute(
        text(
            """
            select o ->> 'code' as code, o ->> 'label' as label
              from public.form_versions v,
                   lateral jsonb_array_elements(v.snapshot -> 'fields') f,
                   lateral jsonb_array_elements(coalesce(f -> 'option_items', '[]'::jsonb)) o
             where v.id = :version_id
               and f ->> 'option_set_id' = cast(:set_id as text)
            """
        ),
        {"version_id": form_version_id, "set_id": condition_option_set_id},
    ).mappings()
    return {str(r["code"]): str(r["label"]) for r in rows if r["code"] and r["label"]}


def upsert_inspection(
    session: Session,
    *,
    gs_item_id: UUID,
    full_opening_confirmed: bool,
    form_version_id: UUID | None = None,
    inspected_by: UUID | None = None,
) -> UUID:
    # G-18: the form version is pinned when the inspection is created and never re-pinned.
    stmt = text(
        """
        insert into public.inspections (
          gs_item_id, form_version_id, full_opening_confirmed, status, inspected_by
        ) values (
          :gs_item_id, :form_version_id, :full_opening_confirmed, 'DRAFT', :inspected_by
        )
        on conflict (gs_item_id) do update
          set full_opening_confirmed = excluded.full_opening_confirmed,
              form_version_id = coalesce(public.inspections.form_version_id,
                                         excluded.form_version_id),
              updated_at = now()
        returning id
        """
    )
    res = session.execute(
        stmt,
        {
            "gs_item_id": gs_item_id,
            "form_version_id": form_version_id,
            "full_opening_confirmed": full_opening_confirmed,
            "inspected_by": inspected_by,
        },
    ).scalar_one()
    return UUID(str(res))


def replace_allocations(
    session: Session,
    *,
    inspection_id: UUID,
    allocations_data: list[dict[str, Any]],
) -> None:
    session.execute(
        text("delete from public.inspection_allocations where inspection_id = :inspection_id"),
        {"inspection_id": inspection_id},
    )

    if allocations_data:
        stmt = text(
            """
            insert into public.inspection_allocations (
              inspection_id, condition_code, option_item_id, qty,
              allowed_status_snapshot, system_behavior_snapshot, label_snapshot
            ) values (
              :inspection_id, :condition_code, :option_item_id, :qty,
              :allowed_status_snapshot, :system_behavior_snapshot, :label_snapshot
            )
            """
        )
        session.execute(
            stmt,
            [
                {
                    "inspection_id": inspection_id,
                    "condition_code": a["condition_code"],
                    "option_item_id": a.get("option_item_id"),
                    "qty": a["qty"],
                    "allowed_status_snapshot": a.get("allowed_status_snapshot"),
                    "system_behavior_snapshot": a.get("system_behavior_snapshot"),
                    "label_snapshot": a.get("label_snapshot"),
                }
                for a in allocations_data
            ],
        )


def upsert_extraction_record(
    session: Session,
    *,
    gs_item_id: UUID,
    primary_type: str,
    packaging_qty: int,
    container_qty: int,
    reconciled: bool,
    created_by: UUID | None = None,
) -> UUID:
    stmt = text(
        """
        insert into public.extraction_records (
          gs_item_id, primary_type, packaging_qty, container_qty, reconciled, created_by
        ) values (
          :gs_item_id, :primary_type, :packaging_qty, :container_qty, :reconciled, :created_by
        )
        on conflict (gs_item_id) do update
          set primary_type = excluded.primary_type,
              packaging_qty = excluded.packaging_qty,
              container_qty = excluded.container_qty,
              reconciled = excluded.reconciled
        returning id
        """
    )
    res = session.execute(
        stmt,
        {
            "gs_item_id": gs_item_id,
            "primary_type": primary_type,
            "packaging_qty": packaging_qty,
            "container_qty": container_qty,
            "reconciled": reconciled,
            "created_by": created_by,
        },
    ).scalar_one()
    return UUID(str(res))


def set_inspection_status_final(
    session: Session,
    *,
    inspection_id: UUID,
    inspected_by: UUID | None,
) -> None:
    stmt = text(
        """
        update public.inspections
        set status = 'FINAL',
            inspected_by = :inspected_by,
            inspected_at = now(),
            updated_at = now()
        where id = :inspection_id
        """
    )
    session.execute(stmt, {"inspection_id": inspection_id, "inspected_by": inspected_by})


def reopen_inspection_db(
    session: Session,
    *,
    inspection_id: UUID,
    reopened_by: UUID | None,
    reopen_reason: str,
) -> None:
    stmt = text(
        """
        update public.inspections
        set status = 'DRAFT',
            reopened_by = :reopened_by,
            reopened_at = now(),
            reopen_reason = :reopen_reason,
            updated_at = now()
        where id = :inspection_id
        """
    )
    session.execute(
        stmt,
        {
            "inspection_id": inspection_id,
            "reopened_by": reopened_by,
            "reopen_reason": reopen_reason,
        },
    )


def create_rejection(
    session: Session,
    *,
    gs_item_id: UUID,
    condition_code: str,
    qty: int,
    disposition: str,
    hazard: bool,
    stock_movement_id: UUID | None,
    created_by: UUID | None = None,
) -> UUID:
    stmt = text(
        """
        insert into public.rejections (
          gs_item_id, condition_code, qty, disposition, hazard, stock_movement_id, created_by
        ) values (
          :gs_item_id, :condition_code, :qty, :disposition, :hazard, :stock_movement_id, :created_by
        )
        returning id
        """
    )
    res = session.execute(
        stmt,
        {
            "gs_item_id": gs_item_id,
            "condition_code": condition_code,
            "qty": qty,
            "disposition": disposition,
            "hazard": hazard,
            "stock_movement_id": stock_movement_id,
            "created_by": created_by,
        },
    ).scalar_one()
    return UUID(str(res))


def delete_rejections_for_item(session: Session, gs_item_id: UUID) -> int:
    res = session.execute(
        text("delete from public.rejections where gs_item_id = :gs_item_id"),
        {"gs_item_id": gs_item_id},
    )
    return int(getattr(res, "rowcount", 0))


def get_initial_lot_for_item(session: Session, gs_item_id: UUID) -> dict[str, Any] | None:
    stmt = text(
        """
        select id, stock_item_id, gs_id, gs_item_id, condition_class, source_condition_code
        from public.stock_lots
        where gs_item_id = :gs_item_id
          and condition_class = 'AS_RECEIVED'
          and source_condition_code is null
        limit 1
        """
    )
    row = session.execute(stmt, {"gs_item_id": gs_item_id}).mappings().first()
    return dict(row) if row else None


def get_lots_for_item(session: Session, gs_item_id: UUID) -> list[dict[str, Any]]:
    stmt = text(
        """
        select id, stock_item_id, gs_id, gs_item_id, condition_class,
               source_condition_code, requires_evaluation, routing_hint
        from public.stock_lots
        where gs_item_id = :gs_item_id
        """
    )
    rows = session.execute(stmt, {"gs_item_id": gs_item_id}).mappings().all()
    return [dict(r) for r in rows]


def get_location_by_code(session: Session, code: str) -> dict[str, Any] | None:
    stmt = text(
        """
        select id, code, name, location_class
        from public.inventory_locations
        where code = :code
        """
    )
    row = session.execute(stmt, {"code": code}).mappings().first()
    return dict(row) if row else None


def get_system_setting(session: Session, key: str) -> Any | None:
    stmt = text("select value from public.system_settings where key = :key")
    return session.execute(stmt, {"key": key}).scalar_one_or_none()


def update_gs_flags(
    session: Session,
    *,
    gs_id: UUID,
    has_hazard: bool | None = None,
    has_rejections: bool | None = None,
) -> None:
    stmt = text(
        """
        update public.goods_slips
        set has_hazard = coalesce(:has_hazard, has_hazard),
            has_rejections = coalesce(:has_rejections, has_rejections),
            updated_at = now()
        where id = :gs_id
        """
    )
    session.execute(
        stmt,
        {
            "gs_id": gs_id,
            "has_hazard": has_hazard,
            "has_rejections": has_rejections,
        },
    )


def get_safety_notification_recipients(session: Session) -> list[UUID]:
    stmt = text(
        """
        select distinct p.id
        from public.profiles p
        join public.user_roles ur on ur.user_id = p.id
        join public.roles r on r.id = ur.role_id
        where r.code in ('REPLACEMENT_MANAGER', 'SPARE_PARTS_MANAGER', 'SUPER_ADMIN')
          and p.is_active = true
        """
    )
    rows = session.execute(stmt).scalars().all()
    return [UUID(str(uid)) for uid in rows]


def has_downstream_custody_transfer(session: Session, gs_id: UUID) -> bool:
    stmt = text(
        """
        select exists (
          select 1 from public.custody_transfers where gs_id = :gs_id
        )
        """
    )
    return bool(session.execute(stmt, {"gs_id": gs_id}).scalar_one())
