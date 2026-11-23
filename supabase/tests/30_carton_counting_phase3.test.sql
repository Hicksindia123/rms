-- Change plan 2026-11-12 Phase 3 pgTAP: Carton Opening & Counting (AMD-04, AMD-08; BR-07; G-01, G-03).
begin;
create extension if not exists pgtap with schema extensions;
select plan(11);

-- AMD-08: status labels are configuration; every status code has exactly one label.
select set_eq(
  $$select oi.code from public.option_items oi join public.option_sets os on os.id = oi.option_set_id
     where os.code = 'GS_STATUS'$$,
  $$values ('GATE_CREATED'),('UNBOXING'),('ITEMIZATION'),('CATEGORISATION'),('CSR_APPROVAL_PENDING'),
           ('INSPECTION'),('RM_REVIEW'),('PENDING_TRANSFER_SLIP'),('TRANSFER_SLIP_GENERATED'),('STORE_ACKNOWLEDGED'),('STORE_PROCESSING'),('ANALYSIS_COMPLETED'),('SALES_RETURN_HOLD'),('HELD_AT_INTERMEDIATE_STORE'),('IN_PROCESS'),('COMMERCIAL_RESOLUTION'),
           ('AWAITING_NOTIFICATION'),('CLOSED'),('CANCELLED')$$,
  'GS_STATUS labels cover exactly the goods_slips status codes');
select is((select oi.label from public.option_items oi join public.option_sets os on os.id = oi.option_set_id
            where os.code = 'GS_STATUS' and oi.code = 'UNBOXING'), 'Carton Opening', 'UNBOXING is labelled Carton Opening');
select is((select s.label from public.workflow_steps s
             join public.workflow_versions v on v.id = s.workflow_version_id and v.status = 'PUBLISHED'
             join public.workflow_definitions d on d.id = v.workflow_definition_id and d.code = 'RMS_STANDARD'
            where s.code = 'S1_UNBOX'), 'Step-2 Carton Opening', 'published workflow labels S1_UNBOX Carton Opening (codes unchanged)');

-- Fixture: a GS in counting (status set without the workflow triggers) and a product.
insert into public.products (code, name, category_id)
select 'PGTAP-PH3-P', 'pgTAP Phase 3 product', id from public.product_categories where code = 'DMT';
insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count)
select 'PGTAP-PH3-1', v.id, 'COURIER_PARCEL', 'A', '1', 1
  from public.workflow_versions v join public.workflow_definitions d on d.id = v.workflow_definition_id
 where d.code = 'RMS_STANDARD' and v.status = 'PUBLISHED';
set local session_replication_role = replica;
update public.goods_slips set status = 'ITEMIZATION' where gs_no = 'PGTAP-PH3-1';
set local session_replication_role = origin;

select throws_like(
  $$update public.goods_slips set status = 'CATEGORISATION' where gs_no = 'PGTAP-PH3-1'$$,
  'G-01:%counting cannot be submitted%', 'G-01: an empty count cannot be submitted');
insert into public.gs_items (gs_id, line_no, product_id, category_id, documented_qty, received_qty)
select g.id, 1, p.id, p.category_id, 0, 3
  from public.goods_slips g, public.products p where g.gs_no = 'PGTAP-PH3-1' and p.code = 'PGTAP-PH3-P';
select throws_like(
  $$update public.goods_slips set category_code = 'RO', original_category_code = 'RO', status = 'INSPECTION'
     where gs_no = 'PGTAP-PH3-1'$$,
  'G-03:%counting is submitted%', 'G-03: counting cannot skip CATEGORISATION');
select lives_ok(
  $$update public.goods_slips set status = 'CATEGORISATION' where gs_no = 'PGTAP-PH3-1'$$,
  'AMD-08: counting with a line is submitted to CATEGORISATION');
-- DEC-64 (P4): lines stay editable in CATEGORISATION until the categorisation lock.
select lives_ok(
  $$insert into public.gs_items (gs_id, line_no, product_id, category_id, documented_qty, received_qty)
    select g.id, 2, p.id, p.category_id, 0, 1
      from public.goods_slips g, public.products p where g.gs_no = 'PGTAP-PH3-1' and p.code = 'PGTAP-PH3-P'$$,
  'DEC-64: a line can still be added in CATEGORISATION (before the lock)');
delete from public.gs_items where line_no = 2
   and gs_id = (select id from public.goods_slips where gs_no = 'PGTAP-PH3-1');
select throws_like(
  $$update public.goods_slips set status = 'INSPECTION' where gs_no = 'PGTAP-PH3-1'$$,
  'G-03:%without a category%', 'G-03: categorisation needs a category');
select lives_ok(
  $$update public.goods_slips set category_code = 'RO', original_category_code = 'RO', status = 'INSPECTION'
     where gs_no = 'PGTAP-PH3-1'$$,
  'BR-07: RO goes from CATEGORISATION to INSPECTION');
select throws_like(
  $$update public.goods_slips set status = 'CATEGORISATION' where gs_no = 'PGTAP-PH3-1'$$,
  'G-03:%only a GS in counting%', 'G-03: nothing but a submitted count reaches CATEGORISATION');

-- AMD-04: a carton-opening document row accepts files only while the GS is UNBOXING.
insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count)
select 'PGTAP-PH3-2', v.id, 'COURIER_PARCEL', 'A', '2', 1
  from public.workflow_versions v join public.workflow_definitions d on d.id = v.workflow_definition_id
 where d.code = 'RMS_STANDARD' and v.status = 'PUBLISHED';
set local session_replication_role = replica;
update public.goods_slips set status = 'UNBOXING' where gs_no = 'PGTAP-PH3-2';
insert into public.gs_gate_documents (gs_id, doc_type_code, doc_type_label, doc_no, source_step)
select id, 'COURIER_SLIP', 'Courier Slip', 'AWB-PH3', 'S1_UNBOX' from public.goods_slips where gs_no = 'PGTAP-PH3-2';
update public.goods_slips set status = 'ITEMIZATION' where gs_no = 'PGTAP-PH3-2';
set local session_replication_role = origin;
select throws_like(
  $$insert into public.attachments (gs_id, kind, bucket, object_path, mime_type, size_bytes, gate_document_id)
    select g.id, 'GATE_DOC', 'rms-documents', 'gs/' || g.id || '/gate_doc/' || gen_random_uuid() || '.png',
           'image/png', 10, d.id
      from public.goods_slips g join public.gs_gate_documents d on d.gs_id = g.id
     where g.gs_no = 'PGTAP-PH3-2'$$,
  '%AMD-04%can no longer be added%', 'AMD-04: carton-opening document files only while UNBOXING');

select * from finish();
rollback;
