import { expect, test } from '@playwright/test';

import {
  addItem,
  api,
  apiAvailable,
  asUser,
  createGs,
  expectNoHorizontalOverflow,
  gsStatus,
  unboxed,
  USERS,
} from './support/stack';

/**
 * Phase P4 (docs/RMS_PHASE_PROMPTS_20-11-2026.md; DEC-64) against the REAL local stack, at 360 px
 * (phone) and 1280 px (desktop). The Replacement Executive: item lines (qty only) → Next → popup
 * "Replacement" → categorisation (split per line, G-19) → Lock (stock booked). Then Management
 * corrects a locked line with a reason. No console errors, no horizontal scroll, touch targets
 * ≥ 44 px. Runs on the desktop Chrome project and sets each width itself.
 */
const MGMT = 'mgmt@rms.local';
const WIDTHS = [
  { name: 'phone-360', width: 360, height: 780 },
  { name: 'desktop-1280', width: 1280, height: 900 },
];

/** A product whose item field profile offers condition buckets. */
async function splittableProduct(): Promise<{ id: string; bucket: string; label: string }> {
  const rows = await api<Array<{ id: string }>>(
    USERS.aman,
    'GET',
    '/itemization/lookups/products?q=&limit=20',
  );
  for (const r of rows) {
    const fields = await api<{
      allowed_buckets: Array<{ field_code: string; field_label: string }>;
    }>(USERS.aman, 'GET', `/itemization/lookups/products/${r.id}/fields`);
    const first = fields.allowed_buckets[0];
    if (first) return { id: r.id, bucket: first.field_code, label: first.field_label };
  }
  throw new Error('no product with condition buckets');
}

async function touchTarget(page: import('@playwright/test').Page, testId: string): Promise<void> {
  const box = await page.getByTestId(testId).boundingBox();
  expect(box?.height ?? 0, `${testId} is a ≥ 44 px touch target`).toBeGreaterThanOrEqual(44);
}

test.describe('P4 items → popup → categorisation → lock', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(testInfo.project.name !== 'desktop-chrome', 'Sets 360 / 1280 px widths itself');
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  for (const vp of WIDTHS) {
    test(`Replacement Executive locks, Management corrects, at ${vp.name}`, async ({ browser }) => {
      test.setTimeout(180_000);
      const gs = await createGs(`P4${String(vp.width)}`);
      await unboxed(gs);
      const product = await splittableProduct();
      await addItem(gs.id, product.id, 5, 4);

      // Items (quantities only) → Next → popup.
      const re = await asUser(browser, USERS.aman, `/gs/${gs.id}/itemization`);
      await re.page.setViewportSize({ width: vp.width, height: vp.height });
      await expect(re.page.getByText(gs.gs_no)).toBeVisible();
      await expect(re.page.getByTestId('line-split-editor')).toHaveCount(0);
      await expectNoHorizontalOverflow(re.page);
      await touchTarget(re.page, 'items-next');
      await re.page.getByTestId('items-next').click();
      const dialog = re.page.getByRole('dialog');
      await expect(dialog).toContainText('Replacement');
      await expect(dialog).toContainText('Complete Sales Return');
      await expect(re.page.getByTestId('return-choice-confirm')).toBeDisabled();
      await dialog.getByLabel('Replacement', { exact: true }).check();
      await re.page.getByTestId('return-choice-confirm').click();
      await expect.poll(() => gsStatus(gs.id)).toBe('CATEGORISATION');

      // Categorisation: split the line; Lock stays disabled until G-19 holds.
      await expect(re.page.getByTestId('lock-categorisation')).toBeDisabled();
      await re.page.getByRole('button', { name: 'Edit line 1' }).click();
      const editor = re.page.getByTestId('line-split-editor');
      await editor.getByLabel(product.label, { exact: true }).fill('4');
      await expect(re.page.getByTestId('split-total')).toHaveText('Split 4 / Physical 4');
      await re.page.getByRole('button', { name: 'Save line' }).click();
      await expect(re.page.getByTestId('lock-categorisation')).toBeEnabled();
      await expectNoHorizontalOverflow(re.page);
      await re.page.getByTestId('lock-categorisation').click();
      await touchTarget(re.page, 'lock-confirm');
      await re.page.getByTestId('lock-confirm').click();
      await expect(re.page.getByTestId('categorisation-locked')).toBeVisible();
      await expect.poll(() => gsStatus(gs.id)).toBe('PENDING_TRANSFER_SLIP');
      await expect(re.page.getByRole('button', { name: /Edit line 1/ })).toHaveCount(0);
      await re.page.screenshot({ path: `test-results/p4/${vp.name}-locked.png`, fullPage: true });
      expect(re.errors).toEqual([]);
      await re.context.close();

      // Management corrects the locked line (reason required).
      const mg = await asUser(browser, MGMT, `/gs/${gs.id}/itemization`);
      await mg.page.setViewportSize({ width: vp.width, height: vp.height });
      await mg.page.getByRole('button', { name: /Change line 1/ }).click();
      await mg.page.getByTestId('line-editor').locator('input[id$="-received"]').fill('3');
      await mg.page
        .getByTestId('line-split-editor')
        .getByLabel(product.label, { exact: true })
        .fill('3');
      const save = mg.page.getByRole('button', { name: 'Save line' });
      await expect(save).toBeDisabled(); // reason missing
      await mg.page.getByLabel('Reason for the change (required)').fill('Recounted: 3 pieces');
      await expect(save).toBeEnabled();
      await save.click();
      await expect(mg.page.getByText('Physically received').first()).toBeVisible();
      await expect
        .poll(async () => {
          const st = await api<{ items: Array<{ received_qty: number }> }>(
            MGMT,
            'GET',
            `/gs/${gs.id}/itemization`,
          );
          return st.items[0]?.received_qty;
        })
        .toBe(3);
      await expectNoHorizontalOverflow(mg.page);
      await mg.page.screenshot({
        path: `test-results/p4/${vp.name}-mgmt-edit.png`,
        fullPage: true,
      });
      expect(mg.errors).toEqual([]);
      await mg.context.close();
    });
  }
});
