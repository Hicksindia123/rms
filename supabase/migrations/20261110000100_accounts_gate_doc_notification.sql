-- 20261110000100_accounts_gate_doc_notification.sql
-- Requirement A: Fast-track notification to Accounts when an Invoice or Debit Note is punched at gate inward.

-- 1. Register GS_DOCUMENT_FOUND in notification_event_types
insert into public.notification_event_types
  (code, label, description, category, default_priority, is_mandatory, source_ref, sort_order)
values
  ('GS_DOCUMENT_FOUND', 'Invoice / Debit Note found at gate',
   'A consignment arrived with a confirmed Invoice or Debit Note for fast-track Accounts review.',
   'COMMERCIAL', 'HIGH', true, 'ACCOUNTS_FAST_TRACK', 25)
on conflict (code) do nothing;

-- 2. The default rule targeting Accounts lives in supabase/seed.sql (after the default rule set).
--    Roles are seed data, so on a fresh `supabase db reset` the ACCOUNTS role does not exist yet
--    here (the rule trigger rejects it), and a rule inserted here also made seed.sql skip its
--    default rule set. Moved 2026-11-12 (docs/DECISIONS.md); databases that already ran this
--    migration keep their rule, and the seed insert is guarded by NOT EXISTS.

-- 3. Add default email notification template
insert into public.notification_templates (event_type, channel, version_no, subject, body, change_reason)
select 'GS_DOCUMENT_FOUND', 'EMAIL', 1,
       '[{app_name}] {title}',
       E'Hello {recipient_name},\n\n{title}\n\n{body}\n\nEvent: {event_label}\nPriority: {priority}\nOpen in RMS: {link}\n\n— {app_name}',
       'Accounts invoice/debit note fast-track alert'
 where not exists (select 1 from public.notification_templates where event_type = 'GS_DOCUMENT_FOUND' and channel = 'EMAIL');
