import { useCallback, useState } from 'react';
import { ArrowLeft, Printer } from 'lucide-react';

import { Button, ErrorState, LoadingState } from '@/components/ui';
import { toApiError, type ApiError } from '@/lib/api/client';
import { formatDateTime, humanize } from '@/features/goods-slips/format';
import { useApiQuery } from '@/hooks/useApiQuery';
import { custodyApi } from './api';
import { layoutText, noteSections } from './rules';
import type { TransferDetail, TransferLine, TransferNote } from './types';

interface Props {
  transferId: string;
  onBack: () => void;
}

function headerValue(t: TransferDetail, key: string): string {
  switch (key) {
    case 'transfer_no':
      return t.transfer_no;
    case 'date':
      return formatDateTime(t.initiated_at);
    case 'from_location':
      return t.from_location_name;
    case 'to_location':
      return t.to_location_name;
    case 'mode':
      return t.mode_label ?? t.mode_code;
    case 'status':
      return t.acceptance_label ?? humanize(t.status);
    case 'discrepancy_notes':
      return t.discrepancy_notes ?? '—';
    default:
      return '';
  }
}

function lineValue(l: TransferLine, key: string): string {
  switch (key) {
    case 'lot_id':
      return l.lot_id.slice(0, 8).toUpperCase();
    case 'product_name':
      return l.product_name ?? '';
    case 'condition':
      return l.condition_label ?? humanize(l.condition_class);
    case 'qty_sent':
      return l.qty_sent === null ? '' : String(l.qty_sent);
    case 'qty_counted':
      return l.qty_counted === null ? '' : String(l.qty_counted);
    default:
      return '';
  }
}

export function TransferNotePrintPage({ transferId, onBack }: Props) {
  const fetcher = useCallback(() => custodyApi.transferNote(transferId), [transferId]);
  const { data, error, loading, reload, setData } = useApiQuery<TransferNote>(fetcher);
  const [printing, setPrinting] = useState(false);
  const [printError, setPrintError] = useState<ApiError | null>(null);
  // The preview has no side effect; a print is logged first, then the browser dialog opens.
  const print = async () => {
    setPrinting(true);
    setPrintError(null);
    try {
      setData(await custodyApi.printTransferNote(transferId));
      window.setTimeout(() => {
        window.print();
      }, 0);
    } catch (err) {
      setPrintError(toApiError(err));
    } finally {
      setPrinting(false);
    }
  };
  const toolbar = (
    <div
      className="no-print"
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        gap: '0.75rem',
        flexWrap: 'wrap',
        marginBottom: '1rem',
      }}
    >
      <Button type="button" variant="ghost" onClick={onBack}>
        <ArrowLeft size={16} aria-hidden="true" /> Transfer
      </Button>
      <Button
        type="button"
        variant="primary"
        disabled={!data}
        isLoading={printing}
        onClick={() => {
          void print();
        }}
      >
        <Printer size={16} aria-hidden="true" /> Print / Save as PDF
      </Button>
    </div>
  );
  if (error) {
    return (
      <div className="page">
        {toolbar}
        <ErrorState error={error} onRetry={reload} title="Could not load the Transfer Note" />
      </div>
    );
  }
  if (loading || !data) {
    return (
      <div className="page">
        {toolbar}
        <LoadingState label="Preparing Transfer Note…" />
      </div>
    );
  }
  const t = data.transfer;
  const layout = data.layout;
  const labels =
    layout.field_labels && typeof layout.field_labels === 'object'
      ? (layout.field_labels as Record<string, string>)
      : {};
  const label = (k: string) => labels[k] ?? humanize(k);
  const signatures = Array.isArray(layout.signature_blocks)
    ? (layout.signature_blocks as Array<{ label?: string }>)
    : [];

  return (
    <div className="page">
      {toolbar}
      {printError ? <ErrorState error={printError} title="Print not logged" /> : null}
      <article className="print-note" aria-label="Transfer Note">
        {data.watermark ? (
          <div
            className="print-note__watermark"
            data-watermark={data.watermark}
            aria-hidden="true"
          />
        ) : null}
        <header style={{ textAlign: 'center', marginBottom: '1rem' }}>
          <h1 style={{ fontSize: '1.125rem', margin: 0 }}>{layoutText(layout.header_title)}</h1>
          {layout.header_subtitle ? (
            <p style={{ margin: '0.25rem 0 0' }}>{layoutText(layout.header_subtitle)}</p>
          ) : null}
        </header>
        {noteSections(layout).map((s) => (
          <section key={s.id || s.title} style={{ marginBottom: '1rem' }}>
            <h2 style={{ fontSize: '0.9375rem', margin: '0 0 0.5rem' }}>{s.title}</h2>
            {s.id === 'lines' ? (
              <div style={{ overflowX: 'auto' }} tabIndex={0} role="region" aria-label={s.title}>
                <table className="print-note__table">
                  <thead>
                    <tr>
                      {s.fields.map((f) => (
                        <th key={f} scope="col">
                          {label(f)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {t.lines.map((l) => (
                      <tr key={l.lot_id}>
                        {s.fields.map((f) => (
                          <td key={f}>{lineValue(l, f)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <dl className="kv">
                {s.fields.map((f) => (
                  <div key={f}>
                    <dt>{label(f)}</dt>
                    <dd>{headerValue(t, f) || '—'}</dd>
                  </div>
                ))}
              </dl>
            )}
          </section>
        ))}
        <div className="print-note__signatures">
          {signatures.map((sig, i) => (
            <div key={sig.label ?? String(i)} className="print-note__signature">
              <span>{sig.label ?? ''}</span>
              <span style={{ fontSize: '0.8125rem' }}>
                {i === 0 ? (t.initiated_by_name ?? '') : (t.accepted_by_name ?? '')}
              </span>
            </div>
          ))}
        </div>
        {layout.footer_text ? (
          <p style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '1rem' }}>
            {layoutText(layout.footer_text)}
          </p>
        ) : null}
        <p style={{ fontSize: '0.75rem', color: '#475569' }}>
          Template v{String(data.template_version)} · print #{String(data.print_count)}
        </p>
      </article>
    </div>
  );
}
