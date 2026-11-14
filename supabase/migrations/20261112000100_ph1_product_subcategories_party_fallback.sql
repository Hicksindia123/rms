-- Change plan 2026-11-12 · Phase 1 — Masters: Sub-Categories and the gate party fallback setting.
--
-- AMD-07 (docs/RMS_MASTER_PLAN_ADDENDUM_2026-11.md): the product hierarchy becomes
--   Category -> Sub-Category -> Product. Sub-category codes are immutable; a product's sub-category
--   must belong to the product's category (DB-enforced here, re-checked in the masters service).
-- AMD-06 / DEC-35: system_settings `gate.party_fallback` = STATE | ALL | NONE decides what the
--   Distributor lookup shows when the selected station has no parties.

-- ---------------------------------------------------------------------------
-- product_subcategories
-- ---------------------------------------------------------------------------
create table public.product_subcategories (
  id           uuid primary key default gen_random_uuid(),
  category_id  uuid not null references public.product_categories (id) on delete restrict,
  code         text not null check (code ~ '^[A-Z][A-Z0-9_]*$'),
  name         text not null check (btrim(name) <> ''),
  is_active    boolean not null default true,
  created_at   timestamptz not null default now(),
  created_by   uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at   timestamptz not null default now(),
  constraint product_subcategories_category_code_key unique (category_id, code),
  -- Target of the composite FK from products (sub-category must belong to the product's category).
  constraint product_subcategories_id_category_key unique (id, category_id)
);
create unique index product_subcategories_category_name_key
  on public.product_subcategories (category_id, lower(btrim(name)));

comment on table public.product_subcategories is
  'AMD-07: second level of the product hierarchy (Category -> Sub-Category -> Product). Codes are immutable.';

-- AMD-07 / rule e: codes are immutable once created (transactions and config key off codes).
-- The category of a sub-category is fixed as well: moving it would silently re-parent its products.
create or replace function rms_private.product_subcategories_immutable()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.code is distinct from old.code then
    raise exception 'AMD-07: product sub-category code % is immutable', old.code
      using errcode = 'check_violation';
  end if;
  if new.category_id is distinct from old.category_id then
    raise exception 'AMD-07: product sub-category % cannot move to another category', old.code
      using errcode = 'check_violation';
  end if;
  return new;
end
$$;
revoke all on function rms_private.product_subcategories_immutable() from public;

create trigger product_subcategories_immutable
  before update on public.product_subcategories
  for each row execute function rms_private.product_subcategories_immutable();

-- ---------------------------------------------------------------------------
-- products.subcategory_id (nullable) — composite FK proves category membership (AMD-07)
-- ---------------------------------------------------------------------------
alter table public.products
  add column subcategory_id uuid;

alter table public.products
  add constraint products_subcategory_in_category_fkey
  foreign key (subcategory_id, category_id)
  references public.product_subcategories (id, category_id)
  on update restrict on delete restrict;
-- MATCH SIMPLE: a NULL subcategory_id means "no sub-category" and is not checked.

create index products_subcategory_idx on public.products (subcategory_id);

-- ---------------------------------------------------------------------------
-- RLS, grants, standard triggers (as for every master: rms_api only, audited, updated_at)
-- ---------------------------------------------------------------------------
alter table public.product_subcategories enable row level security;
revoke all on public.product_subcategories from anon, authenticated;
grant select, insert, update, delete on public.product_subcategories to rms_api;
select rms_private.attach_standard_triggers('public.product_subcategories');

-- ---------------------------------------------------------------------------
-- gate.party_fallback (AMD-06, DEC-35 PROVISIONAL): STATE | ALL | NONE
-- ---------------------------------------------------------------------------
insert into public.system_settings (key, value, category, description, source_ref) values
  ('gate.party_fallback', '"STATE"', 'provisional',
   'Distributor lookup when the selected station has no parties: STATE = parties of the selected state, ALL = all parties, NONE = empty list. Creating a provisional party stays available (DEC-02).',
   'DEC-35')
on conflict (key) do nothing;

alter table public.system_settings
  add constraint system_settings_gate_party_fallback_check
  check (key <> 'gate.party_fallback' or value in ('"STATE"'::jsonb, '"ALL"'::jsonb, '"NONE"'::jsonb));
