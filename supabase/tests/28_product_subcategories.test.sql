-- Change plan 2026-11-12 Phase 1 pgTAP: product sub-categories (AMD-07) and the
-- gate.party_fallback setting (AMD-06, DEC-35).
begin;
create extension if not exists pgtap with schema extensions;
select plan(13);

select has_table('public', 'product_subcategories', 'product_subcategories exists');
select col_is_null('public', 'products', 'subcategory_id', 'products.subcategory_id is nullable');
select ok(
  (select relrowsecurity from pg_class where oid = 'public.product_subcategories'::regclass),
  'RLS is enabled on product_subcategories');
select ok(
  not has_table_privilege('authenticated', 'public.product_subcategories', 'SELECT')
  and not has_table_privilege('anon', 'public.product_subcategories', 'SELECT'),
  'anon/authenticated have no access to product_subcategories (masters go through the API)');

-- Fixtures: two categories, one sub-category each.
insert into public.product_categories (code, name) values ('PGTAP_SC_A', 'pgTAP A'), ('PGTAP_SC_B', 'pgTAP B');
insert into public.product_subcategories (category_id, code, name)
select id, 'SUB_A', 'Sub A' from public.product_categories where code = 'PGTAP_SC_A';
insert into public.product_subcategories (category_id, code, name)
select id, 'SUB_B', 'Sub B' from public.product_categories where code = 'PGTAP_SC_B';

-- AMD-07: a product may use a sub-category of its own category.
select lives_ok($$
  insert into public.products (code, name, category_id, subcategory_id)
  select 'PGTAP-SC-OK', 'pgTAP sub ok', c.id, s.id
    from public.product_categories c join public.product_subcategories s on s.category_id = c.id
   where c.code = 'PGTAP_SC_A'$$,
  'AMD-07: product with a sub-category of its own category is accepted');

-- AMD-07: a sub-category from another category is rejected by the DB.
select throws_ok($$
  insert into public.products (code, name, category_id, subcategory_id)
  select 'PGTAP-SC-BAD', 'pgTAP sub bad', a.id, sb.id
    from public.product_categories a, public.product_subcategories sb
   where a.code = 'PGTAP_SC_A' and sb.code = 'SUB_B'$$,
  '23503', null,
  'AMD-07: product with a sub-category of another category is rejected');

-- AMD-07: changing only the category while the old sub-category stays is rejected too.
select throws_ok($$
  update public.products set category_id = (select id from public.product_categories where code = 'PGTAP_SC_B')
   where code = 'PGTAP-SC-OK'$$,
  '23503', null,
  'AMD-07: moving a product to another category without changing its sub-category is rejected');

select lives_ok($$
  update public.products
     set category_id = (select id from public.product_categories where code = 'PGTAP_SC_B'),
         subcategory_id = (select id from public.product_subcategories where code = 'SUB_B')
   where code = 'PGTAP-SC-OK'$$,
  'AMD-07: category and sub-category changed together is accepted');

-- AMD-07: sub-category code and category are immutable.
select throws_ok($$update public.product_subcategories set code = 'SUB_A2' where code = 'SUB_A'$$,
  '23514', null, 'AMD-07: sub-category code is immutable');
select throws_ok($$
  update public.product_subcategories
     set category_id = (select id from public.product_categories where code = 'PGTAP_SC_B')
   where code = 'SUB_A'$$,
  '23514', null, 'AMD-07: sub-category cannot move to another category');

-- unique (category_id, code)
select throws_ok($$
  insert into public.product_subcategories (category_id, code, name)
  select id, 'SUB_A', 'Another' from public.product_categories where code = 'PGTAP_SC_A'$$,
  '23505', null, 'sub-category code is unique within its category');

-- DEC-35: gate.party_fallback exists and only takes STATE | ALL | NONE.
select is((select value #>> '{}' from public.system_settings where key = 'gate.party_fallback'),
  'STATE', 'DEC-35: gate.party_fallback defaults to STATE');
select throws_ok($$update public.system_settings set value = '"STATION"' where key = 'gate.party_fallback'$$,
  '23514', null, 'DEC-35: gate.party_fallback rejects values other than STATE | ALL | NONE');

select * from finish();
rollback;
