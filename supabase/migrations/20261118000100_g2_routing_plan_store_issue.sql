-- Gap plan 2026-11-17 · Phase G2 — RM routing plan + Store issue
-- (docs/RMS_GAP_PLAN_2026-11-17.md G2; DEC-55; Q3–Q6, Q15, Q16; T4; Guard G-20, G-21).
--
-- Workflow step 7 changes from "RM clicks → stock moves to one shared Technician Bench" to:
--   RM plans the routing per item + condition bucket (no stock move)
--     → Intermediate Store Manager is alerted
--     → Store Manager issues the planned lines (prints the DIN): stock INTERMEDIATE_STORE →
--       the department's own location through rms_move_stock.
--   STORE ("no work") lines need no issue: the pieces stay in the Intermediate Store and are ready
--   for Final Actions.
--
-- 1. Departments (config, item_field_library DEPARTMENT): add STORE, relabel REPAIR →
--    "Technician / Repair", deactivate TECHNICAL_INSPECTION (Q15, kept in history), and enable the
--    active departments for every category that has no DEPARTMENT assignment yet (admin may
--    restrict). New categories get the same default (trigger). Shared function, re-run by seed.sql
--    because categories are seed data on a fresh reset.
-- 2. Locations DEPT_CLEANING / DEPT_TECHNICIAN_REPAIR / DEPT_MERCURY_EXTRACTION (Q16). The
--    Technician Bench stays for older routings. Repeated in seed.sql (roles are seed data).
-- 3. Settings: department.location_by_code (department code → location code) and
--    department.no_work_codes (["STORE"]). Configuration only; the guards below never read a
--    setting that could switch them off.
-- 4. department_routing_plan_lines: the RM plan. Status PLANNED → ISSUED | CANCELLED, or
--    NO_WORK → CANCELLED. Insert / transition guards in the DB (G-20 / DEC-55).
-- 5. department_routings.location_id: the department location the stock went to (NULL = legacy
--    Technician Bench). New routings need it and must not target a no-work department.
-- 6. DEC-55 in the DB: every NEW routing line must be the issue of a PLANNED plan line (deferred
--    check at commit), so the RM can no longer move stock to a department directly.
-- 7. G-20 extended: planned-not-yet-issued pieces are still in the store and can never exceed it.
--    G-21 finalise: nothing may be planned-not-yet-issued.
-- 8. Permission department_routing.approve = Store issue (INTERMEDIATE_STORE_MANAGER, grant in
--    seed.sql), notification DEPT_ROUTING_PLANNED → Store Manager, journey step DEPT_ISSUE.
-- Messages carry "G-20" / "G-21" so the API maps them to the standard 409 guard envelope.

-- ===========================================================================
-- 1. Departments
-- ===========================================================================
insert into public.item_field_library (field_group, code, label, description, sort_order, is_system, source_ref)
values ('DEPARTMENT', 'STORE', 'Store (no work)',
        'No work needed: the pieces stay in the Intermediate Store and go straight to Final Actions (DEC-55 Q4).',
        5, true, 'DEC-55')
on conflict (field_group, code) do nothing;

update public.item_field_library
   set label = 'Technician / Repair'
 where field_group = 'DEPARTMENT' and code = 'REPAIR' and label = 'Repair';

update public.item_field_library
   set is_active = false
 where field_group = 'DEPARTMENT' and code = 'TECHNICAL_INSPECTION' and is_active;

-- DEC-55: departments are enabled for all categories by default. A category that already has any
-- DEPARTMENT assignment was configured by an admin and is left alone. Idempotent.
create or replace function rms_private.enable_departments_for_categories(p_category_id uuid default null)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_count integer;
begin
  insert into public.item_field_assignments
    (field_id, field_group, scope_type, category_id, is_included, sort_order)
  select l.id, 'DEPARTMENT', 'CATEGORY', c.id, true, l.sort_order
    from public.product_categories c
    cross join public.item_field_library l
   where l.field_group = 'DEPARTMENT'
     and l.is_active
     and (p_category_id is null or c.id = p_category_id)
     and not exists (
       select 1 from public.item_field_assignments a
        where a.field_group = 'DEPARTMENT' and a.scope_type = 'CATEGORY' and a.category_id = c.id
     )
  on conflict do nothing;
  get diagnostics v_count = row_count;
  return v_count;
end;
$$;
revoke all on function rms_private.enable_departments_for_categories(uuid) from public, anon, authenticated;
comment on function rms_private.enable_departments_for_categories(uuid) is
  'DEC-55: enable every active DEPARTMENT for categories without a DEPARTMENT assignment (default; admin may restrict).';

select rms_private.enable_departments_for_categories();

create or replace function rms_private.product_categories_default_departments()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  perform rms_private.enable_departments_for_categories(new.id);
  return null;
end;
$$;
revoke all on function rms_private.product_categories_default_departments() from public, anon, authenticated;

drop trigger if exists product_categories_default_departments on public.product_categories;
create trigger product_categories_default_departments
  after insert on public.product_categories
  for each row execute function rms_private.product_categories_default_departments();

-- ===========================================================================
-- 2. Department locations (Q16). Custodian: the Store Manager issues into them; the receiving
--    role (DEC-42 setting) books them back.
-- ===========================================================================
insert into public.inventory_locations (code, name, location_class, custodian_role_id)
select v.code, v.name, 'TECHNICIAN', r.id
  from (values
    ('DEPT_CLEANING',            'Department: Cleaning'),
    ('DEPT_TECHNICIAN_REPAIR',   'Department: Technician / Repair'),
    ('DEPT_MERCURY_EXTRACTION',  'Department: Mercury Extraction')
  ) as v(code, name)
  left join public.roles r on r.code = 'INTERMEDIATE_STORE_MANAGER'
on conflict (code) do nothing;

-- ===========================================================================
-- 3. Settings
-- ===========================================================================
insert into public.system_settings (key, value, category, description, source_ref) values
  ('department.location_by_code',
   '{"CLEANING": "DEPT_CLEANING", "REPAIR": "DEPT_TECHNICIAN_REPAIR", "MERCURY_EXTRACTION": "DEPT_MERCURY_EXTRACTION"}'::jsonb,
   'department',
   'Per DEPARTMENT code: the inventory location code that receives the pieces the Store Manager issues to that department (DEC-55 Q16). A department that needs work must be listed.',
   'DEC-55'),
  ('department.no_work_codes',
   '["STORE"]'::jsonb,
   'department',
   'DEPARTMENT codes that mean "no work needed": the pieces stay in the Intermediate Store, need no Store issue and go to Final Actions (DEC-55 Q4).',
   'DEC-55')
on conflict (key) do nothing;

-- Is this department code a "no work" department? (configuration; a missing / broken setting
-- means "none", so a work department can never silently skip the Store issue)
create or replace function rms_private.department_is_no_work(p_code text)
returns boolean
language sql
stable
set search_path = ''
as $$
  select coalesce((
    select jsonb_typeof(s.value) = 'array' and s.value ? p_code
      from public.system_settings s
     where s.key = 'department.no_work_codes'
  ), false);
$$;
revoke all on function rms_private.department_is_no_work(text) from public, anon, authenticated;
grant execute on function rms_private.department_is_no_work(text) to rms_api;

-- ===========================================================================
-- 4. Routing plan lines
-- ===========================================================================
create table public.department_routing_plan_lines (
  id                      uuid primary key default gen_random_uuid(),
  gs_id                   uuid not null references public.goods_slips (id) on delete restrict,
  gs_item_id              uuid not null references public.gs_items (id) on delete restrict,
  source_bucket_field_id  uuid references public.item_field_library (id) on delete restrict,
  source_bucket_label     text,
  department_field_id     uuid not null references public.item_field_library (id) on delete restrict,
  department_code         text not null,
  department_label        text not null,
  is_no_work              boolean not null default false,
  qty                     integer not null check (qty > 0),
  status                  text not null default 'PLANNED'
                          check (status in ('PLANNED', 'ISSUED', 'NO_WORK', 'CANCELLED')),
  notes                   text,
  planned_by              uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  planned_at              timestamptz not null default now(),
  routing_id              uuid references public.department_routings (id) on delete restrict,
  routing_line_id         uuid unique references public.department_routing_lines (id) on delete restrict,
  issued_by               uuid references public.profiles (id) on delete restrict,
  issued_at               timestamptz,
  cancelled_by            uuid references public.profiles (id) on delete restrict,
  cancelled_at            timestamptz,
  cancel_reason           text,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now(),
  constraint dept_plan_lines_status_kind_check check (
    (is_no_work and status in ('NO_WORK', 'CANCELLED'))
    or (not is_no_work and status in ('PLANNED', 'ISSUED', 'CANCELLED'))),
  constraint dept_plan_lines_issue_check check (
    (status = 'ISSUED') = (routing_line_id is not null and routing_id is not null and issued_at is not null)),
  constraint dept_plan_lines_cancel_check check (
    (status = 'CANCELLED') = (cancelled_at is not null and cancel_reason is not null and btrim(cancel_reason) <> ''))
);

create index dept_plan_lines_gs_idx on public.department_routing_plan_lines (gs_id);
create index dept_plan_lines_item_idx on public.department_routing_plan_lines (gs_item_id);
create index dept_plan_lines_status_idx on public.department_routing_plan_lines (status)
  where status = 'PLANNED';

comment on table public.department_routing_plan_lines is
  'DEC-55: RM routing plan per item + condition bucket. PLANNED lines are issued by the Store Manager (DIN, stock move); NO_WORK (STORE) lines stay in the Intermediate Store.';

-- 4a. Insert guard: GS held, not finalised, item of the GS, bucket of the item, department active
--     and allowed by the product's resolved profile. Snapshots and status come from the DB.
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

  if new.source_bucket_field_id is not null then
    select b.label_snapshot into v_bucket
      from public.gs_item_buckets b
     where b.gs_item_id = new.gs_item_id and b.field_id = new.source_bucket_field_id;
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

create trigger trg_dept_plan_lines_insert_guard
  before insert on public.department_routing_plan_lines
  for each row execute function rms_private.department_plan_lines_insert_guard();

-- 4b. Update guard: only PLANNED → ISSUED (with a matching routing line), PLANNED / NO_WORK →
--     CANCELLED (GS held, not finalised). Everything else is immutable.
create or replace function rms_private.department_plan_lines_update_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_status  text;
  v_rl      record;
begin
  if new.gs_id is distinct from old.gs_id
     or new.gs_item_id is distinct from old.gs_item_id
     or new.source_bucket_field_id is distinct from old.source_bucket_field_id
     or new.source_bucket_label is distinct from old.source_bucket_label
     or new.department_field_id is distinct from old.department_field_id
     or new.department_code is distinct from old.department_code
     or new.department_label is distinct from old.department_label
     or new.is_no_work is distinct from old.is_no_work
     or new.qty is distinct from old.qty
     or new.planned_by is distinct from old.planned_by
     or new.planned_at is distinct from old.planned_at then
    raise exception 'G-20: a routing plan line cannot be changed; cancel it and plan again'
      using errcode = 'P0001';
  end if;

  if new.status = old.status then
    if new.routing_id is distinct from old.routing_id
       or new.routing_line_id is distinct from old.routing_line_id
       or new.issued_by is distinct from old.issued_by
       or new.issued_at is distinct from old.issued_at
       or new.cancelled_by is distinct from old.cancelled_by
       or new.cancelled_at is distinct from old.cancelled_at
       or new.cancel_reason is distinct from old.cancel_reason then
      raise exception 'G-20: routing plan line % is %; it cannot be changed', old.id, old.status
        using errcode = 'P0001';
    end if;
    return new;
  end if;

  if old.status = 'PLANNED' and new.status = 'ISSUED' then
    select rl.gs_item_id, rl.qty_sent, r.gs_id, r.department_field_id, rl.routing_id into v_rl
      from public.department_routing_lines rl
      join public.department_routings r on r.id = rl.routing_id
     where rl.id = new.routing_line_id;
    if not found
       or v_rl.routing_id is distinct from new.routing_id
       or v_rl.gs_item_id <> old.gs_item_id
       or v_rl.qty_sent <> old.qty
       or v_rl.gs_id <> old.gs_id
       or v_rl.department_field_id <> old.department_field_id then
      raise exception 'G-20: issued routing line does not match plan line % (item, qty, department)', old.id
        using errcode = 'P0001';
    end if;
    return new;
  end if;

  if old.status in ('PLANNED', 'NO_WORK') and new.status = 'CANCELLED' then
    select status into v_status from public.goods_slips where id = old.gs_id for update;
    if v_status is distinct from 'HELD_AT_INTERMEDIATE_STORE' then
      raise exception 'G-20: routing plan lines change only while the goods slip is held (status %)', v_status
        using errcode = 'P0001';
    end if;
    if exists (select 1 from public.ac_action_slips s where s.gs_id = old.gs_id and s.status = 'CURRENT') then
      raise exception 'G-21: final actions of this goods slip are finalised; revise them before changing the routing plan'
        using errcode = 'P0001';
    end if;
    return new;
  end if;

  raise exception 'G-20: routing plan line cannot go from % to %', old.status, new.status
    using errcode = 'P0001';
end;
$$;
revoke all on function rms_private.department_plan_lines_update_guard() from public, anon, authenticated;

create trigger trg_dept_plan_lines_update_guard
  before update on public.department_routing_plan_lines
  for each row execute function rms_private.department_plan_lines_update_guard();

-- 4c. G-20 after every plan write (serialised per GS, like routing / receipt lines).
create or replace function rms_private.trg_dept_plan_lines_reconciliation()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  perform 1 from public.goods_slips where id = new.gs_id for update;
  perform rms_private.validate_department_reconciliation(new.gs_id);
  return new;
end;
$$;
revoke all on function rms_private.trg_dept_plan_lines_reconciliation() from public, anon, authenticated;

create trigger trg_dept_plan_lines_g20
  after insert or update on public.department_routing_plan_lines
  for each row execute function rms_private.trg_dept_plan_lines_reconciliation();

-- ===========================================================================
-- 5. Routing header: department location; never to a no-work department
-- ===========================================================================
alter table public.department_routings
  add column location_id uuid references public.inventory_locations (id) on delete restrict;

comment on column public.department_routings.location_id is
  'DEC-55: department location the Store issue moved the stock to. NULL = routing made before G2 (Technician Bench).';

create or replace function rms_private.department_routings_insert_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_status text;
  v_dept   record;
begin
  -- Lock the GS so its status cannot change under this issue (G-20 serialisation).
  select status into v_status from public.goods_slips where id = new.gs_id for update;
  if v_status is distinct from 'HELD_AT_INTERMEDIATE_STORE' then
    raise exception 'G-20: department routing needs the goods slip held at the intermediate store (current status: %)',
      coalesce(v_status, 'missing')
      using errcode = 'P0001';
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

-- ===========================================================================
-- 6. DEC-55: a new routing line is always the Store issue of a PLANNED plan line (checked at
--    commit, after the plan line was marked ISSUED in the same transaction).
-- ===========================================================================
create or replace function rms_private.department_routing_lines_from_plan()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if not exists (
    select 1 from public.department_routing_plan_lines p
     where p.routing_line_id = new.id and p.status = 'ISSUED'
  ) then
    raise exception 'G-20: department routing line % has no issued routing plan line; the RM plans and the Store Manager issues (DEC-55)', new.id
      using errcode = 'P0001';
  end if;
  return null;
end;
$$;
revoke all on function rms_private.department_routing_lines_from_plan() from public, anon, authenticated;

create constraint trigger trg_dept_routing_lines_from_plan
  after insert on public.department_routing_lines
  deferrable initially deferred
  for each row execute function rms_private.department_routing_lines_from_plan();

-- The Store issue inserts the routing line first and then marks its plan line ISSUED (the plan
-- line needs the routing line id). Checked immediately, G-20 would see those pieces both "at the
-- department" and "still planned" in between. The routing-line G-20 check therefore runs at
-- commit (same function, same GS lock); plan lines and receipt lines stay immediate, and the
-- service validates again after every command.
drop trigger if exists trg_dept_routing_lines_g20 on public.department_routing_lines;
create constraint trigger trg_dept_routing_lines_g20
  after insert or update on public.department_routing_lines
  deferrable initially deferred
  for each row execute function rms_private.trg_dept_routing_lines_reconciliation();

-- ===========================================================================
-- 7. G-20 extended + G-21 finalise
-- ===========================================================================
-- Identity unchanged (counted = in_store + at_departments + outcome_heads + actioned).
-- New: pieces planned but not yet issued are part of in_store and can never exceed it.
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
  end loop;
end;
$$;
revoke all on function rms_private.validate_department_reconciliation(uuid) from public, anon, authenticated;
grant execute on function rms_private.validate_department_reconciliation(uuid) to rms_api;

-- G-21 finalise (p_complete): additionally nothing may wait for a Store issue (DEC-55).
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
-- 8. Permission, notification, journey step, audit, RLS, grants
-- ===========================================================================
insert into public.permissions (module_code, action, description)
values ('department_routing', 'approve', 'Issue planned goods to departments and print the DIN (Store Manager, DEC-55)')
on conflict (module_code, action) do nothing;
-- Role grants live in seed.sql (_seed_role_matrix): roles are seed data. Existing databases:
insert into public.role_permissions (role_id, permission_id, scope)
select r.id, p.id, 'all'
  from public.roles r
  join public.permissions p on p.module_code = 'department_routing' and p.action = 'approve'
 where r.code in ('INTERMEDIATE_STORE_MANAGER', 'SUPER_ADMIN')
on conflict (role_id, permission_id) do nothing;

insert into public.notification_event_types
  (code, label, description, category, default_priority, is_mandatory, source_ref, sort_order)
values
  ('DEPT_ROUTING_PLANNED', 'Department routing planned',
   'The Replacement Manager planned department routing; the Intermediate Store Manager issues the goods (DEC-55).',
   'WORKFLOW', 'NORMAL', false, 'DEC-55', 515)
on conflict (code) do nothing;

insert into public.notification_templates (event_type, channel, version_no, subject, body, change_reason)
select 'DEPT_ROUTING_PLANNED', 'EMAIL', 1,
       '[{app_name}] {title}',
       E'Hello {recipient_name},\n\n{title}\n\n{body}\n\nEvent: {event_label}\nPriority: {priority}\nOpen in RMS: {link}\n\n— {app_name} (automated message; manage email preferences in RMS)',
       'DEC-55 default'
 where not exists (
   select 1 from public.notification_templates
    where event_type = 'DEPT_ROUTING_PLANNED' and channel = 'EMAIL'
 );

-- The rule names a role, and roles are seed data: on a fresh reset seed.sql adds it; on an existing
-- database (roles present) it is added here.
insert into public.notification_rules
  (event_type, name, include_context_recipients, recipient_role_codes, channels, priority, is_active)
select 'DEPT_ROUTING_PLANNED', 'Store Manager: routing planned, issue the goods (DEC-55)', true,
       array['INTERMEDIATE_STORE_MANAGER'], array['IN_APP'], 'NORMAL', true
 where not exists (select 1 from public.notification_rules where event_type = 'DEPT_ROUTING_PLANNED')
   and exists (select 1 from public.roles where code = 'INTERMEDIATE_STORE_MANAGER');

-- Journey step: Store issue queue.
alter table public.journey_steps drop constraint if exists journey_steps_screen_key_check;
alter table public.journey_steps add constraint journey_steps_screen_key_check check (screen_key in (
  'journey-queue', 'gs-new', 'gs-list', 'dashboard', 'pendencies',
  'container-audit', 'reports', 'audit', 'custody', 'inventory', 'store-issues',
  'servicing', 'batteries', 'dismantling', 'scrap', 'credit-notes', 'approvals',
  'dispatch-queue', 'department-routing', 'department-receiving', 'department-issue',
  'accounts-entry', 'accounts-docs', 'dispatch-slips'));

alter table public.journey_steps drop constraint if exists journey_steps_item_screen_key_check;
alter table public.journey_steps add constraint journey_steps_item_screen_key_check check (
  item_screen_key is null or item_screen_key in (
    'gs-detail', 'gs-unboxing', 'gs-itemization', 'gs-inspection', 'gs-rm-review',
    'custody-transfer', 'gs-final-actions', 'department-receiving', 'department-issue',
    'accounts-entry-gs', 'accounts-docs', 'dispatch-slips',
    'gs-party-notification'));

alter table public.journey_steps drop constraint if exists journey_steps_queue_code_check;
alter table public.journey_steps add constraint journey_steps_queue_code_check check (
  queue_code is null or queue_code in (
    'CARTON_OPENING', 'COUNTING', 'CATEGORISATION', 'INSPECTION', 'RM_REVIEW', 'STORE_ACCEPT',
    'DEPT_ROUTING', 'DEPT_ISSUE', 'DEPT_RECEIVING', 'FINAL_ACTIONS', 'ACCOUNTS_DOCS',
    'ACCOUNTS_ENTRY', 'DISPATCH_SLIP', 'PARTY_EMAIL'));

insert into public.journey_steps
  (code, label, hint, kind, screen_key, item_screen_key, queue_code, feature_code,
   perm_module, perm_action, sort_order, source_ref)
values
  ('DEPT_ISSUE', 'Department Issue', 'Issue the planned goods to departments and print the DIN',
   'STEP', 'department-issue', 'department-issue', 'DEPT_ISSUE', null,
   'department_routing', 'approve', 75, 'DEC-55')
on conflict (code) do nothing;

update public.journey_steps
   set hint = 'Held in store: plan where each condition goes (Store / Cleaning / Technician / Mercury)'
 where code = 'DEPT_ROUTING' and hint = 'Held in store: send quantities to departments';

-- Existing databases (roles exist): the Store Manager's journey gets the issue step.
insert into public.role_journey_steps (role_id, journey_step_id, sort_order)
select r.id, s.id, 20
  from public.roles r, public.journey_steps s
 where r.code = 'INTERMEDIATE_STORE_MANAGER' and s.code = 'DEPT_ISSUE'
on conflict (role_id, journey_step_id) do nothing;

create trigger audit_row
  after insert or update or delete on public.department_routing_plan_lines
  for each row execute function rms_private.audit_row();

create trigger set_updated_at
  before update on public.department_routing_plan_lines
  for each row execute function rms_private.set_updated_at();

alter table public.department_routing_plan_lines enable row level security;
create policy dept_plan_lines_api_all on public.department_routing_plan_lines
  for all to rms_api using (true) with check (true);

-- Insert-only history apart from the guarded status transitions.
grant select, insert, update on public.department_routing_plan_lines to rms_api;
revoke delete, truncate on public.department_routing_plan_lines from rms_api;
