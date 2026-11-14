import { useCallback, useMemo, useState } from 'react';
import { ArrowLeft, Ban, PackageCheck, Send } from 'lucide-react';

import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  LoadingState,
  Select,
  Textarea,
} from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { newIdempotencyKey, toApiError, type ApiError } from '@/lib/api/client';
import { QtyStepper } from '@/features/itemization/LineParts';
import { custodyApi } from './api';
import { TransferStatusBadge } from './display';
import { lineTitle } from './rules';
import type { HandoverPreview } from './types';

interface Props {
  gsId: string;
  onBack: () => void;
  onOpenTransfer: (id: string) => void;
}

/** Step-4 handover Aman → Sahil (BR-20/BR-21): eligible lines, held-back lines with reasons. */
export function HandoverPage({ gsId, onBack, onOpenTransfer }: Props) {
  const fetcher = useCallback(() => custodyApi.handoverPreview(gsId), [gsId]);
  const { data, error, loading, reload } = useApiQuery<HandoverPreview>(fetcher);
  const back = (
    <Button type="button" variant="ghost" onClick={onBack}>
      <ArrowLeft size={16} aria-hidden="true" /> Goods slip
    </Button>
  );

  if (error) {
    return (
      <div className="page page--narrow">
        {back}
        <h1 className="page__title">Handover to Intermediate Store</h1>
        <ErrorState error={error} onRetry={reload} />
      </div>
    );
  }
  if (loading || !data) {
    return (
      <div className="page page--narrow">
        {back}
        <h1 className="page__title">Handover to Intermediate Store</h1>
        <LoadingState />
      </div>
    );
  }
  return (
    <div className="page page--narrow">
      {back}
      <HandoverForm key={data.gs_id} data={data} onDone={onOpenTransfer} />
    </div>
  );
}

function HandoverForm({ data, onDone }: { data: HandoverPreview; onDone: (id: string) => void }) {
  const fixed = data.proposal_transfer_id !== null;
  const [qty, setQty] = useState<Record<string, number>>(() =>
    Object.fromEntries(data.eligible.map((e) => [e.lot_id, e.qty])),
  );
  const [mode, setMode] = useState(data.default_mode_code ?? data.mode_options[0]?.code ?? '');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<ApiError | null>(null);
  // One key per confirmed intent: a retry after a network error is replayed, never duplicated.
  const [idemKey, setIdemKey] = useState(newIdempotencyKey);
  const total = useMemo(() => Object.values(qty).reduce((a, b) => a + b, 0), [qty]);

  const submit = async () => {
    setBusy(true);
    setFailure(null);
    try {
      const lines = fixed
        ? undefined
        : data.eligible
            .filter((e) => (qty[e.lot_id] ?? 0) > 0)
            .map((e) => ({ lot_id: e.lot_id, qty: qty[e.lot_id] ?? 0 }));
      const transfer = await custodyApi.handover(
        data.gs_id,
        {
          mode_code: mode,
          ...(lines ? { lines } : {}),
          ...(notes.trim() ? { notes: notes.trim() } : {}),
        },
        idemKey,
      );
      onDone(transfer.id);
    } catch (err) {
      const apiErr = toApiError(err);
      setFailure(apiErr);
      if (apiErr.status >= 400 && apiErr.status < 500) setIdemKey(newIdempotencyKey());
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <h1 className="page__title">Handover to {data.to_location_name}</h1>
      <p className="page__subtitle">
        GS {data.gs_no} · from {data.from_location_name}
        {fixed ? ' · Complete Sales Return with packaging (fixed lines)' : ''}
      </p>

      {data.blocked ? (
        <div className="banner" role="status" style={{ marginBottom: '1rem' }}>
          <Ban size={18} aria-hidden="true" /> {data.blocked.message}
        </div>
      ) : null}

      {data.live_transfers.length > 0 ? (
        <section className="card" style={{ marginBottom: '1rem' }} aria-label="Open transfers">
          <div className="card-body">
            <strong>Open transfers of this GS</strong>
            <ul style={{ listStyle: 'none', padding: 0, margin: '0.5rem 0 0' }}>
              {data.live_transfers.map((t) => (
                <li
                  key={t.id}
                  style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}
                >
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => {
                      onDone(t.id);
                    }}
                  >
                    {t.transfer_no}
                  </Button>
                  <TransferStatusBadge status={t.status} inTransit={t.stock_moved} />
                </li>
              ))}
            </ul>
          </div>
        </section>
      ) : null}

      <section aria-label="Eligible lines" style={{ marginBottom: '1rem' }}>
        <h2 style={{ fontSize: '1rem', margin: '0 0 0.5rem' }}>
          To hand over ({String(fixed ? data.eligible.reduce((a, e) => a + e.qty, 0) : total)} pcs)
        </h2>
        {data.eligible.length === 0 ? (
          <EmptyState
            title="Nothing eligible"
            hint="No allowed, non-pending stock waits in staging."
          />
        ) : (
          <ul className="custody-lines">
            {data.eligible.map((e) => (
              <li key={e.lot_id} className="card custody-line">
                <div className="custody-line__head">
                  <strong>{lineTitle(e)}</strong>
                  {e.condition_label ? <Badge variant="info">{e.condition_label}</Badge> : null}
                </div>
                {fixed ? (
                  <p style={{ margin: '0.25rem 0 0' }}>{String(e.qty)} pcs</p>
                ) : (
                  <QtyStepper
                    id={`handover-${e.lot_id}`}
                    label={`Quantity (max ${String(e.qty)})`}
                    value={qty[e.lot_id] ?? 0}
                    disabled={!data.can_initiate}
                    onChange={(v) => {
                      setQty((q) => ({ ...q, [e.lot_id]: Math.min(v, e.qty) }));
                    }}
                  />
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {data.excluded.length > 0 ? (
        <section aria-label="Held back" style={{ marginBottom: '1rem' }}>
          <h2 style={{ fontSize: '1rem', margin: '0 0 0.5rem' }}>Held back (not transferred)</h2>
          <ul className="custody-lines">
            {data.excluded.map((x, i) => (
              <li
                key={`${x.lot_id ?? 'x'}-${x.reason_code}-${String(i)}`}
                className="card custody-line custody-line--muted"
              >
                <div className="custody-line__head">
                  <strong>{lineTitle(x)}</strong>
                  <Badge variant={x.reason_code === 'HAZARD' ? 'danger' : 'warning'}>
                    {x.reason_label}
                  </Badge>
                </div>
                <p style={{ margin: '0.25rem 0 0', fontSize: '0.875rem' }}>
                  {String(x.qty)} pcs
                  {x.condition_label ? ` · ${x.condition_label}` : ''}
                  {x.location_name ? ` · ${x.location_name}` : ''}
                  {x.detail ? ` · ${x.detail}` : ''}
                </p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {data.can_initiate ? (
        <section className="card" aria-label="Confirm handover">
          <div className="card-body" style={{ display: 'grid', gap: '0.75rem' }}>
            <div>
              <label className="form-label" htmlFor="handover-mode">
                Custody transfer mode
              </label>
              <Select
                id="handover-mode"
                value={mode}
                options={data.mode_options.map((o) => ({ value: o.code, label: o.label }))}
                onChange={(e) => {
                  setMode(e.target.value);
                }}
              />
            </div>
            <div>
              <label className="form-label" htmlFor="handover-notes">
                Notes (optional)
              </label>
              <Textarea
                id="handover-notes"
                rows={2}
                value={notes}
                onChange={(e) => {
                  setNotes(e.target.value);
                }}
              />
            </div>
            {failure ? <ErrorState error={failure} title="Handover not started" /> : null}
            <div className="sticky-submit">
              <Button
                type="button"
                variant="primary"
                size="lg"
                style={{ width: '100%' }}
                isLoading={busy}
                disabled={!mode || (!fixed && total === 0)}
                onClick={() => {
                  void submit();
                }}
              >
                {fixed ? (
                  <PackageCheck size={18} aria-hidden="true" />
                ) : (
                  <Send size={18} aria-hidden="true" />
                )}{' '}
                Confirm handover
              </Button>
            </div>
          </div>
        </section>
      ) : null}
    </>
  );
}
