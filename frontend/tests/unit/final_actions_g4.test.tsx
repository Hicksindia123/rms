/**
 * Gap plan G4 (DEC-57; Q9–Q12): final actions per item + current condition, and the Pending
 * re-action round. The API client is mocked with backend-shaped payloads
 * (backend/app/modules/final_actions/schemas.py).
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ApiRequestOptions } from '@/lib/api/client';
import type { FinalActionLine, FinalActionsState } from '@/features/final-actions/types';

const apiRequestFn = vi.fn<(path: string, options?: ApiRequestOptions) => Promise<unknown>>();

vi.mock('@/lib/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/client')>();
  return {
    ...actual,
    apiRequest: (path: string, options?: ApiRequestOptions) => apiRequestFn(path, options),
  };
});

vi.mock('@/features/auth/useAuth', () => ({
  useAuth: () => ({ can: () => true, me: null, status: 'signed-in' }),
}));

const { FinalActionsPage } = await import('@/features/final-actions/FinalActionsPage');
const { toSavePayload, initialAllocations, allBalanced, groupKey } =
  await import('@/features/final-actions/rules');

const action = (code: string, label: string, sort: number) => ({
  code,
  label,
  requires_cn: code === 'ISSUE_CN',
  requires_challan: code === 'SEND_NEW' || code === 'SEND_REPAIRED',
  sort_order: sort,
});

const ACTIONS = [
  action('SEND_NEW', 'Send New', 10),
  action('ISSUE_CN', 'Issue CN', 30),
  action('NOT_ALLOWED', 'Not Allowed', 40),
  action('PENDING_BP', 'Pending', 50),
];

const group = (id: string, code: string, label: string, available: number) => ({
  condition_field_id: id,
  condition_code: code,
  condition_label: label,
  current_qty: available,
  at_departments_qty: 0,
  available_qty: available,
  actioned_qty: 0,
  is_balanced: false,
  current_actions: [],
});

const LINE: FinalActionLine = {
  gs_item_id: 'item-1',
  line_no: 1,
  product_id: 'p-1',
  product_code: 'DMT-01',
  product_name: 'Digital Thermometer',
  counted_qty: 10,
  at_departments_qty: 0,
  available_qty: 10,
  actioned_qty: 0,
  is_balanced: false,
  outcomes: [],
  current_conditions: [
    { field_code: 'GOOD', field_label: 'Good', original_qty: 7, current_qty: 7 },
    { field_code: 'BROKEN', field_label: 'Broken Body', original_qty: 3, current_qty: 3 },
  ],
  allowed_actions: ACTIONS,
  current_actions: [],
  groups: [group('c-good', 'GOOD', 'Good', 7), group('c-broken', 'BROKEN', 'Broken Body', 3)],
};

const STATE = (over: Partial<FinalActionsState> = {}): FinalActionsState => ({
  gs_id: 'gs-1',
  gs_no: 'GS/2026-27/00077',
  status: 'HELD_AT_INTERMEDIATE_STORE',
  party_name: 'Acme',
  on_final_action_flow: true,
  can_edit: true,
  can_finalise: false,
  finalise_blockers: ['No final actions have been saved yet.'],
  current_revision_no: 0,
  round_no: 1,
  pending_from_previous_round: 0,
  waiting_for_previous_round: false,
  is_finalised: false,
  is_completed: false,
  current_slip: null,
  lines: [LINE],
  revisions: [],
  slips: [],
  ...over,
});

beforeEach(() => {
  apiRequestFn.mockReset();
});

describe('G4 rules (DEC-57)', () => {
  it('allocates and saves per item + condition', () => {
    const allocs = initialAllocations([LINE]);
    expect(Object.keys(allocs).sort()).toEqual(
      [groupKey('item-1', 'c-good'), groupKey('item-1', 'c-broken')].sort(),
    );
    allocs[groupKey('item-1', 'c-good')] = { SEND_NEW: 8 };
    allocs[groupKey('item-1', 'c-broken')] = { NOT_ALLOWED: 2 };
    // The item total is right (10) but Good has only 7: not balanced.
    expect(allBalanced([LINE], allocs)).toBe(false);
    allocs[groupKey('item-1', 'c-good')] = { SEND_NEW: 5, PENDING_BP: 2 };
    allocs[groupKey('item-1', 'c-broken')] = { NOT_ALLOWED: 3 };
    expect(allBalanced([LINE], allocs)).toBe(true);
    expect(toSavePayload([LINE], allocs, null)).toEqual({
      lines: [
        {
          gs_item_id: 'item-1',
          condition_field_id: 'c-good',
          actions: [
            { action_code: 'SEND_NEW', qty: 5 },
            { action_code: 'PENDING_BP', qty: 2 },
          ],
        },
        {
          gs_item_id: 'item-1',
          condition_field_id: 'c-broken',
          actions: [{ action_code: 'NOT_ALLOWED', qty: 3 }],
        },
      ],
      reason: null,
    });
  });
});

describe('G4 FinalActionsPage', () => {
  it('shows one block per condition with its own G-21 feedback and saves per condition', async () => {
    apiRequestFn.mockImplementation((_path, options) => {
      if (options?.method === 'PUT') return Promise.resolve(STATE({ current_revision_no: 1 }));
      return Promise.resolve(STATE());
    });
    render(<FinalActionsPage gsId="gs-1" onBack={() => undefined} />);

    expect(await screen.findByText('Final Actions · GS/2026-27/00077')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Line 1 · Good' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Line 1 · Broken Body' })).toBeInTheDocument();
    expect(screen.getByText('7 pc(s) still to allocate')).toBeInTheDocument();
    expect(screen.getByText('3 pc(s) still to allocate')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Send New qty, line 1 · Good'), {
      target: { value: '5' },
    });
    fireEvent.change(screen.getByLabelText('Pending qty, line 1 · Good'), {
      target: { value: '2' },
    });
    const saveBtn = screen.getByRole('button', { name: /save actions/i });
    expect(saveBtn).toBeDisabled(); // Broken Body still unallocated
    fireEvent.change(screen.getByLabelText('Not Allowed qty, line 1 · Broken Body'), {
      target: { value: '3' },
    });
    expect(screen.getByText('10 / 10 allocated')).toBeInTheDocument();
    expect(saveBtn).toBeEnabled();
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(apiRequestFn).toHaveBeenCalledWith(
        '/gs/gs-1/final-actions',
        expect.objectContaining({ method: 'PUT' }),
      );
    });
    const put = apiRequestFn.mock.calls.find(([, o]) => o?.method === 'PUT');
    expect(put?.[1]?.idempotencyKey).toMatch(/^web-/);
    expect(put?.[1]?.body).toEqual({
      lines: [
        {
          gs_item_id: 'item-1',
          condition_field_id: 'c-good',
          actions: [
            { action_code: 'SEND_NEW', qty: 5 },
            { action_code: 'PENDING_BP', qty: 2 },
          ],
        },
        {
          gs_item_id: 'item-1',
          condition_field_id: 'c-broken',
          actions: [{ action_code: 'NOT_ALLOWED', qty: 3 }],
        },
      ],
      reason: null,
    });
  });

  it('re-action round: only the Pending pieces, per condition', async () => {
    apiRequestFn.mockResolvedValue(
      STATE({
        status: 'IN_PROCESS',
        round_no: 2,
        pending_from_previous_round: 3,
        lines: [
          {
            ...LINE,
            available_qty: 3,
            groups: [
              group('c-good', 'GOOD', 'Good', 2),
              group('c-broken', 'BROKEN', 'Broken Body', 1),
            ],
          },
        ],
      }),
    );
    render(<FinalActionsPage gsId="gs-1" onBack={() => undefined} />);

    expect(await screen.findByText('Pending re-action · round 2')).toBeInTheDocument();
    expect(screen.getByText('3 pc(s) were left Pending in round 1.')).toBeInTheDocument();
    expect(screen.getByText(/They are in the Pending Hold/)).toBeInTheDocument();
    expect(screen.getByText('2 pc(s) still to allocate')).toBeInTheDocument();
    expect(screen.getByLabelText('Issue CN qty, line 1 · Good')).toBeEnabled();
  });

  it('re-action waits for Accounts / dispatch of the previous round', async () => {
    apiRequestFn.mockResolvedValue(
      STATE({
        round_no: 2,
        pending_from_previous_round: 3,
        waiting_for_previous_round: true,
        can_edit: false,
        finalise_blockers: ['Round 1 is not settled yet.'],
      }),
    );
    render(<FinalActionsPage gsId="gs-1" onBack={() => undefined} />);

    expect(
      await screen.findByText(/once Accounts has completed round 1 and its Dispatch Slip/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Issue CN qty, line 1 · Good')).toBeDisabled();
    expect(screen.queryByRole('button', { name: /save actions/i })).not.toBeInTheDocument();
  });
});
