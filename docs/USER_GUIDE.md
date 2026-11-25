# RMS End-User Guide (Role-by-Role Operations)

**System:** Replacement Management System (RMS)  
**Version:** 1.1.0 (12-step offline return flow, 2026-11-23)  
**Target Audience:** Operational teams, Store Managers, Technicians, Coordinators, Accounts, and Administrators  
**Device Support:** Desktop Web Browsers (Chrome, Firefox, Edge, Safari) & Mobile Phones (Android & iOS)

---

## Table of Contents
1. [General System Navigation & Shell](#1-general-system-navigation--shell)
   - [1.3 Your journey: one page per role](#13-your-journey-one-page-per-role)
2. [Gate User — Step 1 (Anuj)](#2-gate-user--step-1-anuj)
3. [Replacement Executive — Steps 2a–2c (Aman)](#3-replacement-executive--steps-2a2c-aman)
4. [Replacement Manager — Step 2d (Pratham Pratap Singh)](#4-replacement-manager--step-2d-pratham-pratap-singh)
5. [Intermediate Store users OP / DT / RI — Steps 3–8](#5-intermediate-store-users-op--dt--ri--steps-38)
   - [5a. Management — corrections, Steps 9–10](#5a-management--corrections-steps-910)
6. [Technician Coordinator Guide (Aman / Sahil)](#6-technician-coordinator-guide-aman--sahil)
7. [Spare Parts & Parts Recovery Guide (Technician & Manager)](#7-spare-parts--parts-recovery-guide-technician--manager)
8. [Accounts — Steps 11–12 (Deepak Ji)](#8-accounts--steps-1112-deepak-ji)
9. [Dispatch Team Guide](#9-dispatch-team-guide)
10. [Super Administrator Guide](#10-super-administrator-guide)
11. [Appendix: goods slips from the earlier flow](#11-appendix-goods-slips-from-the-earlier-flow)

---

## 1. General System Navigation & Shell

### 1.1 Responsive Layout Overview
RMS adapts to your device:
- **Desktop (≥ 1024 px):** left-hand menu, top header with Global Search, notification bell and sign-out.
- **Phone (360 px and up):** ☰ opens the menu; the bottom bar has **My Work**, **Goods Slips**,
  **Dashboard** and **Alerts**. Every screen works on a 360 px phone without sideways scrolling, and
  every button is at least 44 px tall.

### 1.2 Accessing Your Tasks ("My Work")
1. After signing in you land on **My Work**. At the top, **My journey** shows one card per step you
   work on, in the order you work: how many goods slips (GS) are waiting at the step and the **next**
   one (the one waiting longest). **Open next** takes you to that GS's screen; **View all** lists every
   GS waiting at the step, oldest first.
2. Store users see **only their own store's** work (OP, DT or RI): the counts and lists are per store.
3. The left menu shows **only your own steps and tools**, with the number waiting next to each step.
4. Alerts (the bell) tell you when work reaches you, e.g. a transfer slip for your store, a goods slip
   sent for Management approval, or a goods slip at Accounts. Email alerts are not switched on yet.

### 1.3 Your journey: one page per role
Each role's menu follows the goods slip from where it reaches you to where you hand it on. The
administrator can rename steps or change the order (Administration → Role Journeys); the defaults are:

| Step | Role (person) | Menu entry → what you do | Tools |
|---|---|---|---|
| 1 | **Gate User** (Anuj) | **Gate Entry**: party, cartons, how the goods came, optional documents → summary → Submit → print the GS tag | Goods Slips |
| 2a–2c | **Replacement Executive** (Aman) | **Carton Opening** (one video per carton, optional carton document) → **Counting & Categorisation** (items and quantities → Replacement / Complete Sales Return → split each item by condition → **Lock**) | Container Register, Goods Slips, Reports |
| 2d | **Replacement Manager** (Pratham) | **Transfer Slips**: one slip per Intermediate Store for one or many goods slips, or an **Edit Request** to Management | Goods Slips, Pendency Register, Dashboard, Reports, Audit Explorer |
| 3–8 | **Intermediate Store OP / DT / RI** | **Acknowledge Transfer Slips** → **Department Routing** → **Receive from Departments** → **Analysis** (Dispatch New / Dispatch Repaired / Not Allowed; optionally send for Management approval) | Goods Slips |
| 9–10 | **Management** | **Management Approval** (change any decision, incl. Issue CN; approve = e-approval stamp) · **Edit Requests** (correct a locked goods slip) | Dashboard, Goods Slips, Pendency Register, Reports, Audit Explorer |
| 11–12 | **Accounts** (Deepak Ji) | **Gate Documents Check** · **Accounts Entry** (one Challan and, if needed, one Credit Note per goods slip → Dispatch Slip) · **Party Email** | Goods Slips, Credit Notes, Reports |
| — | **Dispatch** | **Dispatch**: ship each ready Dispatch Slip | Goods Slips, Dispatch Queue |
| — | **Management Viewer** | Read-only | Dashboard, Goods Slips, Pendency Register, Reports, Audit Explorer |
| — | **Super Admin** | Every step and tool, plus Administration | All |

A goods slip moves through these statuses (labels are configurable): Gate Created → Carton Opening →
Counting → Categorisation → **Pending Transfer Slip** → **Transfer Slip Generated** → **Acknowledged
by Store** → **In Store Processing** → **Analysis Completed** → **At Accounts** → **Pending Dispatch**
→ In Process → Closed. Two parking statuses: **Sales Return – On Hold** (Complete Sales Return; that
journey is built later) and **On Hold – Not Allowed** (every piece Not Allowed: no Accounts entry).

---

## 2. Gate User — Step 1 (Anuj)

**Role:** `GATE_INWARD` · **Device:** phone or tablet

### 2.1 Creating a Goods Slip
1. Menu → **Gate Entry** (or **+ New**).
2. **Return Type**: Offline or E-Commerce. For Offline enter the **Gate Entry Date** and **Gate Entry
   No.** (the number is unique in the financial year).
3. **State → Station → Party**: pick the state, then the station, then search the party.
4. **Cartons**: how many cartons arrived.
5. **Received Through**: Courier (courier name + docket no.), Transport (transport name) or By Hand.
6. **Documents From Party** (optional): one row per document (Invoice, GST Debit Note, Hand Written
   Slip) with its photo, or choose **No Documents From Party**. **Documents From Transport** (optional):
   e.g. the courier slip with its photo. Only photos are needed, no document numbers or dates.
7. Tap **Submit & Create GS**. A **summary** opens: check party, station, cartons, transport and
   documents. **Back to edit** returns to the form without creating anything; **Submit** creates the GS.
8. The GS number appears (e.g. `GS/2026-27/00042`). Tap **Print GS Tag** and stick one tag on each
   carton. The photos upload right after; a failed upload shows **Retry**.

---

## 3. Replacement Executive — Steps 2a–2c (Aman)

**Role:** `INWARD_VERIFIER` (shown as "Replacement Executive") · **Device:** phone with camera

### 3.1 Carton Opening (Step 2a)
1. Menu → **Carton Opening** → open the GS → **Start**.
2. Record or upload **one video per carton**. The checklist shows "Carton videos 1 of 2 · carton 2
   missing" until every carton has its video.
3. Optional: if a document is found inside a carton, choose its type (Invoice, GST Debit Note, Hand
   Written Slip), take its photo and tap **Save document**. If the gate recorded "No Documents From
   Party", this document clears that tag.
4. **Next** is enabled once every carton has a video. It opens the item screen.

### 3.2 Items (Step 2b)
1. For each product: search by name or code, enter **As per document** (optional) and **Physically
   received**, tap **Add line**.
2. Tap **Next**. A popup asks: **Replacement** or **Complete Sales Return**.
   - **Complete Sales Return**: the GS parks as *Sales Return – On Hold* (no further steps for now).
   - **Replacement**: the categorisation screen opens.

### 3.3 Categorisation and Lock (Step 2c)
1. For each line tap **Edit line** and split the physical quantity across the conditions offered for
   that product's category (e.g. 3 OK + 1 Broken). The line shows "Split 4 / Physical 4" when it adds up.
2. **Lock** is enabled only when every line adds up. Tap **Lock** and confirm. The goods are booked into
   Inward Staging and the GS waits for the Replacement Manager's transfer slip.
3. After the lock only Management (or the Super Admin) can change the GS, and only until department
   routing has started.

### 3.4 Daily DMT Container Audit
Menu → **Container Register**: count each DMT bin, tick the confirmation and submit.

---

## 4. Replacement Manager — Step 2d (Pratham Pratap Singh)

**Role:** `REPLACEMENT_MANAGER` · **Device:** desktop or tablet

### 4.1 Generating transfer slips
1. Menu → **Transfer Slips** → tab **Pending Transfer Slip** lists every locked GS. **View items**
   shows a GS's items (read-only).
2. Tick one GS, several, or all. Tap **Generate Transfer Slip**. The confirmation shows one slip per
   Intermediate Store (e.g. "DT · 2 GS · 7 pc", "OP · 1 GS · 2 pc"); confirm.
3. Each store gets one slip that combines its items from all the selected goods slips (`TRF/DT/…`,
   `TRF/OP/…`, `TRF/RI/…`). Which store gets which item comes from the category → store mapping
   (Administration → Intermediate Stores).
4. Tab **Generated slips**: open a slip to see its lines per GS and condition, subtotals and the grand
   total; **Download PDF** prints it with the HICKS logo.

### 4.2 Edit Request instead of a slip
If a locked GS is wrong (e.g. a wrong product or count), tap **Send Edit Request** on its card, write
what should be corrected and tap **Send to Management**. The GS shows "Edit requested" and cannot be
selected until Management resolves the request. If Management changes a GS that already has a slip,
that slip is voided and the GS comes back to your pending list: generate it again.

---

## 5. Intermediate Store users OP / DT / RI — Steps 3–8

**Roles:** `ISTORE_OP`, `ISTORE_DT`, `ISTORE_RI` (one per store; the Admin can add stores)
**Device:** phone or desktop. You only see your own store's slips and items; **Show all items of this
GS** shows the other stores' items read-only.

### 5.1 Acknowledge the transfer slip (Step 3)
1. Menu → **Acknowledge Transfer Slips** → open the slip. Check the goods against the lines.
2. Tap **Acknowledge receipt**, add a remark if you like, **Confirm receipt**. The goods are now in
   your store's location. A slip is always acknowledged in full.
3. Something wrong (e.g. a damaged carton)? Tap **Report discrepancy** and describe it; the RM and
   Management are alerted. You still acknowledge the slip afterwards.

### 5.2 Department Routing (Steps 4–5)
1. Menu → **Department Routing** → open the GS ("DT: Routing pending (3 pcs)"). You can start as soon
   as **your** slip is acknowledged; you do not wait for the other stores.
2. For each item and condition, enter how many pieces go to which department. "Issue to Store" (stays
   in store) means no department work.
3. **Save routing** → check the summary → **Save & issue**. Saving issues the pieces at once: a
   Department Issue Note (DIN) is created; tap it to print. The pieces wait at the department.
4. Saved an "Issue to Store" line by mistake? Tap **Undo**, give a reason, and route those pieces again
   (possible until the piece is analysed).

### 5.3 Receive from Departments (Step 6)
1. Menu → **Receive from Departments** shows each GS with goods still at a department (per party).
2. Tap **Receive** on a DIN. Enter the quantity back, the outcome (e.g. Repaired, Cleaned / Calibrated,
   Not Repaired, **Return for Re-routing**) and the condition after the work. Partial receipts are
   fine. **Confirm receipt**: the stock goes back to your store.
3. "Return for Re-routing" sends the pieces back to your Department Routing list.
4. When everything of your store is back (or stayed in store), the GS is **ready for analysis**.

### 5.4 Analysis (Steps 7–8)
1. Menu → **Analysis** → open the GS ("DT: Ready for analysis").
2. For each item and condition decide the pieces: **Dispatch New Piece**, **Dispatch Repaired Piece**
   or **Not Allowed** (you may split, e.g. 1 new + 2 repaired). The one-tap buttons put every piece of
   a condition on one decision.
   **Issue CN Request** (DEC-74): a store cannot issue a credit note itself, but it can put pieces on
   **Issue CN Request** (with the quantity) for Management to decide. On submit, the dialog shows how
   many pieces go to Management and takes an optional note. The GS then waits for Management: it
   cannot go to Accounts until Management has decided those pieces (Issue CN or another action) and
   approved it.
3. **Submit analysis**. A submission is final for your store (only Management can change it later).
4. **Send for Management Approval** (optional, Step 9): after your own submission, with a reason. If
   your store is the last one to submit, tick **Also send for Management approval** in the submit
   dialog; otherwise the GS goes straight on to Accounts.
5. When every store on the GS has submitted, the GS is *Analysis Completed* and moves on by itself: to
   Accounts, or on hold if every piece is Not Allowed.

---

## 5a. Management — corrections, Steps 9–10

**Role:** `MANAGEMENT` · **Device:** phone or desktop

### 5a.1 Edit Requests (after the lock)
1. Menu → **Edit Requests** → open the GS. The request is shown at the top.
2. **Change line** (quantities, product or condition split; a reason is required), or add / remove a
   line. Possible until department routing has started. A change voids that GS's transfer slips; the
   RM generates them again.
3. **Mark as edited** closes the request, or **Reject request** with a note to the RM.

### 5a.2 Management Approval (Steps 9–10)
1. Menu → **Management Approval** lists the goods slips stores sent to you (with their reason); you can
   also search any analysed goods slip.
2. Open a GS. You may change any decision to any other, including **Issue CN** (only Management sets
   Issue CN), change quantities, and add or remove decision lines. Every change needs a reason;
   **Save changes**.
   **Issue CN Request from a store** (DEC-74): the queue marks it ("Issue CN Request · N pcs"), and each
   condition shows "Store requests Issue CN for N pcs". Those pieces start undecided. Put them on
   **Issue CN** (the one-tap **Issue CN N pcs** button) or on any other action, give a reason, and save.
   **Approve** stays off until no piece is left on the request.
3. **Approve**. The goods slip gets the **"Digitally approved by Management"** stamp (your name, role,
   time and a reference). It is a system e-approval, not a legal digital signature. **Verify** checks
   that the approved content is unchanged. The stamp prints on the Replacement Slip and Dispatch Slip.
4. A goods slip with Issue CN always carries this stamp. Approving sends the GS on to Accounts (or on
   hold). Until Accounts completes it you may still change it: the Replacement Slip is withdrawn and
   your next approval sends version 2 to Accounts.

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

## 8. Accounts — Steps 11–12 (Deepak Ji)

**Role:** `ACCOUNTS` · **Device:** desktop (works on a phone too)

### 8.1 Gate Documents Check
Menu → **Gate Documents Check**: the party documents photographed at the gate and in the cartons, for
the GST input check. Acknowledge each.

### 8.2 Accounts Entry per goods slip
1. A goods slip reaches you only when **every** Intermediate Store on it has submitted its analysis
   and no Management approval is pending. You get an alert; the Replacement Slip is ready.
2. Menu → **Accounts Entry** → tab **To enter**. Each card says what is needed (e.g. "Challan to
   enter"). Tab **On hold** lists goods slips where every piece is Not Allowed: they never need an
   Accounts entry.
3. Open the GS. **Print Replacement Slip** prints the GS-wise slip (lines with store, condition,
   decision and quantity, totals per decision, Management stamp if any).
4. Enter, for the whole goods slip:
   - **Challan No.** + **Challan Date**: shown only if goods ship (Dispatch New / Dispatch Repaired);
   - **CN No.** + **CN Date** + **CN Value (₹)**: shown only if the GS has Issue CN.
   Dates cannot be in the future, the CN number must be unique and the value must be above 0. **Save**.
5. **Complete** → **Complete & generate Dispatch Slip**. The Dispatch Slip (with the Challan, Credit
   Note and stamp) goes to Dispatch and the GS shows *Pending Dispatch*. If nothing ships (Issue CN
   only), completing settles the pieces and the GS goes on to closure.
6. **Party Email** (menu): send the party the Credit Note / Challan / dispatch details.

---

## 9. Dispatch Team Guide

**Role:** `DISPATCH`

1. Menu → **Dispatch** lists the ready Dispatch Slips.
2. Open a slip, pack the goods (Dispatch New: a fresh piece from the Main Store; Dispatch Repaired: the
   repaired piece from the store), enter the dispatch date, transporter / courier and docket or vehicle
   number, and confirm.
3. Dispatching moves the stock: the old piece of a "Dispatch New" goes to the Non-Functional Store, Not
   Allowed pieces to the Rejected Hold, repaired pieces out as dispatched.

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

### 10.5 Intermediate Stores and category mapping
- **Administration → Intermediate Stores**: rename a store, add a new one (each has its own role and
  stock location) and map product categories / sub-categories to it. A sub-category mapping overrides
  its category; anything unmapped goes to the default store. See `docs/ADMIN_GUIDE.md` §3.4.

---

## 11. Appendix: goods slips from the earlier flow

Goods slips created before the 12-step flow (RM Review, RM department routing, Store Manager
acceptance / issue, RE department receiving, RM Final Actions, CSR approval, Inspection & Grading)
still open from **Goods Slips** → the GS page, which shows the buttons for their current step. Those
menu entries are hidden for new work; the administrator can switch one back on in Administration →
Role Journeys if an old goods slip needs it. Accounts enters their Credit Note / Challan per line as
before.
