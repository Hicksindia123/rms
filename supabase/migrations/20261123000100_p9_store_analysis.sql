-- =============================================================================================
-- Phase P9 (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-69 (PROVISIONAL; Q15, Q16).
-- Analysis by the Intermediate Store user (Steps 7–8 of the 20-11-2026 flow).
--
-- Once a store's part of a goods slip is READY_FOR_ANALYSIS (P8: everything routed and back, or
-- "Issue to Store"), a user of that store decides per item + current condition (DEC-57 groups):
-- Dispatch New Piece (SEND_NEW), Dispatch Repaired Piece (SEND_REPAIRED) or Not Allowed
-- (NOT_ALLOWED). Codes are unchanged; the labels are configuration (seed + release snippet).
-- The decisions are rm_item_actions round-1 rows (the existing table, G-18 label + condition
-- snapshots); "Submit analysis" writes them and the store's submission in one transaction. Each
-- store submits its part independently; when every store with lines on the GS has submitted, the
-- GS moves STORE_PROCESSING → ANALYSIS_COMPLETED. Nothing is settled in stock here: the piece
-- destinations of DEC-57 (Q16) are applied by the Accounts / dispatch settlement (P11), so a
-- Management change (P10) needs no stock reversal. No A/c (Replacement) slip is created here
-- (it is created once per GS at the Accounts gate, DEC-71).
--
-- 1. Status ANALYSIS_COMPLETED ("Analysis Completed"); P10 / P11 add its exits.
-- 2. Permission module store_analysis (view / create). Grants + menus: seed.sql + the snippet.
-- 3. Helpers: rms_private.gs_on_store_flow, store_analysis_groups (per store, item + condition:
--    qty to decide and qty decided), gs_store_analysis_progress, gs_store_analysis_complete,
--    validate_store_analysis (G-21 for the store flow).
-- 4. gs_store_analyses: one submission per GS and store (append-only; P10 may reopen through its
--    own migration). Guard: a user of that store (store_analysis.create), GS STORE_PROCESSING, the
--    store READY_FOR_ANALYSIS, every item + condition of the store exactly decided (G-21).
-- 5. gs_management_approval_requests: "Send for Management Approval" (reason required) by any
--    user of a store on the GS; one OPEN request per GS. Resolved by Management in P10.
-- 6. rm_item_actions guard (full body: 20261118000300 G4 body + the DEC-69 branch, checked
--    FIRST): on a store-flow GS a row is written only by a user of the item's store, while the GS
--    is STORE_PROCESSING, the store is READY_FOR_ANALYSIS and has not submitted; ISSUE_CN and
--    PENDING_BP are refused (Q15: Issue CN is Management's, DEC-70; Pending is retired for new
--    GSs). Legacy GSs (HELD_AT_INTERMEDIATE_STORE / RM final actions) are unchanged.
-- 7. Deferred G-21 check (full body: 20261113001100 + the store flow).
-- 8. G-03 status chain (full body: P7 body + ANALYSIS_COMPLETED).
-- 9. Journey catalogue STORE_ANALYSIS (queue STORE_ANALYSIS, user-scoped; screens store-analysis /
--    gs-store-analysis) + notification event types.
-- Q32: the undo of an "Issue to Store" line already stops once the item has a current
-- rm_item_actions row (20261121000400); here those rows exist exactly when the store submitted.
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- 1. Status
-- ---------------------------------------------------------------------------------------------
alter table public.goods_slips drop constraint goods_slips_status_check;
alter table public.goods_slips
  add constraint goods_slips_status_check check (status in (
    'GATE_CREATED', 'UNBOXING', 'ITEMIZATION', 'CATEGORISATION', 'CSR_APPROVAL_PENDING',
    'INSPECTION', 'RM_REVIEW', 'PENDING_TRANSFER_SLIP', 'TRANSFER_SLIP_GENERATED',
    'STORE_ACKNOWLEDGED', 'STORE_PROCESSING', 'ANALYSIS_COMPLETED', 'SALES_RETURN_HOLD',
    'HELD_AT_INTERMEDIATE_STORE', 'IN_PROCESS', 'COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION',
    'CLOSED', 'CANCELLED'));

-- ---------------------------------------------------------------------------------------------
-- 2. Permission
-- ---------------------------------------------------------------------------------------------
insert into public.permissions (module_code, action, description)
values
  ('store_analysis', 'view',
   'See the analysis (final decisions) of the Intermediate Stores'' goods (DEC-69)'),
  ('store_analysis', 'create',
   'Analyse and submit the user''s own Intermediate Store goods; send a goods slip for Management approval (DEC-69)')
on conflict (module_code, action) do nothing;

insert into public.role_permissions (role_id, permission_id, scope)
select r.id, p.id, 'all'
  from public.roles r
  join public.permissions p on p.module_code = 'store_analysis'
 where r.code = 'SUPER_ADMIN'
on conflict (role_id, permission_id) do nothing;

-- ---------------------------------------------------------------------------------------------
-- 3. Helpers
-- ---------------------------------------------------------------------------------------------
-- DEC-65..69: the goods slip went through the Intermediate Store transfer slips (P5).
create or replace function rms_private.gs_on_store_flow(p_gs_id uuid)
returns boolean
language sql
stable
set search_path = ''
as $$
  select exists (
    select 1 from public.transfer_slip_gs tg
      join public.transfer_slips s on s.id = tg.slip_id
     where tg.gs_id = p_gs_id and s.status in ('GENERATED', 'ACKNOWLEDGED'))
$$;
revoke all on function rms_private.gs_on_store_flow(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_on_store_flow(uuid) to rms_api;

-- DEC-69 / G-21: per store, item and current condition (DEC-57 groups) the qty to decide and the
-- qty decided (current round-1 actions). Items without a condition split are one group (NULL).
create or replace function rms_private.store_analysis_groups(p_gs_id uuid)
returns table (
  store_id            uuid,
  gs_item_id          uuid,
  line_no             integer,
  item_name           text,
  product_id          uuid,
  condition_field_id  uuid,
  condition_code      text,
  condition_label     text,
  sort_order          integer,
  current_qty         integer,
  at_dept_qty         integer,
  available_qty       integer,
  actioned_qty        integer
)
language sql
stable
set search_path = ''
as $$
  select rms_private.gs_item_store(gi.id), q.gs_item_id, q.line_no, q.item_name, gi.product_id,
         q.condition_field_id, q.condition_code, q.condition_label, q.sort_order,
         q.current_qty, q.at_dept_qty, q.available_qty, q.actioned_qty
    from rms_private.final_action_condition_quantities(p_gs_id) q
    join public.gs_items gi on gi.id = q.gs_item_id
   where gi.removed_at is null and gi.received_qty > 0
     and (q.current_qty > 0 or q.actioned_qty > 0)
$$;
revoke all on function rms_private.store_analysis_groups(uuid) from public, anon, authenticated;
grant execute on function rms_private.store_analysis_groups(uuid) to rms_api;
comment on function rms_private.store_analysis_groups(uuid) is
  'DEC-69 / G-21: per Intermediate Store, GS item and current condition: qty to decide (available) and qty decided (round-1 actions).';

-- ---------------------------------------------------------------------------------------------
-- 4. Store submissions
-- ---------------------------------------------------------------------------------------------
create table public.gs_store_analyses (
  id            uuid primary key default gen_random_uuid(),
  gs_id         uuid not null references public.goods_slips (id) on delete restrict,
  store_id      uuid not null references public.intermediate_stores (id) on delete restrict,
  store_code_snapshot text not null,
  store_name_snapshot text not null,
  revision_no   integer not null check (revision_no >= 1),
  total_qty     integer not null check (total_qty > 0),
  totals        jsonb not null default '[]'::jsonb check (jsonb_typeof(totals) = 'array'),
  remarks       text,
  submitted_by  uuid not null default rms_private.current_actor()
                  references public.profiles (id) on delete restrict,
  submitted_at  timestamptz not null default now(),
  created_at    timestamptz not null default now(),
  unique (gs_id, store_id)
);
create index gs_store_analyses_store_idx on public.gs_store_analyses (store_id);
create index gs_store_analyses_submitted_by_idx on public.gs_store_analyses (submitted_by);
comment on table public.gs_store_analyses is
  'DEC-69: an Intermediate Store submitted its analysis of a goods slip (its decisions are the current rm_item_actions round-1 rows of its items). Append-only.';

-- Progress of the analysis per store on one GS (built on the P7/P8 routing progress):
--   NOT_READY  goods still to acknowledge / route / at a department
--   PENDING    READY_FOR_ANALYSIS, not submitted
--   SUBMITTED  the store submitted its analysis
create or replace function rms_private.gs_store_analysis_progress(p_gs_id uuid)
returns table (
  store_id         uuid,
  store_code       text,
  store_name       text,
  routing_status   text,
  analysis_status  text,
  submitted_at     timestamptz,
  submitted_by     uuid
)
language sql
stable
set search_path = ''
as $$
  select p.store_id, p.store_code, p.store_name, p.status,
         case when a.id is not null then 'SUBMITTED'
              when p.status = 'READY_FOR_ANALYSIS' then 'PENDING'
              else 'NOT_READY' end,
         a.submitted_at, a.submitted_by
    from rms_private.gs_store_routing_progress(p_gs_id) p
    left join public.gs_store_analyses a on a.gs_id = p_gs_id and a.store_id = p.store_id
$$;
revoke all on function rms_private.gs_store_analysis_progress(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_store_analysis_progress(uuid) to rms_api;

-- DEC-69: every Intermediate Store with lines on the GS submitted its analysis.
create or replace function rms_private.gs_store_analysis_complete(p_gs_id uuid)
returns boolean
language sql
stable
set search_path = ''
as $$
  select exists (select 1 from rms_private.gs_store_routing_progress(p_gs_id))
     and not exists (
       select 1 from rms_private.gs_store_routing_progress(p_gs_id) p
        where not exists (select 1 from public.gs_store_analyses a
                           where a.gs_id = p_gs_id and a.store_id = p.store_id))
$$;
revoke all on function rms_private.gs_store_analysis_complete(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_store_analysis_complete(uuid) to rms_api;

-- G-21 for the store flow: a store that has decisions (or submitted) decided every piece of every
-- item + condition of its part exactly once, and no decision names a group that does not exist.
create or replace function rms_private.validate_store_analysis(p_gs_id uuid)
returns void
language plpgsql
stable
set search_path = ''
as $$
declare
  v_bad record;
begin
  select g.line_no, g.item_name, g.condition_label, g.actioned_qty, g.available_qty,
         s.name as store_name into v_bad
    from rms_private.store_analysis_groups(p_gs_id) g
    join public.intermediate_stores s on s.id = g.store_id
   where g.actioned_qty <> g.available_qty
     and (exists (select 1 from public.gs_store_analyses a
                   where a.gs_id = p_gs_id and a.store_id = g.store_id)
          or exists (select 1 from rms_private.store_analysis_groups(p_gs_id) g2
                      where g2.store_id = g.store_id and g2.actioned_qty > 0))
   order by g.line_no, g.sort_order
   limit 1;
  if found then
    raise exception 'G-21: % analysis, item line % (%)%: decisions total % pc(s), the item has % pc(s) to decide',
      v_bad.store_name, v_bad.line_no, v_bad.item_name,
      case when v_bad.condition_label is null then '' else ' condition ' || v_bad.condition_label end,
      v_bad.actioned_qty, v_bad.available_qty
      using errcode = 'P0001';
  end if;

  select gi.line_no, act.condition_label into v_bad
    from public.rm_item_actions act
    join public.gs_items gi on gi.id = act.gs_item_id
   where gi.gs_id = p_gs_id and act.is_current
     and not exists (select 1 from rms_private.store_analysis_groups(p_gs_id) g
                      where g.gs_item_id = act.gs_item_id
                        and g.condition_field_id is not distinct from act.condition_field_id
                        and g.store_id is not null)
   limit 1;
  if found then
    raise exception 'G-21: item line %: the decision% is not part of a store''s goods of this goods slip',
      v_bad.line_no,
      case when v_bad.condition_label is null then '' else ' for ' || v_bad.condition_label end
      using errcode = 'P0001';
  end if;
end;
$$;
revoke all on function rms_private.validate_store_analysis(uuid) from public, anon, authenticated;
grant execute on function rms_private.validate_store_analysis(uuid) to rms_api;

create or replace function rms_private.gs_store_analyses_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_status  text;
  v_store   record;
  v_prog    text;
  v_bad     record;
  v_rev     integer;
  v_total   integer;
  v_actor   uuid := rms_private.current_actor();
begin
  if tg_op <> 'INSERT' then
    raise exception 'DEC-69: a submitted store analysis is kept as history' using errcode = '42501';
  end if;
  select status into v_status from public.goods_slips where id = new.gs_id for update;
  if v_status is distinct from 'STORE_PROCESSING' then
    raise exception 'DEC-69: the analysis is submitted while the goods slip is in store processing (current status: %)',
      coalesce(v_status, 'missing') using errcode = '23514';
  end if;
  select code, name into v_store from public.intermediate_stores where id = new.store_id;
  if not coalesce(rms_private.user_holds_permission(v_actor, 'store_analysis', 'create')
                  and rms_private.user_acts_for_store(v_actor, new.store_id), false) then
    raise exception 'DEC-69: only a user of Intermediate Store % submits its analysis', coalesce(v_store.code, '?')
      using errcode = '42501';
  end if;
  select p.status into v_prog
    from rms_private.gs_store_routing_progress(new.gs_id) p where p.store_id = new.store_id;
  if v_prog is distinct from 'READY_FOR_ANALYSIS' then
    raise exception 'DEC-69: % has no goods ready for analysis on this goods slip (%)',
      v_store.name, coalesce(v_prog, 'no goods of this store') using errcode = '23514';
  end if;

  -- G-21: every item + condition of the store decided exactly.
  select g.line_no, g.condition_label, g.actioned_qty, g.available_qty into v_bad
    from rms_private.store_analysis_groups(new.gs_id) g
   where g.store_id = new.store_id and g.actioned_qty <> g.available_qty
   order by g.line_no, g.sort_order
   limit 1;
  if found then
    raise exception 'G-21: item line %: decisions total % pc(s), the item has % pc(s) to decide',
      v_bad.line_no::text
        || case when v_bad.condition_label is null then '' else ' condition ' || v_bad.condition_label end,
      v_bad.actioned_qty, v_bad.available_qty using errcode = 'P0001';
  end if;

  select coalesce(sum(g.actioned_qty), 0)::integer into v_total
    from rms_private.store_analysis_groups(new.gs_id) g where g.store_id = new.store_id;
  if v_total = 0 then
    raise exception 'DEC-69: % has nothing to analyse on this goods slip', v_store.name using errcode = '23514';
  end if;
  select coalesce(max(act.revision_no), 0) into v_rev
    from public.rm_item_actions act
    join public.gs_items gi on gi.id = act.gs_item_id
   where gi.gs_id = new.gs_id;

  new.store_code_snapshot := v_store.code;
  new.store_name_snapshot := v_store.name;
  new.revision_no := v_rev;
  new.total_qty := v_total;
  new.submitted_by := v_actor;
  new.submitted_at := now();
  new.remarks := nullif(btrim(coalesce(new.remarks, '')), '');
  return new;
end
$$;
revoke all on function rms_private.gs_store_analyses_guard() from public, anon, authenticated;
create trigger gs_store_analyses_guard
  before insert or update or delete on public.gs_store_analyses
  for each row execute function rms_private.gs_store_analyses_guard();

alter table public.gs_store_analyses enable row level security;
revoke all on public.gs_store_analyses from anon, authenticated;
grant select, insert on public.gs_store_analyses to rms_api;
select rms_private.attach_standard_triggers('public.gs_store_analyses');

-- ---------------------------------------------------------------------------------------------
-- 5. "Send for Management Approval" (P10 resolves the requests)
-- ---------------------------------------------------------------------------------------------
create table public.gs_management_approval_requests (
  id                  uuid primary key default gen_random_uuid(),
  gs_id               uuid not null references public.goods_slips (id) on delete restrict,
  store_id            uuid not null references public.intermediate_stores (id) on delete restrict,
  store_name_snapshot text not null,
  reason              text not null check (length(btrim(reason)) >= 3),
  status              text not null default 'OPEN' check (status in ('OPEN', 'RESOLVED')),
  requested_by        uuid not null default rms_private.current_actor()
                        references public.profiles (id) on delete restrict,
  requested_at        timestamptz not null default now(),
  created_at          timestamptz not null default now()
);
create unique index gs_mgmt_approval_requests_one_open
  on public.gs_management_approval_requests (gs_id) where status = 'OPEN';
create index gs_mgmt_approval_requests_store_idx on public.gs_management_approval_requests (store_id);
create index gs_mgmt_approval_requests_by_idx on public.gs_management_approval_requests (requested_by);
comment on table public.gs_management_approval_requests is
  'DEC-69 (target flow step 9): a store user sent the goods slip for Management approval (reason). One OPEN request per GS; Management resolves it (P10, DEC-70).';

create or replace function rms_private.gs_management_approval_requests_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_status  text;
  v_store   text;
  v_actor   uuid := rms_private.current_actor();
begin
  if tg_op <> 'INSERT' then
    -- P10 (DEC-70) adds the Management resolution; until then requests are history.
    raise exception 'DEC-69: a Management approval request is resolved by Management (P10)' using errcode = '42501';
  end if;
  select status into v_status from public.goods_slips where id = new.gs_id for update;
  if v_status is null or v_status not in ('STORE_PROCESSING', 'ANALYSIS_COMPLETED') then
    raise exception 'DEC-69: a goods slip is sent for Management approval during or after the store analysis (current status: %)',
      coalesce(v_status, 'missing') using errcode = '23514';
  end if;
  select name into v_store from public.intermediate_stores where id = new.store_id;
  if not coalesce(rms_private.user_holds_permission(v_actor, 'store_analysis', 'create')
                  and rms_private.user_acts_for_store(v_actor, new.store_id), false) then
    raise exception 'DEC-69: only a user of an Intermediate Store on the goods slip sends it for Management approval'
      using errcode = '42501';
  end if;
  if not exists (select 1 from rms_private.gs_store_routing_progress(new.gs_id) p
                  where p.store_id = new.store_id) then
    raise exception 'DEC-69: % has no goods on this goods slip', coalesce(v_store, '?') using errcode = '23514';
  end if;
  new.status := 'OPEN';
  new.store_name_snapshot := v_store;
  new.reason := btrim(new.reason);
  new.requested_by := v_actor;
  new.requested_at := now();
  return new;
end
$$;
revoke all on function rms_private.gs_management_approval_requests_guard() from public, anon, authenticated;
create trigger gs_management_approval_requests_guard
  before insert or update or delete on public.gs_management_approval_requests
  for each row execute function rms_private.gs_management_approval_requests_guard();

alter table public.gs_management_approval_requests enable row level security;
revoke all on public.gs_management_approval_requests from anon, authenticated;
grant select, insert on public.gs_management_approval_requests to rms_api;
select rms_private.attach_standard_triggers('public.gs_management_approval_requests');

-- ---------------------------------------------------------------------------------------------
-- 6. rm_item_actions guard (full body: 20261118000300 G4 body + the DEC-69 store branch first)
-- ---------------------------------------------------------------------------------------------
create or replace function rms_private.rm_item_actions_final_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_gs_id     uuid;
  v_line_no   integer;
  v_status    text;
  v_version   uuid;
  v_product   uuid;
  v_slip      record;
  v_cond      record;
  v_has_cond  boolean;
  v_store     uuid;
  v_store_nm  text;
  v_prog      text;
  v_actor     uuid := rms_private.current_actor();
begin
  select gi.gs_id, gi.product_id, gi.line_no into v_gs_id, v_product, v_line_no
    from public.gs_items gi where gi.id = new.gs_item_id;

  -- DEC-69 (P9): the store analysis of a goods slip on the Intermediate Store flow.
  if v_gs_id is not null and rms_private.gs_on_store_flow(v_gs_id) then
    select status, item_field_profile_version_id into v_status, v_version
      from public.goods_slips where id = v_gs_id for update;
    if tg_op = 'UPDATE'
       and ((to_jsonb(new) - 'is_current') <> (to_jsonb(old) - 'is_current')
            or not old.is_current or new.is_current) then
      raise exception 'G-18: a store decision is history; it is only retired by a newer one' using errcode = '42501';
    end if;
    if new.round_no <> 1 then
      raise exception 'DEC-69: the store analysis has a single round (no Pending re-action)' using errcode = '23514';
    end if;
    if v_status is distinct from 'STORE_PROCESSING' then
      raise exception 'DEC-69: the analysis changes only while the goods slip is in store processing (status %)',
        coalesce(v_status, 'missing') using errcode = '23514';
    end if;
    v_store := rms_private.gs_item_store(new.gs_item_id);
    if v_store is null then
      raise exception 'DEC-69: item line % is on no Intermediate Store''s transfer slip', v_line_no using errcode = '23514';
    end if;
    select name into v_store_nm from public.intermediate_stores where id = v_store;
    if not coalesce(rms_private.user_holds_permission(v_actor, 'store_analysis', 'create')
                    and rms_private.user_acts_for_store(v_actor, v_store), false) then
      raise exception 'DEC-69: item line % belongs to %; only a user of that store analyses it', v_line_no, v_store_nm
        using errcode = '42501';
    end if;
    if exists (select 1 from public.gs_store_analyses a where a.gs_id = v_gs_id and a.store_id = v_store) then
      raise exception 'DEC-69: % submitted its analysis of this goods slip; it can no longer change', v_store_nm
        using errcode = '23514';
    end if;
    select p.status into v_prog
      from rms_private.gs_store_routing_progress(v_gs_id) p where p.store_id = v_store;
    if v_prog is distinct from 'READY_FOR_ANALYSIS' then
      raise exception 'DEC-69: % goods of this goods slip are not ready for analysis (%)', v_store_nm, coalesce(v_prog, 'none')
        using errcode = '23514';
    end if;

    if tg_op = 'INSERT' and new.is_current then
      -- Q15: the store decides Dispatch New / Dispatch Repaired / Not Allowed. Issue CN is set by
      -- Management only (DEC-70, P10); Pending is not offered on new goods slips.
      if new.action_code in ('ISSUE_CN', 'PENDING_BP') then
        raise exception 'DEC-69: % is not a store analysis option (Issue CN is decided by Management, DEC-70)',
          new.action_code using errcode = '42501';
      end if;
      if not exists (
        select 1 from rms_private.resolve_item_field_profile(v_product, v_version) r
         where r.field_group = 'ACTION' and r.code = new.action_code
      ) then
        raise exception 'G-21: action % is not allowed by the resolved profile of this product',
          new.action_code using errcode = 'P0001';
      end if;
      v_has_cond := exists (select 1 from rms_private.item_current_conditions(new.gs_item_id));
      if v_has_cond then
        if new.condition_field_id is null then
          raise exception 'G-21: item line % has a condition split; every decision names its condition (DEC-57)',
            v_line_no using errcode = 'P0001';
        end if;
        select c.field_code, c.field_label into v_cond
          from rms_private.item_current_conditions(new.gs_item_id) c
         where c.field_id = new.condition_field_id;
        if not found then
          raise exception 'G-21: item line %: the condition is not in the item''s current condition split (DEC-57)',
            v_line_no using errcode = 'P0001';
        end if;
        new.condition_code := v_cond.field_code;
        new.condition_label := v_cond.field_label;
      elsif new.condition_field_id is not null then
        raise exception 'G-21: item line % has no condition split; its decisions name no condition',
          v_line_no using errcode = 'P0001';
      else
        new.condition_code := null;
        new.condition_label := null;
      end if;
    end if;
    return new;
  end if;

  if v_gs_id is null or not rms_private.gs_on_final_action_flow(v_gs_id) then
    return new;  -- P2-07 flow: unchanged
  end if;

  -- Serialise with department dispatches / receipts and other revisions of this GS (G-20 / G-21).
  select status, item_field_profile_version_id into v_status, v_version
    from public.goods_slips where id = v_gs_id for update;

  if new.round_no = 1 then
    if v_status is distinct from 'HELD_AT_INTERMEDIATE_STORE' then
      raise exception 'G-21: RM final actions change only while the goods slip is held at the intermediate store (status %)',
        v_status using errcode = 'P0001';
    end if;
  else
    -- DEC-57 (Q10): a Pending re-action follows a round Accounts completed and that was settled.
    if v_status is null or v_status not in ('IN_PROCESS', 'COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION') then
      raise exception 'G-21: Pending pieces are re-actioned only while the goods slip is open after the store stage (status %)',
        v_status using errcode = 'P0001';
    end if;
    if not rms_private.final_action_round_settled(v_gs_id, new.round_no - 1) then
      raise exception 'G-21: round % is not completed by Accounts and settled yet; its Pending pieces cannot be re-actioned',
        new.round_no - 1 using errcode = 'P0001';
    end if;
    if rms_private.final_action_pending_qty(v_gs_id, new.round_no - 1) = 0 then
      raise exception 'G-21: round % left no Pending pieces to re-action', new.round_no - 1
        using errcode = 'P0001';
    end if;
  end if;

  select slip_no, version_no into v_slip
    from public.ac_action_slips
   where gs_id = v_gs_id and round_no = new.round_no and status = 'CURRENT';
  if found then
    raise exception 'G-21: final actions are finalised on slip % v%; revise with a reason to supersede it first',
      v_slip.slip_no, v_slip.version_no using errcode = 'P0001';
  end if;

  if exists (select 1 from public.rm_item_actions act
               join public.gs_items gi on gi.id = act.gs_item_id
              where gi.gs_id = v_gs_id and act.is_current and act.round_no > new.round_no) then
    raise exception 'G-21: a later re-action round exists; round % can no longer change', new.round_no
      using errcode = 'P0001';
  end if;

  if tg_op = 'INSERT' and new.is_current then
    if not exists (
      select 1 from rms_private.resolve_item_field_profile(v_product, v_version) r
       where r.field_group = 'ACTION' and r.code = new.action_code
    ) then
      raise exception 'G-21: action % is not allowed by the resolved profile of this product',
        new.action_code using errcode = 'P0001';
    end if;

    -- DEC-57 (Q9): an item with a condition split is actioned per condition.
    v_has_cond := exists (select 1 from rms_private.item_current_conditions(new.gs_item_id));
    if v_has_cond then
      if new.condition_field_id is null then
        raise exception 'G-21: item line % has a condition split; every final action names its condition (DEC-57)',
          v_line_no using errcode = 'P0001';
      end if;
      select c.field_code, c.field_label into v_cond
        from rms_private.item_current_conditions(new.gs_item_id) c
       where c.field_id = new.condition_field_id;
      if not found then
        raise exception 'G-21: item line %: the condition is not in the item''s current condition split (DEC-57)',
          v_line_no using errcode = 'P0001';
      end if;
      new.condition_code := v_cond.field_code;
      new.condition_label := v_cond.field_label;
    elsif new.condition_field_id is not null then
      raise exception 'G-21: item line % has no condition split; its final actions name no condition',
        v_line_no using errcode = 'P0001';
    else
      new.condition_code := null;
      new.condition_label := null;
    end if;
  end if;
  return new;
end;
$$;
revoke all on function rms_private.rm_item_actions_final_guard() from public, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- 7. Deferred whole-GS G-21 check at commit (20261113001100 body + the store flow)
-- ---------------------------------------------------------------------------------------------
create or replace function rms_private.rm_item_actions_g21_deferred()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_gs_id uuid;
begin
  select gi.gs_id into v_gs_id from public.gs_items gi where gi.id = new.gs_item_id;
  if v_gs_id is null then
    return null;
  end if;
  if rms_private.gs_on_store_flow(v_gs_id) then
    perform rms_private.validate_store_analysis(v_gs_id);        -- DEC-69
    perform rms_private.validate_department_reconciliation(v_gs_id);
  elsif rms_private.gs_on_final_action_flow(v_gs_id) then
    perform rms_private.validate_final_action_split(v_gs_id, false);
    perform rms_private.validate_department_reconciliation(v_gs_id);
  end if;
  return null;
end;
$$;
revoke all on function rms_private.rm_item_actions_g21_deferred() from public, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- 8. Status chain (G-03 trigger, full body replaced: P7 body + ANALYSIS_COMPLETED)
-- ---------------------------------------------------------------------------------------------
create or replace function rms_private.goods_slips_g03_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_decision text;
begin
  -- original_category_code records the Step-3 choice and is kept for good (BR-08).
  if old.original_category_code is not null
     and new.original_category_code is distinct from old.original_category_code then
    raise exception 'G-03: the original category of a GS cannot change' using errcode = '23514';
  end if;

  select decision_code into v_decision
    from public.csr_approvals where gs_id = new.id and is_current;

  -- Category changes after Step-3: CSR -> RO only by a current CSR_REJECTED_TO_RO decision;
  -- RO -> CSR only when an admin reopened that decision (back to CSR_APPROVAL_PENDING).
  if old.category_code is not null and new.category_code is distinct from old.category_code then
    if not coalesce((old.category_code = 'CSR' and new.category_code is not distinct from 'RO'
                     and v_decision is not distinct from 'CSR_REJECTED_TO_RO')
                    or (old.category_code = 'RO' and new.category_code is not distinct from 'CSR'
                        and new.original_category_code is not distinct from 'CSR'
                        and v_decision is null
                        and new.status is not distinct from 'CSR_APPROVAL_PENDING'), false) then
      raise exception 'G-03: category % -> % needs a matching Replacement Manager decision',
        old.category_code, coalesce(new.category_code, 'none') using errcode = '23514';
    end if;
  end if;

  if new.status is not distinct from old.status or new.status = 'CANCELLED' then
    return new;
  end if;

  -- DEC-64 (a, b): items → popup. Replacement → CATEGORISATION, Complete Sales Return → hold.
  if old.status = 'ITEMIZATION' then
    if new.status not in ('CATEGORISATION', 'SALES_RETURN_HOLD') then
      raise exception 'G-03: counting is submitted to CATEGORISATION (Replacement) or SALES_RETURN_HOLD (Complete Sales Return), not %', new.status
        using errcode = '23514';
    end if;
    if not exists (select 1 from public.gs_items where gs_id = new.id) then
      raise exception 'G-01: counting cannot be submitted without item lines' using errcode = '23514';
    end if;
    if new.status = 'CATEGORISATION' then
      return new;
    end if;
    if new.status = 'SALES_RETURN_HOLD' then
      if new.category_code is distinct from 'CSR' then
        raise exception 'G-03: only a Complete Sales Return goes to SALES_RETURN_HOLD (DEC-64, Q11)'
          using errcode = '23514';
      end if;
      return new;
    end if;
  end if;

  if old.status = 'CATEGORISATION' then
    if not exists (select 1 from public.gs_items where gs_id = new.id) then
      raise exception 'G-01: a GS cannot be categorised without item lines' using errcode = '23514';
    end if;
    -- DEC-64 (c): the lock.
    if new.status = 'PENDING_TRANSFER_SLIP' then
      if new.category_code is distinct from 'RO' then
        raise exception 'G-03: only a Replacement GS is locked for transfer slips (DEC-64)' using errcode = '23514';
      end if;
      perform rms_private.validate_item_bucket_conservation(new.id);   -- G-19
      if new.categorisation_locked_at is null then
        raise exception 'DEC-64: PENDING_TRANSFER_SLIP needs the categorisation lock stamp' using errcode = '23514';
      end if;
      return new;
    end if;
    if new.status = 'RM_REVIEW' then
      raise exception 'DEC-64: categorisation is locked, not submitted to RM review any more' using errcode = '23514';
    end if;
    -- A legacy GS sent back by the RM has no category yet: its popup may still park it (Q11).
    if new.status = 'SALES_RETURN_HOLD' then
      if new.category_code is distinct from 'CSR' then
        raise exception 'G-03: only a Complete Sales Return goes to SALES_RETURN_HOLD (DEC-64, Q11)'
          using errcode = '23514';
      end if;
      return new;
    end if;

    -- Legacy path (P2-04 /categorize): category_code required
    if new.category_code is null then
      raise exception 'G-03: a GS cannot leave CATEGORISATION without a category' using errcode = '23514';
    end if;
    if new.category_code = 'CSR' and new.status <> 'CSR_APPROVAL_PENDING' then
      raise exception 'G-03: a Complete Sales Return must go to CSR_APPROVAL_PENDING (not %)', new.status
        using errcode = '23514';
    end if;
    if new.category_code = 'RO' and new.status <> 'INSPECTION' then
      raise exception 'G-03: Replacement Only goes to INSPECTION (not %)', new.status using errcode = '23514';
    end if;
    return new;
  end if;

  -- DEC-64 / Q11: a Complete Sales Return on hold has no further steps until that journey exists.
  if old.status = 'SALES_RETURN_HOLD' then
    raise exception 'G-03: a Complete Sales Return on hold cannot advance yet (DEC-64, Q11)' using errcode = '23514';
  end if;
  -- DEC-65 (P5): a locked GS leaves PENDING_TRANSFER_SLIP only when every physical line is on a
  -- live transfer slip; a void (Q10) brings it back while any line is uncovered.
  if old.status = 'PENDING_TRANSFER_SLIP' then
    if new.status = 'TRANSFER_SLIP_GENERATED' then
      if rms_private.gs_transfer_slip_gaps(new.id) > 0 then
        raise exception 'DEC-65: every physical line of the goods slip must be on a live transfer slip'
          using errcode = '23514';
      end if;
      return new;
    end if;
    raise exception 'G-03: a locked GS leaves PENDING_TRANSFER_SLIP only through its transfer slips (DEC-65), not to %', new.status
      using errcode = '23514';
  end if;
  -- DEC-67 (P7, Q29): the first department routing of any store (a store routes after its own
  -- acknowledgement, the other stores may still be acknowledging).
  if new.status = 'STORE_PROCESSING' then
    if old.status not in ('TRANSFER_SLIP_GENERATED', 'STORE_ACKNOWLEDGED') then
      raise exception 'G-03: STORE_PROCESSING is reached from the transfer slips / store acknowledgement (from %)', old.status
        using errcode = '23514';
    end if;
    if rms_private.gs_transfer_slip_gaps(new.id) > 0 or not rms_private.gs_routing_started(new.id) then
      raise exception 'DEC-67: STORE_PROCESSING needs the goods slip fully on transfer slips and a department routing'
        using errcode = '23514';
    end if;
    return new;
  end if;
  if old.status = 'TRANSFER_SLIP_GENERATED' then
    if new.status = 'PENDING_TRANSFER_SLIP' then
      if rms_private.gs_transfer_slip_gaps(new.id) = 0 then
        raise exception 'DEC-65: the goods slip is still fully on live transfer slips' using errcode = '23514';
      end if;
      return new;
    end if;
    -- DEC-66 (P6): every live slip of the GS acknowledged by its Intermediate Store.
    if new.status = 'STORE_ACKNOWLEDGED' then
      if not rms_private.gs_slips_acknowledged(new.id) then
        raise exception 'DEC-66: every transfer slip of the goods slip must be acknowledged by its store first'
          using errcode = '23514';
      end if;
      return new;
    end if;
    raise exception 'G-03: a goods slip on transfer slips goes to STORE_ACKNOWLEDGED (DEC-66), STORE_PROCESSING (DEC-67) or back to PENDING_TRANSFER_SLIP (Q10), not %', new.status
      using errcode = '23514';
  end if;
  -- DEC-66: an acknowledged GS goes back only when a slip of it is voided (Q10).
  if old.status = 'STORE_ACKNOWLEDGED' then
    if new.status = 'PENDING_TRANSFER_SLIP' then
      if rms_private.gs_transfer_slip_gaps(new.id) = 0 then
        raise exception 'DEC-65: the goods slip is still fully on live transfer slips' using errcode = '23514';
      end if;
      return new;
    end if;
    raise exception 'G-03: % is not reachable from STORE_ACKNOWLEDGED (department routing goes to STORE_PROCESSING, DEC-67)', new.status
      using errcode = '23514';
  end if;
  -- DEC-69 (P9): every Intermediate Store with goods on the GS submitted its analysis.
  if new.status = 'ANALYSIS_COMPLETED' then
    if old.status is distinct from 'STORE_PROCESSING' then
      raise exception 'G-03: ANALYSIS_COMPLETED is reached from STORE_PROCESSING (from %)', old.status
        using errcode = '23514';
    end if;
    if not rms_private.gs_store_analysis_complete(new.id) then
      raise exception 'DEC-69: every Intermediate Store on the goods slip must submit its analysis first'
        using errcode = '23514';
    end if;
    return new;
  end if;
  -- DEC-67 / DEC-69: Management approval and Accounts (P10–P11) add the other exits.
  if old.status = 'STORE_PROCESSING' then
    raise exception 'G-03: % is not reachable from STORE_PROCESSING (analysis goes to ANALYSIS_COMPLETED, DEC-69)', new.status
      using errcode = '23514';
  end if;
  if old.status = 'ANALYSIS_COMPLETED' then
    raise exception 'G-03: % is not reachable from ANALYSIS_COMPLETED yet (P10–P11)', new.status
      using errcode = '23514';
  end if;
  if new.status in ('PENDING_TRANSFER_SLIP', 'SALES_RETURN_HOLD', 'TRANSFER_SLIP_GENERATED',
                    'STORE_ACKNOWLEDGED') then
    raise exception 'G-03: % is reached only from counting / categorisation / transfer slips (from %)', new.status, old.status
      using errcode = '23514';
  end if;

  -- Phase 5 (AMD-12, AMD-13): RM_REVIEW transitions (legacy GSs)
  if old.status = 'RM_REVIEW' then
    if new.status = 'CATEGORISATION' then
      return new;   -- send back with remark
    end if;
    if new.status = 'HELD_AT_INTERMEDIATE_STORE' then
      perform rms_private.validate_item_bucket_conservation(new.id);
      return new;
    end if;
    if new.status = 'IN_PROCESS' then
      return new;   -- legacy Step-4 RO RM review
    end if;
  end if;

  if new.status = 'CATEGORISATION' and old.status <> 'RM_REVIEW' then
    raise exception 'G-03: only a GS in counting (ITEMIZATION) moves to CATEGORISATION (from %)', old.status
      using errcode = '23514';
  end if;

  if new.status = 'CSR_APPROVAL_PENDING' then
    if new.category_code is distinct from 'CSR' or v_decision is not null then
      raise exception 'G-03: CSR_APPROVAL_PENDING needs category CSR and no current decision'
        using errcode = '23514';
    end if;
    return new;
  end if;

  -- Leaving CSR_APPROVAL_PENDING (BR-08, DD r19-r20): only through the recorded decision.
  if old.status = 'CSR_APPROVAL_PENDING' then
    if v_decision is null then
      raise exception 'G-03: a Complete Sales Return cannot advance without the Replacement Manager''s decision'
        using errcode = '23514';
    end if;
    if v_decision = 'CSR_APPROVED' and (new.status <> 'IN_PROCESS'
                                         or new.category_code is distinct from 'CSR') then
      raise exception 'G-03: an approved CSR goes to IN_PROCESS as CSR (not %)', new.status using errcode = '23514';
    end if;
    if v_decision = 'CSR_REJECTED_TO_RO' and (new.status <> 'INSPECTION'
                                               or new.category_code is distinct from 'RO') then
      raise exception 'G-03: a rejected CSR is converted to RO and goes to INSPECTION (not %)', new.status
        using errcode = '23514';
    end if;
  end if;

  -- No CSR GS (nor one that was CSR) reaches inspection, handover or Stage-6 without a decision.
  if new.status in ('INSPECTION', 'RM_REVIEW', 'HELD_AT_INTERMEDIATE_STORE', 'IN_PROCESS',
                    'COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION', 'CLOSED')
     and 'CSR' in (new.category_code, new.original_category_code) and old.status not in ('RM_REVIEW', 'CATEGORISATION') then
    if (new.category_code = 'CSR' and v_decision is distinct from 'CSR_APPROVED')
       or (new.category_code = 'RO' and v_decision is distinct from 'CSR_REJECTED_TO_RO') then
      raise exception 'G-03: status % needs the Replacement Manager''s CSR decision', new.status
        using errcode = '23514';
    end if;
  end if;

  return new;
end
$$;
revoke all on function rms_private.goods_slips_g03_guard() from public, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- 9. Journey catalogue + notification event types (grants, menus, rules: seed.sql + snippet)
-- ---------------------------------------------------------------------------------------------
alter table public.journey_steps drop constraint if exists journey_steps_screen_key_check;
alter table public.journey_steps add constraint journey_steps_screen_key_check check (screen_key in (
  'journey-queue', 'gs-new', 'gs-list', 'dashboard', 'pendencies',
  'container-audit', 'reports', 'audit', 'custody', 'inventory', 'store-issues',
  'servicing', 'batteries', 'dismantling', 'scrap', 'credit-notes', 'approvals',
  'dispatch-queue', 'department-routing', 'department-receiving', 'department-issue',
  'accounts-entry', 'accounts-docs', 'dispatch-slips', 'transfer-slips', 'transfer-slip-acks',
  'store-routing', 'store-receiving', 'store-analysis'));

alter table public.journey_steps drop constraint if exists journey_steps_item_screen_key_check;
alter table public.journey_steps add constraint journey_steps_item_screen_key_check check (
  item_screen_key is null or item_screen_key in (
    'gs-detail', 'gs-unboxing', 'gs-itemization', 'gs-inspection', 'gs-rm-review',
    'custody-transfer', 'gs-final-actions', 'department-receiving', 'department-issue',
    'accounts-entry-gs', 'accounts-docs', 'dispatch-slips',
    'gs-party-notification', 'transfer-slips', 'transfer-slip', 'gs-store-routing',
    'gs-store-receiving', 'gs-store-analysis'));

alter table public.journey_steps drop constraint if exists journey_steps_queue_code_check;
alter table public.journey_steps add constraint journey_steps_queue_code_check check (
  queue_code is null or queue_code in (
    'CARTON_OPENING', 'COUNTING', 'CATEGORISATION', 'INSPECTION', 'RM_REVIEW', 'STORE_ACCEPT',
    'DEPT_ROUTING', 'DEPT_ISSUE', 'DEPT_RECEIVING', 'FINAL_ACTIONS', 'ACCOUNTS_DOCS',
    'ACCOUNTS_ENTRY', 'DISPATCH_SLIP', 'PARTY_EMAIL', 'PENDING_TRANSFER_SLIP', 'EDIT_REQUESTS',
    'STORE_ACK', 'STORE_ROUTING', 'STORE_RECEIVING', 'STORE_ANALYSIS'));

insert into public.journey_steps
  (code, label, hint, kind, screen_key, item_screen_key, queue_code, feature_code,
   perm_module, perm_action, sort_order, source_ref)
values
  ('STORE_ANALYSIS', 'Analysis',
   'Goods of your Intermediate Store back from departments (or with no work): decide Dispatch New, Dispatch Repaired or Not Allowed',
   'STEP', 'store-analysis', 'gs-store-analysis', 'STORE_ANALYSIS', null,
   'store_analysis', 'create', 60, 'DEC-69')
on conflict (code) do nothing;

insert into public.notification_event_types
  (code, label, description, category, default_priority, is_mandatory, source_ref, sort_order)
values
  ('STORE_ANALYSIS_SUBMITTED', 'Store analysis submitted',
   'DEC-69: an Intermediate Store submitted its analysis of a goods slip (Dispatch New / Dispatch Repaired / Not Allowed).',
   'WORKFLOW', 'NORMAL', false, 'DEC-69', 580),
  ('GS_ANALYSIS_COMPLETED', 'Analysis completed by every store',
   'DEC-69: every Intermediate Store with goods on the goods slip submitted its analysis.',
   'WORKFLOW', 'NORMAL', false, 'DEC-69', 582),
  ('MANAGEMENT_APPROVAL_REQUESTED', 'Sent for Management approval',
   'DEC-69 (target flow step 9): a store user sent a goods slip for Management approval with a reason.',
   'WORKFLOW', 'HIGH', false, 'DEC-69', 584)
on conflict (code) do update
  set label = excluded.label, description = excluded.description,
      default_priority = excluded.default_priority, source_ref = excluded.source_ref;

-- Default email templates of the new events (every event type has one; email itself is deferred,
-- Q22 — the in-app alert is what is sent today).
insert into public.notification_templates (event_type, channel, version_no, subject, body, change_reason)
select v.event_type, 'EMAIL', 1,
       '[{app_name}] {title}',
       E'Hello {recipient_name},

{title}

{body}

Event: {event_label}
Priority: {priority}
Open in RMS: {link}

— {app_name} (automated message; manage email preferences in RMS)',
       'P9 default'
  from (values ('STORE_ANALYSIS_SUBMITTED'), ('GS_ANALYSIS_COMPLETED'), ('MANAGEMENT_APPROVAL_REQUESTED')) as v(event_type)
 where not exists (select 1 from public.notification_templates t
                    where t.event_type = v.event_type and t.channel = 'EMAIL');
