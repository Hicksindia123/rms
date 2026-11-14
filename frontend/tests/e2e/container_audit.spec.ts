import { expect, test } from '@playwright/test';

/**
 * P2-06 Daily DMT Container Audit - Playwright mobile test (390px viewport).
 * Verifies mobile-first layout: container steppers, quick barcode filter,
 * mandatory checkbox, and audit confirmation.
 */

test.use({
  viewport: { width: 390, height: 844 },
});

test.describe('Daily DMT Container Audit Mobile Register (P2-06, BR-18, DEC-08)', () => {
  test('enters container counts, toggles confirmation checkbox, and confirms on 390px mobile viewport', async ({
    page,
  }) => {
    let isConfirmed = false;
    const counts: Record<string, number> = {
      'c-1': 10,
      'c-2': 12,
      'c-3': 8,
      'c-4': 14,
    };

    // Inject active Supabase session into localStorage before loading page
    await page.addInitScript(() => {
      const session = {
        access_token: 'fake-jwt',
        token_type: 'bearer',
        expires_at: Math.floor(Date.now() / 1000) + 3600,
        expires_in: 3600,
        refresh_token: 'fake-refresh',
        user: {
          id: 'u-aman',
          aud: 'authenticated',
          role: 'authenticated',
          email: 'aman@example.com',
          app_metadata: { provider: 'email' },
          user_metadata: {},
          created_at: new Date().toISOString(),
        },
      };
      window.localStorage.setItem('sb-127-auth-token', JSON.stringify(session));
      window.localStorage.setItem('sb-127.0.0.1-auth-token', JSON.stringify(session));
      window.localStorage.setItem('supabase.auth.token', JSON.stringify(session));
    });

    // Mock Supabase Auth network requests
    await page.route('**/auth/v1/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'u-aman',
          aud: 'authenticated',
          role: 'authenticated',
          email: 'aman@example.com',
        }),
      });
    });

    // Mock RMS /api/v1/me
    await page.route('**/api/v1/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          profile: {
            id: 'u-aman',
            email: 'aman@example.com',
            full_name: 'Aman (Inward Verifier)',
            is_super_admin: false,
          },
          roles: [{ code: 'INWARD_VERIFIER', name: 'Inward Verifier' }],
          permissions: [
            { module_code: 'container_audit', action: 'view', scope: 'ALL' },
            { module_code: 'container_audit', action: 'edit', scope: 'ALL' },
          ],
          step_codes: ['S1_INSPECT'],
        }),
      });
    });

    // Mock /api/v1/notifications/unread-count or bell
    await page.route('**/api/v1/notifications/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], unread_count: 0 }),
      });
    });

    // Mock /container-audits/today
    await page.route('**/api/v1/container-audits/today', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          day: {
            id: 'day-today',
            audit_date: new Date().toISOString().split('T')[0],
            status: isConfirmed ? 'CONFIRMED' : 'PENDING',
            is_late: false,
            late_reason: null,
            confirmed: isConfirmed,
            confirmed_by: isConfirmed ? 'u-aman' : null,
            confirmed_by_name: isConfirmed ? 'Aman' : null,
            confirmed_at: isConfirmed ? new Date().toISOString() : null,
            remarks: null,
            created_at: new Date().toISOString(),
          },
          containers: [
            {
              id: 'l-1',
              container_id: 'c-1',
              container_code: 'DMT-BIN-01',
              container_barcode: 'DMT-BIN-01',
              container_name: 'DMT Return Bin 01',
              counted_qty: counts['c-1'] ?? 0,
              sellable_packaging_qty: 2,
              remarks: '',
              yesterday_counted_qty: 12,
              yesterday_sellable_packaging_qty: 3,
            },
            {
              id: 'l-2',
              container_id: 'c-2',
              container_code: 'DMT-BIN-02',
              container_barcode: 'DMT-BIN-02',
              container_name: 'DMT Return Bin 02',
              counted_qty: counts['c-2'] ?? 0,
              sellable_packaging_qty: 1,
              remarks: '',
              yesterday_counted_qty: 15,
              yesterday_sellable_packaging_qty: 2,
            },
            {
              id: 'l-3',
              container_id: 'c-3',
              container_code: 'DMT-BIN-03',
              container_barcode: 'DMT-BIN-03',
              container_name: 'DMT Return Bin 03',
              counted_qty: counts['c-3'] ?? 0,
              sellable_packaging_qty: 0,
              remarks: '',
              yesterday_counted_qty: 8,
              yesterday_sellable_packaging_qty: 0,
            },
            {
              id: 'l-4',
              container_id: 'c-4',
              container_code: 'DMT-BIN-04',
              container_barcode: 'DMT-BIN-04',
              container_name: 'DMT Return Bin 04',
              counted_qty: counts['c-4'] ?? 0,
              sellable_packaging_qty: 4,
              remarks: '',
              yesterday_counted_qty: 10,
              yesterday_sellable_packaging_qty: 1,
            },
          ],
          checkbox_label: 'Containers Checked & Counted Daily',
          can_edit: true,
          can_confirm: !isConfirmed,
        }),
      });
    });

    await page.route('**/api/v1/container-audits/*/confirm', async (route) => {
      isConfirmed = true;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          day: {
            id: 'day-today',
            audit_date: new Date().toISOString().split('T')[0],
            status: 'CONFIRMED',
            is_late: false,
            late_reason: null,
            confirmed: true,
            confirmed_by: 'u-aman',
            confirmed_by_name: 'Aman',
            confirmed_at: new Date().toISOString(),
            remarks: null,
            created_at: new Date().toISOString(),
          },
          containers: [],
          checkbox_label: 'Containers Checked & Counted Daily',
          can_edit: false,
          can_confirm: false,
        }),
      });
    });

    // Navigate to container audit page
    await page.goto('/#/container-audit');
    await page.waitForLoadState('networkidle');

    // Verify Title and Subtitle
    await expect(
      page.getByRole('heading', { level: 1, name: /Daily DMT Container Register/i }),
    ).toBeVisible();

    // Verify all active containers rendered
    await expect(page.getByRole('heading', { name: 'DMT-BIN-01' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'DMT-BIN-02' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'DMT-BIN-03' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'DMT-BIN-04' })).toBeVisible();

    // Test barcode search filter
    const searchInput = page.getByPlaceholder(/Scan or enter container barcode/i);
    await searchInput.fill('DMT-BIN-02');
    await expect(page.getByRole('heading', { name: 'DMT-BIN-02' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'DMT-BIN-01' })).not.toBeVisible();

    // Clear search filter
    await page.getByRole('button', { name: 'Clear' }).click();
    await expect(page.getByRole('heading', { name: 'DMT-BIN-01' })).toBeVisible();

    // Test stepper button
    const incBtn = page.getByRole('button', { name: /Increase count for DMT-BIN-01/i });
    await incBtn.click();

    // Verify confirm checkbox
    const confirmCheckbox = page.getByRole('checkbox', {
      name: /Containers Checked & Counted Daily/i,
    });
    await expect(confirmCheckbox).toBeVisible();
    await confirmCheckbox.check();

    // Click submit
    const submitBtn = page.getByRole('button', { name: /Confirm Daily Audit/i });
    await expect(submitBtn).toBeEnabled();
    await submitBtn.click();

    // Verify audit confirmed message
    await expect(page.getByText(/Daily container audit confirmed successfully!/i)).toBeVisible();
  });
});
