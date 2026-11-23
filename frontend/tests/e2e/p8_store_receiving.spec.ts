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
 * Phase P8 (docs/RMS_PHASE_PROMPTS_20-11-2026.md; DEC-68) against the REAL local stack, at 360 px
 * and 1280 px. Setup through the API: one locked Replacement GS with a DT (DMT) line of 3; the RM
 * generates the slip, the DT store acknowledges it and routes all 3 pcs to a work department (DIN).
 * The DT store user opens "Receive from Departments", sees the GS (party-wise) with its DIN, receives
 * 1 pc (partial), then the remaining 2 pcs. The DIN leaves the queue and the store is ready for
 * analysis. No console errors, no horizontal scroll, touch targets ≥ 44 px.
 */
const DT_STORE = 'dtstore@rms.local';
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
    store: { id: string } | null;
    conditions: Array<{ field_id: string; current_qty: number }>;
    allowed_departments: Array<{ field_id: string; code: string; is_no_work: boolean }>;
  }>;
}

test.describe('P8 store receiving', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(testInfo.project.name !== 'desktop-chrome', 'Sets 360 / 1280 px widths itself');
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  for (const vp of WIDTHS) {
    test(`the DT store receives its goods back at ${vp.name}`, async ({ browser }) => {
      test.setTimeout(240_000);
      const dmt = await productOf('DMT');
      const gs = await lockedGs(`P8${String(vp.width)}`, [[dmt, 3]]);
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
      if (!item) throw new Error('expected a DT item');
      const dept = item.allowed_departments.find((d) => !d.is_no_work);
      if (!dept) throw new Error('expected a work department');
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
              department_field_id: dept.field_id,
              qty: c.current_qty,
            })),
        },
        true,
      );
      await expect.poll(() => gsStatus(gs.id)).toBe('STORE_PROCESSING');

      const dt = await asUser(browser, DT_STORE, '/store-receiving');
      await dt.page.setViewportSize({ width: vp.width, height: vp.height });
      const page = dt.page.getByTestId('store-receiving');
      await expect(page.getByRole('heading', { name: 'Receive from Departments' })).toBeVisible();
      const card = page.getByRole('listitem').filter({ hasText: gs.gs_no }).first();
      await expect(card).toBeVisible({ timeout: 20_000 });
      await expect(card).toContainText('DT: At departments');
      await expect(card).toContainText('Pending 3');
      const receive = card.getByRole('button', { name: 'Receive' });
      expect((await receive.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
      await expectNoHorizontalOverflow(dt.page);
      await dt.page.screenshot({ path: `test-results/p8/${vp.name}-queue.png`, fullPage: true });

      // Partial: 1 of 3 back.
      await receive.click();
      const dialog = dt.page.getByRole('dialog');
      await expect(dialog.getByText('Receive from Department')).toBeVisible({ timeout: 20_000 });
      await expect(dialog).toContainText('Ready for analysis.');
      await expect(dialog).toContainText('Stock goes back to Intermediate Store DT.');
      await dialog.getByLabel('Qty').first().fill('1');
      await expectNoHorizontalOverflow(dt.page);
      await dt.page.screenshot({ path: `test-results/p8/${vp.name}-receive.png`, fullPage: true });
      await dialog.getByRole('button', { name: /Confirm receipt \(1 pcs\)/ }).click();
      await expect(page.getByText(/Receipt recorded for/)).toBeVisible({ timeout: 20_000 });
      await expect(card).toContainText('Pending 2');

      // The rest: the DIN leaves the queue.
      await card.getByRole('button', { name: 'Receive' }).click();
      await expect(dialog.getByText('Receive from Department')).toBeVisible({ timeout: 20_000 });
      await dialog.getByRole('button', { name: /Confirm receipt \(2 pcs\)/ }).click();
      await expect(page.getByText(/Receipt recorded for/)).toBeVisible({ timeout: 20_000 });
      await expect(page.getByRole('listitem').filter({ hasText: gs.gs_no })).toHaveCount(0);
      const after = await api<{ stores: Array<{ store_code: string; status: string }> }>(
        DT_STORE,
        'GET',
        `/department-routing/store/gs/${gs.id}`,
      );
      expect(after.stores.find((s) => s.store_code === 'DT')?.status).toBe('READY_FOR_ANALYSIS');
      await expectNoHorizontalOverflow(dt.page);
      await dt.page.screenshot({ path: `test-results/p8/${vp.name}-done.png`, fullPage: true });
      expect(dt.errors).toEqual([]);
      await dt.context.close();
    });
  }
});
