-- Read-only post-deploy verification of an RMS database (docs/DATABASE_MIGRATION_GUIDE.md §6).
-- Safe on production: SELECT only, no writes. Run as the postgres user:
--   psql "<connection string>" -X -v ON_ERROR_STOP=1 -f scripts/verify_production_db.sql
-- Every row must show ok = true. Mirrors supabase/tests/40_production_hardening.test.sql.

with checks(check_name, ok, detail) as (
  select 'migrations applied',
         (select count(*) from supabase_migrations.schema_migrations) >= 52,
         (select count(*)::text || ' rows; latest ' || max(version) from supabase_migrations.schema_migrations)
  union all
  select 'RLS on every public/rms_private table',
         not exists (select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
                      where n.nspname in ('public', 'rms_private') and c.relkind in ('r', 'p')
                        and not c.relrowsecurity),
         null
  union all
  select 'anon holds no table privileges',
         not exists (select 1 from information_schema.role_table_grants
                      where table_schema = 'public' and grantee = 'anon'),
         null
  union all
  select 'anon cannot execute public functions',
         not exists (select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
                      where n.nspname = 'public' and has_function_privilege('anon', p.oid, 'EXECUTE')),
         null
  union all
  select 'SECURITY DEFINER functions pin search_path',
         not exists (select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
                      where n.nspname in ('public', 'rms_private') and p.prosecdef
                        and not exists (select 1 from unnest(coalesce(p.proconfig, '{}')) c
                                         where c like 'search_path=%')),
         null
  union all
  select 'rms_api: login, BYPASSRLS, not superuser',
         coalesce((select rolcanlogin and rolbypassrls and not rolsuper
                     from pg_roles where rolname = 'rms_api'), false),
         null
  union all
  select 'rms_api has a password',
         -- pg_authid is readable by postgres on Supabase; NULL means the role cannot log in.
         coalesce((select rolpassword is not null from pg_authid where rolname = 'rms_api'), false),
         null
  union all
  select 'evidence buckets private',
         (select count(*) from storage.buckets
           where id in ('rms-videos', 'rms-documents') and not public) = 2,
         null
  union all
  select 'no storage.objects policies (signed URLs only)',
         not exists (select 1 from pg_policies where schemaname = 'storage' and tablename = 'objects'),
         null
  union all
  select 'reference seed loaded',
         (select count(*) from public.roles) >= 13
           and (select count(*) from public.permissions) >= 151
           and (select count(*) from public.role_permissions) > 0
           and (select count(*) from public.form_versions where status = 'PUBLISHED') > 0
           and (select count(*) from public.workflow_versions where status = 'PUBLISHED') = 1,
         (select format('%s roles, %s permissions, %s grants',
                        (select count(*) from public.roles), (select count(*) from public.permissions),
                        (select count(*) from public.role_permissions)))
  union all
  select 'master data loaded',
         (select count(*) from public.stations) > 0 and (select count(*) from public.parties) > 0
           and (select count(*) from public.products) > 0,
         (select format('%s states, %s stations, %s parties, %s products',
                        (select count(*) from public.states), (select count(*) from public.stations),
                        (select count(*) from public.parties), (select count(*) from public.products)))
  union all
  select 'no DEMO data',
         not exists (select 1 from public.parties where code like 'DEMO-%' or name like '%(DEMO)%')
           and not exists (select 1 from public.products where code like 'DEMO-%' or name like '%(DEMO)%'),
         null
  union all
  select 'no local/UAT accounts',
         not exists (select 1 from auth.users where email like '%@rms.local'),
         null
  union all
  select 'at least one active Super Admin',
         (select count(*) from public.profiles where is_super_admin and is_active) >= 1,
         (select count(*)::text || ' active Super Admin(s)' from public.profiles
           where is_super_admin and is_active)
  union all
  select 'video limit within the plan (setting vs bucket)',
         (select (value #>> '{}')::bigint from public.system_settings where key = 'upload_max_video_bytes')
           <= (select file_size_limit from storage.buckets where id = 'rms-videos'),
         (select 'upload_max_video_bytes = ' || (value #>> '{}') from public.system_settings
           where key = 'upload_max_video_bytes')
)
select check_name, ok, detail from checks;
