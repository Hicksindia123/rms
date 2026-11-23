import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { expect, test, type Browser, type Page } from '@playwright/test';

import { gateBody } from './support/stack';

/**
 * P2-04 · Step-3 on phones against the REAL local stack (no API mocks): a GS is brought to
 * ITEMIZATION through the real Step-1/Step-2 APIs (Anuj, Aman; real Storage uploads), then Aman
 * itemises on a Pixel 7 (product search, steppers, documents bottom sheet, CSR categorisation) and
 * Pratham approves the Complete Sales Return from his Approvals inbox on a second Pixel 7.
 *
 * Needs: `supabase start`, demo users (backend/scripts/seed_demo_users.py), demo products
 * (seed.sql DEMO block) and the API on :8000.
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

async function call<T>(token: string, path: string, body?: unknown, key?: string): Promise<T> {
  const res = await fetch(`${API}/api/v1${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(key ? { 'Idempotency-Key': key } : {}),
    },
    body: body === undefined ? null : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path}: ${String(res.status)} ${await res.text()}`);
  return (await res.json()) as T;
}

// 1×1 PNG document photo and a few KB of bytes as a stand-in mp4 (Storage stores bytes).
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
  'base64',
);
const VIDEO = Buffer.alloc(32 * 1024, 7);

async function uploadConfirmed(
  token: string,
  gsId: string,
  kind: string,
  mime: string,
  bytes: Buffer,
): Promise<string> {
  const ticket = await call<{
    attachment: { id: string };
    upload: { method: string; url: string };
  }>(token, `/gs/${gsId}/attachments/upload-url`, {
    kind,
    mime_type: mime,
    size_bytes: bytes.length,
  });
  if (ticket.upload.method !== 'SIGNED_PUT') throw new Error('expected a signed PUT ticket');
  const put = await fetch(ticket.upload.url, {
    method: 'PUT',
    headers: { 'Content-Type': mime, 'x-upsert': 'false' },
    body: new Uint8Array(bytes),
  });
  if (!put.ok) throw new Error(`storage PUT failed: ${String(put.status)} ${await put.text()}`);
  await call(token, `/attachments/${ticket.attachment.id}/confirm`, {});
  return ticket.attachment.id;
}

/** Step-1 + Step-2 through the real API → a GS at ITEMIZATION. */
async function gsAtItemization(): Promise<{ id: string; gs_no: string }> {
  const anuj = await accessToken('anuj@rms.local');
  const parties = await call<Array<{ id: string }>>(anuj, '/gs/lookups/parties?q=Demo');
  const created = await call<{ goods_slip: { id: string; gs_no: string } }>(
    anuj,
    '/gs',
    {
      // Gate form v2 (AMD-01..AMD-04): see support/stack.ts gateBody().
      ...gateBody(parties[0]?.id, 'E2E'),
    },
    `e2e-${crypto.randomUUID()}`,
  );
  const gs = created.goods_slip;
  const aman = await accessToken('aman@rms.local');
  await call(aman, `/gs/${gs.id}/unboxing/start`, {});
  await uploadConfirmed(aman, gs.id, 'UNBOXING_VIDEO', 'video/mp4', VIDEO);
  const photo = await uploadConfirmed(aman, gs.id, 'DOC_PHOTO', 'image/png', PNG);
  await call(aman, `/gs/${gs.id}/documents`, {
    attachment_id: photo,
    values: {
      doc_classification: 'INVOICE',
      invoice_no: 'INV-E2E',
      invoice_date: '2026-11-01',
      buyer_gstin: '09AAACH7409R1ZZ',
      seller_gstin: '07AAACB1234C1Z5',
      items_verified: true,
    },
  });
  await call(aman, `/gs/${gs.id}/unboxing/complete`, {});
  return gs;
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

async function noHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);
}

async function phone(browser: Browser, email: string) {
  const { devices } = await import('@playwright/test');
  const context = await browser.newContext({ ...devices['Pixel 7'] });
  const page = await context.newPage();
  const errors = trackConsole(page);
  await signIn(page, email);
  return { context, page, errors };
}

async function addLine(page: Page, search: string, documented: number, received: number) {
  const editor = page.getByTestId('line-editor').last();
  await editor.getByRole('combobox').or(editor.locator('input').first()).first().fill(search);
  await page
    .getByRole('option', { name: new RegExp(search) })
    .first()
    .click();
  await editor.getByRole('spinbutton', { name: 'As per document' }).fill(String(documented));
  await editor.getByRole('spinbutton', { name: 'Physically received' }).fill(String(received));
  // One tap on the big "+" stepper, then back with "−" (touch targets work).
  await editor.getByRole('button', { name: 'Increase Physically received' }).click();
  await editor.getByRole('button', { name: 'Decrease Physically received' }).click();
  // DEC-53: the condition split is entered with the line; put every piece in the first bucket.
  const split = editor.getByTestId('line-split-editor');
  await split.getByRole('spinbutton').first().fill(String(received));
  await expect(editor.getByTestId('split-total')).toHaveText(
    `Split ${String(received)} / Physical ${String(received)}`,
  );
  await editor.getByRole('button', { name: 'Add line' }).click();
}

test.describe('Itemisation & CSR approval (P2-04)', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    if (testInfo.project.name !== 'mobile-pixel-7') {
      test.skip(true, 'Itemisation E2E runs on the Pixel 7 viewport');
    }
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  test('Aman itemises on mobile → Pratham approves the CSR on mobile', async ({
    page,
    browser,
  }) => {
    test.fixme(
      true,
      'Complete Sales Return now parks in SALES_RETURN_HOLD (DEC-64); the RM CSR approval is retired (DEC-72). Covered by offline_replacement_flow.spec.ts (P12)',
    );
    test.setTimeout(120_000);
    const gs = await gsAtItemization();
    const errors = trackConsole(page);

    // --- Aman, Pixel 7 -----------------------------------------------------------------------
    await signIn(page, 'aman@rms.local');
    await page.goto(`/#/gs/${gs.id}`);
    // AMD-08: the Step-3 button carries the configured label (Counting).
    await page.getByRole('button', { name: 'Counting' }).click();
    await expect(page.getByRole('heading', { name: gs.gs_no })).toBeVisible();

    // Documents as a bottom sheet for counting against the paper.
    await page.getByRole('button', { name: /Documents \(1\)/ }).click();
    const sheet = page.getByTestId('doc-panel');
    await expect(sheet).toBeVisible();
    await expect(sheet.locator('img')).toBeVisible();
    await sheet.getByRole('button', { name: 'Close documents' }).click();
    await expect(sheet).toBeHidden();

    await addLine(page, 'Demo DMT', 10, 10);
    await expect(page.getByTestId('item-line')).toHaveCount(1);
    await addLine(page, 'Demo Prismatic', 5, 4);
    await expect(page.getByTestId('item-line')).toHaveCount(2);
    await expect(page.getByTestId('item-line').nth(1)).toContainText('Short 1');
    await noHorizontalOverflow(page);

    // DEC-53: the screen's one submit goes straight to RM Review. The earlier whole-GS CSR / RO
    // path is reached here through the counting-submit API (kept for compatibility).
    await expect(page.getByRole('button', { name: /^Submit to / })).toBeEnabled();
    await call(
      await accessToken('aman@rms.local'),
      `/gs/${gs.id}/counting/submit`,
      {},
      `count-${crypto.randomUUID()}`,
    );
    await page.reload();

    // Category explanations come from the option set; CSR "Requires approval".
    const csr = page.locator('.category-option', { hasText: 'Complete Sales Return' });
    await expect(csr).toContainText('Requires approval');
    await csr.click();
    await page.getByRole('button', { name: 'Categorise GS' }).click();
    await expect(page.getByText(/Waiting for the Replacement Manager/)).toBeVisible();
    await expect(page.getByTestId('lot-row')).toHaveCount(2);
    await expect(page.getByTestId('lot-row').first()).toContainText('Inward Staging: 10');
    await noHorizontalOverflow(page);

    // --- Pratham, second Pixel 7 ----------------------------------------------------------------
    const rm = await phone(browser, 'pratham@rms.local');
    await rm.page.getByRole('button', { name: 'Approvals' }).click();
    const card = rm.page.getByTestId('csr-card').filter({ hasText: gs.gs_no });
    await expect(card).toBeVisible();
    await expect(card).toContainText('Complete Sales Return');
    await expect(card).toContainText('received 14 of 15');
    await expect(card.locator('.thumb')).toHaveCount(1);
    await noHorizontalOverflow(rm.page);
    await card.getByLabel(/Remarks/).fill('All items, full quantity');
    await card.getByRole('button', { name: /Approved - Complete Sales Return/ }).click();
    await expect(card).toBeHidden();

    await rm.page.goto(`/#/gs/${gs.id}/itemization`);
    await expect(rm.page.getByText('Approved - Complete Sales Return')).toBeVisible();
    const transfer = rm.page.getByTestId('transfer-card');
    await expect(transfer).toContainText('With packaging');
    await expect(transfer).toContainText('Inward Staging → Intermediate Store');
    expect(rm.errors).toEqual([]);
    await rm.context.close();

    // Aman's screen reflects the decision after a reload.
    await page.reload();
    await expect(page.getByText('Approved - Complete Sales Return')).toBeVisible();
    expect(errors).toEqual([]);
  });
});
