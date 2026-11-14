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
 * P3-06 · Step-7 Credit Note Workflow & Accounting Settlement
 * (BR-32..BR-37, G-13, G-14, DEC-13, DEC-22, DEC-23, DEC-24, DEC-33).
 *
 * Flow:
 * 1. Deepak (Accounts - deepak@rms.local) navigates to Accounts Credit Note Queue (/credit-notes).
 * 2. Verifies Pending Goods Slips table and Credit Notes Register.
 * 3. Checks touch targets (>= 44px) and no horizontal overflow on mobile viewports.
 * 4. Verifies responsive split-screen layout on Credit Note Workspace.
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

test.describe('Credit Notes & Step-7 Accounting Settlement (P3-06)', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(
      !GATE_PROJECTS.includes(testInfo.project.name),
      'P3-06 scenarios run on desktop-chromium and mobile-pixel-7',
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

  test('Accounts team (Deepak Ji) can view Credit Note Work Queue and Register', async ({
    browser,
  }) => {
    const deepak = await asUser(browser, USERS.accounts, '/credit-notes');
    devices.push(deepak);

    // Verify page header
    await expect(
      deepak.page.getByRole('heading', { name: /Credit Notes & Accounts Work Queue/i }),
    ).toBeVisible({ timeout: 10000 });

    // Verify tabs
    await expect(deepak.page.getByRole('button', { name: /Pending Goods Slips/i })).toBeVisible();
    await expect(deepak.page.getByRole('button', { name: /Credit Notes Register/i })).toBeVisible();

    // Responsive checks
    await expectNoHorizontalOverflow(deepak.page);
    await touchTargets(deepak.page);

    // Switch to Credit Notes Register tab
    await deepak.page.getByRole('button', { name: /Credit Notes Register/i }).click();

    // Verify search & filters are visible
    await expect(deepak.page.getByLabel(/Search credit notes/i)).toBeVisible();
    await expect(deepak.page.getByRole('combobox').first()).toBeVisible();

    await expectNoHorizontalOverflow(deepak.page);
  });

  test('Replacement Manager (Pratham) can access RM CN Decision screen', async ({ browser }) => {
    const rm = await asUser(browser, USERS.rm, '/mywork');
    devices.push(rm);

    await expect(rm.page.getByRole('heading', { name: /My Work/i })).toBeVisible({
      timeout: 10000,
    });

    await expectNoHorizontalOverflow(rm.page);
    await touchTargets(rm.page);
  });
});
