# Future Deployment Readiness & Pre-Flight Review (Render / Cloud)

**Current Deployment Status:** **NOT DEPLOYED**  
*As mandated by `RMS_DEVELOPMENT_MASTER_PLAN.md` §19 and `CLAUDE.md`: Render deployment is strictly out of scope for Phases 1–4. All services run locally against local Supabase. This document and the `render.yaml` draft blueprint exist solely to prepare for the future deployment exercise without any architectural modifications required.*

---

## 1. Readiness Architecture Matrix (Master Plan §19)

| Component / Layer | Architectural Readiness Built In | Verification Status in Codebase | Target Production Environment |
|---|---|---|---|
| **Backend Web Service** | • Stateless FastAPI service.<br>• Reads dynamically assigned `$PORT` (default: 8000).<br>• Fast health check at `GET /api/v1/health`.<br>• Proxy headers & forwarded-for enabled (`--proxy-headers --forwarded-allow-ips="*"`).<br>• Zero local disk storage reliance (ephemeral file system safe).<br>• Standardized structured logging to `stdout`. | Verified in P4-05 (`app/main.py`, `app/core/config.py`). | Render Web Service (Python 3.12 / Uvicorn) |
| **Background Worker** | • Distinct execution entry point `python -m app.worker`.<br>• Processes transactional notification outbox queue.<br>• Evaluates step SLA timers and escalation policies.<br>• Zero HTTP listener dependencies. | Verified in P4-03 / P4-05 (`app/worker.py`). | Render Background Worker or Cron Job |
| **Frontend Static Site** | • Vite / Rolldown production static build (`pnpm build` → `dist/`).<br>• Client-side routing with SPA rewrite rule (`frontend/public/_redirects`).<br>• Dynamic bundle code splitting (initial gzipped JS bundle: **114.35 kB**, well within < 300 kB budget).<br>• Environment injection at build time via `VITE_*` variables. | Verified in P4-05 / P4-06. | Render Static Site or Cloudflare Pages |
| **Database Engine** | • Supabase Managed PostgreSQL 15.<br>• Row Level Security (RLS) active on 100% of public tables.<br>• Role `rms_api` granted least-privilege DML.<br>• Migrations applied via CLI (`supabase db push`), **never** automatically executed at application boot. | Verified in pgTAP suites `01_schema` … `27_security_rls`. | Supabase Cloud Pro Tier |
| **Secrets & Credentials** | • Zero credentials in code, Git repository, or frontend build artifacts.<br>• Strict separation of `SUPABASE_SERVICE_ROLE_KEY` (backend private) vs `VITE_SUPABASE_ANON_KEY` (frontend public).<br>• Backend settings use Pydantic `SecretStr` to prevent leakage in reprs or log traces. | Scanned clean via `scripts/check-secrets.ps1`. | Render Environment Groups |
| **CORS & Domain URLs** | • Backend `CORS_ORIGINS` supports comma-separated explicit domain allow-list.<br>• Wildcard (`*`) is strictly rejected by Pydantic validator when `APP_ENV=prod`. | Tested in `test_security_auth.py`. | Production FQDN (e.g., `https://rms.company.com`) |
| **Object Storage** | • S3-compatible private storage buckets (`rms-evidence`, `rms-videos`, `rms-attachments`, `rms-proofs`).<br>• Public access blocked on all buckets except public branding/logo assets.<br>• Short-lived signed URLs with configurable TTL (`SIGNED_URL_TTL_SECONDS=600`). | Tested in `test_security_upload.py`. | Supabase Cloud Storage |
| **Email Channel** | • SMTP client supporting TLS/STARTTLS (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`).<br>• Deep-linking to application entities via `APP_PUBLIC_URL`. | Tested in `test_notifications_unit.py`. | Amazon SES / SendGrid / Postmark |
| **Observability & Audit** | • Unique `X-Request-ID` attached to every request and error response.<br>• Append-only database audit tables (`audit_log`, `user_activity`, `config_change_log`). | Tested in P4-04 / P4-05. | Render Logs / Datadog / OpenTelemetry |
| **Data Protection & Backups**| • Point-in-Time Recovery (PITR) support.<br>• Automated daily logical backups via `pg_dump`.<br>• Runbook restore drill documented in `docs/RUNBOOK.md`. | Verified in `scripts/integrity_check.sql`. | Supabase PITR + External S3 Backup |

---

## 2. Blueprint Configuration Review (`render.yaml`)

The draft blueprint `render.yaml` was established in prompt P4-05 with environment variable names only (no secrets):

```yaml
# DRAFT BLUEPRINT - NOT DEPLOYED
# Intended for the future production deployment exercise.
services:
  - type: web
    name: rms-backend
    env: python
    region: singapore
    plan: standard
    buildCommand: "uv sync --frozen --no-dev"
    startCommand: "uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'"
    healthCheckPath: /api/v1/health
    envVars:
      - key: APP_ENV
        value: prod
      - key: DATABASE_URL
        fromDatabase:
          name: rms-supabase-pooler
          property: connectionString
      - key: SUPABASE_URL
        sync: false
      - key: SUPABASE_SERVICE_ROLE_KEY
        sync: false
      - key: CORS_ORIGINS
        sync: false

  - type: worker
    name: rms-worker
    env: python
    region: singapore
    plan: starter
    buildCommand: "uv sync --frozen --no-dev"
    startCommand: "uv run python -m app.worker"
    envVars:
      - key: APP_ENV
        value: prod
      - fromGroup: rms-backend-secrets

  - type: web
    name: rms-frontend
    env: static
    buildCommand: "pnpm install --frozen-lockfile && pnpm build"
    staticPublishPath: dist
    routes:
      - type: rewrite
        source: /*
        destination: /index.html
    envVars:
      - key: VITE_SUPABASE_URL
        sync: false
      - key: VITE_SUPABASE_ANON_KEY
        sync: false
      - key: VITE_API_URL
        sync: false
```

---

## 3. Pre-Flight Go-Live Checklist (For Future Exercise)

When the business owner approves cloud provisioning, execute this step-by-step checklist:

### Stage 1: Supabase Cloud Setup
- [ ] Create production Supabase project in closest region (e.g., AWS Mumbai `ap-south-1`).
- [ ] Set database password and store in enterprise password manager.
- [ ] Run migrations: `supabase db push --db-url "postgresql://postgres:[PASSWORD]@db.[PROJECT_REF].supabase.co:5432/postgres"`.
- [ ] Run reference seed (excluding DEMO block at end of `seed.sql`).
- [ ] Create production storage buckets: `rms-evidence`, `rms-videos`, `rms-attachments`, `rms-branding`. Apply RLS storage policies.

### Stage 2: Master Data & Identity Migration
- [ ] Bootstrap initial Production Super Admin:
  ```bash
  python backend/scripts/bootstrap_super_admin.py --email admin@company.com --name "Enterprise Admin"
  ```
- [ ] Execute `backend/scripts/uat_reset.py --clean-demo-masters --products-csv /path/to/real_products.csv --parties-csv /path/to/real_parties.csv --skip-users`.
- [ ] Provision production user accounts for personnel (Anuj, Aman, Pratham, Sahil, Deepak, Raj Kumar Ji, etc.).
- [ ] Confirm starting sequential counter for Goods Slips in `number_series` table (DEC-01).

### Stage 3: Render Resource Provisioning
- [ ] Create Render Web Service linking to repository branch.
- [ ] Bind environment variables in Render Dashboard (Database URL, Supabase service key, SMTP credentials).
- [ ] Deploy backend and confirm health probe `/api/v1/health` returns `200 OK` with JSON `{"status": "ok"}`.
- [ ] Create Render Background Worker linking to `python -m app.worker`.
- [ ] Create Render Static Site for frontend; configure build command and publish directory `dist`.
- [ ] Update CORS allow-list in backend with production static site domain.

### Stage 4: Go-Live Smoke & Handover
- [ ] Execute smoke test over HTTPS on desktop and mobile.
- [ ] Verify SSL certificate termination and security headers (`X-Content-Type-Options`, `X-Frame-Options: DENY`, `Strict-Transport-Security`).
- [ ] Run `scripts/integrity_check.sql` against production DB to verify `violations = 0`.
- [ ] Hand over administrative credentials and sign off.
