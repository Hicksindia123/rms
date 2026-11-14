-- Change plan 2026-11-12 · Phase 5 — Item Categorisation, RM Review, Transfer Slip, Intermediate Store
-- (docs/RMS_MASTER_PLAN_ADDENDUM_2026-11.md AMD-09, AMD-11, AMD-12, AMD-13; G-03, G-07, G-09, G-16, G-18, G-19; DEC-40).
--
-- 1. gs_item_buckets (AMD-09): per item, quantity split across the resolved categorisation buckets
--    (Good, Damaged, Body Broken, Wastage, ...; Phase 4 library entries).
--    - Trigger gs_item_buckets_guard: only fields belonging to CATEGORISATION in the item's resolved
--      item field profile can be added. Label snapshot taken from library at insert (G-18).
--    - Editable while GS is in CATEGORISATION or RM_REVIEW.
-- 2. Conservation Guard G-19 (AMD-09): for every item on a goods slip, sum(bucket qty) = counted qty (received_qty).
--    Enforced in DB trigger rms_private.goods_slips_g03_guard and validate_item_bucket_conservation.
-- 3. goods_slips.counted_by: tracks the user who submitted counting (INWARD_VERIFIER). Categorisation must
--    be submitted by the same user who counted (or Super Admin).
-- 4. rm_review_revisions (AMD-12): revision history of categorisation & RM review actions:
--    (SUBMITTED, RM_EDIT, RM_SENT_BACK, RM_APPROVED), with full item snapshots, reason, actor, timestamp.
-- 5. goods_slips_status_check: accepts 'HELD_AT_INTERMEDIATE_STORE' (AMD-13).
-- 6. goods_slips.transfer_slip_id: links to the auto-generated Transfer Slip (TRF/...) handing goods to
--    INTERMEDIATE_STORE_MANAGER.
-- 7. GS_STATUS: seeds 'HELD_AT_INTERMEDIATE_STORE' label 'Held at Intermediate Store' (AMD-13).

-- ===========================================================================
-- 1. Status list extension: HELD_AT_INTERMEDIATE_STORE
-- ===========================================================================
do $$
declare
  c record;
begin
  for c in
    select conname from pg_constraint
     where conrelid = 'public.goods_slips'::regclass and contype = 'c'
       and pg_get_constraintdef(oid) like '%''GATE_CREATED''%'
       and pg_get_constraintdef(oid) like '%''CATEGORISATION''%'
  loop
    execute format('alter table public.goods_slips drop constraint %I', c.conname);
  end loop;
end
$$;

alter table public.goods_slips
  add constraint goods_slips_status_check check (status in (
    'GATE_CREATED', 'UNBOXING', 'ITEMIZATION', 'CATEGORISATION', 'CSR_APPROVAL_PENDING',
    'INSPECTION', 'RM_REVIEW', 'HELD_AT_INTERMEDIATE_STORE', 'IN_PROCESS', 'COMMERCIAL_RESOLUTION',
    'AWAITING_NOTIFICATION', 'CLOSED', 'CANCELLED'));

-- Seed HELD_AT_INTERMEDIATE_STORE option item if GS_STATUS option set exists
insert into public.option_items (option_set_id, code, label, allowed_status, rule_text, next_action_text,
                                 remarks, system_behavior, required_fields, sort_order, source_ref)
select os.id, 'HELD_AT_INTERMEDIATE_STORE', 'Held at Intermediate Store', 'YES', null, null, null, null, '[]'::jsonb, 75, 'AMD-13'
  from public.option_sets os
 where os.code = 'GS_STATUS'
on conflict (option_set_id, code) do update
   set label = excluded.label, sort_order = excluded.sort_order;

-- ===========================================================================
-- 2. goods_slips columns: counted_by, transfer_slip_id
-- ===========================================================================
alter table public.goods_slips
  add column if not exists counted_by uuid references public.profiles (id) on delete restrict,
  add column if not exists transfer_slip_id uuid references public.custody_transfers (id) on delete set null;

create index if not exists goods_slips_counted_by_idx on public.goods_slips (counted_by);
create index if not exists goods_slips_transfer_slip_idx on public.goods_slips (transfer_slip_id);

comment on column public.goods_slips.counted_by is
  'AMD-08 / Phase 5: profile ID of the user who completed counting. Categorisation must be submitted by the same user.';
comment on column public.goods_slips.transfer_slip_id is
  'AMD-13 / Phase 5: Transfer Slip auto-generated upon RM Review approval.';

-- ===========================================================================
-- 3. gs_item_buckets (AMD-09: item-level categorisation bucket quantities)
-- ===========================================================================
create table public.gs_item_buckets (
  id              uuid primary key default gen_random_uuid(),
  gs_item_id      uuid not null references public.gs_items (id) on delete cascade,
  field_id        uuid not null references public.item_field_library (id) on delete restrict,
  field_code      text not null,
  label_snapshot  text not null,
  qty             integer not null check (qty >= 0),
  created_at      timestamptz not null default now(),
  created_by      uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at      timestamptz not null default now(),
  constraint gs_item_buckets_item_field_key unique (gs_item_id, field_id)
);

create index gs_item_buckets_item_idx on public.gs_item_buckets (gs_item_id);
create index gs_item_buckets_field_idx on public.gs_item_buckets (field_id);

comment on table public.gs_item_buckets is
  'AMD-09: per-item categorisation bucket quantities (Good, Damaged, Body Broken, Wastage, ...) resolved from Phase 4 item field profile.';

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
    if v_status is not null and v_status not in ('CATEGORISATION', 'RM_REVIEW') then
      raise exception 'G-18: item buckets change only while the GS is in CATEGORISATION or RM_REVIEW (status %)', v_status
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
  if v_status not in ('CATEGORISATION', 'RM_REVIEW') then
    raise exception 'G-18: item buckets are recorded only while the GS is in CATEGORISATION or RM_REVIEW (status %)', v_status
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
revoke all on function rms_private.gs_item_buckets_guard() from public;
grant execute on function rms_private.gs_item_buckets_guard() to rms_api;

create trigger gs_item_buckets_guard
  before insert or update or delete on public.gs_item_buckets
  for each row execute function rms_private.gs_item_buckets_guard();

-- Extend gs_item_counts_guard so counts are also editable in RM_REVIEW (AMD-12)
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
    if v_status is not null and v_status not in ('CATEGORISATION', 'RM_REVIEW') then
      raise exception 'G-18: item counts change only while the GS is in CATEGORISATION or RM_REVIEW (status %)', v_status
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
  if v_status not in ('CATEGORISATION', 'RM_REVIEW') then
    raise exception 'G-18: item counts are recorded only while the GS is in CATEGORISATION or RM_REVIEW (status %)', v_status
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

-- ===========================================================================
-- 4. Conservation Guard G-19 (AMD-09: sum of bucket qty = counted qty per item)
-- ===========================================================================
create or replace function rms_private.validate_item_bucket_conservation(p_gs_id uuid)
returns void
language plpgsql
stable
set search_path = ''
as $$
declare
  r record;
begin
  for r in
    select gi.id, gi.line_no, p.name as product_name, gi.received_qty,
           coalesce(sum(gb.qty), 0) as bucket_sum
      from public.gs_items gi
      join public.products p on p.id = gi.product_id
      left join public.gs_item_buckets gb on gb.gs_item_id = gi.id
     where gi.gs_id = p_gs_id
     group by gi.id, gi.line_no, p.name, gi.received_qty
  loop
    if r.bucket_sum <> r.received_qty then
      raise exception 'G-19: sum of bucket quantities (%) must equal counted quantity (%) for item line % (%)',
        r.bucket_sum, r.received_qty, r.line_no, r.product_name
        using errcode = '23514';
    end if;
  end loop;
end;
$$;
revoke all on function rms_private.validate_item_bucket_conservation(uuid) from public;
grant execute on function rms_private.validate_item_bucket_conservation(uuid) to rms_api;

-- ===========================================================================
-- 5. rm_review_revisions (AMD-12: audit + revision tracking)
-- ===========================================================================
create table public.rm_review_revisions (
  id              uuid primary key default gen_random_uuid(),
  gs_id           uuid not null references public.goods_slips (id) on delete cascade,
  revision_no     integer not null check (revision_no >= 1),
  action          text not null check (action in ('SUBMITTED', 'RM_EDIT', 'RM_SENT_BACK', 'RM_APPROVED')),
  remarks         text,
  items_snapshot  jsonb not null check (jsonb_typeof(items_snapshot) = 'array'),
  created_by      uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  created_at      timestamptz not null default now(),
  constraint rm_review_revisions_gs_rev_key unique (gs_id, revision_no)
);

create index rm_review_revisions_gs_idx on public.rm_review_revisions (gs_id, revision_no desc);

comment on table public.rm_review_revisions is
  'AMD-12: revisions and audit history for categorisation and RM Review actions.';

-- ===========================================================================
-- 6. G-03 Guard Update: CATEGORISATION -> RM_REVIEW -> HELD_AT_INTERMEDIATE_STORE
-- ===========================================================================
create or replace function rms_private.goods_slips_g03_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_decision text;
begin
  -- original_category_code records the Step-3 choice and is kept for good (BR-08).
  if old.original_category_code is not null
     and new.original_category_code is distinct from old.original_category_code then
    raise exception 'G-03: the original category of a GS cannot change' using errcode = '23514';
  end if;

  select decision_code into v_decision
    from public.csr_approvals where gs_id = new.id and is_current;

  -- Category changes after Step-3: CSR → RO only by a current CSR_REJECTED_TO_RO decision;
  -- RO → CSR only when an admin reopened that decision (back to CSR_APPROVAL_PENDING).
  if old.category_code is not null and new.category_code is distinct from old.category_code then
    -- (null-safe comparisons: a missing decision must never let the change through)
    if not coalesce((old.category_code = 'CSR' and new.category_code is not distinct from 'RO'
                     and v_decision is not distinct from 'CSR_REJECTED_TO_RO')
                    or (old.category_code = 'RO' and new.category_code is not distinct from 'CSR'
                        and new.original_category_code is not distinct from 'CSR'
                        and v_decision is null
                        and new.status is not distinct from 'CSR_APPROVAL_PENDING'), false) then
      raise exception 'G-03: category % → % needs a matching Replacement Manager decision',
        old.category_code, coalesce(new.category_code, 'none') using errcode = '23514';
    end if;
  end if;

  if new.status is not distinct from old.status or new.status = 'CANCELLED' then
    return new;
  end if;

  -- AMD-08 / BR-07: Counting (ITEMIZATION) is submitted to CATEGORISATION with >= 1 counted line.
  if old.status = 'ITEMIZATION' then
    if new.status <> 'CATEGORISATION' then
      raise exception 'G-03: counting is submitted to CATEGORISATION before categorisation (not %)', new.status
        using errcode = '23514';
    end if;
    if not exists (select 1 from public.gs_items where gs_id = new.id) then
      raise exception 'G-01: counting cannot be submitted without item lines' using errcode = '23514';
    end if;
    return new;
  end if;

  -- Phase 5 (AMD-09, AMD-12): Leaving CATEGORISATION to RM_REVIEW.
  if old.status = 'CATEGORISATION' then
    if new.status = 'RM_REVIEW' then
      if not exists (select 1 from public.gs_items where gs_id = new.id) then
        raise exception 'G-01: a GS cannot be categorised without item lines' using errcode = '23514';
      end if;
      -- Enforce G-19 bucket conservation guard
      perform rms_private.validate_item_bucket_conservation(new.id);
      return new;
    end if;

    -- Legacy path: category_code required
    if new.category_code is null then
      raise exception 'G-03: a GS cannot leave CATEGORISATION without a category' using errcode = '23514';
    end if;
    if not exists (select 1 from public.gs_items where gs_id = new.id) then
      raise exception 'G-01: a GS cannot be categorised without item lines' using errcode = '23514';
    end if;
    if new.category_code = 'CSR' and new.status <> 'CSR_APPROVAL_PENDING' then
      raise exception 'G-03: a Complete Sales Return must go to CSR_APPROVAL_PENDING (not %)', new.status
        using errcode = '23514';
    end if;
    if new.category_code = 'RO' and new.status <> 'INSPECTION' then
      raise exception 'G-03: Replacement Only goes to INSPECTION (not %)', new.status using errcode = '23514';
    end if;
    return new;
  end if;

  -- Phase 5 (AMD-12, AMD-13): RM_REVIEW transitions
  if old.status = 'RM_REVIEW' then
    -- Send back with remark to CATEGORISATION
    if new.status = 'CATEGORISATION' then
      return new;
    end if;
    -- Intermediate Store acceptance (AMD-13)
    if new.status in ('HELD_AT_INTERMEDIATE_STORE', 'IN_PROCESS') then
      perform rms_private.validate_item_bucket_conservation(new.id);
      return new;
    end if;
  end if;

  -- Nothing but a submitted count reaches CATEGORISATION.
  if new.status = 'CATEGORISATION' and old.status <> 'RM_REVIEW' then
    raise exception 'G-03: only a GS in counting (ITEMIZATION) moves to CATEGORISATION (from %)', old.status
      using errcode = '23514';
  end if;

  if new.status = 'CSR_APPROVAL_PENDING' then
    if new.category_code is distinct from 'CSR' or v_decision is not null then
      raise exception 'G-03: CSR_APPROVAL_PENDING needs category CSR and no current decision'
        using errcode = '23514';
    end if;
    return new;
  end if;

  -- Leaving CSR_APPROVAL_PENDING (BR-08, DD r19–r20): only through the recorded decision.
  if old.status = 'CSR_APPROVAL_PENDING' then
    if v_decision is null then
      raise exception 'G-03: a Complete Sales Return cannot advance without the Replacement Manager''s decision'
        using errcode = '23514';
    end if;
    if v_decision = 'CSR_APPROVED' and (new.status <> 'IN_PROCESS'
                                         or new.category_code is distinct from 'CSR') then
      raise exception 'G-03: an approved CSR goes to IN_PROCESS as CSR (not %)', new.status using errcode = '23514';
    end if;
    if v_decision = 'CSR_REJECTED_TO_RO' and (new.status <> 'INSPECTION'
                                               or new.category_code is distinct from 'RO') then
      raise exception 'G-03: a rejected CSR is converted to RO and goes to INSPECTION (not %)', new.status
        using errcode = '23514';
    end if;
  end if;

  -- No CSR GS (nor one that was CSR) reaches inspection, handover or Stage-6 without a decision.
  if new.status in ('INSPECTION', 'RM_REVIEW', 'HELD_AT_INTERMEDIATE_STORE', 'IN_PROCESS',
                    'COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION', 'CLOSED')
     and 'CSR' in (new.category_code, new.original_category_code) and old.status not in ('RM_REVIEW', 'CATEGORISATION') then
    if (new.category_code = 'CSR' and v_decision is distinct from 'CSR_APPROVED')
       or (new.category_code = 'RO' and v_decision is distinct from 'CSR_REJECTED_TO_RO') then
      raise exception 'G-03: status % needs the Replacement Manager''s CSR decision', new.status
        using errcode = '23514';
    end if;
  end if;

  return new;
end
$$;

-- ===========================================================================
-- 7. Audit Triggers and RLS
-- ===========================================================================
create trigger audit_row
  after insert or update or delete on public.gs_item_buckets
  for each row execute function rms_private.audit_row();

create trigger audit_row
  after insert or update or delete on public.rm_review_revisions
  for each row execute function rms_private.audit_row();

create trigger set_updated_at
  before update on public.gs_item_buckets
  for each row execute function rms_private.set_updated_at();

alter table public.gs_item_buckets enable row level security;
alter table public.rm_review_revisions enable row level security;

create policy gs_item_buckets_api_all on public.gs_item_buckets
  for all to rms_api using (true) with check (true);

create policy rm_review_revisions_api_all on public.rm_review_revisions
  for all to rms_api using (true) with check (true);
