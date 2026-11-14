import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

import {
  addItem,
  api,
  apiAvailable,
  asUser,
  categorize,
  createGs,
  type Device,
  expectNoHorizontalOverflow,
  inspectByApi,
  productId,
  unboxed,
  USERS,
} from './support/stack';

/**
 * P3-01 · custody screens at desktop (1280) and phone (360) widths against the REAL local stack:
 * handover (eligible + held back), receive / discrepancy / reconciliation, transfers list,
 * Intermediate Store stock, Transfer Note. No horizontal overflow, axe serious/critical = 0,
 * touch targets ≥ 44 px, no console errors. Screenshots: test-results/p3-01.
 */
const WIDTHS = [
  { label: 'desktop', width: 1280, height: 900 },
  { label: 'phone', width: 360, height: 780 },
];

interface Transfer {
  id: string;
  lines: Array<{ lot_id: string; qty_sent: number }>;
}

async function axeClean(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();
  const serious = results.violations.filter(
    (v) => v.impact === 'serious' || v.impact === 'critical',
  );
  expect(serious.map((v) => `${v.id}: ${v.nodes[0]?.target.join(' ') ?? ''}`)).toEqual([]);
}

/** CLAUDE.md rule h: interactive controls in main are at least 44 px tall on phones. */
async function touchTargets(page: Page) {
  const small = await page.evaluate(() =>
    [...document.querySelectorAll('main button, main select, main input, main textarea')]
      .filter((el) => (el as HTMLElement).offsetParent !== null)
      // A checkbox is tapped through its wrapping label.
      .map((el) =>
        el instanceof HTMLInputElement && el.type === 'checkbox' ? (el.closest('label') ?? el) : el,
      )
      .filter((el) => el.getBoundingClientRect().height < 44)
      .map(
        (el) =>
          `${el.tagName}:${el.textContent.trim().slice(0, 30) || (el.getAttribute('aria-label') ?? el.id)}`,
      ),
  );
  expect(small).toEqual([]);
}

async function check(page: Page, name: string, label: string) {
  // axe measures colours: let enable/disable transitions (.btn opacity) finish first.
  await page.waitForFunction(() =>
    document.getAnimations().every((a) => a.playState !== 'running'),
  );
  await expectNoHorizontalOverflow(page);
  await axeClean(page);
  if (label === 'phone') await touchTargets(page);
  await page.screenshot({ path: `test-results/p3-01/${label}-${name}.png`, fullPage: true });
}

async function inProcessGs(tag: string): Promise<{ id: string; gs_no: string }> {
  const gs = await createGs(tag);
  await unboxed(gs);
  const dmt = await addItem(gs.id, await productId('DEMO-DMT-001'), 8, 8);
  await categorize(gs.id, 'RO');
  await inspectByApi(dmt, { DMT_OK_PACKED: 5, DMT_DIRTY: 2, DMT_OTHER_BRANDS: 1 });
  await api(USERS.rm, 'PUT', `/gs/${gs.id}/rm-actions`, {
    lines: [
      {
        gs_item_id: dmt,
        actions: [
          { action_code: 'SEND_NEW', qty: 5 },
          { action_code: 'NOT_ALLOWED', qty: 1 },
          { action_code: 'PENDING_BP', qty: 2 },
        ],
      },
    ],
    pendency_details: {
      [dmt]: { reason: 'Display flicker, Repair Team check', sent_to: 'Repair Team' },
    },
  });
  await api(USERS.rm, 'POST', `/gs/${gs.id}/rm-actions/finalise`, {});
  return gs;
}

test.describe('Custody screens responsive (P3-01)', () => {
  const devices: Device[] = [];
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(
      testInfo.project.name !== 'desktop-chrome' && testInfo.project.name !== 'desktop-chromium',
      'Viewports are set explicitly',
    );
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });
  test.afterEach(async () => {
    for (const d of devices.splice(0)) {
      expect(d.errors, `console errors on ${d.page.url()}`).toEqual([]);
      await d.context.close();
    }
  });

  for (const vp of WIDTHS) {
    test(`handover, receive, reconcile, store and note at ${vp.label}`, async ({ browser }) => {
      test.setTimeout(120_000);
      const { id: gsId, gs_no: gsNo } = await inProcessGs(`P301V${vp.label[0] ?? ''}`);
      const open = async (email: string, path: string) => {
        const d = await asUser(browser, email, path);
        await d.page.setViewportSize({ width: vp.width, height: vp.height });
        devices.push(d);
        return d.page;
      };

      const aman = await open(USERS.aman, `/gs/${gsId}/handover`);
      await expect(aman.getByText('Pending (BP)')).toBeVisible();
      await expect(aman.getByText(/Display flicker/)).toBeVisible();
      await check(aman, 'handover', vp.label);

      const transfer = await api<Transfer>(
        USERS.aman,
        'POST',
        `/gs/${gsId}/handover`,
        { mode_code: 'PHYSICAL_AND_DIGITAL' },
        true,
      );
      const sahil = await open(USERS.sahil, `/custody/transfers/${transfer.id}`);
      await expect(sahil.getByRole('button', { name: /Accepted - Quantity/ })).toBeVisible();
      await check(sahil, 'receive', vp.label);

      const first = transfer.lines[0];
      await api(
        USERS.sahil,
        'POST',
        `/custody/transfers/${transfer.id}/accept`,
        {
          lines: transfer.lines.map((l) => ({
            lot_id: l.lot_id,
            qty_counted: l.lot_id === first?.lot_id ? l.qty_sent - 1 : l.qty_sent,
          })),
          acceptance_code: 'DISCREPANCY',
          notes: 'One piece short',
        },
        true,
      );
      await api(
        USERS.aman,
        'POST',
        `/custody/transfers/${transfer.id}/reconcile`,
        { resolution_code: 'CANCEL_RETURN', notes: 'Recount and resend' },
        true,
      );
      await sahil.reload();
      await expect(sahil.getByText(/frozen in transit/)).toBeVisible();
      await expect(sahil.getByRole('button', { name: /Sign as receiver/ })).toBeVisible();
      await check(sahil, 'reconcile', vp.label);

      const rm = await open(USERS.rm, `/custody/transfers/${transfer.id}`);
      await expect(rm.getByRole('button', { name: /RM override/ })).toBeVisible();
      await check(rm, 'rm-override', vp.label);

      // Sahil co-signs → reconciled; Aman re-sends; Sahil accepts the clean resend.
      await api(
        USERS.sahil,
        'POST',
        `/custody/transfers/${transfer.id}/reconcile`,
        { resolution_code: 'CANCEL_RETURN', notes: 'Agreed' },
        true,
      );
      const clean = await api<Transfer>(
        USERS.aman,
        'POST',
        `/gs/${gsId}/handover`,
        { mode_code: 'PHYSICAL_AND_DIGITAL' },
        true,
      );
      await api(
        USERS.sahil,
        'POST',
        `/custody/transfers/${clean.id}/accept`,
        {
          lines: clean.lines.map((l) => ({ lot_id: l.lot_id, qty_counted: l.qty_sent })),
          acceptance_code: 'ACCEPTED_VERIFIED',
        },
        true,
      );

      await sahil.goto('/#/custody');
      await expect(sahil.getByRole('tab', { name: 'Transfers' })).toBeVisible();
      await expect(sahil.getByText(/TRF\//).filter({ visible: true }).first()).toBeVisible();
      await check(sahil, 'transfers', vp.label);

      await sahil.goto('/#/custody/store');
      // Scope to this test's GS: the other viewport's run works in the same Intermediate Store.
      await sahil.getByLabel('Search GS / product').fill(gsNo);
      await sahil.getByRole('button', { name: 'Search', exact: true }).click();
      await expect(sahil.getByText(`${gsNo} · `).first()).toBeVisible();
      await expect(
        sahil.getByRole('button', { name: /Classify Functional Good/ }).first(),
      ).toBeVisible();
      await sahil.getByLabel('Group by').selectOption('routing');
      await check(sahil, 'store', vp.label);
      await sahil
        .getByRole('button', { name: /Classify Functional Good/ })
        .first()
        .click();
      await expect(sahil.getByRole('dialog')).toBeVisible();
      await sahil.getByRole('button', { name: /Classify \d+ as Functional Good/ }).click();
      await expect(sahil.getByRole('dialog')).toBeHidden();
      await expect(sahil.getByText('Classified').first()).toBeVisible();

      await sahil.goto(`/#/custody/transfers/${clean.id}/note`);
      await expect(sahil.getByText('CUSTODY TRANSFER NOTE')).toBeVisible();
      await check(sahil, 'transfer-note', vp.label);
    });
  }
});
