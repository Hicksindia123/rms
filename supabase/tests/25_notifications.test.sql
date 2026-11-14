-- =============================================================================
-- 25_notifications.test.sql — P4-03 Notification Automation, Escalations, Outbox & Templates
-- (master plan §8.7, §10; BR-06, DEC-05, DEC-25, DEC-30)
-- =============================================================================
begin;
select plan(23);

-- 1. Verify tables exist
select has_table('public', 'notification_event_types', 'notification_event_types table exists');
select has_table('public', 'notification_rules', 'notification_rules table exists');
select has_table('public', 'notification_events', 'notification_events outbox table exists');
select has_table('public', 'notification_deliveries', 'notification_deliveries table exists');
select has_table('public', 'notification_templates', 'notification_templates table exists');
select has_table('public', 'notification_user_settings', 'notification_user_settings table exists');
select has_table('public', 'workflow_task_escalations', 'workflow_task_escalations table exists');

-- 2. Verify P4-03 prompt required event types are present
select ok(
  (select count(*) >= 22 from public.notification_event_types where code in (
    'GS_CREATED', 'MISSING_DOCUMENTS', 'EVIDENCE_COMPLETED', 'CSR_APPROVAL_REQUIRED',
    'CSR_DECIDED', 'HAZARD_DETECTED', 'REJECTION_RECORDED', 'PENDENCY_OPENED',
    'PENDENCY_CLEARED', 'TRANSFER_INITIATED', 'TRANSFER_DISCREPANCY', 'TECH_BATCH_ALLOTTED',
    'TECH_BATCH_RECEIVED', 'BATTERY_LOW_STOCK', 'PARTS_RECOVERED', 'STORE_ISSUED',
    'DISPATCHED', 'CN_DECISION_REQUIRED', 'CN_ISSUED', 'NOTIFICATION_PENDING',
    'GS_CLOSED', 'DAILY_AUDIT_MISSED'
  )),
  'All required P4-03 event types seeded in notification_event_types'
);

-- 3. Mandatory flags on critical compliance/safety events
select ok(
  (select is_mandatory from public.notification_event_types where code = 'HAZARD_DETECTED'),
  'HAZARD_DETECTED is mandatory'
);
select ok(
  (select is_mandatory from public.notification_event_types where code = 'MISSING_DOCUMENTS'),
  'MISSING_DOCUMENTS is mandatory'
);
select ok(
  (select is_mandatory from public.notification_event_types where code = 'DAILY_AUDIT_MISSED'),
  'DAILY_AUDIT_MISSED is mandatory'
);

-- 4. Event types immutability guard
select throws_ok(
  $$delete from public.notification_event_types where code = 'GS_CREATED'$$,
  '42501',
  null,
  'Event types cannot be deleted'
);
select throws_ok(
  $$update public.notification_event_types set code = 'GS_CREATED_RENAMED' where code = 'GS_CREATED'$$,
  '42501',
  null,
  'Event type codes are immutable'
);

-- 5. Outbox append-only guard
-- The guard trigger is row-level: on a fresh `supabase db reset` the outbox is empty and the delete
-- would succeed vacuously. Publish one event first so the guard is actually exercised.
insert into public.notification_events (event_type, dedupe_key, payload)
values ('GS_CREATED', 'pgtap-25-append-only', '{"title": "pgTAP outbox guard"}');

select throws_ok(
  $$delete from public.notification_events$$,
  '42501',
  null,
  'Notification outbox events are append-only'
);

-- 6. Exactly-once delivery guarantee (unique event_id, user_id, channel)
select col_is_unique(
  'public',
  'notification_deliveries',
  ARRAY['event_id', 'user_id', 'channel'],
  'notification_deliveries enforces unique (event_id, user_id, channel)'
);

-- 7. Escalation unique constraint (task_id, escalation_rule_id)
select col_is_unique(
  'public',
  'workflow_task_escalations',
  ARRAY['task_id', 'escalation_rule_id'],
  'workflow_task_escalations enforces unique (task_id, escalation_rule_id)'
);

-- 8. Templates have one published version per event_type and channel
select is(
  (select count(*)::int from (
    select event_type, channel, count(*) as cnt
    from public.notification_templates
    where status = 'PUBLISHED'
    group by event_type, channel
    having count(*) > 1
  ) sub),
  0,
  'Exactly one published template per event_type and channel'
);

-- 9. Notification template immutability guard
select throws_ok(
  $$delete from public.notification_templates where status = 'PUBLISHED'$$,
  '42501',
  null,
  'Template versions cannot be deleted'
);

-- 10. Role validation trigger on notification_rules
select throws_ok(
  $$insert into public.notification_rules (event_type, name, recipient_role_codes, channels)
    values ('GS_CREATED', 'Invalid Role Rule', array['NON_EXISTENT_ROLE'], array['IN_APP'])$$,
  '23503',
  null,
  'Rule recipient_role_codes must exist in public.roles'
);

-- 11. Channel array constraint on notification_rules
select throws_ok(
  $$insert into public.notification_rules (event_type, name, recipient_role_codes, channels)
    values ('GS_CREATED', 'Invalid Channel Rule', array['SUPER_ADMIN'], array['SMS'])$$,
  '23514',
  null,
  'Rule channels must only contain IN_APP and/or EMAIL'
);

-- 12. RLS enabled on tables
select ok(
  (select bool_and(c.relrowsecurity) from pg_class c
   where c.oid in (
     'public.notification_event_types'::regclass,
     'public.notification_rules'::regclass,
     'public.notification_events'::regclass,
     'public.notification_deliveries'::regclass,
     'public.notification_templates'::regclass,
     'public.notification_user_settings'::regclass,
     'public.workflow_task_escalations'::regclass
   )),
  'RLS enabled on all notification tables'
);

-- 13. Escalation rules are seeded inactive by default (DEC-30)
select is(
  (select count(*)::int from public.escalation_rules where is_active = true),
  0,
  'All escalation rules are seeded inactive by default per DEC-30'
);

-- 14. Default rules exist for critical events
select ok(
  (select count(*) > 0 from public.notification_rules where is_active = true),
  'Active notification rules exist'
);

select * from finish();
rollback;
