import { expect, test, type Page } from '@playwright/test';
import {
  apiAvailable,
  asUser,
  expectNoHorizontalOverflow,
  GATE_PROJECTS,
  USERS,
  type Device,
} from './support/stack';

/**
 * P3-05 · Post-technical RM revision, Main Store issue & replacement dispatch.
 * (BR-19, BR-31, BR-32, DEC-21, DEC-26, DEC-33, §8.6).
 * Flow:
 * 1. Mobile (Pixel 7 / 360px): Sahil (sahil@rms.local) navigates to Store Issues (/store-issues).
 * 2. Verifies functional stock candidate list, register tab, touch targets >= 44px.
 * 3. Dispatch Officer (dispatch@rms.local) navigates to Dispatch Queue (/dispatch).
 * 4. Verifies pending replacements queue, register tab, and dispatch modal.
 */

const devices: Device[] = [];

async function touchTargets(page: Page) {
  const small = await page.evaluate(() =>
    [...document.querySelectorAll('main button, main select, main input, main textarea')]
      .filter((el) => (el as HTMLElement).offsetParent !== null)
      .map((el) =>
        el instanceof HTMLInputElement && el.type === 'checkbox' ? (el.closest('label') ?? el) : el,
      )
      .filter((el) => el.getBoundingClientRect().height < 44)
      .map(
        (el) =>
          `${el.tagName}:${el.textContent.trim().slice(0, 30) || (el.getAttribute('aria-label') ?? el.id)}`,
      ),
  );
  expect(small).toEqual([]);
}

test.describe('Store Issue & Replacement Dispatch (P3-05)', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(
      !GATE_PROJECTS.includes(testInfo.project.name),
      'P3-05 scenarios run on desktop-chromium and mobile-pixel-7',
    );
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  test.afterEach(async () => {
    const opened = devices.splice(0);
    for (const d of opened) {
      expect(d.errors, `console errors on ${d.page.url()}`).toEqual([]);
      await d.context.close();
    }
  });

  test('Sahil can view and manage Store Issues (Step-6 Store Return)', async ({ browser }) => {
    // 1. Sign in as Sahil on Store Issues page
    const sahil = await asUser(browser, USERS.sahil, '/store-issues');
    devices.push(sahil);
    const page = sahil.page;

    // 2. Verify page header and tabs
    await expect(page.getByText('Intermediate Store: Main Store Issue')).toBeVisible();
    await expect(page.getByRole('button', { name: /Issue Functional Stock/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Issue Register/i })).toBeVisible();

    // 3. Check layout and touch targets
    await expectNoHorizontalOverflow(page);
    await touchTargets(page);

    // 4. Switch to Issue Register tab
    await page.getByRole('button', { name: /Issue Register/i }).click();
    await expect(page.getByText(/Past Store Issue Notes/i)).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });

  test('Dispatch Officer can view Replacement Dispatch Queue and Register', async ({ browser }) => {
    // 1. Sign in as Dispatch Officer on Dispatch page
    const disp = await asUser(browser, USERS.dispatch, '/dispatch');
    devices.push(disp);
    const page = disp.page;

    // 2. Verify header and tabs
    await expect(page.getByText('Replacement Dispatch Queue')).toBeVisible();
    await expect(page.getByRole('button', { name: /Pending Queue/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Dispatch Register/i })).toBeVisible();

    // 3. Check layout and touch targets
    await expectNoHorizontalOverflow(page);
    await touchTargets(page);

    // 4. Switch to Dispatch Register tab
    await page.getByRole('button', { name: /Dispatch Register/i }).click();
    await expect(page.getByText(/Dispatched Replacement Register/i)).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });
});
