-- P1-02 · 0003 — master data (master plan §8.2).
-- Masters are soft-deactivated (is_active) and referenced with ON DELETE RESTRICT.

-- ---------------------------------------------------------------------------
-- product_categories (DMT / PRISMATIC / ENCLOSED_OVAL; flags drive DEC-15, DEC-18, BR-14)
-- condition_option_set_id FK is added in the config migration (option_sets defined there).
-- ---------------------------------------------------------------------------
create table public.product_categories (
  id                       uuid primary key default gen_random_uuid(),
  code                     text not null unique check (code ~ '^[A-Z][A-Z0-9_]*$'),
  name                     text not null check (btrim(name) <> ''),
  requires_full_opening    boolean not null default false,  -- BR-14 / G-06 (EO)
  supports_battery         boolean not null default false,  -- DEC-15 (DMT)
  supports_dismantling     boolean not null default false,  -- DEC-18 (DMT)
  hazard_capable           boolean not null default false,  -- G-05 (PRISMATIC, EO)
  condition_option_set_id  uuid,
  is_active                boolean not null default true,
  created_at               timestamptz not null default now(),
  created_by               uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at               timestamptz not null default now()
);

create table public.products (
  id           uuid primary key default gen_random_uuid(),
  code         text not null unique check (btrim(code) <> ''),
  name         text not null check (btrim(name) <> ''),
  category_id  uuid not null references public.product_categories (id) on delete restrict,
  uom          text not null default 'PCS' check (btrim(uom) <> ''),
  hsn_code     text check (hsn_code is null or hsn_code ~ '^[0-9]{4,8}$'),
  is_active    boolean not null default true,
  created_at   timestamptz not null default now(),
  created_by   uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at   timestamptz not null default now()
);
create index products_category_idx on public.products (category_id);
create index products_name_trgm_idx on public.products using gin (name extensions.gin_trgm_ops);

-- ---------------------------------------------------------------------------
-- states / stations (DEC-02)
-- ---------------------------------------------------------------------------
create table public.states (
  id          uuid primary key default gen_random_uuid(),
  code        text unique check (code is null or btrim(code) <> ''),
  name        text not null unique check (btrim(name) <> ''),
  is_active   boolean not null default true,
  created_at  timestamptz not null default now(),
  created_by  uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at  timestamptz not null default now()
);

create table public.stations (
  id          uuid primary key default gen_random_uuid(),
  state_id    uuid not null references public.states (id) on delete restrict,
  name        text not null check (btrim(name) <> ''),
  is_active   boolean not null default true,
  created_at  timestamptz not null default now(),
  created_by  uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at  timestamptz not null default now(),
  unique (state_id, name)
);

-- ---------------------------------------------------------------------------
-- parties (GSTIN format: 2-digit state + PAN (5 letters, 4 digits, 1 letter) + entity + 'Z' + check)
-- ---------------------------------------------------------------------------
create table public.parties (
  id              uuid primary key default gen_random_uuid(),
  code            text not null unique check (btrim(code) <> ''),
  name            text not null check (btrim(name) <> ''),
  gstin           text check (gstin is null or gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),
  state_id        uuid references public.states (id) on delete restrict,
  station_id      uuid references public.stations (id) on delete restrict,
  contact_name    text,
  phone           text,
  email           extensions.citext,
  is_provisional  boolean not null default false,   -- DEC-02: created at the gate, reviewed later
  is_active       boolean not null default true,
  created_at      timestamptz not null default now(),
  created_by      uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at      timestamptz not null default now()
);
create index parties_state_idx on public.parties (state_id);
create index parties_station_idx on public.parties (station_id);
create index parties_name_trgm_idx on public.parties using gin (name extensions.gin_trgm_ops);

create table public.transporters (
  id          uuid primary key default gen_random_uuid(),
  name        text not null unique check (btrim(name) <> ''),
  type        text,
  phone       text,
  is_active   boolean not null default true,
  created_at  timestamptz not null default now(),
  created_by  uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at  timestamptz not null default now()
);

-- DD r47 "Assigned Technician" is sourced from this master.
create table public.technicians (
  id            uuid primary key default gen_random_uuid(),
  profile_id    uuid unique references public.profiles (id) on delete restrict,
  display_name  text not null unique check (btrim(display_name) <> ''),
  is_active     boolean not null default true,
  created_at    timestamptz not null default now(),
  created_by    uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at    timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- inventory_locations: every custody holder (§6.1 point 4, §8.2)
-- ---------------------------------------------------------------------------
create table public.inventory_locations (
  id                  uuid primary key default gen_random_uuid(),
  code                text not null unique check (code ~ '^[A-Z][A-Z0-9_]*$'),
  name                text not null check (btrim(name) <> ''),
  location_class      text not null check (location_class in (
                        'INWARD','TRANSIT','FUNCTIONAL','TECHNICIAN','NON_FUNCTIONAL','SPARE_PARTS',
                        'REJECTED_HOLD','HAZARD_QUARANTINE','MAIN_STORE','DISPATCHED',
                        'SCRAP_DISPOSED','CREDITED','PENDING_HOLD')),
  custodian_role_id   uuid references public.roles (id) on delete restrict,
  custodian_user_id   uuid references public.profiles (id) on delete restrict,
  department_id       uuid references public.departments (id) on delete restrict,
  parent_location_id  uuid references public.inventory_locations (id) on delete restrict,
  is_active           boolean not null default true,
  created_at          timestamptz not null default now(),
  created_by          uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at          timestamptz not null default now(),
  check (parent_location_id is null or parent_location_id <> id)
);
create index inventory_locations_class_idx on public.inventory_locations (location_class);

-- ---------------------------------------------------------------------------
-- Containers & partitions (DD r57–62, BR-28)
-- ---------------------------------------------------------------------------
create table public.storage_containers (
  id                   uuid primary key default gen_random_uuid(),
  code                 text not null unique check (btrim(code) <> ''),
  barcode              text not null unique check (btrim(barcode) <> ''),
  name                 text,
  container_type       text not null check (container_type in ('DMT_RETURN','PARTS')),
  storage_method       text check (storage_method in ('DEDICATED_CONTAINERS','PARTITIONED_CONTAINER')),
  location_id          uuid references public.inventory_locations (id) on delete restrict,
  dedicated_part_type  text check (dedicated_part_type in ('TIP','BODY','WIRE','PCB')),
  is_active            boolean not null default true,
  created_at           timestamptz not null default now(),
  created_by           uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at           timestamptz not null default now(),
  -- a parts container declares how it stores parts; a dedicated part type only on dedicated ones
  check (container_type <> 'PARTS' or storage_method is not null),
  check (dedicated_part_type is null or storage_method = 'DEDICATED_CONTAINERS')
);
create index storage_containers_location_idx on public.storage_containers (location_id);

create table public.container_partitions (
  id                uuid primary key default gen_random_uuid(),
  container_id      uuid not null references public.storage_containers (id) on delete restrict,
  compartment_code  text not null check (btrim(compartment_code) <> ''),
  part_type         text check (part_type in ('TIP','BODY','WIRE','PCB')),
  is_active         boolean not null default true,
  created_at        timestamptz not null default now(),
  created_by        uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at        timestamptz not null default now(),
  unique (container_id, compartment_code)
);

-- ---------------------------------------------------------------------------
-- Smaller masters
-- ---------------------------------------------------------------------------
create table public.rejection_reasons (
  id                      uuid primary key default gen_random_uuid(),
  code                    text not null unique check (code ~ '^[A-Z][A-Z0-9_]*$'),
  label                   text not null check (btrim(label) <> ''),
  applies_to_category_id  uuid references public.product_categories (id) on delete restrict,
  is_active               boolean not null default true,
  created_at              timestamptz not null default now(),
  created_by              uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at              timestamptz not null default now()
);

create table public.battery_types (
  id          uuid primary key default gen_random_uuid(),
  code        text not null unique check (btrim(code) <> ''),
  name        text not null check (btrim(name) <> ''),
  is_active   boolean not null default true,
  created_at  timestamptz not null default now(),
  created_by  uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at  timestamptz not null default now()
);

create table public.pcb_suppliers (
  id          uuid primary key default gen_random_uuid(),
  name        text not null unique check (btrim(name) <> ''),
  is_active   boolean not null default true,
  created_at  timestamptz not null default now(),
  created_by  uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at  timestamptz not null default now()
);

create table public.pcb_models (
  id           uuid primary key default gen_random_uuid(),
  name         text not null unique check (btrim(name) <> ''),
  supplier_id  uuid references public.pcb_suppliers (id) on delete restrict,
  is_active    boolean not null default true,
  created_at   timestamptz not null default now(),
  created_by   uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at   timestamptz not null default now()
);
