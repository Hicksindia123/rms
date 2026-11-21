/**
 * Phase P7 (DEC-67; Q14, Q29): the Intermediate Store user routes its own lines of a goods slip
 * per item + condition; the other stores' items show read-only behind a toggle. Saving is the issue
 * (DIN per department). Rendered from backend-shaped payloads
 * (backend/app/modules/department_routing/schemas.py Store* models); only the HTTP layer is mocked.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const apiRequest = vi.fn<(path: string, options?: Record<string, unknown>) => Promise<unknown>>();
vi.mock('@/lib/api/client', () => ({
  apiRequest: (path: string, options?: Record<string, unknown>) => apiRequest(path, options),
  newIdempotencyKey: () => 'web-test-key',
  toApiError: (err: unknown) => ({
    message: err instanceof Error ? err.message : String(err),
    requestId: 'req-p7',
  }),
}));

import { StoreRoutingGsPage } from '@/features/department-routing/StoreRoutingGsPage';
import { StoreRoutingQueuePage } from '@/features/department-routing/StoreRoutingQueuePage';
import { entryPath, itemPath } from '@/features/journey/screens';

const DT = { id: 's-dt', code: 'DT', name: 'Intermediate Store DT' };
const OP = { id: 's-op', code: 'OP', name: 'Intermediate Store OP' };

function progress(store: typeof DT, status: string, isMine: boolean, unrouted = 3) {
  return {
    store_id: store.id,
    store_code: store.code,
    store_name: store.name,
    total_qty: 3,
    unrouted_qty: unrouted,
    at_dept_qty: 0,
    no_work_qty: 0,
    status,
    is_mine: isMine,
  };
}

const DEPTS = [
  {
    field_id: 'd-store',
    code: 'STORE',
    label: 'Issue to Store',
    is_no_work: true,
  },
  { field_id: 'd-clean', code: 'CLEANING', label: 'Cleaning (Production)', is_no_work: false },
];

function gsView(extra: Record<string, unknown> = {}) {
  return {
    gs_id: 'gs-1',
    gs_no: 'GS/2026-27/0007',
    status: 'STORE_ACKNOWLEDGED',
    party_name: 'Acme Pharma',
    station_name: 'Agra',
    stores: [
      progress(DT, 'ROUTING_PENDING', true),
      progress(OP, 'AWAITING_ACKNOWLEDGEMENT', false, 1),
    ],
    items: [
      {
        item_id: 'i-dt',
        line_no: 1,
        item_name: 'Digital thermometer',
        sku_code: 'DMT-1',
        store: DT,
        is_mine: true,
        acknowledged: true,
        received_qty: 3,
        routable_qty: 3,
        at_departments_qty: 0,
        conditions: [
          {
            field_id: 'c-ok',
            field_code: 'VISUALLY_OKAY_SELLABLE',
            field_label: 'VISUALLY OKAY SELLABLE',
            original_qty: 2,
            current_qty: 2,
            routable_qty: 2,
          },
          {
            field_id: 'c-dirty',
            field_code: 'SCRATCHED_DIRTY',
            field_label: 'SCRATCHED / DIRTY',
            original_qty: 1,
            current_qty: 1,
            routable_qty: 1,
          },
        ],
        allowed_departments: DEPTS,
        routed: [],
        undoable_line_ids: [],
      },
      {
        item_id: 'i-op',
        line_no: 2,
        item_name: 'Oval thermometer',
        sku_code: 'OVL-1',
        store: OP,
        is_mine: false,
        acknowledged: false,
        received_qty: 1,
        routable_qty: 0,
        at_departments_qty: 0,
        conditions: [],
        allowed_departments: [],
        routed: [],
        undoable_line_ids: [],
      },
    ],
    dins: [],
    can_route: true,
    ...extra,
  };
}

afterEach(() => {
  apiRequest.mockReset();
});

/** A quantity input of the routing grid (id = route-<item>|<condition>|<department>). */
function cell(id: string): HTMLElement {
  const el = document.getElementById(id);
  if (!el) throw new Error(`no input ${id}`);
  return el;
}

function renderGs() {
  const onOpenPrint = vi.fn();
  render(
    <StoreRoutingGsPage
      gsId="gs-1"
      onBack={vi.fn()}
      onOpenGs={vi.fn()}
      onOpenPrint={onOpenPrint}
    />,
  );
  return { onOpenPrint };
}

describe('StoreRoutingGsPage', () => {
  it('shows only the store’s own items until "Show all items" is ticked (read-only)', async () => {
    apiRequest.mockResolvedValue(gsView());
    renderGs();
    expect(await screen.findByText(/Digital thermometer/)).toBeInTheDocument();
    expect(screen.queryByText(/Oval thermometer/)).not.toBeInTheDocument();
    expect(screen.getByText('DT: Routing pending (3 pcs)')).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/Show all items of this GS/));
    const opCard = await screen.findByTestId('routing-item-2');
    expect(within(opCard).getByText('Intermediate Store OP')).toBeInTheDocument();
    expect(within(opCard).getByText('Not acknowledged')).toBeInTheDocument();
    expect(within(opCard).queryByRole('spinbutton')).not.toBeInTheDocument();
  });

  it('routes a condition split across departments and offers the DIN print', async () => {
    apiRequest.mockImplementation((_path, options) => {
      if (options?.method === 'POST') {
        return Promise.resolve({
          gs_id: 'gs-1',
          gs_status: 'STORE_PROCESSING',
          store: progress(DT, 'AT_DEPARTMENTS', true, 0),
          dins: [
            {
              id: 'r-1',
              routing_no: 'DIN/2026-27/0001',
              department_code: 'CLEANING',
              department_label: 'Cleaning (Production)',
              status: 'DISPATCHED',
              store_id: DT.id,
              store_code: 'DT',
              qty_sent: 1,
              qty_received: 0,
              dispatched_at: '2026-11-21T08:00:00Z',
              dispatched_by_name: 'Dinesh',
            },
          ],
          no_work_qty: 2,
        });
      }
      return Promise.resolve(gsView());
    });
    const { onOpenPrint } = renderGs();
    await screen.findByText(/Digital thermometer/);
    fireEvent.change(cell('route-i-dt|c-ok|d-store'), { target: { value: '2' } });
    fireEvent.change(cell('route-i-dt|c-dirty|d-clean'), { target: { value: '1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save routing' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('2 pcs')).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: /Save & issue/ }));

    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledWith(
        '/department-routing/store/gs/gs-1/route',
        expect.objectContaining({
          method: 'POST',
          idempotencyKey: 'web-test-key',
          body: {
            store_id: 's-dt',
            lines: [
              {
                gs_item_id: 'i-dt',
                source_bucket_field_id: 'c-ok',
                department_field_id: 'd-store',
                qty: 2,
              },
              {
                gs_item_id: 'i-dt',
                source_bucket_field_id: 'c-dirty',
                department_field_id: 'd-clean',
                qty: 1,
              },
            ],
          },
        }),
      );
    });
    const print = await screen.findByRole('button', { name: /DIN\/2026-27\/0001/ });
    fireEvent.click(print);
    expect(onOpenPrint).toHaveBeenCalledWith('r-1');
    expect(screen.getByText(/2 pc\(s\) stay in the store/)).toBeInTheDocument();
  });

  it('blocks routing more than a condition holds', async () => {
    apiRequest.mockResolvedValue(gsView());
    renderGs();
    await screen.findByText(/Digital thermometer/);
    fireEvent.change(cell('route-i-dt|c-dirty|d-store'), { target: { value: '2' } });
    expect(screen.getByRole('button', { name: 'Save routing' })).toBeDisabled();
    expect(screen.getByText('2 of 1 routed')).toBeInTheDocument();
  });

  it('shows the error with its request id and retries', async () => {
    apiRequest.mockRejectedValueOnce(
      new Error('Goods slip has no goods at your Intermediate Store'),
    );
    apiRequest.mockResolvedValueOnce(gsView());
    renderGs();
    expect(await screen.findByText(/no goods at your Intermediate Store/)).toBeInTheDocument();
    expect(screen.getByText(/req-p7/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Retry/ }));
    expect(await screen.findByText(/Digital thermometer/)).toBeInTheDocument();
  });
});

describe('StoreRoutingGsPage undo (Q32)', () => {
  it('undoes an own "Issue to Store" line with a reason', async () => {
    const routedLine = {
      id: 'pl-1',
      gs_id: 'gs-1',
      gs_no: 'GS/2026-27/0007',
      gs_item_id: 'i-dt',
      line_no: 1,
      item_name: 'Digital thermometer',
      source_bucket_field_id: 'c-ok',
      source_bucket_label: 'VISUALLY OKAY SELLABLE',
      department_field_id: 'd-store',
      department_code: 'STORE',
      department_label: 'Issue to Store',
      is_no_work: true,
      qty: 2,
      status: 'NO_WORK',
      planned_at: '2026-11-21T08:00:00Z',
      store_id: 's-dt',
      store_code: 'DT',
    };
    const routed = gsView();
    const item = (routed.items as Array<Record<string, unknown>>)[0] ?? {};
    item.routed = [routedLine];
    item.undoable_line_ids = ['pl-1'];
    apiRequest.mockImplementation((path, options) =>
      Promise.resolve(options?.method === 'POST' && path.endsWith('/undo') ? gsView() : routed),
    );
    renderGs();
    fireEvent.click(await screen.findByRole('button', { name: 'Undo' }));
    const confirm = screen.getByRole('button', { name: /Confirm undo/ });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText('Reason (required)'), {
      target: { value: 'Needs cleaning' },
    });
    fireEvent.click(confirm);
    await waitFor(() => {
      expect(apiRequest).toHaveBeenCalledWith('/department-routing/store/plan-lines/pl-1/undo', {
        method: 'POST',
        body: { reason: 'Needs cleaning' },
      });
    });
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument();
    });
  });
});

describe('StoreRoutingQueuePage', () => {
  it('lists goods slips with the store progress and opens one', async () => {
    apiRequest.mockResolvedValue([
      {
        gs_id: 'gs-1',
        gs_no: 'GS/2026-27/0007',
        status: 'STORE_ACKNOWLEDGED',
        party_name: 'Acme Pharma',
        station_name: 'Agra',
        since: '2026-11-21T07:00:00Z',
        stores: [progress(DT, 'ROUTING_PENDING', true)],
      },
    ]);
    const onOpenGs = vi.fn();
    render(<StoreRoutingQueuePage onOpenGs={onOpenGs} />);
    fireEvent.click(await screen.findByText('GS/2026-27/0007'));
    expect(onOpenGs).toHaveBeenCalledWith('gs-1');
    expect(apiRequest).toHaveBeenCalledWith(
      '/department-routing/store/queue?pending_only=true',
      undefined,
    );

    apiRequest.mockResolvedValue([]);
    fireEvent.click(screen.getByRole('button', { name: 'All on stores' }));
    expect(await screen.findByText('No goods slips on your stores')).toBeInTheDocument();
    expect(apiRequest).toHaveBeenLastCalledWith(
      '/department-routing/store/queue?pending_only=false',
      undefined,
    );
  });
});

describe('journey screens (DEC-67)', () => {
  it('maps the store routing menu and queue item', () => {
    expect(entryPath({ code: 'STORE_DEPT_ROUTING', screen_key: 'store-routing' })).toBe(
      '/store-routing',
    );
    expect(itemPath('gs-store-routing', { gs_id: 'gs-1', target_id: 'gs-1' })).toBe(
      '/store-routing/gs-1',
    );
  });
});
