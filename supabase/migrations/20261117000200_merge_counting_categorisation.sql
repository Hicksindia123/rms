-- DEC-53: Counting and Categorisation merged into one step (AMD-08 + AMD-09).
--
-- The Inward Verifier now records each item line together with its condition split
-- (gs_item_buckets) and item counts (gs_item_counts) while the GS is still in ITEMIZATION.
-- Only change: ITEMIZATION joins the statuses in which buckets/counts may be written.
-- Every other G-18 check (field group, profile-enabled field, immutable snapshot) is kept
-- verbatim, the G-03 status chain ITEMIZATION -> CATEGORISATION -> RM_REVIEW is untouched and
-- the G-19 conservation check (validate_item_bucket_conservation) still runs on
-- CATEGORISATION -> RM_REVIEW and RM_REVIEW -> HELD_AT_INTERMEDIATE_STORE.
-- Note: item_field_profile_version_id is null until the GS leaves CATEGORISATION, so the
-- resolver uses the current profile version during ITEMIZATION exactly as in CATEGORISATION.

create or replace function rms_private.gs_item_buckets_guard()
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
    if v_status is not null and v_status not in ('ITEMIZATION', 'CATEGORISATION', 'RM_REVIEW') then
      raise exception 'G-18: item buckets change only while the GS is in ITEMIZATION (Counting & Categorisation), CATEGORISATION or RM_REVIEW (status %)', v_status
        using errcode = '23514';
    end if;
    return old;
  end if;

  if tg_op = 'UPDATE' and (new.gs_item_id, new.field_id, new.field_code, new.label_snapshot)
                          is distinct from (old.gs_item_id, old.field_id, old.field_code, old.label_snapshot) then
    raise exception 'G-18: the field and label snapshot of an item bucket are immutable' using errcode = '42501';
  end if;

  select gi.product_id, gs.status, gs.item_field_profile_version_id into v_product, v_status, v_version
    from public.gs_items gi join public.goods_slips gs on gs.id = gi.gs_id where gi.id = new.gs_item_id;
  if v_status not in ('ITEMIZATION', 'CATEGORISATION', 'RM_REVIEW') then
    raise exception 'G-18: item buckets are recorded only while the GS is in ITEMIZATION (Counting & Categorisation), CATEGORISATION or RM_REVIEW (status %)', v_status
      using errcode = '23514';
  end if;

  if tg_op = 'INSERT' then
    select * into v_lib from public.item_field_library where id = new.field_id;
    if v_lib.field_group is distinct from 'CATEGORISATION' then
      raise exception 'G-18: % is not a categorisation bucket field', coalesce(v_lib.code, new.field_id::text)
        using errcode = '23514';
    end if;
    if not exists (select 1 from rms_private.resolve_item_field_profile(v_product, v_version) r
                    where r.field_group = 'CATEGORISATION' and r.field_id = new.field_id) then
      raise exception 'G-18: bucket % is not enabled in the item field profile of this product', v_lib.code
        using errcode = '23514';
    end if;
    -- label snapshot (G-18): the label in force when the bucket was recorded
    new.field_code := v_lib.code;
    new.label_snapshot := v_lib.label;
  end if;
  return new;
end
$$;

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
    if v_status is not null and v_status not in ('ITEMIZATION', 'CATEGORISATION', 'RM_REVIEW') then
      raise exception 'G-18: item counts change only while the GS is in ITEMIZATION (Counting & Categorisation), CATEGORISATION or RM_REVIEW (status %)', v_status
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
  if v_status not in ('ITEMIZATION', 'CATEGORISATION', 'RM_REVIEW') then
    raise exception 'G-18: item counts are recorded only while the GS is in ITEMIZATION (Counting & Categorisation), CATEGORISATION or RM_REVIEW (status %)', v_status
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

-- Journey menu (DB configuration, rule e): one Inward Verifier entry for both activities.
update public.journey_steps
   set label = 'Counting & Categorisation',
       hint  = 'Add each item with its quantities and condition split',
       updated_at = now()
 where code = 'COUNTING';
