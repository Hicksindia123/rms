-- Phase P1 (docs/RMS_PHASE_PROMPTS_20-11-2026.md) - Intermediate Stores and the category -> store
-- mapping (DEC-61; Q3 confirmed by the user 2026-11-20, Q4 PROVISIONAL).
--
-- 1. intermediate_stores: N stores (seeded OP / DT / RI in seed.sql). Each store has an immutable
--    code, its own role (the store users) and its own stock location (class FUNCTIONAL: there is
--    no INTERMEDIATE_STORE location class, P0 finding F5). Exactly one active store is the
--    default for products that no mapping covers (partial unique index + deferred check).
--    Stores are never deleted (history); they are deactivated.
-- 2. intermediate_store_category_map: a store owns categories and/or sub-categories. A category or
--    sub-category belongs to at most one store. Sub-category mapping wins over category mapping.
-- 3. rms_private.store_for_product(product_id): sub-category -> category -> default store; the
--    mappings of an inactive store are skipped.
-- 4. rms_private.user_store_ids(user_id): the active stores a user acts for (via the store role);
--    Super Admin and MANAGEMENT (DEC-60) see every active store.
-- 5. rms_private.assert_store_for_products(product_ids): guard STORE_MAPPING_MISSING (DEC-61).
--    Transfer-slip generation (Phase P5) must call it inside its transaction; the service checks
--    the same rule first (IntermediateStoreService.require_stores_for_products).
--
-- Roles, store rows, locations and the mapping are seed data (seed.sql + supabase/snippets/
-- release_20261120_roles_intermediate_stores.sql), never this migration. The legacy location
-- INTERMEDIATE_STORE and role INTERMEDIATE_STORE_MANAGER are untouched (retired in P6/P7); stock
-- already there stays there.

-- ---------------------------------------------------------------------------
-- 1. intermediate_stores
-- ---------------------------------------------------------------------------
create table public.intermediate_stores (
  id           uuid primary key default gen_random_uuid(),
  code         text not null unique check (code ~ '^[A-Z][A-Z0-9_]{0,19}$'),
  name         text not null check (btrim(name) <> ''),
  role_id      uuid not null unique references public.roles (id) on delete restrict,
  location_id  uuid not null unique references public.inventory_locations (id) on delete restrict,
  is_default   boolean not null default false,
  is_active    boolean not null default true,
  sort_order   integer not null default 100 check (sort_order between 0 and 100000),
  created_at   timestamptz not null default now(),
  created_by   uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at   timestamptz not null default now(),
  -- DEC-61: the fallback store must be able to take goods.
  constraint intermediate_stores_default_is_active check (not is_default or is_active)
);
-- DEC-61: at most one default store (the deferred trigger below requires at least one).
create unique index intermediate_stores_single_default
  on public.intermediate_stores ((true)) where is_default;
create unique index intermediate_stores_name_key
  on public.intermediate_stores (lower(btrim(name)));

comment on table public.intermediate_stores is
  'DEC-61: Intermediate Stores (OP / DT / RI ...). Each has its own role and FUNCTIONAL stock location; exactly one active default store takes unmapped products.';

-- Code, role and location are immutable (rule e: logic keys off codes; the role and location carry
-- history). A store location must be a FUNCTIONAL location (DEC-61, P0 F5).
create or replace function rms_private.intermediate_stores_validate()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'UPDATE' then
    if new.code is distinct from old.code then
      raise exception 'DEC-61: Intermediate Store code % is immutable', old.code
        using errcode = 'check_violation';
    end if;
    if new.role_id is distinct from old.role_id or new.location_id is distinct from old.location_id then
      raise exception 'DEC-61: the role and location of Intermediate Store % cannot change', old.code
        using errcode = 'check_violation';
    end if;
  else
    if not exists (select 1 from public.inventory_locations l
                    where l.id = new.location_id and l.location_class = 'FUNCTIONAL') then
      raise exception 'DEC-61: the location of Intermediate Store % must be a FUNCTIONAL location', new.code
        using errcode = 'check_violation';
    end if;
  end if;
  return new;
end
$$;
revoke all on function rms_private.intermediate_stores_validate() from public;

create trigger intermediate_stores_validate
  before insert or update on public.intermediate_stores
  for each row execute function rms_private.intermediate_stores_validate();

-- Stores carry history: deactivate, never delete.
create or replace function rms_private.intermediate_stores_no_delete()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'DEC-61: Intermediate Store % cannot be deleted; deactivate it instead', old.code
    using errcode = 'check_violation';
end
$$;
revoke all on function rms_private.intermediate_stores_no_delete() from public;

create trigger intermediate_stores_no_delete
  before delete on public.intermediate_stores
  for each row execute function rms_private.intermediate_stores_no_delete();

-- DEC-61: while any store exists, exactly one ACTIVE default store exists (checked at commit, so a
-- service can move the default flag from one store to another in one transaction).
create or replace function rms_private.intermediate_stores_default_required()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if exists (select 1 from public.intermediate_stores)
     and not exists (select 1 from public.intermediate_stores s where s.is_default and s.is_active) then
    raise exception 'DEC-61: exactly one active default Intermediate Store is required'
      using errcode = 'check_violation';
  end if;
  return null;
end
$$;
revoke all on function rms_private.intermediate_stores_default_required() from public;

create constraint trigger intermediate_stores_default_required
  after insert or update on public.intermediate_stores
  deferrable initially deferred
  for each row execute function rms_private.intermediate_stores_default_required();

-- ---------------------------------------------------------------------------
-- 2. intermediate_store_category_map
-- ---------------------------------------------------------------------------
-- ON DELETE CASCADE on the category / sub-category: a removed (sub-)category simply stops being
-- mapped (the catalogue snippets rebuild sub-categories); resolution then falls back as usual.
create table public.intermediate_store_category_map (
  id              uuid primary key default gen_random_uuid(),
  store_id        uuid not null references public.intermediate_stores (id) on delete restrict,
  category_id     uuid references public.product_categories (id) on delete cascade,
  subcategory_id  uuid references public.product_subcategories (id) on delete cascade,
  created_at      timestamptz not null default now(),
  created_by      uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at      timestamptz not null default now(),
  constraint intermediate_store_category_map_one_target
    check (num_nonnulls(category_id, subcategory_id) = 1)
);
-- DEC-61: a category / sub-category belongs to at most one store.
create unique index intermediate_store_category_map_category_key
  on public.intermediate_store_category_map (category_id) where category_id is not null;
create unique index intermediate_store_category_map_subcategory_key
  on public.intermediate_store_category_map (subcategory_id) where subcategory_id is not null;
create index intermediate_store_category_map_store_idx
  on public.intermediate_store_category_map (store_id);

comment on table public.intermediate_store_category_map is
  'DEC-61: category / sub-category -> Intermediate Store. Sub-category mapping wins over category mapping; unmapped products go to the default store.';

-- ---------------------------------------------------------------------------
-- 3. Resolution: sub-category -> category -> default store (active stores only)
-- ---------------------------------------------------------------------------
create or replace function rms_private.store_for_product(p_product_id uuid)
returns uuid
language sql
stable
set search_path = ''
as $$
  select coalesce(
    (select m.store_id
       from public.products p
       join public.intermediate_store_category_map m on m.subcategory_id = p.subcategory_id
       join public.intermediate_stores s on s.id = m.store_id and s.is_active
      where p.id = p_product_id),
    (select m.store_id
       from public.products p
       join public.intermediate_store_category_map m on m.category_id = p.category_id
       join public.intermediate_stores s on s.id = m.store_id and s.is_active
      where p.id = p_product_id),
    (select s.id
       from public.intermediate_stores s
      where s.is_default and s.is_active
        and exists (select 1 from public.products p where p.id = p_product_id))
  )
$$;
comment on function rms_private.store_for_product(uuid) is
  'DEC-61: the Intermediate Store of a product (sub-category mapping, else category mapping, else the default store). NULL only for an unknown product or when no default store exists.';

-- ---------------------------------------------------------------------------
-- 4. The stores a user acts for
-- ---------------------------------------------------------------------------
create or replace function rms_private.user_store_ids(p_user_id uuid)
returns setof uuid
language sql
stable
set search_path = ''
as $$
  select s.id
    from public.intermediate_stores s
   where s.is_active
     and exists (select 1 from public.profiles pr where pr.id = p_user_id and pr.is_active)
     and (
       exists (select 1 from public.profiles pr where pr.id = p_user_id and pr.is_super_admin)
       -- DEC-60: Management sees every store.
       or exists (select 1 from public.user_roles ur
                    join public.roles r on r.id = ur.role_id
                   where ur.user_id = p_user_id and r.code = 'MANAGEMENT')
       or exists (select 1 from public.user_roles ur
                   where ur.user_id = p_user_id and ur.role_id = s.role_id)
     )
   order by s.sort_order, s.code
$$;
comment on function rms_private.user_store_ids(uuid) is
  'DEC-61: active Intermediate Stores the user acts for (holds the store role); Super Admin and MANAGEMENT (DEC-60) get every active store.';

-- ---------------------------------------------------------------------------
-- 5. Guard STORE_MAPPING_MISSING (DEC-61): every product must resolve to a store before a
--    transfer slip is generated (P5 calls this inside the generation transaction).
-- ---------------------------------------------------------------------------
create or replace function rms_private.assert_store_for_products(p_product_ids uuid[])
returns void
language plpgsql
stable
set search_path = ''
as $$
declare
  v_missing text;
begin
  select string_agg(p.code, ', ' order by p.code)
    into v_missing
    from public.products p
   where p.id = any(p_product_ids)
     and rms_private.store_for_product(p.id) is null;
  if v_missing is not null then
    raise exception 'STORE_MAPPING_MISSING: no Intermediate Store resolves for product(s) %', v_missing
      using errcode = 'P0001', hint = 'DEC-61';
  end if;
end
$$;

-- ---------------------------------------------------------------------------
-- 6. Permissions (module intermediate_stores). Grants live in seed.sql (_seed_role_matrix);
--    existing databases get the Super Admin marker grant here (as in earlier migrations).
-- ---------------------------------------------------------------------------
insert into public.permissions (module_code, action, description)
values
  ('intermediate_stores', 'view',      'View — Intermediate Stores and their category mapping'),
  ('intermediate_stores', 'create',    'Create — add an Intermediate Store (with its role and location)'),
  ('intermediate_stores', 'edit',      'Edit — rename, activate / deactivate, set the default store'),
  ('intermediate_stores', 'configure', 'Configure — map categories / sub-categories to a store')
on conflict (module_code, action) do nothing;

insert into public.role_permissions (role_id, permission_id, scope)
select r.id, p.id, 'all'
  from public.roles r
  join public.permissions p on p.module_code = 'intermediate_stores'
 where r.code = 'SUPER_ADMIN'
on conflict (role_id, permission_id) do nothing;

-- ---------------------------------------------------------------------------
-- 7. RLS, grants, standard triggers (rms_api only, audited, updated_at)
-- ---------------------------------------------------------------------------
alter table public.intermediate_stores enable row level security;
alter table public.intermediate_store_category_map enable row level security;
revoke all on public.intermediate_stores from anon, authenticated;
revoke all on public.intermediate_store_category_map from anon, authenticated;
-- No DELETE on stores (deactivate only); mapping rows are replaced by the admin.
grant select, insert, update on public.intermediate_stores to rms_api;
grant select, insert, update, delete on public.intermediate_store_category_map to rms_api;
select rms_private.attach_standard_triggers('public.intermediate_stores');
select rms_private.attach_standard_triggers('public.intermediate_store_category_map');

revoke all on function rms_private.store_for_product(uuid) from public, anon, authenticated;
revoke all on function rms_private.user_store_ids(uuid) from public, anon, authenticated;
revoke all on function rms_private.assert_store_for_products(uuid[]) from public, anon, authenticated;
grant execute on function rms_private.store_for_product(uuid) to rms_api;
grant execute on function rms_private.user_store_ids(uuid) to rms_api;
grant execute on function rms_private.assert_store_for_products(uuid[]) to rms_api;
