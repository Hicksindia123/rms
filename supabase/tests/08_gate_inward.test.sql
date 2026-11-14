-- P2-02 pgTAP: Step-1 gate inward guards (BR-01..BR-03, DD r2–r9, G-01, G-17).
begin;
create extension if not exists pgtap with schema extensions;
select plan(16);

create temporary table _ctx as
select (select v.id from public.workflow_versions v
          join public.workflow_definitions d on d.id = v.workflow_definition_id
         where d.code = 'RMS_STANDARD' and v.status = 'PUBLISHED') as wv;

-- G-01: no item without an existing goods slip (FK).
insert into public.product_categories (code, name) values ('PGTAP_G01', 'pgTAP G-01');
insert into public.products (category_id, code, name)
select id, 'PGTAP_G01_P', 'pgTAP product' from public.product_categories where code = 'PGTAP_G01';
select throws_ok(
  $$insert into public.gs_items (gs_id, line_no, product_id, category_id, documented_qty, received_qty)
    select gen_random_uuid(), 1, p.id, p.category_id, 1, 1 from public.products p where p.code = 'PGTAP_G01_P'$$,
  '23503', null, 'G-01: gs_items for a non-existent GS fails at the FK');

-- Delivery-mode conditional fields (DD r2–r4).
select throws_ok(
  $$insert into public.goods_slips (gs_no, workflow_version_id, box_count, delivery_mode_code, courier_name)
    select 'PGTAP-1', wv, 1, 'COURIER_PARCEL', 'BlueDart' from _ctx$$,
  '23514', null, 'COURIER_PARCEL requires docket_no');
select throws_ok(
  $$insert into public.goods_slips (gs_no, workflow_version_id, box_count, delivery_mode_code, vehicle_no)
    select 'PGTAP-2', wv, 1, 'DIRECT_TRUCK', 'UP80' from _ctx$$,
  '23514', null, 'DIRECT_TRUCK requires a transporter (master or name)');
select lives_ok(
  $$insert into public.goods_slips (gs_no, workflow_version_id, box_count, delivery_mode_code, vehicle_no, transporter_name)
    select 'PGTAP-3', wv, 1, 'DIRECT_TRUCK', 'UP80', 'Agra Roadways' from _ctx$$,
  'DIRECT_TRUCK with a free-text transporter name is accepted');
select throws_ok(
  $$insert into public.goods_slips (gs_no, workflow_version_id, box_count, delivery_mode_code, rep_name)
    select 'PGTAP-4', wv, 1, 'SELF_PARTY_REP', 'Ramesh' from _ctx$$,
  '23514', null, 'SELF_PARTY_REP requires rep_contact');
select throws_ok(
  $$insert into public.goods_slips (gs_no, workflow_version_id, box_count, delivery_mode_code, vehicle_no, transporter_name)
    select 'PGTAP-5', wv, 1, 'DIRECT_VEHICLE', 'UP80', 'X' from _ctx$$,
  '23514', null, 'codes outside the DELIVERY_MODE option set are rejected');

-- Gate document conditional fields (DD r5–r9, BR-03).
select throws_ok(
  $$insert into public.goods_slips (gs_no, workflow_version_id, box_count, delivery_mode_code, courier_name, docket_no, gate_document_code, gate_doc_no)
    select 'PGTAP-6', wv, 1, 'COURIER_PARCEL', 'A', '1', 'INVOICE', 'INV-1' from _ctx$$,
  '23514', null, 'INVOICE requires a document date');
select throws_ok(
  $$insert into public.goods_slips (gs_no, workflow_version_id, box_count, delivery_mode_code, courier_name, docket_no, gate_document_code)
    select 'PGTAP-7', wv, 1, 'COURIER_PARCEL', 'A', '1', 'HANDWRITTEN_SLIP' from _ctx$$,
  '23514', null, 'HANDWRITTEN_SLIP requires remarks');
select throws_ok(
  $$insert into public.goods_slips (gs_no, workflow_version_id, box_count, delivery_mode_code, courier_name, docket_no, gate_document_code)
    select 'PGTAP-8', wv, 1, 'COURIER_PARCEL', 'A', '1', 'NO_DOCUMENT' from _ctx$$,
  '23514', null, 'BR-03: NO_DOCUMENT requires missing_documentation');
select lives_ok(
  $$insert into public.goods_slips (gs_no, workflow_version_id, box_count, delivery_mode_code, courier_name, docket_no, gate_document_code, missing_documentation)
    select 'PGTAP-9', wv, 1, 'COURIER_PARCEL', 'A', '1', 'NO_DOCUMENT', true from _ctx$$,
  'NO_DOCUMENT with the flag is accepted');
select throws_ok(
  $$insert into public.goods_slips (gs_no, workflow_version_id, box_count, delivery_mode_code, courier_name, docket_no)
    select 'PGTAP-10', wv, 0, 'COURIER_PARCEL', 'A', '1' from _ctx$$,
  '23514', null, 'box_count must be > 0');

-- G-01: gs_no is immutable; cancellation lifecycle (§6.5).
select throws_ok(
  $$update public.goods_slips set gs_no = 'PGTAP-X' where gs_no = 'PGTAP-9'$$,
  '23514', null, 'G-01: the generated GS number cannot change');
select throws_ok(
  $$update public.goods_slips set status = 'CANCELLED', cancelled_at = now() where gs_no = 'PGTAP-9'$$,
  '23514', null, 'cancellation needs a reason');
-- Setup only: jump past Step-2 (the P2-03 G-02 trigger rejects this without evidence).
set local session_replication_role = replica;
update public.goods_slips set status = 'ITEMIZATION' where gs_no = 'PGTAP-3';
set local session_replication_role = origin;
select throws_ok(
  $$update public.goods_slips set status = 'CANCELLED', cancelled_at = now(), cancel_reason = 'late' where gs_no = 'PGTAP-3'$$,
  '23514', null, 'no cancellation after unboxing completes');

-- G-17: the audit row carries app.reason.
select set_config('app.reason', 'pgTAP edit reason', true);
update public.goods_slips set box_count = 2 where gs_no = 'PGTAP-9';
select set_config('app.reason', '', true);
select is(
  (select reason from public.audit_log
    where table_name = 'public.goods_slips' and action = 'UPDATE'
      and row_id = (select id::text from public.goods_slips where gs_no = 'PGTAP-9')
    order by id desc limit 1),
  'pgTAP edit reason', 'audit_log.reason is filled from app.reason');
select is(
  (select reason from public.audit_log
    where table_name = 'public.goods_slips' and action = 'INSERT'
      and row_id = (select id::text from public.goods_slips where gs_no = 'PGTAP-9')),
  null, 'no reason set → null');

select * from finish();
rollback;
