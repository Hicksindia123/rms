-- =============================================================================
-- Migration: 20261104000400_p3_04_inventory_segregation.sql
-- P3-04 · Custody segregation, functional inventory & spare-parts ledger
-- Master plan §2.2 (Stage-5, Step-6), §3.2 DD r63–r66, BR-30, G-04, G-05, G-08, G-09, G-12, G-16.
--
-- 1. custody_assignments   — explicit Step-6 custody assignment (DD r63–66) with a DB guard that
--                            rejects an assignment contradicting the lot's condition (G-04/G-12).
-- 2. stock_adjustments     — physical count differences: request (custodian) → approve / reject
--                            (RM / admin), reason mandatory, separation of duties, ADJUST movement.
-- 3. segregation_check_runs + rms_private.inventory_segregation_violations() — the single
--                            definition of the BR-30 / G-04 / G-05 / G-08 / G-09 / G-12 integrity
--                            check, used by the API, the nightly job and pgTAP.
-- 4. stock_lots condition guard — closes a G-04/G-05/G-12 gap: a lot's condition_class could be
--                            edited in place while it sits in a location that forbids the new class.
-- 5. Settings (configuration, never able to disable a guard).
-- =============================================================================

-- ===========================================================================
-- 1. custody_assignments (DD r63–66, BR-30)
-- ===========================================================================
create table public.custody_assignments (
  id                 uuid primary key default gen_random_uuid(),
  lot_id             uuid not null references public.stock_lots (id) on delete restrict,
  qty                integer not null check (qty > 0),
  assignment_code    text not null check (assignment_code in (
                       'CUST_FUNCTIONAL_GOOD','CUST_FUNCTIONAL_REPAIRED',
                       'CUST_NON_FUNCTIONAL','CUST_SALVAGED_PARTS')),
  condition_class    text not null,
  from_location_id   uuid not null references public.inventory_locations (id) on delete restrict,
  to_location_id     uuid not null references public.inventory_locations (id) on delete restrict,
  outcome            text not null check (outcome in ('ALREADY_IN_PLACE','TRANSFER_INITIATED')),
  transfer_id        uuid references public.custody_transfers (id) on delete restrict,
  form_version_id    uuid references public.form_versions (id) on delete restrict,   -- G-18 pin
  labels_snapshot    jsonb not null default '{}'::jsonb,
  notes              text,
  created_by         uuid default rms_private.current_actor() references public.profiles (id) on delete set null,
  created_at         timestamptz not null default now(),
  check ((outcome = 'TRANSFER_INITIATED') = (transfer_id is not null)),
  check ((outcome = 'ALREADY_IN_PLACE') = (from_location_id = to_location_id))
);

create index custody_assignments_lot_idx on public.custody_assignments (lot_id);
create index custody_assignments_transfer_idx on public.custody_assignments (transfer_id);
create index custody_assignments_created_at_idx on public.custody_assignments (created_at desc);

-- Assignment ↔ condition ↔ destination class. Locked (not configuration): the target location of
-- each code is a setting, but this trigger stops any setting from pointing a non-functional
-- assignment at a FUNCTIONAL location or vice versa.
create or replace function rms_private.custody_assignments_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_lot   record;
  v_to    record;
begin
  if tg_op <> 'INSERT' then
    raise exception 'custody_assignments is insert-only' using errcode = 'P0001';
  end if;

  select * into v_lot from public.stock_lots where id = new.lot_id;
  select * into v_to from public.inventory_locations where id = new.to_location_id;
  new.condition_class := v_lot.condition_class;

  if v_lot.condition_class = 'HAZARD' then
    raise exception 'G-05: HAZARD lots are never custody-assigned; they stay in HAZARD_QUARANTINE'
      using errcode = 'P0001';
  end if;
  if new.assignment_code in ('CUST_FUNCTIONAL_GOOD','CUST_FUNCTIONAL_REPAIRED')
     and v_lot.condition_class in ('NOT_ALLOWED','NON_GOOD','NON_SELLABLE','SCRAP') then
    raise exception 'G-04: a % lot cannot be assigned to functional custody (%)',
      v_lot.condition_class, new.assignment_code using errcode = 'P0001';
  end if;
  if new.assignment_code in ('CUST_FUNCTIONAL_GOOD','CUST_FUNCTIONAL_REPAIRED')
     and v_lot.condition_class = 'SALVAGED' then
    raise exception 'G-12: salvaged parts cannot be assigned to functional custody'
      using errcode = 'P0001';
  end if;
  if (new.assignment_code = 'CUST_FUNCTIONAL_GOOD' and v_lot.condition_class <> 'FUNCTIONAL_GOOD')
     or (new.assignment_code = 'CUST_FUNCTIONAL_REPAIRED' and v_lot.condition_class <> 'FUNCTIONAL_REPAIRED')
     or (new.assignment_code = 'CUST_NON_FUNCTIONAL'
         and v_lot.condition_class not in ('NON_GOOD','NON_SELLABLE','NOT_ALLOWED'))
     or (new.assignment_code = 'CUST_SALVAGED_PARTS' and v_lot.condition_class <> 'SALVAGED') then
    raise exception 'BR-30: assignment % does not match lot condition %',
      new.assignment_code, v_lot.condition_class using errcode = '23514';
  end if;

  if (new.assignment_code in ('CUST_FUNCTIONAL_GOOD','CUST_FUNCTIONAL_REPAIRED')
        and v_to.location_class <> 'FUNCTIONAL')
     or (new.assignment_code = 'CUST_NON_FUNCTIONAL' and v_to.location_class <> 'NON_FUNCTIONAL')
     or (new.assignment_code = 'CUST_SALVAGED_PARTS' and v_to.location_class <> 'SPARE_PARTS') then
    raise exception 'G-12: assignment % cannot target a % location',
      new.assignment_code, v_to.location_class using errcode = 'P0001';
  end if;
  return new;
end;
$$;

create trigger custody_assignments_guard
  before insert or update or delete on public.custody_assignments
  for each row execute function rms_private.custody_assignments_guard();

create trigger audit_row
  after insert or update or delete on public.custody_assignments
  for each row execute function rms_private.audit_row();

-- ===========================================================================
-- 2. stock_adjustments (physical count differences, ADJUST movements)
-- ===========================================================================
create table public.stock_adjustments (
  id                 uuid primary key default gen_random_uuid(),
  lot_id             uuid not null references public.stock_lots (id) on delete restrict,
  location_id        uuid not null references public.inventory_locations (id) on delete restrict,
  system_qty         integer not null check (system_qty >= 0),
  counted_qty        integer not null check (counted_qty >= 0),
  delta              integer generated always as (counted_qty - system_qty) stored,
  reason             text not null check (btrim(reason) <> ''),
  status             text not null default 'REQUESTED'
                       check (status in ('REQUESTED','APPROVED','REJECTED')),
  requested_by       uuid not null default rms_private.current_actor() references public.profiles (id) on delete restrict,
  requested_at       timestamptz not null default now(),
  decided_by         uuid references public.profiles (id) on delete restrict,
  decided_at         timestamptz,
  decision_remarks   text,
  movement_id        uuid references public.stock_movements (id) on delete restrict,
  updated_at         timestamptz not null default now(),
  check (counted_qty <> system_qty),
  check (status = 'REQUESTED' or (decided_by is not null and decided_at is not null)),
  check ((status = 'APPROVED') = (movement_id is not null)),
  check (status <> 'REJECTED' or btrim(coalesce(decision_remarks, '')) <> '')
);

create index stock_adjustments_lot_idx on public.stock_adjustments (lot_id);
create index stock_adjustments_location_idx on public.stock_adjustments (location_id);
create index stock_adjustments_status_idx on public.stock_adjustments (status, requested_at desc);
-- One open count difference per lot and location at a time.
create unique index stock_adjustments_one_open
  on public.stock_adjustments (lot_id, location_id) where status = 'REQUESTED';

create or replace function rms_private.stock_adjustments_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_class text;
begin
  if tg_op = 'DELETE' then
    raise exception 'stock_adjustments rows cannot be deleted' using errcode = 'P0001';
  end if;

  if tg_op = 'INSERT' then
    if new.status <> 'REQUESTED' then
      raise exception 'A stock adjustment starts as REQUESTED' using errcode = '23514';
    end if;
    select location_class into v_class from public.inventory_locations where id = new.location_id;
    -- G-09: stock in TRANSIT belongs to a custody transfer and is settled by its reconciliation.
    if v_class = 'TRANSIT' then
      raise exception 'G-09: stock in transit is adjusted only through its custody transfer'
        using errcode = 'P0001';
    end if;
    return new;
  end if;

  -- UPDATE: only the decision columns change, once.
  if old.status <> 'REQUESTED' then
    raise exception 'Stock adjustment % is already %', old.id, old.status using errcode = '23514';
  end if;
  if new.lot_id <> old.lot_id or new.location_id <> old.location_id
     or new.system_qty <> old.system_qty or new.counted_qty <> old.counted_qty
     or new.reason <> old.reason or new.requested_by <> old.requested_by
     or new.requested_at <> old.requested_at then
    raise exception 'A stock adjustment request is immutable; only its decision is recorded'
      using errcode = '23514';
  end if;
  -- §9.3 separation of duties: the requester never decides their own count (Super Admin too).
  if new.status <> 'REQUESTED' and new.decided_by = old.requested_by then
    raise exception 'SEGREGATION_OF_DUTIES: the requester cannot decide their own stock adjustment'
      using errcode = '42501';
  end if;
  return new;
end;
$$;

create trigger stock_adjustments_guard
  before insert or update or delete on public.stock_adjustments
  for each row execute function rms_private.stock_adjustments_guard();

create trigger audit_row
  after insert or update or delete on public.stock_adjustments
  for each row execute function rms_private.audit_row();

create trigger set_updated_at
  before update on public.stock_adjustments
  for each row execute function rms_private.set_updated_at();

-- ===========================================================================
-- 3. Segregation integrity check (BR-30, G-04, G-05, G-08, G-09, G-12)
-- ===========================================================================
create table public.segregation_check_runs (
  id               uuid primary key default gen_random_uuid(),
  trigger_code     text not null check (trigger_code in ('NIGHTLY','ON_DEMAND')),
  run_by           uuid default rms_private.current_actor() references public.profiles (id) on delete set null,
  run_at           timestamptz not null default now(),
  violation_count  integer not null check (violation_count >= 0),
  violations       jsonb not null default '[]'::jsonb check (jsonb_typeof(violations) = 'array')
);

create index segregation_check_runs_run_at_idx on public.segregation_check_runs (run_at desc);

create trigger audit_row
  after insert or update or delete on public.segregation_check_runs
  for each row execute function rms_private.audit_row();

-- Every positive balance that breaks the custody boundary. Should always return zero rows: the
-- guards in rms_move_stock and the triggers prevent each case; this proves it independently.
create or replace function rms_private.inventory_segregation_violations()
returns table (
  rule_code       text,
  guard_ref       text,
  lot_id          uuid,
  location_id     uuid,
  qty             integer,
  condition_class text,
  location_class  text,
  detail          text
)
language sql
stable
security definer
set search_path = ''
as $$
  with pos as (
    select b.lot_id, b.location_id, b.qty, lot.condition_class, lot.is_pending,
           si.item_kind, l.location_class, l.code as location_code, r.code as custodian_role
      from public.stock_balances b
      join public.stock_lots lot on lot.id = b.lot_id
      join public.stock_items si on si.id = lot.stock_item_id
      join public.inventory_locations l on l.id = b.location_id
      left join public.roles r on r.id = l.custodian_role_id
     where b.qty > 0
  )
  -- G-12 / BR-30: the Intermediate Store never holds non-functional, scrap, hazard or parts.
  select 'NON_FUNCTIONAL_IN_FUNCTIONAL', 'G-12', p.lot_id, p.location_id, p.qty, p.condition_class,
         p.location_class,
         format('%s stock in functional location %s', p.condition_class, p.location_code)
    from pos p
   where p.location_class = 'FUNCTIONAL'
     and p.condition_class not in ('AS_RECEIVED','FUNCTIONAL_GOOD','FUNCTIONAL_REPAIRED')
  union all
  -- G-04: not-allowed / non-functional stock never reaches Main Store or dispatch.
  select 'NOT_ALLOWED_DOWNSTREAM', 'G-04', p.lot_id, p.location_id, p.qty, p.condition_class,
         p.location_class,
         format('%s stock in %s', p.condition_class, p.location_code)
    from pos p
   where p.condition_class in ('NOT_ALLOWED','HAZARD','NON_GOOD','NON_SELLABLE','SCRAP')
     and p.location_class in ('MAIN_STORE','DISPATCHED')
  union all
  -- G-05: hazard stock only in quarantine (or disposed).
  select 'HAZARD_OUTSIDE_QUARANTINE', 'G-05', p.lot_id, p.location_id, p.qty, p.condition_class,
         p.location_class,
         format('HAZARD stock in %s', p.location_code)
    from pos p
   where p.condition_class = 'HAZARD'
     and p.location_class not in ('HAZARD_QUARANTINE','SCRAP_DISPOSED')
  union all
  -- G-08: Pending (BP) pieces never sit in the store or in transit.
  select 'PENDING_IN_FUNCTIONAL', 'G-08', p.lot_id, p.location_id, p.qty, p.condition_class,
         p.location_class,
         format('Pending (BP) stock in %s', p.location_code)
    from pos p
   where p.is_pending and p.location_class in ('FUNCTIONAL','TRANSIT')
  union all
  -- BR-30: functional finished goods are with Sahil (or legitimately downstream / in transit).
  select 'FUNCTIONAL_OUTSIDE_STORE', 'BR-30', p.lot_id, p.location_id, p.qty, p.condition_class,
         p.location_class,
         format('%s stock held in %s instead of the Intermediate Store', p.condition_class, p.location_code)
    from pos p
   where p.item_kind = 'FINISHED_GOOD'
     and p.condition_class in ('FUNCTIONAL_GOOD','FUNCTIONAL_REPAIRED')
     and p.location_class not in ('FUNCTIONAL','TRANSIT','MAIN_STORE','DISPATCHED','CREDITED')
  union all
  -- BR-30: non-functional / non-sellable stock is exclusively the Spare Parts Manager's.
  select 'NON_FUNCTIONAL_OUTSIDE_SPM', 'BR-30', p.lot_id, p.location_id, p.qty, p.condition_class,
         p.location_class,
         format('%s stock held in %s outside Spare Parts Manager custody', p.condition_class, p.location_code)
    from pos p
   where p.condition_class in ('NON_GOOD','NON_SELLABLE')
     and p.location_class not in ('NON_FUNCTIONAL','SPARE_PARTS','TRANSIT','SCRAP_DISPOSED')
  union all
  -- BR-30: salvaged parts only in the spare parts ledger.
  select 'SALVAGED_OUTSIDE_LEDGER', 'BR-30', p.lot_id, p.location_id, p.qty, p.condition_class,
         p.location_class,
         format('Salvaged parts held in %s outside the spare parts ledger', p.location_code)
    from pos p
   where p.condition_class = 'SALVAGED'
     and p.location_class not in ('SPARE_PARTS','TRANSIT','SCRAP_DISPOSED')
  union all
  -- BR-30: the custodian of each segregated location is the right role.
  select 'CUSTODIAN_MISMATCH', 'BR-30', p.lot_id, p.location_id, p.qty, p.condition_class,
         p.location_class,
         format('%s location %s is not in %s custody (custodian role %s)', p.location_class,
                p.location_code,
                case when p.location_class = 'FUNCTIONAL' then 'INTERMEDIATE_STORE_MANAGER'
                     else 'SPARE_PARTS_MANAGER' end,
                coalesce(p.custodian_role, 'none'))
    from pos p
   where (p.location_class = 'FUNCTIONAL'
          and p.custodian_role is distinct from 'INTERMEDIATE_STORE_MANAGER')
      or (p.location_class in ('NON_FUNCTIONAL','SPARE_PARTS')
          and p.custodian_role is distinct from 'SPARE_PARTS_MANAGER')
  union all
  -- G-09: every piece in transit belongs to a live custody transfer.
  select 'TRANSIT_WITHOUT_TRANSFER', 'G-09', p.lot_id, p.location_id, p.qty, p.condition_class,
         p.location_class,
         'Stock in transit without a live custody transfer'
    from pos p
   where p.location_class = 'TRANSIT'
     and not exists (
       select 1
         from public.custody_transfer_lines tl
         join public.custody_transfers t on t.id = tl.transfer_id
        where tl.lot_id = p.lot_id
          and t.transit_location_id = p.location_id
          and t.stock_moved
          and t.status in ('INITIATED','DISCREPANCY'));
$$;

revoke all on function rms_private.inventory_segregation_violations() from public, anon, authenticated;
grant execute on function rms_private.inventory_segregation_violations() to rms_api, service_role;

-- ===========================================================================
-- 4. stock_lots: condition_class may not change into a class its current locations forbid
-- ===========================================================================
create or replace function rms_private.stock_lots_condition_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_class text;
begin
  if new.condition_class is not distinct from old.condition_class then
    return new;
  end if;
  for v_class in
    select distinct l.location_class
      from public.stock_balances b
      join public.inventory_locations l on l.id = b.location_id
     where b.lot_id = new.id and b.qty > 0
  loop
    if new.condition_class in ('NOT_ALLOWED','HAZARD','NON_GOOD','NON_SELLABLE','SCRAP')
       and v_class in ('FUNCTIONAL','MAIN_STORE','DISPATCHED') then
      raise exception 'G-04: lot % holds stock in a % location; it cannot become %',
        new.id, v_class, new.condition_class using errcode = 'P0001';
    end if;
    if new.condition_class = 'HAZARD' and v_class not in ('HAZARD_QUARANTINE','SCRAP_DISPOSED') then
      raise exception 'G-05: lot % holds stock in a % location; it cannot become HAZARD',
        new.id, v_class using errcode = 'P0001';
    end if;
    if v_class = 'FUNCTIONAL'
       and new.condition_class not in ('AS_RECEIVED','FUNCTIONAL_GOOD','FUNCTIONAL_REPAIRED') then
      raise exception 'G-12: lot % holds stock in a FUNCTIONAL location; it cannot become %',
        new.id, new.condition_class using errcode = 'P0001';
    end if;
  end loop;
  return new;
end;
$$;

create trigger stock_lots_condition_guard
  before update of condition_class on public.stock_lots
  for each row execute function rms_private.stock_lots_condition_guard();

revoke all on function rms_private.custody_assignments_guard() from public, anon, authenticated;
revoke all on function rms_private.stock_adjustments_guard() from public, anon, authenticated;
revoke all on function rms_private.stock_lots_condition_guard() from public, anon, authenticated;

-- ===========================================================================
-- 5. RLS & grants: business tables are reachable only through FastAPI (§6.1)
-- ===========================================================================
alter table public.custody_assignments enable row level security;
alter table public.stock_adjustments enable row level security;
alter table public.segregation_check_runs enable row level security;

revoke all on public.custody_assignments from anon, authenticated;
revoke all on public.stock_adjustments from anon, authenticated;
revoke all on public.segregation_check_runs from anon, authenticated;

grant select, insert on public.custody_assignments to rms_api;
grant select, insert, update on public.stock_adjustments to rms_api;
grant select, insert on public.segregation_check_runs to rms_api;
grant all on public.custody_assignments to service_role;
grant all on public.stock_adjustments to service_role;
grant all on public.segregation_check_runs to service_role;

-- ===========================================================================
-- 6. Settings (configuration; none of them can disable a guard)
-- ===========================================================================
insert into public.system_settings (key, value, category, description, source_ref) values
  ('custody_assignment_targets',
   '{"CUST_FUNCTIONAL_GOOD":"INTERMEDIATE_STORE","CUST_FUNCTIONAL_REPAIRED":"INTERMEDIATE_STORE","CUST_NON_FUNCTIONAL":"NON_FUNCTIONAL_STORE","CUST_SALVAGED_PARTS":"SPARE_PARTS_STORE"}'::jsonb,
   'inventory',
   'Step-6 custody assignment: destination location code per assignment option (DD r63–66). The location class must still match the assignment (G-04/G-12, locked).',
   'BR-30'),
  ('stock_adjustment_approver_roles', '["REPLACEMENT_MANAGER"]'::jsonb, 'inventory',
   'Roles that may approve or reject a stock adjustment (with inventory.approve). Super Admin always may; the requester never may.',
   'P3-04'),
  ('spare_parts_ledger_view_roles', '["SPARE_PARTS_MANAGER","MANAGEMENT_VIEWER"]'::jsonb, 'inventory',
   'Roles that may see salvaged spare parts (with inventory.view). Super Admin always may.',
   'BR-30'),
  ('segregation_alert_roles', '["REPLACEMENT_MANAGER"]'::jsonb, 'inventory',
   'Roles notified when the nightly segregation check finds a violation (Super Admins are always notified).',
   'P3-04')
on conflict (key) do nothing;
