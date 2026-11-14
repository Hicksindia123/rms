import { useCallback, useMemo, useState } from 'react';
import { Plus, RefreshCw, CheckCircle, Clock, User, Layers } from 'lucide-react';
import { Button, Badge, LoadingState, ErrorState } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { servicingApi } from './api';
import type { BatchSummary } from './types';

interface Props {
  canAllot: boolean;
  onAllot: () => void;
  onReceive: (batchId: string) => void;
}

export function TechnicianBoardPage({ canAllot, onAllot, onReceive }: Props) {
  const [statusFilter, setStatusFilter] = useState<string>('ALL');

  const fetcher = useCallback(
    () => servicingApi.listBatches(statusFilter !== 'ALL' ? { status: statusFilter } : undefined),
    [statusFilter],
  );

  const { data: batchesData, loading, error, reload } = useApiQuery<BatchSummary[]>(fetcher);
  const batches = useMemo(() => batchesData ?? [], [batchesData]);

  const allottedCount = batches.filter((b) => b.status === 'ALLOTTED').length;
  const partialCount = batches.filter((b) => b.status === 'PARTIALLY_RECEIVED').length;
  const completedCount = batches.filter((b) => b.status === 'COMPLETED').length;

  return (
    <div
      style={{
        maxWidth: '1200px',
        margin: '0 auto',
        display: 'flex',
        flexDirection: 'column',
        gap: '1.25rem',
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: '1rem',
          backgroundColor: '#fff',
          padding: '1.25rem',
          borderRadius: '8px',
          boxShadow: '0 1px 3px rgba(0,0,0,0.08)',
        }}
      >
        <div>
          <h1 style={{ margin: 0, fontSize: '1.5rem', fontWeight: 700, color: '#0f172a' }}>
            Technician Servicing Board
          </h1>
          <p style={{ margin: '0.25rem 0 0 0', color: '#64748b', fontSize: '0.875rem' }}>
            Allotment and receiving results for technician servicing (Raj Kumar Ji)
          </p>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              reload();
            }}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.5rem',
              minHeight: '44px',
            }}
          >
            <RefreshCw size={16} />
            Refresh
          </Button>

          {canAllot && (
            <Button
              type="button"
              variant="primary"
              onClick={onAllot}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.5rem',
                minHeight: '44px',
                fontWeight: 600,
              }}
            >
              <Plus size={18} />
              Allot Batch
            </Button>
          )}
        </div>
      </div>

      {/* KPI Cards */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '1rem',
        }}
      >
        <div
          onClick={() => {
            setStatusFilter('ALL');
          }}
          style={{
            cursor: 'pointer',
            backgroundColor: '#fff',
            padding: '1rem',
            borderRadius: '8px',
            border: statusFilter === 'ALL' ? '2px solid #3b82f6' : '1px solid #e2e8f0',
            boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
          }}
        >
          <div style={{ color: '#64748b', fontSize: '0.8125rem', fontWeight: 600 }}>
            TOTAL BATCHES
          </div>
          <div
            style={{ fontSize: '1.75rem', fontWeight: 700, color: '#0f172a', marginTop: '0.25rem' }}
          >
            {batches.length}
          </div>
        </div>

        <div
          onClick={() => {
            setStatusFilter('ALLOTTED');
          }}
          style={{
            cursor: 'pointer',
            backgroundColor: '#fff',
            padding: '1rem',
            borderRadius: '8px',
            border: statusFilter === 'ALLOTTED' ? '2px solid #3b82f6' : '1px solid #e2e8f0',
            boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
          }}
        >
          <div style={{ color: '#0284c7', fontSize: '0.8125rem', fontWeight: 600 }}>
            ALLOTTED (ACTIVE)
          </div>
          <div
            style={{ fontSize: '1.75rem', fontWeight: 700, color: '#0284c7', marginTop: '0.25rem' }}
          >
            {allottedCount}
          </div>
        </div>

        <div
          onClick={() => {
            setStatusFilter('PARTIALLY_RECEIVED');
          }}
          style={{
            cursor: 'pointer',
            backgroundColor: '#fff',
            padding: '1rem',
            borderRadius: '8px',
            border:
              statusFilter === 'PARTIALLY_RECEIVED' ? '2px solid #3b82f6' : '1px solid #e2e8f0',
            boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
          }}
        >
          <div style={{ color: '#d97706', fontSize: '0.8125rem', fontWeight: 600 }}>
            PARTIALLY RECEIVED
          </div>
          <div
            style={{ fontSize: '1.75rem', fontWeight: 700, color: '#d97706', marginTop: '0.25rem' }}
          >
            {partialCount}
          </div>
        </div>

        <div
          onClick={() => {
            setStatusFilter('COMPLETED');
          }}
          style={{
            cursor: 'pointer',
            backgroundColor: '#fff',
            padding: '1rem',
            borderRadius: '8px',
            border: statusFilter === 'COMPLETED' ? '2px solid #3b82f6' : '1px solid #e2e8f0',
            boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
          }}
        >
          <div style={{ color: '#16a34a', fontSize: '0.8125rem', fontWeight: 600 }}>COMPLETED</div>
          <div
            style={{ fontSize: '1.75rem', fontWeight: 700, color: '#16a34a', marginTop: '0.25rem' }}
          >
            {completedCount}
          </div>
        </div>
      </div>

      {/* Main Content Area */}
      {loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} />
      ) : batches.length === 0 ? (
        <div
          style={{
            backgroundColor: '#fff',
            padding: '3rem 1.5rem',
            borderRadius: '8px',
            textAlign: 'center',
            color: '#64748b',
          }}
        >
          <Layers size={40} style={{ color: '#94a3b8', margin: '0 auto 1rem' }} />
          <h3 style={{ margin: '0 0 0.5rem', color: '#1e293b' }}>No technician batches found</h3>
          <p style={{ margin: '0 0 1.25rem', fontSize: '0.875rem' }}>
            {statusFilter !== 'ALL'
              ? `No batches matching status "${statusFilter}".`
              : 'Pick lots from Intermediate Store to allot the first batch to Raj Kumar Ji.'}
          </p>
          {canAllot && (
            <Button type="button" variant="primary" onClick={onAllot} style={{ minHeight: '44px' }}>
              <Plus size={16} style={{ marginRight: '0.5rem' }} />
              Allot Batch Now
            </Button>
          )}
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          {batches.map((batch) => {
            const isPending = batch.status === 'ALLOTTED' || batch.status === 'PARTIALLY_RECEIVED';
            return (
              <div
                key={batch.id}
                style={{
                  backgroundColor: '#fff',
                  borderRadius: '8px',
                  padding: '1.25rem',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
                  border: isPending ? '1px solid #cbd5e1' : '1px solid #f1f5f9',
                  display: 'flex',
                  flexWrap: 'wrap',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: '1rem',
                }}
              >
                {/* Left info */}
                <div
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '0.375rem',
                    minWidth: '240px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <span style={{ fontSize: '1.125rem', fontWeight: 700, color: '#0f172a' }}>
                      {batch.batch_no}
                    </span>
                    <Badge
                      variant={
                        batch.status === 'COMPLETED'
                          ? 'success'
                          : batch.status === 'PARTIALLY_RECEIVED'
                            ? 'warning'
                            : batch.status === 'CANCELLED'
                              ? 'danger'
                              : 'info'
                      }
                    >
                      {batch.status}
                    </Badge>
                  </div>

                  <div
                    style={{
                      display: 'flex',
                      flexWrap: 'wrap',
                      gap: '1rem',
                      fontSize: '0.875rem',
                      color: '#475569',
                    }}
                  >
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
                      <User size={15} style={{ color: '#64748b' }} />
                      Technician: <strong>{batch.technician_name}</strong>
                    </span>

                    <span>
                      Entry: <strong>{batch.entry_by_name}</strong>
                    </span>

                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
                      <Clock
                        size={15}
                        style={{ color: batch.age_days > 2 ? '#dc2626' : '#64748b' }}
                      />
                      Age:{' '}
                      <strong>
                        {batch.age_days} {batch.age_days === 1 ? 'day' : 'days'}
                      </strong>
                    </span>
                  </div>
                </div>

                {/* Progress & counts */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem' }}>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: '0.75rem', color: '#64748b', fontWeight: 600 }}>
                      PROGRESS
                    </div>
                    <div style={{ fontSize: '1.125rem', fontWeight: 700, color: '#0f172a' }}>
                      {batch.total_qty_received} / {batch.total_qty_allotted} pcs
                    </div>
                    <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                      {batch.line_count} {batch.line_count === 1 ? 'line' : 'lines'}
                    </div>
                  </div>

                  {/* Action button */}
                  {isPending && (
                    <Button
                      type="button"
                      variant="primary"
                      onClick={() => {
                        onReceive(batch.id);
                      }}
                      style={{
                        minHeight: '44px',
                        minWidth: '120px',
                        display: 'inline-flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '0.5rem',
                        fontWeight: 600,
                      }}
                    >
                      <CheckCircle size={16} />
                      Receive
                    </Button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
