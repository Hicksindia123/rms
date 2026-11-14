-- P1-02 · 0005 — cross-cutting: notifications, audit log, idempotency (master plan §8.7),
-- the generic audit trigger (G-17) and the trigger-attachment helper used by every later
-- migration that adds a business table.

-- ===========================================================================
-- Notifications (Realtime-enabled in the RLS migration)
-- ===========================================================================
create table public.notifications (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references public.profiles (id) on delete restrict,
  type         text not null check (btrim(type) <> ''),
  title        text not null check (btrim(title) <> ''),
  body         text,
  entity_type  text,
  entity_id    uuid,
  priority     text not null default 'NORMAL' check (priority in ('LOW','NORMAL','HIGH')),
  read_at      timestamptz,
  created_at   timestamptz not null default now(),
  created_by   uuid default rms_private.current_actor() references public.profiles (id) on delete restrict
);
create index notifications_user_unread_idx on public.notifications (user_id, created_at desc) where read_at is null;
create index notifications_user_created_idx on public.notifications (user_id, created_at desc);

create table public.notification_preferences (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null references public.profiles (id) on delete restrict,
  notification_type  text not null check (btrim(notification_type) <> ''),
  channel            text not null check (channel in ('IN_APP','EMAIL')),
  is_enabled         boolean not null default true,
  created_at         timestamptz not null default now(),
  created_by         uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at         timestamptz not null default now(),
  unique (user_id, notification_type, channel)
);

-- ===========================================================================
-- Audit log (insert-only; G-17)
-- ===========================================================================
create table public.audit_log (
  id              bigint generated always as identity primary key,
  table_name      text not null,
  row_id          text,
  action          text not null check (action in ('INSERT','UPDATE','DELETE')),
  "old"           jsonb,
  "new"           jsonb,
  changed_fields  text[],
  actor_id        uuid,            -- current_setting('app.user_id'); null = system / migration / seed
  request_id      text,            -- current_setting('app.request_id')
  db_user         text not null default current_user,
  at              timestamptz not null default now()
);
create index audit_log_table_row_idx on public.audit_log (table_name, row_id);
create index audit_log_actor_idx on public.audit_log (actor_id, at desc);
create index audit_log_at_idx on public.audit_log (at);
create index audit_log_request_idx on public.audit_log (request_id) where request_id is not null;

create trigger audit_log_insert_only
  before update or delete on public.audit_log
  for each row execute function rms_private.raise_insert_only();
create trigger audit_log_no_truncate
  before truncate on public.audit_log
  for each statement execute function rms_private.raise_insert_only();

-- Generic row audit. TG_ARGV = primary-key column names (default: 'id').
-- SECURITY DEFINER so that any writer (rms_api, or `authenticated` marking a notification
-- read) records history without holding INSERT on audit_log itself.
create or replace function rms_private.audit_row()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_old     jsonb;
  v_new     jsonb;
  v_row     jsonb;
  v_row_id  text;
  v_changed text[];
begin
  if tg_op in ('UPDATE','DELETE') then v_old := to_jsonb(old); end if;
  if tg_op in ('INSERT','UPDATE') then v_new := to_jsonb(new); end if;
  v_row := coalesce(v_new, v_old);

  if tg_nargs = 0 then
    v_row_id := v_row ->> 'id';
  else
    select string_agg(coalesce(v_row ->> a.col, ''), ':' order by a.ord)
      into v_row_id
      from unnest(tg_argv) with ordinality as a(col, ord);
  end if;

  if tg_op = 'UPDATE' then
    select array_agg(n.key order by n.key)
      into v_changed
      from jsonb_each(v_new) n
     where n.key <> 'updated_at'
       and n.value is distinct from (v_old -> n.key);
    if v_changed is null then
      return null;   -- nothing but updated_at changed: no audit row
    end if;
  end if;

  insert into public.audit_log (table_name, row_id, action, "old", "new", changed_fields, actor_id, request_id)
  values (tg_table_schema || '.' || tg_table_name, v_row_id, tg_op, v_old, v_new, v_changed,
          rms_private.current_actor(), rms_private.current_request_id());
  return null;
end
$$;
revoke all on function rms_private.audit_row() from public;

-- ===========================================================================
-- Idempotency keys (G-16). Lives in rms_private: never exposed through the Data API.
-- ===========================================================================
create table rms_private.idempotency_keys (
  key              text primary key check (length(key) between 8 and 200),
  user_id          uuid references public.profiles (id) on delete restrict,
  endpoint         text not null,
  request_hash     text not null,
  response_status  integer,
  response_body    jsonb,
  created_at       timestamptz not null default now()
);
create index idempotency_keys_created_at_idx on rms_private.idempotency_keys (created_at);  -- TTL cleanup

-- ===========================================================================
-- Trigger attachment helper. Every later migration that creates a table calls:
--   select rms_private.attach_standard_triggers('public.my_table');
-- It adds set_updated_at (when the table has updated_at) and the audit trigger (G-17).
-- ===========================================================================
create or replace function rms_private.attach_standard_triggers(
  p_table regclass,
  p_audit boolean default true
)
returns void
language plpgsql
set search_path = ''
as $$
declare
  v_pk   text[];
  v_args text;
begin
  if exists (select 1 from pg_attribute
              where attrelid = p_table and attname = 'updated_at' and not attisdropped) then
    execute format('drop trigger if exists set_updated_at on %s', p_table);
    execute format('create trigger set_updated_at before update on %s '
                   'for each row execute function rms_private.set_updated_at()', p_table);
  end if;

  if p_audit then
    select array_agg(a.attname::text order by k.ord)
      into v_pk
      from pg_index i
      cross join lateral unnest(i.indkey::int2[]) with ordinality as k(attnum, ord)
      join pg_attribute a on a.attrelid = i.indrelid and a.attnum = k.attnum
     where i.indrelid = p_table and i.indisprimary;

    if v_pk is null or v_pk = array['id'] then
      v_args := '';
    else
      select string_agg(quote_literal(x), ', ') into v_args from unnest(v_pk) as x;
    end if;

    execute format('drop trigger if exists audit_row on %s', p_table);
    execute format('create trigger audit_row after insert or update or delete on %s '
                   'for each row execute function rms_private.audit_row(%s)', p_table, v_args);
  end if;
end
$$;
revoke all on function rms_private.attach_standard_triggers(regclass, boolean) from public;

-- Attach to every public table created so far.
-- Not audited: the logs themselves, and number_series_counters (bookkeeping; every generated
-- number is audited through the business row that stores it).
do $$
declare
  t record;
begin
  for t in
    select c.oid::regclass as tbl, c.relname
      from pg_class c join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relkind = 'r'
     order by c.relname
  loop
    perform rms_private.attach_standard_triggers(
      t.tbl,
      t.relname not in ('audit_log','config_change_log','number_series_counters'));
  end loop;
end
$$;
