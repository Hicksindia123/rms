# RMS Database Migration Guide (Supabase Cloud)

**Audience:** whoever sets up and upgrades the production database. **Status:** procedure rehearsed locally on
2026-11-14 (see §9). Steps on the real Supabase Cloud project run only with the owner's explicit approval.

**Golden rules**

1. **Never** run `supabase db reset`, `supabase db push --include-seed`, `scripts/reset-db.*`, `scripts/uat-reset.*`, `backend/scripts/uat_reset.py` or
   `backend/scripts/seed_demo_users.py` against production. They delete data or create UAT accounts.
2. Schema changes go through **new** timestamped files in `supabase/migrations/`. An applied migration is never edited
   (fix forward). Destructive changes (drop / rename / type change / data rewrite) need the owner's written approval.
3. **Back up before every change.** The Free plan has **no automatic backups** (§2).
4. Seeds are loaded **once**, into a fresh production database. Later configuration changes ship as reviewed
   per-release SQL (§7.3), not by re-running the seed files.

---

## 1. What makes up the database

| Part | Where | Applied by |
|---|---|---|
| Schema, guards (G-01…G-22 + P1-05 triggers), RLS, grants, storage buckets | `supabase/migrations/*.sql` (52 files, `20261102000100` → `20261114000600`) | `supabase db push` |
| Reference configuration: roles + permission matrix, journeys, option catalogue, forms, workflow, settings (incl. `company_name`), number series, departments, categories | `supabase/seed.sql` (DEMO block at the end) | once, via the production seed (§5.4) |
| Master data: states/stations, parties, products | `supabase/seed_stations.sql`, `seed_parties.sql`, `seed_products.sql` | once, via the production seed |
| DB tests | `supabase/tests/*.test.sql` (40 files, 689 tests) | `supabase test db` (local / CI only) |
| Post-deploy checks (read-only) | `scripts/verify_production_db.sql` | `psql` against production |

`scripts/build_production_seed.py` turns the four seed files into **one** transaction-wrapped file with the DEMO block
removed (`supabase/.temp/production_seed.sql`, git-ignored). It refuses to output DEMO content.

## 2. Supabase Cloud facts this plan depends on

Verified against the Supabase docs on 2026-11-14: [pricing](https://supabase.com/pricing),
[upload limits](https://supabase.com/docs/guides/storage/uploads/file-limits),
[project pausing](https://supabase.com/docs/guides/platform/free-project-pausing),
[connecting](https://supabase.com/docs/guides/database/connecting-to-postgres),
[JWT signing keys](https://supabase.com/docs/guides/auth/signing-keys).

| Topic | Free plan (chosen for launch) | Consequence for RMS |
|---|---|---|
| Upload size | Global limit **max 50 MB**; bucket limits cannot exceed it | Set `upload_max_video_bytes` to 52 428 800 (§5.6). Long carton-opening videos must be shorter or compressed. |
| Storage total | Small quota on Free (see pricing page) | Videos fill it quickly. Monitor **Storage usage** weekly. Plan the Pro upgrade before it fills. |
| Database size | 500 MB | Local UAT data is ~60 MB incl. the audit log. Fine for launch. Watch `audit_log` growth. |
| Backups | **None** (Pro: daily, 7 days) | Manual dumps before every change and on a schedule (§8). |
| Pausing | Paused after **7 days** of low activity | Daily use prevents it. A paused project returns errors until it is restored from the dashboard. |
| Network | Direct DB host is IPv6. **Shared pooler is IPv4** (session mode port 5432) | Render needs IPv4, so the backend uses the **session pooler** (§4). |
| Pooler user for a custom role | `<role>.<project-ref>` (e.g. `rms_api.abcd…`) | `DATABASE_URL` uses `rms_api.<ref>`. |
| JWT | New projects sign with **asymmetric keys** (JWKS). Legacy projects can migrate in the dashboard | Required: the API refuses HS256 tokens outside local/test (§3.4). |

The `postgres` role on Supabase is not a superuser but has `BYPASSRLS` and `CREATEROLE`. That is all migration `0001`
needs to create `rms_api WITH LOGIN BYPASSRLS` (the local stack has the same attributes, and the rehearsal created it).

## 3. One-time prerequisites (Supabase dashboard)

1. **Create the project**: region **Mumbai (ap-south-1)**; a strong DB password (password manager, never in Git).
   Note the **project ref**.
2. **Storage → Settings**: confirm the global file size limit (50 MB on Free).
3. **Authentication → Providers / Settings** (`config.toml` does *not* configure the cloud project):
   - Email provider **on**; **"Allow new users to sign up" OFF** (RMS users are created by admins).
   - Minimum password length **8**; require letters and digits (matches DEC-50).
   - Site URL = the production frontend URL; Redirect URLs = that URL only.
   - Access token (JWT) expiry: 3600 s (as local).
4. **Authentication → JWT Keys**: the project must sign with an **asymmetric key** (ES256/RS256). If it still shows the
   legacy secret: *Migrate JWT secret* → *Rotate keys*. The backend reads
   `https://<ref>.supabase.co/auth/v1/.well-known/jwks.json`.
5. **Project Settings → API**: copy the **anon / publishable** key (frontend) and the **service_role / secret** key
   (backend only, Render secret env var). Never paste the secret key anywhere else.
6. **Database → Settings**: **Enforce SSL** on.

## 4. Connection strings

| Use | Connection | Notes |
|---|---|---|
| Backend `DATABASE_URL` (Render) | `postgresql://rms_api.<ref>:<RMS_API_PASSWORD>@aws-<n>-ap-south-1.pooler.supabase.com:5432/postgres?sslmode=require` | Session pooler, IPv4. `sslmode=require` is **mandatory**: the API refuses to start in prod without it. |
| Admin tasks (migrations, seed, verify) | the pooler string with user `postgres.<ref>` and the DB password, `?sslmode=require` | Shown in the dashboard under **Connect**. Use the session pooler (port 5432), not transaction mode. |

**Statement timeout.** The API asks for `statement_timeout` as a connection option (`DB_STATEMENT_TIMEOUT_MS`, 30 s).
Set it on the role as well, which works regardless of pooler behaviour (§5.5). If the pooler ever rejects the startup
option, set `DB_STATEMENT_TIMEOUT_MS=0` in Render. The role-level timeout still applies.

**Pool sizing (Free tier: small connection budget).** Render API: `DB_POOL_SIZE=5`, `DB_MAX_OVERFLOW=5`. Worker:
`DB_POOL_SIZE=2`, `DB_MAX_OVERFLOW=2`.

## 5. First-time bootstrap of production (run once)

Run from the repo root on the operator's machine. `psql` can come from the local Docker container:
`docker exec -i supabase_db_rms psql "<url>" ...`. Commands use `<...>` placeholders. Paste nothing secret into
tickets or chat.

### 5.1 Check the repository state
```bash
git status            # clean; on the release commit
supabase test db      # local: 40 files, all PASS
```

### 5.2 Link and preview
```bash
supabase link --project-ref <ref>        # asks for the DB password
supabase db push --dry-run               # must list exactly the 52 migrations on an empty project
```

### 5.3 Apply the migrations
```bash
supabase db push
```
**Never add `--include-seed`.** It would load `seed.sql` *including the DEMO block* into production. The seed is
loaded only as the DEMO-free production seed in §5.4.

### 5.4 Load the production seed (once)
```bash
python scripts/build_production_seed.py          # -> supabase/.temp/production_seed.sql (~416 KB)
psql "<admin url>" -X -v ON_ERROR_STOP=1 -f supabase/.temp/production_seed.sql
```
It is one transaction: on any error nothing is kept and the run can be repeated.

### 5.5 Give the API role a password and a timeout
In the dashboard SQL editor (as postgres):
```sql
alter role rms_api with password '<generate a 32+ char random password>';
alter role rms_api set statement_timeout = '30s';
```
Store the password in the password manager. It goes only into Render's `DATABASE_URL`.

### 5.6 Free-plan upload limit (configuration, not code)
```sql
update public.system_settings set value = '52428800' where key = 'upload_max_video_bytes';      -- 50 MB
update public.system_settings set value = '26214400' where key = 'upload_max_document_bytes';   -- 25 MB (unchanged)
```
The API refuses larger files with a clear message before anything reaches Storage. After moving to Pro, raise the
global Storage limit first, then this setting (max 1 GB = the `rms-videos` bucket ceiling).

### 5.7 First Super Admin
Use the production values in the shell environment only (not `backend/.env`):
```bash
cd backend
APP_ENV=prod DATABASE_URL="<rms_api pooler url>" SUPABASE_URL="https://<ref>.supabase.co" \
SUPABASE_SERVICE_ROLE_KEY="<secret key>" CORS_ORIGINS="https://<frontend>" \
python scripts/bootstrap_super_admin.py           # prompts for e-mail and password (twice)
```
Outside local/test the script refuses `@rms.local` addresses, the old default password and passwords that break DEC-50.
It is idempotent. The Super Admin then creates everyone else in **Administration → Users** (§12 of
`PRODUCTION_AUDIT.md`).

### 5.8 Verify (read-only)
```bash
psql "<admin url>" -X -v ON_ERROR_STOP=1 -f scripts/verify_production_db.sql
```
Every row must show `ok = t`. Then `GET https://<api>/health/ready` must return `{"database":"ok"}`.

## 6. What "verified" means
`verify_production_db.sql` checks: migrations count, RLS on every table, no `anon` privileges or callable functions,
pinned `search_path` on definer functions, `rms_api` attributes + password, private buckets without object policies,
the reference seed and master data present, **no DEMO rows**, **no `@rms.local` accounts**, at least one Super Admin,
and the video setting within the bucket ceiling.

## 7. Upgrades (every later release)

### 7.1 Before
1. Backup (§8).
2. Locally: `scripts/reset-db.ps1` and the full test suite green.
3. `supabase db push --dry-run`: review the list. Only the new files must appear.
4. Read every new migration for destructive statements (`drop`, `alter … type`, `rename`, `delete`, `update` without
   `where`, `truncate`). Any of them needs the owner's written approval and a tested restore.

### 7.2 Apply
```bash
supabase db push
psql "<admin url>" -X -v ON_ERROR_STOP=1 -f scripts/verify_production_db.sql
```
Deploy the backend **after** the migration when the code needs the new schema. Migrations must stay
backward-compatible with the running backend for that window (add columns/tables first, remove later).

### 7.3 Configuration and master-data changes
- New **settings, options, permissions, role grants** added to `seed.sql` for a release are also written as a small,
  reviewed, idempotent script `supabase/snippets/release_<yyyymmdd>.sql` (`insert … on conflict do nothing`). It is
  applied with `psql` after the migration. Never re-run the whole seed in production: a few seed statements upsert and
  would overwrite admin edits (inventory location custodians, form definition names).
- New **products / parties**: Admin → Masters → *Import CSV* (dry run first), or a reviewed SQL insert.

## 8. Backups on the Free plan (manual)

```bash
supabase db dump --linked -f backups/prod-<yyyymmdd>-schema.sql
supabase db dump --linked --data-only -f backups/prod-<yyyymmdd>-data.sql
```
or `pg_dump "<admin url>" -Fc -f backups/prod-<yyyymmdd>.dump`. `backups/` is git-ignored. Keep copies off the laptop
(encrypted drive or company storage). **Storage files (videos, documents) are not in these dumps.** On Free they are
backed up only by downloading the buckets (rclone/S3 protocol, or the dashboard). `docs/ROLLBACK_AND_RECOVERY.md`
(Phase 12) has the schedule and restore drill. Moving to Pro gives daily backups. PITR is a paid add-on.

## 9. Rehearsal evidence (local, 2026-11-14)

Run on the local Supabase stack, whose `postgres` role has the same attributes as Cloud:

| Step | Result |
|---|---|
| Backup | `backups/rms-20261114-171429-pre-rehearsal.dump` (2.1 MB) |
| `supabase db reset --no-seed` (= push on an empty project) | 52 migrations applied |
| `build_production_seed.py` + `psql -f` | exit 0, 0 errors: 13 roles, 151 permissions, 321 grants, 51 journey steps, 20 published forms, 1 workflow, 67 settings, 36 states, 973 stations, 2 350 parties, 315 products, **0 DEMO rows, 0 users** |
| `rms_api` password | set |
| `bootstrap_super_admin.py` with `APP_ENV=dev` | `@rms.local` refused; env credentials → Super Admin created; second run idempotent |
| `supabase test db` on that database | 40 files, 689 tests PASS |
| API smoke (real Supabase Auth) | 10/10: readiness, owner sign-in, `/me` Super Admin, journey, 13 roles, party lookup, first user created, forced password change enforced, password changed, user works |
| `verify_production_db.sql` on the UAT DB | all ok except **"no local/UAT accounts" = false**, as expected on UAT (proves the check works) |
| Restore | `reset-db.ps1 -SkipBackup`: UAT state back (12 users, 2 350 parties, 315 products) |

Not yet verifiable without the cloud project (checked during Phase 10 with approval): pooler login as
`rms_api.<ref>`, the JWKS URL, the 50 MB global limit and Render → Supabase connectivity.

## 10. Database audit notes (2026-11-14)

- 128 tables, 372 foreign keys, 459 check constraints, 543 indexes, 293 triggers. Every table has a primary key.
  RLS is on everywhere.
- **Fixed:** `rms_private.credit_notes_g14_guard()` was the only `SECURITY DEFINER` function without a pinned
  `search_path` (migration `20261114000600`; pgTAP `40_production_hardening` prevents regressions).
- **Accepted for now:** 142 foreign keys without a supporting index (77 are `created_by`-style actor columns; parents
  are never deleted). Index them when `pg_stat_statements` shows slow joins (`docs/QUERY_PERFORMANCE.md`).
- `audit_log` is the largest table. Its growth determines when the 500 MB Free limit is reached.
