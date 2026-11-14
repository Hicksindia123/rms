import { readFileSync } from 'node:fs';

import { expect, test } from '@playwright/test';

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
 * P4-02 · Reports & MIS against the REAL local stack (no mocks), desktop Chrome + Pixel 7.
 *
 * Catalogue is permission-filtered; a report runs, filters (desktop bar / phone drawer), sorts,
 * shows totals equal to the API, exports CSV and Excel (real downloads), and opens the A4-landscape
 * print preview. No console errors, no horizontal scroll on phones.
 */

interface Group {
  code: string;
  reports: Array<{ code: string; title: string }>;
}
interface Data {
  total: number;
  totals: Record<string, number | null>;
}

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

function isPhone(): boolean {
  return test.info().project.name.startsWith('mobile');
}

test('catalogue lists exactly the reports the API allows', async ({ browser }) => {
  for (const email of [USERS.admin, USERS.accounts]) {
    const groups = await api<Group[]>(email, 'GET', '/reports');
    const d = await asUser(browser, email, '/reports');
    devices.push(d);
    await expect(d.page.getByRole('heading', { name: 'Reports & MIS' })).toBeVisible();
    const codes = groups.flatMap((g) => g.reports.map((r) => r.code));
    await expect(d.page.locator('.report-tile')).toHaveCount(codes.length);
    for (const code of codes)
      await expect(d.page.locator('.report-tile', { hasText: code })).toHaveCount(1);
    await expectNoHorizontalOverflow(d.page);
  }
  // Accounts sees the commercial reports but not inventory reconciliation.
  const accounts = (await api<Group[]>(USERS.accounts, 'GET', '/reports')).flatMap((g) =>
    g.reports.map((r) => r.code),
  );
  expect(accounts).toContain('R-16');
  expect(accounts).not.toContain('R-14');
});

test('run, filter, sort and see totals that match the API', async ({ browser }) => {
  const admin = USERS.admin;
  const all = await api<Data>(admin, 'GET', '/reports/R-03/data?page_size=1');
  const closed = await api<Data>(admin, 'GET', '/reports/R-03/data?page_size=1&status=CLOSED');

  const d = await asUser(browser, USERS.admin, '/reports');
  devices.push(d);
  const { page } = d;
  await page.locator('.report-tile', { hasText: 'R-03' }).click();
  await expect(page.getByRole('heading', { name: 'GS register' })).toBeVisible();
  await expect(page.locator('.report-viewer__meta')).toContainText(
    `${all.total.toLocaleString('en-IN')} row`,
  );

  // Filter by status (phone: inside the Filters drawer).
  if (isPhone()) await page.getByRole('button', { name: /^Filters/ }).click();
  await page.getByLabel('Status').selectOption('CLOSED');
  await page.getByRole('button', { name: 'Apply filters' }).click();
  await expect(page).toHaveURL(/status=CLOSED/);
  await expect(page.locator('.report-viewer__meta')).toContainText(
    `${closed.total.toLocaleString('en-IN')} row`,
  );
  const received = String(closed.totals.received_qty ?? 0);
  if (isPhone()) {
    await expect(page.locator('.dataview__totals-card')).toContainText(received);
    await expect(page.locator('.dataview__card').first()).toBeVisible();
  } else {
    await expect(page.locator('tr.dataview__totals')).toContainText(received);
    // Server-side sort by clicking a header.
    await page.getByRole('button', { name: /^Received qty/ }).click();
    await expect(page).toHaveURL(/sort=received_qty/);
    await expect(page.locator('th[aria-sort="descending"]')).toContainText('Received qty');
  }
  // Drill-down link opens the goods slip.
  const link = page.locator('a.report-link').first();
  await expect(link).toHaveAttribute('href', /^#\/gs\//);
  await expectNoHorizontalOverflow(page);
});

test('export CSV and Excel downloads', async ({ browser }) => {
  const d = await asUser(browser, USERS.admin, '/reports/R-16');
  devices.push(d);
  const { page } = d;
  await expect(page.getByRole('heading', { name: 'Credit note register' })).toBeVisible();
  await expect(page.locator('.report-viewer__meta')).toContainText('row');

  const [csv] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'CSV' }).click(),
  ]);
  expect(csv.suggestedFilename()).toMatch(/^R-16-.*\.csv$/);
  const text = readFileSync(await csv.path(), 'utf-8').replace(String.fromCharCode(0xfeff), '');
  expect(text.split(/\r?\n/)[0]).toContain('CN / JV No.');

  const [xlsx] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Excel' }).click(),
  ]);
  expect(xlsx.suggestedFilename()).toMatch(/^R-16-.*\.xlsx$/);
  const bytes = readFileSync(await xlsx.path());
  expect(bytes.subarray(0, 2).toString()).toBe('PK'); // a zip container (Office Open XML)
});

test('column chooser changes the visible columns', async ({ browser }) => {
  test.skip(isPhone(), 'table headers are desktop-only');
  const d = await asUser(browser, USERS.admin, '/reports/R-08');
  devices.push(d);
  const { page } = d;
  await expect(page.getByRole('heading', { name: 'Pendency register & ageing' })).toBeVisible();
  await page.getByRole('button', { name: 'Columns', exact: true }).click();
  await page.getByLabel('Opened by').check();
  await page.getByRole('button', { name: 'Apply', exact: true }).click();
  await expect(page.locator('thead')).toContainText('Opened by');
});

test('print preview renders the A4-landscape layout', async ({ browser }) => {
  const d = await asUser(browser, USERS.admin, '/reports/R-07');
  devices.push(d);
  const { page } = d;
  await expect(
    page.getByRole('heading', { name: 'Daily container audit compliance' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Print', exact: true }).click();
  await expect(page).toHaveURL(/#\/reports\/R-07\/print/);
  const sheet = page.locator('article.report-print');
  await expect(sheet).toBeVisible();
  await expect(sheet.locator('.report-print__title')).toContainText('R-07');
  await expect(sheet).toContainText('Generated by');
  await expect(sheet.locator('.report-print__filters')).toContainText('Audit date from');
  await expect(sheet.locator('tbody tr')).toHaveCount(30); // default 30-day window, one row per day

  await page.emulateMedia({ media: 'print' });
  await expect(page.locator('.report-print__toolbar')).toBeHidden();
  await expect(page.locator('header.no-print').first()).toBeHidden();
  const pageRule = await sheet.evaluate((el) => getComputedStyle(el).getPropertyValue('page'));
  expect(pageRule.trim()).toBe('report-landscape');
  if (!isPhone()) {
    const pdf = await page.pdf({ preferCSSPageSize: true });
    expect(pdf.length).toBeGreaterThan(1000);
  }
  await page.emulateMedia({ media: 'screen' });
  await expectNoHorizontalOverflow(page);
});
