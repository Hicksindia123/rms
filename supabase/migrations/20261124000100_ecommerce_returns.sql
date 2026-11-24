-- =============================================================================================
-- E-Commerce Return gate entry + platform ticket (DEC-73; user answers 2026-11-24).
--
-- Return Type = E-Commerce at Gate Entry no longer creates an offline goods slip (DEC-39 path,
-- replaced in the UI). It creates an **E-Commerce Return** in its own tables, numbered by its own
-- Admin-editable series ECOM_RETURN (default ECR/{FY}/{SEQ:5}). The offline goods_slips tables,
-- statuses, queues and guards are not touched.
--
-- Lifecycle (status), enforced here AND in backend/app/modules/ecommerce_returns/service.py:
--   DRAFT            created; media declared, files being uploaded. Leaves DRAFT only with a
--                    CONFIRMED package-opening video (mandatory) and no image still uploading.
--   IN_CHECKING      qc_routing = ISSUE_TO_CHECKING. OPEN. EXTENSION POINT: the Checking
--                    Department process is not defined yet; it adds its exits from IN_CHECKING
--                    in a later migration (ecommerce_returns_guard, branch "IN_CHECKING").
--   PENDING_TICKET   qc_routing = TICKET_RAISE; an ecommerce_tickets row is queued for the Ticket
--                    Handlers with sla_due_at = queued time + setting ecommerce_ticket_sla_hours (2).
--   TICKET_RAISED    a Ticket Handler raised the ticket on the platform (raised_at).
--   CLOSED           the ticket was closed with a final response: REJECTED (remark required) or
--                    CLAIM_RECEIVED (claim amount required). Never while the response is PENDING.
--   VOIDED           Super Admin / Management (ecommerce_returns.delete), reason required, any
--                    time before CLOSED.
-- The return's status follows its ticket: the ticket trigger moves it (raise → TICKET_RAISED,
-- close → CLOSED), so the two can never disagree.
--
-- 1. Permissions (ecommerce_returns view/create/delete, ecommerce_tickets view/edit).
-- 2. Number series ECOM_RETURN.
-- 3. Option sets (labels are configuration; logic keys off the codes): ECOM_PLATFORM (Admin may add
--    platforms), ECOM_PRODUCT_TYPE, ECOM_QC_ROUTING, ECOM_TICKET_RESPONSE.
-- 4. Settings: ticket SLA hours, image total cap, order id pattern.
-- 5. Tables ecommerce_returns, ecommerce_return_media, ecommerce_tickets, ecommerce_return_events.
-- 6. Guards (triggers). 7. RLS / grants / audit (G-17). 8. Journey catalogue (menus: seed + snippet).
-- Roles ECOM_GATE / TICKET_HANDLER and their grants are seed data (seed.sql + release snippet).
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- 1. Permissions
-- ---------------------------------------------------------------------------------------------
insert into public.permissions (module_code, action, description)
values
  ('ecommerce_returns', 'view',   'See E-Commerce Returns (DEC-73)'),
  ('ecommerce_returns', 'create', 'Record an E-Commerce Return at Gate Entry (DEC-73)'),
  ('ecommerce_returns', 'delete', 'Void an E-Commerce Return with a reason before it is closed (DEC-73)'),
  ('ecommerce_tickets', 'view',   'See the E-Commerce platform ticket queue (DEC-73)'),
  ('ecommerce_tickets', 'edit',   'Raise, answer and close E-Commerce platform tickets (Ticket Handler, DEC-73)')
on conflict (module_code, action) do nothing;

insert into public.role_permissions (role_id, permission_id, scope)
select r.id, p.id, 'all'
  from public.roles r
  join public.permissions p on p.module_code in ('ecommerce_returns', 'ecommerce_tickets')
 where r.code = 'SUPER_ADMIN'
on conflict (role_id, permission_id) do nothing;

-- ---------------------------------------------------------------------------------------------
-- 2. Number series (pattern / prefix editable in Admin → Numbering)
-- ---------------------------------------------------------------------------------------------
insert into public.number_series (code, name, prefix, pattern, reset_policy, fy_start_month, fy_format)
values ('ECOM_RETURN', 'E-Commerce Return', 'ECR', '{PREFIX}/{FY}/{SEQ:5}', 'YEARLY_FY', 4, 'LONG')
on conflict (code) do nothing;

-- ---------------------------------------------------------------------------------------------
-- 3. Option sets
-- ---------------------------------------------------------------------------------------------
insert into public.option_sets (code, name, description, control_type, source_kind, master_ref_type, source_ref, is_system)
values
  ('ECOM_PLATFORM', 'Platform', 'E-Commerce Return · Gate Entry · the marketplace / channel of the order. Admin may add platforms.', 'dropdown', 'STATIC', null, 'DEC-73', true),
  ('ECOM_PRODUCT_TYPE', 'Product Type', 'E-Commerce Return · Gate Entry · our product, or a different item found in the packet.', 'radio', 'STATIC', null, 'DEC-73', true),
  ('ECOM_QC_ROUTING', 'QC Status', 'E-Commerce Return · Gate Entry · raise a platform ticket, or issue to the Checking Department.', 'radio', 'STATIC', null, 'DEC-73', true),
  ('ECOM_TICKET_RESPONSE', 'Platform Response', 'E-Commerce Return · Ticket Handler · the platform''s answer to the ticket.', 'radio', 'STATIC', null, 'DEC-73', true),
  ('ECOM_RETURN_STATUS', 'E-Commerce Return Status', 'E-Commerce Return · status labels (the codes are the lifecycle; only the labels are editable).', 'dropdown', 'STATIC', null, 'DEC-73', true)
on conflict (code) do nothing;

insert into public.option_items (option_set_id, code, label, allowed_status, rule_text, next_action_text,
                                 remarks, system_behavior, required_fields, sort_order, source_ref)
select os.id, v.code, v.label, 'YES', v.rule_text, null, null, null, v.required_fields::jsonb, v.sort_order, 'DEC-73'
  from (values
    ('ECOM_PLATFORM', 'AMAZON', 'Amazon', null, '[]', 10),
    ('ECOM_PLATFORM', 'FLIPKART', 'Flipkart', null, '[]', 20),
    ('ECOM_PLATFORM', 'WEBSITE', 'Website', null, '[]', 30),
    ('ECOM_PRODUCT_TYPE', 'COMPANY_PRODUCT', 'Company Product', 'Pick the product from the product master', '["product_id"]', 10),
    ('ECOM_PRODUCT_TYPE', 'DIFFERENT_PRODUCT', 'Different Product', 'Describe the item found in the packet', '["different_product_desc"]', 20),
    ('ECOM_QC_ROUTING', 'TICKET_RAISE', 'Ticket Raise', 'A Ticket Handler raises a ticket on the platform within the SLA', '[]', 10),
    ('ECOM_QC_ROUTING', 'ISSUE_TO_CHECKING', 'Issue to Checking Department', 'Goes to the Checking Department (process to be defined)', '[]', 20),
    ('ECOM_TICKET_RESPONSE', 'REJECTED', 'Rejected', 'Remark required', '["rejection_remark"]', 10),
    ('ECOM_TICKET_RESPONSE', 'CLAIM_RECEIVED', 'Claim Received', 'Claim amount required', '["claim_amount"]', 20),
    ('ECOM_TICKET_RESPONSE', 'PENDING', 'Pending', 'Stays open; update it later', '[]', 30),
    ('ECOM_RETURN_STATUS', 'DRAFT', 'Upload Pending', 'Created; the package opening video is not uploaded yet', '[]', 10),
    ('ECOM_RETURN_STATUS', 'IN_CHECKING', 'In Checking', 'Issued to the Checking Department (open)', '[]', 20),
    ('ECOM_RETURN_STATUS', 'PENDING_TICKET', 'Ticket Pending', 'Waiting for a Ticket Handler to raise the platform ticket', '[]', 30),
    ('ECOM_RETURN_STATUS', 'TICKET_RAISED', 'Ticket Raised', 'Raised on the platform; waiting for the final response', '[]', 40),
    ('ECOM_RETURN_STATUS', 'CLOSED', 'Closed', 'Ticket closed with a final response', '[]', 50),
    ('ECOM_RETURN_STATUS', 'VOIDED', 'Voided', 'Voided with a reason', '[]', 60)
  ) as v(set_code, code, label, rule_text, required_fields, sort_order)
  join public.option_sets os on os.code = v.set_code
on conflict (option_set_id, code) do nothing;

-- ---------------------------------------------------------------------------------------------
-- 4. Settings (Admin → Settings)
-- ---------------------------------------------------------------------------------------------
insert into public.system_settings (key, value, category, description, source_ref) values
  ('ecommerce_ticket_sla_hours', '2'::jsonb, 'ecommerce',
   'Hours a Ticket Handler has to raise the platform ticket of an E-Commerce Return (SLA; the queue flags OVERDUE after it).', 'DEC-73'),
  ('ecommerce_images_max_total_bytes', '52428800'::jsonb, 'uploads',
   'Combined size limit of the optional images of one E-Commerce Return (50 MB). Each image also obeys upload_max_document_bytes.', 'DEC-73'),
  ('ecommerce_order_id_pattern', '"^[A-Za-z0-9-]{3,40}$"'::jsonb, 'ecommerce',
   'Regular expression an E-Commerce Order ID must match (letters, digits; hyphen allowed because Amazon order ids contain hyphens).', 'DEC-73')
on conflict (key) do nothing;

-- Positive whole-number setting, or the default when missing / invalid (a guard never weakens).
create or replace function rms_private.ecom_int_setting(p_key text, p_default bigint)
returns bigint
language sql
stable
set search_path = ''
as $$
  select coalesce(
           (select (s.value #>> '{}')::bigint
              from public.system_settings s
             where s.key = p_key and jsonb_typeof(s.value) = 'number' and (s.value #>> '{}')::numeric > 0
                   and (s.value #>> '{}')::numeric = trunc((s.value #>> '{}')::numeric)),
           p_default)
$$;
revoke all on function rms_private.ecom_int_setting(text, bigint) from public, anon, authenticated;
grant execute on function rms_private.ecom_int_setting(text, bigint) to rms_api;

-- ---------------------------------------------------------------------------------------------
-- 5. Tables
-- ---------------------------------------------------------------------------------------------
create table public.ecommerce_returns (
  id                      uuid primary key default gen_random_uuid(),
  return_no               text not null unique check (btrim(return_no) <> ''),
  entry_date              date not null,
  platform_code           text not null check (platform_code ~ '^[A-Z][A-Z0-9_]*$'),
  platform_label          text not null check (btrim(platform_label) <> ''),          -- G-18 snapshot
  order_id                text not null check (order_id = btrim(order_id) and order_id <> '' and length(order_id) <= 60),
  product_type_code       text not null check (product_type_code in ('COMPANY_PRODUCT', 'DIFFERENT_PRODUCT')),
  product_type_label      text not null check (btrim(product_type_label) <> ''),
  product_id              uuid references public.products (id) on delete restrict,
  product_code_snapshot   text,
  product_name_snapshot   text,
  different_product_desc  text check (different_product_desc is null
                                      or (btrim(different_product_desc) <> '' and length(different_product_desc) <= 500)),
  qty                     integer not null check (qty >= 1),
  qc_routing_code         text not null check (qc_routing_code in ('TICKET_RAISE', 'ISSUE_TO_CHECKING')),
  qc_routing_label        text not null check (btrim(qc_routing_label) <> ''),
  status                  text not null default 'DRAFT' check (status in (
                            'DRAFT', 'IN_CHECKING', 'PENDING_TICKET', 'TICKET_RAISED', 'CLOSED', 'VOIDED')),
  submitted_at            timestamptz,
  submitted_by            uuid references public.profiles (id) on delete restrict,
  void_reason             text,
  voided_at               timestamptz,
  voided_by               uuid references public.profiles (id) on delete restrict,
  closed_at               timestamptz,
  created_at              timestamptz not null default now(),
  created_by              uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at              timestamptz not null default now(),
  -- Product type drives exactly one of the two product fields.
  constraint ecommerce_returns_product_shape check (
    (product_type_code = 'COMPANY_PRODUCT' and product_id is not null and different_product_desc is null
       and product_code_snapshot is not null and product_name_snapshot is not null)
    or (product_type_code = 'DIFFERENT_PRODUCT' and product_id is null and different_product_desc is not null
       and product_code_snapshot is null and product_name_snapshot is null)),
  constraint ecommerce_returns_submitted_shape check ((status = 'DRAFT') = (submitted_at is null)
                                                      or status = 'VOIDED'),
  constraint ecommerce_returns_void_shape check (
    (status = 'VOIDED') = (voided_at is not null)
    and (status <> 'VOIDED' or (voided_by is not null and length(btrim(coalesce(void_reason, ''))) >= 3))),
  constraint ecommerce_returns_closed_shape check ((status = 'CLOSED') = (closed_at is not null)),
  constraint ecommerce_returns_routing_status check (
    status in ('DRAFT', 'VOIDED', 'CLOSED')
    or (qc_routing_code = 'ISSUE_TO_CHECKING' and status = 'IN_CHECKING')
    or (qc_routing_code = 'TICKET_RAISE' and status in ('PENDING_TICKET', 'TICKET_RAISED'))),
  constraint ecommerce_returns_closed_route check (status <> 'CLOSED' or qc_routing_code = 'TICKET_RAISE')
);
create index ecommerce_returns_order_idx on public.ecommerce_returns (order_id);
create index ecommerce_returns_platform_order_idx on public.ecommerce_returns (platform_code, order_id);
create index ecommerce_returns_status_idx on public.ecommerce_returns (status);
create index ecommerce_returns_entry_date_idx on public.ecommerce_returns (entry_date desc);
create index ecommerce_returns_product_idx on public.ecommerce_returns (product_id);
create index ecommerce_returns_created_by_idx on public.ecommerce_returns (created_by);
comment on table public.ecommerce_returns is
  'DEC-73: an E-Commerce Return recorded at Gate Entry (own number series ECOM_RETURN). Status machine enforced by ecommerce_returns_guard; IN_CHECKING is the open extension point for the Checking Department.';

create table public.ecommerce_return_media (
  id            uuid primary key default gen_random_uuid(),
  return_id     uuid not null references public.ecommerce_returns (id) on delete restrict,
  kind          text not null check (kind in ('PACKAGE_VIDEO', 'IMAGE')),
  bucket        text not null check (bucket in ('rms-videos', 'rms-documents')),
  object_path   text not null unique check (object_path ~ '^ecom/[0-9a-f-]{36}/(package_video|image)/[0-9a-f-]{36}\.[a-z0-9]{1,8}$'),
  mime_type     text not null,
  size_bytes    bigint not null check (size_bytes > 0),
  file_name     text check (file_name is null or length(file_name) <= 255),
  status        text not null default 'PENDING_UPLOAD' check (status in ('PENDING_UPLOAD', 'CONFIRMED', 'REJECTED')),
  uploaded_by   uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  confirmed_at  timestamptz,
  created_at    timestamptz not null default now(),
  -- Allow-list mirror of backend app/modules/ecommerce_returns (videos: mp4 / mov; images: jpeg / png / heic).
  constraint ecommerce_return_media_mime check (
    (kind = 'PACKAGE_VIDEO' and bucket = 'rms-videos' and mime_type in ('video/mp4', 'video/quicktime'))
    or (kind = 'IMAGE' and bucket = 'rms-documents'
        and mime_type in ('image/jpeg', 'image/png', 'image/heic', 'image/heif'))),
  constraint ecommerce_return_media_confirmed check ((status = 'CONFIRMED') = (confirmed_at is not null))
);
create index ecommerce_return_media_return_idx on public.ecommerce_return_media (return_id);
-- One live package-opening video per return.
create unique index ecommerce_return_media_one_video
  on public.ecommerce_return_media (return_id) where kind = 'PACKAGE_VIDEO' and status <> 'REJECTED';
comment on table public.ecommerce_return_media is
  'DEC-73: package-opening video (mandatory, one) and optional images (combined size cap) of an E-Commerce Return; uploaded to signed URLs like the offline attachments.';

create table public.ecommerce_tickets (
  id                   uuid primary key default gen_random_uuid(),
  return_id            uuid not null unique references public.ecommerce_returns (id) on delete restrict,
  sla_due_at           timestamptz not null,
  -- DEC-51: no ownership lock. The ticket is queued for every Ticket Handler; the handler who raises
  -- it on the platform is recorded here.
  assigned_handler_id  uuid references public.profiles (id) on delete restrict,
  raised_at            timestamptz,
  response_code        text check (response_code in ('REJECTED', 'CLAIM_RECEIVED', 'PENDING')),
  response_label       text,
  rejection_remark     text,
  claim_amount         numeric(14, 2),
  responded_at         timestamptz,
  responded_by         uuid references public.profiles (id) on delete restrict,
  closed_at            timestamptz,
  closed_by            uuid references public.profiles (id) on delete restrict,
  created_at           timestamptz not null default now(),
  created_by           uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  updated_at           timestamptz not null default now(),
  constraint ecommerce_tickets_raised_shape check ((raised_at is null) = (assigned_handler_id is null)),
  constraint ecommerce_tickets_response_after_raise check (response_code is null or raised_at is not null),
  constraint ecommerce_tickets_response_shape check (
    (response_code is null) = (responded_at is null)
    and (response_code is null) = (response_label is null)),
  -- REJECTED → remark required; CLAIM_RECEIVED → claim amount required; nothing stray otherwise.
  constraint ecommerce_tickets_rejection_remark check (
    case when response_code = 'REJECTED' then length(btrim(coalesce(rejection_remark, ''))) >= 3
         else rejection_remark is null end),
  constraint ecommerce_tickets_claim_amount check (
    case when response_code = 'CLAIM_RECEIVED' then claim_amount is not null and claim_amount > 0
         else claim_amount is null end),
  -- Never closed while PENDING or unanswered.
  constraint ecommerce_tickets_close_needs_final_response check (
    closed_at is null or (response_code in ('REJECTED', 'CLAIM_RECEIVED') and closed_by is not null))
);
create index ecommerce_tickets_sla_due_idx on public.ecommerce_tickets (sla_due_at) where raised_at is null;
create index ecommerce_tickets_open_idx on public.ecommerce_tickets (created_at) where closed_at is null;
create index ecommerce_tickets_handler_idx on public.ecommerce_tickets (assigned_handler_id);
comment on table public.ecommerce_tickets is
  'DEC-73: the platform ticket of an E-Commerce Return routed TICKET_RAISE (SLA = queued + ecommerce_ticket_sla_hours). Closing requires a final response with its mandatory data.';

create table public.ecommerce_return_events (
  id           uuid primary key default gen_random_uuid(),
  return_id    uuid not null references public.ecommerce_returns (id) on delete restrict,
  event_code   text not null check (event_code ~ '^[A-Z][A-Z0-9_]*$'),
  from_status  text,
  to_status    text,
  details      jsonb not null default '{}'::jsonb check (jsonb_typeof(details) = 'object'),
  actor_id     uuid default rms_private.current_actor() references public.profiles (id) on delete restrict,
  created_at   timestamptz not null default now()
);
create index ecommerce_return_events_return_idx on public.ecommerce_return_events (return_id, created_at);
comment on table public.ecommerce_return_events is
  'DEC-73: append-only history of an E-Commerce Return (created, submitted, ticket raised / answered / closed, voided).';

-- ---------------------------------------------------------------------------------------------
-- 6. Guards
-- ---------------------------------------------------------------------------------------------

-- 6a. Return: insert shape, immutable fields, allowed transitions.
create or replace function rms_private.ecommerce_returns_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_actor   uuid := rms_private.current_actor();
  v_pattern text;
  v_ticket  public.ecommerce_tickets%rowtype;
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
       or new.closed_at is not null then
      raise exception 'ECOM_INVALID_STATE: an E-Commerce Return starts as DRAFT' using errcode = '23514';
    end if;
    if new.entry_date > rms_private.business_today() then
      raise exception 'ECOM_ENTRY_DATE_FUTURE: the entry date cannot be later than today' using errcode = '23514';
    end if;
    if not exists (select 1 from public.option_items oi join public.option_sets os on os.id = oi.option_set_id
                    where os.code = 'ECOM_PLATFORM' and oi.code = new.platform_code and oi.is_active) then
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

  if new.status = old.status then
    if (new.submitted_at, new.submitted_by, new.void_reason, new.voided_at, new.voided_by, new.closed_at)
       is distinct from
       (old.submitted_at, old.submitted_by, old.void_reason, old.voided_at, old.voided_by, old.closed_at) then
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

  if old.status = 'IN_CHECKING' then
    -- EXTENSION POINT (DEC-73): the Checking Department process adds its exits here.
    raise exception 'ECOM_INVALID_TRANSITION: the Checking Department step is not defined yet'
      using errcode = '23514';
  end if;

  -- Ticket route: the return follows its ticket.
  select * into v_ticket from public.ecommerce_tickets t where t.return_id = new.id;
  if old.status = 'PENDING_TICKET' and new.status = 'TICKET_RAISED' and v_ticket.raised_at is not null then
    return new;
  end if;
  if old.status = 'TICKET_RAISED' and new.status = 'CLOSED' and v_ticket.closed_at is not null then
    return new;
  end if;
  raise exception 'ECOM_INVALID_TRANSITION: % → % is not allowed', old.status, new.status using errcode = '23514';
end
$$;
revoke all on function rms_private.ecommerce_returns_guard() from public, anon, authenticated;
create trigger ecommerce_returns_guard
  before insert or update or delete on public.ecommerce_returns
  for each row execute function rms_private.ecommerce_returns_guard();

-- 6b. A return on the ticket route always has its ticket (checked at commit).
create or replace function rms_private.ecommerce_returns_ticket_present()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_status text;
begin
  select r.status into v_status from public.ecommerce_returns r where r.id = new.id;
  if v_status in ('PENDING_TICKET', 'TICKET_RAISED', 'CLOSED')
     and not exists (select 1 from public.ecommerce_tickets t where t.return_id = new.id) then
    raise exception 'ECOM_TICKET_MISSING: return % is on the ticket route without a ticket', new.id
      using errcode = '23514';
  end if;
  return null;
end
$$;
revoke all on function rms_private.ecommerce_returns_ticket_present() from public, anon, authenticated;
create constraint trigger ecommerce_returns_ticket_present
  after insert or update of status on public.ecommerce_returns
  deferrable initially deferred
  for each row execute function rms_private.ecommerce_returns_ticket_present();

-- 6c. Media: added only to a DRAFT, image total cap, status moves forward only, never deleted.
create or replace function rms_private.ecommerce_return_media_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_status text;
  v_total  bigint;
  v_cap    bigint;
begin
  if tg_op = 'DELETE' then
    raise exception 'ECOM_RETURN_IMMUTABLE: media rows are kept (a removed file is REJECTED)' using errcode = '42501';
  end if;
  select r.status into v_status from public.ecommerce_returns r where r.id = new.return_id for update;
  if tg_op = 'INSERT' then
    if v_status <> 'DRAFT' then
      raise exception 'ECOM_INVALID_STATE: files can only be added before the return is submitted'
        using errcode = '23514';
    end if;
    if not coalesce(rms_private.user_holds_permission(rms_private.current_actor(), 'ecommerce_returns', 'create'), false) then
      raise exception 'ECOM_FORBIDDEN: adding files needs ecommerce_returns.create' using errcode = '42501';
    end if;
    if new.status <> 'PENDING_UPLOAD' then
      raise exception 'ECOM_INVALID_STATE: a file starts as PENDING_UPLOAD' using errcode = '23514';
    end if;
    if new.kind = 'IMAGE' then
      v_cap := rms_private.ecom_int_setting('ecommerce_images_max_total_bytes', 52428800);
      select coalesce(sum(m.size_bytes), 0) into v_total from public.ecommerce_return_media m
       where m.return_id = new.return_id and m.kind = 'IMAGE' and m.status <> 'REJECTED';
      if v_total + new.size_bytes > v_cap then
        raise exception 'ECOM_IMAGES_TOO_LARGE: images total % bytes; the limit is % bytes', v_total + new.size_bytes, v_cap
          using errcode = '23514';
      end if;
    end if;
    return new;
  end if;
  if (new.id, new.return_id, new.kind, new.bucket, new.object_path, new.mime_type, new.size_bytes,
      new.file_name, new.uploaded_by, new.created_at)
     is distinct from
     (old.id, old.return_id, old.kind, old.bucket, old.object_path, old.mime_type, old.size_bytes,
      old.file_name, old.uploaded_by, old.created_at) then
    raise exception 'ECOM_RETURN_IMMUTABLE: a file row only changes its status' using errcode = '42501';
  end if;
  if new.status is distinct from old.status and (old.status <> 'PENDING_UPLOAD' or v_status <> 'DRAFT') then
    raise exception 'ECOM_INVALID_STATE: only an uploading file of a DRAFT return is confirmed or removed'
      using errcode = '23514';
  end if;
  return new;
end
$$;
revoke all on function rms_private.ecommerce_return_media_guard() from public, anon, authenticated;
create trigger ecommerce_return_media_guard
  before insert or update or delete on public.ecommerce_return_media
  for each row execute function rms_private.ecommerce_return_media_guard();

-- 6d. Ticket: created by the submit of a TICKET_RAISE return (SLA computed here), worked by a
--     Ticket Handler, final once closed; the return's status follows.
create or replace function rms_private.ecommerce_tickets_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_actor  uuid := rms_private.current_actor();
  v_ret    public.ecommerce_returns%rowtype;
begin
  if tg_op = 'DELETE' then
    raise exception 'ECOM_RETURN_IMMUTABLE: a ticket is never deleted' using errcode = '42501';
  end if;
  select * into v_ret from public.ecommerce_returns r where r.id = new.return_id;
  if tg_op = 'INSERT' then
    if v_ret.status <> 'PENDING_TICKET' or v_ret.qc_routing_code <> 'TICKET_RAISE' then
      raise exception 'ECOM_INVALID_STATE: a ticket is only queued for a submitted TICKET_RAISE return'
        using errcode = '23514';
    end if;
    if new.raised_at is not null or new.response_code is not null or new.closed_at is not null then
      raise exception 'ECOM_INVALID_STATE: a ticket starts unraised' using errcode = '23514';
    end if;
    new.created_at := now();
    new.sla_due_at := now() + make_interval(hours => rms_private.ecom_int_setting('ecommerce_ticket_sla_hours', 2)::integer);
    return new;
  end if;

  if (new.id, new.return_id, new.sla_due_at, new.created_at, new.created_by)
     is distinct from (old.id, old.return_id, old.sla_due_at, old.created_at, old.created_by) then
    raise exception 'ECOM_RETURN_IMMUTABLE: the ticket header and its SLA cannot be changed' using errcode = '42501';
  end if;
  if not coalesce(rms_private.user_holds_permission(v_actor, 'ecommerce_tickets', 'edit'), false) then
    raise exception 'ECOM_FORBIDDEN: only a Ticket Handler works platform tickets' using errcode = '42501';
  end if;
  if v_ret.status = 'VOIDED' then
    raise exception 'ECOM_INVALID_STATE: the return is voided' using errcode = '23514';
  end if;
  if old.closed_at is not null then
    raise exception 'ECOM_TICKET_CLOSED: a closed ticket is final' using errcode = '23514';
  end if;
  if old.raised_at is not null
     and (new.raised_at, new.assigned_handler_id) is distinct from (old.raised_at, old.assigned_handler_id) then
    raise exception 'ECOM_RETURN_IMMUTABLE: the ticket was already raised' using errcode = '42501';
  end if;
  if new.closed_at is not null and new.response_code = 'PENDING' then
    raise exception 'ECOM_TICKET_PENDING: a ticket cannot be closed while the platform response is Pending'
      using errcode = '23514';
  end if;
  return new;
end
$$;
revoke all on function rms_private.ecommerce_tickets_guard() from public, anon, authenticated;
create trigger ecommerce_tickets_guard
  before insert or update or delete on public.ecommerce_tickets
  for each row execute function rms_private.ecommerce_tickets_guard();

create or replace function rms_private.ecommerce_tickets_sync_return()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.raised_at is not null and old.raised_at is null then
    update public.ecommerce_returns set status = 'TICKET_RAISED' where id = new.return_id;
  end if;
  if new.closed_at is not null and old.closed_at is null then
    update public.ecommerce_returns set status = 'CLOSED', closed_at = new.closed_at where id = new.return_id;
  end if;
  return null;
end
$$;
revoke all on function rms_private.ecommerce_tickets_sync_return() from public, anon, authenticated;
create trigger ecommerce_tickets_sync_return
  after update on public.ecommerce_tickets
  for each row execute function rms_private.ecommerce_tickets_sync_return();

-- 6e. History is append-only.
create or replace function rms_private.ecommerce_return_events_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'ECOM_RETURN_IMMUTABLE: E-Commerce Return history is append-only' using errcode = '42501';
end
$$;
revoke all on function rms_private.ecommerce_return_events_guard() from public, anon, authenticated;
create trigger ecommerce_return_events_guard
  before update or delete on public.ecommerce_return_events
  for each row execute function rms_private.ecommerce_return_events_guard();

-- ---------------------------------------------------------------------------------------------
-- 7. RLS, grants, audit (G-17). Business data flows through the API (rms_api) only.
-- ---------------------------------------------------------------------------------------------
alter table public.ecommerce_returns enable row level security;
alter table public.ecommerce_return_media enable row level security;
alter table public.ecommerce_tickets enable row level security;
alter table public.ecommerce_return_events enable row level security;
revoke all on public.ecommerce_returns, public.ecommerce_return_media, public.ecommerce_tickets,
              public.ecommerce_return_events from anon, authenticated;
grant select, insert, update on public.ecommerce_returns to rms_api;
grant select, insert, update on public.ecommerce_return_media to rms_api;
grant select, insert, update on public.ecommerce_tickets to rms_api;
grant select, insert on public.ecommerce_return_events to rms_api;
select rms_private.attach_standard_triggers('public.ecommerce_returns');
select rms_private.attach_standard_triggers('public.ecommerce_return_media');
select rms_private.attach_standard_triggers('public.ecommerce_tickets');
select rms_private.attach_standard_triggers('public.ecommerce_return_events');

-- ---------------------------------------------------------------------------------------------
-- 8. Journey catalogue (who sees which entry: seed.sql + release snippet)
-- ---------------------------------------------------------------------------------------------
alter table public.journey_steps drop constraint if exists journey_steps_screen_key_check;
alter table public.journey_steps add constraint journey_steps_screen_key_check check (screen_key in (
  'journey-queue', 'gs-new', 'gs-list', 'dashboard', 'pendencies',
  'container-audit', 'reports', 'audit', 'custody', 'inventory', 'store-issues',
  'servicing', 'batteries', 'dismantling', 'scrap', 'credit-notes', 'approvals',
  'dispatch-queue', 'department-routing', 'department-receiving', 'department-issue',
  'accounts-entry', 'accounts-docs', 'dispatch-slips', 'transfer-slips', 'transfer-slip-acks',
  'store-routing', 'store-receiving', 'store-analysis', 'management-approval',
  'ecom-return-new', 'ecom-returns', 'ecom-tickets'));

alter table public.journey_steps drop constraint if exists journey_steps_item_screen_key_check;
alter table public.journey_steps add constraint journey_steps_item_screen_key_check check (
  item_screen_key is null or item_screen_key in (
    'gs-detail', 'gs-unboxing', 'gs-itemization', 'gs-inspection', 'gs-rm-review',
    'custody-transfer', 'gs-final-actions', 'department-receiving', 'department-issue',
    'accounts-entry-gs', 'accounts-docs', 'dispatch-slips',
    'gs-party-notification', 'transfer-slips', 'transfer-slip', 'gs-store-routing',
    'gs-store-receiving', 'gs-store-analysis', 'gs-management-approval', 'ecom-return'));

insert into public.journey_steps
  (code, label, hint, kind, screen_key, item_screen_key, queue_code, feature_code,
   perm_module, perm_action, sort_order, source_ref)
values
  ('ECOM_GATE_ENTRY', 'E-Commerce Gate Entry', 'Record an E-Commerce Return received at the gate',
   'STEP', 'ecom-return-new', 'ecom-return', null, null, 'ecommerce_returns', 'create', 12, 'DEC-73'),
  ('ECOM_TICKETS', 'Platform Tickets', 'Raise E-Commerce platform tickets within the SLA and record the platform''s response',
   'STEP', 'ecom-tickets', 'ecom-return', null, null, 'ecommerce_tickets', 'view', 13, 'DEC-73'),
  ('ECOM_RETURNS', 'E-Commerce Returns', 'Every E-Commerce Return with its status and history',
   'TOOL', 'ecom-returns', null, null, null, 'ecommerce_returns', 'view', 14, 'DEC-73')
on conflict (code) do nothing;
