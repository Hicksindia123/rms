-- =============================================================================
-- 23_dashboards.test.sql — P4-01 dashboards (20261106000100_p4_01_dashboards.sql):
-- widget catalogue, per-role layouts (validated by trigger), append-only guard / job logs,
-- the locked login-stats function, RLS and the authenticated baseline (no new grants).
-- =============================================================================
begin;
select plan(16);

select is((select count(*)::int from public.dashboard_widgets), 20, '20 widgets in the catalogue');
select is(
  (select count(*)::int from public.roles r
    where not exists (select 1 from public.role_dashboard_layouts l where l.role_id = r.id)
      and r.code in ('SUPER_ADMIN','GATE_INWARD','INWARD_VERIFIER','REPLACEMENT_MANAGER',
                     'INTERMEDIATE_STORE_MANAGER','TECHNICIAN_COORDINATOR','TECHNICIAN',
                     'SPARE_PARTS_TECHNICIAN','SPARE_PARTS_MANAGER','ACCOUNTS','DISPATCH',
                     'MAIN_STORE','MANAGEMENT_VIEWER')),
  0, 'every §3.3 role has a seeded default dashboard');

-- Layout validation trigger
select throws_like(
  $$update public.role_dashboard_layouts set widgets = '[{"code":"NOPE","size":"S"}]'
     where role_id = (select id from public.roles where code = 'TECHNICIAN')$$,
  '%unknown widgets%', 'a layout cannot name an unknown widget');
select throws_like(
  $$update public.role_dashboard_layouts set widgets = '[{"code":"MY_TASKS","size":"XL"}]'
     where role_id = (select id from public.roles where code = 'TECHNICIAN')$$,
  '%invalid sizes%', 'a layout size must be S, M or L');
select throws_like(
  $$update public.role_dashboard_layouts
       set widgets = '[{"code":"MY_TASKS","size":"S"},{"code":"MY_TASKS","size":"M"}]'
     where role_id = (select id from public.roles where code = 'TECHNICIAN')$$,
  '%more than once%', 'a widget appears at most once per layout');
select throws_ok(
  $$update public.role_dashboard_layouts set widgets = '{}'::jsonb
     where role_id = (select id from public.roles where code = 'TECHNICIAN')$$,
  '22023', null, 'widgets must be a JSON array (rejected by the validation trigger)');

-- RLS on, no access for anon / authenticated (P1-02 baseline: only notifications)
select ok((select bool_and(c.relrowsecurity) from pg_class c
            where c.oid in ('public.dashboard_widgets'::regclass,
                            'public.role_dashboard_layouts'::regclass,
                            'public.system_guard_events'::regclass,
                            'public.job_runs'::regclass)),
          'RLS enabled on the four P4-01 tables');
select ok(not has_table_privilege('authenticated', 'public.role_dashboard_layouts', 'select'),
          'authenticated cannot read layouts directly');
select ok(not has_table_privilege('authenticated', 'public.system_guard_events', 'select'),
          'authenticated cannot read guard events');
select ok(not has_table_privilege('authenticated', 'public.workflow_tasks', 'select'),
          'workflow_tasks stays closed to authenticated (realtime via notifications only)');

-- Append-only logs and a fixed widget catalogue for rms_api
select ok(not has_table_privilege('rms_api', 'public.system_guard_events', 'delete')
          and not has_table_privilege('rms_api', 'public.system_guard_events', 'update'),
          'rms_api cannot change or delete guard events');
select ok(not has_table_privilege('rms_api', 'public.job_runs', 'delete')
          and not has_table_privilege('rms_api', 'public.job_runs', 'update'),
          'rms_api cannot change or delete job runs');
select ok(not has_table_privilege('rms_api', 'public.dashboard_widgets', 'insert')
          and not has_table_privilege('rms_api', 'public.dashboard_widgets', 'delete'),
          'rms_api can relabel widgets but never add or delete codes');
select throws_ok(
  $$insert into public.system_guard_events (guard_code, source) values ('G-23', 'SERVICE')$$,
  '23514', null, 'guard events accept only G-01…G-22');

-- Login statistics: a locked SECURITY DEFINER function, executable by rms_api only
select ok(has_function_privilege('rms_api', 'rms_private.auth_login_stats(timestamptz)', 'execute')
          and not has_function_privilege('authenticated',
                                         'rms_private.auth_login_stats(timestamptz)', 'execute'),
          'auth_login_stats is executable by rms_api only');
select lives_ok($$select * from rms_private.auth_login_stats(now() - interval '7 days')$$,
                'auth_login_stats runs');

select * from finish();
rollback;
