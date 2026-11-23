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
 * Phase P11 (docs/RMS_PHASE_PROMPTS_20-11-2026.md; DEC-71) against the REAL local stack, at 360 px
 * and 1280 px. Setup through the API: one locked Replacement GS with a DT (DMT) line of 3; the DT
 * store acknowledges, routes everything "Issue to Store", decides "Dispatch New Piece" and submits.
 * With no Management request and no Issue CN the gate passes at once: the GS is "At Accounts" with
 * its Replacement Slip. In the browser, Accounts opens the queue, enters the one Challan of the
 * goods slip (no Credit Note field: no Issue CN), saves, completes (Dispatch Slip generated, GS
 * "Pending Dispatch"), and Dispatch sees the slip in its list. Also the "On hold" tab renders.
 * No console errors, no horizontal scroll, touch targets ≥ 44 px.
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
interface AnalysisView {
  items: Array<{
    gs_item_id: string;
    is_mine: boolean;
    groups: Array<{ condition_field_id: string | null; qty: number }>;
  }>;
}

async function atAccounts(tag: string): Promise<{ id: string; gs_no: string }> {
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
    },
    true,
  );
  await expect.poll(() => gsStatus(gs.id)).toBe('ACCOUNTS_PENDING');
  return gs;
}

test.describe('P11 Accounts per goods slip', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(testInfo.project.name !== 'desktop-chrome', 'Sets 360 / 1280 px widths itself');
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  for (const vp of WIDTHS) {
    test(`Accounts enters the Challan and completes at ${vp.name}`, async ({ browser }) => {
      test.setTimeout(240_000);
      const gs = await atAccounts(`P11${String(vp.width)}`);

      const a = await asUser(browser, USERS.accounts, '/accounts-entry');
      await a.page.setViewportSize({ width: vp.width, height: vp.height });
      await expect(a.page.getByRole('heading', { name: /Accounts Entry/ })).toBeVisible();
      const card = a.page.getByRole('button').filter({ hasText: gs.gs_no }).first();
      await expect(card).toBeVisible({ timeout: 20_000 });
      await expect(card).toContainText('Challan to enter');
      await expectNoHorizontalOverflow(a.page);
      await a.page.screenshot({ path: `test-results/p11/${vp.name}-queue.png`, fullPage: true });

      await a.page.getByRole('button', { name: 'On hold' }).click();
      await expect(
        a.page
          .getByText('Nothing on hold')
          .or(a.page.getByRole('list', { name: 'Goods slips on hold' })),
      ).toBeVisible({ timeout: 20_000 });
      await expectNoHorizontalOverflow(a.page);
      await a.page.getByRole('button', { name: 'To enter' }).click();
      await a.page.getByRole('button').filter({ hasText: gs.gs_no }).first().click();

      await expect(
        a.page.getByRole('heading', { name: `Accounts Entry · ${gs.gs_no}` }),
      ).toBeVisible({ timeout: 20_000 });
      await expect(a.page.getByText('Accounts entry (whole goods slip)')).toBeVisible();
      await expect(a.page.getByLabel('CN No.')).toHaveCount(0); // no Issue CN on this GS
      const print = a.page.getByRole('button', { name: /Print Replacement Slip/ });
      await expect(print).toBeVisible();
      expect((await print.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
      await a.page.getByLabel('Challan No.').fill(`CH-${String(vp.width)}-${String(Date.now())}`);
      await a.page.getByLabel('Challan Date').fill(new Date().toISOString().slice(0, 10));
      const save = a.page.getByRole('button', { name: /^Save/ });
      expect((await save.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
      await expectNoHorizontalOverflow(a.page);
      await a.page.screenshot({ path: `test-results/p11/${vp.name}-entry.png`, fullPage: true });
      await save.click();
      await expect(a.page.getByText('Saved.')).toBeVisible({ timeout: 20_000 });

      await a.page.getByRole('button', { name: /^Complete$/ }).click();
      const dialog = a.page.getByRole('dialog');
      await expect(
        dialog.getByText(/Challan \/ Credit Note and the Replacement Slip/),
      ).toBeVisible();
      await expectNoHorizontalOverflow(a.page);
      await dialog.getByRole('button', { name: /Complete & generate Dispatch Slip/ }).click();
      await expect(a.page.getByText(/Dispatch Slip .* is ready/)).toBeVisible({ timeout: 30_000 });
      await expect.poll(() => gsStatus(gs.id)).toBe('DISPATCH_PENDING');
      await expectNoHorizontalOverflow(a.page);
      await a.page.screenshot({
        path: `test-results/p11/${vp.name}-completed.png`,
        fullPage: true,
      });
      expect(a.errors).toEqual([]);
      await a.context.close();

      // The goods slip is in Dispatch's queue.
      const d = await asUser(browser, USERS.dispatch, '/dispatch-slips');
      await d.page.setViewportSize({ width: vp.width, height: vp.height });
      await expect(d.page.getByText(gs.gs_no).first()).toBeVisible({ timeout: 20_000 });
      await expectNoHorizontalOverflow(d.page);
      await d.page.screenshot({ path: `test-results/p11/${vp.name}-dispatch.png`, fullPage: true });
      expect(d.errors).toEqual([]);
      await d.context.close();
    });
  }
});
