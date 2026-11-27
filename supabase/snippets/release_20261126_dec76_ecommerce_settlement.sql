-- Release 2026-11-26 - E-Commerce settlement (DEC-76): roles, grants and menus.
-- The E-Commerce Executive (role TICKET_HANDLER, relabelled) closes tickets with the portal
-- resolution and does the Portal Check; the Replacement Executive (INWARD_VERIFIER) unboxes into
-- per-platform action sheets and records repairs; Intermediate Store users acknowledge receipts;
-- the new role ECOM_ACCOUNTS issues the credit note of an action sheet.
--
-- Apply to production AFTER migration 20261126000100_dec76_ecommerce_settlement.sql and after
-- deploying the backend + frontend. Idempotent; safe to re-run:
--   supabase db query --linked -f supabase/snippets/release_20261126_dec76_ecommerce_settlement.sql
-- Same configuration as supabase/seed.sql.
begin;

-- 1. Roles (seed data, DEC-60 convention). Relabel only the seeded name (an admin rename stays).
insert into public.roles (code, name, description, is_system) values
  ('ECOM_ACCOUNTS', 'Accounts (E-Commerce)', 'DEC-76: issues the credit note of E-Commerce action sheets', true)
on conflict (code) do nothing;
update public.roles
   set name = 'E-Commerce Executive',
       description = 'DEC-73 / DEC-76: platform tickets and follow-ups, portal check (Free Replacement / Refund)'
 where code = 'TICKET_HANDLER' and name = 'Ticket Handler';

-- 2. Grants.
insert into public.role_permissions (role_id, permission_id, scope)
select r.id, p.id, 'all'
  from (values
    ('INWARD_VERIFIER',   'ecommerce_returns',        'view'),
    ('INWARD_VERIFIER',   'ecommerce_unboxing',       'view'),
    ('INWARD_VERIFIER',   'ecommerce_unboxing',       'create'),
    ('INWARD_VERIFIER',   'ecommerce_accounts',       'view'),
    ('ISTORE_OP',         'ecommerce_store_receipts', 'view'),
    ('ISTORE_OP',         'ecommerce_store_receipts', 'create'),
    ('ISTORE_DT',         'ecommerce_store_receipts', 'view'),
    ('ISTORE_DT',         'ecommerce_store_receipts', 'create'),
    ('ISTORE_RI',         'ecommerce_store_receipts', 'view'),
    ('ISTORE_RI',         'ecommerce_store_receipts', 'create'),
    ('ECOM_ACCOUNTS',     'dashboards',               'view'),
    ('ECOM_ACCOUNTS',     'notifications',            'view'),
    ('ECOM_ACCOUNTS',     'ecommerce_returns',        'view'),
    ('ECOM_ACCOUNTS',     'ecommerce_accounts',       'view'),
    ('ECOM_ACCOUNTS',     'ecommerce_accounts',       'edit'),
    ('MANAGEMENT',        'ecommerce_unboxing',       'view'),
    ('MANAGEMENT',        'ecommerce_store_receipts', 'view'),
    ('MANAGEMENT',        'ecommerce_accounts',       'view'),
    ('MANAGEMENT_VIEWER', 'ecommerce_unboxing',       'view'),
    ('MANAGEMENT_VIEWER', 'ecommerce_store_receipts', 'view'),
    ('MANAGEMENT_VIEWER', 'ecommerce_accounts',       'view')
  ) as m(role_code, module_code, action)
  join public.roles r on r.code = m.role_code
  join public.permissions p on p.module_code = m.module_code and p.action = m.action
on conflict (role_id, permission_id) do nothing;

-- 3. Menus.
insert into public.role_journey_steps (role_id, journey_step_id, sort_order)
select r.id, s.id, m.ord
  from (values
    ('TICKET_HANDLER',    'ECOM_PORTAL_CHECK',    20),
    ('INWARD_VERIFIER',   'ECOM_UNBOXING',        50),
    ('INWARD_VERIFIER',   'ECOM_ACTION_SHEETS',   55),
    ('INWARD_VERIFIER',   'ECOM_RETURNS',        130),
    ('ISTORE_OP',         'ECOM_STORE_RECEIPTS',  50),
    ('ISTORE_DT',         'ECOM_STORE_RECEIPTS',  50),
    ('ISTORE_RI',         'ECOM_STORE_RECEIPTS',  50),
    ('ECOM_ACCOUNTS',     'ECOM_ACTION_SHEETS',   10),
    ('ECOM_ACCOUNTS',     'ECOM_RETURNS',        100),
    ('MANAGEMENT',        'ECOM_ACTION_SHEETS',  155),
    ('MANAGEMENT_VIEWER', 'ECOM_ACTION_SHEETS',  155)
  ) as m(role_code, step_code, ord)
  join public.roles r on r.code = m.role_code
  join public.journey_steps s on s.code = m.step_code
on conflict (role_id, journey_step_id) do nothing;

-- 4. Report
do $$
declare
  v_menus integer;
begin
  select count(*) into v_menus from public.role_journey_steps rjs
    join public.journey_steps s on s.id = rjs.journey_step_id
   where s.code in ('ECOM_PORTAL_CHECK', 'ECOM_UNBOXING', 'ECOM_STORE_RECEIPTS', 'ECOM_ACTION_SHEETS');
  raise notice 'DEC-76: role ECOM_ACCOUNTS present: %; % settlement menu entries',
    exists (select 1 from public.roles where code = 'ECOM_ACCOUNTS'), v_menus;
end
$$;

commit;
