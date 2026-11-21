/**
 * Phase P5 (DEC-65): Pending Transfer Slip screen and slip view, rendered from backend-shaped
 * payloads (backend/app/modules/transfer_slips/schemas.py). Only the HTTP layer is mocked.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const apiRequest = vi.fn<(path: string, options?: Record<string, unknown>) => Promise<unknown>>();
vi.mock('@/lib/api/client', () => ({
  apiRequest: (path: string, options?: Record<string, unknown>) => apiRequest(path, options),
  apiDownload: vi.fn(() => Promise.resolve()),
  newIdempotencyKey: () => 'web-test-key',
  toApiError: (err: unknown) => ({
    message: err instanceof Error ? err.message : String(err),
    requestId: 'req-123',
  }),
}));

import { TransferSlipDetailPage } from '@/features/transfer-slips/TransferSlipDetailPage';
import { TransferSlipsPage } from '@/features/transfer-slips/TransferSlipsPage';

const DT = { id: 's-dt', code: 'DT', name: 'Intermediate Store DT' };
const OP = { id: 's-op', code: 'OP', name: 'Intermediate Store OP' };

function line(item: string, store: typeof DT, qty: number) {
  return {
    item_id: item,
    line_no: 1,
    product_code: `P-${item}`,
    product_name: `Product ${item}`,
    documented_qty: qty,
    received_qty: qty,
    store,
    buckets: [{ field_code: 'DMT_OK', label: 'OK Packed', qty }],
    on_slip_no: null,
  };
}

function pendingGs(id: string, extra: Record<string, unknown> = {}) {
  return {
    gs_id: id,
    gs_no: `GS/2026-27/${id}`,
    party_id: 'party-1',
    party_name: 'Acme Pharma',
    station_name: 'Agra',
    state_name: 'Uttar Pradesh',
    cartons: 2,
    received_date: '2026-11-20',
    locked_at: '2026-11-21T05:00:00Z',
    stores: [DT, OP],
    physical_qty: 5,
    lines: [line(`${id}-a`, DT, 3), line(`${id}-b`, OP, 2)],
    open_edit_request: null,
    partially_on_slips: false,
    ...extra,
  };
}

const slipSummary = (id: string, store: typeof DT, qty: number) => ({
  id,
  slip_no: `TRF/${store.code}/2026-27/0001`,
  store,
  status: 'GENERATED',
  gs_count: 1,
  gs_nos: ['GS/2026-27/1'],
  relevant_qty: qty,
  grand_total_qty: 5,
  generated_by_name: 'Pratham',
  generated_at: '2026-11-21T06:00:00Z',
  voided_at: null,
  void_reason: null,
  acknowledged_at: null,
  discrepancy_count: 0,
});

afterEach(() => {
  apiRequest.mockReset();
});

describe('TransferSlipsPage (DEC-65)', () => {
  it('selects all except GSs with an open edit request and generates one slip per store', async () => {
    const blocked = pendingGs('3', {
      open_edit_request: {
        id: 'r1',
        gs_id: '3',
        gs_no: 'GS/2026-27/3',
        party_name: 'Acme Pharma',
        reason: 'qty looks wrong',
        status: 'OPEN',
        requested_by_name: 'Pratham',
        requested_at: '2026-11-21T05:30:00Z',
        resolved_by_name: null,
        resolved_at: null,
        resolution_note: null,
      },
    });
    apiRequest.mockImplementation((path, options) => {
      if (path === '/transfer-slips/pending') {
        return Promise.resolve([pendingGs('1'), pendingGs('2'), blocked]);
      }
      if (path === '/transfer-slips' && options?.method === 'POST') {
        return Promise.resolve({
          slips: [slipSummary('t-dt', DT, 6), slipSummary('t-op', OP, 4)],
          goods_slip_ids: ['1', '2'],
        });
      }
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    render(<TransferSlipsPage canGenerate onOpenGs={vi.fn()} onOpenSlip={vi.fn()} />);

    expect(await screen.findByText('GS/2026-27/1')).toBeTruthy();
    expect(screen.getByText('Edit requested')).toBeTruthy();
    const blockedBox = screen.getByLabelText<HTMLInputElement>('Select GS/2026-27/3');
    expect(blockedBox.disabled).toBe(true);

    fireEvent.click(screen.getByLabelText('Select all goods slips shown'));
    expect(screen.getByText('2 goods slip(s) selected')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /Generate Transfer Slip/ }));
    const dialog = await screen.findByRole('dialog');
    // Plan: one slip per store across the selected GSs.
    expect(within(dialog).getByText('2 GS · 6 pc')).toBeTruthy();
    expect(within(dialog).getByText('2 GS · 4 pc')).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Generate 2 slip(s)' }));

    await waitFor(() => {
      expect(screen.getByTestId('generated-slips')).toBeTruthy();
    });
    const post = apiRequest.mock.calls.find((c) => c[1]?.method === 'POST');
    expect(post?.[1]).toMatchObject({
      body: { gs_ids: ['1', '2'] },
      idempotencyKey: 'web-test-key',
    });
    expect(screen.getByText('TRF/DT/2026-27/0001')).toBeTruthy();
  });

  it('shows the error with the request id and keeps the selection', async () => {
    apiRequest.mockImplementation((path, options) => {
      if (path === '/transfer-slips/pending') return Promise.resolve([pendingGs('1')]);
      if (options?.method === 'POST') return Promise.reject(new Error('Store mapping missing'));
      return Promise.reject(new Error('unexpected'));
    });
    render(<TransferSlipsPage canGenerate onOpenGs={vi.fn()} onOpenSlip={vi.fn()} />);
    fireEvent.click(await screen.findByLabelText('Select GS/2026-27/1'));
    fireEvent.click(screen.getByRole('button', { name: /Generate Transfer Slip/ }));
    fireEvent.click(await screen.findByRole('button', { name: 'Generate 2 slip(s)' }));
    expect(await screen.findByText('Store mapping missing (Request ID: req-123)')).toBeTruthy();
    expect(screen.getByText('1 goods slip(s) selected')).toBeTruthy();
  });

  it('sends an edit request only with a reason', async () => {
    apiRequest.mockImplementation((path) => {
      if (path === '/transfer-slips/pending') return Promise.resolve([pendingGs('1')]);
      if (path === '/gs/1/edit-requests') return Promise.resolve({ id: 'r1', status: 'OPEN' });
      return Promise.reject(new Error('unexpected'));
    });
    render(<TransferSlipsPage canGenerate onOpenGs={vi.fn()} onOpenSlip={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: /Send Edit Request/ }));
    const send = await screen.findByRole('button', { name: 'Send to Management' });
    expect((send as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('What should be corrected?'), {
      target: { value: 'Line 1 physical qty is 2, not 3' },
    });
    fireEvent.click(send);
    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledWith('/gs/1/edit-requests', {
        method: 'POST',
        body: { reason: 'Line 1 physical qty is 2, not 3' },
        idempotencyKey: 'web-test-key',
      });
    });
  });

  it('shows the empty state', async () => {
    apiRequest.mockResolvedValue([]);
    render(<TransferSlipsPage canGenerate onOpenGs={vi.fn()} onOpenSlip={vi.fn()} />);
    expect(await screen.findByText('No goods slip is waiting for a transfer slip')).toBeTruthy();
  });

  it('hides the RM actions without the generate permission', async () => {
    apiRequest.mockResolvedValue([pendingGs('1')]);
    render(<TransferSlipsPage canGenerate={false} onOpenGs={vi.fn()} onOpenSlip={vi.fn()} />);
    expect(await screen.findByText('GS/2026-27/1')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Generate Transfer Slip/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Send Edit Request/ })).toBeNull();
  });
});

describe('TransferSlipDetailPage (DEC-65)', () => {
  it('shows relevant items per GS, the greyed items of other stores and the totals', async () => {
    apiRequest.mockResolvedValue({
      ...slipSummary('t-dt', DT, 3),
      custody_transfer_id: 'ct-1',
      acknowledged_by_name: null,
      acknowledge_remarks: null,
      discrepancies: [],
      can_acknowledge: false,
      goods_slips: [
        {
          gs_id: '1',
          gs_no: 'GS/2026-27/1',
          party_name: 'Acme Pharma',
          station_name: 'Agra',
          state_name: 'Uttar Pradesh',
          cartons: 2,
          received_date: '2026-11-20',
          relevant_qty: 3,
          total_qty: 5,
        },
      ],
      lines: [
        {
          id: 'l1',
          gs_id: '1',
          gs_item_id: 'i1',
          line_no: 1,
          product_code: 'DMT-1',
          product_name: 'Digital thermometer',
          bucket_label: 'OK Packed',
          qty: 3,
          is_relevant: true,
          belongs_store_name: 'Intermediate Store DT',
        },
        {
          id: 'l2',
          gs_id: '1',
          gs_item_id: 'i2',
          line_no: 2,
          product_code: 'EO-1',
          product_name: 'Oval thermometer',
          bucket_label: 'Broken body',
          qty: 2,
          is_relevant: false,
          belongs_store_name: 'Intermediate Store OP',
        },
      ],
    });
    render(<TransferSlipDetailPage slipId="t-dt" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    expect(await screen.findByText('Subtotal GS/2026-27/1')).toBeTruthy();
    expect(screen.getByTestId('slip-relevant-qty').textContent).toBe('3');
    expect(screen.getByTestId('slip-grand-total').textContent).toBe('5');
    // DEC-66: the other stores' items sit behind a toggle.
    expect(screen.queryByText(/Oval thermometer/)).toBeNull();
    fireEvent.click(screen.getByLabelText(/Show other items of these goods slips/));
    const greyed = screen.getByText(/Oval thermometer/).closest('li');
    expect(greyed?.className).toContain('line-through');
    expect(greyed?.textContent).toContain('Intermediate Store OP');
  });
});
