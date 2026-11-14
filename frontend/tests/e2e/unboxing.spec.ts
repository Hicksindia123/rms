import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

import { expect, test, type Browser, type Page } from '@playwright/test';

import { gateBody } from './support/stack';

/**
 * P2-03 · Step-2 unboxing on a phone (Pixel 7) against the REAL local stack (no API mocks):
 * Anuj's GS (created through the API) → Aman starts unboxing, uploads a small fixture video and a
 * document photo, classifies it as an Invoice and completes → Deepak (Accounts), signed in on a
 * second device, gets the bell alert through Supabase Realtime and sees the GS in the queue.
 *
 * Needs: `supabase start`, demo users (backend/scripts/seed_demo_users.py) and the API on :8000.
 */
const API = process.env.RMS_E2E_API ?? 'http://localhost:8000';
const PASSWORD = process.env.RMS_DEMO_PASSWORD ?? 'Demo@123456';

function frontendEnv(): Record<string, string> {
  const text = readFileSync(resolve(process.cwd(), '.env.local'), 'utf-8');
  return Object.fromEntries(
    text
      .split(/\r?\n/)
      .filter((l) => l.includes('=') && !l.startsWith('#'))
      .map((l) => [l.slice(0, l.indexOf('=')).trim(), l.slice(l.indexOf('=') + 1).trim()]),
  );
}

async function apiAvailable(): Promise<string | null> {
  try {
    const res = await fetch(`${API}/api/v1/health`);
    return res.ok ? null : `API health returned ${String(res.status)}`;
  } catch (err) {
    return `API not reachable at ${API}: ${String(err)}`;
  }
}

async function accessToken(email: string): Promise<string> {
  const env = frontendEnv();
  const res = await fetch(`${env.VITE_SUPABASE_URL ?? ''}/auth/v1/token?grant_type=password`, {
    method: 'POST',
    headers: { apikey: env.VITE_SUPABASE_ANON_KEY ?? '', 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password: PASSWORD }),
  });
  if (!res.ok) throw new Error(`sign-in failed for ${email}: ${String(res.status)}`);
  return ((await res.json()) as { access_token: string }).access_token;
}

/** Step-1 precondition through the real API (P2-02), as the gate user. */
async function createGs(doc = 'INVOICE'): Promise<{ id: string; gs_no: string }> {
  const token = await accessToken('anuj@rms.local');
  const auth = { Authorization: `Bearer ${token}` };
  const parties = (await (
    await fetch(`${API}/api/v1/gs/lookups/parties?q=Demo`, { headers: auth })
  ).json()) as Array<{ id: string }>;
  const res = await fetch(`${API}/api/v1/gs`, {
    method: 'POST',
    headers: {
      ...auth,
      'Content-Type': 'application/json',
      'Idempotency-Key': `e2e-${crypto.randomUUID()}`,
    },
    body: JSON.stringify({
      // Gate form v2 (AMD-01..AMD-04): see support/stack.ts gateBody().
      ...gateBody(parties[0]?.id, 'U', doc === 'NO_DOCUMENT' ? 'NO_DOCUMENT' : 'INVOICE'),
    }),
  });
  if (res.status !== 201) throw new Error(`GS create failed: ${await res.text()}`);
  return ((await res.json()) as { goods_slip: { id: string; gs_no: string } }).goods_slip;
}

async function signIn(page: Page, email: string) {
  await page.goto('/#/login');
  await page.getByLabel('Email Address').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('main').getByRole('button', { name: 'Sign In', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
}

function trackConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  page.on('pageerror', (err) => errors.push(err.message));
  return errors;
}

async function accountsDevice(browser: Browser) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const errors = trackConsole(page);
  await signIn(page, 'deepak@rms.local');
  await page.goto('/#/accounts');
  await expect(page.getByRole('heading', { name: 'Accounts Document Queue' })).toBeVisible();
  // Realtime channel joined (data-live) before the alert is produced.
  await expect(page.getByTestId('notification-bell')).toHaveAttribute('data-live', 'true');
  return { context, page, errors };
}

// 1×1 PNG: a stand-in document photo; a few KB of bytes: a stand-in mp4 (Storage stores bytes).
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
  'base64',
);
const VIDEO = Buffer.alloc(64 * 1024, 7);

test.describe('Unboxing evidence (P2-03)', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    if (testInfo.project.name !== 'mobile-pixel-7') {
      test.skip(true, 'Unboxing E2E runs on the Pixel 7 viewport');
    }
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  test('upload video + photo, classify, complete; Accounts alerted in real time', async ({
    page,
    browser,
  }) => {
    test.setTimeout(120_000);
    const gs = await createGs();
    // Deterministic baseline: clear Deepak's unread count first (other specs also alert Accounts).
    const deepak = await accessToken('deepak@rms.local');
    const cleared = await fetch(`${API}/api/v1/notifications/read-all`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${deepak}` },
    });
    if (!cleared.ok) throw new Error(`read-all failed: ${String(cleared.status)}`);
    // (No zero-count assertion: parallel specs may alert Accounts at any moment.)
    const accounts = await accountsDevice(browser);

    const errors = trackConsole(page);
    await signIn(page, 'aman@rms.local');
    await page.goto(`/#/gs/${gs.id}/unboxing`);
    await expect(page.getByRole('heading', { name: gs.gs_no })).toBeVisible();
    await page.getByRole('button', { name: 'Start carton opening' }).click();

    const checklist = page.getByTestId('checklist');
    await expect(checklist).toContainText('Video ✖');
    await expect(page.getByRole('button', { name: 'Complete carton opening' })).toBeDisabled();

    // Video (signed upload, then server-side confirmation).
    await page.getByTestId('video-file-input').setInputFiles({
      name: 'unboxing.mp4',
      mimeType: 'video/mp4',
      buffer: VIDEO,
    });
    await expect(checklist).toContainText('Video ✔', { timeout: 30_000 });
    await expect(page.getByTestId('evidence-video')).toHaveCount(1);

    // Document photo → classify as Invoice (conditional fields per DD r12).
    await page.getByTestId('doc-photo-file-input').setInputFiles({
      name: 'invoice.png',
      mimeType: 'image/png',
      buffer: PNG,
    });
    const card = page.getByTestId('doc-photo-card');
    await expect(card).toHaveCount(1, { timeout: 30_000 });
    await expect(card.locator('.thumb img')).toBeVisible(); // thumbnail via signed URL
    await expect(checklist).toContainText('Classified ✖');
    await card.getByRole('button', { name: 'Classify' }).click();
    await page.locator('#field-doc_classification').selectOption('INVOICE');
    await page.locator('#field-invoice_no').fill('INV-E2E-1');
    await page.locator('#field-invoice_date').fill('2026-11-01');
    await page.locator('#field-buyer_gstin').fill('09AAACH7409R1ZZ');
    await page.locator('#field-seller_gstin').fill('07AAACB1234C1Z5');
    await page.locator('#field-items_verified').check();
    await page.getByRole('button', { name: 'Save classification' }).click();
    await expect(checklist).toContainText('Classified ✔');
    await expect(card).toContainText('Invoice');

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(overflow).toBe(false);
    await page.screenshot({ path: 'test-results/p2-03/pixel7-unboxing-ready.png', fullPage: true });

    await page.getByRole('button', { name: 'Complete carton opening' }).click();
    await expect(page.getByTestId('unboxing-complete')).toContainText('itemization');

    // Accounts: the bell count rises without a reload (Supabase Realtime), then the queue lists it.
    await expect(accounts.page.getByTestId('notification-count')).toHaveText(/^[1-9]\d*\+?$/, {
      timeout: 15_000,
    });
    await accounts.page.getByTestId('notification-bell').click();
    await expect(accounts.page.getByRole('dialog', { name: 'Notifications' })).toContainText(
      `Documents received for GS ${gs.gs_no}`,
    );
    await accounts.page.keyboard.press('Escape');
    await accounts.page.reload();
    await expect(accounts.page.getByRole('main')).toContainText(gs.gs_no);
    await accounts.page.screenshot({ path: 'test-results/p2-03/desktop-accounts-queue.png' });

    expect(errors).toEqual([]);
    expect(accounts.errors).toEqual([]);
    await accounts.context.close();
  });

  /**
   * Large video over a throttled network: resumable (TUS) upload with pause / resume.
   * Size and throughput are configurable (RMS_E2E_VIDEO_MB, RMS_E2E_UPLOAD_KBPS); defaults keep
   * the run to about a minute. The P2-03 acceptance run used RMS_E2E_VIDEO_MB=300.
   */
  test('large video uploads resumably on a throttled network with pause/resume', async ({
    page,
  }) => {
    const mb = Number(process.env.RMS_E2E_VIDEO_MB ?? '24');
    const kbps = Number(process.env.RMS_E2E_UPLOAD_KBPS ?? '4000');
    test.setTimeout(Math.max(180_000, ((mb * 8 * 1024) / kbps) * 1000 * 2 + 60_000));
    const file = join(tmpdir(), `rms-e2e-${String(mb)}mb.mp4`);
    if (!existsSync(file)) writeFileSync(file, Buffer.alloc(mb * 1024 * 1024, 1));

    const gs = await createGs();
    const errors = trackConsole(page);
    await signIn(page, 'aman@rms.local');
    await page.goto(`/#/gs/${gs.id}/unboxing`);
    await page.getByRole('button', { name: 'Start carton opening' }).click();
    await expect(page.getByTestId('checklist')).toContainText('Video ✖');

    // DevTools network throttling (Chromium CDP), like "Fast 3G" with a configurable uplink.
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Network.enable');
    await cdp.send('Network.emulateNetworkConditions', {
      offline: false,
      latency: 150,
      downloadThroughput: (1600 * 1024) / 8,
      uploadThroughput: (kbps * 1024) / 8,
    });

    await page.getByTestId('video-file-input').setInputFiles(file);
    const item = page.getByTestId('upload-item');
    await expect(page.getByTestId('upload-warning')).toBeVisible();
    await expect(item).toHaveAttribute('data-phase', 'uploading', { timeout: 30_000 });
    await expect(item.locator('.upload-item__meta')).toContainText(/^[1-9]\d?% of/, {
      timeout: 120_000,
    });
    await item.getByRole('button', { name: 'Pause' }).click();
    await expect(item).toHaveAttribute('data-phase', 'paused');
    const pausedAt = await item.locator('progress').getAttribute('value');
    await page.screenshot({ path: 'test-results/p2-03/pixel7-upload-paused.png' });
    await item.getByRole('button', { name: 'Resume' }).click();
    await expect(item).toHaveAttribute('data-phase', 'uploading');

    await expect(page.getByTestId('checklist')).toContainText('Video ✔', {
      timeout: test.info().timeout - 30_000,
    });
    expect(Number(pausedAt)).toBeGreaterThan(0);
    expect(errors).toEqual([]);
  });

  test('no documents: parcel photo + remark, RM approves on the approval card (DEC-03)', async ({
    page,
    browser,
  }) => {
    test.setTimeout(120_000);
    const gs = await createGs('NO_DOCUMENT');
    const errors = trackConsole(page);
    await signIn(page, 'aman@rms.local');
    await page.goto(`/#/gs/${gs.id}/unboxing`);
    await page.getByRole('button', { name: 'Start carton opening' }).click();
    await page.getByTestId('video-file-input').setInputFiles({
      name: 'unboxing.mov',
      mimeType: 'video/quicktime',
      buffer: VIDEO,
    });
    const checklist = page.getByTestId('checklist');
    await expect(checklist).toContainText('Video ✔', { timeout: 30_000 });
    await expect(checklist).toContainText('exception needed');
    await page.getByTestId('parcel-photo-file-input').setInputFiles({
      name: 'box.png',
      mimeType: 'image/png',
      buffer: PNG,
    });
    await expect(page.locator('.parcel-option')).toHaveCount(1, { timeout: 30_000 });
    await page.locator('#exception-remark').fill('No papers inside the box; label photographed');
    await page.getByRole('button', { name: 'Request Missing Document Exception' }).click();
    await expect(page.getByTestId('exception-status')).toContainText('requested');
    await expect(page.getByRole('button', { name: 'Complete carton opening' })).toBeDisabled();

    // Pratham (RM) on his phone: Approvals → approval card.
    const rmContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const rm = await rmContext.newPage();
    const rmErrors = trackConsole(rm);
    await signIn(rm, 'pratham@rms.local');
    await rm.goto('/#/approvals');
    const card = rm.getByTestId('exception-card').filter({ hasText: gs.gs_no });
    await expect(card).toBeVisible();
    await rm.screenshot({ path: 'test-results/p2-03/rm-approval-card.png', fullPage: true });
    await card.getByRole('button', { name: 'Approve exception' }).click();
    await expect(rm.getByTestId('exception-card').filter({ hasText: gs.gs_no })).toHaveCount(0);

    await page.reload();
    await expect(page.getByTestId('exception-status')).toContainText('approved');
    await expect(checklist).toContainText('Documents ✔');
    await page.getByRole('button', { name: 'Complete carton opening' }).click();
    await expect(page.getByTestId('unboxing-complete')).toContainText('itemization');
    expect(errors).toEqual([]);
    expect(rmErrors).toEqual([]);
    await rmContext.close();
  });
});
