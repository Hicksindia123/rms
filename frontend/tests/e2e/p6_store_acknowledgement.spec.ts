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
 * Phase P6 (docs/RMS_PHASE_PROMPTS_20-11-2026.md; DEC-66, Q12, Q13) against the REAL local stack,
 * at 360 px and 1280 px. Setup through the API: one locked Replacement GS with a DT (DMT) line and
 * an OP (Enclosed Oval) line; the RM generates → one DT slip and one OP slip. The DT store user
 * opens "Acknowledge Transfer Slips" (only the DT slip is listed), checks the per-condition summary
 * and the hidden other-store items, and acknowledges with a remark. The OP store user reports a
 * discrepancy (the slip stays open), then acknowledges → the GS is STORE_ACKNOWLEDGED.
 * No console errors, no horizontal scroll, touch targets ≥ 44 px.
 */
const DT_STORE = 'dtstore@rms.local';
const OP_STORE = 'opstore@rms.local';
const WIDTHS = [
  { name: 'phone-360', width: 360, height: 780 },
  { name: 'desktop-1280', width: 1280, height: 900 },
];

interface Slip {
  id: string;
  slip_no: string;
  store: { code: string };
}

test.describe('P6 store acknowledgement', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(testInfo.project.name !== 'desktop-chrome', 'Sets 360 / 1280 px widths itself');
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  for (const vp of WIDTHS) {
    test(`store users acknowledge their slips and report a discrepancy at ${vp.name}`, async ({
      browser,
    }) => {
      test.setTimeout(240_000);
      const dmt = await productOf('DMT');
      const eo = await productOf('ENCLOSED_OVAL');
      const gs = await lockedGs(`P6${String(vp.width)}`, [
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
      const opSlip = gen.slips.find((s) => s.store.code === 'OP');
      if (!dtSlip || !opSlip) throw new Error('expected a DT and an OP slip');

      // DT store: the list shows its slip only.
      const dt = await asUser(browser, DT_STORE, '/transfer-slips/acknowledge');
      await dt.page.setViewportSize({ width: vp.width, height: vp.height });
      await expect(
        dt.page.getByRole('heading', { name: 'Acknowledge Transfer Slips' }),
      ).toBeVisible();
      const list = dt.page.getByTestId('slip-list');
      await expect(list.getByText(dtSlip.slip_no)).toBeVisible({ timeout: 20_000 });
      await expect(list.getByText(opSlip.slip_no)).toHaveCount(0);
      await expectNoHorizontalOverflow(dt.page);
      await dt.page.screenshot({ path: `test-results/p6/${vp.name}-list.png`, fullPage: true });

      await list.getByText(dtSlip.slip_no).click();
      const detail = dt.page.getByTestId('transfer-slip-detail');
      await expect(detail.getByLabel(`${gs.gs_no} by condition`)).toBeVisible();
      await expect(dt.page.getByTestId('slip-relevant-qty')).toHaveText('3');
      await expect(detail.locator('li.line-through')).toHaveCount(0);
      await detail.getByLabel(/Show other items of these goods slips/).check();
      await expect(detail.locator('li.line-through')).toHaveCount(1);
      const ack = dt.page.getByRole('button', { name: /Acknowledge receipt/ });
      expect((await ack.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
      await expectNoHorizontalOverflow(dt.page);
      await ack.click();
      const dialog = dt.page.getByRole('dialog');
      await expect(dialog).toContainText('3 pc');
      await dialog.getByLabel(/Remark/).fill('All 3 received in good order');
      await dt.page.screenshot({ path: `test-results/p6/${vp.name}-confirm.png`, fullPage: true });
      await dialog.getByRole('button', { name: 'Confirm receipt' }).click();
      await expect(dt.page.getByText(/acknowledged\. The goods are now in/)).toBeVisible({
        timeout: 20_000,
      });
      await expect(detail.getByText(/Acknowledged by/)).toBeVisible();
      await expect(dt.page.getByTestId('slip-ack-panel')).toHaveCount(0);
      // One of two slips: the GS is still on transfer slips.
      expect(await gsStatus(gs.id)).toBe('TRANSFER_SLIP_GENERATED');
      await expectNoHorizontalOverflow(dt.page);
      await dt.page.screenshot({
        path: `test-results/p6/${vp.name}-acknowledged.png`,
        fullPage: true,
      });
      expect(dt.errors).toEqual([]);
      await dt.context.close();

      // OP store: report a discrepancy (remark only), then acknowledge.
      const op = await asUser(browser, OP_STORE, `/transfer-slips/${opSlip.id}`);
      await op.page.setViewportSize({ width: vp.width, height: vp.height });
      await op.page.getByRole('button', { name: /Report discrepancy/ }).click();
      const report = op.page.getByRole('dialog');
      await expect(report.getByRole('button', { name: 'Send report' })).toBeDisabled();
      await report.getByLabel(/What is wrong/).fill('Outer carton was damaged');
      await report.getByRole('button', { name: 'Send report' }).click();
      await expect(op.page.getByText('Outer carton was damaged')).toBeVisible({ timeout: 20_000 });
      await expect(op.page.getByTestId('slip-ack-panel')).toBeVisible();
      await expectNoHorizontalOverflow(op.page);
      await op.page.getByRole('button', { name: /Acknowledge receipt/ }).click();
      await op.page.getByRole('dialog').getByRole('button', { name: 'Confirm receipt' }).click();
      await expect(op.page.getByText(/acknowledged\. The goods are now in/)).toBeVisible({
        timeout: 20_000,
      });
      await expect.poll(() => gsStatus(gs.id)).toBe('STORE_ACKNOWLEDGED');
      await op.page.screenshot({ path: `test-results/p6/${vp.name}-op.png`, fullPage: true });
      expect(op.errors).toEqual([]);
      await op.context.close();
    });
  }
});
