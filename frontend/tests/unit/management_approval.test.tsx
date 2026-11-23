/**
 * Phase P10 (DEC-70; Q17, Q18): Management reviews an analysed goods slip, changes any decision
 * (incl. Issue CN; a reason per change; the item + condition must still total its pieces, G-21),
 * saves the changes with an Idempotency-Key, approves (e-approval stamp) and verifies the stamp.
 * Rendered from backend-shaped payloads (backend/app/modules/management_approval/schemas.py); only
 * the HTTP layer is mocked.
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const apiRequest = vi.fn<(path: string, options?: Record<string, unknown>) => Promise<unknown>>();
vi.mock('@/lib/api/client', () => ({
  apiRequest: (path: string, options?: Record<string, unknown>) => apiRequest(path, options),
  newIdempotencyKey: () => 'web-test-key',
  toApiError: (err: unknown) => ({
    message: err instanceof Error ? err.message : String(err),
    requestId: 'req-p10',
  }),
}));

import { ManagementApprovalGsPage } from '@/features/management-approval/ManagementApprovalGsPage';
import { ManagementApprovalQueuePage } from '@/features/management-approval/ManagementApprovalQueuePage';
import { StampPanel } from '@/features/management-approval/ApprovalStamp';
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
    code: 'ISSUE_CN',
    label: 'Issue CN',
    requires_cn: true,
    requires_challan: false,
    sort_order: 30,
  },
  {
    code: 'NOT_ALLOWED',
    label: 'Not Allowed',
    requires_cn: false,
    requires_challan: false,
    sort_order: 40,
  },
];

const DISCLAIMER = 'System e-approval: non-official, non-legal.';
const REQUEST = {
  id: 'r-1',
  store_id: 's-dt',
  store_name: 'Intermediate Store DT',
  reason: 'Party asks for a credit note',
  status: 'OPEN',
  requested_at: '2026-11-23T11:00:00Z',
  requested_by_name: 'Dinesh',
};
const APPROVAL = {
  id: 'a-1',
  approval_no: 1,
  approver_name: 'Mgmt',
  approver_role: 'Management',
  approved_at: '2026-11-23T12:00:00Z',
  revision_no: 3,
  snapshot_sha256: 'abcdef0123456789'.repeat(4),
  short_ref: 'abcdef012345',
  has_issue_cn: true,
  remarks: null,
  request_id: 'r-1',
};

const GS = {
  gs_id: 'gs-1',
  gs_no: 'GS/2026-27/0010',
  status: 'ANALYSIS_COMPLETED',
  party_name: 'Acme Pharma',
  station_name: 'Agra',
  stores: [
    {
      store_id: 's-dt',
      store_code: 'DT',
      store_name: 'Intermediate Store DT',
      analysis_status: 'SUBMITTED',
    },
  ],
  items: [
    {
      gs_item_id: 'i-1',
      line_no: 1,
      product_code: 'ITM-1',
      product_name: 'Digital thermometer',
      received_qty: 2,
      store_code: 'DT',
      store_name: 'Intermediate Store DT',
      options: OPTIONS,
      groups: [
        {
          condition_field_id: 'c-a',
          condition_code: 'WORKING',
          condition_label: 'Working',
          qty: 2,
          decisions: [{ action_code: 'SEND_NEW', label: 'Dispatch New Piece', qty: 2 }],
        },
      ],
    },
  ],
  can_edit: true,
  can_approve: true,
  blocked_reason: null,
  open_request: REQUEST,
  requests: [REQUEST],
  revisions: [],
  approvals: [],
  stamp: {
    gs_id: 'gs-1',
    gs_no: 'GS/2026-27/0010',
    state: 'NONE',
    approval: null,
    stamp_text: null,
    disclaimer: DISCLAIMER,
  },
  accounts_gate: {
    passes: false,
    problem: 'DEC-70: the goods slip waits for Management approval (sent by a store)',
  },
};

const CHANGED_GS = {
  ...GS,
  items: [
    {
      ...GS.items[0],
      groups: [
        {
          condition_field_id: 'c-a',
          condition_code: 'WORKING',
          condition_label: 'Working',
          qty: 2,
          decisions: [
            { action_code: 'ISSUE_CN', label: 'Issue CN', qty: 1 },
            { action_code: 'SEND_NEW', label: 'Dispatch New Piece', qty: 1 },
          ],
        },
      ],
    },
  ],
  revisions: [
    {
      revision_no: 3,
      made_at: '2026-11-23T11:30:00Z',
      made_by_name: 'Mgmt',
      changes: [
        {
          line_no: 1,
          product_name: 'Digital thermometer',
          condition_label: 'Working',
          before: [{ action_code: 'SEND_NEW', label: 'Dispatch New Piece', qty: 2 }],
          after: [
            { action_code: 'ISSUE_CN', label: 'Issue CN', qty: 1 },
            { action_code: 'SEND_NEW', label: 'Dispatch New Piece', qty: 1 },
          ],
          reason: 'Credit for one piece',
        },
      ],
    },
  ],
};

const STAMP_TEXT = 'Digitally approved by Management — Mgmt, 23-11-2026 17:30, ref abcdef012345';
const APPROVED_GS = {
  ...CHANGED_GS,
  open_request: null,
  requests: [{ ...REQUEST, status: 'RESOLVED', resolved_by_name: 'Mgmt', approval_id: 'a-1' }],
  approvals: [APPROVAL],
  stamp: {
    gs_id: 'gs-1',
    gs_no: GS.gs_no,
    state: 'VALID',
    approval: APPROVAL,
    stamp_text: STAMP_TEXT,
    disclaimer: DISCLAIMER,
  },
  accounts_gate: { passes: true, problem: null },
};

/** Answers by path (StatusChip loads the status labels itself). */
function serve(routes: Record<string, unknown>): void {
  apiRequest.mockImplementation((path) => {
    if (path === '/gs/lookups/statuses') return Promise.resolve([]);
    const hit = routes[path];
    if (hit === undefined) return Promise.reject(new Error(`unexpected ${path}`));
    return hit instanceof Error ? Promise.reject(hit) : Promise.resolve(hit);
  });
}

const calls = (path: string) => apiRequest.mock.calls.filter(([p]) => p === path);

afterEach(() => {
  apiRequest.mockReset();
});

describe('Management approval (P10, DEC-70)', () => {
  it('opens a My Work item on the Management page of its goods slip', () => {
    expect(itemPath('gs-management-approval', { gs_id: 'gs-1', target_id: 'gs-1' })).toBe(
      '/management-approval/gs-1',
    );
  });

  it('lists the requests first with their reason, then searches', async () => {
    serve({
      '/management-approval/queue': [
        {
          gs_id: 'gs-1',
          gs_no: 'GS/2026-27/0010',
          status: 'ANALYSIS_COMPLETED',
          party_name: 'Acme Pharma',
          station_name: 'Agra',
          request_id: 'r-1',
          request_reason: 'Party asks for a credit note',
          request_store_name: 'Intermediate Store DT',
          requested_at: '2026-11-23T11:00:00Z',
          requested_by_name: 'Dinesh',
          approval_state: 'NONE',
          has_issue_cn: false,
          waiting_store_codes: [],
        },
      ],
      '/management-approval/queue?q=0010': [],
    });
    const onOpen = vi.fn();
    render(<ManagementApprovalQueuePage onOpenGs={onOpen} />);
    const sent = await screen.findByRole('list', { name: 'Sent for approval' });
    expect(within(sent).getByText(/Party asks for a credit note/)).toBeInTheDocument();
    fireEvent.click(within(sent).getByText('GS/2026-27/0010'));
    expect(onOpen).toHaveBeenCalledWith('gs-1');

    fireEvent.change(screen.getByLabelText('Search goods slips'), { target: { value: '0010' } });
    fireEvent.click(screen.getByRole('button', { name: /Search/ }));
    expect(await screen.findByText('No goods slip found')).toBeInTheDocument();
  });

  it('changes a decision to Issue CN with a reason, then approves (stamp + verify)', async () => {
    serve({
      '/management-approval/gs/gs-1': GS,
      '/management-approval/gs/gs-1/changes': CHANGED_GS,
      '/management-approval/gs/gs-1/approve': APPROVED_GS,
      '/management-approval/gs/gs-1/verify': {
        gs_id: 'gs-1',
        result: 'VALID',
        approval: APPROVAL,
        stored_sha256: APPROVAL.snapshot_sha256,
        current_sha256: APPROVAL.snapshot_sha256,
        integrity_ok: true,
        checked_at: '2026-11-23T12:05:00Z',
      },
    });
    render(<ManagementApprovalGsPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    const item = await screen.findByTestId('mgmt-item-1');
    expect(screen.getByTestId('open-request')).toHaveTextContent('Party asks for a credit note');
    const save = screen.getByRole('button', { name: 'Save changes' });
    const approve = screen.getByRole('button', { name: 'Approve' });
    expect(save).toBeDisabled();

    // 1 new + 1 Issue CN: the group totals (2 of 2) but the change needs a reason.
    fireEvent.change(within(item).getByLabelText('Dispatch New Piece, Working, item 1'), {
      target: { value: '1' },
    });
    expect(within(item).getByText('1 of 2 decided')).toBeInTheDocument();
    fireEvent.change(within(item).getByLabelText('Issue CN, Working, item 1'), {
      target: { value: '1' },
    });
    expect(within(item).getByText('2 of 2 decided')).toBeInTheDocument();
    expect(save).toBeDisabled();
    expect(approve).toBeDisabled(); // unsaved changes are never approved
    fireEvent.change(within(item).getByLabelText('Reason for this change (required)'), {
      target: { value: 'Credit for one piece' },
    });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    expect(await screen.findByText(/Changes saved/)).toBeInTheDocument();
    expect(calls('/management-approval/gs/gs-1/changes')[0]?.[1]).toEqual({
      method: 'POST',
      idempotencyKey: 'web-test-key',
      body: {
        changes: [
          {
            gs_item_id: 'i-1',
            condition_field_id: 'c-a',
            decisions: [
              { action_code: 'SEND_NEW', qty: 1 },
              { action_code: 'ISSUE_CN', qty: 1 },
            ],
            reason: 'Credit for one piece',
          },
        ],
      },
    });
    expect(screen.getByText(/“Credit for one piece”/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText(DISCLAIMER)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Approve' }));
    expect(await screen.findByTestId('stamp-text')).toHaveTextContent(STAMP_TEXT);
    expect(calls('/management-approval/gs/gs-1/approve')[0]?.[1]).toEqual({
      method: 'POST',
      body: { remarks: null },
      idempotencyKey: 'web-test-key',
    });
    // Approved as it is: Approve is off until something changes.
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Verify' }));
    expect(await screen.findByTestId('verify-result')).toHaveTextContent(/^Valid/);
  });

  it('keeps the page read-only while stores are still analysing', async () => {
    serve({
      '/management-approval/gs/gs-1': {
        ...GS,
        status: 'STORE_PROCESSING',
        can_edit: false,
        can_approve: false,
        blocked_reason:
          'Waiting for the analysis of OP; Management changes and approves the goods slip once every store has submitted.',
      },
    });
    render(<ManagementApprovalGsPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    const item = await screen.findByTestId('mgmt-item-1');
    expect(screen.getByText(/Waiting for the analysis of OP/)).toBeInTheDocument();
    expect(within(item).queryByRole('spinbutton')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();
  });

  it('warns that a change reopens a goods slip at Accounts; no Approve there (DEC-71)', async () => {
    serve({
      '/management-approval/gs/gs-1': {
        ...GS,
        status: 'ACCOUNTS_PENDING',
        can_edit: true,
        can_approve: false,
        reopen_notice:
          'The goods slip is at Accounts: saving a change withdraws its Replacement Slip until you approve it again.',
      },
    });
    render(<ManagementApprovalGsPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    expect(await screen.findByTestId('reopen-notice')).toHaveTextContent(
      'withdraws its Replacement Slip',
    );
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();
  });

  it('shows the error with the request id and keeps the draft', async () => {
    serve({
      '/management-approval/gs/gs-1': GS,
      '/management-approval/gs/gs-1/changes': new Error('G-21: decisions total 1 pc(s)'),
    });
    render(<ManagementApprovalGsPage gsId="gs-1" onBack={vi.fn()} onOpenGs={vi.fn()} />);
    const item = await screen.findByTestId('mgmt-item-1');
    fireEvent.click(within(item).getByRole('button', { name: 'All 2 pcs: Issue CN' }));
    fireEvent.change(within(item).getByLabelText('Reason for this change (required)'), {
      target: { value: 'credit' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByText('The changes were not saved')).toBeInTheDocument();
    expect(screen.getByText(/G-21: decisions total 1 pc\(s\)/)).toBeInTheDocument();
    expect(within(item).getByLabelText('Issue CN, Working, item 1')).toHaveValue(2);
  });

  it('shows a changed approval on the goods slip page (and nothing before analysis)', async () => {
    serve({
      '/management-approval/gs/gs-1/stamp': {
        gs_id: 'gs-1',
        gs_no: GS.gs_no,
        state: 'CHANGED',
        approval: APPROVAL,
        stamp_text: null,
        disclaimer: DISCLAIMER,
      },
    });
    const { unmount } = render(<StampPanel gsId="gs-1" status="ANALYSIS_COMPLETED" />);
    expect(await screen.findByText(/Changed after the Management approval/)).toBeInTheDocument();
    unmount();
    apiRequest.mockClear();
    render(<StampPanel gsId="gs-1" status="STORE_PROCESSING" />);
    expect(calls('/management-approval/gs/gs-1/stamp')).toHaveLength(0);
  });
});
