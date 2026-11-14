"""P3-04 inventory repository: SQL only, no business rules (CLAUDE.md rule g).

Stock never changes here: movements go through `ledger_service` (rms_move_stock, rule f).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

# View → location class / condition filter. Fixed SQL fragments (no client text); BR-30 / G-12:
# the functional view only ever selects functional conditions in FUNCTIONAL locations.
VIEW_FILTERS: Mapping[str, str] = {
    "FUNCTIONAL": (
        "l.location_class = 'FUNCTIONAL' and si.item_kind = 'FINISHED_GOOD' "
        "and lot.condition_class in ('AS_RECEIVED','FUNCTIONAL_GOOD','FUNCTIONAL_REPAIRED')"
    ),
    "NON_FUNCTIONAL": "l.location_class = 'NON_FUNCTIONAL' and lot.condition_class <> 'SALVAGED'",
    "SPARE_PARTS": "l.location_class = 'SPARE_PARTS' and lot.condition_class = 'SALVAGED'",
    "BATTERIES": "l.location_class = 'SPARE_PARTS' and si.item_kind = 'BATTERY'",
    "REJECTED_HOLD": "l.location_class = 'REJECTED_HOLD'",
    "HAZARD_QUARANTINE": "l.location_class = 'HAZARD_QUARANTINE'",
    "PENDING_HOLD": "l.location_class = 'PENDING_HOLD'",
    "IN_TRANSIT": "l.location_class = 'TRANSIT'",
}

# Optional equality / search filters → SQL (values are always bound parameters).
FILTER_SQL: Mapping[str, str] = {
    "product_id": "si.product_id = :product_id",
    "condition_class": "lot.condition_class = :condition_class",
    "gs_id": "lot.gs_id = :gs_id",
    "location_id": "b.location_id = :location_id",
    "part_type": "si.part_type = :part_type",
    "pcb_model_id": "si.pcb_model_id = :pcb_model_id",
    "pcb_supplier_id": "si.pcb_supplier_id = :pcb_supplier_id",
    "container_id": "lot.container_id = :container_id",
    "partition_id": "lot.partition_id = :partition_id",
    "battery_type_id": "si.battery_type_id = :battery_type_id",
    "q": "(gs.gs_no ilike :q or p.code ilike :q or p.name ilike :q)",
    "min_age_days": "r.received_at <= now() - make_interval(days => :min_age_days)",
    "max_age_days": "r.received_at >= now() - make_interval(days => :max_age_days)",
}

_STOCK_FROM = """
  from public.stock_balances b
  join public.stock_lots lot on lot.id = b.lot_id
  join public.stock_items si on si.id = lot.stock_item_id
  join public.inventory_locations l on l.id = b.location_id
  left join public.goods_slips gs on gs.id = lot.gs_id
  left join public.gs_items gi on gi.id = lot.gs_item_id
  left join public.products p on p.id = si.product_id
  left join public.product_categories pc on pc.id = p.category_id
  left join public.pcb_models pm on pm.id = si.pcb_model_id
  left join public.pcb_suppliers ps on ps.id = si.pcb_supplier_id
  left join public.battery_types bt on bt.id = si.battery_type_id
  left join public.storage_containers sc on sc.id = lot.container_id
  left join public.container_partitions cp on cp.id = lot.partition_id
  left join lateral (
    select max(m.created_at) as received_at
      from public.stock_movements m
     where m.lot_id = b.lot_id and m.to_location_id = b.location_id
  ) r on true
  left join lateral (
    select t.id, t.transfer_no, tl_to.name as to_name
      from public.custody_transfer_lines tl
      join public.custody_transfers t on t.id = tl.transfer_id
      join public.inventory_locations tl_to on tl_to.id = t.to_location_id
     where tl.lot_id = b.lot_id and t.transit_location_id = b.location_id
       and t.status in ('INITIATED','DISCREPANCY')
     order by t.initiated_at desc
     limit 1
  ) tr on true
"""

_STOCK_COLUMNS = """
  b.lot_id, b.location_id, l.code as location_code, l.name as location_name, l.location_class,
  b.qty, lot.condition_class, lot.source_condition_code, lot.is_pending, si.item_kind,
  lot.gs_id, gs.gs_no, gi.line_no, si.product_id,
  coalesce(p.code, gi.product_code_snapshot) as product_code,
  coalesce(p.name, gi.product_name_snapshot) as product_name,
  pc.code as category_code, si.part_type, pm.name as pcb_model_name, ps.name as pcb_supplier_name,
  bt.code as battery_type_code, bt.name as battery_type_name,
  sc.code as container_code, cp.compartment_code as partition_code,
  r.received_at,
  case when r.received_at is null then null
       else ((now() at time zone 'Asia/Kolkata')::date
             - (r.received_at at time zone 'Asia/Kolkata')::date) end as age_days,
  tr.id as transfer_id, tr.transfer_no, tr.to_name as transfer_to_name
"""


def _stock_where(
    view: str, filters: Mapping[str, Any], *, include_salvaged: bool
) -> tuple[str, dict[str, Any]]:
    clauses = ["b.qty > 0", VIEW_FILTERS[view]]
    if not include_salvaged:
        clauses.append("lot.condition_class <> 'SALVAGED'")
    params: dict[str, Any] = {}
    for key, value in filters.items():
        if value is None or value == "":
            continue
        clauses.append(FILTER_SQL[key])
        params[key] = f"%{value}%" if key == "q" else value
    return " and ".join(clauses), params


def stock_page(
    session: Session,
    view: str,
    filters: Mapping[str, Any],
    *,
    include_salvaged: bool,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int, int]:
    """Rows of one segregated stock view, oldest arrival first (ageing), plus total rows / qty."""
    where, params = _stock_where(view, filters, include_salvaged=include_salvaged)
    totals = (
        session.execute(
            text(f"select count(*) as n, coalesce(sum(b.qty), 0) as q {_STOCK_FROM} where {where}"),
            params,
        )
        .mappings()
        .one()
    )
    rows = session.execute(
        text(
            f"select {_STOCK_COLUMNS} {_STOCK_FROM} where {where} "
            "order by r.received_at asc nulls last, gs.gs_no, gi.line_no, b.lot_id, l.code "
            "limit :limit offset :offset"
        ),
        {**params, "limit": limit, "offset": offset},
    ).mappings()
    return [dict(r) for r in rows], int(totals["n"]), int(totals["q"])


# --- lots, locations, balances -------------------------------------------------------------------
def lot_for_update(session: Session, lot_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select lot.id, lot.gs_id, lot.condition_class, lot.source_condition_code,
                       lot.is_pending, si.item_kind
                  from public.stock_lots lot
                  join public.stock_items si on si.id = lot.stock_item_id
                 where lot.id = :id
                   for update of lot
                """
            ),
            {"id": lot_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def lot_positions(session: Session, lot_id: UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select b.location_id, l.code as location_code, l.name as location_name,
                   l.location_class, b.qty
              from public.stock_balances b
              join public.inventory_locations l on l.id = b.location_id
             where b.lot_id = :lot and b.qty > 0
             order by l.code
            """
        ),
        {"lot": lot_id},
    ).mappings()
    return [dict(r) for r in rows]


def location_by_id(session: Session, location_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select l.id, l.code, l.name, l.location_class, l.custodian_role_id,
                       l.custodian_user_id, l.is_active
                  from public.inventory_locations l where l.id = :id
                """
            ),
            {"id": location_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def location_by_code(session: Session, code: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select l.id, l.code, l.name, l.location_class, l.custodian_role_id,
                       l.custodian_user_id, l.is_active
                  from public.inventory_locations l where l.code = :code
                """
            ),
            {"code": code},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def balance_for_update(session: Session, lot_id: UUID, location_id: UUID) -> int:
    value = session.execute(
        text(
            "select qty from public.stock_balances "
            "where lot_id = :lot and location_id = :loc for update"
        ),
        {"lot": lot_id, "loc": location_id},
    ).scalar()
    return int(value) if value is not None else 0


def get_setting(session: Session, key: str) -> Any:
    return session.execute(
        text("select value from public.system_settings where key = :key"), {"key": key}
    ).scalar()


# --- stock card ----------------------------------------------------------------------------------
def lot_header(session: Session, lot_id: UUID) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select lot.id as lot_id, lot.condition_class, lot.source_condition_code,
                       (select oi.label from public.option_items oi
                         where oi.code = lot.source_condition_code
                         order by oi.created_at limit 1) as source_condition_label,
                       lot.is_pending, si.item_kind, lot.gs_id, gs.gs_no, gi.line_no,
                       coalesce(p.code, gi.product_code_snapshot) as product_code,
                       coalesce(p.name, gi.product_name_snapshot) as product_name,
                       si.part_type, pm.name as pcb_model_name, ps.name as pcb_supplier_name,
                       sc.code as container_code, cp.compartment_code as partition_code
                  from public.stock_lots lot
                  join public.stock_items si on si.id = lot.stock_item_id
                  left join public.goods_slips gs on gs.id = lot.gs_id
                  left join public.gs_items gi on gi.id = lot.gs_item_id
                  left join public.products p on p.id = si.product_id
                  left join public.pcb_models pm on pm.id = si.pcb_model_id
                  left join public.pcb_suppliers ps on ps.id = si.pcb_supplier_id
                  left join public.storage_containers sc on sc.id = lot.container_id
                  left join public.container_partitions cp on cp.id = lot.partition_id
                 where lot.id = :id
                """
            ),
            {"id": lot_id},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def lot_lineage(session: Session, lot_id: UUID) -> list[dict[str, Any]]:
    """The lot and every lot it descends from, with the movement that split it off (`split_seq`).

    Two ledger links: a RECLASSIFY pair from rms_reclassify_lot (keys `<k>:OUT` / `<k>:IN`), and a
    dismantling RECEIPT of salvaged parts (reference DISMANTLE_BATCH → dismantle_inputs).
    """
    rows = session.execute(
        text(
            """
            with recursive anc (lot_id, depth, split_seq) as (
              select cast(:lot as uuid), 0, cast(null as bigint)
              union all
              select parent.lot_id, a.depth + 1, parent.split_seq
                from anc a
               cross join lateral (
                 select src.lot_id, src.seq as split_seq
                   from public.stock_movements inm
                   join public.stock_movements src
                     on src.idempotency_key = left(inm.idempotency_key,
                                                   length(inm.idempotency_key) - 3) || :out_suffix
                  where inm.lot_id = a.lot_id
                    and inm.movement_type = 'RECLASSIFY'
                    and inm.from_location_id is null
                    and inm.idempotency_key like :in_pattern
                 union all
                 select di.lot_id,
                        (select max(dm.seq) from public.stock_movements dm
                          where dm.lot_id = di.lot_id and dm.reference_id = di.batch_id)
                   from public.stock_movements rm
                   join public.dismantle_inputs di on di.batch_id = rm.reference_id
                  where rm.lot_id = a.lot_id
                    and rm.movement_type = 'RECEIPT'
                    and rm.reference_type = 'DISMANTLE_BATCH'
               ) parent
               where a.depth < 12
            )
            select lot_id, min(depth) as depth, max(split_seq) as split_seq
              from anc group by lot_id order by min(depth)
            """
        ),
        # rms_reclassify_lot suffixes (bound: a literal ":OUT" would read as a bind parameter).
        {"lot": lot_id, "out_suffix": ":OUT", "in_pattern": "%:IN"},
    ).mappings()
    return [dict(r) for r in rows]


def movements_for_lineage(
    session: Session, lot_id: UUID, ancestors: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The lot's movements plus each ancestor's movements up to the movement that split it."""
    anc_ids = [a["lot_id"] for a in ancestors]
    anc_split = [a["split_seq"] for a in ancestors]
    rows = session.execute(
        text(
            """
            with anc as (
              select * from unnest(cast(:anc_ids as uuid[]), cast(:anc_split as bigint[]))
                     as x(lot_id, split_seq)
            )
            select m.id, m.lot_id, lot.condition_class as lot_condition_class,
                   (m.lot_id <> :lot) as is_ancestor, m.movement_type, m.qty,
                   fl.code as from_location_code, fl.name as from_location_name,
                   tl.code as to_location_code, tl.name as to_location_name,
                   m.reference_type, m.reference_id,
                   case m.reference_type
                     when 'custody_transfer' then
                       (select t.transfer_no from public.custody_transfers t
                         where t.id = m.reference_id)
                     when 'DISMANTLE_BATCH' then
                       (select d.batch_no from public.dismantle_batches d
                         where d.id = m.reference_id)
                     when 'TECH_BATCH_RECEIVE' then
                       (select tb.batch_no from public.technician_batches tb
                         where tb.id = m.reference_id)
                     when 'goods_slip' then
                       (select g.gs_no from public.goods_slips g where g.id = m.reference_id)
                   end as reference_no,
                   m.reason, m.created_at, pr.full_name as created_by_name
              from public.stock_movements m
              join public.stock_lots lot on lot.id = m.lot_id
              left join public.inventory_locations fl on fl.id = m.from_location_id
              left join public.inventory_locations tl on tl.id = m.to_location_id
              left join public.profiles pr on pr.id = m.created_by
              left join anc on anc.lot_id = m.lot_id
             where m.lot_id = :lot
                or (anc.lot_id is not null and m.seq <= anc.split_seq)
             order by m.created_at, m.seq
            """
        ),
        {"lot": lot_id, "anc_ids": anc_ids, "anc_split": anc_split},
    ).mappings()
    return [dict(r) for r in rows]


# --- custody assignments -------------------------------------------------------------------------
_ASSIGNMENT_SELECT = """
  select a.id, a.lot_id, a.qty, a.assignment_code,
         coalesce(a.labels_snapshot #>> '{custody_assignment,value_label}', a.assignment_code)
           as assignment_label,
         a.condition_class, fl.code as from_location_code, tl.code as to_location_code,
         tl.name as to_location_name, a.outcome, a.transfer_id, t.transfer_no, a.notes,
         pr.full_name as created_by_name, a.created_at
    from public.custody_assignments a
    join public.inventory_locations fl on fl.id = a.from_location_id
    join public.inventory_locations tl on tl.id = a.to_location_id
    left join public.custody_transfers t on t.id = a.transfer_id
    left join public.profiles pr on pr.id = a.created_by
"""


def insert_assignment(
    session: Session,
    *,
    lot_id: UUID,
    qty: int,
    assignment_code: str,
    condition_class: str,
    from_location_id: UUID,
    to_location_id: UUID,
    outcome: str,
    transfer_id: UUID | None,
    form_version_id: UUID,
    labels_snapshot: dict[str, Any],
    notes: str | None,
    by: UUID,
) -> UUID:
    value = session.execute(
        text(
            """
            insert into public.custody_assignments (
              lot_id, qty, assignment_code, condition_class, from_location_id, to_location_id,
              outcome, transfer_id, form_version_id, labels_snapshot, notes, created_by
            ) values (
              :lot, :qty, :code, :cond, :from_loc, :to_loc, :outcome, :transfer,
              :form_version, cast(:labels as jsonb), :notes, :by
            ) returning id
            """
        ),
        {
            "lot": lot_id,
            "qty": qty,
            "code": assignment_code,
            "cond": condition_class,
            "from_loc": from_location_id,
            "to_loc": to_location_id,
            "outcome": outcome,
            "transfer": transfer_id,
            "form_version": form_version_id,
            "labels": _json(labels_snapshot),
            "notes": notes,
            "by": by,
        },
    ).scalar_one()
    return UUID(str(value))


def get_assignment(session: Session, assignment_id: UUID) -> dict[str, Any]:
    return dict(
        session.execute(text(_ASSIGNMENT_SELECT + " where a.id = :id"), {"id": assignment_id})
        .mappings()
        .one()
    )


def assignments_for_lots(session: Session, lot_ids: list[UUID]) -> list[dict[str, Any]]:
    rows = session.execute(
        text(_ASSIGNMENT_SELECT + " where a.lot_id = any(:ids) order by a.created_at"),
        {"ids": lot_ids},
    ).mappings()
    return [dict(r) for r in rows]


# --- segregation check ---------------------------------------------------------------------------
def segregation_violations(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select v.rule_code, v.guard_ref, v.lot_id, v.location_id, l.code as location_code,
                   v.qty, v.condition_class, v.location_class, v.detail, gs.gs_no,
                   coalesce(p.name, gi.product_name_snapshot) as product_name
              from rms_private.inventory_segregation_violations() v
              join public.inventory_locations l on l.id = v.location_id
              join public.stock_lots lot on lot.id = v.lot_id
              join public.stock_items si on si.id = lot.stock_item_id
              left join public.goods_slips gs on gs.id = lot.gs_id
              left join public.gs_items gi on gi.id = lot.gs_item_id
              left join public.products p on p.id = si.product_id
             order by v.guard_ref, v.rule_code, l.code, v.lot_id
            """
        )
    ).mappings()
    return [dict(r) for r in rows]


def insert_segregation_run(
    session: Session, *, trigger_code: str, by: UUID | None, violations: list[dict[str, Any]]
) -> UUID:
    value = session.execute(
        text(
            """
            insert into public.segregation_check_runs (trigger_code, run_by, violation_count,
                                                       violations)
            values (:t, :by, :n, cast(:v as jsonb)) returning id
            """
        ),
        {"t": trigger_code, "by": by, "n": len(violations), "v": _json(violations)},
    ).scalar_one()
    return UUID(str(value))


def last_segregation_run(session: Session, trigger_code: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                select id, trigger_code, run_at, violation_count
                  from public.segregation_check_runs where trigger_code = :t
                 order by run_at desc limit 1
                """
            ),
            {"t": trigger_code},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


# --- stock adjustments ---------------------------------------------------------------------------
_ADJUSTMENT_SELECT = """
  select a.id, a.lot_id, a.location_id, l.code as location_code, l.name as location_name,
         lot.condition_class, si.item_kind, gs.gs_no,
         coalesce(p.name, gi.product_name_snapshot) as product_name, si.part_type,
         a.system_qty, a.counted_qty, a.delta,
         coalesce((select b.qty from public.stock_balances b
                    where b.lot_id = a.lot_id and b.location_id = a.location_id), 0)
           as current_qty,
         a.reason, a.status, a.requested_by, rq.full_name as requested_by_name, a.requested_at,
         dc.full_name as decided_by_name, a.decided_at, a.decision_remarks, a.movement_id
    from public.stock_adjustments a
    join public.inventory_locations l on l.id = a.location_id
    join public.stock_lots lot on lot.id = a.lot_id
    join public.stock_items si on si.id = lot.stock_item_id
    left join public.goods_slips gs on gs.id = lot.gs_id
    left join public.gs_items gi on gi.id = lot.gs_item_id
    left join public.products p on p.id = si.product_id
    left join public.profiles rq on rq.id = a.requested_by
    left join public.profiles dc on dc.id = a.decided_by
"""


def insert_adjustment(
    session: Session,
    *,
    lot_id: UUID,
    location_id: UUID,
    system_qty: int,
    counted_qty: int,
    reason: str,
    by: UUID,
) -> UUID:
    value = session.execute(
        text(
            """
            insert into public.stock_adjustments (lot_id, location_id, system_qty, counted_qty,
                                                  reason, requested_by)
            values (:lot, :loc, :sys, :counted, :reason, :by) returning id
            """
        ),
        {
            "lot": lot_id,
            "loc": location_id,
            "sys": system_qty,
            "counted": counted_qty,
            "reason": reason,
            "by": by,
        },
    ).scalar_one()
    return UUID(str(value))


def open_adjustment_exists(session: Session, lot_id: UUID, location_id: UUID) -> bool:
    return bool(
        session.execute(
            text(
                "select exists (select 1 from public.stock_adjustments where lot_id = :lot "
                "and location_id = :loc and status = 'REQUESTED')"
            ),
            {"lot": lot_id, "loc": location_id},
        ).scalar()
    )


def get_adjustment(
    session: Session, adjustment_id: UUID, *, for_update: bool = False
) -> dict[str, Any] | None:
    if for_update:
        session.execute(
            text("select 1 from public.stock_adjustments where id = :id for update"),
            {"id": adjustment_id},
        )
    row = (
        session.execute(text(_ADJUSTMENT_SELECT + " where a.id = :id"), {"id": adjustment_id})
        .mappings()
        .first()
    )
    return dict(row) if row else None


def list_adjustments(
    session: Session, *, status: str | None, include_salvaged: bool, limit: int, offset: int
) -> tuple[list[dict[str, Any]], int]:
    clauses = ["true"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if status:
        clauses.append("a.status = :status")
        params["status"] = status
    if not include_salvaged:
        clauses.append("lot.condition_class <> 'SALVAGED'")
    where = " and ".join(clauses)
    total = session.execute(
        text(
            "select count(*) from public.stock_adjustments a "  # noqa: S608 - fixed fragments
            "join public.stock_lots lot on lot.id = a.lot_id where " + where
        ),
        params,
    ).scalar_one()
    rows = session.execute(
        text(
            _ADJUSTMENT_SELECT
            + " where "
            + where
            + " order by (a.status = 'REQUESTED') desc, a.requested_at desc"
            " limit :limit offset :offset"
        ),
        params,
    ).mappings()
    return [dict(r) for r in rows], int(total)


def decide_adjustment(
    session: Session,
    adjustment_id: UUID,
    *,
    status: str,
    by: UUID,
    remarks: str | None,
    movement_id: UUID | None,
) -> None:
    session.execute(
        text(
            """
            update public.stock_adjustments
               set status = :status, decided_by = :by, decided_at = now(),
                   decision_remarks = :remarks, movement_id = :movement
             where id = :id
            """
        ),
        {
            "id": adjustment_id,
            "status": status,
            "by": by,
            "remarks": remarks,
            "movement": movement_id,
        },
    )


def super_admin_ids(session: Session) -> list[UUID]:
    rows = session.execute(
        text("select id from public.profiles where is_super_admin and is_active")
    ).scalars()
    return [UUID(str(r)) for r in rows]


# --- lookups -------------------------------------------------------------------------------------
def stocked_products(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select distinct p.id, p.code, p.name
              from public.stock_balances b
              join public.stock_lots lot on lot.id = b.lot_id
              join public.stock_items si on si.id = lot.stock_item_id
              join public.products p on p.id = si.product_id
             where b.qty > 0
             order by p.name
            """
        )
    ).mappings()
    return [dict(r) for r in rows]


def simple_master(session: Session, table: str) -> list[dict[str, Any]]:
    """Active rows of a small master (`table` is a fixed name below, never client text)."""
    sql = {
        "pcb_models": "select id, null as code, name from public.pcb_models where is_active",
        "pcb_suppliers": "select id, null as code, name from public.pcb_suppliers where is_active",
        "battery_types": "select id, code, name from public.battery_types where is_active",
        "containers": (
            "select id, code, coalesce(name, code) as name from public.storage_containers "
            "where is_active and container_type = 'PARTS'"
        ),
        "partitions": (
            "select cp.id, cp.compartment_code as code, "
            "sc.code || ' / ' || cp.compartment_code as name "
            "from public.container_partitions cp "
            "join public.storage_containers sc on sc.id = cp.container_id where cp.is_active"
        ),
    }[table]
    rows = session.execute(text(sql + " order by 3")).mappings()
    return [dict(r) for r in rows]


def option_items(session: Session, set_code: str) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            select oi.code, oi.label, oi.next_action_text
              from public.option_items oi
              join public.option_sets os on os.id = oi.option_set_id
             where os.code = :set and oi.is_active
             order by oi.sort_order
            """
        ),
        {"set": set_code},
    ).mappings()
    return [dict(r) for r in rows]


def _json(value: Any) -> str:
    return json.dumps(value, default=str)
