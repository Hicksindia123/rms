import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join, resolve } from 'node:path';

import { expect, test } from '@playwright/test';

import {
  apiAvailable,
  asUser,
  expectNoHorizontalOverflow,
  GATE_PROJECTS,
  USERS,
  type Device,
} from './support/stack';

/**
 * P3-07 · Party notification, GS closure engine & Complete Sales Return closure
 * (BR-38, BR-39, G-15, DEC-25).
 *
 * Fixtures (`backend/scripts/verify_p3_07.py`, local only): an RO GS and an approved CSR GS whose
 * stock, CN and dispatch work is complete. Accounts records the prior party notification in the
 * UI, then closes the GS from the closure checklist; the incomplete GS shows its failures.
 */

interface Fixture {
  gs_id: string;
  gs_no: string;
}

function createFixtures(): Record<'ro' | 'csr' | 'incomplete', Fixture> {
  const backend = resolve(process.cwd(), '..', 'backend');
  const python = existsSync(join(backend, '.venv', 'Scripts', 'python.exe'))
    ? join(backend, '.venv', 'Scripts', 'python.exe')
    : join(backend, '.venv', 'bin', 'python');
  const out = execFileSync(python, ['scripts/verify_p3_07.py'], { cwd: backend, stdio: 'pipe' });
  return JSON.parse(out.toString().trim().split('\n').pop() ?? '{}') as Record<
    'ro' | 'csr' | 'incomplete',
    Fixture
  >;
}

const devices: Device[] = [];

test.describe('GS closure (P3-07)', () => {
  // Each scenario first creates its fixtures with the backend script (a few seconds per run).
  test.describe.configure({ timeout: 120_000 });

  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(
      !GATE_PROJECTS.includes(testInfo.project.name),
      'P3-07 scenarios run on desktop-chromium and mobile-pixel-7',
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

  for (const kind of ['ro', 'csr'] as const) {
    test(`Accounts notifies the party and closes a ${kind.toUpperCase()} GS`, async ({
      browser,
    }) => {
      const fx = createFixtures();
      const gs = fx[kind];
      const deepak = await asUser(browser, USERS.accounts, `/gs/${gs.gs_id}/party-notification`);
      devices.push(deepak);
      const page = deepak.page;

      await expect(page.getByRole('heading', { name: new RegExp(gs.gs_no) })).toBeVisible({
        timeout: 15000,
      });
      await expect(page.getByLabel('Message')).toHaveValue(/dated \d{2}-\d{2}-\d{4}/);
      await expect(page.getByLabel('Recipient')).not.toHaveValue('');
      await expectNoHorizontalOverflow(page);
      await page.getByRole('button', { name: /record notification/i }).click();
      await expect(page.getByText(/^Recorded for /)).toBeVisible();

      await page.goto(`/#/gs/${gs.gs_id}`);
      await page.getByRole('tab', { name: /closure/i }).click();
      const closeBtn = page.getByRole('button', { name: /^close gs$/i });
      await expect(closeBtn).toBeEnabled({ timeout: 15000 });
      await expectNoHorizontalOverflow(page);
      await closeBtn.click();
      await page
        .getByRole('dialog')
        .getByRole('button', { name: /^close gs$/i })
        .click();
      await expect(page.getByRole('heading', { name: 'Closed' })).toBeVisible();
      if (kind === 'csr') {
        await expect(
          page.getByText(/Inward to Inventory with Packaging \+ CN Issued \+ Prior Party Info/),
        ).toBeVisible();
      }
      await page.getByRole('button', { name: /closure certificate/i }).click();
      await expect(page.getByRole('heading', { name: 'Closure certificate' })).toBeVisible();
      await expectNoHorizontalOverflow(page);
    });
  }

  test('an incomplete GS shows the failing checks with fix links', async ({ browser }) => {
    const fx = createFixtures();
    const pratham = await asUser(browser, USERS.rm, `/gs/${fx.incomplete.gs_id}`);
    devices.push(pratham);
    const page = pratham.page;
    await page.getByRole('tab', { name: /closure/i }).click();
    await expect(page.getByTestId('check-DENY_QTY_DISPATCHED')).toHaveAttribute(
      'data-passed',
      'false',
    );
    await expect(page.getByTestId('check-PRIOR_NOTIFICATION')).toHaveAttribute(
      'data-passed',
      'false',
    );
    await expect(page.getByRole('button', { name: /^close gs$/i })).toBeDisabled();
    await expectNoHorizontalOverflow(page);
    // CLAUDE.md rule h: 360px phones, no horizontal scroll, >= 44px fix-link targets.
    await page.setViewportSize({ width: 360, height: 780 });
    await expectNoHorizontalOverflow(page);
    const fix = page.getByTestId('check-PRIOR_NOTIFICATION').getByRole('button');
    expect((await fix.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
    await fix.click();
    await expect(page.getByRole('heading', { name: /notify party/i })).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });
});
