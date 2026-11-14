-- Migration: 20261102000800_p1_07_config_guards.sql
-- Description: G-05 hazard option status protection and option usage counter function.

-- 1. System guard G-05: Hazard options cannot be set to allowed_status = 'YES'.
create or replace function rms_private.guard_hazard_option_status()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if (new.system_behavior = 'HAZARD' or (tg_op = 'UPDATE' and old.system_behavior = 'HAZARD'))
     and new.allowed_status = 'YES' then
    raise exception 'G-05: Options with system_behavior=HAZARD cannot be changed to YES' using errcode = '42501';
  end if;
  return new;
end;
$$;
revoke all on function rms_private.guard_hazard_option_status() from public;

drop trigger if exists option_items_guard_hazard_status on public.option_items;
create trigger option_items_guard_hazard_status
  before insert or update on public.option_items
  for each row execute function rms_private.guard_hazard_option_status();

-- 2. Option usage counter function: counts references in form_responses.
create or replace function rms_private.count_option_usage(p_code text)
returns integer
language plpgsql
stable
set search_path = ''
as $$
declare
  v_count integer := 0;
begin
  if p_code is null or btrim(p_code) = '' then
    return 0;
  end if;

  select count(*)::integer into v_count
    from public.form_responses
   where "values"::text ~ ('\m' || p_code || '\M');

  return v_count;
end;
$$;
revoke all on function rms_private.count_option_usage(text) from public;
grant execute on function rms_private.count_option_usage(text) to rms_api;
