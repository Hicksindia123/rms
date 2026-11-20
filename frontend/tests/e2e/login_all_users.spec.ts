import { expect, test } from '@playwright/test';

interface TestUser {
  email: string;
  name: string;
  roleTitle: string;
  isSuperAdmin: boolean;
  roleCode: string;
}

const ALL_TEST_USERS: TestUser[] = [
  {
    email: 'admin@rms.local',
    name: 'RMS Super Admin',
    roleTitle: 'Super Admin',
    isSuperAdmin: true,
    roleCode: 'SUPER_ADMIN',
  },
  {
    email: 'anuj@rms.local',
    name: 'Anuj',
    roleTitle: 'Gate Inward',
    isSuperAdmin: false,
    roleCode: 'GATE_INWARD',
  },
  {
    email: 'aman@rms.local',
    name: 'Aman',
    roleTitle: 'Inward Verifier',
    isSuperAdmin: false,
    roleCode: 'INWARD_VERIFIER',
  },
  {
    email: 'pratham@rms.local',
    name: 'Pratham Pratap Singh',
    roleTitle: 'Replacement Manager',
    isSuperAdmin: false,
    roleCode: 'REPLACEMENT_MANAGER',
  },
  {
    email: 'sahil@rms.local',
    name: 'Sahil',
    roleTitle: 'Intermediate Store Manager',
    isSuperAdmin: false,
    roleCode: 'INTERMEDIATE_STORE_MANAGER',
  },
  {
    email: 'deepak@rms.local',
    name: 'Deepak Ji',
    roleTitle: 'Accounts',
    isSuperAdmin: false,
    roleCode: 'ACCOUNTS',
  },
  {
    email: 'rajkumar@rms.local',
    name: 'Raj Kumar Ji',
    roleTitle: 'Technician',
    isSuperAdmin: false,
    roleCode: 'TECHNICIAN',
  },
  {
    email: 'spt@rms.local',
    name: 'Spare Parts Technician',
    roleTitle: 'Spare Parts Technician',
    isSuperAdmin: false,
    roleCode: 'SPARE_PARTS_TECHNICIAN',
  },
  {
    email: 'spm@rms.local',
    name: 'Spare Parts Manager',
    roleTitle: 'Spare Parts Manager',
    isSuperAdmin: false,
    roleCode: 'SPARE_PARTS_MANAGER',
  },
  {
    email: 'dispatch@rms.local',
    name: 'Dispatch Team',
    roleTitle: 'Dispatch',
    isSuperAdmin: false,
    roleCode: 'DISPATCH',
  },
  {
    email: 'mainstore@rms.local',
    name: 'Main Store Manager',
    roleTitle: 'Main Store',
    isSuperAdmin: false,
    roleCode: 'MAIN_STORE',
  },
  {
    email: 'management@rms.local',
    name: 'Management Viewer',
    roleTitle: 'Management Viewer',
    isSuperAdmin: false,
    roleCode: 'MANAGEMENT_VIEWER',
  },
  // Phase P1 20-11-2026: Intermediate Store users (DEC-61) and Management (DEC-60).
  {
    email: 'opstore@rms.local',
    name: 'Intermediate Store OP User',
    roleTitle: 'Intermediate Store OP',
    isSuperAdmin: false,
    roleCode: 'ISTORE_OP',
  },
  {
    email: 'dtstore@rms.local',
    name: 'Intermediate Store DT User',
    roleTitle: 'Intermediate Store DT',
    isSuperAdmin: false,
    roleCode: 'ISTORE_DT',
  },
  {
    email: 'ristore@rms.local',
    name: 'Intermediate Store RI User',
    roleTitle: 'Intermediate Store RI',
    isSuperAdmin: false,
    roleCode: 'ISTORE_RI',
  },
  {
    email: 'mgmt@rms.local',
    name: 'Management Approver',
    roleTitle: 'Management',
    isSuperAdmin: false,
    roleCode: 'MANAGEMENT',
  },
];

for (const user of ALL_TEST_USERS) {
  test(`E2E sign-in flow for ${user.name} (${user.email})`, async ({ page }) => {
    // Intercept Supabase Auth token request
    await page.route('**/auth/v1/token?grant_type=password', async (route) => {
      const postData = route.request().postDataJSON() as { email?: string; password?: string };
      expect(postData.email).toBe(user.email);
      expect(postData.password).toBe('Uat@2026RMS!');

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: `mock-token-${user.email}`,
          token_type: 'bearer',
          expires_in: 3600,
          refresh_token: `mock-refresh-${user.email}`,
          user: {
            id: '00000000-0000-0000-0000-000000000001',
            aud: 'authenticated',
            role: 'authenticated',
            email: user.email,
            created_at: new Date().toISOString(),
          },
        }),
      });
    });

    // Intercept API endpoints
    await page.route('**/api/v1/**', async (route) => {
      const url = route.request().url();
      if (url.includes('/container-audits/today')) {
        // Today's DMT container audit already confirmed: no banner (P2-06).
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            day: { confirmed: true },
            containers: [],
            checkbox_label: '',
            can_edit: false,
            can_confirm: false,
          }),
        });
      } else if (url.includes('/tasks/mine')) {
        // My Work task list (empty for a fresh sign-in).
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ items: [], total: 0 }),
        });
      } else if (url.includes('/me/journey')) {
        // Phase 10 (AMD-22): My Work is the landing page and renders the journey.
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ entries: [], hidden_features: [] }),
        });
      } else if (url.endsWith('/me') || url.includes('/me?')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            profile: {
              id: '00000000-0000-0000-0000-000000000001',
              email: user.email,
              full_name: user.name,
              is_super_admin: user.isSuperAdmin,
              department: 'Testing',
            },
            roles: [
              {
                id: 'role-1',
                code: user.roleCode,
                name: user.roleTitle,
              },
            ],
            permissions: [
              { module_code: 'dashboards', action: 'view' },
              { module_code: 'goods_slips', action: 'view' },
            ],
          }),
        });
      } else if (url.includes('/notifications')) {
        await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
      } else if (url.includes('/dashboards')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ kpis: [], charts: [] }),
        });
      } else {
        await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
      }
    });

    // Navigate to sign-in page
    await page.goto('/');

    // Verify presence of Hicks brand and RMS header
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    // Fill credentials
    const emailInput = page.locator('#login-email');
    const pwdInput = page.locator('#login-password');
    await emailInput.fill(user.email);
    await pwdInput.fill('Uat@2026RMS!');

    // Test password show/hide toggle
    const toggleBtn = page.locator('.rms-pwd-toggle');
    await expect(pwdInput).toHaveAttribute('type', 'password');
    await toggleBtn.click();
    await expect(pwdInput).toHaveAttribute('type', 'text');
    await toggleBtn.click();
    await expect(pwdInput).toHaveAttribute('type', 'password');

    // Click Sign In
    const submitBtn = page.getByRole('button', { name: 'Sign in', exact: true });
    await submitBtn.click();

    // Verify successful login transition into the app
    // The topbar user profile should display the logged-in user's name
    // Phones show only the avatar in the top bar, so the visible signal is the Sign out button
    // (as in support/stack.ts); the user's name is still rendered in the profile pill.
    await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible({ timeout: 10000 });
    await expect(page.locator('.saas-profile-pill')).toContainText(user.name);
  });
}
