-- P2-05 pgTAP: Product-specific inspection, G-06 Enclosed Oval full-opening guard,
-- G-07 reconciliation guard on inspections and goods_slips.
begin;
create extension if not exists pgtap with schema extensions;
select plan(9);

-- 1. Create a test goods slip at status 'INSPECTION'
-- 1. Setup test user and context
create temporary table _ctx as
select 'aaaaaaaa-0000-4000-8000-000000000001'::uuid as inspector_id;

insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data)
select inspector_id, 'pgtap-p205-inspector@example.test', '{"rms_activate": true}'::jsonb, '{"full_name": "Aman Inspector"}'::jsonb
from _ctx;

-- 2. Create a test goods slip
insert into public.goods_slips (
  id, gs_no, workflow_version_id, party_id, state_id, station_id,
  delivery_mode_code, courier_name, docket_no, box_count,
  gate_document_code, gate_doc_no, gate_doc_date, status
) values (
  '11111111-1111-1111-1111-111111111111',
  'GS/2026-27/99001',
  (select id from public.workflow_versions where status = 'PUBLISHED' limit 1),
  (select id from public.parties limit 1),
  (select id from public.states limit 1),
  (select id from public.stations limit 1),
  'COURIER_PARCEL', 'Test Express', 'DOCK-99001', 2,
  'DELIVERY_CHALLAN', 'CH-99001', '2026-11-03', 'ITEMIZATION'
);

-- 3. Create items: one EO (requires_full_opening=true) and one DMT
insert into public.gs_items (
  id, gs_id, line_no, product_id, category_id, documented_qty, received_qty
) values (
  '22222222-2222-2222-2222-222222222222',
  '11111111-1111-1111-1111-111111111111',
  1,
  (select id from public.products where category_id = (select id from public.product_categories where code = 'ENCLOSED_OVAL') limit 1),
  (select id from public.product_categories where code = 'ENCLOSED_OVAL'),
  5, 5
), (
  '33333333-3333-3333-3333-333333333333',
  '11111111-1111-1111-1111-111111111111',
  2,
  (select id from public.products where category_id = (select id from public.product_categories where code = 'DMT') limit 1),
  (select id from public.product_categories where code = 'DMT'),
  10, 10
);

-- AMD-08 (change plan Phase 3): submit the count, then categorize and advance GS to INSPECTION
update public.goods_slips set status = 'CATEGORISATION'
 where id = '11111111-1111-1111-1111-111111111111';
update public.goods_slips
   set category_code = 'RO',
       original_category_code = 'RO',
       categorized_by = (select inspector_id from _ctx),
       categorized_at = now(),
       status = 'INSPECTION'
 where id = '11111111-1111-1111-1111-111111111111';

-- 3. Create draft inspection for EO line without full opening confirmation
insert into public.inspections (
  id, gs_item_id, full_opening_confirmed, status
) values (
  '44444444-4444-4444-4444-444444444444',
  '22222222-2222-2222-2222-222222222222',
  false, 'DRAFT'
);

-- Test 1: G-06 blocks saving allocations for EO without full opening confirmed
select throws_matching(
  format($$
    insert into public.inspection_allocations (
      inspection_id, condition_code, qty, option_item_id
    ) values (
      '44444444-4444-4444-4444-444444444444',
      'EO_OK', 5,
      (select id from public.option_items where code = 'EO_OK')
    )
  $$),
  'G-06',
  'G-06: cannot insert EO allocation when full_opening_confirmed is false'
);

-- Update full_opening_confirmed to true
update public.inspections
   set full_opening_confirmed = true
 where id = '44444444-4444-4444-4444-444444444444';

-- Test 2: G-06 allows saving allocations once full_opening_confirmed is true
select lives_ok(
  format($$
    insert into public.inspection_allocations (
      inspection_id, condition_code, qty, option_item_id
    ) values (
      '44444444-4444-4444-4444-444444444444',
      'EO_OK', 5,
      (select id from public.option_items where code = 'EO_OK')
    )
  $$),
  'G-06: EO allocation succeeds when full_opening_confirmed is true'
);

-- Test 3: G-07 blocks finalising EO line without extraction record
select throws_matching(
  format($$
    update public.inspections
       set status = 'FINAL'
     where id = '44444444-4444-4444-4444-444444444444'
  $$),
  'G-07',
  'G-07: cannot finalise inspection without extraction record'
);

-- Add extraction record for EO with wrong sum (4 != 5)
insert into public.extraction_records (
  gs_item_id, primary_type, packaging_qty, container_qty, reconciled
) values (
  '22222222-2222-2222-2222-222222222222',
  'PACKAGING_EXTRACTED', 4, 0, true
);

-- Test 4: G-07 blocks finalising when extraction sum does not match received_qty
select throws_matching(
  format($$
    update public.inspections
       set status = 'FINAL'
     where id = '44444444-4444-4444-4444-444444444444'
  $$),
  'G-07',
  'G-07: cannot finalise inspection when extraction sum does not match received_qty'
);

-- Fix extraction record for EO (5 = 5)
update public.extraction_records
   set packaging_qty = 5
 where gs_item_id = '22222222-2222-2222-2222-222222222222';

-- Test 5: G-07 allows finalising EO inspection when sums match
select lives_ok(
  format($$
    update public.inspections
       set status = 'FINAL'
     where id = '44444444-4444-4444-4444-444444444444'
  $$),
  'G-07: EO inspection finalises when allocations and extraction match received_qty'
);

-- 4. DMT Line Tests
insert into public.inspections (
  id, gs_item_id, full_opening_confirmed, status
) values (
  '55555555-5555-5555-5555-555555555555',
  '33333333-3333-3333-3333-333333333333',
  false, 'DRAFT'
);

-- Add allocations with sum = 8 (< 10)
insert into public.inspection_allocations (
  inspection_id, condition_code, qty, option_item_id
) values (
  '55555555-5555-5555-5555-555555555555',
  'DMT_OK_PACKED', 8,
  (select id from public.option_items where code = 'DMT_OK_PACKED')
);

insert into public.extraction_records (
  gs_item_id, primary_type, packaging_qty, container_qty, reconciled
) values (
  '33333333-3333-3333-3333-333333333333',
  'CONTAINER_EXTRACTED', 0, 10, true
);

-- Test 6: G-07 blocks DMT finalise when allocation sum != received_qty
select throws_matching(
  format($$
    update public.inspections
       set status = 'FINAL'
     where id = '55555555-5555-5555-5555-555555555555'
  $$),
  'G-07',
  'G-07: cannot finalise DMT inspection when allocation sum (8) != received_qty (10)'
);

-- Add remaining 2 pcs under DMT_DIRTY (total 10) and 3 pcs under DMT_SHORT_QTY (DEC-09: does not consume pieces)
insert into public.inspection_allocations (
  inspection_id, condition_code, qty, option_item_id, system_behavior_snapshot
) values (
  '55555555-5555-5555-5555-555555555555',
  'DMT_DIRTY', 2,
  (select id from public.option_items where code = 'DMT_DIRTY'),
  'TO_TECHNICIAN'
), (
  '55555555-5555-5555-5555-555555555555',
  'DMT_SHORT_QTY', 3,
  (select id from public.option_items where code = 'DMT_SHORT_QTY'),
  'SHORT_QTY'
);

-- Test 7: G-07 allows finalising DMT inspection with DMT_SHORT_QTY excluded from sum check
select lives_ok(
  format($$
    update public.inspections
       set status = 'FINAL'
     where id = '55555555-5555-5555-5555-555555555555'
  $$),
  'G-07: DMT finalisation succeeds with allocations (8+2=10) and DMT_SHORT_QTY excluded'
);

-- Test 8: G-07 on goods_slips allows moving to RM_REVIEW when all lines are FINAL
select lives_ok(
  format($$
    update public.goods_slips
       set status = 'RM_REVIEW'
     where id = '11111111-1111-1111-1111-111111111111'
  $$),
  'G-07 on goods_slips: GS advances to RM_REVIEW when all items are finalized'
);

-- Reset DMT line to DRAFT
update public.inspections
   set status = 'DRAFT'
 where id = '55555555-5555-5555-5555-555555555555';

-- Reset GS back to INSPECTION
update public.goods_slips
   set status = 'INSPECTION'
 where id = '11111111-1111-1111-1111-111111111111';

-- Test 9: G-07 on goods_slips blocks advancing to RM_REVIEW if any line is not FINAL
select throws_matching(
  format($$
    update public.goods_slips
       set status = 'RM_REVIEW'
     where id = '11111111-1111-1111-1111-111111111111'
  $$),
  'G-07',
  'G-07 on goods_slips: cannot advance GS to RM_REVIEW when an item is in DRAFT'
);

select * from finish();
rollback;
