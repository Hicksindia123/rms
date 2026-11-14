-- P2-03 pgTAP: Step-2 unboxing evidence guards (G-02, BR-04, BR-05, DEC-03, §8.8, §9.6, G-17).
begin;
create extension if not exists pgtap with schema extensions;
select plan(24);

create temporary table _ctx as
select (select v.id from public.workflow_versions v
          join public.workflow_definitions d on d.id = v.workflow_definition_id
         where d.code = 'RMS_STANDARD' and v.status = 'PUBLISHED') as wv,
       '11111111-1111-4111-8111-111111111111'::uuid as gs_a,   -- documents path
       '22222222-2222-4222-8222-222222222222'::uuid as gs_m,   -- missing documentation path
       'aaaaaaaa-0000-4000-8000-000000000001'::uuid as rm,     -- Replacement Manager
       'aaaaaaaa-0000-4000-8000-000000000002'::uuid as aman;   -- Inward Verifier

insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data)
select rm, 'pgtap-rm@example.test', '{"rms_activate": true}'::jsonb, '{"full_name": "pgTAP RM"}'::jsonb from _ctx
union all
select aman, 'pgtap-aman@example.test', '{"rms_activate": true}'::jsonb, '{"full_name": "pgTAP Aman"}'::jsonb from _ctx;
insert into public.user_roles (user_id, role_id)
select c.rm, r.id from _ctx c, public.roles r where r.code = 'REPLACEMENT_MANAGER'
union all
select c.aman, r.id from _ctx c, public.roles r where r.code = 'INWARD_VERIFIER';

insert into public.goods_slips (id, gs_no, workflow_version_id, box_count, delivery_mode_code,
                                courier_name, docket_no, gate_document_code, gate_doc_no, gate_doc_date)
select gs_a, 'PGTAP-U1', wv, 1, 'COURIER_PARCEL', 'A', '1', 'INVOICE', 'INV-1', current_date from _ctx;
insert into public.goods_slips (id, gs_no, workflow_version_id, box_count, delivery_mode_code,
                                courier_name, docket_no, gate_document_code, missing_documentation)
select gs_m, 'PGTAP-U2', wv, 1, 'COURIER_PARCEL', 'A', '2', 'NO_DOCUMENT', true from _ctx;

-- G-02: unboxing cannot be skipped.
select throws_like(
  $$update public.goods_slips set status = 'ITEMIZATION' where gs_no = 'PGTAP-U1'$$,
  'G-02:%', 'G-02: GATE_CREATED cannot jump past UNBOXING');

-- Evidence only while UNBOXING.
select throws_ok(
  $$insert into public.attachments (gs_id, kind, bucket, object_path, mime_type, size_bytes)
    select gs_a, 'UNBOXING_VIDEO', 'rms-videos',
           'gs/' || gs_a || '/unboxing_video/00000000-0000-4000-8000-000000000001.mp4', 'video/mp4', 10
      from _ctx$$,
  '23514', null, 'evidence cannot be uploaded before unboxing starts');

update public.goods_slips set status = 'UNBOXING' where gs_no in ('PGTAP-U1', 'PGTAP-U2');

-- §8.8 / §9.6: bucket, MIME and server path per kind.
select throws_ok(
  $$insert into public.attachments (gs_id, kind, bucket, object_path, mime_type, size_bytes)
    select gs_a, 'UNBOXING_VIDEO', 'rms-documents',
           'gs/' || gs_a || '/unboxing_video/00000000-0000-4000-8000-000000000002.mp4', 'video/mp4', 10
      from _ctx$$,
  '23514', null, 'videos live in rms-videos');
select throws_ok(
  $$insert into public.attachments (gs_id, kind, bucket, object_path, mime_type, size_bytes)
    select gs_a, 'DOC_PHOTO', 'rms-documents',
           'gs/' || gs_a || '/doc_photo/00000000-0000-4000-8000-000000000003.gif', 'image/gif', 10
      from _ctx$$,
  '23514', null, 'GIF is not on the document allow-list');
select throws_ok(
  $$insert into public.attachments (gs_id, kind, bucket, object_path, mime_type, size_bytes)
    select gs_a, 'DOC_PHOTO', 'rms-documents', 'gs/' || gs_m || '/doc_photo/00000000-0000-4000-8000-000000000004.png',
           'image/png', 10 from _ctx$$,
  '23514', null, 'object path must be under the attachment''s own GS');
select throws_ok(
  $$insert into public.attachments (gs_id, kind, bucket, object_path, mime_type, size_bytes)
    select gs_a, 'DOC_PHOTO', 'rms-documents', 'gs/' || gs_a || '/doc_photo/invoice.png', 'image/png', 10 from _ctx$$,
  '23514', null, 'object names are server UUIDs, never client file names');

insert into public.attachments (id, gs_id, kind, bucket, object_path, mime_type, size_bytes, status, confirmed_at)
select 'bbbbbbbb-0000-4000-8000-000000000001', gs_a, 'UNBOXING_VIDEO', 'rms-videos',
       'gs/' || gs_a || '/unboxing_video/00000000-0000-4000-8000-000000000011.mp4', 'video/mp4', 10, 'CONFIRMED', now()
  from _ctx;
insert into public.attachments (id, gs_id, kind, bucket, object_path, mime_type, size_bytes, status, confirmed_at)
select 'bbbbbbbb-0000-4000-8000-000000000002', gs_a, 'DOC_PHOTO', 'rms-documents',
       'gs/' || gs_a || '/doc_photo/00000000-0000-4000-8000-000000000012.heic', 'image/heic', 10, 'CONFIRMED', now()
  from _ctx;
select is((select preview_unsupported from public.attachments where id = 'bbbbbbbb-0000-4000-8000-000000000002'),
  true, '§9.6: HEIC is accepted and flagged');
select throws_ok(
  $$update public.attachments set object_path = 'gs/' || gs_id || '/doc_photo/00000000-0000-4000-8000-000000000099.heic'
     where id = 'bbbbbbbb-0000-4000-8000-000000000002'$$,
  '23514', null, 'object path is immutable');

-- G-02: video alone is not enough; an unclassified photo blocks.
select throws_like(
  $$update public.goods_slips set status = 'ITEMIZATION' where gs_no = 'PGTAP-U1'$$,
  'G-02:%every confirmed document photo must be classified%', 'G-02: unclassified document photo blocks');

-- BR-05 / DD r12–r15 conditional fields.
select throws_ok(
  $$insert into public.gs_documents (gs_id, attachment_id, classification_code, doc_no, doc_date, buyer_gstin, items_verified)
    select gs_a, 'bbbbbbbb-0000-4000-8000-000000000002', 'INVOICE', 'INV-1', current_date, '09AAACH7409R1ZZ', true from _ctx$$,
  '23514', null, 'invoice needs the seller GSTIN');
select throws_ok(
  $$insert into public.gs_documents (gs_id, attachment_id, classification_code, doc_no, doc_date, buyer_gstin, seller_gstin, items_verified)
    select gs_a, 'bbbbbbbb-0000-4000-8000-000000000002', 'INVOICE', 'INV-1', current_date, '09AAACH7409R1ZZ', '07AAACB1234C1Z5', false from _ctx$$,
  '23514', null, 'invoice needs item details verified');
select throws_ok(
  $$insert into public.gs_documents (gs_id, attachment_id, classification_code, doc_no)
    select gs_a, 'bbbbbbbb-0000-4000-8000-000000000002', 'DEBIT_NOTE', 'DN-1' from _ctx$$,
  '23514', null, 'debit note needs the amount');
select throws_ok(
  $$insert into public.gs_documents (gs_id, attachment_id, classification_code)
    select gs_a, 'bbbbbbbb-0000-4000-8000-000000000002', 'DELIVERY_CHALLAN' from _ctx$$,
  '23514', null, 'challan needs the quantity-matched answer');
select throws_ok(
  $$insert into public.gs_documents (gs_id, attachment_id, classification_code)
    select gs_a, 'bbbbbbbb-0000-4000-8000-000000000002', 'NO_DOCUMENT' from _ctx$$,
  '23514', null, 'classification codes come from RECEIVED_DOC_CLASSIFICATION');
select throws_ok(
  $$insert into public.gs_documents (gs_id, attachment_id, classification_code, party_claim_text)
    select gs_a, 'bbbbbbbb-0000-4000-8000-000000000001', 'HANDWRITTEN_SLIP', 'claim' from _ctx$$,
  '23514', null, 'only a DOC_PHOTO can be classified');
select lives_ok(
  $$insert into public.gs_documents (gs_id, attachment_id, classification_code, party_claim_text)
    select gs_a, 'bbbbbbbb-0000-4000-8000-000000000002', 'HANDWRITTEN_SLIP', '3 pcs broken' from _ctx$$,
  'slip with the party claim is accepted');

select lives_ok(
  $$update public.goods_slips set status = 'ITEMIZATION' where gs_no = 'PGTAP-U1'$$,
  'G-02: video + classified photo lets the GS leave UNBOXING');
select throws_ok(
  $$update public.gs_documents set party_claim_text = 'changed' where attachment_id = 'bbbbbbbb-0000-4000-8000-000000000002'$$,
  '23514', null, 'classification is frozen after UNBOXING');
select lives_ok(
  $$update public.gs_documents set accounts_acknowledged_by = (select aman from _ctx), accounts_acknowledged_at = now()
     where attachment_id = 'bbbbbbbb-0000-4000-8000-000000000002'$$,
  'Accounts acknowledgement is still allowed (BR-06)');
select throws_like(
  $$delete from public.attachments where id = 'bbbbbbbb-0000-4000-8000-000000000001'$$,
  'G-02:%', 'G-02: confirmed evidence cannot be deleted after unboxing');

-- DEC-03: missing documentation needs an approved exception with a parcel photo.
insert into public.attachments (id, gs_id, kind, bucket, object_path, mime_type, size_bytes, status, confirmed_at)
select 'bbbbbbbb-0000-4000-8000-000000000003', gs_m, 'UNBOXING_VIDEO', 'rms-videos',
       'gs/' || gs_m || '/unboxing_video/00000000-0000-4000-8000-000000000021.mov', 'video/quicktime', 10, 'CONFIRMED', now()
  from _ctx;
insert into public.attachments (id, gs_id, kind, bucket, object_path, mime_type, size_bytes, status, confirmed_at)
select 'bbbbbbbb-0000-4000-8000-000000000004', gs_m, 'PARCEL_PHOTO', 'rms-documents',
       'gs/' || gs_m || '/parcel_photo/00000000-0000-4000-8000-000000000022.jpg', 'image/jpeg', 10, 'CONFIRMED', now()
  from _ctx;
select throws_like(
  $$update public.goods_slips set status = 'ITEMIZATION' where gs_no = 'PGTAP-U2'$$,
  'G-02:%Missing Document Exception%', 'G-02: missing documentation without an exception blocks');
insert into public.missing_doc_exceptions (id, gs_id, parcel_attachment_id, remark, requested_by)
select 'cccccccc-0000-4000-8000-000000000001', gs_m, 'bbbbbbbb-0000-4000-8000-000000000004', 'No papers', aman from _ctx;
select throws_like(
  $$update public.missing_doc_exceptions set status = 'APPROVED', decided_by = (select aman from _ctx), decided_at = now()
     where id = 'cccccccc-0000-4000-8000-000000000001'$$,
  'G-02:%unboxing.approve%', 'G-02: only a holder of unboxing.approve can approve the exception');
update public.missing_doc_exceptions set status = 'APPROVED', decided_by = (select rm from _ctx), decided_at = now()
 where id = 'cccccccc-0000-4000-8000-000000000001';
select lives_ok(
  $$update public.goods_slips set status = 'ITEMIZATION' where gs_no = 'PGTAP-U2'$$,
  'G-02: approved exception + parcel photo + video lets the GS leave UNBOXING');

-- G-17: read access is auditable.
select lives_ok(
  $$insert into public.audit_log (table_name, row_id, action, "new") values ('public.attachments', 'x', 'ACCESS', '{}')$$,
  'audit_log accepts ACCESS rows');

select * from finish();
rollback;
