-- Change plan 2026-11-12 · Phase 9 — Party communication (email from Accounts values)
-- (docs/RMS_MASTER_PLAN_ADDENDUM_2026-11.md AMD-20; BR-38, DD r79, DEC-25, DEC-48; G-15, G-16, G-18).
--
-- 1. party_emails (AMD-20): one row per party email (send, resend or auto-send) built from the values
--    Accounts entered on the CURRENT, completed A/c Actions slip (CN No./Date/Value, Challan No./Date)
--    plus the Dispatch Slip details. Recipient, subject, body, the structured values and the template
--    used are frozen at insert (G-18). Delivery: QUEUED -> SENT | FAILED | SKIPPED, once. Never deleted.
-- 2. party_notifications: a SENT party email records the BR-38 PRIOR_INFO_SENT notification with
--    delivery_mode EMAIL_SENT and a link to the email (until now only RECORDED_MANUALLY existed,
--    DEC-25). The guard checks the link (same GS, email SENT, same recipient).
-- 3. Config (rule e): settings party_email.template (subject / body / line templates) and
--    party_email.delivery (auto_send = OFF until an admin enables it; optional CC list).

-- ===========================================================================
-- 1. party_emails
-- ===========================================================================
create table public.party_emails (
  id                   uuid primary key default gen_random_uuid(),
  gs_id                uuid not null references public.goods_slips (id) on delete restrict,
  ac_action_slip_id    uuid not null references public.ac_action_slips (id) on delete restrict,
  -- MANUAL: Accounts pressed Send · RESEND: re-send of an earlier email · AUTO: party_email.delivery
  trigger_code         text not null check (trigger_code in ('MANUAL', 'RESEND', 'AUTO')),
  resend_of_id         uuid references public.party_emails (id) on delete restrict,
  email_to             text,
  cc                   text[] not null default '{}',
  subject              text not null,
  body                 text not null,
  -- G-18: the Accounts values and the template the message was built from.
  snapshot             jsonb not null check (jsonb_typeof(snapshot) = 'object'),
  template_snapshot    jsonb not null check (jsonb_typeof(template_snapshot) = 'object'),
  status               text not null default 'QUEUED'
                       check (status in ('QUEUED', 'SENT', 'FAILED', 'SKIPPED')),
  skip_reason          text check (skip_reason in ('SMTP_NOT_CONFIGURED', 'NO_EMAIL_ADDRESS', 'TEMPLATE_INVALID')),
  attempts             integer not null default 0 check (attempts >= 0),
  next_attempt_at      timestamptz not null default now(),
  last_error           text,
  sent_at              timestamptz,
  requested_by         uuid not null default rms_private.current_actor() references public.profiles (id) on delete restrict,
  requested_at         timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  constraint party_emails_resend_link check ((trigger_code = 'RESEND') = (resend_of_id is not null)),
  constraint party_emails_skip_reason check ((status = 'SKIPPED') = (skip_reason is not null)),
  constraint party_emails_sent_at check ((status = 'SENT') = (sent_at is not null)),
  -- Anything that is (or may be) sent has a recipient and a non-empty message.
  constraint party_emails_content check (
    status = 'SKIPPED'
    or (btrim(coalesce(email_to, '')) <> '' and btrim(subject) <> '' and btrim(body) <> ''))
);
create index party_emails_gs_idx on public.party_emails (gs_id, requested_at);
create index party_emails_slip_idx on public.party_emails (ac_action_slip_id);
create index party_emails_resend_idx on public.party_emails (resend_of_id);
create index party_emails_requested_by_idx on public.party_emails (requested_by);
create index party_emails_due_idx on public.party_emails (next_attempt_at) where status = 'QUEUED';

comment on table public.party_emails is
  'AMD-20: party emails built from the Accounts values of a completed A/c Actions slip. Content frozen at insert (G-18); QUEUED -> SENT/FAILED/SKIPPED once; never deleted.';

create or replace function rms_private.party_emails_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_gs_status text;
  v_slip      record;
  v_prev      record;
begin
  if tg_op = 'DELETE' then
    raise exception 'AMD-20: party emails are a permanent log and are never deleted' using errcode = '23514';
  end if;

  if tg_op = 'INSERT' then
    if new.status not in ('QUEUED', 'SKIPPED') or new.attempts <> 0 or new.sent_at is not null then
      raise exception 'AMD-20: a party email starts QUEUED (or SKIPPED with a reason)' using errcode = '23514';
    end if;
    select status into v_gs_status from public.goods_slips where id = new.gs_id;
    if v_gs_status in ('CLOSED', 'CANCELLED') then
      raise exception 'AMD-20 / BR-38: no party email on a % goods slip', v_gs_status using errcode = '23514';
    end if;
    -- Built only from the values of the CURRENT A/c Actions slip after Accounts completed it.
    select s.gs_id, s.status,
           exists (select 1 from public.ac_entry_completions c where c.ac_action_slip_id = s.id) as completed
      into v_slip
      from public.ac_action_slips s where s.id = new.ac_action_slip_id;
    if not found or v_slip.gs_id <> new.gs_id or v_slip.status <> 'CURRENT' or not v_slip.completed then
      raise exception 'AMD-20: a party email needs the completed Accounts entry of the CURRENT A/c Actions slip of this goods slip'
        using errcode = '23514';
    end if;
    if new.resend_of_id is not null then
      select gs_id into v_prev from public.party_emails where id = new.resend_of_id;
      if not found or v_prev.gs_id <> new.gs_id then
        raise exception 'AMD-20: a resend must repeat an email of the same goods slip' using errcode = '23514';
      end if;
    end if;
    return new;
  end if;

  -- UPDATE: only the delivery columns change, and only while QUEUED.
  if (new.gs_id, new.ac_action_slip_id, new.trigger_code, new.resend_of_id, new.email_to, new.cc,
      new.subject, new.body, new.snapshot, new.template_snapshot, new.requested_by, new.requested_at)
     is distinct from
     (old.gs_id, old.ac_action_slip_id, old.trigger_code, old.resend_of_id, old.email_to, old.cc,
      old.subject, old.body, old.snapshot, old.template_snapshot, old.requested_by, old.requested_at) then
    raise exception 'AMD-20 / G-18: the recipient and content of a party email are frozen' using errcode = '23514';
  end if;
  if old.status <> 'QUEUED' then
    raise exception 'AMD-20: a % party email is final (resend creates a new email)', old.status using errcode = '23514';
  end if;
  if new.attempts < old.attempts then
    raise exception 'AMD-20: delivery attempts only increase' using errcode = '23514';
  end if;
  return new;
end
$$;
revoke all on function rms_private.party_emails_guard() from public, anon, authenticated;

create trigger party_emails_guard
  before insert or update or delete on public.party_emails
  for each row execute function rms_private.party_emails_guard();

-- ===========================================================================
-- 2. party_notifications: EMAIL_SENT records linked to the party email (BR-38, DEC-25, AMD-20)
-- ===========================================================================
alter table public.party_notifications
  add column party_email_id uuid unique references public.party_emails (id) on delete restrict;

alter table public.party_notifications drop constraint party_notifications_delivery_mode_check;
alter table public.party_notifications
  add constraint party_notifications_delivery_mode_check
  check (delivery_mode in ('RECORDED_MANUALLY', 'EMAIL_SENT'));
alter table public.party_notifications
  add constraint party_notifications_email_link
  check ((delivery_mode = 'EMAIL_SENT') = (party_email_id is not null)
         and (party_email_id is null or channel_code = 'EMAIL'));

comment on column public.party_notifications.party_email_id is
  'AMD-20: the SENT party email this PRIOR_INFO_SENT record stands for (delivery_mode EMAIL_SENT).';

-- Same rules as 20261105000300 (P3-07), plus the party-email link.
create or replace function rms_private.party_notifications_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_gs_status text;
  v_cn        record;
  v_att       record;
  v_mail      record;
begin
  if tg_op <> 'INSERT' then
    raise exception 'BR-38: party notifications are append-only evidence' using errcode = '23514';
  end if;

  select status into v_gs_status from public.goods_slips where id = new.gs_id;
  if v_gs_status in ('CLOSED', 'CANCELLED') then
    raise exception 'BR-38: a party notification cannot be recorded on a % GS', v_gs_status
      using errcode = '23514';
  end if;

  if new.credit_note_id is not null then
    select gs_id, status into v_cn from public.credit_notes where id = new.credit_note_id;
    if not found or v_cn.gs_id <> new.gs_id then
      raise exception 'BR-38: the credit note does not belong to this GS' using errcode = '23514';
    end if;
    if v_cn.status <> 'ISSUED' then
      raise exception 'BR-38: notify the party only after the CN/JV is ISSUED (status %)', v_cn.status
        using errcode = '23514';
    end if;
  end if;

  if new.proof_attachment_id is not null then
    select gs_id, kind, status into v_att from public.attachments where id = new.proof_attachment_id;
    if not found or v_att.gs_id <> new.gs_id or v_att.kind <> 'NOTIFICATION_PROOF'
       or v_att.status <> 'CONFIRMED' then
      raise exception 'DEC-25: the proof must be a confirmed NOTIFICATION_PROOF upload of this GS'
        using errcode = '23514';
    end if;
  end if;

  -- AMD-20: an EMAIL_SENT record stands for a party email of this GS that was actually SENT.
  if new.party_email_id is not null then
    select gs_id, status, email_to into v_mail from public.party_emails where id = new.party_email_id;
    if not found or v_mail.gs_id <> new.gs_id or v_mail.status <> 'SENT'
       or lower(v_mail.email_to) <> lower(new.recipient) then
      raise exception 'AMD-20: an EMAIL_SENT notification needs a SENT party email of this GS to the same recipient'
        using errcode = '23514';
    end if;
  end if;
  return new;
end
$$;
revoke all on function rms_private.party_notifications_guard() from public, anon, authenticated;

-- ===========================================================================
-- 3. Audit, RLS, grants
-- ===========================================================================
create trigger audit_row after insert or update or delete on public.party_emails
  for each row execute function rms_private.audit_row();
create trigger set_updated_at before update on public.party_emails
  for each row execute function rms_private.set_updated_at();

alter table public.party_emails enable row level security;
create policy party_emails_api_all on public.party_emails
  for all to rms_api using (true) with check (true);
revoke all on public.party_emails from anon, authenticated;
grant select, insert, update on public.party_emails to rms_api;
grant all on public.party_emails to service_role;

-- ===========================================================================
-- 4. Config (rule e): template and delivery settings (DEC-48)
-- ===========================================================================
-- Template placeholders (docs/DECISIONS.md DEC-48):
--   subject / body: {party_name} {party_code} {gs_no} {ac_slip_no} {cn_lines} {cn_total_value}
--                   {challan_lines} {dispatch_details}
--   cn_line:        {line_no} {product_code} {product_name} {action_label} {qty} {cn_no} {cn_date} {cn_value}
--   challan_line:   {line_no} {product_code} {product_name} {action_label} {qty} {challan_no} {challan_date}
--   dispatch_line:  {dispatch_slip_no} {dispatch_date} {transporter} {docket_no} {vehicle_no} {total_qty}
-- {cn_lines} / {challan_lines} / {dispatch_details} expand to one line per entry, each starting on a
-- new line. A body line whose placeholders are all empty is left out (e.g. no CN on the slip).
insert into public.system_settings (key, value, category, description, source_ref) values
  ('party_email.template',
   jsonb_build_object(
     'subject', 'Goods Slip {gs_no}: credit note / replacement details',
     'body', E'Dear {party_name},\n\nThis is prior information on your return under Goods Slip {gs_no} (A/c Actions slip {ac_slip_no}).\n\nCredit note(s):{cn_lines}\nTotal credit note value: {cn_total_value}\n\nReplacement goods (challan):{challan_lines}\n\nDispatch:{dispatch_details}\n\nRegards,\nAccounts Department',
     'cn_line', '- {product_name} ({product_code}): {qty} pc(s), {action_label}. CN {cn_no} dated {cn_date}, value {cn_value}',
     'challan_line', '- {product_name} ({product_code}): {qty} pc(s), {action_label}. Challan {challan_no} dated {challan_date}',
     'dispatch_line', '- Dispatch Slip {dispatch_slip_no} dated {dispatch_date}: {total_qty} pc(s) via {transporter}, docket {docket_no}, vehicle {vehicle_no}'
   ),
   'party_email',
   'AMD-20: party email built from the Accounts values (CN / Challan / Dispatch). Keys: subject, body, cn_line, challan_line, dispatch_line. Placeholders: see DEC-48.',
   'AMD-20'),
  ('party_email.delivery',
   jsonb_build_object('auto_send', 'OFF', 'cc', jsonb_build_array()),
   'party_email',
   'AMD-20 / DEC-48: auto_send = OFF (default; Accounts sends from the party notification screen) | ON_AC_COMPLETION (when Accounts completes the entry) | ON_DISPATCH (when the Dispatch Slip is dispatched, or at completion if nothing ships). cc = list of e-mail addresses copied on every party email.',
   'AMD-20')
on conflict (key) do nothing;
