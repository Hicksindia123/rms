-- P2-01 pgTAP tests for Generic Inventory Ledger & Stock Movement Guards
begin;
create extension if not exists pgtap with schema extensions;
select plan(20);

-- Setup test data
do $$
declare
  v_wf_ver_id   uuid;
  v_party_id    uuid;
  v_prod_id     uuid;
  v_cat_id      uuid;
  v_gs_id       uuid;
  v_item_id     uuid;
  v_stock_item  uuid;
  v_loc_inward  uuid;
  v_loc_transit uuid;
  v_loc_func    uuid;
  v_loc_hazard  uuid;
  v_loc_spare   uuid;
  v_loc_main    uuid;
  v_lot_recv    uuid;
  v_lot_na      uuid;
  v_lot_hazard  uuid;
  v_lot_nongood uuid;
  v_lot_pending uuid;
  v_lot_fg      uuid;
begin
  select id into v_wf_ver_id from public.workflow_versions where status = 'PUBLISHED' limit 1;
  select id into v_party_id from public.parties limit 1;
  select id into v_cat_id from public.product_categories where code = 'DMT' limit 1;

  insert into public.products (code, name, category_id, uom)
  values ('TEST-PROD-01', 'Test DMT Thermometer', v_cat_id, 'NOS')
  returning id into v_prod_id;

  -- Locations
  select id into v_loc_inward from public.inventory_locations where location_class = 'INWARD' limit 1;
  select id into v_loc_transit from public.inventory_locations where location_class = 'TRANSIT' limit 1;
  select id into v_loc_func from public.inventory_locations where location_class = 'FUNCTIONAL' limit 1;
  select id into v_loc_hazard from public.inventory_locations where location_class = 'HAZARD_QUARANTINE' limit 1;
  select id into v_loc_spare from public.inventory_locations where location_class = 'SPARE_PARTS' limit 1;
  select id into v_loc_main from public.inventory_locations where location_class = 'MAIN_STORE' limit 1;

  -- Goods slip
  insert into public.goods_slips (
    gs_no, workflow_version_id, party_id, delivery_mode_code, courier_name, docket_no, box_count
  ) values (
    'GS/2026-27/TEST01', v_wf_ver_id, v_party_id, 'COURIER_PARCEL', 'Test Courier', 'TEST-DKT-01', 2
  ) returning id into v_gs_id;

  -- GS item
  insert into public.gs_items (
    gs_id, line_no, product_id, category_id, documented_qty, received_qty
  ) values (
    v_gs_id, 1, v_prod_id, v_cat_id, 10, 10
  ) returning id into v_item_id;

  -- Stock item
  insert into public.stock_items (
    item_kind, product_id
  ) values (
    'FINISHED_GOOD', v_prod_id
  ) returning id into v_stock_item;

  -- Stock lots with various conditions
  insert into public.stock_lots (stock_item_id, gs_id, gs_item_id, condition_class)
  values (v_stock_item, v_gs_id, v_item_id, 'AS_RECEIVED') returning id into v_lot_recv;

  insert into public.stock_lots (stock_item_id, gs_id, gs_item_id, condition_class)
  values (v_stock_item, v_gs_id, v_item_id, 'NOT_ALLOWED') returning id into v_lot_na;

  insert into public.stock_lots (stock_item_id, gs_id, gs_item_id, condition_class)
  values (v_stock_item, v_gs_id, v_item_id, 'HAZARD') returning id into v_lot_hazard;

  insert into public.stock_lots (stock_item_id, gs_id, gs_item_id, condition_class)
  values (v_stock_item, v_gs_id, v_item_id, 'NON_GOOD') returning id into v_lot_nongood;

  insert into public.stock_lots (stock_item_id, gs_id, gs_item_id, condition_class, is_pending)
  values (v_stock_item, v_gs_id, v_item_id, 'AS_RECEIVED', true) returning id into v_lot_pending;

  insert into public.stock_lots (stock_item_id, gs_id, gs_item_id, condition_class)
  values (v_stock_item, v_gs_id, v_item_id, 'FUNCTIONAL_GOOD') returning id into v_lot_fg;
end;
$$;

-- Test 1: Inward stock movement works
select lives_ok(
  format($$
    select rms_private.rms_move_stock(
      p_lot => (select id from public.stock_lots where condition_class = 'AS_RECEIVED' and is_pending = false limit 1),
      p_from => null,
      p_to => (select id from public.inventory_locations where location_class = 'INWARD' limit 1),
      p_qty => 10,
      p_type => 'INWARD',
      p_ref_type => 'GS',
      p_ref_id => (select id from public.goods_slips limit 1),
      p_idem_key => 'test-idem-inward-1',
      p_actor => null,
      p_reason => 'Initial inward'
    );
  $$),
  'rms_move_stock performs valid inward movement'
);

-- Test 2: Balance is credited correctly
select results_eq(
  format($$
    select qty from public.stock_balances
    where lot_id = (select id from public.stock_lots where condition_class = 'AS_RECEIVED' and is_pending = false limit 1)
      and location_id = (select id from public.inventory_locations where location_class = 'INWARD' limit 1)
  $$),
  array[10],
  'stock balance is exactly 10 after inward'
);

-- Test 3: Idempotent replay returns same id and does not double-count balance
select lives_ok(
  format($$
    select rms_private.rms_move_stock(
      p_lot => (select id from public.stock_lots where condition_class = 'AS_RECEIVED' and is_pending = false limit 1),
      p_from => null,
      p_to => (select id from public.inventory_locations where location_class = 'INWARD' limit 1),
      p_qty => 10,
      p_type => 'INWARD',
      p_ref_type => 'GS',
      p_ref_id => (select id from public.goods_slips limit 1),
      p_idem_key => 'test-idem-inward-1',
      p_actor => null,
      p_reason => 'Initial inward'
    );
  $$),
  'idempotent replay of rms_move_stock succeeds'
);

select results_eq(
  format($$
    select qty from public.stock_balances
    where lot_id = (select id from public.stock_lots where condition_class = 'AS_RECEIVED' and is_pending = false limit 1)
      and location_id = (select id from public.inventory_locations where location_class = 'INWARD' limit 1)
  $$),
  array[10],
  'balance remains 10 after idempotent replay'
);

-- Test 4: Idempotency conflict raises G-16
select throws_ok(
  format($$
    select rms_private.rms_move_stock(
      p_lot => (select id from public.stock_lots where condition_class = 'AS_RECEIVED' and is_pending = false limit 1),
      p_from => null,
      p_to => (select id from public.inventory_locations where location_class = 'INWARD' limit 1),
      p_qty => 5,  -- Different quantity
      p_type => 'INWARD',
      p_ref_type => 'GS',
      p_ref_id => (select id from public.goods_slips limit 1),
      p_idem_key => 'test-idem-inward-1',
      p_actor => null,
      p_reason => 'Conflicting movement'
    );
  $$),
  'P0001',
  null,
  'idempotency conflict raises G-16 error'
);

-- Test 5: Insufficient stock balance raises G-16
select throws_ok(
  format($$
    select rms_private.rms_move_stock(
      p_lot => (select id from public.stock_lots where condition_class = 'AS_RECEIVED' and is_pending = false limit 1),
      p_from => (select id from public.inventory_locations where location_class = 'INWARD' limit 1),
      p_to => (select id from public.inventory_locations where location_class = 'TRANSIT' limit 1),
      p_qty => 20,  -- Available is only 10
      p_type => 'TRANSFER_OUT',
      p_ref_type => 'GS',
      p_ref_id => (select id from public.goods_slips limit 1),
      p_idem_key => 'test-idem-insufficient',
      p_actor => null,
      p_reason => 'Overdraft transfer'
    );
  $$),
  'P0001',
  null,
  'insufficient balance raises G-16'
);

-- Test 6: Direct update to negative balance impossible (CHECK qty >= 0)
select throws_ok(
  format($$
    update public.stock_balances
       set qty = -1
     where lot_id = (select id from public.stock_lots where condition_class = 'AS_RECEIVED' and is_pending = false limit 1);
  $$),
  '23514',
  NULL,
  'direct update to negative stock balance violates check constraint'
);

-- Test 7: Guard G-04 raises when NOT_ALLOWED lot moves to FUNCTIONAL
select throws_ok(
  format($$
    select rms_private.rms_move_stock(
      p_lot => (select id from public.stock_lots where condition_class = 'NOT_ALLOWED' limit 1),
      p_from => null,
      p_to => (select id from public.inventory_locations where location_class = 'FUNCTIONAL' limit 1),
      p_qty => 5,
      p_type => 'INWARD',
      p_ref_type => 'GS',
      p_ref_id => (select id from public.goods_slips limit 1),
      p_idem_key => 'test-idem-g04-func',
      p_actor => null,
      p_reason => 'Illegal G-04 functional move'
    );
  $$),
  'P0001',
  null,
  'G-04 raises when NOT_ALLOWED lot attempts to move to FUNCTIONAL location'
);

-- Test 8: Guard G-04 raises when NOT_ALLOWED lot moves to MAIN_STORE
select throws_ok(
  format($$
    select rms_private.rms_move_stock(
      p_lot => (select id from public.stock_lots where condition_class = 'NOT_ALLOWED' limit 1),
      p_from => null,
      p_to => (select id from public.inventory_locations where location_class = 'MAIN_STORE' limit 1),
      p_qty => 5,
      p_type => 'INWARD',
      p_ref_type => 'GS',
      p_ref_id => (select id from public.goods_slips limit 1),
      p_idem_key => 'test-idem-g04-main',
      p_actor => null,
      p_reason => 'Illegal G-04 main store move'
    );
  $$),
  'P0001',
  null,
  'G-04 raises when NOT_ALLOWED lot attempts to move to MAIN_STORE location'
);

-- Test 9: Guard G-05 raises when HAZARD lot moves to non-quarantine location
select throws_ok(
  format($$
    select rms_private.rms_move_stock(
      p_lot => (select id from public.stock_lots where condition_class = 'HAZARD' limit 1),
      p_from => null,
      p_to => (select id from public.inventory_locations where location_class = 'TRANSIT' limit 1),
      p_qty => 2,
      p_type => 'INWARD',
      p_ref_type => 'GS',
      p_ref_id => (select id from public.goods_slips limit 1),
      p_idem_key => 'test-idem-g05-transit',
      p_actor => null,
      p_reason => 'Illegal G-05 transit move'
    );
  $$),
  'P0001',
  null,
  'G-05 raises when HAZARD lot moves to non-quarantine location'
);

-- Test 10: Guard G-05 allows HAZARD lot to move to HAZARD_QUARANTINE
select lives_ok(
  format($$
    select rms_private.rms_move_stock(
      p_lot => (select id from public.stock_lots where condition_class = 'HAZARD' limit 1),
      p_from => null,
      p_to => (select id from public.inventory_locations where location_class = 'HAZARD_QUARANTINE' limit 1),
      p_qty => 2,
      p_type => 'INWARD',
      p_ref_type => 'GS',
      p_ref_id => (select id from public.goods_slips limit 1),
      p_idem_key => 'test-idem-g05-valid',
      p_actor => null,
      p_reason => 'Valid hazard quarantine inward'
    );
  $$),
  'HAZARD lot successfully moves to HAZARD_QUARANTINE location'
);

-- Test 11: Guard G-12 raises when NON_GOOD lot moves to FUNCTIONAL location
select throws_ok(
  format($$
    select rms_private.rms_move_stock(
      p_lot => (select id from public.stock_lots where condition_class = 'NON_GOOD' limit 1),
      p_from => null,
      p_to => (select id from public.inventory_locations where location_class = 'FUNCTIONAL' limit 1),
      p_qty => 3,
      p_type => 'INWARD',
      p_ref_type => 'GS',
      p_ref_id => (select id from public.goods_slips limit 1),
      p_idem_key => 'test-idem-g12-func',
      p_actor => null,
      p_reason => 'Illegal non-good to functional move'
    );
  $$),
  'P0001',
  null,  -- Note: G-04 and G-12 both guard this boundary; G-04 checks condition in NOT_ALLOWED/NON_GOOD/SCRAP
  'Guard blocks NON_GOOD lot from entering FUNCTIONAL location'
);

-- Test 12: Guard G-08 raises when Pending lot moves to TRANSIT
select throws_ok(
  format($$
    select rms_private.rms_move_stock(
      p_lot => (select id from public.stock_lots where is_pending = true limit 1),
      p_from => null,
      p_to => (select id from public.inventory_locations where location_class = 'TRANSIT' limit 1),
      p_qty => 1,
      p_type => 'INWARD',
      p_ref_type => 'GS',
      p_ref_id => (select id from public.goods_slips limit 1),
      p_idem_key => 'test-idem-g08-transit',
      p_actor => null,
      p_reason => 'Illegal pending to transit move'
    );
  $$),
  'P0001',
  null,
  'G-08 raises when Pending (BP) lot attempts to move to TRANSIT'
);

-- Test 13: Guard G-08 raises when Pending lot moves to FUNCTIONAL
select throws_ok(
  format($$
    select rms_private.rms_move_stock(
      p_lot => (select id from public.stock_lots where is_pending = true limit 1),
      p_from => null,
      p_to => (select id from public.inventory_locations where location_class = 'FUNCTIONAL' limit 1),
      p_qty => 1,
      p_type => 'INWARD',
      p_ref_type => 'GS',
      p_ref_id => (select id from public.goods_slips limit 1),
      p_idem_key => 'test-idem-g08-func',
      p_actor => null,
      p_reason => 'Illegal pending to functional move'
    );
  $$),
  'P0001',
  null,
  'G-08 raises when Pending (BP) lot attempts to move to FUNCTIONAL'
);

-- Test 14: stock_movements is insert-only (UPDATE fails)
select throws_ok(
  $$
    update public.stock_movements
       set reason = 'Attempted update'
     where idempotency_key = 'test-idem-inward-1';
  $$,
  'P0001',
  null,
  'updating stock_movements triggers immutability exception'
);

-- Test 15: stock_movements is insert-only (DELETE fails)
select throws_ok(
  $$
    delete from public.stock_movements
     where idempotency_key = 'test-idem-inward-1';
  $$,
  'P0001',
  null,
  'deleting from stock_movements triggers immutability exception'
);

-- Test 16: inventory_locations.location_class cannot change once balance > 0
select throws_ok(
  format($$
    update public.inventory_locations
       set location_class = 'SPARE_PARTS'
     where id = (select id from public.inventory_locations where location_class = 'INWARD' limit 1);
  $$),
  'P0001',
  null,
  'changing location_class on location with positive stock balance raises exception'
);

-- Test 17: Valid reclassification (AS_RECEIVED -> FUNCTIONAL_GOOD in INWARD location)
select lives_ok(
  format($$
    select rms_private.rms_reclassify_lot(
      p_source_lot => (select id from public.stock_lots where condition_class = 'AS_RECEIVED' and is_pending = false limit 1),
      p_target_lot => (select id from public.stock_lots where condition_class = 'FUNCTIONAL_GOOD' limit 1),
      p_location => (select id from public.inventory_locations where location_class = 'INWARD' limit 1),
      p_qty => 3,
      p_ref_type => 'GS',
      p_ref_id => (select id from public.goods_slips limit 1),
      p_idem_key => 'test-idem-reclass-valid',
      p_actor => null,
      p_reason => 'Reclassifying received to functional good'
    );
  $$),
  'valid reclassification succeeds and produces movement pair'
);

-- Test 18: Balances updated correctly after reclassification
select results_eq(
  format($$
    select qty from public.stock_balances
    where lot_id = (select id from public.stock_lots where condition_class = 'AS_RECEIVED' and is_pending = false limit 1)
      and location_id = (select id from public.inventory_locations where location_class = 'INWARD' limit 1)
  $$),
  array[7],
  'source lot balance deducted to 7 after reclassifying 3'
);

select results_eq(
  format($$
    select qty from public.stock_balances
    where lot_id = (select id from public.stock_lots where condition_class = 'FUNCTIONAL_GOOD' limit 1)
      and location_id = (select id from public.inventory_locations where location_class = 'INWARD' limit 1)
  $$),
  array[3],
  'target lot balance credited to 3 after reclassifying 3'
);

rollback;
