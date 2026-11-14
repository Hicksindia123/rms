-- Migration: 20261103000500_p2_06_container_audit.sql
-- Prompt: P2-06 Daily DMT Container Audit & Register (BR-18, DEC-08, DD r31)

-- 1. Extend container_audit_days with status, is_late, late_reason
alter table public.container_audit_days
  add column if not exists status text not null default 'PENDING' check (status in ('PENDING', 'CONFIRMED', 'LATE', 'MISSED')),
  add column if not exists is_late boolean not null default false,
  add column if not exists late_reason text;

create index if not exists container_audit_days_status_idx on public.container_audit_days (status);
create index if not exists container_audit_days_date_idx on public.container_audit_days (audit_date);

-- 2. Seed active DMT_RETURN storage containers if none exist
insert into public.storage_containers (code, barcode, name, container_type, location_id, is_active)
select c.code, c.barcode, c.name, 'DMT_RETURN', l.id, true
from (values
  ('DMT-BIN-01', 'DMT-BIN-01', 'DMT Return Bin 01'),
  ('DMT-BIN-02', 'DMT-BIN-02', 'DMT Return Bin 02'),
  ('DMT-BIN-03', 'DMT-BIN-03', 'DMT Return Bin 03'),
  ('DMT-BIN-04', 'DMT-BIN-04', 'DMT Return Bin 04')
) as c(code, barcode, name)
cross join (
  select id from public.inventory_locations where code = 'INWARD_STAGING' limit 1
) as l
on conflict (code) do nothing;

-- 3. Seed / update system settings for container audit
insert into public.system_settings (key, value, category, description, source_ref)
values
  ('daily_audit_blocks_inspection', 'false'::jsonb, 'provisional', 'DEC-08: If true, Step-3 inspection finalise for DMT items is blocked when today''s container audit is not confirmed', 'DEC-08'),
  ('container_audit_evening_alert_time', '"18:00"'::jsonb, 'provisional', 'Time (IST) for daily container audit reminder alert', 'BR-18'),
  ('container_audit_morning_missed_time', '"09:00"'::jsonb, 'provisional', 'Time (IST) next day when unconfirmed audit becomes MISSED', 'BR-18')
on conflict (key) do update set
  description = excluded.description;

-- 4. Permissions grant
grant select, insert, update, delete on
  public.storage_containers,
  public.container_partitions,
  public.container_audit_days,
  public.container_audit_lines
to rms_api;
