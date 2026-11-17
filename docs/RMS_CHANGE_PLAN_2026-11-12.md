# RMS Change Plan — 12-11-2026

**Purpose:** a working file for the 2026-11 change request (Offline/E-commerce gate entry, cartons,
item-level categorisation, admin-configurable categorisation/department/action fields, department
round-trips, A/c Actions PDF, Dispatch Slip). Each phase below ends in a **ready-to-paste prompt** for
Claude Code. Run phases **in order**. Tick a phase only after its Definition of Done (CLAUDE.md §k) passes.

**Status legend:** `[ ]` not started · `[~]` in progress · `[x]` done (checks green)

---

## 0. Where the repository stands today (inspected 2026-11-12)

| Area | Current state | Gap vs. this change request |
|---|---|---|
| Parties | 2,080 parties imported with `state_id` + `station_id` (`backend/scripts/import_parties.py`, `supabase/seed_parties.sql`). 558 rows failed (`party_import_exceptions.csv`, mostly "Station not found under state"). | Gate form must filter parties by **State + Station**, with a fallback when a station has no parties. The 558 exception rows still need their stations created and the parties imported. |
| Products | 315 products imported. `products.category_id` only (DMT 28, PRISMATIC 13, ENCLOSED_OVAL 3, GENERAL 271). Review list: `product_import_review.csv` (columns: Item Name, Category). | There is **no Sub-Category** level. The CSV with Item / Category / Sub-Category is **not in the repo yet**. |
| Gate (P2-02) | `goods_slips` has `box_count`, a single `gate_document_code` (CHALLAN/INVOICE/LR_BILITY/DELIVERY_NOTE/NO_DOCUMENT/OTHER), and delivery mode. | Needs Return Type (Offline / E-commerce), Gate Entry Date (backdate allowed), Gate Entry Number (numeric), **Carton No.** instead of Box No., **multiple document rows** including **Courier Slip**. |
| Unboxing (P2-03) | Video is mandatory per box (Requirement B, 2026-11-10). Documents are classified. An Accounts alert exists (migration `20261110000100_accounts_gate_doc_notification.sql`). | Rename to Carton Opening with one video per carton. Alert Accounts on Invoice/Debit Note at **both** gate and carton opening. |
| Itemisation / categorisation (P2-04/05) | Items are counted against documents. Categorisation is **GS-wise** (CSR/RO). Condition options are set per **category** only. | Needs **item-level quantity buckets** (Good, Damaged, Body Broken, …) configured at Category → Sub-Category → Product. Needs Packaging / Container / User Manual numeric fields. |
| RM actions (P2-07) | `rm_item_actions` with a hard `CHECK` on SEND_NEW / SEND_REPAIRED / ISSUE_CN / NOT_ALLOWED / PENDING_BP. Quantity split is supported. Replacement Slip print page exists. | Actions must be **admin-configurable per level**. The slip must become a real **PDF** ("Replacement Slip – A/c Actions"). |
| Custody / Store (P3-01, P3-05) | Custody transfer engine and Transfer Note print exist. Roles `INTERMEDIATE_STORE_MANAGER` and `MAIN_STORE` exist. | Transfer Slip must be generated automatically when the RM approves categorisation. The GS must show "Held at Intermediate Store". |
| Departments (P3-02/03) | Technician allotment, battery, dismantling, spare-parts ledger. | Needs a generic **Department** round-trip (Mercury Extraction, Repair, Cleaning, Technical Inspection, …) with **quantity reconciliation on return**. Dismantling sub-inventory goes **ON HOLD**. |
| Commercial (P3-06/07) | Credit notes, dispatch, party notifications and closure exist. | Accounts must enter CN No./Date/Value and Challan No./Date per action line, which then produces a **Dispatch Slip**. Party email uses the Accounts values (later phase). |
| Test health | Per PROGRESS 2026-11-12: `pytest` **54 failed / 758 passed / 1 error** (helpers upload 1 video for 3 boxes), plus 2 pgTAP files failing. P1-04/05/06 and P2-07/08 are unticked. | Fix this first (Phase 0) so every later phase has a green baseline. |

Roles in the DB: `GATE_INWARD`, `INWARD_VERIFIER` (Aman), `REPLACEMENT_MANAGER` (Pratham Pratap Singh),
`INTERMEDIATE_STORE_MANAGER`, `MAIN_STORE`, `TECHNICIAN`, `TECHNICIAN_COORDINATOR`, `ACCOUNTS`, `DISPATCH`,
`SPARE_PARTS_MANAGER`, `SPARE_PARTS_TECHNICIAN`, `MANAGEMENT_VIEWER`, `SUPER_ADMIN`.

---

## 1. The target workflow (as requested on 2026-11-12)

```
GATE ENTRY (Gate user)
  Return Type: Offline Return | E-Commerce Return
  [Offline] Gate Entry Date (backdate ok) · Gate Entry Number (numeric)
  State → Station → Distributor (filtered by state + station)
  Carton No. (count of cartons) · Documents: N rows (Invoice / Debit Note / Courier Slip / Hand-written slip / …)
  └─ Invoice or Debit Note present → instant alert to ACCOUNTS (GST input check)
        │
CARTON OPENING (Inward Verifier – Aman)
  Video per carton · more document rows (alert Accounts again on Invoice/Debit Note)
        │
COUNTING (same role) — add items + quantities
        │
CATEGORISATION (same role) — per item, split qty into admin-configured buckets
  + Packaging / Container / User Manual counts (numeric)
        │
RM REVIEW (Replacement Manager – Pratham) — whole GS at a glance; approve or modify anything
        │ approve
TRANSFER SLIP auto-generated → INTERMEDIATE STORE accepts → GS status "Held at Intermediate Store"
        │
RM DEPARTMENT ROUTING — send item qty to departments (Mercury Extraction, Repair, Cleaning, …)
        │
DEPARTMENT RECEIVING (assigned user – Aman) — receive back per head
  e.g. 5 sent to Repair → 4 Repaired + 1 Wastage (or onward to another department)
  GS aggregate qty must always reconcile
        │
RM FINAL ACTIONS — per item, split qty across Send New / Send Repaired / Issue CN / Not Allowed
  → "Replacement Slip – A/c Actions" PDF (printable any time)
        │
ACCOUNTS — CN No./Date/Value (Issue CN) · Challan No./Date (Send New / Send Repaired)
        │
DISPATCH SLIP → Dispatch team issues goods
        │
(Later) Party email built from the Accounts values
```

**On hold for now:** sub-inventory of dismantled items (tip, container, PCB, …), the spare-parts
ledger and dismantling screens. **Hide them with a config flag. Do not delete code or data.**

---

## 2. Decisions to confirm before the phase that needs them

Record each answer in `docs/DECISIONS.md` as a new DEC entry, and in the master-plan addendum (Phase 0).

| # | Question | Proposed default (until you answer) | Needed by |
|---|---|---|---|
| Q1 | A station has **no** parties linked. What should the Distributor list show? | First all parties of the selected **state**, then the full list with search. "Create provisional party" stays available (DEC-02). Configurable. | Phase 2 |
| Q2 | The CSV with **Item / Category / Sub-Category**: what is the file name? | You place it in the repo root as `products_with_subcategory.csv`. Columns: `Item Name,Category,Sub-Category`. | Phase 1 |
| Q3 | The 558 party exception rows: create the missing stations and import them? | Yes. Add the missing stations under their state, then re-import. Rows that still fail stay in the exceptions file. | Phase 1 |
| Q4 | Gate Entry Number: unique overall, unique per year, or free? Is there a limit on how far back the date can go? | Unique per financial year. Date ≤ today, with no lower limit (admin setting `gate.max_backdate_days`, empty = unlimited). | Phase 2 |
| Q5 | E-Commerce Return: which fields differ from Offline? | Same form without Gate Entry Date/Number. Optional marketplace / order ID fields are added only if you list them. | Phase 2 |
| Q6 | Is GS-wise CSR / RO categorisation still needed? | Keep it as the GS **type** (Complete Sales Return / Replacement). Item-level buckets replace product condition dropdowns. | Phase 4 |
| Q7 | PDF generation: server-side PDF or browser "print to PDF"? | **Server-side PDF** (backend, one template per slip) so the file is identical for everyone and can be stored and re-printed. | Phase 7 |
| Q8 | Who receives goods back from departments? | `INWARD_VERIFIER` (Aman). The assignment is configurable per step. | Phase 6 |
| Q9 | Can a department return items to **another** department directly, or must the RM re-route? | Receiver books the qty to an outcome head. Heads like "Send to Mercury Extraction" send it back to the RM routing queue. | Phase 6 |
| Q10 | Which existing modules are "on hold"? | Dismantling, spare-parts ledger, battery consumption, PCB sub-inventory. Container audit stays active. Please confirm. | Phase 0 |

---

## 3. Phases

> **Common footer for every prompt below:** paste it at the end of each prompt.
>
> ```
> Follow CLAUDE.md standing rules (a–k) strictly. Inspect before editing; minimal changes; new
> timestamped migrations only; guards enforced in DB + service with tests; business values from DB
> config (stable codes, never labels); idempotent transactional commands; router→service→repository;
> loading/empty/error/success states; 360px mobile + desktop. Cite the source (AMD-xx / DEC-xx / BR-xx /
> G-xx) in code comments and tests. Finish with the Definition of Done checks and a completion report
> with real command output, and update docs/PROGRESS.md and docs/RMS_CHANGE_PLAN_2026-11-12.md (tick
> the phase).
> ```

---

### Phase 0 — Baseline, requirements addendum, feature hold  `[ ]`

**Goal:** get a green test baseline, record the new requirements formally, and hide the on-hold modules.

**Prompt:**
```
Phase 0 of docs/RMS_CHANGE_PLAN_2026-11-12.md.

1. Fix the existing red tests before any feature work: the 54 pytest failures + 1 error (integration
   helpers upload one video for 3 boxes since Requirement B 2026-11-10) and the 2 failing pgTAP files
   (25 test 14; 27 tests 5–6). Fix the tests/helpers, not the guards. Report before/after counts.
2. Add docs/RMS_MASTER_PLAN_ADDENDUM_2026-11.md recording the 2026-11-12 change request as amendments
   AMD-01…AMD-nn (gate return type + gate entry date/number, carton no., multi-document rows incl.
   courier slip, party filter by state+station, sub-categories, item-level categorisation buckets,
   admin-configurable categorisation/department/action field groups at category/sub-category/product
   level, packaging/container/user-manual counts, RM review → transfer slip → intermediate store hold,
   department routing & receiving with qty reconciliation, RM final actions with qty split, A/c Actions
   PDF, Accounts CN/Challan entry, Dispatch Slip, party email later). Add a short pointer section in
   RMS_DEVELOPMENT_MASTER_PLAN.md to the addendum (do not rewrite existing sections). Add DEC entries for
   the open questions in §2 of the change plan with the proposed defaults marked PROVISIONAL.
3. Feature hold: add an admin setting `features.on_hold` (list of module codes; default: dismantling,
   spare_parts, battery, pcb_subinventory). On-hold modules are hidden from navigation and their
   write endpoints return a standard error envelope (code FEATURE_ON_HOLD). Do not delete code, data or
   migrations. Guards are unaffected.
4. Show me the list of modules/screens that will be hidden before you apply the hold.
```

---

### Phase 1 — Masters: Sub-Categories, product CSV, party/station completion  `[~]`

> **Status 2026-11-12:** steps 1, 2, 4 (safe set) and 5 done and checked. Step 3 tooling done; the
> product data load is **waiting for the full CSV** (`items.csv` is an 8-row sample, not imported).
> Tick `[x]` after the full CSV is imported and the suite is green.

**Goal:** a Category → Sub-Category → Product hierarchy, loaded from your CSV, and complete party/station data.

**Pre-requisite:** put the product CSV (Item Name, Category, Sub-Category) in the repo root (Q2).

**Prompt:**
```
Phase 1 of docs/RMS_CHANGE_PLAN_2026-11-12.md.

1. New migration: table product_subcategories (id, code immutable, name, category_id FK, is_active,
   audit cols, unique(category_id, code)); products.subcategory_id nullable FK with a constraint/trigger
   that the sub-category belongs to the product's category. RLS like other masters.
2. Masters API + Admin UI: CRUD for sub-categories, product edit shows Category → Sub-Category
   (dependent dropdown), CSV import screen supports the Sub-Category column.
3. Extend backend/scripts/import_products.py to read `Item Name,Category,Sub-Category` from
   <CSV FILE NAME IN ROOT>: create missing sub-categories, update existing products' category/
   sub-category by exact name match, insert new products, write exceptions to
   product_import_exceptions.csv. Regenerate supabase/seed_products.sql so `scripts/reset-db.ps1`
   reproduces it. Show me a dry-run summary (new categories, sub-categories, products, updates,
   exceptions) BEFORE writing to the DB.
4. Party exceptions (party_import_exceptions.csv, 558 rows): produce a dry-run listing distinct missing
   (state, station) pairs; after my confirmation add those stations (seed, not hard-coded) and
   re-import the parties; keep remaining failures in the exceptions file. Regenerate seed_parties.sql.
5. Lookup endpoint: GET parties filtered by state_id + station_id (paged, searchable), with fallback
   behaviour per DEC (Q1) as a config setting `gate.party_fallback` = STATE | ALL | NONE.
```

---

### Phase 2 — Gate Entry revamp (Offline / E-Commerce)  `[x]`

> **Status 2026-11-13:** done, Definition of Done checks green (docs/PROGRESS.md). Phase 0 is still `[ ]`
> and Phase 1 `[~]` (full product CSV pending); Phase 2 was run on user request. `box_count` is kept as a
> synced mirror until Phase 3 switches the unboxing / itemisation APIs, then a migration drops it.

**Prompt:**
```
Phase 2 of docs/RMS_CHANGE_PLAN_2026-11-12.md (AMD gate items).

1. Migration on goods_slips: return_type_code (OFFLINE_RETURN | ECOMMERCE_RETURN, option set in config),
   gate_entry_date (date, required for OFFLINE, must be <= current date; backdate allowed, optional
   max from setting gate.max_backdate_days), gate_entry_no (numeric, required for OFFLINE, uniqueness per
   DEC Q4 enforced in DB), rename the business concept Box → Carton: add carton_count (>0) and migrate
   box_count data (keep the old column readable until all code is switched, then drop in a later
   migration). Update G-02 "video per box" to "video per carton" in DB and service.
2. Gate documents: replace the single gate_document_code with a child table gs_gate_documents (many rows
   per GS: document type from option set incl. INVOICE, DEBIT_NOTE, CHALLAN, COURIER_SLIP,
   HANDWRITTEN_SLIP, LR_BILITY, DELIVERY_NOTE, OTHER; doc_no, doc_date, remarks, one or more file
   attachments). Migrate existing rows. "No document" stays a GS-level flag (missing_documentation).
3. Accounts alert: whenever a gate document of type INVOICE or DEBIT_NOTE is saved, notify the ACCOUNTS
   role immediately (reuse the notifications module and the existing accounts_gate_doc rule; make the
   trigger document types configurable).
4. Gate form UI (mobile first): Return Type first; for Offline show Gate Entry Date + Gate Entry Number
   above State and Station; State → Station → Distributor (filtered list from Phase 1, with fallback);
   Carton No.; "Add document" rows (+ / remove) each with type, no., date and file upload. Clean,
   uncluttered layout.
5. Update the GS tag print, GS detail, search and reports where box_count / gate document was shown.
```

---

### Phase 3 — Carton Opening & Counting  `[x]`

> **Status 2026-11-13:** done, checks green (docs/PROGRESS.md). Status list confirmed by the user:
> UNBOXING = Carton Opening, ITEMIZATION = Counting (labels, codes unchanged) + new CATEGORISATION.
> **Open question:** there is no "reopen counting" (CATEGORISATION → Counting) because it is not in the
> requirements; after submit, line changes go through the RM-approved correction. Confirm or ask for it.

**Prompt:**
```
Phase 3 of docs/RMS_CHANGE_PLAN_2026-11-12.md.

1. Rename the Unboxing step to "Carton Opening" in config labels (codes unchanged). One video per
   carton (G-02 as updated in Phase 2), carton-wise progress (Carton 1 of N).
2. Carton opening can add more document rows (same gs_gate_documents model, stage = CARTON_OPENING);
   INVOICE / DEBIT_NOTE again triggers the immediate Accounts alert (no duplicate alert for the same
   attachment).
3. Counting step (same INWARD_VERIFIER role): add items (product search by name/category/sub-category)
   with received quantity; documented qty optional. Save as draft, submit to move to Categorisation.
4. Show me the updated status list for goods_slips before migrating statuses.
```

---

### Phase 4 — Admin Categorisation Engine (Category / Sub-Category / Product)  `[x]`

> **Status 2026-11-13:** done, checks green (docs/PROGRESS.md). Rule: per group the most specific level
> with its own rows wins. A GS is stamped with the profile version when it leaves CATEGORISATION.
> Restricting RM actions to the product's profile is left to Phase 7; bucket/count entry UI is Phase 5.

**Goal:** the most critical piece. Three admin-managed field groups, resolved per product with inheritance.

**Prompt:**
```
Phase 4 of docs/RMS_CHANGE_PLAN_2026-11-12.md.

Build an admin-configurable "item field profile" with THREE field groups:
  a) CATEGORISATION buckets (numeric qty fields) e.g. Good, Damaged, Body Broken, Wastage …
  b) DEPARTMENTS (where goods can be routed) e.g. Mercury Extraction, Technical Inspection, Repair,
     Cleaning …
  c) ACTIONS (final RM actions) e.g. Send New, Send Repaired, Issue CN, Not Allowed …

1. Schema (new migration): a field library per group (code immutable, label editable, sort, active,
   flags such as is_wastage / returns_to_routing / requires_cn / requires_challan for actions), and
   assignment tables mapping field → scope (CATEGORY | SUBCATEGORY | PRODUCT, scope_id) with
   include/exclude and sort order. Resolution rule: PRODUCT overrides SUBCATEGORY overrides CATEGORY
   (most specific scope that has an assignment for that group wins; document the rule). A DB function
   resolves the effective profile for a product; the backend uses only this function.
2. Seed the existing categorisation/condition options and the existing action codes (SEND_NEW,
   SEND_REPAIRED, ISSUE_CN, NOT_ALLOWED; PENDING_BP kept) as library entries so nothing in use breaks.
   Replace the hard CHECK on rm_item_actions.action_code with an FK/validation against the action
   library (codes immutable once used, G-18 label snapshots on transactions).
3. Packaging, Container and User Manual: separate numeric fields recorded per GS item (not buckets),
   enabled per scope in the same profile.
4. Admin UI: one clean screen "Item Field Profiles": pick Category → (optional) Sub-Category →
   (optional) Product; three tabs (Categorisation / Departments / Actions); shows inherited fields
   greyed with "override here" option; create new labels inline. Guards stay read-only.
5. Profiles are versioned (config history); a GS stores the profile version it was categorised under.
```

---

### Phase 5 — Item Categorisation, RM Review, Transfer Slip, Intermediate Store  `[x]`

**Prompt:**
```
Phase 5 of docs/RMS_CHANGE_PLAN_2026-11-12.md.

1. Categorisation (INWARD_VERIFIER, same user who counted): per item, the resolved categorisation
   buckets (Phase 4) as qty inputs + Packaging / Container / User Manual counts. New guard: sum of
   bucket qty = counted qty per item (DB constraint/trigger + service + test). Submit → RM review.
2. RM Review (REPLACEMENT_MANAGER): one-screen GS at a glance — header, documents, cartons/videos,
   every item with counted qty and the qty per bucket; RM can approve, or edit any qty/bucket/item
   (audit + revision kept), or send back with a remark.
3. On approval: auto-generate a Transfer Slip (number from numbering config; uses the existing custody
   transfer engine; printable) handing the goods to INTERMEDIATE_STORE_MANAGER.
4. Intermediate store accepts the transfer (qty check per line) → GS status/label
   "Held at Intermediate Store". All stock moves via rms_move_stock, idempotent.
```

---

### Phase 6 — Department Routing & Receiving with Reconciliation  `[x]`

> **Status 2026-11-13:** done, checks green (docs/PROGRESS.md). DB guard G-20 enforces quantity conservation
> across `counted_qty = in_store + at_departments + outcome_heads + actioned`. One printable DIN (Department Issue Note)
> per routing document with stock moved via `rms_move_stock`. Partial receipts into outcome heads with `returns_to_routing`
> support. Timeline shows sent / received / pending legs with visual G-20 reconciliation meter.

**Prompt:**
```
Phase 6 of docs/RMS_CHANGE_PLAN_2026-11-12.md.

1. RM routing queue: all GSs held at intermediate store; per item/bucket the RM sends qty to the
   departments allowed by the resolved profile (Phase 4). One routing document per department
   (printable issue note), stock moved via rms_move_stock.
2. Department receiving (assigned user, default INWARD_VERIFIER — configurable): receive back per
   routing line into outcome heads (e.g. Repaired, Not Repaired, Wastage, Send to Mercury Extraction…);
   partial receipts allowed; lines can return to the RM routing queue.
3. Reconciliation guard (new G-xx in addendum): for every GS item, qty is always conserved —
   counted = in store + at departments + in outcome heads + actioned. Enforced in DB + service, with a
   per-GS reconciliation panel showing where every piece is now.
4. GS timeline shows each department leg (sent / received / pending).
```

---

### Phase 7 — RM Final Actions & "Replacement Slip – A/c Actions" PDF  `[x]`

> **Status 2026-11-13:** done (docs/PROGRESS.md). New guard **G-21** (split = counted − at departments,
> profile actions only, finalise with nothing at a department, slip immutable / superseded by a
> reasoned revision). G-20 fixed forward (actioned qty drawn from outcome heads first). The GS stays
> *Held at Intermediate Store* after finalise (DEC-45); Phase 8's Accounts queue = GS with a CURRENT
> `ac_action_slips` row; reuse `app/shared/pdf.py` for the Dispatch Slip. Open: DEC-45, DEC-46.

**Prompt:**
```
Phase 7 of docs/RMS_CHANGE_PLAN_2026-11-12.md.

1. RM final actions: per item, split the available qty across the actions allowed by the resolved
   profile (e.g. 10 pcs → 6 Send New, 3 Send Repaired, 1 Issue CN). Guard: sum of action qty = qty
   available for action (reconciled with Phase 6). Revisions kept.
2. Server-side PDF "Replacement Slip – A/c Actions" (per DEC Q7): branding/template from config, GS
   header, party, gate entry details, item × action × qty table, totals, signatures. Stored as an
   attachment with version; RM can re-print any time; print log kept.
3. On finalise, notify ACCOUNTS that the slip is ready.
```

---

### Phase 8 — Accounts Entry & Dispatch Slip  `[x]`

> **Status 2026-11-14:** done (docs/PROGRESS.md). New guard **G-22** (Accounts data only where the
> action flags ask, CN No. per GS, completion freezes entries / slip / RM actions, Dispatch Slip lists
> exactly the shipping lines and is dispatched once; P3-05 dispatch closed for this flow). Module
> `ac_entry` (Accounts queue + entry, Dispatch Slips), PDF template `DISPATCH_SLIP` (series DS), stock via
> `rms_move_stock` per setting `dispatch.returned_goods_location_by_action` (DEC-47). Closure checklist
> fixed forward. **Open (DEC-47):** where retained Send New / Not Allowed pieces go; until answered they
> stay in the intermediate store and block closure. Phase 9 must record PRIOR_INFO_SENT for CN lines.

**Prompt:**
```
Phase 8 of docs/RMS_CHANGE_PLAN_2026-11-12.md.

1. Accounts work queue: GSs with finalised actions. Per action line: Issue CN → CN No., CN Date,
   CN Value (required); Send New / Send Repaired → Challan No., Challan Date (required). Which fields an
   action needs comes from the action flags (Phase 4), not hard-code. Reuse the credit_notes module
   where it fits.
2. When all lines needing Accounts data are complete → generate a Dispatch Slip (PDF, numbered) for
   lines that ship goods; notify DISPATCH.
3. Dispatch team issues goods against the slip (store issue + rms_move_stock), marks dispatched with
   date/docket; GS moves to closure per the existing closure engine.
```

---

### Phase 9 — Party communication (email from Accounts values)  `[x]`

> **Status 2026-11-14:** done (docs/PROGRESS.md). `party_emails` log + settings `party_email.template` / `party_email.delivery`
> (auto-send OFF), preview / send / resend from the party notification screen, Admin -> Notifications -> Party email. A SENT email is
> the BR-38 PRIOR_INFO_SENT record (`EMAIL_SENT`). Without SMTP Accounts records manually from the same values. DEC-48 open.

**Prompt:**
```
Phase 9 of docs/RMS_CHANGE_PLAN_2026-11-12.md.

Party email built from the values Accounts entered (CN no./date/value, challan no./date, dispatch
details) using the existing party_notifications module and a config template; preview + send +
log; resend allowed. No auto-send until enabled in settings.
```

---

### Phase 10 — Role journeys & UI clean-up  `[x]`

> **Status 2026-11-14:** done (docs/PROGRESS.md). Menu per role from `journey_steps` / `role_journey_steps` (Admin →
> Role Journeys), `GET /me/journey` with count + next GS per step, My Work = landing page, on-hold modules hidden via
> `features.on_hold` (navigation only; Phase 0 step 3 `FEATURE_ON_HOLD` endpoints still open), admin collapsed, one primary
> action. AMD-22, DEC-49 (PROVISIONAL).

**Prompt:**
```
Phase 10 of docs/RMS_CHANGE_PLAN_2026-11-12.md.

1. Role-based "journey" navigation: each role sees only its own menu, ordered as its working journey
   (where a GS starts for them → where it ends), with a "My Work" home showing counts per step and the
   next GS to act on. Menus come from DB config (role ↔ step), not hard-coded.
2. Remove clutter: hide on-hold modules, collapse rarely used admin items, consistent page headers,
   one primary action per screen, clear status badges. Verify at 360px and ≥1024px, no console errors.
3. Update docs/USER_GUIDE.md with one short journey per role.
```

---

### Phase 11 — End-to-end gate & UAT  `[x]`

**Prompt:**
```
Phase 11 of docs/RMS_CHANGE_PLAN_2026-11-12.md.

E2E (Playwright) for the full new flow: Offline gate entry with backdated date and multiple documents
(incl. courier slip) → Accounts alert → carton opening (video per carton) → counting → categorisation
→ RM review/approve → transfer slip → store hold → department round-trip with partial outcomes →
RM final actions split → A/c Actions PDF → Accounts CN/challan → Dispatch slip → dispatch. Plus an
E-commerce return path. Every new guard has a rejecting test. Update docs/UAT.md with scenarios and run
scripts/test-all.ps1 -E2E. Report real results.
```

---

## 4. Log

| Date | Phase | Result |
|---|---|---|
| 2026-11-12 | — | Plan created after repository inspection. |
| 2026-11-12 | 1 | `[~]` Sub-categories (migration 20261112000100, AMD-07 composite FK + immutable code), Masters API + Admin UI (Products / Sub-Categories / Categories / Import CSV), `gate.party_fallback` lookup. Stations: 128 added (`seed_stations.sql`), 20 MAPs, 270 parties imported (2,350 total), 288 rows pending decision. Product hierarchy confirmed (existing categories kept); full product CSV pending. |
| 2026-11-13 | 2 | `[x]` Gate form v2: return type, gate entry date/no. (unique per FY, DEC-38), carton count (G-02 per carton in DB + service), gate document rows with files, configurable Accounts alert (AMD-05), State → Station → Distributor. Migrations 20261113000100/0200. pgTAP 486/486, pytest 866 passed / 0 failed, vitest 159/159, browser check 360 + 1280 px clean. |
| 2026-11-13 | 3 | `[x]` Status labels (GS_STATUS) + CATEGORISATION; workflow v2 labels; carton-opening document rows with Accounts alert (no duplicates); carton progress; Counting draft → submit → Categorisation; product search by category / sub-category. Migration 20261113000300. pgTAP 497/497, pytest 871 passed / 2 failed (1 known data-dependent, 1 ordering flake passing 3/3 alone), vitest 159/159, browser check 360 + 1280 px clean. |
| 2026-11-13 | 4 | `[x]` Item field library (4 groups) + scope assignments + DB resolver + insert-only versions (G-18) + GS version stamp; `gs_item_counts` (AMD-11); `rm_item_actions` CHECK → FK + label snapshot (AMD-16); Admin → Item Field Profiles. Migration 20261113000400. pgTAP 533/533, pytest 879 passed / 2 failed (1 known data-dependent, 1 Phase 3 ordering assertion fixed), vitest 164/164, browser 360 + 1280 px clean. |
| 2026-11-13 | 7 | `[x]` RM final actions (`final_actions` module, G-21 DB + service), server-side A/c Actions PDF (reportlab, template `AC_ACTIONS_SLIP`, series RSA, stored as GENERATED_PDF, versions + print log), Accounts notified by rule; G-20 fixed forward. Migration 20261113001100. pgTAP 611/611, pytest 893 + re-run of 9 (1 known data-dependent fail), vitest 184/184, browser 360 + 1280 px clean. |
| 2026-11-14 | 8 | `[x]` Accounts entry per action line (fields from `requires_cn` / `requires_challan`), completion → numbered Dispatch Slip PDF (DS series) + DISPATCH notified, dispatch with DEC-26 data via `rms_move_stock`, GS → closure engine; G-22 DB + service; checklist fix-forward. Migration 20261114000100. pgTAP 638/638, pytest Phase 8 7/7 (full run in PROGRESS), vitest 193/193, browser 360 + 1280 px clean. DEC-47 open. |
| 2026-11-14 | 9 | `[x]` Party email from the Accounts values (AMD-20): `party_emails` (frozen content, final status, completed-slip source; DB triggers), EMAIL_SENT PRIOR_INFO_SENT, templates + auto-send in settings (OFF), worker retry, Admin Party email tab. Migration 20261114000200. pgTAP 656/656, pytest Phase 9 8/8 (full run in PROGRESS), vitest 203/203, browser 360 + 1280 px clean with real SMTP delivery. DEC-48 open. |
| 2026-11-14 | 10 | `[x]` Role journeys: catalogue + role ↔ step config (migrations 20261114000300/0400, seed 51 rows), `journeys` module (`/me/journey`, queue list, admin config with change log), config-driven sidebar with counts, My Work journey board + queue view, Admin → Role Journeys, `features.on_hold` hides Dismantling / Scrap / Batteries, UI declutter (single primary action, PageHeader, 360px topbar). pgTAP 670/670, pytest 927 passed / 2 failed (known data-dependent + log-order flake, passes alone), vitest 207/207, browser 360 + 1280 px clean for 9 roles. DEC-49 open. |
| 2026-11-14 | 11 | `[x]` E2E Playwright full new flow (`tests/e2e/phase11_new_flow.spec.ts`): L-09 Offline return with backdated date, multi-docs, Accounts alert, carton opening (video per carton), counting, categorisation, RM review/approve, transfer slip, store hold, department round-trip, RM final actions, A/c actions PDF, Accounts entry, Dispatch slip & dispatch; L-10 E-commerce return without gate date/no to closure; Rejecting tests for G-02 (updated), G-19, G-20, G-21, G-22. Desktop Chrome + Mobile Pixel 7 passed (3/3 passed on both, 0 console errors, 0 overflow, IC-01..IC-12 verified 0 violations). Updated `docs/UAT.md`. |
| 2026-11-17 | 3+5 | DEC-53: Counting (AMD-08) and Categorisation (AMD-09) merged into one Inward Verifier step: split entered per line at counting, one submit → RM Review (send-back stays split-only). See docs/PROGRESS.md. |
