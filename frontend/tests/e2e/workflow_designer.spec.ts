import { expect, test } from '@playwright/test';
import { setupApiMocks } from './mockApi';

test.describe('Workflow Designer & Admin Configuration UI', () => {
  test('workflow designer renders stage columns on desktop and stacked list on mobile viewport', async ({
    page,
  }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });
    page.on('pageerror', (err) => consoleErrors.push(err.message));

    await setupApiMocks(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Switch to Workflow Designer tab
    const workflowTab = page.getByRole('button', { name: 'Workflow Designer' });
    await expect(workflowTab).toBeVisible();
    await workflowTab.click();

    // Verify header and published status
    await expect(
      page.getByRole('heading', { name: /Workflow Designer: RMS Standard/i }),
    ).toBeVisible();
    await expect(page.getByText('PUBLISHED')).toBeVisible();

    // Desktop view: stage cards are visible
    await expect(page.getByText('Stage 1: Gate & Unboxing')).toBeVisible();
    await expect(page.getByText('Gate Inward & Entry')).toBeVisible();

    // Resize viewport to mobile (375x667)
    await page.setViewportSize({ width: 375, height: 667 });
    await page.waitForTimeout(300);

    // Verify stage cards are still accessible and rendered
    await expect(page.getByText('Stage 1: Gate & Unboxing')).toBeVisible();

    // Verify no horizontal overflow in mobile
    const hasHorizontalScroll = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(hasHorizontalScroll).toBe(false);
    expect(consoleErrors).toEqual([]);
  });

  test('admin can create draft, edit step details, and publish workflow version', async ({
    page,
  }) => {
    await setupApiMocks(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Go to Workflow tab
    await page.getByRole('button', { name: 'Workflow Designer' }).click();

    // Click "Create Draft v2"
    const createDraftBtn = page.getByRole('button', { name: /Create Draft v2/i });
    await expect(createDraftBtn).toBeVisible();
    await createDraftBtn.click();

    // Should now show DRAFT status and Publish Version 2 button
    await expect(page.getByText('DRAFT')).toBeVisible();
    const publishBtn = page.getByRole('button', { name: /Publish Version 2/i });
    await expect(publishBtn).toBeVisible();

    // Open Step Drawer by clicking a step
    await page.getByText('S1 Gate Inward').click();
    await expect(page.getByRole('heading', { name: /Step Details: S1_GATE/i })).toBeVisible();

    // Edit step label
    const labelInput = page.locator('input[type="text"]').first();
    await labelInput.fill('S1 Gate Inward Hub Inward');
    await page.getByRole('button', { name: /Update Step Label/i }).click();

    // Close drawer
    await page.getByRole('button', { name: '✕' }).click();

    // Click Publish Version 2
    await publishBtn.click();
    await expect(page.getByText(/Publish Workflow Version 2/i)).toBeVisible();

    // Fill version notes and confirm
    const notesInput = page.getByPlaceholder(/Reason for publishing this workflow version/i);
    await notesInput.fill('Updated step label for Gate Inward');
    await page.getByRole('button', { name: /Confirm & Publish/i }).click();

    // Should show success notification
    await expect(page.getByText(/Workflow version published successfully/i)).toBeVisible();
  });

  test('system guards page renders static G-01..G-18 with locked status', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Navigate to System Guards
    await page.getByRole('button', { name: 'System Guards' }).click();

    await expect(page.getByRole('heading', { name: /System Guards Catalogue/i })).toBeVisible();
    await expect(page.getByText('G-01', { exact: true })).toBeVisible();
    await expect(page.getByText('G-18', { exact: true })).toBeVisible();
    await expect(page.getByText(/Read-Only System Security/i)).toBeVisible();
  });

  test('number series manager displays provisional GS series banner and preview numbers', async ({
    page,
  }) => {
    await setupApiMocks(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Navigate to Numbering
    await page.getByRole('button', { name: 'Number Series' }).click();

    await expect(page.getByRole('heading', { name: /Number Series Configuration/i })).toBeVisible();
    await expect(page.getByText(/DEC-01 Provisional Goods Slip Format/i)).toBeVisible();
    await expect(page.getByText('GS-2425-00001')).toBeVisible();
    await expect(page.getByText('GS-2425-00002')).toBeVisible();
    await expect(page.getByText('GS-2425-00003')).toBeVisible();
  });

  test('system settings displays provisional business rules DEC-01..DEC-20', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Navigate to System Settings
    await page.getByRole('button', { name: 'System Settings' }).click();

    await expect(
      page.getByRole('heading', { name: /System Settings & Provisional Business Rules/i }),
    ).toBeVisible();
    await expect(page.getByText(/Business Rules \(Provisional\)/i)).toBeVisible();
    await expect(page.getByText('DEC-01: Timing of Gate Slip', { exact: false })).toBeVisible();
  });

  test('print templates manager shows live sample preview with watermark', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Navigate to Print Templates
    await page.getByRole('button', { name: 'Print Templates' }).click();

    await expect(
      page.getByRole('heading', { name: /Print Templates & Document Layout Designer/i }),
    ).toBeVisible();
    await expect(page.getByText(/SAMPLE PREVIEW \(NO DATA PERSISTED\)/i)).toBeVisible();
    await expect(
      page.getByRole('heading', { name: 'REPLACEMENT SLIP', exact: true }),
    ).toBeVisible();
  });

  test('config history viewer displays change logs and diffs', async ({ page }) => {
    await setupApiMocks(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Navigate to Config History
    await page.getByRole('button', { name: 'Config History' }).click();

    await expect(
      page.getByRole('heading', { name: /Configuration Change History/i }),
    ).toBeVisible();
    await expect(page.getByText(/Published RMS_STANDARD workflow v1/i)).toBeVisible();
    await expect(page.getByText('WORKFLOW_DEFINITION')).toBeVisible();
  });
});
