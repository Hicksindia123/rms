-- ===========================================================================
-- P3-07: Party notification, GS closure engine & Complete Sales Return closure
-- References: Master Plan §2.2 (Step-7), §6.5, §8 (party_notifications, gs_closures),
--             DD r79 (PRIOR_INFO_SENT), DD r80 (CSR_CLOSED), WF r11,
--             BR-09, BR-38, BR-39, G-08, G-15, DEC-25.
--
-- 1. party_notifications (DEC-25: channel, recipient, timestamp, message snapshot, optional proof).
--    Append-only; the CN must be ISSUED and of the same GS; proof = CONFIRMED NOTIFICATION_PROOF.
-- 2. gs_closures (one row per GS; reopen fields kept; every change audited).
-- 3. rms_private.gs_closure_checklist(gs): the single closure checklist. The backend service shows
--    it (with fix links) and the database trigger below re-runs it, so the two layers cannot drift.
-- 4. G-15 on goods_slips: CLOSED only when every applicable checklist item passes and a matching
--    gs_closures row exists; a CLOSED GS only leaves CLOSED through a recorded Super Admin reopen.
-- 5. Settings: gs_closure_roles (default RM + Accounts).
-- ===========================================================================

-- ===========================================================================
-- 1. party_notifications (BR-38, DD r79, DEC-25)
-- ===========================================================================
create table public.party_notifications (
  id                   uuid primary key default gen_random_uuid(),
  gs_id                uuid not null references public.goods_slips (id) on delete restrict,
  credit_note_id       uuid references public.credit_notes (id) on delete restrict,
  status_code          text not null default 'PRIOR_INFO_SENT' check (status_code = 'PRIOR_INFO_SENT'),
  status_label         text,
  channel_code         text not null check (channel_code in ('EMAIL','WHATSAPP','PHONE','LETTER','OTHER')),
  recipient            text not null check (btrim(recipient) <> ''),
  message              text not null check (btrim(message) <> ''),
  message_snapshot     jsonb not null check (jsonb_typeof(message_snapshot) = 'object'),
  -- DEC-25: SMTP sending is Phase 4; until then every notification is recorded manually.
  delivery_mode        text not null default 'RECORDED_MANUALLY' check (delivery_mode = 'RECORDED_MANUALLY'),
  proof_attachment_id  uuid references public.attachments (id) on delete restrict,
  form_version_id      uuid references public.form_versions (id) on delete restrict,
  sent_by              uuid not null default rms_private.current_actor() references public.profiles (id) on delete restrict,
  sent_at              timestamptz not null default now(),
  created_at           timestamptz not null default now()
);

create index party_notifications_gs_idx on public.party_notifications (gs_id);
create index party_notifications_cn_idx on public.party_notifications (credit_note_id);
create index party_notifications_proof_idx on public.party_notifications (proof_attachment_id);
create index party_notifications_sent_by_idx on public.party_notifications (sent_by);
create index party_notifications_form_version_idx on public.party_notifications (form_version_id);

create or replace function rms_private.party_notifications_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_gs_status text;
  v_cn        record;
  v_att       record;
begin
  if tg_op <> 'INSERT' then
    raise exception 'BR-38: party notifications are append-only evidence' using errcode = '23514';
  end if;

  select status into v_gs_status from public.goods_slips where id = new.gs_id;
  if v_gs_status in ('CLOSED', 'CANCELLED') then
    raise exception 'BR-38: a party notification cannot be recorded on a % GS', v_gs_status
      using errcode = '23514';
  end if;

  if new.credit_note_id is not null then
    select gs_id, status into v_cn from public.credit_notes where id = new.credit_note_id;
    if not found or v_cn.gs_id <> new.gs_id then
      raise exception 'BR-38: the credit note does not belong to this GS' using errcode = '23514';
    end if;
    if v_cn.status <> 'ISSUED' then
      raise exception 'BR-38: notify the party only after the CN/JV is ISSUED (status %)', v_cn.status
        using errcode = '23514';
    end if;
  end if;

  if new.proof_attachment_id is not null then
    select gs_id, kind, status into v_att from public.attachments where id = new.proof_attachment_id;
    if not found or v_att.gs_id <> new.gs_id or v_att.kind <> 'NOTIFICATION_PROOF'
       or v_att.status <> 'CONFIRMED' then
      raise exception 'DEC-25: the proof must be a confirmed NOTIFICATION_PROOF upload of this GS'
        using errcode = '23514';
    end if;
  end if;
  return new;
end
$$;
revoke all on function rms_private.party_notifications_guard() from public, anon, authenticated;

create trigger party_notifications_guard
  before insert or update or delete on public.party_notifications
  for each row execute function rms_private.party_notifications_guard();

-- ===========================================================================
-- 2. gs_closures (§8: gs_id unique, closure_type, checklist_snapshot, closed/reopened fields)
-- ===========================================================================
create table public.gs_closures (
  id                  uuid primary key default gen_random_uuid(),
  gs_id               uuid not null unique references public.goods_slips (id) on delete restrict,
  closure_type        text not null check (closure_type in ('CSR_CLOSED','RO_CLOSED')),
  closure_label       text,
  checklist_snapshot  jsonb not null check (jsonb_typeof(checklist_snapshot) = 'object'),
  remarks             text,
  close_count         integer not null default 1 check (close_count >= 1),
  closed_by           uuid not null default rms_private.current_actor() references public.profiles (id) on delete restrict,
  closed_at           timestamptz not null default now(),
  reopened_by         uuid references public.profiles (id) on delete restrict,
  reopened_at         timestamptz,
  reopen_reason       text,
  reopen_count        integer not null default 0 check (reopen_count >= 0),
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  constraint gs_closures_reopen_fields check (
    (reopened_at is null and reopened_by is null and reopen_reason is null)
    or (reopened_at is not null and reopened_by is not null
        and reopen_reason is not null and btrim(reopen_reason) <> '')
  )
);

create index gs_closures_closed_by_idx on public.gs_closures (closed_by);
create index gs_closures_reopened_by_idx on public.gs_closures (reopened_by);
create index gs_closures_closed_at_idx on public.gs_closures (closed_at desc);

create or replace function rms_private.gs_closures_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'G-15: closure records are never deleted' using errcode = '23514';
  end if;
  if tg_op = 'UPDATE' and new.gs_id <> old.gs_id then
    raise exception 'G-15: a closure record cannot move to another GS' using errcode = '23514';
  end if;
  -- §6.5: reopen only by a Super Admin with a reason (the backend checks it too).
  if new.reopened_at is not null
     and (tg_op = 'INSERT' or new.reopened_at is distinct from old.reopened_at)
     and not exists (select 1 from public.profiles p
                      where p.id = new.reopened_by and p.is_super_admin and p.is_active) then
    raise exception 'G-15: only an active Super Admin can reopen a closed GS' using errcode = '23514';
  end if;
  return new;
end
$$;
revoke all on function rms_private.gs_closures_guard() from public, anon, authenticated;

create trigger gs_closures_guard
  before insert or update or delete on public.gs_closures
  for each row execute function rms_private.gs_closures_guard();

-- ===========================================================================
-- 3. The closure checklist (G-15, BR-38, BR-39) — one implementation for API and DB guard
-- ===========================================================================
create or replace function rms_private.gs_closure_type(p_gs_id uuid)
returns text
language sql
stable
set search_path = ''
as $$
  -- BR-09 / BR-39: an approved CSR (category still CSR) closes as CSR; RO (incl. CSR→RO) as RO.
  select case when g.category_code = 'CSR' then 'CSR_CLOSED' else 'RO_CLOSED' end
    from public.goods_slips g where g.id = p_gs_id
$$;

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
begin
  select g.id, g.gs_no, g.status, g.category_code, g.has_discrepancy
    into v_gs from public.goods_slips g where g.id = p_gs_id;
  if not found then
    raise exception 'Goods slip % not found', p_gs_id using errcode = 'P0002';
  end if;
  v_csr := v_gs.category_code = 'CSR';

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

  -- 3. Every remaining piece is in a terminal or accounted location (G-15, BR-30):
  --    functional → Main Store or dispatched; non-good / parts → Spare Parts Manager stores;
  --    rejected / hazard → hold or quarantine with a recorded rejection disposition.
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

  -- 6. RM Step-7 CN decision recorded where a commercial resolution is needed (BR-32).
  v_needs_dec := v_csr or exists (
    select 1 from public.rm_item_actions a
      join public.gs_items gi on gi.id = a.gs_item_id
     where gi.gs_id = p_gs_id and a.is_current
       and a.action_code in ('ISSUE_CN', 'SEND_NEW', 'SEND_REPAIRED'));
  v_has_dec := exists (select 1 from public.rm_cn_decisions d where d.gs_id = p_gs_id and d.is_current);
  return query select 60, 'CN_DECISION_RECORDED', 'BR-32', v_needs_dec, (not v_needs_dec) or v_has_dec,
    case when not v_needs_dec then 'No commercial resolution needed (no CN / replacement action)'
         when v_has_dec then 'The Replacement Manager''s CN decision is recorded'
         else 'The Replacement Manager''s Step-7 CN decision is missing' end,
    jsonb_build_object('decision_recorded', v_has_dec);

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

  -- 9. Every issued CN / JV has a PRIOR_INFO_SENT notification (BR-38, DD r79, G-15).
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
  return query select 90, 'PRIOR_NOTIFICATION', 'BR-38', v_issued > 0, v_count = 0,
    case when v_issued = 0 then 'No CN / JV issued, so no prior notification is required'
         when v_count = 0 then 'The party was notified of every issued CN / JV before closure'
         else v_count || ' issued CN / JV without a prior party notification (PRIOR_INFO_SENT)' end,
    jsonb_build_object('credit_notes', v_rows);

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

  return query select 120, 'CSR_CN_ISSUED', 'BR-39', v_csr, (not v_csr) or v_issued > 0,
    case when not v_csr then 'Not a Complete Sales Return'
         when v_issued > 0 then 'A credit note / JV is issued'
         else 'No credit note / JV is issued for this CSR' end,
    jsonb_build_object('issued_credit_notes', v_issued);
end
$$;
revoke all on function rms_private.gs_closure_checklist(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_closure_checklist(uuid) to rms_api;
revoke all on function rms_private.gs_closure_type(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_closure_type(uuid) to rms_api;

-- ===========================================================================
-- 4. G-15 on goods_slips: close only when the checklist passes; leave CLOSED only by reopen
-- ===========================================================================
create or replace function rms_private.goods_slips_g15_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_failed   text;
  v_closure  record;
  v_type     text;
begin
  if new.status is not distinct from old.status then
    if new.status = 'CLOSED' and (new.closure_type is distinct from old.closure_type
                                  or new.closed_at is distinct from old.closed_at) then
      raise exception 'G-15: the closure of a CLOSED GS cannot be edited' using errcode = '23514';
    end if;
    return new;
  end if;

  -- Leaving CLOSED: only to COMMERCIAL_RESOLUTION after a recorded Super Admin reopen (§6.5).
  if old.status = 'CLOSED' then
    select * into v_closure from public.gs_closures c where c.gs_id = new.id;
    if new.status <> 'COMMERCIAL_RESOLUTION' or v_closure.id is null
       or v_closure.reopened_at is null or v_closure.reopened_at < v_closure.closed_at then
      raise exception 'G-15: GS % is CLOSED; only a Super Admin reopen (with reason) returns it to COMMERCIAL_RESOLUTION',
        new.gs_no using errcode = '23514';
    end if;
    return new;
  end if;

  if new.status <> 'CLOSED' then
    return new;
  end if;

  -- Entering CLOSED: every applicable checklist item passes (evaluated on the pre-update row).
  select string_agg(c.code, ', ' order by c.sort_order) into v_failed
    from rms_private.gs_closure_checklist(new.id) c
   where c.applicable and not c.passed;
  if v_failed is not null then
    raise exception 'G-15: GS % cannot be closed; failing checks: %', new.gs_no, v_failed
      using errcode = '23514';
  end if;

  v_type := rms_private.gs_closure_type(new.id);
  select * into v_closure from public.gs_closures c where c.gs_id = new.id;
  if v_closure.id is null or v_closure.closure_type <> v_type
     or (v_closure.reopened_at is not null and v_closure.closed_at <= v_closure.reopened_at) then
    raise exception 'G-15: GS % needs a current % closure record before it is CLOSED', new.gs_no, v_type
      using errcode = '23514';
  end if;
  if new.closure_type is distinct from v_type or new.closed_at is null then
    raise exception 'G-15: GS % must close as % (BR-39)', new.gs_no, v_type using errcode = '23514';
  end if;
  return new;
end
$$;
revoke all on function rms_private.goods_slips_g15_guard() from public, anon, authenticated;

create trigger goods_slips_g15_guard
  before update of status, closure_type, closed_at on public.goods_slips
  for each row execute function rms_private.goods_slips_g15_guard();

-- ===========================================================================
-- 5. Settings (CLAUDE.md rule b: configurable, never hidden code)
-- ===========================================================================
insert into public.system_settings (key, value, category, description, source_ref) values
  ('gs_closure_roles', '["REPLACEMENT_MANAGER", "ACCOUNTS"]'::jsonb, 'workflow',
   'Roles allowed to close a goods slip (S6_CLOSE). Super Admin always may. The closure checklist (G-15) cannot be bypassed by any role.',
   'P3-07'),
  ('party_notification_message_template',
   to_jsonb(E'Dear {party_name},\nThis is prior information on your return under Goods Slip {gs_no}.\n{voucher_label}: {voucher_no} dated {voucher_date}\nItems:\n{items}\nTotal value: {total_value}\n{dispatch_details}'::text),
   'notifications',
   'Party notification message (BR-38, DD r79). Placeholders: {party_name} {gs_no} {voucher_label} {voucher_no} {voucher_date} {items} {total_value} {dispatch_details}. The structured CN No. / Date / items are always stored in message_snapshot.',
   'DEC-25')
on conflict (key) do nothing;

-- ===========================================================================
-- 6. Audit, RLS, grants
-- ===========================================================================
select rms_private.attach_standard_triggers('public.party_notifications');
select rms_private.attach_standard_triggers('public.gs_closures');

alter table public.party_notifications enable row level security;
alter table public.gs_closures enable row level security;

revoke all on public.party_notifications from anon, authenticated;
revoke all on public.gs_closures from anon, authenticated;

-- Default privileges gave rms_api full DML: notifications are append-only, closures never deleted.
revoke update, delete on public.party_notifications from rms_api;
revoke delete on public.gs_closures from rms_api;
grant select, insert on public.party_notifications to rms_api;
grant select, insert, update on public.gs_closures to rms_api;

grant all on public.party_notifications to service_role;
grant all on public.gs_closures to service_role;
