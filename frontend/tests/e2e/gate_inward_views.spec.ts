import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

/**
 * P2-02 · GS screens at desktop and phone widths against the REAL local stack:
 * list (table vs cards), detail (Overview / Timeline), new-GS form, and Aman's My Work (S1_UNBOX).
 * Checks no horizontal overflow and no console errors; saves screenshots to test-results/p2-02.
 * Skipped with the reason when the API is not reachable.
 */
const API = process.env.RMS_E2E_API ?? 'http://localhost:8000';
const PASSWORD = process.env.RMS_DEMO_PASSWORD ?? 'Demo@123456';
const WIDTHS = [
  { label: 'desktop', width: 1280, height: 900 },
  { label: 'phone', width: 360, height: 780 },
];

async function apiAvailable(): Promise<string | null> {
  try {
    const res = await fetch(`${API}/api/v1/health`);
    return res.ok ? null : `API health returned ${String(res.status)}`;
  } catch (err) {
    return `API not reachable at ${API}: ${String(err)}`;
  }
}

async function signIn(page: Page, email: string) {
  await page.goto('/#/login');
  await page.getByLabel('Email Address').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('main').getByRole('button', { name: 'Sign In', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
}

async function axeClean(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();
  const serious = results.violations.filter(
    (v) => v.impact === 'serious' || v.impact === 'critical',
  );
  expect(serious.map((v) => v.id)).toEqual([]);
}

async function noOverflow(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);
}

test.describe('GS screens responsive (P2-02)', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(
      testInfo.project.name !== 'desktop-chrome' && testInfo.project.name !== 'desktop-chromium',
      'Viewports are set explicitly',
    );
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  for (const vp of WIDTHS) {
    test(`gate user screens at ${vp.label}`, async ({ page }) => {
      const errors: string[] = [];
      page.on('console', (m) => {
        if (m.type() === 'error') errors.push(m.text());
      });
      page.on('pageerror', (e) => errors.push(e.message));
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await signIn(page, 'anuj@rms.local');

      await page.goto('/#/gs');
      await expect(page.getByRole('heading', { name: 'Goods Slips' })).toBeVisible();
      const firstGs = page.getByRole('button', { name: /^Open GS\// }).filter({ visible: true });
      await expect(firstGs.first()).toBeVisible();
      await noOverflow(page);
      await axeClean(page);
      await page.screenshot({ path: `test-results/p2-02/${vp.label}-gs-list.png`, fullPage: true });

      await firstGs.first().click();
      await expect(page.getByRole('tab', { name: 'Overview' })).toBeVisible();
      await noOverflow(page);
      await axeClean(page);
      await page.screenshot({
        path: `test-results/p2-02/${vp.label}-gs-detail.png`,
        fullPage: true,
      });
      await page.getByRole('tab', { name: 'Timeline' }).click();
      await expect(page.getByText(/Created → Gate created/)).toBeVisible();
      await page.screenshot({
        path: `test-results/p2-02/${vp.label}-gs-timeline.png`,
        fullPage: true,
      });

      await page.goto('/#/gs/new');
      await expect(page.getByRole('button', { name: 'Submit & Create GS' })).toBeVisible();
      // Gate v4 (DEC-62, Q5): Transport = transport name only, no vehicle number.
      await page.locator('#field-delivery_mode').selectOption('DIRECT_TRUCK');
      await expect(page.locator('#field-vehicle_no')).toHaveCount(0);
      await expect(page.locator('#field-transporter_name')).toBeVisible();
      await page.locator('#field-delivery_mode').selectOption('SELF_PARTY_REP');
      await expect(page.locator('#field-rep_contact')).toBeVisible();
      // UI-side conditional validation (the backend rejection is proven by pytest / curl).
      await page.locator('#field-rep_contact').fill('12345');
      await page.getByRole('button', { name: 'Submit & Create GS' }).click();
      await expect(page.getByText('Contact Name is required')).toBeVisible();
      await noOverflow(page);
      await axeClean(page);
      await page.screenshot({ path: `test-results/p2-02/${vp.label}-gs-new.png`, fullPage: true });

      expect(errors).toEqual([]);
    });

    test(`inward verifier My Work at ${vp.label}`, async ({ page }) => {
      const errors: string[] = [];
      page.on('console', (m) => {
        if (m.type() === 'error') errors.push(m.text());
      });
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await signIn(page, 'aman@rms.local');
      await page.goto('/#/mywork');
      const cards = page.getByTestId('task-card');
      // Aman performs S1_UNBOX and, after unboxing (P2-03), S1_ITEMIZE: either task may be first.
      await expect(
        cards
          .filter({ hasText: /Step-2 (Unboxing|Carton Opening)|Step-3 (Itemisation|Counting)/ })
          .first(),
      ).toBeVisible();
      await noOverflow(page);
      await axeClean(page);
      await page.screenshot({
        path: `test-results/p2-02/${vp.label}-aman-mywork.png`,
        fullPage: true,
      });
      // Aman cannot create a GS: the nav entry is not rendered.
      await expect(page.getByRole('button', { name: 'New Goods Slip' })).toHaveCount(0);
      expect(errors).toEqual([]);
    });
  }
});
