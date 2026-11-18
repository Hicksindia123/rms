-- Gap plan 2026-11-17 · Phase G3 — Receiving with the new condition
-- (docs/RMS_GAP_PLAN_2026-11-17.md G3; DEC-56; Q7, Q8, Q17; Guards G-18, G-20).
--
-- Workflow step 8: when pieces come back from a department, Aman (the receiving role, DEC-42)
-- records per receipt line the quantity, the outcome AND the condition the pieces came back in
-- (the categorisation list of that product). The item's CURRENT condition split is updated by
-- every receipt; the original counting split (gs_item_buckets) is never changed (history).
--
-- 1. department_outcome_heads.destination_location_code (configuration): where the stock goes.
--    NULL = default (wastage → SCRAP_DISPOSED as today, everything else → INTERMEDIATE_STORE,
--    no Store Manager acceptance, Q8). New head MERCURY_EXTRACTED → NON_FUNCTIONAL_STORE (Q17).
-- 2. gs_item_conditions: the current condition split per item. Filled from the counting split on
--    the item's first receipt (older GSs and legacy data need no backfill); read through
--    rms_private.item_current_conditions(), which falls back to the counting split until then.
--    Written only by the receipt-line guard (SECURITY DEFINER); rms_api may only read it.
-- 3. department_receipt_lines: source condition, condition after work (+ label snapshot, G-18)
--    and the destination location snapshot. The DB guard requires the condition when the routed
--    line came from a condition, rejects it otherwise, checks it is in the product's
--    categorisation list (GS profile version, G-18) and moves the pieces between conditions.
-- 4. rms_private.item_condition_balances(): per current condition, the pieces committed (planned,
--    no work, at a department, or back with a final outcome) and still free to plan. The plan
--    guard accepts any current condition (a piece may come back in a condition the counting split
--    did not have) and G-20 now also rejects over-planning a single condition.
-- 5. Fix (G2): the plan-line UPDATE G-20 check runs at commit. A Store issue of two or more plan
--    lines of one item (e.g. 7 Good + 3 Damaged) inserts all routing lines before marking the plan
--    lines ISSUED; checked immediately, G-20 saw the pieces both "at the department" and "still
--    planned" and rejected a valid issue. Inserts stay immediate; the service validates again.
-- Messages carry "G-18" / "G-20" so the API maps them to the standard 409 guard envelope.

-- ===========================================================================
-- 1. Outcome heads: destination location (configuration) + "Mercury Extracted"
-- ===========================================================================
alter table public.department_outcome_heads
  add column destination_location_code text
    check (destination_location_code is null or destination_location_code ~ '^[A-Z][A-Z0-9_]*$');

comment on column public.department_outcome_heads.destination_location_code is
  'DEC-56: inventory location code the received pieces move to. NULL = default: wastage → SCRAP_DISPOSED, otherwise back to INTERMEDIATE_STORE (Q8).';

insert into public.department_outcome_heads
  (code, label, description, is_wastage, returns_to_routing, sort_order, destination_location_code)
values
  ('MERCURY_EXTRACTED', 'Mercury Extracted',
   'Mercury extracted by the department; the piece goes to the Non-Functional Store (DEC-56 Q17)',
   false, false, 45, 'NON_FUNCTIONAL_STORE')
on conflict (code) do nothing;

-- 1b. Receipt lines: condition after work + destination snapshot (filled by the guard, section 3).
alter table public.department_receipt_lines
  add column source_condition_field_id uuid references public.item_field_library (id) on delete restrict,
  add column condition_field_id        uuid references public.item_field_library (id) on delete restrict,
  add column condition_code            text,
  add column condition_label           text,
  add column destination_location_code text;

comment on column public.department_receipt_lines.condition_field_id is
  'DEC-56 Q7: condition the pieces came back in (categorisation list of the product). NULL for items without a condition split and for receipts made before G3.';
comment on column public.department_receipt_lines.source_condition_field_id is
  'DEC-56: condition the pieces were routed from (snapshot of the routing line).';
comment on column public.department_receipt_lines.destination_location_code is
  'DEC-56: location the stock moved to (snapshot of the outcome head destination / default). NULL for receipts made before G3.';

-- ===========================================================================
-- 2. Current condition per item
-- ===========================================================================
create table public.gs_item_conditions (
  id              uuid primary key default gen_random_uuid(),
  gs_item_id      uuid not null references public.gs_items (id) on delete cascade,
  field_id        uuid not null references public.item_field_library (id) on delete restrict,
  field_code      text not null,
  label_snapshot  text not null,
  qty             integer not null check (qty >= 0),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  constraint gs_item_conditions_item_field_key unique (gs_item_id, field_id)
);

create index gs_item_conditions_item_idx on public.gs_item_conditions (gs_item_id);

comment on table public.gs_item_conditions is
  'DEC-56: current condition split per GS item, updated by every department receipt. The counting split (gs_item_buckets) stays unchanged as history. Rows exist from the item''s first receipt; before that the counting split is the current split (rms_private.item_current_conditions).';

-- Current split of one item: the table once it has rows, otherwise the counting split.
create or replace function rms_private.item_current_conditions(p_gs_item_id uuid)
returns table (
  field_id      uuid,
  field_code    text,
  field_label   text,
  sort_order    integer,
  original_qty  integer,
  current_qty   integer
)
language sql
stable
set search_path = ''
as $$
  with has_rows as (
    select exists (select 1 from public.gs_item_conditions c where c.gs_item_id = p_gs_item_id) as yes
  ),
  b as (
    select bk.field_id, bk.field_code, bk.label_snapshot, bk.qty
      from public.gs_item_buckets bk where bk.gs_item_id = p_gs_item_id
  ),
  c as (
    select ci.field_id, ci.field_code, ci.label_snapshot, ci.qty
      from public.gs_item_conditions ci where ci.gs_item_id = p_gs_item_id
  )
  select coalesce(c.field_id, b.field_id),
         coalesce(c.field_code, b.field_code),
         coalesce(c.label_snapshot, b.label_snapshot),
         coalesce(l.sort_order, 0),
         coalesce(b.qty, 0)::integer,
         (case when (select yes from has_rows) then coalesce(c.qty, 0) else coalesce(b.qty, 0) end)::integer
    from b
    full join c on c.field_id = b.field_id
    left join public.item_field_library l on l.id = coalesce(c.field_id, b.field_id)
   order by coalesce(l.sort_order, 0), coalesce(c.label_snapshot, b.label_snapshot);
$$;
revoke all on function rms_private.item_current_conditions(uuid) from public, anon, authenticated;
grant execute on function rms_private.item_current_conditions(uuid) to rms_api;
comment on function rms_private.item_current_conditions(uuid) is
  'DEC-56: current condition split of a GS item (original = counting split, current = after department work).';

-- Per current condition: committed pieces and what is still free to plan (DEC-55 Q6 + DEC-56).
-- committed = planned (PLANNED / NO_WORK) from the condition
--           + issued and still at a department from the condition
--           + back from a department with a final outcome, now in the condition
-- Pieces back with a "return to routing" outcome are free again in the condition they came back in.
create or replace function rms_private.item_condition_balances(p_gs_item_id uuid)
returns table (
  field_id       uuid,
  field_code     text,
  field_label    text,
  sort_order     integer,
  original_qty   integer,
  current_qty    integer,
  committed_qty  integer,
  free_qty       integer
)
language sql
stable
set search_path = ''
as $$
  with cur as (
    select * from rms_private.item_current_conditions(p_gs_item_id)
  ),
  committed as (
    select p.source_bucket_field_id as field_id, sum(p.qty)::integer as qty
      from public.department_routing_plan_lines p
     where p.gs_item_id = p_gs_item_id
       and p.status in ('PLANNED', 'NO_WORK')
       and p.source_bucket_field_id is not null
     group by p.source_bucket_field_id
    union all
    select rl.source_bucket_field_id, sum(rl.qty_sent - rl.qty_received)::integer
      from public.department_routing_lines rl
      join public.department_routings r on r.id = rl.routing_id
     where rl.gs_item_id = p_gs_item_id
       and r.status in ('DISPATCHED', 'PARTIALLY_RECEIVED')
       and rl.source_bucket_field_id is not null
     group by rl.source_bucket_field_id
    union all
    select coalesce(rcl.condition_field_id, rl.source_bucket_field_id), sum(rcl.quantity)::integer
      from public.department_receipt_lines rcl
      join public.department_routing_lines rl on rl.id = rcl.routing_line_id
     where rl.gs_item_id = p_gs_item_id
       and not rcl.returns_to_routing
       and coalesce(rcl.condition_field_id, rl.source_bucket_field_id) is not null
     group by coalesce(rcl.condition_field_id, rl.source_bucket_field_id)
  ),
  com as (
    select c.field_id, sum(c.qty)::integer as qty from committed c group by c.field_id
  )
  select cur.field_id, cur.field_code, cur.field_label, cur.sort_order,
         cur.original_qty, cur.current_qty,
         coalesce(com.qty, 0)::integer,
         (cur.current_qty - coalesce(com.qty, 0))::integer
    from cur
    left join com on com.field_id = cur.field_id
   order by cur.sort_order, cur.field_label;
$$;
revoke all on function rms_private.item_condition_balances(uuid) from public, anon, authenticated;
grant execute on function rms_private.item_condition_balances(uuid) to rms_api;
comment on function rms_private.item_condition_balances(uuid) is
  'DEC-55/DEC-56: per current condition of a GS item, the committed pieces and the pieces still free to plan.';

-- Moves received pieces from their source condition to the condition after work. Called only by
-- the receipt-line guard (SECURITY DEFINER); no role may call it directly.
create or replace function rms_private.move_item_condition(
  p_gs_item_id  uuid,
  p_from_field  uuid,
  p_to_field    uuid,
  p_qty         integer
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_have  integer;
  v_label text;
  v_lib   record;
begin
  if p_qty is null or p_qty <= 0 then
    raise exception 'G-20: condition change needs a positive quantity' using errcode = 'P0001';
  end if;

  -- First receipt of the item: the counting split becomes the current split.
  if not exists (select 1 from public.gs_item_conditions where gs_item_id = p_gs_item_id) then
    insert into public.gs_item_conditions (gs_item_id, field_id, field_code, label_snapshot, qty)
    select b.gs_item_id, b.field_id, b.field_code, b.label_snapshot, b.qty
      from public.gs_item_buckets b
     where b.gs_item_id = p_gs_item_id;
  end if;

  select qty, label_snapshot into v_have, v_label
    from public.gs_item_conditions
   where gs_item_id = p_gs_item_id and field_id = p_from_field
   for update;
  if not found or v_have < p_qty then
    raise exception 'G-20: only % pc(s) of this item are in condition % (% received back)',
      coalesce(v_have, 0), coalesce(v_label, p_from_field::text), p_qty
      using errcode = 'P0001';
  end if;

  if p_from_field = p_to_field then
    return;  -- same condition after work: nothing moves
  end if;

  select id, code, label into v_lib from public.item_field_library where id = p_to_field;

  update public.gs_item_conditions
     set qty = qty - p_qty
   where gs_item_id = p_gs_item_id and field_id = p_from_field;

  insert into public.gs_item_conditions (gs_item_id, field_id, field_code, label_snapshot, qty)
  values (p_gs_item_id, v_lib.id, v_lib.code, v_lib.label, p_qty)
  on conflict (gs_item_id, field_id) do update
    set qty = public.gs_item_conditions.qty + excluded.qty;
end;
$$;
-- Default privileges grant rms_api EXECUTE on rms_private functions: revoke it explicitly.
revoke all on function rms_private.move_item_condition(uuid, uuid, uuid, integer) from public, anon, authenticated, rms_api;

-- ===========================================================================
-- 3. Receipt lines guard: condition after work + destination snapshot (columns: section 1b)
-- ===========================================================================
-- Replaces the Phase 6 guard (same checks) and adds the DEC-56 condition rules. SECURITY DEFINER:
-- it is the only writer of gs_item_conditions.
create or replace function rms_private.department_receipt_lines_insert_guard()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_head    record;
  v_rl      record;
  v_lib     record;
begin
  select rl.id, rl.gs_item_id, rl.source_bucket_field_id, gi.product_id,
         gs.item_field_profile_version_id as version_id, gi.line_no
    into v_rl
    from public.department_receipts rc
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
-- trigger trg_dept_receipt_lines_insert_guard (Phase 6 hardening) already calls this function.

-- ===========================================================================
-- 4. Plan guard: any current condition; G-20 per condition
-- ===========================================================================
create or replace function rms_private.department_plan_lines_insert_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_status   text;
  v_product  uuid;
  v_dept     record;
  v_bucket   text;
begin
  select status into v_status from public.goods_slips where id = new.gs_id for update;
  if v_status is distinct from 'HELD_AT_INTERMEDIATE_STORE' then
    raise exception 'G-20: a routing plan needs the goods slip held at the intermediate store (current status: %)',
      coalesce(v_status, 'missing') using errcode = 'P0001';
  end if;

  if exists (select 1 from public.ac_action_slips s where s.gs_id = new.gs_id and s.status = 'CURRENT') then
    raise exception 'G-21: final actions of this goods slip are finalised; revise them before planning new routing'
      using errcode = 'P0001';
  end if;

  select gi.product_id into v_product
    from public.gs_items gi where gi.id = new.gs_item_id and gi.gs_id = new.gs_id;
  if not found then
    raise exception 'G-20: routing plan item % does not belong to the goods slip', new.gs_item_id
      using errcode = 'P0001';
  end if;

  -- DEC-56: the condition comes from the item's CURRENT split (it may differ from the counting
  -- split after department work).
  if new.source_bucket_field_id is not null then
    select c.field_label into v_bucket
      from rms_private.item_current_conditions(new.gs_item_id) c
     where c.field_id = new.source_bucket_field_id;
    if not found then
      raise exception 'G-20: condition % is not a categorisation bucket of this item', new.source_bucket_field_id
        using errcode = 'P0001';
    end if;
  end if;

  select id, code, label, is_active into v_dept
    from public.item_field_library
   where id = new.department_field_id and field_group = 'DEPARTMENT';
  if not found or not v_dept.is_active then
    raise exception 'G-20: routing plan needs an active DEPARTMENT field (%)', new.department_field_id
      using errcode = 'P0001';
  end if;

  if not exists (
    select 1 from rms_private.resolve_item_field_profile(v_product) r
     where r.field_group = 'DEPARTMENT' and r.field_id = v_dept.id
  ) then
    raise exception 'G-20: department % is not allowed by the resolved profile of this product', v_dept.code
      using errcode = 'P0001';
  end if;

  -- Snapshots (G-18) and the initial status are never trusted from the client.
  new.department_code     := v_dept.code;
  new.department_label    := v_dept.label;
  new.source_bucket_label := v_bucket;
  new.is_no_work          := rms_private.department_is_no_work(v_dept.code);
  new.status              := case when new.is_no_work then 'NO_WORK' else 'PLANNED' end;
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

-- G-20 (unchanged identity, G2 planned check) + DEC-56: no condition is committed beyond its
-- current quantity.
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

    select coalesce(sum(act.qty), 0)
      into v_actioned
      from public.rm_item_actions act
     where act.gs_item_id = v_item.id
       and act.is_current = true;

    select coalesce(sum(p.qty), 0)
      into v_planned
      from public.department_routing_plan_lines p
     where p.gs_item_id = v_item.id
       and p.status = 'PLANNED';

    -- AMD-16: an RM final action covers a piece wherever it waits (outcome head first, then store).
    v_outcome_open := greatest(v_outcomes - v_actioned, 0);
    v_in_store := v_item.received_qty - v_at_dept - v_outcome_open - v_actioned;

    if v_in_store < 0 then
      raise exception 'G-20: Quantity conservation violation for item line % (%): counted (%) < at_departments (%) + outcome_heads (%) + actioned (%). Available store quantity cannot be negative (%)',
        v_item.line_no, v_item.item_name, v_item.received_qty, v_at_dept, v_outcome_open, v_actioned, v_in_store
        using errcode = 'P0001';
    end if;

    -- DEC-55: planned, not yet issued pieces are still in the store.
    if v_planned > v_in_store then
      raise exception 'G-20: item line % (%): % pc(s) planned for departments but only % pc(s) in the intermediate store',
        v_item.line_no, v_item.item_name, v_planned, v_in_store
        using errcode = 'P0001';
    end if;

    -- DEC-55 Q6 / DEC-56: per current condition, committed pieces never exceed the condition.
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
-- 5. Fix (G2): plan-line updates are checked at commit
-- ===========================================================================
drop trigger if exists trg_dept_plan_lines_g20 on public.department_routing_plan_lines;
create trigger trg_dept_plan_lines_g20
  after insert on public.department_routing_plan_lines
  for each row execute function rms_private.trg_dept_plan_lines_reconciliation();
create constraint trigger trg_dept_plan_lines_g20_update
  after update on public.department_routing_plan_lines
  deferrable initially deferred
  for each row execute function rms_private.trg_dept_plan_lines_reconciliation();

-- ===========================================================================
-- 6. Audit, timestamps, RLS, privileges
-- ===========================================================================
create trigger audit_row
  after insert or update or delete on public.gs_item_conditions
  for each row execute function rms_private.audit_row();

create trigger set_updated_at
  before update on public.gs_item_conditions
  for each row execute function rms_private.set_updated_at();

alter table public.gs_item_conditions enable row level security;
create policy gs_item_conditions_api_read on public.gs_item_conditions
  for select to rms_api using (true);

-- Read-only for the API: only the receipt-line guard (SECURITY DEFINER) writes it.
revoke all on public.gs_item_conditions from public, anon, authenticated;
grant select on public.gs_item_conditions to rms_api;
revoke insert, update, delete, truncate on public.gs_item_conditions from rms_api;
