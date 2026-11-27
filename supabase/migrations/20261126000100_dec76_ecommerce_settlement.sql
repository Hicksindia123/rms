-- =============================================================================================
-- DEC-76: E-Commerce Return settlement (user spec 2026-11-26).
--
-- Extends the DEC-73 E-Commerce Return (one return = one platform order id) after the gate entry:
--
--   E-Commerce Executive (role TICKET_HANDLER, relabelled)
--     * ticket route   PENDING_TICKET → TICKET_RAISED (+ follow-ups) → ticket closed with the
--                      platform outcome AND the portal resolution  → PENDING_UNBOXING
--     * no ticket      IN_CHECKING ("Portal Check Pending") → portal resolution → PENDING_UNBOXING
--     The portal resolution = what the portal shows for the order (option set
--     ECOM_PORTAL_RESOLUTION: FREE_REPLACEMENT / REFUND) + its qty (1..received) + a short note.
--   Unboxing / Verifier (ecommerce_unboxing.create)
--     * sees every PENDING_UNBOXING return at a glance (platform, date), splits each one into
--       To Store / To Repair / Wastage (sum = received qty) and submits a batch of ONE platform
--       → one E-Commerce Action Sheet (series ECOM_ACTION_SHEET) listing every order id with
--       Qty Received and Qty Issue CN. Qty Issue CN = resolution qty for REFUND, 0 for a free
--       replacement (enforced by a CHECK below; logic keys off the code REFUND, rule e).
--       Each return → UNBOXED.
--     * stock (rms_move_stock in the backend, same transaction): good pieces → receipt location
--       (setting ecommerce_receipt_location_code), repair pieces → the chosen repair department
--       location (setting ecommerce_repair_location_codes), wastage → wastage location
--       (setting ecommerce_wastage_location_code). A "Different Product" has no product master
--       entry: all its pieces are wastage and nothing is stocked.
--     * records the pieces back from repair (ok / scrap); ok pieces go to the store.
--   Intermediate Store user (ecommerce_store_receipts.create, a user of that store)
--     * acknowledges the receipt of good / repaired pieces → stock moves into the store location
--       (the store of the product, DEC-61 mapping).
--   E-Commerce Accounts (role ECOM_ACCOUNTS, ecommerce_accounts.edit)
--     * issues ONE credit note per action sheet when its Qty Issue CN > 0 (same data as the
--       offline accountant: CN no, CN date, CN value, remarks). A sheet without CN qty completes
--       by itself.
--   A return is CLOSED once its sheet is completed, every good / repaired piece is acknowledged by
--   the store and its repair (if any) came back.
--
-- Rules are enforced here (CHECKs, triggers; coded errors ECOM_*) AND in the backend services
-- (app/modules/ecommerce_returns, app/modules/ecommerce_settlement). No guard G-01…G-22 changes.
-- Roles, grants and menus are seed data (seed.sql + supabase/snippets/release_20261126_dec76_*).
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- 1. Permissions
-- ---------------------------------------------------------------------------------------------
insert into public.permissions (module_code, action, description)
values
  ('ecommerce_unboxing',       'view',   'See the E-Commerce unboxing queue (DEC-76)'),
  ('ecommerce_unboxing',       'create', 'Unbox E-Commerce Returns, create action sheets, record repairs (DEC-76)'),
  ('ecommerce_store_receipts', 'view',   'See E-Commerce pieces issued to the Intermediate Store (DEC-76)'),
  ('ecommerce_store_receipts', 'create', 'Acknowledge E-Commerce pieces received in the store (DEC-76)'),
  ('ecommerce_accounts',       'view',   'See E-Commerce action sheets (DEC-76)'),
  ('ecommerce_accounts',       'edit',   'Issue the credit note of an E-Commerce action sheet (DEC-76)')
on conflict (module_code, action) do nothing;

insert into public.role_permissions (role_id, permission_id, scope)
select r.id, p.id, 'all'
  from public.roles r
  join public.permissions p
    on p.module_code in ('ecommerce_unboxing', 'ecommerce_store_receipts', 'ecommerce_accounts')
 where r.code = 'SUPER_ADMIN'
on conflict (role_id, permission_id) do nothing;

-- ---------------------------------------------------------------------------------------------
-- 2. Number series (editable in Admin → Numbering)
-- ---------------------------------------------------------------------------------------------
insert into public.number_series (code, name, prefix, pattern, reset_policy, fy_start_month, fy_format)
values ('ECOM_ACTION_SHEET', 'E-Commerce Action Sheet', 'EAS', '{PREFIX}/{FY}/{SEQ:5}', 'YEARLY_FY', 4, 'LONG')
on conflict (code) do nothing;

-- ---------------------------------------------------------------------------------------------
-- 3. Option sets (labels are configuration; logic keys off the codes)
-- ---------------------------------------------------------------------------------------------
insert into public.option_sets (code, name, description, control_type, source_kind, master_ref_type, source_ref, is_system)
values
  ('ECOM_PORTAL_RESOLUTION', 'Portal Resolution', 'E-Commerce Return · E-Commerce Executive · what the platform portal shows for the order (by order id). Only REFUND needs a credit note.', 'radio', 'STATIC', null, 'DEC-76', true),
  ('ECOM_UNBOX_BUCKET', 'Unboxing Result', 'E-Commerce Return · Unboxing · where the received pieces go.', 'radio', 'STATIC', null, 'DEC-76', true),
  ('ECOM_ACTION_SHEET_STATUS', 'E-Commerce Action Sheet Status', 'E-Commerce Action Sheet · status labels (the codes are the lifecycle).', 'dropdown', 'STATIC', null, 'DEC-76', true)
on conflict (code) do nothing;

insert into public.option_items (option_set_id, code, label, allowed_status, rule_text, next_action_text,
                                 remarks, system_behavior, required_fields, sort_order, source_ref)
select os.id, v.code, v.label, 'YES', v.rule_text, null, null, null, '[]'::jsonb, v.sort_order, 'DEC-76'
  from (values
    ('ECOM_PORTAL_RESOLUTION', 'FREE_REPLACEMENT', 'Free Replacement', 'A free replacement is sent; no credit note', 10),
    ('ECOM_PORTAL_RESOLUTION', 'REFUND', 'Refund', 'The customer is refunded; Accounts issues a credit note for the qty', 20),
    ('ECOM_UNBOX_BUCKET', 'TO_STORE', 'Good / Fresh → Store', 'Issued to the store; the store acknowledges the receipt', 10),
    ('ECOM_UNBOX_BUCKET', 'TO_REPAIR', 'Production / Repair', 'Dirty, not working or packaging damaged; comes back to the store after repair', 20),
    ('ECOM_UNBOX_BUCKET', 'WASTAGE', 'Damaged / Wastage', 'Cannot be used', 30),
    ('ECOM_ACTION_SHEET_STATUS', 'PENDING_ACCOUNTS', 'Pending with Accounts', 'Accounts issues the credit note', 10),
    ('ECOM_ACTION_SHEET_STATUS', 'COMPLETED', 'Completed', 'Credit note issued, or no credit note needed', 20),
    ('ECOM_RETURN_STATUS', 'PENDING_UNBOXING', 'Awaiting Unboxing', 'The E-Commerce Executive finished; waiting for the unboxing user', 42),
    ('ECOM_RETURN_STATUS', 'UNBOXED', 'In Process', 'Unboxed; waiting for the store receipt, the repair or the credit note', 44)
  ) as v(set_code, code, label, rule_text, sort_order)
  join public.option_sets os on os.code = v.set_code
on conflict (option_set_id, code) do nothing;

-- Relabel the seeded labels only (an admin relabel is never overwritten).
update public.option_items oi
   set label = 'Portal Check Pending',
       rule_text = 'The E-Commerce Executive checks the portal (Free Replacement / Refund)'
  from public.option_sets os
 where os.id = oi.option_set_id and os.code = 'ECOM_RETURN_STATUS'
   and oi.code = 'IN_CHECKING' and oi.label = 'In Checking';
update public.option_items oi
   set rule_text = 'Settled: action sheet completed and every piece received'
  from public.option_sets os
 where os.id = oi.option_set_id and os.code = 'ECOM_RETURN_STATUS'
   and oi.code = 'CLOSED' and oi.rule_text = 'Ticket closed with a final response';
update public.option_items oi
   set rule_text = 'No ticket: the E-Commerce Executive checks the portal for a free replacement or a refund'
  from public.option_sets os
 where os.id = oi.option_set_id and os.code = 'ECOM_QC_ROUTING'
   and oi.code = 'ISSUE_TO_CHECKING' and oi.rule_text = 'Goes to the Checking Department (process to be defined)';

-- ---------------------------------------------------------------------------------------------
-- 4. Settings
-- ---------------------------------------------------------------------------------------------
insert into public.system_settings (key, value, category, description, source_ref) values
  ('ecommerce_receipt_location_code', '"INWARD_STAGING"'::jsonb, 'ecommerce',
   'Inventory location (class INWARD) holding good E-Commerce pieces until the store acknowledges them.', 'DEC-76'),
  ('ecommerce_wastage_location_code', '"REJECTED_HOLD"'::jsonb, 'ecommerce',
   'Inventory location (class REJECTED_HOLD / NON_FUNCTIONAL / SCRAP_DISPOSED) for damaged / wastage E-Commerce pieces.', 'DEC-76'),
  ('ecommerce_repair_location_codes', '["DEPT_TECHNICIAN_REPAIR", "DEPT_REPACKAGING"]'::jsonb, 'ecommerce',
   'Department locations (class TECHNICIAN) the unboxing user may send E-Commerce pieces to for repair / repackaging.', 'DEC-76')
on conflict (key) do nothing;

-- ---------------------------------------------------------------------------------------------
-- 5. Tables
-- ---------------------------------------------------------------------------------------------
create table public.ecommerce_action_sheets (
  id              uuid primary key default gen_random_uuid(),
  sheet_no        text not null unique check (btrim(sheet_no) <> ''),
  platform_code   text not null check (platform_code ~ '^[A-Z][A-Z0-9_]*$'),
  platform_label  text not null check (btrim(platform_label) <> ''),          -- G-18 snapshot
  status          text not null default 'PENDING_ACCOUNTS' check (status in ('PENDING_ACCOUNTS', 'COMPLETED')),
  cn_no           text check (cn_no is null or (cn_no = btrim(cn_no) and cn_no <> '' and length(cn_no) <= 60)),
  cn_date         date,
  cn_value        numeric(14, 2) check (cn_value is null or cn_value > 0),
  remarks         text check (remarks is null or length(remarks) <= 1000),
  completed_at    timestamptz,
  completed_by    uuid references public.profiles (id) on delete restrict,
  created_at      timestamptz not null default now(),
  created_by      uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at      timestamptz not null default now(),
  constraint ecommerce_action_sheets_completed_shape check (
    (status = 'COMPLETED') = (completed_at is not null) and (completed_at is null) = (completed_by is null)),
  constraint ecommerce_action_sheets_cn_shape check (
    (cn_no is null) = (cn_date is null) and (cn_no is null) = (cn_value is null))
);
create index ecommerce_action_sheets_status_idx on public.ecommerce_action_sheets (status, created_at desc);
comment on table public.ecommerce_action_sheets is
  'DEC-76: one per unboxing batch of ONE platform; lists every order id (its returns) with Qty Received and Qty Issue CN. Accounts issues one credit note per sheet when Qty Issue CN > 0.';

alter table public.ecommerce_returns drop constraint ecommerce_returns_status_check;
alter table public.ecommerce_returns add constraint ecommerce_returns_status_check check (status in (
  'DRAFT', 'IN_CHECKING', 'PENDING_TICKET', 'TICKET_RAISED', 'PENDING_UNBOXING', 'UNBOXED', 'CLOSED', 'VOIDED'));

alter table public.ecommerce_returns
  add column resolution_code     text check (resolution_code is null or resolution_code ~ '^[A-Z][A-Z0-9_]*$'),
  add column resolution_label    text,
  add column resolution_qty      integer,
  add column resolution_note     text check (resolution_note is null or (btrim(resolution_note) <> '' and length(resolution_note) <= 200)),
  add column resolved_at         timestamptz,
  add column resolved_by         uuid references public.profiles (id) on delete restrict,
  add column action_sheet_id     uuid references public.ecommerce_action_sheets (id) on delete restrict,
  add column good_qty            integer,
  add column repair_qty          integer,
  add column wastage_qty         integer,
  add column cn_qty              integer,
  add column repair_location_id  uuid references public.inventory_locations (id) on delete restrict,
  add column unbox_note          text check (unbox_note is null or (btrim(unbox_note) <> '' and length(unbox_note) <= 300)),
  add column unboxed_at          timestamptz,
  add column unboxed_by          uuid references public.profiles (id) on delete restrict;
create index ecommerce_returns_sheet_idx on public.ecommerce_returns (action_sheet_id);

alter table public.ecommerce_returns drop constraint ecommerce_returns_routing_status;
alter table public.ecommerce_returns add constraint ecommerce_returns_routing_status check (
  status in ('DRAFT', 'VOIDED', 'CLOSED', 'PENDING_UNBOXING', 'UNBOXED')
  or (qc_routing_code = 'ISSUE_TO_CHECKING' and status = 'IN_CHECKING')
  or (qc_routing_code = 'TICKET_RAISE' and status in ('PENDING_TICKET', 'TICKET_RAISED')));
-- DEC-73 closed only the ticket route; DEC-76 closes both routes after the settlement. A CLOSED
-- return without unboxing is a DEC-73 return closed by its ticket (before this change).
alter table public.ecommerce_returns drop constraint ecommerce_returns_closed_route;
alter table public.ecommerce_returns add constraint ecommerce_returns_closed_route check (
  status <> 'CLOSED' or unboxed_at is not null
  or (qc_routing_code = 'TICKET_RAISE' and resolution_code is null));

alter table public.ecommerce_returns add constraint ecommerce_returns_resolution_shape check (
  (resolution_code is null) = (resolution_label is null)
  and (resolution_code is null) = (resolution_qty is null)
  and (resolution_code is null) = (resolved_at is null)
  and (resolution_code is null) = (resolved_by is null)
  and (resolution_note is null or resolution_code is not null)
  and (resolution_qty is null or resolution_qty between 1 and qty)
  and (status not in ('PENDING_UNBOXING', 'UNBOXED') or resolution_code is not null));

alter table public.ecommerce_returns add constraint ecommerce_returns_unboxing_shape check (
  (unboxed_at is null) = (unboxed_by is null)
  and (unboxed_at is null) = (action_sheet_id is null)
  and (unboxed_at is null) = (good_qty is null)
  and (unboxed_at is null) = (repair_qty is null)
  and (unboxed_at is null) = (wastage_qty is null)
  and (unboxed_at is null) = (cn_qty is null)
  and (unbox_note is null or unboxed_at is not null)
  and (status <> 'UNBOXED' or unboxed_at is not null)
  and (unboxed_at is null or (status in ('UNBOXED', 'CLOSED') and resolution_code is not null))
  and (unboxed_at is null or (good_qty >= 0 and repair_qty >= 0 and wastage_qty >= 0
                              and good_qty + repair_qty + wastage_qty = qty))
  -- Repair pieces go to exactly one department location.
  and ((coalesce(repair_qty, 0) > 0) = (repair_location_id is not null))
  -- A different product is not in the product master: nothing can be stocked.
  and (product_id is not null or unboxed_at is null or (good_qty = 0 and repair_qty = 0)));

-- The CN rule (user spec 2026-11-26): a free replacement never gets a credit note; a refund gets
-- one for the executive's qty. Keys off the stable code REFUND.
alter table public.ecommerce_returns add constraint ecommerce_returns_cn_qty_rule check (
  cn_qty is null
  or cn_qty = case when resolution_code = 'REFUND' then resolution_qty else 0 end);

-- Ticket follow-ups (the executive chases the platform; each follow-up is also an event).
alter table public.ecommerce_tickets
  add column follow_up_count    integer not null default 0 check (follow_up_count >= 0),
  add column last_follow_up_at  timestamptz,
  add column next_follow_up_on  date;
alter table public.ecommerce_tickets add constraint ecommerce_tickets_follow_up_shape check (
  (follow_up_count = 0) = (last_follow_up_at is null));

create table public.ecommerce_repairs (
  id             uuid primary key default gen_random_uuid(),
  return_id      uuid not null unique references public.ecommerce_returns (id) on delete restrict,
  location_id    uuid not null references public.inventory_locations (id) on delete restrict,
  lot_id         uuid not null references public.stock_lots (id) on delete restrict,
  qty_sent       integer not null check (qty_sent > 0),
  status         text not null default 'AT_DEPARTMENT' check (status in ('AT_DEPARTMENT', 'RETURNED')),
  qty_ok         integer check (qty_ok is null or qty_ok >= 0),
  qty_scrap      integer check (qty_scrap is null or qty_scrap >= 0),
  return_note    text check (return_note is null or (btrim(return_note) <> '' and length(return_note) <= 300)),
  returned_at    timestamptz,
  returned_by    uuid references public.profiles (id) on delete restrict,
  created_at     timestamptz not null default now(),
  created_by     uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at     timestamptz not null default now(),
  constraint ecommerce_repairs_returned_shape check (
    (status = 'RETURNED') = (returned_at is not null)
    and (returned_at is null) = (returned_by is null)
    and (returned_at is null) = (qty_ok is null)
    and (returned_at is null) = (qty_scrap is null)
    and (returned_at is null or qty_ok + qty_scrap = qty_sent))
);
create index ecommerce_repairs_open_idx on public.ecommerce_repairs (created_at) where status = 'AT_DEPARTMENT';
comment on table public.ecommerce_repairs is
  'DEC-76: E-Commerce pieces sent to a production / repair department at unboxing, and what came back (ok → store, scrap → wastage).';

create table public.ecommerce_store_receipts (
  id                uuid primary key default gen_random_uuid(),
  return_id         uuid not null references public.ecommerce_returns (id) on delete restrict,
  source            text not null check (source in ('UNBOXING', 'REPAIR')),
  store_id          uuid not null references public.intermediate_stores (id) on delete restrict,
  lot_id            uuid not null references public.stock_lots (id) on delete restrict,
  from_location_id  uuid not null references public.inventory_locations (id) on delete restrict,
  qty               integer not null check (qty > 0),
  status            text not null default 'PENDING' check (status in ('PENDING', 'ACKNOWLEDGED')),
  movement_id       uuid references public.stock_movements (id) on delete restrict,
  acknowledged_at   timestamptz,
  acknowledged_by   uuid references public.profiles (id) on delete restrict,
  created_at        timestamptz not null default now(),
  created_by        uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at        timestamptz not null default now(),
  constraint ecommerce_store_receipts_ack_shape check (
    (status = 'ACKNOWLEDGED') = (acknowledged_at is not null)
    and (acknowledged_at is null) = (acknowledged_by is null)
    and (acknowledged_at is null) = (movement_id is null))
);
create index ecommerce_store_receipts_store_idx on public.ecommerce_store_receipts (store_id, status);
create index ecommerce_store_receipts_return_idx on public.ecommerce_store_receipts (return_id);
create unique index ecommerce_store_receipts_one_per_source
  on public.ecommerce_store_receipts (return_id, source);
comment on table public.ecommerce_store_receipts is
  'DEC-76: good (UNBOXING) or repaired (REPAIR) E-Commerce pieces issued to the product''s Intermediate Store; the store acknowledges the receipt, which moves the stock into the store.';

-- Traceability of E-Commerce stock (these lots have no goods slip).
alter table public.stock_lots
  add column ecommerce_return_id uuid references public.ecommerce_returns (id) on delete restrict;
create index stock_lots_ecommerce_return_idx on public.stock_lots (ecommerce_return_id)
  where ecommerce_return_id is not null;
alter table public.stock_lots add constraint stock_lots_ecommerce_no_gs check (
  ecommerce_return_id is null or (gs_id is null and gs_item_id is null));

-- ---------------------------------------------------------------------------------------------
-- 6. Helpers
-- ---------------------------------------------------------------------------------------------
create or replace function rms_private.ecom_option_active(p_set text, p_code text)
returns boolean
language sql
stable
set search_path = ''
as $$
  select exists (select 1 from public.option_items oi join public.option_sets os on os.id = oi.option_set_id
                  where os.code = p_set and oi.code = p_code and oi.is_active)
$$;
revoke all on function rms_private.ecom_option_active(text, text) from public, anon, authenticated;
grant execute on function rms_private.ecom_option_active(text, text) to rms_api;

-- A return is settled: its sheet is completed, every good piece and every repaired piece has been
-- acknowledged by the store, and its repair (if any) came back.
create or replace function rms_private.ecom_return_settled(p_return_id uuid)
returns boolean
language sql
stable
set search_path = ''
as $$
  select r.unboxed_at is not null
     and exists (select 1 from public.ecommerce_action_sheets s
                  where s.id = r.action_sheet_id and s.status = 'COMPLETED')
     and r.good_qty = coalesce((select sum(x.qty) from public.ecommerce_store_receipts x
                                 where x.return_id = r.id and x.source = 'UNBOXING'
                                   and x.status = 'ACKNOWLEDGED'), 0)
     and (r.repair_qty = 0
          or exists (select 1 from public.ecommerce_repairs p
                      where p.return_id = r.id and p.status = 'RETURNED'
                        and p.qty_ok = coalesce((select sum(x.qty) from public.ecommerce_store_receipts x
                                                  where x.return_id = r.id and x.source = 'REPAIR'
                                                    and x.status = 'ACKNOWLEDGED'), 0)))
    from public.ecommerce_returns r
   where r.id = p_return_id
$$;
revoke all on function rms_private.ecom_return_settled(uuid) from public, anon, authenticated;
grant execute on function rms_private.ecom_return_settled(uuid) to rms_api;

-- ---------------------------------------------------------------------------------------------
-- 7. Guards
-- ---------------------------------------------------------------------------------------------

-- 7a. Return (full body; DEC-73 rules unchanged, DEC-76 transitions added).
create or replace function rms_private.ecommerce_returns_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_actor   uuid := rms_private.current_actor();
  v_pattern text;
  v_ticket  public.ecommerce_tickets%rowtype;
  v_sheet   public.ecommerce_action_sheets%rowtype;
  v_class   text;
begin
  if tg_op = 'DELETE' then
    raise exception 'ECOM_RETURN_IMMUTABLE: an E-Commerce Return is never deleted; void it instead'
      using errcode = '42501';
  end if;

  if tg_op = 'INSERT' then
    if not coalesce(rms_private.user_holds_permission(v_actor, 'ecommerce_returns', 'create'), false) then
      raise exception 'ECOM_FORBIDDEN: recording an E-Commerce Return needs ecommerce_returns.create'
        using errcode = '42501';
    end if;
    if new.status <> 'DRAFT' or new.submitted_at is not null or new.voided_at is not null
       or new.closed_at is not null or new.resolution_code is not null or new.unboxed_at is not null then
      raise exception 'ECOM_INVALID_STATE: an E-Commerce Return starts as DRAFT' using errcode = '23514';
    end if;
    if new.entry_date > rms_private.business_today() then
      raise exception 'ECOM_ENTRY_DATE_FUTURE: the entry date cannot be later than today' using errcode = '23514';
    end if;
    if not rms_private.ecom_option_active('ECOM_PLATFORM', new.platform_code) then
      raise exception 'ECOM_PLATFORM_UNKNOWN: platform % is not an active ECOM_PLATFORM option', new.platform_code
        using errcode = '23514';
    end if;
    select s.value #>> '{}' into v_pattern from public.system_settings s
     where s.key = 'ecommerce_order_id_pattern' and jsonb_typeof(s.value) = 'string';
    if new.order_id !~ coalesce(v_pattern, '^[A-Za-z0-9-]{3,40}$') then
      raise exception 'ECOM_ORDER_ID_INVALID: order id % does not match the configured pattern', new.order_id
        using errcode = '23514';
    end if;
    if new.product_id is not null and not exists (
         select 1 from public.products p where p.id = new.product_id and p.is_active) then
      raise exception 'ECOM_PRODUCT_INACTIVE: the product is not active in the product master' using errcode = '23514';
    end if;
    return new;
  end if;

  -- UPDATE: the gate data never changes (no edits after creation, DEC-73 Q6).
  if (new.id, new.return_no, new.entry_date, new.platform_code, new.platform_label, new.order_id,
      new.product_type_code, new.product_type_label, new.product_id, new.product_code_snapshot,
      new.product_name_snapshot, new.different_product_desc, new.qty, new.qc_routing_code,
      new.qc_routing_label, new.created_at, new.created_by)
     is distinct from
     (old.id, old.return_no, old.entry_date, old.platform_code, old.platform_label, old.order_id,
      old.product_type_code, old.product_type_label, old.product_id, old.product_code_snapshot,
      old.product_name_snapshot, old.different_product_desc, old.qty, old.qc_routing_code,
      old.qc_routing_label, old.created_at, old.created_by) then
    raise exception 'ECOM_RETURN_IMMUTABLE: the gate entry of an E-Commerce Return cannot be edited'
      using errcode = '42501';
  end if;

  -- The executive's resolution is written once (on the way to PENDING_UNBOXING), the unboxing once
  -- (on the way to UNBOXED); neither changes afterwards.
  if old.resolution_code is not null
     and (new.resolution_code, new.resolution_label, new.resolution_qty, new.resolution_note,
          new.resolved_at, new.resolved_by)
         is distinct from
         (old.resolution_code, old.resolution_label, old.resolution_qty, old.resolution_note,
          old.resolved_at, old.resolved_by) then
    raise exception 'ECOM_RETURN_IMMUTABLE: the portal resolution cannot be changed' using errcode = '42501';
  end if;
  if old.unboxed_at is not null
     and (new.action_sheet_id, new.good_qty, new.repair_qty, new.wastage_qty, new.cn_qty,
          new.repair_location_id, new.unbox_note, new.unboxed_at, new.unboxed_by)
         is distinct from
         (old.action_sheet_id, old.good_qty, old.repair_qty, old.wastage_qty, old.cn_qty,
          old.repair_location_id, old.unbox_note, old.unboxed_at, old.unboxed_by) then
    raise exception 'ECOM_RETURN_IMMUTABLE: the unboxing result cannot be changed' using errcode = '42501';
  end if;

  if new.status = old.status then
    if (new.submitted_at, new.submitted_by, new.void_reason, new.voided_at, new.voided_by, new.closed_at,
        new.resolution_code, new.unboxed_at)
       is distinct from
       (old.submitted_at, old.submitted_by, old.void_reason, old.voided_at, old.voided_by, old.closed_at,
        old.resolution_code, old.unboxed_at) then
      raise exception 'ECOM_RETURN_IMMUTABLE: lifecycle stamps change only with the status' using errcode = '42501';
    end if;
    return new;
  end if;

  if old.status in ('CLOSED', 'VOIDED') then
    raise exception 'ECOM_INVALID_TRANSITION: % is final', old.status using errcode = '23514';
  end if;

  if new.status = 'VOIDED' then
    if not coalesce(rms_private.user_holds_permission(v_actor, 'ecommerce_returns', 'delete'), false) then
      raise exception 'ECOM_FORBIDDEN: voiding needs ecommerce_returns.delete (Super Admin / Management)'
        using errcode = '42501';
    end if;
    -- DEC-76: an unboxed return carries stock and sits on an action sheet.
    if old.status = 'UNBOXED' then
      raise exception 'ECOM_INVALID_STATE: an unboxed return cannot be voided' using errcode = '23514';
    end if;
    return new;
  end if;

  if old.status = 'DRAFT' then
    -- Submit: the mandatory package-opening video is confirmed, no image is still uploading.
    if not coalesce(rms_private.user_holds_permission(v_actor, 'ecommerce_returns', 'create'), false) then
      raise exception 'ECOM_FORBIDDEN: submitting needs ecommerce_returns.create' using errcode = '42501';
    end if;
    if not exists (select 1 from public.ecommerce_return_media m
                    where m.return_id = new.id and m.kind = 'PACKAGE_VIDEO' and m.status = 'CONFIRMED') then
      raise exception 'ECOM_VIDEO_REQUIRED: the package opening video must be uploaded before submitting'
        using errcode = '23514';
    end if;
    if exists (select 1 from public.ecommerce_return_media m
                where m.return_id = new.id and m.status = 'PENDING_UPLOAD') then
      raise exception 'ECOM_MEDIA_PENDING: a file is still uploading; finish or remove it' using errcode = '23514';
    end if;
    if (old.qc_routing_code = 'ISSUE_TO_CHECKING' and new.status = 'IN_CHECKING')
       or (old.qc_routing_code = 'TICKET_RAISE' and new.status = 'PENDING_TICKET') then
      return new;
    end if;
    raise exception 'ECOM_INVALID_TRANSITION: DRAFT → % does not match QC routing %', new.status, old.qc_routing_code
      using errcode = '23514';
  end if;

  select * into v_ticket from public.ecommerce_tickets t where t.return_id = new.id;

  -- DEC-76: the E-Commerce Executive finishes (portal check, or ticket closed) with the resolution.
  if new.status = 'PENDING_UNBOXING' then
    if old.status not in ('IN_CHECKING', 'TICKET_RAISED') then
      raise exception 'ECOM_INVALID_TRANSITION: % → PENDING_UNBOXING is not allowed', old.status
        using errcode = '23514';
    end if;
    if not coalesce(rms_private.user_holds_permission(v_actor, 'ecommerce_tickets', 'edit'), false) then
      raise exception 'ECOM_FORBIDDEN: only the E-Commerce Executive records the portal resolution'
        using errcode = '42501';
    end if;
    if old.status = 'TICKET_RAISED' and v_ticket.closed_at is null then
      raise exception 'ECOM_TICKET_OPEN: close the ticket with the platform response first' using errcode = '23514';
    end if;
    if new.resolution_code is null or not rms_private.ecom_option_active('ECOM_PORTAL_RESOLUTION', new.resolution_code) then
      raise exception 'ECOM_RESOLUTION_REQUIRED: choose an active portal resolution (Free Replacement / Refund)'
        using errcode = '23514';
    end if;
    if new.resolved_by is distinct from v_actor then
      raise exception 'ECOM_INVALID_STATE: the resolution is recorded by the acting user' using errcode = '23514';
    end if;
    return new;
  end if;

  -- DEC-76: unboxing puts the return on an action sheet of its platform, created in this transaction.
  if new.status = 'UNBOXED' then
    if old.status <> 'PENDING_UNBOXING' then
      raise exception 'ECOM_INVALID_TRANSITION: % → UNBOXED is not allowed', old.status using errcode = '23514';
    end if;
    if not coalesce(rms_private.user_holds_permission(v_actor, 'ecommerce_unboxing', 'create'), false) then
      raise exception 'ECOM_FORBIDDEN: unboxing needs ecommerce_unboxing.create' using errcode = '42501';
    end if;
    select * into v_sheet from public.ecommerce_action_sheets s where s.id = new.action_sheet_id;
    if v_sheet.id is null or v_sheet.status <> 'PENDING_ACCOUNTS' or v_sheet.created_at <> now() then
      raise exception 'ECOM_SHEET_INVALID: a return joins only the action sheet created by its unboxing'
        using errcode = '23514';
    end if;
    if v_sheet.platform_code <> new.platform_code then
      raise exception 'ECOM_SHEET_PLATFORM: one action sheet holds one platform (% ≠ %)', new.platform_code, v_sheet.platform_code
        using errcode = '23514';
    end if;
    if new.repair_location_id is not null then
      select l.location_class into v_class from public.inventory_locations l
       where l.id = new.repair_location_id and l.is_active;
      if v_class is distinct from 'TECHNICIAN' then
        raise exception 'ECOM_REPAIR_LOCATION: repair pieces go to an active department location'
          using errcode = '23514';
      end if;
    end if;
    if new.unboxed_by is distinct from v_actor then
      raise exception 'ECOM_INVALID_STATE: the unboxing is recorded by the acting user' using errcode = '23514';
    end if;
    return new;
  end if;

  -- DEC-76: closed once settled.
  if new.status = 'CLOSED' then
    if old.status <> 'UNBOXED' then
      raise exception 'ECOM_INVALID_TRANSITION: % → CLOSED is not allowed', old.status using errcode = '23514';
    end if;
    if not rms_private.ecom_return_settled(new.id) then
      raise exception 'ECOM_NOT_SETTLED: the action sheet, the store receipts or the repair are still open'
        using errcode = '23514';
    end if;
    if new.closed_at is null then
      raise exception 'ECOM_INVALID_STATE: closed_at is required' using errcode = '23514';
    end if;
    return new;
  end if;

  if old.status = 'IN_CHECKING' then
    raise exception 'ECOM_INVALID_TRANSITION: IN_CHECKING → % is not allowed', new.status using errcode = '23514';
  end if;

  -- Ticket route: the return follows its ticket.
  if old.status = 'PENDING_TICKET' and new.status = 'TICKET_RAISED' and v_ticket.raised_at is not null then
    return new;
  end if;
  raise exception 'ECOM_INVALID_TRANSITION: % → % is not allowed', old.status, new.status using errcode = '23514';
end
$$;
revoke all on function rms_private.ecommerce_returns_guard() from public, anon, authenticated;

-- 7b. Ticket → return sync: raising still moves the return; closing no longer closes it (DEC-76:
--     the executive closes the ticket AND records the resolution in the same command).
create or replace function rms_private.ecommerce_tickets_sync_return()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.raised_at is not null and old.raised_at is null then
    update public.ecommerce_returns set status = 'TICKET_RAISED' where id = new.return_id;
  end if;
  return null;
end
$$;
revoke all on function rms_private.ecommerce_tickets_sync_return() from public, anon, authenticated;

-- A closed ticket never leaves its return waiting on the ticket (checked at commit).
create or replace function rms_private.ecommerce_tickets_closed_resolved()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.closed_at is not null and exists (
       select 1 from public.ecommerce_returns r where r.id = new.return_id and r.status = 'TICKET_RAISED') then
    raise exception 'ECOM_RESOLUTION_REQUIRED: closing the ticket needs the portal resolution' using errcode = '23514';
  end if;
  return null;
end
$$;
revoke all on function rms_private.ecommerce_tickets_closed_resolved() from public, anon, authenticated;
create constraint trigger ecommerce_tickets_closed_resolved
  after update of closed_at on public.ecommerce_tickets
  deferrable initially deferred
  for each row execute function rms_private.ecommerce_tickets_closed_resolved();

-- 7b'. DEC-73 "a return on the ticket route has its ticket" (checked at commit): DEC-76 closes
--      returns of both routes, so a CLOSED return needs a ticket only on the ticket route.
create or replace function rms_private.ecommerce_returns_ticket_present()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_status  text;
  v_routing text;
begin
  select r.status, r.qc_routing_code into v_status, v_routing
    from public.ecommerce_returns r where r.id = new.id;
  if (v_status in ('PENDING_TICKET', 'TICKET_RAISED')
      or (v_routing = 'TICKET_RAISE' and v_status in ('PENDING_UNBOXING', 'UNBOXED', 'CLOSED')))
     and not exists (select 1 from public.ecommerce_tickets t where t.return_id = new.id) then
    raise exception 'ECOM_TICKET_MISSING: return % is on the ticket route without a ticket', new.id
      using errcode = '23514';
  end if;
  return null;
end
$$;
revoke all on function rms_private.ecommerce_returns_ticket_present() from public, anon, authenticated;

-- 7c. Unboxed returns carry their repair and their store receipt of good pieces (at commit).
create or replace function rms_private.ecommerce_returns_unboxing_complete()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_ret public.ecommerce_returns%rowtype;
begin
  select * into v_ret from public.ecommerce_returns r where r.id = new.id;
  if v_ret.status <> 'UNBOXED' then
    return null;
  end if;
  if (v_ret.repair_qty > 0) <> exists (select 1 from public.ecommerce_repairs p
                                        where p.return_id = v_ret.id and p.qty_sent = v_ret.repair_qty
                                          and p.location_id = v_ret.repair_location_id) then
    raise exception 'ECOM_REPAIR_MISSING: return % must send exactly its repair pieces', v_ret.return_no
      using errcode = '23514';
  end if;
  if (v_ret.good_qty > 0) <> exists (select 1 from public.ecommerce_store_receipts x
                                      where x.return_id = v_ret.id and x.source = 'UNBOXING'
                                        and x.qty = v_ret.good_qty) then
    raise exception 'ECOM_RECEIPT_MISSING: return % must issue exactly its good pieces to the store', v_ret.return_no
      using errcode = '23514';
  end if;
  return null;
end
$$;
revoke all on function rms_private.ecommerce_returns_unboxing_complete() from public, anon, authenticated;
create constraint trigger ecommerce_returns_unboxing_complete
  after update of status on public.ecommerce_returns
  deferrable initially deferred
  for each row execute function rms_private.ecommerce_returns_unboxing_complete();

-- 7d. Action sheet.
create or replace function rms_private.ecommerce_action_sheets_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_actor  uuid := rms_private.current_actor();
  v_cn_qty bigint;
begin
  if tg_op = 'DELETE' then
    raise exception 'ECOM_RETURN_IMMUTABLE: an action sheet is never deleted' using errcode = '42501';
  end if;
  if tg_op = 'INSERT' then
    if not coalesce(rms_private.user_holds_permission(v_actor, 'ecommerce_unboxing', 'create'), false) then
      raise exception 'ECOM_FORBIDDEN: an action sheet is created by the unboxing user' using errcode = '42501';
    end if;
    if new.status <> 'PENDING_ACCOUNTS' or new.cn_no is not null or new.remarks is not null
       or new.completed_at is not null then
      raise exception 'ECOM_INVALID_STATE: an action sheet starts pending, without a credit note' using errcode = '23514';
    end if;
    if not exists (select 1 from public.option_items oi join public.option_sets os on os.id = oi.option_set_id
                    where os.code = 'ECOM_PLATFORM' and oi.code = new.platform_code) then
      raise exception 'ECOM_PLATFORM_UNKNOWN: platform %', new.platform_code using errcode = '23514';
    end if;
    new.created_at := now();
    return new;
  end if;

  if (new.id, new.sheet_no, new.platform_code, new.platform_label, new.created_at, new.created_by)
     is distinct from (old.id, old.sheet_no, old.platform_code, old.platform_label, old.created_at, old.created_by) then
    raise exception 'ECOM_RETURN_IMMUTABLE: the action sheet header cannot be changed' using errcode = '42501';
  end if;
  if old.status = 'COMPLETED' then
    raise exception 'ECOM_SHEET_COMPLETED: a completed action sheet is final' using errcode = '23514';
  end if;
  if new.status = 'PENDING_ACCOUNTS' then
    raise exception 'ECOM_INVALID_STATE: the credit note is recorded when the sheet is completed' using errcode = '23514';
  end if;

  -- PENDING_ACCOUNTS → COMPLETED
  select coalesce(sum(r.cn_qty), 0) into v_cn_qty from public.ecommerce_returns r where r.action_sheet_id = new.id;
  if v_cn_qty > 0 then
    if not coalesce(rms_private.user_holds_permission(v_actor, 'ecommerce_accounts', 'edit'), false) then
      raise exception 'ECOM_FORBIDDEN: the credit note is issued by E-Commerce Accounts' using errcode = '42501';
    end if;
    if new.cn_no is null then
      raise exception 'ECOM_CN_REQUIRED: Qty Issue CN is % — enter the credit note number, date and value', v_cn_qty
        using errcode = '23514';
    end if;
    if new.cn_date > rms_private.business_today() then
      raise exception 'ECOM_CN_DATE_FUTURE: the credit note date cannot be later than today' using errcode = '23514';
    end if;
  else
    if new.cn_no is not null then
      raise exception 'ECOM_CN_NOT_NEEDED: this sheet has no qty for a credit note' using errcode = '23514';
    end if;
    if not (coalesce(rms_private.user_holds_permission(v_actor, 'ecommerce_unboxing', 'create'), false)
            or coalesce(rms_private.user_holds_permission(v_actor, 'ecommerce_accounts', 'edit'), false)) then
      raise exception 'ECOM_FORBIDDEN: completing an action sheet' using errcode = '42501';
    end if;
  end if;
  if new.completed_by is distinct from v_actor then
    raise exception 'ECOM_INVALID_STATE: completed by the acting user' using errcode = '23514';
  end if;
  return new;
end
$$;
revoke all on function rms_private.ecommerce_action_sheets_guard() from public, anon, authenticated;
create trigger ecommerce_action_sheets_guard
  before insert or update or delete on public.ecommerce_action_sheets
  for each row execute function rms_private.ecommerce_action_sheets_guard();

create or replace function rms_private.ecommerce_action_sheets_not_empty()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if not exists (select 1 from public.ecommerce_returns r where r.action_sheet_id = new.id) then
    raise exception 'ECOM_SHEET_EMPTY: action sheet % has no order', new.sheet_no using errcode = '23514';
  end if;
  return null;
end
$$;
revoke all on function rms_private.ecommerce_action_sheets_not_empty() from public, anon, authenticated;
create constraint trigger ecommerce_action_sheets_not_empty
  after insert on public.ecommerce_action_sheets
  deferrable initially deferred
  for each row execute function rms_private.ecommerce_action_sheets_not_empty();

-- 7e. Repair.
create or replace function rms_private.ecommerce_repairs_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_actor uuid := rms_private.current_actor();
  v_ret   public.ecommerce_returns%rowtype;
begin
  if tg_op = 'DELETE' then
    raise exception 'ECOM_RETURN_IMMUTABLE: a repair record is never deleted' using errcode = '42501';
  end if;
  if not coalesce(rms_private.user_holds_permission(v_actor, 'ecommerce_unboxing', 'create'), false) then
    raise exception 'ECOM_FORBIDDEN: repairs are recorded by the unboxing user' using errcode = '42501';
  end if;
  select * into v_ret from public.ecommerce_returns r where r.id = new.return_id;
  if tg_op = 'INSERT' then
    if v_ret.status <> 'UNBOXED' or v_ret.repair_qty is distinct from new.qty_sent
       or v_ret.repair_location_id is distinct from new.location_id then
      raise exception 'ECOM_INVALID_STATE: a repair carries the unboxed repair pieces of its return' using errcode = '23514';
    end if;
    if new.status <> 'AT_DEPARTMENT' then
      raise exception 'ECOM_INVALID_STATE: a repair starts at the department' using errcode = '23514';
    end if;
    if not exists (select 1 from public.stock_lots l where l.id = new.lot_id and l.ecommerce_return_id = new.return_id) then
      raise exception 'ECOM_LOT_MISMATCH: the repair lot belongs to another return' using errcode = '23514';
    end if;
    return new;
  end if;
  if (new.id, new.return_id, new.location_id, new.lot_id, new.qty_sent, new.created_at, new.created_by)
     is distinct from (old.id, old.return_id, old.location_id, old.lot_id, old.qty_sent, old.created_at, old.created_by) then
    raise exception 'ECOM_RETURN_IMMUTABLE: the repair header cannot be changed' using errcode = '42501';
  end if;
  if old.status = 'RETURNED' then
    raise exception 'ECOM_REPAIR_RETURNED: the repair pieces already came back' using errcode = '23514';
  end if;
  if new.returned_by is distinct from v_actor then
    raise exception 'ECOM_INVALID_STATE: recorded by the acting user' using errcode = '23514';
  end if;
  return new;
end
$$;
revoke all on function rms_private.ecommerce_repairs_guard() from public, anon, authenticated;
create trigger ecommerce_repairs_guard
  before insert or update or delete on public.ecommerce_repairs
  for each row execute function rms_private.ecommerce_repairs_guard();

-- 7f. Store receipt.
create or replace function rms_private.ecommerce_store_receipts_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_actor  uuid := rms_private.current_actor();
  v_ret    public.ecommerce_returns%rowtype;
  v_repair public.ecommerce_repairs%rowtype;
  v_loc    uuid;
begin
  if tg_op = 'DELETE' then
    raise exception 'ECOM_RETURN_IMMUTABLE: a store receipt is never deleted' using errcode = '42501';
  end if;
  select * into v_ret from public.ecommerce_returns r where r.id = new.return_id;
  if tg_op = 'INSERT' then
    if not coalesce(rms_private.user_holds_permission(v_actor, 'ecommerce_unboxing', 'create'), false) then
      raise exception 'ECOM_FORBIDDEN: pieces are issued to the store by the unboxing user' using errcode = '42501';
    end if;
    if v_ret.status <> 'UNBOXED' or v_ret.product_id is null then
      raise exception 'ECOM_INVALID_STATE: only unboxed pieces of our product go to the store' using errcode = '23514';
    end if;
    if new.status <> 'PENDING' then
      raise exception 'ECOM_INVALID_STATE: a store receipt starts pending' using errcode = '23514';
    end if;
    if new.store_id is distinct from rms_private.store_for_product(v_ret.product_id) then
      raise exception 'ECOM_STORE_MISMATCH: pieces go to the store of the product (DEC-61 mapping)' using errcode = '23514';
    end if;
    if not exists (select 1 from public.stock_lots l where l.id = new.lot_id and l.ecommerce_return_id = new.return_id) then
      raise exception 'ECOM_LOT_MISMATCH: the lot belongs to another return' using errcode = '23514';
    end if;
    if new.source = 'UNBOXING' and new.qty <> v_ret.good_qty then
      raise exception 'ECOM_QTY_MISMATCH: % good pieces were unboxed', v_ret.good_qty using errcode = '23514';
    end if;
    if new.source = 'REPAIR' then
      select * into v_repair from public.ecommerce_repairs p where p.return_id = new.return_id;
      if v_repair.status is distinct from 'RETURNED' or v_repair.qty_ok <> new.qty
         or v_repair.location_id <> new.from_location_id then
        raise exception 'ECOM_QTY_MISMATCH: the store receives the repaired pieces that came back' using errcode = '23514';
      end if;
    end if;
    return new;
  end if;

  if (new.id, new.return_id, new.source, new.store_id, new.lot_id, new.from_location_id, new.qty,
      new.created_at, new.created_by)
     is distinct from
     (old.id, old.return_id, old.source, old.store_id, old.lot_id, old.from_location_id, old.qty,
      old.created_at, old.created_by) then
    raise exception 'ECOM_RETURN_IMMUTABLE: a store receipt only changes its acknowledgement' using errcode = '42501';
  end if;
  if old.status = 'ACKNOWLEDGED' then
    raise exception 'ECOM_RECEIPT_ACKNOWLEDGED: already acknowledged' using errcode = '23514';
  end if;
  if not coalesce(rms_private.user_holds_permission(v_actor, 'ecommerce_store_receipts', 'create'), false)
     or not rms_private.user_acts_for_store(v_actor, new.store_id) then
    raise exception 'ECOM_FORBIDDEN: only a user of the receiving store acknowledges' using errcode = '42501';
  end if;
  select s.location_id into v_loc from public.intermediate_stores s where s.id = new.store_id;
  if not exists (select 1 from public.stock_movements m
                  where m.id = new.movement_id and m.lot_id = new.lot_id and m.qty = new.qty
                    and m.from_location_id = new.from_location_id and m.to_location_id = v_loc) then
    raise exception 'ECOM_MOVEMENT_MISMATCH: the acknowledgement needs the stock movement into the store'
      using errcode = '23514';
  end if;
  if new.acknowledged_by is distinct from v_actor then
    raise exception 'ECOM_INVALID_STATE: acknowledged by the acting user' using errcode = '23514';
  end if;
  return new;
end
$$;
revoke all on function rms_private.ecommerce_store_receipts_guard() from public, anon, authenticated;
create trigger ecommerce_store_receipts_guard
  before insert or update or delete on public.ecommerce_store_receipts
  for each row execute function rms_private.ecommerce_store_receipts_guard();

-- ---------------------------------------------------------------------------------------------
-- 8. RLS, grants, audit (G-17). Business data flows through the API (rms_api) only.
-- ---------------------------------------------------------------------------------------------
alter table public.ecommerce_action_sheets enable row level security;
alter table public.ecommerce_repairs enable row level security;
alter table public.ecommerce_store_receipts enable row level security;
revoke all on public.ecommerce_action_sheets, public.ecommerce_repairs, public.ecommerce_store_receipts
  from anon, authenticated;
grant select, insert, update on public.ecommerce_action_sheets to rms_api;
grant select, insert, update on public.ecommerce_repairs to rms_api;
grant select, insert, update on public.ecommerce_store_receipts to rms_api;
select rms_private.attach_standard_triggers('public.ecommerce_action_sheets');
select rms_private.attach_standard_triggers('public.ecommerce_repairs');
select rms_private.attach_standard_triggers('public.ecommerce_store_receipts');

-- ---------------------------------------------------------------------------------------------
-- 9. Journey catalogue (menus per role: seed + release snippet)
-- ---------------------------------------------------------------------------------------------
alter table public.journey_steps drop constraint if exists journey_steps_screen_key_check;
alter table public.journey_steps add constraint journey_steps_screen_key_check check (screen_key in (
  'journey-queue', 'gs-new', 'gs-list', 'dashboard', 'pendencies',
  'container-audit', 'reports', 'audit', 'custody', 'inventory', 'store-issues',
  'servicing', 'batteries', 'dismantling', 'scrap', 'credit-notes', 'approvals',
  'dispatch-queue', 'department-routing', 'department-receiving', 'department-issue',
  'accounts-entry', 'accounts-docs', 'dispatch-slips', 'transfer-slips', 'transfer-slip-acks',
  'store-routing', 'store-receiving', 'store-analysis', 'management-approval',
  'ecom-return-new', 'ecom-returns', 'ecom-tickets',
  'ecom-portal-check', 'ecom-unboxing', 'ecom-store-receipts', 'ecom-action-sheets'));

alter table public.journey_steps drop constraint if exists journey_steps_item_screen_key_check;
alter table public.journey_steps add constraint journey_steps_item_screen_key_check check (
  item_screen_key is null or item_screen_key in (
    'gs-detail', 'gs-unboxing', 'gs-itemization', 'gs-inspection', 'gs-rm-review',
    'custody-transfer', 'gs-final-actions', 'department-receiving', 'department-issue',
    'accounts-entry-gs', 'accounts-docs', 'dispatch-slips',
    'gs-party-notification', 'transfer-slips', 'transfer-slip', 'gs-store-routing',
    'gs-store-receiving', 'gs-store-analysis', 'gs-management-approval', 'ecom-return',
    'ecom-action-sheet'));

-- Work queues (menu badge counts + My Work list): the SQL fragments live in
-- backend/app/modules/journeys/repository.py (_QUEUES). queue_code is immutable once set.
alter table public.journey_steps drop constraint if exists journey_steps_queue_code_check;
alter table public.journey_steps add constraint journey_steps_queue_code_check check (
  queue_code is null or queue_code in (
    'CARTON_OPENING', 'COUNTING', 'CATEGORISATION', 'INSPECTION', 'RM_REVIEW', 'STORE_ACCEPT',
    'DEPT_ROUTING', 'DEPT_ISSUE', 'DEPT_RECEIVING', 'FINAL_ACTIONS', 'ACCOUNTS_DOCS',
    'ACCOUNTS_ENTRY', 'DISPATCH_SLIP', 'PARTY_EMAIL', 'PENDING_TRANSFER_SLIP', 'EDIT_REQUESTS',
    'STORE_ACK', 'STORE_ROUTING', 'STORE_RECEIVING', 'STORE_ANALYSIS', 'MANAGEMENT_APPROVAL',
    'ECOM_PORTAL_CHECK', 'ECOM_UNBOXING', 'ECOM_STORE_RECEIPTS', 'ECOM_ACTION_SHEETS'));

insert into public.journey_steps
  (code, label, hint, kind, screen_key, item_screen_key, queue_code, feature_code,
   perm_module, perm_action, sort_order, source_ref)
values
  ('ECOM_PORTAL_CHECK', 'Portal Check', 'Returns without a ticket: record what the portal shows (Free Replacement / Refund) and the qty',
   'STEP', 'ecom-portal-check', 'ecom-return', 'ECOM_PORTAL_CHECK', null, 'ecommerce_tickets', 'view', 13, 'DEC-76'),
  ('ECOM_UNBOXING', 'E-Commerce Unboxing', 'Unbox the returns per platform: pieces to the store, to repair or wastage; creates the action sheet',
   'STEP', 'ecom-unboxing', 'ecom-return', 'ECOM_UNBOXING', null, 'ecommerce_unboxing', 'view', 15, 'DEC-76'),
  ('ECOM_STORE_RECEIPTS', 'E-Commerce Receipts', 'Acknowledge E-Commerce pieces received in your store',
   'STEP', 'ecom-store-receipts', 'ecom-return', 'ECOM_STORE_RECEIPTS', null, 'ecommerce_store_receipts', 'view', 16, 'DEC-76'),
  ('ECOM_ACTION_SHEETS', 'E-Commerce Action Sheets', 'Order ids, Qty Received and Qty Issue CN per platform; Accounts issues the credit note',
   'STEP', 'ecom-action-sheets', 'ecom-action-sheet', 'ECOM_ACTION_SHEETS', null, 'ecommerce_accounts', 'view', 17, 'DEC-76')
on conflict (code) do nothing;

