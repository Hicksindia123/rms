-- Release 2026-11-20 - Phase P4 (DEC-64; Q9 PROVISIONAL, Q10-Q12 user): items -> Replacement /
-- Complete Sales Return popup -> categorisation -> lock (inward stock booked), edits after the lock
-- by Super Admin / Management only. RM Review edits retired.
--
-- Apply to production AFTER migration 20261120000500_p4_categorisation_lock.sql and after deploying
-- the P4 backend + frontend. Idempotent; safe to re-run:
--   psql "<admin url>" -X -v ON_ERROR_STOP=1 -f supabase/snippets/release_20261120_p4_categorisation_lock.sql
-- Same configuration as supabase/seed.sql (phase prompts §0 rule 3).
begin;

-- 1. Status labels (GS_STATUS)
insert into public.option_items (option_set_id, code, label, allowed_status, rule_text, next_action_text,
                                 remarks, system_behavior, required_fields, sort_order, source_ref)
select os.id, v.code, v.label, 'YES', null, null, null, null, '[]'::jsonb, v.sort_order, 'DEC-64'
  from (values ('PENDING_TRANSFER_SLIP', 'Pending Transfer Slip', 72),
               ('SALES_RETURN_HOLD', 'Sales Return – On Hold', 74)) as v(code, label, sort_order)
  join public.option_sets os on os.code = 'GS_STATUS'
on conflict (option_set_id, code) do nothing;

-- 2. Popup choices (RETURN_CATEGORY; codes unchanged): RO = "Replacement", listed first.
update public.option_items oi
   set label = v.label, sort_order = v.sort_order
  from public.option_sets os,
       (values ('RO', 'Replacement', 10), ('CSR', 'Complete Sales Return', 20)) as v(code, label, sort_order)
 where os.code = 'RETURN_CATEGORY' and oi.option_set_id = os.id and oi.code = v.code
   and (oi.label, oi.sort_order) is distinct from (v.label, v.sort_order);

-- 3. Management edits after the lock (itemization.configure; Super Admin holds every permission).
insert into public.role_permissions (role_id, permission_id, scope)
select r.id, p.id, 'all'
  from public.roles r
  join public.permissions p on p.module_code = 'itemization' and p.action = 'configure'
 where r.code = 'MANAGEMENT'
on conflict (role_id, permission_id) do nothing;

-- 4. RM Review menu step retired (Q9). Legacy RM_REVIEW GSs are opened from the goods slip.
delete from public.role_journey_steps rjs
 using public.journey_steps s
 where rjs.journey_step_id = s.id and s.code = 'RM_REVIEW';
update public.journey_steps set is_active = false where code = 'RM_REVIEW' and is_active;

-- 5. Notification rules (event types come with the migration).
insert into public.notification_rules
  (event_type, name, include_context_recipients, recipient_role_codes, channels, priority, is_active)
select v.event_type, v.name, true, v.roles, array['IN_APP'], v.priority, true
  from (values
    ('CATEGORISATION_LOCKED', 'RM: goods slip ready for its transfer slip', array['REPLACEMENT_MANAGER'], 'NORMAL'),
    ('SALES_RETURN_HOLD', 'RM & Management: Complete Sales Return on hold', array['REPLACEMENT_MANAGER', 'MANAGEMENT'], 'NORMAL'),
    ('LOCKED_GS_EDITED', 'RM & locker: goods slip edited after the lock', array['REPLACEMENT_MANAGER'], 'HIGH')
  ) as v(event_type, name, roles, priority)
 where not exists (select 1 from public.notification_rules r where r.event_type = v.event_type);

-- 6. Report GSs in CATEGORISATION / RM_REVIEW (legacy): CATEGORISATION GSs now finish with the
--    popup + lock; RM_REVIEW GSs keep approve / send back.
do $$
declare
  v_cat integer;
  v_rm  integer;
begin
  select count(*) filter (where status = 'CATEGORISATION'), count(*) filter (where status = 'RM_REVIEW')
    into v_cat, v_rm from public.goods_slips;
  raise notice 'DEC-64: % GS(s) in CATEGORISATION (finish with the lock), % in RM_REVIEW (approve / send back)', v_cat, v_rm;
end
$$;

commit;
