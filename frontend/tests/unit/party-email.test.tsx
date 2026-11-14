/**
 * Change plan Phase 9 (AMD-20, DEC-48): party email panel (preview → send → log → resend) and the
 * admin Party email settings editor.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  parseAddressList,
  partyNotificationsApi,
  type PartyEmail,
  type PartyEmailSettings,
  type PartyEmailState,
} from '@/features/party-notifications/api';
import { PartyEmailPanel } from '@/features/party-notifications/PartyEmailPanel';
import { PartyEmailSettingsEditor } from '@/features/party-notifications/PartyEmailSettingsEditor';
import { ApiError } from '@/lib/api/client';

vi.mock('@/features/party-notifications/api', async (orig) => {
  const actual = await orig<typeof import('@/features/party-notifications/api')>();
  return {
    ...actual,
    partyNotificationsApi: {
      sendEmail: vi.fn(),
      resendEmail: vi.fn(),
      emailSettings: vi.fn(),
      saveEmailSettings: vi.fn(),
      previewEmail: vi.fn(),
    },
  };
});

const sentMail: PartyEmail = {
  id: 'm-1',
  gs_id: 'gs-1',
  ac_action_slip_id: 'slip-1',
  trigger_code: 'MANUAL',
  resend_of_id: null,
  email_to: 'party@example.com',
  cc: [],
  subject: 'Goods Slip GS-1',
  body: 'Dear P,\nCN CN-9 dated 14-11-2026',
  status: 'SENT',
  skip_reason: null,
  attempts: 1,
  next_attempt_at: '2026-11-14T10:00:00Z',
  last_error: null,
  sent_at: '2026-11-14T10:00:00Z',
  requested_at: '2026-11-14T10:00:00Z',
  requested_by_name: 'Deepak',
  party_notification_id: 'n-1',
};

function panelState(over: Partial<PartyEmailState> = {}): PartyEmailState {
  return {
    ready: true,
    blocker: null,
    smtp_enabled: true,
    smtp_reason: null,
    auto_send: 'OFF',
    can_send: true,
    to: 'party@example.com',
    cc: [],
    subject: 'Goods Slip GS-1',
    body: 'Dear P,\nCN CN-9 dated 14-11-2026',
    template_error: null,
    snapshot: {},
    emails: [],
    ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('parseAddressList', () => {
  it('splits on commas, semicolons and new lines and drops blanks', () => {
    expect(parseAddressList(' a@b.co, c@d.co;\n\n e@f.co ,')).toEqual([
      'a@b.co',
      'c@d.co',
      'e@f.co',
    ]);
  });
});

describe('PartyEmailPanel', () => {
  it('previews the generated email and sends it unchanged (server builds the text)', async () => {
    vi.mocked(partyNotificationsApi.sendEmail).mockResolvedValue(sentMail);
    const onChanged = vi.fn();
    render(<PartyEmailPanel gsId="gs-1" email={panelState()} onChanged={onChanged} />);
    expect(screen.getByDisplayValue('party@example.com')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Goods Slip GS-1')).toBeInTheDocument();
    expect(screen.getByText(/Auto-send: Off/i)).toBeInTheDocument();
    expect(screen.getByText('No party email yet')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Cc'), { target: { value: 'x@y.co, z@y.co' } });
    fireEvent.click(screen.getByRole('button', { name: /send email/i }));
    await waitFor(() => {
      expect(partyNotificationsApi.sendEmail).toHaveBeenCalledWith('gs-1', {
        to: 'party@example.com',
        cc: ['x@y.co', 'z@y.co'],
        subject: null,
        body: null,
      });
    });
    expect(await screen.findByText(/The party notification is recorded/)).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalled();
  });

  it('sends edited text and can reset it', () => {
    render(<PartyEmailPanel gsId="gs-1" email={panelState()} onChanged={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Subject'), { target: { value: 'Changed' } });
    fireEvent.click(screen.getByRole('button', { name: /reset text/i }));
    expect(screen.getByDisplayValue('Goods Slip GS-1')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /reset text/i })).not.toBeInTheDocument();
  });

  it('shows the blocker before Accounts completes and offers no send', () => {
    render(
      <PartyEmailPanel
        gsId="gs-1"
        email={panelState({
          ready: false,
          can_send: false,
          blocker: 'Accounts has not completed the CN / Challan entry of this slip yet.',
          subject: null,
          body: null,
        })}
        onChanged={vi.fn()}
      />,
    );
    expect(screen.getByText(/has not completed/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /send email/i })).not.toBeInTheDocument();
  });

  it('explains when e-mail is not configured and disables send', () => {
    render(
      <PartyEmailPanel
        gsId="gs-1"
        email={panelState({ smtp_enabled: false, can_send: false, smtp_reason: 'SMTP off' })}
        onChanged={vi.fn()}
      />,
    );
    expect(
      screen.getByText(/E-mail is not configured on the server \(SMTP off\)/),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /send email/i })).toBeDisabled();
  });

  it('shows the error envelope when sending fails', async () => {
    vi.mocked(partyNotificationsApi.sendEmail).mockRejectedValue(
      new ApiError(409, 'PARTY_EMAIL_NOT_READY', 'AMD-20: not ready', null, 'req-9'),
    );
    render(<PartyEmailPanel gsId="gs-1" email={panelState()} onChanged={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /send email/i }));
    expect(await screen.findByText('The email was not sent')).toBeInTheDocument();
    expect(screen.getByText(/AMD-20: not ready/)).toBeInTheDocument();
  });

  it('lists the log with status and re-sends a logged email', async () => {
    const failed: PartyEmail = {
      ...sentMail,
      id: 'm-2',
      status: 'FAILED',
      last_error: 'mailbox unavailable',
      party_notification_id: null,
      sent_at: null,
    };
    vi.mocked(partyNotificationsApi.resendEmail).mockResolvedValue({ ...sentMail, id: 'm-3' });
    const onChanged = vi.fn();
    render(
      <PartyEmailPanel
        gsId="gs-1"
        email={panelState({ emails: [failed, sentMail] })}
        onChanged={onChanged}
      />,
    );
    expect(screen.getByText('mailbox unavailable')).toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
    const resend = screen.getAllByRole('button', { name: /resend/i });
    expect(resend).toHaveLength(2);
    fireEvent.click(resend[0] as HTMLElement);
    await waitFor(() => {
      expect(partyNotificationsApi.resendEmail).toHaveBeenCalledWith('gs-1', 'm-2');
    });
    expect(onChanged).toHaveBeenCalled();
  });
});

describe('PartyEmailSettingsEditor', () => {
  const settings: PartyEmailSettings = {
    template: {
      subject: 'Goods Slip {gs_no}',
      body: 'Dear {party_name},{cn_lines}',
      cn_line: '- {cn_no}',
      challan_line: '- {challan_no}',
      dispatch_line: '- {dispatch_slip_no}',
    },
    delivery: { auto_send: 'OFF', cc: [] },
    auto_send_modes: ['OFF', 'ON_AC_COMPLETION', 'ON_DISPATCH'],
    placeholders: { subject: ['gs_no'], body: ['party_name', 'cn_lines'] },
    smtp_enabled: true,
    smtp_reason: null,
  };

  it('saves the template and auto-send mode, and previews with sample values', async () => {
    vi.mocked(partyNotificationsApi.emailSettings).mockResolvedValue(settings);
    vi.mocked(partyNotificationsApi.saveEmailSettings).mockResolvedValue(settings);
    vi.mocked(partyNotificationsApi.previewEmail).mockResolvedValue({
      subject: 'Goods Slip GS/2026-27/00042',
      body: 'Dear Sample Distributor,',
    });
    render(<PartyEmailSettingsEditor canEdit />);
    expect(await screen.findByDisplayValue('Goods Slip {gs_no}')).toBeInTheDocument();
    expect(screen.getByText(/Placeholders: \{gs_no\}/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Auto-send'), { target: { value: 'ON_DISPATCH' } });
    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() => {
      expect(partyNotificationsApi.saveEmailSettings).toHaveBeenCalledWith({
        template: settings.template,
        delivery: { auto_send: 'ON_DISPATCH', cc: [] },
        reason: null,
      });
    });

    fireEvent.click(screen.getByRole('button', { name: /preview with sample values/i }));
    expect(await screen.findByText('Goods Slip GS/2026-27/00042')).toBeInTheDocument();
  });

  it('is read-only without the configure permission', async () => {
    vi.mocked(partyNotificationsApi.emailSettings).mockResolvedValue(settings);
    render(<PartyEmailSettingsEditor canEdit={false} />);
    expect(await screen.findByDisplayValue('Goods Slip {gs_no}')).toBeDisabled();
    expect(screen.queryByRole('button', { name: /^save$/i })).not.toBeInTheDocument();
  });

  it('shows the load error with retry', async () => {
    vi.mocked(partyNotificationsApi.emailSettings).mockRejectedValue(
      new ApiError(403, 'PERMISSION_DENIED', 'Not allowed', null, 'req-1'),
    );
    render(<PartyEmailSettingsEditor canEdit />);
    expect(await screen.findByText('Could not load the party email settings')).toBeInTheDocument();
  });
});
