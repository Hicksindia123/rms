-- DEC-59 (user request 2026-11-19): replace the Categorisation and Department Routing masters
-- (item_field_library groups CATEGORISATION / DEPARTMENT, AMD-10) with the business list per
-- thermometer category, and map them to the categories:
--
--   OVAL (category ENCLOSED_OVAL; XL + Enclosed thermometers)
--     GOOD PIECE              -> Grading (Production)
--     INNER BROKEN            -> Mercury Extraction (Production)
--     BODY BROKEN             -> Mercury Extraction (Production)
--     DAMAGED / WASTAGE       -> Waste Management
--   PRISMATIC (Dumark, Akutum)
--     GOOD PIECE              -> Grading (Production)
--     Broken (With Mercury)   -> Mercury Extraction (Production)
--   DIGITAL (category DMT; all items)
--     VISUALLY OKAY SELLABLE          -> Issue to Store
--     VISUALLY OKAY PACKAGING DAMAGED -> Repackaging (Production)
--     SCRATCHED / DIRTY               -> Cleaning (Production)
--     DAMAGED / WASTAGE               -> Waste Management
--
-- User decision 2026-11-19: each category is restricted to exactly the departments of its list;
-- the Replacement Manager still picks the department per condition bucket (DEC-55 unchanged).
--
-- 1. Library: the entries above are created / re-activated with these labels. Codes STORE,
--    MERCURY_EXTRACTION and CLEANING are kept (relabelled) because logic and settings key off
--    them (department.no_work_codes = STORE, department.location_by_code). Every other
--    CATEGORISATION / DEPARTMENT entry is DEACTIVATED, never deleted (AMD-10: history keeps
--    resolving; GS stamped with an older profile version keep their configuration, G-18).
-- 2. Assignments: every CATEGORISATION / DEPARTMENT assignment of the three thermometer categories
--    (category, sub-category and product scope) and every assignment of a deactivated entry is
--    removed; the category-level assignments above are added. The deferred version trigger writes
--    one new item field profile version for the whole change.
-- 3. Locations DEPT_GRADING / DEPT_REPACKAGING / DEPT_WASTE_MANAGEMENT (user decision: own
--    location per department, as DEC-55 Q16) + department.location_by_code entries (admin entries
--    win). Repeated in seed.sql for the custodian (roles are seed data on a fresh reset).
--
-- rms_private.apply_thermometer_masters() is idempotent. It does nothing when the three categories
-- do not exist (fresh `supabase db reset`: categories are seed data; the repo seed keeps the
-- workbook masters the automated tests are written against, see docs/DECISIONS.md DEC-59). On an
-- existing database (local, Supabase Cloud) this migration applies it. No guard is touched.

-- ===========================================================================
-- 1–2. Masters + category mapping
-- ===========================================================================
create or replace function rms_private.apply_thermometer_masters()
returns boolean
language plpgsql
set search_path = ''
as $$
declare
  v_ref  constant text := 'DEC-59';
begin
  if (select count(*) from public.product_categories
       where code in ('DMT', 'PRISMATIC', 'ENCLOSED_OVAL')) <> 3 then
    return false;
  end if;

  -- Library (codes immutable, rule e; labels verbatim from the business list).
  insert into public.item_field_library
    (field_group, code, label, sort_order, is_active, is_wastage, source_ref)
  values
    ('CATEGORISATION', 'GOOD_PIECE',                      'GOOD PIECE',                      10, true, false, v_ref),
    ('CATEGORISATION', 'INNER_BROKEN',                    'INNER BROKEN',                    20, true, false, v_ref),
    ('CATEGORISATION', 'BODY_BROKEN',                     'BODY BROKEN',                     30, true, false, v_ref),
    ('CATEGORISATION', 'BROKEN_WITH_MERCURY',             'Broken (With Mercury)',           40, true, false, v_ref),
    ('CATEGORISATION', 'VISUALLY_OKAY_SELLABLE',          'VISUALLY OKAY SELLABLE',          50, true, false, v_ref),
    ('CATEGORISATION', 'VISUALLY_OKAY_PACKAGING_DAMAGED', 'VISUALLY OKAY PACKAGING DAMAGED', 60, true, false, v_ref),
    ('CATEGORISATION', 'SCRATCHED_DIRTY',                 'SCRATCHED / DIRTY',               70, true, false, v_ref),
    ('CATEGORISATION', 'DAMAGED_WASTAGE',                 'DAMAGED / WASTAGE',               80, true, true,  v_ref),
    ('DEPARTMENT',     'STORE',                           'Issue to Store',                   5, true, false, v_ref),
    ('DEPARTMENT',     'GRADING',                         'Grading (Production)',            10, true, false, v_ref),
    ('DEPARTMENT',     'MERCURY_EXTRACTION',              'Mercury Extraction (Production)', 20, true, false, v_ref),
    ('DEPARTMENT',     'REPACKAGING',                     'Repackaging (Production)',        30, true, false, v_ref),
    ('DEPARTMENT',     'CLEANING',                        'Cleaning (Production)',           40, true, false, v_ref),
    ('DEPARTMENT',     'WASTE_MANAGEMENT',                'Waste Management',                50, true, true,  v_ref)
  on conflict (field_group, code) do update
     set label = excluded.label,
         sort_order = excluded.sort_order,
         is_active = true,
         is_wastage = excluded.is_wastage,
         source_ref = excluded.source_ref
   where (public.item_field_library.label, public.item_field_library.sort_order,
          public.item_field_library.is_active, public.item_field_library.is_wastage,
          public.item_field_library.source_ref)
         is distinct from
         (excluded.label, excluded.sort_order, true, excluded.is_wastage, excluded.source_ref);

  create temporary table if not exists pg_temp.dec59_map (
    category_code text, field_group text, code text, sort_order integer
  ) on commit drop;
  truncate pg_temp.dec59_map;
  insert into pg_temp.dec59_map values
    ('ENCLOSED_OVAL', 'CATEGORISATION', 'GOOD_PIECE',                      10),
    ('ENCLOSED_OVAL', 'CATEGORISATION', 'INNER_BROKEN',                    20),
    ('ENCLOSED_OVAL', 'CATEGORISATION', 'BODY_BROKEN',                     30),
    ('ENCLOSED_OVAL', 'CATEGORISATION', 'DAMAGED_WASTAGE',                 40),
    ('ENCLOSED_OVAL', 'DEPARTMENT',     'GRADING',                         10),
    ('ENCLOSED_OVAL', 'DEPARTMENT',     'MERCURY_EXTRACTION',              20),
    ('ENCLOSED_OVAL', 'DEPARTMENT',     'WASTE_MANAGEMENT',                30),
    ('PRISMATIC',     'CATEGORISATION', 'GOOD_PIECE',                      10),
    ('PRISMATIC',     'CATEGORISATION', 'BROKEN_WITH_MERCURY',             20),
    ('PRISMATIC',     'DEPARTMENT',     'GRADING',                         10),
    ('PRISMATIC',     'DEPARTMENT',     'MERCURY_EXTRACTION',              20),
    ('DMT',           'CATEGORISATION', 'VISUALLY_OKAY_SELLABLE',          10),
    ('DMT',           'CATEGORISATION', 'VISUALLY_OKAY_PACKAGING_DAMAGED', 20),
    ('DMT',           'CATEGORISATION', 'SCRATCHED_DIRTY',                 30),
    ('DMT',           'CATEGORISATION', 'DAMAGED_WASTAGE',                 40),
    ('DMT',           'DEPARTMENT',     'STORE',                           10),
    ('DMT',           'DEPARTMENT',     'REPACKAGING',                     20),
    ('DMT',           'DEPARTMENT',     'CLEANING',                        30),
    ('DMT',           'DEPARTMENT',     'WASTE_MANAGEMENT',                40);

  -- "Remove the current masters": deactivate everything not on the business list.
  update public.item_field_library l
     set is_active = false
   where l.field_group in ('CATEGORISATION', 'DEPARTMENT')
     and l.is_active
     and not exists (select 1 from pg_temp.dec59_map m
                      where m.field_group = l.field_group and m.code = l.code);

  -- Assignments: drop the old mapping of the thermometer categories (every scope) and every
  -- assignment of a deactivated entry, unless it is already exactly the target mapping.
  delete from public.item_field_assignments a
   where a.field_group in ('CATEGORISATION', 'DEPARTMENT')
     and (
       a.field_id in (select l.id from public.item_field_library l
                       where l.field_group in ('CATEGORISATION', 'DEPARTMENT') and not l.is_active)
       or a.subcategory_id in (select s.id from public.product_subcategories s
                                 join public.product_categories c on c.id = s.category_id
                                where c.code in ('DMT', 'PRISMATIC', 'ENCLOSED_OVAL'))
       or a.product_id in (select p.id from public.products p
                             join public.product_categories c on c.id = p.category_id
                            where c.code in ('DMT', 'PRISMATIC', 'ENCLOSED_OVAL'))
       or (a.scope_type = 'CATEGORY'
           and a.category_id in (select c.id from public.product_categories c
                                  where c.code in ('DMT', 'PRISMATIC', 'ENCLOSED_OVAL'))
           and not exists (
             select 1 from pg_temp.dec59_map m
               join public.product_categories c on c.code = m.category_code
               join public.item_field_library l on l.field_group = m.field_group and l.code = m.code
              where c.id = a.category_id and l.id = a.field_id
                and a.is_included and a.sort_order = m.sort_order))
     );

  insert into public.item_field_assignments
    (field_id, field_group, scope_type, category_id, is_included, sort_order)
  select l.id, m.field_group, 'CATEGORY', c.id, true, m.sort_order
    from pg_temp.dec59_map m
    join public.product_categories c on c.code = m.category_code
    join public.item_field_library l on l.field_group = m.field_group and l.code = m.code
  on conflict (scope_type, scope_id, field_id) do nothing;

  drop table pg_temp.dec59_map;
  return true;
end;
$$;
revoke all on function rms_private.apply_thermometer_masters() from public, anon, authenticated;
comment on function rms_private.apply_thermometer_masters() is
  'DEC-59: business Categorisation / Department masters per thermometer category (idempotent; false = categories missing, nothing done).';

select rms_private.apply_thermometer_masters();

-- ===========================================================================
-- 3. Department locations + location map (DEC-55 Q16 pattern)
-- ===========================================================================
insert into public.inventory_locations (code, name, location_class, custodian_role_id)
select v.code, v.name, 'TECHNICIAN', r.id
  from (values
    ('DEPT_GRADING',          'Department: Grading'),
    ('DEPT_REPACKAGING',      'Department: Repackaging'),
    ('DEPT_WASTE_MANAGEMENT', 'Department: Waste Management')
  ) as v(code, name)
  left join public.roles r on r.code = 'INTERMEDIATE_STORE_MANAGER'
on conflict (code) do nothing;

update public.system_settings
   set value = '{"GRADING": "DEPT_GRADING", "REPACKAGING": "DEPT_REPACKAGING", "WASTE_MANAGEMENT": "DEPT_WASTE_MANAGEMENT"}'::jsonb
               || value,
       source_ref = 'DEC-55, DEC-59'
 where key = 'department.location_by_code'
   and jsonb_typeof(value) = 'object';

-- ===========================================================================
-- 4. Journey hint: department names come from the masters, so the hint names none (only if it is
--    still the G2 text; an admin edit wins).
-- ===========================================================================
update public.journey_steps
   set hint = 'Held in store: plan which department each condition goes to'
 where code = 'DEPT_ROUTING'
   and hint = 'Held in store: plan where each condition goes (Store / Cleaning / Technician / Mercury)';
