-- P2-04 pgTAP: Step-3 categorisation & CSR decision guards (BR-07, BR-08, G-03, G-17, DEC-27).
begin;
create extension if not exists pgtap with schema extensions;
select plan(22);

create temporary table _ctx as
select (select v.id from public.workflow_versions v
          join public.workflow_definitions d on d.id = v.workflow_definition_id
         where d.code = 'RMS_STANDARD' and v.status = 'PUBLISHED') as wv,
       '33333333-3333-4333-8333-333333333333'::uuid as gs_c,   -- CSR path
       '44444444-4444-4444-8444-444444444444'::uuid as gs_r,   -- RO path
       'bbbbbbbb-0000-4000-8000-000000000001'::uuid as rm,
       'bbbbbbbb-0000-4000-8000-000000000002'::uuid as aman,
       'bbbbbbbb-0000-4000-8000-000000000003'::uuid as item_c;

insert into auth.users (id, email, raw_app_meta_data, raw_user_meta_data)
select rm, 'pgtap-p204-rm@example.test', '{"rms_activate": true}'::jsonb, '{"full_name": "RM"}'::jsonb from _ctx
union all
select aman, 'pgtap-p204-aman@example.test', '{"rms_activate": true}'::jsonb, '{"full_name": "Aman"}'::jsonb from _ctx;
insert into public.user_roles (user_id, role_id)
select c.rm, r.id from _ctx c, public.roles r where r.code = 'REPLACEMENT_MANAGER'
union all
select c.aman, r.id from _ctx c, public.roles r where r.code = 'INWARD_VERIFIER';

-- Own fixture products, so the test does not depend on the DEMO seed block (reset-db removes it).
insert into public.products (code, name, category_id)
select v.code, v.name, c.id
  from (values ('PGTAP-DMT-001', 'pgTAP DMT product', 'DMT'),
               ('PGTAP-PRS-001', 'pgTAP Prismatic product', 'PRISMATIC')) as v(code, name, category)
  join public.product_categories c on c.code = v.category;

insert into public.goods_slips (id, gs_no, workflow_version_id, box_count, delivery_mode_code,
                                courier_name, docket_no, gate_document_code, gate_doc_no, gate_doc_date)
select gs_c, 'PGTAP-I1', wv, 1, 'COURIER_PARCEL', 'A', '1', 'INVOICE', 'INV-1', current_date from _ctx
union all
select gs_r, 'PGTAP-I2', wv, 1, 'COURIER_PARCEL', 'A', '2', 'INVOICE', 'INV-2', current_date from _ctx;

-- Setup only: skip Step-2 evidence (G-02 is covered by 09_unboxing_evidence).
set local session_replication_role = replica;
update public.goods_slips set status = 'ITEMIZATION' where gs_no in ('PGTAP-I1', 'PGTAP-I2');
set local session_replication_role = origin;

-- BR-07 / AMD-08 (change plan Phase 3): Counting (ITEMIZATION) is submitted to CATEGORISATION
-- only, and only with >= 1 counted line; a line has some quantity.
select throws_like(
  $$update public.goods_slips set category_code = 'RO', original_category_code = 'RO',
           status = 'INSPECTION' where gs_no = 'PGTAP-I2'$$,
  'G-03:%counting is submitted to CATEGORISATION%', 'counting goes to CATEGORISATION before routing');
select throws_like(
  $$update public.goods_slips set status = 'CATEGORISATION' where gs_no = 'PGTAP-I2'$$,
  'G-01:%item lines%', 'counting cannot be submitted without item lines');
select throws_ok(
  $$insert into public.gs_items (gs_id, line_no, product_id, category_id, documented_qty, received_qty)
    select gs_r, 1, p.id, p.category_id, 0, 0 from _ctx, public.products p where p.code = 'PGTAP-DMT-001'$$,
  '23514', null, 'a line needs a documented or received quantity');

insert into public.gs_items (id, gs_id, line_no, product_id, category_id, documented_qty, received_qty)
select item_c, gs_c, 1, p.id, p.category_id, 10, 8 from _ctx, public.products p where p.code = 'PGTAP-DMT-001';
insert into public.gs_items (gs_id, line_no, product_id, category_id, documented_qty, received_qty)
select gs_r, 1, p.id, p.category_id, 4, 4 from _ctx, public.products p where p.code = 'PGTAP-PRS-001';

select is((select short_qty from public.gs_items i join _ctx c on i.id = c.item_c), 2,
  'DEC-09: short_qty = documented - received');

-- AMD-08: the count is submitted (setup), then the category is chosen in CATEGORISATION.
update public.goods_slips set status = 'CATEGORISATION' where gs_no in ('PGTAP-I1', 'PGTAP-I2');

-- Routing out of CATEGORISATION follows the category.
select throws_like(
  $$update public.goods_slips set category_code = 'CSR', original_category_code = 'CSR',
           status = 'INSPECTION' where gs_no = 'PGTAP-I1'$$,
  'G-03:%CSR_APPROVAL_PENDING%', 'a CSR cannot go straight to INSPECTION');
select throws_like(
  $$update public.goods_slips set category_code = 'RO', original_category_code = 'RO',
           status = 'CSR_APPROVAL_PENDING' where gs_no = 'PGTAP-I2'$$,
  '%G-03%', 'RO is not routed to CSR approval');
select lives_ok(
  $$update public.goods_slips set category_code = 'RO', original_category_code = 'RO',
           status = 'INSPECTION' where gs_no = 'PGTAP-I2'$$, 'RO → INSPECTION');
select lives_ok(
  $$update public.goods_slips set category_code = 'CSR', original_category_code = 'CSR',
           status = 'CSR_APPROVAL_PENDING' where gs_no = 'PGTAP-I1'$$, 'CSR → CSR_APPROVAL_PENDING');

-- Lines are frozen after categorisation.
select throws_like(
  $$update public.gs_items set received_qty = 9 where id = (select item_c from _ctx)$$,
  '%approved line correction%', 'quantities change only through an approved correction');
select throws_like(
  $$delete from public.gs_items where id = (select item_c from _ctx)$$,
  '%cannot be added or removed%', 'lines cannot be removed after categorisation');

-- G-03: no advance (nor conversion) without the RM decision.
select throws_like(
  $$update public.goods_slips set status = 'INSPECTION' where gs_no = 'PGTAP-I1'$$,
  'G-03:%', 'CSR_APPROVAL_PENDING → INSPECTION needs a decision');
select throws_like(
  $$update public.goods_slips set status = 'IN_PROCESS' where gs_no = 'PGTAP-I1'$$,
  'G-03:%', 'CSR_APPROVAL_PENDING → IN_PROCESS needs a decision');
select throws_like(
  $$update public.goods_slips set status = 'COMMERCIAL_RESOLUTION' where gs_no = 'PGTAP-I1'$$,
  'G-03:%', 'no Stage-6 status without a decision');
select throws_like(
  $$update public.goods_slips set category_code = 'RO' where gs_no = 'PGTAP-I1'$$,
  'G-03:%', 'CSR → RO only through a rejection');
select throws_like(
  $$update public.goods_slips set original_category_code = 'RO' where gs_no = 'PGTAP-I1'$$,
  'G-03:%', 'the original category is kept');

-- G-03: only the S1_CSR_APPROVAL approver records the decision; rejection needs remarks.
select throws_like(
  $$insert into public.csr_approvals (gs_id, decision_code, decided_by)
    select gs_c, 'CSR_APPROVED', aman from _ctx$$,
  'G-03:%Replacement Manager%', 'the Inward Verifier cannot decide');
select throws_ok(
  $$insert into public.csr_approvals (gs_id, decision_code, decided_by)
    select gs_c, 'CSR_REJECTED_TO_RO', rm from _ctx$$,
  '23514', null, 'a rejection needs remarks');
select lives_ok(
  $$insert into public.csr_approvals (gs_id, decision_code, remarks, decided_by)
    select gs_c, 'CSR_REJECTED_TO_RO', 'damaged pieces', rm from _ctx$$, 'the RM rejects');
select is((select is_admin_action from public.csr_approvals c join _ctx x on c.gs_id = x.gs_c), false,
  'an assigned RM decision is not an admin action');
select throws_like(
  $$update public.goods_slips set status = 'IN_PROCESS', category_code = 'CSR' where gs_no = 'PGTAP-I1'$$,
  'G-03:%', 'a rejected CSR cannot be routed as approved');
select lives_ok(
  $$update public.goods_slips set category_code = 'RO', status = 'INSPECTION' where gs_no = 'PGTAP-I1'$$,
  'rejected CSR → RO → INSPECTION');
select throws_like(
  $$update public.csr_approvals set decision_code = 'CSR_APPROVED'
     where gs_id = (select gs_c from _ctx)$$,
  'G-03:%', 'a recorded decision is immutable');

select * from finish();
rollback;
