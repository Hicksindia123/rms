-- Change plan 2026-11-12 Phase 4 pgTAP: item field profiles (AMD-10, AMD-11, AMD-16; G-05; G-18).
begin;
create extension if not exists pgtap with schema extensions;
select plan(36);

-- ---------------------------------------------------------------------------
-- Schema, RLS, grants
-- ---------------------------------------------------------------------------
select has_table('public', 'item_field_library', 'item_field_library exists');
select has_table('public', 'item_field_assignments', 'item_field_assignments exists');
select has_table('public', 'item_field_profile_versions', 'item_field_profile_versions exists');
select has_table('public', 'gs_item_counts', 'gs_item_counts exists (AMD-11)');
select ok(
  (select bool_and(relrowsecurity) from pg_class
    where oid in ('public.item_field_library'::regclass, 'public.item_field_assignments'::regclass,
                  'public.item_field_profile_versions'::regclass, 'public.gs_item_counts'::regclass))
  and not has_table_privilege('authenticated', 'public.item_field_library', 'SELECT')
  and not has_table_privilege('anon', 'public.item_field_assignments', 'SELECT'),
  'RLS on; anon/authenticated have no direct access (config goes through the API)');
select ok(not has_table_privilege('rms_api', 'public.item_field_library', 'DELETE'),
  'AMD-10: library fields are never deleted (deactivate instead)');

-- ---------------------------------------------------------------------------
-- Seed: nothing in use breaks (AMD-10 / AMD-16)
-- ---------------------------------------------------------------------------
select set_eq(
  $$select code from public.item_field_library where field_group = 'ACTION'$$,
  $$values ('SEND_NEW'),('SEND_REPAIRED'),('ISSUE_CN'),('NOT_ALLOWED'),('PENDING_BP')$$,
  'AMD-16: the existing action codes are ACTION library entries');
select ok(
  (select requires_cn from public.item_field_library where field_group = 'ACTION' and code = 'ISSUE_CN')
  and (select bool_and(requires_challan) from public.item_field_library
        where field_group = 'ACTION' and code in ('SEND_NEW', 'SEND_REPAIRED')),
  'AMD-18: ISSUE_CN requires CN data; SEND_NEW / SEND_REPAIRED require challan data');
select set_eq(
  $$select l.code from public.item_field_assignments a
      join public.item_field_library l on l.id = a.field_id
      join public.product_categories c on c.id = a.category_id
     where c.code = 'DMT' and a.field_group = 'CATEGORISATION' and a.is_included$$,
  $$select oi.code from public.option_items oi join public.option_sets os on os.id = oi.option_set_id
     where os.code = 'DMT_CONDITION' and oi.code <> 'DMT_SHORT_QTY'$$,
  'AMD-10: DMT condition options are its CATEGORISATION buckets (short qty excluded, G-07)');

-- ---------------------------------------------------------------------------
-- Immutability (rule e, G-18) and the hazard lock (G-05)
-- ---------------------------------------------------------------------------
select throws_like(
  $$update public.item_field_library set code = 'SEND_NEW_2' where field_group = 'ACTION' and code = 'SEND_NEW'$$,
  'G-18:%immutable%', 'G-18: item field codes are immutable');
select throws_like(
  $$update public.item_field_library set field_group = 'DEPARTMENT' where field_group = 'ACTION' and code = 'SEND_NEW'$$,
  'G-18:%another field group%', 'G-18: item field group is immutable');
select throws_like(
  $$update public.item_field_library set system_behavior = 'SELLABLE'
     where field_group = 'CATEGORISATION' and code = 'PRS_BROKEN_WITH_HG'$$,
  'G-05:%locked%', 'G-05: hazard behaviour of a categorisation field is locked');
select lives_ok(
  $$update public.item_field_library set label = 'Send New Unit' where field_group = 'ACTION' and code = 'SEND_NEW'$$,
  'labels are editable');
select throws_ok(
  $$insert into public.item_field_library (field_group, code, label, requires_cn)
    values ('CATEGORISATION', 'PGTAP_BAD_FLAG', 'Bad flag', true)$$,
  '23514', null, 'action-only flags are rejected on other groups');

-- ---------------------------------------------------------------------------
-- Fixtures: category -> sub-category -> products, and library fields
-- ---------------------------------------------------------------------------
insert into public.product_categories (code, name) values ('PGTAP_IFP', 'pgTAP IFP');
insert into public.product_subcategories (category_id, code, name)
select id, 'PGTAP_IFP_SUB', 'pgTAP IFP sub' from public.product_categories where code = 'PGTAP_IFP';
insert into public.products (code, name, category_id, subcategory_id)
select v.code, v.code, c.id, s.id
  from (values ('PGTAP-IFP-P1'), ('PGTAP-IFP-P2')) as v(code),
       public.product_categories c join public.product_subcategories s on s.category_id = c.id
 where c.code = 'PGTAP_IFP';
insert into public.products (code, name, category_id)
select 'PGTAP-IFP-P3', 'no sub-category', id from public.product_categories where code = 'PGTAP_IFP';
insert into public.item_field_library (field_group, code, label, sort_order) values
  ('CATEGORISATION', 'PGTAP_B1', 'Bucket 1', 10),
  ('CATEGORISATION', 'PGTAP_B2', 'Bucket 2', 20),
  ('CATEGORISATION', 'PGTAP_B3', 'Bucket 3', 30);

create temporary table ifp_ids on commit drop as
select (select id from public.product_categories where code = 'PGTAP_IFP') as cat,
       (select id from public.product_subcategories where code = 'PGTAP_IFP_SUB') as sub,
       (select id from public.products where code = 'PGTAP-IFP-P1') as p1,
       (select id from public.products where code = 'PGTAP-IFP-P2') as p2,
       (select id from public.products where code = 'PGTAP-IFP-P3') as p3;

select throws_ok(
  $$insert into public.item_field_assignments (field_id, field_group, scope_type, category_id, product_id)
    select l.id, 'CATEGORISATION', 'CATEGORY', i.cat, i.p1
      from public.item_field_library l, ifp_ids i where l.code = 'PGTAP_B1'$$,
  '23514', null, 'AMD-10: exactly the scope column matching scope_type is set');
select throws_ok(
  $$insert into public.item_field_assignments (field_id, field_group, scope_type, category_id)
    select l.id, 'ACTION', 'CATEGORY', i.cat
      from public.item_field_library l, ifp_ids i where l.code = 'PGTAP_B1'$$,
  '23503', null, 'AMD-10: an assignment cannot put a field into another group');

-- CATEGORY scope: B2 (sort 1), B1 (sort 2) -> order follows the assignment sort.
insert into public.item_field_assignments (field_id, field_group, scope_type, category_id, sort_order)
select l.id, 'CATEGORISATION', 'CATEGORY', i.cat, case l.code when 'PGTAP_B2' then 1 else 2 end
  from public.item_field_library l, ifp_ids i where l.code in ('PGTAP_B1', 'PGTAP_B2');
insert into public.item_field_assignments (field_id, field_group, scope_type, category_id)
select l.id, 'ACTION', 'CATEGORY', i.cat
  from public.item_field_library l, ifp_ids i where l.field_group = 'ACTION' and l.code = 'ISSUE_CN';

select results_eq(
  $$select r.code, r.source_scope_type from ifp_ids i, rms_private.resolve_item_field_profile(i.p1) r
     where r.field_group = 'CATEGORISATION'$$,
  $$values ('PGTAP_B2', 'CATEGORY'), ('PGTAP_B1', 'CATEGORY')$$,
  'AMD-10: a product inherits its category''s fields, in assignment order');

insert into public.item_field_assignments (field_id, field_group, scope_type, subcategory_id)
select l.id, 'CATEGORISATION', 'SUBCATEGORY', i.sub
  from public.item_field_library l, ifp_ids i where l.code = 'PGTAP_B3';
select results_eq(
  $$select r.code, r.source_scope_type from ifp_ids i, rms_private.resolve_item_field_profile(i.p1) r
     where r.field_group = 'CATEGORISATION'$$,
  $$values ('PGTAP_B3', 'SUBCATEGORY')$$,
  'AMD-10: SUBCATEGORY overrides CATEGORY (most specific scope wins, no merge)');
select results_eq(
  $$select r.code from ifp_ids i, rms_private.resolve_item_field_profile(i.p3) r
     where r.field_group = 'CATEGORISATION'$$,
  $$values ('PGTAP_B2'), ('PGTAP_B1')$$,
  'AMD-10: a product without a sub-category falls back to its category');

-- PRODUCT override with only an exclusion: P1 gets no buckets; P2 keeps the sub-category's.
insert into public.item_field_assignments (field_id, field_group, scope_type, product_id, is_included)
select l.id, 'CATEGORISATION', 'PRODUCT', i.p1, false
  from public.item_field_library l, ifp_ids i where l.code = 'PGTAP_B3';
select is_empty(
  $$select 1 from ifp_ids i, rms_private.resolve_item_field_profile(i.p1) r where r.field_group = 'CATEGORISATION'$$,
  'AMD-10: a PRODUCT override of exclusions only yields no fields and blocks inheritance');
select results_eq(
  $$select r.code from ifp_ids i, rms_private.resolve_item_field_profile(i.p2) r where r.field_group = 'CATEGORISATION'$$,
  $$values ('PGTAP_B3')$$, 'AMD-10: overrides are per product');
select results_eq(
  $$select r.code, r.source_scope_type from ifp_ids i, rms_private.resolve_item_field_profile(i.p1) r
     where r.field_group = 'ACTION'$$,
  $$values ('ISSUE_CN', 'CATEGORY')$$,
  'AMD-10: groups resolve independently (P1 overrides buckets, inherits actions)');

update public.item_field_library set is_active = false where code = 'PGTAP_B1';
select results_eq(
  $$select r.code from ifp_ids i, rms_private.resolve_item_field_profile(i.p3) r where r.field_group = 'CATEGORISATION'$$,
  $$values ('PGTAP_B2')$$, 'AMD-10: inactive library fields drop out of every profile');

-- ---------------------------------------------------------------------------
-- Versions (G-18): one insert-only snapshot per transaction; resolve against a version
-- ---------------------------------------------------------------------------
set constraints all immediate;   -- fire the deferred version trigger now (this test never commits)
select ok(
  (select snapshot -> 'library' @> '[{"code": "PGTAP_B3"}]'::jsonb
     from public.item_field_profile_versions where txid = txid_current()),
  'G-18: the transaction''s changes produced a profile version with a full snapshot');
create temporary table ifp_ver on commit drop as
select id from public.item_field_profile_versions where txid = txid_current();
select throws_like(
  $$update public.item_field_profile_versions set snapshot = '{}'::jsonb where id = (select id from ifp_ver)$$,
  '%insert-only%', 'G-18: profile versions are insert-only');

-- A later change (same transaction, already versioned) shows live but not in the stored version.
update public.item_field_library set is_active = true where code = 'PGTAP_B1';
select results_eq(
  $$select r.code from ifp_ids i, rms_private.resolve_item_field_profile(i.p3, (select id from ifp_ver)) r
     where r.field_group = 'CATEGORISATION'$$,
  $$values ('PGTAP_B2')$$, 'G-18: resolving against a stored version uses its snapshot');
select results_eq(
  $$select r.code from ifp_ids i, rms_private.resolve_item_field_profile(i.p3) r where r.field_group = 'CATEGORISATION'$$,
  $$values ('PGTAP_B2'), ('PGTAP_B1')$$, 'live resolution sees the current configuration');

-- ---------------------------------------------------------------------------
-- GS stamps its profile version on leaving CATEGORISATION (AMD-10, G-18); item counts (AMD-11)
-- ---------------------------------------------------------------------------
insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count)
select 'PGTAP-PH4-1', v.id, 'COURIER_PARCEL', 'A', '1', 1
  from public.workflow_versions v join public.workflow_definitions d on d.id = v.workflow_definition_id
 where d.code = 'RMS_STANDARD' and v.status = 'PUBLISHED';
insert into public.gs_items (gs_id, line_no, product_id, category_id, documented_qty, received_qty)
select g.id, 1, i.p3, i.cat, 0, 4 from public.goods_slips g, ifp_ids i where g.gs_no = 'PGTAP-PH4-1';
set local session_replication_role = replica;
update public.goods_slips set status = 'CATEGORISATION' where gs_no = 'PGTAP-PH4-1';
set local session_replication_role = origin;

select throws_like(
  $$insert into public.gs_item_counts (gs_item_id, field_id, field_code, label_snapshot, qty)
    select gi.id, l.id, 'x', 'x', 2 from public.gs_items gi join public.goods_slips g on g.id = gi.gs_id,
           public.item_field_library l
     where g.gs_no = 'PGTAP-PH4-1' and l.field_group = 'ITEM_COUNT' and l.code = 'PACKAGING'$$,
  'G-18:%not enabled%', 'AMD-11: a count field must be enabled in the item''s profile');
select throws_like(
  $$insert into public.gs_item_counts (gs_item_id, field_id, field_code, label_snapshot, qty)
    select gi.id, l.id, 'x', 'x', 2 from public.gs_items gi join public.goods_slips g on g.id = gi.gs_id,
           public.item_field_library l
     where g.gs_no = 'PGTAP-PH4-1' and l.code = 'PGTAP_B2'$$,
  'G-18:%not an item count field%', 'AMD-11: buckets are not item counts');
insert into public.item_field_assignments (field_id, field_group, scope_type, category_id)
select l.id, 'ITEM_COUNT', 'CATEGORY', i.cat
  from public.item_field_library l, ifp_ids i where l.field_group = 'ITEM_COUNT' and l.code = 'PACKAGING';
insert into public.gs_item_counts (gs_item_id, field_id, field_code, label_snapshot, qty)
select gi.id, l.id, 'x', 'x', 2 from public.gs_items gi join public.goods_slips g on g.id = gi.gs_id,
       public.item_field_library l
 where g.gs_no = 'PGTAP-PH4-1' and l.field_group = 'ITEM_COUNT' and l.code = 'PACKAGING';
select is(
  (select field_code || '|' || label_snapshot from public.gs_item_counts c
     join public.gs_items gi on gi.id = c.gs_item_id join public.goods_slips g on g.id = gi.gs_id
    where g.gs_no = 'PGTAP-PH4-1'),
  'PACKAGING|Packaging', 'G-18: an item count stores the code and label snapshot');

update public.goods_slips set category_code = 'RO', original_category_code = 'RO', status = 'INSPECTION'
 where gs_no = 'PGTAP-PH4-1';
select is(
  (select item_field_profile_version_id from public.goods_slips where gs_no = 'PGTAP-PH4-1'),
  (select id from public.item_field_profile_versions order by version_no desc limit 1),
  'AMD-10: a GS stores the profile version it was categorised under');
select throws_like(
  $$update public.goods_slips set item_field_profile_version_id = null where gs_no = 'PGTAP-PH4-1'$$,
  'G-18:%immutable%', 'G-18: the stamped profile version cannot change');

-- ---------------------------------------------------------------------------
-- rm_item_actions: FK to the ACTION library + label snapshot (AMD-16, G-18)
-- ---------------------------------------------------------------------------
insert into auth.users (id, email)
values ('11111111-1111-1111-1111-111111111111', 'test_rm@example.com')
on conflict do nothing;

insert into public.profiles (id, full_name, is_active)
values ('11111111-1111-1111-1111-111111111111', 'Test RM', true)
on conflict do nothing;

select throws_ok(
  $$insert into public.rm_item_actions (gs_item_id, action_code, qty, decided_by)
    select gi.id, 'MADE_UP_ACTION', 1, (select id from public.profiles limit 1)
      from public.gs_items gi join public.goods_slips g on g.id = gi.gs_id where g.gs_no = 'PGTAP-PH4-1'$$,
  '23503', null, 'AMD-16: an action code outside the action library is rejected');
insert into public.rm_item_actions (gs_item_id, action_code, qty, decided_by)
select gi.id, 'SEND_NEW', 1, (select id from public.profiles limit 1)
  from public.gs_items gi join public.goods_slips g on g.id = gi.gs_id where g.gs_no = 'PGTAP-PH4-1';
select is(
  (select ra.action_label from public.rm_item_actions ra join public.gs_items gi on gi.id = ra.gs_item_id
     join public.goods_slips g on g.id = gi.gs_id where g.gs_no = 'PGTAP-PH4-1'),
  'Send New Unit', 'G-18: an RM action stores the action label in force at the time');
select throws_like(
  $$update public.rm_item_actions set action_label = 'Changed'
     where gs_item_id in (select gi.id from public.gs_items gi join public.goods_slips g on g.id = gi.gs_id
                           where g.gs_no = 'PGTAP-PH4-1')$$,
  'G-18:%immutable%', 'G-18: the action label snapshot is immutable');
update public.item_field_library set is_active = false where field_group = 'ACTION' and code = 'PENDING_BP';
select throws_like(
  $$insert into public.rm_item_actions (gs_item_id, action_code, qty, decided_by)
    select gi.id, 'PENDING_BP', 1, (select id from public.profiles limit 1)
      from public.gs_items gi join public.goods_slips g on g.id = gi.gs_id where g.gs_no = 'PGTAP-PH4-1'$$,
  'G-18:%inactive%', 'AMD-16: an inactive action cannot be used on new rows');

select * from finish();
rollback;
