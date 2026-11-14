# CLAUDE.md — RMS standing rules

Standing rules for every Claude Code session on the **RMS (Replacement Management System)** repository.
They apply to every prompt (P1-01 … P4-07) and override convenience. Read this file and the relevant
sections of `RMS_DEVELOPMENT_MASTER_PLAN.md` before changing anything.

## Project at a glance

- **Requirements / architecture source of truth:** `RMS_DEVELOPMENT_MASTER_PLAN.md`.
- **Business source:** `Replacement_Management_System_Workflow.xlsx` is a **read-only reference**. Never modify,
  move, rename or re-save it (not even to "fix" formatting). Check its hash if in doubt.
- **Mandatory stack (do not substitute):** React 18 + TypeScript (strict, Vite) · Python 3.12 FastAPI +
  Pydantic v2 · Supabase (Postgres, Auth, Storage, RLS, Realtime). Package managers: `uv` (Python),
  `pnpm` (Node).
- **Deployment:** none. Render deployment is out of scope until explicitly requested.
- **Layout (master plan §6.3):** `backend/` · `frontend/` · `supabase/` · `docs/` · `scripts/` · `shared/`.

## STANDING RULES

### a. Inspect before editing

- Inspect the existing repository before editing: list files, read the configs and the code you are
  about to touch.
- Make minimal, targeted changes. Never delete or rewrite working functionality without need. Preserve
  everything that works.
- If a change would break existing behaviour, stop and explain instead of silently changing it.

### b. Requirements come from the master plan only

- Requirements live in `RMS_DEVELOPMENT_MASTER_PLAN.md`:
  - §3: the option catalogue (every dropdown option, verbatim, with its stable code).
  - §4: business rules **BR-01…BR-40** and system guards **G-01…G-18**.
  - §5: open decisions **DEC-01…DEC-34**.
- **Never invent business rules**, options, products, people or workflow steps.
- If a rule is unclear, implement the documented **provisional approach** from §5 *as configuration*
  (a setting, toggle or option), never as hidden code. Record it in `docs/DECISIONS.md`.
- Cite the source (BR-xx / G-xx / DEC-xx / `WF rN` / `DD rN`) in code comments, migrations and tests where
  a rule is enforced.

### c. System guards are non-bypassable

- System guards **G-01…G-18** (§4.2) must be enforced in the **database** (constraints, triggers, locked
  functions) **and** in **backend services**. They are never enforced only in the UI.
- Configuration must never be able to disable a guard. Not admin settings, option edits, workflow
  versions, or Super Admin status. The Admin Panel shows them read-only.
- Every guard has at least one automated test proving that it rejects the forbidden action.

### d. Schema changes = new migration files

- All schema changes go through **new** timestamped files in `supabase/migrations/`.
- **Never edit a migration that has been applied.** Fix forward with a new migration.
- **No Alembic** and no ORM-driven schema generation. SQLAlchemy maps onto the SQL schema; it does not
  own it.
- `supabase db reset` must rebuild the whole database (migrations + `seed.sql`) reproducibly.

### e. Business values come from DB configuration

- Labels, dropdown options, roles per step, numbering formats, templates, branding and similar business
  values come from the **DB configuration**. Never hard-code them in React (or anywhere else).
- Business logic keys off **stable option CODES** (e.g. `DMT_BROKEN_BODY`, `ALLOW_CN`), never off labels.
  Admins can relabel without breaking logic.
- Option codes are immutable once used. Transactions store label snapshots and the form/workflow
  version they were created under (G-18).

### f. Stock and commercial commands are transactional and idempotent

- Every stock-affecting or commercial command runs in a **single DB transaction**.
- All stock movement goes through **`rms_move_stock`** (`rms_private.rms_move_stock`). Never
  insert into `stock_movements` or update `stock_balances` directly.
- Such endpoints accept an **`Idempotency-Key`** header. A duplicate key returns the original result
  (G-16).
- Multi-line operations call `rms_move_stock` per line inside the same transaction, so any failure rolls
  back everything.

### g. Backend layering

- `router -> service -> repository`.
  - **router:** HTTP, auth dependency, permission dependency, Pydantic I/O. **No SQL.**
  - **service:** business rules, guards, workflow transitions, one transaction per command.
  - **repository:** SQL only. **No business rules.**
- Cross-module calls go service-to-service, never into another module's repository.
- Module layout: `backend/app/modules/<module>/{router,schemas,service,repository}.py`. Shared
  infrastructure is in `app/core/`. Shared domain helpers are in `app/shared/`.

### h. Frontend structure and UX states

- Reusable components go in `frontend/src/components` (`ui/` for primitives, `erp/` for composite
  business widgets). Feature code goes in `frontend/src/features/<module>`. Import via the `@/` alias.
- Every screen has **loading, empty, error and success** states. Errors show retry and the request id.
- Every screen works on **360px-wide phones**: no horizontal scroll (except opt-in wide reports),
  touch targets ≥ 44px. Desktop-friendly layouts at ≥ 1024px.
- All business data flows through FastAPI. `supabase-js` is used only for auth session, Realtime and
  uploads to signed URLs (§6.1).

### i. Secrets stay in the backend env

- Secrets exist only in `backend/.env` (git-ignored).
- **Never** put the Supabase service-role key, DB password or JWT secret in frontend code, in
  `frontend/.env*`, or in any committed file. `.env.example` files contain variable names only (no real
  values).
- The frontend may only hold `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` and `VITE_API_BASE_URL`.
- `scripts/check-secrets.(sh|ps1)` fails if any service-role reference appears under `frontend/`. Keep it
  passing.

### j. No fakes, no placeholders, no swallowed errors

- No mock data in production code paths. Fixtures and mocks live only in tests. Demo data lives only in
  the `-- DEMO` section of `supabase/seed.sql`.
- No placeholder buttons or dead links. If a feature isn't built yet, don't render a control for it.
- No silent exception swallowing. Handle errors explicitly, log them with context, and return the standard
  error envelope `{error:{code,message,details,request_id}}`. Never use bare `except:` or `except
  Exception: pass`.

### k. Definition of Done (every prompt)

A prompt is done only when **all** of these have been run and pass:

1. Migrations apply cleanly on `supabase db reset`.
2. Backend tests (`uv run pytest`), frontend tests (`pnpm test`), lint (`uv run ruff check .`, `pnpm lint`)
   and typecheck (`uv run mypy app`, `pnpm typecheck`) pass.
3. New/changed APIs are exercised (pytest and/or curl).
4. The UI is checked in the browser at desktop **and** mobile widths, with **no console errors**.
5. Backend logs are clean (no unexpected errors or warnings).
6. `docs/PROGRESS.md` is updated.

**Never claim completion without running these checks. Report the actual command output**, including
failures and anything skipped. `scripts/test-all.ps1` / `scripts/test-all.sh` runs the automated subset.

## Commands

| Purpose | Command |
|---|---|
| Start everything | `scripts/dev.ps1` (Windows) · `scripts/dev.sh` |
| Backend API | `cd backend && uv run uvicorn app.main:app --reload --port 8000` |
| Backend tests / lint / types | `uv run pytest -q` · `uv run ruff check .` · `uv run mypy app` |
| Frontend dev | `cd frontend && pnpm dev` (http://localhost:5173) |
| Frontend checks | `pnpm lint` · `pnpm typecheck` · `pnpm test` · `pnpm build` · `pnpm e2e` |
| API types | `pnpm gen:api` (backend must be running on :8000) |
| DB | `supabase start` · `supabase db reset` · `supabase test db` |
| All checks | `scripts/test-all.ps1 [-E2E]` · `scripts/test-all.sh [--e2e]` |
| Secrets scan | `scripts/check-secrets.ps1` · `scripts/check-secrets.sh` |

## Working process

- Run prompts strictly in order (see `docs/PROGRESS.md`). Tick a prompt only after its checks pass.
- New unresolved ambiguities go to `docs/DECISIONS.md` (and are raised in the completion report), not into
  code assumptions.
- Every prompt ends with a **completion report**: files created or changed, commands run with their real
  results, anything not done, and open questions.
