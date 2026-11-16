-- ---------------------------------------------------------------------------------------------
-- Add Inspection & Grading to Journey Steps (P2-05 / Role Journeys)
-- ---------------------------------------------------------------------------------------------

-- 1. Update check constraint on item_screen_key to include 'gs-inspection'
alter table public.journey_steps drop constraint if exists journey_steps_item_screen_key_check;
alter table public.journey_steps add constraint journey_steps_item_screen_key_check check (
  item_screen_key is null or item_screen_key in (
    'gs-detail', 'gs-unboxing', 'gs-itemization', 'gs-inspection', 'gs-rm-review',
    'custody-transfer', 'gs-final-actions', 'department-receiving',
    'accounts-entry-gs', 'accounts-docs', 'dispatch-slips',
    'gs-party-notification'
  )
);

-- 2. Update check constraint on queue_code to include 'INSPECTION'
alter table public.journey_steps drop constraint if exists journey_steps_queue_code_check;
alter table public.journey_steps add constraint journey_steps_queue_code_check check (
  queue_code is null or queue_code in (
    'CARTON_OPENING', 'COUNTING', 'CATEGORISATION', 'INSPECTION', 'RM_REVIEW', 'STORE_ACCEPT',
    'DEPT_ROUTING', 'DEPT_RECEIVING', 'FINAL_ACTIONS', 'ACCOUNTS_DOCS',
    'ACCOUNTS_ENTRY', 'DISPATCH_SLIP', 'PARTY_EMAIL'
  )
);

-- 3. Insert 'INSPECTION' step into public.journey_steps
insert into public.journey_steps
  (code, label, hint, kind, screen_key, item_screen_key, queue_code, feature_code,
   perm_module, perm_action, sort_order, source_ref)
values
  ('INSPECTION', 'Inspection & Grading', 'Visual inspection and grading of items', 'STEP', 'journey-queue', 'gs-inspection', 'INSPECTION', null, 'inspection', 'edit', 45, 'P2-05')
on conflict (code) do update set
  label = excluded.label,
  hint = excluded.hint,
  kind = excluded.kind,
  screen_key = excluded.screen_key,
  item_screen_key = excluded.item_screen_key,
  queue_code = excluded.queue_code,
  perm_module = excluded.perm_module,
  perm_action = excluded.perm_action,
  sort_order = excluded.sort_order;

-- 4. Assign to INWARD_VERIFIER role journey
insert into public.role_journey_steps (role_id, journey_step_id, sort_order)
select r.id, s.id, 35
  from public.roles r, public.journey_steps s
 where r.code = 'INWARD_VERIFIER' and s.code = 'INSPECTION'
on conflict (role_id, journey_step_id) do nothing;
