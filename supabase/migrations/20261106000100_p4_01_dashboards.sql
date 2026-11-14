-- Migration: 20261106000100_p4_01_dashboards.sql
-- Prompt: P4-01 Admin & role-specific dashboards (master plan §10 "Dashboard widgets", §11).
--
-- 1. dashboard_widgets         — widget catalogue: code, title (admin-relabelable, rule e), default size.
--                                Query functions and permission requirements live in the backend
--                                widget registry (app/modules/dashboards/registry.py), never in config,
--                                so an option edit can never widen data access.
-- 2. role_dashboard_layouts    — per-role ordered widget list with sizes (admin CRUD, config_change_log).
--                                Default layouts are seeded in seed.sql (roles are seeded there).
-- 3. system_guard_events       — append-only record of every rejected G-01…G-18 attempt (service and
--                                DB-trigger paths), feeding the Admin "guard violations attempted" widget.
-- 4. job_runs                  — append-only record of background worker job runs (failed-jobs widget).
-- 5. rms_private.auth_login_stats(since) — login counts from Supabase Auth's audit log, exposed to
--                                rms_api through a locked SECURITY DEFINER function (no auth grants).
--
-- Realtime: workflow_tasks is deliberately NOT exposed to `authenticated` (P1-02 baseline: authenticated
-- may SELECT only its own notifications; supabase/tests/02_rls). Live task counts use the existing
-- own-row notifications subscription plus 60 s polling (docs/DECISIONS.md, P4-01).

-- ===========================================================================
-- 1. dashboard_widgets
-- ===========================================================================
create table public.dashboard_widgets (
  code          text primary key check (code ~ '^[A-Z][A-Z0-9_]{1,59}$'),
  title         text not null check (btrim(title) <> ''),
  description   text,
  default_size  text not null default 'M' check (default_size in ('S', 'M', 'L')),
  is_active     boolean not null default true,
  created_at    timestamptz not null default now(),
  created_by    uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at    timestamptz not null default now()
);
comment on table public.dashboard_widgets is
  'P4-01 widget catalogue (§10). Codes are immutable and must match the backend widget registry.';

insert into public.dashboard_widgets (code, title, description, default_size) values
  ('MY_TASKS',              'My tasks',                         'Open workflow tasks for your roles, by step, with the overdue count.', 'M'),
  ('GS_PIPELINE',           'GS pipeline by status',            'Open goods slips per status with the average age in days.', 'L'),
  ('GATE_INWARDS_TODAY',    'Today''s gate inwards',            'Goods slips created at the gate today and their box count.', 'S'),
  ('EVIDENCE_PENDING',      'Evidence pending (Step-2)',        'Goods slips waiting for unboxing evidence.', 'S'),
  ('CSR_APPROVALS_PENDING', 'CSR approvals pending',            'Goods slips waiting for the Replacement Manager''s CSR decision.', 'S'),
  ('INSPECTIONS_PENDING',   'Inspections pending',              'Goods slips in product inspection.', 'S'),
  ('CONTAINER_AUDIT',       'Daily container audit',            'Today''s DMT container audit status and the 30-day compliance.', 'M'),
  ('OPEN_PENDENCIES',       'Open pendencies',                  'Open Pending (BP) records, quantity and the oldest one.', 'S'),
  ('TRANSFERS_ATTENTION',   'Transfers needing attention',      'Custody transfers awaiting acceptance or in discrepancy.', 'M'),
  ('TECHNICIAN_WIP',        'Technician WIP',                   'Open technician batches, pieces still with technicians and their age.', 'M'),
  ('BATTERY_STOCK',         'Battery stock & consumption',      'Battery store balance and batteries installed in the last 7 / 30 days.', 'M'),
  ('DISMANTLING',           'Dismantling queue & recovery',     'Lots waiting for dismantling and parts recovered in the last 30 days by type.', 'M'),
  ('FUNCTIONAL_STOCK',      'Functional stock',                 'Functional finished-goods stock: good vs repaired.', 'M'),
  ('NON_FUNCTIONAL_STOCK',  'Non-functional & spare parts',     'Non-functional custody stock and the salvaged spare-parts ledger.', 'M'),
  ('HAZARD_QUARANTINE',     'Hazard quarantine',                'Stock held in hazard quarantine.', 'S'),
  ('CN_PIPELINE',           'Credit note pipeline',             'Goods slips awaiting credit and credit notes by stage.', 'M'),
  ('CN_ISSUED',             'Credit notes issued',              'Issued credit note value by type and month.', 'L'),
  ('GS_TREND',              'GS opened vs closed',              'Goods slips opened and closed per week.', 'L'),
  ('ACCOUNTS_DOC_QUEUE',    'Accounts document queue',          'Goods slips with Step-2 documents not yet acknowledged by Accounts.', 'S'),
  ('ADMIN_HEALTH',          'System health',                    'Active users, logins, configuration changes, guard violations attempted and failed jobs (7 days).', 'L')
on conflict (code) do nothing;

-- ===========================================================================
-- 2. role_dashboard_layouts
-- ===========================================================================
create table public.role_dashboard_layouts (
  role_id     uuid primary key references public.roles (id) on delete cascade,
  -- Ordered: [{"code": "MY_TASKS", "size": "M"}, ...]
  widgets     jsonb not null default '[]'::jsonb check (jsonb_typeof(widgets) = 'array'),
  created_at  timestamptz not null default now(),
  created_by  uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at  timestamptz not null default now(),
  updated_by  uuid default rms_private.current_actor() references public.profiles (id) on delete restrict
);
comment on table public.role_dashboard_layouts is
  'P4-01 per-role landing dashboard: ordered widget codes with size S/M/L (admin-editable, §10).';

-- Every entry names a catalogue widget once, with a valid size. Enforced here so no path
-- (API, SQL console, seed) can store a layout the API cannot render.
create or replace function rms_private.role_dashboard_layouts_validate()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_bad text;
begin
  select string_agg(coalesce(e->>'code', '<missing>'), ', ')
    into v_bad
    from jsonb_array_elements(new.widgets) as e
   where jsonb_typeof(e) <> 'object'
      or not exists (select 1 from public.dashboard_widgets w where w.code = e->>'code')
      or coalesce(e->>'size', '') not in ('S', 'M', 'L');
  if v_bad is not null then
    raise exception 'dashboard layout has unknown widgets or invalid sizes: %', v_bad
      using errcode = '23514';
  end if;
  if (select count(*) from jsonb_array_elements(new.widgets))
     <> (select count(distinct e->>'code') from jsonb_array_elements(new.widgets) as e) then
    raise exception 'dashboard layout lists a widget more than once' using errcode = '23514';
  end if;
  new.updated_by := rms_private.current_actor();
  return new;
end;
$$;
revoke all on function rms_private.role_dashboard_layouts_validate() from public, anon, authenticated;

create trigger role_dashboard_layouts_validate
  before insert or update on public.role_dashboard_layouts
  for each row execute function rms_private.role_dashboard_layouts_validate();

-- ===========================================================================
-- 3. system_guard_events (append-only)
-- ===========================================================================
create table public.system_guard_events (
  id           bigint generated always as identity primary key,
  guard_code   text not null check (guard_code ~ '^G-(0[1-9]|1[0-8])$'),
  source       text not null check (source in ('SERVICE', 'DB')),
  http_method  text,
  path         text,
  user_id      uuid,
  request_id   text,
  occurred_at  timestamptz not null default now()
);
comment on table public.system_guard_events is
  'P4-01: every rejected attempt at an action a system guard G-01…G-18 forbids (append-only).';
create index system_guard_events_at_idx on public.system_guard_events (occurred_at desc);

-- ===========================================================================
-- 4. job_runs (append-only)
-- ===========================================================================
create table public.job_runs (
  id             bigint generated always as identity primary key,
  job_code       text not null check (btrim(job_code) <> ''),
  status         text not null check (status in ('SUCCEEDED', 'FAILED')),
  started_at     timestamptz not null,
  finished_at    timestamptz not null default now(),
  result_count   integer,
  error_message  text,
  check (status = 'SUCCEEDED' or error_message is not null)
);
comment on table public.job_runs is 'P4-01: one row per background worker job run (app/worker.py).';
create index job_runs_finished_idx on public.job_runs (finished_at desc);

-- ===========================================================================
-- 5. Login statistics from Supabase Auth (read-only, locked)
-- ===========================================================================
create or replace function rms_private.auth_login_stats(p_since timestamptz)
returns table (logins bigint, distinct_users bigint)
language sql
stable
security definer
set search_path = ''
as $$
  select count(*)::bigint,
         count(distinct (e.payload->>'actor_id'))::bigint
    from auth.audit_log_entries e
   where e.payload->>'action' = 'login'
     and e.created_at >= p_since;
$$;
revoke all on function rms_private.auth_login_stats(timestamptz) from public, anon, authenticated;
grant execute on function rms_private.auth_login_stats(timestamptz) to rms_api;

-- ===========================================================================
-- 6. Audit, RLS, grants
-- ===========================================================================
select rms_private.attach_standard_triggers('public.dashboard_widgets');
select rms_private.attach_standard_triggers('public.role_dashboard_layouts');
-- The two logs are themselves the record; they are not row-audited (like audit_log).

alter table public.dashboard_widgets enable row level security;
alter table public.role_dashboard_layouts enable row level security;
alter table public.system_guard_events enable row level security;
alter table public.job_runs enable row level security;

revoke all on public.dashboard_widgets from anon, authenticated;
revoke all on public.role_dashboard_layouts from anon, authenticated;
revoke all on public.system_guard_events from anon, authenticated;
revoke all on public.job_runs from anon, authenticated;

-- Widget codes are fixed by the registry: rms_api may relabel, never add or delete.
revoke insert, delete on public.dashboard_widgets from rms_api;
grant select, update on public.dashboard_widgets to rms_api;
grant select, insert, update, delete on public.role_dashboard_layouts to rms_api;
-- Logs are append-only.
revoke update, delete, truncate on public.system_guard_events from rms_api;
revoke update, delete, truncate on public.job_runs from rms_api;
grant select, insert on public.system_guard_events to rms_api;
grant select, insert on public.job_runs to rms_api;

grant all on public.dashboard_widgets to service_role;
grant all on public.role_dashboard_layouts to service_role;
grant select, insert on public.system_guard_events to service_role;
grant select, insert on public.job_runs to service_role;
