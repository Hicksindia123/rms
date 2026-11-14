import React, { useCallback } from 'react';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import { Button, ErrorState, LoadingState } from '@/components/ui';
import { StatusChip } from '@/features/goods-slips/display';
import { useApiQuery } from '@/hooks/useApiQuery';
import { InspectionSummary } from './InspectionSummary';
import { InspectionLineCard } from './InspectionLineCard';
import { HazardBanner } from './HazardBanner';
import { inspectionApi, newIdempotencyKey } from './api';
import type { InspectionGsOut, InspectionDraftIn } from './types';

interface InspectionPageProps {
  gsId: string;
  onBack: () => void;
}

export const InspectionPage: React.FC<InspectionPageProps> = ({ gsId, onBack }) => {
  const fetcher = useCallback(() => inspectionApi.getGsInspection(gsId), [gsId]);
  const query = useApiQuery<InspectionGsOut>(fetcher);
  const data = query.data?.gs_id === gsId ? query.data : null;

  const handleSaveDraft = async (lineId: string, payload: InspectionDraftIn) => {
    await inspectionApi.saveDraft(lineId, payload);
    query.reload();
  };

  const handleFinaliseLine = async (lineId: string) => {
    await inspectionApi.finaliseLine(lineId, newIdempotencyKey());
    query.reload();
  };

  const handleFinaliseAll = async () => {
    await inspectionApi.finaliseAll(gsId, newIdempotencyKey());
    query.reload();
  };

  const handleReopenLine = async (lineId: string, reason: string) => {
    await inspectionApi.reopenLine(lineId, reason);
    query.reload();
  };

  const back = (
    <Button type="button" variant="ghost" onClick={onBack}>
      <ArrowLeft size={16} aria-hidden="true" /> Goods slip
    </Button>
  );

  if (query.loading && !data) {
    return (
      <div className="page">
        {back}
        <LoadingState />
      </div>
    );
  }

  if (query.error && !data) {
    return (
      <div className="page">
        {back}
        <ErrorState error={query.error} onRetry={query.reload} />
      </div>
    );
  }

  if (!data) {
    return null;
  }

  const { totals, permissions, lines, has_hazard } = data;
  const canFinaliseAll =
    permissions.can_finalise &&
    totals.lines_count > 0 &&
    totals.lines_finalised < totals.lines_count;

  return (
    <div className="page" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Button type="button" variant="ghost" onClick={onBack}>
          <ArrowLeft size={16} aria-hidden="true" /> Goods slip {data.gs_no}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            query.reload();
          }}
        >
          <RefreshCw size={14} aria-hidden="true" /> Refresh
        </Button>
      </div>

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          flexWrap: 'wrap',
          gap: '1rem',
        }}
      >
        <div>
          <h1 className="page__title" style={{ margin: 0 }}>
            Visual Inspection & Extraction Reconciliation
          </h1>
          <div
            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.25rem' }}
          >
            <span style={{ fontWeight: 700, fontSize: '1.1rem' }}>{data.gs_no}</span>
            <StatusChip status={data.status} />
            {data.category_code && (
              <span
                style={{
                  fontWeight: 600,
                  fontSize: '0.75rem',
                  backgroundColor: '#e0f2fe',
                  color: '#0369a1',
                  padding: '2px 8px',
                  borderRadius: '12px',
                }}
              >
                Category: {data.category_code}
              </span>
            )}
          </div>
        </div>
      </div>

      {has_hazard && (
        <HazardBanner
          hazardQty={totals.total_hazard_qty}
          message="Mercury hazard has been identified and quarantined on this Goods Slip. Downstream movements are restricted to authorized safety flows."
        />
      )}

      <InspectionSummary
        totals={totals}
        status={data.status}
        hasHazard={has_hazard}
        canFinaliseAll={canFinaliseAll}
        onFinaliseAll={handleFinaliseAll}
      />

      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
        {lines.map((line) => (
          <InspectionLineCard
            key={`${line.gs_item_id}-${line.inspection_status}-${String(line.inspected_at)}`}
            line={line}
            canInspect={permissions.can_inspect}
            canFinalise={permissions.can_finalise}
            canReopen={permissions.can_reopen}
            onSaveDraft={handleSaveDraft}
            onFinaliseLine={handleFinaliseLine}
            onReopenLine={handleReopenLine}
          />
        ))}
      </div>
    </div>
  );
};
