import { expect, test, type Locator, type Page } from '@playwright/test';

import {
  addItem,
  api,
  ApiError,
  apiAvailable,
  asUser,
  categorize,
  createGs,
  type Device,
  expectNoHorizontalOverflow,
  FIXTURES,
  GATE_PROJECTS,
  gsStatus,
  inspectByApi,
  productId,
  runWorkerJob,
  shot,
  unboxed,
  USERS,
} from './support/stack';

/**
 * P2-08 · Phase 2 gate: end-to-end inward scenarios E2E-01 … E2E-07 against the REAL local stack.
 * Each runs on desktop Chrome and on the Pixel 7 project, as the demo users, on fresh data created
 * through the API (preconditions) and the UI (the steps under test). No SQL into business tables.
 *
 * Needs: `supabase start`, demo users (backend/scripts/seed_demo_users.py), the API on :8000.
 */

interface ConditionOption {
  code: string;
  label: string;
  allowed_status: string;
}
interface InspectionState {
  status: string;
  lines: Array<{
    gs_item_id: string;
    line_no: number;
    short_qty: number;
    condition_options: ConditionOption[];
  }>;
}
interface RmState {
  options: Array<{ code: string; label: string }>;
  has_open_pendency: boolean;
  current_revision_no: number;
}

const devices: Device[] = [];

test.describe('Phase 2 gate scenarios (P2-08)', () => {
  test.beforeEach(async ({ browserName }, testInfo) => {
    testInfo.annotations.push({ type: 'browser', description: browserName });
    test.skip(
      !GATE_PROJECTS.includes(testInfo.project.name),
      'P2-08 gate scenarios run on desktop-chromium and mobile-pixel-7',
    );
    const reason = await apiAvailable();
    test.skip(reason !== null, reason ?? '');
  });

  test.afterEach(async () => {
    const opened = devices.splice(0);
    for (const d of opened) {
      expect(d.errors, `console errors on ${d.page.url()}`).toEqual([]);
      await d.context.close();
    }
  });

  async function open(
    browser: Parameters<typeof asUser>[0],
    email: string,
    path: string,
  ): Promise<Page> {
    const d = await asUser(browser, email, path);
    devices.push(d);
    return d.page;
  }

  const lineCard = (page: Page, lineNo: number): Locator =>
    page.locator(`[data-testid="inspection-line"][data-line-no="${String(lineNo)}"]`);

  /** Grade one inspection line in the UI and finalise it. Keys are option CODES (rule e). */
  async function gradeInUi(
    page: Page,
    lineNo: number,
    options: ConditionOption[],
    allocations: Record<string, number>,
    opts: { fullOpening?: boolean; container?: number; received: number } = { received: 0 },
  ) {
    const card = lineCard(page, lineNo);
    await card.scrollIntoViewIfNeeded();
    if (opts.fullOpening) {
      const first = options[0];
      if (first) {
        // Grading is locked until the full opening is confirmed (G-06 / BR-14).
        await expect(card.getByLabel(`${first.label} quantity`, { exact: true })).toBeDisabled();
      }
      await card.getByLabel('Confirm Enclosed Oval full opening').check();
    }
    for (const [code, qty] of Object.entries(allocations)) {
      const opt = options.find((o) => o.code === code);
      if (!opt) throw new Error(`condition ${code} not offered on line ${String(lineNo)}`);
      await card.getByLabel(`${opt.label} quantity`, { exact: true }).fill(String(qty));
      if (opt.allowed_status !== 'YES') {
        const dialog = page.getByRole('dialog');
        await expect(dialog).toContainText(opt.label);
        await dialog.getByRole('button', { name: 'Confirm Allocation' }).click();
        await expect(dialog).toBeHidden();
      }
      await expect(card.getByLabel(`${opt.label} quantity`, { exact: true })).toHaveValue(
        String(qty),
      );
    }
    if (opts.container) {
      await card.getByLabel('Packaging Qty (pieces)').fill(String(opts.received - opts.container));
      await card.getByLabel('Container Qty (pieces)').fill(String(opts.container));
    }
    await card.getByRole('button', { name: 'Finalise Line' }).click();
    await expect(card).toContainText('Finalised', { timeout: 15_000 });
  }

  async function rmAllocate(page: Page, lineNo: number, label: string, clicks: number) {
    const card = page.locator(`[data-testid="rm-line"][data-line-no="${String(lineNo)}"]`);
    const plus = card.getByRole('button', { name: `Increase ${label}`, exact: true });
    for (let i = 0; i < clicks; i++) await plus.click();
  }

  // --- E2E-01 -----------------------------------------------------------------------------------
  test('E2E-01 RO: DMT (8 conditions), Prismatic (3), EO (4, full opening) → RM review → slip printed', async ({
    browser,
  }) => {
    test.setTimeout(240_000);
    const gs = await createGs('E2E01');
    await unboxed(gs);
    const [dmt, prs, eo] = await Promise.all([
      productId('DEMO-DMT-001'),
      productId('DEMO-PRS-001'),
      productId('DEMO-EO-001'),
    ]);
    await addItem(gs.id, dmt, 7, 7);
    await addItem(gs.id, dmt, 6, 5); // short by one (DEC-09)
    await addItem(gs.id, prs, 3, 3);
    await addItem(gs.id, eo, 4, 4);
    await categorize(gs.id, 'RO');
    const state = await api<InspectionState>(USERS.aman, 'GET', `/gs/${gs.id}/inspection`);
    const opts = (n: number) => state.lines.find((l) => l.line_no === n)?.condition_options ?? [];
    // Every DMT (8), Prismatic (3) and EO (4) condition of the catalogue is used below.
    expect([opts(1).length, opts(3).length, opts(4).length]).toEqual([8, 3, 4]);

    // Aman grades on his device.
    const aman = await open(browser, USERS.aman, `/gs/${gs.id}/inspection`);
    await expect(aman.getByText(/Visual Inspection & Extraction Reconciliation/i)).toBeVisible();
    await gradeInUi(
      aman,
      1,
      opts(1),
      { DMT_OK_PACKED: 2, DMT_OK_PKG_DAMAGED: 2, DMT_OTHER_BRANDS: 1, DMT_SCRATCHED: 2 },
      { received: 7, container: 2 },
    );
    await gradeInUi(
      aman,
      2,
      opts(2),
      { DMT_DIRTY: 2, DMT_BROKEN_BODY: 1, DMT_DISPLAY_ISSUE: 2, DMT_SHORT_QTY: 1 },
      { received: 5 },
    );
    await gradeInUi(
      aman,
      3,
      opts(3),
      { PRS_OK: 1, PRS_BULB_BROKEN_NO_HG: 1, PRS_BROKEN_WITH_HG: 1 },
      { received: 3 },
    );
    await expect(lineCard(aman, 3)).toContainText(/MERCURY HAZARD/i);
    await gradeInUi(
      aman,
      4,
      opts(4),
      {
        EO_OK: 1,
        EO_INNER_CAPILLARY_BROKEN: 1,
        EO_BODY_BROKEN_HG: 1,
        EO_BULB_BROKEN_NO_HG: 1,
      },
      { received: 4, fullOpening: true },
    );
    await expectNoHorizontalOverflow(aman);
    await shot(aman, 'e2e01-inspection-finalised');
    await expect.poll(() => gsStatus(gs.id)).toBe('RM_REVIEW');

    // Pratham (RM) reviews item-wise; not-allowed quantities are locked from inspection.
    const rm = await open(browser, USERS.rm, `/gs/${gs.id}/rm-actions`);
    await expect(rm.getByRole('heading', { name: 'RM Item Segregation' })).toBeVisible();
    const rmState = await api<RmState>(USERS.rm, 'GET', `/gs/${gs.id}/rm-actions`);
    const label = (code: string) => rmState.options.find((o) => o.code === code)?.label ?? code;
    await expect(rm.getByText(/Locked: 1 rejected at inspection/).first()).toBeVisible();
    await rmAllocate(rm, 1, label('SEND_NEW'), 6);
    await rmAllocate(rm, 2, label('SEND_REPAIRED'), 4);
    await rmAllocate(rm, 3, label('ISSUE_CN'), 1);
    await rmAllocate(rm, 4, label('SEND_NEW'), 2);
    await expect(rm.getByText(/All Lines Fully/)).toBeVisible();
    await expectNoHorizontalOverflow(rm);
    await rm.getByRole('button', { name: 'Finalise & Advance' }).click();
    await expect(rm.getByText(/RM Actions finalised/)).toBeVisible({ timeout: 15_000 });
    await expect.poll(() => gsStatus(gs.id)).toBe('IN_PROCESS');

    // Replacement Slip: printed from the RM screen; the header comes from the print template.
    await rm.getByRole('button', { name: 'Print Replacement Slip' }).click();
    await expect(rm.getByRole('button', { name: /Print \/ Save as PDF/ })).toBeVisible();
    const sheet = rm.locator('.replacement-slip-sheet');
    await expect(sheet).toContainText(gs.gs_no);
    await expect(sheet.locator('h1')).not.toHaveText('');
    await rm.evaluate(() => {
      const w = window as unknown as { __printed: number; print: () => void };
      w.__printed = 0;
      w.print = () => {
        w.__printed += 1;
      };
    });
    await rm.getByRole('button', { name: /Print \/ Save as PDF/ }).click();
    expect(await rm.evaluate(() => (window as unknown as { __printed: number }).__printed)).toBe(1);
    await shot(rm, 'e2e01-replacement-slip');
    // Every slip view is logged (print_logs); opening it again is a numbered reprint.
    await rm.reload();
    await expect(rm.getByText(/Reprint #\d+/)).toBeVisible();
  });

  // --- E2E-02 -----------------------------------------------------------------------------------
  test('E2E-02 CSR → RM approved → custody transfer initiated', async ({ browser }) => {
    test.setTimeout(150_000);
    const gs = await createGs('E2E02');
    await unboxed(gs);
    await addItem(gs.id, await productId('DEMO-DMT-001'), 5, 5);

    const aman = await open(browser, USERS.aman, `/gs/${gs.id}/itemization`);
    await aman.locator('.category-option', { hasText: 'Complete Sales Return' }).click();
    await aman.getByRole('button', { name: 'Categorise GS' }).click();
    await expect(aman.getByText(/Waiting for the Replacement Manager/)).toBeVisible();
    await expectNoHorizontalOverflow(aman);

    const rm = await open(browser, USERS.rm, '/approvals');
    const card = rm.getByTestId('csr-card').filter({ hasText: gs.gs_no });
    await expect(card).toBeVisible();
    await card.getByLabel(/Remarks/).fill('All items, full quantity (E2E-02)');
    await card.getByRole('button', { name: /^Approved/ }).click();
    await expect(card).toBeHidden();
    await expectNoHorizontalOverflow(rm);

    await rm.goto(`/#/gs/${gs.id}/itemization`);
    const transfer = rm.getByTestId('transfer-card');
    await expect(transfer).toContainText('Initiated');
    await expect(transfer).toContainText('With packaging');
    await expect(transfer).toContainText('Inward Staging → Intermediate Store');
    await expect(transfer).toContainText('awaiting handover');
    await shot(rm, 'e2e02-transfer-initiated');
    expect(await gsStatus(gs.id)).toBe('IN_PROCESS');
  });

  // --- E2E-03 -----------------------------------------------------------------------------------
  test('E2E-03 CSR → RM rejected → converted to RO → inspection', async ({ browser }) => {
    test.setTimeout(150_000);
    const gs = await createGs('E2E03');
    await unboxed(gs);
    await addItem(gs.id, await productId('DEMO-DMT-001'), 4, 4);
    await categorize(gs.id, 'CSR');
    expect(await gsStatus(gs.id)).toBe('CSR_APPROVAL_PENDING');

    const rm = await open(browser, USERS.rm, '/approvals');
    const card = rm.getByTestId('csr-card').filter({ hasText: gs.gs_no });
    await card.getByLabel(/Remarks/).fill('Mixed condition, not a complete return (E2E-03)');
    await card.getByRole('button', { name: /^Rejected/ }).click();
    await expect(card).toBeHidden();
    await expect.poll(() => gsStatus(gs.id)).toBe('INSPECTION');
    const detail = await api<{ goods_slip: { category_code: string } }>(
      USERS.rm,
      'GET',
      `/gs/${gs.id}`,
    );
    expect(detail.goods_slip.category_code).toBe('RO');

    const aman = await open(browser, USERS.aman, `/gs/${gs.id}/inspection`);
    const state = await api<InspectionState>(USERS.aman, 'GET', `/gs/${gs.id}/inspection`);
    await gradeInUi(
      aman,
      1,
      state.lines[0]?.condition_options ?? [],
      { DMT_OK_PACKED: 4 },
      {
        received: 4,
      },
    );
    await expectNoHorizontalOverflow(aman);
    await expect.poll(() => gsStatus(gs.id)).toBe('RM_REVIEW');
  });

  // --- E2E-04 -----------------------------------------------------------------------------------
  test('E2E-04 NO_DOCUMENT gate → Step-2 blocked → missing-doc exception approved → continue', async ({
    browser,
  }) => {
    test.setTimeout(180_000);
    // Anuj creates the GS at the gate (UI), choosing "No Document Attached" (BR-03).
    const gate = await open(browser, USERS.gate, '/gs/new');
    await expect(gate.getByRole('heading', { name: 'New Goods Slip' })).toBeVisible();
    // Form v2 (AMD-01/06): E-Commerce return → State → Station → Distributor.
    await gate.getByTestId('return-type-ECOMMERCE_RETURN').click();
    await gate.locator('#field-state').selectOption({ label: 'Uttar Pradesh' });
    await gate.locator('#field-station').selectOption({ label: 'Agra' });
    await gate.locator('#field-party_name input').fill('Demo Party One');
    await gate.getByRole('option', { name: /Demo Party One/ }).click();
    await gate.locator('#field-carton_count').fill('1');
    await gate.locator('#field-delivery_mode').selectOption('COURIER_PARCEL');
    await gate.locator('#field-courier_name').fill('DTDC');
    await gate.locator('#field-docket_no').fill(`E2E04-${String(Date.now())}`);
    await gate.getByLabel('No Document Attached').check();
    await expect(gate.getByTestId('no-document-warning')).toBeVisible();
    await gate.getByLabel('Missing documentation warning acknowledged').check();
    await expectNoHorizontalOverflow(gate);
    await gate.getByRole('button', { name: 'Create Goods Slip' }).click();
    const gsNo = ((await gate.getByTestId('created-gs-no').textContent()) ?? '').trim();
    expect(gsNo).not.toBe('');
    const listed = await api<{ items: Array<{ id: string; gs_no: string }> }>(
      USERS.aman,
      'GET',
      `/gs?q=${encodeURIComponent(gsNo)}`,
    );
    const gsId = listed.items.find((g) => g.gs_no === gsNo)?.id ?? '';
    expect(gsId).not.toBe('');

    // Aman: video recorded, but without a document photo Step-2 cannot complete (G-02).
    const aman = await open(browser, USERS.aman, `/gs/${gsId}/unboxing`);
    await aman.getByRole('button', { name: 'Start carton opening' }).click();
    await aman.getByTestId('video-file-input').setInputFiles({
      name: 'unboxing.mp4',
      mimeType: 'video/mp4',
      buffer: FIXTURES.VIDEO,
    });
    const checklist = aman.getByTestId('checklist');
    await expect(checklist).toContainText('Video ✔', { timeout: 30_000 });
    await expect(checklist).toContainText('exception needed');
    await expect(aman.getByRole('button', { name: 'Complete carton opening' })).toBeDisabled();
    const blocked = await api(USERS.aman, 'POST', `/gs/${gsId}/unboxing/complete`, {}).catch(
      (e: unknown) => e,
    );
    expect(blocked).toBeInstanceOf(ApiError);
    expect((blocked as ApiError).body.error?.code).toBe('G-02');

    // DEC-03: parcel photo + remark → exception request.
    await aman.getByTestId('parcel-photo-file-input').setInputFiles({
      name: 'box.png',
      mimeType: 'image/png',
      buffer: FIXTURES.PNG,
    });
    await expect(aman.locator('.parcel-option')).toHaveCount(1, { timeout: 30_000 });
    await aman.locator('#exception-remark').fill('No papers inside the box; label photographed');
    await aman.getByRole('button', { name: 'Request Missing Document Exception' }).click();
    await expect(aman.getByTestId('exception-status')).toContainText('requested');
    await expect(aman.getByRole('button', { name: 'Complete carton opening' })).toBeDisabled();

    // Pratham approves the exception.
    const rm = await open(browser, USERS.rm, '/approvals');
    const card = rm.getByTestId('exception-card').filter({ hasText: gsNo });
    await expect(card).toBeVisible();
    await card.getByRole('button', { name: 'Approve exception' }).click();
    await expect(card).toBeHidden();

    // Aman continues.
    await aman.reload();
    await expect(aman.getByTestId('exception-status')).toContainText('approved');
    await expect(checklist).toContainText('Documents ✔');
    await aman.getByRole('button', { name: 'Complete carton opening' }).click();
    await expect(aman.getByTestId('unboxing-complete')).toContainText('itemization');
    await expectNoHorizontalOverflow(aman);
    expect(await gsStatus(gsId)).toBe('ITEMIZATION');
  });

  // --- E2E-05 -----------------------------------------------------------------------------------
  test('E2E-05 short quantity GS: shortage recorded, only received pieces processed', async ({
    browser,
  }) => {
    test.setTimeout(150_000);
    const gs = await createGs('E2E05');
    await unboxed(gs);

    const aman = await open(browser, USERS.aman, `/gs/${gs.id}/itemization`);
    const editor = aman.getByTestId('line-editor').last();
    await editor.getByRole('combobox').or(editor.locator('input').first()).first().fill('Demo DMT');
    await aman
      .getByRole('option', { name: /Demo DMT/ })
      .first()
      .click();
    await editor.getByRole('spinbutton', { name: 'As per document' }).fill('10');
    await editor.getByRole('spinbutton', { name: 'Physically received' }).fill('8');
    await editor.getByRole('button', { name: 'Add line' }).click();
    await expect(aman.getByTestId('item-line')).toHaveCount(1);
    await expect(aman.getByTestId('item-line').first()).toContainText('Short 2');
    await aman.locator('.category-option', { hasText: 'Replacement Only' }).click();
    await aman.getByRole('button', { name: 'Categorise GS' }).click();
    await expect.poll(() => gsStatus(gs.id)).toBe('INSPECTION');
    await expect(aman.getByTestId('lot-row').first()).toContainText('Inward Staging: 8');
    await expectNoHorizontalOverflow(aman);

    await aman.goto(`/#/gs/${gs.id}/inspection`);
    const card = lineCard(aman, 1);
    await expect(card).toContainText('Short: 2');
    const state = await api<InspectionState>(USERS.aman, 'GET', `/gs/${gs.id}/inspection`);
    expect(state.lines[0]?.short_qty).toBe(2);
    await gradeInUi(
      aman,
      1,
      state.lines[0]?.condition_options ?? [],
      { DMT_OK_PACKED: 8, DMT_SHORT_QTY: 2 },
      { received: 8 },
    );
    await expect.poll(() => gsStatus(gs.id)).toBe('RM_REVIEW');
    await shot(aman, 'e2e05-short-qty');
  });

  // --- E2E-06 -----------------------------------------------------------------------------------
  test('E2E-06 Pending (BP): RM opens a pendency, register lists it, RM clears it', async ({
    browser,
  }) => {
    test.setTimeout(150_000);
    const gs = await createGs('E2E06');
    await unboxed(gs);
    const item = await addItem(gs.id, await productId('DEMO-DMT-001'), 10, 10);
    await categorize(gs.id, 'RO');
    await inspectByApi(item, { DMT_OK_PACKED: 10 });

    const rm = await open(browser, USERS.rm, `/gs/${gs.id}/rm-actions`);
    const rmState = await api<RmState>(USERS.rm, 'GET', `/gs/${gs.id}/rm-actions`);
    const label = (code: string) => rmState.options.find((o) => o.code === code)?.label ?? code;
    await rmAllocate(rm, 1, label('SEND_NEW'), 8);
    await rmAllocate(rm, 1, label('PENDING_BP'), 2);
    await rm.locator(`#pending-reason-${item}`).fill('Sent to Repair Team for checking (E2E-06)');
    await rm.getByRole('button', { name: 'Save Draft Revision' }).click();
    await expect(rm.getByText(/Saved revision 1/)).toBeVisible();
    await expect(rm.getByText('Pending (BP) Held')).toBeVisible();
    await expectNoHorizontalOverflow(rm);

    await rm.goto('/#/pendencies');
    await expect(rm.getByRole('heading', { name: 'Pendency (BP) Register' })).toBeVisible();
    await rm.getByLabel('Search by GS no., party, or product').fill(gs.gs_no);
    const row = rm.getByTestId('pendency-row').filter({ hasText: gs.gs_no });
    await expect(row).toContainText('PENDING (BP)');
    await expect(row).toContainText('Held Qty: 2');
    await expectNoHorizontalOverflow(rm);
    await row.getByRole('button', { name: 'Clear Pendency' }).click();
    // Resolution choices come from the RM_ITEM_ACTION option set (rule e).
    await rm.locator('#pendency-reg-resolution-action').selectOption('SEND_REPAIRED');
    await rm.locator('#pendency-reg-clearance-notes').fill('Repaired by Repair Team (E2E-06)');
    await rm.getByRole('button', { name: 'Confirm Clearance' }).click();
    // The register opens on OPEN pendencies: the cleared one leaves that view.
    await expect(rm.getByTestId('pendency-row').filter({ hasText: gs.gs_no })).toHaveCount(0);
    await rm.getByRole('button', { name: 'CLEARED', exact: true }).click();
    await expect(
      rm.getByTestId('pendency-row').filter({ hasText: gs.gs_no }).filter({ hasText: 'CLEARED' }),
    ).toBeVisible();
    await shot(rm, 'e2e06-pendency-cleared');

    const after = await api<RmState>(USERS.rm, 'GET', `/gs/${gs.id}/rm-actions`);
    expect(after.has_open_pendency).toBe(false);
    expect(after.current_revision_no).toBe(2);
  });

  // --- E2E-07 -----------------------------------------------------------------------------------
  test('E2E-07 daily DMT container audit: confirm, then a missed day is flagged', async ({
    browser,
  }, testInfo) => {
    test.setTimeout(150_000);
    const desktop = testInfo.project.name.startsWith('desktop');
    const ist = (offsetDays: number) => {
      const now = new Date(Date.now() + 5.5 * 3600_000 - offsetDays * 86_400_000);
      return now.toISOString().slice(0, 10);
    };
    // Each project audits its own past day so the two runs never touch the same date.
    const auditDay = ist(desktop ? 20 : 24);
    const skippedDay = ist(desktop ? 19 : 23);

    const aman = await open(browser, USERS.aman, '/container-audit');
    await expect(aman.getByRole('heading', { name: 'Daily DMT Container Register' })).toBeVisible();

    async function countAll(page: Page, date: string, late: boolean) {
      const data = await api<{
        day: { confirmed: boolean };
        containers: Array<{ container_code: string }>;
        checkbox_label: string;
      }>(USERS.aman, 'GET', `/container-audits/${date}`).catch(() => null);
      if (data?.day.confirmed) return 'already-confirmed';
      const containers =
        data?.containers ??
        (
          await api<{ containers: Array<{ container_code: string }> }>(
            USERS.aman,
            'GET',
            '/container-audits/today',
          )
        ).containers;
      expect(containers.length).toBeGreaterThanOrEqual(1);
      for (const c of containers) {
        for (let i = 0; i < 3; i++) {
          await page
            .getByRole('button', { name: `Increase count for ${c.container_code}` })
            .click();
        }
        await page
          .getByRole('button', { name: `Increase sellable packaging for ${c.container_code}` })
          .click();
      }
      if (late) {
        await page
          .getByPlaceholder(/Specify reason for late audit confirmation/)
          .fill('Register was not updated on the day (E2E-07)');
      }
      await page.getByRole('checkbox').check();
      await page.getByRole('button', { name: 'Confirm Daily Audit' }).click();
      await expect(page.getByRole('button', { name: 'Audit Confirmed' })).toBeVisible({
        timeout: 15_000,
      });
      return 'confirmed';
    }

    // Today's audit (desktop confirms it; the phone run sees it confirmed or confirms it).
    const today = await countAll(aman, ist(0), false);
    testInfo.annotations.push({ type: 'today', description: today });
    await expect(aman.getByText('CONFIRMED').first()).toBeVisible();
    await expectNoHorizontalOverflow(aman);
    await shot(aman, 'e2e07-today-confirmed');

    // A late audit for an earlier day, then the 09:00 job flags the day nobody audited.
    await aman.locator('#audit-date').fill(auditDay);
    await countAll(aman, auditDay, true);
    runWorkerJob('container_audit_morning_missed');
    const calendar = await api<{ days: Array<{ audit_date: string; status: string }> }>(
      USERS.aman,
      'GET',
      `/container-audits?from=${auditDay}&to=${skippedDay}`,
    );
    expect(calendar.days.find((d) => d.audit_date === skippedDay)?.status).toBe('MISSED');

    await aman.getByRole('button', { name: 'Compliance Calendar' }).click();
    const monthsBack =
      (Number(ist(0).slice(0, 4)) - Number(skippedDay.slice(0, 4))) * 12 +
      Number(ist(0).slice(5, 7)) -
      Number(skippedDay.slice(5, 7));
    for (let i = 0; i < monthsBack; i++) {
      await aman.getByRole('button', { name: 'Previous month' }).click();
    }
    const cell = aman.getByRole('button', { name: `${skippedDay}: MISSED` });
    await expect(cell).toBeVisible();
    await cell.click();
    await expect(aman.getByText(`Audit Details for ${skippedDay}`)).toBeVisible();
    await expectNoHorizontalOverflow(aman);
    await shot(aman, 'e2e07-missed-day');
  });
});
