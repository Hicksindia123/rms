-- P1-02 pgTAP: audit capture (G-17, BR-40) and insert-only logs.
begin;
create extension if not exists pgtap with schema extensions;
select plan(18);

-- Every business/config table carries the audit trigger, except the logs themselves (incl. the
-- P4-01 append-only system_guard_events / job_runs, the Phase 4 insert-only
-- item_field_profile_versions snapshots, G-18) and the number counters (bookkeeping).
select is(
  (select array_agg(c.relname::text order by c.relname)
     from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind = 'r'
      and not exists (select 1 from pg_trigger t where t.tgrelid = c.oid and t.tgname = 'audit_row')),
  array['audit_log','config_change_log','item_field_profile_versions','job_runs','notification_deliveries','notification_events','number_series_counters','saved_views','system_guard_events','user_activity'],
  'audit_row trigger is attached to every business and config table');

select is(
  (select array_agg(c.relname::text order by c.relname)
     from pg_class c join pg_namespace n on n.oid = c.relnamespace
     join pg_attribute a on a.attrelid = c.oid and a.attname = 'updated_at' and not a.attisdropped
    where n.nspname = 'public' and c.relkind = 'r'
      and not exists (select 1 from pg_trigger t where t.tgrelid = c.oid and t.tgname = 'set_updated_at')),
  null,
  'set_updated_at trigger is attached to every table with updated_at');

-- Actor and request id come from the backend's SET LOCAL settings.
insert into auth.users (id, email, aud, role, raw_app_meta_data, raw_user_meta_data)
values ('33333333-3333-4333-8333-333333333333', 'audit-actor@example.test', 'authenticated', 'authenticated',
        '{"rms_activate": true}', '{"full_name": "Audit Actor"}');

select set_config('app.user_id',    '33333333-3333-4333-8333-333333333333', true);
select set_config('app.request_id', 'req-audit-test-1', true);

insert into public.departments (id, code, name)
values ('dddddddd-0000-4000-8000-000000000001', 'TEST_AUDIT_DEPT', 'Audit Test Dept');

select results_eq(
  $$select action, actor_id, request_id, "new" ->> 'code'
      from public.audit_log
     where table_name = 'public.departments' and row_id = 'dddddddd-0000-4000-8000-000000000001'$$,
  $$values ('INSERT'::text, '33333333-3333-4333-8333-333333333333'::uuid, 'req-audit-test-1'::text, 'TEST_AUDIT_DEPT'::text)$$,
  'INSERT is audited with actor and request id');

select is((select created_by from public.departments where id = 'dddddddd-0000-4000-8000-000000000001'),
          '33333333-3333-4333-8333-333333333333'::uuid, 'created_by defaults to app.user_id');

update public.departments set name = 'Audit Test Dept (renamed)'
 where id = 'dddddddd-0000-4000-8000-000000000001';

select results_eq(
  $$select changed_fields, "old" ->> 'name', "new" ->> 'name'
      from public.audit_log
     where table_name = 'public.departments' and row_id = 'dddddddd-0000-4000-8000-000000000001'
       and action = 'UPDATE'$$,
  $$values (array['name']::text[], 'Audit Test Dept'::text, 'Audit Test Dept (renamed)'::text)$$,
  'UPDATE is audited with old/new values and changed fields');

delete from public.departments where id = 'dddddddd-0000-4000-8000-000000000001';
select is(
  (select count(*)::int from public.audit_log
    where table_name = 'public.departments' and row_id = 'dddddddd-0000-4000-8000-000000000001'
      and action = 'DELETE' and "old" ->> 'code' = 'TEST_AUDIT_DEPT'),
  1, 'DELETE is audited with the old row');

-- Composite primary keys are recorded as "col1:col2".
insert into public.user_roles (user_id, role_id)
select '33333333-3333-4333-8333-333333333333', id from public.roles where code = 'TECHNICIAN';
select is(
  (select row_id from public.audit_log where table_name = 'public.user_roles' and action = 'INSERT'
    order by id desc limit 1),
  '33333333-3333-4333-8333-333333333333:' || (select id::text from public.roles where code = 'TECHNICIAN'),
  'composite-key rows are audited with a composite row id');

-- An invalid app.user_id is rejected rather than silently ignored.
select set_config('app.user_id', 'not-a-uuid', true);
select throws_ok($$insert into public.departments (code, name) values ('TEST_BAD_ACTOR','x')$$,
                 '22P02', null, 'invalid app.user_id is rejected');
select set_config('app.user_id', '33333333-3333-4333-8333-333333333333', true);

-- config_change_log: insert-only (G-17)
insert into public.config_change_log (entity_type, entity_id, action, before, after, reason)
values ('system_settings', 'page_size', 'UPDATE', '{"value":25}', '{"value":50}', 'pgTAP');
select is(
  (select changed_by from public.config_change_log where reason = 'pgTAP'),
  '33333333-3333-4333-8333-333333333333'::uuid, 'config_change_log records the acting user');
select throws_ok($$update public.config_change_log set reason = 'tampered' where reason = 'pgTAP'$$,
                 '42501', null, 'config_change_log rejects UPDATE');
select throws_ok($$delete from public.config_change_log where reason = 'pgTAP'$$,
                 '42501', null, 'config_change_log rejects DELETE');
select throws_ok($$truncate public.config_change_log$$,
                 '42501', null, 'config_change_log rejects TRUNCATE');

-- audit_log: insert-only (G-17)
select throws_ok($$update public.audit_log set actor_id = null$$, '42501', null, 'audit_log rejects UPDATE');
select throws_ok($$delete from public.audit_log$$,               '42501', null, 'audit_log rejects DELETE');
select throws_ok($$truncate public.audit_log$$,                  '42501', null, 'audit_log rejects TRUNCATE');

-- The backend role has no UPDATE/DELETE privilege on the logs at all.
select ok(not has_table_privilege('rms_api', 'public.audit_log', 'UPDATE')
          and not has_table_privilege('rms_api', 'public.audit_log', 'DELETE'),
          'rms_api holds no UPDATE/DELETE on audit_log');
select ok(not has_table_privilege('rms_api', 'public.config_change_log', 'UPDATE')
          and not has_table_privilege('rms_api', 'public.config_change_log', 'DELETE'),
          'rms_api holds no UPDATE/DELETE on config_change_log');
select ok(has_table_privilege('rms_api', 'public.config_change_log', 'INSERT')
          and has_table_privilege('rms_api', 'public.option_items', 'UPDATE'),
          'rms_api can insert config log rows and edit config');

select * from finish();
rollback;
