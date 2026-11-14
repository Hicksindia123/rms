import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { finalActionsApi } from '@/features/final-actions/api';
import { FinalActionsPage } from '@/features/final-actions/FinalActionsPage';
import {
  allBalanced,
  initialAllocations,
  isDirty,
  lineIssue,
  parseQty,
  toSavePayload,
} from '@/features/final-actions/rules';
import type { FinalActionLine, FinalActionsState } from '@/features/final-actions/types';
import { notificationPath } from '@/features/notifications/links';
import { ApiError } from '@/lib/api/client';

vi.mock('@/features/auth/useAuth', () => ({
  useAuth: () => ({ can: () => true, me: null, status: 'signed-in' }),
}));

const action = (code: string, label: string) => ({
  code,
  label,
  requires_cn: code === 'ISSUE_CN',
  requires_challan: code.startsWith('SEND_'),
  sort_order: 0,
});

const line: FinalActionLine = {
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
  outcomes: [{ outcome_code: 'REPAIRED', outcome_label: 'Repaired', is_wastage: false, qty: 3 }],
  allowed_actions: [
    action('SEND_NEW', 'Send New'),
    action('SEND_REPAIRED', 'Send Repaired'),
    action('ISSUE_CN', 'Issue CN'),
  ],
  current_actions: [],
};

const state = (over: Partial<FinalActionsState> = {}): FinalActionsState => ({
  gs_id: 'gs-1',
  gs_no: 'GS/2026-27/00042',
  status: 'HELD_AT_INTERMEDIATE_STORE',
  party_name: 'Acme',
  on_final_action_flow: true,
  can_edit: true,
  can_finalise: false,
  finalise_blockers: ['No final actions have been saved yet.'],
  current_revision_no: 0,
  is_finalised: false,
  current_slip: null,
  lines: [line],
  revisions: [],
  slips: [],
  ...over,
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('Phase 7 rules (AMD-16, G-21)', () => {
  it('flags under / over allocation and builds the save payload without zero rows', () => {
    const allocs = initialAllocations([line]);
    expect(allocs['item-1']).toEqual({ SEND_NEW: 0, SEND_REPAIRED: 0, ISSUE_CN: 0 });
    expect(lineIssue(line, allocs['item-1'])).toBe('10 pc(s) still to allocate');
    allocs['item-1'] = { SEND_NEW: 6, SEND_REPAIRED: 3, ISSUE_CN: 2 };
    expect(lineIssue(line, allocs['item-1'])).toBe('1 pc(s) over the available qty');
    allocs['item-1'] = { SEND_NEW: 6, SEND_REPAIRED: 3, ISSUE_CN: 1 };
    expect(allBalanced([line], allocs)).toBe(true);
    expect(isDirty([line], allocs)).toBe(true);
    expect(toSavePayload([line], { 'item-1': { SEND_NEW: 10, ISSUE_CN: 0 } }, '  ')).toEqual({
      lines: [{ gs_item_id: 'item-1', actions: [{ action_code: 'SEND_NEW', qty: 10 }] }],
      reason: null,
    });
  });

  it('accepts only whole non-negative quantities', () => {
    expect(parseQty('7')).toBe(7);
    expect(parseQty('-1')).toBe(0);
    expect(parseQty('2.5')).toBe(0);
    expect(parseQty('abc')).toBe(0);
  });

  it('deep-links A/c Actions slip notifications to the Final Actions screen', () => {
    const path = notificationPath(
      {
        id: 'n1',
        type: 'AC_ACTIONS_SLIP_READY',
        entity_type: 'ac_action_slips',
        entity_id: 'slip-1',
        gs_id: 'gs-1',
      } as never,
      () => true,
    );
    expect(path).toBe('/gs/gs-1/final-actions');
  });
});

describe('Phase 7 FinalActionsPage', () => {
  it('shows G-21 feedback, then saves a balanced split with an Idempotency-Key', async () => {
    vi.spyOn(finalActionsApi, 'get').mockResolvedValue(state());
    const save = vi.spyOn(finalActionsApi, 'save').mockResolvedValue(
      state({
        current_revision_no: 1,
        can_finalise: true,
        finalise_blockers: [],
        lines: [
          {
            ...line,
            actioned_qty: 10,
            is_balanced: true,
            current_actions: [{ action_code: 'SEND_NEW', label: 'Send New', qty: 10 }],
          },
        ],
      }),
    );
    render(<FinalActionsPage gsId="gs-1" onBack={() => undefined} />);

    expect(await screen.findByText('Final Actions · GS/2026-27/00042')).toBeInTheDocument();
    expect(screen.getByText('Repaired 3')).toBeInTheDocument();
    expect(screen.getByText('10 pc(s) still to allocate')).toBeInTheDocument();
    const saveBtn = screen.getByRole('button', { name: /save actions/i });
    expect(saveBtn).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Send New qty, line 1'), { target: { value: '10' } });
    expect(screen.getByText('10 / 10 allocated')).toBeInTheDocument();
    expect(saveBtn).toBeEnabled();
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(save).toHaveBeenCalledTimes(1);
    });
    const [gsId, body, key] = save.mock.calls[0] ?? [];
    expect(gsId).toBe('gs-1');
    expect(body).toEqual({
      lines: [{ gs_item_id: 'item-1', actions: [{ action_code: 'SEND_NEW', qty: 10 }] }],
      reason: null,
    });
    expect(String(key)).toMatch(/^web-/);
    expect(await screen.findByText('Saved as revision 1.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /finalise & generate slip/i })).toBeEnabled();
  });

  it('locks a finalised split, offers print and requires a reason to revise', async () => {
    const slip = {
      id: 'slip-1',
      slip_no: 'RSA/2026-27/00001',
      version_no: 1,
      revision_no: 1,
      status: 'CURRENT',
      finalised_at: '2026-11-13T10:00:00Z',
      finalised_by_name: 'Pratham',
      superseded_at: null,
      superseded_by_name: null,
      supersede_reason: null,
      remarks: null,
      total_qty: 10,
      action_totals: [{ action_code: 'SEND_NEW', action_label: 'Send New', qty: 10 }],
      print_count: 0,
    };
    vi.spyOn(finalActionsApi, 'get').mockResolvedValue(
      state({
        is_finalised: true,
        current_revision_no: 1,
        current_slip: slip,
        slips: [slip],
        finalise_blockers: ['Already finalised on RSA/2026-27/00001 v1.'],
        lines: [
          {
            ...line,
            actioned_qty: 10,
            is_balanced: true,
            current_actions: [{ action_code: 'SEND_NEW', label: 'Send New', qty: 10 }],
          },
        ],
      }),
    );
    render(<FinalActionsPage gsId="gs-1" onBack={() => undefined} />);

    expect(await screen.findByText('Finalised on RSA/2026-27/00001 v1')).toBeInTheDocument();
    expect(screen.getByLabelText('Send New qty, line 1')).toBeDisabled();
    expect(screen.getByRole('button', { name: /print a\/c actions slip/i })).toBeEnabled();

    fireEvent.click(screen.getByRole('button', { name: /revise/i }));
    fireEvent.change(screen.getByLabelText('Send New qty, line 1'), { target: { value: '9' } });
    fireEvent.change(screen.getByLabelText('Issue CN qty, line 1'), { target: { value: '1' } });
    const saveBtn = screen.getByRole('button', { name: /save actions/i });
    expect(saveBtn).toBeDisabled(); // reason still empty
    fireEvent.change(screen.getByLabelText('Reason for the revision'), {
      target: { value: 'One piece not repairable' },
    });
    expect(saveBtn).toBeEnabled();
  });

  it('shows the error envelope with code and request id, with retry', async () => {
    vi.spyOn(finalActionsApi, 'get').mockRejectedValue(
      new ApiError(404, 'GS_NOT_FOUND', 'Goods slip not found', null, 'req-77'),
    );
    render(<FinalActionsPage gsId="gs-x" onBack={() => undefined} />);
    expect(await screen.findByText('Goods slip not found')).toBeInTheDocument();
    expect(screen.getByText(/Request ID: req-77/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});
