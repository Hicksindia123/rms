-- Release 2026-11-24 - E-Commerce Returns (DEC-73): roles, grants and menus.
-- Gate Entry with Return Type = E-Commerce now records an E-Commerce Return (own number series
-- ECR/{FY}/{SEQ:5}) with a mandatory package-opening video; TICKET_RAISE returns are queued for the
-- Ticket Handlers (2-hour SLA), ISSUE_TO_CHECKING returns stay open In Checking.
--
-- Apply to production AFTER migration 20261124000100_ecommerce_returns.sql and after deploying the
-- backend + frontend. Idempotent; safe to re-run:
--   supabase db query --linked -f supabase/snippets/release_20261124_ecommerce_returns.sql
-- Same configuration as supabase/seed.sql.
begin;

-- 1. Roles (seed data, DEC-60 convention).
insert into public.roles (code, name, description, is_system) values
  ('ECOM_GATE',      'Gate User (E-Commerce)', 'DEC-73: records E-Commerce Returns at Gate Entry', true),
  ('TICKET_HANDLER', 'Ticket Handler',         'DEC-73: raises E-Commerce platform tickets and records the platform response', true)
on conflict (code) do nothing;

-- 2. Grants.
insert into public.role_permissions (role_id, permission_id, scope)
select r.id, p.id, 'all'
  from (values
    ('ECOM_GATE',         'dashboards',        'view'),
    ('ECOM_GATE',         'notifications',     'view'),
    ('ECOM_GATE',         'ecommerce_returns', 'view'),
    ('ECOM_GATE',         'ecommerce_returns', 'create'),
    ('TICKET_HANDLER',    'dashboards',        'view'),
    ('TICKET_HANDLER',    'notifications',     'view'),
    ('TICKET_HANDLER',    'ecommerce_returns', 'view'),
    ('TICKET_HANDLER',    'ecommerce_tickets', 'view'),
    ('TICKET_HANDLER',    'ecommerce_tickets', 'edit'),
    ('MANAGEMENT',        'ecommerce_returns', 'view'),
    ('MANAGEMENT',        'ecommerce_returns', 'delete'),
    ('MANAGEMENT',        'ecommerce_tickets', 'view'),
    ('MANAGEMENT_VIEWER', 'ecommerce_returns', 'view'),
    ('MANAGEMENT_VIEWER', 'ecommerce_tickets', 'view')
  ) as m(role_code, module_code, action)
  join public.roles r on r.code = m.role_code
  join public.permissions p on p.module_code = m.module_code and p.action = m.action
on conflict (role_id, permission_id) do nothing;

-- 3. Menus.
insert into public.role_journey_steps (role_id, journey_step_id, sort_order)
select r.id, s.id, m.ord
  from (values
    ('ECOM_GATE',         'ECOM_GATE_ENTRY', 10),
    ('ECOM_GATE',         'ECOM_RETURNS',   100),
    ('TICKET_HANDLER',    'ECOM_TICKETS',    10),
    ('TICKET_HANDLER',    'ECOM_RETURNS',   100),
    ('MANAGEMENT',        'ECOM_RETURNS',   150),
    ('MANAGEMENT_VIEWER', 'ECOM_RETURNS',   150)
  ) as m(role_code, step_code, ord)
  join public.roles r on r.code = m.role_code
  join public.journey_steps s on s.code = m.step_code
on conflict (role_id, journey_step_id) do nothing;

-- 4. Report
do $$
declare
  v_roles integer;
  v_menus integer;
begin
  select count(*) into v_roles from public.roles where code in ('ECOM_GATE', 'TICKET_HANDLER');
  select count(*) into v_menus from public.role_journey_steps rjs
    join public.journey_steps s on s.id = rjs.journey_step_id
   where s.code in ('ECOM_GATE_ENTRY', 'ECOM_TICKETS', 'ECOM_RETURNS');
  raise notice 'DEC-73: % of 2 roles present; % E-Commerce menu entries', v_roles, v_menus;
end
$$;

commit;
