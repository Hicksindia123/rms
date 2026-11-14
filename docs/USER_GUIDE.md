# RMS End-User Guide (Role-by-Role Operations)

**System:** Replacement Management System (RMS)  
**Version:** 1.0.0  
**Target Audience:** Operational teams, Store Managers, Technicians, Coordinators, Accounts, and Administrators  
**Device Support:** Desktop Web Browsers (Chrome, Firefox, Edge, Safari) & Mobile Phones (Android & iOS)

---

## Table of Contents
1. [General System Navigation & Shell](#1-general-system-navigation--shell)
   - [1.3 Your journey: one page per role](#13-your-journey-one-page-per-role)
2. [Gate Inward Guide (Anuj)](#2-gate-inward-guide-anuj)
3. [Unboxing & Inward Verifier Guide (Aman)](#3-unboxing--inward-verifier-guide-aman)
4. [Replacement Manager Guide (Pratham Pratap Singh)](#4-replacement-manager-guide-pratham-pratap-singh)
5. [Intermediate Store In-Charge Guide (Sahil)](#5-intermediate-store-in-charge-guide-sahil)
6. [Technician Coordinator Guide (Aman / Sahil)](#6-technician-coordinator-guide-aman--sahil)
7. [Spare Parts & Parts Recovery Guide (Technician & Manager)](#7-spare-parts--parts-recovery-guide-technician--manager)
8. [Accounts Team Guide (Deepak Ji)](#8-accounts-team-guide-deepak-ji)
9. [Dispatch Team Guide](#9-dispatch-team-guide)
10. [Super Administrator Guide](#10-super-administrator-guide)

---

## 1. General System Navigation & Shell

### 1.1 Responsive Layout Overview
RMS adapts seamlessly to your device:
- **Desktop (>1024px):** Fixed left-hand navigation sidebar, top header with Global Search (`/search?q=...`), active role switcher, and quick notification bell.
- **Mobile (<640px):** Fixed bottom navigation bar containing 5 quick-access tabs:
  - 📋 **My Work:** Your personal task inbox, prioritized by SLA due dates.
  - 📦 **Goods Slips:** Search and browse all consignments.
  - ➕ **+ New:** Create a new Goods Slip (Gate role).
  - 📊 **Dashboard:** Real-time role KPI cards and metrics.
  - ⚙️ **Profile / Alerts:** Switch active role, view unread alerts, or sign out.

### 1.2 Accessing Your Tasks ("My Work")
1. Upon logging in, you land on **My Work** (`/#/mywork`). At the top, **My journey** shows one card
   per step you work on, in the order you work: how many goods slips are waiting at the step and the
   **next** one to act on (the one waiting longest). **Open next** takes you straight to that goods
   slip's screen; **View all** lists every goods slip waiting at the step, oldest first.
2. The left menu (☰ on a phone) shows **only your own steps and tools**, in the same order, with the
   number waiting next to each step. Modules that are on hold (dismantling, scrap register, batteries)
   are not shown. **Administration** is collapsed; open it only when you need it.
3. Below the journey, **Assigned tasks** lists workflow tasks for your roles. Tasks are color-coded:
   - 🟢 **Normal:** Within standard turnaround SLA.
   - 🟡 **Due Soon:** Under 4 hours remaining.
   - 🔴 **Overdue:** SLA exceeded; supervisor notified.
4. Tap or click on any task card to navigate directly into the corresponding step screen.

### 1.3 Your journey: one page per role
Each role's menu follows the goods slip (GS) from where it reaches you to where you hand it on.
The administrator can change the order, labels and which role sees what (Administration → Role
Journeys); the steps below are the defaults.

| Role (person) | Journey: start → end | Tools |
|---|---|---|
| **Gate Inward** (Anuj) | **Gate Entry**: choose Offline / E-Commerce return, gate entry date and number, State → Station → Distributor, carton count and documents (invoice / debit note alerts Accounts) → print the GS tag. The GS then waits at Carton Opening. | Goods Slips |
| **Inward Verifier** (Aman) | **Carton Opening** (video per carton, more documents) → **Counting** (items and quantities) → **Categorisation** (split each item's quantity into its buckets, plus packaging / container / user-manual counts) → the GS goes to RM Review. Later: **Department Receiving**, receiving goods back from departments per outcome. | Container Register, Goods Slips, Reports |
| **Replacement Manager** (Pratham) | **RM Review** (approve the whole GS; the Transfer Slip is created) → **Department Routing** (GS held in the store: send quantities to departments) → **Final Actions** (back from departments: split quantities across Send New / Send Repaired / Issue CN / Not Allowed and print the A/c Actions slip). | Approvals, Goods Slips, Pendency Register, Dashboard, Reports, Audit Explorer |
| **Intermediate Store** (Sahil) | **Store Acceptance**: accept the Transfer Slip; the GS shows "Held at Intermediate Store". | Custody & Store, Inventory, Store Issues, Goods Slips |
| **Accounts** (Deepak Ji) | **Gate Documents Check** (GST input check of invoices / debit notes) → **Accounts Entry** (CN No./Date/Value and Challan No./Date per action line; completing it creates the Dispatch Slip) → **Party Email** (send the party the CN / challan / dispatch details). | Goods Slips, Credit Notes (earlier flow), Reports |
| **Dispatch** | **Dispatch**: issue the goods on each ready Dispatch Slip (date, transporter, docket / vehicle). | Goods Slips, Dispatch Queue (earlier flow) |
| **Technician Coordinator / Technician** | No journey step in the new flow; servicing works as before. | Servicing, Custody & Store, Goods Slips |
| **Spare Parts Manager / Technician, Main Store** | Dismantling and spare parts are **on hold**: their screens are hidden until released. | Inventory, Custody & Store, Reports |
| **Management Viewer** | Read-only. | Dashboard, Goods Slips, Pendency Register, Reports, Audit Explorer |
| **Super Admin** | Sees every step and tool, plus Administration. | All |

---

## 2. Gate Inward Guide (Anuj)

**Persona:** Anuj  
**System Role:** `GATE_INWARD`  
**Primary Devices:** Android smartphone or rugged tablet (📱)  

### 2.1 Receiving a Delivery & Creating a Goods Slip (GS)
1. Tap the **+ New** button on the bottom navigation bar or top header.
2. Select the **Delivery Mode**:
   - **COURIER:** Enter Courier Company Name and Tracking/Docket Number.
   - **DIRECT_TRUCK:** Enter Truck Vehicle Registration Number and Driver Contact Phone.
   - **SELF_DELIVERY:** Enter Bearer/Person Name and Contact Phone.
3. **Party Selection:**
   - Type to search party by Name or GSTIN.
   - State and Station auto-populate based on party master data. If receiving from a different station, check the "Override" checkbox and enter the actual station and reason.
   - If the party is not in the system, enter the party name; it will be registered as a **Provisional Party** for Accounts review.
4. **Package Count & Condition:**
   - Enter total number of physical boxes/packages received.
   - Inspect outer box condition. If torn, crushed, or water-damaged, record remarks.
5. **Document Verification:**
   - If no delivery document (invoice, challan, debit note) is physically attached to the outer package, check the **"No Document Attached"** toggle.
   - *Note:* This raises an alert for the Unboxing Verifier and Replacement Manager.
6. Tap **"Create Goods Slip"**.
7. The system generates a formal Goods Slip number (e.g., `GS/2026-27/00042`).

### 2.2 Barcode & Tag Printing
1. Immediately upon creation, tap **"Print Barcode Tags"**.
2. One adhesive barcode label is printed per physical box (e.g., Box 1 of 3, Box 2 of 3).
3. Affix each printed tag securely to the corresponding outer carton before placing into inward staging.

---

## 3. Unboxing & Inward Verifier Guide (Aman)

**Persona:** Aman  
**System Role:** `INWARD_VERIFIER`  
**Primary Devices:** Mobile phone with camera (📱) / Workbench terminal  

### 3.1 Unboxing Evidence & Document Classification (G-02)
1. Open the assigned GS from your **My Work** inbox.
2. Tap **"Start Unboxing"**.
3. **Video Evidence:**
   - Tap "Record Unboxing Video" or upload a pre-recorded clip showing the unopened carton, shipping label, cut seal, and contents unpacked.
4. **Document Capture & Classification:**
   - Photograph all enclosed documents (Invoice, Debit Note, Delivery Challan, Return Slip).
   - For each photo, tap the document type tag (`INVOICE`, `DEBIT_NOTE`, `CHALLAN`, `RETURN_SLIP`).
   - If "No Document Attached" was flagged at the gate, photograph the courier shipping label and outer carton clearly, enter a justification note, and tap **"Request Missing Document Exception"**.
5. Once video and classified photos are attached, tap **"Complete Unboxing"**.

### 3.2 Product Itemisation & Shortage Logging
1. Enter each returned product:
   - Search Product Code or Name.
   - **Documented Quantity:** Quantity claimed on party document.
   - **Received Quantity:** Actual physical count unpacked.
2. If Received < Documented, the system automatically marks the difference as **Shortage** (e.g., "Short 2 pcs").
3. Select Return Nature:
   - **Replacement Only (RO):** Standard return for servicing/replacement.
   - **Complete Sales Return (CSR):** Whole shipment commercial return. Requires RM approval.
4. Tap **"Submit Itemisation"**.

### 3.3 Condition Grading (BR-11, BR-12, G-06)
1. For each itemized product line, tap **"Grade Conditions"**:
   - **DMT Category (8 conditions):** OK Packed, Dirty, Scratched, Display Issue, Broken Body (Not Allowed), Other Brands (Not Allowed), Short Quantity.
   - **Prismatic Category (3 conditions):** OK Packed, Bulb Broken (No Mercury), Broken With Mercury (Hazardous).
   - **Enclosed Oval Category (4 conditions):**
     > ⚠️ **Important Guard (G-06):** Grading options remain disabled until you tick the checkbox: *"Full outer enclosure opened and bulb inspected"*.
2. **Hazard Handling:** Any piece marked "Broken With Mercury" turns the UI red, shows a hazardous materials warning, and routes immediately to `HAZARD_QUARANTINE`.
3. **Extraction Reconciliation (G-07):**
   - Record quantities extracted from packaging vs container bins.
   - *Total extracted must exactly equal received quantity.*
4. Tap **"Finalise Grading"**.

### 3.4 Daily DMT Container Audit (BR-18)
1. Every morning before 09:00, open **Container Register**.
2. Count pieces in each DMT bin (`DMT-BIN-01` … `04`).
3. Enter counts, tick the confirmation checkbox, and tap **"Submit Daily Audit"**.

---

## 4. Replacement Manager Guide (Pratham Pratap Singh)

**Persona:** Pratham Pratap Singh  
**System Role:** `REPLACEMENT_MANAGER`  
**Primary Devices:** Desktop PC / Tablet  

### 4.1 Approving CSR Requests (G-03)
1. In your **Approvals** inbox, review consignments flagged as **Complete Sales Return (CSR)**.
2. Inspect unboxing video and uploaded party debit note.
3. Click **"Approve CSR"** (moves directly to Intermediate Store with packaging) or **"Reject CSR"** (reverts consignment to Replacement Only for technical grading).

### 4.2 Item-Wise Segregation & Pending (BP) Management (BR-19, G-08)
1. Open the graded Goods Slip.
2. For each condition group, assign an operational resolution:
   - **Send New:** Dispatch brand new replacement unit.
   - **Send Repaired:** Serviced/repaired unit to be issued.
   - **Issue CN:** Issue commercial credit note.
   - **Pending (BP):** Put on hold awaiting customer authorization or bill-pass approval. Enter mandatory reason.
3. Tap **"Generate Replacement Slip"**.
4. Hand over the printable slip to the Intermediate Store.
5. To release a pending piece: Open **Pendency Register**, select line, click **"Resolve Pendency"**, choose final action (e.g., Send New), and save. This generates Revision 2.

### 4.3 Credit Note Decision (DEC-13)
1. Following technical servicing and dismantling, open the **Resolution Board**.
2. Compare the original planned RM action against actual technical outcome.
3. Select **"ALLOW_CN"** or **"DENY_CN_SEND_REPLACEMENT"**.
4. If denying CN after initially planning to issue one, enter a **Deviation Reason**.
5. Submit decision to route approved lines to Accounts.

---

## 5. Intermediate Store In-Charge Guide (Sahil)

**Persona:** Sahil  
**System Role:** `INTERMEDIATE_STORE_MANAGER`  
**Primary Devices:** Desktop Terminal / Mobile Phone (📱)  

### 5.1 Accepting Custody & Resolving Discrepancies (G-09)
1. When Inward Verifier initiates a handover, an **Accept Custody** task appears in your inbox.
2. Count the delivered physical pieces against the digital Transfer Note.
3. If counts match: Tap **"Accept Handover"**. Stock immediately reflects in Intermediate Store ledger.
4. If counts differ (e.g., 5 delivered vs 6 digital):
   - Tap **"Report Discrepancy"**.
   - Enter physical count received (5). Handover freezes.
   - Inward Verifier (Aman) joins you to verify physical count.
   - Both parties review the resolution dialog: select *"Accept Counted (5), Return Difference (1)"*.
   - Both sign digitally. 5 units enter your store; 1 unit returns to Aman.

### 5.2 Functional Stock Issuance to Main Store (BR-31)
1. In your inventory view, filter by **Functional Good** or **Functional Repaired**.
2. Select products and quantities ready for commercial distribution.
3. Click **"Issue to Main Store"**.
4. Print the **Store Issue Voucher** and physically transfer items to Main Store shelves.

---

## 6. Technician Coordinator Guide (Aman / Sahil)

**Personas:** Aman or Sahil  
**System Role:** `TECHNICIAN_COORDINATOR`  
**Primary Devices:** Workshop Terminal / Tablet  

### 6.1 Allotting Servicing Batches (BR-23)
1. Open **Servicing Workshop** → **New Batch Allotment**.
2. Select Technician: **Raj Kumar Ji**.
3. Select eligible units in Intermediate Store needing servicing (Dirty, Scratched, Display Issue).
4. System automatically assigns batch number (e.g., `TECH/2026-27/00015`).
5. Hand over physical units with printed batch slip.

### 6.2 Recording Servicing Results & Battery Deductions (G-10)
1. When technician returns serviced batch, open batch record.
2. Enter results:
   - **Cleaned & Functional:** Pieces restored to working order.
   - **Batteries Installed:** Exact number of CR2032 batteries consumed.
     > 💡 **Automated Stock Deduction:** System immediately deducts this exact quantity from `BATTERY_STORE` ledger.
   - **Permanent Scratches:** Classified as `NON_SELLABLE`.
   - **Non-Repairable:** Classified as `NON_GOOD` (routes to Parts Recovery).
3. Tap **"Receive Batch"** to update stock categories.

---

## 7. Spare Parts & Parts Recovery Guide (Technician & Manager)

**Personas:** Spare Parts Technician (`spt@rms.local`) & Spare Parts Manager (`spm@rms.local`)  
**Roles:** `SPARE_PARTS_TECHNICIAN`, `SPARE_PARTS_MANAGER`  
**Primary Devices:** Dismantling Bench Terminal / Desktop  

### 7.1 Dismantling Non-Good Units (BR-26, G-11)
1. Spare Parts Technician opens **Dismantling Queue**.
2. Select lots marked `NON_GOOD`.
3. Choose storage method: **Dedicated Containers** or **Partitioned Bins**.
4. Enter extracted component quantities:
   - **TIP** (Pcs)
   - **BODY** (Pcs)
   - **WIRE** (Pcs)
   - **PCB** (Pcs)
5. **Mandatory PCB Metadata (G-11):** Enter PCB Model Code and Supplier Name. System will strictly reject submission without both.
6. Select target container barcode (e.g., `PART-BIN-B4`).
7. Tap **"Complete Dismantling"**. Recovered parts are instantly available in spare parts inventory.

### 7.2 Scrap & Hazardous Waste Disposal (DEC-11, G-05)
1. Spare Parts Manager opens **Scrap Register** (`/#/scrap`).
2. Review stock awaiting disposal (Scrap body parts and Mercury-quarantined units).
3. Select lot to dispose and click **"Mark for Disposal"**.
4. Enter mandatory **Authorized Waste Manifest Number** and Government-authorized Contractor Name.
5. Click **"Confirm Disposal"**.
6. Lot transfers to `SCRAP_DISPOSED` with immutable audit log.

---

## 8. Accounts Team Guide (Deepak Ji)

**Persona:** Deepak Ji  
**System Role:** `ACCOUNTS`  
**Primary Devices:** Desktop Browser (Wide display recommended)  

### 8.1 Document Audit & GST Portal Verification (G-13, G-14)
1. Open **Credit Notes Workspace** (`/#/credit-notes`).
2. Inspect unboxing document photos and party tax invoice.
3. Open government GST portal in companion window.
4. For each credit note line:
   - Toggle **GST Portal Reflected**:
     - **Yes (Reflected):** System permits standard **GST Credit Note**.
     - **No (Not Reflected):** System strictly blocks GST Credit Note and allows only **Journal Voucher (JV)**.
5. **Rate Verification (G-14):**
   - Enter proposed CN rate.
   - If rate exceeds the historical purchase rate recorded on the invoice, the system raises a rate violation warning requiring Manager sign-off.
6. Select CN Type:
   - **GST Credit Note:** Standard tax reversal.
   - **General Credit Note:** For repaired items (no tax reversal).
   - **Journal Voucher (JV):** Pure financial adjustment without GST return impact.
7. Click **"Issue Credit Note"**.

---

## 9. Dispatch Team Guide

**Persona:** Dispatch Team  
**System Role:** `DISPATCH`  
**Primary Devices:** Logistics Workbench Terminal / Mobile  

### 9.1 Processing Replacement Shipments
1. Open **Dispatch Queue** (`/#/dispatch`).
2. View pending dispatches:
   - **Send New:** Brand new stock drawn from Main Store.
   - **Send Repaired:** Tested repaired stock drawn from Intermediate Store.
3. Package the replacement goods.
4. Enter carrier details: Transporter / Courier Name and Docket / Consignment Number.
5. Click **"Confirm Dispatch"**.
6. System links the dispatch record directly to the original Goods Slip.

---

## 10. Super Administrator Guide

**Persona:** System Administrator  
**System Role:** `SUPER_ADMIN`  
**Primary Devices:** Desktop Browser  

### 10.1 User & Role Management
- Navigate to **Admin Panel** → **Users & Permissions**.
- Create users, deactivate departures, assign multiple roles, and review the RBAC permission matrix.

### 10.2 Option Sets & The Critical NO → YES Warning
- Navigate to **Admin Panel** → **Option Sets**.
- You can relabel options safely at any time (G-18 protects historical records).
- ⚠️ **Critical Compliance Warning:** If you attempt to change an option from "Not Allowed" to "Allowed" (e.g., hazardous mercury conditions), the system requires administrative re-authentication, mandatory justification remarks, and alerts company compliance officers. Locked System Guards (G-01 … G-18) can never be disabled.

### 10.3 Form & Workflow Versioning
- Use the visual **Form Builder** to configure fields and rules.
- When ready, click **"Publish Version"**. The system increments the version counter (`v1` → `v2`) and pins all active Goods Slips to their current version to ensure complete audit integrity.

### 10.4 Role Journeys & modules on hold (change plan Phase 10)
- **Administration → Role Journeys:** pick a role, then add, remove or reorder its steps and tools
  (▲ / ▼), give a reason and **Save journey**. Under *Steps and tools* you can rename an entry, change
  its hint, or deactivate it for everyone. Every change is in Config History. Screens and queue
  definitions are fixed; a menu entry never hides a permission check (an entry also needs the
  matching permission to appear).
- **Modules on hold:** setting `features.on_hold` (Administration → System Settings) lists the
  modules whose menu entries are hidden (default: dismantling, spare_parts, battery,
  pcb_subinventory). Remove a code to show its screens again. Nothing is deleted.
