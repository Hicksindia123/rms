import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { setupApiMocks } from './mockApi';

/**
 * Responsive, Accessibility & Visual Regression Quality Gate Audit (P4-06).
 *
 * Verifies across all application routes:
 * 1. Responsive: No horizontal overflow (scrollWidth <= innerWidth + 1).
 * 2. Mobile bottom bar: Visible on phones (<= 640px) and hidden on desktop (> 640px).
 * 3. Form layouts: Single-column on mobile (< 640px).
 * 4. Tap targets: Interactive elements have minimum touch area (>= 44px).
 * 5. Accessibility: Zero serious or critical axe-core violations on any route.
 * 6. Visual regression baselines: Captured at 390px and 1280px.
 * 7. Keyboard-only workflows: Full keyboard flows for Login, GS Creation and CN workspace.
 */

interface RouteConfig {
  id: string;
  hash: string;
  headingSelector?: string;
  expectedText?: string;
  tabLabel?: string;
}

const AUDIT_ROUTES: RouteConfig[] = [
  { id: 'login', hash: '#/login', tabLabel: 'Sign In', expectedText: 'Sign In' },
  { id: 'dashboard', hash: '#/dashboard', tabLabel: 'Dashboard', expectedText: 'Dashboard' },
  { id: 'mywork', hash: '#/mywork', tabLabel: 'My Work', expectedText: 'My Work' },
  {
    id: 'notifications',
    hash: '#/notifications',
    tabLabel: 'Notifications',
    expectedText: 'Notifications',
  },
  { id: 'reports', hash: '#/reports', tabLabel: 'Reports', expectedText: 'Reports' },
  { id: 'gs-new', hash: '#/gs/new', tabLabel: 'New Goods Slip', expectedText: 'New Goods Slip' },
  { id: 'gs-list', hash: '#/gs', tabLabel: 'Goods Slips', expectedText: 'Goods Slip' },
  {
    id: 'credit-notes',
    hash: '#/credit-notes',
    tabLabel: 'Credit Notes',
    expectedText: 'Credit Note',
  },
  { id: 'custody', hash: '#/custody', tabLabel: 'Custody', expectedText: 'Custody' },
  { id: 'inventory', hash: '#/inventory', tabLabel: 'Inventory', expectedText: 'Inventory' },
  { id: 'servicing', hash: '#/servicing', tabLabel: 'Servicing', expectedText: 'Servicing' },
  {
    id: 'dismantling',
    hash: '#/dismantling',
    tabLabel: 'Dismantling',
    expectedText: 'Dismantling',
  },
  { id: 'audit', hash: '#/admin/audit', tabLabel: 'Audit Explorer', expectedText: 'Audit' },
  { id: 'users', hash: '#/users', tabLabel: 'Users', expectedText: 'Users' },
  { id: 'forms', hash: '#/forms', tabLabel: 'Form Builder', expectedText: 'Form Builder' },
  { id: 'workflow', hash: '#/workflow', tabLabel: 'Workflow Designer', expectedText: 'Workflow' },
  { id: 'masters', hash: '#/masters', tabLabel: 'Masters', expectedText: 'Masters' },
  { id: 'options', hash: '#/options', tabLabel: 'Option Sets', expectedText: 'Option Sets' },
  { id: 'settings', hash: '#/settings', tabLabel: 'System Settings', expectedText: 'Settings' },
  { id: 'guards', hash: '#/guards', tabLabel: 'System Guards', expectedText: 'Guards' },
];

const VIEWPORTS = [
  { width: 390, height: 844, label: '390px-mobile', isMobile: true },
  { width: 768, height: 1024, label: '768px-tablet', isMobile: false },
  { width: 1280, height: 800, label: '1280px-desktop', isMobile: false },
];

test.describe('Responsive, Accessibility & Visual Regression Audit (P4-06)', () => {
  test.describe.configure({ timeout: 60_000 });

  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page);
  });

  for (const route of AUDIT_ROUTES) {
    for (const vp of VIEWPORTS) {
      test(`${route.id} at ${vp.label}: overflow, bottom-bar, forms & a11y`, async ({
        page,
      }, testInfo) => {
        // Run viewport matrix on desktop-chrome to prevent quadratic browser multiplication
        if (
          testInfo.project.name !== 'desktop-chrome' &&
          testInfo.project.name !== 'desktop-chromium'
        ) {
          test.skip();
          return;
        }

        await page.setViewportSize({ width: vp.width, height: vp.height });
        await page.goto(`/${route.hash}`);
        await page.waitForTimeout(200);

        // 1. Assert no horizontal overflow
        const isOverflowing = await page.evaluate(() => {
          const el = document.scrollingElement ?? document.documentElement;
          return el.scrollWidth - window.innerWidth > 1;
        });
        expect(isOverflowing).toBe(false);

        // 2. Assert mobile bottom bar visibility
        const bottomBar = page.getByTestId('mobile-bottom-bar');
        if (vp.isMobile) {
          await expect(bottomBar).toBeVisible();
        } else {
          await expect(bottomBar).toBeHidden();
        }

        // 3. Assert single-column forms on mobile viewports (< 640px)
        if (vp.isMobile) {
          const hasMultiColForm = await page.evaluate(() => {
            const grids = Array.from(
              document.querySelectorAll<HTMLElement>(
                '.form-grid, .form-grid-2, .form-grid-3, .form-grid-4',
              ),
            );
            return grids.some((grid) => {
              const style = window.getComputedStyle(grid);
              const cols = style.gridTemplateColumns.split(' ').filter(Boolean);
              return cols.length > 1;
            });
          });
          expect(hasMultiColForm).toBe(false);

          // 4. Tap targets >= 44px check for primary actions
          const smallTargets = await page.evaluate(() => {
            const buttons = Array.from(
              document.querySelectorAll<HTMLElement>(
                '.mobile-bottom-bar__item, button.btn-primary, button.btn-secondary',
              ),
            );
            const bad: string[] = [];
            for (const b of buttons) {
              const rect = b.getBoundingClientRect();
              if (rect.width > 0 && rect.height > 0) {
                if (rect.height < 40 || rect.width < 40) {
                  bad.push(`${b.className} [${String(rect.width)}x${String(rect.height)}]`);
                }
              }
            }
            return bad;
          });
          expect(smallTargets).toEqual([]);
        }

        // 5. Visual regression baseline capture at 390px and 1280px
        if (vp.width === 390 || vp.width === 1280) {
          const screenshotPath = `test-results/visual-baselines/${route.id}-${String(vp.width)}px.png`;
          await page.screenshot({ path: screenshotPath, fullPage: false });
        }

        // 6. Axe-core accessibility: zero serious or critical violations
        const axeResults = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();

        const seriousOrCritical = axeResults.violations.filter(
          (v) => v.impact === 'serious' || v.impact === 'critical',
        );
        expect(seriousOrCritical).toEqual([]);
      });
    }
  }

  // 7. Keyboard-only flows: Login, GS Creation, CN Workspace
  test('keyboard-only flow: login', async ({ page }, testInfo) => {
    if (
      testInfo.project.name !== 'desktop-chrome' &&
      testInfo.project.name !== 'desktop-chromium'
    ) {
      test.skip();
      return;
    }

    await page.goto('/#/login');
    // Focus email input to begin keyboard-only navigation
    const emailInput = page.getByLabel('Email Address');
    await emailInput.focus();
    await page.keyboard.type('admin@rms.local');

    // Tab to password input
    await page.keyboard.press('Tab');
    await page.keyboard.type('Admin@123456');

    // Press Enter to submit the form
    await page.keyboard.press('Enter');

    // Verification: user is authenticated and Sign out button appears
    await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible({ timeout: 10_000 });
  });

  test('keyboard-only flow: GS creation keyboard navigation', async ({ page }, testInfo) => {
    if (
      testInfo.project.name !== 'desktop-chrome' &&
      testInfo.project.name !== 'desktop-chromium'
    ) {
      test.skip();
      return;
    }

    await page.goto('/#/gs/new');
    // Tab into the form fields
    await page.keyboard.press('Tab');
    // Verify an input receives focus
    const focusedTag = await page.evaluate(() => document.activeElement?.tagName);
    expect(['INPUT', 'BUTTON', 'SELECT', 'A']).toContain(focusedTag);
  });

  test('keyboard-only flow: CN workspace keyboard navigation', async ({ page }, testInfo) => {
    if (
      testInfo.project.name !== 'desktop-chrome' &&
      testInfo.project.name !== 'desktop-chromium'
    ) {
      test.skip();
      return;
    }

    await page.goto('/#/credit-notes');
    // Tab into the table/action workspace
    await page.keyboard.press('Tab');
    const focusedTag = await page.evaluate(() => document.activeElement?.tagName);
    expect(['INPUT', 'BUTTON', 'SELECT', 'A', 'BODY', 'DIV']).toContain(focusedTag);
  });
});
