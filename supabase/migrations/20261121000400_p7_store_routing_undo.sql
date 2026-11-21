-- =============================================================================================
-- Phase P7 follow-up (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-67, Q32 (user 2026-11-21).
-- A store user may undo an "Issue to Store" (NO_WORK) line of its own store until that piece is
-- analysed (P9). Issued lines (pieces at a department) come back through receiving (P8).
--
-- 1. Plan-line update guard (full body: 20261118000100 G2 body + the DEC-67 branch):
--    NO_WORK → CANCELLED of a store line by store_routing.create + a user of that store, GS in a
--    store-routing status, not finalised (G-21), no current final action on the item (the analysis
--    of P9 must add its own "already analysed" check here).
-- 2. rms_private.gs_routing_started: a store routing keeps the DEC-64 edit window closed even when
--    all its lines are undone (the GS is STORE_PROCESSING and its slips cannot be voided any more).
-- =============================================================================================

create or replace function rms_private.department_plan_lines_update_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_status  text;
  v_rl      record;
  v_actor   uuid := rms_private.current_actor();
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

  if new.status = 'CANCELLED' and old.store_id is not null then
    -- DEC-67 / Q32: a store undoes its own "Issue to Store" line until the piece is analysed.
    if old.status <> 'NO_WORK' then
      raise exception 'DEC-67: only an "Issue to Store" line is undone; issued pieces come back through receiving'
        using errcode = '23514';
    end if;
    select status into v_status from public.goods_slips where id = old.gs_id for update;
    if not rms_private.gs_store_routing_status_ok(v_status) then
      raise exception 'DEC-67: the routing of this goods slip can no longer be undone (status %)', v_status
        using errcode = '23514';
    end if;
    if not rms_private.user_holds_permission(v_actor, 'store_routing', 'create')
       or not rms_private.user_acts_for_store(v_actor, old.store_id) then
      raise exception 'DEC-67: only a user of the Intermediate Store undoes its routing' using errcode = '42501';
    end if;
    if exists (select 1 from public.ac_action_slips s where s.gs_id = old.gs_id and s.status = 'CURRENT')
       or exists (select 1 from public.rm_item_actions a where a.gs_item_id = old.gs_item_id and a.is_current) then
      raise exception 'G-21: the item is analysed; its routing can no longer be undone' using errcode = 'P0001';
    end if;
    if new.cancelled_at is null or length(btrim(coalesce(new.cancel_reason, ''))) < 3 then
      raise exception 'DEC-67: undoing a routing line needs a reason' using errcode = '23514';
    end if;
    new.cancelled_by := v_actor;
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

-- DEC-64 d + Q32: any store routing (even undone) keeps the edit window closed.
create or replace function rms_private.gs_routing_started(p_gs_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (select 1 from public.department_routing_plan_lines l
                  where l.gs_id = p_gs_id and (l.status <> 'CANCELLED' or l.store_id is not null))
      or exists (select 1 from public.department_routings r
                  where r.gs_id = p_gs_id and r.status <> 'CANCELLED')
$$;
revoke all on function rms_private.gs_routing_started(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_routing_started(uuid) to rms_api;
