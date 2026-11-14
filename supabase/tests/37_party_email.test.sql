-- Change plan 2026-11-12 · Phase 9 (migration 20261114000200): party email from the Accounts values.
-- AMD-20 / BR-38 / DEC-25 / DEC-48 / G-18: a party email is built only from the completed Accounts
-- entry of the CURRENT A/c Actions slip; content is frozen at insert; delivery QUEUED -> final once;
-- never deleted; an EMAIL_SENT PRIOR_INFO_SENT record needs a SENT email of the same GS and recipient.
-- Auto-send is OFF until enabled in settings.

begin;
select plan(18);

insert into auth.users (id, email)
values ('99999999-9999-0000-0000-000000000001', 'ph9_user@example.com')
on conflict do nothing;
insert into public.profiles (id, full_name, is_active)
values ('99999999-9999-0000-0000-000000000001', 'Ph9 User', true)
on conflict do nothing;

-- GS A (completed by Accounts) and B (finalised, not completed): 4 pcs Issue CN each.
do $$
declare
  v_wf uuid;
begin
  set local session_replication_role = 'replica';
  select v.id into v_wf from public.workflow_versions v
    join public.workflow_definitions d on d.id = v.workflow_definition_id and d.code = 'RMS_STANDARD'
   where v.status = 'PUBLISHED' limit 1;

  insert into public.goods_slips (
    id, gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count, box_count, status
  )
  values
    ('99999999-9999-0000-0000-00000000000a', 'GS/TEST/PH9/A', v_wf, 'COURIER_PARCEL', 'C', '1', 1, 1, 'HELD_AT_INTERMEDIATE_STORE'),
    ('99999999-9999-0000-0000-00000000000b', 'GS/TEST/PH9/B', v_wf, 'COURIER_PARCEL', 'C', '1', 1, 1, 'HELD_AT_INTERMEDIATE_STORE');

  insert into public.gs_items (id, gs_id, line_no, product_id, category_id, documented_qty, received_qty)
  select i.id, i.gs_id, 1, p.id, p.category_id, 4, 4
    from (values
      ('99999999-9999-0000-0000-0000000000a1'::uuid, '99999999-9999-0000-0000-00000000000a'::uuid),
      ('99999999-9999-0000-0000-0000000000b1'::uuid, '99999999-9999-0000-0000-00000000000b'::uuid)
    ) as i(id, gs_id)
    cross join lateral (
      select pr.id, pr.category_id from public.products pr
        join public.product_categories c on c.id = pr.category_id and c.code = 'DMT'
       order by pr.code limit 1
    ) p;

  insert into public.attachments (id, gs_id, entity_type, kind, bucket, object_path, mime_type, size_bytes, status, confirmed_at)
  values
    ('99999999-9999-0000-0000-0000000000f1', '99999999-9999-0000-0000-00000000000a', 'ac_action_slips', 'GENERATED_PDF',
     'rms-documents', 'gs/99999999-9999-0000-0000-00000000000a/generated_pdf/99999999-9999-4000-8000-0000000000f1.pdf',
     'application/pdf', 1000, 'CONFIRMED', now()),
    ('99999999-9999-0000-0000-0000000000f2', '99999999-9999-0000-0000-00000000000b', 'ac_action_slips', 'GENERATED_PDF',
     'rms-documents', 'gs/99999999-9999-0000-0000-00000000000b/generated_pdf/99999999-9999-4000-8000-0000000000f2.pdf',
     'application/pdf', 1000, 'CONFIRMED', now());
  set local session_replication_role = 'origin';
end;
$$;

insert into public.rm_item_actions (gs_item_id, revision_no, action_code, qty, decided_by)
values ('99999999-9999-0000-0000-0000000000a1', 1, 'ISSUE_CN', 4, '99999999-9999-0000-0000-000000000001'),
       ('99999999-9999-0000-0000-0000000000b1', 1, 'ISSUE_CN', 4, '99999999-9999-0000-0000-000000000001');

insert into public.ac_action_slips (id, gs_id, slip_no, version_no, revision_no, attachment_id, template_version_no, content, totals, sha256, finalised_by)
values ('99999999-9999-0000-0000-0000000000e1', '99999999-9999-0000-0000-00000000000a', 'RSA/TEST/PH9/A', 1, 1, '99999999-9999-0000-0000-0000000000f1', 1, '{}', '{}', repeat('a', 64), '99999999-9999-0000-0000-000000000001'),
       ('99999999-9999-0000-0000-0000000000e2', '99999999-9999-0000-0000-00000000000b', 'RSA/TEST/PH9/B', 1, 1, '99999999-9999-0000-0000-0000000000f2', 1, '{}', '{}', repeat('a', 64), '99999999-9999-0000-0000-000000000001');

update public.ac_entry_lines set cn_no = 'CN-PH9-1', cn_date = current_date, cn_value = 99.50
 where ac_action_slip_id = '99999999-9999-0000-0000-0000000000e1';
insert into public.ac_entry_completions (gs_id, ac_action_slip_id, completed_by)
values ('99999999-9999-0000-0000-00000000000a', '99999999-9999-0000-0000-0000000000e1', '99999999-9999-0000-0000-000000000001');

-- ---------------------------------------------------------------------------
-- 1. Structure and configuration (rule e)
-- ---------------------------------------------------------------------------
select has_table('public', 'party_emails', 'AMD-20: party_emails log exists');
select is(
  (select value->>'auto_send' from public.system_settings where key = 'party_email.delivery'),
  'OFF', 'AMD-20: auto-send is OFF until enabled in settings'
);
select ok(
  (select value ?& array['subject', 'body', 'cn_line', 'challan_line', 'dispatch_line']
     from public.system_settings where key = 'party_email.template'),
  'DEC-48: the party email template is configuration (subject, body, line templates)'
);

-- ---------------------------------------------------------------------------
-- 2. Source: the completed Accounts entry of the CURRENT slip only
-- ---------------------------------------------------------------------------
select throws_matching(
  $$insert into public.party_emails (gs_id, ac_action_slip_id, trigger_code, email_to, subject, body, snapshot, template_snapshot, requested_by)
    values ('99999999-9999-0000-0000-00000000000b', '99999999-9999-0000-0000-0000000000e2', 'MANUAL', 'p@example.com', 's', 'b', '{}', '{}', '99999999-9999-0000-0000-000000000001')$$,
  'completed Accounts entry of the CURRENT A/c Actions slip',
  'AMD-20: no party email before Accounts completed the entry'
);
select throws_matching(
  $$insert into public.party_emails (gs_id, ac_action_slip_id, trigger_code, email_to, subject, body, snapshot, template_snapshot, requested_by)
    values ('99999999-9999-0000-0000-00000000000b', '99999999-9999-0000-0000-0000000000e1', 'MANUAL', 'p@example.com', 's', 'b', '{}', '{}', '99999999-9999-0000-0000-000000000001')$$,
  'completed Accounts entry of the CURRENT A/c Actions slip',
  'AMD-20: the slip must belong to the same goods slip'
);
select throws_matching(
  $$insert into public.party_emails (gs_id, ac_action_slip_id, trigger_code, email_to, subject, body, snapshot, template_snapshot, status, sent_at, requested_by)
    values ('99999999-9999-0000-0000-00000000000a', '99999999-9999-0000-0000-0000000000e1', 'MANUAL', 'p@example.com', 's', 'b', '{}', '{}', 'SENT', now(), '99999999-9999-0000-0000-000000000001')$$,
  'starts QUEUED',
  'AMD-20: an email cannot be inserted as already SENT'
);
select throws_matching(
  $$insert into public.party_emails (gs_id, ac_action_slip_id, trigger_code, email_to, subject, body, snapshot, template_snapshot, requested_by)
    values ('99999999-9999-0000-0000-00000000000a', '99999999-9999-0000-0000-0000000000e1', 'RESEND', 'p@example.com', 's', 'b', '{}', '{}', '99999999-9999-0000-0000-000000000001')$$,
  'party_emails_resend_link',
  'AMD-20: a resend names the email it repeats'
);
select throws_matching(
  $$insert into public.party_emails (gs_id, ac_action_slip_id, trigger_code, email_to, subject, body, snapshot, template_snapshot, requested_by)
    values ('99999999-9999-0000-0000-00000000000a', '99999999-9999-0000-0000-0000000000e1', 'MANUAL', null, 's', 'b', '{}', '{}', '99999999-9999-0000-0000-000000000001')$$,
  'party_emails_content',
  'AMD-20: an email that may be sent has a recipient'
);
select lives_ok(
  $$insert into public.party_emails (id, gs_id, ac_action_slip_id, trigger_code, email_to, subject, body, snapshot, template_snapshot, requested_by)
    values ('99999999-9999-0000-0000-0000000000c1', '99999999-9999-0000-0000-00000000000a', '99999999-9999-0000-0000-0000000000e1', 'MANUAL', 'Party@Example.com', 'Subject', 'Body', '{"cn_lines": []}', '{}', '99999999-9999-0000-0000-000000000001')$$,
  'A QUEUED party email is accepted for the completed slip'
);

-- ---------------------------------------------------------------------------
-- 3. Frozen content, final status, never deleted (G-18)
-- ---------------------------------------------------------------------------
select throws_matching(
  $$update public.party_emails set body = 'changed' where id = '99999999-9999-0000-0000-0000000000c1'$$,
  'frozen',
  'G-18: recipient and content are frozen at insert'
);
select throws_matching(
  $$update public.party_emails set email_to = 'other@example.com' where id = '99999999-9999-0000-0000-0000000000c1'$$,
  'frozen',
  'G-18: the recipient cannot be changed after insert'
);
select throws_matching(
  $$insert into public.party_notifications (gs_id, channel_code, recipient, message, message_snapshot, delivery_mode, party_email_id, sent_by)
    values ('99999999-9999-0000-0000-00000000000a', 'EMAIL', 'party@example.com', 'm', '{}', 'EMAIL_SENT', '99999999-9999-0000-0000-0000000000c1', '99999999-9999-0000-0000-000000000001')$$,
  'needs a SENT party email',
  'BR-38: an EMAIL_SENT record needs the email to be SENT'
);
select lives_ok(
  $$update public.party_emails set status = 'SENT', attempts = 1, sent_at = now() where id = '99999999-9999-0000-0000-0000000000c1'$$,
  'Delivery marks the QUEUED email SENT'
);
select throws_matching(
  $$update public.party_emails set last_error = 'x' where id = '99999999-9999-0000-0000-0000000000c1'$$,
  'is final',
  'AMD-20: a SENT email is final (resend creates a new email)'
);
select throws_matching(
  $$delete from public.party_emails where id = '99999999-9999-0000-0000-0000000000c1'$$,
  'never deleted',
  'AMD-20: the party email log is never deleted'
);

-- ---------------------------------------------------------------------------
-- 4. PRIOR_INFO_SENT by email (BR-38, DEC-25)
-- ---------------------------------------------------------------------------
select throws_matching(
  $$insert into public.party_notifications (gs_id, channel_code, recipient, message, message_snapshot, delivery_mode, party_email_id, sent_by)
    values ('99999999-9999-0000-0000-00000000000a', 'EMAIL', 'someone.else@example.com', 'm', '{}', 'EMAIL_SENT', '99999999-9999-0000-0000-0000000000c1', '99999999-9999-0000-0000-000000000001')$$,
  'same recipient',
  'BR-38: the EMAIL_SENT record names the recipient the email went to'
);
select throws_matching(
  $$insert into public.party_notifications (gs_id, channel_code, recipient, message, message_snapshot, delivery_mode, sent_by)
    values ('99999999-9999-0000-0000-00000000000a', 'EMAIL', 'party@example.com', 'm', '{}', 'EMAIL_SENT', '99999999-9999-0000-0000-000000000001')$$,
  'party_notifications_email_link',
  'DEC-25: EMAIL_SENT always links its party email (manual records stay RECORDED_MANUALLY)'
);
select lives_ok(
  $$insert into public.party_notifications (gs_id, channel_code, recipient, message, message_snapshot, delivery_mode, party_email_id, sent_by)
    values ('99999999-9999-0000-0000-00000000000a', 'EMAIL', 'party@example.com', 'm', '{}', 'EMAIL_SENT', '99999999-9999-0000-0000-0000000000c1', '99999999-9999-0000-0000-000000000001')$$,
  'A SENT email records PRIOR_INFO_SENT (EMAIL_SENT, recipient case-insensitive)'
);

select * from finish();
rollback;
