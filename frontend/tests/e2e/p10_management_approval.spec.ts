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
 * Phase P10 (docs/RMS_PHASE_PROMPTS_20-11-2026.md; DEC-70) against the REAL local stack, at 360 px
 * and 1280 px. Setup through the API: one locked Replacement GS with a DT (DMT) line of 3; the DT
 * store acknowledges, routes everything "Issue to Store", decides "Dispatch New Piece" and submits
 * together with a request for Management approval (reason; the GS stays Analysis Completed). In the
 * browser, Management opens "Management Approval", changes the first condition to Issue CN with a
 * reason, saves, approves (e-approval stamp) and verifies it; the goods slip page shows the stamp.
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
interface AnalysisView {
  items: Array<{
    gs_item_id: string;
    is_mine: boolean;
    groups: Array<{ condition_field_id: string | null; qty: number }>;
  }>;
}

async function analysedAndSent(tag: string): Promise<{ id: string; gs_no: string }> {
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
  const analysis = await api<AnalysisView>(DT_STORE, 'GET', `/store-analysis/gs/${gs.id}`);
  await api(
    DT_STORE,
    'POST',
    `/store-analysis/gs/${gs.id}/submit`,
    {
      store_id: dtSlip.store.id,
      lines: analysis.items
        .filter((i) => i.is_mine)
        .flatMap((i) =>
          i.groups
            .filter((g) => g.qty > 0)
            .map((g) => ({
              gs_item_id: i.gs_item_id,
              condition_field_id: g.condition_field_id,
              decisions: [{ action_code: 'SEND_NEW', qty: g.qty }],
            })),
        ),
      // DEC-71 (P11): the only store's submission would route the GS to Accounts at once, so the
      // request goes with the submission (Q36: after its own analysis, same transaction).
      management_approval_reason: 'Party asks for a credit note',
    },
    true,
  );
  await expect.poll(() => gsStatus(gs.id)).toBe('ANALYSIS_COMPLETED');
  return gs;
}

test.describe('P10 Management approval', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(testInfo.project.name !== 'desktop-chrome', 'Sets 360 / 1280 px widths itself');
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  for (const vp of WIDTHS) {
    test(`Management changes to Issue CN and approves at ${vp.name}`, async ({ browser }) => {
      test.setTimeout(240_000);
      const gs = await analysedAndSent(`P10${String(vp.width)}`);

      const m = await asUser(browser, MGMT, '/management-approval');
      await m.page.setViewportSize({ width: vp.width, height: vp.height });
      const queue = m.page.getByTestId('management-approval-queue');
      await expect(queue.getByRole('heading', { name: 'Management Approval' })).toBeVisible();
      const sent = queue.getByRole('list', { name: 'Sent for approval' });
      const card = sent.getByRole('listitem').filter({ hasText: gs.gs_no }).first();
      await expect(card).toBeVisible({ timeout: 20_000 });
      await expect(card).toContainText('Party asks for a credit note');
      await expectNoHorizontalOverflow(m.page);
      await m.page.screenshot({ path: `test-results/p10/${vp.name}-queue.png`, fullPage: true });
      await card.getByRole('button').click();

      const page = m.page.getByTestId('management-approval-gs');
      await expect(
        page.getByRole('heading', { name: `Management Approval · ${gs.gs_no}` }),
      ).toBeVisible({ timeout: 20_000 });
      await expect(page.getByTestId('open-request')).toContainText('Party asks for a credit note');
      const line = page.getByTestId('mgmt-item-1');
      const first = line.locator('fieldset').first();
      const toCn = first.getByRole('button', { name: /: Issue CN$/ });
      expect((await toCn.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
      await toCn.click();
      await expect(first).toContainText(/(\d+) of \1 decided/);
      const save = page.getByRole('button', { name: 'Save changes' });
      await expect(save).toBeDisabled(); // a reason is required
      await first.getByLabel('Reason for this change (required)').fill('Party credit note agreed');
      await expect(save).toBeEnabled();
      expect((await save.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
      await expectNoHorizontalOverflow(m.page);
      await m.page.screenshot({ path: `test-results/p10/${vp.name}-changed.png`, fullPage: true });
      await save.click();
      await expect(page.getByText(/Changes saved/)).toBeVisible({ timeout: 20_000 });
      await expect(page).toContainText('Party credit note agreed');

      await page.getByRole('button', { name: 'Approve' }).click();
      const dialog = m.page.getByRole('dialog');
      await expect(dialog.getByText('Approve this goods slip?')).toBeVisible();
      await expectNoHorizontalOverflow(m.page);
      await dialog.getByRole('button', { name: 'Approve' }).click();
      const stamp = page.getByTestId('stamp-text');
      await expect(stamp).toContainText('Digitally approved by Management', { timeout: 20_000 });
      await expect(stamp).toContainText(/ref [0-9a-f]{12}$/);
      await expect(page.getByTestId('open-request')).toHaveCount(0);
      await page.getByRole('button', { name: 'Verify' }).click();
      await expect(page.getByTestId('verify-result')).toContainText('Valid', { timeout: 20_000 });
      await expectNoHorizontalOverflow(m.page);
      await m.page.screenshot({ path: `test-results/p10/${vp.name}-approved.png`, fullPage: true });

      // The goods slip page carries the stamp too.
      await page.getByRole('button', { name: 'Open goods slip' }).click();
      await expect(m.page.getByTestId('approval-stamp')).toContainText(
        'Digitally approved by Management',
        { timeout: 20_000 },
      );
      await expectNoHorizontalOverflow(m.page);
      await m.page.screenshot({ path: `test-results/p10/${vp.name}-gs.png`, fullPage: true });
      expect(m.errors).toEqual([]);
      await m.context.close();
    });
  }
});
