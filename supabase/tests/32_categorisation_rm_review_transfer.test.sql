-- Change plan 2026-11-12 Phase 5 pgTAP: Item Categorisation, RM Review, Transfer Slip, Intermediate Store
-- (AMD-09, AMD-11, AMD-12, AMD-13; G-03, G-16, G-18, G-19; DEC-40).
begin;
create extension if not exists pgtap with schema extensions;
select plan(18);

-- 1. Table existence & columns
select has_table('public', 'gs_item_buckets', 'gs_item_buckets exists');
select has_table('public', 'rm_review_revisions', 'rm_review_revisions exists');
select has_column('public', 'goods_slips', 'counted_by', 'goods_slips.counted_by exists');
select has_column('public', 'goods_slips', 'transfer_slip_id', 'goods_slips.transfer_slip_id exists');

-- 2. Status constraint accepts HELD_AT_INTERMEDIATE_STORE
select lives_ok(
  $$insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count, status)
    select 'PGTAP-PH5-TEST-STATUS', v.id, 'COURIER_PARCEL', 'Test Courier', '123', 1, 'HELD_AT_INTERMEDIATE_STORE'
      from public.workflow_versions v
      join public.workflow_definitions d on d.id = v.workflow_definition_id and d.code = 'RMS_STANDARD'
     where v.status = 'PUBLISHED'$$,
  'goods_slips.status accepts HELD_AT_INTERMEDIATE_STORE'
);

-- Setup fixtures for G-19 bucket conservation testing
create temp table _fix_gs (id uuid);
with ins as (
  insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count, status)
  select 'PGTAP-PH5-G19-GS', v.id, 'COURIER_PARCEL', 'Test Courier', '456', 1, 'ITEMIZATION'
    from public.workflow_versions v
    join public.workflow_definitions d on d.id = v.workflow_definition_id and d.code = 'RMS_STANDARD'
   where v.status = 'PUBLISHED'
  returning id
)
insert into _fix_gs (id) select id from ins;

create temp table _fix_item (id uuid, product_id uuid);
with ins as (
  insert into public.gs_items (gs_id, line_no, product_id, category_id, documented_qty, received_qty)
  select (select id from _fix_gs), 1, p.id, p.category_id, 10, 10
    from public.products p
   -- a product whose profile has a bucket (the full product master includes some without)
   where exists (select 1 from rms_private.resolve_item_field_profile(p.id) r
                  where r.field_group = 'CATEGORISATION')
   limit 1
  returning id, product_id
)
insert into _fix_item (id, product_id) select id, product_id from ins;

-- Transition GS to CATEGORISATION
update public.goods_slips set status = 'CATEGORISATION' where id = (select id from _fix_gs);

create temp table _fix_bucket (id uuid, code text);
insert into _fix_bucket (id, code)
select r.field_id, r.code
  from rms_private.resolve_item_field_profile((select product_id from _fix_item)) r
 where r.field_group = 'CATEGORISATION'
 limit 1;

-- 3. Inserting bucket with quantity
select lives_ok(
  $$insert into public.gs_item_buckets (gs_item_id, field_id, qty)
    select (select id from _fix_item), (select id from _fix_bucket), 7$$,
  'can insert bucket quantity while in CATEGORISATION'
);

-- 4. Label snapshot taken from library
select is(
  (select label_snapshot from public.gs_item_buckets where gs_item_id = (select id from _fix_item)),
  (select label from public.item_field_library where id = (select id from _fix_bucket)),
  'label_snapshot populated from item_field_library on insert'
);

-- P4 (DEC-64): CATEGORISATION leaves through the lock (PENDING_TRANSFER_SLIP), not RM_REVIEW.
insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data)
values ('aaaaaaaa-0000-4000-8000-0000000000d4', 'pgtap-p4-re@example.test',
        '{"rms_activate": true}'::jsonb, '{"full_name": "pgTAP RE"}'::jsonb);
update public.goods_slips
   set category_code = 'RO', original_category_code = 'RO',
       categorisation_locked_at = now(), categorisation_locked_by = 'aaaaaaaa-0000-4000-8000-0000000000d4'
 where id = (select id from _fix_gs);

-- 5. G-19 Conservation Guard: Mismatch (7 != 10) blocks the lock
select throws_like(
  $$update public.goods_slips set status = 'PENDING_TRANSFER_SLIP' where id = (select id from _fix_gs)$$,
  '%G-19%sum of bucket quantities (7) must equal counted quantity (10)%',
  'G-19: sum of bucket quantities != counted qty rejects the categorisation lock'
);

-- 6. Add remaining quantity so sum = 10
select lives_ok(
  $$update public.gs_item_buckets set qty = 10 where gs_item_id = (select id from _fix_item)$$,
  'can update bucket quantity to match counted qty'
);

-- 7. Now the lock succeeds
select lives_ok(
  $$update public.goods_slips set status = 'PENDING_TRANSFER_SLIP' where id = (select id from _fix_gs)$$,
  'transition from CATEGORISATION to PENDING_TRANSFER_SLIP succeeds when G-19 is satisfied'
);

-- 8. GS profile version is stamped when leaving CATEGORISATION
select isnt(
  (select item_field_profile_version_id from public.goods_slips where id = (select id from _fix_gs)),
  null,
  'item_field_profile_version_id is stamped when leaving CATEGORISATION'
);

-- 9. After the lock, a user without itemization.configure cannot change the split (DEC-64 d)
select throws_like(
  $$update public.gs_item_buckets set qty = 9 where gs_item_id = (select id from _fix_item)$$,
  'DEC-64:%Super Admin or Management%',
  'DEC-64: buckets of a locked GS change only for Super Admin / Management'
);

-- 10. A locked GS leaves only through its transfer slips (P5)
select throws_like(
  $$update public.goods_slips set status = 'HELD_AT_INTERMEDIATE_STORE' where id = (select id from _fix_gs)$$,
  'G-03:%transfer slips%',
  'G-03: PENDING_TRANSFER_SLIP is left only through the transfer slip flow'
);

-- 11-12. Legacy GS in RM_REVIEW: no RM edits any more (Q9), send back still works
create temp table _fix_gs2 (id uuid);
with ins as (
  insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count, status)
  select 'PGTAP-PH5-SENDBACK-GS', v.id, 'COURIER_PARCEL', 'Test Courier', '789', 1, 'ITEMIZATION'
    from public.workflow_versions v
    join public.workflow_definitions d on d.id = v.workflow_definition_id and d.code = 'RMS_STANDARD'
   where v.status = 'PUBLISHED'
  returning id
)
insert into _fix_gs2 (id) select id from ins;

create temp table _fix_item2 (id uuid, product_id uuid);
with ins as (
  insert into public.gs_items (gs_id, line_no, product_id, category_id, documented_qty, received_qty)
  select (select id from _fix_gs2), 1, p.id, p.category_id, 5, 5
    from public.products p
   where exists (select 1 from rms_private.resolve_item_field_profile(p.id) r
                  where r.field_group = 'CATEGORISATION')
   limit 1
  returning id, product_id
)
insert into _fix_item2 (id, product_id) select id, product_id from ins;

-- Setup only: a GS that reached RM_REVIEW before DEC-64 (the route is closed now).
set local session_replication_role = replica;
update public.goods_slips set status = 'RM_REVIEW' where id = (select id from _fix_gs2);
set local session_replication_role = origin;

select is(
  (select status from public.goods_slips where id = (select id from _fix_gs2)),
  'RM_REVIEW',
  'GS is in RM_REVIEW'
);
select throws_like(
  $$insert into public.gs_items (gs_id, line_no, product_id, category_id, documented_qty, received_qty)
    select (select id from _fix_gs2), 2, product_id, (select category_id from public.products where id = product_id), 1, 1
      from _fix_item2$$,
  '%cannot be added or removed%',
  'DEC-64 (Q9): the RM no longer adds lines in RM_REVIEW'
);

-- Send back to CATEGORISATION
select lives_ok(
  $$update public.goods_slips set status = 'CATEGORISATION' where id = (select id from _fix_gs2)$$,
  'RM send back to CATEGORISATION succeeds'
);

-- 13. rm_review_revisions table works and records revisions
select lives_ok(
  $$insert into public.rm_review_revisions (gs_id, revision_no, action, remarks, items_snapshot)
    select (select id from _fix_gs2), 1, 'SUBMITTED', 'Initial submit', '[]'::jsonb$$,
  'can insert rm_review_revisions record'
);

select is(
  (select action from public.rm_review_revisions where gs_id = (select id from _fix_gs2) and revision_no = 1),
  'SUBMITTED',
  'rm_review_revisions records SUBMITTED action'
);

select * from finish();
rollback;
