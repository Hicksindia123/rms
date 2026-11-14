-- ===========================================================================
-- P3-08: Phase 3 gate — defect fixes found by the full-lifecycle run (fix forward, rule d)
-- References: G-13, BR-34, DEC-23, §8.6, DEC-11, DEC-18, P3-03 task 4, G-05, G-16.
--
-- 1. G-13 (credit_notes): "GST_NOT_REFLECTED permits only a JV record" and "a GST CN needs
--    GST_REFLECTED" are now enforced as soon as the portal result is recorded, at every status
--    (P3-06 only checked VERIFIED / ISSUED, so a DRAFT could carry a contradictory type). A DRAFT
--    created before the portal check (gst_portal_code null) stays allowed: G-13 forbids issuing it.
-- 2. JV_ONLY is not a workbook dropdown row: P3-06 tagged it 'DD r76' (which is GST_NOT_REFLECTED).
--    It is the system CN type of §8.6 / BR-34 / DEC-23, kept in CN_TYPE so its label stays
--    configurable (rule e). Re-tag its source; the code is unchanged (codes are immutable, G-18).
-- 3. Scrap disposal of a stock lot (DEC-11 / DEC-18; P3-03 task 4 "DISPOSE movement"): a
--    lot-linked scrap record can only be DISPOSED together with its stock movement.
-- ===========================================================================

-- 1. G-13 -------------------------------------------------------------------------------------
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

    -- G-13 / BR-34: a GST CN needs the return reflected on the portal — at any status once the
    -- portal result is recorded, and always before it can be verified or issued.
    if v_cn_type = 'GST_CN'
       and ((v_portal_code is not null and v_portal_code <> 'GST_REFLECTED')
            or (new.status in ('VERIFIED', 'ISSUED') and v_portal_code is null)) then
      raise exception 'G-13: GST Credit Note requires return to be reflected on GST portal';
    end if;

    -- G-13 / BR-34 / DD r76: not reflected → only a JV record, at any status.
    if v_portal_code = 'GST_NOT_REFLECTED' and v_cn_type <> 'JV_ONLY' then
      raise exception 'G-13: Return not reflected on GST portal permits only JV_ONLY';
    end if;

    return new;

  elsif tg_table_name = 'credit_note_lines' then
    select cn.gs_id, cn.cn_type_code into v_gs_id, v_cn_type
    from public.credit_notes cn
    where cn.id = new.credit_note_id;

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
$$ language plpgsql security definer set search_path = '';

revoke all on function rms_private.credit_notes_g13_guard() from public, anon, authenticated;

-- 2. JV_ONLY provenance -------------------------------------------------------------------------
update public.option_items oi
   set source_ref = '§8.6 / BR-34 / DEC-23 [ARCH]',
       remarks = 'System CN type (not a workbook row): the only record permitted when the return '
                 || 'is not reflected on the GST portal (BR-34, DD r76).'
  from public.option_sets os
 where os.id = oi.option_set_id
   and os.code = 'CN_TYPE'
   and oi.code = 'JV_ONLY';

-- 3. Lot-linked scrap disposal ------------------------------------------------------------------
alter table public.scrap_records
  add constraint scrap_records_lot_disposal_movement check (
    disposal_status <> 'DISPOSED' or lot_id is null or stock_movement_id is not null
  );

create index if not exists scrap_records_lot_idx on public.scrap_records (lot_id);
create index if not exists scrap_records_movement_idx on public.scrap_records (stock_movement_id);
