-- Change plan 2026-11-12 · Phase 6 hardening (migration 20261113001000).
-- G-20 integrity guards on insert, outcome snapshot from the head (DEC-43), insert-only history
-- for the API role, and the GS row lock taken by the reconciliation triggers.

begin;
select plan(15);

-- Scenario: GS A held at the intermediate store (10 pcs), GS B still in RM_REVIEW (5 pcs).
do $$
begin
  set local session_replication_role = 'replica';

  insert into public.goods_slips (
    id, gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count, box_count, status
  )
  select g.id, g.no, v.id, 'COURIER_PARCEL', 'Test Courier', '123', 1, 1, g.status
    from (values
      ('77777777-0000-0000-0000-00000000000a'::uuid, 'GS/TEST/PH6H/A', 'HELD_AT_INTERMEDIATE_STORE'),
      ('77777777-0000-0000-0000-00000000000b'::uuid, 'GS/TEST/PH6H/B', 'RM_REVIEW')
    ) as g(id, no, status)
    cross join lateral (
      select v.id from public.workflow_versions v
        join public.workflow_definitions d on d.id = v.workflow_definition_id and d.code = 'RMS_STANDARD'
       where v.status = 'PUBLISHED' limit 1
    ) v;

  insert into public.gs_items (id, gs_id, line_no, product_id, category_id, documented_qty, received_qty)
  select i.id, i.gs_id, 1, p.id, p.category_id, i.qty, i.qty
    from (values
      ('77777777-0000-0000-0000-0000000000a1'::uuid, '77777777-0000-0000-0000-00000000000a'::uuid, 10),
      ('77777777-0000-0000-0000-0000000000b1'::uuid, '77777777-0000-0000-0000-00000000000b'::uuid, 5)
    ) as i(id, gs_id, qty)
    cross join lateral (select id, category_id from public.products limit 1) p;

  set local session_replication_role = 'origin';
end;
$$;

-- 1. Routing for a GS that is not held at the intermediate store is rejected (G-20).
select throws_matching(
  $$insert into public.department_routings (routing_no, gs_id, department_field_id, department_code, department_label)
    select 'DIN/TEST/H/1', '77777777-0000-0000-0000-00000000000b', id, code, label
      from public.item_field_library where field_group = 'DEPARTMENT' and code = 'REPAIR'$$,
  'G-20: department routing needs the goods slip held',
  'G-20: routing rejected while the GS is not HELD_AT_INTERMEDIATE_STORE'
);

-- 2. Routing to a non-DEPARTMENT field is rejected.
select throws_matching(
  $$insert into public.department_routings (routing_no, gs_id, department_field_id, department_code, department_label)
    select 'DIN/TEST/H/2', '77777777-0000-0000-0000-00000000000a', id, code, label
      from public.item_field_library where field_group <> 'DEPARTMENT' limit 1$$,
  'G-20: department routing needs an active DEPARTMENT field',
  'G-20: routing rejected for a field outside the DEPARTMENT group'
);

-- 3. Valid routing; client-supplied department label is replaced by the library snapshot (G-18).
select lives_ok(
  $$insert into public.department_routings (id, routing_no, gs_id, department_field_id, department_code, department_label)
    select '77777777-0000-0000-0000-000000000100', 'DIN/TEST/H/3', '77777777-0000-0000-0000-00000000000a', id, 'FAKE', 'Fake label'
      from public.item_field_library where field_group = 'DEPARTMENT' and code = 'REPAIR'$$,
  'Routing accepted for a held GS and an active department'
);
select is(
  (select department_code from public.department_routings where id = '77777777-0000-0000-0000-000000000100'),
  'REPAIR',
  'Routing department code is snapshotted from the library, not the client'
);

-- 4. Routing line with an item of another GS is rejected (G-20).
select throws_matching(
  $$insert into public.department_routing_lines (routing_id, gs_item_id, qty_sent)
    values ('77777777-0000-0000-0000-000000000100', '77777777-0000-0000-0000-0000000000b1', 1)$$,
  'does not belong to the routing''s goods slip',
  'G-20: routing line rejected for an item of another GS'
);

select lives_ok(
  $$insert into public.department_routing_lines (id, routing_id, gs_item_id, qty_sent)
    values ('77777777-0000-0000-0000-000000000101', '77777777-0000-0000-0000-000000000100', '77777777-0000-0000-0000-0000000000a1', 3)$$,
  'Routing line accepted for an item of the same GS'
);

-- 5. Receipt line: flags and labels come from the outcome head, whatever the client sends (DEC-43).
insert into public.department_receipts (id, receipt_no, routing_id)
values ('77777777-0000-0000-0000-000000000200', 'DRN/TEST/H/1', '77777777-0000-0000-0000-000000000100');

insert into public.department_receipt_lines (
  id, receipt_id, routing_line_id, outcome_head_id, outcome_code, outcome_label, is_wastage, returns_to_routing, quantity
)
select '77777777-0000-0000-0000-000000000201', '77777777-0000-0000-0000-000000000200',
       '77777777-0000-0000-0000-000000000101', id, 'REPAIRED', 'Lie', false, false, 1
  from public.department_outcome_heads where code = 'WASTAGE';

select is(
  (select row(outcome_code, is_wastage)::text from public.department_receipt_lines
    where id = '77777777-0000-0000-0000-000000000201'),
  '(WASTAGE,t)',
  'Receipt line outcome code and is_wastage are snapshotted from the head'
);

-- 6. Inactive outcome head is rejected.
update public.department_outcome_heads set is_active = false where code = 'CLEANED';
select throws_matching(
  $$insert into public.department_receipt_lines (receipt_id, routing_line_id, outcome_head_id, outcome_code, outcome_label, quantity)
    select '77777777-0000-0000-0000-000000000200', '77777777-0000-0000-0000-000000000101', id, code, label, 1
      from public.department_outcome_heads where code = 'CLEANED'$$,
  'G-20: receipt line needs an active outcome head',
  'G-20: receipt line rejected for an inactive outcome head'
);

-- 7. Receipt against a completed routing is rejected: receive the last 2 pcs, then try again.
insert into public.department_receipt_lines (receipt_id, routing_line_id, outcome_head_id, outcome_code, outcome_label, quantity)
select '77777777-0000-0000-0000-000000000200', '77777777-0000-0000-0000-000000000101', id, code, label, 2
  from public.department_outcome_heads where code = 'REPAIRED';

select is(
  (select status from public.department_routings where id = '77777777-0000-0000-0000-000000000100'),
  'COMPLETED',
  'Routing completed after all pieces are received'
);
select throws_matching(
  $$insert into public.department_receipts (receipt_no, routing_id)
    values ('DRN/TEST/H/2', '77777777-0000-0000-0000-000000000100')$$,
  'G-20: department receipt needs an open routing',
  'G-20: receipt rejected for a completed routing'
);

-- 8. Insert-only history for the API role (deleting a receipt line would break G-20).
-- Checked as privileges: on a fresh `supabase db reset` (PG16+) postgres holds rms_api WITH ADMIN
-- but without SET, so `set role rms_api` is refused (fixed 2026-11-13, change plan Phase 7).
select ok(not has_table_privilege('rms_api', 'public.department_receipt_lines', 'DELETE'),
  'rms_api cannot delete department receipt lines');
select ok(not has_table_privilege('rms_api', 'public.department_receipt_lines', 'UPDATE'),
  'rms_api cannot update department receipt lines');
select ok(not has_table_privilege('rms_api', 'public.department_routing_lines', 'UPDATE'),
  'rms_api cannot update routing line quantities (only the receipt trigger does)');
select ok(not has_table_privilege('rms_api', 'public.department_routings', 'DELETE'),
  'rms_api cannot delete department routings');

-- 9. The reconciliation trigger locks the GS row (G-20 serialisation): the function source holds it.
select ok(
  pg_get_functiondef('rms_private.trg_dept_receipt_lines_reconciliation()'::regprocedure)
    ~ 'from public\.goods_slips where id = v_gs_id for update',
  'G-20 receipt trigger locks the goods slip before validating'
);

select * from finish();
rollback;
