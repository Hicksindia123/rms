import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { custodyApi } from '@/features/custody/api';
import { HandoverPage } from '@/features/custody/HandoverPage';
import { countMismatches, noteSections } from '@/features/custody/rules';
import { TransferDetailPage } from '@/features/custody/TransferDetailPage';
import type { CustodyLookups, HandoverPreview, TransferDetail } from '@/features/custody/types';

vi.mock('@/features/custody/api');
vi.mock('@/features/auth/useAuth', () => ({
  useAuth: () => ({ status: 'signed-in', me: null, can: () => true }),
}));

const lookups: CustodyLookups = {
  acceptance_options: [
    { code: 'ACCEPTED_VERIFIED', label: 'Accepted - Quantity & Lots Verified' },
    { code: 'DISCREPANCY', label: 'Discrepancy Reported' },
  ],
  mode_options: [{ code: 'PHYSICAL_AND_DIGITAL', label: 'Physical Movement & Digital Transfer' }],
  resolution_options: [
    { code: 'CANCEL_RETURN', label: 'Cancel and return', description: 'All back' },
    { code: 'ACCEPT_COUNTED_WITH_ADJUSTMENT', label: 'Accept counted quantity' },
  ],
  disposition_options: [{ code: 'RETURN_TO_SOURCE', label: 'Return the difference' }],
  blind_count: false,
  statuses: ['INITIATED', 'ACCEPTED', 'DISCREPANCY', 'RECONCILED', 'CANCELLED'],
};

const preview: HandoverPreview = {
  gs_id: 'gs-1',
  gs_no: 'GS/2026-27/00001',
  gs_status: 'IN_PROCESS',
  category_code: 'RO',
  from_location_code: 'INWARD_STAGING',
  from_location_name: 'Inward Staging',
  to_location_code: 'INTERMEDIATE_STORE',
  to_location_name: 'Intermediate Store',
  eligible: [
    {
      lot_id: 'lot-ok',
      gs_item_id: 'item-1',
      line_no: 1,
      product_code: 'DMT-1',
      product_name: 'Digital thermometer',
      condition_code: 'DMT_OK_PACKED',
      condition_label: 'Visually okay and packed',
      routing_hint: 'SELLABLE',
      qty: 6,
    },
  ],
  excluded: [
    {
      lot_id: 'lot-pend',
      gs_item_id: 'item-1',
      line_no: 1,
      product_name: 'Digital thermometer',
      qty: 2,
      reason_code: 'PENDING_BP',
      reason_label: 'Pending (BP)',
      condition_label: null,
      location_code: 'PENDING_HOLD',
      location_name: 'Pending Hold',
      detail: 'Checking with Repair Team',
    },
    {
      lot_id: 'lot-hg',
      gs_item_id: 'item-2',
      line_no: 2,
      product_name: 'Prismatic',
      qty: 1,
      reason_code: 'HAZARD',
      reason_label: 'Hazard Quarantine',
      condition_label: 'Broken with mercury',
      location_code: 'HAZARD_QUARANTINE',
      location_name: 'Hazard Quarantine',
      detail: null,
    },
  ],
  blocked: null,
  proposal_transfer_id: null,
  live_transfers: [],
  can_initiate: true,
  mode_options: lookups.mode_options,
  default_mode_code: 'PHYSICAL_AND_DIGITAL',
};

function transfer(overrides: Partial<TransferDetail> = {}): TransferDetail {
  return {
    id: 'trf-1',
    transfer_no: 'TRF/2026-27/00001',
    gs_id: 'gs-1',
    gs_no: 'GS/2026-27/00001',
    status: 'INITIATED',
    purpose_code: 'STEP4_HANDOVER',
    with_packaging: false,
    stock_moved: true,
    mode_code: 'PHYSICAL_AND_DIGITAL',
    mode_label: 'Physical Movement & Digital Transfer',
    from_location_code: 'INWARD_STAGING',
    from_location_name: 'Inward Staging',
    to_location_code: 'INTERMEDIATE_STORE',
    to_location_name: 'Intermediate Store',
    initiated_by: 'aman',
    initiated_by_name: 'Aman',
    initiated_at: '2026-11-04T05:00:00Z',
    accepted_by_name: null,
    accepted_at: null,
    acceptance_code: null,
    acceptance_label: null,
    line_count: 1,
    total_qty: 6,
    created_at: '2026-11-04T05:00:00Z',
    notes: null,
    discrepancy_notes: null,
    cancel_reason: null,
    cancelled_at: null,
    resolution_code: null,
    reconciled_at: null,
    supersedes_transfer_id: null,
    blind_count: false,
    lines: [
      {
        lot_id: 'lot-ok',
        gs_item_id: 'item-1',
        line_no: 1,
        product_code: 'DMT-1',
        product_name: 'Digital thermometer',
        condition_class: 'AS_RECEIVED',
        condition_code: 'DMT_OK_PACKED',
        condition_label: 'Visually okay and packed',
        routing_hint: 'SELLABLE',
        qty_sent: 6,
        qty_counted: null,
        qty_accepted: 0,
        qty_returned: 0,
        qty_adjusted: 0,
      },
    ],
    reconciliations: [],
    permissions: {
      can_accept: true,
      can_cancel: false,
      can_print: true,
      reconcile_side: null,
      can_override: false,
      can_approve_adjustment: false,
    },
    ...overrides,
  };
}

describe('custody rules', () => {
  it('flags every line whose count differs from the quantity sent', () => {
    const lines = [
      { lot_id: 'a', qty_sent: 5 },
      { lot_id: 'b', qty_sent: 2 },
      { lot_id: 'c', qty_sent: null },
    ];
    expect(countMismatches(lines, { a: 5, b: 1, c: 9 })).toEqual(['b']);
  });

  it('reads TRANSFER_NOTE sections, flattening a nested section array', () => {
    const sections = noteSections({
      sections: [
        { id: 'transfer_meta', title: 'Transfer Info', fields: ['transfer_no'] },
        [{ id: 'lines', title: 'Allocated Lots', fields: ['product_name', 'qty_sent'] }],
      ],
    });
    expect(sections.map((s) => s.id)).toEqual(['transfer_meta', 'lines']);
    expect(sections[1]?.fields).toEqual(['product_name', 'qty_sent']);
  });
});

describe('HandoverPage', () => {
  beforeEach(() => {
    vi.mocked(custodyApi.handoverPreview).mockResolvedValue(preview);
    vi.mocked(custodyApi.handover).mockResolvedValue(transfer());
  });

  it('lists held-back lines with their reasons and sends the chosen quantities', async () => {
    const onOpenTransfer = vi.fn();
    render(<HandoverPage gsId="gs-1" onBack={vi.fn()} onOpenTransfer={onOpenTransfer} />);
    expect(await screen.findByText('Pending (BP)')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'Handover to Intermediate Store',
    );
    expect(screen.getByText(/Checking with Repair Team/)).toBeInTheDocument();
    expect(screen.getByText('Hazard Quarantine')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Decrease Quantity/ }));
    fireEvent.click(screen.getByRole('button', { name: /Confirm handover/ }));
    await waitFor(() => {
      expect(onOpenTransfer).toHaveBeenCalledWith('trf-1');
    });
    const [gsId, body, key] = vi.mocked(custodyApi.handover).mock.calls[0] ?? [];
    expect(gsId).toBe('gs-1');
    expect(body).toEqual({
      mode_code: 'PHYSICAL_AND_DIGITAL',
      lines: [{ lot_id: 'lot-ok', qty: 5 }],
    });
    expect(key).toMatch(/^web-/);
  });

  it('shows why a handover is blocked and offers no confirm button', async () => {
    vi.mocked(custodyApi.handoverPreview).mockResolvedValue({
      ...preview,
      blocked: { code: 'G-08', message: 'Open Pending (BP) pendencies block the whole GS' },
      can_initiate: false,
    });
    render(<HandoverPage gsId="gs-1" onBack={vi.fn()} onOpenTransfer={vi.fn()} />);
    expect(await screen.findByText(/block the whole GS/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Confirm handover/ })).not.toBeInTheDocument();
  });
});

describe('TransferDetailPage receive screen', () => {
  beforeEach(() => {
    vi.mocked(custodyApi.lookups).mockResolvedValue(lookups);
  });

  it('allows acceptance only when the count matches; a mismatch needs a discrepancy note', async () => {
    vi.mocked(custodyApi.detail).mockResolvedValue(transfer());
    vi.mocked(custodyApi.accept).mockResolvedValue(
      transfer({
        status: 'DISCREPANCY',
        permissions: { ...transfer().permissions, can_accept: false },
      }),
    );
    render(
      <TransferDetailPage
        transferId="trf-1"
        onBack={vi.fn()}
        onOpenTransfer={vi.fn()}
        onOpenNote={vi.fn()}
      />,
    );
    const accept = await screen.findByRole('button', { name: /Accepted - Quantity/ });
    const report = screen.getByRole('button', { name: /Discrepancy Reported/ });
    expect(accept).toBeEnabled();
    expect(report).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: /Decrease Counted/ }));
    expect(accept).toBeDisabled();
    expect(report).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Discrepancy details/), {
      target: { value: 'One piece missing' },
    });
    expect(report).toBeEnabled();
    fireEvent.click(report);
    await waitFor(() => {
      expect(custodyApi.accept).toHaveBeenCalled();
    });
    const [, body] = vi.mocked(custodyApi.accept).mock.calls[0] ?? [];
    expect(body).toEqual({
      lines: [{ lot_id: 'lot-ok', qty_counted: 5 }],
      acceptance_code: 'DISCREPANCY',
      notes: 'One piece missing',
    });
    expect(await screen.findByText(/frozen in transit/)).toBeInTheDocument();
  });

  it('hides the quantity sent during a blind count', async () => {
    const blind = transfer({ blind_count: true, total_qty: null });
    blind.lines = blind.lines.map((l) => ({ ...l, qty_sent: null }));
    vi.mocked(custodyApi.detail).mockResolvedValue(blind);
    render(
      <TransferDetailPage
        transferId="trf-1"
        onBack={vi.fn()}
        onOpenTransfer={vi.fn()}
        onOpenNote={vi.fn()}
      />,
    );
    expect(await screen.findByText(/Hidden until your count is submitted/)).toBeInTheDocument();
    expect(screen.queryByText(/sent 6/)).not.toBeInTheDocument();
    expect(screen.getByLabelText('Counted')).toHaveValue(0);
  });
});
