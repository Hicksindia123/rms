import { expect, test, type Page } from '@playwright/test';

import {
  addItem,
  api,
  apiAvailable,
  asUser,
  categorize,
  createGs,
  type Device,
  expectNoHorizontalOverflow,
  GATE_PROJECTS,
  inspectByApi,
  productId,
  unboxed,
  USERS,
} from './support/stack';

/**
 * P3-01 · Step-4 handover against the REAL local stack (BR-21, G-09): Aman initiates on the
 * project device (Pixel 7 = mobile), Sahil reports a discrepancy, both sign the reconciliation,
 * then a clean handover of the returned piece is accepted. Preconditions through the API only.
 *
 * Needs: `supabase start`, demo users (backend/scripts/seed_demo_users.py), the API on :8000.
 */

const devices: Device[] = [];

async function rmFinalised(tag: string, qty: number): Promise<string> {
  const gs = await createGs(tag);
  await unboxed(gs);
  const item = await addItem(gs.id, await productId('DEMO-DMT-001'), qty, qty);
  await categorize(gs.id, 'RO');
  await inspectByApi(item, { DMT_OK_PACKED: qty });
  await api(USERS.rm, 'PUT', `/gs/${gs.id}/rm-actions`, {
    lines: [{ gs_item_id: item, actions: [{ action_code: 'SEND_NEW', qty }] }],
  });
  await api(USERS.rm, 'POST', `/gs/${gs.id}/rm-actions/finalise`, {});
  return gs.id;
}

test.describe('Custody handover (P3-01)', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(
      !GATE_PROJECTS.includes(testInfo.project.name),
      'P3-01 scenarios run on desktop-chromium and mobile-pixel-7',
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
  });

  async function open(browser: Parameters<typeof asUser>[0], email: string, path: string) {
    const d = await asUser(browser, email, path);
    devices.push(d);
    return d.page;
  }

  async function transferIdFrom(page: Page): Promise<string> {
    await expect(page).toHaveURL(/#\/custody\/transfers\/[0-9a-f-]{36}$/);
    return page.url().split('/').pop() ?? '';
  }

  test('discrepancy halts, both parties reconcile, then a clean handover is accepted', async ({
    browser,
  }) => {
    test.setTimeout(120_000);
    const gsId = await rmFinalised('P301', 6);

    // 1. Aman initiates the handover.
    const aman = await open(browser, USERS.aman, `/gs/${gsId}/handover`);
    await expect(
      aman.getByRole('heading', { name: 'Handover to Intermediate Store' }),
    ).toBeVisible();
    await expect(aman.getByText('To hand over (6 pcs)')).toBeVisible();
    await expectNoHorizontalOverflow(aman);
    await aman.getByRole('button', { name: 'Confirm handover' }).click();
    const transferId = await transferIdFrom(aman);
    await expect(aman.getByText('In transit', { exact: true })).toBeVisible();
    await expect(
      aman.getByText(/neither Inward Staging nor Intermediate Store holds/),
    ).toBeVisible();

    // 2. Sahil counts 5 and reports a discrepancy.
    const sahil = await open(browser, USERS.sahil, `/custody/transfers/${transferId}`);
    const accept = sahil.getByRole('button', { name: /Accepted - Quantity/ });
    await expect(accept).toBeEnabled();
    await sahil.getByRole('button', { name: /^Decrease Counted/ }).click();
    await expect(accept).toBeDisabled();
    await sahil.getByLabel(/Discrepancy details/).fill('One piece missing from the carton');
    await sahil.getByRole('button', { name: /Discrepancy Reported/ }).click();
    await expect(sahil.getByText(/frozen in transit/)).toBeVisible();
    await expectNoHorizontalOverflow(sahil);

    // 3. Sahil proposes: accept the counted 5, return the difference to Aman.
    await sahil.getByLabel('Resolution').selectOption('ACCEPT_COUNTED_WITH_ADJUSTMENT');
    await sahil.getByLabel('Pieces not counted').selectOption('RETURN_TO_SOURCE');
    await sahil.getByLabel('Notes', { exact: true }).fill('Missing piece stays with Aman');
    await sahil.getByRole('button', { name: /Sign as receiver/ }).click();
    await expect(sahil.getByText('Receiver: Sahil', { exact: false })).toBeVisible();

    // 4. Aman co-signs the same resolution → reconciled.
    await aman.reload(); // Aman is still on this transfer: load the current state
    await aman.getByLabel('Resolution').selectOption('ACCEPT_COUNTED_WITH_ADJUSTMENT');
    await aman.getByLabel('Pieces not counted').selectOption('RETURN_TO_SOURCE');
    await aman.getByLabel('Notes', { exact: true }).fill('Agreed, piece found on my table');
    await aman.getByRole('button', { name: /Sign as sender/ }).click();
    await expect(aman.getByText('Reconciled', { exact: true })).toBeVisible();
    await expect(aman.getByText('5 / 5 / 1')).toBeVisible(); // counted / accepted / returned

    // 5. A clean handover of the returned piece, accepted by Sahil.
    await aman.goto(`/#/gs/${gsId}/handover`);
    await expect(aman.getByText('To hand over (1 pcs)')).toBeVisible();
    await aman.getByRole('button', { name: 'Confirm handover' }).click();
    const second = await transferIdFrom(aman);
    await sahil.goto(`/#/custody/transfers/${second}`);
    await sahil.getByRole('button', { name: /Accepted - Quantity/ }).click();
    await expect(sahil.getByText('Accepted', { exact: true })).toBeVisible();

    // The Intermediate Store holds all 6; nothing is left in transit.
    await sahil.goto('/#/custody/store');
    await expect(sahil.getByText(/Demo DMT Product/).first()).toBeVisible();
    await expectNoHorizontalOverflow(sahil);
    const stock = await api<{ rows: Array<{ gs_id: string; qty: number }> }>(
      USERS.sahil,
      'GET',
      `/custody/intermediate-store/stock?gs_id=${gsId}`,
    );
    expect(stock.rows.reduce((a, r) => a + r.qty, 0)).toBe(6);
    const live = await api<{ total: number }>(
      USERS.rm,
      'GET',
      `/custody/transfers?gs_id=${gsId}&status=INITIATED`,
    );
    expect(live.total).toBe(0);
  });
});
