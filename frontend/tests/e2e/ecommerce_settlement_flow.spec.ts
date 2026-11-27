import { expect, test, type Page } from '@playwright/test';

import { apiAvailable, asUser, expectNoHorizontalOverflow } from './support/stack';

/**
 * DEC-76 against the REAL local stack (API + Supabase Storage), at 360 px (phone) and 1280 px
 * (desktop): the whole E-Commerce return settlement.
 *
 *  1. Gate (ECOM_GATE): order A (our product, qty 2, Ticket Raise) and order B (a different product,
 *     qty 1, no ticket), both Amazon.
 *  2. E-Commerce Executive (TICKET_HANDLER): raises A's ticket, follows it up, records the claim and
 *     closes it with "Refund 2"; Portal Check of B: "Free Replacement 1".
 *  3. Unboxing (INWARD_VERIFIER): Amazon tab, A → 1 store + 1 repair (Repackaging), B → wastage;
 *     creates the action sheet (platform printed, Qty Received 3, Qty Issue CN 2); records the
 *     repaired piece back.
 *  4. Store user of the product's store: acknowledges both pieces of A.
 *  5. E-Commerce Accounts (ECOM_ACCOUNTS): issues the credit note; A and B are CLOSED.
 * No console errors, no horizontal scroll at either width.
 */
const GATE = 'ecomgate@rms.local';
const EXEC = 'tickets@rms.local';
const UNBOXER = 'aman@rms.local';
const ACCOUNTS = 'ecomaccounts@rms.local';
const STORE_USERS: Record<string, string> = {
  'Intermediate Store OP': 'opstore@rms.local',
  'Intermediate Store DT': 'dtstore@rms.local',
  'Intermediate Store RI': 'ristore@rms.local',
};
const WIDTHS = [
  { name: 'phone-360', width: 360, height: 780 },
  { name: 'desktop-1280', width: 1280, height: 900 },
];

const fakeFile = (name: string, mimeType: string, kb: number) => ({
  name,
  mimeType,
  buffer: Buffer.alloc(kb * 1024, 7),
});

async function recordReturn(
  page: Page,
  opts: { orderId: string; ours: boolean; qty: number; ticket: boolean },
): Promise<string> {
  await page.getByLabel(/Platform/).selectOption({ label: 'Amazon' });
  await page.getByLabel(/Order ID/).fill(opts.orderId);
  if (opts.ours) {
    await page.getByLabel('Our Product').check();
    await page.getByRole('textbox', { name: 'Product' }).fill('a');
    await page.getByRole('listbox').getByRole('option').first().click();
  } else {
    await page.getByLabel('Different Product').check();
    await page.getByLabel(/Different Product Name/).fill('Empty box with a brick');
  }
  await page.getByLabel(/^Qty/).fill(String(opts.qty));
  await page.getByLabel(opts.ticket ? 'Ticket Raise' : 'Issue to Checking Department').check();
  await page.locator('#ecom-video').setInputFiles(fakeFile('open.mp4', 'video/mp4', 200));
  await page.getByTestId('ecom-record').click();
  const success = page.getByTestId('ecom-success');
  await expect(success).toBeVisible({ timeout: 60_000 });
  const returnNo = (await success.locator('p').first().innerText()).trim();
  expect(returnNo).toMatch(/^ECR\//);
  return returnNo;
}

test.describe('E-Commerce settlement: executive → unboxing → store → accounts', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(testInfo.project.name !== 'desktop-chrome', 'Sets 360 / 1280 px widths itself');
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  for (const vp of WIDTHS) {
    test(`full settlement at ${vp.name}`, async ({ browser }) => {
      test.setTimeout(300_000);
      const stamp = `${String(vp.width)}-${String(Date.now()).slice(-6)}`;
      const orderA = `S76A-${stamp}`;
      const orderB = `S76B-${stamp}`;
      const size = async (p: Page) => {
        await p.setViewportSize({ width: vp.width, height: vp.height });
      };

      // 1. Gate entry.
      const gate = await asUser(browser, GATE, '/ecom-returns/new');
      await size(gate.page);
      const returnA = await recordReturn(gate.page, {
        orderId: orderA,
        ours: true,
        qty: 2,
        ticket: true,
      });
      await gate.page.getByRole('button', { name: 'Record another' }).click();
      const returnB = await recordReturn(gate.page, {
        orderId: orderB,
        ours: false,
        qty: 1,
        ticket: false,
      });
      await expect(gate.page.getByTestId('ecom-success')).toContainText('Portal Check Pending');

      // 2. E-Commerce Executive: ticket of A (raise, follow-up, claim, close with Refund 2).
      const exec = await asUser(browser, EXEC, '/ecom-tickets');
      await size(exec.page);
      const card = exec.page.getByTestId(`ticket-${returnA}`);
      await expect(card).toBeVisible();
      await card.getByTestId('ticket-raise').click();
      await expect(card).toContainText('Ticket Raised');
      await card.getByTestId('ticket-follow-up').click();
      await exec.page
        .getByRole('dialog')
        .getByLabel(/What happened/)
        .fill('Asked for an update');
      await exec.page.getByTestId('follow-up-save').click();
      await expect(card.getByTestId('ticket-follow-ups')).toContainText('1 follow-up');
      await card.getByTestId('ticket-respond').click();
      let dialog = exec.page.getByRole('dialog');
      await dialog.getByLabel('Claim Received').check();
      await dialog.getByLabel(/Claim amount/).fill('350');
      await exec.page.getByTestId('ticket-response-save').click();
      await expect(card).toContainText('Claim Received');
      await card.getByTestId('ticket-close').click();
      dialog = exec.page.getByRole('dialog');
      await dialog.getByLabel('Refund').check();
      await dialog.getByLabel(/^Qty/).fill('2');
      await dialog.getByLabel('Short note').fill('Refund shown on portal');
      await expectNoHorizontalOverflow(exec.page);
      await exec.page.getByTestId('resolution-save').click();
      await expect(card).toHaveCount(0);

      // Portal check of B: Free Replacement 1.
      await exec.page.goto('/#/ecom-portal-check');
      const portal = exec.page.getByTestId(`portal-${returnB}`);
      await expect(portal).toBeVisible();
      await expectNoHorizontalOverflow(exec.page);
      await portal.getByTestId('portal-check-record').click();
      await exec.page.getByRole('dialog').getByLabel('Free Replacement').check();
      await exec.page.getByTestId('resolution-save').click();
      await expect(portal).toHaveCount(0);

      // 3. Unboxing: only this run's two Amazon orders.
      const unbox = await asUser(browser, UNBOXER, '/ecom-unboxing');
      await size(unbox.page);
      await expect(unbox.page.getByTestId('ecom-unboxing')).toBeVisible();
      await unbox.page.getByTestId('unbox-platform-AMAZON').click();
      const cardA = unbox.page.getByTestId(`unbox-${returnA}`);
      const cardB = unbox.page.getByTestId(`unbox-${returnB}`);
      await expect(cardA).toBeVisible();
      await expect(cardA).toContainText('Qty Issue CN 2');
      await expect(cardB).toContainText('Not our product');
      for (const other of await unbox.page.locator('[data-testid^="unbox-ECR"]').all()) {
        const id = await other.getAttribute('data-testid');
        if (id !== `unbox-${returnA}` && id !== `unbox-${returnB}`) {
          await other.getByRole('checkbox').uncheck();
        }
      }
      const storeName = ((await cardA.getByText(/^Store: /).innerText()) || '')
        .replace('Store: ', '')
        .trim();
      expect(Object.keys(STORE_USERS)).toContain(storeName);
      await cardA.getByTestId('unbox-good').getByRole('spinbutton').fill('1');
      await cardA.getByTestId('unbox-repair').getByRole('spinbutton').fill('1');
      await cardA
        .getByLabel('Repair department')
        .selectOption({ label: 'Department: Repackaging' });
      await expectNoHorizontalOverflow(unbox.page);
      await unbox.page.getByTestId('unbox-submit').click();

      const sheet = unbox.page.getByTestId('ecom-action-sheet');
      await expect(sheet).toBeVisible({ timeout: 30_000 });
      await expect(sheet.getByTestId('sheet-platform')).toHaveText('Amazon');
      await expect(sheet).toContainText(orderA);
      await expect(sheet).toContainText(orderB);
      await expect(sheet).toContainText('Pending with Accounts');
      await expect(sheet).toContainText('Qty Issue CN 2');
      await expectNoHorizontalOverflow(unbox.page);
      const sheetUrl = unbox.page.url();
      const sheetId = sheetUrl.split('/ecom-action-sheets/')[1] ?? '';
      expect(sheetId).not.toBe('');

      // The repaired piece comes back from the department.
      await unbox.page.goto('/#/ecom-unboxing');
      const repairRow = unbox.page.getByTestId(`repair-${returnA}`);
      await expect(repairRow).toBeVisible();
      await repairRow.getByTestId('repair-record').click();
      await unbox.page.getByTestId('repair-save').click();
      await expect(repairRow).toHaveCount(0);

      // 4. The product's store acknowledges the good and the repaired piece.
      const storeUser = STORE_USERS[storeName] ?? '';
      const store = await asUser(browser, storeUser, '/ecom-store-receipts');
      await size(store.page);
      const receipts = store.page.getByTestId(`receipt-${returnA}`);
      await expect(receipts).toHaveCount(2);
      await expectNoHorizontalOverflow(store.page);
      for (const r of await receipts.all()) await r.getByRole('checkbox').check();
      await store.page.getByTestId('receipts-acknowledge').click();
      await expect(store.page.getByRole('status')).toContainText('2 receipt(s) acknowledged.');
      await expect(receipts).toHaveCount(0);

      // 5. E-Commerce Accounts issues the credit note.
      const acc = await asUser(browser, ACCOUNTS, `/ecom-action-sheets/${sheetId}`);
      await size(acc.page);
      const accSheet = acc.page.getByTestId('ecom-action-sheet');
      await expect(accSheet.getByTestId('sheet-platform')).toHaveText('Amazon');
      await expectNoHorizontalOverflow(acc.page);
      await acc.page.getByLabel(/CN No/).fill(`CN-${stamp}`);
      await acc.page.getByLabel(/CN Value/).fill('700');
      await acc.page.getByTestId('sheet-complete').click();
      await expect(accSheet.getByTestId('sheet-cn')).toContainText(`CN-${stamp}`);
      await expect(accSheet).toContainText('Completed');

      // Both returns are closed; the detail shows the settlement.
      await acc.page.goto('/#/ecom-returns');
      await acc.page.getByRole('button', { name: new RegExp(returnA) }).click();
      const detail = acc.page.getByTestId('ecom-return-detail');
      await expect(detail).toContainText('Closed');
      await expect(detail.getByTestId('ecom-settlement')).toContainText('Qty Issue CN 2');
      await expect(detail.getByTestId('ecom-settlement')).toContainText('received');
      await expectNoHorizontalOverflow(acc.page);

      for (const [who, s] of [
        ['gate', gate],
        ['executive', exec],
        ['unboxing', unbox],
        ['store', store],
        ['accounts', acc],
      ] as const) {
        expect(s.errors, `${who} console errors`).toEqual([]);
        await s.context.close();
      }
    });
  }
});
