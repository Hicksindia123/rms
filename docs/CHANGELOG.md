# Changelog

All notable changes to the **Replacement Management System (RMS)** project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to Semantic Versioning.

---

## [1.1.0] - 2026-11-23 (not deployed)

The 12-step **Offline Return → Replacement** flow (`docs/RMS_PHASE_PROMPTS_20-11-2026.md`, phases
P0 – P12, decisions DEC-60 … DEC-72). Production steps: `docs/RELEASE_OFFLINE_FLOW_2026-11.md`.

### Added
- **Intermediate Stores** OP / DT / RI (Admin can rename and add), each with its own role and stock
  location, and a category / sub-category → store mapping (DEC-61). New role **Management** (approver,
  DEC-60).
- **Gate entry v4** with a summary sheet before the GS is created; image-only party and transport
  documents (DEC-62).
- **Unboxing**: one video per carton (G-02 changed by DEC-63) and one optional carton document.
- **Items → Replacement / Complete Sales Return popup → categorisation → Lock**; stock booked at the
  lock; Sales Return parks in *Sales Return – On Hold* (DEC-64).
- **Transfer slips** by the RM: one slip per Intermediate Store, many goods slips per slip, PDF with the
  HICKS logo; **Edit Request** to Management; a Management change voids the slips (DEC-65).
- **Store acknowledgement** per slip with discrepancy reports (DEC-66); **department routing** by the
  store user (saving = issue, DIN) with undo of "Issue to Store" lines (DEC-67); **receiving back** per
  store (DEC-68); **analysis** per item + condition: Dispatch New / Dispatch Repaired / Not Allowed,
  optionally sent for Management approval (DEC-69).
- **Management approval**: change any decision incl. Issue CN, approve with a verifiable
  "Digitally approved by Management" e-approval stamp (SHA-256 of the approved snapshot) (DEC-70).
- **Accounts per goods slip**: the GS reaches Accounts only when every store has submitted and no
  approval is pending; GS-wise **Replacement Slip**; one Challan and one Credit Note per GS; Dispatch
  Slip on completion; all Not Allowed → *On Hold – Not Allowed* (DEC-71).
- E2E `frontend/tests/e2e/offline_replacement_flow.spec.ts` (whole flow for 3 goods slips across the
  three stores at 1280 px and 360 px; Sales Return branch; Edit Request → void → regenerate).

### Changed
- Role menus follow the new flow (`docs/USER_GUIDE.md` §1.3). `INWARD_VERIFIER` is labelled
  "Replacement Executive".
- `docs/USER_GUIDE.md`, `docs/ADMIN_GUIDE.md` and `docs/UAT.md` (script O-01 … O-14) rewritten for the
  new flow.

### Retired (hidden, not deleted; goods slips from the earlier flow keep working from the GS page)
- RM Review edits, RM department routing plan, Store Manager acceptance / department issue, RE
  department receiving, RM final actions, the RM missing-document exception, the RM Approvals inbox and
  Inspection & Grading menus (DEC-63 … DEC-68, DEC-72); legacy widgets on the RM / RE dashboards.

### Known open points
- Q43: GENERAL products have no condition fields, so nothing reaches the RI store with today's masters.
- Email alerts for the new steps are deferred (Q22); in-app alerts only.

## [1.0.0] - 2026-11-07

### Added
- **Phase 1: Foundation, DB, Auth & Admin**
  - Supabase PostgreSQL schema with Role-Based Access Control (RBAC), Row Level Security (RLS) on all tables, and insert-only audit triggers.
  - FastAPI modular architecture with Dependency Injection, Unit of Work pattern (`UowDep`), Pydantic v2 schemas, and structured error responses (`DomainError`, `SystemGuardViolation`).
  - Dynamic Form Builder and rules engine with published form versioning (`draft`, `published`, `retired`) ensuring historical safety (G-18).
  - Workflow engine supporting step assignments, SLA timers, escalation policies, and number series formatting (`GS/{FY}/{SEQ:5}`).
  - Responsive React 18 frontend shell with mobile bottom navigation bar, token-based design system, and unified AppShell.

- **Phase 2: Gate & Inward Core**
  - Multi-mode Goods Slip inwarding (Courier, Direct Truck, Self Delivery) with automatic party state/station resolution (DEC-02).
  - Mandatory unboxing evidence enforcement (video and classified photo capture) preventing Step-2 entry without documentation (G-02).
  - Itemisation engine with document quantity vs physically received quantity tracking and shortage logging.
  - Complete Sales Return (CSR) approval/rejection decision board by Replacement Manager (G-03).
  - Three-category condition grading: DMT (8 statuses), Prismatic (3 statuses), Enclosed Oval (4 statuses with mandatory full-opening guard G-06).
  - Extraction quantity reconciliation enforcing strict conservation between packaging and container allocations (G-07).
  - Daily DMT Container Register with confirmation checks and compliance calendar tracking.
  - RM item-wise segregation (Send New, Send Repaired, Issue CN, Not Allowed, Pending BP) with Replacement Slip printing and pending transfer lock (G-08).

- **Phase 3: Processing, Servicing & Commercial Resolution**
  - Physical/digital custody synchronization engine with transfer notes, barcode scanning, and two-party count discrepancy reconciliation (G-09).
  - Technician servicing batch allotment, CR2032 battery balance tracking, exact battery stock deduction (G-10), and post-servicing classification.
  - Parts recovery dismantling workflow with TIP/BODY/WIRE/PCB extraction, partitioned container storage, and mandatory PCB model + supplier tracking (G-11).
  - Strict physical segregation boundary: Intermediate Store holds only Functional Good & Repaired stock; Spare Parts Manager exclusively holds Non-Functional, Scratched, and Scrap stock (G-04, G-12).
  - Store issue vouchers for transferring functional stock to Main Store.
  - Replacement dispatch tracking for Send New and Send Repaired units.
  - Comprehensive Credit Note engine: RM CN decision, Accounts party document review, GST portal status checking (G-13), rate verification against historical purchases (G-14), and GST CN vs General CN vs JV issuance.
  - Pre-closure party notification verification ensuring no GS can close without confirmed customer communication (G-15).
  - Formal GS closure snapshot and Closure Certificate generation.

- **Phase 4: Platform, Integration & Hardening**
  - Role-specific dashboards for all 13 system roles with widget configuration and realtime task notifications.
  - 18 comprehensive operational and management reports (R-01 … R-18) with Excel (.xlsx) and CSV export capabilities.
  - Centralized notification outbox and event dispatcher with email and SMS/WhatsApp channels.
  - Global search with PostgreSQL pg_trgm trigram indexes across GS numbers, party GSTINs, dockets, vehicle numbers, and container barcodes.
  - Comprehensive Audit Explorer and immutable GS Activity Timeline (G-17).
  - Security hardening: authorization matrix testing across all 13 roles, IDOR protection, upload file validation (MIME sniffing and path traversal prevention), CSV formula injection escaping, and deactivated-user immediate lockout.
  - Code splitting with Rolldown `manualChunks` reducing initial gzipped bundle to 114.35 kB.
  - Complete test traceability verifying 100% of Business Rules (BR-01 … BR-40) and System Guards (G-01 … G-18).
  - UAT environment reset script (`scripts/uat-reset.ps1`, `scripts/uat-reset.sh`, `backend/scripts/uat_reset.py`) supporting clean zero-demo-transaction database resets, UAT user provisioning, and real CSV data import.

### Fixed
- **Accessibility:** Resolved color contrast failure on active status badges in Option Sets Manager by adjusting green shade to `#166534` (7.87:1 contrast ratio, WCAG 2.1 AA compliant).
- **Code Hygiene:** Corrected ruff formatting and unused imports in `test_traceability_rules_and_guards.py`.
- **E2E Stability:** Resolved timeout during AxeBuilder responsive evaluation on complex multi-table views by tuning suite timeout to 60s.
- **Database Numbering:** Fixed counter cleanup in pgTAP tests to reset both `GS` and `TRANSFER` series sequences.

### Changed
- Refactored `test-all.ps1` and `test-all.sh` to provide an end-to-end unified verification pipeline covering security scans, database resets, pgTAP, backend lint/types/tests, frontend lint/build/tests, API type generation freshness, and database integrity invariants.
- Finalized role catalogue per master plan §3.3 with 13 standard roles and workbook personas.
