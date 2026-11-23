# Release: 12-step Offline Return → Replacement flow (P1 – P12)

**Branch:** `feature/offline-flow-20-11-2026` (not pushed) · **Prepared:** 2026-11-23 (Phase P12)
**Status:** NOT deployed. The user approves the push and the production run separately.
**Production:** Supabase Cloud (Free plan: no automatic backups) + Render (`rms-api`, `rms-worker`,
`rms-web`). Last migration known on production: `20261119000100_dec59_thermometer_masters.sql`
(pushed 2026-11-19).

Do the steps in order. Stop at the first surprise.

## 1. First check (read-only)

```powershell
supabase migration list --linked
```

Expected: every migration up to `20261119000100` is applied on **Remote**, and exactly the 14 files
in step 4 are missing. Anything else missing or extra → stop and compare before going on.

## 2. Backup (DEPLOY_HELPER.md §8, step 1)

```powershell
$d = Get-Date -Format yyyyMMdd
New-Item -ItemType Directory -Force "backups/prod-before-offline-flow-$d"
supabase db dump --linked -f "backups/prod-before-offline-flow-$d/schema.sql"
supabase db dump --linked --data-only --use-copy -f "backups/prod-before-offline-flow-$d/data.sql"
supabase db dump --linked --role-only -f "backups/prod-before-offline-flow-$d/roles.sql"
```

Check the three files are not empty. Keep them out of Git.

## 3. Push the code (needs the user's approval)

Merge / push `feature/offline-flow-20-11-2026`. Render is deployed only in step 6, after the database.

## 4. Migrations (one `supabase db push`)

```powershell
supabase db push --linked --dry-run   # must list exactly these, in this order
supabase db push --linked
```

| # | Migration | Phase |
|---|---|---|
| 1 | `20261120000100_p1_intermediate_stores.sql` | P1 roles, Intermediate Stores, mapping |
| 2 | `20261120000200_p2_gate_v4_documents.sql` | P2 gate documents v4 |
| 3 | `20261120000300_p3_unboxing_carton_document_g02.sql` | P3 G-02 = video per carton |
| 4 | `20261120000400_p3_carton_doc_clears_no_document.sql` | P3 follow-up (Q27) |
| 5 | `20261120000500_p4_categorisation_lock.sql` | P4 categorisation lock |
| 6 | `20261121000100_p5_transfer_slips.sql` | P5 transfer slips |
| 7 | `20261121000200_p6_store_acknowledgement.sql` | P6 store acknowledgement |
| 8 | `20261121000300_p7_store_department_routing.sql` | P7 store routing |
| 9 | `20261121000400_p7_store_routing_undo.sql` | P7 follow-up (Q32) |
| 10 | `20261121000500_p8_store_receiving.sql` | P8 store receiving |
| 11 | `20261123000100_p9_store_analysis.sql` | P9 store analysis |
| 12 | `20261123000200_p9_approval_after_submission.sql` | P9 follow-up (Q36) |
| 13 | `20261123000300_p10_management_approval.sql` | P10 Management approval |
| 14 | `20261123000400_p11_accounts_replacement_dispatch.sql` | P11 Accounts, Replacement Slip, Dispatch |

(14 files; P12 adds no migration.)

## 5. Release snippets (role grants, menus, labels, templates)

Run each file once, in this order, in the Supabase SQL editor or with
`psql "<admin url>" -X -v ON_ERROR_STOP=1 -f <file>`. All are idempotent. Read the NOTICE lines: the
"hide legacy menu" snippets only hide a menu when no goods slip from the earlier flow still needs it,
and print the count otherwise (re-run them later).

| # | Snippet (`supabase/snippets/`) | Phase |
|---|---|---|
| 1 | `release_20261120_roles_intermediate_stores.sql` | P1 |
| 2 | `release_20261120_gate_v4.sql` | P2 |
| 3 | `release_20261120_p3_unboxing.sql` | P3 |
| 4 | `release_20261120_p4_categorisation_lock.sql` | P4 |
| 5 | `release_20261121_p5_transfer_slips.sql` | P5 |
| 6 | `release_20261121_p6_store_acknowledgement.sql` | P6 |
| 7 | `release_20261121_p7_store_routing.sql` | P7 |
| 8 | `release_20261121_p7_hide_legacy_routing_menus.sql` | P7 follow-up (Q33, conditional) |
| 9 | `release_20261121_p8_store_receiving.sql` | P8 |
| 10 | `release_20261123_p9_store_analysis.sql` | P9 |
| 11 | `release_20261123_p10_management_approval.sql` | P10 |
| 12 | `release_20261123_p11_accounts_replacement_slip.sql` | P11 |
| 13 | `release_20261123_p12_hide_legacy_menus.sql` | P12 (DEC-72, conditional) |

## 6. Deploy the apps

Render → `rms-api`, `rms-worker`, `rms-web` → **Manual Deploy → Deploy latest commit**. The HICKS logo
for the PDFs ships with the backend (`backend/app/assets/branding/hicks-logo.png`, setting
`branding_print_logo`).

## 7. After the deploy

1. DEPLOY_HELPER.md step 2.7 + the smoke test in step 6.
2. **Create the new users** (Administration → Users): one or more users per Intermediate Store role
   (`ISTORE_OP`, `ISTORE_DT`, `ISTORE_RI`) and the Management approver (`MANAGEMENT`). The local
   UAT users (`opstore@`, `dtstore@`, `ristore@`, `mgmt@rms.local`) exist only in the local database.
3. Check Administration → Intermediate Stores: OP / DT / RI and their category mapping (Q4 default:
   OP = ENCLOSED_OVAL + PRISMATIC, DT = DMT, RI = GENERAL). See open question **Q43** (GENERAL products
   have no condition fields, so nothing reaches RI with today's masters).
4. Sign in as each role and compare the menu with `docs/USER_GUIDE.md` §1.3.
5. If a screen shows "Menu unavailable" or a 500: `supabase migration list --linked` first (2026-11-18
   incident: code deployed before its migrations).

## 8. Roll back

Restore from the step-2 backup (DEPLOY_HELPER.md §7) and redeploy the previous commit on Render.
Migrations are never edited; a fix goes into a new migration.
