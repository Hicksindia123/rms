# Audit Log Retention & Monthly Partitioning Strategy

Master plan reference: Prompt P4-04 item 4, BR-40, G-17.

## 1. Non-Bypassable Immutability Policy (G-17)

All audit logs (`public.audit_log`, `public.config_change_log`, and `public.user_activity`) are **append-only**:
- **Zero Deletion:** Under no circumstances are audit rows deleted or truncated by any user or API, including `SUPER_ADMIN`.
- **Database Triggers:** Database triggers (`audit_log_immutable`, `user_activity_guard`) explicitly block `UPDATE` and `DELETE` queries with exception code `42501` (`INSUFFICIENT_PRIVILEGE`).
- **Traceability:** Every insert, update, and soft-delete on business entities is recorded in `audit_log` with the acting profile ID (`actor_id`) and correlated HTTP request ID (`request_id`).

---

## 2. Partitioning Thresholds & Sizing

In the foundation schema, `public.audit_log` is stored as an unpartitioned table with secondary indexes on `(table_name, row_id)`, `(actor_id, at desc)`, `(request_id)`, and `(at desc)`.

### Threshold Trigger for Range Partitioning
When either of the following capacity triggers is reached:
1. **Row Count Threshold:** `audit_log` reaches **5,000,000 rows**.
2. **Table Storage Footprint:** Physical relation size exceeds **10 GB** (including index pages).

At that point, `public.audit_log` will transition to a **Monthly Declarative Range Partition** table partitioned by `at (timestamp with time zone)`.

---

## 3. Monthly Partitioning Architecture

### Partition Key
`PARTITION BY RANGE (at)`

### Partition Table Naming Convention
`public.audit_log_yYYYYmMM`  
Example:
- `public.audit_log_y2026m11` for `2026-11-01 00:00:00+00` to `2026-12-01 00:00:00+00`
- `public.audit_log_y2026m12` for `2026-12-01 00:00:00+00` to `2027-01-01 00:00:00+00`

### Automated Partition Maintenance
A background worker cron job (e.g., `audit_partition_maintenance`, running on the 25th of each month) pre-creates partitions for the next 3 months:
```sql
CREATE TABLE IF NOT EXISTS public.audit_log_y2026m12
  PARTITION OF public.audit_log
  FOR VALUES FROM ('2026-12-01 00:00:00+00') TO ('2027-01-01 00:00:00+00');
```

---

## 4. Query & Index Performance SLA

- **Local Time Range Pruning:** Queries specifying `date_from` and `date_to` take advantage of PostgreSQL partition pruning (`enable_partition_pruning = on`), scanning only relevant monthly segments.
- **Global Search & Timeline SLA:**
  - GS-level activity searches (`/gs/{id}/activity`) utilize the `(table_name, row_id)` and `(new->>'gs_id')` indexes.
  - Audit Explorer searches (`/audit`) respond within **300 ms** on up to 50k GS and multi-million audit entries.

---

## 5. Long-Term Cold Storage & Archival (Post 7 Years)

Per Indian tax and corporate compliance regulations:
- Active transactional audit data remains queryable live for a minimum of **7 financial years**.
- Archived older partitions can be detached to cold object storage (`rms-audit-archive` bucket / Parquet tables) with SHA-256 cryptographic manifests, ensuring audit completeness without database bloat.
