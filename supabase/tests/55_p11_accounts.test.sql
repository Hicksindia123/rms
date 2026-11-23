-- Phase P11 pgTAP (docs/RMS_PHASE_PROMPTS_20-11-2026.md, DEC-71; migration 20261123000400):
-- a store-flow goods slip leaves ANALYSIS_COMPLETED only to Accounts (ACCOUNTS_PENDING, when a
-- decision needs a Challan or a CN) or on hold (NOT_ALLOWED_HOLD, Q21); the Replacement Slip is
-- created only at Accounts and a goods slip at Accounts always has one; Accounts enters one Challan /
-- CN per goods slip (ac_gs_entries: only the groups the GS needs, no future dates, frozen after
-- completion, never deleted); the per-line entry is refused on the store flow; the goods slip leaves
-- Accounts only after completion (Dispatch when goods ship).
begin;
create extension if not exists pgtap with schema extensions;
select plan(22);

insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data) values
  ('aaaaaaaa-0000-4000-8000-0000000011e1', 'pgtap-p11-re@example.test', '{"rms_activate": true}', '{"full_name": "P11 RE"}'),
  ('aaaaaaaa-0000-4000-8000-0000000011e2', 'pgtap-p11-rm@example.test', '{"rms_activate": true}', '{"full_name": "P11 RM"}'),
  ('aaaaaaaa-0000-4000-8000-0000000011e3', 'pgtap-p11-mgmt@example.test', '{"rms_activate": true}', '{"full_name": "P11 Mgmt"}'),
  ('aaaaaaaa-0000-4000-8000-0000000011e4', 'pgtap-p11-dt@example.test', '{"rms_activate": true}', '{"full_name": "P11 DT store"}'),
  ('aaaaaaaa-0000-4000-8000-0000000011e5', 'pgtap-p11-ac@example.test', '{"rms_activate": true}', '{"full_name": "P11 Accounts"}');
insert into public.user_roles (user_id, role_id)
select v.u::uuid, r.id
  from (values ('aaaaaaaa-0000-4000-8000-0000000011e1', 'INWARD_VERIFIER'),
               ('aaaaaaaa-0000-4000-8000-0000000011e2', 'REPLACEMENT_MANAGER'),
               ('aaaaaaaa-0000-4000-8000-0000000011e3', 'MANAGEMENT'),
               ('aaaaaaaa-0000-4000-8000-0000000011e4', 'ISTORE_DT'),
               ('aaaaaaaa-0000-4000-8000-0000000011e5', 'ACCOUNTS')) as v(u, role)
  join public.roles r on r.code = v.role;

create temp table _p11 as
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
select 'PGTAP-P11-A', wv, 'COURIER_PARCEL', 'A', 'PGTAP-P11-A', 1, 'CATEGORISATION', 'RO', 'RO' from _p11;
insert into public.gs_items (gs_id, line_no, product_id, category_id, documented_qty, received_qty)
select g.id, 1, p.id, p.category_id, 3, 3
  from public.goods_slips g, _p11 join public.products p on p.id = _p11.product
 where g.gs_no = 'PGTAP-P11-A';
insert into public.gs_item_buckets (gs_item_id, field_id, qty)
select i.id, (select r.field_id from rms_private.resolve_item_field_profile(i.product_id) r
               where r.field_group = 'CATEGORISATION' limit 1), 3
  from public.gs_items i join public.goods_slips g on g.id = i.gs_id where g.gs_no = 'PGTAP-P11-A';
update public.goods_slips set status = 'PENDING_TRANSFER_SLIP', categorisation_locked_at = now(),
       categorisation_locked_by = 'aaaaaaaa-0000-4000-8000-0000000011e1'
 where gs_no = 'PGTAP-P11-A';

select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000011e2', true);
insert into public.custody_transfers (transfer_no, from_location_id, to_location_id, status, initiated_by)
select 'PGTAP-P11-CT', staging, dt_loc, 'INITIATED', 'aaaaaaaa-0000-4000-8000-0000000011e2' from _p11;
insert into public.transfer_slips (slip_no, store_id, store_code_snapshot, store_name_snapshot,
       custody_transfer_id, relevant_qty, grand_total_qty, template_version_no)
select 'PGTAP-P11-TRF', dt, '', '', (select id from public.custody_transfers where transfer_no = 'PGTAP-P11-CT'),
       3, 3, 1 from _p11;
insert into public.transfer_slip_gs (slip_id, gs_id, gs_no_snapshot, relevant_qty, total_qty)
select s.id, g.id, '', 3, 3 from public.transfer_slips s, public.goods_slips g
 where s.slip_no = 'PGTAP-P11-TRF' and g.gs_no = 'PGTAP-P11-A';
insert into public.transfer_slip_lines (slip_id, gs_id, gs_item_id, line_no_snapshot, product_id,
       product_name_snapshot, bucket_field_id, qty, is_relevant, belongs_store_id, belongs_store_name_snapshot)
select sg.slip_id, sg.gs_id, i.id, 1, i.product_id, 'X', b.field_id, 3, true, p.dt, 'DT'
  from public.transfer_slip_gs sg
  join public.transfer_slips s on s.id = sg.slip_id and s.slip_no = 'PGTAP-P11-TRF'
  join public.gs_items i on i.gs_id = sg.gs_id
  join public.gs_item_buckets b on b.gs_item_id = i.id, _p11 p;
update public.goods_slips set status = 'TRANSFER_SLIP_GENERATED' where gs_no = 'PGTAP-P11-A';
update public.custody_transfers set stock_moved = true where transfer_no = 'PGTAP-P11-CT';
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000011e4', true);
update public.transfer_slips set status = 'ACKNOWLEDGED' where slip_no = 'PGTAP-P11-TRF';
update public.goods_slips set status = 'STORE_ACKNOWLEDGED' where gs_no = 'PGTAP-P11-A';

create temp table _gs as
select g.id as gs_id, i.id as item_id, b.field_id as bucket
  from public.goods_slips g
  join public.gs_items i on i.gs_id = g.id
  join public.gs_item_buckets b on b.gs_item_id = i.id
 where g.gs_no = 'PGTAP-P11-A';
grant select on _gs, _p11 to public;

insert into public.department_routing_plan_lines
  (gs_id, gs_item_id, source_bucket_field_id, department_field_id, department_code, department_label, qty, store_id)
select g.gs_id, g.item_id, g.bucket, p.dept_store, '-', '-', 3, p.dt from _gs g, _p11 p;
update public.goods_slips set status = 'STORE_PROCESSING' where gs_no = 'PGTAP-P11-A';

create function pg_temp.decide(p_code text, p_qty integer) returns void language sql as $$
  insert into public.rm_item_actions (gs_item_id, revision_no, round_no, condition_field_id, action_code, qty)
  select g.item_id, 1, 1, g.bucket, p_code, p_qty from _gs g
$$;
create function pg_temp.status(p_to text) returns void language sql as $$
  update public.goods_slips set status = p_to where id = (select gs_id from _gs)
$$;
create function pg_temp.entry(p_set text) returns void language plpgsql as $$
begin
  execute format('update public.ac_gs_entries set %s where gs_id = (select gs_id from _gs)', p_set);
end
$$;
create function pg_temp.slip() returns void language sql as $$
  insert into public.attachments (gs_id, entity_type, entity_id, kind, bucket, object_path, mime_type,
                                  size_bytes, status, uploaded_by, confirmed_by, confirmed_at)
  select gs_id, 'ac_action_slips', gen_random_uuid(), 'GENERATED_PDF', 'rms-documents',
         'gs/' || gs_id || '/generated_pdf/' || gen_random_uuid() || '.pdf', 'application/pdf', 10, 'CONFIRMED',
         'aaaaaaaa-0000-4000-8000-0000000011e2', 'aaaaaaaa-0000-4000-8000-0000000011e2', now() from _gs;
  insert into public.ac_action_slips (gs_id, slip_no, version_no, revision_no, attachment_id, template_version_no,
                                      content, totals, sha256)
  select g.gs_id, 'PGTAP-P11-RS', 1, 1,
         (select a.id from public.attachments a where a.gs_id = g.gs_id and a.entity_type = 'ac_action_slips'
           order by a.created_at desc limit 1), 1, '{}', '{}', repeat('a', 64) from _gs g
$$;
create function pg_temp.complete() returns void language sql as $$
  insert into public.ac_entry_completions (gs_id, ac_action_slip_id, completed_by)
  select g.gs_id, s.id, 'aaaaaaaa-0000-4000-8000-0000000011e5'
    from _gs g join public.ac_action_slips s on s.gs_id = g.gs_id and s.status = 'CURRENT'
$$;

-- The DT store analyses (2 Dispatch New + 1 Not Allowed) and submits: Analysis Completed.
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000011e4', true);
select pg_temp.decide('SEND_NEW', 2);
select pg_temp.decide('NOT_ALLOWED', 1);
insert into public.gs_store_analyses (gs_id, store_id, store_code_snapshot, store_name_snapshot, revision_no, total_qty)
select g.gs_id, p.dt, '-', '-', 1, 3 from _gs g, _p11 p;
select pg_temp.status('ANALYSIS_COMPLETED');

-- 1–4. The Accounts gate (G-03): Dispatch New needs a Challan, so not on hold, not straight to
-- closure; no Replacement Slip before Accounts.
select ok(rms_private.gs_needs_accounts((select gs_id from _gs)), 'Dispatch New needs Accounts data (a Challan)');
select throws_like($$ select pg_temp.status('NOT_ALLOWED_HOLD') $$,
  'DEC-71 (Q21): a decision of the goods slip needs a Challan%', 'a goods slip with goods to ship is not put on hold');
select throws_like($$ select pg_temp.status('IN_PROCESS') $$,
  'G-03: ANALYSIS_COMPLETED goes to Accounts%', 'analysis does not jump to closure');
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000011e2', true);
select throws_like($$ select pg_temp.slip() $$,
  'DEC-71: the Replacement Slip is created when the goods slip reaches Accounts%', 'no Replacement Slip before Accounts');

-- 5–8. To Accounts: without its Replacement Slip the commit check refuses; the slip creates one
-- per-GS entry with only the Challan needed.
select lives_ok($$ select pg_temp.status('ACCOUNTS_PENDING') $$, 'the gate passes: the goods slip goes to Accounts');
select throws_like($$ set constraints goods_slips_accounts_slip_check immediate $$,
  'DEC-71: a goods slip at Accounts must have its CURRENT Replacement Slip%', 'a goods slip at Accounts has its Replacement Slip');
select lives_ok($$ select pg_temp.slip() $$, 'the Replacement Slip is created at Accounts');
select is((select requires_challan::text || '/' || requires_cn::text from public.ac_gs_entries
            where gs_id = (select gs_id from _gs)), 'true/false', 'one per-GS entry: Challan needed, no Credit Note');

-- 9–15. Accounts entry guards.
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000011e5', true);
select throws_like($$ select pg_temp.entry('cn_no = ''CN-1'', cn_date = current_date, cn_value = 10') $$,
  'G-22: this goods slip has no Issue CN%', 'no Credit Note on a goods slip without Issue CN');
select throws_like($$ select pg_temp.entry('challan_no = ''CH-1'', challan_date = current_date + 2') $$,
  'G-22: CN / Challan dates cannot be in the future%', 'no future Challan date');
select throws_like($$ select pg_temp.complete() $$,
  'G-22: the goods slip still needs its Challan%', 'no completion without the Challan');
select throws_like($$ update public.ac_entry_lines set challan_no = 'X', challan_date = current_date
                       where gs_id = (select gs_id from _gs) $$,
  'DEC-71: Accounts data of a store-flow goods slip is entered once per goods slip%', 'no per-line entry on the store flow');
select throws_like($$ insert into public.ac_gs_entries (gs_id, ac_action_slip_id, requires_challan, requires_cn)
                      select g.gs_id, s.id, true, true from _gs g
                        join public.ac_action_slips s on s.gs_id = g.gs_id $$,
  'G-22: the Accounts entry of a Replacement Slip starts empty%', 'the per-GS entry flags follow the slip lines');
select throws_like($$ select pg_temp.status('IN_PROCESS') $$,
  'DEC-71: Accounts must complete the Replacement Slip%', 'the goods slip leaves Accounts only after completion');
select throws_like($$ select pg_temp.status('ANALYSIS_COMPLETED') $$,
  'DEC-71: the Replacement Slip at Accounts must be withdrawn%', 'reopening needs the Replacement Slip withdrawn');

-- 16–22. Complete: frozen, never deleted, Dispatch first (goods ship).
select lives_ok($$ select pg_temp.entry('challan_no = ''CH-P11'', challan_date = current_date') $$, 'Accounts enters the Challan');
select lives_ok($$ select pg_temp.complete() $$, 'Accounts completes the Replacement Slip');
select throws_like($$ select pg_temp.entry('challan_no = ''CH-P11-B'', challan_date = current_date') $$,
  'G-22: the Accounts entry of this Replacement Slip is complete and frozen%', 'a completed entry is frozen');
select throws_like($$ delete from public.ac_gs_entries where gs_id = (select gs_id from _gs) $$,
  'G-22: Accounts entries are never deleted%', 'an Accounts entry is never deleted');
select throws_like($$ select pg_temp.status('IN_PROCESS') $$,
  'DEC-71: the goods slip ships goods; it goes to Dispatch%', 'goods to ship go to Dispatch first');
select throws_like($$ select pg_temp.status('DISPATCH_PENDING') $$,
  'DEC-71: DISPATCH_PENDING needs the Dispatch Slip%', 'Dispatch needs its Dispatch Slip');
select throws_like($$ update public.ac_action_slips set status = 'SUPERSEDED', superseded_at = now(),
                        superseded_by = 'aaaaaaaa-0000-4000-8000-0000000011e3', supersede_reason = 'late change'
                      where gs_id = (select gs_id from _gs) $$,
  'G-22: Accounts completed A/c Actions slip%', 'a completed Replacement Slip is never withdrawn');

select * from finish();
rollback;
