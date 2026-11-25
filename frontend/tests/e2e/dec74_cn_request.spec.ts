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
 * DEC-74 (user request 2026-11-25) against the REAL local stack, at 360 px and 1280 px. Setup
 * through the API: one locked Replacement GS with a DT (DMT) line of 3, acknowledged and routed
 * "Issue to Store" by the DT store. In the browser the DT store user puts the pieces of the first
 * condition on "Issue CN Request" (the others Dispatch New Piece) and submits with a note; the
 * goods slip waits (Analysis Completed). Management sees the request, cannot approve until it
 * decides, grants the CN in one tap, saves and approves: the goods slip goes to Accounts.
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

test.describe('DEC-74 Issue CN Request', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(testInfo.project.name !== 'desktop-chrome', 'Sets 360 / 1280 px widths itself');
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  for (const vp of WIDTHS) {
    test(`store requests CN, Management decides at ${vp.name}`, async ({ browser }) => {
      test.setTimeout(240_000);
      const gs = await readyForAnalysis(`D74${String(vp.width)}`);

      // --- the store ------------------------------------------------------------------------
      const dt = await asUser(browser, DT_STORE, '/store-analysis');
      await dt.page.setViewportSize({ width: vp.width, height: vp.height });
      const queue = dt.page.getByTestId('store-analysis-queue');
      const card = queue.getByRole('listitem').filter({ hasText: gs.gs_no }).first();
      await expect(card).toBeVisible({ timeout: 20_000 });
      await card.getByRole('button').click();

      const page = dt.page.getByTestId('store-analysis-gs');
      await expect(page.getByRole('heading', { name: `Analysis · ${gs.gs_no}` })).toBeVisible({
        timeout: 20_000,
      });
      const line = page.getByTestId('analysis-item-1');
      await expect(line).toContainText('Issue CN Request');
      await expect(line).not.toContainText(/Issue CN(?! Request)/);
      const groups = line.locator('fieldset');
      const count = await groups.count();
      let requested = 0;
      for (let i = 0; i < count; i += 1) {
        const g = groups.nth(i);
        const shortcut = g.getByRole('button', {
          name: i === 0 ? /: Issue CN Request$/ : /: Dispatch New Piece$/,
        });
        expect((await shortcut.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
        await shortcut.click();
        await expect(g).toContainText(/(\d+) of \1 decided/);
        if (i === 0) {
          const m = /(\d+) of \d+ decided/.exec((await g.textContent()) ?? '');
          requested = Number(m?.[1] ?? 0);
        }
      }
      expect(requested).toBeGreaterThan(0);
      await expectNoHorizontalOverflow(dt.page);
      await dt.page.screenshot({ path: `test-results/dec74/${vp.name}-store.png`, fullPage: true });

      await page.getByRole('button', { name: 'Submit analysis' }).click();
      const dialog = dt.page.getByRole('dialog');
      await expect(dialog.getByTestId('cn-request-notice')).toContainText(
        `${String(requested)} pc(s) go to Management as an Issue CN Request`,
      );
      await dialog.getByLabel('Note for Management (optional)').fill('Party insists on a CN');
      const send = dialog.getByRole('button', { name: 'Submit & send CN request' });
      expect((await send.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
      await expectNoHorizontalOverflow(dt.page);
      await dt.page.screenshot({ path: `test-results/dec74/${vp.name}-confirm.png`, fullPage: true });
      await send.click();
      await expect(page.getByText(/Analysis submitted for/)).toBeVisible({ timeout: 20_000 });
      await expect(page.getByTestId('approval-request')).toContainText('Issue CN Request: #1');
      await expect(page.getByTestId('approval-request')).toContainText('Party insists on a CN');
      await expect.poll(() => gsStatus(gs.id)).toBe('ANALYSIS_COMPLETED');
      expect(dt.errors).toEqual([]);
      await dt.context.close();

      // --- Management -----------------------------------------------------------------------
      const m = await asUser(browser, MGMT, '/management-approval');
      await m.page.setViewportSize({ width: vp.width, height: vp.height });
      const mq = m.page.getByTestId('management-approval-queue');
      const mcard = mq.getByRole('listitem').filter({ hasText: gs.gs_no }).first();
      await expect(mcard).toBeVisible({ timeout: 20_000 });
      await expect(mcard).toContainText(`Issue CN Request · ${String(requested)} pcs`);
      await expectNoHorizontalOverflow(m.page);
      await mcard.getByRole('button').first().click();

      const mp = m.page.getByTestId('management-approval-gs');
      await expect(
        mp.getByRole('heading', { name: `Management Approval · ${gs.gs_no}` }),
      ).toBeVisible({ timeout: 20_000 });
      const first = mp.getByTestId('mgmt-item-1').locator('fieldset').first();
      await expect(first).toContainText(
        `Store requests Issue CN for ${String(requested)} pcs`,
      );
      const approve = mp.getByRole('button', { name: 'Approve' });
      await expect(approve).toBeDisabled();
      await expect(mp).toContainText('on Issue CN Request still to decide');
      await expectNoHorizontalOverflow(m.page);
      await m.page.screenshot({ path: `test-results/dec74/${vp.name}-mgmt.png`, fullPage: true });

      const grant = first.getByRole('button', { name: `Issue CN ${String(requested)} pcs` });
      expect((await grant.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
      await grant.click();
      await expect(first).toContainText(/(\d+) of \1 decided/);
      await mp.getByRole('button', { name: 'Save changes' }).click();
      await expect(mp.getByText(/Changes saved/)).toBeVisible({ timeout: 20_000 });
      await expect(approve).toBeEnabled();
      await approve.click();
      const mdialog = m.page.getByRole('dialog');
      await expect(mdialog.getByText('Approve this goods slip?')).toBeVisible();
      await mdialog.getByRole('button', { name: 'Approve' }).click();
      await expect(mp.getByTestId('stamp-text')).toContainText('Digitally approved by Management', {
        timeout: 20_000,
      });
      await expect.poll(() => gsStatus(gs.id)).toBe('ACCOUNTS_PENDING');
      await expectNoHorizontalOverflow(m.page);
      await m.page.screenshot({ path: `test-results/dec74/${vp.name}-approved.png`, fullPage: true });
      expect(m.errors).toEqual([]);
      await m.context.close();
    });
  }
});
