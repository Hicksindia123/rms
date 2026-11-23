-- =============================================================================================
-- Phase P9 follow-up (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-69, user answers Q35 / Q36
-- (2026-11-23).
--
-- Q36: a store sends a goods slip for Management approval only AFTER it submitted its own
-- analysis of that goods slip (gs_store_analyses row of the requesting store).
-- Q35: a submitted analysis is never reopened by the store; only Management changes it (P10).
-- That is already enforced (gs_store_analyses is append-only; the rm_item_actions store branch
-- refuses a submitted store), so nothing changes for Q35.
--
-- Full body of the request guard (20261123000100 body + the Q36 check).
-- =============================================================================================
create or replace function rms_private.gs_management_approval_requests_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_status  text;
  v_store   text;
  v_actor   uuid := rms_private.current_actor();
begin
  if tg_op <> 'INSERT' then
    -- P10 (DEC-70) adds the Management resolution; until then requests are history.
    raise exception 'DEC-69: a Management approval request is resolved by Management (P10)' using errcode = '42501';
  end if;
  select status into v_status from public.goods_slips where id = new.gs_id for update;
  if v_status is null or v_status not in ('STORE_PROCESSING', 'ANALYSIS_COMPLETED') then
    raise exception 'DEC-69: a goods slip is sent for Management approval during or after the store analysis (current status: %)',
      coalesce(v_status, 'missing') using errcode = '23514';
  end if;
  select name into v_store from public.intermediate_stores where id = new.store_id;
  if not coalesce(rms_private.user_holds_permission(v_actor, 'store_analysis', 'create')
                  and rms_private.user_acts_for_store(v_actor, new.store_id), false) then
    raise exception 'DEC-69: only a user of an Intermediate Store on the goods slip sends it for Management approval'
      using errcode = '42501';
  end if;
  if not exists (select 1 from rms_private.gs_store_routing_progress(new.gs_id) p
                  where p.store_id = new.store_id) then
    raise exception 'DEC-69: % has no goods on this goods slip', coalesce(v_store, '?') using errcode = '23514';
  end if;
  -- Q36 (user 2026-11-23): the store submits its own analysis first.
  if not exists (select 1 from public.gs_store_analyses a
                  where a.gs_id = new.gs_id and a.store_id = new.store_id) then
    raise exception 'DEC-69 (Q36): % submits its own analysis of this goods slip before sending it for Management approval',
      coalesce(v_store, '?') using errcode = '23514';
  end if;
  new.status := 'OPEN';
  new.store_name_snapshot := v_store;
  new.reason := btrim(new.reason);
  new.requested_by := v_actor;
  new.requested_at := now();
  return new;
end
$$;
revoke all on function rms_private.gs_management_approval_requests_guard() from public, anon, authenticated;
