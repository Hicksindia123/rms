import { expect } from '@playwright/test';

import { addItem, api, createGs, gsStatus, unboxed, USERS } from './stack';

/**
 * Locked Replacement GSs for the transfer-slip specs (P5 RM generation, P6 store acknowledgement),
 * built through the API (P4 endpoints).
 */
export interface Product {
  id: string;
  bucket: string;
}

export async function productOf(category: string): Promise<Product> {
  const cats = await api<Array<{ id: string; code: string }>>(
    USERS.aman,
    'GET',
    '/itemization/lookups/categories',
  );
  const cat = cats.find((c) => c.code === category);
  if (!cat) throw new Error(`no category ${category}`);
  const rows = await api<Array<{ id: string }>>(
    USERS.aman,
    'GET',
    `/itemization/lookups/products?q=&limit=50&category_id=${cat.id}`,
  );
  for (const r of rows) {
    const fields = await api<{ allowed_buckets: Array<{ field_code: string }> }>(
      USERS.aman,
      'GET',
      `/itemization/lookups/products/${r.id}/fields`,
    );
    const first = fields.allowed_buckets[0];
    if (first) return { id: r.id, bucket: first.field_code };
  }
  throw new Error(`no ${category} product with condition buckets`);
}

/** A locked Replacement GS with one line per product (API setup, P4 endpoints). */
export async function lockedGs(tag: string, lines: Array<[Product, number]>) {
  const gs = await createGs(tag);
  await unboxed(gs);
  const ids: string[] = [];
  for (const [p, qty] of lines) ids.push(await addItem(gs.id, p.id, qty, qty));
  await api(
    USERS.aman,
    'POST',
    `/gs/${gs.id}/itemization/return-choice`,
    { category_code: 'RO' },
    true,
  );
  for (const [i, [p, qty]] of lines.entries()) {
    await api(USERS.aman, 'PATCH', `/gs/${gs.id}/items/${ids[i] ?? ''}`, {
      buckets: [{ field_code: p.bucket, qty }],
    });
  }
  await api(USERS.aman, 'POST', `/gs/${gs.id}/categorisation/lock`, {}, true);
  expect(await gsStatus(gs.id)).toBe('PENDING_TRANSFER_SLIP');
  return gs;
}
