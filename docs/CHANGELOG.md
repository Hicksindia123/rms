# Changelog

All notable changes to the **Replacement Management System (RMS)** project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to Semantic Versioning.

---

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
