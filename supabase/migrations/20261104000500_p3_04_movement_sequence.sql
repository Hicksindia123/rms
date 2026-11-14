-- =============================================================================
-- Migration: 20261104000500_p3_04_movement_sequence.sql
-- P3-04 · stock card ordering (master plan §8.5; BR-30 acceptance "the stock card reconstructs
-- its full path").
--
-- Movements written in one transaction share created_at (now()): a custody auto-transfer writes
-- TRANSFER_OUT and TRANSFER_IN together, rms_reclassify_lot writes its :OUT / :IN pair together.
-- Ordering by created_at alone therefore cannot reproduce the real sequence. `seq` is an
-- insertion-order identity; existing rows are numbered in physical (= insertion, the table is
-- insert-only) order by the table rewrite, which fires no row triggers.
-- =============================================================================

alter table public.stock_movements
  add column seq bigint generated always as identity;

create index stock_movements_lot_seq_idx on public.stock_movements (lot_id, seq);

comment on column public.stock_movements.seq is
  'Insertion order (identity). Orders movements that share created_at (one transaction).';
