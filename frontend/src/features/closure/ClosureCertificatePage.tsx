import { useCallback, type CSSProperties } from 'react';
import { ArrowLeft, Printer } from 'lucide-react';

import { Button, EmptyState, ErrorState, LoadingState } from '@/components/ui';
import { formatDateTime, humanize } from '@/features/goods-slips/format';
import { useApiQuery } from '@/hooks/useApiQuery';

import { closureApi, formatDuration, type ClosureState } from './api';

interface Props {
  gsId: string;
  onBack: () => void;
}

const cell: CSSProperties = {
  border: '1px solid var(--color-border)',
  padding: '0.375rem 0.5rem',
  textAlign: 'left',
  verticalAlign: 'top',
};

/** P3-07 [IMP]: printable closure certificate from the frozen closure record. */
export function ClosureCertificatePage({ gsId, onBack }: Props) {
  const fetcher = useCallback(() => closureApi.state(gsId), [gsId]);
  const query = useApiQuery<ClosureState>(fetcher);
  const back = (
    <Button type="button" variant="ghost" onClick={onBack} className="no-print">
      <ArrowLeft size={16} aria-hidden="true" /> Goods slip
    </Button>
  );
  if (query.error) {
    return (
      <div className="page">
        {back}
        <ErrorState error={query.error} onRetry={query.reload} />
      </div>
    );
  }
  if (!query.data || query.data.gs_id !== gsId) {
    return (
      <div className="page">
        {back}
        <LoadingState />
      </div>
    );
  }
  const s = query.data;
  const c = s.closure;
  if (s.status !== 'CLOSED' || !c) {
    return (
      <div className="page">
        {back}
        <EmptyState title="Not closed" hint="The certificate is available once the GS is closed." />
      </div>
    );
  }
  const items = (c.checklist_snapshot.items ?? []) as Array<{
    code: string;
    rule_ref: string;
    applicable: boolean;
    passed: boolean;
    explanation: string;
  }>;
  return (
    <div className="page">
      <div
        className="no-print"
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          gap: '0.5rem',
          flexWrap: 'wrap',
        }}
      >
        {back}
        <Button
          type="button"
          variant="primary"
          onClick={() => {
            window.print();
          }}
        >
          <Printer size={16} aria-hidden="true" /> Print
        </Button>
      </div>
      <article
        className="card"
        style={{ padding: '1.25rem', marginTop: '1rem', overflowX: 'auto' }}
      >
        <h1 style={{ fontSize: '1.25rem', margin: '0 0 0.25rem' }}>Closure certificate</h1>
        <p style={{ margin: 0, fontWeight: 600, wordBreak: 'break-all' }}>{s.gs_no}</p>
        <dl className="kv" style={{ marginTop: '1rem' }}>
          <div>
            <dt>Party</dt>
            <dd>{[s.party_name, s.station_name, s.state_name].filter(Boolean).join(' · ')}</dd>
          </div>
          <div>
            <dt>Closure</dt>
            <dd>{c.closure_label ?? humanize(c.closure_type)}</dd>
          </div>
          <div>
            <dt>Closed</dt>
            <dd>
              {formatDateTime(c.closed_at)}
              {c.closed_by_name ? ` · ${c.closed_by_name}` : ''}
            </dd>
          </div>
          <div>
            <dt>Lifecycle</dt>
            <dd>
              {formatDateTime(s.created_at)} → {formatDateTime(c.closed_at)} (
              {formatDuration(s.total_duration_seconds)})
            </dd>
          </div>
          {c.remarks ? (
            <div>
              <dt>Remarks</dt>
              <dd>{c.remarks}</dd>
            </div>
          ) : null}
        </dl>

        <h2 style={{ fontSize: '1rem', margin: '1.25rem 0 0.5rem' }}>Items</h2>
        <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: '0.875rem' }}>
          <tbody>
            {s.lines.map((l) => (
              <tr key={l.line_no}>
                <td style={cell}>{l.line_no}</td>
                <td style={cell}>{[l.product_code, l.product_name].filter(Boolean).join(' · ')}</td>
                <td style={cell}>{l.received_qty} pcs</td>
              </tr>
            ))}
          </tbody>
        </table>

        {s.credit_notes.length > 0 ? (
          <>
            <h2 style={{ fontSize: '1rem', margin: '1.25rem 0 0.5rem' }}>Credit notes / JV</h2>
            <ul style={{ margin: 0, paddingLeft: '1.25rem' }}>
              {s.credit_notes.map((cn) => (
                <li key={cn.id}>
                  {cn.voucher_no} · {cn.voucher_date ?? ''} ·{' '}
                  {cn.cn_type_label ?? humanize(cn.cn_type_code)} · {cn.total_value}
                </li>
              ))}
            </ul>
          </>
        ) : null}
        {s.dispatches.length > 0 ? (
          <>
            <h2 style={{ fontSize: '1rem', margin: '1.25rem 0 0.5rem' }}>Replacement dispatches</h2>
            <ul style={{ margin: 0, paddingLeft: '1.25rem' }}>
              {s.dispatches.map((d) => (
                <li key={d.id}>
                  {d.dispatch_no} · {d.qty} pcs · {d.transporter}
                  {d.docket_no ? ` · ${d.docket_no}` : ''} · {formatDateTime(d.dispatched_at)}
                </li>
              ))}
            </ul>
          </>
        ) : null}
        {s.notifications.length > 0 ? (
          <>
            <h2 style={{ fontSize: '1rem', margin: '1.25rem 0 0.5rem' }}>Party notified</h2>
            <ul style={{ margin: 0, paddingLeft: '1.25rem' }}>
              {s.notifications.map((n) => (
                <li key={n.id}>
                  {n.status_label ?? humanize(n.status_code)} · {humanize(n.channel_code)} ·{' '}
                  {n.recipient} · {formatDateTime(n.sent_at)}
                </li>
              ))}
            </ul>
          </>
        ) : null}

        <h2 style={{ fontSize: '1rem', margin: '1.25rem 0 0.5rem' }}>Closure checklist (frozen)</h2>
        <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: '0.8125rem' }}>
          <tbody>
            {items.map((i) => (
              <tr key={i.code}>
                <td style={cell}>{i.applicable ? (i.passed ? 'Pass' : 'Fail') : 'N/A'}</td>
                <td style={cell}>
                  {humanize(i.code)} ({i.rule_ref})
                </td>
                <td style={cell}>{i.explanation}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </article>
    </div>
  );
}
