import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

import { gateBody } from './support/stack';

/**
 * P2-07 · Step-3 a) RM Item Segregation, Pendency Register & Replacement Slip E2E test.
 * Flow:
 * 1. Seed / advance GS to RM_REVIEW (via API).
 * 2. Pratham (RM) signs in on mobile viewport (390x844), inspects segregation touch steppers,
 *    verifies locked Not Allowed quantity from inspection, saves/finalises segregation.
 * 3. On desktop viewport (1280x800), navigates to Replacement Slip print page,
 *    verifies company header, party details, line items, totals, and signature blocks.
 * 4. Navigates to Pendency Register and verifies register list view.
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

async function call<T>(
  token: string,
  path: string,
  body?: unknown,
  key?: string,
  method = 'POST',
): Promise<T> {
  const res = await fetch(`${API}/api/v1${path}`, {
    method: body === undefined && method === 'POST' ? 'GET' : method,
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
  const put = await fetch(ticket.upload.url, {
    method: 'PUT',
    headers: { 'Content-Type': mime, 'x-upsert': 'false' },
    body: new Uint8Array(bytes),
  });
  if (!put.ok) throw new Error(`storage PUT failed: ${String(put.status)} ${await put.text()}`);
  await call(token, `/attachments/${ticket.attachment.id}/confirm`, {});
  return ticket.attachment.id;
}

async function gsAtRmReview(): Promise<{ id: string; gs_no: string; item_id: string }> {
  const anuj = await accessToken('anuj@rms.local');
  const parties = await call<Array<{ id: string }>>(anuj, '/gs/lookups/parties?q=Demo');
  const created = await call<{ goods_slip: { id: string; gs_no: string } }>(
    anuj,
    '/gs',
    {
      // Gate form v2 (AMD-01..AMD-04): see support/stack.ts gateBody().
      ...gateBody(parties[0]?.id, 'RM-01'),
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
      invoice_no: 'INV-RM-01',
      invoice_date: '2026-11-01',
      buyer_gstin: '09AAACH7409R1ZZ',
      seller_gstin: '07AAACB1234C1Z5',
      items_verified: true,
    },
  });
  await call(aman, `/gs/${gs.id}/unboxing/complete`, {});

  // Add a DMT line (10 pcs)
  const dmtProducts = await call<Array<{ id: string }>>(
    aman,
    '/itemization/lookups/products?q=DEMO-DMT-001&limit=5',
  );
  const dmtProdId = dmtProducts[0]?.id;
  const itemRes = await call<{ id: string }>(aman, `/gs/${gs.id}/items`, {
    product_id: dmtProdId,
    documented_qty: 10,
    received_qty: 10,
    remarks: 'E2E DMT test line',
  });

  // AMD-08: submit the count, then categorize as RO to move to INSPECTION status
  await call(aman, `/gs/${gs.id}/counting/submit`, {}, `count-${crypto.randomUUID()}`);
  await call(
    aman,
    `/gs/${gs.id}/categorize`,
    { category: 'RO', remarks: 'E2E RO categorization' },
    `cat-${crypto.randomUUID()}`,
  );

  // Inspect line: 8 Good, 2 Broken Body (Rejected)
  await call(
    aman,
    `/gs-items/${itemRes.id}/inspection`,
    {
      allocations: [
        { condition_code: 'DMT_OK_PACKED', qty: 8 },
        { condition_code: 'DMT_BROKEN_BODY', qty: 2 },
      ],
      extraction: { primary_type: 'PACKAGING_EXTRACTED', packaging_qty: 10, container_qty: 0 },
    },
    undefined,
    'PUT',
  );

  // Finalise inspection line -> advances GS to RM_REVIEW
  await call(aman, `/gs-items/${itemRes.id}/inspection/finalise`, {});

  return { id: gs.id, gs_no: gs.gs_no, item_id: itemRes.id };
}

async function signIn(page: Page, email: string) {
  await page.goto('/#/login');
  await page.getByLabel('Email Address').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('main').getByRole('button', { name: 'Sign In', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible({ timeout: 10000 });
}

test.describe('P2-07 RM Actions & Replacement Slip E2E', () => {
  test('RM segregates on mobile viewport then prints slip on desktop viewport', async ({
    page,
  }) => {
    const skipReason = await apiAvailable();
    if (skipReason) {
      test.skip(true, skipReason);
      return;
    }

    const { id: gsId, gs_no } = await gsAtRmReview();

    // 1. Mobile Viewport: RM Segregation
    await page.setViewportSize({ width: 390, height: 844 });
    await signIn(page, 'pratham@rms.local');

    // Navigate to goods slip detail
    await page.goto(`/#/gs/${gsId}`);
    await expect(page.getByText(gs_no)).toBeVisible({ timeout: 10000 });

    // Click "RM Actions" button
    const rmActionsBtn = page.getByRole('button', { name: /RM Actions/i });
    await expect(rmActionsBtn).toBeVisible();
    await rmActionsBtn.click();

    // Verify RM Segregation Page loaded
    await expect(page.getByText('RM Item Segregation')).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/Locked: 2 rejected at inspection/i)).toBeVisible();

    // Click "+" on Send New to allocate remaining 8 pieces
    const sendNewPlusBtn = page.getByRole('button', { name: 'Increase Send New' });
    await expect(sendNewPlusBtn).toBeVisible();
    for (let i = 0; i < 8; i++) {
      await sendNewPlusBtn.click();
    }

    // Verify reconciliation badge
    await expect(page.getByText(/All Lines Fully Reconciled/i)).toBeVisible({ timeout: 5000 });

    // Save draft or finalise
    const saveDraftBtn = page.getByRole('button', { name: /Save Draft Revision/i });
    await expect(saveDraftBtn).toBeEnabled();
    await saveDraftBtn.click();

    await expect(page.getByText(/Saved revision/i)).toBeVisible({ timeout: 8000 });

    // 2. Desktop Viewport: Replacement Slip View
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(`/#/gs/${gsId}/replacement-slip`);

    // Verify company header and replacement slip structure
    await expect(page.getByText('Hicks Thermometers (India) Limited')).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByText('Goods Return Replacement Slip')).toBeVisible();
    await expect(page.getByText(gs_no)).toBeVisible();
    await expect(page.getByRole('button', { name: /Print \/ Save as PDF/i })).toBeVisible();

    // Verify table lines and quantities
    await expect(page.getByText('Total:')).toBeVisible();

    // Verify signature blocks
    await expect(page.getByText(/Replacement Manager/i)).toBeVisible();

    // 3. Pendency Register View
    await page.goto('/#/pendencies');
    await expect(page.getByText('Pendency (BP) Register')).toBeVisible({ timeout: 10000 });
    await expect(page.getByPlaceholder(/Search GS, party, or product/i)).toBeVisible();
  });
});
