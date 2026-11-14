-- P1-05 · migration 20261114000500: user administration guards (production audit B10).
--   * profiles.must_change_password exists (DEC-50)
--   * nobody deactivates themselves or removes their own Super Admin flag
--   * through the API the last active Super Admin cannot be deactivated or demoted
--   * through the API (actor set) only an active Super Admin grants / revokes the SUPER_ADMIN role
-- Self-contained: works on a bare `supabase db reset` (no users) and on a UAT database.

begin;
select plan(11);

select has_column('public', 'profiles', 'must_change_password', 'profiles.must_change_password exists');

-- Test users (profiles created ACTIVE by the auth trigger via rms_activate).
insert into auth.users (id, email, aud, role, raw_app_meta_data, raw_user_meta_data) values
  ('a1a1a1a1-0000-4000-8000-000000000001', 'p105-a@example.test', 'authenticated', 'authenticated',
   '{"rms_activate": true}', '{"full_name": "P105 A"}'),
  ('a1a1a1a1-0000-4000-8000-000000000002', 'p105-b@example.test', 'authenticated', 'authenticated',
   '{"rms_activate": true}', '{"full_name": "P105 B"}'),
  ('a1a1a1a1-0000-4000-8000-000000000003', 'p105-c@example.test', 'authenticated', 'authenticated',
   '{"rms_activate": true}', '{"full_name": "P105 C"}'),
  ('a1a1a1a1-0000-4000-8000-000000000004', 'p105-d@example.test', 'authenticated', 'authenticated',
   '{"rms_activate": true}', '{"full_name": "P105 D"}');

-- A becomes Super Admin (granted by an existing active SA, or the bootstrap path on a bare DB).
select set_config('app.user_id',
  coalesce((select id::text from public.profiles where is_super_admin and is_active limit 1), ''), true);
update public.profiles set is_super_admin = true where id = 'a1a1a1a1-0000-4000-8000-000000000001';
select set_config('app.user_id', '', true);
-- Leave A as the only active Super Admin (maintenance path, no actor).
update public.profiles set is_active = false
 where is_super_admin and is_active and id <> 'a1a1a1a1-0000-4000-8000-000000000001';

-- Through the API (actor set: C, a plain user) the last active Super Admin stays.
select set_config('app.user_id', 'a1a1a1a1-0000-4000-8000-000000000003', true);
select throws_ok(
  $$update public.profiles set is_active = false where id = 'a1a1a1a1-0000-4000-8000-000000000001'$$,
  '42501', 'P1-05: the last active Super Admin cannot be deactivated or demoted',
  'the last active Super Admin cannot be deactivated');
select throws_ok(
  $$update public.profiles set is_super_admin = false where id = 'a1a1a1a1-0000-4000-8000-000000000001'$$,
  '42501', null, 'the last active Super Admin cannot be demoted');
select set_config('app.user_id', '', true);

-- Self-protection (actor = A).
select set_config('app.user_id', 'a1a1a1a1-0000-4000-8000-000000000001', true);
update public.profiles set is_super_admin = true where id = 'a1a1a1a1-0000-4000-8000-000000000002';
select throws_ok(
  $$update public.profiles set is_active = false where id = 'a1a1a1a1-0000-4000-8000-000000000001'$$,
  '42501', null, 'a user cannot deactivate themselves');
select throws_ok(
  $$update public.profiles set is_super_admin = false where id = 'a1a1a1a1-0000-4000-8000-000000000001'$$,
  '42501', null, 'a user cannot remove their own Super Admin flag');
select lives_ok(
  $$update public.profiles set is_active = false where id = 'a1a1a1a1-0000-4000-8000-000000000002'$$,
  'an active Super Admin can deactivate another (non-last) Super Admin');

-- SUPER_ADMIN marker role.
select set_config('app.user_id', 'a1a1a1a1-0000-4000-8000-000000000003', true);
select throws_ok(
  $$insert into public.user_roles (user_id, role_id)
    select 'a1a1a1a1-0000-4000-8000-000000000003', id from public.roles where code = 'SUPER_ADMIN'$$,
  '42501', null, 'a non-Super-Admin actor cannot grant the SUPER_ADMIN role');
select lives_ok(
  $$insert into public.user_roles (user_id, role_id)
    select 'a1a1a1a1-0000-4000-8000-000000000003', id from public.roles where code = 'GATE_INWARD'$$,
  'other roles are not affected by the SUPER_ADMIN role guard');
select set_config('app.user_id', 'a1a1a1a1-0000-4000-8000-000000000001', true);
select lives_ok(
  $$insert into public.user_roles (user_id, role_id)
    select 'a1a1a1a1-0000-4000-8000-000000000004', id from public.roles where code = 'SUPER_ADMIN'$$,
  'an active Super Admin can grant the SUPER_ADMIN role');
select set_config('app.user_id', 'a1a1a1a1-0000-4000-8000-000000000003', true);
select throws_ok(
  $$delete from public.user_roles
     where user_id = 'a1a1a1a1-0000-4000-8000-000000000004'
       and role_id = (select id from public.roles where code = 'SUPER_ADMIN')$$,
  '42501', null, 'a non-Super-Admin actor cannot revoke the SUPER_ADMIN role');
select set_config('app.user_id', '', true);
select lives_ok(
  $$delete from public.user_roles
     where user_id = 'a1a1a1a1-0000-4000-8000-000000000004'
       and role_id = (select id from public.roles where code = 'SUPER_ADMIN')$$,
  'maintenance scripts (no actor) are not blocked');

select * from finish();
rollback;
