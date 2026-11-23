-- Phase P9 pgTAP (docs/RMS_PHASE_PROMPTS_20-11-2026.md, DEC-69; migration 20261123000100):
-- a store's goods of a GS are analysed only by a user of that store once they are ready for
-- analysis; Issue CN / Pending are refused to the store (Q15, DEC-70); the submission needs every
-- piece decided (G-21) and is history; a submitted store cannot change its decisions; the last
-- store moves the GS to ANALYSIS_COMPLETED (G-03); the Management approval request is sent (Q36: after its own submission) only by
-- a user of a store on the GS, once per GS; the Q32 undo stops once the item is analysed.
begin;
create extension if not exists pgtap with schema extensions;
select plan(21);

insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data) values
  ('aaaaaaaa-0000-4000-8000-0000000009e1', 'pgtap-p9-re@example.test', '{"rms_activate": true}', '{"full_name": "P9 RE"}'),
  ('aaaaaaaa-0000-4000-8000-0000000009e2', 'pgtap-p9-rm@example.test', '{"rms_activate": true}', '{"full_name": "P9 RM"}'),
  ('aaaaaaaa-0000-4000-8000-0000000009e3', 'pgtap-p9-mgmt@example.test', '{"rms_activate": true}', '{"full_name": "P9 Mgmt"}'),
  ('aaaaaaaa-0000-4000-8000-0000000009e4', 'pgtap-p9-dt@example.test', '{"rms_activate": true}', '{"full_name": "P9 DT store"}'),
  ('aaaaaaaa-0000-4000-8000-0000000009e5', 'pgtap-p9-op@example.test', '{"rms_activate": true}', '{"full_name": "P9 OP store"}');
insert into public.user_roles (user_id, role_id)
select v.u::uuid, r.id
  from (values ('aaaaaaaa-0000-4000-8000-0000000009e1', 'INWARD_VERIFIER'),
               ('aaaaaaaa-0000-4000-8000-0000000009e2', 'REPLACEMENT_MANAGER'),
               ('aaaaaaaa-0000-4000-8000-0000000009e3', 'MANAGEMENT'),
               ('aaaaaaaa-0000-4000-8000-0000000009e4', 'ISTORE_DT'),
               ('aaaaaaaa-0000-4000-8000-0000000009e5', 'ISTORE_OP')) as v(u, role)
  join public.roles r on r.code = v.role;

create temp table _p9 as
select v.id as wv,
       (select p.id from public.products p
          join public.product_categories c on c.id = p.category_id and c.code = 'DMT'
         where exists (select 1 from rms_private.resolve_item_field_profile(p.id) r
                        where r.field_group = 'CATEGORISATION')
           and exists (select 1 from rms_private.resolve_item_field_profile(p.id) r
                        where r.field_group = 'DEPARTMENT' and r.code = 'STORE')
           and exists (select 1 from rms_private.resolve_item_field_profile(p.id) r
                        where r.field_group = 'ACTION' and r.code = 'ISSUE_CN') limit 1) as product,
       (select id from public.intermediate_stores where code = 'DT') as dt,
       (select location_id from public.intermediate_stores where code = 'DT') as dt_loc,
       (select id from public.inventory_locations where code = 'INWARD_STAGING') as staging,
       (select id from public.item_field_library where field_group = 'DEPARTMENT' and code = 'STORE') as dept_store
  from public.workflow_versions v
  join public.workflow_definitions d on d.id = v.workflow_definition_id and d.code = 'RMS_STANDARD'
 where v.status = 'PUBLISHED';

-- Setup (as in 51_p7 / 52_p8): one locked GS, one DMT line of 3 in one condition, on a DT slip
-- that the DT store acknowledged and routed entirely "Issue to Store" (no work).
insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no,
                                carton_count, status, category_code, original_category_code)
select 'PGTAP-P9-A', wv, 'COURIER_PARCEL', 'A', 'PGTAP-P9-A', 1, 'CATEGORISATION', 'RO', 'RO' from _p9;
insert into public.gs_items (gs_id, line_no, product_id, category_id, documented_qty, received_qty)
select g.id, 1, p.id, p.category_id, 3, 3
  from public.goods_slips g, _p9 join public.products p on p.id = _p9.product
 where g.gs_no = 'PGTAP-P9-A';
insert into public.gs_item_buckets (gs_item_id, field_id, qty)
select i.id, (select r.field_id from rms_private.resolve_item_field_profile(i.product_id) r
               where r.field_group = 'CATEGORISATION' limit 1), 3
  from public.gs_items i join public.goods_slips g on g.id = i.gs_id where g.gs_no = 'PGTAP-P9-A';
update public.goods_slips set status = 'PENDING_TRANSFER_SLIP', categorisation_locked_at = now(),
       categorisation_locked_by = 'aaaaaaaa-0000-4000-8000-0000000009e1'
 where gs_no = 'PGTAP-P9-A';

select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000009e2', true);
insert into public.custody_transfers (transfer_no, from_location_id, to_location_id, status, initiated_by)
select 'PGTAP-P9-CT', staging, dt_loc, 'INITIATED', 'aaaaaaaa-0000-4000-8000-0000000009e2' from _p9;
insert into public.transfer_slips (slip_no, store_id, store_code_snapshot, store_name_snapshot,
       custody_transfer_id, relevant_qty, grand_total_qty, template_version_no)
select 'PGTAP-P9-TRF', dt, '', '', (select id from public.custody_transfers where transfer_no = 'PGTAP-P9-CT'),
       3, 3, 1 from _p9;
insert into public.transfer_slip_gs (slip_id, gs_id, gs_no_snapshot, relevant_qty, total_qty)
select s.id, g.id, '', 3, 3 from public.transfer_slips s, public.goods_slips g
 where s.slip_no = 'PGTAP-P9-TRF' and g.gs_no = 'PGTAP-P9-A';
insert into public.transfer_slip_lines (slip_id, gs_id, gs_item_id, line_no_snapshot, product_id,
       product_name_snapshot, bucket_field_id, qty, is_relevant, belongs_store_id, belongs_store_name_snapshot)
select sg.slip_id, sg.gs_id, i.id, 1, i.product_id, 'X', b.field_id, 3, true, p.dt, 'DT'
  from public.transfer_slip_gs sg
  join public.transfer_slips s on s.id = sg.slip_id and s.slip_no = 'PGTAP-P9-TRF'
  join public.gs_items i on i.gs_id = sg.gs_id
  join public.gs_item_buckets b on b.gs_item_id = i.id, _p9 p;
update public.goods_slips set status = 'TRANSFER_SLIP_GENERATED' where gs_no = 'PGTAP-P9-A';
update public.custody_transfers set stock_moved = true where transfer_no = 'PGTAP-P9-CT';
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000009e4', true);
update public.transfer_slips set status = 'ACKNOWLEDGED' where slip_no = 'PGTAP-P9-TRF';
update public.goods_slips set status = 'STORE_ACKNOWLEDGED' where gs_no = 'PGTAP-P9-A';

create temp table _gs as
select g.id as gs_id, i.id as item_id, b.field_id as bucket
  from public.goods_slips g
  join public.gs_items i on i.gs_id = g.id
  join public.gs_item_buckets b on b.gs_item_id = i.id
 where g.gs_no = 'PGTAP-P9-A';
grant select on _gs, _p9 to public;

insert into public.department_routing_plan_lines
  (gs_id, gs_item_id, source_bucket_field_id, department_field_id, department_code, department_label, qty, store_id)
select g.gs_id, g.item_id, g.bucket, p.dept_store, '-', '-', 3, p.dt from _gs g, _p9 p;
update public.goods_slips set status = 'STORE_PROCESSING' where gs_no = 'PGTAP-P9-A';

create function pg_temp.decide(p_code text, p_qty integer) returns void language sql as $$
  insert into public.rm_item_actions (gs_item_id, revision_no, round_no, condition_field_id, action_code, qty)
  select g.item_id, 1, 1, g.bucket, p_code, p_qty from _gs g
$$;
create function pg_temp.submit() returns void language sql as $$
  insert into public.gs_store_analyses (gs_id, store_id, store_code_snapshot, store_name_snapshot, revision_no, total_qty)
  select g.gs_id, p.dt, '-', '-', 1, 1 from _gs g, _p9 p
$$;
create function pg_temp.request(p_reason text) returns void language sql as $$
  insert into public.gs_management_approval_requests (gs_id, store_id, store_name_snapshot, reason)
  select g.gs_id, p.dt, '-', p_reason from _gs g, _p9 p
$$;

-- 1. Ready for analysis: everything "Issue to Store".
select is((select analysis_status from rms_private.gs_store_analysis_progress((select gs_id from _gs))),
          'PENDING', 'no-work goods: the DT part is ready for analysis');

-- 2–5. Who decides: a user of the item's store; not the RE, the RM, Management or another store.
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000009e2', true);
select throws_like($$ select pg_temp.decide('SEND_NEW', 3) $$,
  'DEC-69: item line 1 belongs to %; only a user of that store analyses it', 'the RM does not analyse');
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000009e3', true);
select throws_like($$ select pg_temp.decide('SEND_NEW', 3) $$, 'DEC-69: item line 1 belongs to %',
  'Management does not analyse (it changes decisions in P10)');
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000009e5', true);
select throws_like($$ select pg_temp.decide('SEND_NEW', 3) $$, 'DEC-69: item line 1 belongs to %',
  'another store does not analyse');
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000009e1', true);
select throws_like($$ select pg_temp.decide('SEND_NEW', 3) $$, 'DEC-69: item line 1 belongs to %',
  'the RE does not analyse');

-- 6–7. Q15 / DEC-70: Issue CN and Pending are not store options.
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000009e4', true);
select throws_like($$ select pg_temp.decide('ISSUE_CN', 3) $$,
  'DEC-69: ISSUE_CN is not a store analysis option%', 'the store cannot pick Issue CN');
select throws_like($$ select pg_temp.decide('PENDING_BP', 3) $$,
  'DEC-69: PENDING_BP is not a store analysis option%', 'the store cannot pick Pending');

-- 7b. Q36 (user 2026-11-23): the store submits its own analysis before sending for approval.
select throws_like($$ select pg_temp.request('Party wants a credit note') $$,
  'DEC-69 (Q36): % submits its own analysis of this goods slip before sending it for Management approval',
  'no approval request before the store''s own submission');

-- 8–9. G-21: a partial decision is not submitted (nor committed).
select lives_ok($$ select pg_temp.decide('SEND_NEW', 2) $$, 'the DT user decides 2 of 3');
select throws_like($$ select pg_temp.submit() $$, 'G-21: item line 1%decisions total 2 pc(s)%',
  'the submission needs every piece decided');

-- 10. Q32: an analysed item's "Issue to Store" line can no longer be undone.
select throws_like($$ update public.department_routing_plan_lines
                         set status = 'CANCELLED', cancelled_at = now(), cancel_reason = 'mistake'
                       where gs_id = (select gs_id from _gs) $$,
  'G-21: the item is analysed; its routing can no longer be undone', 'the undo stops once analysed');

-- 11–15. Complete, submit; the submission is history and freezes the store's decisions.
select lives_ok($$ select pg_temp.decide('NOT_ALLOWED', 1) $$, 'the last piece is decided');
select lives_ok($$ select pg_temp.submit() $$, 'the DT store submits its analysis');
select is((select (store_code_snapshot, total_qty, submitted_by)::text from public.gs_store_analyses
            where gs_id = (select gs_id from _gs)),
          '(DT,3,aaaaaaaa-0000-4000-8000-0000000009e4)', 'the guard stamps the store, total and submitter');
select throws_like($$ delete from public.gs_store_analyses where gs_id = (select gs_id from _gs) $$,
  'DEC-69: a submitted store analysis is kept as history', 'a submission is never deleted');
select throws_like($$ update public.rm_item_actions set is_current = false
                       where gs_item_id = (select item_id from _gs) $$,
  'DEC-69: % submitted its analysis of this goods slip; it can no longer change',
  'a submitted store cannot change its decisions');

-- 16–17. G-03: every store submitted → ANALYSIS_COMPLETED (and not back).
select lives_ok($$ update public.goods_slips set status = 'ANALYSIS_COMPLETED' where id = (select gs_id from _gs) $$,
  'every store submitted: the goods slip is Analysis Completed');
select throws_like($$ update public.goods_slips set status = 'STORE_PROCESSING' where id = (select gs_id from _gs) $$,
  'G-03: STORE_PROCESSING is reached from the transfer slips%', 'no way back to store processing');

-- 18–20. "Send for Management Approval": a user of a store on the GS, reason, one OPEN per GS.
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000009e2', true);
select throws_like($$ select pg_temp.request('Please check') $$,
  'DEC-69: only a user of an Intermediate Store on the goods slip%', 'the RM does not send it');
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000009e4', true);
select lives_ok($$ select pg_temp.request('Party wants a credit note') $$, 'the DT user sends it');
select throws_like($$ select pg_temp.request('Again') $$, '%gs_mgmt_approval_requests_one_open%',
  'one open request per goods slip');

select * from finish();
rollback;
