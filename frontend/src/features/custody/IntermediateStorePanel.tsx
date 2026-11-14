import { useCallback, useMemo, useState } from 'react';
import { BadgeCheck, Package } from 'lucide-react';

import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
  Modal,
  Select,
  Textarea,
} from '@/components/ui';
import { humanize } from '@/features/goods-slips/format';
import { QtyStepper } from '@/features/itemization/LineParts';
import { useApiQuery } from '@/hooks/useApiQuery';
import { newIdempotencyKey, toApiError, type ApiError } from '@/lib/api/client';
import { custodyApi } from './api';
import { lineTitle } from './rules';
import type { StoreStock, StoreStockRow } from './types';

type GroupBy = 'gs' | 'product' | 'condition' | 'routing';
const GROUPS: Array<{ value: GroupBy; label: string }> = [
  { value: 'gs', label: 'Goods slip' },
  { value: 'product', label: 'Product' },
  { value: 'condition', label: 'Condition' },
  { value: 'routing', label: 'Routing hint' },
];

function groupKey(r: StoreStockRow, by: GroupBy): string {
  if (by === 'gs') return r.gs_no;
  if (by === 'product') return r.product_name ?? r.product_code ?? '—';
  if (by === 'condition') return r.condition_label ?? humanize(r.condition_class);
  return humanize(r.routing_hint ?? 'NONE');
}

/** BR-22 Intermediate Store stock; DEC-14 direct classification and DEC-27 packaging check. */
export function IntermediateStorePanel({ onOpenGs }: { onOpenGs: (id: string) => void }) {
  const [q, setQ] = useState('');
  const [query, setQuery] = useState('');
  const [groupBy, setGroupBy] = useState<GroupBy>('gs');
  const fetcher = useCallback(() => custodyApi.storeStock(query ? { q: query } : {}), [query]);
  const { data, error, loading, reload } = useApiQuery<StoreStock>(fetcher);
  const [classifyRow, setClassifyRow] = useState<StoreStockRow | null>(null);
  const [packagingRow, setPackagingRow] = useState<StoreStockRow | null>(null);

  const groups = useMemo(() => {
    const out = new Map<string, StoreStockRow[]>();
    for (const r of data?.rows ?? []) {
      const k = groupKey(r, groupBy);
      out.set(k, [...(out.get(k) ?? []), r]);
    }
    return [...out.entries()];
  }, [data, groupBy]);

  return (
    <section aria-label="Intermediate Store stock">
      <form
        style={{
          display: 'flex',
          gap: '0.75rem',
          flexWrap: 'wrap',
          alignItems: 'flex-end',
          marginBottom: '1rem',
        }}
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(q.trim());
        }}
      >
        <div style={{ flex: '1 1 200px' }}>
          <label className="form-label" htmlFor="store-q">
            Search GS / product
          </label>
          <Input
            id="store-q"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
            }}
          />
        </div>
        <div style={{ flex: '1 1 160px' }}>
          <label className="form-label" htmlFor="store-group">
            Group by
          </label>
          <Select
            id="store-group"
            value={groupBy}
            placeholder=""
            options={GROUPS}
            onChange={(e) => {
              setGroupBy(e.target.value as GroupBy);
            }}
          />
        </div>
        <Button type="submit" variant="secondary">
          Search
        </Button>
      </form>

      {error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : loading && !data ? (
        <LoadingState />
      ) : !data || data.rows.length === 0 ? (
        <EmptyState
          title="The Intermediate Store is empty"
          hint="Accepted handovers appear here."
        />
      ) : (
        groups.map(([title, rows]) => (
          <div key={title} style={{ marginBottom: '1rem' }}>
            <h2 style={{ fontSize: '0.9375rem', margin: '0 0 0.5rem' }}>
              {title} · {String(rows.reduce((a, r) => a + r.qty, 0))} pcs
            </h2>
            <ul className="custody-lines">
              {rows.map((r) => (
                <li key={r.lot_id} className="card custody-line">
                  <div className="custody-line__head">
                    <strong>{lineTitle(r)}</strong>
                    <Badge variant="neutral">{String(r.qty)} pcs</Badge>
                    {r.condition_label ? <Badge variant="info">{r.condition_label}</Badge> : null}
                    <Badge variant={r.next_step === 'AWAITING_TECHNICIAN' ? 'warning' : 'success'}>
                      {humanize(r.next_step)}
                    </Badge>
                  </div>
                  <p
                    style={{
                      margin: '0.25rem 0 0',
                      fontSize: '0.8125rem',
                      color: 'var(--color-muted)',
                    }}
                  >
                    GS{' '}
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => {
                        onOpenGs(r.gs_id);
                      }}
                    >
                      {r.gs_no}
                    </Button>
                    · {humanize(r.condition_class)}
                    {r.routing_hint ? ` · routing ${humanize(r.routing_hint)}` : ''}
                    {r.last_packaging_check
                      ? ` · packaging ${humanize(r.last_packaging_check.result_code)}`
                      : ''}
                  </p>
                  <div
                    style={{
                      display: 'flex',
                      gap: '0.5rem',
                      flexWrap: 'wrap',
                      marginTop: '0.5rem',
                    }}
                  >
                    {r.can_classify ? (
                      <Button
                        type="button"
                        variant="primary"
                        onClick={() => {
                          setClassifyRow(r);
                        }}
                      >
                        <BadgeCheck size={16} aria-hidden="true" /> Classify Functional Good
                      </Button>
                    ) : null}
                    {data.can_check_packaging ? (
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => {
                          setPackagingRow(r);
                        }}
                      >
                        <Package size={16} aria-hidden="true" /> Packaging check
                      </Button>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ))
      )}

      {classifyRow ? (
        <ClassifyModal
          row={classifyRow}
          onClose={() => {
            setClassifyRow(null);
          }}
          onDone={() => {
            setClassifyRow(null);
            reload();
          }}
        />
      ) : null}
      {packagingRow ? (
        <PackagingModal
          row={packagingRow}
          onClose={() => {
            setPackagingRow(null);
          }}
          onDone={() => {
            setPackagingRow(null);
            reload();
          }}
        />
      ) : null}
    </section>
  );
}

function useCommand() {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [idemKey, setIdemKey] = useState(newIdempotencyKey);
  const run = async (action: (key: string) => Promise<unknown>, onDone: () => void) => {
    setBusy(true);
    setFailure(null);
    try {
      await action(idemKey);
      onDone();
    } catch (err) {
      const apiErr = toApiError(err);
      setFailure(apiErr);
      if (apiErr.status >= 400 && apiErr.status < 500) setIdemKey(newIdempotencyKey());
    } finally {
      setBusy(false);
    }
  };
  return { busy, failure, run };
}

function ClassifyModal({
  row,
  onClose,
  onDone,
}: {
  row: StoreStockRow;
  onClose: () => void;
  onDone: () => void;
}) {
  const [qty, setQty] = useState(row.qty);
  const [remarks, setRemarks] = useState('');
  const { busy, failure, run } = useCommand();
  return (
    <Modal
      isOpen
      onClose={onClose}
      title={`Classify ${lineTitle(row)}`}
      footer={
        <Button
          type="button"
          variant="primary"
          isLoading={busy}
          disabled={qty < 1}
          onClick={() => {
            void run(
              (k) => custodyApi.classify(row.lot_id, qty, remarks.trim() || null, k),
              onDone,
            );
          }}
        >
          Classify {String(qty)} as Functional Good
        </Button>
      }
    >
      <p style={{ marginTop: 0 }}>Visually OK lots routed sellable skip the technician (DEC-14).</p>
      <QtyStepper
        id="classify-qty"
        label={`Quantity (max ${String(row.qty)})`}
        value={qty}
        onChange={(v) => {
          setQty(Math.min(v, row.qty));
        }}
      />
      <label className="form-label" htmlFor="classify-remarks">
        Remarks (optional)
      </label>
      <Textarea
        id="classify-remarks"
        rows={2}
        value={remarks}
        onChange={(e) => {
          setRemarks(e.target.value);
        }}
      />
      {failure ? <ErrorState error={failure} title="Not classified" /> : null}
    </Modal>
  );
}

function PackagingModal({
  row,
  onClose,
  onDone,
}: {
  row: StoreStockRow;
  onClose: () => void;
  onDone: () => void;
}) {
  const [replaced, setReplaced] = useState(0);
  const [remarks, setRemarks] = useState('');
  const { busy, failure, run } = useCommand();
  const submit = (result: 'OK' | 'REPLACED') => {
    void run(
      (k) =>
        custodyApi.packagingCheck(
          row.lot_id,
          { result, qty_replaced: result === 'OK' ? 0 : replaced, remarks: remarks.trim() || null },
          k,
        ),
      onDone,
    );
  };
  return (
    <Modal
      isOpen
      onClose={onClose}
      title={`Packaging check · ${lineTitle(row)}`}
      footer={
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          <Button
            type="button"
            variant="secondary"
            isLoading={busy}
            onClick={() => {
              submit('OK');
            }}
          >
            Packaging OK
          </Button>
          <Button
            type="button"
            variant="primary"
            isLoading={busy}
            disabled={replaced < 1}
            onClick={() => {
              submit('REPLACED');
            }}
          >
            Replaced {String(replaced)}
          </Button>
        </div>
      }
    >
      <QtyStepper
        id="packaging-qty"
        label={`Packaging replaced (max ${String(row.qty)})`}
        value={replaced}
        onChange={(v) => {
          setReplaced(Math.min(v, row.qty));
        }}
      />
      <label className="form-label" htmlFor="packaging-remarks">
        Remarks (optional)
      </label>
      <Textarea
        id="packaging-remarks"
        rows={2}
        value={remarks}
        onChange={(e) => {
          setRemarks(e.target.value);
        }}
      />
      {failure ? <ErrorState error={failure} title="Packaging check not recorded" /> : null}
    </Modal>
  );
}
