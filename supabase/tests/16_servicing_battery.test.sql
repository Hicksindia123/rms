-- =============================================================================
-- pgTAP Test: 16_servicing_battery.test.sql
-- Prompt: P3-02 — Technician allotment & receiving, battery inventory & consumption,
-- cleaning & classification (migration 20261104000200).
-- =============================================================================

begin;
select plan(16);

-- 1. Tables exist
select has_table('public', 'battery_receipts', 'battery_receipts table exists');
select has_table('public', 'battery_adjustments', 'battery_adjustments table exists');
select has_table('public', 'technician_batches', 'technician_batches table exists');
select has_table('public', 'technician_batch_lines', 'technician_batch_lines table exists');
select has_table('public', 'technician_receiving_records', 'technician_receiving_records table exists');

-- 2. BATTERY_STORE location exists
select is(
  (select location_class from public.inventory_locations where code = 'BATTERY_STORE'),
  'SPARE_PARTS',
  'BATTERY_STORE location exists with location_class SPARE_PARTS'
);

-- 3. stock_lots.gs_id is nullable
select col_is_null('public', 'stock_lots', 'gs_id', 'stock_lots.gs_id is nullable for general spare parts / batteries');

-- 4. Seeded battery types
select ok(
  exists(select 1 from public.battery_types where code = 'LR44'),
  'Battery type LR44 is seeded'
);

-- Users & Master setup
insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data) values
  ('00000000-0000-0000-0000-00000000d101', 'pgtap-p302-coord@example.test',
   '{"rms_activate": true}'::jsonb, '{"full_name": "Aman Coord"}'::jsonb);

-- Technician
insert into public.technicians (id, display_name) values
  ('00000000-0000-0000-0000-00000000d102', 'PGTAP Tech')
on conflict do nothing;

-- Fixture Goods Slip and Lots
set local session_replication_role = replica;
-- AMD-03 (change plan Phase 2): triggers are off here, so carton_count is set explicitly.
insert into public.goods_slips (id, gs_no, workflow_version_id, delivery_mode_code, courier_name,
                                docket_no, box_count, carton_count, status)
select '00000000-0000-0000-0000-00000000d201', 'PGTAP/P302/0001', v.id, 'COURIER_PARCEL', 'BlueDart',
       'PGTAP-P302', 1, 1, 'IN_PROCESS'
  from public.workflow_versions v where v.status = 'PUBLISHED' limit 1;

insert into public.stock_items (id, item_kind, product_id)
select '00000000-0000-0000-0000-00000000d202', 'FINISHED_GOOD', p.id from public.products p limit 1;

insert into public.stock_lots (id, stock_item_id, gs_id, condition_class)
values ('00000000-0000-0000-0000-00000000d203', '00000000-0000-0000-0000-00000000d202',
        '00000000-0000-0000-0000-00000000d201', 'AS_RECEIVED');

insert into public.technician_batches (id, batch_no, technician_id, entry_by, status) values
  ('00000000-0000-0000-0000-00000000d301', 'TB/2026-27/99999',
   '00000000-0000-0000-0000-00000000d102',
   '00000000-0000-0000-0000-00000000d101', 'ALLOTTED');

insert into public.technician_batch_lines (id, batch_id, lot_id, qty_allotted, qty_received) values
  ('00000000-0000-0000-0000-00000000d302',
   '00000000-0000-0000-0000-00000000d301',
   '00000000-0000-0000-0000-00000000d203', 6, 0);

set local session_replication_role = origin;

-- 5. DB Guard G-10 test: BATTERY_REPLACED requires pieces_checked > 0 and batteries_installed > 0 and battery_type
select throws_matching(
  $$
  insert into public.technician_receiving_records (
    batch_id, batch_line_id, qty_received, battery_check_code, pieces_checked, batteries_installed,
    functional_good_qty, entry_by
  ) values (
    '00000000-0000-0000-0000-00000000d301',
    '00000000-0000-0000-0000-00000000d302',
    6, 'BATTERY_REPLACED', 6, 0, 6, '00000000-0000-0000-0000-00000000d101'
  )
  $$,
  'g10_battery_counts_check',
  'G-10 DB check rejects BATTERY_REPLACED with batteries_installed = 0'
);

select throws_matching(
  $$
  insert into public.technician_receiving_records (
    batch_id, batch_line_id, qty_received, battery_check_code, pieces_checked, batteries_installed,
    functional_good_qty, entry_by
  ) values (
    '00000000-0000-0000-0000-00000000d301',
    '00000000-0000-0000-0000-00000000d302',
    6, 'BATTERY_REPLACED', 0, 4, 6, '00000000-0000-0000-0000-00000000d101'
  )
  $$,
  'g10_battery_counts_check',
  'G-10 DB check rejects BATTERY_REPLACED with pieces_checked = 0'
);

select throws_matching(
  $$
  insert into public.technician_receiving_records (
    batch_id, batch_line_id, qty_received, battery_check_code, pieces_checked, batteries_installed,
    battery_type_id, functional_good_qty, entry_by
  ) values (
    '00000000-0000-0000-0000-00000000d301',
    '00000000-0000-0000-0000-00000000d302',
    6, 'BATTERY_REPLACED', 6, 4, null, 6, '00000000-0000-0000-0000-00000000d101'
  )
  $$,
  'g10_battery_counts_check',
  'G-10 DB check rejects BATTERY_REPLACED with missing battery_type_id'
);

-- 6. DEC-17 test: PERMANENT_SCRATCHES forces NON_SELLABLE
select throws_matching(
  $$
  insert into public.technician_receiving_records (
    batch_id, batch_line_id, qty_received, cleaning_code, functional_good_qty, non_sellable_qty, entry_by
  ) values (
    '00000000-0000-0000-0000-00000000d301',
    '00000000-0000-0000-0000-00000000d302',
    6, 'PERMANENT_SCRATCHES', 4, 2, '00000000-0000-0000-0000-00000000d101'
  )
  $$,
  'dec17_permanent_scratches_check',
  'DEC-17 DB check rejects PERMANENT_SCRATCHES if any piece is classified functional_good'
);

-- Valid PERMANENT_SCRATCHES passes DB check
select lives_ok(
  $$
  insert into public.technician_receiving_records (
    id, batch_id, batch_line_id, qty_received, cleaning_code, functional_good_qty, non_sellable_qty, entry_by
  ) values (
    '00000000-0000-0000-0000-00000000d401',
    '00000000-0000-0000-0000-00000000d301',
    '00000000-0000-0000-0000-00000000d302',
    6, 'PERMANENT_SCRATCHES', 0, 6, '00000000-0000-0000-0000-00000000d101'
  )
  $$,
  'DEC-17 DB check allows PERMANENT_SCRATCHES when all 6 pieces are classified non_sellable'
);

-- 7. Allocation sum check: Σ allocations = qty_received
select throws_matching(
  $$
  insert into public.technician_receiving_records (
    batch_id, batch_line_id, qty_received, functional_good_qty, functional_repaired_qty, entry_by
  ) values (
    '00000000-0000-0000-0000-00000000d301',
    '00000000-0000-0000-0000-00000000d302',
    6, 3, 2, '00000000-0000-0000-0000-00000000d101'
  )
  $$,
  'technician_receiving_records_check',
  'Allocation sum mismatch (5 != 6) is rejected by DB check'
);

-- 8. Custody transfer DEC-34 auto-acceptance for TECHNICIAN_ALLOTMENT:
-- Initiator and receiver can be the same user when purpose_code = 'TECHNICIAN_ALLOTMENT'
set local session_replication_role = replica;
insert into public.custody_transfers (
  id, transfer_no, from_location_id, to_location_id, mode_code, status, stock_moved,
  initiated_by, purpose_code
) select
  '00000000-0000-0000-0000-00000000d501', 'PGTAP/ALLOT/001',
  (select id from public.inventory_locations where code = 'INTERMEDIATE_STORE'),
  (select id from public.inventory_locations where code = 'TECHNICIAN_BENCH'),
  'PHYSICAL_AND_DIGITAL', 'INITIATED', true,
  '00000000-0000-0000-0000-00000000d101', 'TECHNICIAN_ALLOTMENT';

insert into public.custody_transfer_lines (transfer_id, lot_id, qty_sent, qty_counted)
values ('00000000-0000-0000-0000-00000000d501', '00000000-0000-0000-0000-00000000d203', 6, 6);
set local session_replication_role = origin;

select lives_ok(
  $$
  update public.custody_transfers
     set status = 'ACCEPTED',
         acceptance_code = 'ACCEPTED_VERIFIED',
         accepted_by = '00000000-0000-0000-0000-00000000d101',
         accepted_at = now()
   where id = '00000000-0000-0000-0000-00000000d501'
  $$,
  'DEC-34: Coordinator can auto-accept transfer on behalf of technician (same initiated_by and accepted_by)'
);

-- Normal transfer without technician purpose still enforces segregation of duties
set local session_replication_role = replica;
insert into public.custody_transfers (
  id, transfer_no, from_location_id, to_location_id, mode_code, status, stock_moved,
  initiated_by, purpose_code
) select
  '00000000-0000-0000-0000-00000000d502', 'PGTAP/NORM/001',
  (select id from public.inventory_locations where code = 'INTERMEDIATE_STORE'),
  (select id from public.inventory_locations where code = 'MAIN_STORE'),
  'PHYSICAL_AND_DIGITAL', 'INITIATED', true,
  '00000000-0000-0000-0000-00000000d101', 'STEP4_HANDOVER';

insert into public.custody_transfer_lines (transfer_id, lot_id, qty_sent, qty_counted)
values ('00000000-0000-0000-0000-00000000d502', '00000000-0000-0000-0000-00000000d203', 6, 6);
set local session_replication_role = origin;

select throws_matching(
  $$
  update public.custody_transfers
     set status = 'ACCEPTED',
         acceptance_code = 'ACCEPTED_VERIFIED',
         accepted_by = '00000000-0000-0000-0000-00000000d101',
         accepted_at = now()
   where id = '00000000-0000-0000-0000-00000000d502'
  $$,
  'SEGREGATION_OF_DUTIES',
  'Normal transfer rejects self-acceptance under segregation of duties'
);

rollback;
