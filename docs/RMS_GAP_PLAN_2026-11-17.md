# RMS gap plan — 2026-11-17 (workflow steps 5–10)

Status: **ANSWERED (2026-11-17) — ready to build, phase by phase.** Business answers Q1–Q17 are recorded
below and in `docs/DECISIONS.md` (DEC-54 … DEC-58).
Source: the user's 10-step OFFLINE RETURN workflow (2026-11-17) compared with the code on `main`
after DEC-53 (Counting & Categorisation merged). Steps 1–4 and the Accounts fields of step 10 already
match; this plan covers the gaps in steps 5–9 and the Accounts alert channel.

## 1. Where we are today vs. the target

| Step | Target | Today | Phase |
|---|---|---|---|
| 5 RM review | RM may edit **anything**: product/name, add/remove lines, quantities, condition split | RM edits quantities and split only; product change and add/remove lines blocked (`gs_items_guard`) | G1 |
| 6 Handover | Transfer slip to the Intermediate Store | ✅ matches | — |
| 7 Routing | RM decides the routing **per condition**; the **Store Manager issues**; departments STORE / CLEANING / TECHNICIAN-REPAIR / MERCURY EXTRACTION, each with its own location | RM's click moves stock directly; one shared "Technician Bench"; no STORE; no department enabled by default; per item only | G2 |
| 8 Receiving | Aman records **outcome + new condition**; the item's condition split is updated; stock returns to the Intermediate Store | Outcome only; condition never updated | G3 |
| 9 Final actions | Per **item + condition**; reachable without department work; Pending/Not Allowed/Send New pieces go to defined places so the GS can close | Per item; a GS with no routing never reaches the queue; Pending/Not Allowed/Send New pieces block closure (DEC-47) | G4 |
| 10 Accounts | In-app **and email** alert, reminder after 2 days | In-app only, no reminder | G5 |

## 2. Business answers

| Q | Question | Answer |
|---|---|---|
| Q1 | When is received stock booked? | **At RM approval** (nothing booked during review) |
| Q2 | RM edit reason / notification | **Reason required** for product change, add line, remove line (optional for qty/split); **verifier notified** of RM changes |
| Q3 | Departments | **STORE, CLEANING, TECHNICIAN / REPAIR (one department), MERCURY EXTRACTION** |
| Q4 | STORE means | **No work needed**: piece stays in the Intermediate Store and goes straight to Final Actions |
| Q5 | Who confirms the issue | **Intermediate Store Manager issues** (prints the DIN); departments need no login |
| Q6 | Routing granularity | **Per item + condition** |
| Q7 | Recorded at receiving | **Outcome + new condition**; current condition split updated |
| Q8 | Store acceptance of returns | **No** — Aman's receipt moves stock back to the Intermediate Store |
| Q9 | Final action granularity | **Per item + condition** |
| Q10 | PENDING | Pieces move to **Pending Hold**; **GS stays open** until each pending piece gets a final action |
| Q11 | NOT ALLOWED pieces | **Kept in Rejected Hold** (no dispatch) |
| Q12 | SEND NEW — old piece | **Non-Functional Store** |
| Q13 | Accounts email | **In-app + email** (needs SMTP settings; in-app only until configured) |
| Q14 | Accounts reminder | **Yes, after 2 days**, repeated daily (days = admin setting) |
| Q15 | TECHNICAL INSPECTION | **Deactivate** (kept in history) |
| Q16 | Locations | **One location per department** (Cleaning, Technician/Repair, Mercury Extraction); STORE needs none |
| Q17 | Mercury outcome | **Add "Mercury Extracted"** → piece goes to the Non-Functional Store |

## 3. Fixes made alongside (no business decision needed)

| # | Problem | Fix |
|---|---|---|
| T1 | RM qty edit stock key `item:rm_edit:<qty>` collides on 10→8→10→8 (ledger drift or G-16 error) | Gone with Q1 (no stock during review) |
| T2 | Edit / Send back / Approve still allowed after the transfer slip exists | Blocked in DB + service + UI once the slip exists |
| T3 | RM edit checks only the buckets it sent; stale bucket rows stay | RM edit replaces the whole split |
| T4 | Routing buttons check non-existent permissions (`dispatch`, `receive`) | Use the real permissions |
| T5 | `test_config_forms` expects gate form v2 (v3 since DEC-52) | Update the test |

## 4. Phases (run in order; each = new migration + backend + UI + tests + docs)

### G1 — RM edits anything in review (DEC-54; Q1, Q2; T1–T3)
- Move the inward stock booking from categorisation submit to **RM approval** (same transaction as the
  transfer slip). Legacy GS already in RM_REVIEW with stock keep working (existing lot reused).
- `gs_items_guard`: insert / delete / product change allowed in RM_REVIEW **while no transfer slip**.
- RM Review UI: per line "Change product", "Remove line" (reason), "Add line" (product, doc qty,
  physical qty, condition split — same editor as DEC-53, reason); split always replaced whole.
- New revision actions `RM_ADD_LINE`, `RM_REMOVE_LINE`, `RM_CHANGE_PRODUCT`; verifier notified
  (`RM_REVIEW_CHANGED`). After approval: read-only.

### G2 — Routing plan + Store issue (DEC-55; Q3–Q6, Q15, Q16; T4)
- Departments (config, `item_field_library` DEPARTMENT): add `STORE` (no-work, no location) and
  relabel `REPAIR` → "Technician / Repair"; keep CLEANING, MERCURY_EXTRACTION; deactivate
  TECHNICAL_INSPECTION. Enabled for all categories by default (admin may restrict).
- Locations: `DEPT_CLEANING`, `DEPT_TECHNICIAN_REPAIR`, `DEPT_MERCURY_EXTRACTION` (custodian: Store
  Manager issues, Inward Verifier receives). Technician Bench kept for older data.
- **RM routing plan** (per item + condition bucket; no stock move) → Store Manager alerted →
  **Store issue** (Store Manager, prints DIN, stock Intermediate Store → department location via
  `rms_move_stock`, idempotent). STORE lines need no issue: they are "no work" and mark those
  pieces ready for Final Actions.
- G-20 reconciliation extended with "planned, not yet issued".

### G3 — Receiving with new condition (DEC-56; Q7, Q8, Q17)
- Receive line = qty + outcome + **condition after work** (categorisation list of that product).
- New table of **current condition** per item (original counting split kept unchanged as history);
  updated by every receipt; shown to the RM in routing and Final Actions.
- Outcome "Mercury Extracted" added → stock to Non-Functional Store. Wastage → scrap (as today);
  other outcomes → back to the Intermediate Store (no Store Manager acceptance).

### G4 — Final actions per condition (DEC-57; Q9–Q12)
- Queue: held GS with nothing planned/issued and still out, i.e. all routed pieces back or routed to
  STORE — so a GS needing no work reaches Final Actions.
- Split per **item + current condition**; slip and Accounts lines show the condition.
- "Pending (BP)" relabelled "Pending"; after finalise: Pending → **Pending Hold** (GS stays open,
  RM later re-actions the piece); Not Allowed → **Rejected Hold**; Send New old piece →
  **Non-Functional Store**; Send Repaired → dispatched; Issue CN → credited
  (setting `dispatch.returned_goods_location_by_action`); closure checklist accepts these locations.

### G5 — Accounts email + reminder (DEC-58; Q13, Q14)
- `AC_ACTIONS_SLIP_READY` / `SUPERSEDED` rules: channels IN_APP + EMAIL (needs `SMTP_HOST`,
  `SMTP_FROM` … in `backend/.env` — **to be supplied by the user**).
- Reminder job: Accounts entry not completed after `ac_entry.reminder_days` (default 2), daily.

## 5. Still needed from the business (not blocking G1–G4)
- SMTP details for Accounts email (G5) — server, port, from-address, login.

## 6. Verification (every phase)
`supabase db reset` + `supabase test db`; pytest, ruff, mypy; vitest, typecheck, lint on touched
files, build; Playwright multi-GS flow extended per phase (desktop + 360px, no console errors);
backend log clean; docs/PROGRESS.md + DECISIONS.md updated; every rule cites its DEC number.
