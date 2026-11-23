-- Phase P10 pgTAP (docs/RMS_PHASE_PROMPTS_20-11-2026.md, DEC-70; migration 20261123000300):
-- after every store submitted (ANALYSIS_COMPLETED) only Management changes the decisions (a store
-- user / the RM cannot set Issue CN), with a reason per change; the approval is append-only and
-- its snapshot + SHA-256 are computed by the DB; a later change makes it CHANGED; a goods slip with
-- an open request, or with Issue CN without a valid approval, does not leave ANALYSIS_COMPLETED and
-- gets no A/c (Replacement) slip (Q18); the approval resolves the open request.
begin;
create extension if not exists pgtap with schema extensions;
select plan(24);

insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data) values
  ('aaaaaaaa-0000-4000-8000-0000000010e1', 'pgtap-p10-re@example.test', '{"rms_activate": true}', '{"full_name": "P10 RE"}'),
  ('aaaaaaaa-0000-4000-8000-0000000010e2', 'pgtap-p10-rm@example.test', '{"rms_activate": true}', '{"full_name": "P10 RM"}'),
  ('aaaaaaaa-0000-4000-8000-0000000010e3', 'pgtap-p10-mgmt@example.test', '{"rms_activate": true}', '{"full_name": "P10 Mgmt"}'),
  ('aaaaaaaa-0000-4000-8000-0000000010e4', 'pgtap-p10-dt@example.test', '{"rms_activate": true}', '{"full_name": "P10 DT store"}'),
  ('aaaaaaaa-0000-4000-8000-0000000010e5', 'pgtap-p10-op@example.test', '{"rms_activate": true}', '{"full_name": "P10 OP store"}');
insert into public.user_roles (user_id, role_id)
select v.u::uuid, r.id
  from (values ('aaaaaaaa-0000-4000-8000-0000000010e1', 'INWARD_VERIFIER'),
               ('aaaaaaaa-0000-4000-8000-0000000010e2', 'REPLACEMENT_MANAGER'),
               ('aaaaaaaa-0000-4000-8000-0000000010e3', 'MANAGEMENT'),
               ('aaaaaaaa-0000-4000-8000-0000000010e4', 'ISTORE_DT'),
               ('aaaaaaaa-0000-4000-8000-0000000010e5', 'ISTORE_OP')) as v(u, role)
  join public.roles r on r.code = v.role;

create temp table _p10 as
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

-- Setup (as in 53_p9): one locked GS, one DMT line of 3 in one condition, on a DT slip
-- that the DT store acknowledged and routed entirely "Issue to Store" (no work).
insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no,
                                carton_count, status, category_code, original_category_code)
select 'PGTAP-P10-A', wv, 'COURIER_PARCEL', 'A', 'PGTAP-P10-A', 1, 'CATEGORISATION', 'RO', 'RO' from _p10;
insert into public.gs_items (gs_id, line_no, product_id, category_id, documented_qty, received_qty)
select g.id, 1, p.id, p.category_id, 3, 3
  from public.goods_slips g, _p10 join public.products p on p.id = _p10.product
 where g.gs_no = 'PGTAP-P10-A';
insert into public.gs_item_buckets (gs_item_id, field_id, qty)
select i.id, (select r.field_id from rms_private.resolve_item_field_profile(i.product_id) r
               where r.field_group = 'CATEGORISATION' limit 1), 3
  from public.gs_items i join public.goods_slips g on g.id = i.gs_id where g.gs_no = 'PGTAP-P10-A';
update public.goods_slips set status = 'PENDING_TRANSFER_SLIP', categorisation_locked_at = now(),
       categorisation_locked_by = 'aaaaaaaa-0000-4000-8000-0000000010e1'
 where gs_no = 'PGTAP-P10-A';

select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000010e2', true);
insert into public.custody_transfers (transfer_no, from_location_id, to_location_id, status, initiated_by)
select 'PGTAP-P10-CT', staging, dt_loc, 'INITIATED', 'aaaaaaaa-0000-4000-8000-0000000010e2' from _p10;
insert into public.transfer_slips (slip_no, store_id, store_code_snapshot, store_name_snapshot,
       custody_transfer_id, relevant_qty, grand_total_qty, template_version_no)
select 'PGTAP-P10-TRF', dt, '', '', (select id from public.custody_transfers where transfer_no = 'PGTAP-P10-CT'),
       3, 3, 1 from _p10;
insert into public.transfer_slip_gs (slip_id, gs_id, gs_no_snapshot, relevant_qty, total_qty)
select s.id, g.id, '', 3, 3 from public.transfer_slips s, public.goods_slips g
 where s.slip_no = 'PGTAP-P10-TRF' and g.gs_no = 'PGTAP-P10-A';
insert into public.transfer_slip_lines (slip_id, gs_id, gs_item_id, line_no_snapshot, product_id,
       product_name_snapshot, bucket_field_id, qty, is_relevant, belongs_store_id, belongs_store_name_snapshot)
select sg.slip_id, sg.gs_id, i.id, 1, i.product_id, 'X', b.field_id, 3, true, p.dt, 'DT'
  from public.transfer_slip_gs sg
  join public.transfer_slips s on s.id = sg.slip_id and s.slip_no = 'PGTAP-P10-TRF'
  join public.gs_items i on i.gs_id = sg.gs_id
  join public.gs_item_buckets b on b.gs_item_id = i.id, _p10 p;
update public.goods_slips set status = 'TRANSFER_SLIP_GENERATED' where gs_no = 'PGTAP-P10-A';
update public.custody_transfers set stock_moved = true where transfer_no = 'PGTAP-P10-CT';
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000010e4', true);
update public.transfer_slips set status = 'ACKNOWLEDGED' where slip_no = 'PGTAP-P10-TRF';
update public.goods_slips set status = 'STORE_ACKNOWLEDGED' where gs_no = 'PGTAP-P10-A';

create temp table _gs as
select g.id as gs_id, i.id as item_id, b.field_id as bucket
  from public.goods_slips g
  join public.gs_items i on i.gs_id = g.id
  join public.gs_item_buckets b on b.gs_item_id = i.id
 where g.gs_no = 'PGTAP-P10-A';
grant select on _gs, _p10 to public;

insert into public.department_routing_plan_lines
  (gs_id, gs_item_id, source_bucket_field_id, department_field_id, department_code, department_label, qty, store_id)
select g.gs_id, g.item_id, g.bucket, p.dept_store, '-', '-', 3, p.dt from _gs g, _p10 p;
update public.goods_slips set status = 'STORE_PROCESSING' where gs_no = 'PGTAP-P10-A';

create function pg_temp.decide(p_code text, p_qty integer, p_reason text default null) returns void language sql as $$
  insert into public.rm_item_actions (gs_item_id, revision_no, round_no, condition_field_id, action_code, qty, reason)
  select g.item_id, 1, 1, g.bucket, p_code, p_qty, p_reason from _gs g
$$;
create function pg_temp.retire() returns void language sql as $$
  update public.rm_item_actions set is_current = false where gs_item_id = (select item_id from _gs) and is_current
$$;
create function pg_temp.approve() returns void language sql as $$
  insert into public.gs_management_approvals (gs_id, approval_no, approver_name_snapshot, approver_role_snapshot,
                                              revision_no, snapshot, snapshot_sha256)
  select gs_id, 1, '-', '-', 0, '{}'::jsonb, repeat('0', 64) from _gs
$$;
create function pg_temp.to_accounts() returns void language sql as $$
  update public.goods_slips set status = 'IN_PROCESS' where id = (select gs_id from _gs)
$$;
create function pg_temp.ac_slip() returns void language sql as $$
  insert into public.ac_action_slips (gs_id, slip_no, version_no, revision_no, attachment_id, template_version_no,
                                      content, totals, sha256)
  select gs_id, 'PGTAP-P10-AC', 1, 1, gen_random_uuid(), 1, '{}', '{}', repeat('a', 64) from _gs
$$;
create function pg_temp.state() returns text language sql as $$
  select rms_private.gs_management_approval_state((select gs_id from _gs))
$$;

-- The DT store analyses (2 Dispatch New + 1 Not Allowed), submits; the GS is Analysis Completed.
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000010e4', true);
select pg_temp.decide('SEND_NEW', 2);
select pg_temp.decide('NOT_ALLOWED', 1);
insert into public.gs_store_analyses (gs_id, store_id, store_code_snapshot, store_name_snapshot, revision_no, total_qty)
select g.gs_id, p.dt, '-', '-', 1, 1 from _gs g, _p10 p;
update public.goods_slips set status = 'ANALYSIS_COMPLETED' where gs_no = 'PGTAP-P10-A';

-- 1. Nothing to approve yet: the gate passes without Management.
select is(rms_private.gs_management_gate_problem((select gs_id from _gs)), null,
  'no request, no Issue CN, no Management change: nothing for Management to approve');

-- 2–4. After the analysis the store user and the RM change nothing (Issue CN is Management's).
select throws_like($$ select pg_temp.decide('ISSUE_CN', 3, 'credit') $$,
  'DEC-70: after the analysis only Management changes the decisions%', 'the store user cannot set Issue CN');
select throws_like($$ select pg_temp.retire() $$,
  'DEC-70: after the analysis only Management changes the decisions%', 'the store user cannot retire a decision');
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000010e2', true);
select throws_like($$ select pg_temp.decide('ISSUE_CN', 3, 'credit') $$,
  'DEC-70: after the analysis only Management changes the decisions%', 'the RM cannot set Issue CN');

-- 5–7. The DT store sends the GS for Management approval (Q36: after its own submission); it
-- neither approves nor resolves the request itself.
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000010e4', true);
select lives_ok($$ insert into public.gs_management_approval_requests (gs_id, store_id, store_name_snapshot, reason)
                   select g.gs_id, p.dt, '-', 'Party wants a credit note' from _gs g, _p10 p $$,
  'the DT user sends it for Management approval');
select throws_like($$ select pg_temp.approve() $$, 'DEC-70: only Management approves%', 'a store user does not approve');
select throws_like($$ update public.gs_management_approval_requests set status = 'RESOLVED'
                       where gs_id = (select gs_id from _gs) $$,
  'DEC-70: only Management resolves%', 'a store user does not resolve the request');

-- 8–10. Management: a reason per change; any action to any other (here everything Issue CN).
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000010e3', true);
select throws_like($$ select pg_temp.retire(); select pg_temp.decide('ISSUE_CN', 3) $$,
  'DEC-70: every Management change carries a reason%', 'a Management change without a reason is refused');
select lives_ok($$ select pg_temp.retire(); select pg_temp.decide('ISSUE_CN', 3, 'Party credit note') $$,
  'Management changes every piece to Issue CN');
select throws_like($$ insert into public.gs_management_revisions (gs_id, revision_no, changes)
                       select gs_id, 1, '[{"reason": ""}]' from _gs $$,
  'DEC-70: every Management change carries a reason%', 'the change history needs a reason per change');

-- 11–13. Accounts gate (Q18): the open request blocks the exit and the A/c (Replacement) slip.
select throws_like($$ select pg_temp.to_accounts() $$, 'DEC-70: the goods slip waits for Management approval%',
  'an open request keeps the goods slip from Accounts');
select throws_like($$ select pg_temp.ac_slip() $$, 'DEC-70: the goods slip waits for Management approval%',
  'no A/c (Replacement) slip while a request is open');
select is(pg_temp.state(), 'NONE', 'no approval yet');

-- 14–18. Approve: the DB computes the snapshot + SHA-256 and resolves the request; append-only.
select lives_ok($$ select pg_temp.approve() $$, 'Management approves');
select is((select (snapshot_sha256 = rms_private.management_snapshot_sha256(snapshot)
                   and snapshot_sha256 = rms_private.management_snapshot_sha256(rms_private.gs_management_snapshot(gs_id))
                   and has_issue_cn and approval_no = 1 and approver_name_snapshot = 'P10 Mgmt'
                   and approver_role_snapshot = 'Management')::text
             from public.gs_management_approvals where gs_id = (select gs_id from _gs)),
          'true', 'the approval carries the DB-computed snapshot hash, Issue CN flag and approver');
select is((select status || '/' || (approval_id is not null)::text || '/' || (resolved_by is not null)::text
             from public.gs_management_approval_requests where gs_id = (select gs_id from _gs)),
          'RESOLVED/true/true', 'the approval resolves the open request');
select throws_like($$ update public.gs_management_approvals set remarks = 'x' where gs_id = (select gs_id from _gs) $$,
  'DEC-70: a Management approval is immutable%', 'an approval is never updated');
select throws_like($$ delete from public.gs_management_approvals where gs_id = (select gs_id from _gs) $$,
  'DEC-70: a Management approval is immutable%', 'an approval is never deleted');

-- 19–20. With a valid approval the Management gate passes; the Accounts exit is ACCOUNTS_PENDING /
--        NOT_ALLOWED_HOLD only (DEC-71, P11), so a jump to IN_PROCESS is still refused.
select is(pg_temp.state(), 'VALID', 'the approval is valid');
select throws_like($$ select pg_temp.to_accounts() $$, 'G-03: ANALYSIS_COMPLETED goes to Accounts%',
  'the Management gate passes; ANALYSIS_COMPLETED leaves only to Accounts or the hold (DEC-71)');

-- 21–24. A later change invalidates the approval: Issue CN without a valid approval is blocked.
select lives_ok($$ select pg_temp.retire(); select pg_temp.decide('ISSUE_CN', 2, 'two pieces only');
                   select pg_temp.decide('SEND_NEW', 1, 'two pieces only') $$,
  'Management changes the decisions again');
select is(pg_temp.state(), 'CHANGED', 'the approval no longer matches the goods slip');
select throws_like($$ select pg_temp.to_accounts() $$, 'DEC-70 (Q18): the goods slip has Issue CN%',
  'Issue CN without a valid approval keeps the goods slip from Accounts');
select throws_like($$ select pg_temp.ac_slip() $$, 'DEC-70 (Q18): the goods slip has Issue CN%',
  'no A/c (Replacement) slip for Issue CN without a valid approval');

select * from finish();
rollback;
