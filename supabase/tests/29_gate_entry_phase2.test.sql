-- Change plan 2026-11-12 Phase 2 pgTAP: gate entry revamp (docs/RMS_MASTER_PLAN_ADDENDUM_2026-11.md).
-- AMD-01 return type · AMD-02 / DEC-38 gate entry date & number · DEC-39 E-Commerce · AMD-03 carton
-- count + G-02 per carton · AMD-04 gate document rows and GATE_DOC files · AMD-05 settings.
begin;
create extension if not exists pgtap with schema extensions;
select plan(24);

select has_table('public', 'gs_gate_documents', 'gs_gate_documents exists');
select ok(
  (select relrowsecurity from pg_class where oid = 'public.gs_gate_documents'::regclass),
  'RLS is enabled on gs_gate_documents');
select ok(
  not has_table_privilege('authenticated', 'public.gs_gate_documents', 'SELECT')
  and not has_table_privilege('anon', 'public.gs_gate_documents', 'SELECT'),
  'anon/authenticated have no access to gs_gate_documents');
select col_not_null('public', 'goods_slips', 'carton_count', 'goods_slips.carton_count is NOT NULL');
select is((select value from public.system_settings where key = 'gate.accounts_alert_doc_types'),
          '["INVOICE", "DEBIT_NOTE"]'::jsonb, 'AMD-05: Invoice and Debit Note alert Accounts by default');
select is((select value from public.system_settings where key = 'gate.max_backdate_days'),
          'null'::jsonb, 'DEC-38: no back-date limit by default');

-- Fixture helper: a raw GS (Courier) with extra columns.
create temporary table _wv as
select v.id from public.workflow_versions v
  join public.workflow_definitions d on d.id = v.workflow_definition_id
 where d.code = 'RMS_STANDARD' and v.status = 'PUBLISHED';

-- AMD-03: box_count and carton_count stay in sync both ways.
insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count)
select 'PGTAP-PH2-1', id, 'COURIER_PARCEL', 'A', '1', 3 from _wv;
select is((select box_count from public.goods_slips where gs_no = 'PGTAP-PH2-1'), 3,
          'AMD-03: an insert with carton_count fills box_count');
update public.goods_slips set box_count = 2 where gs_no = 'PGTAP-PH2-1';
select is((select carton_count from public.goods_slips where gs_no = 'PGTAP-PH2-1'), 2,
          'AMD-03: a legacy box_count update moves carton_count');

-- AMD-01 / AMD-02 / DEC-39
select throws_like(
  $$insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count, return_type_code)
    select 'PGTAP-PH2-X', id, 'COURIER_PARCEL', 'A', '1', 1, 'WALK_IN' from _wv$$,
  '%AMD-01%', 'AMD-01: unknown return type rejected');
select throws_like(
  $$insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count, return_type_code)
    select 'PGTAP-PH2-X', id, 'COURIER_PARCEL', 'A', '1', 1, 'OFFLINE_RETURN' from _wv$$,
  '%goods_slips_offline_gate_entry%', 'AMD-02: Offline without gate entry date / number rejected');
select throws_like(
  $$insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count, return_type_code, gate_entry_date, gate_entry_no)
    select 'PGTAP-PH2-X', id, 'COURIER_PARCEL', 'A', '1', 1, 'ECOMMERCE_RETURN', current_date - 1, 5 from _wv$$,
  '%goods_slips_ecommerce_no_gate_entry%', 'DEC-39: E-Commerce with a gate entry rejected');
select throws_like(
  $$insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count, return_type_code, gate_entry_date, gate_entry_no)
    select 'PGTAP-PH2-X', id, 'COURIER_PARCEL', 'A', '1', 1, 'OFFLINE_RETURN', rms_private.business_today() + 1, 5 from _wv$$,
  '%AMD-02%later than today%', 'AMD-02: a future gate entry date rejected');

insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count, return_type_code, gate_entry_date, gate_entry_no)
select 'PGTAP-PH2-2', id, 'COURIER_PARCEL', 'A', '1', 1, 'OFFLINE_RETURN', date '2026-05-10', 987654321 from _wv;
select is((select gate_entry_fy from public.goods_slips where gs_no = 'PGTAP-PH2-2'), 2026::smallint,
          'DEC-38: FY derived from the gate entry date (April start)');
select throws_like(
  $$insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count, return_type_code, gate_entry_date, gate_entry_no)
    select 'PGTAP-PH2-3', id, 'COURIER_PARCEL', 'A', '1', 1, 'OFFLINE_RETURN', date '2026-04-01', 987654321 from _wv$$,
  '%goods_slips_gate_entry_no_fy_key%', 'DEC-38: gate entry number unique within the financial year');
select lives_ok(
  $$insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count, return_type_code, gate_entry_date, gate_entry_no)
    select 'PGTAP-PH2-4', id, 'COURIER_PARCEL', 'A', '1', 1, 'OFFLINE_RETURN', date '2026-03-31', 987654321 from _wv$$,
  'DEC-38: the same number is allowed in the previous financial year');
update public.system_settings set value = '3' where key = 'gate.max_backdate_days';
select throws_like(
  $$insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count, return_type_code, gate_entry_date, gate_entry_no)
    select 'PGTAP-PH2-X', id, 'COURIER_PARCEL', 'A', '1', 1, 'OFFLINE_RETURN', rms_private.business_today() - 4, 11 from _wv$$,
  '%DEC-38%', 'DEC-38: the configured back-date limit is enforced');
select throws_ok(
  $$update public.system_settings set value = '-1' where key = 'gate.max_backdate_days'$$,
  '23514', null, 'DEC-38: a negative back-date limit is rejected');

-- AMD-04 document rows
select throws_like(
  $$insert into public.gs_gate_documents (gs_id, doc_type_code, doc_type_label)
    select id, 'NO_DOCUMENT', 'No Document' from public.goods_slips where gs_no = 'PGTAP-PH2-1'$$,
  '%gs_gate_documents_doc_type_code_check%', 'AMD-04: NO_DOCUMENT is a GS flag, not a row type');
select throws_like(
  $$insert into public.gs_gate_documents (gs_id, doc_type_code, doc_type_label, doc_no)
    select id, 'INVOICE', 'Invoice', 'INV-1' from public.goods_slips where gs_no = 'PGTAP-PH2-1'$$,
  '%gs_gate_documents_formal_fields%', 'DD r5: an invoice row needs number and date');
select lives_ok(
  $$insert into public.gs_gate_documents (gs_id, doc_type_code, doc_type_label, doc_no)
    select id, 'COURIER_SLIP', 'Courier Slip', 'AWB-1' from public.goods_slips where gs_no = 'PGTAP-PH2-1'$$,
  'AMD-04: a courier slip row is accepted at the gate');
select throws_like(
  $$update public.goods_slips set missing_documentation = true where gs_no = 'PGTAP-PH2-1'$$,
  '%remove the document rows%', 'DEC-03: "no document" cannot be set while rows exist');
select throws_like(
  $$insert into public.attachments (gs_id, kind, bucket, object_path, mime_type, size_bytes)
    select id, 'GATE_DOC', 'rms-documents',
           'gs/' || id || '/gate_doc/' || gen_random_uuid() || '.png', 'image/png', 10
      from public.goods_slips where gs_no = 'PGTAP-PH2-1'$$,
  '%attachments_gate_document_link%', 'AMD-04: a GATE_DOC file must belong to a document row');

-- Gate rows are frozen once the GS left the gate (status set without the workflow triggers).
set local session_replication_role = replica;
update public.goods_slips set status = 'UNBOXING' where gs_no = 'PGTAP-PH2-1';
set local session_replication_role = origin;
select throws_like(
  $$delete from public.gs_gate_documents
     where gs_id = (select id from public.goods_slips where gs_no = 'PGTAP-PH2-1')$$,
  '%only change while the GS is at the gate%', 'AMD-04: gate rows cannot change after the gate');

-- G-02 per carton (AMD-03): 2 cartons, one video → cannot leave UNBOXING.
update public.goods_slips set carton_count = 2 where gs_no = 'PGTAP-PH2-1';
set local session_replication_role = replica;
insert into public.attachments (gs_id, kind, bucket, object_path, mime_type, size_bytes, box_no, status, confirmed_at)
select id, 'UNBOXING_VIDEO', 'rms-videos', 'gs/' || id || '/unboxing_video/' || gen_random_uuid() || '.mp4',
       'video/mp4', 10, 1, 'CONFIRMED', now()
  from public.goods_slips where gs_no = 'PGTAP-PH2-1';
set local session_replication_role = origin;
select throws_like(
  $$update public.goods_slips set status = 'ITEMIZATION' where gs_no = 'PGTAP-PH2-1'$$,
  '%G-02%every carton (missing carton 2)%', 'G-02 / AMD-03: one confirmed video per carton');

select * from finish();
rollback;
