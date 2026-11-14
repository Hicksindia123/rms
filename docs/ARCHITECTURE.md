# Architecture

This is a summary. The authoritative design is
[`RMS_DEVELOPMENT_MASTER_PLAN.md`](../RMS_DEVELOPMENT_MASTER_PLAN.md), especially §6 (architecture), §7
(stack), §8 (database), §9 (auth) and §11 (UI). If this file and the master plan disagree, the master plan
wins. Fix this file.

## What RMS is

A configuration-driven mini-ERP that tracks replacement and sales-return consignments from gate inward to
GS closure. It covers unboxing evidence, itemisation, product-specific inspection, custody handover,
servicing, dismantling, custody segregation, store issue, replacement dispatch and Credit Note resolution.
One Postgres database, a versioned workflow engine, a quantity-based inventory ledger, and full audit.

## High-level shape

```text
React SPA (Vite, TS)  ──Bearer JWT──▶  FastAPI  ──SQL (txn)──▶  Supabase Postgres
   │  supabase-js: auth session,          │                        (RLS on every table,
   │  Realtime (own notifications/tasks), │ service role:           triggers, rms_move_stock)
   │  uploads to signed URLs              │ storage URLs, auth admin
   └──────────────────────────────────────┴──▶ Supabase Auth / Storage / Realtime
```

- **FastAPI is the single business gateway.** The frontend never reads or writes business tables
  directly.
- **Defence in depth.** API permission checks, plus DB constraints, triggers and `SECURITY DEFINER` stock
  functions. RLS is enabled everywhere, and the backend connects as the dedicated `rms_api` role.
- **Workflow engine.** Versioned stage, step and transition definitions in the DB, evaluated by a backend
  `WorkflowService`. System guards G-01…G-18 cannot be removed by configuration.
- **Inventory ledger.** `stock_lots` / `stock_movements` (insert-only) / `stock_balances`. Every custody
  holder is an `inventory_location`. All movements go through `rms_private.rms_move_stock` (locking,
  non-negative stock, guard checks, idempotency key).
- **Configuration-driven forms.** Typed core columns, plus admin-defined fields in JSONB tagged with the
  form version. One JSON rule format, evaluated in TS (UX) and Python (authoritative), parity-tested via
  `shared/rules-test-vectors.json`.
- **History safety.** Published form, workflow and template versions are immutable. Transactions store
  the version and label snapshots.

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | FastAPI app (`app/core`, `app/shared`, `app/modules/<module>/{router,schemas,service,repository}.py`), `scripts/`, `tests/` |
| `frontend/` | Vite React app (`src/app`, `src/components/{ui,erp}`, `src/features/<module>`, `src/lib/{api,rules}`, `src/hooks`, `src/styles`), `tests/{unit,e2e}` |
| `supabase/` | `migrations/` (only schema source), `seed.sql`, `tests/` (pgTAP), `config.toml` |
| `shared/` | Cross-language artifacts (rules test vectors) |
| `scripts/` | `dev`, `test-all`, `check-secrets` (PowerShell + bash) |
| `docs/` | This file, `DECISIONS.md`, `PROGRESS.md`, `SETUP.md`, `API.md` (+ `UAT.md`, `RUNBOOK.md` later) |

## Backend layering

`router` (HTTP, auth, permission dependency, Pydantic I/O) → `service` (business rules, guards,
transitions, one transaction per command) → `repository` (SQL only). Commands set
`SET LOCAL app.user_id` for audit triggers. Stock and commercial commands accept `Idempotency-Key`.

## Backend conventions

Introduced in P1-03. Every module builds on `backend/app/core` and `backend/app/shared`.

### Core package

| File | Responsibility |
|---|---|
| `core/config.py` | `Settings` (pydantic-settings) from env / `backend/.env` (§12.4). Required values (`DATABASE_URL`, `SUPABASE_URL`) fail fast at startup. `APP_ENV` ∈ `local`, `test`, `dev`, `prod`. Secrets are `SecretStr`. |
| `core/db.py` | SQLAlchemy 2 engine (psycopg 3, pool settings from env). `UnitOfWork.transaction(user_id)`: one transaction per command, commit on success, rollback and re-raise on any exception. It first sets `app.user_id` / `app.request_id` with `set_config(…, true)`, which is SET LOCAL with bind parameters. The audit trigger (G-17) and `created_by` defaults read these. |
| `core/security.py` | Verifies Supabase access tokens: RS256/ES256 via cached JWKS, HS256 only for `APP_ENV` local/test. Always checks `exp`, `aud`, `iss`. `get_current_user` returns 401 for a missing/invalid token, and 403 `ACCOUNT_INACTIVE` for an inactive or missing profile. |
| `core/permissions.py` | `effective_permissions` = role permissions + live grant overrides − live deny overrides (deny wins, expired overrides ignored, widest scope wins). Computed once per request. `require(module, action)` dependency. `assert_step_actor(session, user, step_code, assignment_type)` reads `step_assignments` of **published** workflow versions. Super Admin passes all of these, but never a system guard. |
| `core/errors.py` | `DomainError` → `ValidationFailed` 422, `Unauthenticated` 401, `PermissionDenied` 403, `NotFound` 404, `Conflict` 409 (→ `IdempotencyConflict`, `SystemGuardViolation`/`SystemGuardError` with code `G-xx`), `ServiceUnavailable` 503. Handlers return `{"error":{"code","message","details","request_id"}}`. A DB error whose message names a guard (`G-xx: …`, raised by a trigger) becomes the same 409 `G-xx` envelope. |
| `core/logging.py` | structlog: console renderer when local, JSON otherwise. Sensitive fields are redacted and headers are never logged. `RequestContextMiddleware`: accepts/generates `X-Request-ID`, writes one access line (method, path, status, duration, user id), and turns any escaped exception into a 500 envelope (stack trace only when `APP_ENV=local`). |
| `core/idempotency.py` | `IdempotencyKeyDep` (mandatory `Idempotency-Key` header, 8–200 chars) and `run_idempotent(session, key, user_id, command)`. Rows live in `rms_private.idempotency_keys` inside the command's own transaction. |
| `core/middleware.py` | Security headers, CORS allow-list (`CORS_ORIGINS`), slowapi `limiter`. Endpoints opt in with `@limiter.limit(...)`; there is no global limit. |
| `core/identity_repository.py` | SQL for profiles, roles, permissions, overrides and step assignments used by the core. |
| `shared/pagination.py` | `PageParamsDep` (`page`, `page_size` capped at `PAGE_SIZE_MAX`, `sort=-a,b`, `filter[x]=v`) and `Page[T]` = `{items, total, page, page_size}`. Sort and filter fields go through repository allow-lists. |
| `shared/storage.py` | `StorageService` (service-role client): signed upload URL, signed download URL (TTL = `SIGNED_URL_TTL_SECONDS`), existence/size, delete. `build_object_path(gs_id, kind, ext)` → `gs/{gs_id}/{kind}/{uuid}.{ext}`. Never derived from user file names. |

### Writing a module

Copy `app/modules/_template` (it is **not** mounted in `main.py`; the integration tests mount it):

```text
app/modules/<module>/
  router.py      HTTP only: Depends(require(...)), Pydantic I/O, IdempotencyKeyDep. No SQL.
  schemas.py     Request models use extra="forbid". Response models are explicit.
  service.py     Business rules and guards. One `with uow.transaction(user.id)` per command.
  repository.py  SQL only (sqlalchemy.text with bound parameters). Takes the caller's Session.
```

* Routes are mounted under `/api/v1` in `app/main.py`.
* A command that changes stock or commercial state takes `IdempotencyKeyDep` and wraps its work in
  `run_idempotent(...)` **inside** its transaction. The router returns `result.to_response()`.
* System guards are raised as `SystemGuardViolation("G-xx", …)` (or `enforce_guard(...)`) in the
  service, **and** enforced in the DB. Nothing in the permission layer catches them.
* Cross-module calls go service → service, never into another module's repository.
* Sync endpoints and a sync engine are used. FastAPI runs them in its threadpool.

### Request lifecycle

`RequestContextMiddleware` (request id, access log, last-resort 500) → security headers → CORS →
rate limiter → router → `get_current_user` (token → profile, roles) → `require(...)` (effective
permissions, cached on the request) → service (`UnitOfWork` transaction with the audit context) →
repository.

### Tests

* `tests/unit`: no database.
* `tests/integration`: against `TEST_DATABASE_URL` (default: local Supabase on `127.0.0.1:54322`).
  Every test runs in one outer transaction that is always rolled back. The app's UoW uses
  savepoints on that connection as the `rms_api` role. Fixtures: `make_token` (JWT factory signed with
  the local test secret), `users.create(roles=…, active=…, super_admin=…, overrides=…)`,
  `publish_workflow(...)`, `client` (httpx over ASGI). Integration tests are **skipped, with the
  reason printed**, when the DB is unreachable. Non-local hosts are refused.

## Database foundation (P1-02)

Migrations in `supabase/migrations/` (timestamped, applied in order):

| File | Contents |
|---|---|
| `…0100_extensions_schemas_roles.sql` | `pgcrypto`, `citext`, `pg_trgm` (schema `extensions`); schema `rms_private`; role `rms_api` (LOGIN, BYPASSRLS, no password in SQL); default privileges; helpers `current_actor()`, `current_request_id()`, `set_updated_at()`, `raise_insert_only()` |
| `…0200_identity_rbac.sql` | §8.1 tables; system-role protection; `is_super_admin` guard; `auth.users` → `profiles` trigger |
| `…0300_masters.sql` | §8.2 master tables |
| `…0400_config.sql` | §8.3 tables; option-code immutability; G-18 version guards; `rms_private.next_number()` |
| `…0500_audit_notifications.sql` | §8.7 tables (`idempotency_keys` lives in `rms_private`); generic `rms_private.audit_row()`; `rms_private.attach_standard_triggers()` |
| `…0600_storage.sql` | Buckets `rms-videos`, `rms-documents` (private), `rms-branding` (public) |
| `…0700_rls.sql` | RLS on every table; grants; notifications policies; Realtime publication |

Conventions every later migration must follow:

- **New table → `select rms_private.attach_standard_triggers('public.<table>');`** This adds
  `set_updated_at` (if the table has `updated_at`) and the `audit_row` trigger (G-17). Then
  `alter table … enable row level security;`. The pgTAP tests fail if either is missing.
- `created_by` defaults to `rms_private.current_actor()`, i.e. the backend's
  `SET LOCAL app.user_id`. `audit_log.request_id` comes from `SET LOCAL app.request_id`.
- Numbers come from `rms_private.next_number(series_code, on_date)`, inside the caller's transaction.
- `audit_log` and `config_change_log` are insert-only: privileges are revoked and triggers raise on
  UPDATE/DELETE/TRUNCATE.
- Published form, workflow and print-template versions are immutable (G-18). Fields, stages, steps,
  transitions and step assignments can only change while their version is `DRAFT`. Form responses must
  reference a `PUBLISHED` form version.
- Access: `anon` has nothing. `authenticated` can only `SELECT` its own `notifications` and
  `UPDATE (read_at)` on them. `rms_api` (the backend) has DML on `public` and `rms_private` and bypasses RLS.

### Default role → permission matrix (seed)

Seeded in `supabase/seed.sql`, all with scope `all`. Admins change it in the Permission Matrix (P1-05).
Permissions = 20 module codes × 7 actions (`view`, `create`, `edit`, `approve`, `delete`, `export`,
`configure`) = 140. The module codes are the §6.2 backend packages plus `roles` and `masters` (used by
P1-05 and P1-06). `auth` gets no permissions because login is not permission-checked.

Every operational role also gets `dashboards:view` and `notifications:view`.

| Role | Module: actions |
|---|---|
| `SUPER_ADMIN` | Every permission. This is the marker role: real Super Admin rights come from `profiles.is_super_admin`, and system guards still apply. |
| `GATE_INWARD` | goods_slips: view, create · attachments: view, create |
| `INWARD_VERIFIER` | goods_slips: view, edit · unboxing: view, create, edit · attachments: view, create · itemization: view, create, edit · inspection: view, create, edit · container_audit: view, create, edit · custody: view, create · reports: view |
| `REPLACEMENT_MANAGER` | goods_slips: view, edit, approve · unboxing: view, approve · attachments: view · itemization: view, approve · inspection: view, approve · container_audit: view · custody: view, approve · inventory: view, approve, export · servicing / dismantling / dispatch: view · credit_notes: view, create, approve · reports: view, export · audit: view |
| `INTERMEDIATE_STORE_MANAGER` | goods_slips: view · attachments: view · custody: view, create, edit, approve · inventory: view, create, edit, export · servicing: view, create, edit · dispatch: view, create · reports: view |
| `TECHNICIAN_COORDINATOR` | goods_slips: view · servicing: view, create, edit · custody: view, create · inventory: view |
| `TECHNICIAN` | servicing: view |
| `SPARE_PARTS_TECHNICIAN` | dismantling: view, create, edit · inventory: view |
| `SPARE_PARTS_MANAGER` | inventory: view, create, edit, export · dismantling: view, create, edit, approve · custody: view, create, edit, approve · reports: view |
| `ACCOUNTS` | goods_slips: view · attachments: view · credit_notes: view, create, edit, approve, export · reports: view, export |
| `DISPATCH` | goods_slips: view · dispatch: view, create, edit · inventory: view |
| `MAIN_STORE` | inventory: view, edit · custody: view, approve |
| `MANAGEMENT_VIEWER` | view on every operational module, plus inventory: export · reports: view, export · audit: view |

Only `SUPER_ADMIN` holds `users`, `roles`, `masters` or `config` permissions, and only `SUPER_ADMIN`
holds `delete` or `configure`. Step-level authority (who may perform or approve a workflow step) comes
from `step_assignments` (P1-08), not from this matrix.

## Workflow engine

The workflow engine (`backend/app/shared/workflow_engine.py` and `backend/app/modules/config/workflow/`) coordinates end-to-end consignment progression across stages, steps, transitions, role assignments, and system guards.

### Core Architecture
- **Version Pinning & Immutability (G-18):** When a workflow definition is published, all stages, steps, step assignments, and transitions are frozen into an immutable version snapshot. Consignments (`goods_slips`) record the `workflow_version_id` at inception and are pinned to that version across their operational lifespan. Publishing a new version (e.g., v2) affects new consignments only; existing consignments remain on their pinned version.
- **WorkflowEngine Core:**
  - `load_version(version_id)`: Loads the frozen workflow version snapshot.
  - `available_transitions(entity, user)`: Computes the permissible forward/backward transitions for the entity's current step, checking user role/actor assignment (PERFORM/APPROVE) and evaluating JSON condition rules.
  - `assert_can_transition(entity, to_step, user)`: Authoritative transition validator that evaluates condition rules and invokes system guard callables.
  - `record_transition(entity, to_step, user, reason, metadata)`: Executes the transition and records immutable audit history (`gs_status_history`).
- **System Guards Registry & Enforcement:**
  - System guards (`G-01` to `G-18` defined in Master Plan §4.2) represent non-bypassable constraints.
  - Transitions link guards to steps. The `WorkflowEngine` guard registry maps guard codes (`G-xx`) to Python callables. Unimplemented guards raise `NotImplementedError` in tests, ensuring no guard check is silently skipped.
  - **Locked Guards (SYSTEM_GUARD_LOCKED):** Core transitions (such as `G-01` gate inward verification, `G-02` unboxing count match, `G-18` immutability) are locked by system rules. Attempts to remove or modify locked guards on transitions are rejected with HTTP 422 `SYSTEM_GUARD_LOCKED`.
- **Graph Reachability & Validation:**
  - Before publishing any draft workflow, the graph reachability validator verifies that every active step is reachable from the starting step (`S1_GATE`), can reach a terminal step (`S6_CLOSE`), and that all locked system guards are intact.
- **Administrative Configuration & Versioning:**
  - `GET /api/v1/config/workflow/{code}`: Retrieves current workflow definition metadata and latest published version.
  - `POST /api/v1/config/workflow/{code}/draft`: Clones the published version into a draft version.
  - `PUT /api/v1/config/workflow/draft/{draft_id}`: Allows editing stages, steps, SLA hours, approval gates, role/user assignments, and transition condition rules.
  - `POST /api/v1/config/workflow/draft/{draft_id}/publish`: Freezes snapshot into a new `PUBLISHED` version, retires the previous version, requires a mandatory reason, and logs a high-severity entry in `config_change_log`.
  - `GET /api/v1/config/workflow/{code}/diff`: Side-by-side JSON diff between any two versions.

### Numbering Series & Provisional Settings
- **Number Series (`/api/v1/config/numbering`):** Document numbering engine supporting `{PREFIX}`, `{FY}`, `{YYYY}`, `{YY}`, `{MM}`, `{SEQ:n}` tokens, configurable start value, reset policies (`YEARLY_FY`, `MONTHLY`, `NEVER`), and live 3-number preview with fiscal year rollover testing (e.g. 31-Mar vs 01-Apr). Includes `DEC-01` provisional Goods Slip format banner.
- **Provisional Decision Rules (`/api/v1/config/settings`):** Exposes 20 Master Plan §5 provisional decisions (`DEC-01` to `DEC-20`) in a dedicated admin group with descriptions and runtime values, along with shell branding (logo upload with presigned URLs and WCAG color contrast validation).
- **Print Templates (`/api/v1/config/templates`):** Versioned JSONB layouts (paper sizes A4/A5/label, whitelisted data dictionary, header/footer, signature blocks) with live "SAMPLE PREVIEW" rendering for `REPLACEMENT_SLIP`, `GS_TAG`, `TRANSFER_NOTE`, `STORE_ISSUE`, and `CN_SUMMARY`.
- **System Guards & Config History:** Read-only `GET /api/v1/config/system-guards` (static catalogue G-01..G-18) and insert-only audit log `GET /api/v1/config/history`.

## Inventory ledger (P2-01)

The generic inventory ledger (`supabase/migrations/20261102000900_p2_01_operational_schema_ledger.sql` and `backend/app/modules/inventory/ledger_service.py`) provides single-source-of-truth quantity tracking across all consignment lifecycle stages, storage locations, and custody boundaries (§8.5).

### Architecture & Principles
1. **Single Entry Point (`rms_move_stock`):** Direct SQL `INSERT`, `UPDATE`, or `DELETE` on `stock_movements` or `stock_balances` is strictly prohibited by database triggers (`stock_movements_immutable`) and revoked privileges. All quantity changes MUST execute through `rms_private.rms_move_stock` or `rms_private.rms_reclassify_lot`.
2. **Row-Level Concurrency Locking:** `rms_move_stock` performs `SELECT qty FROM public.stock_balances ... FOR UPDATE` on the source location before checking balance or mutating rows. Parallel transactions attempting to deduct balance are strictly serialized, preventing double-allocation and race conditions.
3. **Idempotency Guarantee:** Every stock movement requires an `idempotency_key`. Replaying the same key with identical arguments returns the original movement UUID; replaying with differing parameters immediately raises an `IDEMPOTENCY_CONFLICT` (G-16).
4. **Location Class Freeze:** Once any balance $> 0$ exists at an `inventory_location`, its `location_class` is immutable (enforced by trigger `inventory_locations_freeze_class`).

### Movement Types

| Movement Type | `p_from` | `p_to` | Purpose & Operational Flow | Applicable Guards |
|---|---|---|---|---|
| `INWARD` | `NULL` | TRANSIT | Initial gate consignment receipt against generated GS number | G-01, G-16 |
| `TRANSFER_OUT` | Source Loc | Dest Loc | Custody transfer initiation out of source location | G-04, G-08, G-12, G-16 |
| `TRANSFER_IN` | Source Loc | Dest Loc | Physical and digital transfer acceptance at destination | G-09, G-16 |
| `RECLASSIFY` | Same Loc | Same Loc | Lot condition grade change (movement pair: consume source lot + receive target lot) | G-04, G-05, G-08, G-12, G-16 |
| `RECEIPT` | `NULL` | Target Loc | Inward creation of salvaged parts or new replacement stock | G-04, G-05, G-12, G-16 |
| `CONSUME` | Source Loc | `NULL` | Consumable deduction (e.g. fresh batteries installed during repair) | G-10, G-16 |
| `ADJUST` | Source Loc | Target Loc | Physical inventory reconciliation adjustment | G-16 |
| `DISMANTLE_OUT` | Scrap Loc | `NULL` | Non-good/unrepairable unit consumed during parts recovery | G-16 |
| `DISMANTLE_IN` | `NULL` | Spare Parts Loc | Salvaged recovered parts (TIP, BODY, WIRE, PCB) credited to ledger | G-11, G-16 |
| `ISSUE` | Intermediate Store | Main Store | Functional sellable/repaired goods transferred to company main store | G-12, G-16 |
| `DISPATCH` | Intermediate Store | DISPATCHED | Replacement items issued to customer / party | G-16 |
| `CREDIT` | Intermediate Store | MAIN_STORE | Goods taken into commercial inventory upon Credit Note closure | G-13, G-16 |
| `DISPOSE` | Hazard Quarantine | SCRAP_DISPOSED | Certified hazardous mercury or unrecoverable scrap disposal | G-05, G-16 |

## Current state

| Prompt | What exists |
|---|---|
| P1-01 | Monorepo skeleton. FastAPI app with `GET /api/v1/health`. Vite React app shell page. Tooling (uv, ruff, mypy, pytest; pnpm, ESLint, Prettier, Vitest, Playwright). Scripts and docs. |
| P1-02 | Supabase project config, foundation schema (identity/RBAC, masters, configuration, notifications, audit, idempotency), storage buckets, RLS baseline, reference + demo seed, pgTAP tests. |
| P1-03 | Backend core (`app/core`, `app/shared`): settings, engine + Unit of Work, Supabase JWT verification, effective permissions / `require` / step actors, error envelope, structlog + request ids, idempotency, pagination, storage helper, CORS / security headers / rate limiter, module template, `GET /api/v1/me`, test harness. |
| P1-04 | Design system & UI shell: Exide palette, accessible components (Input, Select, AsyncCombobox, FileUpload, etc.), top bar, breadcrumbs, responsive layout, dark mode, keyboard navigation. |
| P1-05 | Identity & RBAC: User management, role CRUD, 140-permission matrix, user assignments, password reset, audit logging. |
| P1-06 | Master Data Management: Master catalog for customers/dealers, products, parts, locations, transporter fleet with bulk CSV upload and soft-delete guards. |
| P1-07 | Form Builder & Rules Engine: Configurable versioned forms, option sets catalog, TS/Python parity-tested conditional rules engine (40+ vectors), 19 published v1 forms, field traceability docs. |
| P1-08 | Workflow Engine & Administration: Configurable stages, steps, assignments (PERFORM/APPROVE), transitions, locked system guards (G-01..G-18), version pinning, number series preview, provisional DEC-01..DEC-20 business rules, branding settings, print templates with sample preview, and config audit history. |
| P2-01 | Operational Schema & Generic Inventory Ledger: 22 operational tables for Stage 1/1a (§8.4) & inventory ledger (§8.5); single guarded stock movement function `rms_private.rms_move_stock` and `rms_reclassify_lot` with G-04, G-05, G-08, G-12, G-16, row-level locking, and idempotency; `ledger_service.py`; guard implementations; `goods_slips` service with workflow version pinning, `gs_status_history`, and `workflow_tasks` lifecycle; concurrency tests (20 parallel requests); 422 envelope test endpoint. |
| P2-02 | Step-1 Gate Inward & GS Creation: Gate consignment creation, party/state/station selection with provisional flags, transport fields per delivery mode, gate document verification, GS tag print preview, and initial INWARD stock receipt. |
| P2-03 | Step-2 Unboxing Evidence: Photo and unboxing video upload, document classification (INVOICE, DELIVERY_CHALLAN, etc.), mandatory checklist verification, missing document exception path, and guarded completion (G-02). |
| P2-04 | Step-3 Itemisation & Categorisation: Line item counting against gate documents, line item corrections with RM approval, return categorisation (RO vs CSR), CSR approval workflow, and packaging checks. |
| P2-05 | Step-3 Visual Inspection & Extraction Reconciliation: Line-by-line grading across product categories (DMT: 8, Prismatic: 3, Enclosed Oval: 4 conditions), Enclosed Oval full opening protocol lock (BR-14 / G-06), quantity reconciliation (G-07, DEC-09), extraction tracking (DEC-07), segregated rejections routing (HOLD_PARTY_RETURN, TO_SPARE_PARTS, RECORDED_REJECT), mercury hazard quarantine and safety alerts (DEC-11, G-05), auto-transition to RM_REVIEW (`S1A_RM_ACTION`), and RM compensating reopen. |

## Condition routing table (P2-05)

Visual inspection and grading (§2.2, §3.2 DD r21–r43) maps physical piece conditions to inventory lots and storage locations based on `allowed_status` and `system_behavior`. The 15 seeded conditions across the 3 product categories are routed as follows:

| # | Category | Condition Code | Option Set | Allowed Status | System Behavior | Destination Location | Condition Class | Extraction Written? | Rule / DEC Reference |
|---|---|---|---|---|---|---|---|---|---|
| 1 | DMT | `DMT_OK_PACKED` | `DMT_CONDITIONS` | `YES` | *None* | `INWARD_STAGING` | `AS_RECEIVED` | Yes | DEC-07 (Reconciled extraction) |
| 2 | DMT | `DMT_DIRTY` | `DMT_CONDITIONS` | `YES` | *None* | `INWARD_STAGING` | `AS_RECEIVED` | Yes | DEC-07 (Reconciled extraction) |
| 3 | DMT | `DMT_OTHER_BRANDS` | `DMT_CONDITIONS` | `NO` | `REJECT_HOLD` | `REJECTED_HOLD` | `NOT_ALLOWED` | Yes | DEC-10 (Hold for party return) |
| 4 | DMT | `DMT_BROKEN_BODY` | `DMT_CONDITIONS` | `NO` | `TO_SPARE_PARTS` | `NON_FUNCTIONAL_STORE` | `NOT_ALLOWED` | Yes | DEC-10 (To spare parts for dismantling) |
| 5 | DMT | `DMT_WATER_DAMAGE` | `DMT_CONDITIONS` | `CONDITIONAL` | *None* | `INWARD_STAGING` | `AS_RECEIVED` | Yes | DEC-10, DEC-14 (Requires inspection / review) |
| 6 | DMT | `DMT_BATTERY_LEAK` | `DMT_CONDITIONS` | `CONDITIONAL` | *None* | `INWARD_STAGING` | `AS_RECEIVED` | Yes | DEC-10, DEC-14 (Requires technician check) |
| 7 | DMT | `DMT_DISPLAY_DEFECT` | `DMT_CONDITIONS` | `CONDITIONAL` | *None* | `INWARD_STAGING` | `AS_RECEIVED` | Yes | DEC-10, DEC-14 (Requires technical service) |
| 8 | DMT | `DMT_SHORT_QTY` | `DMT_CONDITIONS` | `YES` | `SHORT_QTY` | *N/A (Discrepancy only)* | *N/A (No stock created)* | No | DEC-09 (Shortage note; does NOT consume received pieces) |
| 9 | PRISMATIC | `PRS_OK` | `PRS_CONDITIONS` | `YES` | *None* | `INWARD_STAGING` | `AS_RECEIVED` | Yes | DEC-07 (Reconciled extraction) |
| 10 | PRISMATIC | `PRS_BULB_BROKEN_NO_HG` | `PRS_CONDITIONS` | `NO` | `RECORDED_REJECT` | `REJECTED_HOLD` | `NOT_ALLOWED` | Yes | DEC-10 (Recorded reject / scrap tracking) |
| 11 | PRISMATIC | `PRS_BROKEN_WITH_HG` | `PRS_CONDITIONS` | `NO` | `HAZARD` | `HAZARD_QUARANTINE` | `HAZARD` | Yes | DEC-11 (Mercury hazard alert, quarantine lot; G-05) |
| 12 | ENCLOSED_OVAL | `EO_OK` | `EO_CONDITIONS` | `YES` | *None* | `INWARD_STAGING` | `AS_RECEIVED` | Yes | BR-14, G-06, DEC-07 |
| 13 | ENCLOSED_OVAL | `EO_INNER_CAPILLARY_BROKEN` | `EO_CONDITIONS` | `CONDITIONAL` | *None* | `INWARD_STAGING` | `AS_RECEIVED` (`requires_evaluation=true`, `routing_hint='EVALUATE'`) | Yes | DEC-14 (Technical evaluation required) |
| 14 | ENCLOSED_OVAL | `EO_BULB_BROKEN_NO_HG` | `EO_CONDITIONS` | `NO` | `RECORDED_REJECT` | `REJECTED_HOLD` | `NOT_ALLOWED` | Yes | DEC-10 (Recorded reject / scrap tracking) |
| 15 | ENCLOSED_OVAL | `EO_BODY_BROKEN_HG` | `EO_CONDITIONS` | `NO` | `HAZARD` | `HAZARD_QUARANTINE` | `HAZARD` | Yes | DEC-11 (Mercury hazard alert, quarantine lot; G-05) |


## Custody engine (P3-01)

Every custody move from Phase 3 on is a **two-phase transfer** (BR-21, G-09), implemented once in
`backend/app/modules/custody/service.py` (engine functions run inside the caller's transaction, so
other services call them service-to-service) and repeated in the database by migration
`20261104000100_p3_01_custody_engine.sql`.

```
          initiate (source custodian)          accept, counts = sent (destination custodian)
 source ───────────────────────────► TRANSIT ──────────────────────────────────────────► destination
  ▲            TRANSFER_OUT            │  │            TRANSFER_IN            status ACCEPTED
  │                                    │  │ any count ≠ sent → DISCREPANCY (frozen in TRANSIT)
  └──── cancel (initiator, INITIATED) ─┘  └─► reconcile: both parties sign the same resolution,
        CANCEL_RETURN / RESEND_CORRECTED       or RM override (audited) → RECONCILED
```

| Status | Entered by | Stock | Exit |
|---|---|---|---|
| `INITIATED` | `initiate` (or a P2-04 CSR proposal taken over by the handover: `stock_moved` false → true) | in TRANSIT | `ACCEPTED`, `DISCREPANCY`, `CANCELLED` |
| `ACCEPTED` | receiver, `ACCEPTED_VERIFIED` (DD r45), every `qty_counted = qty_sent` | destination | terminal |
| `DISCREPANCY` | receiver, `DISCREPANCY` (DD r46) + notes | frozen in TRANSIT | `RECONCILED` |
| `RECONCILED` | an `APPLIED` row in `custody_reconciliations` | per resolution | terminal |
| `CANCELLED` | initiator, while `INITIATED` | back to source | terminal |

**Resolutions** (`custody_reconciliations`, initiator + receiver signatures, one person never signs
both sides; or `override` by a role in `custody_override_roles`, reason on every audit row):

| Code | Effect |
|---|---|
| `CANCEL_RETURN` | every piece TRANSIT → source |
| `RESEND_CORRECTED` | every piece → source, then a new transfer (`supersedes_transfer_id`) with the corrected lines (default: counted qty), initiated by the original sender |
| `ACCEPT_COUNTED_WITH_ADJUSTMENT` | counted pieces → destination; the shortfall → source (`RETURN_TO_SOURCE`) or `ADJUST` write-off (`WRITE_OFF_LOSS`); an excess count → `ADJUST` into the destination. Any ADJUST needs the RM's approval with reason (`AWAITING_RM_APPROVAL`). |

**Database enforcement (G-09)**: `custody_transfers_g09_guard` (state machine, ACCEPTED only with
matching counts, receiver ≠ initiator while `segregation_of_duties_transfer` is on, RECONCILED only
with an applied reconciliation, `stock_moved` never reset); `custody_transfer_lines_g09_guard`
(lines frozen once dispatched, counts recorded once); `stock_movements_g09_transit_guard` (any
movement into / out of a TRANSIT location must reference a `custody_transfer` in the matching state,
from / to its own locations, never more than the quantity sent); plus P2-08's
`custody_transfer_lines_g08_guard` (no Pending (BP) lot on a line). Movement idempotency keys are
deterministic per transfer, lot and event (`custody:{transfer}:{lot}:{dispatch|accept|return|loss|cancel|excess}`);
the HTTP commands also take an `Idempotency-Key` (replay → original response). Concurrent accepts
serialise on `SELECT … FOR UPDATE` of the transfer row (the second gets 409).

**Step-4 handover** (`GET/POST /gs/{id}/handover`): lines = allowed, non-pending stock of the GS in
`INWARD_STAGING`; held back with reason: Pending (BP) (`PENDING_HOLD`), Not Allowed (`REJECTED_HOLD`,
`NON_FUNCTIONAL_STORE`), Hazard (`HAZARD_QUARANTINE`) and pieces the RM marked Not Allowed beyond the
inspection rejections. Blocked unless the GS is `IN_PROCESS`, G-03 is decided, and (DEC-12
`pending_blocks_entire_gs`) no pendency is open. The GS stays `IN_PROCESS`; `has_discrepancy` follows
the transfers; the sender's S2_HANDOVER task stays open while eligible stock waits, the receiver gets
an S2_HANDOVER task per dispatched transfer. In the Intermediate Store, SELLABLE-routed lots (DEC-14)
can be classified Functional Good directly (`POST /custody/lots/{id}/classify`, reclassification in
place); every other lot awaits the technician (P3-02). The DEC-27 packaging check is the P2-04
endpoint. Transfer Note: `GET …/transfer-note` (preview) and `POST …/transfer-note/print` (logged in
`print_logs`, reprint watermark).
