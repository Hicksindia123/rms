-- Change plan 2026-11-12 · Phase 10 (migration 20261114000300): role journeys (AMD-22, DEC-49) and
-- the feature hold setting (AMD-21, DEC-44). The menu catalogue only names screens / queues that
-- exist (closed lists, rule j), codes are immutable (rule e), a role lists a step once, and the
-- tables are reachable only through the API role (RLS on, no anon / authenticated grants).

begin;
select plan(14);

select has_table('public', 'journey_steps', 'journey_steps exists');
select has_table('public', 'role_journey_steps', 'role_journey_steps exists');
select ok((select relrowsecurity from pg_class where oid = 'public.journey_steps'::regclass),
          'RLS on journey_steps');
select ok((select relrowsecurity from pg_class where oid = 'public.role_journey_steps'::regclass),
          'RLS on role_journey_steps');
select ok(not has_table_privilege('authenticated', 'public.journey_steps', 'select'),
          'authenticated cannot read journey_steps directly');

select is((select count(*)::int from public.journey_steps where kind = 'STEP'), 21,
          'catalogue seeds the 21 journey steps of the target workflow (G2: DEPT_ISSUE; DEC-65: TRANSFER_SLIPS, EDIT_REQUESTS; DEC-66: ACK_TRANSFER_SLIPS; DEC-67: STORE_DEPT_ROUTING; DEC-68: STORE_DEPT_RECEIVING; DEC-69: STORE_ANALYSIS)');
select is((select value from public.system_settings where key = 'features.on_hold'),
          '["dismantling", "spare_parts", "battery", "pcb_subinventory"]'::jsonb,
          'features.on_hold default (DEC-44, PROVISIONAL)');
select ok((select count(*) from public.role_journey_steps) >= 51,
          'every operational role has its journey (seed.sql)');

select throws_ok(
  $$insert into public.journey_steps (code, label, kind, screen_key, perm_module)
    values ('T_BAD_SCREEN', 'X', 'TOOL', 'no-such-screen', 'goods_slips')$$,
  '23514', null, 'unknown screen_key is rejected (no dead links)');
select throws_ok(
  $$insert into public.journey_steps (code, label, kind, screen_key, item_screen_key, queue_code, perm_module)
    values ('T_BAD_QUEUE', 'X', 'STEP', 'journey-queue', 'gs-detail', 'NO_SUCH_QUEUE', 'goods_slips')$$,
  '23514', null, 'unknown queue_code is rejected');
select throws_ok(
  $$insert into public.journey_steps (code, label, kind, screen_key, item_screen_key, perm_module)
    values ('T_TOOL_ITEM', 'X', 'TOOL', 'reports', 'gs-detail', 'reports')$$,
  '23514', null, 'a TOOL has no per-GS screen');
select throws_ok(
  $$update public.journey_steps set code = 'OPEN_CARTONS' where code = 'CARTON_OPENING'$$,
  'P0001', null, 'journey step codes are immutable');
select throws_ok(
  $$update public.journey_steps set queue_code = 'COUNTING' where code = 'CARTON_OPENING'$$,
  null, null, 'queue codes are immutable');
select throws_ok(
  $$insert into public.role_journey_steps (role_id, journey_step_id)
    select rjs.role_id, rjs.journey_step_id from public.role_journey_steps rjs limit 1$$,
  '23505', null, 'a role lists a step only once');

select * from finish();
rollback;
