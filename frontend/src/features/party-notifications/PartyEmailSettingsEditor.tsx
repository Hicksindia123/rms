import { useCallback, useState } from 'react';
import { Eye, Save } from 'lucide-react';

import { Button, ErrorState, Input, LoadingState, Select, Textarea } from '@/components/ui';
import { humanize } from '@/features/goods-slips/format';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError, type ApiError } from '@/lib/api/client';

import {
  parseAddressList,
  partyNotificationsApi,
  type PartyEmailSettings,
  type PartyEmailTemplate,
} from './api';

/**
 * Admin → Notifications → Party email (change plan Phase 9; AMD-20, DEC-48). The template and the
 * auto-send mode are configuration (settings party_email.template / party_email.delivery); the
 * server validates placeholders and records every change in the config history.
 */

const PARTS: { key: keyof PartyEmailTemplate; label: string; rows?: number }[] = [
  { key: 'subject', label: 'Subject' },
  { key: 'body', label: 'Body', rows: 12 },
  { key: 'cn_line', label: 'Line per credit note' },
  { key: 'challan_line', label: 'Line per challan' },
  { key: 'dispatch_line', label: 'Dispatch line' },
];

export function PartyEmailSettingsEditor({ canEdit }: { canEdit: boolean }) {
  const fetcher = useCallback(() => partyNotificationsApi.emailSettings(), []);
  const query = useApiQuery<PartyEmailSettings>(fetcher);

  if (query.error) {
    return (
      <ErrorState
        error={query.error}
        onRetry={query.reload}
        title="Could not load the party email settings"
      />
    );
  }
  if (!query.data) return <LoadingState label="Loading party email settings…" />;
  // Remount with the saved values after a save (no state syncing in an effect).
  return (
    <Editor
      key={JSON.stringify(query.data)}
      settings={query.data}
      canEdit={canEdit}
      onSaved={query.reload}
    />
  );
}

function Editor({
  settings,
  canEdit,
  onSaved,
}: {
  settings: PartyEmailSettings;
  canEdit: boolean;
  onSaved: () => void;
}) {
  const [template, setTemplate] = useState<PartyEmailTemplate>(settings.template);
  const [autoSend, setAutoSend] = useState(settings.delivery.auto_send);
  const [cc, setCc] = useState(settings.delivery.cc.join(', '));
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState<'save' | 'preview' | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);
  const [preview, setPreview] = useState<{ subject: string; body: string } | null>(null);

  const fieldErrors = error?.fieldErrors ?? {};
  const partError = (key: string): string | undefined => fieldErrors[key]?.[0];

  const run = (kind: 'save' | 'preview') => {
    setBusy(kind);
    setError(null);
    setSaved(false);
    const call =
      kind === 'save'
        ? partyNotificationsApi
            .saveEmailSettings({
              template,
              delivery: { auto_send: autoSend, cc: parseAddressList(cc) },
              reason: reason.trim() ? reason.trim() : null,
            })
            .then(() => {
              setSaved(true);
              setReason('');
              onSaved();
            })
        : partyNotificationsApi.previewEmail(template).then(setPreview);
    call
      .catch((err: unknown) => {
        setError(toApiError(err));
      })
      .finally(() => {
        setBusy(null);
      });
  };

  return (
    <section className="card" style={{ padding: '1rem', display: 'grid', gap: '0.875rem' }}>
      <p style={{ margin: 0, fontSize: '0.875rem', color: 'var(--color-muted)' }}>
        The email Accounts sends to the party, built from the CN / Challan / Dispatch values entered
        in RMS. A body line whose placeholders are all empty is left out.
        {settings.smtp_enabled
          ? ''
          : ` E-mail is not configured on the server (${settings.smtp_reason ?? 'SMTP not set'}).`}
      </p>
      <Select
        id="pes-auto"
        aria-label="Auto-send"
        value={autoSend}
        disabled={!canEdit}
        options={settings.auto_send_modes.map((m) => ({ value: m, label: humanize(m) }))}
        onChange={(e) => {
          setAutoSend(e.target.value);
        }}
        helperText="Auto-send: Off = Accounts sends from the party notification screen; On AC Completion / On Dispatch = sent automatically at that point"
      />
      <Input
        id="pes-cc"
        aria-label="Copy every party email to"
        value={cc}
        disabled={!canEdit}
        onChange={(e) => {
          setCc(e.target.value);
        }}
        error={partError('cc')}
        helperText="Cc on every party email (optional, comma separated)"
      />
      {PARTS.map((p) => {
        const allowed = (settings.placeholders[p.key] ?? []).map((n) => `{${n}}`).join(' ');
        const common = {
          id: `pes-${p.key}`,
          'aria-label': p.label,
          value: template[p.key],
          disabled: !canEdit,
          error: partError(p.key),
          helperText: `${p.label}. Placeholders: ${allowed}`,
        };
        return p.rows ? (
          <Textarea
            key={p.key}
            {...common}
            rows={p.rows}
            onChange={(e) => {
              setTemplate({ ...template, [p.key]: e.target.value });
            }}
          />
        ) : (
          <Input
            key={p.key}
            {...common}
            onChange={(e) => {
              setTemplate({ ...template, [p.key]: e.target.value });
            }}
          />
        );
      })}
      {canEdit ? (
        <Input
          id="pes-reason"
          aria-label="Reason for the change"
          value={reason}
          onChange={(e) => {
            setReason(e.target.value);
          }}
          helperText="Reason (kept in the config history)"
        />
      ) : null}
      {error ? <ErrorState error={error} title="The party email settings were not saved" /> : null}
      {saved ? (
        <div className="banner" role="status">
          Party email settings saved.
        </div>
      ) : null}
      <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
        <Button
          type="button"
          variant="outline"
          isLoading={busy === 'preview'}
          disabled={busy !== null}
          onClick={() => {
            run('preview');
          }}
        >
          <Eye size={16} aria-hidden="true" /> Preview with sample values
        </Button>
        {canEdit ? (
          <Button
            type="button"
            variant="primary"
            isLoading={busy === 'save'}
            disabled={busy !== null}
            onClick={() => {
              run('save');
            }}
          >
            <Save size={16} aria-hidden="true" /> Save
          </Button>
        ) : null}
      </div>
      {preview ? (
        <div className="card" style={{ padding: '0.75rem 1rem', minWidth: 0 }}>
          <div style={{ fontWeight: 600, wordBreak: 'break-word' }}>{preview.subject}</div>
          <pre
            style={{
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              margin: '0.5rem 0 0',
              fontFamily: 'inherit',
              fontSize: '0.875rem',
            }}
          >
            {preview.body}
          </pre>
        </div>
      ) : null}
    </section>
  );
}
