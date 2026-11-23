-- Release 2026-11-21 - Phase P8 (DEC-68 PROVISIONAL): each Intermediate Store receives back the
-- goods it sent to departments (sent vs received qty, outcome, condition after work, partial
-- receipts). The pieces return to that store's location, or to scrap / the Non-Functional Store
-- per outcome. The Replacement Executive's legacy "Department Receiving" menu is hidden once no
-- legacy routing is still at a department.
--
-- Apply to production AFTER migration 20261121000500_p8_store_receiving.sql and after deploying the
-- P8 backend + frontend. Idempotent; safe to re-run:
--   psql "<admin url>" -X -v ON_ERROR_STOP=1 -f supabase/snippets/release_20261121_p8_store_receiving.sql
-- Same configuration as supabase/seed.sql (phase prompts §0 rule 3).
begin;

-- 1. Grants. Every Intermediate Store role (stores added in the Admin Panel have their own role)
--    receives its goods back (store_routing edit).
insert into public.role_permissions (role_id, permission_id, scope)
select s.role_id, p.id, 'all'
  from public.intermediate_stores s
  join public.permissions p on p.module_code = 'store_routing' and p.action = 'edit'
on conflict (role_id, permission_id) do nothing;

-- 2. Menu: "Receive from Departments" for every store role.
insert into public.role_journey_steps (role_id, journey_step_id, sort_order)
select st.role_id, js.id, 30
  from public.intermediate_stores st
  join public.journey_steps js on js.code = 'STORE_DEPT_RECEIVING'
on conflict (role_id, journey_step_id) do nothing;

-- 3. The outcome that sends pieces back to routing now returns them to the store's routing
--    (label only; code RE_ROUTE unchanged, G-18). An admin's own relabel is kept.
update public.department_outcome_heads
   set label = 'Return for Re-routing',
       description = 'Returned to the store for re-evaluation and routing again'
 where code = 'RE_ROUTE' and label = 'Return to RM Routing Queue';

-- 4. Legacy "Department Receiving" (Replacement Executive): hidden once no legacy routing (issued
--    from the old Intermediate Store) is still at a department; otherwise kept and reported.
do $$
declare
  v_legacy integer;
  v_store  integer;
begin
  select count(*) into v_legacy from public.department_routings
   where status in ('DISPATCHED', 'PARTIALLY_RECEIVED') and store_id is null;
  select count(*) into v_store from public.department_routings
   where status in ('DISPATCHED', 'PARTIALLY_RECEIVED') and store_id is not null;
  if v_legacy = 0 then
    update public.journey_steps set is_active = false where code = 'DEPT_RECEIVING' and is_active;
    raise notice 'DEC-68: legacy DEPT_RECEIVING menu hidden; % store DIN(s) waiting at departments', v_store;
  else
    raise notice 'DEC-68: DEPT_RECEIVING kept: % legacy routing(s) still at departments; re-run when 0 (% store DIN(s) waiting)',
      v_legacy, v_store;
  end if;
end
$$;

commit;
