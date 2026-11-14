-- P1-02 · 0002 — identity & access (master plan §8.1, §9).
-- Conventions (§8): uuid PKs, created_at/created_by/updated_at, soft-deactivate via is_active,
-- FKs to referenced masters are ON DELETE RESTRICT.
-- created_by defaults to the acting user from `app.user_id` (set by the backend per transaction).

-- ---------------------------------------------------------------------------
-- departments (DEC-20)
-- ---------------------------------------------------------------------------
create table public.departments (
  id          uuid primary key default gen_random_uuid(),
  code        text not null unique check (code ~ '^[A-Z][A-Z0-9_]*$'),
  name        text not null check (btrim(name) <> ''),
  is_active   boolean not null default true,
  created_at  timestamptz not null default now(),
  created_by  uuid default rms_private.current_actor(),
  updated_at  timestamptz not null default now()
);
comment on table public.departments is 'Departments (master plan §8.1, DEC-20).';

-- ---------------------------------------------------------------------------
-- profiles: 1:1 with auth.users. Deleting an auth user that has a profile is blocked
-- (RESTRICT): users are deactivated, never hard-deleted, so audit history stays intact.
-- ---------------------------------------------------------------------------
create table public.profiles (
  id              uuid primary key references auth.users (id) on delete restrict,
  email           extensions.citext unique,
  employee_code   text unique check (employee_code is null or btrim(employee_code) <> ''),
  full_name       text not null check (btrim(full_name) <> ''),
  phone           text,
  department_id   uuid references public.departments (id) on delete restrict,
  is_active       boolean not null default false,
  is_super_admin  boolean not null default false,
  last_login_at   timestamptz,
  created_at      timestamptz not null default now(),
  created_by      uuid default rms_private.current_actor(),
  updated_at      timestamptz not null default now()
);
comment on table public.profiles is
  'User profile (master plan §8.1). is_super_admin is only settable by an active Super Admin.';
create index profiles_department_idx on public.profiles (department_id);

alter table public.profiles
  add constraint profiles_created_by_fkey foreign key (created_by)
  references public.profiles (id) on delete restrict;
alter table public.departments
  add constraint departments_created_by_fkey foreign key (created_by)
  references public.profiles (id) on delete restrict;

-- ---------------------------------------------------------------------------
-- roles / user_roles
-- ---------------------------------------------------------------------------
create table public.roles (
  id           uuid primary key default gen_random_uuid(),
  code         text not null unique check (code ~ '^[A-Z][A-Z0-9_]*$'),
  name         text not null check (btrim(name) <> ''),
  description  text,
  is_system    boolean not null default false,
  created_at   timestamptz not null default now(),
  created_by   uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at   timestamptz not null default now()
);
comment on table public.roles is 'Roles (master plan §3.3, §8.1). System roles cannot be deleted.';

create table public.user_roles (
  user_id     uuid not null references public.profiles (id) on delete restrict,
  role_id     uuid not null references public.roles (id) on delete restrict,
  created_at  timestamptz not null default now(),
  created_by  uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  primary key (user_id, role_id)
);
create index user_roles_role_idx on public.user_roles (role_id);

-- ---------------------------------------------------------------------------
-- permissions / role_permissions / user_permission_overrides
-- ---------------------------------------------------------------------------
create table public.permissions (
  id           uuid primary key default gen_random_uuid(),
  module_code  text not null check (module_code ~ '^[a-z][a-z0-9_]*$'),
  action       text not null
               check (action in ('view','create','edit','approve','delete','export','configure')),
  description  text,
  created_at   timestamptz not null default now(),
  unique (module_code, action)
);
comment on table public.permissions is 'Permission catalogue: module × action (master plan §6.2, §8.1).';

create table public.role_permissions (
  role_id        uuid not null references public.roles (id) on delete restrict,
  permission_id  uuid not null references public.permissions (id) on delete restrict,
  scope          text not null default 'all' check (scope in ('own','department','all')),
  created_at     timestamptz not null default now(),
  created_by     uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at     timestamptz not null default now(),
  primary key (role_id, permission_id)
);
create index role_permissions_permission_idx on public.role_permissions (permission_id);

create table public.user_permission_overrides (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references public.profiles (id) on delete restrict,
  permission_id  uuid not null references public.permissions (id) on delete restrict,
  effect         text not null check (effect in ('grant','deny')),
  reason         text not null check (btrim(reason) <> ''),
  expires_at     timestamptz,
  created_at     timestamptz not null default now(),
  created_by     uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at     timestamptz not null default now(),
  unique (user_id, permission_id)
);
create index user_permission_overrides_permission_idx on public.user_permission_overrides (permission_id);

-- ---------------------------------------------------------------------------
-- Guard: system roles cannot be deleted (§8.1).
-- ---------------------------------------------------------------------------
create or replace function rms_private.roles_protect_system()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'DELETE' and old.is_system then
    raise exception 'System role % cannot be deleted', old.code using errcode = '42501';
  end if;
  if tg_op = 'UPDATE' and old.is_system and (new.code <> old.code or not new.is_system) then
    raise exception 'System role % cannot be renamed or un-flagged', old.code using errcode = '42501';
  end if;
  return coalesce(new, old);
end
$$;
revoke all on function rms_private.roles_protect_system() from public;

create trigger roles_protect_system
  before update or delete on public.roles
  for each row execute function rms_private.roles_protect_system();

-- ---------------------------------------------------------------------------
-- Guard: profiles.is_super_admin is only settable by an active Super Admin (§8.1).
-- Exception: the very first Super Admin (no active Super Admin exists yet), which is the
-- bootstrap path used by backend/scripts/bootstrap_super_admin.py (P1-05).
-- ---------------------------------------------------------------------------
create or replace function rms_private.profiles_guard_super_admin()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor uuid := rms_private.current_actor();
  v_actor_is_sa boolean;
  v_any_active_sa boolean;
begin
  if tg_op = 'UPDATE' and new.is_super_admin is not distinct from old.is_super_admin then
    return new;
  end if;
  if tg_op = 'INSERT' and not new.is_super_admin then
    return new;
  end if;

  select exists (select 1 from public.profiles p where p.is_super_admin and p.is_active)
    into v_any_active_sa;
  if not v_any_active_sa then
    return new;   -- bootstrap of the first Super Admin
  end if;

  select coalesce(bool_and(p.is_super_admin and p.is_active), false)
    into v_actor_is_sa
    from public.profiles p
   where p.id = v_actor;

  if not v_actor_is_sa then
    raise exception 'is_super_admin can only be changed by an active Super Admin'
      using errcode = '42501';
  end if;
  return new;
end
$$;
revoke all on function rms_private.profiles_guard_super_admin() from public;

create trigger profiles_guard_super_admin
  before insert or update of is_super_admin on public.profiles
  for each row execute function rms_private.profiles_guard_super_admin();

-- ---------------------------------------------------------------------------
-- New auth user → profile row.
-- Choice (documented in docs/DECISIONS.md): the profile is INACTIVE by default. It is
-- created ACTIVE only when the user was created through the backend admin API, which sets
-- app_metadata.rms_activate = true. app_metadata is writable only with the service-role key
-- (backend), never by the end user. Public sign-up is disabled (config.toml).
-- ---------------------------------------------------------------------------
create or replace function rms_private.handle_new_auth_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, email, full_name, employee_code, phone, is_active)
  values (
    new.id,
    new.email,
    coalesce(nullif(btrim(new.raw_user_meta_data ->> 'full_name'), ''),
             nullif(btrim(new.email), ''),
             new.id::text),
    nullif(btrim(new.raw_user_meta_data ->> 'employee_code'), ''),
    coalesce(nullif(btrim(new.phone), ''), nullif(btrim(new.raw_user_meta_data ->> 'phone'), '')),
    coalesce((new.raw_app_meta_data ->> 'rms_activate')::boolean, false)
  )
  on conflict (id) do nothing;
  return new;
end
$$;
revoke all on function rms_private.handle_new_auth_user() from public;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function rms_private.handle_new_auth_user();

-- Keep profiles.email in sync when the auth email changes.
create or replace function rms_private.handle_auth_user_email_change()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  update public.profiles set email = new.email where id = new.id;
  return new;
end
$$;
revoke all on function rms_private.handle_auth_user_email_change() from public;

create trigger on_auth_user_email_changed
  after update of email on auth.users
  for each row
  when (old.email is distinct from new.email)
  execute function rms_private.handle_auth_user_email_change();
