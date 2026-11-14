-- Change plan 2026-11-12 · Phase 4 — Admin Categorisation Engine: item field profiles
-- (docs/RMS_MASTER_PLAN_ADDENDUM_2026-11.md AMD-10, AMD-11, AMD-16; G-05; G-18; DEC-14; DEC-40; DEC-43).
--
-- 1. item_field_library: one library of admin-managed fields, partitioned by field_group:
--      CATEGORISATION  quantity buckets (Good, Damaged, Body Broken, Wastage, … ; AMD-09/10)
--      DEPARTMENT      routing destinations (Mercury Extraction, Repair, Cleaning, … ; AMD-10/14)
--      ACTION          final RM actions (SEND_NEW, SEND_REPAIRED, ISSUE_CN, NOT_ALLOWED, PENDING_BP; AMD-16)
--      ITEM_COUNT      per-item numeric counts that are NOT buckets (Packaging, Container,
--                      User Manual; AMD-11)
--    Codes (and the group) are immutable (rule e); labels, sort, active and flags are editable.
--    Rows are never deleted (no DELETE grant): deactivate instead, so history keeps resolving.
-- 2. item_field_assignments: field -> scope (CATEGORY | SUBCATEGORY | PRODUCT) with
--    include / exclude and sort order. Each scope column is a real FK.
-- 3. RESOLUTION RULE (AMD-10), per field group, for a product P (category C, sub-category S):
--      the most specific scope that has ANY assignment row for that group wins —
--      PRODUCT(P) overrides SUBCATEGORY(S) overrides CATEGORY(C); nothing at any level = no fields.
--      Within the winning scope the effective fields are the INCLUDED rows whose library entry is
--      active, ordered by assignment sort_order, then library sort_order, then code.
--      Excluded rows (is_included = false) never yield a field; they record a deliberate removal
--      and let an override yield an empty set while still blocking inheritance.
--      Groups resolve independently (a product may override Actions and inherit Departments).
--    rms_private.resolve_item_field_profile(...) is the ONLY implementation of this rule; the
--    backend calls it and never re-implements it.
-- 4. item_field_profile_versions (G-18 extended, AMD-10): every committed transaction that changes
--    the library or the assignments gets exactly one new, insert-only version holding a full
--    snapshot (deferred constraint trigger, fires once per transaction at commit). The resolver can
--    resolve against any historical version.
-- 5. goods_slips.item_field_profile_version_id: stamped when a GS leaves CATEGORISATION (the version
--    it was categorised under) and immutable afterwards (G-18).
-- 6. rm_item_actions: the hard CHECK on action_code is replaced by an FK to the ACTION library
--    (codes immutable), plus an action_label snapshot taken at insert (G-18). New rows must use an
--    active action.
-- 7. gs_item_counts (AMD-11): Packaging / Container / User Manual counts per GS item, only for
--    ITEM_COUNT fields enabled by the item's resolved profile, with label snapshots (G-18).
-- 8. Seeding: the condition options of each category (DMT/PRISMATIC/EO_CONDITION) become
--    CATEGORISATION entries assigned to that category; RM_ITEM_ACTION options become ACTION entries
--    assigned to every category; AMD-10 departments and AMD-11 counts are added to the library
--    unassigned (an admin enables them per scope). Shared function, re-run by seed.sql after the
--    option catalogue is loaded (migrations run before seed.sql on `supabase db reset`).

-- ===========================================================================
-- 1. Library
-- ===========================================================================
create table public.item_field_library (
  id                     uuid primary key default gen_random_uuid(),
  field_group            text not null
                         check (field_group in ('CATEGORISATION', 'DEPARTMENT', 'ACTION', 'ITEM_COUNT')),
  code                   text not null check (code ~ '^[A-Z][A-Z0-9_]*$'),
  label                  text not null check (btrim(label) <> ''),
  description            text,
  sort_order             integer not null default 0,
  is_active              boolean not null default true,
  -- Seeded from the workbook catalogue / referenced by code in business logic (informational).
  is_system              boolean not null default false,
  -- Flags. Their meaning is per group and enforced below:
  --   is_wastage          CATEGORISATION / DEPARTMENT: quantity booked here is wastage.
  --   returns_to_routing  CATEGORISATION / DEPARTMENT: quantity goes (back) to the RM routing
  --                       queue (DEC-43: no direct department-to-department hand-off).
  --   requires_cn         ACTION: Accounts must enter CN No./Date/Value (AMD-18).
  --   requires_challan    ACTION: Accounts must enter Challan No./Date (AMD-18).
  is_wastage             boolean not null default false,
  returns_to_routing     boolean not null default false,
  requires_cn            boolean not null default false,
  requires_challan       boolean not null default false,
  -- CATEGORISATION only: behaviour carried over from the condition option (G-05: HAZARD is locked).
  system_behavior        text check (system_behavior in (
                           'SELLABLE','REPACK_OR_TECHNICIAN','TO_TECHNICIAN','TO_SPARE_PARTS',
                           'REJECT_HOLD','REJECT_RECORD','HAZARD','SHORT_QTY')),
  source_option_item_id  uuid references public.option_items (id) on delete restrict,
  source_ref             text,
  created_at             timestamptz not null default now(),
  created_by             uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at             timestamptz not null default now(),
  constraint item_field_library_group_code_key unique (field_group, code),
  -- target of the composite FK from item_field_assignments (field must be of the stated group)
  constraint item_field_library_id_group_key unique (id, field_group),
  constraint item_field_library_action_flags_check
    check (field_group = 'ACTION' or (not requires_cn and not requires_challan)),
  constraint item_field_library_routing_flags_check
    check (field_group in ('CATEGORISATION', 'DEPARTMENT') or (not is_wastage and not returns_to_routing)),
  constraint item_field_library_behavior_check
    check (field_group = 'CATEGORISATION' or system_behavior is null)
);
-- Labels are not unique: the catalogue repeats them across categories (PRS_OK / EO_OK "VISUALLY OKAY").
create index item_field_library_group_sort_idx on public.item_field_library (field_group, sort_order);

comment on table public.item_field_library is
  'AMD-10/11: admin-managed item fields (CATEGORISATION buckets, DEPARTMENTs, ACTIONs, ITEM_COUNTs). Codes immutable.';

-- rule e / AMD-10: codes and groups are immutable; G-05: HAZARD behaviour is locked.
create or replace function rms_private.item_field_library_immutable()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.code is distinct from old.code then
    raise exception 'G-18: item field code % is immutable', old.code using errcode = '42501';
  end if;
  if new.field_group is distinct from old.field_group then
    raise exception 'G-18: item field % cannot move to another field group', old.code using errcode = '42501';
  end if;
  if old.system_behavior = 'HAZARD' and new.system_behavior is distinct from old.system_behavior then
    raise exception 'G-05: hazard behaviour of item field % is locked', old.code using errcode = '42501';
  end if;
  return new;
end
$$;
revoke all on function rms_private.item_field_library_immutable() from public;

create trigger item_field_library_immutable
  before update on public.item_field_library
  for each row execute function rms_private.item_field_library_immutable();

-- ===========================================================================
-- 2. Assignments (field -> scope)
-- ===========================================================================
create table public.item_field_assignments (
  id              uuid primary key default gen_random_uuid(),
  field_id        uuid not null,
  field_group     text not null,
  scope_type      text not null check (scope_type in ('CATEGORY', 'SUBCATEGORY', 'PRODUCT')),
  category_id     uuid references public.product_categories (id) on delete restrict,
  subcategory_id  uuid references public.product_subcategories (id) on delete restrict,
  product_id      uuid references public.products (id) on delete restrict,
  scope_id        uuid generated always as (coalesce(product_id, subcategory_id, category_id)) stored,
  is_included     boolean not null default true,
  sort_order      integer not null default 0,
  created_at      timestamptz not null default now(),
  created_by      uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at      timestamptz not null default now(),
  constraint item_field_assignments_field_fkey
    foreign key (field_id, field_group) references public.item_field_library (id, field_group)
    on update restrict on delete restrict,
  -- exactly the scope column that matches scope_type is set
  constraint item_field_assignments_scope_check check (
    (scope_type = 'CATEGORY'    and category_id is not null and subcategory_id is null and product_id is null)
 or (scope_type = 'SUBCATEGORY' and subcategory_id is not null and category_id is null and product_id is null)
 or (scope_type = 'PRODUCT'     and product_id is not null and category_id is null and subcategory_id is null)),
  constraint item_field_assignments_scope_field_key unique (scope_type, scope_id, field_id)
);
create index item_field_assignments_scope_group_idx
  on public.item_field_assignments (scope_type, scope_id, field_group);
create index item_field_assignments_field_idx on public.item_field_assignments (field_id);
create index item_field_assignments_category_idx on public.item_field_assignments (category_id);
create index item_field_assignments_subcategory_idx on public.item_field_assignments (subcategory_id);
create index item_field_assignments_product_idx on public.item_field_assignments (product_id);

comment on table public.item_field_assignments is
  'AMD-10: field -> scope assignments. Most specific scope with any row for a group wins (PRODUCT > SUBCATEGORY > CATEGORY).';

-- The field and the scope of an assignment never change (delete + insert instead), so the
-- version history reads as a clean list of overrides.
create or replace function rms_private.item_field_assignments_immutable_keys()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if (new.field_id, new.field_group, new.scope_type, new.category_id, new.subcategory_id, new.product_id)
     is distinct from
     (old.field_id, old.field_group, old.scope_type, old.category_id, old.subcategory_id, old.product_id) then
    raise exception 'G-18: the field and scope of an item field assignment are immutable (delete and re-add)'
      using errcode = '42501';
  end if;
  return new;
end
$$;
revoke all on function rms_private.item_field_assignments_immutable_keys() from public;

create trigger item_field_assignments_immutable_keys
  before update on public.item_field_assignments
  for each row execute function rms_private.item_field_assignments_immutable_keys();

-- ===========================================================================
-- 3. Versions (G-18 extended): one insert-only snapshot per changing transaction
-- ===========================================================================
create table public.item_field_profile_versions (
  id          uuid primary key default gen_random_uuid(),
  version_no  integer not null unique check (version_no > 0),
  txid        bigint not null unique,
  snapshot    jsonb not null check (jsonb_typeof(snapshot) = 'object'),
  created_at  timestamptz not null default now(),
  created_by  uuid default rms_private.current_actor() references public.profiles (id) on delete restrict
);
comment on table public.item_field_profile_versions is
  'G-18 / AMD-10: insert-only snapshots of the item field library + assignments; one per changing transaction.';

create trigger item_field_profile_versions_insert_only
  before update or delete on public.item_field_profile_versions
  for each row execute function rms_private.raise_insert_only();
create trigger item_field_profile_versions_no_truncate
  before truncate on public.item_field_profile_versions
  for each statement execute function rms_private.raise_insert_only();

create or replace function rms_private.item_field_profile_snapshot()
returns jsonb
language sql
stable
set search_path = ''
as $$
  select jsonb_build_object(
    'library', coalesce((
      select jsonb_agg(jsonb_build_object(
               'id', l.id, 'field_group', l.field_group, 'code', l.code, 'label', l.label,
               'sort_order', l.sort_order, 'is_active', l.is_active,
               'is_wastage', l.is_wastage, 'returns_to_routing', l.returns_to_routing,
               'requires_cn', l.requires_cn, 'requires_challan', l.requires_challan,
               'system_behavior', l.system_behavior)
             order by l.field_group, l.sort_order, l.code)
        from public.item_field_library l), '[]'::jsonb),
    'assignments', coalesce((
      select jsonb_agg(jsonb_build_object(
               'field_id', a.field_id, 'scope_type', a.scope_type, 'scope_id', a.scope_id,
               'is_included', a.is_included, 'sort_order', a.sort_order)
             order by a.scope_type, a.scope_id, a.sort_order, a.field_id)
        from public.item_field_assignments a), '[]'::jsonb));
$$;
revoke all on function rms_private.item_field_profile_snapshot() from public;
-- called by the deferred version trigger, which runs as the committing role (rms_api)
grant execute on function rms_private.item_field_profile_snapshot() to rms_api;

-- Deferred: runs at commit, after every statement of the transaction, so the first firing sees
-- the final state; later firings in the same transaction find the version and do nothing.
create or replace function rms_private.item_field_profile_bump_version()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_txid bigint := txid_current();
begin
  if exists (select 1 from public.item_field_profile_versions where txid = v_txid) then
    return null;
  end if;
  -- serialise version numbers across concurrent admin saves
  perform pg_advisory_xact_lock(hashtext('public.item_field_profile_versions'));
  insert into public.item_field_profile_versions (version_no, txid, snapshot)
  select coalesce(max(version_no), 0) + 1, v_txid, rms_private.item_field_profile_snapshot()
    from public.item_field_profile_versions;
  return null;
end
$$;
revoke all on function rms_private.item_field_profile_bump_version() from public;

create constraint trigger item_field_library_version
  after insert or update or delete on public.item_field_library
  deferrable initially deferred
  for each row execute function rms_private.item_field_profile_bump_version();
create constraint trigger item_field_assignments_version
  after insert or update or delete on public.item_field_assignments
  deferrable initially deferred
  for each row execute function rms_private.item_field_profile_bump_version();

-- ===========================================================================
-- 4. Resolver (the only implementation of the AMD-10 resolution rule)
-- ===========================================================================
-- Resolves the effective fields for a scope chain (category [, sub-category [, product]]).
-- p_version_id null = the live configuration (reported with the latest version number);
-- otherwise the snapshot of that version.
create or replace function rms_private.resolve_item_field_profile_for_scope(
  p_category_id     uuid,
  p_subcategory_id  uuid default null,
  p_product_id      uuid default null,
  p_version_id      uuid default null
)
returns table (
  profile_version_id  uuid,
  profile_version_no  integer,
  field_group         text,
  field_id            uuid,
  code                text,
  label               text,
  sort_order          integer,
  source_scope_type   text,
  source_scope_id     uuid,
  is_wastage          boolean,
  returns_to_routing  boolean,
  requires_cn         boolean,
  requires_challan    boolean,
  system_behavior     text
)
language plpgsql
stable
set search_path = ''
as $$
#variable_conflict use_column
declare
  v_ver_id  uuid;
  v_ver_no  integer;
  v_lib     jsonb;
  v_asg     jsonb;
begin
  if p_category_id is null then
    raise exception 'resolve_item_field_profile: category is required' using errcode = '22004';
  end if;

  if p_version_id is null then
    select v.id, v.version_no into v_ver_id, v_ver_no
      from public.item_field_profile_versions v order by v.version_no desc limit 1;
    select coalesce(jsonb_agg(jsonb_build_object(
             'id', l.id, 'field_group', l.field_group, 'code', l.code, 'label', l.label,
             'sort_order', l.sort_order, 'is_active', l.is_active,
             'is_wastage', l.is_wastage, 'returns_to_routing', l.returns_to_routing,
             'requires_cn', l.requires_cn, 'requires_challan', l.requires_challan,
             'system_behavior', l.system_behavior)), '[]'::jsonb)
      into v_lib
      from public.item_field_library l
     where l.id in (select a.field_id from public.item_field_assignments a
                     where (a.scope_type = 'CATEGORY' and a.category_id = p_category_id)
                        or (a.scope_type = 'SUBCATEGORY' and a.subcategory_id = p_subcategory_id)
                        or (a.scope_type = 'PRODUCT' and a.product_id = p_product_id));
    select coalesce(jsonb_agg(jsonb_build_object(
             'field_id', a.field_id, 'scope_type', a.scope_type, 'scope_id', a.scope_id,
             'is_included', a.is_included, 'sort_order', a.sort_order)), '[]'::jsonb)
      into v_asg
      from public.item_field_assignments a
     where (a.scope_type = 'CATEGORY' and a.category_id = p_category_id)
        or (a.scope_type = 'SUBCATEGORY' and a.subcategory_id = p_subcategory_id)
        or (a.scope_type = 'PRODUCT' and a.product_id = p_product_id);
  else
    select v.id, v.version_no, v.snapshot -> 'library', v.snapshot -> 'assignments'
      into v_ver_id, v_ver_no, v_lib, v_asg
      from public.item_field_profile_versions v where v.id = p_version_id;
    if not found then
      raise exception 'resolve_item_field_profile: unknown profile version %', p_version_id
        using errcode = 'P0002';
    end if;
  end if;

  return query
  with asg as (
    select a.field_id, a.scope_type, a.scope_id, a.is_included, a.sort_order,
           case a.scope_type when 'PRODUCT' then 1 when 'SUBCATEGORY' then 2 else 3 end as rnk
      from jsonb_to_recordset(v_asg)
           as a(field_id uuid, scope_type text, scope_id uuid, is_included boolean, sort_order integer)
     where (a.scope_type = 'CATEGORY' and a.scope_id = p_category_id)
        or (a.scope_type = 'SUBCATEGORY' and a.scope_id = p_subcategory_id)
        or (a.scope_type = 'PRODUCT' and a.scope_id = p_product_id)
  ),
  lib as (
    select *
      from jsonb_to_recordset(v_lib)
           as l(id uuid, field_group text, code text, label text, sort_order integer, is_active boolean,
                is_wastage boolean, returns_to_routing boolean, requires_cn boolean,
                requires_challan boolean, system_behavior text)
  ),
  j as (
    select asg.*, lib.field_group, lib.code, lib.label, lib.sort_order as lib_sort, lib.is_active,
           lib.is_wastage, lib.returns_to_routing, lib.requires_cn, lib.requires_challan,
           lib.system_behavior
      from asg join lib on lib.id = asg.field_id
  ),
  win as (
    select j.field_group, min(j.rnk) as rnk from j group by j.field_group
  )
  select v_ver_id, v_ver_no, j.field_group, j.field_id, j.code, j.label, j.sort_order,
         j.scope_type, j.scope_id, j.is_wastage, j.returns_to_routing, j.requires_cn,
         j.requires_challan, j.system_behavior
    from j join win on win.field_group = j.field_group and win.rnk = j.rnk
   where j.is_included and j.is_active
   order by j.field_group, j.sort_order, j.lib_sort, j.code;
end
$$;
revoke all on function rms_private.resolve_item_field_profile_for_scope(uuid, uuid, uuid, uuid) from public;
grant execute on function rms_private.resolve_item_field_profile_for_scope(uuid, uuid, uuid, uuid) to rms_api;

-- Product entry point: the effective profile of a product (its current category / sub-category).
create or replace function rms_private.resolve_item_field_profile(
  p_product_id  uuid,
  p_version_id  uuid default null
)
returns table (
  profile_version_id  uuid,
  profile_version_no  integer,
  field_group         text,
  field_id            uuid,
  code                text,
  label               text,
  sort_order          integer,
  source_scope_type   text,
  source_scope_id     uuid,
  is_wastage          boolean,
  returns_to_routing  boolean,
  requires_cn         boolean,
  requires_challan    boolean,
  system_behavior     text
)
language plpgsql
stable
set search_path = ''
as $$
declare
  v_cat  uuid;
  v_sub  uuid;
begin
  select p.category_id, p.subcategory_id into v_cat, v_sub
    from public.products p where p.id = p_product_id;
  if not found then
    raise exception 'resolve_item_field_profile: unknown product %', p_product_id using errcode = 'P0002';
  end if;
  return query
  select * from rms_private.resolve_item_field_profile_for_scope(v_cat, v_sub, p_product_id, p_version_id);
end
$$;
revoke all on function rms_private.resolve_item_field_profile(uuid, uuid) from public;
grant execute on function rms_private.resolve_item_field_profile(uuid, uuid) to rms_api;

-- ===========================================================================
-- 5. GS stores the profile version it was categorised under (AMD-10, G-18)
-- ===========================================================================
alter table public.goods_slips
  add column item_field_profile_version_id uuid
  references public.item_field_profile_versions (id) on delete restrict;
create index goods_slips_item_field_profile_version_idx
  on public.goods_slips (item_field_profile_version_id);
comment on column public.goods_slips.item_field_profile_version_id is
  'AMD-10 / G-18: item field profile version the GS was categorised under (stamped on leaving CATEGORISATION; immutable).';

create or replace function rms_private.goods_slips_field_profile_stamp()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if old.item_field_profile_version_id is not null
     and new.item_field_profile_version_id is distinct from old.item_field_profile_version_id then
    raise exception 'G-18: the item field profile version of a GS is immutable once stamped'
      using errcode = '42501';
  end if;
  if old.status = 'CATEGORISATION' and new.status is distinct from old.status
     and new.status <> 'CANCELLED' and new.item_field_profile_version_id is null then
    select v.id into new.item_field_profile_version_id
      from public.item_field_profile_versions v order by v.version_no desc limit 1;
  end if;
  return new;
end
$$;
revoke all on function rms_private.goods_slips_field_profile_stamp() from public;

create trigger goods_slips_field_profile_stamp
  before update on public.goods_slips
  for each row execute function rms_private.goods_slips_field_profile_stamp();

-- ===========================================================================
-- 6. Packaging / Container / User Manual counts per GS item (AMD-11)
-- ===========================================================================
create table public.gs_item_counts (
  id              uuid primary key default gen_random_uuid(),
  gs_item_id      uuid not null references public.gs_items (id) on delete cascade,
  field_id        uuid not null references public.item_field_library (id) on delete restrict,
  field_code      text not null,
  label_snapshot  text not null,
  qty             integer not null check (qty >= 0),
  created_at      timestamptz not null default now(),
  created_by      uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at      timestamptz not null default now(),
  constraint gs_item_counts_item_field_key unique (gs_item_id, field_id)
);
create index gs_item_counts_field_idx on public.gs_item_counts (field_id);
comment on table public.gs_item_counts is
  'AMD-11: per-item numeric counts (Packaging / Container / User Manual) enabled by the resolved item field profile.';

create or replace function rms_private.gs_item_counts_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_product  uuid;
  v_status   text;
  v_version  uuid;
  v_lib      public.item_field_library%rowtype;
begin
  if tg_op = 'DELETE' then
    select gs.status into v_status
      from public.gs_items gi join public.goods_slips gs on gs.id = gi.gs_id where gi.id = old.gs_item_id;
    if v_status is not null and v_status <> 'CATEGORISATION' then
      raise exception 'G-18: item counts change only while the GS is in CATEGORISATION (status %)', v_status
        using errcode = '23514';
    end if;
    return old;
  end if;

  if tg_op = 'UPDATE' and (new.gs_item_id, new.field_id, new.field_code, new.label_snapshot)
                          is distinct from (old.gs_item_id, old.field_id, old.field_code, old.label_snapshot) then
    raise exception 'G-18: the field and label snapshot of an item count are immutable' using errcode = '42501';
  end if;

  select gi.product_id, gs.status, gs.item_field_profile_version_id into v_product, v_status, v_version
    from public.gs_items gi join public.goods_slips gs on gs.id = gi.gs_id where gi.id = new.gs_item_id;
  if v_status is distinct from 'CATEGORISATION' then
    raise exception 'G-18: item counts are recorded only while the GS is in CATEGORISATION (status %)', v_status
      using errcode = '23514';
  end if;

  if tg_op = 'INSERT' then
    select * into v_lib from public.item_field_library where id = new.field_id;
    if v_lib.field_group is distinct from 'ITEM_COUNT' then
      raise exception 'G-18: % is not an item count field', coalesce(v_lib.code, new.field_id::text)
        using errcode = '23514';
    end if;
    if not exists (select 1 from rms_private.resolve_item_field_profile(v_product, v_version) r
                    where r.field_group = 'ITEM_COUNT' and r.field_id = new.field_id) then
      raise exception 'G-18: item count % is not enabled in the item field profile of this product', v_lib.code
        using errcode = '23514';
    end if;
    -- label snapshot (G-18): the label in force when the count was recorded
    new.field_code := v_lib.code;
    new.label_snapshot := v_lib.label;
  end if;
  return new;
end
$$;
revoke all on function rms_private.gs_item_counts_guard() from public;

create trigger gs_item_counts_guard
  before insert or update or delete on public.gs_item_counts
  for each row execute function rms_private.gs_item_counts_guard();

-- ===========================================================================
-- 7. rm_item_actions: CHECK -> FK to the ACTION library + label snapshot (AMD-16, G-18)
-- ===========================================================================
do $$
declare
  c record;
begin
  for c in
    select conname from pg_constraint
     where conrelid = 'public.rm_item_actions'::regclass and contype = 'c'
       and pg_get_constraintdef(oid) like '%action_code%'
       and pg_get_constraintdef(oid) like '%SEND_NEW%'
  loop
    execute format('alter table public.rm_item_actions drop constraint %I', c.conname);
  end loop;
end
$$;

alter table public.rm_item_actions
  add column action_field_group text not null default 'ACTION'
    constraint rm_item_actions_action_field_group_check check (action_field_group = 'ACTION'),
  add column action_label text;

create or replace function rms_private.rm_item_actions_label_snapshot()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_label   text;
  v_active  boolean;
begin
  if tg_op = 'UPDATE' then
    if new.action_code is distinct from old.action_code
       or new.action_label is distinct from old.action_label then
      raise exception 'G-18: the action and its label snapshot are immutable on an RM action row'
        using errcode = '42501';
    end if;
    return new;
  end if;
  select l.label, l.is_active into v_label, v_active
    from public.item_field_library l where l.field_group = 'ACTION' and l.code = new.action_code;
  if v_label is null then
    raise exception 'G-18: unknown action code % (not in the action library)', new.action_code
      using errcode = '23503';
  end if;
  if not v_active then
    raise exception 'G-18: action % is inactive in the action library', new.action_code using errcode = '23514';
  end if;
  new.action_label := v_label;
  return new;
end
$$;
revoke all on function rms_private.rm_item_actions_label_snapshot() from public;

create trigger rm_item_actions_label_snapshot
  before insert or update on public.rm_item_actions
  for each row execute function rms_private.rm_item_actions_label_snapshot();

-- ===========================================================================
-- RLS, grants, standard triggers (config goes through the API: rms_api only).
-- Before the seeding: the deferred version trigger leaves pending events that block later ALTERs.
-- ===========================================================================
alter table public.item_field_library enable row level security;
alter table public.item_field_assignments enable row level security;
alter table public.item_field_profile_versions enable row level security;
alter table public.gs_item_counts enable row level security;
revoke all on public.item_field_library, public.item_field_assignments,
              public.item_field_profile_versions, public.gs_item_counts from anon, authenticated;
-- No DELETE on the library: fields are deactivated, never removed (history keeps resolving).
revoke delete, truncate on public.item_field_library from rms_api;   -- default privileges grant it
grant select, insert, update on public.item_field_library to rms_api;
grant select, insert, update, delete on public.item_field_assignments to rms_api;
revoke update, delete, truncate on public.item_field_profile_versions from rms_api;
grant select, insert on public.item_field_profile_versions to rms_api;
grant select, insert, update, delete on public.gs_item_counts to rms_api;
select rms_private.attach_standard_triggers('public.item_field_library');
select rms_private.attach_standard_triggers('public.item_field_assignments');
select rms_private.attach_standard_triggers('public.gs_item_counts');

-- ===========================================================================
-- 8. Seeding (shared with seed.sql; idempotent, never re-adds what an admin removed)
-- ===========================================================================
create or replace function rms_private.seed_item_field_library_from_options()
returns void
language plpgsql
set search_path = ''
as $$
declare
  c record;
begin
  -- CATEGORISATION: each category's condition options (DD r21–r41) -> library + category assignment.
  insert into public.item_field_library
    (field_group, code, label, sort_order, is_active, is_system, system_behavior,
     source_option_item_id, source_ref)
  select 'CATEGORISATION', oi.code, oi.label, oi.sort_order, oi.is_active, true, oi.system_behavior,
         oi.id, oi.source_ref
    from public.product_categories pc
    join public.option_items oi on oi.option_set_id = pc.condition_option_set_id
  on conflict (field_group, code) do nothing;

  for c in
    select pc.id, pc.condition_option_set_id from public.product_categories pc
     where pc.condition_option_set_id is not null
       and not exists (select 1 from public.item_field_assignments a
                        where a.scope_type = 'CATEGORY' and a.category_id = pc.id
                          and a.field_group = 'CATEGORISATION')
  loop
    insert into public.item_field_assignments
      (field_id, field_group, scope_type, category_id, is_included, sort_order)
    select l.id, 'CATEGORISATION', 'CATEGORY', c.id,
           -- G-07: short quantity is documented minus received, never a physical bucket.
           l.system_behavior is distinct from 'SHORT_QTY', oi.sort_order
      from public.option_items oi
      join public.item_field_library l on l.source_option_item_id = oi.id
     where oi.option_set_id = c.condition_option_set_id;
  end loop;

  -- ACTION: RM_ITEM_ACTION options (WF r6) -> library (flags per AMD-18) + every category.
  insert into public.item_field_library
    (field_group, code, label, sort_order, is_active, is_system, requires_cn, requires_challan,
     source_option_item_id, source_ref)
  select 'ACTION', oi.code, oi.label, oi.sort_order, oi.is_active, true,
         oi.code = 'ISSUE_CN', oi.code in ('SEND_NEW', 'SEND_REPAIRED'), oi.id, oi.source_ref
    from public.option_items oi
    join public.option_sets os on os.id = oi.option_set_id
   where os.code = 'RM_ITEM_ACTION'
  on conflict (field_group, code) do nothing;

  insert into public.item_field_assignments
    (field_id, field_group, scope_type, category_id, is_included, sort_order)
  select l.id, 'ACTION', 'CATEGORY', pc.id, true, l.sort_order
    from public.product_categories pc
    cross join public.item_field_library l
   where l.field_group = 'ACTION' and l.is_system
     and not exists (select 1 from public.item_field_assignments a
                      where a.scope_type = 'CATEGORY' and a.category_id = pc.id
                        and a.field_group = 'ACTION');
end
$$;
revoke all on function rms_private.seed_item_field_library_from_options() from public;

-- AMD-10 departments and AMD-11 counts: library entries only (unassigned; enabled per scope by an admin).
insert into public.item_field_library (field_group, code, label, sort_order, is_system, source_ref) values
  ('DEPARTMENT', 'MERCURY_EXTRACTION',   'Mercury Extraction',   10, false, 'AMD-10'),
  ('DEPARTMENT', 'TECHNICAL_INSPECTION', 'Technical Inspection', 20, false, 'AMD-10'),
  ('DEPARTMENT', 'REPAIR',               'Repair',               30, false, 'AMD-10'),
  ('DEPARTMENT', 'CLEANING',             'Cleaning',             40, false, 'AMD-10'),
  ('ITEM_COUNT', 'PACKAGING',            'Packaging',            10, false, 'AMD-11'),
  ('ITEM_COUNT', 'CONTAINER',            'Container',            20, false, 'AMD-11'),
  ('ITEM_COUNT', 'USER_MANUAL',          'User Manual',          30, false, 'AMD-11')
on conflict (field_group, code) do nothing;

-- Existing databases: the option catalogue is already loaded. (Fresh reset: no-op here; seed.sql
-- calls the same function after loading the catalogue.)
select rms_private.seed_item_field_library_from_options();

-- Backfill the label snapshot of existing RM actions, then add the FK (codes now in the library).
alter table public.rm_item_actions disable trigger rm_item_actions_label_snapshot;
update public.rm_item_actions ra
   set action_label = l.label
  from public.item_field_library l
 where l.field_group = 'ACTION' and l.code = ra.action_code and ra.action_label is null;
alter table public.rm_item_actions enable trigger rm_item_actions_label_snapshot;

alter table public.rm_item_actions
  add constraint rm_item_actions_action_fkey
  foreign key (action_field_group, action_code)
  references public.item_field_library (field_group, code)
  on update restrict on delete restrict;
