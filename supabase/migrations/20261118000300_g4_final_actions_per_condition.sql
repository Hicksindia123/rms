-- Gap plan 2026-11-17 · Phase G4 — Final actions per condition
-- (docs/RMS_GAP_PLAN_2026-11-17.md G4; DEC-57; Q9–Q12; closes DEC-47's open destinations;
--  Guards G-15, G-20, G-21, G-22).
--
-- Workflow step 9: the RM decides the final actions per item + CURRENT condition (DEC-56), the
-- pieces of every action go to a defined place, and pieces marked Pending are re-actioned later in
-- a follow-up round that goes through Accounts again (user decision 2026-11-18, DEC-57).
--
-- 1. rm_item_actions: round_no (1 = the first decision; 2+ = re-action of the pieces still Pending
--    after the previous round) and the condition (condition_field_id + code / label snapshot,
--    G-18). An item with a condition split names the condition on every new action; an item
--    without a split never does. The "one current row" index now includes round and condition.
-- 2. ac_action_slips.round_no: one CURRENT slip per goods slip AND round. A round-2 slip continues
--    the same slip number (next version) and does not supersede the completed round-1 slip.
--    ac_entry_completions / dispatch_slips: one per A/c Actions slip (no longer one per goods slip).
--    ac_entry_lines.condition_label: the condition shown to Accounts (snapshot).
-- 3. G-21 per condition: rms_private.final_action_condition_quantities() (round 1); the split check
--    adds "no condition gets more actions than it has available" and, for every round >= 2,
--    "the round's actions per item + condition = the previous round's Pending pieces".
--    G-20 and the item quantities count round 1 only (it already covers every piece once).
-- 4. Guards per round: round 1 changes / finalises / Accounts-completes while the goods slip is held
--    at the intermediate store (unchanged); a later round only after the previous round was
--    completed by Accounts and settled (Dispatch Slip dispatched, if any), while the goods slip is
--    still open (IN_PROCESS / COMMERCIAL_RESOLUTION / AWAITING_NOTIFICATION).
-- 5. Closure checklist (G-15): every round's slip completed, every Dispatch Slip dispatched, CN
--    lines of every round need the prior notification, stock the A/c flow moved to the Rejected Hold
--    counts as accounted (Q11), and new item NO_PENDING_REACTION (Q10: the goods slip stays open
--    until every Pending piece got a final action).
-- 6. Config: dispatch.returned_goods_location_by_action gains PENDING_BP → PENDING_HOLD,
--    NOT_ALLOWED → REJECTED_HOLD, SEND_NEW → NON_FUNCTIONAL_STORE (Q10–Q12; admin entries kept);
--    ACTION PENDING_BP relabelled "Pending" (code unchanged, rule e; repeated in seed.sql because the
--    ACTION library is built from seed data on a fresh reset).
-- Messages carry "G-15" / "G-20" / "G-21" / "G-22" so the API maps them to the 409 guard envelope.

-- ===========================================================================
-- 1. rm_item_actions: round + condition
-- ===========================================================================
alter table public.rm_item_actions
  add column round_no            integer not null default 1 check (round_no >= 1),
  add column condition_field_id  uuid references public.item_field_library (id) on delete restrict,
  add column condition_code      text,
  add column condition_label     text;

create index rm_item_actions_condition_field_idx on public.rm_item_actions (condition_field_id);

comment on column public.rm_item_actions.round_no is
  'DEC-57: 1 = first final-action decision; 2+ = re-action of the pieces still Pending after the previous round (follow-up A/c Actions slip).';
comment on column public.rm_item_actions.condition_field_id is
  'DEC-57: the current condition (DEC-56) the action applies to. NULL only for items without a condition split (and rows saved before G4).';

drop index if exists public.rm_item_actions_current_uq;
create unique index rm_item_actions_current_uq
  on public.rm_item_actions (
    gs_item_id, round_no,
    coalesce(condition_field_id, '00000000-0000-0000-0000-000000000000'::uuid),
    action_code)
  where is_current;

-- ===========================================================================
-- 2. Slips / completions / dispatch slips per round
-- ===========================================================================
alter table public.ac_action_slips
  add column round_no integer not null default 1 check (round_no >= 1);
comment on column public.ac_action_slips.round_no is
  'DEC-57: the final-action round this slip version covers (1 = all pieces; 2+ = Pending re-action).';

drop index if exists public.ac_action_slips_one_current_idx;
create unique index ac_action_slips_one_current_idx
  on public.ac_action_slips (gs_id, round_no) where status = 'CURRENT';

drop index if exists public.ac_entry_completions_gs_idx;
create index ac_entry_completions_gs_idx on public.ac_entry_completions (gs_id);

alter table public.dispatch_slips drop constraint if exists dispatch_slips_gs_id_key;
create index dispatch_slips_gs_idx on public.dispatch_slips (gs_id);

alter table public.ac_entry_lines add column condition_label text;
comment on column public.ac_entry_lines.condition_label is
  'DEC-57: condition of the action line (snapshot of rm_item_actions.condition_label).';

-- ===========================================================================
-- 3. Helpers
-- ===========================================================================
-- Same as 20261113001100, plus: a goods slip with an A/c Actions slip is on the flow, so it stays
-- on it after it leaves the store stage (re-action rounds, DEC-57) even without a transfer slip.
create or replace function rms_private.gs_on_final_action_flow(p_gs_id uuid)
returns boolean
language sql
stable
set search_path = ''
as $$
  select exists (
    select 1 from public.goods_slips gs
     where gs.id = p_gs_id
       and (gs.transfer_slip_id is not null or gs.status = 'HELD_AT_INTERMEDIATE_STORE'
            or exists (select 1 from public.ac_action_slips s where s.gs_id = gs.id))
  );
$$;
revoke all on function rms_private.gs_on_final_action_flow(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_on_final_action_flow(uuid) to rms_api;

-- A round is settled when Accounts completed its CURRENT slip and its Dispatch Slip (if any) left.
create or replace function rms_private.final_action_round_settled(p_gs_id uuid, p_round integer)
returns boolean
language sql
stable
set search_path = ''
as $$
  select exists (
           select 1 from public.ac_action_slips s
             join public.ac_entry_completions c on c.ac_action_slip_id = s.id
            where s.gs_id = p_gs_id and s.round_no = p_round and s.status = 'CURRENT')
     and not exists (
           select 1 from public.ac_action_slips s
             join public.dispatch_slips d on d.ac_action_slip_id = s.id
            where s.gs_id = p_gs_id and s.round_no = p_round and s.status = 'CURRENT'
              and d.status = 'READY');
$$;
revoke all on function rms_private.final_action_round_settled(uuid, integer) from public, anon, authenticated;
grant execute on function rms_private.final_action_round_settled(uuid, integer) to rms_api;

-- Pieces marked Pending (stable code PENDING_BP, rule e) in a round.
create or replace function rms_private.final_action_pending_qty(p_gs_id uuid, p_round integer)
returns integer
language sql
stable
set search_path = ''
as $$
  select coalesce(sum(act.qty), 0)::integer
    from public.rm_item_actions act
    join public.gs_items gi on gi.id = act.gs_item_id
   where gi.gs_id = p_gs_id and act.is_current and act.round_no = p_round
     and act.action_code = 'PENDING_BP';
$$;
revoke all on function rms_private.final_action_pending_qty(uuid, integer) from public, anon, authenticated;
grant execute on function rms_private.final_action_pending_qty(uuid, integer) to rms_api;

-- ===========================================================================
-- 4. G-21 quantities: round 1 per item, and per item + current condition
-- ===========================================================================
-- Same columns as 20261113001100; actioned counts round 1 only (later rounds re-cover Pending).
create or replace function rms_private.final_action_item_quantities(p_gs_id uuid)
returns table (
  gs_item_id     uuid,
  line_no        integer,
  item_name      text,
  product_id     uuid,
  counted_qty    integer,
  at_dept_qty    integer,
  available_qty  integer,
  actioned_qty   integer
)
language sql
stable
set search_path = ''
as $$
  select gi.id, gi.line_no, coalesce(gi.product_name_snapshot, 'Item'), gi.product_id,
         gi.received_qty,
         coalesce(d.at_dept, 0)::integer,
         (gi.received_qty - coalesce(d.at_dept, 0))::integer,
         coalesce(a.actioned, 0)::integer
    from public.gs_items gi
    left join lateral (
      select sum(rl.qty_sent - rl.qty_received) as at_dept
        from public.department_routing_lines rl
        join public.department_routings r on r.id = rl.routing_id
       where rl.gs_item_id = gi.id
         and r.status in ('DISPATCHED', 'PARTIALLY_RECEIVED')
    ) d on true
    left join lateral (
      select sum(act.qty) as actioned
        from public.rm_item_actions act
       where act.gs_item_id = gi.id and act.is_current and act.round_no = 1
    ) a on true
   where gi.gs_id = p_gs_id
   order by gi.line_no;
$$;
revoke all on function rms_private.final_action_item_quantities(uuid) from public, anon, authenticated;
grant execute on function rms_private.final_action_item_quantities(uuid) to rms_api;

-- DEC-57 (Q9): per item + current condition (DEC-56). Items without a condition split have one
-- row with a NULL condition (the whole item). available = in the condition - still at a department
-- from that condition.
create or replace function rms_private.final_action_condition_quantities(p_gs_id uuid)
returns table (
  gs_item_id          uuid,
  line_no             integer,
  item_name           text,
  condition_field_id  uuid,
  condition_code      text,
  condition_label     text,
  sort_order          integer,
  current_qty         integer,
  at_dept_qty         integer,
  available_qty       integer,
  actioned_qty        integer
)
language sql
stable
set search_path = ''
as $$
  with items as (
    select gi.id, gi.line_no, coalesce(gi.product_name_snapshot, 'Item') as item_name,
           gi.received_qty,
           exists (select 1 from rms_private.item_current_conditions(gi.id)) as has_cond
      from public.gs_items gi
     where gi.gs_id = p_gs_id
  ),
  grp as (
    select i.id as gs_item_id, i.line_no, i.item_name, c.field_id, c.field_code, c.field_label,
           c.sort_order, c.current_qty
      from items i
      cross join lateral rms_private.item_current_conditions(i.id) c
     where i.has_cond
    union all
    select i.id, i.line_no, i.item_name, null::uuid, null::text, null::text, 0, i.received_qty
      from items i
     where not i.has_cond
  )
  select g.gs_item_id, g.line_no, g.item_name, g.field_id, g.field_code, g.field_label,
         g.sort_order, g.current_qty,
         coalesce(d.qty, 0)::integer,
         (g.current_qty - coalesce(d.qty, 0))::integer,
         coalesce(a.qty, 0)::integer
    from grp g
    left join lateral (
      select sum(rl.qty_sent - rl.qty_received) as qty
        from public.department_routing_lines rl
        join public.department_routings r on r.id = rl.routing_id
       where rl.gs_item_id = g.gs_item_id
         and r.status in ('DISPATCHED', 'PARTIALLY_RECEIVED')
         and (g.field_id is null or rl.source_bucket_field_id = g.field_id)
    ) d on true
    left join lateral (
      select sum(act.qty) as qty
        from public.rm_item_actions act
       where act.gs_item_id = g.gs_item_id and act.is_current and act.round_no = 1
         and act.condition_field_id is not distinct from g.field_id
    ) a on true
   order by g.line_no, g.sort_order, g.field_label;
$$;
revoke all on function rms_private.final_action_condition_quantities(uuid) from public, anon, authenticated;
grant execute on function rms_private.final_action_condition_quantities(uuid) to rms_api;
comment on function rms_private.final_action_condition_quantities(uuid) is
  'DEC-57: round-1 G-21 quantities per GS item + current condition (NULL condition = item without a split).';

-- ===========================================================================
-- 5. G-20: same as 20261118000200 (G3); actioned = round 1 only
-- ===========================================================================
create or replace function rms_private.validate_department_reconciliation(p_gs_id uuid)
returns void
language plpgsql
set search_path = ''
as $$
declare
  v_item          record;
  v_at_dept       integer;
  v_outcomes      integer;
  v_outcome_open  integer;
  v_actioned      integer;
  v_in_store      integer;
  v_planned       integer;
  v_cond          record;
begin
  for v_item in
    select id, line_no, coalesce(product_name_snapshot, 'Item') as item_name, received_qty
      from public.gs_items
     where gs_id = p_gs_id
     order by line_no asc
  loop
    select coalesce(sum(rl.qty_sent - rl.qty_received), 0)
      into v_at_dept
      from public.department_routing_lines rl
      join public.department_routings r on r.id = rl.routing_id
     where rl.gs_item_id = v_item.id
       and r.status in ('DISPATCHED', 'PARTIALLY_RECEIVED');

    select coalesce(sum(rcl.quantity), 0)
      into v_outcomes
      from public.department_receipt_lines rcl
      join public.department_routing_lines rl on rl.id = rcl.routing_line_id
     where rl.gs_item_id = v_item.id
       and not rcl.returns_to_routing;

    -- DEC-57: round 1 covers every piece once; later rounds re-action Pending pieces.
    select coalesce(sum(act.qty), 0)
      into v_actioned
      from public.rm_item_actions act
     where act.gs_item_id = v_item.id
       and act.is_current = true
       and act.round_no = 1;

    select coalesce(sum(p.qty), 0)
      into v_planned
      from public.department_routing_plan_lines p
     where p.gs_item_id = v_item.id
       and p.status = 'PLANNED';

    v_outcome_open := greatest(v_outcomes - v_actioned, 0);
    v_in_store := v_item.received_qty - v_at_dept - v_outcome_open - v_actioned;

    if v_in_store < 0 then
      raise exception 'G-20: Quantity conservation violation for item line % (%): counted (%) < at_departments (%) + outcome_heads (%) + actioned (%). Available store quantity cannot be negative (%)',
        v_item.line_no, v_item.item_name, v_item.received_qty, v_at_dept, v_outcome_open, v_actioned, v_in_store
        using errcode = 'P0001';
    end if;

    if v_planned > v_in_store then
      raise exception 'G-20: item line % (%): % pc(s) planned for departments but only % pc(s) in the intermediate store',
        v_item.line_no, v_item.item_name, v_planned, v_in_store
        using errcode = 'P0001';
    end if;

    select b.field_label, b.current_qty, b.committed_qty into v_cond
      from rms_private.item_condition_balances(v_item.id) b
     where b.free_qty < 0
     limit 1;
    if found then
      raise exception 'G-20: item line % (%) condition %: % pc(s) committed but only % pc(s) in that condition',
        v_item.line_no, v_item.item_name, v_cond.field_label, v_cond.committed_qty, v_cond.current_qty
        using errcode = 'P0001';
    end if;
  end loop;
end;
$$;
revoke all on function rms_private.validate_department_reconciliation(uuid) from public, anon, authenticated;
grant execute on function rms_private.validate_department_reconciliation(uuid) to rms_api;

-- ===========================================================================
-- 6. G-21 split check: G2 body (round 1) + per condition + later rounds
-- ===========================================================================
create or replace function rms_private.validate_final_action_split(
  p_gs_id     uuid,
  p_complete  boolean default false
)
returns void
language plpgsql
stable
set search_path = ''
as $$
declare
  v_item     record;
  v_version  uuid;
  v_bad      record;
  v_planned  record;
  v_cond     record;
  v_round    integer;
begin
  select item_field_profile_version_id into v_version from public.goods_slips where id = p_gs_id;

  if p_complete and not exists (
    select 1 from public.rm_item_actions act
      join public.gs_items gi on gi.id = act.gs_item_id
     where gi.gs_id = p_gs_id
  ) then
    raise exception 'G-21: no RM final actions have been saved for this goods slip'
      using errcode = 'P0001';
  end if;

  if p_complete then
    select gi.line_no, sum(p.qty)::integer as qty, min(p.department_label) as dept into v_planned
      from public.department_routing_plan_lines p
      join public.gs_items gi on gi.id = p.gs_item_id
     where p.gs_id = p_gs_id and p.status = 'PLANNED'
     group by gi.line_no
     order by gi.line_no
     limit 1;
    if found then
      raise exception 'G-21: item line % has % pc(s) planned for % but not issued by the store; issue or cancel them before finalising',
        v_planned.line_no, v_planned.qty, v_planned.dept
        using errcode = 'P0001';
    end if;
  end if;

  -- Round 1, per item: every piece not at a department has exactly one action.
  for v_item in select * from rms_private.final_action_item_quantities(p_gs_id) loop
    if p_complete and v_item.at_dept_qty > 0 then
      raise exception 'G-21: item line % (%) still has % pc(s) at a department; receive them back before finalising',
        v_item.line_no, v_item.item_name, v_item.at_dept_qty
        using errcode = 'P0001';
    end if;
    if v_item.actioned_qty <> v_item.available_qty then
      raise exception 'G-21: item line % (%): action qty total (%) must equal the qty available for action (%) = counted (%) - at departments (%)',
        v_item.line_no, v_item.item_name, v_item.actioned_qty, v_item.available_qty,
        v_item.counted_qty, v_item.at_dept_qty
        using errcode = 'P0001';
    end if;
  end loop;

  -- DEC-57 (Q9), round 1, per condition: never more actions than pieces available in it. With the
  -- per-item equality above this makes every condition exactly allocated.
  select q.line_no, q.item_name, q.condition_label, q.actioned_qty, q.available_qty into v_cond
    from rms_private.final_action_condition_quantities(p_gs_id) q
   where q.condition_field_id is not null and q.actioned_qty > q.available_qty
   order by q.line_no, q.sort_order
   limit 1;
  if found then
    raise exception 'G-21: item line % (%) condition %: action qty (%) exceeds the qty available in that condition (%)',
      v_cond.line_no, v_cond.item_name, v_cond.condition_label, v_cond.actioned_qty, v_cond.available_qty
      using errcode = 'P0001';
  end if;

  -- DEC-57: a current action names a condition the item has now (or none if it has no split).
  select gi.line_no, act.condition_label into v_cond
    from public.rm_item_actions act
    join public.gs_items gi on gi.id = act.gs_item_id
   where gi.gs_id = p_gs_id and act.is_current and act.condition_field_id is not null
     and not exists (select 1 from rms_private.item_current_conditions(gi.id) c
                      where c.field_id = act.condition_field_id)
   limit 1;
  if found then
    raise exception 'G-21: item line %: condition % is not in the item''s current condition split',
      v_cond.line_no, v_cond.condition_label
      using errcode = 'P0001';
  end if;

  -- DEC-57 (Q10), rounds >= 2: per item + condition, the round re-actions exactly the pieces the
  -- previous round left Pending.
  for v_round in
    select distinct act.round_no
      from public.rm_item_actions act
      join public.gs_items gi on gi.id = act.gs_item_id
     where gi.gs_id = p_gs_id and act.is_current and act.round_no > 1
     order by 1
  loop
    select gi.line_no, x.cond_label, coalesce(x.cur, 0) as cur, coalesce(x.prev, 0) as prev
      into v_cond
      from (
        select act.gs_item_id, act.condition_field_id,
               max(act.condition_label) as cond_label,
               sum(act.qty) filter (where act.round_no = v_round) as cur,
               sum(act.qty) filter (where act.round_no = v_round - 1
                                      and act.action_code = 'PENDING_BP') as prev
          from public.rm_item_actions act
          join public.gs_items gi2 on gi2.id = act.gs_item_id
         where gi2.gs_id = p_gs_id and act.is_current
           and act.round_no in (v_round, v_round - 1)
         group by act.gs_item_id, act.condition_field_id
      ) x
      join public.gs_items gi on gi.id = x.gs_item_id
     where coalesce(x.cur, 0) <> coalesce(x.prev, 0)
     order by gi.line_no
     limit 1;
    if found then
      raise exception 'G-21: re-action round %: item line % must re-action exactly the % Pending pc(s)% (actions total %)',
        v_round, v_cond.line_no, v_cond.prev,
        case when v_cond.cond_label is null then '' else ' of condition ' || v_cond.cond_label end,
        v_cond.cur
        using errcode = 'P0001';
    end if;
  end loop;

  select gi.line_no, act.action_code into v_bad
    from public.rm_item_actions act
    join public.gs_items gi on gi.id = act.gs_item_id
   where gi.gs_id = p_gs_id
     and act.is_current
     and not exists (
       select 1 from rms_private.resolve_item_field_profile(gi.product_id, v_version) r
        where r.field_group = 'ACTION' and r.code = act.action_code
     )
   limit 1;
  if found then
    raise exception 'G-21: action % is not allowed by the resolved profile of item line %',
      v_bad.action_code, v_bad.line_no
      using errcode = 'P0001';
  end if;
end;
$$;
revoke all on function rms_private.validate_final_action_split(uuid, boolean) from public, anon, authenticated;
grant execute on function rms_private.validate_final_action_split(uuid, boolean) to rms_api;

-- ===========================================================================
-- 7. rm_item_actions guard: per round + condition (replaces 20261113001100)
-- ===========================================================================
create or replace function rms_private.rm_item_actions_final_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_gs_id     uuid;
  v_line_no   integer;
  v_status    text;
  v_version   uuid;
  v_product   uuid;
  v_slip      record;
  v_cond      record;
  v_has_cond  boolean;
begin
  select gi.gs_id, gi.product_id, gi.line_no into v_gs_id, v_product, v_line_no
    from public.gs_items gi where gi.id = new.gs_item_id;
  if v_gs_id is null or not rms_private.gs_on_final_action_flow(v_gs_id) then
    return new;  -- P2-07 flow: unchanged
  end if;

  -- Serialise with department dispatches / receipts and other revisions of this GS (G-20 / G-21).
  select status, item_field_profile_version_id into v_status, v_version
    from public.goods_slips where id = v_gs_id for update;

  if new.round_no = 1 then
    if v_status is distinct from 'HELD_AT_INTERMEDIATE_STORE' then
      raise exception 'G-21: RM final actions change only while the goods slip is held at the intermediate store (status %)',
        v_status using errcode = 'P0001';
    end if;
  else
    -- DEC-57 (Q10): a Pending re-action follows a round Accounts completed and that was settled.
    if v_status is null or v_status not in ('IN_PROCESS', 'COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION') then
      raise exception 'G-21: Pending pieces are re-actioned only while the goods slip is open after the store stage (status %)',
        v_status using errcode = 'P0001';
    end if;
    if not rms_private.final_action_round_settled(v_gs_id, new.round_no - 1) then
      raise exception 'G-21: round % is not completed by Accounts and settled yet; its Pending pieces cannot be re-actioned',
        new.round_no - 1 using errcode = 'P0001';
    end if;
    if rms_private.final_action_pending_qty(v_gs_id, new.round_no - 1) = 0 then
      raise exception 'G-21: round % left no Pending pieces to re-action', new.round_no - 1
        using errcode = 'P0001';
    end if;
  end if;

  select slip_no, version_no into v_slip
    from public.ac_action_slips
   where gs_id = v_gs_id and round_no = new.round_no and status = 'CURRENT';
  if found then
    raise exception 'G-21: final actions are finalised on slip % v%; revise with a reason to supersede it first',
      v_slip.slip_no, v_slip.version_no using errcode = 'P0001';
  end if;

  if exists (select 1 from public.rm_item_actions act
               join public.gs_items gi on gi.id = act.gs_item_id
              where gi.gs_id = v_gs_id and act.is_current and act.round_no > new.round_no) then
    raise exception 'G-21: a later re-action round exists; round % can no longer change', new.round_no
      using errcode = 'P0001';
  end if;

  if tg_op = 'INSERT' and new.is_current then
    if not exists (
      select 1 from rms_private.resolve_item_field_profile(v_product, v_version) r
       where r.field_group = 'ACTION' and r.code = new.action_code
    ) then
      raise exception 'G-21: action % is not allowed by the resolved profile of this product',
        new.action_code using errcode = 'P0001';
    end if;

    -- DEC-57 (Q9): an item with a condition split is actioned per condition.
    v_has_cond := exists (select 1 from rms_private.item_current_conditions(new.gs_item_id));
    if v_has_cond then
      if new.condition_field_id is null then
        raise exception 'G-21: item line % has a condition split; every final action names its condition (DEC-57)',
          v_line_no using errcode = 'P0001';
      end if;
      select c.field_code, c.field_label into v_cond
        from rms_private.item_current_conditions(new.gs_item_id) c
       where c.field_id = new.condition_field_id;
      if not found then
        raise exception 'G-21: item line %: the condition is not in the item''s current condition split (DEC-57)',
          v_line_no using errcode = 'P0001';
      end if;
      new.condition_code := v_cond.field_code;
      new.condition_label := v_cond.field_label;
    elsif new.condition_field_id is not null then
      raise exception 'G-21: item line % has no condition split; its final actions name no condition',
        v_line_no using errcode = 'P0001';
    else
      new.condition_code := null;
      new.condition_label := null;
    end if;
  end if;
  return new;
end;
$$;
revoke all on function rms_private.rm_item_actions_final_guard() from public, anon, authenticated;

-- ===========================================================================
-- 8. A/c Actions slip guard per round (replaces 20261114000100 4g)
-- ===========================================================================
create or replace function rms_private.ac_action_slips_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_status    text;
  v_prev      record;
  v_max_rev   integer;
  v_att       record;
begin
  if tg_op = 'DELETE' then
    raise exception 'G-21: A/c Actions slips are never deleted (slip % v%)', old.slip_no, old.version_no
      using errcode = '42501';
  end if;

  if tg_op = 'UPDATE' then
    if old.status <> 'CURRENT' or new.status <> 'SUPERSEDED'
       or (to_jsonb(new) - array['status', 'superseded_at', 'superseded_by', 'supersede_reason'])
          <> (to_jsonb(old) - array['status', 'superseded_at', 'superseded_by', 'supersede_reason']) then
      raise exception 'G-21: an A/c Actions slip is immutable; the only change is CURRENT -> SUPERSEDED'
        using errcode = '42501';
    end if;
    if exists (select 1 from public.ac_entry_completions c where c.ac_action_slip_id = old.id) then
      raise exception 'G-22: Accounts completed A/c Actions slip % v%; it can no longer be revised',
        old.slip_no, old.version_no using errcode = 'P0001';
    end if;
    return new;
  end if;

  -- INSERT = finalise a round.
  select status into v_status from public.goods_slips where id = new.gs_id for update;
  if new.round_no = 1 then
    if v_status is distinct from 'HELD_AT_INTERMEDIATE_STORE' then
      raise exception 'G-21: final actions are finalised only while the goods slip is held at the intermediate store (status %)',
        coalesce(v_status, 'missing') using errcode = 'P0001';
    end if;
  else
    if v_status is null or v_status not in ('IN_PROCESS', 'COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION') then
      raise exception 'G-21: a Pending re-action is finalised only while the goods slip is open after the store stage (status %)',
        coalesce(v_status, 'missing') using errcode = 'P0001';
    end if;
    if not rms_private.final_action_round_settled(new.gs_id, new.round_no - 1) then
      raise exception 'G-21: round % is not completed by Accounts and settled yet', new.round_no - 1
        using errcode = 'P0001';
    end if;
  end if;

  if not exists (select 1 from public.rm_item_actions act
                   join public.gs_items gi on gi.id = act.gs_item_id
                  where gi.gs_id = new.gs_id and act.is_current and act.round_no = new.round_no) then
    raise exception 'G-21: no final actions are recorded for round %', new.round_no
      using errcode = 'P0001';
  end if;
  if exists (select 1 from public.rm_item_actions act
               join public.gs_items gi on gi.id = act.gs_item_id
              where gi.gs_id = new.gs_id and act.is_current and act.round_no > new.round_no) then
    raise exception 'G-21: a later re-action round exists; round % cannot be finalised', new.round_no
      using errcode = 'P0001';
  end if;

  perform rms_private.validate_final_action_split(new.gs_id, true);

  select coalesce(max(act.revision_no), 0) into v_max_rev
    from public.rm_item_actions act
    join public.gs_items gi on gi.id = act.gs_item_id
   where gi.gs_id = new.gs_id;
  if new.revision_no <> v_max_rev then
    raise exception 'G-21: the slip must capture the latest action revision (%), not %', v_max_rev, new.revision_no
      using errcode = 'P0001';
  end if;

  select slip_no, version_no into v_prev
    from public.ac_action_slips where gs_id = new.gs_id order by version_no desc limit 1;
  if found then
    if new.slip_no <> v_prev.slip_no or new.version_no <> v_prev.version_no + 1 then
      raise exception 'G-21: the next slip version of this goods slip is % v%', v_prev.slip_no, v_prev.version_no + 1
        using errcode = 'P0001';
    end if;
  elsif new.version_no <> 1
        or exists (select 1 from public.ac_action_slips s where s.slip_no = new.slip_no) then
    raise exception 'G-21: the first slip of a goods slip is version 1 with a new slip number'
      using errcode = 'P0001';
  end if;

  select gs_id, kind, status, mime_type into v_att from public.attachments where id = new.attachment_id;
  if not found or v_att.gs_id <> new.gs_id or v_att.kind <> 'GENERATED_PDF'
     or v_att.status <> 'CONFIRMED' or v_att.mime_type <> 'application/pdf' then
    raise exception 'G-21: the slip PDF must be a confirmed GENERATED_PDF attachment of the same goods slip'
      using errcode = 'P0001';
  end if;

  new.status := 'CURRENT';
  new.superseded_at := null;
  new.superseded_by := null;
  new.supersede_reason := null;
  return new;
end;
$$;
revoke all on function rms_private.ac_action_slips_guard() from public, anon, authenticated;

-- Entry lines: one per current action of the slip's round, with the condition snapshot.
create or replace function rms_private.ac_action_slips_create_entry_lines()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.ac_entry_lines
    (gs_id, ac_action_slip_id, rm_item_action_id, gs_item_id, line_no, action_code, action_label,
     qty, requires_cn, requires_challan, condition_label)
  select new.gs_id, new.id, act.id, gi.id, gi.line_no, act.action_code,
         coalesce(act.action_label, lib.label, act.action_code), act.qty,
         coalesce(lib.requires_cn, false), coalesce(lib.requires_challan, false),
         act.condition_label
    from public.rm_item_actions act
    join public.gs_items gi on gi.id = act.gs_item_id
    left join public.item_field_library lib
           on lib.field_group = 'ACTION' and lib.code = act.action_code
   where gi.gs_id = new.gs_id
     and act.is_current
     and act.round_no = new.round_no
     and act.qty > 0;
  return null;
end;
$$;
revoke all on function rms_private.ac_action_slips_create_entry_lines() from public, anon, authenticated;

-- ===========================================================================
-- 9. G-22 Accounts guards per round (replace 20261114000100 4b / 4c)
-- ===========================================================================
create or replace function rms_private.ac_entry_lines_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_slip         record;
  v_gs_status    text;
  v_other_gs     text;
begin
  if tg_op = 'DELETE' then
    raise exception 'G-22: Accounts entry lines are never deleted' using errcode = '42501';
  end if;

  if tg_op = 'UPDATE' then
    if (to_jsonb(new) - array['cn_no', 'cn_date', 'cn_value', 'challan_no', 'challan_date',
                              'entered_by', 'entered_at', 'updated_at'])
       <> (to_jsonb(old) - array['cn_no', 'cn_date', 'cn_value', 'challan_no', 'challan_date',
                                 'entered_by', 'entered_at', 'updated_at']) then
      raise exception 'G-22: only the Accounts fields of an entry line can change'
        using errcode = '42501';
    end if;
  end if;

  select status into v_gs_status from public.goods_slips where id = new.gs_id for update;
  select status, round_no into v_slip from public.ac_action_slips where id = new.ac_action_slip_id;

  if tg_op = 'UPDATE' then
    if v_slip.status is distinct from 'CURRENT' then
      raise exception 'G-22: the A/c Actions slip of this line is superseded; enter the data on the current version'
        using errcode = 'P0001';
    end if;
    if v_slip.round_no = 1 and v_gs_status is distinct from 'HELD_AT_INTERMEDIATE_STORE' then
      raise exception 'G-22: Accounts data changes only while the goods slip is held at the intermediate store (status %)',
        v_gs_status using errcode = 'P0001';
    end if;
    if v_slip.round_no > 1
       and (v_gs_status is null or v_gs_status not in ('IN_PROCESS', 'COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION')) then
      raise exception 'G-22: Accounts data of a Pending re-action changes only while the goods slip is open (status %)',
        v_gs_status using errcode = 'P0001';
    end if;
    if exists (select 1 from public.ac_entry_completions c where c.ac_action_slip_id = new.ac_action_slip_id) then
      raise exception 'G-22: the Accounts entry of this slip is complete and frozen'
        using errcode = 'P0001';
    end if;
  end if;

  if new.cn_date > current_date or new.challan_date > current_date then
    raise exception 'G-22: CN / Challan dates cannot be in the future' using errcode = 'P0001';
  end if;

  if new.cn_no is not null then
    perform pg_advisory_xact_lock(hashtext('ac_entry_cn_no:' || upper(btrim(new.cn_no))));
    select g.gs_no into v_other_gs
      from public.ac_entry_lines e
      join public.goods_slips g on g.id = e.gs_id
     where upper(btrim(e.cn_no)) = upper(btrim(new.cn_no))
       and e.gs_id <> new.gs_id
     limit 1;
    if found then
      raise exception 'G-22: CN No. % is already recorded on goods slip % (DEC-22)', new.cn_no, v_other_gs
        using errcode = 'P0001';
    end if;
    if exists (select 1 from public.credit_notes cn
                where upper(btrim(cn.cn_no)) = upper(btrim(new.cn_no))) then
      raise exception 'G-22: CN No. % is already recorded on a credit note (DEC-22)', new.cn_no
        using errcode = 'P0001';
    end if;
  end if;

  new.updated_at := now();
  return new;
end;
$$;
revoke all on function rms_private.ac_entry_lines_guard() from public, anon, authenticated;

create or replace function rms_private.ac_entry_completions_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_gs_status   text;
  v_slip        record;
  v_open        record;
begin
  if tg_op <> 'INSERT' then
    raise exception 'G-22: an Accounts completion is final' using errcode = '42501';
  end if;

  select status into v_gs_status from public.goods_slips where id = new.gs_id for update;
  select gs_id, status, round_no into v_slip from public.ac_action_slips where id = new.ac_action_slip_id;
  if not found or v_slip.gs_id <> new.gs_id or v_slip.status <> 'CURRENT' then
    raise exception 'G-22: Accounts completes the CURRENT A/c Actions slip of the same goods slip'
      using errcode = 'P0001';
  end if;

  if v_slip.round_no = 1 and v_gs_status is distinct from 'HELD_AT_INTERMEDIATE_STORE' then
    raise exception 'G-22: Accounts completes only while the goods slip is held at the intermediate store (status %)',
      coalesce(v_gs_status, 'missing') using errcode = 'P0001';
  end if;
  if v_slip.round_no > 1
     and (v_gs_status is null or v_gs_status not in ('IN_PROCESS', 'COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION')) then
    raise exception 'G-22: Accounts completes a Pending re-action only while the goods slip is open (status %)',
      coalesce(v_gs_status, 'missing') using errcode = 'P0001';
  end if;

  if not exists (select 1 from public.ac_entry_lines e where e.ac_action_slip_id = new.ac_action_slip_id) then
    raise exception 'G-22: the A/c Actions slip has no action lines' using errcode = 'P0001';
  end if;

  select e.line_no, e.action_label into v_open
    from public.ac_entry_lines e
   where e.ac_action_slip_id = new.ac_action_slip_id
     and not rms_private.ac_entry_line_complete(e)
   order by e.line_no
   limit 1;
  if found then
    raise exception 'G-22: item line % (%) still needs its Accounts data', v_open.line_no, v_open.action_label
      using errcode = 'P0001';
  end if;
  return new;
end;
$$;
revoke all on function rms_private.ac_entry_completions_guard() from public, anon, authenticated;

-- ===========================================================================
-- 10. Closure checklist (G-15): same as 20261114000100 section 6 with the DEC-57 changes
-- ===========================================================================
create or replace function rms_private.gs_closure_checklist(p_gs_id uuid)
returns table (
  sort_order  integer,
  code        text,
  rule_ref    text,
  applicable  boolean,
  passed      boolean,
  explanation text,
  details     jsonb
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_gs            record;
  v_csr           boolean;
  v_rows          jsonb;
  v_count         integer;
  v_needs_dec     boolean;
  v_has_dec       boolean;
  v_issued        integer;
  v_ac_flow       boolean;
  v_open_rounds   jsonb;
  v_open_count    integer;
  v_last_round    integer;
  v_pending       integer;
  v_dslips        jsonb;
  v_ready         integer;
  v_cn_lines      integer;
  v_notified      boolean;
begin
  select g.id, g.gs_no, g.status, g.category_code, g.has_discrepancy
    into v_gs from public.goods_slips g where g.id = p_gs_id;
  if not found then
    raise exception 'Goods slip % not found', p_gs_id using errcode = 'P0002';
  end if;
  v_csr := coalesce(v_gs.category_code = 'CSR', false);
  v_ac_flow := exists (select 1 from public.ac_action_slips s where s.gs_id = p_gs_id);

  -- 1. Status (§6.5).
  return query select 10, 'GS_STATUS', '§6.5', true,
    v_gs.status in ('IN_PROCESS', 'COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION'),
    case when v_gs.status in ('IN_PROCESS', 'COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION')
         then 'The GS is in a closable stage (' || v_gs.status || ')'
         else 'The GS is ' || v_gs.status || '; only an in-process / commercial-resolution GS can close' end,
    jsonb_build_object('status', v_gs.status);

  -- 2. Nothing in TRANSIT, PENDING_HOLD or INWARD_STAGING, nothing marked Pending (BP) (G-15).
  select coalesce(jsonb_agg(jsonb_build_object(
           'lot_id', l.id, 'location_code', loc.code, 'location_class', loc.location_class,
           'condition_class', l.condition_class, 'qty', b.qty, 'is_pending', l.is_pending)
           order by loc.code), '[]'::jsonb), count(*)
    into v_rows, v_count
    from public.stock_lots l
    join public.stock_balances b on b.lot_id = l.id and b.qty > 0
    join public.inventory_locations loc on loc.id = b.location_id
   where l.gs_id = p_gs_id
     and (loc.location_class in ('TRANSIT', 'PENDING_HOLD', 'INWARD') or l.is_pending);
  return query select 20, 'STOCK_NOT_IN_TRANSIT', 'G-15', true, v_count = 0,
    case when v_count = 0 then 'No stock of this GS is in transit, pending hold or inward staging'
         else v_count || ' stock balance(s) still in transit / pending hold / inward staging' end,
    jsonb_build_object('lots', v_rows);

  -- 3. Every remaining piece is in a terminal or accounted location (G-15, BR-30). DEC-57 (Q11):
  --    pieces the A/c Actions flow moved to the Rejected Hold (Not Allowed) are accounted.
  select coalesce(jsonb_agg(jsonb_build_object(
           'lot_id', l.id, 'location_code', loc.code, 'location_class', loc.location_class,
           'condition_class', l.condition_class, 'qty', b.qty,
           'reason', case when loc.location_class in ('REJECTED_HOLD', 'HAZARD_QUARANTINE')
                          then 'NO_DISPOSITION' else 'NOT_TERMINAL' end)
           order by loc.code), '[]'::jsonb), count(*)
    into v_rows, v_count
    from public.stock_lots l
    join public.stock_balances b on b.lot_id = l.id and b.qty > 0
    join public.inventory_locations loc on loc.id = b.location_id
   where l.gs_id = p_gs_id
     and not l.is_pending
     and loc.location_class not in ('TRANSIT', 'PENDING_HOLD', 'INWARD')
     and not (
       loc.location_class in ('MAIN_STORE', 'DISPATCHED', 'CREDITED', 'SCRAP_DISPOSED',
                              'SPARE_PARTS', 'NON_FUNCTIONAL')
       or (loc.location_class in ('REJECTED_HOLD', 'HAZARD_QUARANTINE')
           and exists (select 1 from public.rejections r where r.gs_item_id = l.gs_item_id))
       or (loc.location_class = 'REJECTED_HOLD'
           and exists (select 1 from public.stock_movements m
                        where m.lot_id = l.id and m.to_location_id = loc.id
                          and m.reference_type in ('ac_action_slips', 'dispatch_slips')))
     );
  return query select 30, 'STOCK_ACCOUNTED', 'G-15', true, v_count = 0,
    case when v_count = 0 then 'Every piece is issued, dispatched, with the Spare Parts Manager or on hold with a disposition'
         else v_count || ' stock balance(s) not yet in a terminal or accounted location' end,
    jsonb_build_object('lots', v_rows);

  -- 4. No open pendency (G-08 / G-15).
  select count(*) into v_count from public.pendencies p where p.gs_id = p_gs_id and p.status = 'OPEN';
  return query select 40, 'NO_OPEN_PENDENCY', 'G-08', true, v_count = 0,
    case when v_count = 0 then 'No open Pending (BP) pendency'
         else v_count || ' open Pending (BP) pendency(ies)' end,
    jsonb_build_object('open_pendencies', v_count);

  -- 5. No open discrepancy.
  select count(*) into v_count
    from (
      select t.id from public.custody_transfers t
       where t.gs_id = p_gs_id and t.status = 'DISCREPANCY'
      union all
      select a.id from public.stock_adjustments a
        join public.stock_lots l on l.id = a.lot_id
       where l.gs_id = p_gs_id and a.status = 'REQUESTED'
    ) d;
  return query select 50, 'NO_OPEN_DISCREPANCY', 'G-15', true,
    v_count = 0 and not v_gs.has_discrepancy,
    case when v_count = 0 and not v_gs.has_discrepancy then 'No open custody discrepancy or stock adjustment'
         else greatest(v_count, 1) || ' open discrepancy / adjustment request(s)' end,
    jsonb_build_object('open_discrepancies', v_count, 'has_discrepancy_flag', v_gs.has_discrepancy);

  -- 6. RM Step-7 CN decision (BR-32), not on the A/c Actions flow.
  v_needs_dec := not v_ac_flow and (v_csr or exists (
    select 1 from public.rm_item_actions a
      join public.gs_items gi on gi.id = a.gs_item_id
     where gi.gs_id = p_gs_id and a.is_current
       and a.action_code in ('ISSUE_CN', 'SEND_NEW', 'SEND_REPAIRED')));
  v_has_dec := exists (select 1 from public.rm_cn_decisions d where d.gs_id = p_gs_id and d.is_current);
  return query select 60, 'CN_DECISION_RECORDED', 'BR-32', v_needs_dec, (not v_needs_dec) or v_has_dec,
    case when v_ac_flow then 'On the A/c Actions flow the Replacement Manager''s finalised actions are the decision'
         when not v_needs_dec then 'No commercial resolution needed (no CN / replacement action)'
         when v_has_dec then 'The Replacement Manager''s CN decision is recorded'
         else 'The Replacement Manager''s Step-7 CN decision is missing' end,
    jsonb_build_object('decision_recorded', v_has_dec);

  -- 6b. AMD-18 + DEC-57: every final-action round has a CURRENT A/c Actions slip that Accounts
  --     completed.
  with rounds as (
    select distinct act.round_no
      from public.rm_item_actions act
      join public.gs_items gi on gi.id = act.gs_item_id
     where gi.gs_id = p_gs_id and act.is_current
  ),
  st as (
    select r.round_no, s.id as slip_id, s.slip_no, s.version_no,
           exists (select 1 from public.ac_entry_completions c where c.ac_action_slip_id = s.id) as completed
      from rounds r
      left join public.ac_action_slips s
             on s.gs_id = p_gs_id and s.round_no = r.round_no and s.status = 'CURRENT'
  )
  select coalesce(jsonb_agg(jsonb_build_object(
           'round_no', st.round_no, 'ac_action_slip_id', st.slip_id, 'slip_no', st.slip_no,
           'version_no', st.version_no, 'completed', st.completed) order by st.round_no)
           filter (where st.slip_id is null or not st.completed), '[]'::jsonb),
         count(*) filter (where st.slip_id is null or not st.completed)
    into v_open_rounds, v_open_count
    from st;
  return query select 65, 'AC_ENTRY_COMPLETE', 'AMD-18', v_ac_flow, (not v_ac_flow) or v_open_count = 0,
    case when not v_ac_flow then 'Not on the A/c Actions flow'
         when v_open_count = 0 then 'Accounts completed the CN / Challan entry of every A/c Actions slip'
         else v_open_count || ' final-action round(s) without a finalised A/c Actions slip completed by Accounts' end,
    jsonb_build_object('open_rounds', v_open_rounds);

  -- 6c. DEC-57 (Q10): the goods slip stays open until every Pending piece got a final action.
  select coalesce(max(act.round_no), 0) into v_last_round
    from public.rm_item_actions act
    join public.gs_items gi on gi.id = act.gs_item_id
   where gi.gs_id = p_gs_id and act.is_current;
  v_pending := case when v_last_round > 0
                    then rms_private.final_action_pending_qty(p_gs_id, v_last_round) else 0 end;
  return query select 66, 'NO_PENDING_REACTION', 'DEC-57', v_ac_flow, (not v_ac_flow) or v_pending = 0,
    case when not v_ac_flow then 'Not on the A/c Actions flow'
         when v_pending = 0 then 'No piece is waiting in Pending for a final action'
         else v_pending || ' pc(s) are Pending; the Replacement Manager must re-action them' end,
    jsonb_build_object('round_no', v_last_round, 'pending_qty', v_pending);

  -- 7. Every ALLOW_CN qty is covered by ISSUED credit notes / JVs (G-13, G-15).
  with allowed as (
    select dl.gs_item_id, sum(dl.qty)::int as qty
      from public.rm_cn_decisions d
      join public.rm_cn_decision_lines dl on dl.decision_id = d.id
     where d.gs_id = p_gs_id and d.is_current and dl.decision_code = 'ALLOW_CN'
     group by dl.gs_item_id),
  issued as (
    select cl.gs_item_id, sum(cl.qty)::int as qty
      from public.credit_notes cn
      join public.credit_note_lines cl on cl.credit_note_id = cn.id
     where cn.gs_id = p_gs_id and cn.status = 'ISSUED'
     group by cl.gs_item_id)
  select coalesce(jsonb_agg(jsonb_build_object(
           'gs_item_id', a.gs_item_id, 'line_no', gi.line_no, 'allowed_qty', a.qty,
           'issued_qty', coalesce(i.qty, 0)) order by gi.line_no), '[]'::jsonb),
         count(*) filter (where coalesce(i.qty, 0) < a.qty)
    into v_rows, v_count
    from allowed a
    join public.gs_items gi on gi.id = a.gs_item_id
    left join issued i on i.gs_item_id = a.gs_item_id;
  return query select 70, 'ALLOW_CN_COVERED', 'G-15', jsonb_array_length(v_rows) > 0, v_count = 0,
    case when jsonb_array_length(v_rows) = 0 then 'No quantity allowed for credit note'
         when v_count = 0 then 'Every ALLOW_CN quantity is covered by an issued CN / JV'
         else v_count || ' line(s) with ALLOW_CN quantity not yet covered by an issued CN / JV' end,
    jsonb_build_object('lines', v_rows);

  -- 8. Every DENY_CN_SEND_REPLACEMENT qty is dispatched (G-15).
  with denied as (
    select dl.gs_item_id, sum(dl.qty)::int as qty
      from public.rm_cn_decisions d
      join public.rm_cn_decision_lines dl on dl.decision_id = d.id
     where d.gs_id = p_gs_id and d.is_current and dl.decision_code = 'DENY_CN_SEND_REPLACEMENT'
     group by dl.gs_item_id),
  dispatched as (
    select rl.gs_item_id, sum(rl.qty)::int as qty
      from public.replacement_dispatches rd
      join public.replacement_dispatch_lines rl on rl.dispatch_id = rd.id
     where rd.gs_id = p_gs_id and rd.status = 'DISPATCHED'
     group by rl.gs_item_id)
  select coalesce(jsonb_agg(jsonb_build_object(
           'gs_item_id', d.gs_item_id, 'line_no', gi.line_no, 'denied_qty', d.qty,
           'dispatched_qty', coalesce(x.qty, 0)) order by gi.line_no), '[]'::jsonb),
         count(*) filter (where coalesce(x.qty, 0) < d.qty)
    into v_rows, v_count
    from denied d
    join public.gs_items gi on gi.id = d.gs_item_id
    left join dispatched x on x.gs_item_id = d.gs_item_id;
  return query select 80, 'DENY_QTY_DISPATCHED', 'G-15', jsonb_array_length(v_rows) > 0, v_count = 0,
    case when jsonb_array_length(v_rows) = 0 then 'No quantity denied for credit note'
         when v_count = 0 then 'Every replacement (CN denied) quantity is dispatched'
         else v_count || ' line(s) with a replacement not yet dispatched' end,
    jsonb_build_object('lines', v_rows);

  -- 8b. AMD-19 + DEC-57: every Dispatch Slip of the goods slip (one per round) is dispatched.
  select coalesce(jsonb_agg(jsonb_build_object(
           'dispatch_slip_id', d.id, 'slip_no', d.slip_no, 'status', d.status)
           order by d.generated_at), '[]'::jsonb),
         count(*) filter (where d.status = 'READY')
    into v_dslips, v_ready
    from public.dispatch_slips d where d.gs_id = p_gs_id;
  return query select 85, 'DISPATCH_SLIP_DISPATCHED', 'AMD-19', jsonb_array_length(v_dslips) > 0,
    v_ready = 0,
    case when jsonb_array_length(v_dslips) = 0 then 'No Dispatch Slip (no action line ships goods, or Accounts not complete yet)'
         when v_ready = 0 then 'Every Dispatch Slip is dispatched'
         else v_ready || ' Dispatch Slip(s) not dispatched yet' end,
    jsonb_build_object('dispatch_slips', v_dslips);

  -- 9. Every issued CN / JV has a PRIOR_INFO_SENT notification (BR-38). On the A/c Actions flow a
  --    CN entered by Accounts on any CURRENT slip (every round) needs a PRIOR_INFO_SENT record.
  select coalesce(jsonb_agg(jsonb_build_object(
           'credit_note_id', cn.id, 'voucher_no', coalesce(cn.cn_no, cn.jv_no),
           'cn_type_code', cn.cn_type_code,
           'notified', exists (select 1 from public.party_notifications pn
                                where pn.credit_note_id = cn.id and pn.status_code = 'PRIOR_INFO_SENT'))
           order by cn.issued_at), '[]'::jsonb), count(*)
    into v_rows, v_issued
    from public.credit_notes cn
   where cn.gs_id = p_gs_id and cn.status = 'ISSUED';
  select count(*) into v_count from jsonb_array_elements(v_rows) e where not (e->>'notified')::boolean;

  select count(*) into v_cn_lines
    from public.ac_entry_lines e
    join public.ac_action_slips s on s.id = e.ac_action_slip_id
   where s.gs_id = p_gs_id and s.status = 'CURRENT' and e.cn_no is not null;
  v_notified := exists (select 1 from public.party_notifications pn
                         where pn.gs_id = p_gs_id and pn.status_code = 'PRIOR_INFO_SENT');
  if v_cn_lines > 0 and not v_notified then
    v_count := v_count + 1;
  end if;

  return query select 90, 'PRIOR_NOTIFICATION', 'BR-38', v_issued > 0 or v_cn_lines > 0, v_count = 0,
    case when v_issued = 0 and v_cn_lines = 0 then 'No CN / JV issued, so no prior notification is required'
         when v_count = 0 then 'The party was notified of every issued CN / JV before closure'
         when v_cn_lines > 0 and not v_notified then 'The party has not been notified of the CN(s) entered by Accounts (PRIOR_INFO_SENT)'
         else v_count || ' issued CN / JV without a prior party notification (PRIOR_INFO_SENT)' end,
    jsonb_build_object('credit_notes', v_rows, 'ac_entry_cn_lines', v_cn_lines, 'gs_notified', v_notified);

  -- 10–12. Complete Sales Return closure (BR-09, BR-39, DD r80).
  select count(*) into v_count
    from public.custody_transfers t
   where t.gs_id = p_gs_id and t.purpose_code = 'CSR_WITH_PACKAGING' and t.with_packaging
     and t.status in ('ACCEPTED', 'RECONCILED');
  return query select 100, 'CSR_PACKAGING_HANDOVER', 'BR-39', v_csr, (not v_csr) or v_count > 0,
    case when not v_csr then 'Not a Complete Sales Return'
         when v_count > 0 then 'The goods were handed over with packaging and accepted'
         else 'The CSR handover with packaging has not been accepted yet' end,
    jsonb_build_object('accepted_transfers', v_count);

  select count(*) into v_count
    from public.packaging_replacements pr
    join public.stock_lots l on l.id = pr.lot_id
   where l.gs_id = p_gs_id;
  return query select 110, 'CSR_PACKAGING_CHECK', 'BR-39', v_csr, (not v_csr) or v_count > 0,
    case when not v_csr then 'Not a Complete Sales Return'
         when v_count > 0 then 'The packaging check is recorded'
         else 'No packaging check is recorded for this CSR' end,
    jsonb_build_object('packaging_checks', v_count);

  return query select 120, 'CSR_CN_ISSUED', 'BR-39', v_csr, (not v_csr) or v_issued > 0 or v_cn_lines > 0,
    case when not v_csr then 'Not a Complete Sales Return'
         when v_issued > 0 or v_cn_lines > 0 then 'A credit note / JV is issued'
         else 'No credit note / JV is issued for this CSR' end,
    jsonb_build_object('issued_credit_notes', v_issued, 'ac_entry_cn_lines', v_cn_lines);
end
$$;
revoke all on function rms_private.gs_closure_checklist(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_closure_checklist(uuid) to rms_api;

-- ===========================================================================
-- 11. Configuration (Q10–Q12)
-- ===========================================================================
-- Where the pieces of each action go when the round settles. Entries an admin already set win.
update public.system_settings
   set value = '{"PENDING_BP": "PENDING_HOLD", "NOT_ALLOWED": "REJECTED_HOLD", "SEND_NEW": "NON_FUNCTIONAL_STORE"}'::jsonb
               || value,
       description = 'Per action code: inventory location code that receives the pieces of the action line when its A/c Actions round settles (Accounts completion, or dispatch when goods ship). Send Repaired -> Dispatched, Issue CN -> Credited, Pending -> Pending Hold (re-actioned later), Not Allowed -> Rejected Hold, Send New -> Non-Functional Store (the old piece). Actions not listed keep their pieces in place.',
       source_ref = 'DEC-47, DEC-57'
 where key = 'dispatch.returned_goods_location_by_action'
   and jsonb_typeof(value) = 'object';

-- Gap plan G4: "Pending (BP)" is shown as "Pending" (code PENDING_BP unchanged). On a fresh reset the
-- ACTION library is built by seed.sql, which repeats this update.
update public.item_field_library
   set label = 'Pending'
 where field_group = 'ACTION' and code = 'PENDING_BP' and label = 'Pending (BP)';
