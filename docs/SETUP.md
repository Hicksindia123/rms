# Local development setup

Master plan reference: §12. Windows 11 is the primary platform. macOS and Linux work with the `.sh`
scripts.

## 1. Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Node.js | 20 LTS or newer | |
| pnpm | 9.x | `npm install -g pnpm@9` |
| Python | 3.12 | uv can install it: `uv python install 3.12` |
| uv | latest | `pip install uv` or the official installer. Make sure `uv` is on `PATH` (with `pip install --user` it lands in `%APPDATA%\Python\Python3xx\Scripts`). |
| WSL2 | | Docker Desktop's backend on Windows. Install once from an **administrator** prompt: `wsl --install`, then reboot. Check with `wsl --status`. |
| Docker Desktop | WSL2 backend | Required for local Supabase (Option A). It must be running before `supabase start`. |
| Supabase CLI | 2.x | `scoop install supabase`, or without installing anything: `npx supabase@2.122.0 <command>` (used below as `supabase`) |
| Git | any recent | |
| Playwright browsers | | `cd frontend && pnpm exec playwright install chromium webkit` |

## 2. Install dependencies

```bash
cd backend  && uv sync
cd frontend && pnpm install
```

## 3. Database: choose one option

### Option A: local Supabase (recommended)

> **Shortcut after the first setup:** `scripts/reset-db.ps1` (Windows) or `scripts/reset-db.sh` does
> steps 2, 3 (password only), 5, 6 and 7 in one go. See [Rebuilding the local database](#rebuilding-the-local-database).

1. `supabase start`. This starts local Postgres, Auth, Storage, Realtime and Studio. Note the printed
   **API URL**, **anon key**, **service-role key** and **DB URL**.
2. `supabase db reset` applies `supabase/migrations/*`, `supabase/seed.sql` (reference seed and the
   demo block), `supabase/seed_parties.sql` and `supabase/seed_products.sql` (bulk-imported party and
   item masters, see [Master data import](#master-data-import-parties-and-items)). `supabase test db` runs the pgTAP tests in `supabase/tests/`.
3. Set the `rms_api` password (see [The `rms_api` database role](#the-rms_api-database-role)), then copy
   `backend/.env.example` → `backend/.env` and fill in the values from step 1. `DATABASE_URL` uses the
   `rms_api` role, not `postgres`.
4. Copy `frontend/.env.example` → `frontend/.env.local`. Set `VITE_SUPABASE_URL`,
   `VITE_SUPABASE_ANON_KEY` and `VITE_API_BASE_URL`. **Only public values go here.**
5. Create the first Super Admin (from P1-05): `cd backend && uv run python scripts/bootstrap_super_admin.py`.
   After that, manage people in the app: **Administration → Users** (create, roles, deactivate, reset password,
   permission exceptions, departments) and **Administration → Permission Matrix** (roles). New users and admin
   password resets get a temporary password that must be replaced at the next sign-in (DEC-50).
6. Local demo users (P2-02, §3.3, **local only**): `cd backend && uv run python scripts/seed_demo_users.py`.
   This creates `anuj@`, `aman@`, `pratham@`, `sahil@`, `deepak@rms.local` (password `Demo@123456` unless
   you pass `--password`) with their §3.3 roles. It refuses to run unless `APP_ENV=local`.
7. After every `supabase db reset`: set the `rms_api` password again (the reset recreates the role), then
   rerun steps 5–6. Auth users are wiped by the reset.

### Option B: remote Supabase *development* project

Use a **separate** project such as `rms-dev`. **Never use production.**

1. `supabase link --project-ref <ref>`
2. `supabase db push` applies the migrations. The storage buckets and the `rms_api` role are created by
   migrations. If the hosted `postgres` role is refused `CREATE ROLE … BYPASSRLS`, run the `do $$ … $$`
   block from `supabase/migrations/20261102000100_extensions_schemas_roles.sql` in the Dashboard SQL
   editor, then run `supabase db push` again.
3. Set the `rms_api` password in the Dashboard **SQL editor** (see below). Never commit it.
4. Auth settings are not pushed from `config.toml`. In the Dashboard (Authentication → Sign In / Providers
   and URL Configuration), disable sign-ups, and set the Site URL and redirect URLs to the frontend
   origin(s), including `/reset-password`.
5. Load the **reference** seed without the demo block. The demo block is everything from the
   `-- DEMO:BEGIN` line to the `-- DEMO:END` line:

   ```bash
   sed '/^-- DEMO:BEGIN/,/^-- DEMO:END/d' supabase/seed.sql | psql "$DEV_DB_URL" -v ON_ERROR_STOP=1 -1
   ```

   ```powershell
   $seed = Get-Content supabase/seed.sql -Raw
   [regex]::Replace($seed, '(?ms)^-- DEMO:BEGIN.*?^-- DEMO:END[^\r\n]*', '') |
     psql $env:DEV_DB_URL -v ON_ERROR_STOP=1 -1
   ```

   The seed is idempotent (`ON CONFLICT DO NOTHING`). Re-running it never overwrites admin edits to
   labels or settings, but it does re-add any default role permission that an admin removed. Run it
   once per environment.

   Then load the party and item masters (also idempotent; each aborts if a state/station pair or a
   product category it needs is missing):

   ```bash
   psql "$DEV_DB_URL" -v ON_ERROR_STOP=1 -1 -f supabase/seed_parties.sql
   psql "$DEV_DB_URL" -v ON_ERROR_STOP=1 -1 -f supabase/seed_products.sql
   ```
6. Put the remote URL and keys in `backend/.env` and `frontend/.env.local`, as in Option A.

### Rebuilding the local database

`scripts/reset-db.ps1` (or `scripts/reset-db.sh`) is the one command to rebuild the **local** database:

```powershell
.\scripts\reset-db.ps1                      # backup, reset, users, verify
.\scripts\reset-db.ps1 -SkipBackup -KeepDemo # options: no backup / keep DEMO-* placeholders
```

1. Preflight: `docker`, `supabase`, backend Python (`uv` or `backend/.venv`). It refuses to run unless
   `APP_ENV=local` in `backend/.env`, and starts local Supabase if it is not running.
2. Dumps the current DB to `backups/rms-<timestamp>.dump` (git-ignored). Restore with
   `pg_restore --clean --if-exists -d postgres` inside the DB container.
3. `supabase db reset`: migrations (schema, guards, roles/permissions, all-India states and stations),
   `seed.sql` (reference config incl. product categories), `seed_parties.sql`, `seed_products.sql`.
4. Sets the `rms_api` password from `DATABASE_URL` in `backend/.env`.
5. `backend/scripts/uat_reset.py`: removes the DEMO placeholder masters (unless `-KeepDemo`) and creates
   the 12 workbook users with their roles (`admin@rms.local` is Super Admin; password `-Password`,
   default as in `RMS_USER_CREDENTIALS.txt`).
6. Verifies the counts (parties and products against the row count in their seed files) and exits
   non-zero on any mismatch.

### Master data import (parties and items)

New masters are imported into the local DB and then exported to the seed files that
`supabase db reset`, `scripts/reset-db.*` and go-live load. Never edit the seed files by hand.

#### Parties

Bulk party lists (CSV with the columns `State,Station,Client Name`) go through
`backend/scripts/import_parties.py`:

```bash
cd backend
uv run python scripts/import_parties.py import "path/to/parties.csv"   # local DB by default
uv run python scripts/import_parties.py export-seed                     # refresh the seed file
```

- `import` inserts every party whose state and station exist in the masters and writes the rest to
  `party_import_exceptions.csv` in the repository root, with a reason. Station matching ignores case and
  accepts a bracketed name in the master (`VIJAYAWADA` → `NTR (Vijayawada)`). Exact duplicates (name +
  state + station) are skipped, so re-importing the same file adds nothing.
- New parties get system codes `PTY-00001`, `PTY-00002`, … continuing from the highest existing one.
- `export-seed` regenerates `supabase/seed_parties.sql` from all `PTY-` parties in the DB. Commit that
  file. It is what `supabase db reset` and go-live load. Never edit it by hand.
- To fix exceptions: add the missing station (or correct the CSV), re-run `import` with the exceptions
  file or the original CSV, then `export-seed` again.
- Another database: `--db-url postgresql+psycopg://...` or `RMS_IMPORT_DATABASE_URL`.

#### Items (products)

Item lists (CSV with the columns `Item Name,Category`; optional `UOM` (default `PCS`) and `HSN`) go
through `backend/scripts/import_products.py`:

```bash
cd backend
uv run python scripts/import_products.py import "path/to/items.csv"
uv run python scripts/import_products.py export-seed      # refresh supabase/seed_products.sql
```

- `Category` is a product category code: `DMT`, `PRISMATIC`, `ENCLOSED_OVAL` (thermometers) or
  `GENERAL` (everything else). Unknown categories, blank names and bad HSN codes go to
  `product_import_exceptions.csv` in the repository root.
- Names are deduplicated ignoring case and spaces, within the file and against the product master.
- New products get system codes `ITM-00001`, `ITM-00002`, … continuing from the highest existing one.
- `product_import_review.csv` (repository root) is the reviewed source of the first import: category
  per item plus possible same-product pairs to check.

### The `rms_api` database role

The backend connects as the dedicated role `rms_api` (master plan §9.4). It has LOGIN, DML on `public`
and `rms_private`, and BYPASSRLS. It is not a superuser, and it holds no UPDATE or DELETE on
`audit_log` / `config_change_log`. The migration creates it **without a password**, because no secret
may live in a migration. Set the password out-of-band and keep it only in `backend/.env`.

**Local (Option A).** Run this after the first `supabase start`. Roles are cluster-wide, so the password
survives `supabase db reset`. Set it again after `supabase stop --no-backup` or if the backend gets
`password authentication failed for user "rms_api"`. The DB container is named after `project_id` in
`supabase/config.toml` (`rms`):

```bash
# bash: the password is passed as a psql variable, so it is not echoed into the SQL text
read -rs RMS_API_PASSWORD
echo "alter role rms_api with password :'pw';" |
  docker exec -i supabase_db_rms psql -U postgres -d postgres -v ON_ERROR_STOP=1 -v pw="$RMS_API_PASSWORD"
```

```powershell
$sec = Read-Host "rms_api password" -AsSecureString   # works in Windows PowerShell 5.1 and 7
$pw = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
"alter role rms_api with password :'pw';" |
  docker exec -i supabase_db_rms psql -U postgres -d postgres -v ON_ERROR_STOP=1 -v pw="$pw"
```

Then set `DATABASE_URL=postgresql+psycopg://rms_api:<password>@127.0.0.1:54322/postgres` in
`backend/.env`. Check it with
`docker exec -it supabase_db_rms psql "postgresql://rms_api:<password>@127.0.0.1:5432/postgres" -c "select current_user"`.

**Remote (Option B).** In the Dashboard SQL editor, run
`alter role rms_api with password '<long random password>';`. Use a password manager value. It is not
stored anywhere in the repository. Connection strings:

- Direct: `postgresql+psycopg://rms_api:<password>@db.<project-ref>.supabase.co:5432/postgres`
- Through the Supavisor pooler, the username carries the project ref:
  `postgresql+psycopg://rms_api.<project-ref>:<password>@<pooler-host>:5432/postgres` (session mode).

To rotate the password, run the same `alter role` again and update `backend/.env`.

### Storage limits for local uploads (P2-03)

Step-2 videos can be large, and three limits apply. Keep them consistent:

1. `supabase/config.toml` → `[storage] file_size_limit = "1GiB"`: the global ceiling of the local
   Storage server. Restart with `supabase stop && supabase start` after changing it.
2. Bucket limits in `20261102000600_storage.sql`: `rms-videos` 1 GiB (mp4 / mov),
   `rms-documents` 25 MB (jpeg / png / heic / heif / pdf). Change them with a **new** migration.
3. `system_settings` `upload_max_video_bytes` / `upload_max_document_bytes` (DEC-04): what the API
   accepts. Set them at or below the bucket limits.

Videos larger than `upload_resumable_threshold_bytes` (6 MB) upload through Supabase's resumable
TUS endpoint (`/storage/v1/upload/resumable/sign`, 6 MB chunks). Smaller files use a signed PUT.
Uploads that are never confirmed are removed by the worker (`uv run python -m app.worker`, started
by `scripts/dev.ps1`) after `pending_upload_retention_hours` (24 h). Uploaded objects can be
inspected in Studio → Storage (http://127.0.0.1:54323).

### Local Email Testing with Inbucket (P4-03)

Supabase local development ships with an embedded Inbucket mail server:
- **Inbucket Web UI**: `http://localhost:54324` (inspect delivered emails in your browser).
- **Inbucket SMTP**: Internal port 2500 (inside docker network) or mapped host port.

To enable local email delivery in the RMS backend:
1. In `backend/.env`, configure:
   ```env
   SMTP_HOST=127.0.0.1
   SMTP_PORT=54325
   SMTP_FROM=rms-notifications@example.local
   SMTP_USE_TLS=false
   SMTP_SSL=false
   ```
2. When SMTP is configured, outbox email deliveries (`channel='EMAIL'`) are rendered from versioned templates (`public.notification_templates`) and dispatched. In local development with Inbucket, outgoing emails appear instantly in the web mailbox at `http://localhost:54324`.
3. If `SMTP_HOST` and `SMTP_FROM` are not both configured in `backend/.env`, the email channel is cleanly disabled: deliveries are ledgered as `status='SKIPPED'` with `skip_reason='SMTP_NOT_CONFIGURED'` in `public.notification_deliveries` (never silently lost), and the Admin Notifications interface renders a read-only SMTP configuration banner indicating email is disabled.
4. To verify the notifications outbox, user preferences, SLA escalations, and email channel locally:
   ```bash
   cd backend && uv run python scripts/verify_p4_03.py
   ```

## 4. Run

### Simulating Daily Container Audit and Missed-Day Job (P2-06, BR-18, DEC-08)

The daily DMT container audit register (BR-18, DD r31) requires counting all active DMT containers daily with sellable packaging separated. Background worker jobs handle evening reminders and morning missed-day transitions:

To simulate worker jobs locally on demand:
```bash
# Run evening alert (notifies Inward Verifier & RM if today's audit is unconfirmed):
cd backend && uv run python -m app.worker --run-job container_audit_evening_alert

# Run morning missed transition (marks past unconfirmed days MISSED and alerts Inward Verifier & RM):
cd backend && uv run python -m app.worker --run-job container_audit_morning_missed

# Stale upload cleanup job (P2-03):
cd backend && uv run python -m app.worker --run-job cleanup_pending_uploads
```

To test the blocking toggle (`daily_audit_blocks_inspection`, DEC-08):
- Default is `false` (DEC-08): DMT line inspection finalisation proceeds even if today's audit is pending.
- To enable blocking: update system setting `daily_audit_blocks_inspection` to `true` (via Settings admin UI or SQL: `update public.system_settings set value = 'true'::jsonb where key = 'daily_audit_blocks_inspection';`).
- When `true`, attempting to finalise inspection for any DMT item returns HTTP 422: `"Daily container audit pending for <date>"`. Once today's container audit is confirmed, inspection finalisation succeeds immediately.

| What | Command |
|---|---|
| Everything | `scripts/dev.ps1` (Windows) · `scripts/dev.sh` |
| Backend only | `cd backend && uv run uvicorn app.main:app --reload --port 8000` |
| Worker (when it exists) | `cd backend && uv run python -m app.worker` |
| Frontend only | `cd frontend && pnpm dev` → http://localhost:5173 |

Health check: http://localhost:8000/api/v1/health → `{"status":"ok","version":"0.1.0","env":"local"}`.

### Calling the API with a token

The API takes a Supabase **access token** as `Authorization: Bearer …`. To get one locally, sign in
through the local Auth REST endpoint. Use the **anon** key from `supabase status`; the service-role
key is not needed.

```bash
ANON_KEY=<anon key from `supabase status`>
TOKEN=$(curl -s -X POST "http://127.0.0.1:54321/auth/v1/token?grant_type=password"   -H "apikey: $ANON_KEY" -H "Content-Type: application/json"   -d '{"email":"<user email>","password":"<password>"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s http://localhost:8000/api/v1/me                                   # 401 UNAUTHENTICATED
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/me # 200, or 403 ACCOUNT_INACTIVE
```

```powershell
$anon = "<anon key from supabase status>"
$body = @{ email = "<user email>"; password = "<password>" } | ConvertTo-Json
$token = (Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:54321/auth/v1/token?grant_type=password" `
  -Headers @{ apikey = $anon } -ContentType "application/json" -Body $body).access_token
Invoke-RestMethod -Uri http://localhost:8000/api/v1/me -Headers @{ Authorization = "Bearer $token" }
```

Demo users are created by the P1-05 script. Until then, add a user in Studio (Authentication → Add
user, with "Auto confirm"). Such a user gets an **inactive** profile (docs/DECISIONS.md, P1-02), so
`/me` answers 403 `ACCOUNT_INACTIVE`. To activate it locally, run
`update public.profiles set is_active = true where email = '<user email>';` in Studio's SQL editor.

`backend/.env` needs `SUPABASE_URL=http://127.0.0.1:54321` and, for the local HS256 fallback,
`SUPABASE_JWT_SECRET` (the JWT secret printed by `supabase status`). The token issuer must equal
`{SUPABASE_URL}/auth/v1`, so use the same host (`127.0.0.1` vs `localhost`) in both places, or set
`SUPABASE_JWT_ISSUER`.

## 5. Checks

| Purpose | Command |
|---|---|
| Reset DB | `supabase db reset` |
| DB tests | `supabase test db` |
| Backend | `cd backend && uv run pytest -q && uv run ruff check . && uv run mypy app` |
| Frontend | `cd frontend && pnpm lint && pnpm typecheck && pnpm test && pnpm build` |
| E2E | `cd frontend && pnpm e2e` (desktop-chromium, mobile-pixel-7, mobile-iphone-14) |
| API types | `cd frontend && pnpm gen:api` (backend running) |
| Everything | `scripts/test-all.ps1 [-E2E]` · `scripts/test-all.sh [--e2e]` |
| Secrets scan | `scripts/check-secrets.ps1` · `scripts/check-secrets.sh` |

Backend integration tests (`backend/tests/integration`) need a local database with the migrations
applied. They connect with `TEST_DATABASE_URL` (default
`postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres`, i.e. local Supabase after
`supabase db reset`). Each test runs in a transaction that is rolled back. When the database is not
reachable, these tests are **skipped** and the reason is printed in the pytest summary (`-ra`). A
skipped integration suite does not satisfy the Definition of Done.

If PowerShell blocks the scripts, run them with
`powershell -ExecutionPolicy Bypass -File scripts\test-all.ps1`.

## Secrets

- `backend/.env` holds every secret (service-role key, DB URL/password, JWT secret). It is git-ignored.
- `frontend/.env.local` holds only `VITE_*` public values. `scripts/check-secrets.*` fails the build if
  a service-role reference appears under `frontend/`.
