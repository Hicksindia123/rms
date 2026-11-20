# RMS flow audit — 20-11-2026 (Phase P0)

Scope: the 12-step OFFLINE RETURN flow in `docs/RMS_PHASE_PROMPTS_20-11-2026.md` §1, compared with `main` @ `c1f3b82`
(local DB after `scripts/reset-db.ps1 -SkipBackup`). No code, migration or seed was changed in P0.
Decisions: DEC-60 … DEC-71 in `docs/DECISIONS.md`. API prefix `/api/v1`; frontend hash routes (`frontend/src/app/router.ts`,
screens in `frontend/src/app/App.tsx`, journey screens in `frontend/src/features/journey/screens.ts`).

Verdicts: **keep** · **modify** · **rebuild** · **add** · **retire** (hide/deactivate; never drop tables or history).

---

## 0. Findings that change the phase plan

| # | Finding | Effect |
|---|---|---|
| F1 | The gate "Return type" field is `return_type_code` = **OFFLINE_RETURN / ECOMMERCE_RETURN** (option set `RETURN_TYPE`). It decides whether Gate Entry Date + Gate Entry No. (DEC-38) are required (DB CHECK `goods_slips_offline_gate_entry`). It is **not** Replacement / Sales Return. | **User 2026-11-20 (Q23, Q24):** the field stays on v4 with Offline and E-Commerce (E-Commerce journey later), and Gate Entry No./Date stay (DEC-62). |
| F2 | Replacement vs Sales Return already exists as `goods_slips.category_code` CSR / RO (option set `RETURN_CATEGORY`: CSR "Complete Sales Return", RO "Replacement Only", DEC-40). The DEC-53 submit path leaves it NULL. There are no REPLACEMENT / SALES_RETURN codes. The `RETURN_TYPE` set is taken (F1). | P4 reuses `category_code` + `RETURN_CATEGORY` (codes are immutable, so RO is only relabelled "Replacement"). It does not create RETURN_TYPE codes REPLACEMENT/SALES_RETURN (DEC-64). |
| F3 | Guard **G-02** has three parts: (a) one confirmed video per carton; (b) every confirmed DOC_PHOTO classified and **≥1 classified DOC_PHOTO** unless `missing_documentation`; (c) if `missing_documentation`, an **APPROVED `missing_doc_exceptions`** row with a parcel photo. The setting `require_rm_missing_doc_approval` named in DEC-03 does **not exist**. | DEC-63 removes (c) (user answer to Q8). The user's Step 2a makes the carton document optional, which also drops the "≥1 doc photo" part of (b). **Confirmed by the user 2026-11-20 (Q25).** |
| F4 | Guard **G-09** (`stock_movements_g09_transit_guard`): stock may enter or leave a TRANSIT-class location **only through a custody transfer**. There is exactly one TRANSIT location. | P5/P6: each new transfer slip is backed by one `custody_transfers` row (INWARD_STAGING → store location via TRANSIT). G-09 stays untouched (DEC-65). |
| F5 | Location class list (`20261102000300_masters.sql:114`) has **no `INTERMEDIATE_STORE` class**. The existing `INTERMEDIATE_STORE` location is class `FUNCTIONAL`. | P1: the store locations ISTORE_OP / _DT / _RI use class `FUNCTIONAL` (no new class). The P1 prompt text "INTERMEDIATE_STORE-class location" is corrected by DEC-61. |
| F6 | The location code `INTERMEDIATE_STORE` is hard-coded in custody, rm_review, department_routing, ac_entry (settlement source), store_issue, servicing and dispatch. | P6–P11 must take the source location from the GS line's store, not from a constant. The legacy path keeps the constant. |
| F7 | `pdf.py` has **no image/logo support**; `branding_logo_url` is seeded without a file; templates have `show_logo: false`. | **User 2026-11-20 (Q26):** use the repo-root `PNG LOGO HICKS.png` (214×76 PNG). P5 adds image support to pdf.py and turns on the logo for the Transfer, Replacement and Dispatch Slips. |
| F8 | The RM approval stays in RM_REVIEW until the store accepts the custody transfer. 1 GS : 1 slip is enforced only in the service (no unique index). | Legacy GSs in RM_REVIEW with an INITIATED transfer need the old STORE_ACCEPT path until they are accepted (see §3). |
| F9 | Department routing checks the allowed department against the **live** item-field profile. Receiving checks the condition against the **pinned** GS profile version. | Inconsistency noted for P7. P7 checks departments against the GS's pinned profile version (G-18). |
| F10 | DEC-59 thermometer masters are applied by migration `20261119000100` only when the categories exist. `seed.sql` never calls `apply_thermometer_masters()`, so a fresh `db reset` has the workbook masters (every active department for every category). | Tests for per-category departments (P7) must call `apply_thermometer_masters()` or seed their own assignments. |
| F11 | Every gate/role check is **permission-based** (`require(module, action)` + `assert_step_actor`). The only role-code check is `department.receiving_role` (single role code). | P1 adds store scoping (`user_store_ids`), which must be checked in the DB and the service. P8 replaces the single receiving role with store scoping. |
| F12 | No journey step is `is_active = false` today. `CATEGORISATION` is active but assigned to no role. | Retiring steps (P4, P6–P9) = deactivate the `journey_steps` row + remove `role_journey_steps` rows in seed + release snippet. |
| F13 | `goods_slips_truck_fields` CHECK requires `vehicle_no` **and** a transporter for DIRECT_TRUCK. | P2 (Q5 "Transport Name only") must relax this CHECK in a new migration (v3 GSs keep their data). |
| F14 | Seeded notification rules are `IN_APP` only. Email exists (`notifications/email.py`, worker jobs) but SMTP is not configured. | Matches Q22 (email deferred). DEC-58 stays "not built". |

---

## 1. Step-by-step audit

### Step 1 — Gate entry (Gate User (Offline), e.g. Anuj) → Phase P2

**Today**

| Layer | What exists |
|---|---|
| Tables | `goods_slips` (gate columns, `return_type_code`, `gate_entry_date/no/fy`, `carton_count` = `box_count`, `delivery_mode_code`, courier/vehicle/transporter/rep fields, `missing_documentation`); `gs_gate_documents` (`source_step` S1_GATE / S1_UNBOX, `accounts_alerted_at`); `attachments.kind = 'GATE_DOC'`. |
| Constraints | `gs_gate_documents_formal_fields` (INVOICE / DEBIT_NOTE / DELIVERY_CHALLAN need doc_no + doc_date); `gs_gate_documents_slip_fields` (HANDWRITTEN_SLIP needs remarks); `goods_slips_courier_fields`, `goods_slips_truck_fields` (vehicle + transporter), `goods_slips_rep_fields`, `goods_slips_offline_gate_entry`, legacy single-doc CHECKs (`goods_slips_formal_doc_fields`, `goods_slips_slip_fields`, v1 columns). Triggers `gs_gate_documents_guard`, `goods_slips_gate_entry_guard`, `goods_slips_no_document_exclusive`. Migrations `20261103000100_p2_02_gate_inward.sql`, `20261113000100_ph2_gate_entry_cartons_documents.sql`. |
| Form / config | `S1_GATE_INWARD` v3 PUBLISHED (v1, v2 RETIRED; the version number is `max+1` at seed time). Fields: return_type, gate_entry_date, gate_entry_no, state, station, party_name, carton_count, delivery_mode (+ courier_name, docket_no, vehicle_no, transporter_name, rep_name, rep_contact), no_document, gs_creation_format. `DELIVERY_MODE`: COURIER_PARCEL "Courier / Parcel", DIRECT_TRUCK "Direct Transport / Truck", SELF_PARTY_REP "Self / Party Representative". `GATE_DOCUMENT`: INVOICE, DEBIT_NOTE, DELIVERY_CHALLAN, COURIER_SLIP, LR_BILITY, DELIVERY_NOTE, HANDWRITTEN_SLIP, OTHER, NO_DOCUMENT. Settings `gate.max_backdate_days`, `gate.accounts_alert_doc_types` = [INVOICE, DEBIT_NOTE], `gate.party_fallback`. |
| Endpoints | `GET /gs/gate-form`, `GET /gs/lookups/*`, `POST /gs` (Idempotency-Key; `goods_slips.create` + S1_GATE PERFORM), `PATCH /gs/{id}/gate`, `GET /gs`, `/gs/{id}`, `/gs/{id}/tag`, `POST /gs/{id}/gate-documents/{doc}/files/upload-url`. Module `backend/app/modules/goods_slips/` (`service.py` `_create`, `_resolve_and_validate`, `_validate_documents`). |
| Screens | `#/gs/new` → `frontend/src/features/goods-slips/NewGoodsSlipPage.tsx` (DynamicForm + `DistributorPicker.tsx`, `GatePickers.tsx` `TransporterInput`, `GateDocumentsEditor`). **No summary/confirm before create**; the `Confirmation` is shown after create. `useStations.ts` and `GatePickers.PartyPicker` are unused. |
| Roles | `GATE_INWARD` "Gate Inward User". |
| Alerts | `MISSING_DOCUMENTS` → ACCOUNTS + REPLACEMENT_MANAGER; `GS_DOCUMENT_FOUND` → ACCOUNTS. |

**Target and verdict**

| Item | Verdict | Files |
|---|---|---|
| State → Station → Party pickers, party fallback | **keep** | `NewGoodsSlipPage.tsx`, `DistributorPicker.tsx` |
| Cartons | **keep** | — |
| Received Through: Courier (name + docket) | **keep** | — |
| Transport = Transport Name only | **modify**: relabel DIRECT_TRUCK "Transport", vehicle_no not in v4, relax `goods_slips_truck_fields` (new migration) | new migration, `seed.sql`, snippet, `goods_slips/service.py` |
| By Hand = Contact Name + Number | **modify**: relabel SELF_PARTY_REP "By Hand", phone format check | same |
| Party documents (Invoice / GST Debit Note / Hand Written Slip / No Documents From Party), image only | **modify**: relax `gs_gate_documents_formal_fields` / `_slip_fields` for v4 rows; relabel DEBIT_NOTE; deactivate DELIVERY_CHALLAN (also LR_BILITY, DELIVERY_NOTE, OTHER from the party list, DEC-62) | migration, seed, `GateDocumentsEditor` |
| Transport document (Courier Slip) | **modify**: COURIER_SLIP already exists in GATE_DOCUMENT; add a source (PARTY / TRANSPORT / CARTON) | migration, seed |
| Return type field (Offline / E-Commerce) | **keep** on v4 (Q24); the E-Commerce journey comes later | — |
| Gate Entry No./Date | **keep** (Q23) | — |
| Summary sheet → Submit / Back | **add** | `NewGoodsSlipPage.tsx` |
| Required asterisks from config | **modify** | DynamicForm |
| Role label "Gate User (Offline)" | **modify** (label only, P1) | `seed.sql` + snippet |

**Legacy GSs:** no impact. A GS created under v3 keeps its form version (G-18) and its documents.

### Step 2a — Unboxing (Replacement Executive, e.g. Aman) → Phase P3

**Today**

| Layer | What exists |
|---|---|
| Tables | `attachments` (`UNBOXING_VIDEO` with `box_no`, `DOC_PHOTO`, `PARCEL_PHOTO`); `gs_documents` (photo classification); carton documents = `gs_gate_documents` rows with `source_step = 'S1_UNBOX'`; `missing_doc_exceptions` (REQUESTED / APPROVED / REJECTED, guard `missing_doc_exceptions_guard`). |
| Guard G-02 | DB: `goods_slips_g02_guard` (trigger `20261103000200_p2_03_unboxing_evidence.sql`, body last replaced in `20261113000100_ph2…:416-476`). Service: `unboxing/service.py` `_checklist` → `shared/guards.py` `g02_missing_evidence`; workflow transition guard `config/workflow/service.py:35`. Rules: see F3. |
| Endpoints | `GET /gs/{id}/unboxing`, `POST /gs/{id}/unboxing/start`, `POST/PATCH /gs/{id}/documents[/{doc}]`, `POST/PATCH/DELETE /gs/{id}/carton-documents[/{doc}]`, `POST /gs/{id}/missing-doc-exception`, `POST /gs/{id}/missing-doc-exception/{exc}/decision` (`unboxing.approve`), `GET /missing-doc-exceptions/pending`, `POST /gs/{id}/unboxing/complete`; Accounts `GET /accounts/document-queue`, `POST /accounts/document-queue/{id}/acknowledge`. Module `backend/app/modules/unboxing/`. |
| Screens | `#/gs/{id}/unboxing` → `features/unboxing/UnboxingPage.tsx` (carton video checklist, `CartonDocumentsSection.tsx`, inline `ExceptionDecisionCard.tsx`); `#/approvals` → `features/unboxing/ApprovalsPage.tsx` (RM inbox: CSR approvals, item corrections, missing-doc exceptions); `#/accounts` → `features/accounts/DocumentQueuePage.tsx`. |
| Roles | `INWARD_VERIFIER` "Unboxing & Inward Verifier" (S1_UNBOX PERFORM); RM decides exceptions (`unboxing.approve`). Journey `CARTON_OPENING`. |

**Target and verdict**

| Item | Verdict | Files |
|---|---|---|
| One video per carton, upload queue, size limit | **keep** | `UnboxingPage.tsx`, unboxing service |
| One optional typed "document found in carton" (photo only) | **modify**: `CartonDocumentsSection` to one typed block, source CARTON, no doc no/date | `CartonDocumentsSection.tsx`, unboxing service |
| G-02 (c) RM missing-doc exception | **retire completely** (DEC-63): DB guard part, service check, exception endpoints (kept read-only for history), approval queue entry, `ApprovalsPage` section; release blocked legacy GSs by migration | migration, `unboxing/`, `shared/guards.py`, `ApprovalsPage.tsx`, `ExceptionDecisionCard.tsx`, pgTAP G-02 test, master-plan addendum, Admin guard view |
| G-02 (b) ≥1 classified doc photo | **modify** to optional (Q25, confirmed, DEC-63) | same |
| G-02 (a) video per carton | **keep** (guard stays) | — |
| `missing_documentation` flag + Accounts alert | **keep** | — |
| Role label "Replacement Executive" | **modify** (label only, P1) | seed + snippet |

**Legacy GSs:** GSs in UNBOXING with a REQUESTED exception are released by the P3 migration (exception left as history). A GS in UNBOXING whose documents are not yet classified can complete under the new G-02.

### Step 2b/2c — Items, Replacement / Sales Return popup, categorisation lock (RE) → Phase P4

**Today**

| Layer | What exists |
|---|---|
| Tables | `gs_items` (documented_qty, received_qty, short/excess, `category_id`, snapshots), `gs_item_buckets`, `gs_item_counts`, `rm_review_revisions`, `goods_slips.category_code` / `original_category_code` (CSR / RO), `csr_approvals` (legacy CSR flow). |
| Guards | `gs_items_guard`, `gs_item_buckets_guard`, `gs_item_counts_guard` (last in `20261117000300_g1_rm_edits_in_review.sql`); G-19 `rms_private.validate_item_bucket_conservation`; status chain `goods_slips_g03_guard` (`20261113000800_ph5_fix_rm_review_guard.sql`). |
| Endpoints | `GET /gs/{id}/itemization`, `POST /gs/{id}/items`, `PATCH|DELETE /gs/{id}/items/{item}`, `POST /gs/{id}/itemization/submit` (Idempotency-Key, ITEMIZATION → CATEGORISATION → RM_REVIEW in one tx, **no stock booking**), legacy `counting/submit`, `categorisation/*`, `/categorize` (CSR/RO), `/csr-decision`, item corrections. Module `backend/app/modules/itemization/`. |
| Screens | `#/gs/{id}/itemization` → `features/itemization/ItemizationPage.tsx`; split editor `LineEditor` in `features/itemization/LineParts.tsx` (read-only `LineSplit`); `SubmitToRmSection` with in-page confirm; legacy `ItemCategorisationSection.tsx`, `CategorizeSection`. |
| Roles | `INWARD_VERIFIER` (S1_ITEMIZE PERFORM). Journey `COUNTING` "Counting & Categorisation". |

**Target and verdict**

| Item | Verdict | Files |
|---|---|---|
| Item lines (doc qty + physical qty), all cartons together | **modify**: split moves off this screen | `ItemizationPage.tsx`, `LineParts.tsx` |
| Popup Replacement / Complete Sales Return | **add**: sets `category_code` RO / CSR (F2); CSR → new status `SALES_RETURN_HOLD` (Q11) | migration (status CHECK, GS_STATUS option), itemization service, new popup |
| Categorisation screen + Lock | **modify**: reuse `LineEditor`; lock = status `PENDING_TRANSFER_SLIP` (new) + inward booking into INWARD_STAGING (moved from RM approval) + locked_at/by | migration, `itemization/service.py`, `inventory/ledger_service.py` |
| Admin/Management edit after lock until first routing | **add** (revision rows, stock correction, slips voided) | migration (guards), new service, UI |
| RM Review edits (DEC-54) | **retire** (hide `RM_REVIEW` journey step; keep endpoints for legacy GSs in RM_REVIEW) | `rm_review/`, `features/rm-review/`, seed + snippet |
| `SubmitToRmSection` | **retire** for new GSs (replaced by Lock) | `ItemizationPage.tsx` |

**Legacy GSs:** GSs in ITEMIZATION/CATEGORISATION keep using `/itemization/submit` until P4 ships. After P4 they take the new path (popup → lock). GSs already in RM_REVIEW keep the RM Review screen (approve / send-back only) until they leave it. Their stock is booked at RM approval as today, so it is never booked twice: the lock books stock only for GSs that have none.

### Step 2d — Transfer slips + Edit Request (RM) → Phase P5

**Today:** RM approval (`POST /gs/{id}/rm-approve`, `itemization.approve`) books stock into INWARD_STAGING, then `custody_service.initiate_transfer` INWARD_STAGING → INTERMEDIATE_STORE (via TRANSIT) and sets `goods_slips.transfer_slip_id`. 1 GS : 1 slip, enforced in the service only. Transfer note print `#/custody/transfers/{id}/note` (`TransferNotePrintPage.tsx`). Files: `backend/app/modules/rm_review/service.py:856-1029`, `custody/service.py`, `features/rm-review/RmReviewPage.tsx`.

| Item | Verdict | Files |
|---|---|---|
| Pending Transfer Slip list (multi-select) | **add** | new module `transfer_slips`, new feature screen, journey step |
| `transfer_slips`, `transfer_slip_gs`, `transfer_slip_lines` (GENERATED / ACKNOWLEDGED / VOIDED) | **add**, each slip backed by one `custody_transfers` row (G-09, F4) | new migration |
| One slip per store, many GSs | **add** (`store_for_product`) | — |
| Edit Request → Management + Admin, EDIT_REQUESTED flag | **add** | migration, notification rule (seed) |
| A4 PDF with HICKS logo | **add**: image support in pdf.py + `PNG LOGO HICKS.png` as the branding logo (Q26) | `app/shared/pdf.py`, template seed |
| `goods_slips.transfer_slip_id` 1:1 | **keep** for legacy GSs only | — |
| `rm-approve` | **retire** for new GSs | `rm_review/` |

**Legacy GSs:** RM_REVIEW GSs approved before P5 keep their single custody transfer and the old STORE_ACCEPT path.

### Step 3 — Store acknowledgement (Intermediate Store user) → Phase P6

**Today:** `custody_transfers` + `custody_transfer_lines` + `custody_reconciliations` (G-09 guards, `20261104000100_p3_01_custody_engine.sql`); accept `POST /custody/transfers/{id}/accept` (`custody.approve` + custodian of destination + segregation `segregation_of_duties_transfer` = true); the accept moves the GS RM_REVIEW → HELD_AT_INTERMEDIATE_STORE. One store: location `INTERMEDIATE_STORE` (class FUNCTIONAL, custodian role INTERMEDIATE_STORE_MANAGER). Journey `STORE_ACCEPT` (queue: RM_REVIEW + INITIATED transfer). Screens `features/custody/TransfersPage.tsx`, `TransferDetailPage.tsx`, `IntermediateStorePanel.tsx`.

| Item | Verdict | Files |
|---|---|---|
| N Intermediate Stores (OP / DT / RI) + roles + locations + category map | **add** (P1) | new module `intermediate_stores`, migration, seed, admin screen |
| Acknowledge per transfer slip, store-scoped, full only + remark; "Report discrepancy" alert only | **add** (on top of the custody engine) | `transfer_slips` module, custody service |
| STORE_ACCEPT journey step for INTERMEDIATE_STORE_MANAGER | **retire** (hidden; legacy transfers keep `/custody/transfers/{id}/accept`) | seed + snippet |
| Custody engine (G-09, reconciliation) | **keep** | — |
| Existing stock in `INTERMEDIATE_STORE` | **keep** where it is (legacy GSs finish there) | — |

**Legacy GSs:** INITIATED legacy transfers are still accepted by INTERMEDIATE_STORE_MANAGER on the custody screens (Custody & Store tool stays in that role's menu until no legacy GS is left).

**Stock path (user answer to Q12, written out):**
1. **Categorisation lock** (P4): `rms_move_stock` INWARD → **INWARD_STAGING** (lot per GS line, AS_RECEIVED).
2. **Transfer slip generated** (P5): the relevant quantities of that store leave INWARD_STAGING into **TRANSIT** under one custody transfer per slip (G-09 allows transit only through a custody transfer).
3. **Acknowledgement** (P6) by a user of **the Intermediate Store the slip is addressed to** (OP, DT, RI …): TRANSIT → **that store's own location** (ISTORE_OP / ISTORE_DT / ISTORE_RI). It is **not** the Main Store or any fresh-inventory store. The returned pieces stay in the Intermediate Store until routing.
4. Routing (P7): store location → department location; receiving (P8): department location → back to the **same** store location (or scrap / Non-Functional per outcome).
5. Final settlement (P11): store location → Rejected Hold / Non-Functional Store / Dispatched / Credited per action. **"Dispatch New" ships a fresh piece from the Main Store**, outside this return lot (DEC-26). The Main Store never receives the returned goods in this flow.

### Step 4–5 — Department routing by store user → Phase P7

**Today:** `department_routings`, `department_routing_lines`, `department_routing_plan_lines` (PLANNED / ISSUED / NO_WORK / CANCELLED); triggers `department_plan_lines_insert_guard`, `department_plan_lines_update_guard`, `trg_dept_routing_lines_from_plan`, G-20 `rms_private.validate_department_reconciliation` (deferred triggers); settings `department.location_by_code`, `department.no_work_codes` = [STORE]; DEC-59 per-category departments as `item_field_assignments`. Endpoints `/department-routing/queue`, `/gs/{id}/state`, `/gs/{id}/plan`, `POST /plan` (RM, `department_routing.create`), `POST /plan-lines/{id}/cancel`, `GET /issue-queue`, `POST /issue` (Store Manager, `department_routing.approve`, DIN, INTERMEDIATE_STORE → DEPT_*), `/gs/{id}/reconciliation`, `/gs/{id}/legs`. Screens `features/department-routing/RmRoutingQueuePage.tsx` + `RmRoutingPlanModal.tsx` (`#/department-routing`), `DepartmentIssuePage.tsx` (`#/department-issue`), `DepartmentIssueNotePrintPage.tsx`, `DepartmentReconciliationPanel.tsx`. Journeys `DEPT_ROUTING` (RM), `DEPT_ISSUE` (Store Manager).

| Item | Verdict | Files |
|---|---|---|
| Plan + issue in one step by the store user, per GS, own-category lines | **modify** (`/plan` + `/issue` combined; store scoping; DIN printed) | `department_routing/service.py`, router, new migration (store scoping guard) |
| "Show all items" read-only toggle | **add** | routing screen |
| Departments allowed per category (DEC-59) | **keep**, checked against the pinned profile version (F9) | plan-line guard |
| G-20 reconciliation | **keep**, the source is the store's location (F6) | `validate_department_reconciliation` |
| First routing closes the Admin/Management edit window | **add** | P4 guard + P7 |
| RM DEPT_ROUTING, Store Manager DEPT_ISSUE journey steps | **retire** for new GSs | seed + snippet |

**Legacy GSs:** HELD GSs with PLANNED lines keep `/issue` by INTERMEDIATE_STORE_MANAGER and the RM plan screen until done (both journey entries stay visible while legacy work exists, or as tools).

### Step 6 — Receiving back (store user) → Phase P8

**Today:** `department_receipts`, `department_receipt_lines` (outcome + condition after work), `department_outcome_heads` (`destination_location_code`; MERCURY_EXTRACTED → NON_FUNCTIONAL_STORE; NULL = wastage → SCRAP_DISPOSED, else back to INTERMEDIATE_STORE), `gs_item_conditions`, `rms_private.item_current_conditions`, `item_condition_balances`, `move_item_condition` (`20261118000200_g3_receiving_new_condition.sql`). Endpoint `POST /department-routing/{routing_id}/receive` (`department_routing.edit` + role in setting `department.receiving_role` = INWARD_VERIFIER). Screens `DepartmentReceivingQueuePage.tsx` (`#/department-receiving`), `DepartmentReceiveModal.tsx`. Journey `DEPT_RECEIVING` (INWARD_VERIFIER).

| Item | Verdict | Files |
|---|---|---|
| Receipt rules (qty + outcome + condition, partial receipts, G-20) | **keep** | — |
| Actor = store user of the routing's store; receipt goes back to that store's location | **modify** | `department_routing/service.py:547-657`, `repository.py:13-24` |
| `department.receiving_role` setting | **retire** for new GSs (kept for legacy routings) | settings |
| RE `DEPT_RECEIVING` journey step | **retire** for new GSs | seed + snippet |

**Legacy GSs:** routings issued from `INTERMEDIATE_STORE` are still received by INWARD_VERIFIER back into `INTERMEDIATE_STORE`.

### Step 7–8 — Analysis (store user) → Phase P9

**Today:** `rm_item_actions` (round_no, condition), G-21 `validate_final_action_split`, `rm_item_actions_final_guard`, helpers in `20261118000300_g4_final_actions_per_condition.sql`; actions in `item_field_library` group ACTION: SEND_NEW, SEND_REPAIRED, ISSUE_CN, NOT_ALLOWED, PENDING_BP ("Pending"). Endpoints `GET/PUT /gs/{id}/final-actions`, `POST /finalise` (`final_actions.approve`; the backend inserts `ac_action_slips` + PDF), `POST /slips/{id}/print`. Screen `features/final-actions/FinalActionsPage.tsx` (`#/gs/{id}/final-actions`). Journey `FINAL_ACTIONS` (RM).

| Item | Verdict | Files |
|---|---|---|
| Per item + current condition split, G-21 | **keep** | — |
| Actor = store user, own store's lines; per-store submit | **modify** | `final_actions/service.py`, new migration (store scoping) |
| Options for store users: SEND_NEW ("Dispatch New Piece"), SEND_REPAIRED ("Dispatch Repaired Piece"), NOT_ALLOWED | **modify** (relabel; codes unchanged) | seed + snippet |
| PENDING_BP, ISSUE_CN for store users | **retire** (ISSUE_CN = Management only, P10) | service + DB guard |
| Rounds (re-action of PENDING) | **keep** for legacy GSs only | — |
| A/c slip on finalise | **modify**: created once per GS at the Accounts gate (P11), not per store | `final_actions/service.py:664-815` |
| "Send for Management Approval" | **add** | new |
| RM `FINAL_ACTIONS` journey step | **retire** for new GSs | seed + snippet |

**Legacy GSs:** GSs with RM actions saved or finalised keep the RM screen, the rounds and the slip versions.

### Step 9–10 — Management approval + e-approval stamp → Phase P10

**Today:** only `MANAGEMENT_VIEWER` (view on 18 modules + export on reports/inventory; menu DASHBOARD, GS_LIST, PENDENCIES, REPORTS, AUDIT). No approval module, no stamp. `ac_action_slips.sha256` / `dispatch_slips.sha256` are PDF fingerprints only. `ApprovalsPage` is the RM's inbox.

| Item | Verdict |
|---|---|
| Role `MANAGEMENT` (approver) | **add** (P1) |
| Management queue, any-to-any edit, ISSUE_CN, approve | **add** (new module, append-only `management_approvals` with SHA-256 of a canonical snapshot) |
| Stamp on GS detail, Replacement Slip, Dispatch Slip + Verify | **add** |
| `MANAGEMENT_VIEWER` | **keep** (read-only) |

**Legacy GSs:** none affected (Management approval applies to GSs on the new analysis path).

### Step 11–12 — Accounts gate, Replacement Slip, A/c entry per GS, Dispatch Slip → Phase P11

**Today:** `ac_action_slips` (versions, rounds, CURRENT/SUPERSEDED, PDF + sha256, template `AC_ACTIONS_SLIP` "Replacement Slip – A/c Actions", series RSA; guard needs GS HELD_AT_INTERMEDIATE_STORE); `ac_entry_lines` per action line (CN no/date/value or challan no/date by flag; CN unique across GSs and `credit_notes`, `VOUCHER_NUMBER_TAKEN`); `ac_entry_completions`; `dispatch_slips` + `dispatch_slip_lines` (READY / DISPATCHED, template `DISPATCH_SLIP`, series DS, generated only if a line needs a challan). Endpoints `GET /ac-entry/queue`, `GET /ac-entry/gs/{id}`, `PUT /ac-entry/gs/{id}/lines`, `POST /ac-entry/gs/{id}/complete`, `GET /dispatch-slips`, `POST /dispatch-slips/{id}/dispatch`, `/print`. Settlement `ac_entry/service.py` `_settle_returned_goods` (source INTERMEDIATE_STORE / PENDING_HOLD). Screens `features/ac-entry/AccountsEntryQueuePage.tsx`, `AccountsEntryPage.tsx`, `DispatchSlipsPage.tsx`. Journeys `ACCOUNTS_ENTRY`, `DISPATCH_SLIP`, `PARTY_EMAIL`, `ACCOUNTS_DOCS`. Older P3-05 `/dispatches` + `features/dispatch/` still exist (tool DISPATCH_QUEUE).

| Item | Verdict |
|---|---|
| Accounts gate: all stores analysed, no pending Management approval, ISSUE_CN approved | **add** (DB + service) |
| Replacement Slip = A/c Actions slip relabelled; one per GS, versioned; stamp | **modify** (template label; `ac_action_slips` reused) |
| Entry per GS: one Challan No/Date, one CN No/Date/Value | **add** (new per-GS table); `ac_entry_lines` **keep** readable for legacy |
| Dispatch Slip with challan/CN + stamp | **modify** (`dispatch_slips` reused) |
| All Not Allowed → GS on HOLD, no Accounts entry (Q21) | **add** |
| Settlement source = the store location of each line | **modify** (F6) |
| Accounts email + reminder (DEC-58) | **deferred** (Q22) |

**Legacy GSs:** GSs with an A/c Actions slip keep per-line entry, rounds and the existing Dispatch Slip.

---

## 2. Roles and journeys (seed.sql)

| Role (code) | Label today | Target | Verdict |
|---|---|---|---|
| GATE_INWARD | Gate Inward User | Gate User (Offline) | modify (label) |
| INWARD_VERIFIER | Unboxing & Inward Verifier | Replacement Executive | modify (label; DEC-60) |
| REPLACEMENT_MANAGER | Replacement Manager | transfer slips + edit requests only | modify (menu) |
| INTERMEDIATE_STORE_MANAGER | Intermediate Store Manager | legacy only | retire after legacy GSs finish (not deleted) |
| ISTORE_OP / ISTORE_DT / ISTORE_RI | — | Intermediate Store users | add (P1) |
| MANAGEMENT | — | approver | add (P1) |
| MANAGEMENT_VIEWER | Management Viewer | unchanged | keep |
| ACCOUNTS, DISPATCH | — | unchanged roles, new screens | keep |
| MAIN_STORE, TECHNICIAN*, SPARE_PARTS_* | — | not in this flow | keep |

UAT users (`backend/scripts/uat_reset.py`, called by `scripts/reset-db.ps1`): admin, anuj (GATE_INWARD), aman (INWARD_VERIFIER + TECHNICIAN_COORDINATOR), pratham (RM), sahil (INTERMEDIATE_STORE_MANAGER + TECHNICIAN_COORDINATOR), deepak (ACCOUNTS), rajkumar, spt, spm, dispatch, mainstore, management (MANAGEMENT_VIEWER). P1 adds one user per store role + one MANAGEMENT user.

Journey step changes (all by deactivation / seed + release snippet): add `TRANSFER_SLIPS` (RM), `STORE_ACK`, `STORE_ROUTING`, `STORE_RECEIVING`, `STORE_ANALYSIS` (store roles), `MANAGEMENT_APPROVAL` (MANAGEMENT); retire for new GSs `RM_REVIEW`, `STORE_ACCEPT`, `DEPT_ROUTING`, `DEPT_ISSUE`, `DEPT_RECEIVING`, `FINAL_ACTIONS`, `APPROVALS` (missing-doc part). Queue SQL lives in `backend/app/modules/journeys/repository.py` `_QUEUES`.

---

## 3. Legacy GSs mid-flow, phase by phase

| After phase | A GS that is in … | behaves like this |
|---|---|---|
| P1 | any status | Unchanged. Stores, roles and the mapping only exist; nothing reads them yet. Stock in `INTERMEDIATE_STORE` stays there (built 2026-11-20, see §5). |
| P2 | GATE_CREATED (v1–v3) | Keeps its form version; editable with the old rules. New GSs use v4. |
| P3 | UNBOXING with a REQUESTED / REJECTED missing-doc exception | Released by the P3 migration (the exception row stays as history); completes on video-per-carton only. |
| P3 | UNBOXING, documents unclassified | Can complete (doc photo optional, Q25 confirmed). |
| P4 | ITEMIZATION / CATEGORISATION (incl. RM send-back) | Takes the new path: popup → categorisation lock → PENDING_TRANSFER_SLIP (stock booked at lock). |
| P4 | RM_REVIEW, not approved | Stays on the retired-but-reachable RM Review (approve / send-back, no edits). Send-back puts it on the new path. If approved, it follows the legacy custody path. |
| P5 | RM_REVIEW with an INITIATED legacy transfer | Legacy STORE_ACCEPT by INTERMEDIATE_STORE_MANAGER (custody screens). |
| P6 | HELD_AT_INTERMEDIATE_STORE (legacy) | Stock in `INTERMEDIATE_STORE`; legacy RM plan + Store Manager issue. |
| P7 | HELD with PLANNED legacy lines | Legacy `/issue` by INTERMEDIATE_STORE_MANAGER. |
| P8 | legacy routings DISPATCHED / PARTIALLY_RECEIVED | Received by INWARD_VERIFIER (`department.receiving_role`) into `INTERMEDIATE_STORE`. |
| P9 | legacy GS with RM actions | RM Final Actions screen, rounds, A/c slip per round as today. |
| P10 | — | Not applied to legacy GSs. |
| P11 | legacy GS with an A/c Actions slip | Per-line Accounts entry, existing Dispatch Slip and settlement; the new per-GS entry applies only to GSs with a P9 analysis. |

A GS is "new path" when it has a categorisation lock (P4 column, e.g. `goods_slips.categorisation_locked_at`). Every retired endpoint checks that flag rather than a date.

---

## 4. Baseline (P0, 2026-11-20, before any P1 change)

| Check | Result |
|---|---|
| `scripts/reset-db.ps1 -SkipBackup` (= `supabase db reset` + users) | PASS (12 users, 315 products, 13 roles) |
| `supabase test db` | PASS — 45 files, 792 tests |
| `pytest` (full, 20 min) | **1008 passed, 3 failed, 3 skipped**. The 3 failures are pre-existing and stale. (1) `test_config_forms::test_list_seeded_forms_and_get_published` expects gate form v2, but v3 has been PUBLISHED since DEC-52 (gap plan T5, never fixed). (2) `test_merged_itemization::test_line_saved_with_split_and_one_submit_reaches_rm_review` expects INWARD stock at submit, but DEC-54 moved booking to RM approval (P4 moves it to the lock). (3) `test_reports::test_xlsx_export_and_limits` is data-dependent on a fresh reset (known). Skipped: 3, need GS data. |
| `ruff check .` | **55 pre-existing errors**, all in `backend/scripts/` (`seed_perf_dataset.py` 26, `verify_p4_03.py` 16, `verify_p4_04.py` 5) and `tests/integration/` (test_workbook_traceability 3, test_security_idor 3, test_security_input 1, test_security_auth 1). None in `app/`. |
| `mypy app` | PASS (252 files) |
| `pnpm lint` | **144 pre-existing problems** (139 errors, 5 warnings) in 36 files; mainly `no-confusing-void-expression` (70), `react-hooks/set-state-in-effect` (13), `no-unnecessary-condition` (13), `no-non-null-assertion` (10), and `vite.config.ts` `rollupOptions` deprecated |
| `pnpm typecheck` | PASS |
| `pnpm test` (vitest) | 232/233 in the full run; `tests/unit/credit_notes.test.tsx` timed out at 5 s while pytest ran in parallel; passes 4/4 when re-run alone (load flake, pre-existing) |

---

## 5. Phase P1 build notes (2026-11-20)

- **Built:** migration `20261120000100_p1_intermediate_stores.sql` (tables `intermediate_stores`, `intermediate_store_category_map`, resolver `rms_private.store_for_product`, `rms_private.user_store_ids`, guard `rms_private.assert_store_for_products` = STORE_MAPPING_MISSING, permission module `intermediate_stores`); seed + `supabase/snippets/release_20261120_roles_intermediate_stores.sql` (labels "Replacement Executive" / "Gate User (Offline)", roles MANAGEMENT / ISTORE_OP / ISTORE_DT / ISTORE_RI, FUNCTIONAL locations ISTORE_OP / _DT / _RI, stores OP / DT / RI, mapping OP = ENCLOSED_OVAL + PRISMATIC, DT = DMT, RI = GENERAL + default); module `intermediate_stores`; Admin → Intermediate Stores.
- **Legacy stock stays where it is.** Stock already in the old `INTERMEDIATE_STORE` location (custodian `INTERMEDIATE_STORE_MANAGER`) is **not moved** to the new store locations, and no ledger row is written for it. Legacy GSs keep using `INTERMEDIATE_STORE` and the Store Manager flow (STORE_ACCEPT, DEPT_ISSUE) until they finish; that flow is retired for new GSs in P6 / P7. The new `ISTORE_*` locations start empty and only receive stock from P6 (store acknowledgement of a P5 transfer slip).
- **Nothing reads the stores yet.** Transfer-slip generation (P5) must call `intermediate_stores.service.require_stores_for_products` inside its transaction (service check + DB guard). P6–P9 scope the store user's work with `rms_private.user_store_ids`.
- The `INTERMEDIATE_STORE_MANAGER` role, its menu and the old `INTERMEDIATE_STORE` location are unchanged in P1 (sahil@rms.local keeps them).
