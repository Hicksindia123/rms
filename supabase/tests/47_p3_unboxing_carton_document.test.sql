-- Phase P3 pgTAP (docs/RMS_PHASE_PROMPTS_20-11-2026.md, DEC-62, DEC-63; migration 20261120000300):
-- the one optional "document found in carton" (doc_source CARTON) and the retired exception table.
begin;
create extension if not exists pgtap with schema extensions;
select plan(9);

create temporary table _wv as
select v.id from public.workflow_versions v
  join public.workflow_definitions d on d.id = v.workflow_definition_id
 where d.code = 'RMS_STANDARD' and v.status = 'PUBLISHED';

-- A GS flagged "No Documents From Party" (BR-03) and a normal one, both UNBOXING.
insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no,
                                carton_count, missing_documentation)
select 'PGTAP-P3-1', id, 'COURIER_PARCEL', 'A', '1', 1, true from _wv
union all
select 'PGTAP-P3-2', id, 'COURIER_PARCEL', 'A', '2', 1, false from _wv;
update public.goods_slips set status = 'UNBOXING' where gs_no in ('PGTAP-P3-1', 'PGTAP-P3-2');

select lives_ok(
  $$insert into public.gs_gate_documents (gs_id, doc_type_code, doc_type_label, source_step, doc_source)
    select id, 'INVOICE', 'Invoice', 'S1_UNBOX', 'CARTON' from public.goods_slips where gs_no = 'PGTAP-P3-1'$$,
  'P3: a carton document is allowed on a GS flagged "No Documents From Party"');
select is((select missing_documentation from public.goods_slips where gs_no = 'PGTAP-P3-1'), true,
  'BR-03: the gate flag stays as recorded');
select throws_ok(
  $$insert into public.gs_gate_documents (gs_id, doc_type_code, doc_type_label, source_step, doc_source)
    select id, 'DEBIT_NOTE', 'GST Debit Note', 'S1_UNBOX', 'CARTON' from public.goods_slips where gs_no = 'PGTAP-P3-1'$$,
  '23505', null, 'P3: at most one carton document per GS');
select throws_ok(
  $$insert into public.gs_gate_documents (gs_id, doc_type_code, doc_type_label, source_step, doc_source, doc_no)
    select id, 'INVOICE', 'Invoice', 'S1_UNBOX', 'CARTON', 'INV-9' from public.goods_slips where gs_no = 'PGTAP-P3-2'$$,
  '23514', null, 'DEC-62: a carton document has no document number');
select throws_ok(
  $$insert into public.gs_gate_documents (gs_id, doc_type_code, doc_type_label, source_step, doc_source, doc_date)
    select id, 'INVOICE', 'Invoice', 'S1_UNBOX', 'CARTON', current_date from public.goods_slips where gs_no = 'PGTAP-P3-2'$$,
  '23514', null, 'DEC-62: a carton document has no document date');
select throws_ok(
  $$insert into public.gs_gate_documents (gs_id, doc_type_code, doc_type_label, source_step, doc_source)
    select id, 'DELIVERY_CHALLAN', 'Delivery Challan', 'S1_UNBOX', 'CARTON' from public.goods_slips where gs_no = 'PGTAP-P3-2'$$,
  '23514', null, 'DEC-62: an inactive document type is refused');
select throws_ok(
  $$insert into public.gs_gate_documents (gs_id, doc_type_code, doc_type_label, source_step, doc_source)
    select id, 'HANDWRITTEN_SLIP', 'Hand Written Slip', 'S1_GATE', 'CARTON' from public.goods_slips where gs_no = 'PGTAP-P3-2'$$,
  '23514', null, 'DEC-62: a carton document belongs to the unboxing step');
select throws_ok(
  $$insert into public.gs_gate_documents (gs_id, doc_type_code, doc_type_label, source_step, doc_no, doc_date)
    select id, 'INVOICE', 'Invoice', 'S1_UNBOX', 'INV-1', current_date from public.goods_slips where gs_no = 'PGTAP-P3-1'$$,
  '23514', null, 'legacy carton rows (no source) are still excluded by the "no document" flag');
select ok(
  obj_description('public.missing_doc_exceptions'::regclass, 'pg_class') like '%RETIRED by DEC-63%',
  'DEC-63: missing_doc_exceptions is documented as read-only history');

select * from finish();
rollback;
