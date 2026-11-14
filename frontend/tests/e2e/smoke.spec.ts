import { expect, test } from '@playwright/test';
import { setupApiMocks } from './mockApi';

test('home page loads without console errors or horizontal scroll', async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', (err) => consoleErrors.push(err.message));

  await setupApiMocks(page);

  await page.goto('/');

  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

  const hasHorizontalScroll = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(hasHorizontalScroll).toBe(false);
  expect(consoleErrors).toEqual([]);
});
