-- Migration: 20261113000600_ph5_rm_review_item_qty_guard.sql
-- Description: Allow updating gs_items quantities during RM_REVIEW (AMD-12 / Phase 5)

create or replace function rms_private.gs_items_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_row        public.gs_items;
  v_status     text;
  v_correction uuid;
begin
  v_row := case when tg_op = 'DELETE' then old else new end;
  select status into v_status from public.goods_slips where id = v_row.gs_id;
  if v_status is null then
    -- cascade from a deleted GS, or a missing GS (the FK reports G-01 on insert)
    return case when tg_op = 'DELETE' then old else new end;
  end if;
  if v_status in ('GATE_CREATED', 'UNBOXING', 'ITEMIZATION') then
    return case when tg_op = 'DELETE' then old else new end;
  end if;

  if tg_op <> 'UPDATE' then
    raise exception 'Item lines cannot be added or removed once the GS is categorised (status %)', v_status
      using errcode = '23514';
  end if;
  if new.gs_id <> old.gs_id or new.line_no <> old.line_no or new.product_id <> old.product_id
     or new.category_id <> old.category_id
     or new.product_code_snapshot is distinct from old.product_code_snapshot
     or new.product_name_snapshot is distinct from old.product_name_snapshot
     or new.category_code_snapshot is distinct from old.category_code_snapshot then
    raise exception 'The product of a categorised item line cannot change' using errcode = '23514';
  end if;
  if new.documented_qty = old.documented_qty and new.received_qty = old.received_qty then
    return new;  -- remarks / updated_at only
  end if;

  -- Phase 5 (AMD-12): RM Review allows editing quantities directly
  if v_status = 'RM_REVIEW' then
    return new;
  end if;

  -- Quantities change only by applying an APPROVED, not yet applied correction for this line.
  v_correction := nullif(current_setting('app.item_correction_id', true), '')::uuid;
  if v_correction is null or not exists (
       select 1 from public.gs_item_corrections c
        where c.id = v_correction and c.gs_item_id = new.id and c.status = 'APPROVED'
          and c.applied_at is null
          and c.old_documented_qty = old.documented_qty and c.old_received_qty = old.received_qty
          and c.new_documented_qty = new.documented_qty and c.new_received_qty = new.received_qty) then
    raise exception 'Item quantities can change after categorisation only through an approved line correction'
      using errcode = '23514';
  end if;
  return new;
end;
$$;
