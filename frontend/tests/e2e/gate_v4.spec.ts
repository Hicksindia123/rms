import { expect, test, type Page } from '@playwright/test';

import {
  api,
  apiAvailable,
  asUser,
  expectNoHorizontalOverflow,
  FIXTURES,
  USERS,
} from './support/stack';

/**
 * Phase P2 / DEC-62 · gate form S1_GATE_INWARD v4 against the REAL local stack (no API mocks), at
 * 1280 px and 360 px: State → Station → Party, Cartons, Received Through (Courier), a party
 * document (Invoice + photo) and a transport document (Courier Slip + photo) → "Submit & Create
 * GS" → summary sheet → Back to edit → Submit → GS number + Print GS Tag. The files go to signed
 * URLs right after the GS is created; the API shows both rows with their source and file.
 *
 * Needs: `supabase start`, `scripts/reset-db.ps1 -SkipBackup`, the API (RMS_E2E_API) and the web
 * app (RMS_E2E_PORT). Runs on the desktop Chrome project and sets each width itself.
 */
const VIEWPORTS = [
  { label: 'desktop-1280', width: 1280, height: 900 },
  { label: 'phone-360', width: 360, height: 780 },
] as const;

interface GsDetail {
  goods_slip: {
    id: string;
    gs_no: string;
    missing_documentation: boolean;
    vehicle_no: string | null;
    documents: Array<{
      doc_type_code: string;
      doc_source: string | null;
      doc_no: string | null;
      files: Array<{ status: string }>;
    }>;
  };
}

function hasAsterisk(page: Page, label: string) {
  return page.locator('label', { hasText: label }).first().locator('[aria-label="required"]');
}

test.describe('Gate form v4 (DEC-62)', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(testInfo.project.name !== 'desktop-chrome', 'Sets 1280 / 360 px widths itself');
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  for (const vp of VIEWPORTS) {
    test(`gate entry → summary → submit at ${vp.label}`, async ({ browser }) => {
      test.setTimeout(120_000);
      const { context, page, errors } = await asUser(browser, USERS.gate, '/gs/new');
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await expect(page.getByRole('button', { name: 'Submit & Create GS' })).toBeVisible();

      // Required marks come from the form config: Received Through yes, transport documents no.
      await expect(hasAsterisk(page, 'Received Through')).toHaveCount(1);
      await expect(hasAsterisk(page, 'Cartons')).toHaveCount(1);
      await expect(hasAsterisk(page, 'Documents From Transport')).toHaveCount(0);

      // Return Type stays (Q24); Offline needs the gate entry (Q23).
      await page.getByTestId('return-type-OFFLINE_RETURN').click();
      await page.locator('#field-gate_entry_date').fill(new Date().toISOString().slice(0, 10));
      const gateEntryNo = `${String(1 + (Date.now() % 9_000_000))}${vp.width === 360 ? '6' : '2'}`;
      await page.locator('#field-gate_entry_no').fill(gateEntryNo);
      await page.locator('#field-state').selectOption({ label: 'Uttar Pradesh' });
      await page.locator('#field-station').selectOption({ label: 'Agra' });
      await page.locator('#field-party_name input').click();
      const firstParty = page.locator('#field-party_name').getByRole('option').first();
      await expect(firstParty).toBeVisible({ timeout: 15_000 });
      const partyName = ((await firstParty.textContent()) ?? '').trim();
      await firstParty.click();
      await page.locator('#field-carton_count').fill('2');

      await page.locator('#field-delivery_mode').selectOption('COURIER_PARCEL');
      await expect(hasAsterisk(page, 'Docket No.')).toHaveCount(1);
      await page.locator('#field-courier_name').fill('DTDC');
      const docket = `V4-${vp.label}-${String(Date.now())}`;
      await page.locator('#field-docket_no').fill(docket);
      // Q5: Transport has no vehicle number on v4.
      await page.locator('#field-delivery_mode').selectOption('DIRECT_TRUCK');
      await expect(page.locator('#field-vehicle_no')).toHaveCount(0);
      await expect(hasAsterisk(page, 'Transport Name')).toHaveCount(1);
      await page.locator('#field-delivery_mode').selectOption('COURIER_PARCEL');
      await page.locator('#field-courier_name').fill('DTDC');
      await page.locator('#field-docket_no').fill(docket);

      // Documents From Party: Invoice + photo; Documents From Transport: Courier Slip + photo.
      await page.getByRole('button', { name: 'Add party document' }).click();
      const party = page.getByTestId('party-documents');
      await party.getByLabel(/Document type/).selectOption('INVOICE');
      await party.getByLabel(/Photo \/ PDF/).setInputFiles({
        name: 'invoice.png',
        mimeType: 'image/png',
        buffer: FIXTURES.PNG,
      });
      await page.getByRole('button', { name: 'Add transport document' }).click();
      const transport = page.getByTestId('transport-documents');
      await transport.getByLabel(/Document type/).selectOption('COURIER_SLIP');
      await transport.getByLabel(/Photo \/ PDF/).setInputFiles({
        name: 'courier-slip.png',
        mimeType: 'image/png',
        buffer: FIXTURES.PNG,
      });
      await expectNoHorizontalOverflow(page);
      await page.screenshot({
        path: `test-results/p2-gate-v4/${vp.label}-form.png`,
        fullPage: true,
      });

      // Summary sheet; nothing is created until Submit.
      await page.getByRole('button', { name: 'Submit & Create GS' }).click();
      const sheet = page.getByRole('dialog', { name: 'Check before creating the GS' });
      const summary = sheet.getByTestId('gate-summary');
      const row = (label: string) =>
        summary
          .locator('.gate-summary__row')
          .filter({ has: page.locator('dt').getByText(label, { exact: true }) })
          .locator('dd');
      // The picker option shows the party name with its code and station.
      const partyShown = ((await row('Party').textContent()) ?? '').trim();
      expect(partyShown).not.toBe('');
      expect(partyName).toContain(partyShown);
      await expect(row('State')).toHaveText('Uttar Pradesh');
      await expect(row('Station')).toHaveText('Agra');
      await expect(row('Cartons')).toHaveText('2');
      await expect(row('Received Through')).toHaveText('Courier');
      await expect(row('Docket No.')).toHaveText(docket);
      await expect(row('Documents From Party')).toHaveText('1 (Invoice)');
      await expect(row('Documents From Transport')).toHaveText('1 (Courier Slip)');
      await expectNoHorizontalOverflow(page);
      await page.screenshot({ path: `test-results/p2-gate-v4/${vp.label}-summary.png` });
      const before = await api<{ total: number }>(USERS.gate, 'GET', `/gs?q=${gateEntryNo}`);
      expect(before.total).toBe(0);

      await sheet.getByRole('button', { name: 'Back to edit' }).click();
      await expect(sheet).toHaveCount(0);
      await expect(page.locator('#field-docket_no')).toHaveValue(docket);

      await page.getByRole('button', { name: 'Submit & Create GS' }).click();
      await sheet.getByRole('button', { name: 'Submit', exact: true }).click();
      const gsNoEl = page.getByTestId('created-gs-no');
      await expect(gsNoEl).toBeVisible({ timeout: 30_000 });
      const gsNo = ((await gsNoEl.textContent()) ?? '').trim();
      expect(gsNo).not.toBe('');
      await expect(page.getByRole('button', { name: /Print GS Tag \(2 cartons\)/ })).toBeVisible();
      await expect(page.getByTestId('gate-upload-failed')).toHaveCount(0);
      await expectNoHorizontalOverflow(page);
      await page.screenshot({
        path: `test-results/p2-gate-v4/${vp.label}-created.png`,
        fullPage: true,
      });

      // The API: one GS, both rows with their source, each with its confirmed file.
      const listed = await api<{ items: Array<{ id: string; gs_no: string }> }>(
        USERS.gate,
        'GET',
        `/gs?q=${gateEntryNo}`,
      );
      expect(listed.items.map((g) => g.gs_no)).toEqual([gsNo]);
      const detail = await api<GsDetail>(USERS.gate, 'GET', `/gs/${listed.items[0]?.id ?? ''}`);
      const gs = detail.goods_slip;
      expect(gs.missing_documentation).toBe(false);
      expect(gs.vehicle_no).toBeNull();
      expect(
        gs.documents.map((d) => [d.doc_type_code, d.doc_source, d.doc_no, d.files.length]),
      ).toEqual([
        ['INVOICE', 'PARTY', null, 1],
        ['COURIER_SLIP', 'TRANSPORT', null, 1],
      ]);
      expect(gs.documents.flatMap((d) => d.files.map((f) => f.status))).toEqual([
        'CONFIRMED',
        'CONFIRMED',
      ]);

      expect(errors).toEqual([]);
      await context.close();
    });
  }
});
