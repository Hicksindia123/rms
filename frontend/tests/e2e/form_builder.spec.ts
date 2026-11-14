import { expect, test } from '@playwright/test';
import { setupApiMocks } from './mockApi';

test.describe('RMS Form Builder & Dynamic Form UI Smoke', () => {
  test('navigates between Form Builder and Option Sets with clean rendering', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });
    page.on('pageerror', (err) => consoleErrors.push(err.message));

    await setupApiMocks(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Check App title
    await expect(
      page.getByRole('heading', { level: 1, name: /Replacement Management System/i }),
    ).toBeVisible();

    // Check tabs
    const formsTab = page.getByRole('button', { name: /^Form Builder/i });
    const optionsTab = page.getByRole('button', { name: /^Option Sets/i });

    await expect(formsTab).toBeVisible();
    await expect(optionsTab).toBeVisible();

    // Switch to Option Sets
    await optionsTab.click();
    await expect(
      page.getByRole('heading', { name: /Option Sets & Dropdown Catalogue/i }),
    ).toBeVisible();

    // Switch back to Form Builder
    await formsTab.click();
    await expect(
      page.getByRole('heading', { name: /Form Builder & Version Manager/i }),
    ).toBeVisible();

    // Verify no horizontal overflow on page
    const hasHorizontalScroll = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(hasHorizontalScroll).toBe(false);
  });

  test('toggles between desktop and mobile 360px preview and tests conditional visibility', async ({
    page,
  }) => {
    await setupApiMocks(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Wait until Form Builder loads the published form
    await expect(page.locator('#form-select')).toBeVisible();

    // Switch to Live Preview
    const previewTabButton = page.getByRole('button', { name: 'Live Preview', exact: true });
    await expect(previewTabButton).toBeVisible();
    await previewTabButton.click();

    await expect(page.getByRole('heading', { name: /Live Form Preview/i })).toBeVisible();

    // Switch to Mobile 360px preview
    const mobileBtn = page.getByRole('button', { name: 'Mobile (360px)', exact: true });
    await expect(mobileBtn).toBeVisible();
    await mobileBtn.click();

    // Check that mobile preview container is rendered
    const mobileFrame = page.locator('.mobile-preview-frame');
    await expect(mobileFrame).toBeVisible();

    // Test conditional interaction inside the preview:
    // Select DIRECT_TRUCK from dropdown
    const deliveryModeSelect = mobileFrame.locator('select#field-delivery_mode');
    await expect(deliveryModeSelect).toBeVisible();
    await deliveryModeSelect.selectOption('DIRECT_TRUCK');

    // Conditional vehicle_no field should appear
    const vehicleInput = mobileFrame.locator('input#field-vehicle_no');
    await expect(vehicleInput).toBeVisible();

    // Switch back to Desktop Full
    const desktopBtn = page.getByRole('button', { name: 'Desktop Full', exact: true });
    await expect(desktopBtn).toBeVisible();
    await desktopBtn.click();
    await expect(page.locator('.dynamic-form')).toBeVisible();
  });
});
