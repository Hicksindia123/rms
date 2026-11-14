-- P1-02 pgTAP: DB-level guards on the foundation schema.
--   * profile auto-creation from auth.users (inactive unless created by the admin API)
--   * is_super_admin only settable by a Super Admin (§8.1)
--   * system roles cannot be deleted (§8.1)
--   * option codes immutable, hazard behaviour locked (CLAUDE.md rule e, §10)
--   * G-18 published form / workflow versions immutable
--   * master CHECK constraints; storage buckets
begin;
create extension if not exists pgtap with schema extensions;
select plan(30);

-- ---------------------------------------------------------------------------
-- Profiles from auth.users
-- ---------------------------------------------------------------------------
insert into auth.users (id, email, aud, role, raw_app_meta_data, raw_user_meta_data)
values ('44444444-4444-4444-8444-444444444444', 'self@example.test', 'authenticated', 'authenticated',
        '{}', '{"full_name": "Self Created"}'),
       ('55555555-5555-4555-8555-555555555555', 'admin-made@example.test', 'authenticated', 'authenticated',
        '{"rms_activate": true}', '{"full_name": "Admin Made", "employee_code": "E-555"}');

select results_eq(
  $$select full_name, is_active, is_super_admin, email::text from public.profiles
     where id = '44444444-4444-4444-8444-444444444444'$$,
  $$values ('Self Created'::text, false, false, 'self@example.test'::text)$$,
  'a new auth user gets an INACTIVE profile by default');
select results_eq(
  $$select full_name, is_active, employee_code from public.profiles
     where id = '55555555-5555-4555-8555-555555555555'$$,
  $$values ('Admin Made'::text, true, 'E-555'::text)$$,
  'a user created by the admin API (app_metadata.rms_activate) is ACTIVE');

update auth.users set email = 'self-new@example.test' where id = '44444444-4444-4444-8444-444444444444';
select is((select email::text from public.profiles where id = '44444444-4444-4444-8444-444444444444'),
          'self-new@example.test', 'profile email follows auth email');

select throws_ok($$delete from auth.users where id = '44444444-4444-4444-8444-444444444444'$$,
                 '23503', null, 'an auth user with a profile cannot be hard-deleted (deactivate instead)');

-- ---------------------------------------------------------------------------
-- is_super_admin guard
-- ---------------------------------------------------------------------------
-- Bootstrap: with no active Super Admin (true after a reset; forced here in case the dev DB
-- already has one — rolled back at the end) → allowed.
update public.profiles set is_active = false where is_super_admin;
select lives_ok($$update public.profiles set is_super_admin = true, is_active = true
                  where id = '55555555-5555-4555-8555-555555555555'$$,
                'the first Super Admin can be bootstrapped');

select set_config('app.user_id', '44444444-4444-4444-8444-444444444444', true);
select throws_ok($$update public.profiles set is_super_admin = true
                   where id = '44444444-4444-4444-8444-444444444444'$$,
                 '42501', null, 'a non-Super-Admin cannot grant is_super_admin');
select set_config('app.user_id', '', true);
select throws_ok($$update public.profiles set is_super_admin = true
                   where id = '44444444-4444-4444-8444-444444444444'$$,
                 '42501', null, 'an anonymous (no actor) session cannot grant is_super_admin');
select set_config('app.user_id', '55555555-5555-4555-8555-555555555555', true);
select lives_ok($$update public.profiles set is_super_admin = true
                  where id = '44444444-4444-4444-8444-444444444444'$$,
                'an active Super Admin can grant is_super_admin');
select set_config('app.user_id', '', true);

-- ---------------------------------------------------------------------------
-- System roles
-- ---------------------------------------------------------------------------
select throws_ok($$delete from public.roles where code = 'TECHNICIAN'$$,
                 '42501', null, 'system roles cannot be deleted');
select throws_ok($$update public.roles set code = 'TECH2' where code = 'TECHNICIAN'$$,
                 '42501', null, 'system role codes cannot change');
select lives_ok($$update public.roles set name = 'Technician (renamed)' where code = 'TECHNICIAN'$$,
                'system roles can be relabelled');

-- ---------------------------------------------------------------------------
-- Option codes and hazard behaviour
-- ---------------------------------------------------------------------------
select throws_ok($$update public.option_items set code = 'DMT_BROKEN' where code = 'DMT_BROKEN_BODY'$$,
                 '42501', null, 'option codes are immutable');
select lives_ok($$update public.option_items set label = 'BROKEN / BODY DAMAGE (edited)' where code = 'DMT_BROKEN_BODY'$$,
                'option labels are editable');
select throws_ok($$update public.option_items set system_behavior = 'SELLABLE' where code = 'PRS_BROKEN_WITH_HG'$$,
                 '42501', null, 'hazard behaviour is locked (G-05)');
select throws_ok($$update public.option_sets set code = 'DMT_COND' where code = 'DMT_CONDITION'$$,
                 '42501', null, 'option set codes are immutable');

-- ---------------------------------------------------------------------------
-- G-18: published form versions are immutable
-- ---------------------------------------------------------------------------
insert into public.form_definitions (id, code, step_code, name)
values ('f0000000-0000-4000-8000-000000000001', 'TEST_FORM', 'S1_GATE', 'Test form');
insert into public.form_versions (id, form_definition_id, version_no)
values ('f0000000-0000-4000-8000-000000000011', 'f0000000-0000-4000-8000-000000000001', 1);
select lives_ok($$insert into public.form_fields (form_version_id, field_key, label, control_type)
                  values ('f0000000-0000-4000-8000-000000000011', 'remarks', 'Remarks', 'textarea')$$,
                'fields can be added to a DRAFT version');
select throws_ok($$insert into public.form_responses (entity_type, entity_id, form_version_id)
                   values ('test', gen_random_uuid(), 'f0000000-0000-4000-8000-000000000011')$$,
                 '23514', null, 'responses cannot reference a DRAFT version');

update public.form_versions
   set status = 'PUBLISHED', snapshot = '{"fields":["remarks"]}', published_at = now()
 where id = 'f0000000-0000-4000-8000-000000000011';

select throws_ok($$insert into public.form_fields (form_version_id, field_key, label, control_type)
                   values ('f0000000-0000-4000-8000-000000000011', 'extra', 'Extra', 'text')$$,
                 '42501', null, 'G-18: no fields can be added to a PUBLISHED version');
select throws_ok($$update public.form_fields set label = 'Changed'
                   where form_version_id = 'f0000000-0000-4000-8000-000000000011'$$,
                 '42501', null, 'G-18: fields of a PUBLISHED version cannot change');
select throws_ok($$update public.form_versions set snapshot = '{}'
                   where id = 'f0000000-0000-4000-8000-000000000011'$$,
                 '42501', null, 'G-18: the snapshot of a PUBLISHED version cannot change');
select throws_ok($$delete from public.form_versions where id = 'f0000000-0000-4000-8000-000000000011'$$,
                 '42501', null, 'G-18: a PUBLISHED version cannot be deleted');
select lives_ok($$insert into public.form_responses (entity_type, entity_id, form_version_id)
                  values ('test', gen_random_uuid(), 'f0000000-0000-4000-8000-000000000011')$$,
                'responses reference the PUBLISHED version');
select lives_ok($$update public.form_versions set status = 'RETIRED'
                  where id = 'f0000000-0000-4000-8000-000000000011'$$,
                'a PUBLISHED version can be retired');
select throws_ok($$update public.form_versions set status = 'PUBLISHED'
                   where id = 'f0000000-0000-4000-8000-000000000011'$$,
                 '42501', null, 'G-18: a RETIRED version is immutable');

-- G-18: published workflow versions are immutable
insert into public.workflow_definitions (id, code, name)
values ('e0000000-0000-4000-8000-000000000001', 'TEST_WF', 'Test workflow');
insert into public.workflow_versions (id, workflow_definition_id, version_no)
values ('e0000000-0000-4000-8000-000000000011', 'e0000000-0000-4000-8000-000000000001', 1);
insert into public.workflow_stages (id, workflow_version_id, code, label)
values ('e0000000-0000-4000-8000-000000000021', 'e0000000-0000-4000-8000-000000000011', 'STAGE_1', 'Stage-1');
insert into public.workflow_steps (id, workflow_version_id, stage_id, code, label)
values ('e0000000-0000-4000-8000-000000000031', 'e0000000-0000-4000-8000-000000000011',
        'e0000000-0000-4000-8000-000000000021', 'S1_GATE', 'Goods Slip (GS) Creation');
select throws_ok($$insert into public.step_assignments (workflow_step_id, assignment_type)
                   values ('e0000000-0000-4000-8000-000000000031', 'PERFORM')$$,
                 '23514', null, 'a step assignment needs exactly one of role / user');
update public.workflow_versions
   set status = 'PUBLISHED', snapshot = '{"steps":["S1_GATE"]}', published_at = now()
 where id = 'e0000000-0000-4000-8000-000000000011';
select throws_ok($$update public.workflow_steps set label = 'Changed'
                   where id = 'e0000000-0000-4000-8000-000000000031'$$,
                 '42501', null, 'G-18: steps of a PUBLISHED workflow cannot change');
select throws_ok($$insert into public.step_assignments (workflow_step_id, role_id, assignment_type)
                   select 'e0000000-0000-4000-8000-000000000031', id, 'PERFORM' from public.roles where code = 'GATE_INWARD'$$,
                 '42501', null, 'G-18: step assignments of a PUBLISHED workflow cannot change');

-- ---------------------------------------------------------------------------
-- Master CHECKs and storage
-- ---------------------------------------------------------------------------
select throws_ok($$insert into public.parties (code, name, gstin) values ('BAD-GSTIN', 'x', '12345')$$,
                 '23514', null, 'invalid GSTIN is rejected');
select results_eq(
  $$select id, public from storage.buckets where id like 'rms-%' order by id$$,
  $$values ('rms-branding'::text, true), ('rms-documents', false), ('rms-videos', false)$$,
  'storage buckets: two private, branding public');
select is((select count(*)::int from pg_policies
            where schemaname = 'storage' and tablename = 'objects'
              and (coalesce(qual, '') || coalesce(with_check, '')) like '%rms-%'),
          0, 'no storage.objects policies for RMS buckets (backend signs URLs)');

select * from finish();
rollback;
