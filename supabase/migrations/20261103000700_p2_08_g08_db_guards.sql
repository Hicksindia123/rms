-- P2-08 · Phase 2 gate: database enforcement of G-08 (master plan §4.2, BR-20, WF r7 col K, DEC-12).
-- Fixes forward on 20261102000900 (P2-01) and 20261103000600 (P2-07). Before this migration G-08 was
-- enforced in the database only for stock movements (rms_move_stock); the two other halves of the
-- guard were service-only, which CLAUDE.md rule c forbids:
--
-- 1. custody_transfer_lines: a lot marked Pending (BP) can never be put on a custody transfer.
-- 2. goods_slips: a GS with an open pendency cannot advance into the Stage-6 statuses
--    (COMMERCIAL_RESOLUTION, AWAITING_NOTIFICATION, CLOSED). When the DEC-12 toggle
--    `pending_blocks_entire_gs` is true (or the pendency was raised with blocks_gs) it also cannot
--    leave RM_REVIEW for handover (IN_PROCESS).
--    The toggle only widens the block (DEC-12 provisional approach); no setting can lift the
--    Stage-6 block. Backward moves (e.g. an RM inspection reopen) and CANCELLED stay possible.

-- ===========================================================================
-- 1. Pending (BP) lots cannot be added to a custody transfer
-- ===========================================================================
create or replace function rms_private.custody_transfer_lines_g08_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if exists (select 1 from public.stock_lots l where l.id = new.lot_id and l.is_pending) then
    raise exception 'G-08: quantities marked Pending (BP) cannot be added to a custody transfer'
      using errcode = '23514';
  end if;
  return new;
end;
$$;

drop trigger if exists custody_transfer_lines_g08_guard on public.custody_transfer_lines;
create trigger custody_transfer_lines_g08_guard
  before insert or update of lot_id on public.custody_transfer_lines
  for each row execute function rms_private.custody_transfer_lines_g08_guard();

-- ===========================================================================
-- 2. A GS with an open blocking pendency cannot advance its workflow status
-- ===========================================================================
create or replace function rms_private.goods_slips_g08_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  v_whole_gs boolean;
begin
  if new.status is not distinct from old.status or new.status = 'CANCELLED' then
    return new;
  end if;
  if not exists (select 1 from public.pendencies p where p.gs_id = new.id and p.status = 'OPEN') then
    return new;
  end if;

  -- Every open pendency blocks Stage-6 (DEC-12), whatever the toggle said when it was raised.
  if new.status in ('COMMERCIAL_RESOLUTION', 'AWAITING_NOTIFICATION', 'CLOSED') then
    raise exception 'G-08: GS % has an open Pending (BP) pendency and cannot advance to %',
      new.gs_no, new.status using errcode = '23514';
  end if;

  -- Whole-GS block: the toggle is on now, or the pendency was raised as blocking (blocks_gs).
  select coalesce((s.value #>> '{}')::boolean, false) into v_whole_gs
    from public.system_settings s where s.key = 'pending_blocks_entire_gs';
  v_whole_gs := coalesce(v_whole_gs, false)
    or exists (select 1 from public.pendencies p
                where p.gs_id = new.id and p.status = 'OPEN' and p.blocks_gs);
  if v_whole_gs and old.status = 'RM_REVIEW' and new.status = 'IN_PROCESS' then
    raise exception 'G-08: GS % has an open Pending (BP) pendency and pending_blocks_entire_gs is on',
      new.gs_no using errcode = '23514';
  end if;
  return new;
end;
$$;

drop trigger if exists goods_slips_g08_guard on public.goods_slips;
create trigger goods_slips_g08_guard
  before update of status on public.goods_slips
  for each row execute function rms_private.goods_slips_g08_guard();

-- Trigger functions are never callable by API clients (P1-02 convention, pgTAP 01_schema).
revoke all on function rms_private.custody_transfer_lines_g08_guard() from public, anon, authenticated;
revoke all on function rms_private.goods_slips_g08_guard() from public, anon, authenticated;
