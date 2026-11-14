-- Change plan 2026-11-12, Phase 10: role journeys and UI clean-up (AMD-22, DEC-49; AMD-21 / DEC-44).
--
-- 1. journey_steps: the catalogue of menu entries. A STEP is a stage of the GS journey with a work
--    queue (counted by the API from `queue_code`); a TOOL is a supporting screen (registers, reports,
--    inventory, ...). Labels, hints and order are configuration (rule e); `screen_key` /
--    `item_screen_key` name a screen the frontend knows (closed list, so configuration can never
--    produce a dead link, rule j); `queue_code` names a counter the API implements (closed list).
-- 2. role_journey_steps: role <-> step, ordered as that role's working journey. Seeded per role in
--    seed.sql (roles are seed data); admins edit it in Admin -> Role Journeys.
-- 3. Setting `features.on_hold` (AMD-21, DEC-44 PROVISIONAL): menu entries whose `feature_code` is
--    listed are hidden. Hiding is navigation only: no code, data or guard is touched.
--
-- No new system guard: the menu is a convenience; every endpoint keeps its own permission check
-- and the API also filters each entry by `perm_module` / `perm_action`.

create table public.journey_steps (
  id               uuid primary key default gen_random_uuid(),
  code             text not null unique check (code ~ '^[A-Z][A-Z0-9_]*$'),
  label            text not null check (btrim(label) <> ''),
  hint             text,
  kind             text not null check (kind in ('STEP', 'TOOL')),
  -- Where the menu entry goes. 'journey-queue' = the step's GS list inside My Work.
  screen_key       text not null check (screen_key in (
                     'journey-queue', 'gs-new', 'gs-list', 'dashboard', 'pendencies',
                     'container-audit', 'reports', 'audit', 'custody', 'inventory', 'store-issues',
                     'servicing', 'batteries', 'dismantling', 'scrap', 'credit-notes', 'approvals',
                     'dispatch-queue', 'department-routing', 'department-receiving',
                     'accounts-entry', 'accounts-docs', 'dispatch-slips')),
  -- Where one GS of the queue opens ("next GS to act on").
  item_screen_key  text check (item_screen_key is null or item_screen_key in (
                     'gs-detail', 'gs-unboxing', 'gs-itemization', 'gs-rm-review',
                     'custody-transfer', 'gs-final-actions', 'department-receiving',
                     'accounts-entry-gs', 'accounts-docs', 'dispatch-slips',
                     'gs-party-notification')),
  queue_code       text unique check (queue_code is null or queue_code in (
                     'CARTON_OPENING', 'COUNTING', 'CATEGORISATION', 'RM_REVIEW', 'STORE_ACCEPT',
                     'DEPT_ROUTING', 'DEPT_RECEIVING', 'FINAL_ACTIONS', 'ACCOUNTS_DOCS',
                     'ACCOUNTS_ENTRY', 'DISPATCH_SLIP', 'PARTY_EMAIL')),
  -- Feature module for the hold (AMD-21): lower-case codes as listed in features.on_hold.
  feature_code     text check (feature_code is null or feature_code ~ '^[a-z][a-z0-9_]*$'),
  -- The permission the entry needs (the API filters by it; endpoints enforce it anyway).
  perm_module      text not null check (btrim(perm_module) <> ''),
  perm_action      text not null default 'view' check (btrim(perm_action) <> ''),
  sort_order       integer not null default 0,
  is_active        boolean not null default true,
  source_ref       text,
  created_at       timestamptz not null default now(),
  created_by       uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at       timestamptz not null default now(),
  -- A STEP has a queue and a per-GS screen; a TOOL has neither.
  constraint journey_steps_kind_shape check (
    (kind = 'STEP' and item_screen_key is not null)
    or (kind = 'TOOL' and queue_code is null and item_screen_key is null)),
  constraint journey_steps_queue_screen check (screen_key <> 'journey-queue' or queue_code is not null)
);
comment on table public.journey_steps is
  'Change plan Phase 10 (AMD-22): role journey menu catalogue. Labels/order are config; screen and queue codes are closed lists.';

create table public.role_journey_steps (
  id               uuid primary key default gen_random_uuid(),
  role_id          uuid not null references public.roles (id) on delete cascade,
  journey_step_id  uuid not null references public.journey_steps (id) on delete restrict,
  sort_order       integer not null default 0,
  created_at       timestamptz not null default now(),
  created_by       uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at       timestamptz not null default now(),
  unique (role_id, journey_step_id)
);
create index role_journey_steps_step_idx on public.role_journey_steps (journey_step_id);
comment on table public.role_journey_steps is
  'Change plan Phase 10 (AMD-22): which journey steps / tools a role sees, in its working order.';

-- RLS, grants, standard triggers (config goes through the API: rms_api only).
alter table public.journey_steps enable row level security;
alter table public.role_journey_steps enable row level security;
revoke all on public.journey_steps, public.role_journey_steps from anon, authenticated;
-- Catalogue entries are deactivated, never deleted (codes are stable, rule e).
revoke delete, truncate on public.journey_steps from rms_api;
grant select, insert, update on public.journey_steps to rms_api;
grant select, insert, update, delete on public.role_journey_steps to rms_api;
select rms_private.attach_standard_triggers('public.journey_steps');
select rms_private.attach_standard_triggers('public.role_journey_steps');

-- Codes are immutable once created (rule e): logic and role assignments key off them.
create or replace function rms_private.journey_steps_code_immutable()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.code is distinct from old.code or new.queue_code is distinct from old.queue_code then
    raise exception 'journey step code / queue code is immutable (%)', old.code
      using errcode = 'P0001';
  end if;
  return new;
end
$$;
create trigger journey_steps_code_immutable
  before update on public.journey_steps
  for each row execute function rms_private.journey_steps_code_immutable();

-- ---------------------------------------------------------------------------------------------
-- Catalogue (sort_order follows the target workflow of the change plan §1; idempotent)
-- ---------------------------------------------------------------------------------------------
insert into public.journey_steps
  (code, label, hint, kind, screen_key, item_screen_key, queue_code, feature_code,
   perm_module, perm_action, sort_order, source_ref)
values
  ('GATE_ENTRY',     'Gate Entry',            'Record a new delivery at the gate',                                'STEP', 'gs-new',               'gs-detail',             null,             null, 'goods_slips',        'create',  10, 'AMD-01'),
  ('CARTON_OPENING', 'Carton Opening',        'Open each carton on video and add its documents',                  'STEP', 'journey-queue',        'gs-unboxing',           'CARTON_OPENING', null, 'unboxing',           'edit',    20, 'AMD-04'),
  ('COUNTING',       'Counting',              'Add the items and quantities found',                               'STEP', 'journey-queue',        'gs-itemization',        'COUNTING',       null, 'itemization',        'edit',    30, 'AMD-08'),
  ('CATEGORISATION', 'Categorisation',        'Split each item''s quantity into its buckets',                     'STEP', 'journey-queue',        'gs-itemization',        'CATEGORISATION', null, 'itemization',        'edit',    40, 'AMD-09'),
  ('RM_REVIEW',      'RM Review',             'Review the whole goods slip and approve',                          'STEP', 'journey-queue',        'gs-rm-review',          'RM_REVIEW',      null, 'goods_slips',        'approve', 50, 'AMD-12'),
  ('STORE_ACCEPT',   'Store Acceptance',      'Accept the transfer slip into the intermediate store',             'STEP', 'journey-queue',        'custody-transfer',      'STORE_ACCEPT',   null, 'custody',            'approve', 60, 'AMD-13'),
  ('DEPT_ROUTING',   'Department Routing',    'Held in store: send quantities to departments',                    'STEP', 'department-routing',   'gs-detail',             'DEPT_ROUTING',   null, 'department_routing', 'create',  70, 'AMD-14'),
  ('DEPT_RECEIVING', 'Department Receiving',  'Receive goods back from departments per outcome',                  'STEP', 'department-receiving', 'department-receiving',  'DEPT_RECEIVING', null, 'department_routing', 'edit',    80, 'AMD-15'),
  ('FINAL_ACTIONS',  'Final Actions',         'Back from departments: split quantities across the final actions', 'STEP', 'journey-queue',        'gs-final-actions',      'FINAL_ACTIONS',  null, 'final_actions',      'edit',    90, 'AMD-16'),
  ('ACCOUNTS_DOCS',  'Gate Documents Check',  'Invoices / debit notes received: GST input check',                  'STEP', 'accounts-docs',        'accounts-docs',         'ACCOUNTS_DOCS',  null, 'credit_notes',       'view',   100, 'AMD-05'),
  ('ACCOUNTS_ENTRY', 'Accounts Entry',        'Enter CN and challan details per action line',                     'STEP', 'accounts-entry',       'accounts-entry-gs',     'ACCOUNTS_ENTRY', null, 'ac_entry',           'edit',   110, 'AMD-18'),
  ('DISPATCH_SLIP',  'Dispatch',              'Issue the goods on the Dispatch Slip',                             'STEP', 'dispatch-slips',       'dispatch-slips',        'DISPATCH_SLIP',  null, 'dispatch',           'edit',   120, 'AMD-19'),
  ('PARTY_EMAIL',    'Party Email',           'Send the party the CN / challan / dispatch details',               'STEP', 'journey-queue',        'gs-party-notification', 'PARTY_EMAIL',    null, 'credit_notes',       'view',   130, 'AMD-20'),
  ('GS_LIST',        'Goods Slips',           'Find any goods slip',                                              'TOOL', 'gs-list',              null,                    null,             null,          'goods_slips',     'view',   200, 'AMD-22'),
  ('DASHBOARD',      'Dashboard',             null,                                                               'TOOL', 'dashboard',            null,                    null,             null,          'dashboards',      'view',   210, 'AMD-22'),
  ('PENDENCIES',     'Pendency Register',     null,                                                               'TOOL', 'pendencies',           null,                    null,             null,          'goods_slips',     'view',   220, 'AMD-22'),
  ('CONTAINER_AUDIT','Container Register',    null,                                                               'TOOL', 'container-audit',      null,                    null,             null,          'container_audit', 'view',   230, 'AMD-22'),
  ('APPROVALS',      'Approvals',             null,                                                               'TOOL', 'approvals',            null,                    null,             null,          'itemization',     'approve',240, 'AMD-22'),
  ('CUSTODY',        'Custody & Store',       null,                                                               'TOOL', 'custody',              null,                    null,             null,          'custody',         'view',   250, 'AMD-22'),
  ('INVENTORY',      'Inventory',             null,                                                               'TOOL', 'inventory',            null,                    null,             null,          'inventory',       'view',   260, 'AMD-22'),
  ('STORE_ISSUES',   'Store Issues',          null,                                                               'TOOL', 'store-issues',         null,                    null,             null,          'inventory',       'view',   270, 'AMD-22'),
  ('SERVICING',      'Servicing',             null,                                                               'TOOL', 'servicing',            null,                    null,             null,          'servicing',       'view',   280, 'AMD-22'),
  ('BATTERIES',      'Batteries',             null,                                                               'TOOL', 'batteries',            null,                    null,             'battery',     'inventory',       'view',   290, 'AMD-21'),
  ('DISMANTLING',    'Dismantling',           null,                                                               'TOOL', 'dismantling',          null,                    null,             'dismantling', 'dismantling',     'view',   300, 'AMD-21'),
  ('SCRAP',          'Scrap Register',        null,                                                               'TOOL', 'scrap',                null,                    null,             'dismantling', 'dismantling',     'view',   310, 'AMD-21'),
  ('CREDIT_NOTES',   'Credit Notes',          'Earlier credit-note flow (P3-06)',                                 'TOOL', 'credit-notes',         null,                    null,             null,          'credit_notes',    'view',   320, 'AMD-22'),
  ('DISPATCH_QUEUE', 'Dispatch Queue',        'Earlier dispatch flow (P3-05)',                                    'TOOL', 'dispatch-queue',       null,                    null,             null,          'dispatch',        'view',   330, 'AMD-22'),
  ('REPORTS',        'Reports',               null,                                                               'TOOL', 'reports',              null,                    null,             null,          'reports',         'view',   340, 'AMD-22'),
  ('AUDIT',          'Audit Explorer',        null,                                                               'TOOL', 'audit',                null,                    null,             null,          'audit',           'view',   350, 'AMD-22')
on conflict (code) do nothing;

-- ---------------------------------------------------------------------------------------------
-- AMD-21 / DEC-44 (PROVISIONAL): modules on hold, hidden from navigation.
-- ---------------------------------------------------------------------------------------------
insert into public.system_settings (key, value, category, description, source_ref) values
  ('features.on_hold',
   '["dismantling", "spare_parts", "battery", "pcb_subinventory"]'::jsonb,
   'features',
   'AMD-21 / DEC-44: feature modules on hold. Menu entries whose feature code is listed are hidden (Dismantling, Scrap Register: dismantling; Batteries: battery). Nothing is deleted and no system guard changes. Remove a code to show its screens again.',
   'DEC-44')
on conflict (key) do nothing;
