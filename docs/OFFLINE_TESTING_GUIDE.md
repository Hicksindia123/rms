# RMS Complete Offline Testing Guide

**Purpose:** Comprehensive, step-by-step instructions to run and test the complete **Replacement Management System (RMS)** locally and offline on your computer and local Wi-Fi network—**without deploying anything to Render or external cloud providers.**

---

## Table of Contents
1. [Prerequisites & System Checks](#1-prerequisites--system-checks)
2. [Step 1: Start Database & Reset to Clean UAT State](#2-step-1-start-database--reset-to-clean-uat-state)
3. [Step 2: Start the Local Application Stack](#3-step-2-start-the-local-application-stack)
4. [Step 3: UAT User Accounts & Credentials](#4-step-3-uat-user-accounts--credentials)
5. [Step 4: Running the Automated Test Pipeline](#5-step-4-running-the-automated-test-pipeline)
6. [Step 5: Step-by-Step Manual End-to-End Walkthrough](#6-step-5-step-by-step-manual-end-to-end-walkthrough)
7. [Step 6: Testing on Real Mobile Phones over Local Wi-Fi](#7-step-6-testing-on-real-mobile-phones-over-local-wi-fi)
8. [Step 7: Running the Database Integrity Audit](#8-step-7-running-the-database-integrity-audit)
9. [Step 8: Offline Troubleshooting & Quick Fixes](#9-step-8-offline-troubleshooting--quick-fixes)

---

## 1. Prerequisites & System Checks

Ensure the following tools are running or installed on your machine:
- **Docker Desktop**: Must be running (powers the local Supabase PostgreSQL database, Auth, and Storage).
- **Supabase CLI**: Local Supabase manager (`supabase`).
- **Python 3.12**: Located in `backend/.venv` (or installed via `uv`).
- **Node.js (v18+) & pnpm**: Frontend package manager (`pnpm`).

### Quick Health Check Command
Open PowerShell in the project root (`c:\Kuldeep510V07\RMS--`):
```powershell
# 1. Verify Docker is running:
docker ps

# 2. Verify Supabase CLI is available:
supabase --version

# 3. Verify pnpm is available:
pnpm --version
```

---

## 2. Step 1: Start Database & Reset to Clean UAT State

Before starting your testing session, ensure your local database is running and freshly initialized with **zero demo transactions** and all 12 workbook users:

### 2.1 Start Local Supabase (if not already running)
```powershell
supabase start
```
*Note: This starts Postgres on port `54322`, GoTrue Auth on `54321`, and local Supabase Studio on `54323`.*

### 2.2 Run the Clean UAT Reset Script
Run the automated reset script from the project root:

```powershell
# Windows PowerShell:
.\scripts\uat-reset.ps1 -Password "Uat@2026RMS!"

# Linux / macOS Bash:
./scripts/uat-reset.sh --password "Uat@2026RMS!"
```

**What this script automatically does:**
1. Resets the database schema and runs all 33 migrations cleanly.
2. Applies the complete workbook reference seed (Option catalogues, System Guards, Roles, Number Series).
3. Purges any leftover demo transactions (Goods Slips, ledger entries, batches, credit notes).
4. Provisions all 12 workbook UAT user accounts in Supabase Auth with the password `Uat@2026RMS!`.

---

## 3. Step 2: Start the Local Application Stack

Launch the entire system using the unified development launcher:

```powershell
# Windows PowerShell:
.\scripts\dev.ps1

# Linux / macOS Bash:
./scripts/dev.sh
```

### What Opens Automatically:
1. **Backend FastAPI API:** `http://localhost:8000`  
   - Interactive Swagger API Docs: [http://localhost:8000/docs](http://localhost:8000/docs)  
   - Health Probe: [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)
2. **Frontend React Application:** `http://localhost:5173`
3. **Local Supabase Studio Dashboard:** `http://127.0.0.1:54323`
4. **Local Inbucket Email Testing Viewer:** `http://localhost:54325` (captures any emails sent by the system without internet access)

---

## 4. Step 3: UAT User Accounts & Credentials

All test accounts use the shared local password: **`Uat@2026RMS!`**

> 💡 **Testing Tip:** To test multiple roles simultaneously without logging out, open separate **Incognito / Private windows** or use different browser profiles (e.g., Profile 1 for Gate Anuj, Profile 2 for Inward Aman, Profile 3 for RM Pratham).

| Persona & Workbook Name | Role Code | Login Email | What to Test with this Account |
|---|---|---|---|
| **RMS Admin** | `SUPER_ADMIN` | `admin@rms.local` | Admin panel, forms, option sets, user administration, locked guards |
| **Anuj** | `GATE_INWARD` | `anuj@rms.local` | Gate Inward, creating Goods Slips, barcode tag printing |
| **Aman** | `INWARD_VERIFIER`<br>`TECHNICIAN_COORDINATOR` | `aman@rms.local` | Unboxing video/photos, itemisation, grading, container audit, tech batches |
| **Pratham Pratap Singh** | `REPLACEMENT_MANAGER` | `pratham@rms.local` | CSR approvals, item actions (Send New/Repaired/CN/BP), Replacement Slip |
| **Sahil** | `INTERMEDIATE_STORE_MANAGER`<br>`TECHNICIAN_COORDINATOR` | `sahil@rms.local` | Custody acceptance, count discrepancies, issue to Main Store |
| **Raj Kumar Ji** | `TECHNICIAN` | `rajkumar@rms.local` | Servicing results, battery replacements, cleaning & repairs |
| **Parts Recovery Tech** | `SPARE_PARTS_TECHNICIAN` | `spt@rms.local` | Dismantling non-good units, PCB model + supplier logging, bins |
| **Spare Parts Manager** | `SPARE_PARTS_MANAGER` | `spm@rms.local` | Non-functional stock, scrap register, hazardous manifest disposal |
| **Deepak Ji** | `ACCOUNTS` | `deepak@rms.local` | Document audit, GST portal check, GST Credit Notes vs General CN vs JV |
| **Dispatch Team** | `DISPATCH` | `dispatch@rms.local` | Replacement dispatch notes (Send New / Send Repaired) |
| **Main Store Manager** | `MAIN_STORE` | `mainstore@rms.local` | Verifying functional stock issues received into Main Store |
| **Management Viewer** | `MANAGEMENT_VIEWER` | `management@rms.local` | Read-only executive reports (R-01…R-18), dashboards, Excel exports |

---

## 5. Step 4: Running the Automated Test Pipeline

You can run the complete automated test suite offline with a single command to prove the codebase is 100% healthy:

```powershell
# Run backend unit tests:
cd backend
.venv\Scripts\python -m pytest -q tests/unit/
cd ..

# Run frontend unit tests:
cd frontend
pnpm test
cd ..

# Run secret scanning (ensures no credentials leaked in bundle):
powershell -File scripts/check-secrets.ps1
```

*Expected Result:*
- Backend Unit Tests: **165 passed**
- Frontend Unit Tests: **151 passed across 21 test suites**
- Secrets check: **OK - no service-role references**

---

## 6. Step 5: Step-by-Step Manual End-to-End Walkthrough

Follow this 7-stage walkthrough to test the complete lifecycle offline:

### Stage 1: Gate Inward (Login: `anuj@rms.local`)
1. Navigate to `http://localhost:5173`. Log in as `anuj@rms.local`.
2. Click **+ New** on the navigation bar.
3. Select Delivery Mode: **COURIER**.
4. Party: Select **Demo Party One (DEMO)**. State and station auto-fill.
5. Enter Courier Name: `SafeXpress`, Docket No: `DX-99214`, Box Count: `2`.
6. Click **Create Goods Slip**. Note the generated number (e.g., `GS/2026-27/00001`).
7. Click **Print Barcode Tags** to verify printable thermal tags render with QR code.

### Stage 2: Unboxing, Itemisation & Grading (Login: `aman@rms.local`)
1. In another browser window, log in as `aman@rms.local`.
2. In **My Work**, click the task for `GS/2026-27/00001` (Unboxing).
3. **Evidence Upload (Guard G-02):**
   - Upload any sample video file (`.mp4` / `.webm`).
   - Upload any document photo (`.jpg` / `.png`) and select tag `INVOICE`.
   - Click **Complete Unboxing** (notice the button was disabled until both were provided).
4. **Itemisation:**
   - Select Product: `DEMO-DMT-001`.
   - Documented Qty: `5`, Received Qty: `5`.
   - Return Nature: **Replacement Only (RO)**.
   - Click **Submit Itemisation**.
5. **Condition Grading (Guard G-07):**
   - Click **Grade Conditions**.
   - Allocate: `OK Packed` = 3, `Dirty` = 1, `Broken Body` = 1.
   - Extraction Quantities: `Packaging` = 3, `Container` = 2 (Sum matches 5).
   - Click **Finalise Grading**.

### Stage 3: RM Action & Replacement Slip (Login: `pratham@rms.local`)
1. Log in as `pratham@rms.local`.
2. Open **RM Item Segregation** for the Goods Slip.
3. Assign actions:
   - For 3 OK Packed pieces $\rightarrow$ select **Issue CN**
   - For 1 Dirty piece $\rightarrow$ select **Send Repaired**
   - For 1 Broken Body piece $\rightarrow$ locked to **Not Allowed** (Guard G-04)
4. Click **Save & Finalise**.
5. Click **Print Replacement Slip** to preview customer authorization slip.

### Stage 4: Handover & Intermediate Store Custody (Login: `sahil@rms.local`)
1. Log in as `sahil@rms.local`.
2. Open **Custody Handover** task.
3. Click **Accept Handover**.
4. The functional and repairable pieces now move into the Intermediate Store ledger.

### Stage 5: Servicing & Exact Battery Deduction (Login: `aman@rms.local` or `sahil@rms.local`)
1. Open **Servicing Workshop** $\rightarrow$ **New Batch Allotment**.
2. Select Technician: **Raj Kumar Ji**, select the 1 dirty piece.
3. Create Allotment Batch.
4. Record Receiving Results:
   - Cleaned & Restored: `1` piece.
   - Battery Replaced: `1` piece (CR2032).
5. Click **Submit Receiving Results**.
6. Check **Battery Stock** page: notice CR2032 inventory decreased by exactly 1 (Guard G-10).

### Stage 6: Commercial Resolution & Credit Note (Login: `deepak@rms.local`)
1. Log in as `deepak@rms.local`.
2. Open **Credit Notes Workspace**.
3. Inspect uploaded invoice photo.
4. Toggle **GST Portal Reflected** = `Yes`.
5. Select **GST Credit Note**. Enter CN No: `CN-2026-001`, Date: today.
6. Verify rate does not exceed invoice ceiling (Guard G-14).
7. Click **Issue Credit Note**.

### Stage 7: Party Notification & Formal Closure (Login: `deepak@rms.local` or `pratham@rms.local`)
1. Open the Goods Slip detail page.
2. Attempt to click **Close GS** (Observe Guard G-15: disabled until prior notification is recorded).
3. Click **Send Party Notification**:
   - Channel: WhatsApp / Email.
   - Preview auto-generated summary. Click **Record Notification Sent**.
4. Click **Close GS**.
5. Status updates to **`RO_CLOSED`**! An immutable Closure Certificate is generated.

---

## 7. Step 6: Testing on Real Mobile Phones over Local Wi-Fi

You can test the actual mobile UI on an iPhone or Android phone connected to the same local Wi-Fi—no cloud deployment required.

### 7.1 Verify Your Computer's Local IP Address
In PowerShell:
```powershell
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch 'vEthernet|Loopback' } | Select-Object IPAddress
```
*(Example IP: `192.168.1.14`)*

### 7.2 Open on Your Mobile Phone
1. Connect your smartphone to the **same Wi-Fi network** as your PC.
2. Open Chrome (Android) or Safari (iPhone) and type:
   ```
   http://192.168.1.14:5173
   ```
3. Log in as **Anuj** (`anuj@rms.local`).
4. **Test Mobile Capabilities:**
   - Bottom navigation bar appears cleanly on mobile screens (<640px).
   - Tap **+ New** to test mobile Gate creation.
   - Test camera upload directly from your phone's camera for unboxing evidence.
   - Verify touch targets are at least 44px for easy thumb tapping.
   - Verify zero horizontal scrolling/overflow on mobile width.

---

## 8. Step 7: Running the Database Integrity Audit

After performing your test transactions, run the mathematical invariant check against PostgreSQL:

```powershell
supabase db query --file scripts/integrity_check.sql
```

### Invariant Rules Verified:
- **IC-01 (Quantity Conservation):** For every line, `Received = Lots + Dismantled + Dispatched + Disposed`.
- **IC-02 (Negative Balance Check):** Zero inventory balances $< 0$.
- **IC-03 (Ledger Balance Parity):** Sum of ledger movements equals current inventory balances.
- **IC-04 (Custody Purity):** Sahil holds only Functional stock; SPM holds only Non-functional/Scrap.
- **IC-05 (Hazard Quarantine):** No mercury lot exists outside `HAZARD_QUARANTINE` or `SCRAP_DISPOSED`.
- **IC-09 (Battery Conservation):** Total batteries consumed equals batteries installed.
- **IC-11 (Closure Completeness):** Every closed Goods Slip has a passing closure snapshot.
- **IC-12 (Zero In-Transit at Closure):** Closed Goods Slips have 0 items in transit or discrepancy.

**Target Result:** All 12 checks report `violations = 0`.

---

## 9. Step 8: Offline Troubleshooting & Quick Fixes

### Problem 1: `Connection refused` on port 54322 or Docker error
- **Cause:** Docker Desktop is not started.
- **Fix:** Open Docker Desktop from the Start Menu, wait until it says "Engine running", then run `supabase start`.

### Problem 2: Port 8000 or 5173 already in use
- **Cause:** A previous test process is still running in the background.
- **Fix:**
  ```powershell
  # Kill process on port 8000:
  Get-NetTCPConnection -LocalPort 8000 | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
  # Kill process on port 5173:
  Get-NetTCPConnection -LocalPort 5173 | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
  ```

### Problem 3: I made test mistakes and want to wipe and restart with a clean slate
- **Fix:** Run the reset script again:
  ```powershell
  .\scripts\uat-reset.ps1 -Password "Uat@2026RMS!"
  ```
  This wipes all test transactions and returns the system to a clean state in under 15 seconds.
