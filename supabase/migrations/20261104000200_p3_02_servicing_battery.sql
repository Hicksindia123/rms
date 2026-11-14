-- P3-02 · Technician allotment & receiving, battery inventory & consumption, cleaning & classification
-- Master plan §2.2 (Stage-3), §3.2 DD r47–r56, BR-23..BR-25, G-10, DEC-14..DEC-17, DEC-34.

-- ===========================================================================
-- 1. Ensure BATTERY_STORE inventory location exists (DEC-15)
-- ===========================================================================
insert into public.inventory_locations (code, name, location_class, custodian_role_id, department_id)
select 'BATTERY_STORE', 'Battery Store', 'SPARE_PARTS',
       (select id from public.roles where code = 'SPARE_PARTS_MANAGER'),
       (select id from public.departments where code = 'REPLACEMENT_DEPT')
on conflict (code) do nothing;

-- ===========================================================================
-- 2. Make stock_lots.gs_id nullable for general spare parts / batteries
-- ===========================================================================
alter table public.stock_lots alter column gs_id drop not null;

-- ===========================================================================
-- 3. Seed common battery types if not present
-- ===========================================================================
insert into public.battery_types (code, name) values
  ('LR44', 'LR44 Button Cell'),
  ('CR2032', 'CR2032 Lithium Coin Cell'),
  ('AAA', 'AAA Alkaline 1.5V'),
  ('AA', 'AA Alkaline 1.5V')
on conflict (code) do nothing;

-- ===========================================================================
-- 4. Seed NON_SELLABLE in POST_SERVICING_CLASSIFICATION option set (DEC-17)
-- ===========================================================================
insert into public.option_items (option_set_id, code, label, allowed_status, rule_text, next_action_text, remarks, system_behavior, required_fields, sort_order, source_ref)
select os.id, 'NON_SELLABLE', 'Non-Sellable Stock', 'YES',
       'Permanent scratches make piece non-sellable; route to Spare Parts Manager',
       'Route to Spare Parts Manager non-functional store', 'DEC-17 cosmetic reject', null, '[]'::jsonb, 40, 'DD r53'
from public.option_sets os
where os.code = 'POST_SERVICING_CLASSIFICATION'
on conflict (option_set_id, code) do nothing;

-- ===========================================================================
-- 5. Battery receipts & adjustments tables
-- ===========================================================================
create table public.battery_receipts (
  id                uuid primary key default gen_random_uuid(),
  battery_type_id   uuid not null references public.battery_types (id) on delete restrict,
  qty               integer not null check (qty > 0),
  reference_no      text not null check (btrim(reference_no) <> ''),
  received_by       uuid not null references public.profiles (id) on delete restrict,
  received_at       timestamptz not null default now(),
  stock_movement_id uuid references public.stock_movements (id) on delete restrict,
  notes             text,
  created_at        timestamptz not null default now()
);

create index battery_receipts_type_idx on public.battery_receipts (battery_type_id);
create index battery_receipts_by_idx on public.battery_receipts (received_by);
create index battery_receipts_at_idx on public.battery_receipts (received_at desc);

create table public.battery_adjustments (
  id                uuid primary key default gen_random_uuid(),
  battery_type_id   uuid not null references public.battery_types (id) on delete restrict,
  qty               integer not null check (qty <> 0),
  reason            text not null check (btrim(reason) <> ''),
  status            text not null check (status in ('PENDING', 'APPROVED', 'REJECTED')) default 'PENDING',
  requested_by      uuid not null references public.profiles (id) on delete restrict,
  requested_at      timestamptz not null default now(),
  approved_by       uuid references public.profiles (id) on delete restrict,
  approved_at       timestamptz,
  approval_notes    text,
  stock_movement_id uuid references public.stock_movements (id) on delete restrict,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index battery_adjustments_type_idx on public.battery_adjustments (battery_type_id);
create index battery_adjustments_status_idx on public.battery_adjustments (status);

-- ===========================================================================
-- 6. Technician batches and lines tables
-- ===========================================================================
create table public.technician_batches (
  id              uuid primary key default gen_random_uuid(),
  batch_no        text not null unique check (btrim(batch_no) <> ''),
  technician_id   uuid not null references public.technicians (id) on delete restrict,
  entry_by        uuid not null references public.profiles (id) on delete restrict,
  status          text not null check (status in ('ALLOTTED', 'IN_PROGRESS', 'PARTIALLY_RECEIVED', 'COMPLETED', 'CANCELLED')) default 'ALLOTTED',
  transfer_id     uuid references public.custody_transfers (id) on delete restrict,
  allotted_at     timestamptz not null default now(),
  completed_at    timestamptz,
  notes           text,
  created_at      timestamptz not null default now(),
  created_by      uuid references public.profiles (id) on delete set null,
  updated_at      timestamptz not null default now()
);

create index technician_batches_tech_idx on public.technician_batches (technician_id);
create index technician_batches_entry_idx on public.technician_batches (entry_by);
create index technician_batches_status_idx on public.technician_batches (status);
create index technician_batches_created_at_idx on public.technician_batches (created_at desc);

create table public.technician_batch_lines (
  id                   uuid primary key default gen_random_uuid(),
  batch_id             uuid not null references public.technician_batches (id) on delete cascade,
  lot_id               uuid not null references public.stock_lots (id) on delete restrict,
  qty_allotted         integer not null check (qty_allotted > 0),
  qty_received         integer not null check (qty_received >= 0) default 0,
  status               text not null check (status in ('PENDING', 'PARTIALLY_RECEIVED', 'RECEIVED')) default 'PENDING',
  requires_evaluation  boolean not null default false,
  evaluation_notes     text,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  check (qty_received <= qty_allotted)
);

create index technician_batch_lines_batch_idx on public.technician_batch_lines (batch_id);
create index technician_batch_lines_lot_idx on public.technician_batch_lines (lot_id);

-- ===========================================================================
-- 7. Technician receiving records (with G-10 and DEC-17 DB constraints)
-- ===========================================================================
create table public.technician_receiving_records (
  id                        uuid primary key default gen_random_uuid(),
  batch_id                  uuid not null references public.technician_batches (id) on delete cascade,
  batch_line_id             uuid not null references public.technician_batch_lines (id) on delete cascade,
  qty_received              integer not null check (qty_received > 0),
  battery_check_code        text check (battery_check_code in ('BATTERY_OK', 'BATTERY_REPLACED') or battery_check_code is null),
  pieces_checked            integer check (pieces_checked >= 0 or pieces_checked is null),
  batteries_installed       integer check (batteries_installed >= 0 or batteries_installed is null),
  battery_type_id           uuid references public.battery_types (id) on delete restrict,
  cleaning_code             text check (cleaning_code in ('CLEANED_SELLABLE', 'PERMANENT_SCRATCHES') or cleaning_code is null),
  functional_good_qty       integer not null check (functional_good_qty >= 0) default 0,
  functional_repaired_qty   integer not null check (functional_repaired_qty >= 0) default 0,
  non_good_qty              integer not null check (non_good_qty >= 0) default 0,
  non_sellable_qty          integer not null check (non_sellable_qty >= 0) default 0,
  evaluation_notes          text,
  technician_remarks        text,
  entry_by                  uuid not null references public.profiles (id) on delete restrict,
  received_at               timestamptz not null default now(),
  battery_stock_movement_id uuid references public.stock_movements (id) on delete restrict,
  functional_transfer_id    uuid references public.custody_transfers (id) on delete restrict,
  non_good_transfer_id      uuid references public.custody_transfers (id) on delete restrict,
  non_sellable_transfer_id  uuid references public.custody_transfers (id) on delete restrict,
  idempotency_key           text unique,
  created_at                timestamptz not null default now(),
  -- Total classification allocation equals qty_received
  check (functional_good_qty + functional_repaired_qty + non_good_qty + non_sellable_qty = qty_received),
  -- System Guard G-10: BATTERY_REPLACED requires pieces_checked > 0 and batteries_installed > 0 and battery_type_id
  constraint g10_battery_counts_check check (
    (battery_check_code = 'BATTERY_REPLACED' and pieces_checked > 0 and batteries_installed > 0 and battery_type_id is not null)
    or
    (battery_check_code = 'BATTERY_OK' and pieces_checked > 0 and coalesce(batteries_installed, 0) = 0)
    or
    (battery_check_code is null)
  ),
  -- DEC-17 / BR-25: Permanent scratches forces NON_SELLABLE
  constraint dec17_permanent_scratches_check check (
    cleaning_code <> 'PERMANENT_SCRATCHES'
    or
    (non_sellable_qty = qty_received and functional_good_qty = 0 and functional_repaired_qty = 0 and non_good_qty = 0)
  )
);

create index technician_receiving_records_batch_idx on public.technician_receiving_records (batch_id);
create index technician_receiving_records_line_idx on public.technician_receiving_records (batch_line_id);
create index technician_receiving_records_at_idx on public.technician_receiving_records (received_at desc);

-- ===========================================================================
-- 8. Custody transfers: add accepted_on_behalf_of & update G-09 trigger for DEC-34
-- ===========================================================================
alter table public.custody_transfers
  add column accepted_on_behalf_of text;

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
    if coalesce(new.purpose_code, '') not in ('TECHNICIAN_ALLOTMENT', 'TECHNICIAN_RECEIVING') then
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

-- Trigger functions are never callable by API clients (P1-02 convention, pgTAP 01_schema).
revoke all on function rms_private.custody_transfers_g09_guard() from public, anon, authenticated;

-- ===========================================================================
-- 9. Audit and Updated-At Triggers (G-17, BR-40, 03_audit.test.sql)
-- ===========================================================================
create trigger audit_row
  after insert or update or delete on public.battery_receipts
  for each row execute function rms_private.audit_row();

create trigger audit_row
  after insert or update or delete on public.battery_adjustments
  for each row execute function rms_private.audit_row();

create trigger set_updated_at
  before update on public.battery_adjustments
  for each row execute function rms_private.set_updated_at();

create trigger audit_row
  after insert or update or delete on public.technician_batches
  for each row execute function rms_private.audit_row();

create trigger set_updated_at
  before update on public.technician_batches
  for each row execute function rms_private.set_updated_at();

create trigger audit_row
  after insert or update or delete on public.technician_batch_lines
  for each row execute function rms_private.audit_row();

create trigger set_updated_at
  before update on public.technician_batch_lines
  for each row execute function rms_private.set_updated_at();

create trigger audit_row
  after insert or update or delete on public.technician_receiving_records
  for each row execute function rms_private.audit_row();

-- ===========================================================================
-- 10. Access Privileges (FastAPI backend uses rms_api; direct access by authenticated is revoked)
-- ===========================================================================
alter table public.battery_receipts enable row level security;
alter table public.battery_adjustments enable row level security;
alter table public.technician_batches enable row level security;
alter table public.technician_batch_lines enable row level security;
alter table public.technician_receiving_records enable row level security;

revoke all on public.battery_receipts from public, anon, authenticated;
revoke all on public.battery_adjustments from public, anon, authenticated;
revoke all on public.technician_batches from public, anon, authenticated;
revoke all on public.technician_batch_lines from public, anon, authenticated;
revoke all on public.technician_receiving_records from public, anon, authenticated;

grant select, insert on public.battery_receipts to rms_api;
grant select, insert, update on public.battery_adjustments to rms_api;
grant select, insert, update on public.technician_batches to rms_api;
grant select, insert, update on public.technician_batch_lines to rms_api;
grant select, insert on public.technician_receiving_records to rms_api;
