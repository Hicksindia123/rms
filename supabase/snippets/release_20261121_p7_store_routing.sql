-- Release 2026-11-21 - Phase P7 (DEC-67; Q14 PROVISIONAL, Q29 / Q31 user): each Intermediate Store
-- routes its own acknowledged goods of a goods slip to departments. Saving the routing is the
-- issue (DIN printed, stock store → department). "Issue to Store" moves no stock.
--
-- Apply to production AFTER migration 20261121000300_p7_store_department_routing.sql and after
-- deploying the P7 backend + frontend. Idempotent; safe to re-run:
--   psql "<admin url>" -X -v ON_ERROR_STOP=1 -f supabase/snippets/release_20261121_p7_store_routing.sql
-- Same configuration as supabase/seed.sql (phase prompts §0 rule 3).
begin;

-- 1. Status label (GS_STATUS)
insert into public.option_items (option_set_id, code, label, allowed_status, rule_text, next_action_text,
                                 remarks, system_behavior, required_fields, sort_order, source_ref)
select os.id, 'STORE_PROCESSING', 'In Store Processing', 'YES', null, null, null, null,
       '[]'::jsonb, 74, 'DEC-67'
  from public.option_sets os
 where os.code = 'GS_STATUS'
on conflict (option_set_id, code) do nothing;

-- 2. Grants. Every Intermediate Store role (stores added in the Admin Panel have their own role)
--    routes its goods (store_routing view + create) and opens the DIN print / department legs
--    (department_routing view). Management and the RM follow the stores' progress (view only).
insert into public.role_permissions (role_id, permission_id, scope)
select s.role_id, p.id, 'all'
  from public.intermediate_stores s
  join public.permissions p
    on (p.module_code = 'store_routing' and p.action in ('view', 'create'))
    or (p.module_code = 'department_routing' and p.action = 'view')
on conflict (role_id, permission_id) do nothing;

insert into public.role_permissions (role_id, permission_id, scope)
select r.id, p.id, 'all'
  from public.roles r
  join public.permissions p on p.module_code = 'store_routing' and p.action = 'view'
 where r.code in ('MANAGEMENT', 'REPLACEMENT_MANAGER')
on conflict (role_id, permission_id) do nothing;

-- 3. Menu: "Department Routing" for every store role. The legacy DEPT_ROUTING (RM) and DEPT_ISSUE
--    (Store Manager) steps stay: their queues only ever list legacy goods slips (held at the
--    legacy Intermediate Store); the report below shows how many are left.
insert into public.role_journey_steps (role_id, journey_step_id, sort_order)
select st.role_id, js.id, 20
  from public.intermediate_stores st
  join public.journey_steps js on js.code = 'STORE_DEPT_ROUTING'
on conflict (role_id, journey_step_id) do nothing;

-- 4. Report
do $$
declare
  v_ready  integer;
  v_legacy integer;
begin
  select count(*) into v_ready
    from public.goods_slips g
   where g.status in ('TRANSFER_SLIP_GENERATED', 'STORE_ACKNOWLEDGED')
     and exists (select 1 from rms_private.gs_store_routing_progress(g.id) p
                  where p.status = 'ROUTING_PENDING');
  select count(*) into v_legacy
    from public.goods_slips where status = 'HELD_AT_INTERMEDIATE_STORE';
  raise notice 'DEC-67: % goods slip(s) waiting for store routing; % legacy goods slip(s) on the RM plan / Store Manager issue path',
    v_ready, v_legacy;
end
$$;

commit;
