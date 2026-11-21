-- Phase P4 pgTAP (docs/RMS_PHASE_PROMPTS_20-11-2026.md, DEC-64; migration 20261120000500):
-- categorisation lock, edit window after the lock (Super Admin / Management until the first
-- routing, G-19 at commit), Complete Sales Return on hold (Q11), revision reasons.
begin;
create extension if not exists pgtap with schema extensions;
select plan(12);

-- Actors: a Replacement Executive (INWARD_VERIFIER) and a Management user (itemization.configure).
insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data) values
  ('aaaaaaaa-0000-4000-8000-0000000000e1', 'pgtap-p4-re@example.test', '{"rms_activate": true}', '{"full_name": "P4 RE"}'),
  ('aaaaaaaa-0000-4000-8000-0000000000e2', 'pgtap-p4-mgmt@example.test', '{"rms_activate": true}', '{"full_name": "P4 Mgmt"}');
insert into public.user_roles (user_id, role_id)
select 'aaaaaaaa-0000-4000-8000-0000000000e1'::uuid, id from public.roles where code = 'INWARD_VERIFIER'
union all
select 'aaaaaaaa-0000-4000-8000-0000000000e2'::uuid, id from public.roles where code = 'MANAGEMENT';

create temp table _p4 as
select v.id as wv,
       (select p.id from public.products p
         where exists (select 1 from rms_private.resolve_item_field_profile(p.id) r
                        where r.field_group = 'CATEGORISATION') limit 1) as product
  from public.workflow_versions v
  join public.workflow_definitions d on d.id = v.workflow_definition_id and d.code = 'RMS_STANDARD'
 where v.status = 'PUBLISHED';

insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count, status)
select g, wv, 'COURIER_PARCEL', 'A', g, 1, 'ITEMIZATION'
  from _p4, (values ('PGTAP-P4-LOCK'), ('PGTAP-P4-CSR'), ('PGTAP-P4-RO')) as v(g);
insert into public.gs_items (gs_id, line_no, product_id, category_id, documented_qty, received_qty)
select g.id, 1, p.id, p.category_id, 4, 4
  from public.goods_slips g, _p4 join public.products p on p.id = _p4.product
 where g.gs_no like 'PGTAP-P4-%';

-- Lock: Replacement chosen, split conserved, stamp.
update public.goods_slips set category_code = 'RO', original_category_code = 'RO', status = 'CATEGORISATION'
 where gs_no = 'PGTAP-P4-LOCK';
insert into public.gs_item_buckets (gs_item_id, field_id, qty)
select i.id, (select r.field_id from rms_private.resolve_item_field_profile(i.product_id) r
               where r.field_group = 'CATEGORISATION' limit 1), 4
  from public.gs_items i join public.goods_slips g on g.id = i.gs_id where g.gs_no = 'PGTAP-P4-LOCK';
select throws_like(
  $$update public.goods_slips set status = 'PENDING_TRANSFER_SLIP' where gs_no = 'PGTAP-P4-LOCK'$$,
  'DEC-64:%lock stamp%', 'DEC-64: the lock needs its stamp');
select lives_ok(
  $$update public.goods_slips set status = 'PENDING_TRANSFER_SLIP', categorisation_locked_at = now(),
           categorisation_locked_by = 'aaaaaaaa-0000-4000-8000-0000000000e1'
     where gs_no = 'PGTAP-P4-LOCK'$$,
  'DEC-64: CATEGORISATION -> PENDING_TRANSFER_SLIP with the stamp and G-19');

-- Edit window after the lock (DEC-64 d).
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000000e1', true);
select throws_like(
  $$update public.gs_items set documented_qty = 5
     where gs_id = (select id from public.goods_slips where gs_no = 'PGTAP-P4-LOCK')$$,
  'DEC-64:%Super Admin or Management%', 'DEC-64: the Replacement Executive cannot edit after the lock');
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000000e2', true);
select lives_ok(
  $$update public.gs_items set documented_qty = 5
     where gs_id = (select id from public.goods_slips where gs_no = 'PGTAP-P4-LOCK')$$,
  'DEC-64: Management edits a locked line');
select throws_like(
  $q$do $d$ begin
      update public.gs_items set received_qty = 3
       where gs_id = (select id from public.goods_slips where gs_no = 'PGTAP-P4-LOCK');
      set constraints all immediate;
    end $d$ $q$,
  '%G-19%', 'G-19: a locked GS edited by Management is re-checked at commit');
select lives_ok(
  $q$do $d$ begin
      update public.gs_items set received_qty = 3
       where gs_id = (select id from public.goods_slips where gs_no = 'PGTAP-P4-LOCK');
      update public.gs_item_buckets set qty = 3
       where gs_item_id = (select i.id from public.gs_items i join public.goods_slips g on g.id = i.gs_id
                            where g.gs_no = 'PGTAP-P4-LOCK');
      set constraints all immediate;
    end $d$ $q$,
  'G-19: qty and split corrected together are accepted');

-- First routing closes the window (setup only: a routing row, bypassing its own guards).
set local session_replication_role = replica;
insert into public.department_routings (routing_no, gs_id, department_field_id, department_code, department_label)
select 'PGTAP-P4-DIN', g.id, (select id from public.item_field_library limit 1), 'DEPT_X', 'Dept X'
  from public.goods_slips g where g.gs_no = 'PGTAP-P4-LOCK';
set local session_replication_role = origin;
select ok(rms_private.gs_routing_started((select id from public.goods_slips where gs_no = 'PGTAP-P4-LOCK')),
  'DEC-64: routing started is detected');
select throws_like(
  $$update public.gs_items set documented_qty = 6
     where gs_id = (select id from public.goods_slips where gs_no = 'PGTAP-P4-LOCK')$$,
  'DEC-64:%routing has started%', 'DEC-64: no edit once department routing has started');
select set_config('app.user_id', '', true);

-- Complete Sales Return on hold (Q11).
select lives_ok(
  $$update public.goods_slips set category_code = 'CSR', original_category_code = 'CSR', status = 'SALES_RETURN_HOLD'
     where gs_no = 'PGTAP-P4-CSR'$$,
  'DEC-64 / Q11: a Complete Sales Return is parked in SALES_RETURN_HOLD');
select throws_like(
  $$update public.goods_slips set status = 'CATEGORISATION' where gs_no = 'PGTAP-P4-CSR'$$,
  'G-03:%on hold%', 'Q11: a parked Complete Sales Return has no further steps');
select throws_like(
  $$update public.goods_slips set category_code = 'RO', original_category_code = 'RO', status = 'SALES_RETURN_HOLD'
     where gs_no = 'PGTAP-P4-RO'$$,
  'G-03:%only a Complete Sales Return%', 'DEC-64: a Replacement is never parked');

-- Edits after the lock need a reason in the revision history.
select throws_ok(
  $$insert into public.rm_review_revisions (gs_id, revision_no, action, items_snapshot, remarks)
    select id, 99, 'LOCKED_EDIT', '[]'::jsonb, ' ' from public.goods_slips where gs_no = 'PGTAP-P4-LOCK'$$,
  '23514', null, 'DEC-64: a post-lock revision needs a reason');

select * from finish();
rollback;
