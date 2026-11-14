import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  closureApi,
  failedItemsOf,
  formatDuration,
  type ClosureState,
} from '@/features/closure/api';
import { ClosurePanel } from '@/features/closure/ClosurePanel';
import {
  partyNotificationsApi,
  suggestedRecipient,
  type PartyNotificationState,
} from '@/features/party-notifications/api';
import { PartyNotificationPage } from '@/features/party-notifications/PartyNotificationPage';
import { ApiError } from '@/lib/api/client';

vi.mock('@/features/closure/api', async (orig) => {
  const actual = await orig<typeof import('@/features/closure/api')>();
  return { ...actual, closureApi: { state: vi.fn(), close: vi.fn(), reopen: vi.fn() } };
});
vi.mock('@/features/party-notifications/api', async (orig) => {
  const actual = await orig<typeof import('@/features/party-notifications/api')>();
  return {
    ...actual,
    partyNotificationsApi: {
      state: vi.fn(),
      record: vi.fn(),
      proofUploadUrl: vi.fn(),
      confirmProof: vi.fn(),
    },
  };
});

function item(code: string, passed: boolean, applicable = true) {
  return {
    code,
    rule_ref: 'G-15',
    applicable,
    passed,
    explanation: `${code} explanation`,
    details: {},
    fix: passed ? null : { label: 'Fix it', path: `/fix/${code}` },
  };
}

function closureState(over: Partial<ClosureState> = {}): ClosureState {
  return {
    gs_id: 'gs-1',
    gs_no: 'GS-0001',
    status: 'AWAITING_NOTIFICATION',
    category_code: 'RO',
    party_name: 'Party',
    state_name: null,
    station_name: null,
    created_at: '2026-11-01T10:00:00Z',
    closed_at: null,
    expected_closure_type: 'RO_CLOSED',
    expected_closure_label: null,
    items: [item('STOCK_ACCOUNTED', true), item('PRIOR_NOTIFICATION', false)],
    all_passed: false,
    can_close: true,
    can_reopen: false,
    closure: null,
    lifecycle: [
      {
        status: 'GATE_CREATED',
        entered_at: '2026-11-01T10:00:00Z',
        left_at: '2026-11-01T12:00:00Z',
        duration_seconds: 7200,
        by_name: null,
      },
    ],
    total_duration_seconds: 7200,
    lines: [],
    credit_notes: [],
    dispatches: [],
    notifications: [],
    ...over,
  };
}

describe('closure helpers', () => {
  it('formats durations and reads G-15 failed items', () => {
    expect(formatDuration(90061)).toBe('1d 1h');
    expect(formatDuration(3900)).toBe('1h 05m');
    expect(formatDuration(120)).toBe('2m');
    expect(
      failedItemsOf({ failed_items: [{ code: 'X', rule_ref: 'G-15', explanation: 'e' }] }),
    ).toHaveLength(1);
    expect(failedItemsOf(null)).toEqual([]);
  });

  it('prefills the recipient from the party master per channel', () => {
    const r = { party_name: 'P', contact_name: 'C', email: 'a@b.in', phone: '98100' };
    expect(suggestedRecipient('EMAIL', r)).toBe('a@b.in');
    expect(suggestedRecipient('WHATSAPP', r)).toBe('98100');
    expect(suggestedRecipient('LETTER', r)).toBe('P');
  });
});

describe('ClosurePanel', () => {
  beforeEach(() => {
    vi.mocked(closureApi.state).mockReset();
    vi.mocked(closureApi.close).mockReset();
  });

  it('disables Close GS while a check fails and links to the fix', async () => {
    vi.mocked(closureApi.state).mockResolvedValue(closureState());
    const onNavigate = vi.fn();
    render(
      <ClosurePanel
        gsId="gs-1"
        onNavigate={onNavigate}
        onOpenCertificate={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    const close = await screen.findByRole('button', { name: /close gs/i });
    expect(close).toBeDisabled();
    expect(screen.getByTestId('check-PRIOR_NOTIFICATION')).toHaveAttribute('data-passed', 'false');
    fireEvent.click(screen.getByRole('button', { name: 'Fix it' }));
    expect(onNavigate).toHaveBeenCalledWith('/fix/PRIOR_NOTIFICATION');
  });

  it('shows every failed item when the server rejects the closure', async () => {
    vi.mocked(closureApi.state).mockResolvedValue(
      closureState({ all_passed: true, items: [item('STOCK_ACCOUNTED', true)] }),
    );
    vi.mocked(closureApi.close).mockRejectedValue(
      new ApiError(
        422,
        'G-15',
        'The goods slip cannot be closed: 2 checklist item(s) failed',
        {
          failed_items: [
            { code: 'STOCK_ACCOUNTED', rule_ref: 'G-15', explanation: 'lot in store' },
            { code: 'NO_OPEN_PENDENCY', rule_ref: 'G-08', explanation: '1 open pendency' },
          ],
        },
        'req-1',
      ),
    );
    render(
      <ClosurePanel
        gsId="gs-1"
        onNavigate={vi.fn()}
        onOpenCertificate={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    fireEvent.click(await screen.findByRole('button', { name: /close gs/i }));
    const buttons = await screen.findAllByRole('button', { name: /close gs/i });
    const confirm = buttons[buttons.length - 1];
    if (!confirm) throw new Error('confirm button missing');
    fireEvent.click(confirm);
    const list = await screen.findByTestId('close-failures');
    expect(list.querySelectorAll('li')).toHaveLength(2);
    expect(screen.getByText(/1 open pendency/)).toBeInTheDocument();
  });
});

describe('PartyNotificationPage', () => {
  it('prefills the message and recipient and records the notification', async () => {
    const state: PartyNotificationState = {
      gs_id: 'gs-1',
      gs_no: 'GS-0001',
      status: 'AWAITING_NOTIFICATION',
      can_record: true,
      status_label: 'Prior Information Sent with CN Details',
      channels: ['EMAIL', 'WHATSAPP', 'PHONE', 'LETTER', 'OTHER'],
      recipient: { party_name: 'P', contact_name: 'C', email: 'a@b.in', phone: '+91 98100 00000' },
      drafts: [
        {
          source: 'CREDIT_NOTE',
          credit_note_id: 'cn-1',
          cn_type_code: 'GENERAL_CN',
          cn_type_label: 'General Credit Note',
          voucher_no: 'CN-1',
          voucher_date: '2026-11-05',
          total_value: '100.00',
          notified: false,
          message: 'Dear P, CN-1 dated 05-11-2026',
          snapshot: {},
        },
      ],
      notifications: [],
      party_email: null,
    };
    vi.mocked(partyNotificationsApi.state).mockResolvedValue(state);
    vi.mocked(partyNotificationsApi.record).mockResolvedValue({
      id: 'n-1',
      gs_id: 'gs-1',
      credit_note_id: 'cn-1',
      voucher_no: 'CN-1',
      status_code: 'PRIOR_INFO_SENT',
      status_label: null,
      channel_code: 'WHATSAPP',
      recipient: '+91 98100 00000',
      message: 'Dear P, CN-1 dated 05-11-2026',
      message_snapshot: {},
      delivery_mode: 'RECORDED_MANUALLY',
      proof_attachment_id: null,
      party_email_id: null,
      sent_at: '2026-11-05T10:00:00Z',
      sent_by_name: 'A',
    });
    render(<PartyNotificationPage gsId="gs-1" onBack={vi.fn()} />);
    expect(await screen.findByDisplayValue('Dear P, CN-1 dated 05-11-2026')).toBeInTheDocument();
    expect(screen.getByDisplayValue('+91 98100 00000')).toBeInTheDocument();
    expect(screen.getAllByText(/Recorded manually/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('button', { name: /record notification/i }));
    await waitFor(() => {
      expect(partyNotificationsApi.record).toHaveBeenCalledWith('gs-1', {
        credit_note_id: 'cn-1',
        channel: 'WHATSAPP',
        recipient: '+91 98100 00000',
        message: null,
        proof_attachment_id: null,
      });
    });
  });
});
