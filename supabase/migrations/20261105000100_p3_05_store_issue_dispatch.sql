-- =============================================================================
-- Migration: 20261105000100_p3_05_store_issue_dispatch.sql
-- P3-05 · Post-technical RM revision, Main Store issue & replacement dispatch
-- Master plan §2.2 (Stage-6, Step-7), §8.6, BR-19, BR-31, BR-32, G-04, DEC-13, DEC-21, DEC-26, DEC-33.
--
-- 1. store_issues & store_issue_lines     — Issue functional stock to Main Store (BR-31, DEC-21)
--                                           with G-04 condition guard (only FUNCTIONAL_*).
-- 2. replacement_dispatches & lines       — Dispatch replacement units (SEND_NEW / SEND_REPAIRED)
--                                           linked to GS and RM actions with G-04 / DEC-26 guards.
-- 3. Settings & Permissions               — System settings for auto-acknowledgement and roles.
-- =============================================================================

-- ===========================================================================
-- 1. store_issues & store_issue_lines (BR-31, DEC-21, G-04)
-- ===========================================================================
create table public.store_issues (
  id                 uuid primary key default gen_random_uuid(),
  issue_no           text not null unique,
  issue_type_code    text not null default 'ISSUE_MAIN_STORE' check (issue_type_code = 'ISSUE_MAIN_STORE'),
  from_location_id   uuid not null references public.inventory_locations (id) on delete restrict,
  to_location_id     uuid not null references public.inventory_locations (id) on delete restrict,
  transfer_id        uuid references public.custody_transfers (id) on delete set null,
  status             text not null default 'ISSUED' check (status in ('ISSUED', 'ACKNOWLEDGED', 'CANCELLED')),
  notes              text,
  created_by         uuid default rms_private.current_actor() references public.profiles (id) on delete set null,
  created_at         timestamptz not null default now(),
  acknowledged_by    uuid references public.profiles (id) on delete set null,
  acknowledged_at    timestamptz
);

create index store_issues_created_at_idx on public.store_issues (created_at desc);
create index store_issues_status_idx on public.store_issues (status);
create index store_issues_transfer_idx on public.store_issues (transfer_id);

create table public.store_issue_lines (
  id                 uuid primary key default gen_random_uuid(),
  issue_id           uuid not null references public.store_issues (id) on delete cascade,
  lot_id             uuid not null references public.stock_lots (id) on delete restrict,
  qty                integer not null check (qty > 0),
  created_at         timestamptz not null default now()
);

create index store_issue_lines_issue_idx on public.store_issue_lines (issue_id);
create index store_issue_lines_lot_idx on public.store_issue_lines (lot_id);

-- Guard G-04 on store issue lines: only functional lots (FUNCTIONAL_GOOD or FUNCTIONAL_REPAIRED)
create or replace function rms_private.store_issue_lines_g04_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_lot record;
begin
  select condition_class into v_lot
    from public.stock_lots
   where id = new.lot_id;

  if not found then
    raise exception 'Lot % not found', new.lot_id using errcode = 'P0002';
  end if;

  if v_lot.condition_class not in ('FUNCTIONAL_GOOD', 'FUNCTIONAL_REPAIRED') then
    raise exception 'G-04: Only functional lots (FUNCTIONAL_GOOD or FUNCTIONAL_REPAIRED) can be issued to Main Store (attempted %)',
      v_lot.condition_class using errcode = 'P0001';
  end if;

  return new;
end;
$$;

-- Update G-09 guard to exempt auto-acknowledged STORE_ISSUE from initiator=receiver check (DEC-21)
create or replace function rms_private.custody_transfers_g09_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_sod boolean;
begin
  if tg_op = 'INSERT' then
    if new.status <> 'INITIATED' then
      raise exception 'G-09: a custody transfer starts INITIATED' using errcode = '23514';
    end if;
    return new;
  end if;

  if old.stock_moved and not new.stock_moved then
    raise exception 'G-09: stock of transfer % has moved; stock_moved cannot be reset', old.transfer_no
      using errcode = '23514';
  end if;
  if new.stock_moved and not old.stock_moved and old.status <> 'INITIATED' then
    raise exception 'G-09: only an INITIATED transfer can move its stock to TRANSIT' using errcode = '23514';
  end if;
  if new.status is not distinct from old.status then
    return new;
  end if;

  if not ((old.status = 'INITIATED' and new.status in ('ACCEPTED','DISCREPANCY','CANCELLED'))
          or (old.status = 'DISCREPANCY' and new.status = 'RECONCILED')) then
    raise exception 'G-09: custody transfer % cannot go from % to %', old.transfer_no, old.status, new.status
      using errcode = '23514';
  end if;

  if new.status in ('ACCEPTED','DISCREPANCY') then
    if not new.stock_moved then
      raise exception 'G-09: transfer % has not been dispatched to TRANSIT yet', new.transfer_no
        using errcode = '23514';
    end if;
    if new.accepted_by is null or new.accepted_at is null then
      raise exception 'G-09: the receiver and the count time are required' using errcode = '23514';
    end if;
    -- §9.3 segregation of duties (setting; checked by the service too).
    -- DEC-34: technician coordinators allot and receive on behalf of the technician.
    -- DEC-21: store issue auto-acknowledgement on behalf of main store.
    if coalesce(new.purpose_code, '') not in ('TECHNICIAN_ALLOTMENT', 'TECHNICIAN_RECEIVING', 'STORE_ISSUE') then
      select coalesce((s.value #>> '{}')::boolean, true) into v_sod
        from public.system_settings s where s.key = 'segregation_of_duties_transfer';
      if coalesce(v_sod, true) and new.accepted_by = new.initiated_by then
        raise exception 'SEGREGATION_OF_DUTIES: the initiator of transfer % cannot accept it', new.transfer_no
          using errcode = '42501';
      end if;
    end if;
  end if;

  if new.status = 'ACCEPTED' then
    if new.acceptance_code is distinct from 'ACCEPTED_VERIFIED' then
      raise exception 'G-09: an accepted transfer needs acceptance code ACCEPTED_VERIFIED' using errcode = '23514';
    end if;
    -- DD r45: counts match → accepted. Any mismatch is a discrepancy (DD r46).
    if exists (select 1 from public.custody_transfer_lines l
                where l.transfer_id = new.id and l.qty_counted <> l.qty_sent) then
      raise exception 'G-09: transfer % has a count that differs from the quantity sent', new.transfer_no
        using errcode = '23514';
    end if;
  elsif new.status = 'DISCREPANCY' then
    if new.acceptance_code is distinct from 'DISCREPANCY' then
      raise exception 'G-09: a discrepancy needs acceptance code DISCREPANCY' using errcode = '23514';
    end if;
  elsif new.status = 'RECONCILED' then
    if not exists (select 1 from public.custody_reconciliations r
                    where r.transfer_id = new.id and r.status = 'APPLIED') then
      raise exception 'G-09: transfer % has no applied reconciliation', new.transfer_no
        using errcode = '23514';
    end if;
  end if;
  return new;
end
$$;

revoke all on function rms_private.custody_transfers_g09_guard() from public, anon, authenticated;

create trigger trg_store_issue_lines_g04
  before insert or update on public.store_issue_lines
  for each row execute function rms_private.store_issue_lines_g04_guard();

-- ===========================================================================
-- 2. replacement_dispatches & replacement_dispatch_lines (BR-32, DEC-26, DEC-33)
-- ===========================================================================
create table public.replacement_dispatches (
  id                 uuid primary key default gen_random_uuid(),
  dispatch_no        text not null unique,
  gs_id              uuid not null references public.goods_slips (id) on delete restrict,
  dispatch_type      text not null check (dispatch_type in ('SEND_NEW', 'SEND_REPAIRED')),
  transporter        text not null,
  docket_no          text,
  vehicle_no         text,
  ref_doc_no         text,
  ref_doc_date       date,
  status             text not null default 'DISPATCHED' check (status in ('DISPATCHED', 'CANCELLED')),
  override_reason    text,
  notes              text,
  dispatched_by      uuid not null default rms_private.current_actor() references public.profiles (id) on delete restrict,
  dispatched_at      timestamptz not null default now(),
  created_at         timestamptz not null default now()
);

create index replacement_dispatches_gs_idx on public.replacement_dispatches (gs_id);
create index replacement_dispatches_created_at_idx on public.replacement_dispatches (created_at desc);
create index replacement_dispatches_type_idx on public.replacement_dispatches (dispatch_type);

create table public.replacement_dispatch_lines (
  id                 uuid primary key default gen_random_uuid(),
  dispatch_id        uuid not null references public.replacement_dispatches (id) on delete cascade,
  gs_item_id         uuid not null references public.gs_items (id) on delete restrict,
  lot_id             uuid references public.stock_lots (id) on delete restrict,
  qty                integer not null check (qty > 0),
  stock_movement_id  uuid references public.stock_movements (id) on delete set null,
  created_at         timestamptz not null default now(),
  check (
    (lot_id is not null) or (stock_movement_id is null)
  )
);

create index replacement_dispatch_lines_dispatch_idx on public.replacement_dispatch_lines (dispatch_id);
create index replacement_dispatch_lines_item_idx on public.replacement_dispatch_lines (gs_item_id);
create index replacement_dispatch_lines_lot_idx on public.replacement_dispatch_lines (lot_id);

-- Guard on replacement dispatch lines:
-- SEND_REPAIRED requires lot_id with condition_class = 'FUNCTIONAL_REPAIRED'
-- SEND_NEW requires lot_id IS NULL (DEC-26)
create or replace function rms_private.replacement_dispatch_lines_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_dispatch record;
  v_lot record;
begin
  select dispatch_type into v_dispatch
    from public.replacement_dispatches
   where id = new.dispatch_id;

  if not found then
    raise exception 'Dispatch % not found', new.dispatch_id using errcode = 'P0002';
  end if;

  if v_dispatch.dispatch_type = 'SEND_REPAIRED' then
    if new.lot_id is null then
      raise exception 'SEND_REPAIRED dispatch requires a specific lot_id' using errcode = 'P0001';
    end if;

    select condition_class into v_lot
      from public.stock_lots
     where id = new.lot_id;

    if not found then
      raise exception 'Lot % not found', new.lot_id using errcode = 'P0002';
    end if;

    if v_lot.condition_class <> 'FUNCTIONAL_REPAIRED' then
      raise exception 'G-04: SEND_REPAIRED requires FUNCTIONAL_REPAIRED lot (lot was %)',
        v_lot.condition_class using errcode = 'P0001';
    end if;
  elsif v_dispatch.dispatch_type = 'SEND_NEW' then
    if new.lot_id is not null then
      raise exception 'DEC-26: SEND_NEW dispatches new stock outside returned goods ledger (lot_id must be null)'
        using errcode = 'P0001';
    end if;
  end if;

  return new;
end;
$$;

-- Update G-09 guard to exempt auto-acknowledged STORE_ISSUE from initiator=receiver check (DEC-21)
create or replace function rms_private.custody_transfers_g09_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_sod boolean;
begin
  if tg_op = 'INSERT' then
    if new.status <> 'INITIATED' then
      raise exception 'G-09: a custody transfer starts INITIATED' using errcode = '23514';
    end if;
    return new;
  end if;

  if old.stock_moved and not new.stock_moved then
    raise exception 'G-09: stock of transfer % has moved; stock_moved cannot be reset', old.transfer_no
      using errcode = '23514';
  end if;
  if new.stock_moved and not old.stock_moved and old.status <> 'INITIATED' then
    raise exception 'G-09: only an INITIATED transfer can move its stock to TRANSIT' using errcode = '23514';
  end if;
  if new.status is not distinct from old.status then
    return new;
  end if;

  if not ((old.status = 'INITIATED' and new.status in ('ACCEPTED','DISCREPANCY','CANCELLED'))
          or (old.status = 'DISCREPANCY' and new.status = 'RECONCILED')) then
    raise exception 'G-09: custody transfer % cannot go from % to %', old.transfer_no, old.status, new.status
      using errcode = '23514';
  end if;

  if new.status in ('ACCEPTED','DISCREPANCY') then
    if not new.stock_moved then
      raise exception 'G-09: transfer % has not been dispatched to TRANSIT yet', new.transfer_no
        using errcode = '23514';
    end if;
    if new.accepted_by is null or new.accepted_at is null then
      raise exception 'G-09: the receiver and the count time are required' using errcode = '23514';
    end if;
    -- §9.3 segregation of duties (setting; checked by the service too).
    -- DEC-34: technician coordinators allot and receive on behalf of the technician.
    -- DEC-21: store issue auto-acknowledgement on behalf of main store.
    if coalesce(new.purpose_code, '') not in ('TECHNICIAN_ALLOTMENT', 'TECHNICIAN_RECEIVING', 'STORE_ISSUE') then
      select coalesce((s.value #>> '{}')::boolean, true) into v_sod
        from public.system_settings s where s.key = 'segregation_of_duties_transfer';
      if coalesce(v_sod, true) and new.accepted_by = new.initiated_by then
        raise exception 'SEGREGATION_OF_DUTIES: the initiator of transfer % cannot accept it', new.transfer_no
          using errcode = '42501';
      end if;
    end if;
  end if;

  if new.status = 'ACCEPTED' then
    if new.acceptance_code is distinct from 'ACCEPTED_VERIFIED' then
      raise exception 'G-09: an accepted transfer needs acceptance code ACCEPTED_VERIFIED' using errcode = '23514';
    end if;
    -- DD r45: counts match → accepted. Any mismatch is a discrepancy (DD r46).
    if exists (select 1 from public.custody_transfer_lines l
                where l.transfer_id = new.id and l.qty_counted <> l.qty_sent) then
      raise exception 'G-09: transfer % has a count that differs from the quantity sent', new.transfer_no
        using errcode = '23514';
    end if;
  elsif new.status = 'DISCREPANCY' then
    if new.acceptance_code is distinct from 'DISCREPANCY' then
      raise exception 'G-09: a discrepancy needs acceptance code DISCREPANCY' using errcode = '23514';
    end if;
  elsif new.status = 'RECONCILED' then
    if not exists (select 1 from public.custody_reconciliations r
                    where r.transfer_id = new.id and r.status = 'APPLIED') then
      raise exception 'G-09: transfer % has no applied reconciliation', new.transfer_no
        using errcode = '23514';
    end if;
  end if;
  return new;
end
$$;

revoke all on function rms_private.custody_transfers_g09_guard() from public, anon, authenticated;

create trigger trg_replacement_dispatch_lines_guard
  before insert or update on public.replacement_dispatch_lines
  for each row execute function rms_private.replacement_dispatch_lines_guard();

-- Revoke execute on private guards
revoke all on function rms_private.store_issue_lines_g04_guard() from public, anon, authenticated;
revoke all on function rms_private.replacement_dispatch_lines_guard() from public, anon, authenticated;

-- ===========================================================================
-- 3. Audit triggers & RLS
-- ===========================================================================
create trigger audit_row
  after insert or update or delete on public.store_issues
  for each row execute function rms_private.audit_row();

create trigger audit_row
  after insert or update or delete on public.store_issue_lines
  for each row execute function rms_private.audit_row();

create trigger audit_row
  after insert or update or delete on public.replacement_dispatches
  for each row execute function rms_private.audit_row();

create trigger audit_row
  after insert or update or delete on public.replacement_dispatch_lines
  for each row execute function rms_private.audit_row();

alter table public.store_issues enable row level security;
alter table public.store_issue_lines enable row level security;
alter table public.replacement_dispatches enable row level security;
alter table public.replacement_dispatch_lines enable row level security;

revoke all on public.store_issues from anon, authenticated;
revoke all on public.store_issue_lines from anon, authenticated;
revoke all on public.replacement_dispatches from anon, authenticated;
revoke all on public.replacement_dispatch_lines from anon, authenticated;

grant select, insert, update on public.store_issues to rms_api;
grant select, insert, delete on public.store_issue_lines to rms_api;
grant select, insert, update on public.replacement_dispatches to rms_api;
grant select, insert, delete on public.replacement_dispatch_lines to rms_api;

grant all on public.store_issues to service_role;
grant all on public.store_issue_lines to service_role;
grant all on public.replacement_dispatches to service_role;
grant all on public.replacement_dispatch_lines to service_role;

-- ===========================================================================
-- 4. Settings
-- ===========================================================================
insert into public.system_settings (key, value, category, description, source_ref) values
  ('main_store_auto_acknowledge', 'true'::jsonb, 'inventory',
   'When true, store issues to Main Store are auto-acknowledged into MAIN_STORE location (DEC-21). When false, requires explicit MAIN_STORE role acknowledgement.',
   'DEC-21'),
  ('dispatch_roles', '["DISPATCH"]'::jsonb, 'dispatch',
   'Roles authorized to create and record replacement dispatches. Super Admin always may.',
   'DEC-26')
on conflict (key) do nothing;
