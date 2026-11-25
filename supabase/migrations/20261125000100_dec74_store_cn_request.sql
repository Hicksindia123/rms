-- =============================================================================================
-- DEC-74 (user request 2026-11-25): "Issue CN Request" from the Intermediate Store analysis.
--
-- In the store analysis (DEC-69) a store user may not set Issue CN (DEC-70: Management only). They
-- may now put pieces of an item + condition on **Issue CN Request** (stable code
-- ISSUE_CN_REQUEST) with a quantity. It is one more decision in the G-21 split (rm_item_actions
-- round 1, G-18 label snapshot), so the store's part still totals its pieces. Management then
-- decides those pieces: Issue CN, or any other action (P10 change with a reason per item +
-- condition). Until every requested piece is decided:
--   * the goods slip does not reach Accounts (rms_private.gs_management_gate_problem; G-03 exit of
--     ANALYSIS_COMPLETED and the Replacement Slip insert already call it), and
--   * Management cannot approve it (gs_management_approvals guard).
-- The request option is an ACTION library entry with no Accounts flags and no profile assignment:
-- it is offered to a store when the entry is active (Admin can switch it off) and the product's
-- resolved profile has a credit-note action (requires_cn, AMD-18), so goods slips created under an
-- older profile version get it too. It is never an RM (legacy) or Management option.
--
-- 1. ACTION library entry ISSUE_CN_REQUEST "Issue CN Request" (label = configuration, rule e).
-- 2. Helpers rms_private.cn_request_allowed, rms_private.gs_open_cn_request_qty.
-- 3. rm_item_actions guard (full body: 20261123000300 body + the DEC-74 branches: store, Management,
--    and a refusal on every RM flow, incl. the P2-07 item actions).
-- 4. Accounts gate (full body: 20261123000300 body + the DEC-74 check first).
-- 5. Management approval guard (full body: 20261123000300 body + the DEC-74 check).
-- Guards G-01…G-22 are unchanged (G-21 totals now simply include the request lines).
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- 1. Library entry (not system-assigned: never part of a profile's ACTION group by default)
-- ---------------------------------------------------------------------------------------------
insert into public.item_field_library
  (field_group, code, label, description, sort_order, is_active, is_system, requires_cn,
   requires_challan, source_ref)
values
  ('ACTION', 'ISSUE_CN_REQUEST', 'Issue CN Request',
   'Store analysis only: the store asks Management to decide a credit note for these pieces (DEC-74). Switch off to hide it from the stores.',
   35, true, false, false, false, 'DEC-74')
on conflict (field_group, code) do nothing;

-- ---------------------------------------------------------------------------------------------
-- 2. Helpers
-- ---------------------------------------------------------------------------------------------
-- DEC-74: may a store put pieces of this product on Issue CN Request (GS profile version)?
create or replace function rms_private.cn_request_allowed(p_product_id uuid, p_version_id uuid)
returns boolean
language sql
stable
set search_path = ''
as $$
  select exists (select 1 from public.item_field_library l
                  where l.field_group = 'ACTION' and l.code = 'ISSUE_CN_REQUEST' and l.is_active)
     and exists (select 1 from rms_private.resolve_item_field_profile(p_product_id, p_version_id) r
                  where r.field_group = 'ACTION' and r.requires_cn)
$$;
revoke all on function rms_private.cn_request_allowed(uuid, uuid) from public, anon, authenticated;
grant execute on function rms_private.cn_request_allowed(uuid, uuid) to rms_api;

-- DEC-74: pieces of a goods slip still on Issue CN Request (current decisions).
create or replace function rms_private.gs_open_cn_request_qty(p_gs_id uuid)
returns integer
language sql
stable
set search_path = ''
as $$
  select coalesce(sum(a.qty), 0)::integer
    from public.rm_item_actions a
    join public.gs_items gi on gi.id = a.gs_item_id
   where gi.gs_id = p_gs_id and a.is_current and a.action_code = 'ISSUE_CN_REQUEST'
$$;
revoke all on function rms_private.gs_open_cn_request_qty(uuid) from public, anon, authenticated;
grant execute on function rms_private.gs_open_cn_request_qty(uuid) to rms_api;

-- ---------------------------------------------------------------------------------------------
-- 3. rm_item_actions guard (full body: 20261123000300 body + DEC-74)
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
        -- DEC-74: Issue CN Request is a store's request; Management answers it with Issue CN or
        -- another action, never by writing a request itself.
        if new.action_code = 'ISSUE_CN_REQUEST' then
          raise exception 'DEC-74: Issue CN Request is raised by a store; Management decides Issue CN or another action for item line %',
            v_line_no using errcode = '23514';
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
      if new.action_code = 'ISSUE_CN_REQUEST' then
        -- DEC-74: the store asks Management for a credit note on these pieces. Offered while the
        -- request option is active and the product's resolved profile has a credit-note action
        -- (requires_cn flag, AMD-18), so goods slips on older profile versions get it too.
        if not rms_private.cn_request_allowed(v_product, v_version) then
          raise exception 'DEC-74: Issue CN Request is not available for item line % (no credit-note action in its profile, or the option is switched off)',
            v_line_no using errcode = '23514';
        end if;
      elsif not exists (
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

  -- DEC-74: outside the store analysis the request is never a decision (RM flows).
  if tg_op = 'INSERT' and new.action_code = 'ISSUE_CN_REQUEST' then
    raise exception 'DEC-74: Issue CN Request is used only by the Intermediate Store analysis'
      using errcode = '23514';
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
-- 4. Accounts gate (full body: 20261123000300 body + DEC-74)
-- ---------------------------------------------------------------------------------------------
create or replace function rms_private.gs_management_gate_problem(p_gs_id uuid)
returns text
language plpgsql
stable
set search_path = ''
as $$
declare
  v_state text;
begin
  -- DEC-74: a store's Issue CN Request is answered by Management before Accounts.
  if rms_private.gs_open_cn_request_qty(p_gs_id) > 0 then
    return 'DEC-74: a store raised an Issue CN Request; Management decides those pieces (Issue CN or another action) and approves';
  end if;
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

-- ---------------------------------------------------------------------------------------------
-- 5. Management approval guard (full body: 20261123000300 body + DEC-74)
-- ---------------------------------------------------------------------------------------------
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
  -- DEC-74: an approval never stamps an unanswered Issue CN Request.
  if rms_private.gs_open_cn_request_qty(new.gs_id) > 0 then
    raise exception 'DEC-74: % pc(s) of this goods slip are still an Issue CN Request; decide them (Issue CN or another action) before approving',
      rms_private.gs_open_cn_request_qty(new.gs_id) using errcode = '23514';
  end if;

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
