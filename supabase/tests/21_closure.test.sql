-- =============================================================================
-- Test File: 21_closure.test.sql
-- P3-07 Party notification & GS closure engine: database half of G-15 / BR-38 / BR-39.
-- No role is involved: these guards hold for any SQL client (CLAUDE.md rule c).
-- =============================================================================

begin;
select plan(15);

select has_table('public', 'party_notifications', 'party_notifications table exists');
select has_table('public', 'gs_closures', 'gs_closures table exists');
select has_function('rms_private', 'gs_closure_checklist', array['uuid'],
  'closure checklist function exists');
select has_trigger('public', 'goods_slips', 'goods_slips_g15_guard', 'G-15 trigger on goods_slips');

-- Fixtures (triggers off while building the state other prompts' engines produce)
set local session_replication_role = replica;

insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data) values
  ('00000000-0000-0000-0000-00000000f701', 'pgtap-p307@example.test',
   '{"rms_activate": true}'::jsonb, '{"full_name": "P307 Test User"}'::jsonb)
on conflict do nothing;
insert into public.profiles (id, full_name, is_active) values
  ('00000000-0000-0000-0000-00000000f701', 'P307 Test User', true)
on conflict do nothing;

insert into public.parties (id, code, name) values
  ('00000000-0000-0000-0000-00000000f702', 'PTY-P307', 'Party P307')
on conflict do nothing;

insert into public.goods_slips (
  id, gs_no, party_id, workflow_version_id, status, delivery_mode_code, courier_name, docket_no,
  box_count, carton_count, category_code, original_category_code, created_by
) values (
  '00000000-0000-0000-0000-00000000f730', 'GS-PGTAP-P307',
  '00000000-0000-0000-0000-00000000f702',
  (select id from public.workflow_versions where status = 'PUBLISHED' limit 1),
  'COMMERCIAL_RESOLUTION', 'COURIER_PARCEL', 'BlueDart', 'DKT-P307', 1, 1, 'RO', 'RO',
  '00000000-0000-0000-0000-00000000f701'
) on conflict do nothing;

insert into public.credit_notes (id, gs_id, cn_type_code, status, cn_no, cn_date, created_by)
values ('00000000-0000-0000-0000-00000000f740', '00000000-0000-0000-0000-00000000f730',
        'GENERAL_CN', 'ISSUED', 'CN-PGTAP-P307', current_date,
        '00000000-0000-0000-0000-00000000f701')
on conflict do nothing;

set local session_replication_role = origin;

select is(
  (select count(*)::int from rms_private.gs_closure_checklist('00000000-0000-0000-0000-00000000f730')),
  15, 'the checklist evaluates 15 items (12 + AC_ENTRY_COMPLETE, DISPATCH_SLIP_DISPATCHED: Phase 8 + NO_PENDING_REACTION: G4)');

-- G-15 / BR-38: an issued CN without a prior party notification blocks closure.
select throws_matching(
  $$ update public.goods_slips set status = 'CLOSED', closure_type = 'RO_CLOSED', closed_at = now()
      where id = '00000000-0000-0000-0000-00000000f730' $$,
  'G-15: .* PRIOR_NOTIFICATION',
  'G-15: closing without PRIOR_INFO_SENT is rejected by the database');

select lives_ok(
  $$ insert into public.party_notifications (id, gs_id, credit_note_id, channel_code, recipient,
       message, message_snapshot, sent_by)
     values ('00000000-0000-0000-0000-00000000f750', '00000000-0000-0000-0000-00000000f730',
             '00000000-0000-0000-0000-00000000f740', 'PHONE', '9810000000', 'CN details',
             '{}'::jsonb, '00000000-0000-0000-0000-00000000f701') $$,
  'BR-38: a notification of an ISSUED CN is recorded');

select throws_matching(
  $$ update public.party_notifications set recipient = 'other'
      where id = '00000000-0000-0000-0000-00000000f750' $$,
  'append-only', 'BR-38: notifications are append-only');

-- Checklist passes, but a closure record is required before the status change.
select throws_matching(
  $$ update public.goods_slips set status = 'CLOSED', closure_type = 'RO_CLOSED', closed_at = now()
      where id = '00000000-0000-0000-0000-00000000f730' $$,
  'closure record', 'G-15: CLOSED needs a matching gs_closures record');

insert into public.gs_closures (gs_id, closure_type, checklist_snapshot, closed_by, closed_at)
values ('00000000-0000-0000-0000-00000000f730', 'RO_CLOSED', '{}'::jsonb,
        '00000000-0000-0000-0000-00000000f701', clock_timestamp());

select throws_matching(
  $$ update public.goods_slips set status = 'CLOSED', closure_type = 'CSR_CLOSED', closed_at = now()
      where id = '00000000-0000-0000-0000-00000000f730' $$,
  'G-15: .* must close as RO_CLOSED', 'BR-39: an RO GS cannot close as CSR_CLOSED');

select lives_ok(
  $$ update public.goods_slips set status = 'CLOSED', closure_type = 'RO_CLOSED', closed_at = now()
      where id = '00000000-0000-0000-0000-00000000f730' $$,
  'G-15: closes once the checklist passes and the closure record exists');

select throws_matching(
  $$ update public.goods_slips set status = 'COMMERCIAL_RESOLUTION'
      where id = '00000000-0000-0000-0000-00000000f730' $$,
  'G-15: .* only a Super Admin reopen', 'a CLOSED GS cannot leave CLOSED without a reopen');

select throws_matching(
  $$ update public.gs_closures set reopened_by = '00000000-0000-0000-0000-00000000f701',
       reopened_at = clock_timestamp(), reopen_reason = 'test'
      where gs_id = '00000000-0000-0000-0000-00000000f730' $$,
  'Super Admin', 'only an active Super Admin can record a reopen');

select throws_matching(
  $$ delete from public.gs_closures where gs_id = '00000000-0000-0000-0000-00000000f730' $$,
  'never deleted', 'closure records are never deleted');

select throws_matching(
  $$ insert into public.party_notifications (gs_id, credit_note_id, channel_code, recipient,
       message, message_snapshot, sent_by)
     values ('00000000-0000-0000-0000-00000000f730', '00000000-0000-0000-0000-00000000f740',
             'OTHER', 'x', 'x', '{}'::jsonb, '00000000-0000-0000-0000-00000000f701') $$,
  'BR-38: .* CLOSED GS', 'no notification is recorded on a closed GS');

select * from finish();
rollback;
