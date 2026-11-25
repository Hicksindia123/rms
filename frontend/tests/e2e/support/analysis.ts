import { expect, type Locator, type Page } from '@playwright/test';

/**
 * DEC-75 store analysis in the browser: per item + condition the store user first gives the
 * verdict (Allowed / Not Allowed), then splits the Allowed pieces between "Send New Pieces to
 * Party" / "Send Repaired Pieces to Party". Pieces may go to Management with a proposal.
 */
export type AnalysisAction =
  'Send New Pieces to Party' | 'Send Repaired Pieces to Party' | 'Not Allowed';

/** Puts every piece of one condition group (a fieldset) on `action`. */
export async function decideGroup(group: Locator, action: AnalysisAction): Promise<void> {
  if (action === 'Not Allowed') {
    await group.getByRole('button', { name: /^All \d+ pcs Not Allowed$/ }).click();
  } else {
    await group.getByRole('button', { name: /^All \d+ pcs Allowed$/ }).click();
    const split = group.getByRole('button', {
      name: new RegExp(`^All \\d+ allowed pcs: ${action}$`),
    });
    if ((await split.count()) > 0) await split.click();
  }
  await expect(group).toContainText('Decided');
}

/** Decides every condition group of an item card. */
export async function decideItem(item: Locator, action: AnalysisAction): Promise<void> {
  const groups = item.locator('fieldset');
  const n = await groups.count();
  for (let i = 0; i < n; i += 1) await decideGroup(groups.nth(i), action);
}

/**
 * "Review & submit" → the confirmation. With `send`, the first piece row of the Management picker
 * (or the first row of decision `from`) is sent in full with the given proposal (and note).
 */
export async function reviewAndSubmit(
  page: Page,
  scope: Locator,
  send?: { proposal: string; note?: string; from?: string },
): Promise<void> {
  const review = scope.getByRole('button', { name: /Review & submit/ });
  expect((await review.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
  await review.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: 'Submit the analysis' })).toBeVisible();
  if (send) {
    const rows = dialog.locator('[data-testid^="mgmt-pick-"]');
    const row = (send.from ? rows.filter({ hasText: `Currently ${send.from}` }) : rows).first();
    const input = row.getByRole('spinbutton');
    await input.fill((await input.getAttribute('max')) ?? '1');
    await row.getByRole('radio', { name: send.proposal }).click();
    if (send.note) await dialog.getByLabel('Note for Management (optional)').fill(send.note);
    await dialog.getByRole('button', { name: 'Submit & send to Management' }).click();
  } else {
    await expect(dialog.getByTestId('mgmt-summary')).toContainText('Nothing goes to Management');
    await dialog.getByRole('button', { name: 'Submit analysis' }).click();
  }
  await expect(scope.getByText(/Analysis submitted for/)).toBeVisible({ timeout: 20_000 });
}
