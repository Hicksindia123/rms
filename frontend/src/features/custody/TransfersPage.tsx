import { useCallback, useState } from 'react';

import { DataView } from '@/components/erp';
import { Checkbox, Select } from '@/components/ui';
import { useAuth } from '@/features/auth/useAuth';
import { formatDateTime, humanize } from '@/features/goods-slips/format';
import { useApiQuery } from '@/hooks/useApiQuery';
import { custodyApi } from './api';
import { TransferStatusBadge } from './display';
import { IntermediateStorePanel } from './IntermediateStorePanel';
import type { TransferPage, TransferSummary } from './types';

const STATUSES = ['INITIATED', 'DISCREPANCY', 'ACCEPTED', 'RECONCILED', 'CANCELLED'] as const;

interface Props {
  /** P4-01: status filter from the URL (dashboard click-through), e.g. INITIATED. */
  initialStatus?: string;
  tab: 'transfers' | 'store';
  onTab: (tab: 'transfers' | 'store') => void;
  onOpen: (id: string) => void;
  onOpenGs: (id: string) => void;
}

/** Custody transfers (all engine moves) and the Intermediate Store stock (BR-22). */
export function TransfersPage({ initialStatus = '', tab, onTab, onOpen, onOpenGs }: Props) {
  const { can } = useAuth();
  return (
    <div className="page">
      <h1 className="page__title">Custody</h1>
      <p className="page__subtitle">
        Two-phase transfers: initiate → in transit → count and accept.
      </p>
      <div className="tabs" role="tablist">
        <button
          type="button"
          role="tab"
          className="tabs__tab"
          aria-selected={tab === 'transfers'}
          onClick={() => {
            onTab('transfers');
          }}
        >
          Transfers
        </button>
        {can('custody', 'view') ? (
          <button
            type="button"
            role="tab"
            className="tabs__tab"
            aria-selected={tab === 'store'}
            onClick={() => {
              onTab('store');
            }}
          >
            Intermediate Store
          </button>
        ) : null}
      </div>
      {tab === 'store' ? (
        <IntermediateStorePanel onOpenGs={onOpenGs} />
      ) : (
        <TransferList onOpen={onOpen} initialStatus={initialStatus} />
      )}
    </div>
  );
}

function TransferList({
  onOpen,
  initialStatus,
}: {
  onOpen: (id: string) => void;
  initialStatus: string;
}) {
  const [status, setStatus] = useState(initialStatus);
  const [mine, setMine] = useState(false);
  const [page, setPage] = useState(1);
  const fetcher = useCallback(
    () =>
      custodyApi.list({
        ...(status ? { status } : {}),
        mine_to_accept: mine,
        page,
      }),
    [status, mine, page],
  );
  const { data, error, loading, reload } = useApiQuery<TransferPage>(fetcher);

  return (
    <>
      <div
        style={{
          display: 'flex',
          gap: '1rem',
          flexWrap: 'wrap',
          alignItems: 'flex-end',
          marginBottom: '1rem',
        }}
      >
        <div style={{ minWidth: '200px' }}>
          <label className="form-label" htmlFor="transfer-status">
            Status
          </label>
          <Select
            id="transfer-status"
            value={status}
            placeholder="All statuses"
            options={STATUSES.map((s) => ({ value: s, label: humanize(s) }))}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
          />
        </div>
        <Checkbox
          id="transfer-mine"
          label="Waiting for my count"
          className="touch-label"
          checked={mine}
          onChange={(e) => {
            setMine(e.target.checked);
            setPage(1);
          }}
        />
      </div>
      <DataView<TransferSummary>
        rows={data?.items ?? null}
        rowKey={(r) => r.id}
        loading={loading}
        error={error}
        onRetry={reload}
        emptyTitle={mine ? 'Nothing waiting for your count' : 'No transfers'}
        onRowClick={(r) => {
          onOpen(r.id);
        }}
        rowLabel={(r) => `Open ${r.transfer_no}`}
        page={page}
        pageSize={data?.page_size ?? 25}
        {...(data ? { total: data.total } : {})}
        onPageChange={setPage}
        columns={[
          { key: 'no', header: 'Transfer', render: (r) => r.transfer_no },
          { key: 'gs', header: 'GS', render: (r) => r.gs_no ?? '—' },
          {
            key: 'route',
            header: 'From → To',
            render: (r) => `${r.from_location_name} → ${r.to_location_name}`,
          },
          {
            key: 'qty',
            header: 'Pcs',
            align: 'right',
            render: (r) => (r.total_qty === null ? '—' : String(r.total_qty)),
          },
          {
            key: 'status',
            header: 'Status',
            render: (r) => <TransferStatusBadge status={r.status} inTransit={r.stock_moved} />,
          },
          {
            key: 'at',
            header: 'Initiated',
            render: (r) => `${r.initiated_by_name ?? ''} · ${formatDateTime(r.initiated_at)}`,
          },
        ]}
        renderCard={(r) => (
          <div style={{ display: 'grid', gap: '0.25rem' }}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                gap: '0.5rem',
                flexWrap: 'wrap',
              }}
            >
              <strong>{r.transfer_no}</strong>
              <TransferStatusBadge status={r.status} inTransit={r.stock_moved} />
            </div>
            <span>
              {r.from_location_name} → {r.to_location_name}
            </span>
            <span style={{ fontSize: '0.8125rem', color: 'var(--color-muted)' }}>
              {r.gs_no ? `GS ${r.gs_no} · ` : ''}
              {r.total_qty === null ? '' : `${String(r.total_qty)} pcs · `}
              {formatDateTime(r.initiated_at)}
            </span>
          </div>
        )}
      />
    </>
  );
}
