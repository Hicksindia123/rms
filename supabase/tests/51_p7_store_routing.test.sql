-- Phase P7 pgTAP (docs/RMS_PHASE_PROMPTS_20-11-2026.md, DEC-67; migration 20261121000300):
-- only a user of the item's Intermediate Store routes it (not the RM, not Management, not another
-- store), only after its store acknowledged it, never more than the qty still to route (G-20), a
-- store's DIN needs a user of that store, the store of a routing line never changes,
-- STORE_PROCESSING needs a routing, and the legacy RM plan still needs a held GS.
begin;
create extension if not exists pgtap with schema extensions;
select plan(21);

insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data) values
  ('aaaaaaaa-0000-4000-8000-0000000007e1', 'pgtap-p7-re@example.test', '{"rms_activate": true}', '{"full_name": "P7 RE"}'),
  ('aaaaaaaa-0000-4000-8000-0000000007e2', 'pgtap-p7-rm@example.test', '{"rms_activate": true}', '{"full_name": "P7 RM"}'),
  ('aaaaaaaa-0000-4000-8000-0000000007e3', 'pgtap-p7-mgmt@example.test', '{"rms_activate": true}', '{"full_name": "P7 Mgmt"}'),
  ('aaaaaaaa-0000-4000-8000-0000000007e4', 'pgtap-p7-dt@example.test', '{"rms_activate": true}', '{"full_name": "P7 DT store"}'),
  ('aaaaaaaa-0000-4000-8000-0000000007e5', 'pgtap-p7-op@example.test', '{"rms_activate": true}', '{"full_name": "P7 OP store"}');
insert into public.user_roles (user_id, role_id)
select v.u::uuid, r.id
  from (values ('aaaaaaaa-0000-4000-8000-0000000007e1', 'INWARD_VERIFIER'),
               ('aaaaaaaa-0000-4000-8000-0000000007e2', 'REPLACEMENT_MANAGER'),
               ('aaaaaaaa-0000-4000-8000-0000000007e3', 'MANAGEMENT'),
               ('aaaaaaaa-0000-4000-8000-0000000007e4', 'ISTORE_DT'),
               ('aaaaaaaa-0000-4000-8000-0000000007e5', 'ISTORE_OP')) as v(u, role)
  join public.roles r on r.code = v.role;

create temp table _p7 as
select v.id as wv,
       (select p.id from public.products p
          join public.product_categories c on c.id = p.category_id and c.code = 'DMT'
         where exists (select 1 from rms_private.resolve_item_field_profile(p.id) r
                        where r.field_group = 'CATEGORISATION')
           and exists (select 1 from rms_private.resolve_item_field_profile(p.id) r
                        where r.field_group = 'DEPARTMENT' and r.code = 'STORE') limit 1) as product,
       (select id from public.intermediate_stores where code = 'DT') as dt,
       (select id from public.intermediate_stores where code = 'OP') as op,
       (select location_id from public.intermediate_stores where code = 'DT') as dt_loc,
       (select id from public.inventory_locations where code = 'INWARD_STAGING') as staging,
       (select id from public.item_field_library where field_group = 'DEPARTMENT' and code = 'STORE') as dept_store,
       (select id from public.item_field_library where field_group = 'DEPARTMENT' and code = 'CLEANING') as dept_clean
  from public.workflow_versions v
  join public.workflow_definitions d on d.id = v.workflow_definition_id and d.code = 'RMS_STANDARD'
 where v.status = 'PUBLISHED';

-- Setup: two locked GSs (A, B), one DMT line of 2 each, each on its own DT slip. A's slip is
-- acknowledged by the DT store, B's is not.
insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no,
                                carton_count, status, category_code, original_category_code)
select g, wv, 'COURIER_PARCEL', 'A', g, 1, 'CATEGORISATION', 'RO', 'RO'
  from _p7, (values ('PGTAP-P7-A'), ('PGTAP-P7-B')) as v(g);
insert into public.gs_items (gs_id, line_no, product_id, category_id, documented_qty, received_qty)
select g.id, 1, p.id, p.category_id, 2, 2
  from public.goods_slips g, _p7 join public.products p on p.id = _p7.product
 where g.gs_no like 'PGTAP-P7-%';
insert into public.gs_item_buckets (gs_item_id, field_id, qty)
select i.id, (select r.field_id from rms_private.resolve_item_field_profile(i.product_id) r
               where r.field_group = 'CATEGORISATION' limit 1), 2
  from public.gs_items i join public.goods_slips g on g.id = i.gs_id where g.gs_no like 'PGTAP-P7-%';
update public.goods_slips set status = 'PENDING_TRANSFER_SLIP', categorisation_locked_at = now(),
       categorisation_locked_by = 'aaaaaaaa-0000-4000-8000-0000000007e1'
 where gs_no like 'PGTAP-P7-%';

select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000007e2', true);
insert into public.custody_transfers (transfer_no, from_location_id, to_location_id, status, initiated_by)
select 'PGTAP-P7-CT-' || s, staging, dt_loc, 'INITIATED', 'aaaaaaaa-0000-4000-8000-0000000007e2'
  from _p7, (values ('A'), ('B')) as v(s);
insert into public.transfer_slips (slip_no, store_id, store_code_snapshot, store_name_snapshot,
       custody_transfer_id, relevant_qty, grand_total_qty, template_version_no)
select 'PGTAP-P7-TRF-' || s, dt, '', '', (select id from public.custody_transfers where transfer_no = 'PGTAP-P7-CT-' || s),
       2, 2, 1 from _p7, (values ('A'), ('B')) as v(s);
insert into public.transfer_slip_gs (slip_id, gs_id, gs_no_snapshot, relevant_qty, total_qty)
select s.id, g.id, '', 2, 2 from public.transfer_slips s
  join public.goods_slips g on g.gs_no = replace(s.slip_no, '-TRF-', '-')
 where s.slip_no like 'PGTAP-P7-TRF-%';
insert into public.transfer_slip_lines (slip_id, gs_id, gs_item_id, line_no_snapshot, product_id,
       product_name_snapshot, bucket_field_id, qty, is_relevant, belongs_store_id, belongs_store_name_snapshot)
select sg.slip_id, sg.gs_id, i.id, 1, i.product_id, 'X', b.field_id, 2, true, p.dt, 'DT'
  from public.transfer_slip_gs sg
  join public.transfer_slips s on s.id = sg.slip_id and s.slip_no like 'PGTAP-P7-TRF-%'
  join public.gs_items i on i.gs_id = sg.gs_id
  join public.gs_item_buckets b on b.gs_item_id = i.id, _p7 p;
update public.goods_slips set status = 'TRANSFER_SLIP_GENERATED' where gs_no like 'PGTAP-P7-%';

update public.custody_transfers set stock_moved = true where transfer_no = 'PGTAP-P7-CT-A';
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000007e4', true);
update public.transfer_slips set status = 'ACKNOWLEDGED' where slip_no = 'PGTAP-P7-TRF-A';
update public.goods_slips set status = 'STORE_ACKNOWLEDGED' where gs_no = 'PGTAP-P7-A';

create temp table _gs as
select g.gs_no, g.id as gs_id, i.id as item_id, b.field_id as bucket
  from public.goods_slips g
  join public.gs_items i on i.gs_id = g.id
  join public.gs_item_buckets b on b.gs_item_id = i.id
 where g.gs_no like 'PGTAP-P7-%';
grant select on _gs, _p7 to public;

create function pg_temp.plan_line(p_gs text, p_store text, p_dept text, p_qty integer) returns void
language sql as $$
  insert into public.department_routing_plan_lines
    (gs_id, gs_item_id, source_bucket_field_id, department_field_id, department_code,
     department_label, qty, store_id)
  select g.gs_id, g.item_id, g.bucket,
         case p_dept when 'STORE' then p.dept_store else p.dept_clean end, '-', '-', p_qty,
         case p_store when 'DT' then p.dt else p.op end
    from _gs g, _p7 p where g.gs_no = p_gs
$$;

-- 1–3. Who routes: a user of the item's store; not the RM, not Management, not another store.
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000007e2', true);
select throws_like($$ select pg_temp.plan_line('PGTAP-P7-A', 'DT', 'STORE', 1) $$,
  'DEC-67: only a user of the Intermediate Store routes its goods', 'the RM does not route');
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000007e3', true);
select throws_like($$ select pg_temp.plan_line('PGTAP-P7-A', 'DT', 'STORE', 1) $$,
  'DEC-67: only a user of the Intermediate Store routes its goods', 'Management does not route');
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000007e5', true);
select throws_like($$ select pg_temp.plan_line('PGTAP-P7-A', 'DT', 'STORE', 1) $$,
  'DEC-67: only a user of the Intermediate Store routes its goods', 'another store does not route');

-- 4. The OP user routing the DT line under its own store: the line belongs to DT.
select throws_like($$ select pg_temp.plan_line('PGTAP-P7-A', 'OP', 'STORE', 1) $$,
  'DEC-67: item line 1 belongs to another Intermediate Store%', 'cross-store routing refused');

-- 5. Not acknowledged yet (GS B).
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000007e4', true);
select throws_like($$ select pg_temp.plan_line('PGTAP-P7-B', 'DT', 'STORE', 1) $$,
  'DEC-67: item line 1 is not acknowledged by its Intermediate Store yet', 'routes only after the acknowledgement');

-- 6. Over-routing (2 pcs in the store).
select throws_like($$ select pg_temp.plan_line('PGTAP-P7-A', 'DT', 'STORE', 3) $$,
  'G-20: item line 1: only 2 pc(s) left to route at the store, 3 requested', 'over-routing refused (G-20)');

-- 7–9. The DT user routes its 2 pcs "Issue to Store" (no work).
select lives_ok($$ select pg_temp.plan_line('PGTAP-P7-A', 'DT', 'STORE', 2) $$, 'the store user routes its goods');
select is((select string_agg(p.status || '/' || s.code, ',') from public.department_routing_plan_lines p
             join public.intermediate_stores s on s.id = p.store_id
            where p.gs_id = (select gs_id from _gs where gs_no = 'PGTAP-P7-A')),
          'NO_WORK/DT', 'no-work line stamped with its store');
select is((select status from rms_private.gs_store_routing_progress((select gs_id from _gs where gs_no = 'PGTAP-P7-A'))),
          'READY_FOR_ANALYSIS', 'everything no-work: the store is ready for analysis');

-- 10. Nothing left to route.
select throws_like($$ select pg_temp.plan_line('PGTAP-P7-A', 'DT', 'STORE', 1) $$,
  'G-20: item line 1: only 0 pc(s) left%', 'nothing left to route');

-- 11–12. Status: A (routed) → STORE_PROCESSING; B (no routing) refused.
select lives_ok($$ update public.goods_slips set status = 'STORE_PROCESSING' where gs_no = 'PGTAP-P7-A' $$,
  'a routed GS goes to STORE_PROCESSING');
select throws_like($$ update public.goods_slips set status = 'STORE_PROCESSING' where gs_no = 'PGTAP-P7-B' $$,
  'DEC-67: STORE_PROCESSING needs the goods slip fully on transfer slips and a department routing', 'B has no routing: refused');

-- 13. The edit window is closed (DEC-64 d) and B's progress waits for the acknowledgement.
select ok(rms_private.gs_routing_started((select gs_id from _gs where gs_no = 'PGTAP-P7-A')),
  'routing started on A');
select is((select status from rms_private.gs_store_routing_progress((select gs_id from _gs where gs_no = 'PGTAP-P7-B'))),
          'AWAITING_ACKNOWLEDGEMENT', 'B waits for its store');

-- 15. A store's DIN needs a user of that store.
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000007e5', true);
select throws_like($$ insert into public.department_routings
                        (routing_no, gs_id, department_field_id, department_code, department_label, location_id, store_id)
                      select 'PGTAP-P7-DIN', g.gs_id, p.dept_clean, '-', '-',
                             (select id from public.inventory_locations where code = 'DEPT_CLEANING'), p.dt
                        from _gs g, _p7 p where g.gs_no = 'PGTAP-P7-A' $$,
  'DEC-67: only a user of the Intermediate Store issues its goods to departments', 'DIN by another store refused');

-- 16. The store of a routing line never changes.
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000007e4', true);
select throws_like($$ update public.department_routing_plan_lines set store_id = (select op from _p7)
                       where gs_id = (select gs_id from _gs where gs_no = 'PGTAP-P7-A') $$,
  'DEC-67: the store of a routing line cannot change', 'store of a line is immutable');

-- 17. The legacy RM plan (no store) still needs a GS held at the legacy Intermediate Store.
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000007e2', true);
select throws_like($$ insert into public.department_routing_plan_lines
                        (gs_id, gs_item_id, source_bucket_field_id, department_field_id, department_code, department_label, qty)
                      select g.gs_id, g.item_id, g.bucket, p.dept_store, '-', '-', 1
                        from _gs g, _p7 p where g.gs_no = 'PGTAP-P7-B' $$,
  'G-20: a routing plan needs the goods slip held at the intermediate store%', 'legacy plan path unchanged');

-- 18–21. Q32: a store undoes its own "Issue to Store" line (reason required); the edit window
-- stays closed (DEC-64 d).
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000007e5', true);
select throws_like($$ update public.department_routing_plan_lines
                         set status = 'CANCELLED', cancelled_at = now(), cancel_reason = 'not mine'
                       where gs_id = (select gs_id from _gs where gs_no = 'PGTAP-P7-A') $$,
  'DEC-67: only a user of the Intermediate Store undoes its routing', 'another store cannot undo');
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000007e4', true);
select throws_like($$ update public.department_routing_plan_lines
                         set status = 'CANCELLED', cancelled_at = now(), cancel_reason = 'x'
                       where gs_id = (select gs_id from _gs where gs_no = 'PGTAP-P7-A') $$,
  'DEC-67: undoing a routing line needs a reason', 'undo needs a reason');
select lives_ok($$ update public.department_routing_plan_lines
                      set status = 'CANCELLED', cancelled_at = now(), cancel_reason = 'Needs cleaning'
                    where gs_id = (select gs_id from _gs where gs_no = 'PGTAP-P7-A') $$,
  'the store undoes its no-work line');
select ok(rms_private.gs_routing_started((select gs_id from _gs where gs_no = 'PGTAP-P7-A')),
  'the edit window stays closed after the undo');

select * from finish();
rollback;
