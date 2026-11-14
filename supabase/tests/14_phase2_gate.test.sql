-- =============================================================================
-- pgTAP Test: 14_phase2_gate.test.sql
-- Prompt: P2-08 — Phase 2 gate. Database enforcement of G-08 (migration 20261103000700):
-- Pending (BP) lots cannot be put on a custody transfer, and a GS with an open pendency cannot
-- advance into Stage-6 (always) or into handover (when pending_blocks_entire_gs is on).
-- =============================================================================

begin;
select plan(7);

select has_trigger('public', 'custody_transfer_lines', 'custody_transfer_lines_g08_guard',
  'custody_transfer_lines has the G-08 trigger');
select has_trigger('public', 'goods_slips', 'goods_slips_g08_guard',
  'goods_slips has the G-08 status trigger');

-- Fixture (triggers off for setup only): a GS in RM_REVIEW with a Pending (BP) lot + pendency.
set local session_replication_role = replica;
-- AMD-03 (change plan Phase 2): triggers are off here, so carton_count is set explicitly.
insert into public.goods_slips (id, gs_no, workflow_version_id, delivery_mode_code, courier_name,
                                docket_no, box_count, carton_count, status)
select '00000000-0000-0000-0000-00000000a801', 'PGTAP/G08/0001', v.id, 'COURIER_PARCEL', 'BlueDart',
       'PGTAP-G08', 1, 1, 'RM_REVIEW'
  from public.workflow_versions v where v.status = 'PUBLISHED' limit 1;
insert into public.stock_items (id, item_kind, product_id)
select '00000000-0000-0000-0000-00000000a802', 'FINISHED_GOOD', p.id from public.products p limit 1;
insert into public.stock_lots (id, stock_item_id, gs_id, condition_class, is_pending)
values ('00000000-0000-0000-0000-00000000a803', '00000000-0000-0000-0000-00000000a802',
        '00000000-0000-0000-0000-00000000a801', 'AS_RECEIVED', true);
insert into public.pendencies (gs_id, qty, reason, blocks_gs, opened_by)
values ('00000000-0000-0000-0000-00000000a801', 2, 'pgTAP pendency', false,
        '00000000-0000-0000-0000-00000000a8ff');
insert into public.custody_transfers (id, transfer_no, gs_id, from_location_id, to_location_id,
                                      mode_code, status, stock_moved, initiated_by)
select '00000000-0000-0000-0000-00000000a804', 'PGTAP/TRF/0001',
       '00000000-0000-0000-0000-00000000a801',
       (select id from public.inventory_locations where code = 'PENDING_HOLD'),
       (select id from public.inventory_locations where code = 'INTERMEDIATE_STORE'),
       'PHYSICAL_AND_DIGITAL', 'INITIATED', false, '00000000-0000-0000-0000-00000000a8ff';
set local session_replication_role = origin;

select throws_like(
  $$ insert into public.custody_transfer_lines (transfer_id, lot_id, qty_sent)
     values ('00000000-0000-0000-0000-00000000a804', '00000000-0000-0000-0000-00000000a803', 2) $$,
  'G-08:%',
  'a Pending (BP) lot cannot be added to a custody transfer'
);

select throws_like(
  $$ update public.goods_slips set status = 'CLOSED'
      where id = '00000000-0000-0000-0000-00000000a801' $$,
  'G-08:%',
  'a GS with an open pendency cannot be closed'
);

select throws_like(
  $$ update public.goods_slips set status = 'COMMERCIAL_RESOLUTION'
      where id = '00000000-0000-0000-0000-00000000a801' $$,
  'G-08:%',
  'a GS with an open pendency cannot enter Stage-6 commercial resolution'
);

update public.system_settings set value = 'true'::jsonb where key = 'pending_blocks_entire_gs';
select throws_like(
  $$ update public.goods_slips set status = 'IN_PROCESS'
      where id = '00000000-0000-0000-0000-00000000a801' $$,
  'G-08:%',
  'with pending_blocks_entire_gs on, the GS cannot leave RM_REVIEW for handover'
);

select is(
  (select status from public.goods_slips where id = '00000000-0000-0000-0000-00000000a801'),
  'RM_REVIEW',
  'the GS stayed in RM_REVIEW'
);

select * from finish();
rollback;
