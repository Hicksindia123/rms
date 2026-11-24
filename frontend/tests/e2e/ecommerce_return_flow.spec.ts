import { expect, test } from '@playwright/test';

import { apiAvailable, asUser, expectNoHorizontalOverflow } from './support/stack';

/**
 * DEC-73 against the REAL local stack (API + Supabase Storage), at 360 px (phone) and 1280 px
 * (desktop). The E-Commerce gate user records a return (Ticket Raise) with a package-opening video
 * (real signed upload + confirm) and an image; the Ticket Handler raises the ticket, records a
 * Claim Received response and closes it. A second return goes to the Checking Department and stays
 * open. No console errors, no horizontal scroll.
 */
const GATE = 'ecomgate@rms.local';
const HANDLER = 'tickets@rms.local';
const WIDTHS = [
  { name: 'phone-360', width: 360, height: 780 },
  { name: 'desktop-1280', width: 1280, height: 900 },
];

const fakeFile = (name: string, mimeType: string, kb: number) => ({
  name,
  mimeType,
  buffer: Buffer.alloc(kb * 1024, 7),
});

test.describe('E-Commerce Return gate entry → platform ticket', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(testInfo.project.name !== 'desktop-chrome', 'Sets 360 / 1280 px widths itself');
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  for (const vp of WIDTHS) {
    test(`record, upload, raise, respond, close at ${vp.name}`, async ({ browser }) => {
      test.setTimeout(180_000);
      const orderId = `E2E-${String(vp.width)}-${String(Date.now()).slice(-6)}`;

      // 1. Gate entry (E-Commerce gate user: no offline switch).
      const gate = await asUser(browser, GATE, '/ecom-returns/new');
      await gate.page.setViewportSize({ width: vp.width, height: vp.height });
      await expect(gate.page.getByTestId('ecom-gate-entry')).toBeVisible();
      await expect(gate.page.getByTestId('return-type-OFFLINE_RETURN')).toHaveCount(0);
      await expect(gate.page.locator('#ecom-video')).not.toHaveAttribute('capture', /.*/);
      await expectNoHorizontalOverflow(gate.page);

      await gate.page.getByLabel(/Platform/).selectOption({ label: 'Amazon' });
      await gate.page.getByLabel(/Order ID/).fill(orderId);
      await gate.page.getByLabel('Company Product').check();
      await gate.page.getByRole('textbox', { name: 'Product' }).fill('a');
      await gate.page.getByRole('listbox').getByRole('option').first().click();
      await gate.page.getByLabel(/^Qty/).fill('2');
      await gate.page.getByLabel('Ticket Raise').check();
      await gate.page.locator('#ecom-video').setInputFiles(fakeFile('open.mp4', 'video/mp4', 300));
      await gate.page.locator('#ecom-images').setInputFiles(fakeFile('box.jpg', 'image/jpeg', 50));
      await expectNoHorizontalOverflow(gate.page);
      await gate.page.getByTestId('ecom-record').click();

      const success = gate.page.getByTestId('ecom-success');
      await expect(success).toBeVisible({ timeout: 60_000 });
      await expect(success).toContainText('Ticket Pending');
      const returnNo = (await success.locator('p').first().innerText()).trim();
      expect(returnNo).toMatch(/^ECR\//);
      await expectNoHorizontalOverflow(gate.page);

      // 2. A second return goes to the Checking Department and stays open.
      await gate.page.getByRole('button', { name: 'Record another' }).click();
      await gate.page.getByLabel(/Platform/).selectOption({ label: 'Flipkart' });
      await gate.page.getByLabel(/Order ID/).fill(`${orderId}-B`);
      await gate.page.getByLabel('Different Product').check();
      await gate.page.getByLabel(/Different Product Description/).fill('Empty box with a brick');
      await gate.page.getByLabel('Issue to Checking Department').check();
      await gate.page.locator('#ecom-video').setInputFiles(fakeFile('open2.mov', 'video/quicktime', 200));
      await gate.page.getByTestId('ecom-record').click();
      await expect(gate.page.getByTestId('ecom-success')).toContainText('In Checking', {
        timeout: 60_000,
      });

      // 3. Ticket Handler: queue with SLA, raise, respond (claim), close.
      const handler = await asUser(browser, HANDLER, '/ecom-tickets');
      await handler.page.setViewportSize({ width: vp.width, height: vp.height });
      const card = handler.page.getByTestId(`ticket-${returnNo}`);
      await expect(card).toBeVisible();
      await expect(card.getByTestId('sla-on-time')).toBeVisible();
      await expectNoHorizontalOverflow(handler.page);
      await card.getByTestId('ticket-raise').click();
      await expect(card).toContainText('Ticket Raised');
      await expect(card.getByTestId('ticket-close')).toBeDisabled();
      await card.getByTestId('ticket-respond').click();
      const dialog = handler.page.getByRole('dialog');
      await dialog.getByLabel('Claim Received').check();
      await dialog.getByLabel(/Claim amount/).fill('1499.50');
      await handler.page.getByTestId('ticket-response-save').click();
      await expect(card).toContainText('Claim Received');
      await card.getByTestId('ticket-close').click();
      await expect(card).toHaveCount(0);

      // 4. Detail page: closed, history, video viewable.
      await handler.page.goto(`/#/ecom-returns`);
      await handler.page.getByRole('button', { name: new RegExp(returnNo) }).click();
      const detail = handler.page.getByTestId('ecom-return-detail');
      await expect(detail).toContainText('Closed');
      await expect(detail).toContainText('Claim ₹1499.50');
      await expect(detail).toContainText('ticket closed');
      await expectNoHorizontalOverflow(handler.page);

      expect(gate.errors, 'gate console errors').toEqual([]);
      expect(handler.errors, 'ticket handler console errors').toEqual([]);
      await gate.context.close();
      await handler.context.close();
    });
  }
});
