-- P1-02 pgTAP: foundation schema exists exactly as specified (master plan §8.1–§8.3, §8.7).
begin;
create extension if not exists pgtap with schema extensions;
select plan(14);

-- Exactly the foundation tables: operational tables (GS, inventory) arrive in Phase 2/3.
select tables_are('public', array[
  -- §8.1 identity & access
  'departments','profiles','roles','user_roles','permissions','role_permissions',
  'user_permission_overrides',
  -- §8.2 masters
  'product_categories','products','states','stations','parties','transporters','technicians',
  'inventory_locations','storage_containers','container_partitions','rejection_reasons',
  'battery_types','pcb_suppliers','pcb_models',
  -- §8.3 configuration
  'option_sets','option_items','form_definitions','form_versions','form_fields','form_responses',
  'workflow_definitions','workflow_versions','workflow_stages','workflow_steps',
  'workflow_transitions','step_assignments','escalation_rules','number_series',
  'number_series_counters','system_settings','print_templates','report_column_prefs',
  'config_change_log',
  -- §8.7 cross-cutting
  'notifications','notification_preferences','audit_log',
  -- §8.4 inward & inspection (P2-01)
  'goods_slips','gs_status_history','attachments','gs_documents','gs_items',
  'csr_approvals','inspections','inspection_allocations','extraction_records',
  'container_audit_days','container_audit_lines','rejections','rm_item_actions',
  'pendencies','workflow_tasks',
  -- Step-2 (P2-03)
  'missing_doc_exceptions',
  -- Step-3 line corrections (P2-04)
  'gs_item_corrections',
  -- §8.5 inventory ledger (P2-01)
  'stock_items','stock_lots','stock_movements','stock_balances',
  'custody_transfers','custody_transfer_lines','packaging_replacements',
  -- Step-3 a) print logs (P2-07)
  'print_logs',
  -- custody engine reconciliations (P3-01)
  'custody_reconciliations',
  -- servicing & battery ledger (P3-02)
  'battery_receipts','battery_adjustments','technician_batches','technician_batch_lines',
  'technician_receiving_records',
  -- dismantling (P3-03)
  'dismantle_batches','dismantle_inputs','recovered_parts','scrap_records',
  -- custody segregation & stock adjustments (P3-04)
  'custody_assignments','stock_adjustments','segregation_check_runs',
  -- store issues & replacement dispatches (P3-05)
  'store_issues','store_issue_lines','replacement_dispatches','replacement_dispatch_lines',
  -- credit notes & commercial resolution (P3-06)
  'rm_cn_decisions','rm_cn_decision_lines','credit_notes','credit_note_lines','rate_verifications',
  'party_notifications','gs_closures',
  -- dashboards, guard events and job runs (P4-01)
  'dashboard_widgets','role_dashboard_layouts','system_guard_events','job_runs',
  -- reports catalogue and saved filters (P4-02)
  'report_definitions','report_saved_filters',
  -- notifications and escalations (P4-03)
  'notification_deliveries','notification_event_types','notification_events','notification_rules',
  'notification_templates','notification_user_settings','workflow_task_escalations',
  -- search and audit (P4-04)
  'saved_views','user_activity',
  -- product sub-categories (change plan 2026-11-12 Phase 1, AMD-07)
  'product_subcategories',
  -- gate document rows (change plan 2026-11-12 Phase 2, AMD-04)
  'gs_gate_documents',
  -- item field profiles and item counts (change plan 2026-11-12 Phase 4, AMD-10/11)
  'item_field_library','item_field_assignments','item_field_profile_versions','gs_item_counts',
  -- categorisation buckets and RM review revisions (change plan 2026-11-12 Phase 5, AMD-09/12)
  'gs_item_buckets','rm_review_revisions',
  -- department routing, receiving and outcome heads (change plan 2026-11-12 Phase 6, AMD-14)
  'department_outcome_heads','department_routings','department_routing_lines',
  'department_receipts','department_receipt_lines',
  -- Change plan Phase 7 (AMD-17)
  'ac_action_slips',
  -- Change plan Phase 8 (AMD-18, AMD-19)
  'ac_entry_lines','ac_entry_completions','dispatch_slips','dispatch_slip_lines',
  -- Change plan Phase 9 (AMD-20)
  'party_emails',
  -- change plan Phase 10 (AMD-22)
  'journey_steps', 'role_journey_steps',
  -- gap plan G2 (DEC-55): RM routing plan
  'department_routing_plan_lines',
  -- Phase P1 20-11-2026 (DEC-61): Intermediate Stores + category mapping
  'intermediate_stores','intermediate_store_category_map',
  -- DEC-65 (P5): transfer slips + edit requests
  'transfer_slips','transfer_slip_gs','transfer_slip_lines','gs_edit_requests','transfer_slip_discrepancies',
  -- gap plan G3 (DEC-56): current condition per item
  'gs_item_conditions'
],'public schema holds foundation, inward and inventory ledger tables');

select has_schema('rms_private');
select tables_are('rms_private', array['idempotency_keys'], 'rms_private holds idempotency_keys');

select has_extension('extensions', 'pgcrypto', 'pgcrypto installed');
select has_extension('extensions', 'citext',   'citext installed');
select has_extension('extensions', 'pg_trgm',  'pg_trgm installed');

select has_function('rms_private', 'next_number', array['text','date'], 'next_number(text, date) exists');
select has_function('rms_private', 'audit_row', 'audit_row() exists');
select has_function('rms_private', 'set_updated_at', 'set_updated_at() exists');

select has_role('rms_api');
select ok((select rolcanlogin and rolbypassrls from pg_roles where rolname = 'rms_api'),
          'rms_api can log in and bypasses RLS');
select ok(not (select rolsuper from pg_roles where rolname = 'rms_api'), 'rms_api is not a superuser');

select is(
  (select array_agg(p.proname::text order by p.proname)
     from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'rms_private'
      and (has_function_privilege('anon', p.oid, 'EXECUTE')
           or has_function_privilege('authenticated', p.oid, 'EXECUTE'))),
  null,
  'no rms_private function is executable by anon/authenticated');

select is(
  (select array_agg(t.tgname::text order by t.tgname)
     from pg_trigger t
    where t.tgrelid = 'auth.users'::regclass and not t.tgisinternal
      and t.tgname in ('on_auth_user_created','on_auth_user_email_changed')),
  array['on_auth_user_created','on_auth_user_email_changed'],
  'auth.users triggers create/sync profiles');

select * from finish();
rollback;
