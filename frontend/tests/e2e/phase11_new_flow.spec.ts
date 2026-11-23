/**
 * Phase 11 E2E test suite (Change plan 2026-11-12; AMD-01..AMD-22; G-02, G-19..G-22).
 *
 * Exercises the complete new workflow against the REAL local stack:
 * 1. Offline gate entry with backdated date & multiple documents (incl. courier slip) (AMD-01..04)
 *    -> Immediate Accounts alert for Invoice (AMD-05)
 *    -> Carton opening with video per carton (AMD-03, G-02)
 *    -> Counting (AMD-08)
 *    -> Item-level categorisation buckets (AMD-09, G-19) + counts (AMD-11)
 *    -> RM review & approve (AMD-12, AMD-13)
 *    -> Transfer slip -> Intermediate store hold (AMD-13)
 *    -> Department round-trip with partial outcomes & reconciliation (AMD-14, AMD-15, G-20)
 *    -> RM final actions split & Replacement Slip PDF (AMD-16, AMD-17, G-21)
 *    -> Accounts entry per action line (AMD-18)
 *    -> Dispatch slip PDF & dispatch (AMD-19, G-22)
 * 2. E-commerce return path (AMD-01, DEC-39: no gate entry date/number)
 * 3. Rejecting test for EVERY new guard:
 *    - G-02 (updated): reject completing carton opening with missing carton videos
 *    - G-19: reject item categorisation if bucket sum != counted qty
 *    - G-20: reject department routing dispatch exceeding in-store available qty
 *    - G-21: reject final action split mismatch & direct editing of finalised slip
 *    - G-22: reject invalid field per action flag, future dates, early completion & double dispatch
 *
 * After each scenario: scripts/integrity_check.sql must report 0 violations across IC-01..IC-12.
 */

import { expect, test, type Browser, type Page } from '@playwright/test';

import {
  acceptStoreTransfer,
  addCartonDocument,
  addItemAndSubmitCount,
  approveRmReview,
  completeCartonOpening,
  createEcommerceGs,
  createOfflineGs,
  dispatchRouting,
  dispatchSlip,
  ensureFieldProfiles,
  finaliseFinalActions,
  getDmtProduct,
  receiveRouting,
  saveAndCompleteAccountsEntry,
  submitItemCategorisation,
  TODAY,
  uploadCartonVideos,
  uploadClassifiedDocPhoto,
} from './support/phase11';
import { integrityViolations } from './support/lifecycle';
import {
  api,
  ApiError,
  apiAvailable,
  asUser,
  expectNoHorizontalOverflow,
  GATE_PROJECTS,
  USERS,
  type Device,
} from './support/stack';

const devices: Device[] = [];

async function openPage(browser: Browser, email: string, path: string): Promise<Page> {
  const d = await asUser(browser, email, path);
  devices.push(d);
  return d.page;
}

test.describe('Phase 11: End-to-End Workflow & System Guards', () => {
  // DEC-64 (P4): categorisation is locked, not submitted to RM review; the path to the Intermediate Store is the P5 transfer slip. Rebuild this flow in P5.
  test.fixme(
    true,
    'Earlier flow (RM review / RM final actions), retired by DEC-64 … DEC-71; superseded by offline_replacement_flow.spec.ts (P12)',
  );
  test.describe.configure({ timeout: 240_000 });

  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(
      !GATE_PROJECTS.includes(testInfo.project.name),
      'Scenarios run on desktop-chrome and mobile-pixel-7',
    );
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  test.afterEach(async () => {
    const opened = devices.splice(0);
    for (const d of opened) {
      expect(d.errors, `Console errors detected on ${d.page.url()}`).toEqual([]);
      await d.context.close();
    }
    // Integrity check verification across all invariants IC-01..IC-12
    expect(integrityViolations()).toEqual([]);
  });

  // ===============================================================================================
  // SCENARIO 1: Full New Flow (Offline Return)
  // ===============================================================================================
  test('L-09: Full Offline Return Flow: Gate backdate/multi-docs -> Carton opening -> Counting -> Categorisation -> RM review -> Store hold -> Dept round-trip -> Final actions -> Accounts -> Dispatch', async ({
    browser,
  }) => {
    const tag = `PH11-${Date.now().toString().slice(-6)}`;
    const { repairDeptId } = await ensureFieldProfiles();
    const product = await getDmtProduct();

    // 1. GATE INWARD (Anuj, GATE_INWARD): Offline return with backdated date, numeric entry no., and multiple docs
    const backdate = new Date(Date.now() - 3 * 86400000).toISOString().slice(0, 10);
    const gateEntryNo = 800000 + Math.floor(Math.random() * 100000);
    const gs = await createOfflineGs({
      tag,
      cartonCount: 2,
      gateEntryDate: backdate,
      gateEntryNo,
      // Gate form v4 (DEC-62): image-only rows, transport + party document.
      documents: [
        { doc_type_code: 'COURIER_SLIP', source: 'TRANSPORT' },
        { doc_type_code: 'INVOICE', source: 'PARTY' },
      ],
    });

    // Verify UI view of the created Goods Slip (Anuj / Desktop + Mobile check)
    const gatePage = await openPage(browser, USERS.gate, `/gs/${gs.id}`);
    await expect(gatePage.getByText(gs.gs_no)).toBeVisible({ timeout: 15_000 });
    await expect(gatePage.getByText(/Offline Return/i)).toBeVisible();
    await expect(gatePage.getByText(String(gateEntryNo))).toBeVisible();
    await expectNoHorizontalOverflow(gatePage);

    // Verify Accounts was immediately alerted for the INVOICE document (AMD-05)
    const notifications = await api<{
      items: Array<{ title: string; body: string | null; gs_id: string | null }>;
    }>(USERS.accounts, 'GET', '/notifications/mine?limit=10');
    expect(
      notifications.items.some(
        (n) =>
          n.gs_id === gs.id ||
          (n.body && (n.body.includes(gs.gs_no) || n.body.includes(`INV-${tag}`))),
      ),
    ).toBe(true);

    // 2. CARTON OPENING (Aman, INWARD_VERIFIER): Video per carton (AMD-03, G-02) + carton document
    const unboxingPage = await openPage(browser, USERS.aman, `/gs/${gs.id}/unboxing`);
    await expect(unboxingPage.getByRole('heading', { name: /Carton Opening/i })).toBeVisible();
    await expectNoHorizontalOverflow(unboxingPage);

    await api(USERS.aman, 'POST', `/gs/${gs.id}/unboxing/start`, {});
    // Upload video for each of the 2 cartons
    await uploadCartonVideos(gs.id, 2);
    // P3 / DEC-62: one optional carton document (type + photo, no number / date)
    await addCartonDocument(gs.id, { doc_type_code: 'DEBIT_NOTE' });
    // Complete carton opening
    await completeCartonOpening(gs.id);

    // 3. COUNTING (Aman, INWARD_VERIFIER): Add items with received qty
    const itemId = await addItemAndSubmitCount(gs.id, product.id, 10);

    // 4. CATEGORISATION (Aman, INWARD_VERIFIER): Item-level buckets + auxiliary counts (AMD-09, G-19, AMD-11)
    const catPage = await openPage(browser, USERS.aman, `/gs/${gs.id}/itemization`);
    await expect(catPage.getByRole('heading', { name: /Categorisation/i })).toBeVisible();
    await expectNoHorizontalOverflow(catPage);

    // Split 10 pcs: 6 DMT_OK_PACKED, 4 DMT_BROKEN_BODY (sum = 10 satisfies G-19)
    await submitItemCategorisation(
      gs.id,
      itemId,
      { DMT_OK_PACKED: 6, DMT_BROKEN_BODY: 4 },
      { PACKAGING: 10, CONTAINER: 10, USER_MANUAL: 10 },
    );

    // 5. RM REVIEW & APPROVAL (Pratham, REPLACEMENT_MANAGER): Whole GS at a glance -> auto Transfer Slip (AMD-12, AMD-13)
    const rmReviewPage = await openPage(browser, USERS.rm, `/gs/${gs.id}/rm-review`);
    await expect(rmReviewPage.getByRole('heading', { name: /RM Review/i })).toBeVisible();
    await expect(rmReviewPage.getByText(gs.gs_no)).toBeVisible();
    await expectNoHorizontalOverflow(rmReviewPage);

    const transferId = await approveRmReview(gs.id);
    expect(transferId).toBeTruthy();

    // 6. INTERMEDIATE STORE HOLD (Sahil, INTERMEDIATE_STORE_MANAGER): Accept transfer -> GS held (AMD-13)
    const transferPage = await openPage(browser, USERS.sahil, `/custody/transfers/${transferId}`);
    await expect(transferPage.getByRole('heading', { name: /Custody transfer/i })).toBeVisible();
    await expectNoHorizontalOverflow(transferPage);

    await acceptStoreTransfer(transferId);

    // Verify GS status is HELD_AT_INTERMEDIATE_STORE
    const gsAfterTransfer = await api<{ goods_slip: { status: string } }>(
      USERS.rm,
      'GET',
      `/gs/${gs.id}`,
    );
    expect(gsAfterTransfer.goods_slip.status).toBe('HELD_AT_INTERMEDIATE_STORE');

    // 7. DEPARTMENT ROUND-TRIP (Pratham, RM & Aman, INWARD_VERIFIER): Partial receipts & G-20 conservation
    const deptRoutingPage = await openPage(browser, USERS.rm, '/department-routing');
    await expect(
      deptRoutingPage.getByRole('heading', { name: /Department Routing Queue/i }),
    ).toBeVisible();
    await expectNoHorizontalOverflow(deptRoutingPage);

    // RM dispatches 4 pieces to REPAIR department
    const routing = await dispatchRouting(gs.id, itemId, repairDeptId, 4);
    expect(routing.lines.length).toBeGreaterThan(0);
    const lineId = routing.lines[0]?.id ?? '';

    // Receiver (Aman) opens receiving queue
    const receivingPage = await openPage(browser, USERS.aman, '/department-receiving');
    await expect(
      receivingPage.getByRole('heading', { name: /Department Receiving Queue/i }),
    ).toBeVisible();
    await expectNoHorizontalOverflow(receivingPage);

    // Receiver books partial returns: 3 Repaired (returned to store) + 1 Wastage (scrap)
    await receiveRouting(routing.id, lineId, [
      { outcome_head_code: 'REPAIRED', qty_received: 3 },
      { outcome_head_code: 'WASTAGE', qty_received: 1 },
    ]);

    // Verify G-20 reconciliation: counted (10) = in store (6) + at dept (0) + outcomes (4) + actioned (0)
    const recon = await api<{
      items: Array<{
        counted_qty: number;
        in_store_qty: number;
        at_departments_qty: number;
        outcome_heads_qty: number;
        actioned_qty: number;
      }>;
    }>(USERS.rm, 'GET', `/department-routing/gs/${gs.id}/reconciliation`);
    const reconItem = recon.items[0];
    expect(reconItem).toBeDefined();
    if (!reconItem) throw new Error('reconItem not found');
    expect(reconItem.counted_qty).toBe(10);
    expect(reconItem.in_store_qty).toBe(6);
    expect(reconItem.at_departments_qty).toBe(0);
    expect(reconItem.outcome_heads_qty).toBe(4);
    expect(reconItem.actioned_qty).toBe(0);

    // 8. RM FINAL ACTIONS SPLIT & A/C ACTIONS PDF (Pratham, RM) (AMD-16, AMD-17, G-21)
    const finalActionsPage = await openPage(browser, USERS.rm, `/gs/${gs.id}/final-actions`);
    await expect(finalActionsPage.getByRole('heading', { name: /Final Actions/i })).toBeVisible();
    await expectNoHorizontalOverflow(finalActionsPage);

    // Split 10 pcs: 5 Send New, 3 Send Repaired, 2 Issue CN (sum = 10 satisfies G-21)
    const acSlipId = await finaliseFinalActions(gs.id, itemId, {
      SEND_NEW: 5,
      SEND_REPAIRED: 3,
      ISSUE_CN: 2,
    });
    expect(acSlipId).toBeTruthy();

    // 9. ACCOUNTS ENTRY (Deepak, ACCOUNTS): Enter required data per action flags (AMD-18, G-22)
    const acEntryPage = await openPage(browser, USERS.accounts, `/accounts-entry/${gs.id}`);
    await expect(acEntryPage.getByRole('heading', { name: /Accounts Entry/i })).toBeVisible();
    await expectNoHorizontalOverflow(acEntryPage);

    const acState = await api<{
      lines: Array<{
        id: string;
        action_code: string;
        requires_cn: boolean;
        requires_challan: boolean;
      }>;
    }>(USERS.accounts, 'GET', `/ac-entry/gs/${gs.id}`);

    const acLinesPayload = acState.lines.map((ln) => {
      if (ln.requires_cn) {
        return {
          action_line_id: ln.id,
          cn_no: `CN-${tag}`,
          cn_date: TODAY,
          cn_value: 2500.0,
        };
      }
      return {
        action_line_id: ln.id,
        challan_no: `CH-${ln.action_code}-${tag}`,
        challan_date: TODAY,
      };
    });

    const dispatchSlipId = await saveAndCompleteAccountsEntry(gs.id, acSlipId, acLinesPayload);
    expect(dispatchSlipId).toBeTruthy();

    // 10. DISPATCH (Dispatch Team): Issue goods against Dispatch Slip (AMD-19)
    const dispatchSlipsPage = await openPage(browser, USERS.dispatch, '/dispatch-slips');
    await expect(dispatchSlipsPage.getByRole('heading', { name: /Dispatch Slips/i })).toBeVisible();
    await expectNoHorizontalOverflow(dispatchSlipsPage);

    await dispatchSlip(dispatchSlipId);

    // Verify Dispatch Slip status is DISPATCHED
    const slip = await api<{ status: string; lines: Array<{ qty: number }> }>(
      USERS.dispatch,
      'GET',
      `/dispatch-slips/${dispatchSlipId}`,
    );
    expect(slip.status).toBe('DISPATCHED');
    // Lines that ship goods: 5 Send New + 3 Send Repaired = 8 pcs
    const shippedQty = slip.lines.reduce((s, l) => s + l.qty, 0);
    expect(shippedQty).toBe(8);
  });

  // ===============================================================================================
  // SCENARIO 2: E-Commerce Return Path
  // ===============================================================================================
  test('L-10: E-Commerce Return Path: No gate date/number -> Carton opening -> Counting -> Categorisation -> RM approve -> Final actions -> Accounts closure', async ({
    browser,
  }) => {
    const tag = `ECOM-${Date.now().toString().slice(-6)}`;
    await ensureFieldProfiles();
    const product = await getDmtProduct();

    // 1. Gate entry with return_type = 'ECOMMERCE_RETURN' (no gate_entry_date or gate_entry_no, DEC-39)
    const gs = await createEcommerceGs({ tag, cartonCount: 1 });

    const gatePage = await openPage(browser, USERS.gate, `/gs/${gs.id}`);
    await expect(gatePage.getByText(gs.gs_no)).toBeVisible({ timeout: 15_000 });
    await expect(gatePage.getByText(/E-Commerce Return/i)).toBeVisible();
    await expectNoHorizontalOverflow(gatePage);

    // 2. Carton opening with 1 video for 1 carton
    await api(USERS.aman, 'POST', `/gs/${gs.id}/unboxing/start`, {});
    await uploadCartonVideos(gs.id, 1, 1);
    await uploadClassifiedDocPhoto(gs.id, `DN-${tag}`);
    await completeCartonOpening(gs.id);

    // 3. Counting: 5 units received
    const itemId = await addItemAndSubmitCount(gs.id, product.id, 5);

    // 4. Categorisation: 5 units -> DMT_BROKEN_BODY (all 5 units)
    await submitItemCategorisation(
      gs.id,
      itemId,
      { DMT_BROKEN_BODY: 5 },
      { PACKAGING: 5, CONTAINER: 5, USER_MANUAL: 5 },
    );

    // 5. RM Review & Approval -> Transfer Slip
    const transferId = await approveRmReview(gs.id);
    await acceptStoreTransfer(transferId);

    // 6. RM Final Actions: 5 units -> ISSUE_CN
    const acSlipId = await finaliseFinalActions(gs.id, itemId, {
      ISSUE_CN: 5,
    });
    expect(acSlipId).toBeTruthy();

    // 7. Accounts Entry: Issue CN (no goods to ship, no dispatch slip generated)
    const acState = await api<{
      lines: Array<{ id: string; action_code: string }>;
    }>(USERS.accounts, 'GET', `/ac-entry/gs/${gs.id}`);
    const firstAcLine = acState.lines[0];
    expect(firstAcLine).toBeDefined();

    await saveAndCompleteAccountsEntry(gs.id, acSlipId, [
      {
        action_line_id: firstAcLine?.id ?? '',
        cn_no: `CN-ECOM-${tag}`,
        cn_date: TODAY,
        cn_value: 1250.0,
      },
    ]);

    // Verify GS status
    const gsStatus = await api<{ goods_slip: { status: string } }>(USERS.rm, 'GET', `/gs/${gs.id}`);
    expect(['IN_PROCESS', 'AWAITING_NOTIFICATION', 'CLOSED']).toContain(gsStatus.goods_slip.status);
  });

  // ===============================================================================================
  // SCENARIO 3: System Guards Rejecting Tests (G-02, G-19, G-20, G-21, G-22)
  // ===============================================================================================
  test('Guards rejection: Every new system guard (G-02, G-19, G-20, G-21, G-22) strictly rejects invalid operations', async () => {
    const tag = `GUARD-${Date.now().toString().slice(-6)}`;
    const { repairDeptId } = await ensureFieldProfiles();
    const product = await getDmtProduct();

    // --- GUARD G-02 (updated): Video mandatory per carton ---
    const gsGuard = await createOfflineGs({ tag, cartonCount: 2 });
    // Start unboxing and upload doc photo + video for carton 1 only
    await api(USERS.aman, 'POST', `/gs/${gsGuard.id}/unboxing/start`, {});
    await uploadClassifiedDocPhoto(gsGuard.id, `INV-${tag}`);
    await uploadCartonVideos(gsGuard.id, 1, 1);
    // Attempting to complete with only 1 video for 2 cartons MUST BE REJECTED by G-02
    let g02Rejected = false;
    try {
      await api(USERS.aman, 'POST', `/gs/${gsGuard.id}/unboxing/complete`, {});
    } catch (err) {
      g02Rejected = err instanceof ApiError && (err.status === 422 || err.status === 409);
    }
    expect(
      g02Rejected,
      'G-02 must reject carton opening when carton video count < carton count',
    ).toBe(true);

    // Provide the 2nd carton video and complete legitimately
    await uploadCartonVideos(gsGuard.id, 1, 2);
    await completeCartonOpening(gsGuard.id);

    // Counting: 10 units
    const itemId = await addItemAndSubmitCount(gsGuard.id, product.id, 10);

    // --- GUARD G-19: Bucket conservation (sum of bucket qty = counted qty) ---
    // Counted is 10; attempt to submit categorisation with only 8 units (6 + 2)
    let g19Rejected = false;
    try {
      await api(
        USERS.aman,
        'PUT',
        `/gs/${gsGuard.id}/items/${itemId}/categorisation`,
        {
          buckets: [
            { field_code: 'DMT_OK_PACKED', qty: 6 },
            { field_code: 'DMT_BROKEN_BODY', qty: 2 },
          ],
          counts: [{ count_type: 'PACKAGING', count_value: 10 }],
        },
        true,
      );
      await api(
        USERS.aman,
        'POST',
        `/gs/${gsGuard.id}/categorisation/submit`,
        { category_code: 'REGULAR_RETURN' },
        true,
      );
    } catch (err) {
      g19Rejected = err instanceof ApiError && (err.status === 422 || err.status === 409);
    }
    expect(g19Rejected, 'G-19 must reject categorisation when sum of buckets != counted qty').toBe(
      true,
    );

    // Categorise legitimately with exact conservation (6 + 4 = 10)
    await submitItemCategorisation(gsGuard.id, itemId, { DMT_OK_PACKED: 6, DMT_BROKEN_BODY: 4 });
    const transferId = await approveRmReview(gsGuard.id);
    await acceptStoreTransfer(transferId);

    // --- GUARD G-20: Quantity conservation across store and departments ---
    // Intermediate store holds 10 units. Attempt to dispatch 15 units to REPAIR department
    let g20Rejected = false;
    try {
      await api(
        USERS.rm,
        'POST',
        '/department-routing/dispatch',
        {
          gs_id: gsGuard.id,
          department_field_id: repairDeptId,
          lines: [{ gs_item_id: itemId, qty_sent: 15 }],
        },
        true,
      );
    } catch (err) {
      g20Rejected = err instanceof ApiError && (err.status === 409 || err.status === 422);
    }
    expect(g20Rejected, 'G-20 must reject department routing dispatch exceeding in-store qty').toBe(
      true,
    );

    // Dispatch 2 units legitimately and receive 2 units back
    const routing = await dispatchRouting(gsGuard.id, itemId, repairDeptId, 2);
    const routingLineId = routing.lines[0]?.id ?? '';
    await receiveRouting(routing.id, routingLineId, [
      { outcome_head_code: 'REPAIRED', qty_received: 2 },
    ]);

    // --- GUARD G-21: RM Final Action split conservation and immutability ---
    // Available qty is 10. Attempt to save actions with only 7 units
    let g21SplitRejected = false;
    try {
      await api(
        USERS.rm,
        'PUT',
        `/gs/${gsGuard.id}/final-actions`,
        {
          lines: [
            {
              gs_item_id: itemId,
              actions: [{ action_code: 'SEND_NEW', qty: 7 }],
            },
          ],
        },
        true,
      );
      await api(USERS.rm, 'POST', `/gs/${gsGuard.id}/final-actions/finalise`, {}, true);
    } catch (err) {
      g21SplitRejected = err instanceof ApiError && (err.status === 409 || err.status === 422);
    }
    expect(
      g21SplitRejected,
      'G-21 must reject final action split when action sum != available qty',
    ).toBe(true);

    // Finalise valid actions (10 units)
    const acSlipId = await finaliseFinalActions(gsGuard.id, itemId, {
      SEND_NEW: 6,
      ISSUE_CN: 4,
    });

    // Attempting to edit finalized actions directly without revision MUST BE REJECTED by G-21
    let g21FrozenRejected = false;
    try {
      await api(
        USERS.rm,
        'PUT',
        `/gs/${gsGuard.id}/final-actions`,
        {
          lines: [
            {
              gs_item_id: itemId,
              actions: [
                { action_code: 'SEND_NEW', qty: 5 },
                { action_code: 'ISSUE_CN', qty: 5 },
              ],
            },
          ],
        },
        true,
      );
    } catch (err) {
      g21FrozenRejected = err instanceof ApiError && (err.status === 409 || err.status === 422);
    }
    expect(g21FrozenRejected, 'G-21 must reject editing finalised actions without revision').toBe(
      true,
    );

    // --- GUARD G-22: Accounts entry rules, completeness, and dispatch immutability ---
    const acState = await api<{
      lines: Array<{
        id: string;
        action_code: string;
        requires_cn: boolean;
        requires_challan: boolean;
      }>;
    }>(USERS.accounts, 'GET', `/ac-entry/gs/${gsGuard.id}`);

    const cnLine = acState.lines.find((l) => l.requires_cn);
    const challanLine = acState.lines.find((l) => l.requires_challan);
    expect(cnLine).toBeDefined();
    expect(challanLine).toBeDefined();
    if (!cnLine || !challanLine) throw new Error('Missing expected ac lines');

    // Reject 1: Providing challan fields on an ISSUE_CN line
    let g22ChallanOnCnRejected = false;
    try {
      await api(
        USERS.accounts,
        'PUT',
        `/ac-entry/gs/${gsGuard.id}/lines`,
        {
          ac_action_slip_id: acSlipId,
          lines: [
            {
              line_id: cnLine.id,
              challan_no: 'CH-ILLEGAL',
              challan_date: TODAY,
            },
          ],
        },
        true,
      );
    } catch (err) {
      g22ChallanOnCnRejected =
        err instanceof ApiError && (err.status === 409 || err.status === 422);
    }
    expect(
      g22ChallanOnCnRejected,
      'G-22 must reject challan fields on an action that requires CN',
    ).toBe(true);

    // Reject 2: Future date
    let g22FutureDateRejected = false;
    try {
      await api(
        USERS.accounts,
        'PUT',
        `/ac-entry/gs/${gsGuard.id}/lines`,
        {
          ac_action_slip_id: acSlipId,
          lines: [
            {
              line_id: cnLine.id,
              cn_no: `CN-${tag}`,
              cn_date: '2099-01-01',
              cn_value: 1000.0,
            },
          ],
        },
        true,
      );
    } catch (err) {
      g22FutureDateRejected = err instanceof ApiError && (err.status === 409 || err.status === 422);
    }
    expect(g22FutureDateRejected, 'G-22 must reject future dates on Accounts entry lines').toBe(
      true,
    );

    // Reject 3: Early completion when lines are incomplete
    let g22EarlyCompleteRejected = false;
    try {
      // Save only the CN line, leave challan line incomplete
      await api(
        USERS.accounts,
        'PUT',
        `/ac-entry/gs/${gsGuard.id}/lines`,
        {
          ac_action_slip_id: acSlipId,
          lines: [
            {
              line_id: cnLine.id,
              cn_no: `CN-${tag}`,
              cn_date: TODAY,
              cn_value: 1000.0,
            },
          ],
        },
        true,
      );
      await api(
        USERS.accounts,
        'POST',
        `/ac-entry/gs/${gsGuard.id}/complete`,
        { ac_action_slip_id: acSlipId },
        true,
      );
    } catch (err) {
      g22EarlyCompleteRejected =
        err instanceof ApiError && (err.status === 409 || err.status === 422);
    }
    expect(
      g22EarlyCompleteRejected,
      'G-22 must reject completion with incomplete required lines',
    ).toBe(true);

    // Save complete Accounts entry legitimately
    const dispatchSlipId = await saveAndCompleteAccountsEntry(gsGuard.id, acSlipId, [
      {
        line_id: cnLine.id,
        cn_no: `CN-${tag}`,
        cn_date: TODAY,
        cn_value: 1000.0,
      },
      {
        line_id: challanLine.id,
        challan_no: `CH-${tag}`,
        challan_date: TODAY,
      },
    ]);

    // Reject 4: Attempt to edit lines after completion (frozen)
    let g22EditAfterCompleteRejected = false;
    try {
      await api(
        USERS.accounts,
        'PUT',
        `/ac-entry/gs/${gsGuard.id}/lines`,
        {
          ac_action_slip_id: acSlipId,
          lines: [
            {
              line_id: cnLine.id,
              cn_no: `CN-MODIFIED-${tag}`,
              cn_date: TODAY,
              cn_value: 1500.0,
            },
          ],
        },
        true,
      );
    } catch (err) {
      g22EditAfterCompleteRejected =
        err instanceof ApiError && (err.status === 409 || err.status === 422);
    }
    expect(g22EditAfterCompleteRejected, 'G-22 must freeze Accounts entries upon completion').toBe(
      true,
    );

    // Dispatch the Dispatch Slip legitimately
    await dispatchSlip(dispatchSlipId);

    // Reject 5: Attempting to dispatch an already dispatched slip
    let g22DoubleDispatchRejected = false;
    try {
      await dispatchSlip(dispatchSlipId);
    } catch (err) {
      g22DoubleDispatchRejected =
        err instanceof ApiError && (err.status === 409 || err.status === 422);
    }
    expect(
      g22DoubleDispatchRejected,
      'G-22 must reject dispatching an already dispatched Dispatch Slip',
    ).toBe(true);
  });
});
