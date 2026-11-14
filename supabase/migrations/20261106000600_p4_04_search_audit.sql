-- Migration: 20261106000600_p4_04_search_audit.sql
-- Prompt: P4-04 Global search, advanced filters, audit trail & activity history UI
-- (master plan §8.7, BR-40, G-17).
--
-- Corrected 2026-11-14 (first `supabase db push` to Supabase Cloud): the operator class is written
-- `extensions.gin_trgm_ops`. pg_trgm lives in schema `extensions` (20261102000100), and the Cloud
-- push session's search_path does not include it, so the unqualified name failed with SQLSTATE 42704.
-- Same object, same result. Local databases that already applied this version are unaffected (the
-- CLI tracks versions, not file contents). Guarded by backend/tests/unit/test_migration_extension_refs.py.

-- ===========================================================================
-- 1. pg_trgm indexes for high-performance global search (<300ms on 50k GS)
-- ===========================================================================
create extension if not exists pg_trgm with schema extensions;  -- already created in 20261102000100

-- Goods Slips (docket, vehicle, transporter, rep, gate_doc_no live directly on goods_slips)
create index if not exists goods_slips_gs_no_trgm_idx
  on public.goods_slips using gin (gs_no extensions.gin_trgm_ops);
create index if not exists goods_slips_docket_no_trgm_idx
  on public.goods_slips using gin (docket_no extensions.gin_trgm_ops) where docket_no is not null;
create index if not exists goods_slips_vehicle_no_trgm_idx
  on public.goods_slips using gin (vehicle_no extensions.gin_trgm_ops) where vehicle_no is not null;
create index if not exists goods_slips_transporter_trgm_idx
  on public.goods_slips using gin (transporter_name extensions.gin_trgm_ops) where transporter_name is not null;
create index if not exists goods_slips_rep_name_trgm_idx
  on public.goods_slips using gin (rep_name extensions.gin_trgm_ops) where rep_name is not null;
create index if not exists goods_slips_gate_doc_no_trgm_idx
  on public.goods_slips using gin (gate_doc_no extensions.gin_trgm_ops) where gate_doc_no is not null;

-- Parties
create index if not exists parties_name_trgm_idx
  on public.parties using gin (name extensions.gin_trgm_ops);
create index if not exists parties_gstin_trgm_idx
  on public.parties using gin (gstin extensions.gin_trgm_ops) where gstin is not null;
create index if not exists parties_contact_name_trgm_idx
  on public.parties using gin (contact_name extensions.gin_trgm_ops) where contact_name is not null;
create index if not exists parties_phone_trgm_idx
  on public.parties using gin (phone extensions.gin_trgm_ops) where phone is not null;

-- GS Documents
create index if not exists gs_documents_doc_no_trgm_idx
  on public.gs_documents using gin (doc_no extensions.gin_trgm_ops) where doc_no is not null;

-- Credit Notes
create index if not exists credit_notes_cn_no_trgm_idx
  on public.credit_notes using gin (cn_no extensions.gin_trgm_ops) where cn_no is not null;
create index if not exists credit_notes_jv_no_trgm_idx
  on public.credit_notes using gin (jv_no extensions.gin_trgm_ops) where jv_no is not null;
create index if not exists credit_notes_party_doc_no_trgm_idx
  on public.credit_notes using gin (party_doc_no extensions.gin_trgm_ops) where party_doc_no is not null;

-- Custody Transfers
create index if not exists custody_transfers_transfer_no_trgm_idx
  on public.custody_transfers using gin (transfer_no extensions.gin_trgm_ops);

-- Technician Batches
create index if not exists technician_batches_batch_no_trgm_idx
  on public.technician_batches using gin (batch_no extensions.gin_trgm_ops);

-- Store Issues
create index if not exists store_issues_issue_no_trgm_idx
  on public.store_issues using gin (issue_no extensions.gin_trgm_ops);

-- Replacement Dispatches
create index if not exists replacement_dispatches_dispatch_no_trgm_idx
  on public.replacement_dispatches using gin (dispatch_no extensions.gin_trgm_ops);
create index if not exists replacement_dispatches_docket_no_trgm_idx
  on public.replacement_dispatches using gin (docket_no extensions.gin_trgm_ops) where docket_no is not null;
create index if not exists replacement_dispatches_vehicle_no_trgm_idx
  on public.replacement_dispatches using gin (vehicle_no extensions.gin_trgm_ops) where vehicle_no is not null;
create index if not exists replacement_dispatches_ref_doc_no_trgm_idx
  on public.replacement_dispatches using gin (ref_doc_no extensions.gin_trgm_ops) where ref_doc_no is not null;

-- Containers & Partitions
create index if not exists storage_containers_barcode_trgm_idx
  on public.storage_containers using gin (barcode extensions.gin_trgm_ops) where barcode is not null;
create index if not exists storage_containers_code_trgm_idx
  on public.storage_containers using gin (code extensions.gin_trgm_ops);
create index if not exists storage_containers_name_trgm_idx
  on public.storage_containers using gin (name extensions.gin_trgm_ops);

-- Dismantling Batches
create index if not exists dismantle_batches_batch_no_trgm_idx
  on public.dismantle_batches using gin (batch_no extensions.gin_trgm_ops);

-- ===========================================================================
-- 2. Audit log index hardening (for instant timeline & audit explorer queries)
-- ===========================================================================
create index if not exists audit_log_table_row_idx
  on public.audit_log (table_name, row_id);
create index if not exists audit_log_actor_at_idx
  on public.audit_log (actor_id, at desc);
create index if not exists audit_log_request_id_idx
  on public.audit_log (request_id) where request_id is not null;
create index if not exists audit_log_at_idx
  on public.audit_log (at desc);

-- ===========================================================================
-- 3. User Activity Table (Sign-in, session, print & export tracking)
-- ===========================================================================
create table if not exists public.user_activity (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references public.profiles(id) on delete cascade,
  session_id     text,
  activity_type  text not null check (activity_type in (
                   'SIGN_IN', 'TOKEN_REFRESH', 'PAGE_VIEW', 'SEARCH', 'EXPORT', 'PRINT', 'API_CALL'
                 )),
  ip_address     text,
  user_agent     text,
  entity_type    text,
  entity_id      uuid,
  details        jsonb not null default '{}'::jsonb check (jsonb_typeof(details) = 'object'),
  request_id     text default rms_private.current_request_id(),
  created_at     timestamptz not null default now()
);

create index if not exists user_activity_user_idx
  on public.user_activity (user_id, created_at desc);
create index if not exists user_activity_type_idx
  on public.user_activity (activity_type, created_at desc);
create index if not exists user_activity_entity_idx
  on public.user_activity (entity_type, entity_id) where entity_id is not null;

comment on table public.user_activity is
  'P4-04 login and session activity ledger. Append-only, immutable.';

-- Guard trigger: user_activity is append-only
create or replace function rms_private.user_activity_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'user activity records cannot be deleted' using errcode = '42501';
  end if;
  if tg_op = 'UPDATE' then
    raise exception 'user activity records are immutable' using errcode = '42501';
  end if;
  return new;
end;
$$;
revoke all on function rms_private.user_activity_guard() from public, anon, authenticated;

drop trigger if exists user_activity_guard on public.user_activity;
create trigger user_activity_guard
  before update or delete on public.user_activity
  for each row execute function rms_private.user_activity_guard();

-- ===========================================================================
-- 4. Saved Views Table (per-user customizable filter & column presets)
-- ===========================================================================
create table if not exists public.saved_views (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references public.profiles(id) on delete cascade,
  view_code   text not null check (btrim(view_code) <> ''),
  name        text not null check (btrim(name) <> '' and length(name) <= 120),
  filters     jsonb not null default '[]'::jsonb check (jsonb_typeof(filters) = 'array'),
  columns     text[] not null default '{}',
  sort_by     text,
  sort_dir    text check (sort_dir is null or sort_dir in ('asc', 'desc')),
  is_default  boolean not null default false,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (user_id, view_code, name)
);

create index if not exists saved_views_user_view_idx
  on public.saved_views (user_id, view_code);

comment on table public.saved_views is
  'P4-04 saved view configurations (filters, sort, column visibility) per user and view code.';

-- Trigger to maintain at most one is_default=true per (user_id, view_code)
create or replace function rms_private.saved_views_default_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.is_default then
    update public.saved_views
       set is_default = false
     where user_id = new.user_id
       and view_code = new.view_code
       and id <> coalesce(new.id, '00000000-0000-0000-0000-000000000000'::uuid);
  end if;
  return new;
end;
$$;
revoke all on function rms_private.saved_views_default_guard() from public, anon, authenticated;

drop trigger if exists saved_views_default_guard on public.saved_views;
create trigger saved_views_default_guard
  before insert or update of is_default on public.saved_views
  for each row when (new.is_default = true)
  execute function rms_private.saved_views_default_guard();

-- set_updated_at trigger for saved_views
drop trigger if exists set_updated_at on public.saved_views;
create trigger set_updated_at
  before update on public.saved_views
  for each row execute function rms_private.set_updated_at();

-- ===========================================================================
-- 5. RLS Configuration
-- ===========================================================================
alter table public.user_activity enable row level security;
alter table public.saved_views enable row level security;

-- user_activity: users can read their own activity; Super Admin / Auditor can read all
drop policy if exists user_activity_select on public.user_activity;
create policy user_activity_select on public.user_activity
  for select
  to authenticated
  using (
    user_id = auth.uid()
    or exists (
      select 1 from public.profiles p
      where p.id = auth.uid() and p.is_super_admin = true
    )
    or exists (
      select 1 from public.user_roles ur
      join public.roles r on r.id = ur.role_id
      where ur.user_id = auth.uid() and r.code in ('AUDITOR', 'SUPER_ADMIN')
    )
  );

-- saved_views: users manage their own saved views
drop policy if exists saved_views_owner on public.saved_views;
create policy saved_views_owner on public.saved_views
  for all
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

-- Grant access to rms_api role
grant select, insert on public.user_activity to rms_api;
grant select, insert, update, delete on public.saved_views to rms_api;
