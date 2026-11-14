import { useCallback, useMemo, useState } from 'react';
import { ArrowLeft, Check, Copy, FileText, Send } from 'lucide-react';

import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  FileUpload,
  Input,
  LoadingState,
  Select,
  Textarea,
} from '@/components/ui';
import { StatusChip } from '@/features/goods-slips/display';
import { formatDateTime, humanize } from '@/features/goods-slips/format';
import { unboxingApi } from '@/features/unboxing/api';
import { createTransfer } from '@/features/unboxing/uploader';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError, type ApiError } from '@/lib/api/client';

import {
  partyNotificationsApi,
  suggestedRecipient,
  type ChannelCode,
  type PartyNotificationState,
} from './api';
import { PartyEmailPanel } from './PartyEmailPanel';

interface Props {
  gsId: string;
  onBack: () => void;
}

const PROOF_ACCEPT = 'image/jpeg,image/png,image/heic,image/heif,application/pdf';

/** Upload the proof through the signed URL and confirm it (DEC-25). */
async function uploadProof(gsId: string, file: File): Promise<string> {
  const ticket = await partyNotificationsApi.proofUploadUrl(gsId, {
    mime_type: file.type || 'application/octet-stream',
    size_bytes: file.size,
    file_name: file.name,
  });
  await new Promise<void>((resolve, reject) => {
    createTransfer(file, ticket.upload, ticket.attachment.mime_type, {
      onProgress: () => undefined,
      onSuccess: resolve,
      onError: (message) => {
        reject(new Error(message));
      },
    }).start();
  });
  const confirmed = await partyNotificationsApi.confirmProof(
    ticket.attachment.id,
    ticket.upload.object_path,
  );
  return confirmed.id;
}

export function PartyNotificationPage({ gsId, onBack }: Props) {
  const fetcher = useCallback(() => partyNotificationsApi.state(gsId), [gsId]);
  const query = useApiQuery<PartyNotificationState>(fetcher);
  const back = (
    <Button type="button" variant="ghost" onClick={onBack}>
      <ArrowLeft size={16} aria-hidden="true" /> Goods slip
    </Button>
  );

  if (query.error) {
    return (
      <div className="page">
        {back}
        <h1 className="page__title">Notify party</h1>
        <ErrorState error={query.error} onRetry={query.reload} />
      </div>
    );
  }
  if (!query.data || query.data.gs_id !== gsId) {
    return (
      <div className="page">
        {back}
        <h1 className="page__title">Notify party</h1>
        <LoadingState />
      </div>
    );
  }
  const state = query.data;
  return (
    <div className="page">
      {back}
      <h1 className="page__title" style={{ wordBreak: 'break-all' }}>
        Notify party · {state.gs_no}
      </h1>
      <p className="page__subtitle" style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        <StatusChip status={state.status} />
        {state.status_label ? <Badge variant="info">{state.status_label}</Badge> : null}
      </p>

      {state.party_email ? (
        <div style={{ marginBottom: '1rem' }}>
          <PartyEmailPanel gsId={state.gs_id} email={state.party_email} onChanged={query.reload} />
        </div>
      ) : null}

      {state.drafts.length === 0 ? (
        <EmptyState
          title="Nothing to notify yet"
          hint={
            state.party_email
              ? 'The party is notified once Accounts completes the CN / Challan entry.'
              : 'The party is notified once a credit note / JV is issued or a replacement is dispatched.'
          }
        />
      ) : state.can_record ? (
        <NotificationForm state={state} onRecorded={query.reload} />
      ) : (
        <div className="banner" role="status">
          You can view the notifications of this goods slip. Recording one needs the Step-7 party
          notification role while the GS awaits closure.
        </div>
      )}

      <section style={{ marginTop: '1.5rem' }}>
        <h2 style={{ fontSize: '1rem', margin: '0 0 0.5rem' }}>Recorded notifications</h2>
        {state.notifications.length === 0 ? (
          <EmptyState title="No notification recorded" />
        ) : (
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: '0.5rem' }}>
            {state.notifications.map((n) => (
              <li key={n.id} className="card" style={{ padding: '0.75rem 1rem', minWidth: 0 }}>
                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', fontWeight: 600 }}>
                  <span>
                    {n.voucher_no ??
                      (n.party_email_id !== null || 'cn_lines' in n.message_snapshot
                        ? 'Accounts values'
                        : 'Dispatch details')}
                  </span>
                  <Badge variant="success">{n.status_label ?? humanize(n.status_code)}</Badge>
                  <Badge variant="neutral">
                    {n.delivery_mode === 'EMAIL_SENT' ? 'Sent by RMS email' : 'Recorded manually'}
                  </Badge>
                </div>
                <div style={{ fontSize: '0.8125rem', color: 'var(--color-muted)' }}>
                  {humanize(n.channel_code)} · {n.recipient} · {formatDateTime(n.sent_at)}
                  {n.sent_by_name ? ` · ${n.sent_by_name}` : ''}
                </div>
                <pre
                  style={{
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    margin: '0.5rem 0 0',
                    fontFamily: 'inherit',
                    fontSize: '0.875rem',
                  }}
                >
                  {n.message}
                </pre>
                {n.proof_attachment_id ? <ProofLink attachmentId={n.proof_attachment_id} /> : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function ProofLink({ attachmentId }: { attachmentId: string }) {
  const [error, setError] = useState<ApiError | null>(null);
  return (
    <div style={{ marginTop: '0.5rem' }}>
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={() => {
          setError(null);
          unboxingApi
            .downloadUrl(attachmentId)
            .then((d) => {
              window.open(d.url, '_blank', 'noopener');
            })
            .catch((err: unknown) => {
              setError(toApiError(err));
            });
        }}
      >
        <FileText size={14} aria-hidden="true" /> View proof
      </Button>
      {error ? <ErrorState error={error} title="Could not open the proof" /> : null}
    </div>
  );
}

function NotificationForm({
  state,
  onRecorded,
}: {
  state: PartyNotificationState;
  onRecorded: () => void;
}) {
  const firstOpen = state.drafts.find((d) => !d.notified) ?? state.drafts[0];
  const draftKey = (d: { credit_note_id: string | null; source: string }) =>
    d.credit_note_id ?? d.source;
  const [selected, setSelected] = useState(firstOpen ? draftKey(firstOpen) : '');
  const draft = useMemo(
    () => state.drafts.find((d) => draftKey(d) === selected) ?? firstOpen,
    [state.drafts, selected, firstOpen],
  );
  const [channel, setChannel] = useState<ChannelCode>('WHATSAPP');
  const [recipient, setRecipient] = useState(suggestedRecipient('WHATSAPP', state.recipient));
  const [recipientEdited, setRecipientEdited] = useState(false);
  const [message, setMessage] = useState(draft?.message ?? '');
  const [proof, setProof] = useState<File | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [done, setDone] = useState<string | null>(null);

  if (!draft) return null;
  const fieldErrors = error?.fieldErrors ?? {};

  const submit = async () => {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const proofId = proof ? await uploadProof(state.gs_id, proof) : null;
      const note = await partyNotificationsApi.record(state.gs_id, {
        credit_note_id: draft.credit_note_id,
        channel,
        recipient: recipient.trim(),
        message: message.trim() === draft.message.trim() ? null : message.trim(),
        proof_attachment_id: proofId,
      });
      setDone(
        `Recorded for ${note.voucher_no ?? 'dispatch details'} (${humanize(note.channel_code)})`,
      );
      setProof(null);
      onRecorded();
    } catch (err: unknown) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card" style={{ padding: '1rem', display: 'grid', gap: '0.875rem' }}>
      <Select
        id="pn-draft"
        aria-label="Credit note / JV"
        value={selected}
        options={state.drafts.map((d) => ({
          value: draftKey(d),
          label: d.credit_note_id
            ? `${d.voucher_no ?? '—'} · ${d.cn_type_label ?? humanize(d.cn_type_code)}${d.notified ? ' · notified' : ''}`
            : d.source === 'AC_ACTIONS'
              ? `Accounts values${d.voucher_no ? ` · CN ${d.voucher_no}` : ''}${d.notified ? ' · notified' : ''}`
              : `Dispatch details${d.notified ? ' · notified' : ''}`,
        }))}
        onChange={(e) => {
          setSelected(e.target.value);
          const next = state.drafts.find((d) => draftKey(d) === e.target.value);
          if (next) setMessage(next.message);
        }}
        helperText="Credit note / JV the party is told about"
      />
      <Select
        id="pn-channel"
        aria-label="Channel"
        value={channel}
        options={state.channels.map((c) => ({ value: c, label: humanize(c) }))}
        onChange={(e) => {
          const next = e.target.value as ChannelCode;
          setChannel(next);
          if (!recipientEdited) setRecipient(suggestedRecipient(next, state.recipient));
        }}
        helperText="Channel"
      />
      <Input
        id="pn-recipient"
        aria-label="Recipient"
        value={recipient}
        onChange={(e) => {
          setRecipient(e.target.value);
          setRecipientEdited(true);
        }}
        error={fieldErrors.recipient?.[0]}
        helperText="Prefilled from the party master"
      />
      <div>
        <Textarea
          id="pn-message"
          aria-label="Message"
          rows={9}
          value={message}
          onChange={(e) => {
            setMessage(e.target.value);
          }}
          error={fieldErrors.message?.[0]}
          helperText="Auto-generated with the CN No., Date and items; the structured details are stored with the record."
        />
        <Button
          type="button"
          variant="outline"
          size="sm"
          style={{ marginTop: '0.5rem' }}
          onClick={() => {
            void navigator.clipboard.writeText(message).then(
              () => {
                setCopied(true);
                window.setTimeout(() => {
                  setCopied(false);
                }, 2000);
              },
              (err: unknown) => {
                setError(toApiError(err));
              },
            );
          }}
        >
          {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}{' '}
          {copied ? 'Copied' : 'Copy message'}
        </Button>
      </div>
      <FileUpload
        id="pn-proof"
        name="proof"
        accept={PROOF_ACCEPT}
        value={proof}
        onChange={(f) => {
          setProof(f instanceof File ? f : null);
        }}
        error={fieldErrors.proof_attachment_id?.[0]}
        helperText="Optional proof: screenshot, scanned letter or PDF"
      />
      <div className="banner" role="note">
        Recorded manually — RMS does not send this message. Send it by the chosen channel, then
        record it here.
      </div>
      {error ? <ErrorState error={error} title="The notification was not recorded" /> : null}
      {done ? (
        <div className="banner" role="status">
          {done}
        </div>
      ) : null}
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Button
          type="button"
          variant="primary"
          isLoading={busy}
          disabled={recipient.trim().length < 3 || message.trim().length === 0}
          onClick={() => {
            void submit();
          }}
        >
          <Send size={16} aria-hidden="true" /> Record notification
        </Button>
      </div>
    </section>
  );
}
