-- Release 2026-11-23 - Phase P10 (DEC-70; Q17 CONFIRMED, Q18 PROVISIONAL): Management approval.
-- Management opens a goods slip sent by a store ("Management Approval" menu) or any analysed goods
-- slip (search), may change any decision (incl. Issue CN) with a reason per change, and approves it:
-- a system e-approval stamp (approver, role, time, SHA-256 of the GS lines + decisions; non-official,
-- non-legal) that "Verify" re-checks. A goods slip with Issue CN reaches Accounts only with a valid
-- approval (Accounts itself is P11).
--
-- Apply to production AFTER migration 20261123000300_p10_management_approval.sql and after deploying
-- the P10 backend + frontend. Idempotent; safe to re-run:
--   psql "<admin url>" -X -v ON_ERROR_STOP=1 -f supabase/snippets/release_20261123_p10_management_approval.sql
-- Same configuration as supabase/seed.sql (phase prompts §0 rule 3).
begin;

-- 1. Grants: Management changes and approves (Super Admin is granted by the migration).
insert into public.role_permissions (role_id, permission_id, scope)
select r.id, p.id, 'all'
  from public.roles r
  join public.permissions p on p.module_code = 'management_approval' and p.action in ('view', 'approve')
 where r.code = 'MANAGEMENT'
on conflict (role_id, permission_id) do nothing;

-- 2. Menu: "Management Approval" first in Management's menu.
insert into public.role_journey_steps (role_id, journey_step_id, sort_order)
select r.id, js.id, 5
  from public.roles r
  join public.journey_steps js on js.code = 'MANAGEMENT_APPROVAL'
 where r.code = 'MANAGEMENT'
on conflict (role_id, journey_step_id) do nothing;

-- 3. In-app alert (recipients are this rule, admin-editable; the requesting store user and the
--    stores of the goods slip are added as context recipients; email deferred, Q22).
insert into public.notification_rules
  (event_type, name, include_context_recipients, recipient_role_codes, channels, priority, is_active)
select 'GS_MANAGEMENT_APPROVED', 'RM & Management: goods slip approved by Management',
       true, array['REPLACEMENT_MANAGER', 'MANAGEMENT'], array['IN_APP'], 'NORMAL', true
 where not exists (select 1 from public.notification_rules r where r.event_type = 'GS_MANAGEMENT_APPROVED');

-- 4. Report
do $$
declare
  v_open integer;
  v_done integer;
begin
  select count(*) into v_open from public.gs_management_approval_requests where status = 'OPEN';
  select count(*) into v_done from public.goods_slips where status = 'ANALYSIS_COMPLETED';
  raise notice 'DEC-70: % open Management approval request(s); % goods slip(s) Analysis Completed',
    v_open, v_done;
end
$$;

commit;
