-- Change plan 2026-11-12 · Phase 7 (migration 20261113001100): RM final actions, A/c Actions slip.
-- G-21 (AMD-16 / AMD-17): Σ action qty = qty available for action (counted - at departments),
-- actions only from the resolved ACTION profile, finalise only with nothing at a department,
-- finalised slip freezes the actions and is immutable / never deleted.
-- G-20 fix-forward: actioned pieces come out of the outcome heads first (no double count).

begin;
select plan(24);

insert into auth.users (id, email)
values ('77777777-7777-0000-0000-000000000001', 'ph7_rm@example.com')
on conflict do nothing;
insert into public.profiles (id, full_name, is_active)
values ('77777777-7777-0000-0000-000000000001', 'Ph7 RM', true)
on conflict do nothing;

-- GS A (10 pcs), B (4 pcs, product limited to SEND_NEW), D (10 pcs, department round trip):
-- all HELD_AT_INTERMEDIATE_STORE. C (5 pcs) is an older GS in IN_PROCESS (P2-07 flow).
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
    ('77777777-7777-0000-0000-00000000000a', 'GS/TEST/PH7/A', v_wf, 'COURIER_PARCEL', 'C', '1', 1, 1, 'HELD_AT_INTERMEDIATE_STORE'),
    ('77777777-7777-0000-0000-00000000000b', 'GS/TEST/PH7/B', v_wf, 'COURIER_PARCEL', 'C', '1', 1, 1, 'HELD_AT_INTERMEDIATE_STORE'),
    ('77777777-7777-0000-0000-00000000000c', 'GS/TEST/PH7/C', v_wf, 'COURIER_PARCEL', 'C', '1', 1, 1, 'IN_PROCESS'),
    ('77777777-7777-0000-0000-00000000000d', 'GS/TEST/PH7/D', v_wf, 'COURIER_PARCEL', 'C', '1', 1, 1, 'HELD_AT_INTERMEDIATE_STORE');

  insert into public.gs_items (id, gs_id, line_no, product_id, category_id, documented_qty, received_qty)
  select i.id, i.gs_id, 1, p.id, p.category_id, i.qty, i.qty
    from (values
      ('77777777-7777-0000-0000-0000000000a1'::uuid, '77777777-7777-0000-0000-00000000000a'::uuid, 10, 0),
      ('77777777-7777-0000-0000-0000000000b1'::uuid, '77777777-7777-0000-0000-00000000000b'::uuid, 4, 1),
      ('77777777-7777-0000-0000-0000000000c1'::uuid, '77777777-7777-0000-0000-00000000000c'::uuid, 5, 0),
      ('77777777-7777-0000-0000-0000000000d1'::uuid, '77777777-7777-0000-0000-00000000000d'::uuid, 10, 0)
    ) as i(id, gs_id, qty, prod_offset)
    cross join lateral (
      select pr.id, pr.category_id from public.products pr
        join public.product_categories c on c.id = pr.category_id and c.code = 'DMT'
       order by pr.code offset i.prod_offset limit 1
    ) p;

  set local session_replication_role = 'origin';
end;
$$;

-- B's product: PRODUCT-scope ACTION profile with only SEND_NEW (AMD-10: most specific scope wins).
insert into public.item_field_assignments (field_id, field_group, scope_type, product_id, is_included)
select l.id, 'ACTION', 'PRODUCT', gi.product_id, true
  from public.item_field_library l, public.gs_items gi
 where l.field_group = 'ACTION' and l.code = 'SEND_NEW'
   and gi.id = '77777777-7777-0000-0000-0000000000b1';

-- ---------------------------------------------------------------------------
-- 1. Catalogue / structure
-- ---------------------------------------------------------------------------
select ok(
  (select tgdeferrable and tginitdeferred from pg_trigger where tgname = 'rm_item_actions_g21'),
  'G-21 whole-GS check is a deferred constraint trigger on rm_item_actions'
);
select ok(
  (select 'G-21' ~ (regexp_match(pg_get_constraintdef(oid), '''(.*)'''))[1]
     from pg_constraint where conname = 'system_guard_events_guard_code_check'),
  'system_guard_events accepts G-21'
);
select ok(
  exists (select 1 from public.print_templates where code = 'AC_ACTIONS_SLIP' and status = 'PUBLISHED')
  and exists (select 1 from public.number_series where code = 'AC_ACTION_SLIP'),
  'AC_ACTIONS_SLIP template is published and the AC_ACTION_SLIP number series exists (DEC-41)'
);

-- ---------------------------------------------------------------------------
-- 2. G-21 split on save (deferred to commit; forced here with SET CONSTRAINTS ... IMMEDIATE)
-- ---------------------------------------------------------------------------
select lives_ok(
  $t$do $x$ begin
      insert into public.rm_item_actions (gs_item_id, revision_no, action_code, qty, decided_by)
      values ('77777777-7777-0000-0000-0000000000a1', 1, 'SEND_NEW', 6, '77777777-7777-0000-0000-000000000001'),
             ('77777777-7777-0000-0000-0000000000a1', 1, 'SEND_REPAIRED', 3, '77777777-7777-0000-0000-000000000001'),
             ('77777777-7777-0000-0000-0000000000a1', 1, 'ISSUE_CN', 1, '77777777-7777-0000-0000-000000000001');
      set constraints public.rm_item_actions_g21 immediate;
      set constraints public.rm_item_actions_g21 deferred;
    end $x$$t$,
  'G-21: 10 pcs split 6 / 3 / 1 is accepted'
);

select throws_matching(
  $t$do $x$ begin
      insert into public.rm_item_actions (gs_item_id, revision_no, action_code, qty, decided_by)
      values ('77777777-7777-0000-0000-0000000000b1', 1, 'SEND_NEW', 3, '77777777-7777-0000-0000-000000000001');
      set constraints public.rm_item_actions_g21 immediate;
    end $x$$t$,
  'G-21: .*action qty total \(3\) must equal the qty available for action \(4\)',
  'G-21: 3 of 4 pcs actioned is rejected at commit (deferred check)'
);

select throws_matching(
  $$insert into public.rm_item_actions (gs_item_id, revision_no, action_code, qty, decided_by)
    values ('77777777-7777-0000-0000-0000000000b1', 1, 'ISSUE_CN', 4, '77777777-7777-0000-0000-000000000001')$$,
  'G-21: action ISSUE_CN is not allowed by the resolved profile',
  'G-21: an action outside the product''s resolved ACTION profile is rejected immediately'
);

select throws_matching(
  $$select rms_private.validate_final_action_split('77777777-7777-0000-0000-00000000000b', true)$$,
  'G-21: no RM final actions have been saved',
  'G-21: finalise check needs a saved revision'
);

-- P2-07 GS (not on the AMD-13 flow) keeps the earlier rules: no G-21 on its rows.
select lives_ok(
  $$insert into public.rm_item_actions (gs_item_id, revision_no, action_code, qty, decided_by)
    values ('77777777-7777-0000-0000-0000000000c1', 1, 'SEND_NEW', 2, '77777777-7777-0000-0000-000000000001')$$,
  'An older (P2-07) GS is not subject to G-21'
);
select is(
  rms_private.gs_on_final_action_flow('77777777-7777-0000-0000-00000000000c'), false,
  'IN_PROCESS GS without a transfer slip is not on the final-action flow'
);

-- ---------------------------------------------------------------------------
-- 3. A/c Actions slip (finalise) guards
-- ---------------------------------------------------------------------------
insert into public.attachments (id, gs_id, entity_type, kind, bucket, object_path, mime_type, size_bytes, status, confirmed_at)
values
  ('77777777-7777-0000-0000-0000000000f1', '77777777-7777-0000-0000-00000000000a', 'ac_action_slips', 'GENERATED_PDF',
   'rms-documents', 'gs/77777777-7777-0000-0000-00000000000a/generated_pdf/77777777-7777-4000-8000-0000000000f1.pdf',
   'application/pdf', 1000, 'CONFIRMED', now()),
  ('77777777-7777-0000-0000-0000000000f2', '77777777-7777-0000-0000-00000000000a', 'ac_action_slips', 'GENERATED_PDF',
   'rms-documents', 'gs/77777777-7777-0000-0000-00000000000a/generated_pdf/77777777-7777-4000-8000-0000000000f2.pdf',
   'application/pdf', 1000, 'CONFIRMED', now());

select throws_matching(
  $$insert into public.attachments (gs_id, kind, bucket, object_path, mime_type, size_bytes)
    values ('77777777-7777-0000-0000-00000000000a', 'GENERATED_PDF', 'rms-documents',
            'gs/77777777-7777-0000-0000-00000000000a/generated_pdf/77777777-7777-4000-8000-0000000000f9.png', 'image/png', 1)$$,
  'attachments_mime_for_kind',
  'A GENERATED_PDF attachment must be application/pdf'
);

select throws_matching(
  $$insert into public.ac_action_slips (gs_id, slip_no, version_no, revision_no, attachment_id, template_version_no, content, totals, sha256, finalised_by)
    values ('77777777-7777-0000-0000-00000000000a', 'RSA/TEST/1', 1, 2, '77777777-7777-0000-0000-0000000000f1', 1, '{}', '{}', repeat('a', 64), '77777777-7777-0000-0000-000000000001')$$,
  'G-21: the slip must capture the latest action revision',
  'G-21: a slip must capture the latest action revision'
);
select throws_matching(
  $$insert into public.ac_action_slips (gs_id, slip_no, version_no, revision_no, attachment_id, template_version_no, content, totals, sha256, finalised_by)
    values ('77777777-7777-0000-0000-00000000000a', 'RSA/TEST/1', 2, 1, '77777777-7777-0000-0000-0000000000f1', 1, '{}', '{}', repeat('a', 64), '77777777-7777-0000-0000-000000000001')$$,
  'G-21: the first slip of a goods slip is version 1',
  'G-21: the first slip version is 1'
);
select lives_ok(
  $$insert into public.ac_action_slips (id, gs_id, slip_no, version_no, revision_no, attachment_id, template_version_no, content, totals, sha256, finalised_by)
    values ('77777777-7777-0000-0000-0000000000e1', '77777777-7777-0000-0000-00000000000a', 'RSA/TEST/1', 1, 1, '77777777-7777-0000-0000-0000000000f1', 1, '{}', '{}', repeat('a', 64), '77777777-7777-0000-0000-000000000001')$$,
  'Finalise: balanced GS with nothing at a department gets slip v1'
);

select throws_matching(
  $$insert into public.rm_item_actions (gs_item_id, revision_no, action_code, qty, decided_by)
    values ('77777777-7777-0000-0000-0000000000a1', 2, 'SEND_NEW', 10, '77777777-7777-0000-0000-000000000001')$$,
  'G-21: final actions are finalised on slip RSA/TEST/1 v1',
  'G-21: finalised actions cannot change while the slip is current'
);
select throws_matching(
  $$update public.ac_action_slips set remarks = 'edited' where id = '77777777-7777-0000-0000-0000000000e1'$$,
  'G-21: an A/c Actions slip is immutable',
  'G-21: slip content is immutable'
);
select throws_matching(
  $$delete from public.ac_action_slips where id = '77777777-7777-0000-0000-0000000000e1'$$,
  'G-21: A/c Actions slips are never deleted',
  'G-21: a slip is never deleted'
);
select throws_matching(
  $$update public.ac_action_slips set status = 'SUPERSEDED', superseded_at = now(),
           superseded_by = '77777777-7777-0000-0000-000000000001', supersede_reason = ''
     where id = '77777777-7777-0000-0000-0000000000e1'$$,
  'ac_action_slips_superseded_fields',
  'Superseding a slip needs a reason'
);
select lives_ok(
  $$update public.ac_action_slips set status = 'SUPERSEDED', superseded_at = now(),
           superseded_by = '77777777-7777-0000-0000-000000000001', supersede_reason = 'One more repaired'
     where id = '77777777-7777-0000-0000-0000000000e1'$$,
  'A reasoned revision supersedes the slip'
);
select lives_ok(
  $t$do $x$ begin
      update public.rm_item_actions set is_current = false
       where gs_item_id = '77777777-7777-0000-0000-0000000000a1' and is_current;
      insert into public.rm_item_actions (gs_item_id, revision_no, action_code, qty, decided_by)
      values ('77777777-7777-0000-0000-0000000000a1', 2, 'SEND_NEW', 5, '77777777-7777-0000-0000-000000000001'),
             ('77777777-7777-0000-0000-0000000000a1', 2, 'SEND_REPAIRED', 4, '77777777-7777-0000-0000-000000000001'),
             ('77777777-7777-0000-0000-0000000000a1', 2, 'ISSUE_CN', 1, '77777777-7777-0000-0000-000000000001');
      set constraints public.rm_item_actions_g21 immediate;
      set constraints public.rm_item_actions_g21 deferred;
      insert into public.ac_action_slips (gs_id, slip_no, version_no, revision_no, attachment_id, template_version_no, content, totals, sha256, finalised_by)
      values ('77777777-7777-0000-0000-00000000000a', 'RSA/TEST/1', 2, 2, '77777777-7777-0000-0000-0000000000f2', 1, '{}', '{}', repeat('b', 64), '77777777-7777-0000-0000-000000000001');
    end $x$$t$,
  'After superseding: revision 2 and slip v2 with the same slip number'
);

-- ---------------------------------------------------------------------------
-- 4. Departments: available = counted - at departments; G-20 fix-forward
-- ---------------------------------------------------------------------------
insert into public.department_routings (id, routing_no, gs_id, department_field_id, department_code, department_label, location_id)
select '77777777-7777-0000-0000-000000000d10', 'DIN/TEST/PH7/1', '77777777-7777-0000-0000-00000000000d', id, code, label,
       (select id from public.inventory_locations where code = 'DEPT_TECHNICIAN_REPAIR')
  from public.item_field_library where field_group = 'DEPARTMENT' and code = 'REPAIR';
insert into public.department_routing_lines (id, routing_id, gs_item_id, qty_sent)
values ('77777777-7777-0000-0000-000000000d11', '77777777-7777-0000-0000-000000000d10', '77777777-7777-0000-0000-0000000000d1', 5);

select is(
  (select row(at_dept_qty, available_qty)::text from rms_private.final_action_item_quantities('77777777-7777-0000-0000-00000000000d')),
  '(5,5)',
  'G-21: 5 of 10 pcs at a department leaves 5 available for action'
);
select throws_matching(
  $t$do $x$ begin
      insert into public.rm_item_actions (gs_item_id, revision_no, action_code, qty, decided_by)
      values ('77777777-7777-0000-0000-0000000000d1', 1, 'SEND_NEW', 10, '77777777-7777-0000-0000-000000000001');
      set constraints public.rm_item_actions_g21 immediate;
    end $x$$t$,
  'G-2[01]:',
  'G-21: pieces at a department cannot be actioned'
);

insert into public.rm_item_actions (gs_item_id, revision_no, action_code, qty, decided_by)
values ('77777777-7777-0000-0000-0000000000d1', 1, 'SEND_NEW', 5, '77777777-7777-0000-0000-000000000001');
select throws_matching(
  $$select rms_private.validate_final_action_split('77777777-7777-0000-0000-00000000000d', true)$$,
  'G-21: item line 1 .* still has 5 pc\(s\) at a department',
  'G-21: finalise is blocked while pieces are at a department'
);

-- Department returns 4 Repaired + 1 Wastage. Old G-20 formula: 10 - 0 - 5 - 5 = 0 now, but
-- after actioning all 10 it gave -5. Fixed: the actioned pieces cover the outcome pieces first.
insert into public.department_receipts (id, receipt_no, routing_id)
values ('77777777-7777-0000-0000-000000000d20', 'DRN/TEST/PH7/1', '77777777-7777-0000-0000-000000000d10');
insert into public.department_receipt_lines (receipt_id, routing_line_id, outcome_head_id, outcome_code, outcome_label, quantity)
select '77777777-7777-0000-0000-000000000d20', '77777777-7777-0000-0000-000000000d11', id, code, label, q
  from public.department_outcome_heads h
  join (values ('REPAIRED', 4), ('WASTAGE', 1)) as v(c, q) on v.c = h.code;

select lives_ok(
  $t$do $x$ begin
      update public.rm_item_actions set is_current = false
       where gs_item_id = '77777777-7777-0000-0000-0000000000d1' and is_current;
      insert into public.rm_item_actions (gs_item_id, revision_no, action_code, qty, decided_by)
      values ('77777777-7777-0000-0000-0000000000d1', 2, 'SEND_NEW', 5, '77777777-7777-0000-0000-000000000001'),
             ('77777777-7777-0000-0000-0000000000d1', 2, 'SEND_REPAIRED', 4, '77777777-7777-0000-0000-000000000001'),
             ('77777777-7777-0000-0000-0000000000d1', 2, 'NOT_ALLOWED', 1, '77777777-7777-0000-0000-000000000001');
      set constraints public.rm_item_actions_g21 immediate;
      set constraints public.rm_item_actions_g21 deferred;
    end $x$$t$,
  'G-20 / G-21: all 10 pcs (5 back from the department) actioned without a double count'
);
select lives_ok(
  $$select rms_private.validate_department_reconciliation('77777777-7777-0000-0000-00000000000d'),
           rms_private.validate_final_action_split('77777777-7777-0000-0000-00000000000d', true)$$,
  'G-20 conserved and G-21 finalise check passes after the round trip'
);

select * from finish();
rollback;
