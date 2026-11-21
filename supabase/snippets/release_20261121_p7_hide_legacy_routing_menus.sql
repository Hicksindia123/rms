-- Release 2026-11-21 - Phase P7 follow-up (DEC-67, Q33 user 2026-11-21): hide the legacy menus
-- "Department Routing" (RM plan, DEPT_ROUTING) and "Department Issue" (Store Manager, DEPT_ISSUE)
-- once no legacy goods slip needs them. New goods slips are routed by the Intermediate Stores.
--
-- Apply to production AFTER release_20261121_p7_store_routing.sql. Idempotent; safe to re-run.
-- While any legacy goods slip is still held at the old Intermediate Store (or has a planned,
-- not issued line) the menus stay and the snippet only reports; run it again later.
--   psql "<admin url>" -X -v ON_ERROR_STOP=1 -f supabase/snippets/release_20261121_p7_hide_legacy_routing_menus.sql
begin;

do $$
declare
  v_held    integer;
  v_planned integer;
begin
  select count(*) into v_held from public.goods_slips where status = 'HELD_AT_INTERMEDIATE_STORE';
  select count(*) into v_planned from public.department_routing_plan_lines
   where status = 'PLANNED' and store_id is null;
  if v_held = 0 and v_planned = 0 then
    update public.journey_steps set is_active = false
     where code in ('DEPT_ROUTING', 'DEPT_ISSUE') and is_active;
    raise notice 'Q33: legacy DEPT_ROUTING / DEPT_ISSUE menus hidden (no legacy goods slip left)';
  else
    raise notice 'Q33: menus kept: % legacy goods slip(s) held, % planned legacy line(s); re-run when 0',
      v_held, v_planned;
  end if;
end
$$;

commit;
