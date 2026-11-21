-- =============================================================================================
-- Phase P4 (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-64 (Q9 PROVISIONAL; Q10, Q11, Q12 user).
-- Step 2b / 2c: items → Replacement / Complete Sales Return popup → categorisation → LOCK.
--
-- 1. Statuses: PENDING_TRANSFER_SLIP (categorisation locked, inward stock booked, waiting for the
--    RM's transfer slip, P5) and SALES_RETURN_HOLD (Complete Sales Return parked, Q11). A new
--    status rather than renaming RM_REVIEW: GSs already in RM_REVIEW keep that meaning (legacy).
-- 2. goods_slips.categorisation_locked_at / _by: stamped by the lock (one transaction with the
--    stock booking into INWARD_STAGING, Q12).
-- 3. Status chain (G-03 trigger, full body replaced):
--      ITEMIZATION → CATEGORISATION      lines, category RO (popup "Replacement") or none (legacy)
--      ITEMIZATION → SALES_RETURN_HOLD   lines, category CSR (popup "Complete Sales Return")
--      CATEGORISATION → PENDING_TRANSFER_SLIP   lines, category RO, locked stamp, G-19
--      CATEGORISATION → RM_REVIEW        RETIRED (DEC-64 e: no submit to RM review any more)
--    Legacy exits from CATEGORISATION (/categorize → CSR_APPROVAL_PENDING / INSPECTION) and from
--    RM_REVIEW (send back, store acceptance) are unchanged.
-- 4. Edit window after the lock (DEC-64 d): item lines, buckets and counts of a
--    PENDING_TRANSFER_SLIP GS change only for a holder of itemization.configure (Super Admin,
--    MANAGEMENT; config, seed.sql) and only while no line of the GS has been routed
--    (rms_private.gs_routing_started; P7 extends it). G-19 is re-checked at commit.
--    RM_REVIEW no longer allows line / split edits (DEC-54 RM edits retired, Q9).
--    Lines may be edited in CATEGORISATION before the lock (the RE corrects qty there).
-- 5. rm_review_revisions: actions CATEGORISATION_LOCKED and LOCKED_* (reason required).
-- 6. gs_items.removed_*: a stocked line removed after the lock stays as history with qty 0.
-- Option labels (GS_STATUS), the configure grant and journeys: seed.sql + the release snippet.
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- 1. Statuses
-- ---------------------------------------------------------------------------------------------
alter table public.goods_slips drop constraint goods_slips_status_check;
alter table public.goods_slips
  add constraint goods_slips_status_check check (status in (
    'GATE_CREATED', 'UNBOXING', 'ITEMIZATION', 'CATEGORISATION', 'CSR_APPROVAL_PENDING',
    'INSPECTION', 'RM_REVIEW', 'PENDING_TRANSFER_SLIP', 'SALES_RETURN_HOLD',
    'HELD_AT_INTERMEDIATE_STORE', 'IN_PROCESS', 'COMMERCIAL_RESOLUTION',
    'AWAITING_NOTIFICATION', 'CLOSED', 'CANCELLED'));

-- ---------------------------------------------------------------------------------------------
-- 2. Lock stamp
-- ---------------------------------------------------------------------------------------------
alter table public.goods_slips
  add column categorisation_locked_at timestamptz,
  add column categorisation_locked_by uuid references public.profiles (id) on delete restrict,
  add constraint goods_slips_categorisation_lock_fields check (
    (categorisation_locked_at is null) = (categorisation_locked_by is null));

create index goods_slips_categorisation_locked_by_idx
  on public.goods_slips (categorisation_locked_by) where categorisation_locked_by is not null;

comment on column public.goods_slips.categorisation_locked_at is
  'DEC-64: when the Replacement Executive locked the categorisation (inward stock booked, Q12).';

-- 2b. A line removed after the lock stays as history (its stock is on the append-only ledger):
--     qty 0 / 0, who, when and why. Lines without stock movements are deleted instead.
alter table public.gs_items
  add column removed_at timestamptz,
  add column removed_by uuid references public.profiles (id) on delete restrict,
  add column removal_reason text,
  add constraint gs_items_removed_fields check (
    removed_at is null
    or (removed_by is not null and length(btrim(coalesce(removal_reason, ''))) >= 3
        and documented_qty = 0 and received_qty = 0));
alter table public.gs_items drop constraint gs_items_has_quantity;
alter table public.gs_items
  add constraint gs_items_has_quantity check (
    documented_qty > 0 or received_qty > 0 or removed_at is not null);
create index gs_items_removed_by_idx on public.gs_items (removed_by) where removed_by is not null;
comment on column public.gs_items.removed_at is
  'DEC-64 d: removed by Super Admin / Management after the categorisation lock (kept as history).';

-- ---------------------------------------------------------------------------------------------
-- 3. Helpers: routing started, post-lock edit authority
-- ---------------------------------------------------------------------------------------------
create or replace function rms_private.gs_routing_started(p_gs_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  -- DEC-64 d: the Admin / Management edit window closes at the first routing of any line.
  select exists (select 1 from public.department_routing_plan_lines l
                  where l.gs_id = p_gs_id and l.status <> 'CANCELLED')
      or exists (select 1 from public.department_routings r
                  where r.gs_id = p_gs_id and r.status <> 'CANCELLED')
$$;
revoke all on function rms_private.gs_routing_started(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_routing_started(uuid) to rms_api;

create or replace function rms_private.assert_locked_gs_edit(p_gs_id uuid)
returns void
language plpgsql
stable
set search_path = ''
as $$
begin
  if not rms_private.user_holds_permission(rms_private.current_actor(), 'itemization', 'configure') then
    raise exception 'DEC-64: after the categorisation lock only Super Admin or Management may edit the goods slip'
      using errcode = '42501';
  end if;
  if rms_private.gs_routing_started(p_gs_id) then
    raise exception 'DEC-64: the goods slip can no longer be edited: department routing has started'
      using errcode = '23514';
  end if;
end
$$;
revoke all on function rms_private.assert_locked_gs_edit(uuid) from public, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- 4. Status chain (G-03 trigger)
-- ---------------------------------------------------------------------------------------------
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

  -- Category changes after Step-3: CSR -> RO only by a current CSR_REJECTED_TO_RO decision;
  -- RO -> CSR only when an admin reopened that decision (back to CSR_APPROVAL_PENDING).
  if old.category_code is not null and new.category_code is distinct from old.category_code then
    if not coalesce((old.category_code = 'CSR' and new.category_code is not distinct from 'RO'
                     and v_decision is not distinct from 'CSR_REJECTED_TO_RO')
                    or (old.category_code = 'RO' and new.category_code is not distinct from 'CSR'
                        and new.original_category_code is not distinct from 'CSR'
                        and v_decision is null
                        and new.status is not distinct from 'CSR_APPROVAL_PENDING'), false) then
      raise exception 'G-03: category % -> % needs a matching Replacement Manager decision',
        old.category_code, coalesce(new.category_code, 'none') using errcode = '23514';
    end if;
  end if;

  if new.status is not distinct from old.status or new.status = 'CANCELLED' then
    return new;
  end if;

  -- DEC-64 (a, b): items → popup. Replacement → CATEGORISATION, Complete Sales Return → hold.
  if old.status = 'ITEMIZATION' then
    if new.status not in ('CATEGORISATION', 'SALES_RETURN_HOLD') then
      raise exception 'G-03: counting is submitted to CATEGORISATION (Replacement) or SALES_RETURN_HOLD (Complete Sales Return), not %', new.status
        using errcode = '23514';
    end if;
    if not exists (select 1 from public.gs_items where gs_id = new.id) then
      raise exception 'G-01: counting cannot be submitted without item lines' using errcode = '23514';
    end if;
    if new.status = 'CATEGORISATION' then
      -- (A CSR GS reaching CATEGORISATION is the legacy P2-04 path; it can never be locked,
      --  the lock below requires RO. The DEC-64 popup parks a CSR in SALES_RETURN_HOLD.)
      return new;
    end if;
    if new.status = 'SALES_RETURN_HOLD' then
      if new.category_code is distinct from 'CSR' then
        raise exception 'G-03: only a Complete Sales Return goes to SALES_RETURN_HOLD (DEC-64, Q11)'
          using errcode = '23514';
      end if;
      return new;
    end if;
  end if;

  if old.status = 'CATEGORISATION' then
    if not exists (select 1 from public.gs_items where gs_id = new.id) then
      raise exception 'G-01: a GS cannot be categorised without item lines' using errcode = '23514';
    end if;
    -- DEC-64 (c): the lock.
    if new.status = 'PENDING_TRANSFER_SLIP' then
      if new.category_code is distinct from 'RO' then
        raise exception 'G-03: only a Replacement GS is locked for transfer slips (DEC-64)' using errcode = '23514';
      end if;
      perform rms_private.validate_item_bucket_conservation(new.id);   -- G-19
      if new.categorisation_locked_at is null then
        raise exception 'DEC-64: PENDING_TRANSFER_SLIP needs the categorisation lock stamp' using errcode = '23514';
      end if;
      return new;
    end if;
    if new.status = 'RM_REVIEW' then
      raise exception 'DEC-64: categorisation is locked, not submitted to RM review any more' using errcode = '23514';
    end if;
    -- A legacy GS sent back by the RM has no category yet: its popup may still park it (Q11).
    if new.status = 'SALES_RETURN_HOLD' then
      if new.category_code is distinct from 'CSR' then
        raise exception 'G-03: only a Complete Sales Return goes to SALES_RETURN_HOLD (DEC-64, Q11)'
          using errcode = '23514';
      end if;
      return new;
    end if;

    -- Legacy path (P2-04 /categorize): category_code required
    if new.category_code is null then
      raise exception 'G-03: a GS cannot leave CATEGORISATION without a category' using errcode = '23514';
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

  -- DEC-64 / Q11: a Complete Sales Return on hold has no further steps until that journey exists.
  if old.status = 'SALES_RETURN_HOLD' then
    raise exception 'G-03: a Complete Sales Return on hold cannot advance yet (DEC-64, Q11)' using errcode = '23514';
  end if;
  -- PENDING_TRANSFER_SLIP leaves only through the transfer slip flow (P5).
  if old.status = 'PENDING_TRANSFER_SLIP' then
    raise exception 'G-03: a locked GS leaves PENDING_TRANSFER_SLIP only through its transfer slips (P5), not to %', new.status
      using errcode = '23514';
  end if;
  if new.status in ('PENDING_TRANSFER_SLIP', 'SALES_RETURN_HOLD') then
    raise exception 'G-03: % is reached only from counting / categorisation (from %)', new.status, old.status
      using errcode = '23514';
  end if;

  -- Phase 5 (AMD-12, AMD-13): RM_REVIEW transitions (legacy GSs)
  if old.status = 'RM_REVIEW' then
    if new.status = 'CATEGORISATION' then
      return new;   -- send back with remark
    end if;
    if new.status = 'HELD_AT_INTERMEDIATE_STORE' then
      perform rms_private.validate_item_bucket_conservation(new.id);
      return new;
    end if;
    if new.status = 'IN_PROCESS' then
      return new;   -- legacy Step-4 RO RM review
    end if;
  end if;

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

  -- Leaving CSR_APPROVAL_PENDING (BR-08, DD r19-r20): only through the recorded decision.
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
revoke all on function rms_private.goods_slips_g03_guard() from public, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- 5. Item lines, buckets, counts: edit windows
-- ---------------------------------------------------------------------------------------------
create or replace function rms_private.gs_items_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_row        public.gs_items;
  v_status     text;
  v_correction uuid;
begin
  v_row := case when tg_op = 'DELETE' then old else new end;
  select status into v_status from public.goods_slips where id = v_row.gs_id;
  if v_status is null then
    -- cascade from a deleted GS, or a missing GS (the FK reports G-01 on insert)
    return case when tg_op = 'DELETE' then old else new end;
  end if;
  if tg_op = 'UPDATE' and (new.gs_id <> old.gs_id or new.line_no <> old.line_no) then
    raise exception 'Item line number or goods slip reference cannot change' using errcode = '23514';
  end if;
  -- DEC-64: lines are free until the categorisation lock (counting and categorisation screens).
  if v_status in ('GATE_CREATED', 'UNBOXING', 'ITEMIZATION', 'CATEGORISATION') then
    return case when tg_op = 'DELETE' then old else new end;
  end if;
  -- DEC-64 (d): after the lock, Super Admin / Management only, until the first routing.
  if v_status = 'PENDING_TRANSFER_SLIP' then
    perform rms_private.assert_locked_gs_edit(v_row.gs_id);
    return case when tg_op = 'DELETE' then old else new end;
  end if;

  if tg_op <> 'UPDATE' then
    raise exception 'Item lines cannot be added or removed in status % (DEC-64)', v_status
      using errcode = '23514';
  end if;
  if new.product_id <> old.product_id
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
revoke all on function rms_private.gs_items_guard() from public, anon, authenticated;

-- Shared by the bucket and count guards: may the split of this line change now?
create or replace function rms_private.assert_item_split_editable(p_gs_item_id uuid, p_what text)
returns void
language plpgsql
stable
set search_path = ''
as $$
declare
  v_gs     uuid;
  v_status text;
begin
  select gs.id, gs.status into v_gs, v_status
    from public.gs_items gi join public.goods_slips gs on gs.id = gi.gs_id where gi.id = p_gs_item_id;
  if v_status is null then
    return;   -- cascade from a deleted line / GS
  end if;
  if v_status in ('ITEMIZATION', 'CATEGORISATION') then
    return;
  end if;
  if v_status = 'PENDING_TRANSFER_SLIP' then
    perform rms_private.assert_locked_gs_edit(v_gs);   -- DEC-64 (d)
    return;
  end if;
  raise exception 'G-18: item % change only before the categorisation lock (ITEMIZATION, CATEGORISATION) or by Management after it (status %, DEC-64)', p_what, v_status
    using errcode = '23514';
end
$$;
revoke all on function rms_private.assert_item_split_editable(uuid, text) from public, anon, authenticated;

create or replace function rms_private.gs_item_buckets_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_product  uuid;
  v_version  uuid;
  v_lib      public.item_field_library%rowtype;
begin
  if tg_op = 'DELETE' then
    perform rms_private.assert_item_split_editable(old.gs_item_id, 'buckets');
    return old;
  end if;

  if tg_op = 'UPDATE' and (new.gs_item_id, new.field_id, new.field_code, new.label_snapshot)
                          is distinct from (old.gs_item_id, old.field_id, old.field_code, old.label_snapshot) then
    raise exception 'G-18: the field and label snapshot of an item bucket are immutable' using errcode = '42501';
  end if;
  perform rms_private.assert_item_split_editable(new.gs_item_id, 'buckets');

  if tg_op = 'INSERT' then
    select gi.product_id, gs.item_field_profile_version_id into v_product, v_version
      from public.gs_items gi join public.goods_slips gs on gs.id = gi.gs_id where gi.id = new.gs_item_id;
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
revoke all on function rms_private.gs_item_buckets_guard() from public, anon, authenticated;

create or replace function rms_private.gs_item_counts_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_product  uuid;
  v_version  uuid;
  v_lib      public.item_field_library%rowtype;
begin
  if tg_op = 'DELETE' then
    perform rms_private.assert_item_split_editable(old.gs_item_id, 'counts');
    return old;
  end if;

  if tg_op = 'UPDATE' and (new.gs_item_id, new.field_id, new.field_code, new.label_snapshot)
                          is distinct from (old.gs_item_id, old.field_id, old.field_code, old.label_snapshot) then
    raise exception 'G-18: the field and label snapshot of an item count are immutable' using errcode = '42501';
  end if;
  perform rms_private.assert_item_split_editable(new.gs_item_id, 'counts');

  if tg_op = 'INSERT' then
    select gi.product_id, gs.item_field_profile_version_id into v_product, v_version
      from public.gs_items gi join public.goods_slips gs on gs.id = gi.gs_id where gi.id = new.gs_item_id;
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
revoke all on function rms_private.gs_item_counts_guard() from public, anon, authenticated;

-- G-19 after a Management edit: checked at commit for every touched locked GS.
create or replace function rms_private.locked_gs_g19_check()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_gs     uuid;
  v_status text;
begin
  if tg_table_name = 'gs_items' then
    v_gs := coalesce(new.gs_id, old.gs_id);
  else
    select gi.gs_id into v_gs from public.gs_items gi
     where gi.id = coalesce(new.gs_item_id, old.gs_item_id);
  end if;
  select status into v_status from public.goods_slips where id = v_gs;
  if v_status = 'PENDING_TRANSFER_SLIP' then
    perform rms_private.validate_item_bucket_conservation(v_gs);
  end if;
  return null;
end
$$;
revoke all on function rms_private.locked_gs_g19_check() from public, anon, authenticated;

create constraint trigger gs_items_locked_g19
  after insert or update on public.gs_items
  deferrable initially deferred
  for each row execute function rms_private.locked_gs_g19_check();
create constraint trigger gs_item_buckets_locked_g19
  after insert or update or delete on public.gs_item_buckets
  deferrable initially deferred
  for each row execute function rms_private.locked_gs_g19_check();

-- ---------------------------------------------------------------------------------------------
-- 6. Revision actions
-- ---------------------------------------------------------------------------------------------
alter table public.rm_review_revisions drop constraint if exists rm_review_revisions_action_check;
alter table public.rm_review_revisions
  add constraint rm_review_revisions_action_check check (action in (
    'SUBMITTED', 'RM_EDIT', 'RM_SENT_BACK', 'RM_APPROVED', 'RM_ADD_LINE', 'RM_REMOVE_LINE',
    'RM_CHANGE_PRODUCT',
    -- DEC-64
    'CATEGORISATION_LOCKED', 'LOCKED_EDIT', 'LOCKED_ADD_LINE', 'LOCKED_REMOVE_LINE',
    'LOCKED_CHANGE_PRODUCT')),
  add constraint rm_review_revisions_locked_edit_reason check (
    action not like 'LOCKED\_%' or length(btrim(coalesce(remarks, ''))) >= 3);

comment on table public.rm_review_revisions is
  'AMD-12 / DEC-64: revisions of a GS''s lines: categorisation submit / lock, legacy RM review '
  'actions and the post-lock Super Admin / Management edits (reason required).';

-- ---------------------------------------------------------------------------------------------
-- 7. Notification event types (catalogue; recipients = rules in seed.sql + the release snippet)
-- ---------------------------------------------------------------------------------------------
insert into public.notification_event_types
  (code, label, description, category, default_priority, is_mandatory, source_ref, sort_order)
values
  ('CATEGORISATION_LOCKED', 'Categorisation locked',
   'DEC-64: the Replacement Executive locked the categorisation; the GS waits for its transfer slip.',
   'WORKFLOW', 'NORMAL', false, 'DEC-64', 520),
  ('SALES_RETURN_HOLD', 'Complete Sales Return on hold',
   'DEC-64 / Q11: the GS was recorded as a Complete Sales Return and parked until that journey exists.',
   'WORKFLOW', 'NORMAL', false, 'DEC-64', 530),
  ('LOCKED_GS_EDITED', 'Locked goods slip edited',
   'DEC-64 d: Super Admin / Management changed a goods slip after the categorisation lock.',
   'WORKFLOW', 'HIGH', false, 'DEC-64', 540)
on conflict (code) do update
  set label = excluded.label, description = excluded.description,
      default_priority = excluded.default_priority, source_ref = excluded.source_ref;

-- Default email template per event type (catalogue integrity; email itself is deferred, Q22).
insert into public.notification_templates (event_type, channel, version_no, subject, body, change_reason)
select v.event_type, 'EMAIL', 1,
       '[{app_name}] {title}',
       E'Hello {recipient_name},

{title}

{body}

Event: {event_label}
Priority: {priority}
Open in RMS: {link}

— {app_name} (automated message; manage email preferences in RMS)',
       'P4 default'
  from (values ('CATEGORISATION_LOCKED'), ('SALES_RETURN_HOLD'), ('LOCKED_GS_EDITED')) as v(event_type)
 where not exists (select 1 from public.notification_templates t
                    where t.event_type = v.event_type and t.channel = 'EMAIL');
