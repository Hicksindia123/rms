# API

Base path: `/api/v1`. The live OpenAPI schema is at `http://localhost:8000/openapi.json`, with
interactive docs at `/docs`. Frontend types are generated with `pnpm gen:api` into
`frontend/src/lib/api/schema.d.ts`.

## Conventions

### Authentication

Send `Authorization: Bearer <Supabase access token>`. The API checks the signature (JWKS; HS256 only
when `APP_ENV` is local/test), `exp`, `aud = authenticated` and `iss`, then loads the profile.

| Situation | Status | `error.code` |
|---|---|---|
| No / non-bearer `Authorization` header | 401 | `UNAUTHENTICATED` |
| Malformed, wrongly signed, wrong `aud`/`iss`, disallowed algorithm | 401 | `INVALID_TOKEN` |
| Expired | 401 | `TOKEN_EXPIRED` |
| Valid token, profile inactive or missing | 403 | `ACCOUNT_INACTIVE` |
| JWKS endpoint unreachable | 503 | `AUTH_UNAVAILABLE` |

### Authorization & permissions

Endpoints declare `require(module, action)`. Effective permissions = role permissions + grant
overrides − deny overrides (deny wins, expired overrides ignored). Missing permission: 403
`PERMISSION_DENIED`, with `details = {"module", "action"}`. Workflow-step commands also check
`step_assignments` (403 `NOT_STEP_ACTOR`). Super Admin passes permission and step checks. System
guards G-01…G-18 still apply to Super Admin: they answer 409 with `error.code = "G-xx"`.

### Error envelope

Every error response has this shape:

```json
{"error": {"code": "NOT_FOUND", "message": "Goods slip not found", "details": null, "request_id": "3f2a…"}}
```

Request validation errors are 422 `VALIDATION_FAILED`, with `details = [{"loc", "msg", "type"}]`
(input values are not echoed). Unexpected errors are 500 `INTERNAL_ERROR`. A stack trace is included
in `details` only when `APP_ENV=local`. Other codes: `CONFLICT` 409, `RATE_LIMITED` 429,
`SERVICE_UNAVAILABLE` / `STORAGE_ERROR` 503.

### Idempotency (`Idempotency-Key`)

Stock-affecting and commercial commands **require** `Idempotency-Key: <8–200 chars>`, which should be a
fresh UUID per user action.

* Missing / invalid key: 422 `IDEMPOTENCY_KEY_REQUIRED` / `IDEMPOTENCY_KEY_INVALID`.
* A replay with the same key and the same request (method, path, canonical JSON body) returns the
  original status and body, plus the header `Idempotency-Replayed: true`. The command does not run
  again.
* Same key with a different request, or from a different user: 409 `IDEMPOTENCY_CONFLICT`.
* If the command fails, nothing is stored, so the same key can be retried.

### Pagination, filtering & sorting

`?page=1&page_size=25&sort=-created_at,code&filter[is_active]=true`

* `page` ≥ 1. `page_size` defaults to `PAGE_SIZE_DEFAULT` (25) and is capped at `PAGE_SIZE_MAX` (100).
* `sort`: comma-separated fields, with a `-` prefix for descending.
* `filter[<field>]`: equality filters.
* Each list endpoint documents its sortable and filterable fields. Others give 422 `INVALID_SORT` /
  `INVALID_FILTER`.
* Response: `{"items": [...], "total": 123, "page": 1, "page_size": 25}`.

### Request IDs & logging

Send `X-Request-ID` (1–128 chars of `A-Z a-z 0-9 . _ : -`) to correlate a request, or the API
generates one. It is returned in the `X-Request-ID` response header and in `error.request_id`, and is
stored in `audit_log.request_id` for every change the request made. Logs are JSON outside local, and
tokens and `Authorization` headers are never logged.

### Rate limits

Endpoints that need it (auth-adjacent and upload-URL endpoints) declare a limit. Exceeding it returns
429 `RATE_LIMITED`.

## Goods slips: Step-1 gate inward (P2-02)

The permission module is `goods_slips` (the plan's `gs/create`, see DECISIONS P1-02). The form is the
published `S1_GATE_INWARD` version. Option codes are the §3.2 codes (DD r2–r10).

| Method | Path | Who | Notes |
|---|---|---|---|
| `GET` | `/gs/gate-form` | `goods_slips.create` | Published form snapshot, `contact_phone_pattern`, `party_state_station_autofill` (DEC-02). |
| `GET` | `/gs/lookups/parties?q=` · `/states` · `/stations?state_id=` · `/transporters?q=` | `goods_slips.view` | Active master rows for the gate pickers. |
| `POST` | `/gs` | `goods_slips.create` + `S1_GATE` PERFORM. **`Idempotency-Key` required** | Creates the GS. 201 `GateInwardOut`. |
| `GET` | `/gs?status=&party_id=&date_from=&date_to=&q=&flag=&page=&page_size=&sort=` | `goods_slips.view` (scope `own` / `department` / `all`) | `flag` is repeatable: `missing_documentation`, `has_open_pendency`, `has_discrepancy`, `has_hazard`, `has_rejections`. Sort by `created_at`, `gs_no`, `status`, `box_count`. Dates use the business timezone. |
| `GET` | `/gs/{id}` | `goods_slips.view` | Header, flags, form values + `labels_snapshot`, timeline (`gs_status_history` + audited edits with reason), tasks, attachment summary, `can_edit_gate`, `can_cancel`. |
| `PATCH` | `/gs/{id}/gate` | creator (with `goods_slips.create`) or GS admin | Only while `GATE_CREATED`, otherwise 409 `GS_NOT_EDITABLE`. Body = create body + `reason` (mandatory). The reason is stored in `audit_log.reason`. |
| `POST` | `/gs/{id}/cancel` | GS admin | `{"reason"}` is mandatory. Only from `GATE_CREATED` / `UNBOXING`, otherwise 409 `GS_NOT_CANCELLABLE`. Open tasks become `CANCELLED`. |
| `GET` | `/gs/{id}/tag` | `goods_slips.view` | `GS_TAG` template layout, `qr_payload = "<gs_no>\|<id>"`, labelled `sections`, `labels` ("Box i of n"). |
| `GET` | `/tasks/mine?status=OPEN&step_code=` | any signed-in user | Tasks for the caller's roles, or assigned to the caller directly. Super Admin sees all. |

A *GS admin* is a Super Admin or a holder of `goods_slips.configure` (DECISIONS P2-02).

**`POST /gs` body**

```json
{
  "party_id": "uuid",                       // or "provisional_party": {"name", "state_id", "station_id"}
  "state_id": "uuid", "station_id": "uuid", // optional: default to the party master (DEC-02)
  "transporter_id": "uuid",                 // optional, DIRECT_TRUCK from the master
  "values": {
    "box_count": 3,
    "delivery_mode": "COURIER_PARCEL",      // DIRECT_TRUCK | SELF_PARTY_REP
    "courier_name": "DTDC", "docket_no": "D-1",
    "accompanying_doc": "NO_DOCUMENT",      // INVOICE | DEBIT_NOTE | DELIVERY_CHALLAN | HANDWRITTEN_SLIP
    "missing_doc_warning_acknowledged": true,
    "gs_creation_format": "AUTO_STANDARD"   // optional; the only option (DD r10)
  }
}
```

Conditional fields, enforced by the form rules, the service and the DB CHECKs:

* `COURIER_PARCEL` needs `courier_name` and `docket_no`.
* `DIRECT_TRUCK` needs `vehicle_no` and either `transporter_name` or `transporter_id`.
* `SELF_PARTY_REP` needs `rep_name` and a `rep_contact` that matches the `contact_phone_pattern` setting.
* `INVOICE` / `DEBIT_NOTE` / `DELIVERY_CHALLAN` need `gate_doc_no` and a `gate_doc_date` that is not in the future.
* `HANDWRITTEN_SLIP` needs `gate_doc_remarks`.
* `NO_DOCUMENT` needs the acknowledgement. It sets `missing_documentation`, adds the warning
  `MISSING_DOCUMENTATION` and sends a HIGH notification to `ACCOUNTS` and `REPLACEMENT_MANAGER` (DEC-05).

The service validates the whole form and only then writes anything. A failure returns 422
`FORM_VALIDATION_FAILED`, with `details = {field_key: [messages]}`.

On success, in one transaction:

1. `gs_no = rms_private.next_number('GS', today in Asia/Kolkata)`.
2. The workflow version is pinned.
3. A `gs_status_history` row is written: `null → GATE_CREATED`, step `S1_GATE`.
4. `form_responses` stores the values and `labels_snapshot`.
5. Tasks open for the step that the pinned workflow routes `S1_GATE` to (`S1_UNBOX`, `INWARD_VERIFIER`).
6. A provisional party, if one was created, notifies Super Admins and `masters.edit` holders.
7. A state/station override sets `state_station_overridden` and writes the reason to the audit row.

## Phase 2 gate changes (P2-08)

Defect fixes found by the Phase 2 gate. No new features; all behaviour is cited.

| Method | Path | Change |
|---|---|---|
| `GET` | `/container-audits/{audit_date}` | **Newly routed** (service already existed). The Daily Register for a chosen past date, so a late entry (reason required) is counted and confirmed against *that* day. Future dates → 422 `VALIDATION_FAILED`. `container_audit.view`. Before P2-08 the page always loaded `/today`. |
| `PUT` | `/gs-items/{gs_item_id}/inspection` | Now 409 `CONFLICT` unless the GS is in `INSPECTION` (a CSR awaiting the RM decision could be graded, G-03), and 409 when the line is already `FINAL` (it changes only through the RM reopen). The first save pins the published `S1_INSPECT_*` form version whose condition field uses the line's option set (`inspections.form_version_id`, G-18). |
| `GET` | `/gs/{gs_id}/inspection` | `condition_options[].label` is taken from the pinned form version's snapshot (or the currently published one before the first save), so a relabel published mid-flight does not change an in-flight GS. Codes, `allowed_status` and `system_behavior` still come from the option set. |
| — | worker `container_audit_morning_missed` | Also records MISSED for days after the first recorded audit that nobody opened (no row), not only for opened-but-unconfirmed days (BR-18, DEC-08). |

Database guards added (migration `20261103000700_p2_08_g08_db_guards.sql`, G-08, DEC-12). They surface
through the standard envelope with `error.code = "G-08"`:

* A Pending (BP) lot cannot be added to `custody_transfer_lines`.
* A GS with an open pendency cannot move to `COMMERCIAL_RESOLUTION`, `AWAITING_NOTIFICATION` or
  `CLOSED`. With `pending_blocks_entire_gs = true` (or a pendency raised with `blocks_gs`), it also
  cannot move `RM_REVIEW → IN_PROCESS`.

Verification assets: `backend/tests/integration/test_phase2_guard_regression.py` (G-01..G-08, G-16..G-18
bypass attempts, Super Admin included), `test_phase2_config_change_safety.py`, `test_phase2_integrity.py`
(runs `scripts/integrity_check.sql`), `test_phase2_performance.py` (5,000 GS list < 1 s),
`frontend/tests/e2e/phase2_gate.spec.ts` (E2E-01..07).

## Phase 3 gate changes (P3-08)

Defects found by the full-lifecycle run and fixed (no new business rules):

| Area | Change |
|---|---|
| Auth (§9) | The read endpoints of `/servicing/*`, `/inventory/batteries/*`, `/dismantling/*` and `GET /scrap` answered **without a token**. They now need an authenticated user with `servicing.view`, `inventory.view` or `dismantling.view` respectively (`GET /servicing/battery-reconciliation` → `inventory.view`, as it is shown on the Battery Stock page). |
| Idempotency (G-16) | `POST /servicing/batches`, `…/{id}/receive`, `/inventory/batteries/receipts`, `…/adjustments/{id}/approve`, `/dismantling/batches`, `…/{id}/recover`, `/scrap/{id}/dispose` only checked that the header was present: a retried receive could consume batteries twice. They now use the shared contract above (replay → original response with `Idempotency-Replayed: true`; same key, different body → 409 `IDEMPOTENCY_CONFLICT`). |
| `POST /scrap/from-lot` (new, DEC-11 / DEC-18) | `{lot_id, qty, weight_kg?, remarks?}` (Spare Parts Manager, `Idempotency-Key`) marks quarantined hazard stock or a non-dismantleable non-good lot (DEC-18 "disposal required") as scrap → 201 scrap record (`hazardous` = quarantine). 422 `LOT_NOT_DISPOSABLE` / `SCRAP_QTY_EXCEEDS_STOCK`. |
| `POST /scrap/{id}/dispose` | For a lot-linked scrap record it now posts the **DISPOSE** movement into `SCRAP_DISPOSED` (P3-03 task 4; the code had `pass`), and stores `stock_movement_id`. 409 `SCRAP_STOCK_NOT_AVAILABLE` if the pieces are gone. Hazardous scrap still needs `manifest_ref` (DEC-11). |
| `POST /credit-notes/{id}/issue` | A CN / JV number already used (DEC-22) → 409 `VOUCHER_NUMBER_TAKEN` (was a 500 from the unique index), also for two simultaneous issues; the CN row is locked during issue. |
| `GET/POST /gs/{id}/cn-decision` | Prefill and DEC-13 divergence now use **all** current RM action rows of a line (ISSUE_CN → ALLOW; SEND_NEW + SEND_REPAIRED → DENY; NOT_ALLOWED / PENDING_BP have no commercial outcome). Before, only the last row counted, so `SEND_NEW 3 + PENDING_BP 1` or `ISSUE_CN 5 + NOT_ALLOWED 1` raised a false divergence. A line may now return one prefill row per outcome. |
| `POST /store-issues/{id}/acknowledge` | The manual Main Store acknowledgement (DEC-21 auto-ack off) crashed (missing argument); it now accepts every issued line at its issued quantity (`ACCEPTED_VERIFIED`). |
| `POST /pendencies/{id}/clear` | The cleared pieces return to a lot with the same inspected condition / routing (the pending lot now keeps them), so e.g. a cleared visually-OK piece can still be classified directly (DEC-14). |
| `POST /servicing/batches/{id}/receive` | Concurrent receives for the same technician could deadlock (500): row locks are now limited to the batch / line / lot rows (`FOR UPDATE OF`). |

## Endpoints

Total API Endpoints: 190

### attachments (5 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `DELETE` | `/api/v1/attachments/{attachment_id}` | Delete Attachment | 204, 422 |
| `POST` | `/api/v1/attachments/{attachment_id}/confirm` | Confirm Upload | 200, 422 |
| `GET` | `/api/v1/attachments/{attachment_id}/download-url` | Download Url | 200, 422 |
| `POST` | `/api/v1/gs/{gs_id}/attachments/notification-proof/upload-url` | Request Proof Upload Url | 201, 422 |
| `POST` | `/api/v1/gs/{gs_id}/attachments/upload-url` | Request Upload Url | 201, 422 |


### auth (1 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/me` | Get Me | 200 |


### closure (3 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `POST` | `/api/v1/gs/{gs_id}/close` | Close Gs | 200, 422 |
| `GET` | `/api/v1/gs/{gs_id}/closure` | Closure State | 200, 422 |
| `POST` | `/api/v1/gs/{gs_id}/reopen` | Reopen Gs | 200, 422 |


### config-forms (10 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/config/forms` | List Forms | 200 |
| `GET` | `/api/v1/config/forms/{form_code}` | Get Form | 200, 422 |
| `GET` | `/api/v1/config/forms/{form_code}/diff` | Diff Versions | 200, 422 |
| `POST` | `/api/v1/config/forms/{form_code}/draft` | Create Draft | 200, 422 |
| `PUT` | `/api/v1/config/forms/{form_code}/draft/fields` | Update Draft Fields | 200, 422 |
| `POST` | `/api/v1/config/forms/{form_code}/draft/publish` | Publish Draft | 200, 422 |
| `POST` | `/api/v1/config/forms/{form_code}/draft/validate` | Validate Draft | 200, 422 |
| `GET` | `/api/v1/config/forms/{form_code}/published` | Get Published Snapshot | 200, 422 |
| `POST` | `/api/v1/config/forms/{form_code}/validate-submission` | Validate Submission Endpoint | 200, 422 |
| `GET` | `/api/v1/config/forms/{form_code}/versions/{version_no}` | Get Version | 200, 422 |


### config-history (4 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/admin/config-history` | Get Config History | 200, 422 |
| `GET` | `/api/v1/admin/system-guards` | Get System Guards | 200 |
| `GET` | `/api/v1/config/history` | Get Config History | 200, 422 |
| `GET` | `/api/v1/config/system-guards` | Get System Guards | 200 |


### config-numbering (4 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/config/numbering` | List Number Series | 200 |
| `GET` | `/api/v1/config/numbering/{code}` | Get Number Series | 200, 422 |
| `PUT` | `/api/v1/config/numbering/{code}` | Update Number Series | 200, 422 |
| `GET` | `/api/v1/config/numbering/{code}/preview` | Preview Number Series | 200, 422 |


### config-options (5 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/config/option-items/{code}/usage` | Get Option Item Usage | 200, 422 |
| `GET` | `/api/v1/config/option-sets` | List Option Sets | 200, 422 |
| `POST` | `/api/v1/config/option-sets/{option_set_id}/items` | Create Option Item | 201, 422 |
| `PUT` | `/api/v1/config/option-sets/{option_set_id}/items/{item_id}` | Update Option Item | 200, 422 |
| `GET` | `/api/v1/config/option-sets/{set_id_or_code}` | Get Option Set | 200, 422 |


### config-settings (5 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/config/settings` | List Settings | 200, 422 |
| `POST` | `/api/v1/config/settings/branding/contrast-check` | Check Contrast | 200, 422 |
| `POST` | `/api/v1/config/settings/branding/upload-url` | Get Logo Upload Url | 200, 422 |
| `GET` | `/api/v1/config/settings/public` | Get Public Settings | 200 |
| `PUT` | `/api/v1/config/settings/{key}` | Update Setting | 200, 422 |


### config-templates (7 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/config/templates` | List Templates | 200 |
| `POST` | `/api/v1/config/templates/{code}/draft` | Create Draft | 200, 422 |
| `PUT` | `/api/v1/config/templates/{code}/draft` | Update Draft | 200, 422 |
| `POST` | `/api/v1/config/templates/{code}/draft/publish` | Publish Draft | 200, 422 |
| `GET` | `/api/v1/config/templates/{code}/published` | Get Published Template | 200, 422 |
| `GET` | `/api/v1/config/templates/{code}/sample-data` | Get Sample Data | 200, 422 |
| `GET` | `/api/v1/config/templates/{code}/versions/{version_no}` | Get Template Version | 200, 422 |


### config-workflow (10 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/config/workflow` | List Workflows | 200 |
| `GET` | `/api/v1/config/workflow/{code}` | Get Workflow | 200, 422 |
| `GET` | `/api/v1/config/workflow/{code}/diff` | Diff Versions | 200, 422 |
| `POST` | `/api/v1/config/workflow/{code}/draft` | Create Draft | 200, 422 |
| `POST` | `/api/v1/config/workflow/{code}/draft/publish` | Publish Draft | 200, 422 |
| `PUT` | `/api/v1/config/workflow/{code}/draft/step-label` | Update Step Label | 200, 422 |
| `PUT` | `/api/v1/config/workflow/{code}/draft/transitions` | Update Draft Transitions | 200, 422 |
| `POST` | `/api/v1/config/workflow/{code}/draft/validate` | Validate Draft | 200, 422 |
| `GET` | `/api/v1/config/workflow/{code}/published` | Get Published Snapshot | 200, 422 |
| `GET` | `/api/v1/config/workflow/{code}/versions/{version_no}` | Get Version | 200, 422 |


### container-audit (5 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/container-audits` | Get Audit Calendar | 200, 422 |
| `GET` | `/api/v1/container-audits/today` | Get Today Audit | 200 |
| `GET` | `/api/v1/container-audits/{audit_date}` | Get Audit For Date | 200, 422 |
| `POST` | `/api/v1/container-audits/{audit_date}/confirm` | Confirm Audit | 200, 422 |
| `PUT` | `/api/v1/container-audits/{audit_date}/lines` | Save Audit Lines | 200, 422 |


### credit-notes (14 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `POST` | `/api/v1/credit-note-lines/{id}/rate-verifications` | Record historical sales or purchase rate verification for a CN line (G-14, DEC-24) | 201, 422 |
| `POST` | `/api/v1/credit-notes` | Draft a new Credit Note from allowed CN quantities (G-13) | 201, 422 |
| `GET` | `/api/v1/credit-notes` | List credit notes with status, type, and party filters | 200, 422 |
| `GET` | `/api/v1/credit-notes/work-queue` | Get Accounts credit note work queue (pending GS and active notes) | 200 |
| `GET` | `/api/v1/credit-notes/{id}` | Get detailed Credit Note with lines, rate verifications, and linked documents | 200, 422 |
| `POST` | `/api/v1/credit-notes/{id}/cancel` | Cancel an issued or draft Credit Note with reason | 200, 422 |
| `PATCH` | `/api/v1/credit-notes/{id}/gst-check` | Accounts verification of GST portal return reflection (GSTR-1/GSTR-2B) | 200, 422 |
| `POST` | `/api/v1/credit-notes/{id}/issue` | Issue Credit Note or Journal Voucher with accounting system voucher numbers (DEC-22) | 200, 422 |
| `PATCH` | `/api/v1/credit-notes/{id}/party-document` | Accounts verification of party document (Invoice, Debit Note, or none) | 200, 422 |
| `GET` | `/api/v1/credit-notes/{id}/print` | Get printable Credit Note Summary note (CN_SUMMARY) | 200, 422 |
| `POST` | `/api/v1/credit-notes/{id}/split` | Automatically split a mixed Credit Note (Good vs Repaired) into separate CN records | 200, 422 |
| `PATCH` | `/api/v1/credit-notes/{id}/type` | Set or update Credit Note type (GST_CN, GENERAL_CN, JV_ONLY) | 200, 422 |
| `GET` | `/api/v1/gs/{id}/cn-decision` | Get RM CN decision prefill & current decision status | 200, 422 |
| `POST` | `/api/v1/gs/{id}/cn-decision` | Record RM Step-7 CN decision (ALLOW_CN / DENY_CN_SEND_REPLACEMENT) | 201, 422 |


### custody (14 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/custody/intermediate-store/stock` | Intermediate Store Stock | 200, 422 |
| `GET` | `/api/v1/custody/lookups` | Lookups | 200 |
| `POST` | `/api/v1/custody/lots/{lot_id}/classify` | Classify | 201, 422 |
| `GET` | `/api/v1/custody/transfers` | List Transfers | 200, 422 |
| `POST` | `/api/v1/custody/transfers` | Initiate | 201, 422 |
| `GET` | `/api/v1/custody/transfers/{transfer_id}` | Detail | 200, 422 |
| `POST` | `/api/v1/custody/transfers/{transfer_id}/accept` | Accept | 200, 422 |
| `POST` | `/api/v1/custody/transfers/{transfer_id}/cancel` | Cancel | 200, 422 |
| `POST` | `/api/v1/custody/transfers/{transfer_id}/reconcile` | Reconcile | 200, 422 |
| `POST` | `/api/v1/custody/transfers/{transfer_id}/reconcile/approve` | Approve Adjustment | 200, 422 |
| `GET` | `/api/v1/custody/transfers/{transfer_id}/transfer-note` | Transfer Note | 200, 422 |
| `POST` | `/api/v1/custody/transfers/{transfer_id}/transfer-note/print` | Print Transfer Note | 200, 422 |
| `GET` | `/api/v1/gs/{gs_id}/handover` | Handover Preview | 200, 422 |
| `POST` | `/api/v1/gs/{gs_id}/handover` | Handover | 201, 422 |


### dismantling (10 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/dismantling/batches` | List Batches | 200, 422 |
| `POST` | `/api/v1/dismantling/batches` | Create Batch | 201, 422 |
| `GET` | `/api/v1/dismantling/batches/{id}` | Get Batch | 200, 422 |
| `POST` | `/api/v1/dismantling/batches/{id}/recover` | Recover Batch | 200, 422 |
| `GET` | `/api/v1/dismantling/containers` | List Containers | 200, 422 |
| `GET` | `/api/v1/dismantling/pcb-models` | List Pcb Models | 200 |
| `POST` | `/api/v1/dismantling/pcb-models` | Create Pcb Model | 201, 422 |
| `GET` | `/api/v1/dismantling/pcb-suppliers` | List Pcb Suppliers | 200 |
| `POST` | `/api/v1/dismantling/pcb-suppliers` | Create Pcb Supplier | 201, 422 |
| `GET` | `/api/v1/dismantling/queue` | Get Dismantling Queue | 200 |


### dispatch (5 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `POST` | `/api/v1/dispatches` | Record a replacement dispatch (SEND_NEW or SEND_REPAIRED) | 200, 422 |
| `GET` | `/api/v1/dispatches` | List replacement dispatches | 200, 422 |
| `GET` | `/api/v1/dispatches/candidate-lots` | Get candidate functional repaired lots available for replacement dispatch | 200, 422 |
| `GET` | `/api/v1/dispatches/queue` | Get pending replacement dispatch queue items | 200 |
| `GET` | `/api/v1/dispatches/{id}` | Get replacement dispatch details by ID | 200, 422 |


### goods-slips (12 endpoints)

Change plan 2026-11-12 Phase 2 (gate form v2): `POST /gs` and `PATCH /gs/{id}/gate` take
`values` (form v2: `return_type`, `gate_entry_date`, `gate_entry_no`, `carton_count`, …,
`no_document`) plus `documents: [{id?, doc_type_code, doc_no, doc_date, remarks}]` (AMD-04; rows
left out of a PATCH are removed). 409 `GATE_ENTRY_NO_TAKEN` = gate entry number already used in
the financial year (DEC-38). Goods slip responses carry `carton_count` (`box_count` is a
deprecated mirror), `return_type_code/label`, `gate_entry_date/no` and `documents[]` with
`files[]`. `GET /gs/gate-form` also returns `document_types`, `business_today`,
`max_backdate_days`. `GET /gs?q=` also matches the gate entry number and document numbers.

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `POST` | `/api/v1/gs` | Create Goods Slip | 201, 409, 422 |
| `GET` | `/api/v1/gs` | List Goods Slips | 200, 422 |
| `GET` | `/api/v1/gs/gate-form` | Get Gate Form | 200 |
| `GET` | `/api/v1/gs/lookups/parties` | Lookup Parties | 200, 422 |
| `GET` | `/api/v1/gs/lookups/statuses` | Goods-slip status labels (GS_STATUS option set, AMD-08) | 200 |
| `GET` | `/api/v1/gs/lookups/parties/by-location` | Distributors by state + station (AMD-06, DEC-35 fallback) | 200, 422, 503 |
| `GET` | `/api/v1/gs/lookups/states` | Lookup States | 200 |
| `GET` | `/api/v1/gs/lookups/stations` | Lookup Stations | 200, 422 |
| `GET` | `/api/v1/gs/lookups/transporters` | Lookup Transporters | 200, 422 |
| `GET` | `/api/v1/gs/{gs_id}` | Get Goods Slip | 200, 422 |
| `POST` | `/api/v1/gs/{gs_id}/cancel` | Cancel Goods Slip | 200, 422 |
| `PATCH` | `/api/v1/gs/{gs_id}/gate` | Edit Gate Details | 200, 422 |
| `GET` | `/api/v1/gs/{gs_id}/tag` | Get Gs Tag | 200, 422 |


### health (1 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/health` | Health | 200 |


### inspection (5 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `PUT` | `/api/v1/gs-items/{gs_item_id}/inspection` | Save Inspection Draft | 200, 422 |
| `POST` | `/api/v1/gs-items/{gs_item_id}/inspection/finalise` | Finalise Inspection | 200, 422 |
| `POST` | `/api/v1/gs-items/{gs_item_id}/inspection/reopen` | Reopen Inspection | 200, 422 |
| `GET` | `/api/v1/gs/{gs_id}/inspection` | Get Gs Inspection | 200, 422 |
| `POST` | `/api/v1/gs/{gs_id}/inspection/finalise-all` | Finalise All Lines | 200, 422 |


### inventory (10 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/inventory/adjustments` | List Adjustments | 200, 422 |
| `POST` | `/api/v1/inventory/adjustments` | Request Adjustment | 201, 422 |
| `POST` | `/api/v1/inventory/adjustments/{adjustment_id}/approve` | Approve Adjustment | 200, 422 |
| `POST` | `/api/v1/inventory/adjustments/{adjustment_id}/reject` | Reject Adjustment | 200, 422 |
| `POST` | `/api/v1/inventory/custody-assignment` | Custody Assignment | 201, 422 |
| `GET` | `/api/v1/inventory/lookups` | Lookups | 200 |
| `GET` | `/api/v1/inventory/lots/{lot_id}/stock-card` | Stock Card | 200, 422 |
| `GET` | `/api/v1/inventory/segregation-check` | Segregation Check | 200 |
| `GET` | `/api/v1/inventory/stock` | Stock | 200, 422 |
| `GET` | `/api/v1/inventory/stock/export` | Export Stock | 200, 422 |


### inventory:batteries (8 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/inventory/batteries/adjustments` | List Adjustments | 200, 422 |
| `POST` | `/api/v1/inventory/batteries/adjustments` | Request Adjustment | 201, 422 |
| `POST` | `/api/v1/inventory/batteries/adjustments/{id}/approve` | Approve Adjustment | 200, 422 |
| `POST` | `/api/v1/inventory/batteries/adjustments/{id}/reject` | Reject Adjustment | 200, 422 |
| `GET` | `/api/v1/inventory/batteries/balances` | Get Balances | 200 |
| `GET` | `/api/v1/inventory/batteries/movements` | List Movements | 200 |
| `POST` | `/api/v1/inventory/batteries/receipts` | Receive Batteries | 201, 422 |
| `GET` | `/api/v1/inventory/batteries/types` | List Types | 200 |


### itemization (13 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/csr-approvals/pending` | Pending Csr Approvals | 200, 422 |
| `POST` | `/api/v1/gs/{gs_id}/categorize` | Categorize | 200, 409, 422 |
| `POST` | `/api/v1/gs/{gs_id}/csr-decision` | Csr Decision | 200, 422 |
| `POST` | `/api/v1/gs/{gs_id}/csr-decision/reopen` | Reopen Csr Decision | 200, 422 |
| `POST` | `/api/v1/gs/{gs_id}/item-corrections/{correction_id}/decision` | Decide Correction | 200, 422 |
| `GET` | `/api/v1/gs/{gs_id}/itemization` | Itemization State | 200, 422 |
| `POST` | `/api/v1/gs/{gs_id}/items` | Add Item | 201, 422 |
| `PATCH` | `/api/v1/gs/{gs_id}/items/{item_id}` | Update Item | 200, 422 |
| `DELETE` | `/api/v1/gs/{gs_id}/items/{item_id}` | Delete Item | 204, 422 |
| `POST` | `/api/v1/gs/{gs_id}/items/{item_id}/corrections` | Request Correction | 201, 422 |
| `GET` | `/api/v1/item-corrections/pending` | Pending Corrections | 200, 422 |
| `GET` | `/api/v1/itemization/lookups/products` | Lookup Products | 200, 422 |
| `POST` | `/api/v1/lots/{lot_id}/packaging-check` | Packaging Check | 201, 422 |


### notifications (3 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/notifications/mine` | My Notifications | 200, 422 |
| `POST` | `/api/v1/notifications/read-all` | Mark All Read | 200 |
| `POST` | `/api/v1/notifications/{notification_id}/read` | Mark Read | 200, 422 |


### party-notifications (2 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/gs/{gs_id}/party-notifications` | Notification State | 200, 422 |
| `POST` | `/api/v1/gs/{gs_id}/party-notifications` | Record Notification | 201, 422 |


### pendency (2 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/pendencies` | List pendencies with optional status, goods slip, or date range filters | 200, 422 |
| `POST` | `/api/v1/pendencies/{id}/clear` | Clear an open pendency with resolution action and notes | 200, 422 |


### reports (13 endpoints, P4-02 — definitions in docs/REPORTS.md)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/reports` | Reports you may run, grouped | 200, 403 |
| `GET` | `/api/v1/reports/{code}` | Columns, filters (choices, defaults), your columns and saved filters | 200, 403, 404 |
| `GET` | `/api/v1/reports/{code}/data` | One page of rows (filters, sort, dir, page, page_size) + totals | 200, 403, 404, 422 |
| `GET` | `/api/v1/reports/{code}/export` | `format=csv|xlsx`, streamed; 422 EXPORT_TOO_LARGE | 200, 403, 404, 422 |
| `GET` | `/api/v1/reports/{code}/print` | Print payload (branding, filters used, generated by/at) | 200, 403, 404, 422 |
| `PUT` | `/api/v1/reports/{code}/columns` | Save your visible columns | 200, 403, 422 |
| `DELETE` | `/api/v1/reports/{code}/columns` | Reset your columns | 200, 403 |
| `POST` | `/api/v1/reports/{code}/saved-filters` | Save a named filter set | 201, 403, 409, 422 |
| `DELETE` | `/api/v1/reports/{code}/saved-filters/{filter_id}` | Delete your saved filter | 204, 403, 404 |
| `GET` | `/api/v1/admin/report-column-defaults` | Role default columns (reports.configure) | 200, 403 |
| `GET` | `/api/v1/admin/report-column-defaults/roles` | Roles a default can be set for | 200, 403 |
| `PUT` | `/api/v1/admin/report-column-defaults/{code}/{role_code}` | Set a role default (config_change_log) | 200, 403, 404, 422 |
| `DELETE` | `/api/v1/admin/report-column-defaults/{code}/{role_code}` | Remove a role default | 204, 403, 404 |


### rm-actions (5 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/gs/{id}/replacement-slip` | Get Replacement Slip print data (logged as document print) | 200, 422 |
| `GET` | `/api/v1/gs/{id}/resolution-board` | Get RM Resolution Board comparing planned actions with actual outcomes | 200, 422 |
| `GET` | `/api/v1/gs/{id}/rm-actions` | Get RM item-wise actions segregation state for a goods slip | 200, 422 |
| `PUT` | `/api/v1/gs/{id}/rm-actions` | Save RM item-wise actions segregation revision | 200, 422 |
| `POST` | `/api/v1/gs/{id}/rm-actions/finalise` | Finalise RM actions segregation and advance to Stage-2 Handover | 200, 422 |


### scrap (3 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/scrap` | List Scrap | 200, 422 |
| `POST` | `/api/v1/scrap/from-lot` | Mark Lot For Disposal | 201, 422 |
| `POST` | `/api/v1/scrap/{id}/dispose` | Dispose Scrap | 200, 422 |


### servicing (7 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/servicing/batches` | List Batches | 200, 422 |
| `POST` | `/api/v1/servicing/batches` | Allot Batch | 201, 422 |
| `GET` | `/api/v1/servicing/batches/{id}` | Get Batch | 200, 422 |
| `POST` | `/api/v1/servicing/batches/{id}/receive` | Receive Batch | 200, 422 |
| `GET` | `/api/v1/servicing/battery-reconciliation` | Get Battery Reconciliation | 200, 422 |
| `GET` | `/api/v1/servicing/intermediate-lots` | Get Intermediate Lots | 200 |
| `GET` | `/api/v1/servicing/technicians` | List Technicians | 200 |


### store-issue (6 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `POST` | `/api/v1/store-issues` | Issue functional stock from Intermediate Store to Main Store | 200, 422 |
| `GET` | `/api/v1/store-issues` | List store issues | 200, 422 |
| `GET` | `/api/v1/store-issues/candidate-lots` | Get candidate functional lots in Intermediate Store available for Main Store issue | 200 |
| `GET` | `/api/v1/store-issues/{id}` | Get store issue by ID | 200, 422 |
| `POST` | `/api/v1/store-issues/{id}/acknowledge` | Acknowledge receipt of store issue by Main Store | 200, 422 |
| `GET` | `/api/v1/store-issues/{id}/print` | Get printable Store Issue note data | 200, 422 |


### tasks (1 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/tasks/mine` | My Tasks | 200, 422 |


### attachments: gate document files (change plan 2026-11-12 Phase 2, AMD-04)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `POST` | `/api/v1/gs/{gs_id}/gate-documents/{document_id}/files/upload-url` | Signed upload for one image / PDF of a gate document row (kind `GATE_DOC`, S1_GATE performer, GS at the gate). Confirm with `POST /attachments/{id}/confirm`. | 201, 403, 404, 409 `GS_NOT_AT_GATE`, 422 `FILE_NOT_ALLOWED` |

### carton opening & counting (change plan 2026-11-12 Phase 3, AMD-04 / AMD-05 / AMD-08)

`GET /gs/{id}/unboxing` also returns `gate_documents`, `document_types` and the checklist fields
`carton_count` / `cartons_with_video`. `GET /gs/{id}/itemization` permissions add
`can_submit_counting`; `can_categorize` is true only in CATEGORISATION. Missing-evidence code
`VIDEO_PER_BOX` is now `VIDEO_PER_CARTON`.

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `POST` | `/api/v1/gs/{gs_id}/carton-documents` | Document row found at carton opening (Idempotency-Key); Invoice / Debit Note alert Accounts | 201, 403, 409 `GS_NOT_UNBOXING` / `GS_NO_DOCUMENT`, 422 |
| `PATCH` | `/api/v1/gs/{gs_id}/carton-documents/{doc_id}` | Correct a carton-opening row | 200, 409 `NOT_A_CARTON_DOCUMENT`, 422 |
| `DELETE` | `/api/v1/gs/{gs_id}/carton-documents/{doc_id}` | Remove a carton-opening row (and its files) | 204, 409 |
| `POST` | `/api/v1/gs/{gs_id}/counting/submit` | Counting (ITEMIZATION) → CATEGORISATION, ≥ 1 line (Idempotency-Key) | 200, 409 `COUNTING_ALREADY_SUBMITTED`, 422 `ITEMS_REQUIRED` |
| `GET` | `/api/v1/itemization/lookups/products` | Now also `category_id`, `subcategory_id` filters; `q` matches category / sub-category names | 200 |
| `GET` | `/api/v1/itemization/lookups/categories` | Categories with their sub-categories (counting filters) | 200 |

`POST /gs/{id}/categorize` now requires CATEGORISATION (409 `COUNTING_NOT_SUBMITTED` while counting).

### item field profiles (change plan 2026-11-12 Phase 4, AMD-10 / AMD-11 / AMD-16)

View needs `config:view`; changes need `config:configure`. Field groups: `CATEGORISATION`,
`DEPARTMENT`, `ACTION`, `ITEM_COUNT`. Resolution runs only in the DB function
`rms_private.resolve_item_field_profile[_for_scope]` (most specific scope with rows for a group wins).

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/config/item-field-profiles/fields` | Library (`field_group`, `include_inactive` filters) | 200, 403 |
| `POST` | `/api/v1/config/item-field-profiles/fields` | New field (Idempotency-Key); code derived from the label when omitted, immutable | 201, 409 `DUPLICATE_CODE`, 422 `FLAG_NOT_ALLOWED` / `FIELD_CODE_REQUIRED` |
| `PATCH` | `/api/v1/config/item-field-profiles/fields/{field_id}` | Label, description, sort, active, flags (code / group immutable, G-18) | 200, 404, 422 |
| `GET` | `/api/v1/config/item-field-profiles/scope` | `category_id` [+ `subcategory_id`] [+ `product_id`]: own / inherited / effective per group | 200, 404, 422 `SCOPE_MISMATCH` |
| `PUT` | `/api/v1/config/item-field-profiles/scope/{field_group}` | Replace this scope's fields for one group (`[]` = inherit again); idempotent by content | 200, 404, 422 `FIELD_GROUP_MISMATCH` / `FIELD_INACTIVE` / `SCOPE_MISMATCH` |
| `GET` | `/api/v1/config/item-field-profiles/resolve/{product_id}` | Effective profile of a product, live or `version_id` | 200, 404 `PROFILE_VERSION_NOT_FOUND` |
| `GET` | `/api/v1/config/item-field-profiles/versions` | Profile versions (one per committed change, insert-only) | 200 |

RM action options (`GET /gs/{id}/rm-actions`) now come from the ACTION library; stored actions carry
an `action_label` snapshot.

### RM final actions & A/c Actions slip (change plan 2026-11-12 Phase 7, AMD-16 / AMD-17, G-21)

Permissions `final_actions`: view (RM, Accounts, Intermediate Store, Management), edit (RM: save),
approve (RM: finalise), export (RM, Accounts: print). Only for a GS on the AMD-13 flow (transfer
slip / held at the intermediate store); older GS use `rm-actions` (which now answers 409
`USE_FINAL_ACTIONS` for an AMD-13 GS).

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/gs/{gs_id}/final-actions` | Per item counted / at departments / available (counted − at departments) / outcome heads, allowed actions (resolved ACTION profile, GS profile version), current split, revisions, slip versions with print counts, finalise blockers | 200, 403, 404 `GS_NOT_FOUND` |
| `PUT` | `/api/v1/gs/{gs_id}/final-actions` | Save a new revision of the split (Idempotency-Key). Every line exactly once; Σ action qty = available qty; `reason` required to revise finalised actions (supersedes the slip) | 200, 409 `G-21` / `INVALID_GS_STATUS` / `NOT_ON_FINAL_ACTION_FLOW`, 422 `REASON_REQUIRED` / `NO_CHANGE` / `LINES_MISSING` / `DUPLICATE_LINE` / `DUPLICATE_ACTION` / `ITEM_NOT_IN_GS` |
| `POST` | `/api/v1/gs/{gs_id}/final-actions/finalise` | Finalise (Idempotency-Key, body `{remarks}`): nothing at a department, split = counted; renders the server-side PDF (template `AC_ACTIONS_SLIP`), stores it (attachment `GENERATED_PDF`), creates slip version n (series `AC_ACTION_SLIP`), notifies Accounts (`AC_ACTIONS_SLIP_READY`) | 200, 409 `G-21` / `ALREADY_FINALISED` / `TEMPLATE_NOT_PUBLISHED`, 503 `STORAGE_ERROR` |
| `POST` | `/api/v1/gs/{gs_id}/final-actions/slips/{slip_id}/print` | Print / re-print any version: logs `print_logs`, returns a short-lived URL of the stored PDF | 200, 403, 404 `SLIP_NOT_FOUND` |

### unboxing (11 endpoints)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/accounts/document-queue` | Accounts Document Queue | 200, 422 |
| `GET` | `/api/v1/accounts/document-queue/classifications` | Queue Classifications | 200 |
| `POST` | `/api/v1/accounts/document-queue/{gs_id}/acknowledge` | Acknowledge Documents | 200, 422 |
| `POST` | `/api/v1/gs/{gs_id}/documents` | Classify Document | 201, 422 |
| `PATCH` | `/api/v1/gs/{gs_id}/documents/{doc_id}` | Update Document | 200, 422 |
| `POST` | `/api/v1/gs/{gs_id}/missing-doc-exception` | Request Missing Doc Exception | 201, 422 |
| `POST` | `/api/v1/gs/{gs_id}/missing-doc-exception/{exception_id}/decision` | Decide Missing Doc Exception | 200, 422 |
| `GET` | `/api/v1/gs/{gs_id}/unboxing` | Unboxing State | 200, 422 |
| `POST` | `/api/v1/gs/{gs_id}/unboxing/complete` | Complete Unboxing | 200, 422 |
| `POST` | `/api/v1/gs/{gs_id}/unboxing/start` | Start Unboxing | 200, 422 |
| `GET` | `/api/v1/missing-doc-exceptions/pending` | Pending Missing Doc Exceptions | 200, 422 |


### users — user administration (P1-05, DEC-50; 2026-11-14)

Permissions: `users.view` (read), `users.create`, `users.edit` (profile, roles, status, password, overrides),
`users.configure` (departments). Super-Admin-only and self-protection rules: DEC-50.

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/admin/users` | Page of users; query `search`, `role`, `department_id`, `status=active\|inactive`, `page`, `page_size` | 200, 403 |
| `POST` | `/api/v1/admin/users` | Create (Supabase admin API): email, full name, employee code, phone, department, `role_codes`, `is_super_admin`, `initial_password`, `must_change_password` | 201, 403 `SUPER_ADMIN_REQUIRED`, 409 `EMAIL_TAKEN` / `EMPLOYEE_CODE_TAKEN`, 422 `UNKNOWN_ROLE` / `SUPER_ADMIN_ROLE_VIA_FLAG` / password policy |
| `GET` | `/api/v1/admin/users/{id}` | One user | 200, 404 |
| `PATCH` | `/api/v1/admin/users/{id}` | Profile fields, department, `role_codes`, `is_super_admin`, optional `reason` | 200, 403 `SELF_CHANGE_FORBIDDEN` / `SUPER_ADMIN_REQUIRED`, 409 `LAST_SUPER_ADMIN` |
| `POST` | `/api/v1/admin/users/{id}/deactivate` | `{reason}`; API access ends at once, sign-in banned | 200, 403, 409 `LAST_SUPER_ADMIN` |
| `POST` | `/api/v1/admin/users/{id}/reactivate` | `{reason}` | 200, 403 |
| `POST` | `/api/v1/admin/users/{id}/reset-password` | `{temporary_password, reason}`; sets `must_change_password` | 200, 403, 422 |
| `GET` | `/api/v1/admin/users/{id}/effective-permissions` | Role grants + live overrides (deny wins, expired ignored) | 200, 404 |
| `GET` | `/api/v1/admin/users/{id}/overrides` | Overrides incl. `is_expired` | 200, 404 |
| `PUT` | `/api/v1/admin/users/{id}/overrides` | Replace all: `[{module_code, action, effect, reason, expires_at}]` | 200, 403 `SELF_CHANGE_FORBIDDEN`, 422 `UNKNOWN_PERMISSION` / `OVERRIDE_EXPIRED` |
| `GET` | `/api/v1/admin/departments` | Departments with user counts | 200 |
| `POST` | `/api/v1/admin/departments` | `{code, name}` (`users.configure`) | 201, 409 `DEPARTMENT_CODE_TAKEN` |
| `PATCH` | `/api/v1/admin/departments/{id}` | `{name?, is_active?}` | 200, 404 |
| `POST` | `/api/v1/me/password` | Signed-in user sets a new password; clears `must_change_password` | 204, 422 |

While `must_change_password` is set, every endpoint except `GET /me` and `POST /me/password` answers
403 `PASSWORD_CHANGE_REQUIRED`. `GET /me` returns `profile.must_change_password`.

### roles — roles & permission matrix (P1-05)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/api/v1/admin/roles` | Roles with user and permission counts (`roles.view`) | 200 |
| `POST` | `/api/v1/admin/roles` | `{code, name, description?}` (`roles.create`) | 201, 409 `ROLE_CODE_TAKEN` |
| `PATCH` | `/api/v1/admin/roles/{id}` | `{name?, description?}` (`roles.edit`) | 200, 404 |
| `DELETE` | `/api/v1/admin/roles/{id}` | Non-system role with no users or references (`roles.delete`) | 204, 409 `ROLE_IS_SYSTEM` / `ROLE_IN_USE` |
| `GET` | `/api/v1/admin/permissions` | Permission catalogue (module × action) | 200 |
| `GET` | `/api/v1/admin/roles/{id}/permissions` | Role grants with scope | 200, 404 |
| `PUT` | `/api/v1/admin/roles/{id}/permissions` | Replace the matrix `{permissions:[{module_code, action, scope}], reason?}` (`roles.configure`) | 200, 403 `SELF_CHANGE_FORBIDDEN`, 409 `ROLE_MATRIX_LOCKED` |

### health (production audit 2026-11-14)

| Method | Endpoint | Summary | Expected Responses |
|---|---|---|---|
| `GET` | `/health`, `/api/v1/health` | Liveness (no DB) | 200 |
| `GET` | `/health/ready`, `/api/v1/health/ready` | Readiness: DB `select 1`; no connection details | 200, 503 |

`/docs`, `/redoc` and `/openapi.json` are not served when `APP_ENV=prod`. The four config snapshot
endpoints (`/config/forms/{code}/published`, `/config/workflow/{code}/published`,
`/config/templates/{code}/published`, `POST /config/forms/{code}/validate-submission`) now need any active signed-in user.
