-- =============================================================================================
-- Phase P5 (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-65 (Q10 user; Q20 PROVISIONAL; Q26 user).
-- Transfer slips: the Replacement Manager selects 1..N locked goods slips and generates ONE slip per
-- Intermediate Store that has lines on them (a GS spanning 3 stores is on 3 slips), or sends an
-- Edit Request to Management / Super Admin.
--
-- 1. Status TRANSFER_SLIP_GENERATED: every physical line of the GS is on a live slip. A void
--    (Q10: Admin / Management edit after the slips exist) brings the GS back to
--    PENDING_TRANSFER_SLIP; generation then covers only the lines that have no live slip.
-- 2. transfer_slips (GENERATED / ACKNOWLEDGED / VOIDED), transfer_slip_gs, transfer_slip_lines
--    (label snapshots, G-18). Append-only: lines and GS rows never change; a slip only changes
--    status. Each slip is backed by ONE custody transfer INWARD_STAGING → TRANSIT → the store's
--    location (G-09: stock enters TRANSIT only through a custody transfer; P0 finding F4). The
--    store acknowledges it in P6.
-- 3. gs_edit_requests: OPEN → EDITED / REJECTED. A GS with an OPEN request cannot go on a slip.
-- 4. Guards (DB half; the service repeats them): RM permission transfer_slips.create to generate
--    and to request edits; itemization.configure (Super Admin / Management) to void and to resolve
--    requests; a line goes only to the slip of its product's store (DEC-61) and on one live slip;
--    the GS reaches TRANSFER_SLIP_GENERATED only when every physical line is covered exactly;
--    post-lock edits (DEC-64 d) are refused while any live slip covers the GS.
-- 5. Number series TRANSFER_SLIP with a new {STORE} token (one counter per store and FY), print
--    template TRANSFER_SLIP (A4, logo on), the logo setting (Q26) and show_logo on for the
--    A/c Actions (Replacement) Slip and the Dispatch Slip (new published template versions).
-- 6. Permissions catalogue `transfer_slips`, journey catalogue entries TRANSFER_SLIPS /
--    EDIT_REQUESTS, notification event types. Grants, menus, rules and labels: seed.sql + the
--    release snippet (roles are seed data).
-- Legacy: goods_slips.transfer_slip_id (1 GS : 1 custody transfer, DEC-54) stays for old GSs.
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- 1. Status
-- ---------------------------------------------------------------------------------------------
alter table public.goods_slips drop constraint goods_slips_status_check;
alter table public.goods_slips
  add constraint goods_slips_status_check check (status in (
    'GATE_CREATED', 'UNBOXING', 'ITEMIZATION', 'CATEGORISATION', 'CSR_APPROVAL_PENDING',
    'INSPECTION', 'RM_REVIEW', 'PENDING_TRANSFER_SLIP', 'TRANSFER_SLIP_GENERATED',
    'SALES_RETURN_HOLD', 'HELD_AT_INTERMEDIATE_STORE', 'IN_PROCESS', 'COMMERCIAL_RESOLUTION',
    'AWAITING_NOTIFICATION', 'CLOSED', 'CANCELLED'));

-- ---------------------------------------------------------------------------------------------
-- 2. Number series: {STORE} token (DEC-65 "TRF/<store code>/<FY>/<seq>")
-- ---------------------------------------------------------------------------------------------
alter table public.number_series drop constraint if exists number_series_pattern_check;
alter table public.number_series
  add constraint number_series_pattern_check check (
    pattern ~ '\{SEQ(:[1-9][0-9]?)?\}'
    and regexp_replace(pattern, '\{(PREFIX|FY|YYYY|YY|MM|STORE|SEQ(:[1-9][0-9]?)?)\}', '', 'g') !~ '[{}]');

-- Scoped variant: {STORE} is replaced by p_scope and the counter runs per scope (one sequence per
-- store and period). Same algorithm as the 2-argument function (20261102000400_config.sql).
create or replace function rms_private.next_number(p_series_code text, p_on_date date, p_scope text)
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
  if p_scope is not null and p_scope !~ '^[A-Z][A-Z0-9_]{0,19}$' then
    raise exception 'next_number: invalid scope %', p_scope using errcode = '22023';
  end if;

  select * into s from public.number_series where code = p_series_code;
  if not found then
    raise exception 'next_number: unknown number series %', p_series_code using errcode = 'P0002';
  end if;
  if not s.is_active then
    raise exception 'next_number: number series % is inactive', p_series_code using errcode = '55000';
  end if;
  if s.pattern like '%{STORE}%' and p_scope is null then
    raise exception 'next_number: number series % needs a store scope ({STORE})', p_series_code
      using errcode = '22023';
  end if;

  v_year := extract(year from p_on_date)::integer;
  v_fy_start := case when extract(month from p_on_date)::integer >= s.fy_start_month
                     then v_year else v_year - 1 end;

  if s.fy_start_month = 1 then
    v_fy := v_fy_start::text;
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
  if s.pattern like '%{STORE}%' then
    v_period := v_period || ':' || p_scope;   -- one counter per store
  end if;

  insert into public.number_series_counters as c (series_id, period_key, last_value)
  values (s.id, v_period, s.start_value)
  on conflict (series_id, period_key)
  do update set last_value = c.last_value + 1, updated_at = now()
  returning c.last_value into v_seq;

  v_out := s.pattern;
  v_out := replace(v_out, '{PREFIX}', coalesce(s.prefix, ''));
  v_out := replace(v_out, '{STORE}',  coalesce(p_scope, ''));
  v_out := replace(v_out, '{FY}',     v_fy);
  v_out := replace(v_out, '{YYYY}',   to_char(p_on_date, 'YYYY'));
  v_out := replace(v_out, '{YY}',     to_char(p_on_date, 'YY'));
  v_out := replace(v_out, '{MM}',     to_char(p_on_date, 'MM'));
  v_pad := (regexp_match(v_out, '\{SEQ:([0-9]+)\}'))[1]::integer;
  if v_pad is not null then
    v_out := regexp_replace(v_out, '\{SEQ:[0-9]+\}',
               case when length(v_seq::text) >= v_pad then v_seq::text
                    else lpad(v_seq::text, v_pad, '0') end, 'g');
  end if;
  v_out := replace(v_out, '{SEQ}', v_seq::text);
  return v_out;
end
$$;
revoke all on function rms_private.next_number(text, date, text) from public, anon, authenticated;
grant execute on function rms_private.next_number(text, date, text) to rms_api;

-- The 2-argument form now delegates (no scope): a series using {STORE} fails loudly instead of
-- printing the literal token.
create or replace function rms_private.next_number(p_series_code text, p_on_date date default current_date)
returns text
language sql
volatile
set search_path = ''
as $$
  select rms_private.next_number(p_series_code, p_on_date, null::text)
$$;
revoke all on function rms_private.next_number(text, date) from public;
grant execute on function rms_private.next_number(text, date) to rms_api;

insert into public.number_series (code, name, prefix, pattern, reset_policy, fy_start_month, fy_format)
values ('TRANSFER_SLIP', 'Transfer Slip (Intermediate Store)', 'TRF', '{PREFIX}/{STORE}/{FY}/{SEQ:4}',
        'YEARLY_FY', 4, 'LONG')
on conflict (code) do nothing;

-- ---------------------------------------------------------------------------------------------
-- 3. Tables
-- ---------------------------------------------------------------------------------------------
create table public.transfer_slips (
  id                    uuid primary key default gen_random_uuid(),
  slip_no               text not null unique check (btrim(slip_no) <> ''),
  store_id              uuid not null references public.intermediate_stores (id) on delete restrict,
  store_code_snapshot   text not null,
  store_name_snapshot   text not null,
  -- G-09: the custody transfer INWARD_STAGING → TRANSIT → the store's location behind this slip.
  custody_transfer_id   uuid not null unique references public.custody_transfers (id) on delete restrict,
  status                text not null default 'GENERATED'
                          check (status in ('GENERATED', 'ACKNOWLEDGED', 'VOIDED')),
  relevant_qty          integer not null check (relevant_qty > 0),
  grand_total_qty       integer not null check (grand_total_qty >= relevant_qty),
  template_version_no   integer not null check (template_version_no > 0),
  content               jsonb not null default '{}'::jsonb check (jsonb_typeof(content) = 'object'),
  generated_by          uuid not null default rms_private.current_actor()
                          references public.profiles (id) on delete restrict,
  generated_at          timestamptz not null default now(),
  acknowledged_by       uuid references public.profiles (id) on delete restrict,
  acknowledged_at       timestamptz,
  acknowledge_remarks   text,
  voided_by             uuid references public.profiles (id) on delete restrict,
  voided_at             timestamptz,
  void_reason           text,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  constraint transfer_slips_ack_fields check (
    (acknowledged_at is null) = (acknowledged_by is null)
    and (status <> 'ACKNOWLEDGED' or acknowledged_at is not null)),
  constraint transfer_slips_void_fields check (
    (status = 'VOIDED') = (voided_at is not null)
    and (voided_at is null) = (voided_by is null)
    and (status <> 'VOIDED' or length(btrim(coalesce(void_reason, ''))) >= 3))
);
create index transfer_slips_store_status_idx on public.transfer_slips (store_id, status);
create index transfer_slips_generated_by_idx on public.transfer_slips (generated_by);
create index transfer_slips_acknowledged_by_idx on public.transfer_slips (acknowledged_by)
  where acknowledged_by is not null;
create index transfer_slips_voided_by_idx on public.transfer_slips (voided_by) where voided_by is not null;
create index transfer_slips_generated_at_idx on public.transfer_slips (generated_at desc);
comment on table public.transfer_slips is
  'DEC-65: Intermediate Store transfer slip (one per store per generation, multi-GS). Backed by one custody transfer (G-09). Status only changes: GENERATED → ACKNOWLEDGED (P6) / VOIDED (Q10).';

create table public.transfer_slip_gs (
  id                     uuid primary key default gen_random_uuid(),
  slip_id                uuid not null references public.transfer_slips (id) on delete restrict,
  gs_id                  uuid not null references public.goods_slips (id) on delete restrict,
  gs_no_snapshot         text not null,
  party_name_snapshot    text,
  station_name_snapshot  text,
  state_name_snapshot    text,
  cartons                integer,
  received_date          date,
  relevant_qty           integer not null check (relevant_qty >= 0),
  total_qty              integer not null check (total_qty >= relevant_qty),
  created_at             timestamptz not null default now(),
  unique (slip_id, gs_id)
);
create index transfer_slip_gs_gs_idx on public.transfer_slip_gs (gs_id);
comment on table public.transfer_slip_gs is
  'DEC-65: the goods slips on a transfer slip (GS block of the slip; header snapshots, G-18).';

create table public.transfer_slip_lines (
  id                        uuid primary key default gen_random_uuid(),
  slip_id                   uuid not null references public.transfer_slips (id) on delete restrict,
  gs_id                     uuid not null,
  gs_item_id                uuid not null references public.gs_items (id) on delete restrict,
  line_no_snapshot          integer not null,
  product_id                uuid not null references public.products (id) on delete restrict,
  product_code_snapshot     text,
  product_name_snapshot     text not null,
  -- Condition bucket of the split (G-19). NULL only for a line recorded without a split.
  bucket_field_id           uuid references public.item_field_library (id) on delete restrict,
  bucket_code_snapshot      text,
  bucket_label_snapshot     text,
  qty                       integer not null check (qty > 0),
  -- true: handed over to this slip's store (section 1). false: belongs to another store and is
  -- printed greyed on this slip (section 2).
  is_relevant               boolean not null,
  belongs_store_id          uuid not null references public.intermediate_stores (id) on delete restrict,
  belongs_store_name_snapshot text not null,
  created_at                timestamptz not null default now(),
  foreign key (slip_id, gs_id) references public.transfer_slip_gs (slip_id, gs_id) on delete restrict
);
create index transfer_slip_lines_slip_idx on public.transfer_slip_lines (slip_id);
create index transfer_slip_lines_item_idx on public.transfer_slip_lines (gs_item_id) where is_relevant;
create index transfer_slip_lines_gs_idx on public.transfer_slip_lines (gs_id);
create index transfer_slip_lines_product_idx on public.transfer_slip_lines (product_id);
create index transfer_slip_lines_bucket_idx on public.transfer_slip_lines (bucket_field_id);
create index transfer_slip_lines_store_idx on public.transfer_slip_lines (belongs_store_id);
comment on table public.transfer_slip_lines is
  'DEC-65: lines of a transfer slip per GS item and condition bucket, with label snapshots (G-18). Relevant lines are this store''s; the others are printed greyed.';

create table public.gs_edit_requests (
  id               uuid primary key default gen_random_uuid(),
  gs_id            uuid not null references public.goods_slips (id) on delete restrict,
  reason           text not null check (length(btrim(reason)) >= 3),
  status           text not null default 'OPEN' check (status in ('OPEN', 'EDITED', 'REJECTED')),
  requested_by     uuid not null default rms_private.current_actor()
                     references public.profiles (id) on delete restrict,
  requested_at     timestamptz not null default now(),
  resolved_by      uuid references public.profiles (id) on delete restrict,
  resolved_at      timestamptz,
  resolution_note  text,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  constraint gs_edit_requests_resolution check (
    (status = 'OPEN') = (resolved_at is null)
    and (resolved_at is null) = (resolved_by is null)
    and (status <> 'REJECTED' or length(btrim(coalesce(resolution_note, ''))) >= 3))
);
create unique index gs_edit_requests_one_open on public.gs_edit_requests (gs_id) where status = 'OPEN';
create index gs_edit_requests_gs_idx on public.gs_edit_requests (gs_id);
create index gs_edit_requests_requested_by_idx on public.gs_edit_requests (requested_by);
create index gs_edit_requests_resolved_by_idx on public.gs_edit_requests (resolved_by)
  where resolved_by is not null;
comment on table public.gs_edit_requests is
  'DEC-65: the RM''s "Send Edit Request" on a locked GS (reason) for Management / Super Admin. While OPEN the GS cannot go on a transfer slip.';

-- ---------------------------------------------------------------------------------------------
-- 4. Helpers
-- ---------------------------------------------------------------------------------------------
-- Physical lines of a GS that are not covered exactly by one live slip (0 = fully covered).
create or replace function rms_private.gs_transfer_slip_gaps(p_gs_id uuid)
returns integer
language sql
stable
set search_path = ''
as $$
  select count(*)::integer
    from public.gs_items gi
   where gi.gs_id = p_gs_id and gi.removed_at is null and gi.received_qty > 0
     and coalesce((select sum(l.qty)
                     from public.transfer_slip_lines l
                     join public.transfer_slips s on s.id = l.slip_id
                    where l.gs_item_id = gi.id and l.is_relevant
                      and s.status in ('GENERATED', 'ACKNOWLEDGED')), 0) <> gi.received_qty
$$;
revoke all on function rms_private.gs_transfer_slip_gaps(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_transfer_slip_gaps(uuid) to rms_api;

create or replace function rms_private.gs_has_live_transfer_slip(p_gs_id uuid)
returns boolean
language sql
stable
set search_path = ''
as $$
  select exists (select 1 from public.transfer_slip_gs g
                   join public.transfer_slips s on s.id = g.slip_id
                  where g.gs_id = p_gs_id and s.status in ('GENERATED', 'ACKNOWLEDGED'))
$$;
revoke all on function rms_private.gs_has_live_transfer_slip(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_has_live_transfer_slip(uuid) to rms_api;

-- DEC-64 d + DEC-65 (Q10): post-lock edits also need every live slip of the GS voided first
-- (the service voids them in the same transaction).
create or replace function rms_private.assert_locked_gs_edit(p_gs_id uuid)
returns void
language plpgsql
stable
set search_path = ''
as $$
begin
  if not rms_private.user_holds_permission(rms_private.current_actor(), 'itemization', 'configure') then
    raise exception 'DEC-64: after the categorisation lock only Super Admin or Management may edit the goods slip'
      using errcode = '42501';
  end if;
  if rms_private.gs_routing_started(p_gs_id) then
    raise exception 'DEC-64: the goods slip can no longer be edited: department routing has started'
      using errcode = '23514';
  end if;
  if rms_private.gs_has_live_transfer_slip(p_gs_id) then
    raise exception 'DEC-65: void the live transfer slips of the goods slip before editing it (Q10)'
      using errcode = '23514';
  end if;
end
$$;
revoke all on function rms_private.assert_locked_gs_edit(uuid) from public, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- 5. Guards
-- ---------------------------------------------------------------------------------------------
create or replace function rms_private.transfer_slips_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_store    public.intermediate_stores%rowtype;
  v_transfer record;
  v_staging  uuid;
begin
  if tg_op = 'DELETE' then
    raise exception 'DEC-65: transfer slips are never deleted (void them instead)' using errcode = '42501';
  end if;

  if tg_op = 'INSERT' then
    if not rms_private.user_holds_permission(rms_private.current_actor(), 'transfer_slips', 'create') then
      raise exception 'DEC-65: only the Replacement Manager generates transfer slips' using errcode = '42501';
    end if;
    if new.status <> 'GENERATED' then
      raise exception 'DEC-65: a transfer slip starts GENERATED' using errcode = '23514';
    end if;
    select * into v_store from public.intermediate_stores where id = new.store_id;
    if not v_store.is_active then
      raise exception 'DEC-65: Intermediate Store % is inactive', v_store.code using errcode = '23514';
    end if;
    select t.from_location_id, t.to_location_id, t.status into v_transfer
      from public.custody_transfers t where t.id = new.custody_transfer_id;
    select id into v_staging from public.inventory_locations where code = 'INWARD_STAGING';
    if v_transfer.to_location_id is distinct from v_store.location_id
       or v_transfer.from_location_id is distinct from v_staging
       or v_transfer.status is distinct from 'INITIATED' then
      raise exception 'G-09: a transfer slip is backed by an open custody transfer from Inward Staging to its store (DEC-65)'
        using errcode = '23514';
    end if;
    new.store_code_snapshot := v_store.code;
    new.store_name_snapshot := v_store.name;
    new.generated_by := rms_private.current_actor();
    return new;
  end if;

  -- UPDATE: only the status (and its stamps) change.
  if (new.slip_no, new.store_id, new.store_code_snapshot, new.store_name_snapshot,
      new.custody_transfer_id, new.relevant_qty, new.grand_total_qty, new.template_version_no,
      new.content, new.generated_by, new.generated_at)
     is distinct from
     (old.slip_no, old.store_id, old.store_code_snapshot, old.store_name_snapshot,
      old.custody_transfer_id, old.relevant_qty, old.grand_total_qty, old.template_version_no,
      old.content, old.generated_by, old.generated_at) then
    raise exception 'DEC-65: a transfer slip is immutable; only its status changes' using errcode = '42501';
  end if;
  if new.status is not distinct from old.status then
    if (new.acknowledged_by, new.acknowledged_at, new.voided_by, new.voided_at, new.void_reason)
       is distinct from (old.acknowledged_by, old.acknowledged_at, old.voided_by, old.voided_at, old.void_reason) then
      raise exception 'DEC-65: acknowledgement / void stamps change only with the status' using errcode = '42501';
    end if;
    return new;
  end if;
  if not ((old.status = 'GENERATED' and new.status in ('ACKNOWLEDGED', 'VOIDED'))
          or (old.status = 'ACKNOWLEDGED' and new.status = 'VOIDED')) then
    raise exception 'DEC-65: transfer slip % cannot go from % to %', old.slip_no, old.status, new.status
      using errcode = '23514';
  end if;
  if new.status = 'VOIDED' then
    -- Q10: voided when Super Admin / Management edit a goods slip on it.
    if not rms_private.user_holds_permission(rms_private.current_actor(), 'itemization', 'configure') then
      raise exception 'DEC-65: only Super Admin or Management void a transfer slip (Q10)' using errcode = '42501';
    end if;
    if exists (select 1 from public.transfer_slip_gs g
                where g.slip_id = new.id and rms_private.gs_routing_started(g.gs_id)) then
      raise exception 'DEC-65: department routing has started on a goods slip of transfer slip %', new.slip_no
        using errcode = '23514';
    end if;
    new.voided_by := rms_private.current_actor();
  end if;
  return new;
end
$$;
revoke all on function rms_private.transfer_slips_guard() from public, anon, authenticated;
create trigger transfer_slips_guard
  before insert or update or delete on public.transfer_slips
  for each row execute function rms_private.transfer_slips_guard();

create or replace function rms_private.transfer_slip_gs_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_gs   record;
  v_slip text;
begin
  if tg_op <> 'INSERT' then
    raise exception 'DEC-65: the goods slips of a transfer slip are fixed' using errcode = '42501';
  end if;
  select status into v_slip from public.transfer_slips where id = new.slip_id;
  if v_slip is distinct from 'GENERATED' then
    raise exception 'DEC-65: goods slips are added only while the transfer slip is being generated' using errcode = '23514';
  end if;
  select g.gs_no, g.status, g.category_code, g.categorisation_locked_at into v_gs
    from public.goods_slips g where g.id = new.gs_id for update;
  if v_gs.status is distinct from 'PENDING_TRANSFER_SLIP' or v_gs.category_code is distinct from 'RO'
     or v_gs.categorisation_locked_at is null then
    raise exception 'DEC-65: goods slip % is not waiting for a transfer slip (status %)', v_gs.gs_no, v_gs.status
      using errcode = '23514';
  end if;
  if exists (select 1 from public.gs_edit_requests r where r.gs_id = new.gs_id and r.status = 'OPEN') then
    raise exception 'DEC-65: goods slip % has an open edit request', v_gs.gs_no using errcode = '23514';
  end if;
  new.gs_no_snapshot := v_gs.gs_no;
  return new;
end
$$;
revoke all on function rms_private.transfer_slip_gs_guard() from public, anon, authenticated;
create trigger transfer_slip_gs_guard
  before insert or update or delete on public.transfer_slip_gs
  for each row execute function rms_private.transfer_slip_gs_guard();

create or replace function rms_private.transfer_slip_lines_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_slip   public.transfer_slips%rowtype;
  v_item   public.gs_items%rowtype;
  v_status text;
  v_bucket integer;
begin
  if tg_op <> 'INSERT' then
    raise exception 'DEC-65: transfer slip lines are immutable' using errcode = '42501';
  end if;
  select * into v_slip from public.transfer_slips where id = new.slip_id;
  if v_slip.status is distinct from 'GENERATED' then
    raise exception 'DEC-65: lines are added only while the transfer slip is being generated' using errcode = '23514';
  end if;
  select * into v_item from public.gs_items where id = new.gs_item_id;
  if v_item.gs_id is distinct from new.gs_id then
    raise exception 'DEC-65: the item line does not belong to goods slip %', new.gs_id using errcode = '23514';
  end if;
  if v_item.removed_at is not null then
    raise exception 'DEC-65: a removed item line is not put on a transfer slip (DEC-64 d)' using errcode = '23514';
  end if;
  select status into v_status from public.goods_slips where id = new.gs_id;
  if v_status is distinct from 'PENDING_TRANSFER_SLIP' then
    raise exception 'DEC-65: the goods slip is not waiting for a transfer slip (status %)', v_status
      using errcode = '23514';
  end if;
  if new.product_id is distinct from v_item.product_id then
    raise exception 'DEC-65: the product snapshot must match the item line' using errcode = '23514';
  end if;
  if new.bucket_field_id is not null then
    select b.qty into v_bucket from public.gs_item_buckets b
     where b.gs_item_id = new.gs_item_id and b.field_id = new.bucket_field_id;
    if v_bucket is distinct from new.qty then
      raise exception 'G-19: the slip quantity (%) must equal the condition split (%) of the line', new.qty, v_bucket
        using errcode = '23514';
    end if;
  end if;

  if new.is_relevant then
    if new.belongs_store_id is distinct from v_slip.store_id
       or rms_private.store_for_product(new.product_id) is distinct from v_slip.store_id then
      raise exception 'DEC-65: product % belongs to another Intermediate Store than slip %',
        coalesce(new.product_code_snapshot, new.product_name_snapshot), v_slip.slip_no using errcode = '23514';
    end if;
    if exists (select 1 from public.transfer_slip_lines l
                 join public.transfer_slips s on s.id = l.slip_id
                where l.gs_item_id = new.gs_item_id and l.is_relevant and l.slip_id <> new.slip_id
                  and s.status in ('GENERATED', 'ACKNOWLEDGED')) then
      raise exception 'DEC-65: item line % is already on a live transfer slip', v_item.line_no using errcode = '23514';
    end if;
  elsif new.belongs_store_id = v_slip.store_id
        and not exists (select 1 from public.transfer_slip_lines l
                          join public.transfer_slips s on s.id = l.slip_id
                         where l.gs_item_id = new.gs_item_id and l.is_relevant
                           and s.status in ('GENERATED', 'ACKNOWLEDGED')) then
    -- A greyed line of the slip's own store is only an item already on another live slip.
    raise exception 'DEC-65: a greyed line belongs to another store than the slip''s' using errcode = '23514';
  end if;
  return new;
end
$$;
revoke all on function rms_private.transfer_slip_lines_guard() from public, anon, authenticated;
create trigger transfer_slip_lines_guard
  before insert or update or delete on public.transfer_slip_lines
  for each row execute function rms_private.transfer_slip_lines_guard();

create or replace function rms_private.gs_edit_requests_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_status text;
begin
  if tg_op = 'DELETE' then
    raise exception 'DEC-65: edit requests are kept as history' using errcode = '42501';
  end if;
  if tg_op = 'INSERT' then
    if not rms_private.user_holds_permission(rms_private.current_actor(), 'transfer_slips', 'create') then
      raise exception 'DEC-65: only the Replacement Manager sends an edit request' using errcode = '42501';
    end if;
    if new.status <> 'OPEN' then
      raise exception 'DEC-65: an edit request starts OPEN' using errcode = '23514';
    end if;
    select status into v_status from public.goods_slips where id = new.gs_id;
    if v_status is distinct from 'PENDING_TRANSFER_SLIP' then
      raise exception 'DEC-65: an edit request is sent for a goods slip pending its transfer slip (status %)', v_status
        using errcode = '23514';
    end if;
    new.requested_by := rms_private.current_actor();
    return new;
  end if;
  if (new.gs_id, new.reason, new.requested_by, new.requested_at)
     is distinct from (old.gs_id, old.reason, old.requested_by, old.requested_at) then
    raise exception 'DEC-65: an edit request is immutable' using errcode = '42501';
  end if;
  if old.status <> 'OPEN' then
    raise exception 'DEC-65: a resolved edit request is immutable' using errcode = '42501';
  end if;
  if new.status = 'OPEN' then
    return new;
  end if;
  if not rms_private.user_holds_permission(rms_private.current_actor(), 'itemization', 'configure') then
    raise exception 'DEC-65: only Super Admin or Management resolve an edit request' using errcode = '42501';
  end if;
  new.resolved_by := rms_private.current_actor();
  return new;
end
$$;
revoke all on function rms_private.gs_edit_requests_guard() from public, anon, authenticated;
create trigger gs_edit_requests_guard
  before insert or update or delete on public.gs_edit_requests
  for each row execute function rms_private.gs_edit_requests_guard();

-- RLS, grants, standard triggers (business data flows through the API: rms_api only).
alter table public.transfer_slips enable row level security;
alter table public.transfer_slip_gs enable row level security;
alter table public.transfer_slip_lines enable row level security;
alter table public.gs_edit_requests enable row level security;
revoke all on public.transfer_slips, public.transfer_slip_gs, public.transfer_slip_lines,
              public.gs_edit_requests from anon, authenticated;
grant select, insert, update on public.transfer_slips to rms_api;
grant select, insert on public.transfer_slip_gs, public.transfer_slip_lines to rms_api;
grant select, insert, update on public.gs_edit_requests to rms_api;
select rms_private.attach_standard_triggers('public.transfer_slips');
select rms_private.attach_standard_triggers('public.transfer_slip_gs');
select rms_private.attach_standard_triggers('public.transfer_slip_lines');
select rms_private.attach_standard_triggers('public.gs_edit_requests');

-- ---------------------------------------------------------------------------------------------
-- 6. Status chain (G-03 trigger, full body replaced: P4 body + the DEC-65 transitions)
-- ---------------------------------------------------------------------------------------------
create or replace function rms_private.goods_slips_g03_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_decision text;
begin
  -- original_category_code records the Step-3 choice and is kept for good (BR-08).
  if old.original_category_code is not null
     and new.original_category_code is distinct from old.original_category_code then
    raise exception 'G-03: the original category of a GS cannot change' using errcode = '23514';
  end if;

  select decision_code into v_decision
    from public.csr_approvals where gs_id = new.id and is_current;

  -- Category changes after Step-3: CSR -> RO only by a current CSR_REJECTED_TO_RO decision;
  -- RO -> CSR only when an admin reopened that decision (back to CSR_APPROVAL_PENDING).
  if old.category_code is not null and new.category_code is distinct from old.category_code then
    if not coalesce((old.category_code = 'CSR' and new.category_code is not distinct from 'RO'
                     and v_decision is not distinct from 'CSR_REJECTED_TO_RO')
                    or (old.category_code = 'RO' and new.category_code is not distinct from 'CSR'
                        and new.original_category_code is not distinct from 'CSR'
                        and v_decision is null
                        and new.status is not distinct from 'CSR_APPROVAL_PENDING'), false) then
      raise exception 'G-03: category % -> % needs a matching Replacement Manager decision',
        old.category_code, coalesce(new.category_code, 'none') using errcode = '23514';
    end if;
  end if;

  if new.status is not distinct from old.status or new.status = 'CANCELLED' then
    return new;
  end if;

  -- DEC-64 (a, b): items → popup. Replacement → CATEGORISATION, Complete Sales Return → hold.
  if old.status = 'ITEMIZATION' then
    if new.status not in ('CATEGORISATION', 'SALES_RETURN_HOLD') then
      raise exception 'G-03: counting is submitted to CATEGORISATION (Replacement) or SALES_RETURN_HOLD (Complete Sales Return), not %', new.status
        using errcode = '23514';
    end if;
    if not exists (select 1 from public.gs_items where gs_id = new.id) then
      raise exception 'G-01: counting cannot be submitted without item lines' using errcode = '23514';
    end if;
    if new.status = 'CATEGORISATION' then
      -- (A CSR GS reaching CATEGORISATION is the legacy P2-04 path; it can never be locked,
      --  the lock below requires RO. The DEC-64 popup parks a CSR in SALES_RETURN_HOLD.)
      return new;
    end if;
    if new.status = 'SALES_RETURN_HOLD' then
      if new.category_code is distinct from 'CSR' then
        raise exception 'G-03: only a Complete Sales Return goes to SALES_RETURN_HOLD (DEC-64, Q11)'
          using errcode = '23514';
      end if;
      return new;
    end if;
  end if;

  if old.status = 'CATEGORISATION' then
    if not exists (select 1 from public.gs_items where gs_id = new.id) then
      raise exception 'G-01: a GS cannot be categorised without item lines' using errcode = '23514';
    end if;
    -- DEC-64 (c): the lock.
    if new.status = 'PENDING_TRANSFER_SLIP' then
      if new.category_code is distinct from 'RO' then
        raise exception 'G-03: only a Replacement GS is locked for transfer slips (DEC-64)' using errcode = '23514';
      end if;
      perform rms_private.validate_item_bucket_conservation(new.id);   -- G-19
      if new.categorisation_locked_at is null then
        raise exception 'DEC-64: PENDING_TRANSFER_SLIP needs the categorisation lock stamp' using errcode = '23514';
      end if;
      return new;
    end if;
    if new.status = 'RM_REVIEW' then
      raise exception 'DEC-64: categorisation is locked, not submitted to RM review any more' using errcode = '23514';
    end if;
    -- A legacy GS sent back by the RM has no category yet: its popup may still park it (Q11).
    if new.status = 'SALES_RETURN_HOLD' then
      if new.category_code is distinct from 'CSR' then
        raise exception 'G-03: only a Complete Sales Return goes to SALES_RETURN_HOLD (DEC-64, Q11)'
          using errcode = '23514';
      end if;
      return new;
    end if;

    -- Legacy path (P2-04 /categorize): category_code required
    if new.category_code is null then
      raise exception 'G-03: a GS cannot leave CATEGORISATION without a category' using errcode = '23514';
    end if;
    if new.category_code = 'CSR' and new.status <> 'CSR_APPROVAL_PENDING' then
      raise exception 'G-03: a Complete Sales Return must go to CSR_APPROVAL_PENDING (not %)', new.status
        using errcode = '23514';
    end if;
    if new.category_code = 'RO' and new.status <> 'INSPECTION' then
      raise exception 'G-03: Replacement Only goes to INSPECTION (not %)', new.status using errcode = '23514';
    end if;
    return new;
  end if;

  -- DEC-64 / Q11: a Complete Sales Return on hold has no further steps until that journey exists.
  if old.status = 'SALES_RETURN_HOLD' then
    raise exception 'G-03: a Complete Sales Return on hold cannot advance yet (DEC-64, Q11)' using errcode = '23514';
  end if;
  -- DEC-65 (P5): a locked GS leaves PENDING_TRANSFER_SLIP only when every physical line is on a
  -- live transfer slip; a void (Q10) brings it back while any line is uncovered.
  if old.status = 'PENDING_TRANSFER_SLIP' then
    if new.status = 'TRANSFER_SLIP_GENERATED' then
      if rms_private.gs_transfer_slip_gaps(new.id) > 0 then
        raise exception 'DEC-65: every physical line of the goods slip must be on a live transfer slip'
          using errcode = '23514';
      end if;
      return new;
    end if;
    raise exception 'G-03: a locked GS leaves PENDING_TRANSFER_SLIP only through its transfer slips (DEC-65), not to %', new.status
      using errcode = '23514';
  end if;
  if old.status = 'TRANSFER_SLIP_GENERATED' then
    if new.status = 'PENDING_TRANSFER_SLIP' then
      if rms_private.gs_transfer_slip_gaps(new.id) = 0 then
        raise exception 'DEC-65: the goods slip is still fully on live transfer slips' using errcode = '23514';
      end if;
      return new;
    end if;
    raise exception 'G-03: % is not reachable from TRANSFER_SLIP_GENERATED yet (store acknowledgement, P6)', new.status
      using errcode = '23514';
  end if;
  if new.status in ('PENDING_TRANSFER_SLIP', 'SALES_RETURN_HOLD', 'TRANSFER_SLIP_GENERATED') then
    raise exception 'G-03: % is reached only from counting / categorisation / transfer slips (from %)', new.status, old.status
      using errcode = '23514';
  end if;

  -- Phase 5 (AMD-12, AMD-13): RM_REVIEW transitions (legacy GSs)
  if old.status = 'RM_REVIEW' then
    if new.status = 'CATEGORISATION' then
      return new;   -- send back with remark
    end if;
    if new.status = 'HELD_AT_INTERMEDIATE_STORE' then
      perform rms_private.validate_item_bucket_conservation(new.id);
      return new;
    end if;
    if new.status = 'IN_PROCESS' then
      return new;   -- legacy Step-4 RO RM review
    end if;
  end if;

  if new.status = 'CATEGORISATION' and old.status <> 'RM_REVIEW' then
    raise exception 'G-03: only a GS in counting (ITEMIZATION) moves to CATEGORISATION (from %)', old.status
      using errcode = '23514';
  end if;

  if new.status = 'CSR_APPROVAL_PENDING' then
    if new.category_code is distinct from 'CSR' or v_decision is not null then
      raise exception 'G-03: CSR_APPROVAL_PENDING needs category CSR and no current decision'
        using errcode = '23514';
    end if;
    return new;
  end if;

  -- Leaving CSR_APPROVAL_PENDING (BR-08, DD r19-r20): only through the recorded decision.
  if old.status = 'CSR_APPROVAL_PENDING' then
    if v_decision is null then
      raise exception 'G-03: a Complete Sales Return cannot advance without the Replacement Manager''s decision'
        using errcode = '23514';
    end if;
    if v_decision = 'CSR_APPROVED' and (new.status <> 'IN_PROCESS'
                                         or new.category_code is distinct from 'CSR') then
      raise exception 'G-03: an approved CSR goes to IN_PROCESS as CSR (not %)', new.status using errcode = '23514';
    end if;
    if v_decision = 'CSR_REJECTED_TO_RO' and (new.status <> 'INSPECTION'
                                               or new.category_code is distinct from 'RO') then
      raise exception 'G-03: a rejected CSR is converted to RO and goes to INSPECTION (not %)', new.status
        using errcode = '23514';
    end if;
  end if;

  -- No CSR GS (nor one that was CSR) reaches inspection, handover or Stage-6 without a decision.
  if new.status in ('INSPECTION', 'RM_REVIEW', 'HELD_AT_INTERMEDIATE_STORE', 'IN_PROCESS',
                    'COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION', 'CLOSED')
     and 'CSR' in (new.category_code, new.original_category_code) and old.status not in ('RM_REVIEW', 'CATEGORISATION') then
    if (new.category_code = 'CSR' and v_decision is distinct from 'CSR_APPROVED')
       or (new.category_code = 'RO' and v_decision is distinct from 'CSR_REJECTED_TO_RO') then
      raise exception 'G-03: status % needs the Replacement Manager''s CSR decision', new.status
        using errcode = '23514';
    end if;
  end if;

  return new;
end
$$;
revoke all on function rms_private.goods_slips_g03_guard() from public, anon, authenticated;


-- ---------------------------------------------------------------------------------------------
-- 7. Print template TRANSFER_SLIP (DEC-41: layout is configuration) and the logo (Q26)
-- ---------------------------------------------------------------------------------------------
alter table public.print_templates drop constraint print_templates_code_check;
alter table public.print_templates
  add constraint print_templates_code_check check (
    code in ('REPLACEMENT_SLIP', 'GS_TAG', 'CN_SUMMARY', 'TRANSFER_NOTE', 'STORE_ISSUE', 'AC_ACTIONS_SLIP',
             'DISPATCH_SLIP', 'TRANSFER_SLIP'));

do $$
declare
  v_layout jsonb := jsonb_build_object(
    'paper_size', 'A4',
    'orientation', 'portrait',
    'show_logo', true,
    'header_title', 'HICKS THERMOMETERS (INDIA) LIMITED',
    'header_subtitle', 'Transfer Slip',
    'footer_text', 'Computer generated by RMS. Hand over the items for this store; greyed items belong to other stores.',
    'sections', jsonb_build_array(
      jsonb_build_object('id', 'header', 'title', 'Transfer Slip',
        'fields', jsonb_build_array('slip_no', 'store_name', 'generated_at', 'generated_by')),
      jsonb_build_object('id', 'goods_slips', 'title', 'Goods Slip',
        'fields', jsonb_build_array('gs_no', 'party_name', 'station_name', 'state_name', 'cartons', 'received_date')),
      jsonb_build_object('id', 'relevant', 'title', 'Items for this store',
        'fields', jsonb_build_array('line_no', 'product_code', 'product_name', 'condition', 'qty')),
      jsonb_build_object('id', 'others', 'title', 'Other items of these goods slips (other stores)',
        'fields', jsonb_build_array('line_no', 'product_name', 'condition', 'qty', 'store_name')),
      jsonb_build_object('id', 'totals', 'title', 'Totals',
        'fields', jsonb_build_array('relevant_qty', 'grand_total_qty')),
      jsonb_build_object('id', 'signatures', 'title', 'Signatures',
        'fields', jsonb_build_array('signature_blocks'))
    ),
    'signature_blocks', jsonb_build_array(
      jsonb_build_object('label', 'Handed over by', 'role', 'Replacement Manager'),
      jsonb_build_object('label', 'Received by', 'role', 'Intermediate Store')
    )
  );
begin
  if not exists (select 1 from public.print_templates where code = 'TRANSFER_SLIP') then
    insert into public.print_templates (code, name, version_no, layout, status, snapshot, published_at)
    values ('TRANSFER_SLIP', 'Transfer Slip', 1, v_layout, 'PUBLISHED', v_layout, now());
  end if;
end
$$;

-- Q26 / DEC-65: the Replacement (A/c Actions) Slip and the Dispatch Slip print the logo too. A
-- published template is immutable (G-18): a new published version replaces it.
do $$
declare
  v_tpl record;
  v_layout jsonb;
begin
  for v_tpl in
    select id, code, name, version_no, coalesce(snapshot, layout) as layout
      from public.print_templates
     where code in ('AC_ACTIONS_SLIP', 'DISPATCH_SLIP') and status = 'PUBLISHED'
       and coalesce((coalesce(snapshot, layout) ->> 'show_logo')::boolean, false) = false
  loop
    v_layout := v_tpl.layout || jsonb_build_object('show_logo', true);
    update public.print_templates set status = 'RETIRED' where id = v_tpl.id;
    insert into public.print_templates (code, name, version_no, layout, status, snapshot, published_at)
    values (v_tpl.code, v_tpl.name,
            (select max(version_no) + 1 from public.print_templates where code = v_tpl.code),
            v_layout, 'PUBLISHED', v_layout, now());
  end loop;
end
$$;

insert into public.system_settings (key, value, category, description, source_ref) values
  ('branding_print_logo', '"hicks-logo.png"'::jsonb, 'branding',
   'Logo drawn on the slip PDFs whose print template has show_logo on (Transfer Slip, Replacement Slip, Dispatch Slip): the file name of an image shipped with the backend (backend/app/assets/branding). Empty string = no logo, the company name only.',
   'DEC-65')
on conflict (key) do nothing;

-- ---------------------------------------------------------------------------------------------
-- 8. Permissions catalogue (grants: seed.sql + snippet)
-- ---------------------------------------------------------------------------------------------
insert into public.permissions (module_code, action, description)
values
  ('transfer_slips', 'view',   'View transfer slips and the goods slips pending a transfer slip (DEC-65)'),
  ('transfer_slips', 'create', 'Generate transfer slips and send edit requests (Replacement Manager, DEC-65)')
on conflict (module_code, action) do nothing;

-- Existing databases: the Super Admin marker role holds every permission.
insert into public.role_permissions (role_id, permission_id, scope)
select r.id, p.id, 'all'
  from public.roles r
  join public.permissions p on p.module_code = 'transfer_slips'
 where r.code = 'SUPER_ADMIN'
on conflict (role_id, permission_id) do nothing;

-- ---------------------------------------------------------------------------------------------
-- 9. Journey catalogue (role menus: seed.sql + snippet)
-- ---------------------------------------------------------------------------------------------
alter table public.journey_steps drop constraint if exists journey_steps_screen_key_check;
alter table public.journey_steps add constraint journey_steps_screen_key_check check (screen_key in (
  'journey-queue', 'gs-new', 'gs-list', 'dashboard', 'pendencies',
  'container-audit', 'reports', 'audit', 'custody', 'inventory', 'store-issues',
  'servicing', 'batteries', 'dismantling', 'scrap', 'credit-notes', 'approvals',
  'dispatch-queue', 'department-routing', 'department-receiving', 'department-issue',
  'accounts-entry', 'accounts-docs', 'dispatch-slips', 'transfer-slips'));

alter table public.journey_steps drop constraint if exists journey_steps_item_screen_key_check;
alter table public.journey_steps add constraint journey_steps_item_screen_key_check check (
  item_screen_key is null or item_screen_key in (
    'gs-detail', 'gs-unboxing', 'gs-itemization', 'gs-inspection', 'gs-rm-review',
    'custody-transfer', 'gs-final-actions', 'department-receiving', 'department-issue',
    'accounts-entry-gs', 'accounts-docs', 'dispatch-slips',
    'gs-party-notification', 'transfer-slips'));

alter table public.journey_steps drop constraint if exists journey_steps_queue_code_check;
alter table public.journey_steps add constraint journey_steps_queue_code_check check (
  queue_code is null or queue_code in (
    'CARTON_OPENING', 'COUNTING', 'CATEGORISATION', 'INSPECTION', 'RM_REVIEW', 'STORE_ACCEPT',
    'DEPT_ROUTING', 'DEPT_ISSUE', 'DEPT_RECEIVING', 'FINAL_ACTIONS', 'ACCOUNTS_DOCS',
    'ACCOUNTS_ENTRY', 'DISPATCH_SLIP', 'PARTY_EMAIL', 'PENDING_TRANSFER_SLIP', 'EDIT_REQUESTS'));

insert into public.journey_steps
  (code, label, hint, kind, screen_key, item_screen_key, queue_code, feature_code,
   perm_module, perm_action, sort_order, source_ref)
values
  ('TRANSFER_SLIPS', 'Transfer Slips', 'Locked goods slips: generate the transfer slips per store, or send an edit request',
   'STEP', 'transfer-slips', 'transfer-slips', 'PENDING_TRANSFER_SLIP', null,
   'transfer_slips', 'create', 52, 'DEC-65'),
  ('EDIT_REQUESTS', 'Edit Requests', 'The Replacement Manager asked to correct a locked goods slip',
   'STEP', 'journey-queue', 'gs-itemization', 'EDIT_REQUESTS', null,
   'itemization', 'configure', 54, 'DEC-65')
on conflict (code) do nothing;

-- ---------------------------------------------------------------------------------------------
-- 10. Notification event types (recipients = rules in seed.sql + the release snippet)
-- ---------------------------------------------------------------------------------------------
insert into public.notification_event_types
  (code, label, description, category, default_priority, is_mandatory, source_ref, sort_order)
values
  ('TRANSFER_SLIP_VOIDED', 'Transfer slip voided',
   'DEC-65 / Q10: a goods slip on the transfer slip was edited after the lock; the slip is void and must be regenerated.',
   'WORKFLOW', 'HIGH', false, 'DEC-65', 560),
  ('GS_EDIT_REQUESTED', 'Edit request for a locked goods slip',
   'DEC-65: the Replacement Manager asked Management / Super Admin to correct a locked goods slip.',
   'WORKFLOW', 'HIGH', false, 'DEC-65', 570),
  ('GS_EDIT_REQUEST_RESOLVED', 'Edit request resolved',
   'DEC-65: Management / Super Admin edited the goods slip or rejected the edit request.',
   'WORKFLOW', 'NORMAL', false, 'DEC-65', 580)
on conflict (code) do update
  set label = excluded.label, description = excluded.description,
      default_priority = excluded.default_priority, source_ref = excluded.source_ref;

insert into public.notification_templates (event_type, channel, version_no, subject, body, change_reason)
select v.event_type, 'EMAIL', 1,
       '[{app_name}] {title}',
       E'Hello {recipient_name},

{title}

{body}

Event: {event_label}
Priority: {priority}
Open in RMS: {link}

— {app_name} (automated message; manage email preferences in RMS)',
       'P5 default'
  from (values ('TRANSFER_SLIP_VOIDED'), ('GS_EDIT_REQUESTED'), ('GS_EDIT_REQUEST_RESOLVED')) as v(event_type)
 where not exists (select 1 from public.notification_templates t
                    where t.event_type = v.event_type and t.channel = 'EMAIL');
