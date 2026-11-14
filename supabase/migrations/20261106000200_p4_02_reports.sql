-- Migration: 20261106000200_p4_02_reports.sql
-- Prompt: P4-02 Reports & MIS, exports & printable reports (master plan §4, §8.3 report_column_prefs,
-- §10 "Report columns").
--
-- 1. report_definitions        — report catalogue: code (R-01…R-18), group, title, description and
--                                optional column-label overrides (admin-relabelable, rule e). The SQL,
--                                column types, filters and permission requirements live in the backend
--                                report registry (app/modules/reports/registry.py), never in
--                                configuration, so no label edit can widen what a user may read.
-- 2. report_column_prefs        — (P1-02 table) now tied to the catalogue; `columns` must be a list of
--                                column keys. User rows = personal choice, role rows = admin defaults.
-- 3. report_saved_filters       — named filter sets per user and report [IMP], one optional default.
-- 4. rms_reports schema         — read-only reporting views (not exposed to PostgREST, rms_api only):
--      gs_stage_times                    R-02 / R-04 stage timestamps from gs_status_history
--      user_activity_events              R-18 one row per user action, with handling time
--      stock_reconciliation_exceptions   R-14 exceptions only (mirrors scripts/integrity_check.sql
--                                        IC-01, IC-02, IC-03, IC-05, IC-09)
-- 5. Indexes for report date filters.

-- ===========================================================================
-- 1. report_definitions
-- ===========================================================================
create table public.report_definitions (
  code           text primary key check (code ~ '^R-[0-9]{2}$'),
  group_code     text not null check (group_code ~ '^[A-Z][A-Z0-9_]{1,39}$'),
  group_title    text not null check (btrim(group_title) <> ''),
  title          text not null check (btrim(title) <> ''),
  description    text,
  -- {"column_key": "Admin label"}; keys unknown to the registry are ignored by the API.
  column_labels  jsonb not null default '{}'::jsonb check (jsonb_typeof(column_labels) = 'object'),
  sort_order     integer not null default 0,
  is_active      boolean not null default true,
  created_at     timestamptz not null default now(),
  created_by     uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at     timestamptz not null default now()
);
comment on table public.report_definitions is
  'P4-02 report catalogue (§10). Codes are immutable and must match the backend report registry.';

insert into public.report_definitions (code, group_code, group_title, title, description, sort_order) values
  ('R-01', 'WORKFLOW',   'Workflow & ageing',        'Pending work by step & user',
   'Open workflow tasks per step and assignee, in ageing buckets 0-1, 1-3, 3-7 and over 7 days.', 10),
  ('R-02', 'WORKFLOW',   'Workflow & ageing',        'GS lifecycle',
   'Per goods slip: time of each stage, stage durations, current status and flags. The totals row gives the average turnaround per stage.', 20),
  ('R-03', 'WORKFLOW',   'Workflow & ageing',        'GS register',
   'Every goods slip with party, station, state, category, status and quantities.', 30),
  ('R-08', 'WORKFLOW',   'Workflow & ageing',        'Pendency register & ageing',
   'Pending (BP) records with their age, ageing bucket and clearance.', 40),
  ('R-04', 'INWARD',     'Inward & inspection',      'Inward evidence compliance',
   'Unboxing video and document photos per goods slip, and the time taken to complete Step-2.', 110),
  ('R-05', 'INWARD',     'Inward & inspection',      'Inspection summary',
   'Graded quantity by product category and condition, with not-allowed and hazard quantities.', 120),
  ('R-06', 'INWARD',     'Inward & inspection',      'Rejections & hazard register',
   'Every rejection with its reason, disposition and hazard flag.', 130),
  ('R-07', 'INWARD',     'Inward & inspection',      'Daily container audit compliance',
   'One row per day: audit status, containers counted and whether it was confirmed on time.', 140),
  ('R-09', 'SERVICING',  'Custody & servicing',      'Custody transfers & discrepancies',
   'Custody transfers with sent, counted and accepted quantities, discrepancies and reconciliation.', 210),
  ('R-10', 'SERVICING',  'Custody & servicing',      'Technician productivity',
   'Per technician: batches, pieces serviced, outcomes and battery replacement rate.', 220),
  ('R-11', 'SERVICING',  'Custody & servicing',      'Battery reconciliation',
   'Per battery type: pieces checked, batteries installed, stock movements and the ledger balance.', 230),
  ('R-12', 'SERVICING',  'Custody & servicing',      'Dismantling & parts recovery',
   'Recovered parts by part type, PCB model, supplier and container.', 240),
  ('R-13', 'INVENTORY',  'Inventory',                'Inventory position (as on date)',
   'Stock by location, custodian and condition, computed from the movement ledger up to the chosen date.', 310),
  ('R-14', 'INVENTORY',  'Inventory',                'Stock reconciliation exceptions',
   'Ledger movements against balances, and per goods-slip line the received quantity against the quantity accounted for. Only exceptions are listed.', 320),
  ('R-15', 'INVENTORY',  'Inventory',                'Store issues & dispatches',
   'Issues to the Main Store and replacement dispatches with quantities and references.', 330),
  ('R-16', 'COMMERCIAL', 'Commercial',               'Credit note register',
   'Credit notes and JVs with party document, GST portal status, values, rate sources and party notification.', 410),
  ('R-17', 'COMMERCIAL', 'Commercial',               'Credit note ageing',
   'Days from the RM CN decision to issue and from issue to party notification.', 420),
  ('R-18', 'PERFORMANCE','User performance',         'User activity & performance',
   'Actions per user per step and the average handling time.', 510)
on conflict (code) do nothing;

-- ===========================================================================
-- 2. report_column_prefs: tie to the catalogue, columns = list of keys
-- ===========================================================================
alter table public.report_column_prefs
  add constraint report_column_prefs_report_fk
    foreign key (report_code) references public.report_definitions (code) on delete cascade,
  add constraint report_column_prefs_columns_nonempty
    check (jsonb_array_length(columns) > 0);

create or replace function rms_private.report_column_prefs_validate()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if exists (select 1 from jsonb_array_elements(new.columns) e
              where jsonb_typeof(e) <> 'string' or btrim(e #>> '{}') = '') then
    raise exception 'report column preferences must be a list of column keys' using errcode = '23514';
  end if;
  if (select count(*) from jsonb_array_elements(new.columns))
     <> (select count(distinct e #>> '{}') from jsonb_array_elements(new.columns) e) then
    raise exception 'report column preferences list a column more than once' using errcode = '23514';
  end if;
  return new;
end;
$$;
revoke all on function rms_private.report_column_prefs_validate() from public, anon, authenticated;

create trigger report_column_prefs_validate
  before insert or update on public.report_column_prefs
  for each row execute function rms_private.report_column_prefs_validate();

-- ===========================================================================
-- 3. report_saved_filters
-- ===========================================================================
create table public.report_saved_filters (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references public.profiles (id) on delete cascade,
  report_code  text not null references public.report_definitions (code) on delete cascade,
  name         text not null check (btrim(name) <> '' and length(name) <= 80),
  params       jsonb not null default '{}'::jsonb check (jsonb_typeof(params) = 'object'),
  is_default   boolean not null default false,
  created_at   timestamptz not null default now(),
  created_by   uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at   timestamptz not null default now()
);
comment on table public.report_saved_filters is 'P4-02 [IMP]: named report filter sets per user.';
create unique index report_saved_filters_name_uq
  on public.report_saved_filters (user_id, report_code, lower(name));
create unique index report_saved_filters_default_uq
  on public.report_saved_filters (user_id, report_code) where is_default;
create index report_saved_filters_report_idx on public.report_saved_filters (report_code);

-- ===========================================================================
-- 4. rms_reports schema (read-only views)
-- ===========================================================================
create schema if not exists rms_reports;
revoke all on schema rms_reports from public, anon, authenticated;
grant usage on schema rms_reports to rms_api, service_role;

-- 4a. First time a goods slip entered each stage (gs_status_history), §6.5.
create view rms_reports.gs_stage_times as
select h.gs_id,
       min(h.at) filter (where h.to_status = 'UNBOXING')                 as unboxing_started_at,
       min(h.at) filter (where h.to_status = 'ITEMIZATION')              as evidence_completed_at,
       min(h.at) filter (where h.from_status = 'CSR_APPROVAL_PENDING')   as csr_decided_at,
       min(h.at) filter (where h.to_status = 'RM_REVIEW')                as inspected_at,
       min(h.at) filter (where h.to_status = 'IN_PROCESS')               as in_process_at,
       min(h.at) filter (where h.to_status = 'COMMERCIAL_RESOLUTION')    as commercial_at,
       min(h.at) filter (where h.to_status = 'AWAITING_NOTIFICATION')    as awaiting_notification_at,
       max(h.at)                                                         as last_status_change_at
  from public.gs_status_history h
 group by h.gs_id;
comment on view rms_reports.gs_stage_times is
  'P4-02 R-02/R-04: first entry into each GS lifecycle stage (§6.5), from gs_status_history.';

-- 4b. One row per user action (R-18). handling_hours = time the item waited for this action:
--     status change → since the previous status change of the same GS; transfer accept → since
--     initiation; technician receive → since allotment; dismantling → since batch creation;
--     CN issue → since the CN draft was created. Actions without a natural start have none.
create view rms_reports.user_activity_events as
select h.by as user_id, h.step_code, 'STATUS_CHANGE'::text as action_code, h.at as acted_at,
       extract(epoch from h.at - lag(h.at) over (partition by h.gs_id order by h.at, h.id))
         / 3600.0 as handling_hours,
       h.gs_id
  from public.gs_status_history h
 where h.by is not null
union all
select t.initiated_by, 'S2_HANDOVER', 'TRANSFER_INITIATE', t.initiated_at, null, t.gs_id
  from public.custody_transfers t
 where t.initiated_by is not null and t.initiated_at is not null
union all
select t.accepted_by, 'S2_HANDOVER', 'TRANSFER_ACCEPT', t.accepted_at,
       extract(epoch from t.accepted_at - t.initiated_at) / 3600.0, t.gs_id
  from public.custody_transfers t
 where t.accepted_by is not null and t.accepted_at is not null
union all
select b.entry_by, 'S3_TECHNICAL', 'TECH_ALLOT', b.allotted_at, null, null
  from public.technician_batches b
 where b.entry_by is not null and b.allotted_at is not null
union all
select r.entry_by, 'S3_TECHNICAL', 'TECH_RECEIVE', r.received_at,
       extract(epoch from r.received_at - b.allotted_at) / 3600.0, null
  from public.technician_receiving_records r
  join public.technician_batches b on b.id = r.batch_id
 where r.entry_by is not null
union all
select d.created_by, 'S4_DISMANTLE', 'DISMANTLE_COMPLETE', d.completed_at,
       extract(epoch from d.completed_at - d.created_at) / 3600.0, null
  from public.dismantle_batches d
 where d.created_by is not null and d.completed_at is not null
union all
select s.created_by, 'S6_STORE_ISSUE', 'STORE_ISSUE', s.created_at, null, null
  from public.store_issues s
 where s.created_by is not null
union all
select c.issued_by, 'S6_ACCOUNTS_CN', 'CN_ISSUE', c.issued_at,
       extract(epoch from c.issued_at - c.created_at) / 3600.0, c.gs_id
  from public.credit_notes c
 where c.issued_by is not null and c.issued_at is not null
union all
select p.sent_by, 'S6_NOTIFY', 'PARTY_NOTIFY', p.sent_at, null, p.gs_id
  from public.party_notifications p
 where p.sent_by is not null
union all
select d.dispatched_by, null, 'DISPATCH', d.dispatched_at, null, d.gs_id
  from public.replacement_dispatches d
 where d.dispatched_by is not null and d.dispatched_at is not null;
comment on view rms_reports.user_activity_events is
  'P4-02 R-18: one row per user action with the time the item waited for it (handling_hours).';

-- 4c. Stock reconciliation exceptions (R-14). The same formulas as scripts/integrity_check.sql
--     IC-01, IC-02, IC-03, IC-05 and IC-09; a healthy ledger returns no rows.
create view rms_reports.stock_reconciliation_exceptions as
with
lot_balance as (
  select l.gs_item_id, sum(b.qty)::bigint as qty
    from public.stock_lots l
    join public.stock_balances b on b.lot_id = l.id
   where l.gs_item_id is not null
   group by l.gs_item_id
),
line_flow as (
  select l.gs_item_id,
         sum(case when m.to_location_id is null then m.qty else -m.qty end)::bigint as qty
    from public.stock_lots l
    join public.stock_movements m on m.lot_id = l.id
   where l.gs_item_id is not null
     and m.movement_type not in ('INWARD', 'RECLASSIFY')
     and (m.from_location_id is null) <> (m.to_location_id is null)
   group by l.gs_item_id
),
ledger as (
  select lot_id, location_id, sum(qty)::bigint as qty
    from (select lot_id, to_location_id as location_id, qty
            from public.stock_movements where to_location_id is not null
          union all
          select lot_id, from_location_id, -qty
            from public.stock_movements where from_location_id is not null) m
   group by lot_id, location_id
)
-- IC-01 per GS line: received vs accounted (balances + quantity that left the ledger)
select 'IC-01'::text as check_code, g.id as gs_id, g.gs_no, gi.line_no, null::uuid as lot_id,
       null::text as location_code,
       gi.received_qty::bigint as expected_qty,
       (coalesce(lb.qty, 0) + coalesce(lf.qty, 0))::bigint as actual_qty,
       format('received %s; lot balances %s; net left the ledger %s',
              gi.received_qty, coalesce(lb.qty, 0), coalesce(lf.qty, 0)) as detail
  from public.gs_items gi
  join public.goods_slips g on g.id = gi.gs_id
  left join lot_balance lb on lb.gs_item_id = gi.id
  left join line_flow lf on lf.gs_item_id = gi.id
 where g.status not in ('GATE_CREATED', 'UNBOXING', 'ITEMIZATION', 'CANCELLED')
   and coalesce(lb.qty, 0) + coalesce(lf.qty, 0) <> gi.received_qty
union all
-- IC-02 negative balance (G-16)
select 'IC-02', l.gs_id, g.gs_no, gi.line_no, b.lot_id, il.code, 0, b.qty::bigint,
       format('negative balance %s', b.qty)
  from public.stock_balances b
  join public.inventory_locations il on il.id = b.location_id
  join public.stock_lots l on l.id = b.lot_id
  left join public.goods_slips g on g.id = l.gs_id
  left join public.gs_items gi on gi.id = l.gs_item_id
 where b.qty < 0
union all
-- IC-03 movements vs balances per lot and location
select 'IC-03', l.gs_id, g.gs_no, gi.line_no, coalesce(m.lot_id, b.lot_id), il.code,
       coalesce(m.qty, 0), coalesce(b.qty, 0)::bigint,
       format('ledger movements %s; stored balance %s', coalesce(m.qty, 0), coalesce(b.qty, 0))
  from ledger m
  full join public.stock_balances b on b.lot_id = m.lot_id and b.location_id = m.location_id
  join public.stock_lots l on l.id = coalesce(m.lot_id, b.lot_id)
  join public.inventory_locations il on il.id = coalesce(m.location_id, b.location_id)
  left join public.goods_slips g on g.id = l.gs_id
  left join public.gs_items gi on gi.id = l.gs_item_id
 where coalesce(m.qty, 0) <> coalesce(b.qty, 0)
union all
-- IC-05 rejection without its stock movement
select 'IC-05', gi.gs_id, g.gs_no, gi.line_no, m.lot_id, null, r.qty::bigint,
       coalesce(case when l.gs_item_id is not distinct from r.gs_item_id then m.qty end, 0)::bigint,
       case when r.stock_movement_id is null then format('rejection %s x %s has no movement', r.qty, r.condition_code)
            when m.id is null then 'rejection movement missing'
            when l.gs_item_id is distinct from r.gs_item_id then 'rejection movement is on another line'
            else format('rejection %s, movement %s', r.qty, m.qty) end
  from public.rejections r
  join public.gs_items gi on gi.id = r.gs_item_id
  join public.goods_slips g on g.id = gi.gs_id
  left join public.stock_movements m on m.id = r.stock_movement_id
  left join public.stock_lots l on l.id = m.lot_id
 where m.id is null
    or l.gs_item_id is distinct from r.gs_item_id
    or m.qty <> r.qty
union all
-- IC-09 (a) batteries installed vs consumed (BR-24, G-10)
select 'IC-09', null, null, null, m.lot_id, coalesce(fl.code, 'BATTERY_STORE'),
       coalesce(r.batteries_installed, 0)::bigint, coalesce(m.qty, 0)::bigint,
       format('technician receiving: batteries installed %s, consumed %s',
              coalesce(r.batteries_installed, 0), coalesce(m.qty, 0))
  from public.technician_receiving_records r
  left join public.stock_movements m on m.id = r.battery_stock_movement_id
  left join public.inventory_locations fl on fl.id = m.from_location_id
 where coalesce(r.batteries_installed, 0) <> coalesce(m.qty, 0)
    or (m.id is not null and (m.movement_type <> 'CONSUME' or fl.code <> 'BATTERY_STORE'
                              or m.to_location_id is not null))
union all
-- IC-09 (b) battery consumption no receiving record accounts for
select 'IC-09', null, null, null, m.lot_id, fl.code, 0, m.qty::bigint,
       format('battery CONSUME of %s pieces has no technician receiving record', m.qty)
  from public.stock_movements m
  left join public.inventory_locations fl on fl.id = m.from_location_id
 where m.movement_type = 'CONSUME'
   and m.reference_type = 'TECH_BATCH_RECEIVE'
   and not exists (select 1 from public.technician_receiving_records r
                    where r.battery_stock_movement_id = m.id);
comment on view rms_reports.stock_reconciliation_exceptions is
  'P4-02 R-14: stock reconciliation exceptions (integrity checks IC-01/02/03/05/09); empty when healthy.';

revoke all on all tables in schema rms_reports from public, anon, authenticated;
grant select on all tables in schema rms_reports to rms_api, service_role;

-- ===========================================================================
-- 5. Indexes for report date filters
-- ===========================================================================
create index if not exists rejections_created_at_idx on public.rejections (created_at desc);
create index if not exists inspections_inspected_at_idx on public.inspections (inspected_at desc)
  where status = 'FINAL';
create index if not exists recovered_parts_created_at_idx on public.recovered_parts (created_at desc);
create index if not exists custody_transfers_initiated_at_idx on public.custody_transfers (initiated_at desc);
create index if not exists pendencies_opened_at_idx on public.pendencies (opened_at desc);
create index if not exists replacement_dispatches_dispatched_at_idx
  on public.replacement_dispatches (dispatched_at desc);
create index if not exists technician_batches_allotted_at_idx on public.technician_batches (allotted_at desc);
create index if not exists workflow_tasks_open_created_idx on public.workflow_tasks (created_at)
  where status = 'OPEN';
create index if not exists gs_status_history_by_at_idx on public.gs_status_history (by, at desc);

-- ===========================================================================
-- 6. Audit, RLS, grants
-- ===========================================================================
select rms_private.attach_standard_triggers('public.report_definitions');
select rms_private.attach_standard_triggers('public.report_saved_filters');

alter table public.report_definitions enable row level security;
alter table public.report_saved_filters enable row level security;

revoke all on public.report_definitions from anon, authenticated;
revoke all on public.report_saved_filters from anon, authenticated;

-- Report codes are fixed by the registry: rms_api may relabel, never add or delete.
revoke insert, delete on public.report_definitions from rms_api;
grant select, update on public.report_definitions to rms_api;
grant select, insert, update, delete on public.report_saved_filters to rms_api;

grant all on public.report_definitions to service_role;
grant all on public.report_saved_filters to service_role;
