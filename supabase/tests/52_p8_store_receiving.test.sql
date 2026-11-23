-- Phase P8 pgTAP (docs/RMS_PHASE_PROMPTS_20-11-2026.md, DEC-68; migration 20261121000500):
-- a store's DIN is received back only by a user of that store (not the Replacement Executive, the
-- RM, Management or another store), the pieces go back to THAT store's location (wastage → scrap,
-- Mercury Extracted → Non-Functional Store), over-receipt is refused (G-20), the condition after
-- work is required when routed from a condition, and the per-store progress follows the receipts.
begin;
create extension if not exists pgtap with schema extensions;
select plan(13);

insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data) values
  ('aaaaaaaa-0000-4000-8000-0000000008e1', 'pgtap-p8-re@example.test', '{"rms_activate": true}', '{"full_name": "P8 RE"}'),
  ('aaaaaaaa-0000-4000-8000-0000000008e2', 'pgtap-p8-rm@example.test', '{"rms_activate": true}', '{"full_name": "P8 RM"}'),
  ('aaaaaaaa-0000-4000-8000-0000000008e3', 'pgtap-p8-mgmt@example.test', '{"rms_activate": true}', '{"full_name": "P8 Mgmt"}'),
  ('aaaaaaaa-0000-4000-8000-0000000008e4', 'pgtap-p8-dt@example.test', '{"rms_activate": true}', '{"full_name": "P8 DT store"}'),
  ('aaaaaaaa-0000-4000-8000-0000000008e5', 'pgtap-p8-op@example.test', '{"rms_activate": true}', '{"full_name": "P8 OP store"}');
insert into public.user_roles (user_id, role_id)
select v.u::uuid, r.id
  from (values ('aaaaaaaa-0000-4000-8000-0000000008e1', 'INWARD_VERIFIER'),
               ('aaaaaaaa-0000-4000-8000-0000000008e2', 'REPLACEMENT_MANAGER'),
               ('aaaaaaaa-0000-4000-8000-0000000008e3', 'MANAGEMENT'),
               ('aaaaaaaa-0000-4000-8000-0000000008e4', 'ISTORE_DT'),
               ('aaaaaaaa-0000-4000-8000-0000000008e5', 'ISTORE_OP')) as v(u, role)
  join public.roles r on r.code = v.role;

create temp table _p8 as
select v.id as wv,
       (select p.id from public.products p
          join public.product_categories c on c.id = p.category_id and c.code = 'DMT'
         where exists (select 1 from rms_private.resolve_item_field_profile(p.id) r
                        where r.field_group = 'CATEGORISATION')
           and exists (select 1 from rms_private.resolve_item_field_profile(p.id) r
                        where r.field_group = 'DEPARTMENT' and r.code = 'CLEANING') limit 1) as product,
       (select id from public.intermediate_stores where code = 'DT') as dt,
       (select location_id from public.intermediate_stores where code = 'DT') as dt_loc,
       (select id from public.inventory_locations where code = 'INWARD_STAGING') as staging,
       (select id from public.inventory_locations where code = 'DEPT_CLEANING') as clean_loc,
       (select id from public.item_field_library where field_group = 'DEPARTMENT' and code = 'CLEANING') as dept_clean
  from public.workflow_versions v
  join public.workflow_definitions d on d.id = v.workflow_definition_id and d.code = 'RMS_STANDARD'
 where v.status = 'PUBLISHED';

-- Setup (as in 51_p7): one locked GS, one DMT line of 3 in one condition, on a DT slip that the
-- DT store acknowledged.
insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no,
                                carton_count, status, category_code, original_category_code)
select 'PGTAP-P8-A', wv, 'COURIER_PARCEL', 'A', 'PGTAP-P8-A', 1, 'CATEGORISATION', 'RO', 'RO' from _p8;
insert into public.gs_items (gs_id, line_no, product_id, category_id, documented_qty, received_qty)
select g.id, 1, p.id, p.category_id, 3, 3
  from public.goods_slips g, _p8 join public.products p on p.id = _p8.product
 where g.gs_no = 'PGTAP-P8-A';
insert into public.gs_item_buckets (gs_item_id, field_id, qty)
select i.id, (select r.field_id from rms_private.resolve_item_field_profile(i.product_id) r
               where r.field_group = 'CATEGORISATION' limit 1), 3
  from public.gs_items i join public.goods_slips g on g.id = i.gs_id where g.gs_no = 'PGTAP-P8-A';
update public.goods_slips set status = 'PENDING_TRANSFER_SLIP', categorisation_locked_at = now(),
       categorisation_locked_by = 'aaaaaaaa-0000-4000-8000-0000000008e1'
 where gs_no = 'PGTAP-P8-A';

select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000008e2', true);
insert into public.custody_transfers (transfer_no, from_location_id, to_location_id, status, initiated_by)
select 'PGTAP-P8-CT', staging, dt_loc, 'INITIATED', 'aaaaaaaa-0000-4000-8000-0000000008e2' from _p8;
insert into public.transfer_slips (slip_no, store_id, store_code_snapshot, store_name_snapshot,
       custody_transfer_id, relevant_qty, grand_total_qty, template_version_no)
select 'PGTAP-P8-TRF', dt, '', '', (select id from public.custody_transfers where transfer_no = 'PGTAP-P8-CT'),
       3, 3, 1 from _p8;
insert into public.transfer_slip_gs (slip_id, gs_id, gs_no_snapshot, relevant_qty, total_qty)
select s.id, g.id, '', 3, 3 from public.transfer_slips s, public.goods_slips g
 where s.slip_no = 'PGTAP-P8-TRF' and g.gs_no = 'PGTAP-P8-A';
insert into public.transfer_slip_lines (slip_id, gs_id, gs_item_id, line_no_snapshot, product_id,
       product_name_snapshot, bucket_field_id, qty, is_relevant, belongs_store_id, belongs_store_name_snapshot)
select sg.slip_id, sg.gs_id, i.id, 1, i.product_id, 'X', b.field_id, 3, true, p.dt, 'DT'
  from public.transfer_slip_gs sg
  join public.transfer_slips s on s.id = sg.slip_id and s.slip_no = 'PGTAP-P8-TRF'
  join public.gs_items i on i.gs_id = sg.gs_id
  join public.gs_item_buckets b on b.gs_item_id = i.id, _p8 p;
update public.goods_slips set status = 'TRANSFER_SLIP_GENERATED' where gs_no = 'PGTAP-P8-A';
update public.custody_transfers set stock_moved = true where transfer_no = 'PGTAP-P8-CT';
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000008e4', true);
update public.transfer_slips set status = 'ACKNOWLEDGED' where slip_no = 'PGTAP-P8-TRF';
update public.goods_slips set status = 'STORE_ACKNOWLEDGED' where gs_no = 'PGTAP-P8-A';

create temp table _gs as
select g.id as gs_id, i.id as item_id, b.field_id as bucket
  from public.goods_slips g
  join public.gs_items i on i.gs_id = g.id
  join public.gs_item_buckets b on b.gs_item_id = i.id
 where g.gs_no = 'PGTAP-P8-A';
grant select on _gs, _p8 to public;

-- The DT user routes all 3 pcs to Cleaning (plan line + DIN + routing line, as the service does).
insert into public.department_routing_plan_lines
  (gs_id, gs_item_id, source_bucket_field_id, department_field_id, department_code, department_label, qty, store_id)
select g.gs_id, g.item_id, g.bucket, p.dept_clean, '-', '-', 3, p.dt from _gs g, _p8 p;
insert into public.department_routings
  (routing_no, gs_id, department_field_id, department_code, department_label, location_id, store_id)
select 'PGTAP-P8-DIN', g.gs_id, p.dept_clean, '-', '-', p.clean_loc, p.dt from _gs g, _p8 p;
insert into public.department_routing_lines (routing_id, gs_item_id, source_bucket_field_id, qty_sent)
select r.id, g.item_id, g.bucket, 3 from public.department_routings r, _gs g where r.routing_no = 'PGTAP-P8-DIN';
update public.department_routing_plan_lines p
   set status = 'ISSUED', routing_id = r.id, routing_line_id = rl.id, issued_by = 'aaaaaaaa-0000-4000-8000-0000000008e4', issued_at = now()
  from public.department_routings r join public.department_routing_lines rl on rl.routing_id = r.id
 where r.routing_no = 'PGTAP-P8-DIN' and p.gs_id = r.gs_id;
update public.goods_slips set status = 'STORE_PROCESSING' where gs_no = 'PGTAP-P8-A';

create function pg_temp.receipt(p_no text) returns void language sql as $$
  insert into public.department_receipts (receipt_no, routing_id, received_by)
  select p_no, r.id, 'aaaaaaaa-0000-4000-8000-0000000008e4'
    from public.department_routings r where r.routing_no = 'PGTAP-P8-DIN'
$$;
create function pg_temp.receipt_line(p_no text, p_head text, p_qty integer, p_with_condition boolean)
returns text language sql as $$
  insert into public.department_receipt_lines
    (receipt_id, routing_line_id, outcome_head_id, outcome_code, outcome_label, is_wastage,
     returns_to_routing, quantity, condition_field_id)
  select rc.id, rl.id, h.id, '-', '-', false, false, p_qty,
         case when p_with_condition then g.bucket end
    from public.department_receipts rc
    join public.department_routing_lines rl on rl.routing_id = rc.routing_id
    join public.department_outcome_heads h on h.code = p_head, _gs g
   where rc.receipt_no = p_no
  returning destination_location_code
$$;

select is((select status from rms_private.gs_store_routing_progress((select gs_id from _gs))),
          'AT_DEPARTMENTS', 'routed to Cleaning: the store waits for its goods');

-- 2–5. Who receives: a user of the routing's store; not the RE, the RM, Management or another store.
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000008e1', true);
select throws_like($$ select pg_temp.receipt('PGTAP-P8-R0') $$,
  'DEC-68: only a user of the Intermediate Store that routed the goods receives them back', 'the RE does not receive a store DIN');
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000008e2', true);
select throws_like($$ select pg_temp.receipt('PGTAP-P8-R0') $$,
  'DEC-68: only a user%', 'the RM does not receive');
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000008e3', true);
select throws_like($$ select pg_temp.receipt('PGTAP-P8-R0') $$,
  'DEC-68: only a user%', 'Management does not receive');
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000008e5', true);
select throws_like($$ select pg_temp.receipt('PGTAP-P8-R0') $$,
  'DEC-68: only a user%', 'another store does not receive');

-- 6. The DT user opens a receipt.
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000008e4', true);
select lives_ok($$ select pg_temp.receipt('PGTAP-P8-R1') $$, 'the store user receives its DIN');

-- 7. Condition after work is required (routed from a condition, DEC-56).
select throws_like($$ select pg_temp.receipt_line('PGTAP-P8-R1', 'CLEANED', 1, false) $$,
  'G-20: item line 1 was routed from a condition; record the condition%', 'condition after work required');

-- 8–10. Destinations: back to the DT store's location / scrap / Non-Functional Store.
select is(pg_temp.receipt_line('PGTAP-P8-R1', 'CLEANED', 1, true),
          (select l.code from public.inventory_locations l join _p8 p on l.id = p.dt_loc),
          'a cleaned piece goes back to the routing store''s location (not INTERMEDIATE_STORE)');
select is(pg_temp.receipt_line('PGTAP-P8-R1', 'WASTAGE', 1, true), 'SCRAP_DISPOSED', 'wastage goes to scrap');
select is((select status from rms_private.gs_store_routing_progress((select gs_id from _gs))),
          'AT_DEPARTMENTS', 'partial receipt: one piece still at the department');

-- 11. Over-receipt (1 pending) refused (G-20).
select throws_like($$ select pg_temp.receipt_line('PGTAP-P8-R1', 'CLEANED', 2, true) $$,
  '%dept_routing_lines_qty_check%', 'over-receipt refused (qty received <= qty sent)');

-- 12–13. The last piece: Mercury Extracted → Non-Functional Store; the store is ready for analysis.
select is(pg_temp.receipt_line('PGTAP-P8-R1', 'MERCURY_EXTRACTED', 1, true), 'NON_FUNCTIONAL_STORE',
          'Mercury Extracted goes to the Non-Functional Store');
select is((select status from rms_private.gs_store_routing_progress((select gs_id from _gs))),
          'READY_FOR_ANALYSIS', 'everything back: the store is ready for analysis');

select * from finish();
rollback;
