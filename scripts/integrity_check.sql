-- =============================================================================
-- RMS data-integrity checks (master plan §17 "Integrity"; P2-08, extended in P3-08 / P4-06).
--
-- One read-only statement. It returns one row per check with the number of violations and up to
-- five sample rows; a healthy database returns violations = 0 on every row.
--
--   psql "$DB_URL" -v ON_ERROR_STOP=1 -f scripts/integrity_check.sql
--   docker exec -i supabase_db_rms psql -U postgres -f - < scripts/integrity_check.sql
--
-- backend/tests/integration/test_phase2_integrity.py runs this same file after driving real
-- Phase-2 scenarios through the API, and against the whole local database.
--
-- IC-01  Conservation per GS line (§17), once the GS has been categorised (stock exists from
--        categorisation on): Σ balances of the line's lots across ALL locations (dispatched,
--        credited, Main Store, quarantine … are locations, so they stay in the balance)
--        + every quantity that left the ledger from those lots (DISMANTLE_IN consumption, DISPOSE,
--          ADJUST losses, any other exit to no location)
--        − every quantity that entered those lots from outside (ADJUST found pieces, RECEIPT)
--        = received_qty. The INWARD that creates the stock and RECLASSIFY pairs between the
--        line's own lots are excluded. Dismantling OUTPUTS (recovered parts) are separate
--        spare-part lots without a GS line, so they never count (P3-04 ADJUST rule generalised
--        in P3-08).
-- IC-02  No negative stock balance (G-16).
-- IC-03  Ledger = balances: per lot and location, Σ movements in − Σ movements out = balance.
-- IC-04  Every inspected quantity has a lot: each condition graded on a FINAL inspection (except
--        the DEC-09 short-quantity marker, which consumes no piece) has a lot carrying that code.
-- IC-05  Every rejection has its stock movement, on a lot of the same GS line, for the same qty.
-- IC-06  Segregation: Not-allowed / hazard stock never in a FUNCTIONAL location (G-04, G-12);
--        hazard stock only in HAZARD_QUARANTINE or, once disposed (DEC-11), SCRAP_DISPOSED (G-05,
--        §8.5); Pending (BP) stock only in PENDING_HOLD
--        (G-08).
-- IC-07  Shortage recorded: short_qty = max(documented − received, 0) and
--        excess_qty = max(received − documented, 0) (BR-16, DEC-09).
-- IC-08  Lot linkage: a lot's GS line belongs to the lot's GS, and that GS has a GS number (G-01).
-- --- P3-08 (Phase 3 gate) -----------------------------------------------------------------------
-- IC-09  Battery consumption (BR-24, G-10): each technician receiving record with batteries
--        installed has exactly one CONSUME movement of that quantity out of BATTERY_STORE, and
--        every CONSUME movement of a technician receive belongs to such a record. Hence
--        Σ battery CONSUME = Σ batteries_installed.
-- IC-10  Functional locations hold only functional classes (BR-30, G-04, G-12): the Intermediate
--        Store (FUNCTIONAL) holds AS_RECEIVED (awaiting the technician) or FUNCTIONAL_GOOD /
--        FUNCTIONAL_REPAIRED lots; the Main Store only FUNCTIONAL_GOOD / FUNCTIONAL_REPAIRED.
-- IC-11  Every CLOSED GS has a closure record whose frozen checklist snapshot has every applicable
--        item passed (G-15).
-- IC-12  A CLOSED GS has no stock in TRANSIT, PENDING_HOLD or INWARD_STAGING (G-15).
-- =============================================================================
with
checks (code, description) as (
  values
    ('IC-01', 'Per GS line: balances + quantity that left the ledger = received_qty'),
    ('IC-02', 'No negative stock balance'),
    ('IC-03', 'Ledger movements reconcile to stock balances'),
    ('IC-04', 'Every inspected condition quantity has a lot'),
    ('IC-05', 'Every rejection has a matching stock movement'),
    ('IC-06', 'Not-allowed / hazard / pending stock is segregated'),
    ('IC-07', 'Shortage and excess recorded per line'),
    ('IC-08', 'Lots link to a numbered GS and its own line'),
    ('IC-09', 'Battery consumption equals batteries installed'),
    ('IC-10', 'Functional locations hold only functional classes'),
    ('IC-11', 'Closed GS has a passing checklist snapshot'),
    ('IC-12', 'Closed GS has no stock in transit, pending hold or inward staging')
),
lot_balance as (
  select l.gs_item_id, sum(b.qty)::bigint as qty
    from public.stock_lots l
    join public.stock_balances b on b.lot_id = l.id
   where l.gs_item_id is not null
   group by l.gs_item_id
),
line_flow as (
  -- P3-08: net quantity that left the ledger (+) or entered it from outside (−) per GS line,
  -- excluding the INWARD that creates the stock and RECLASSIFY between the line's own lots.
  select l.gs_item_id,
         sum(case when m.to_location_id is null then m.qty else -m.qty end)::bigint as qty
    from public.stock_lots l
    join public.stock_movements m on m.lot_id = l.id
   where l.gs_item_id is not null
     and m.movement_type not in ('INWARD', 'RECLASSIFY')
     and (m.from_location_id is null) <> (m.to_location_id is null)
   group by l.gs_item_id
),
ledger as (
  select lot_id, location_id, sum(qty)::bigint as qty
    from (select lot_id, to_location_id as location_id, qty
            from public.stock_movements where to_location_id is not null
          union all
          select lot_id, from_location_id, -qty
            from public.stock_movements where from_location_id is not null) m
   group by lot_id, location_id
),
violations (code, detail) as (
  -- IC-01
  select 'IC-01', format('%s line %s: received %s, lot balances %s, net left the ledger %s',
                         g.gs_no, gi.line_no, gi.received_qty, coalesce(lb.qty, 0),
                         coalesce(lf.qty, 0))
    from public.gs_items gi
    join public.goods_slips g on g.id = gi.gs_id
    left join lot_balance lb on lb.gs_item_id = gi.id
    left join line_flow lf on lf.gs_item_id = gi.id
   where g.status not in ('GATE_CREATED', 'UNBOXING', 'ITEMIZATION', 'CATEGORISATION', 'CANCELLED')
     and coalesce(lb.qty, 0) + coalesce(lf.qty, 0) <> gi.received_qty
  union all
  -- IC-02
  select 'IC-02', format('lot %s at %s: %s', b.lot_id, il.code, b.qty)
    from public.stock_balances b
    join public.inventory_locations il on il.id = b.location_id
   where b.qty < 0
  union all
  -- IC-03
  select 'IC-03', format('lot %s at %s: ledger %s, balance %s',
                         coalesce(m.lot_id, b.lot_id), coalesce(m.location_id, b.location_id),
                         coalesce(m.qty, 0), coalesce(b.qty, 0))
    from ledger m
    full join public.stock_balances b on b.lot_id = m.lot_id and b.location_id = m.location_id
   where coalesce(m.qty, 0) <> coalesce(b.qty, 0)
  union all
  -- IC-04
  select 'IC-04', format('%s line %s: %s x %s graded but no lot carries the condition',
                         g.gs_no, gi.line_no, a.qty, a.condition_code)
    from public.inspection_allocations a
    join public.inspections i on i.id = a.inspection_id and i.status = 'FINAL'
    join public.gs_items gi on gi.id = i.gs_item_id
    join public.goods_slips g on g.id = gi.gs_id
   where a.qty > 0
     and coalesce(a.system_behavior_snapshot, '') <> 'SHORT_QTY'
     and not exists (select 1 from public.stock_lots l
                      where l.gs_item_id = gi.id and l.source_condition_code = a.condition_code)
  union all
  -- IC-05
  select 'IC-05', format('rejection %s (%s x %s): %s', r.id, r.qty, r.condition_code,
                         case when r.stock_movement_id is null then 'no movement'
                              when m.id is null then 'movement missing'
                              when l.gs_item_id is distinct from r.gs_item_id then 'other line'
                              else format('movement qty %s', m.qty) end)
    from public.rejections r
    left join public.stock_movements m on m.id = r.stock_movement_id
    left join public.stock_lots l on l.id = m.lot_id
   where m.id is null
      or l.gs_item_id is distinct from r.gs_item_id
      or m.qty <> r.qty
  union all
  -- IC-06
  select 'IC-06', format('%s lot %s (pending=%s): %s at %s (%s)',
                         l.condition_class, l.id, l.is_pending, b.qty, il.code, il.location_class)
    from public.stock_balances b
    join public.stock_lots l on l.id = b.lot_id
    join public.inventory_locations il on il.id = b.location_id
   where b.qty > 0
     and ((l.condition_class in ('NOT_ALLOWED', 'HAZARD') and il.location_class = 'FUNCTIONAL')
          or (l.condition_class = 'HAZARD'
              and il.location_class not in ('HAZARD_QUARANTINE', 'SCRAP_DISPOSED'))
          or (l.is_pending and il.location_class <> 'PENDING_HOLD'))
  union all
  -- IC-07
  select 'IC-07', format('%s line %s: documented %s, received %s, short %s, excess %s',
                         g.gs_no, gi.line_no, gi.documented_qty, gi.received_qty,
                         gi.short_qty, gi.excess_qty)
    from public.gs_items gi
    join public.goods_slips g on g.id = gi.gs_id
   where gi.short_qty <> greatest(gi.documented_qty - gi.received_qty, 0)
      or gi.excess_qty <> greatest(gi.received_qty - gi.documented_qty, 0)
  union all
  -- IC-08
  select 'IC-08', format('lot %s: gs %s, line %s', l.id, l.gs_id, l.gs_item_id)
    from public.stock_lots l
    left join public.goods_slips g on g.id = l.gs_id
    left join public.gs_items gi on gi.id = l.gs_item_id
   where l.gs_item_id is not null
     and (gi.id is null or gi.gs_id is distinct from l.gs_id or g.gs_no is null)
  union all
  -- IC-09 (a) a receiving record whose batteries_installed has no / a different CONSUME movement
  select 'IC-09', format('receiving %s: batteries_installed %s, consumed %s (%s)',
                         r.id, coalesce(r.batteries_installed, 0), coalesce(m.qty, 0),
                         coalesce(m.movement_type || ' from ' || fl.code, 'no movement'))
    from public.technician_receiving_records r
    left join public.stock_movements m on m.id = r.battery_stock_movement_id
    left join public.inventory_locations fl on fl.id = m.from_location_id
   where coalesce(r.batteries_installed, 0) <> coalesce(m.qty, 0)
      or (m.id is not null and (m.movement_type <> 'CONSUME' or fl.code <> 'BATTERY_STORE'
                                or m.to_location_id is not null))
  union all
  -- IC-09 (b) a technician-receive CONSUME movement that no receiving record accounts for
  select 'IC-09', format('CONSUME movement %s (%s pcs) of batch %s has no receiving record',
                         m.id, m.qty, m.reference_id)
    from public.stock_movements m
   where m.movement_type = 'CONSUME'
     and m.reference_type = 'TECH_BATCH_RECEIVE'
     and not exists (select 1 from public.technician_receiving_records r
                      where r.battery_stock_movement_id = m.id)
  union all
  -- IC-10
  select 'IC-10', format('%s lot %s: %s at %s (%s)',
                         l.condition_class, l.id, b.qty, il.code, il.location_class)
    from public.stock_balances b
    join public.stock_lots l on l.id = b.lot_id
    join public.inventory_locations il on il.id = b.location_id
   where b.qty > 0
     and ((il.location_class = 'FUNCTIONAL'
           and l.condition_class not in ('AS_RECEIVED', 'FUNCTIONAL_GOOD', 'FUNCTIONAL_REPAIRED'))
          or (il.location_class = 'MAIN_STORE'
              and l.condition_class not in ('FUNCTIONAL_GOOD', 'FUNCTIONAL_REPAIRED')))
  union all
  -- IC-11
  select 'IC-11', format('%s: %s', g.gs_no,
                         case when c.id is null then 'CLOSED without a closure record'
                              when jsonb_typeof(c.checklist_snapshot->'items')
                                   is distinct from 'array'
                                or jsonb_array_length(c.checklist_snapshot->'items') = 0
                              then 'closure snapshot has no checklist items'
                              else 'snapshot has failing items '
                                   || (select string_agg(i->>'code', ', ')
                                         from jsonb_array_elements(c.checklist_snapshot->'items') i
                                        where (i->>'applicable')::boolean
                                          and not (i->>'passed')::boolean) end)
    from public.goods_slips g
    left join public.gs_closures c on c.gs_id = g.id
   where g.status = 'CLOSED'
     and (c.id is null
          or jsonb_typeof(c.checklist_snapshot->'items') is distinct from 'array'
          or jsonb_array_length(c.checklist_snapshot->'items') = 0
          or exists (select 1 from jsonb_array_elements(c.checklist_snapshot->'items') i
                      where (i->>'applicable')::boolean and not (i->>'passed')::boolean))
  union all
  -- IC-12
  select 'IC-12', format('%s lot %s: %s at %s', g.gs_no, l.id, b.qty, il.code)
    from public.goods_slips g
    join public.stock_lots l on l.gs_id = g.id
    join public.stock_balances b on b.lot_id = l.id and b.qty > 0
    join public.inventory_locations il on il.id = b.location_id
   where g.status = 'CLOSED'
     and il.location_class in ('TRANSIT', 'PENDING_HOLD', 'INWARD')
)
select c.code,
       c.description,
       count(v.detail) as violations,
       coalesce((array_agg(v.detail order by v.detail) filter (where v.detail is not null))[1:5],
                '{}') as samples
  from checks c
  left join violations v on v.code = c.code
 group by c.code, c.description
 order by c.code;
