/**
 * Phase P6 (DEC-66; Q12, Q13): the Intermediate Store acknowledges a transfer slip in full or
 * reports a discrepancy, from the slip view. Rendered from backend-shaped payloads
 * (backend/app/modules/transfer_slips/schemas.py SlipDetailOut). Only the HTTP layer is mocked.
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
    requestId: 'req-456',
  }),
}));

import { StoreAcknowledgementPage } from '@/features/transfer-slips/StoreAcknowledgementPage';
import { TransferSlipDetailPage } from '@/features/transfer-slips/TransferSlipDetailPage';
import { itemPath, entryPath } from '@/features/journey/screens';

const DT = { id: 's-dt', code: 'DT', name: 'Intermediate Store DT' };

function slip(extra: Record<string, unknown> = {}) {
  return {
    id: 't-dt',
    slip_no: 'TRF/DT/2026-27/0001',
    store: DT,
    status: 'GENERATED',
    gs_count: 1,
    gs_nos: ['GS/2026-27/1'],
    relevant_qty: 4,
    grand_total_qty: 4,
    generated_by_name: 'Pratham',
    generated_at: '2026-11-21T06:00:00Z',
    voided_at: null,
    void_reason: null,
    acknowledged_at: null,
    discrepancy_count: 0,
    custody_transfer_id: 'ct-1',
    acknowledged_by_name: null,
    acknowledge_remarks: null,
    discrepancies: [],
    can_acknowledge: true,
    goods_slips: [
      {
        gs_id: '1',
        gs_no: 'GS/2026-27/1',
        party_name: 'Acme Pharma',
        station_name: 'Agra',
        state_name: 'Uttar Pradesh',
        cartons: 2,
        received_date: '2026-11-20',
        relevant_qty: 4,
        total_qty: 4,
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
        gs_item_id: 'i1',
        line_no: 1,
        product_code: 'DMT-1',
        product_name: 'Digital thermometer',
        bucket_label: 'Broken body',
        qty: 1,
        is_relevant: true,
        belongs_store_name: 'Intermediate Store DT',
      },
    ],
    ...extra,
  };
}

afterEach(() => {
  apiRequest.mockReset();
});

describe('Store acknowledgement (DEC-66)', () => {
  it('sums the items per condition and acknowledges with an optional remark', async () => {
    apiRequest.mockImplementation((path) =>
      Promise.resolve(
        path.endsWith('/acknowledge')
          ? slip({
              status: 'ACKNOWLEDGED',
              can_acknowledge: false,
              acknowledged_at: '2026-11-21T07:00:00Z',
              acknowledged_by_name: 'Dinesh',
              acknowledge_remarks: 'All received',
            })
          : slip(),
      ),
    );
    render(<TransferSlipDetailPage slipId="t-dt" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    const byCondition = await screen.findByLabelText('GS/2026-27/1 by condition');
    expect(within(byCondition).getByText('OK Packed: 3')).toBeTruthy();
    expect(within(byCondition).getByText('Broken body: 1')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /Acknowledge receipt/ }));
    const dialog = await screen.findByRole('dialog');
    expect(dialog.textContent).toContain('4 pc');
    fireEvent.change(within(dialog).getByLabelText(/Remark/), {
      target: { value: '  All received ' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm receipt' }));

    expect(await screen.findByText(/acknowledged\. The goods are now in/)).toBeTruthy();
    const call = apiRequest.mock.calls.find(([p]) => p.endsWith('/acknowledge'));
    expect(call?.[0]).toBe('/transfer-slips/t-dt/acknowledge');
    expect(call?.[1]).toMatchObject({
      method: 'POST',
      body: { remarks: 'All received' },
      idempotencyKey: 'web-test-key',
    });
    expect(screen.queryByTestId('slip-ack-panel')).toBeNull();
    expect(screen.getByText(/Acknowledged by Dinesh/)).toBeTruthy();
  });

  it('reports a discrepancy only with a remark and shows the error with the request id', async () => {
    apiRequest.mockImplementation((path) =>
      path.endsWith('/discrepancies')
        ? Promise.reject(new Error('Transfer slip TRF/DT/2026-27/0001 is void'))
        : Promise.resolve(slip()),
    );
    render(<TransferSlipDetailPage slipId="t-dt" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: /Report discrepancy/ }));
    const dialog = await screen.findByRole('dialog');
    const send = within(dialog).getByRole('button', { name: 'Send report' });
    expect((send as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(within(dialog).getByLabelText(/What is wrong/), {
      target: { value: 'One piece short' },
    });
    fireEvent.click(send);
    expect(await within(dialog).findByRole('alert')).toBeTruthy();
    expect(within(dialog).getByRole('alert').textContent).toContain('req-456');
  });

  it('hides the actions from users who may not acknowledge and lists discrepancies', async () => {
    apiRequest.mockResolvedValue(
      slip({
        can_acknowledge: false,
        discrepancy_count: 1,
        discrepancies: [
          {
            id: 'd1',
            remark: 'Carton 2 one short',
            reported_by_name: 'Dinesh',
            reported_at: '2026-11-21T06:30:00Z',
          },
        ],
      }),
    );
    render(<TransferSlipDetailPage slipId="t-dt" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    expect(await screen.findByText('Carton 2 one short')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Acknowledge receipt/ })).toBeNull();
  });

  it('lists the store slips waiting for acknowledgement', async () => {
    apiRequest.mockResolvedValue({ items: [slip()], total: 1 });
    const open = vi.fn();
    render(<StoreAcknowledgementPage onOpenSlip={open} />);
    const list = await screen.findByTestId('slip-list');
    expect(apiRequest.mock.calls[0]?.[1]).toMatchObject({ query: { status: 'GENERATED' } });
    fireEvent.click(within(list).getByText('TRF/DT/2026-27/0001'));
    await waitFor(() => {
      expect(open).toHaveBeenCalledWith('t-dt');
    });
  });

  it('routes the journey entry and its queue items to the slip screens', () => {
    expect(entryPath({ code: 'ACK_TRANSFER_SLIPS', screen_key: 'transfer-slip-acks' })).toBe(
      '/transfer-slips/acknowledge',
    );
    expect(itemPath('transfer-slip', { gs_id: 'g1', target_id: 't-dt' })).toBe(
      '/transfer-slips/t-dt',
    );
  });
});
