-- DEC-59 (migration 20261119000100): business Categorisation / Department masters per thermometer
-- category. The repo seed keeps the workbook masters, so the function is applied here inside the
-- test transaction (rolled back).

begin;
select plan(16);

select ok(rms_private.apply_thermometer_masters(), 'masters applied (categories exist)');

-- Resolved category-level lists (live configuration), in business order.
create temporary table resolved on commit drop as
select c.code as category_code, r.field_group, array_agg(r.code order by r.sort_order) as codes
  from public.product_categories c
  cross join lateral rms_private.resolve_item_field_profile_for_scope(c.id) r
 where c.code in ('DMT', 'PRISMATIC', 'ENCLOSED_OVAL')
   and r.field_group in ('CATEGORISATION', 'DEPARTMENT')
 group by c.code, r.field_group;

select is((select codes from resolved where category_code = 'ENCLOSED_OVAL' and field_group = 'CATEGORISATION'),
  array['GOOD_PIECE', 'INNER_BROKEN', 'BODY_BROKEN', 'DAMAGED_WASTAGE'], 'OVAL categorisation list');
select is((select codes from resolved where category_code = 'ENCLOSED_OVAL' and field_group = 'DEPARTMENT'),
  array['GRADING', 'MERCURY_EXTRACTION', 'WASTE_MANAGEMENT'], 'OVAL department list');
select is((select codes from resolved where category_code = 'PRISMATIC' and field_group = 'CATEGORISATION'),
  array['GOOD_PIECE', 'BROKEN_WITH_MERCURY'], 'PRISMATIC categorisation list');
select is((select codes from resolved where category_code = 'PRISMATIC' and field_group = 'DEPARTMENT'),
  array['GRADING', 'MERCURY_EXTRACTION'], 'PRISMATIC department list');
select is((select codes from resolved where category_code = 'DMT' and field_group = 'CATEGORISATION'),
  array['VISUALLY_OKAY_SELLABLE', 'VISUALLY_OKAY_PACKAGING_DAMAGED', 'SCRATCHED_DIRTY', 'DAMAGED_WASTAGE'],
  'DIGITAL categorisation list');
select is((select codes from resolved where category_code = 'DMT' and field_group = 'DEPARTMENT'),
  array['STORE', 'REPACKAGING', 'CLEANING', 'WASTE_MANAGEMENT'], 'DIGITAL department list');

-- Labels verbatim.
select is((select label from public.item_field_library where field_group = 'DEPARTMENT' and code = 'STORE'),
  'Issue to Store', 'STORE relabelled (code kept: no-work setting keys off it)');
select is((select label from public.item_field_library where field_group = 'CATEGORISATION' and code = 'BROKEN_WITH_MERCURY'),
  'Broken (With Mercury)', 'label verbatim');

-- Old masters deactivated, not deleted.
select is((select count(*)::int from public.item_field_library
            where field_group in ('CATEGORISATION', 'DEPARTMENT') and is_active),
  14, 'only the 14 business entries are active');
select ok(exists (select 1 from public.item_field_library
                   where field_group = 'DEPARTMENT' and code = 'REPAIR' and not is_active),
  'old department REPAIR kept but inactive');
select is((select count(*)::int from public.item_field_assignments a
             join public.item_field_library l on l.id = a.field_id
            where l.field_group in ('CATEGORISATION', 'DEPARTMENT') and not l.is_active),
  0, 'no assignment points at a deactivated entry');

-- Idempotent: a second run changes nothing (no new profile version).
create temporary table v_before on commit drop as
  select count(*) as n from public.item_field_assignments;
select ok(rms_private.apply_thermometer_masters(), 'second run');
select is((select count(*) from public.item_field_assignments), (select n from v_before),
  'second run leaves the assignments unchanged');

-- Locations and the location map.
select is((select count(*)::int from public.inventory_locations
            where code in ('DEPT_GRADING', 'DEPT_REPACKAGING', 'DEPT_WASTE_MANAGEMENT')),
  3, 'department locations exist');
select is((select value ->> 'WASTE_MANAGEMENT' from public.system_settings
            where key = 'department.location_by_code'),
  'DEPT_WASTE_MANAGEMENT', 'location map lists the new departments');

select * from finish();
rollback;
