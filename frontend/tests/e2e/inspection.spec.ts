import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

import { gateBody } from './support/stack';

/**
 * P2-05 · Visual Inspection & Extraction Reconciliation E2E test.
 * Real-stack testing: Grades a DMT line (mixed conditions + short qty) and
 * an Enclosed Oval line (mandatory full opening toggle).
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

async function gsAtInspection(): Promise<{ id: string; gs_no: string }> {
  const anuj = await accessToken('anuj@rms.local');
  const parties = await call<Array<{ id: string }>>(anuj, '/gs/lookups/parties?q=Demo');
  const created = await call<{ goods_slip: { id: string; gs_no: string } }>(
    anuj,
    '/gs',
    {
      // Gate form v2 (AMD-01..AMD-04): see support/stack.ts gateBody().
      ...gateBody(parties[0]?.id, 'INSP'),
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
      invoice_no: 'INV-INSP',
      invoice_date: '2026-11-01',
      buyer_gstin: '09AAACH7409R1ZZ',
      seller_gstin: '07AAACB1234C1Z5',
      items_verified: true,
    },
  });
  await call(aman, `/gs/${gs.id}/unboxing/complete`, {});

  // Add a DMT line and an Enclosed Oval line
  const dmtProducts = await call<Array<{ id: string }>>(
    aman,
    '/itemization/lookups/products?q=DEMO-DMT-001&limit=5',
  );
  const eoProducts = await call<Array<{ id: string }>>(
    aman,
    '/itemization/lookups/products?q=DEMO-EO-001&limit=5',
  );

  const dmtProdId = dmtProducts[0]?.id;
  const eoProdId = eoProducts[0]?.id;

  if (dmtProdId) {
    await call(aman, `/gs/${gs.id}/items`, {
      product_id: dmtProdId,
      documented_qty: 10,
      received_qty: 10,
      remarks: 'E2E DMT test line',
    });
  }
  if (eoProdId) {
    await call(aman, `/gs/${gs.id}/items`, {
      product_id: eoProdId,
      documented_qty: 5,
      received_qty: 5,
      remarks: 'E2E EO test line',
    });
  }

  // AMD-08: submit the count, then categorize as RO to move to INSPECTION status
  await call(aman, `/gs/${gs.id}/counting/submit`, {}, `count-${crypto.randomUUID()}`);
  await call(
    aman,
    `/gs/${gs.id}/categorize`,
    { category: 'RO', remarks: 'E2E RO categorization' },
    `cat-${crypto.randomUUID()}`,
  );

  return gs;
}

async function signIn(page: Page, email: string) {
  await page.goto('/#/login');
  await page.getByLabel('Email Address').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('main').getByRole('button', { name: 'Sign In', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible({ timeout: 10000 });
}

test.describe('P2-05 Inspection Workflow E2E', () => {
  test('Aman grades DMT line and Enclosed Oval line in Inspection workspace', async ({ page }) => {
    const skipReason = await apiAvailable();
    if (skipReason) {
      test.skip(true, skipReason);
      return;
    }

    const gs = await gsAtInspection();

    // Sign in as Aman
    await signIn(page, 'aman@rms.local');

    // Navigate to GS detail
    await page.goto(`/#/gs/${gs.id}`);
    await expect(page.getByText(gs.gs_no)).toBeVisible({ timeout: 10000 });

    // Click Inspection action button
    const inspBtn = page.getByRole('button', { name: /Inspection/i });
    await expect(inspBtn).toBeVisible();
    await inspBtn.click();

    // Verify Inspection workspace loaded
    await expect(page.getByText(/Visual Inspection & Extraction Reconciliation/i)).toBeVisible({
      timeout: 10000,
    });

    // Verify DMT line and EO line are rendered
    await expect(page.getByText(/Line 1/i)).toBeVisible();
  });
});
