-- =============================================================================
-- Test File: 18_inventory_segregation.test.sql
-- P3-04 custody segregation (BR-30, DD r63–66), G-04 / G-05 / G-09 / G-12 DB guards,
-- stock adjustment state machine and the segregation integrity function.
-- =============================================================================

begin;
select plan(17);

select has_table('public', 'custody_assignments', 'custody_assignments table exists');
select has_table('public', 'stock_adjustments', 'stock_adjustments table exists');
select has_table('public', 'segregation_check_runs', 'segregation_check_runs table exists');
select has_function('rms_private', 'inventory_segregation_violations', 'segregation check function exists');
select has_column('public', 'stock_movements', 'seq', 'stock_movements.seq orders movements within one transaction');

-- Every configured assignment target has the locked location class (G-12).
select is(
  (select count(*)::int
     from jsonb_each_text((select value from public.system_settings
                            where key = 'custody_assignment_targets')) t(code, loc)
     join public.inventory_locations l on l.code = t.loc
    where (t.code in ('CUST_FUNCTIONAL_GOOD','CUST_FUNCTIONAL_REPAIRED') and l.location_class = 'FUNCTIONAL')
       or (t.code = 'CUST_NON_FUNCTIONAL' and l.location_class = 'NON_FUNCTIONAL')
       or (t.code = 'CUST_SALVAGED_PARTS' and l.location_class = 'SPARE_PARTS')),
  4,
  'custody_assignment_targets: all 4 DD r63–66 codes point at a location of the right class'
);

-- Fixtures ---------------------------------------------------------------------------------
insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data) values
  ('00000000-0000-0000-0000-00000000e401', 'pgtap-p304-a@example.test',
   '{"rms_activate": true}'::jsonb, '{"full_name": "P304 Custodian"}'::jsonb),
  ('00000000-0000-0000-0000-00000000e402', 'pgtap-p304-b@example.test',
   '{"rms_activate": true}'::jsonb, '{"full_name": "P304 Approver"}'::jsonb)
on conflict do nothing;

insert into public.product_categories (id, code, name)
values ('00000000-0000-0000-0000-00000000e410', 'P304_PGTAP_CAT', 'P304 pgTAP category')
on conflict do nothing;
insert into public.products (id, code, name, category_id)
values ('00000000-0000-0000-0000-00000000e411', 'P304-PGTAP', 'P304 pgTAP product',
        '00000000-0000-0000-0000-00000000e410')
on conflict do nothing;
insert into public.stock_items (id, item_kind, product_id)
values ('00000000-0000-0000-0000-00000000e412', 'FINISHED_GOOD', '00000000-0000-0000-0000-00000000e411')
on conflict do nothing;
insert into public.stock_lots (id, stock_item_id, condition_class) values
  ('00000000-0000-0000-0000-00000000e420', '00000000-0000-0000-0000-00000000e412', 'FUNCTIONAL_GOOD'),
  ('00000000-0000-0000-0000-00000000e421', '00000000-0000-0000-0000-00000000e412', 'NON_GOOD')
on conflict do nothing;

select rms_private.rms_move_stock(
  '00000000-0000-0000-0000-00000000e420', null,
  (select id from public.inventory_locations where code = 'INTERMEDIATE_STORE'),
  5, 'INWARD', null, null, 'pgtap-p304-fg', null, 'pgTAP fixture');
select rms_private.rms_move_stock(
  '00000000-0000-0000-0000-00000000e421', null,
  (select id from public.inventory_locations where code = 'NON_FUNCTIONAL_STORE'),
  3, 'INWARD', null, null, 'pgtap-p304-ng', null, 'pgTAP fixture');

select is(
  (select count(*)::int from rms_private.inventory_segregation_violations()
    where lot_id in ('00000000-0000-0000-0000-00000000e420', '00000000-0000-0000-0000-00000000e421')),
  0,
  'segregation check: correctly segregated fixture lots raise no violation'
);

-- custody_assignments guard (G-04 / G-12 / BR-30) ----------------------------------------
select throws_like(
  $$ insert into public.custody_assignments (lot_id, qty, assignment_code, condition_class,
       from_location_id, to_location_id, outcome, transfer_id)
     select '00000000-0000-0000-0000-00000000e421', 1, 'CUST_FUNCTIONAL_GOOD', 'NON_GOOD',
            nfs.id, ism.id, 'TRANSFER_INITIATED', (select id from public.custody_transfers limit 1)
       from public.inventory_locations nfs, public.inventory_locations ism
      where nfs.code = 'NON_FUNCTIONAL_STORE' and ism.code = 'INTERMEDIATE_STORE' $$,
  'G-04%',
  'G-04: a NON_GOOD lot cannot be assigned to functional custody'
);

select throws_like(
  $$ insert into public.custody_assignments (lot_id, qty, assignment_code, condition_class,
       from_location_id, to_location_id, outcome)
     select '00000000-0000-0000-0000-00000000e421', 1, 'CUST_NON_FUNCTIONAL', 'NON_GOOD',
            ism.id, ism.id, 'ALREADY_IN_PLACE'
       from public.inventory_locations ism where ism.code = 'INTERMEDIATE_STORE' $$,
  'G-12%',
  'G-12: a non-functional assignment cannot target a FUNCTIONAL location'
);

select throws_like(
  $$ insert into public.custody_assignments (lot_id, qty, assignment_code, condition_class,
       from_location_id, to_location_id, outcome)
     select '00000000-0000-0000-0000-00000000e420', 1, 'CUST_FUNCTIONAL_REPAIRED', 'FUNCTIONAL_GOOD',
            ism.id, ism.id, 'ALREADY_IN_PLACE'
       from public.inventory_locations ism where ism.code = 'INTERMEDIATE_STORE' $$,
  'BR-30%',
  'BR-30: an assignment must match the lot condition (GOOD is not REPAIRED)'
);

select lives_ok(
  $$ insert into public.custody_assignments (lot_id, qty, assignment_code, condition_class,
       from_location_id, to_location_id, outcome)
     select '00000000-0000-0000-0000-00000000e420', 5, 'CUST_FUNCTIONAL_GOOD', 'FUNCTIONAL_GOOD',
            ism.id, ism.id, 'ALREADY_IN_PLACE'
       from public.inventory_locations ism where ism.code = 'INTERMEDIATE_STORE' $$,
  'a matching in-place assignment is recorded'
);

select throws_like(
  $$ update public.custody_assignments set notes = 'edit'
      where lot_id = '00000000-0000-0000-0000-00000000e420' $$,
  '%insert-only%',
  'custody_assignments is insert-only'
);

-- stock_lots condition guard (gap closed: in-place reclassification) ------------------------
select throws_like(
  $$ update public.stock_lots set condition_class = 'NON_GOOD'
      where id = '00000000-0000-0000-0000-00000000e420' $$,
  'G-04%',
  'G-04/G-12: a lot in the Intermediate Store cannot be edited into NON_GOOD'
);

-- stock_adjustments ------------------------------------------------------------------------
insert into public.stock_adjustments (id, lot_id, location_id, system_qty, counted_qty, reason, requested_by)
select '00000000-0000-0000-0000-00000000e430', '00000000-0000-0000-0000-00000000e420', l.id, 5, 4,
       'pgTAP count', '00000000-0000-0000-0000-00000000e401'
  from public.inventory_locations l where l.code = 'INTERMEDIATE_STORE';

select throws_like(
  $$ update public.stock_adjustments
        set status = 'REJECTED', decided_by = '00000000-0000-0000-0000-00000000e401',
            decided_at = now(), decision_remarks = 'self'
      where id = '00000000-0000-0000-0000-00000000e430' $$,
  'SEGREGATION_OF_DUTIES%',
  'the requester cannot decide their own stock adjustment'
);

select throws_like(
  $$ insert into public.stock_adjustments (lot_id, location_id, system_qty, counted_qty, reason, requested_by)
     select '00000000-0000-0000-0000-00000000e420', l.id, 0, 1, 'transit',
            '00000000-0000-0000-0000-00000000e401'
       from public.inventory_locations l where l.code = 'TRANSIT' $$,
  'G-09%',
  'G-09: stock in transit is not adjusted by a count adjustment'
);

select lives_ok(
  $$ update public.stock_adjustments
        set status = 'REJECTED', decided_by = '00000000-0000-0000-0000-00000000e402',
            decided_at = now(), decision_remarks = 'recount'
      where id = '00000000-0000-0000-0000-00000000e430' $$,
  'another user rejects the adjustment'
);

-- Injected violation (raw SQL bypass, triggers off) is detected --------------------------
set local session_replication_role = replica;
update public.stock_lots set condition_class = 'NON_GOOD'
 where id = '00000000-0000-0000-0000-00000000e420';
set local session_replication_role = origin;

select ok(
  exists (select 1 from rms_private.inventory_segregation_violations()
           where lot_id = '00000000-0000-0000-0000-00000000e420'
             and rule_code = 'NON_FUNCTIONAL_IN_FUNCTIONAL' and guard_ref = 'G-12'),
  'segregation check finds non-functional stock injected into the Intermediate Store'
);

select * from finish();
rollback;
