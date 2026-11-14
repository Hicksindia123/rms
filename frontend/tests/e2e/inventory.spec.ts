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
 * P3-04 · custody segregation views against the REAL local stack (BR-30, G-04, G-12):
 * one GS is walked to functional custody (Sahil) and non-functional custody (Spare Parts
 * Manager); the inventory views, stock card, custody assignment, a count adjustment and the
 * segregation check are checked at desktop (1280) and phone (360) widths. No horizontal overflow,
 * axe serious/critical = 0, touch targets ≥ 44 px, no console errors. Screenshots: test-results/p3-04.
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

async function touchTargets(page: Page) {
  const small = await page.evaluate(() =>
    [...document.querySelectorAll('main button, main select, main input, main textarea')]
      .filter((el) => (el as HTMLElement).offsetParent !== null)
      // A radio / checkbox is tapped through its wrapping label row.
      .map((el) =>
        el instanceof HTMLInputElement && (el.type === 'checkbox' || el.type === 'radio')
          ? (el.closest('label') ?? el)
          : el,
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
  await page.screenshot({ path: `test-results/p3-04/${label}-${name}.png`, fullPage: true });
}

/** GS → inspection (4 good, 2 broken body) → RM plan → handover accepted → direct classification. */
async function segregatedGs(tag: string): Promise<{ id: string; gs_no: string }> {
  const gs = await createGs(tag);
  await unboxed(gs);
  const dmt = await addItem(gs.id, await productId('DEMO-DMT-001'), 6, 6);
  await categorize(gs.id, 'RO');
  await inspectByApi(dmt, { DMT_OK_PACKED: 4, DMT_BROKEN_BODY: 2 });
  await api(USERS.rm, 'PUT', `/gs/${gs.id}/rm-actions`, {
    lines: [
      {
        gs_item_id: dmt,
        actions: [
          { action_code: 'SEND_NEW', qty: 4 },
          { action_code: 'NOT_ALLOWED', qty: 2 },
        ],
      },
    ],
  });
  await api(USERS.rm, 'POST', `/gs/${gs.id}/rm-actions/finalise`, {});
  const transfer = await api<Transfer>(
    USERS.aman,
    'POST',
    `/gs/${gs.id}/handover`,
    { mode_code: 'PHYSICAL_AND_DIGITAL' },
    true,
  );
  await api(
    USERS.sahil,
    'POST',
    `/custody/transfers/${transfer.id}/accept`,
    {
      lines: transfer.lines.map((l) => ({ lot_id: l.lot_id, qty_counted: l.qty_sent })),
      acceptance_code: 'ACCEPTED_VERIFIED',
    },
    true,
  );
  // DEC-14: the sellable lot is classified Functional Good directly in the store.
  for (const line of transfer.lines) {
    await api(
      USERS.sahil,
      'POST',
      `/custody/lots/${line.lot_id}/classify`,
      { qty: line.qty_sent },
      true,
    );
  }
  return gs;
}

test.describe('Inventory segregation views (P3-04)', () => {
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
    test(`functional, non-functional, stock card, assignment, adjustment, check at ${vp.label}`, async ({
      browser,
    }) => {
      test.setTimeout(150_000);
      const gs = await segregatedGs(`P304${vp.label[0] ?? ''}`);
      const open = async (email: string, path: string) => {
        const d = await asUser(browser, email, path);
        await d.page.setViewportSize({ width: vp.width, height: vp.height });
        devices.push(d);
        return d.page;
      };
      const search = async (page: Page, view: string) => {
        await page.getByLabel('Search GS / product').fill(gs.gs_no);
        await page.getByRole('button', { name: 'Apply' }).click();
        await expect(page.getByText(/1 lot\b/)).toBeVisible();
        await expect(page.locator(`section[aria-label="${view}"]`)).toBeVisible();
      };

      // 1. Sahil: functional inventory with the DD r63 routing text; no spare parts ledger tab.
      const sahil = await open(USERS.sahil, '/inventory/functional');
      await search(sahil, 'Functional Inventory');
      await expect(
        sahil
          .getByText('Stage for Store Issue or Customer Dispatch')
          .filter({ visible: true })
          .first(),
      ).toBeVisible();
      await expect(sahil.getByRole('tab', { name: 'Spare Parts Ledger' })).toHaveCount(0);
      await check(sahil, 'functional', vp.label);

      // 2. Stock card: the path from GS inward through handover and classification.
      await sahil
        .getByRole('button', { name: new RegExp(`Open stock card: .*${gs.gs_no}`) })
        .filter({ visible: true })
        .first()
        .click();
      const drawer = sahil.getByRole('dialog', { name: /Stock card/ });
      await expect(drawer.getByText('Inward').first()).toBeVisible();
      await expect(drawer.getByText('Transfer out').first()).toBeVisible();
      await expect(drawer.getByText('Transfer in').first()).toBeVisible();
      await expect(drawer.getByText('Reclassify').first()).toBeVisible();
      await check(sahil, 'stock-card', vp.label);

      // 3. Count difference reported from the stock card (custodian), approved by the RM.
      await drawer.getByRole('button', { name: 'Report count difference' }).click();
      await sahil.getByLabel('Physically counted').fill('3');
      await sahil.getByLabel(/Reason/).fill(`Cycle count ${gs.gs_no}: one piece missing`);
      // The submit button just became enabled: let its opacity transition finish before axe.
      await expect(sahil.getByRole('button', { name: 'Send for approval' })).toHaveCSS(
        'opacity',
        '1',
      );
      await check(sahil, 'adjustment-request', vp.label);
      await sahil.getByRole('button', { name: 'Send for approval' }).click();
      await expect(sahil.getByText(/Sent for approval/)).toBeVisible();
      await sahil.getByRole('button', { name: 'Done' }).click();
      await sahil.keyboard.press('Escape');

      const rm = await open(USERS.rm, '/inventory/adjustments');
      const row = rm
        .getByText(`Cycle count ${gs.gs_no}: one piece missing`)
        .filter({ visible: true })
        .first();
      await expect(row).toBeVisible();
      await check(rm, 'adjustments', vp.label);
      await rm
        .locator('tr, li', { hasText: `Cycle count ${gs.gs_no}: one piece missing` })
        .filter({ visible: true })
        .first()
        .getByRole('button', { name: 'Approve' })
        .click();
      await rm.getByRole('dialog').getByRole('button', { name: 'Approve' }).click();
      await expect(rm.getByRole('dialog')).toHaveCount(0);

      // 4. Spare Parts Manager: the broken-body pieces are in non-functional custody; the only
      //    assignment offered is DD r65 and it records "already in place".
      const spm = await open(USERS.spm, '/inventory/non-functional');
      await search(spm, 'Non-Functional');
      await check(spm, 'non-functional', vp.label);
      await spm
        .getByRole('button', { name: new RegExp(`Open stock card: .*${gs.gs_no}`) })
        .filter({ visible: true })
        .first()
        .click();
      await spm.getByRole('button', { name: 'Custody assignment' }).click();
      const dialog = spm.getByRole('dialog', { name: 'Custody assignment' });
      await expect(dialog.getByRole('radio')).toHaveCount(1);
      await check(spm, 'assign', vp.label);
      await dialog.getByRole('button', { name: 'Assign' }).click();
      await expect(dialog.getByRole('status')).toContainText('already with the right custodian');
      await dialog.getByRole('button', { name: 'Done' }).click();
      await spm.keyboard.press('Escape');

      await spm.goto('/#/inventory/spare-parts');
      await expect(spm.getByRole('tab', { name: 'Spare Parts Ledger' })).toBeVisible();
      await check(spm, 'spare-parts', vp.label);

      // 5. Segregation check: the custody boundary is intact.
      await spm.goto('/#/inventory/segregation');
      await expect(spm.getByText('No segregation violations')).toBeVisible();
      await expect(spm.getByRole('button', { name: 'Run check now' })).toHaveCSS('opacity', '1');
      await check(spm, 'segregation', vp.label);

      // The adjustment is posted (4 → 3 in the Intermediate Store).
      await sahil.goto('/#/inventory/functional');
      await search(sahil, 'Functional Inventory');
      await expect(sahil.getByText(/3\s*pieces/).filter({ visible: true })).toBeVisible();
    });
  }
});
