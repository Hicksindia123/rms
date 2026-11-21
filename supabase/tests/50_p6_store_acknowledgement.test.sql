-- Phase P6 pgTAP (docs/RMS_PHASE_PROMPTS_20-11-2026.md, DEC-66; migration 20261121000200):
-- only a user of the slip's Intermediate Store (or Super Admin) acknowledges it or reports a
-- discrepancy, a VOIDED slip is never acknowledged, the acknowledgement is written once, the
-- custody transfer behind a slip follows the slip (no direct accept / cancel / discrepancy), an
-- acknowledged slip is voided only after its goods came back to Inward Staging, and a GS reaches
-- STORE_ACKNOWLEDGED only when every slip of it is acknowledged.
begin;
create extension if not exists pgtap with schema extensions;
select plan(20);

insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data) values
  ('aaaaaaaa-0000-4000-8000-0000000006e1', 'pgtap-p6-re@example.test', '{"rms_activate": true}', '{"full_name": "P6 RE"}'),
  ('aaaaaaaa-0000-4000-8000-0000000006e2', 'pgtap-p6-rm@example.test', '{"rms_activate": true}', '{"full_name": "P6 RM"}'),
  ('aaaaaaaa-0000-4000-8000-0000000006e3', 'pgtap-p6-mgmt@example.test', '{"rms_activate": true}', '{"full_name": "P6 Mgmt"}'),
  ('aaaaaaaa-0000-4000-8000-0000000006e4', 'pgtap-p6-dt@example.test', '{"rms_activate": true}', '{"full_name": "P6 DT store"}'),
  ('aaaaaaaa-0000-4000-8000-0000000006e5', 'pgtap-p6-op@example.test', '{"rms_activate": true}', '{"full_name": "P6 OP store"}');
insert into public.user_roles (user_id, role_id)
select v.u::uuid, r.id
  from (values ('aaaaaaaa-0000-4000-8000-0000000006e1', 'INWARD_VERIFIER'),
               ('aaaaaaaa-0000-4000-8000-0000000006e2', 'REPLACEMENT_MANAGER'),
               ('aaaaaaaa-0000-4000-8000-0000000006e3', 'MANAGEMENT'),
               ('aaaaaaaa-0000-4000-8000-0000000006e4', 'ISTORE_DT'),
               ('aaaaaaaa-0000-4000-8000-0000000006e5', 'ISTORE_OP')) as v(u, role)
  join public.roles r on r.code = v.role;

create temp table _p6 as
select v.id as wv,
       (select p.id from public.products p
          join public.product_categories c on c.id = p.category_id and c.code = 'DMT'
         where exists (select 1 from rms_private.resolve_item_field_profile(p.id) r
                        where r.field_group = 'CATEGORISATION') limit 1) as product,
       (select id from public.intermediate_stores where code = 'DT') as dt,
       (select location_id from public.intermediate_stores where code = 'DT') as dt_loc,
       (select id from public.inventory_locations where code = 'INWARD_STAGING') as staging
  from public.workflow_versions v
  join public.workflow_definitions d on d.id = v.workflow_definition_id and d.code = 'RMS_STANDARD'
 where v.status = 'PUBLISHED';

-- Setup: two locked GSs (A, B), one DMT line of 2 each, each on its own DT slip.
insert into public.goods_slips (gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no,
                                carton_count, status, category_code, original_category_code)
select g, wv, 'COURIER_PARCEL', 'A', g, 1, 'CATEGORISATION', 'RO', 'RO'
  from _p6, (values ('PGTAP-P6-A'), ('PGTAP-P6-B')) as v(g);
insert into public.gs_items (gs_id, line_no, product_id, category_id, documented_qty, received_qty)
select g.id, 1, p.id, p.category_id, 2, 2
  from public.goods_slips g, _p6 join public.products p on p.id = _p6.product
 where g.gs_no like 'PGTAP-P6-%';
insert into public.gs_item_buckets (gs_item_id, field_id, qty)
select i.id, (select r.field_id from rms_private.resolve_item_field_profile(i.product_id) r
               where r.field_group = 'CATEGORISATION' limit 1), 2
  from public.gs_items i join public.goods_slips g on g.id = i.gs_id where g.gs_no like 'PGTAP-P6-%';
update public.goods_slips set status = 'PENDING_TRANSFER_SLIP', categorisation_locked_at = now(),
       categorisation_locked_by = 'aaaaaaaa-0000-4000-8000-0000000006e1'
 where gs_no like 'PGTAP-P6-%';

select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000006e2', true);
insert into public.custody_transfers (transfer_no, from_location_id, to_location_id, status, initiated_by)
select 'PGTAP-P6-CT-' || s, staging, dt_loc, 'INITIATED', 'aaaaaaaa-0000-4000-8000-0000000006e2'
  from _p6, (values ('A'), ('B')) as v(s);
insert into public.transfer_slips (slip_no, store_id, store_code_snapshot, store_name_snapshot,
       custody_transfer_id, relevant_qty, grand_total_qty, template_version_no)
select 'PGTAP-P6-TRF-' || s, dt, '', '', (select id from public.custody_transfers where transfer_no = 'PGTAP-P6-CT-' || s),
       2, 2, 1 from _p6, (values ('A'), ('B')) as v(s);
insert into public.transfer_slip_gs (slip_id, gs_id, gs_no_snapshot, relevant_qty, total_qty)
select s.id, g.id, '', 2, 2 from public.transfer_slips s
  join public.goods_slips g on g.gs_no = replace(s.slip_no, '-TRF-', '-')
 where s.slip_no like 'PGTAP-P6-TRF-%';
insert into public.transfer_slip_lines (slip_id, gs_id, gs_item_id, line_no_snapshot, product_id,
       product_name_snapshot, bucket_field_id, qty, is_relevant, belongs_store_id, belongs_store_name_snapshot)
select sg.slip_id, sg.gs_id, i.id, 1, i.product_id, 'X', b.field_id, 2, true, p.dt, 'DT'
  from public.transfer_slip_gs sg
  join public.transfer_slips s on s.id = sg.slip_id and s.slip_no like 'PGTAP-P6-TRF-%'
  join public.gs_items i on i.gs_id = sg.gs_id
  join public.gs_item_buckets b on b.gs_item_id = i.id, _p6 p;
update public.goods_slips set status = 'TRANSFER_SLIP_GENERATED' where gs_no like 'PGTAP-P6-%';

-- 1. The custody transfer behind a slip follows the slip.
update public.custody_transfers set stock_moved = true where transfer_no = 'PGTAP-P6-CT-A';
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000006e4', true);
select throws_like(
  $$update public.custody_transfers set status = 'ACCEPTED', acceptance_code = 'ACCEPTED_VERIFIED',
           accepted_by = 'aaaaaaaa-0000-4000-8000-0000000006e4', accepted_at = now()
     where transfer_no = 'PGTAP-P6-CT-A'$$,
  'DEC-66:%acknowledging the slip%', 'DEC-66: a slip transfer is not accepted directly');
select throws_like(
  $$update public.custody_transfers set status = 'DISCREPANCY', acceptance_code = 'DISCREPANCY',
           accepted_by = 'aaaaaaaa-0000-4000-8000-0000000006e4', accepted_at = now()
     where transfer_no = 'PGTAP-P6-CT-A'$$,
  'DEC-66 (Q13):%', 'DEC-66 / Q13: a slip transfer never goes to DISCREPANCY');
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000006e2', true);
select throws_like(
  $$update public.custody_transfers set status = 'CANCELLED', cancelled_at = now(),
           cancelled_by = 'aaaaaaaa-0000-4000-8000-0000000006e2', cancel_reason = 'x'
     where transfer_no = 'PGTAP-P6-CT-A'$$,
  'DEC-66:%voiding the slip%', 'DEC-66: a slip transfer is cancelled only by voiding the slip');

-- 2. Who acknowledges: a user of the slip's store only.
select throws_like(
  $$update public.transfer_slips set status = 'ACKNOWLEDGED', acknowledged_at = now(),
           acknowledged_by = 'aaaaaaaa-0000-4000-8000-0000000006e2' where slip_no = 'PGTAP-P6-TRF-A'$$,
  'DEC-66:%only a user of Intermediate Store DT%', 'DEC-66: the RM cannot acknowledge');
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000006e3', true);
select throws_like(
  $$update public.transfer_slips set status = 'ACKNOWLEDGED', acknowledged_at = now(),
           acknowledged_by = 'aaaaaaaa-0000-4000-8000-0000000006e3' where slip_no = 'PGTAP-P6-TRF-A'$$,
  'DEC-66:%only a user of Intermediate Store DT%', 'DEC-66: Management sees every store but does not acknowledge');
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000006e5', true);
select throws_like(
  $$update public.transfer_slips set status = 'ACKNOWLEDGED', acknowledged_at = now(),
           acknowledged_by = 'aaaaaaaa-0000-4000-8000-0000000006e5' where slip_no = 'PGTAP-P6-TRF-A'$$,
  'DEC-66:%only a user of Intermediate Store DT%', 'DEC-66: another store cannot acknowledge');
select ok(not rms_private.user_acts_for_store('aaaaaaaa-0000-4000-8000-0000000006e3', (select dt from _p6)),
  'DEC-66: Management is not a store user');

-- 3. Discrepancy reports: own store only, append-only.
select throws_like(
  $$insert into public.transfer_slip_discrepancies (slip_id, remark)
    select id, 'one short' from public.transfer_slips where slip_no = 'PGTAP-P6-TRF-A'$$,
  'DEC-66:%only a user of Intermediate Store DT%', 'DEC-66: another store cannot report a discrepancy');
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000006e4', true);
select lives_ok(
  $$insert into public.transfer_slip_discrepancies (slip_id, remark)
    select id, 'one short' from public.transfer_slips where slip_no = 'PGTAP-P6-TRF-A'$$,
  'DEC-66: the DT store reports a discrepancy');
select throws_like(
  $$delete from public.transfer_slip_discrepancies$$,
  'DEC-66:%history%', 'DEC-66: discrepancy reports are append-only');

-- 4. The goods must be in transit; then the DT user acknowledges, once.
select throws_like(
  $$update public.transfer_slips set status = 'ACKNOWLEDGED', acknowledged_at = now(),
           acknowledged_by = 'aaaaaaaa-0000-4000-8000-0000000006e4' where slip_no = 'PGTAP-P6-TRF-B'$$,
  'G-09:%not in transit%', 'G-09: a slip whose goods are not in transit cannot be acknowledged');
select lives_ok(
  $$update public.transfer_slips set status = 'ACKNOWLEDGED', acknowledged_at = now(),
           acknowledged_by = 'aaaaaaaa-0000-4000-8000-0000000006e4', acknowledge_remarks = ' ok '
     where slip_no = 'PGTAP-P6-TRF-A'$$,
  'DEC-66: the DT store user acknowledges the DT slip');
select is((select acknowledge_remarks from public.transfer_slips where slip_no = 'PGTAP-P6-TRF-A'), 'ok',
  'DEC-66: the remark is stored trimmed');
select throws_like(
  $$update public.transfer_slips set acknowledge_remarks = 'changed' where slip_no = 'PGTAP-P6-TRF-A'$$,
  'DEC-65:%change only with the status%', 'DEC-66: the acknowledgement is written once');
select throws_like(
  $$insert into public.transfer_slip_discrepancies (slip_id, remark)
    select id, 'late' from public.transfer_slips where slip_no = 'PGTAP-P6-TRF-A'$$,
  'DEC-66:%waiting for acknowledgement%', 'DEC-66: no discrepancy on an acknowledged slip');

-- 5. G-03: GS A is fully acknowledged; GS B (slip still GENERATED) is not.
select lives_ok(
  $$update public.goods_slips set status = 'STORE_ACKNOWLEDGED' where gs_no = 'PGTAP-P6-A'$$,
  'DEC-66: GS A reaches STORE_ACKNOWLEDGED');
select throws_like(
  $$update public.goods_slips set status = 'STORE_ACKNOWLEDGED' where gs_no = 'PGTAP-P6-B'$$,
  'DEC-66:%must be acknowledged%', 'DEC-66: GS B waits for its slip');

-- 6. Void (Q10): an acknowledged slip needs the return transfer; a voided slip is never acknowledged.
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000006e3', true);
select throws_like(
  $$update public.transfer_slips set status = 'VOIDED', voided_at = now(),
           voided_by = 'aaaaaaaa-0000-4000-8000-0000000006e3', void_reason = 'edited'
     where slip_no = 'PGTAP-P6-TRF-A'$$,
  'DEC-66:%back from the store to Inward Staging%', 'DEC-66: an acknowledged slip is voided only after the return');
select lives_ok(
  $$update public.transfer_slips set status = 'VOIDED', voided_at = now(),
           voided_by = 'aaaaaaaa-0000-4000-8000-0000000006e3', void_reason = 'edited'
     where slip_no = 'PGTAP-P6-TRF-B'$$,
  'DEC-65 / Q10: Management voids the GENERATED slip B');
select set_config('app.user_id', 'aaaaaaaa-0000-4000-8000-0000000006e4', true);
select throws_like(
  $$update public.transfer_slips set status = 'ACKNOWLEDGED', acknowledged_at = now(),
           acknowledged_by = 'aaaaaaaa-0000-4000-8000-0000000006e4' where slip_no = 'PGTAP-P6-TRF-B'$$,
  'DEC-65:%cannot go from VOIDED to ACKNOWLEDGED%', 'DEC-66: a VOIDED slip cannot be acknowledged');

select set_config('app.user_id', '', true);
select * from finish();
rollback;
