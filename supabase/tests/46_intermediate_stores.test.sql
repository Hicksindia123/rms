-- Phase P1 · migration 20261120000100 (DEC-61): Intermediate Stores and the category -> store mapping.
--   * seed: OP (ENCLOSED_OVAL, PRISMATIC), DT (DMT), RI (GENERAL, default)
--   * rms_private.store_for_product: sub-category mapping > category mapping > default store
--   * exactly one active default store (partial unique index + deferred check), default stays active
--   * inactive store: its mappings are skipped (falls back to the default store)
--   * code / role / location immutable, no delete, location must be FUNCTIONAL, mapping XOR + unique
--   * rms_private.user_store_ids: store role -> that store; MANAGEMENT / Super Admin -> all
--   * guard STORE_MAPPING_MISSING (rms_private.assert_store_for_products)
-- Self-contained (works on a bare `supabase db reset`); everything is rolled back.

begin;
select plan(31);

select has_table('public', 'intermediate_stores', 'intermediate_stores exists');
select has_table('public', 'intermediate_store_category_map', 'intermediate_store_category_map exists');

-- ---------------------------------------------------------------------------
-- Seed
-- ---------------------------------------------------------------------------
select results_eq(
  $$ select s.code, s.is_default, r.code, l.code, l.location_class
       from public.intermediate_stores s
       join public.roles r on r.id = s.role_id
       join public.inventory_locations l on l.id = s.location_id
      order by s.sort_order $$,
  $$ values ('OP', false, 'ISTORE_OP', 'ISTORE_OP', 'FUNCTIONAL'),
            ('DT', false, 'ISTORE_DT', 'ISTORE_DT', 'FUNCTIONAL'),
            ('RI', true,  'ISTORE_RI', 'ISTORE_RI', 'FUNCTIONAL') $$,
  'seeded OP / DT / RI with own role and FUNCTIONAL location; RI is the default');

select results_eq(
  $$ select s.code, c.code
       from public.intermediate_store_category_map m
       join public.intermediate_stores s on s.id = m.store_id
       join public.product_categories c on c.id = m.category_id
      order by s.sort_order, c.code $$,
  $$ values ('OP', 'ENCLOSED_OVAL'), ('OP', 'PRISMATIC'), ('DT', 'DMT'), ('RI', 'GENERAL') $$,
  'seeded category mapping (DEC-61 / Q4)');

select is((select name from public.roles where code = 'INWARD_VERIFIER'), 'Replacement Executive', 'DEC-60 RE label');
select is((select name from public.roles where code = 'GATE_INWARD'), 'Gate User (Offline)', 'DEC-60 gate label');
select is((select count(*)::int from public.roles where code = 'MANAGEMENT'), 1, 'DEC-60 MANAGEMENT role exists');

-- ---------------------------------------------------------------------------
-- Test masters: one product per seeded category, a sub-category under DMT mapped to OP, and a new
-- unmapped category.
-- ---------------------------------------------------------------------------
insert into public.product_subcategories (id, category_id, code, name)
select 'b1b1b1b1-0000-4000-8000-000000000001', c.id, 'P1_TEST_SUB', 'P1 test sub-category'
  from public.product_categories c where c.code = 'DMT';
insert into public.product_categories (id, code, name)
values ('b1b1b1b1-0000-4000-8000-000000000002', 'P1_TEST_CAT', 'P1 test category');

insert into public.products (id, code, name, category_id, subcategory_id)
select v.id::uuid, v.code, v.code, c.id, v.sub::uuid
  from (values
    ('c1c1c1c1-0000-4000-8000-000000000001', 'P1-DMT',  'DMT',           null),
    ('c1c1c1c1-0000-4000-8000-000000000002', 'P1-PRI',  'PRISMATIC',     null),
    ('c1c1c1c1-0000-4000-8000-000000000003', 'P1-EO',   'ENCLOSED_OVAL', null),
    ('c1c1c1c1-0000-4000-8000-000000000004', 'P1-GEN',  'GENERAL',       null),
    ('c1c1c1c1-0000-4000-8000-000000000005', 'P1-SUB',  'DMT',           'b1b1b1b1-0000-4000-8000-000000000001'),
    ('c1c1c1c1-0000-4000-8000-000000000006', 'P1-NEW',  'P1_TEST_CAT',   null)
  ) as v(id, code, category, sub)
  join public.product_categories c on c.code = v.category;

create function pg_temp.store_of(p_code text) returns text language sql as $$
  select s.code from public.intermediate_stores s
   where s.id = rms_private.store_for_product((select id from public.products where code = p_code))
$$;

-- ---------------------------------------------------------------------------
-- Resolution
-- ---------------------------------------------------------------------------
select is(pg_temp.store_of('P1-DMT'), 'DT', 'DMT -> DT');
select is(pg_temp.store_of('P1-PRI'), 'OP', 'PRISMATIC -> OP');
select is(pg_temp.store_of('P1-EO'),  'OP', 'ENCLOSED_OVAL -> OP');
select is(pg_temp.store_of('P1-GEN'), 'RI', 'GENERAL -> RI');
select is(pg_temp.store_of('P1-NEW'), 'RI', 'unmapped category -> default store RI');
select is(pg_temp.store_of('P1-SUB'), 'DT', 'unmapped sub-category -> its category store DT');

insert into public.intermediate_store_category_map (store_id, subcategory_id)
select id, 'b1b1b1b1-0000-4000-8000-000000000001' from public.intermediate_stores where code = 'OP';
select is(pg_temp.store_of('P1-SUB'), 'OP', 'sub-category mapping wins over category mapping');
select is(rms_private.store_for_product('00000000-0000-4000-8000-0000000000ff'), null, 'unknown product -> NULL');

-- ---------------------------------------------------------------------------
-- Mapping integrity
-- ---------------------------------------------------------------------------
select throws_ok(
  $$ insert into public.intermediate_store_category_map (store_id, category_id)
     select s.id, c.id from public.intermediate_stores s, public.product_categories c
      where s.code = 'OP' and c.code = 'DMT' $$,
  '23505', null, 'a category maps to at most one store');
select throws_ok(
  $$ insert into public.intermediate_store_category_map (store_id)
     select id from public.intermediate_stores where code = 'OP' $$,
  '23514', null, 'mapping needs a category or a sub-category');
select throws_ok(
  $$ insert into public.intermediate_store_category_map (store_id, category_id, subcategory_id)
     select s.id, c.id, 'b1b1b1b1-0000-4000-8000-000000000001'
       from public.intermediate_stores s, public.product_categories c
      where s.code = 'DT' and c.code = 'P1_TEST_CAT' $$,
  '23514', null, 'mapping is category XOR sub-category');

-- ---------------------------------------------------------------------------
-- Single default store, default stays active, immutable code, no delete, FUNCTIONAL location
-- ---------------------------------------------------------------------------
select throws_ok(
  $$ update public.intermediate_stores set is_default = true where code = 'OP' $$,
  '23505', null, 'a second default store is rejected (partial unique index)');
select throws_ok(
  $$ update public.intermediate_stores set is_default = false where code = 'RI';
     set constraints all immediate $$,
  '23514', 'DEC-61: exactly one active default Intermediate Store is required',
  'removing the only default store is rejected');
select lives_ok(
  $$ set constraints all deferred;
     update public.intermediate_stores set is_default = false where code = 'RI';
     update public.intermediate_stores set is_default = true where code = 'DT';
     set constraints all immediate;
     set constraints all deferred;
     update public.intermediate_stores set is_default = false where code = 'DT';
     update public.intermediate_stores set is_default = true where code = 'RI';
     set constraints all immediate;
     set constraints all deferred $$,
  'the default can move to another store inside one transaction');
select throws_ok(
  $$ update public.intermediate_stores set is_active = false where code = 'RI' $$,
  '23514', null, 'the default store cannot be deactivated');
select throws_ok(
  $$ update public.intermediate_stores set code = 'OX' where code = 'OP' $$,
  '23514', 'DEC-61: Intermediate Store code OP is immutable', 'store code is immutable');
select throws_ok(
  $$ delete from public.intermediate_stores where code = 'OP' $$,
  '23514', null, 'stores are never deleted');
select throws_ok(
  $$ insert into public.intermediate_stores (code, name, role_id, location_id)
     select 'ZZ', 'Bad store', r.id, l.id from public.roles r, public.inventory_locations l
      where r.code = 'MANAGEMENT' and l.code = 'TRANSIT' $$,
  '23514', 'DEC-61: the location of Intermediate Store ZZ must be a FUNCTIONAL location',
  'store location must be FUNCTIONAL');

-- Inactive store: its mappings are skipped.
update public.intermediate_stores set is_active = false where code = 'DT';
select is(pg_temp.store_of('P1-DMT'), 'RI', 'inactive store DT: DMT falls back to the default store');
update public.intermediate_stores set is_active = true where code = 'DT';

-- ---------------------------------------------------------------------------
-- user_store_ids (DEC-60 / DEC-61)
-- ---------------------------------------------------------------------------
insert into auth.users (id, email, aud, role, raw_app_meta_data, raw_user_meta_data) values
  ('d1d1d1d1-0000-4000-8000-000000000001', 'p1-dt@example.test', 'authenticated', 'authenticated',
   '{"rms_activate": true}', '{"full_name": "P1 DT user"}'),
  ('d1d1d1d1-0000-4000-8000-000000000002', 'p1-mgmt@example.test', 'authenticated', 'authenticated',
   '{"rms_activate": true}', '{"full_name": "P1 Management"}'),
  ('d1d1d1d1-0000-4000-8000-000000000003', 'p1-none@example.test', 'authenticated', 'authenticated',
   '{"rms_activate": true}', '{"full_name": "P1 no store"}');
insert into public.user_roles (user_id, role_id)
select v.uid::uuid, r.id from (values
  ('d1d1d1d1-0000-4000-8000-000000000001', 'ISTORE_DT'),
  ('d1d1d1d1-0000-4000-8000-000000000002', 'MANAGEMENT'),
  ('d1d1d1d1-0000-4000-8000-000000000003', 'GATE_INWARD')
) as v(uid, role_code) join public.roles r on r.code = v.role_code;

select results_eq(
  $$ select s.code from rms_private.user_store_ids('d1d1d1d1-0000-4000-8000-000000000001') u(id)
       join public.intermediate_stores s on s.id = u.id $$,
  $$ values ('DT') $$, 'store role -> that store only');
select results_eq(
  $$ select s.code from rms_private.user_store_ids('d1d1d1d1-0000-4000-8000-000000000002') u(id)
       join public.intermediate_stores s on s.id = u.id order by s.sort_order $$,
  $$ values ('OP'), ('DT'), ('RI') $$, 'MANAGEMENT -> every active store');
select is_empty(
  $$ select * from rms_private.user_store_ids('d1d1d1d1-0000-4000-8000-000000000003') $$,
  'no store role -> no store');

-- ---------------------------------------------------------------------------
-- Guard STORE_MAPPING_MISSING
-- ---------------------------------------------------------------------------
select lives_ok(
  $$ select rms_private.assert_store_for_products(array(select id from public.products where code like 'P1-%')) $$,
  'every product resolves while a default store exists');

-- Force the impossible state (no default store) with triggers off, to prove the guard rejects.
set local session_replication_role = replica;
update public.intermediate_stores set is_default = false where code = 'RI';
set local session_replication_role = origin;
select throws_ok(
  $$ select rms_private.assert_store_for_products(array(select id from public.products where code in ('P1-NEW', 'P1-DMT'))) $$,
  'P0001', 'STORE_MAPPING_MISSING: no Intermediate Store resolves for product(s) P1-NEW',
  'no resolvable store -> STORE_MAPPING_MISSING (mapped products still pass)');

select * from finish();
rollback;
