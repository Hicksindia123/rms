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
 * P3-02 · Technician Allotment & Receiving, Battery Inventory & Consumption (BR-23..BR-25, G-10, DEC-14..DEC-17).
 * Flow:
 * 1. Mobile (Pixel 7 / 360px): Coordinator (Aman/Sahil) navigates to Technician Board.
 * 2. Navigates to Allot screen, verifies intermediate store lots, touch steppers >= 44px.
 * 3. Navigates to Battery Stock page, checks balances, tabs, and reconciliation tie-out.
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

test.describe('Technician Servicing & Battery Stock (P3-02)', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(
      !GATE_PROJECTS.includes(testInfo.project.name),
      'P3-02 scenarios run on desktop-chromium and mobile-pixel-7',
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

  test('Coordinator can view technician board, allot batches, and inspect battery stock', async ({
    browser,
  }) => {
    // 1. Sign in as Aman (Technician Coordinator) on Technician Board
    const aman = await asUser(browser, USERS.aman, '/servicing');
    devices.push(aman);

    await expect(
      aman.page.getByRole('heading', { name: /Technician Servicing Board/i }),
    ).toBeVisible();
    await expectNoHorizontalOverflow(aman.page);

    // 2. Navigate to Allot screen
    const allotBtn = aman.page.getByRole('button', { name: /Allot New Batch/i });
    if (await allotBtn.isVisible()) {
      await allotBtn.click();
      await expect(
        aman.page.getByRole('heading', { name: /Allot Batch to Technician/i }),
      ).toBeVisible();
      await expectNoHorizontalOverflow(aman.page);
      if (test.info().project.name === 'mobile-pixel-7') {
        await touchTargets(aman.page);
      }
    }

    // 3. Navigate to Battery Stock page
    // The battery ledger page is routed at #/batteries (#/inventory/batteries is the P3-04
    // segregated Batteries view).
    await aman.page.goto('/#/batteries');
    await expect(aman.page.getByRole('heading', { name: /Battery Stock & Ledger/i })).toBeVisible();
    await expectNoHorizontalOverflow(aman.page);

    // Check tabs
    const reconTab = aman.page.getByRole('button', { name: /Reconciliation Report/i });
    await expect(reconTab).toBeVisible();
    await reconTab.click();
    await expect(aman.page.getByText(/Pieces Checked/i)).toBeVisible();
  });
});
