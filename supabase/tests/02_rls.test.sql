-- P1-02 pgTAP: RLS baseline (master plan §9.4). anon sees nothing; authenticated sees only its
-- own notifications and may only set read_at on them.
begin;
create extension if not exists pgtap with schema extensions;
select plan(17);

select is(
  (select array_agg(c.relname::text order by c.relname)
     from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname in ('public','rms_private') and c.relkind = 'r' and not c.relrowsecurity),
  null,
  'RLS is enabled on every public and rms_private table');

select is(
  (select array_agg(c.relname::text order by c.relname)
     from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname in ('public','rms_private') and c.relkind = 'r'
      and (has_table_privilege('anon', c.oid, 'SELECT') or has_table_privilege('anon', c.oid, 'INSERT')
        or has_table_privilege('anon', c.oid, 'UPDATE') or has_table_privilege('anon', c.oid, 'DELETE'))),
  null,
  'anon has no privilege on any table');

select is(
  (select array_agg(c.relname::text order by c.relname)
     from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname in ('public','rms_private') and c.relkind = 'r'
      and has_table_privilege('authenticated', c.oid, 'SELECT')),
  array['notifications'],
  'authenticated can SELECT only notifications');

select is(
  (select array_agg(c.relname::text order by c.relname)
     from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname in ('public','rms_private') and c.relkind = 'r'
      and (has_table_privilege('authenticated', c.oid, 'INSERT')
        or has_table_privilege('authenticated', c.oid, 'DELETE'))),
  null,
  'authenticated cannot INSERT or DELETE anywhere');

select is(
  (select count(*)::int from pg_policies where schemaname = 'public' and 'anon' = any (roles)),
  0, 'no anon policies');

select ok(
  exists (select 1 from pg_publication_tables
           where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'notifications'),
  'notifications is in the supabase_realtime publication');

-- Fixtures: two users with one notification each.
insert into auth.users (id, email, aud, role, raw_app_meta_data, raw_user_meta_data)
values ('11111111-1111-4111-8111-111111111111', 'rls-u1@example.test', 'authenticated', 'authenticated', '{}', '{}'),
       ('22222222-2222-4222-8222-222222222222', 'rls-u2@example.test', 'authenticated', 'authenticated', '{}', '{}');
insert into public.notifications (id, user_id, type, title)
values ('aaaaaaaa-0000-4000-8000-000000000001', '11111111-1111-4111-8111-111111111111', 'TEST', 'for u1'),
       ('aaaaaaaa-0000-4000-8000-000000000002', '22222222-2222-4222-8222-222222222222', 'TEST', 'for u2');

-- anon: denied everywhere (privilege error, not just empty results).
set local role anon;
select throws_ok('select * from public.option_items',   '42501', null, 'anon cannot read option_items');
select throws_ok('select * from public.notifications',  '42501', null, 'anon cannot read notifications');
select throws_ok('select * from public.profiles',       '42501', null, 'anon cannot read profiles');
reset role;

-- authenticated as u1
set local role authenticated;
select set_config('request.jwt.claims',
  '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated"}', true);

select results_eq('select title from public.notifications', array['for u1'],
  'authenticated sees only its own notifications');
select throws_ok('select * from public.roles',          '42501', null, 'authenticated cannot read roles');
select throws_ok('select * from public.system_settings','42501', null, 'authenticated cannot read business/config tables');
select throws_ok($$insert into public.notifications (user_id, type, title)
                   values ('11111111-1111-4111-8111-111111111111','X','x')$$,
                 '42501', null, 'authenticated cannot insert notifications');
select throws_ok($$update public.notifications set title = 'hacked'
                   where id = 'aaaaaaaa-0000-4000-8000-000000000001'$$,
                 '42501', null, 'authenticated cannot update columns other than read_at');
select lives_ok($$update public.notifications set read_at = now()
                  where id = 'aaaaaaaa-0000-4000-8000-000000000001'$$,
                'authenticated can mark its own notification read');
-- RLS silently filters another user's row out of the UPDATE (checked below as postgres).
update public.notifications set read_at = now() where id = 'aaaaaaaa-0000-4000-8000-000000000002';
reset role;

select is((select read_at is not null from public.notifications where id = 'aaaaaaaa-0000-4000-8000-000000000001'),
          true, 'read_at was set on own notification');
select is((select read_at from public.notifications where id = 'aaaaaaaa-0000-4000-8000-000000000002'),
          null, 'authenticated cannot mark another user''s notification read');

select * from finish();
rollback;
