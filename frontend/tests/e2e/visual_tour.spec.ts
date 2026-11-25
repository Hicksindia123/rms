import { expect, test } from '@playwright/test';

import { apiAvailable, asUser, expectNoHorizontalOverflow, USERS } from './support/stack';

/**
 * Portal-wide visual tour (portal refresh 2026-11-25) against the REAL local stack: the sign-in
 * page and the main screens of several roles at 360 px and 1280 px. Each screen must render
 * without console errors and without horizontal scroll; screenshots go to test-results/tour for
 * review.
 */
const WIDTHS = [
  { name: 'phone-360', width: 360, height: 780 },
  { name: 'desktop-1280', width: 1280, height: 900 },
];

const TOUR: Array<{ user: string; paths: string[] }> = [
  { user: USERS.admin, paths: ['/mywork', '/gs', '/dashboard', '/reports', '/settings', '/users'] },
  { user: USERS.gate, paths: ['/mywork', '/gs/new'] },
  { user: 'dtstore@rms.local', paths: ['/store-analysis'] },
  { user: 'mgmt@rms.local', paths: ['/management-approval'] },
  { user: USERS.accounts, paths: ['/accounts-entry'] },
];

test.describe('Portal visual tour', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(testInfo.project.name !== 'desktop-chrome', 'Sets 360 / 1280 px widths itself');
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  for (const vp of WIDTHS) {
    test(`sign-in page at ${vp.name}`, async ({ browser }) => {
      const { baseURL } = test.info().project.use;
      const context = await browser.newContext({
        ...(baseURL ? { baseURL } : {}),
        viewport: { width: vp.width, height: vp.height },
      });
      const page = await context.newPage();
      const errors: string[] = [];
      page.on('console', (m) => {
        if (m.type() === 'error') errors.push(m.text());
      });
      await page.goto('/#/login');
      await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
      await expect(page.getByText(/Development only/)).toHaveCount(0);
      await expectNoHorizontalOverflow(page);
      await page.screenshot({ path: `test-results/tour/${vp.name}-login.png`, fullPage: true });
      expect(errors).toEqual([]);
      await context.close();
    });

    for (const stop of TOUR) {
      test(`${stop.user} screens at ${vp.name}`, async ({ browser }) => {
        test.setTimeout(180_000);
        const d = await asUser(browser, stop.user, stop.paths[0] ?? '/mywork');
        await d.page.setViewportSize({ width: vp.width, height: vp.height });
        const failed: string[] = [];
        d.page.on('response', (r) => {
          if (r.status() >= 400) failed.push(`${String(r.status())} ${r.url()}`);
        });
        for (const path of stop.paths) {
          await d.page.goto(`/#${path}`);
          await expect(d.page.locator('main')).toBeVisible();
          await d.page.waitForLoadState('networkidle');
          await expect(d.page.getByText(/Loading/)).toHaveCount(0, { timeout: 20_000 });
          await expectNoHorizontalOverflow(d.page);
          const name = `${vp.name}-${stop.user.split('@')[0] ?? 'user'}${path.replace(/\W+/g, '-')}`;
          await d.page.screenshot({ path: `test-results/tour/${name}.png`, fullPage: true });
        }
        expect(failed, 'failed requests').toEqual([]);
        expect(d.errors).toEqual([]);
        await d.context.close();
      });
    }
  }
});
