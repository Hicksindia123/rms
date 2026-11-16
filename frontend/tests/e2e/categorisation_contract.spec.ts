import { expect, test, type Page } from '@playwright/test';

import {
  addItem,
  api,
  apiAvailable,
  asUser,
  createGs,
  expectNoHorizontalOverflow,
  gsStatus,
  productId,
  unboxed,
  USERS,
} from './support/stack';

/**
 * Regression: "e.allowed_counts is not iterable" (CLIENT_ERROR) on the Categorisation screen right
 * after a successful count (reported on GS/2026-27/00001, ENCLOSED SCALE OVAL THERMOMETER
 * ITM-00180, 6 of 6). Drives the real UI against the real API (no mocks) for Counting →
 * Categorisation: exact / partial / excess / multi-product, malformed payload handling, an
 * existing (pre-saved) record, and both whole-GS options (CSR → approval, RO → inspection).
 */

const EO = 'ITM-00180'; // ENCLOSED_OVAL — the product of the report
const DMT = 'ITM-00165';
const PRS = 'ITM-00167';

interface CatField {
  field_id: string;
  field_code: string;
  field_label: string;
  sort_order: number;
}
interface CatItem {
  item_id: string;
  received_qty: number;
  allowed_buckets: CatField[];
  allowed_counts: CatField[];
  buckets: Array<{ field_code: string; qty: number }>;
}
interface CatState {
  items: CatItem[];
  can_submit: boolean;
  all_conserved: boolean;
}

test.beforeAll(async () => {
  const down = await apiAvailable();
  test.skip(down !== null, `RMS stack not available: ${down ?? ''}`);
});

/** GS through gate + carton opening with the given lines (document qty, received qty). */
async function countedLines(tag: string, lines: Array<[string, number, number]>) {
  const gs = await createGs(tag);
  await unboxed(gs);
  const itemIds: string[] = [];
  for (const [code, doc, recv] of lines) {
    itemIds.push(await addItem(gs.id, await productId(code), doc, recv));
  }
  return { gs, itemIds };
}

/** Submit the count in the UI and return the categorisation payload the screen received. */
async function submitCountInUi(page: Page, gsId: string): Promise<CatState> {
  await page.getByRole('button', { name: 'Submit count' }).click();
  const catResponse = page.waitForResponse(
    (r) => r.url().endsWith(`/gs/${gsId}/categorisation`) && r.request().method() === 'GET',
  );
  await page.getByRole('button', { name: /Confirm submit/ }).click();
  const res = await catResponse;
  expect(res.status()).toBe(200);
  return (await res.json()) as CatState;
}

/** The categorisation section loaded without the contract crash. */
async function expectCategorisationLoaded(page: Page): Promise<void> {
  await expect(page.getByRole('heading', { name: /Item Categorisation/ })).toBeVisible();
  await expect(page.getByText('Item categorisation could not be loaded')).toHaveCount(0);
  await expect(page.getByText(/is not iterable/)).toHaveCount(0);
  await expect(page.getByText('CLIENT_ERROR')).toHaveCount(0);
}

function expectContract(state: CatState): void {
  for (const it of state.items) {
    expect(Array.isArray(it.allowed_buckets), 'allowed_buckets is an array').toBe(true);
    expect(Array.isArray(it.allowed_counts), 'allowed_counts is an array').toBe(true);
    for (const f of [...it.allowed_buckets, ...it.allowed_counts]) {
      expect(Object.keys(f).sort()).toEqual(['field_code', 'field_id', 'field_label', 'sort_order']);
    }
  }
}

async function fillBucket(page: Page, itemId: string, code: string, qty: number): Promise<void> {
  await page.locator(`[id="b-${itemId}-${code}"]`).fill(String(qty));
}

async function saveLine(page: Page, lineNo: number, gsId: string): Promise<void> {
  const saved = page.waitForResponse(
    (r) => r.url().includes(`/gs/${gsId}/items/`) && r.request().method() === 'PUT',
  );
  await page.getByRole('button', { name: `Save Line ${String(lineNo)}` }).click();
  const res = await saved;
  expect(res.status(), await res.text()).toBe(200);
  expect(res.request().headers()['idempotency-key']).toMatch(/^web-/);
}

async function submitCategorisation(page: Page, gsId: string): Promise<void> {
  const button = page.getByRole('button', { name: /Submit Categorisation to RM Review/ });
  await expect(button).toBeEnabled();
  await button.click();
  await expect.poll(() => gsStatus(gsId)).toBe('RM_REVIEW');
}

test.describe('Counting → Categorisation (allowed_counts contract)', () => {
  test('Scenario 1: 6 of 6 (ITM-00180) loads, saves, submits to RM review; RM review loads', async ({
    browser,
  }) => {
    const { gs, itemIds } = await countedLines('cat-exact', [[EO, 6, 6]]);
    const itemId = itemIds[0] ?? '';
    const aman = await asUser(browser, USERS.aman, `/gs/${gs.id}/itemization`);
    const { page } = aman;

    const state = await submitCountInUi(page, gs.id);
    expectContract(state);
    await expectCategorisationLoaded(page);
    // Both whole-GS options are still offered alongside.
    await expect(page.locator('.category-option', { hasText: 'Complete Sales Return' })).toContainText(
      'Requires approval',
    );
    await expect(page.locator('.category-option', { hasText: 'Replacement Only' })).toBeVisible();

    const item = state.items[0];
    expect(item?.received_qty).toBe(6);
    const codes = item?.allowed_buckets.map((b) => b.field_code) ?? [];
    expect(codes.length).toBeGreaterThan(1);
    for (const b of item?.allowed_buckets ?? []) {
      await expect(page.locator(`label[for="b-${itemId}-${b.field_code}"]`)).toHaveText(b.field_label);
    }
    await expect(page.getByText(/SKU: ITM-00180/)).toBeVisible();
    await expect(page.getByText(/ENCLOSED SCALE OVAL THERMOMETER/).first()).toBeVisible();
    await expect(page.getByRole('button', { name: /Submit Categorisation/ })).toBeDisabled();

    await fillBucket(page, itemId, codes[0] ?? '', 5);
    await fillBucket(page, itemId, codes[1] ?? '', 1);
    await expect(page.getByText('Conserved (6/6)')).toBeVisible();
    await saveLine(page, 1, gs.id);
    await expect(page.getByText(/G-19 Conserved: All items/)).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await submitCategorisation(page, gs.id);
    expect(aman.errors, aman.errors.join('\n')).toEqual([]);
    await aman.context.close();

    const rm = await asUser(browser, USERS.rm, `/gs/${gs.id}/rm-review`);
    await expect(rm.page.getByText(/ENCLOSED SCALE OVAL THERMOMETER/).first()).toBeVisible();
    await expect(rm.page.getByText(`${item?.allowed_buckets[0]?.field_label ?? ''}:`)).toBeVisible();
    await expectNoHorizontalOverflow(rm.page);
    expect(rm.errors, rm.errors.join('\n')).toEqual([]);
    await rm.context.close();
  });

  for (const [name, doc, recv] of [
    ['Scenario 2: partial receipt 4 of 6', 6, 4],
    ['Scenario 3: excess receipt 8 of 6', 6, 8],
  ] as const) {
    test(`${name} conserves the received qty (G-19)`, async ({ browser }) => {
      const { gs, itemIds } = await countedLines('cat-qty', [[EO, doc, recv]]);
      const itemId = itemIds[0] ?? '';
      const aman = await asUser(browser, USERS.aman, `/gs/${gs.id}/itemization`);
      const { page } = aman;
      const state = await submitCountInUi(page, gs.id);
      expectContract(state);
      await expectCategorisationLoaded(page);
      const code = state.items[0]?.allowed_buckets[0]?.field_code ?? '';

      // The documented qty is not the categorised total: mismatch, submit stays disabled.
      await fillBucket(page, itemId, code, doc);
      const diff = doc - recv;
      await expect(
        page.getByText(`Mismatch: ${String(doc)}/${String(recv)} (${diff > 0 ? '+' : ''}${String(diff)})`),
      ).toBeVisible();
      await saveLine(page, 1, gs.id);
      await expect(page.getByRole('button', { name: /Submit Categorisation/ })).toBeDisabled();

      await fillBucket(page, itemId, code, recv);
      await expect(page.getByText(`Conserved (${String(recv)}/${String(recv)})`)).toBeVisible();
      await saveLine(page, 1, gs.id);
      await submitCategorisation(page, gs.id);
      expect(aman.errors, aman.errors.join('\n')).toEqual([]);
      await aman.context.close();
    });
  }

  test('Scenario 4: multi-product GS — each line gets its own buckets and quantities', async ({
    browser,
  }) => {
    const { gs, itemIds } = await countedLines('cat-multi', [
      [EO, 6, 6],
      [DMT, 6, 4],
      [PRS, 2, 3],
    ]);
    const aman = await asUser(browser, USERS.aman, `/gs/${gs.id}/itemization`);
    const { page } = aman;
    const state = await submitCountInUi(page, gs.id);
    expectContract(state);
    await expectCategorisationLoaded(page);

    expect(state.items.map((i) => i.item_id)).toEqual(itemIds);
    expect(state.items.map((i) => i.received_qty)).toEqual([6, 4, 3]);
    const sets = state.items.map((i) => i.allowed_buckets.map((b) => b.field_code).join(','));
    expect(new Set(sets).size, 'three categories, three different bucket sets').toBe(3);

    for (const [idx, it] of state.items.entries()) {
      for (const b of it.allowed_buckets) {
        await expect(page.locator(`[id="b-${it.item_id}-${b.field_code}"]`)).toBeVisible();
      }
      await fillBucket(page, it.item_id, it.allowed_buckets[0]?.field_code ?? '', it.received_qty);
      await saveLine(page, idx + 1, gs.id);
    }
    await expect(page.getByText(/G-19 Conserved: All items/)).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await submitCategorisation(page, gs.id);
    expect(aman.errors, aman.errors.join('\n')).toEqual([]);
    await aman.context.close();
  });

  test('Scenario 5: a malformed payload shows an actionable error with retry, not a crash', async ({
    browser,
  }) => {
    const { gs } = await countedLines('cat-bad', [[EO, 6, 6]]);
    await api(USERS.aman, 'POST', `/gs/${gs.id}/counting/submit`, {}, true);
    const aman = await asUser(browser, USERS.aman, `/gs/${gs.id}/itemization`);
    const { page } = aman;
    await expectCategorisationLoaded(page);

    // Corrupt the real response: allowed_counts null / object / missing.
    const url = `**/api/v1/gs/${gs.id}/categorisation`;
    for (const bad of [null, { PACKAGING: 1 }, undefined]) {
      await page.route(url, async (route) => {
        const response = await route.fetch();
        const body = (await response.json()) as CatState;
        const items = body.items.map((i) => ({ ...i, allowed_counts: bad }));
        await route.fulfill({ response, json: { ...body, items } });
      });
      await page.reload();
      await expect(page.getByText('Item categorisation could not be loaded')).toBeVisible();
      await expect(page.getByText(/items\.0\.allowed_counts/)).toBeVisible();
      await expect(page.getByText(/is not iterable/)).toHaveCount(0);
      // The rest of the page (whole-GS options) is still usable.
      await expect(page.getByRole('button', { name: 'Categorise GS' })).toBeVisible();
      await page.unroute(url);
      await page.getByRole('button', { name: /retry/i }).click();
      await expectCategorisationLoaded(page);
    }
    // Only the deliberately injected payloads may have produced console output.
    expect(aman.errors.filter((e) => !/categorisation/i.test(e))).toEqual([]);
    await aman.context.close();
  });

  test('Scenario 6: an existing GS with saved categorisation reloads its values', async ({
    browser,
  }) => {
    const { gs, itemIds } = await countedLines('cat-existing', [[EO, 6, 6]]);
    const itemId = itemIds[0] ?? '';
    await api(USERS.aman, 'POST', `/gs/${gs.id}/counting/submit`, {}, true);
    const before = await api<CatState>(USERS.aman, 'GET', `/gs/${gs.id}/categorisation`);
    const code = before.items[0]?.allowed_buckets[0]?.field_code ?? '';
    // Saved earlier (e.g. before this fix) through the API.
    await api(
      USERS.aman,
      'PUT',
      `/gs/${gs.id}/items/${itemId}/categorisation`,
      { buckets: [{ field_code: code, qty: 6 }], counts: [] },
      true,
    );

    const aman = await asUser(browser, USERS.aman, `/gs/${gs.id}/itemization`);
    const { page } = aman;
    await expectCategorisationLoaded(page);
    await expect(page.locator(`[id="b-${itemId}-${code}"]`)).toHaveValue('6');
    await expect(page.getByText('Conserved (6/6)')).toBeVisible();
    await submitCategorisation(page, gs.id);
    expect(aman.errors, aman.errors.join('\n')).toEqual([]);
    await aman.context.close();
  });

  for (const [option, status] of [
    ['Complete Sales Return', 'CSR_APPROVAL_PENDING'],
    ['Replacement Only', 'INSPECTION'],
  ] as const) {
    test(`whole-GS option "${option}" still works after counting → ${status}`, async ({ browser }) => {
      const { gs } = await countedLines('cat-opt', [[EO, 6, 6]]);
      const aman = await asUser(browser, USERS.aman, `/gs/${gs.id}/itemization`);
      const { page } = aman;
      expectContract(await submitCountInUi(page, gs.id));
      await expectCategorisationLoaded(page);
      await page.locator('.category-option', { hasText: option }).click();
      await page.getByRole('button', { name: 'Categorise GS' }).click();
      await expect.poll(() => gsStatus(gs.id)).toBe(status);
      if (status === 'CSR_APPROVAL_PENDING') {
        await expect(page.getByText(/Waiting for the Replacement Manager/)).toBeVisible();
      }
      expect(aman.errors, aman.errors.join('\n')).toEqual([]);
      await aman.context.close();
    });
  }
});
