-- Change plan 2026-11-12 · Phase 8 — Accounts Entry & Dispatch Slip
-- (docs/RMS_MASTER_PLAN_ADDENDUM_2026-11.md AMD-18, AMD-19; DEC-22, DEC-26, DEC-45, DEC-47;
--  G-04, G-15, G-16, G-18; new guard G-22).
--
-- 1. ac_entry_lines (AMD-18): one row per action line of an A/c Actions slip version, created by a
--    DB trigger when the slip is finalised. The flags requires_cn / requires_challan are copied from
--    the ACTION library at that moment (G-18 snapshot); Accounts fills CN No./Date/Value and/or
--    Challan No./Date only where the flag asks for it. CN numbers are external vouchers (DEC-22):
--    one CN No. belongs to one goods slip and is never also on a credit_notes row.
-- 2. ac_entry_completions: Accounts marks the entry complete once every line that needs data has
--    it. The entries, the A/c Actions slip and the RM actions are frozen from then on.
-- 3. dispatch_slips / dispatch_slip_lines (AMD-19): on completion, a numbered Dispatch Slip (PDF,
--    GENERATED_PDF attachment) holds the lines that ship goods (requires_challan, DEC-47). DISPATCH
--    marks it dispatched (date + transporter + docket / vehicle, DEC-26); stock moves through
--    rms_move_stock in the service, in the same transaction.
-- 4. G-22 (AMD-18/19) in the DB: entries change only on the CURRENT slip of a held GS before
--    completion; fields only where the action flag requires them; completion only when every line
--    is complete; the Dispatch Slip covers exactly the shipping lines; a dispatched slip is final;
--    the A/c Actions slip cannot be superseded once Accounts completed; the P3-05 replacement
--    dispatch path is closed for goods slips on the AMD-13 flow.
-- 5. Closure checklist (G-15) fix-forward: on the AMD-13 flow the commercial items are the Accounts
--    completion and the Dispatch Slip (the P3-06 RM CN decision does not apply there).
-- 6. Config: number series DISPATCH_SLIP, print template DISPATCH_SLIP v1, notification events,
--    setting dispatch.returned_goods_location_by_action (DEC-47), permissions `ac_entry`.
-- Messages carry "G-22" so the API maps them to the standard 409 guard envelope.

-- ===========================================================================
-- 1. ac_entry_lines
-- ===========================================================================
create table public.ac_entry_lines (
  id                   uuid primary key default gen_random_uuid(),
  gs_id                uuid not null references public.goods_slips (id) on delete restrict,
  ac_action_slip_id    uuid not null references public.ac_action_slips (id) on delete restrict,
  rm_item_action_id    uuid not null references public.rm_item_actions (id) on delete restrict,
  gs_item_id           uuid not null references public.gs_items (id) on delete restrict,
  line_no              integer not null check (line_no > 0),
  action_code          text not null,
  action_label         text not null,
  qty                  integer not null check (qty > 0),
  -- G-18: flags of the ACTION library at finalise time (AMD-18: fields come from flags, not code).
  requires_cn          boolean not null,
  requires_challan     boolean not null,
  cn_no                text check (cn_no is null or btrim(cn_no) <> ''),
  cn_date              date,
  cn_value             numeric(14,2) check (cn_value is null or cn_value > 0),
  challan_no           text check (challan_no is null or btrim(challan_no) <> ''),
  challan_date         date,
  entered_by           uuid references public.profiles (id) on delete restrict,
  entered_at           timestamptz,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  unique (ac_action_slip_id, rm_item_action_id),
  -- AMD-18: a field group is filled only where the action asks for it, and then all of it.
  constraint ac_entry_lines_cn_fields check (
    (requires_cn or (cn_no is null and cn_date is null and cn_value is null))
    and ((cn_no is null) = (cn_date is null) and (cn_no is null) = (cn_value is null))),
  constraint ac_entry_lines_challan_fields check (
    (requires_challan or (challan_no is null and challan_date is null))
    and ((challan_no is null) = (challan_date is null)))
);
create index ac_entry_lines_gs_idx on public.ac_entry_lines (gs_id);
create index ac_entry_lines_rm_action_idx on public.ac_entry_lines (rm_item_action_id);
create index ac_entry_lines_gs_item_idx on public.ac_entry_lines (gs_item_id);
create index ac_entry_lines_entered_by_idx on public.ac_entry_lines (entered_by);
create index ac_entry_lines_cn_no_idx on public.ac_entry_lines (upper(btrim(cn_no))) where cn_no is not null;

comment on table public.ac_entry_lines is
  'AMD-18: Accounts data per action line of an A/c Actions slip version (CN No./Date/Value, Challan No./Date). Flags snapshotted from the ACTION library (G-18).';

-- A line is complete when every field group its flags require is filled.
create or replace function rms_private.ac_entry_line_complete(p public.ac_entry_lines)
returns boolean
language sql
immutable
set search_path = ''
as $$
  select (not p.requires_cn or p.cn_no is not null)
     and (not p.requires_challan or p.challan_no is not null);
$$;
revoke all on function rms_private.ac_entry_line_complete(public.ac_entry_lines) from public, anon, authenticated;
grant execute on function rms_private.ac_entry_line_complete(public.ac_entry_lines) to rms_api;

-- ===========================================================================
-- 2. ac_entry_completions
-- ===========================================================================
create table public.ac_entry_completions (
  id                   uuid primary key default gen_random_uuid(),
  gs_id                uuid not null references public.goods_slips (id) on delete restrict,
  ac_action_slip_id    uuid not null unique references public.ac_action_slips (id) on delete restrict,
  completed_by         uuid not null default rms_private.current_actor() references public.profiles (id) on delete restrict,
  completed_at         timestamptz not null default now(),
  remarks              text
);
create unique index ac_entry_completions_gs_idx on public.ac_entry_completions (gs_id);
create index ac_entry_completions_completed_by_idx on public.ac_entry_completions (completed_by);

comment on table public.ac_entry_completions is
  'AMD-18/19: Accounts completed the entry of a CURRENT A/c Actions slip. Insert-only; freezes the entries, the slip and the RM actions (G-22).';

-- ===========================================================================
-- 3. dispatch_slips / dispatch_slip_lines
-- ===========================================================================
create table public.dispatch_slips (
  id                   uuid primary key default gen_random_uuid(),
  gs_id                uuid not null unique references public.goods_slips (id) on delete restrict,
  ac_action_slip_id    uuid not null unique references public.ac_action_slips (id) on delete restrict,
  slip_no              text not null unique check (btrim(slip_no) <> ''),
  status               text not null default 'READY' check (status in ('READY', 'DISPATCHED')),
  attachment_id        uuid not null unique references public.attachments (id) on delete restrict,
  template_code        text not null default 'DISPATCH_SLIP',
  template_version_no  integer not null check (template_version_no > 0),
  content              jsonb not null,
  sha256               text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  generated_by         uuid not null default rms_private.current_actor() references public.profiles (id) on delete restrict,
  generated_at         timestamptz not null default now(),
  -- DEC-26 tracking data, recorded by DISPATCH when the goods leave.
  dispatch_date        date,
  transporter          text,
  docket_no            text,
  vehicle_no           text,
  dispatch_remarks     text,
  dispatched_by        uuid references public.profiles (id) on delete restrict,
  dispatched_at        timestamptz,
  constraint dispatch_slips_dispatched_fields check (
    (status = 'READY' and dispatch_date is null and dispatched_by is null and dispatched_at is null)
    or (status = 'DISPATCHED' and dispatch_date is not null and dispatched_by is not null
        and dispatched_at is not null and btrim(coalesce(transporter, '')) <> ''
        and (btrim(coalesce(docket_no, '')) <> '' or btrim(coalesce(vehicle_no, '')) <> '')))
);
create index dispatch_slips_status_idx on public.dispatch_slips (status);
create index dispatch_slips_generated_by_idx on public.dispatch_slips (generated_by);
create index dispatch_slips_dispatched_by_idx on public.dispatch_slips (dispatched_by);

comment on table public.dispatch_slips is
  'AMD-19: numbered Dispatch Slip (PDF) of the action lines that ship goods. READY -> DISPATCHED once (G-22).';

create table public.dispatch_slip_lines (
  id                   uuid primary key default gen_random_uuid(),
  dispatch_slip_id     uuid not null references public.dispatch_slips (id) on delete restrict,
  ac_entry_line_id     uuid not null unique references public.ac_entry_lines (id) on delete restrict,
  gs_item_id           uuid not null references public.gs_items (id) on delete restrict,
  line_no              integer not null check (line_no > 0),
  action_code          text not null,
  action_label         text not null,
  qty                  integer not null check (qty > 0),
  challan_no           text not null check (btrim(challan_no) <> ''),
  challan_date         date not null,
  created_at           timestamptz not null default now()
);
create index dispatch_slip_lines_slip_idx on public.dispatch_slip_lines (dispatch_slip_id);
create index dispatch_slip_lines_gs_item_idx on public.dispatch_slip_lines (gs_item_id);

-- ===========================================================================
-- 4. G-22 guards
-- ===========================================================================

-- 4a. Entry rows are created by the DB when a slip version is finalised (one per current action).
create or replace function rms_private.ac_action_slips_create_entry_lines()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.ac_entry_lines
    (gs_id, ac_action_slip_id, rm_item_action_id, gs_item_id, line_no, action_code, action_label,
     qty, requires_cn, requires_challan)
  select new.gs_id, new.id, act.id, gi.id, gi.line_no, act.action_code,
         coalesce(act.action_label, lib.label, act.action_code), act.qty,
         coalesce(lib.requires_cn, false), coalesce(lib.requires_challan, false)
    from public.rm_item_actions act
    join public.gs_items gi on gi.id = act.gs_item_id
    left join public.item_field_library lib
           on lib.field_group = 'ACTION' and lib.code = act.action_code
   where gi.gs_id = new.gs_id
     and act.is_current
     and act.qty > 0;
  return null;
end;
$$;
revoke all on function rms_private.ac_action_slips_create_entry_lines() from public, anon, authenticated;

create trigger ac_action_slips_create_entry_lines
  after insert on public.ac_action_slips
  for each row execute function rms_private.ac_action_slips_create_entry_lines();

-- 4b. Entry rows: no delete; only the Accounts columns change, only before completion, only on the
--     CURRENT slip of a GS held at the intermediate store; dates not in the future; CN No. unique
--     per goods slip and never on a credit note (DEC-22).
create or replace function rms_private.ac_entry_lines_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_slip_status  text;
  v_gs_status    text;
  v_other_gs     text;
begin
  if tg_op = 'DELETE' then
    raise exception 'G-22: Accounts entry lines are never deleted' using errcode = '42501';
  end if;

  if tg_op = 'UPDATE' then
    if (to_jsonb(new) - array['cn_no', 'cn_date', 'cn_value', 'challan_no', 'challan_date',
                              'entered_by', 'entered_at', 'updated_at'])
       <> (to_jsonb(old) - array['cn_no', 'cn_date', 'cn_value', 'challan_no', 'challan_date',
                                 'entered_by', 'entered_at', 'updated_at']) then
      raise exception 'G-22: only the Accounts fields of an entry line can change'
        using errcode = '42501';
    end if;
  end if;

  select status into v_gs_status from public.goods_slips where id = new.gs_id for update;
  select status into v_slip_status from public.ac_action_slips where id = new.ac_action_slip_id;

  if tg_op = 'UPDATE' then
    if v_slip_status is distinct from 'CURRENT' then
      raise exception 'G-22: the A/c Actions slip of this line is superseded; enter the data on the current version'
        using errcode = 'P0001';
    end if;
    if v_gs_status is distinct from 'HELD_AT_INTERMEDIATE_STORE' then
      raise exception 'G-22: Accounts data changes only while the goods slip is held at the intermediate store (status %)',
        v_gs_status using errcode = 'P0001';
    end if;
    if exists (select 1 from public.ac_entry_completions c where c.ac_action_slip_id = new.ac_action_slip_id) then
      raise exception 'G-22: the Accounts entry of this slip is complete and frozen'
        using errcode = 'P0001';
    end if;
  end if;

  if new.cn_date > current_date or new.challan_date > current_date then
    raise exception 'G-22: CN / Challan dates cannot be in the future' using errcode = 'P0001';
  end if;

  if new.cn_no is not null then
    -- Serialise concurrent saves of the same voucher number (DEC-22).
    perform pg_advisory_xact_lock(hashtext('ac_entry_cn_no:' || upper(btrim(new.cn_no))));
    select g.gs_no into v_other_gs
      from public.ac_entry_lines e
      join public.goods_slips g on g.id = e.gs_id
     where upper(btrim(e.cn_no)) = upper(btrim(new.cn_no))
       and e.gs_id <> new.gs_id
     limit 1;
    if found then
      raise exception 'G-22: CN No. % is already recorded on goods slip % (DEC-22)', new.cn_no, v_other_gs
        using errcode = 'P0001';
    end if;
    if exists (select 1 from public.credit_notes cn
                where upper(btrim(cn.cn_no)) = upper(btrim(new.cn_no))) then
      raise exception 'G-22: CN No. % is already recorded on a credit note (DEC-22)', new.cn_no
        using errcode = 'P0001';
    end if;
  end if;

  new.updated_at := now();
  return new;
end;
$$;
revoke all on function rms_private.ac_entry_lines_guard() from public, anon, authenticated;

create trigger ac_entry_lines_guard
  before insert or update or delete on public.ac_entry_lines
  for each row execute function rms_private.ac_entry_lines_guard();

-- 4c. Completion: insert-only, CURRENT slip, held GS, every line complete.
create or replace function rms_private.ac_entry_completions_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_gs_status   text;
  v_slip        record;
  v_open        record;
begin
  if tg_op <> 'INSERT' then
    raise exception 'G-22: an Accounts completion is final' using errcode = '42501';
  end if;

  select status into v_gs_status from public.goods_slips where id = new.gs_id for update;
  if v_gs_status is distinct from 'HELD_AT_INTERMEDIATE_STORE' then
    raise exception 'G-22: Accounts completes only while the goods slip is held at the intermediate store (status %)',
      coalesce(v_gs_status, 'missing') using errcode = 'P0001';
  end if;

  select gs_id, status into v_slip from public.ac_action_slips where id = new.ac_action_slip_id;
  if not found or v_slip.gs_id <> new.gs_id or v_slip.status <> 'CURRENT' then
    raise exception 'G-22: Accounts completes the CURRENT A/c Actions slip of the same goods slip'
      using errcode = 'P0001';
  end if;

  if not exists (select 1 from public.ac_entry_lines e where e.ac_action_slip_id = new.ac_action_slip_id) then
    raise exception 'G-22: the A/c Actions slip has no action lines' using errcode = 'P0001';
  end if;

  select e.line_no, e.action_label into v_open
    from public.ac_entry_lines e
   where e.ac_action_slip_id = new.ac_action_slip_id
     and not rms_private.ac_entry_line_complete(e)
   order by e.line_no
   limit 1;
  if found then
    raise exception 'G-22: item line % (%) still needs its Accounts data', v_open.line_no, v_open.action_label
      using errcode = 'P0001';
  end if;
  return new;
end;
$$;
revoke all on function rms_private.ac_entry_completions_guard() from public, anon, authenticated;

create trigger ac_entry_completions_guard
  before insert or update or delete on public.ac_entry_completions
  for each row execute function rms_private.ac_entry_completions_guard();

-- 4d. Dispatch Slip header: created after completion of its slip; READY -> DISPATCHED only.
create or replace function rms_private.dispatch_slips_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_att record;
begin
  if tg_op = 'DELETE' then
    raise exception 'G-22: Dispatch Slips are never deleted (%)', old.slip_no using errcode = '42501';
  end if;

  if tg_op = 'UPDATE' then
    if old.status <> 'READY' or new.status <> 'DISPATCHED'
       or (to_jsonb(new) - array['status', 'dispatch_date', 'transporter', 'docket_no', 'vehicle_no',
                                 'dispatch_remarks', 'dispatched_by', 'dispatched_at'])
          <> (to_jsonb(old) - array['status', 'dispatch_date', 'transporter', 'docket_no', 'vehicle_no',
                                    'dispatch_remarks', 'dispatched_by', 'dispatched_at']) then
      raise exception 'G-22: a Dispatch Slip is immutable; the only change is READY -> DISPATCHED'
        using errcode = '42501';
    end if;
    if new.dispatch_date > current_date then
      raise exception 'G-22: the dispatch date cannot be in the future' using errcode = 'P0001';
    end if;
    return new;
  end if;

  if not exists (select 1 from public.ac_entry_completions c
                  where c.ac_action_slip_id = new.ac_action_slip_id and c.gs_id = new.gs_id) then
    raise exception 'G-22: a Dispatch Slip is generated only after Accounts completed the A/c Actions slip'
      using errcode = 'P0001';
  end if;

  select gs_id, kind, status, mime_type into v_att from public.attachments where id = new.attachment_id;
  if not found or v_att.gs_id <> new.gs_id or v_att.kind <> 'GENERATED_PDF'
     or v_att.status <> 'CONFIRMED' or v_att.mime_type <> 'application/pdf' then
    raise exception 'G-22: the Dispatch Slip PDF must be a confirmed GENERATED_PDF attachment of the same goods slip'
      using errcode = 'P0001';
  end if;

  new.status := 'READY';
  new.dispatch_date := null;
  new.dispatched_by := null;
  new.dispatched_at := null;
  return new;
end;
$$;
revoke all on function rms_private.dispatch_slips_guard() from public, anon, authenticated;

create trigger dispatch_slips_guard
  before insert or update or delete on public.dispatch_slips
  for each row execute function rms_private.dispatch_slips_guard();

-- 4e. Dispatch Slip lines: insert-only, a shipping line (requires_challan) of the same slip, with the
--     Accounts challan data and qty copied unchanged.
create or replace function rms_private.dispatch_slip_lines_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_slip   record;
  v_entry  record;
begin
  if tg_op <> 'INSERT' then
    raise exception 'G-22: Dispatch Slip lines are immutable' using errcode = '42501';
  end if;

  select ac_action_slip_id, status into v_slip from public.dispatch_slips where id = new.dispatch_slip_id;
  select * into v_entry from public.ac_entry_lines where id = new.ac_entry_line_id;
  if v_slip.status is distinct from 'READY' then
    raise exception 'G-22: lines are added only while the Dispatch Slip is being generated'
      using errcode = 'P0001';
  end if;
  if v_entry.id is null or v_entry.ac_action_slip_id <> v_slip.ac_action_slip_id
     or not v_entry.requires_challan then
    raise exception 'G-22: a Dispatch Slip line must be a goods-shipping action line of the same A/c Actions slip'
      using errcode = 'P0001';
  end if;
  if new.qty <> v_entry.qty or new.gs_item_id <> v_entry.gs_item_id
     or new.action_code <> v_entry.action_code
     or new.challan_no is distinct from v_entry.challan_no
     or new.challan_date is distinct from v_entry.challan_date then
    raise exception 'G-22: a Dispatch Slip line copies its action line (qty, item, action, challan) unchanged'
      using errcode = 'P0001';
  end if;
  return new;
end;
$$;
revoke all on function rms_private.dispatch_slip_lines_guard() from public, anon, authenticated;

create trigger dispatch_slip_lines_guard
  before insert or update or delete on public.dispatch_slip_lines
  for each row execute function rms_private.dispatch_slip_lines_guard();

-- 4f. At commit: the Dispatch Slip covers exactly the shipping lines of its A/c Actions slip.
create or replace function rms_private.dispatch_slips_coverage_check()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_slip_id  uuid;
  v_ac_slip  uuid;
  v_missing  integer;
  v_lines    integer;
begin
  v_slip_id := new.id;
  select ac_action_slip_id into v_ac_slip from public.dispatch_slips where id = v_slip_id;

  select count(*) into v_missing
    from public.ac_entry_lines e
   where e.ac_action_slip_id = v_ac_slip
     and e.requires_challan
     and not exists (select 1 from public.dispatch_slip_lines l
                      where l.dispatch_slip_id = v_slip_id and l.ac_entry_line_id = e.id);
  select count(*) into v_lines from public.dispatch_slip_lines where dispatch_slip_id = v_slip_id;

  if v_missing > 0 or v_lines = 0 then
    raise exception 'G-22: the Dispatch Slip must list every goods-shipping action line (% missing, % listed)',
      v_missing, v_lines using errcode = 'P0001';
  end if;
  return null;
end;
$$;
revoke all on function rms_private.dispatch_slips_coverage_check() from public, anon, authenticated;

create constraint trigger dispatch_slips_coverage
  after insert on public.dispatch_slips
  deferrable initially deferred
  for each row execute function rms_private.dispatch_slips_coverage_check();

-- 4g. A/c Actions slip (Phase 7, applied; fixed forward here): it cannot be superseded once Accounts
--     completed it. Same body as 20261113001100 plus the G-22 check on UPDATE.
create or replace function rms_private.ac_action_slips_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_status    text;
  v_prev      record;
  v_max_rev   integer;
  v_att       record;
begin
  if tg_op = 'DELETE' then
    raise exception 'G-21: A/c Actions slips are never deleted (slip % v%)', old.slip_no, old.version_no
      using errcode = '42501';
  end if;

  if tg_op = 'UPDATE' then
    if old.status <> 'CURRENT' or new.status <> 'SUPERSEDED'
       or (to_jsonb(new) - array['status', 'superseded_at', 'superseded_by', 'supersede_reason'])
          <> (to_jsonb(old) - array['status', 'superseded_at', 'superseded_by', 'supersede_reason']) then
      raise exception 'G-21: an A/c Actions slip is immutable; the only change is CURRENT -> SUPERSEDED'
        using errcode = '42501';
    end if;
    -- AMD-18/19: Accounts completed this slip (Dispatch Slip / closure follow); it is final.
    if exists (select 1 from public.ac_entry_completions c where c.ac_action_slip_id = old.id) then
      raise exception 'G-22: Accounts completed A/c Actions slip % v%; it can no longer be revised',
        old.slip_no, old.version_no using errcode = 'P0001';
    end if;
    return new;
  end if;

  -- INSERT = finalise.
  select status into v_status from public.goods_slips where id = new.gs_id for update;
  if v_status is distinct from 'HELD_AT_INTERMEDIATE_STORE' then
    raise exception 'G-21: final actions are finalised only while the goods slip is held at the intermediate store (status %)',
      coalesce(v_status, 'missing') using errcode = 'P0001';
  end if;

  perform rms_private.validate_final_action_split(new.gs_id, true);

  select coalesce(max(act.revision_no), 0) into v_max_rev
    from public.rm_item_actions act
    join public.gs_items gi on gi.id = act.gs_item_id
   where gi.gs_id = new.gs_id;
  if new.revision_no <> v_max_rev then
    raise exception 'G-21: the slip must capture the latest action revision (%), not %', v_max_rev, new.revision_no
      using errcode = 'P0001';
  end if;

  select slip_no, version_no into v_prev
    from public.ac_action_slips where gs_id = new.gs_id order by version_no desc limit 1;
  if found then
    if new.slip_no <> v_prev.slip_no or new.version_no <> v_prev.version_no + 1 then
      raise exception 'G-21: the next slip version of this goods slip is % v%', v_prev.slip_no, v_prev.version_no + 1
        using errcode = 'P0001';
    end if;
  elsif new.version_no <> 1
        or exists (select 1 from public.ac_action_slips s where s.slip_no = new.slip_no) then
    raise exception 'G-21: the first slip of a goods slip is version 1 with a new slip number'
      using errcode = 'P0001';
  end if;

  select gs_id, kind, status, mime_type into v_att from public.attachments where id = new.attachment_id;
  if not found or v_att.gs_id <> new.gs_id or v_att.kind <> 'GENERATED_PDF'
     or v_att.status <> 'CONFIRMED' or v_att.mime_type <> 'application/pdf' then
    raise exception 'G-21: the slip PDF must be a confirmed GENERATED_PDF attachment of the same goods slip'
      using errcode = 'P0001';
  end if;

  new.status := 'CURRENT';
  new.superseded_at := null;
  new.superseded_by := null;
  new.supersede_reason := null;
  return new;
end;
$$;
revoke all on function rms_private.ac_action_slips_guard() from public, anon, authenticated;

-- 4h. The P3-05 replacement dispatch path stays for earlier goods slips; on the AMD-13 flow goods
--     ship only against a Dispatch Slip (AMD-19).
create or replace function rms_private.replacement_dispatches_amd_flow_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if rms_private.gs_on_final_action_flow(new.gs_id) then
    raise exception 'G-22: goods slip on the A/c Actions flow ships only against its Dispatch Slip (AMD-19)'
      using errcode = 'P0001';
  end if;
  return new;
end;
$$;
revoke all on function rms_private.replacement_dispatches_amd_flow_guard() from public, anon, authenticated;

create trigger replacement_dispatches_amd_flow_guard
  before insert on public.replacement_dispatches
  for each row execute function rms_private.replacement_dispatches_amd_flow_guard();

-- ===========================================================================
-- 5. Audit, RLS, grants
-- ===========================================================================
create trigger audit_row after insert or update or delete on public.ac_entry_lines
  for each row execute function rms_private.audit_row();
create trigger set_updated_at before update on public.ac_entry_lines
  for each row execute function rms_private.set_updated_at();
create trigger audit_row after insert or update or delete on public.ac_entry_completions
  for each row execute function rms_private.audit_row();
create trigger audit_row after insert or update or delete on public.dispatch_slips
  for each row execute function rms_private.audit_row();
create trigger audit_row after insert or update or delete on public.dispatch_slip_lines
  for each row execute function rms_private.audit_row();

alter table public.ac_entry_lines enable row level security;
alter table public.ac_entry_completions enable row level security;
alter table public.dispatch_slips enable row level security;
alter table public.dispatch_slip_lines enable row level security;

create policy ac_entry_lines_api_all on public.ac_entry_lines
  for all to rms_api using (true) with check (true);
create policy ac_entry_completions_api_all on public.ac_entry_completions
  for all to rms_api using (true) with check (true);
create policy dispatch_slips_api_all on public.dispatch_slips
  for all to rms_api using (true) with check (true);
create policy dispatch_slip_lines_api_all on public.dispatch_slip_lines
  for all to rms_api using (true) with check (true);

revoke all on public.ac_entry_lines, public.ac_entry_completions, public.dispatch_slips,
              public.dispatch_slip_lines from anon, authenticated;
grant select, insert, update on public.ac_entry_lines, public.ac_entry_completions,
                               public.dispatch_slips, public.dispatch_slip_lines to rms_api;

-- ===========================================================================
-- 6. Closure checklist (G-15) fix-forward for the AMD-13 flow
-- ===========================================================================
-- Same checklist as 20261105000300 (P3-07). Changes, all scoped to goods slips with an A/c Actions
-- slip (Phase 7/8 flow), plus one fix: a NULL category (AMD-13 flow) counts as "not CSR":
--   60 CN_DECISION_RECORDED is not applicable there (the RM's actions are the commercial decision);
--   65 AC_ENTRY_COMPLETE (AMD-18): Accounts completed the CURRENT A/c Actions slip;
--   85 DISPATCH_SLIP_DISPATCHED (AMD-19): the Dispatch Slip, if any, is dispatched;
--   90 PRIOR_NOTIFICATION (BR-38): a CN entered by Accounts needs a PRIOR_INFO_SENT record for the GS.
create or replace function rms_private.gs_closure_checklist(p_gs_id uuid)
returns table (
  sort_order  integer,
  code        text,
  rule_ref    text,
  applicable  boolean,
  passed      boolean,
  explanation text,
  details     jsonb
)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_gs            record;
  v_csr           boolean;
  v_rows          jsonb;
  v_count         integer;
  v_needs_dec     boolean;
  v_has_dec       boolean;
  v_issued        integer;
  v_ac_flow       boolean;
  v_ac_slip       record;
  v_completed     boolean;
  v_dslip         record;
  v_cn_lines      integer;
  v_notified      boolean;
begin
  select g.id, g.gs_no, g.status, g.category_code, g.has_discrepancy
    into v_gs from public.goods_slips g where g.id = p_gs_id;
  if not found then
    raise exception 'Goods slip % not found', p_gs_id using errcode = 'P0002';
  end if;
  -- category_code is NULL on the AMD-13 flow: NULL = 'CSR' would make the CSR rows NULL.
  v_csr := coalesce(v_gs.category_code = 'CSR', false);
  -- AMD-17/18: the GS is on the A/c Actions flow once the RM finalised a slip.
  v_ac_flow := exists (select 1 from public.ac_action_slips s where s.gs_id = p_gs_id);

  -- 1. Status (§6.5): closure follows the stock / commercial stages.
  return query select 10, 'GS_STATUS', '§6.5', true,
    v_gs.status in ('IN_PROCESS', 'COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION'),
    case when v_gs.status in ('IN_PROCESS', 'COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION')
         then 'The GS is in a closable stage (' || v_gs.status || ')'
         else 'The GS is ' || v_gs.status || '; only an in-process / commercial-resolution GS can close' end,
    jsonb_build_object('status', v_gs.status);

  -- 2. Nothing in TRANSIT, PENDING_HOLD or INWARD_STAGING, nothing marked Pending (BP) (G-15).
  select coalesce(jsonb_agg(jsonb_build_object(
           'lot_id', l.id, 'location_code', loc.code, 'location_class', loc.location_class,
           'condition_class', l.condition_class, 'qty', b.qty, 'is_pending', l.is_pending)
           order by loc.code), '[]'::jsonb), count(*)
    into v_rows, v_count
    from public.stock_lots l
    join public.stock_balances b on b.lot_id = l.id and b.qty > 0
    join public.inventory_locations loc on loc.id = b.location_id
   where l.gs_id = p_gs_id
     and (loc.location_class in ('TRANSIT', 'PENDING_HOLD', 'INWARD') or l.is_pending);
  return query select 20, 'STOCK_NOT_IN_TRANSIT', 'G-15', true, v_count = 0,
    case when v_count = 0 then 'No stock of this GS is in transit, pending hold or inward staging'
         else v_count || ' stock balance(s) still in transit / pending hold / inward staging' end,
    jsonb_build_object('lots', v_rows);

  -- 3. Every remaining piece is in a terminal or accounted location (G-15, BR-30).
  select coalesce(jsonb_agg(jsonb_build_object(
           'lot_id', l.id, 'location_code', loc.code, 'location_class', loc.location_class,
           'condition_class', l.condition_class, 'qty', b.qty,
           'reason', case when loc.location_class in ('REJECTED_HOLD', 'HAZARD_QUARANTINE')
                          then 'NO_DISPOSITION' else 'NOT_TERMINAL' end)
           order by loc.code), '[]'::jsonb), count(*)
    into v_rows, v_count
    from public.stock_lots l
    join public.stock_balances b on b.lot_id = l.id and b.qty > 0
    join public.inventory_locations loc on loc.id = b.location_id
   where l.gs_id = p_gs_id
     and not l.is_pending
     and loc.location_class not in ('TRANSIT', 'PENDING_HOLD', 'INWARD')
     and not (
       loc.location_class in ('MAIN_STORE', 'DISPATCHED', 'CREDITED', 'SCRAP_DISPOSED',
                              'SPARE_PARTS', 'NON_FUNCTIONAL')
       or (loc.location_class in ('REJECTED_HOLD', 'HAZARD_QUARANTINE')
           and exists (select 1 from public.rejections r where r.gs_item_id = l.gs_item_id))
     );
  return query select 30, 'STOCK_ACCOUNTED', 'G-15', true, v_count = 0,
    case when v_count = 0 then 'Every piece is issued, dispatched, with the Spare Parts Manager or on hold with a disposition'
         else v_count || ' stock balance(s) not yet in a terminal or accounted location' end,
    jsonb_build_object('lots', v_rows);

  -- 4. No open pendency (G-08 / G-15).
  select count(*) into v_count from public.pendencies p where p.gs_id = p_gs_id and p.status = 'OPEN';
  return query select 40, 'NO_OPEN_PENDENCY', 'G-08', true, v_count = 0,
    case when v_count = 0 then 'No open Pending (BP) pendency'
         else v_count || ' open Pending (BP) pendency(ies)' end,
    jsonb_build_object('open_pendencies', v_count);

  -- 5. No open discrepancy (custody transfer frozen in DISCREPANCY, or an unapproved adjustment).
  select count(*) into v_count
    from (
      select t.id from public.custody_transfers t
       where t.gs_id = p_gs_id and t.status = 'DISCREPANCY'
      union all
      select a.id from public.stock_adjustments a
        join public.stock_lots l on l.id = a.lot_id
       where l.gs_id = p_gs_id and a.status = 'REQUESTED'
    ) d;
  return query select 50, 'NO_OPEN_DISCREPANCY', 'G-15', true,
    v_count = 0 and not v_gs.has_discrepancy,
    case when v_count = 0 and not v_gs.has_discrepancy then 'No open custody discrepancy or stock adjustment'
         else greatest(v_count, 1) || ' open discrepancy / adjustment request(s)' end,
    jsonb_build_object('open_discrepancies', v_count, 'has_discrepancy_flag', v_gs.has_discrepancy);

  -- 6. RM Step-7 CN decision recorded where a commercial resolution is needed (BR-32). Not on the
  --    A/c Actions flow: there the RM's finalised actions are the decision (AMD-16/17).
  v_needs_dec := not v_ac_flow and (v_csr or exists (
    select 1 from public.rm_item_actions a
      join public.gs_items gi on gi.id = a.gs_item_id
     where gi.gs_id = p_gs_id and a.is_current
       and a.action_code in ('ISSUE_CN', 'SEND_NEW', 'SEND_REPAIRED')));
  v_has_dec := exists (select 1 from public.rm_cn_decisions d where d.gs_id = p_gs_id and d.is_current);
  return query select 60, 'CN_DECISION_RECORDED', 'BR-32', v_needs_dec, (not v_needs_dec) or v_has_dec,
    case when v_ac_flow then 'On the A/c Actions flow the Replacement Manager''s finalised actions are the decision'
         when not v_needs_dec then 'No commercial resolution needed (no CN / replacement action)'
         when v_has_dec then 'The Replacement Manager''s CN decision is recorded'
         else 'The Replacement Manager''s Step-7 CN decision is missing' end,
    jsonb_build_object('decision_recorded', v_has_dec);

  -- 6b. AMD-18: Accounts completed the CURRENT A/c Actions slip (CN / Challan per action line).
  select s.id, s.slip_no, s.version_no into v_ac_slip
    from public.ac_action_slips s where s.gs_id = p_gs_id and s.status = 'CURRENT';
  v_completed := v_ac_slip.id is not null
                 and exists (select 1 from public.ac_entry_completions c where c.ac_action_slip_id = v_ac_slip.id);
  return query select 65, 'AC_ENTRY_COMPLETE', 'AMD-18', v_ac_flow, (not v_ac_flow) or v_completed,
    case when not v_ac_flow then 'Not on the A/c Actions flow'
         when v_ac_slip.id is null then 'No CURRENT A/c Actions slip (being revised by the Replacement Manager)'
         when v_completed then 'Accounts completed the CN / Challan entry of ' || v_ac_slip.slip_no || ' v' || v_ac_slip.version_no
         else 'Accounts has not completed the CN / Challan entry of ' || v_ac_slip.slip_no || ' v' || v_ac_slip.version_no end,
    jsonb_build_object('ac_action_slip_id', v_ac_slip.id, 'completed', v_completed);

  -- 7. Every ALLOW_CN qty is covered by ISSUED credit notes / JVs (G-13, G-15).
  with allowed as (
    select dl.gs_item_id, sum(dl.qty)::int as qty
      from public.rm_cn_decisions d
      join public.rm_cn_decision_lines dl on dl.decision_id = d.id
     where d.gs_id = p_gs_id and d.is_current and dl.decision_code = 'ALLOW_CN'
     group by dl.gs_item_id),
  issued as (
    select cl.gs_item_id, sum(cl.qty)::int as qty
      from public.credit_notes cn
      join public.credit_note_lines cl on cl.credit_note_id = cn.id
     where cn.gs_id = p_gs_id and cn.status = 'ISSUED'
     group by cl.gs_item_id)
  select coalesce(jsonb_agg(jsonb_build_object(
           'gs_item_id', a.gs_item_id, 'line_no', gi.line_no, 'allowed_qty', a.qty,
           'issued_qty', coalesce(i.qty, 0)) order by gi.line_no), '[]'::jsonb),
         count(*) filter (where coalesce(i.qty, 0) < a.qty)
    into v_rows, v_count
    from allowed a
    join public.gs_items gi on gi.id = a.gs_item_id
    left join issued i on i.gs_item_id = a.gs_item_id;
  return query select 70, 'ALLOW_CN_COVERED', 'G-15', jsonb_array_length(v_rows) > 0, v_count = 0,
    case when jsonb_array_length(v_rows) = 0 then 'No quantity allowed for credit note'
         when v_count = 0 then 'Every ALLOW_CN quantity is covered by an issued CN / JV'
         else v_count || ' line(s) with ALLOW_CN quantity not yet covered by an issued CN / JV' end,
    jsonb_build_object('lines', v_rows);

  -- 8. Every DENY_CN_SEND_REPLACEMENT qty is dispatched (G-15).
  with denied as (
    select dl.gs_item_id, sum(dl.qty)::int as qty
      from public.rm_cn_decisions d
      join public.rm_cn_decision_lines dl on dl.decision_id = d.id
     where d.gs_id = p_gs_id and d.is_current and dl.decision_code = 'DENY_CN_SEND_REPLACEMENT'
     group by dl.gs_item_id),
  dispatched as (
    select rl.gs_item_id, sum(rl.qty)::int as qty
      from public.replacement_dispatches rd
      join public.replacement_dispatch_lines rl on rl.dispatch_id = rd.id
     where rd.gs_id = p_gs_id and rd.status = 'DISPATCHED'
     group by rl.gs_item_id)
  select coalesce(jsonb_agg(jsonb_build_object(
           'gs_item_id', d.gs_item_id, 'line_no', gi.line_no, 'denied_qty', d.qty,
           'dispatched_qty', coalesce(x.qty, 0)) order by gi.line_no), '[]'::jsonb),
         count(*) filter (where coalesce(x.qty, 0) < d.qty)
    into v_rows, v_count
    from denied d
    join public.gs_items gi on gi.id = d.gs_item_id
    left join dispatched x on x.gs_item_id = d.gs_item_id;
  return query select 80, 'DENY_QTY_DISPATCHED', 'G-15', jsonb_array_length(v_rows) > 0, v_count = 0,
    case when jsonb_array_length(v_rows) = 0 then 'No quantity denied for credit note'
         when v_count = 0 then 'Every replacement (CN denied) quantity is dispatched'
         else v_count || ' line(s) with a replacement not yet dispatched' end,
    jsonb_build_object('lines', v_rows);

  -- 8b. AMD-19: the Dispatch Slip of the goods-shipping lines is dispatched.
  select d.id, d.slip_no, d.status into v_dslip from public.dispatch_slips d where d.gs_id = p_gs_id;
  return query select 85, 'DISPATCH_SLIP_DISPATCHED', 'AMD-19', v_dslip.id is not null,
    v_dslip.id is null or v_dslip.status = 'DISPATCHED',
    case when v_dslip.id is null then 'No Dispatch Slip (no action line ships goods, or Accounts not complete yet)'
         when v_dslip.status = 'DISPATCHED' then 'Dispatch Slip ' || v_dslip.slip_no || ' is dispatched'
         else 'Dispatch Slip ' || v_dslip.slip_no || ' is not dispatched yet' end,
    jsonb_build_object('dispatch_slip_id', v_dslip.id, 'status', v_dslip.status);

  -- 9. Every issued CN / JV has a PRIOR_INFO_SENT notification (BR-38, DD r79, G-15). On the A/c
  --    Actions flow a CN entered by Accounts needs a PRIOR_INFO_SENT record of the goods slip.
  select coalesce(jsonb_agg(jsonb_build_object(
           'credit_note_id', cn.id, 'voucher_no', coalesce(cn.cn_no, cn.jv_no),
           'cn_type_code', cn.cn_type_code,
           'notified', exists (select 1 from public.party_notifications pn
                                where pn.credit_note_id = cn.id and pn.status_code = 'PRIOR_INFO_SENT'))
           order by cn.issued_at), '[]'::jsonb), count(*)
    into v_rows, v_issued
    from public.credit_notes cn
   where cn.gs_id = p_gs_id and cn.status = 'ISSUED';
  select count(*) into v_count from jsonb_array_elements(v_rows) e where not (e->>'notified')::boolean;

  select count(*) into v_cn_lines
    from public.ac_entry_lines e
   where e.ac_action_slip_id = v_ac_slip.id and e.cn_no is not null;
  v_notified := exists (select 1 from public.party_notifications pn
                         where pn.gs_id = p_gs_id and pn.status_code = 'PRIOR_INFO_SENT');
  if v_cn_lines > 0 and not v_notified then
    v_count := v_count + 1;
  end if;

  return query select 90, 'PRIOR_NOTIFICATION', 'BR-38', v_issued > 0 or v_cn_lines > 0, v_count = 0,
    case when v_issued = 0 and v_cn_lines = 0 then 'No CN / JV issued, so no prior notification is required'
         when v_count = 0 then 'The party was notified of every issued CN / JV before closure'
         when v_cn_lines > 0 and not v_notified then 'The party has not been notified of the CN(s) entered by Accounts (PRIOR_INFO_SENT)'
         else v_count || ' issued CN / JV without a prior party notification (PRIOR_INFO_SENT)' end,
    jsonb_build_object('credit_notes', v_rows, 'ac_entry_cn_lines', v_cn_lines, 'gs_notified', v_notified);

  -- 10–12. Complete Sales Return closure (BR-09, BR-39, DD r80).
  select count(*) into v_count
    from public.custody_transfers t
   where t.gs_id = p_gs_id and t.purpose_code = 'CSR_WITH_PACKAGING' and t.with_packaging
     and t.status in ('ACCEPTED', 'RECONCILED');
  return query select 100, 'CSR_PACKAGING_HANDOVER', 'BR-39', v_csr, (not v_csr) or v_count > 0,
    case when not v_csr then 'Not a Complete Sales Return'
         when v_count > 0 then 'The goods were handed over with packaging and accepted'
         else 'The CSR handover with packaging has not been accepted yet' end,
    jsonb_build_object('accepted_transfers', v_count);

  select count(*) into v_count
    from public.packaging_replacements pr
    join public.stock_lots l on l.id = pr.lot_id
   where l.gs_id = p_gs_id;
  return query select 110, 'CSR_PACKAGING_CHECK', 'BR-39', v_csr, (not v_csr) or v_count > 0,
    case when not v_csr then 'Not a Complete Sales Return'
         when v_count > 0 then 'The packaging check is recorded'
         else 'No packaging check is recorded for this CSR' end,
    jsonb_build_object('packaging_checks', v_count);

  return query select 120, 'CSR_CN_ISSUED', 'BR-39', v_csr, (not v_csr) or v_issued > 0 or v_cn_lines > 0,
    case when not v_csr then 'Not a Complete Sales Return'
         when v_issued > 0 or v_cn_lines > 0 then 'A credit note / JV is issued'
         else 'No credit note / JV is issued for this CSR' end,
    jsonb_build_object('issued_credit_notes', v_issued, 'ac_entry_cn_lines', v_cn_lines);
end
$$;
revoke all on function rms_private.gs_closure_checklist(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_closure_checklist(uuid) to rms_api;

-- ===========================================================================
-- 7. Config: number series, print template, setting, notifications, permissions, guard events
-- ===========================================================================
insert into public.number_series (code, name, prefix, pattern, reset_policy, fy_start_month, fy_format)
values ('DISPATCH_SLIP', 'Dispatch Slip', 'DS', '{PREFIX}/{FY}/{SEQ:5}', 'YEARLY_FY', 4, 'LONG')
on conflict (code) do nothing;

alter table public.print_templates drop constraint print_templates_code_check;
alter table public.print_templates
  add constraint print_templates_code_check check (
    code in ('REPLACEMENT_SLIP', 'GS_TAG', 'CN_SUMMARY', 'TRANSFER_NOTE', 'STORE_ISSUE', 'AC_ACTIONS_SLIP',
             'DISPATCH_SLIP'));

-- DEC-41: one server-side template per slip; branding / titles / signatures are configuration.
do $$
declare
  v_layout jsonb := jsonb_build_object(
    'paper_size', 'A4',
    'orientation', 'portrait',
    'show_logo', false,
    'header_title', 'HICKS THERMOMETERS (INDIA) LIMITED',
    'header_subtitle', 'Dispatch Slip',
    'footer_text', 'Computer generated by RMS. Issue goods against this slip and record the dispatch in RMS.',
    'sections', jsonb_build_array(
      jsonb_build_object('id', 'header', 'title', 'Dispatch Slip',
        'fields', jsonb_build_array('slip_no', 'gs_no', 'ac_slip_no', 'generated_at')),
      jsonb_build_object('id', 'party', 'title', 'Ship To',
        'fields', jsonb_build_array('party_name', 'party_code', 'state_station')),
      jsonb_build_object('id', 'items', 'title', 'Goods to Ship',
        'fields', jsonb_build_array('line_no', 'product_code', 'product_name', 'action_label', 'qty', 'challan_no', 'challan_date')),
      jsonb_build_object('id', 'signatures', 'title', 'Signatures',
        'fields', jsonb_build_array('signature_blocks'))
    ),
    'signature_blocks', jsonb_build_array(
      jsonb_build_object('label', 'Prepared By', 'role', 'Accounts'),
      jsonb_build_object('label', 'Issued By', 'role', 'Store'),
      jsonb_build_object('label', 'Dispatched By', 'role', 'Dispatch')
    )
  );
begin
  if not exists (select 1 from public.print_templates where code = 'DISPATCH_SLIP') then
    insert into public.print_templates (code, name, version_no, layout, status, snapshot, published_at)
    values ('DISPATCH_SLIP', 'Dispatch Slip', 1, v_layout, 'PUBLISHED', v_layout, now());
  end if;
end
$$;

-- DEC-47 (PROVISIONAL): where the RETURNED pieces of each action line go when the goods slip's
-- commercial work completes (dispatch, or Accounts completion when nothing ships). Keyed by stable
-- action codes (rule e); an action without an entry leaves its pieces where they are (the closure
-- checklist then shows them, G-15). SEND_NEW ships new stock outside the RMS ledger (DEC-26).
insert into public.system_settings (key, value, category, description, source_ref) values
  ('dispatch.returned_goods_location_by_action',
   '{"SEND_REPAIRED": "DISPATCHED", "ISSUE_CN": "CREDITED"}'::jsonb, 'dispatch',
   'Per action code: inventory location code that receives the returned pieces of the action line when the A/c Actions flow completes (dispatch / Accounts completion). Actions not listed keep their pieces in place (DEC-47).',
   'DEC-47')
on conflict (key) do nothing;

insert into public.notification_event_types
  (code, label, description, category, default_priority, is_mandatory, source_ref, sort_order)
values
  ('AC_ENTRY_COMPLETED', 'Accounts entry completed',
   'Accounts entered CN / Challan details for every action line of the A/c Actions slip (AMD-18).',
   'COMMERCIAL', 'NORMAL', false, 'AMD-18', 530),
  ('DISPATCH_SLIP_READY', 'Dispatch Slip ready',
   'A numbered Dispatch Slip was generated for the goods-shipping action lines of a goods slip (AMD-19).',
   'COMMERCIAL', 'HIGH', false, 'AMD-19', 540),
  ('DISPATCH_SLIP_DISPATCHED', 'Dispatch Slip dispatched',
   'The Dispatch team issued and dispatched the goods of a Dispatch Slip (AMD-19).',
   'COMMERCIAL', 'NORMAL', false, 'AMD-19', 550)
on conflict (code) do nothing;

insert into public.notification_templates (event_type, channel, version_no, subject, body, change_reason)
select v.event_type, 'EMAIL', 1,
       '[{app_name}] {title}',
       E'Hello {recipient_name},\n\n{title}\n\n{body}\n\nEvent: {event_label}\nPriority: {priority}\nOpen in RMS: {link}\n\n— {app_name} (automated message; manage email preferences in RMS)',
       'Phase 8 default'
  from (values ('AC_ENTRY_COMPLETED'), ('DISPATCH_SLIP_READY'), ('DISPATCH_SLIP_DISPATCHED')) as v(event_type)
 where not exists (
   select 1 from public.notification_templates where event_type = v.event_type and channel = 'EMAIL'
 );

-- Role grants are in seed.sql (_seed_role_matrix): roles are seed data.
insert into public.permissions (module_code, action, description)
values
  ('ac_entry', 'view',   'View the Accounts work queue and entries (AMD-18)'),
  ('ac_entry', 'edit',   'Enter CN / Challan details per action line and complete (AMD-18)'),
  ('ac_entry', 'export', 'Print / download the Dispatch Slip PDF (AMD-19)')
on conflict (module_code, action) do nothing;

alter table public.system_guard_events
  drop constraint if exists system_guard_events_guard_code_check;
alter table public.system_guard_events
  add constraint system_guard_events_guard_code_check
  check (guard_code ~ '^G-(0[1-9]|1[0-9]|2[0-2])$');
