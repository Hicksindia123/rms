# RMS Production Audit — Phase 0 (Discovery)

**Date:** 2026-11-14 · **Scope:** read-only inspection of the local workspace `c:\Kuldeep510V07\RMS--`.
**Method:** targeted reading of configs, entry points, core infrastructure and migrations, live
**read-only** queries against the running local Supabase DB, introspection of the FastAPI route table,
and non-destructive checks (lint, typecheck, unit tests, production build).
No application code, migration or data was changed in Phase 0. The only new file is this document.

Status words used below: **VERIFIED** (checked by running something), **READ** (confirmed by
reading code/config), **UNVERIFIED** (claimed by existing docs or assumed; still to be proven).

---

## 1. Executive summary

RMS is a mature, well-structured application. Its security foundations are already better than
typical for a first deployment: strict layering, DB-enforced guards, RLS on every table, a
least-privilege DB role, private storage with signed URLs, JWT verification via JWKS, structured
logging with redaction, and no stack traces leaking outside `APP_ENV=local`.

It is **not yet deployable as-is**. The blockers are mostly in *deployment glue*, *repository hygiene*
and *open business data*, not in the core application:

| # | Severity | Blocker |
|---|---|---|
| B1 | **CRITICAL** (fixed in Phase 1) | `RMS_USER_CREDENTIALS.txt` (repo root **and** `docs/`) is **not git-ignored**. It holds the shared UAT password and 26 user e-mails. A `git add .` would publish it. |
| B2 | **CRITICAL** | The existing `render.yaml` cannot work: `APP_ENV: production` fails config validation (only `local/test/dev/prod` are allowed), so the API would **crash on boot**. It also builds from `requirements.txt`, which does not exist, and sets `VITE_API_URL` while the app reads `VITE_API_BASE_URL`. |
| B3 | **HIGH** (open, Phase 3) | Frontend `configApi.ts` (used by Admin → Form Builder and Option Sets Manager) calls `VITE_API_URL` with a hard `http://localhost:8000` fallback, sends **no auth header**, and calls paths that do not exist on the backend (`/config/options/sets/...`; backend has `/config/option-sets`). These screens are broken in every environment. The backend is *not* exposed by this, because the real routes require `config:view`. |
| B4 | **HIGH** | Both API URL resolvers (`lib/api/client.ts`, `lib/supabase.ts`) silently fall back to `http://<host>:8000` / `localhost` when the build variable is missing. A misconfigured production build would call the wrong host over plain HTTP instead of failing loudly. |
| B5 | **HIGH** (resolved in Phase 2: procedure + tooling rehearsed, see `DATABASE_MIGRATION_GUIDE.md` §9) | Production DB bootstrap is undocumented end-to-end: reference/config data and the **role ↔ permission matrix live in `supabase/seed.sql`** (with a DEMO block at the end), and `supabase db push` does **not** run seeds. The `rms_api` role is created without a password and with `BYPASSRLS`, and whether Supabase Cloud's `postgres` role may create a BYPASSRLS role is **UNVERIFIED**. |
| B6 | **MEDIUM (business)** | *Corrected 2026-11-14 after a DB reset:* the seeds load **315 products and 2,350 parties**. The user confirmed that the current product data is what goes live, with more products imported later by CSV or SQL. Still open: **288 party rows marked SKIP** in `party_station_review.csv`, and change-plan Phase 0 (server-side block of writes to ON-HOLD features) is `[ ]`. |
| B7 | **HIGH (cost/plan)** (Free tier chosen; handled by configuration: `upload_max_video_bytes` = 50 MB, guide §5.6) | Videos are allowed up to **1 GiB** (`rms-videos` bucket). Supabase Cloud **Free** caps uploads at 50 MB. Large evidence videos need a **Pro** project with the global upload limit raised. |
| B8 | **MEDIUM** | No CI (`.github/` absent). The repository has **no commits yet** (`master`, no remote). The lint gates fail today (ruff 55 in scripts/tests; ESLint 131 in the frontend), so CI would start red. |

Found during Phase 1 (2026-11-14):

| # | Severity | Finding |
|---|---|---|
| B9 | **CRITICAL** (fixed in Phase 1) | The login page shipped a "Quick Test Roles (UAT)" panel that one-click-filled the **Super Admin e-mail and the shared UAT password**, in the production bundle too. It is now rendered only in dev builds (`import.meta.env.DEV`), and the strings are removed from `vite build` output (VERIFIED by bundle grep + browser). |
| B10 | **HIGH** (fixed 2026-11-14, user chose option a) | **User/role administration does not exist** (master-plan prompt P1-05 is re-opened): there is no backend API to create users, assign roles or deactivate accounts, and `/users` (`UsersView.tsx`) plus `PermissionMatrixView` render **hard-coded sample users and dead buttons** (CLAUDE.md rule j). In production every user change would need `backend/scripts/*` run with the service-role key. **Fixed:** P1-05 built: modules `users` / `roles` (`/admin/users`, `/admin/roles`, `/admin/permissions`, `/admin/departments`, `/me/password`), migration `20261114000500` (DB guards), real Users / Departments / Roles & Permissions screens, forced password change, DEC-50. |
| B11 | LOW (fixed 2026-11-14) | Login page text: the "Remember workstation" checkbox has no effect (the session always persists), and the footer claims "Protected by … **2FA** Guard", but RMS has no MFA. The e-mail placeholder `e.g. pratham@rms.local` exposes the local naming scheme. **Fixed:** sign-in page redesigned (single card, branding from settings incl. the new `company_name`, no claims, no dead controls, no placeholder e-mail); the dark pre-login splash is replaced by a calm loader. |
| B12 | MEDIUM (policy adopted 2026-11-14, see §12) | The shared UAT password is also hard-coded in committed scripts and docs (`scripts/reset-db.*`, `scripts/uat-reset.*`, `backend/scripts/uat_reset.py`, `docs/UAT.md`, `docs/OFFLINE_TESTING_GUIDE.md`, e2e `support/stack.ts`, `login_all_users.spec.ts`). It is acceptable only if it **never** becomes a production password. Production accounts must get their own passwords, and the scripts must never be pointed at production. |

Found during Phase 2 (2026-11-14):

| # | Severity | Finding |
|---|---|---|
| B13 | **HIGH** (cloud setup check) | The API accepts only asymmetric (JWKS) Supabase tokens outside local/test. The Cloud project must sign with **asymmetric JWT keys** (default for new projects; legacy projects: *Migrate JWT secret* → *Rotate keys*). Otherwise every sign-in fails with 401. Guide §3.4. |
| B14 | **MEDIUM** (operational, Free plan) | No automatic backups, a 50 MB upload cap, a small storage quota, and pausing after 7 idle days. Manual DB dumps plus bucket downloads are mandatory (guide §8). Plan the Pro upgrade before storage fills with videos. |
| B15 | MEDIUM (fixed) | `backend/scripts/bootstrap_super_admin.py` defaulted to `admin@rms.local` / `Admin@123456` in every environment. Outside local/test it now requires explicit, env or prompted credentials and refuses `@rms.local`, the default password and passwords outside DEC-50. |
| B16 | MEDIUM (fixed) | The production DB connection could fall back to plaintext (libpq `sslmode=prefer`). With `APP_ENV=prod` the API refuses a `DATABASE_URL` without `sslmode=require`/`verify-*`. |
| B17 | LOW (fixed) | `rms_private.credit_notes_g14_guard()` was `SECURITY DEFINER` without a pinned `search_path` (migration `20261114000600`). |
| B18 | LOW (accepted) | 142 foreign keys lack a supporting index (77 actor columns). Revisit with `pg_stat_statements` data. |

Nothing found so far is a business-logic defect. The remediation plan (§10) is ordered so that the
blockers are removed with minimal, targeted changes.

---

## 2. Technology stack (VERIFIED from manifests / tool versions)

| Layer | Actual implementation |
|---|---|
| Frontend | React 18.3 + TypeScript (strict), **Vite 8**, Tailwind 3.4, react-hook-form + zod 4, recharts, supabase-js 2.49.4 (auth session, Realtime), tus-js-client (resumable video uploads). Package manager **pnpm 9.15.9**, Node 24 locally. Static SPA, no SSR. |
| Backend | **Python 3.12** (`requires-python >=3.12,<3.13`, `.python-version`), FastAPI 0.162, Pydantic v2 + pydantic-settings, SQLAlchemy 2 (Core/text SQL, no ORM schema), psycopg 3, PyJWT[crypto], structlog, slowapi, APScheduler 3, openpyxl, reportlab, supabase-py (Storage). Dependencies are unpinned in `pyproject.toml` but locked in `uv.lock`. |
| Database | Supabase Postgres **17** (local `config.toml`), 50 SQL migrations, 38 pgTAP test files, 4 seed files. |
| Auth | Supabase Auth (email/password, public sign-up disabled), backend verifies the access token. |
| Storage | Supabase Storage, 3 buckets (2 private, 1 public branding). |
| Background | Separate worker process `python -m app.worker` (APScheduler, 9 jobs). |
| Tooling | `uv` (not installed on this machine; `.venv` used instead), ruff, mypy strict, pytest, vitest, Playwright, ESLint, Prettier. |

## 3. Repository structure

```
backend/   FastAPI app (app/core, app/modules/<37 modules>, app/shared), tests/{unit,contract,integration}, scripts/
frontend/  Vite SPA (src/app, components/{ui,erp}, features/<module>, lib/api), tests/{unit,e2e}
supabase/  config.toml, migrations/ (50), tests/ (38 pgTAP), seed.sql + seed_{stations,parties,products}.sql
docs/      21 project documents (master plan addendum, change plan, SECURITY, RUNBOOK, UAT, …)
scripts/   dev/test-all/reset-db/uat-reset (.ps1 + .sh), check-secrets, integrity_check.sql
shared/    rules-test-vectors.json (shared rule vectors for backend + frontend tests)
render.yaml (draft, see B2)
```

Untracked local artefacts that must **not** go to GitHub: `backend/.env`, `frontend/.env.local`
(both correctly ignored), `backups/*.dump` (ignored), `RMS_USER_CREDENTIALS.txt` ×2 (**not ignored**),
`frontend/x/*.png` screenshots, root CSV working files (`items.csv`, `party_*.csv`, `product_*.csv`, which
contain party/product master data; decision needed), `.coverage` files (ignored).

## 4. Application architecture

### 4.1 Backend (READ)

- **Entry point:** `backend/app/main.py` → `create_app()`; module-level `app = create_app()`, so the
  uvicorn import path is `app.main:app` with `rootDir=backend`.
- **Lifecycle:** settings validated at import (fail fast); lifespan disposes the SQLAlchemy engine on shutdown.
- **Routers:** 44 included routers, all under `/api/v1`. **300 endpoints** (154 GET, 99 POST, 27 PUT,
  10 PATCH, 10 DELETE), VERIFIED by route-table introspection with `APP_ENV=prod`.
  The `test_support` router is mounted only when `APP_ENV` is `local`/`test` (VERIFIED absent under `prod`).
- **Layering:** `router → service → repository` per module (CLAUDE.md rule g).
- **DB access:** `app/core/db.py` uses a pooled SQLAlchemy engine (`pool_pre_ping`, recycle, connect timeout,
  `statement_timeout` passed as a libpq startup option) and a `UnitOfWork`, so each command is exactly one
  transaction that sets `app.user_id` / `app.request_id` for the audit trigger. Rollback on any exception.
- **Idempotency:** `app/core/idempotency.py`, `Idempotency-Key` header on stock/commercial commands (G-16).
- **Errors:** uniform envelope `{error:{code,message,details,request_id}}`; DB guard messages (`G-xx`) map to
  409; unknown DB errors → 500 with **no details outside `APP_ENV=local`** (VERIFIED in `core/errors.py`).
- **Logging:** structlog JSON to stdout, request-id middleware, a redaction processor for
  authorization/token/password/secret/key/cookie fields, and headers are never logged.
- **Worker:** `app/worker.py` runs APScheduler `BlockingScheduler` jobs: pending-upload cleanup,
  container-audit alerts (18:00 / 09:00 IST), nightly segregation check, notification outbox, e-mail,
  party e-mail, digest and SLA escalation. All jobs use `max_instances=1, coalesce=True`, and every run is
  recorded in `job_runs`. **It must run as exactly one instance**; two workers would double-send e-mails.

### 4.2 Frontend (READ)

- Vite SPA; `public/_redirects` holds the SPA rewrite. Route-level code splitting via `lazy()` in
  `src/app/App.tsx`, and vendor chunks in `vite.config.ts`.
- All business data goes through FastAPI (`lib/api/client.ts`, bearer token from the supabase-js session).
- Direct Supabase use is limited to the auth session, **Realtime** channels (dashboard and notifications,
  which require `public.notifications` in the `supabase_realtime` publication, done in migration `0007`) and **TUS
  resumable uploads** of videos to Storage via backend-issued signed tokens (`features/unboxing/uploader.ts`).
- There is no self-service password-reset screen, although `config.toml` lists a `/reset-password` redirect. Admins reset passwords.

### 4.3 Configuration / environment variables (READ, names only)

Backend (`app/core/config.py`, pydantic-settings; reads process env then `backend/.env`):

| Variable | Required | Notes |
|---|---|---|
| `APP_ENV` | default `local` | **must be one of `local,test,dev,prod`**. `prod` enables HSTS, forbids `*` CORS and HS256 tokens. |
| `DATABASE_URL` | **yes** | the `rms_api` role, never `postgres`. `postgres://` is rewritten to `postgresql+psycopg://`. |
| `SUPABASE_URL` | **yes** | used for JWKS / issuer / Storage. |
| `SUPABASE_SERVICE_ROLE_KEY` | for Storage + user admin | backend only. |
| `SUPABASE_JWT_SECRET` | local/test only | ignored in `dev`/`prod`. |
| `SUPABASE_JWKS_URL`, `SUPABASE_JWT_ISSUER`, `JWKS_CACHE_TTL_SECONDS` | optional | derived from `SUPABASE_URL`. |
| `CORS_ORIGINS` | yes in practice | comma list, no `*` in prod. |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT_SECONDS`, `DB_POOL_RECYCLE_SECONDS`, `DB_CONNECT_TIMEOUT_SECONDS`, `DB_STATEMENT_TIMEOUT_MS` | optional | code defaults 10 / 20 / 30 / 1800 / 10 / 30000. |
| `LOG_LEVEL`, `RATE_LIMIT_ENABLED`, `PAGE_SIZE_DEFAULT`, `PAGE_SIZE_MAX`, `SIGNED_URL_TTL_SECONDS`, `TZ`, `PORT` | optional | |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS`, `SMTP_SSL`, `SMTP_TIMEOUT_SECONDS`, `APP_PUBLIC_URL` | optional | e-mail channel; empty host/from = disabled. |

Not read by the code, but present in `render.yaml`: `SUPABASE_KEY`, `APP_DEBUG`, `RATE_LIMIT_DEFAULT`,
`RATE_LIMIT_SENSITIVE`, `VITE_API_URL` (see B2).

Frontend (`VITE_*`, baked in at build time): `VITE_API_BASE_URL`, `VITE_SUPABASE_URL`,
`VITE_SUPABASE_ANON_KEY`, plus the stray `VITE_API_URL` read by `configApi.ts` (B3).
`frontend/.env.local` holds exactly the three allowed variables (VERIFIED, names only).

## 5. Database architecture

- **Schema ownership:** SQL migrations only (no Alembic or ORM generation). 50 timestamped files
  `20261102000100` … `20261114000400`, plus pgTAP suites `01_schema` … `38_role_journeys`.
- **Schemas:** `public` (business tables), `rms_private` (locked helper functions such as `rms_move_stock`,
  `next_number`, `current_actor`), and the Supabase `auth` / `storage` schemas.
- **Integrity:** system guards G-01…G-22 enforced by constraints/triggers **and** services; append-only
  `audit_log` / `config_change_log` (UPDATE/DELETE/TRUNCATE revoked even from `service_role`); stock moves only via
  `rms_private.rms_move_stock`.
- **Live security state of the local DB (VERIFIED, read-only queries 2026-11-14):**
  - Tables in `public`/`rms_private` without RLS: **0**.
  - Table privileges held by `anon`: **none**. `authenticated`: **SELECT on `notifications` only**
    (plus policies limiting it to own rows; column UPDATE `read_at`).
  - `public` functions executable by `anon`: **0**. Views in `public`: **0**.
  - `rms_api`: LOGIN, BYPASSRLS, not superuser, password set (locally).
  - Local data volume: 6 goods slips, 13 auth users, 26 storage objects (test data).
- **Seeds:** `seed.sql` (3,541 lines: options catalogue, forms, workflow, settings, templates, roles and the
  role matrix, journey steps; DEMO block at lines 3495–3541), `seed_stations.sql`, `seed_parties.sql`,
  `seed_products.sql`.
- **Connection model for Cloud:** Render has no outbound IPv6, while Supabase's direct DB host is IPv6 unless the IPv4
  add-on is bought. The backend must therefore use the **Supavisor session pooler (port 5432)** with user
  `rms_api.<project-ref>`. Transaction mode (6543) may reject the `statement_timeout` startup option
  (`DB_STATEMENT_TIMEOUT_MS=0` would be needed). Exact Cloud behaviour is **UNVERIFIED** until a staging project exists.
- **Pool sizing risk:** default 10 + 20 overflow per API instance, plus the worker, can exceed the
  connection budget of small Supabase compute tiers. It needs explicit sizing (recommend 5 + 5 for API, 2 + 2 for worker).

## 6. Security implementation (current state)

| Area | Finding | Status |
|---|---|---|
| Authentication | JWKS (RS256/ES256) with `exp`/`aud`/`iss` required, 30 s leeway; HS256 only in local/test; inactive/unknown profile → 403 `ACCOUNT_INACTIVE`. Token never logged. | READ |
| Authorization | `require(module, action)` permission dependency per route. **294 of 300 endpoints require an authenticated user** (VERIFIED). | VERIFIED |
| Unauthenticated endpoints | `GET /health`; `GET /config/settings/public` (login branding, intended); **`GET /config/forms/{code}/published`, `GET /config/workflow/{code}/published`, `GET /config/templates/{code}/published`, `POST /config/forms/{code}/validate-submission`**. These four expose business configuration (forms, option lists, workflow, print templates) to anonymous callers. | **MEDIUM**, fixed in Phase 1: they now require any active signed-in user |
| RLS / grants | See §5: locked down, defence-in-depth behind the backend. | VERIFIED |
| Storage | Private `rms-videos` (1 GiB, mp4/quicktime) and `rms-documents` (25 MB, jpeg/png/pdf/heic); public `rms-branding` (2 MB). **No `storage.objects` policies**, so only signed URLs work (VERIFIED). Object paths are server-generated `gs/{gs_id}/{kind}/{uuid}.{ext}` (no path traversal); MIME + extension allow-list + size check in `attachments/allowlist.py`. | VERIFIED / READ |
| Secrets | `SecretStr` for all secrets; `scripts/check-secrets.sh` **passes**; no service-role key in `frontend/`. Only dummy/local-demo JWT strings in tests. **Credential files not ignored (B1).** | VERIFIED |
| CORS | Explicit allow-list, credentials off, `*` rejected in prod. | READ |
| Security headers (API) | nosniff, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, COOP, Permissions-Policy, `CSP default-src 'none'`, `Cache-Control: no-store`, HSTS in prod. | READ |
| Security headers (SPA) | Only via `render.yaml` (nosniff, DENY, referrer). **No CSP and no HSTS for the static site yet.** | finding |
| Rate limiting | slowapi, **only on 4 upload endpoints**. Login is handled by Supabase Auth (its own rate limits). The anonymous POST `validate-submission` is not limited. The limiter is in-memory, so the limit applies per instance. Behind Render's proxy, `--forwarded-allow-ips="*"` makes the client IP come from `X-Forwarded-For`. | finding |
| API docs | `/docs`, `/redoc`, `/openapi.json` are public in every environment, including prod. This discloses the full API surface. | LOW, fixed in Phase 1: not served when `APP_ENV=prod` |
| Auth settings | Local `config.toml`: sign-up disabled, **min password length 6, no complexity rules**, JWT expiry 3600 s, e-mail confirmations off. Cloud Auth settings are configured in the dashboard, not by `config.toml`. They must be set deliberately. | finding |
| Dependency vulnerabilities | Not yet scanned (`pip-audit` / `pnpm audit`). | NOT TESTED |

## 7. Deployment readiness (existing artefacts)

- `docs/DEPLOYMENT_READINESS.md` (P4-05) describes the target architecture correctly at a high level, but
  its embedded blueprint differs from the real `render.yaml` and both contain errors. **Treat it as unverified.**
- `render.yaml` defects: `APP_ENV: production` (crash), `pip install -r requirements.txt` (file absent),
  `PORT` hard-set to 8000 (unnecessary, Render injects it), `SUPABASE_KEY` / `APP_DEBUG` / `RATE_LIMIT_*`
  unused, frontend `VITE_API_URL` (wrong name), and `plan: standard` (cost decision is yours).
  The worker service is correctly modelled (`python -m app.worker`, one instance).
- Health: `GET /api/v1/health` is a liveness probe (no DB). There is no readiness probe and no root `/health`.
- SPA rewrite is present twice (`public/_redirects`, `render.yaml` routes). Render static sites use the
  `routes` block, so this is fine.
- pnpm: `package.json` has no `packageManager` field, so the pnpm version used on Render is not pinned.
- Python: `.python-version` (3.12) is in `backend/`; Render must get 3.12 via `PYTHON_VERSION` or that file (to confirm against Render docs in Phase 8).

## 8. Tests and quality baseline

Inventory: backend `tests/{unit,contract,integration}` (73 test files), frontend 29 vitest unit files,
**27 Playwright specs** (incl. `phase11_new_flow.spec.ts`, `login_all_users`, `responsive_a11y_audit`),
38 pgTAP files. Known from project notes: the full pytest takes ~13 min; 3 tests are data-dependent after a fresh
reset; some older e2e specs use stale login labels; there is pre-existing lint debt in a few modules.

Baseline run in Phase 0 (non-destructive only; DB-writing suites deliberately **not** run, to protect local data):

| Check | Command | Result |
|---|---|---|
| Backend lint | `.venv/Scripts/ruff check .` | **FAIL: 55 errors**, all in `backend/scripts/` (seed_perf_dataset 26, verify_p4_03 16, verify_p4_04 5) and 8 in `tests/integration/*`. **`backend/app` is clean.** Mostly E501/E402. There are 4 BLE001 (blind except) and 1 S106; review those. |
| Backend types | `.venv/Scripts/mypy app` | **PASS**, no issues in 240 files |
| Backend unit tests | `.venv/Scripts/pytest -q tests/unit` | **PASS**, 178 passed (43 s) |
| Frontend types | `pnpm typecheck` | **PASS** |
| Frontend lint | `pnpm lint` (`--max-warnings 0`) | **FAIL: 131 problems (125 errors, 6 warnings)**. Main rules: no-confusing-void-expression 68, no-unnecessary-condition 13, react-hooks/set-state-in-effect 11, exhaustive-deps 6, no-misused-promises 5. Worst files: `App.tsx` 21, `RmReviewPage.tsx` 19, `GoodsSlipDetailPage.tsx` 11. `vite.config.ts` uses deprecated `rollupOptions` (Vite 8 → `rolldownOptions`). |
| Frontend unit tests | `pnpm test` | **PASS**, 207 passed (29 files) |
| Frontend prod build | `pnpm build` with dummy `https://` values | **PASS**. Main chunk 588 kB (142 kB gzip). `DEPLOYMENT_READINESS.md` quotes 114 kB, now outdated. |
| Bundle localhost scan | `grep dist/assets` | **FAIL**: `configApi-*.js` contains `http://localhost:8000` (B3, a real request target). `index-*.js` contains `127.0.0.1:54321` (only in a login error *message*, misleading in prod). `vendor-supabase` contains `localhost:9999` (library-internal default, harmless). |
| Secrets scan | `scripts/check-secrets.sh` | **PASS** |

**Not run in Phase 0:** integration pytest, pgTAP (`supabase test db`), Playwright. These write to or reset
the local database and need your go-ahead (see §11).

## 9. Business-workflow coverage relevant to the regression phase

The Gate Keeper / GS journey (state, station, party, carton count, gate-entry date incl. backdating, received
through, remarks, documents incl. courier slip, per-carton opening video, counting, categorisation into
Fresh/Sales Return, Damaged, Scratched, Different Item, quantity allocation) is implemented in modules
`goods_slips`, `unboxing`, `itemization`, `inspection`, `rm_review`, `department_routing`, `final_actions`,
`ac_entry`, `dispatch`. It is covered by pgTAP `08`, `09`, `10`, `29`, `30`, `32`–`36` and by Playwright `gate_inward*`,
`unboxing`, `itemization`, `phase11_new_flow`. The source of truth for expected behaviour is
`RMS_DEVELOPMENT_MASTER_PLAN.md` §3–§5, `docs/RMS_MASTER_PLAN_ADDENDUM_2026-11.md` and `docs/DECISIONS.md`.
**No new business rule will be introduced.** Regression work will run and extend these suites.

## 10. Remediation plan / execution roadmap

Each phase ends with a report (inspected, changed, files, tests run with real output, blockers, approval needed).

| Phase | Work | Needs your approval |
|---|---|---|
| **1 Backend** | Add root `GET /health` (liveness) + `GET /api/v1/health/ready` (DB `select 1`, no secrets); require auth on the 4 config snapshot endpoints (after checking every frontend caller sends a token); disable `/docs`/`/openapi.json` when `APP_ENV=prod`; rate-limit the remaining anonymous POST; prod-safe pool defaults; verify CORS/headers with real requests. | the endpoint auth change (behaviour change) |
| **2 DB & Storage** | `DATABASE_MIGRATION_GUIDE.md`: Cloud bootstrap order (migrations → `rms_api` password → reference seed *without* DEMO → stations/parties/products → super-admin bootstrap); verify the BYPASSRLS / pooler questions on a **staging** Cloud project; storage upload/download round-trip test. | creating a staging project |
| **3 Frontend** | Fix `configApi.ts` (use the shared authenticated client and the real paths); remove silent localhost/host fallbacks in production builds (fail loudly); add CSP/HSTS for the static site; desktop + 360 px browser check. | — |
| **4–5 Regression & QA** | Run the full pytest + pgTAP + Playwright on a **fresh local DB** (needs `reset-db.ps1`, which first backs up the current DB to `backups/`), fix stale specs, add rejecting tests for any new guard/auth change, write `QA_TEST_REPORT.md` with PASS/FAIL/BLOCKED. | resetting the **local** DB (backup is taken first) |
| **6 Env config** | `ENVIRONMENT_VARIABLES.md`; align `.env.example` files; production values only in Render. | — |
| **7 GitHub** | Fix `.gitignore` (credential files, screenshots, working CSVs); first commit on a `main` branch; private repo; `GITHUB_DEPLOYMENT_GUIDE.md`. | repo name/visibility, first push |
| **8 Render** | Rewrite `render.yaml` (API web service + one worker + static site) with correct commands/env names, no secrets, `autoDeploy` off until approved. | plans/costs, creating services |
| **9 CI** | GitHub Actions: ruff, mypy, unit pytest, pgTAP + integration via `supabase start` in CI, frontend lint/typecheck/test/build, secrets scan. No automatic production migrations. | — |
| **10 Deploy** | GitHub → Supabase Cloud → Render API → Render static → end-to-end smoke through the public URL. | every production step |
| **11–12** | Security/performance audit (pip-audit, pnpm audit, headers, RLS, indexes, response times), final docs (`PRODUCTION_*`, `ROLLBACK_AND_RECOVERY.md`, `PRODUCTION_RUNBOOK.md`). | — |

## 11. Decisions needed from you before / during Phase 1–2

1. **Credentials file (B1):** OK to add `RMS_USER_CREDENTIALS.txt` (both copies) to `.gitignore`? Is the shared
   UAT password ever used anywhere real? If yes, it must be rotated.
2. **Working CSVs and screenshots** (`items.csv`, `party_*.csv`, `product_*.csv`, `frontend/x/`): keep them out of Git (recommended)?
   Note that `supabase/seed_parties.sql` / `seed_products.sql` contain party/product master data and *will* be committed,
   so the GitHub repository **must be private**.
3. **Master data (B6):** the full product CSV and the 288 SKIP party rows. Go-live needs these. Should change-plan Phase 0
   (server-side ON-HOLD write block) be completed before go-live?
4. **Supabase plan (B7):** Pro (needed for videos > 50 MB, daily backups, PITR add-on) or Free with a lower video limit?
   Region: Mumbai (`ap-south-1`) recommended for users in India, with Render in Singapore (closest Render region).
5. **Behaviour changes in Phase 1:** require auth on the 4 public config endpoints, and hide API docs in prod. OK?
6. **Local DB reset for full regression:** OK to run `scripts/reset-db.ps1` (it backs up the current DB first)?

*Answered 2026-11-14:* 1 yes · 2 yes · 3 go live with the current products, add more later by CSV/SQL · 4 Free tier
first · 5 Claude's call (done in Phase 1) · 6 yes. B10: build user administration (done) · B11/B12: Claude's call (done).

## 12. Credentials policy (adopted 2026-11-14)

The shared local UAT password and the `*@rms.local` accounts exist only for local development and UAT.

1. **Never in production.** No production account may use the UAT password or an `@rms.local` address. Production
   users are created by an administrator in **User Management** with a generated initial password and "set their own
   password at first sign-in" ticked (DEC-50).
2. **Never point the local scripts at production.** `scripts/reset-db.*`, `scripts/uat-reset.*`,
   `backend/scripts/uat_reset.py` and `backend/scripts/seed_demo_users.py` reset data and create UAT users. The first
   production Super Admin is created once with `backend/scripts/bootstrap_super_admin.py`, which reads the
   e-mail and password from the environment or a prompt. That password is changed right after the first sign-in.
3. **The sign-in page never shows credentials in production builds.** The UAT quick-fill exists only in dev builds
   (`import.meta.env.DEV`). CI will grep the production bundle for the UAT password (Phase 9).
4. **Credential files stay local.** `RMS_USER_CREDENTIALS.txt` is git-ignored. Production secrets live only in Render
   environment variables and the Supabase dashboard.
5. **Forgotten passwords** go through an administrator ("Reset password" → temporary password → forced change). There
   is no self-service reset e-mail (DEC-50).
