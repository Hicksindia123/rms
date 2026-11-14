import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

import {
  api,
  apiAvailable,
  asUser,
  expectNoHorizontalOverflow,
  GATE_PROJECTS,
  USERS,
  type Device,
} from './support/stack';

/**
 * P4-01 · Role dashboards against the REAL local stack (no mocks), on desktop Chrome and Pixel 7.
 *
 * Every demo user lands on their role dashboard, every widget loads (no error card), the phone
 * layout never scrolls horizontally, each widget's "Open" link reaches its list screen, a widget
 * number equals the total of the filtered list it links to, the admin layout editor previews and
 * saves, and My Work is grouped by step. No console errors anywhere.
 *
 * Needs: `supabase start`, demo users (backend/scripts/seed_demo_users.py), the bootstrap Super
 * Admin, the API on :8000.
 */

interface DashboardBody {
  role: { code: string } | null;
  widgets: Array<{ code: string; title: string }>;
}

const ROLE_USERS: Array<[string, string]> = [
  ['admin', USERS.admin],
  ['gate', USERS.gate],
  ['aman', USERS.aman],
  ['rm', USERS.rm],
  ['sahil', USERS.sahil],
  ['tech', USERS.tech],
  ['spt', USERS.spt],
  ['spm', USERS.spm],
  ['accounts', USERS.accounts],
  ['dispatch', USERS.dispatch],
  ['mainstore', USERS.mainstore],
];

const devices: Device[] = [];

test.beforeEach(async ({ browserName }, testInfo) => {
  testInfo.annotations.push({ type: 'browser', description: browserName });
  test.skip(!GATE_PROJECTS.includes(testInfo.project.name), 'desktop + Pixel 7 only');
  const reason = await apiAvailable();
  test.skip(reason !== null, reason ?? '');
});

test.afterEach(async () => {
  for (const d of devices.splice(0)) {
    expect(d.errors, 'no console errors').toEqual([]);
    await d.context.close();
  }
});

async function widgetsLoaded(page: Page, expected: number): Promise<void> {
  const cards = page.locator('section.dash-card');
  await expect(cards).toHaveCount(expected, { timeout: 20_000 });
  // Every card finishes loading (no skeleton) and none shows an error.
  await expect(page.locator('.dash-skeleton')).toHaveCount(0, { timeout: 30_000 });
  await expect(page.getByText('Could not load this widget')).toHaveCount(0);
}

for (const [label, email] of ROLE_USERS) {
  test(`${label} lands on a role dashboard with every widget loaded`, async ({ browser }) => {
    const body = await api<DashboardBody>(email, 'GET', '/dashboard');
    expect(body.role, `${label} has a role`).not.toBeNull();
    expect(body.widgets.length, `${label} has widgets`).toBeGreaterThan(0);

    const d = await asUser(browser, email, '/');
    devices.push(d);
    const { page } = d;
    await page.evaluate(() => {
      window.localStorage.removeItem('rms.dashboard.role');
    });
    await expect(page.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeVisible();
    await widgetsLoaded(page, body.widgets.length);
    for (const w of body.widgets) {
      await expect(page.getByTestId(`widget-${w.code}`)).toBeVisible();
    }
    await expectNoHorizontalOverflow(page);

    if (test.info().project.name === 'mobile-pixel-7') {
      // Phones stack the actionable widgets first.
      const first = await page.locator('section.dash-card').first().getAttribute('data-testid');
      const firstCode = (first ?? '').replace('widget-', '');
      const insightOnly = ['GS_PIPELINE', 'GS_TREND', 'CN_ISSUED', 'BATTERY_STOCK'];
      if (body.widgets.some((w) => !insightOnly.includes(w.code)) && firstCode) {
        expect(insightOnly).not.toContain(firstCode);
      }
    }
    await page.screenshot({
      path: `test-results/p4-01/${test.info().project.name}-${label}-dashboard.png`,
      fullPage: true,
    });
  });
}

test('every widget Open link reaches its list screen', async ({ browser }) => {
  const body = await api<DashboardBody>(USERS.rm, 'GET', '/dashboard');
  const d = await asUser(browser, USERS.rm, '/dashboard');
  devices.push(d);
  const { page } = d;
  await widgetsLoaded(page, body.widgets.length);
  test.setTimeout(120_000);
  for (const w of body.widgets) {
    await page.goto('/#/dashboard');
    await page
      .getByTestId(`widget-${w.code}`)
      .getByRole('link', { name: `Open ${w.title}` })
      .click();
    await expect(page).not.toHaveURL(/#\/dashboard$/);
    await expect(page.getByRole('main').getByRole('heading', { level: 1 }).first()).toBeVisible();
    await expect(page.getByText('Something went wrong')).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
  }
});

test('a pipeline number equals the total of the filtered list it opens', async ({ browser }) => {
  test.setTimeout(90_000);
  const pipeline = await api<{
    data: { by_status: Array<{ status: string; count: number }> };
  }>(USERS.admin, 'GET', '/dashboard/widgets/GS_PIPELINE');
  const row = pipeline.data.by_status.find((s) => s.count > 0);
  test.skip(!row, 'no open goods slips in the local data');
  if (!row) return;
  // Other workers create goods slips concurrently and aggregate widgets are cached for up to
  // `dashboard_cache_seconds` (30 s): the widget equals the list total within that window.
  // (Exact parity in one transaction is proven by backend tests/integration/test_dashboards.py.)
  await expect
    .poll(
      async () => {
        const [w, list] = await Promise.all([
          api<{ data: { by_status: Array<{ status: string; count: number }> } }>(
            USERS.admin,
            'GET',
            '/dashboard/widgets/GS_PIPELINE',
          ),
          api<{ total: number }>(USERS.admin, 'GET', `/gs?status=${row.status}&page_size=1`),
        ]);
        return (w.data.by_status.find((s) => s.status === row.status)?.count ?? 0) - list.total;
      },
      { timeout: 45_000, intervals: [2_000] },
    )
    .toBe(0);

  const d = await asUser(browser, USERS.admin, '/dashboard');
  devices.push(d);
  const { page } = d;
  const card = page.getByTestId('widget-GS_PIPELINE');
  await expect(card).toBeVisible({ timeout: 20_000 });
  await card.locator(`a[href="#/gs?status=${row.status}"]`).click();
  await expect(page).toHaveURL(new RegExp(`#/gs\\?status=${row.status}$`));
  await expect(page.getByRole('group', { name: 'Active filters' })).toBeVisible();
  await page.getByRole('button', { name: /Clear filters/ }).click();
  await expect(page).toHaveURL(/#\/gs$/);
});

test('multi-role users switch dashboards', async ({ browser }) => {
  const d = await asUser(browser, USERS.aman, '/dashboard');
  devices.push(d);
  const { page } = d;
  const select = page.getByLabel('View as');
  await expect(select).toBeVisible({ timeout: 20_000 });
  await select.selectOption('TECHNICIAN_COORDINATOR');
  await expect(page.getByText('Technician Coordinator ·')).toBeVisible();
  await expect(page.getByTestId('widget-TECHNICIAN_WIP')).toBeVisible();
  await select.selectOption('INWARD_VERIFIER');
  await expect(page.getByTestId('widget-EVIDENCE_PENDING')).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test('admin reorders a role layout with preview and saves it', async ({ browser }) => {
  const before = await api<{ widgets: Array<{ code: string; size: string }> }>(
    USERS.admin,
    'GET',
    '/admin/dashboard-layouts/TECHNICIAN',
  );
  const d = await asUser(browser, USERS.admin, '/dashboard-config');
  devices.push(d);
  const { page } = d;
  try {
    await expect(page.getByRole('heading', { level: 1, name: 'Dashboard layouts' })).toBeVisible();
    await page.getByLabel('Role', { exact: true }).selectOption('TECHNICIAN');
    await expect(page.getByTestId('layout-item-MY_TASKS')).toBeVisible();
    await page.getByRole('button', { name: 'Move Technician WIP up' }).click();
    await expect(page.locator('.dash-editor__list li').first()).toContainText('Technician WIP');
    await page.getByRole('button', { name: 'Phone', exact: true }).click();
    await expectNoHorizontalOverflow(page);
    await page.getByLabel('Reason for the change (optional)').fill('E2E reorder');
    await page.getByRole('button', { name: 'Save layout' }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Saved the' })).toBeVisible();
    const saved = await api<{ widgets: Array<{ code: string }> }>(
      USERS.admin,
      'GET',
      '/admin/dashboard-layouts/TECHNICIAN',
    );
    expect(saved.widgets.map((w) => w.code)).toEqual(['TECHNICIAN_WIP', 'MY_TASKS']);
  } finally {
    await api(USERS.admin, 'PUT', '/admin/dashboard-layouts/TECHNICIAN', {
      widgets: before.widgets.map((w) => ({ code: w.code, size: w.size })),
      reason: 'E2E restore',
    });
  }
});

test('My Work groups tasks by step with quick actions', async ({ browser }) => {
  const inbox = await api<{ total: number; items: Array<{ step_code: string }> }>(
    USERS.aman,
    'GET',
    '/tasks/mine?status=OPEN&page_size=100',
  );
  const d = await asUser(browser, USERS.aman, '/mywork');
  devices.push(d);
  const { page } = d;
  await expect(page.getByRole('heading', { level: 1, name: 'My Work' })).toBeVisible();
  if (inbox.total === 0) {
    await expect(page.getByText('No open tasks')).toBeVisible();
    return;
  }
  const steps = new Set(inbox.items.map((t) => t.step_code));
  await expect(page.locator('.mywork-group')).toHaveCount(steps.size);
  await expect(page.getByTestId('task-card')).toHaveCount(inbox.items.length);
  await expectNoHorizontalOverflow(page);
  await page
    .getByTestId('task-card')
    .first()
    .getByRole('button', { name: /^Open / })
    .click();
  await expect(page).toHaveURL(/#\/(gs|approvals|credit-notes)/);
});

test('dashboard, layout editor and My Work have no serious accessibility violations', async ({
  browser,
}) => {
  test.setTimeout(90_000);
  for (const [email, path] of [
    [USERS.admin, '/dashboard'],
    [USERS.accounts, '/dashboard'],
    [USERS.admin, '/dashboard-config'],
    [USERS.aman, '/mywork'],
  ] as const) {
    const d = await asUser(browser, email, path);
    devices.push(d);
    await expect(d.page.locator('.dash-skeleton')).toHaveCount(0, { timeout: 30_000 });
    await expect(d.page.getByRole('status').filter({ hasText: /Loading/ })).toHaveCount(0, {
      timeout: 30_000,
    });
    const results = await new AxeBuilder({ page: d.page })
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();
    const serious = results.violations.filter(
      (v) => v.impact === 'serious' || v.impact === 'critical',
    );
    expect(serious.map((v) => `${path}: ${v.id}`)).toEqual([]);
  }
});
