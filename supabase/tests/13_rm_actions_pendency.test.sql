-- =============================================================================
-- pgTAP Test: 13_rm_actions_pendency.test.sql
-- Prompt: P2-07 — Step-3 a) RM item-wise actions, Pending (BP) register & printable Replacement Slip
-- =============================================================================

begin;
select plan(12);

-- 1. Table public.print_logs exists
select has_table('public', 'print_logs', 'public.print_logs table exists');

-- 2. Columns on public.print_logs
select columns_are(
  'public',
  'print_logs',
  array['id', 'template_code', 'entity_type', 'entity_id', 'revision_no', 'printed_by', 'printed_at', 'metadata'],
  'public.print_logs has expected columns'
);

-- 3. Privileges for rms_api on public.print_logs
select table_privs_are(
  'public',
  'print_logs',
  'rms_api',
  array['DELETE', 'INSERT', 'SELECT', 'UPDATE'],
  'rms_api has expected privileges on print_logs'
);

-- 4. Check resolution_action on public.pendencies
select has_column('public', 'pendencies', 'resolution_action', 'public.pendencies has resolution_action column');
select has_column('public', 'pendencies', 'lot_id', 'public.pendencies has lot_id column');
select has_column('public', 'pendencies', 'stock_movement_id', 'public.pendencies has stock_movement_id column');

-- 5. Check index rm_item_actions_current_uq (gap plan G4 / DEC-57: per item, round, condition and
--    action; the columns include an expression, so only the index itself is checked here, and
--    44_g4_final_actions_per_condition covers the behaviour).
select has_index('public', 'rm_item_actions', 'rm_item_actions_current_uq', 'rm_item_actions has partial unique index on current actions');

-- 6. Check audit_log action check includes 'PRINT'
select lives_ok(
  $$
    insert into public.audit_log (table_name, row_id, action, new, actor_id)
    values ('goods_slips', '00000000-0000-0000-0000-000000000001', 'PRINT', '{"template": "REPLACEMENT_SLIP"}'::jsonb, '00000000-0000-0000-0000-000000000002')
  $$,
  'audit_log accepts action PRINT'
);

-- 7. System setting pending_blocks_entire_gs exists
select results_eq(
  $$
    select value from public.system_settings where key = 'pending_blocks_entire_gs'
  $$,
  $$
    values ('false'::jsonb)
  $$,
  'pending_blocks_entire_gs setting is false by default'
);

-- 8. Storage location PENDING_HOLD exists
select results_eq(
  $$
    select location_class from public.inventory_locations where code = 'PENDING_HOLD'
  $$,
  $$
    values ('PENDING_HOLD'::text)
  $$,
  'PENDING_HOLD inventory location exists with location_class PENDING_HOLD'
);

-- 9. RM_ITEM_ACTION option items exist
select results_eq(
  $$
    select count(*)::integer from public.option_items oi
    join public.option_sets os on os.id = oi.option_set_id
    where os.code = 'RM_ITEM_ACTION'
  $$,
  $$
    values (5::integer)
  $$,
  'RM_ITEM_ACTION option set has exactly 5 options'
);

-- 10. REPLACEMENT_SLIP template exists
select results_eq(
  $$
    select status from public.print_templates where code = 'REPLACEMENT_SLIP' and status = 'PUBLISHED'
  $$,
  $$
    values ('PUBLISHED'::text)
  $$,
  'REPLACEMENT_SLIP print template is published'
);

select * from finish();
rollback;
