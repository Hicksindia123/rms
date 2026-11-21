-- =============================================================================================
-- Phase P7 (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-67 (Q14 PROVISIONAL; Q29 / Q31 user).
-- Department routing by the Intermediate Store user (Steps 4–5 of the 20-11-2026 flow).
--
-- After its own transfer slip is acknowledged (P6), an Intermediate Store routes ITS lines of a GS
-- (per item + current condition) to departments. Saving the routing IS the issue: there is no
-- separate RM plan and no Store Manager issue step for these goods slips (DEC-55 superseded for
-- them). The existing tables carry it:
--   department_routing_plan_lines  one row per (item, condition, department): ISSUED for a work
--                                  department, NO_WORK for "Issue to Store" (no stock move)
--   department_routings            one DIN per department, stock store location → department
--                                  location through rms_move_stock (the service, same transaction)
-- so G-20 (quantity conservation), the DEC-55 check "every routing line is the issue of a plan
-- line" and rms_private.gs_routing_started (the DEC-64 edit window, which already counts plan
-- lines and routings) apply unchanged.
--
-- 1. Status STORE_PROCESSING ("In Store Processing"): the first routing of any store moves the
--    GS out of TRANSFER_SLIP_GENERATED (Q29: a store routes after ITS acknowledgement, other
--    stores may still be on their way) or STORE_ACKNOWLEDGED. P8–P11 add its exits.
-- 2. store_id on plan lines and routings: NULL = legacy DEC-55 path (GS held at the legacy
--    Intermediate Store), set = DEC-67 store routing. P8 returns the pieces to that store.
-- 3. Helpers: the store holding an item (its relevant lines on live transfer slips), whether the
--    store acknowledged it, the qty still to route, and the progress per GS and store:
--    AWAITING_ACKNOWLEDGEMENT → ROUTING_PENDING → AT_DEPARTMENTS / READY_FOR_ANALYSIS.
-- 4. Plan-line insert guard (full body: G3 body for legacy + the DEC-67 branch). DEC-67 guards:
--    store_routing.create + a user of the item's store (Super Admin or the store role; not
--    Management), the store acknowledged the item, the department is allowed by the GS's PINNED
--    profile version (P0 F9; legacy keeps the live profile), a condition is chosen when the item
--    is split, and qty ≤ the qty still to route (G-20).
-- 5. Routing insert guard (full body: G2 body + the DEC-67 branch): same store / status rules.
-- 6. G-03 status chain (full body: P6 body + STORE_PROCESSING).
-- 7. Permission module store_routing (view / create), journey catalogue entry STORE_DEPT_ROUTING
--    (queue STORE_ROUTING, user-scoped). Grants and menus: seed.sql + the release snippet.
-- Legacy GSs (HELD_AT_INTERMEDIATE_STORE) keep the RM plan + Store Manager issue path; the
-- legacy queues only ever list them.
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- 1. Status
-- ---------------------------------------------------------------------------------------------
alter table public.goods_slips drop constraint goods_slips_status_check;
alter table public.goods_slips
  add constraint goods_slips_status_check check (status in (
    'GATE_CREATED', 'UNBOXING', 'ITEMIZATION', 'CATEGORISATION', 'CSR_APPROVAL_PENDING',
    'INSPECTION', 'RM_REVIEW', 'PENDING_TRANSFER_SLIP', 'TRANSFER_SLIP_GENERATED',
    'STORE_ACKNOWLEDGED', 'STORE_PROCESSING', 'SALES_RETURN_HOLD', 'HELD_AT_INTERMEDIATE_STORE',
    'IN_PROCESS', 'COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION', 'CLOSED', 'CANCELLED'));

-- ---------------------------------------------------------------------------------------------
-- 2. Store on plan lines and routings
-- ---------------------------------------------------------------------------------------------
alter table public.department_routing_plan_lines
  add column store_id uuid references public.intermediate_stores (id) on delete restrict;
create index dept_plan_lines_store_idx on public.department_routing_plan_lines (store_id)
  where store_id is not null;
comment on column public.department_routing_plan_lines.store_id is
  'DEC-67: the Intermediate Store that routed these pieces (its user saved the routing = the issue). NULL = legacy RM plan (DEC-55).';

alter table public.department_routings
  add column store_id uuid references public.intermediate_stores (id) on delete restrict;
create index dept_routings_store_idx on public.department_routings (store_id)
  where store_id is not null;
comment on column public.department_routings.store_id is
  'DEC-67: the Intermediate Store whose location the pieces left (and return to, P8). NULL = legacy Intermediate Store (DEC-55).';

-- ---------------------------------------------------------------------------------------------
-- 3. Helpers
-- ---------------------------------------------------------------------------------------------
-- DEC-67: the store an item belongs to = the store of its relevant lines on live transfer slips
-- (P5 puts every line of an item on the slip of the store its product maps to).
create or replace function rms_private.gs_item_store(p_gs_item_id uuid)
returns uuid
language sql
stable
set search_path = ''
as $$
  select min(s.store_id::text)::uuid
    from public.transfer_slip_lines l
    join public.transfer_slips s on s.id = l.slip_id
   where l.gs_item_id = p_gs_item_id and l.is_relevant
     and s.status in ('GENERATED', 'ACKNOWLEDGED')
$$;
revoke all on function rms_private.gs_item_store(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_item_store(uuid) to rms_api;

-- DEC-67: every physical piece of the item is on an ACKNOWLEDGED slip (it is in the store).
create or replace function rms_private.gs_item_acknowledged(p_gs_item_id uuid)
returns boolean
language sql
stable
set search_path = ''
as $$
  select gi.received_qty > 0
     and coalesce((select sum(l.qty)
                     from public.transfer_slip_lines l
                     join public.transfer_slips s on s.id = l.slip_id
                    where l.gs_item_id = gi.id and l.is_relevant
                      and s.status = 'ACKNOWLEDGED'), 0) = gi.received_qty
    from public.gs_items gi
   where gi.id = p_gs_item_id and gi.removed_at is null
$$;
revoke all on function rms_private.gs_item_acknowledged(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_item_acknowledged(uuid) to rms_api;

-- G-20 / DEC-67: pieces of the item in the store that are not routed yet (same identity as
-- rms_private.validate_department_reconciliation: in store = counted − at departments − back
-- with a final outcome − actioned; minus PLANNED and NO_WORK plan lines). Pieces back with a
-- "return to routing" outcome are routable again.
create or replace function rms_private.gs_item_routable_qty(p_gs_item_id uuid)
returns integer
language sql
stable
set search_path = ''
as $$
  with q as (
    select gi.received_qty as counted,
           coalesce((select sum(rl.qty_sent - rl.qty_received)
                       from public.department_routing_lines rl
                       join public.department_routings r on r.id = rl.routing_id
                      where rl.gs_item_id = gi.id
                        and r.status in ('DISPATCHED', 'PARTIALLY_RECEIVED')), 0) as at_dept,
           coalesce((select sum(rcl.quantity)
                       from public.department_receipt_lines rcl
                       join public.department_routing_lines rl on rl.id = rcl.routing_line_id
                      where rl.gs_item_id = gi.id and not rcl.returns_to_routing), 0) as outcomes,
           coalesce((select sum(a.qty) from public.rm_item_actions a
                      where a.gs_item_id = gi.id and a.is_current and a.round_no = 1), 0) as actioned,
           coalesce((select sum(p.qty) from public.department_routing_plan_lines p
                      where p.gs_item_id = gi.id and p.status in ('PLANNED', 'NO_WORK')), 0) as planned
      from public.gs_items gi
     where gi.id = p_gs_item_id
  )
  select greatest(counted - at_dept - greatest(outcomes - actioned, 0) - actioned - planned, 0)::integer
    from q
$$;
revoke all on function rms_private.gs_item_routable_qty(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_item_routable_qty(uuid) to rms_api;

-- DEC-67: progress of each Intermediate Store on one GS (its lines on live transfer slips).
--   AWAITING_ACKNOWLEDGEMENT  the store has not acknowledged its slip yet
--   ROUTING_PENDING           pieces in the store still to route
--   AT_DEPARTMENTS            everything routed, pieces still at a department
--   READY_FOR_ANALYSIS        everything routed and back (or no work): ready for P9
create or replace function rms_private.gs_store_routing_progress(p_gs_id uuid)
returns table (
  store_id      uuid,
  store_code    text,
  store_name    text,
  total_qty     integer,
  unrouted_qty  integer,
  at_dept_qty   integer,
  no_work_qty   integer,
  status        text
)
language sql
stable
set search_path = ''
as $$
  with items as (
    select gi.id, rms_private.gs_item_store(gi.id) as store_id, gi.received_qty,
           rms_private.gs_item_acknowledged(gi.id) as acked
      from public.gs_items gi
     where gi.gs_id = p_gs_id and gi.removed_at is null and gi.received_qty > 0
  ),
  per_item as (
    select i.store_id, i.received_qty, i.acked,
           case when i.acked then rms_private.gs_item_routable_qty(i.id) else i.received_qty end as unrouted,
           coalesce((select sum(rl.qty_sent - rl.qty_received)
                       from public.department_routing_lines rl
                       join public.department_routings r on r.id = rl.routing_id
                      where rl.gs_item_id = i.id
                        and r.status in ('DISPATCHED', 'PARTIALLY_RECEIVED')), 0) as at_dept,
           coalesce((select sum(p.qty) from public.department_routing_plan_lines p
                      where p.gs_item_id = i.id and p.status = 'NO_WORK'), 0) as no_work
      from items i
     where i.store_id is not null
  ),
  agg as (
    select p.store_id, sum(p.received_qty)::integer as total_qty,
           sum(p.unrouted)::integer as unrouted_qty, sum(p.at_dept)::integer as at_dept_qty,
           sum(p.no_work)::integer as no_work_qty, bool_and(p.acked) as acked
      from per_item p
     group by p.store_id
  )
  select a.store_id, s.code, s.name, a.total_qty, a.unrouted_qty, a.at_dept_qty, a.no_work_qty,
         case when not a.acked then 'AWAITING_ACKNOWLEDGEMENT'
              when a.unrouted_qty > 0 then 'ROUTING_PENDING'
              when a.at_dept_qty > 0 then 'AT_DEPARTMENTS'
              else 'READY_FOR_ANALYSIS' end
    from agg a
    join public.intermediate_stores s on s.id = a.store_id
   order by s.sort_order, s.code
$$;
revoke all on function rms_private.gs_store_routing_progress(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_store_routing_progress(uuid) to rms_api;
comment on function rms_private.gs_store_routing_progress(uuid) is
  'DEC-67: per Intermediate Store on a GS: AWAITING_ACKNOWLEDGEMENT → ROUTING_PENDING → AT_DEPARTMENTS / READY_FOR_ANALYSIS.';

-- DEC-67 statuses in which a store routes (Q29: before the other stores acknowledged).
create or replace function rms_private.gs_store_routing_status_ok(p_status text)
returns boolean
language sql
immutable
set search_path = ''
as $$
  select p_status in ('TRANSFER_SLIP_GENERATED', 'STORE_ACKNOWLEDGED', 'STORE_PROCESSING')
$$;
revoke all on function rms_private.gs_store_routing_status_ok(text) from public, anon, authenticated;
grant execute on function rms_private.gs_store_routing_status_ok(text) to rms_api;

-- ---------------------------------------------------------------------------------------------
-- 4. Plan-line insert guard (full body: 20261118000200 G3 body = legacy + the DEC-67 branch)
-- ---------------------------------------------------------------------------------------------
create or replace function rms_private.department_plan_lines_insert_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_status   text;
  v_version  uuid;
  v_product  uuid;
  v_line_no  integer;
  v_dept     record;
  v_bucket   text;
  v_store    uuid;
  v_free     integer;
  v_actor    uuid := rms_private.current_actor();
begin
  select status, item_field_profile_version_id into v_status, v_version
    from public.goods_slips where id = new.gs_id for update;

  if new.store_id is null then
    -- Legacy DEC-55: the RM plans a GS held at the legacy Intermediate Store.
    if v_status is distinct from 'HELD_AT_INTERMEDIATE_STORE' then
      raise exception 'G-20: a routing plan needs the goods slip held at the intermediate store (current status: %)',
        coalesce(v_status, 'missing') using errcode = 'P0001';
    end if;
  else
    -- DEC-67: the Intermediate Store routes its own acknowledged goods.
    if not rms_private.gs_store_routing_status_ok(v_status) then
      raise exception 'DEC-67: department routing needs the goods slip at its Intermediate Stores (current status: %)',
        coalesce(v_status, 'missing') using errcode = '23514';
    end if;
    if not rms_private.user_holds_permission(v_actor, 'store_routing', 'create')
       or not rms_private.user_acts_for_store(v_actor, new.store_id) then
      raise exception 'DEC-67: only a user of the Intermediate Store routes its goods' using errcode = '42501';
    end if;
  end if;

  if exists (select 1 from public.ac_action_slips s where s.gs_id = new.gs_id and s.status = 'CURRENT') then
    raise exception 'G-21: final actions of this goods slip are finalised; revise them before planning new routing'
      using errcode = 'P0001';
  end if;

  select gi.product_id, gi.line_no into v_product, v_line_no
    from public.gs_items gi where gi.id = new.gs_item_id and gi.gs_id = new.gs_id;
  if not found then
    raise exception 'G-20: routing plan item % does not belong to the goods slip', new.gs_item_id
      using errcode = 'P0001';
  end if;

  if new.store_id is not null then
    v_store := rms_private.gs_item_store(new.gs_item_id);
    if v_store is distinct from new.store_id then
      raise exception 'DEC-67: item line % belongs to another Intermediate Store; it is routed by that store', v_line_no
        using errcode = '42501';
    end if;
    if not coalesce(rms_private.gs_item_acknowledged(new.gs_item_id), false) then
      raise exception 'DEC-67: item line % is not acknowledged by its Intermediate Store yet', v_line_no
        using errcode = '23514';
    end if;
  end if;

  -- DEC-56: the condition comes from the item's CURRENT split.
  if new.source_bucket_field_id is not null then
    select c.field_label into v_bucket
      from rms_private.item_current_conditions(new.gs_item_id) c
     where c.field_id = new.source_bucket_field_id;
    if not found then
      raise exception 'G-20: condition % is not a categorisation bucket of this item', new.source_bucket_field_id
        using errcode = 'P0001';
    end if;
  elsif new.store_id is not null
        and exists (select 1 from rms_private.item_current_conditions(new.gs_item_id) c where c.current_qty > 0) then
    raise exception 'G-20: item line % is split by condition; route each condition (DEC-67)', v_line_no
      using errcode = 'P0001';
  end if;

  select id, code, label, is_active into v_dept
    from public.item_field_library
   where id = new.department_field_id and field_group = 'DEPARTMENT';
  if not found or not v_dept.is_active then
    raise exception 'G-20: routing plan needs an active DEPARTMENT field (%)', new.department_field_id
      using errcode = 'P0001';
  end if;

  -- DEC-67 (P0 F9): a store routes against the profile version the GS was locked under;
  -- the legacy path keeps the live profile (DEC-55).
  if not exists (
    select 1 from rms_private.resolve_item_field_profile(
                    v_product, case when new.store_id is null then null else v_version end) r
     where r.field_group = 'DEPARTMENT' and r.field_id = v_dept.id
  ) then
    raise exception 'G-20: department % is not allowed by the resolved profile of this product', v_dept.code
      using errcode = 'P0001';
  end if;

  -- DEC-67: never more than the pieces of the item still to route at the store (G-20).
  if new.store_id is not null then
    v_free := rms_private.gs_item_routable_qty(new.gs_item_id);
    if new.qty > v_free then
      raise exception 'G-20: item line %: only % pc(s) left to route at the store, % requested', v_line_no, v_free, new.qty
        using errcode = 'P0001';
    end if;
  end if;

  -- Snapshots (G-18) and the initial status are never trusted from the client.
  new.department_code     := v_dept.code;
  new.department_label    := v_dept.label;
  new.source_bucket_label := v_bucket;
  new.is_no_work          := rms_private.department_is_no_work(v_dept.code);
  new.status              := case when new.is_no_work then 'NO_WORK' else 'PLANNED' end;
  new.planned_by          := coalesce(v_actor, new.planned_by);
  new.routing_id          := null;
  new.routing_line_id     := null;
  new.issued_by           := null;
  new.issued_at           := null;
  new.cancelled_by        := null;
  new.cancelled_at        := null;
  new.cancel_reason       := null;
  return new;
end;
$$;
revoke all on function rms_private.department_plan_lines_insert_guard() from public, anon, authenticated;

-- The store of a plan line never changes (the update guard checks every other column).
create or replace function rms_private.department_plan_lines_store_immutable()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.store_id is distinct from old.store_id then
    raise exception 'DEC-67: the store of a routing line cannot change' using errcode = '42501';
  end if;
  return new;
end;
$$;
revoke all on function rms_private.department_plan_lines_store_immutable() from public, anon, authenticated;
create trigger trg_dept_plan_lines_store_immutable
  before update on public.department_routing_plan_lines
  for each row execute function rms_private.department_plan_lines_store_immutable();

-- ---------------------------------------------------------------------------------------------
-- 5. Routing (DIN) insert guard (full body: 20261118000100 G2 body + the DEC-67 branch)
-- ---------------------------------------------------------------------------------------------
create or replace function rms_private.department_routings_insert_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_status text;
  v_dept   record;
  v_actor  uuid := rms_private.current_actor();
begin
  -- Lock the GS so its status cannot change under this issue (G-20 serialisation).
  select status into v_status from public.goods_slips where id = new.gs_id for update;
  if new.store_id is null then
    if v_status is distinct from 'HELD_AT_INTERMEDIATE_STORE' then
      raise exception 'G-20: department routing needs the goods slip held at the intermediate store (current status: %)',
        coalesce(v_status, 'missing')
        using errcode = 'P0001';
    end if;
  else
    -- DEC-67: the store user's routing is the issue.
    if not rms_private.gs_store_routing_status_ok(v_status) then
      raise exception 'DEC-67: department routing needs the goods slip at its Intermediate Stores (current status: %)',
        coalesce(v_status, 'missing') using errcode = '23514';
    end if;
    if not rms_private.user_holds_permission(v_actor, 'store_routing', 'create')
       or not rms_private.user_acts_for_store(v_actor, new.store_id) then
      raise exception 'DEC-67: only a user of the Intermediate Store issues its goods to departments' using errcode = '42501';
    end if;
  end if;

  select code, label, is_active into v_dept
    from public.item_field_library
   where id = new.department_field_id and field_group = 'DEPARTMENT';
  if not found or not v_dept.is_active then
    raise exception 'G-20: department routing needs an active DEPARTMENT field (%)', new.department_field_id
      using errcode = 'P0001';
  end if;

  -- DEC-55: no-work departments are never issued; work departments go to their own location.
  if rms_private.department_is_no_work(v_dept.code) then
    raise exception 'G-20: department % needs no work; its pieces stay in the intermediate store', v_dept.code
      using errcode = 'P0001';
  end if;
  if new.location_id is null then
    raise exception 'G-20: a department issue needs the department''s stock location (%)', v_dept.code
      using errcode = 'P0001';
  end if;

  -- Label snapshot comes from the library (G-18), not from the client.
  new.department_code  := v_dept.code;
  new.department_label := v_dept.label;
  return new;
end;
$$;
revoke all on function rms_private.department_routings_insert_guard() from public, anon, authenticated;

-- DEC-67: an issued plan line and its routing belong to the same store (checked at commit with
-- the DEC-55 "every routing line is an issued plan line" check).
create or replace function rms_private.department_routing_lines_from_plan()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if not exists (
    select 1 from public.department_routing_plan_lines p
      join public.department_routings r on r.id = p.routing_id
     where p.routing_line_id = new.id and p.status = 'ISSUED'
       and r.store_id is not distinct from p.store_id
  ) then
    raise exception 'G-20: department routing line % has no issued routing plan line of the same store (DEC-55 / DEC-67)', new.id
      using errcode = 'P0001';
  end if;
  return null;
end;
$$;
revoke all on function rms_private.department_routing_lines_from_plan() from public, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- 6. Status chain (G-03 trigger, full body replaced: P6 body + STORE_PROCESSING)
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
  -- DEC-65 (P5): a locked GS leaves PENDING_TRANSFER_SLIP only when every physical line is on a
  -- live transfer slip; a void (Q10) brings it back while any line is uncovered.
  if old.status = 'PENDING_TRANSFER_SLIP' then
    if new.status = 'TRANSFER_SLIP_GENERATED' then
      if rms_private.gs_transfer_slip_gaps(new.id) > 0 then
        raise exception 'DEC-65: every physical line of the goods slip must be on a live transfer slip'
          using errcode = '23514';
      end if;
      return new;
    end if;
    raise exception 'G-03: a locked GS leaves PENDING_TRANSFER_SLIP only through its transfer slips (DEC-65), not to %', new.status
      using errcode = '23514';
  end if;
  -- DEC-67 (P7, Q29): the first department routing of any store (a store routes after its own
  -- acknowledgement, the other stores may still be acknowledging).
  if new.status = 'STORE_PROCESSING' then
    if old.status not in ('TRANSFER_SLIP_GENERATED', 'STORE_ACKNOWLEDGED') then
      raise exception 'G-03: STORE_PROCESSING is reached from the transfer slips / store acknowledgement (from %)', old.status
        using errcode = '23514';
    end if;
    if rms_private.gs_transfer_slip_gaps(new.id) > 0 or not rms_private.gs_routing_started(new.id) then
      raise exception 'DEC-67: STORE_PROCESSING needs the goods slip fully on transfer slips and a department routing'
        using errcode = '23514';
    end if;
    return new;
  end if;
  if old.status = 'TRANSFER_SLIP_GENERATED' then
    if new.status = 'PENDING_TRANSFER_SLIP' then
      if rms_private.gs_transfer_slip_gaps(new.id) = 0 then
        raise exception 'DEC-65: the goods slip is still fully on live transfer slips' using errcode = '23514';
      end if;
      return new;
    end if;
    -- DEC-66 (P6): every live slip of the GS acknowledged by its Intermediate Store.
    if new.status = 'STORE_ACKNOWLEDGED' then
      if not rms_private.gs_slips_acknowledged(new.id) then
        raise exception 'DEC-66: every transfer slip of the goods slip must be acknowledged by its store first'
          using errcode = '23514';
      end if;
      return new;
    end if;
    raise exception 'G-03: a goods slip on transfer slips goes to STORE_ACKNOWLEDGED (DEC-66), STORE_PROCESSING (DEC-67) or back to PENDING_TRANSFER_SLIP (Q10), not %', new.status
      using errcode = '23514';
  end if;
  -- DEC-66: an acknowledged GS goes back only when a slip of it is voided (Q10).
  if old.status = 'STORE_ACKNOWLEDGED' then
    if new.status = 'PENDING_TRANSFER_SLIP' then
      if rms_private.gs_transfer_slip_gaps(new.id) = 0 then
        raise exception 'DEC-65: the goods slip is still fully on live transfer slips' using errcode = '23514';
      end if;
      return new;
    end if;
    raise exception 'G-03: % is not reachable from STORE_ACKNOWLEDGED (department routing goes to STORE_PROCESSING, DEC-67)', new.status
      using errcode = '23514';
  end if;
  -- DEC-67: receiving, analysis, Management approval and Accounts (P8–P11) add the exits.
  if old.status = 'STORE_PROCESSING' then
    raise exception 'G-03: % is not reachable from STORE_PROCESSING yet (P8–P11)', new.status
      using errcode = '23514';
  end if;
  if new.status in ('PENDING_TRANSFER_SLIP', 'SALES_RETURN_HOLD', 'TRANSFER_SLIP_GENERATED',
                    'STORE_ACKNOWLEDGED') then
    raise exception 'G-03: % is reached only from counting / categorisation / transfer slips (from %)', new.status, old.status
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
-- 7. Permission + journey catalogue (grants and role menus: seed.sql + snippet)
-- ---------------------------------------------------------------------------------------------
insert into public.permissions (module_code, action, description)
values
  ('store_routing', 'view',
   'See the department routing of the Intermediate Stores per goods slip (DEC-67)'),
  ('store_routing', 'create',
   'Route the user''s own Intermediate Store goods to departments; saving is the issue (DIN, DEC-67)')
on conflict (module_code, action) do nothing;

insert into public.role_permissions (role_id, permission_id, scope)
select r.id, p.id, 'all'
  from public.roles r
  join public.permissions p on p.module_code = 'store_routing'
 where r.code = 'SUPER_ADMIN'
on conflict (role_id, permission_id) do nothing;

alter table public.journey_steps drop constraint if exists journey_steps_screen_key_check;
alter table public.journey_steps add constraint journey_steps_screen_key_check check (screen_key in (
  'journey-queue', 'gs-new', 'gs-list', 'dashboard', 'pendencies',
  'container-audit', 'reports', 'audit', 'custody', 'inventory', 'store-issues',
  'servicing', 'batteries', 'dismantling', 'scrap', 'credit-notes', 'approvals',
  'dispatch-queue', 'department-routing', 'department-receiving', 'department-issue',
  'accounts-entry', 'accounts-docs', 'dispatch-slips', 'transfer-slips', 'transfer-slip-acks',
  'store-routing'));

alter table public.journey_steps drop constraint if exists journey_steps_item_screen_key_check;
alter table public.journey_steps add constraint journey_steps_item_screen_key_check check (
  item_screen_key is null or item_screen_key in (
    'gs-detail', 'gs-unboxing', 'gs-itemization', 'gs-inspection', 'gs-rm-review',
    'custody-transfer', 'gs-final-actions', 'department-receiving', 'department-issue',
    'accounts-entry-gs', 'accounts-docs', 'dispatch-slips',
    'gs-party-notification', 'transfer-slips', 'transfer-slip', 'gs-store-routing'));

alter table public.journey_steps drop constraint if exists journey_steps_queue_code_check;
alter table public.journey_steps add constraint journey_steps_queue_code_check check (
  queue_code is null or queue_code in (
    'CARTON_OPENING', 'COUNTING', 'CATEGORISATION', 'INSPECTION', 'RM_REVIEW', 'STORE_ACCEPT',
    'DEPT_ROUTING', 'DEPT_ISSUE', 'DEPT_RECEIVING', 'FINAL_ACTIONS', 'ACCOUNTS_DOCS',
    'ACCOUNTS_ENTRY', 'DISPATCH_SLIP', 'PARTY_EMAIL', 'PENDING_TRANSFER_SLIP', 'EDIT_REQUESTS',
    'STORE_ACK', 'STORE_ROUTING'));

insert into public.journey_steps
  (code, label, hint, kind, screen_key, item_screen_key, queue_code, feature_code,
   perm_module, perm_action, sort_order, source_ref)
values
  ('STORE_DEPT_ROUTING', 'Department Routing',
   'Goods slips acknowledged by your Intermediate Store: route each condition to a department',
   'STEP', 'store-routing', 'gs-store-routing', 'STORE_ROUTING', null,
   'store_routing', 'create', 58, 'DEC-67')
on conflict (code) do nothing;
