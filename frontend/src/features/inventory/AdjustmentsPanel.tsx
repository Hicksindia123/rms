import { useCallback, useState } from 'react';

import { DataView, type DataViewColumn } from '@/components/erp';
import { Badge, Button, Modal, Select, Textarea } from '@/components/ui';
import { formatDateTime, humanize } from '@/features/goods-slips/format';
import { useApiQuery } from '@/hooks/useApiQuery';
import { newIdempotencyKey, toApiError, type ApiError } from '@/lib/api/client';
import { inventoryApi } from './api';
import { formatDelta } from './rules';
import type { Adjustment, AdjustmentPage, AdjustmentStatus } from './types';

const STATUSES: AdjustmentStatus[] = ['REQUESTED', 'APPROVED', 'REJECTED'];

interface Decision {
  adjustment: Adjustment;
  kind: 'approve' | 'reject';
  key: string;
}

/** Stock count adjustments: custodians request (from a stock card), approvers decide. */
export function AdjustmentsPanel({ reloadToken }: { reloadToken: number }) {
  const [status, setStatus] = useState<AdjustmentStatus | ''>('REQUESTED');
  const [page, setPage] = useState(1);
  const [localReload, setLocalReload] = useState(0);
  const fetcher = useCallback(
    () => inventoryApi.adjustments(status, page),
    // reload tokens force a refetch after commands.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [status, page, reloadToken, localReload],
  );
  const { data, error, loading, reload } = useApiQuery<AdjustmentPage>(fetcher);
  const [decision, setDecision] = useState<Decision | null>(null);

  const actions = (a: Adjustment) =>
    a.can_decide ? (
      <span style={{ display: 'inline-flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        <Button
          type="button"
          size="sm"
          variant="primary"
          style={{ minHeight: 44 }}
          onClick={() => {
            setDecision({ adjustment: a, kind: 'approve', key: newIdempotencyKey() });
          }}
        >
          Approve
        </Button>
        <Button
          type="button"
          size="sm"
          variant="danger"
          style={{ minHeight: 44 }}
          onClick={() => {
            setDecision({ adjustment: a, kind: 'reject', key: newIdempotencyKey() });
          }}
        >
          Reject
        </Button>
      </span>
    ) : null;

  const columns: DataViewColumn<Adjustment>[] = [
    {
      key: 'item',
      header: 'Item',
      render: (a) => a.product_name ?? (a.part_type ? `Part · ${a.part_type}` : '—'),
    },
    { key: 'gs', header: 'GS', render: (a) => a.gs_no ?? '—' },
    { key: 'location', header: 'Location', render: (a) => a.location_name },
    {
      key: 'count',
      header: 'System → counted',
      align: 'right',
      render: (a) => `${String(a.system_qty)} → ${String(a.counted_qty)} (${formatDelta(a.delta)})`,
    },
    { key: 'reason', header: 'Reason', render: (a) => a.reason },
    {
      key: 'requested',
      header: 'Requested',
      render: (a) => `${a.requested_by_name ?? '—'} · ${formatDateTime(a.requested_at)}`,
    },
    { key: 'status', header: 'Status', render: (a) => <StatusBadge a={a} /> },
    { key: 'actions', header: 'Decision', render: actions },
  ];

  return (
    <section aria-label="Stock adjustments">
      <div className="filters">
        <div>
          <label className="form-label" htmlFor="adj-status">
            Status
          </label>
          <Select
            id="adj-status"
            placeholder="All"
            value={status}
            options={STATUSES.map((s) => ({ value: s, label: humanize(s) }))}
            onChange={(e) => {
              setStatus(e.target.value as AdjustmentStatus | '');
              setPage(1);
            }}
          />
        </div>
      </div>
      <p className="stat-row">
        A custodian reports a count difference from a lot&apos;s stock card; an approver (never the
        same person) posts it.
      </p>
      <DataView<Adjustment>
        rows={data?.items ?? null}
        rowKey={(a) => a.id}
        columns={columns}
        loading={loading}
        error={error}
        onRetry={reload}
        emptyTitle="No stock adjustments"
        {...(status ? { emptyHint: `Nothing ${humanize(status).toLowerCase()}.` } : {})}
        page={page}
        pageSize={data?.page_size ?? 25}
        {...(data ? { total: data.total } : {})}
        onPageChange={setPage}
        renderCard={(a) => (
          <div style={{ display: 'grid', gap: '0.375rem' }}>
            <strong>{a.product_name ?? (a.part_type ? `Part · ${a.part_type}` : '—')}</strong>
            <span style={{ color: 'var(--color-muted)', fontSize: '0.875rem' }}>
              {a.gs_no ?? '—'} · {a.location_name}
            </span>
            <span>
              {a.system_qty} → {a.counted_qty} ({formatDelta(a.delta)}) <StatusBadge a={a} />
            </span>
            <span style={{ fontSize: '0.875rem' }}>{a.reason}</span>
            <span style={{ color: 'var(--color-muted)', fontSize: '0.8125rem' }}>
              {a.requested_by_name ?? '—'} · {formatDateTime(a.requested_at)}
            </span>
            {actions(a)}
          </div>
        )}
      />
      {decision ? (
        <DecisionModal
          decision={decision}
          onClose={() => {
            setDecision(null);
          }}
          onDone={() => {
            setDecision(null);
            setLocalReload((n) => n + 1);
          }}
        />
      ) : null}
    </section>
  );
}

function StatusBadge({ a }: { a: Adjustment }) {
  const variant =
    a.status === 'APPROVED' ? 'success' : a.status === 'REJECTED' ? 'danger' : 'warning';
  return <Badge variant={variant}>{humanize(a.status)}</Badge>;
}

function DecisionModal({
  decision,
  onClose,
  onDone,
}: {
  decision: Decision;
  onClose: () => void;
  onDone: () => void;
}) {
  const { adjustment: a, kind, key } = decision;
  const [remarks, setRemarks] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const needsRemarks = kind === 'reject';
  const submit = () => {
    setBusy(true);
    setError(null);
    const call =
      kind === 'approve'
        ? inventoryApi.approveAdjustment(a.id, remarks.trim(), key)
        : inventoryApi.rejectAdjustment(a.id, remarks.trim());
    call
      .then(onDone)
      .catch((err: unknown) => {
        setError(toApiError(err));
      })
      .finally(() => {
        setBusy(false);
      });
  };
  return (
    <Modal
      isOpen
      onClose={onClose}
      title={kind === 'approve' ? 'Approve stock adjustment' : 'Reject stock adjustment'}
      footer={
        <>
          <Button type="button" variant="secondary" style={{ minHeight: 44 }} onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            variant={kind === 'approve' ? 'primary' : 'danger'}
            style={{ minHeight: 44 }}
            disabled={busy || (needsRemarks && remarks.trim() === '')}
            onClick={submit}
          >
            {busy ? 'Saving…' : kind === 'approve' ? 'Approve' : 'Reject'}
          </Button>
        </>
      }
    >
      <p style={{ marginTop: 0 }}>
        {a.location_name}: {a.system_qty} → {a.counted_qty} ({formatDelta(a.delta)}). Current system
        quantity {a.current_qty}.
      </p>
      <p>Reason: {a.reason}</p>
      <label className="form-label" htmlFor="adj-remarks">
        Remarks{needsRemarks ? <span className="required-star"> *</span> : null}
      </label>
      <Textarea
        id="adj-remarks"
        rows={2}
        maxLength={1000}
        value={remarks}
        onChange={(e) => {
          setRemarks(e.target.value);
        }}
      />
      {error ? (
        <p role="alert" className="form-error">
          {error.message}
          {error.requestId ? ` (Request ID: ${error.requestId})` : ''}
        </p>
      ) : null}
    </Modal>
  );
}
