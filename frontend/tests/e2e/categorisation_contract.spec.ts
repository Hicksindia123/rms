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
 * Regression: "e.allowed_counts is not iterable" (CLIENT_ERROR) on the Categorisation screen
 * (2026-11-16, GS/2026-27/00001, ENCLOSED SCALE OVAL THERMOMETER ITM-00180, 6 of 6). Ported in P12
 * to the DEC-64 screen: items → "Replacement" → categorisation (split editor per line, fed by
 * GET /itemization/lookups/products/{id}/fields) → Lock. Real UI against the real API, no mocks:
 * exact / partial / excess receipt, a multi-product GS and the reload of a saved split.
 */
const EO = 'ITM-00180'; // ENCLOSED_OVAL: the product of the report
const DMT = 'ITM-00165';
const PRS = 'ITM-00167';

interface Field {
  field_id: string;
  field_code: string;
  field_label: string;
  sort_order: number;
}
interface Fields {
  allowed_buckets: Field[];
  allowed_counts: Field[];
}

test.beforeEach(async ({ browserName }, testInfo) => {
  testInfo.annotations.push({ type: 'browser', description: browserName });
  test.skip(testInfo.project.name !== 'desktop-chrome', 'Real-stack contract check (one project)');
  const down = await apiAvailable();
  test.skip(down !== null, `RMS stack not available: ${down ?? ''}`);
});

/** A GS at CATEGORISATION (items counted, "Replacement" chosen) with the given lines. */
async function atCategorisation(tag: string, lines: Array<[string, number, number]>) {
  const gs = await createGs(tag);
  await unboxed(gs);
  for (const [code, doc, recv] of lines) await addItem(gs.id, await productId(code), doc, recv);
  await api(
    USERS.aman,
    'POST',
    `/gs/${gs.id}/itemization/return-choice`,
    { category_code: 'RO' },
    true,
  );
  expect(await gsStatus(gs.id)).toBe('CATEGORISATION');
  return gs;
}

function expectContract(f: Fields): void {
  expect(Array.isArray(f.allowed_buckets), 'allowed_buckets is an array').toBe(true);
  expect(Array.isArray(f.allowed_counts), 'allowed_counts is an array').toBe(true);
  for (const x of [...f.allowed_buckets, ...f.allowed_counts]) {
    expect(Object.keys(x).sort()).toEqual(['field_code', 'field_id', 'field_label', 'sort_order']);
  }
}

/** Opens "Edit line N" and returns the field payload the split editor received. */
async function openLine(page: Page, lineNo: number): Promise<Fields> {
  const res = page.waitForResponse(
    (r) => /\/itemization\/lookups\/products\/[^/]+\/fields$/.test(r.url()) && r.ok(),
  );
  await page.getByRole('button', { name: `Edit line ${String(lineNo)}` }).click();
  const fields = (await (await res).json()) as Fields;
  expectContract(fields);
  const editor = page.getByTestId('line-split-editor');
  await expect(editor).toBeVisible();
  await expect(page.getByText(/is not iterable/)).toHaveCount(0);
  await expect(page.getByText('CLIENT_ERROR')).toHaveCount(0);
  // Every bucket and count of the payload is rendered with its configured label.
  for (const f of [...fields.allowed_buckets, ...fields.allowed_counts]) {
    await expect(editor.getByLabel(f.field_label, { exact: true })).toBeVisible();
  }
  return fields;
}

async function split(page: Page, label: string, qty: number): Promise<void> {
  await page.getByTestId('line-split-editor').getByLabel(label, { exact: true }).fill(String(qty));
}

async function saveLine(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Save line' }).click();
  await expect(page.getByTestId('line-split-editor')).toHaveCount(0, { timeout: 20_000 });
}

test.describe('Categorisation (allowed_counts contract, DEC-64 screen)', () => {
  test('6 of 6 (ITM-00180) loads, splits, locks', async ({ browser }) => {
    const gs = await atCategorisation('cat-exact', [[EO, 6, 6]]);
    const aman = await asUser(browser, USERS.aman, `/gs/${gs.id}/itemization`);
    const { page } = aman;
    await expect(page.getByText(/ENCLOSED SCALE OVAL THERMOMETER/).first()).toBeVisible();
    await expect(page.getByTestId('lock-categorisation')).toBeDisabled();
    const fields = await openLine(page, 1);
    const [first, second] = fields.allowed_buckets;
    expect(second, 'ENCLOSED_OVAL offers more than one condition').toBeTruthy();
    await split(page, first?.field_label ?? '', 5);
    await expect(page.getByTestId('split-total')).toHaveText('Split 5 / Physical 6');
    await split(page, second?.field_label ?? '', 1);
    await expect(page.getByTestId('split-total')).toHaveText('Split 6 / Physical 6');
    await saveLine(page);
    await expect(page.getByTestId('lock-categorisation')).toBeEnabled();
    await expectNoHorizontalOverflow(page);
    await page.getByTestId('lock-categorisation').click();
    await page.getByTestId('lock-confirm').click();
    await expect(page.getByTestId('categorisation-locked')).toBeVisible({ timeout: 20_000 });
    await expect.poll(() => gsStatus(gs.id)).toBe('PENDING_TRANSFER_SLIP');
    expect(aman.errors, aman.errors.join('\n')).toEqual([]);
    await aman.context.close();
  });

  for (const [name, doc, recv] of [
    ['partial receipt 4 of 6', 6, 4],
    ['excess receipt 8 of 6', 6, 8],
  ] as const) {
    test(`${name}: the split must equal the physical qty (G-19)`, async ({ browser }) => {
      const gs = await atCategorisation('cat-qty', [[EO, doc, recv]]);
      const aman = await asUser(browser, USERS.aman, `/gs/${gs.id}/itemization`);
      const { page } = aman;
      const fields = await openLine(page, 1);
      const label = fields.allowed_buckets[0]?.field_label ?? '';
      // The document qty is not the categorised total.
      await split(page, label, doc);
      await expect(page.getByTestId('split-total')).toHaveText(
        `Split ${String(doc)} / Physical ${String(recv)}`,
      );
      await split(page, label, recv);
      await expect(page.getByTestId('split-total')).toHaveText(
        `Split ${String(recv)} / Physical ${String(recv)}`,
      );
      await saveLine(page);
      await expect(page.getByTestId('lock-categorisation')).toBeEnabled();
      expect(aman.errors, aman.errors.join('\n')).toEqual([]);
      await aman.context.close();
    });
  }

  test('multi-product GS: each line gets its own buckets; a saved split reloads', async ({
    browser,
  }) => {
    const gs = await atCategorisation('cat-multi', [
      [EO, 2, 2],
      [DMT, 3, 3],
      [PRS, 1, 1],
    ]);
    const aman = await asUser(browser, USERS.aman, `/gs/${gs.id}/itemization`);
    const { page } = aman;
    const qty = [2, 3, 1];
    const codes: string[][] = [];
    for (const [i, q] of qty.entries()) {
      const fields = await openLine(page, i + 1);
      codes.push(fields.allowed_buckets.map((b) => b.field_code));
      await split(page, fields.allowed_buckets[0]?.field_label ?? '', q);
      await saveLine(page);
    }
    // DMT, EO and Prismatic come with their own condition lists.
    expect(new Set(codes.map((c) => c.join(','))).size).toBe(3);
    await expect(page.getByTestId('lock-categorisation')).toBeEnabled();

    // Reload: the saved split is shown again in the editor.
    await page.reload();
    const again = await openLine(page, 2);
    await expect(
      page
        .getByTestId('line-split-editor')
        .getByLabel(again.allowed_buckets[0]?.field_label ?? '', { exact: true }),
    ).toHaveValue('3');
    await expect(page.getByTestId('split-total')).toHaveText('Split 3 / Physical 3');
    await expectNoHorizontalOverflow(page);
    expect(aman.errors, aman.errors.join('\n')).toEqual([]);
    await aman.context.close();
  });
});
