import { expect, test, type Browser, type Page } from '@playwright/test';

import {
  allot,
  batteryBalance,
  classifyGood,
  close,
  closure,
  cnDecision,
  creditNote,
  csrApprove,
  DEMO_DMT,
  DEMO_PRISMATIC,
  dismantleQueue,
  dismantleWithPcb,
  dispatch,
  failing,
  functionalLots,
  handover,
  hazardLots,
  inspect,
  integrityViolations,
  inwardLine,
  issueToMainStore,
  receive,
  receiveBatteries,
  rmActions,
  storeLots,
} from './support/lifecycle';
import {
  api,
  apiAvailable,
  asUser,
  expectNoHorizontalOverflow,
  GATE_PROJECTS,
  USERS,
  type Device,
} from './support/stack';

/**
 * P3-08 · Phase 3 gate: full-lifecycle scenarios L-01..L-08 against the REAL local stack.
 *
 * Every role works in its own browser context (signed in as that demo user, on the project's
 * device: desktop Chrome or Pixel 7). The steps a scenario is about are performed in the UI by the
 * role that owns them; the remaining steps go through the same API as the role that owns them
 * (support/lifecycle.ts). After every scenario scripts/integrity_check.sql must report zero
 * violations (IC-01..IC-12) and no page may have logged a console error.
 *
 * Needs: `supabase start`, demo users (backend/scripts/seed_demo_users.py), the API on :8000.
 */

const devices: Device[] = [];

async function open(browser: Browser, email: string, path: string): Promise<Page> {
  const d = await asUser(browser, email, path);
  devices.push(d);
  return d.page;
}

// --- role steps in the UI ------------------------------------------------------------------------
/** Step-4 (BR-21, G-09): Aman sends, Sahil counts and accepts, each on their own device. */
async function uiHandover(browser: Browser, gsId: string): Promise<void> {
  const aman = await open(browser, USERS.aman, `/gs/${gsId}/handover`);
  await expect(aman.getByRole('heading', { name: 'Handover to Intermediate Store' })).toBeVisible();
  await expectNoHorizontalOverflow(aman);
  await aman.getByRole('button', { name: 'Confirm handover' }).click();
  await expect(aman).toHaveURL(/#\/custody\/transfers\/[0-9a-f-]{36}$/);
  const transferId = aman.url().split('/').pop() ?? '';
  const sahil = await open(browser, USERS.sahil, `/custody/transfers/${transferId}`);
  await sahil.getByRole('button', { name: /Accepted - Quantity/ }).click();
  await expect(sahil.getByText('Accepted', { exact: true })).toBeVisible();
  await expectNoHorizontalOverflow(sahil);
}

/** Step-7 (BR-32, DEC-13): Pratham confirms the CN decision prefilled from the RM actions. */
async function uiCnDecision(browser: Browser, gsId: string): Promise<void> {
  const rm = await open(browser, USERS.rm, `/gs/${gsId}/cn-decision`);
  const confirm = rm.getByRole('button', { name: /Confirm Step-7 Decision/ });
  await expect(confirm).toBeEnabled({ timeout: 15_000 });
  await expectNoHorizontalOverflow(rm);
  await confirm.click();
  await expect(rm.getByText(/decision recorded successfully/i)).toBeVisible();
}

/** BR-38 / DD r79: Deepak Ji records the prior party notification. */
async function uiNotify(browser: Browser, gsId: string): Promise<void> {
  const acc = await open(browser, USERS.accounts, `/gs/${gsId}/party-notification`);
  await expect(acc.getByLabel('Message')).toHaveValue(/dated \d{2}-\d{2}-\d{4}/, {
    timeout: 15_000,
  });
  // The demo party has no contact on file: Accounts types the recipient (DEC-25).
  const recipient = acc.getByLabel('Recipient');
  if ((await recipient.inputValue()) === '') {
    await acc.getByLabel('Channel').selectOption('EMAIL');
    await recipient.fill('accounts@demo-party.example');
  }
  await expectNoHorizontalOverflow(acc);
  await acc.getByRole('button', { name: /record notification/i }).click();
  await expect(acc.getByText(/^Recorded for /)).toBeVisible();
}

/** G-15: Pratham closes the GS from the closure checklist. */
async function uiClose(browser: Browser, gsId: string, csr = false): Promise<void> {
  const rm = await open(browser, USERS.rm, `/gs/${gsId}`);
  await rm.getByRole('tab', { name: /closure/i }).click();
  const closeBtn = rm.getByRole('button', { name: /^close gs$/i });
  await expect(closeBtn).toBeEnabled({ timeout: 15_000 });
  await expectNoHorizontalOverflow(rm);
  await closeBtn.click();
  await rm
    .getByRole('dialog')
    .getByRole('button', { name: /^close gs$/i })
    .click();
  await expect(rm.getByRole('heading', { name: 'Closed' })).toBeVisible();
  if (csr) {
    await expect(
      rm.getByText(/Inward to Inventory with Packaging \+ CN Issued \+ Prior Party Info/),
    ).toBeVisible();
  }
}

async function expectClosed(gsId: string, type: 'RO_CLOSED' | 'CSR_CLOSED'): Promise<void> {
  const gs = await api<{ goods_slip: { status: string } }>(USERS.rm, 'GET', `/gs/${gsId}`);
  expect(gs.goods_slip.status).toBe('CLOSED');
  const c = await api<{ closure: { closure_type: string } | null }>(
    USERS.rm,
    'GET',
    `/gs/${gsId}/closure`,
  );
  expect(c.closure?.closure_type).toBe(type);
}

// --- suite ---------------------------------------------------------------------------------------
test.describe('P3-08 full lifecycle', () => {
  test.describe.configure({ timeout: 240_000 });

  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(
      !GATE_PROJECTS.includes(testInfo.project.name),
      'Lifecycle scenarios run on desktop-chromium and mobile-pixel-7',
    );
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  test.afterEach(async () => {
    const opened = devices.splice(0);
    for (const d of opened) {
      expect(d.errors, `console errors on ${d.page.url()}`).toEqual([]);
      await d.context.close();
    }
    // Task 2: scripts/integrity_check.sql after every scenario — zero violations.
    expect(integrityViolations()).toEqual([]);
  });

  test('L-01 RO with DMT: grading → technician (battery) → Main Store, dismantling → GST CN → close', async ({
    browser,
  }) => {
    const { gs, item } = await inwardLine('L01', DEMO_DMT, 10);
    await inspect(item, {
      DMT_OK_PACKED: 3,
      DMT_DIRTY: 2,
      DMT_SCRATCHED: 2,
      DMT_DISPLAY_ISSUE: 2,
      DMT_BROKEN_BODY: 1,
    });
    await rmActions(gs.id, [{ item, actions: { ISSUE_CN: 9, NOT_ALLOWED: 1 } }]);
    await uiHandover(browser, gs.id);

    const lots = await storeLots(gs.id);
    const lot = (code: string) => {
      const hit = lots.find((l) => l.source_condition_code === code);
      if (!hit) throw new Error(`no ${code} lot in the Intermediate Store`);
      return hit.lot_id;
    };
    await classifyGood(lot('DMT_OK_PACKED'), 3); // DEC-14
    await receiveBatteries(10);
    const before = await batteryBalance();
    const tech = ['DMT_DIRTY', 'DMT_SCRATCHED', 'DMT_DISPLAY_ISSUE'].map(lot);
    const batch = await allot(tech.map((l) => ({ lot_id: l, qty: 2 })));
    await receive(batch, [
      {
        lot_id: lot('DMT_DIRTY'),
        qty: 2,
        allocations: { FUNCTIONAL_GOOD: 2 },
        cleaning_code: 'CLEANED_SELLABLE',
        battery: { checked: 2, replaced: 2 }, // BR-24 / G-10
      },
      {
        lot_id: lot('DMT_SCRATCHED'),
        qty: 2,
        allocations: { NON_SELLABLE: 2 },
        cleaning_code: 'PERMANENT_SCRATCHES', // DEC-17
      },
      { lot_id: lot('DMT_DISPLAY_ISSUE'), qty: 2, allocations: { NON_GOOD: 2 } },
    ]);
    expect(before - (await batteryBalance())).toBe(2);
    await issueToMainStore(gs.id); // BR-31: 5 functional good pieces
    const nonGood = (await dismantleQueue()).dismantleable_lots.find(
      (l) => l.gs_no === gs.gs_no && l.condition_class === 'NON_GOOD',
    );
    expect(nonGood?.qty).toBe(2);
    await dismantleWithPcb(nonGood?.lot_id ?? '', 2); // BR-27 / G-11: PCB with model + supplier
    // P3-05 post-technical revision, then the Step-7 decision in the UI (prefilled ALLOW 5).
    await rmActions(gs.id, [{ item, actions: { ISSUE_CN: 5, NOT_ALLOWED: 5 } }], {
      reason: 'Post-technical revision: 2 non-good dismantled, 2 permanently scratched',
    });
    await uiCnDecision(browser, gs.id);
    const cn = await creditNote(gs.id, [{ item, qty: 5 }], {
      type: 'GST_CN',
      portal: 'GST_REFLECTED',
    });
    expect([cn.cn_type_code, cn.status]).toEqual(['GST_CN', 'ISSUED']);
    await uiNotify(browser, gs.id);
    await uiClose(browser, gs.id);
    await expectClosed(gs.id, 'RO_CLOSED');
  });

  test('L-02 RO with repaired pieces → General CN → close', async ({ browser }) => {
    const { gs, item } = await inwardLine('L02', DEMO_DMT, 4);
    await inspect(item, { DMT_DISPLAY_ISSUE: 4 });
    await rmActions(gs.id, [{ item, actions: { ISSUE_CN: 4 } }]);
    await handover(gs.id);
    const [lot] = await storeLots(gs.id);
    const lotId = lot?.lot_id ?? '';
    const batch = await allot([{ lot_id: lotId, qty: 4 }]);
    await receive(batch, [{ lot_id: lotId, qty: 4, allocations: { FUNCTIONAL_REPAIRED: 4 } }]);
    await issueToMainStore(gs.id);
    await uiCnDecision(browser, gs.id);
    const cn = await creditNote(gs.id, [{ item, qty: 4 }], {
      type: 'GENERAL_CN',
      portal: 'GST_REFLECTED',
    });
    expect([cn.cn_type_code, cn.status]).toEqual(['GENERAL_CN', 'ISSUED']); // BR-35
    await uiNotify(browser, gs.id);
    await uiClose(browser, gs.id);
    await expectClosed(gs.id, 'RO_CLOSED');
  });

  test('L-03 GST not reflected → JV only → close', async ({ browser }) => {
    const { gs, item } = await inwardLine('L03', DEMO_DMT, 3);
    await inspect(item, { DMT_OK_PACKED: 3 });
    await rmActions(gs.id, [{ item, actions: { ISSUE_CN: 3 } }]);
    await uiHandover(browser, gs.id);
    for (const l of await storeLots(gs.id)) await classifyGood(l.lot_id, l.balance ?? 0);
    await issueToMainStore(gs.id);
    await cnDecision(gs.id, [{ item, qty: 3, decision: 'ALLOW_CN' }]);
    const jv = await creditNote(gs.id, [{ item, qty: 3 }], {
      type: 'GENERAL_CN',
      portal: 'GST_NOT_REFLECTED',
    });
    expect([jv.cn_type_code, jv.status]).toEqual(['JV_ONLY', 'ISSUED']); // BR-34 / G-13
    await uiNotify(browser, gs.id);
    await uiClose(browser, gs.id);
    await expectClosed(gs.id, 'RO_CLOSED');
  });

  test('L-04 Send Repaired dispatch → close (no CN)', async ({ browser }) => {
    const { gs, item } = await inwardLine('L04', DEMO_DMT, 3);
    await inspect(item, { DMT_DISPLAY_ISSUE: 3 });
    await rmActions(gs.id, [{ item, actions: { SEND_REPAIRED: 3 } }]);
    await uiHandover(browser, gs.id);
    const [lot] = await storeLots(gs.id);
    const lotId = lot?.lot_id ?? '';
    const batch = await allot([{ lot_id: lotId, qty: 3 }]);
    await receive(batch, [{ lot_id: lotId, qty: 3, allocations: { FUNCTIONAL_REPAIRED: 3 } }]);
    await uiCnDecision(browser, gs.id); // prefilled DENY_CN_SEND_REPLACEMENT 3
    const [repaired] = await functionalLots(gs.id);
    await dispatch(gs.id, 'SEND_REPAIRED', [{ item, qty: 3, lot_id: repaired?.lot_id ?? '' }]);
    const c = await closure(gs.id);
    expect(c.items.find((i) => i.code === 'PRIOR_NOTIFICATION')?.applicable).toBe(false);
    await uiClose(browser, gs.id);
    await expectClosed(gs.id, 'RO_CLOSED');
  });

  test('L-05 CSR approved → handover with packaging → CN → notify → CSR_CLOSED', async ({
    browser,
  }) => {
    const { gs, item } = await inwardLine('L05', DEMO_DMT, 4, 'CSR');
    await csrApprove(gs.id); // BR-08 / G-03: RM approval forwards the goods with packaging
    await uiHandover(browser, gs.id);
    for (const l of await storeLots(gs.id)) {
      // BR-10: packaging check by the Intermediate Store In-charge
      await api(
        USERS.sahil,
        'POST',
        `/lots/${l.lot_id}/packaging-check`,
        { result: 'OK', qty_replaced: 0 },
        true,
      );
    }
    // DEC-14: un-graded CSR goods are checked by the technician before Functional Good custody.
    const [lot] = await storeLots(gs.id);
    const lotId = lot?.lot_id ?? '';
    const batch = await allot([{ lot_id: lotId, qty: 4 }]);
    await receive(batch, [{ lot_id: lotId, qty: 4, allocations: { FUNCTIONAL_GOOD: 4 } }]);
    await issueToMainStore(gs.id);
    await uiCnDecision(browser, gs.id); // CSR: ALLOW_CN for the full quantity
    const cn = await creditNote(gs.id, [{ item, qty: 4 }], {
      type: 'GST_CN',
      portal: 'GST_REFLECTED',
    });
    expect([cn.cn_type_code, cn.status]).toEqual(['GST_CN', 'ISSUED']);
    await uiNotify(browser, gs.id);
    await uiClose(browser, gs.id, true);
    await expectClosed(gs.id, 'CSR_CLOSED');
  });

  test('L-06 handover discrepancy → reconciliation → continue', async ({ browser }) => {
    const { gs, item } = await inwardLine('L06', DEMO_DMT, 6);
    await inspect(item, { DMT_OK_PACKED: 6 });
    await rmActions(gs.id, [{ item, actions: { SEND_NEW: 6 } }]);

    // BR-21: Aman sends 6, Sahil counts 5 → frozen; both sign the reconciliation.
    const aman = await open(browser, USERS.aman, `/gs/${gs.id}/handover`);
    await expect(aman.getByText('To hand over (6 pcs)')).toBeVisible();
    await aman.getByRole('button', { name: 'Confirm handover' }).click();
    await expect(aman).toHaveURL(/#\/custody\/transfers\/[0-9a-f-]{36}$/);
    const transferId = aman.url().split('/').pop() ?? '';
    const sahil = await open(browser, USERS.sahil, `/custody/transfers/${transferId}`);
    await sahil.getByRole('button', { name: /^Decrease Counted/ }).click();
    await sahil.getByLabel(/Discrepancy details/).fill('One piece missing from the carton');
    await sahil.getByRole('button', { name: /Discrepancy Reported/ }).click();
    await expect(sahil.getByText(/frozen in transit/)).toBeVisible();
    await expectNoHorizontalOverflow(sahil);
    expect(failing(await closure(gs.id))).toContain('NO_OPEN_DISCREPANCY');
    await sahil.getByLabel('Resolution').selectOption('ACCEPT_COUNTED_WITH_ADJUSTMENT');
    await sahil.getByLabel('Pieces not counted').selectOption('RETURN_TO_SOURCE');
    await sahil.getByLabel('Notes', { exact: true }).fill('Missing piece stays with Aman');
    await sahil.getByRole('button', { name: /Sign as receiver/ }).click();
    await expect(sahil.getByText('Receiver: Sahil', { exact: false })).toBeVisible();
    await aman.reload();
    await aman.getByLabel('Resolution').selectOption('ACCEPT_COUNTED_WITH_ADJUSTMENT');
    await aman.getByLabel('Pieces not counted').selectOption('RETURN_TO_SOURCE');
    await aman.getByLabel('Notes', { exact: true }).fill('Agreed, piece found on my table');
    await aman.getByRole('button', { name: /Sign as sender/ }).click();
    await expect(aman.getByText('Reconciled', { exact: true })).toBeVisible();

    // Continue: the returned piece is handed over cleanly, then the normal path to closure.
    await handover(gs.id);
    for (const l of await storeLots(gs.id)) await classifyGood(l.lot_id, l.balance ?? 0);
    await issueToMainStore(gs.id);
    await cnDecision(gs.id, [{ item, qty: 6, decision: 'DENY_CN_SEND_REPLACEMENT' }]);
    await dispatch(gs.id, 'SEND_NEW', [{ item, qty: 6 }]); // DEC-26: new stock, outside the ledger
    await uiClose(browser, gs.id);
    await expectClosed(gs.id, 'RO_CLOSED');
  });

  test('L-07 hazard: Prismatic broken with mercury → quarantine → disposal with manifest → close', async ({
    browser,
  }) => {
    const { gs, item } = await inwardLine('L07', DEMO_PRISMATIC, 3);
    await inspect(item, { PRS_OK: 2, PRS_BROKEN_WITH_HG: 1 }); // BR-13 / G-05 → quarantine
    const [hazard] = await hazardLots(gs.id);
    expect(hazard?.qty).toBe(1);
    await rmActions(gs.id, [{ item, actions: { SEND_NEW: 2, NOT_ALLOWED: 1 } }]);
    await uiHandover(browser, gs.id);
    for (const l of await storeLots(gs.id)) await classifyGood(l.lot_id, l.balance ?? 0);
    await issueToMainStore(gs.id);
    await cnDecision(gs.id, [{ item, qty: 2, decision: 'DENY_CN_SEND_REPLACEMENT' }]);
    await dispatch(gs.id, 'SEND_NEW', [{ item, qty: 2 }]);

    // DEC-11: the Spare Parts Manager marks the quarantined piece as scrap and disposes of it.
    const spm = await open(browser, USERS.spm, '/scrap');
    const card = spm.getByTestId(`disposable-${hazard?.lot_id ?? ''}`);
    await expect(card).toBeVisible({ timeout: 15_000 });
    await expect(card.getByText(/HAZARDOUS/)).toBeVisible();
    await expectNoHorizontalOverflow(spm);
    const mark = card.getByRole('button', { name: 'Mark for disposal' });
    expect((await mark.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
    await mark.click();
    await expect(spm.getByText('1 piece(s) marked for disposal.')).toBeVisible();
    await expect(card).toBeHidden();
    const row = spm.getByRole('row', { name: /Mercury hazard \(DEC-11\)/ }).first();
    await row.getByRole('button', { name: 'Dispose' }).click();
    const dialog = spm.getByRole('dialog');
    const confirm = dialog.getByRole('button', { name: 'Confirm Disposal' });
    await expect(confirm).toBeDisabled(); // DEC-11: no manifest, no disposal
    await dialog.getByLabel(/Manifest Reference Number/).fill(`MNF-HAZ-${gs.gs_no}`);
    await confirm.click();
    await expect(spm.getByText('Scrap record disposed successfully!')).toBeVisible();
    expect(await hazardLots(gs.id)).toEqual([]);

    await uiClose(browser, gs.id);
    await expectClosed(gs.id, 'RO_CLOSED');
  });

  test('L-08 Pending (BP) blocks closure until cleared', async ({ browser }) => {
    const { gs, item } = await inwardLine('L08', DEMO_DMT, 4);
    await inspect(item, { DMT_OK_PACKED: 4 });
    await rmActions(gs.id, [{ item, actions: { SEND_NEW: 3, PENDING_BP: 1 } }], {
      pendency_details: {
        [item]: { reason: 'With the repair team for checking', sent_to: 'Repair Team' },
      },
    });
    await uiHandover(browser, gs.id); // BR-20 / G-08: the pending piece stays behind
    for (const l of await storeLots(gs.id)) await classifyGood(l.lot_id, l.balance ?? 0);
    await issueToMainStore(gs.id);
    await cnDecision(gs.id, [{ item, qty: 3, decision: 'DENY_CN_SEND_REPLACEMENT' }]);
    await dispatch(gs.id, 'SEND_NEW', [{ item, qty: 3 }]);

    // G-15: the checklist blocks the closure while the pendency is open.
    const rm = await open(browser, USERS.rm, `/gs/${gs.id}`);
    await rm.getByRole('tab', { name: /closure/i }).click();
    await expect(rm.getByTestId('check-NO_OPEN_PENDENCY')).toHaveAttribute('data-passed', 'false');
    await expect(rm.getByRole('button', { name: /^close gs$/i })).toBeDisabled();
    await expect(close(gs.id)).rejects.toThrow(/G-15/);

    // DEC-12: the RM clears it from the Pendency (BP) register.
    await rm.goto('/#/pendencies');
    await rm.getByLabel('Search by GS no., party, or product').fill(gs.gs_no);
    await rm.getByRole('button', { name: 'Clear Pendency' }).click();
    await rm.locator('#pendency-reg-resolution-action').selectOption('SEND_NEW');
    await rm
      .locator('#pendency-reg-clearance-notes')
      .fill('Checked by the repair team: replace with new');
    await rm.getByRole('button', { name: 'Confirm Clearance' }).click();
    await expect(rm.getByRole('dialog')).toBeHidden();

    // The cleared piece is back in Inward Staging and follows the normal path.
    expect(failing(await closure(gs.id))).toContain('STOCK_NOT_IN_TRANSIT');
    await handover(gs.id);
    for (const l of await storeLots(gs.id)) await classifyGood(l.lot_id, l.balance ?? 0);
    await issueToMainStore(gs.id);
    await cnDecision(gs.id, [{ item, qty: 4, decision: 'DENY_CN_SEND_REPLACEMENT' }]);
    await dispatch(gs.id, 'SEND_NEW', [{ item, qty: 1 }]);
    await uiClose(browser, gs.id);
    await expectClosed(gs.id, 'RO_CLOSED');
  });
});
