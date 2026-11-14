import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { acEntryApi, dispatchSlipsApi } from '@/features/ac-entry/api';
import { AccountsEntryPage } from '@/features/ac-entry/AccountsEntryPage';
import { AccountsEntryQueuePage } from '@/features/ac-entry/AccountsEntryQueuePage';
import { DispatchSlipsPage } from '@/features/ac-entry/DispatchSlipsPage';
import {
  dispatchIssue,
  draftComplete,
  draftIssues,
  initialDrafts,
  isDirty,
  localToday,
  toDraft,
  toSaveLines,
} from '@/features/ac-entry/rules';
import type { AcEntryLine, AcEntryState, DispatchSlipOut } from '@/features/ac-entry/types';
import { notificationPath } from '@/features/notifications/links';
import { ApiError } from '@/lib/api/client';

vi.mock('@/features/auth/useAuth', () => ({
  useAuth: () => ({ can: () => true, me: null, status: 'signed-in' }),
}));

afterEach(() => {
  vi.restoreAllMocks();
});

const TODAY = localToday();

const line = (over: Partial<AcEntryLine>): AcEntryLine => ({
  id: 'l-1',
  gs_item_id: 'item-1',
  line_no: 1,
  product_code: 'DMT-01',
  product_name: 'Digital Thermometer',
  action_code: 'SEND_NEW',
  action_label: 'Send New',
  qty: 6,
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
  ...over,
});

const cnLine = line({
  id: 'l-2',
  action_code: 'ISSUE_CN',
  action_label: 'Issue CN',
  qty: 1,
  requires_cn: true,
  requires_challan: false,
});

const state = (over: Partial<AcEntryState> = {}): AcEntryState => ({
  gs_id: 'gs-1',
  gs_no: 'GS/2026-27/00042',
  gs_status: 'HELD_AT_INTERMEDIATE_STORE',
  party_name: 'Sharma Medicos',
  party_code: 'P-001',
  ac_action_slip_id: 'slip-1',
  slip_no: 'RSA/2026-27/00001',
  version_no: 1,
  lines: [line({}), cnLine],
  lines_needing_data: 2,
  lines_complete: 0,
  shipping_lines: 1,
  is_completed: false,
  completed_by_name: null,
  completed_at: null,
  can_edit: true,
  can_complete: false,
  complete_blockers: ['Line 1 Send New: Challan No./Date missing.'],
  dispatch_slip: null,
  ...over,
});

describe('Phase 8 Accounts entry rules (AMD-18)', () => {
  it('takes only the field groups the action flags require', () => {
    const drafts = initialDrafts([line({}), cnLine]);
    drafts['l-1'] = { ...toDraft(line({})), challan_no: ' CH-1 ', challan_date: TODAY, cn_no: 'X' };
    expect(isDirty([line({}), cnLine], drafts)).toBe(true);
    expect(toSaveLines([line({}), cnLine], drafts)).toEqual([
      {
        line_id: 'l-1',
        cn_no: null,
        cn_date: null,
        cn_value: null,
        challan_no: 'CH-1',
        challan_date: TODAY,
      },
    ]);
  });

  it('flags partial groups, bad amounts and future dates', () => {
    const d = { cn_no: 'CN1', cn_date: '', cn_value: '0', challan_no: '', challan_date: '' };
    const issues = draftIssues(cnLine, d, TODAY);
    expect(issues).toContain('CN No., CN Date and CN Value are entered together.');
    expect(issues).toContain('CN Value must be a positive amount.');
    expect(
      draftIssues(line({}), { ...d, challan_no: 'C', challan_date: '2999-01-01' }, TODAY),
    ).toContain('Challan Date cannot be in the future.');
    expect(draftComplete(cnLine, { ...d, cn_date: TODAY, cn_value: '12.50' })).toBe(true);
    expect(draftComplete(line({ requires_challan: false }), d)).toBe(true);
  });

  it('checks DEC-26 dispatch tracking data', () => {
    const base = {
      dispatch_date: TODAY,
      transporter: 'Blue Dart',
      docket_no: '',
      vehicle_no: '',
      remarks: null,
    };
    expect(dispatchIssue(base, TODAY)).toBe('Enter a docket number or a vehicle number.');
    expect(dispatchIssue({ ...base, vehicle_no: 'DL1' }, TODAY)).toBeNull();
    expect(dispatchIssue({ ...base, transporter: ' ', docket_no: 'D' }, TODAY)).toBe(
      'Enter the transporter / courier.',
    );
  });

  it('deep-links Phase 8 notifications by permission', () => {
    const accountsCan = (m: string, a: string) => !(m === 'final_actions' && a === 'edit');
    const n = {
      id: 'n1',
      type: 'AC_ACTIONS_SLIP_READY',
      entity_type: 'ac_action_slips',
      entity_id: 's',
      gs_id: 'gs-1',
    };
    expect(notificationPath(n as never, accountsCan)).toBe('/accounts-entry/gs-1');
    expect(notificationPath(n as never, () => true)).toBe('/gs/gs-1/final-actions');
    const d = { ...n, type: 'DISPATCH_SLIP_READY', entity_type: 'dispatch_slips' };
    expect(notificationPath(d as never, () => true)).toBe('/dispatch-slips');
  });
});

describe('Phase 8 Accounts screens', () => {
  it('queue: loading, then items; empty state on a filter without rows', async () => {
    const queue = vi.spyOn(acEntryApi, 'queue').mockImplementation((status) =>
      Promise.resolve(
        status === 'pending'
          ? [
              {
                gs_id: 'gs-1',
                gs_no: 'GS/2026-27/00042',
                gs_status: 'HELD_AT_INTERMEDIATE_STORE',
                party_name: 'Sharma Medicos',
                ac_action_slip_id: 'slip-1',
                slip_no: 'RSA/2026-27/00001',
                version_no: 1,
                finalised_at: '2026-11-13T10:00:00Z',
                lines_total: 3,
                lines_needing_data: 3,
                lines_complete: 1,
                is_completed: false,
                completed_at: null,
                dispatch_slip_no: null,
                dispatch_status: null,
              },
            ]
          : [],
      ),
    );
    const onOpen = vi.fn();
    render(<AccountsEntryQueuePage onOpen={onOpen} />);
    expect(screen.getByText('Loading the Accounts queue…')).toBeInTheDocument();
    expect(await screen.findByText('1 / 3 lines entered')).toBeInTheDocument();
    fireEvent.click(screen.getByText('GS/2026-27/00042'));
    expect(onOpen).toHaveBeenCalledWith('gs-1');

    fireEvent.click(screen.getByRole('button', { name: 'Completed' }));
    expect(await screen.findByText('No goods slips')).toBeInTheDocument();
    expect(queue).toHaveBeenCalledWith('completed');
  });

  it('entry: shows only the flagged fields, saves with an Idempotency-Key, then completes', async () => {
    vi.spyOn(acEntryApi, 'get').mockResolvedValue(state());
    const saved = state({
      lines: [
        line({ challan_no: 'CH-1', challan_date: TODAY, is_complete: true }),
        { ...cnLine, cn_no: 'CN-9', cn_date: TODAY, cn_value: '125.50', is_complete: true },
      ],
      lines_complete: 2,
      can_complete: true,
      complete_blockers: [],
    });
    const save = vi.spyOn(acEntryApi, 'save').mockResolvedValue(saved);
    const complete = vi.spyOn(acEntryApi, 'complete').mockResolvedValue(
      state({
        ...saved,
        is_completed: true,
        can_edit: false,
        can_complete: false,
        dispatch_slip: {
          id: 'ds-1',
          slip_no: 'DS/2026-27/00001',
          status: 'READY',
          generated_at: '2026-11-14T10:00:00Z',
          dispatch_date: null,
          transporter: null,
          docket_no: null,
          vehicle_no: null,
          dispatched_at: null,
          total_qty: 6,
          print_count: 0,
        },
      }),
    );
    render(<AccountsEntryPage gsId="gs-1" onBack={() => undefined} onOpenGs={() => undefined} />);

    expect(await screen.findByText('Accounts Entry · GS/2026-27/00042')).toBeInTheDocument();
    const sendNew = screen.getByRole('article', { name: 'Line 1 Send New' });
    expect(sendNew.querySelector('[id$="-cn_no"]')).toBeNull(); // Send New takes no CN fields
    expect(screen.getByRole('button', { name: /complete/i })).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Challan No.'), { target: { value: 'CH-1' } });
    fireEvent.change(screen.getByLabelText('Challan Date'), { target: { value: TODAY } });
    fireEvent.change(screen.getByLabelText('CN No.'), { target: { value: 'CN-9' } });
    fireEvent.change(screen.getByLabelText('CN Date'), { target: { value: TODAY } });
    fireEvent.change(screen.getByLabelText('CN Value (₹)'), { target: { value: '125.50' } });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => {
      expect(save).toHaveBeenCalledTimes(1);
    });
    const [, body, key] = save.mock.calls[0] ?? [];
    expect(body).toMatchObject({ ac_action_slip_id: 'slip-1' });
    expect((body as { lines: unknown[] }).lines).toHaveLength(2);
    expect(String(key)).toMatch(/^web-/);
    expect(await screen.findByText('Saved.')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /^complete$/i }));
    fireEvent.click(screen.getByRole('button', { name: /complete & generate dispatch slip/i }));
    await waitFor(() => {
      expect(complete).toHaveBeenCalledWith('gs-1', 'slip-1', null, expect.stringMatching(/^web-/));
    });
    expect(
      await screen.findByText(/Dispatch Slip DS\/2026-27\/00001 is ready/),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /print dispatch slip/i })).toBeEnabled();
  });

  it('entry: error state with retry and request id', async () => {
    vi.spyOn(acEntryApi, 'get').mockRejectedValue(
      new ApiError(404, 'GS_NOT_FOUND', 'Goods slip not found', null, 'req-9'),
    );
    render(<AccountsEntryPage gsId="gs-x" onBack={() => undefined} onOpenGs={() => undefined} />);
    expect(await screen.findByText('Goods slip not found')).toBeInTheDocument();
    expect(screen.getByText(/req-9/)).toBeInTheDocument();
  });
});

describe('Phase 8 Dispatch Slips screen', () => {
  const slip: DispatchSlipOut = {
    id: 'ds-1',
    slip_no: 'DS/2026-27/00001',
    status: 'READY',
    generated_at: '2026-11-14T10:00:00Z',
    dispatch_date: null,
    transporter: null,
    docket_no: null,
    vehicle_no: null,
    dispatched_at: null,
    total_qty: 6,
    print_count: 0,
    gs_id: 'gs-1',
    gs_no: 'GS/2026-27/00042',
    gs_status: 'HELD_AT_INTERMEDIATE_STORE',
    party_name: 'Sharma Medicos',
    ac_slip_no: 'RSA/2026-27/00001',
    ac_version_no: 1,
    dispatch_remarks: null,
    generated_by_name: 'Deepak',
    dispatched_by_name: null,
    lines: [
      {
        id: 'dl-1',
        gs_item_id: 'item-1',
        line_no: 1,
        product_code: 'DMT-01',
        product_name: 'Digital Thermometer',
        action_code: 'SEND_NEW',
        action_label: 'Send New',
        qty: 6,
        challan_no: 'CH-1',
        challan_date: '2026-11-14',
      },
    ],
  };

  it('requires DEC-26 tracking data and dispatches with an Idempotency-Key', async () => {
    vi.spyOn(dispatchSlipsApi, 'list').mockResolvedValue([slip]);
    const dispatch = vi
      .spyOn(dispatchSlipsApi, 'dispatch')
      .mockResolvedValue({ ...slip, status: 'DISPATCHED' });
    render(<DispatchSlipsPage onOpenGs={() => undefined} />);

    expect(await screen.findByText('DS/2026-27/00001')).toBeInTheDocument();
    expect(screen.getByText(/Challan CH-1/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /mark dispatched/i }));
    const submit = screen.getByRole('button', { name: /issue & dispatch/i });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Transporter / courier'), {
      target: { value: 'Blue Dart' },
    });
    expect(screen.getByText('Enter a docket number or a vehicle number.')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Docket No.'), { target: { value: 'BD123' } });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    await waitFor(() => {
      expect(dispatch).toHaveBeenCalledWith(
        'ds-1',
        expect.objectContaining({ transporter: 'Blue Dart', docket_no: 'BD123', vehicle_no: null }),
        expect.stringMatching(/^web-/),
      );
    });
    expect(
      await screen.findByText('DS/2026-27/00001 dispatched. GS/2026-27/00042 moves on to closure.'),
    ).toBeInTheDocument();
  });

  it('shows the empty state', async () => {
    vi.spyOn(dispatchSlipsApi, 'list').mockResolvedValue([]);
    render(<DispatchSlipsPage onOpenGs={() => undefined} />);
    expect(await screen.findByText('Nothing to dispatch')).toBeInTheDocument();
  });
});
