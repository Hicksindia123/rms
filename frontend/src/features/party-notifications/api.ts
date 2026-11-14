import { apiRequest, newIdempotencyKey } from '@/lib/api/client';
import type { Attachment, SignedPutTicket, TusTicket } from '@/features/unboxing/api';

/** P3-07 prior party notification (BR-38, DD r79, DEC-25). */

export type ChannelCode = 'EMAIL' | 'WHATSAPP' | 'PHONE' | 'LETTER' | 'OTHER';

/** CREDIT_NOTE: issued CN / JV · DISPATCH: P3-05 dispatches · AC_ACTIONS: Accounts values (AMD-20). */
export type DraftSource = 'CREDIT_NOTE' | 'DISPATCH' | 'AC_ACTIONS';

export interface NotificationDraft {
  source: DraftSource;
  credit_note_id: string | null;
  cn_type_code: string | null;
  cn_type_label: string | null;
  voucher_no: string | null;
  voucher_date: string | null;
  total_value: string | null;
  notified: boolean;
  message: string;
  snapshot: Record<string, unknown>;
}

export interface PartyNotification {
  id: string;
  gs_id: string;
  credit_note_id: string | null;
  voucher_no: string | null;
  status_code: string;
  status_label: string | null;
  channel_code: ChannelCode;
  recipient: string;
  message: string;
  message_snapshot: Record<string, unknown>;
  delivery_mode: string;
  proof_attachment_id: string | null;
  party_email_id: string | null;
  sent_at: string;
  sent_by_name: string | null;
}

/** Phase 9 (AMD-20): a logged party email. Status codes come from the server. */
export type PartyEmailStatus = 'QUEUED' | 'SENT' | 'FAILED' | 'SKIPPED';

export interface PartyEmail {
  id: string;
  gs_id: string;
  ac_action_slip_id: string;
  trigger_code: 'MANUAL' | 'RESEND' | 'AUTO';
  resend_of_id: string | null;
  email_to: string | null;
  cc: string[];
  subject: string;
  body: string;
  status: PartyEmailStatus;
  skip_reason: string | null;
  attempts: number;
  next_attempt_at: string;
  last_error: string | null;
  sent_at: string | null;
  requested_at: string;
  requested_by_name: string | null;
  party_notification_id: string | null;
}

export interface PartyEmailState {
  ready: boolean;
  blocker: string | null;
  smtp_enabled: boolean;
  smtp_reason: string | null;
  auto_send: string;
  can_send: boolean;
  to: string | null;
  cc: string[];
  subject: string | null;
  body: string | null;
  template_error: string | null;
  snapshot: Record<string, unknown> | null;
  emails: PartyEmail[];
}

export interface PartyEmailTemplate {
  subject: string;
  body: string;
  cn_line: string;
  challan_line: string;
  dispatch_line: string;
}

export interface PartyEmailDelivery {
  auto_send: string;
  cc: string[];
}

export interface PartyEmailSettings {
  template: PartyEmailTemplate;
  delivery: PartyEmailDelivery;
  auto_send_modes: string[];
  placeholders: Record<string, string[]>;
  smtp_enabled: boolean;
  smtp_reason: string | null;
}

export interface PartyNotificationState {
  gs_id: string;
  gs_no: string;
  status: string;
  can_record: boolean;
  status_label: string | null;
  channels: ChannelCode[];
  recipient: {
    party_name: string | null;
    contact_name: string | null;
    email: string | null;
    phone: string | null;
  };
  drafts: NotificationDraft[];
  notifications: PartyNotification[];
  /** Null when the goods slip is not on the A/c Actions flow. */
  party_email: PartyEmailState | null;
}

export interface ProofUploadResult {
  attachment: Attachment;
  upload: SignedPutTicket | TusTicket;
}

const gs = (id: string) => `/gs/${encodeURIComponent(id)}`;

export const partyNotificationsApi = {
  state: (gsId: string) => apiRequest<PartyNotificationState>(`${gs(gsId)}/party-notifications`),
  record: (
    gsId: string,
    body: {
      credit_note_id: string | null;
      channel: ChannelCode;
      recipient: string;
      message: string | null;
      proof_attachment_id: string | null;
    },
    idempotencyKey = newIdempotencyKey(),
  ) =>
    apiRequest<PartyNotification>(`${gs(gsId)}/party-notifications`, {
      method: 'POST',
      body,
      idempotencyKey,
    }),
  proofUploadUrl: (
    gsId: string,
    body: { mime_type: string; size_bytes: number; file_name: string },
  ) =>
    apiRequest<ProofUploadResult>(`${gs(gsId)}/attachments/notification-proof/upload-url`, {
      method: 'POST',
      body,
    }),
  confirmProof: (attachmentId: string, objectPath: string) =>
    apiRequest<Attachment>(`/attachments/${encodeURIComponent(attachmentId)}/confirm`, {
      method: 'POST',
      body: { object_path: objectPath },
    }),
  // Phase 9 (AMD-20): party email from the Accounts values.
  sendEmail: (
    gsId: string,
    body: { to: string; cc: string[]; subject: string | null; body: string | null },
    idempotencyKey = newIdempotencyKey(),
  ) =>
    apiRequest<PartyEmail>(`${gs(gsId)}/party-emails`, {
      method: 'POST',
      body,
      idempotencyKey,
    }),
  resendEmail: (gsId: string, emailId: string, idempotencyKey = newIdempotencyKey()) =>
    apiRequest<PartyEmail>(`${gs(gsId)}/party-emails/${encodeURIComponent(emailId)}/resend`, {
      method: 'POST',
      idempotencyKey,
    }),
  emailSettings: () => apiRequest<PartyEmailSettings>('/party-email/settings'),
  saveEmailSettings: (body: {
    template: PartyEmailTemplate;
    delivery: PartyEmailDelivery;
    reason: string | null;
  }) => apiRequest<PartyEmailSettings>('/party-email/settings', { method: 'PUT', body }),
  previewEmail: (template: PartyEmailTemplate) =>
    apiRequest<{ subject: string; body: string }>('/party-email/settings/preview', {
      method: 'POST',
      body: { template },
    }),
};

/** Comma / newline separated addresses → trimmed list (validated by the server). */
export function parseAddressList(raw: string): string[] {
  return raw
    .split(/[,;\n]/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

/** The recipient prefilled from the party master for the chosen channel. */
export function suggestedRecipient(
  channel: ChannelCode,
  r: PartyNotificationState['recipient'],
): string {
  if (channel === 'EMAIL') return r.email ?? '';
  if (channel === 'WHATSAPP' || channel === 'PHONE') return r.phone ?? '';
  if (channel === 'LETTER') return r.party_name ?? '';
  return r.contact_name ?? r.party_name ?? '';
}
