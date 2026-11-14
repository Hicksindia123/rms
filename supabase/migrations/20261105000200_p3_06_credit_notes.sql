-- ===========================================================================
-- P3-06: Credit Notes, RM CN Decision, Accounts Verification & Rates
-- References: Master Plan §2.2 (Step-7), §3.2 DD r68–r78, BR-32..BR-37,
--             G-13, G-14, DEC-13, DEC-22, DEC-23, DEC-24, DEC-33.
-- ===========================================================================

-- 1. Ensure JV_ONLY option exists in CN_TYPE option set (DD r76, DEC-23)
insert into public.option_items (
  option_set_id, code, label, allowed_status, rule_text, next_action_text,
  remarks, sort_order, source_ref
)
select
  id, 'JV_ONLY', 'Journal Voucher (JV) Only', 'CONDITIONAL',
  'Issued when return is not reflected on GST portal. Permitted only as normal JV.',
  'Record JV voucher details and valuation',
  'Strict compliance rule', 30, 'DD r76'
from public.option_sets
where code = 'CN_TYPE'
on conflict (option_set_id, code) do update set
  label = excluded.label,
  allowed_status = excluded.allowed_status,
  rule_text = excluded.rule_text,
  next_action_text = excluded.next_action_text,
  remarks = excluded.remarks;

-- 2. System settings for commercial verification
insert into public.system_settings (key, value, category, description, source_ref) values
  ('company_state_code', '"UP"'::jsonb, 'accounts',
   'State code of the company for GST intra-state vs inter-state tax determination.', 'P3-06'),
  ('rate_variance_warning_percent', '15'::jsonb, 'accounts',
   'Percentage difference between verified sales and purchase rates that triggers an advisory warning.', 'P3-06'),
  ('default_gst_rate_percent', '18'::jsonb, 'accounts',
   'Default GST rate percent applied on credit note items if not specified.', 'P3-06')
on conflict (key) do nothing;

-- 3. rm_cn_decisions & rm_cn_decision_lines (BR-32, DEC-13, G-13)
create table if not exists public.rm_cn_decisions (
  id                 uuid primary key default gen_random_uuid(),
  gs_id              uuid not null references public.goods_slips (id) on delete restrict,
  decision_by        uuid not null default rms_private.current_actor() references public.profiles (id) on delete restrict,
  decision_at        timestamptz not null default now(),
  deviation_reason   text,
  is_current         boolean not null default true,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create unique index if not exists rm_cn_decisions_current_idx
  on public.rm_cn_decisions (gs_id)
  where is_current = true;

create index if not exists rm_cn_decisions_gs_idx on public.rm_cn_decisions (gs_id);

create table if not exists public.rm_cn_decision_lines (
  id                 uuid primary key default gen_random_uuid(),
  decision_id        uuid not null references public.rm_cn_decisions (id) on delete cascade,
  gs_item_id         uuid not null references public.gs_items (id) on delete restrict,
  decision_code      text not null check (decision_code in ('ALLOW_CN', 'DENY_CN_SEND_REPLACEMENT')),
  qty                integer not null check (qty > 0),
  created_at         timestamptz not null default now()
);

create index if not exists rm_cn_decision_lines_dec_idx on public.rm_cn_decision_lines (decision_id);
create index if not exists rm_cn_decision_lines_item_idx on public.rm_cn_decision_lines (gs_item_id);

-- 4. credit_notes (BR-33..BR-37, G-13, G-14, DEC-22, DEC-23)
create table if not exists public.credit_notes (
  id                          uuid primary key default gen_random_uuid(),
  gs_id                       uuid not null references public.goods_slips (id) on delete restrict,
  cn_type_code                text not null check (cn_type_code in ('GST_CN', 'GENERAL_CN', 'JV_ONLY')),
  status                      text not null default 'DRAFT' check (status in ('DRAFT', 'VERIFIED', 'ISSUED', 'CANCELLED')),
  party_doc_code              text check (party_doc_code is null or party_doc_code in ('PARTY_INVOICE', 'PARTY_DEBIT_NOTE', 'PARTY_NO_DOC')),
  party_doc_no                text,
  party_doc_date              date,
  party_doc_amount            numeric(12,2) check (party_doc_amount is null or party_doc_amount >= 0),
  party_doc_notes             text,
  party_doc_verified_by       uuid references public.profiles (id) on delete set null,
  party_doc_verified_at       timestamptz,
  gst_portal_code             text check (gst_portal_code is null or gst_portal_code in ('GST_REFLECTED', 'GST_NOT_REFLECTED')),
  gst_return_type             text check (gst_return_type is null or gst_return_type in ('GSTR-1', 'GSTR-2B')),
  gst_return_period           text,
  gst_checked_on              date,
  gst_evidence_attachment_id  uuid references public.attachments (id) on delete set null,
  gst_verified_by             uuid references public.profiles (id) on delete set null,
  gst_verified_at             timestamptz,
  cn_no                       text,
  cn_date                     date,
  jv_no                       text,
  jv_date                     date,
  taxable_value               numeric(12,2) not null default 0.00 check (taxable_value >= 0),
  cgst_rate                   numeric(5,2) not null default 0.00 check (cgst_rate >= 0),
  cgst_amount                 numeric(12,2) not null default 0.00 check (cgst_amount >= 0),
  sgst_rate                   numeric(5,2) not null default 0.00 check (sgst_rate >= 0),
  sgst_amount                 numeric(12,2) not null default 0.00 check (sgst_amount >= 0),
  igst_rate                   numeric(5,2) not null default 0.00 check (igst_rate >= 0),
  igst_amount                 numeric(12,2) not null default 0.00 check (igst_amount >= 0),
  total_value                 numeric(12,2) not null default 0.00 check (total_value >= 0),
  is_inter_state              boolean not null default false,
  issued_by                   uuid references public.profiles (id) on delete set null,
  issued_at                   timestamptz,
  cancelled_by                uuid references public.profiles (id) on delete set null,
  cancelled_at                timestamptz,
  cancel_reason               text,
  created_by                  uuid not null default rms_private.current_actor() references public.profiles (id) on delete restrict,
  created_at                  timestamptz not null default now(),
  updated_at                  timestamptz not null default now(),
  constraint cn_gst_reflected_check check (
    status = 'DRAFT' or cn_type_code <> 'GST_CN' or gst_portal_code = 'GST_REFLECTED'
  ),
  constraint cn_not_reflected_jv_check check (
    status = 'DRAFT' or gst_portal_code is null or gst_portal_code <> 'GST_NOT_REFLECTED' or cn_type_code = 'JV_ONLY'
  ),
  constraint cn_issue_numbers_check check (
    status <> 'ISSUED' or (
      (cn_type_code in ('GST_CN', 'GENERAL_CN') and cn_no is not null and cn_date is not null) or
      (cn_type_code = 'JV_ONLY' and jv_no is not null and jv_date is not null)
    )
  )
);

create unique index if not exists credit_notes_cn_no_idx
  on public.credit_notes (cn_no)
  where cn_no is not null;

create unique index if not exists credit_notes_jv_no_idx
  on public.credit_notes (jv_no)
  where jv_no is not null;

create index if not exists credit_notes_gs_idx on public.credit_notes (gs_id);
create index if not exists credit_notes_status_idx on public.credit_notes (status);
create index if not exists credit_notes_created_at_idx on public.credit_notes (created_at desc);

-- 5. credit_note_lines (G-13, DEC-23)
create table if not exists public.credit_note_lines (
  id                 uuid primary key default gen_random_uuid(),
  credit_note_id     uuid not null references public.credit_notes (id) on delete cascade,
  gs_item_id         uuid not null references public.gs_items (id) on delete restrict,
  lot_id             uuid references public.stock_lots (id) on delete restrict,
  line_no            integer not null check (line_no > 0),
  qty                integer not null check (qty > 0),
  rate               numeric(12,2) not null default 0.00 check (rate >= 0),
  tax_rate           numeric(5,2) not null default 18.00 check (tax_rate >= 0),
  taxable_amount     numeric(12,2) not null default 0.00 check (taxable_amount >= 0),
  cgst_amount        numeric(12,2) not null default 0.00 check (cgst_amount >= 0),
  sgst_amount        numeric(12,2) not null default 0.00 check (sgst_amount >= 0),
  igst_amount        numeric(12,2) not null default 0.00 check (igst_amount >= 0),
  total_amount       numeric(12,2) not null default 0.00 check (total_amount >= 0),
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create index if not exists credit_note_lines_cn_idx on public.credit_note_lines (credit_note_id);
create index if not exists credit_note_lines_item_idx on public.credit_note_lines (gs_item_id);
create index if not exists credit_note_lines_lot_idx on public.credit_note_lines (lot_id);

-- 6. rate_verifications (G-14, BR-36, DEC-24)
create table if not exists public.rate_verifications (
  id                   uuid primary key default gen_random_uuid(),
  credit_note_line_id  uuid not null references public.credit_note_lines (id) on delete cascade,
  reference_code       text not null check (reference_code in ('RATE_SALES', 'RATE_PURCHASE')),
  ref_doc_no           text not null check (btrim(ref_doc_no) <> ''),
  ref_doc_date         date not null,
  rate                 numeric(12,2) not null check (rate > 0),
  notes                text,
  verified_by          uuid not null default rms_private.current_actor() references public.profiles (id) on delete restrict,
  verified_at          timestamptz not null default now(),
  created_at           timestamptz not null default now()
);

create index if not exists rate_verifications_line_idx on public.rate_verifications (credit_note_line_id);

-- ===========================================================================
-- 7. System Guards G-13 & G-14 Triggers
-- ===========================================================================

create or replace function rms_private.credit_notes_g13_guard()
returns trigger as $$
declare
  v_gs_id uuid;
  v_cn_type text;
  v_portal_code text;
  v_has_rm_allow boolean;
  v_allowed_qty integer;
  v_existing_qty integer;
  v_lot_condition text;
begin
  if tg_table_name = 'credit_notes' then
    v_gs_id := new.gs_id;
    v_cn_type := new.cn_type_code;
    v_portal_code := new.gst_portal_code;

    -- Must have an active RM decision allowing at least 1 item
    select exists (
      select 1
      from public.rm_cn_decisions d
      join public.rm_cn_decision_lines dl on dl.decision_id = d.id
      where d.gs_id = v_gs_id
        and d.is_current = true
        and dl.decision_code = 'ALLOW_CN'
    ) into v_has_rm_allow;

    if not v_has_rm_allow then
      raise exception 'G-13: No active RM ALLOW_CN decision found for goods slip %', v_gs_id;
    end if;

    if new.status in ('VERIFIED', 'ISSUED') and v_cn_type = 'GST_CN' and (v_portal_code is null or v_portal_code <> 'GST_REFLECTED') then
      raise exception 'G-13: GST Credit Note requires return to be reflected on GST portal';
    end if;

    if new.status in ('VERIFIED', 'ISSUED') and v_portal_code = 'GST_NOT_REFLECTED' and v_cn_type <> 'JV_ONLY' then
      raise exception 'G-13: Return not reflected on GST portal permits only JV_ONLY';
    end if;

    return new;

  elsif tg_table_name = 'credit_note_lines' then
    select cn.gs_id, cn.cn_type_code into v_gs_id, v_cn_type
    from public.credit_notes cn
    where cn.id = new.credit_note_id;

    -- Allowed qty for this item in current decision
    select coalesce(sum(dl.qty), 0) into v_allowed_qty
    from public.rm_cn_decisions d
    join public.rm_cn_decision_lines dl on dl.decision_id = d.id
    where d.gs_id = v_gs_id
      and d.is_current = true
      and dl.gs_item_id = new.gs_item_id
      and dl.decision_code = 'ALLOW_CN';

    if v_allowed_qty <= 0 then
      raise exception 'G-13: Item % has not been allowed for Credit Note by RM', new.gs_item_id;
    end if;

    -- Check cumulative qty across active credit notes
    select coalesce(sum(cl.qty), 0) into v_existing_qty
    from public.credit_note_lines cl
    join public.credit_notes cn on cn.id = cl.credit_note_id
    where cn.gs_id = v_gs_id
      and cl.gs_item_id = new.gs_item_id
      and cn.status <> 'CANCELLED'
      and cl.id <> coalesce(new.id, '00000000-0000-0000-0000-000000000000'::uuid);

    if (v_existing_qty + new.qty) > v_allowed_qty then
      raise exception 'G-13: Credit Note qty % exceeds allowed qty % for item % (already credited: %)',
        new.qty, v_allowed_qty, new.gs_item_id, v_existing_qty;
    end if;

    -- Condition class checks if lot is referenced
    if new.lot_id is not null then
      select condition_class into v_lot_condition
      from public.stock_lots
      where id = new.lot_id;

      if v_cn_type = 'GST_CN' and v_lot_condition not in ('FUNCTIONAL_GOOD', 'AS_RECEIVED') then
        raise exception 'G-13: GST Credit Note only applies to FUNCTIONAL_GOOD items. Lot % is %',
          new.lot_id, v_lot_condition;
      elsif v_cn_type = 'GENERAL_CN' and v_lot_condition <> 'FUNCTIONAL_REPAIRED' then
        raise exception 'G-13: General Credit Note only applies to FUNCTIONAL_REPAIRED items. Lot % is %',
          new.lot_id, v_lot_condition;
      end if;
    end if;

    return new;
  end if;

  return new;
end;
$$ language plpgsql security definer;

revoke all on function rms_private.credit_notes_g13_guard() from public, anon, authenticated;

drop trigger if exists trg_credit_notes_g13 on public.credit_notes;
create trigger trg_credit_notes_g13
  before insert or update on public.credit_notes
  for each row execute function rms_private.credit_notes_g13_guard();

drop trigger if exists trg_credit_note_lines_g13 on public.credit_note_lines;
create trigger trg_credit_note_lines_g13
  before insert or update on public.credit_note_lines
  for each row execute function rms_private.credit_notes_g13_guard();

create or replace function rms_private.credit_notes_g14_guard()
returns trigger as $$
declare
  v_missing_lines integer;
  v_total_lines integer;
begin
  if new.status = 'ISSUED' and old.status <> 'ISSUED' then
    select count(*) into v_total_lines
    from public.credit_note_lines
    where credit_note_id = new.id;

    if v_total_lines = 0 then
      raise exception 'G-14: Cannot issue Credit Note % with zero lines', new.id;
    end if;

    select count(*) into v_missing_lines
    from public.credit_note_lines cnl
    where cnl.credit_note_id = new.id
      and not exists (
        select 1
        from public.rate_verifications rv
        where rv.credit_note_line_id = cnl.id
      );

    if v_missing_lines > 0 then
      raise exception 'G-14: Credit Note % has % line(s) without rate verification. Issue blocked.',
        new.id, v_missing_lines;
    end if;
  end if;

  return new;
end;
$$ language plpgsql security definer;

revoke all on function rms_private.credit_notes_g14_guard() from public, anon, authenticated;

drop trigger if exists trg_credit_notes_g14 on public.credit_notes;
create trigger trg_credit_notes_g14
  before update on public.credit_notes
  for each row execute function rms_private.credit_notes_g14_guard();

-- ===========================================================================
-- 8. Audit and RLS
-- ===========================================================================
select rms_private.attach_standard_triggers('public.rm_cn_decisions');
select rms_private.attach_standard_triggers('public.rm_cn_decision_lines');
select rms_private.attach_standard_triggers('public.credit_notes');
select rms_private.attach_standard_triggers('public.credit_note_lines');
select rms_private.attach_standard_triggers('public.rate_verifications');

alter table public.rm_cn_decisions enable row level security;
alter table public.rm_cn_decision_lines enable row level security;
alter table public.credit_notes enable row level security;
alter table public.credit_note_lines enable row level security;
alter table public.rate_verifications enable row level security;

revoke all on public.rm_cn_decisions from anon, authenticated;
revoke all on public.rm_cn_decision_lines from anon, authenticated;
revoke all on public.credit_notes from anon, authenticated;
revoke all on public.credit_note_lines from anon, authenticated;
revoke all on public.rate_verifications from anon, authenticated;

grant select, insert, update on public.rm_cn_decisions to rms_api;
grant select, insert, delete on public.rm_cn_decision_lines to rms_api;
grant select, insert, update on public.credit_notes to rms_api;
grant select, insert, update, delete on public.credit_note_lines to rms_api;
grant select, insert, update, delete on public.rate_verifications to rms_api;

grant all on public.rm_cn_decisions to service_role;
grant all on public.rm_cn_decision_lines to service_role;
grant all on public.credit_notes to service_role;
grant all on public.credit_note_lines to service_role;
grant all on public.rate_verifications to service_role;
