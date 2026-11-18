-- Migration: 20261117000300_g1_rm_edits_in_review.sql
-- Description: G1 - RM edits anything in review (DEC-54; Q1, Q2; T1-T3)
--   1. gs_items_guard: allow insert / delete / product change in RM_REVIEW while no transfer slip exists.
--   2. gs_item_buckets_guard & gs_item_counts_guard: block modifications in RM_REVIEW once transfer slip exists.
--   3. rm_review_revisions: allow new actions RM_ADD_LINE, RM_REMOVE_LINE, RM_CHANGE_PRODUCT.
--   4. notification_event_types & rules: register RM_REVIEW_CHANGED and notify INWARD_VERIFIER.

-- 1. Update gs_items_guard
create or replace function rms_private.gs_items_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_row        public.gs_items;
  v_status     text;
  v_transfer   uuid;
  v_correction uuid;
begin
  v_row := case when tg_op = 'DELETE' then old else new end;
  select status, transfer_slip_id into v_status, v_transfer from public.goods_slips where id = v_row.gs_id;
  if v_status is null then
    -- cascade from a deleted GS, or a missing GS (the FK reports G-01 on insert)
    return case when tg_op = 'DELETE' then old else new end;
  end if;
  if v_status in ('GATE_CREATED', 'UNBOXING', 'ITEMIZATION') then
    return case when tg_op = 'DELETE' then old else new end;
  end if;

  -- Phase G1 (DEC-54): RM Review allows insert / delete / product change / qty update while no transfer slip exists
  if v_status = 'RM_REVIEW' then
    if v_transfer is not null then
      raise exception 'Item lines cannot be modified once the transfer slip exists (status %)', v_status
        using errcode = '23514';
    end if;
    if tg_op = 'DELETE' then
      return old;
    end if;
    if tg_op = 'INSERT' then
      return new;
    end if;
    if new.gs_id <> old.gs_id or new.line_no <> old.line_no then
      raise exception 'Item line number or goods slip reference cannot change' using errcode = '23514';
    end if;
    return new;
  end if;

  if tg_op <> 'UPDATE' then
    raise exception 'Item lines cannot be added or removed once the GS is categorised (status %)', v_status
      using errcode = '23514';
  end if;
  if new.gs_id <> old.gs_id or new.line_no <> old.line_no or new.product_id <> old.product_id
     or new.category_id <> old.category_id
     or new.product_code_snapshot is distinct from old.product_code_snapshot
     or new.product_name_snapshot is distinct from old.product_name_snapshot
     or new.category_code_snapshot is distinct from old.category_code_snapshot then
    raise exception 'The product of a categorised item line cannot change' using errcode = '23514';
  end if;
  if new.documented_qty = old.documented_qty and new.received_qty = old.received_qty then
    return new;  -- remarks / updated_at only
  end if;

  -- Quantities change only by applying an APPROVED, not yet applied correction for this line.
  v_correction := nullif(current_setting('app.item_correction_id', true), '')::uuid;
  if v_correction is null or not exists (
       select 1 from public.gs_item_corrections c
        where c.id = v_correction and c.gs_item_id = new.id and c.status = 'APPROVED'
          and c.applied_at is null
          and c.old_documented_qty = old.documented_qty and c.old_received_qty = old.received_qty
          and c.new_documented_qty = new.documented_qty and c.new_received_qty = new.received_qty) then
    raise exception 'Item quantities can change after categorisation only through an approved line correction'
      using errcode = '23514';
  end if;
  return new;
end;
$$;

-- 2. Update gs_item_buckets_guard to block changes once transfer slip exists
create or replace function rms_private.gs_item_buckets_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_product  uuid;
  v_status   text;
  v_version  uuid;
  v_transfer uuid;
  v_lib      public.item_field_library%rowtype;
begin
  if tg_op = 'DELETE' then
    select gs.status, gs.transfer_slip_id into v_status, v_transfer
      from public.gs_items gi join public.goods_slips gs on gs.id = gi.gs_id where gi.id = old.gs_item_id;
    if v_status is not null and v_status not in ('ITEMIZATION', 'CATEGORISATION', 'RM_REVIEW') then
      raise exception 'G-18: item buckets change only while the GS is in ITEMIZATION (Counting & Categorisation), CATEGORISATION or RM_REVIEW (status %)', v_status
        using errcode = '23514';
    end if;
    if v_status = 'RM_REVIEW' and v_transfer is not null then
      raise exception 'G-18: item buckets cannot be modified once the transfer slip exists' using errcode = '23514';
    end if;
    return old;
  end if;

  if tg_op = 'UPDATE' and (new.gs_item_id, new.field_id, new.field_code, new.label_snapshot)
                          is distinct from (old.gs_item_id, old.field_id, old.field_code, old.label_snapshot) then
    raise exception 'G-18: the field and label snapshot of an item bucket are immutable' using errcode = '42501';
  end if;

  select gi.product_id, gs.status, gs.item_field_profile_version_id, gs.transfer_slip_id
    into v_product, v_status, v_version, v_transfer
    from public.gs_items gi join public.goods_slips gs on gs.id = gi.gs_id where gi.id = new.gs_item_id;
  if v_status not in ('ITEMIZATION', 'CATEGORISATION', 'RM_REVIEW') then
    raise exception 'G-18: item buckets are recorded only while the GS is in ITEMIZATION (Counting & Categorisation), CATEGORISATION or RM_REVIEW (status %)', v_status
      using errcode = '23514';
  end if;
  if v_status = 'RM_REVIEW' and v_transfer is not null then
    raise exception 'G-18: item buckets cannot be modified once the transfer slip exists' using errcode = '23514';
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

-- 3. Update gs_item_counts_guard to block changes once transfer slip exists
create or replace function rms_private.gs_item_counts_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_product  uuid;
  v_status   text;
  v_version  uuid;
  v_transfer uuid;
  v_lib      public.item_field_library%rowtype;
begin
  if tg_op = 'DELETE' then
    select gs.status, gs.transfer_slip_id into v_status, v_transfer
      from public.gs_items gi join public.goods_slips gs on gs.id = gi.gs_id where gi.id = old.gs_item_id;
    if v_status is not null and v_status not in ('ITEMIZATION', 'CATEGORISATION', 'RM_REVIEW') then
      raise exception 'G-18: item counts change only while the GS is in ITEMIZATION (Counting & Categorisation), CATEGORISATION or RM_REVIEW (status %)', v_status
        using errcode = '23514';
    end if;
    if v_status = 'RM_REVIEW' and v_transfer is not null then
      raise exception 'G-18: item counts cannot be modified once the transfer slip exists' using errcode = '23514';
    end if;
    return old;
  end if;

  if tg_op = 'UPDATE' and (new.gs_item_id, new.field_id, new.field_code, new.label_snapshot)
                          is distinct from (old.gs_item_id, old.field_id, old.field_code, old.label_snapshot) then
    raise exception 'G-18: the field and label snapshot of an item count are immutable' using errcode = '42501';
  end if;

  select gi.product_id, gs.status, gs.item_field_profile_version_id, gs.transfer_slip_id
    into v_product, v_status, v_version, v_transfer
    from public.gs_items gi join public.goods_slips gs on gs.id = gi.gs_id where gi.id = new.gs_item_id;
  if v_status not in ('ITEMIZATION', 'CATEGORISATION', 'RM_REVIEW') then
    raise exception 'G-18: item counts are recorded only while the GS is in ITEMIZATION (Counting & Categorisation), CATEGORISATION or RM_REVIEW (status %)', v_status
      using errcode = '23514';
  end if;
  if v_status = 'RM_REVIEW' and v_transfer is not null then
    raise exception 'G-18: item counts cannot be modified once the transfer slip exists' using errcode = '23514';
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

-- 4. Extend rm_review_revisions action check
alter table public.rm_review_revisions
  drop constraint if exists rm_review_revisions_action_check;

alter table public.rm_review_revisions
  add constraint rm_review_revisions_action_check
  check (action in ('SUBMITTED', 'RM_EDIT', 'RM_SENT_BACK', 'RM_APPROVED', 'RM_ADD_LINE', 'RM_REMOVE_LINE', 'RM_CHANGE_PRODUCT'));

-- 5. Notification event type and rule for RM_REVIEW_CHANGED
insert into public.notification_event_types
  (code, label, description, category, default_priority, is_mandatory, source_ref, sort_order)
values
  ('RM_REVIEW_CHANGED', 'RM review changed',
   'Replacement Manager modified item lines or condition split during review (DEC-54).',
   'WORKFLOW', 'NORMAL', false, 'DEC-54', 510)
on conflict (code) do update
  set label = excluded.label, description = excluded.description,
      default_priority = excluded.default_priority, source_ref = excluded.source_ref;

insert into public.notification_templates (event_type, channel, version_no, subject, body, change_reason)
select 'RM_REVIEW_CHANGED', 'EMAIL', 1,
       '[{app_name}] {title}',
       E'Hello {recipient_name},\n\n{title}\n\n{body}\n\nEvent: {event_label}\nPriority: {priority}\nOpen in RMS: {link}\n\n— {app_name} (automated message; manage email preferences in RMS)',
       'DEC-54 default'
 where not exists (
   select 1 from public.notification_templates
    where event_type = 'RM_REVIEW_CHANGED' and channel = 'EMAIL'
 );

insert into public.notification_rules
  (event_type, name, include_context_recipients, recipient_role_codes, channels, priority, is_active)
select 'RM_REVIEW_CHANGED', 'Verifier: RM modified items during review (DEC-54)', true,
       array['INWARD_VERIFIER'], array['IN_APP'], 'NORMAL', true
 where not exists (select 1 from public.notification_rules where event_type = 'RM_REVIEW_CHANGED')
   -- 2026-11-18 (G2): roles are seed data; on a fresh reset seed.sql adds this rule instead.
   and exists (select 1 from public.roles where code = 'INWARD_VERIFIER');
