-- Change plan 2026-11-12 · Phase 2 — Gate Entry revamp (Offline / E-Commerce).
-- Sources: docs/RMS_MASTER_PLAN_ADDENDUM_2026-11.md AMD-01 … AMD-05, DEC-38, DEC-39; G-02, G-18.
--
-- 1. goods_slips: return_type_code (AMD-01, option set RETURN_TYPE), gate_entry_date /
--    gate_entry_no (AMD-02, required for OFFLINE_RETURN, absent for ECOMMERCE_RETURN per DEC-39),
--    gate_entry_fy + unique (FY, number) per DEC-38, date <= business today and the optional
--    `gate.max_backdate_days` limit.
-- 2. carton_count (AMD-03) replaces the business concept box_count. box_count stays readable and is
--    kept in sync both ways by a trigger until all code is switched (dropped in a later migration).
-- 3. gs_gate_documents (AMD-04): many document rows per GS with files (attachments kind GATE_DOC).
--    Existing single gate documents are migrated. "No document" stays the GS-level
--    missing_documentation flag (DEC-03) and is exclusive with document rows.
-- 4. Settings: gate.max_backdate_days (DEC-38), gate.accounts_alert_doc_types (AMD-05).
-- 5. G-02 (AMD-03): one confirmed unboxing video per CARTON before a GS leaves UNBOXING.
--
-- Legacy rows (created before AMD-01) keep return_type_code NULL: they never had a return type,
-- and inventing one would also invent gate entry numbers. Every GS created through the API gets a
-- return type (service-enforced; docs/DECISIONS.md 2026-11-13).

-- ===========================================================================
-- 0. Business "today" (timezone setting, default Asia/Kolkata as seeded)
-- ===========================================================================
create or replace function rms_private.business_today()
returns date
language sql
stable
set search_path = ''
as $$
  select (now() at time zone coalesce(
            (select s.value #>> '{}' from public.system_settings s where s.key = 'timezone'),
            'Asia/Kolkata'))::date
$$;
revoke all on function rms_private.business_today() from public, anon, authenticated;
grant execute on function rms_private.business_today() to rms_api;

-- ===========================================================================
-- 1. goods_slips: return type, gate entry date / number, carton count
-- ===========================================================================
alter table public.goods_slips
  add column return_type_code text,
  add column gate_entry_date  date,
  add column gate_entry_no    bigint check (gate_entry_no is null or gate_entry_no > 0),
  -- DEC-38: financial year of gate_entry_date (start year), set by trigger, never by the client.
  add column gate_entry_fy    smallint,
  add column carton_count     integer check (carton_count is null or carton_count > 0);

comment on column public.goods_slips.carton_count is
  'AMD-03: number of cartons received (replaces box_count; box_count is kept in sync until dropped).';
comment on column public.goods_slips.box_count is
  'DEPRECATED (AMD-03): mirror of carton_count, kept readable until all code uses carton_count.';
comment on column public.goods_slips.return_type_code is
  'AMD-01: RETURN_TYPE option code. NULL only on GS created before AMD-01 (2026-11-13).';
comment on column public.goods_slips.gate_document_code is
  'DEPRECATED (AMD-04): replaced by public.gs_gate_documents; kept readable for legacy rows.';

update public.goods_slips set carton_count = box_count where carton_count is null;
alter table public.goods_slips alter column carton_count set not null;

-- AMD-03: box_count <-> carton_count stay identical while both columns exist.
create or replace function rms_private.goods_slips_sync_carton_count()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' then
    new.carton_count := coalesce(new.carton_count, new.box_count);
    new.box_count := coalesce(new.box_count, new.carton_count);
  elsif new.carton_count is distinct from old.carton_count then
    new.box_count := new.carton_count;
  elsif new.box_count is distinct from old.box_count then
    new.carton_count := new.box_count;
  end if;
  return new;
end
$$;
revoke all on function rms_private.goods_slips_sync_carton_count() from public, anon, authenticated;

create trigger goods_slips_sync_carton_count
  before insert or update of box_count, carton_count on public.goods_slips
  for each row execute function rms_private.goods_slips_sync_carton_count();

alter table public.goods_slips
  add constraint goods_slips_carton_box_in_sync check (carton_count = box_count),
  -- AMD-02: an Offline Return always carries its gate entry date and number.
  add constraint goods_slips_offline_gate_entry check (
    return_type_code is distinct from 'OFFLINE_RETURN'
    or (gate_entry_date is not null and gate_entry_no is not null)),
  -- DEC-39 (PROVISIONAL): an E-Commerce Return has no gate entry date / number.
  add constraint goods_slips_ecommerce_no_gate_entry check (
    return_type_code is distinct from 'ECOMMERCE_RETURN'
    or (gate_entry_date is null and gate_entry_no is null)),
  add constraint goods_slips_gate_entry_fy_set check (
    (gate_entry_date is null) = (gate_entry_fy is null));

-- DEC-38 (PROVISIONAL): the gate entry number is unique per financial year. A cancelled GS frees
-- its number so the consignment can be re-entered correctly.
create unique index goods_slips_gate_entry_no_fy_key
  on public.goods_slips (gate_entry_fy, gate_entry_no)
  where gate_entry_no is not null and status <> 'CANCELLED';

-- AMD-01 / AMD-02 / DEC-38: code from the option set, date <= business today, optional back-date
-- limit, FY derived from the GS number series start month.
create or replace function rms_private.goods_slips_gate_entry_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_today     date;
  v_max_days  jsonb;
  v_fy_start  smallint;
begin
  if new.return_type_code is not null
     and (tg_op = 'INSERT' or new.return_type_code is distinct from old.return_type_code) then
    if not exists (
      select 1 from public.option_items oi
        join public.option_sets os on os.id = oi.option_set_id
       where os.code = 'RETURN_TYPE' and oi.code = new.return_type_code and oi.is_active
    ) then
      raise exception 'AMD-01: unknown or inactive return type %', new.return_type_code
        using errcode = '23514';
    end if;
  end if;

  if new.gate_entry_date is null then
    new.gate_entry_fy := null;
    return new;
  end if;

  if tg_op = 'INSERT' or new.gate_entry_date is distinct from old.gate_entry_date then
    v_today := rms_private.business_today();
    if new.gate_entry_date > v_today then
      raise exception 'AMD-02: the gate entry date % is later than today (%)', new.gate_entry_date, v_today
        using errcode = '23514';
    end if;
    select s.value into v_max_days from public.system_settings s where s.key = 'gate.max_backdate_days';
    if v_max_days is not null and jsonb_typeof(v_max_days) = 'number'
       and new.gate_entry_date < v_today - (v_max_days #>> '{}')::integer then
      raise exception 'DEC-38: the gate entry date % is more than % days back', new.gate_entry_date, v_max_days #>> '{}'
        using errcode = '23514';
    end if;
  end if;

  select ns.fy_start_month into v_fy_start from public.number_series ns where ns.code = 'GS';
  v_fy_start := coalesce(v_fy_start, 4);
  new.gate_entry_fy := extract(year from new.gate_entry_date)::smallint
    - case when extract(month from new.gate_entry_date)::smallint < v_fy_start then 1 else 0 end;
  return new;
end
$$;
revoke all on function rms_private.goods_slips_gate_entry_guard() from public, anon, authenticated;

create trigger goods_slips_gate_entry_guard
  before insert or update of return_type_code, gate_entry_date, gate_entry_fy on public.goods_slips
  for each row execute function rms_private.goods_slips_gate_entry_guard();

-- ===========================================================================
-- 2. gs_gate_documents (AMD-04)
-- ===========================================================================
create table public.gs_gate_documents (
  id               uuid primary key default gen_random_uuid(),
  gs_id            uuid not null references public.goods_slips (id) on delete cascade,
  doc_type_code    text not null check (doc_type_code ~ '^[A-Z][A-Z0-9_]*$' and doc_type_code <> 'NO_DOCUMENT'),
  doc_type_label   text not null check (btrim(doc_type_label) <> ''),   -- G-18 label snapshot
  doc_no           text,
  doc_date         date,
  remarks          text,
  -- Where the row was captured: the gate (Phase 2) or carton opening (Phase 3, AMD-04).
  source_step      text not null default 'S1_GATE' check (source_step in ('S1_GATE', 'S1_UNBOX')),
  sort_order       integer not null default 0,
  -- AMD-05: set once Accounts has been alerted for this row; never alerted twice.
  accounts_alerted_at timestamptz,
  created_at       timestamptz not null default now(),
  created_by       uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at       timestamptz not null default now(),
  constraint gs_gate_documents_id_gs_key unique (id, gs_id),
  -- DD r5–r7 (unchanged rule, now per row): Invoice / Debit Note / Delivery Challan → number + date
  constraint gs_gate_documents_formal_fields check (
    doc_type_code not in ('INVOICE', 'DEBIT_NOTE', 'DELIVERY_CHALLAN')
    or (coalesce(btrim(doc_no), '') <> '' and doc_date is not null)),
  -- DD r8: Handwritten Slip / Party Note → slip details / remarks
  constraint gs_gate_documents_slip_fields check (
    doc_type_code <> 'HANDWRITTEN_SLIP' or coalesce(btrim(remarks), '') <> '')
);
create index gs_gate_documents_gs_idx on public.gs_gate_documents (gs_id, sort_order);
create index gs_gate_documents_doc_no_idx on public.gs_gate_documents (lower(doc_no)) where doc_no is not null;
create index gs_gate_documents_created_by_idx on public.gs_gate_documents (created_by);
comment on table public.gs_gate_documents is
  'AMD-04: documents received with a consignment (many per GS), each with its own files (attachments kind GATE_DOC).';

-- Migrate the single gate document of existing GS (before the guard trigger exists, so GS that
-- already left the gate are migrated too). NO_DOCUMENT stays the missing_documentation flag.
insert into public.gs_gate_documents (gs_id, doc_type_code, doc_type_label, doc_no, doc_date, remarks,
                                      source_step, sort_order, accounts_alerted_at, created_at, created_by)
select g.id, g.gate_document_code,
       coalesce((select oi.label from public.option_items oi
                   join public.option_sets os on os.id = oi.option_set_id
                  where os.code = 'GATE_DOCUMENT' and oi.code = g.gate_document_code),
                g.gate_document_code),
       g.gate_doc_no, g.gate_doc_date, g.gate_doc_remarks, 'S1_GATE', 1,
       -- Requirement A already alerted Accounts for these at creation; never alert them again.
       case when g.gate_document_code in ('INVOICE', 'DEBIT_NOTE') then g.created_at end,
       g.created_at, g.created_by
  from public.goods_slips g
 where g.gate_document_code is not null and g.gate_document_code <> 'NO_DOCUMENT';

create or replace function rms_private.gs_gate_documents_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_row     public.gs_gate_documents;
  v_status  text;
  v_missing boolean;
begin
  v_row := case when tg_op = 'DELETE' then old else new end;
  select g.status, g.missing_documentation into v_status, v_missing
    from public.goods_slips g where g.id = v_row.gs_id;
  if v_status is null then
    return case when tg_op = 'DELETE' then old else new end;   -- cascade from a deleted GS
  end if;

  if tg_op = 'UPDATE' and (new.gs_id <> old.gs_id or new.source_step <> old.source_step) then
    raise exception 'AMD-04: a gate document cannot move to another GS or step' using errcode = '23514';
  end if;
  -- Gate rows are captured and corrected only while the GS is at the gate (as gate details are).
  if v_row.source_step = 'S1_GATE' and v_status <> 'GATE_CREATED' then
    raise exception 'AMD-04: gate documents can only change while the GS is at the gate (status %)', v_status
      using errcode = '23514';
  end if;
  if v_row.source_step = 'S1_UNBOX' and v_status <> 'UNBOXING' then
    raise exception 'AMD-04: carton-opening documents can only change while the GS is UNBOXING (status %)', v_status
      using errcode = '23514';
  end if;

  if tg_op <> 'DELETE' then
    -- DEC-03 / BR-03: "No document" is a GS-level flag and excludes document rows.
    if v_missing then
      raise exception 'AMD-04: a GS flagged "no document" cannot have document rows' using errcode = '23514';
    end if;
    if tg_op = 'INSERT' or new.doc_type_code is distinct from old.doc_type_code then
      if not exists (
        select 1 from public.option_items oi
          join public.option_sets os on os.id = oi.option_set_id
         where os.code = 'GATE_DOCUMENT' and oi.code = new.doc_type_code and oi.is_active
      ) then
        raise exception 'AMD-04: unknown or inactive gate document type %', new.doc_type_code
          using errcode = '23514';
      end if;
    end if;
    if new.doc_date is not null and (tg_op = 'INSERT' or new.doc_date is distinct from old.doc_date)
       and new.doc_date > rms_private.business_today() then
      raise exception 'AMD-04: the document date % is in the future', new.doc_date using errcode = '23514';
    end if;
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end
$$;
revoke all on function rms_private.gs_gate_documents_guard() from public, anon, authenticated;

create trigger gs_gate_documents_guard
  before insert or update or delete on public.gs_gate_documents
  for each row execute function rms_private.gs_gate_documents_guard();

-- The reverse direction: flagging "no document" while document rows exist.
create or replace function rms_private.goods_slips_no_document_exclusive()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.missing_documentation and not coalesce(old.missing_documentation, false)
     and exists (select 1 from public.gs_gate_documents d where d.gs_id = new.id) then
    raise exception 'AMD-04: remove the document rows before flagging the GS as "no document"'
      using errcode = '23514';
  end if;
  return new;
end
$$;
revoke all on function rms_private.goods_slips_no_document_exclusive() from public, anon, authenticated;

create trigger goods_slips_no_document_exclusive
  before update of missing_documentation on public.goods_slips
  for each row execute function rms_private.goods_slips_no_document_exclusive();

alter table public.gs_gate_documents enable row level security;
revoke all on public.gs_gate_documents from anon, authenticated;
grant select, insert, update, delete on public.gs_gate_documents to rms_api;
select rms_private.attach_standard_triggers('public.gs_gate_documents');

-- ===========================================================================
-- 2b. Gate document files: attachments kind GATE_DOC linked to one document row
-- ===========================================================================
alter table public.attachments add column gate_document_id uuid;
alter table public.attachments
  add constraint attachments_gate_document_fkey
  foreign key (gate_document_id, gs_id) references public.gs_gate_documents (id, gs_id)
  on delete cascade;
create index attachments_gate_document_idx on public.attachments (gate_document_id)
  where gate_document_id is not null;
comment on column public.attachments.box_no is
  'Carton number (AMD-03; the column keeps its original name).';

do $$
declare
  c record;
begin
  for c in
    select conname from pg_constraint
     where conrelid = 'public.attachments'::regclass and contype = 'c'
       and (pg_get_constraintdef(oid) like '%''NOTIFICATION_PROOF''%''OTHER''%'
            and pg_get_constraintdef(oid) not like '%mime_type%')
  loop
    execute format('alter table public.attachments drop constraint %I', c.conname);
  end loop;
end
$$;

alter table public.attachments drop constraint attachments_mime_for_kind;
alter table public.attachments
  add constraint attachments_kind_check check (
    kind in ('UNBOXING_VIDEO', 'DOC_PHOTO', 'PARCEL_PHOTO', 'NOTIFICATION_PROOF', 'GATE_DOC', 'OTHER')),
  add constraint attachments_mime_for_kind check (
    (kind = 'UNBOXING_VIDEO' and mime_type in ('video/mp4', 'video/quicktime'))
    or (kind in ('DOC_PHOTO', 'GATE_DOC') and mime_type in ('image/jpeg', 'image/png', 'image/heic', 'image/heif', 'application/pdf'))
    or (kind = 'PARCEL_PHOTO' and mime_type in ('image/jpeg', 'image/png', 'image/heic', 'image/heif'))
    or kind in ('NOTIFICATION_PROOF', 'OTHER')),
  -- AMD-04: a gate document file always belongs to exactly one document row of the same GS.
  add constraint attachments_gate_document_link check ((kind = 'GATE_DOC') = (gate_document_id is not null));

-- Same body as 20261103000200, plus GATE_DOC: uploaded while the GS is at the gate (or being
-- unboxed, if Aman already started), deleted only while it is still at the gate.
create or replace function rms_private.attachments_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_gs_status text;
  v_row       public.attachments;
begin
  v_row := case when tg_op = 'DELETE' then old else new end;
  select status into v_gs_status from public.goods_slips where id = v_row.gs_id;

  if tg_op = 'UPDATE' then
    if new.gs_id <> old.gs_id or new.kind <> old.kind or new.bucket <> old.bucket
       or new.object_path <> old.object_path
       or new.gate_document_id is distinct from old.gate_document_id then
      raise exception 'An attachment''s GS, kind, bucket, object path and document cannot change'
        using errcode = '23514';
    end if;
    if old.status = 'CONFIRMED' and new.status <> 'CONFIRMED' then
      raise exception 'A confirmed attachment cannot return to %', new.status using errcode = '23514';
    end if;
  end if;

  if v_row.kind in ('UNBOXING_VIDEO', 'DOC_PHOTO', 'PARCEL_PHOTO') then
    -- Step-2 evidence is captured only while the GS is being unboxed.
    if (tg_op = 'INSERT' or (tg_op = 'UPDATE' and new.status = 'CONFIRMED' and old.status <> 'CONFIRMED'))
       and v_gs_status is distinct from 'UNBOXING' then
      raise exception 'Unboxing evidence can only be added while the GS is UNBOXING (status %)', v_gs_status
        using errcode = '23514';
    end if;
    -- G-02: confirmed evidence stays once the GS has left UNBOXING (a cascade from a deleted GS
    -- finds no GS row and is allowed).
    if tg_op = 'DELETE' and old.status = 'CONFIRMED' and v_gs_status is not null
       and v_gs_status not in ('GATE_CREATED', 'UNBOXING') then
      raise exception 'G-02: confirmed unboxing evidence cannot be deleted after unboxing (status %)', v_gs_status
        using errcode = '23514';
    end if;
  elsif v_row.kind = 'GATE_DOC' then
    if (tg_op = 'INSERT' or (tg_op = 'UPDATE' and new.status = 'CONFIRMED' and old.status <> 'CONFIRMED'))
       and v_gs_status not in ('GATE_CREATED', 'UNBOXING') then
      raise exception 'AMD-04: gate document files can only be added at the gate (status %)', v_gs_status
        using errcode = '23514';
    end if;
    if tg_op = 'DELETE' and old.status = 'CONFIRMED' and v_gs_status is not null
       and v_gs_status <> 'GATE_CREATED' then
      raise exception 'AMD-04: a confirmed gate document file cannot be deleted after the gate (status %)', v_gs_status
        using errcode = '23514';
    end if;
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end
$$;
revoke all on function rms_private.attachments_guard() from public, anon, authenticated;

-- ===========================================================================
-- 3. Settings (DEC-38, AMD-05) — configuration only, never a guard switch
-- ===========================================================================
insert into public.system_settings (key, value, category, description, source_ref) values
  ('gate.max_backdate_days', 'null', 'provisional',
   'Maximum number of days a Gate Entry Date may lie in the past. null = unlimited (dates are never later than today).',
   'DEC-38'),
  ('gate.accounts_alert_doc_types', '["INVOICE", "DEBIT_NOTE"]', 'notifications',
   'GATE_DOCUMENT codes that alert the ACCOUNTS role as soon as a document row of that type is saved (GST input check).',
   'AMD-05')
on conflict (key) do nothing;

alter table public.system_settings
  add constraint system_settings_gate_max_backdate_days_check
  check (key <> 'gate.max_backdate_days'
         or value = 'null'::jsonb
         or (jsonb_typeof(value) = 'number' and (value #>> '{}')::numeric >= 0
             and (value #>> '{}')::numeric = trunc((value #>> '{}')::numeric))),
  add constraint system_settings_gate_accounts_alert_doc_types_check
  check (key <> 'gate.accounts_alert_doc_types'
         or (jsonb_typeof(value) = 'array'
             and not jsonb_path_exists(value, '$[*] ? (@.type() != "string")')));

-- ===========================================================================
-- 4. G-02 per carton (AMD-03). Same body as 20261103000200, the video check is per carton.
-- ===========================================================================
create or replace function rms_private.goods_slips_g02_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_missing integer[];
begin
  if new.status is not distinct from old.status or new.status = 'CANCELLED' then
    return new;
  end if;
  if old.status = 'GATE_CREATED' and new.status <> 'UNBOXING' then
    raise exception 'G-02: a GS must pass through UNBOXING before %', new.status using errcode = '23514';
  end if;
  if old.status <> 'UNBOXING' then
    return new;
  end if;

  if not exists (select 1 from public.attachments
                  where gs_id = new.id and kind = 'UNBOXING_VIDEO' and status = 'CONFIRMED') then
    raise exception 'G-02: a confirmed unboxing video is required before leaving UNBOXING'
      using errcode = '23514';
  end if;
  -- AMD-03: one confirmed video per carton (1..carton_count). A single-carton GS accepts a video
  -- without a carton number.
  if new.carton_count > 1 then
    select array_agg(n order by n) into v_missing
      from generate_series(1, new.carton_count) n
     where not exists (select 1 from public.attachments a
                        where a.gs_id = new.id and a.kind = 'UNBOXING_VIDEO'
                          and a.status = 'CONFIRMED' and a.box_no = n);
    if v_missing is not null then
      raise exception 'G-02: a confirmed unboxing video is required for every carton (missing carton %)',
        array_to_string(v_missing, ', ')
        using errcode = '23514';
    end if;
  end if;
  if exists (select 1 from public.attachments a
              where a.gs_id = new.id and a.kind = 'DOC_PHOTO' and a.status = 'CONFIRMED'
                and not exists (select 1 from public.gs_documents d where d.attachment_id = a.id)) then
    raise exception 'G-02: every confirmed document photo must be classified before leaving UNBOXING'
      using errcode = '23514';
  end if;
  if new.missing_documentation then
    -- DEC-03: parcel photo + remark + approved Missing Document Exception.
    if not exists (select 1 from public.missing_doc_exceptions e
                     join public.attachments a on a.id = e.parcel_attachment_id
                    where e.gs_id = new.id and e.status = 'APPROVED' and a.status = 'CONFIRMED') then
      raise exception 'G-02: a GS with missing documentation needs an approved Missing Document Exception'
        using errcode = '23514';
    end if;
  elsif not exists (select 1 from public.attachments a
                      join public.gs_documents d on d.attachment_id = a.id
                     where a.gs_id = new.id and a.kind = 'DOC_PHOTO' and a.status = 'CONFIRMED') then
    raise exception 'G-02: a confirmed, classified document photo is required before leaving UNBOXING'
      using errcode = '23514';
  end if;
  return new;
end
$$;
revoke all on function rms_private.goods_slips_g02_guard() from public, anon, authenticated;
