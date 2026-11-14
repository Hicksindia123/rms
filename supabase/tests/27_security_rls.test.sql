-- P4-05 pgTAP: Comprehensive Security, RLS Hardening & Audit Immutability Test
begin;
create extension if not exists pgtap with schema extensions;
select plan(12);

-- 1. All tables in public and rms_private must have Row Level Security enabled
select is(
  (select array_agg(c.relname::text order by c.relname)
     from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname in ('public','rms_private') and c.relkind = 'r' and not c.relrowsecurity),
  null,
  'RLS is enabled on ALL public and rms_private tables without exception');

-- 2. anon role has zero table privilege anywhere in public or rms_private
select is(
  (select array_agg(c.relname::text order by c.relname)
     from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname in ('public','rms_private') and c.relkind = 'r'
      and (has_table_privilege('anon', c.oid, 'SELECT')
        or has_table_privilege('anon', c.oid, 'INSERT')
        or has_table_privilege('anon', c.oid, 'UPDATE')
        or has_table_privilege('anon', c.oid, 'DELETE'))),
  null,
  'anon role has zero privileges on all tables');

-- 3. audit_log is strictly append-only (UPDATE and DELETE prohibited, SQLSTATE 42501)
select throws_ok(
  'update public.audit_log set table_name = ''hacked'' where true',
  '42501',
  null,
  'audit_log rejects any UPDATE statement with 42501');

select throws_ok(
  'delete from public.audit_log where true',
  '42501',
  null,
  'audit_log rejects any DELETE statement with 42501');

-- 4. user_activity is strictly append-only (UPDATE and DELETE prohibited, SQLSTATE 42501)
-- The guard trigger is row-level, so a fresh `supabase db reset` (no activity rows yet) would let the
-- statements succeed vacuously. Insert one row first so the guard is actually exercised (G-17).
insert into auth.users (id, email, aud, role, raw_app_meta_data, raw_user_meta_data)
values ('27272727-2727-4727-8727-272727272727', 'rls-activity@example.test', 'authenticated',
        'authenticated', '{"rms_activate": true}', '{"full_name": "RLS Activity Actor"}');
insert into public.user_activity (user_id, activity_type)
values ('27272727-2727-4727-8727-272727272727', 'SIGN_IN');

select throws_ok(
  'update public.user_activity set activity_type = ''hacked'' where true',
  '42501',
  null,
  'user_activity rejects any UPDATE statement with 42501');

select throws_ok(
  'delete from public.user_activity where true',
  '42501',
  null,
  'user_activity rejects any DELETE statement with 42501');

-- 5. anon direct queries are rejected with SQLSTATE 42501
set local role anon;

select throws_ok(
  'select * from public.goods_slips',
  '42501',
  null,
  'anon is blocked from reading goods_slips');

select throws_ok(
  'select * from public.stock_movements',
  '42501',
  null,
  'anon is blocked from reading stock_movements');

select throws_ok(
  'select * from public.credit_notes',
  '42501',
  null,
  'anon is blocked from reading credit_notes');

select throws_ok(
  'select * from public.audit_log',
  '42501',
  null,
  'anon is blocked from reading audit_log');

select throws_ok(
  'select * from public.saved_views',
  '42501',
  null,
  'anon is blocked from reading saved_views');

select throws_ok(
  'select * from public.system_settings',
  '42501',
  null,
  'anon is blocked from reading system_settings');

reset role;
rollback;
