# RMS Security Architecture & Hardening Guide

This document details the threat model, defensive controls, authorization guarantees, and verification evidence for the **Replacement Management System (RMS)** (Prompt P4-05).

---

## 1. Threat Model & Architecture Overview

RMS processes technical returns, warranty claims, high-value component salvaging, inventory ledger adjustments, and credit notes / journal vouchers. Its threat landscape spans external tampering, insider threat, unauthorized privilege escalation, and direct object reference manipulation.

```
+---------------------------------------------------------------------------------------+
|                                    Client Layer                                       |
|  - SPA Frontend (Vite / React)                                                        |
|  - Security Headers: X-Content-Type-Options: nosniff, X-Frame-Options: DENY, CSP       |
+-------------------------------------------+-------------------------------------------+
                                            | HTTPS / Bearer JWT
+-------------------------------------------v-------------------------------------------+
|                                  API Gateway / FastAPI                                |
|  - Rate Limiting (SlowAPI / Limiter): sensitive actions throttled                     |
|  - TokenVerifier: Exp, Aud, Iss, Alg (HS256 in test, RS256 in prod)                   |
|  - Account Status: Active Profile Check on every request (403 ACCOUNT_INACTIVE)       |
|  - GZip Compression & Response Sanitization                                           |
+---------------------+-------------------------------------+---------------------------+
                      |                                     |
+---------------------v-------------------+   +-------------v---------------------------+
|        Authorization & IDOR Layer       |   |             Storage Layer               |
|  - 13 Predefined System Roles           |   |  - Server-Generated Object Paths:       |
|  - User Permission Overrides            |   |    gs/{gs_id}/{kind}/{uuid}.{ext}       |
|  - Object Ownership & Step Actor Checks |   |  - MIME & Extension Allow-list          |
|  - Guard Rails (G-01 .. G-18)           |   |  - Short-Lived Signed URLs (Audited)    |
+---------------------+-------------------+   +-----------------------------------------+
                      |
+---------------------v-----------------------------------------------------------------+
|                             Database Layer (PostgreSQL / Supabase)                    |
|  - Row Level Security (RLS) on ALL tables                                             |
|  - Zero Privileges for `anon` role                                                    |
|  - App runs as least-privilege `rms_api` role                                         |
|  - Immutability Triggers on `audit_log` and `user_activity` (SQLSTATE 42501)          |
+---------------------------------------------------------------------------------------+
```

---

## 2. Authentication & Session Security

1. **Token Verification**:
   - Every request verifies JWT expiration (`exp`), audience (`aud`), issuer (`iss`), and cryptographic signature.
   - Algorithm policy rejects `none`, garbage, and mismatched symmetric tokens in production environments.
2. **Immediate Lockout on Deactivation**:
   - User profile status (`is_active`) is verified on every request.
   - Deactivating a user immediately invalidates active sessions with `403 ACCOUNT_INACTIVE`, preventing window-of-vulnerability attacks without requiring distributed token revocation lists.
3. **Security Headers**:
   - `X-Content-Type-Options: nosniff` (MIME confusion prevention)
   - `X-Frame-Options: DENY` (Clickjacking prevention)
   - `Referrer-Policy: strict-origin-when-cross-origin` / `no-referrer`
   - `Permissions-Policy: camera=(), microphone=(), geolocation=()`
   - `Content-Security-Policy: default-src 'none'; frame-ancestors 'none';` on API routes.

---

## 3. Role-Based Access Control & Authorization Matrix

The system enforces least-privilege access across **13 distinct system roles**:

| Role Code | Operational Scope | Key Permissions |
| :--- | :--- | :--- |
| `GATE_INWARD` | Inward gate security | `goods_slips.create`, `goods_slips.view` |
| `INWARD_VERIFIER` | Physical unboxing & inspection | `unboxing.create/edit`, `itemization.create/edit`, `inspection.create/edit` |
| `REPLACEMENT_MANAGER` | Decisions, approvals & review | `rm_actions.*`, `csr.*`, `inventory.manage`, `reports.view` |
| `TECHNICIAN_COORDINATOR` | Servicing allotment & receiving | `servicing.create`, `servicing.view` |
| `TECHNICIAN` | Component servicing bench | `servicing.view` |
| `SPARE_PARTS_TECHNICIAN` | Parts dismantling & recovery | `dismantling.create`, `dismantling.view` |
| `SPARE_PARTS_MANAGER` | Salvaged parts inventory & scrap | `inventory.view`, `dismantling.manage` |
| `INTERMEDIATE_STORE_MANAGER` | Functional inventory & store issue | `inventory.view`, `store_issue.create`, `custody.view/create` |
| `MAIN_STORE` | Main store receipt | `store_issue.acknowledge` |
| `DISPATCH` | Replacement logistics | `dispatch.create`, `dispatch.view` |
| `ACCOUNTS` | Commercial CN / JV issuing | `credit_notes.create`, `credit_notes.view` |
| `MANAGEMENT_VIEWER` | Read-only executive visibility | `dashboards.view`, `reports.view` |
| `SUPER_ADMIN` | System administration | Complete platform access (subject to system guards) |

### Permission Overrides Precedence
- **Deny Precedence**: Explicit `DENY` overrides win over any role grant.
- **Grant Overrides**: Confer specific elevated privileges to an individual account.
- **Guard Non-Bypassability**: System guards (e.g. `G-16` negative stock balance, `G-18` published workflow immutability) cannot be bypassed by any user, including `SUPER_ADMIN`.

---

## 4. Insecure Direct Object Reference (IDOR) Hardening

1. **Saved Views (`/saved-views`)**:
   - Queries strictly filter on `user_id = current_user.id`.
   - Modifying or deleting another user's view returns `404 SAVED_VIEW_NOT_FOUND` to eliminate existence oracle attacks.
2. **Task Inbox (`/tasks/mine`)**:
   - Standard users only receive tasks explicitly assigned to their user ID or active roles.
3. **Attachments (`/attachments`)**:
   - Confirmed files can only be deleted by the original uploader (`uploaded_by == user.id`), raising `403 NOT_UPLOADER` otherwise.
   - Access to signed download URLs requires verified visibility permissions on the parent Goods Slip.

---

## 5. Upload & Storage Hardening

1. **Server-Generated Paths**:
   - Client filenames are never used in object storage paths.
   - Objects are stored under strict UUID hierarchies: `gs/{gs_id}/{kind}/{uuid}.{ext}`.
   - Path traversal payloads (e.g. `../../etc/passwd.jpg`) in filename headers are completely neutralized.
2. **MIME & Extension Enforcement**:
   - Strict allowlist per attachment kind (`UNBOXING_VIDEO`, `DOC_PHOTO`, `PARCEL_PHOTO`, `NOTIFICATION_PROOF`).
   - MIME / extension mismatches (e.g., `image/jpeg` with `.exe`) are rejected with `422 FILE_NOT_ALLOWED`.
3. **Short-Lived Signed URLs**:
   - Download URLs are generated with short-lived signed tokens (default 300 seconds).
   - Issuance is audited in `access_audit` with timestamp, requester, and IP metadata.

---

## 6. Injection Defense & Input Hardening

1. **SQL Injection**:
   - All database interactions use SQLAlchemy parameter binding or pre-compiled prepared statements.
   - Trigram search queries (`pg_trgm`) parameterize query inputs.
   - Filter operators are validated against an allowlist (`eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `in`, `like`, `is_null`).
2. **Formula Injection (CSV / Excel Injection)**:
   - All cell values in exported CSV and XLSX files are sanitized via `_safe_csv_cell`.
   - Cells beginning with dangerous formula characters (`=`, `+`, `-`, `@`, `\t`, `\r`) are automatically prefixed with a single quote (`'`), preventing formula evaluation in Microsoft Excel, LibreOffice Calc, and Google Sheets.
3. **XSS Protection**:
   - User inputs in remark and label fields are stored as literal strings without HTML parsing.
   - Frontend UI renders text nodes safely using React JSX auto-escaping.

---

## 7. Database & Supabase Security

1. **Row Level Security (RLS)**:
   - Enabled across **100% of tables** in the `public` and `rms_private` schemas.
   - Verified via pgTAP test suite `27_security_rls.test.sql`.
2. **Zero Privileges for `anon`**:
   - Direct database access by unauthenticated clients is completely blocked (SQLSTATE `42501`).
3. **Append-Only Immutability**:
   - Tables `public.audit_log` and `public.user_activity` enforce an absolute prohibition on `UPDATE` and `DELETE` operations via database triggers, preserving forensic chain-of-custody.
4. **Least Privilege API Role (`rms_api`)**:
   - The backend service connects using dedicated role `rms_api`, with table access granted on operational tables only.

---

## 8. Verification & Test Evidence

All security controls are verified by automated test suites:

| Suite | File | Tests | Status |
| :--- | :--- | :--- | :--- |
| **Authz Matrix** | `backend/tests/integration/test_security_authz_matrix.py` | 8 | PASS |
| **IDOR Protection** | `backend/tests/integration/test_security_idor.py` | 3 | PASS |
| **Upload Security** | `backend/tests/integration/test_security_upload.py` | 5 | PASS |
| **Input Hardening** | `backend/tests/integration/test_security_input.py` | 4 | PASS |
| **Auth & Headers** | `backend/tests/integration/test_security_auth.py` | 4 | PASS |
| **Database RLS (pgTAP)** | `supabase/tests/27_security_rls.test.sql` | 12 | PASS |
