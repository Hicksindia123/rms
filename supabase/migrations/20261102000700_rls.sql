-- P1-02 · 0007 — RLS baseline and grants (master plan §6.1 point 2, §9.4).
-- * RLS ENABLED on every public table (later migrations must do the same for new tables;
--   supabase/tests checks it).
-- * anon: no policies, no grants.
-- * authenticated: SELECT own notifications and UPDATE(read_at) on own notifications only.
-- * rms_api: full DML (BYPASSRLS); audit_log / config_change_log are insert-only.

do $$
declare
  t record;
begin
  for t in
    select c.oid::regclass as tbl
      from pg_class c join pg_namespace n on n.oid = c.relnamespace
     where n.nspname in ('public','rms_private') and c.relkind in ('r','p')
  loop
    execute format('alter table %s enable row level security', t.tbl);
  end loop;
end
$$;

-- ---------------------------------------------------------------------------
-- Grants
-- ---------------------------------------------------------------------------
revoke all on all tables    in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
revoke all on all functions in schema public from anon, authenticated;
revoke all on all tables    in schema rms_private from anon, authenticated, public;
revoke all on all functions in schema rms_private from anon, authenticated, public;

grant select, insert, update, delete on all tables    in schema public      to rms_api;
grant usage, select                  on all sequences in schema public      to rms_api;
grant select, insert, update, delete on all tables    in schema rms_private to rms_api;
grant execute on function rms_private.next_number(text, date)  to rms_api;
grant execute on function rms_private.current_actor()          to rms_api;
grant execute on function rms_private.current_request_id()     to rms_api;

-- Logs are append-only for everyone (G-17); the triggers also raise on UPDATE/DELETE/TRUNCATE.
revoke update, delete, truncate on public.audit_log         from rms_api, anon, authenticated, service_role;
revoke update, delete, truncate on public.config_change_log from rms_api, anon, authenticated, service_role;

-- Realtime notifications for signed-in users (own rows only, via policies below).
grant select on public.notifications to authenticated;
grant update (read_at) on public.notifications to authenticated;

-- ---------------------------------------------------------------------------
-- Policies
-- ---------------------------------------------------------------------------
create policy notifications_select_own
  on public.notifications
  for select
  to authenticated
  using (user_id = (select auth.uid()));

create policy notifications_update_own_read_at
  on public.notifications
  for update
  to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));

-- ---------------------------------------------------------------------------
-- Realtime
-- ---------------------------------------------------------------------------
do $$
begin
  if not exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    create publication supabase_realtime;
  end if;
  if not exists (select 1 from pg_publication_tables
                  where pubname = 'supabase_realtime'
                    and schemaname = 'public' and tablename = 'notifications') then
    alter publication supabase_realtime add table public.notifications;
  end if;
end
$$;
