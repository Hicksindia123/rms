-- Gap plan G3 (migration 20261118000200; DEC-56; Q7, Q8, Q17; Guards G-18, G-20).
-- Receiving records the condition after work; the item's current condition split is updated
-- (counting split kept as history); outcome destinations; per-condition G-20; the G2 fix that
-- lets the Store issue several plan lines of one item in one DIN.

begin;
select plan(25);

-- Scenario: GS held; item 1 = 10 pcs split C1 6 / C2 4 (two conditions of the product's
-- categorisation list); item 2 = 3 pcs without a split.
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
   limit 1;

  insert into public.goods_slips (
    id, gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count, box_count, status
  )
  select '99999999-0000-0000-0000-00000000000a', 'GS/TEST/G3/A', v.id, 'COURIER_PARCEL', 'Test Courier', '123', 1, 1,
         'HELD_AT_INTERMEDIATE_STORE'
    from public.workflow_versions v
    join public.workflow_definitions d on d.id = v.workflow_definition_id and d.code = 'RMS_STANDARD'
   where v.status = 'PUBLISHED' limit 1;

  insert into public.gs_items (id, gs_id, line_no, product_id, category_id, documented_qty, received_qty)
  values ('99999999-0000-0000-0000-0000000000a1', '99999999-0000-0000-0000-00000000000a', 1, v_prod.id, v_prod.category_id, 10, 10),
         ('99999999-0000-0000-0000-0000000000a2', '99999999-0000-0000-0000-00000000000a', 2, v_prod.id, v_prod.category_id, 3, 3);

  insert into public.gs_item_buckets (gs_item_id, field_id, field_code, label_snapshot, qty)
  select '99999999-0000-0000-0000-0000000000a1', r.field_id, r.code, r.label,
         case when r.rn = 1 then 6 else 4 end
    from (select r.field_id, r.code, r.label, row_number() over (order by r.sort_order, r.code) as rn
            from rms_private.resolve_item_field_profile(v_prod.id) r
           where r.field_group = 'CATEGORISATION') r
   where r.rn <= 2;

  set local session_replication_role = 'origin';
end;
$$;

create temp table g3 as
select (select id from public.item_field_library where field_group = 'DEPARTMENT' and code = 'REPAIR') as repair,
       (select id from public.item_field_library where field_group = 'DEPARTMENT' and code = 'STORE') as store,
       (select id from public.inventory_locations where code = 'DEPT_TECHNICIAN_REPAIR') as repair_loc,
       (select field_id from public.gs_item_buckets where gs_item_id = '99999999-0000-0000-0000-0000000000a1' and qty = 6) as c1,
       (select field_id from public.gs_item_buckets where gs_item_id = '99999999-0000-0000-0000-0000000000a1' and qty = 4) as c2,
       (select id from public.item_field_library where field_group = 'ACTION' limit 1) as not_a_condition,
       (select id from public.department_outcome_heads where code = 'REPAIRED') as h_repaired,
       (select id from public.department_outcome_heads where code = 'RE_ROUTE') as h_reroute,
       (select id from public.department_outcome_heads where code = 'WASTAGE') as h_wastage,
       (select id from public.department_outcome_heads where code = 'MERCURY_EXTRACTED') as h_mercury;

-- ---------------------------------------------------------------------------
-- 1. Configuration (Q17) and the current split before any receipt
-- ---------------------------------------------------------------------------
select has_table('public', 'gs_item_conditions', 'current condition table exists');
select results_eq(
  $$select label, is_wastage, returns_to_routing, destination_location_code
      from public.department_outcome_heads where code = 'MERCURY_EXTRACTED'$$,
  $$values ('Mercury Extracted'::text, false, false, 'NON_FUNCTIONAL_STORE'::text)$$,
  'outcome "Mercury Extracted" goes to the Non-Functional Store (Q17)');
select results_eq(
  $$select original_qty, current_qty from rms_private.item_current_conditions('99999999-0000-0000-0000-0000000000a1')
     order by original_qty desc$$,
  $$values (6, 6), (4, 4)$$,
  'before any receipt the current split is the counting split');

-- ---------------------------------------------------------------------------
-- 2. Plan + Store issue of two conditions of one item in ONE DIN (G2 fix) + item 2 without split
-- ---------------------------------------------------------------------------
insert into public.department_routing_plan_lines (id, gs_id, gs_item_id, source_bucket_field_id, department_field_id, department_code, department_label, qty)
select v.id, '99999999-0000-0000-0000-00000000000a', v.item, v.cond, g3.repair, '-', '-', v.qty
  from g3, lateral (values
    ('99999999-0000-0000-0000-000000000101'::uuid, '99999999-0000-0000-0000-0000000000a1'::uuid, g3.c1, 6),
    ('99999999-0000-0000-0000-000000000102'::uuid, '99999999-0000-0000-0000-0000000000a1'::uuid, g3.c2, 4),
    ('99999999-0000-0000-0000-000000000103'::uuid, '99999999-0000-0000-0000-0000000000a2'::uuid, null::uuid, 3)
  ) as v(id, item, cond, qty);

select lives_ok(
  $q$do $x$ begin
      insert into public.department_routings (id, routing_no, gs_id, department_field_id, department_code, department_label, location_id)
      select '99999999-0000-0000-0000-000000000201', 'DIN/TEST/G3/1', '99999999-0000-0000-0000-00000000000a', repair, '-', '-', repair_loc from g3;
      insert into public.department_routing_lines (id, routing_id, gs_item_id, source_bucket_field_id, qty_sent)
      select v.id, '99999999-0000-0000-0000-000000000201', v.item, v.cond, v.qty
        from g3, lateral (values
          ('99999999-0000-0000-0000-000000000301'::uuid, '99999999-0000-0000-0000-0000000000a1'::uuid, g3.c1, 6),
          ('99999999-0000-0000-0000-000000000302'::uuid, '99999999-0000-0000-0000-0000000000a1'::uuid, g3.c2, 4),
          ('99999999-0000-0000-0000-000000000303'::uuid, '99999999-0000-0000-0000-0000000000a2'::uuid, null::uuid, 3)
        ) as v(id, item, cond, qty);
      update public.department_routing_plan_lines p
         set status = 'ISSUED', routing_id = '99999999-0000-0000-0000-000000000201',
             routing_line_id = ('99999999-0000-0000-0000-0000000003' || right(p.id::text, 2))::uuid, issued_at = now()
       where p.gs_id = '99999999-0000-0000-0000-00000000000a';
      set constraints all immediate;
    end $x$ $q$,
  'G2 fix: the Store issues two conditions of one item (6 + 4 = all 10 pcs) in one DIN');

insert into public.department_receipts (id, receipt_no, routing_id)
values ('99999999-0000-0000-0000-000000000401', 'DRN/TEST/G3/1', '99999999-0000-0000-0000-000000000201');

-- ---------------------------------------------------------------------------
-- 3. Receipt line guard (Q7)
-- ---------------------------------------------------------------------------
select throws_matching(
  $$insert into public.department_receipt_lines (receipt_id, routing_line_id, outcome_head_id, outcome_code, outcome_label, quantity)
    select '99999999-0000-0000-0000-000000000401', '99999999-0000-0000-0000-000000000302', h_repaired, '-', '-', 1 from g3$$,
  'G-20: item line 1 was routed from a condition; record the condition it came back in',
  'G-20: the condition after work is required for pieces routed from a condition');
select throws_matching(
  $$insert into public.department_receipt_lines (receipt_id, routing_line_id, outcome_head_id, outcome_code, outcome_label, quantity, condition_field_id)
    select '99999999-0000-0000-0000-000000000401', '99999999-0000-0000-0000-000000000302', h_repaired, '-', '-', 1, not_a_condition from g3$$,
  'G-18: condition .* is not in the categorisation list of item line 1',
  'G-18: the condition must come from the product''s categorisation list');
select throws_matching(
  $$insert into public.department_receipt_lines (receipt_id, routing_line_id, outcome_head_id, outcome_code, outcome_label, quantity, condition_field_id)
    select '99999999-0000-0000-0000-000000000401', '99999999-0000-0000-0000-000000000303', h_repaired, '-', '-', 1, c1 from g3$$,
  'G-20: item line 2 was routed without a condition',
  'G-20: no condition after work for an item routed without a condition');

-- r1: 2 of the C2 pieces come back Repaired, now in condition C1.
select lives_ok(
  $$insert into public.department_receipt_lines (id, receipt_id, routing_line_id, outcome_head_id, outcome_code, outcome_label, is_wastage, quantity, condition_field_id, condition_label)
    select '99999999-0000-0000-0000-000000000501', '99999999-0000-0000-0000-000000000401', '99999999-0000-0000-0000-000000000302',
           h_repaired, 'FAKE', 'Fake', true, 2, c1, 'Fake label' from g3$$,
  'receipt line with outcome + condition after work accepted');
select results_eq(
  $$select r.outcome_code, r.is_wastage, r.source_condition_field_id = g3.c2, r.condition_field_id = g3.c1,
           r.condition_label = l.label, r.destination_location_code
      from public.department_receipt_lines r, g3, public.item_field_library l
     where r.id = '99999999-0000-0000-0000-000000000501' and l.id = g3.c1$$,
  $$values ('REPAIRED'::text, false, true, true, true, 'INTERMEDIATE_STORE'::text)$$,
  'snapshots come from the DB: outcome, source condition, condition label (G-18), destination = Intermediate Store (Q8)');
select results_eq(
  $$select c.qty from public.gs_item_conditions c, g3
     where c.gs_item_id = '99999999-0000-0000-0000-0000000000a1' and c.field_id in (g3.c1, g3.c2)
     order by c.field_id = g3.c1 desc$$,
  $$values (8), (2)$$,
  'current split updated: C1 6 → 8, C2 4 → 2');
select results_eq(
  $$select b.qty from public.gs_item_buckets b, g3
     where b.gs_item_id = '99999999-0000-0000-0000-0000000000a1' order by b.field_id = g3.c1 desc$$,
  $$values (6), (4)$$,
  'counting split unchanged (history)');

-- r2: 1 C1 piece re-routed, now C2. r3: 1 C1 piece wastage, now C2. r4: 1 C2 piece Mercury Extracted.
-- One row per statement, as the service books them (the Phase 6 AFTER-row G-20 trigger of a
-- multi-row insert sees later rows before their qty_received update).
insert into public.department_receipt_lines (id, receipt_id, routing_line_id, outcome_head_id, outcome_code, outcome_label, quantity, condition_field_id)
select '99999999-0000-0000-0000-000000000502', '99999999-0000-0000-0000-000000000401', '99999999-0000-0000-0000-000000000301', h_reroute, '-', '-', 1, c2 from g3;
insert into public.department_receipt_lines (id, receipt_id, routing_line_id, outcome_head_id, outcome_code, outcome_label, quantity, condition_field_id)
select '99999999-0000-0000-0000-000000000503', '99999999-0000-0000-0000-000000000401', '99999999-0000-0000-0000-000000000301', h_wastage, '-', '-', 1, c2 from g3;
insert into public.department_receipt_lines (id, receipt_id, routing_line_id, outcome_head_id, outcome_code, outcome_label, quantity, condition_field_id)
select '99999999-0000-0000-0000-000000000504', '99999999-0000-0000-0000-000000000401', '99999999-0000-0000-0000-000000000302', h_mercury, '-', '-', 1, c2 from g3;

select results_eq(
  $$select destination_location_code from public.department_receipt_lines
     where id in ('99999999-0000-0000-0000-000000000502', '99999999-0000-0000-0000-000000000503', '99999999-0000-0000-0000-000000000504')
     order by id$$,
  $$values ('INTERMEDIATE_STORE'::text), ('SCRAP_DISPOSED'::text), ('NON_FUNCTIONAL_STORE'::text)$$,
  'destinations: re-route → store, wastage → scrap (as today), Mercury Extracted → Non-Functional Store');
select results_eq(
  $$select c.qty from public.gs_item_conditions c, g3
     where c.gs_item_id = '99999999-0000-0000-0000-0000000000a1' and c.field_id in (g3.c1, g3.c2)
     order by c.field_id = g3.c1 desc$$,
  $$values (6), (4)$$,
  'current split after four receipts: C1 6, C2 4');
select is((select sum(qty)::int from public.gs_item_conditions where gs_item_id = '99999999-0000-0000-0000-0000000000a1'),
          10, 'the current split always totals the counted qty');

-- C1: 6 = 4 still at the department + 2 back Repaired → free 0.
-- C2: 4 = 1 at the department + wastage 1 + mercury 1 + 1 re-routed (free again) → free 1.
select results_eq(
  $$select b.current_qty, b.committed_qty, b.free_qty
      from rms_private.item_condition_balances('99999999-0000-0000-0000-0000000000a1') b, g3
     order by b.field_id = g3.c1 desc$$,
  $$values (6, 6, 0), (4, 3, 1)$$,
  'condition balances: re-routed pieces are free again in the condition they came back in');
select is((select count(*)::int from public.gs_item_conditions where gs_item_id = '99999999-0000-0000-0000-0000000000a2'),
          0, 'an item without a split has no current-condition rows');
select lives_ok(
  $$insert into public.department_receipt_lines (receipt_id, routing_line_id, outcome_head_id, outcome_code, outcome_label, quantity)
    select '99999999-0000-0000-0000-000000000401', '99999999-0000-0000-0000-000000000303', h_repaired, '-', '-', 1 from g3$$,
  'an item without a split is received without a condition');

-- ---------------------------------------------------------------------------
-- 4. Planning from the current split; G-20 per condition
-- ---------------------------------------------------------------------------
select lives_ok(
  $$insert into public.department_routing_plan_lines (gs_id, gs_item_id, source_bucket_field_id, department_field_id, department_code, department_label, qty)
    select '99999999-0000-0000-0000-00000000000a', '99999999-0000-0000-0000-0000000000a1', c2, repair, '-', '-', 1 from g3$$,
  'the re-routed piece is planned again from its new condition');
select throws_matching(
  $$insert into public.department_routing_plan_lines (gs_id, gs_item_id, source_bucket_field_id, department_field_id, department_code, department_label, qty)
    select '99999999-0000-0000-0000-00000000000a', '99999999-0000-0000-0000-0000000000a1', c1, store, '-', '-', 1 from g3$$,
  'G-20: item line 1 .* condition .*committed but only',
  'G-20: a condition cannot be committed beyond its current quantity (even as "no work")');
select throws_matching(
  $$insert into public.department_routing_plan_lines (gs_id, gs_item_id, source_bucket_field_id, department_field_id, department_code, department_label, qty)
    select '99999999-0000-0000-0000-00000000000a', '99999999-0000-0000-0000-0000000000a1', not_a_condition, repair, '-', '-', 1 from g3$$,
  'is not a categorisation bucket of this item',
  'G-20: a plan line needs one of the item''s current conditions');

-- A condition that exists only after work (not in the counting split) can be planned.
do $$
declare
  v_c3 uuid;
begin
  select r.field_id into v_c3
    from rms_private.resolve_item_field_profile(
           (select product_id from public.gs_items where id = '99999999-0000-0000-0000-0000000000a1')) r
   where r.field_group = 'CATEGORISATION'
     and r.field_id not in (select field_id from public.gs_item_buckets where gs_item_id = '99999999-0000-0000-0000-0000000000a1')
   limit 1;
  create temp table g3c3 as select v_c3 as c3;
end;
$$;
select skip('product has only two conditions', 2) from g3c3 where c3 is null;
select lives_ok(
  $$insert into public.department_receipt_lines (receipt_id, routing_line_id, outcome_head_id, outcome_code, outcome_label, quantity, condition_field_id)
    select '99999999-0000-0000-0000-000000000401', '99999999-0000-0000-0000-000000000301', h_reroute, '-', '-', 1, c3 from g3, g3c3$$,
  'a piece can come back in a condition the counting split did not have')
  from g3c3 where c3 is not null;
select lives_ok(
  $$insert into public.department_routing_plan_lines (gs_id, gs_item_id, source_bucket_field_id, department_field_id, department_code, department_label, qty)
    select '99999999-0000-0000-0000-00000000000a', '99999999-0000-0000-0000-0000000000a1', c3, store, '-', '-', 1 from g3, g3c3$$,
  'and is then planned from that new condition')
  from g3c3 where c3 is not null;

-- ---------------------------------------------------------------------------
-- 5. Only the receipt guard writes the current split
-- ---------------------------------------------------------------------------
select ok(has_table_privilege('rms_api', 'public.gs_item_conditions', 'SELECT'), 'rms_api reads the current split');
select ok(not has_table_privilege('rms_api', 'public.gs_item_conditions', 'INSERT')
          and not has_table_privilege('rms_api', 'public.gs_item_conditions', 'UPDATE')
          and not has_table_privilege('rms_api', 'public.gs_item_conditions', 'DELETE'),
  'rms_api cannot write the current split');
select ok(not has_function_privilege('rms_api', 'rms_private.move_item_condition(uuid, uuid, uuid, integer)', 'EXECUTE'),
  'rms_api cannot move pieces between conditions directly');

select * from finish();
rollback;
