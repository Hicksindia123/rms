-- =============================================================================
-- RMS seed (master plan §8.9). Run by `supabase db reset` after the migrations.
--
-- REFERENCE seed: roles, permissions, default role matrix, departments, product categories,
-- inventory locations, the full workbook option catalogue (§3.2, verbatim), number series and
-- system settings. Idempotent: re-running never fails and never overwrites admin edits
-- (ON CONFLICT DO NOTHING).
--
-- DEMO seed: the block between the DEMO BEGIN / DEMO END marker lines at the end of this file.
-- Local development only. The remote (Option B) procedure strips it (docs/SETUP.md).
-- Demo USERS are not created here; they are created by the P1-05 script.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Departments (DEC-20)
-- -----------------------------------------------------------------------------
insert into public.departments (code, name) values
  ('REPLACEMENT_DEPT',   'Replacement Department'),
  ('INTERMEDIATE_STORE', 'Intermediate Store'),
  ('ACCOUNTS',           'Accounts'),
  ('GATE_SECURITY',      'Gate/Security'),
  ('MAIN_STORE',         'Main Store')
on conflict (code) do nothing;

-- -----------------------------------------------------------------------------
-- Roles (§3.3, codes exactly). Descriptions carry the workbook role text.
-- SUPER_ADMIN is the marker role: Super Admin rights come from profiles.is_super_admin
-- (§9.3), which still cannot bypass system guards G-01…G-18.
-- -----------------------------------------------------------------------------
insert into public.roles (code, name, description, is_system) values
  ('SUPER_ADMIN',                'Super Admin',                'Marker role. Full rights come from profiles.is_super_admin; system guards still apply (§9.3).', true),
  ('GATE_INWARD',                'Gate Inward User',           'Workbook: Gate Inward User', true),
  ('INWARD_VERIFIER',            'Unboxing & Inward Verifier', 'Workbook: Unboxing & Inward Verifier / Inward Verifier', true),
  ('REPLACEMENT_MANAGER',        'Replacement Manager',        'Workbook: Replacement Manager', true),
  ('INTERMEDIATE_STORE_MANAGER', 'Intermediate Store Manager', 'Workbook: Intermediate Store Manager / Intermediate Store In-charge', true),
  ('TECHNICIAN_COORDINATOR',     'Technician Coordinator',     'Workbook: Technician Coordinator (Aman / Sahil)', true),
  ('TECHNICIAN',                 'Technician',                 'Workbook: Technician', true),
  ('SPARE_PARTS_TECHNICIAN',     'Spare Parts Technician',     'Workbook: Parts Recovery Technician / Spare Parts Technician / Replacement Department Technician', true),
  ('SPARE_PARTS_MANAGER',        'Spare Parts Manager',        'Workbook: Spare Parts Manager', true),
  ('ACCOUNTS',                   'Accounts Team',              'Workbook: Accounts Team', true),
  ('DISPATCH',                   'Dispatch Team',              'Implied by workbook "dispatch team" (DD r69); DEC-26', true),
  ('MAIN_STORE',                 'Main Store',                 'Implied by workbook Main Store (WF r11); DEC-21', true),
  ('MANAGEMENT_VIEWER',          'Management Viewer',          'Implied: read-only MIS', true)
on conflict (code) do nothing;

-- -----------------------------------------------------------------------------
-- Permissions: every module code (§6.2 backend packages, plus `roles` and `masters` used by
-- P1-05 / P1-06) × every action. `auth` has no protected resources and gets none.
-- -----------------------------------------------------------------------------
insert into public.permissions (module_code, action, description)
select m.module_code, a.action, initcap(a.action) || ' — ' || m.module_label
from (values
  ('users',           'Users'),
  ('roles',           'Roles & permissions'),
  ('masters',         'Master data'),
  ('config',          'System configuration'),
  ('audit',           'Audit trail & activity'),
  ('notifications',   'Notifications & alerts'),
  ('dashboards',      'Dashboards'),
  ('reports',         'Reports & MIS'),
  ('goods_slips',     'Goods slips'),
  ('unboxing',        'Inward & unboxing'),
  ('attachments',     'Documents & videos'),
  ('itemization',     'Itemisation & categorisation'),
  ('inspection',      'Product inspection & grading'),
  ('container_audit', 'Daily container audit'),
  ('custody',         'Custody transfers & intermediate store'),
  ('servicing',       'Technician & servicing'),
  ('inventory',       'Inventory (functional, spare parts, batteries)'),
  ('dismantling',     'Dismantling & parts recovery'),
  ('dispatch',        'Replacement dispatch'),
  ('credit_notes',    'Credit notes & accounts verification')
) as m(module_code, module_label)
cross join (values ('view'),('create'),('edit'),('approve'),('delete'),('export'),('configure')) as a(action)
on conflict (module_code, action) do nothing;

-- -----------------------------------------------------------------------------
-- Default role → permission matrix (scope 'all'). Documented in docs/ARCHITECTURE.md.
-- Admins change it from the Permission Matrix (P1-05). Note: re-running this seed re-adds a
-- default grant an admin has since removed, so on a shared environment run it once.
-- -----------------------------------------------------------------------------
drop table if exists _seed_role_matrix;
create temporary table _seed_role_matrix (role_code text, module_code text, actions text[]);
insert into _seed_role_matrix values
  -- every operational role
  ('GATE_INWARD',                'dashboards',      array['view']),
  ('GATE_INWARD',                'notifications',   array['view']),
  ('GATE_INWARD',                'goods_slips',     array['view','create']),
  ('GATE_INWARD',                'attachments',     array['view','create']),

  ('INWARD_VERIFIER',            'dashboards',      array['view']),
  ('INWARD_VERIFIER',            'notifications',   array['view']),
  ('INWARD_VERIFIER',            'goods_slips',     array['view','edit']),
  ('INWARD_VERIFIER',            'unboxing',        array['view','create','edit']),
  ('INWARD_VERIFIER',            'attachments',     array['view','create']),
  ('INWARD_VERIFIER',            'itemization',     array['view','create','edit']),
  ('INWARD_VERIFIER',            'inspection',      array['view','create','edit']),
  ('INWARD_VERIFIER',            'container_audit', array['view','create','edit']),
  ('INWARD_VERIFIER',            'custody',         array['view','create']),
  ('INWARD_VERIFIER',            'reports',         array['view']),

  ('REPLACEMENT_MANAGER',        'dashboards',      array['view']),
  ('REPLACEMENT_MANAGER',        'notifications',   array['view']),
  ('REPLACEMENT_MANAGER',        'goods_slips',     array['view','edit','approve']),
  ('REPLACEMENT_MANAGER',        'unboxing',        array['view','approve']),
  ('REPLACEMENT_MANAGER',        'attachments',     array['view']),
  ('REPLACEMENT_MANAGER',        'itemization',     array['view','approve']),
  ('REPLACEMENT_MANAGER',        'inspection',      array['view','approve']),
  ('REPLACEMENT_MANAGER',        'container_audit', array['view']),
  ('REPLACEMENT_MANAGER',        'custody',         array['view','approve']),
  ('REPLACEMENT_MANAGER',        'servicing',       array['view']),
  ('REPLACEMENT_MANAGER',        'inventory',       array['view','approve','export']),  -- P3-04 adjustments
  ('REPLACEMENT_MANAGER',        'dismantling',     array['view']),
  ('REPLACEMENT_MANAGER',        'dispatch',        array['view']),
  ('REPLACEMENT_MANAGER',        'credit_notes',    array['view','create','approve']),
  ('REPLACEMENT_MANAGER',        'reports',         array['view','export']),
  ('REPLACEMENT_MANAGER',        'audit',           array['view']),

  ('INTERMEDIATE_STORE_MANAGER', 'dashboards',      array['view']),
  ('INTERMEDIATE_STORE_MANAGER', 'notifications',   array['view']),
  ('INTERMEDIATE_STORE_MANAGER', 'goods_slips',     array['view']),
  ('INTERMEDIATE_STORE_MANAGER', 'attachments',     array['view']),
  ('INTERMEDIATE_STORE_MANAGER', 'custody',         array['view','create','edit','approve']),
  ('INTERMEDIATE_STORE_MANAGER', 'inventory',       array['view','create','edit','export']),
  ('INTERMEDIATE_STORE_MANAGER', 'servicing',       array['view','create','edit']),
  ('INTERMEDIATE_STORE_MANAGER', 'dispatch',        array['view','create']),
  ('INTERMEDIATE_STORE_MANAGER', 'reports',         array['view']),

  ('TECHNICIAN_COORDINATOR',     'dashboards',      array['view']),
  ('TECHNICIAN_COORDINATOR',     'notifications',   array['view']),
  ('TECHNICIAN_COORDINATOR',     'goods_slips',     array['view']),
  ('TECHNICIAN_COORDINATOR',     'servicing',       array['view','create','edit']),
  ('TECHNICIAN_COORDINATOR',     'custody',         array['view','create']),
  ('TECHNICIAN_COORDINATOR',     'inventory',       array['view']),

  ('TECHNICIAN',                 'dashboards',      array['view']),
  ('TECHNICIAN',                 'notifications',   array['view']),
  ('TECHNICIAN',                 'servicing',       array['view']),

  ('SPARE_PARTS_TECHNICIAN',     'dashboards',      array['view']),
  ('SPARE_PARTS_TECHNICIAN',     'notifications',   array['view']),
  ('SPARE_PARTS_TECHNICIAN',     'dismantling',     array['view','create','edit']),
  ('SPARE_PARTS_TECHNICIAN',     'inventory',       array['view']),

  ('SPARE_PARTS_MANAGER',        'dashboards',      array['view']),
  ('SPARE_PARTS_MANAGER',        'notifications',   array['view']),
  ('SPARE_PARTS_MANAGER',        'inventory',       array['view','create','edit','export']),
  ('SPARE_PARTS_MANAGER',        'dismantling',     array['view','create','edit','approve']),
  ('SPARE_PARTS_MANAGER',        'custody',         array['view','create','edit','approve']),
  ('SPARE_PARTS_MANAGER',        'reports',         array['view']),

  ('ACCOUNTS',                   'dashboards',      array['view']),
  ('ACCOUNTS',                   'notifications',   array['view']),
  ('ACCOUNTS',                   'goods_slips',     array['view']),
  ('ACCOUNTS',                   'attachments',     array['view','create']),  -- P3-07 notification proof (S6_NOTIFY)
  ('ACCOUNTS',                   'credit_notes',    array['view','create','edit','approve','export']),
  ('ACCOUNTS',                   'reports',         array['view','export']),

  ('DISPATCH',                   'dashboards',      array['view']),
  ('DISPATCH',                   'notifications',   array['view']),
  ('DISPATCH',                   'goods_slips',     array['view']),
  ('DISPATCH',                   'dispatch',        array['view','create','edit']),
  ('DISPATCH',                   'inventory',       array['view']),

  ('MAIN_STORE',                 'dashboards',      array['view']),
  ('MAIN_STORE',                 'notifications',   array['view']),
  ('MAIN_STORE',                 'inventory',       array['view','edit']),
  ('MAIN_STORE',                 'custody',         array['view','approve']),

  ('MANAGEMENT_VIEWER',          'dashboards',      array['view']),
  ('MANAGEMENT_VIEWER',          'notifications',   array['view']),
  ('MANAGEMENT_VIEWER',          'reports',         array['view','export']),
  ('MANAGEMENT_VIEWER',          'audit',           array['view']),
  ('MANAGEMENT_VIEWER',          'goods_slips',     array['view']),
  ('MANAGEMENT_VIEWER',          'unboxing',        array['view']),
  ('MANAGEMENT_VIEWER',          'attachments',     array['view']),
  ('MANAGEMENT_VIEWER',          'itemization',     array['view']),
  ('MANAGEMENT_VIEWER',          'inspection',      array['view']),
  ('MANAGEMENT_VIEWER',          'container_audit', array['view']),
  ('MANAGEMENT_VIEWER',          'custody',         array['view']),
  ('MANAGEMENT_VIEWER',          'servicing',       array['view']),
  ('MANAGEMENT_VIEWER',          'inventory',       array['view','export']),
  ('MANAGEMENT_VIEWER',          'dismantling',     array['view']),
  ('MANAGEMENT_VIEWER',          'dispatch',        array['view']),
  ('MANAGEMENT_VIEWER',          'credit_notes',    array['view']),

  -- Change plan Phase 6 (AMD-14, DEC-42). The Phase 6 migration granted these with a roles join,
  -- which inserts nothing on a fresh `supabase db reset` (roles are seed data); the grants live here.
  ('REPLACEMENT_MANAGER',        'department_routing', array['view','create','export']),
  ('INWARD_VERIFIER',            'department_routing', array['view','edit']),
  ('INTERMEDIATE_STORE_MANAGER', 'department_routing', array['view']),

  -- Change plan Phase 7 (AMD-16, AMD-17): RM final actions and the A/c Actions slip.
  ('REPLACEMENT_MANAGER',        'final_actions',   array['view','edit','approve','export']),
  ('ACCOUNTS',                   'final_actions',   array['view','export']),
  ('INTERMEDIATE_STORE_MANAGER', 'final_actions',   array['view']),
  ('MANAGEMENT_VIEWER',          'final_actions',   array['view']),

  -- Change plan Phase 8 (AMD-18, AMD-19): Accounts entry per action line and the Dispatch Slip.
  -- DISPATCH works the Dispatch Slips through its existing `dispatch` grants.
  ('ACCOUNTS',                   'ac_entry',        array['view','edit','export']),
  ('REPLACEMENT_MANAGER',        'ac_entry',        array['view','export']),
  ('DISPATCH',                   'ac_entry',        array['view','export']),
  ('MANAGEMENT_VIEWER',          'ac_entry',        array['view']);

-- Fail loudly on a typo in the matrix instead of silently dropping a permission.
do $$
declare
  v_missing text;
begin
  select string_agg(m.role_code || '/' || m.module_code || '/' || a.action, ', ')
    into v_missing
    from _seed_role_matrix m
    cross join unnest(m.actions) as a(action)
   where not exists (select 1 from public.roles r where r.code = m.role_code)
      or not exists (select 1 from public.permissions p
                      where p.module_code = m.module_code and p.action = a.action);
  if v_missing is not null then
    raise exception 'seed role matrix references unknown role/permission: %', v_missing;
  end if;
end
$$;

insert into public.role_permissions (role_id, permission_id, scope)
select r.id, p.id, 'all'
  from _seed_role_matrix m
  cross join unnest(m.actions) as a(action)
  join public.roles r on r.code = m.role_code
  join public.permissions p on p.module_code = m.module_code and p.action = a.action
on conflict (role_id, permission_id) do nothing;

-- SUPER_ADMIN marker role: every permission.
insert into public.role_permissions (role_id, permission_id, scope)
select r.id, p.id, 'all'
  from public.roles r cross join public.permissions p
 where r.code = 'SUPER_ADMIN'
on conflict (role_id, permission_id) do nothing;

drop table if exists _seed_role_matrix;

-- -----------------------------------------------------------------------------
-- Role journeys (change plan Phase 10, AMD-22, DEC-49 PROVISIONAL): the menu each role sees, in
-- the order of its working journey (where a GS starts for the role -> where it ends), then its
-- tools. Catalogue: public.journey_steps (migration 20261114000300). Admins edit it in
-- Admin -> Role Journeys. SUPER_ADMIN sees the whole catalogue and needs no rows.
-- -----------------------------------------------------------------------------
insert into public.role_journey_steps (role_id, journey_step_id, sort_order)
select r.id, s.id, m.ord
  from (values
    ('GATE_INWARD',                'GATE_ENTRY',      10),
    ('GATE_INWARD',                'GS_LIST',        100),

    ('INWARD_VERIFIER',            'CARTON_OPENING',  10),
    ('INWARD_VERIFIER',            'COUNTING',        20),
    -- DEC-53: no separate CATEGORISATION entry; COUNTING = "Counting & Categorisation".
    ('INWARD_VERIFIER',            'INSPECTION',      35),
    ('INWARD_VERIFIER',            'DEPT_RECEIVING',  40),   -- Q8 / DEC-42
    ('INWARD_VERIFIER',            'CONTAINER_AUDIT',100),
    ('INWARD_VERIFIER',            'GS_LIST',        110),
    ('INWARD_VERIFIER',            'REPORTS',        120),

    ('REPLACEMENT_MANAGER',        'RM_REVIEW',       10),
    ('REPLACEMENT_MANAGER',        'DEPT_ROUTING',    20),
    ('REPLACEMENT_MANAGER',        'FINAL_ACTIONS',   30),
    ('REPLACEMENT_MANAGER',        'APPROVALS',      100),
    ('REPLACEMENT_MANAGER',        'GS_LIST',        110),
    ('REPLACEMENT_MANAGER',        'PENDENCIES',     120),
    ('REPLACEMENT_MANAGER',        'DASHBOARD',      130),
    ('REPLACEMENT_MANAGER',        'REPORTS',        140),
    ('REPLACEMENT_MANAGER',        'AUDIT',          150),

    ('INTERMEDIATE_STORE_MANAGER', 'STORE_ACCEPT',    10),
    ('INTERMEDIATE_STORE_MANAGER', 'CUSTODY',        100),
    ('INTERMEDIATE_STORE_MANAGER', 'INVENTORY',      110),
    ('INTERMEDIATE_STORE_MANAGER', 'STORE_ISSUES',   120),
    ('INTERMEDIATE_STORE_MANAGER', 'GS_LIST',        130),

    ('ACCOUNTS',                   'ACCOUNTS_DOCS',   10),
    ('ACCOUNTS',                   'ACCOUNTS_ENTRY',  20),
    ('ACCOUNTS',                   'PARTY_EMAIL',     30),
    ('ACCOUNTS',                   'GS_LIST',        100),
    ('ACCOUNTS',                   'CREDIT_NOTES',   110),
    ('ACCOUNTS',                   'REPORTS',        120),

    ('DISPATCH',                   'DISPATCH_SLIP',   10),
    ('DISPATCH',                   'GS_LIST',        100),
    ('DISPATCH',                   'DISPATCH_QUEUE', 110),

    ('TECHNICIAN_COORDINATOR',     'SERVICING',      100),
    ('TECHNICIAN_COORDINATOR',     'CUSTODY',        110),
    ('TECHNICIAN_COORDINATOR',     'GS_LIST',        120),

    ('TECHNICIAN',                 'SERVICING',      100),

    ('SPARE_PARTS_TECHNICIAN',     'DISMANTLING',    100),
    ('SPARE_PARTS_TECHNICIAN',     'INVENTORY',      110),

    ('SPARE_PARTS_MANAGER',        'INVENTORY',      100),
    ('SPARE_PARTS_MANAGER',        'DISMANTLING',    110),
    ('SPARE_PARTS_MANAGER',        'SCRAP',          120),
    ('SPARE_PARTS_MANAGER',        'BATTERIES',      130),
    ('SPARE_PARTS_MANAGER',        'CUSTODY',        140),
    ('SPARE_PARTS_MANAGER',        'REPORTS',        150),

    ('MAIN_STORE',                 'INVENTORY',      100),
    ('MAIN_STORE',                 'CUSTODY',        110),

    ('MANAGEMENT_VIEWER',          'DASHBOARD',      100),
    ('MANAGEMENT_VIEWER',          'GS_LIST',        110),
    ('MANAGEMENT_VIEWER',          'PENDENCIES',     120),
    ('MANAGEMENT_VIEWER',          'REPORTS',        130),
    ('MANAGEMENT_VIEWER',          'AUDIT',          140)
  ) as m(role_code, step_code, ord)
  join public.roles r on r.code = m.role_code
  join public.journey_steps s on s.code = m.step_code
on conflict (role_id, journey_step_id) do nothing;

-- Fail loudly on a typo in the journey matrix (same rule as the permission matrix).
do $$
begin
  if (select count(*) from public.role_journey_steps) < 51 then
    raise exception 'role journey seed incomplete: % rows (expected 51)',
      (select count(*) from public.role_journey_steps);
  end if;
end
$$;

-- -----------------------------------------------------------------------------
-- Default landing dashboards per role (§3.3, §10 "Dashboard widgets", P4-01). Ordered: the most
-- actionable widgets first. Each layout only lists widgets the role's default permissions allow
-- (the API filters by permission anyway). Admins edit them in Admin → Dashboard layouts.
-- Never overwrites an admin's edit (ON CONFLICT DO NOTHING).
-- -----------------------------------------------------------------------------
insert into public.role_dashboard_layouts (role_id, widgets)
select r.id, l.widgets::jsonb
  from (values
    ('SUPER_ADMIN', '[{"code":"ADMIN_HEALTH","size":"L"},{"code":"MY_TASKS","size":"M"},{"code":"TRANSFERS_ATTENTION","size":"M"},{"code":"GS_PIPELINE","size":"L"},{"code":"OPEN_PENDENCIES","size":"S"},{"code":"HAZARD_QUARANTINE","size":"S"},{"code":"CONTAINER_AUDIT","size":"M"},{"code":"CN_PIPELINE","size":"M"},{"code":"TECHNICIAN_WIP","size":"M"},{"code":"GS_TREND","size":"L"}]'),
    ('GATE_INWARD', '[{"code":"MY_TASKS","size":"M"},{"code":"GATE_INWARDS_TODAY","size":"S"},{"code":"GS_PIPELINE","size":"L"},{"code":"GS_TREND","size":"L"}]'),
    ('INWARD_VERIFIER', '[{"code":"MY_TASKS","size":"M"},{"code":"EVIDENCE_PENDING","size":"S"},{"code":"INSPECTIONS_PENDING","size":"S"},{"code":"CONTAINER_AUDIT","size":"M"},{"code":"TRANSFERS_ATTENTION","size":"M"},{"code":"GATE_INWARDS_TODAY","size":"S"},{"code":"OPEN_PENDENCIES","size":"S"},{"code":"GS_PIPELINE","size":"L"}]'),
    ('REPLACEMENT_MANAGER', '[{"code":"MY_TASKS","size":"M"},{"code":"CSR_APPROVALS_PENDING","size":"S"},{"code":"OPEN_PENDENCIES","size":"S"},{"code":"TRANSFERS_ATTENTION","size":"M"},{"code":"INSPECTIONS_PENDING","size":"S"},{"code":"HAZARD_QUARANTINE","size":"S"},{"code":"CONTAINER_AUDIT","size":"M"},{"code":"CN_PIPELINE","size":"M"},{"code":"TECHNICIAN_WIP","size":"M"},{"code":"FUNCTIONAL_STOCK","size":"M"},{"code":"GS_PIPELINE","size":"L"},{"code":"GS_TREND","size":"L"}]'),
    ('INTERMEDIATE_STORE_MANAGER', '[{"code":"MY_TASKS","size":"M"},{"code":"TRANSFERS_ATTENTION","size":"M"},{"code":"TECHNICIAN_WIP","size":"M"},{"code":"FUNCTIONAL_STOCK","size":"M"},{"code":"NON_FUNCTIONAL_STOCK","size":"M"},{"code":"BATTERY_STOCK","size":"M"},{"code":"HAZARD_QUARANTINE","size":"S"}]'),
    ('TECHNICIAN_COORDINATOR', '[{"code":"MY_TASKS","size":"M"},{"code":"TECHNICIAN_WIP","size":"M"},{"code":"TRANSFERS_ATTENTION","size":"M"},{"code":"BATTERY_STOCK","size":"M"},{"code":"FUNCTIONAL_STOCK","size":"M"}]'),
    ('TECHNICIAN', '[{"code":"MY_TASKS","size":"M"},{"code":"TECHNICIAN_WIP","size":"M"}]'),
    ('SPARE_PARTS_TECHNICIAN', '[{"code":"MY_TASKS","size":"M"},{"code":"DISMANTLING","size":"M"},{"code":"NON_FUNCTIONAL_STOCK","size":"M"}]'),
    ('SPARE_PARTS_MANAGER', '[{"code":"MY_TASKS","size":"M"},{"code":"TRANSFERS_ATTENTION","size":"M"},{"code":"DISMANTLING","size":"M"},{"code":"HAZARD_QUARANTINE","size":"S"},{"code":"NON_FUNCTIONAL_STOCK","size":"M"},{"code":"BATTERY_STOCK","size":"M"}]'),
    ('ACCOUNTS', '[{"code":"MY_TASKS","size":"M"},{"code":"ACCOUNTS_DOC_QUEUE","size":"S"},{"code":"CN_PIPELINE","size":"M"},{"code":"CN_ISSUED","size":"L"}]'),
    ('DISPATCH', '[{"code":"MY_TASKS","size":"M"},{"code":"FUNCTIONAL_STOCK","size":"M"}]'),
    ('MAIN_STORE', '[{"code":"MY_TASKS","size":"M"},{"code":"TRANSFERS_ATTENTION","size":"M"},{"code":"FUNCTIONAL_STOCK","size":"M"}]'),
    ('MANAGEMENT_VIEWER', '[{"code":"GS_PIPELINE","size":"L"},{"code":"OPEN_PENDENCIES","size":"S"},{"code":"HAZARD_QUARANTINE","size":"S"},{"code":"CONTAINER_AUDIT","size":"M"},{"code":"TECHNICIAN_WIP","size":"M"},{"code":"CN_PIPELINE","size":"M"},{"code":"FUNCTIONAL_STOCK","size":"M"},{"code":"NON_FUNCTIONAL_STOCK","size":"M"},{"code":"DISMANTLING","size":"M"},{"code":"BATTERY_STOCK","size":"M"},{"code":"CN_ISSUED","size":"L"},{"code":"GS_TREND","size":"L"}]')
  ) as l(role_code, widgets)
  join public.roles r on r.code = l.role_code
on conflict (role_id) do nothing;

-- -----------------------------------------------------------------------------
-- Option sets & items — workbook sheet `Roles_Steps_Dropdowns` r2–r80 (79 rows, verbatim)
-- + WF r6 RM item actions (5 rows). Total 84 option_items in 35 option_sets.
-- Extraction options (DD r29–30, r35–36, r42–43) are stored once per category set, with the
-- same codes PACKAGING_EXTRACTED / CONTAINER_EXTRACTED in each set.
-- Generated from the workbook; do not hand-edit labels.
-- -----------------------------------------------------------------------------
insert into public.option_sets (code, name, description, control_type, source_kind, master_ref_type, source_ref, is_system)
select v.code, v.name, v.description, v.control_type, v.source_kind, v.master_ref_type, v.source_ref, true
from (values
  ('DELIVERY_MODE', 'Delivery Mode / Transporter', 'Stage-1 · Step-1 · Goods Slip (GS) Creation · Gate Inward User (Anuj) · General', 'dropdown', 'STATIC', null, 'DD r2–r4'),
  ('GATE_DOCUMENT', 'Accompanying Document at Gate', 'Stage-1 · Step-1 · Goods Slip (GS) Creation · Gate Inward User (Anuj) · General', 'dropdown', 'STATIC', null, 'DD r5–r9'),
  ('GS_CREATION_FORMAT', 'GS Creation Format', 'Stage-1 · Step-1 · Goods Slip (GS) Creation · Gate Inward User (Anuj) · General', 'dropdown', 'STATIC', null, 'DD r10'),
  ('UNBOXING_VIDEO', 'Unboxing Video Attachment', 'Stage-1 · Step-2 · Unboxing & Document Capture · Unboxing & Inward Verifier (Aman) · General', 'file', 'STATIC', null, 'DD r11'),
  ('RECEIVED_DOC_CLASSIFICATION', 'Received Document Classification', 'Stage-1 · Step-2 · Unboxing & Document Capture · Unboxing & Inward Verifier (Aman) · General', 'dropdown', 'STATIC', null, 'DD r12–r15'),
  ('DOCUMENT_PHOTO', 'Document Photo Attachment', 'Stage-1 · Step-2 · Unboxing & Document Capture · Unboxing & Inward Verifier (Aman) · General', 'file', 'STATIC', null, 'DD r16'),
  ('RETURN_CATEGORY', 'Return Categorization (GS Wise)', 'Stage-1 · Step-3 · Item Addition & Categorization · Inward Verifier (Aman) · General', 'dropdown', 'STATIC', null, 'DD r17–r18'),
  ('CSR_APPROVAL', 'Complete Sales Return Approval', 'Stage-1 · Step-3 · Item Addition & Categorization · Replacement Manager · General', 'dropdown', 'STATIC', null, 'DD r19–r20'),
  ('DMT_CONDITION', 'DMT Visual Condition', 'Stage-1 · Step-3 (Inspection) · Visual Inspection & Grading · Inward Verifier (Aman) · DMT', 'dropdown', 'STATIC', null, 'DD r21–r28'),
  ('DMT_EXTRACTION_TYPE', 'DMT Extraction Type', 'Stage-1 · Step-3 (Inspection) · Extraction Tracking · Inward Verifier (Aman) · DMT', 'radio', 'STATIC', null, 'DD r29–r30'),
  ('DAILY_CONTAINER_AUDIT', 'Daily Container Audit', 'Stage-1 · Step-3 (Inspection) · Audit Check · Inward Verifier (Aman) · DMT', 'checkbox', 'STATIC', null, 'DD r31'),
  ('PRISMATIC_CONDITION', 'Prismatic Visual Condition', 'Stage-1 · Step-3 (Inspection) · Visual Inspection & Grading · Inward Verifier (Aman) · PRISMATIC', 'dropdown', 'STATIC', null, 'DD r32–r34'),
  ('PRISMATIC_EXTRACTION_TYPE', 'Prismatic Extraction Type', 'Stage-1 · Step-3 (Inspection) · Extraction Tracking · Inward Verifier (Aman) · PRISMATIC', 'radio', 'STATIC', null, 'DD r35–r36'),
  ('EO_INSPECTION_PROTOCOL', 'Inspection Protocol', 'Stage-1 · Step-3 (Inspection) · Inspection Requirement · Inward Verifier (Aman) · ENCLOSED OVAL', 'dropdown', 'STATIC', null, 'DD r37'),
  ('EO_CONDITION', 'Enclosed Oval Visual Condition', 'Stage-1 · Step-3 (Inspection) · Visual Inspection & Grading · Inward Verifier (Aman) · ENCLOSED OVAL', 'dropdown', 'STATIC', null, 'DD r38–r41'),
  ('EO_EXTRACTION_TYPE', 'Enclosed Oval Extraction Type', 'Stage-1 · Step-3 (Inspection) · Extraction Tracking · Inward Verifier (Aman) · ENCLOSED OVAL', 'radio', 'STATIC', null, 'DD r42–r43'),
  ('CUSTODY_TRANSFER_MODE', 'Custody Transfer Mode', 'Stage-2 · Step-4 · Handover to Intermediate Store · Intermediate Store Manager (Sahil) · General', 'dropdown', 'STATIC', null, 'DD r44'),
  ('TRANSFER_ACCEPTANCE', 'Transfer Acceptance Status', 'Stage-2 · Step-4 · Handover to Intermediate Store · Intermediate Store Manager (Sahil) · General', 'dropdown', 'STATIC', null, 'DD r45–r46'),
  ('ASSIGNED_TECHNICIAN', 'Assigned Technician', 'Stage-3 · Step-4 (Technical) · Technician Servicing · Technician Coordinator (Aman / Sahil) · General', 'dropdown', 'MASTER', 'technicians', 'DD r47'),
  ('DATA_ENTRY_BY', 'Data Entry Performed By', 'Stage-3 · Step-4 (Technical) · Technician Servicing · Technician Coordinator (Aman / Sahil) · General', 'dropdown', 'MASTER', 'profiles:TECHNICIAN_COORDINATOR', 'DD r48–r49'),
  ('BATTERY_CHECK', 'Battery Check Result', 'Stage-3 · Step-4 (Technical) · Technician Servicing · Technician (Raj Kumar Ji) · General', 'dropdown', 'STATIC', null, 'DD r50–r51'),
  ('CLEANING_TREATMENT', 'Cleaning & Scratch Treatment', 'Stage-3 · Step-4 (Technical) · Technician Servicing · Technician (Raj Kumar Ji) · General', 'dropdown', 'STATIC', null, 'DD r52–r53'),
  ('POST_SERVICING_CLASSIFICATION', 'Post-Servicing Classification', 'Stage-3 · Step-4 (Technical) · Technician Servicing · Technician (Raj Kumar Ji) · General', 'dropdown', 'STATIC', null, 'DD r54–r56'),
  ('RECOVERABLE_PART_TYPE', 'Recoverable Part Type', 'Stage-4 · Step-5 · Dismantling & Parts Recovery · Spare Parts Technician · Parts Recovery', 'dropdown', 'STATIC', null, 'DD r57–r60'),
  ('PARTS_STORAGE_SEPARATION', 'Parts Storage Separation', 'Stage-4 · Step-5 · Dismantling & Parts Recovery · Spare Parts Technician · Parts Recovery', 'dropdown', 'STATIC', null, 'DD r61–r62'),
  ('CUSTODY_ASSIGNMENT', 'Inventory Custody Assignment', 'Stage-5 · Step-6 · Custody Segregation · Intermediate Store Manager (Sahil) · General', 'dropdown', 'STATIC', null, 'DD r63–r66'),
  ('STORE_ISSUE_TYPE', 'Store Issue Type', 'Stage-6 · Step-7 · Store Issue & Credit Note · Intermediate Store Manager (Sahil) · General', 'dropdown', 'STATIC', null, 'DD r67'),
  ('RM_CN_DECISION', 'Replacement Manager CN Decision', 'Stage-6 · Step-7 · Store Issue & Credit Note · Replacement Manager · Credit Note', 'dropdown', 'STATIC', null, 'DD r68–r69'),
  ('CN_TYPE', 'Credit Note Type', 'Stage-6 · Step-7 · Store Issue & Credit Note · Accounts Team (Deepak Ji) · Credit Note', 'dropdown', 'STATIC', null, 'DD r70–r71'),
  ('PARTY_DOC_VERIFICATION', 'Party Document Verification', 'Stage-6 · Step-7 · Store Issue & Credit Note · Accounts Team (Deepak Ji) · Credit Note', 'dropdown', 'STATIC', null, 'DD r72–r74'),
  ('GST_PORTAL_VERIFICATION', 'GST Portal Return Verification', 'Stage-6 · Step-7 · Store Issue & Credit Note · Accounts Team (Deepak Ji) · Credit Note', 'dropdown', 'STATIC', null, 'DD r75–r76'),
  ('RATE_VERIFICATION_REF', 'Rate Verification Reference', 'Stage-6 · Step-7 · Store Issue & Credit Note · Accounts Team (Deepak Ji) · Credit Note', 'dropdown', 'STATIC', null, 'DD r77–r78'),
  ('PARTY_NOTIFICATION_STATUS', 'Party Notification Status', 'Stage-6 · Step-7 · Store Issue & Credit Note · Accounts Team (Deepak Ji) · Credit Note', 'dropdown', 'STATIC', null, 'DD r79'),
  ('CSR_FINAL_STATUS', 'Complete Sales Return Final Status', 'Stage-6 · Step-7 · Complete Sales Return Closure · Inward & Accounts Team · General', 'dropdown', 'STATIC', null, 'DD r80'),
  ('RM_ITEM_ACTION', 'Item-wise RM action', 'Stage-1 a) · Step-3 a) · ACTIONS FROM HICKS END · REPLACEMENT MANAGER · Item Wise Segregation', 'dropdown', 'STATIC', null, 'WF r6')
) as v(code, name, description, control_type, source_kind, master_ref_type, source_ref)
on conflict (code) do nothing;

insert into public.option_items (option_set_id, code, label, allowed_status, rule_text, next_action_text,
                                 remarks, system_behavior, required_fields, sort_order, source_ref)
select os.id, v.code, v.label, v.allowed_status, v.rule_text, v.next_action_text, v.remarks,
       v.system_behavior, v.required_fields::jsonb, v.sort_order, v.source_ref
from (values
  ('DELIVERY_MODE', 'COURIER_PARCEL', 'Courier / Parcel', 'YES', 'Record courier name and docket number', 'Proceed to GS Generation', 'Gate entry point', null, '["courier_name", "docket_no"]', 10, 'DD r2'),
  ('DELIVERY_MODE', 'DIRECT_TRUCK', 'Direct Transport / Truck', 'YES', 'Record vehicle number and transporter name', 'Proceed to GS Generation', 'Gate entry point', null, '["vehicle_no", "transporter_id"]', 20, 'DD r3'),
  ('DELIVERY_MODE', 'SELF_PARTY_REP', 'Self / Party Representative', 'YES', 'Record person name and contact number', 'Proceed to GS Generation', 'Gate entry point', null, '["rep_name", "rep_contact"]', 30, 'DD r4'),
  ('GATE_DOCUMENT', 'INVOICE', 'Invoice', 'YES', 'Record invoice number and date', 'Attach to Inward Entry', 'Physical document received', null, '["gate_doc_no", "gate_doc_date"]', 10, 'DD r5'),
  ('GATE_DOCUMENT', 'DEBIT_NOTE', 'Debit Note', 'YES', 'Record debit note number and date', 'Attach to Inward Entry', 'Physical document received', null, '["gate_doc_no", "gate_doc_date"]', 20, 'DD r6'),
  ('GATE_DOCUMENT', 'DELIVERY_CHALLAN', 'Delivery Challan', 'YES', 'Record challan number and date', 'Attach to Inward Entry', 'Physical document received', null, '["gate_doc_no", "gate_doc_date"]', 30, 'DD r7'),
  ('GATE_DOCUMENT', 'HANDWRITTEN_SLIP', 'Handwritten Slip / Party Note', 'YES', 'Record slip details or party remarks', 'Attach to Inward Entry', 'Informal slip received', null, '["gate_doc_remarks"]', 40, 'DD r8'),
  ('GATE_DOCUMENT', 'NO_DOCUMENT', 'No Document Attached', 'CONDITIONAL', 'Flag consignment as missing documentation', 'Proceed with Gate Inward warning', 'Requires verification at Step-2', null, '[]', 50, 'DD r9'),
  ('GS_CREATION_FORMAT', 'AUTO_STANDARD', 'Auto-Generated (Standard Formatting)', 'YES', 'System creates GS number using current format automatically', 'Handover box to Aman (Step-2)', 'Auto with existing formatting', null, '[]', 10, 'DD r10'),
  ('UNBOXING_VIDEO', 'VIDEO', 'Continuous Unboxing Video File (.mp4 / .mov)', 'YES', 'Mandatory continuous video recording during box opening', 'Attach video to GS record', 'Step-2 mandatory checkpoint', null, '[]', 10, 'DD r11'),
  ('RECEIVED_DOC_CLASSIFICATION', 'INVOICE', 'Invoice', 'YES', 'Capture photo; verify buyer/seller GSTIN and item details', 'Link photo to GS & Accounts check', 'Document received with goods', null, '["buyer_gstin", "seller_gstin"]', 10, 'DD r12'),
  ('RECEIVED_DOC_CLASSIFICATION', 'DEBIT_NOTE', 'Debit Note', 'YES', 'Capture photo; record debit note number and amount', 'Link photo to GS & Accounts check', 'Document received with goods', null, '["doc_no", "amount"]', 20, 'DD r13'),
  ('RECEIVED_DOC_CLASSIFICATION', 'DELIVERY_CHALLAN', 'Delivery Challan', 'YES', 'Capture photo; match item quantity against parcel contents', 'Link photo to GS & Accounts check', 'Document received with goods', null, '["qty_matched"]', 30, 'DD r14'),
  ('RECEIVED_DOC_CLASSIFICATION', 'HANDWRITTEN_SLIP', 'Handwritten Slip / Party Note', 'YES', 'Capture photo; note party claim or complaint details', 'Link photo to GS & Accounts check', 'Any kind of slip received', null, '["party_claim_text"]', 40, 'DD r15'),
  ('DOCUMENT_PHOTO', 'DOC_PHOTO', 'Document Photo Image (.jpg / .png / .pdf)', 'YES', 'High-resolution picture of all paper documents received', 'Upload and proceed to Step-3 Item Addition', 'Mandatory alongside video', null, '[]', 10, 'DD r16'),
  ('RETURN_CATEGORY', 'CSR', 'Complete Sales Return', 'CONDITIONAL', 'All items and full quantity are sales return (e.g., 5 items, 100 qty). Requires Replacement Manager checking/approval.', 'Route to Replacement Manager for Approval', 'Won''t proceed without approval', null, '[]', 10, 'DD r17'),
  ('RETURN_CATEGORY', 'RO', 'Replacement Only', 'YES', 'Defective/mixed goods received for replacement (e.g., 1 damaged, 1 waste). Does not require pre-approval.', 'Proceed directly to Product Inspection & Grading', 'Standard replacement path', null, '[]', 20, 'DD r18'),
  ('CSR_APPROVAL', 'CSR_APPROVED', 'Approved - Complete Sales Return', 'YES', 'Manager confirms entire consignment is eligible for complete sales return', 'Forward to Sahil with packaging -> Inventory & CN', 'Manager approval granted', null, '[]', 10, 'DD r19'),
  ('CSR_APPROVAL', 'CSR_REJECTED_TO_RO', 'Rejected - Convert to Replacement Only', 'YES', 'Consignment fails sales return criteria; reclassified for replacement processing', 'Route items to Visual Inspection & Repair flow', 'Manager rejected sales return', null, '[]', 20, 'DD r20'),
  ('DMT_CONDITION', 'DMT_OK_PACKED', 'VISUALLY OKAY and PACKED', 'YES', 'When packing is in 100% sellable condition', 'Mark as sellable lot; record extraction', 'Option 1', 'SELLABLE', '[]', 10, 'DD r21'),
  ('DMT_CONDITION', 'DMT_OK_PKG_DAMAGED', 'VISUALLY OKAY but unpacked or maybe packaging is damaged', 'YES', 'Packaging not in 100% sellable condition (some sort of marking, torn box, unpacked)', 'Route for repackaging or technician check', 'Option 2', 'REPACK_OR_TECHNICIAN', '[]', 20, 'DD r22'),
  ('DMT_CONDITION', 'DMT_OTHER_BRANDS', 'OTHER BRANDS', 'NO', 'Not Allowed. Competitor or unauthorized third-party brand returned.', 'Log rejection; hold for party return or dispute', 'Option 3 - Strictly not allowed', 'REJECT_HOLD', '[]', 30, 'DD r23'),
  ('DMT_CONDITION', 'DMT_SHORT_QTY', 'SHORT QUANTITY', 'YES', 'Physical quantity received is less than documented quantity on slip', 'Log discrepancy count; process only actual received qty', 'Option 4', 'SHORT_QTY', '[]', 40, 'DD r24'),
  ('DMT_CONDITION', 'DMT_SCRATCHED', 'SCRATCHED/SPOTS', 'YES', 'Surface scratches or cosmetic spots on thermometer body', 'Route to Step-4 Technician cleaning & scratch buffing', 'Option 5', 'TO_TECHNICIAN', '[]', 50, 'DD r25'),
  ('DMT_CONDITION', 'DMT_DIRTY', 'DIRTY', 'YES', 'Dust, residue, or dirty surface on thermometer body', 'Route to Step-4 Technician for cleaning process', 'Option 6', 'TO_TECHNICIAN', '[]', 60, 'DD r26'),
  ('DMT_CONDITION', 'DMT_BROKEN_BODY', 'BROKEN / BODY DAMAGE', 'NO', 'Not Allowed. Physical cracks or severe body breakage.', 'Log body damage rejection; transfer to scrap/spare parts', 'Option 7 - Strictly not allowed', 'TO_SPARE_PARTS', '[]', 70, 'DD r27'),
  ('DMT_CONDITION', 'DMT_DISPLAY_ISSUE', 'DISPLAY ISSUES', 'YES', 'LCD display missing segments, blank screen, or faded numbers', 'Route to Step-4 Technician for battery/PCB check', 'Option 8', 'TO_TECHNICIAN', '[]', 80, 'DD r28'),
  ('DMT_EXTRACTION_TYPE', 'PACKAGING_EXTRACTED', 'Packaging Extracted', 'YES', 'Specify extracted packaging pieces; sum must match total allocated qty', 'Log packaging pieces count', 'Mandatory radio button', null, '[]', 10, 'DD r29'),
  ('DMT_EXTRACTION_TYPE', 'CONTAINER_EXTRACTED', 'Container Extracted', 'YES', 'Specify extracted container pieces; sum must match total allocated qty', 'Log container pieces count', 'Mandatory radio button', null, '[]', 20, 'DD r30'),
  ('DAILY_CONTAINER_AUDIT', 'DAILY_AUDIT_DONE', 'Containers Checked & Counted Daily', 'YES', 'All DMT containers must be counted and checked on a daily basis; sellable packaging separated', 'Daily audit compliance confirmed', 'Notepad explicit instruction', null, '[]', 10, 'DD r31'),
  ('PRISMATIC_CONDITION', 'PRS_OK', 'VISUALLY OKAY', 'YES', 'Glass thermometer body and scale intact', 'Route to Step-4 Intermediate Store', 'Option 1', 'SELLABLE', '[]', 10, 'DD r32'),
  ('PRISMATIC_CONDITION', 'PRS_BULB_BROKEN_NO_HG', 'BULB BROKEN WITHOUT MERCURY', 'NO', 'Not Allowed. Glass bulb broken and mercury leaked/absent.', 'Reject for replacement; record rejection in GS', 'Option 2 - Strictly not allowed', 'REJECT_RECORD', '[]', 20, 'DD r33'),
  ('PRISMATIC_CONDITION', 'PRS_BROKEN_WITH_HG', 'BROKEN WITH MERCURY', 'NO', 'Not Allowed. Glass broken with mercury contained inside hazard enclosure.', 'Hazard rejection; route to hazardous quarantine', 'Option 3 - Strictly not allowed', 'HAZARD', '[]', 30, 'DD r34'),
  ('PRISMATIC_EXTRACTION_TYPE', 'PACKAGING_EXTRACTED', 'Packaging Extracted', 'YES', 'Specify extracted packaging pieces; sum must match total allocated qty', 'Log packaging pieces count', 'Mandatory radio button', null, '[]', 10, 'DD r35'),
  ('PRISMATIC_EXTRACTION_TYPE', 'CONTAINER_EXTRACTED', 'Container Extracted', 'YES', 'Specify extracted container pieces; sum must match total allocated qty', 'Log container pieces count', 'Mandatory radio button', null, '[]', 20, 'DD r36'),
  ('EO_INSPECTION_PROTOCOL', 'EO_FULL_OPENING_DONE', 'Full Opening Inspection Completed', 'YES', 'Mandatory note: IT MUST BE CHECKED COMPLETELY BY OPENING IT.', 'Proceed with enclosed oval status grading', 'Mandatory operational check', null, '[]', 10, 'DD r37'),
  ('EO_CONDITION', 'EO_OK', 'VISUALLY OKAY', 'YES', 'Enclosed oval thermometer intact upon full opening', 'Route to Step-4 Intermediate Store', 'Option 1', 'SELLABLE', '[]', 10, 'DD r38'),
  ('EO_CONDITION', 'EO_INNER_CAPILLARY_BROKEN', 'Inner Capillary Broken but Mercury Present', 'YES', 'Internal capillary cracked/broken, but mercury remains sealed inside outer envelope', 'Route for evaluation / technical segregation', 'Option 2 - Conditionally acceptable', 'TO_TECHNICIAN', '[]', 20, 'DD r39'),
  ('EO_CONDITION', 'EO_BODY_BROKEN_HG', 'Body Broken but Mercury Present', 'NO', 'Not Allowed. Outer envelope broken with mercury present.', 'Hazard rejection; quarantine for safety', 'Option 3 - Strictly not allowed', 'HAZARD', '[]', 30, 'DD r40'),
  ('EO_CONDITION', 'EO_BULB_BROKEN_NO_HG', 'Bulb Broken and Mercury Absent', 'NO', 'Not Allowed. Bulb shattered and mercury leaked/absent.', 'Reject for replacement; record rejection in GS', 'Option 4 - Strictly not allowed', 'REJECT_RECORD', '[]', 40, 'DD r41'),
  ('EO_EXTRACTION_TYPE', 'PACKAGING_EXTRACTED', 'Packaging Extracted', 'YES', 'Specify extracted packaging pieces; sum must match total allocated qty', 'Log packaging pieces count', 'Mandatory radio button', null, '[]', 10, 'DD r42'),
  ('EO_EXTRACTION_TYPE', 'CONTAINER_EXTRACTED', 'Container Extracted', 'YES', 'Specify extracted container pieces; sum must match total allocated qty', 'Log container pieces count', 'Mandatory radio button', null, '[]', 20, 'DD r43'),
  ('CUSTODY_TRANSFER_MODE', 'PHYSICAL_AND_DIGITAL', 'Physical Movement & Digital Transfer', 'YES', 'Goods physically handed over from Aman to Sahil; system digitally shows Sahil is holding goods', 'Sahil accepts custody in RMS', 'Dual sync checkpoint', null, '[]', 10, 'DD r44'),
  ('TRANSFER_ACCEPTANCE', 'ACCEPTED_VERIFIED', 'Accepted - Quantity & Lots Verified', 'YES', 'Piece counts match grading summary from Step-3', 'Stock allocated in Intermediate Store', 'Successful custody transfer', null, '[]', 10, 'DD r45'),
  ('TRANSFER_ACCEPTANCE', 'DISCREPANCY', 'Discrepancy Reported', 'CONDITIONAL', 'Physical piece count differs from system transfer quantity', 'Halt transfer; reconcile with Aman', 'Discrepancy resolution', null, '[]', 20, 'DD r46'),
  ('ASSIGNED_TECHNICIAN', 'RAJ_KUMAR_JI', 'Raj Kumar Ji', 'YES', 'Entry handled by Aman or Sahil for allotment and receiving both', 'Assign item batch for testing & servicing', 'Primary technician', null, '[]', 10, 'DD r47'),
  ('DATA_ENTRY_BY', 'AMAN', 'Aman', 'YES', 'Aman logs allotment and receiving records for technician', 'Update servicing log', 'Entry operator option 1', null, '[]', 10, 'DD r48'),
  ('DATA_ENTRY_BY', 'SAHIL', 'Sahil', 'YES', 'Sahil logs allotment and receiving records for technician', 'Update servicing log', 'Entry operator option 2', null, '[]', 20, 'DD r49'),
  ('BATTERY_CHECK', 'BATTERY_OK', 'Battery Okay / Fine', 'YES', 'Original battery functioning properly; no replacement required', 'Record checked piece count', 'Battery OK', null, '["pieces_checked"]', 10, 'DD r50'),
  ('BATTERY_CHECK', 'BATTERY_REPLACED', 'Battery Changed / Replaced', 'YES', 'Battery replaced. Must enter: 1) Number of pieces checked, 2) Number of batteries installed.', 'Deduct battery stock; log goods & battery count', 'Battery replaced', null, '["pieces_checked", "batteries_installed", "battery_type_id"]', 20, 'DD r51'),
  ('CLEANING_TREATMENT', 'CLEANED_SELLABLE', 'Cleaned - Sellable / Fresh Finish', 'YES', 'Cleaning process successful; surface dirt and minor scratches removed', 'Classify piece as Functional', 'Cleaning successful', null, '[]', 10, 'DD r52'),
  ('CLEANING_TREATMENT', 'PERMANENT_SCRATCHES', 'Permanent Scratches / Non-Recoverable', 'YES', 'Scratches cannot be removed; body condition not sellable', 'Mark as Non-Sellable; route to Spare Parts Manager', 'Cosmetic reject', null, '[]', 20, 'DD r53'),
  ('POST_SERVICING_CLASSIFICATION', 'FUNCTIONAL_GOOD', 'Functional - Good / Fresh', 'YES', 'Piece is in pristine, 100% sellable working condition', 'Hand over to Intermediate Store (Sahil)', 'Good fresh unit', null, '[]', 10, 'DD r54'),
  ('POST_SERVICING_CLASSIFICATION', 'FUNCTIONAL_REPAIRED', 'Functional - Repaired & Working', 'YES', 'Piece successfully repaired by technician and fully functional', 'Hand over to Intermediate Store (Sahil)', 'Repaired unit', null, '[]', 20, 'DD r55'),
  ('POST_SERVICING_CLASSIFICATION', 'NON_GOOD', 'Non-Good Inventory (Defective / Unrepairable)', 'YES', 'Non-functional pieces received from technician that cannot be repaired', 'Route to Step-5 Parts Recovery Dismantle Process', 'Sends to dismantling', null, '[]', 30, 'DD r56'),
  ('RECOVERABLE_PART_TYPE', 'TIP', 'TIP', 'YES', 'Recover stainless steel / metal sensing tip', 'Store in designated Tip container partition', 'Harvested part', null, '[]', 10, 'DD r57'),
  ('RECOVERABLE_PART_TYPE', 'BODY', 'BODY', 'YES', 'Recover reusable plastic body shells', 'Store in designated Body container partition', 'Harvested part', null, '[]', 20, 'DD r58'),
  ('RECOVERABLE_PART_TYPE', 'WIRE', 'WIRE', 'YES', 'Recover internal connection wires and harnesses', 'Store in designated Wire container partition', 'Harvested part', null, '[]', 30, 'DD r59'),
  ('RECOVERABLE_PART_TYPE', 'PCB', 'PCB', 'YES', 'Recover circuit board. Mandatory to record Model Name and Supplier Name after dismantle.', 'Prompt for Model Name & Supplier Name inputs', 'Harvested electronic part', null, '["pcb_model_id", "pcb_supplier_id"]', 40, 'DD r60'),
  ('PARTS_STORAGE_SEPARATION', 'DEDICATED_CONTAINERS', 'Different Dedicated Containers', 'YES', 'Separate individual containers used for each recovered part type', 'Assign physical container barcode / shelf', 'Storage method 1', null, '["container_id"]', 10, 'DD r61'),
  ('PARTS_STORAGE_SEPARATION', 'PARTITIONED_CONTAINER', 'Separations / Partitions in Single Container', 'YES', 'One large container partitioned into compartments for Tip, Body, Wire, PCB', 'Assign compartment ID', 'Storage method 2', null, '["partition_id"]', 20, 'DD r62'),
  ('CUSTODY_ASSIGNMENT', 'CUST_FUNCTIONAL_GOOD', 'Functional Stock (Good / Fresh)', 'YES', 'Managed by Intermediate Store Manager (Sahil)', 'Stage for Store Issue or Customer Dispatch', 'Intermediate store scope', null, '[]', 10, 'DD r63'),
  ('CUSTODY_ASSIGNMENT', 'CUST_FUNCTIONAL_REPAIRED', 'Functional Stock (Repaired)', 'YES', 'Managed by Intermediate Store Manager (Sahil)', 'Stage for Store Issue or General CN', 'Intermediate store scope', null, '[]', 20, 'DD r64'),
  ('CUSTODY_ASSIGNMENT', 'CUST_NON_FUNCTIONAL', 'Non-Functional / Scratched / Non-Sellable Stock', 'YES', 'Owned by Spare Parts Manager under Replacement Department', 'Retain under Replacement Dept Spare Parts stock', 'Spare parts manager scope', null, '[]', 30, 'DD r65'),
  ('CUSTODY_ASSIGNMENT', 'CUST_SALVAGED_PARTS', 'Salvaged Reusable Spare Parts (Tip / Body / Wire / PCB)', 'YES', 'Owned by Spare Parts Manager under Replacement Department', 'Add to replacement department spare parts ledger', 'Spare parts inventory', null, '[]', 40, 'DD r66'),
  ('STORE_ISSUE_TYPE', 'ISSUE_MAIN_STORE', 'Issue to Main Store', 'YES', 'Sahil transfers functional stock to Main Store ledger', 'Main Store inward entry created', 'Step-7 initial action', null, '[]', 10, 'DD r67'),
  ('RM_CN_DECISION', 'ALLOW_CN', 'Allow Credit Note (No Replacement Dispatched)', 'YES', 'Pieces are perfectly fine (good/fresh/repaired) and company will not send new/repaired piece', 'Send approval to Accounts Team (Deepak Ji) for CN', 'Triggers CN flow', null, '[]', 10, 'DD r68'),
  ('RM_CN_DECISION', 'DENY_CN_SEND_REPLACEMENT', 'Do Not Allow CN (Send Replacement Piece)', 'YES', 'Company will send replacement goods to customer instead of issuing financial credit', 'Route to dispatch team for replacement shipment', 'Physical replacement flow', null, '[]', 20, 'DD r69'),
  ('CN_TYPE', 'GST_CN', 'GST CREDIT NOTE', 'CONDITIONAL', 'Issued for Good / Packed pieces. Requires GST portal return reflection.', 'Check GST portal return status', 'Good/packed piece standard', null, '[]', 10, 'DD r70'),
  ('CN_TYPE', 'GENERAL_CN', 'GENERAL CREDIT NOTE', 'YES', 'Issued for Repaired functional pieces', 'Process General Credit Note voucher', 'Repaired piece standard', null, '[]', 20, 'DD r71'),
  -- JV_ONLY is not a workbook row: the system CN type of §8.6 / BR-34 / DEC-23 (P3-08 re-tag).
  ('CN_TYPE', 'JV_ONLY', 'Journal Voucher (JV) Only', 'CONDITIONAL', 'Issued when return is not reflected on GST portal. Permitted only as normal JV.', 'Record JV voucher details and valuation', 'System CN type (not a workbook row): the only record permitted when the return is not reflected on the GST portal (BR-34, DD r76).', null, '[]', 30, '§8.6 / BR-34 / DEC-23 [ARCH]'),
  ('PARTY_DOC_VERIFICATION', 'PARTY_INVOICE', 'Party Raised Invoice', 'YES', 'Discuss with party; verify if invoice was raised against returned goods', 'Match invoice details against historical rates', 'Commercial discussion', null, '[]', 10, 'DD r72'),
  ('PARTY_DOC_VERIFICATION', 'PARTY_DEBIT_NOTE', 'Party Raised Debit Note', 'YES', 'Discuss with party; verify party debit note number, date, and amount', 'Match debit note against internal sales records', 'Commercial discussion', null, '[]', 20, 'DD r73'),
  ('PARTY_DOC_VERIFICATION', 'PARTY_NO_DOC', 'No Commercial Document Raised by Party', 'YES', 'Party sent goods without tax invoice or debit note', 'Determine applicable rate from historical sales record', 'Commercial discussion', null, '[]', 30, 'DD r74'),
  ('GST_PORTAL_VERIFICATION', 'GST_REFLECTED', 'Return Reflected on GST Portal', 'YES', 'GST portal confirms sales return filed by party under GSTR-1 / GSTR-2B', 'Raise formal GST Credit Note with GSTIN and tax breakup', 'GST portal confirmed', null, '[]', 10, 'DD r75'),
  ('GST_PORTAL_VERIFICATION', 'GST_NOT_REFLECTED', 'Return NOT Reflected on GST Portal', 'CONDITIONAL', 'GST portal does not reflect return from party', 'Allow only a normal Journal Voucher (JV) entry for credit note', 'Strict compliance rule', null, '[]', 20, 'DD r76'),
  ('RATE_VERIFICATION_REF', 'RATE_SALES', 'Previous Sales Record Rate Check', 'YES', 'Accounts user checks historical sales invoice entries for exact customer billing rate', 'Apply verified sales rate to CN voucher', 'Pricing check', null, '[]', 10, 'DD r77'),
  ('RATE_VERIFICATION_REF', 'RATE_PURCHASE', 'Previous Purchase Entry Rate Check', 'YES', 'Accounts user checks previous purchase records for cost valuation reference (Deepak Ji discusses)', 'Validate valuation baseline', 'Cost check', null, '[]', 20, 'DD r78'),
  ('PARTY_NOTIFICATION_STATUS', 'PRIOR_INFO_SENT', 'Prior Information Sent with CN Details', 'YES', 'Send Credit Note Number, Credit Note Date, and item details to party prior to final closure', 'Close GS lifecycle in RMS', 'Mandatory notification rule', null, '[]', 10, 'DD r79'),
  ('CSR_FINAL_STATUS', 'CSR_CLOSED', 'Inward to Inventory with Packaging + CN Issued + Prior Party Info', 'YES', 'Summary flow: Goods handed over with packaging -> inward to INVENTORY + ACCOUNTS entry and CN issued + prior notification sent to party', 'GS successfully closed as Complete Sales Return', 'Summary flow (line 83)', null, '[]', 10, 'DD r80'),
  ('RM_ITEM_ACTION', 'SEND_NEW', 'Send New', 'YES', 'PRATHAM''S STEP will define the *PRINTABLE REPLACEMENT* SLIP; and also these actions can also be modified by Pratham Once the goods will be returned from the *Technical Team* so that should also be there.', null, null, null, '[]', 10, 'WF r6'),
  ('RM_ITEM_ACTION', 'SEND_REPAIRED', 'Send Repaired', 'YES', 'PRATHAM''S STEP will define the *PRINTABLE REPLACEMENT* SLIP; and also these actions can also be modified by Pratham Once the goods will be returned from the *Technical Team* so that should also be there.', null, null, null, '[]', 20, 'WF r6'),
  ('RM_ITEM_ACTION', 'ISSUE_CN', 'Issue CN', 'YES', 'PRATHAM''S STEP will define the *PRINTABLE REPLACEMENT* SLIP; and also these actions can also be modified by Pratham Once the goods will be returned from the *Technical Team* so that should also be there.', null, null, null, '[]', 30, 'WF r6'),
  ('RM_ITEM_ACTION', 'NOT_ALLOWED', 'Not Allowed', 'YES', 'PRATHAM''S STEP will define the *PRINTABLE REPLACEMENT* SLIP; and also these actions can also be modified by Pratham Once the goods will be returned from the *Technical Team* so that should also be there.', null, null, null, '[]', 40, 'WF r6'),
  ('RM_ITEM_ACTION', 'PENDING_BP', 'Pending (BP)', 'YES', 'PRATHAM''S STEP will define the *PRINTABLE REPLACEMENT* SLIP; and also these actions can also be modified by Pratham Once the goods will be returned from the *Technical Team* so that should also be there.', null, null, null, '[]', 50, 'WF r6')
) as v(set_code, code, label, allowed_status, rule_text, next_action_text, remarks, system_behavior,
      required_fields, sort_order, source_ref)
join public.option_sets os on os.code = v.set_code
on conflict (option_set_id, code) do nothing;

-- -----------------------------------------------------------------------------
-- Change request 2026-11-12 (docs/RMS_MASTER_PLAN_ADDENDUM_2026-11.md), Phase 2 — gate entry.
-- AMD-01: RETURN_TYPE (Offline / E-Commerce). AMD-04: gate document row types added to
-- GATE_DOCUMENT (Courier Slip, LR / Bilty, Delivery Note, Other). "Challan" is the existing
-- DELIVERY_CHALLAN code (codes are immutable, no duplicate). NO_DOCUMENT stays for v1 forms; from
-- v2 "no document" is the GS-level missing_documentation flag (DEC-03).
-- -----------------------------------------------------------------------------
insert into public.option_sets (code, name, description, control_type, source_kind, master_ref_type, source_ref, is_system)
values ('RETURN_TYPE', 'Return Type', 'Stage-1 · Step-1 · Goods Slip (GS) Creation · Gate Inward User · General', 'radio', 'STATIC', null, 'AMD-01', true)
on conflict (code) do nothing;

insert into public.option_items (option_set_id, code, label, allowed_status, rule_text, next_action_text,
                                 remarks, system_behavior, required_fields, sort_order, source_ref)
select os.id, v.code, v.label, v.allowed_status, v.rule_text, v.next_action_text, v.remarks,
       v.system_behavior, v.required_fields::jsonb, v.sort_order, v.source_ref
from (values
  ('RETURN_TYPE', 'OFFLINE_RETURN', 'Offline Return', 'YES', 'Record gate entry date and gate entry number', 'Proceed to GS Generation', 'Distributor / dealer consignment', null, '["gate_entry_date", "gate_entry_no"]', 10, 'AMD-01, AMD-02'),
  ('RETURN_TYPE', 'ECOMMERCE_RETURN', 'E-Commerce Return', 'YES', 'Same gate form without gate entry date and number', 'Proceed to GS Generation', 'Marketplace / online return', null, '[]', 20, 'AMD-01, DEC-39'),
  ('GATE_DOCUMENT', 'COURIER_SLIP', 'Courier Slip', 'YES', null, 'Attach to Inward Entry', 'Physical document received', null, '[]', 35, 'AMD-04'),
  ('GATE_DOCUMENT', 'LR_BILITY', 'LR / Bilty', 'YES', null, 'Attach to Inward Entry', 'Physical document received', null, '[]', 36, 'AMD-04'),
  ('GATE_DOCUMENT', 'DELIVERY_NOTE', 'Delivery Note', 'YES', null, 'Attach to Inward Entry', 'Physical document received', null, '[]', 37, 'AMD-04'),
  ('GATE_DOCUMENT', 'OTHER', 'Other', 'YES', null, 'Attach to Inward Entry', 'Physical document received', null, '[]', 45, 'AMD-04')
) as v(set_code, code, label, allowed_status, rule_text, next_action_text, remarks, system_behavior,
      required_fields, sort_order, source_ref)
join public.option_sets os on os.code = v.set_code
on conflict (option_set_id, code) do nothing;

-- Change request 2026-11-12, Phase 3 (AMD-08): display labels of the goods-slip statuses. Codes are
-- the goods_slips.status values (§6.5) and never change; admins may relabel. Status list confirmed
-- by the user on 2026-11-13: UNBOXING = Carton Opening, ITEMIZATION = Counting, + CATEGORISATION.
insert into public.option_sets (code, name, description, control_type, source_kind, master_ref_type, source_ref, is_system)
values ('GS_STATUS', 'Goods Slip Status', 'Display labels of the goods-slip lifecycle statuses (codes fixed by the system)', 'dropdown', 'STATIC', null, 'AMD-08', true)
on conflict (code) do nothing;

insert into public.option_items (option_set_id, code, label, allowed_status, rule_text, next_action_text,
                                 remarks, system_behavior, required_fields, sort_order, source_ref)
select os.id, v.code, v.label, 'YES', null, null, null, null, '[]'::jsonb, v.sort_order, v.source_ref
from (values
  ('GATE_CREATED', 'Gate Entry', 10, '§6.5'),
  ('UNBOXING', 'Carton Opening', 20, 'AMD-08'),
  ('ITEMIZATION', 'Counting', 30, 'AMD-08'),
  ('CATEGORISATION', 'Categorisation', 40, 'AMD-08'),
  ('CSR_APPROVAL_PENDING', 'CSR Approval Pending', 50, '§6.5'),
  ('INSPECTION', 'Inspection', 60, '§6.5'),
  ('RM_REVIEW', 'RM Review', 70, '§6.5'),
  ('HELD_AT_INTERMEDIATE_STORE', 'Held at Intermediate Store', 75, 'AMD-13'),
  ('IN_PROCESS', 'In Process', 80, '§6.5'),
  ('COMMERCIAL_RESOLUTION', 'Commercial Resolution', 90, '§6.5'),
  ('AWAITING_NOTIFICATION', 'Awaiting Notification', 100, '§6.5'),
  ('CLOSED', 'Closed', 110, '§6.5'),
  ('CANCELLED', 'Cancelled', 120, '§6.5')
) as v(code, label, sort_order, source_ref)
join public.option_sets os on os.code = 'GS_STATUS'
on conflict (option_set_id, code) do nothing;

-- -----------------------------------------------------------------------------
-- Product categories (§8.2; DEC-15, DEC-18, BR-14, G-05/G-06)
-- -----------------------------------------------------------------------------
insert into public.product_categories
  (code, name, requires_full_opening, supports_battery, supports_dismantling, hazard_capable, condition_option_set_id)
select v.code, v.name, v.full_opening, v.battery, v.dismantling, v.hazard, os.id
from (values
  ('DMT',           'DMT',           false, true,  true,  false, 'DMT_CONDITION'),
  ('PRISMATIC',     'PRISMATIC',     false, false, false, true,  'PRISMATIC_CONDITION'),
  ('ENCLOSED_OVAL', 'ENCLOSED OVAL', true,  false, false, true,  'EO_CONDITION'),
  -- Non-thermometer catalogue items (BP monitors, nebulizers, supports, consumables, ...): every
  -- flag off and no condition option set yet (docs/DECISIONS.md, 2026-11-12 product import).
  ('GENERAL',       'GENERAL',       false, false, false, false, null)
) as v(code, name, full_opening, battery, dismantling, hazard, condition_set)
left join public.option_sets os on os.code = v.condition_set
on conflict (code) do nothing;

-- -----------------------------------------------------------------------------
-- Item field profiles (Phase 4, AMD-10 / AMD-16): condition options -> CATEGORISATION buckets per
-- category; RM_ITEM_ACTION options -> ACTION library assigned to every category. Same function as
-- migration 20261113000400 (which runs before this catalogue exists on a fresh reset). One statement,
-- so it is one profile version.
-- -----------------------------------------------------------------------------
select rms_private.seed_item_field_library_from_options();

-- -----------------------------------------------------------------------------
-- Inventory locations (§8.2; custodians per P1-02 prompt and DEC-10)
-- -----------------------------------------------------------------------------
insert into public.inventory_locations (code, name, location_class, custodian_role_id, department_id)
select v.code, v.name, v.location_class, r.id, d.id
from (values
  ('INWARD_STAGING',       'Inward Staging',       'INWARD',            'INWARD_VERIFIER',            null),
  ('TRANSIT',              'In Transit',           'TRANSIT',           null,                         null),
  ('INTERMEDIATE_STORE',   'Intermediate Store',   'FUNCTIONAL',        'INTERMEDIATE_STORE_MANAGER', 'INTERMEDIATE_STORE'),
  ('TECHNICIAN_BENCH',     'Technician Bench',     'TECHNICIAN',        null,                         null),
  ('NON_FUNCTIONAL_STORE', 'Non-Functional Store', 'NON_FUNCTIONAL',    'SPARE_PARTS_MANAGER',        'REPLACEMENT_DEPT'),
  ('BATTERY_STORE',        'Battery Store',        'SPARE_PARTS',       'SPARE_PARTS_MANAGER',        'REPLACEMENT_DEPT'),
  ('SPARE_PARTS_STORE',    'Spare Parts Store',    'SPARE_PARTS',       'SPARE_PARTS_MANAGER',        'REPLACEMENT_DEPT'),
  ('REJECTED_HOLD',        'Rejected Hold',        'REJECTED_HOLD',     'REPLACEMENT_MANAGER',        'REPLACEMENT_DEPT'),
  ('HAZARD_QUARANTINE',    'Hazard Quarantine',    'HAZARD_QUARANTINE', 'SPARE_PARTS_MANAGER',        'REPLACEMENT_DEPT'),  -- DEC-10 default
  ('PENDING_HOLD',         'Pending Hold',         'PENDING_HOLD',      null,                         null),
  ('MAIN_STORE',           'Main Store',           'MAIN_STORE',        null,                         'MAIN_STORE'),
  ('DISPATCHED',           'Dispatched',           'DISPATCHED',        null,                         null),
  ('SCRAP_DISPOSED',       'Scrap Disposed',       'SCRAP_DISPOSED',    null,                         null),
  ('CREDITED',             'Credited',             'CREDITED',          null,                         null)
) as v(code, name, location_class, custodian_role, department)
left join public.roles r on r.code = v.custodian_role
left join public.departments d on d.code = v.department
on conflict (code) do update set custodian_role_id = excluded.custodian_role_id, department_id = excluded.department_id;

-- -----------------------------------------------------------------------------
-- DMT return containers for the daily container audit (BR-18, DEC-08). Same rows as migration
-- 20261103000500_p2_06; repeated here because that migration runs before the locations above
-- exist, so on a fresh `supabase db reset` its insert matched nothing (fixed in P2-08).
-- -----------------------------------------------------------------------------
insert into public.storage_containers (code, barcode, name, container_type, location_id, is_active)
select c.code, c.barcode, c.name, 'DMT_RETURN', l.id, true
from (values
  ('DMT-BIN-01', 'DMT-BIN-01', 'DMT Return Bin 01'),
  ('DMT-BIN-02', 'DMT-BIN-02', 'DMT Return Bin 02'),
  ('DMT-BIN-03', 'DMT-BIN-03', 'DMT Return Bin 03'),
  ('DMT-BIN-04', 'DMT-BIN-04', 'DMT Return Bin 04')
) as c(code, barcode, name)
join public.inventory_locations l on l.code = 'INWARD_STAGING'
on conflict (code) do nothing;

-- -----------------------------------------------------------------------------
-- Number series (DEC-01). GS uses the PLACEHOLDER pattern until the business provides the
-- existing format; all patterns are editable by the admin (P1-08).
-- -----------------------------------------------------------------------------
insert into public.number_series (code, name, prefix, pattern, reset_policy, fy_start_month, fy_format) values
  ('GS',          'Goods Slip',            'GS',  'GS/{FY}/{SEQ:5}',       'YEARLY_FY', 4, 'LONG'),
  ('TRANSFER',    'Custody Transfer',      'TRF', '{PREFIX}/{FY}/{SEQ:5}', 'YEARLY_FY', 4, 'LONG'),
  ('TECH_BATCH',  'Technician Batch',      'TB',  '{PREFIX}/{FY}/{SEQ:5}', 'YEARLY_FY', 4, 'LONG'),
  ('DISMANTLE',   'Dismantle Batch',       'DSM', '{PREFIX}/{FY}/{SEQ:5}', 'YEARLY_FY', 4, 'LONG'),
  ('STORE_ISSUE', 'Store Issue',           'SI',  '{PREFIX}/{FY}/{SEQ:5}', 'YEARLY_FY', 4, 'LONG'),
  ('DISPATCH',    'Replacement Dispatch',  'DSP', '{PREFIX}/{FY}/{SEQ:5}', 'YEARLY_FY', 4, 'LONG')
on conflict (code) do nothing;

-- -----------------------------------------------------------------------------
-- System settings (§10 System settings; provisional DEC toggles from §5)
-- -----------------------------------------------------------------------------
insert into public.system_settings (key, value, category, description, source_ref) values
  ('app_name',                       '"Replacement Management System"', 'general',  'Application name shown in the UI and print headers.', null),
  ('timezone',                       '"Asia/Kolkata"',                   'general',  'Business timezone (IANA).', null),
  ('date_format',                    '"DD-MM-YYYY"',                     'general',  'Display date format.', null),
  ('page_size',                      '25',                               'general',  'Default page size for lists.', null),
  ('upload_max_video_bytes',         '1073741824',                       'uploads',  'Maximum unboxing video size (1 GB).', 'DEC-04'),
  ('upload_max_document_bytes',      '26214400',                         'uploads',  'Maximum document photo / PDF size (25 MB).', null),
  ('signed_url_ttl_seconds',         '600',                              'security', 'Lifetime of signed download/upload URLs.', null),
  ('pending_blocks_entire_gs',       'false',                            'provisional', 'Provisional: Pending (BP) blocks only the pending pieces; non-pending pieces may continue to handover.', 'DEC-12'),
  ('daily_audit_blocks_inspection',  'false',                            'provisional', 'Provisional: a missed daily DMT container audit raises an alert but does not block inspection.', 'DEC-08'),
  ('segregation_of_duties_transfer', 'true',                             'workflow',    'The same user cannot initiate and accept a custody transfer.', '§9.3'),
  ('extraction_rule',                '"packaging_plus_container_equals_received"', 'provisional', 'Provisional extraction reconciliation: packaging_qty + container_qty = received_qty.', 'DEC-07'),
  ('party_state_station_autofill',   'true',                             'provisional', 'Auto-fill state and station from party master with manual override.', 'DEC-02'),
  ('contact_phone_pattern',          '"^([+]91[ -]?|0)?[6-9][0-9]{9}$"', 'validation',  'Provisional: regex for contact numbers captured at the gate (Indian mobile, optional +91 / 0 prefix).', 'P2-02'),
  ('no_document_requires_rm_approval','true',                            'provisional', 'Consignments with missing gate documents require RM approval at Step-2.', 'DEC-03'),
  ('unboxing_video_per_box',         'false',                            'provisional', 'Allow video per GS (false) or require per box (true).', 'DEC-04'),
  ('accounts_alert_on_doc_classified','true',                            'provisional', 'Alert Accounts team when invoices and debit notes are classified.', 'DEC-05'),
  ('upload_resumable_threshold_bytes','6291456',                         'uploads',     'Videos larger than this (6 MB) upload through the resumable (TUS) endpoint.', 'DEC-04'),
  ('pending_upload_retention_hours', '24',                               'uploads',     'Uploads never confirmed are deleted (row and object) after this many hours.', 'P2-03'),
  ('allow_mixed_csr_ro_gs',          'false',                            'provisional', 'Enforce one categorization (CSR vs RO) per GS.', 'DEC-06'),
  ('track_short_qty_all_categories', 'true',                             'provisional', 'Track short quantity discrepancy for all categories, not just DMT.', 'DEC-09'),
  ('return_to_party_dispatch_enabled','false',                           'provisional', 'Enable return-to-party dispatch route for rejected goods.', 'DEC-10'),
  ('mercury_quarantine_manifest_req','true',                             'provisional', 'Require manifest reference for hazardous mercury disposal.', 'DEC-11'),
  ('cn_decision_prefill_from_rm',    'true',                             'provisional', 'Pre-fill Step-7 CN decision from Step-3 a) RM planned actions.', 'DEC-13'),
  ('skip_technician_for_sellable',   'true',                             'provisional', 'Allow visually OK packed items to bypass technician servicing.', 'DEC-14'),
  ('battery_check_dmt_only',         'true',                             'provisional', 'Battery check and consumption applies only to battery-supported categories.', 'DEC-15'),
  ('cleaning_req_only_for_dirty',    'true',                             'provisional', 'Cleaning treatment required only when inbound condition is dirty or scratched.', 'DEC-16'),
  ('permanent_scratches_non_sellable','true',                            'provisional', 'Permanent scratches force item to non-sellable custody with Spare Parts Manager.', 'DEC-17'),
  ('dismantling_dmt_only',           'true',                             'provisional', 'Dismantling parts recovery applies only to DMT products.', 'DEC-18'),
  ('dismantling_reconcile_units',    'true',                             'provisional', 'Reconcile dismantled units count rather than component parts yield.', 'DEC-19'),
  ('department_structure_enabled',   'true',                             'provisional', 'Enable standard five-department operational structure.', 'DEC-20'),
  ('branding_primary_color',         '"#0f172a"',                        'branding',    'Primary brand color for application shell and headers.', null),
  ('branding_logo_url',              '"/assets/logo.png"',               'branding',    'Branding logo URL displayed in shell and print headers.', null),
  ('company_name',                   '"Hicks Thermometers (India) Limited"', 'branding', 'Company name shown on the sign-in page and footers.', 'P1-05'),
  ('dashboard_poll_seconds',         '60',                               'dashboards',  'Dashboards re-fetch widget data at this interval (seconds) when no realtime event arrives.', 'P4-01'),
  ('dashboard_cache_seconds',        '30',                               'dashboards',  'Server-side cache lifetime (seconds, 0-60) for aggregate widget data. Task widgets are never cached.', 'P4-01'),
  ('container_audit_compliance_days','30',                               'dashboards',  'Window (days, ending yesterday) for the container audit compliance percentage on dashboards.', 'P4-01'),
  ('report_export_max_rows',         '100000',                           'reports',     'Largest CSV / XLSX report export (rows). A larger result is refused with a request to narrow the filters.', 'P4-02'),
  ('report_print_max_rows',          '2000',                             'reports',     'Largest printable report (rows). A larger result prints the first rows and says so in the header.', 'P4-02'),
  ('report_default_window_days',     '30',                               'reports',     'Default date window (days, ending today) for report date filters.', 'P4-02')
on conflict (key) do nothing;

-- =============================================================================
-- -----------------------------------------------------------------------------
-- Published v1 forms for all 20 workflow steps (master plan §3.2, §8.3, §10, prompt P1-07)
-- Idempotent: safe to run multiple times without re-creating existing published versions.
-- -----------------------------------------------------------------------------
do $$
declare
  v_def_id uuid;
  v_ver_id uuid;
  v_snapshot jsonb;
  v_opt_set_id uuid;
begin
  -- Form S1_GATE_INWARD
  insert into public.form_definitions (code, step_code, name, is_active)
  values ('S1_GATE_INWARD', 'S1_GATE', 'Gate Inward & GS Creation', true)
  on conflict (code) do update set step_code = excluded.step_code, name = excluded.name
  returning id into v_def_id;

  -- If no published version exists for S1_GATE_INWARD, create draft v1, populate fields, and publish
  if not exists (select 1 from public.form_versions where form_definition_id = v_def_id and status = 'PUBLISHED') then
    -- Insert draft version
    insert into public.form_versions (form_definition_id, version_no, status)
    values (v_def_id, 1, 'DRAFT')
    returning id into v_ver_id;

    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'state', 'State', 'text', null,
      null, true, null, null, null,
      null, 10, 'Consignment Header', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'station', 'Station', 'text', null,
      null, true, null, null, null,
      null, 20, 'Consignment Header', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'party_name', 'Party Name', 'text', null,
      null, true, null, null, null,
      null, 30, 'Consignment Header', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'box_count', 'Box Count', 'number', null,
      null, true, null, null, '{"min": 1}'::jsonb,
      null, 40, 'Consignment Header', true
    );
    select id into v_opt_set_id from public.option_sets where code = 'DELIVERY_MODE';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'delivery_mode', 'Delivery Mode / Transporter', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      null, 50, 'Delivery Details', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'courier_name', 'Courier Name', 'text', null,
      null, false, '{"field": "delivery_mode", "op": "eq", "value": "COURIER_PARCEL"}'::jsonb, '{"field": "delivery_mode", "op": "eq", "value": "COURIER_PARCEL"}'::jsonb, null,
      null, 60, 'Delivery Details', false
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'docket_no', 'Docket Number', 'text', null,
      null, false, '{"field": "delivery_mode", "op": "eq", "value": "COURIER_PARCEL"}'::jsonb, '{"field": "delivery_mode", "op": "eq", "value": "COURIER_PARCEL"}'::jsonb, null,
      null, 70, 'Delivery Details', false
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'vehicle_no', 'Vehicle Number', 'text', null,
      null, false, '{"field": "delivery_mode", "op": "eq", "value": "DIRECT_TRUCK"}'::jsonb, '{"field": "delivery_mode", "op": "eq", "value": "DIRECT_TRUCK"}'::jsonb, null,
      null, 80, 'Delivery Details', false
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'transporter_name', 'Transporter Name', 'text', null,
      null, false, '{"field": "delivery_mode", "op": "eq", "value": "DIRECT_TRUCK"}'::jsonb, '{"field": "delivery_mode", "op": "eq", "value": "DIRECT_TRUCK"}'::jsonb, null,
      null, 90, 'Delivery Details', false
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'rep_name', 'Representative Name', 'text', null,
      null, false, '{"field": "delivery_mode", "op": "eq", "value": "SELF_PARTY_REP"}'::jsonb, '{"field": "delivery_mode", "op": "eq", "value": "SELF_PARTY_REP"}'::jsonb, null,
      null, 100, 'Delivery Details', false
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'rep_contact', 'Representative Contact No.', 'text', null,
      null, false, '{"field": "delivery_mode", "op": "eq", "value": "SELF_PARTY_REP"}'::jsonb, '{"field": "delivery_mode", "op": "eq", "value": "SELF_PARTY_REP"}'::jsonb, null,
      null, 110, 'Delivery Details', false
    );
    select id into v_opt_set_id from public.option_sets where code = 'GATE_DOCUMENT';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'accompanying_doc', 'Accompanying Document at Gate', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      null, 120, 'Documentation', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'gate_doc_no', 'Gate Document Number', 'text', null,
      null, false, '{"field": "accompanying_doc", "op": "in", "value": ["INVOICE", "DEBIT_NOTE", "DELIVERY_CHALLAN"]}'::jsonb, '{"field": "accompanying_doc", "op": "in", "value": ["INVOICE", "DEBIT_NOTE", "DELIVERY_CHALLAN"]}'::jsonb, null,
      null, 130, 'Documentation', false
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'gate_doc_date', 'Gate Document Date', 'date', null,
      null, false, '{"field": "accompanying_doc", "op": "in", "value": ["INVOICE", "DEBIT_NOTE", "DELIVERY_CHALLAN"]}'::jsonb, '{"field": "accompanying_doc", "op": "in", "value": ["INVOICE", "DEBIT_NOTE", "DELIVERY_CHALLAN"]}'::jsonb, '{"date_not_in_future": true}'::jsonb,
      null, 140, 'Documentation', false
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'gate_doc_image', 'Document Picture / Image', 'file', null,
      null, false, '{"field": "accompanying_doc", "op": "in", "value": ["INVOICE", "DEBIT_NOTE", "DELIVERY_CHALLAN", "HANDWRITTEN_SLIP"]}'::jsonb, null, null,
      null, 145, 'Documentation', false
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'gate_doc_remarks', 'Slip Remarks / Party Note', 'textarea', null,
      null, false, '{"field": "accompanying_doc", "op": "eq", "value": "HANDWRITTEN_SLIP"}'::jsonb, '{"field": "accompanying_doc", "op": "eq", "value": "HANDWRITTEN_SLIP"}'::jsonb, null,
      null, 150, 'Documentation', false
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'missing_doc_warning_acknowledged', 'Missing documentation warning acknowledged', 'checkbox', null,
      null, false, '{"field": "accompanying_doc", "op": "eq", "value": "NO_DOCUMENT"}'::jsonb, '{"field": "accompanying_doc", "op": "eq", "value": "NO_DOCUMENT"}'::jsonb, null,
      null, 160, 'Documentation', false
    );
    select id into v_opt_set_id from public.option_sets where code = 'GS_CREATION_FORMAT';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'gs_creation_format', 'GS Creation Format', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      '"AUTO_STANDARD"'::jsonb, 170, 'System Generation', true
    );

    -- Build frozen snapshot jsonb
    select jsonb_build_object(
      'form_code', 'S1_GATE_INWARD',
      'name', 'Gate Inward & GS Creation',
      'step_code', 'S1_GATE',
      'version_no', 1,
      'version_notes', 'Initial v1 seed',
      'fields', coalesce(jsonb_agg(
        to_jsonb(fld) || jsonb_build_object(
          'option_items', coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'code', oi.code,
                'label', oi.label,
                'allowed_status', oi.allowed_status,
                'rule_text', oi.rule_text,
                'next_action_text', oi.next_action_text,
                'remarks', oi.remarks,
                'system_behavior', oi.system_behavior,
                'sort_order', oi.sort_order,
                'is_active', oi.is_active
              ) order by oi.sort_order asc, oi.code asc
            )
            from public.option_items oi
            where oi.option_set_id = fld.option_set_id
          ), '[]'::jsonb)
        ) order by fld.sort_order asc, fld.field_key asc
      ), '[]'::jsonb)
    ) into v_snapshot
    from public.form_fields fld
    where fld.form_version_id = v_ver_id;

    -- Publish draft version 1
    update public.form_versions
    set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
    where id = v_ver_id;
  end if;

  -- Form S1_UNBOXING
  insert into public.form_definitions (code, step_code, name, is_active)
  values ('S1_UNBOXING', 'S1_UNBOX', 'Carton Opening & Document Capture', true)
  on conflict (code) do update set step_code = excluded.step_code, name = excluded.name
  returning id into v_def_id;

  -- If no published version exists for S1_UNBOXING, create draft v1, populate fields, and publish
  if not exists (select 1 from public.form_versions where form_definition_id = v_def_id and status = 'PUBLISHED') then
    -- Insert draft version
    insert into public.form_versions (form_definition_id, version_no, status)
    values (v_def_id, 1, 'DRAFT')
    returning id into v_ver_id;

    select id into v_opt_set_id from public.option_sets where code = 'UNBOXING_VIDEO';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'unboxing_video', 'Continuous Unboxing Video File (.mp4 / .mov)', 'file', v_opt_set_id,
      null, true, null, null, '{"file_types": [".mp4", ".mov"], "max_file_size": 209715200}'::jsonb,
      null, 10, 'Video Recording', true
    );
    select id into v_opt_set_id from public.option_sets where code = 'RECEIVED_DOC_CLASSIFICATION';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'doc_classification', 'Received Document Classification', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      null, 20, 'Document Verification', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'buyer_gstin', 'Buyer GSTIN', 'text', null,
      null, false, '{"field": "doc_classification", "op": "eq", "value": "INVOICE"}'::jsonb, '{"field": "doc_classification", "op": "eq", "value": "INVOICE"}'::jsonb, '{"regex": "^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"}'::jsonb,
      null, 30, 'Document Verification', false
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'seller_gstin', 'Seller GSTIN', 'text', null,
      null, false, '{"field": "doc_classification", "op": "eq", "value": "INVOICE"}'::jsonb, '{"field": "doc_classification", "op": "eq", "value": "INVOICE"}'::jsonb, '{"regex": "^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"}'::jsonb,
      null, 40, 'Document Verification', false
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'dn_number', 'Debit Note Number', 'text', null,
      null, false, '{"field": "doc_classification", "op": "eq", "value": "DEBIT_NOTE"}'::jsonb, '{"field": "doc_classification", "op": "eq", "value": "DEBIT_NOTE"}'::jsonb, null,
      null, 50, 'Document Verification', false
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'dn_amount', 'Debit Note Amount', 'number', null,
      null, false, '{"field": "doc_classification", "op": "eq", "value": "DEBIT_NOTE"}'::jsonb, '{"field": "doc_classification", "op": "eq", "value": "DEBIT_NOTE"}'::jsonb, '{"min": 0}'::jsonb,
      null, 60, 'Document Verification', false
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'challan_qty_matched', 'Challan quantity matched against parcel contents', 'checkbox', null,
      null, false, '{"field": "doc_classification", "op": "eq", "value": "DELIVERY_CHALLAN"}'::jsonb, '{"field": "doc_classification", "op": "eq", "value": "DELIVERY_CHALLAN"}'::jsonb, null,
      null, 70, 'Document Verification', false
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'party_claim_text', 'Party Claim / Complaint Details', 'textarea', null,
      null, false, '{"field": "doc_classification", "op": "eq", "value": "HANDWRITTEN_SLIP"}'::jsonb, '{"field": "doc_classification", "op": "eq", "value": "HANDWRITTEN_SLIP"}'::jsonb, null,
      null, 80, 'Document Verification', false
    );
    select id into v_opt_set_id from public.option_sets where code = 'DOCUMENT_PHOTO';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'document_photo', 'Document Photo Image (.jpg / .png / .pdf)', 'file', v_opt_set_id,
      null, true, null, null, '{"file_types": [".jpg", ".jpeg", ".png", ".pdf"], "max_file_size": 20971520}'::jsonb,
      null, 90, 'Document Verification', true
    );

    -- Build frozen snapshot jsonb
    select jsonb_build_object(
      'form_code', 'S1_UNBOXING',
      'name', 'Unboxing & Document Capture',
      'step_code', 'S1_UNBOX',
      'version_no', 1,
      'version_notes', 'Initial v1 seed',
      'fields', coalesce(jsonb_agg(
        to_jsonb(fld) || jsonb_build_object(
          'option_items', coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'code', oi.code,
                'label', oi.label,
                'allowed_status', oi.allowed_status,
                'rule_text', oi.rule_text,
                'next_action_text', oi.next_action_text,
                'remarks', oi.remarks,
                'system_behavior', oi.system_behavior,
                'sort_order', oi.sort_order,
                'is_active', oi.is_active
              ) order by oi.sort_order asc, oi.code asc
            )
            from public.option_items oi
            where oi.option_set_id = fld.option_set_id
          ), '[]'::jsonb)
        ) order by fld.sort_order asc, fld.field_key asc
      ), '[]'::jsonb)
    ) into v_snapshot
    from public.form_fields fld
    where fld.form_version_id = v_ver_id;

    -- Publish draft version 1
    update public.form_versions
    set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
    where id = v_ver_id;
  end if;

  -- S1_UNBOXING v2 (prompt P2-03, DD r12–r15, BR-05): adds the Invoice number / date, the
  -- item-details-verified check and the challan remarks the Step-2 classification card records.
  -- File limits are no longer duplicated in the form: system_settings upload_max_*_bytes (DEC-04)
  -- are authoritative. v1 is retired, never edited (G-18).
  if not exists (select 1 from public.form_versions where form_definition_id = v_def_id and version_no = 2) then
    insert into public.form_versions (form_definition_id, version_no, status)
    values (v_def_id, 2, 'DRAFT')
    returning id into v_ver_id;

    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id, master_ref_type, is_required,
      visible_when, required_when, validation, default_value, sort_order, section, is_core, help_text,
      is_system_locked
    )
    select v_ver_id, f.field_key, f.label, f.control_type, f.option_set_id, f.master_ref_type,
           f.is_required, f.visible_when, f.required_when,
           case when f.control_type = 'file' then (f.validation - 'max_file_size') else f.validation end,
           f.default_value, f.sort_order, f.section, f.is_core, f.help_text, f.is_system_locked
      from public.form_fields f
      join public.form_versions v on v.id = f.form_version_id
     where v.form_definition_id = v_def_id and v.version_no = 1;

    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id, master_ref_type, is_required,
      visible_when, required_when, validation, default_value, sort_order, section, is_core
    ) values
      (v_ver_id, 'invoice_no', 'Invoice No.', 'text', null, null, false,
       '{"field": "doc_classification", "op": "eq", "value": "INVOICE"}'::jsonb,
       '{"field": "doc_classification", "op": "eq", "value": "INVOICE"}'::jsonb,
       '{"max_length": 60}'::jsonb, null, 24, 'Document Verification', false),
      (v_ver_id, 'invoice_date', 'Invoice Date', 'date', null, null, false,
       '{"field": "doc_classification", "op": "eq", "value": "INVOICE"}'::jsonb,
       '{"field": "doc_classification", "op": "eq", "value": "INVOICE"}'::jsonb,
       null, null, 26, 'Document Verification', false),
      (v_ver_id, 'items_verified', 'Item details verified against the invoice', 'checkbox', null, null, false,
       '{"field": "doc_classification", "op": "eq", "value": "INVOICE"}'::jsonb,
       '{"field": "doc_classification", "op": "eq", "value": "INVOICE"}'::jsonb,
       null, null, 45, 'Document Verification', false),
      (v_ver_id, 'challan_remarks', 'Challan Remarks', 'textarea', null, null, false,
       '{"field": "doc_classification", "op": "eq", "value": "DELIVERY_CHALLAN"}'::jsonb,
       '{"all": [{"field": "doc_classification", "op": "eq", "value": "DELIVERY_CHALLAN"}, {"field": "challan_qty_matched", "op": "neq", "value": true}]}'::jsonb,
       '{"max_length": 1000}'::jsonb, null, 75, 'Document Verification', false);

    select jsonb_build_object(
      'form_code', 'S1_UNBOXING',
      'name', 'Unboxing & Document Capture',
      'step_code', 'S1_UNBOX',
      'version_no', 2,
      'version_notes', 'P2-03: invoice no./date, items verified, challan remarks',
      'fields', coalesce(jsonb_agg(
        to_jsonb(fld) || jsonb_build_object(
          'option_items', coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'code', oi.code,
                'label', oi.label,
                'allowed_status', oi.allowed_status,
                'rule_text', oi.rule_text,
                'next_action_text', oi.next_action_text,
                'remarks', oi.remarks,
                'system_behavior', oi.system_behavior,
                'sort_order', oi.sort_order,
                'is_active', oi.is_active
              ) order by oi.sort_order asc, oi.code asc
            )
            from public.option_items oi
            where oi.option_set_id = fld.option_set_id
          ), '[]'::jsonb)
        ) order by fld.sort_order asc, fld.field_key asc
      ), '[]'::jsonb)
    ) into v_snapshot
    from public.form_fields fld
    where fld.form_version_id = v_ver_id;

    update public.form_versions set status = 'RETIRED'
     where form_definition_id = v_def_id and status = 'PUBLISHED';
    update public.form_versions
       set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
     where id = v_ver_id;
  end if;

  -- Form S1_ITEMIZE
  insert into public.form_definitions (code, step_code, name, is_active)
  values ('S1_ITEMIZE', 'S1_ITEMIZE', 'Counting & Return Categorization', true)
  on conflict (code) do update set step_code = excluded.step_code, name = excluded.name
  returning id into v_def_id;

  -- If no published version exists for S1_ITEMIZE, create draft v1, populate fields, and publish
  if not exists (select 1 from public.form_versions where form_definition_id = v_def_id and status = 'PUBLISHED') then
    -- Insert draft version
    insert into public.form_versions (form_definition_id, version_no, status)
    values (v_def_id, 1, 'DRAFT')
    returning id into v_ver_id;

    select id into v_opt_set_id from public.option_sets where code = 'RETURN_CATEGORY';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'return_category', 'Return Categorization (GS Wise)', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      null, 10, 'Categorization', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'received_qty', 'Received Quantity', 'number', null,
      null, true, null, null, '{"min": 1}'::jsonb,
      null, 20, 'Quantities', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'item_notes', 'Itemization Remarks / Observations', 'textarea', null,
      null, false, null, null, null,
      null, 30, 'Notes', false
    );

    -- Build frozen snapshot jsonb
    select jsonb_build_object(
      'form_code', 'S1_ITEMIZE',
      'name', 'Item Addition & Return Categorization',
      'step_code', 'S1_ITEMIZE',
      'version_no', 1,
      'version_notes', 'Initial v1 seed',
      'fields', coalesce(jsonb_agg(
        to_jsonb(fld) || jsonb_build_object(
          'option_items', coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'code', oi.code,
                'label', oi.label,
                'allowed_status', oi.allowed_status,
                'rule_text', oi.rule_text,
                'next_action_text', oi.next_action_text,
                'remarks', oi.remarks,
                'system_behavior', oi.system_behavior,
                'sort_order', oi.sort_order,
                'is_active', oi.is_active
              ) order by oi.sort_order asc, oi.code asc
            )
            from public.option_items oi
            where oi.option_set_id = fld.option_set_id
          ), '[]'::jsonb)
        ) order by fld.sort_order asc, fld.field_key asc
      ), '[]'::jsonb)
    ) into v_snapshot
    from public.form_fields fld
    where fld.form_version_id = v_ver_id;

    -- Publish draft version 1
    update public.form_versions
    set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
    where id = v_ver_id;
  end if;

  -- Form S1_CSR_APPROVAL
  insert into public.form_definitions (code, step_code, name, is_active)
  values ('S1_CSR_APPROVAL', 'S1_CSR_APPROVAL', 'Complete Sales Return Approval', true)
  on conflict (code) do update set step_code = excluded.step_code, name = excluded.name
  returning id into v_def_id;

  -- If no published version exists for S1_CSR_APPROVAL, create draft v1, populate fields, and publish
  if not exists (select 1 from public.form_versions where form_definition_id = v_def_id and status = 'PUBLISHED') then
    -- Insert draft version
    insert into public.form_versions (form_definition_id, version_no, status)
    values (v_def_id, 1, 'DRAFT')
    returning id into v_ver_id;

    select id into v_opt_set_id from public.option_sets where code = 'CSR_APPROVAL';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'csr_approval', 'Complete Sales Return Approval', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      null, 10, 'Approval', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'rm_approval_notes', 'Manager Check & Approval Remarks', 'textarea', null,
      null, false, null, null, null,
      null, 20, 'Approval', false
    );

    -- Build frozen snapshot jsonb
    select jsonb_build_object(
      'form_code', 'S1_CSR_APPROVAL',
      'name', 'Complete Sales Return Approval',
      'step_code', 'S1_CSR_APPROVAL',
      'version_no', 1,
      'version_notes', 'Initial v1 seed',
      'fields', coalesce(jsonb_agg(
        to_jsonb(fld) || jsonb_build_object(
          'option_items', coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'code', oi.code,
                'label', oi.label,
                'allowed_status', oi.allowed_status,
                'rule_text', oi.rule_text,
                'next_action_text', oi.next_action_text,
                'remarks', oi.remarks,
                'system_behavior', oi.system_behavior,
                'sort_order', oi.sort_order,
                'is_active', oi.is_active
              ) order by oi.sort_order asc, oi.code asc
            )
            from public.option_items oi
            where oi.option_set_id = fld.option_set_id
          ), '[]'::jsonb)
        ) order by fld.sort_order asc, fld.field_key asc
      ), '[]'::jsonb)
    ) into v_snapshot
    from public.form_fields fld
    where fld.form_version_id = v_ver_id;

    -- Publish draft version 1
    update public.form_versions
    set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
    where id = v_ver_id;
  end if;

  -- Form S1_INSPECT_DMT
  insert into public.form_definitions (code, step_code, name, is_active)
  values ('S1_INSPECT_DMT', 'S1_INSPECT', 'DMT Visual Inspection & Grading', true)
  on conflict (code) do update set step_code = excluded.step_code, name = excluded.name
  returning id into v_def_id;

  -- If no published version exists for S1_INSPECT_DMT, create draft v1, populate fields, and publish
  if not exists (select 1 from public.form_versions where form_definition_id = v_def_id and status = 'PUBLISHED') then
    -- Insert draft version
    insert into public.form_versions (form_definition_id, version_no, status)
    values (v_def_id, 1, 'DRAFT')
    returning id into v_ver_id;

    select id into v_opt_set_id from public.option_sets where code = 'DMT_CONDITION';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'visual_condition', 'DMT Visual Condition', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      null, 10, 'Grading', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'discrepancy_count', 'Discrepancy Short Count', 'number', null,
      null, false, '{"field": "visual_condition", "op": "eq", "value": "DMT_SHORT_QTY"}'::jsonb, '{"field": "visual_condition", "op": "eq", "value": "DMT_SHORT_QTY"}'::jsonb, '{"min": 1}'::jsonb,
      null, 20, 'Grading', false
    );
    select id into v_opt_set_id from public.option_sets where code = 'DMT_EXTRACTION_TYPE';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'extraction_type', 'DMT Extraction Type', 'radio', v_opt_set_id,
      null, true, null, null, null,
      null, 30, 'Extraction Reconciliation', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'packaging_extracted_qty', 'Packaging Extracted Quantity', 'number', null,
      null, true, null, null, '{"min": 0}'::jsonb,
      '0'::jsonb, 40, 'Extraction Reconciliation', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'container_extracted_qty', 'Container Extracted Quantity', 'number', null,
      null, true, null, null, '{"min": 0}'::jsonb,
      '0'::jsonb, 50, 'Extraction Reconciliation', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'allocated_qty', 'Total Allocated Quantity', 'number', null,
      null, true, null, null, '{"min": 1, "cross_field_sums": {"sum_equals": {"fields": ["packaging_extracted_qty", "container_extracted_qty"], "target": "allocated_qty"}}}'::jsonb,
      null, 60, 'Extraction Reconciliation', true
    );

    -- Build frozen snapshot jsonb
    select jsonb_build_object(
      'form_code', 'S1_INSPECT_DMT',
      'name', 'DMT Visual Inspection & Grading',
      'step_code', 'S1_INSPECT',
      'version_no', 1,
      'version_notes', 'Initial v1 seed',
      'fields', coalesce(jsonb_agg(
        to_jsonb(fld) || jsonb_build_object(
          'option_items', coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'code', oi.code,
                'label', oi.label,
                'allowed_status', oi.allowed_status,
                'rule_text', oi.rule_text,
                'next_action_text', oi.next_action_text,
                'remarks', oi.remarks,
                'system_behavior', oi.system_behavior,
                'sort_order', oi.sort_order,
                'is_active', oi.is_active
              ) order by oi.sort_order asc, oi.code asc
            )
            from public.option_items oi
            where oi.option_set_id = fld.option_set_id
          ), '[]'::jsonb)
        ) order by fld.sort_order asc, fld.field_key asc
      ), '[]'::jsonb)
    ) into v_snapshot
    from public.form_fields fld
    where fld.form_version_id = v_ver_id;

    -- Publish draft version 1
    update public.form_versions
    set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
    where id = v_ver_id;
  end if;

  -- Form S1_INSPECT_PRISMATIC
  insert into public.form_definitions (code, step_code, name, is_active)
  values ('S1_INSPECT_PRISMATIC', 'S1_INSPECT', 'Prismatic Inspection & Grading', true)
  on conflict (code) do update set step_code = excluded.step_code, name = excluded.name
  returning id into v_def_id;

  -- If no published version exists for S1_INSPECT_PRISMATIC, create draft v1, populate fields, and publish
  if not exists (select 1 from public.form_versions where form_definition_id = v_def_id and status = 'PUBLISHED') then
    -- Insert draft version
    insert into public.form_versions (form_definition_id, version_no, status)
    values (v_def_id, 1, 'DRAFT')
    returning id into v_ver_id;

    select id into v_opt_set_id from public.option_sets where code = 'PRISMATIC_CONDITION';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'visual_condition', 'Prismatic Visual Condition', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      null, 10, 'Grading', true
    );
    select id into v_opt_set_id from public.option_sets where code = 'PRISMATIC_EXTRACTION_TYPE';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'extraction_type', 'Prismatic Extraction Type', 'radio', v_opt_set_id,
      null, true, null, null, null,
      null, 20, 'Extraction Reconciliation', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'packaging_extracted_qty', 'Packaging Extracted Quantity', 'number', null,
      null, true, null, null, '{"min": 0}'::jsonb,
      '0'::jsonb, 30, 'Extraction Reconciliation', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'container_extracted_qty', 'Container Extracted Quantity', 'number', null,
      null, true, null, null, '{"min": 0}'::jsonb,
      '0'::jsonb, 40, 'Extraction Reconciliation', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'allocated_qty', 'Total Allocated Quantity', 'number', null,
      null, true, null, null, '{"min": 1, "cross_field_sums": {"sum_equals": {"fields": ["packaging_extracted_qty", "container_extracted_qty"], "target": "allocated_qty"}}}'::jsonb,
      null, 50, 'Extraction Reconciliation', true
    );

    -- Build frozen snapshot jsonb
    select jsonb_build_object(
      'form_code', 'S1_INSPECT_PRISMATIC',
      'name', 'Prismatic Inspection & Grading',
      'step_code', 'S1_INSPECT',
      'version_no', 1,
      'version_notes', 'Initial v1 seed',
      'fields', coalesce(jsonb_agg(
        to_jsonb(fld) || jsonb_build_object(
          'option_items', coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'code', oi.code,
                'label', oi.label,
                'allowed_status', oi.allowed_status,
                'rule_text', oi.rule_text,
                'next_action_text', oi.next_action_text,
                'remarks', oi.remarks,
                'system_behavior', oi.system_behavior,
                'sort_order', oi.sort_order,
                'is_active', oi.is_active
              ) order by oi.sort_order asc, oi.code asc
            )
            from public.option_items oi
            where oi.option_set_id = fld.option_set_id
          ), '[]'::jsonb)
        ) order by fld.sort_order asc, fld.field_key asc
      ), '[]'::jsonb)
    ) into v_snapshot
    from public.form_fields fld
    where fld.form_version_id = v_ver_id;

    -- Publish draft version 1
    update public.form_versions
    set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
    where id = v_ver_id;
  end if;

  -- Form S1_INSPECT_EO
  insert into public.form_definitions (code, step_code, name, is_active)
  values ('S1_INSPECT_EO', 'S1_INSPECT', 'Enclosed Oval Inspection & Grading', true)
  on conflict (code) do update set step_code = excluded.step_code, name = excluded.name
  returning id into v_def_id;

  -- If no published version exists for S1_INSPECT_EO, create draft v1, populate fields, and publish
  if not exists (select 1 from public.form_versions where form_definition_id = v_def_id and status = 'PUBLISHED') then
    -- Insert draft version
    insert into public.form_versions (form_definition_id, version_no, status)
    values (v_def_id, 1, 'DRAFT')
    returning id into v_ver_id;

    select id into v_opt_set_id from public.option_sets where code = 'EO_INSPECTION_PROTOCOL';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'inspection_protocol', 'Inspection Protocol', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      null, 10, 'Protocol', true
    );
    select id into v_opt_set_id from public.option_sets where code = 'EO_CONDITION';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'visual_condition', 'Enclosed Oval Visual Condition', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      null, 20, 'Grading', true
    );
    select id into v_opt_set_id from public.option_sets where code = 'EO_EXTRACTION_TYPE';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'extraction_type', 'Enclosed Oval Extraction Type', 'radio', v_opt_set_id,
      null, true, null, null, null,
      null, 30, 'Extraction Reconciliation', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'packaging_extracted_qty', 'Packaging Extracted Quantity', 'number', null,
      null, true, null, null, '{"min": 0}'::jsonb,
      '0'::jsonb, 40, 'Extraction Reconciliation', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'container_extracted_qty', 'Container Extracted Quantity', 'number', null,
      null, true, null, null, '{"min": 0}'::jsonb,
      '0'::jsonb, 50, 'Extraction Reconciliation', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'allocated_qty', 'Total Allocated Quantity', 'number', null,
      null, true, null, null, '{"min": 1, "cross_field_sums": {"sum_equals": {"fields": ["packaging_extracted_qty", "container_extracted_qty"], "target": "allocated_qty"}}}'::jsonb,
      null, 60, 'Extraction Reconciliation', true
    );

    -- Build frozen snapshot jsonb
    select jsonb_build_object(
      'form_code', 'S1_INSPECT_EO',
      'name', 'Enclosed Oval Inspection & Grading',
      'step_code', 'S1_INSPECT',
      'version_no', 1,
      'version_notes', 'Initial v1 seed',
      'fields', coalesce(jsonb_agg(
        to_jsonb(fld) || jsonb_build_object(
          'option_items', coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'code', oi.code,
                'label', oi.label,
                'allowed_status', oi.allowed_status,
                'rule_text', oi.rule_text,
                'next_action_text', oi.next_action_text,
                'remarks', oi.remarks,
                'system_behavior', oi.system_behavior,
                'sort_order', oi.sort_order,
                'is_active', oi.is_active
              ) order by oi.sort_order asc, oi.code asc
            )
            from public.option_items oi
            where oi.option_set_id = fld.option_set_id
          ), '[]'::jsonb)
        ) order by fld.sort_order asc, fld.field_key asc
      ), '[]'::jsonb)
    ) into v_snapshot
    from public.form_fields fld
    where fld.form_version_id = v_ver_id;

    -- Publish draft version 1
    update public.form_versions
    set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
    where id = v_ver_id;
  end if;

  -- Form S1_DAILY_CONTAINER_AUDIT
  insert into public.form_definitions (code, step_code, name, is_active)
  values ('S1_DAILY_CONTAINER_AUDIT', 'S1_INSPECT', 'Daily Container Audit', true)
  on conflict (code) do update set step_code = excluded.step_code, name = excluded.name
  returning id into v_def_id;

  -- If no published version exists for S1_DAILY_CONTAINER_AUDIT, create draft v1, populate fields, and publish
  if not exists (select 1 from public.form_versions where form_definition_id = v_def_id and status = 'PUBLISHED') then
    -- Insert draft version
    insert into public.form_versions (form_definition_id, version_no, status)
    values (v_def_id, 1, 'DRAFT')
    returning id into v_ver_id;

    select id into v_opt_set_id from public.option_sets where code = 'DAILY_CONTAINER_AUDIT';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'audit_check', 'Containers Checked & Counted Daily', 'checkbox', v_opt_set_id,
      null, true, null, null, null,
      null, 10, 'Audit Verification', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'container_count', 'Total DMT Containers Counted', 'number', null,
      null, true, null, null, '{"min": 0}'::jsonb,
      null, 20, 'Audit Verification', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'sellable_packaging_separated', 'Sellable packaging separated', 'checkbox', null,
      null, true, null, null, null,
      null, 30, 'Audit Verification', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'audit_notes', 'Audit Notes & Observations', 'textarea', null,
      null, false, null, null, null,
      null, 40, 'Audit Verification', false
    );

    -- Build frozen snapshot jsonb
    select jsonb_build_object(
      'form_code', 'S1_DAILY_CONTAINER_AUDIT',
      'name', 'Daily Container Audit',
      'step_code', 'S1_INSPECT',
      'version_no', 1,
      'version_notes', 'Initial v1 seed',
      'fields', coalesce(jsonb_agg(
        to_jsonb(fld) || jsonb_build_object(
          'option_items', coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'code', oi.code,
                'label', oi.label,
                'allowed_status', oi.allowed_status,
                'rule_text', oi.rule_text,
                'next_action_text', oi.next_action_text,
                'remarks', oi.remarks,
                'system_behavior', oi.system_behavior,
                'sort_order', oi.sort_order,
                'is_active', oi.is_active
              ) order by oi.sort_order asc, oi.code asc
            )
            from public.option_items oi
            where oi.option_set_id = fld.option_set_id
          ), '[]'::jsonb)
        ) order by fld.sort_order asc, fld.field_key asc
      ), '[]'::jsonb)
    ) into v_snapshot
    from public.form_fields fld
    where fld.form_version_id = v_ver_id;

    -- Publish draft version 1
    update public.form_versions
    set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
    where id = v_ver_id;
  end if;

  -- Form S1A_RM_ACTION
  insert into public.form_definitions (code, step_code, name, is_active)
  values ('S1A_RM_ACTION', 'S1A_RM_ACTION', 'RM Item-wise Actions', true)
  on conflict (code) do update set step_code = excluded.step_code, name = excluded.name
  returning id into v_def_id;

  -- If no published version exists for S1A_RM_ACTION, create draft v1, populate fields, and publish
  if not exists (select 1 from public.form_versions where form_definition_id = v_def_id and status = 'PUBLISHED') then
    -- Insert draft version
    insert into public.form_versions (form_definition_id, version_no, status)
    values (v_def_id, 1, 'DRAFT')
    returning id into v_ver_id;

    select id into v_opt_set_id from public.option_sets where code = 'RM_ITEM_ACTION';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'rm_action', 'Item-wise RM action', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      null, 10, 'RM Decision', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'rm_action_remarks', 'Replacement Slip Remarks', 'textarea', null,
      null, false, null, null, null,
      null, 20, 'RM Decision', false
    );

    -- Build frozen snapshot jsonb
    select jsonb_build_object(
      'form_code', 'S1A_RM_ACTION',
      'name', 'RM Item-wise Actions',
      'step_code', 'S1A_RM_ACTION',
      'version_no', 1,
      'version_notes', 'Initial v1 seed',
      'fields', coalesce(jsonb_agg(
        to_jsonb(fld) || jsonb_build_object(
          'option_items', coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'code', oi.code,
                'label', oi.label,
                'allowed_status', oi.allowed_status,
                'rule_text', oi.rule_text,
                'next_action_text', oi.next_action_text,
                'remarks', oi.remarks,
                'system_behavior', oi.system_behavior,
                'sort_order', oi.sort_order,
                'is_active', oi.is_active
              ) order by oi.sort_order asc, oi.code asc
            )
            from public.option_items oi
            where oi.option_set_id = fld.option_set_id
          ), '[]'::jsonb)
        ) order by fld.sort_order asc, fld.field_key asc
      ), '[]'::jsonb)
    ) into v_snapshot
    from public.form_fields fld
    where fld.form_version_id = v_ver_id;

    -- Publish draft version 1
    update public.form_versions
    set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
    where id = v_ver_id;
  end if;

  -- Form S2_HANDOVER_INITIATE
  insert into public.form_definitions (code, step_code, name, is_active)
  values ('S2_HANDOVER_INITIATE', 'S2_HANDOVER', 'Custody Handover Initiation', true)
  on conflict (code) do update set step_code = excluded.step_code, name = excluded.name
  returning id into v_def_id;

  -- If no published version exists for S2_HANDOVER_INITIATE, create draft v1, populate fields, and publish
  if not exists (select 1 from public.form_versions where form_definition_id = v_def_id and status = 'PUBLISHED') then
    -- Insert draft version
    insert into public.form_versions (form_definition_id, version_no, status)
    values (v_def_id, 1, 'DRAFT')
    returning id into v_ver_id;

    select id into v_opt_set_id from public.option_sets where code = 'CUSTODY_TRANSFER_MODE';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'transfer_mode', 'Custody Transfer Mode', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      '"PHYSICAL_AND_DIGITAL"'::jsonb, 10, 'Handover Details', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'transfer_qty', 'Dispatched Transfer Quantity', 'number', null,
      null, true, null, null, '{"min": 1}'::jsonb,
      null, 20, 'Handover Details', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'dispatch_notes', 'Handover Dispatch Notes', 'textarea', null,
      null, false, null, null, null,
      null, 30, 'Handover Details', false
    );

    -- Build frozen snapshot jsonb
    select jsonb_build_object(
      'form_code', 'S2_HANDOVER_INITIATE',
      'name', 'Custody Handover Initiation',
      'step_code', 'S2_HANDOVER',
      'version_no', 1,
      'version_notes', 'Initial v1 seed',
      'fields', coalesce(jsonb_agg(
        to_jsonb(fld) || jsonb_build_object(
          'option_items', coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'code', oi.code,
                'label', oi.label,
                'allowed_status', oi.allowed_status,
                'rule_text', oi.rule_text,
                'next_action_text', oi.next_action_text,
                'remarks', oi.remarks,
                'system_behavior', oi.system_behavior,
                'sort_order', oi.sort_order,
                'is_active', oi.is_active
              ) order by oi.sort_order asc, oi.code asc
            )
            from public.option_items oi
            where oi.option_set_id = fld.option_set_id
          ), '[]'::jsonb)
        ) order by fld.sort_order asc, fld.field_key asc
      ), '[]'::jsonb)
    ) into v_snapshot
    from public.form_fields fld
    where fld.form_version_id = v_ver_id;

    -- Publish draft version 1
    update public.form_versions
    set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
    where id = v_ver_id;
  end if;

  -- Form S2_HANDOVER_ACCEPT
  insert into public.form_definitions (code, step_code, name, is_active)
  values ('S2_HANDOVER_ACCEPT', 'S2_HANDOVER', 'Custody Handover Acceptance', true)
  on conflict (code) do update set step_code = excluded.step_code, name = excluded.name
  returning id into v_def_id;

  -- If no published version exists for S2_HANDOVER_ACCEPT, create draft v1, populate fields, and publish
  if not exists (select 1 from public.form_versions where form_definition_id = v_def_id and status = 'PUBLISHED') then
    -- Insert draft version
    insert into public.form_versions (form_definition_id, version_no, status)
    values (v_def_id, 1, 'DRAFT')
    returning id into v_ver_id;

    select id into v_opt_set_id from public.option_sets where code = 'TRANSFER_ACCEPTANCE';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'acceptance_status', 'Transfer Acceptance Status', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      null, 10, 'Acceptance Check', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'discrepancy_reason', 'Discrepancy Explanation & Details', 'textarea', null,
      null, false, '{"field": "acceptance_status", "op": "eq", "value": "DISCREPANCY"}'::jsonb, '{"field": "acceptance_status", "op": "eq", "value": "DISCREPANCY"}'::jsonb, null,
      null, 20, 'Acceptance Check', false
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'accepted_qty', 'Physical Count Accepted Quantity', 'number', null,
      null, true, null, null, '{"min": 0}'::jsonb,
      null, 30, 'Acceptance Check', true
    );

    -- Build frozen snapshot jsonb
    select jsonb_build_object(
      'form_code', 'S2_HANDOVER_ACCEPT',
      'name', 'Custody Handover Acceptance',
      'step_code', 'S2_HANDOVER',
      'version_no', 1,
      'version_notes', 'Initial v1 seed',
      'fields', coalesce(jsonb_agg(
        to_jsonb(fld) || jsonb_build_object(
          'option_items', coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'code', oi.code,
                'label', oi.label,
                'allowed_status', oi.allowed_status,
                'rule_text', oi.rule_text,
                'next_action_text', oi.next_action_text,
                'remarks', oi.remarks,
                'system_behavior', oi.system_behavior,
                'sort_order', oi.sort_order,
                'is_active', oi.is_active
              ) order by oi.sort_order asc, oi.code asc
            )
            from public.option_items oi
            where oi.option_set_id = fld.option_set_id
          ), '[]'::jsonb)
        ) order by fld.sort_order asc, fld.field_key asc
      ), '[]'::jsonb)
    ) into v_snapshot
    from public.form_fields fld
    where fld.form_version_id = v_ver_id;

    -- Publish draft version 1
    update public.form_versions
    set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
    where id = v_ver_id;
  end if;

  -- Form S3_TECH_ALLOT
  insert into public.form_definitions (code, step_code, name, is_active)
  values ('S3_TECH_ALLOT', 'S3_TECHNICAL', 'Technician Servicing Allotment', true)
  on conflict (code) do update set step_code = excluded.step_code, name = excluded.name
  returning id into v_def_id;

  -- If no published version exists for S3_TECH_ALLOT, create draft v1, populate fields, and publish
  if not exists (select 1 from public.form_versions where form_definition_id = v_def_id and status = 'PUBLISHED') then
    -- Insert draft version
    insert into public.form_versions (form_definition_id, version_no, status)
    values (v_def_id, 1, 'DRAFT')
    returning id into v_ver_id;

    select id into v_opt_set_id from public.option_sets where code = 'ASSIGNED_TECHNICIAN';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'assigned_technician', 'Assigned Technician', 'dropdown', v_opt_set_id,
      'technicians', true, null, null, null,
      null, 10, 'Allotment', true
    );
    select id into v_opt_set_id from public.option_sets where code = 'DATA_ENTRY_BY';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'data_entry_by', 'Data Entry Performed By', 'dropdown', v_opt_set_id,
      'profiles:TECHNICIAN_COORDINATOR', true, null, null, null,
      null, 20, 'Allotment', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'allotted_qty', 'Pieces Allotted for Servicing', 'number', null,
      null, true, null, null, '{"min": 1}'::jsonb,
      null, 30, 'Allotment', true
    );

    -- Build frozen snapshot jsonb
    select jsonb_build_object(
      'form_code', 'S3_TECH_ALLOT',
      'name', 'Technician Servicing Allotment',
      'step_code', 'S3_TECHNICAL',
      'version_no', 1,
      'version_notes', 'Initial v1 seed',
      'fields', coalesce(jsonb_agg(
        to_jsonb(fld) || jsonb_build_object(
          'option_items', coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'code', oi.code,
                'label', oi.label,
                'allowed_status', oi.allowed_status,
                'rule_text', oi.rule_text,
                'next_action_text', oi.next_action_text,
                'remarks', oi.remarks,
                'system_behavior', oi.system_behavior,
                'sort_order', oi.sort_order,
                'is_active', oi.is_active
              ) order by oi.sort_order asc, oi.code asc
            )
            from public.option_items oi
            where oi.option_set_id = fld.option_set_id
          ), '[]'::jsonb)
        ) order by fld.sort_order asc, fld.field_key asc
      ), '[]'::jsonb)
    ) into v_snapshot
    from public.form_fields fld
    where fld.form_version_id = v_ver_id;

    -- Publish draft version 1
    update public.form_versions
    set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
    where id = v_ver_id;
  end if;

  -- Form S3_TECH_RECEIVE
  insert into public.form_definitions (code, step_code, name, is_active)
  values ('S3_TECH_RECEIVE', 'S3_TECHNICAL', 'Technician Servicing Receiving', true)
  on conflict (code) do update set step_code = excluded.step_code, name = excluded.name
  returning id into v_def_id;

  -- If no published version exists for S3_TECH_RECEIVE, create draft v1, populate fields, and publish
  if not exists (select 1 from public.form_versions where form_definition_id = v_def_id and status = 'PUBLISHED') then
    -- Insert draft version
    insert into public.form_versions (form_definition_id, version_no, status)
    values (v_def_id, 1, 'DRAFT')
    returning id into v_ver_id;

    select id into v_opt_set_id from public.option_sets where code = 'BATTERY_CHECK';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'battery_check', 'Battery Check Result', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      null, 10, 'Battery Servicing', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'pieces_checked', 'Pieces Checked', 'number', null,
      null, false, '{"field": "battery_check", "op": "in", "value": ["BATTERY_OK", "BATTERY_REPLACED"]}'::jsonb, '{"field": "battery_check", "op": "in", "value": ["BATTERY_OK", "BATTERY_REPLACED"]}'::jsonb, '{"min": 1}'::jsonb,
      null, 20, 'Battery Servicing', false
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'batteries_installed', 'Batteries Installed', 'number', null,
      null, false, '{"field": "battery_check", "op": "eq", "value": "BATTERY_REPLACED"}'::jsonb, '{"field": "battery_check", "op": "eq", "value": "BATTERY_REPLACED"}'::jsonb, '{"min": 1}'::jsonb,
      null, 30, 'Battery Servicing', false
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'battery_type', 'Battery Type / Model', 'text', null,
      null, false, '{"field": "battery_check", "op": "eq", "value": "BATTERY_REPLACED"}'::jsonb, '{"field": "battery_check", "op": "eq", "value": "BATTERY_REPLACED"}'::jsonb, null,
      null, 40, 'Battery Servicing', false
    );
    select id into v_opt_set_id from public.option_sets where code = 'CLEANING_TREATMENT';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'cleaning_treatment', 'Cleaning & Scratch Treatment', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      null, 50, 'Finishing & Grading', true
    );
    select id into v_opt_set_id from public.option_sets where code = 'POST_SERVICING_CLASSIFICATION';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'post_servicing_classification', 'Post-Servicing Classification', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      null, 60, 'Finishing & Grading', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'technician_remarks', 'Technician Observations / Servicing Remarks', 'textarea', null,
      null, false, null, null, null,
      null, 70, 'Finishing & Grading', false
    );

    -- Build frozen snapshot jsonb
    select jsonb_build_object(
      'form_code', 'S3_TECH_RECEIVE',
      'name', 'Technician Servicing Receiving',
      'step_code', 'S3_TECHNICAL',
      'version_no', 1,
      'version_notes', 'Initial v1 seed',
      'fields', coalesce(jsonb_agg(
        to_jsonb(fld) || jsonb_build_object(
          'option_items', coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'code', oi.code,
                'label', oi.label,
                'allowed_status', oi.allowed_status,
                'rule_text', oi.rule_text,
                'next_action_text', oi.next_action_text,
                'remarks', oi.remarks,
                'system_behavior', oi.system_behavior,
                'sort_order', oi.sort_order,
                'is_active', oi.is_active
              ) order by oi.sort_order asc, oi.code asc
            )
            from public.option_items oi
            where oi.option_set_id = fld.option_set_id
          ), '[]'::jsonb)
        ) order by fld.sort_order asc, fld.field_key asc
      ), '[]'::jsonb)
    ) into v_snapshot
    from public.form_fields fld
    where fld.form_version_id = v_ver_id;

    -- Publish draft version 1
    update public.form_versions
    set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
    where id = v_ver_id;
  end if;

  -- Form S4_DISMANTLE
  insert into public.form_definitions (code, step_code, name, is_active)
  values ('S4_DISMANTLE', 'S4_DISMANTLE', 'Dismantling & Parts Recovery', true)
  on conflict (code) do update set step_code = excluded.step_code, name = excluded.name
  returning id into v_def_id;

  -- If no published version exists for S4_DISMANTLE, create draft v1, populate fields, and publish
  if not exists (select 1 from public.form_versions where form_definition_id = v_def_id and status = 'PUBLISHED') then
    -- Insert draft version
    insert into public.form_versions (form_definition_id, version_no, status)
    values (v_def_id, 1, 'DRAFT')
    returning id into v_ver_id;

    select id into v_opt_set_id from public.option_sets where code = 'RECOVERABLE_PART_TYPE';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'part_type', 'Recoverable Part Type', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      null, 10, 'Part Classification', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'model_name', 'PCB Model Name', 'text', null,
      null, false, '{"field": "part_type", "op": "eq", "value": "PCB"}'::jsonb, '{"field": "part_type", "op": "eq", "value": "PCB"}'::jsonb, null,
      null, 20, 'Part Classification', false
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'supplier_name', 'PCB Supplier Name', 'text', null,
      null, false, '{"field": "part_type", "op": "eq", "value": "PCB"}'::jsonb, '{"field": "part_type", "op": "eq", "value": "PCB"}'::jsonb, null,
      null, 30, 'Part Classification', false
    );
    select id into v_opt_set_id from public.option_sets where code = 'PARTS_STORAGE_SEPARATION';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'parts_storage_separation', 'Parts Storage Separation', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      null, 40, 'Storage Allocation', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'container_barcode', 'Dedicated Container Barcode / Shelf', 'text', null,
      null, false, '{"field": "parts_storage_separation", "op": "eq", "value": "DEDICATED_CONTAINERS"}'::jsonb, '{"field": "parts_storage_separation", "op": "eq", "value": "DEDICATED_CONTAINERS"}'::jsonb, null,
      null, 50, 'Storage Allocation', false
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'partition_id', 'Container Compartment / Partition ID', 'text', null,
      null, false, '{"field": "parts_storage_separation", "op": "eq", "value": "PARTITIONED_CONTAINER"}'::jsonb, '{"field": "parts_storage_separation", "op": "eq", "value": "PARTITIONED_CONTAINER"}'::jsonb, null,
      null, 60, 'Storage Allocation', false
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'scrap_disposal_marked', 'Remaining scrap marked for safe disposal', 'checkbox', null,
      null, true, null, null, null,
      null, 70, 'Scrap Handling', true
    );

    -- Build frozen snapshot jsonb
    select jsonb_build_object(
      'form_code', 'S4_DISMANTLE',
      'name', 'Dismantling & Parts Recovery',
      'step_code', 'S4_DISMANTLE',
      'version_no', 1,
      'version_notes', 'Initial v1 seed',
      'fields', coalesce(jsonb_agg(
        to_jsonb(fld) || jsonb_build_object(
          'option_items', coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'code', oi.code,
                'label', oi.label,
                'allowed_status', oi.allowed_status,
                'rule_text', oi.rule_text,
                'next_action_text', oi.next_action_text,
                'remarks', oi.remarks,
                'system_behavior', oi.system_behavior,
                'sort_order', oi.sort_order,
                'is_active', oi.is_active
              ) order by oi.sort_order asc, oi.code asc
            )
            from public.option_items oi
            where oi.option_set_id = fld.option_set_id
          ), '[]'::jsonb)
        ) order by fld.sort_order asc, fld.field_key asc
      ), '[]'::jsonb)
    ) into v_snapshot
    from public.form_fields fld
    where fld.form_version_id = v_ver_id;

    -- Publish draft version 1
    update public.form_versions
    set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
    where id = v_ver_id;
  end if;

  -- Form S5_SEGREGATE
  insert into public.form_definitions (code, step_code, name, is_active)
  values ('S5_SEGREGATE', 'S5_SEGREGATE', 'Inventory Custody Segregation', true)
  on conflict (code) do update set step_code = excluded.step_code, name = excluded.name
  returning id into v_def_id;

  -- If no published version exists for S5_SEGREGATE, create draft v1, populate fields, and publish
  if not exists (select 1 from public.form_versions where form_definition_id = v_def_id and status = 'PUBLISHED') then
    -- Insert draft version
    insert into public.form_versions (form_definition_id, version_no, status)
    values (v_def_id, 1, 'DRAFT')
    returning id into v_ver_id;

    select id into v_opt_set_id from public.option_sets where code = 'CUSTODY_ASSIGNMENT';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'custody_assignment', 'Inventory Custody Assignment', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      null, 10, 'Custody Routing', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'storage_location_id', 'Assigned Storage Location ID', 'text', null,
      null, true, null, null, null,
      null, 20, 'Custody Routing', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'segregation_notes', 'Segregation & Storage Remarks', 'textarea', null,
      null, false, null, null, null,
      null, 30, 'Custody Routing', false
    );

    -- Build frozen snapshot jsonb
    select jsonb_build_object(
      'form_code', 'S5_SEGREGATE',
      'name', 'Inventory Custody Segregation',
      'step_code', 'S5_SEGREGATE',
      'version_no', 1,
      'version_notes', 'Initial v1 seed',
      'fields', coalesce(jsonb_agg(
        to_jsonb(fld) || jsonb_build_object(
          'option_items', coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'code', oi.code,
                'label', oi.label,
                'allowed_status', oi.allowed_status,
                'rule_text', oi.rule_text,
                'next_action_text', oi.next_action_text,
                'remarks', oi.remarks,
                'system_behavior', oi.system_behavior,
                'sort_order', oi.sort_order,
                'is_active', oi.is_active
              ) order by oi.sort_order asc, oi.code asc
            )
            from public.option_items oi
            where oi.option_set_id = fld.option_set_id
          ), '[]'::jsonb)
        ) order by fld.sort_order asc, fld.field_key asc
      ), '[]'::jsonb)
    ) into v_snapshot
    from public.form_fields fld
    where fld.form_version_id = v_ver_id;

    -- Publish draft version 1
    update public.form_versions
    set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
    where id = v_ver_id;
  end if;

  -- Form S6_STORE_ISSUE
  insert into public.form_definitions (code, step_code, name, is_active)
  values ('S6_STORE_ISSUE', 'S6_STORE_ISSUE', 'Main Store Issue', true)
  on conflict (code) do update set step_code = excluded.step_code, name = excluded.name
  returning id into v_def_id;

  -- If no published version exists for S6_STORE_ISSUE, create draft v1, populate fields, and publish
  if not exists (select 1 from public.form_versions where form_definition_id = v_def_id and status = 'PUBLISHED') then
    -- Insert draft version
    insert into public.form_versions (form_definition_id, version_no, status)
    values (v_def_id, 1, 'DRAFT')
    returning id into v_ver_id;

    select id into v_opt_set_id from public.option_sets where code = 'STORE_ISSUE_TYPE';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'store_issue_type', 'Store Issue Type', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      '"ISSUE_MAIN_STORE"'::jsonb, 10, 'Issue Details', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'issue_qty', 'Main Store Inward Issue Quantity', 'number', null,
      null, true, null, null, '{"min": 1}'::jsonb,
      null, 20, 'Issue Details', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'main_store_inward_ref', 'Main Store Inward Voucher Ref', 'text', null,
      null, true, null, null, null,
      null, 30, 'Issue Details', true
    );

    -- Build frozen snapshot jsonb
    select jsonb_build_object(
      'form_code', 'S6_STORE_ISSUE',
      'name', 'Main Store Issue',
      'step_code', 'S6_STORE_ISSUE',
      'version_no', 1,
      'version_notes', 'Initial v1 seed',
      'fields', coalesce(jsonb_agg(
        to_jsonb(fld) || jsonb_build_object(
          'option_items', coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'code', oi.code,
                'label', oi.label,
                'allowed_status', oi.allowed_status,
                'rule_text', oi.rule_text,
                'next_action_text', oi.next_action_text,
                'remarks', oi.remarks,
                'system_behavior', oi.system_behavior,
                'sort_order', oi.sort_order,
                'is_active', oi.is_active
              ) order by oi.sort_order asc, oi.code asc
            )
            from public.option_items oi
            where oi.option_set_id = fld.option_set_id
          ), '[]'::jsonb)
        ) order by fld.sort_order asc, fld.field_key asc
      ), '[]'::jsonb)
    ) into v_snapshot
    from public.form_fields fld
    where fld.form_version_id = v_ver_id;

    -- Publish draft version 1
    update public.form_versions
    set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
    where id = v_ver_id;
  end if;

  -- Form S6_CN_DECISION
  insert into public.form_definitions (code, step_code, name, is_active)
  values ('S6_CN_DECISION', 'S6_CN_DECISION', 'Replacement Manager CN Decision', true)
  on conflict (code) do update set step_code = excluded.step_code, name = excluded.name
  returning id into v_def_id;

  -- If no published version exists for S6_CN_DECISION, create draft v1, populate fields, and publish
  if not exists (select 1 from public.form_versions where form_definition_id = v_def_id and status = 'PUBLISHED') then
    -- Insert draft version
    insert into public.form_versions (form_definition_id, version_no, status)
    values (v_def_id, 1, 'DRAFT')
    returning id into v_ver_id;

    select id into v_opt_set_id from public.option_sets where code = 'RM_CN_DECISION';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'rm_cn_decision', 'Replacement Manager CN Decision', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      null, 10, 'Decision', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'cn_decision_remarks', 'Decision Justification & Remarks', 'textarea', null,
      null, false, null, null, null,
      null, 20, 'Decision', false
    );

    -- Build frozen snapshot jsonb
    select jsonb_build_object(
      'form_code', 'S6_CN_DECISION',
      'name', 'Replacement Manager CN Decision',
      'step_code', 'S6_CN_DECISION',
      'version_no', 1,
      'version_notes', 'Initial v1 seed',
      'fields', coalesce(jsonb_agg(
        to_jsonb(fld) || jsonb_build_object(
          'option_items', coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'code', oi.code,
                'label', oi.label,
                'allowed_status', oi.allowed_status,
                'rule_text', oi.rule_text,
                'next_action_text', oi.next_action_text,
                'remarks', oi.remarks,
                'system_behavior', oi.system_behavior,
                'sort_order', oi.sort_order,
                'is_active', oi.is_active
              ) order by oi.sort_order asc, oi.code asc
            )
            from public.option_items oi
            where oi.option_set_id = fld.option_set_id
          ), '[]'::jsonb)
        ) order by fld.sort_order asc, fld.field_key asc
      ), '[]'::jsonb)
    ) into v_snapshot
    from public.form_fields fld
    where fld.form_version_id = v_ver_id;

    -- Publish draft version 1
    update public.form_versions
    set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
    where id = v_ver_id;
  end if;

  -- Form S6_ACCOUNTS_CN
  insert into public.form_definitions (code, step_code, name, is_active)
  values ('S6_ACCOUNTS_CN', 'S6_ACCOUNTS_CN', 'Accounts Credit Note Verification', true)
  on conflict (code) do update set step_code = excluded.step_code, name = excluded.name
  returning id into v_def_id;

  -- If no published version exists for S6_ACCOUNTS_CN, create draft v1, populate fields, and publish
  if not exists (select 1 from public.form_versions where form_definition_id = v_def_id and status = 'PUBLISHED') then
    -- Insert draft version
    insert into public.form_versions (form_definition_id, version_no, status)
    values (v_def_id, 1, 'DRAFT')
    returning id into v_ver_id;

    select id into v_opt_set_id from public.option_sets where code = 'PARTY_DOC_VERIFICATION';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'party_doc_verification', 'Party Document Verification', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      null, 10, 'Verification', true
    );
    select id into v_opt_set_id from public.option_sets where code = 'GST_PORTAL_VERIFICATION';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'gst_portal_verification', 'GST Portal Return Verification', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      null, 20, 'Verification', true
    );
    select id into v_opt_set_id from public.option_sets where code = 'CN_TYPE';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'cn_type', 'Credit Note Type', 'dropdown', v_opt_set_id,
      null, true, null, null, '{"restricted_when": {"condition": {"field": "gst_portal_verification", "op": "eq", "value": "GST_NOT_REFLECTED"}, "allowed_values": ["GENERAL_CN"]}}'::jsonb,
      null, 30, 'Voucher Generation', true
    );
    select id into v_opt_set_id from public.option_sets where code = 'RATE_VERIFICATION_REF';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'rate_verification_ref', 'Rate Verification Reference', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      null, 40, 'Valuation', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'verified_rate', 'Verified Commercial Rate', 'number', null,
      null, true, null, null, '{"min": 0}'::jsonb,
      null, 50, 'Valuation', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'cn_number', 'Credit Note Voucher Number', 'text', null,
      null, true, null, null, null,
      null, 60, 'Voucher Details', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'cn_date', 'Credit Note Voucher Date', 'date', null,
      null, true, null, null, '{"date_not_in_future": true}'::jsonb,
      null, 70, 'Voucher Details', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'cn_valuation', 'Total Credit Note Valuation', 'number', null,
      null, true, null, null, '{"min": 0}'::jsonb,
      null, 80, 'Voucher Details', true
    );

    -- Build frozen snapshot jsonb
    select jsonb_build_object(
      'form_code', 'S6_ACCOUNTS_CN',
      'name', 'Accounts Credit Note Verification',
      'step_code', 'S6_ACCOUNTS_CN',
      'version_no', 1,
      'version_notes', 'Initial v1 seed',
      'fields', coalesce(jsonb_agg(
        to_jsonb(fld) || jsonb_build_object(
          'option_items', coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'code', oi.code,
                'label', oi.label,
                'allowed_status', oi.allowed_status,
                'rule_text', oi.rule_text,
                'next_action_text', oi.next_action_text,
                'remarks', oi.remarks,
                'system_behavior', oi.system_behavior,
                'sort_order', oi.sort_order,
                'is_active', oi.is_active
              ) order by oi.sort_order asc, oi.code asc
            )
            from public.option_items oi
            where oi.option_set_id = fld.option_set_id
          ), '[]'::jsonb)
        ) order by fld.sort_order asc, fld.field_key asc
      ), '[]'::jsonb)
    ) into v_snapshot
    from public.form_fields fld
    where fld.form_version_id = v_ver_id;

    -- Publish draft version 1
    update public.form_versions
    set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
    where id = v_ver_id;
  end if;

  -- Form S6_PARTY_NOTIFY
  insert into public.form_definitions (code, step_code, name, is_active)
  values ('S6_PARTY_NOTIFY', 'S6_NOTIFY', 'Party Notification Prior to Closure', true)
  on conflict (code) do update set step_code = excluded.step_code, name = excluded.name
  returning id into v_def_id;

  -- If no published version exists for S6_PARTY_NOTIFY, create draft v1, populate fields, and publish
  if not exists (select 1 from public.form_versions where form_definition_id = v_def_id and status = 'PUBLISHED') then
    -- Insert draft version
    insert into public.form_versions (form_definition_id, version_no, status)
    values (v_def_id, 1, 'DRAFT')
    returning id into v_ver_id;

    select id into v_opt_set_id from public.option_sets where code = 'PARTY_NOTIFICATION_STATUS';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'party_notification_status', 'Party Notification Status', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      '"PRIOR_INFO_SENT"'::jsonb, 10, 'Notification', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'notification_sent_date', 'Notification Sent Date', 'date', null,
      null, true, null, null, '{"date_not_in_future": true}'::jsonb,
      null, 20, 'Notification', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'notification_mode', 'Notification Mode (Email / WhatsApp / Letter)', 'text', null,
      null, true, null, null, null,
      null, 30, 'Notification', true
    );

    -- Build frozen snapshot jsonb
    select jsonb_build_object(
      'form_code', 'S6_PARTY_NOTIFY',
      'name', 'Party Notification Prior to Closure',
      'step_code', 'S6_NOTIFY',
      'version_no', 1,
      'version_notes', 'Initial v1 seed',
      'fields', coalesce(jsonb_agg(
        to_jsonb(fld) || jsonb_build_object(
          'option_items', coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'code', oi.code,
                'label', oi.label,
                'allowed_status', oi.allowed_status,
                'rule_text', oi.rule_text,
                'next_action_text', oi.next_action_text,
                'remarks', oi.remarks,
                'system_behavior', oi.system_behavior,
                'sort_order', oi.sort_order,
                'is_active', oi.is_active
              ) order by oi.sort_order asc, oi.code asc
            )
            from public.option_items oi
            where oi.option_set_id = fld.option_set_id
          ), '[]'::jsonb)
        ) order by fld.sort_order asc, fld.field_key asc
      ), '[]'::jsonb)
    ) into v_snapshot
    from public.form_fields fld
    where fld.form_version_id = v_ver_id;

    -- Publish draft version 1
    update public.form_versions
    set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
    where id = v_ver_id;
  end if;

  -- Form S6_CSR_CLOSE
  insert into public.form_definitions (code, step_code, name, is_active)
  values ('S6_CSR_CLOSE', 'S6_CLOSE', 'Complete Sales Return Closure', true)
  on conflict (code) do update set step_code = excluded.step_code, name = excluded.name
  returning id into v_def_id;

  -- If no published version exists for S6_CSR_CLOSE, create draft v1, populate fields, and publish
  if not exists (select 1 from public.form_versions where form_definition_id = v_def_id and status = 'PUBLISHED') then
    -- Insert draft version
    insert into public.form_versions (form_definition_id, version_no, status)
    values (v_def_id, 1, 'DRAFT')
    returning id into v_ver_id;

    select id into v_opt_set_id from public.option_sets where code = 'CSR_FINAL_STATUS';
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'csr_final_status', 'Complete Sales Return Final Status', 'dropdown', v_opt_set_id,
      null, true, null, null, null,
      '"CSR_CLOSED"'::jsonb, 10, 'Closure Checklist', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'closure_checklist_confirmed', 'Goods in stock + CN issued + party notified', 'checkbox', null,
      null, true, null, null, null,
      null, 20, 'Closure Checklist', true
    );
    insert into public.form_fields (
      form_version_id, field_key, label, control_type, option_set_id,
      master_ref_type, is_required, visible_when, required_when, validation,
      default_value, sort_order, section, is_core
    ) values (
      v_ver_id, 'closure_remarks', 'Closure Notes / Final Remarks', 'textarea', null,
      null, false, null, null, null,
      null, 30, 'Closure Checklist', false
    );

    -- Build frozen snapshot jsonb
    select jsonb_build_object(
      'form_code', 'S6_CSR_CLOSE',
      'name', 'Complete Sales Return Closure',
      'step_code', 'S6_CLOSE',
      'version_no', 1,
      'version_notes', 'Initial v1 seed',
      'fields', coalesce(jsonb_agg(
        to_jsonb(fld) || jsonb_build_object(
          'option_items', coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'code', oi.code,
                'label', oi.label,
                'allowed_status', oi.allowed_status,
                'rule_text', oi.rule_text,
                'next_action_text', oi.next_action_text,
                'remarks', oi.remarks,
                'system_behavior', oi.system_behavior,
                'sort_order', oi.sort_order,
                'is_active', oi.is_active
              ) order by oi.sort_order asc, oi.code asc
            )
            from public.option_items oi
            where oi.option_set_id = fld.option_set_id
          ), '[]'::jsonb)
        ) order by fld.sort_order asc, fld.field_key asc
      ), '[]'::jsonb)
    ) into v_snapshot
    from public.form_fields fld
    where fld.form_version_id = v_ver_id;

    -- Publish draft version 1
    update public.form_versions
    set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
    where id = v_ver_id;
  end if;

end $$;

-- -----------------------------------------------------------------------------
-- S1_GATE_INWARD v2 — change request 2026-11-12, Phase 2 (AMD-01 … AMD-04, DEC-38, DEC-39).
-- Return Type first; Gate Entry Date / Number (Offline only) above State and Station; Carton No.
-- replaces Box Count; the single "Accompanying Document" dropdown is replaced by document rows
-- (sent as `documents`, stored in gs_gate_documents) plus the "No Document Attached" flag.
-- v1 is RETIRED (G-18: GS created under v1 keep their pinned version). Idempotent: runs only
-- while the published version has no carton_count field.
-- -----------------------------------------------------------------------------
do $$
declare
  v_def_id   uuid;
  v_pub      record;
  v_ver_id   uuid;
  v_snapshot jsonb;
  v_rt       uuid := (select id from public.option_sets where code = 'RETURN_TYPE');
  v_dm       uuid := (select id from public.option_sets where code = 'DELIVERY_MODE');
  v_fmt      uuid := (select id from public.option_sets where code = 'GS_CREATION_FORMAT');
  v_offline  jsonb := '{"field": "return_type", "op": "eq", "value": "OFFLINE_RETURN"}'::jsonb;
  v_nodoc    jsonb := '{"field": "no_document", "op": "eq", "value": true}'::jsonb;
begin
  select id into v_def_id from public.form_definitions where code = 'S1_GATE_INWARD';
  select v.id, v.version_no, v.snapshot into v_pub
    from public.form_versions v where v.form_definition_id = v_def_id and v.status = 'PUBLISHED';
  if v_pub.id is null
     or jsonb_path_exists(v_pub.snapshot, '$.fields[*] ? (@.field_key == "carton_count")') then
    return;
  end if;

  insert into public.form_versions (form_definition_id, version_no, status)
  values (v_def_id, (select max(version_no) + 1 from public.form_versions where form_definition_id = v_def_id), 'DRAFT')
  returning id into v_ver_id;

  insert into public.form_fields (form_version_id, field_key, label, control_type, option_set_id,
                                  is_required, visible_when, required_when, validation, default_value,
                                  sort_order, section, help_text, is_core)
  values
    (v_ver_id, 'return_type', 'Return Type', 'radio', v_rt, true, null, null, null, null, 5, 'Return Type', null, true),
    (v_ver_id, 'gate_entry_date', 'Gate Entry Date', 'date', null, false, v_offline, v_offline,
     '{"date_not_in_future": true}'::jsonb, null, 6, 'Gate Entry', 'Back-dating is allowed; never later than today', false),
    (v_ver_id, 'gate_entry_no', 'Gate Entry Number', 'number', null, false, v_offline, v_offline,
     '{"min": 1}'::jsonb, null, 7, 'Gate Entry', null, false),
    (v_ver_id, 'state', 'State', 'text', null, true, null, null, null, null, 10, 'Consignment Header', null, true),
    (v_ver_id, 'station', 'Station', 'text', null, true, null, null, null, null, 20, 'Consignment Header', null, true),
    (v_ver_id, 'party_name', 'Distributor / Party', 'text', null, true, null, null, null, null, 30, 'Consignment Header', null, true),
    (v_ver_id, 'carton_count', 'Carton No.', 'number', null, true, null, null, '{"min": 1}'::jsonb, null, 40, 'Consignment Header', 'Number of cartons received', true),
    (v_ver_id, 'delivery_mode', 'Delivery Mode / Transporter', 'dropdown', v_dm, true, null, null, null, null, 50, 'Delivery Details', null, true),
    (v_ver_id, 'courier_name', 'Courier Name', 'text', null, false,
     '{"field": "delivery_mode", "op": "eq", "value": "COURIER_PARCEL"}'::jsonb, '{"field": "delivery_mode", "op": "eq", "value": "COURIER_PARCEL"}'::jsonb, null, null, 60, 'Delivery Details', null, false),
    (v_ver_id, 'docket_no', 'Docket Number', 'text', null, false,
     '{"field": "delivery_mode", "op": "eq", "value": "COURIER_PARCEL"}'::jsonb, '{"field": "delivery_mode", "op": "eq", "value": "COURIER_PARCEL"}'::jsonb, null, null, 70, 'Delivery Details', null, false),
    (v_ver_id, 'vehicle_no', 'Vehicle Number', 'text', null, false,
     '{"field": "delivery_mode", "op": "eq", "value": "DIRECT_TRUCK"}'::jsonb, '{"field": "delivery_mode", "op": "eq", "value": "DIRECT_TRUCK"}'::jsonb, null, null, 80, 'Delivery Details', null, false),
    (v_ver_id, 'transporter_name', 'Transporter Name', 'text', null, false,
     '{"field": "delivery_mode", "op": "eq", "value": "DIRECT_TRUCK"}'::jsonb, '{"field": "delivery_mode", "op": "eq", "value": "DIRECT_TRUCK"}'::jsonb, null, null, 90, 'Delivery Details', null, false),
    (v_ver_id, 'rep_name', 'Representative Name', 'text', null, false,
     '{"field": "delivery_mode", "op": "eq", "value": "SELF_PARTY_REP"}'::jsonb, '{"field": "delivery_mode", "op": "eq", "value": "SELF_PARTY_REP"}'::jsonb, null, null, 100, 'Delivery Details', null, false),
    (v_ver_id, 'rep_contact', 'Representative Contact No.', 'text', null, false,
     '{"field": "delivery_mode", "op": "eq", "value": "SELF_PARTY_REP"}'::jsonb, '{"field": "delivery_mode", "op": "eq", "value": "SELF_PARTY_REP"}'::jsonb, null, null, 110, 'Delivery Details', null, false),
    (v_ver_id, 'no_document', 'No Document Attached', 'checkbox', null, false, null, null, null, 'false'::jsonb, 120, 'Documentation',
     'Tick only when the consignment came without any document (BR-03)', true),
    (v_ver_id, 'missing_doc_warning_acknowledged', 'Missing documentation warning acknowledged', 'checkbox', null, false,
     v_nodoc, v_nodoc, null, null, 160, 'Documentation', null, false),
    (v_ver_id, 'gs_creation_format', 'GS Creation Format', 'dropdown', v_fmt, true, null, null, null, '"AUTO_STANDARD"'::jsonb, 170, 'System Generation', null, true);

  select jsonb_build_object(
    'form_code', 'S1_GATE_INWARD',
    'name', 'Gate Inward & GS Creation',
    'step_code', 'S1_GATE',
    'version_no', (select version_no from public.form_versions where id = v_ver_id),
    'version_notes', 'AMD-01..AMD-04: return type, gate entry date/number, carton no., document rows',
    'fields', coalesce(jsonb_agg(
      to_jsonb(fld) || jsonb_build_object(
        'option_items', coalesce((
          select jsonb_agg(jsonb_build_object(
                   'code', oi.code, 'label', oi.label, 'allowed_status', oi.allowed_status,
                   'rule_text', oi.rule_text, 'next_action_text', oi.next_action_text,
                   'remarks', oi.remarks, 'system_behavior', oi.system_behavior,
                   'sort_order', oi.sort_order, 'is_active', oi.is_active)
                 order by oi.sort_order asc, oi.code asc)
            from public.option_items oi where oi.option_set_id = fld.option_set_id
        ), '[]'::jsonb)
      ) order by fld.sort_order asc, fld.field_key asc
    ), '[]'::jsonb)
  ) into v_snapshot
  from public.form_fields fld
  where fld.form_version_id = v_ver_id;

  update public.form_versions set status = 'RETIRED' where id = v_pub.id;
  update public.form_versions
     set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
   where id = v_ver_id;
end $$;

-- -----------------------------------------------------------------------------
-- S1_GATE_INWARD v3 — DEC-52 (user request 2026-11-17): "No Document Attached" alone is enough at
-- the gate; the "Missing documentation warning acknowledged" checkbox is dropped. Copies every
-- other field of the published version unchanged. Idempotent: runs only while the published v2+
-- version (carton_count) still has the acknowledgement field. Also shipped for production as
-- supabase/snippets/release_20261117_gate_no_doc_ack.sql.
-- -----------------------------------------------------------------------------
do $$
declare
  v_def_id   uuid;
  v_pub      record;
  v_ver_id   uuid;
  v_snapshot jsonb;
begin
  select id into v_def_id from public.form_definitions where code = 'S1_GATE_INWARD';
  select v.id, v.version_no, v.snapshot into v_pub
    from public.form_versions v where v.form_definition_id = v_def_id and v.status = 'PUBLISHED';
  if v_pub.id is null
     or not jsonb_path_exists(v_pub.snapshot, '$.fields[*] ? (@.field_key == "carton_count")')
     or not jsonb_path_exists(v_pub.snapshot, '$.fields[*] ? (@.field_key == "missing_doc_warning_acknowledged")') then
    return;
  end if;

  insert into public.form_versions (form_definition_id, version_no, status)
  values (v_def_id, (select max(version_no) + 1 from public.form_versions where form_definition_id = v_def_id), 'DRAFT')
  returning id into v_ver_id;

  insert into public.form_fields (form_version_id, field_key, label, control_type, option_set_id,
                                  master_ref_type, is_required, visible_when, required_when, validation,
                                  default_value, sort_order, section, help_text, is_core, is_system_locked)
  select v_ver_id, f.field_key, f.label, f.control_type, f.option_set_id,
         f.master_ref_type, f.is_required, f.visible_when, f.required_when, f.validation,
         f.default_value, f.sort_order, f.section, f.help_text, f.is_core, f.is_system_locked
    from public.form_fields f
   where f.form_version_id = v_pub.id
     and f.field_key <> 'missing_doc_warning_acknowledged';

  select jsonb_build_object(
    'form_code', 'S1_GATE_INWARD',
    'name', coalesce(v_pub.snapshot ->> 'name', 'Gate Inward & GS Creation'),
    'step_code', coalesce(v_pub.snapshot ->> 'step_code', 'S1_GATE'),
    'version_no', (select version_no from public.form_versions where id = v_ver_id),
    'version_notes', 'DEC-52: no separate missing-documentation acknowledgement at the gate',
    'fields', coalesce(jsonb_agg(
      to_jsonb(fld) || jsonb_build_object(
        'option_items', coalesce((
          select jsonb_agg(jsonb_build_object(
                   'code', oi.code, 'label', oi.label, 'allowed_status', oi.allowed_status,
                   'rule_text', oi.rule_text, 'next_action_text', oi.next_action_text,
                   'remarks', oi.remarks, 'system_behavior', oi.system_behavior,
                   'sort_order', oi.sort_order, 'is_active', oi.is_active)
                 order by oi.sort_order asc, oi.code asc)
            from public.option_items oi where oi.option_set_id = fld.option_set_id
        ), '[]'::jsonb)
      ) order by fld.sort_order asc, fld.field_key asc
    ), '[]'::jsonb)
  ) into v_snapshot
  from public.form_fields fld
  where fld.form_version_id = v_ver_id;

  update public.form_versions set status = 'RETIRED' where id = v_pub.id;
  update public.form_versions
     set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
   where id = v_ver_id;
end $$;



-- =============================================================================
-- Print Templates v1 (master plan §8.3, prompt P1-08)
-- Seed v1 published templates: REPLACEMENT_SLIP, GS_TAG, TRANSFER_NOTE, STORE_ISSUE, CN_SUMMARY.
-- =============================================================================
do $$
declare
  v_tpl_rec record;
  v_tpl_id uuid;
  v_layout jsonb;
begin
  for v_tpl_rec in (
    select * from (values
      ('REPLACEMENT_SLIP', 'Replacement Slip', 'A4', jsonb_build_object(
        'paper_size', 'A4',
        'orientation', 'portrait',
        'show_logo', true,
        'header_title', 'HICKS THERMOMETERS (INDIA) LIMITED',
        'header_subtitle', 'Goods Return Replacement Slip (WF r6)',
        'footer_text', 'This is a computer generated document. Physical goods must match this slip before dispatch.',
        'sections', jsonb_build_array(
          jsonb_build_object('id', 'consignment', 'title', 'Consignment Details', 'fields', jsonb_build_array('gs_no', 'party_name', 'date', 'box_count', 'delivery_mode')),
          jsonb_build_object('id', 'items', 'title', 'Item-Wise Planned Actions', 'fields', jsonb_build_array('line_no', 'product_name', 'received_qty', 'action_code', 'remarks')),
          jsonb_build_object('id', 'signatures', 'title', 'Signatures', 'fields', jsonb_build_array('prepared_by', 'replacement_manager_sign'))
        ),
        'signature_blocks', jsonb_build_array(
          jsonb_build_object('label', 'Prepared By', 'role', 'Unboxing Verifier'),
          jsonb_build_object('label', 'Replacement Manager', 'role', 'Replacement Manager')
        )
      )),
      ('GS_TAG', 'Inward Goods Slip Tag', 'LABEL', jsonb_build_object(
        'paper_size', 'LABEL',
        'orientation', 'landscape',
        'show_logo', false,
        'header_title', 'RMS INWARD TAG',
        'header_subtitle', 'Gate Inward Consignment Identification (BR-02)',
        'footer_text', 'Scan QR for GS details',
        'sections', jsonb_build_array(
          jsonb_build_object('id', 'barcode', 'title', 'GS Identification', 'fields', jsonb_build_array('gs_no', 'qr_code')),
          jsonb_build_object('id', 'header', 'title', 'Inward Header', 'fields', jsonb_build_array('party_name', 'state_station', 'carton_count', 'received_date', 'transporter'))
        ),
        'signature_blocks', '[]'::jsonb
      )),
      ('TRANSFER_NOTE', 'Custody Transfer Note', 'A5', jsonb_build_object(
        'paper_size', 'A5',
        'orientation', 'landscape',
        'show_logo', true,
        'header_title', 'CUSTODY TRANSFER NOTE',
        'header_subtitle', 'Intermediate Store Custody Handover (Step-4)',
        'footer_text', 'Both physical count and digital verification required before acceptance.',
        'sections', jsonb_build_array(
          jsonb_build_object('id', 'transfer_meta', 'title', 'Transfer Info', 'fields', jsonb_build_array('transfer_no', 'date', 'from_location', 'to_location', 'mode')),
          jsonb_build_array(jsonb_build_object('id', 'lines', 'title', 'Allocated Lots', 'fields', jsonb_build_array('lot_id', 'product_name', 'condition', 'qty_sent', 'qty_counted'))),
          jsonb_build_object('id', 'reconciliation', 'title', 'Discrepancy / Remarks', 'fields', jsonb_build_array('status', 'discrepancy_notes'))
        ),
        'signature_blocks', jsonb_build_array(
          jsonb_build_object('label', 'Initiated By (Aman)', 'role', 'Inward Verifier'),
          jsonb_build_object('label', 'Accepted By (Sahil)', 'role', 'Intermediate Store Manager')
        )
      )),
      ('STORE_ISSUE', 'Store Issue Note', 'A4', jsonb_build_object(
        'paper_size', 'A4',
        'orientation', 'portrait',
        'show_logo', true,
        'header_title', 'STORE ISSUE NOTE',
        'header_subtitle', 'Main Store Issue & Inward Transfer (WF r11)',
        'footer_text', 'Main Store receipt acknowledged in RMS.',
        'sections', jsonb_build_array(
          jsonb_build_object('id', 'issue_info', 'title', 'Issue Information', 'fields', jsonb_build_array('issue_no', 'date', 'from_store', 'to_store', 'issued_by')),
          jsonb_build_object('id', 'lots', 'title', 'Issued Stock', 'fields', jsonb_build_array('line_no', 'product_name', 'lot_code', 'condition_class', 'quantity')),
          jsonb_build_object('id', 'receipt', 'title', 'Main Store Receipt', 'fields', jsonb_build_array('acknowledged_by', 'acknowledged_at', 'notes'))
        ),
        'signature_blocks', jsonb_build_array(
          jsonb_build_object('label', 'Issued By', 'role', 'Intermediate Store Manager'),
          jsonb_build_object('label', 'Received By', 'role', 'Main Store Manager')
        )
      )),
      ('CN_SUMMARY', 'Credit Note Summary', 'A4', jsonb_build_object(
        'paper_size', 'A4',
        'orientation', 'portrait',
        'show_logo', true,
        'header_title', 'CREDIT NOTE SUMMARY & CLEARANCE',
        'header_subtitle', 'Accounts Commercial Resolution (Step-7, Deepak Ji)',
        'footer_text', 'Accounts verification completed per Master Plan §4.2 (G-13, G-14).',
        'sections', jsonb_build_array(
          jsonb_build_object('id', 'gs_ref', 'title', 'Consignment & Party', 'fields', jsonb_build_array('gs_no', 'party_name', 'party_gstin', 'party_doc_no', 'party_doc_date')),
          jsonb_build_object('id', 'gst_verification', 'title', 'GST Portal & Rate Baseline', 'fields', jsonb_build_array('gst_portal_status', 'return_period', 'verified_rate', 'rate_ref_doc')),
          jsonb_build_object('id', 'cn_details', 'title', 'Credit Note Voucher', 'fields', jsonb_build_array('cn_type', 'cn_no', 'cn_date', 'jv_no', 'taxable_value', 'tax_breakup', 'total_amount')),
          jsonb_build_object('id', 'notification', 'title', 'Party Notification Status', 'fields', jsonb_build_array('prior_info_sent', 'notification_date', 'channel'))
        ),
        'signature_blocks', jsonb_build_array(
          jsonb_build_object('label', 'Verified By', 'role', 'Accounts Executive'),
          jsonb_build_object('label', 'Approved By', 'role', 'Replacement Manager')
        )
      ))
    ) as t(code, name, paper_size, layout)
  ) loop
    if not exists (select 1 from public.print_templates pt where pt.code = v_tpl_rec.code and pt.status = 'PUBLISHED') then
      insert into public.print_templates (code, name, version_no, status, layout)
      values (v_tpl_rec.code, v_tpl_rec.name, 1, 'DRAFT', v_tpl_rec.layout)
      returning id into v_tpl_id;

      update public.print_templates
      set status = 'PUBLISHED', snapshot = v_tpl_rec.layout, published_at = now()
      where id = v_tpl_id;
    end if;
  end loop;
end $$;

-- =============================================================================
-- Workflow RMS_STANDARD v1 (master plan §2, §4.2, §6.5, §8.3, prompt P1-08)
-- Published v1 workflow definition with stages, steps, assignments, transitions.
-- =============================================================================
do $$
declare
  v_wf_def_id uuid;
  v_wf_ver_id uuid;
  v_snapshot jsonb;
  v_s1 uuid;
  v_s1a uuid;
  v_s2 uuid;
  v_s3 uuid;
  v_s4 uuid;
  v_s5 uuid;
  v_s6 uuid;

  v_st_gate uuid;
  v_st_unbox uuid;
  v_st_itemize uuid;
  v_st_csr_appr uuid;
  v_st_inspect uuid;
  v_st_rm_act uuid;
  v_st_handover uuid;
  v_st_tech uuid;
  v_st_dismantle uuid;
  v_st_segregate uuid;
  v_st_issue uuid;
  v_st_cn_dec uuid;
  v_st_acct_cn uuid;
  v_st_notify uuid;
  v_st_close uuid;

  v_role_gate uuid;
  v_role_inward uuid;
  v_role_rm uuid;
  v_role_store_mgr uuid;
  v_role_tech_coord uuid;
  v_role_tech uuid;
  v_role_sp_tech uuid;
  v_role_sp_mgr uuid;
  v_role_accounts uuid;
begin
  -- 1. Create or get workflow definition
  insert into public.workflow_definitions (code, name, is_active)
  values ('RMS_STANDARD', 'RMS Standard Return Workflow', true)
  on conflict (code) do update set name = excluded.name
  returning id into v_wf_def_id;

  -- 2. Check if published version 1 exists
  if not exists (
    select 1 from public.workflow_versions
    where workflow_definition_id = v_wf_def_id and version_no = 1
  ) then
    -- Create draft version 1
    insert into public.workflow_versions (workflow_definition_id, version_no, status)
    values (v_wf_def_id, 1, 'DRAFT')
    returning id into v_wf_ver_id;

    -- Look up role IDs
    select id into v_role_gate from public.roles where code = 'GATE_INWARD';
    select id into v_role_inward from public.roles where code = 'INWARD_VERIFIER';
    select id into v_role_rm from public.roles where code = 'REPLACEMENT_MANAGER';
    select id into v_role_store_mgr from public.roles where code = 'INTERMEDIATE_STORE_MANAGER';
    select id into v_role_tech_coord from public.roles where code = 'TECHNICIAN_COORDINATOR';
    select id into v_role_tech from public.roles where code = 'TECHNICIAN';
    select id into v_role_sp_tech from public.roles where code = 'SPARE_PARTS_TECHNICIAN';
    select id into v_role_sp_mgr from public.roles where code = 'SPARE_PARTS_MANAGER';
    select id into v_role_accounts from public.roles where code = 'ACCOUNTS';

    -- 3. Insert stages (Stage-1 to Stage-6 + Stage-1 a)
    insert into public.workflow_stages (workflow_version_id, code, label, sort_order)
    values (v_wf_ver_id, 'STAGE_1', 'Stage 1 – Inward & Initial Processing', 1) returning id into v_s1;

    insert into public.workflow_stages (workflow_version_id, code, label, sort_order)
    values (v_wf_ver_id, 'STAGE_1A', 'Stage 1 a) – Replacement Manager Actions', 2) returning id into v_s1a;

    insert into public.workflow_stages (workflow_version_id, code, label, sort_order)
    values (v_wf_ver_id, 'STAGE_2', 'Stage 2 – Intermediate Store', 3) returning id into v_s2;

    insert into public.workflow_stages (workflow_version_id, code, label, sort_order)
    values (v_wf_ver_id, 'STAGE_3', 'Stage 3 – Technical Servicing', 4) returning id into v_s3;

    insert into public.workflow_stages (workflow_version_id, code, label, sort_order)
    values (v_wf_ver_id, 'STAGE_4', 'Stage 4 – Dismantling & Parts Recovery', 5) returning id into v_s4;

    insert into public.workflow_stages (workflow_version_id, code, label, sort_order)
    values (v_wf_ver_id, 'STAGE_5', 'Stage 5 – Custody Segregation', 6) returning id into v_s5;

    insert into public.workflow_stages (workflow_version_id, code, label, sort_order)
    values (v_wf_ver_id, 'STAGE_6', 'Stage 6 – Store Issue & Commercial Resolution', 7) returning id into v_s6;

    -- 4. Insert steps linking to seeded form definitions
    insert into public.workflow_steps (
      workflow_version_id, stage_id, code, label, form_definition_id, sla_hours, requires_approval, sort_order, is_active
    ) values (
      v_wf_ver_id, v_s1, 'S1_GATE', 'Step-1 GS creation',
      (select id from public.form_definitions where code = 'S1_GATE_INWARD'), 4.0, false, 1, true
    ) returning id into v_st_gate;

    insert into public.workflow_steps (
      workflow_version_id, stage_id, code, label, form_definition_id, sla_hours, requires_approval, sort_order, is_active
    ) values (
      v_wf_ver_id, v_s1, 'S1_UNBOX', 'Step-2 Unboxing',
      (select id from public.form_definitions where code = 'S1_UNBOXING'), 8.0, false, 2, true
    ) returning id into v_st_unbox;

    insert into public.workflow_steps (
      workflow_version_id, stage_id, code, label, form_definition_id, sla_hours, requires_approval, sort_order, is_active
    ) values (
      v_wf_ver_id, v_s1, 'S1_ITEMIZE', 'Step-3 Itemisation & categorisation',
      (select id from public.form_definitions where code = 'S1_ITEMIZE'), 4.0, false, 3, true
    ) returning id into v_st_itemize;

    insert into public.workflow_steps (
      workflow_version_id, stage_id, code, label, form_definition_id, sla_hours, requires_approval, sort_order, is_active
    ) values (
      v_wf_ver_id, v_s1, 'S1_CSR_APPROVAL', 'Step-3 CSR Approval',
      (select id from public.form_definitions where code = 'S1_CSR_APPROVAL'), 8.0, true, 4, true
    ) returning id into v_st_csr_appr;

    insert into public.workflow_steps (
      workflow_version_id, stage_id, code, label, form_definition_id, sla_hours, requires_approval, sort_order, is_active
    ) values (
      v_wf_ver_id, v_s1, 'S1_INSPECT', 'Step-3 Inspection & Grading',
      (select id from public.form_definitions where code = 'S1_INSPECT_DMT'), 12.0, false, 5, true
    ) returning id into v_st_inspect;

    insert into public.workflow_steps (
      workflow_version_id, stage_id, code, label, form_definition_id, sla_hours, requires_approval, sort_order, is_active
    ) values (
      v_wf_ver_id, v_s1a, 'S1A_RM_ACTION', 'Step-3 a) Actions from Hicks end',
      (select id from public.form_definitions where code = 'S1A_RM_ACTION'), 8.0, false, 6, true
    ) returning id into v_st_rm_act;

    insert into public.workflow_steps (
      workflow_version_id, stage_id, code, label, form_definition_id, sla_hours, requires_approval, sort_order, is_active
    ) values (
      v_wf_ver_id, v_s2, 'S2_HANDOVER', 'Step-4 Handover Aman to Sahil',
      (select id from public.form_definitions where code = 'S2_HANDOVER_INITIATE'), 4.0, false, 7, true
    ) returning id into v_st_handover;

    insert into public.workflow_steps (
      workflow_version_id, stage_id, code, label, form_definition_id, sla_hours, requires_approval, sort_order, is_active
    ) values (
      v_wf_ver_id, v_s3, 'S3_TECHNICAL', 'Step-4 (Technical) Servicing & Battery Check',
      (select id from public.form_definitions where code = 'S3_TECH_ALLOT'), 24.0, false, 8, true
    ) returning id into v_st_tech;

    insert into public.workflow_steps (
      workflow_version_id, stage_id, code, label, form_definition_id, sla_hours, requires_approval, sort_order, is_active
    ) values (
      v_wf_ver_id, v_s4, 'S4_DISMANTLE', 'Step-5 Dismantling & Parts Recovery',
      (select id from public.form_definitions where code = 'S4_DISMANTLE'), 16.0, false, 9, true
    ) returning id into v_st_dismantle;

    insert into public.workflow_steps (
      workflow_version_id, stage_id, code, label, form_definition_id, sla_hours, requires_approval, sort_order, is_active
    ) values (
      v_wf_ver_id, v_s5, 'S5_SEGREGATE', 'Step-6 Custody Segregation & Stock Allocation',
      (select id from public.form_definitions where code = 'S5_SEGREGATE'), 4.0, false, 10, true
    ) returning id into v_st_segregate;

    insert into public.workflow_steps (
      workflow_version_id, stage_id, code, label, form_definition_id, sla_hours, requires_approval, sort_order, is_active
    ) values (
      v_wf_ver_id, v_s6, 'S6_STORE_ISSUE', 'Step-7 Store Issue to Main Store',
      (select id from public.form_definitions where code = 'S6_STORE_ISSUE'), 8.0, false, 11, true
    ) returning id into v_st_issue;

    insert into public.workflow_steps (
      workflow_version_id, stage_id, code, label, form_definition_id, sla_hours, requires_approval, sort_order, is_active
    ) values (
      v_wf_ver_id, v_s6, 'S6_CN_DECISION', 'Step-7 RM CN Decision',
      (select id from public.form_definitions where code = 'S6_CN_DECISION'), 8.0, true, 12, true
    ) returning id into v_st_cn_dec;

    insert into public.workflow_steps (
      workflow_version_id, stage_id, code, label, form_definition_id, sla_hours, requires_approval, sort_order, is_active
    ) values (
      v_wf_ver_id, v_s6, 'S6_ACCOUNTS_CN', 'Step-7 Accounts Document & GST Verification',
      (select id from public.form_definitions where code = 'S6_ACCOUNTS_CN'), 24.0, false, 13, true
    ) returning id into v_st_acct_cn;

    insert into public.workflow_steps (
      workflow_version_id, stage_id, code, label, form_definition_id, sla_hours, requires_approval, sort_order, is_active
    ) values (
      v_wf_ver_id, v_s6, 'S6_NOTIFY', 'Step-7 Prior Party Notification',
      (select id from public.form_definitions where code = 'S6_PARTY_NOTIFY'), 4.0, false, 14, true
    ) returning id into v_st_notify;

    insert into public.workflow_steps (
      workflow_version_id, stage_id, code, label, form_definition_id, sla_hours, requires_approval, sort_order, is_active
    ) values (
      v_wf_ver_id, v_s6, 'S6_CLOSE', 'Step-7 Complete Sales Return / GS Closure',
      (select id from public.form_definitions where code = 'S6_CSR_CLOSE'), 4.0, true, 15, true
    ) returning id into v_st_close;

    -- 5. Step assignments (PERFORM / APPROVE / VIEW per master plan §3.3)
    insert into public.step_assignments (workflow_step_id, role_id, assignment_type) values
      (v_st_gate, v_role_gate, 'PERFORM'),
      (v_st_unbox, v_role_inward, 'PERFORM'),
      (v_st_itemize, v_role_inward, 'PERFORM'),
      (v_st_csr_appr, v_role_rm, 'APPROVE'),
      (v_st_inspect, v_role_inward, 'PERFORM'),
      (v_st_rm_act, v_role_rm, 'PERFORM'),
      (v_st_handover, v_role_inward, 'PERFORM'),
      (v_st_handover, v_role_store_mgr, 'APPROVE'),
      (v_st_tech, v_role_tech_coord, 'PERFORM'),
      (v_st_tech, v_role_tech, 'PERFORM'),
      (v_st_dismantle, v_role_sp_tech, 'PERFORM'),
      (v_st_segregate, v_role_store_mgr, 'PERFORM'),
      (v_st_segregate, v_role_sp_mgr, 'PERFORM'),
      (v_st_issue, v_role_store_mgr, 'PERFORM'),
      (v_st_cn_dec, v_role_rm, 'APPROVE'),
      (v_st_acct_cn, v_role_accounts, 'PERFORM'),
      (v_st_notify, v_role_accounts, 'PERFORM'),
      (v_st_close, v_role_rm, 'APPROVE');

    -- 6. Transitions matching §2.1 flow, §6.5 state machine, with system_guards (G-xx)
    insert into public.workflow_transitions (workflow_version_id, from_step_id, to_step_id, condition, system_guards, priority) values
      -- S1_GATE -> S1_UNBOX
      (v_wf_ver_id, v_st_gate, v_st_unbox, null, array['G-01'], 10),
      -- S1_UNBOX -> S1_ITEMIZE
      (v_wf_ver_id, v_st_unbox, v_st_itemize, null, array['G-02'], 10),
      -- S1_ITEMIZE -> S1_CSR_APPROVAL (CSR)
      (v_wf_ver_id, v_st_itemize, v_st_csr_appr, '{"field": "category_code", "op": "eq", "value": "CSR"}'::jsonb, '{}', 20),
      -- S1_ITEMIZE -> S1_INSPECT (RO)
      (v_wf_ver_id, v_st_itemize, v_st_inspect, '{"field": "category_code", "op": "eq", "value": "RO"}'::jsonb, '{}', 10),
      -- S1_CSR_APPROVAL -> S1_INSPECT (CSR Rejected -> RO)
      (v_wf_ver_id, v_st_csr_appr, v_st_inspect, '{"field": "csr_decision", "op": "eq", "value": "CSR_REJECTED_TO_RO"}'::jsonb, '{}', 10),
      -- S1_CSR_APPROVAL -> S2_HANDOVER (CSR Approved)
      (v_wf_ver_id, v_st_csr_appr, v_st_handover, '{"field": "csr_decision", "op": "eq", "value": "CSR_APPROVED"}'::jsonb, array['G-03'], 20),
      -- S1_INSPECT -> S1A_RM_ACTION
      (v_wf_ver_id, v_st_inspect, v_st_rm_act, null, array['G-06', 'G-07'], 10),
      -- S1A_RM_ACTION -> S2_HANDOVER
      (v_wf_ver_id, v_st_rm_act, v_st_handover, null, array['G-08'], 10),
      -- S2_HANDOVER -> S3_TECHNICAL
      (v_wf_ver_id, v_st_handover, v_st_tech, '{"field": "requires_technical_servicing", "op": "neq", "value": false}'::jsonb, array['G-09'], 10),
      -- S2_HANDOVER -> S6_STORE_ISSUE (direct to store, e.g. CSR or sellable lot)
      (v_wf_ver_id, v_st_handover, v_st_issue, '{"field": "direct_to_store", "op": "eq", "value": true}'::jsonb, array['G-09'], 20),
      -- S3_TECHNICAL -> S4_DISMANTLE (Non-Good)
      (v_wf_ver_id, v_st_tech, v_st_dismantle, '{"field": "classification", "op": "eq", "value": "NON_GOOD"}'::jsonb, array['G-10'], 10),
      -- S3_TECHNICAL -> S5_SEGREGATE (Functional / Non-Sellable)
      (v_wf_ver_id, v_st_tech, v_st_segregate, '{"field": "classification", "op": "neq", "value": "NON_GOOD"}'::jsonb, array['G-10'], 20),
      -- S4_DISMANTLE -> S5_SEGREGATE
      (v_wf_ver_id, v_st_dismantle, v_st_segregate, null, array['G-11'], 10),
      -- S5_SEGREGATE -> S6_STORE_ISSUE
      (v_wf_ver_id, v_st_segregate, v_st_issue, null, array['G-12'], 10),
      -- S6_STORE_ISSUE -> S6_CN_DECISION
      (v_wf_ver_id, v_st_issue, v_st_cn_dec, null, '{}', 10),
      -- S6_CN_DECISION -> S6_ACCOUNTS_CN (Allow CN)
      (v_wf_ver_id, v_st_cn_dec, v_st_acct_cn, '{"field": "cn_decision", "op": "eq", "value": "ALLOW_CN"}'::jsonb, array['G-13'], 20),
      -- S6_CN_DECISION -> S6_CLOSE (Deny CN / Replacement dispatched)
      (v_wf_ver_id, v_st_cn_dec, v_st_close, '{"field": "cn_decision", "op": "eq", "value": "DENY_CN_SEND_REPLACEMENT"}'::jsonb, '{}', 10),
      -- S6_ACCOUNTS_CN -> S6_NOTIFY
      (v_wf_ver_id, v_st_acct_cn, v_st_notify, null, array['G-13', 'G-14'], 10),
      -- S6_NOTIFY -> S6_CLOSE
      (v_wf_ver_id, v_st_notify, v_st_close, null, array['G-15'], 10);

    -- 7. Build frozen snapshot jsonb
    select jsonb_build_object(
      'workflow_code', 'RMS_STANDARD',
      'name', 'RMS Standard Return Workflow',
      'version_no', 1,
      'version_notes', 'Initial v1 seed',
      'stages', (
        select jsonb_agg(
          jsonb_build_object(
            'id', stg.id,
            'code', stg.code,
            'label', stg.label,
            'sort_order', stg.sort_order
          ) order by stg.sort_order asc
        )
        from public.workflow_stages stg
        where stg.workflow_version_id = v_wf_ver_id
      ),
      'steps', (
        select jsonb_agg(
          jsonb_build_object(
            'id', stp.id,
            'code', stp.code,
            'label', stp.label,
            'stage_id', stp.stage_id,
            'stage_code', (select code from public.workflow_stages where id = stp.stage_id),
            'form_definition_id', stp.form_definition_id,
            'form_code', (select code from public.form_definitions where id = stp.form_definition_id),
            'sla_hours', stp.sla_hours,
            'requires_approval', stp.requires_approval,
            'is_active', stp.is_active,
            'sort_order', stp.sort_order,
            'assignments', coalesce((
              select jsonb_agg(
                jsonb_build_object(
                  'assignment_type', sa.assignment_type,
                  'role_id', sa.role_id,
                  'role_code', (select code from public.roles where id = sa.role_id),
                  'user_id', sa.user_id
                ) order by sa.assignment_type asc
              )
              from public.step_assignments sa
              where sa.workflow_step_id = stp.id
            ), '[]'::jsonb)
          ) order by stp.sort_order asc
        )
        from public.workflow_steps stp
        where stp.workflow_version_id = v_wf_ver_id
      ),
      'transitions', (
        select jsonb_agg(
          jsonb_build_object(
            'id', tr.id,
            'from_step_id', tr.from_step_id,
            'from_step_code', (select code from public.workflow_steps where id = tr.from_step_id),
            'to_step_id', tr.to_step_id,
            'to_step_code', (select code from public.workflow_steps where id = tr.to_step_id),
            'condition', tr.condition,
            'system_guards', tr.system_guards,
            'priority', tr.priority
          ) order by tr.priority desc, tr.id asc
        )
        from public.workflow_transitions tr
        where tr.workflow_version_id = v_wf_ver_id
      )
    ) into v_snapshot;

    -- 8. Publish draft version 1
    update public.workflow_versions
    set status = 'PUBLISHED', snapshot = v_snapshot, published_at = now()
    where id = v_wf_ver_id;
  end if;
end $$;

-- =============================================================================
-- Notification rules, settings & escalation rules (master plan §10 "Notifications", prompt P4-03)
-- Defaults reproduce the pre-P4-03 behaviour: every event that already notified keeps one active
-- IN_APP rule addressed to the recipients the publishing service names (context recipients).
-- Events that did not notify before are seeded INACTIVE (admins switch them on in the rules editor).
-- BATTERY_LOW_STOCK is new in P4-03 (item 6) and seeded active (DEC-15 battery store, BR-24).
-- =============================================================================
insert into public.system_settings (key, value, category, description, source_ref) values
  ('battery_low_stock_threshold',      '10', 'notifications', 'Provisional: BATTERY_LOW_STOCK fires when a battery type''s Battery Store balance falls below this many pieces (0 disables).', 'P4-03'),
  ('notification_digest_hour',         '9',  'notifications', 'Local hour (0-23, system timezone) after which the daily email digest is sent to users who chose DAILY_DIGEST.', 'P4-03'),
  ('notification_max_attempts',        '5',  'notifications', 'Delivery attempts (outbox dispatch and each email) before a notification is marked FAILED.', 'P4-03')
on conflict (key) do nothing;

do $$
begin
  if not exists (select 1 from public.notification_rules) then
    insert into public.notification_rules
      (event_type, name, include_context_recipients, include_step_assignees, recipient_role_codes, channels, is_active)
    values
      -- Events that already notified (centralised unchanged)
      ('MISSING_DOCUMENTS',               'Accounts & RM: no gate document (DEC-05)',          true,  false, '{}', array['IN_APP'], true),
      ('EVIDENCE_COMPLETED',              'Accounts: documents received (BR-06, DEC-05)',      true,  false, '{}', array['IN_APP'], true),
      ('CSR_APPROVAL_REQUIRED',           'CSR approvers',                                     true,  false, '{}', array['IN_APP'], true),
      ('CSR_DECIDED',                     'Categoriser: CSR decision',                          true,  false, '{}', array['IN_APP'], true),
      ('HAZARD_DETECTED',                 'Mercury hazard alert (G-05)',                        true,  false, '{}', array['IN_APP'], true),
      ('TRANSFER_INITIATED',              'Receiving custodians',                               true,  false, '{}', array['IN_APP'], true),
      ('TRANSFER_DISCREPANCY',            'Transfer discrepancy parties',                       true,  false, '{}', array['IN_APP'], true),
      ('DISPATCHED',                      'RM: replacement dispatched',                         true,  false, '{}', array['IN_APP'], true),
      ('CN_ISSUED',                       'RM: credit note issued',                             true,  false, '{}', array['IN_APP'], true),
      ('GS_CLOSED',                       'Closure roles (gs_closure_roles)',                   true,  false, '{}', array['IN_APP'], true),
      ('DAILY_AUDIT_MISSED',              'Inward Verifier & RM: audit missed (DEC-08)',        true,  false, '{}', array['IN_APP'], true),
      ('PROVISIONAL_PARTY_CREATED',       'Master-data editors (DEC-02)',                       true,  false, '{}', array['IN_APP'], true),
      ('MISSING_DOC_EXCEPTION_REQUESTED', 'Exception approvers (DEC-03)',                       true,  false, '{}', array['IN_APP'], true),
      ('MISSING_DOC_EXCEPTION_DECIDED',   'Requester: exception decision',                      true,  false, '{}', array['IN_APP'], true),
      ('TRANSFER_PROPOSED',               'Packaging custodian (BR-09)',                        true,  false, '{}', array['IN_APP'], true),
      ('ITEM_CORRECTION_REQUESTED',       'Correction approvers',                               true,  false, '{}', array['IN_APP'], true),
      ('ITEM_CORRECTION_DECIDED',         'Requester: correction decision',                     true,  false, '{}', array['IN_APP'], true),
      ('CONTAINER_AUDIT_REMINDER',        'Inward Verifier & RM: evening reminder (DEC-08)',    true,  false, '{}', array['IN_APP'], true),
      ('CN_DECISION_ALLOWED',             'Accounts: CN allowed',                               true,  false, '{}', array['IN_APP'], true),
      ('TRANSFER_ACCEPTED',               'Initiator: transfer accepted',                       true,  false, '{}', array['IN_APP'], true),
      ('TRANSFER_ADJUSTMENT_APPROVAL',    'Override approvers',                                 true,  false, '{}', array['IN_APP'], true),
      ('TRANSFER_RECONCILIATION_PROPOSED','Transfer parties: reconciliation proposed',          true,  false, '{}', array['IN_APP'], true),
      ('TRANSFER_CANCELLED',              'Transfer parties: cancelled',                        true,  false, '{}', array['IN_APP'], true),
      ('TRANSFER_RECONCILED',             'Transfer parties: reconciled',                       true,  false, '{}', array['IN_APP'], true),
      ('STOCK_ADJUSTMENT_REQUESTED',      'Adjustment approvers',                               true,  false, '{}', array['IN_APP'], true),
      ('STOCK_ADJUSTMENT_DECIDED',        'Requester: adjustment decision',                     true,  false, '{}', array['IN_APP'], true),
      ('SEGREGATION_VIOLATION',           'Super Admins & segregation_alert_roles',             true,  false, '{}', array['IN_APP'], true),
      ('NON_SELLABLE_RECEIVED',           'Spare Parts Managers (DEC-17)',                      true,  false, '{}', array['IN_APP'], true),
      ('SLA_ESCALATION',                  'Escalation targets (DEC-30)',                        true,  false, '{}', array['IN_APP'], true),
      -- New in P4-03, battery threshold (item 6)
      ('BATTERY_LOW_STOCK',               'Battery store: low stock',                           false, false, array['SPARE_PARTS_MANAGER','TECHNICIAN_COORDINATOR'], array['IN_APP'], true),
      -- New in P4-03: no notification before → seeded inactive
      ('GS_CREATED',                      'Next step assignees: new GS',                        false, true,  '{}', array['IN_APP'], false),
      ('REJECTION_RECORDED',              'RM action roles: rejection recorded',                true,  false, '{}', array['IN_APP'], false),
      ('PENDENCY_OPENED',                 'Open step assignees: pendency opened',               false, true,  '{}', array['IN_APP'], false),
      ('PENDENCY_CLEARED',                'Pendency opener: cleared',                           true,  false, '{}', array['IN_APP'], false),
      ('TECH_BATCH_ALLOTTED',             'Technician (login): batch allotted',                 true,  false, '{}', array['IN_APP'], false),
      ('TECH_BATCH_RECEIVED',             'Stock custodians: batch received',                   true,  false, '{}', array['IN_APP'], false),
      ('PARTS_RECOVERED',                 'Spare Parts Managers: parts recovered',              true,  false, '{}', array['IN_APP'], false),
      ('STORE_ISSUED',                    'Main Store: stock issued',                           true,  false, '{}', array['IN_APP'], false),
      ('CN_DECISION_REQUIRED',            'CN decision makers',                                 true,  false, '{}', array['IN_APP'], false),
      ('NOTIFICATION_PENDING',            'Party notification performers',                      true,  false, '{}', array['IN_APP'], false);
  end if;
end $$;

-- RM action revision alert (pre-P4-03 recipients; catalogue entry added by 20261106000400).
insert into public.notification_rules (event_type, name, include_context_recipients, channels, is_active)
select 'RM_ACTION_REVISED', 'Accounts & Intermediate Store: RM actions revised', true, array['IN_APP'], true
 where not exists (select 1 from public.notification_rules where event_type = 'RM_ACTION_REVISED');

-- Accounts fast-track alert for an Invoice / Debit Note at the gate (catalogue entry added by
-- 20261110000100; the rule is here because it names the ACCOUNTS role, which is seed data).
insert into public.notification_rules
  (event_type, name, include_context_recipients, recipient_role_codes, channels, priority, is_active)
select 'GS_DOCUMENT_FOUND', 'Notify Accounts of Invoice or Debit Note at gate', true,
       array['ACCOUNTS'], array['IN_APP'], 'HIGH', true
 where not exists (select 1 from public.notification_rules where event_type = 'GS_DOCUMENT_FOUND');

-- Change plan Phase 7 (AMD-16, AMD-17): Accounts is told when the A/c Actions slip is ready and when
-- a finalised slip is superseded by a revision. Recipients are this rule (admin-editable), not code.
insert into public.notification_rules
  (event_type, name, include_context_recipients, recipient_role_codes, channels, priority, is_active)
select v.event_type, v.name, true, array['ACCOUNTS'], array['IN_APP'], 'HIGH', true
  from (values
    ('AC_ACTIONS_SLIP_READY',      'Accounts: A/c Actions slip ready (AMD-17)'),
    ('AC_ACTIONS_SLIP_SUPERSEDED', 'Accounts: A/c Actions slip superseded (AMD-16)')
  ) as v(event_type, name)
 where not exists (select 1 from public.notification_rules r where r.event_type = v.event_type);

-- Change plan Phase 8 (AMD-18, AMD-19): DISPATCH is told a Dispatch Slip is ready; the RM and
-- Accounts are told when Accounts completed and when the goods are dispatched. Admin-editable rules.
insert into public.notification_rules
  (event_type, name, include_context_recipients, recipient_role_codes, channels, priority, is_active)
select v.event_type, v.name, true, v.roles, array['IN_APP'], v.priority, true
  from (values
    ('DISPATCH_SLIP_READY',      'Dispatch: Dispatch Slip ready (AMD-19)',
     array['DISPATCH'], 'HIGH'),
    ('AC_ENTRY_COMPLETED',       'RM: Accounts entry completed (AMD-18)',
     array['REPLACEMENT_MANAGER'], 'NORMAL'),
    ('DISPATCH_SLIP_DISPATCHED', 'RM & Accounts: goods dispatched (AMD-19)',
     array['REPLACEMENT_MANAGER', 'ACCOUNTS'], 'NORMAL')
  ) as v(event_type, name, roles, priority)
 where not exists (select 1 from public.notification_rules r where r.event_type = v.event_type);

-- -----------------------------------------------------------------------------
-- RMS_STANDARD v2 — change request 2026-11-12, Phase 3 (AMD-08): the Unboxing step is labelled
-- Carton Opening and Step-3 Counting & Categorisation. Codes, assignments, SLAs and transitions are
-- unchanged. Mirrors the admin path (config/workflow create_draft → update_draft_step_label →
-- publish_draft); v1 is RETIRED and GS pinned to it keep it (G-18). Idempotent.
-- -----------------------------------------------------------------------------
do $$
declare
  v_def_id  uuid;
  v_pub     record;
  v_new_id  uuid;
  v_new_no  integer;
  v_snap    jsonb;
  r         record;
  v_stage   jsonb := '{}'::jsonb;   -- old stage id -> new stage id
  v_step    jsonb := '{}'::jsonb;   -- old step id  -> new step id
  v_id      uuid;
begin
  select id into v_def_id from public.workflow_definitions where code = 'RMS_STANDARD';
  select v.id, v.version_no into v_pub
    from public.workflow_versions v where v.workflow_definition_id = v_def_id and v.status = 'PUBLISHED';
  if v_pub.id is null or exists (select 1 from public.workflow_steps
                                  where workflow_version_id = v_pub.id and code = 'S1_UNBOX'
                                    and label = 'Step-2 Carton Opening') then
    return;
  end if;

  v_new_no := (select max(version_no) + 1 from public.workflow_versions where workflow_definition_id = v_def_id);
  insert into public.workflow_versions (workflow_definition_id, version_no, status)
  values (v_def_id, v_new_no, 'DRAFT') returning id into v_new_id;

  for r in select * from public.workflow_stages where workflow_version_id = v_pub.id order by sort_order loop
    insert into public.workflow_stages (workflow_version_id, code, label, sort_order)
    values (v_new_id, r.code, r.label, r.sort_order) returning id into v_id;
    v_stage := v_stage || jsonb_build_object(r.id::text, v_id);
  end loop;

  for r in select * from public.workflow_steps where workflow_version_id = v_pub.id order by sort_order loop
    insert into public.workflow_steps (workflow_version_id, stage_id, code, label, form_definition_id,
                                       sla_hours, requires_approval, sort_order, is_active)
    values (v_new_id, (v_stage ->> r.stage_id::text)::uuid, r.code,
            case r.code when 'S1_UNBOX' then 'Step-2 Carton Opening'
                        when 'S1_ITEMIZE' then 'Step-3 Counting & Categorisation'
                        else r.label end,
            r.form_definition_id, r.sla_hours, r.requires_approval, r.sort_order, r.is_active)
    returning id into v_id;
    v_step := v_step || jsonb_build_object(r.id::text, v_id);
    insert into public.step_assignments (workflow_step_id, role_id, user_id, assignment_type)
    select v_id, sa.role_id, sa.user_id, sa.assignment_type
      from public.step_assignments sa where sa.workflow_step_id = r.id;
  end loop;

  insert into public.workflow_transitions (workflow_version_id, from_step_id, to_step_id, condition, system_guards, priority)
  select v_new_id, (v_step ->> t.from_step_id::text)::uuid, (v_step ->> t.to_step_id::text)::uuid,
         t.condition, t.system_guards, t.priority
    from public.workflow_transitions t where t.workflow_version_id = v_pub.id;

  -- Frozen snapshot, same shape as publish_draft (config/workflow/service.py).
  select jsonb_build_object(
    'workflow_code', 'RMS_STANDARD',
    'name', (select name from public.workflow_definitions where id = v_def_id),
    'version_no', v_new_no,
    'version_notes', 'AMD-08: Carton Opening / Counting & Categorisation step labels',
    'stages', (select coalesce(jsonb_agg(jsonb_build_object('id', s.id, 'code', s.code, 'label', s.label,
                                                            'sort_order', s.sort_order) order by s.sort_order), '[]'::jsonb)
                 from public.workflow_stages s where s.workflow_version_id = v_new_id),
    'steps', (select coalesce(jsonb_agg(jsonb_build_object(
                'id', st.id, 'code', st.code, 'label', st.label, 'stage_id', st.stage_id,
                'stage_code', sg.code, 'form_definition_id', st.form_definition_id, 'form_code', fd.code,
                'sla_hours', st.sla_hours, 'requires_approval', st.requires_approval,
                'sort_order', st.sort_order, 'is_active', st.is_active,
                'assignments', (select coalesce(jsonb_agg(jsonb_build_object(
                                  'assignment_type', sa.assignment_type, 'role_id', sa.role_id,
                                  'role_code', ro.code, 'user_id', sa.user_id)), '[]'::jsonb)
                                  from public.step_assignments sa
                                  left join public.roles ro on ro.id = sa.role_id
                                 where sa.workflow_step_id = st.id)) order by st.sort_order), '[]'::jsonb)
                from public.workflow_steps st
                join public.workflow_stages sg on sg.id = st.stage_id
                left join public.form_definitions fd on fd.id = st.form_definition_id
               where st.workflow_version_id = v_new_id),
    'transitions', (select coalesce(jsonb_agg(jsonb_build_object(
                      'id', t.id, 'from_step_id', t.from_step_id, 'from_step_code', fs.code,
                      'to_step_id', t.to_step_id, 'to_step_code', ts.code, 'condition', t.condition,
                      'system_guards', to_jsonb(coalesce(t.system_guards, array[]::text[])),
                      'priority', t.priority)), '[]'::jsonb)
                      from public.workflow_transitions t
                      join public.workflow_steps fs on fs.id = t.from_step_id
                      join public.workflow_steps ts on ts.id = t.to_step_id
                     where t.workflow_version_id = v_new_id)
  ) into v_snap;

  update public.workflow_versions set status = 'RETIRED' where id = v_pub.id;
  update public.workflow_versions
     set status = 'PUBLISHED', snapshot = v_snap, published_at = now()
   where id = v_new_id;
end $$;

-- DEC-30: one escalation level per step that has an SLA, seeded DISABLED. Fires `after_hours`
-- after the SLA breach and notifies the Replacement Manager role (provisional; docs/DECISIONS.md).
insert into public.escalation_rules (workflow_step_id, after_hours, notify_role_id, is_active)
select ws.id, ws.sla_hours, r.id, false
  from public.workflow_steps ws
  join public.workflow_versions wv on wv.id = ws.workflow_version_id and wv.status = 'PUBLISHED'
  join public.workflow_definitions wd on wd.id = wv.workflow_definition_id and wd.code = 'RMS_STANDARD'
  join public.roles r on r.code = 'REPLACEMENT_MANAGER'
 where ws.sla_hours is not null
   and not exists (select 1 from public.escalation_rules er where er.workflow_step_id = ws.id);

-- DEMO:BEGIN — local development demo data. NOT for remote/production.
-- docs/SETUP.md (Option B) strips this block (from this line to the DEMO END line).
-- Demo users are created by the P1-05 script, not here.
-- (Departments are the DEC-20 reference list above; no extra demo departments are invented.)
-- =============================================================================
insert into public.states (code, name) values
  ('UP', 'Uttar Pradesh'),
  ('DL', 'Delhi')
on conflict (name) do nothing;

insert into public.stations (state_id, name)
select s.id, v.station
from (values ('Uttar Pradesh', 'Agra'), ('Delhi', 'New Delhi')) as v(state, station)
join public.states s on s.name = v.state
on conflict (state_id, name) do nothing;

insert into public.parties (code, name, state_id, station_id, contact_name)
select v.code, v.name, s.id, st.id, v.contact
from (values
  ('DEMO-P001', 'Demo Party One (DEMO)', 'Uttar Pradesh', 'Agra',      'Demo Contact One'),
  ('DEMO-P002', 'Demo Party Two (DEMO)', 'Delhi',         'New Delhi', 'Demo Contact Two')
) as v(code, name, state, station, contact)
join public.states s on s.name = v.state
join public.stations st on st.state_id = s.id and st.name = v.station
on conflict (code) do nothing;

insert into public.transporters (name, type, phone) values
  ('Demo Transport Co. (DEMO)', 'DIRECT_TRUCK', null)
on conflict (name) do nothing;

-- Demo products, one per seeded category (P2-04 itemisation needs a product lookup; the real product
-- master arrives with P1-06). Clearly marked DEMO; not business products.
insert into public.products (code, name, category_id)
select v.code, v.name, c.id
from (values
  ('DEMO-DMT-001', 'Demo DMT Product (DEMO)',           'DMT'),
  ('DEMO-PRS-001', 'Demo Prismatic Product (DEMO)',     'PRISMATIC'),
  ('DEMO-EO-001',  'Demo Enclosed Oval Product (DEMO)', 'ENCLOSED_OVAL')
) as v(code, name, category)
join public.product_categories c on c.code = v.category
on conflict (code) do nothing;

-- DD r47: "Assigned Technician" option "Raj Kumar Ji" (not linked to a login yet).
insert into public.technicians (display_name) values
  ('Raj Kumar Ji')
on conflict (display_name) do nothing;
-- DEMO:END
