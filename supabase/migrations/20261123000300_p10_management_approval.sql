-- =============================================================================================
-- Phase P10 (docs/RMS_PHASE_PROMPTS_20-11-2026.md) · DEC-70 (Q17 CONFIRMED, Q18 PROVISIONAL).
-- Management approval + system e-approval stamp + Issue CN (Steps 9–10 of the 20-11-2026 flow).
--
-- Once every Intermediate Store on a goods slip submitted its analysis (ANALYSIS_COMPLETED, P9),
-- MANAGEMENT (or Super Admin) may change any decision to any other (incl. ISSUE_CN and back),
-- move quantities between actions and add or remove decision lines of an item + condition, each
-- change with a reason (revision history: rm_item_actions revisions + gs_management_revisions),
-- then "Approve". Analysis moves no stock (DEC-69: the DEC-57 destinations are settled by the
-- Accounts / dispatch step, P11), so a Management change has nothing to correct in stock.
--
-- The approval is a system e-approval stamp (non-official, non-legal; no PKI / DSC; Q17): approver,
-- role, timestamp and the SHA-256 of a canonical JSON snapshot of the GS lines + current actions
-- (codes only, so an admin relabel never invalidates it), computed by the DB and stored in an
-- append-only table. Any later change of the lines / actions gives another hash: the approval is
-- then CHANGED and a new approval is needed.
--
-- Accounts gate (DEC-70 part; P11 adds the ANALYSIS_COMPLETED exit and the per-GS Replacement
-- Slip): a store-flow goods slip does not leave ANALYSIS_COMPLETED, and gets no A/c (Replacement)
-- slip, while a Management approval request is OPEN, while it holds ISSUE_CN without a VALID
-- approval (Q18), or while a Management change / approval is not covered by a VALID approval.
--
-- 1. Permission module management_approval (view / approve). Grants + menus: seed + snippet.
-- 2. Snapshot / hash / state helpers.
-- 3. gs_management_revisions (append-only header of each Management change, reason per change).
-- 4. gs_management_approvals (append-only, DB-computed snapshot + SHA-256) + request resolution.
-- 5. rm_item_actions guard (full body: P9 body + the DEC-70 Management branch for
--    ANALYSIS_COMPLETED, checked before the P9 store branch).
-- 6. Accounts gate: G-03 (full body: P9 body + the gate on leaving ANALYSIS_COMPLETED) and an
--    ac_action_slips insert guard for store-flow goods slips.
-- 7. Journey step MANAGEMENT_APPROVAL + notification event type.
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- 1. Permission
-- ---------------------------------------------------------------------------------------------
insert into public.permissions (module_code, action, description)
values
  ('management_approval', 'view',
   'See goods slips sent for Management approval and their approvals (DEC-70)'),
  ('management_approval', 'approve',
   'Change any final decision of an analysed goods slip (incl. Issue CN) and approve it with the e-approval stamp (DEC-70)')
on conflict (module_code, action) do nothing;

insert into public.role_permissions (role_id, permission_id, scope)
select r.id, p.id, 'all'
  from public.roles r
  join public.permissions p on p.module_code = 'management_approval'
 where r.code = 'SUPER_ADMIN'
on conflict (role_id, permission_id) do nothing;

-- ---------------------------------------------------------------------------------------------
-- 2. Snapshot, hash, state
-- ---------------------------------------------------------------------------------------------
-- DEC-70 (Q17): the canonical snapshot of a goods slip's lines + current decisions. Codes only (an
-- admin relabel does not change it); arrays in a fixed order; jsonb text is canonical (sorted keys,
-- no insignificant whitespace), so the same decisions always give the same text and hash.
create or replace function rms_private.gs_management_snapshot(p_gs_id uuid)
returns jsonb
language sql
stable
set search_path = ''
as $$
  select jsonb_build_object(
           'format', 'RMS-DEC70-v1',
           'gs_id', g.id,
           'gs_no', g.gs_no,
           'lines', coalesce((
             select jsonb_agg(l.line order by l.line_no, l.cond)
               from (select gi.line_no,
                            coalesce(a.condition_code, '') as cond,
                            jsonb_build_object(
                              'line_no', gi.line_no,
                              'gs_item_id', gi.id,
                              'product_code', coalesce(gi.product_code_snapshot, pr.code),
                              'received_qty', gi.received_qty,
                              'store_code', s.code,
                              'condition_code', a.condition_code,
                              'actions', jsonb_agg(jsonb_build_object('action_code', a.action_code,
                                                                      'qty', a.qty)
                                                   order by a.action_code)) as line
                       from public.rm_item_actions a
                       join public.gs_items gi on gi.id = a.gs_item_id
                       left join public.products pr on pr.id = gi.product_id
                       left join public.intermediate_stores s on s.id = rms_private.gs_item_store(gi.id)
                      where gi.gs_id = g.id and a.is_current and a.round_no = 1
                      group by gi.line_no, gi.id, gi.product_code_snapshot, pr.code, gi.received_qty,
                               s.code, a.condition_code) l), '[]'::jsonb))
    from public.goods_slips g
   where g.id = p_gs_id
$$;
revoke all on function rms_private.gs_management_snapshot(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_management_snapshot(uuid) to rms_api;

create or replace function rms_private.management_snapshot_sha256(p_snapshot jsonb)
returns text
language sql
immutable
set search_path = ''
as $$
  select encode(pg_catalog.sha256(convert_to(p_snapshot::text, 'UTF8')), 'hex')
$$;
revoke all on function rms_private.management_snapshot_sha256(jsonb) from public, anon, authenticated;
grant execute on function rms_private.management_snapshot_sha256(jsonb) to rms_api;
comment on function rms_private.management_snapshot_sha256(jsonb) is
  'DEC-70 (Q17): SHA-256 (hex) of the canonical jsonb text of a Management approval snapshot.';

-- ---------------------------------------------------------------------------------------------
-- 3. Management change history (reason per change)
-- ---------------------------------------------------------------------------------------------
create table public.gs_management_revisions (
  id           uuid primary key default gen_random_uuid(),
  gs_id        uuid not null references public.goods_slips (id) on delete restrict,
  revision_no  integer not null check (revision_no >= 1),
  -- [{line_no, product_name, condition_label, before:[{action_code,label,qty}], after:[...], reason}]
  changes      jsonb not null check (jsonb_typeof(changes) = 'array' and jsonb_array_length(changes) > 0),
  made_by      uuid not null default rms_private.current_actor()
                 references public.profiles (id) on delete restrict,
  made_at      timestamptz not null default now(),
  created_at   timestamptz not null default now(),
  unique (gs_id, revision_no)
);
create index gs_management_revisions_made_by_idx on public.gs_management_revisions (made_by);
comment on table public.gs_management_revisions is
  'DEC-70: one row per Management change of an analysed goods slip (the rm_item_actions revision it wrote, before / after per item + condition, reason per change). Append-only.';

create or replace function rms_private.gs_management_revisions_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_status text;
  v_actor  uuid := rms_private.current_actor();
begin
  if tg_op <> 'INSERT' then
    raise exception 'DEC-70: a Management change is kept as history' using errcode = '42501';
  end if;
  if not coalesce(rms_private.user_holds_permission(v_actor, 'management_approval', 'approve'), false) then
    raise exception 'DEC-70: only Management changes an analysed goods slip' using errcode = '42501';
  end if;
  select status into v_status from public.goods_slips where id = new.gs_id for update;
  if v_status is distinct from 'ANALYSIS_COMPLETED' then
    raise exception 'DEC-70: Management changes the decisions once every store submitted its analysis (status %)',
      coalesce(v_status, 'missing') using errcode = '23514';
  end if;
  if exists (select 1 from jsonb_array_elements(new.changes) e
              where length(btrim(coalesce(e ->> 'reason', ''))) < 3) then
    raise exception 'DEC-70: every Management change carries a reason (at least 3 characters)'
      using errcode = '23514';
  end if;
  if not exists (select 1 from public.rm_item_actions a
                   join public.gs_items gi on gi.id = a.gs_item_id
                  where gi.gs_id = new.gs_id and a.revision_no = new.revision_no and a.is_current) then
    raise exception 'DEC-70: revision % has no decisions on this goods slip', new.revision_no
      using errcode = '23514';
  end if;
  new.made_by := v_actor;
  new.made_at := now();
  return new;
end
$$;
revoke all on function rms_private.gs_management_revisions_guard() from public, anon, authenticated;
create trigger gs_management_revisions_guard
  before insert or update or delete on public.gs_management_revisions
  for each row execute function rms_private.gs_management_revisions_guard();

alter table public.gs_management_revisions enable row level security;
revoke all on public.gs_management_revisions from anon, authenticated;
grant select, insert on public.gs_management_revisions to rms_api;
select rms_private.attach_standard_triggers('public.gs_management_revisions');

-- ---------------------------------------------------------------------------------------------
-- 4. Approvals (append-only) and the resolution of "Send for Management Approval" requests
-- ---------------------------------------------------------------------------------------------
create table public.gs_management_approvals (
  id                      uuid primary key default gen_random_uuid(),
  gs_id                   uuid not null references public.goods_slips (id) on delete restrict,
  approval_no             integer not null check (approval_no >= 1),
  request_id              uuid references public.gs_management_approval_requests (id) on delete restrict,
  approver_id             uuid not null default rms_private.current_actor()
                            references public.profiles (id) on delete restrict,
  approver_name_snapshot  text not null,
  approver_role_snapshot  text not null,
  approved_at             timestamptz not null default now(),
  revision_no             integer not null check (revision_no >= 0),
  snapshot                jsonb not null check (jsonb_typeof(snapshot) = 'object'),
  snapshot_sha256         text not null check (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
  has_issue_cn            boolean not null default false,
  remarks                 text,
  created_at              timestamptz not null default now(),
  unique (gs_id, approval_no)
);
create index gs_management_approvals_approver_idx on public.gs_management_approvals (approver_id);
create index gs_management_approvals_request_idx on public.gs_management_approvals (request_id);
comment on table public.gs_management_approvals is
  'DEC-70 (Q17): system e-approval stamp of Management (non-official, non-legal; no PKI): approver, role, time and the SHA-256 of the canonical snapshot of the GS lines + decisions. Append-only; the latest one is VALID while the current snapshot has the same hash.';

-- Latest approval of a goods slip: NONE | VALID (current snapshot = approved snapshot) | CHANGED.
create or replace function rms_private.gs_management_approval_state(p_gs_id uuid)
returns text
language sql
stable
set search_path = ''
as $$
  select case
           when a.id is null then 'NONE'
           when a.snapshot_sha256 = rms_private.management_snapshot_sha256(rms_private.gs_management_snapshot(p_gs_id))
                and a.snapshot_sha256 = rms_private.management_snapshot_sha256(a.snapshot) then 'VALID'
           else 'CHANGED'
         end
    from (select 1) one
    left join lateral (select x.id, x.snapshot, x.snapshot_sha256
                         from public.gs_management_approvals x
                        where x.gs_id = p_gs_id
                        order by x.approval_no desc limit 1) a on true
$$;
revoke all on function rms_private.gs_management_approval_state(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_management_approval_state(uuid) to rms_api;

-- DEC-70 / Q18: why a store-flow goods slip may not reach Accounts yet (NULL = it may).
create or replace function rms_private.gs_management_gate_problem(p_gs_id uuid)
returns text
language plpgsql
stable
set search_path = ''
as $$
declare
  v_state text;
begin
  if exists (select 1 from public.gs_management_approval_requests r
              where r.gs_id = p_gs_id and r.status = 'OPEN') then
    return 'DEC-70: the goods slip waits for Management approval (sent by a store)';
  end if;
  v_state := rms_private.gs_management_approval_state(p_gs_id);
  if v_state <> 'VALID'
     and exists (select 1 from public.rm_item_actions a
                   join public.gs_items gi on gi.id = a.gs_item_id
                  where gi.gs_id = p_gs_id and a.is_current and a.action_code = 'ISSUE_CN') then
    return 'DEC-70 (Q18): the goods slip has Issue CN; it needs a valid Management approval before Accounts';
  end if;
  if v_state = 'CHANGED' then
    return 'DEC-70: the goods slip changed after its Management approval; it needs a new approval';
  end if;
  if v_state = 'NONE' and exists (select 1 from public.gs_management_revisions m where m.gs_id = p_gs_id) then
    return 'DEC-70: Management changed the goods slip; it needs Management approval';
  end if;
  return null;
end
$$;
revoke all on function rms_private.gs_management_gate_problem(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_management_gate_problem(uuid) to rms_api;

create or replace function rms_private.gs_management_approvals_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_status  text;
  v_actor   uuid := rms_private.current_actor();
  v_name    text;
  v_role    text;
  v_super   boolean;
  v_last    text;
begin
  if tg_op <> 'INSERT' then
    raise exception 'DEC-70: a Management approval is immutable (append-only)' using errcode = '42501';
  end if;
  if not coalesce(rms_private.user_holds_permission(v_actor, 'management_approval', 'approve'), false) then
    raise exception 'DEC-70: only Management approves a goods slip' using errcode = '42501';
  end if;
  select status into v_status from public.goods_slips where id = new.gs_id for update;
  if v_status is distinct from 'ANALYSIS_COMPLETED' then
    raise exception 'DEC-70: a goods slip is approved once every store submitted its analysis (status %)',
      coalesce(v_status, 'missing') using errcode = '23514';
  end if;
  perform rms_private.validate_store_analysis(new.gs_id);   -- G-21: every piece decided

  -- The DB computes the snapshot and its hash; whatever the caller sent is replaced.
  new.snapshot := rms_private.gs_management_snapshot(new.gs_id);
  new.snapshot_sha256 := rms_private.management_snapshot_sha256(new.snapshot);
  new.has_issue_cn := exists (select 1 from jsonb_array_elements(new.snapshot -> 'lines') l,
                                            jsonb_array_elements(l -> 'actions') a
                               where a ->> 'action_code' = 'ISSUE_CN');
  select r.id into new.request_id
    from public.gs_management_approval_requests r
   where r.gs_id = new.gs_id and r.status = 'OPEN';
  select x.snapshot_sha256 into v_last
    from public.gs_management_approvals x
   where x.gs_id = new.gs_id order by x.approval_no desc limit 1;
  if v_last = new.snapshot_sha256 and new.request_id is null then
    raise exception 'DEC-70: the goods slip is already approved as it is (nothing changed since)'
      using errcode = '23514';
  end if;

  select p.full_name, p.is_super_admin into v_name, v_super from public.profiles p where p.id = v_actor;
  select r.name into v_role
    from public.user_roles ur
    join public.roles r on r.id = ur.role_id
    join public.role_permissions rp on rp.role_id = r.id
    join public.permissions pm on pm.id = rp.permission_id
   where ur.user_id = v_actor and pm.module_code = 'management_approval' and pm.action = 'approve'
     and r.code <> 'SUPER_ADMIN'
   order by r.name limit 1;
  new.approver_id := v_actor;
  new.approver_name_snapshot := coalesce(v_name, '?');
  new.approver_role_snapshot := coalesce(v_role, case when v_super then 'Super Admin' end, 'Management');
  new.approved_at := now();
  new.approval_no := coalesce((select max(x.approval_no) from public.gs_management_approvals x
                                where x.gs_id = new.gs_id), 0) + 1;
  new.revision_no := coalesce((select max(a.revision_no) from public.rm_item_actions a
                                 join public.gs_items gi on gi.id = a.gs_item_id
                                where gi.gs_id = new.gs_id), 0);
  new.remarks := nullif(btrim(coalesce(new.remarks, '')), '');
  return new;
end
$$;
revoke all on function rms_private.gs_management_approvals_guard() from public, anon, authenticated;
create trigger gs_management_approvals_guard
  before insert or update or delete on public.gs_management_approvals
  for each row execute function rms_private.gs_management_approvals_guard();

-- The approval resolves the open "Send for Management Approval" request in the same transaction.
create or replace function rms_private.gs_management_approvals_resolve()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.request_id is not null then
    update public.gs_management_approval_requests
       set status = 'RESOLVED', approval_id = new.id
     where id = new.request_id and status = 'OPEN';
  end if;
  return null;
end
$$;
revoke all on function rms_private.gs_management_approvals_resolve() from public, anon, authenticated;
create trigger gs_management_approvals_resolve
  after insert on public.gs_management_approvals
  for each row execute function rms_private.gs_management_approvals_resolve();

alter table public.gs_management_approvals enable row level security;
revoke all on public.gs_management_approvals from anon, authenticated;
grant select, insert on public.gs_management_approvals to rms_api;
select rms_private.attach_standard_triggers('public.gs_management_approvals');

alter table public.gs_management_approval_requests
  add column resolved_by  uuid references public.profiles (id) on delete restrict,
  add column resolved_at  timestamptz,
  add column approval_id  uuid references public.gs_management_approvals (id) on delete restrict;
create index gs_mgmt_approval_requests_resolved_by_idx on public.gs_management_approval_requests (resolved_by);
create index gs_mgmt_approval_requests_approval_idx on public.gs_management_approval_requests (approval_id);
alter table public.gs_management_approval_requests
  add constraint gs_mgmt_approval_requests_resolved_fields check (
    (status = 'OPEN' and resolved_by is null and resolved_at is null and approval_id is null)
    or (status = 'RESOLVED' and resolved_by is not null and resolved_at is not null and approval_id is not null));
grant update (status, resolved_by, resolved_at, approval_id) on public.gs_management_approval_requests to rms_api;

-- Full body of the request guard (20261123000200 body + the DEC-70 resolution).
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
  if tg_op = 'UPDATE' then
    -- DEC-70: Management resolves an OPEN request by approving the goods slip (only the
    -- resolution columns change; the request itself is history).
    if old.status <> 'OPEN' or new.status <> 'RESOLVED'
       or (to_jsonb(new) - array['status', 'resolved_by', 'resolved_at', 'approval_id', 'updated_at'])
          <> (to_jsonb(old) - array['status', 'resolved_by', 'resolved_at', 'approval_id', 'updated_at']) then
      raise exception 'DEC-70: a Management approval request is only resolved (OPEN → RESOLVED) by an approval'
        using errcode = '42501';
    end if;
    if not coalesce(rms_private.user_holds_permission(v_actor, 'management_approval', 'approve'), false) then
      raise exception 'DEC-70: only Management resolves a Management approval request' using errcode = '42501';
    end if;
    if not exists (select 1 from public.gs_management_approvals a
                    where a.id = new.approval_id and a.gs_id = new.gs_id) then
      raise exception 'DEC-70: the request is resolved by an approval of the same goods slip' using errcode = '23514';
    end if;
    new.resolved_by := v_actor;
    new.resolved_at := now();
    return new;
  end if;
  if tg_op <> 'INSERT' then
    raise exception 'DEC-69: a Management approval request is kept as history' using errcode = '42501';
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
  -- Q36 (user 2026-11-23): the store submits its own analysis first.
  if not exists (select 1 from public.gs_store_analyses a
                  where a.gs_id = new.gs_id and a.store_id = new.store_id) then
    raise exception 'DEC-69 (Q36): % submits its own analysis of this goods slip before sending it for Management approval',
      coalesce(v_store, '?') using errcode = '23514';
  end if;
  new.status := 'OPEN';
  new.store_name_snapshot := v_store;
  new.reason := btrim(new.reason);
  new.requested_by := v_actor;
  new.requested_at := now();
  new.resolved_by := null;
  new.resolved_at := null;
  new.approval_id := null;
  return new;
end
$$;
revoke all on function rms_private.gs_management_approval_requests_guard() from public, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- 5. rm_item_actions guard (full body: 20261123000100 body + the DEC-70 Management branch)
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

    -- DEC-70 (P10): once every store submitted (ANALYSIS_COMPLETED) only Management changes the
    -- decisions: any action to any other (incl. ISSUE_CN and back), with a reason per change.
    if v_status = 'ANALYSIS_COMPLETED' then
      if tg_op = 'UPDATE'
         and ((to_jsonb(new) - 'is_current') <> (to_jsonb(old) - 'is_current')
              or not old.is_current or new.is_current) then
        raise exception 'G-18: a decision is history; it is only retired by a newer one' using errcode = '42501';
      end if;
      if not coalesce(rms_private.user_holds_permission(v_actor, 'management_approval', 'approve'), false) then
        raise exception 'DEC-70: after the analysis only Management changes the decisions of item line % (and sets Issue CN)',
          v_line_no using errcode = '42501';
      end if;
      if new.round_no <> 1 then
        raise exception 'DEC-69: the store analysis has a single round (no Pending re-action)' using errcode = '23514';
      end if;
      if tg_op = 'INSERT' and new.is_current then
        if new.action_code = 'PENDING_BP' then
          raise exception 'DEC-70: Pending is not used on the Intermediate Store flow (DEC-69)' using errcode = '23514';
        end if;
        if length(btrim(coalesce(new.reason, ''))) < 3 then
          raise exception 'DEC-70: every Management change carries a reason (item line %)', v_line_no
            using errcode = '23514';
        end if;
        if rms_private.gs_item_store(new.gs_item_id) is null then
          raise exception 'DEC-70: item line % is on no Intermediate Store''s transfer slip', v_line_no
            using errcode = '23514';
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
-- 6. Accounts gate: G-03 status chain (full body: 20261123000100 body + the DEC-70 gate)
-- ---------------------------------------------------------------------------------------------
create or replace function rms_private.goods_slips_g03_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_decision text;
  v_problem  text;
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
    -- DEC-70 / Q18: no open Management approval request, Issue CN only with a valid approval,
    -- no Management change without a valid approval. P11 adds the Accounts exit itself.
    v_problem := rms_private.gs_management_gate_problem(new.id);
    if v_problem is not null then
      raise exception '%', v_problem using errcode = '23514';
    end if;
    raise exception 'G-03: % is not reachable from ANALYSIS_COMPLETED yet (Accounts, P11)', new.status
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

-- DEC-70 / DEC-71: the A/c (Replacement) slip of a store-flow goods slip is created only when the
-- Management gate passes (no open request; Issue CN only with a VALID approval; no unapproved
-- Management change). Legacy goods slips are unchanged.
create or replace function rms_private.ac_action_slips_dec70_gate()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_problem text;
begin
  if rms_private.gs_on_store_flow(new.gs_id) then
    v_problem := rms_private.gs_management_gate_problem(new.gs_id);
    if v_problem is not null then
      raise exception '%', v_problem using errcode = '23514';
    end if;
  end if;
  return new;
end
$$;
revoke all on function rms_private.ac_action_slips_dec70_gate() from public, anon, authenticated;
create trigger ac_action_slips_dec70_gate
  before insert on public.ac_action_slips
  for each row execute function rms_private.ac_action_slips_dec70_gate();

-- ---------------------------------------------------------------------------------------------
-- 7. Journey catalogue + notification event type (grants, menus, rules: seed.sql + snippet)
-- ---------------------------------------------------------------------------------------------
alter table public.journey_steps drop constraint if exists journey_steps_screen_key_check;
alter table public.journey_steps add constraint journey_steps_screen_key_check check (screen_key in (
  'journey-queue', 'gs-new', 'gs-list', 'dashboard', 'pendencies',
  'container-audit', 'reports', 'audit', 'custody', 'inventory', 'store-issues',
  'servicing', 'batteries', 'dismantling', 'scrap', 'credit-notes', 'approvals',
  'dispatch-queue', 'department-routing', 'department-receiving', 'department-issue',
  'accounts-entry', 'accounts-docs', 'dispatch-slips', 'transfer-slips', 'transfer-slip-acks',
  'store-routing', 'store-receiving', 'store-analysis', 'management-approval'));

alter table public.journey_steps drop constraint if exists journey_steps_item_screen_key_check;
alter table public.journey_steps add constraint journey_steps_item_screen_key_check check (
  item_screen_key is null or item_screen_key in (
    'gs-detail', 'gs-unboxing', 'gs-itemization', 'gs-inspection', 'gs-rm-review',
    'custody-transfer', 'gs-final-actions', 'department-receiving', 'department-issue',
    'accounts-entry-gs', 'accounts-docs', 'dispatch-slips',
    'gs-party-notification', 'transfer-slips', 'transfer-slip', 'gs-store-routing',
    'gs-store-receiving', 'gs-store-analysis', 'gs-management-approval'));

alter table public.journey_steps drop constraint if exists journey_steps_queue_code_check;
alter table public.journey_steps add constraint journey_steps_queue_code_check check (
  queue_code is null or queue_code in (
    'CARTON_OPENING', 'COUNTING', 'CATEGORISATION', 'INSPECTION', 'RM_REVIEW', 'STORE_ACCEPT',
    'DEPT_ROUTING', 'DEPT_ISSUE', 'DEPT_RECEIVING', 'FINAL_ACTIONS', 'ACCOUNTS_DOCS',
    'ACCOUNTS_ENTRY', 'DISPATCH_SLIP', 'PARTY_EMAIL', 'PENDING_TRANSFER_SLIP', 'EDIT_REQUESTS',
    'STORE_ACK', 'STORE_ROUTING', 'STORE_RECEIVING', 'STORE_ANALYSIS', 'MANAGEMENT_APPROVAL'));

insert into public.journey_steps
  (code, label, hint, kind, screen_key, item_screen_key, queue_code, feature_code,
   perm_module, perm_action, sort_order, source_ref)
values
  ('MANAGEMENT_APPROVAL', 'Management Approval',
   'Goods slips sent by a store for Management approval: review, change any decision (incl. Issue CN) and approve',
   'STEP', 'management-approval', 'gs-management-approval', 'MANAGEMENT_APPROVAL', null,
   'management_approval', 'approve', 65, 'DEC-70')
on conflict (code) do nothing;

insert into public.notification_event_types
  (code, label, description, category, default_priority, is_mandatory, source_ref, sort_order)
values
  ('GS_MANAGEMENT_APPROVED', 'Approved by Management',
   'DEC-70: Management approved a goods slip (e-approval stamp; with Issue CN where decided).',
   'WORKFLOW', 'NORMAL', false, 'DEC-70', 586)
on conflict (code) do update
  set label = excluded.label, description = excluded.description,
      default_priority = excluded.default_priority, source_ref = excluded.source_ref;

-- DEC-70 (Q17): the stamp wording is configuration (Admin → Settings), printed before
-- "— <approver>, <date time>, ref <short hash>".
insert into public.system_settings (key, value, category, description, source_ref) values
  ('management_approval_stamp_title', '"Digitally approved by Management"'::jsonb, 'branding',
   'Title of the Management e-approval stamp on the goods slip page, the Replacement Slip and the Dispatch Slip (DEC-70; a non-official, non-legal system stamp).',
   'DEC-70')
on conflict (key) do nothing;

-- Default email template (every event type has one; email itself is deferred, Q22).
insert into public.notification_templates (event_type, channel, version_no, subject, body, change_reason)
select 'GS_MANAGEMENT_APPROVED', 'EMAIL', 1,
       '[{app_name}] {title}',
       E'Hello {recipient_name},

{title}

{body}

Event: {event_label}
Priority: {priority}
Open in RMS: {link}

— {app_name} (automated message; manage email preferences in RMS)',
       'P10 default'
 where not exists (select 1 from public.notification_templates t
                    where t.event_type = 'GS_MANAGEMENT_APPROVED' and t.channel = 'EMAIL');
