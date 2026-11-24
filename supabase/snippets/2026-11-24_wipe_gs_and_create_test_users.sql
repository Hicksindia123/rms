-- =============================================================================
-- ONE-OFF PRODUCTION SCRIPT (2026-11-24). Run once, as the postgres role:
--   supabase db query --linked -f supabase/snippets/2026-11-24_wipe_gs_and_create_test_users.sql
-- or paste it into the Supabase SQL editor.
--
-- PART 1: removes every Goods Slip and all transaction data created by user actions (same scope
--   as 2026-11-19_wipe_goods_slips.sql, now also covering the P5-P11 tables: transfer slips,
--   store acknowledgement discrepancies, store analyses, Management approvals / revisions,
--   A/c GS entries, edit requests). GS numbers restart at 00001.
-- KEPT: users, roles, permissions, products, categories, parties, transporters, states/stations,
--   locations, Intermediate Stores + category map, containers, technicians, forms, workflows,
--   option lists, item field profiles, settings, branding, and the append-only ledgers audit_log,
--   config_change_log, user_activity and system_guard_events.
-- Files in Storage are NOT removed (Supabase blocks SQL deletes on storage.objects). Empty the
--   rms-documents and rms-videos buckets in the dashboard if wanted. Do NOT empty rms-branding.
--
-- PART 2: creates one TEST user per business role (16 users, all active, password below, no forced
--   password change). Idempotent: an e-mail that already exists is not re-created; its profile is
--   re-activated, its password reset to the one below and its role ensured.
--   No test Super Admin is created: G-guard profiles_guard_super_admin only lets an active Super
--   Admin grant that flag. Use the existing admin account (or grant it in User Management).
--   Test addresses use the reserved domain example.com, so no mail can reach a real person.
--   To remove the test users later: deactivate them in Admin -> User Management.
--
-- Everything runs in ONE transaction: any error rolls the whole script back.
-- =============================================================================

begin;

-- -----------------------------------------------------------------------------
-- PART 1: wipe all Goods Slips and their transactions
-- -----------------------------------------------------------------------------
-- TRUNCATE ... CASCADE also empties every table that references these (all GS / stock /
-- workflow / store-flow / approval / accounts children). No configuration or ledger table
-- references a transaction table (checked 2026-11-24 against the FK graph).
truncate table
  public.goods_slips,
  public.stock_items,
  public.dismantle_batches,
  public.container_audit_days,
  public.custody_transfers,
  public.technician_batches,
  public.store_issues,
  public.notification_events,
  public.notifications,
  public.attachments,
  public.credit_notes,
  public.form_responses,
  public.print_logs,
  public.number_series_counters,
  rms_private.idempotency_keys
cascade;

-- -----------------------------------------------------------------------------
-- PART 2: test users, one per role
-- -----------------------------------------------------------------------------
do $$
declare
  -- Shared password of every test user created by this script. Change it here if wanted.
  v_password constant text := 'RmsTest#2611!Qa';
  u    record;
  v_id uuid;
begin
  for u in
    select * from (values
      -- email                                   full name           emp code   role                         department
      ('ramesh.yadav@rmstest.example.com',      'Ramesh Yadav',      'TST-001', 'GATE_INWARD',                'GATE_SECURITY'),
      ('priya.sharma@rmstest.example.com',      'Priya Sharma',      'TST-002', 'INWARD_VERIFIER',            'REPLACEMENT_DEPT'),
      ('vikas.gupta@rmstest.example.com',       'Vikas Gupta',       'TST-003', 'TECHNICIAN_COORDINATOR',     'REPLACEMENT_DEPT'),
      ('neha.verma@rmstest.example.com',        'Neha Verma',        'TST-004', 'REPLACEMENT_MANAGER',        'REPLACEMENT_DEPT'),
      ('sandeep.chauhan@rmstest.example.com',   'Sandeep Chauhan',   'TST-005', 'INTERMEDIATE_STORE_MANAGER', 'INTERMEDIATE_STORE'),
      ('manoj.kumar@rmstest.example.com',       'Manoj Kumar',       'TST-006', 'ISTORE_OP',                  'INTERMEDIATE_STORE'),
      ('pooja.rawat@rmstest.example.com',       'Pooja Rawat',       'TST-007', 'ISTORE_DT',                  'INTERMEDIATE_STORE'),
      ('arjun.mehta@rmstest.example.com',       'Arjun Mehta',       'TST-008', 'ISTORE_RI',                  'INTERMEDIATE_STORE'),
      ('rajesh.agarwal@rmstest.example.com',    'Rajesh Agarwal',    'TST-009', 'MANAGEMENT',                 null),
      ('kavita.bansal@rmstest.example.com',     'Kavita Bansal',     'TST-010', 'MANAGEMENT_VIEWER',          null),
      ('suresh.jain@rmstest.example.com',       'Suresh Jain',       'TST-011', 'ACCOUNTS',                   'ACCOUNTS'),
      ('imran.khan@rmstest.example.com',        'Imran Khan',        'TST-012', 'TECHNICIAN',                 'REPLACEMENT_DEPT'),
      ('ravi.prakash@rmstest.example.com',      'Ravi Prakash',      'TST-013', 'SPARE_PARTS_TECHNICIAN',     'REPLACEMENT_DEPT'),
      ('anil.saxena@rmstest.example.com',       'Anil Saxena',       'TST-014', 'SPARE_PARTS_MANAGER',        'REPLACEMENT_DEPT'),
      ('deepika.negi@rmstest.example.com',      'Deepika Negi',      'TST-015', 'DISPATCH',                   'MAIN_STORE'),
      ('harish.tiwari@rmstest.example.com',     'Harish Tiwari',     'TST-016', 'MAIN_STORE',                 'MAIN_STORE')
    ) as t(email, full_name, emp_code, role_code, dept_code)
  loop
    if not exists (select 1 from public.roles where code = u.role_code) then
      raise exception 'Role % does not exist in this database; aborting', u.role_code;
    end if;

    select id into v_id from auth.users where lower(email) = lower(u.email);

    if v_id is null then
      v_id := gen_random_uuid();
      -- Same shape as a user created by the Auth admin API. Token columns must be '' (not NULL)
      -- or GoTrue fails to sign the user in. rms_activate=true makes the profile trigger
      -- (rms_private.handle_new_auth_user) create the profile ACTIVE.
      insert into auth.users (
        instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
        raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
        confirmation_token, recovery_token, email_change, email_change_token_new,
        email_change_token_current, phone_change, phone_change_token, reauthentication_token
      ) values (
        '00000000-0000-0000-0000-000000000000', v_id, 'authenticated', 'authenticated', u.email,
        extensions.crypt(v_password, extensions.gen_salt('bf')), now(),
        jsonb_build_object('provider', 'email', 'providers', jsonb_build_array('email'), 'rms_activate', true),
        jsonb_build_object('full_name', u.full_name, 'employee_code', u.emp_code, 'email_verified', true),
        now(), now(),
        '', '', '', '', '', '', '', ''
      );
      insert into auth.identities (provider_id, user_id, identity_data, provider, last_sign_in_at, created_at, updated_at)
      values (
        v_id::text, v_id,
        jsonb_build_object('sub', v_id::text, 'email', u.email, 'email_verified', true, 'phone_verified', false),
        'email', now(), now(), now()
      );
      raise notice 'created  %  (%)', u.email, u.role_code;
    else
      update auth.users
         set encrypted_password = extensions.crypt(v_password, extensions.gen_salt('bf')),
             email_confirmed_at = coalesce(email_confirmed_at, now()),
             banned_until = null,
             updated_at = now()
       where id = v_id;
      raise notice 'existing %  (%): password reset, re-activated', u.email, u.role_code;
    end if;

    -- Profile: active, named, department, no forced password change (DEC-50 flag off for testing).
    update public.profiles p
       set full_name = u.full_name,
           employee_code = u.emp_code,
           department_id = (select d.id from public.departments d where d.code = u.dept_code),
           is_active = true,
           must_change_password = false,
           updated_at = now()
     where p.id = v_id;
    if not found then
      raise exception 'Profile for % was not created by the auth trigger; aborting', u.email;
    end if;

    insert into public.user_roles (user_id, role_id)
    select v_id, r.id from public.roles r where r.code = u.role_code
    on conflict (user_id, role_id) do nothing;
  end loop;
end
$$;

-- -----------------------------------------------------------------------------
-- Self-check: abort (roll back everything) unless the result is exactly as intended.
-- -----------------------------------------------------------------------------
do $$
begin
  if (select count(*) from public.goods_slips) <> 0
     or (select count(*) from public.gs_items) <> 0
     or (select count(*) from public.stock_movements) <> 0
     or (select count(*) from public.stock_balances) <> 0
     or (select count(*) from public.stock_lots) <> 0
     or (select count(*) from public.transfer_slips) <> 0
     or (select count(*) from public.gs_management_approvals) <> 0
     or (select count(*) from public.ac_gs_entries) <> 0
     or (select count(*) from public.credit_notes) <> 0 then
    raise exception 'Transactions were not fully removed; aborting';
  end if;
  if (select count(*) from public.products) = 0
     or (select count(*) from public.intermediate_stores) = 0 then
    raise exception 'Masters were removed; aborting';
  end if;
  if (select count(*)
        from public.profiles p
        join public.user_roles ur on ur.user_id = p.id
       where p.email like '%@rmstest.example.com' and p.is_active) <> 16 then
    raise exception 'Expected 16 active test users with a role; aborting';
  end if;
end $$;

commit;

-- -----------------------------------------------------------------------------
-- Result (read-only).
-- -----------------------------------------------------------------------------
select (select count(*) from public.goods_slips)    as goods_slips,
       (select count(*) from public.stock_balances) as stock_balances,
       (select count(*) from public.products)       as products,
       (select count(*) from public.profiles)       as users_total;

select p.email, p.full_name, p.employee_code, r.name as role, d.name as department, p.is_active
  from public.profiles p
  join public.user_roles ur on ur.user_id = p.id
  join public.roles r on r.id = ur.role_id
  left join public.departments d on d.id = p.department_id
 where p.email like '%@rmstest.example.com'
 order by p.employee_code;
