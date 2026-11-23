-- Release 2026-11-23 - Phase P9 (DEC-69 PROVISIONAL; Q15, Q16): each Intermediate Store analyses
-- its own goods of a goods slip once they are back from the departments (or had no work):
-- Dispatch New Piece / Dispatch Repaired Piece / Not Allowed per item + condition, then "Submit
-- analysis". When every store on the goods slip submitted, the goods slip is "Analysis Completed".
-- Any store user may "Send for Management Approval" (reason); Management resolves it in P10.
--
-- Apply to production AFTER migration 20261123000100_p9_store_analysis.sql and after deploying the
-- P9 backend + frontend. Idempotent; safe to re-run:
--   psql "<admin url>" -X -v ON_ERROR_STOP=1 -f supabase/snippets/release_20261123_p9_store_analysis.sql
-- Same configuration as supabase/seed.sql (phase prompts §0 rule 3).
begin;

-- 1. Status label (GS_STATUS)
insert into public.option_items (option_set_id, code, label, allowed_status, rule_text, next_action_text,
                                 remarks, system_behavior, required_fields, sort_order, source_ref)
select os.id, 'ANALYSIS_COMPLETED', 'Analysis Completed', 'YES', null, null, null, null,
       '[]'::jsonb, 74, 'DEC-69'
  from public.option_sets os
 where os.code = 'GS_STATUS'
on conflict (option_set_id, code) do nothing;

-- 2. Grants. Every Intermediate Store role (stores added in the Admin Panel have their own role)
--    analyses its goods (store_analysis view + create). Management and the RM see the analysis.
insert into public.role_permissions (role_id, permission_id, scope)
select s.role_id, p.id, 'all'
  from public.intermediate_stores s
  join public.permissions p on p.module_code = 'store_analysis' and p.action in ('view', 'create')
on conflict (role_id, permission_id) do nothing;

insert into public.role_permissions (role_id, permission_id, scope)
select r.id, p.id, 'all'
  from public.roles r
  join public.permissions p on p.module_code = 'store_analysis' and p.action = 'view'
 where r.code in ('MANAGEMENT', 'REPLACEMENT_MANAGER')
on conflict (role_id, permission_id) do nothing;

-- 3. Menu: "Analysis" for every store role.
insert into public.role_journey_steps (role_id, journey_step_id, sort_order)
select st.role_id, js.id, 40
  from public.intermediate_stores st
  join public.journey_steps js on js.code = 'STORE_ANALYSIS'
on conflict (role_id, journey_step_id) do nothing;

-- 4. Action labels (Q15) in the ACTION field library (what the screens and G-18 snapshots use):
--    codes SEND_NEW / SEND_REPAIRED unchanged. An admin's own relabel is kept. The RM_ITEM_ACTION
--    option items keep the workbook's verbatim WF r6 labels.
update public.item_field_library l
   set label = v.label
  from (values ('SEND_NEW', 'Send New', 'Dispatch New Piece'),
               ('SEND_REPAIRED', 'Send Repaired', 'Dispatch Repaired Piece')) as v(code, old_label, label)
 where l.field_group = 'ACTION' and l.code = v.code and l.label = v.old_label;

-- 5. In-app alerts (recipients are these rules, admin-editable; email deferred, Q22).
insert into public.notification_rules
  (event_type, name, include_context_recipients, recipient_role_codes, channels, priority, is_active)
select v.event_type, v.name, true, v.roles, array['IN_APP'], v.priority, true
  from (values
    ('STORE_ANALYSIS_SUBMITTED', 'RM: a store submitted its analysis', array['REPLACEMENT_MANAGER'], 'NORMAL'),
    ('GS_ANALYSIS_COMPLETED', 'RM & Management: every store analysed the goods slip', array['REPLACEMENT_MANAGER', 'MANAGEMENT'], 'NORMAL'),
    ('MANAGEMENT_APPROVAL_REQUESTED', 'Management & Super Admin: goods slip sent for approval', array['MANAGEMENT', 'SUPER_ADMIN'], 'HIGH')
  ) as v(event_type, name, roles, priority)
 where not exists (select 1 from public.notification_rules r where r.event_type = v.event_type);

-- 6. Report
do $$
declare
  v_ready integer;
begin
  select count(*) into v_ready
    from public.goods_slips g
   where g.status = 'STORE_PROCESSING'
     and exists (select 1 from rms_private.gs_store_analysis_progress(g.id) p
                  where p.analysis_status = 'PENDING');
  raise notice 'DEC-69: % goods slip(s) with a store part ready for analysis', v_ready;
end
$$;

commit;
