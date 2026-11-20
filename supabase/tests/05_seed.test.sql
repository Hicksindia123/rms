-- P1-02 pgTAP: reference seed matches the workbook (§3.2) and master plan (§3.3, DEC-20, §8.2).
begin;
create extension if not exists pgtap with schema extensions;
select plan(25);

-- ---------------------------------------------------------------------------
-- Option catalogue: 79 workbook rows (DD r2–r80) + 5 RM actions (WF r6)
-- ---------------------------------------------------------------------------
-- P3-08: + 1 system option (JV_ONLY in CN_TYPE, §8.6 / BR-34 / DEC-23) that is not a workbook row.
-- Change plan 2026-11-12 Phase 2: + RETURN_TYPE (2, AMD-01) + 4 GATE_DOCUMENT row types (AMD-04).
-- Phase 3: + GS_STATUS (12 status labels, AMD-08; + HELD_AT_INTERMEDIATE_STORE, AMD-13).
select is((select count(*)::int from public.option_items), 104,
          '104 option items (79 DD rows + 5 WF r6 + JV_ONLY + 2 AMD-01 + 4 AMD-04 + 13 AMD-08/13)');
select is((select count(*)::int from public.option_items where source_ref like 'DD r%'), 79,
          '79 option items come from Roles_Steps_Dropdowns');
select is((select count(distinct source_ref)::int from public.option_items where source_ref like 'DD r%'), 79,
          'each DD row r2–r80 is represented exactly once');
select set_eq(
  $$select substring(source_ref from 5)::int from public.option_items where source_ref like 'DD r%'$$,
  $$select generate_series(2, 80)$$,
  'DD rows r2..r80 are all present');
select is((select count(*)::int from public.option_items where source_ref = 'WF r6'), 5, '5 RM item actions from WF r6');
select is((select count(*)::int from public.option_sets), 37, '37 option sets (+ RETURN_TYPE, AMD-01; + GS_STATUS, AMD-08)');

select results_eq(
  $$select os.code::text, count(*)::int from public.option_items oi
      join public.option_sets os on os.id = oi.option_set_id group by 1 order by 1$$,
  $$values
    ('ASSIGNED_TECHNICIAN',1),('BATTERY_CHECK',2),('CLEANING_TREATMENT',2),('CN_TYPE',3),
    ('CSR_APPROVAL',2),('CSR_FINAL_STATUS',1),('CUSTODY_ASSIGNMENT',4),('CUSTODY_TRANSFER_MODE',1),
    ('DAILY_CONTAINER_AUDIT',1),('DATA_ENTRY_BY',2),('DELIVERY_MODE',3),('DMT_CONDITION',8),
    ('DMT_EXTRACTION_TYPE',2),('DOCUMENT_PHOTO',1),('EO_CONDITION',4),('EO_EXTRACTION_TYPE',2),
    ('EO_INSPECTION_PROTOCOL',1),('GATE_DOCUMENT',9),('GS_CREATION_FORMAT',1),('GS_STATUS',13),('GST_PORTAL_VERIFICATION',2),
    ('PARTS_STORAGE_SEPARATION',2),('PARTY_DOC_VERIFICATION',3),('PARTY_NOTIFICATION_STATUS',1),
    ('POST_SERVICING_CLASSIFICATION',3),('PRISMATIC_CONDITION',3),('PRISMATIC_EXTRACTION_TYPE',2),
    ('RATE_VERIFICATION_REF',2),('RECEIVED_DOC_CLASSIFICATION',4),('RECOVERABLE_PART_TYPE',4),
    ('RETURN_CATEGORY',2),('RETURN_TYPE',2),('RM_CN_DECISION',2),('RM_ITEM_ACTION',5),('STORE_ISSUE_TYPE',1),
    ('TRANSFER_ACCEPTANCE',2),('UNBOXING_VIDEO',1)$$,
  'option item count per set matches master plan §3.2 (+ JV_ONLY, §8.6)');

-- Verbatim labels / allowed status (spot checks on the trickiest rows)
select results_eq(
  $$select oi.source_ref, oi.code, oi.label, oi.allowed_status from public.option_items oi
     where oi.source_ref in ('DD r9','DD r22','DD r23','DD r33','DD r39','DD r46','DD r70','DD r76','DD r80')
     order by substring(oi.source_ref from 5)::int$$,
  $$values
    ('DD r9',  'NO_DOCUMENT',               'No Document Attached', 'CONDITIONAL'),
    ('DD r22', 'DMT_OK_PKG_DAMAGED',        'VISUALLY OKAY but unpacked or maybe packaging is damaged', 'YES'),
    ('DD r23', 'DMT_OTHER_BRANDS',          'OTHER BRANDS', 'NO'),
    ('DD r33', 'PRS_BULB_BROKEN_NO_HG',     'BULB BROKEN WITHOUT MERCURY', 'NO'),
    ('DD r39', 'EO_INNER_CAPILLARY_BROKEN', 'Inner Capillary Broken but Mercury Present', 'YES'),
    ('DD r46', 'DISCREPANCY',               'Discrepancy Reported', 'CONDITIONAL'),
    ('DD r70', 'GST_CN',                    'GST CREDIT NOTE', 'CONDITIONAL'),
    ('DD r76', 'GST_NOT_REFLECTED',         'Return NOT Reflected on GST Portal', 'CONDITIONAL'),
    ('DD r80', 'CSR_CLOSED',                'Inward to Inventory with Packaging + CN Issued + Prior Party Info', 'YES')$$,
  'labels and allowed status are verbatim from the workbook');

select is((select rule_text from public.option_items where source_ref = 'DD r17'),
  'All items and full quantity are sales return (e.g., 5 items, 100 qty). Requires Replacement Manager checking/approval.',
  'rule text is verbatim (DD r17)');
select is((select remarks from public.option_items where source_ref = 'DD r17'),
  'Won''t proceed without approval', 'remarks are verbatim (DD r17)');

select results_eq(
  $$select oi.code, oi.label from public.option_items oi join public.option_sets os on os.id = oi.option_set_id
     where os.code = 'RM_ITEM_ACTION' order by oi.sort_order$$,
  $$values ('SEND_NEW','Send New'),('SEND_REPAIRED','Send Repaired'),('ISSUE_CN','Issue CN'),
           ('NOT_ALLOWED','Not Allowed'),('PENDING_BP','Pending (BP)')$$,
  'WF r6 RM item actions');

select set_eq(
  $$select code from public.option_items where allowed_status = 'NO'$$,
  array['DMT_OTHER_BRANDS','DMT_BROKEN_BODY','PRS_BULB_BROKEN_NO_HG','PRS_BROKEN_WITH_HG',
        'EO_BODY_BROKEN_HG','EO_BULB_BROKEN_NO_HG'],
  'not-allowed conditions match BR-12');
select set_eq(
  $$select code from public.option_items where system_behavior = 'HAZARD'$$,
  array['PRS_BROKEN_WITH_HG','EO_BODY_BROKEN_HG'],
  'mercury hazard conditions match G-05');
select set_eq(
  $$select distinct code from public.option_items where code in ('PACKAGING_EXTRACTED','CONTAINER_EXTRACTED')$$,
  array['PACKAGING_EXTRACTED','CONTAINER_EXTRACTED'],
  'shared extraction codes');
select is((select count(*)::int from public.option_items where code in ('PACKAGING_EXTRACTED','CONTAINER_EXTRACTED')),
          6, 'extraction options stored once per category set (DMT, PRISMATIC, EO)');

-- ---------------------------------------------------------------------------
-- Roles, permissions, departments
-- ---------------------------------------------------------------------------
select set_eq($$select code from public.roles$$,
  array['SUPER_ADMIN','GATE_INWARD','INWARD_VERIFIER','REPLACEMENT_MANAGER','INTERMEDIATE_STORE_MANAGER',
        'TECHNICIAN_COORDINATOR','TECHNICIAN','SPARE_PARTS_TECHNICIAN','SPARE_PARTS_MANAGER','ACCOUNTS',
        'DISPATCH','MAIN_STORE','MANAGEMENT_VIEWER',
        -- Phase P1 20-11-2026: DEC-60 Management, DEC-61 one role per Intermediate Store
        'MANAGEMENT','ISTORE_OP','ISTORE_DT','ISTORE_RI'],
  'roles match master plan §3.3');
select is((select count(*)::int from public.permissions), 156, '20 modules × 7 actions + 5 department_routing (G2 approve = Store issue) + 4 final_actions + 3 ac_entry + 4 intermediate_stores (DEC-61) actions');
select is((select count(*)::int from public.role_permissions rp join public.roles r on r.id = rp.role_id
            where r.code = 'SUPER_ADMIN'), 156, 'SUPER_ADMIN marker role holds every permission');
select is((select count(*)::int from public.roles r
            where not exists (select 1 from public.role_permissions rp where rp.role_id = r.id)), 0,
          'every role has a default permission set');
select set_eq($$select name from public.departments$$,
  array['Replacement Department','Intermediate Store','Accounts','Gate/Security','Main Store'],
  'departments match DEC-20');

-- ---------------------------------------------------------------------------
-- Categories, locations, numbering, settings
-- ---------------------------------------------------------------------------
select results_eq(
  $$select pc.code, pc.requires_full_opening, pc.supports_battery, pc.supports_dismantling, pc.hazard_capable, os.code
      from public.product_categories pc join public.option_sets os on os.id = pc.condition_option_set_id
     order by pc.code$$,
  $$values ('DMT', false, true, true, false, 'DMT_CONDITION'),
           ('ENCLOSED_OVAL', true, false, false, true, 'EO_CONDITION'),
           ('PRISMATIC', false, false, false, true, 'PRISMATIC_CONDITION')$$,
  'product categories and flags');

select results_eq(
  $$select l.code, l.location_class, r.code from public.inventory_locations l
      left join public.roles r on r.id = l.custodian_role_id order by l.code$$,
  $$values ('BATTERY_STORE','SPARE_PARTS','SPARE_PARTS_MANAGER'),
           ('CREDITED','CREDITED',null::text),
           ('DEPT_CLEANING','TECHNICIAN','INTERMEDIATE_STORE_MANAGER'),
           ('DEPT_GRADING','TECHNICIAN','INTERMEDIATE_STORE_MANAGER'),
           ('DEPT_MERCURY_EXTRACTION','TECHNICIAN','INTERMEDIATE_STORE_MANAGER'),
           ('DEPT_REPACKAGING','TECHNICIAN','INTERMEDIATE_STORE_MANAGER'),
           ('DEPT_TECHNICIAN_REPAIR','TECHNICIAN','INTERMEDIATE_STORE_MANAGER'),
           ('DEPT_WASTE_MANAGEMENT','TECHNICIAN','INTERMEDIATE_STORE_MANAGER'),
           ('DISPATCHED','DISPATCHED',null),
           ('HAZARD_QUARANTINE','HAZARD_QUARANTINE','SPARE_PARTS_MANAGER'),
           ('INTERMEDIATE_STORE','FUNCTIONAL','INTERMEDIATE_STORE_MANAGER'),
           ('INWARD_STAGING','INWARD','INWARD_VERIFIER'),
           ('ISTORE_DT','FUNCTIONAL','ISTORE_DT'),
           ('ISTORE_OP','FUNCTIONAL','ISTORE_OP'),
           ('ISTORE_RI','FUNCTIONAL','ISTORE_RI'),
           ('MAIN_STORE','MAIN_STORE',null),
           ('NON_FUNCTIONAL_STORE','NON_FUNCTIONAL','SPARE_PARTS_MANAGER'),
           ('PENDING_HOLD','PENDING_HOLD',null),
           ('REJECTED_HOLD','REJECTED_HOLD','REPLACEMENT_MANAGER'),
           ('SCRAP_DISPOSED','SCRAP_DISPOSED',null),
           ('SPARE_PARTS_STORE','SPARE_PARTS','SPARE_PARTS_MANAGER'),
           ('TECHNICIAN_BENCH','TECHNICIAN',null),
           ('TRANSIT','TRANSIT',null)$$,
  'inventory locations, classes and custodians');

select set_eq($$select code from public.number_series$$,
  array['GS','TRANSFER','TECH_BATCH','DISMANTLE','STORE_ISSUE','DISPATCH','DEPT_ROUTING','DEPT_RECEIPT','AC_ACTION_SLIP','DISPATCH_SLIP'], 'number series');
select is((select pattern from public.number_series where code = 'GS'), 'GS/{FY}/{SEQ:5}', 'GS placeholder pattern (DEC-01)');

select results_eq(
  $$select key, value from public.system_settings
     where key in ('app_name','timezone','date_format','page_size','upload_max_video_bytes',
                   'upload_max_document_bytes','signed_url_ttl_seconds','pending_blocks_entire_gs',
                   'daily_audit_blocks_inspection','segregation_of_duties_transfer','extraction_rule')
     order by key$$,
  $$values ('app_name','"Replacement Management System"'::jsonb),
           ('daily_audit_blocks_inspection','false'),
           ('date_format','"DD-MM-YYYY"'),
           ('extraction_rule','"packaging_plus_container_equals_received"'),
           ('page_size','25'),
           ('pending_blocks_entire_gs','false'),
           ('segregation_of_duties_transfer','true'),
           ('signed_url_ttl_seconds','600'),
           ('timezone','"Asia/Kolkata"'),
           ('upload_max_document_bytes','26214400'),
           ('upload_max_video_bytes','1073741824')$$,
  'system settings defaults and provisional DEC toggles');

select * from finish();
rollback;
