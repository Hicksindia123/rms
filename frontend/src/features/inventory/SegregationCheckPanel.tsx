import { useCallback, useState } from 'react';
import { ShieldCheck, ShieldAlert } from 'lucide-react';

import { DataView, type DataViewColumn } from '@/components/erp';
import { Badge, Button } from '@/components/ui';
import { formatDateTime, humanize } from '@/features/goods-slips/format';
import { useApiQuery } from '@/hooks/useApiQuery';
import { inventoryApi } from './api';
import type { SegregationCheck, Violation } from './types';

/** BR-30 / G-04 / G-05 / G-08 / G-09 / G-12 integrity check: expected to find nothing. */
export function SegregationCheckPanel() {
  const [runKey, setRunKey] = useState(0);
  const fetcher = useCallback(
    () => inventoryApi.segregationCheck(),
    // runKey re-runs the check on demand.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [runKey],
  );
  const { data, error, loading, reload } = useApiQuery<SegregationCheck>(fetcher);

  const columns: DataViewColumn<Violation>[] = [
    { key: 'guard', header: 'Rule', render: (v) => <Badge variant="danger">{v.guard_ref}</Badge> },
    { key: 'rule', header: 'Check', render: (v) => humanize(v.rule_code) },
    { key: 'detail', header: 'Detail', render: (v) => v.detail },
    { key: 'gs', header: 'GS', render: (v) => v.gs_no ?? '—' },
    { key: 'qty', header: 'Qty', align: 'right', render: (v) => v.qty },
  ];

  return (
    <section aria-label="Segregation check">
      <div className="filters" style={{ alignItems: 'center' }}>
        <div>
          {data ? (
            data.violation_count === 0 ? (
              <p
                role="status"
                style={{ margin: 0, display: 'flex', gap: '0.5rem', alignItems: 'center' }}
              >
                <ShieldCheck
                  size={20}
                  aria-hidden="true"
                  style={{ color: 'var(--color-success)' }}
                />
                No segregation violations · checked {formatDateTime(data.checked_at)}
              </p>
            ) : (
              <p
                role="alert"
                style={{ margin: 0, display: 'flex', gap: '0.5rem', alignItems: 'center' }}
              >
                <ShieldAlert
                  size={20}
                  aria-hidden="true"
                  style={{ color: 'var(--color-danger)' }}
                />
                {data.violation_count} violation(s) found · checked{' '}
                {formatDateTime(data.checked_at)}
              </p>
            )
          ) : null}
          {data?.last_nightly_run ? (
            <p className="timeline__meta">
              Last nightly run {formatDateTime(data.last_nightly_run.run_at)}:{' '}
              {data.last_nightly_run.violation_count} violation(s)
            </p>
          ) : data ? (
            <p className="timeline__meta">The nightly check has not run yet.</p>
          ) : null}
        </div>
        <div className="filters__actions">
          <Button
            type="button"
            variant="primary"
            style={{ minHeight: 44 }}
            disabled={loading}
            onClick={() => {
              setRunKey((n) => n + 1);
            }}
          >
            {loading ? 'Checking…' : 'Run check now'}
          </Button>
        </div>
      </div>
      <DataView<Violation>
        rows={data?.violations ?? null}
        rowKey={(v) => `${v.rule_code}:${v.lot_id}:${v.location_id}`}
        columns={columns}
        loading={loading}
        error={error}
        onRetry={reload}
        emptyTitle="Custody boundary intact"
        emptyHint="Functional stock is only with the Intermediate Store; non-functional stock and parts only with the Spare Parts Manager."
        renderCard={(v) => (
          <div style={{ display: 'grid', gap: '0.25rem' }}>
            <span>
              <Badge variant="danger">{v.guard_ref}</Badge> {humanize(v.rule_code)}
            </span>
            <span>{v.detail}</span>
            <span style={{ color: 'var(--color-muted)', fontSize: '0.875rem' }}>
              {v.gs_no ?? '—'} · Qty {v.qty}
            </span>
          </div>
        )}
      />
    </section>
  );
}
