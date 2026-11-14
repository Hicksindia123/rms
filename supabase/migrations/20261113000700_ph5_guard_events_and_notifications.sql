-- Migration: 20261113000700_ph5_guard_events_and_notifications.sql
-- Description: Allow G-19 in system_guard_events and register Phase 5 notification event types (AMD-11, AMD-12, AMD-13, G-19).

-- 1. Extend system_guard_events guard_code check to allow G-19
alter table public.system_guard_events
  drop constraint if exists system_guard_events_guard_code_check;

alter table public.system_guard_events
  add constraint system_guard_events_guard_code_check check (guard_code ~ '^G-(0[1-9]|1[0-9])$');

-- 2. Register Phase 5 notification event types
insert into public.notification_event_types
  (code, label, description, category, default_priority, is_mandatory, source_ref, sort_order)
values
  ('RM_REVIEW_REQUIRED', 'RM review required',
   'Categorisation completed; GS is ready for Replacement Manager review (AMD-11).',
   'WORKFLOW', 'HIGH', false, 'AMD-11', 480),
  ('CATEGORISATION_SENT_BACK', 'Categorisation sent back',
   'Replacement Manager sent the GS back to categorisation with remarks (AMD-12).',
   'WORKFLOW', 'HIGH', false, 'AMD-12', 490),
  ('TRANSFER_AWAITING_ACCEPTANCE', 'Transfer awaiting acceptance',
   'A custody transfer slip has been generated and is awaiting receipt count (AMD-13).',
   'INVENTORY', 'HIGH', false, 'AMD-13', 500)
on conflict (code) do update
  set label = excluded.label, description = excluded.description,
      default_priority = excluded.default_priority, source_ref = excluded.source_ref;

-- 3. Default email templates for new event types
insert into public.notification_templates (event_type, channel, version_no, subject, body, change_reason)
select v.event_type, 'EMAIL', 1,
       '[{app_name}] {title}',
       E'Hello {recipient_name},\n\n{title}\n\n{body}\n\nEvent: {event_label}\nPriority: {priority}\nOpen in RMS: {link}\n\n— {app_name} (automated message; manage email preferences in RMS)',
       'Phase 5 default'
  from (values
    ('RM_REVIEW_REQUIRED'),
    ('CATEGORISATION_SENT_BACK'),
    ('TRANSFER_AWAITING_ACCEPTANCE')
  ) as v(event_type)
 where not exists (
   select 1 from public.notification_templates
    where event_type = v.event_type and channel = 'EMAIL'
 );
