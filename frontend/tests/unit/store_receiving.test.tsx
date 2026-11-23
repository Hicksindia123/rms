/**
 * Phase P8 (DEC-68): the Intermediate Store user receives its goods back from departments, per goods
 * slip and DIN: outcome + condition after work per line, partial receipts. The receipt posts to the
 * store endpoint with an Idempotency-Key. Rendered from backend-shaped payloads
 * (backend/app/modules/department_routing/schemas.py StoreReceiving* / DepartmentRoutingOut); only
 * the HTTP layer is mocked.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const apiRequest = vi.fn<(path: string, options?: Record<string, unknown>) => Promise<unknown>>();
vi.mock('@/lib/api/client', () => ({
  apiRequest: (path: string, options?: Record<string, unknown>) => apiRequest(path, options),
  newIdempotencyKey: () => 'web-test-key',
  toApiError: (err: unknown) => ({
    message: err instanceof Error ? err.message : String(err),
    requestId: 'req-p8',
  }),
}));

import { StoreReceivingPage } from '@/features/department-routing/StoreReceivingPage';
import { itemPath } from '@/features/journey/screens';

const DIN = {
  id: 'din-1',
  routing_no: 'DIN/2026-27/00001',
  department_code: 'CLEANING',
  department_label: 'Cleaning (Production)',
  status: 'DISPATCHED',
  store_id: 's-dt',
  store_code: 'DT',
  store_name: 'Intermediate Store DT',
  dispatched_at: '2026-11-21T10:00:00Z',
  dispatched_by_name: 'Dinesh',
  qty_sent: 3,
  qty_received: 0,
  qty_pending: 3,
  is_mine: true,
};

const QUEUE = [
  {
    gs_id: 'gs-1',
    gs_no: 'GS/2026-27/0007',
    status: 'STORE_PROCESSING',
    party_name: 'Acme Pharma',
    station_name: 'Agra',
    since: '2026-11-21T10:00:00Z',
    stores: [
      {
        store_id: 's-dt',
        store_code: 'DT',
        store_name: 'Intermediate Store DT',
        total_qty: 3,
        unrouted_qty: 0,
        at_dept_qty: 3,
        no_work_qty: 0,
        status: 'AT_DEPARTMENTS',
        is_mine: true,
      },
    ],
    dins: [DIN, { ...DIN, id: 'din-2', routing_no: 'DIN/2026-27/00002', is_mine: false }],
  },
];

const ROUTING = {
  id: 'din-1',
  routing_no: 'DIN/2026-27/00001',
  gs_id: 'gs-1',
  gs_no: 'GS/2026-27/0007',
  department_field_id: 'd-clean',
  department_code: 'CLEANING',
  department_label: 'Cleaning (Production)',
  status: 'DISPATCHED',
  dispatched_at: '2026-11-21T10:00:00Z',
  dispatched_by: 'u-dt',
  dispatched_by_name: 'Dinesh',
  remarks: null,
  location_code: 'DEPT_CLEANING',
  location_name: 'Cleaning',
  store_code: 'DT',
  store_name: 'Intermediate Store DT',
  lines: [
    {
      id: 'rl-1',
      routing_id: 'din-1',
      gs_item_id: 'i-1',
      line_no: 1,
      item_name: 'Digital thermometer',
      sku_code: 'DMT-1',
      source_bucket_field_id: 'c-ok',
      source_bucket_code: 'OK',
      source_bucket_label: 'Visually okay',
      qty_sent: 3,
      qty_received: 0,
      qty_pending: 3,
      notes: null,
      condition_options: [
        { field_id: 'c-ok', code: 'OK', label: 'Visually okay' },
        { field_id: 'c-bad', code: 'BAD', label: 'Broken body' },
      ],
    },
  ],
};

const HEADS = [
  {
    id: 'h-clean',
    code: 'CLEANED',
    label: 'Cleaned / Calibrated',
    is_wastage: false,
    returns_to_routing: false,
    sort_order: 30,
    is_active: true,
    destination_location_code: 'INTERMEDIATE_STORE',
    destination_location_name: 'Intermediate Store',
  },
  {
    id: 'h-reroute',
    code: 'RE_ROUTE',
    label: 'Return for Re-routing',
    is_wastage: false,
    returns_to_routing: true,
    sort_order: 60,
    is_active: true,
    destination_location_code: 'INTERMEDIATE_STORE',
    destination_location_name: 'Intermediate Store',
  },
];

function route(path: string): Promise<unknown> {
  if (path.startsWith('/department-routing/store/receiving')) return Promise.resolve(QUEUE);
  if (path === '/department-routing/din-1') return Promise.resolve(ROUTING);
  if (path.startsWith('/department-routing/outcome-heads')) return Promise.resolve(HEADS);
  if (path === '/department-routing/store/routings/din-1/receive') return Promise.resolve({});
  return Promise.reject(new Error(`unexpected ${path}`));
}

afterEach(() => {
  apiRequest.mockReset();
});

const noop = () => undefined;

describe('StoreReceivingPage (DEC-68)', () => {
  it('lists the goods slip with its DINs; only the own store DIN can be received', async () => {
    apiRequest.mockImplementation(route);
    render(<StoreReceivingPage onShowAll={noop} onOpenGs={noop} onOpenPrint={noop} />);
    expect(await screen.findByText('GS/2026-27/0007')).toBeTruthy();
    expect(screen.getByText(/Acme Pharma/)).toBeTruthy();
    expect(screen.getByText(/DT: At departments/)).toBeTruthy();
    const notes = screen.getByRole('list', { name: 'Issue notes of GS/2026-27/0007' });
    const rows = within(notes).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(within(rows[0] as HTMLElement).getByRole('button', { name: /Receive/ })).toBeTruthy();
    expect(within(rows[1] as HTMLElement).queryByRole('button', { name: /Receive/ })).toBeNull();
    expect(apiRequest).toHaveBeenCalledWith('/department-routing/store/receiving', undefined);
  });

  it('filters to one goods slip when opened from My Work', async () => {
    apiRequest.mockImplementation(route);
    render(<StoreReceivingPage gsId="gs-1" onShowAll={noop} onOpenGs={noop} onOpenPrint={noop} />);
    expect(await screen.findByText('GS/2026-27/0007')).toBeTruthy();
    expect(apiRequest).toHaveBeenCalledWith(
      '/department-routing/store/receiving?gs_id=gs-1',
      undefined,
    );
    expect(screen.getByRole('button', { name: 'Show all goods slips' })).toBeTruthy();
    expect(itemPath('gs-store-receiving', { gs_id: 'gs-1', target_id: 'gs-1' })).toBe(
      '/store-receiving/gs-1',
    );
  });

  it('posts a partial receipt to the store endpoint with an Idempotency-Key', async () => {
    apiRequest.mockImplementation(route);
    render(<StoreReceivingPage onShowAll={noop} onOpenGs={noop} onOpenPrint={noop} />);
    const notes = await screen.findByRole('list', { name: 'Issue notes of GS/2026-27/0007' });
    fireEvent.click(within(notes).getAllByRole('button', { name: /Receive/ })[0] as HTMLElement);
    const dialog = await screen.findByRole('dialog');
    await within(dialog).findByLabelText('Qty');
    expect(within(dialog).getByText(/Stock goes back to Intermediate Store DT\./)).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText('Qty'), { target: { value: '1' } });
    fireEvent.change(within(dialog).getByLabelText('Condition after work'), {
      target: { value: 'c-bad' },
    });
    fireEvent.change(within(dialog).getByLabelText('Outcome'), {
      target: { value: 'h-reroute' },
    });
    expect(within(dialog).getByText(/Back to your store for routing again\./)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: /Confirm receipt \(1 pcs\)/ }));
    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledWith('/department-routing/store/routings/din-1/receive', {
        method: 'POST',
        body: {
          lines: [
            {
              routing_line_id: 'rl-1',
              outcome_head_id: 'h-reroute',
              quantity: 1,
              condition_field_id: 'c-bad',
              remarks: undefined,
            },
          ],
          remarks: undefined,
        },
        idempotencyKey: 'web-test-key',
      });
    });
    expect(await screen.findByText(/Receipt recorded for DIN\/2026-27\/00001/)).toBeTruthy();
  });

  it('shows the error with a retry when the queue cannot load', async () => {
    apiRequest.mockRejectedValue(new Error('boom'));
    render(<StoreReceivingPage onShowAll={noop} onOpenGs={noop} onOpenPrint={noop} />);
    expect(await screen.findByText(/Could not load the receiving queue/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /Retry/ })).toBeTruthy();
  });
});
