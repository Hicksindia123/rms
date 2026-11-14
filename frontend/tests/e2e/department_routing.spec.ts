/**
 * Change plan 2026-11-12 · Phase 6 (AMD-10, AMD-14, AMD-15; DEC-42; G-20) — screen check.
 *
 * Real stack (API on :8000, Vite dev server). The RM opens the department routing queue and the
 * receiving role (DEC-42 default INWARD_VERIFIER) opens the receiving queue. Each screen must show
 * its success / empty / error state, raise no console errors and never scroll horizontally
 * (CLAUDE.md rule h), on desktop and on phones (Pixel 7 project + an explicit 360 px viewport).
 */
import { expect, test } from '@playwright/test';

import { apiAvailable, asUser, expectNoHorizontalOverflow, USERS } from './support/stack';

const PROJECTS = ['desktop-chrome', 'mobile-pixel-7'];

const SCREENS = [
  {
    name: 'RM department routing queue',
    user: USERS.rm,
    path: '/department-routing',
    heading: /RM Department Routing Queue/i,
  },
  {
    name: 'department receiving queue',
    user: USERS.aman,
    path: '/department-receiving',
    heading: /Department Receiving Queue/i,
  },
] as const;

test.describe('Phase 6 department routing screens', () => {
  test.beforeEach(async () => {
    test.skip(!PROJECTS.includes(test.info().project.name), 'desktop-chrome + mobile-pixel-7');
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  for (const screenDef of SCREENS) {
    test(`${screenDef.name} renders cleanly`, async ({ browser }) => {
      const { context, page, errors } = await asUser(browser, screenDef.user, screenDef.path);
      try {
        await expect(page.getByRole('heading', { name: screenDef.heading })).toBeVisible({
          timeout: 15_000,
        });
        // One of: list loaded, empty state, or error with retry — never a stuck spinner.
        await expect(page.getByText(/^Loading /)).toHaveCount(0, { timeout: 15_000 });
        await expectNoHorizontalOverflow(page);

        // Strict phone width from CLAUDE.md rule h.
        await page.setViewportSize({ width: 360, height: 780 });
        await expect(page.getByRole('heading', { name: screenDef.heading })).toBeVisible();
        await expectNoHorizontalOverflow(page);

        expect(errors, 'no console errors').toEqual([]);
      } finally {
        await context.close();
      }
    });
  }
});
