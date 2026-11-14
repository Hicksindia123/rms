-- Production audit Phase 2 (2026-11-14): database settings Supabase Cloud depends on.
--   * every SECURITY DEFINER function in public / rms_private pins search_path (migration 20261114000600)
--   * the API role is a login role that bypasses RLS but is not a superuser
--   * anon has no table privileges and no callable function in public; RLS on every table
--   * private buckets stay private and have no storage.objects policies (signed URLs only)

begin;
select plan(8);

select is(
  (select count(*)::int from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname in ('public', 'rms_private') and p.prosecdef
      and not exists (select 1 from unnest(coalesce(p.proconfig, '{}')) c
                       where c like 'search_path=%')),
  0, 'every SECURITY DEFINER function pins search_path');

select ok(
  (select rolcanlogin and rolbypassrls and not rolsuper from pg_roles where rolname = 'rms_api'),
  'rms_api: login, BYPASSRLS, not superuser');

select is(
  (select count(*)::int from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname in ('public', 'rms_private') and c.relkind in ('r', 'p')
      and not c.relrowsecurity),
  0, 'RLS is enabled on every table');

select is(
  (select count(*)::int from information_schema.role_table_grants
    where table_schema = 'public' and grantee = 'anon'),
  0, 'anon holds no table privileges in public');

select is(
  (select count(*)::int from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and has_function_privilege('anon', p.oid, 'EXECUTE')),
  0, 'anon cannot execute any function in public');

select results_eq(
  $$select id, public from storage.buckets where id in ('rms-videos', 'rms-documents') order by id$$,
  $$values ('rms-documents'::text, false), ('rms-videos'::text, false)$$,
  'evidence buckets are private');

select is(
  (select count(*)::int from pg_policies where schemaname = 'storage' and tablename = 'objects'),
  0, 'no storage.objects policies: only backend-signed URLs reach private files');

select ok(
  (select allowed_mime_types is not null and file_size_limit is not null
     from storage.buckets where id = 'rms-documents')
  and (select allowed_mime_types is not null and file_size_limit is not null
     from storage.buckets where id = 'rms-videos'),
  'private buckets carry a MIME allow-list and a size ceiling');

select * from finish();
rollback;
