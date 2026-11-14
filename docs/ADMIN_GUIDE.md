# RMS Administrator & Governance Guide

**Document Version:** 1.0.0  
**Target Audience:** Super Administrators, System Architects, IT Operations, and Compliance Officers  
**Security Level:** Internal & Operational  

---

## 1. Governance Architecture Overview

The **Replacement Management System (RMS)** separates business logic, data models, and user interfaces into an auditable, configuration-driven platform. 

Administrators have granular authority over:
- Identity, authentication, and the Role-Based Access Control (RBAC) permission matrix.
- Master data records (Parties, Products, Transporters, Containers, Locations).
- Option catalogues, dropdown hierarchies, and conditional form fields.
- Workflow versions, step routing, and escalation timelines.
- Number series formatting and fiscal year reset behavior.
- Document print layouts and email/SMS/WhatsApp notification dispatch rules.
- **Provisional decision toggles (DEC-01 … DEC-34)** implemented in `system_settings`.

### 1.1 Fundamental Administrative Principles
1. **Historical Immutability (Guard G-18):** Changes made in the Admin Panel never retroactively mutate or corrupt closed or in-flight Goods Slips. Every transaction pins its form version, option snapshot, and workflow version.
2. **System Guards are Non-Bypassable:** Guards G-01 through G-18 are hardcoded into database constraints, row-level policies, and core services. Even a `SUPER_ADMIN` cannot bypass or turn off a System Guard.
3. **Audit Trail Completeness (Guard G-17):** Every configuration create, update, or publish action is permanently recorded in `config_change_log` with user ID, timestamp, prior state, new state, and mandatory justification reason.

---

## 2. Managing Users, Roles & Permissions

### 2.1 Role Catalogue (§3.3)
RMS defines 13 operational and management roles:

| Role Code | Description / Department | Typical Personnel | Key Responsibilities |
|---|---|---|---|
| `SUPER_ADMIN` | Global System Administrator | IT Admin | Full administrative access, user creation, config publishing. |
| `GATE_INWARD` | Gate Security & Receiving | Anuj | Physical consignment intake, delivery modes, package tags. |
| `INWARD_VERIFIER` | Unboxing & Inspection Verifier | Aman | Video/photo unboxing, itemisation, condition grading, daily container audit. |
| `REPLACEMENT_MANAGER` | Replacement Dept Head | Pratham Pratap Singh | CSR approval/rejection, item actions (Send New/Repaired/CN/BP), CN decisions. |
| `INTERMEDIATE_STORE_MANAGER` | Intermediate Store In-charge | Sahil | Physical custody intake, discrepancy reporting, packaging replacement, Main Store issues. |
| `TECHNICIAN_COORDINATOR` | Servicing Batch Coordinator | Aman, Sahil | Allots batches to technician, logs servicing results, tracks CR2032 battery stock. |
| `TECHNICIAN` | Servicing & Repair Technician | Raj Kumar Ji | Performs cleaning, component fixes, and battery installations. |
| `SPARE_PARTS_TECHNICIAN` | Parts Recovery Technician | Parts Recovery Tech | Dismantles non-good units, logs TIP/BODY/WIRE/PCB, records PCB model & supplier. |
| `SPARE_PARTS_MANAGER` | Spare Parts Custodian | Spare Parts Manager | Exclusive custody of non-functional stock, scrap register, hazardous disposal manifests. |
| `ACCOUNTS` | Commercial & Financial Team | Deepak Ji | Inspects unboxing documents, checks GST portal, issues GST/General CNs or JVs. |
| `DISPATCH` | Replacement Dispatch Team | Logistics Dispatch | Issues replacement dispatch notes, records tracking details for Send New/Repaired. |
| `MAIN_STORE` | Central Commercial Warehouse | Main Store Manager | Receives certified functional stock from Intermediate Store for sales replenishment. |
| `MANAGEMENT_VIEWER` | Executive & MIS Stakeholders | Management / Auditors | Read-only access to all reports (R-01…R-18), dashboards, and audit logs. |

### 2.2 User Provisioning & Immediate Deactivation
- **Creating a User:**
  1. Open **Admin Panel** → **Users**.
  2. Click **"+ Add User"**.
  3. Enter Full Name, Email, and assign one or more Roles.
  4. User is provisioned in Supabase Auth and receives an invitation or out-of-band password.
- **Multi-Role Assignment:**
  - Users can hold multiple roles (e.g., Aman holds both `INWARD_VERIFIER` and `TECHNICIAN_COORDINATOR`).
  - In the application shell, a role switcher dropdown appears, allowing users to switch between active operational contexts without logging out.
- **Immediate Deactivation:**
  - Toggling `is_active = false` immediately terminates the user's active session.
  - Future API calls return `403 ACCOUNT_INACTIVE`.

### 2.3 The Role-Permission Matrix
- Open **Admin Panel** → **Permission Matrix**.
- Permissions are structured by Module (`goods_slips`, `unboxing`, `inspection`, `custody`, `servicing`, `credit_notes`, etc.) and Action (`view`, `create`, `edit`, `approve`, `delete`, `export`, `configure`).
- Modifications apply dynamically to all users holding the updated role upon their next API call.

---

## 3. Master Data Management

Navigate to **Admin Panel** → **Masters** to manage enterprise reference entities:

### 3.1 Parties Master (`public.parties`)
- Fields: Party Code, Name, GSTIN (validated against GST checksum regex), State, Station, Contact Person, Phone, Email.
- **Provisional Parties:** Parties created by Gate users during off-hours are flagged `is_provisional = true`. Accounts or Admins must review, populate complete GSTIN details, and toggle off provisional status.

### 3.2 Products Master (`public.products`)
- Fields: Product Code, Name, Product Category (DMT, Prismatic, Enclosed Oval), Unit of Measure (UOM, default: `PCS`), HSN Code (4–8 numeric digits).
- Products are linked to categories to control condition grading workflows (BR-11).

### 3.3 Inventory Locations (`public.inventory_locations`)
- Key Locations:
  - `GATE_STAGE`: Unboxed stock prior to custody handover.
  - `INTERMEDIATE_STORE`: Sahil's verified functional/repaired staging area.
  - `BATTERY_STORE`: Stores CR2032 coin batteries for technician servicing.
  - `NON_FUNCTIONAL_STORE`: SPM's holding area for defective stock awaiting dismantling.
  - `HAZARD_QUARANTINE`: Segregated storage for mercury-contaminated units.
  - `SCRAP_DISPOSED`: Terminal output location for manifested scrap.
  - `MAIN_STORE`: Central company warehouse.

---

## 4. Option Sets & The Critical "NO → YES" Warning

### 4.1 Safe Option Relabeling (G-18)
- Navigating to **Admin Panel** → **Option Sets** allows modifying the display text of options (e.g., changing "DIRTY" to "DIRTY / SURFACE SOIL").
- Because historical Goods Slips pin their exact option snapshot at time of grading, changing option text does **not** corrupt historical data.

### 4.2 The Critical "NO → YES" Compliance Warning
> ⚠️ **CRITICAL COMPLIANCE NOTICE (G-04, G-05, G-12):**
> 
> In RMS, certain conditions are permanently classified as **Not Allowed** (e.g., DMT Other Brands, Broken/Body Damage, Prismatic Mercury Broken, Enclosed Oval Mercury Absent).
> 
> If an administrator attempts to modify a condition disposition from **Disallowed to Allowed (NO → YES)**:
> 1. The system displays a prominent modal alert explaining the regulatory, hazardous material, and financial risks.
> 2. Administrator must re-enter their credentials.
> 3. Administrator must input a mandatory justification reason (minimum 20 characters) which is permanently logged to `config_change_log`.
> 4. An automated high-priority compliance notification (`HAZARD_DETECTED` / `COMPLIANCE_ALERT`) is instantly dispatched to senior management.
> 5. **Note:** Locked System Guards (such as G-05 prohibiting mercury in functional inventory) will reject the operation at the database level even if attempted.

---

## 5. Dynamic Form Builder & Versioning

### 5.1 Form Lifecycle
Dynamic forms (`S1_GATE`, `S1_UNBOX`, `S1_INSPECT_DMT`, `S1_INSPECT_PRS`, `S1_INSPECT_EO`, `S3_TECH_ALLOT`, etc.) follow a strict lifecycle:
- **DRAFT:** Work in progress. Admin can add, reorder, or edit fields, validation rules, and conditional display criteria.
- **PUBLISHED:** The live active version. Only one version per form code can be PUBLISHED at any time.
- **RETIRED:** Historical version. Read-only. Preserved forever so that older Goods Slips render their exact original form structure.

### 5.2 Form Field Configuration
- Field Types: Text, Number, Dropdown, Multi-select, Date, Checkbox, Textarea, File/Photo, Barcode Scan.
- Conditional Rules: Visual rule builder allowing expressions such as `delivery_mode == 'COURIER'` to toggle visibility and mandatory status of docket fields.

---

## 6. Workflow Versions, Steps & SLA Escalations

- Visual Workflow Designer displays step progression:
  1. `S1_GATE` (Gate Inward)
  2. `S1_UNBOX` (Unboxing & Evidence)
  3. `S1_ITEMIZE` (Itemisation)
  4. `S1_INSPECT` (Condition Grading)
  5. `S2_HANDOVER` (Custody Transfer to Intermediate Store)
  6. `S3_TECH` (Servicing & Allotment)
  7. `S4_DISMANTLE` (Parts Recovery)
  8. `S5_STORE_ISSUE` (Issue to Main Store)
  9. `S6_CN_DECISION` (RM Credit Note Decision)
  10. `S6_CN_ISSUE` (Accounts Credit Note Generation)
  11. `S7_CLOSE` (Party Notification & Formal Closure)
- **SLA Timers & Escalations:** Each step can have an SLA duration in hours. When exceeded, the system creates escalation events and notifies supervisors.

---

## 7. Number Series Configuration

Format pattern tokens in **Admin Panel** → **Numbering**:
- `{FY}`: Indian Financial Year (e.g., `2026-27`). Automatically rolls over on April 1st.
- `{YYYY}`, `{YY}`, `{MM}`: Calendar year and month.
- `{SEQ:X}`: Sequential counter zero-padded to `X` digits.

| Series Code | Name | Default Pattern | Rollover Period |
|---|---|---|---|
| `GS` | Goods Slip | `GS/{FY}/{SEQ:5}` | Annual (April 1) |
| `TRANSFER` | Custody Transfer Note | `TRF/{FY}/{SEQ:5}` | Annual (April 1) |
| `TECH_BATCH` | Technician Batch Allotment | `TECH/{FY}/{SEQ:5}` | Annual (April 1) |
| `DISMANTLE` | Dismantling Batch | `DMTL/{FY}/{SEQ:5}` | Annual (April 1) |
| `STORE_ISSUE` | Store Issue Voucher | `ISS/{FY}/{SEQ:5}` | Annual (April 1) |
| `DISPATCH` | Replacement Dispatch | `DSP/{FY}/{SEQ:5}` | Annual (April 1) |
| `CN_GST` | GST Credit Note | `CN-GST/{FY}/{SEQ:5}` | Annual (April 1) |
| `CN_GEN` | General Credit Note | `CN-GEN/{FY}/{SEQ:5}` | Annual (April 1) |
| `JV` | Accounts Journal Voucher | `JV/{FY}/{SEQ:5}` | Annual (April 1) |

---

## 8. Document & Print Template Designer

Administrators can customize HTML/CSS templates for printed vouchers:
1. **Goods Slip Barcode Tag (4" × 2"):** Compact thermal format with QR code, GS number, Party name, Box sequence.
2. **Replacement Slip (A4 / Thermal):** Lists customer return, item actions (Send New/Repaired/CN), and authorized signatures.
3. **Custody Transfer Note (A4):** Handover document with piece counts and dual-signature blocks.
4. **Store Issue Note (A4):** Store replenishment slip for Main Store custody.
5. **Credit Note Summary (A4):** Accounting statement with tax breakdowns, HSN codes, and GST portal status.

---

## 9. Notification Rules & Central Outbox

Manage notifications under **Admin Panel** → **Notifications**:
- **Event Types:** `GS_CREATED`, `MISSING_DOCUMENTS`, `CSR_APPROVAL_REQUIRED`, `HAZARD_DETECTED`, `PENDENCY_OPENED`, `TRANSFER_DISCREPANCY`, `BATTERY_LOW_STOCK`, `CN_DECISION_REQUIRED`, `PRIOR_NOTIFICATION_PENDING`, `DAILY_AUDIT_MISSED`.
- **Channels:**
  - **In-App:** Realtime websocket / polling alert bar and notification center.
  - **Email:** Dispatched via configured SMTP server (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`).
  - **SMS / WhatsApp:** Webhook integration for outbound party messages.
- **Outbox Engine:** Notifications are written transactionally with business events (`notification_events` table) and dispatched asynchronously by the background worker, guaranteeing zero lost notifications.

---

## 10. Provisional Business Decisions (DEC-01 … DEC-34 Toggles)

The master plan defines 34 business ambiguities resolved provisionally. Administrators can adjust these toggles in `system_settings`:

| Decision ID | Topic | Admin Config Key / Setting | Default Value | Notes |
|---|---|---|---|---|
| **DEC-01** | GS Number Pattern | `number_series.GS.pattern` | `GS/{FY}/{SEQ:5}` | Configurable starting sequence. |
| **DEC-02** | Gate State/Station | `party_state_station_autofill` | `true` | Allows audited manual override at gate. |
| **DEC-03** | Missing Document Flow | `require_rm_missing_doc_approval` | `true` | RM exception required if no doc attached. |
| **DEC-04** | Max Video File Size | `upload_max_video_bytes` | `1073741824` (1 GB) | Resumable chunked upload. |
| **DEC-05** | Video Retention Period | `video_retention_days` | `0` (Indefinite) | Days before archival. |
| **DEC-06** | Shortage Logging | `auto_log_document_shortage` | `true` | Document Qty − Received Qty. |
| **DEC-07** | Shortage Inspection | `inspect_shortages_separately` | `false` | Inspects received pieces only. |
| **DEC-08** | CSR Whole Consignment | `csr_enforce_entire_gs` | `true` | CSR applies to all lines in GS. |
| **DEC-09** | Disallowed Dispositions | `disallowed_action_mapping` | JSON Map | Routes Other Brands vs Body Damage. |
| **DEC-10** | Mercury Quarantine | `auto_route_mercury_quarantine` | `true` | Strict isolation (G-05). |
| **DEC-11** | Scrap Disposal Manifest | `require_scrap_manifest` | `true` | Mandates manifest before disposal. |
| **DEC-12** | Extraction Containers | `default_dmt_containers` | `["BIN-01"..."04"]` | Seeded container list. |
| **DEC-13** | CN Decision Revision | `allow_rm_action_revision` | `true` | Requires deviation reason. |
| **DEC-14** | Skip Tech for Sellable | `skip_technician_for_sellable` | `true` | Visually perfect DMT skips tech. |
| **DEC-15** | Battery Deduction | `auto_deduct_battery_stock` | `true` | Deducts from `BATTERY_STORE` (G-10). |
| **DEC-16** | Allotment Batching | `servicing_batch_max_size` | `50` | Maximum units per technician batch. |
| **DEC-17** | Permanent Scratches | `treat_scratches_as_non_sellable`| `true` | Moves to Non-Sellable store. |
| **DEC-18** | Dismantling Eligibility | `category_supports_dismantling` | `["DMT"]` | DMT only; Prismatic requires disposal. |
| **DEC-19** | PCB Metadata | `mandate_pcb_model_and_supplier` | `true` | Enforces Guard G-11. |
| **DEC-20** | Department Master | `departments_catalogue` | 5 Depts | Seeded reference list. |
| **DEC-21** | Replacement Dispatch | `require_dispatch_tracking_no` | `true` | Mandates carrier details. |
| **DEC-22** | GST Portal Proof | `require_gst_portal_screenshot` | `false` | Optional audit attachment. |
| **DEC-23** | General CN Repaired | `enforce_general_cn_for_repaired`| `true` | Enforces BR-35 tax compliance. |
| **DEC-24** | Historical Rate Cap | `enforce_historical_rate_ceiling`| `true` | Enforces Guard G-14. |
| **DEC-25** | Prior Party Notice | `block_closure_without_notice` | `true` | Enforces Guard G-15. |
| **DEC-26** | Closure Re-opening | `allow_super_admin_gs_reopen` | `true` | Audited Super Admin override only. |
| **DEC-27** | SLA Escalation Schedule| `escalation_check_cron` | `*/15 * * * *` | Runs every 15 minutes. |
| **DEC-28** | Daily Audit Cutoff | `daily_audit_cutoff_time` | `09:00` | Flags missed audit after 9 AM. |
| **DEC-29** | Print Reprints Marking | `watermark_reprinted_vouchers` | `true` | Watermarks "DUPLICATE / REPRINT". |
| **DEC-30** | Audit Retention | `audit_log_retention_years` | `8` | Exceeds 7-year statutory rule. |
| **DEC-31** | Container Barcodes | `enforce_scanned_container_barcodes`| `true` | Verifies container barcodes. |
| **DEC-32** | Gate Camera Upload | `enable_direct_camera_capture` | `true` | Uses HTML5 Media Capture API. |
| **DEC-33** | Auto Notification Text | `auto_compose_party_message` | `true` | Prefills party SMS/email. |
| **DEC-34** | Technician Master | `technicians_catalogue` | `["Raj Kumar Ji"]`| Technician master list. |

---

## 10a. Item Field Profiles (change plan 2026-11-12 Phase 4)

**Admin → Item Field Profiles.** Pick a Category, optionally a Sub-Category, optionally a Product.
Tabs: **Categorisation** (quantity buckets + item counts such as Packaging / Container / User Manual),
**Departments** (routing destinations), **Actions** (final RM actions).

- **Rule:** for each group, the most specific level that has its own fields wins
  (Product > Sub-Category > Category). Levels without their own fields show the inherited fields greyed.
- **Override here** copies the inherited fields to this level for editing; **Use inherited** removes the
  override. Untick *Included* to exclude a field (an override with only exclusions gives no fields).
- **Create new field** adds a label to the library; its code is generated once and never changes.
  Flags: buckets / departments can be *Wastage* or *Goes to RM routing*; actions can need CN or challan
  details (used by Accounts entry in a later phase).
- Every saved change creates a new **config version**; a goods slip keeps the version it was categorised
  under. Guards (G-05 hazard lock, G-07, G-18) are shown read-only and cannot be changed here.

## 11. System Guards (G-01 … G-18) Reference

Administrators must understand that **System Guards cannot be toggled off**:

- **G-01 (Valid GS Number):** Every transaction must link to an authenticated, sequentially numbered Goods Slip.
- **G-02 (Mandatory Unboxing Evidence):** Video clip and categorized document photos are strictly required before Step-2 itemisation.
- **G-03 (CSR RM Approval):** Complete Sales Returns cannot bypass Replacement Manager approval.
- **G-04 (Segregation Purity):** Non-functional or disallowed conditions can never enter functional inventory locations.
- **G-05 (Hazardous Quarantine):** Mercury-broken pieces must route to `HAZARD_QUARANTINE` and can only exit via manifest disposal.
- **G-06 (EO Full Opening):** Enclosed Oval grading is locked until physical opening checkbox is verified.
- **G-07 (Extraction Conservation):** Extracted packaging and container pieces must exactly balance received quantity.
- **G-08 (Pending BP Transfer Lock):** Units on Pending hold cannot be transferred to intermediate store.
- **G-09 (Custody Synchronicity):** Digital ledger movements require physical handover acceptance; discrepancies freeze transfer.
- **G-10 (Exact Battery Deduction):** Every technician battery installation deducts exact inventory from `BATTERY_STORE`.
- **G-11 (Mandatory PCB Metadata):** Dismantled PCBs must record model code and vendor name.
- **G-12 (Salvaged Separation):** Recovered dismantled parts remain in spare parts custody; cannot enter functional store.
- **G-13 (GST CN Compliance):** GST Credit Notes are refused if portal is unreflected; JV is enforced.
- **G-14 (Rate Verification):** Credit note line rates cannot exceed verified historical purchase/sale rates.
- **G-15 (Pre-Closure Notification):** A Goods Slip cannot close until prior customer notification is recorded.
- **G-16 (Idempotency Header):** Financial and stock mutating APIs require unique `Idempotency-Key` headers.
- **G-17 (Audit Immutability):** Operational audit logs and user activity records are insert-only (updates and deletes prohibited).
- **G-18 (Historical Configuration Safety):** Form and option changes pin new versions; historical records remain immutable.
