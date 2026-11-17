import { expect, test, type Page } from '@playwright/test';

/**
 * P2-02 · Gate inward on a phone (Pixel 7) against the REAL local stack (no API mocks):
 * Anuj signs in → creates a GS → confirmation → print-tag preview with one label per box.
 *
 * Needs: `supabase start`, demo users (backend/scripts/seed_demo_users.py) and the API on :8000.
 * Skipped with the reason when the API is not reachable.
 */
const API = process.env.RMS_E2E_API ?? 'http://localhost:8000';
const GATE_USER = {
  email: 'anuj@rms.local',
  password: process.env.RMS_DEMO_PASSWORD ?? 'Demo@123456',
};

async function apiAvailable(): Promise<string | null> {
  try {
    const res = await fetch(`${API}/api/v1/health`);
    return res.ok ? null : `API health returned ${String(res.status)}`;
  } catch (err) {
    return `API not reachable at ${API}: ${String(err)}`;
  }
}

async function signIn(page: Page) {
  await page.goto('/#/login');
  await page.getByLabel('Email Address').fill(GATE_USER.email);
  await page.getByLabel('Password').fill(GATE_USER.password);
  await page.getByRole('main').getByRole('button', { name: 'Sign In', exact: true }).click();
  await expect(page.getByRole('button', { name: 'New Goods Slip' })).toBeVisible();
}

test.describe('Gate inward (P2-02)', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    if (testInfo.project.name !== 'mobile-pixel-7') {
      test.skip(true, 'Gate inward E2E runs on the Pixel 7 viewport');
    }
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  test('create GS on a phone, then preview the carton tags', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });
    page.on('pageerror', (err) => consoleErrors.push(err.message));

    await signIn(page);
    await page.getByRole('button', { name: 'New Goods Slip' }).click();
    await expect(page.getByRole('heading', { name: 'New Goods Slip' })).toBeVisible();

    // Form v2 (AMD-01/02/06): Return Type → Gate Entry → State → Station → Distributor.
    await page.getByTestId('return-type-OFFLINE_RETURN').click();
    await page.locator('#field-gate_entry_date').fill(new Date().toISOString().slice(0, 10));
    await page.locator('#field-gate_entry_no').fill(String(Date.now()).slice(-9));
    await page.locator('#field-state').selectOption({ label: 'Uttar Pradesh' });
    await page.locator('#field-station').selectOption({ label: 'Agra' });
    await page.locator('#field-party_name input').fill('Demo Party One');
    await page.getByRole('option', { name: /Demo Party One/ }).click();

    await page.locator('#field-carton_count').fill('3');
    await page.locator('#field-delivery_mode').selectOption('COURIER_PARCEL');
    await page.locator('#field-courier_name').fill('DTDC');
    await page.locator('#field-docket_no').fill(`E2E-${String(Date.now())}`);

    // "No Document Attached" (BR-03 / DEC-03) replaces the document rows; DEC-52: no extra
    // acknowledgement checkbox.
    await page.getByLabel('No Document Attached').check();
    await expect(page.getByLabel('Missing documentation warning acknowledged')).toHaveCount(0);

    // The sticky submit bar stays reachable without horizontal scroll at phone width.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(overflow).toBe(false);

    await page.getByRole('button', { name: 'Create Goods Slip' }).click();
    const gsNo = page.getByTestId('created-gs-no');
    await expect(gsNo).toHaveText(/^\S+\/\d{4}-\d{2}\/\d{5}$|^\S+$/);
    const createdNo = (await gsNo.textContent())?.trim() ?? '';
    expect(createdNo.length).toBeGreaterThan(0);
    await expect(page.getByRole('alert').filter({ hasText: 'No Document Attached' })).toBeVisible();

    await page.getByRole('button', { name: /Print tag \(3 cartons\)/ }).click();
    const sheet = page.getByTestId('tag-sheet');
    await expect(sheet.locator('article')).toHaveCount(3);
    await expect(sheet).toContainText('Carton 1 of 3'); // AMD-03
    await expect(sheet).toContainText('Carton 3 of 3');
    await expect(sheet).toContainText(createdNo);
    await expect(sheet.locator('img').first()).toHaveAttribute('src', /^data:image\/png/);

    await page.getByLabel(/Label printer/).check();
    await expect(sheet).toHaveClass(/tag-sheet--label/);
    await page.screenshot({ path: 'test-results/p2-02/pixel7-tag-preview.png', fullPage: true });

    expect(consoleErrors).toEqual([]);
  });
});
