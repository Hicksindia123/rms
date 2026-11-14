-- Migration: 20261106000400_p4_03_rm_action_revised_event.sql
-- Prompt: P4-03 (fix forward of 20261106000300). The RM action revision alert (P2-07 / P3-05,
-- type RM_ACTION_REVISED) wrote public.notifications directly; centralising it through the
-- outbox needs a catalogue entry and its default email template.

insert into public.notification_event_types
  (code, label, description, category, default_priority, is_mandatory, source_ref, sort_order)
values
  ('RM_ACTION_REVISED', 'RM actions revised',
   'The Replacement Manager revised planned actions (CN / send) after they were finalised.',
   'COMMERCIAL', 'HIGH', false, 'WF r6, BR-36', 470)
on conflict (code) do nothing;

insert into public.notification_templates (event_type, channel, version_no, subject, body, change_reason)
select 'RM_ACTION_REVISED', 'EMAIL', 1,
       '[{app_name}] {title}',
       E'Hello {recipient_name},\n\n{title}\n\n{body}\n\nEvent: {event_label}\nPriority: {priority}\nOpen in RMS: {link}\n\n— {app_name} (automated message; manage email preferences in RMS)',
       'P4-03 default'
 where not exists (select 1 from public.notification_templates
                    where event_type = 'RM_ACTION_REVISED' and channel = 'EMAIL');
