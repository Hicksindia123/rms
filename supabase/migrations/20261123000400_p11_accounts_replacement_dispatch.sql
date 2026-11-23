-- =============================================================================================
-- Phase P11 (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-71 (Q19 PROVISIONAL; Q21, Q22 CONFIRMED).
-- Accounts gate, Replacement Slip per goods slip, one Challan / CN per goods slip, Dispatch Slip
-- (Steps 11–12 of the 20-11-2026 flow).
--
-- A store-flow goods slip leaves ANALYSIS_COMPLETED when every Intermediate Store with goods on it
-- submitted its analysis (DEC-69) and the Management gate passes (DEC-70: no open request, Issue CN
-- only with a VALID approval, no unapproved Management change):
--   * some decision needs a Challan or a Credit Note (action flags requires_challan / requires_cn,
--     AMD-18)        → ACCOUNTS_PENDING ("At Accounts") and one Replacement Slip is created (the
--                       A/c Actions slip reused, ac_action_slips round 1; versioned when Management
--                       later changes the goods slip);
--   * nothing does (every decision Not Allowed, Q21) → NOT_ALLOWED_HOLD (on hold, no Accounts).
-- Accounts enters ONE Challan No. + Date (only if the GS ships goods) and ONE CN No. + Date + Value
-- (only if it has Issue CN) per goods slip (new table ac_gs_entries; the per-line ac_entry_lines
-- stay as the line breakdown and stay readable for legacy goods slips, DEC-47). Completion:
--   * goods ship → Dispatch Slip (dispatch_slips reused) → DISPATCH_PENDING; dispatch settles the
--     returned pieces (DEC-57 destinations, rms_move_stock) → IN_PROCESS (closure engine);
--   * nothing ships (Issue CN only) → pieces settled at completion → IN_PROCESS.
-- Management may still change a goods slip at Accounts (entry not completed) or on hold: the
-- current Replacement Slip is withdrawn (SUPERSEDED) and the goods slip returns to
-- ANALYSIS_COMPLETED; the next approval routes it again (Replacement Slip v+1).
--
-- 1. Statuses ACCOUNTS_PENDING, NOT_ALLOWED_HOLD, DISPATCH_PENDING.
-- 2. Helper gs_needs_accounts.
-- 3. ac_gs_entries (one per Replacement Slip version) + guard + creation with the slip.
-- 4. A/c (Replacement) slip guard: store flow = ACCOUNTS_PENDING, one round, G-21 per store.
-- 5. Deferred check: a goods slip at Accounts has its CURRENT Replacement Slip.
-- 6. G-22 guards: entry lines (per-GS data on the store flow; CN unique across both tables),
--    completion (per-GS entry complete), Dispatch Slip lines (the GS challan).
-- 7. G-03 status chain (full body: 20261123000300 body + DEC-71).
-- 8. Closure checklist (G-15): the per-GS CN counts for the prior party notification (BR-38).
-- 9. Notification event type GS_NOT_ALLOWED_HOLD (rules: seed + snippet).
-- Status labels, the "Replacement Slip" template name and the alert rule: seed.sql + snippet
-- release_20261123_p11_accounts_replacement_slip.sql (phase prompts §0 rule 3).
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- 1. Statuses
-- ---------------------------------------------------------------------------------------------
alter table public.goods_slips drop constraint goods_slips_status_check;
alter table public.goods_slips
  add constraint goods_slips_status_check check (status in (
    'GATE_CREATED', 'UNBOXING', 'ITEMIZATION', 'CATEGORISATION', 'CSR_APPROVAL_PENDING',
    'INSPECTION', 'RM_REVIEW', 'PENDING_TRANSFER_SLIP', 'TRANSFER_SLIP_GENERATED',
    'STORE_ACKNOWLEDGED', 'STORE_PROCESSING', 'ANALYSIS_COMPLETED', 'ACCOUNTS_PENDING',
    'NOT_ALLOWED_HOLD', 'DISPATCH_PENDING', 'SALES_RETURN_HOLD',
    'HELD_AT_INTERMEDIATE_STORE', 'IN_PROCESS', 'COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION',
    'CLOSED', 'CANCELLED'));

-- ---------------------------------------------------------------------------------------------
-- 2. Helper
-- ---------------------------------------------------------------------------------------------
-- DEC-71 (Q21): some current decision of the goods slip needs Accounts data (a Challan because
-- goods ship, or a Credit Note). Keyed off the ACTION library flags (AMD-18), never off codes.
create or replace function rms_private.gs_needs_accounts(p_gs_id uuid)
returns boolean
language sql
stable
set search_path = ''
as $$
  select exists (
    select 1 from public.rm_item_actions a
      join public.gs_items gi on gi.id = a.gs_item_id
      join public.item_field_library lib on lib.field_group = 'ACTION' and lib.code = a.action_code
     where gi.gs_id = p_gs_id and a.is_current and a.qty > 0
       and (lib.requires_challan or lib.requires_cn))
$$;
revoke all on function rms_private.gs_needs_accounts(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_needs_accounts(uuid) to rms_api;

-- ---------------------------------------------------------------------------------------------
-- 3. One Challan / CN per goods slip (per Replacement Slip version)
-- ---------------------------------------------------------------------------------------------
create table public.ac_gs_entries (
  id                 uuid primary key default gen_random_uuid(),
  gs_id              uuid not null references public.goods_slips (id) on delete restrict,
  ac_action_slip_id  uuid not null unique references public.ac_action_slips (id) on delete restrict,
  -- Snapshot of the slip's lines (G-18): does any line ship goods / need a credit note.
  requires_challan   boolean not null,
  requires_cn        boolean not null,
  challan_no         text check (challan_no is null or (btrim(challan_no) <> '' and length(challan_no) <= 60)),
  challan_date       date,
  cn_no              text check (cn_no is null or (btrim(cn_no) <> '' and length(cn_no) <= 60)),
  cn_date            date,
  cn_value           numeric(14, 2) check (cn_value is null or cn_value > 0),
  entered_by         uuid references public.profiles (id) on delete restrict,
  entered_at         timestamptz,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  constraint ac_gs_entries_needs_something check (requires_challan or requires_cn),
  constraint ac_gs_entries_challan_pair check ((challan_no is null) = (challan_date is null)),
  constraint ac_gs_entries_cn_triple check ((cn_no is null) = (cn_date is null)
                                            and (cn_no is null) = (cn_value is null)),
  -- DEC-71: a field group exists only where the goods slip needs it (hidden = not sent, not stored).
  constraint ac_gs_entries_challan_only_if_required check (requires_challan or challan_no is null),
  constraint ac_gs_entries_cn_only_if_required check (requires_cn or cn_no is null)
);
create index ac_gs_entries_gs_idx on public.ac_gs_entries (gs_id);
create index ac_gs_entries_cn_no_idx on public.ac_gs_entries (upper(btrim(cn_no))) where cn_no is not null;
comment on table public.ac_gs_entries is
  'DEC-71: Accounts entry per goods slip on the Intermediate Store flow: one Challan No. + Date (only if goods ship) and one CN No. + Date + Value (only if the GS has Issue CN), per Replacement Slip version.';

create or replace function rms_private.ac_gs_entry_complete(p public.ac_gs_entries)
returns boolean
language sql
immutable
set search_path = ''
as $$
  select (not p.requires_challan or (p.challan_no is not null and p.challan_date is not null))
     and (not p.requires_cn or (p.cn_no is not null and p.cn_date is not null and p.cn_value is not null))
$$;
revoke all on function rms_private.ac_gs_entry_complete(public.ac_gs_entries) from public, anon, authenticated;
grant execute on function rms_private.ac_gs_entry_complete(public.ac_gs_entries) to rms_api;

create or replace function rms_private.ac_gs_entries_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_slip      record;
  v_status    text;
  v_flags     record;
  v_other_gs  text;
begin
  if tg_op = 'DELETE' then
    raise exception 'G-22: Accounts entries are never deleted' using errcode = '42501';
  end if;

  select gs_id, status into v_slip from public.ac_action_slips where id = new.ac_action_slip_id;
  if not found or v_slip.gs_id <> new.gs_id then
    raise exception 'G-22: the Accounts entry belongs to a Replacement Slip of the same goods slip'
      using errcode = 'P0001';
  end if;

  if tg_op = 'INSERT' then
    -- Created with the Replacement Slip: flags = what its lines need, no data yet.
    select coalesce(bool_or(e.requires_challan), false) as ch, coalesce(bool_or(e.requires_cn), false) as cn
      into v_flags
      from public.ac_entry_lines e where e.ac_action_slip_id = new.ac_action_slip_id;
    if new.requires_challan is distinct from v_flags.ch or new.requires_cn is distinct from v_flags.cn
       or new.challan_no is not null or new.cn_no is not null then
      raise exception 'G-22: the Accounts entry of a Replacement Slip starts empty with the slip''s Challan / CN needs'
        using errcode = 'P0001';
    end if;
    new.entered_by := null;
    new.entered_at := null;
    return new;
  end if;

  -- UPDATE: only the Accounts fields, only on the CURRENT slip while the GS is at Accounts.
  if (to_jsonb(new) - array['challan_no', 'challan_date', 'cn_no', 'cn_date', 'cn_value',
                            'entered_by', 'entered_at', 'updated_at'])
     <> (to_jsonb(old) - array['challan_no', 'challan_date', 'cn_no', 'cn_date', 'cn_value',
                               'entered_by', 'entered_at', 'updated_at']) then
    raise exception 'G-22: only the Challan / CN fields of an Accounts entry can change' using errcode = '42501';
  end if;
  select status into v_status from public.goods_slips where id = new.gs_id for update;
  if v_slip.status is distinct from 'CURRENT' then
    raise exception 'G-22: the Replacement Slip of this entry is superseded; enter the data on the current version'
      using errcode = 'P0001';
  end if;
  if v_status is distinct from 'ACCOUNTS_PENDING' then
    raise exception 'G-22: Accounts data changes only while the goods slip is at Accounts (status %)', v_status
      using errcode = 'P0001';
  end if;
  if exists (select 1 from public.ac_entry_completions c where c.ac_action_slip_id = new.ac_action_slip_id) then
    raise exception 'G-22: the Accounts entry of this Replacement Slip is complete and frozen'
      using errcode = 'P0001';
  end if;
  if new.cn_date > current_date or new.challan_date > current_date then
    raise exception 'G-22: CN / Challan dates cannot be in the future' using errcode = 'P0001';
  end if;
  if new.challan_no is not null and not new.requires_challan then
    raise exception 'G-22: this goods slip ships no goods; it takes no Challan (DEC-71)' using errcode = 'P0001';
  end if;
  if new.cn_no is not null and not new.requires_cn then
    raise exception 'G-22: this goods slip has no Issue CN; it takes no Credit Note (DEC-71)' using errcode = 'P0001';
  end if;

  -- DEC-22: an external CN voucher number is used on one goods slip only (case-insensitive), across
  -- the per-GS entries, the legacy per-line entries and the credit notes.
  if new.cn_no is not null then
    perform pg_advisory_xact_lock(hashtext('ac_entry_cn_no:' || upper(btrim(new.cn_no))));
    select g.gs_no into v_other_gs
      from (select e.gs_id from public.ac_gs_entries e
             where upper(btrim(e.cn_no)) = upper(btrim(new.cn_no)) and e.gs_id <> new.gs_id
            union all
            select l.gs_id from public.ac_entry_lines l
             where upper(btrim(l.cn_no)) = upper(btrim(new.cn_no)) and l.gs_id <> new.gs_id) x
      join public.goods_slips g on g.id = x.gs_id
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
revoke all on function rms_private.ac_gs_entries_guard() from public, anon, authenticated;
create trigger ac_gs_entries_guard
  before insert or update or delete on public.ac_gs_entries
  for each row execute function rms_private.ac_gs_entries_guard();

alter table public.ac_gs_entries enable row level security;
create policy ac_gs_entries_api_all on public.ac_gs_entries
  for all to rms_api using (true) with check (true);
revoke all on public.ac_gs_entries from anon, authenticated;
grant select, insert, update on public.ac_gs_entries to rms_api;
select rms_private.attach_standard_triggers('public.ac_gs_entries');

-- The per-GS entry is created with every store-flow Replacement Slip version. Runs after
-- ac_action_slips_create_entry_lines (triggers of one event fire in name order), so the slip's
-- lines and their flags exist.
create or replace function rms_private.ac_action_slips_create_gs_entry()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if rms_private.gs_on_store_flow(new.gs_id) then
    insert into public.ac_gs_entries (gs_id, ac_action_slip_id, requires_challan, requires_cn)
    select new.gs_id, new.id, coalesce(bool_or(e.requires_challan), false), coalesce(bool_or(e.requires_cn), false)
      from public.ac_entry_lines e
     where e.ac_action_slip_id = new.id;
  end if;
  return null;
end;
$$;
revoke all on function rms_private.ac_action_slips_create_gs_entry() from public, anon, authenticated;
create trigger ac_action_slips_create_gs_entry
  after insert on public.ac_action_slips
  for each row execute function rms_private.ac_action_slips_create_gs_entry();

-- ---------------------------------------------------------------------------------------------
-- 4. A/c (Replacement) slip guard (full body: 20261118000300 body + the DEC-71 store flow)
-- ---------------------------------------------------------------------------------------------
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
  v_store     boolean;
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
    if exists (select 1 from public.ac_entry_completions c where c.ac_action_slip_id = old.id) then
      raise exception 'G-22: Accounts completed A/c Actions slip % v%; it can no longer be revised',
        old.slip_no, old.version_no using errcode = 'P0001';
    end if;
    return new;
  end if;

  -- INSERT = finalise a round.
  select status into v_status from public.goods_slips where id = new.gs_id for update;
  v_store := rms_private.gs_on_store_flow(new.gs_id);
  if v_store then
    -- DEC-71 (P11): on the Intermediate Store flow the Replacement Slip (one per GS, one round) is
    -- created when the goods slip reaches Accounts; a Management change later gives a new version.
    if new.round_no <> 1 then
      raise exception 'DEC-71: a store-flow goods slip has one Replacement Slip round (got round %)', new.round_no
        using errcode = 'P0001';
    end if;
    if v_status is distinct from 'ACCOUNTS_PENDING' then
      raise exception 'DEC-71: the Replacement Slip is created when the goods slip reaches Accounts (status %)',
        coalesce(v_status, 'missing') using errcode = 'P0001';
    end if;
  elsif new.round_no = 1 then
    if v_status is distinct from 'HELD_AT_INTERMEDIATE_STORE' then
      raise exception 'G-21: final actions are finalised only while the goods slip is held at the intermediate store (status %)',
        coalesce(v_status, 'missing') using errcode = 'P0001';
    end if;
  else
    if v_status is null or v_status not in ('IN_PROCESS', 'COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION') then
      raise exception 'G-21: a Pending re-action is finalised only while the goods slip is open after the store stage (status %)',
        coalesce(v_status, 'missing') using errcode = 'P0001';
    end if;
    if not rms_private.final_action_round_settled(new.gs_id, new.round_no - 1) then
      raise exception 'G-21: round % is not completed by Accounts and settled yet', new.round_no - 1
        using errcode = 'P0001';
    end if;
  end if;

  if not exists (select 1 from public.rm_item_actions act
                   join public.gs_items gi on gi.id = act.gs_item_id
                  where gi.gs_id = new.gs_id and act.is_current and act.round_no = new.round_no) then
    raise exception 'G-21: no final actions are recorded for round %', new.round_no
      using errcode = 'P0001';
  end if;
  if exists (select 1 from public.rm_item_actions act
               join public.gs_items gi on gi.id = act.gs_item_id
              where gi.gs_id = new.gs_id and act.is_current and act.round_no > new.round_no) then
    raise exception 'G-21: a later re-action round exists; round % cannot be finalised', new.round_no
      using errcode = 'P0001';
  end if;

  if v_store then
    perform rms_private.validate_store_analysis(new.gs_id);   -- G-21 per store (DEC-69)
  else
    perform rms_private.validate_final_action_split(new.gs_id, true);
  end if;

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

-- ---------------------------------------------------------------------------------------------
-- 5. A goods slip at Accounts always has its CURRENT Replacement Slip (checked at commit: the
--    service moves the status first, then creates the slip in the same transaction).
-- ---------------------------------------------------------------------------------------------
create or replace function rms_private.goods_slips_accounts_slip_check()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if exists (select 1 from public.goods_slips g
              where g.id = new.id and g.status = 'ACCOUNTS_PENDING')
     and not exists (select 1 from public.ac_action_slips s
                      where s.gs_id = new.id and s.status = 'CURRENT') then
    raise exception 'DEC-71: a goods slip at Accounts must have its CURRENT Replacement Slip'
      using errcode = '23514';
  end if;
  return null;
end;
$$;
revoke all on function rms_private.goods_slips_accounts_slip_check() from public, anon, authenticated;
create constraint trigger goods_slips_accounts_slip_check
  after update of status on public.goods_slips
  deferrable initially deferred
  for each row when (new.status = 'ACCOUNTS_PENDING')
  execute function rms_private.goods_slips_accounts_slip_check();

-- A withdrawn (superseded) Replacement Slip of a goods slip that stays at Accounts is checked too.
create or replace function rms_private.ac_action_slips_accounts_slip_check()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if exists (select 1 from public.goods_slips g
              where g.id = new.gs_id and g.status = 'ACCOUNTS_PENDING')
     and not exists (select 1 from public.ac_action_slips s
                      where s.gs_id = new.gs_id and s.status = 'CURRENT') then
    raise exception 'DEC-71: a goods slip at Accounts must have its CURRENT Replacement Slip'
      using errcode = '23514';
  end if;
  return null;
end;
$$;
revoke all on function rms_private.ac_action_slips_accounts_slip_check() from public, anon, authenticated;
create constraint trigger ac_action_slips_accounts_slip_check
  after update of status on public.ac_action_slips
  deferrable initially deferred
  for each row when (new.status = 'SUPERSEDED')
  execute function rms_private.ac_action_slips_accounts_slip_check();

-- ---------------------------------------------------------------------------------------------
-- 6. G-22 guards (full bodies: 20261118000300 / 20261114000100 bodies + DEC-71)
-- ---------------------------------------------------------------------------------------------
create or replace function rms_private.ac_entry_lines_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_slip         record;
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
  select status, round_no into v_slip from public.ac_action_slips where id = new.ac_action_slip_id;

  if tg_op = 'UPDATE' then
    -- DEC-71 (P11): a store-flow goods slip takes one Challan / CN per goods slip (ac_gs_entries).
    if rms_private.gs_on_store_flow(new.gs_id)
       and (new.cn_no, new.cn_date, new.cn_value, new.challan_no, new.challan_date)
           is distinct from (old.cn_no, old.cn_date, old.cn_value, old.challan_no, old.challan_date) then
      raise exception 'DEC-71: Accounts data of a store-flow goods slip is entered once per goods slip, not per line'
        using errcode = 'P0001';
    end if;
    if v_slip.status is distinct from 'CURRENT' then
      raise exception 'G-22: the A/c Actions slip of this line is superseded; enter the data on the current version'
        using errcode = 'P0001';
    end if;
    if v_slip.round_no = 1 and v_gs_status is distinct from 'HELD_AT_INTERMEDIATE_STORE' then
      raise exception 'G-22: Accounts data changes only while the goods slip is held at the intermediate store (status %)',
        v_gs_status using errcode = 'P0001';
    end if;
    if v_slip.round_no > 1
       and (v_gs_status is null or v_gs_status not in ('IN_PROCESS', 'COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION')) then
      raise exception 'G-22: Accounts data of a Pending re-action changes only while the goods slip is open (status %)',
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
    -- DEC-71: also unique against the per-GS entries of the store flow.
    select g.gs_no into v_other_gs
      from public.ac_gs_entries e
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
  select gs_id, status, round_no into v_slip from public.ac_action_slips where id = new.ac_action_slip_id;
  if not found or v_slip.gs_id <> new.gs_id or v_slip.status <> 'CURRENT' then
    raise exception 'G-22: Accounts completes the CURRENT A/c Actions slip of the same goods slip'
      using errcode = 'P0001';
  end if;

  -- DEC-71 (P11): store flow = one Challan / CN per goods slip (ac_gs_entries), at Accounts.
  if rms_private.gs_on_store_flow(new.gs_id) then
    if v_gs_status is distinct from 'ACCOUNTS_PENDING' then
      raise exception 'G-22: Accounts completes the Replacement Slip only while the goods slip is at Accounts (status %)',
        coalesce(v_gs_status, 'missing') using errcode = 'P0001';
    end if;
    if not exists (select 1 from public.ac_gs_entries e
                    where e.ac_action_slip_id = new.ac_action_slip_id
                      and rms_private.ac_gs_entry_complete(e)) then
      raise exception 'G-22: the goods slip still needs its Challan No. / Date or CN No. / Date / Value (DEC-71)'
        using errcode = 'P0001';
    end if;
    return new;
  end if;

  if v_slip.round_no = 1 and v_gs_status is distinct from 'HELD_AT_INTERMEDIATE_STORE' then
    raise exception 'G-22: Accounts completes only while the goods slip is held at the intermediate store (status %)',
      coalesce(v_gs_status, 'missing') using errcode = 'P0001';
  end if;
  if v_slip.round_no > 1
     and (v_gs_status is null or v_gs_status not in ('IN_PROCESS', 'COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION')) then
    raise exception 'G-22: Accounts completes a Pending re-action only while the goods slip is open (status %)',
      coalesce(v_gs_status, 'missing') using errcode = 'P0001';
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

create or replace function rms_private.dispatch_slip_lines_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_slip   record;
  v_entry  record;
  v_gs     record;
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
  -- DEC-71 (P11): on the store flow the challan is the goods slip's one Challan (ac_gs_entries).
  if rms_private.gs_on_store_flow(v_entry.gs_id) then
    select challan_no, challan_date into v_gs
      from public.ac_gs_entries where ac_action_slip_id = v_slip.ac_action_slip_id;
    if new.qty <> v_entry.qty or new.gs_item_id <> v_entry.gs_item_id
       or new.action_code <> v_entry.action_code
       or v_gs.challan_no is null
       or new.challan_no is distinct from v_gs.challan_no
       or new.challan_date is distinct from v_gs.challan_date then
      raise exception 'G-22: a Dispatch Slip line copies its action line (qty, item, action) and the goods slip''s Challan unchanged (DEC-71)'
        using errcode = 'P0001';
    end if;
    return new;
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


-- ---------------------------------------------------------------------------------------------
-- 7. G-03 status chain (full body: 20261123000300 body + DEC-71)
-- ---------------------------------------------------------------------------------------------
create or replace function rms_private.goods_slips_g03_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_decision text;
  v_problem  text;
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
  -- DEC-67 (P7, Q29): the first department routing of any store (a store routes after its own
  -- acknowledgement, the other stores may still be acknowledging).
  if new.status = 'STORE_PROCESSING' then
    if old.status not in ('TRANSFER_SLIP_GENERATED', 'STORE_ACKNOWLEDGED') then
      raise exception 'G-03: STORE_PROCESSING is reached from the transfer slips / store acknowledgement (from %)', old.status
        using errcode = '23514';
    end if;
    if rms_private.gs_transfer_slip_gaps(new.id) > 0 or not rms_private.gs_routing_started(new.id) then
      raise exception 'DEC-67: STORE_PROCESSING needs the goods slip fully on transfer slips and a department routing'
        using errcode = '23514';
    end if;
    return new;
  end if;
  if old.status = 'TRANSFER_SLIP_GENERATED' then
    if new.status = 'PENDING_TRANSFER_SLIP' then
      if rms_private.gs_transfer_slip_gaps(new.id) = 0 then
        raise exception 'DEC-65: the goods slip is still fully on live transfer slips' using errcode = '23514';
      end if;
      return new;
    end if;
    -- DEC-66 (P6): every live slip of the GS acknowledged by its Intermediate Store.
    if new.status = 'STORE_ACKNOWLEDGED' then
      if not rms_private.gs_slips_acknowledged(new.id) then
        raise exception 'DEC-66: every transfer slip of the goods slip must be acknowledged by its store first'
          using errcode = '23514';
      end if;
      return new;
    end if;
    raise exception 'G-03: a goods slip on transfer slips goes to STORE_ACKNOWLEDGED (DEC-66), STORE_PROCESSING (DEC-67) or back to PENDING_TRANSFER_SLIP (Q10), not %', new.status
      using errcode = '23514';
  end if;
  -- DEC-66: an acknowledged GS goes back only when a slip of it is voided (Q10).
  if old.status = 'STORE_ACKNOWLEDGED' then
    if new.status = 'PENDING_TRANSFER_SLIP' then
      if rms_private.gs_transfer_slip_gaps(new.id) = 0 then
        raise exception 'DEC-65: the goods slip is still fully on live transfer slips' using errcode = '23514';
      end if;
      return new;
    end if;
    raise exception 'G-03: % is not reachable from STORE_ACKNOWLEDGED (department routing goes to STORE_PROCESSING, DEC-67)', new.status
      using errcode = '23514';
  end if;
  -- DEC-69 (P9): every Intermediate Store with goods on the GS submitted its analysis.
  if new.status = 'ANALYSIS_COMPLETED' then
    -- DEC-71 (P11): Management reopens a goods slip at Accounts (entry not completed) or on hold
    -- to change it. A Replacement Slip at Accounts is withdrawn (superseded) first; a completed one
    -- can never be superseded (G-22), so a completed Accounts entry is never reopened.
    if old.status in ('ACCOUNTS_PENDING', 'NOT_ALLOWED_HOLD') then
      if exists (select 1 from public.ac_action_slips s
                  where s.gs_id = new.id and s.status = 'CURRENT') then
        raise exception 'DEC-71: the Replacement Slip at Accounts must be withdrawn before Management reopens the goods slip'
          using errcode = '23514';
      end if;
      return new;
    end if;
    if old.status is distinct from 'STORE_PROCESSING' then
      raise exception 'G-03: ANALYSIS_COMPLETED is reached from STORE_PROCESSING (from %)', old.status
        using errcode = '23514';
    end if;
    if not rms_private.gs_store_analysis_complete(new.id) then
      raise exception 'DEC-69: every Intermediate Store on the goods slip must submit its analysis first'
        using errcode = '23514';
    end if;
    return new;
  end if;
  -- DEC-67 / DEC-69: Management approval and Accounts (P10–P11) add the other exits.
  if old.status = 'STORE_PROCESSING' then
    raise exception 'G-03: % is not reachable from STORE_PROCESSING (analysis goes to ANALYSIS_COMPLETED, DEC-69)', new.status
      using errcode = '23514';
  end if;
  if old.status = 'ANALYSIS_COMPLETED' then
    -- DEC-70 / Q18: no open Management approval request, Issue CN only with a valid approval,
    -- no Management change without a valid approval.
    v_problem := rms_private.gs_management_gate_problem(new.id);
    if v_problem is not null then
      raise exception '%', v_problem using errcode = '23514';
    end if;
    -- DEC-71 (P11): the Accounts gate. Every store with goods on the GS submitted its analysis.
    if not rms_private.gs_store_analysis_complete(new.id) then
      raise exception 'DEC-71: every Intermediate Store on the goods slip must submit its analysis before Accounts'
        using errcode = '23514';
    end if;
    if new.status = 'ACCOUNTS_PENDING' then
      if not rms_private.gs_needs_accounts(new.id) then
        raise exception 'DEC-71 (Q21): no decision of the goods slip needs a Challan or a Credit Note; it stays on hold (NOT_ALLOWED_HOLD)'
          using errcode = '23514';
      end if;
      return new;
    end if;
    if new.status = 'NOT_ALLOWED_HOLD' then
      if rms_private.gs_needs_accounts(new.id) then
        raise exception 'DEC-71 (Q21): a decision of the goods slip needs a Challan or a Credit Note; it goes to Accounts'
          using errcode = '23514';
      end if;
      return new;
    end if;
    raise exception 'G-03: ANALYSIS_COMPLETED goes to Accounts (ACCOUNTS_PENDING) or on hold (NOT_ALLOWED_HOLD), not % (DEC-71)', new.status
      using errcode = '23514';
  end if;
  -- DEC-71 (Q21): on hold until Management changes the decisions (back to ANALYSIS_COMPLETED).
  if old.status = 'NOT_ALLOWED_HOLD' then
    raise exception 'G-03: a goods slip on hold (every decision Not Allowed) only returns to ANALYSIS_COMPLETED through a Management change, not % (DEC-71, Q21)', new.status
      using errcode = '23514';
  end if;
  -- DEC-71: Accounts completed the CURRENT Replacement Slip: goods to ship → Dispatch Slip
  -- (DISPATCH_PENDING); nothing to ship → the closure engine (IN_PROCESS).
  if old.status = 'ACCOUNTS_PENDING' then
    if new.status in ('DISPATCH_PENDING', 'IN_PROCESS') then
      if not exists (select 1 from public.ac_action_slips s
                       join public.ac_entry_completions c on c.ac_action_slip_id = s.id
                      where s.gs_id = new.id and s.status = 'CURRENT') then
        raise exception 'DEC-71: Accounts must complete the Replacement Slip before the goods slip leaves Accounts'
          using errcode = '23514';
      end if;
      if new.status = 'DISPATCH_PENDING'
         and not exists (select 1 from public.dispatch_slips d
                           join public.ac_action_slips s on s.id = d.ac_action_slip_id
                          where d.gs_id = new.id and s.status = 'CURRENT' and d.status = 'READY') then
        raise exception 'DEC-71: DISPATCH_PENDING needs the Dispatch Slip of the Replacement Slip'
          using errcode = '23514';
      end if;
      if new.status = 'IN_PROCESS'
         and exists (select 1 from public.ac_entry_lines e
                       join public.ac_action_slips s on s.id = e.ac_action_slip_id
                      where s.gs_id = new.id and s.status = 'CURRENT' and e.requires_challan) then
        raise exception 'DEC-71: the goods slip ships goods; it goes to Dispatch (DISPATCH_PENDING) first'
          using errcode = '23514';
      end if;
      return new;
    end if;
    raise exception 'G-03: % is not reachable from ACCOUNTS_PENDING (Dispatch or closure after Accounts, or Management reopening, DEC-71)', new.status
      using errcode = '23514';
  end if;
  if old.status = 'DISPATCH_PENDING' then
    if new.status = 'IN_PROCESS' then
      if exists (select 1 from public.dispatch_slips d where d.gs_id = new.id and d.status = 'READY') then
        raise exception 'DEC-71: the Dispatch Slip of the goods slip is not dispatched yet'
          using errcode = '23514';
      end if;
      return new;
    end if;
    raise exception 'G-03: % is not reachable from DISPATCH_PENDING (dispatch moves it to IN_PROCESS, DEC-71)', new.status
      using errcode = '23514';
  end if;
  if new.status in ('ACCOUNTS_PENDING', 'NOT_ALLOWED_HOLD', 'DISPATCH_PENDING') then
    raise exception 'G-03: % is reached only from the analysis / Accounts steps (from %, DEC-71)', new.status, old.status
      using errcode = '23514';
  end if;
  if new.status in ('PENDING_TRANSFER_SLIP', 'SALES_RETURN_HOLD', 'TRANSFER_SLIP_GENERATED',
                    'STORE_ACKNOWLEDGED') then
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
-- 8. Closure checklist (G-15; full body: 20261118000300 body + the per-GS CN of DEC-71)
-- ---------------------------------------------------------------------------------------------
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
  v_open_rounds   jsonb;
  v_open_count    integer;
  v_last_round    integer;
  v_pending       integer;
  v_dslips        jsonb;
  v_ready         integer;
  v_cn_lines      integer;
  v_notified      boolean;
begin
  select g.id, g.gs_no, g.status, g.category_code, g.has_discrepancy
    into v_gs from public.goods_slips g where g.id = p_gs_id;
  if not found then
    raise exception 'Goods slip % not found', p_gs_id using errcode = 'P0002';
  end if;
  v_csr := coalesce(v_gs.category_code = 'CSR', false);
  v_ac_flow := exists (select 1 from public.ac_action_slips s where s.gs_id = p_gs_id);

  -- 1. Status (§6.5).
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

  -- 3. Every remaining piece is in a terminal or accounted location (G-15, BR-30). DEC-57 (Q11):
  --    pieces the A/c Actions flow moved to the Rejected Hold (Not Allowed) are accounted.
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
       or (loc.location_class = 'REJECTED_HOLD'
           and exists (select 1 from public.stock_movements m
                        where m.lot_id = l.id and m.to_location_id = loc.id
                          and m.reference_type in ('ac_action_slips', 'dispatch_slips')))
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

  -- 5. No open discrepancy.
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

  -- 6. RM Step-7 CN decision (BR-32), not on the A/c Actions flow.
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

  -- 6b. AMD-18 + DEC-57: every final-action round has a CURRENT A/c Actions slip that Accounts
  --     completed.
  with rounds as (
    select distinct act.round_no
      from public.rm_item_actions act
      join public.gs_items gi on gi.id = act.gs_item_id
     where gi.gs_id = p_gs_id and act.is_current
  ),
  st as (
    select r.round_no, s.id as slip_id, s.slip_no, s.version_no,
           exists (select 1 from public.ac_entry_completions c where c.ac_action_slip_id = s.id) as completed
      from rounds r
      left join public.ac_action_slips s
             on s.gs_id = p_gs_id and s.round_no = r.round_no and s.status = 'CURRENT'
  )
  select coalesce(jsonb_agg(jsonb_build_object(
           'round_no', st.round_no, 'ac_action_slip_id', st.slip_id, 'slip_no', st.slip_no,
           'version_no', st.version_no, 'completed', st.completed) order by st.round_no)
           filter (where st.slip_id is null or not st.completed), '[]'::jsonb),
         count(*) filter (where st.slip_id is null or not st.completed)
    into v_open_rounds, v_open_count
    from st;
  return query select 65, 'AC_ENTRY_COMPLETE', 'AMD-18', v_ac_flow, (not v_ac_flow) or v_open_count = 0,
    case when not v_ac_flow then 'Not on the A/c Actions flow'
         when v_open_count = 0 then 'Accounts completed the CN / Challan entry of every A/c Actions slip'
         else v_open_count || ' final-action round(s) without a finalised A/c Actions slip completed by Accounts' end,
    jsonb_build_object('open_rounds', v_open_rounds);

  -- 6c. DEC-57 (Q10): the goods slip stays open until every Pending piece got a final action.
  select coalesce(max(act.round_no), 0) into v_last_round
    from public.rm_item_actions act
    join public.gs_items gi on gi.id = act.gs_item_id
   where gi.gs_id = p_gs_id and act.is_current;
  v_pending := case when v_last_round > 0
                    then rms_private.final_action_pending_qty(p_gs_id, v_last_round) else 0 end;
  return query select 66, 'NO_PENDING_REACTION', 'DEC-57', v_ac_flow, (not v_ac_flow) or v_pending = 0,
    case when not v_ac_flow then 'Not on the A/c Actions flow'
         when v_pending = 0 then 'No piece is waiting in Pending for a final action'
         else v_pending || ' pc(s) are Pending; the Replacement Manager must re-action them' end,
    jsonb_build_object('round_no', v_last_round, 'pending_qty', v_pending);

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

  -- 8b. AMD-19 + DEC-57: every Dispatch Slip of the goods slip (one per round) is dispatched.
  select coalesce(jsonb_agg(jsonb_build_object(
           'dispatch_slip_id', d.id, 'slip_no', d.slip_no, 'status', d.status)
           order by d.generated_at), '[]'::jsonb),
         count(*) filter (where d.status = 'READY')
    into v_dslips, v_ready
    from public.dispatch_slips d where d.gs_id = p_gs_id;
  return query select 85, 'DISPATCH_SLIP_DISPATCHED', 'AMD-19', jsonb_array_length(v_dslips) > 0,
    v_ready = 0,
    case when jsonb_array_length(v_dslips) = 0 then 'No Dispatch Slip (no action line ships goods, or Accounts not complete yet)'
         when v_ready = 0 then 'Every Dispatch Slip is dispatched'
         else v_ready || ' Dispatch Slip(s) not dispatched yet' end,
    jsonb_build_object('dispatch_slips', v_dslips);

  -- 9. Every issued CN / JV has a PRIOR_INFO_SENT notification (BR-38). On the A/c Actions flow a
  --    CN entered by Accounts on any CURRENT slip (every round) needs a PRIOR_INFO_SENT record.
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
    join public.ac_action_slips s on s.id = e.ac_action_slip_id
   where s.gs_id = p_gs_id and s.status = 'CURRENT' and e.cn_no is not null;
  -- DEC-71 (P11): the store flow records one CN per goods slip (ac_gs_entries).
  v_cn_lines := v_cn_lines + (
    select count(*)::integer
      from public.ac_gs_entries e
      join public.ac_action_slips s on s.id = e.ac_action_slip_id
     where s.gs_id = p_gs_id and s.status = 'CURRENT' and e.cn_no is not null);
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

-- ---------------------------------------------------------------------------------------------
-- 9. Notification event type (rules: seed.sql + snippet; email deferred, Q22)
-- ---------------------------------------------------------------------------------------------
insert into public.notification_event_types
  (code, label, description, category, default_priority, is_mandatory, source_ref, sort_order)
values
  ('GS_NOT_ALLOWED_HOLD', 'Goods slip on hold (all Not Allowed)',
   'DEC-71 (Q21): every decision of a goods slip is Not Allowed (no Challan, no Credit Note); it stays open on hold, without an Accounts entry.',
   'WORKFLOW', 'NORMAL', false, 'DEC-71', 587)
on conflict (code) do update
  set label = excluded.label, description = excluded.description,
      default_priority = excluded.default_priority, source_ref = excluded.source_ref;

-- Default email template (every event type has one; email itself is deferred, Q22).
insert into public.notification_templates (event_type, channel, version_no, subject, body, change_reason)
select 'GS_NOT_ALLOWED_HOLD', 'EMAIL', 1,
       '[{app_name}] {title}',
       E'Hello {recipient_name},

{title}

{body}

Event: {event_label}
Priority: {priority}
Open in RMS: {link}

— {app_name} (automated message; manage email preferences in RMS)',
       'P11 default'
 where not exists (select 1 from public.notification_templates t
                    where t.event_type = 'GS_NOT_ALLOWED_HOLD' and t.channel = 'EMAIL');
