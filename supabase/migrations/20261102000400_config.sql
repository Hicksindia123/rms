-- P1-02 · 0004 — configuration (master plan §8.3).
-- Option sets/items (workbook catalogue §3.2), versioned forms and workflow, numbering,
-- settings, print templates, report column prefs and the insert-only config change log.
-- G-18: published form / workflow / template versions are immutable (triggers below).

-- ===========================================================================
-- Option sets & items (CLAUDE.md rule e: logic keys off immutable CODES)
-- ===========================================================================
create table public.option_sets (
  id               uuid primary key default gen_random_uuid(),
  code             text not null unique check (code ~ '^[A-Z][A-Z0-9_]*$'),
  name             text not null check (btrim(name) <> ''),   -- workbook "Field / Attribute Name"
  description      text,
  control_type     text not null default 'dropdown'
                   check (control_type in ('dropdown','radio','checkbox','file','multiselect')),
  -- STATIC: options are the option_items rows. MASTER: runtime values come from a master
  -- (e.g. technicians); option_items keep the workbook reference rows (see DECISIONS.md).
  source_kind      text not null default 'STATIC' check (source_kind in ('STATIC','MASTER')),
  master_ref_type  text,
  source_ref       text,          -- e.g. 'DD r21–r28'
  is_system        boolean not null default false,
  is_active        boolean not null default true,
  created_at       timestamptz not null default now(),
  created_by       uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at       timestamptz not null default now(),
  check (source_kind <> 'MASTER' or master_ref_type is not null)
);
comment on table public.option_sets is 'Dropdown / radio / checkbox option sets (master plan §3.2, §8.3).';

create table public.option_items (
  id               uuid primary key default gen_random_uuid(),
  option_set_id    uuid not null references public.option_sets (id) on delete restrict,
  code             text not null check (code ~ '^[A-Z][A-Z0-9_]*$'),
  label            text not null check (btrim(label) <> ''),
  allowed_status   text not null default 'YES' check (allowed_status in ('YES','NO','CONDITIONAL')),
  rule_text        text,
  next_action_text text,
  remarks          text,
  system_behavior  text check (system_behavior in (
                     'SELLABLE','REPACK_OR_TECHNICIAN','TO_TECHNICIAN','TO_SPARE_PARTS',
                     'REJECT_HOLD','REJECT_RECORD','HAZARD','SHORT_QTY')),
  required_fields  jsonb not null default '[]'::jsonb check (jsonb_typeof(required_fields) = 'array'),
  sort_order       integer not null default 0,
  is_active        boolean not null default true,
  source_ref       text,          -- e.g. 'DD r23', 'WF r6'
  created_at       timestamptz not null default now(),
  created_by       uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at       timestamptz not null default now(),
  unique (option_set_id, code)
);
create index option_items_set_sort_idx on public.option_items (option_set_id, sort_order);
comment on column public.option_items.code is
  'Stable system code. Immutable (trigger option_codes_immutable); labels may be edited.';

-- Codes are immutable (CLAUDE.md rule e; §8.3). Hazard behaviour is locked (§10 Option sets).
create or replace function rms_private.option_codes_immutable()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.code is distinct from old.code then
    raise exception 'Option code % is immutable', old.code using errcode = '42501';
  end if;
  if tg_table_name = 'option_items' then
    if new.option_set_id is distinct from old.option_set_id then
      raise exception 'Option item % cannot move to another option set', old.code using errcode = '42501';
    end if;
    if old.system_behavior = 'HAZARD' and new.system_behavior is distinct from old.system_behavior then
      raise exception 'Hazard behaviour of option % is locked (G-05)', old.code using errcode = '42501';
    end if;
  end if;
  return new;
end
$$;
revoke all on function rms_private.option_codes_immutable() from public;

create trigger option_sets_codes_immutable
  before update on public.option_sets
  for each row execute function rms_private.option_codes_immutable();
create trigger option_items_codes_immutable
  before update on public.option_items
  for each row execute function rms_private.option_codes_immutable();

alter table public.product_categories
  add constraint product_categories_condition_option_set_id_fkey
  foreign key (condition_option_set_id) references public.option_sets (id) on delete restrict;

-- ===========================================================================
-- Forms (versioned; G-18)
-- ===========================================================================
create table public.form_definitions (
  id          uuid primary key default gen_random_uuid(),
  code        text not null unique check (code ~ '^[A-Z][A-Z0-9_]*$'),
  step_code   text check (step_code ~ '^[A-Z][A-Z0-9_]*$'),
  name        text not null check (btrim(name) <> ''),
  is_active   boolean not null default true,
  created_at  timestamptz not null default now(),
  created_by  uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at  timestamptz not null default now()
);

create table public.form_versions (
  id                  uuid primary key default gen_random_uuid(),
  form_definition_id  uuid not null references public.form_definitions (id) on delete restrict,
  version_no          integer not null check (version_no > 0),
  status              text not null default 'DRAFT' check (status in ('DRAFT','PUBLISHED','RETIRED')),
  snapshot            jsonb,
  published_by        uuid references public.profiles (id) on delete restrict,
  published_at        timestamptz,
  created_at          timestamptz not null default now(),
  created_by          uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at          timestamptz not null default now(),
  unique (form_definition_id, version_no),
  check (status = 'DRAFT' or (snapshot is not null and published_at is not null))
);
create unique index form_versions_one_published_idx
  on public.form_versions (form_definition_id) where status = 'PUBLISHED';

create table public.form_fields (
  id               uuid primary key default gen_random_uuid(),
  form_version_id  uuid not null references public.form_versions (id) on delete restrict,
  field_key        text not null check (field_key ~ '^[a-z][a-z0-9_]*$'),
  label            text not null check (btrim(label) <> ''),
  control_type     text not null check (control_type in (
                     'text','number','date','dropdown','radio','checkbox','multiselect','file',
                     'textarea','master_ref')),
  option_set_id    uuid references public.option_sets (id) on delete restrict,
  master_ref_type  text,
  is_required      boolean not null default false,
  visible_when     jsonb,
  required_when    jsonb,
  validation       jsonb,
  default_value    jsonb,
  sort_order       integer not null default 0,
  section          text,
  help_text        text,
  is_core          boolean not null default false,   -- bound to a typed column; relabel only
  is_system_locked boolean not null default false,
  created_at       timestamptz not null default now(),
  created_by       uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at       timestamptz not null default now(),
  unique (form_version_id, field_key),
  check (control_type not in ('dropdown','radio','multiselect') or option_set_id is not null),
  check (control_type <> 'master_ref' or master_ref_type is not null)
);

create table public.form_responses (
  id               uuid primary key default gen_random_uuid(),
  entity_type      text not null check (btrim(entity_type) <> ''),
  entity_id        uuid not null,
  form_version_id  uuid not null references public.form_versions (id) on delete restrict,  -- G-18
  "values"         jsonb not null default '{}'::jsonb check (jsonb_typeof("values") = 'object'),
  labels_snapshot  jsonb not null default '{}'::jsonb,
  submitted_by     uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  submitted_at     timestamptz not null default now(),
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create index form_responses_entity_idx on public.form_responses (entity_type, entity_id);
create index form_responses_version_idx on public.form_responses (form_version_id);

-- ===========================================================================
-- Workflow (versioned; G-18). DEC-32: internal step codes S2_HANDOVER / S3_TECHNICAL.
-- ===========================================================================
create table public.workflow_definitions (
  id          uuid primary key default gen_random_uuid(),
  code        text not null unique check (code ~ '^[A-Z][A-Z0-9_]*$'),
  name        text not null check (btrim(name) <> ''),
  is_active   boolean not null default true,
  created_at  timestamptz not null default now(),
  created_by  uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at  timestamptz not null default now()
);

create table public.workflow_versions (
  id                      uuid primary key default gen_random_uuid(),
  workflow_definition_id  uuid not null references public.workflow_definitions (id) on delete restrict,
  version_no              integer not null check (version_no > 0),
  status                  text not null default 'DRAFT' check (status in ('DRAFT','PUBLISHED','RETIRED')),
  snapshot                jsonb,
  published_by            uuid references public.profiles (id) on delete restrict,
  published_at            timestamptz,
  created_at              timestamptz not null default now(),
  created_by              uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at              timestamptz not null default now(),
  unique (workflow_definition_id, version_no),
  check (status = 'DRAFT' or (snapshot is not null and published_at is not null))
);
create unique index workflow_versions_one_published_idx
  on public.workflow_versions (workflow_definition_id) where status = 'PUBLISHED';

create table public.workflow_stages (
  id                   uuid primary key default gen_random_uuid(),
  workflow_version_id  uuid not null references public.workflow_versions (id) on delete restrict,
  code                 text not null check (code ~ '^[A-Z][A-Z0-9_]*$'),
  label                text not null check (btrim(label) <> ''),
  sort_order           integer not null default 0,
  created_at           timestamptz not null default now(),
  created_by           uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at           timestamptz not null default now(),
  unique (workflow_version_id, code),
  unique (id, workflow_version_id)
);

create table public.workflow_steps (
  id                   uuid primary key default gen_random_uuid(),
  workflow_version_id  uuid not null references public.workflow_versions (id) on delete restrict,
  stage_id             uuid not null,
  code                 text not null check (code in (
                         'S1_GATE','S1_UNBOX','S1_ITEMIZE','S1_CSR_APPROVAL','S1_INSPECT',
                         'S1A_RM_ACTION','S2_HANDOVER','S3_TECHNICAL','S4_DISMANTLE','S5_SEGREGATE',
                         'S6_STORE_ISSUE','S6_CN_DECISION','S6_ACCOUNTS_CN','S6_NOTIFY','S6_CLOSE')),
  label                text not null check (btrim(label) <> ''),
  form_definition_id   uuid references public.form_definitions (id) on delete restrict,
  sla_hours            numeric(8,2) check (sla_hours is null or sla_hours > 0),
  requires_approval    boolean not null default false,
  is_active            boolean not null default true,
  sort_order           integer not null default 0,
  created_at           timestamptz not null default now(),
  created_by           uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at           timestamptz not null default now(),
  unique (workflow_version_id, code),
  unique (id, workflow_version_id),
  -- stage must belong to the same workflow version
  foreign key (stage_id, workflow_version_id)
    references public.workflow_stages (id, workflow_version_id) on delete restrict
);

create table public.workflow_transitions (
  id                   uuid primary key default gen_random_uuid(),
  workflow_version_id  uuid not null references public.workflow_versions (id) on delete restrict,
  from_step_id         uuid not null,
  to_step_id           uuid not null,
  condition            jsonb,
  -- guard codes from §4.2 (G-01..G-18); configuration can reference, never remove them
  system_guards        text[] not null default '{}'
                       check (system_guards <@ array['G-01','G-02','G-03','G-04','G-05','G-06',
                         'G-07','G-08','G-09','G-10','G-11','G-12','G-13','G-14','G-15','G-16',
                         'G-17','G-18']::text[]),
  priority             integer not null default 0,
  created_at           timestamptz not null default now(),
  created_by           uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at           timestamptz not null default now(),
  foreign key (from_step_id, workflow_version_id)
    references public.workflow_steps (id, workflow_version_id) on delete restrict,
  foreign key (to_step_id, workflow_version_id)
    references public.workflow_steps (id, workflow_version_id) on delete restrict,
  check (from_step_id <> to_step_id)
);

create table public.step_assignments (
  id                uuid primary key default gen_random_uuid(),
  workflow_step_id  uuid not null references public.workflow_steps (id) on delete restrict,
  role_id           uuid references public.roles (id) on delete restrict,
  user_id           uuid references public.profiles (id) on delete restrict,
  assignment_type   text not null check (assignment_type in ('PERFORM','APPROVE','VIEW')),
  created_at        timestamptz not null default now(),
  created_by        uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at        timestamptz not null default now(),
  check (num_nonnulls(role_id, user_id) = 1)
);
create unique index step_assignments_role_uq
  on public.step_assignments (workflow_step_id, role_id, assignment_type) where role_id is not null;
create unique index step_assignments_user_uq
  on public.step_assignments (workflow_step_id, user_id, assignment_type) where user_id is not null;

-- DEC-30: escalation rules are configurable but seeded disabled.
create table public.escalation_rules (
  id                uuid primary key default gen_random_uuid(),
  workflow_step_id  uuid not null references public.workflow_steps (id) on delete restrict,
  after_hours       numeric(8,2) not null check (after_hours > 0),
  notify_role_id    uuid references public.roles (id) on delete restrict,
  notify_user_id    uuid references public.profiles (id) on delete restrict,
  is_active         boolean not null default false,
  created_at        timestamptz not null default now(),
  created_by        uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at        timestamptz not null default now(),
  check (num_nonnulls(notify_role_id, notify_user_id) = 1)
);

-- ---------------------------------------------------------------------------
-- G-18 guards: published versions are immutable; children only change while DRAFT.
-- ---------------------------------------------------------------------------
create or replace function rms_private.guard_version_row()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then
    if old.status <> 'DRAFT' then
      raise exception 'G-18: % % v% is % and cannot be deleted',
        tg_table_name, old.id, old.version_no, old.status using errcode = '42501';
    end if;
    return old;
  end if;

  if tg_op = 'INSERT' then
    if new.status <> 'DRAFT' and (new.snapshot is null or new.published_at is null) then
      raise exception 'G-18: % must be published with a snapshot', tg_table_name using errcode = '23514';
    end if;
    return new;
  end if;

  -- UPDATE
  if old.status = 'RETIRED' then
    raise exception 'G-18: retired % v% is immutable', tg_table_name, old.version_no using errcode = '42501';
  end if;
  if old.status = 'PUBLISHED' then
    -- the only permitted change is retiring it
    if new.status <> 'RETIRED'
       or (to_jsonb(new) - array['status','updated_at']) <> (to_jsonb(old) - array['status','updated_at']) then
      raise exception 'G-18: published % v% is immutable (only retiring is allowed)',
        tg_table_name, old.version_no using errcode = '42501';
    end if;
  end if;
  if old.status = 'DRAFT' and new.status = 'RETIRED' then
    raise exception 'G-18: a draft cannot be retired; delete it instead' using errcode = '23514';
  end if;
  return new;
end
$$;
revoke all on function rms_private.guard_version_row() from public;

create trigger form_versions_guard
  before insert or update or delete on public.form_versions
  for each row execute function rms_private.guard_version_row();
create trigger workflow_versions_guard
  before insert or update or delete on public.workflow_versions
  for each row execute function rms_private.guard_version_row();

-- Child rows of a version: TG_ARGV[0] = parent kind ('form' | 'workflow' | 'workflow_step').
create or replace function rms_private.guard_version_child()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_row       jsonb := to_jsonb(coalesce(new, old));
  v_old_row   jsonb := case when tg_op = 'UPDATE' then to_jsonb(old) end;
  v_status    text;
  v_old_status text;
begin
  if tg_argv[0] = 'form' then
    select status into v_status from public.form_versions where id = (v_row ->> 'form_version_id')::uuid;
    if v_old_row is not null then
      select status into v_old_status from public.form_versions where id = (v_old_row ->> 'form_version_id')::uuid;
    end if;
  elsif tg_argv[0] = 'workflow' then
    select status into v_status from public.workflow_versions where id = (v_row ->> 'workflow_version_id')::uuid;
    if v_old_row is not null then
      select status into v_old_status from public.workflow_versions where id = (v_old_row ->> 'workflow_version_id')::uuid;
    end if;
  elsif tg_argv[0] = 'workflow_step' then
    select wv.status into v_status
      from public.workflow_steps ws join public.workflow_versions wv on wv.id = ws.workflow_version_id
     where ws.id = (v_row ->> 'workflow_step_id')::uuid;
    if v_old_row is not null then
      select wv.status into v_old_status
        from public.workflow_steps ws join public.workflow_versions wv on wv.id = ws.workflow_version_id
       where ws.id = (v_old_row ->> 'workflow_step_id')::uuid;
    end if;
  else
    raise exception 'guard_version_child: unknown parent kind %', tg_argv[0];
  end if;

  if coalesce(v_status, 'DRAFT') <> 'DRAFT' or coalesce(v_old_status, 'DRAFT') <> 'DRAFT' then
    raise exception 'G-18: % belongs to a % version and cannot be changed',
      tg_table_name, coalesce(nullif(v_status, 'DRAFT'), v_old_status) using errcode = '42501';
  end if;
  return coalesce(new, old);
end
$$;
revoke all on function rms_private.guard_version_child() from public;

create trigger form_fields_guard
  before insert or update or delete on public.form_fields
  for each row execute function rms_private.guard_version_child('form');
create trigger workflow_stages_guard
  before insert or update or delete on public.workflow_stages
  for each row execute function rms_private.guard_version_child('workflow');
create trigger workflow_steps_guard
  before insert or update or delete on public.workflow_steps
  for each row execute function rms_private.guard_version_child('workflow');
create trigger workflow_transitions_guard
  before insert or update or delete on public.workflow_transitions
  for each row execute function rms_private.guard_version_child('workflow');
create trigger step_assignments_guard
  before insert or update or delete on public.step_assignments
  for each row execute function rms_private.guard_version_child('workflow_step');

-- G-18: responses are always recorded against a PUBLISHED form version.
create or replace function rms_private.form_responses_require_published()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'UPDATE' and new.form_version_id is not distinct from old.form_version_id then
    return new;
  end if;
  if not exists (select 1 from public.form_versions
                  where id = new.form_version_id and status = 'PUBLISHED') then
    raise exception 'G-18: form responses must reference a PUBLISHED form version'
      using errcode = '23514';
  end if;
  return new;
end
$$;
revoke all on function rms_private.form_responses_require_published() from public;

create trigger form_responses_require_published
  before insert or update of form_version_id on public.form_responses
  for each row execute function rms_private.form_responses_require_published();

-- ===========================================================================
-- Numbering (DEC-01)
-- ===========================================================================
create table public.number_series (
  id              uuid primary key default gen_random_uuid(),
  code            text not null unique check (code ~ '^[A-Z][A-Z0-9_]*$'),
  name            text not null check (btrim(name) <> ''),
  prefix          text,
  -- tokens: {PREFIX} {FY} {YYYY} {YY} {MM} {SEQ} {SEQ:n}; exactly the listed tokens are allowed
  pattern         text not null
                  check (pattern ~ '\{SEQ(:[1-9][0-9]?)?\}'
                     and regexp_replace(pattern, '\{(PREFIX|FY|YYYY|YY|MM|SEQ(:[1-9][0-9]?)?)\}', '', 'g') !~ '[{}]'),
  reset_policy    text not null default 'YEARLY_FY' check (reset_policy in ('NEVER','YEARLY_FY','MONTHLY')),
  fy_start_month  smallint not null default 4 check (fy_start_month between 1 and 12),
  -- {FY} rendering: LONG = '2026-27', COMPACT = '2627', SHORT = '26-27'
  fy_format       text not null default 'LONG' check (fy_format in ('LONG','COMPACT','SHORT')),
  start_value     bigint not null default 1 check (start_value >= 1),
  is_active       boolean not null default true,
  created_at      timestamptz not null default now(),
  created_by      uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at      timestamptz not null default now()
);

create table public.number_series_counters (
  series_id   uuid not null references public.number_series (id) on delete restrict,
  period_key  text not null check (btrim(period_key) <> ''),
  last_value  bigint not null check (last_value >= 1),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  primary key (series_id, period_key)
);

-- rms_private.next_number: atomic per-period counter (INSERT … ON CONFLICT … DO UPDATE …
-- RETURNING takes the row lock, so concurrent callers get distinct, gap-free values within
-- the committed transactions). Runs inside the caller's transaction.
create or replace function rms_private.next_number(p_series_code text, p_on_date date default current_date)
returns text
language plpgsql
volatile
set search_path = ''
as $$
declare
  s          public.number_series%rowtype;
  v_year     integer;
  v_fy_start integer;
  v_fy       text;
  v_period   text;
  v_seq      bigint;
  v_pad      integer;
  v_out      text;
begin
  if p_on_date is null then
    raise exception 'next_number: on_date is required' using errcode = '22004';
  end if;

  select * into s from public.number_series where code = p_series_code;
  if not found then
    raise exception 'next_number: unknown number series %', p_series_code using errcode = 'P0002';
  end if;
  if not s.is_active then
    raise exception 'next_number: number series % is inactive', p_series_code using errcode = '55000';
  end if;

  v_year := extract(year from p_on_date)::integer;
  v_fy_start := case when extract(month from p_on_date)::integer >= s.fy_start_month
                     then v_year else v_year - 1 end;

  if s.fy_start_month = 1 then
    v_fy := v_fy_start::text;   -- calendar-year FY: a single year
  else
    v_fy := case s.fy_format
      when 'LONG'    then v_fy_start::text || '-' || lpad(((v_fy_start + 1) % 100)::text, 2, '0')
      when 'COMPACT' then lpad((v_fy_start % 100)::text, 2, '0') || lpad(((v_fy_start + 1) % 100)::text, 2, '0')
      when 'SHORT'   then lpad((v_fy_start % 100)::text, 2, '0') || '-' || lpad(((v_fy_start + 1) % 100)::text, 2, '0')
    end;
  end if;

  v_period := case s.reset_policy
    when 'NEVER'     then 'ALL'
    when 'YEARLY_FY' then 'FY' || v_fy_start::text
    when 'MONTHLY'   then to_char(p_on_date, 'YYYY-MM')
  end;

  insert into public.number_series_counters as c (series_id, period_key, last_value)
  values (s.id, v_period, s.start_value)
  on conflict (series_id, period_key)
  do update set last_value = c.last_value + 1, updated_at = now()
  returning c.last_value into v_seq;

  v_out := s.pattern;
  v_out := replace(v_out, '{PREFIX}', coalesce(s.prefix, ''));
  v_out := replace(v_out, '{FY}',     v_fy);
  v_out := replace(v_out, '{YYYY}',   to_char(p_on_date, 'YYYY'));
  v_out := replace(v_out, '{YY}',     to_char(p_on_date, 'YY'));
  v_out := replace(v_out, '{MM}',     to_char(p_on_date, 'MM'));
  v_pad := (regexp_match(v_out, '\{SEQ:([0-9]+)\}'))[1]::integer;
  if v_pad is not null then
    -- never truncate: a value longer than the padding is rendered in full
    v_out := regexp_replace(v_out, '\{SEQ:[0-9]+\}',
               case when length(v_seq::text) >= v_pad then v_seq::text
                    else lpad(v_seq::text, v_pad, '0') end, 'g');
  end if;
  v_out := replace(v_out, '{SEQ}', v_seq::text);
  return v_out;
end
$$;
revoke all on function rms_private.next_number(text, date) from public;
grant execute on function rms_private.next_number(text, date) to rms_api;

-- ===========================================================================
-- Settings, templates, report prefs, config change log
-- ===========================================================================
create table public.system_settings (
  id           uuid primary key default gen_random_uuid(),
  key          text not null unique check (key ~ '^[a-z][a-z0-9_.]*$'),
  value        jsonb not null,
  category     text not null default 'general',
  description  text,
  source_ref   text,                -- e.g. 'DEC-12'
  is_secret    boolean not null default false check (is_secret = false),   -- never store secrets
  created_at   timestamptz not null default now(),
  created_by   uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at   timestamptz not null default now()
);

create table public.print_templates (
  id            uuid primary key default gen_random_uuid(),
  code          text not null check (code in ('REPLACEMENT_SLIP','GS_TAG','CN_SUMMARY','TRANSFER_NOTE','STORE_ISSUE')),
  name          text not null check (btrim(name) <> ''),
  version_no    integer not null check (version_no > 0),
  layout        jsonb not null default '{}'::jsonb,
  status        text not null default 'DRAFT' check (status in ('DRAFT','PUBLISHED','RETIRED')),
  snapshot      jsonb,
  published_by  uuid references public.profiles (id) on delete restrict,
  published_at  timestamptz,
  created_at    timestamptz not null default now(),
  created_by    uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at    timestamptz not null default now(),
  unique (code, version_no),
  check (status = 'DRAFT' or (snapshot is not null and published_at is not null))
);
create unique index print_templates_one_published_idx
  on public.print_templates (code) where status = 'PUBLISHED';
create trigger print_templates_guard
  before insert or update or delete on public.print_templates
  for each row execute function rms_private.guard_version_row();

create table public.report_column_prefs (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid references public.profiles (id) on delete restrict,
  role_id      uuid references public.roles (id) on delete restrict,
  report_code  text not null check (btrim(report_code) <> ''),
  columns      jsonb not null check (jsonb_typeof(columns) = 'array'),
  created_at   timestamptz not null default now(),
  created_by   uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at   timestamptz not null default now(),
  check (num_nonnulls(user_id, role_id) = 1)
);
create unique index report_column_prefs_user_uq
  on public.report_column_prefs (user_id, report_code) where user_id is not null;
create unique index report_column_prefs_role_uq
  on public.report_column_prefs (role_id, report_code) where role_id is not null;

-- Insert-only (G-17). Written by the backend on every configuration save (§10).
create table public.config_change_log (
  id           bigint generated always as identity primary key,
  entity_type  text not null check (btrim(entity_type) <> ''),
  entity_id    text,
  action       text not null check (btrim(action) <> ''),
  before       jsonb,
  after        jsonb,
  reason       text,
  changed_by   uuid default rms_private.current_actor(),
  request_id   text default rms_private.current_request_id(),
  changed_at   timestamptz not null default now()
);
create index config_change_log_entity_idx on public.config_change_log (entity_type, entity_id);
create index config_change_log_changed_at_idx on public.config_change_log (changed_at);

create trigger config_change_log_insert_only
  before update or delete on public.config_change_log
  for each row execute function rms_private.raise_insert_only();
create trigger config_change_log_no_truncate
  before truncate on public.config_change_log
  for each statement execute function rms_private.raise_insert_only();
