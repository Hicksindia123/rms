-- P2-04 · Step-3 Itemisation, GS-wise categorisation, CSR approval & packaging check
-- (master plan §2.2 Step-3, §3.2 DD r17–r20, WF r4, BR-07..BR-10, G-01, G-03, G-16, G-17, G-18,
-- DEC-06, DEC-09, DEC-27, DEC-28). Fixes forward on 20261102000900 (P2-01).
--
-- 1. Shared authority helpers: permission (role grant / live override, no live deny) and workflow
--    step assignment on a pinned workflow version.
-- 2. gs_items: remarks + label snapshots (G-18 / rule e); a line has documented or received qty;
--    lines are frozen once the GS is categorised, except through an RM-approved correction.
-- 3. gs_item_corrections: post-categorisation line edits (reason, RM approval, ADJUST movement).
-- 4. goods_slips: categorisation snapshot columns + csr_commercial_path (Step-7 flag).
-- 5. csr_approvals: one current decision per GS, decided only by an authorised approver, decision
--    immutable; an admin "reopen" (reason) supersedes it. Super Admin decisions are flagged.
-- 6. G-03 on goods_slips: categorisation routing, no CSR GS past CSR_APPROVAL_PENDING (nor into
--    inspection / handover / Stage-6 statuses) without a current, consistent RM decision.
-- 7. custody_transfers: GS link, purpose, "with packaging", stock_moved (P2-04 records the CSR
--    proposal without moving stock; the P3-01 engine moves it to TRANSIT).
-- 8. packaging_replacements: result OK | REPLACED (DEC-27); qty_replaced ≤ the lot's stock.

-- ===========================================================================
-- 1. Authority helpers
-- ===========================================================================
create or replace function rms_private.user_holds_permission(p_user uuid, p_module text, p_action text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.profiles p
     where p.id = p_user and p.is_active
       and (p.is_super_admin
            or ((exists (select 1 from public.user_roles ur
                           join public.role_permissions rp on rp.role_id = ur.role_id
                           join public.permissions pm on pm.id = rp.permission_id
                          where ur.user_id = p.id and pm.module_code = p_module and pm.action = p_action)
                 or exists (select 1 from public.user_permission_overrides o
                              join public.permissions pm on pm.id = o.permission_id
                             where o.user_id = p.id and o.effect = 'grant'
                               and pm.module_code = p_module and pm.action = p_action
                               and (o.expires_at is null or o.expires_at > now())))
                and not exists (select 1 from public.user_permission_overrides o
                                  join public.permissions pm on pm.id = o.permission_id
                                 where o.user_id = p.id and o.effect = 'deny'
                                   and pm.module_code = p_module and pm.action = p_action
                                   and (o.expires_at is null or o.expires_at > now()))))
  )
$$;

-- Assignment on the GS's pinned workflow version (G-18), by role or by user. Super Admin is NOT
-- implied here: callers decide whether a Super Admin acts as an (audited) admin.
create or replace function rms_private.user_assigned_to_step(
  p_user uuid, p_workflow_version uuid, p_step_code text, p_assignment_type text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.step_assignments sa
      join public.workflow_steps ws on ws.id = sa.workflow_step_id
      join public.profiles p on p.id = p_user and p.is_active
     where ws.workflow_version_id = p_workflow_version and ws.code = p_step_code and ws.is_active
       and sa.assignment_type = p_assignment_type
       and (sa.user_id = p_user
            or exists (select 1 from public.user_roles ur
                        where ur.user_id = p_user and ur.role_id = sa.role_id))
  )
$$;

revoke all on function rms_private.user_holds_permission(uuid, text, text) from public, anon, authenticated;
revoke all on function rms_private.user_assigned_to_step(uuid, uuid, text, text) from public, anon, authenticated;
grant execute on function rms_private.user_holds_permission(uuid, text, text) to rms_api;
grant execute on function rms_private.user_assigned_to_step(uuid, uuid, text, text) to rms_api;

-- ===========================================================================
-- 2. gs_items
-- ===========================================================================
alter table public.gs_items
  add column remarks                text,
  -- G-18 / rule e: product master values as they were when the line was counted.
  add column product_code_snapshot  text,
  add column product_name_snapshot  text,
  add column category_code_snapshot text,
  add constraint gs_items_has_quantity check (documented_qty > 0 or received_qty > 0);

-- ===========================================================================
-- 3. gs_item_corrections (post-categorisation line edits, RM approved)
-- ===========================================================================
create table public.gs_item_corrections (
  id                   uuid primary key default gen_random_uuid(),
  gs_id                uuid not null references public.goods_slips (id) on delete cascade,
  gs_item_id           uuid not null references public.gs_items (id) on delete cascade,
  old_documented_qty   integer not null check (old_documented_qty >= 0),
  old_received_qty     integer not null check (old_received_qty >= 0),
  new_documented_qty   integer not null check (new_documented_qty >= 0),
  new_received_qty     integer not null check (new_received_qty >= 0),
  reason               text not null check (btrim(reason) <> ''),
  status               text not null default 'REQUESTED' check (status in ('REQUESTED', 'APPROVED', 'REJECTED')),
  requested_by         uuid not null default rms_private.current_actor() references public.profiles (id) on delete restrict,
  requested_at         timestamptz not null default now(),
  decided_by           uuid references public.profiles (id) on delete restrict,
  decided_at           timestamptz,
  decision_remarks     text,
  applied_at           timestamptz,
  stock_movement_id    uuid references public.stock_movements (id) on delete restrict,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  constraint gs_item_corrections_changes check (
    new_documented_qty <> old_documented_qty or new_received_qty <> old_received_qty),
  constraint gs_item_corrections_has_quantity check (new_documented_qty > 0 or new_received_qty > 0),
  constraint gs_item_corrections_decision_fields check (
    status = 'REQUESTED' or (decided_by is not null and decided_at is not null)),
  constraint gs_item_corrections_reject_reason check (
    status <> 'REJECTED' or coalesce(btrim(decision_remarks), '') <> ''),
  constraint gs_item_corrections_applied_only_approved check (applied_at is null or status = 'APPROVED')
);

create index gs_item_corrections_gs_idx on public.gs_item_corrections (gs_id);
create index gs_item_corrections_item_idx on public.gs_item_corrections (gs_item_id);
create index gs_item_corrections_requested_by_idx on public.gs_item_corrections (requested_by);
create index gs_item_corrections_decided_by_idx on public.gs_item_corrections (decided_by);
create index gs_item_corrections_movement_idx on public.gs_item_corrections (stock_movement_id);
create index gs_item_corrections_open_idx on public.gs_item_corrections (requested_at desc)
  where status = 'REQUESTED';
create unique index gs_item_corrections_one_open on public.gs_item_corrections (gs_item_id)
  where status = 'REQUESTED';

-- Statuses in which a categorised line may still be corrected (before any grading is final).
create or replace function rms_private.gs_item_correctable_status(p_status text)
returns boolean
language sql
immutable
set search_path = ''
as $$ select p_status in ('CSR_APPROVAL_PENDING', 'INSPECTION') $$;
revoke all on function rms_private.gs_item_correctable_status(text) from public, anon, authenticated;
grant execute on function rms_private.gs_item_correctable_status(text) to rms_api;

create or replace function rms_private.gs_item_corrections_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_gs   record;
  v_item record;
begin
  select status into v_gs from public.goods_slips where id = new.gs_id;
  if tg_op = 'INSERT' then
    if new.status <> 'REQUESTED' or new.applied_at is not null then
      raise exception 'A line correction starts as REQUESTED' using errcode = '23514';
    end if;
    select gs_id, documented_qty, received_qty into v_item from public.gs_items where id = new.gs_item_id;
    if v_item.gs_id is distinct from new.gs_id then
      raise exception 'The corrected line does not belong to this GS' using errcode = '23514';
    end if;
    if new.old_documented_qty <> v_item.documented_qty or new.old_received_qty <> v_item.received_qty then
      raise exception 'The correction must start from the line''s current quantities' using errcode = '23514';
    end if;
    if not rms_private.gs_item_correctable_status(v_gs.status) then
      raise exception 'Line corrections are possible only after categorisation and before grading (status %)', v_gs.status
        using errcode = '23514';
    end if;
    return new;
  end if;

  -- UPDATE: the request never changes; REQUESTED → APPROVED / REJECTED once; applied once.
  if new.gs_id <> old.gs_id or new.gs_item_id <> old.gs_item_id
     or new.old_documented_qty <> old.old_documented_qty or new.old_received_qty <> old.old_received_qty
     or new.new_documented_qty <> old.new_documented_qty or new.new_received_qty <> old.new_received_qty
     or new.reason <> old.reason or new.requested_by <> old.requested_by
     or new.requested_at <> old.requested_at then
    raise exception 'A line correction request cannot be edited' using errcode = '23514';
  end if;
  if old.status <> 'REQUESTED' then
    if new.status <> old.status or new.decided_by is distinct from old.decided_by
       or new.decided_at is distinct from old.decided_at
       or new.decision_remarks is distinct from old.decision_remarks then
      raise exception 'A decided line correction cannot change' using errcode = '23514';
    end if;
    if old.applied_at is not null and (new.applied_at is distinct from old.applied_at
       or new.stock_movement_id is distinct from old.stock_movement_id) then
      raise exception 'An applied line correction cannot change' using errcode = '23514';
    end if;
    return new;
  end if;
  if new.status <> 'REQUESTED' then
    if not rms_private.gs_item_correctable_status(v_gs.status) then
      raise exception 'Line corrections can only be decided after categorisation and before grading (status %)', v_gs.status
        using errcode = '23514';
    end if;
    -- "RM-approved correction": the decider holds itemization.approve (or is an active Super Admin).
    if not rms_private.user_holds_permission(new.decided_by, 'itemization', 'approve') then
      raise exception 'A line correction must be decided by a user holding itemization.approve'
        using errcode = '42501';
    end if;
  end if;
  return new;
end
$$;
revoke all on function rms_private.gs_item_corrections_guard() from public, anon, authenticated;

create trigger gs_item_corrections_guard
  before insert or update on public.gs_item_corrections
  for each row execute function rms_private.gs_item_corrections_guard();

create trigger gs_item_corrections_no_delete
  before delete on public.gs_item_corrections
  for each row when (pg_trigger_depth() = 0)
  execute function rms_private.raise_insert_only();

alter table public.gs_item_corrections enable row level security;
select rms_private.attach_standard_triggers('public.gs_item_corrections');
grant select, insert, update on public.gs_item_corrections to rms_api;

-- gs_items freeze (BR-07: the category is decided on the counted lines).
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
  if v_status in ('GATE_CREATED', 'UNBOXING', 'ITEMIZATION') then
    return case when tg_op = 'DELETE' then old else new end;
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
end
$$;
revoke all on function rms_private.gs_items_guard() from public, anon, authenticated;

create trigger gs_items_guard
  before insert or update or delete on public.gs_items
  for each row execute function rms_private.gs_items_guard();

-- ===========================================================================
-- 4. goods_slips: categorisation columns
-- ===========================================================================
alter table public.goods_slips
  add column categorized_by            uuid references public.profiles (id) on delete restrict,
  add column categorized_at            timestamptz,
  add column category_form_version_id  uuid references public.form_versions (id) on delete restrict,
  add column category_labels_snapshot  jsonb not null default '{}'::jsonb,
  -- BR-09 / DD r19: approved CSR → Step-7 commercial path (CN, CSR closure).
  add column csr_commercial_path       boolean not null default false,
  add constraint goods_slips_csr_path_needs_csr check (not csr_commercial_path or category_code = 'CSR'),
  add constraint goods_slips_original_category check (
    (category_code is null) = (original_category_code is null)),
  add constraint goods_slips_categorized_pair check ((categorized_by is null) = (categorized_at is null));

create index goods_slips_categorized_by_idx on public.goods_slips (categorized_by);
create index goods_slips_category_form_version_idx on public.goods_slips (category_form_version_id);

-- ===========================================================================
-- 5. csr_approvals
-- ===========================================================================
alter table public.csr_approvals
  add column form_version_id  uuid references public.form_versions (id) on delete restrict,
  add column labels_snapshot  jsonb not null default '{}'::jsonb,
  -- A Super Admin decision without the APPROVE assignment is allowed but flagged (set by trigger).
  add column is_admin_action  boolean not null default false,
  add column reopened_by      uuid references public.profiles (id) on delete restrict,
  add column reopened_at      timestamptz,
  add column reopen_reason    text,
  add column updated_at       timestamptz not null default now(),
  add constraint csr_approvals_reject_remarks check (
    decision_code <> 'CSR_REJECTED_TO_RO' or coalesce(btrim(remarks), '') <> ''),
  add constraint csr_approvals_reopen_fields check (
    is_current = (reopened_at is null)
    and (reopened_at is null) = (reopened_by is null)
    and (reopened_at is null or coalesce(btrim(reopen_reason), '') <> ''));

create unique index csr_approvals_one_current on public.csr_approvals (gs_id) where is_current;
create index csr_approvals_form_version_idx on public.csr_approvals (form_version_id);
create index csr_approvals_reopened_by_idx on public.csr_approvals (reopened_by);

create or replace function rms_private.csr_approvals_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_gs        record;
  v_assigned  boolean;
  v_is_admin  boolean;
begin
  if tg_op = 'DELETE' then
    if exists (select 1 from public.goods_slips where id = old.gs_id) then
      raise exception 'G-03: CSR decisions cannot be deleted' using errcode = '23514';
    end if;
    return old;  -- cascade from a deleted GS
  end if;

  select status, category_code, workflow_version_id into v_gs from public.goods_slips where id = new.gs_id;

  if tg_op = 'INSERT' then
    if not new.is_current or new.reopened_at is not null then
      raise exception 'A CSR decision is recorded as the current decision' using errcode = '23514';
    end if;
    if v_gs.status is distinct from 'CSR_APPROVAL_PENDING' or v_gs.category_code is distinct from 'CSR' then
      raise exception 'G-03: a CSR decision can only be recorded while the GS is CSR_APPROVAL_PENDING (status %)', v_gs.status
        using errcode = '23514';
    end if;
    -- G-03: "recorded by a user holding the approve permission" = itemization.approve AND the
    -- S1_CSR_APPROVAL APPROVE assignment on the GS's pinned workflow version; an active Super Admin
    -- may decide, and such a decision is flagged as an admin action.
    v_assigned := rms_private.user_assigned_to_step(new.decided_by, v_gs.workflow_version_id, 'S1_CSR_APPROVAL', 'APPROVE')
                  and rms_private.user_holds_permission(new.decided_by, 'itemization', 'approve');
    v_is_admin := exists (select 1 from public.profiles where id = new.decided_by and is_active and is_super_admin);
    if not v_assigned and not v_is_admin then
      raise exception 'G-03: the CSR decision must be recorded by the Replacement Manager (S1_CSR_APPROVAL approver)'
        using errcode = '42501';
    end if;
    new.is_admin_action := not v_assigned;
    return new;
  end if;

  -- UPDATE: the decision is immutable; only an admin reopen (with reason) supersedes it.
  if new.gs_id <> old.gs_id or new.decision_code <> old.decision_code
     or new.remarks is distinct from old.remarks or new.decided_by <> old.decided_by
     or new.decided_at <> old.decided_at or new.is_admin_action <> old.is_admin_action
     or new.form_version_id is distinct from old.form_version_id
     or new.labels_snapshot <> old.labels_snapshot then
    raise exception 'G-03: a recorded CSR decision cannot be changed; reopen it instead' using errcode = '23514';
  end if;
  if not old.is_current then
    if new.is_current or new.reopened_at is distinct from old.reopened_at
       or new.reopened_by is distinct from old.reopened_by
       or new.reopen_reason is distinct from old.reopen_reason then
      raise exception 'A reopened CSR decision cannot change' using errcode = '23514';
    end if;
    return new;
  end if;
  if not new.is_current then
    if not (exists (select 1 from public.profiles where id = new.reopened_by and is_active and is_super_admin)
            or rms_private.user_holds_permission(new.reopened_by, 'goods_slips', 'configure')) then
      raise exception 'Only an admin may reopen a CSR decision' using errcode = '42501';
    end if;
  end if;
  return new;
end
$$;
revoke all on function rms_private.csr_approvals_guard() from public, anon, authenticated;

create trigger csr_approvals_guard
  before insert or update or delete on public.csr_approvals
  for each row execute function rms_private.csr_approvals_guard();

select rms_private.attach_standard_triggers('public.csr_approvals');

-- ===========================================================================
-- 6. G-03 on goods_slips
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

  -- Leaving ITEMIZATION (BR-07, DD r17–r18): a GS-wise category on ≥1 counted line.
  if old.status = 'ITEMIZATION' then
    if new.category_code is null then
      raise exception 'G-03: a GS cannot leave ITEMIZATION without a category' using errcode = '23514';
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
  if new.status in ('INSPECTION', 'RM_REVIEW', 'IN_PROCESS', 'COMMERCIAL_RESOLUTION',
                    'AWAITING_NOTIFICATION', 'CLOSED')
     and 'CSR' in (new.category_code, new.original_category_code) then
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

create trigger goods_slips_g03_guard
  before update of status, category_code, original_category_code on public.goods_slips
  for each row execute function rms_private.goods_slips_g03_guard();

-- ===========================================================================
-- 7. custody_transfers (minimal CSR proposal; engine in P3-01)
-- ===========================================================================
alter table public.custody_transfers
  add column gs_id           uuid references public.goods_slips (id) on delete restrict,
  add column purpose_code    text check (purpose_code is null or btrim(purpose_code) <> ''),
  add column with_packaging  boolean not null default false,
  -- false = proposal recorded, stock still at from_location (P2-04); P3-01 moves it to TRANSIT.
  add column stock_moved     boolean not null default false,
  add column notes           text,
  add column updated_at      timestamptz not null default now();

create index custody_transfers_gs_idx on public.custody_transfers (gs_id);
-- One live CSR "forward with packaging" transfer per GS.
create unique index custody_transfers_one_live_csr on public.custody_transfers (gs_id)
  where purpose_code = 'CSR_WITH_PACKAGING' and status in ('INITIATED', 'DISCREPANCY');

select rms_private.attach_standard_triggers('public.custody_transfers');

-- ===========================================================================
-- 8. packaging_replacements (WF r4, BR-10, DEC-27)
-- ===========================================================================
alter table public.packaging_replacements drop constraint packaging_replacements_qty_check;
alter table public.packaging_replacements
  add column result_code text not null default 'REPLACED' check (result_code in ('OK', 'REPLACED')),
  add constraint packaging_replacements_qty_for_result check (
    (result_code = 'OK' and qty = 0) or (result_code = 'REPLACED' and qty > 0));
alter table public.packaging_replacements alter column result_code drop default;

create or replace function rms_private.packaging_replacements_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_stock integer;
begin
  if tg_op <> 'INSERT' then
    raise exception 'Packaging checks are append-only' using errcode = '23514';
  end if;
  select coalesce(sum(qty), 0) into v_stock from public.stock_balances where lot_id = new.lot_id;
  if v_stock <= 0 then
    raise exception 'The lot has no stock to check' using errcode = '23514';
  end if;
  if new.qty > v_stock then
    raise exception 'Packaging replaced (%) exceeds the lot''s stock (%)', new.qty, v_stock using errcode = '23514';
  end if;
  return new;
end
$$;
revoke all on function rms_private.packaging_replacements_guard() from public, anon, authenticated;

create trigger packaging_replacements_guard
  before insert or update or delete on public.packaging_replacements
  for each row when (pg_trigger_depth() = 0)
  execute function rms_private.packaging_replacements_guard();
