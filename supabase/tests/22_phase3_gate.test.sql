-- =============================================================================
-- 22_phase3_gate.test.sql — P3-08 Phase 3 gate: DB behaviour fixed forward in
-- 20261105000400_p3_08_gate_fixes.sql (G-13 at every status, JV_ONLY provenance, lot-linked
-- scrap disposal needs its DISPOSE movement — DEC-11 / DEC-18).
-- =============================================================================
begin;
select plan(9);

set local session_replication_role = replica;

insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data) values
  ('00000000-0000-0000-0000-00000000f801', 'pgtap-p308@example.test',
   '{"rms_activate": true}'::jsonb, '{"full_name": "P308 Test User"}'::jsonb);
insert into public.profiles (id, full_name) values
  ('00000000-0000-0000-0000-00000000f801', 'P308 Test User') on conflict do nothing;
insert into public.parties (id, code, name) values
  ('00000000-0000-0000-0000-00000000f802', 'PTY-P308', 'Party P308');
insert into public.products (id, code, name, category_id)
select '00000000-0000-0000-0000-00000000f811', 'P308-PRS', 'P308 Prismatic', id
  from public.product_categories where code = 'PRISMATIC';
insert into public.stock_items (id, item_kind, product_id) values
  ('00000000-0000-0000-0000-00000000f812', 'FINISHED_GOOD', '00000000-0000-0000-0000-00000000f811');
insert into public.goods_slips (
  id, gs_no, party_id, workflow_version_id, status, delivery_mode_code, courier_name, docket_no,
  box_count, carton_count, created_by
) values (
  '00000000-0000-0000-0000-00000000f830', 'GS-PGTAP-P308', '00000000-0000-0000-0000-00000000f802',
  (select id from public.workflow_versions where status = 'PUBLISHED' limit 1),
  'IN_PROCESS', 'COURIER_PARCEL', 'BlueDart', 'DKT-P308', 1, 1, '00000000-0000-0000-0000-00000000f801'
);
insert into public.gs_items (id, gs_id, line_no, product_id, category_id, documented_qty,
                             received_qty, created_by)
select '00000000-0000-0000-0000-00000000f831', '00000000-0000-0000-0000-00000000f830', 1,
       '00000000-0000-0000-0000-00000000f811', id, 3, 3, '00000000-0000-0000-0000-00000000f801'
  from public.product_categories where code = 'PRISMATIC';
insert into public.stock_lots (id, stock_item_id, gs_id, gs_item_id, condition_class) values
  ('00000000-0000-0000-0000-00000000f840', '00000000-0000-0000-0000-00000000f812',
   '00000000-0000-0000-0000-00000000f830', '00000000-0000-0000-0000-00000000f831', 'HAZARD');
insert into public.rm_cn_decisions (id, gs_id, decision_by, is_current) values
  ('00000000-0000-0000-0000-00000000f850', '00000000-0000-0000-0000-00000000f830',
   '00000000-0000-0000-0000-00000000f801', true);
insert into public.rm_cn_decision_lines (decision_id, gs_item_id, decision_code, qty) values
  ('00000000-0000-0000-0000-00000000f850', '00000000-0000-0000-0000-00000000f831', 'ALLOW_CN', 2);

set local session_replication_role = origin;

-- G-13 (P3-08): enforced as soon as the portal result is recorded, whatever the status.
select throws_matching(
  $$ insert into public.credit_notes (gs_id, cn_type_code, gst_portal_code, status, created_by)
     values ('00000000-0000-0000-0000-00000000f830', 'GENERAL_CN', 'GST_NOT_REFLECTED', 'DRAFT',
             '00000000-0000-0000-0000-00000000f801') $$,
  'G-13.*permits only JV_ONLY',
  'G-13: a DRAFT General CN with the return NOT reflected is rejected (only a JV)');

select lives_ok(
  $$ insert into public.credit_notes (id, gs_id, cn_type_code, gst_portal_code, status, created_by)
     values ('00000000-0000-0000-0000-00000000f860', '00000000-0000-0000-0000-00000000f830',
             'GST_CN', null, 'DRAFT', '00000000-0000-0000-0000-00000000f801') $$,
  'G-13: a GST CN draft before the portal check is allowed');

select throws_matching(
  $$ update public.credit_notes set status = 'VERIFIED'
      where id = '00000000-0000-0000-0000-00000000f860' $$,
  'G-13.*GST Credit Note requires return to be reflected',
  'G-13: a GST CN cannot be verified while the portal result is missing');

select throws_matching(
  $$ update public.credit_notes set gst_portal_code = 'GST_NOT_REFLECTED'
      where id = '00000000-0000-0000-0000-00000000f860' $$,
  'G-13',
  'G-13: recording NOT reflected on a GST CN without switching to JV is rejected');

select lives_ok(
  $$ update public.credit_notes set gst_portal_code = 'GST_NOT_REFLECTED', cn_type_code = 'JV_ONLY'
      where id = '00000000-0000-0000-0000-00000000f860' $$,
  'G-13: NOT reflected together with JV_ONLY is accepted');

-- JV_ONLY provenance: a system CN type, not a workbook row.
select is(
  (select oi.source_ref from public.option_items oi
     join public.option_sets os on os.id = oi.option_set_id
    where os.code = 'CN_TYPE' and oi.code = 'JV_ONLY'),
  '§8.6 / BR-34 / DEC-23 [ARCH]',
  'JV_ONLY is tagged as the §8.6 system CN type, not DD r76');

-- DEC-11 / DEC-18: a lot-linked scrap record is DISPOSED only with its stock movement.
insert into public.scrap_records (id, lot_id, qty_pieces, hazardous, disposal_status, created_by)
values ('00000000-0000-0000-0000-00000000f870', '00000000-0000-0000-0000-00000000f840', 1, true,
        'MARKED', '00000000-0000-0000-0000-00000000f801');

select throws_ok(
  $$ update public.scrap_records
        set disposal_status = 'DISPOSED', manifest_ref = 'MNF-P308', disposed_at = now()
      where id = '00000000-0000-0000-0000-00000000f870' $$,
  '23514', null,
  'DEC-11: disposing lot-linked scrap without its DISPOSE movement is rejected');

insert into public.scrap_records (id, qty_pieces, hazardous, disposal_status, created_by)
values ('00000000-0000-0000-0000-00000000f871', 1, true, 'MARKED',
        '00000000-0000-0000-0000-00000000f801');
select throws_ok(
  $$ update public.scrap_records set disposal_status = 'DISPOSED', disposed_at = now()
      where id = '00000000-0000-0000-0000-00000000f871' $$,
  '23514', null,
  'DEC-11: hazardous scrap (no lot) still needs a manifest');

select has_index('public', 'scrap_records', 'scrap_records_lot_idx', 'scrap_records.lot_id is indexed');

select * from finish();
rollback;
