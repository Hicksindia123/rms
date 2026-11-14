import { useState } from 'react';
import { Mail, RefreshCw, RotateCcw, Send } from 'lucide-react';

import { Badge, Button, EmptyState, ErrorState, Input, Textarea } from '@/components/ui';
import type { BadgeVariant } from '@/components/ui/Badge';
import { formatDateTime, humanize } from '@/features/goods-slips/format';
import { toApiError, type ApiError } from '@/lib/api/client';

import {
  parseAddressList,
  partyNotificationsApi,
  type PartyEmail,
  type PartyEmailState,
} from './api';

/**
 * Party email built from the values Accounts entered (change plan Phase 9; AMD-20, BR-38, DEC-48).
 * Preview (editable) → send → log; any logged email can be re-sent. The text comes from the
 * `party_email.template` setting; a SENT email records the prior party notification (BR-38).
 */

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  SENT: 'success',
  QUEUED: 'warning',
  FAILED: 'danger',
  SKIPPED: 'neutral',
};

interface Props {
  gsId: string;
  email: PartyEmailState;
  onChanged: () => void;
}

export function PartyEmailPanel({ gsId, email, onChanged }: Props) {
  return (
    <section className="card" style={{ padding: '1rem', display: 'grid', gap: '0.875rem' }}>
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
        <Mail size={18} aria-hidden="true" />
        <h2 style={{ fontSize: '1rem', margin: 0 }}>Party email</h2>
        <Badge variant="neutral">Auto-send: {humanize(email.auto_send)}</Badge>
      </div>

      {!email.ready ? (
        <div className="banner" role="status">
          {email.blocker ?? 'The party email is not available yet.'}
        </div>
      ) : email.template_error ? (
        <ErrorState
          title="The party email template is invalid"
          error={{ message: `${email.template_error} Ask an administrator to fix it.` }}
        />
      ) : (
        <>
          {!email.smtp_enabled ? (
            <div className="banner" role="status">
              E-mail is not configured on the server
              {email.smtp_reason ? ` (${email.smtp_reason})` : ''}. Send the message yourself and
              record it below as a manual notification.
            </div>
          ) : null}
          <EmailForm gsId={gsId} email={email} onSent={onChanged} />
        </>
      )}

      <div>
        <h3 style={{ fontSize: '0.9375rem', margin: '0 0 0.5rem' }}>Email log</h3>
        {email.emails.length === 0 ? (
          <EmptyState title="No party email yet" />
        ) : (
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: '0.5rem' }}>
            {email.emails.map((m) => (
              <EmailLogItem
                key={m.id}
                gsId={gsId}
                mail={m}
                canResend={email.can_send}
                onResent={onChanged}
              />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function EmailForm({
  gsId,
  email,
  onSent,
}: {
  gsId: string;
  email: PartyEmailState;
  onSent: () => void;
}) {
  const generatedSubject = email.subject ?? '';
  const generatedBody = email.body ?? '';
  const [to, setTo] = useState(email.to ?? '');
  const [cc, setCc] = useState(email.cc.join(', '));
  const [subject, setSubject] = useState(generatedSubject);
  const [body, setBody] = useState(generatedBody);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [result, setResult] = useState<PartyEmail | null>(null);
  const fieldErrors = error?.fieldErrors ?? {};
  const edited = subject !== generatedSubject || body !== generatedBody;

  const send = () => {
    setBusy(true);
    setError(null);
    setResult(null);
    partyNotificationsApi
      .sendEmail(gsId, {
        to: to.trim(),
        cc: parseAddressList(cc),
        subject: subject.trim() === generatedSubject.trim() ? null : subject.trim(),
        body: body.trim() === generatedBody.trim() ? null : body.trim(),
      })
      .then((mail) => {
        setResult(mail);
        onSent();
      })
      .catch((err: unknown) => {
        setError(toApiError(err));
      })
      .finally(() => {
        setBusy(false);
      });
  };

  return (
    <div style={{ display: 'grid', gap: '0.75rem' }}>
      <Input
        id="pe-to"
        aria-label="To"
        type="email"
        value={to}
        onChange={(e) => {
          setTo(e.target.value);
        }}
        error={fieldErrors.to?.[0]}
        helperText="To: prefilled from the party master"
      />
      <Input
        id="pe-cc"
        aria-label="Cc"
        value={cc}
        onChange={(e) => {
          setCc(e.target.value);
        }}
        error={fieldErrors.cc?.[0]}
        helperText="Cc (optional, comma separated)"
      />
      <Input
        id="pe-subject"
        aria-label="Subject"
        value={subject}
        onChange={(e) => {
          setSubject(e.target.value);
        }}
        helperText="Subject"
      />
      <Textarea
        id="pe-body"
        aria-label="Message"
        rows={12}
        value={body}
        onChange={(e) => {
          setBody(e.target.value);
        }}
        helperText="Preview built from the CN / Challan / Dispatch values Accounts entered. You may edit it before sending."
      />
      {error ? <ErrorState error={error} title="The email was not sent" /> : null}
      {result ? <SendResult mail={result} /> : null}
      <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
        {edited ? (
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              setSubject(generatedSubject);
              setBody(generatedBody);
            }}
          >
            <RotateCcw size={16} aria-hidden="true" /> Reset text
          </Button>
        ) : null}
        <Button
          type="button"
          variant="primary"
          isLoading={busy}
          disabled={!email.can_send || to.trim().length < 3 || body.trim().length === 0}
          onClick={send}
        >
          <Send size={16} aria-hidden="true" /> Send email
        </Button>
      </div>
      {!email.can_send && email.smtp_enabled ? (
        <p style={{ margin: 0, fontSize: '0.8125rem', color: 'var(--color-muted)' }}>
          Sending needs the Accounts party-notification role.
        </p>
      ) : null}
    </div>
  );
}

function SendResult({ mail }: { mail: PartyEmail }) {
  const text =
    mail.status === 'SENT'
      ? `Sent to ${mail.email_to ?? ''}. The party notification is recorded.`
      : mail.status === 'QUEUED'
        ? `Not delivered yet (${mail.last_error ?? 'mail server busy'}). RMS retries automatically.`
        : mail.status === 'FAILED'
          ? `Sending failed: ${mail.last_error ?? 'unknown error'}.`
          : `Skipped: ${humanize(mail.skip_reason)}.`;
  return (
    <div className="banner" role="status">
      {text}
    </div>
  );
}

function EmailLogItem({
  gsId,
  mail,
  canResend,
  onResent,
}: {
  gsId: string;
  mail: PartyEmail;
  canResend: boolean;
  onResent: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const resendable =
    canResend && mail.status !== 'QUEUED' && mail.email_to !== null && mail.body.trim() !== '';

  const resend = () => {
    setBusy(true);
    setError(null);
    partyNotificationsApi
      .resendEmail(gsId, mail.id)
      .then(() => {
        onResent();
      })
      .catch((err: unknown) => {
        setError(toApiError(err));
      })
      .finally(() => {
        setBusy(false);
      });
  };

  return (
    <li className="card" style={{ padding: '0.75rem 1rem', minWidth: 0 }}>
      <div
        style={{
          display: 'flex',
          gap: '0.5rem',
          flexWrap: 'wrap',
          alignItems: 'center',
          fontWeight: 600,
          wordBreak: 'break-word',
        }}
      >
        <span style={{ minWidth: 0 }}>{mail.subject || '(no subject)'}</span>
        <Badge variant={STATUS_VARIANT[mail.status] ?? 'neutral'}>{humanize(mail.status)}</Badge>
        <Badge variant="neutral">{humanize(mail.trigger_code)}</Badge>
      </div>
      <div style={{ fontSize: '0.8125rem', color: 'var(--color-muted)', wordBreak: 'break-word' }}>
        {mail.email_to ?? 'No recipient'}
        {mail.cc.length > 0 ? ` · cc ${mail.cc.join(', ')}` : ''} ·{' '}
        {formatDateTime(mail.sent_at ?? mail.requested_at)}
        {mail.requested_by_name ? ` · ${mail.requested_by_name}` : ''}
        {mail.attempts > 1 ? ` · ${String(mail.attempts)} attempts` : ''}
      </div>
      {mail.skip_reason ? (
        <div style={{ fontSize: '0.8125rem' }}>Skipped: {humanize(mail.skip_reason)}</div>
      ) : null}
      {mail.last_error && mail.status !== 'SENT' ? (
        <div style={{ fontSize: '0.8125rem', color: 'var(--color-danger, #b91c1c)' }}>
          {mail.last_error}
        </div>
      ) : null}
      {mail.body ? (
        <details style={{ marginTop: '0.5rem' }}>
          <summary
            style={{ cursor: 'pointer', minHeight: 44, display: 'flex', alignItems: 'center' }}
          >
            Show message
          </summary>
          <pre
            style={{
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              margin: '0.5rem 0 0',
              fontFamily: 'inherit',
              fontSize: '0.875rem',
            }}
          >
            {mail.body}
          </pre>
        </details>
      ) : null}
      {resendable ? (
        <div style={{ marginTop: '0.5rem' }}>
          <Button type="button" variant="outline" isLoading={busy} onClick={resend}>
            <RefreshCw size={14} aria-hidden="true" /> Resend
          </Button>
        </div>
      ) : null}
      {error ? <ErrorState error={error} title="The email was not re-sent" /> : null}
    </li>
  );
}
