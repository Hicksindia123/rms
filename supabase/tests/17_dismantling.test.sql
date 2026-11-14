-- =============================================================================
-- Test File: 17_dismantling.test.sql
-- Description: pgTAP tests for Stage-4 Dismantling & Parts Recovery (BR-26..BR-29, G-11, DEC-11, DEC-18)
-- =============================================================================

begin;
select plan(15);

-- 1. Schema: Check tables exist
select has_table('public', 'dismantle_batches', 'dismantle_batches table exists');
select has_table('public', 'dismantle_inputs', 'dismantle_inputs table exists');
select has_table('public', 'recovered_parts', 'recovered_parts table exists');
select has_table('public', 'scrap_records', 'scrap_records table exists');

-- 2. Masters exist
select is(
  (select count(*)::int from public.storage_containers where container_type = 'PARTS'),
  5,
  '5 parts containers seeded (4 dedicated + 1 partitioned)'
);

select is(
  (select count(*)::int from public.container_partitions),
  4,
  '4 container partitions seeded for multi-container'
);

select is(
  (select count(*)::int from public.pcb_suppliers),
  2,
  '2 initial PCB suppliers seeded'
);

select is(
  (select count(*)::int from public.pcb_models),
  2,
  '2 initial PCB models seeded'
);

-- Users & Master setup
insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data) values
  ('00000000-0000-0000-0000-00000000d401', 'pgtap-p303-tech@example.test',
   '{"rms_activate": true}'::jsonb, '{"full_name": "Recovery Tech"}'::jsonb)
on conflict do nothing;

-- Fixture Goods Slip and Lots
set local session_replication_role = replica;
-- AMD-03 (change plan Phase 2): triggers are off here, so carton_count is set explicitly.
insert into public.goods_slips (id, gs_no, workflow_version_id, delivery_mode_code, courier_name,
                                docket_no, box_count, carton_count, status)
select '00000000-0000-0000-0000-00000000d402', 'PGTAP/P303/0001', v.id, 'COURIER_PARCEL', 'BlueDart',
       'PGTAP-P303', 1, 1, 'IN_PROCESS'
  from public.workflow_versions v where v.status = 'PUBLISHED' limit 1
on conflict do nothing;

insert into public.stock_items (id, item_kind, product_id)
select '00000000-0000-0000-0000-00000000d403', 'FINISHED_GOOD', p.id
  from public.products p limit 1
on conflict do nothing;

insert into public.stock_lots (id, stock_item_id, gs_id, condition_class)
values ('00000000-0000-0000-0000-00000000d404', '00000000-0000-0000-0000-00000000d403',
        '00000000-0000-0000-0000-00000000d402', 'NON_GOOD')
on conflict do nothing;

set local session_replication_role = default;

-- 3. G-11: PCB without model/supplier throws check violation
do $$
declare
  v_tech_id uuid := '00000000-0000-0000-0000-00000000d401';
  v_batch_id uuid;
  v_dummy_lot uuid := '00000000-0000-0000-0000-00000000d404';
  v_cont_id uuid;
  v_sup_id uuid;
  v_model_id uuid;
begin
  select id into v_cont_id from public.storage_containers where code = 'CONT-PARTS-PCB-01';
  select id into v_sup_id from public.pcb_suppliers limit 1;
  select id into v_model_id from public.pcb_models limit 1;

  insert into public.dismantle_batches (batch_no, technician_profile_id, storage_method_code)
  values ('DSM-TEST-001', v_tech_id, 'DEDICATED_CONTAINERS')
  returning id into v_batch_id;

  -- Test 1: TIP part without PCB fields succeeds
  insert into public.recovered_parts (batch_id, part_type, qty, container_id, lot_id)
  values (v_batch_id, 'TIP', 5, v_cont_id, v_dummy_lot);

  -- Test 2: PCB with both model and supplier succeeds
  insert into public.recovered_parts (batch_id, part_type, qty, pcb_model_id, pcb_supplier_id, container_id, lot_id)
  values (v_batch_id, 'PCB', 3, v_model_id, v_sup_id, v_cont_id, v_dummy_lot);
end $$;

select pass('TIP without PCB fields and PCB with both fields succeeded');

-- G-11 failure test: PCB without model
select throws_matching(
  $$
  insert into public.recovered_parts (
    batch_id, part_type, qty, pcb_supplier_id, container_id, lot_id
  ) values (
    (select id from public.dismantle_batches where batch_no = 'DSM-TEST-001'),
    'PCB', 1, (select id from public.pcb_suppliers limit 1),
    (select id from public.storage_containers limit 1),
    '00000000-0000-0000-0000-00000000d404'::uuid
  )
  $$,
  'violates check constraint "recovered_parts_pcb_guard"',
  'G-11: PCB without model fails check constraint'
);

-- G-11 failure test: PCB without supplier
select throws_matching(
  $$
  insert into public.recovered_parts (
    batch_id, part_type, qty, pcb_model_id, container_id, lot_id
  ) values (
    (select id from public.dismantle_batches where batch_no = 'DSM-TEST-001'),
    'PCB', 1, (select id from public.pcb_models limit 1),
    (select id from public.storage_containers limit 1),
    '00000000-0000-0000-0000-00000000d404'::uuid
  )
  $$,
  'violates check constraint "recovered_parts_pcb_guard"',
  'G-11: PCB without supplier fails check constraint'
);

-- Storage reference failure test: missing both container and partition
select throws_matching(
  $$
  insert into public.recovered_parts (
    batch_id, part_type, qty, lot_id
  ) values (
    (select id from public.dismantle_batches where batch_no = 'DSM-TEST-001'),
    'WIRE', 2, '00000000-0000-0000-0000-00000000d404'::uuid
  )
  $$,
  'violates check constraint "recovered_parts_storage_ref"',
  'Recovered part without container or partition fails check constraint'
);

-- 4. DEC-11: Hazardous scrap disposal without manifest fails
do $$
begin
  -- Marked hazardous scrap succeeds
  insert into public.scrap_records (batch_id, qty_pieces, hazardous, disposal_status)
  values (
    (select id from public.dismantle_batches where batch_no = 'DSM-TEST-001'),
    2, true, 'MARKED'
  );
end $$;

select pass('Marked hazardous scrap without manifest succeeded');

select throws_matching(
  $$
  insert into public.scrap_records (
    batch_id, qty_pieces, hazardous, disposal_status, manifest_ref
  ) values (
    (select id from public.dismantle_batches where batch_no = 'DSM-TEST-001'),
    2, true, 'DISPOSED', null
  )
  $$,
  'violates check constraint "scrap_records_hazardous_manifest"',
  'DEC-11: Hazardous scrap disposed without manifest fails check constraint'
);

-- Hazardous scrap disposed with manifest succeeds
do $$
begin
  insert into public.scrap_records (
    batch_id, qty_pieces, hazardous, disposal_status, manifest_ref, disposed_at
  ) values (
    (select id from public.dismantle_batches where batch_no = 'DSM-TEST-001'),
    2, true, 'DISPOSED', 'HAZ-MAN-2026-001', now()
  );
end $$;

select pass('Hazardous scrap disposed with manifest succeeds');

select * from finish();
rollback;
