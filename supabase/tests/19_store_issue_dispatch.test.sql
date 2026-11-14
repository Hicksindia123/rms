-- =============================================================================
-- Test File: 19_store_issue_dispatch.test.sql
-- P3-05 store issue & replacement dispatch schema, guards (G-04, DEC-26), and DB triggers.
-- =============================================================================

begin;
select plan(12);

select has_table('public', 'store_issues', 'store_issues table exists');
select has_table('public', 'store_issue_lines', 'store_issue_lines table exists');
select has_table('public', 'replacement_dispatches', 'replacement_dispatches table exists');
select has_table('public', 'replacement_dispatch_lines', 'replacement_dispatch_lines table exists');

select has_trigger('public', 'store_issue_lines', 'trg_store_issue_lines_g04', 'G-04 trigger on store_issue_lines exists');
select has_trigger('public', 'replacement_dispatch_lines', 'trg_replacement_dispatch_lines_guard', 'guard trigger on replacement_dispatch_lines exists');

-- Fixtures for trigger tests
insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data) values
  ('00000000-0000-0000-0000-00000000e501', 'pgtap-p305@example.test',
   '{"rms_activate": true}'::jsonb, '{"full_name": "P305 Test User"}'::jsonb)
on conflict do nothing;

insert into public.product_categories (id, code, name)
values ('00000000-0000-0000-0000-00000000e510', 'P305_PGTAP_CAT', 'P305 pgTAP category')
on conflict do nothing;

insert into public.products (id, code, name, category_id)
values ('00000000-0000-0000-0000-00000000e511', 'P305-PGTAP', 'P305 pgTAP product',
        '00000000-0000-0000-0000-00000000e510')
on conflict do nothing;

insert into public.stock_items (id, item_kind, product_id)
values ('00000000-0000-0000-0000-00000000e512', 'FINISHED_GOOD', '00000000-0000-0000-0000-00000000e511')
on conflict do nothing;

insert into public.stock_lots (id, stock_item_id, condition_class) values
  ('00000000-0000-0000-0000-00000000e520', '00000000-0000-0000-0000-00000000e512', 'FUNCTIONAL_GOOD'),
  ('00000000-0000-0000-0000-00000000e521', '00000000-0000-0000-0000-00000000e512', 'FUNCTIONAL_REPAIRED'),
  ('00000000-0000-0000-0000-00000000e522', '00000000-0000-0000-0000-00000000e512', 'NON_GOOD')
on conflict do nothing;

-- 1. Store issue fixture
insert into public.store_issues (
  id, issue_no, issue_type_code, from_location_id, to_location_id, status, created_by
) values (
  '00000000-0000-0000-0000-00000000e530', 'ISS-PGTAP-001', 'ISSUE_MAIN_STORE',
  (select id from public.inventory_locations where code = 'INTERMEDIATE_STORE'),
  (select id from public.inventory_locations where code = 'MAIN_STORE'),
  'ISSUED', '00000000-0000-0000-0000-00000000e501'
) on conflict do nothing;

-- Functional lot in store issue succeeds
select lives_ok(
  $$insert into public.store_issue_lines (id, issue_id, lot_id, qty)
    values ('00000000-0000-0000-0000-00000000e531', '00000000-0000-0000-0000-00000000e530', '00000000-0000-0000-0000-00000000e520', 2)$$,
  'Functional Good lot accepted into store_issue_lines'
);

-- Non-good lot in store issue fails with G-04
select throws_ok(
  $$insert into public.store_issue_lines (id, issue_id, lot_id, qty)
    values ('00000000-0000-0000-0000-00000000e532', '00000000-0000-0000-0000-00000000e530', '00000000-0000-0000-0000-00000000e522', 1)$$,
  'P0001',
  null,
  'Non-good lot rejected by store_issue_lines G-04 guard'
);

-- 2. Replacement dispatch fixtures
-- Create a GS and GS item for dispatch testing
insert into public.parties (id, code, name)
values ('00000000-0000-0000-0000-00000000e540', 'PRTY-P305', 'Party P305')
on conflict do nothing;

insert into public.goods_slips (
  id, gs_no, party_id, workflow_version_id, status, delivery_mode_code, courier_name, docket_no, category_code, original_category_code, box_count, created_by
) values (
  '00000000-0000-0000-0000-00000000e541', 'GS-PGTAP-P305-01', '00000000-0000-0000-0000-00000000e540',
  (select id from public.workflow_versions limit 1),
  'ITEMIZATION', 'COURIER_PARCEL', 'DTDC', 'DOC-999', 'CSR', 'CSR', 1, '00000000-0000-0000-0000-00000000e501'
) on conflict do nothing;

insert into public.gs_items (
  id, gs_id, line_no, product_id, category_id, received_qty, created_by
) values (
  '00000000-0000-0000-0000-00000000e542', '00000000-0000-0000-0000-00000000e541',
  1, '00000000-0000-0000-0000-00000000e511', '00000000-0000-0000-0000-00000000e510', 5, '00000000-0000-0000-0000-00000000e501'
) on conflict do nothing;

insert into public.replacement_dispatches (
  id, dispatch_no, gs_id, dispatch_type, transporter, dispatched_by
) values
  ('00000000-0000-0000-0000-00000000e550', 'DSP-PGTAP-001', '00000000-0000-0000-0000-00000000e541', 'SEND_NEW', 'BlueDart', '00000000-0000-0000-0000-00000000e501'),
  ('00000000-0000-0000-0000-00000000e551', 'DSP-PGTAP-002', '00000000-0000-0000-0000-00000000e541', 'SEND_REPAIRED', 'Delhivery', '00000000-0000-0000-0000-00000000e501')
on conflict do nothing;

-- SEND_NEW with null lot succeeds (DEC-26)
select lives_ok(
  $$insert into public.replacement_dispatch_lines (dispatch_id, gs_item_id, lot_id, qty)
    values ('00000000-0000-0000-0000-00000000e550', '00000000-0000-0000-0000-00000000e542', null, 2)$$,
  'SEND_NEW dispatch line with null lot_id succeeds (DEC-26)'
);

-- SEND_NEW with non-null lot fails (DEC-26)
select throws_ok(
  $$insert into public.replacement_dispatch_lines (dispatch_id, gs_item_id, lot_id, qty)
    values ('00000000-0000-0000-0000-00000000e550', '00000000-0000-0000-0000-00000000e542', '00000000-0000-0000-0000-00000000e520', 1)$$,
  'P0001',
  null,
  'SEND_NEW dispatch line with non-null lot_id is rejected'
);

-- SEND_REPAIRED with FUNCTIONAL_REPAIRED lot succeeds
select lives_ok(
  $$insert into public.replacement_dispatch_lines (dispatch_id, gs_item_id, lot_id, qty)
    values ('00000000-0000-0000-0000-00000000e551', '00000000-0000-0000-0000-00000000e542', '00000000-0000-0000-0000-00000000e521', 1)$$,
  'SEND_REPAIRED dispatch line with FUNCTIONAL_REPAIRED lot succeeds'
);

-- SEND_REPAIRED with non-repaired lot (FUNCTIONAL_GOOD) fails
select throws_ok(
  $$insert into public.replacement_dispatch_lines (dispatch_id, gs_item_id, lot_id, qty)
    values ('00000000-0000-0000-0000-00000000e551', '00000000-0000-0000-0000-00000000e542', '00000000-0000-0000-0000-00000000e520', 1)$$,
  'P0001',
  null,
  'SEND_REPAIRED dispatch line with non-repaired lot fails'
);

rollback;
