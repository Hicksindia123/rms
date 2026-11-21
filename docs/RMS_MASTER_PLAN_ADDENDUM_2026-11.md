# RMS Master Plan — Addendum 2026-11 (Change Request of 12-11-2026)

| Item | Value |
|---|---|
| Amends | `RMS_DEVELOPMENT_MASTER_PLAN.md` (§2 workflow, §3 option catalogue, §4 rules/guards, §5 decisions) |
| Source | Business change request, 2026-11-12, as captured in `docs/RMS_CHANGE_PLAN_2026-11-12.md` §1 |
| Implementation plan | `docs/RMS_CHANGE_PLAN_2026-11-12.md`, Phases 0–11 |
| Open questions | DEC-35 … DEC-44 in `docs/DECISIONS.md` (all **PROVISIONAL** until the business owner confirms) |
| Status | Recorded 2026-11-12. Nothing in this addendum is implemented unless the "Phase" column's phase is ticked in the change plan. |

## How to read this addendum

- Each amendment has a stable ID **AMD-xx**. Cite it in code comments, migrations and tests, in the same way
  as BR-xx / G-xx / DEC-xx.
- Where an amendment conflicts with the master plan, **the amendment wins** for the scope it describes.
  Everything else in the master plan stays in force.
- System guards **G-01…G-18 stay non-bypassable**. An amendment may change *what* a guard checks (for
  example, "per box" becomes "per carton"). It never makes a guard configurable or optional.
- Business values (labels, option sets, field groups, roles per step) still come from DB configuration.
  Logic keys off stable codes (CLAUDE.md §e).
- New guards proposed here get the next free numbers (**G-19, G-20, …**) when their phase is implemented.

## Target workflow (summary)

```
Gate Entry (GATE_INWARD) → Carton Opening (INWARD_VERIFIER) → Counting → Item Categorisation
  → RM Review (REPLACEMENT_MANAGER) → Transfer Slip → Intermediate Store hold
  → RM Department Routing → Department Receiving (qty reconciled)
  → RM Final Actions (qty split) → "Replacement Slip – A/c Actions" PDF
  → Accounts CN / Challan entry → Dispatch Slip → Dispatch → (later) Party email
```

The full diagram is in `docs/RMS_CHANGE_PLAN_2026-11-12.md` §1.

---

## Amendments

### A. Gate entry

| ID | Amendment | Amends / relates to | Phase |
|---|---|---|---|
| **AMD-01** | **Return Type** is the first gate field, with options *Offline Return* and *E-Commerce Return*. It is held in an option set (codes `OFFLINE_RETURN`, `ECOMMERCE_RETURN`). E-Commerce uses the same form without the gate-entry date and number (DEC-39). | §2 Step-1; DD Step-1 header | 2 |
| **AMD-02** | **Offline Return** captures a **Gate Entry Date** (back-dating allowed, never later than today; an optional maximum back-date comes from a setting) and a numeric **Gate Entry Number**. The uniqueness scope is set by DEC-38. Both fields are shown above State and Station. | §2 Step-1 | 2 |
| **AMD-03** | **Carton No.** (the count of cartons) replaces the business concept *Box No.* The rule "one unboxing video per box" (Requirement B, 2026-11-10) becomes **one video per carton**. The G-02 guard text and its DB/service checks are updated accordingly. G-02 itself stays non-bypassable. | G-02; DEC-04; Requirement B | 2, 3 |
| **AMD-04** | **Multiple document rows**, at the gate and again at carton opening. Each row has a document type, number, date, remarks and one or more files. Types: Invoice, Debit Note, Challan, **Courier Slip**, Hand-written slip, LR/Bilty, Delivery Note, Other. This replaces the single gate-document field. "No document" stays a GS-level flag (`missing_documentation`, DEC-03). | DD r9; DEC-03 | 2, 3 |
| **AMD-05** | **Accounts alert:** when a document row of type Invoice or Debit Note is saved, at the gate **or** at carton opening, the ACCOUNTS role is notified immediately (for GST input checks). The trigger document types are configurable. The same attachment never raises a duplicate alert. | WF r3; DEC-05; BR-06 | 2, 3 |
| **AMD-06** | **Distributor (party) list filtered by State + Station.** When the selected station has no parties, the fallback (DEC-35) is configurable. Creating a provisional party stays available (DEC-02). | DEC-02 | 1, 2 |

### B. Masters

| ID | Amendment | Amends / relates to | Phase |
|---|---|---|---|
| **AMD-07** | **Sub-Categories:** the product hierarchy becomes Category → Sub-Category → Product. Sub-category codes are immutable. A product's sub-category must belong to the product's category (DB-enforced). Products are loaded from the business CSV `Item Name, Category, Sub-Category` (DEC-36). Missing stations for the party import exceptions are added and the parties re-imported (DEC-37). | §3 product master; DEC-29 | 1 |

### C. Carton opening, counting and categorisation

| ID | Amendment | Amends / relates to | Phase |
|---|---|---|---|
| **AMD-08** | **Carton Opening** is the new label for the Unboxing step (codes unchanged). It shows carton-wise progress (Carton *n* of *N*). **Counting** (adding items and quantities) is done by the same role (INWARD_VERIFIER). | §2 Step-2/3; P2-03, P2-04 | 3 |
| **AMD-09** | **Item-level categorisation buckets:** the counted quantity of each item is split into admin-configured quantity buckets (e.g. Good, Damaged, Body Broken, Wastage). New guard: Σ bucket qty = counted qty per item (DB + service + test). GS-wise CSR / RO remains as the GS **type** (DEC-40). | BR (categorisation); G-07 (analogous conservation); DEC-06 | 4, 5 |
| **AMD-10** | **Admin-configurable item field profiles** with three field groups: **Categorisation buckets**, **Departments** (routing destinations, e.g. Mercury Extraction, Technical Inspection, Repair, Cleaning) and **Actions** (final RM actions, e.g. Send New, Send Repaired, Issue CN, Not Allowed). Fields are assigned at Category, Sub-Category or Product level. The most specific level that has an assignment for a group wins (Product > Sub-Category > Category). One DB function resolves the effective profile. Profiles are versioned, and a GS stores the version it was categorised under (G-18). Existing action codes (`SEND_NEW`, `SEND_REPAIRED`, `ISSUE_CN`, `NOT_ALLOWED`, `PENDING_BP`) and condition options are seeded as library entries, so nothing in use breaks. | §3 option catalogue; G-18; DEC-14 | 4 |
| **AMD-11** | **Packaging / Container / User Manual counts:** numeric fields recorded per GS item (not buckets), enabled per scope in the item field profile. | DEC-07 | 4, 5 |

### D. RM review, custody and departments

| ID | Amendment | Amends / relates to | Phase |
|---|---|---|---|
| **AMD-12** | **RM Review:** the REPLACEMENT_MANAGER sees the whole GS on one screen (header, documents, cartons/videos, items with counted qty and qty per bucket). The RM can approve, edit any qty, bucket or item (audited, with revisions kept), or send the GS back with a remark. | §2 Step-3 a); DEC-13 | 5 |
| **AMD-13** | **Transfer Slip → Intermediate Store hold:** RM approval auto-generates a numbered, printable Transfer Slip using the existing custody engine (two-phase, G-09). INTERMEDIATE_STORE_MANAGER accepts it with a per-line qty check. The GS then shows "Held at Intermediate Store". All stock moves go through `rms_move_stock` and are idempotent (G-16). | G-09; G-16; P3-01 | 5 |
| **AMD-14** | **Department routing & receiving:** the RM sends item/bucket quantities to the departments allowed by the resolved profile (one printable issue note per department). The assigned receiver (DEC-42) books returns into outcome heads (e.g. Repaired, Not Repaired, Wastage, "Send to Mercury Extraction"). Partial receipts are allowed. Whether a department can pass goods directly to another department is set by DEC-43. | P3-02 (servicing); DEC-34 | 6 |
| **AMD-15** | **Quantity reconciliation guard** (**G-20**, implemented Phase 6): for every GS item, quantity is always conserved: counted = in store + at departments + in outcome heads + actioned. Enforced in DB + service, with a per-GS reconciliation panel. | G-07, G-16 (analogous) | 6 |

### E. Final actions, accounts and dispatch

| ID | Amendment | Amends / relates to | Phase |
|---|---|---|---|
| **AMD-16** | **RM final actions with qty split:** per item, the available qty is split across the actions allowed by the resolved profile (e.g. 10 pcs → 6 Send New, 3 Send Repaired, 1 Issue CN). Guard: Σ action qty = qty available for action. Revisions are kept. The hard-coded action `CHECK` on `rm_item_actions` is replaced by validation against the action library (codes immutable once used). | P2-07; DEC-13; DEC-33 | 4, 7 |
| **AMD-17** | **"Replacement Slip – A/c Actions" PDF:** generated per DEC-41 (proposed server-side), with branding/template from config. It contains the GS header, party, gate entry details, an item × action × qty table, totals and signatures. It is stored as a versioned attachment, can be re-printed at any time, and every print is logged. On finalise, ACCOUNTS is notified. | P2-07 Replacement Slip; print templates | 7 |
| **AMD-18** | **Accounts entry per action line:** for *Issue CN*, CN No., CN Date and CN Value; for *Send New* / *Send Repaired*, Challan No. and Challan Date. Which fields an action requires comes from action flags in the library (e.g. `requires_cn`, `requires_challan`), not from code. The existing credit-notes module is reused where it fits (DEC-22, G-13, G-14 stay in force). | P3-06; DEC-22; G-13; G-14 | 8 |
| **AMD-19** | **Dispatch Slip:** when every line that needs Accounts data is complete, a numbered Dispatch Slip (PDF) is generated for lines that ship goods, and DISPATCH is notified. Dispatch issues goods against the slip (store issue + `rms_move_stock`). The GS then continues to the existing closure engine (G-15). | P3-05; DEC-26; G-15 | 8 |
| **AMD-20** | **Party email (later phase):** built from the values Accounts entered (CN no./date/value, challan no./date, dispatch details) using the party-notifications module and a config template. Preview, send, log and resend are supported. No auto-send until it is enabled in settings. | P3-07; DEC-25; G-15 | 9 |

### F. Scope control

| ID | Amendment | Amends / relates to | Phase |
|---|---|---|---|
| **AMD-21** | **Feature hold:** the dismantled-item sub-inventory (tip, container, PCB, …), the spare-parts ledger and the dismantling screens are **on hold**. Setting `features.on_hold` (list of module codes) hides on-hold modules from navigation, and their write endpoints return `FEATURE_ON_HOLD`. No code, data or migration is deleted. **Guards are unaffected** (G-10, G-11 and the others keep their DB triggers and constraints). The default list is set by DEC-44. | P3-02 (battery), P3-03, P3-04; G-10; G-11 | 0 |
| **AMD-22** | **Role journeys & UI clean-up:** each role sees only its own menu, ordered as its working journey (where a GS reaches the role → where it leaves), with a **My Work** home showing the count per step and the next GS to act on. Menus come from DB configuration (`journey_steps` catalogue + `role_journey_steps`, Admin → Role Journeys), never from code; on-hold modules (AMD-21) are hidden; admin items are collapsed; one primary action per screen; consistent page headers and status badges. Navigation only: endpoints keep their permission checks and no guard changes. Defaults: DEC-49. | P1-04 (shell), P4-01 (landing page); AMD-21 | 10 |

---

## Impact on existing guards (summary)

| Guard | Change | AMD |
|---|---|---|
| G-02 | "video per box" becomes "video per carton". Still mandatory and non-bypassable. | AMD-03 |
| **G-02 (2026-11-20)** | **DEC-63 (user Q8 + Q25), P3:** G-02 = "a GS cannot leave UNBOXING until every carton 1..N has a confirmed unboxing video", **nothing else**, for all GSs. Dropped: (b) ≥ 1 classified document photo and every document photo classified; (c) the RM Missing Document Exception (DEC-03), also for a GS flagged "No Documents From Party". Still enforced in the DB (trigger `goods_slips_g02_guard`, migration `20261120000300`) and the service (`shared/guards.py`), not configurable, not bypassable by Super Admin. The `missing_doc_exceptions` table is read-only history. | DEC-63 |
| **G-19 (2026-11-20)** | **DEC-64, P4:** unchanged rule; it now gates the categorisation lock (CATEGORISATION → PENDING_TRANSFER_SLIP) and is re-checked at commit after a Super Admin / Management edit of a locked GS. No guard is weakened. | DEC-64 |
| G-07 | Unchanged for existing inspection. A new per-item bucket conservation guard is added alongside it. | AMD-09 |
| G-09, G-16 | Reused by the Transfer Slip and department routing. | AMD-13, AMD-14 |
| G-10, G-11 | Unchanged. The UI and write endpoints of their modules are on hold (AMD-21), but the DB checks remain. | AMD-21 |
| G-13, G-14, G-15 | Unchanged. Accounts entry and dispatch feed them. | AMD-18, AMD-19 |
| G-18 | Extended to item field profile versions. | AMD-10 |
| **G-19** (new, Phase 5) | Per-item bucket conservation: Σ categorisation bucket qty = counted qty. | AMD-09 |
| **G-20** (new, Phase 6) | Quantity reconciliation across store, departments, outcome heads and actions (DB triggers serialise per GS; insert-only receipts). | AMD-15 |
| **G-21** (new, Phase 7) | RM final action split: per item Σ action qty = qty available for action (counted − at departments), actions only from the resolved ACTION profile, finalise only with nothing at a department; a finalised A/c Actions slip freezes the actions, is immutable and is superseded only by a reasoned revision. G-20 was fixed forward in the same phase: actioned pieces are taken from the outcome heads first, so nothing is counted twice. | AMD-16, AMD-17 |
| **G-22** (new, Phase 8) | Accounts entry & Dispatch Slip: Accounts data only where the action flags require it (`requires_cn` → CN No./Date/Value, `requires_challan` → Challan No./Date), only on the CURRENT A/c Actions slip of a held GS, dates not in the future, CN No. on one GS only (DEC-22); completion only when every line is complete, and it freezes the entries, the slip (no supersede) and the RM actions; the Dispatch Slip lists exactly the goods-shipping lines, goes READY → DISPATCHED once with DEC-26 data and is never deleted; the P3-05 replacement dispatch refuses a GS on this flow. The G-15 checklist gains `AC_ENTRY_COMPLETE` and `DISPATCH_SLIP_DISPATCHED` for this flow (and a NULL category no longer yields NULL CSR rows). | AMD-18, AMD-19 |

## Change log

| Date | Change |
|---|---|
| 2026-11-12 | Addendum created (Phase 0). AMD-01 … AMD-21 recorded. DEC-35 … DEC-44 opened as PROVISIONAL. |
| 2026-11-13 | Guard numbers fixed to match the code: G-19 = bucket conservation (Phase 5), G-20 = quantity reconciliation (Phase 6, AMD-15). The earlier draft called the reconciliation guard "G-19". |
| 2026-11-13 | Phase 7: **G-21** added (AMD-16 / AMD-17, RM final action split and A/c Actions slip). G-20 formula fixed forward (actioned pieces drawn from outcome heads first). DEC-45 / DEC-46 opened as PROVISIONAL. |
| 2026-11-14 | Phase 8: **G-22** added (AMD-18 / AMD-19, Accounts entry and Dispatch Slip). Closure checklist fixed forward for the A/c Actions flow. DEC-47 opened as PROVISIONAL (destination of retained Send New / Not Allowed pieces is an open question). |
| 2026-11-14 | Phase 9: AMD-20 implemented (party email from the Accounts values; `party_emails` log; a SENT email is the BR-38 PRIOR_INFO_SENT record, `delivery_mode = EMAIL_SENT`). No new system guard: the source / frozen-content / final-status rules are DB triggers under AMD-20, BR-38 and G-18. DEC-48 opened as PROVISIONAL (auto-send OFF by default). |
| 2026-11-14 | Phase 10: **AMD-22** added and implemented (role journeys, My Work home with counts per step and next GS, config-driven menu, Admin → Role Journeys). Setting `features.on_hold` created (AMD-21 / DEC-44, navigation hiding). No new system guard. DEC-49 opened as PROVISIONAL. |
