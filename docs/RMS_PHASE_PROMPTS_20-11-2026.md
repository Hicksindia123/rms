# RMS — Phase prompts, 20-11-2026 (Offline Return → Replacement, Steps 1–12)

Source: the user's 12-step OFFLINE RETURN workflow (20-11-2026).
Usage: give Claude Code **one phase at a time, in order**: "Run Phase N of docs/RMS_PHASE_PROMPTS_20-11-2026.md".
Every phase follows `CLAUDE.md` (standing rules a–k). The rules below apply to every phase and are not repeated in each prompt.

---

## 0. Common rules for every phase (Claude must follow these)

1. Read `CLAUDE.md`, this file (the phase plus §1–§3), `docs/DECISIONS.md` (DEC-51 … DEC-59) and `docs/PROGRESS.md` first.
2. **Inspect before editing.** For each item, decide whether to *keep*, *modify*, *rebuild*, *add* or *retire (hide, don't delete)*. Put this list in the completion report.
3. Schema changes go in **new** migrations only (`supabase/migrations/2026112xxxxxxx_*.sql`). Never edit an applied migration. Role grants and journey menus go in `seed.sql` (`_seed_role_matrix`, the journey matrix) **plus** a `supabase/snippets/release_<date>_<topic>.sql` for Supabase Cloud. Never put them in migrations.
4. Labels, options, store names and category→store mappings come from **DB config** and are editable in the Admin Panel. Logic keys off **codes**.
5. Stock moves only through `rms_private.rms_move_stock`. Every command runs in one transaction and takes an `Idempotency-Key`.
6. Every new guard is enforced in the DB **and** in the service, and has a test. Cite the DEC number in code, migrations and tests.
7. **DEC-51 still holds:** no "same user" locks between steps. Any user with the eligible role may act.
8. Retire old behaviour by **deactivating/hiding** (journey steps, options, settings). Never drop tables or history. Legacy GSs already mid-flow must keep working or have a documented migration path.
9. Mobile first: 360 px, no horizontal scroll, touch targets ≥ 44 px. Every screen has loading, empty, error and success states.
10. Local env (memory): `uv` is not on PATH (use `backend/.venv/Scripts/*.exe`). Start Docker Desktop before `supabase`. Use `scripts/reset-db.ps1 -SkipBackup` before browser checks. Delete `%TEMP%\rms-e2e-sessions.json` after a reset. If ports 8000/5173 are busy, use the second stack on 8001/5174.
11. **Do not push, deploy or run SQL on Supabase Cloud.** List the migrations and snippets that production will need in the completion report.
12. Definition of Done = CLAUDE.md §k. Also update `docs/PROGRESS.md`, `docs/DECISIONS.md`, and tick the phase in §4 of this file with a one-line log entry.

---

## 1. Target flow (summary)

| Step | Who | What |
|---|---|---|
| 1 | Gate User (Offline), e.g. Anuj | State → Station → Party, Cartons, Received Through (Courier / Transport / By Hand), optional party documents + transport document → **Submit & Create GS** → summary → **Submit** (or Back) |
| 2a | Replacement Executive (RE), e.g. Aman | Unbox: one video per carton → optional single "document found in carton" (type + photo) → Next |
| 2b | RE | Add items: As per Doc/Party qty + Physically Received qty → Next → popup **Replacement / Complete Sales Return** |
| 2c | RE | Replacement → categorisation window (conditions per product category) → **Lock**. Only Admin/Management can edit afterwards, and only until department routing has started |
| 2d | Replacement Manager (RM) | Pending-for-transfer-slip list (single or multi-select / select all) → **Generate Transfer Slip** (one slip per Intermediate Store, multi-GS combined) **or Send Edit Request** (→ Management + Admin) |
| 3 | Intermediate Store user (OP / DT / RI …) | Acknowledges physical receipt **per transfer slip** |
| 4 | Intermediate Store user | Department routing **per GS**, only for own-category items (toggle "view all items" is read-only) |
| 5 | — | Goods pending at departments |
| 6 | Intermediate Store user | Receives back from departments: sent qty vs received qty, condition after work, per GS |
| 7–8 | Intermediate Store user | Analysis per item + condition: **Allowed → Dispatch New / Dispatch Repaired**, or **Not Allowed** |
| 9 | Any Intermediate Store user → Management | Optional "Send for Management Approval". Management may change any final action to any other (incl. Issue CN), change qty, add/remove lines (mobile) |
| 10 | Management | Any GS with **Issue CN** carries a "Digitally approved by Management" stamp. From here each GS flows on its own |
| 11 | Accounts | GS reaches Accounts only when **every** Intermediate Store has finished analysis for it (and no Management approval is pending) |
| 12 | Accounts | GS-wise **Replacement Slip** → one Challan No/Date, and one CN No/Date/Value only if the GS has Issue CN → **Dispatch Slip** generated → Dispatch dept |

Complete Sales Return is **on hold**: only the choice is recorded (see Q11).

---

## 2. Questions for the user (recommended answer first; phases use it unless you answer otherwise)

Answer by editing the "Answer" column. Blank = recommended.

| # | Question | Recommended | Answer |
|---|---|---|---|
| Q1 | "Replacement Executive": rename the existing Inward Verifier role or create a new one? | **Rename the label** of `INWARD_VERIFIER` to "Replacement Executive" (code unchanged, users keep access) | |
| Q2 | "Management": new role with edit/approve rights? | **New role `MANAGEMENT`** (approver). `MANAGEMENT_VIEWER` stays read-only | |
| Q3 | Intermediate Stores: how to model them? | **One master `intermediate_stores`** (code, name, stock location, role). Seed OP, DT, RI, each with its own role (`ISTORE_OP`, `ISTORE_DT`, `ISTORE_RI`). Admin can rename stores and add new ones | **Yes (user 2026-11-20).** Admin can rename stores and add new ones |
| Q4 | Default category → store mapping? | **OP = ENCLOSED_OVAL + PRISMATIC, DT = DMT, RI = GENERAL + anything unmapped**. Sub-category mapping overrides category mapping | |
| Q5 | Gate "Transport": vehicle number too? | **Transport Name only** (as written) | |
| Q6 | Gate "Return type" field: remove it now that RE chooses Replacement / Sales Return later? | **Remove from the gate form** (gate form v4). The choice moves to the RE popup | **Overridden by Q24 (user 2026-11-20):** the gate field is Offline / E-Commerce and stays. Replacement / Sales Return is the RE popup (P4) |
| Q7 | Party document types | **Invoice, GST Debit Note, Hand Written Slip, No Documents From Party**. Deactivate Delivery Challan. No doc no/date anywhere (image only) | |
| Q8 | Step-2 "Missing document exception" by the RM (guard G-02, DEC-03) — the RM no longer reviews. Keep it? | **Retire the RM exception step** (new DEC). Keep the `missing_documentation` flag and the Accounts alert | **Yes (user 2026-11-20): remove the G-02 RM approval completely**, for all GSs |
| Q9 | Old RM Review screen (DEC-54: RM edits anything) | **Retire it.** The RM only generates transfer slips or sends an edit request. Edits = Admin/Management only | |
| Q10 | Edit by Admin/Management **after** a transfer slip exists but before routing | **Allowed.** Affected slips are voided and must be regenerated by the RM and re-acknowledged. Blocked once any line of the GS is routed | **Yes (user 2026-11-20):** the RM regenerates the slips |
| Q11 | RE picks "Complete Sales Return" today | **Record it** (`return_type = SALES_RETURN`). The GS parks in status `SALES_RETURN_HOLD` (visible in lists, no further steps) until that journey is built | **Yes (user 2026-11-20)** |
| Q12 | When is the inward stock booked? | **At categorisation lock** into Inward Staging. Transfer slip = stock "in transit". **Store acknowledgement** moves it into that store's location | **Yes (user 2026-11-20).** The acknowledging store is the **Intermediate Store the slip is addressed to** (OP / DT / RI …), not the fresh-inventory / Main Store. P0 must write this out in the audit doc and DECISIONS: stock path Inward Staging → transit → that Intermediate Store's location. Fresh/new stock for "Dispatch New" comes from the Main Store later |
| Q13 | Store acknowledgement: partial or short receipt allowed? | **Full acknowledgement only** + optional remark. A "Report discrepancy" sends an alert to RM + Management (no qty change) | |
| Q14 | Routing: keep the separate "Store Manager issues (DIN)" step (DEC-55)? | **No.** The store user's routing *is* the issue (DIN printed, stock store → department location). "Issue to Store / no-work" lines go straight to analysis | |
| Q15 | Analysis options: what happens to the old PENDING and ISSUE_CN? | **Store user sees only Dispatch New, Dispatch Repaired, Not Allowed.** ISSUE_CN only by Management. PENDING retired for new GSs (legacy rounds keep working) | |
| Q16 | Piece destinations (DEC-57) | **Keep:** Not Allowed → Rejected Hold; Dispatch New → old piece to Non-Functional Store; Dispatch Repaired → dispatched; Issue CN → credited | |
| Q17 | "Digitally signed by Management" means? | **System e-approval stamp:** approver name, role, timestamp and a SHA-256 hash of the approved GS snapshot, printed on GS / Replacement Slip / Dispatch Slip and verifiable in-app. Not a PKI/DSC certificate | **Yes (user 2026-11-20):** non-official, non-legal; built with system logic and code only |
| Q18 | Is Management approval **mandatory** for Issue CN? | **Yes, by construction**: only Management can set Issue CN, and doing so is the signed approval | |
| Q19 | Accounts: one Challan + one CN **per GS** replaces today's per-line entry? | **Yes, per GS** (as written). Old per-line data stays readable | |
| Q20 | Transfer slip print | **A4 PDF** (existing `app/shared/pdf.py`), HICKS logo header, also viewable on screen | |
| Q21 | P11: GS where everything is Not Allowed (no challan, no CN) | — | **User 2026-11-20: keep the GS on HOLD** (no Accounts entry, GS stays open) |
| Q22 | Email alerts | — | **User 2026-11-20: deferred.** The user will define email setup for all steps later. Build in-app alerts only for now |

Questions not answered on 2026-11-20 (Q1, Q2, Q4–Q7, Q9, Q13–Q16, Q18–Q20) use the recommended answer, marked PROVISIONAL.

**New questions from the P0 audit (2026-11-20)** (see `docs/RMS_FLOW_AUDIT_20-11-2026.md` §0). All answered by the user on 2026-11-20:

| # | Question | Recommended | Answer |
|---|---|---|---|
| Q23 | Gate Entry Date + Gate Entry No. (DEC-38) are mandatory today for offline returns (DB CHECK, unique per FY), but they are not in the Step 1 list. Keep them on gate v4? | **Keep them** (required, as today) until you say otherwise | **Keep (user 2026-11-20)** |
| Q24 | The gate "Return type" field today is **Offline / E-Commerce** (not Replacement / Sales Return). Removing it (Q6) means every v4 GS is an Offline Return. Is E-Commerce out of scope for this flow? | **Yes**: v4 stamps OFFLINE_RETURN; E-Commerce returns are a later journey | **User 2026-11-20: keep both Offline and E-Commerce on the gate** (E-Commerce journey built later). This overrides Q6: the Return Type field **stays** on gate v4 |
| Q25 | Guard G-02 also requires at least one classified **document photo** at unboxing when the party sent documents. Step 2a says the carton document is optional. Drop that requirement too, so G-02 = "a video for every carton" only? | **Yes, drop it** (DEC-63 b) | **Yes (user 2026-11-20)** |
| Q27 | (P3 report) The gate recorded "No Documents From Party", then a document turns up in a carton. Clear the tag? | Keep the gate record | **User 2026-11-20: yes, clear it** when a carton document is recorded at unboxing (restored if that document is removed during unboxing). Built in migration 20261120000400 |
| Q28 | (P3 report) Revoke the RM's `unboxing.approve` (only used by the retired exception)? | Revoke | **User 2026-11-20: yes** |
| Q26 | HICKS logo on the Transfer Slip / Replacement Slip / Dispatch Slip PDFs: no logo file exists in the system, and the PDF code cannot draw images yet. Can you supply the logo (PNG/SVG)? | Upload it in Admin → Branding. Until then the PDFs show the company name in text | **User 2026-11-20: use the logo file in the repo root** (`PNG LOGO HICKS.png`, 214×76 PNG) in the PDFs |
| Q29 | (P6 report) A GS on slips of several stores: may a store start routing (P7) once its own slip is acknowledged, before the other stores acknowledge? | Yes, per store | **User 2026-11-21: yes**, each Intermediate Store starts its work after its own acknowledgement |
| Q30 | (P6 report) Name of the new GS status STORE_ACKNOWLEDGED | "Acknowledged by Store" | **User 2026-11-21: confirmed** |
| Q31 | (P6 report) The STORE_ROUTING task has no screen until P7 | P7 handles it | **User 2026-11-21: P7 handles it** |
| Q32 | (P7 report) A store user saved a routing line by mistake (e.g. "Issue to Store" instead of Cleaning). May the store undo it? Today it cannot: issued pieces come back only through receiving (P8) | **Allow undoing a "no work" line** until that piece is analysed (P9); issued lines come back through P8 | **User 2026-11-21: accepted** (built in the P7 follow-up: migration 20261121000400; P9 must close the undo once a piece is analysed) |
| Q33 | (P7 report) The old menus "Department Routing" (RM plan) and "Department Issue" (Store Manager) only list legacy goods slips held at the old Intermediate Store. Hide them? | **Hide them once no legacy goods slip is left** (the P7 release snippet prints the count) | **User 2026-11-21: yes** (seed hides them; snippet `release_20261121_p7_hide_legacy_routing_menus.sql` hides them only when no legacy GS is left) |
| Q34 | (P8 report) The department outcome "Return to RM Routing Queue" now sends the pieces back to the Intermediate Store's own routing (the RM no longer routes). Rename it? | **"Return for Re-routing"** (code RE_ROUTE unchanged; built in the P8 seed + snippet, editable in Admin) | **User 2026-11-23: left to Claude → keep "Return for Re-routing"** (already built) |
| Q35 | (P9 report) After a store submits its analysis, may it reopen its own submission (before every store has submitted)? | **No**; only Management changes it (P10) | **User 2026-11-23: no, only Management** (as built: submissions are append-only, the store branch refuses a submitted store) |
| Q36 | (P9 report) May a store send the GS for Management approval before it submitted its own analysis? | Allowed (as first built) | **User 2026-11-23: the store submits its own analysis first, then sends for Management approval.** Built in migration 20261123000200 (DB + service; button only after the store's submission) |

---

## 3. Current system vs target (checked in Phase 0 on `main` @ c1f3b82, 2026-11-20; details in `docs/RMS_FLOW_AUDIT_20-11-2026.md`)

| Area | Today (corrected in P0) | Action |
|---|---|---|
| Gate form | `S1_GATE_INWARD` v3 PUBLISHED (the number is `max+1` at seed time). `DELIVERY_MODE` = COURIER_PARCEL / DIRECT_TRUCK (vehicle + transporter; DB CHECK `goods_slips_truck_fields` requires both) / SELF_PARTY_REP. `gs_gate_documents` CHECKs: INVOICE / DEBIT_NOTE / DELIVERY_CHALLAN need doc no + date, HANDWRITTEN_SLIP needs remarks; other types (COURIER_SLIP already exists) need nothing. `source_step` S1_GATE / S1_UNBOX already exists. **The gate "Return type" is Offline / E-Commerce (`return_type_code`, drives Gate Entry No./Date, DEC-38), not Replacement / Sales Return.** No confirm step before create | **Modify** → v4 (P2, DEC-62; Q23, Q24) |
| Unboxing | Per-carton video (`box_no`) + `CartonDocumentsSection` (carton docs = `gs_gate_documents` with `source_step` S1_UNBOX). **G-02 = video per carton + ≥1 classified doc photo, or an APPROVED RM missing-doc exception** (setting `require_rm_missing_doc_approval` does not exist) | **Modify** (single typed doc, image only); G-02 changed by DEC-63 (Q8, Q25) |
| Counting + categorisation | Merged (DEC-53), split per line, submit → RM_REVIEW, no stock booked at submit. Replacement / Sales Return already exists as `goods_slips.category_code` RO / CSR (`RETURN_CATEGORY`, DEC-40), left NULL by the DEC-53 path. **Option set `RETURN_TYPE` is taken (Offline / E-Commerce)** | **Modify**: items screen → popup (sets `category_code`; no new RETURN_TYPE codes) → categorisation screen → lock (DEC-64) |
| RM Review | RM edits anything (DEC-54); approval books stock into INWARD_STAGING and starts a custody transfer (`goods_slips.transfer_slip_id` → `custody_transfers`, 1 GS : 1 slip, enforced in the service only). The GS stays RM_REVIEW until the store accepts | **Retire** edits. **Rebuild** transfer slips (many GS : many slips, per store), each backed by a custody transfer because of G-09 (DEC-65) |
| Intermediate Store | One location `INTERMEDIATE_STORE` (class **FUNCTIONAL**; no INTERMEDIATE_STORE class exists), one TRANSIT location, role `INTERMEDIATE_STORE_MANAGER` (also custodian of all DEPT_* locations), STORE_ACCEPT / DEPT_ISSUE. Code `INTERMEDIATE_STORE` hard-coded in 7 modules | **Rebuild** as N stores mapped to categories (DEC-61) |
| Routing | RM plans per item + current condition (DEC-55), Store Manager issues (DIN). DEC-59 departments per category (applied by migration only; a fresh reset keeps the workbook masters). Allowed department checked against the **live** profile | **Modify**: actor = store user, own categories only, no separate issue; check the pinned profile (DEC-67) |
| Receiving | Inward Verifier (setting `department.receiving_role`) records outcome + condition after work (DEC-56) | **Modify**: actor = store user (DEC-68) |
| Final actions | RM, per item + condition, PENDING_BP ("Pending") / NOT_ALLOWED / SEND_NEW / SEND_REPAIRED / ISSUE_CN, rounds (DEC-57). The backend inserts `ac_action_slips` on finalise (no trigger); stock is settled at Accounts completion / dispatch | **Modify**: actor = store user, 3 options; Management any-to-any (DEC-69, DEC-70) |
| Management | `MANAGEMENT_VIEWER` view + export only. No approval / stamp feature. `ApprovalsPage` is the RM's inbox (CSR, corrections, missing-doc exceptions) | **Add** `MANAGEMENT` role + approval module + e-approval stamp (DEC-60, DEC-70) |
| Accounts | `ac_action_slips` + `ac_entry_lines` (CN/challan per line, per round) + `dispatch_slips` (in module `ac_entry`, PDF + sha256). `pdf.py` cannot draw a logo | **Modify**: per-GS entry, gate on all stores done, rename slip to "Replacement Slip" (DEC-71; Q26) |


**P0 corrections to the phase prompts below** (the DECs take precedence over the prompt wording):
- P1 item 2: store locations use location class `FUNCTIONAL`. There is no `INTERMEDIATE_STORE` class (DEC-61).
- P2 target + item 3: **do not remove the Return Type field** (Offline / E-Commerce) and keep its validation and Gate Entry No./Date for Offline (Q23, Q24, DEC-62). The E-Commerce journey is built later.
- P5 / P11 PDFs: draw the HICKS logo from `PNG LOGO HICKS.png` (repo root): add image support to `app/shared/pdf.py`, store the file as the branding logo, and turn on `show_logo` for the Transfer Slip, Replacement Slip and Dispatch Slip templates (Q26, DEC-65).
- P3 item 2: G-02 also loses its "≥1 classified document photo" part (DEC-63 b, Q25).
- P4 item 2: the popup writes `goods_slips.category_code` RO / CSR (option set `RETURN_CATEGORY`), not new `RETURN_TYPE` codes (DEC-64).
- P5 stock: each transfer slip is backed by one `custody_transfers` row (G-09 allows TRANSIT only through a custody transfer) (DEC-65).
- P7: check the allowed department against the GS's pinned profile version. Tests must apply the DEC-59 masters themselves (fresh reset = workbook masters).

---

## 4. Phases

Status: `[ ]` todo · `[~]` in progress · `[x]` done.

| Phase | Title | Status | Log |
|---|---|---|---|
| P0 | Audit & decisions | [x] | 2026-11-20: `docs/RMS_FLOW_AUDIT_20-11-2026.md`; DEC-60…DEC-71 + supersession map; §3 corrected; Q23–Q26 added; baseline recorded (no code changed) |
| P1 | Roles, Intermediate Stores, category mapping | [x] | 2026-11-20: migration 20261120000100, module `intermediate_stores`, Admin → Intermediate Stores, roles MANAGEMENT / ISTORE_*, snippet release_20261120_roles_intermediate_stores.sql; all checks pass except the 3 P0 pre-existing pytest failures |
| P2 | Step 1 — Gate entry v4 + confirm summary | [x] | 2026-11-20: migration 20261120000200 (doc_source, image-only rows, truck = transporter only), gate form v4 + GATE_TRANSPORT_DOCUMENT via seed + snippet release_20261120_gate_v4.sql, v4 service rules, summary sheet + upload progress / retry / remove; Return Type and Gate Entry kept (Q23, Q24); uploads stay right after create (open question) |
| P3 | Step 2a — Unboxing + carton document | [x] | 2026-11-20: migration 20261120000300 (G-02 = video per carton only, DEC-63; one image-only CARTON document per GS, allowed without party documents; exception table read-only, legacy GSs released), snippet release_20261120_p3_unboxing.sql (RM unboxing.approve revoked, exception rules off), Next → item screen; exception endpoints / Approvals section / ExceptionDecisionCard removed |
| P4 | Step 2b/2c — Items, Replacement/Sales-Return popup, categorisation lock, Admin/Management edit | [x] | 2026-11-20: migration 20261120000500 (PENDING_TRANSFER_SLIP + SALES_RETURN_HOLD, lock stamp, status chain, post-lock edit window = itemization.configure until first routing, G-19 at commit, removed-line history, event types), snippet release_20261120_p4_categorisation_lock.sql (status labels, RO = "Replacement", MANAGEMENT configure, RM_REVIEW menu off, rules); popup + lock + Management edits; RM edits and DEC-53 submit retired; Q10 slip voiding moves to P5 |
| P5 | Transfer slips (RM, multi-GS, per store) + Edit Request | [x] | 2026-11-21: migration 20261121000100 (slip tables, status TRANSFER_SLIP_GENERATED, guards, `{STORE}` numbering, TRANSFER_SLIP template, logo), module `transfer_slips`, snippet release_20261121_p5_transfer_slips.sql; one slip per store backed by a custody transfer (G-09); Edit Request; post-lock edit voids the live slips (Q10). **P6 must extend the void to ACKNOWLEDGED slips** |
| P6 | Step 3 — Store acknowledgement | [x] | 2026-11-21: migration 20261121000200 (status STORE_ACKNOWLEDGED, store guards, discrepancy table, slip-backed custody rules, void of acknowledged slips via a TRANSFER_SLIP_VOID return), snippet release_20261121_p6_store_acknowledgement.sql (store grants, Acknowledge Transfer Slips menu, STORE_ACCEPT hidden, rules); store users see only their slips; acknowledge in full / report discrepancy; STORE_ROUTING task per GS for P7 |
| P7 | Step 4–5 — Department routing by store user | [x] | 2026-11-21: migration 20261121000300 (status STORE_PROCESSING, `store_id` on plan lines / DINs, store-scoped DB guards, pinned-profile departments, per-store progress function), snippet release_20261121_p7_store_routing.sql (store_routing grants, "Department Routing" menu, status label); the store user routes its own lines per condition, saving = issue (DIN, stock store → department), "Issue to Store" moves no stock; other stores' items read-only behind a toggle. Follow-up (user Q32, Q33): migration 20261121000400 (store undoes its own "Issue to Store" line until analysed; edit window stays closed), legacy RM routing / Store issue menus hidden |
| P8 | Step 6 — Receiving back by store user | [x] | 2026-11-21: migration 20261121000500 (store_routing.edit; receipt guard = user of the routing's store while STORE_PROCESSING; "back to the store" = that store's location; journey step STORE_DEPT_RECEIVING, queue STORE_RECEIVING), snippet release_20261121_p8_store_receiving.sql (store grants + menu, RE_ROUTE relabel, DEPT_RECEIVING hidden when no legacy DIN is open); "Receive from Departments" per GS / department, partial receipts, return-to-routing reopens the store's routing task; per-store READY_FOR_ANALYSIS for P9 |
| P9 | Step 7–8 — Analysis (Allowed / Not Allowed) | [x] | 2026-11-23: migration 20261123000100 (status ANALYSIS_COMPLETED, store_analysis permission, store branch of the rm_item_actions guard: own store, ready, not submitted, no ISSUE_CN / PENDING_BP; gs_store_analyses submissions with G-21; gs_management_approval_requests; journey step STORE_ANALYSIS), snippet release_20261123_p9_store_analysis.sql (grants, "Analysis" menu, "Dispatch New Piece" / "Dispatch Repaired Piece" labels, alerts); each store decides per item + condition and submits its part; the last store completes the GS; no stock moves at analysis (settled in P11); Send for Management Approval recorded for P10. Follow-up (user Q35 / Q36): migration 20261123000200 — a store sends for Management approval only after its own submission; reopening a submission stays Management-only |
| P10 | Step 9–10 — Management approval + digital stamp + Issue CN | [ ] | |
| P11 | Step 11–12 — Accounts gate, Replacement Slip, A/c entry per GS, Dispatch Slip | [ ] | |
| P12 | Clean-up, full E2E, UAT pack | [ ] | |

---

### PHASE P0 — Audit & decisions (no feature code)

```
Run Phase P0 of docs/RMS_PHASE_PROMPTS_20-11-2026.md.

Goal: confirm the current state against the target flow (§1) and lock the decisions before any build.

Do:
1. Follow §0. Read §1–§3 of this file, docs/RMS_GAP_PLAN_2026-11-17.md, and DEC-51…DEC-59 in docs/DECISIONS.md.
2. Inspect the code for every row of §3 (gate form + gs_gate_documents, unboxing, itemization,
   rm_review, custody_transfers / transfer_slip_id, department_routing (+ plan lines), receiving,
   final_actions, ac_action_slips, ac_entry, dispatch, journeys, roles/permissions in seed.sql).
   Correct §3 of this file wherever it is wrong.
3. Write docs/RMS_FLOW_AUDIT_20-11-2026.md: for each step 1–12, list current tables / endpoints /
   screens / roles, then keep | modify | rebuild | add | retire, with the files involved.
   Also list how legacy GSs mid-flow will behave after each phase.
4. Read the "Answer" column of §2. Add DEC-60 … DEC-71 to docs/DECISIONS.md, using the user's
   answer, or the recommended one marked PROVISIONAL:
   DEC-60 roles (Q1, Q2) · DEC-61 intermediate stores + mapping (Q3, Q4) · DEC-62 gate v4 (Q5–Q7)
   · DEC-63 RM missing-doc exception retired (Q8) · DEC-64 counting → popup → categorisation
   lock, RM review retired, Admin/Management edit window (Q9–Q12) · DEC-65 transfer slips
   (Q10, Q20) · DEC-66 store acknowledgement (Q13) · DEC-67 routing by store user (Q14)
   · DEC-68 receiving by store user · DEC-69 analysis options (Q15, Q16) · DEC-70 Management
   approval + e-stamp (Q17, Q18) · DEC-71 Accounts per GS (Q19).
   Mark which existing DECs each one supersedes (DEC-53 UI part, DEC-54, DEC-55 issue step,
   DEC-56 actor, DEC-57 actor/options).
   Changing guard G-02 needs an explicit DEC (CLAUDE.md §c). Flag it in the report.
5. Run the baseline: supabase db reset + supabase test db, pytest, ruff, mypy, pnpm lint /
   typecheck / test. Record pre-existing failures so later phases are not blamed for them.

Do not change code, migrations or seed in this phase. Completion report: audit file path,
DEC list, baseline results, and any question the answers in §2 do not cover.
```

---

### PHASE P1 — Roles, Intermediate Stores, category mapping

```
Run Phase P1 of docs/RMS_PHASE_PROMPTS_20-11-2026.md (DEC-60, DEC-61).

Build:
1. Roles (seed.sql + release snippet):
   - INWARD_VERIFIER label → "Replacement Executive" (code unchanged).
   - New role MANAGEMENT ("Management"): view everything + approve/edit permissions used in
     P4 and P10. MANAGEMENT_VIEWER unchanged.
   - Gate role label → "Gate User (Offline)" (code GATE_INWARD unchanged).
2. Intermediate Stores (new migration):
   - Table intermediate_stores (id, code immutable, name, role_id → roles, location_id →
     inventory_locations, is_active, sort_order, audit columns).
   - Table intermediate_store_category_map (store_id, category_id XOR sub_category_id, unique
     per category/sub-category). Resolution function rms_private.store_for_product(product_id):
     sub-category mapping wins over category; if nothing is mapped, use the store flagged
     is_default (exactly one default; enforce with a partial unique index).
   - Seed (seed.sql + snippet): OP "Intermediate Store OP" (ENCLOSED_OVAL, PRISMATIC),
     DT "Intermediate Store DT" (DMT), RI "Intermediate Store RI" (GENERAL, default). Each gets
     its own role (ISTORE_OP / ISTORE_DT / ISTORE_RI) and an INTERMEDIATE_STORE-class location
     (ISTORE_OP / ISTORE_DT / ISTORE_RI).
   - Admin can create a store; that creates its role and its location in one transaction.
   - Helper rms_private.user_store_ids(user_id): the stores the user acts for (via role).
     Super Admin and MANAGEMENT see all stores.
   - Guard (DB + service): a product with no resolvable store blocks transfer-slip generation
     (error code STORE_MAPPING_MISSING). It cannot happen while a default store exists; test it.
3. Backend module intermediate_stores (router/schemas/service/repository):
   GET/POST/PATCH /admin/intermediate-stores, GET/PUT /admin/intermediate-stores/{id}/mapping,
   GET /intermediate-stores/mine. Admin permission only for writes.
4. Admin Panel → "Intermediate Stores": list, rename, activate/deactivate, add store, map
   categories / sub-categories (checkbox tree, shows conflicts), see which users hold each
   store role. Mobile-friendly.
5. Do NOT change the old INTERMEDIATE_STORE_MANAGER flow yet. It is retired in P6/P7.
   Existing stock in the old INTERMEDIATE_STORE location stays where it is; note this in the audit file.

Tests: pgTAP for the mapping resolution, the single default store and the inactive-store
rules; pytest for the endpoints and permissions; vitest for the admin screen.
Update the UAT users script (scripts/reset-db.ps1 provisioning) with one user per store role + one
MANAGEMENT user, and add them to RMS_USER_CREDENTIALS.txt (git-ignored).
```

---

### PHASE P2 — Step 1: Gate entry v4 + confirmation summary

```
Run Phase P2 of docs/RMS_PHASE_PROMPTS_20-11-2026.md (DEC-62).

Target (Gate User (Offline), e.g. Anuj):
- State → Station → Party: dependent dropdowns (reuse GatePickers / DistributorPicker /
  useStations; keep the party fallback rules already built).
- Cartons: numeric, required, integer ≥ 1.
- Received Through (required, option set DELIVERY_MODE):
  * Courier → Courier Name* + Docket No.*  (existing COURIER_PARCEL)
  * Transport → Transport Name*  (relabel DIRECT_TRUCK "Transport"; vehicle no. hidden/not required
    in v4, unless Q5 says otherwise)
  * By Hand → Contact Name* + Contact Number* (relabel SELF_PARTY_REP "By Hand"; phone format check)
- Documents From Party (optional): type = Invoice / GST Debit Note / Hand Written Slip /
  No Documents From Party (+ file attachment for any type except No Documents). No doc no / date /
  remarks. Deactivate DELIVERY_CHALLAN (not delete). Relabel DEBIT_NOTE "GST Debit Note".
- Documents From Transport (optional): only type "Courier Slip" + file attachment.
- Red asterisk on every required field and only on those (driven by is_required / required_when
  from the form config, not hard-coded).
- Remove the Return Type field from the gate (Q6). Return type is set in P4.

Build:
1. New migration: relax the gs_gate_documents CHECKs so INVOICE / DEBIT_NOTE / HANDWRITTEN_SLIP
   no longer need doc_no / doc_date / remarks (existing rows untouched). Add a document "source"
   (PARTY | TRANSPORT | CARTON, CARTON used in P3) or a separate option set GATE_TRANSPORT_DOCUMENT
   with COURIER_SLIP. Pick one, justify it in DECISIONS.
2. seed.sql + release snippet: S1_GATE_INWARD v4 (copy the published version, same pattern as v3),
   option label changes, new option set/items.
3. goods_slips service: validate v4 (conditional required fields per delivery mode, server side).
   Gate documents are optional. Keep the missing_documentation flag when "No Documents From Party"
   is chosen or nothing is attached, and keep the Accounts alert (setting
   gate.accounts_alert_doc_types). Remove return-type validation for v4 GSs and keep it for older
   versions (G-18).
4. UI NewGoodsSlipPage: "Submit & Create GS" opens a compact summary sheet (Party, State, Station,
   Cartons, Received Through + its details, documents count) with "Back to edit" and "Submit".
   The GS is created only on Submit (Idempotency-Key generated when the sheet opens, so
   double-tap is safe). Success shows the GS number + Print GS Tag.
5. Attachments: uploads go to signed URLs before submit, the same way as today. Show the upload
   progress, and if an upload fails let the user retry it or remove it.

Tests: pytest per delivery mode (missing courier docket → 422 with field error), document optional,
v3 GS still readable; vitest for asterisks + summary/back/submit; Playwright gate flow at 1280 and 360 px.
```

---

### PHASE P3 — Step 2a: Unboxing (video per carton) + carton document

```
Run Phase P3 of docs/RMS_PHASE_PROMPTS_20-11-2026.md (DEC-62/63).

Target (Replacement Executive, e.g. Aman):
- Unboxing screen lists cartons 1..N from the gate count. Each carton needs its own video
  (keep the existing per-carton video, upload queue, size limit from settings).
- After all carton videos: ONE optional "Document found in carton" block: choose the type (same
  options as Documents From Party in P2) → attach photo(s). No numbers, no dates, no classification.
- "Next" is enabled only when every carton has a video, then goes to item addition (P4).

Do:
1. Inspect unboxing (CartonDocumentsSection, api, backend unboxing module, ph3 migration).
   Keep what works. Change the document part to one typed block (source = CARTON). Remove any
   doc no/date inputs.
2. Apply DEC-63 (user 2026-11-20, Q8): remove the RM missing-document approval (G-02) completely,
   for all GSs. That means the DB guard, service check, approval screen/queue entry and journey step.
   Update the guard list in the master plan addendum and the Admin read-only guard view. Replace
   the G-02 pgTAP test with one proving no RM approval is needed. Keep the missing_documentation
   flag and the Accounts alert. Release any legacy GSs blocked on that exception with a migration.
3. Exceptions that exist today in unboxing (ExceptionDecisionCard, ApprovalsPage): list them in
   the report. Don't remove any unless a DEC covers it.

Tests: pytest (Next blocked until all carton videos exist; carton doc optional; doc type
validated against the option set); Playwright on mobile 360 px, including camera/file input.
```

---

### PHASE P4 — Step 2b/2c: Items, Replacement / Sales-Return popup, categorisation lock

```
Run Phase P4 of docs/RMS_PHASE_PROMPTS_20-11-2026.md (DEC-64; Q9–Q12).

Target (RE):
1. Item addition screen: all items of the GS (all cartons together). Per line: product, "As per
   Doc/Party" qty, "Physically Received" qty. No condition split on this screen.
2. "Next" → popup: "Replacement" or "Complete Sales Return" (labels from config option set
   RETURN_TYPE, codes REPLACEMENT / SALES_RETURN).
   - SALES_RETURN → store return_type, GS status SALES_RETURN_HOLD, show it in lists with a clear
     badge, stop the flow (Q11). No further screens.
   - REPLACEMENT → categorisation screen.
3. Categorisation screen: per line, split the physical qty into the product's conditions (DEC-59
   masters per category). Split total = physical qty (G-19). "Lock Categorisation" → confirm →
   one transaction: status → PENDING_TRANSFER_SLIP (new status, or reuse RM_REVIEW renamed; justify),
   inward stock booked into Inward Staging via rms_move_stock (Q12), locked_at/locked_by stamped.
4. After lock, nobody can edit except Super Admin and MANAGEMENT, and only while no line of the GS
   has been routed (P7). DB trigger on gs_items / gs_item_buckets / gs_item_counts + service check.
   Admin/Management may change qty, product, split, and add/remove lines (reason required, revision
   rows like rm_review_revisions, stock corrected through rms_move_stock in the same tx).
   If transfer slips already exist for the GS: void the affected slips and return the GS to
   "pending transfer slip" (Q10). The P5 slip tables must support voiding, so design for it.

Retire: the RM Review edit UI and endpoints (DEC-54). Hide the journey step; keep the code paths
that legacy GSs in RM_REVIEW need, or migrate them with a documented snippet. Re-use the DEC-53
split editor component for the categorisation screen. Don't build a second one.

Tests: pgTAP (lock trigger; edit window closes at first routing; G-19); pytest (popup both
branches, lock tx books stock exactly once with Idempotency-Key, Admin/Management edit + revision
+ stock correction, RE/RM edit after lock → 403/409); vitest; Playwright RE flow at 360 px.
```

---

### PHASE P5 — Transfer slips (RM): single / multi-GS, one slip per store, Edit Request

```
Run Phase P5 of docs/RMS_PHASE_PROMPTS_20-11-2026.md (DEC-65).

Target (Replacement Manager only; RE has no part):
- Screen "Pending Transfer Slip": GSs with categorisation locked and no live slip yet. Checkbox per
  row + Select all, filters (party, date, store involved). Per GS, a read-only view of items +
  categorisation.
- Actions: "Generate Transfer Slip" (1..N GSs) and "Send Edit Request" (per GS, reason required →
  notifies MANAGEMENT + Super Admin; GS flagged EDIT_REQUESTED, excluded from generation until
  resolved: either edited (P4 rules) or rejected with a reason).
- Generation (one transaction, Idempotency-Key): for the selected GSs, group lines by store
  (store_for_product). Create ONE slip per store that has at least one relevant line.
  Each slip covers all selected GSs. A GS whose lines span 3 stores appears on 3 slips.
- Numbering from config (e.g. TRF/<store code>/<FY>/<seq>). Use the existing numbering settings.

Data (new migration): transfer_slips (store_id, number, status GENERATED / ACKNOWLEDGED / VOIDED,
generated_by/at, void reason), transfer_slip_gs (slip ↔ GS), transfer_slip_lines (slip, gs, gs_item,
condition bucket, qty, is_relevant, snapshots of product + condition labels, G-18).
Legacy goods_slips.transfer_slip_id stays for old GSs.
Stock: the slip puts the relevant qty into "in transit to <store>" (Inward Staging → transit
location per store via rms_move_stock). Acknowledgement in P6 completes the move. If a different
model is cleaner, record the reason in DECISIONS.

Slip document (A4 PDF via app/shared/pdf.py + on-screen view, HICKS logo from branding config):
- Header: HICKS branding, slip no, store name, date, generated by. A GS block for every GS
  included (GS no, party, station, state, cartons, received date).
- Section 1, relevant items (this store): per GS (party-wise segregation), product, condition, qty to
  hand over. Subtotal per GS. "Total relevant qty".
- Section 2, other items of the same GSs: greyed + strikethrough, with the store they belong to.
- "Grand total (all items of included GSs)".
- Signature boxes: handed over by (RM), received by (store).

Tests: pytest (1 GS 1 store → 1 slip; 1 GS 3 stores → 3 slips; 3 GS mixed → one slip per store with
correct relevant/grand totals; duplicate key → same slips; EDIT_REQUESTED GS rejected; void path from
P4); PDF snapshot test (text extraction); Playwright multi-select at 360 px and 1280 px.
```

---

### PHASE P6 — Step 3: Store acknowledgement (per transfer slip)

```
Run Phase P6 of docs/RMS_PHASE_PROMPTS_20-11-2026.md (DEC-66; Q13).

Target (Intermediate Store user; sees only slips of their store(s)):
- My Work → "Acknowledge Transfer Slips": list of GENERATED slips for my store.
- Open a slip: a summary as per the slip (not per GS): relevant lines grouped by GS → condition → qty,
  totals; toggle to see the greyed other items; download PDF.
- "Acknowledge receipt" (confirm, optional remark) → one transaction: slip ACKNOWLEDGED, stock
  transit → that store's location via rms_move_stock, task for routing (P7) created per GS.
- "Report discrepancy": remark only, alerts RM + MANAGEMENT. Slip stays GENERATED.

Guards (DB + service): only a user of the slip's store (or Super Admin) can acknowledge; a VOIDED slip
cannot be acknowledged; acknowledging twice returns the first result (G-16).
Retire: the old STORE_ACCEPT journey step for INTERMEDIATE_STORE_MANAGER (hide; legacy custody
transfers keep working). Notifications: new rule TRANSFER_SLIP_GENERATED → store role (in-app).

Tests: pgTAP + pytest for the guards and the stock move; Playwright store user at 360 px.
```

---

### PHASE P7 — Step 4–5: Department routing by the Intermediate Store user

```
Run Phase P7 of docs/RMS_PHASE_PROMPTS_20-11-2026.md (DEC-67; Q14).

Target:
- After acknowledgement, the store user gets a routing task **per GS** (party-wise).
- By default the GS view shows only the store's relevant items. A toggle "Show all items of this
  GS" shows the rest read-only (with their store name).
- Routing per item + condition bucket → department. Allowed departments = DEC-59 masters for the
  product's category. A line can be split across departments; the split must total the bucket qty.
- Saving the routing = issue: DIN printed, stock store location → department location
  (rms_move_stock, Idempotency-Key). "Issue to Store" (no-work) moves no stock and makes those pieces
  ready for analysis (P9).
- First routing on a GS closes the P4 Admin/Management edit window (DB-enforced).
- Status per GS per store: ROUTING_PENDING → AT_DEPARTMENTS / READY_FOR_ANALYSIS.

Do: inspect department_routing (+ department_routing_plan_lines, G-20 reconciliation). Adapt the
plan/issue model so the store user does both in one step, and keep G-20. Retire the RM DEPT_ROUTING
and Store Manager DEPT_ISSUE journey steps for new GSs. Legacy GSs keep the old path until done.

Guards (DB + service): a store user can route only lines whose product maps to their store;
department must be allowed for the category; qty ≤ unrouted qty at that store.
Tests: pgTAP + pytest (cross-store routing rejected, over-routing rejected, edit window closed after
routing, no-work path); Playwright at 360 px with the toggle.
```

---

### PHASE P8 — Step 6: Receiving back from departments (store user)

```
Run Phase P8 of docs/RMS_PHASE_PROMPTS_20-11-2026.md (DEC-68).

Target (Intermediate Store user who routed the goods):
- "Receive from Departments" queue per GS (party-wise), per department.
- Per routed line: sent qty (read-only), received qty, outcome (department outcome heads), condition
  after work (product's condition list, DEC-56 rules). Partial receipts allowed. Pending qty shown.
- Receipt moves stock department location → store location (or Non-Functional/scrap per outcome, as
  DEC-56 today) via rms_move_stock, one tx, Idempotency-Key. Updates gs_item_conditions.
- When everything routed for this store on the GS is back (or was no-work) → READY_FOR_ANALYSIS.

Do: change the receiving actor from INWARD_VERIFIER to the store role(s). Keep DEC-56 data rules and
G-20. Hide the old DEPT_RECEIVING step for the RE for new GSs.
Tests: pytest (store scoping, partial then full, over-receipt rejected, condition required when routed
from a condition); Playwright at 360 px.
```

---

### PHASE P9 — Step 7–8: Analysis (Allowed / Not Allowed)

```
Run Phase P9 of docs/RMS_PHASE_PROMPTS_20-11-2026.md (DEC-69; Q15, Q16).

Target (Intermediate Store user, per GS, own items only, per item + current condition):
- Decision: Allowed → "Dispatch New Piece" | "Dispatch Repaired Piece"; or "Not Allowed".
  Option labels/codes from config (new option set or reuse the final-action set with codes
  DISPATCH_NEW / DISPATCH_REPAIRED / NOT_ALLOWED mapped to the existing SEND_NEW / SEND_REPAIRED /
  NOT_ALLOWED codes; codes are immutable, so reuse existing codes and relabel). The qty split must
  equal the current qty.
- "Submit analysis" for my store's part of the GS (one tx). Piece destinations per DEC-57 (Q16).
- Each store submits independently. GS-level status shows per-store progress (e.g. OP done, DT pending).
- Button "Send for Management Approval" (any store user of a store on this GS, reason required)
  → P10.

Do: inspect final_actions (rm_item_actions, rounds, G-21, ac_action_slips trigger). Change the actor
to store users scoped by store. Hide PENDING and ISSUE_CN from store users (Q15). Keep the round
model for legacy GSs only. The A/c slip must NOT be created per store. It is created once per GS in P11.
Tests: pgTAP/pytest (cross-store action rejected, split total, store user cannot pick ISSUE_CN,
per-store completion), Playwright at 360 px.
```

---

### PHASE P10 — Step 9–10: Management approval + digital approval stamp + Issue CN

```
Run Phase P10 of docs/RMS_PHASE_PROMPTS_20-11-2026.md (DEC-70; Q17, Q18).

Target (MANAGEMENT role; fully mobile):
- Queue "Management Approval": GSs sent by any store user (reason shown), plus a GS search to open
  any GS that is between analysis and Accounts.
- Management can: change any final action to any other (incl. ISSUE_CN, back from ISSUE_CN), change
  quantities, add or remove lines (reason per change, revision history, stock corrected via
  rms_move_stock in the same tx), then "Approve".
- Approve = e-approval record: approver, role, timestamp, SHA-256 of the canonical JSON snapshot of
  the GS lines + actions, stored immutable (append-only table, DB-enforced). Any later change
  invalidates it (needs a new approval).
- Any GS containing ISSUE_CN must have a valid Management approval before it can reach Accounts
  (guard, DB + service). Only MANAGEMENT/Super Admin can set ISSUE_CN.
- Stamp "Digitally approved by Management — <name>, <date time>, ref <short hash>" shown on the GS
  detail page and printed on the Replacement Slip and the Dispatch Slip. "Verify" button recomputes
  the hash and shows Valid / Changed.
- From here every GS flows on its own (no combined slips).

Tests: pgTAP (append-only approvals; ISSUE_CN without approval blocked; store user cannot set
ISSUE_CN), pytest (any-to-any edits, hash verify, change after approval invalidates),
Playwright Management flow at 360 px.
```

---

### PHASE P11 — Step 11–12: Accounts gate, Replacement Slip, A/c entry per GS, Dispatch Slip

```
Run Phase P11 of docs/RMS_PHASE_PROMPTS_20-11-2026.md (DEC-71; Q19).

Target:
1. Accounts gate: a GS reaches Accounts only when every store with lines on it has submitted
   analysis, no Management approval is pending, and the ISSUE_CN guard from P10 passes.
   Guard in DB + service. Create the Replacement Slip at that moment (GS-wise, one per GS, versioned
   if Management later changes it).
2. Replacement Slip (rename the existing A/c Actions slip label via config; keep code/table
   ac_action_slips if suitable): HICKS header, GS details, lines with condition + final action + qty,
   totals per action, Management stamp if any. PDF via app/shared/pdf.py.
3. Accounts entry per GS: Challan No + Challan Date (shown and required only if the GS ships goods:
   Dispatch New / Dispatch Repaired); Credit Note No + Date + Value (shown and required only if the GS
   has ISSUE_CN). Nothing else. Hidden fields are not sent and not required. One tx, Idempotency-Key.
   New per-GS table or columns. Old per-line ac_entry_lines stay readable for legacy GSs.
   CN no unique (case-insensitive), dates not in future, value > 0.
4. On completion → Dispatch Slip generated (reuse dispatch_slips + PDF) with challan/CN details and
   the Management stamp. The GS moves to the Dispatch queue. Dispatch department work itself is out of
   scope for this file.
5. Notifications: Accounts in-app alert when a GS reaches Accounts (email per DEC-58 only if SMTP is
   configured).

6. All lines Not Allowed (no challan, no CN): the GS stays open on HOLD (user 2026-11-20, Q21). It
   does not go to Accounts. Show it in a "Hold" list with a clear badge.
7. Email: none in this phase (Q22, the user defines email for all steps later).

Tests: pytest (blocked while one store pending; only challan; only CN; both; all Not Allowed → HOLD,
not in the Accounts queue), PDF tests, Playwright Accounts flow at 360 px.
```

---

### PHASE P12 — Clean-up, full end-to-end, UAT pack

```
Run Phase P12 of docs/RMS_PHASE_PROMPTS_20-11-2026.md.

Do:
1. Journeys/menus: final role menus match §1 (Gate User, RE, RM, each store, Management, Accounts,
   Dispatch). Retired steps are hidden, not deleted. My Work counts are correct per role and store.
2. Sweep for dead links, placeholder controls, and references to retired flows (RM edit, Store Manager
   issue/accept, RE receiving, RM final actions) in the UI and the docs.
3. Playwright E2E new spec offline_replacement_flow.spec.ts, --workers=1:
   gate (courier) → unboxing (2 cartons) → items → Replacement → categorisation lock → RM multi-GS
   slips (3 GS, products of OP + DT + RI) → each store acknowledges → routes → receives back →
   analysis → one GS sent to Management, changed to ISSUE_CN + approved → Accounts entry
   (challan-only GS and CN GS) → Dispatch Slip. Run it at 1280 px and 360 px, with zero console errors.
   Also: Sales Return branch parks the GS; Edit Request → Management edit → slip voided → regenerated.
4. Full checks: supabase db reset + test db, full pytest, ruff, mypy, pnpm lint/typecheck/test/build.
5. Docs: USER_GUIDE.md (per role, screenshots optional), ADMIN_GUIDE.md (stores + mapping, roles),
   UAT.md test script for the business, CHANGELOG.md, PROGRESS.md.
6. Production list: every migration and snippet from P1–P11 in order, the pre-push backup steps
   (docs/DEPLOY_HELPER.md), and `supabase migration list --linked` as the first check.
   Do NOT push. The user approves deployment separately.
```
