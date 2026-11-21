import { expect, test } from '@playwright/test';

import { apiAvailable, asUser, expectNoHorizontalOverflow, gsStatus, USERS } from './support/stack';
import { lockedGs, productOf } from './support/transfer_slips';

/**
 * Phase P5 (docs/RMS_PHASE_PROMPTS_20-11-2026.md; DEC-65) against the REAL local stack, at 360 px
 * and 1280 px. Setup through the API: two locked Replacement GSs, one with a DT (DMT) line and an
 * OP (Enclosed Oval) line, one with a DT line only, plus a third GS. The Replacement Manager selects
 * the first two (multi-select) and generates → one slip per store (DT covers both GSs), opens a
 * slip (relevant + greyed items, totals), downloads the PDF, and sends an Edit Request for the
 * third GS, which Management then sees on the item screen. No console errors, no horizontal scroll.
 */
const MGMT = 'mgmt@rms.local';
const WIDTHS = [
  { name: 'phone-360', width: 360, height: 780 },
  { name: 'desktop-1280', width: 1280, height: 900 },
];

test.describe('P5 transfer slips (RM)', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(testInfo.project.name !== 'desktop-chrome', 'Sets 360 / 1280 px widths itself');
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  for (const vp of WIDTHS) {
    test(`RM multi-selects, generates per store, views the slip, requests an edit at ${vp.name}`, async ({
      browser,
    }) => {
      test.setTimeout(240_000);
      const dmt = await productOf('DMT');
      const eo = await productOf('ENCLOSED_OVAL');
      const w = String(vp.width);
      const a = await lockedGs(`P5A${w}`, [
        [dmt, 3],
        [eo, 2],
      ]);
      const b = await lockedGs(`P5B${w}`, [[dmt, 4]]);
      const c = await lockedGs(`P5C${w}`, [[eo, 1]]);

      const rm = await asUser(browser, USERS.rm, '/transfer-slips');
      await rm.page.setViewportSize({ width: vp.width, height: vp.height });
      await expect(rm.page.getByRole('heading', { name: 'Transfer Slips' })).toBeVisible();
      await expect(rm.page.getByText(a.gs_no)).toBeVisible();
      await expectNoHorizontalOverflow(rm.page);

      // Read-only items of a GS.
      const cardA = rm.page.getByTestId('pending-gs').filter({ hasText: a.gs_no });
      await cardA.getByRole('button', { name: 'View items' }).click();
      await expect(cardA.getByTestId('pending-gs-items')).toBeVisible();

      // Multi-select A + B, then generate: DT covers both, OP only A.
      await rm.page.getByLabel(`Select ${a.gs_no}`).check();
      await rm.page.getByLabel(`Select ${b.gs_no}`).check();
      await expect(rm.page.getByText('2 goods slip(s) selected')).toBeVisible();
      const generate = rm.page.getByRole('button', { name: /Generate Transfer Slip/ });
      expect((await generate.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
      await generate.click();
      const confirm = rm.page.getByRole('dialog');
      await expect(confirm).toContainText('2 GS · 7 pc');
      await expect(confirm).toContainText('1 GS · 2 pc');
      await expectNoHorizontalOverflow(rm.page);
      await rm.page.screenshot({ path: `test-results/p5/${vp.name}-confirm.png`, fullPage: true });
      await confirm.getByRole('button', { name: 'Generate 2 slip(s)' }).click();
      const result = rm.page.getByTestId('generated-slips');
      await expect(result).toContainText('TRF/DT/', { timeout: 20_000 });
      await expect(result).toContainText('TRF/OP/');
      await expect.poll(() => gsStatus(a.id)).toBe('TRANSFER_SLIP_GENERATED');
      await expect.poll(() => gsStatus(b.id)).toBe('TRANSFER_SLIP_GENERATED');

      // Open the DT slip: items of this store per GS, greyed OP item of GS A, totals.
      await result
        .locator('li')
        .filter({ hasText: 'TRF/DT/' })
        .getByRole('button', { name: /View/ })
        .click();
      const detail = rm.page.getByTestId('transfer-slip-detail');
      await expect(detail).toBeVisible();
      await expect(rm.page.getByTestId('slip-relevant-qty')).toHaveText('7');
      await expect(rm.page.getByTestId('slip-grand-total')).toHaveText('9');
      await expect(detail.getByText(`Subtotal ${a.gs_no}`)).toBeVisible();
      // DEC-66 (P6): the other stores' items sit behind a toggle.
      await detail.getByLabel(/Show other items of these goods slips/).check();
      await expect(detail.locator('li.line-through')).toHaveCount(1);
      await expectNoHorizontalOverflow(rm.page);
      const download = rm.page.waitForEvent('download');
      await rm.page.getByRole('button', { name: /Download PDF/ }).click();
      expect((await download).suggestedFilename()).toMatch(/^TRF-DT-.*\.pdf$/);
      await rm.page.screenshot({ path: `test-results/p5/${vp.name}-slip.png`, fullPage: true });

      // Edit request for GS C (reason required) → the GS cannot be selected any more.
      await detail.getByRole('button', { name: 'Transfer Slips' }).click();
      const cardC = rm.page.getByTestId('pending-gs').filter({ hasText: c.gs_no });
      await cardC.getByRole('button', { name: /Send Edit Request/ }).click();
      await rm.page.getByLabel('What should be corrected?').fill('Line 1 is a DMT, not an oval');
      await rm.page.getByRole('button', { name: 'Send to Management' }).click();
      await expect(cardC.getByText('Edit requested')).toBeVisible();
      await expect(rm.page.getByLabel(`Select ${c.gs_no}`)).toBeDisabled();
      await expectNoHorizontalOverflow(rm.page);
      expect(rm.errors).toEqual([]);
      await rm.context.close();

      // Management sees the request on the item screen and may resolve it.
      const mg = await asUser(browser, MGMT, `/gs/${c.id}/itemization`);
      await mg.page.setViewportSize({ width: vp.width, height: vp.height });
      await expect(mg.page.getByTestId('open-edit-request')).toContainText('DMT, not an oval');
      await expect(mg.page.getByRole('button', { name: 'Reject request' })).toBeVisible();
      await expectNoHorizontalOverflow(mg.page);
      await mg.page.screenshot({ path: `test-results/p5/${vp.name}-mgmt.png`, fullPage: true });
      expect(mg.errors).toEqual([]);
      await mg.context.close();
    });
  }
});
