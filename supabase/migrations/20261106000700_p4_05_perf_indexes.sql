-- Migration: 20261106000700_p4_05_perf_indexes.sql
-- Prompt: P4-05 Performance optimisation & query tuning
-- Composite indexes for keyset pagination, filtered sorting, and stock card lookup.

create index if not exists goods_slips_created_at_id_idx
    on public.goods_slips (created_at desc, id desc);

create index if not exists goods_slips_status_created_at_idx
    on public.goods_slips (status, created_at desc);

create index if not exists goods_slips_party_created_at_idx
    on public.goods_slips (party_id, created_at desc);

create index if not exists stock_movements_lot_created_at_idx
    on public.stock_movements (lot_id, created_at desc);

create index if not exists stock_lots_gs_id_item_idx
    on public.stock_lots (gs_id, gs_item_id);
