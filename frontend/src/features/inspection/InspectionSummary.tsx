import React from 'react';
import { CheckCheck, AlertOctagon, CheckCircle2 } from 'lucide-react';
import { Button } from '@/components/ui';
import type { InspectionTotals } from './types';

interface InspectionSummaryProps {
  totals: InspectionTotals;
  status: string;
  hasHazard: boolean;
  canFinaliseAll: boolean;
  onFinaliseAll: () => Promise<void>;
}

export const InspectionSummary: React.FC<InspectionSummaryProps> = ({
  totals,
  status,
  hasHazard,
  canFinaliseAll,
  onFinaliseAll,
}) => {
  const isGsFinalised = totals.lines_count > 0 && totals.lines_finalised === totals.lines_count;

  return (
    <div
      className="card"
      style={{
        padding: '1rem 1.25rem',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: '1rem',
        backgroundColor: '#ffffff',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem', flexWrap: 'wrap' }}>
        <div>
          <span style={{ fontSize: '0.75rem', color: '#64748b', display: 'block' }}>Progress</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
            <span style={{ fontWeight: 800, fontSize: '1.1rem' }}>
              {totals.lines_finalised} / {totals.lines_count}
            </span>
            <span style={{ fontSize: '0.8rem', color: '#64748b' }}>lines finalised</span>
          </div>
        </div>

        <div>
          <span style={{ fontSize: '0.75rem', color: '#64748b', display: 'block' }}>
            Pieces Graded
          </span>
          <span style={{ fontWeight: 800, fontSize: '1.1rem' }}>
            {totals.total_graded_qty} / {totals.total_received_qty}
          </span>
        </div>

        {totals.total_rejected_qty > 0 && (
          <div>
            <span style={{ fontSize: '0.75rem', color: '#b91c1c', display: 'block' }}>
              Rejections
            </span>
            <span style={{ fontWeight: 800, fontSize: '1.1rem', color: '#dc2626' }}>
              {totals.total_rejected_qty} pcs
            </span>
          </div>
        )}

        {hasHazard && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', color: '#dc2626' }}>
            <AlertOctagon size={18} aria-hidden="true" />
            <span style={{ fontWeight: 700, fontSize: '0.85rem' }}>
              Hazard Quarantined ({totals.total_hazard_qty} pcs)
            </span>
          </div>
        )}
      </div>

      <div>
        {isGsFinalised ? (
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.35rem',
              color: '#15803d',
              fontWeight: 700,
              fontSize: '0.9rem',
            }}
          >
            <CheckCircle2 size={18} aria-hidden="true" /> All Lines Finalised &bull; {status}
          </div>
        ) : (
          <Button
            type="button"
            variant="primary"
            disabled={!canFinaliseAll}
            onClick={() => {
              void onFinaliseAll();
            }}
          >
            <CheckCheck size={16} aria-hidden="true" /> Finalise All Lines
          </Button>
        )}
      </div>
    </div>
  );
};
