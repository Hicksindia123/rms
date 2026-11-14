create or replace function rms_private.custody_transfers_g09_guard()
returns trigger
language plpgsql
set search_path = ''
as $body$
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
    if coalesce(new.purpose_code, '') not in ('TECHNICIAN_ALLOTMENT', 'TECHNICIAN_RECEIVING', 'STORE_ISSUE') then
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
$body$;

revoke all on function rms_private.custody_transfers_g09_guard() from public, anon, authenticated;
