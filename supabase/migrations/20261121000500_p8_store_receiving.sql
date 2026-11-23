-- =============================================================================================
-- Phase P8 (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-68 (PROVISIONAL, target flow step 6).
-- Receiving back from departments by the Intermediate Store user.
--
-- The store whose user routed the goods (DEC-67: department_routings.store_id) receives them back
-- per GS and department: sent vs received qty, outcome, condition after work (DEC-56 rules
-- unchanged), partial receipts allowed. The pieces return to THAT store's location (not the legacy
-- INTERMEDIATE_STORE), or to scrap / the Non-Functional Store per outcome head, as today.
-- Legacy routings (store_id NULL) keep the DEC-42 receiving role and the legacy location.
--
-- 1. Permission store_routing.edit ("receive the store's goods back from departments").
-- 2. Receipt header guard (full body: 20261113001000 Phase 6 hardening body + the DEC-68 branch):
--    a store routing is received only by a user of that store (Super Admin or the store role, not
--    Management) holding store_routing.edit, while the GS is at its stores (STORE_PROCESSING).
-- 3. Receipt line guard (full body: 20261118000200 G3 body + the DEC-68 destination): a head
--    without a configured destination sends non-wastage pieces back to the ROUTING's store
--    location; a head configured for the legacy INTERMEDIATE_STORE means "the store" too.
-- 4. Journey catalogue: STORE_DEPT_RECEIVING "Receive from Departments" (queue STORE_RECEIVING,
--    user-scoped, screens store-receiving / gs-store-receiving). Grants and menus: seed.sql +
--    supabase/snippets/release_20261121_p8_store_receiving.sql.
-- G-20 (quantity conservation) and the per-store progress (rms_private.gs_store_routing_progress:
-- AT_DEPARTMENTS → READY_FOR_ANALYSIS, or ROUTING_PENDING again for a "return to routing" outcome)
-- need no change: they already count receipts per routing line.
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- 1. Permission
-- ---------------------------------------------------------------------------------------------
insert into public.permissions (module_code, action, description)
values
  ('store_routing', 'edit',
   'Receive the user''s own Intermediate Store goods back from departments (outcome + condition after work, DEC-68)')
on conflict (module_code, action) do nothing;

insert into public.role_permissions (role_id, permission_id, scope)
select r.id, p.id, 'all'
  from public.roles r
  join public.permissions p on p.module_code = 'store_routing' and p.action = 'edit'
 where r.code = 'SUPER_ADMIN'
on conflict (role_id, permission_id) do nothing;

-- ---------------------------------------------------------------------------------------------
-- 2. Receipt header guard
-- ---------------------------------------------------------------------------------------------
create or replace function rms_private.department_receipts_insert_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_routing  record;
  v_status   text;
  v_actor    uuid := rms_private.current_actor();
begin
  select status, store_id, gs_id into v_routing
    from public.department_routings where id = new.routing_id for update;
  if v_routing.status is null or v_routing.status not in ('DISPATCHED', 'PARTIALLY_RECEIVED') then
    raise exception 'G-20: department receipt needs an open routing (current status: %)',
      coalesce(v_routing.status, 'missing')
      using errcode = 'P0001';
  end if;

  if v_routing.store_id is not null then
    -- DEC-68: the Intermediate Store that issued the goods receives them back.
    if not coalesce(rms_private.user_holds_permission(v_actor, 'store_routing', 'edit')
                    and rms_private.user_acts_for_store(v_actor, v_routing.store_id), false) then
      raise exception 'DEC-68: only a user of the Intermediate Store that routed the goods receives them back'
        using errcode = '42501';
    end if;
    select status into v_status from public.goods_slips where id = v_routing.gs_id;
    if v_status is distinct from 'STORE_PROCESSING' then
      raise exception 'DEC-68: goods are received back while the goods slip is in store processing (current status: %)',
        coalesce(v_status, 'missing') using errcode = '23514';
    end if;
  end if;
  return new;
end;
$$;
revoke all on function rms_private.department_receipts_insert_guard() from public, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- 3. Receipt line guard (full body; only the destination default changes)
-- ---------------------------------------------------------------------------------------------
create or replace function rms_private.department_receipt_lines_insert_guard()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_head        record;
  v_rl          record;
  v_lib         record;
  v_store_loc   text;
begin
  select rl.id, rl.gs_item_id, rl.source_bucket_field_id, gi.product_id,
         gs.item_field_profile_version_id as version_id, gi.line_no, r.store_id
    into v_rl
    from public.department_receipts rc
    join public.department_routings r on r.id = rc.routing_id
    join public.department_routing_lines rl on rl.routing_id = rc.routing_id
    join public.gs_items gi on gi.id = rl.gs_item_id
    join public.goods_slips gs on gs.id = gi.gs_id
   where rc.id = new.receipt_id and rl.id = new.routing_line_id;
  if not found then
    raise exception 'G-20: receipt line % does not belong to the receipt''s routing', new.routing_line_id
      using errcode = 'P0001';
  end if;

  select code, label, is_wastage, returns_to_routing, is_active, destination_location_code into v_head
    from public.department_outcome_heads
   where id = new.outcome_head_id;
  if not found or not v_head.is_active then
    raise exception 'G-20: receipt line needs an active outcome head (%)', new.outcome_head_id
      using errcode = 'P0001';
  end if;

  -- DEC-43 flags drive G-20 (returns_to_routing) and stock (is_wastage): always from the head.
  new.outcome_code       := v_head.code;
  new.outcome_label      := v_head.label;
  new.is_wastage         := v_head.is_wastage;
  new.returns_to_routing := v_head.returns_to_routing;
  -- DEC-56 Q8 / Q17: destination from the head; default wastage → scrap, else back to the store.
  new.destination_location_code := coalesce(
    v_head.destination_location_code,
    case when v_head.is_wastage then 'SCRAP_DISPOSED' else 'INTERMEDIATE_STORE' end);
  -- DEC-68: "back to the store" is the location of the Intermediate Store that routed the goods.
  if v_rl.store_id is not null and new.destination_location_code = 'INTERMEDIATE_STORE' then
    select l.code into v_store_loc
      from public.intermediate_stores s
      join public.inventory_locations l on l.id = s.location_id
     where s.id = v_rl.store_id;
    if v_store_loc is null then
      raise exception 'DEC-68: the Intermediate Store of this routing has no stock location' using errcode = 'P0001';
    end if;
    new.destination_location_code := v_store_loc;
  end if;

  -- DEC-56 Q7: condition after work.
  new.source_condition_field_id := v_rl.source_bucket_field_id;
  if v_rl.source_bucket_field_id is null then
    if new.condition_field_id is not null then
      raise exception 'G-20: item line % was routed without a condition; no condition after work is recorded for it',
        v_rl.line_no using errcode = 'P0001';
    end if;
    new.condition_code  := null;
    new.condition_label := null;
    return new;
  end if;

  if new.condition_field_id is null then
    raise exception 'G-20: item line % was routed from a condition; record the condition it came back in (DEC-56)',
      v_rl.line_no using errcode = 'P0001';
  end if;

  select l.id, l.code, l.label, l.field_group into v_lib
    from public.item_field_library l where l.id = new.condition_field_id;
  if not found or v_lib.field_group is distinct from 'CATEGORISATION'
     or not exists (
       select 1 from rms_private.resolve_item_field_profile(v_rl.product_id, v_rl.version_id) r
        where r.field_group = 'CATEGORISATION' and r.field_id = new.condition_field_id
     ) then
    raise exception 'G-18: condition % is not in the categorisation list of item line %',
      coalesce(v_lib.code, new.condition_field_id::text), v_rl.line_no
      using errcode = 'P0001';
  end if;

  -- Label snapshot (G-18): the label in force when the receipt was booked.
  new.condition_code  := v_lib.code;
  new.condition_label := v_lib.label;

  perform rms_private.move_item_condition(
    v_rl.gs_item_id, v_rl.source_bucket_field_id, new.condition_field_id, new.quantity);
  return new;
end;
$$;
revoke all on function rms_private.department_receipt_lines_insert_guard() from public, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- 4. Journey catalogue (grants and role menus: seed.sql + snippet)
-- ---------------------------------------------------------------------------------------------
alter table public.journey_steps drop constraint if exists journey_steps_screen_key_check;
alter table public.journey_steps add constraint journey_steps_screen_key_check check (screen_key in (
  'journey-queue', 'gs-new', 'gs-list', 'dashboard', 'pendencies',
  'container-audit', 'reports', 'audit', 'custody', 'inventory', 'store-issues',
  'servicing', 'batteries', 'dismantling', 'scrap', 'credit-notes', 'approvals',
  'dispatch-queue', 'department-routing', 'department-receiving', 'department-issue',
  'accounts-entry', 'accounts-docs', 'dispatch-slips', 'transfer-slips', 'transfer-slip-acks',
  'store-routing', 'store-receiving'));

alter table public.journey_steps drop constraint if exists journey_steps_item_screen_key_check;
alter table public.journey_steps add constraint journey_steps_item_screen_key_check check (
  item_screen_key is null or item_screen_key in (
    'gs-detail', 'gs-unboxing', 'gs-itemization', 'gs-inspection', 'gs-rm-review',
    'custody-transfer', 'gs-final-actions', 'department-receiving', 'department-issue',
    'accounts-entry-gs', 'accounts-docs', 'dispatch-slips',
    'gs-party-notification', 'transfer-slips', 'transfer-slip', 'gs-store-routing',
    'gs-store-receiving'));

alter table public.journey_steps drop constraint if exists journey_steps_queue_code_check;
alter table public.journey_steps add constraint journey_steps_queue_code_check check (
  queue_code is null or queue_code in (
    'CARTON_OPENING', 'COUNTING', 'CATEGORISATION', 'INSPECTION', 'RM_REVIEW', 'STORE_ACCEPT',
    'DEPT_ROUTING', 'DEPT_ISSUE', 'DEPT_RECEIVING', 'FINAL_ACTIONS', 'ACCOUNTS_DOCS',
    'ACCOUNTS_ENTRY', 'DISPATCH_SLIP', 'PARTY_EMAIL', 'PENDING_TRANSFER_SLIP', 'EDIT_REQUESTS',
    'STORE_ACK', 'STORE_ROUTING', 'STORE_RECEIVING'));

insert into public.journey_steps
  (code, label, hint, kind, screen_key, item_screen_key, queue_code, feature_code,
   perm_module, perm_action, sort_order, source_ref)
values
  ('STORE_DEPT_RECEIVING', 'Receive from Departments',
   'Goods your Intermediate Store sent to departments: record what came back, the outcome and the condition',
   'STEP', 'store-receiving', 'gs-store-receiving', 'STORE_RECEIVING', null,
   'store_routing', 'edit', 59, 'DEC-68')
on conflict (code) do nothing;
