import { expect, test } from '@playwright/test';

import {
  api,
  apiAvailable,
  asUser,
  expectNoHorizontalOverflow,
  gsStatus,
  USERS,
} from './support/stack';
import { decideGroup, reviewAndSubmit } from './support/analysis';
import { lockedGs, productOf } from './support/transfer_slips';

/**
 * Phase P9 (docs/RMS_PHASE_PROMPTS_20-11-2026.md; DEC-69) against the REAL local stack, at 360 px
 * and 1280 px. Setup through the API: one locked Replacement GS with a DT (DMT) line of 3; the RM
 * generates the slip, the DT store acknowledges it and routes every piece "Issue to Store" (no
 * work), so its part is ready for analysis. The DT store user opens "Analysis", gives each
 * condition its verdict (Allowed → Send New Pieces / Not Allowed; DEC-75), sends the first
 * condition's pieces to Management (proposal Issue CN) with the submission; the GS becomes Analysis
 * Completed and waits for Management. No console errors, no horizontal scroll, touch targets
 * ≥ 44 px.
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
    conditions: Array<{ field_id: string; current_qty: number }>;
    allowed_departments: Array<{ field_id: string; code: string; is_no_work: boolean }>;
  }>;
}

test.describe('P9 store analysis', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(testInfo.project.name !== 'desktop-chrome', 'Sets 360 / 1280 px widths itself');
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  for (const vp of WIDTHS) {
    test(`the DT store analyses its goods at ${vp.name}`, async ({ browser }) => {
      test.setTimeout(240_000);
      const dmt = await productOf('DMT');
      const gs = await lockedGs(`P9${String(vp.width)}`, [[dmt, 3]]);
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
      const noWork = item.allowed_departments.find((d) => d.is_no_work);
      if (!noWork) throw new Error('expected an "Issue to Store" department for DMT');
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

      const dt = await asUser(browser, DT_STORE, '/store-analysis');
      await dt.page.setViewportSize({ width: vp.width, height: vp.height });
      const queue = dt.page.getByTestId('store-analysis-queue');
      await expect(queue.getByRole('heading', { name: 'Analysis' })).toBeVisible();
      const card = queue.getByRole('listitem').filter({ hasText: gs.gs_no }).first();
      await expect(card).toBeVisible({ timeout: 20_000 });
      await expect(card).toContainText('DT: Ready for analysis');
      await expectNoHorizontalOverflow(dt.page);
      await dt.page.screenshot({ path: `test-results/p9/${vp.name}-queue.png`, fullPage: true });
      await card.getByRole('button').click();

      const page = dt.page.getByTestId('store-analysis-gs');
      await expect(page.getByRole('heading', { name: `Analysis ${gs.gs_no}` })).toBeVisible({
        timeout: 20_000,
      });
      const line = page.getByTestId('analysis-item-1');
      await expect(line).toBeVisible();
      // Issue CN stays Management's (DEC-70); step 1 offers only the two verdicts (DEC-75).
      await expect(line).not.toContainText(/Issue CN/);
      await expect(line).toContainText('Allowed');
      await expect(line).toContainText('Not Allowed');
      const review = page.getByRole('button', { name: /Review & submit/ });
      await expect(review).toBeDisabled();
      // Nothing to send to Management before the store's own submission.
      await expect(page.getByRole('button', { name: /Send for Management approval/ })).toHaveCount(
        0,
      );

      // Decide: the first condition all Allowed → sent as new pieces, the others Not Allowed.
      const groups = line.locator('fieldset');
      const count = await groups.count();
      for (let i = 0; i < count; i += 1) {
        const g = groups.nth(i);
        const verdict = g.getByRole('button', {
          name: i === 0 ? /^All \d+ pcs Allowed$/ : /^All \d+ pcs Not Allowed$/,
        });
        expect((await verdict.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
        await decideGroup(g, i === 0 ? 'Send New Pieces to Party' : 'Not Allowed');
      }
      await expect(review).toBeEnabled();
      await expectNoHorizontalOverflow(dt.page);
      await dt.page.screenshot({ path: `test-results/p9/${vp.name}-decided.png`, fullPage: true });

      // The only store's submission would send the GS on to Accounts; the store sends its
      // first condition's pieces to Management (proposal: Issue CN) with the submission.
      await reviewAndSubmit(dt.page, page, { proposal: 'Issue CN', note: 'Party asks for a CN' });
      await expect(page).toContainText('Every store has submitted');
      await expect(page.getByRole('button', { name: /Review & submit/ })).toHaveCount(0);
      await expect.poll(() => gsStatus(gs.id)).toBe('ANALYSIS_COMPLETED');
      await expect(page.getByTestId('approval-request')).toContainText('→ Issue CN', {
        timeout: 20_000,
      });
      await expectNoHorizontalOverflow(dt.page);
      await dt.page.screenshot({ path: `test-results/p9/${vp.name}-done.png`, fullPage: true });
      expect(dt.errors).toEqual([]);
      await dt.context.close();
    });
  }
});
