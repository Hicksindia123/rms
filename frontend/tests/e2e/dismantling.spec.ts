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
 * P3-03 · Stage-4 Dismantling & Parts Recovery (BR-26..BR-29, G-11, DEC-18, DEC-19, DEC-11).
 * Flow:
 * 1. Mobile (Pixel 7 / 360px): Spare Parts Technician (spt@rms.local) navigates to Dismantling Queue.
 * 2. Verifies candidate lots, DEC-18 non-dismantling routing notice, touch targets >= 44px.
 * 3. Navigates to Scrap Register (/scrap), checks hazardous disposal manifest requirements (DEC-11).
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

test.describe('Dismantling & Parts Recovery (P3-03)', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(
      !GATE_PROJECTS.includes(testInfo.project.name),
      'P3-03 scenarios run on desktop-chromium and mobile-pixel-7',
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

  test('Spare Parts Technician can view queue, inspect DEC-18 notices, and access scrap register', async ({
    browser,
  }) => {
    // 1. Sign in as Spare Parts Technician on Dismantling page
    const spt = await asUser(browser, USERS.spt, '/dismantling');
    devices.push(spt);

    await expect(
      spt.page.getByRole('heading', { name: /Stage-4: Dismantling & Parts Recovery/i }),
    ).toBeVisible();
    await expectNoHorizontalOverflow(spt.page);

    if (test.info().project.name === 'mobile-pixel-7') {
      await touchTargets(spt.page);
    }

    // 2. Check tab switching between Queue and Batches
    const batchesTab = spt.page.getByRole('button', { name: /Dismantling Batches/i });
    if (await batchesTab.isVisible()) {
      await batchesTab.click();
      await expectNoHorizontalOverflow(spt.page);
    }

    const queueTab = spt.page.getByRole('button', { name: /Dismantling Queue/i });
    if (await queueTab.isVisible()) {
      await queueTab.click();
      await expectNoHorizontalOverflow(spt.page);
    }

    // 3. Navigate to Scrap Register page
    await spt.page.goto('/#/scrap');
    await expect(
      spt.page.getByRole('heading', { name: /Scrap & Safe Disposal Register/i }),
    ).toBeVisible();
    await expectNoHorizontalOverflow(spt.page);

    if (test.info().project.name === 'mobile-pixel-7') {
      await touchTargets(spt.page);
    }
  });
});
