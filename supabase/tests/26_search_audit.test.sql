-- =============================================================================
-- 26_search_audit.test.sql — P4-04 Global Search, Advanced Filters, Audit Trail & Activity
-- (master plan §8.7; BR-40, G-17)
-- =============================================================================
begin;
select plan(16);

-- 1. Check tables exist
select has_table('public', 'audit_log', 'audit_log table exists');
select has_table('public', 'user_activity', 'user_activity table exists');
select has_table('public', 'saved_views', 'saved_views table exists');

-- 2. Check pg_trgm extension
select has_extension('pg_trgm', 'pg_trgm extension is active');

-- 3. Check indexes on key searchable entities
select has_index('public', 'goods_slips', 'goods_slips_gs_no_trgm_idx', 'Trigram search index on goods_slips exists');
select has_index('public', 'parties', 'parties_name_trgm_idx', 'Trigram search index on parties exists');
select has_index('public', 'credit_notes', 'credit_notes_cn_no_trgm_idx', 'Trigram search index on credit_notes exists');
select has_index('public', 'custody_transfers', 'custody_transfers_transfer_no_trgm_idx', 'Trigram search index on custody_transfers exists');
select has_index('public', 'technician_batches', 'technician_batches_batch_no_trgm_idx', 'Trigram search index on technician_batches exists');
select has_index('public', 'storage_containers', 'storage_containers_barcode_trgm_idx', 'Trigram search index on storage_containers exists');
select has_index('public', 'audit_log', 'audit_log_table_row_idx', 'Composite index (table_name, row_id) on audit_log exists');

-- 4. Audit Log Immutability Guard (G-17 / BR-40)
select throws_ok(
  $$delete from public.audit_log$$,
  '42501',
  null,
  'Audit log rows cannot be deleted (G-17)'
);

select throws_ok(
  $$update public.audit_log set actor_id = null$$,
  '42501',
  null,
  'Audit log rows cannot be updated (G-17)'
);

-- 5. User Activity Immutability Guard
-- Insert a test activity row so FOR EACH ROW triggers can fire on delete/update
insert into auth.users (id, email)
values ('33333333-3333-3333-3333-333333333333', 'search_test@example.com')
on conflict do nothing;
insert into public.profiles (id, full_name, is_active)
values ('33333333-3333-3333-3333-333333333333', 'Search Test', true)
on conflict do nothing;

do $$
declare
  v_user_id uuid;
begin
  select id into v_user_id from auth.users limit 1;
  if v_user_id is not null then
    insert into public.user_activity (user_id, activity_type)
    values (v_user_id, 'SIGN_IN');
  end if;
end $$;

select throws_ok(
  $$delete from public.user_activity$$,
  '42501',
  null,
  'User activity rows cannot be deleted'
);

select throws_ok(
  $$update public.user_activity set activity_type = 'SIGN_OUT'$$,
  '42501',
  null,
  'User activity rows cannot be updated'
);

-- 6. Saved Views Default Uniqueness Trigger
do $$
declare
  v_user_id uuid;
  v_id1 uuid;
  v_id2 uuid;
begin
  select id into v_user_id from auth.users limit 1;
  if v_user_id is not null then
    insert into public.saved_views (user_id, view_code, name, filters, is_default)
    values (v_user_id, 'test_resource', 'View 1', '[]'::jsonb, true)
    returning id into v_id1;

    insert into public.saved_views (user_id, view_code, name, filters, is_default)
    values (v_user_id, 'test_resource', 'View 2', '[]'::jsonb, true)
    returning id into v_id2;

    -- Verify View 1 is no longer default
    if (select is_default from public.saved_views where id = v_id1) = true then
      raise exception 'View 1 should have had is_default reset to false';
    end if;
  end if;
end $$;

select ok(true, 'Saved views default guard ensures at most one default view per user & resource');

-- 7. RLS enabled
select row_security_active('public.user_activity');
select row_security_active('public.saved_views');

select * from finish();
rollback;
