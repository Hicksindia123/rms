import { expect, test } from '@playwright/test';

import {
  api,
  apiAvailable,
  asUser,
  expectNoHorizontalOverflow,
  FIXTURES,
  gateBody,
  gsStatus,
  USERS,
  type Gs,
} from './support/stack';

/**
 * Phase P3 (docs/RMS_PHASE_PROMPTS_20-11-2026.md; DEC-62, DEC-63) against the REAL local stack:
 * Step 2a on a 2-carton GS at 360 px (phone) and 1280 px (desktop): one video per carton through the
 * carton picker, the one optional "document found in carton" through the camera input, Next disabled
 * → enabled → item addition. No console errors, no horizontal scroll, touch targets ≥ 44 px.
 * Runs on the desktop Chrome project and sets each width itself.
 */
const WIDTHS = [
  { name: 'phone-360', width: 360, height: 780 },
  { name: 'desktop-1280', width: 1280, height: 900 },
];

async function twoCartonGs(tag: string): Promise<Gs> {
  const parties = await api<Array<{ id: string }>>(
    USERS.gate,
    'GET',
    '/gs/lookups/parties?limit=5',
  );
  const body = gateBody(parties[0]?.id, tag, 'NO_DOCUMENT');
  const values = { ...(body.values as Record<string, unknown>), carton_count: 2 };
  const res = await api<{ goods_slip: Gs }>(USERS.gate, 'POST', '/gs', { ...body, values }, true);
  return res.goods_slip;
}

test.describe('P3 unboxing: video per carton + optional carton document', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(testInfo.project.name !== 'desktop-chrome', 'Sets 360 / 1280 px widths itself');
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  for (const vp of WIDTHS) {
    test(`Next only after every carton video, at ${vp.name}`, async ({ browser }) => {
      test.setTimeout(150_000);
      const gs = await twoCartonGs(`P3${String(vp.width)}`);
      const { context, page, errors } = await asUser(browser, USERS.aman, `/gs/${gs.id}/unboxing`);
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await expect(page.getByRole('heading', { name: gs.gs_no })).toBeVisible();
      await page.getByRole('button', { name: /^Start / }).click();

      const checklist = page.getByTestId('checklist');
      const next = page.getByTestId('unboxing-next');
      await expect(checklist).toContainText('Carton videos 0 of 2');
      await expect(next).toBeDisabled();
      await expect(page.getByTestId('no-party-documents')).toBeVisible();
      await expectNoHorizontalOverflow(page);

      // Carton 1 (selected first), then the picker moves on to carton 2.
      await page.getByTestId('video-file-input').setInputFiles({
        name: 'carton-1.mp4',
        mimeType: 'video/mp4',
        buffer: FIXTURES.VIDEO,
      });
      await expect(checklist).toContainText('Carton videos 1 of 2', { timeout: 30_000 });
      await expect(checklist).toContainText('carton 2 missing');
      await expect(next).toBeDisabled();
      await expect(page.getByTestId('missing-list')).toContainText('carton 2');
      await expect(page.getByTestId('record-video')).toContainText('carton 2');
      await page.getByTestId('video-file-input').setInputFiles({
        name: 'carton-2.mp4',
        mimeType: 'video/mp4',
        buffer: FIXTURES.VIDEO,
      });
      await expect(checklist).toContainText('Video ✔', { timeout: 30_000 });
      await expect(page.getByTestId('evidence-video')).toHaveCount(2);
      await expect(next).toBeEnabled();

      // Optional carton document: type + photo from the camera input (capture=environment).
      const camera = page.getByTestId('carton-doc-camera-input');
      await expect(camera).toHaveAttribute('capture', 'environment');
      await expect(camera).toHaveAttribute('accept', 'image/*');
      await expect(page.locator('#carton-doc-type option')).toHaveText([
        '-- Select document type --',
        'Invoice',
        'GST Debit Note',
        'Hand Written Slip',
      ]);
      const save = page.getByRole('button', { name: /Save document/ });
      await expect(save).toBeDisabled();
      await page.locator('#carton-doc-type').selectOption('HANDWRITTEN_SLIP');
      await camera.setInputFiles({ name: 'slip.png', mimeType: 'image/png', buffer: FIXTURES.PNG });
      await expect(save).toBeEnabled();
      for (const target of [next, save, page.getByTestId('record-video')]) {
        const box = await target.boundingBox();
        expect(box?.height ?? 0, 'touch target ≥ 44 px').toBeGreaterThanOrEqual(44);
      }
      await save.click();
      await expect(page.getByTestId('carton-document')).toContainText('Hand Written Slip', {
        timeout: 30_000,
      });
      await expect(page.getByTestId('carton-document')).toContainText('File 1');
      await expect(checklist).toContainText('added');
      await expectNoHorizontalOverflow(page);
      await page.screenshot({
        path: `test-results/p3/${vp.name}-unboxing-ready.png`,
        fullPage: true,
      });

      await next.click();
      await expect(page).toHaveURL(new RegExp(`/gs/${gs.id}/itemization`));
      await expect.poll(() => gsStatus(gs.id)).toBe('ITEMIZATION');
      await expectNoHorizontalOverflow(page);
      expect(errors).toEqual([]);
      await context.close();
    });
  }
});
