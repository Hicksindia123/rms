-- Change plan 2026-11-12 · Phase 8 (migration 20261114000100): Accounts entry & Dispatch Slip.
-- G-22 (AMD-18 / AMD-19): entry lines are created from the finalised slip with the action flags
-- snapshotted; fields only where a flag requires them; completion only when every line is
-- complete; frozen afterwards; the Dispatch Slip lists exactly the goods-shipping lines and goes
-- READY -> DISPATCHED once; the A/c Actions slip cannot be superseded after completion; the P3-05
-- replacement dispatch refuses goods slips on the A/c Actions flow. DEC-22: CN No. per goods slip.
-- G-15: closure checklist rows for the A/c Actions flow.

begin;
select plan(27);

insert into auth.users (id, email)
values ('88888888-8888-0000-0000-000000000001', 'ph8_user@example.com')
on conflict do nothing;
insert into public.profiles (id, full_name, is_active)
values ('88888888-8888-0000-0000-000000000001', 'Ph8 User', true)
on conflict do nothing;

-- GS A (10 pcs: 6 Send New / 3 Send Repaired / 1 Issue CN) and B (4 pcs: Issue CN), both held at
-- the intermediate store with finalised slips.
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
    ('88888888-8888-0000-0000-00000000000a', 'GS/TEST/PH8/A', v_wf, 'COURIER_PARCEL', 'C', '1', 1, 1, 'HELD_AT_INTERMEDIATE_STORE'),
    ('88888888-8888-0000-0000-00000000000b', 'GS/TEST/PH8/B', v_wf, 'COURIER_PARCEL', 'C', '1', 1, 1, 'HELD_AT_INTERMEDIATE_STORE');

  insert into public.gs_items (id, gs_id, line_no, product_id, category_id, documented_qty, received_qty)
  select i.id, i.gs_id, 1, p.id, p.category_id, i.qty, i.qty
    from (values
      ('88888888-8888-0000-0000-0000000000a1'::uuid, '88888888-8888-0000-0000-00000000000a'::uuid, 10),
      ('88888888-8888-0000-0000-0000000000b1'::uuid, '88888888-8888-0000-0000-00000000000b'::uuid, 4)
    ) as i(id, gs_id, qty)
    cross join lateral (
      select pr.id, pr.category_id from public.products pr
        join public.product_categories c on c.id = pr.category_id and c.code = 'DMT'
       order by pr.code limit 1
    ) p;

  insert into public.attachments (id, gs_id, entity_type, kind, bucket, object_path, mime_type, size_bytes, status, confirmed_at)
  values
    ('88888888-8888-0000-0000-0000000000f1', '88888888-8888-0000-0000-00000000000a', 'ac_action_slips', 'GENERATED_PDF',
     'rms-documents', 'gs/88888888-8888-0000-0000-00000000000a/generated_pdf/88888888-8888-4000-8000-0000000000f1.pdf',
     'application/pdf', 1000, 'CONFIRMED', now()),
    ('88888888-8888-0000-0000-0000000000f2', '88888888-8888-0000-0000-00000000000b', 'ac_action_slips', 'GENERATED_PDF',
     'rms-documents', 'gs/88888888-8888-0000-0000-00000000000b/generated_pdf/88888888-8888-4000-8000-0000000000f2.pdf',
     'application/pdf', 1000, 'CONFIRMED', now()),
    ('88888888-8888-0000-0000-0000000000f3', '88888888-8888-0000-0000-00000000000a', 'dispatch_slips', 'GENERATED_PDF',
     'rms-documents', 'gs/88888888-8888-0000-0000-00000000000a/generated_pdf/88888888-8888-4000-8000-0000000000f3.pdf',
     'application/pdf', 1000, 'CONFIRMED', now());
  set local session_replication_role = 'origin';
end;
$$;

insert into public.rm_item_actions (gs_item_id, revision_no, action_code, qty, decided_by)
values ('88888888-8888-0000-0000-0000000000a1', 1, 'SEND_NEW', 6, '88888888-8888-0000-0000-000000000001'),
       ('88888888-8888-0000-0000-0000000000a1', 1, 'SEND_REPAIRED', 3, '88888888-8888-0000-0000-000000000001'),
       ('88888888-8888-0000-0000-0000000000a1', 1, 'ISSUE_CN', 1, '88888888-8888-0000-0000-000000000001'),
       ('88888888-8888-0000-0000-0000000000b1', 1, 'ISSUE_CN', 4, '88888888-8888-0000-0000-000000000001');

insert into public.ac_action_slips (id, gs_id, slip_no, version_no, revision_no, attachment_id, template_version_no, content, totals, sha256, finalised_by)
values ('88888888-8888-0000-0000-0000000000e1', '88888888-8888-0000-0000-00000000000a', 'RSA/TEST/PH8/A', 1, 1, '88888888-8888-0000-0000-0000000000f1', 1, '{}', '{}', repeat('a', 64), '88888888-8888-0000-0000-000000000001'),
       ('88888888-8888-0000-0000-0000000000e2', '88888888-8888-0000-0000-00000000000b', 'RSA/TEST/PH8/B', 1, 1, '88888888-8888-0000-0000-0000000000f2', 1, '{}', '{}', repeat('a', 64), '88888888-8888-0000-0000-000000000001');

-- ---------------------------------------------------------------------------
-- 1. Catalogue / structure
-- ---------------------------------------------------------------------------
select ok(
  (select 'G-22' ~ (regexp_match(pg_get_constraintdef(oid), '''(.*)'''))[1]
     from pg_constraint where conname = 'system_guard_events_guard_code_check'),
  'system_guard_events accepts G-22'
);
select ok(
  exists (select 1 from public.print_templates where code = 'DISPATCH_SLIP' and status = 'PUBLISHED')
  and exists (select 1 from public.number_series where code = 'DISPATCH_SLIP'),
  'DISPATCH_SLIP template is published and the DISPATCH_SLIP number series exists (DEC-41)'
);
select ok(
  (select value ? 'SEND_REPAIRED' from public.system_settings where key = 'dispatch.returned_goods_location_by_action'),
  'DEC-47 setting dispatch.returned_goods_location_by_action is seeded (keyed by action codes)'
);
select ok(
  (select tgdeferrable and tginitdeferred from pg_trigger where tgname = 'dispatch_slips_coverage'),
  'Dispatch Slip coverage check is a deferred constraint trigger'
);

-- ---------------------------------------------------------------------------
-- 2. Entry lines created on finalise with flag snapshots (AMD-18, G-18)
-- ---------------------------------------------------------------------------
select is(
  (select count(*)::int from public.ac_entry_lines where ac_action_slip_id = '88888888-8888-0000-0000-0000000000e1'),
  3, 'Finalising creates one entry line per current action line'
);
select results_eq(
  $$select action_code, requires_cn, requires_challan from public.ac_entry_lines
     where ac_action_slip_id = '88888888-8888-0000-0000-0000000000e1' order by action_code$$,
  $$values ('ISSUE_CN'::text, true, false), ('SEND_NEW'::text, false, true), ('SEND_REPAIRED'::text, false, true)$$,
  'AMD-18: requires_cn / requires_challan are copied from the ACTION library flags'
);

-- ---------------------------------------------------------------------------
-- 3. G-22 on entry lines
-- ---------------------------------------------------------------------------
select throws_matching(
  $$update public.ac_entry_lines set cn_no = 'CN1', cn_date = current_date, cn_value = 10
     where ac_action_slip_id = '88888888-8888-0000-0000-0000000000e1' and action_code = 'SEND_NEW'$$,
  'ac_entry_lines_cn_fields',
  'AMD-18: CN fields on an action without requires_cn are rejected'
);
select throws_matching(
  $$update public.ac_entry_lines set cn_no = 'CN1'
     where ac_action_slip_id = '88888888-8888-0000-0000-0000000000e1' and action_code = 'ISSUE_CN'$$,
  'ac_entry_lines_cn_fields',
  'AMD-18: CN No., Date and Value are entered together'
);
select throws_matching(
  $$update public.ac_entry_lines set challan_no = 'CH1', challan_date = current_date + 1
     where ac_action_slip_id = '88888888-8888-0000-0000-0000000000e1' and action_code = 'SEND_NEW'$$,
  'G-22: CN / Challan dates cannot be in the future',
  'G-22: future dates are rejected'
);
select throws_matching(
  $$update public.ac_entry_lines set qty = 99
     where ac_action_slip_id = '88888888-8888-0000-0000-0000000000e1' and action_code = 'SEND_NEW'$$,
  'G-22: only the Accounts fields',
  'G-22: only the Accounts fields of an entry line change'
);
select throws_matching(
  $$delete from public.ac_entry_lines where ac_action_slip_id = '88888888-8888-0000-0000-0000000000e1'$$,
  'G-22: Accounts entry lines are never deleted',
  'G-22: entry lines are never deleted'
);
select throws_matching(
  $$insert into public.ac_entry_completions (gs_id, ac_action_slip_id, completed_by)
    values ('88888888-8888-0000-0000-00000000000a', '88888888-8888-0000-0000-0000000000e1', '88888888-8888-0000-0000-000000000001')$$,
  'G-22: item line 1 .* still needs its Accounts data',
  'G-22: completion is rejected while a line misses its data'
);
select lives_ok(
  $$update public.ac_entry_lines
       set cn_no = 'CN-PH8-1', cn_date = current_date, cn_value = 125.50
     where ac_action_slip_id = '88888888-8888-0000-0000-0000000000e1' and action_code = 'ISSUE_CN'$$,
  'Accounts enters CN No./Date/Value on the Issue CN line'
);
select throws_matching(
  $$update public.ac_entry_lines set cn_no = 'cn-ph8-1', cn_date = current_date, cn_value = 5
     where ac_action_slip_id = '88888888-8888-0000-0000-0000000000e2'$$,
  'G-22: CN No. cn-ph8-1 is already recorded on goods slip GS/TEST/PH8/A',
  'DEC-22: a CN No. belongs to one goods slip (case-insensitive)'
);
select lives_ok(
  $$update public.ac_entry_lines set challan_no = 'CH-PH8-' || action_code, challan_date = current_date
     where ac_action_slip_id = '88888888-8888-0000-0000-0000000000e1' and requires_challan$$,
  'Accounts enters Challan No./Date on the Send New / Send Repaired lines'
);

-- ---------------------------------------------------------------------------
-- 4. Completion, Dispatch Slip
-- ---------------------------------------------------------------------------
select throws_matching(
  $$insert into public.dispatch_slips (gs_id, ac_action_slip_id, slip_no, attachment_id, template_version_no, content, sha256, generated_by)
    values ('88888888-8888-0000-0000-00000000000a', '88888888-8888-0000-0000-0000000000e1', 'DS/TEST/PH8/1', '88888888-8888-0000-0000-0000000000f3', 1, '{}', repeat('a', 64), '88888888-8888-0000-0000-000000000001')$$,
  'G-22: a Dispatch Slip is generated only after Accounts completed',
  'G-22: no Dispatch Slip before completion'
);
select lives_ok(
  $$insert into public.ac_entry_completions (gs_id, ac_action_slip_id, completed_by)
    values ('88888888-8888-0000-0000-00000000000a', '88888888-8888-0000-0000-0000000000e1', '88888888-8888-0000-0000-000000000001')$$,
  'Completion is accepted once every line is complete'
);
select throws_matching(
  $$update public.ac_entry_lines set challan_no = 'OTHER'
     where ac_action_slip_id = '88888888-8888-0000-0000-0000000000e1' and action_code = 'SEND_NEW'$$,
  'G-22: the Accounts entry of this slip is complete and frozen',
  'G-22: entries are frozen after completion'
);
select throws_matching(
  $$update public.ac_action_slips set status = 'SUPERSEDED', superseded_at = now(),
           superseded_by = '88888888-8888-0000-0000-000000000001', supersede_reason = 'late change'
     where id = '88888888-8888-0000-0000-0000000000e1'$$,
  'G-22: Accounts completed A/c Actions slip RSA/TEST/PH8/A v1',
  'G-22: the A/c Actions slip cannot be superseded after completion'
);

select throws_matching(
  $t$do $x$ begin
      insert into public.dispatch_slips (id, gs_id, ac_action_slip_id, slip_no, attachment_id, template_version_no, content, sha256, generated_by)
      values ('88888888-8888-0000-0000-0000000000d1', '88888888-8888-0000-0000-00000000000a', '88888888-8888-0000-0000-0000000000e1', 'DS/TEST/PH8/1', '88888888-8888-0000-0000-0000000000f3', 1, '{}', repeat('a', 64), '88888888-8888-0000-0000-000000000001');
      insert into public.dispatch_slip_lines (dispatch_slip_id, ac_entry_line_id, gs_item_id, line_no, action_code, action_label, qty, challan_no, challan_date)
      select '88888888-8888-0000-0000-0000000000d1', e.id, e.gs_item_id, e.line_no, e.action_code, e.action_label, e.qty, e.challan_no, e.challan_date
        from public.ac_entry_lines e
       where e.ac_action_slip_id = '88888888-8888-0000-0000-0000000000e1' and e.action_code = 'SEND_NEW';
      set constraints public.dispatch_slips_coverage immediate;
    end $x$$t$,
  'G-22: the Dispatch Slip must list every goods-shipping action line \(1 missing',
  'G-22: a Dispatch Slip missing a shipping line is rejected (deferred coverage check)'
);
select throws_matching(
  $t$do $x$ begin
      insert into public.dispatch_slips (id, gs_id, ac_action_slip_id, slip_no, attachment_id, template_version_no, content, sha256, generated_by)
      values ('88888888-8888-0000-0000-0000000000d1', '88888888-8888-0000-0000-00000000000a', '88888888-8888-0000-0000-0000000000e1', 'DS/TEST/PH8/1', '88888888-8888-0000-0000-0000000000f3', 1, '{}', repeat('a', 64), '88888888-8888-0000-0000-000000000001');
      insert into public.dispatch_slip_lines (dispatch_slip_id, ac_entry_line_id, gs_item_id, line_no, action_code, action_label, qty, challan_no, challan_date)
      select '88888888-8888-0000-0000-0000000000d1', e.id, e.gs_item_id, e.line_no, e.action_code, e.action_label, e.qty, e.challan_no, e.challan_date
        from public.ac_entry_lines e
       where e.ac_action_slip_id = '88888888-8888-0000-0000-0000000000e1' and e.action_code = 'ISSUE_CN';
    end $x$$t$,
  'G-22: a Dispatch Slip line must be a goods-shipping action line',
  'G-22: a non-shipping line cannot be put on the Dispatch Slip'
);
select lives_ok(
  $t$do $x$ begin
      insert into public.dispatch_slips (id, gs_id, ac_action_slip_id, slip_no, attachment_id, template_version_no, content, sha256, generated_by)
      values ('88888888-8888-0000-0000-0000000000d1', '88888888-8888-0000-0000-00000000000a', '88888888-8888-0000-0000-0000000000e1', 'DS/TEST/PH8/1', '88888888-8888-0000-0000-0000000000f3', 1, '{}', repeat('a', 64), '88888888-8888-0000-0000-000000000001');
      insert into public.dispatch_slip_lines (dispatch_slip_id, ac_entry_line_id, gs_item_id, line_no, action_code, action_label, qty, challan_no, challan_date)
      select '88888888-8888-0000-0000-0000000000d1', e.id, e.gs_item_id, e.line_no, e.action_code, e.action_label, e.qty, e.challan_no, e.challan_date
        from public.ac_entry_lines e
       where e.ac_action_slip_id = '88888888-8888-0000-0000-0000000000e1' and e.requires_challan;
      set constraints public.dispatch_slips_coverage immediate;
      set constraints public.dispatch_slips_coverage deferred;
    end $x$$t$,
  'A Dispatch Slip listing every shipping line is accepted'
);
select throws_matching(
  $$update public.dispatch_slips set status = 'DISPATCHED', dispatch_date = current_date, transporter = 'X',
           dispatched_by = '88888888-8888-0000-0000-000000000001', dispatched_at = now()
     where id = '88888888-8888-0000-0000-0000000000d1'$$,
  'dispatch_slips_dispatched_fields',
  'DEC-26: dispatching needs a docket or vehicle number'
);
select lives_ok(
  $$update public.dispatch_slips set status = 'DISPATCHED', dispatch_date = current_date, transporter = 'Blue Dart',
           docket_no = 'BD1', dispatched_by = '88888888-8888-0000-0000-000000000001', dispatched_at = now()
     where id = '88888888-8888-0000-0000-0000000000d1'$$,
  'READY -> DISPATCHED with date, transporter and docket'
);
select throws_matching(
  $$update public.dispatch_slips set docket_no = 'BD2' where id = '88888888-8888-0000-0000-0000000000d1'$$,
  'G-22: a Dispatch Slip is immutable',
  'G-22: a dispatched slip is final'
);

-- ---------------------------------------------------------------------------
-- 5. P3-05 path closed for the A/c Actions flow; closure checklist rows (G-15)
-- ---------------------------------------------------------------------------
select throws_matching(
  $$insert into public.replacement_dispatches (dispatch_no, gs_id, dispatch_type, transporter)
    values ('DSP/TEST/PH8', '88888888-8888-0000-0000-00000000000b', 'SEND_NEW', 'X')$$,
  'G-22: goods slip on the A/c Actions flow ships only against its Dispatch Slip',
  'G-22: the P3-05 replacement dispatch refuses a goods slip on the A/c Actions flow'
);
select results_eq(
  $$select code, applicable, passed from rms_private.gs_closure_checklist('88888888-8888-0000-0000-00000000000a')
     where code in ('CN_DECISION_RECORDED', 'AC_ENTRY_COMPLETE', 'DISPATCH_SLIP_DISPATCHED', 'CSR_CN_ISSUED')
     order by sort_order$$,
  $$values ('CN_DECISION_RECORDED'::text, false, true), ('AC_ENTRY_COMPLETE'::text, true, true),
           ('DISPATCH_SLIP_DISPATCHED'::text, true, true), ('CSR_CN_ISSUED'::text, false, true)$$,
  'G-15 checklist on the A/c Actions flow: Accounts complete and Dispatch Slip dispatched; no NULL rows'
);

select * from finish();
rollback;
