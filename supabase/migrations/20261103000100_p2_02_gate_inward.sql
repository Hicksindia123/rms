-- P2-02 · Step-1 Gate inward & GS creation (master plan §2.2 Step-1, §3.2 DD r2–r10, BR-01..BR-03,
-- DEC-01, DEC-02, DEC-03, DEC-05, G-01, G-17). Fixes forward on 20261102000900 (P2-01):
--
-- 1. P2-01 hard-coded delivery-mode / gate-document code lists that do not exist in the §3.2
--    catalogue ('DIRECT_VEHICLE', 'DIRECT_PERSON', 'CHALLAN', 'LR_BILITY', 'DELIVERY_NOTE', 'OTHER').
--    They are replaced by a trigger that validates the codes against the configured option sets
--    (DELIVERY_MODE = DD r2–r4, GATE_DOCUMENT = DD r5–r9), plus named CHECKs per stable code.
-- 2. DIRECT_TRUCK accepts a transporter from the master OR a free-text name (P2-02 "master or new
--    name"): new column transporter_name.
-- 3. DEC-02 state/station override flag; cancellation columns (§6.5 CANCELLED).
-- 4. G-01: gs_no is immutable once generated; CANCELLED only before Step-2 completes, never reopened.
-- 5. G-17: audit_log gains a `reason` column, filled from the transaction setting app.reason, so
--    edits "audited with reason" keep the reason next to the row change.

-- ===========================================================================
-- 1. Replace the P2-01 code lists and conditional checks
-- ===========================================================================
do $$
declare
  c record;
begin
  for c in
    select conname
      from pg_constraint
     where conrelid = 'public.goods_slips'::regclass
       and contype = 'c'
       and (pg_get_constraintdef(oid) like '%delivery_mode_code%'
            or pg_get_constraintdef(oid) like '%gate_document_code%')
  loop
    execute format('alter table public.goods_slips drop constraint %I', c.conname);
  end loop;
end
$$;

alter table public.goods_slips
  add column transporter_name          text,
  add column state_station_overridden  boolean not null default false,
  add column cancelled_at              timestamptz,
  add column cancelled_by              uuid references public.profiles (id) on delete restrict,
  add column cancel_reason             text;

create index goods_slips_created_at_idx on public.goods_slips (created_at desc);
create index goods_slips_cancelled_by_idx on public.goods_slips (cancelled_by);

alter table public.goods_slips
  -- DD r2: Courier / Parcel → courier name + docket no.
  add constraint goods_slips_courier_fields check (
    delivery_mode_code <> 'COURIER_PARCEL'
    or (coalesce(btrim(courier_name), '') <> '' and coalesce(btrim(docket_no), '') <> '')),
  -- DD r3: Direct Transport / Truck → vehicle no. + transporter (master or new name)
  add constraint goods_slips_truck_fields check (
    delivery_mode_code <> 'DIRECT_TRUCK'
    or (coalesce(btrim(vehicle_no), '') <> ''
        and (transporter_id is not null or coalesce(btrim(transporter_name), '') <> ''))),
  -- DD r4: Self / Party Representative → person name + contact no.
  add constraint goods_slips_rep_fields check (
    delivery_mode_code <> 'SELF_PARTY_REP'
    or (coalesce(btrim(rep_name), '') <> '' and coalesce(btrim(rep_contact), '') <> '')),
  -- DD r5–r7: Invoice / Debit Note / Delivery Challan → number + date
  add constraint goods_slips_formal_doc_fields check (
    gate_document_code is null
    or gate_document_code not in ('INVOICE', 'DEBIT_NOTE', 'DELIVERY_CHALLAN')
    or (coalesce(btrim(gate_doc_no), '') <> '' and gate_doc_date is not null)),
  -- DD r8: Handwritten Slip / Party Note → slip details / party remarks
  add constraint goods_slips_slip_fields check (
    gate_document_code is distinct from 'HANDWRITTEN_SLIP'
    or coalesce(btrim(gate_doc_remarks), '') <> ''),
  -- DD r9 / BR-03: No Document Attached is only allowed with the missing-documentation flag
  add constraint goods_slips_no_document_flag check (
    gate_document_code is distinct from 'NO_DOCUMENT' or missing_documentation),
  -- §6.5: a cancelled GS always carries when and why
  add constraint goods_slips_cancel_fields check (
    status <> 'CANCELLED'
    or (cancelled_at is not null and coalesce(btrim(cancel_reason), '') <> ''));

-- Codes must exist in the configured option sets (labels stay editable; codes are immutable).
create or replace function rms_private.goods_slips_validate_codes()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' or new.delivery_mode_code is distinct from old.delivery_mode_code then
    if not exists (
      select 1 from public.option_items oi
        join public.option_sets os on os.id = oi.option_set_id
       where os.code = 'DELIVERY_MODE' and oi.code = new.delivery_mode_code and oi.is_active
    ) then
      raise exception 'Unknown or inactive delivery mode %', new.delivery_mode_code
        using errcode = '23514';
    end if;
  end if;
  if new.gate_document_code is not null
     and (tg_op = 'INSERT' or new.gate_document_code is distinct from old.gate_document_code) then
    if not exists (
      select 1 from public.option_items oi
        join public.option_sets os on os.id = oi.option_set_id
       where os.code = 'GATE_DOCUMENT' and oi.code = new.gate_document_code and oi.is_active
    ) then
      raise exception 'Unknown or inactive gate document %', new.gate_document_code
        using errcode = '23514';
    end if;
  end if;
  return new;
end
$$;
revoke all on function rms_private.goods_slips_validate_codes() from public, anon, authenticated;

create trigger goods_slips_validate_codes
  before insert or update of delivery_mode_code, gate_document_code on public.goods_slips
  for each row execute function rms_private.goods_slips_validate_codes();

-- G-01: the generated GS number never changes. §6.5: CANCELLED only from GATE_CREATED / UNBOXING
-- ("before Step-2 completes") and is terminal (no reopen path is defined for a cancelled GS).
create or replace function rms_private.goods_slips_lifecycle_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.gs_no is distinct from old.gs_no then
    raise exception 'G-01: the generated GS number % cannot be changed', old.gs_no
      using errcode = '23514';
  end if;
  if new.status = 'CANCELLED' and old.status <> 'CANCELLED'
     and old.status not in ('GATE_CREATED', 'UNBOXING') then
    raise exception 'A goods slip can only be cancelled before unboxing completes (status %)', old.status
      using errcode = '23514';
  end if;
  if old.status = 'CANCELLED' and new.status <> 'CANCELLED' then
    raise exception 'A cancelled goods slip cannot change status'
      using errcode = '23514';
  end if;
  return new;
end
$$;
revoke all on function rms_private.goods_slips_lifecycle_guard() from public, anon, authenticated;

create trigger goods_slips_lifecycle_guard
  before update on public.goods_slips
  for each row execute function rms_private.goods_slips_lifecycle_guard();

-- ===========================================================================
-- 2. G-17: audit reason
-- ===========================================================================
alter table public.audit_log add column reason text;

create or replace function rms_private.current_audit_reason()
returns text
language sql
stable
set search_path = ''
as $$
  select nullif(current_setting('app.reason', true), '')
$$;
revoke all on function rms_private.current_audit_reason() from public;
grant execute on function rms_private.current_audit_reason() to rms_api;

-- Same body as 20261102000500, plus the reason column.
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

  insert into public.audit_log (table_name, row_id, action, "old", "new", changed_fields, actor_id,
                                request_id, reason)
  values (tg_table_schema || '.' || tg_table_name, v_row_id, tg_op, v_old, v_new, v_changed,
          rms_private.current_actor(), rms_private.current_request_id(),
          rms_private.current_audit_reason());
  return null;
end
$$;
revoke all on function rms_private.audit_row() from public;

-- ===========================================================================
-- 3. Lookup index for the gate "My Work" inbox (open tasks per role)
-- ===========================================================================
create index workflow_tasks_open_role_idx on public.workflow_tasks (assigned_role_id, created_at desc)
  where status = 'OPEN';
