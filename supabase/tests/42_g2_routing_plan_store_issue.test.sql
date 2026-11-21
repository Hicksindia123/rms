-- Gap plan G2 (migration 20261118000100; DEC-55; Q3–Q6, Q15, Q16; Guard G-20).
-- RM routing plan per item + condition, Store issue as the only way to a department, department
-- locations, STORE "no work", plan-line state machine and the extended G-20 check.

begin;
select plan(27);

-- Scenario: GS A held (10 pcs, split GOOD 6 / DAMAGED 4), GS B in RM_REVIEW (5 pcs).
do $$
declare
  v_good uuid;
  v_dmg  uuid;
begin
  set local session_replication_role = 'replica';

  insert into public.goods_slips (
    id, gs_no, workflow_version_id, delivery_mode_code, courier_name, docket_no, carton_count, box_count, status
  )
  select g.id, g.no, v.id, 'COURIER_PARCEL', 'Test Courier', '123', 1, 1, g.status
    from (values
      ('88888888-0000-0000-0000-00000000000a'::uuid, 'GS/TEST/G2/A', 'HELD_AT_INTERMEDIATE_STORE'),
      ('88888888-0000-0000-0000-00000000000b'::uuid, 'GS/TEST/G2/B', 'RM_REVIEW')
    ) as g(id, no, status)
    cross join lateral (
      select v.id from public.workflow_versions v
        join public.workflow_definitions d on d.id = v.workflow_definition_id and d.code = 'RMS_STANDARD'
       where v.status = 'PUBLISHED' limit 1
    ) v;

  insert into public.gs_items (id, gs_id, line_no, product_id, category_id, documented_qty, received_qty)
  select i.id, i.gs_id, 1, p.id, p.category_id, i.qty, i.qty
    from (values
      ('88888888-0000-0000-0000-0000000000a1'::uuid, '88888888-0000-0000-0000-00000000000a'::uuid, 10),
      ('88888888-0000-0000-0000-0000000000b1'::uuid, '88888888-0000-0000-0000-00000000000b'::uuid, 5)
    ) as i(id, gs_id, qty)
    cross join lateral (
      select pr.id, pr.category_id from public.products pr
        join public.product_categories c on c.id = pr.category_id and c.code = 'DMT'
       limit 1
    ) p;

  select id into v_good from public.item_field_library where field_group = 'CATEGORISATION' order by sort_order limit 1;
  select id into v_dmg  from public.item_field_library where field_group = 'CATEGORISATION' and id <> v_good order by sort_order limit 1;
  insert into public.gs_item_buckets (gs_item_id, field_id, field_code, label_snapshot, qty)
  select '88888888-0000-0000-0000-0000000000a1', l.id, l.code, l.label, case when l.id = v_good then 6 else 4 end
    from public.item_field_library l where l.id in (v_good, v_dmg);

  set local session_replication_role = 'origin';
end;
$$;

create temp table g2 as
select (select id from public.item_field_library where field_group = 'DEPARTMENT' and code = 'REPAIR') as repair,
       (select id from public.item_field_library where field_group = 'DEPARTMENT' and code = 'STORE') as store,
       (select id from public.item_field_library where field_group = 'DEPARTMENT' and code = 'TECHNICAL_INSPECTION') as tech_insp,
       (select b.field_id from public.gs_item_buckets b
         where b.gs_item_id = '88888888-0000-0000-0000-0000000000a1' and b.qty = 6) as good,
       (select id from public.inventory_locations where code = 'DEPT_TECHNICIAN_REPAIR') as repair_loc;

-- ---------------------------------------------------------------------------
-- 1. Configuration (Q3, Q15, Q16)
-- ---------------------------------------------------------------------------
select has_table('public', 'department_routing_plan_lines', 'routing plan lines table exists');
select is((select label from public.item_field_library where field_group = 'DEPARTMENT' and code = 'REPAIR'),
          'Technician / Repair', 'REPAIR relabelled "Technician / Repair" (Q3)');
select ok(not (select is_active from public.item_field_library where field_group = 'DEPARTMENT' and code = 'TECHNICAL_INSPECTION'),
          'TECHNICAL_INSPECTION deactivated (Q15)');
select ok(rms_private.department_is_no_work('STORE') and not rms_private.department_is_no_work('REPAIR'),
          'STORE is the configured "no work" department (Q4)');
select is((select count(*)::int from public.product_categories c
            where not exists (select 1 from public.item_field_assignments a
                               where a.field_group = 'DEPARTMENT' and a.category_id = c.id)), 0,
          'every category has departments enabled by default');
select is((select value ->> 'REPAIR' from public.system_settings where key = 'department.location_by_code'),
          'DEPT_TECHNICIAN_REPAIR', 'Technician / Repair has its own stock location (Q16)');

-- ---------------------------------------------------------------------------
-- 2. Plan insert guard
-- ---------------------------------------------------------------------------
select throws_matching(
  $$insert into public.department_routing_plan_lines (gs_id, gs_item_id, department_field_id, department_code, department_label, qty)
    select '88888888-0000-0000-0000-00000000000b', '88888888-0000-0000-0000-0000000000b1', repair, '-', '-', 1 from g2$$,
  'G-20: a routing plan needs the goods slip held',
  'G-20: plan rejected while the GS is not held at the intermediate store'
);
select throws_matching(
  $$insert into public.department_routing_plan_lines (gs_id, gs_item_id, department_field_id, department_code, department_label, qty)
    select '88888888-0000-0000-0000-00000000000a', '88888888-0000-0000-0000-0000000000b1', repair, '-', '-', 1 from g2$$,
  'does not belong to the goods slip',
  'G-20: plan rejected for an item of another GS'
);
select throws_matching(
  $$insert into public.department_routing_plan_lines (gs_id, gs_item_id, department_field_id, department_code, department_label, qty)
    select '88888888-0000-0000-0000-00000000000a', '88888888-0000-0000-0000-0000000000a1', tech_insp, '-', '-', 1 from g2$$,
  'needs an active DEPARTMENT field',
  'G-20: plan rejected for the deactivated TECHNICAL_INSPECTION department'
);
select throws_matching(
  $$insert into public.department_routing_plan_lines (gs_id, gs_item_id, source_bucket_field_id, department_field_id, department_code, department_label, qty)
    select '88888888-0000-0000-0000-00000000000a', '88888888-0000-0000-0000-0000000000a1',
           (select id from public.item_field_library where field_group = 'ACTION' limit 1), repair, '-', '-', 1 from g2$$,
  'is not a categorisation bucket of this item',
  'G-20: plan rejected for a condition that is not part of the item split'
);

select lives_ok(
  $$insert into public.department_routing_plan_lines
      (id, gs_id, gs_item_id, source_bucket_field_id, department_field_id, department_code, department_label, qty, status, is_no_work)
    select '88888888-0000-0000-0000-000000000101', '88888888-0000-0000-0000-00000000000a', '88888888-0000-0000-0000-0000000000a1',
           good, repair, 'FAKE', 'Fake', 6, 'ISSUED', true from g2$$,
  'plan line to Technician / Repair accepted'
);
select results_eq(
  $$select status, is_no_work, department_code, department_label from public.department_routing_plan_lines
     where id = '88888888-0000-0000-0000-000000000101'$$,
  $$values ('PLANNED'::text, false, 'REPAIR'::text, 'Technician / Repair'::text)$$,
  'status, no-work flag and labels come from the DB, not the client (G-18)'
);
select lives_ok(
  $$insert into public.department_routing_plan_lines
      (id, gs_id, gs_item_id, department_field_id, department_code, department_label, qty)
    select '88888888-0000-0000-0000-000000000102', '88888888-0000-0000-0000-00000000000a', '88888888-0000-0000-0000-0000000000a1',
           store, '-', '-', 2 from g2$$,
  'STORE plan line accepted'
);
select is((select status from public.department_routing_plan_lines where id = '88888888-0000-0000-0000-000000000102'),
          'NO_WORK', 'STORE line is NO_WORK: no Store issue needed (Q4)');

-- G-20 extended: planned pieces can never exceed the store (6 planned + 5 > 10 in store).
select throws_matching(
  $$insert into public.department_routing_plan_lines (gs_id, gs_item_id, department_field_id, department_code, department_label, qty)
    select '88888888-0000-0000-0000-00000000000a', '88888888-0000-0000-0000-0000000000a1', repair, '-', '-', 5 from g2$$,
  'G-20: item line 1 .*planned for departments but only',
  'G-20: over-planning beyond the intermediate store is rejected'
);

-- ---------------------------------------------------------------------------
-- 3. Plan line state machine
-- ---------------------------------------------------------------------------
select throws_matching(
  $$update public.department_routing_plan_lines set qty = 1 where id = '88888888-0000-0000-0000-000000000101'$$,
  'cannot be changed; cancel it and plan again',
  'G-20: a plan line quantity cannot be edited'
);
select throws_matching(
  $$update public.department_routing_plan_lines set status = 'NO_WORK' where id = '88888888-0000-0000-0000-000000000101'$$,
  'routing plan line cannot go from PLANNED to NO_WORK|dept_plan_lines_status_kind_check',
  'G-20: PLANNED cannot jump to NO_WORK'
);
select throws_matching(
  $$update public.department_routing_plan_lines set status = 'CANCELLED', cancelled_at = now()
     where id = '88888888-0000-0000-0000-000000000102'$$,
  'dept_plan_lines_cancel_check',
  'cancelling needs a reason'
);
select lives_ok(
  $$update public.department_routing_plan_lines
       set status = 'CANCELLED', cancelled_at = now(), cancel_reason = 'Re-plan'
     where id = '88888888-0000-0000-0000-000000000102'$$,
  'a NO_WORK line can be cancelled with a reason'
);
select throws_matching(
  $$update public.department_routing_plan_lines set status = 'NO_WORK', cancelled_at = null, cancel_reason = null
     where id = '88888888-0000-0000-0000-000000000102'$$,
  'cannot go from CANCELLED to NO_WORK',
  'G-20: a cancelled line stays cancelled'
);

-- ---------------------------------------------------------------------------
-- 4. Department routings: location required, never to STORE, only through a Store issue
-- ---------------------------------------------------------------------------
select throws_matching(
  $$insert into public.department_routings (routing_no, gs_id, department_field_id, department_code, department_label)
    select 'DIN/TEST/G2/0', '88888888-0000-0000-0000-00000000000a', repair, '-', '-' from g2$$,
  'needs the department''s stock location',
  'G-20: a department routing without its department location is rejected'
);
select throws_matching(
  $$insert into public.department_routings (routing_no, gs_id, department_field_id, department_code, department_label, location_id)
    select 'DIN/TEST/G2/S', '88888888-0000-0000-0000-00000000000a', store, '-', '-', repair_loc from g2$$,
  'needs no work; its pieces stay in the intermediate store',
  'G-20: STORE (no work) is never issued to a department'
);

insert into public.department_routings (id, routing_no, gs_id, department_field_id, department_code, department_label, location_id)
select '88888888-0000-0000-0000-000000000201', 'DIN/TEST/G2/1', '88888888-0000-0000-0000-00000000000a', repair, '-', '-', repair_loc from g2;

-- DEC-55: a routing line that is not the issue of a plan line fails at commit (deferred check).
select throws_matching(
  $q$do $x$ begin
      insert into public.department_routing_lines (routing_id, gs_item_id, qty_sent)
      values ('88888888-0000-0000-0000-000000000201', '88888888-0000-0000-0000-0000000000a1', 1);
      set constraints trg_dept_routing_lines_from_plan, trg_dept_routing_lines_g20 immediate;
    end $x$ $q$,
  'has no issued routing plan line of the same store',
  'DEC-55: the RM cannot move pieces to a department without a Store issue'
);

-- Issue must match the plan line (item, qty, department).
select throws_matching(
  $q$do $x$ begin
      insert into public.department_routing_lines (id, routing_id, gs_item_id, qty_sent)
      values ('88888888-0000-0000-0000-000000000301', '88888888-0000-0000-0000-000000000201', '88888888-0000-0000-0000-0000000000a1', 5);
      update public.department_routing_plan_lines
         set status = 'ISSUED', routing_id = '88888888-0000-0000-0000-000000000201',
             routing_line_id = '88888888-0000-0000-0000-000000000301', issued_at = now()
       where id = '88888888-0000-0000-0000-000000000101';
    end $x$ $q$,
  'issued routing line does not match plan line',
  'G-20: an issue with a different quantity than planned is rejected'
);

-- Happy path: matching routing line + plan line ISSUED; the deferred check passes.
select lives_ok(
  $q$do $x$ begin
      insert into public.department_routing_lines (id, routing_id, gs_item_id, source_bucket_field_id, qty_sent)
      select '88888888-0000-0000-0000-000000000302', '88888888-0000-0000-0000-000000000201', '88888888-0000-0000-0000-0000000000a1', good, 6 from g2;
      update public.department_routing_plan_lines
         set status = 'ISSUED', routing_id = '88888888-0000-0000-0000-000000000201',
             routing_line_id = '88888888-0000-0000-0000-000000000302', issued_at = now()
       where id = '88888888-0000-0000-0000-000000000101';
      set constraints trg_dept_routing_lines_from_plan, trg_dept_routing_lines_g20 immediate;
    end $x$ $q$,
  'Store issue of a planned line passes every guard'
);
select throws_matching(
  $$update public.department_routing_plan_lines set status = 'CANCELLED', cancelled_at = now(), cancel_reason = 'x'
     where id = '88888888-0000-0000-0000-000000000101'$$,
  'cannot go from ISSUED to CANCELLED',
  'G-20: an issued line cannot be cancelled'
);

-- ---------------------------------------------------------------------------
-- 5. Privileges
-- ---------------------------------------------------------------------------
select ok(not has_table_privilege('rms_api', 'public.department_routing_plan_lines', 'DELETE'),
  'rms_api cannot delete routing plan lines');

select * from finish();
rollback;
