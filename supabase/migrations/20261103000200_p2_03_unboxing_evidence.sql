-- P2-03 · Step-2 Unboxing evidence: video/photo upload, document classification, Accounts alert
-- (master plan §2.2 Step-2, §3.2 DD r11–r16, BR-03..BR-06, G-02, G-17, DEC-03, DEC-04, DEC-05,
-- §8.8, §9.6). Fixes forward on 20261102000900 (P2-01) and 20261103000100 (P2-02).
--
-- 1. attachments: bucket / MIME per kind, server path under gs/{gs_id}/{kind}/, identity immutable,
--    evidence uploads only while the GS is UNBOXING, confirmed evidence never deleted after it.
-- 2. gs_documents: one classification per DOC_PHOTO, codes from RECEIVED_DOC_CLASSIFICATION,
--    conditional fields per DD r12–r15 (BR-05), form version + label snapshot (G-18), Accounts
--    acknowledgement (BR-06 / DEC-05), frozen once the GS leaves UNBOXING.
-- 3. missing_doc_exceptions (DEC-03): parcel photo + mandatory remark, approved by a holder of
--    unboxing.approve (Replacement Manager by default).
-- 4. G-02 on goods_slips: a GS cannot leave UNBOXING (nor skip it) without ≥1 confirmed unboxing
--    video and ≥1 confirmed, classified document photo — or, for missing_documentation, an
--    approved Missing Document Exception. Every confirmed document photo must be classified.
-- 5. G-17: audit_log accepts action 'ACCESS' (signed download URL issuance is audited).

-- ===========================================================================
-- 1. attachments
-- ===========================================================================
alter table public.attachments
  add column updated_at    timestamptz not null default now(),
  add column confirmed_by  uuid references public.profiles (id) on delete set null,
  -- §9.6 "heic → accept and flag": browsers cannot preview HEIC, the UI shows a notice instead.
  add column preview_unsupported boolean generated always as (mime_type in ('image/heic', 'image/heif')) stored;

create index attachments_confirmed_by_idx on public.attachments (confirmed_by);
create index attachments_pending_created_idx on public.attachments (created_at) where status = 'PENDING_UPLOAD';
create index attachments_gs_kind_status_idx on public.attachments (gs_id, kind, status);

alter table public.attachments
  -- §8.8: videos in rms-videos, photos / PDFs / proofs in rms-documents (both private).
  add constraint attachments_bucket_for_kind check (
    (kind = 'UNBOXING_VIDEO' and bucket = 'rms-videos')
    or (kind <> 'UNBOXING_VIDEO' and bucket = 'rms-documents')),
  -- §9.6 allow-list: video mp4 / mov; document photo jpeg / png / heic / pdf; parcel photo images.
  add constraint attachments_mime_for_kind check (
    (kind = 'UNBOXING_VIDEO' and mime_type in ('video/mp4', 'video/quicktime'))
    or (kind = 'DOC_PHOTO' and mime_type in ('image/jpeg', 'image/png', 'image/heic', 'image/heif', 'application/pdf'))
    or (kind = 'PARCEL_PHOTO' and mime_type in ('image/jpeg', 'image/png', 'image/heic', 'image/heif'))
    or kind in ('NOTIFICATION_PROOF', 'OTHER')),
  -- §8.8: object paths are server generated gs/{gs_id}/{kind}/{uuid}.{ext}, never client names.
  add constraint attachments_path_under_gs check (
    object_path ~ ('^gs/' || gs_id::text || '/' || lower(kind)
                   || '/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.[a-z0-9]{1,8}$')),
  add constraint attachments_confirmed_fields check (status <> 'CONFIRMED' or confirmed_at is not null);

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
       or new.object_path <> old.object_path then
      raise exception 'An attachment''s GS, kind, bucket and object path cannot change'
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
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end
$$;
revoke all on function rms_private.attachments_guard() from public, anon, authenticated;

create trigger attachments_guard
  before insert or update or delete on public.attachments
  for each row execute function rms_private.attachments_guard();

-- attach_standard_triggers adds set_updated_at now that the column exists (audit already attached).
select rms_private.attach_standard_triggers('public.attachments');

-- ===========================================================================
-- 2. gs_documents
-- ===========================================================================
alter table public.gs_documents drop constraint gs_documents_attachment_id_fkey;

alter table public.gs_documents
  alter column attachment_id set not null,
  add constraint gs_documents_attachment_id_fkey
    foreign key (attachment_id) references public.attachments (id) on delete cascade,
  add constraint gs_documents_attachment_unique unique (attachment_id),
  add column items_verified            boolean,
  add column remarks                   text,
  add column form_version_id           uuid references public.form_versions (id) on delete restrict,
  add column labels_snapshot           jsonb not null default '{}'::jsonb,
  add column updated_at                timestamptz not null default now(),
  add column accounts_acknowledged_by  uuid references public.profiles (id) on delete restrict,
  add column accounts_acknowledged_at  timestamptz;

create index gs_documents_form_version_idx on public.gs_documents (form_version_id);
create index gs_documents_ack_by_idx on public.gs_documents (accounts_acknowledged_by);
create index gs_documents_unacknowledged_idx on public.gs_documents (gs_id, classification_code)
  where accounts_acknowledged_at is null;

alter table public.gs_documents
  -- DD r12 / BR-05: Invoice → doc no + date, buyer / seller GSTIN, item details verified.
  add constraint gs_documents_invoice_fields check (
    classification_code <> 'INVOICE'
    or (coalesce(btrim(doc_no), '') <> '' and doc_date is not null
        and coalesce(btrim(buyer_gstin), '') <> '' and coalesce(btrim(seller_gstin), '') <> ''
        and items_verified is true)),
  -- DD r13 / BR-05: Debit Note → number + amount.
  add constraint gs_documents_debit_note_fields check (
    classification_code <> 'DEBIT_NOTE' or (coalesce(btrim(doc_no), '') <> '' and amount is not null)),
  -- DD r14 / BR-05: Delivery Challan → quantity matched against parcel contents (Y/N).
  add constraint gs_documents_challan_fields check (
    classification_code <> 'DELIVERY_CHALLAN' or qty_matched is not null),
  -- DD r15 / BR-05: Handwritten Slip / Party Note → party claim / complaint.
  add constraint gs_documents_slip_fields check (
    classification_code <> 'HANDWRITTEN_SLIP' or coalesce(btrim(party_claim_text), '') <> ''),
  add constraint gs_documents_ack_pair check (
    (accounts_acknowledged_by is null) = (accounts_acknowledged_at is null));

create or replace function rms_private.gs_documents_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_row        public.gs_documents;
  v_gs_status  text;
  v_att        record;
begin
  v_row := case when tg_op = 'DELETE' then old else new end;
  select status into v_gs_status from public.goods_slips where id = v_row.gs_id;

  if tg_op in ('INSERT', 'UPDATE') then
    -- Codes come from the configured option set (labels editable, codes immutable).
    if tg_op = 'INSERT' or new.classification_code is distinct from old.classification_code then
      if not exists (
        select 1 from public.option_items oi
          join public.option_sets os on os.id = oi.option_set_id
         where os.code = 'RECEIVED_DOC_CLASSIFICATION' and oi.code = new.classification_code
           and oi.is_active
      ) then
        raise exception 'Unknown or inactive document classification %', new.classification_code
          using errcode = '23514';
      end if;
    end if;
    -- A classification links one confirmed DOC_PHOTO of the same GS (DD r16).
    select a.gs_id, a.kind, a.status into v_att from public.attachments a where a.id = new.attachment_id;
    if v_att.gs_id is distinct from new.gs_id or v_att.kind is distinct from 'DOC_PHOTO'
       or v_att.status is distinct from 'CONFIRMED' then
      raise exception 'A document classification must link a confirmed DOC_PHOTO of the same GS'
        using errcode = '23514';
    end if;
  end if;

  if v_gs_status = 'UNBOXING' then
    if tg_op = 'UPDATE' and old.accounts_acknowledged_at is not null then
      raise exception 'An acknowledged document cannot change' using errcode = '23514';
    end if;
    return case when tg_op = 'DELETE' then old else new end;
  end if;
  if tg_op = 'DELETE' and v_gs_status is null then
    return old;  -- cascade from a deleted GS
  end if;

  -- After Step-2 the classification is frozen; only the Accounts acknowledgement may be set, once.
  if tg_op = 'UPDATE'
     and (to_jsonb(new) - array['accounts_acknowledged_by', 'accounts_acknowledged_at', 'updated_at'])
         = (to_jsonb(old) - array['accounts_acknowledged_by', 'accounts_acknowledged_at', 'updated_at'])
     and old.accounts_acknowledged_at is null then
    return new;
  end if;
  raise exception 'Document classifications are frozen once the GS has left UNBOXING (status %)', v_gs_status
    using errcode = '23514';
end
$$;
revoke all on function rms_private.gs_documents_guard() from public, anon, authenticated;

create trigger gs_documents_guard
  before insert or update or delete on public.gs_documents
  for each row execute function rms_private.gs_documents_guard();

select rms_private.attach_standard_triggers('public.gs_documents');

-- ===========================================================================
-- 3. Missing Document Exception (DEC-03)
-- ===========================================================================
create table public.missing_doc_exceptions (
  id                    uuid primary key default gen_random_uuid(),
  gs_id                 uuid not null references public.goods_slips (id) on delete cascade,
  parcel_attachment_id  uuid not null references public.attachments (id) on delete restrict,
  remark                text not null check (btrim(remark) <> ''),
  status                text not null default 'REQUESTED' check (status in ('REQUESTED', 'APPROVED', 'REJECTED')),
  requested_by          uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  requested_at          timestamptz not null default now(),
  decided_by            uuid references public.profiles (id) on delete restrict,
  decided_at            timestamptz,
  decision_remarks      text,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  constraint missing_doc_exceptions_decision_fields check (
    status = 'REQUESTED' or (decided_by is not null and decided_at is not null)),
  constraint missing_doc_exceptions_reject_reason check (
    status <> 'REJECTED' or coalesce(btrim(decision_remarks), '') <> '')
);

create index missing_doc_exceptions_gs_idx on public.missing_doc_exceptions (gs_id);
create index missing_doc_exceptions_parcel_idx on public.missing_doc_exceptions (parcel_attachment_id);
create index missing_doc_exceptions_requested_by_idx on public.missing_doc_exceptions (requested_by);
create index missing_doc_exceptions_decided_by_idx on public.missing_doc_exceptions (decided_by);
create index missing_doc_exceptions_open_idx on public.missing_doc_exceptions (requested_at desc)
  where status = 'REQUESTED';
-- At most one live (requested or approved) exception per GS; rejected ones stay as history.
create unique index missing_doc_exceptions_one_live on public.missing_doc_exceptions (gs_id)
  where status in ('REQUESTED', 'APPROVED');

create or replace function rms_private.missing_doc_exceptions_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_gs   record;
  v_att  record;
begin
  select status, missing_documentation into v_gs from public.goods_slips where id = new.gs_id;
  if tg_op = 'INSERT' then
    if new.status <> 'REQUESTED' then
      raise exception 'A Missing Document Exception starts as REQUESTED' using errcode = '23514';
    end if;
    if v_gs.missing_documentation is not true then
      raise exception 'A Missing Document Exception applies only to a GS flagged missing documentation (DEC-03)'
        using errcode = '23514';
    end if;
    if v_gs.status is distinct from 'UNBOXING' then
      raise exception 'A Missing Document Exception can only be requested while the GS is UNBOXING'
        using errcode = '23514';
    end if;
    select gs_id, kind, status into v_att from public.attachments where id = new.parcel_attachment_id;
    if v_att.gs_id is distinct from new.gs_id or v_att.kind is distinct from 'PARCEL_PHOTO'
       or v_att.status is distinct from 'CONFIRMED' then
      raise exception 'The exception must reference a confirmed PARCEL_PHOTO of the same GS (DEC-03)'
        using errcode = '23514';
    end if;
    return new;
  end if;

  -- UPDATE: only REQUESTED → APPROVED / REJECTED, once; the request itself never changes.
  if old.status <> 'REQUESTED' then
    raise exception 'A decided Missing Document Exception cannot change' using errcode = '23514';
  end if;
  if new.gs_id <> old.gs_id or new.parcel_attachment_id <> old.parcel_attachment_id
     or new.remark <> old.remark or new.requested_by is distinct from old.requested_by
     or new.requested_at <> old.requested_at then
    raise exception 'The exception request cannot be edited' using errcode = '23514';
  end if;
  if new.status <> 'REQUESTED' then
    if v_gs.status is distinct from 'UNBOXING' then
      raise exception 'A Missing Document Exception can only be decided while the GS is UNBOXING'
        using errcode = '23514';
    end if;
    -- G-02 "authorised exception": the decider holds unboxing.approve (role grant or live grant
    -- override, no live deny) or is an active Super Admin.
    if not exists (
      select 1 from public.profiles p
       where p.id = new.decided_by and p.is_active
         and (p.is_super_admin
              or ((exists (select 1 from public.user_roles ur
                             join public.role_permissions rp on rp.role_id = ur.role_id
                             join public.permissions pm on pm.id = rp.permission_id
                            where ur.user_id = p.id and pm.module_code = 'unboxing' and pm.action = 'approve')
                   or exists (select 1 from public.user_permission_overrides o
                                join public.permissions pm on pm.id = o.permission_id
                               where o.user_id = p.id and o.effect = 'grant'
                                 and pm.module_code = 'unboxing' and pm.action = 'approve'
                                 and (o.expires_at is null or o.expires_at > now())))
                  and not exists (select 1 from public.user_permission_overrides o
                                    join public.permissions pm on pm.id = o.permission_id
                                   where o.user_id = p.id and o.effect = 'deny'
                                     and pm.module_code = 'unboxing' and pm.action = 'approve'
                                     and (o.expires_at is null or o.expires_at > now()))))
    ) then
      raise exception 'G-02: the Missing Document Exception must be decided by a user holding unboxing.approve'
        using errcode = '42501';
    end if;
  end if;
  return new;
end
$$;
revoke all on function rms_private.missing_doc_exceptions_guard() from public, anon, authenticated;

create trigger missing_doc_exceptions_guard
  before insert or update on public.missing_doc_exceptions
  for each row execute function rms_private.missing_doc_exceptions_guard();

alter table public.missing_doc_exceptions enable row level security;
select rms_private.attach_standard_triggers('public.missing_doc_exceptions');
grant select, insert, update on public.missing_doc_exceptions to rms_api;

-- ===========================================================================
-- 4. G-02 on goods_slips
-- ===========================================================================
create or replace function rms_private.goods_slips_g02_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
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

create trigger goods_slips_g02_guard
  before update of status on public.goods_slips
  for each row execute function rms_private.goods_slips_g02_guard();

-- ===========================================================================
-- 5. G-17: audited read access (signed download URLs)
-- ===========================================================================
do $$
declare
  c record;
begin
  for c in
    select conname from pg_constraint
     where conrelid = 'public.audit_log'::regclass and contype = 'c'
       and pg_get_constraintdef(oid) like '%action%'
  loop
    execute format('alter table public.audit_log drop constraint %I', c.conname);
  end loop;
end
$$;
alter table public.audit_log
  add constraint audit_log_action_check check (action in ('INSERT', 'UPDATE', 'DELETE', 'ACCESS'));
