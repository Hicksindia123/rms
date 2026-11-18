-- Change plan 2026-11-12 · Phase 6 pgTAP test suite
-- Tests for department routings, lines, receipts, outcome heads, and Guard G-20 reconciliation.

begin;
select plan(20);

-- 1. Number series exist
select ok(exists(select 1 from public.number_series where code = 'DEPT_ROUTING'), 'DEPT_ROUTING number series exists');
select ok(exists(select 1 from public.number_series where code = 'DEPT_RECEIPT'), 'DEPT_RECEIPT number series exists');

-- 2. Outcome heads seeded
select is(
  (select count(*)::integer from public.department_outcome_heads where code in ('REPAIRED', 'NOT_REPAIRED', 'CLEANED', 'WASTAGE', 'SEND_TO_MERCURY_EXTRACTION', 'RE_ROUTE')),
  6,
  'All 6 default department outcome heads are seeded'
);

-- 3. System guard events accepts G-20
select lives_ok(
  $$insert into public.system_guard_events (guard_code, source)
    values ('G-20', 'SERVICE')$$,
  'system_guard_events accepts G-20'
);

-- 4. Set up test scenario:
-- Create a test GS in HELD_AT_INTERMEDIATE_STORE with 1 item of 10 pcs
do $$
declare
  v_gs_id uuid := '66666666-0000-0000-0000-000000000001';
  v_item_id uuid := '66666666-0000-0000-0000-000000000002';
  v_prod_id uuid;
  v_party_id uuid;
  v_dept_id uuid;
  v_routing_id uuid;
  v_rline_id uuid;
  v_receipt_id uuid;
begin
  select id into v_prod_id from public.products limit 1;
  select id into v_party_id from public.parties limit 1;
  select id into v_dept_id from public.item_field_library where field_group = 'DEPARTMENT' and code = 'REPAIR' limit 1;

  set local session_replication_role = 'replica';

  -- Insert GS in HELD_AT_INTERMEDIATE_STORE
  insert into public.goods_slips (
    id, gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count, box_count, status
  )
  select
    v_gs_id, 'GS/TEST/PH6/001', v.id, 'COURIER_PARCEL', 'Test Courier', '123', 1, 1, 'HELD_AT_INTERMEDIATE_STORE'
    from public.workflow_versions v
    join public.workflow_definitions d on d.id = v.workflow_definition_id and d.code = 'RMS_STANDARD'
   where v.status = 'PUBLISHED'
   limit 1;

  -- Insert item with 10 pcs
  insert into public.gs_items (
    id, gs_id, line_no, product_id, category_id, documented_qty, received_qty
  )
  select
    v_item_id, v_gs_id, 1, p.id, p.category_id, 10, 10
    from public.products p
   limit 1;

  set local session_replication_role = 'origin';
end;
$$;

-- 5. Test G-20: initial reconciliation is valid (10 pcs counted = 10 pcs in store)
select lives_ok(
  $$select rms_private.validate_department_reconciliation('66666666-0000-0000-0000-000000000001')$$,
  'G-20: initial reconciliation passes with all items in store'
);

-- 6. Test routing dispatch: dispatch 6 pcs to REPAIR
do $$
declare
  v_gs_id uuid := '66666666-0000-0000-0000-000000000001';
  v_item_id uuid := '66666666-0000-0000-0000-000000000002';
  v_dept_id uuid;
  v_routing_id uuid := '66666666-0000-0000-0000-000000000010';
  v_line_id uuid := '66666666-0000-0000-0000-000000000011';
begin
  select id into v_dept_id from public.item_field_library where field_group = 'DEPARTMENT' and code = 'REPAIR' limit 1;

  -- G2 (DEC-55): a routing carries its department location.
  insert into public.department_routings (
    id, routing_no, gs_id, department_field_id, department_code, department_label, status, location_id
  ) values (
    v_routing_id, 'DIN/TEST/001', v_gs_id, v_dept_id, 'REPAIR', 'Repair', 'DISPATCHED',
    (select id from public.inventory_locations where code = 'DEPT_TECHNICIAN_REPAIR')
  );

  insert into public.department_routing_lines (
    id, routing_id, gs_item_id, qty_sent, qty_received
  ) values (
    v_line_id, v_routing_id, v_item_id, 6, 0
  );
end;
$$;

select is(
  (select status from public.department_routings where id = '66666666-0000-0000-0000-000000000010'),
  'DISPATCHED',
  'Routing created in DISPATCHED status'
);

select is(
  (select qty_sent from public.department_routing_lines where id = '66666666-0000-0000-0000-000000000011'),
  6,
  'Routing line has qty_sent = 6'
);

-- 7. Test G-20 passes with 6 at department and 4 in store
select lives_ok(
  $$select rms_private.validate_department_reconciliation('66666666-0000-0000-0000-000000000001')$$,
  'G-20: passes with 6 at department + 4 in store = 10'
);

-- 8. Test G-20 rejects over-dispatch: trying to send 5 more when only 4 remain in store
-- (G2 / DEC-55: the routing-line G-20 check is deferred to commit; forced immediate here.)
select throws_matching(
  $q$do $x$ begin
      insert into public.department_routing_lines (
        routing_id, gs_item_id, qty_sent, qty_received
      ) values (
        '66666666-0000-0000-0000-000000000010', '66666666-0000-0000-0000-000000000002', 5, 0
      );
      set constraints trg_dept_routing_lines_g20 immediate;
    end $x$ $q$,
  'G-20',
  'G-20: rejects routing lines that exceed available store quantity'
);

-- 9. Test partial receipt: receive 4 pcs as REPAIRED
do $$
declare
  v_routing_id uuid := '66666666-0000-0000-0000-000000000010';
  v_rline_id uuid := '66666666-0000-0000-0000-000000000011';
  v_receipt_id uuid := '66666666-0000-0000-0000-000000000020';
  v_outcome_id uuid;
begin
  select id into v_outcome_id from public.department_outcome_heads where code = 'REPAIRED';

  insert into public.department_receipts (
    id, receipt_no, routing_id, remarks
  ) values (
    v_receipt_id, 'DRN/TEST/001', v_routing_id, 'Partial receipt: 4 repaired'
  );

  insert into public.department_receipt_lines (
    receipt_id, routing_line_id, outcome_head_id, outcome_code, outcome_label, is_wastage, returns_to_routing, quantity
  ) values (
    v_receipt_id, v_rline_id, v_outcome_id, 'REPAIRED', 'Repaired', false, false, 4
  );
end;
$$;

-- 10. Check that qty_received was updated to 4 and routing is PARTIALLY_RECEIVED
select is(
  (select qty_received from public.department_routing_lines where id = '66666666-0000-0000-0000-000000000011'),
  4,
  'Routing line qty_received auto-updated to 4'
);

select is(
  (select status from public.department_routings where id = '66666666-0000-0000-0000-000000000010'),
  'PARTIALLY_RECEIVED',
  'Routing status auto-updated to PARTIALLY_RECEIVED'
);

-- 11. G-20 passes: 4 in store + 2 at dept + 4 in outcome = 10
select lives_ok(
  $$select rms_private.validate_department_reconciliation('66666666-0000-0000-0000-000000000001')$$,
  'G-20: passes with 4 in store + 2 at dept + 4 outcome = 10'
);

-- 12. Check that over-receiving is rejected by check constraint
select throws_ok(
  $$insert into public.department_receipt_lines (
      receipt_id, routing_line_id, outcome_head_id, outcome_code, outcome_label, is_wastage, returns_to_routing, quantity
    ) values (
      '66666666-0000-0000-0000-000000000020', '66666666-0000-0000-0000-000000000011',
      (select id from public.department_outcome_heads where code = 'REPAIRED'), 'REPAIRED', 'Repaired', false, false, 3
    )$$,
  '23514', null,
  'Check constraint rejects receiving more than remaining sent quantity'
);

-- 13. Receive remaining 2 pcs: 1 as WASTAGE, 1 as RE_ROUTE
do $$
declare
  v_rline_id uuid := '66666666-0000-0000-0000-000000000011';
  v_receipt_id uuid := '66666666-0000-0000-0000-000000000021';
  v_outcome_waste uuid;
  v_outcome_reroute uuid;
begin
  select id into v_outcome_waste from public.department_outcome_heads where code = 'WASTAGE';
  select id into v_outcome_reroute from public.department_outcome_heads where code = 'RE_ROUTE';

  insert into public.department_receipts (
    id, receipt_no, routing_id, remarks
  ) values (
    v_receipt_id, 'DRN/TEST/002', '66666666-0000-0000-0000-000000000010', 'Final receipt: 1 wastage + 1 re-route'
  );

  insert into public.department_receipt_lines (
    receipt_id, routing_line_id, outcome_head_id, outcome_code, outcome_label, is_wastage, returns_to_routing, quantity
  ) values
    (v_receipt_id, v_rline_id, v_outcome_waste, 'WASTAGE', 'Wastage', true, false, 1),
    (v_receipt_id, v_rline_id, v_outcome_reroute, 'RE_ROUTE', 'Return to RM Routing Queue', false, true, 1);
end;
$$;

-- 14. Check routing is now COMPLETED and line has qty_received = 6
select is(
  (select qty_received from public.department_routing_lines where id = '66666666-0000-0000-0000-000000000011'),
  6,
  'Routing line qty_received is now 6 (fully received)'
);

select is(
  (select status from public.department_routings where id = '66666666-0000-0000-0000-000000000010'),
  'COMPLETED',
  'Routing status auto-updated to COMPLETED'
);

-- 15. Check G-20 conservation:
-- counted = 10
-- at_dept = 0
-- outcome_heads (not returns_to_routing): 4 (REPAIRED) + 1 (WASTAGE) = 5
-- in_store: initial 4 + 1 (RE_ROUTE) = 5
-- actioned: 0
-- sum: 5 + 0 + 5 + 0 = 10
select lives_ok(
  $$select rms_private.validate_department_reconciliation('66666666-0000-0000-0000-000000000001')$$,
  'G-20: fully conserved: 5 in store + 0 at dept + 5 terminal outcomes + 0 actioned = 10'
);

-- 16. Permissions registered
select ok(exists(select 1 from public.permissions where module_code = 'department_routing' and action = 'view'), 'department_routing.view permission exists');
select ok(exists(select 1 from public.permissions where module_code = 'department_routing' and action = 'create'), 'department_routing.create permission exists');
select ok(exists(select 1 from public.permissions where module_code = 'department_routing' and action = 'edit'), 'department_routing.edit permission exists');

-- 17. Settings registered
select is(
  (select value->>0 from public.system_settings where key = 'department.receiving_role'),
  'INWARD_VERIFIER',
  'DEC-42: department.receiving_role defaults to INWARD_VERIFIER'
);

select * from finish();
rollback;
