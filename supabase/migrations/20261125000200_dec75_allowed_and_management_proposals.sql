-- =============================================================================================
-- DEC-75 (user request 2026-11-25): Intermediate Store analysis = "Allowed" / "Not Allowed" first,
-- then the Allowed pieces split into "Send New Pieces to Party" / "Send Repaired Pieces to Party";
-- pieces are sent to Management per item + condition + qty with a proposed action.
--
-- 1. Configuration (rule e):
--    * setting `store_analysis.verdicts`: the two verdicts shown to every store user and the ACTION
--      codes under each (Allowed → SEND_NEW, SEND_REPAIRED; Not Allowed → NOT_ALLOWED). The store
--      decides only these codes (DB trigger below + service). ISSUE_CN / PENDING_BP stay refused
--      by the DEC-69 store branch whatever the setting says (Issue CN = Management only, DEC-70).
--    * setting `store_analysis.management_proposals`: what a store may propose to Management for
--      pieces it sends (Send New Pieces / Issue CN).
--    * ACTION labels SEND_NEW "Send New Pieces to Party", SEND_REPAIRED "Send Repaired Pieces to
--      Party" (codes unchanged, G-18). Also in seed.sql (the library is seeded after migrations on
--      a fresh reset) and in supabase/snippets/release_20261125_dec75_allowed_management.sql.
--    * The DEC-74 store option ISSUE_CN_REQUEST is switched off (replaced by the per-piece request
--      below). Its code paths stay for goods slips that already carry it.
-- 2. gs_management_request_lines: "X items — Y qty — proposed action" lines of a Management approval
--    request. Each line names the pieces (item + condition + the store's current decision = the
--    "previous action" Management sees) and the proposed action. Append-only. Lines join the OPEN
--    request of the goods slip (one OPEN per GS, unchanged) or open a new one.
-- 3. rm_item_actions verdict guard (store analysis inserts only).
-- 4. My Work hint of the Analysis step follows the new wording.
-- Guards G-01…G-22 are unchanged. The Accounts gate (an OPEN request blocks Accounts, DEC-70) is
-- unchanged: a goods slip with no piece sent to Management goes straight to Accounts.
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- 1. Configuration
-- ---------------------------------------------------------------------------------------------
insert into public.system_settings (key, value, category, description, source_ref) values
  ('store_analysis.verdicts',
   '{"allowed": {"label": "Allowed", "actions": ["SEND_NEW", "SEND_REPAIRED"]},
     "not_allowed": {"label": "Not Allowed", "actions": ["NOT_ALLOWED"]}}'::jsonb,
   'workflow',
   'Store analysis: the two verdicts every Intermediate Store user sees first, and the ACTION codes under each (Allowed pieces are split between its actions; Not Allowed needs no more input). Issue CN / Pending are never store options.',
   'DEC-75'),
  ('store_analysis.management_proposals',
   '["SEND_NEW", "ISSUE_CN"]'::jsonb,
   'workflow',
   'Store analysis: the actions a store may propose for pieces it sends for Management approval. Management decides the final action.',
   'DEC-75')
on conflict (key) do nothing;

update public.item_field_library l
   set label = v.label
  from (values ('SEND_NEW', 'Dispatch New Piece', 'Send New Pieces to Party'),
               ('SEND_REPAIRED', 'Dispatch Repaired Piece', 'Send Repaired Pieces to Party'))
       as v(code, old_label, label)
 where l.field_group = 'ACTION' and l.code = v.code and l.label = v.old_label;

update public.item_field_library
   set is_active = false,
       description = 'Retired by DEC-75: stores send pieces to Management with a proposed action instead. Kept for goods slips that already carry it.'
 where field_group = 'ACTION' and code = 'ISSUE_CN_REQUEST' and is_active;

create or replace function rms_private.store_verdict_actions()
returns text[]
language sql
stable
set search_path = ''
as $$
  select coalesce(array(
           select jsonb_array_elements_text(s.value -> v.k -> 'actions')
             from public.system_settings s
            cross join (values ('allowed'), ('not_allowed')) as v(k)
            where s.key = 'store_analysis.verdicts'), '{}'::text[])
$$;
revoke all on function rms_private.store_verdict_actions() from public, anon, authenticated;
grant execute on function rms_private.store_verdict_actions() to rms_api;

create or replace function rms_private.store_proposal_actions()
returns text[]
language sql
stable
set search_path = ''
as $$
  select coalesce(array(
           select jsonb_array_elements_text(s.value)
             from public.system_settings s
            where s.key = 'store_analysis.management_proposals'
              and jsonb_typeof(s.value) = 'array'), '{}'::text[])
$$;
revoke all on function rms_private.store_proposal_actions() from public, anon, authenticated;
grant execute on function rms_private.store_proposal_actions() to rms_api;

-- ---------------------------------------------------------------------------------------------
-- 2. Request lines
-- ---------------------------------------------------------------------------------------------
create table public.gs_management_request_lines (
  id                    uuid primary key default gen_random_uuid(),
  request_id            uuid not null references public.gs_management_approval_requests (id) on delete restrict,
  gs_id                 uuid not null references public.goods_slips (id) on delete restrict,
  gs_item_id            uuid not null references public.gs_items (id) on delete restrict,
  condition_field_id    uuid references public.item_field_library (id) on delete restrict,
  condition_label       text,
  store_id              uuid not null references public.intermediate_stores (id) on delete restrict,
  from_action_code      text not null,
  from_action_label     text not null,
  proposed_action_code  text not null,
  proposed_action_label text not null,
  qty                   integer not null check (qty > 0),
  requested_by          uuid not null default rms_private.current_actor()
                          references public.profiles (id) on delete restrict,
  requested_at          timestamptz not null default now(),
  created_at            timestamptz not null default now(),
  check (proposed_action_code <> from_action_code)
);
create index gs_mgmt_request_lines_request_idx on public.gs_management_request_lines (request_id);
create index gs_mgmt_request_lines_gs_idx on public.gs_management_request_lines (gs_id);
create index gs_mgmt_request_lines_item_idx on public.gs_management_request_lines (gs_item_id);
create index gs_mgmt_request_lines_cond_idx on public.gs_management_request_lines (condition_field_id);
create index gs_mgmt_request_lines_store_idx on public.gs_management_request_lines (store_id);
create index gs_mgmt_request_lines_by_idx on public.gs_management_request_lines (requested_by);
comment on table public.gs_management_request_lines is
  'DEC-75: pieces a store sends for Management approval (item + condition + the store''s current decision + qty) with a proposed action. Append-only; Management''s decision is final.';

-- Pieces of a decision still free to send (current qty minus the lines of OPEN requests).
create or replace function rms_private.gs_request_free_qty(
  p_gs_item_id uuid, p_condition_field_id uuid, p_action_code text)
returns integer
language sql
stable
set search_path = ''
as $$
  select coalesce((select sum(a.qty) from public.rm_item_actions a
                    where a.gs_item_id = p_gs_item_id and a.is_current
                      and a.condition_field_id is not distinct from p_condition_field_id
                      and a.action_code = p_action_code), 0)::integer
       - coalesce((select sum(l.qty) from public.gs_management_request_lines l
                     join public.gs_management_approval_requests r on r.id = l.request_id
                    where r.status = 'OPEN' and l.gs_item_id = p_gs_item_id
                      and l.condition_field_id is not distinct from p_condition_field_id
                      and l.from_action_code = p_action_code), 0)::integer
$$;
revoke all on function rms_private.gs_request_free_qty(uuid, uuid, text) from public, anon, authenticated;
grant execute on function rms_private.gs_request_free_qty(uuid, uuid, text) to rms_api;

create or replace function rms_private.gs_management_request_lines_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_req      record;
  v_status   text;
  v_item     record;
  v_store    uuid;
  v_store_nm text;
  v_from     text;
  v_prop     text;
  v_free     integer;
  v_actor    uuid := rms_private.current_actor();
begin
  if tg_op <> 'INSERT' then
    raise exception 'DEC-75: a line sent for Management approval is history (append-only)'
      using errcode = '42501';
  end if;
  select r.gs_id, r.status into v_req
    from public.gs_management_approval_requests r where r.id = new.request_id;
  if not found or v_req.status <> 'OPEN' then
    raise exception 'DEC-75: pieces are added only to an OPEN Management approval request'
      using errcode = '23514';
  end if;
  select gi.gs_id, gi.product_id, gi.line_no into v_item
    from public.gs_items gi where gi.id = new.gs_item_id;
  if not found or v_item.gs_id <> v_req.gs_id or new.gs_id <> v_req.gs_id then
    raise exception 'DEC-75: the item is not on the goods slip of the request' using errcode = '23514';
  end if;
  select status into v_status from public.goods_slips where id = new.gs_id for update;
  if v_status is null or v_status not in ('STORE_PROCESSING', 'ANALYSIS_COMPLETED') then
    raise exception 'DEC-75: pieces are sent for Management approval between the store analysis and Accounts (status %)',
      coalesce(v_status, 'missing') using errcode = '23514';
  end if;
  v_store := rms_private.gs_item_store(new.gs_item_id);
  if v_store is null then
    raise exception 'DEC-75: item line % is on no Intermediate Store''s transfer slip', v_item.line_no
      using errcode = '23514';
  end if;
  select name into v_store_nm from public.intermediate_stores where id = v_store;
  if not coalesce(rms_private.user_holds_permission(v_actor, 'store_analysis', 'create')
                  and rms_private.user_acts_for_store(v_actor, v_store), false) then
    raise exception 'DEC-75: item line % belongs to %; only a user of that store sends its pieces to Management',
      v_item.line_no, v_store_nm using errcode = '42501';
  end if;
  if not exists (select 1 from public.gs_store_analyses a
                  where a.gs_id = new.gs_id and a.store_id = v_store) then
    raise exception 'DEC-75: % sends pieces to Management with or after its analysis submission', v_store_nm
      using errcode = '23514';
  end if;
  -- The "previous action": the store's (or Management's) current decision of these pieces.
  select a.action_label into v_from
    from public.rm_item_actions a
   where a.gs_item_id = new.gs_item_id and a.is_current
     and a.condition_field_id is not distinct from new.condition_field_id
     and a.action_code = new.from_action_code
   limit 1;
  if not found then
    raise exception 'DEC-75: item line % has no current % decision to send', v_item.line_no, new.from_action_code
      using errcode = '23514';
  end if;
  v_free := rms_private.gs_request_free_qty(new.gs_item_id, new.condition_field_id, new.from_action_code);
  if new.qty > v_free then
    raise exception 'DEC-75: item line %: % pc(s) of % are free to send, not %', v_item.line_no, v_free,
      new.from_action_code, new.qty using errcode = '23514';
  end if;
  if not (new.proposed_action_code = any (rms_private.store_proposal_actions())) then
    raise exception 'DEC-75: % is not a proposal a store may send to Management', new.proposed_action_code
      using errcode = '23514';
  end if;
  select r.label into v_prop
    from rms_private.resolve_item_field_profile(
           v_item.product_id,
           (select g.item_field_profile_version_id from public.goods_slips g where g.id = new.gs_id)) r
   where r.field_group = 'ACTION' and r.code = new.proposed_action_code;
  if not found then
    raise exception 'G-21: action % is not allowed by the resolved profile of item line %',
      new.proposed_action_code, v_item.line_no using errcode = 'P0001';
  end if;
  new.store_id := v_store;
  new.from_action_label := coalesce(v_from, new.from_action_code);
  new.proposed_action_label := coalesce(v_prop, new.proposed_action_code);
  new.condition_label := (select c.field_label from rms_private.item_current_conditions(new.gs_item_id) c
                           where c.field_id = new.condition_field_id);
  new.requested_by := v_actor;
  new.requested_at := now();
  return new;
end
$$;
revoke all on function rms_private.gs_management_request_lines_guard() from public, anon, authenticated;
create trigger gs_management_request_lines_guard
  before insert or update or delete on public.gs_management_request_lines
  for each row execute function rms_private.gs_management_request_lines_guard();

alter table public.gs_management_request_lines enable row level security;
revoke all on public.gs_management_request_lines from anon, authenticated;
grant select, insert on public.gs_management_request_lines to rms_api;
select rms_private.attach_standard_triggers('public.gs_management_request_lines');

-- ---------------------------------------------------------------------------------------------
-- 3. Verdict guard: a store decides only the configured verdict actions.
-- ---------------------------------------------------------------------------------------------
create or replace function rms_private.rm_item_actions_store_verdict_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_gs_id  uuid;
  v_status text;
begin
  if not new.is_current then
    return new;
  end if;
  select gi.gs_id into v_gs_id from public.gs_items gi where gi.id = new.gs_item_id;
  if v_gs_id is null or not rms_private.gs_on_store_flow(v_gs_id) then
    return new;
  end if;
  select status into v_status from public.goods_slips where id = v_gs_id;
  -- Store analysis only (Management works at ANALYSIS_COMPLETED with every action, DEC-70).
  if v_status = 'STORE_PROCESSING'
     and not (new.action_code = any (rms_private.store_verdict_actions())) then
    raise exception 'DEC-75: % is not an Allowed / Not Allowed option of the store analysis', new.action_code
      using errcode = '23514';
  end if;
  return new;
end
$$;
revoke all on function rms_private.rm_item_actions_store_verdict_guard() from public, anon, authenticated;
create trigger rm_item_actions_store_verdict_guard
  before insert on public.rm_item_actions
  for each row execute function rms_private.rm_item_actions_store_verdict_guard();

-- ---------------------------------------------------------------------------------------------
-- 4. My Work hint of the Analysis step (journey catalogue text; only while it is the P9 default)
-- ---------------------------------------------------------------------------------------------
update public.journey_steps
   set hint = 'Goods of your Intermediate Store back from departments (or with no work): mark Allowed or Not Allowed, choose new or repaired pieces, and send pieces to Management when needed'
 where code = 'STORE_ANALYSIS'
   and hint = 'Goods of your Intermediate Store back from departments (or with no work): decide Dispatch New, Dispatch Repaired or Not Allowed';
