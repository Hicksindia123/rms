"""Report base queries (prompt P4-02). SQL only, no business rules (CLAUDE.md rule g).

Each query returns one row per report row with column aliases equal to the registry column keys
(plus hidden id columns used for drill-down links). The token ``{where}`` is replaced by the
report runner with the inner filter and data-scope predicates (``true`` when there are none);
``:tz`` is always bound to the business timezone. Report parameters (``mode="param"`` filters) are
bound as ``:p_<key>`` and always present (their default or NULL), so they are cast explicitly.

Aggregation is done here in SQL, never by loading rows into Python. Formulas are documented in
docs/REPORTS.md.
"""

from __future__ import annotations

# Day boundaries in the business timezone for a date parameter.
_FROM = "(cast(:p_date_from as date)::timestamp at time zone :tz)"
_TO_END = "((cast(:p_date_to as date) + 1)::timestamp at time zone :tz)"


def _window(col: str) -> str:
    """`col` within [date_from, date_to] (each bound optional) in the business timezone."""
    return (
        f"(cast(:p_date_from as date) is null or {col} >= {_FROM}) "
        f"and (cast(:p_date_to as date) is null or {col} < {_TO_END})"
    )


# Published step labels (latest published version per step code), for step-based reports.
STEP_LABELS_CTE = """
step_labels as (
  select distinct on (ws.code) ws.code, ws.label
    from public.workflow_steps ws
    join public.workflow_versions v on v.id = ws.workflow_version_id
   where v.status = 'PUBLISHED'
   order by ws.code, v.published_at desc nulls last
)"""

# --- R-01 Pending work by step & user (ageing buckets 0-1, 1-3, 3-7, >7 days) ------------------
R01 = """
select t.step_code,
       coalesce(max(ws.label), t.step_code) as step_label,
       case when t.assigned_user_id is not null then 'USER' else 'ROLE' end as assignee_type,
       coalesce(p.full_name, r.name, '-') as assignee,
       count(*)::int as open_tasks,
       count(*) filter (where now() - t.created_at <= interval '1 day')::int as age_0_1,
       count(*) filter (where now() - t.created_at > interval '1 day'
                          and now() - t.created_at <= interval '3 days')::int as age_1_3,
       count(*) filter (where now() - t.created_at > interval '3 days'
                          and now() - t.created_at <= interval '7 days')::int as age_3_7,
       count(*) filter (where now() - t.created_at > interval '7 days')::int as age_over_7,
       count(*) filter (where t.due_at is not null and t.due_at < now())::int as overdue,
       round((extract(epoch from now() - min(t.created_at)) / 86400.0)::numeric, 1)
         as oldest_days
  from public.workflow_tasks t
  join public.goods_slips g on g.id = t.gs_id
  left join public.workflow_steps ws
         on ws.workflow_version_id = g.workflow_version_id and ws.code = t.step_code
  left join public.profiles p on p.id = t.assigned_user_id
  left join public.roles r on r.id = t.assigned_role_id
 where t.status = 'OPEN'
   and {where}
 group by t.step_code, t.assigned_user_id, t.assigned_role_id, p.full_name, r.name
"""

# --- R-02 GS lifecycle ---------------------------------------------------------------------------
R02 = """
select g.id as gs_id, g.gs_no,
       (g.created_at at time zone :tz)::date as gs_date,
       pa.name as party_name, g.category_code, g.status,
       g.created_at as gate_at,
       s.unboxing_started_at, s.evidence_completed_at, g.categorized_at, s.csr_decided_at,
       s.inspected_at, s.in_process_at, s.commercial_at, pn.first_sent_at as notified_at,
       g.closed_at,
       round((extract(epoch from s.evidence_completed_at - g.created_at) / 3600.0)::numeric, 1)
         as h_gate_to_evidence,
       round((extract(epoch from coalesce(s.inspected_at, s.csr_decided_at)
                                 - s.evidence_completed_at) / 3600.0)::numeric, 1)
         as h_evidence_to_review,
       round((extract(epoch from s.in_process_at - coalesce(s.inspected_at, s.csr_decided_at))
              / 3600.0)::numeric, 1) as h_review_to_process,
       round((extract(epoch from s.commercial_at - s.in_process_at) / 3600.0)::numeric, 1)
         as h_process_to_commercial,
       round((extract(epoch from g.closed_at - s.commercial_at) / 3600.0)::numeric, 1)
         as h_commercial_to_close,
       round((extract(epoch from coalesce(g.closed_at, g.cancelled_at, now()) - g.created_at)
              / 3600.0)::numeric, 1) as h_total,
       case when g.status in ('CLOSED', 'CANCELLED') then null
            else round((extract(epoch from now() - coalesce(s.last_status_change_at, g.created_at))
                        / 86400.0)::numeric, 1) end as days_in_status,
       nullif(concat_ws(', ',
         case when g.missing_documentation then 'MISSING_DOCUMENTATION' end,
         case when g.has_open_pendency then 'OPEN_PENDENCY' end,
         case when g.has_discrepancy then 'DISCREPANCY' end,
         case when g.has_hazard then 'HAZARD' end,
         case when g.has_rejections then 'REJECTIONS' end), '') as flags
  from public.goods_slips g
  left join public.parties pa on pa.id = g.party_id
  left join rms_reports.gs_stage_times s on s.gs_id = g.id
  left join lateral (select min(n.sent_at) as first_sent_at
                       from public.party_notifications n where n.gs_id = g.id) pn on true
 where {where}
"""

# --- R-03 GS register ----------------------------------------------------------------------------
R03 = """
select g.id as gs_id, g.gs_no,
       (g.created_at at time zone :tz)::date as gs_date,
       pa.code as party_code, pa.name as party_name, st.name as state_name,
       sn.name as station_name, g.delivery_mode_code, g.return_type_code,
       g.gate_entry_date, g.gate_entry_no::text as gate_entry_no, g.carton_count,
       (select string_agg(d.doc_type_code || coalesce(' ' || d.doc_no, ''), '; '
                        order by d.sort_order, d.created_at)
          from public.gs_gate_documents d
         where d.gs_id = g.id) as gate_documents, g.category_code, g.status,
       coalesce(li.lines, 0)::int as lines,
       coalesce(li.documented_qty, 0)::int as documented_qty,
       coalesce(li.received_qty, 0)::int as received_qty,
       coalesce(li.short_qty, 0)::int as short_qty,
       g.missing_documentation, g.has_open_pendency, g.has_discrepancy, g.has_hazard,
       g.has_rejections, g.closed_at, g.closure_type
  from public.goods_slips g
  left join public.parties pa on pa.id = g.party_id
  left join public.states st on st.id = g.state_id
  left join public.stations sn on sn.id = g.station_id
  left join lateral (select count(*) as lines, sum(i.documented_qty) as documented_qty,
                            sum(i.received_qty) as received_qty, sum(i.short_qty) as short_qty
                       from public.gs_items i where i.gs_id = g.id) li on true
 where {where}
"""

# --- R-04 Inward evidence compliance (G-02, BR-04, DEC-03) ---------------------------------------
R04 = """
select g.id as gs_id, g.gs_no,
       (g.created_at at time zone :tz)::date as gs_date,
       pa.name as party_name, g.status,
       (select string_agg(d.doc_type_code || coalesce(' ' || d.doc_no, ''), '; '
                        order by d.sort_order, d.created_at)
          from public.gs_gate_documents d
         where d.gs_id = g.id) as gate_documents, g.missing_documentation,
       coalesce(a.videos, 0)::int as videos,
       coalesce(a.doc_photos, 0)::int as doc_photos,
       coalesce(d.docs, 0)::int as docs_classified,
       x.status as missing_doc_exception,
       (coalesce(a.videos, 0) > 0
        and (coalesce(a.doc_photos, 0) > 0 or x.status = 'APPROVED')) as evidence_complete,
       s.unboxing_started_at, s.evidence_completed_at,
       round((extract(epoch from s.evidence_completed_at - g.created_at) / 3600.0)::numeric, 1)
         as h_gate_to_step2,
       round((extract(epoch from s.evidence_completed_at - s.unboxing_started_at)
              / 3600.0)::numeric, 1) as h_step2
  from public.goods_slips g
  left join public.parties pa on pa.id = g.party_id
  left join rms_reports.gs_stage_times s on s.gs_id = g.id
  left join lateral (select count(*) filter (where at.kind = 'UNBOXING_VIDEO') as videos,
                            count(*) filter (where at.kind = 'DOC_PHOTO') as doc_photos
                       from public.attachments at
                      where at.gs_id = g.id and at.status = 'CONFIRMED') a on true
  left join lateral (select count(*) as docs from public.gs_documents gd
                      where gd.gs_id = g.id) d on true
  left join lateral (select e.status from public.missing_doc_exceptions e
                      where e.gs_id = g.id order by e.requested_at desc limit 1) x on true
 where {where}
"""

# --- R-05 Inspection summary by category & condition ---------------------------------------------
R05 = """
select coalesce(gi.category_code_snapshot, pc.code) as category_code,
       a.condition_code,
       (array_agg(a.label_snapshot order by a.created_at desc))[1] as condition_label,
       (array_agg(a.allowed_status_snapshot order by a.created_at desc))[1] as allowed_status,
       (array_agg(a.system_behavior_snapshot order by a.created_at desc))[1] as system_behavior,
       count(distinct gi.gs_id)::int as gs_count,
       count(distinct gi.id)::int as lines,
       sum(a.qty)::int as qty,
       coalesce(sum(a.qty) filter (where a.allowed_status_snapshot = 'NO'), 0)::int
         as not_allowed_qty,
       coalesce(sum(a.qty) filter (where a.system_behavior_snapshot = 'HAZARD'), 0)::int
         as hazard_qty
  from public.inspection_allocations a
  join public.inspections i on i.id = a.inspection_id and i.status = 'FINAL'
  join public.gs_items gi on gi.id = i.gs_item_id
  join public.goods_slips g on g.id = gi.gs_id
  left join public.product_categories pc on pc.id = gi.category_id
 where {where}
 group by coalesce(gi.category_code_snapshot, pc.code), a.condition_code
"""

# --- R-06 Rejections & hazard register -----------------------------------------------------------
R06 = """
select r.id as rejection_id, g.id as gs_id, g.gs_no,
       (r.created_at at time zone :tz)::date as rejected_on,
       pa.name as party_name, gi.line_no,
       coalesce(gi.product_code_snapshot, pr.code) as product_code,
       coalesce(gi.product_name_snapshot, pr.name) as product_name,
       coalesce(gi.category_code_snapshot, pc.code) as category_code,
       r.condition_code, coalesce(cl.label, r.condition_code) as condition_label,
       r.qty, rr.label as reason, r.disposition, r.hazard,
       cur.locations as current_location, sr.disposal_status as scrap_status, sr.manifest_ref
  from public.rejections r
  join public.gs_items gi on gi.id = r.gs_item_id
  join public.goods_slips g on g.id = gi.gs_id
  left join public.parties pa on pa.id = g.party_id
  left join public.products pr on pr.id = gi.product_id
  left join public.product_categories pc on pc.id = gi.category_id
  left join public.rejection_reasons rr on rr.id = r.rejection_reason_id
  left join public.stock_movements m on m.id = r.stock_movement_id
  left join lateral (select a.label_snapshot as label
                       from public.inspection_allocations a
                       join public.inspections i on i.id = a.inspection_id
                      where i.gs_item_id = gi.id and a.condition_code = r.condition_code
                      order by a.created_at desc limit 1) cl on true
  left join lateral (select string_agg(il.code || ' ' || b.qty, ', ' order by il.code) as locations
                       from public.stock_balances b
                       join public.inventory_locations il on il.id = b.location_id
                      where b.lot_id = m.lot_id and b.qty > 0) cur on true
  left join lateral (select s.disposal_status, s.manifest_ref from public.scrap_records s
                      where s.lot_id = m.lot_id order by s.created_at desc limit 1) sr on true
 where {where}
"""

# --- R-07 Daily container audit compliance (BR-18, DEC-08) ---------------------------------------
R07 = """
select day::date as audit_date,
       d.status,
       (d.id is not null) as recorded,
       (d.status = 'CONFIRMED') is true as on_time,
       (d.status = 'LATE') is true as late,
       cb.full_name as confirmed_by_name, d.confirmed_at,
       coalesce(l.containers, 0)::int as containers_counted,
       coalesce(l.counted_qty, 0)::int as counted_qty,
       coalesce(l.sellable_qty, 0)::int as sellable_packaging_qty,
       d.late_reason, d.remarks
  from generate_series(cast(:p_date_from as date), cast(:p_date_to as date), interval '1 day') day
  left join public.container_audit_days d on d.audit_date = day::date
  left join public.profiles cb on cb.id = d.confirmed_by
  left join lateral (select count(*) as containers, sum(cl.counted_qty) as counted_qty,
                            sum(cl.sellable_packaging_qty) as sellable_qty
                       from public.container_audit_lines cl
                      where cl.audit_day_id = d.id) l on true
 where {where}
"""

# --- R-08 Pendency register & ageing (BR-20, DEC-12) ---------------------------------------------
R08 = """
select pd.id as pendency_id, g.id as gs_id, g.gs_no, pa.name as party_name, gi.line_no,
       coalesce(gi.product_code_snapshot, pr.code) as product_code,
       coalesce(gi.product_name_snapshot, pr.name) as product_name,
       pd.qty, pd.reason, pd.sent_to, pd.blocks_gs, pd.status,
       ob.full_name as opened_by_name, pd.opened_at,
       cb.full_name as cleared_by_name, pd.cleared_at, pd.resolution_action,
       a.age_days,
       case when a.age_days <= 1 then '0-1' when a.age_days <= 3 then '1-3'
            when a.age_days <= 7 then '3-7' else '>7' end as ageing_bucket
  from public.pendencies pd
  join public.goods_slips g on g.id = pd.gs_id
  left join public.parties pa on pa.id = g.party_id
  left join public.gs_items gi on gi.id = pd.gs_item_id
  left join public.products pr on pr.id = gi.product_id
  left join public.profiles ob on ob.id = pd.opened_by
  left join public.profiles cb on cb.id = pd.cleared_by
  cross join lateral (select round((extract(epoch from coalesce(pd.cleared_at, now())
                                                       - pd.opened_at) / 86400.0)::numeric, 1)
                               as age_days) a
 where {where}
"""

# --- R-09 Custody transfers & discrepancies (BR-21, G-09) ----------------------------------------
R09 = """
select t.id as transfer_id, t.transfer_no, g.id as gs_id, g.gs_no, t.purpose_code,
       fl.code as from_location, tl.code as to_location, t.status,
       ib.full_name as initiated_by_name, t.initiated_at,
       ab.full_name as accepted_by_name, t.accepted_at,
       round((extract(epoch from t.accepted_at - t.initiated_at) / 3600.0)::numeric, 1)
         as h_to_accept,
       coalesce(l.qty_sent, 0)::int as qty_sent,
       l.qty_counted::int as qty_counted,
       coalesce(l.qty_accepted, 0)::int as qty_accepted,
       (l.qty_counted - l.qty_sent)::int as qty_difference,
       (t.status in ('DISCREPANCY', 'RECONCILED') or rc.id is not null) as had_discrepancy,
       t.discrepancy_notes, rc.resolution_code, rc.status as reconciliation_status,
       t.reconciled_at
  from public.custody_transfers t
  left join public.goods_slips g on g.id = t.gs_id
  left join public.inventory_locations fl on fl.id = t.from_location_id
  left join public.inventory_locations tl on tl.id = t.to_location_id
  left join public.profiles ib on ib.id = t.initiated_by
  left join public.profiles ab on ab.id = t.accepted_by
  left join lateral (select sum(x.qty_sent) as qty_sent, sum(x.qty_counted) as qty_counted,
                            sum(x.qty_accepted) as qty_accepted
                       from public.custody_transfer_lines x where x.transfer_id = t.id) l on true
  left join lateral (select c.id, c.resolution_code, c.status
                       from public.custody_reconciliations c
                      where c.transfer_id = t.id order by c.created_at desc limit 1) rc on true
 where {where}
"""

# --- R-10 Technician productivity (BR-23, BR-24) -------------------------------------------------
R10 = f"""
select te.id as technician_id, te.display_name as technician_name,
       coalesce(al.batches, 0)::int as batches,
       coalesce(al.pieces_allotted, 0)::int as pieces_allotted,
       coalesce(rc.pieces_received, 0)::int as pieces_received,
       coalesce(rc.pieces_checked, 0)::int as pieces_checked,
       coalesce(rc.batteries_installed, 0)::int as batteries_installed,
       round(100.0 * coalesce(rc.batteries_installed, 0)
             / nullif(coalesce(rc.pieces_checked, 0), 0), 1) as battery_replacement_rate,
       coalesce(rc.functional_good, 0)::int as functional_good,
       coalesce(rc.functional_repaired, 0)::int as functional_repaired,
       coalesce(rc.non_good, 0)::int as non_good,
       coalesce(rc.non_sellable, 0)::int as non_sellable,
       rc.avg_turnaround_hours
  from public.technicians te
  left join (select tb.technician_id, count(distinct tb.id) as batches,
                    sum(tbl.qty_allotted) as pieces_allotted
               from public.technician_batches tb
               left join public.technician_batch_lines tbl on tbl.batch_id = tb.id
              where tb.status <> 'CANCELLED' and {_window("tb.allotted_at")}
              group by tb.technician_id) al on al.technician_id = te.id
  left join (select tb.technician_id,
                    sum(r.qty_received) as pieces_received,
                    sum(r.pieces_checked) as pieces_checked,
                    sum(r.batteries_installed) as batteries_installed,
                    sum(r.functional_good_qty) as functional_good,
                    sum(r.functional_repaired_qty) as functional_repaired,
                    sum(r.non_good_qty) as non_good,
                    sum(r.non_sellable_qty) as non_sellable,
                    round((avg(extract(epoch from r.received_at - tb.allotted_at))
                           / 3600.0)::numeric, 1) as avg_turnaround_hours
               from public.technician_receiving_records r
               join public.technician_batches tb on tb.id = r.batch_id
              where {_window("r.received_at")}
              group by tb.technician_id) rc on rc.technician_id = te.id
 where (al.technician_id is not null or rc.technician_id is not null)
   and {{where}}
"""  # noqa: S608 - registry SQL; only fixed fragments are interpolated

# --- R-11 Battery reconciliation (BR-24, G-10, IC-09) --------------------------------------------
R11 = f"""
with mv as (
  select si.battery_type_id, m.movement_type, m.created_at, m.qty,
         case when m.to_location_id is not null and m.from_location_id is null then m.qty
              when m.from_location_id is not null and m.to_location_id is null then -m.qty
              else 0 end as net
    from public.stock_movements m
    join public.stock_lots l on l.id = m.lot_id
    join public.stock_items si on si.id = l.stock_item_id
   where si.item_kind = 'BATTERY'
),
flows as (
  select battery_type_id,
         coalesce(sum(net) filter (where cast(:p_date_from as date) is not null
                                     and created_at < {_FROM}), 0) as opening_qty,
         coalesce(sum(qty) filter (where movement_type = 'RECEIPT'
                                     and {_window("created_at")}), 0) as received_qty,
         coalesce(sum(net) filter (where movement_type = 'ADJUST'
                                     and {_window("created_at")}), 0) as adjusted_qty,
         coalesce(sum(qty) filter (where movement_type = 'CONSUME'
                                     and {_window("created_at")}), 0) as consumed_qty,
         coalesce(sum(net) filter (where cast(:p_date_to as date) is null
                                      or created_at < {_TO_END}), 0) as closing_qty
    from mv
   group by battery_type_id
),
rec as (
  select r.battery_type_id,
         sum(r.pieces_checked) as pieces_checked,
         sum(r.batteries_installed) as batteries_installed,
         count(*) filter (where r.battery_check_code = 'BATTERY_REPLACED') as replaced_records
    from public.technician_receiving_records r
   where {_window("r.received_at")}
   group by r.battery_type_id
),
bal as (
  select si.battery_type_id, sum(b.qty) as balance_qty
    from public.stock_balances b
    join public.stock_lots l on l.id = b.lot_id
    join public.stock_items si on si.id = l.stock_item_id
   where si.item_kind = 'BATTERY'
   group by si.battery_type_id
),
types as (
  select bt.id, bt.code, bt.name, bt.is_active from public.battery_types bt
  union all
  select null, null, null, true where exists (select 1 from rec where rec.battery_type_id is null)
)
select bt.id as battery_type_id, bt.code as battery_code, bt.name as battery_name,
       coalesce(rec.pieces_checked, 0)::int as pieces_checked,
       coalesce(rec.replaced_records, 0)::int as replaced_records,
       coalesce(rec.batteries_installed, 0)::int as batteries_installed,
       coalesce(f.opening_qty, 0)::int as opening_qty,
       coalesce(f.received_qty, 0)::int as received_qty,
       coalesce(f.adjusted_qty, 0)::int as adjusted_qty,
       coalesce(f.consumed_qty, 0)::int as consumed_qty,
       coalesce(f.closing_qty, 0)::int as closing_qty,
       case when bt.id is null then null else coalesce(bal.balance_qty, 0)::int end
         as current_balance,
       (coalesce(rec.batteries_installed, 0) - coalesce(f.consumed_qty, 0))::int
         as installed_minus_consumed,
       (coalesce(rec.batteries_installed, 0) = coalesce(f.consumed_qty, 0)) as reconciled
  from types bt
  left join flows f on f.battery_type_id is not distinct from bt.id
  left join rec on rec.battery_type_id is not distinct from bt.id
  left join bal on bal.battery_type_id is not distinct from bt.id
 where (bt.is_active or f.battery_type_id is not null or rec.battery_type_id is not null
        or bt.id is null)
   and {{where}}
"""  # noqa: S608 - registry SQL; only fixed fragments are interpolated

# --- R-12 Dismantling & parts recovery (BR-27, BR-28, G-11) --------------------------------------
R12 = """
select rp.part_type,
       pm.name as pcb_model, ps.name as pcb_supplier,
       coalesce(sc.code, psc.code) as container_code,
       cp.compartment_code as partition_code,
       count(distinct rp.batch_id)::int as batches,
       sum(rp.qty)::int as qty_recovered,
       min(rp.created_at) as first_recovered_at,
       max(rp.created_at) as last_recovered_at
  from public.recovered_parts rp
  join public.dismantle_batches db on db.id = rp.batch_id
  left join public.pcb_models pm on pm.id = rp.pcb_model_id
  left join public.pcb_suppliers ps on ps.id = rp.pcb_supplier_id
  left join public.storage_containers sc on sc.id = rp.container_id
  left join public.container_partitions cp on cp.id = rp.partition_id
  left join public.storage_containers psc on psc.id = cp.container_id
 where {where}
 group by rp.part_type, pm.name, ps.name, coalesce(sc.code, psc.code), cp.compartment_code
"""

# --- R-13 Inventory position as on date (movement ledger up to the end of the date) --------------
R13 = """
with mv as (
  select m.lot_id, m.to_location_id as location_id, m.qty
    from public.stock_movements m
   where m.to_location_id is not null
     and m.created_at < ((cast(:p_as_on as date) + 1)::timestamp at time zone :tz)
  union all
  select m.lot_id, m.from_location_id, -m.qty
    from public.stock_movements m
   where m.from_location_id is not null
     and m.created_at < ((cast(:p_as_on as date) + 1)::timestamp at time zone :tz)
),
pos as (
  select lot_id, location_id, sum(qty) as qty from mv group by lot_id, location_id
  having sum(qty) <> 0
)
select il.id as location_id, il.code as location_code, il.name as location_name,
       il.location_class,
       coalesce(cu.full_name, cr.name) as custodian,
       l.condition_class, si.item_kind,
       coalesce(pr.code, bt.code, si.part_type) as item_code,
       coalesce(pr.name, bt.name,
                si.part_type || coalesce(' / ' || pm.name, '') || coalesce(' / ' || ps.name, ''))
         as item_name,
       count(distinct l.id)::int as lots,
       count(distinct l.gs_id)::int as gs_count,
       sum(pos.qty)::int as qty
  from pos
  join public.stock_lots l on l.id = pos.lot_id
  join public.stock_items si on si.id = l.stock_item_id
  join public.inventory_locations il on il.id = pos.location_id
  left join public.profiles cu on cu.id = il.custodian_user_id
  left join public.roles cr on cr.id = il.custodian_role_id
  left join public.products pr on pr.id = si.product_id
  left join public.battery_types bt on bt.id = si.battery_type_id
  left join public.pcb_models pm on pm.id = si.pcb_model_id
  left join public.pcb_suppliers ps on ps.id = si.pcb_supplier_id
 where (cast(:p_include_terminal as boolean)
        or il.location_class not in ('DISPATCHED', 'CREDITED', 'SCRAP_DISPOSED'))
   and {where}
 group by il.id, il.code, il.name, il.location_class, cu.full_name, cr.name, l.condition_class,
          si.item_kind, pr.code, bt.code, si.part_type, pr.name, bt.name, pm.name, ps.name
"""

# --- R-14 Stock reconciliation exceptions (IC-01, IC-02, IC-03, IC-05, IC-09) --------------------
R14 = """
select x.check_code,
       case x.check_code
         when 'IC-01' then 'GS line: received vs accounted'
         when 'IC-02' then 'Negative balance'
         when 'IC-03' then 'Movements vs balance'
         when 'IC-05' then 'Rejection without movement'
         when 'IC-09' then 'Batteries installed vs consumed'
       end as check_label,
       x.gs_id, x.gs_no, x.line_no, x.lot_id::text as lot_ref, x.location_code,
       x.expected_qty::int as expected_qty, x.actual_qty::int as actual_qty,
       (x.actual_qty - x.expected_qty)::int as difference, x.detail
  from rms_reports.stock_reconciliation_exceptions x
 where {where}
"""

# --- R-15 Store issues & dispatches (BR-31, DEC-21, DEC-26) --------------------------------------
R15 = """
select * from (
  select 'STORE_ISSUE'::text as doc_kind, s.id as doc_id, s.issue_no as doc_no,
         s.issue_type_code as doc_type,
         (s.created_at at time zone :tz)::date as doc_date, s.created_at as doc_at,
         null::uuid as gs_id,
         (select string_agg(distinct g.gs_no, ', ')
            from public.store_issue_lines x
            join public.stock_lots l on l.id = x.lot_id
            join public.goods_slips g on g.id = l.gs_id
           where x.issue_id = s.id) as gs_nos,
         fl.code as from_location, tl.code as to_location,
         coalesce((select sum(x.qty) from public.store_issue_lines x
                    where x.issue_id = s.id), 0)::int
           as qty,
         (select count(*) from public.store_issue_lines x where x.issue_id = s.id)::int as lines,
         s.status, s.created_by as done_by_id, cb.full_name as done_by_name,
         ab.full_name as acknowledged_by_name, s.acknowledged_at,
         null::text as transporter, null::text as docket_or_vehicle, null::text as ref_doc_no
    from public.store_issues s
    left join public.inventory_locations fl on fl.id = s.from_location_id
    left join public.inventory_locations tl on tl.id = s.to_location_id
    left join public.profiles cb on cb.id = s.created_by
    left join public.profiles ab on ab.id = s.acknowledged_by
  union all
  select 'DISPATCH', d.id, d.dispatch_no, d.dispatch_type,
         (coalesce(d.dispatched_at, d.created_at) at time zone :tz)::date,
         coalesce(d.dispatched_at, d.created_at),
         g.id, g.gs_no,
         (select string_agg(distinct fl.code, ', ')
            from public.replacement_dispatch_lines x
            join public.stock_movements m on m.id = x.stock_movement_id
            join public.inventory_locations fl on fl.id = m.from_location_id
           where x.dispatch_id = d.id),
         'DISPATCHED',
         coalesce((select sum(x.qty) from public.replacement_dispatch_lines x
                    where x.dispatch_id = d.id), 0)::int,
         (select count(*) from public.replacement_dispatch_lines x where x.dispatch_id = d.id)::int,
         d.status, d.dispatched_by, db.full_name, null, null,
         d.transporter, coalesce(d.docket_no, d.vehicle_no), d.ref_doc_no
    from public.replacement_dispatches d
    left join public.goods_slips g on g.id = d.gs_id
    left join public.profiles db on db.id = d.dispatched_by
) u
 where {where}
"""

# --- R-16 Credit Note register (BR-32…BR-38, G-13, G-14) -----------------------------------------
R16 = """
select c.id as cn_id, g.id as gs_id, g.gs_no, pa.name as party_name, pa.gstin as party_gstin,
       c.cn_type_code, c.status,
       coalesce(c.cn_no, c.jv_no) as voucher_no,
       coalesce(c.cn_date, c.jv_date, (c.created_at at time zone :tz)::date) as voucher_date,
       c.party_doc_code, c.party_doc_no, c.party_doc_date, c.party_doc_amount,
       c.gst_portal_code, c.gst_return_type, c.gst_return_period,
       coalesce(c.taxable_value, 0) as taxable_value,
       coalesce(c.cgst_amount, 0) as cgst_amount,
       coalesce(c.sgst_amount, 0) as sgst_amount,
       coalesce(c.igst_amount, 0) as igst_amount,
       coalesce(c.total_value, 0) as total_value,
       coalesce(ln.lines, 0)::int as lines, coalesce(ln.qty, 0)::int as qty,
       rv.rate_sources, coalesce(rv.lines_verified, 0)::int as lines_rate_verified,
       pn.sent_at as notified_at, pn.channel_code as notification_channel,
       (pn.sent_at is not null) as notified,
       ib.full_name as issued_by_name, c.issued_at
  from public.credit_notes c
  join public.goods_slips g on g.id = c.gs_id
  left join public.parties pa on pa.id = g.party_id
  left join public.profiles ib on ib.id = c.issued_by
  left join lateral (select count(*) as lines, sum(l.qty) as qty
                       from public.credit_note_lines l where l.credit_note_id = c.id) ln on true
  left join lateral (select string_agg(distinct v.reference_code, ', ') as rate_sources,
                            count(distinct v.credit_note_line_id) as lines_verified
                       from public.rate_verifications v
                       join public.credit_note_lines l on l.id = v.credit_note_line_id
                      where l.credit_note_id = c.id) rv on true
  left join lateral (select n.sent_at, n.channel_code from public.party_notifications n
                      where n.credit_note_id = c.id
                         or (n.credit_note_id is null and n.gs_id = c.gs_id)
                      order by n.sent_at limit 1) pn on true
 where {where}
"""

# --- R-17 CN ageing (RM decision -> issue -> notification) ---------------------------------------
R17 = """
select g.id as gs_id, g.gs_no, pa.name as party_name, d.decision_at,
       c.id as cn_id, c.cn_type_code, c.status as cn_status,
       coalesce(c.cn_no, c.jv_no) as voucher_no, c.issued_at, pn.sent_at as notified_at,
       round((extract(epoch from c.issued_at - d.decision_at) / 86400.0)::numeric, 1)
         as days_decision_to_issue,
       round((extract(epoch from pn.sent_at - c.issued_at) / 86400.0)::numeric, 1)
         as days_issue_to_notification,
       round((extract(epoch from coalesce(pn.sent_at, now()) - d.decision_at) / 86400.0)::numeric,
             1) as days_total,
       st.stage,
       case when st.stage = 'NOTIFIED' then null
            else round((extract(epoch from now()
                                   - coalesce(c.issued_at, c.created_at, d.decision_at))
                        / 86400.0)::numeric, 1) end as days_in_stage
  from public.rm_cn_decisions d
  join public.goods_slips g on g.id = d.gs_id
  left join public.parties pa on pa.id = g.party_id
  left join public.credit_notes c on c.gs_id = d.gs_id and c.status <> 'CANCELLED'
  left join lateral (select n.sent_at from public.party_notifications n
                      where n.gs_id = d.gs_id
                        and (n.credit_note_id = c.id or n.credit_note_id is null)
                      order by n.sent_at limit 1) pn on true
  cross join lateral (select case when c.id is null then 'AWAITING_CN'
                                  when c.issued_at is null then 'AWAITING_ISSUE'
                                  when pn.sent_at is null then 'AWAITING_NOTIFICATION'
                                  else 'NOTIFIED' end as stage) st
 where d.is_current
   and exists (select 1 from public.rm_cn_decision_lines dl
                where dl.decision_id = d.id and dl.decision_code = 'ALLOW_CN')
   and {where}
"""

# --- R-18 User activity / performance ------------------------------------------------------------
R18 = f"""
with {STEP_LABELS_CTE.strip()}
select e.user_id, coalesce(p.full_name, e.user_id::text) as user_name, e.step_code,
       coalesce(sl.label, e.step_code) as step_label, e.action_code,
       count(*)::int as actions,
       count(distinct e.gs_id)::int as gs_count,
       round(avg(e.handling_hours)::numeric, 1) as avg_handling_hours,
       round(max(e.handling_hours)::numeric, 1) as max_handling_hours,
       min(e.acted_at) as first_action_at,
       max(e.acted_at) as last_action_at
  from rms_reports.user_activity_events e
  left join public.profiles p on p.id = e.user_id
  left join step_labels sl on sl.code = e.step_code
 where {_window("e.acted_at")}
   and {{where}}
 group by e.user_id, p.full_name, e.step_code, sl.label, e.action_code
"""  # noqa: S608 - registry SQL; only fixed fragments are interpolated

# --- filter lookups (choices for dropdown filters) -----------------------------------------------
LOOKUPS: dict[str, str] = {
    "states": "select id::text as value, name as label from public.states order by name",
    "stations": (
        "select sn.id::text as value, sn.name || ' (' || st.name || ')' as label "
        "from public.stations sn join public.states st on st.id = sn.state_id order by sn.name"
    ),
    "locations": (
        "select id::text as value, code || ' - ' || name as label "
        "from public.inventory_locations order by code"
    ),
    "technicians": (
        "select id::text as value, display_name as label from public.technicians "
        "order by display_name"
    ),
    "battery_types": (
        "select id::text as value, code || ' - ' || name as label from public.battery_types "
        "order by code"
    ),
    "pcb_suppliers": (
        "select id::text as value, name as label from public.pcb_suppliers order by name"
    ),
    "categories": (
        "select code as value, name as label from public.product_categories order by code"
    ),
    "steps": (
        f"with {STEP_LABELS_CTE.strip()} "  # noqa: S608 - fixed CTE
        "select code as value, label from step_labels order by code"
    ),
}
