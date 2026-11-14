-- =============================================================================
-- Migration: 20261104000300_p3_03_dismantling.sql
-- Description: Stage-4 Dismantling & Parts Recovery (BR-26..BR-29, G-11, DEC-18, DEC-19, DEC-11)
-- =============================================================================

-- 1. Update rms_private.rms_move_stock to allow p_to is null for DISMANTLE_IN
create or replace function rms_private.rms_move_stock(
  p_lot         uuid,
  p_from        uuid,
  p_to          uuid,
  p_qty         integer,
  p_type        text,
  p_ref_type    text,
  p_ref_id      uuid,
  p_idem_key    text,
  p_actor       uuid default null,
  p_reason      text default null
) returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_existing_id     uuid;
  v_existing_lot    uuid;
  v_existing_from   uuid;
  v_existing_to     uuid;
  v_existing_qty    integer;
  v_existing_type   text;
  v_lot             record;
  v_to_loc          record;
  v_current_balance integer;
  v_movement_id     uuid;
begin
  -- 1. Idempotency Check
  if p_idem_key is not null and btrim(p_idem_key) <> '' then
    select id, lot_id, from_location_id, to_location_id, qty, movement_type
      into v_existing_id, v_existing_lot, v_existing_from, v_existing_to, v_existing_qty, v_existing_type
      from public.stock_movements
     where idempotency_key = p_idem_key;

    if found then
      if v_existing_lot = p_lot
         and v_existing_from is not distinct from p_from
         and v_existing_to is not distinct from p_to
         and v_existing_qty = p_qty
         and v_existing_type = p_type then
        return v_existing_id;
      else
        raise exception 'G-16: Idempotency conflict for stock movement key %', p_idem_key using errcode = 'P0001';
      end if;
    end if;
  else
    raise exception 'G-16: Idempotency key is required for stock movements' using errcode = 'P0001';
  end if;

  -- 2. Basic Parameter Validation
  if p_lot is null then
    raise exception 'Lot ID cannot be null' using errcode = 'P0001';
  end if;

  if p_qty is null or p_qty <= 0 then
    raise exception 'G-16: Movement quantity must be greater than zero' using errcode = 'P0001';
  end if;

  if p_from is null and p_to is null then
    raise exception 'Source and destination locations cannot both be null' using errcode = 'P0001';
  end if;

  if p_from is not null and p_to is not null and p_from = p_to then
    raise exception 'Source and destination locations cannot be the same' using errcode = 'P0001';
  end if;

  if p_from is null and p_type not in ('INWARD','RECEIPT','ADJUST','RECLASSIFY') then
    raise exception 'Source location is required for movement type %', p_type using errcode = 'P0001';
  end if;

  -- Allow DISMANTLE_IN when consuming units from non-functional store
  if p_to is null and p_type not in ('CONSUME','DISPOSE','DISPATCH','ADJUST','RECLASSIFY','DISMANTLE_IN') then
    raise exception 'Destination location is required for movement type %', p_type using errcode = 'P0001';
  end if;

  -- 3. Fetch lot details
  select * into v_lot from public.stock_lots where id = p_lot;
  if not found then
    raise exception 'Stock lot % not found', p_lot using errcode = 'P0001';
  end if;

  -- 4. Location Class Rules & System Guards
  if p_to is not null then
    select * into v_to_loc from public.inventory_locations where id = p_to;
    if not found then
      raise exception 'Destination location % not found', p_to using errcode = 'P0001';
    end if;

    -- Guard G-04: lot.condition_class IN (NOT_ALLOWED, HAZARD, NON_GOOD, NON_SELLABLE, SCRAP)
    -- cannot move to location_class in (FUNCTIONAL, MAIN_STORE, DISPATCHED)
    if v_lot.condition_class in ('NOT_ALLOWED','HAZARD','NON_GOOD','NON_SELLABLE','SCRAP')
       and v_to_loc.location_class in ('FUNCTIONAL','MAIN_STORE','DISPATCHED') then
      raise exception 'G-04: Lot condition % cannot move to % location', v_lot.condition_class, v_to_loc.location_class using errcode = 'P0001';
    end if;

    -- Guard G-05: HAZARD lots can only go to HAZARD_QUARANTINE or SCRAP_DISPOSED
    if v_lot.condition_class = 'HAZARD'
       and v_to_loc.location_class not in ('HAZARD_QUARANTINE','SCRAP_DISPOSED') then
      raise exception 'G-05: HAZARD lots can only move to HAZARD_QUARANTINE or SCRAP_DISPOSED (target was %)', v_to_loc.location_class using errcode = 'P0001';
    end if;

    -- Guard G-12: FUNCTIONAL locations accept only AS_RECEIVED (allowed conditions), FUNCTIONAL_GOOD and FUNCTIONAL_REPAIRED lots
    if v_to_loc.location_class = 'FUNCTIONAL'
       and v_lot.condition_class not in ('AS_RECEIVED','FUNCTIONAL_GOOD','FUNCTIONAL_REPAIRED') then
      raise exception 'G-12: FUNCTIONAL locations accept only AS_RECEIVED, FUNCTIONAL_GOOD and FUNCTIONAL_REPAIRED lots (attempted %)', v_lot.condition_class using errcode = 'P0001';
    end if;

    -- Guard G-08: lots with is_pending=true cannot move to TRANSIT/FUNCTIONAL
    if v_lot.is_pending = true
       and v_to_loc.location_class in ('TRANSIT','FUNCTIONAL') then
      raise exception 'G-08: Lots marked Pending (BP) cannot move to TRANSIT or FUNCTIONAL locations' using errcode = 'P0001';
    end if;
  end if;

  -- 5. Deduct from Source Balance (with row-level lock)
  if p_from is not null then
    select qty into v_current_balance
      from public.stock_balances
     where lot_id = p_lot and location_id = p_from
       for update;

    if not found or v_current_balance < p_qty then
      raise exception 'G-16: Insufficient stock balance for lot % at location % (available %, requested %)', p_lot, p_from, coalesce(v_current_balance, 0), p_qty using errcode = 'P0001';
    end if;

    update public.stock_balances
       set qty = qty - p_qty,
           updated_at = now()
     where lot_id = p_lot and location_id = p_from;
  end if;

  -- 6. Credit Destination Balance
  if p_to is not null then
    insert into public.stock_balances (lot_id, location_id, qty, updated_at)
    values (p_lot, p_to, p_qty, now())
    on conflict (lot_id, location_id)
    do update set qty = public.stock_balances.qty + excluded.qty, updated_at = now();
  end if;

  -- 7. Insert Movement Record
  insert into public.stock_movements (
    lot_id, from_location_id, to_location_id, qty, movement_type,
    reference_type, reference_id, idempotency_key, reason, created_by, created_at
  ) values (
    p_lot, p_from, p_to, p_qty, p_type,
    p_ref_type, p_ref_id, p_idem_key, p_reason, coalesce(p_actor, rms_private.current_actor()), now()
  ) returning id into v_movement_id;

  return v_movement_id;
end;
$$;

revoke execute on function rms_private.rms_move_stock(uuid, uuid, uuid, integer, text, text, uuid, text, uuid, text) from public, anon, authenticated;
grant execute on function rms_private.rms_move_stock(uuid, uuid, uuid, integer, text, text, uuid, text, uuid, text) to service_role, rms_api;

-- 2. Seed initial parts storage containers and partitions (DD r61–r62, BR-28)
do $$
declare
  v_sp_store_id uuid;
  v_multi_cont_id uuid;
begin
  select id into v_sp_store_id from public.inventory_locations where code = 'SPARE_PARTS_STORE';

  -- Dedicated parts containers (one for each part type)
  insert into public.storage_containers (code, barcode, name, container_type, storage_method, dedicated_part_type, location_id, is_active)
  values
    ('CONT-PARTS-TIP-01',  'CONT-PARTS-TIP-01',  'Dedicated Parts Container - TIP',  'PARTS', 'DEDICATED_CONTAINERS', 'TIP',  v_sp_store_id, true),
    ('CONT-PARTS-BODY-01', 'CONT-PARTS-BODY-01', 'Dedicated Parts Container - BODY', 'PARTS', 'DEDICATED_CONTAINERS', 'BODY', v_sp_store_id, true),
    ('CONT-PARTS-WIRE-01', 'CONT-PARTS-WIRE-01', 'Dedicated Parts Container - WIRE', 'PARTS', 'DEDICATED_CONTAINERS', 'WIRE', v_sp_store_id, true),
    ('CONT-PARTS-PCB-01',  'CONT-PARTS-PCB-01',  'Dedicated Parts Container - PCB',  'PARTS', 'DEDICATED_CONTAINERS', 'PCB',  v_sp_store_id, true)
  on conflict (code) do nothing;

  -- Partitioned parts container
  insert into public.storage_containers (code, barcode, name, container_type, storage_method, dedicated_part_type, location_id, is_active)
  values
    ('CONT-PARTS-MULTI-01', 'CONT-PARTS-MULTI-01', 'Partitioned Parts Bin 01', 'PARTS', 'PARTITIONED_CONTAINER', null, v_sp_store_id, true)
  on conflict (code) do nothing
  returning id into v_multi_cont_id;

  if v_multi_cont_id is null then
    select id into v_multi_cont_id from public.storage_containers where code = 'CONT-PARTS-MULTI-01';
  end if;

  -- Partitions for the multi-container
  if v_multi_cont_id is not null then
    insert into public.container_partitions (container_id, compartment_code, part_type, is_active)
    values
      (v_multi_cont_id, 'COMP-TIP-A1',  'TIP',  true),
      (v_multi_cont_id, 'COMP-BODY-B1', 'BODY', true),
      (v_multi_cont_id, 'COMP-WIRE-C1', 'WIRE', true),
      (v_multi_cont_id, 'COMP-PCB-D1',  'PCB',  true)
    on conflict (container_id, compartment_code) do nothing;
  end if;
end $$;

-- 3. Seed initial PCB Suppliers and Models
do $$
declare
  v_sup_alpha uuid;
  v_sup_beta  uuid;
begin
  insert into public.pcb_suppliers (name, is_active)
  values ('Alpha Microelectronics Ltd', true)
  on conflict (name) do nothing
  returning id into v_sup_alpha;

  if v_sup_alpha is null then
    select id into v_sup_alpha from public.pcb_suppliers where name = 'Alpha Microelectronics Ltd';
  end if;

  insert into public.pcb_suppliers (name, is_active)
  values ('Beta Tech Components', true)
  on conflict (name) do nothing
  returning id into v_sup_beta;

  if v_sup_beta is null then
    select id into v_sup_beta from public.pcb_suppliers where name = 'Beta Tech Components';
  end if;

  if v_sup_alpha is not null then
    insert into public.pcb_models (name, supplier_id, is_active)
    values ('DMT-PCB-V1', v_sup_alpha, true)
    on conflict (name) do nothing;
  end if;

  if v_sup_beta is not null then
    insert into public.pcb_models (name, supplier_id, is_active)
    values ('DMT-PCB-V2', v_sup_beta, true)
    on conflict (name) do nothing;
  end if;
end $$;

-- 4. Create dismantle_batches table
create table if not exists public.dismantle_batches (
  id                     uuid primary key default gen_random_uuid(),
  batch_no               text not null unique check (btrim(batch_no) <> ''),
  technician_profile_id   uuid not null references public.profiles (id) on delete restrict,
  storage_method_code    text not null check (storage_method_code in ('DEDICATED_CONTAINERS', 'PARTITIONED_CONTAINER')),
  status                 text not null check (status in ('OPEN', 'COMPLETED', 'CANCELLED')) default 'OPEN',
  total_input_qty        integer not null default 0 check (total_input_qty >= 0),
  total_dismantled_qty   integer not null default 0 check (total_dismantled_qty >= 0),
  created_at             timestamptz not null default now(),
  created_by             uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at             timestamptz not null default now(),
  completed_at           timestamptz
);

create index if not exists dismantle_batches_status_idx on public.dismantle_batches (status);
create index if not exists dismantle_batches_tech_idx on public.dismantle_batches (technician_profile_id);

-- 5. Create dismantle_inputs table
create table if not exists public.dismantle_inputs (
  id                 uuid primary key default gen_random_uuid(),
  batch_id           uuid not null references public.dismantle_batches (id) on delete cascade,
  lot_id             uuid not null references public.stock_lots (id) on delete restrict,
  qty                integer not null check (qty > 0),
  stock_movement_id  uuid references public.stock_movements (id) on delete set null,
  created_at         timestamptz not null default now(),
  created_by         uuid default rms_private.current_actor() references public.profiles (id) on delete restrict
);

create index if not exists dismantle_inputs_batch_idx on public.dismantle_inputs (batch_id);
create index if not exists dismantle_inputs_lot_idx on public.dismantle_inputs (lot_id);

-- 6. Create recovered_parts table with G-11 constraint
create table if not exists public.recovered_parts (
  id                 uuid primary key default gen_random_uuid(),
  batch_id           uuid not null references public.dismantle_batches (id) on delete cascade,
  part_type          text not null check (part_type in ('TIP', 'BODY', 'WIRE', 'PCB')),
  qty                integer not null check (qty >= 0),
  pcb_model_id       uuid references public.pcb_models (id) on delete restrict,
  pcb_supplier_id    uuid references public.pcb_suppliers (id) on delete restrict,
  container_id       uuid references public.storage_containers (id) on delete set null,
  partition_id       uuid references public.container_partitions (id) on delete set null,
  lot_id             uuid references public.stock_lots (id) on delete restrict,
  stock_movement_id  uuid references public.stock_movements (id) on delete set null,
  created_at         timestamptz not null default now(),
  created_by         uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,

  -- G-11: PCB rows require both PCB model and supplier (DB CHECK)
  constraint recovered_parts_pcb_guard check (
    part_type <> 'PCB' or (pcb_model_id is not null and pcb_supplier_id is not null)
  ),
  -- Must have container or partition reference
  constraint recovered_parts_storage_ref check (
    container_id is not null or partition_id is not null
  )
);

create index if not exists recovered_parts_batch_idx on public.recovered_parts (batch_id);
create index if not exists recovered_parts_type_idx on public.recovered_parts (part_type);
create index if not exists recovered_parts_lot_idx on public.recovered_parts (lot_id);

-- 7. Create scrap_records table with DEC-11 constraint
create table if not exists public.scrap_records (
  id                 uuid primary key default gen_random_uuid(),
  batch_id           uuid references public.dismantle_batches (id) on delete cascade,
  lot_id             uuid references public.stock_lots (id) on delete set null,
  qty_pieces         integer not null check (qty_pieces >= 0),
  weight_kg          numeric(8, 3) check (weight_kg is null or weight_kg >= 0),
  hazardous          boolean not null default false,
  remarks            text,
  disposal_status    text not null check (disposal_status in ('MARKED', 'DISPOSED')) default 'MARKED',
  manifest_ref       text,
  disposed_at        timestamptz,
  disposed_by        uuid references public.profiles (id) on delete set null,
  stock_movement_id  uuid references public.stock_movements (id) on delete set null,
  created_at         timestamptz not null default now(),
  created_by         uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,

  -- DEC-11: Hazardous scrap requires a manifest reference when disposed
  constraint scrap_records_hazardous_manifest check (
    disposal_status <> 'DISPOSED' or (not hazardous or manifest_ref is not null)
  )
);

create index if not exists scrap_records_batch_idx on public.scrap_records (batch_id);
create index if not exists scrap_records_status_idx on public.scrap_records (disposal_status);

-- 8. Audit and updated_at Triggers (Trigger name must be 'audit_row' per 03_audit.test.sql)
drop trigger if exists audit_row on public.dismantle_batches;
create trigger audit_row
  after insert or update or delete on public.dismantle_batches
  for each row execute function rms_private.audit_row();

drop trigger if exists set_updated_at on public.dismantle_batches;
create trigger set_updated_at
  before update on public.dismantle_batches
  for each row execute function rms_private.set_updated_at();

drop trigger if exists audit_row on public.dismantle_inputs;
create trigger audit_row
  after insert or update or delete on public.dismantle_inputs
  for each row execute function rms_private.audit_row();

drop trigger if exists audit_row on public.recovered_parts;
create trigger audit_row
  after insert or update or delete on public.recovered_parts
  for each row execute function rms_private.audit_row();

drop trigger if exists audit_row on public.scrap_records;
create trigger audit_row
  after insert or update or delete on public.scrap_records
  for each row execute function rms_private.audit_row();

-- 9. RLS & Permissions: strictly service_role and rms_api (anon and authenticated have no table access)
alter table public.dismantle_batches enable row level security;
alter table public.dismantle_inputs enable row level security;
alter table public.recovered_parts enable row level security;
alter table public.scrap_records enable row level security;

revoke all on public.dismantle_batches from anon, authenticated;
revoke all on public.dismantle_inputs from anon, authenticated;
revoke all on public.recovered_parts from anon, authenticated;
revoke all on public.scrap_records from anon, authenticated;

grant all on public.dismantle_batches to service_role, rms_api;
grant all on public.dismantle_inputs to service_role, rms_api;
grant all on public.recovered_parts to service_role, rms_api;
grant all on public.scrap_records to service_role, rms_api;
