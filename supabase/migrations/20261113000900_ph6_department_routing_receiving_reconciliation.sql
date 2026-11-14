-- Change plan 2026-11-12 · Phase 6 — Department Routing & Receiving with Reconciliation
-- (docs/RMS_MASTER_PLAN_ADDENDUM_2026-11.md AMD-10, AMD-14, AMD-15; G-20; DEC-42; DEC-43).
--
-- 1. Number series for Department Routing Documents ('DEPT_ROUTING', prefix 'DIN')
--    and Department Receipt Notes ('DEPT_RECEIPT', prefix 'DRN').
-- 2. department_outcome_heads: configurable outcome heads for department returns
--    (Repaired, Not Repaired, Cleaned, Wastage, Send to Mercury Extraction, Return to RM).
-- 3. department_routings & department_routing_lines: tracking goods sent by RM to departments.
-- 4. department_receipts & department_receipt_lines: tracking goods received back per line into outcome heads.
-- 5. Guard G-20: Quantity conservation across store, departments, outcome heads and actions:
--      counted_qty = in_store + at_departments + outcome_heads + actioned
-- 6. Notifications & permissions for department routing and receiving.

-- ===========================================================================
-- 1. Number Series
-- ===========================================================================
insert into public.number_series (code, name, prefix, pattern, reset_policy, fy_start_month, fy_format)
values
  ('DEPT_ROUTING', 'Department Issue Note',   'DIN', '{PREFIX}/{FY}/{SEQ:5}', 'YEARLY_FY', 4, 'LONG'),
  ('DEPT_RECEIPT', 'Department Receipt Note', 'DRN', '{PREFIX}/{FY}/{SEQ:5}', 'YEARLY_FY', 4, 'LONG')
on conflict (code) do nothing;

-- ===========================================================================
-- 2. Department Outcome Heads (DEC-43)
-- ===========================================================================
create table public.department_outcome_heads (
  id                  uuid primary key default gen_random_uuid(),
  code                text not null unique check (code ~ '^[A-Z][A-Z0-9_]*$'),
  label               text not null check (btrim(label) <> ''),
  description         text,
  is_wastage          boolean not null default false,
  returns_to_routing  boolean not null default false,
  is_active           boolean not null default true,
  sort_order          integer not null default 0,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

comment on table public.department_outcome_heads is
  'AMD-14/DEC-43: Configurable outcome heads for department returns (Repaired, Wastage, Re-route, etc.).';

insert into public.department_outcome_heads (code, label, description, is_wastage, returns_to_routing, sort_order)
values
  ('REPAIRED',                    'Repaired',                    'Item repaired successfully; ready for RM action',                     false, false, 10),
  ('NOT_REPAIRED',                'Not Repaired',                'Item could not be repaired; returned as-is',                           false, false, 20),
  ('CLEANED',                     'Cleaned / Calibrated',        'Item cleaned or calibrated; ready for RM action',                     false, false, 30),
  ('WASTAGE',                     'Wastage',                     'Item damaged beyond repair / scrap; condemned to wastage',             true,  false, 40),
  ('SEND_TO_MERCURY_EXTRACTION',  'Send to Mercury Extraction',  'Mercury extraction required before further handling',                 false, true,  50),
  ('RE_ROUTE',                    'Return to RM Routing Queue',  'Returned for re-evaluation and re-routing by Replacement Manager',     false, true,  60)
on conflict (code) do nothing;

-- ===========================================================================
-- 3. Department Routings (Issue Notes) & Lines
-- ===========================================================================
create table public.department_routings (
  id                    uuid primary key default gen_random_uuid(),
  routing_no            text not null unique,
  gs_id                 uuid not null references public.goods_slips (id) on delete restrict,
  department_field_id   uuid not null references public.item_field_library (id) on delete restrict,
  department_code       text not null,
  department_label      text not null,
  status                text not null default 'DISPATCHED'
                        check (status in ('DISPATCHED', 'PARTIALLY_RECEIVED', 'COMPLETED', 'CANCELLED')),
  dispatched_at         timestamptz not null default now(),
  dispatched_by         uuid default rms_private.current_actor() references public.profiles (id) on delete set null,
  notes                 text,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

create index dept_routings_gs_idx on public.department_routings (gs_id);
create index dept_routings_status_idx on public.department_routings (status);
create index dept_routings_dept_idx on public.department_routings (department_field_id);

comment on table public.department_routings is
  'AMD-14: Department routing document (Department Issue Note) dispatching items to a department.';

create table public.department_routing_lines (
  id                      uuid primary key default gen_random_uuid(),
  routing_id              uuid not null references public.department_routings (id) on delete cascade,
  gs_item_id              uuid not null references public.gs_items (id) on delete restrict,
  source_bucket_field_id  uuid references public.item_field_library (id) on delete set null,
  lot_id                  uuid references public.stock_lots (id) on delete restrict,
  qty_sent                integer not null check (qty_sent > 0),
  qty_received            integer not null default 0 check (qty_received >= 0),
  notes                   text,
  created_at              timestamptz not null default now(),
  constraint dept_routing_lines_qty_check check (qty_received <= qty_sent)
);

create index dept_routing_lines_routing_idx on public.department_routing_lines (routing_id);
create index dept_routing_lines_item_idx on public.department_routing_lines (gs_item_id);

comment on table public.department_routing_lines is
  'AMD-14: Line items on a Department Issue Note with quantity sent and received.';

-- ===========================================================================
-- 4. Department Receipts & Lines
-- ===========================================================================
create table public.department_receipts (
  id                    uuid primary key default gen_random_uuid(),
  receipt_no            text not null unique,
  routing_id            uuid not null references public.department_routings (id) on delete restrict,
  received_by           uuid default rms_private.current_actor() references public.profiles (id) on delete set null,
  received_at           timestamptz not null default now(),
  remarks               text,
  created_at            timestamptz not null default now()
);

create index dept_receipts_routing_idx on public.department_receipts (routing_id);

comment on table public.department_receipts is
  'AMD-14: Department Receipt Note acknowledging return of items from a department.';

create table public.department_receipt_lines (
  id                    uuid primary key default gen_random_uuid(),
  receipt_id            uuid not null references public.department_receipts (id) on delete cascade,
  routing_line_id       uuid not null references public.department_routing_lines (id) on delete restrict,
  outcome_head_id       uuid not null references public.department_outcome_heads (id) on delete restrict,
  outcome_code          text not null,
  outcome_label         text not null,
  is_wastage            boolean not null default false,
  returns_to_routing    boolean not null default false,
  quantity              integer not null check (quantity > 0),
  remarks               text,
  created_at            timestamptz not null default now()
);

create index dept_receipt_lines_receipt_idx on public.department_receipt_lines (receipt_id);
create index dept_receipt_lines_routing_line_idx on public.department_receipt_lines (routing_line_id);

comment on table public.department_receipt_lines is
  'AMD-14/DEC-43: Breakdown of received quantity into outcome heads (repaired, wastage, re-route).';

-- ===========================================================================
-- 5. Trigger: Auto-update qty_received and routing status on receipt
-- ===========================================================================
create or replace function rms_private.on_dept_receipt_line_inserted()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_routing_id          uuid;
  v_unreceived_count    integer;
begin
  -- Update qty_received on the routing line
  update public.department_routing_lines
     set qty_received = qty_received + new.quantity
   where id = new.routing_line_id
  returning routing_id into v_routing_id;

  -- Check if any lines remain incomplete
  select count(*)
    into v_unreceived_count
    from public.department_routing_lines
   where routing_id = v_routing_id
     and qty_received < qty_sent;

  if v_unreceived_count = 0 then
    update public.department_routings
       set status = 'COMPLETED', updated_at = now()
     where id = v_routing_id;
  else
    update public.department_routings
       set status = 'PARTIALLY_RECEIVED', updated_at = now()
     where id = v_routing_id;
  end if;

  return new;
end;
$$;

create trigger trg_dept_receipt_line_inserted
after insert on public.department_receipt_lines
for each row execute function rms_private.on_dept_receipt_line_inserted();

-- ===========================================================================
-- 6. Guard G-20: Quantity Conservation across Store, Departments, Outcomes & Actions
-- ===========================================================================
-- Invariant per item line:
--   counted_qty = in_store + at_departments + outcome_heads + actioned
-- where:
--   counted_qty    = gs_items.received_qty
--   at_departments = sum(rl.qty_sent - rl.qty_received) for active routings
--   outcome_heads  = sum(rc.quantity) filter (where not rc.returns_to_routing)
--   actioned       = sum(act.quantity) from rm_item_actions (where is_current)
--   in_store       = counted_qty - at_departments - outcome_heads - actioned (must be >= 0)

create or replace function rms_private.validate_department_reconciliation(p_gs_id uuid)
returns void
language plpgsql
set search_path = ''
as $$
declare
  v_item record;
  v_at_dept integer;
  v_outcomes integer;
  v_actioned integer;
  v_in_store integer;
begin
  for v_item in
    select id, line_no, coalesce(product_name_snapshot, 'Item') as item_name, received_qty
      from public.gs_items
     where gs_id = p_gs_id
     order by line_no asc
  loop
    -- 1. Quantity currently at departments
    select coalesce(sum(rl.qty_sent - rl.qty_received), 0)
      into v_at_dept
      from public.department_routing_lines rl
      join public.department_routings r on r.id = rl.routing_id
     where rl.gs_item_id = v_item.id
       and r.status in ('DISPATCHED', 'PARTIALLY_RECEIVED');

    -- 2. Quantity booked into terminal outcome heads (not returning to routing)
    select coalesce(sum(rcl.quantity), 0)
      into v_outcomes
      from public.department_receipt_lines rcl
      join public.department_routing_lines rl on rl.id = rcl.routing_line_id
     where rl.gs_item_id = v_item.id
       and not rcl.returns_to_routing;

    -- 3. Quantity already actioned by RM (if any action rows exist)
    select coalesce(sum(act.qty), 0)
      into v_actioned
      from public.rm_item_actions act
     where act.gs_item_id = v_item.id
       and act.is_current = true;

    -- 4. Calculate available in store
    v_in_store := v_item.received_qty - v_at_dept - v_outcomes - v_actioned;

    if v_in_store < 0 then
      raise exception 'G-20: Quantity conservation violation for item line % (%): counted (%) < at_departments (%) + outcome_heads (%) + actioned (%). Available store quantity cannot be negative (%)',
        v_item.line_no, v_item.item_name, v_item.received_qty, v_at_dept, v_outcomes, v_actioned, v_in_store
        using errcode = 'P0001';
    end if;

    if (v_in_store + v_at_dept + v_outcomes + v_actioned) != v_item.received_qty then
      raise exception 'G-20: Quantity conservation violation for item line % (%): sum of parts (% + % + % + %) != counted quantity (%)',
        v_item.line_no, v_item.item_name, v_in_store, v_at_dept, v_outcomes, v_actioned, v_item.received_qty
        using errcode = 'P0001';
    end if;
  end loop;
end;
$$;

-- Trigger on department_routing_lines
create or replace function rms_private.trg_dept_routing_lines_reconciliation()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_gs_id uuid;
begin
  select gs_id into v_gs_id
    from public.department_routings
   where id = coalesce(new.routing_id, old.routing_id);

  if v_gs_id is not null then
    perform rms_private.validate_department_reconciliation(v_gs_id);
  end if;

  return coalesce(new, old);
end;
$$;

create trigger trg_dept_routing_lines_g20
after insert or update on public.department_routing_lines
for each row execute function rms_private.trg_dept_routing_lines_reconciliation();

-- Trigger on department_receipt_lines
create or replace function rms_private.trg_dept_receipt_lines_reconciliation()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_gs_id uuid;
begin
  select r.gs_id into v_gs_id
    from public.department_routing_lines rl
    join public.department_routings r on r.id = rl.routing_id
   where rl.id = coalesce(new.routing_line_id, old.routing_line_id);

  if v_gs_id is not null then
    perform rms_private.validate_department_reconciliation(v_gs_id);
  end if;

  return coalesce(new, old);
end;
$$;

create trigger trg_dept_receipt_lines_g20
after insert or update on public.department_receipt_lines
for each row execute function rms_private.trg_dept_receipt_lines_reconciliation();

-- ===========================================================================
-- 7. Update System Guard Events to accept G-20
-- ===========================================================================
alter table public.system_guard_events
  drop constraint if exists system_guard_events_guard_code_check;

alter table public.system_guard_events
  add constraint system_guard_events_guard_code_check
  check (guard_code ~ '^G-(0[1-9]|1[0-9]|20)$');

-- ===========================================================================
-- 8. Notifications, Permissions and Settings
-- ===========================================================================
insert into public.notification_event_types (code, label, category, description)
values
  ('DEPT_ROUTING_DISPATCHED', 'Department Routing Dispatched', 'WORKFLOW', 'Goods dispatched to a department for repair/processing'),
  ('DEPT_ROUTING_RECEIVED',   'Department Return Received',    'WORKFLOW', 'Goods received back from department into outcome heads'),
  ('DEPT_ROUTING_COMPLETED',  'Department Routing Completed',  'WORKFLOW', 'Department routing completely received')
on conflict (code) do nothing;

insert into public.notification_templates (event_type, channel, version_no, subject, body, status)
values
  ('DEPT_ROUTING_DISPATCHED', 'EMAIL', 1,
   'Routing {{ routing_no }}: {{ department_label }}',
   'Goods Slip {{ gs_no }} has dispatched {{ total_qty }} items to {{ department_label }}.',
   'PUBLISHED'),
  ('DEPT_ROUTING_RECEIVED', 'EMAIL', 1,
   'Receipt {{ receipt_no }}: {{ department_label }}',
   '{{ total_qty }} items received from {{ department_label }} under Goods Slip {{ gs_no }}.',
   'PUBLISHED')
on conflict (event_type, channel, version_no) do nothing;

-- Permissions
insert into public.permissions (module_code, action, description)
values
  ('department_routing', 'view',   'View department routings and reconciliation state'),
  ('department_routing', 'create', 'Dispatch items to departments (RM)'),
  ('department_routing', 'edit',   'Receive items back from departments and book outcome heads'),
  ('department_routing', 'export', 'Export department routing reports')
on conflict (module_code, action) do nothing;

-- Role Grants
insert into public.role_permissions (role_id, permission_id, scope)
select r.id, p.id, 'all'
from public.roles r
cross join public.permissions p
where p.module_code = 'department_routing'
  and (
    (r.code = 'REPLACEMENT_MANAGER' and p.action in ('view', 'create', 'export')) or
    (r.code = 'INWARD_VERIFIER' and p.action in ('view', 'edit')) or
    (r.code = 'INTERMEDIATE_STORE_MANAGER' and p.action in ('view')) or
    (r.code = 'SUPER_ADMIN')
  )
on conflict (role_id, permission_id) do nothing;

-- Setting for department receiver role (DEC-42)
insert into public.system_settings (key, value, description)
values (
  'department.receiving_role',
  '"INWARD_VERIFIER"'::jsonb,
  'DEC-42: Role designated to receive goods back from departments into outcome heads.'
)
on conflict (key) do nothing;

-- ===========================================================================
-- 9. Audit Triggers and RLS
-- ===========================================================================
create trigger audit_row
  after insert or update or delete on public.department_outcome_heads
  for each row execute function rms_private.audit_row();

create trigger audit_row
  after insert or update or delete on public.department_routings
  for each row execute function rms_private.audit_row();

create trigger audit_row
  after insert or update or delete on public.department_routing_lines
  for each row execute function rms_private.audit_row();

create trigger audit_row
  after insert or update or delete on public.department_receipts
  for each row execute function rms_private.audit_row();

create trigger audit_row
  after insert or update or delete on public.department_receipt_lines
  for each row execute function rms_private.audit_row();

create trigger set_updated_at
  before update on public.department_outcome_heads
  for each row execute function rms_private.set_updated_at();

create trigger set_updated_at
  before update on public.department_routings
  for each row execute function rms_private.set_updated_at();

alter table public.department_outcome_heads enable row level security;
alter table public.department_routings enable row level security;
alter table public.department_routing_lines enable row level security;
alter table public.department_receipts enable row level security;
alter table public.department_receipt_lines enable row level security;

create policy dept_outcome_heads_api_all on public.department_outcome_heads
  for all to rms_api using (true) with check (true);

create policy dept_routings_api_all on public.department_routings
  for all to rms_api using (true) with check (true);

create policy dept_routing_lines_api_all on public.department_routing_lines
  for all to rms_api using (true) with check (true);

create policy dept_receipts_api_all on public.department_receipts
  for all to rms_api using (true) with check (true);

create policy dept_receipt_lines_api_all on public.department_receipt_lines
  for all to rms_api using (true) with check (true);

-- Revoke default public execute on private schema functions
revoke all on function rms_private.on_dept_receipt_line_inserted() from public, anon, authenticated;
grant execute on function rms_private.on_dept_receipt_line_inserted() to rms_api;

revoke all on function rms_private.validate_department_reconciliation(uuid) from public, anon, authenticated;
grant execute on function rms_private.validate_department_reconciliation(uuid) to rms_api;

revoke all on function rms_private.trg_dept_routing_lines_reconciliation() from public, anon, authenticated;
grant execute on function rms_private.trg_dept_routing_lines_reconciliation() to rms_api;

revoke all on function rms_private.trg_dept_receipt_lines_reconciliation() from public, anon, authenticated;
grant execute on function rms_private.trg_dept_receipt_lines_reconciliation() to rms_api;
