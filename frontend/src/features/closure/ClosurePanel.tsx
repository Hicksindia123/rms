import { useCallback, useState } from 'react';
import { CheckCircle2, CircleSlash, Lock, Printer, RotateCcw, XCircle } from 'lucide-react';

import { Badge, Button, ErrorState, LoadingState, Modal, Textarea } from '@/components/ui';
import { formatDateTime, humanize } from '@/features/goods-slips/format';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError, type ApiError } from '@/lib/api/client';

import {
  closureApi,
  failedItemsOf,
  formatDuration,
  type ChecklistItem,
  type ClosureState,
} from './api';

interface Props {
  gsId: string;
  /** Navigate to the screen that fixes a failing item (hash route). */
  onNavigate: (path: string) => void;
  onOpenCertificate: () => void;
  /** The GS changed status (closed / reopened): the detail page reloads. */
  onChanged: () => void;
}

/** P3-07: live closure checklist (G-15, BR-38, BR-39); the backend is authoritative. */
export function ClosurePanel({ gsId, onNavigate, onOpenCertificate, onChanged }: Props) {
  const fetcher = useCallback(() => closureApi.state(gsId), [gsId]);
  const query = useApiQuery<ClosureState>(fetcher);
  const [closeOpen, setCloseOpen] = useState(false);
  const [reopenOpen, setReopenOpen] = useState(false);

  if (query.error) return <ErrorState error={query.error} onRetry={query.reload} />;
  if (!query.data || query.data.gs_id !== gsId) return <LoadingState label="Evaluating closure…" />;
  const s = query.data;
  const closed = s.status === 'CLOSED';
  const applicable = s.items.filter((i) => i.applicable);
  const failing = applicable.filter((i) => !i.passed).length;

  return (
    <div style={{ display: 'grid', gap: '1.25rem' }}>
      <section className="card" style={{ padding: '1rem' }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            gap: '0.75rem',
            flexWrap: 'wrap',
            alignItems: 'center',
          }}
        >
          <div style={{ minWidth: 0 }}>
            <h2 style={{ fontSize: '1rem', margin: 0 }}>
              {closed ? 'Closed' : 'Closure checklist'}
            </h2>
            <p style={{ margin: '0.25rem 0 0', color: 'var(--color-muted)', fontSize: '0.875rem' }}>
              {closed && s.closure
                ? `${s.closure.closure_label ?? humanize(s.closure.closure_type)} · ${formatDateTime(s.closure.closed_at)}${s.closure.closed_by_name ? ` · ${s.closure.closed_by_name}` : ''}`
                : `Closes as ${s.expected_closure_label ?? humanize(s.expected_closure_type)} · ${failing === 0 ? 'all checks pass' : `${String(failing)} check(s) failing`}`}
            </p>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            {closed ? (
              <Button type="button" variant="outline" onClick={onOpenCertificate}>
                <Printer size={16} aria-hidden="true" /> Closure certificate
              </Button>
            ) : null}
            {s.can_reopen ? (
              <Button
                type="button"
                variant="danger"
                onClick={() => {
                  setReopenOpen(true);
                }}
              >
                <RotateCcw size={16} aria-hidden="true" /> Reopen
              </Button>
            ) : null}
            {!closed && s.can_close ? (
              <Button
                type="button"
                variant="primary"
                disabled={!s.all_passed}
                title={s.all_passed ? undefined : 'Every applicable check must pass'}
                onClick={() => {
                  setCloseOpen(true);
                }}
              >
                <Lock size={16} aria-hidden="true" /> Close GS
              </Button>
            ) : null}
          </div>
        </div>
        {s.closure?.reopen_reason ? (
          <div className="banner" role="status" style={{ marginTop: '0.75rem' }}>
            Reopened {formatDateTime(s.closure.reopened_at)}
            {s.closure.reopened_by_name ? ` by ${s.closure.reopened_by_name}` : ''}:{' '}
            {s.closure.reopen_reason}
          </div>
        ) : null}
      </section>

      {!closed ? (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: '0.5rem' }}>
          {s.items.map((item) => (
            <ChecklistRow key={item.code} item={item} onNavigate={onNavigate} />
          ))}
        </ul>
      ) : null}

      <section>
        <h2 style={{ fontSize: '1rem', margin: '0 0 0.5rem' }}>
          Lifecycle · {formatDuration(s.total_duration_seconds)}
        </h2>
        <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: '0.375rem' }}>
          {s.lifecycle.map((st, i) => (
            <li
              key={`${st.status}-${String(i)}`}
              className="card"
              style={{
                padding: '0.5rem 0.75rem',
                display: 'flex',
                justifyContent: 'space-between',
                gap: '0.5rem',
                flexWrap: 'wrap',
              }}
            >
              <span style={{ fontWeight: 600 }}>{humanize(st.status)}</span>
              <span style={{ color: 'var(--color-muted)', fontSize: '0.8125rem' }}>
                {formatDateTime(st.entered_at)} ·{' '}
                {st.left_at || st.status === 'CLOSED'
                  ? formatDuration(st.duration_seconds)
                  : `${formatDuration(st.duration_seconds)} so far`}
              </span>
            </li>
          ))}
        </ol>
      </section>

      {closeOpen ? (
        <CloseDialog
          state={s}
          onClose={() => {
            setCloseOpen(false);
          }}
          onDone={(next) => {
            query.setData(next);
            setCloseOpen(false);
            onChanged();
          }}
          onRefresh={query.reload}
        />
      ) : null}
      {reopenOpen ? (
        <ReopenDialog
          gsId={gsId}
          gsNo={s.gs_no}
          onClose={() => {
            setReopenOpen(false);
          }}
          onDone={(next) => {
            query.setData(next);
            setReopenOpen(false);
            onChanged();
          }}
        />
      ) : null}
    </div>
  );
}

function ChecklistRow({
  item,
  onNavigate,
}: {
  item: ChecklistItem;
  onNavigate: (path: string) => void;
}) {
  const icon = !item.applicable ? (
    <CircleSlash size={20} aria-hidden="true" style={{ color: 'var(--color-muted)' }} />
  ) : item.passed ? (
    <CheckCircle2 size={20} aria-hidden="true" style={{ color: 'var(--color-success)' }} />
  ) : (
    <XCircle size={20} aria-hidden="true" style={{ color: 'var(--color-danger)' }} />
  );
  return (
    <li
      className="card"
      data-testid={`check-${item.code}`}
      data-passed={item.applicable ? String(item.passed) : 'na'}
      style={{
        padding: '0.75rem',
        display: 'flex',
        gap: '0.625rem',
        alignItems: 'flex-start',
        opacity: item.applicable ? 1 : 0.7,
      }}
    >
      <span style={{ flexShrink: 0, marginTop: '0.125rem' }}>{icon}</span>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ display: 'flex', gap: '0.375rem', flexWrap: 'wrap', alignItems: 'center' }}>
          <strong style={{ wordBreak: 'break-word' }}>{humanize(item.code)}</strong>
          <Badge variant="neutral">{item.rule_ref}</Badge>
          {!item.applicable ? <Badge variant="neutral">Not applicable</Badge> : null}
        </div>
        <div style={{ fontSize: '0.875rem', marginTop: '0.125rem', wordBreak: 'break-word' }}>
          {item.explanation}
        </div>
      </div>
      {item.fix && item.applicable && !item.passed ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          style={{ flexShrink: 0, minHeight: '44px' }}
          onClick={() => {
            if (item.fix) onNavigate(item.fix.path);
          }}
        >
          {item.fix.label}
        </Button>
      ) : null}
    </li>
  );
}

function CloseDialog({
  state,
  onClose,
  onDone,
  onRefresh,
}: {
  state: ClosureState;
  onClose: () => void;
  onDone: (next: ClosureState) => void;
  onRefresh: () => void;
}) {
  const [remarks, setRemarks] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const failed = error ? failedItemsOf(error.details) : [];
  return (
    <Modal isOpen onClose={onClose} title={`Close ${state.gs_no}`}>
      <p style={{ marginTop: 0 }}>
        Closes as{' '}
        <strong>{state.expected_closure_label ?? humanize(state.expected_closure_type)}</strong>.
        The checklist is re-evaluated by the server and frozen with the closure.
      </p>
      <label
        htmlFor="close-remarks"
        style={{ display: 'block', fontWeight: 500, marginBottom: '0.375rem' }}
      >
        Closure remarks (optional)
      </label>
      <Textarea
        id="close-remarks"
        value={remarks}
        onChange={(e) => {
          setRemarks(e.target.value);
        }}
      />
      {error ? (
        <div style={{ marginTop: '0.75rem' }}>
          <ErrorState error={error} title="The goods slip was not closed" />
          {failed.length > 0 ? (
            <ul
              style={{ margin: '0.5rem 0 0', paddingLeft: '1.25rem' }}
              data-testid="close-failures"
            >
              {failed.map((f) => (
                <li key={f.code}>
                  <strong>{humanize(f.code)}</strong> ({f.rule_ref}): {f.explanation}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      <div
        style={{
          display: 'flex',
          gap: '0.5rem',
          justifyContent: 'flex-end',
          marginTop: '1rem',
          flexWrap: 'wrap',
        }}
      >
        <Button
          type="button"
          variant="secondary"
          onClick={() => {
            if (failed.length > 0) onRefresh();
            onClose();
          }}
          disabled={busy}
        >
          Cancel
        </Button>
        <Button
          type="button"
          variant="primary"
          isLoading={busy}
          onClick={() => {
            setBusy(true);
            setError(null);
            closureApi
              .close(state.gs_id, remarks.trim() || null)
              .then(onDone)
              .catch((err: unknown) => {
                setError(toApiError(err));
              })
              .finally(() => {
                setBusy(false);
              });
          }}
        >
          Close GS
        </Button>
      </div>
    </Modal>
  );
}

function ReopenDialog({
  gsId,
  gsNo,
  onClose,
  onDone,
}: {
  gsId: string;
  gsNo: string;
  onClose: () => void;
  onDone: (next: ClosureState) => void;
}) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  return (
    <Modal isOpen onClose={onClose} title={`Reopen ${gsNo}`}>
      <p style={{ marginTop: 0 }}>
        The goods slip returns to commercial resolution. The reason is kept on the closure record
        and in the audit trail.
      </p>
      <label
        htmlFor="reopen-reason"
        style={{ display: 'block', fontWeight: 500, marginBottom: '0.375rem' }}
      >
        Reason (mandatory)
      </label>
      <Textarea
        id="reopen-reason"
        value={reason}
        onChange={(e) => {
          setReason(e.target.value);
        }}
      />
      {error ? (
        <div style={{ marginTop: '0.75rem' }}>
          <ErrorState error={error} title="The goods slip was not reopened" />
        </div>
      ) : null}
      <div
        style={{
          display: 'flex',
          gap: '0.5rem',
          justifyContent: 'flex-end',
          marginTop: '1rem',
          flexWrap: 'wrap',
        }}
      >
        <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>
          Keep closed
        </Button>
        <Button
          type="button"
          variant="danger"
          isLoading={busy}
          disabled={reason.trim().length < 5}
          onClick={() => {
            setBusy(true);
            setError(null);
            closureApi
              .reopen(gsId, reason.trim())
              .then(onDone)
              .catch((err: unknown) => {
                setError(toApiError(err));
              })
              .finally(() => {
                setBusy(false);
              });
          }}
        >
          Reopen
        </Button>
      </div>
    </Modal>
  );
}
