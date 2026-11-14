-- P3-01 · Custody transfer engine & Step-4 handover Aman → Sahil
-- (master plan §2.2 Stage-2, §8.5, DD r44–r46, BR-20..BR-22, G-08, G-09, DEC-12, DEC-14, DEC-27).
--
-- Extends the P2-01 custody tables and the P2-04 CSR proposal (stock_moved = false) into a
-- two-phase engine: initiate (source → TRANSIT) → accept (TRANSIT → destination) | discrepancy
-- (frozen in TRANSIT) → reconcile (two signatures or RM override) | cancel (→ source).
--
-- 1. custody_transfers: form version pins + label snapshot (G-18), receiver task, cancel / resend /
--    resolution columns, acceptance code CHECK (DD r45–r46).
-- 2. custody_transfer_lines: one line per lot; qty_returned / qty_adjusted bookkeeping.
-- 3. custody_reconciliations: discrepancy resolutions with initiator + receiver signatures, RM
--    override and RM approval of stock adjustments (BR-21).
-- 4. G-09 (database half): transfer state machine; ACCEPTED only with every count = qty sent;
--    lines frozen once stock moved; every stock movement into or out of a TRANSIT location must
--    belong to a transfer in the matching state and never exceed the quantity sent.
-- 5. Settings: transfer_blind_count ([IMP], off), custody_override_roles (RM).

-- ===========================================================================
-- 1. custody_transfers
-- ===========================================================================
alter table public.custody_transfers
  add column supersedes_transfer_id   uuid references public.custody_transfers (id) on delete restrict,
  add column initiate_form_version_id uuid references public.form_versions (id) on delete restrict,
  add column accept_form_version_id   uuid references public.form_versions (id) on delete restrict,
  add column labels_snapshot          jsonb not null default '{}'::jsonb,
  add column stock_moved_at           timestamptz,
  add column receiver_task_id         uuid references public.workflow_tasks (id) on delete set null,
  add column cancelled_by             uuid references public.profiles (id) on delete set null,
  add column cancelled_at             timestamptz,
  add column cancel_reason            text,
  add column resolution_code          text check (resolution_code is null or resolution_code in (
                                        'RESEND_CORRECTED','ACCEPT_COUNTED_WITH_ADJUSTMENT','CANCEL_RETURN')),
  add column reconciled_at            timestamptz,
  -- DD r45–r46: the acceptance status codes the engine keys off (labels live in TRANSFER_ACCEPTANCE).
  add constraint custody_transfers_acceptance_code_check
    check (acceptance_code is null or acceptance_code in ('ACCEPTED_VERIFIED','DISCREPANCY')),
  add constraint custody_transfers_not_to_self check (from_location_id <> to_location_id);

create index custody_transfers_supersedes_idx on public.custody_transfers (supersedes_transfer_id);
create index custody_transfers_receiver_task_idx on public.custody_transfers (receiver_task_id);
create index custody_transfers_cancelled_by_idx on public.custody_transfers (cancelled_by);
create index custody_transfers_initiate_form_idx on public.custody_transfers (initiate_form_version_id);
create index custody_transfers_accept_form_idx on public.custody_transfers (accept_form_version_id);

-- ===========================================================================
-- 2. custody_transfer_lines
-- ===========================================================================
alter table public.custody_transfer_lines
  -- Pieces sent back to the source (cancel / CANCEL_RETURN / RESEND_CORRECTED / difference return).
  add column qty_returned integer not null default 0 check (qty_returned >= 0),
  -- RM-approved stock adjustment on reconciliation: < 0 loss written off, > 0 excess counted.
  add column qty_adjusted integer not null default 0,
  add constraint custody_transfer_lines_one_per_lot unique (transfer_id, lot_id);

-- ===========================================================================
-- 3. custody_reconciliations (BR-21 "reconcile with Aman": two signatures or RM override)
-- ===========================================================================
create table public.custody_reconciliations (
  id                     uuid primary key default gen_random_uuid(),
  transfer_id            uuid not null references public.custody_transfers (id) on delete cascade,
  resolution_code        text not null check (resolution_code in (
                           'RESEND_CORRECTED','ACCEPT_COUNTED_WITH_ADJUSTMENT','CANCEL_RETURN')),
  -- ACCEPT_COUNTED_WITH_ADJUSTMENT only: what happens to pieces sent but not counted.
  difference_disposition text check (difference_disposition is null
                           or difference_disposition in ('RETURN_TO_SOURCE','WRITE_OFF_LOSS')),
  -- RESEND_CORRECTED only: [{lot_id, qty}] of the corrected transfer.
  resend_lines           jsonb not null default '[]'::jsonb check (jsonb_typeof(resend_lines) = 'array'),
  notes                  text not null check (btrim(notes) <> ''),
  status                 text not null default 'PROPOSED' check (status in (
                           'PROPOSED','AWAITING_RM_APPROVAL','APPLIED','SUPERSEDED')),
  -- An ADJUST movement (loss / excess) needs the RM's approval with a reason.
  requires_rm_approval   boolean not null default false,
  proposed_by            uuid not null default rms_private.current_actor()
                           references public.profiles (id) on delete restrict,
  proposed_at            timestamptz not null default clock_timestamp(),  -- ordered within one txn
  initiator_signed_by    uuid references public.profiles (id) on delete restrict,
  initiator_signed_at    timestamptz,
  receiver_signed_by     uuid references public.profiles (id) on delete restrict,
  receiver_signed_at     timestamptz,
  is_rm_override         boolean not null default false,
  rm_approved_by         uuid references public.profiles (id) on delete restrict,
  rm_approved_at         timestamptz,
  rm_reason              text,
  applied_at             timestamptz,
  resend_transfer_id     uuid references public.custody_transfers (id) on delete restrict,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now(),
  check ((resolution_code = 'ACCEPT_COUNTED_WITH_ADJUSTMENT') = (difference_disposition is not null)),
  check (initiator_signed_by is null or receiver_signed_by is null
         or initiator_signed_by <> receiver_signed_by),
  check (not is_rm_override or (rm_approved_by is not null and btrim(coalesce(rm_reason, '')) <> '')),
  check (rm_approved_by is null or btrim(coalesce(rm_reason, '')) <> ''),
  check (status <> 'APPLIED' or (
           applied_at is not null
           and (is_rm_override or (initiator_signed_by is not null and receiver_signed_by is not null))
           and (not requires_rm_approval or rm_approved_by is not null)))
);

create index custody_reconciliations_transfer_idx on public.custody_reconciliations (transfer_id);
create index custody_reconciliations_proposed_by_idx on public.custody_reconciliations (proposed_by);
create index custody_reconciliations_initiator_idx on public.custody_reconciliations (initiator_signed_by);
create index custody_reconciliations_receiver_idx on public.custody_reconciliations (receiver_signed_by);
create index custody_reconciliations_rm_idx on public.custody_reconciliations (rm_approved_by);
create index custody_reconciliations_resend_idx on public.custody_reconciliations (resend_transfer_id);
-- One open resolution per transfer (a counter-proposal supersedes the previous one).
create unique index custody_reconciliations_one_open on public.custody_reconciliations (transfer_id)
  where status in ('PROPOSED','AWAITING_RM_APPROVAL');

create or replace function rms_private.custody_reconciliations_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'Custody reconciliations are never deleted' using errcode = '23514';
  end if;
  if tg_op = 'INSERT' then
    if not exists (select 1 from public.custody_transfers t
                    where t.id = new.transfer_id and t.status = 'DISCREPANCY') then
      raise exception 'G-09: only a transfer in DISCREPANCY can be reconciled' using errcode = '23514';
    end if;
    return new;
  end if;
  if old.status in ('APPLIED','SUPERSEDED') then
    -- RESEND_CORRECTED: the corrected transfer is created after the return movements, so its id
    -- is recorded once, right after APPLIED. Nothing else ever changes.
    if old.status = 'APPLIED' and old.resend_transfer_id is null and new.resend_transfer_id is not null
       and (to_jsonb(new) - 'resend_transfer_id' - 'updated_at')
           = (to_jsonb(old) - 'resend_transfer_id' - 'updated_at') then
      return new;
    end if;
    raise exception 'G-09: an applied or superseded reconciliation is immutable' using errcode = '23514';
  end if;
  if new.resolution_code is distinct from old.resolution_code
     or new.difference_disposition is distinct from old.difference_disposition
     or new.resend_lines is distinct from old.resend_lines
     or new.transfer_id is distinct from old.transfer_id then
    raise exception 'A reconciliation proposal cannot be changed; propose a new one' using errcode = '23514';
  end if;
  return new;
end
$$;
revoke all on function rms_private.custody_reconciliations_guard() from public, anon, authenticated;

create trigger custody_reconciliations_guard
  before insert or update or delete on public.custody_reconciliations
  for each row execute function rms_private.custody_reconciliations_guard();

alter table public.custody_reconciliations enable row level security;
select rms_private.attach_standard_triggers('public.custody_reconciliations');
grant select, insert, update on public.custody_reconciliations to rms_api;

-- ===========================================================================
-- 4a. G-09: custody transfer state machine
-- ===========================================================================
create or replace function rms_private.custody_transfers_g09_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_sod boolean;
begin
  if tg_op = 'INSERT' then
    if new.status <> 'INITIATED' then
      raise exception 'G-09: a custody transfer starts INITIATED' using errcode = '23514';
    end if;
    return new;
  end if;

  if old.stock_moved and not new.stock_moved then
    raise exception 'G-09: stock of transfer % has moved; stock_moved cannot be reset', old.transfer_no
      using errcode = '23514';
  end if;
  if new.stock_moved and not old.stock_moved and old.status <> 'INITIATED' then
    raise exception 'G-09: only an INITIATED transfer can move its stock to TRANSIT' using errcode = '23514';
  end if;
  if new.status is not distinct from old.status then
    return new;
  end if;

  if not ((old.status = 'INITIATED' and new.status in ('ACCEPTED','DISCREPANCY','CANCELLED'))
          or (old.status = 'DISCREPANCY' and new.status = 'RECONCILED')) then
    raise exception 'G-09: custody transfer % cannot go from % to %', old.transfer_no, old.status, new.status
      using errcode = '23514';
  end if;

  if new.status in ('ACCEPTED','DISCREPANCY') then
    if not new.stock_moved then
      raise exception 'G-09: transfer % has not been dispatched to TRANSIT yet', new.transfer_no
        using errcode = '23514';
    end if;
    if new.accepted_by is null or new.accepted_at is null then
      raise exception 'G-09: the receiver and the count time are required' using errcode = '23514';
    end if;
    -- §9.3 segregation of duties (setting; checked by the service too).
    select coalesce((s.value #>> '{}')::boolean, true) into v_sod
      from public.system_settings s where s.key = 'segregation_of_duties_transfer';
    if coalesce(v_sod, true) and new.accepted_by = new.initiated_by then
      raise exception 'SEGREGATION_OF_DUTIES: the initiator of transfer % cannot accept it', new.transfer_no
        using errcode = '42501';
    end if;
  end if;

  if new.status = 'ACCEPTED' then
    if new.acceptance_code is distinct from 'ACCEPTED_VERIFIED' then
      raise exception 'G-09: an accepted transfer needs acceptance code ACCEPTED_VERIFIED' using errcode = '23514';
    end if;
    -- DD r45: counts match → accepted. Any mismatch is a discrepancy (DD r46).
    if exists (select 1 from public.custody_transfer_lines l
                where l.transfer_id = new.id and l.qty_counted <> l.qty_sent) then
      raise exception 'G-09: transfer % has a count that differs from the quantity sent', new.transfer_no
        using errcode = '23514';
    end if;
  elsif new.status = 'DISCREPANCY' then
    if new.acceptance_code is distinct from 'DISCREPANCY' then
      raise exception 'G-09: a discrepancy needs acceptance code DISCREPANCY' using errcode = '23514';
    end if;
  elsif new.status = 'RECONCILED' then
    if not exists (select 1 from public.custody_reconciliations r
                    where r.transfer_id = new.id and r.status = 'APPLIED') then
      raise exception 'G-09: transfer % has no applied reconciliation', new.transfer_no
        using errcode = '23514';
    end if;
  end if;
  return new;
end
$$;
revoke all on function rms_private.custody_transfers_g09_guard() from public, anon, authenticated;

create trigger custody_transfers_g09_guard
  before insert or update on public.custody_transfers
  for each row execute function rms_private.custody_transfers_g09_guard();

-- Lines: added only while the transfer is a proposal; lot / qty_sent frozen once the stock moved.
create or replace function rms_private.custody_transfer_lines_g09_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_t record;
begin
  select t.status, t.stock_moved, t.transfer_no into v_t
    from public.custody_transfers t
   where t.id = coalesce(new.transfer_id, old.transfer_id);
  if tg_op in ('INSERT','DELETE') then
    if v_t.status <> 'INITIATED' or v_t.stock_moved then
      raise exception 'G-09: lines of transfer % are frozen once its stock has moved', v_t.transfer_no
        using errcode = '23514';
    end if;
    return coalesce(new, old);
  end if;
  if new.lot_id is distinct from old.lot_id or new.transfer_id is distinct from old.transfer_id
     or (v_t.stock_moved and new.qty_sent is distinct from old.qty_sent) then
    raise exception 'G-09: lines of transfer % are frozen once its stock has moved', v_t.transfer_no
      using errcode = '23514';
  end if;
  if new.qty_counted is distinct from old.qty_counted and v_t.status <> 'INITIATED' then
    raise exception 'G-09: the count of transfer % is already recorded', v_t.transfer_no
      using errcode = '23514';
  end if;
  return new;
end
$$;
revoke all on function rms_private.custody_transfer_lines_g09_guard() from public, anon, authenticated;

create trigger custody_transfer_lines_g09_guard
  before insert or update or delete on public.custody_transfer_lines
  for each row execute function rms_private.custody_transfer_lines_g09_guard();

-- ===========================================================================
-- 4b. G-09: stock in TRANSIT belongs to exactly one transfer and leaves it only as the state allows
-- ===========================================================================
create or replace function rms_private.stock_movements_g09_transit_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_from_class text;
  v_to_class   text;
  v_t          record;
  v_sent       integer;
  v_in         integer;
  v_out        integer;
begin
  select l.location_class into v_from_class from public.inventory_locations l where l.id = new.from_location_id;
  select l.location_class into v_to_class from public.inventory_locations l where l.id = new.to_location_id;
  if v_from_class is distinct from 'TRANSIT' and v_to_class is distinct from 'TRANSIT' then
    return new;
  end if;

  if new.reference_type is distinct from 'custody_transfer' or new.reference_id is null then
    raise exception 'G-09: stock enters or leaves TRANSIT only through a custody transfer'
      using errcode = '23514';
  end if;
  select t.id, t.transfer_no, t.status, t.from_location_id, t.to_location_id, t.transit_location_id
    into v_t from public.custody_transfers t where t.id = new.reference_id;
  if not found then
    raise exception 'G-09: custody transfer % not found', new.reference_id using errcode = '23514';
  end if;
  select l.qty_sent into v_sent from public.custody_transfer_lines l
   where l.transfer_id = v_t.id and l.lot_id = new.lot_id;
  if not found then
    raise exception 'G-09: lot % is not on transfer %', new.lot_id, v_t.transfer_no using errcode = '23514';
  end if;

  select coalesce(sum(m.qty) filter (where tl.location_class = 'TRANSIT'), 0),
         coalesce(sum(m.qty) filter (where fl.location_class = 'TRANSIT'), 0)
    into v_in, v_out
    from public.stock_movements m
    left join public.inventory_locations fl on fl.id = m.from_location_id
    left join public.inventory_locations tl on tl.id = m.to_location_id
   where m.reference_type = 'custody_transfer' and m.reference_id = v_t.id and m.lot_id = new.lot_id;

  if v_to_class = 'TRANSIT' then
    if v_t.status <> 'INITIATED' or new.from_location_id is distinct from v_t.from_location_id
       or new.to_location_id is distinct from v_t.transit_location_id then
      raise exception 'G-09: only an INITIATED transfer moves stock from its source into TRANSIT (%)', v_t.transfer_no
        using errcode = '23514';
    end if;
    if v_in + new.qty > v_sent then
      raise exception 'G-09: transfer % would dispatch more than the quantity sent', v_t.transfer_no
        using errcode = '23514';
    end if;
  else
    -- Leaving TRANSIT: credited to the receiver only once accepted / reconciled (G-09);
    -- back to the source on cancel / reconcile; written off (ADJUST, no target) only when reconciled.
    if new.from_location_id is distinct from v_t.transit_location_id then
      raise exception 'G-09: stock of transfer % is not in its TRANSIT location', v_t.transfer_no
        using errcode = '23514';
    end if;
    if not (
         (new.to_location_id = v_t.to_location_id and v_t.status in ('ACCEPTED','RECONCILED'))
      or (new.to_location_id = v_t.from_location_id and v_t.status in ('CANCELLED','RECONCILED'))
      or (new.to_location_id is null and new.movement_type = 'ADJUST' and v_t.status = 'RECONCILED')) then
      raise exception 'G-09: transfer % is % — its stock cannot leave TRANSIT this way', v_t.transfer_no, v_t.status
        using errcode = '23514';
    end if;
    if v_out + new.qty > v_in then
      raise exception 'G-09: transfer % would release more than it holds in TRANSIT', v_t.transfer_no
        using errcode = '23514';
    end if;
  end if;
  return new;
end
$$;
revoke all on function rms_private.stock_movements_g09_transit_guard() from public, anon, authenticated;

create trigger stock_movements_g09_transit_guard
  before insert on public.stock_movements
  for each row execute function rms_private.stock_movements_g09_transit_guard();

-- ===========================================================================
-- 5. Settings
-- ===========================================================================
insert into public.system_settings (key, value, category, description, source_ref) values
  ('transfer_blind_count', 'false', 'workflow',
   '[IMP] Blind count: the receiver does not see the quantities sent until the count is submitted.',
   'P3-01'),
  ('custody_override_roles', '["REPLACEMENT_MANAGER"]'::jsonb, 'workflow',
   'Roles that may override a custody discrepancy reconciliation (audited) and approve its stock adjustments.',
   'BR-21')
on conflict (key) do nothing;
