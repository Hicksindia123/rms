-- Gap plan G4 (migration 20261118000300; DEC-57; Q9–Q12; Guards G-15, G-20, G-21, G-22).
-- Final actions per item + current condition; Pending re-action rounds; where the pieces of each
-- action go (setting); closure: Rejected Hold via the A/c flow is accounted, NO_PENDING_REACTION.

begin;
select plan(27);

insert into auth.users (id, email)
values ('44444444-4444-0000-0000-000000000001', 'g4_rm@example.com')
on conflict do nothing;
insert into public.profiles (id, full_name, is_active)
values ('44444444-4444-0000-0000-000000000001', 'G4 RM', true)
on conflict do nothing;

-- Scenario: GS held; item 1 = 10 pcs split C1 7 / C2 3; item 2 = 3 pcs without a split.
do $$
declare
  v_prod  record;
begin
  set local session_replication_role = 'replica';

  select pr.id, pr.category_id into v_prod
    from public.products pr
    join public.product_categories c on c.id = pr.category_id and c.code = 'DMT'
   where (select count(*) from rms_private.resolve_item_field_profile(pr.id) r
           where r.field_group = 'CATEGORISATION') >= 2
     and (select count(*) from rms_private.resolve_item_field_profile(pr.id) r
           where r.field_group = 'ACTION' and r.code in ('SEND_NEW', 'ISSUE_CN', 'NOT_ALLOWED', 'PENDING_BP')) = 4
   limit 1;

  insert into public.goods_slips (
    id, gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count, box_count, status
  )
  select '44444444-0000-0000-0000-00000000000a', 'GS/TEST/G4/A', v.id, 'COURIER_PARCEL', 'Test Courier', '123', 1, 1,
         'HELD_AT_INTERMEDIATE_STORE'
    from public.workflow_versions v
    join public.workflow_definitions d on d.id = v.workflow_definition_id and d.code = 'RMS_STANDARD'
   where v.status = 'PUBLISHED' limit 1;

  insert into public.gs_items (id, gs_id, line_no, product_id, category_id, documented_qty, received_qty)
  values ('44444444-0000-0000-0000-0000000000a1', '44444444-0000-0000-0000-00000000000a', 1, v_prod.id, v_prod.category_id, 10, 10),
         ('44444444-0000-0000-0000-0000000000a2', '44444444-0000-0000-0000-00000000000a', 2, v_prod.id, v_prod.category_id, 3, 3);

  insert into public.gs_item_buckets (gs_item_id, field_id, field_code, label_snapshot, qty)
  select '44444444-0000-0000-0000-0000000000a1', r.field_id, r.code, r.label,
         case when r.rn = 1 then 7 else 3 end
    from (select r.field_id, r.code, r.label, row_number() over (order by r.sort_order, r.code) as rn
            from rms_private.resolve_item_field_profile(v_prod.id) r
           where r.field_group = 'CATEGORISATION') r
   where r.rn <= 2;

  set local session_replication_role = 'origin';
end;
$$;

create temp table g4 as
select (select field_id from public.gs_item_buckets where gs_item_id = '44444444-0000-0000-0000-0000000000a1' and qty = 7) as c1,
       (select field_id from public.gs_item_buckets where gs_item_id = '44444444-0000-0000-0000-0000000000a1' and qty = 3) as c2,
       (select id from public.item_field_library where field_group = 'ACTION' limit 1) as not_a_condition,
       '44444444-4444-0000-0000-000000000001'::uuid as rm;
grant select on g4 to public;

-- ---------------------------------------------------------------------------
-- 1. Schema + configuration (Q10–Q12)
-- ---------------------------------------------------------------------------
select has_column('public', 'rm_item_actions', 'round_no', 'rm_item_actions.round_no exists');
select has_column('public', 'rm_item_actions', 'condition_field_id', 'rm_item_actions.condition_field_id exists');
select has_column('public', 'ac_action_slips', 'round_no', 'ac_action_slips.round_no exists');
select has_column('public', 'ac_entry_lines', 'condition_label', 'ac_entry_lines.condition_label exists');
select results_eq(
  $$select value->>'PENDING_BP', value->>'NOT_ALLOWED', value->>'SEND_NEW', value->>'SEND_REPAIRED', value->>'ISSUE_CN'
      from public.system_settings where key = 'dispatch.returned_goods_location_by_action'$$,
  $$values ('PENDING_HOLD'::text, 'REJECTED_HOLD'::text, 'NON_FUNCTIONAL_STORE'::text, 'DISPATCHED'::text, 'CREDITED'::text)$$,
  'Pending -> Pending Hold, Not Allowed -> Rejected Hold, Send New -> Non-Functional Store (DEC-57)');
select is(
  (select label from public.item_field_library where field_group = 'ACTION' and code = 'PENDING_BP'),
  'Pending', 'action PENDING_BP is labelled "Pending" (code unchanged)');

-- ---------------------------------------------------------------------------
-- 2. G-21 per condition: the rm_item_actions guard (Q9)
-- ---------------------------------------------------------------------------
select throws_matching(
  $$insert into public.rm_item_actions (gs_item_id, revision_no, action_code, qty, decided_by)
    select '44444444-0000-0000-0000-0000000000a1', 1, 'SEND_NEW', 10, rm from g4$$,
  'G-21: item line 1 has a condition split; every final action names its condition',
  'G-21: an item with a condition split is actioned per condition');
select throws_matching(
  $$insert into public.rm_item_actions (gs_item_id, revision_no, condition_field_id, action_code, qty, decided_by)
    select '44444444-0000-0000-0000-0000000000a1', 1, not_a_condition, 'SEND_NEW', 1, rm from g4$$,
  'G-21: item line 1: the condition is not in the item''s current condition split',
  'G-21: the condition must be one of the item''s current conditions');
select throws_matching(
  $$insert into public.rm_item_actions (gs_item_id, revision_no, condition_field_id, action_code, qty, decided_by)
    select '44444444-0000-0000-0000-0000000000a2', 1, c1, 'ISSUE_CN', 3, rm from g4$$,
  'G-21: item line 2 has no condition split; its final actions name no condition',
  'G-21: an item without a split names no condition');
select throws_matching(
  $$insert into public.rm_item_actions (gs_item_id, revision_no, round_no, condition_field_id, action_code, qty, decided_by)
    select '44444444-0000-0000-0000-0000000000a1', 1, 2, c1, 'ISSUE_CN', 1, rm from g4$$,
  'G-21: Pending pieces are re-actioned only while the goods slip is open after the store stage',
  'G-21: no re-action round while round 1 is still at the store stage');

-- Item total right (8 + 2 = 10) but C1 has only 7 pcs: the split check rejects it.
select throws_matching(
  $q$do $x$ begin
      insert into public.rm_item_actions (gs_item_id, revision_no, condition_field_id, action_code, qty, decided_by)
      select '44444444-0000-0000-0000-0000000000a1', 1, v.cond, 'SEND_NEW', v.qty, g4.rm
        from g4, lateral (values (g4.c1, 8), (g4.c2, 2)) as v(cond, qty);
      insert into public.rm_item_actions (gs_item_id, revision_no, action_code, qty, decided_by)
      select '44444444-0000-0000-0000-0000000000a2', 1, 'ISSUE_CN', 3, rm from g4;
      perform rms_private.validate_final_action_split('44444444-0000-0000-0000-00000000000a', false);
    end $x$ $q$,
  'G-21: item line 1 .* condition .*: action qty \(8\) exceeds the qty available in that condition \(7\)',
  'G-21: no condition gets more actions than it has (per-item total alone is not enough)');

-- The round-1 decision: C1 Send New 5 + Pending 2, C2 Not Allowed 3; item 2 Issue CN 3.
select lives_ok(
  $q$do $x$ begin
      insert into public.rm_item_actions (gs_item_id, revision_no, condition_field_id, action_code, qty, decided_by)
      select '44444444-0000-0000-0000-0000000000a1', 1, v.cond, v.code, v.qty, g4.rm
        from g4, lateral (values (g4.c1, 'SEND_NEW', 5), (g4.c1, 'PENDING_BP', 2), (g4.c2, 'NOT_ALLOWED', 3)) as v(cond, code, qty);
      insert into public.rm_item_actions (gs_item_id, revision_no, action_code, qty, decided_by)
      select '44444444-0000-0000-0000-0000000000a2', 1, 'ISSUE_CN', 3, rm from g4;
      perform rms_private.validate_final_action_split('44444444-0000-0000-0000-00000000000a', false);
    end $x$ $q$,
  'a split that allocates every condition exactly is accepted');
select is(
  (select count(*)::int from public.rm_item_actions
    where gs_item_id = '44444444-0000-0000-0000-0000000000a1' and is_current
      and condition_code is not null and condition_label is not null),
  3, 'G-18: every action of item 1 carries its condition code / label snapshot');
select results_eq(
  $$select line_no, current_qty, available_qty, actioned_qty
      from rms_private.final_action_condition_quantities('44444444-0000-0000-0000-00000000000a')
     order by line_no, current_qty desc$$,
  $$values (1, 7, 7, 7), (1, 3, 3, 3), (2, 3, 3, 3)$$,
  'per item + condition quantities (item 2: one group without a condition)');
select is(rms_private.final_action_pending_qty('44444444-0000-0000-0000-00000000000a', 1), 2,
  'round 1 leaves 2 pcs Pending');

-- ---------------------------------------------------------------------------
-- 3. Round 1 finalised + completed + settled (data set up directly; the services do this)
-- ---------------------------------------------------------------------------
do $$
begin
  set local session_replication_role = 'replica';
  insert into public.attachments (id, gs_id, entity_type, entity_id, kind, bucket, object_path, mime_type, size_bytes, status, uploaded_by, confirmed_by, confirmed_at)
  values ('44444444-0000-0000-0000-0000000000f1', '44444444-0000-0000-0000-00000000000a', 'ac_action_slips',
          '44444444-0000-0000-0000-0000000000e1', 'GENERATED_PDF', 'rms-documents', 'gs/44444444-0000-0000-0000-00000000000a/generated_pdf/44444444-0000-0000-0000-0000000000f1.pdf', 'application/pdf', 10,
          'CONFIRMED', '44444444-4444-0000-0000-000000000001', '44444444-4444-0000-0000-000000000001', now());
  insert into public.ac_action_slips (id, gs_id, slip_no, version_no, revision_no, round_no, attachment_id,
                                      template_version_no, content, totals, sha256, finalised_by)
  values ('44444444-0000-0000-0000-0000000000e1', '44444444-0000-0000-0000-00000000000a', 'AS/TEST/G4', 1, 1, 1,
          '44444444-0000-0000-0000-0000000000f1', 1, '{}', '{}', repeat('a', 64), '44444444-4444-0000-0000-000000000001');
  insert into public.ac_entry_completions (gs_id, ac_action_slip_id, completed_by)
  values ('44444444-0000-0000-0000-00000000000a', '44444444-0000-0000-0000-0000000000e1', '44444444-4444-0000-0000-000000000001');
  update public.goods_slips set status = 'IN_PROCESS' where id = '44444444-0000-0000-0000-00000000000a';
  set local session_replication_role = 'origin';
end;
$$;

select ok(rms_private.final_action_round_settled('44444444-0000-0000-0000-00000000000a', 1),
  'round 1 is settled (completed, no READY Dispatch Slip)');
select throws_matching(
  $$update public.rm_item_actions set is_current = false
     where gs_item_id = '44444444-0000-0000-0000-0000000000a2' and round_no = 1$$,
  'G-21', 'G-21: round-1 actions are frozen once the goods slip left the store stage');

-- ---------------------------------------------------------------------------
-- 4. Pending re-action round 2 (Q10)
-- ---------------------------------------------------------------------------
select throws_matching(
  $q$do $x$ begin
      insert into public.rm_item_actions (gs_item_id, revision_no, round_no, condition_field_id, action_code, qty, decided_by)
      select '44444444-0000-0000-0000-0000000000a1', 2, 2, c1, 'ISSUE_CN', 1, rm from g4;
      perform rms_private.validate_final_action_split('44444444-0000-0000-0000-00000000000a', false);
    end $x$ $q$,
  'G-21: re-action round 2: item line 1 must re-action exactly the 2 Pending pc\(s\) of condition',
  'G-21: a re-action round covers exactly the pieces left Pending');
select throws_matching(
  $$insert into public.rm_item_actions (gs_item_id, revision_no, round_no, condition_field_id, action_code, qty, decided_by)
    select '44444444-0000-0000-0000-0000000000a1', 2, 3, c1, 'ISSUE_CN', 2, rm from g4$$,
  'G-21: round 2 is not completed by Accounts and settled yet',
  'G-21: rounds follow each other (no round 3 before round 2 settled)');
select lives_ok(
  $q$do $x$ begin
      insert into public.rm_item_actions (gs_item_id, revision_no, round_no, condition_field_id, action_code, qty, decided_by)
      select '44444444-0000-0000-0000-0000000000a1', 2, 2, c1, 'ISSUE_CN', 2, rm from g4;
      perform rms_private.validate_final_action_split('44444444-0000-0000-0000-00000000000a', false);
      perform rms_private.validate_department_reconciliation('44444444-0000-0000-0000-00000000000a');
    end $x$ $q$,
  'round 2 re-actions the 2 Pending pcs (G-20 counts round 1 only, no double count)');
select is(
  (select actioned_qty from rms_private.final_action_item_quantities('44444444-0000-0000-0000-00000000000a') where line_no = 1),
  10, 'item quantities count round 1 only');

-- ---------------------------------------------------------------------------
-- 5. Closure checklist (G-15, Q10, Q11)
-- ---------------------------------------------------------------------------
-- Stock: C2's 3 pcs moved to the Rejected Hold by the A/c flow; 2 pcs in the Pending Hold.
do $$
declare
  v_lot uuid := '44444444-0000-0000-0000-0000000000b1';
  v_si  uuid;
begin
  set local session_replication_role = 'replica';
  insert into public.stock_items (item_kind, product_id)
  select 'FINISHED_GOOD', product_id from public.gs_items where id = '44444444-0000-0000-0000-0000000000a1'
  returning id into v_si;
  insert into public.stock_lots (id, stock_item_id, gs_id, gs_item_id, condition_class)
  values (v_lot, v_si, '44444444-0000-0000-0000-00000000000a', '44444444-0000-0000-0000-0000000000a1', 'AS_RECEIVED');
  insert into public.stock_balances (lot_id, location_id, qty)
  select v_lot, id, case code when 'REJECTED_HOLD' then 3 else 2 end
    from public.inventory_locations where code in ('REJECTED_HOLD', 'PENDING_HOLD');
  insert into public.stock_movements (movement_type, lot_id, from_location_id, to_location_id, qty, reference_type, reference_id, idempotency_key)
  select 'ISSUE', v_lot, (select id from public.inventory_locations where code = 'INTERMEDIATE_STORE'), loc.id, 3,
         'ac_action_slips', '44444444-0000-0000-0000-0000000000e1', 'g4-test-rejected'
    from public.inventory_locations loc where loc.code = 'REJECTED_HOLD';
  set local session_replication_role = 'origin';
end;
$$;

select is(
  (select passed from rms_private.gs_closure_checklist('44444444-0000-0000-0000-00000000000a') where code = 'STOCK_ACCOUNTED'),
  true, 'Q11: pieces the A/c flow moved to the Rejected Hold are accounted');
select is(
  (select passed from rms_private.gs_closure_checklist('44444444-0000-0000-0000-00000000000a') where code = 'STOCK_NOT_IN_TRANSIT'),
  false, 'Q10: pieces in the Pending Hold keep the goods slip open');
select results_eq(
  $$select applicable, passed, (details->>'pending_qty')::int
      from rms_private.gs_closure_checklist('44444444-0000-0000-0000-00000000000a') where code = 'NO_PENDING_REACTION'$$,
  $$values (true, true, 0)$$,
  'NO_PENDING_REACTION passes once the last round re-actioned every Pending piece');
select is(
  (select passed from rms_private.gs_closure_checklist('44444444-0000-0000-0000-00000000000a') where code = 'AC_ENTRY_COMPLETE'),
  false, 'AC_ENTRY_COMPLETE: round 2 has no completed slip yet');

-- Round 2 re-actions the Pending pieces as Pending again: NO_PENDING_REACTION fails.
update public.rm_item_actions set is_current = false
 where gs_item_id = '44444444-0000-0000-0000-0000000000a1' and round_no = 2;
insert into public.rm_item_actions (gs_item_id, revision_no, round_no, condition_field_id, action_code, qty, decided_by)
select '44444444-0000-0000-0000-0000000000a1', 3, 2, c1, 'PENDING_BP', 2, rm from g4;
select results_eq(
  $$select passed, (details->>'pending_qty')::int
      from rms_private.gs_closure_checklist('44444444-0000-0000-0000-00000000000a') where code = 'NO_PENDING_REACTION'$$,
  $$values (false, 2)$$,
  'NO_PENDING_REACTION fails while the last round still has Pending pieces');

-- Rejected Hold stock without an A/c flow movement or a rejection stays unaccounted (unchanged rule).
do $$
begin
  set local session_replication_role = 'replica';
  delete from public.stock_movements where idempotency_key = 'g4-test-rejected';
  set local session_replication_role = 'origin';
end;
$$;
select is(
  (select passed from rms_private.gs_closure_checklist('44444444-0000-0000-0000-00000000000a') where code = 'STOCK_ACCOUNTED'),
  false, 'Rejected Hold stock not placed by the A/c flow (and no rejection) is not accounted');

select * from finish();
rollback;
