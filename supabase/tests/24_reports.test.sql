-- =============================================================================
-- 24_reports.test.sql — P4-02 reports (20261106000200_p4_02_reports.sql):
-- report catalogue, column preferences tied to it, saved filters, the private rms_reports
-- schema (rms_api only) and the R-14 reconciliation view.
-- =============================================================================
begin;
select plan(16);

select is((select count(*)::int from public.report_definitions), 18, '18 reports R-01..R-18');
select is(
  (select count(*)::int from public.report_definitions where code !~ '^R-(0[1-9]|1[0-8])$'),
  0, 'catalogue codes are R-01..R-18');
select has_view('rms_reports', 'gs_stage_times', 'GS stage times view');
select has_view('rms_reports', 'user_activity_events', 'user activity view');
select has_view('rms_reports', 'stock_reconciliation_exceptions', 'R-14 view');

-- Private schema: rms_api reads, anon / authenticated cannot even see the schema.
select ok(has_schema_privilege('rms_api', 'rms_reports', 'USAGE'), 'rms_api uses rms_reports');
select ok(not has_schema_privilege('anon', 'rms_reports', 'USAGE'), 'anon has no rms_reports');
select ok(not has_schema_privilege('authenticated', 'rms_reports', 'USAGE'),
          'authenticated has no rms_reports');
select ok(has_table_privilege('rms_api', 'rms_reports.stock_reconciliation_exceptions', 'SELECT'),
          'rms_api reads the reconciliation view');
select ok(not has_table_privilege('rms_api', 'public.report_definitions', 'INSERT')
          and not has_table_privilege('rms_api', 'public.report_definitions', 'DELETE'),
          'report codes are fixed: rms_api may only relabel');
select ok((select bool_and(c.relrowsecurity) from pg_class c
            where c.oid in ('public.report_definitions'::regclass,
                            'public.report_saved_filters'::regclass)),
          'RLS enabled on the report tables');

-- A healthy ledger has no reconciliation exceptions (same formulas as scripts/integrity_check.sql).
select is((select count(*)::int from rms_reports.stock_reconciliation_exceptions), 0,
          'no stock reconciliation exceptions on a healthy ledger');

-- Column preferences: a known report, a non-empty list of distinct string keys.
select throws_ok(
  $$insert into public.report_column_prefs (role_id, report_code, columns)
    values ((select id from public.roles where code = 'ACCOUNTS'), 'R-99', '["a"]')$$,
  '23503', null, 'column preferences must name a catalogue report');
select throws_like(
  $$insert into public.report_column_prefs (role_id, report_code, columns)
    values ((select id from public.roles where code = 'ACCOUNTS'), 'R-16', '["a","a"]')$$,
  '%more than once%', 'a column is listed at most once');
select throws_ok(
  $$insert into public.report_column_prefs (role_id, report_code, columns)
    values ((select id from public.roles where code = 'ACCOUNTS'), 'R-16', '[]')$$,
  '23514', null, 'column preferences are not empty');

-- Saved filters: one default per user and report.
insert into auth.users (id, email)
values ('22222222-2222-2222-2222-222222222222', 'report_test@example.com')
on conflict do nothing;
insert into public.profiles (id, full_name, is_active)
values ('22222222-2222-2222-2222-222222222222', 'Report Test', true)
on conflict do nothing;

select throws_ok(
  $$insert into public.report_saved_filters (user_id, report_code, name, is_default)
    select p.id, 'R-03', n, true
      from (select id from public.profiles limit 1) p, (values ('a'), ('b')) v(n)$$,
  '23505', null, 'at most one default saved filter per user and report');

select * from finish();
rollback;
