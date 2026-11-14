/**
 * Production audit Phase 2 (2026-11-14): Supabase Storage round trip on the real stack.
 * Upload through a backend-issued signed URL, confirm, download byte-for-byte, and prove that
 * private files are not reachable without a short-lived signed URL, that the signed URL lives
 * for SIGNED_URL_TTL_SECONDS, and that wrong types / sizes are refused by the API and the bucket.
 * API-level only, so it runs once (desktop-chrome).
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { expect, test } from '@playwright/test';

import {
  API,
  api,
  ApiError,
  apiAvailable,
  createGs,
  FIXTURES,
  token,
  uploadConfirmed,
  USERS,
} from './support/stack';

function supabaseUrl(): string {
  const env = readFileSync(resolve(process.cwd(), '.env.local'), 'utf-8');
  const line = env.split(/\r?\n/).find((l) => l.startsWith('VITE_SUPABASE_URL='));
  return (line?.slice('VITE_SUPABASE_URL='.length) ?? 'http://127.0.0.1:54321').trim();
}

function jwtClaims(jwt: string): { exp: number; iat: number } {
  const part = jwt.split('.')[1] ?? '';
  return JSON.parse(Buffer.from(part, 'base64url').toString('utf-8')) as {
    exp: number;
    iat: number;
  };
}

/** A goods slip in UNBOXING: evidence uploads are only accepted there (GS_NOT_UNBOXING). */
async function unboxingGs(tag: string): Promise<{ id: string }> {
  const gs = await createGs(tag);
  await api(USERS.aman, 'POST', `/gs/${gs.id}/unboxing/start`, {});
  return gs;
}

async function status(promise: Promise<unknown>): Promise<number> {
  try {
    await promise;
    return 200;
  } catch (err) {
    if (err instanceof ApiError) return err.status;
    throw err;
  }
}

test.beforeEach(async () => {
  test.skip(test.info().project.name !== 'desktop-chrome', 'API-level spec runs once');
  const reason = await apiAvailable();
  test.skip(reason !== null, reason ?? '');
});

test('private file: signed upload, confirm, byte-exact download, no public access', async () => {
  const gs = await unboxingGs('storage');
  const attachmentId = await uploadConfirmed(gs.id, 'DOC_PHOTO');

  const dl = await api<{ url: string; expires_in: number; mime_type: string }>(
    USERS.aman,
    'GET',
    `/attachments/${attachmentId}/download-url`,
  );
  expect(dl.mime_type).toBe('image/png');
  const res = await fetch(dl.url);
  expect(res.status).toBe(200);
  // Byte-for-byte the file uploadConfirmed() sent (FIXTURES.PNG).
  const body = Buffer.from(await res.arrayBuffer());
  expect(body.equals(FIXTURES.PNG)).toBe(true);

  // The signed URL is short-lived: its token lives exactly the configured TTL.
  const signed = new URL(dl.url);
  const tokenParam = signed.searchParams.get('token') ?? '';
  const claims = jwtClaims(tokenParam);
  expect(claims.exp - claims.iat).toBe(dl.expires_in);
  expect(dl.expires_in).toBeLessThanOrEqual(3600);

  // Without the token, or through the public endpoint, the private object is not served.
  const path = signed.pathname.replace(/^.*\/object\/sign\//, '');
  const noToken = await fetch(`${signed.origin}${signed.pathname}`);
  expect(noToken.ok).toBe(false);
  const publicUrl = await fetch(`${supabaseUrl()}/storage/v1/object/public/${path}`);
  expect(publicUrl.ok).toBe(false);

  // The API itself needs a signed-in user.
  const anon = await fetch(`${API}/api/v1/attachments/${attachmentId}/download-url`);
  expect(anon.status).toBe(401);
});

test('wrong type and oversize uploads are refused before storage', async () => {
  const gs = await unboxingGs('storage-bad');
  const badType = status(
    api(USERS.aman, 'POST', `/gs/${gs.id}/attachments/upload-url`, {
      kind: 'UNBOXING_VIDEO',
      mime_type: 'application/x-msdownload',
      size_bytes: 1024,
    }),
  );
  expect(await badType).toBe(422);
  const tooBig = status(
    api(USERS.aman, 'POST', `/gs/${gs.id}/attachments/upload-url`, {
      kind: 'DOC_PHOTO',
      mime_type: 'image/png',
      size_bytes: 10 * 1024 * 1024 * 1024,
    }),
  );
  expect(await tooBig).toBe(422);
});

test('the bucket refuses a content type outside its allow-list', async () => {
  const gs = await unboxingGs('storage-mime');
  const ticket = await api<{ attachment: { id: string }; upload: { url: string } }>(
    USERS.aman,
    'POST',
    `/gs/${gs.id}/attachments/upload-url`,
    { kind: 'DOC_PHOTO', mime_type: 'image/png', size_bytes: FIXTURES.PNG.length },
  );
  // A client that lies about the type after getting the URL is stopped by the bucket itself.
  const put = await fetch(ticket.upload.url, {
    method: 'PUT',
    headers: { 'Content-Type': 'text/html', 'x-upsert': 'false' },
    body: '<script>alert(1)</script>',
  });
  expect(put.ok).toBe(false);

  // The pending upload can be discarded; afterwards there is nothing to download.
  const del = await fetch(`${API}/api/v1/attachments/${ticket.attachment.id}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${await token(USERS.aman)}` },
  });
  expect(del.status).toBe(204);
  expect(
    await status(api(USERS.aman, 'GET', `/attachments/${ticket.attachment.id}/download-url`)),
  ).toBe(404);
});
