/**
 * Multi-GS end-to-end run (2026-11-17) on the live 19-item thermometer catalogue
 * (supabase/snippets/2026-11-16_reset_transactions_and_load_thermometer_catalogue.sql).
 *
 * Four goods slips with different scenarios go through every role:
 *   Gate -> Carton Opening -> Counting -> Categorisation -> RM Review -> Intermediate Store ->
 *   Department routing & taking goods back -> RM Final Actions -> Accounts (CN / Challan) ->
 *   Dispatch alert (DISPATCH_SLIP_READY) -> Dispatch.
 *
 * DEC-51 (no task-ownership lock): steps are deliberately done by DIFFERENT eligible users, e.g.
 * Aman counts and a second inward verifier categorises (the screenshot bug), and a second gate
 * user may edit gate details of a GS someone else created.
 *
 *  GS-1  Offline, 2 cartons. DMT-102: documented 10, counted 8 (short 2), 5 buckets.
 *        Counted by Aman, categorised in the BROWSER by Verifier-2. REPAIR dept round-trip
 *        (2 repaired + 1 wastage). Final: Send New 3 / Send Repaired 2 / Issue CN 3.
 *  GS-2  Offline, 1 carton, two lines (DMT-437 Baby 6 + A-01 Akutem Prismatic 4).
 *        Counted by Verifier-2, categorised by Aman. Full replacement (no CN).
 *  GS-3  E-Commerce, 1 carton. NT-INFRA 5 -> Issue CN only: no Dispatch Slip, no alert.
 *  GS-4  Offline, 1 carton. ECO XL Oval 4 + MT-401R 3. RM sends categorisation back; the OTHER
 *        verifier corrects and resubmits. Final: Send New 4 (oval) + Send New 1 / Issue CN 2 (DMT).
 */
import { expect, test, type Browser, type Page } from '@playwright/test';

import { integrityViolations } from './support/lifecycle';
import {
  acceptStoreTransfer,
  createEcommerceGs,
  createOfflineGs,
  ensureFieldProfiles,
  receiveRouting,
  TODAY,
  uploadCartonVideos,
  uploadClassifiedDocPhoto,
} from './support/phase11';
import {
  api,
  apiAvailable,
  asUser,
  expectNoHorizontalOverflow,
  GATE_PROJECTS,
  USERS,
  type Device,
} from './support/stack';

const VERIFIER2 = 'verifier2@rms.local';
const GATE2 = 'gate2@rms.local';
const PASSWORD = process.env.RMS_DEMO_PASSWORD ?? 'Uat@2026RMS!';

interface Product {
  id: string;
  code: string;
  name: string;
}
interface CatState {
  items: Array<{
    item_id: string;
    received_qty: number;
    allowed_buckets: Array<{ field_code: string; field_label: string }>;
    allowed_counts: Array<{ field_code: string }>;
  }>;
  is_same_user_who_counted: boolean;
  can_submit: boolean;
}
interface FaState {
  lines: Array<{
    gs_item_id: string;
    product_code: string | null;
    available_qty: number;
    allowed_actions: Array<{ code: string }>;
  }>;
  current_slip: { id: string } | null;
}
interface AcState {
  lines: Array<{
    id: string;
    action_code: string;
    requires_cn: boolean;
    requires_challan: boolean;
  }>;
  dispatch_slip: { id: string; slip_no: string; total_qty: number; status: string } | null;
}
interface Notif {
  type: string;
  title: string;
  body: string | null;
  gs_id: string | null;
}

const devices: Device[] = [];
async function openPage(browser: Browser, email: string, path: string): Promise<Page> {
  const d = await asUser(browser, email, path);
  devices.push(d);
  return d.page;
}

// --- set-up -----------------------------------------------------------------------------------
/** Second inward verifier + second gate user (DEC-51 checks). Idempotent across runs. */
async function ensureUser(email: string, fullName: string, role: string): Promise<void> {
  const page = await api<{ items: Array<{ email: string | null }> }>(
    USERS.admin,
    'GET',
    `/admin/users?search=${encodeURIComponent(email)}&page_size=5`,
  );
  if (page.items.some((u) => u.email === email)) return;
  await api(USERS.admin, 'POST', '/admin/users', {
    email,
    full_name: fullName,
    role_codes: [role],
    initial_password: PASSWORD,
    must_change_password: false,
  });
}

async function product(code: string): Promise<Product> {
  const rows = await api<Product[]>(
    USERS.aman,
    'GET',
    `/itemization/lookups/products?q=${encodeURIComponent(code)}&limit=5`,
  );
  const p = rows.find((r) => r.code === code);
  if (!p) throw new Error(`Product ${code} is not in the catalogue (load the thermometer list)`);
  return p;
}

// --- step helpers (the acting user is explicit) ----------------------------------------------
async function openCartons(
  gsId: string,
  cartons: number,
  docNo: string,
  by: string,
): Promise<void> {
  await api(by, 'POST', `/gs/${gsId}/unboxing/start`, {});
  await uploadCartonVideos(gsId, cartons);
  await uploadClassifiedDocPhoto(gsId, docNo);
  await api(by, 'POST', `/gs/${gsId}/unboxing/complete`, {});
}

async function addLine(by: string, gsId: string, p: Product, doc: number, recv: number) {
  const res = await api<{ id: string }>(by, 'POST', `/gs/${gsId}/items`, {
    product_id: p.id,
    documented_qty: doc,
    received_qty: recv,
  });
  return res.id;
}

async function saveBuckets(
  by: string,
  gsId: string,
  itemId: string,
  buckets: Record<string, number>,
) {
  const state = await api<CatState>(by, 'GET', `/gs/${gsId}/categorisation`);
  const item = state.items.find((i) => i.item_id === itemId);
  if (!item) throw new Error(`item ${itemId} not on ${gsId}`);
  await api(
    by,
    'PUT',
    `/gs/${gsId}/items/${itemId}/categorisation`,
    {
      buckets: Object.entries(buckets).map(([field_code, qty]) => ({ field_code, qty })),
      // Only the item counts the product's profile offers (DMT has them, others none).
      counts: item.allowed_counts.map((c) => ({
        count_type: c.field_code,
        count_value: item.received_qty,
      })),
    },
    true,
  );
}

async function submitCategorisation(by: string, gsId: string): Promise<void> {
  await api(
    by,
    'POST',
    `/gs/${gsId}/categorisation/submit`,
    { category_code: 'REGULAR_RETURN' },
    true,
  );
}

async function approveAndStore(gsId: string): Promise<void> {
  const res = await api<{ transfer_id: string }>(
    USERS.rm,
    'POST',
    `/gs/${gsId}/rm-approve`,
    { remarks: 'Approved (multi-GS E2E)' },
    true,
  );
  await acceptStoreTransfer(res.transfer_id);
  const gs = await api<{ goods_slip: { status: string } }>(USERS.rm, 'GET', `/gs/${gsId}`);
  expect(gs.goods_slip.status).toBe('HELD_AT_INTERMEDIATE_STORE');
}

async function finalise(
  gsId: string,
  split: Record<string, Record<string, number>>, // product code -> action -> qty
): Promise<string> {
  const state = await api<FaState>(USERS.rm, 'GET', `/gs/${gsId}/final-actions`);
  const lines = state.lines.map((ln) => {
    const actions = split[ln.product_code ?? ''];
    if (!actions) throw new Error(`no split for ${String(ln.product_code)}`);
    const total = Object.values(actions).reduce((s, q) => s + q, 0);
    expect(total, `G-21 split for ${String(ln.product_code)}`).toBe(ln.available_qty);
    return {
      gs_item_id: ln.gs_item_id,
      actions: Object.entries(actions).map(([action_code, qty]) => ({ action_code, qty })),
    };
  });
  await api(USERS.rm, 'PUT', `/gs/${gsId}/final-actions`, { lines }, true);
  const fin = await api<FaState>(USERS.rm, 'POST', `/gs/${gsId}/final-actions/finalise`, {}, true);
  if (!fin.current_slip) throw new Error('finalise returned no A/c Actions slip');
  return fin.current_slip.id;
}

/** Accounts: CN details for CN lines, CHALLAN details for goods-shipping lines (AMD-18). */
async function accountsEntry(gsId: string, acSlipId: string, tag: string): Promise<AcState> {
  const st = await api<AcState>(USERS.accounts, 'GET', `/ac-entry/gs/${gsId}`);
  const lines = st.lines.map((ln, i) => ({
    line_id: ln.id,
    ...(ln.requires_cn ? { cn_no: `CN-${tag}-${String(i)}`, cn_date: TODAY, cn_value: 950.0 } : {}),
    ...(ln.requires_challan
      ? { challan_no: `CH-${tag}-${ln.action_code}`, challan_date: TODAY }
      : {}),
  }));
  await api(
    USERS.accounts,
    'PUT',
    `/ac-entry/gs/${gsId}/lines`,
    { ac_action_slip_id: acSlipId, lines },
    true,
  );
  return api<AcState>(
    USERS.accounts,
    'POST',
    `/ac-entry/gs/${gsId}/complete`,
    { ac_action_slip_id: acSlipId, remarks: 'Accounts entry (multi-GS E2E)' },
    true,
  );
}

async function dispatchAlerts(gsId: string): Promise<Notif[]> {
  const mine = await api<{ items: Notif[] }>(USERS.dispatch, 'GET', '/notifications/mine?limit=50');
  return mine.items.filter((n) => n.type === 'DISPATCH_SLIP_READY' && n.gs_id === gsId);
}

async function dispatch(slipId: string, tag: string): Promise<void> {
  await api(
    USERS.dispatch,
    'POST',
    `/dispatch-slips/${slipId}/dispatch`,
    { dispatch_date: TODAY, transporter: 'SafeX Logistics', docket_no: `DSP-${tag}` },
    true,
  );
  const slip = await api<{ status: string }>(USERS.dispatch, 'GET', `/dispatch-slips/${slipId}`);
  expect(slip.status).toBe('DISPATCHED');
}

/** Accounts -> alert -> dispatch, with the alert content checked against the challans. */
async function accountsAlertDispatch(gsId: string, acSlipId: string, tag: string, shipQty: number) {
  const done = await accountsEntry(gsId, acSlipId, tag);
  const ds = done.dispatch_slip;
  if (!ds) throw new Error('Accounts completion generated no Dispatch Slip');
  expect(ds.total_qty).toBe(shipQty);

  const alerts = await dispatchAlerts(gsId);
  expect(alerts).toHaveLength(1);
  const alert = alerts[0];
  if (!alert) throw new Error('no dispatch alert');
  expect(alert.title).toContain(ds.slip_no);
  expect(alert.title).toContain(`send ${String(shipQty)} pc`);
  for (const ln of done.lines.filter((l) => l.requires_challan)) {
    expect(alert.body).toContain(`Challan CH-${tag}-${ln.action_code}`);
  }
  await dispatch(ds.id, tag);
  return { slip: ds, alert };
}

// --- the run ------------------------------------------------------------------------------------
test.describe('Multi-GS full flow on the thermometer catalogue (DEC-51)', () => {
  // DEC-64 (P4): categorisation is locked, not submitted to RM review; the path to the Intermediate Store is the P5 transfer slip. Rebuild this flow in P5.
  test.fixme(true, 'DEC-64 (P4): flow retired; rebuild in P5 / P12');
  test.describe.configure({ mode: 'serial', timeout: 300_000 });

  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(!GATE_PROJECTS.includes(testInfo.project.name), 'desktop-chrome and mobile-pixel-7');
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
    await ensureUser(VERIFIER2, 'Ravi (Inward Verifier 2)', 'INWARD_VERIFIER');
    await ensureUser(GATE2, 'Gate User 2', 'GATE_INWARD');
  });

  test.afterEach(async () => {
    const opened = devices.splice(0);
    for (const d of opened) {
      expect(d.errors, `Console errors on ${d.page.url()}`).toEqual([]);
      await d.context.close();
    }
    expect(integrityViolations()).toEqual([]);
  });

  test('GS-1: counted by Aman, categorised in the UI by Verifier-2, dept round-trip, CN + new + repaired, dispatch alert', async ({
    browser,
  }) => {
    const tag = `M1-${Date.now().toString().slice(-6)}`;
    const { repairDeptId } = await ensureFieldProfiles();
    const dmt102 = await product('ITM-00003');
    expect(dmt102.name).toContain('DMT-102');

    // Gate (Anuj). A second gate user may edit it too (DEC-51).
    const gs = await createOfflineGs({ tag, cartonCount: 2 });
    const asGate2 = await api<{ can_edit_gate: boolean }>(GATE2, 'GET', `/gs/${gs.id}`);
    expect(asGate2.can_edit_gate).toBe(true);

    // Carton opening + counting (Aman): documented 10, counted 8.
    await openCartons(gs.id, 2, `INV-${tag}`, USERS.aman);
    const itemId = await addLine(USERS.aman, gs.id, dmt102, 10, 8);
    await api(USERS.aman, 'POST', `/gs/${gs.id}/counting/submit`, {}, true);

    // Categorisation by Verifier-2 in the browser (the reported bug).
    const page = await openPage(browser, VERIFIER2, `/gs/${gs.id}/itemization`);
    await expect(page.getByRole('heading', { name: /Categorisation/i })).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByText(/Only the inward verifier who counted/)).toHaveCount(0);
    const state = await api<CatState>(VERIFIER2, 'GET', `/gs/${gs.id}/categorisation`);
    expect(state.is_same_user_who_counted).toBe(false);
    expect(state.can_submit).toBe(true);
    const split: Record<string, number> = {
      DMT_OK_PACKED: 3,
      DMT_OK_PKG_DAMAGED: 2,
      DMT_SCRATCHED: 1,
      DMT_DIRTY: 1,
      DMT_DISPLAY_ISSUE: 1,
    };
    for (const [code, qty] of Object.entries(split)) {
      await page.locator(`#b-${itemId}-${code}`).fill(String(qty));
    }
    for (const c of state.items[0]?.allowed_counts ?? []) {
      await page.locator(`#c-${itemId}-${c.field_code}`).fill('8');
    }
    await page.getByRole('button', { name: /Save Line 1/ }).click();
    // Saved on the server by Verifier-2 (before the fix this was a 403, AMD-08 notice).
    await expect
      .poll(
        async () =>
          (await api<{ all_conserved: boolean }>(VERIFIER2, 'GET', `/gs/${gs.id}/categorisation`))
            .all_conserved,
        { timeout: 15_000 },
      )
      .toBe(true);
    await expect(page.getByText(/Request ID/)).toHaveCount(0);
    await expect(page.getByText(/Only the inward verifier who counted/)).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
    const submit = page.getByRole('button', { name: /Submit Categorisation/ });
    await expect(submit).toBeEnabled();
    await submit.click();
    await expect
      .poll(
        async () =>
          (await api<{ goods_slip: { status: string } }>(USERS.rm, 'GET', `/gs/${gs.id}`))
            .goods_slip.status,
        { timeout: 15_000 },
      )
      .toBe('RM_REVIEW');

    // RM review -> Intermediate Store (Sahil accepts the transfer).
    await approveAndStore(gs.id);

    // Department: 3 pcs to REPAIR; taking back 2 repaired + 1 wastage (Aman receives).
    const routing = await api<{ id: string; lines: Array<{ id: string }> }>(
      USERS.rm,
      'POST',
      '/department-routing/dispatch',
      {
        gs_id: gs.id,
        department_field_id: repairDeptId,
        lines: [{ gs_item_id: itemId, qty_sent: 3 }],
        remarks: tag,
      },
      true,
    );
    await receiveRouting(routing.id, routing.lines[0]?.id ?? '', [
      { outcome_head_code: 'REPAIRED', qty_received: 2 },
      { outcome_head_code: 'WASTAGE', qty_received: 1 },
    ]);

    // RM final actions -> Accounts (CN + challans) -> Dispatch alert -> Dispatch.
    const acSlipId = await finalise(gs.id, {
      'ITM-00003': { SEND_NEW: 3, SEND_REPAIRED: 2, ISSUE_CN: 3 },
    });
    const { alert } = await accountsAlertDispatch(gs.id, acSlipId, tag, 5);
    expect(alert.body).toContain('DMT-102');

    // The Dispatch team sees the alert in the Notification Centre (UI).
    const centre = await openPage(browser, USERS.dispatch, '/notifications');
    await expect(centre.getByText(alert.title).first()).toBeVisible({ timeout: 15_000 });
    await expectNoHorizontalOverflow(centre);
    await centre.screenshot({
      path: `test-results/multi-gs/${test.info().project.name}-dispatch-alert.png`,
    });
  });

  test('GS-2: counted by Verifier-2, categorised by Aman, two products, full replacement', async () => {
    const tag = `M2-${Date.now().toString().slice(-6)}`;
    const { repairDeptId } = await ensureFieldProfiles();
    const baby = await product('ITM-00007');
    const akutem = await product('ITM-00013');

    const gs = await createOfflineGs({ tag, cartonCount: 1 });
    await openCartons(gs.id, 1, `INV-${tag}`, VERIFIER2);
    const babyId = await addLine(VERIFIER2, gs.id, baby, 6, 6);
    const akutemId = await addLine(VERIFIER2, gs.id, akutem, 4, 4);
    await api(VERIFIER2, 'POST', `/gs/${gs.id}/counting/submit`, {}, true);

    await saveBuckets(USERS.aman, gs.id, babyId, { DMT_OK_PACKED: 4, DMT_BROKEN_BODY: 2 });
    await saveBuckets(USERS.aman, gs.id, akutemId, { PRS_OK: 3, PRS_BULB_BROKEN_NO_HG: 1 });
    await submitCategorisation(USERS.aman, gs.id);
    await approveAndStore(gs.id);

    // 2 broken baby thermometers to REPAIR, both come back repaired.
    const routing = await api<{ id: string; lines: Array<{ id: string }> }>(
      USERS.rm,
      'POST',
      '/department-routing/dispatch',
      {
        gs_id: gs.id,
        department_field_id: repairDeptId,
        lines: [{ gs_item_id: babyId, qty_sent: 2 }],
        remarks: tag,
      },
      true,
    );
    await receiveRouting(routing.id, routing.lines[0]?.id ?? '', [
      { outcome_head_code: 'REPAIRED', qty_received: 2 },
    ]);

    const acSlipId = await finalise(gs.id, {
      'ITM-00007': { SEND_NEW: 4, SEND_REPAIRED: 2 },
      'ITM-00013': { SEND_NEW: 4 },
    });
    const { alert } = await accountsAlertDispatch(gs.id, acSlipId, tag, 10);
    expect(alert.body).toContain('DMT-437');
    expect(alert.body).toContain('A-01 Akutem');
  });

  test('GS-3: E-Commerce return, Issue CN only -> no Dispatch Slip and no dispatch alert', async () => {
    const tag = `M3-${Date.now().toString().slice(-6)}`;
    const infra = await product('ITM-00012');

    const gs = await createEcommerceGs({ tag, cartonCount: 1 });
    await openCartons(gs.id, 1, `DN-${tag}`, USERS.aman);
    const itemId = await addLine(USERS.aman, gs.id, infra, 5, 5);
    await api(USERS.aman, 'POST', `/gs/${gs.id}/counting/submit`, {}, true);
    await saveBuckets(VERIFIER2, gs.id, itemId, { DMT_DISPLAY_ISSUE: 3, DMT_BROKEN_BODY: 2 });
    await submitCategorisation(VERIFIER2, gs.id);
    await approveAndStore(gs.id);

    const acSlipId = await finalise(gs.id, { 'ITM-00012': { ISSUE_CN: 5 } });
    const done = await accountsEntry(gs.id, acSlipId, tag);
    expect(done.dispatch_slip).toBeNull();
    expect(await dispatchAlerts(gs.id)).toHaveLength(0);
  });

  test('GS-4: RM sends categorisation back, the OTHER verifier corrects it; oval + DMT; dispatch', async () => {
    const tag = `M4-${Date.now().toString().slice(-6)}`;
    const oval = await product('ITM-00001');
    const fastRead = await product('ITM-00005');

    const gs = await createOfflineGs({ tag, cartonCount: 1 });
    await openCartons(gs.id, 1, `INV-${tag}`, USERS.aman);
    const ovalId = await addLine(USERS.aman, gs.id, oval, 4, 4);
    const frId = await addLine(USERS.aman, gs.id, fastRead, 3, 3);
    await api(USERS.aman, 'POST', `/gs/${gs.id}/counting/submit`, {}, true);

    await saveBuckets(USERS.aman, gs.id, ovalId, { EO_OK: 4 });
    await saveBuckets(USERS.aman, gs.id, frId, { DMT_OK_PACKED: 3 });
    await submitCategorisation(USERS.aman, gs.id);

    // RM sends it back; Verifier-2 (not the counter, not the first categoriser) corrects it.
    await api(
      USERS.rm,
      'POST',
      `/gs/${gs.id}/rm-send-back`,
      { remarks: '1 MT-401R display is faulty' },
      true,
    );
    await saveBuckets(VERIFIER2, gs.id, frId, { DMT_OK_PACKED: 2, DMT_DISPLAY_ISSUE: 1 });
    await submitCategorisation(VERIFIER2, gs.id);
    await approveAndStore(gs.id);

    const acSlipId = await finalise(gs.id, {
      'ITM-00001': { SEND_NEW: 4 },
      'ITM-00005': { SEND_NEW: 1, ISSUE_CN: 2 },
    });
    const { alert } = await accountsAlertDispatch(gs.id, acSlipId, tag, 5);
    expect(alert.body).toContain('ECO XL');
  });

  test('GS-6 (DEC-53): Counting & Categorisation in one step on a 360px phone -> RM Review', async ({
    browser,
  }) => {
    const tag = `M6-${Date.now().toString().slice(-6)}`;
    await ensureFieldProfiles();
    const dmt102 = await product('ITM-00003');

    const gs = await createOfflineGs({ tag, cartonCount: 1 });
    await openCartons(gs.id, 1, `INV-${tag}`, USERS.aman);

    const page = await openPage(browser, USERS.aman, `/gs/${gs.id}/itemization`);
    await page.setViewportSize({ width: 360, height: 800 });
    const editor = page.getByTestId('line-editor').last();
    await editor.locator('#line-new-product input').fill(dmt102.code);
    await page.getByRole('option', { name: dmt102.name }).first().click();

    // 4 as per document, 3 physically received; the split is entered on the same line.
    await editor.getByRole('spinbutton', { name: /As per document/ }).fill('4');
    await editor.getByRole('spinbutton', { name: 'Physically received' }).fill('3');
    const splitBox = editor.getByTestId('line-split-editor');
    await expect(splitBox).toBeVisible();
    const add = editor.getByRole('button', { name: 'Add line' });
    await expect(editor.getByTestId('split-total')).toHaveText('Split 0 / Physical 3');
    await expect(add).toBeDisabled();
    const buckets = splitBox.getByRole('spinbutton');
    await buckets.nth(0).fill('2');
    await buckets.nth(1).fill('1');
    await expect(editor.getByTestId('split-total')).toHaveText('Split 3 / Physical 3');
    await expectNoHorizontalOverflow(page);
    await add.click();

    const line = page.getByTestId('item-line').first();
    await expect(line).toContainText('Short 1');
    await expect(line.getByTestId('line-split')).toBeVisible();

    // One submit: ITEMIZATION -> CATEGORISATION -> RM_REVIEW in one transaction.
    await page.getByRole('button', { name: /^Submit to / }).click();
    await page.getByRole('button', { name: /Confirm submit/ }).click();
    await expect
      .poll(
        async () =>
          (await api<{ goods_slip: { status: string } }>(USERS.rm, 'GET', `/gs/${gs.id}`))
            .goods_slip.status,
        { timeout: 15_000 },
      )
      .toBe('RM_REVIEW');
    await expect(page.getByRole('status').filter({ hasText: /Submitted to/ })).toBeVisible();
    await expectNoHorizontalOverflow(page);

    // The RM sees the split recorded at counting.
    const review = await api<{ items: Array<{ total_bucket_qty: number }> }>(
      USERS.rm,
      'GET',
      `/gs/${gs.id}/rm-review`,
    );
    expect(review.items[0]?.total_bucket_qty).toBe(3);
  });
});
