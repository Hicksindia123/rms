/**
 * DEC-76: E-Commerce pieces issued to the Intermediate Store (good pieces from unboxing, repaired
 * pieces back from a department). A user of that store acknowledges the receipt; only then does
 * the stock move into the store. Read-only roles see every store.
 */
import React, { useCallback, useRef, useState } from 'react';
import { PackageCheck, RefreshCw } from 'lucide-react';

import { PageHeader } from '@/components/erp';
import { Badge, Button, EmptyState, ErrorState, LoadingState } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { newIdempotencyKey, toApiError, type ApiError } from '@/lib/api/client';
import { formatDateTime } from '@/features/goods-slips/format';
import '@/features/goods-slips/gateForm.css';

import { settlementApi } from './api';
import type { StoreReceipts } from './types';

interface Props {
  onOpen: (returnId: string) => void;
}

type State = 'PENDING' | 'ACKNOWLEDGED';

export const EcomStoreReceiptsPage: React.FC<Props> = ({ onOpen }) => {
  const [state, setState] = useState<State>('PENDING');
  const fetcher = useCallback(() => settlementApi.receipts(state), [state]);
  const query = useApiQuery<StoreReceipts>(fetcher);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const key = useRef(newIdempotencyKey());

  const rows = query.data?.rows ?? [];
  const ackable = rows.filter((r) => r.can_acknowledge);
  const chosen = ackable.filter((r) => selected.has(r.id));

  const toggle = (id: string, on: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const acknowledge = async () => {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const res = await settlementApi.acknowledge(
        chosen.map((r) => r.id),
        key.current,
      );
      key.current = newIdempotencyKey();
      setSelected(new Set());
      setDone(`${String(res.rows.length)} receipt(s) acknowledged.`);
      query.reload();
    } catch (err) {
      console.error('Acknowledging the receipts failed', { err });
      setError(toApiError(err));
      key.current = newIdempotencyKey();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6" data-testid="ecom-store-receipts">
      <PageHeader
        title="E-Commerce Receipts"
        subtitle="Acknowledge the E-Commerce pieces your store has received; the stock then moves into your store."
        actions={
          <Button type="button" variant="outline" className="min-h-[44px]" onClick={query.reload}>
            <RefreshCw className="h-4 w-4" aria-hidden="true" /> Refresh
          </Button>
        }
      />
      <div className="gate-return-type" role="tablist" aria-label="Receipts">
        {(['PENDING', 'ACKNOWLEDGED'] as const).map((s) => (
          <button
            key={s}
            type="button"
            role="tab"
            aria-selected={state === s}
            aria-checked={state === s}
            className="gate-return-type__option"
            onClick={() => {
              setState(s);
              setSelected(new Set());
            }}
          >
            {s === 'PENDING' ? 'To acknowledge' : 'Acknowledged'}
          </button>
        ))}
      </div>
      {done ? (
        <p
          className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-100"
          role="status"
        >
          {done}
        </p>
      ) : null}
      {error ? <ErrorState error={error} title="Could not acknowledge" /> : null}

      {query.error ? (
        <ErrorState
          error={query.error}
          onRetry={query.reload}
          title="Could not load the receipts"
        />
      ) : !query.data ? (
        <LoadingState label="Loading receipts…" />
      ) : rows.length === 0 ? (
        <EmptyState
          title={state === 'PENDING' ? 'Nothing to acknowledge' : 'No acknowledged receipt'}
          hint="Pieces appear here when the unboxing user sends good or repaired E-Commerce pieces to your store."
        />
      ) : (
        <>
          {state === 'PENDING' && ackable.length > 0 ? (
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <Button
                type="button"
                variant="outline"
                className="min-h-[44px]"
                onClick={() => {
                  setSelected(
                    chosen.length === ackable.length
                      ? new Set()
                      : new Set(ackable.map((r) => r.id)),
                  );
                }}
              >
                {chosen.length === ackable.length ? 'Clear selection' : 'Select all'}
              </Button>
              <Button
                type="button"
                className="min-h-[44px]"
                disabled={busy || chosen.length === 0}
                data-testid="receipts-acknowledge"
                onClick={() => {
                  void acknowledge();
                }}
              >
                <PackageCheck className="h-4 w-4" aria-hidden="true" /> Acknowledge received (
                {chosen.length})
              </Button>
            </div>
          ) : null}
          <ul className="m-0 list-none space-y-3 p-0" aria-label="Store receipts">
            {rows.map((r) => (
              <li
                key={r.id}
                className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900"
                data-testid={`receipt-${r.return_no}`}
              >
                {r.can_acknowledge ? (
                  <input
                    type="checkbox"
                    className="mt-1 h-6 w-6 shrink-0"
                    aria-label={`Select ${r.return_no}`}
                    checked={selected.has(r.id)}
                    onChange={(e) => {
                      toggle(r.id, e.target.checked);
                    }}
                  />
                ) : null}
                <button
                  type="button"
                  className="min-h-[44px] min-w-0 flex-1 space-y-1 border-0 bg-transparent p-0 text-left"
                  onClick={() => {
                    onOpen(r.return_id);
                  }}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">
                      {r.product_name ?? '—'} {r.product_code ? `(${r.product_code})` : ''}
                    </span>
                    <Badge variant="info">Qty {r.qty}</Badge>
                    <Badge variant={r.source === 'REPAIR' ? 'warning' : 'success'}>
                      {r.source === 'REPAIR' ? 'Repaired' : r.source_label}
                    </Badge>
                  </div>
                  <div className="break-words text-sm text-slate-600 dark:text-slate-300">
                    {r.platform_label} · Order {r.order_id} · {r.return_no}
                  </div>
                  <div className="text-xs text-slate-500">
                    {r.store_name} · from {r.from_location_name} · issued{' '}
                    {formatDateTime(r.created_at)}
                    {r.acknowledged_at
                      ? ` · acknowledged ${formatDateTime(r.acknowledged_at)} by ${r.acknowledged_by_name ?? '—'}`
                      : ''}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
};
