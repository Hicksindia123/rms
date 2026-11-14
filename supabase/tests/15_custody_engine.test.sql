-- =============================================================================
-- pgTAP Test: 15_custody_engine.test.sql
-- Prompt: P3-01 — custody transfer engine (migration 20261104000100). Database half of G-09:
-- transfer state machine, ACCEPTED only with matching counts, lines frozen once dispatched,
-- TRANSIT movements bound to a transfer in the matching state and capped at the quantity sent,
-- segregation of duties, reconciliation signatures / immutability.
-- =============================================================================

begin;
select plan(21);

select has_table('public', 'custody_reconciliations', 'custody_reconciliations exists');
select has_trigger('public', 'custody_transfers', 'custody_transfers_g09_guard', 'G-09 state machine trigger');
select has_trigger('public', 'custody_transfer_lines', 'custody_transfer_lines_g09_guard', 'G-09 line freeze trigger');
select has_trigger('public', 'stock_movements', 'stock_movements_g09_transit_guard', 'G-09 TRANSIT movement trigger');

-- Users: Aman (initiator) and Sahil (receiver).
insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data) values
  ('00000000-0000-0000-0000-00000000c101', 'pgtap-p301-aman@example.test',
   '{"rms_activate": true}'::jsonb, '{"full_name": "Aman"}'::jsonb),
  ('00000000-0000-0000-0000-00000000c102', 'pgtap-p301-sahil@example.test',
   '{"rms_activate": true}'::jsonb, '{"full_name": "Sahil"}'::jsonb);

-- Fixture (triggers off for setup only): a GS with one AS_RECEIVED lot of 5 in INWARD_STAGING and
-- an INITIATED transfer of 3 to the Intermediate Store.
set local session_replication_role = replica;
-- AMD-03 (change plan Phase 2): triggers are off here, so carton_count is set explicitly.
insert into public.goods_slips (id, gs_no, workflow_version_id, delivery_mode_code, courier_name,
                                docket_no, box_count, carton_count, status)
select '00000000-0000-0000-0000-00000000c201', 'PGTAP/P301/0001', v.id, 'COURIER_PARCEL', 'BlueDart',
       'PGTAP-P301', 1, 1, 'IN_PROCESS'
  from public.workflow_versions v where v.status = 'PUBLISHED' limit 1;
insert into public.stock_items (id, item_kind, product_id)
select '00000000-0000-0000-0000-00000000c202', 'FINISHED_GOOD', p.id from public.products p limit 1;
insert into public.stock_lots (id, stock_item_id, gs_id, condition_class)
values ('00000000-0000-0000-0000-00000000c203', '00000000-0000-0000-0000-00000000c202',
        '00000000-0000-0000-0000-00000000c201', 'AS_RECEIVED');
insert into public.custody_transfers (id, transfer_no, gs_id, from_location_id, to_location_id,
                                      mode_code, status, stock_moved, initiated_by)
select '00000000-0000-0000-0000-00000000c204', 'PGTAP/TRF/P301',
       '00000000-0000-0000-0000-00000000c201',
       (select id from public.inventory_locations where code = 'INWARD_STAGING'),
       (select id from public.inventory_locations where code = 'INTERMEDIATE_STORE'),
       'PHYSICAL_AND_DIGITAL', 'INITIATED', false, '00000000-0000-0000-0000-00000000c101';
insert into public.custody_transfer_lines (transfer_id, lot_id, qty_sent)
values ('00000000-0000-0000-0000-00000000c204', '00000000-0000-0000-0000-00000000c203', 3);
set local session_replication_role = origin;

select rms_private.rms_move_stock('00000000-0000-0000-0000-00000000c203', null,
  (select id from public.inventory_locations where code = 'INWARD_STAGING'), 5, 'INWARD',
  null, null, 'pgtap-p301-inward');

select throws_like(
  $$ select rms_private.rms_move_stock('00000000-0000-0000-0000-00000000c203',
       (select id from public.inventory_locations where code = 'INWARD_STAGING'),
       (select id from public.inventory_locations where code = 'TRANSIT'), 1, 'TRANSFER_OUT',
       null, null, 'pgtap-p301-no-ref') $$,
  'G-09:%', 'stock enters TRANSIT only through a custody transfer');

update public.custody_transfers
   set stock_moved = true, stock_moved_at = now(),
       transit_location_id = (select id from public.inventory_locations where code = 'TRANSIT')
 where id = '00000000-0000-0000-0000-00000000c204';

select lives_ok(
  $$ select rms_private.rms_move_stock('00000000-0000-0000-0000-00000000c203',
       (select id from public.inventory_locations where code = 'INWARD_STAGING'),
       (select id from public.inventory_locations where code = 'TRANSIT'), 3, 'TRANSFER_OUT',
       'custody_transfer', '00000000-0000-0000-0000-00000000c204', 'pgtap-p301-dispatch') $$,
  'the INITIATED transfer dispatches its quantity into TRANSIT');

select throws_like(
  $$ select rms_private.rms_move_stock('00000000-0000-0000-0000-00000000c203',
       (select id from public.inventory_locations where code = 'INWARD_STAGING'),
       (select id from public.inventory_locations where code = 'TRANSIT'), 1, 'TRANSFER_OUT',
       'custody_transfer', '00000000-0000-0000-0000-00000000c204', 'pgtap-p301-extra') $$,
  'G-09:%', 'a transfer never dispatches more than the quantity sent');

select throws_like(
  $$ select rms_private.rms_move_stock('00000000-0000-0000-0000-00000000c203',
       (select id from public.inventory_locations where code = 'TRANSIT'),
       (select id from public.inventory_locations where code = 'INTERMEDIATE_STORE'), 3, 'TRANSFER_IN',
       'custody_transfer', '00000000-0000-0000-0000-00000000c204', 'pgtap-p301-early') $$,
  'G-09:%', 'the receiver is credited only after acceptance');

select throws_like(
  $$ update public.custody_transfer_lines set qty_sent = 2
      where transfer_id = '00000000-0000-0000-0000-00000000c204' $$,
  'G-09:%', 'lines are frozen once the stock moved');

select throws_like(
  $$ update public.custody_transfers
        set status = 'ACCEPTED', acceptance_code = 'ACCEPTED_VERIFIED',
            accepted_by = '00000000-0000-0000-0000-00000000c102', accepted_at = now()
      where id = '00000000-0000-0000-0000-00000000c204' $$,
  'G-09:%', 'a transfer whose count differs from the quantity sent cannot be ACCEPTED');

select throws_like(
  $$ update public.custody_transfers
        set status = 'DISCREPANCY', acceptance_code = 'DISCREPANCY',
            accepted_by = '00000000-0000-0000-0000-00000000c101', accepted_at = now()
      where id = '00000000-0000-0000-0000-00000000c204' $$,
  'SEGREGATION_OF_DUTIES:%', 'the initiator cannot record the receipt (segregation of duties)');

select throws_like(
  $$ update public.custody_transfers set status = 'RECONCILED'
      where id = '00000000-0000-0000-0000-00000000c204' $$,
  'G-09:%', 'INITIATED cannot jump to RECONCILED');

-- Sahil counts 2 of 3: discrepancy (frozen in TRANSIT).
update public.custody_transfer_lines set qty_counted = 2
 where transfer_id = '00000000-0000-0000-0000-00000000c204';
select lives_ok(
  $$ update public.custody_transfers
        set status = 'DISCREPANCY', acceptance_code = 'DISCREPANCY', discrepancy_notes = 'one short',
            accepted_by = '00000000-0000-0000-0000-00000000c102', accepted_at = now()
      where id = '00000000-0000-0000-0000-00000000c204' $$,
  'the receiver reports a discrepancy');

select throws_like(
  $$ update public.custody_transfer_lines set qty_counted = 3
      where transfer_id = '00000000-0000-0000-0000-00000000c204' $$,
  'G-09:%', 'the recorded count cannot be rewritten');

select throws_like(
  $$ select rms_private.rms_move_stock('00000000-0000-0000-0000-00000000c203',
       (select id from public.inventory_locations where code = 'TRANSIT'),
       (select id from public.inventory_locations where code = 'INWARD_STAGING'), 3, 'TRANSFER_IN',
       'custody_transfer', '00000000-0000-0000-0000-00000000c204', 'pgtap-p301-frozen') $$,
  'G-09:%', 'a discrepancy freezes the stock in TRANSIT');

select throws_like(
  $$ update public.custody_transfers set status = 'RECONCILED'
      where id = '00000000-0000-0000-0000-00000000c204' $$,
  'G-09:%', 'RECONCILED needs an applied reconciliation');

-- Two signatures by the same person are impossible.
select throws_like(
  $$ insert into public.custody_reconciliations (transfer_id, resolution_code, notes, proposed_by,
       initiator_signed_by, receiver_signed_by)
     values ('00000000-0000-0000-0000-00000000c204', 'CANCEL_RETURN', 'x',
       '00000000-0000-0000-0000-00000000c101', '00000000-0000-0000-0000-00000000c101',
       '00000000-0000-0000-0000-00000000c101') $$,
  '%custody_reconciliations_check%', 'one person cannot sign for both parties');

insert into public.custody_reconciliations (id, transfer_id, resolution_code, notes, proposed_by,
  initiator_signed_by, initiator_signed_at, receiver_signed_by, receiver_signed_at)
values ('00000000-0000-0000-0000-00000000c205', '00000000-0000-0000-0000-00000000c204',
  'CANCEL_RETURN', 'return everything', '00000000-0000-0000-0000-00000000c101',
  '00000000-0000-0000-0000-00000000c101', now(), '00000000-0000-0000-0000-00000000c102', now());
update public.custody_reconciliations set status = 'APPLIED', applied_at = now()
 where id = '00000000-0000-0000-0000-00000000c205';

select lives_ok(
  $$ update public.custody_transfers set status = 'RECONCILED', resolution_code = 'CANCEL_RETURN'
      where id = '00000000-0000-0000-0000-00000000c204' $$,
  'with an applied two-signature reconciliation the transfer is RECONCILED');

select lives_ok(
  $$ select rms_private.rms_move_stock('00000000-0000-0000-0000-00000000c203',
       (select id from public.inventory_locations where code = 'TRANSIT'),
       (select id from public.inventory_locations where code = 'INWARD_STAGING'), 3, 'TRANSFER_IN',
       'custody_transfer', '00000000-0000-0000-0000-00000000c204', 'pgtap-p301-return') $$,
  'the reconciled transfer returns its stock to the source');

select is(
  (select qty from public.stock_balances
    where lot_id = '00000000-0000-0000-0000-00000000c203'
      and location_id = (select id from public.inventory_locations where code = 'TRANSIT')),
  0, 'TRANSIT is back to zero');

select throws_like(
  $$ update public.custody_reconciliations set notes = 'changed'
      where id = '00000000-0000-0000-0000-00000000c205' $$,
  'G-09:%', 'an applied reconciliation is immutable');

select * from finish();
rollback;
