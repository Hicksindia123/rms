/**
 * P1-05 user administration on the real stack (production audit B10): an admin creates a user on
 * a desktop, the new user must set their own password, and roles are edited on a phone.
 * Needs the API on :8000 and local Supabase (scripts/dev.ps1); passwords from
 * RMS_DEMO_PASSWORD / RMS_ADMIN_PASSWORD like the other real-stack specs.
 */
import { expect, test } from '@playwright/test';

import {
  api,
  apiAvailable,
  asUser,
  expectNoHorizontalOverflow,
  USERS,
  type Device,
} from './support/stack';

interface AdminUser {
  id: string;
  email: string;
  roles: Array<{ code: string }>;
}

const stamp = `${Date.now().toString(36)}${Math.floor(Math.random() * 1000).toString(36)}`;
const created: string[] = [];
const devices: Device[] = [];

test.beforeEach(async () => {
  const reason = await apiAvailable();
  test.skip(reason !== null, reason ?? '');
});

test.afterAll(async () => {
  for (const d of devices) await d.context.close();
  // Leave no active test accounts behind.
  for (const id of created) {
    await api(USERS.admin, 'POST', `/admin/users/${id}/deactivate`, {
      reason: 'e2e cleanup',
    }).catch((err: unknown) => {
      console.warn('cleanup failed', id, err);
    });
  }
});

test('admin creates a user who then sets their own password (desktop)', async ({
  browser,
}, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chrome', 'desktop flow');
  const admin = await asUser(browser, USERS.admin, '/users');
  devices.push(admin);
  const { page } = admin;
  const email = `e2e.${stamp}@example.test`;

  await page.getByRole('button', { name: 'Add user' }).click();
  await page.locator('#user-full-name').fill(`E2E User ${stamp}`);
  await page.locator('#user-email').fill(email);
  await page.locator('#role-GATE_INWARD').check();
  const initial = await page.locator('#user-initial-password').inputValue();
  await page.getByRole('button', { name: 'Create user' }).click();
  await expect(page.getByText(`Added E2E User ${stamp}`)).toBeVisible({ timeout: 15_000 });

  const list = await api<{ items: AdminUser[] }>(
    USERS.admin,
    'GET',
    `/admin/users?search=${encodeURIComponent(email)}`,
  );
  const user = list.items[0];
  expect(user?.roles.map((r) => r.code)).toEqual(['GATE_INWARD']);
  if (user) created.push(user.id);

  // The new user signs in with the initial password and must replace it first.
  const context = await browser.newContext();
  const fresh = await context.newPage();
  await fresh.goto('/');
  await fresh.getByLabel('Email').fill(email);
  await fresh.getByLabel('Password', { exact: true }).fill(initial);
  await fresh.getByRole('button', { name: 'Sign in' }).click();
  await expect(fresh.getByRole('heading', { name: 'Set a new password' })).toBeVisible({
    timeout: 15_000,
  });
  await fresh.locator('#new-password').fill(`E2e${stamp}x9`);
  await fresh.locator('#confirm-password').fill(`E2e${stamp}x9`);
  await fresh.getByRole('button', { name: 'Save password' }).click();
  await expect(fresh.getByRole('button', { name: 'Sign out' })).toBeVisible({ timeout: 15_000 });
  await context.close();
  expect(admin.errors, 'no console errors').toEqual([]);
});

test('admin edits roles on a phone', async ({ browser }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile-pixel-7', 'phone flow');
  const email = `e2e.m.${stamp}@example.test`;
  const user = await api<AdminUser>(USERS.admin, 'POST', '/admin/users', {
    email,
    full_name: `E2E Mobile ${stamp}`,
    role_codes: ['GATE_INWARD'],
    is_super_admin: false,
    initial_password: `Start${stamp}1`,
    must_change_password: true,
  });
  created.push(user.id);

  const admin = await asUser(browser, USERS.admin, '/users');
  devices.push(admin);
  const { page } = admin;
  await page.locator('#user-search').fill(email);
  await page.locator('#user-search').press('Enter');
  await page.getByRole('button', { name: 'Manage' }).first().click();
  await page.locator('#role-DISPATCH').check();
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByText(`Saved E2E Mobile ${stamp}.`)).toBeVisible({ timeout: 15_000 });
  await expectNoHorizontalOverflow(page);

  const after = await api<AdminUser>(USERS.admin, 'GET', `/admin/users/${user.id}`);
  expect(after.roles.map((r) => r.code).sort()).toEqual(['DISPATCH', 'GATE_INWARD']);
  expect(admin.errors, 'no console errors').toEqual([]);
});
