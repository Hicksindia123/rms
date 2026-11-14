-- Migration: 20261106000300_p4_03_notifications.sql
-- Prompt: P4-03 Notification automation, escalations & email channel
-- (master plan §8.7, §10 "Notifications"; BR-06, DEC-05, DEC-25, DEC-30).
--
-- 1. notification_event_types   — catalogue of domain events (code immutable; label, mandatory flag
--                                  and default priority admin-editable, rule e).
-- 2. notification_rules         — event → recipients (roles / users / the publisher's context
--                                  recipients / assignees of the GS's open step) → channels
--                                  (IN_APP, EMAIL) → priority → active. Defaults are seeded in
--                                  seed.sql (role codes are validated against public.roles).
-- 3. notification_events        — the transactional OUTBOX: written in the same transaction as the
--                                  business change (no phantom notifications on rollback), delivered
--                                  inline in a savepoint and retried by the worker (no lost ones).
-- 4. notification_deliveries    — one row per (event, user, channel): exactly-once fan-out.
-- 5. notification_templates     — versioned email subject/body per event (one PUBLISHED per event).
-- 6. notification_user_settings — per-user email mode (IMMEDIATE / DAILY_DIGEST).
-- 7. workflow_task_escalations  — one row per (task, escalation rule) = "escalate once per level".
-- 8. notifications.event_id     — links each in-app row to its outbox event.
--
-- SMTP settings are NOT stored here: they come from backend env only (P4-03 item 4, rule i).

-- ===========================================================================
-- 1. notification_event_types
-- ===========================================================================
create table public.notification_event_types (
  code              text primary key check (code ~ '^[A-Z][A-Z0-9_]{1,59}$'),
  label             text not null check (btrim(label) <> ''),
  description       text,
  category          text not null default 'WORKFLOW'
                    check (category in ('WORKFLOW','INVENTORY','COMMERCIAL','COMPLIANCE','SYSTEM')),
  default_priority  text not null default 'NORMAL' check (default_priority in ('LOW','NORMAL','HIGH')),
  -- Mandatory events ignore a user's email opt-out and are never batched into the digest.
  is_mandatory      boolean not null default false,
  source_ref        text,
  sort_order        integer not null default 0,
  created_at        timestamptz not null default now(),
  created_by        uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at        timestamptz not null default now()
);
comment on table public.notification_event_types is
  'P4-03 domain event catalogue. Codes are immutable and published by backend services.';

-- Codes are immutable (business logic and preferences key off them, rule e).
create or replace function rms_private.notification_event_types_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'notification event types cannot be deleted (%)', old.code using errcode = '42501';
  end if;
  if new.code <> old.code then
    raise exception 'notification event type codes are immutable (%)', old.code using errcode = '42501';
  end if;
  return new;
end
$$;
revoke all on function rms_private.notification_event_types_guard() from public, anon, authenticated;
create trigger notification_event_types_guard
  before update or delete on public.notification_event_types
  for each row execute function rms_private.notification_event_types_guard();

insert into public.notification_event_types
  (code, label, description, category, default_priority, is_mandatory, source_ref, sort_order) values
  -- P4-03 catalogue (prompt item 1)
  ('GS_CREATED',               'Goods slip created',                 'A goods slip was created at the gate (Step-1).',                                   'WORKFLOW',   'NORMAL', false, 'WF r2', 10),
  ('MISSING_DOCUMENTS',        'Missing documents at gate',          'A consignment arrived without a gate document (NO_DOCUMENT).',                     'COMPLIANCE', 'HIGH',   true,  'BR-03, DEC-05', 20),
  ('EVIDENCE_COMPLETED',       'Unboxing evidence completed',        'Step-2 evidence is complete; documents are ready for Accounts.',                   'WORKFLOW',   'NORMAL', false, 'BR-06, DEC-05', 30),
  ('CSR_APPROVAL_REQUIRED',    'CSR approval required',              'A Complete Sales Return needs the Replacement Manager''s decision.',               'WORKFLOW',   'HIGH',   false, 'BR-08, G-03', 40),
  ('CSR_DECIDED',              'CSR decided',                        'The Replacement Manager decided a Complete Sales Return.',                         'WORKFLOW',   'NORMAL', false, 'BR-08', 50),
  ('HAZARD_DETECTED',          'Hazard detected',                    'A mercury hazard was recorded at inspection.',                                     'COMPLIANCE', 'HIGH',   true,  'G-05', 60),
  ('REJECTION_RECORDED',       'Rejection recorded',                 'Inspection recorded rejected quantity for a goods slip.',                          'WORKFLOW',   'NORMAL', false, 'WF r5', 70),
  ('PENDENCY_OPENED',          'Pendency opened',                    'A Pending (BP) record was opened.',                                                'WORKFLOW',   'NORMAL', false, 'WF r6', 80),
  ('PENDENCY_CLEARED',         'Pendency cleared',                   'A Pending (BP) record was cleared.',                                               'WORKFLOW',   'NORMAL', false, 'WF r6', 90),
  ('TRANSFER_INITIATED',       'Custody transfer initiated',         'A custody transfer is waiting for acceptance.',                                    'INVENTORY',  'NORMAL', false, 'BR-20', 100),
  ('TRANSFER_DISCREPANCY',     'Custody transfer discrepancy',       'A custody transfer was accepted with a quantity discrepancy.',                     'INVENTORY',  'HIGH',   false, 'BR-20, G-09', 110),
  ('TECH_BATCH_ALLOTTED',      'Technician batch allotted',          'A technician batch was allotted.',                                                 'WORKFLOW',   'NORMAL', false, 'BR-23', 120),
  ('TECH_BATCH_RECEIVED',      'Technician batch received',          'Technician receiving results were recorded.',                                      'WORKFLOW',   'NORMAL', false, 'BR-23, BR-24', 130),
  ('BATTERY_LOW_STOCK',        'Battery stock low',                  'A battery type fell below the low-stock threshold in the Battery Store.',          'INVENTORY',  'HIGH',   false, 'BR-24, DEC-15', 140),
  ('PARTS_RECOVERED',          'Parts recovered',                    'Dismantling recovered parts into the spare-parts ledger.',                         'INVENTORY',  'NORMAL', false, 'WF r9', 150),
  ('STORE_ISSUED',             'Issued to Main Store',               'Functional stock was issued to the Main Store.',                                   'INVENTORY',  'NORMAL', false, 'WF r11', 160),
  ('DISPATCHED',               'Replacement dispatched',             'A replacement was dispatched to the party.',                                       'WORKFLOW',   'NORMAL', false, 'WF r11', 170),
  ('CN_DECISION_REQUIRED',     'CN decision required',               'A goods slip reached commercial resolution and needs the CN decision.',            'COMMERCIAL', 'NORMAL', false, 'WF r11', 180),
  ('CN_ISSUED',                'Credit note issued',                 'Accounts issued a credit note / JV.',                                              'COMMERCIAL', 'NORMAL', false, 'WF r11', 190),
  ('NOTIFICATION_PENDING',     'Party notification pending',         'A goods slip is waiting for the prior party notification.',                        'COMMERCIAL', 'NORMAL', false, 'BR-38, DEC-25', 200),
  ('GS_CLOSED',                'Goods slip closed',                  'A goods slip was closed.',                                                         'WORKFLOW',   'NORMAL', false, 'BR-39', 210),
  ('DAILY_AUDIT_MISSED',       'Daily container audit missed',       'Yesterday''s DMT container audit was not confirmed.',                              'COMPLIANCE', 'HIGH',   true,  'DEC-08', 220),
  -- Events that already produced notifications before P4-03 (centralised unchanged)
  ('PROVISIONAL_PARTY_CREATED',       'Provisional party created',       'A provisional party was created at the gate for admin review.',       'WORKFLOW',   'NORMAL', false, 'DEC-02', 300),
  ('MISSING_DOC_EXCEPTION_REQUESTED', 'Missing-document exception requested', 'A Missing Document Exception needs approval.',                'WORKFLOW',   'HIGH',   false, 'DEC-03', 310),
  ('MISSING_DOC_EXCEPTION_DECIDED',   'Missing-document exception decided',  'A Missing Document Exception was approved or rejected.',          'WORKFLOW',   'NORMAL', false, 'DEC-03', 320),
  ('TRANSFER_PROPOSED',               'Packaging transfer proposed',     'A Complete Sales Return is coming with packaging.',                    'INVENTORY',  'NORMAL', false, 'BR-09', 330),
  ('ITEM_CORRECTION_REQUESTED',       'Item correction requested',       'An itemisation correction needs approval.',                            'WORKFLOW',   'NORMAL', false, 'P2-04', 340),
  ('ITEM_CORRECTION_DECIDED',         'Item correction decided',         'An itemisation correction was approved or rejected.',                  'WORKFLOW',   'NORMAL', false, 'P2-04', 350),
  ('CONTAINER_AUDIT_REMINDER',        'Container audit reminder',        'Today''s DMT container audit is not yet confirmed (evening reminder).','COMPLIANCE', 'HIGH',   false, 'DEC-08', 360),
  ('CN_DECISION_ALLOWED',             'CN allowed by RM',                'The Replacement Manager allowed a credit note; Accounts to act.',      'COMMERCIAL', 'HIGH',   false, 'WF r11', 370),
  ('TRANSFER_ACCEPTED',               'Custody transfer accepted',       'A custody transfer was accepted.',                                     'INVENTORY',  'NORMAL', false, 'BR-20', 380),
  ('TRANSFER_ADJUSTMENT_APPROVAL',    'Transfer adjustment approval',    'A custody transfer adjustment needs approval.',                        'INVENTORY',  'HIGH',   false, 'G-09', 390),
  ('TRANSFER_RECONCILIATION_PROPOSED','Transfer reconciliation proposed','A custody transfer reconciliation was proposed.',                       'INVENTORY',  'NORMAL', false, 'G-09', 400),
  ('TRANSFER_CANCELLED',              'Custody transfer cancelled',      'A custody transfer was cancelled.',                                    'INVENTORY',  'NORMAL', false, 'BR-20', 410),
  ('TRANSFER_RECONCILED',             'Custody transfer reconciled',     'A custody transfer discrepancy was reconciled.',                       'INVENTORY',  'NORMAL', false, 'G-09', 420),
  ('STOCK_ADJUSTMENT_REQUESTED',      'Stock adjustment requested',      'A stock count difference needs approval.',                             'INVENTORY',  'NORMAL', false, 'BR-30', 430),
  ('STOCK_ADJUSTMENT_DECIDED',        'Stock adjustment decided',        'A stock adjustment request was approved or rejected.',                 'INVENTORY',  'NORMAL', false, 'BR-30', 440),
  ('SEGREGATION_VIOLATION',           'Segregation violation',           'The nightly custody segregation check found violations.',              'COMPLIANCE', 'HIGH',   true,  'BR-30, G-04', 450),
  ('NON_SELLABLE_RECEIVED',           'Non-sellable stock received',     'Non-sellable pieces moved from a technician batch to the Non-Functional Store.', 'INVENTORY', 'NORMAL', false, 'DEC-17', 460),
  ('SLA_ESCALATION',                  'SLA escalation',                  'A workflow task breached its SLA and reached an escalation level.',    'SYSTEM',     'HIGH',   true,  'DEC-30', 500)
on conflict (code) do nothing;

-- ===========================================================================
-- 2. notification_rules
-- ===========================================================================
create table public.notification_rules (
  id                          uuid primary key default gen_random_uuid(),
  event_type                  text not null references public.notification_event_types (code) on delete restrict,
  name                        text not null check (btrim(name) <> ''),
  -- The recipients the publishing service names for this occurrence (requester, custodian,
  -- the step's approver roles, ...): reproduces the pre-P4-03 behaviour.
  include_context_recipients  boolean not null default false,
  -- Assignees (role holders / users) of the OPEN workflow tasks of the event's GS:
  -- "assignee of next step".
  include_step_assignees      boolean not null default false,
  recipient_role_codes        text[] not null default '{}',
  recipient_user_ids          uuid[] not null default '{}',
  channels                    text[] not null default array['IN_APP']
                              check (cardinality(channels) between 1 and 2
                                     and channels <@ array['IN_APP','EMAIL']::text[]),
  -- null = the event's priority (publisher-supplied, else the catalogue default)
  priority                    text check (priority in ('LOW','NORMAL','HIGH')),
  is_active                   boolean not null default true,
  created_at                  timestamptz not null default now(),
  created_by                  uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at                  timestamptz not null default now(),
  check (include_context_recipients or include_step_assignees
         or cardinality(recipient_role_codes) > 0 or cardinality(recipient_user_ids) > 0)
);
create index notification_rules_event_idx on public.notification_rules (event_type) where is_active;
comment on table public.notification_rules is
  'P4-03 event → recipients → channels rules (admin CRUD, config_change_log; §10 Notifications).';

-- Role codes / user ids must exist (arrays cannot carry FKs).
create or replace function rms_private.notification_rules_validate()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_bad text;
begin
  select string_agg(c, ', ') into v_bad
    from unnest(new.recipient_role_codes) as c
   where not exists (select 1 from public.roles r where r.code = c);
  if v_bad is not null then
    raise exception 'notification rule names unknown roles: %', v_bad using errcode = '23503';
  end if;
  select string_agg(u::text, ', ') into v_bad
    from unnest(new.recipient_user_ids) as u
   where not exists (select 1 from public.profiles p where p.id = u);
  if v_bad is not null then
    raise exception 'notification rule names unknown users: %', v_bad using errcode = '23503';
  end if;
  return new;
end
$$;
revoke all on function rms_private.notification_rules_validate() from public, anon, authenticated;
create trigger notification_rules_validate
  before insert or update on public.notification_rules
  for each row execute function rms_private.notification_rules_validate();

-- ===========================================================================
-- 3. notification_events (transactional outbox)
-- ===========================================================================
create table public.notification_events (
  id                 uuid primary key default gen_random_uuid(),
  event_type         text not null references public.notification_event_types (code) on delete restrict,
  -- Publisher idempotency: the same business occurrence is published once (G-16 retries, jobs).
  dedupe_key         text unique check (dedupe_key is null or length(dedupe_key) between 1 and 300),
  entity_type        text,
  entity_id          uuid,
  gs_id              uuid references public.goods_slips (id) on delete set null,
  -- title, body, notification_type (in-app `type`), and template placeholders
  payload            jsonb not null default '{}'::jsonb check (jsonb_typeof(payload) = 'object'),
  context_user_ids   uuid[] not null default '{}',
  priority           text not null default 'NORMAL' check (priority in ('LOW','NORMAL','HIGH')),
  status             text not null default 'PENDING' check (status in ('PENDING','DISPATCHED','FAILED')),
  attempts           integer not null default 0 check (attempts >= 0),
  next_attempt_at    timestamptz not null default now(),
  last_error         text,
  dispatched_at      timestamptz,
  request_id         text default rms_private.current_request_id(),
  created_at         timestamptz not null default now(),
  created_by         uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  check (status <> 'DISPATCHED' or dispatched_at is not null)
);
create index notification_events_pending_idx on public.notification_events (next_attempt_at)
  where status = 'PENDING';
create index notification_events_type_idx on public.notification_events (event_type, created_at desc);
create index notification_events_gs_idx on public.notification_events (gs_id);
comment on table public.notification_events is
  'P4-03 transactional outbox. Written with the business change; delivered inline (savepoint) or by the worker.';

-- The published facts are immutable; only the delivery bookkeeping columns change.
create or replace function rms_private.notification_events_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'notification events are append-only' using errcode = '42501';
  end if;
  if (to_jsonb(new) - array['status','attempts','next_attempt_at','last_error','dispatched_at'])
     <> (to_jsonb(old) - array['status','attempts','next_attempt_at','last_error','dispatched_at']) then
    raise exception 'a published notification event cannot be changed' using errcode = '42501';
  end if;
  return new;
end
$$;
revoke all on function rms_private.notification_events_guard() from public, anon, authenticated;
create trigger notification_events_guard
  before update or delete on public.notification_events
  for each row execute function rms_private.notification_events_guard();

-- ===========================================================================
-- 4. notification_deliveries (exactly once per event × user × channel)
-- ===========================================================================
create table public.notification_deliveries (
  id               uuid primary key default gen_random_uuid(),
  event_id         uuid not null references public.notification_events (id) on delete restrict,
  user_id          uuid not null references public.profiles (id) on delete restrict,
  channel          text not null check (channel in ('IN_APP','EMAIL')),
  rule_ids         uuid[] not null default '{}',
  priority         text not null default 'NORMAL' check (priority in ('LOW','NORMAL','HIGH')),
  -- SENT: delivered · PENDING: email waiting for the worker · DIGEST: waiting for the daily digest
  -- SKIPPED: deliberately not sent (skip_reason) · FAILED: retries exhausted (last_error)
  status           text not null check (status in ('PENDING','DIGEST','SENT','SKIPPED','FAILED')),
  skip_reason      text check (skip_reason in ('OPTED_OUT','SMTP_NOT_CONFIGURED','NO_EMAIL_ADDRESS')),
  notification_id  uuid references public.notifications (id) on delete restrict,
  email_to         text,
  attempts         integer not null default 0 check (attempts >= 0),
  next_attempt_at  timestamptz not null default now(),
  last_error       text,
  sent_at          timestamptz,
  digest_key       text,
  created_at       timestamptz not null default now(),
  unique (event_id, user_id, channel),
  check (status <> 'SKIPPED' or skip_reason is not null),
  check (channel <> 'IN_APP' or status in ('SENT','FAILED')),
  check (status <> 'SENT' or sent_at is not null)
);
create index notification_deliveries_email_due_idx on public.notification_deliveries (next_attempt_at)
  where channel = 'EMAIL' and status = 'PENDING';
create index notification_deliveries_digest_idx on public.notification_deliveries (user_id)
  where status = 'DIGEST';
create index notification_deliveries_user_idx on public.notification_deliveries (user_id, created_at desc);
create index notification_deliveries_notification_idx on public.notification_deliveries (notification_id);
comment on table public.notification_deliveries is
  'P4-03 fan-out ledger: one row per event × user × channel (exactly-once; never silently dropped).';

alter table public.notifications
  add column event_id uuid references public.notification_events (id) on delete restrict;
create index notifications_event_idx on public.notifications (event_id);

-- ===========================================================================
-- 5. notification_templates (versioned; one PUBLISHED per event × channel)
-- ===========================================================================
create table public.notification_templates (
  id            uuid primary key default gen_random_uuid(),
  event_type    text not null references public.notification_event_types (code) on delete restrict,
  channel       text not null default 'EMAIL' check (channel in ('EMAIL')),
  version_no    integer not null check (version_no > 0),
  subject       text not null check (btrim(subject) <> '' and length(subject) <= 300),
  body          text not null check (btrim(body) <> '' and length(body) <= 20000),
  status        text not null default 'PUBLISHED' check (status in ('PUBLISHED','RETIRED')),
  change_reason text,
  published_at  timestamptz not null default now(),
  created_at    timestamptz not null default now(),
  created_by    uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at    timestamptz not null default now(),
  unique (event_type, channel, version_no)
);
create unique index notification_templates_one_published
  on public.notification_templates (event_type, channel) where status = 'PUBLISHED';
comment on table public.notification_templates is
  'P4-03 email templates per event. Each save is a new version; older versions are RETIRED and immutable.';

create or replace function rms_private.notification_templates_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'notification template versions cannot be deleted' using errcode = '42501';
  end if;
  if old.status = 'RETIRED'
     or new.status <> 'RETIRED'
     or (to_jsonb(new) - array['status','updated_at']) <> (to_jsonb(old) - array['status','updated_at']) then
    raise exception 'a template version is immutable; only retiring the published version is allowed'
      using errcode = '42501';
  end if;
  return new;
end
$$;
revoke all on function rms_private.notification_templates_guard() from public, anon, authenticated;
create trigger notification_templates_guard
  before update or delete on public.notification_templates
  for each row execute function rms_private.notification_templates_guard();

-- Default v1 template for every event (placeholders: docs/NOTIFICATIONS.md).
insert into public.notification_templates (event_type, channel, version_no, subject, body, change_reason)
select t.code, 'EMAIL', 1,
       '[{app_name}] {title}',
       E'Hello {recipient_name},\n\n{title}\n\n{body}\n\nEvent: {event_label}\nPriority: {priority}\nOpen in RMS: {link}\n\n— {app_name} (automated message; manage email preferences in RMS)',
       'P4-03 default'
  from public.notification_event_types t
on conflict do nothing;

-- ===========================================================================
-- 6. notification_user_settings
-- ===========================================================================
create table public.notification_user_settings (
  user_id     uuid primary key references public.profiles (id) on delete cascade,
  email_mode  text not null default 'IMMEDIATE' check (email_mode in ('IMMEDIATE','DAILY_DIGEST')),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
comment on table public.notification_user_settings is
  'P4-03 per-user email delivery mode. Mandatory events are always sent immediately.';

-- ===========================================================================
-- 7. workflow_task_escalations (once per task × level)
-- ===========================================================================
create table public.workflow_task_escalations (
  id                  uuid primary key default gen_random_uuid(),
  task_id             uuid not null references public.workflow_tasks (id) on delete cascade,
  escalation_rule_id  uuid not null references public.escalation_rules (id) on delete restrict,
  level_no            integer not null check (level_no > 0),
  due_at              timestamptz not null,
  escalated_at        timestamptz not null default now(),
  event_id            uuid references public.notification_events (id) on delete restrict,
  unique (task_id, escalation_rule_id)
);
create index workflow_task_escalations_rule_idx on public.workflow_task_escalations (escalation_rule_id);
create index workflow_task_escalations_event_idx on public.workflow_task_escalations (event_id);
comment on table public.workflow_task_escalations is
  'P4-03 / DEC-30: each SLA escalation level fires once per task (unique task × rule).';

create index escalation_rules_step_idx on public.escalation_rules (workflow_step_id) where is_active;
create index workflow_tasks_open_escalation_idx on public.workflow_tasks (created_at) where status = 'OPEN';

-- ===========================================================================
-- 8. Audit, RLS, grants
-- ===========================================================================
select rms_private.attach_standard_triggers('public.notification_event_types');
select rms_private.attach_standard_triggers('public.notification_rules');
select rms_private.attach_standard_triggers('public.notification_templates');
select rms_private.attach_standard_triggers('public.notification_user_settings');
select rms_private.attach_standard_triggers('public.workflow_task_escalations');
-- notification_events / notification_deliveries are themselves logs (high volume): not row-audited.
select rms_private.attach_standard_triggers('public.notification_events', false);
select rms_private.attach_standard_triggers('public.notification_deliveries', false);

alter table public.notification_event_types   enable row level security;
alter table public.notification_rules         enable row level security;
alter table public.notification_events        enable row level security;
alter table public.notification_deliveries    enable row level security;
alter table public.notification_templates     enable row level security;
alter table public.notification_user_settings enable row level security;
alter table public.workflow_task_escalations  enable row level security;

revoke all on public.notification_event_types   from anon, authenticated;
revoke all on public.notification_rules         from anon, authenticated;
revoke all on public.notification_events        from anon, authenticated;
revoke all on public.notification_deliveries    from anon, authenticated;
revoke all on public.notification_templates     from anon, authenticated;
revoke all on public.notification_user_settings from anon, authenticated;
revoke all on public.workflow_task_escalations  from anon, authenticated;

-- rms_api has full DML by default privileges (P1-02); narrow it to what the API needs.
revoke insert, delete, truncate on public.notification_event_types from rms_api;
revoke delete, truncate on public.notification_events from rms_api;
revoke delete, truncate on public.notification_deliveries from rms_api;
revoke delete, truncate on public.notification_templates from rms_api;
revoke delete, truncate on public.notification_user_settings from rms_api;
revoke update, delete, truncate on public.workflow_task_escalations from rms_api;
grant select, update on public.notification_event_types to rms_api;
grant select, insert, update, delete on public.notification_rules to rms_api;
grant select, insert, update on public.notification_events to rms_api;
grant select, insert, update on public.notification_deliveries to rms_api;
grant select, insert, update on public.notification_templates to rms_api;
grant select, insert, update on public.notification_user_settings to rms_api;
grant select, insert on public.workflow_task_escalations to rms_api;

grant all on public.notification_event_types   to service_role;
grant all on public.notification_rules         to service_role;
grant all on public.notification_events        to service_role;
grant all on public.notification_deliveries    to service_role;
grant all on public.notification_templates     to service_role;
grant all on public.notification_user_settings to service_role;
grant all on public.workflow_task_escalations  to service_role;
