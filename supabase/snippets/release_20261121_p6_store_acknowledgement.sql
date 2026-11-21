-- Release 2026-11-21 - Phase P6 (DEC-66; Q12 user, Q13 PROVISIONAL): the Intermediate Store the
-- transfer slip is addressed to (OP / DT / RI …) acknowledges its receipt in full, or reports a
-- discrepancy (remark only). The old STORE_ACCEPT menu step is hidden.
--
-- Apply to production AFTER migration 20261121000200_p6_store_acknowledgement.sql and after
-- deploying the P6 backend + frontend. Idempotent; safe to re-run:
--   psql "<admin url>" -X -v ON_ERROR_STOP=1 -f supabase/snippets/release_20261121_p6_store_acknowledgement.sql
-- Same configuration as supabase/seed.sql (phase prompts §0 rule 3).
begin;

-- 1. Status label (GS_STATUS)
insert into public.option_items (option_set_id, code, label, allowed_status, rule_text, next_action_text,
                                 remarks, system_behavior, required_fields, sort_order, source_ref)
select os.id, 'STORE_ACKNOWLEDGED', 'Acknowledged by Store', 'YES', null, null, null, null,
       '[]'::jsonb, 74, 'DEC-66'
  from public.option_sets os
 where os.code = 'GS_STATUS'
on conflict (option_set_id, code) do nothing;

-- 2. Grants: every Intermediate Store role views its slips and acknowledges them. Stores added in
--    the Admin Panel have their own role; it gets the same grants here (one role per store).
insert into public.role_permissions (role_id, permission_id, scope)
select s.role_id, p.id, 'all'
  from public.intermediate_stores s
  join public.permissions p on p.module_code = 'transfer_slips' and p.action in ('view', 'approve')
on conflict (role_id, permission_id) do nothing;

-- 3. Menus: "Acknowledge Transfer Slips" for every store role; STORE_ACCEPT hidden (legacy custody
--    transfers are still accepted from the Custody screen).
insert into public.role_journey_steps (role_id, journey_step_id, sort_order)
select st.role_id, js.id, 10
  from public.intermediate_stores st
  join public.journey_steps js on js.code = 'ACK_TRANSFER_SLIPS'
on conflict (role_id, journey_step_id) do nothing;

delete from public.role_journey_steps rjs
 using public.journey_steps s
 where rjs.journey_step_id = s.id and s.code = 'STORE_ACCEPT';
update public.journey_steps set is_active = false where code = 'STORE_ACCEPT' and is_active;

-- 4. Notification rules (event types come with the migration)
insert into public.notification_rules
  (event_type, name, include_context_recipients, recipient_role_codes, channels, priority, is_active)
select v.event_type, v.name, true, v.roles, array['IN_APP'], v.priority, true
  from (values
    ('TRANSFER_SLIP_GENERATED', 'Store users: transfer slip to acknowledge', '{}'::text[], 'NORMAL'),
    ('TRANSFER_SLIP_DISCREPANCY', 'RM & Management: transfer slip discrepancy', array['REPLACEMENT_MANAGER', 'MANAGEMENT'], 'HIGH')
  ) as v(event_type, name, roles, priority)
 where not exists (select 1 from public.notification_rules r where r.event_type = v.event_type);

-- 5. Report: slips waiting for their store; legacy store-accept transfers still open
do $$
declare
  v_slips  integer;
  v_legacy integer;
begin
  select count(*) into v_slips from public.transfer_slips where status = 'GENERATED';
  select count(*) into v_legacy
    from public.goods_slips g join public.custody_transfers t on t.id = g.transfer_slip_id
   where g.status = 'RM_REVIEW' and t.status = 'INITIATED';
  raise notice 'DEC-66: % transfer slip(s) waiting for store acknowledgement; % legacy transfer(s) to accept from Custody',
    v_slips, v_legacy;
end
$$;

commit;
