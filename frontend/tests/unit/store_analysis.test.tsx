/**
 * Phase P9 (DEC-69; Q15): the Intermediate Store user analyses its goods of a goods slip per item
 * + condition (Dispatch New Piece / Dispatch Repaired Piece / Not Allowed), the split must total
 * the pieces (G-21) before "Submit analysis" is enabled, the submission posts with an
 * Idempotency-Key, and any store user may send the GS for Management approval with a reason.
 * Rendered from backend-shaped payloads (backend/app/modules/final_actions/schemas.py
 * StoreAnalysis*); only the HTTP layer is mocked.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const apiRequest = vi.fn<(path: string, options?: Record<string, unknown>) => Promise<unknown>>();
vi.mock('@/lib/api/client', () => ({
  apiRequest: (path: string, options?: Record<string, unknown>) => apiRequest(path, options),
  newIdempotencyKey: () => 'web-test-key',
  toApiError: (err: unknown) => ({
    message: err instanceof Error ? err.message : String(err),
    requestId: 'req-p9',
  }),
}));

import { StoreAnalysisGsPage } from '@/features/store-analysis/StoreAnalysisGsPage';
import { StoreAnalysisQueuePage } from '@/features/store-analysis/StoreAnalysisQueuePage';
import { itemPath } from '@/features/journey/screens';

const OPTIONS = [
  {
    code: 'SEND_NEW',
    label: 'Dispatch New Piece',
    requires_cn: false,
    requires_challan: true,
    sort_order: 10,
  },
  {
    code: 'SEND_REPAIRED',
    label: 'Dispatch Repaired Piece',
    requires_cn: false,
    requires_challan: true,
    sort_order: 20,
  },
  {
    code: 'NOT_ALLOWED',
    label: 'Not Allowed',
    requires_cn: false,
    requires_challan: false,
    sort_order: 40,
  },
];

const DT = {
  store_id: 's-dt',
  store_code: 'DT',
  store_name: 'Intermediate Store DT',
  routing_status: 'READY_FOR_ANALYSIS',
  analysis_status: 'PENDING',
  submitted_at: null,
  submitted_by_name: null,
  remarks: null,
  total_qty: null,
  is_mine: true,
};
const OP = {
  ...DT,
  store_id: 's-op',
  store_code: 'OP',
  store_name: 'Intermediate Store OP',
  routing_status: 'AT_DEPARTMENTS',
  analysis_status: 'NOT_READY',
  is_mine: false,
};

const GS = {
  gs_id: 'gs-1',
  gs_no: 'GS/2026-27/0009',
  status: 'STORE_PROCESSING',
  party_name: 'Acme Pharma',
  station_name: 'Agra',
  stores: [OP, DT],
  items: [
    {
      gs_item_id: 'i-1',
      line_no: 1,
      product_code: 'ITM-1',
      product_name: 'Digital thermometer',
      received_qty: 3,
      store_id: 's-dt',
      store_code: 'DT',
      store_name: 'Intermediate Store DT',
      is_mine: true,
      outcomes: [{ outcome_code: 'CLEANED', outcome_label: 'Cleaned', is_wastage: false, qty: 2 }],
      options: OPTIONS,
      groups: [
        {
          condition_field_id: 'c-a',
          condition_code: 'WORKING',
          condition_label: 'Working',
          qty: 2,
          decisions: [],
        },
        {
          condition_field_id: 'c-b',
          condition_code: 'BROKEN',
          condition_label: 'Broken',
          qty: 1,
          decisions: [],
        },
      ],
    },
    {
      gs_item_id: 'i-2',
      line_no: 2,
      product_code: 'ITM-2',
      product_name: 'Oval thermometer',
      received_qty: 1,
      store_id: 's-op',
      store_code: 'OP',
      store_name: 'Intermediate Store OP',
      is_mine: false,
      outcomes: [],
      options: OPTIONS,
      groups: [
        {
          condition_field_id: null,
          condition_code: null,
          condition_label: null,
          qty: 1,
          decisions: [],
        },
      ],
    },
  ],
  submittable_store_ids: ['s-dt'],
  // Q36: a store sends for Management approval only after its own submission.
  approval_store_ids: [],
  can_request_approval: false,
  open_approval_request: null,
  approval_requests: [],
};

/** Answers by path (StatusChip loads the status labels itself). A function gets the options. */
function serve(routes: Record<string, unknown>): void {
  apiRequest.mockImplementation((path, options) => {
    if (path === '/gs/lookups/statuses') return Promise.resolve([]);
    const hit = routes[path];
    if (hit === undefined) return Promise.reject(new Error(`unexpected ${path}`));
    const value: unknown =
      typeof hit === 'function' ? (hit as (o: unknown) => unknown)(options) : hit;
    return value instanceof Error ? Promise.reject(value) : Promise.resolve(value);
  });
}

const calls = (path: string) => apiRequest.mock.calls.filter(([p]) => p === path);

afterEach(() => {
  // Unmount first: a late StatusChip effect must not hit the reset (undefined-returning) mock.
  cleanup();
  apiRequest.mockReset();
});

describe('Store analysis (P9, DEC-69)', () => {
  it('opens a queue item on the analysis of its goods slip (My Work)', () => {
    expect(itemPath('gs-store-analysis', { gs_id: 'gs-1', target_id: 'gs-1' })).toBe(
      '/store-analysis/gs-1',
    );
  });

  it('lists the goods slips with each store state', async () => {
    serve({
      '/store-analysis/queue?pending_only=true': [
        {
          gs_id: 'gs-1',
          gs_no: 'GS/2026-27/0009',
          status: 'STORE_PROCESSING',
          party_name: 'Acme Pharma',
          station_name: 'Agra',
          since: '2026-11-23T10:00:00Z',
          approval_requested: true,
          stores: [DT],
        },
      ],
    });
    const onOpen = vi.fn();
    render(<StoreAnalysisQueuePage onOpenGs={onOpen} />);
    expect(await screen.findByText('GS/2026-27/0009')).toBeInTheDocument();
    expect(apiRequest).toHaveBeenCalledWith('/store-analysis/queue?pending_only=true', undefined);
    expect(screen.getByText('DT: Ready for analysis')).toBeInTheDocument();
    expect(screen.getByText('Sent for Management approval')).toBeInTheDocument();
    fireEvent.click(screen.getByText('GS/2026-27/0009'));
    expect(onOpen).toHaveBeenCalledWith('gs-1');
  });

  it('submits the store part only when every condition is fully decided (G-21)', async () => {
    const done = {
      ...GS,
      stores: [
        OP,
        { ...DT, analysis_status: 'SUBMITTED', total_qty: 3, submitted_by_name: 'Dinesh' },
      ],
      submittable_store_ids: [],
    };
    serve({ '/store-analysis/gs/gs-1': GS, '/store-analysis/gs/gs-1/submit': done });
    render(<StoreAnalysisGsPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    const item = await screen.findByTestId('analysis-item-1');
    // Only the store's own item by default; Issue CN is not an option.
    expect(screen.queryByTestId('analysis-item-2')).not.toBeInTheDocument();
    expect(within(item).queryByText(/Issue CN/)).not.toBeInTheDocument();
    const submit = screen.getByRole('button', { name: 'Submit analysis' });
    expect(submit).toBeDisabled();
    expect(
      screen.queryByRole('button', { name: /Send for Management Approval/ }),
    ).not.toBeInTheDocument();

    // Working: 1 new + 1 not allowed; Broken: all repaired (touch shortcut).
    fireEvent.change(within(item).getByLabelText('Dispatch New Piece, Working, item 1'), {
      target: { value: '1' },
    });
    expect(within(item).getByText('1 of 2 decided')).toBeInTheDocument();
    expect(submit).toBeDisabled();
    fireEvent.change(within(item).getByLabelText('Not Allowed, Working, item 1'), {
      target: { value: '1' },
    });
    fireEvent.click(
      within(item).getByRole('button', { name: 'All 1 pcs: Dispatch Repaired Piece' }),
    );
    expect(submit).toBeEnabled();

    fireEvent.click(submit);
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
    await screen.findByText(/Analysis submitted for/);
    const [submitCall] = calls('/store-analysis/gs/gs-1/submit');
    expect(submitCall?.[1]).toMatchObject({
      method: 'POST',
      idempotencyKey: 'web-test-key',
      body: {
        store_id: 's-dt',
        lines: [
          {
            gs_item_id: 'i-1',
            condition_field_id: 'c-a',
            decisions: [
              { action_code: 'SEND_NEW', qty: 1 },
              { action_code: 'NOT_ALLOWED', qty: 1 },
            ],
          },
          {
            gs_item_id: 'i-1',
            condition_field_id: 'c-b',
            decisions: [{ action_code: 'SEND_REPAIRED', qty: 1 }],
          },
        ],
      },
    });
    expect(screen.queryByRole('button', { name: 'Submit analysis' })).not.toBeInTheDocument();
  });

  it('shows the other stores read-only behind the toggle', async () => {
    serve({ '/store-analysis/gs/gs-1': GS });
    render(<StoreAnalysisGsPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    await screen.findByTestId('analysis-item-1');
    fireEvent.click(screen.getByLabelText(/Show all items of this GS/));
    const other = screen.getByTestId('analysis-item-2');
    expect(within(other).getByText('Intermediate Store OP')).toBeInTheDocument();
    expect(within(other).getByText('Not decided yet')).toBeInTheDocument();
    expect(within(other).queryByRole('spinbutton')).not.toBeInTheDocument();
  });

  it('sends the goods slip for Management approval with a reason (after submitting)', async () => {
    const submitted = {
      ...GS,
      stores: [OP, { ...DT, analysis_status: 'SUBMITTED', total_qty: 3 }],
      submittable_store_ids: [],
      approval_store_ids: ['s-dt'],
      can_request_approval: true,
    };
    serve({
      '/store-analysis/gs/gs-1': submitted,
      '/store-analysis/gs/gs-1/management-approval': {
        ...GS,
        can_request_approval: false,
        open_approval_request: {
          id: 'r-1',
          store_id: 's-dt',
          store_name: 'Intermediate Store DT',
          reason: 'Party asks for a credit note',
          status: 'OPEN',
          requested_at: '2026-11-23T11:00:00Z',
          requested_by_name: 'Dinesh',
        },
      },
    });
    render(<StoreAnalysisGsPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    await screen.findByTestId('analysis-item-1');
    fireEvent.click(screen.getByRole('button', { name: /Send for Management Approval/ }));
    const send = screen.getByRole('button', { name: 'Send' });
    expect(send).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Reason (required)'), {
      target: { value: 'Party asks for a credit note' },
    });
    fireEvent.click(send);
    expect(await screen.findByTestId('approval-request')).toHaveTextContent(
      'Party asks for a credit note',
    );
    expect(calls('/store-analysis/gs/gs-1/management-approval')[0]?.[1]).toEqual({
      method: 'POST',
      body: { store_id: 's-dt', reason: 'Party asks for a credit note' },
      idempotencyKey: 'web-test-key',
    });
    await waitFor(() => {
      expect(
        screen.queryByRole('button', { name: /Send for Management Approval/ }),
      ).not.toBeInTheDocument();
    });
  });

  it('shows the error with the request id and keeps the decisions', async () => {
    serve({
      '/store-analysis/gs/gs-1': GS,
      '/store-analysis/gs/gs-1/submit': new Error('G-21: decisions total 2 pc(s)'),
    });
    render(<StoreAnalysisGsPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    const item = await screen.findByTestId('analysis-item-1');
    fireEvent.click(within(item).getByRole('button', { name: 'All 2 pcs: Not Allowed' }));
    fireEvent.click(within(item).getByRole('button', { name: 'All 1 pcs: Not Allowed' }));
    fireEvent.click(screen.getByRole('button', { name: 'Submit analysis' }));
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
    expect(await screen.findByText('The analysis was not submitted')).toBeInTheDocument();
    expect(screen.getByText(/G-21: decisions total 2 pc\(s\)/)).toBeInTheDocument();
    expect(within(item).getByText('2 of 2 decided')).toBeInTheDocument();
  });
});

describe('Issue CN Request (DEC-74)', () => {
  const CN_OPTION = {
    code: 'ISSUE_CN_REQUEST',
    label: 'Issue CN Request',
    requires_cn: false,
    requires_challan: false,
    sort_order: 35,
    is_cn_request: true,
  };
  const WITH_CN = {
    ...GS,
    items: GS.items.map((it) => ({ ...it, options: [...OPTIONS, CN_OPTION] })),
  };

  it('sends the requested pieces to Management with the submission (optional note)', async () => {
    const done = {
      ...WITH_CN,
      stores: [OP, { ...DT, analysis_status: 'SUBMITTED', total_qty: 3 }],
      submittable_store_ids: [],
    };
    serve({ '/store-analysis/gs/gs-1': WITH_CN, '/store-analysis/gs/gs-1/submit': done });
    render(<StoreAnalysisGsPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    const item = await screen.findByTestId('analysis-item-1');
    // A 4th option; Issue CN itself is still not offered.
    expect(within(item).getAllByText('Issue CN Request')).toHaveLength(2);
    expect(within(item).queryByText('Issue CN')).not.toBeInTheDocument();

    fireEvent.change(within(item).getByLabelText('Dispatch New Piece, Working, item 1'), {
      target: { value: '1' },
    });
    fireEvent.change(within(item).getByLabelText('Issue CN Request, Working, item 1'), {
      target: { value: '1' },
    });
    fireEvent.click(within(item).getByRole('button', { name: 'All 1 pcs: Issue CN Request' }));
    fireEvent.click(screen.getByRole('button', { name: 'Submit analysis' }));

    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByTestId('cn-request-notice')).toHaveTextContent(
      '2 pc(s) go to Management as an Issue CN Request',
    );
    // No "Also send" checkbox: the CN request goes to Management anyway.
    expect(within(dialog).queryByLabelText('Also send for Management approval')).toBeNull();
    const send = within(dialog).getByRole('button', { name: 'Submit & send CN request' });
    const note = within(dialog).getByLabelText('Note for Management (optional)');
    fireEvent.change(note, { target: { value: 'ab' } });
    expect(send).toBeDisabled();
    fireEvent.change(note, { target: { value: 'Party insists' } });
    expect(send).toBeEnabled();
    fireEvent.click(send);
    await screen.findByText(/Analysis submitted for/);
    expect(calls('/store-analysis/gs/gs-1/submit')[0]?.[1]).toMatchObject({
      body: {
        store_id: 's-dt',
        management_approval_reason: 'Party insists',
        lines: [
          {
            condition_field_id: 'c-a',
            decisions: [
              { action_code: 'SEND_NEW', qty: 1 },
              { action_code: 'ISSUE_CN_REQUEST', qty: 1 },
            ],
          },
          {
            condition_field_id: 'c-b',
            decisions: [{ action_code: 'ISSUE_CN_REQUEST', qty: 1 }],
          },
        ],
      },
    });
  });
});
