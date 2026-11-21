import { expect, test } from '@playwright/test';

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
 * Phase P7 (docs/RMS_PHASE_PROMPTS_20-11-2026.md; DEC-67, Q14, Q29) against the REAL local stack,
 * at 360 px and 1280 px. Setup through the API: one locked Replacement GS with a DT (DMT) line of 3
 * and an OP (Enclosed Oval) line of 1; the RM generates the two slips; the DT store acknowledges
 * its slip (OP has not yet). The DT store user opens "Department Routing", sees only its own item,
 * ticks "Show all items" (the OP item shows read-only, not acknowledged), splits its condition
 * across two departments (2 "no work" + 1 to a work department), saves = issue, and opens the DIN.
 * The GS is STORE_PROCESSING. No console errors, no horizontal scroll, touch targets ≥ 44 px.
 */
const DT_STORE = 'dtstore@rms.local';
const WIDTHS = [
  { name: 'phone-360', width: 360, height: 780 },
  { name: 'desktop-1280', width: 1280, height: 900 },
];

interface Slip {
  id: string;
  store: { code: string };
}

test.describe('P7 store department routing', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(testInfo.project.name !== 'desktop-chrome', 'Sets 360 / 1280 px widths itself');
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  for (const vp of WIDTHS) {
    test(`the DT store routes its goods at ${vp.name}`, async ({ browser }) => {
      test.setTimeout(240_000);
      const dmt = await productOf('DMT');
      const eo = await productOf('ENCLOSED_OVAL');
      const gs = await lockedGs(`P7${String(vp.width)}`, [
        [dmt, 3],
        [eo, 1],
      ]);
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

      const dt = await asUser(browser, DT_STORE, '/store-routing');
      await dt.page.setViewportSize({ width: vp.width, height: vp.height });
      const queue = dt.page.getByTestId('store-routing-queue');
      await expect(queue.getByRole('heading', { name: 'Department Routing' })).toBeVisible();
      const row = queue.getByRole('button', { name: new RegExp(gs.gs_no) });
      await expect(row).toBeVisible({ timeout: 20_000 });
      await expect(row).toContainText('DT: Routing pending (3 pcs)');
      await expectNoHorizontalOverflow(dt.page);
      await dt.page.screenshot({ path: `test-results/p7/${vp.name}-queue.png`, fullPage: true });

      await row.click();
      const view = dt.page.getByTestId('store-routing-gs');
      await expect(view.getByTestId('routing-item-1')).toBeVisible({ timeout: 20_000 });
      await expect(view.getByTestId('routing-item-2')).toHaveCount(0);
      await view.getByLabel(/Show all items of this GS/).check();
      const other = view.getByTestId('routing-item-2');
      await expect(other).toContainText('Intermediate Store OP');
      await expect(other).toContainText('Not acknowledged');
      await expect(other.getByRole('spinbutton')).toHaveCount(0);
      await view.getByLabel(/Show all items of this GS/).uncheck();

      // One condition of 3 pcs split: 2 "no work" + 1 to a work department.
      const item = view.getByTestId('routing-item-1');
      const noWork = item.locator('label', { hasText: 'stays in store' }).first();
      const noWorkInput = item.locator(`#${await escapeId(noWork)}`);
      await noWorkInput.fill('2');
      const work = item.locator('label').filter({ hasNotText: 'stays in store' }).first();
      const workLabel = (await work.innerText()).trim();
      await item.locator(`#${await escapeId(work)}`).fill('1');
      const save = dt.page.getByRole('button', { name: 'Save routing' });
      expect((await save.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
      await expectNoHorizontalOverflow(dt.page);
      await dt.page.screenshot({ path: `test-results/p7/${vp.name}-routing.png`, fullPage: true });
      await save.click();
      const dialog = dt.page.getByRole('dialog');
      await expect(dialog).toContainText('2 pcs');
      await expect(dialog).toContainText(workLabel);
      await dialog.getByRole('button', { name: /Save & issue/ }).click();
      await expect(dt.page.getByText(/Routing saved for Intermediate Store DT/)).toBeVisible({
        timeout: 20_000,
      });
      await expect(dt.page.getByText(/2 pc\(s\) stay in the store/)).toBeVisible();
      await expect.poll(() => gsStatus(gs.id)).toBe('STORE_PROCESSING');
      await expect(item).toContainText(workLabel);
      await expectNoHorizontalOverflow(dt.page);
      await dt.page.screenshot({ path: `test-results/p7/${vp.name}-saved.png`, fullPage: true });

      // The DIN opens for printing.
      await dt.page.getByTestId('din-print').first().click();
      await expect(dt.page.getByText('DEPARTMENT ISSUE NOTE (DIN)')).toBeVisible({
        timeout: 20_000,
      });
      // The DIN names the store the pieces left (DEC-67), not the legacy Intermediate Store.
      await expect(dt.page.getByText('Source Location:').locator('..')).toContainText(
        'Intermediate Store DT',
      );
      await expectNoHorizontalOverflow(dt.page);
      await dt.page.screenshot({ path: `test-results/p7/${vp.name}-din.png`, fullPage: true });
      // Back returns to the routing view.
      await dt.page.getByRole('button', { name: /Back to Details/ }).click();
      await expect(dt.page.getByTestId('store-routing-gs')).toBeVisible({ timeout: 20_000 });
      expect(dt.errors).toEqual([]);
      await dt.context.close();
    });
  }
});

/** The input a label points at (its `for` id, CSS-escaped: ids contain "|"). */
async function escapeId(label: import('@playwright/test').Locator): Promise<string> {
  const id = await label.getAttribute('for');
  if (!id) throw new Error('label without for');
  return id.replace(/[|]/g, '\\|');
}
