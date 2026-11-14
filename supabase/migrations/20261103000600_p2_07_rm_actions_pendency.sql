-- =============================================================================
-- Migration: 20261103000600_p2_07_rm_actions_pendency.sql
-- Prompt: P2-07 — Step-3 a) RM item-wise actions, Pending (BP) register & printable Replacement Slip
-- References: BR-19, BR-20, G-08, DEC-12, DEC-13, DEC-33, §8.4 (rm_item_actions, pendencies)
-- =============================================================================

-- 1. rm_item_actions partial unique index for current revision
create unique index if not exists rm_item_actions_current_uq
  on public.rm_item_actions (gs_item_id, action_code) where is_current;

-- 2. Enhance pendencies table with resolution details & lot/movement references
alter table public.pendencies
  add column if not exists resolution_action text check (resolution_action is null or resolution_action in ('SEND_NEW','SEND_REPAIRED','ISSUE_CN','NOT_ALLOWED')),
  add column if not exists lot_id uuid references public.stock_lots(id) on delete set null,
  add column if not exists stock_movement_id uuid references public.stock_movements(id) on delete set null;

-- 3. Print logs table to track document print/reprint history
create table if not exists public.print_logs (
  id uuid primary key default gen_random_uuid(),
  template_code text not null check (btrim(template_code) <> ''),
  entity_type text not null default 'goods_slips',
  entity_id uuid not null,
  revision_no integer not null default 1,
  printed_by uuid not null default rms_private.current_actor() references public.profiles(id) on delete restrict,
  printed_at timestamptz not null default now(),
  metadata jsonb not null default '{}'::jsonb
);

create index if not exists print_logs_entity_idx on public.print_logs (entity_type, entity_id);
create index if not exists print_logs_printed_by_idx on public.print_logs (printed_by);

alter table public.print_logs enable row level security;
select rms_private.attach_standard_triggers('public.print_logs');
grant select, insert, update on public.print_logs to rms_api;

-- 4. Extend audit_log action constraint to include 'PRINT'
alter table public.audit_log drop constraint if exists audit_log_action_check;
alter table public.audit_log add constraint audit_log_action_check check (action in ('INSERT','UPDATE','DELETE','ACCESS','PRINT'));

-- 5. Seed / ensure system setting for DEC-12
insert into public.system_settings (key, value, category, description, source_ref)
values ('pending_blocks_entire_gs', 'false', 'provisional', 'Provisional: Pending (BP) blocks only the pending pieces; non-pending pieces may continue to handover.', 'DEC-12')
on conflict (key) do nothing;
