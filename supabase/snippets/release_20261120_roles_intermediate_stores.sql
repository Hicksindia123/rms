-- Release 2026-11-20 - Phase P1 (docs/RMS_PHASE_PROMPTS_20-11-2026.md): roles (DEC-60) and the
-- Intermediate Stores OP / DT / RI with their category mapping (DEC-61).
-- Run AFTER migration 20261120000100_p1_intermediate_stores.sql is pushed. Idempotent; safe to
-- re-run (it never removes a grant, store or mapping an admin has changed since):
--   psql "<admin url>" -X -v ON_ERROR_STOP=1 -f supabase/snippets/release_20261120_roles_intermediate_stores.sql
-- Same rows as supabase/seed.sql (roles, _seed_role_matrix, role journeys, inventory locations,
-- Intermediate Stores block).
begin;

-- DEC-60: labels only; codes (and so every user's access) are unchanged.
update public.roles set name = 'Gate User (Offline)', updated_at = now()
 where code = 'GATE_INWARD' and name = 'Gate Inward User';
update public.roles set name = 'Replacement Executive', updated_at = now()
 where code = 'INWARD_VERIFIER' and name = 'Unboxing & Inward Verifier';

insert into public.roles (code, name, description, is_system) values
  ('MANAGEMENT', 'Management',            'DEC-60: views everything; approves and edits (P4, P10)', true),
  ('ISTORE_OP',  'Intermediate Store OP', 'DEC-61: users of Intermediate Store OP', true),
  ('ISTORE_DT',  'Intermediate Store DT', 'DEC-61: users of Intermediate Store DT', true),
  ('ISTORE_RI',  'Intermediate Store RI', 'DEC-61: users of Intermediate Store RI', true)
on conflict (code) do nothing;

-- Permission grants (same as seed.sql _seed_role_matrix). Only for roles created by this release
-- or still without any grant, so a matrix an admin has already edited is left alone.
insert into public.role_permissions (role_id, permission_id, scope)
select r.id, p.id, 'all'
  from (values
    ('MANAGEMENT', 'dashboards',      array['view']),
    ('MANAGEMENT', 'notifications',   array['view']),
    ('MANAGEMENT', 'reports',         array['view','export']),
    ('MANAGEMENT', 'audit',           array['view']),
    ('MANAGEMENT', 'masters',         array['view']),
    ('MANAGEMENT', 'goods_slips',     array['view']),
    ('MANAGEMENT', 'unboxing',        array['view']),
    ('MANAGEMENT', 'attachments',     array['view']),
    ('MANAGEMENT', 'itemization',     array['view']),
    ('MANAGEMENT', 'inspection',      array['view']),
    ('MANAGEMENT', 'container_audit', array['view']),
    ('MANAGEMENT', 'custody',         array['view']),
    ('MANAGEMENT', 'servicing',       array['view']),
    ('MANAGEMENT', 'inventory',       array['view','export']),
    ('MANAGEMENT', 'dismantling',     array['view']),
    ('MANAGEMENT', 'dispatch',        array['view']),
    ('MANAGEMENT', 'credit_notes',    array['view']),
    ('MANAGEMENT', 'department_routing', array['view']),
    ('MANAGEMENT', 'final_actions',   array['view']),
    ('MANAGEMENT', 'ac_entry',        array['view']),
    ('MANAGEMENT', 'intermediate_stores', array['view']),
    ('ISTORE_OP',  'dashboards',      array['view']),
    ('ISTORE_OP',  'notifications',   array['view']),
    ('ISTORE_OP',  'goods_slips',     array['view']),
    ('ISTORE_OP',  'attachments',     array['view']),
    ('ISTORE_DT',  'dashboards',      array['view']),
    ('ISTORE_DT',  'notifications',   array['view']),
    ('ISTORE_DT',  'goods_slips',     array['view']),
    ('ISTORE_DT',  'attachments',     array['view']),
    ('ISTORE_RI',  'dashboards',      array['view']),
    ('ISTORE_RI',  'notifications',   array['view']),
    ('ISTORE_RI',  'goods_slips',     array['view']),
    ('ISTORE_RI',  'attachments',     array['view'])
  ) as m(role_code, module_code, actions)
  cross join unnest(m.actions) as a(action)
  join public.roles r on r.code = m.role_code
  join public.permissions p on p.module_code = m.module_code and p.action = a.action
 -- The statement snapshot is taken before the insert, so a role without grants gets all its rows.
 where not exists (select 1 from public.role_permissions x where x.role_id = r.id)
on conflict (role_id, permission_id) do nothing;

-- Super Admin marker role holds the whole catalogue (the migration already did this; repeated).
insert into public.role_permissions (role_id, permission_id, scope)
select r.id, p.id, 'all'
  from public.roles r cross join public.permissions p
 where r.code = 'SUPER_ADMIN'
on conflict (role_id, permission_id) do nothing;

-- Role journeys (menus).
insert into public.role_journey_steps (role_id, journey_step_id, sort_order)
select r.id, s.id, m.ord
  from (values
    ('MANAGEMENT', 'DASHBOARD',  100),
    ('MANAGEMENT', 'GS_LIST',    110),
    ('MANAGEMENT', 'PENDENCIES', 120),
    ('MANAGEMENT', 'REPORTS',    130),
    ('MANAGEMENT', 'AUDIT',      140),
    ('ISTORE_OP',  'GS_LIST',    100),
    ('ISTORE_DT',  'GS_LIST',    100),
    ('ISTORE_RI',  'GS_LIST',    100)
  ) as m(role_code, step_code, ord)
  join public.roles r on r.code = m.role_code
  join public.journey_steps s on s.code = m.step_code
on conflict (role_id, journey_step_id) do nothing;

-- Management dashboard (same widgets as Management Viewer; never overwrites an admin edit).
insert into public.role_dashboard_layouts (role_id, widgets)
select r.id, cast('[{"code":"GS_PIPELINE","size":"L"},{"code":"OPEN_PENDENCIES","size":"S"},{"code":"HAZARD_QUARANTINE","size":"S"},{"code":"CONTAINER_AUDIT","size":"M"},{"code":"TECHNICIAN_WIP","size":"M"},{"code":"CN_PIPELINE","size":"M"},{"code":"FUNCTIONAL_STOCK","size":"M"},{"code":"NON_FUNCTIONAL_STOCK","size":"M"},{"code":"DISMANTLING","size":"M"},{"code":"BATTERY_STOCK","size":"M"},{"code":"CN_ISSUED","size":"L"},{"code":"GS_TREND","size":"L"}]' as jsonb)
  from public.roles r where r.code = 'MANAGEMENT'
on conflict (role_id) do nothing;

-- Store locations (class FUNCTIONAL, DEC-61 / P0 F5).
insert into public.inventory_locations (code, name, location_class, custodian_role_id, department_id)
select v.code, v.name, 'FUNCTIONAL', r.id, d.id
  from (values
    ('ISTORE_OP', 'Intermediate Store OP'),
    ('ISTORE_DT', 'Intermediate Store DT'),
    ('ISTORE_RI', 'Intermediate Store RI')
  ) as v(code, name)
  join public.roles r on r.code = v.code
  left join public.departments d on d.code = 'INTERMEDIATE_STORE'
on conflict (code) do nothing;

-- Stores + mapping (only on a database that has no stores yet).
insert into public.intermediate_stores (code, name, role_id, location_id, is_default, sort_order)
select v.code, v.name, r.id, l.id, v.is_default, v.ord
  from (values
    ('OP', 'Intermediate Store OP', 'ISTORE_OP', false, 10),
    ('DT', 'Intermediate Store DT', 'ISTORE_DT', false, 20),
    ('RI', 'Intermediate Store RI', 'ISTORE_RI', true,  30)
  ) as v(code, name, role_code, is_default, ord)
  join public.roles r on r.code = v.role_code
  join public.inventory_locations l on l.code = v.role_code
 where not exists (select 1 from public.intermediate_stores)
on conflict (code) do nothing;

insert into public.intermediate_store_category_map (store_id, category_id)
select s.id, c.id
  from (values
    ('OP', 'ENCLOSED_OVAL'),
    ('OP', 'PRISMATIC'),
    ('DT', 'DMT'),
    ('RI', 'GENERAL')
  ) as v(store_code, category_code)
  join public.intermediate_stores s on s.code = v.store_code
  join public.product_categories c on c.code = v.category_code
 where not exists (select 1 from public.intermediate_store_category_map m where m.category_id = c.id)
on conflict do nothing;

-- Report what is there (read it in the psql output).
select s.code, s.name, s.is_default, s.is_active, r.code as role_code, l.code as location_code,
       (select string_agg(c.code, ', ' order by c.code)
          from public.intermediate_store_category_map m
          join public.product_categories c on c.id = m.category_id
         where m.store_id = s.id) as categories
  from public.intermediate_stores s
  join public.roles r on r.id = s.role_id
  join public.inventory_locations l on l.id = s.location_id
 order by s.sort_order;

commit;
