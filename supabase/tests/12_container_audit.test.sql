-- pgTAP test suite: 12_container_audit.test.sql
-- Verifies container_audit_days extensions, active DMT containers, and system settings for P2-06

begin;
select plan(12);

-- 1. Table public.container_audit_days exists
select has_table('public', 'container_audit_days', 'container_audit_days table exists');

-- 2. Columns exist on container_audit_days
select has_column('public', 'container_audit_days', 'status', 'container_audit_days has status column');
select has_column('public', 'container_audit_days', 'is_late', 'container_audit_days has is_late column');
select has_column('public', 'container_audit_days', 'late_reason', 'container_audit_days has late_reason column');

-- 3. Check constraint on status
select col_type_is('public', 'container_audit_days', 'status', 'text', 'status is text');
select col_default_is('public', 'container_audit_days', 'status', 'PENDING', 'status defaults to PENDING');

-- 4. Check status check constraint rejects invalid status
prepare insert_bad_status as
  insert into public.container_audit_days (audit_date, status)
  values ('2099-01-01', 'INVALID_STATUS');
select throws_ok('insert_bad_status', '23514', null, 'status check rejects invalid values');

-- 5. Active DMT storage containers seeded
select ok(
  (select count(*) >= 4 from public.storage_containers where container_type = 'DMT_RETURN' and is_active = true),
  'At least 4 active DMT_RETURN storage containers seeded'
);

-- 6. container_audit_lines table exists and has expected foreign keys
select has_table('public', 'container_audit_lines', 'container_audit_lines table exists');
select has_column('public', 'container_audit_lines', 'counted_qty', 'container_audit_lines has counted_qty');
select has_column('public', 'container_audit_lines', 'sellable_packaging_qty', 'container_audit_lines has sellable_packaging_qty');

-- 7. System settings seeded
select ok(
  (select count(*) = 3 from public.system_settings where key in ('daily_audit_blocks_inspection', 'container_audit_evening_alert_time', 'container_audit_morning_missed_time')),
  'Container audit system settings seeded'
);

select * from finish();
rollback;
