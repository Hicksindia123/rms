import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { acEntryApi } from '@/features/ac-entry/api';
import { AccountsEntryPage } from '@/features/ac-entry/AccountsEntryPage';
import { AccountsEntryQueuePage } from '@/features/ac-entry/AccountsEntryQueuePage';
import {
  gsDraftComplete,
  gsDraftDirty,
  gsDraftIssues,
  localToday,
  toGsDraft,
  toGsEntryBody,
} from '@/features/ac-entry/rules';
import type { AcEntryState, AcGsEntry } from '@/features/ac-entry/types';

/** Phase P11 (DEC-71): one Challan / Credit Note per goods slip on the Intermediate Store flow. */

vi.mock('@/features/auth/useAuth', () => ({
  useAuth: () => ({ can: () => true, me: null, status: 'signed-in' }),
}));

afterEach(() => {
  vi.restoreAllMocks();
});

const TODAY = localToday();

const entry = (over: Partial<AcGsEntry> = {}): AcGsEntry => ({
  requires_challan: true,
  requires_cn: false,
  challan_no: null,
  challan_date: null,
  cn_no: null,
  cn_date: null,
  cn_value: null,
  is_complete: false,
  entered_by_name: null,
  entered_at: null,
  ...over,
});

const state = (over: Partial<AcEntryState> = {}): AcEntryState => ({
  gs_id: 'gs-1',
  gs_no: 'GS/2026-27/00007',
  gs_status: 'ACCOUNTS_PENDING',
  party_name: 'Sharma Medicos',
  party_code: 'P-001',
  ac_action_slip_id: 'slip-1',
  slip_no: 'RSA/2026-27/00003',
  version_no: 2,
  lines: [
    {
      id: 'l-1',
      gs_item_id: 'i-1',
      line_no: 1,
      product_code: 'DMT-01',
      product_name: 'Digital Thermometer',
      action_code: 'SEND_NEW',
      action_label: 'Dispatch New Piece',
      condition_label: 'Broken Body',
      qty: 2,
      requires_cn: false,
      requires_challan: true,
      cn_no: null,
      cn_date: null,
      cn_value: null,
      challan_no: null,
      challan_date: null,
      is_complete: false,
      entered_by_name: null,
      entered_at: null,
    },
  ],
  lines_needing_data: 1,
  lines_complete: 0,
  shipping_lines: 1,
  is_completed: false,
  completed_by_name: null,
  completed_at: null,
  can_edit: true,
  can_complete: false,
  complete_blockers: ['Challan No. and Challan Date are missing.'],
  dispatch_slip: null,
  per_gs: true,
  gs_entry: entry(),
  slip_title: 'Replacement Slip',
  management_stamp: 'Digitally approved by Management — Mgmt, 23-11-2026 10:00, ref abcdef123456',
  ...over,
});

describe('P11 per-GS entry rules (DEC-71)', () => {
  it('sends only the groups the goods slip needs', () => {
    const e = entry();
    const d = { ...toGsDraft(e), challan_no: ' CH-1 ', challan_date: TODAY, cn_no: 'X' };
    expect(gsDraftDirty(e, d)).toBe(true);
    expect(toGsEntryBody(e, d)).toEqual({ challan_no: 'CH-1', challan_date: TODAY });
    const cn = entry({ requires_challan: false, requires_cn: true });
    expect(toGsEntryBody(cn, { ...d, cn_no: 'CN-1', cn_date: TODAY, cn_value: '10' })).toEqual({
      cn_no: 'CN-1',
      cn_date: TODAY,
      cn_value: '10',
    });
  });

  it('flags partial groups, amounts and future dates; completes with every needed group', () => {
    const both = entry({ requires_cn: true });
    const d = { challan_no: 'CH', challan_date: '', cn_no: 'CN', cn_date: TODAY, cn_value: '0' };
    const issues = gsDraftIssues(both, d, TODAY);
    expect(issues).toContain('Challan No. and Challan Date are entered together.');
    expect(issues).toContain('CN Value must be a positive amount.');
    expect(
      gsDraftIssues(both, { ...d, challan_date: '2999-01-01', cn_value: '5' }, TODAY),
    ).toContain('Challan Date cannot be in the future.');
    expect(gsDraftComplete(both, { ...d, challan_date: TODAY, cn_value: '5' })).toBe(true);
    expect(gsDraftComplete(both, { ...d, challan_date: TODAY, cn_no: '' })).toBe(false);
  });
});

describe('P11 Accounts entry page (per goods slip)', () => {
  it('shows only the Challan, the stamp and read-only lines, and saves the GS entry', async () => {
    vi.spyOn(acEntryApi, 'get').mockResolvedValue(state());
    const saved = state({
      gs_entry: entry({ challan_no: 'CH-9', challan_date: TODAY, is_complete: true }),
      can_complete: true,
      complete_blockers: [],
    });
    const save = vi.spyOn(acEntryApi, 'saveGsEntry').mockResolvedValue(saved);
    render(<AccountsEntryPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} />);

    await screen.findByText('Accounts entry (whole goods slip)');
    expect(screen.getByLabelText('Challan No.')).toBeInTheDocument();
    expect(screen.queryByLabelText('CN No.')).not.toBeInTheDocument();
    expect(screen.getByTestId('ac-stamp')).toHaveTextContent('Digitally approved by Management');
    expect(screen.getByRole('button', { name: /Print Replacement Slip/ })).toBeInTheDocument();
    expect(screen.getByText(/Broken Body · Dispatch New Piece/)).toBeInTheDocument();
    // Lines are read-only: no per-line inputs.
    expect(screen.getAllByRole('textbox')).toHaveLength(1);

    fireEvent.change(screen.getByLabelText('Challan No.'), { target: { value: 'CH-9' } });
    fireEvent.change(screen.getByLabelText('Challan Date'), { target: { value: TODAY } });
    fireEvent.click(screen.getByRole('button', { name: /Save/ }));
    await waitFor(() => {
      expect(save).toHaveBeenCalled();
    });
    const [gsId, body] = save.mock.calls[0] ?? [];
    expect(gsId).toBe('gs-1');
    expect(body).toEqual({ ac_action_slip_id: 'slip-1', challan_no: 'CH-9', challan_date: TODAY });
    expect(await screen.findByText('Saved.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Complete/ })).toBeEnabled();
  });

  it('explains a goods slip that has no Replacement Slip at Accounts', async () => {
    vi.spyOn(acEntryApi, 'get').mockResolvedValue(
      state({
        ac_action_slip_id: null,
        slip_no: null,
        version_no: null,
        lines: [],
        gs_entry: null,
        can_edit: false,
        complete_blockers: [
          'No Replacement Slip at Accounts: the goods slip waits for the store analysis or Management approval.',
        ],
      }),
    );
    render(<AccountsEntryPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    expect(await screen.findByText('No Replacement Slip at Accounts')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Save/ })).not.toBeInTheDocument();
  });
});

describe('P11 Accounts queue: goods slips on hold (Q21)', () => {
  it('lists the hold read-only and opens the goods slip', async () => {
    vi.spyOn(acEntryApi, 'queue').mockResolvedValue([]);
    vi.spyOn(acEntryApi, 'hold').mockResolvedValue([
      {
        gs_id: 'gs-9',
        gs_no: 'GS/2026-27/00009',
        gs_status: 'NOT_ALLOWED_HOLD',
        party_name: 'Gupta Traders',
        since: '2026-11-23T08:00:00Z',
        total_qty: 4,
      },
    ]);
    const onOpenGs = vi.fn();
    const onOpen = vi.fn();
    render(<AccountsEntryQueuePage onOpen={onOpen} onOpenGs={onOpenGs} />);
    await screen.findByText('Nothing to enter');
    fireEvent.click(screen.getByRole('button', { name: 'On hold' }));
    fireEvent.click(await screen.findByRole('button', { name: /GS\/2026-27\/00009/ }));
    expect(screen.getByText(/all Not Allowed · no Accounts entry/)).toBeInTheDocument();
    expect(onOpenGs).toHaveBeenCalledWith('gs-9');
    expect(onOpen).not.toHaveBeenCalled();
  });
});
