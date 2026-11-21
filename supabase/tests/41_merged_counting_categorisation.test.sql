-- DEC-53 pgTAP: Counting & Categorisation merged. Buckets / item counts may be written while the
-- GS is ITEMIZATION; the G-18 guards still refuse them in any other earlier / later status and the
-- G-19 conservation check still gates leaving CATEGORISATION (DEC-64: the lock).
begin;
create extension if not exists pgtap with schema extensions;
select plan(8);

create temp table _m_gs (id uuid);
with ins as (
  insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count, status)
  select 'PGTAP-DEC53-GS', v.id, 'COURIER_PARCEL', 'Test Courier', 'DEC53', 1, 'ITEMIZATION'
    from public.workflow_versions v
    join public.workflow_definitions d on d.id = v.workflow_definition_id and d.code = 'RMS_STANDARD'
   where v.status = 'PUBLISHED'
  returning id
)
insert into _m_gs (id) select id from ins;

-- A product whose resolved profile has a categorisation bucket.
create temp table _m_item (id uuid, product_id uuid);
with p as (
  select p.id, p.category_id
    from public.products p
   where exists (select 1 from rms_private.resolve_item_field_profile(p.id) r
                  where r.field_group = 'CATEGORISATION')
   limit 1
), ins as (
  insert into public.gs_items (gs_id, line_no, product_id, category_id, documented_qty, received_qty)
  select (select id from _m_gs), 1, p.id, p.category_id, 4, 3 from p
  returning id, product_id
)
insert into _m_item (id, product_id) select id, product_id from ins;

create temp table _m_bucket (id uuid);
insert into _m_bucket (id)
select r.field_id
  from rms_private.resolve_item_field_profile((select product_id from _m_item)) r
 where r.field_group = 'CATEGORISATION'
 limit 1;

-- 1. The split is recorded with the line while the GS is ITEMIZATION (DEC-53).
select lives_ok(
  $$insert into public.gs_item_buckets (gs_item_id, field_id, qty)
    select (select id from _m_item), (select id from _m_bucket), 2$$,
  'DEC-53: bucket insert allowed while the GS is ITEMIZATION'
);

-- 2. ... and edited while ITEMIZATION.
select lives_ok(
  $$update public.gs_item_buckets set qty = 3 where gs_item_id = (select id from _m_item)$$,
  'DEC-53: bucket update allowed while the GS is ITEMIZATION'
);

-- 3. G-18 snapshot still taken on insert.
select is(
  (select label_snapshot from public.gs_item_buckets where gs_item_id = (select id from _m_item)),
  (select label from public.item_field_library where id = (select id from _m_bucket)),
  'G-18: label snapshot still copied from the library'
);

-- 4. G-18: a field that is not a categorisation bucket is still refused in ITEMIZATION.
select throws_like(
  $$insert into public.gs_item_buckets (gs_item_id, field_id, qty)
    select (select id from _m_item), l.id, 1
      from public.item_field_library l where l.field_group <> 'CATEGORISATION' limit 1$$,
  '%G-18%is not a categorisation bucket field%',
  'G-18: non-bucket field refused in ITEMIZATION'
);

-- 5. A line with a split can still be deleted in ITEMIZATION (buckets cascade).
select lives_ok(
  $$with ins as (
      insert into public.gs_items (gs_id, line_no, product_id, category_id, documented_qty, received_qty)
      select gs_id, 2, product_id, category_id, 1, 1 from public.gs_items where id = (select id from _m_item)
      returning id)
    insert into public.gs_item_buckets (gs_item_id, field_id, qty)
    select ins.id, (select id from _m_bucket), 1 from ins;
    delete from public.gs_items where gs_id = (select id from _m_gs) and line_no = 2$$,
  'DEC-53: deleting a line with a split works in ITEMIZATION'
);

-- 6. Still refused before counting (UNBOXING). Setup only: triggers off to force the status.
set session_replication_role = replica;
update public.goods_slips set status = 'UNBOXING' where id = (select id from _m_gs);
set session_replication_role = origin;
select throws_like(
  $$update public.gs_item_buckets set qty = 1 where gs_item_id = (select id from _m_item)$$,
  '%G-18: item buckets%',
  'G-18: buckets still frozen in UNBOXING'
);

-- 7. G-19 still gates leaving CATEGORISATION: the lock (DEC-64; split 3 of 3 here, make it 2).
set session_replication_role = replica;
update public.goods_slips set status = 'CATEGORISATION', category_code = 'RO', original_category_code = 'RO'
 where id = (select id from _m_gs);
update public.gs_item_buckets set qty = 2 where gs_item_id = (select id from _m_item);
set session_replication_role = origin;
select throws_like(
  $$update public.goods_slips set status = 'PENDING_TRANSFER_SLIP' where id = (select id from _m_gs)$$,
  '%G-19%',
  'G-19: unbalanced split still blocks the categorisation lock (DEC-64)'
);

-- 8. Still refused after the GS left review (HELD_AT_INTERMEDIATE_STORE).
set session_replication_role = replica;
update public.goods_slips set status = 'HELD_AT_INTERMEDIATE_STORE' where id = (select id from _m_gs);
set session_replication_role = origin;
select throws_like(
  $$update public.gs_item_buckets set qty = 3 where gs_item_id = (select id from _m_item)$$,
  '%G-18: item buckets%',
  'G-18: buckets frozen once held at the intermediate store'
);

select * from finish();
rollback;
