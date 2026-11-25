/**
 * Store analysis (DEC-69, DEC-75): the Intermediate Store user first splits each item + condition
 * into Allowed / Not Allowed, then the Allowed pieces between Send New / Send Repaired (G-21), and
 * may send pieces to Management with a proposal, with the submission or later. Rendered from
 * backend-shaped payloads (backend/app/modules/final_actions/schemas.py StoreAnalysis*); only the
 * HTTP layer is mocked.
 */
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
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
    label: 'Send New Pieces to Party',
    requires_cn: false,
    requires_challan: true,
    sort_order: 10,
  },
  {
    code: 'SEND_REPAIRED',
    label: 'Send Repaired Pieces to Party',
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

const VERDICTS = {
  allowed: { label: 'Allowed', actions: ['SEND_NEW', 'SEND_REPAIRED'] },
  not_allowed: { label: 'Not Allowed', actions: ['NOT_ALLOWED'] },
};
const PROPOSALS = [
  { code: 'SEND_NEW', label: 'Send New Pieces to Party' },
  { code: 'ISSUE_CN', label: 'Issue CN' },
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
  approval_store_ids: [],
  can_request_approval: false,
  can_send_to_management: false,
  open_approval_request: null,
  approval_requests: [],
  verdicts: VERDICTS,
  proposals: PROPOSALS,
  request_lines: [],
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

describe('Store analysis (DEC-69, DEC-75)', () => {
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

  it('decides Allowed / Not Allowed first, then splits the Allowed pieces (G-21)', async () => {
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
    // Only the store's own item by default; Issue CN is never a store option.
    expect(screen.queryByTestId('analysis-item-2')).not.toBeInTheDocument();
    expect(within(item).queryByText(/Issue CN/)).not.toBeInTheDocument();
    // Step 1 shows the two verdicts only; the Allowed actions appear after a verdict.
    expect(within(item).getAllByText('Allowed')).toHaveLength(2);
    expect(within(item).queryByText('Send New Pieces to Party')).not.toBeInTheDocument();
    const review = screen.getByRole('button', { name: /Review & submit/ });
    expect(review).toBeDisabled();

    // Working (2 pcs): 1 Allowed (→ 1 Not Allowed), the Allowed piece goes as a new piece.
    fireEvent.change(within(item).getByLabelText('Allowed pieces, Working, item 1'), {
      target: { value: '1' },
    });
    expect(within(item).getByLabelText('Not Allowed pieces, Working, item 1')).toHaveTextContent(
      '1',
    );
    expect(review).toBeDisabled(); // the Allowed piece is not split yet
    fireEvent.click(
      within(item).getByRole('button', { name: 'All 1 allowed pcs: Send New Pieces to Party' }),
    );
    // Broken (1 pc): all Allowed, sent repaired.
    fireEvent.click(within(item).getByRole('button', { name: 'All 1 pcs Allowed' }));
    const allowedRepaired = within(item).getAllByRole('button', {
      name: 'All 1 allowed pcs: Send Repaired Pieces to Party',
    });
    fireEvent.click(allowedRepaired[allowedRepaired.length - 1] as HTMLElement);
    expect(review).toBeEnabled();

    fireEvent.click(review);
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByTestId('mgmt-summary')).toHaveTextContent(
      'Nothing goes to Management',
    );
    fireEvent.click(within(dialog).getByRole('button', { name: 'Submit analysis' }));
    await screen.findByText(/Analysis submitted for/);
    const [submitCall] = calls('/store-analysis/gs/gs-1/submit');
    expect(submitCall?.[1]).toMatchObject({
      method: 'POST',
      idempotencyKey: 'web-test-key',
      body: {
        store_id: 's-dt',
        management_lines: [],
        management_approval_reason: null,
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
    expect(screen.queryByRole('button', { name: /Review & submit/ })).not.toBeInTheDocument();
  });

  it('shows the other stores read-only behind the toggle', async () => {
    serve({ '/store-analysis/gs/gs-1': GS });
    render(<StoreAnalysisGsPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    await screen.findByTestId('analysis-item-1');
    fireEvent.click(screen.getByLabelText(/Show all items of this goods slip/));
    const other = screen.getByTestId('analysis-item-2');
    expect(within(other).getByText('Intermediate Store OP')).toBeInTheDocument();
    expect(within(other).getByText('Not decided yet')).toBeInTheDocument();
    expect(within(other).queryByRole('spinbutton')).not.toBeInTheDocument();
  });

  it('sends selected pieces to Management with the submission (optional note)', async () => {
    const done = {
      ...GS,
      stores: [OP, { ...DT, analysis_status: 'SUBMITTED', total_qty: 3 }],
      submittable_store_ids: [],
    };
    serve({ '/store-analysis/gs/gs-1': GS, '/store-analysis/gs/gs-1/submit': done });
    render(<StoreAnalysisGsPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    const item = await screen.findByTestId('analysis-item-1');
    fireEvent.click(within(item).getByRole('button', { name: 'All 2 pcs Allowed' }));
    fireEvent.click(
      within(item).getByRole('button', { name: 'All 2 allowed pcs: Send New Pieces to Party' }),
    );
    fireEvent.click(within(item).getByRole('button', { name: 'All 1 pcs Not Allowed' }));
    fireEvent.click(screen.getByRole('button', { name: /Review & submit/ }));

    const dialog = screen.getByRole('dialog');
    const row = within(dialog).getByTestId('mgmt-pick-i-1|c-b|NOT_ALLOWED');
    expect(row).toHaveTextContent('Currently Not Allowed');
    fireEvent.click(
      within(row).getByRole('button', {
        name: 'Increase Pieces to send, item 1, Broken, Not Allowed',
      }),
    );
    const send = within(dialog).getByRole('button', { name: 'Submit & send to Management' });
    expect(send).toBeDisabled(); // no proposal chosen yet
    fireEvent.click(within(row).getByRole('radio', { name: 'Issue CN' }));
    expect(within(dialog).getByTestId('mgmt-summary')).toHaveTextContent(
      '1 item(s) · 1 pcs go to Management',
    );
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
        management_lines: [
          {
            gs_item_id: 'i-1',
            condition_field_id: 'c-b',
            from_action_code: 'NOT_ALLOWED',
            proposed_action_code: 'ISSUE_CN',
            qty: 1,
          },
        ],
      },
    });
  });

  it('sends pieces to Management after the submission', async () => {
    const submitted = {
      ...GS,
      stores: [OP, { ...DT, analysis_status: 'SUBMITTED', total_qty: 3 }],
      submittable_store_ids: [],
      approval_store_ids: ['s-dt'],
      can_request_approval: true,
      can_send_to_management: true,
      items: GS.items.map((it) =>
        it.gs_item_id !== 'i-1'
          ? it
          : {
              ...it,
              groups: [
                {
                  ...it.groups[0],
                  decisions: [{ action_code: 'NOT_ALLOWED', label: 'Not Allowed', qty: 2 }],
                  sendable: [
                    { action_code: 'NOT_ALLOWED', label: 'Not Allowed', qty: 2, free_qty: 2 },
                  ],
                },
                {
                  ...it.groups[1],
                  decisions: [
                    { action_code: 'SEND_NEW', label: 'Send New Pieces to Party', qty: 1 },
                  ],
                  sendable: [
                    {
                      action_code: 'SEND_NEW',
                      label: 'Send New Pieces to Party',
                      qty: 1,
                      free_qty: 1,
                    },
                  ],
                },
              ],
            },
      ),
    };
    const LINE = {
      id: 'l-1',
      request_id: 'r-1',
      request_status: 'OPEN',
      gs_item_id: 'i-1',
      line_no: 1,
      product_name: 'Digital thermometer',
      condition_field_id: 'c-a',
      condition_label: 'Working',
      store_id: 's-dt',
      store_name: 'Intermediate Store DT',
      from_action_code: 'NOT_ALLOWED',
      from_action_label: 'Not Allowed',
      proposed_action_code: 'ISSUE_CN',
      proposed_action_label: 'Issue CN',
      qty: 2,
      requested_at: '2026-11-25T11:00:00Z',
      requested_by_name: 'Dinesh',
    };
    serve({
      '/store-analysis/gs/gs-1': submitted,
      '/store-analysis/gs/gs-1/management-approval': { ...submitted, request_lines: [LINE] },
    });
    render(<StoreAnalysisGsPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    await screen.findByTestId('analysis-item-1');
    fireEvent.click(screen.getByRole('button', { name: /Send for Management approval/ }));
    const dialog = screen.getByRole('dialog');
    const send = within(dialog).getByRole('button', { name: 'Send' });
    expect(send).toBeDisabled();
    const row = within(dialog).getByTestId('mgmt-pick-i-1|c-a|NOT_ALLOWED');
    fireEvent.change(within(row).getByLabelText('Pieces to send, item 1, Working, Not Allowed'), {
      target: { value: '2' },
    });
    fireEvent.click(within(row).getByRole('radio', { name: 'Issue CN' }));
    expect(within(dialog).getByText('1 item(s) · 2 pcs')).toBeInTheDocument();
    fireEvent.click(send);
    expect(await screen.findByTestId('approval-request')).toHaveTextContent(
      '2 pcs Not Allowed → Issue CN',
    );
    expect(calls('/store-analysis/gs/gs-1/management-approval')[0]?.[1]).toEqual({
      method: 'POST',
      body: {
        lines: [
          {
            gs_item_id: 'i-1',
            condition_field_id: 'c-a',
            from_action_code: 'NOT_ALLOWED',
            proposed_action_code: 'ISSUE_CN',
            qty: 2,
          },
        ],
        reason: null,
      },
      idempotencyKey: 'web-test-key',
    });
  });

  it('shows the error with the request id and keeps the decisions', async () => {
    serve({
      '/store-analysis/gs/gs-1': GS,
      '/store-analysis/gs/gs-1/submit': new Error('Decisions total 2 pc(s)'),
    });
    render(<StoreAnalysisGsPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    const item = await screen.findByTestId('analysis-item-1');
    fireEvent.click(within(item).getByRole('button', { name: 'All 2 pcs Not Allowed' }));
    fireEvent.click(within(item).getByRole('button', { name: 'All 1 pcs Not Allowed' }));
    fireEvent.click(screen.getByRole('button', { name: /Review & submit/ }));
    fireEvent.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Submit analysis' }),
    );
    expect(await screen.findByText('The analysis was not submitted')).toBeInTheDocument();
    expect(screen.getByText(/Decisions total 2 pc\(s\)/)).toBeInTheDocument();
    expect(screen.getByText(/req-p9/)).toBeInTheDocument();
    expect(within(item).getAllByText('Decided')).toHaveLength(2);
  });
});
