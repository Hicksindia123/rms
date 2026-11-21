-- =============================================================================================
-- Phase P6 (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-66 (Q12 user; Q13 PROVISIONAL).
-- Store acknowledgement per transfer slip: a user of the Intermediate Store the slip is addressed
-- to (OP / DT / RI …, NOT the Main Store) acknowledges the physical receipt of the whole slip.
--
-- 1. Status STORE_ACKNOWLEDGED ("Acknowledged by Store"): every live transfer slip of the GS is
--    acknowledged (rms_private.gs_slips_acknowledged). A GS on several slips stays
--    TRANSFER_SLIP_GENERATED until its last slip is acknowledged. A void (Q10) brings it back to
--    PENDING_TRANSFER_SLIP. Department routing (P7) adds the exit.
-- 2. rms_private.user_acts_for_store(user, store): Super Admin or a holder of the store's role.
--    MANAGEMENT sees every store (user_store_ids) but does not acknowledge (DEC-66).
-- 3. transfer_slips guard (full body replaced):
--    GENERATED → ACKNOWLEDGED: transfer_slips.approve + a user of the slip's store; the backing
--    custody transfer is still INITIATED in TRANSIT (the service accepts it in full in the same
--    transaction). Full acknowledgement only (Q13).
--    ACKNOWLEDGED → VOIDED (Q10, P5 left a 409): the stock goes back from the store's location to
--    Inward Staging through a return custody transfer (purpose TRANSFER_SLIP_VOID, accepted),
--    recorded in transfer_slips.void_return_transfer_id.
-- 4. transfer_slip_discrepancies: "Report discrepancy" (remark only, append-only history). The
--    slip stays GENERATED; RM + MANAGEMENT are alerted (notification rule).
-- 5. Custody G-09 guard (full body replaced: 20261105000100 body + the slip rules):
--    the custody transfer behind a slip is ACCEPTED only together with the slip acknowledgement,
--    CANCELLED only together with the slip void, and never goes to DISCREPANCY (Q13: full
--    acknowledgement; the discrepancy is reported on the slip). The generic custody accept /
--    cancel / count endpoints therefore cannot desynchronise a slip. The void-return transfer
--    (TRANSFER_SLIP_VOID) is accepted by the voiding Super Admin / Management on behalf of
--    Inward Staging (same pattern as DEC-21 / DEC-34): only from an Intermediate Store location
--    to Inward Staging, only by a holder of itemization.configure.
-- 6. G-03 status chain: TRANSFER_SLIP_GENERATED → STORE_ACKNOWLEDGED, STORE_ACKNOWLEDGED →
--    PENDING_TRANSFER_SLIP (void).
-- 7. Permission transfer_slips.approve (= acknowledge / report a discrepancy), journey catalogue
--    entry ACK_TRANSFER_SLIPS (queue STORE_ACK), notification event types
--    TRANSFER_SLIP_GENERATED (the slip's store users) and TRANSFER_SLIP_DISCREPANCY.
--    Grants, menus, rules, labels and the retired STORE_ACCEPT menu: seed.sql + the release
--    snippet (roles are seed data).
-- Legacy: custody transfers that are not slip-backed (goods_slips.transfer_slip_id, DEC-54) keep
-- their accept / discrepancy / reconcile path unchanged.
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- 1. Status
-- ---------------------------------------------------------------------------------------------
alter table public.goods_slips drop constraint goods_slips_status_check;
alter table public.goods_slips
  add constraint goods_slips_status_check check (status in (
    'GATE_CREATED', 'UNBOXING', 'ITEMIZATION', 'CATEGORISATION', 'CSR_APPROVAL_PENDING',
    'INSPECTION', 'RM_REVIEW', 'PENDING_TRANSFER_SLIP', 'TRANSFER_SLIP_GENERATED',
    'STORE_ACKNOWLEDGED', 'SALES_RETURN_HOLD', 'HELD_AT_INTERMEDIATE_STORE', 'IN_PROCESS',
    'COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION', 'CLOSED', 'CANCELLED'));

-- ---------------------------------------------------------------------------------------------
-- 2. Helpers
-- ---------------------------------------------------------------------------------------------
-- DEC-66: who acts for a store = Super Admin or a holder of the store's own role. Unlike
-- user_store_ids, MANAGEMENT is not a store user.
create or replace function rms_private.user_acts_for_store(p_user_id uuid, p_store_id uuid)
returns boolean
language sql
stable
set search_path = ''
as $$
  select exists (
    select 1
      from public.profiles pr
      join public.intermediate_stores s on s.id = p_store_id
     where pr.id = p_user_id and pr.is_active
       and (pr.is_super_admin
            or exists (select 1 from public.user_roles ur
                        where ur.user_id = pr.id and ur.role_id = s.role_id)))
$$;
revoke all on function rms_private.user_acts_for_store(uuid, uuid) from public, anon, authenticated;
grant execute on function rms_private.user_acts_for_store(uuid, uuid) to rms_api;
comment on function rms_private.user_acts_for_store(uuid, uuid) is
  'DEC-66: Super Admin or a holder of the Intermediate Store''s role (the users who acknowledge its transfer slips).';

-- DEC-66: the GS is fully on live slips and none of them waits for its store.
create or replace function rms_private.gs_slips_acknowledged(p_gs_id uuid)
returns boolean
language sql
stable
set search_path = ''
as $$
  select rms_private.gs_transfer_slip_gaps(p_gs_id) = 0
     and exists (select 1 from public.transfer_slip_gs g
                   join public.transfer_slips s on s.id = g.slip_id
                  where g.gs_id = p_gs_id and s.status = 'ACKNOWLEDGED')
     and not exists (select 1 from public.transfer_slip_gs g
                       join public.transfer_slips s on s.id = g.slip_id
                      where g.gs_id = p_gs_id and s.status = 'GENERATED')
$$;
revoke all on function rms_private.gs_slips_acknowledged(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_slips_acknowledged(uuid) to rms_api;

-- ---------------------------------------------------------------------------------------------
-- 3. transfer_slips: the void-return transfer + guard
-- ---------------------------------------------------------------------------------------------
alter table public.transfer_slips
  add column void_return_transfer_id uuid unique
    references public.custody_transfers (id) on delete restrict;
create index transfer_slips_void_return_idx on public.transfer_slips (void_return_transfer_id)
  where void_return_transfer_id is not null;
comment on column public.transfer_slips.void_return_transfer_id is
  'DEC-66 / Q10: when an ACKNOWLEDGED slip is voided, the custody transfer that brought its stock back from the store''s location to Inward Staging.';
comment on column public.transfer_slips.acknowledge_remarks is
  'DEC-66: optional remark of the store user who acknowledged the slip (full acknowledgement only, Q13).';

create or replace function rms_private.transfer_slips_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_store    public.intermediate_stores%rowtype;
  v_transfer record;
  v_return   record;
  v_staging  uuid;
  v_store_loc uuid;
  v_actor    uuid := rms_private.current_actor();
begin
  if tg_op = 'DELETE' then
    raise exception 'DEC-65: transfer slips are never deleted (void them instead)' using errcode = '42501';
  end if;
  select id into v_staging from public.inventory_locations where code = 'INWARD_STAGING';

  if tg_op = 'INSERT' then
    if not rms_private.user_holds_permission(v_actor, 'transfer_slips', 'create') then
      raise exception 'DEC-65: only the Replacement Manager generates transfer slips' using errcode = '42501';
    end if;
    if new.status <> 'GENERATED' then
      raise exception 'DEC-65: a transfer slip starts GENERATED' using errcode = '23514';
    end if;
    if new.acknowledged_by is not null or new.voided_by is not null or new.void_return_transfer_id is not null then
      raise exception 'DEC-65: a new transfer slip carries no acknowledgement or void' using errcode = '23514';
    end if;
    select * into v_store from public.intermediate_stores where id = new.store_id;
    if not v_store.is_active then
      raise exception 'DEC-65: Intermediate Store % is inactive', v_store.code using errcode = '23514';
    end if;
    select t.from_location_id, t.to_location_id, t.status into v_transfer
      from public.custody_transfers t where t.id = new.custody_transfer_id;
    if v_transfer.to_location_id is distinct from v_store.location_id
       or v_transfer.from_location_id is distinct from v_staging
       or v_transfer.status is distinct from 'INITIATED' then
      raise exception 'G-09: a transfer slip is backed by an open custody transfer from Inward Staging to its store (DEC-65)'
        using errcode = '23514';
    end if;
    new.store_code_snapshot := v_store.code;
    new.store_name_snapshot := v_store.name;
    new.generated_by := v_actor;
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
    if (new.acknowledged_by, new.acknowledged_at, new.acknowledge_remarks, new.voided_by, new.voided_at,
        new.void_reason, new.void_return_transfer_id)
       is distinct from
       (old.acknowledged_by, old.acknowledged_at, old.acknowledge_remarks, old.voided_by, old.voided_at,
        old.void_reason, old.void_return_transfer_id) then
      raise exception 'DEC-65: acknowledgement / void stamps change only with the status' using errcode = '42501';
    end if;
    return new;
  end if;
  if not ((old.status = 'GENERATED' and new.status in ('ACKNOWLEDGED', 'VOIDED'))
          or (old.status = 'ACKNOWLEDGED' and new.status = 'VOIDED')) then
    raise exception 'DEC-65: transfer slip % cannot go from % to %', old.slip_no, old.status, new.status
      using errcode = '23514';
  end if;
  -- The acknowledgement stamps are written once, by the acknowledgement.
  if old.status = 'ACKNOWLEDGED'
     and (new.acknowledged_by, new.acknowledged_at, new.acknowledge_remarks)
         is distinct from (old.acknowledged_by, old.acknowledged_at, old.acknowledge_remarks) then
    raise exception 'DEC-66: the acknowledgement of transfer slip % is immutable', old.slip_no using errcode = '42501';
  end if;

  if new.status = 'ACKNOWLEDGED' then
    -- DEC-66 (Q12): a user of the Intermediate Store the slip is addressed to (or Super Admin).
    if not rms_private.user_holds_permission(v_actor, 'transfer_slips', 'approve')
       or not rms_private.user_acts_for_store(v_actor, new.store_id) then
      raise exception 'DEC-66: only a user of Intermediate Store % acknowledges transfer slip %',
        new.store_code_snapshot, new.slip_no using errcode = '42501';
    end if;
    select t.status, t.stock_moved into v_transfer
      from public.custody_transfers t where t.id = new.custody_transfer_id;
    if v_transfer.status is distinct from 'INITIATED' or not coalesce(v_transfer.stock_moved, false) then
      raise exception 'G-09: the goods of transfer slip % are not in transit (custody status %)',
        new.slip_no, v_transfer.status using errcode = '23514';
    end if;
    if new.void_return_transfer_id is not null or new.voided_at is not null then
      raise exception 'DEC-66: an acknowledgement carries no void' using errcode = '23514';
    end if;
    new.acknowledged_by := v_actor;
    new.acknowledged_at := coalesce(new.acknowledged_at, now());
    new.acknowledge_remarks := nullif(btrim(coalesce(new.acknowledge_remarks, '')), '');
    return new;
  end if;

  -- VOIDED (Q10): voided when Super Admin / Management edit a goods slip on it.
  if not rms_private.user_holds_permission(v_actor, 'itemization', 'configure') then
    raise exception 'DEC-65: only Super Admin or Management void a transfer slip (Q10)' using errcode = '42501';
  end if;
  if exists (select 1 from public.transfer_slip_gs g
              where g.slip_id = new.id and rms_private.gs_routing_started(g.gs_id)) then
    raise exception 'DEC-65: department routing has started on a goods slip of transfer slip %', new.slip_no
      using errcode = '23514';
  end if;
  if old.status = 'GENERATED' then
    if new.void_return_transfer_id is not null then
      raise exception 'DEC-66: a slip that was not acknowledged is voided by cancelling its transit (no return transfer)'
        using errcode = '23514';
    end if;
  else
    -- DEC-66: the acknowledged stock came back from the store's location to Inward Staging
    -- through an accepted custody transfer of the same quantity.
    select s.location_id into v_store_loc from public.intermediate_stores s where s.id = new.store_id;
    select t.from_location_id, t.to_location_id, t.status, t.purpose_code,
           (select coalesce(sum(l.qty_sent), 0) from public.custody_transfer_lines l where l.transfer_id = t.id) as qty
      into v_return
      from public.custody_transfers t where t.id = new.void_return_transfer_id;
    if new.void_return_transfer_id is null
       or v_return.status is distinct from 'ACCEPTED'
       or v_return.purpose_code is distinct from 'TRANSFER_SLIP_VOID'
       or v_return.from_location_id is distinct from v_store_loc
       or v_return.to_location_id is distinct from v_staging
       or v_return.qty is distinct from (select coalesce(sum(l.qty_sent), 0)
                                           from public.custody_transfer_lines l
                                          where l.transfer_id = new.custody_transfer_id) then
      raise exception 'DEC-66: an acknowledged transfer slip is voided only after its goods went back from the store to Inward Staging (accepted TRANSFER_SLIP_VOID transfer)'
        using errcode = '23514';
    end if;
  end if;
  new.voided_by := v_actor;
  return new;
end
$$;
revoke all on function rms_private.transfer_slips_guard() from public, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- 4. Discrepancy reports (Q13: remark only, the slip stays GENERATED)
-- ---------------------------------------------------------------------------------------------
create table public.transfer_slip_discrepancies (
  id           uuid primary key default gen_random_uuid(),
  slip_id      uuid not null references public.transfer_slips (id) on delete restrict,
  remark       text not null check (length(btrim(remark)) >= 3),
  reported_by  uuid not null default rms_private.current_actor()
                 references public.profiles (id) on delete restrict,
  reported_at  timestamptz not null default now(),
  created_at   timestamptz not null default now()
);
create index transfer_slip_discrepancies_slip_idx on public.transfer_slip_discrepancies (slip_id);
create index transfer_slip_discrepancies_reported_by_idx on public.transfer_slip_discrepancies (reported_by);
comment on table public.transfer_slip_discrepancies is
  'DEC-66 (Q13): "Report discrepancy" on a transfer slip by its store: remark only, no quantity change; the slip stays GENERATED. Append-only history.';

create or replace function rms_private.transfer_slip_discrepancies_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_slip  public.transfer_slips%rowtype;
  v_actor uuid := rms_private.current_actor();
begin
  if tg_op <> 'INSERT' then
    raise exception 'DEC-66: discrepancy reports are kept as history' using errcode = '42501';
  end if;
  select * into v_slip from public.transfer_slips where id = new.slip_id;
  if v_slip.status is distinct from 'GENERATED' then
    raise exception 'DEC-66: a discrepancy is reported on a transfer slip waiting for acknowledgement (status %)',
      v_slip.status using errcode = '23514';
  end if;
  if not rms_private.user_holds_permission(v_actor, 'transfer_slips', 'approve')
     or not rms_private.user_acts_for_store(v_actor, v_slip.store_id) then
    raise exception 'DEC-66: only a user of Intermediate Store % reports a discrepancy on transfer slip %',
      v_slip.store_code_snapshot, v_slip.slip_no using errcode = '42501';
  end if;
  new.reported_by := v_actor;
  new.remark := btrim(new.remark);
  return new;
end
$$;
revoke all on function rms_private.transfer_slip_discrepancies_guard() from public, anon, authenticated;
create trigger transfer_slip_discrepancies_guard
  before insert or update or delete on public.transfer_slip_discrepancies
  for each row execute function rms_private.transfer_slip_discrepancies_guard();

alter table public.transfer_slip_discrepancies enable row level security;
revoke all on public.transfer_slip_discrepancies from anon, authenticated;
grant select, insert on public.transfer_slip_discrepancies to rms_api;
select rms_private.attach_standard_triggers('public.transfer_slip_discrepancies');

-- ---------------------------------------------------------------------------------------------
-- 5. Custody G-09 guard (full body replaced: 20261105000100 + the DEC-66 slip rules)
-- ---------------------------------------------------------------------------------------------
create or replace function rms_private.custody_transfers_g09_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_sod         boolean;
  v_slip_status text;
  v_slip_no     text;
  v_exempt      boolean := false;
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

  -- DEC-66: the custody transfer behind a transfer slip follows the slip. Accepted only with the
  -- slip acknowledgement, cancelled only with the slip void, never a discrepancy (Q13).
  select s.status, s.slip_no into v_slip_status, v_slip_no
    from public.transfer_slips s where s.custody_transfer_id = new.id;
  if v_slip_status is not null then
    if new.status = 'ACCEPTED' and v_slip_status <> 'ACKNOWLEDGED' then
      raise exception 'DEC-66: transfer slip % is received by acknowledging the slip, not the custody transfer', v_slip_no
        using errcode = '23514';
    end if;
    if new.status = 'CANCELLED' and v_slip_status <> 'VOIDED' then
      raise exception 'DEC-66: transfer slip % is cancelled only by voiding the slip (Q10)', v_slip_no
        using errcode = '23514';
    end if;
    if new.status = 'DISCREPANCY' then
      raise exception 'DEC-66 (Q13): transfer slip % is acknowledged in full; report a discrepancy on the slip', v_slip_no
        using errcode = '23514';
    end if;
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
    -- DEC-34: technician coordinators allot and receive on behalf of the technician.
    -- DEC-21: store issue auto-acknowledgement on behalf of main store.
    -- DEC-66: the return of a voided, acknowledged transfer slip (Q10) is accepted on behalf of
    -- Inward Staging by the Super Admin / Management who voided it, and only store → staging.
    if new.purpose_code = 'TRANSFER_SLIP_VOID' then
      v_exempt := rms_private.user_holds_permission(new.accepted_by, 'itemization', 'configure')
              and new.to_location_id = (select id from public.inventory_locations where code = 'INWARD_STAGING')
              and exists (select 1 from public.intermediate_stores s where s.location_id = new.from_location_id);
      if not v_exempt then
        raise exception 'DEC-66: a TRANSFER_SLIP_VOID return goes from an Intermediate Store to Inward Staging, by Super Admin / Management'
          using errcode = '42501';
      end if;
    end if;
    if coalesce(new.purpose_code, '') not in ('TECHNICIAN_ALLOTMENT', 'TECHNICIAN_RECEIVING', 'STORE_ISSUE')
       and not v_exempt then
      select coalesce((s.value #>> '{}')::boolean, true) into v_sod
        from public.system_settings s where s.key = 'segregation_of_duties_transfer';
      if coalesce(v_sod, true) and new.accepted_by = new.initiated_by then
        raise exception 'SEGREGATION_OF_DUTIES: the initiator of transfer % cannot accept it', new.transfer_no
          using errcode = '42501';
      end if;
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

-- ---------------------------------------------------------------------------------------------
-- 6. Status chain (G-03 trigger, full body replaced: P5 body + the DEC-66 transitions)
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
    -- DEC-66 (P6): every live slip of the GS acknowledged by its Intermediate Store.
    if new.status = 'STORE_ACKNOWLEDGED' then
      if not rms_private.gs_slips_acknowledged(new.id) then
        raise exception 'DEC-66: every transfer slip of the goods slip must be acknowledged by its store first'
          using errcode = '23514';
      end if;
      return new;
    end if;
    raise exception 'G-03: a goods slip on transfer slips goes to STORE_ACKNOWLEDGED (DEC-66) or back to PENDING_TRANSFER_SLIP (Q10), not %', new.status
      using errcode = '23514';
  end if;
  -- DEC-66: an acknowledged GS goes back only when a slip of it is voided (Q10). Department
  -- routing (P7) adds its exit.
  if old.status = 'STORE_ACKNOWLEDGED' then
    if new.status = 'PENDING_TRANSFER_SLIP' then
      if rms_private.gs_transfer_slip_gaps(new.id) = 0 then
        raise exception 'DEC-65: the goods slip is still fully on live transfer slips' using errcode = '23514';
      end if;
      return new;
    end if;
    raise exception 'G-03: % is not reachable from STORE_ACKNOWLEDGED yet (department routing, P7)', new.status
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
-- 7. Permission: acknowledge / report a discrepancy (grants: seed.sql + snippet)
-- ---------------------------------------------------------------------------------------------
insert into public.permissions (module_code, action, description)
values ('transfer_slips', 'approve',
        'Acknowledge receipt of a transfer slip / report a discrepancy, for the user''s own Intermediate Store (DEC-66)')
on conflict (module_code, action) do nothing;

insert into public.role_permissions (role_id, permission_id, scope)
select r.id, p.id, 'all'
  from public.roles r
  join public.permissions p on p.module_code = 'transfer_slips' and p.action = 'approve'
 where r.code = 'SUPER_ADMIN'
on conflict (role_id, permission_id) do nothing;

-- ---------------------------------------------------------------------------------------------
-- 8. Journey catalogue (role menus: seed.sql + snippet)
-- ---------------------------------------------------------------------------------------------
alter table public.journey_steps drop constraint if exists journey_steps_screen_key_check;
alter table public.journey_steps add constraint journey_steps_screen_key_check check (screen_key in (
  'journey-queue', 'gs-new', 'gs-list', 'dashboard', 'pendencies',
  'container-audit', 'reports', 'audit', 'custody', 'inventory', 'store-issues',
  'servicing', 'batteries', 'dismantling', 'scrap', 'credit-notes', 'approvals',
  'dispatch-queue', 'department-routing', 'department-receiving', 'department-issue',
  'accounts-entry', 'accounts-docs', 'dispatch-slips', 'transfer-slips', 'transfer-slip-acks'));

alter table public.journey_steps drop constraint if exists journey_steps_item_screen_key_check;
alter table public.journey_steps add constraint journey_steps_item_screen_key_check check (
  item_screen_key is null or item_screen_key in (
    'gs-detail', 'gs-unboxing', 'gs-itemization', 'gs-inspection', 'gs-rm-review',
    'custody-transfer', 'gs-final-actions', 'department-receiving', 'department-issue',
    'accounts-entry-gs', 'accounts-docs', 'dispatch-slips',
    'gs-party-notification', 'transfer-slips', 'transfer-slip'));

alter table public.journey_steps drop constraint if exists journey_steps_queue_code_check;
alter table public.journey_steps add constraint journey_steps_queue_code_check check (
  queue_code is null or queue_code in (
    'CARTON_OPENING', 'COUNTING', 'CATEGORISATION', 'INSPECTION', 'RM_REVIEW', 'STORE_ACCEPT',
    'DEPT_ROUTING', 'DEPT_ISSUE', 'DEPT_RECEIVING', 'FINAL_ACTIONS', 'ACCOUNTS_DOCS',
    'ACCOUNTS_ENTRY', 'DISPATCH_SLIP', 'PARTY_EMAIL', 'PENDING_TRANSFER_SLIP', 'EDIT_REQUESTS',
    'STORE_ACK'));

insert into public.journey_steps
  (code, label, hint, kind, screen_key, item_screen_key, queue_code, feature_code,
   perm_module, perm_action, sort_order, source_ref)
values
  ('ACK_TRANSFER_SLIPS', 'Acknowledge Transfer Slips',
   'Transfer slips sent to your Intermediate Store: check the goods and acknowledge receipt',
   'STEP', 'transfer-slip-acks', 'transfer-slip', 'STORE_ACK', null,
   'transfer_slips', 'approve', 56, 'DEC-66')
on conflict (code) do nothing;

-- ---------------------------------------------------------------------------------------------
-- 9. Notification event types (recipients = rules in seed.sql + the release snippet)
-- ---------------------------------------------------------------------------------------------
insert into public.notification_event_types
  (code, label, description, category, default_priority, is_mandatory, source_ref, sort_order)
values
  ('TRANSFER_SLIP_GENERATED', 'Transfer slip for your store',
   'DEC-66: the Replacement Manager generated a transfer slip for an Intermediate Store; its users acknowledge the receipt.',
   'WORKFLOW', 'NORMAL', false, 'DEC-66', 555),
  ('TRANSFER_SLIP_DISCREPANCY', 'Transfer slip discrepancy reported',
   'DEC-66 (Q13): an Intermediate Store reported a discrepancy on a transfer slip (remark only; the slip stays open).',
   'WORKFLOW', 'HIGH', false, 'DEC-66', 557)
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
       'P6 default'
  from (values ('TRANSFER_SLIP_GENERATED'), ('TRANSFER_SLIP_DISCREPANCY')) as v(event_type)
 where not exists (select 1 from public.notification_templates t
                    where t.event_type = v.event_type and t.channel = 'EMAIL');
