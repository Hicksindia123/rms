/**
 * Real-stack helpers for the Phase-2 gate E2E scenarios (P2-08). No API mocks: every call goes to
 * the local FastAPI (:8000) and Supabase. Business data is created only through the API or the UI.
 *
 * Sessions: each demo user signs in ONCE per run (tokens cached in a lock-guarded temp file shared
 * by all Playwright workers), because local Supabase Auth allows 30 sign-ins per 5 minutes. A
 * browser context gets the real session injected into supabase-js storage, so the app runs exactly
 * as after an interactive sign-in (interactive sign-in itself is covered by the gate scenario and
 * the P2-02..P2-04 specs).
 */
import { execFileSync } from 'node:child_process';
import { existsSync, openSync, closeSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

import { expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test';

export const API = process.env.RMS_E2E_API ?? 'http://localhost:8000';
export const PASSWORD = process.env.RMS_DEMO_PASSWORD ?? 'Demo@123456';
export const USERS = {
  gate: 'anuj@rms.local',
  aman: 'aman@rms.local',
  rm: 'pratham@rms.local',
  accounts: 'deepak@rms.local',
  sahil: 'sahil@rms.local',
  spt: 'spt@rms.local',
  spm: 'spm@rms.local',
  dispatch: 'dispatch@rms.local',
  tech: 'rajkumar@rms.local',
  mainstore: 'mainstore@rms.local',
  admin: 'admin@rms.local',
} as const;

/** The local bootstrap Super Admin has its own password (backend/scripts/bootstrap_super_admin.py). */
const ADMIN_PASSWORD = process.env.RMS_ADMIN_PASSWORD ?? 'Admin@123456';
function passwordFor(email: string): string {
  return email === USERS.admin ? ADMIN_PASSWORD : PASSWORD;
}

/** Scenarios run across all configured Playwright projects (desktop Chrome, Firefox, WebKit, Pixel 7, iPhone 14, iPad). */
export const GATE_PROJECTS = [
  'desktop-chrome',
  'desktop-chromium',
  'desktop-firefox',
  'desktop-webkit',
  'mobile-pixel-7',
  'mobile-iphone-14',
  'tablet-ipad',
];

function frontendEnv(): Record<string, string> {
  const text = readFileSync(resolve(process.cwd(), '.env.local'), 'utf-8');
  return Object.fromEntries(
    text
      .split(/\r?\n/)
      .filter((l) => l.includes('=') && !l.startsWith('#'))
      .map((l) => [l.slice(0, l.indexOf('=')).trim(), l.slice(l.indexOf('=') + 1).trim()]),
  );
}

export async function apiAvailable(): Promise<string | null> {
  try {
    const res = await fetch(`${API}/api/v1/health`);
    return res.ok ? null : `API health returned ${String(res.status)}`;
  } catch (err) {
    return `API not reachable at ${API}: ${String(err)}`;
  }
}

// --- sessions ------------------------------------------------------------------------------------
interface Session {
  access_token: string;
  refresh_token: string;
  expires_at: number;
  [k: string]: unknown;
}

const CACHE = join(tmpdir(), 'rms-e2e-sessions.json');
const LOCK = `${CACHE}.lock`;

function readCache(): Record<string, Session> {
  try {
    return JSON.parse(readFileSync(CACHE, 'utf-8')) as Record<string, Session>;
  } catch {
    return {};
  }
}

function fresh(s: Session | undefined): s is Session {
  // Keep 20 minutes of margin so supabase-js never needs to refresh (refresh tokens are shared).
  return Boolean(s) && (s?.expires_at ?? 0) - Date.now() / 1000 > 20 * 60;
}

export async function session(email: string): Promise<Session> {
  const cached = readCache()[email];
  if (fresh(cached)) return cached;
  const deadline = Date.now() + 60_000;
  for (;;) {
    let fd: number | null;
    try {
      fd = openSync(LOCK, 'wx'); // exclusive create: only one worker signs in at a time
    } catch {
      fd = null; // another worker holds the lock
    }
    if (fd !== null) {
      try {
        const again = readCache()[email];
        if (fresh(again)) return again;
        const env = frontendEnv();
        const candidates = [passwordFor(email), 'Uat@2026RMS!', 'Admin@123456', 'Demo@123456'];
        let s: Session | null = null;
        for (const pw of candidates) {
          const res = await fetch(
            `${env.VITE_SUPABASE_URL ?? ''}/auth/v1/token?grant_type=password`,
            {
              method: 'POST',
              headers: {
                apikey: env.VITE_SUPABASE_ANON_KEY ?? '',
                'Content-Type': 'application/json',
              },
              body: JSON.stringify({ email, password: pw }),
            },
          );
          if (res.ok) {
            s = (await res.json()) as Session;
            break;
          }
        }
        if (!s) throw new Error(`sign-in failed for ${email}`);
        writeFileSync(CACHE, JSON.stringify({ ...readCache(), [email]: s }));
        return s;
      } finally {
        closeSync(fd);
        unlinkSync(LOCK);
      }
    }
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${LOCK}`);
    await new Promise((r) => setTimeout(r, 150));
    const other = readCache()[email];
    if (fresh(other)) return other;
  }
}

export async function token(email: string): Promise<string> {
  return (await session(email)).access_token;
}

// --- API -----------------------------------------------------------------------------------------
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: { error?: { code?: string; message?: string } },
  ) {
    super(`${String(status)} ${JSON.stringify(body)}`);
  }
}

/** A cached session can outlive its user (e.g. after `supabase db reset`): forget it. */
function forget(email: string): void {
  const kept = Object.entries(readCache()).filter(([k]) => k !== email);
  writeFileSync(CACHE, JSON.stringify(Object.fromEntries(kept)));
}

export async function api<T>(
  email: string,
  method: string,
  path: string,
  body?: unknown,
  idempotent = false,
  retried = false,
): Promise<T> {
  const res = await fetch(`${API}/api/v1${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${await token(email)}`,
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(idempotent ? { 'Idempotency-Key': `e2e-${crypto.randomUUID()}` } : {}),
    },
    body: body === undefined ? null : JSON.stringify(body),
  });
  if (res.status === 401 && !retried) {
    forget(email);
    return api<T>(email, method, path, body, idempotent, true);
  }
  const text = await res.text();
  const parsed: unknown = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, parsed as ApiError['body']);
  return parsed as T;
}

const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
  'base64',
);
export const FIXTURES = { PNG, VIDEO: Buffer.alloc(32 * 1024, 7) };

export async function uploadConfirmed(
  gsId: string,
  kind: 'UNBOXING_VIDEO' | 'DOC_PHOTO',
  boxNo?: number,
): Promise<string> {
  const [mime, bytes] =
    kind === 'UNBOXING_VIDEO' ? ['video/mp4', FIXTURES.VIDEO] : ['image/png', PNG];
  const ticket = await api<{ attachment: { id: string }; upload: { url: string } }>(
    USERS.aman,
    'POST',
    `/gs/${gsId}/attachments/upload-url`,
    { kind, mime_type: mime, size_bytes: bytes.length, ...(boxNo ? { box_no: boxNo } : {}) },
  );
  const put = await fetch(ticket.upload.url, {
    method: 'PUT',
    headers: { 'Content-Type': mime, 'x-upsert': 'false' },
    body: new Uint8Array(bytes),
  });
  if (!put.ok) throw new Error(`storage PUT failed: ${String(put.status)} ${await put.text()}`);
  await api(USERS.aman, 'POST', `/attachments/${ticket.attachment.id}/confirm`, {});
  return ticket.attachment.id;
}

export interface Gs {
  id: string;
  gs_no: string;
}

/** Gate form v2 body (change plan 2026-11-12 Phase 2, AMD-01..AMD-04). E-Commerce returns have
 * no gate entry number (DEC-39), so parallel workers never collide on it (DEC-38). */
export function gateBody(
  partyId: string | undefined,
  tag: string,
  doc: 'INVOICE' | 'NO_DOCUMENT' = 'INVOICE',
): Record<string, unknown> {
  const noDoc = doc === 'NO_DOCUMENT';
  return {
    party_id: partyId,
    values: {
      return_type: 'ECOMMERCE_RETURN',
      carton_count: 1,
      delivery_mode: 'COURIER_PARCEL',
      courier_name: 'DTDC',
      docket_no: `E2E-${tag}-${String(Date.now())}`,
      no_document: noDoc,
      ...(noDoc ? { missing_doc_warning_acknowledged: true } : {}),
      gs_creation_format: 'AUTO_STANDARD',
    },
    documents: noDoc
      ? []
      : [{ doc_type_code: 'INVOICE', doc_no: `INV-${tag}`, doc_date: '2026-11-01' }],
  };
}

/** Step-1 through the API as the gate user. */
export async function createGs(tag: string): Promise<Gs> {
  let partyId: string | undefined;
  const demoParties = await api<Array<{ id: string }>>(USERS.gate, 'GET', '/gs/lookups/parties?q=Demo');
  if (demoParties.length && demoParties[0]) {
    partyId = demoParties[0].id;
  } else {
    const anyParties = await api<Array<{ id: string }>>(USERS.gate, 'GET', '/gs/lookups/parties?limit=5');
    partyId = anyParties[0]?.id;
  }
  const created = await api<{ goods_slip: Gs }>(
    USERS.gate,
    'POST',
    '/gs',
    gateBody(partyId, tag),
    true,
  );
  return created.goods_slip;
}

/** Step-2 through the API as Aman: video + classified invoice photo, then complete. */
export async function unboxed(gs: Gs): Promise<void> {
  await api(USERS.aman, 'POST', `/gs/${gs.id}/unboxing/start`, {});
  await uploadConfirmed(gs.id, 'UNBOXING_VIDEO');
  const photo = await uploadConfirmed(gs.id, 'DOC_PHOTO');
  await api(USERS.aman, 'POST', `/gs/${gs.id}/documents`, {
    attachment_id: photo,
    values: {
      doc_classification: 'INVOICE',
      invoice_no: `INV-${gs.gs_no}`,
      invoice_date: '2026-11-01',
      buyer_gstin: '09AAACH7409R1ZZ',
      seller_gstin: '07AAACB1234C1Z5',
      items_verified: true,
    },
  });
  await api(USERS.aman, 'POST', `/gs/${gs.id}/unboxing/complete`, {});
}

export async function productId(code: string): Promise<string> {
  const rows = await api<Array<{ id: string; code: string }>>(
    USERS.aman,
    'GET',
    `/itemization/lookups/products?q=${encodeURIComponent(code)}&limit=5`,
  );
  const hit = rows.find((r) => r.code === code);
  if (hit) return hit.id;
  if (code.includes('DMT')) {
    const dmt = await api<Array<{ id: string; code: string }>>(
      USERS.aman,
      'GET',
      '/itemization/lookups/products?q=DMT&limit=5',
    );
    const first = dmt[0];
    if (first) return first.id;
  }
  throw new Error(`product ${code} not found`);
}

export async function addItem(gsId: string, product: string, doc: number, recv: number) {
  return (
    await api<{ id: string }>(USERS.aman, 'POST', `/gs/${gsId}/items`, {
      product_id: product,
      documented_qty: doc,
      received_qty: recv,
    })
  ).id;
}

export async function categorize(gsId: string, category: 'RO' | 'CSR'): Promise<void> {
  // AMD-08 (change plan Phase 3): Counting is submitted before the category is chosen.
  await api(USERS.aman, 'POST', `/gs/${gsId}/counting/submit`, {}, true);
  await api(USERS.aman, 'POST', `/gs/${gsId}/categorize`, { category }, true);
}

export async function gsStatus(gsId: string): Promise<string> {
  return (await api<{ goods_slip: { status: string } }>(USERS.aman, 'GET', `/gs/${gsId}`))
    .goods_slip.status;
}

/** Grade + finalise a line through the API (setup for scenarios that focus on later steps). */
export async function inspectByApi(itemId: string, allocations: Record<string, number>) {
  const received = Object.entries(allocations)
    .filter(([c]) => !c.endsWith('_SHORT_QTY'))
    .reduce((s, [, q]) => s + q, 0);
  await api(USERS.aman, 'PUT', `/gs-items/${itemId}/inspection`, {
    full_opening_confirmed: true,
    allocations: Object.entries(allocations).map(([condition_code, qty]) => ({
      condition_code,
      qty,
    })),
    extraction: { primary_type: 'PACKAGING_EXTRACTED', packaging_qty: received, container_qty: 0 },
  });
  await api(USERS.aman, 'POST', `/gs-items/${itemId}/inspection/finalise`, {}, true);
}

/** Run a worker job exactly as the scheduler does (`python -m app.worker --run-job …`). */
export function runWorkerJob(job: string): void {
  const backend = resolve(process.cwd(), '..', 'backend');
  const python = existsSync(join(backend, '.venv', 'Scripts', 'python.exe'))
    ? join(backend, '.venv', 'Scripts', 'python.exe')
    : join(backend, '.venv', 'bin', 'python');
  execFileSync(python, ['-m', 'app.worker', '--run-job', job], { cwd: backend, stdio: 'pipe' });
}

// --- browser -------------------------------------------------------------------------------------
export interface Device {
  context: BrowserContext;
  page: Page;
  errors: string[];
}

export function trackConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  page.on('pageerror', (err) => errors.push(err.message));
  return errors;
}

/** A browser context for `email` with the project's device (desktop or Pixel 7), signed in. */
export async function asUser(browser: Browser, email: string, path: string): Promise<Device> {
  const { baseURL, viewport, userAgent, deviceScaleFactor, isMobile, hasTouch } =
    test.info().project.use;
  const context = await browser.newContext({
    ...(baseURL ? { baseURL } : {}),
    ...(viewport ? { viewport } : {}),
    ...(userAgent ? { userAgent } : {}),
    ...(deviceScaleFactor ? { deviceScaleFactor } : {}),
    ...(isMobile !== undefined ? { isMobile } : {}),
    ...(hasTouch !== undefined ? { hasTouch } : {}),
    timezoneId: 'Asia/Kolkata', // business timezone; the API dates audits in IST
  });
  const s = await session(email);
  const ref = new URL(frontendEnv().VITE_SUPABASE_URL ?? 'http://127.0.0.1').hostname.split('.')[0];
  await context.addInitScript(
    ([key, value]) => {
      window.localStorage.setItem(key, value);
    },
    [`sb-${ref ?? ''}-auth-token`, JSON.stringify(s)] as const,
  );
  const page = await context.newPage();
  const errors = trackConsole(page);
  await page.goto(`/#${path}`);
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible({ timeout: 15_000 });
  return { context, page, errors };
}

export async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow, 'page must not scroll horizontally').toBe(false);
}

export async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({
    path: `test-results/p2-08/${test.info().project.name}-${name}.png`,
    fullPage: true,
  });
}
