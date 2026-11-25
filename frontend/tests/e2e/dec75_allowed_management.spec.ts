import { expect, test } from '@playwright/test';

import { decideGroup, reviewAndSubmit } from './support/analysis';
import {
  api,
  apiAvailable,
  asUser,
  expectNoHorizontalOverflow,
  gsStatus,
  USERS,
} from './support/stack';
import { lockedGs, productOf } from './support/transfer_slips';

/**
 * DEC-75 (user request 2026-11-25) against the REAL local stack, at 360 px and 1280 px. Setup
 * through the API: one locked Replacement GS with a DT (DMT) line of 3, acknowledged and routed
 * "Issue to Store" by the DT store. In the browser the DT store user gives the first condition
 * "Not Allowed" and the rest "Allowed → Send New Pieces to Party", and sends the Not Allowed
 * pieces to Management proposing Issue CN, with a note. Management sees the previous action and
 * the proposal, applies it in one tap, saves and approves; the goods slip goes to Accounts, whose
 * action sheet lists every item with its action and qty.
 * No console errors, no horizontal scroll, touch targets ≥ 44 px.
 */
const DT_STORE = 'dtstore@rms.local';
const MGMT = 'mgmt@rms.local';
const WIDTHS = [
  { name: 'phone-360', width: 360, height: 780 },
  { name: 'desktop-1280', width: 1280, height: 900 },
];

interface Slip {
  id: string;
  store: { id: string; code: string };
}
interface RoutingView {
  items: Array<{
    item_id: string;
    is_mine: boolean;
    conditions: Array<{ field_id: string; current_qty: number }>;
    allowed_departments: Array<{ field_id: string; code: string; is_no_work: boolean }>;
  }>;
}

async function readyForAnalysis(tag: string): Promise<{ id: string; gs_no: string }> {
  const dmt = await productOf('DMT');
  const gs = await lockedGs(tag, [[dmt, 3]]);
  const gen = await api<{ slips: Slip[] }>(
    USERS.rm,
    'POST',
    '/transfer-slips',
    { gs_ids: [gs.id] },
    true,
  );
  const dtSlip = gen.slips.find((s) => s.store.code === 'DT');
  if (!dtSlip) throw new Error('expected a DT slip');
  await api(DT_STORE, 'POST', `/transfer-slips/${dtSlip.id}/acknowledge`, {}, true);
  const view = await api<RoutingView>(DT_STORE, 'GET', `/department-routing/store/gs/${gs.id}`);
  const item = view.items.find((i) => i.is_mine);
  const noWork = item?.allowed_departments.find((d) => d.is_no_work);
  if (!item || !noWork) throw new Error('expected a DT item with "Issue to Store"');
  await api(
    DT_STORE,
    'POST',
    `/department-routing/store/gs/${gs.id}/route`,
    {
      store_id: dtSlip.store.id,
      lines: item.conditions
        .filter((c) => c.current_qty > 0)
        .map((c) => ({
          gs_item_id: item.item_id,
          source_bucket_field_id: c.field_id,
          department_field_id: noWork.field_id,
          qty: c.current_qty,
        })),
    },
    true,
  );
  await expect.poll(() => gsStatus(gs.id)).toBe('STORE_PROCESSING');
  return gs;
}

test.describe('DEC-75 Allowed / Not Allowed + pieces to Management', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(testInfo.project.name !== 'desktop-chrome', 'Sets 360 / 1280 px widths itself');
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  for (const vp of WIDTHS) {
    test(`store sends pieces, Management decides, Accounts sees the sheet at ${vp.name}`, async ({
      browser,
    }) => {
      test.setTimeout(300_000);
      const gs = await readyForAnalysis(`D75${String(vp.width)}`);

      // --- the store ------------------------------------------------------------------------
      const dt = await asUser(browser, DT_STORE, '/store-analysis');
      await dt.page.setViewportSize({ width: vp.width, height: vp.height });
      const queue = dt.page.getByTestId('store-analysis-queue');
      const card = queue.getByRole('listitem').filter({ hasText: gs.gs_no }).first();
      await expect(card).toBeVisible({ timeout: 20_000 });
      await card.getByRole('button').click();

      const page = dt.page.getByTestId('store-analysis-gs');
      await expect(page.getByRole('heading', { name: `Analysis ${gs.gs_no}` })).toBeVisible({
        timeout: 20_000,
      });
      const line = page.getByTestId('analysis-item-1');
      await expect(line).not.toContainText(/Issue CN/);
      const groups = line.locator('fieldset');
      const count = await groups.count();
      // First condition: 1 piece Allowed (sent new), the rest Not Allowed (step 1 → step 2).
      const g0 = groups.first();
      await g0.getByLabel(/^Allowed pieces, /).fill('1');
      await expect(g0.getByLabel(/^Not Allowed pieces, /)).not.toHaveText('0');
      await g0.getByRole('button', { name: 'All 1 allowed pcs: Send New Pieces to Party' }).click();
      await expect(g0).toContainText('Decided');
      for (let i = 1; i < count; i += 1) {
        await decideGroup(groups.nth(i), 'Send New Pieces to Party');
      }
      await expectNoHorizontalOverflow(dt.page);
      await dt.page.screenshot({ path: `test-results/dec75/${vp.name}-store.png`, fullPage: true });

      await reviewAndSubmit(dt.page, page, {
        proposal: 'Issue CN',
        note: 'Party insists on a CN',
        from: 'Not Allowed',
      });
      const waiting = page.getByTestId('approval-request');
      await expect(waiting).toContainText('Not Allowed → Issue CN');
      await expect.poll(() => gsStatus(gs.id)).toBe('ANALYSIS_COMPLETED');
      await expectNoHorizontalOverflow(dt.page);
      await dt.page.screenshot({ path: `test-results/dec75/${vp.name}-sent.png`, fullPage: true });
      expect(dt.errors).toEqual([]);
      await dt.context.close();

      // --- Management -----------------------------------------------------------------------
      const m = await asUser(browser, MGMT, '/management-approval');
      await m.page.setViewportSize({ width: vp.width, height: vp.height });
      const mq = m.page.getByTestId('management-approval-queue');
      const mcard = mq.getByRole('listitem').filter({ hasText: gs.gs_no }).first();
      await expect(mcard).toBeVisible({ timeout: 20_000 });
      await expect(mcard).toContainText(/Sent by store · \d+ pcs/);
      await mcard.getByRole('button').first().click();

      const mp = m.page.getByTestId('management-approval-gs');
      const first = mp.getByTestId('mgmt-item-1').locator('fieldset').first();
      await expect(first).toContainText('previous action Not Allowed', { timeout: 20_000 });
      await expect(first).toContainText('proposes Issue CN');
      const apply = first.getByRole('button', { name: /^Apply: Issue CN \d+ pcs$/ });
      expect((await apply.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
      await apply.click();
      await expect(first).toContainText(/(\d+) of \1 decided/);
      await expectNoHorizontalOverflow(m.page);
      await m.page.screenshot({ path: `test-results/dec75/${vp.name}-mgmt.png`, fullPage: true });
      await mp.getByRole('button', { name: 'Save changes' }).click();
      await expect(mp.getByText(/Changes saved/)).toBeVisible({ timeout: 20_000 });
      // The store's own decision stays visible after the change.
      await expect(first).toContainText('Store decided: Not Allowed');
      await mp.getByRole('button', { name: 'Approve' }).click();
      const mdialog = m.page.getByRole('dialog');
      await mdialog.getByRole('button', { name: 'Approve' }).click();
      await expect(mp.getByTestId('stamp-text')).toContainText('Digitally approved by Management', {
        timeout: 20_000,
      });
      await expect.poll(() => gsStatus(gs.id)).toBe('ACCOUNTS_PENDING');
      expect(m.errors).toEqual([]);
      await m.context.close();

      // --- Accounts: the action sheet -------------------------------------------------------
      const a = await asUser(browser, USERS.accounts, '/accounts-entry');
      await a.page.setViewportSize({ width: vp.width, height: vp.height });
      await a.page.getByRole('button').filter({ hasText: gs.gs_no }).first().click({
        timeout: 20_000,
      });
      const sheet = a.page.getByTestId('action-sheet');
      await expect(sheet).toBeVisible({ timeout: 20_000 });
      await expect(sheet).toContainText('Issue CN');
      await expect(sheet).toContainText('Send New Pieces to Party');
      await expectNoHorizontalOverflow(a.page);
      await a.page.screenshot({
        path: `test-results/dec75/${vp.name}-accounts.png`,
        fullPage: true,
      });
      expect(a.errors).toEqual([]);
      await a.context.close();
    });
  }
});
