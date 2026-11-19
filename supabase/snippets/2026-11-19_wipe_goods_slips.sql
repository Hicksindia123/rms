-- =============================================================================
-- ONE-OFF PRODUCTION DATA RESET (2026-11-19, DEC-59). Run once in the Supabase SQL editor.
--
-- User decision 2026-11-19: remove every existing Goods Slip before the new Categorisation and
-- Department Routing masters (migration 20261119000100) are used. GS 00001 / 00002 / 00004 were
-- past the point where a GS can be cancelled (§6.5: only GATE_CREATED / UNBOXING), so all GS and
-- their transactions are removed, as in the 2026-11-16 reset.
--
-- REMOVES: every Goods Slip and all transaction data created by user actions: GS items, counts,
-- buckets, conditions, inspections, RM reviews, routing plans / routings / receipts, A/c Actions
-- slips, Accounts entries, dispatch slips, credit notes, stock lots, stock movements and balances,
-- custody transfers, notifications, party emails, attachment records, print logs, idempotency
-- keys and number-series counters (GS numbers restart at 00001).
--
-- KEPT: users, roles, permissions, products (19 thermometers), categories, parties, transporters,
-- states/stations, locations, containers, technicians, forms, workflows, option lists, item field
-- profiles (masters), settings, branding, and the append-only ledgers audit_log,
-- config_change_log, user_activity and system_guard_events.
--
-- Files in Storage are NOT removed (Supabase blocks SQL deletes on storage.objects). Empty the
-- rms-documents and rms-videos buckets in the dashboard if wanted. Do NOT empty rms-branding.
--
-- Everything runs in one transaction: any error rolls the whole script back.
-- =============================================================================

begin;

-- TRUNCATE ... CASCADE also empties every table that references these (all GS / stock /
-- workflow children). No configuration table references a transaction table.
truncate table
  public.goods_slips,
  public.stock_items,
  public.dismantle_batches,
  public.container_audit_days,
  public.custody_transfers,
  public.technician_batches,
  public.store_issues,
  public.notification_events,
  public.notifications,
  public.attachments,
  public.credit_notes,
  public.form_responses,
  public.print_logs,
  public.number_series_counters,
  rms_private.idempotency_keys
cascade;

-- Self-check: abort (roll back) unless the result is exactly as intended.
do $$
begin
  if (select count(*) from public.goods_slips) <> 0
     or (select count(*) from public.stock_movements) <> 0
     or (select count(*) from public.stock_balances) <> 0
     or (select count(*) from public.stock_lots) <> 0
     or (select count(*) from public.credit_notes) <> 0 then
    raise exception 'Transactions were not fully removed; aborting';
  end if;
  if (select count(*) from public.products) = 0 then
    raise exception 'Products were removed; aborting';
  end if;
end $$;

commit;

-- Result (read-only).
select (select count(*) from public.goods_slips)   as goods_slips,
       (select count(*) from public.stock_balances) as stock_balances,
       (select count(*) from public.products)       as products,
       (select count(*) from public.profiles)       as users;
