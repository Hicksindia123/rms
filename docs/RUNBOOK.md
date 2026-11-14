# RMS Operations & Infrastructure Runbook

**Document Version:** 1.0.0  
**Target Audience:** DevOps Engineers, System Administrators, and On-Call Technical Support  
**Environment:** Local Development, On-Premises Testing, and Render/Cloud Staging  

---

## 1. Service Topology & Port Allocation

RMS is composed of the following services running on dedicated ports:

| Service | Component | Local Port | Health Check / Endpoint | Configuration Source |
|---|---|---|---|---|
| **Backend API** | FastAPI / Python 3.12 | `:8000` | `GET /api/v1/health` | `backend/.env` |
| **Frontend Web** | React 18 / Vite / Rolldown | `:5173` | `GET /` | `frontend/.env` |
| **Database** | PostgreSQL 15 (Supabase) | `:54322` | `pg_isready -p 54322` | `supabase/config.toml` |
| **Auth / Gateway** | Supabase GoTrue / Kong | `:54321` | `GET /auth/v1/health` | `supabase/config.toml` |
| **Studio UI** | Supabase Web Dashboard | `:54323` | `GET /` | Local Docker |
| **Local SMTP** | Inbucket Mail Server | `:54324` (SMTP)<br>`:54325` (Web) | `GET /` | Local Docker |

---

## 2. Normal Start & Stop Procedures

### 2.1 Starting the Entire Environment

#### Prerequisites
- Docker Desktop is installed and running.
- Supabase CLI installed.
- Python 3.12 (`uv`) and Node.js (`pnpm`) available on PATH.

#### Step 1: Ensure Local Supabase Services are Running
```powershell
# From repository root:
supabase status

# If stopped, start local services:
supabase start
```

#### Step 2: Launch Backend, Worker & Frontend
```powershell
# Windows PowerShell:
.\scripts\dev.ps1

# Linux / macOS Bash:
./scripts/dev.sh
```
`scripts/dev.ps1` launches:
1. Backend API (`uvicorn app.main:app --reload --port 8000`) in a background process.
2. Background Worker (`python -m app.worker`) if worker tasks are enabled.
3. Vite Dev Server (`pnpm dev`) in the active console.

### 2.2 Graceful Shutdown Procedure
- Pressing `Ctrl + C` in the console running `dev.ps1` triggers the `finally` block, terminating the uvicorn process tree and Vite child processes.
- To shut down Supabase Docker containers:
  ```powershell
  supabase stop
  ```

---

## 3. Database Backup Procedures

Database backups should be taken before each UAT cycle, schema migration, or production deployment.

### 3.1 Full Database Logical Backup (`pg_dump`)
```powershell
# Export complete schema and data (plain SQL format):
pg_dump -h 127.0.0.1 -p 54322 -U postgres -d postgres -F p -f "backups/rms_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss').sql"

# Export in PostgreSQL Custom Archive format (compressed, recommended for large DBs):
pg_dump -h 127.0.0.1 -p 54322 -U postgres -d postgres -F c -b -v -f "backups/rms_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss').dump"
```
*Default local password for user `postgres`:* `postgres`

### 3.2 Backup Critical Master & Configuration Tables Only
To create a lightweight snapshot of masters, option sets, forms, and workflows:
```powershell
pg_dump -h 127.0.0.1 -p 54322 -U postgres -d postgres -F p `
  -t public.departments `
  -t public.roles `
  -t public.permissions `
  -t public.user_roles `
  -t public.parties `
  -t public.products `
  -t public.product_categories `
  -t public.inventory_locations `
  -t public.option_sets `
  -t public.option_values `
  -t public.forms `
  -t public.form_versions `
  -t public.form_fields `
  -t public.workflows `
  -t public.workflow_steps `
  -t public.number_series `
  -t public.system_settings `
  -f "backups/rms_config_seed_$(Get-Date -Format 'yyyyMMdd').sql"
```

---

## 4. Database Restore Procedures

> ⚠️ **CAUTION:** Restoring a database snapshot overwrites existing records. Always take a fresh backup before performing a restore.

### 4.1 Restoring from SQL Plaintext Script
```powershell
# Using psql:
psql -h 127.0.0.1 -p 54322 -U postgres -d postgres -f "backups/rms_backup_YYYYMMDD_HHMMSS.sql"
```

### 4.2 Restoring from Custom Archive Dump (`pg_restore`)
```powershell
# Drop existing objects and recreate:
pg_restore -h 127.0.0.1 -p 54322 -U postgres -d postgres --clean --if-exists -v "backups/rms_backup_YYYYMMDD_HHMMSS.dump"
```

### 4.3 Post-Restore Verification Checklist
Immediately following any restore operation:
1. Run `supabase db query --file scripts/integrity_check.sql` to verify all 12 invariants pass.
2. Verify backend API health: `curl http://localhost:8000/api/v1/health`.
3. Check Supabase Auth connectivity by logging in as `admin@rms.local`.

---

## 5. Log Files, Monitoring & Traceability

### 5.1 Request Traceability (`request_id`)
- Every HTTP request passing through FastAPI is stamped with a unique `X-Request-ID` UUID header.
- If an error occurs, the API returns a structured envelope:
  ```json
  {
    "error": {
      "code": "SYSTEM_GUARD_VIOLATION",
      "message": "Enclosed Oval full opening confirmation is required",
      "request_id": "8f3b6d21-9a72-4b33-8c41-11d234567890",
      "details": { "guard": "G-06" }
    }
  }
  ```
- End-users can provide this `request_id` to technical support for exact log correlation.

### 5.2 Log Locations
- **Backend Application Logs:** Output to `stdout` in structured JSON format when `APP_ENV=prod` or colored text when `APP_ENV=local`.
- **Docker Container Logs:**
  ```powershell
  # Supabase Postgres engine logs:
  docker logs -f supabase_db_RMS--

  # Supabase Auth (GoTrue) logs:
  docker logs -f supabase_auth_RMS--

  # Kong API Gateway logs:
  docker logs -f supabase_kong_RMS--
  ```
- **Database Audit Tables:**
  - Operational changes: `SELECT * FROM public.audit_log ORDER BY created_at DESC LIMIT 50;`
  - User logins & navigation: `SELECT * FROM public.user_activity ORDER BY created_at DESC LIMIT 50;`
  - System configuration diffs: `SELECT * FROM public.config_change_log ORDER BY created_at DESC LIMIT 50;`

---

## 6. Common Errors & Troubleshooting Runbooks

### Runbook 6.1: Docker Daemon Not Running / DB Refused
- **Symptom:** `psycopg.OperationalError: connection to server at "127.0.0.1", port 54322 failed: Connection refused`.
- **Root Cause:** Docker Desktop is stopped or failed to initialize Windows named pipes.
- **Remediation Steps:**
  1. Check Docker service: `Get-Service com.docker.service`.
  2. If stopped, start Docker Desktop from Start Menu or:
     ```powershell
     Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
     ```
  3. Wait 30 seconds for Docker Engine to initialize (`docker ps`).
  4. Run `supabase start`.

### Runbook 6.2: Port Collisions (:8000 or :5173 occupied)
- **Symptom:** `uvicorn` fails with `[Errno 10048] error while attempting to bind on address ('127.0.0.1', 8000): only one usage of each socket address is normally permitted`.
- **Remediation Steps:**
  1. Find process holding port 8000:
     ```powershell
     Get-NetTCPConnection -LocalPort 8000 | Select-Object OwningProcess
     ```
  2. Terminate rogue process:
     ```powershell
     taskkill /PID <PID> /F
     ```

### Runbook 6.3: System Guard Violation Encountered (`422 G-xx`)
- **Symptom:** Frontend displays amber/red alert toast stating `Guard G-XX failed`.
- **Diagnosis:**
  - `G-02`: Unboxing completed without both video and classified photos.
  - `G-05`: Attempt to move mercury lot to functional location.
  - `G-06`: Grading Enclosed Oval without full opening checkbox.
  - `G-07`: Extraction quantities (packaging + container) do not equal received count.
  - `G-08`: Attempting custody handover of a piece held in Pending (BP).
  - `G-10`: Battery stock in `BATTERY_STORE` insufficient to cover replaced count.
  - `G-11`: Dismantling batch submitted without PCB Model or Supplier.
  - `G-13`: Issuing GST Credit Note for a party invoice unreflected on GST portal.
  - `G-14`: Proposed credit note unit rate exceeds historical purchase rate.
  - `G-15`: Attempt to close Goods Slip before sending party notification.
- **Resolution:** Review business condition; system guards are operating by design to protect physical and commercial compliance. Never attempt to force database updates.

### Runbook 6.4: Stale API Types Warning
- **Symptom:** Frontend TypeScript errors when compiling API client objects.
- **Remediation Steps:**
  1. Ensure backend is running on `http://localhost:8000`.
  2. Regenerate TypeScript client contracts:
     ```powershell
     cd frontend
     pnpm gen:api
     ```
  3. Check Git diff on `frontend/src/types/api.ts` to confirm new models match backend schema.

---

## 7. Key Rotation Procedures

### 7.1 Rotating the Database Password (`rms_api`)
1. Connect as superuser `postgres`:
   ```sql
   ALTER USER rms_api WITH PASSWORD 'new_secure_api_password_2026';
   ```
2. Update `DATABASE_URL` in `backend/.env`:
   ```env
   DATABASE_URL=postgresql+psycopg://rms_api:new_secure_api_password_2026@127.0.0.1:54322/postgres
   ```
3. Restart backend API service.

### 7.2 Rotating Supabase JWT Secret & Service Role Key
1. Generate new 32+ character random secret string.
2. In Supabase project configuration (or `supabase/config.toml` locally):
   - Update `jwt_secret`.
3. In `backend/.env`:
   - Update `SUPABASE_JWT_SECRET`.
   - Update `SUPABASE_SERVICE_ROLE_KEY`.
4. Restart backend and notify users to re-login (existing JWT sessions expire immediately).

---

## 8. Data Integrity Audits (`scripts/integrity_check.sql`)

Execute the comprehensive SQL invariant checker against the active database:

```powershell
# PowerShell command:
supabase db query --file scripts/integrity_check.sql
```

### Invariant Catalog Reference:
- **IC-01 (Quantity Conservation):** For every Goods Slip line, physical units are 100% accounted for:
  $$\text{Received Qty} = \sum \text{Active Lots} + \sum \text{Dismantled} + \sum \text{Dispatched} + \sum \text{Disposed}$$
- **IC-02 (No Negative Balances):** Zero inventory balances $< 0$ anywhere in the warehouse network.
- **IC-03 (Ledger vs Balance Parity):** Sum of movements in `stock_ledger` equals current `inventory_balances`.
- **IC-04 (Custody Segregation):** Intermediate Store contains zero scrap/non-good stock; Spare Parts Manager contains zero functional good stock.
- **IC-05 (Hazard Quarantine Isolation):** Mercury-contaminated stock cannot exist in standard functional stores.
- **IC-06 (Disposal Manifest Reference):** All rows in `SCRAP_DISPOSED` have a valid manifest record attached.
- **IC-07 (Closed GS Purity):** Closed Goods Slips cannot have active tasks, pending drafts, or open movements.
- **IC-08 (Replacement Dispatch Conservation):** Dispatched quantities match approved replacement authorizations.
- **IC-09 (Battery Stock Consumption):** $\sum \text{BATTERY\_CONSUMED}$ matches total batteries installed by technician.
- **IC-10 (Functional Store Purity):** `INTERMEDIATE_STORE` and `MAIN_STORE` hold strictly `FUNCTIONAL_GOOD` or `FUNCTIONAL_REPAIRED` condition classes.
- **IC-11 (Closure Checklist Snapshot):** Every closed Goods Slip possesses an immutable passing closure snapshot.
- **IC-12 (Zero In-Transit at Closure):** No units remain in transit, pending handover, or discrepancy upon GS closure.

If any invariant reports `violations > 0`, investigate immediately using `public.audit_log` and freeze downstream closures until reconciled.
