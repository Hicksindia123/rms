"""Stage-4 Dismantling database repository (BR-26..BR-29, G-11, DEC-18, DEC-19, DEC-11)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.inventory import ledger_service


def get_location_by_code(session: Session, code: str) -> dict[str, Any] | None:
    stmt = text(
        """
        select id, code, name, location_class
        from public.inventory_locations
        where code = :code and is_active = true
        """
    )
    row = session.execute(stmt, {"code": code}).mappings().first()
    return dict(row) if row else None


def get_dismantling_queue_lots(session: Session) -> list[dict[str, Any]]:
    """Fetch all lots in NON_FUNCTIONAL_STORE that are candidates for dismantling or disposal."""
    stmt = text(
        """
        select
          l.id as lot_id,
          l.stock_item_id,
          si.product_id,
          p.name as product_name,
          p.code as product_sku,
          pc.id as category_id,
          pc.code as category_code,
          pc.name as category_name,
          coalesce(pc.supports_dismantling, false) as supports_dismantling,
          l.condition_class,
          l.source_condition_code,
          l.routing_hint,
          l.requires_evaluation,
          b.qty,
          gs.gs_no
        from public.stock_balances b
        join public.stock_lots l on l.id = b.lot_id
        join public.inventory_locations loc on loc.id = b.location_id
        join public.stock_items si on si.id = l.stock_item_id
        left join public.products p on p.id = si.product_id
        left join public.product_categories pc on pc.id = p.category_id
        left join public.goods_slips gs on gs.id = l.gs_id
        where loc.code = 'NON_FUNCTIONAL_STORE'
          and b.qty > 0
          and l.condition_class in ('NON_GOOD', 'NON_SELLABLE')
        order by l.created_at asc
        """
    )
    rows = session.execute(stmt).mappings().all()
    return [dict(r) for r in rows]


def get_lot_balance(session: Session, lot_id: UUID, location_id: UUID) -> int:
    stmt = text(
        """
        select coalesce(qty, 0)
        from public.stock_balances
        where lot_id = :lot_id and location_id = :location_id
        """
    )
    val = session.execute(stmt, {"lot_id": lot_id, "location_id": location_id}).scalar()
    return int(val) if val is not None else 0


def get_lot_details(session: Session, lot_id: UUID) -> dict[str, Any] | None:
    stmt = text(
        """
        select
          l.id as lot_id,
          l.stock_item_id,
          l.condition_class,
          si.item_kind,
          si.product_id,
          p.name as product_name,
          coalesce(pc.supports_dismantling, false) as supports_dismantling
        from public.stock_lots l
        join public.stock_items si on si.id = l.stock_item_id
        left join public.products p on p.id = si.product_id
        left join public.product_categories pc on pc.id = p.category_id
        where l.id = :lot_id
        """
    )
    row = session.execute(stmt, {"lot_id": lot_id}).mappings().first()
    return dict(row) if row else None


def next_dismantle_batch_no(session: Session) -> str:
    stmt = text("select rms_private.next_number('DISMANTLE') as batch_no")
    return str(session.execute(stmt).scalar_one())


def create_dismantle_batch(
    session: Session,
    *,
    batch_no: str,
    technician_profile_id: UUID,
    storage_method_code: str,
    total_input_qty: int,
    created_by: UUID,
) -> dict[str, Any]:
    stmt = text(
        """
        insert into public.dismantle_batches (
          batch_no, technician_profile_id, storage_method_code,
          status, total_input_qty, total_dismantled_qty, created_by
        ) values (
          :batch_no, :technician_profile_id, :storage_method_code,
          'OPEN', :total_input_qty, 0, :created_by
        )
        returning id, batch_no, technician_profile_id, storage_method_code,
                  status, total_input_qty, total_dismantled_qty, created_at, completed_at
        """
    )
    row = (
        session.execute(
            stmt,
            {
                "batch_no": batch_no,
                "technician_profile_id": technician_profile_id,
                "storage_method_code": storage_method_code,
                "total_input_qty": total_input_qty,
                "created_by": created_by,
            },
        )
        .mappings()
        .first()
    )
    return dict(row) if row else {}


def create_dismantle_input(
    session: Session,
    *,
    batch_id: UUID,
    lot_id: UUID,
    qty: int,
    stock_movement_id: UUID | None,
    created_by: UUID,
) -> dict[str, Any]:
    stmt = text(
        """
        insert into public.dismantle_inputs (
          batch_id, lot_id, qty, stock_movement_id, created_by
        ) values (
          :batch_id, :lot_id, :qty, :stock_movement_id, :created_by
        )
        returning id, batch_id, lot_id, qty, stock_movement_id, created_at
        """
    )
    row = (
        session.execute(
            stmt,
            {
                "batch_id": batch_id,
                "lot_id": lot_id,
                "qty": qty,
                "stock_movement_id": stock_movement_id,
                "created_by": created_by,
            },
        )
        .mappings()
        .first()
    )
    return dict(row) if row else {}


def get_batch(session: Session, batch_id: UUID) -> dict[str, Any] | None:
    stmt = text(
        """
        select
          b.id,
          b.batch_no,
          b.technician_profile_id,
          p.full_name as technician_name,
          b.storage_method_code,
          b.status,
          b.total_input_qty,
          b.total_dismantled_qty,
          b.created_at,
          b.completed_at
        from public.dismantle_batches b
        join public.profiles p on p.id = b.technician_profile_id
        where b.id = :batch_id
        """
    )
    row = session.execute(stmt, {"batch_id": batch_id}).mappings().first()
    return dict(row) if row else None


def list_batches(
    session: Session,
    *,
    status: str | None = None,
    technician_profile_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    stmt = text(
        """
        select
          b.id,
          b.batch_no,
          b.technician_profile_id,
          p.full_name as technician_name,
          b.storage_method_code,
          b.status,
          b.total_input_qty,
          b.total_dismantled_qty,
          b.created_at,
          b.completed_at
        from public.dismantle_batches b
        join public.profiles p on p.id = b.technician_profile_id
        where (cast(:status as text) is null or b.status = cast(:status as text))
          and (cast(:tech_id as uuid) is null or b.technician_profile_id = cast(:tech_id as uuid))
        order by b.created_at desc
        limit :limit offset :offset
        """
    )
    rows = (
        session.execute(
            stmt,
            {
                "status": status,
                "tech_id": technician_profile_id,
                "limit": limit,
                "offset": offset,
            },
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def get_batch_inputs(session: Session, batch_id: UUID) -> list[dict[str, Any]]:
    stmt = text(
        """
        select
          di.id,
          di.batch_id,
          di.lot_id,
          p.name as product_name,
          di.qty,
          di.stock_movement_id,
          di.created_at
        from public.dismantle_inputs di
        join public.stock_lots sl on sl.id = di.lot_id
        join public.stock_items si on si.id = sl.stock_item_id
        left join public.products p on p.id = si.product_id
        where di.batch_id = :batch_id
        order by di.created_at asc
        """
    )
    rows = session.execute(stmt, {"batch_id": batch_id}).mappings().all()
    return [dict(r) for r in rows]


def get_recovered_parts(session: Session, batch_id: UUID) -> list[dict[str, Any]]:
    stmt = text(
        """
        select
          rp.id,
          rp.batch_id,
          rp.part_type,
          rp.qty,
          rp.pcb_model_id,
          pm.name as pcb_model_name,
          rp.pcb_supplier_id,
          ps.name as pcb_supplier_name,
          rp.container_id,
          sc.code as container_code,
          rp.partition_id,
          cp.compartment_code as partition_code,
          rp.lot_id,
          rp.stock_movement_id,
          rp.created_at
        from public.recovered_parts rp
        left join public.pcb_models pm on pm.id = rp.pcb_model_id
        left join public.pcb_suppliers ps on ps.id = rp.pcb_supplier_id
        left join public.storage_containers sc on sc.id = rp.container_id
        left join public.container_partitions cp on cp.id = rp.partition_id
        where rp.batch_id = :batch_id
        order by rp.created_at asc
        """
    )
    rows = session.execute(stmt, {"batch_id": batch_id}).mappings().all()
    return [dict(r) for r in rows]


def get_scrap_records(
    session: Session,
    *,
    batch_id: UUID | None = None,
    disposal_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    stmt = text(
        """
        select
          sr.id,
          sr.batch_id,
          db.batch_no,
          sr.lot_id,
          sr.qty_pieces,
          cast(sr.weight_kg as double precision) as weight_kg,
          sr.hazardous,
          sr.remarks,
          sr.disposal_status,
          sr.manifest_ref,
          sr.disposed_at,
          sr.disposed_by,
          p.full_name as disposed_by_name,
          sr.stock_movement_id,
          sr.created_at
        from public.scrap_records sr
        left join public.dismantle_batches db on db.id = sr.batch_id
        left join public.profiles p on p.id = sr.disposed_by
        where (cast(:batch_id as uuid) is null or sr.batch_id = cast(:batch_id as uuid))
          and (
            cast(:disposal_status as text) is null
            or sr.disposal_status = cast(:disposal_status as text)
          )
        order by sr.created_at desc
        limit :limit offset :offset
        """
    )
    rows = (
        session.execute(
            stmt,
            {
                "batch_id": batch_id,
                "disposal_status": disposal_status,
                "limit": limit,
                "offset": offset,
            },
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def get_scrap_record(session: Session, scrap_id: UUID) -> dict[str, Any] | None:
    stmt = text(
        """
        select
          sr.id,
          sr.batch_id,
          db.batch_no,
          sr.lot_id,
          sr.qty_pieces,
          cast(sr.weight_kg as double precision) as weight_kg,
          sr.hazardous,
          sr.remarks,
          sr.disposal_status,
          sr.manifest_ref,
          sr.disposed_at,
          sr.disposed_by,
          p.full_name as disposed_by_name,
          sr.stock_movement_id,
          sr.created_at
        from public.scrap_records sr
        left join public.dismantle_batches db on db.id = sr.batch_id
        left join public.profiles p on p.id = sr.disposed_by
        where sr.id = :scrap_id
        """
    )
    row = session.execute(stmt, {"scrap_id": scrap_id}).mappings().first()
    return dict(row) if row else None


def create_recovered_part(
    session: Session,
    *,
    batch_id: UUID,
    part_type: str,
    qty: int,
    pcb_model_id: UUID | None,
    pcb_supplier_id: UUID | None,
    container_id: UUID | None,
    partition_id: UUID | None,
    lot_id: UUID | None,
    stock_movement_id: UUID | None,
    created_by: UUID,
) -> dict[str, Any]:
    stmt = text(
        """
        insert into public.recovered_parts (
          batch_id, part_type, qty, pcb_model_id, pcb_supplier_id,
          container_id, partition_id, lot_id, stock_movement_id, created_by
        ) values (
          :batch_id, :part_type, :qty, :pcb_model_id, :pcb_supplier_id,
          :container_id, :partition_id, :lot_id, :stock_movement_id, :created_by
        )
        returning id, batch_id, part_type, qty, pcb_model_id, pcb_supplier_id,
                  container_id, partition_id, lot_id, stock_movement_id, created_at
        """
    )
    row = (
        session.execute(
            stmt,
            {
                "batch_id": batch_id,
                "part_type": part_type,
                "qty": qty,
                "pcb_model_id": pcb_model_id,
                "pcb_supplier_id": pcb_supplier_id,
                "container_id": container_id,
                "partition_id": partition_id,
                "lot_id": lot_id,
                "stock_movement_id": stock_movement_id,
                "created_by": created_by,
            },
        )
        .mappings()
        .first()
    )
    return dict(row) if row else {}


def create_scrap_record(
    session: Session,
    *,
    batch_id: UUID | None,
    lot_id: UUID | None,
    qty_pieces: int,
    weight_kg: float | None,
    hazardous: bool,
    remarks: str | None,
    created_by: UUID,
) -> dict[str, Any]:
    stmt = text(
        """
        insert into public.scrap_records (
          batch_id, lot_id, qty_pieces, weight_kg, hazardous, remarks,
          disposal_status, created_by
        ) values (
          :batch_id, :lot_id, :qty_pieces, :weight_kg, :hazardous, :remarks,
          'MARKED', :created_by
        )
        returning id, batch_id, lot_id, qty_pieces, weight_kg, hazardous, remarks,
                  disposal_status, created_at
        """
    )
    row = (
        session.execute(
            stmt,
            {
                "batch_id": batch_id,
                "lot_id": lot_id,
                "qty_pieces": qty_pieces,
                "weight_kg": weight_kg,
                "hazardous": hazardous,
                "remarks": remarks,
                "created_by": created_by,
            },
        )
        .mappings()
        .first()
    )
    return dict(row) if row else {}


def update_batch_progress(
    session: Session,
    *,
    batch_id: UUID,
    additional_dismantled_qty: int,
    mark_completed: bool,
) -> dict[str, Any]:
    if mark_completed:
        stmt = text(
            """
            update public.dismantle_batches
            set total_dismantled_qty = total_dismantled_qty + :add_qty,
                completed_at = now(),
                status = 'COMPLETED'
            where id = :batch_id
            returning id, batch_no, technician_profile_id, storage_method_code,
                      status, total_input_qty, total_dismantled_qty, created_at, completed_at
            """
        )
    else:
        stmt = text(
            """
            update public.dismantle_batches
            set total_dismantled_qty = total_dismantled_qty + :add_qty
            where id = :batch_id
            returning id, batch_no, technician_profile_id, storage_method_code,
                      status, total_input_qty, total_dismantled_qty, created_at, completed_at
            """
        )
    row = (
        session.execute(
            stmt,
            {
                "batch_id": batch_id,
                "add_qty": additional_dismantled_qty,
            },
        )
        .mappings()
        .first()
    )
    return dict(row) if row else {}


def get_disposable_lot(session: Session, lot_id: UUID) -> dict[str, Any] | None:
    """The lot with its stock in a disposal-eligible location (DEC-11 / DEC-18), locked."""
    stmt = text(
        """
        select l.id as lot_id, l.condition_class, l.gs_id,
               coalesce(pc.supports_dismantling, false) as supports_dismantling,
               il.id as location_id, il.code as location_code, b.qty as balance,
               coalesce((select sum(sr.qty_pieces) from public.scrap_records sr
                          where sr.lot_id = l.id and sr.disposal_status = 'MARKED'), 0)::int
                 as marked_qty
          from public.stock_lots l
          join public.stock_balances b on b.lot_id = l.id and b.qty > 0
          join public.inventory_locations il on il.id = b.location_id
          left join public.gs_items gi on gi.id = l.gs_item_id
          left join public.products pr on pr.id = gi.product_id
          left join public.product_categories pc on pc.id = pr.category_id
         where l.id = :lot_id
           and il.code in ('HAZARD_QUARANTINE', 'NON_FUNCTIONAL_STORE')
         order by il.code
         limit 1
           for update of b
        """
    )
    row = session.execute(stmt, {"lot_id": lot_id}).mappings().first()
    return dict(row) if row else None


def get_location_id(session: Session, code: str) -> UUID | None:
    row = session.execute(
        text("select id from public.inventory_locations where code = :c"), {"c": code}
    ).first()
    return UUID(str(row[0])) if row else None


def update_scrap_disposed(
    session: Session,
    *,
    scrap_id: UUID,
    manifest_ref: str | None,
    disposed_at: datetime,
    disposed_by: UUID,
    stock_movement_id: UUID | None = None,
) -> dict[str, Any]:
    stmt = text(
        """
        update public.scrap_records
        set disposal_status = 'DISPOSED',
            manifest_ref = :manifest_ref,
            disposed_at = :disposed_at,
            disposed_by = :disposed_by,
            stock_movement_id = :stock_movement_id
        where id = :scrap_id
        returning id, batch_id, lot_id, qty_pieces, weight_kg, hazardous, remarks,
                  disposal_status, manifest_ref, disposed_at, disposed_by, created_at
        """
    )
    row = (
        session.execute(
            stmt,
            {
                "scrap_id": scrap_id,
                "manifest_ref": manifest_ref,
                "disposed_at": disposed_at,
                "disposed_by": disposed_by,
                "stock_movement_id": stock_movement_id,
            },
        )
        .mappings()
        .first()
    )
    return dict(row) if row else {}


def get_storage_container(session: Session, container_id: UUID) -> dict[str, Any] | None:
    stmt = text(
        """
        select id, code, barcode, name, container_type, storage_method,
               dedicated_part_type, location_id, is_active
        from public.storage_containers
        where id = :container_id
        """
    )
    row = session.execute(stmt, {"container_id": container_id}).mappings().first()
    return dict(row) if row else None


def get_container_partition(session: Session, partition_id: UUID) -> dict[str, Any] | None:
    stmt = text(
        """
        select cp.id, cp.container_id, cp.compartment_code, cp.part_type, cp.is_active,
               sc.storage_method
        from public.container_partitions cp
        join public.storage_containers sc on sc.id = cp.container_id
        where cp.id = :partition_id
        """
    )
    row = session.execute(stmt, {"partition_id": partition_id}).mappings().first()
    return dict(row) if row else None


def list_containers(
    session: Session,
    *,
    storage_method: str | None = None,
    part_type: str | None = None,
) -> list[dict[str, Any]]:
    stmt = text(
        """
        select
          sc.id, sc.code, sc.barcode, sc.name, sc.container_type,
          sc.storage_method, sc.dedicated_part_type, sc.location_id, sc.is_active
        from public.storage_containers sc
        where sc.container_type = 'PARTS'
          and sc.is_active = true
          and (
            cast(:storage_method as text) is null
            or sc.storage_method = cast(:storage_method as text)
          )
          and (
            cast(:part_type as text) is null
            or sc.dedicated_part_type = cast(:part_type as text)
            or sc.storage_method = 'PARTITIONED_CONTAINER'
          )
        order by sc.code asc
        """
    )
    containers = [
        dict(r)
        for r in session.execute(
            stmt,
            {
                "storage_method": storage_method,
                "part_type": part_type,
            },
        )
        .mappings()
        .all()
    ]

    if not containers:
        return []

    c_ids = [c["id"] for c in containers]
    part_stmt = text(
        """
        select id, container_id, compartment_code, part_type, is_active
        from public.container_partitions
        where container_id = any(:c_ids) and is_active = true
        order by compartment_code asc
        """
    )
    part_rows = session.execute(part_stmt, {"c_ids": c_ids}).mappings().all()
    part_map: dict[UUID, list[dict[str, Any]]] = {}
    for p in part_rows:
        cid = p["container_id"]
        part_map.setdefault(cid, []).append(dict(p))

    for c in containers:
        c["partitions"] = part_map.get(c["id"], [])

    return containers


def list_pcb_models(session: Session) -> list[dict[str, Any]]:
    stmt = text(
        """
        select m.id, m.name, m.supplier_id, s.name as supplier_name, m.is_active
        from public.pcb_models m
        left join public.pcb_suppliers s on s.id = m.supplier_id
        where m.is_active = true
        order by m.name asc
        """
    )
    rows = session.execute(stmt).mappings().all()
    return [dict(r) for r in rows]


def create_pcb_model(
    session: Session,
    *,
    name: str,
    supplier_id: UUID,
    is_active: bool,
    actor_id: UUID | None,
) -> dict[str, Any]:
    stmt = text(
        """
        insert into public.pcb_models (name, supplier_id, is_active, created_by)
        values (:name, :supplier_id, :is_active, :created_by)
        returning id, name, supplier_id, is_active
        """
    )
    row = (
        session.execute(
            stmt,
            {
                "name": name,
                "supplier_id": supplier_id,
                "is_active": is_active,
                "created_by": actor_id,
            },
        )
        .mappings()
        .first()
    )
    return dict(row) if row else {}


def list_pcb_suppliers(session: Session) -> list[dict[str, Any]]:
    stmt = text(
        """
        select id, name, is_active
        from public.pcb_suppliers
        where is_active = true
        order by name asc
        """
    )
    rows = session.execute(stmt).mappings().all()
    return [dict(r) for r in rows]


def create_pcb_supplier(
    session: Session,
    *,
    name: str,
    is_active: bool,
    actor_id: UUID | None,
) -> dict[str, Any]:
    stmt = text(
        """
        insert into public.pcb_suppliers (name, is_active, created_by)
        values (:name, :is_active, :created_by)
        returning id, name, is_active
        """
    )
    row = (
        session.execute(
            stmt,
            {
                "name": name,
                "is_active": is_active,
                "created_by": actor_id,
            },
        )
        .mappings()
        .first()
    )
    return dict(row) if row else {}


def find_or_create_spare_part_item(
    session: Session,
    *,
    part_type: str,
    pcb_model_id: UUID | None,
    pcb_supplier_id: UUID | None,
    actor_id: UUID | None,
) -> UUID:
    """Find existing catalog stock item for this spare part or create one."""
    if part_type == "PCB":
        stmt = text(
            """
            select id from public.stock_items
            where item_kind = 'SPARE_PART'
              and part_type = 'PCB'
              and pcb_model_id = :model_id
              and pcb_supplier_id = :supplier_id
            limit 1
            """
        )
        existing = session.execute(
            stmt, {"model_id": pcb_model_id, "supplier_id": pcb_supplier_id}
        ).scalar()
    else:
        stmt = text(
            """
            select id from public.stock_items
            where item_kind = 'SPARE_PART'
              and part_type = :part_type
              and pcb_model_id is null
              and pcb_supplier_id is null
            limit 1
            """
        )
        existing = session.execute(stmt, {"part_type": part_type}).scalar()

    if existing:
        return UUID(str(existing))

    return ledger_service.create_stock_item(
        session,
        item_kind="SPARE_PART",
        part_type=part_type,
        pcb_model_id=pcb_model_id,
        pcb_supplier_id=pcb_supplier_id,
        created_by=actor_id,
    )
