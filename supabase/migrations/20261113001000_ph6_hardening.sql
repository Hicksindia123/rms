-- Change plan 2026-11-12 · Phase 6 hardening (AMD-10, AMD-14, AMD-15; DEC-42, DEC-43; Guard G-20).
--
-- Fix-forward of 20261113000900 (never edit an applied migration, CLAUDE.md rule d):
--   1. G-20 concurrency: the reconciliation triggers lock the goods slip row before validating, so
--      two concurrent dispatches / receipts for the same GS are serialised and cannot both pass
--      the "in store >= 0" check on stale snapshots.
--   2. Integrity guards on insert (DB side of G-20; the service checks the same first):
--      - a routing is only created while the GS is HELD_AT_INTERMEDIATE_STORE, to an active
--        DEPARTMENT field;
--      - a routing line's item belongs to the routing's GS;
--      - a receipt only books against an open routing (DISPATCHED / PARTIALLY_RECEIVED);
--      - a receipt line's outcome code / label / is_wastage / returns_to_routing are snapshotted
--        from the active outcome head by the DB (never trusted from the client, G-18 style).
--   3. Insert-only history: receipts and receipt lines cannot be updated or deleted by the API
--      role; routing lines cannot be updated or deleted by it (qty_received is maintained only by
--      the SECURITY DEFINER receipt trigger); routings cannot be deleted. Deleting a receipt line
--      would otherwise silently break G-20 (qty_received would not be reversed).
-- Messages carry "G-20" so the API maps them to the standard 409 guard envelope.

-- ===========================================================================
-- 1. G-20 reconciliation triggers: serialise per goods slip
-- ===========================================================================
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
    -- G-20: serialise concurrent routing / receipt writes for the same GS (row lock held to commit).
    perform 1 from public.goods_slips where id = v_gs_id for update;
    perform rms_private.validate_department_reconciliation(v_gs_id);
  end if;

  return coalesce(new, old);
end;
$$;

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
    -- G-20: serialise concurrent routing / receipt writes for the same GS (row lock held to commit).
    perform 1 from public.goods_slips where id = v_gs_id for update;
    perform rms_private.validate_department_reconciliation(v_gs_id);
  end if;

  return coalesce(new, old);
end;
$$;

-- ===========================================================================
-- 2a. Routing header: GS must be held at the intermediate store; department must be active
-- ===========================================================================
create or replace function rms_private.department_routings_insert_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_status text;
  v_dept   record;
begin
  -- Lock the GS so its status cannot change under this dispatch (G-20 serialisation).
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

  -- Label snapshot comes from the library (G-18), not from the client.
  new.department_code  := v_dept.code;
  new.department_label := v_dept.label;
  return new;
end;
$$;

create trigger trg_dept_routings_insert_guard
before insert on public.department_routings
for each row execute function rms_private.department_routings_insert_guard();

-- ===========================================================================
-- 2b. Routing line: item must belong to the routing's GS
-- ===========================================================================
create or replace function rms_private.department_routing_lines_insert_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if not exists (
    select 1
      from public.department_routings r
      join public.gs_items gi on gi.gs_id = r.gs_id
     where r.id = new.routing_id and gi.id = new.gs_item_id
  ) then
    raise exception 'G-20: routing line item % does not belong to the routing''s goods slip', new.gs_item_id
      using errcode = 'P0001';
  end if;
  return new;
end;
$$;

create trigger trg_dept_routing_lines_insert_guard
before insert on public.department_routing_lines
for each row execute function rms_private.department_routing_lines_insert_guard();

-- ===========================================================================
-- 2c. Receipt header: routing must still be open
-- ===========================================================================
create or replace function rms_private.department_receipts_insert_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_status text;
begin
  select status into v_status from public.department_routings where id = new.routing_id for update;
  if v_status is null or v_status not in ('DISPATCHED', 'PARTIALLY_RECEIVED') then
    raise exception 'G-20: department receipt needs an open routing (current status: %)',
      coalesce(v_status, 'missing')
      using errcode = 'P0001';
  end if;
  return new;
end;
$$;

create trigger trg_dept_receipts_insert_guard
before insert on public.department_receipts
for each row execute function rms_private.department_receipts_insert_guard();

-- ===========================================================================
-- 2d. Receipt line: line belongs to the receipt's routing; outcome snapshot from the active head
-- ===========================================================================
create or replace function rms_private.department_receipt_lines_insert_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_head record;
begin
  if not exists (
    select 1
      from public.department_receipts rc
      join public.department_routing_lines rl on rl.routing_id = rc.routing_id
     where rc.id = new.receipt_id and rl.id = new.routing_line_id
  ) then
    raise exception 'G-20: receipt line % does not belong to the receipt''s routing', new.routing_line_id
      using errcode = 'P0001';
  end if;

  select code, label, is_wastage, returns_to_routing, is_active into v_head
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
  return new;
end;
$$;

create trigger trg_dept_receipt_lines_insert_guard
before insert on public.department_receipt_lines
for each row execute function rms_private.department_receipt_lines_insert_guard();

-- ===========================================================================
-- 3. Insert-only history for the API role
-- ===========================================================================
-- department_routings: status / updated_at change through the SECURITY DEFINER receipt trigger
-- and set_updated_at; UPDATE stays granted for a future documented cancel flow, DELETE does not.
revoke delete, truncate on public.department_routings from rms_api;
-- department_routing_lines: qty_received is maintained only by on_dept_receipt_line_inserted()
-- (SECURITY DEFINER), so the API role needs no UPDATE.
revoke update, delete, truncate on public.department_routing_lines from rms_api;
revoke update, delete, truncate on public.department_receipts from rms_api;
revoke update, delete, truncate on public.department_receipt_lines from rms_api;

-- ===========================================================================
-- 4. Missing v1 template: DEPT_ROUTING_COMPLETED is published by the service but 20261113000900
--    seeded templates only for DISPATCHED / RECEIVED (every event type has a published template).
-- ===========================================================================
insert into public.notification_templates (event_type, channel, version_no, subject, body, status)
values
  ('DEPT_ROUTING_COMPLETED', 'EMAIL', 1,
   'Routing {{ routing_no }} completed: {{ department_label }}',
   'All items of routing {{ routing_no }} ({{ department_label }}) under Goods Slip {{ gs_no }} have been received back.',
   'PUBLISHED')
on conflict (event_type, channel, version_no) do nothing;

-- ===========================================================================
-- 5. Function privileges (private schema)
-- ===========================================================================
revoke all on function rms_private.department_routings_insert_guard() from public, anon, authenticated;
revoke all on function rms_private.department_routing_lines_insert_guard() from public, anon, authenticated;
revoke all on function rms_private.department_receipts_insert_guard() from public, anon, authenticated;
revoke all on function rms_private.department_receipt_lines_insert_guard() from public, anon, authenticated;

comment on function rms_private.department_routings_insert_guard() is
  'G-20 / AMD-14: routing only while GS is HELD_AT_INTERMEDIATE_STORE, to an active DEPARTMENT field; label snapshot.';
comment on function rms_private.department_receipt_lines_insert_guard() is
  'G-20 / DEC-43: receipt line belongs to the receipt routing; outcome snapshot and flags from the active head.';
