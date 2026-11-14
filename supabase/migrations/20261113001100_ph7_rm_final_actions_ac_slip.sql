-- Change plan 2026-11-12 · Phase 7 — RM Final Actions & "Replacement Slip – A/c Actions" PDF
-- (docs/RMS_MASTER_PLAN_ADDENDUM_2026-11.md AMD-16, AMD-17; DEC-41, DEC-45, DEC-46; G-18, G-20;
--  new guard G-21).
--
-- 1. G-20 fix-forward (20261113000900 / 001000 are applied and never edited, rule d): pieces the RM
--    has actioned are drawn from the outcome heads first, then from the store. The old formula
--    subtracted outcome heads AND actioned, so actioning a piece that came back from a department
--    counted it twice (10 counted, 5 repaired, 10 actioned => in_store -5). Identity unchanged:
--      counted = in_store + at_departments + outcome_heads (not yet actioned) + actioned.
-- 2. G-21 (AMD-16): per item of a GS on the AMD-13 flow,
--      Σ current RM final action qty = qty available for action = counted - at_departments,
--    every action code is in the product's resolved ACTION profile (Phase 4, GS profile version),
--    actions change only while the GS is HELD_AT_INTERMEDIATE_STORE and never while a CURRENT
--    A/c Actions slip exists (revising supersedes the slip first, with a reason). Finalising needs
--    nothing at a department, so the actions then cover the full counted qty.
-- 3. ac_action_slips (AMD-17): the finalised "Replacement Slip – A/c Actions", one row per version,
--    insert-only apart from CURRENT -> SUPERSEDED; the PDF is an attachment (kind GENERATED_PDF).
-- 4. Config: print template AC_ACTIONS_SLIP v1 (branding / layout, DEC-41), number series
--    AC_ACTION_SLIP, notification events AC_ACTIONS_SLIP_READY / AC_ACTIONS_SLIP_SUPERSEDED (rules
--    naming ACCOUNTS live in seed.sql because roles are seed data), permissions `final_actions`.
-- Messages carry "G-20" / "G-21" so the API maps them to the standard 409 guard envelope.

-- ===========================================================================
-- 1. G-20 fix-forward: actioned pieces come out of the outcome heads first
-- ===========================================================================
create or replace function rms_private.validate_department_reconciliation(p_gs_id uuid)
returns void
language plpgsql
set search_path = ''
as $$
declare
  v_item          record;
  v_at_dept       integer;
  v_outcomes      integer;
  v_outcome_open  integer;
  v_actioned      integer;
  v_in_store      integer;
begin
  for v_item in
    select id, line_no, coalesce(product_name_snapshot, 'Item') as item_name, received_qty
      from public.gs_items
     where gs_id = p_gs_id
     order by line_no asc
  loop
    select coalesce(sum(rl.qty_sent - rl.qty_received), 0)
      into v_at_dept
      from public.department_routing_lines rl
      join public.department_routings r on r.id = rl.routing_id
     where rl.gs_item_id = v_item.id
       and r.status in ('DISPATCHED', 'PARTIALLY_RECEIVED');

    select coalesce(sum(rcl.quantity), 0)
      into v_outcomes
      from public.department_receipt_lines rcl
      join public.department_routing_lines rl on rl.id = rcl.routing_line_id
     where rl.gs_item_id = v_item.id
       and not rcl.returns_to_routing;

    select coalesce(sum(act.qty), 0)
      into v_actioned
      from public.rm_item_actions act
     where act.gs_item_id = v_item.id
       and act.is_current = true;

    -- AMD-16: an RM final action covers a piece wherever it waits (outcome head first, then store).
    v_outcome_open := greatest(v_outcomes - v_actioned, 0);
    v_in_store := v_item.received_qty - v_at_dept - v_outcome_open - v_actioned;

    if v_in_store < 0 then
      raise exception 'G-20: Quantity conservation violation for item line % (%): counted (%) < at_departments (%) + outcome_heads (%) + actioned (%). Available store quantity cannot be negative (%)',
        v_item.line_no, v_item.item_name, v_item.received_qty, v_at_dept, v_outcome_open, v_actioned, v_in_store
        using errcode = 'P0001';
    end if;
  end loop;
end;
$$;
revoke all on function rms_private.validate_department_reconciliation(uuid) from public, anon, authenticated;
grant execute on function rms_private.validate_department_reconciliation(uuid) to rms_api;

-- ===========================================================================
-- 2. G-21: RM final action split
-- ===========================================================================
-- A GS is on the AMD-13 flow once the RM approved categorisation (transfer slip) or it is held at
-- the intermediate store. Older GS keep the P2-07 rules (inspection-based RM actions).
create or replace function rms_private.gs_on_final_action_flow(p_gs_id uuid)
returns boolean
language sql
stable
set search_path = ''
as $$
  select exists (
    select 1 from public.goods_slips gs
     where gs.id = p_gs_id
       and (gs.transfer_slip_id is not null or gs.status = 'HELD_AT_INTERMEDIATE_STORE')
  );
$$;
revoke all on function rms_private.gs_on_final_action_flow(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_on_final_action_flow(uuid) to rms_api;

-- Per item: counted, at departments, available for action (= counted - at departments), actioned.
create or replace function rms_private.final_action_item_quantities(p_gs_id uuid)
returns table (
  gs_item_id     uuid,
  line_no        integer,
  item_name      text,
  product_id     uuid,
  counted_qty    integer,
  at_dept_qty    integer,
  available_qty  integer,
  actioned_qty   integer
)
language sql
stable
set search_path = ''
as $$
  select gi.id, gi.line_no, coalesce(gi.product_name_snapshot, 'Item'), gi.product_id,
         gi.received_qty,
         coalesce(d.at_dept, 0)::integer,
         (gi.received_qty - coalesce(d.at_dept, 0))::integer,
         coalesce(a.actioned, 0)::integer
    from public.gs_items gi
    left join lateral (
      select sum(rl.qty_sent - rl.qty_received) as at_dept
        from public.department_routing_lines rl
        join public.department_routings r on r.id = rl.routing_id
       where rl.gs_item_id = gi.id
         and r.status in ('DISPATCHED', 'PARTIALLY_RECEIVED')
    ) d on true
    left join lateral (
      select sum(act.qty) as actioned
        from public.rm_item_actions act
       where act.gs_item_id = gi.id and act.is_current
    ) a on true
   where gi.gs_id = p_gs_id
   order by gi.line_no;
$$;
revoke all on function rms_private.final_action_item_quantities(uuid) from public, anon, authenticated;
grant execute on function rms_private.final_action_item_quantities(uuid) to rms_api;

-- The whole-GS check. p_complete = true is the finalise check: nothing may be at a department and
-- at least one revision must exist, so the actions cover the full counted quantity.
create or replace function rms_private.validate_final_action_split(
  p_gs_id     uuid,
  p_complete  boolean default false
)
returns void
language plpgsql
stable
set search_path = ''
as $$
declare
  v_item     record;
  v_version  uuid;
  v_bad      record;
begin
  select item_field_profile_version_id into v_version from public.goods_slips where id = p_gs_id;

  if p_complete and not exists (
    select 1 from public.rm_item_actions act
      join public.gs_items gi on gi.id = act.gs_item_id
     where gi.gs_id = p_gs_id
  ) then
    raise exception 'G-21: no RM final actions have been saved for this goods slip'
      using errcode = 'P0001';
  end if;

  for v_item in select * from rms_private.final_action_item_quantities(p_gs_id) loop
    if p_complete and v_item.at_dept_qty > 0 then
      raise exception 'G-21: item line % (%) still has % pc(s) at a department; receive them back before finalising',
        v_item.line_no, v_item.item_name, v_item.at_dept_qty
        using errcode = 'P0001';
    end if;
    if v_item.actioned_qty <> v_item.available_qty then
      raise exception 'G-21: item line % (%): action qty total (%) must equal the qty available for action (%) = counted (%) - at departments (%)',
        v_item.line_no, v_item.item_name, v_item.actioned_qty, v_item.available_qty,
        v_item.counted_qty, v_item.at_dept_qty
        using errcode = 'P0001';
    end if;
  end loop;

  -- Every current action must be allowed by the product's resolved ACTION profile (AMD-10/16),
  -- resolved under the profile version the GS was categorised with (G-18; live if none stamped).
  select gi.line_no, act.action_code into v_bad
    from public.rm_item_actions act
    join public.gs_items gi on gi.id = act.gs_item_id
   where gi.gs_id = p_gs_id
     and act.is_current
     and not exists (
       select 1 from rms_private.resolve_item_field_profile(gi.product_id, v_version) r
        where r.field_group = 'ACTION' and r.code = act.action_code
     )
   limit 1;
  if found then
    raise exception 'G-21: action % is not allowed by the resolved profile of item line %',
      v_bad.action_code, v_bad.line_no
      using errcode = 'P0001';
  end if;
end;
$$;
revoke all on function rms_private.validate_final_action_split(uuid, boolean) from public, anon, authenticated;
grant execute on function rms_private.validate_final_action_split(uuid, boolean) to rms_api;

-- Immediate guard on every RM action row of an AMD-13 GS.
create or replace function rms_private.rm_item_actions_final_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_gs_id    uuid;
  v_status   text;
  v_version  uuid;
  v_product  uuid;
  v_slip     record;
begin
  select gi.gs_id, gi.product_id into v_gs_id, v_product
    from public.gs_items gi where gi.id = new.gs_item_id;
  if v_gs_id is null or not rms_private.gs_on_final_action_flow(v_gs_id) then
    return new;  -- P2-07 flow: unchanged
  end if;

  -- Serialise with department dispatches / receipts and other revisions of this GS (G-20 / G-21).
  select status, item_field_profile_version_id into v_status, v_version
    from public.goods_slips where id = v_gs_id for update;

  if v_status is distinct from 'HELD_AT_INTERMEDIATE_STORE' then
    raise exception 'G-21: RM final actions change only while the goods slip is held at the intermediate store (status %)',
      v_status using errcode = 'P0001';
  end if;

  select slip_no, version_no into v_slip
    from public.ac_action_slips where gs_id = v_gs_id and status = 'CURRENT';
  if found then
    raise exception 'G-21: final actions are finalised on slip % v%; revise with a reason to supersede it first',
      v_slip.slip_no, v_slip.version_no using errcode = 'P0001';
  end if;

  if tg_op = 'INSERT' and new.is_current and not exists (
    select 1 from rms_private.resolve_item_field_profile(v_product, v_version) r
     where r.field_group = 'ACTION' and r.code = new.action_code
  ) then
    raise exception 'G-21: action % is not allowed by the resolved profile of this product',
      new.action_code using errcode = 'P0001';
  end if;
  return new;
end;
$$;
revoke all on function rms_private.rm_item_actions_final_guard() from public, anon, authenticated;

create trigger rm_item_actions_final_guard
  before insert or update on public.rm_item_actions
  for each row execute function rms_private.rm_item_actions_final_guard();

-- Deferred whole-GS check at commit (a revision writes several rows; the sum is checked at the end).
create or replace function rms_private.rm_item_actions_g21_deferred()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_gs_id uuid;
begin
  select gi.gs_id into v_gs_id from public.gs_items gi where gi.id = new.gs_item_id;
  if v_gs_id is not null and rms_private.gs_on_final_action_flow(v_gs_id) then
    perform rms_private.validate_final_action_split(v_gs_id, false);
    perform rms_private.validate_department_reconciliation(v_gs_id);
  end if;
  return null;
end;
$$;
revoke all on function rms_private.rm_item_actions_g21_deferred() from public, anon, authenticated;

create constraint trigger rm_item_actions_g21
  after insert or update on public.rm_item_actions
  deferrable initially deferred
  for each row execute function rms_private.rm_item_actions_g21_deferred();

-- ===========================================================================
-- 3. Generated PDFs are attachments (kind GENERATED_PDF, application/pdf, rms-documents)
-- ===========================================================================
alter table public.attachments drop constraint attachments_kind_check;
alter table public.attachments drop constraint attachments_mime_for_kind;
alter table public.attachments
  add constraint attachments_kind_check check (
    kind in ('UNBOXING_VIDEO', 'DOC_PHOTO', 'PARCEL_PHOTO', 'NOTIFICATION_PROOF', 'GATE_DOC',
             'GENERATED_PDF', 'OTHER')),
  add constraint attachments_mime_for_kind check (
    (kind = 'UNBOXING_VIDEO' and mime_type in ('video/mp4', 'video/quicktime'))
    or (kind in ('DOC_PHOTO', 'GATE_DOC') and mime_type in ('image/jpeg', 'image/png', 'image/heic', 'image/heif', 'application/pdf'))
    or (kind = 'PARCEL_PHOTO' and mime_type in ('image/jpeg', 'image/png', 'image/heic', 'image/heif'))
    or (kind = 'GENERATED_PDF' and mime_type = 'application/pdf')
    or kind in ('NOTIFICATION_PROOF', 'OTHER'));

-- ===========================================================================
-- 4. ac_action_slips (AMD-17)
-- ===========================================================================
create table public.ac_action_slips (
  id                   uuid primary key default gen_random_uuid(),
  gs_id                uuid not null references public.goods_slips (id) on delete restrict,
  slip_no              text not null check (btrim(slip_no) <> ''),
  version_no           integer not null check (version_no > 0),
  revision_no          integer not null check (revision_no > 0),
  status               text not null default 'CURRENT' check (status in ('CURRENT', 'SUPERSEDED')),
  attachment_id        uuid not null unique references public.attachments (id) on delete restrict,
  template_code        text not null default 'AC_ACTIONS_SLIP',
  template_version_no  integer not null check (template_version_no > 0),
  content              jsonb not null,
  totals               jsonb not null,
  sha256               text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  remarks              text,
  finalised_by         uuid not null default rms_private.current_actor() references public.profiles (id) on delete restrict,
  finalised_at         timestamptz not null default now(),
  superseded_at        timestamptz,
  superseded_by        uuid references public.profiles (id) on delete restrict,
  supersede_reason     text,
  unique (gs_id, version_no),
  unique (slip_no, version_no),
  constraint ac_action_slips_superseded_fields check (
    (status = 'CURRENT' and superseded_at is null and superseded_by is null and supersede_reason is null)
    or (status = 'SUPERSEDED' and superseded_at is not null and superseded_by is not null
        and btrim(coalesce(supersede_reason, '')) <> ''))
);
create unique index ac_action_slips_one_current_idx on public.ac_action_slips (gs_id) where status = 'CURRENT';
create index ac_action_slips_finalised_by_idx on public.ac_action_slips (finalised_by);
create index ac_action_slips_superseded_by_idx on public.ac_action_slips (superseded_by);

comment on table public.ac_action_slips is
  'AMD-17: finalised "Replacement Slip – A/c Actions" versions. content = the exact data rendered into the stored PDF (G-18 snapshot). Insert-only apart from CURRENT -> SUPERSEDED.';

create or replace function rms_private.ac_action_slips_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_status    text;
  v_prev      record;
  v_max_rev   integer;
  v_att       record;
begin
  if tg_op = 'DELETE' then
    raise exception 'G-21: A/c Actions slips are never deleted (slip % v%)', old.slip_no, old.version_no
      using errcode = '42501';
  end if;

  if tg_op = 'UPDATE' then
    if old.status <> 'CURRENT' or new.status <> 'SUPERSEDED'
       or (to_jsonb(new) - array['status', 'superseded_at', 'superseded_by', 'supersede_reason'])
          <> (to_jsonb(old) - array['status', 'superseded_at', 'superseded_by', 'supersede_reason']) then
      raise exception 'G-21: an A/c Actions slip is immutable; the only change is CURRENT -> SUPERSEDED'
        using errcode = '42501';
    end if;
    return new;
  end if;

  -- INSERT = finalise.
  select status into v_status from public.goods_slips where id = new.gs_id for update;
  if v_status is distinct from 'HELD_AT_INTERMEDIATE_STORE' then
    raise exception 'G-21: final actions are finalised only while the goods slip is held at the intermediate store (status %)',
      coalesce(v_status, 'missing') using errcode = 'P0001';
  end if;

  perform rms_private.validate_final_action_split(new.gs_id, true);

  select coalesce(max(act.revision_no), 0) into v_max_rev
    from public.rm_item_actions act
    join public.gs_items gi on gi.id = act.gs_item_id
   where gi.gs_id = new.gs_id;
  if new.revision_no <> v_max_rev then
    raise exception 'G-21: the slip must capture the latest action revision (%), not %', v_max_rev, new.revision_no
      using errcode = 'P0001';
  end if;

  select slip_no, version_no into v_prev
    from public.ac_action_slips where gs_id = new.gs_id order by version_no desc limit 1;
  if found then
    if new.slip_no <> v_prev.slip_no or new.version_no <> v_prev.version_no + 1 then
      raise exception 'G-21: the next slip version of this goods slip is % v%', v_prev.slip_no, v_prev.version_no + 1
        using errcode = 'P0001';
    end if;
  elsif new.version_no <> 1
        or exists (select 1 from public.ac_action_slips s where s.slip_no = new.slip_no) then
    raise exception 'G-21: the first slip of a goods slip is version 1 with a new slip number'
      using errcode = 'P0001';
  end if;

  select gs_id, kind, status, mime_type into v_att from public.attachments where id = new.attachment_id;
  if not found or v_att.gs_id <> new.gs_id or v_att.kind <> 'GENERATED_PDF'
     or v_att.status <> 'CONFIRMED' or v_att.mime_type <> 'application/pdf' then
    raise exception 'G-21: the slip PDF must be a confirmed GENERATED_PDF attachment of the same goods slip'
      using errcode = 'P0001';
  end if;

  new.status := 'CURRENT';
  new.superseded_at := null;
  new.superseded_by := null;
  new.supersede_reason := null;
  return new;
end;
$$;
revoke all on function rms_private.ac_action_slips_guard() from public, anon, authenticated;

create trigger ac_action_slips_guard
  before insert or update or delete on public.ac_action_slips
  for each row execute function rms_private.ac_action_slips_guard();

create trigger audit_row
  after insert or update or delete on public.ac_action_slips
  for each row execute function rms_private.audit_row();

alter table public.ac_action_slips enable row level security;
create policy ac_action_slips_api_all on public.ac_action_slips
  for all to rms_api using (true) with check (true);
revoke all on public.ac_action_slips from anon, authenticated;
revoke delete, truncate on public.ac_action_slips from rms_api;

-- ===========================================================================
-- 5. Config: print template, number series, notifications, permissions, guard events
-- ===========================================================================
alter table public.print_templates drop constraint print_templates_code_check;
alter table public.print_templates
  add constraint print_templates_code_check check (
    code in ('REPLACEMENT_SLIP', 'GS_TAG', 'CN_SUMMARY', 'TRANSFER_NOTE', 'STORE_ISSUE', 'AC_ACTIONS_SLIP'));

-- DEC-41: one server-side template per slip. Branding (company line, titles, footer, signature
-- blocks, paper) is configuration; admins publish a new version from Admin -> Print Templates.
do $$
declare
  v_layout jsonb := jsonb_build_object(
    'paper_size', 'A4',
    'orientation', 'portrait',
    'show_logo', false,
    'header_title', 'HICKS THERMOMETERS (INDIA) LIMITED',
    'header_subtitle', 'Replacement Slip – A/c Actions',
    'footer_text', 'Computer generated by RMS. Accounts record CN / Challan details against each action line.',
    'sections', jsonb_build_array(
      jsonb_build_object('id', 'gs_header', 'title', 'Goods Slip',
        'fields', jsonb_build_array('gs_no', 'gs_date', 'return_type', 'carton_count', 'slip_no', 'version_no')),
      jsonb_build_object('id', 'party', 'title', 'Party',
        'fields', jsonb_build_array('party_name', 'party_code', 'state_station')),
      jsonb_build_object('id', 'gate_entry', 'title', 'Gate Entry',
        'fields', jsonb_build_array('gate_entry_no', 'gate_entry_date', 'gate_documents')),
      jsonb_build_object('id', 'items', 'title', 'Item × Action × Qty',
        'fields', jsonb_build_array('line_no', 'product_code', 'product_name', 'counted_qty', 'action_label', 'qty')),
      jsonb_build_object('id', 'totals', 'title', 'Totals by Action',
        'fields', jsonb_build_array('action_label', 'qty')),
      jsonb_build_object('id', 'signatures', 'title', 'Signatures',
        'fields', jsonb_build_array('signature_blocks'))
    ),
    'signature_blocks', jsonb_build_array(
      jsonb_build_object('label', 'Prepared By', 'role', 'Replacement Manager'),
      jsonb_build_object('label', 'Received By', 'role', 'Accounts')
    )
  );
begin
  if not exists (select 1 from public.print_templates where code = 'AC_ACTIONS_SLIP') then
    insert into public.print_templates (code, name, version_no, layout, status, snapshot, published_at)
    values ('AC_ACTIONS_SLIP', 'Replacement Slip – A/c Actions', 1, v_layout, 'PUBLISHED', v_layout, now());
  end if;
end
$$;

insert into public.number_series (code, name, prefix, pattern, reset_policy, fy_start_month, fy_format)
values ('AC_ACTION_SLIP', 'Replacement Slip – A/c Actions', 'RSA', '{PREFIX}/{FY}/{SEQ:5}', 'YEARLY_FY', 4, 'LONG')
on conflict (code) do nothing;

insert into public.notification_event_types
  (code, label, description, category, default_priority, is_mandatory, source_ref, sort_order)
values
  ('AC_ACTIONS_SLIP_READY', 'A/c Actions slip ready',
   'The Replacement Manager finalised the item actions of a goods slip; the "Replacement Slip – A/c Actions" PDF is ready for Accounts (AMD-17).',
   'COMMERCIAL', 'HIGH', false, 'AMD-17', 510),
  ('AC_ACTIONS_SLIP_SUPERSEDED', 'A/c Actions slip superseded',
   'The Replacement Manager revised finalised item actions; the previous A/c Actions slip version is superseded (AMD-16).',
   'COMMERCIAL', 'HIGH', false, 'AMD-16', 520)
on conflict (code) do nothing;

insert into public.notification_templates (event_type, channel, version_no, subject, body, change_reason)
select v.event_type, 'EMAIL', 1,
       '[{app_name}] {title}',
       E'Hello {recipient_name},\n\n{title}\n\n{body}\n\nEvent: {event_label}\nPriority: {priority}\nOpen in RMS: {link}\n\n— {app_name} (automated message; manage email preferences in RMS)',
       'Phase 7 default'
  from (values ('AC_ACTIONS_SLIP_READY'), ('AC_ACTIONS_SLIP_SUPERSEDED')) as v(event_type)
 where not exists (
   select 1 from public.notification_templates where event_type = v.event_type and channel = 'EMAIL'
 );

-- Role grants are in seed.sql (_seed_role_matrix): roles are seed data and do not exist yet when
-- the migrations run on a fresh `supabase db reset`.
insert into public.permissions (module_code, action, description)
values
  ('final_actions', 'view',    'View RM final actions and A/c Actions slips'),
  ('final_actions', 'edit',    'Split item qty across final actions (RM)'),
  ('final_actions', 'approve', 'Finalise final actions and generate the A/c Actions slip (RM)'),
  ('final_actions', 'export',  'Print / download the A/c Actions slip PDF')
on conflict (module_code, action) do nothing;

alter table public.system_guard_events
  drop constraint if exists system_guard_events_guard_code_check;
alter table public.system_guard_events
  add constraint system_guard_events_guard_code_check
  check (guard_code ~ '^G-(0[1-9]|1[0-9]|2[01])$');
