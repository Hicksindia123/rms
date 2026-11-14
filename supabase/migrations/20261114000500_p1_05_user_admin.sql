-- P1-05 · User, role & permission administration (master plan prompt P1-05; production audit
-- 2026-11-14, finding B10). Defence-in-depth for the rules the users/roles services enforce first:
--
--   1. profiles.must_change_password: set by an admin "temporary password" reset; the user must
--      choose a new password before using the app (DEC-50).
--   2. Self-protection: a user cannot deactivate themselves or remove their own Super Admin flag.
--   3. Through the API (an actor is set) the last active Super Admin cannot be deactivated or
--      lose the flag.
--   4. Through the API (an actor is set) only an active Super Admin may add or remove the
--      SUPER_ADMIN marker role, which holds every permission. Maintenance scripts run without an
--      actor (bootstrap, uat_reset) and are not affected; profiles.is_super_admin keeps its own guard.
--
-- No existing object is altered except by `add column` / new triggers.

alter table public.profiles
  add column must_change_password boolean not null default false;

comment on column public.profiles.must_change_password is
  'Set when an admin issues a temporary password (P1-05, DEC-50); cleared after the user sets a new one.';

-- ---------------------------------------------------------------------------
-- 2 + 3: profile status / Super Admin flag protection
-- ---------------------------------------------------------------------------
create or replace function rms_private.profiles_protect_admin_state()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor uuid := rms_private.current_actor();
  v_was_active_sa boolean := old.is_active and old.is_super_admin;
  v_is_active_sa  boolean := new.is_active and new.is_super_admin;
begin
  if v_actor is not null and v_actor = new.id then
    if old.is_active and not new.is_active then
      raise exception 'P1-05: you cannot deactivate your own account' using errcode = '42501';
    end if;
    if old.is_super_admin and not new.is_super_admin then
      raise exception 'P1-05: you cannot remove your own Super Admin rights' using errcode = '42501';
    end if;
  end if;

  -- API path only: maintenance sessions (no actor) may reach the "no active Super Admin" state,
  -- which is the documented bootstrap path (profiles_guard_super_admin, bootstrap_super_admin.py).
  if v_actor is not null and v_was_active_sa and not v_is_active_sa
     and not exists (
       select 1 from public.profiles p
        where p.id <> new.id and p.is_active and p.is_super_admin
     ) then
    raise exception 'P1-05: the last active Super Admin cannot be deactivated or demoted'
      using errcode = '42501';
  end if;
  return new;
end
$$;
revoke all on function rms_private.profiles_protect_admin_state() from public;

create trigger profiles_protect_admin_state
  before update of is_active, is_super_admin on public.profiles
  for each row execute function rms_private.profiles_protect_admin_state();

-- ---------------------------------------------------------------------------
-- 4: SUPER_ADMIN marker role assignment
-- ---------------------------------------------------------------------------
create or replace function rms_private.user_roles_guard_super_admin_role()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor uuid := rms_private.current_actor();
  v_role_id uuid := coalesce(new.role_id, old.role_id);
begin
  if v_actor is null then
    return coalesce(new, old);   -- maintenance scripts / seeds (no API actor)
  end if;
  if not exists (select 1 from public.roles r where r.id = v_role_id and r.code = 'SUPER_ADMIN') then
    return coalesce(new, old);
  end if;
  if not exists (
    select 1 from public.profiles p where p.id = v_actor and p.is_active and p.is_super_admin
  ) then
    raise exception 'P1-05: only an active Super Admin can grant or revoke the SUPER_ADMIN role'
      using errcode = '42501';
  end if;
  return coalesce(new, old);
end
$$;
revoke all on function rms_private.user_roles_guard_super_admin_role() from public;

create trigger user_roles_guard_super_admin_role
  before insert or update or delete on public.user_roles
  for each row execute function rms_private.user_roles_guard_super_admin_role();
