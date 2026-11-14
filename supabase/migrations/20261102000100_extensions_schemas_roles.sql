-- P1-02 · 0001 — extensions, schemas, backend DB role, shared helper functions.
-- Master plan §8 (conventions), §9.4 (rms_api role), CLAUDE.md rule d.
-- No secrets in this file: rms_api is created WITHOUT a password. The password is set by a
-- documented local-only step (docs/SETUP.md, "rms_api role").

-- ---------------------------------------------------------------------------
-- Extensions (Supabase keeps extensions in the `extensions` schema)
-- ---------------------------------------------------------------------------
create extension if not exists pgcrypto with schema extensions;
create extension if not exists citext   with schema extensions;   -- case-insensitive emails
create extension if not exists pg_trgm  with schema extensions;   -- fuzzy search (P4-04)

-- ---------------------------------------------------------------------------
-- Private schema: functions, idempotency. Not exposed through the Data API
-- (supabase/config.toml [api].schemas lists only public + graphql_public).
-- ---------------------------------------------------------------------------
create schema if not exists rms_private;
revoke all on schema rms_private from public;
revoke all on schema rms_private from anon, authenticated;

-- ---------------------------------------------------------------------------
-- Backend role (master plan §9.4). LOGIN + BYPASSRLS; the backend is the only writer.
-- Idempotent: roles are cluster-wide and can survive a database reset.
-- ---------------------------------------------------------------------------
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'rms_api') then
    create role rms_api with login bypassrls noinherit nocreatedb nocreaterole;
  else
    alter role rms_api with login bypassrls;
  end if;
end
$$;

comment on role rms_api is
  'RMS FastAPI backend role (master plan §9.4). Password set out-of-band; see docs/SETUP.md.';

grant usage on schema public, rms_private, extensions to rms_api;

-- Objects created later by the migration owner are automatically usable by rms_api.
alter default privileges in schema public
  grant select, insert, update, delete on tables to rms_api;
alter default privileges in schema public
  grant usage, select on sequences to rms_api;
alter default privileges in schema public
  grant execute on functions to rms_api;
alter default privileges in schema rms_private
  grant select, insert, update, delete on tables to rms_api;
alter default privileges in schema rms_private
  grant usage, select on sequences to rms_api;
alter default privileges in schema rms_private
  grant execute on functions to rms_api;

-- Supabase grants anon/authenticated everything on new public objects by default.
-- RMS exposes no business data to them (§9.4): remove those defaults. Explicit grants
-- (notifications for Realtime) are added in the RLS migration.
alter default privileges in schema public revoke all on tables    from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;
alter default privileges in schema public revoke all on functions from anon, authenticated;
-- EXECUTE-to-PUBLIC is a global default (it cannot be revoked per schema), so every RMS
-- function revokes it explicitly below and in later migrations; supabase/tests asserts it.

-- ---------------------------------------------------------------------------
-- Request context helpers. The backend runs `SET LOCAL app.user_id = '<uuid>'` and
-- `SET LOCAL app.request_id = '<id>'` in each transaction (master plan §6.4).
-- ---------------------------------------------------------------------------
create or replace function rms_private.current_actor()
returns uuid
language plpgsql
stable
set search_path = ''
as $$
declare
  v text := nullif(current_setting('app.user_id', true), '');
begin
  if v is null then
    return null;
  end if;
  return v::uuid;
exception when invalid_text_representation then
  raise exception 'app.user_id is not a valid uuid: %', v
    using errcode = '22P02';
end
$$;

create or replace function rms_private.current_request_id()
returns text
language sql
stable
set search_path = ''
as $$
  select nullif(current_setting('app.request_id', true), '')
$$;

-- ---------------------------------------------------------------------------
-- updated_at maintenance (attached to every table that has updated_at)
-- ---------------------------------------------------------------------------
create or replace function rms_private.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end
$$;

-- Generic "this table is append-only" guard (audit_log, config_change_log; later
-- stock_movements). G-17: audit history cannot be altered.
create or replace function rms_private.raise_insert_only()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception '% on %.% is not allowed: table is insert-only (G-17)',
    tg_op, tg_table_schema, tg_table_name
    using errcode = '42501';
end
$$;

revoke all on function rms_private.current_actor()      from public;
revoke all on function rms_private.current_request_id() from public;
revoke all on function rms_private.set_updated_at()     from public;
revoke all on function rms_private.raise_insert_only()  from public;
grant execute on function rms_private.current_actor()      to rms_api;
grant execute on function rms_private.current_request_id() to rms_api;
