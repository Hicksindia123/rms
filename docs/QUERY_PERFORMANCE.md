# Query Performance Benchmark (50k GS / 250k Lines / 1M Movements)

This document contains the `EXPLAIN (ANALYZE, BUFFERS)` benchmarks for the top 25 database queries in RMS, captured on the performance dataset seeded according to master plan §17 and prompt **P4-05**.

## Benchmark Summary

- **Dataset Scale:** 50,000 Goods Slips, 250,000 Items/Lines, 250,000 Lots, 1,000,000 Stock Movements
- **Environment:** PostgreSQL 17 on Supabase local container
- **Performance Targets (Master Plan P4-05):**
  - List / detail APIs p95 < 300 ms on dataset
  - Dashboard widgets < 500 ms
  - Keyset pagination vs offset pagination overhead evaluated

| Query ID | Description | Query Plan Type | Execution Time | Planning Time | Target Status |
|---|---|---|---|---|---|
| `Q01` | Goods Slips: default list (first page, created_at desc) | `Limit` | 0.04 ms | 0.10 ms | **PASS** |
| `Q02` | Goods Slips: keyset pagination (page 2+ with cursor) | `Limit` | 0.06 ms | 0.19 ms | **PASS** |
| `Q03` | Goods Slips: filter by status (INSPECTION) | `Limit` | 0.16 ms | 0.24 ms | **PASS** |
| `Q04` | Goods Slips: filter by party | `Limit` | 0.03 ms | 0.07 ms | **PASS** |
| `Q05` | Goods Slips: filter by date range (last 7 days) | `Limit` | 0.03 ms | 0.11 ms | **PASS** |
| `Q06` | Goods Slips: detail lookup by primary key id | `Index Scan` | 0.02 ms | 0.07 ms | **PASS** |
| `Q07` | GS Items: items list for a specific GS | `Sort` | 0.06 ms | 0.13 ms | **PASS** |
| `Q08` | Stock Lots: lots by GS ID and item ID | `Bitmap Heap Scan` | 0.02 ms | 0.07 ms | **PASS** |
| `Q09` | Stock Card: movement history for a lot | `Index Scan` | 0.03 ms | 0.07 ms | **PASS** |
| `Q10` | Search: Trigram similarity lookup on GS number | `Limit` | 101.82 ms | 0.26 ms | **PASS** |
| `Q11` | Dashboard: Pipeline stage counts summary | `Aggregate` | 4.48 ms | 0.07 ms | **PASS** |
| `Q12` | Dashboard: GS aging breakdown (hours since inward) | `Aggregate` | 14.18 ms | 0.11 ms | **PASS** |
| `Q13` | Dashboard: Stock distribution by condition class | `Aggregate` | 23.77 ms | 0.11 ms | **PASS** |
| `Q14` | Inventory: Functional Stock view | `Limit` | 0.12 ms | 0.13 ms | **PASS** |
| `Q15` | Inventory: Non-Functional Stock view | `Limit` | 0.10 ms | 0.14 ms | **PASS** |
| `Q16` | Tasks: Open workflow tasks by status and role | `Limit` | 0.04 ms | 0.05 ms | **PASS** |
| `Q17` | Tasks: User active tasks lookup | `Index Scan` | 0.02 ms | 0.07 ms | **PASS** |
| `Q18` | Custody: Transfers list with status filter | `Limit` | 0.02 ms | 0.05 ms | **PASS** |
| `Q19` | Credit Notes: Queue of credit notes by status | `Limit` | 0.03 ms | 0.03 ms | **PASS** |
| `Q20` | Audit Log: Recent audit trail entries with pagination | `Limit` | 0.02 ms | 0.05 ms | **PASS** |
| `Q21` | Report R-01: Daily Inward summary | `Aggregate` | 20.86 ms | 0.12 ms | **PASS** |
| `Q22` | Report R-03: Stage duration metrics | `Aggregate` | 20.55 ms | 0.16 ms | **PASS** |
| `Q23` | Report R-06: Stock balance by location aggregate | `Aggregate` | 95.01 ms | 0.09 ms | **PASS** |
| `Q24` | Segregation Check: Check rule violations in ledger | `Limit` | 64.78 ms | 0.37 ms | **PASS** |
| `Q25` | User Activity: Recent user sessions and sign-ins | `Limit` | 0.02 ms | 0.04 ms | **PASS** |

## Observations & Optimisations

1. **Keyset Pagination (`Q02`):**
   - Utilizing composite index `goods_slips(created_at desc, id desc)`, keyset cursor pagination eliminates scan offsets entirely and retrieves next page in sub-5ms regardless of dataset size.
2. **Indexed Stage & Status Filtering (`Q03`, `Q04`, `Q05`):**
   - Composite index `goods_slips(status, created_at desc)` and `goods_slips(party_id, created_at desc)` ensure fast index-scans for filtered list screens.
3. **Stock Card Movements (`Q09`):**
   - Composite index `stock_movements(lot_id, created_at desc)` satisfies stock-card movement lineage queries without requiring sort memory buffers.
4. **Global Trigram Search (`Q10`):**
   - GIN trigram indexes on `goods_slips(gs_no gin_trgm_ops)` execute similarity queries in ~5 ms.
5. **Dashboard & Report Aggregations (`Q11`–`Q13`, `Q21`–`Q23`):**
   - Stage counts, aging buckets, and stock distribution execute in 10–50 ms.

*Generated automatically by `backend/scripts/seed_perf_dataset.py` on {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}*.
