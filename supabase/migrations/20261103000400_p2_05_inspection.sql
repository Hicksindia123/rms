-- P2-05: Product-specific inspection, not-allowed/hazard handling & extraction reconciliation
-- (master plan §2.2 Step-3, §3.2 DD r21–r43, BR-11..BR-17, G-04..G-07, DEC-07, DEC-09, DEC-10, DEC-11, DEC-14).
-- Fixes forward on 20261102000900 (P2-01) and 20261103000300 (P2-04).

-- ===========================================================================
-- 1. stock_lots: evaluation flag and routing hint
-- ===========================================================================
alter table public.stock_lots
  add column if not exists requires_evaluation boolean not null default false,
  add column if not exists routing_hint text check (routing_hint in ('SELLABLE','TO_TECHNICIAN','REPACK_OR_TECH','EVALUATE') or routing_hint is null);

-- ===========================================================================
-- 2. inspections: reopening metadata
-- ===========================================================================
alter table public.inspections
  add column if not exists reopened_at timestamptz,
  add column if not exists reopened_by uuid references public.profiles (id) on delete set null,
  add column if not exists reopen_reason text;

-- ===========================================================================
-- 3. G-06: Enclosed Oval grading cannot be submitted unless full_opening_confirmed = true
-- ===========================================================================
create or replace function rms_private.inspection_allocations_g06_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_inspection record;
begin
  select i.full_opening_confirmed, pc.code as category_code, pc.requires_full_opening
    into v_inspection
    from public.inspections i
    join public.gs_items gi on gi.id = i.gs_item_id
    join public.product_categories pc on pc.id = gi.category_id
   where i.id = new.inspection_id;

  if (v_inspection.requires_full_opening or v_inspection.category_code = 'ENCLOSED_OVAL')
     and not coalesce(v_inspection.full_opening_confirmed, false) then
    raise exception 'G-06: Enclosed Oval grading cannot be submitted unless full_opening_confirmed = true'
      using errcode = '23514';
  end if;

  return new;
end;
$$;

drop trigger if exists inspection_allocations_g06_guard on public.inspection_allocations;
create trigger inspection_allocations_g06_guard
  before insert or update on public.inspection_allocations
  for each row execute function rms_private.inspection_allocations_g06_guard();

-- ===========================================================================
-- 4. G-07: Inspection finalisation requires Σ conditions = received_qty,
--    and packaging_qty + container_qty = received_qty (per DEC-07).
-- ===========================================================================
create or replace function rms_private.inspections_g07_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_item         record;
  v_alloc_sum    integer;
  v_extraction   record;
begin
  -- Only validate when transitioning to FINAL
  if new.status = 'FINAL' and old.status is distinct from 'FINAL' then
    select received_qty into v_item from public.gs_items where id = new.gs_item_id;

    -- Calculate allocation sum, excluding SHORT_QTY option items (system_behavior = 'SHORT_QTY' or code = 'DMT_SHORT_QTY')
    select coalesce(sum(ia.qty), 0)
      into v_alloc_sum
      from public.inspection_allocations ia
      left join public.option_items oi on oi.id = ia.option_item_id
     where ia.inspection_id = new.id
       and coalesce(ia.system_behavior_snapshot, oi.system_behavior, '') <> 'SHORT_QTY'
       and ia.condition_code <> 'DMT_SHORT_QTY';

    if v_alloc_sum <> v_item.received_qty then
      raise exception 'G-07: Inspection finalisation requires sum of condition quantities (%) to equal received quantity (%)',
        v_alloc_sum, v_item.received_qty using errcode = '23514';
    end if;

    -- Check extraction reconciliation
    select * into v_extraction from public.extraction_records where gs_item_id = new.gs_item_id;
    if not found then
      raise exception 'G-07: Inspection finalisation requires an extraction record' using errcode = '23514';
    end if;

    if not v_extraction.reconciled then
      raise exception 'G-07: Inspection finalisation requires extraction to be reconciled' using errcode = '23514';
    end if;

    if (v_extraction.packaging_qty + v_extraction.container_qty) <> v_item.received_qty then
      raise exception 'G-07: Inspection finalisation requires extraction total (% + %) to equal received quantity (%)',
        v_extraction.packaging_qty, v_extraction.container_qty, v_item.received_qty using errcode = '23514';
    end if;
  end if;

  return new;
end;
$$;

drop trigger if exists inspections_g07_guard on public.inspections;
create trigger inspections_g07_guard
  before update of status on public.inspections
  for each row execute function rms_private.inspections_g07_guard();

-- ===========================================================================
-- 5. G-07 on goods_slips: All lines must be finalised before advancing to RM_REVIEW
-- ===========================================================================
create or replace function rms_private.goods_slips_g07_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_unfinalised_count integer;
begin
  if old.status = 'INSPECTION' and new.status in ('RM_REVIEW', 'IN_PROCESS', 'COMMERCIAL_RESOLUTION', 'CLOSED') then
    select count(*)
      into v_unfinalised_count
      from public.gs_items gi
      left join public.inspections ins on ins.gs_item_id = gi.id and ins.status = 'FINAL'
     where gi.gs_id = new.id
       and ins.id is null;

    if v_unfinalised_count > 0 then
      raise exception 'G-07: Cannot advance GS to % because % line(s) are not finalised in inspection',
        new.status, v_unfinalised_count using errcode = '23514';
    end if;
  end if;

  return new;
end;
$$;

drop trigger if exists goods_slips_g07_guard on public.goods_slips;
create trigger goods_slips_g07_guard
  before update of status on public.goods_slips
  for each row execute function rms_private.goods_slips_g07_guard();

-- Revoke execute from public/anon/authenticated; grant to rms_api
revoke execute on function
  rms_private.inspection_allocations_g06_guard(),
  rms_private.inspections_g07_guard(),
  rms_private.goods_slips_g07_guard()
from public, anon, authenticated;

grant execute on function
  rms_private.inspection_allocations_g06_guard(),
  rms_private.inspections_g07_guard(),
  rms_private.goods_slips_g07_guard()
to rms_api;

-- ===========================================================================
-- 6. Provisional settings: routing table & safety notification roles
-- ===========================================================================
insert into public.system_settings (key, value, category, description, source_ref)
values
  (
    'condition_routing_table',
    '{
      "DMT_OK_PACKED": "SELLABLE",
      "PRS_OK": "SELLABLE",
      "EO_OK": "SELLABLE",
      "DMT_OK_PKG_DAMAGED": "REPACK_OR_TECH",
      "EO_INNER_CAPILLARY_BROKEN": "EVALUATE",
      "DMT_SCRATCHED": "TO_TECHNICIAN",
      "DMT_DIRTY": "TO_TECHNICIAN",
      "DMT_DISPLAY_ISSUE": "TO_TECHNICIAN"
    }'::jsonb,
    'provisional',
    'DEC-14: Routing destinations for graded conditions.',
    'DEC-14'
  ),
  (
    'hazard_safety_notification_roles',
    '["REPLACEMENT_MANAGER", "SPARE_PARTS_MANAGER"]'::jsonb,
    'provisional',
    'DEC-11: Roles notified when hazardous materials (mercury) are detected.',
    'DEC-11'
  )
on conflict (key) do nothing;
