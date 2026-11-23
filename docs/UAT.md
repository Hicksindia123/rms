# RMS User Acceptance Testing (UAT) Guide & Test Protocol

**Document Version:** 1.1.0 (12-step offline flow added 2026-11-23)  
**Status:** Approved for Local Business User Acceptance  
**Reference:** `RMS_DEVELOPMENT_MASTER_PLAN.md` §18 (Scenarios U-01 … U-21) and §20  

---

## 1. Executive Summary & Test Strategy

The User Acceptance Testing (UAT) protocol validates the **Replacement Management System (RMS)** against real-world business workflows, option sets, roles, and System Guards (G-01 … G-18).

Testing is organized into:
1. **Administrative & Platform Controls (U-01 … U-03)**: RBAC, dynamic forms, safe option re-labeling, and immutability of system guards.
2. **Stage 1 — Gate & Inward Operations (U-04 … U-09)**: Physical receipt, unboxing video/photo evidence, itemisation, shortage logging, CSR/RO segregation, 3-category grading, daily container audit.
3. **Stage 2 — Segregation & Custody Handover (U-10 … U-11)**: RM actions, Replacement Slip generation, physical handover, count mismatch / discrepancy reconciliation.
4. **Stage 3 — Servicing & Battery Management (U-12)**: Allotment to technician (Raj Kumar Ji), exact battery deduction, cleaning/scratch classification.
5. **Stage 4 — Dismantling & Parts Recovery (U-13 … U-14)**: Recovery into TIP/BODY/WIRE/PCB, mandatory PCB metadata (G-11), partitioned storage, hazardous scrap disposal with manifests.
6. **Stage 5 — Functional Issue to Main Store (U-15)**: Inter-store transfer of Good & Repaired stock to Main Store.
7. **Stage 6 — Commercial Resolution & Credit Notes (U-16 … U-17)**: RM CN decision, Accounts GST portal verification, GST vs General vs JV Credit Notes, historical rate validation.
8. **Stage 7 — Party Notification & Closure (U-18)**: Pre-closure party communications (G-15) and stage closure snapshots.
9. **MIS, Reporting & Auditing (U-19 … U-20)**: Reports R-01 … R-18, dashboards, export validation, activity timeline.
10. **Mobile & Cross-Device LAN Verification (U-21)**: Android Chrome & iPhone Safari on local network.
11. **End-to-End Lifecycle Scenarios (L-01 … L-10)**: integrated end-to-end multi-role scenarios with invariant check.
12. **12-step Offline Return → Replacement (O-01 … O-14, §4.2)**: the current flow (Intermediate Stores OP / DT / RI, Management approval, per-GS Accounts entry).

---

## 2. Environment Setup & Execution Instructions

### 2.1 Fresh Reset Procedure
Before each UAT cycle or tester transition, reset the local environment to a baseline state with **zero demo transactions**:

```powershell
# Windows PowerShell:
.\scripts\uat-reset.ps1 -Password "Uat@2026RMS!"

# Linux / macOS Bash:
./scripts/uat-reset.sh --password "Uat@2026RMS!"
```

To import real customer and product masters from business CSV files:
```powershell
.\scripts\uat-reset.ps1 -ProductsCsv "C:\path\to\products.csv" -PartiesCsv "C:\path\to\parties.csv" -CleanDemoMasters
```

### 2.2 Starting the Application Stack
```powershell
.\scripts\dev.ps1
```
- **Backend API:** `http://localhost:8000` (Swagger UI: `http://localhost:8000/docs`)
- **Frontend SPA:** `http://localhost:5173`
- **Supabase Local Studio:** `http://127.0.0.1:54323`

### 2.3 UAT User Accounts (Pre-configured)
All accounts share the default password: **`Uat@2026RMS!`** (or as supplied via out-of-band secret).

| Department | Role Code | Workbook Personnel | Login Email | Notes |
|---|---|---|---|---|
| Administration | `SUPER_ADMIN` | RMS Admin | `admin@rms.local` | Full system governance |
| Gate / Security | `GATE_INWARD` | Anuj | `anuj@rms.local` | Mobile tablet/phone (📱) |
| Replacement Dept | `INWARD_VERIFIER` | Aman | `aman@rms.local` | Unboxing & grading (📱) |
| Replacement Dept | `REPLACEMENT_MANAGER` | Pratham Pratap Singh | `pratham@rms.local` | Approvals & resolution |
| Intermediate Store | `INTERMEDIATE_STORE_MANAGER` | Sahil | `sahil@rms.local` | Custody & Main Store issue |
| Servicing | `TECHNICIAN_COORDINATOR` | Aman / Sahil | `aman@rms.local` / `sahil@rms.local` | Allotment & batch results |
| Servicing | `TECHNICIAN` | Raj Kumar Ji | `rajkumar@rms.local` | Repairs & testing |
| Parts Recovery | `SPARE_PARTS_TECHNICIAN` | Parts Recovery Tech | `spt@rms.local` | Dismantling & PCB logging |
| Parts Recovery | `SPARE_PARTS_MANAGER` | Spare Parts Manager | `spm@rms.local` | Scrap & hazardous register |
| Accounts | `ACCOUNTS` | Deepak Ji | `deepak@rms.local` | Tax portal, CNs & JVs |
| Logistics | `DISPATCH` | Dispatch Team | `dispatch@rms.local` | Replacement dispatches |
| Main Store | `MAIN_STORE` | Main Store Manager | `mainstore@rms.local` | Stock receipt verification |
| Executive | `MANAGEMENT_VIEWER` | Management | `management@rms.local` | Read-only reports & MIS |
| Management | `MANAGEMENT` | Management approver | `mgmt@rms.local` | Edit requests, approval + stamp, Issue CN |
| Intermediate Store OP | `ISTORE_OP` | OP store user | `opstore@rms.local` | Steps 3–8 for OP (📱) |
| Intermediate Store DT | `ISTORE_DT` | DT store user | `dtstore@rms.local` | Steps 3–8 for DT (📱) |
| Intermediate Store RI | `ISTORE_RI` | RI store user | `ristore@rms.local` | Steps 3–8 for RI (📱) |

---

## 3. Role-Based UAT Test Protocols (U-01 … U-21)

Legend: 📱 = Test primarily on mobile browser (viewport 360–390px) or phone over LAN.

| # | Role / Persona | Test Scenario & Step Instructions | Expected Business Result | Data to Use | Status |
|---|---|---|---|---|:---:|
| **U-01** | Super Admin (`admin@rms.local`) | **User Lifecycle & Multi-role Management**<br>1. Log in to Admin Panel → Users.<br>2. Create a new user with email `test.tech@rms.local` and role `TECHNICIAN`.<br>3. Edit Aman (`aman@rms.local`) and ensure both `INWARD_VERIFIER` and `TECHNICIAN_COORDINATOR` are assigned.<br>4. Deactivate `test.tech@rms.local` and attempt immediate login.<br>5. Reactivate user. | 1. User created successfully.<br>2. Aman can access both Inward tasks and Servicing Allotment.<br>3. Deactivated user is immediately locked out (`403 ACCOUNT_INACTIVE`).<br>4. Reactivated user logs in normally. | Email: `test.tech@rms.local`<br>Password: `Uat@2026RMS!` | **PASS** |
| **U-02** | Super Admin (`admin@rms.local`) | **Dynamic Form & Option Safety (G-18)**<br>1. Go to Admin → Option Sets → `DMT_CONDITION`.<br>2. Relabel option "DIRTY" to "DIRTY / SURFACE SOIL".<br>3. Open Form Builder → `S1_INSPECT_DMT` → publish new version.<br>4. Open an existing in-flight GS and inspect label.<br>5. Create a new GS and inspect dropdown options. | 1. Existing GS preserves original pinned option label version (G-18).<br>2. Newly created GS renders the updated label.<br>3. No historical data corruption. | Option set: `DMT_CONDITION`<br>Form: `S1_INSPECT_DMT` | **PASS** |
| **U-03** | Super Admin (`admin@rms.local`) | **Immutability of Locked System Guards (G-05)**<br>1. Navigate to Admin → Option Sets → Prismatic conditions.<br>2. Attempt to toggle "BROKEN WITH MERCURY" from disallowed to allowed.<br>3. Admin → System Guards view.<br>4. Attempt to delete or disable Guard G-05 via UI or API. | 1. Toggling hazard condition rejected with validation error explaining hazardous material constraint.<br>2. Guard deletion blocked with `422 SYSTEM_GUARD_LOCKED` (G-05). | Prismatic condition: `PRS_COND_BROKEN_HG` | **PASS** |
| **U-04** | Gate Inward (Anuj 📱) | **Goods Slip Generation Across Delivery Modes**<br>1. Create GS with Delivery Mode = COURIER (Docket No, Courier Name).<br>2. Create GS with Delivery Mode = DIRECT_TRUCK (Vehicle No, Driver Phone).<br>3. Create GS with Delivery Mode = SELF_DELIVERY.<br>4. Create GS with "No Document Attached" flagged.<br>5. Generate and print GS barcode tags. | 1. Dynamic fields toggle accurately per delivery mode.<br>2. System generates sequential number in configured pattern `GS/2026-27/0000X`.<br>3. "No Document" triggers amber warning badge on GS card.<br>4. Tag prints cleanly with QR code. | Transporter: SafeX Courier<br>Party: Demo Party One<br>Boxes: 3 | **PASS** |
| **U-05** | Inward Verifier (Aman 📱) | **Unboxing Evidence Capture (G-02)**<br>1. Open GS assigned to Inward queue.<br>2. Attempt to complete unboxing without video/photos.<br>3. Upload unboxing video file.<br>4. Upload photos of party documents and classify as `INVOICE`, `DEBIT_NOTE`, `CHALLAN`, `SLIP`.<br>5. Click "Complete Unboxing". | 1. "Complete Unboxing" button is strictly disabled or returns `422 EVIDENCE_MISSING` (G-02).<br>2. Upload displays progress bar and thumbnail previews.<br>3. Completion triggers real-time notification to Accounts (`deepak@rms.local`). | Test video (MP4/WebM)<br>Document photos (JPEG/PNG) | **PASS** |
| **U-06** | Inward Verifier (Aman 📱) | **Itemisation & Document Shortage Logging**<br>1. Open GS Step-2 (Itemisation).<br>2. Add product line: Documented Qty = 10, Received Qty = 8.<br>3. Categorise consignment as Replacement Only (RO).<br>4. Submit itemisation. | 1. Line displays prominent "Short 2" indicator.<br>2. Physical stock ledger logs exactly 8 received units.<br>3. Inspection task created for exactly 8 units. | Product: `DEMO-DMT-001`<br>Doc Qty: 10, Rec Qty: 8 | **PASS** |
| **U-07** | Inward Verifier & RM (Aman & Pratham 📱) | **Complete Sales Return (CSR) Approval Flow (G-03)**<br>1. Aman flags GS-01 as Complete Sales Return (CSR).<br>2. Aman flags GS-02 as CSR.<br>3. Pratham logs in, opens Approvals dashboard.<br>4. Pratham approves GS-01 with remarks.<br>5. Pratham rejects GS-02 with remarks. | 1. GS-01 advances directly to Intermediate Store with "With Packaging" custody transfer initiated (bypasses item-wise grading).<br>2. GS-02 reverts to Replacement Only (RO) and routes to Aman's inspection queue. | GS-01: 5 units DMT<br>GS-02: 4 units Prismatic | **PASS** |
| **U-08** | Inward Verifier (Aman 📱) | **Condition Grading & Extraction Reconciliation (G-06, G-07)**<br>1. DMT line (10 pcs): distribute across 8 conditions (OK 4, Dirty 2, Display Issue 2, Other Brands 1, Body Damage 1).<br>2. Prismatic (3 pcs): OK 2, Mercury Broken 1.<br>3. Enclosed Oval (4 pcs): attempt grading before ticking "Full Opening Completed". Then tick and grade.<br>4. Enter extraction quantities (packaging vs container).<br>5. Test extraction sum mismatch vs received sum. | 1. EO grading is strictly locked until full opening confirmed (G-06).<br>2. Mercury piece triggers Red Hazard banner and moves to `HAZARD_QUARANTINE`.<br>3. Non-reconciled extraction quantities block submission with `422 EXTRACTION_MISMATCH` (G-07).<br>4. When reconciled, finalisation succeeds. | DMT (10 pcs)<br>PRS (3 pcs)<br>EO (4 pcs) | **PASS** |
| **U-09** | Inward Verifier (Aman 📱) | **Daily DMT Container Register & Compliance**<br>1. Navigate to Daily Container Register.<br>2. Record count for all containers (BIN-01 … BIN-04).<br>3. Confirm count with confirmation checkbox.<br>4. Simulate missed audit day. | 1. Submission requires confirmation checkbox checked.<br>2. Ledger updates container balances.<br>3. Missed day renders in Red "MISSED" status on Compliance Calendar. | DMT Containers: 4 bins | **PASS** |
| **U-10** | Replacement Manager (Pratham 📱) | **Item-wise Segregation & Pending (BP) (G-08)**<br>1. Open RM Segregation view for graded GS.<br>2. Assign actions: Send New (2), Send Repaired (2), Issue CN (4), Pending BP (2). Reason entered for Pending.<br>3. Save and generate Replacement Slip.<br>4. Attempt to transfer pending pieces to store.<br>5. Clear pending piece in Pendency Register (resolution: Send New). | 1. Pending pieces locked from transfer (G-08).<br>2. Replacement Slip prints with barcode & breakdown.<br>3. Clearing pendency generates Revision 2 with audit trail. | GS items (10 pcs total) | **PASS** |
| **U-11** | Inward Verifier & Sahil (Aman ↔ Sahil 📱) | **Custody Transfer & Discrepancy Reconciliation (G-09)**<br>1. Aman initiates custody transfer of 6 units to Intermediate Store.<br>2. Sahil counts physical delivery and finds 5 units.<br>3. Sahil reports count mismatch (discrepancy).<br>4. Both parties review Discrepancy Resolution dialog and sign "Accept Counted (5), Return Difference (1)".<br>5. Sahil accepts 5 units into store. | 1. Transfer freezes during discrepancy state (nothing credited to store).<br>2. Closure checklist shows open discrepancy blocking closure.<br>3. Mutual resolution credits 5 units to Intermediate Store and returns 1 unit to Aman's staging.<br>4. Full audit trail recorded. | Dispatched: 6<br>Received: 5<br>Discrepancy: -1 | **PASS** |
| **U-12** | Tech Coordinator & Tech (Aman/Sahil & Raj Kumar Ji 📱) | **Batch Allotment & Servicing Results (G-10)**<br>1. Aman allots batch of 4 units to Raj Kumar Ji.<br>2. Check initial battery stock in `BATTERY_STORE`.<br>3. Raj Kumar Ji records servicing: 2 units cleaned + batteries replaced, 1 unit permanent scratch, 1 unit non-repairable.<br>4. Submit receiving results. | 1. Allotment batch series generated (`TECH/2026-27/0000X`).<br>2. Battery store balance decreases by exactly 2 (G-10).<br>3. Units classified into: 2 Functional Repaired, 1 Non-Sellable (Scratched), 1 Non-Good. | Batch: 4 units<br>Battery Type: CR2032 | **PASS** |
| **U-13** | Spare Parts Tech (`spt@rms.local` 📱) | **Parts Recovery & Mandatory PCB Metadata (G-11)**<br>1. Open Dismantling Queue.<br>2. Select 2 non-good units for dismantling.<br>3. Enter recovered parts: TIP (2), BODY (2), WIRE (2), PCB (2).<br>4. Attempt submit without PCB model or supplier.<br>5. Enter PCB Model: `PCB-V3-REV2`, Supplier: `MicroTech Ltd`. Select partitioned bin `PART-BIN-A2`. | 1. Missing PCB model or supplier is blocked with `422 PCB_METADATA_MANDATORY` (G-11).<br>2. After entering metadata, batch completes with batch series `DMTL/2026-27/0000X`.<br>3. Recovered parts become independent spare-parts inventory lots. | Inputs: 2 Non-Good<br>Storage: Partitioned | **PASS** |
| **U-14** | Spare Parts Manager (`spm@rms.local`) | **Non-Functional Stock Custody & Scrap Manifest (DEC-11)**<br>1. Navigate to Spare Parts Inventory.<br>2. Verify exclusive custody of non-functional, scratched, and mercury scrap.<br>3. Open Scrap Register → Stock Awaiting Disposal.<br>4. Mark mercury unit for disposal.<br>5. Enter authorized Hazardous Waste Manifest No: `HAZ-2026-9812` and contractor details. Submit. | 1. Functional store managers cannot access scrap items.<br>2. Disposal without manifest number is rejected.<br>3. Disposed unit moves to `SCRAP_DISPOSED` ledger location.<br>4. Manifest reference attached to GS closure audit. | Lot: Mercury broken unit<br>Manifest: `HAZ-2026-9812` | **PASS** |
| **U-15** | Intermediate Store (Sahil) | **Issue Functional Stock to Main Store**<br>1. Filter inventory by Functional Good and Functional Repaired.<br>2. Select 5 units of Functional Good.<br>3. Create Store Issue with Issue Type = `ISSUE_MAIN_STORE`.<br>4. Generate and print Store Issue Note. | 1. Store Issue voucher generated (`ISS/2026-27/0000X`).<br>2. Stock moves from `INTERMEDIATE_STORE` to `MAIN_STORE`.<br>3. Main Store manager verifies incoming voucher and balance increments. | Qty: 5 units `DEMO-DMT-001` | **PASS** |
| **U-16** | Replacement Manager (Pratham) | **Final Credit Note Decision (DEC-13)**<br>1. Open Resolution Board for serviced GS.<br>2. Compare planned RM action vs actual servicing outcomes.<br>3. Record CN Decision: 3 lines `ALLOW_CN`, 1 line `DENY_CN_SEND_REPLACEMENT`.<br>4. Enter deviation reason for any divergence from initial plan. | 1. `ALLOW_CN` lines route to Accounts work queue with notification.<br>2. `DENY_CN` line routes to Dispatch queue for replacement dispatch.<br>3. Deviation reasons logged to GS activity timeline. | GS with 4 lines | **PASS** |
| **U-17** | Accounts (Deepak Ji) | **Compliance Credit Notes & Valuation (G-13, G-14)**<br>1. Open Accounts CN Workspace.<br>2. Verify uploaded party invoice and debit note.<br>3. Line 1: Check GST portal = "Reflected". Select GST Credit Note. Check rate against historical invoice.<br>4. Line 2: Repaired unit. Select General Credit Note.<br>5. Line 3: Check GST portal = "Not Reflected". Attempt GST CN.<br>6. Select Journal Voucher (JV) for Line 3.<br>7. Submit Credit Notes. | 1. GST CN allowed only when portal reflected (G-13).<br>2. Non-reflected line rejects GST CN and mandates JV.<br>3. Repaired item mandates General CN.<br>4. Rate check enforces historical rate ceiling (G-14).<br>5. CN numbers generated and recorded. | 3 GS lines<br>Invoice rates verified | **PASS** |
| **U-18** | Accounts & RM (Deepak & Pratham) | **Prior Party Notification & GS Closure (G-15)**<br>1. Attempt to Close GS before sending party notification.<br>2. Open Party Notification dialog.<br>3. Review auto-generated message with CN and dispatch references.<br>4. Record notification sent (Email/WhatsApp) with communication proof upload.<br>5. Return to GS Detail and click "Close GS".<br>6. For CSR GS: execute CSR Closure. | 1. Premature closure is blocked with `422 G-15: PRIOR_NOTIFICATION_REQUIRED`.<br>2. Notification logged with sender, recipient, timestamp, and proof attachment.<br>3. GS successfully closes with status `RO_CLOSED` or `CSR_CLOSED`.<br>4. Immutable closure checklist snapshot recorded. | Closed GS record | **PASS** |
| **U-19** | Management Viewer (`management@rms.local`) | **MIS Dashboards, Reports & Excel Export**<br>1. Open Management Dashboard.<br>2. Verify widget counts match underlying list screens.<br>3. Open Reports R-01 through R-18 (Turnaround Time, Defect Pareto, Scrap Register, Battery Consumption).<br>4. Export R-01 and R-04 to Excel (`.xlsx`).<br>5. Inspect downloaded Excel files for formatting and formula security. | 1. Widget KPIs reflect live database figures with zero discrepancy.<br>2. All 18 reports render with server-side pagination and filters.<br>3. Excel exports open cleanly without corruption or formula injection warnings (`=`, `+`, `-` escaped). | Reports R-01 … R-18 | **PASS** |
| **U-20** | Any Authenticated User | **Global Search, Audit Explorer & GS Activity Timeline (G-17)**<br>1. Use Global Search header (`/search?q=...`) to query by GS number, party GSTIN, docket number, CN number, and container barcode.<br>2. Open GS Activity Timeline.<br>3. Inspect chronological sequence of every status change, handover, allotment, and print log.<br>4. Filter Audit Explorer by entity and user. | 1. Search returns instant categorized results with deep-link navigation.<br>2. Activity timeline provides an unalterable narrative of every actor, action, and timestamp (G-17).<br>3. Audit Explorer confirms append-only integrity. | Search terms: `GS/2026-27/00001`, `09AAACH7409R1ZZ` | **PASS** |
| **U-21** | All Mobile Roles (Anuj, Aman, Sahil, Pratham 📱) | **Real Device & LAN Cross-Platform Smoke Test**<br>1. Connect Android phone (Chrome) and iPhone (Safari) to same local Wi-Fi.<br>2. Open `http://<LAN_IP>:5173`.<br>3. Log in as Anuj: create GS, test camera capture.<br>4. Log in as Aman: review unboxing, test grading sliders.<br>5. Verify: bottom navigation bar visibility, minimum 44px touch targets, zero horizontal scrollbar on 360px/390px screens. | 1. Application is 100% responsive on both mobile operating systems.<br>2. Touch targets easy to tap without zoom.<br>3. Camera capture works seamlessly.<br>4. Zero layout shifts or horizontal clipping. | Device: Pixel 7 (Android 14)<br>Device: iPhone 14 (iOS 17) | **PASS** |

---

## 4. End-to-End Lifecycle Scenarios (L-01 … L-08)

These scenarios represent comprehensive multi-role business journeys. After each scenario run, `scripts/integrity_check.sql` must confirm `violations = 0` across all 12 system invariants (IC-01 … IC-12).

| Scenario | Journey Description | Key Invariants & Safeguards Tested | Expected Outcome | Status |
|---|---|---|---|:---:|
| **L-01** | **Standard RO Lifecycle: 10 DMT units**<br>Anuj (Gate) → Aman (Inward: OK 3, Dirty 2, Scratched 2, Display 2, Broken 1) → Pratham (RM: Issue CN 9, Not Allowed 1) → Sahil (Handover) → Technician (2 Cleaned + Battery Replaced, 1 Scratched, 1 Non-Good) → Parts Recovery (Dismantle 2 Non-Good with PCB metadata) → Pratham (Revision 2: Issue CN 5, Not Allowed 5) → Deepak (GST CN for 5) → Party Notification → Closure. | Exact battery deduction (G-10), PCB metadata (G-11), quantity conservation (IC-01), zero stock in transit at closure (IC-12). | Status: `RO_CLOSED`<br>Violations: 0 | **PASS** |
| **L-02** | **Servicing & General CN for Repaired Units**<br>RO of 4 display issue units → RM: Issue CN → Technician: all 4 repaired → Functional Repaired → Main Store → Deepak: General CN (BR-35) → Notification → Closure. | Repaired stock issuance, General CN compliance rules. | Status: `RO_CLOSED`<br>Violations: 0 | **PASS** |
| **L-03** | **Unreflected GST Portal → JV Enforced**<br>RO of 3 OK units → RM: Issue CN → Sahil → Deepak: GST portal unreflected → System blocks GST CN (G-13) and mandates Journal Voucher → Party Notification → Closure. | GST compliance guard (G-13). | Status: `RO_CLOSED` (JV Issued)<br>Violations: 0 | **PASS** |
| **L-04** | **Replacement Dispatch Flow (No CN)**<br>RO of 3 display issue units → RM: Send Repaired → Technician repairs → RM: Deny CN, Send Replacement → Dispatch Team issues replacement slip & dispatches → Closure. | Replacement dispatch link, no party notification required when 100% replaced. | Status: `RO_CLOSED`<br>Violations: 0 | **PASS** |
| **L-05** | **Complete Sales Return (CSR) Happy Path**<br>4 units categorized as CSR → Pratham approves CSR → Handover "With Packaging" → Sahil records packaging verification → Technician quick test → Main Store → RM confirms all lines → Deepak: GST CN → Notification → Closure. | CSR workflow (G-03), packaging verification, closure reason "Inward to Inventory with Packaging + CN Issued + Prior Party Info". | Status: `CSR_CLOSED`<br>Violations: 0 | **PASS** |
| **L-06** | **Handover Count Mismatch & Discrepancy Resolution**<br>Aman hands over 6 units; Sahil counts 5. Sahil logs discrepancy. Handover halted. Aman & Sahil negotiate and sign resolution ("Accept 5, Return 1"). Staged return processed. Flow continues to dispatch and closure. | Handover discrepancy lock (G-09), physical/digital custody synchronicity. | Status: `RO_CLOSED`<br>Violations: 0 | **PASS** |
| **L-07** | **Hazardous Waste Quarantine & Manifest Disposal**<br>Prismatic consignment: 2 OK, 1 Broken with Mercury. Mercury unit automatically routed to `HAZARD_QUARANTINE`. RM cannot issue to store. SPM marks for disposal and disposes with Manifest `HAZ-2026-9812`. Flow closes. | Hazard isolation (G-05), mandatory scrap manifest (DEC-11). | Status: `RO_CLOSED`<br>Violations: 0 | **PASS** |
| **L-08** | **Blocked Closure via Pending (BP) Clearance**<br>RM marks 1 of 4 units as Pending (BP). Other 3 processed. Premature closure attempted and rejected by system. RM resolves pendency to Send New. Cleared piece dispatched. Closure re-attempted and succeeds. | Closure blocking on open pendency (G-08, G-15). | Status: `RO_CLOSED`<br>Violations: 0 | **PASS** |
| **L-09** | **Full Offline Return Flow (Change Plan 2026-11-12)**<br>Anuj (Offline return, backdated gate entry date & numeric entry no., Courier Slip + Invoice docs) → Immediate Accounts alert (AMD-05) → Aman (Carton opening with video per carton G-02 + carton Debit Note) → Counting (10 pcs) → Categorisation (6 DMT_OK_PACKED, 4 DMT_BROKEN_BODY + packaging/container counts G-19) → Pratham (RM review & approve, auto Transfer Slip AMD-13) → Sahil (Accept store transfer → `HELD_AT_INTERMEDIATE_STORE`) → Pratham & Aman (Department round-trip: dispatch 4 to REPAIR, receive 3 REPAIRED + 1 WASTAGE, G-20 conservation verified: 10 counted = 6 in-store + 4 outcomes) → Pratham (RM final actions split: 5 Send New, 3 Send Repaired, 2 Issue CN, G-21) → Deepak (Accounts entry per line flags, G-22) → Dispatch Team (Numbered Dispatch Slip PDF, issue goods via `rms_move_stock`). | AMD-01..AMD-19, G-02, G-19, G-20, G-21, G-22. Real local stack, desktop & mobile (360px). | Status: `DISPATCHED`<br>Violations: 0 | **PASS** |
| **L-10** | **E-Commerce Return Path (Change Plan 2026-11-12)**<br>Gate entry with return type `ECOMMERCE_RETURN` (no gate entry date or gate entry number, DEC-39) → Carton opening with video → Counting (5 pcs) → Categorisation (5 DMT_BROKEN_BODY) → RM approve → Sahil accept store transfer → RM final actions (5 Issue CN) → Accounts entry (CN issued, no goods to ship) → Closure. | DEC-39, AMD-01, AMD-16..AMD-18, G-19, G-21, G-22. Non-shipping return resolution. | Status: `AWAITING_NOTIFICATION` / `CLOSED`<br>Violations: 0 | **PASS** |

### 4.1 System Guards Rejection Test Matrix (Change Plan 2026-11-12)

Every system guard introduced or updated in the 2026-11-12 Change Plan has automated rejecting tests in `frontend/tests/e2e/phase11_new_flow.spec.ts`:

| Guard | Rule & Requirement | Rejecting Test Scenario | HTTP Status & Error Code | Test Result |
|---|---|---|:---:|:---:|
| **G-02 (updated)** | Video is strictly mandatory for every individual carton (`carton_count`); unboxing cannot complete until video count = carton count. | Consignment with 2 cartons: 1 video uploaded, unboxing complete attempted. | `422 VALIDATION_FAILED` (`VIDEO_PER_CARTON`) | **PASS (Rejected)** |
| **G-19** | Item-level categorisation bucket quantities must exactly conserve counted qty: `sum(bucket_qty) = received_qty`. | Counted = 10 pcs; submission attempted with 8 pcs (6 + 2). | `422 VALIDATION_FAILED` / `409 CONFLICT` | **PASS (Rejected)** |
| **G-20** | Department routing dispatch cannot exceed in-store available quantity for the item. | In-store = 10 pcs; dispatch attempted for 15 pcs to REPAIR. | `422 VALIDATION_FAILED` / `409 CONFLICT` | **PASS (Rejected)** |
| **G-21** | RM final action split quantities must equal available quantity; finalised slips are frozen and immutable without formal revision. | Available = 10 pcs; final action attempted with 7 pcs. Direct editing of finalised slip attempted without revision. | `422 VALIDATION_FAILED` / `409 CONFLICT` | **PASS (Rejected)** |
| **G-22** | Accounts entry rules: no challan fields on CN actions; no future dates; no early completion with missing fields; frozen on complete; no double dispatch. | 1. Challan fields on `ISSUE_CN`.<br>2. Future date (`2099-01-01`).<br>3. Early complete with missing challan line.<br>4. Edit lines after completion.<br>5. Second dispatch on already-dispatched slip. | `422 VALIDATION_FAILED` / `409 CONFLICT` | **PASS (Rejected)** |

### 4.2 12-step Offline Return → Replacement (UAT script for the business, 2026-11-23)

The flow of `docs/RMS_PHASE_PROMPTS_20-11-2026.md` §1 (DEC-60 … DEC-72). L-09 / L-10 above describe the
earlier flow (RM review, RM final actions) and stay valid only for goods slips created before it.
Run each case on a phone (360–390 px) **and** a desktop. Fill in **Status** (PASS / FAIL + defect id)
and **Tester**. The automated run of the same journey is `frontend/tests/e2e/offline_replacement_flow.spec.ts`
(PASS at 1280 px and 360 px on 2026-11-23, zero console errors).

**Test data.** Three goods slips: **A** with one DMT (→ DT), one Enclosed Oval (→ OP) and one product
of a category mapped to RI; **B** with DMT + Enclosed Oval; **C** with an RI product only.
⚠️ With today's masters, GENERAL products have no condition fields and cannot pass the categorisation
lock, so nothing reaches RI (open question Q43). Until it is answered, map one category to RI for the
test (Administration → Intermediate Stores) and map it back afterwards.

| # | Who (login) | Steps | Expected result | Status | Tester |
|---|---|---|---|---|---|
| **O-01** | Gate User (`anuj@rms.local` 📱) | Gate Entry: Offline, gate entry date + no., State → Station → Party, Cartons 2, Received Through Courier (name + docket), Documents From Party = No Documents → **Submit & Create GS** → check the summary → **Back to edit** → **Submit & Create GS** → **Submit** → **Print GS Tag**. | Nothing is created before the summary's Submit. GS number shown; tag prints 2 labels. Gate entry no. used twice in the FY is refused. | | |
| **O-02** | Replacement Executive (`aman@rms.local` 📱) | Carton Opening → Start → video for carton 1 only → try **Next** → video for carton 2 → optional carton document (Hand Written Slip + photo) → **Next**. | Next stays disabled with one video ("carton 2 missing"). The carton document clears "No Documents From Party". Next opens the item screen. | | |
| **O-03** | Replacement Executive 📱 | Add 3 lines (DT, OP, RI products) with as-per-document and physical qty → **Next** → **Replacement** → split each line by condition → try **Lock** with one line not adding up → fix → **Lock**. | Lock disabled until every line adds up (G-19). After the lock the lines are read-only and the GS is "Pending Transfer Slip". | | |
| **O-04** | Replacement Executive 📱 | New GS with one line → **Next** → **Complete Sales Return**. | GS shows "Sales Return – On Hold"; it never appears in the RM's pending list. | | |
| **O-05** | Replacement Manager (`pratham@rms.local`) | Transfer Slips → select A, B, C → **Generate Transfer Slip** → confirm → open each slip → **Download PDF**. | 3 slips, one per store: OP (A + B), DT (A + B), RI (A + C). PDF has the HICKS logo, lines per GS and condition, totals. | | |
| **O-06** | RM → Management (`mgmt@rms.local`) → RM | New locked GS → **Send Edit Request** (reason) → Management: Edit Requests → **Change line** (reason) → **Mark as edited** → RM generates → Management changes the GS again. | GS cannot be selected while the request is open. The second change voids the slip; the GS is back in the RM's pending list; regenerating gives a new slip. | | |
| **O-07** | Store users (`opstore@`, `dtstore@`, `ristore@rms.local` 📱) | Each: Acknowledge Transfer Slips → open own slip (try "Show other items") → **Report discrepancy** on one → **Acknowledge receipt** → **Confirm receipt**. | Each store sees only its own slip. Discrepancy alerts the RM + Management. After acknowledgement the goods are in that store's location. | | |
| **O-08** | Each store user 📱 | Department Routing → open A (own item only) → send pieces to a work department → **Save routing** → **Save & issue** → print the DIN. Save an "Issue to Store" line on B and **Undo** it (reason). | Routing starts right after the store's own acknowledgement. DIN prints with the store as source. Undo returns the pieces to routing. | | |
| **O-09** | Each store user 📱 | Receive from Departments → **Receive** 1 pc (partial) → receive the rest; on one line choose **Return for Re-routing** and route it again. | Partial receipt keeps the DIN open. Re-routing puts the pieces back in Department Routing. When all is back the GS is ready for analysis. | | |
| **O-10** | Each store user 📱 | Analysis: A — DT **Dispatch New**, OP **Dispatch Repaired**, RI **Not Allowed**, the last store ticks **Also send for Management approval** (reason); B — Dispatch New / Dispatch Repaired; C — Not Allowed. | No "Issue CN" for stores. A waits for Management; B goes to Accounts; C becomes "On Hold – Not Allowed" (Accounts → On hold tab). | | |
| **O-11** | Management 📱 | Management Approval → A → change DT's line to **Issue CN** (reason) → **Save changes** → **Approve** → **Verify** → open the GS page. | Stamp "Digitally approved by Management" with name, time and reference; Verify says Valid; GS goes to Accounts. | | |
| **O-12** | Accounts (`deepak@rms.local`) | Accounts Entry → B: Challan No. + Date only → Save → Complete. A: Challan + CN No. + Date + Value → Save → Complete. Try a future date and a duplicate CN no. | B shows no CN fields. Future date and duplicate CN refused. Completing generates the Dispatch Slip; GS "Pending Dispatch". Replacement Slip PDF shows the stamp on A. | | |
| **O-13** | Dispatch (`dispatch@rms.local`) | Dispatch → open A's and B's slips → dispatch (date, transporter, docket). | Slips list Challan / CN and stamp; stock moves per decision (old piece of Dispatch New → Non-Functional Store, Not Allowed → Rejected Hold). | | |
| **O-14** | Every role 📱 | Sign in as each role and open My Work. | Menus match `docs/USER_GUIDE.md` §1.3; counts match the lists; store users see only their store's work; no retired menu (RM Review, Final Actions, Approvals, Inspection, Store Acceptance, Department Issue / Receiving) is shown. | | |

---

## 5. Post-Session Data Integrity Verification

At the conclusion of each UAT testing batch, execute the formal database integrity validator:

```powershell
# Using Supabase CLI:
supabase db query --file scripts/integrity_check.sql
```

### Invariant Verification Checklist:
- **IC-01: Quantity Conservation:** For every GS line, `received_qty = active_lots + dismantled + dispatched + disposed`. (Violations: **0**)
- **IC-02: Negative Balance Check:** No inventory balance in any location is `< 0`. (Violations: **0**)
- **IC-03: Ledger vs Balance Parity:** `sum(stock_ledger) = inventory_balances`. (Violations: **0**)
- **IC-04: Custody Boundary:** Sahil holds only Functional stock; SPM holds only Non-functional/Scrap. (Violations: **0**)
- **IC-05: Hazardous Isolation:** No mercury lot exists outside `HAZARD_QUARANTINE` or `SCRAP_DISPOSED`. (Violations: **0**)
- **IC-06: Disposed Units:** All units in `SCRAP_DISPOSED` have a logged manifest reference. (Violations: **0**)
- **IC-07: Closed GS Immutability:** Closed Goods Slips have no pending tasks or active drafts. (Violations: **0**)
- **IC-08: Dispatch Conservation:** Dispatched quantities match replacement approvals. (Violations: **0**)
- **IC-09: Battery Stock Conservation:** `sum(BATTERY_CONSUMED) = sum(batteries_installed)`. (Violations: **0**)
- **IC-10: Functional Locations Purity:** Locations `INTERMEDIATE_STORE` and `MAIN_STORE` contain zero non-good units. (Violations: **0**)
- **IC-11: Closure Checklist Completeness:** Every closed GS has an immutable passing snapshot. (Violations: **0**)
- **IC-12: Zero In-Transit at Closure:** Closed Goods Slips have zero units in transit or discrepancy. (Violations: **0**)

---

## 6. Defect Log Template & Registered Issue Records

### 6.1 Defect Logging Template

```markdown
### DEF-XXXX: [Short Summary of Defect]
- **Date Reported:** YYYY-MM-DD
- **Reported By:** [Name & Role]
- **Tested Scenario:** [e.g., U-08 or L-01]
- **Severity:** [Blocker | Critical | High | Medium | Low]
- **Steps to Reproduce:**
  1. ...
  2. ...
- **Expected Behavior:** [What should happen]
- **Actual Behavior:** [What actually happened + Error message]
- **Screenshot / Evidence Reference:** `docs/screenshots/...`
- **Failing Automated Test:** `tests/.../test_xxx.py`
- **Resolution / Fix Commit:** [Description of code fix]
- **Status:** [Open | Investigating | Fixed | Verified & Closed]
```

### 6.2 Resolved UAT & Test Regression Defect Log

#### DEF-001: Mobile Axe-Core Color Contrast Failure on Active Status Badge
- **Date Reported:** 2026-11-06
- **Reported By:** QA Lead / Automated A11y Suite
- **Tested Scenario:** U-02 (Option Sets Management)
- **Severity:** Medium (Accessibility Compliance)
- **Actual Behavior:** Active badge used color `#16a34a` (contrast 3.29:1 against white), failing WCAG 2.1 AA 4.5:1 requirement.
- **Failing Test:** `frontend/tests/e2e/responsive_a11y_audit.spec.ts`
- **Resolution:** Updated `OptionSetsManager.tsx` to `#166534` (dark emerald, contrast 7.87:1).
- **Status:** **Closed / Verified**

#### DEF-002: Long Assertion String Formatting in Traceability Suite
- **Date Reported:** 2026-11-07
- **Reported By:** Test Automation Runner (`test-all.ps1`)
- **Tested Scenario:** P4-06 Pre-flight Code Hygiene
- **Severity:** Low (Lint & Formatting)
- **Actual Behavior:** `test_traceability_rules_and_guards.py` lines exceeded 100 characters and had unused imports.
- **Resolution:** Formatted with `ruff` and verified clean lint pass.
- **Status:** **Closed / Verified**

#### DEF-003: Playwright Responsive Timeout on Dismantling at 1280px Desktop
- **Date Reported:** 2026-11-07
- **Reported By:** E2E Test Suite
- **Tested Scenario:** U-13 (Dismantling View)
- **Severity:** Low (Test Flakiness)
- **Actual Behavior:** AxeBuilder analysis on heavy multi-table view exceeded default 30s timeout on 3rd sequential run.
- **Resolution:** Added `test.describe.configure({ timeout: 60_000 })` in `responsive_a11y_audit.spec.ts`.
- **Status:** **Closed / Verified**

---

## 7. Known Limits & Operational Notes
1. **Placeholder Masters:** If business CSVs are not imported, system defaults to 2 demo parties, 1 demo transporter, and 3 demo products (`DEMO-DMT-001`, `DEMO-PRS-001`, `DEMO-EO-001`).
2. **DMT Containers:** Seeded with 4 default containers (`DMT-BIN-01` … `04`); business may add custom bins via Admin → Masters.
3. **Party Notifications:** When sending SMS/WhatsApp, manual confirmation with reference upload is enabled if external SMS gateway credentials are not configured in environment.
4. **Local Hardware Connectivity:** Barcode printing renders high-resolution HTML/SVG labels optimized for standard thermal label printers (4" × 2" and 4" × 6").
