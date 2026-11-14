import React from 'react';
import { CheckCircle2, AlertTriangle, AlertCircle, Info } from 'lucide-react';

interface QuantityReconciliationMeterProps {
  receivedQty: number;
  gradedQty: number;
  shortQtyDiscrepancy?: number;
  shortQtyRuleText?: string | null;
}

export const QuantityReconciliationMeter: React.FC<QuantityReconciliationMeterProps> = ({
  receivedQty,
  gradedQty,
  shortQtyDiscrepancy = 0,
  shortQtyRuleText,
}) => {
  const diff = gradedQty - receivedQty;
  const isMatch = diff === 0;
  const isUnder = diff < 0;
  const isOver = diff > 0;

  const statusColor = isMatch
    ? 'var(--color-success, #16a34a)'
    : isUnder
      ? 'var(--color-warning, #d97706)'
      : 'var(--color-danger, #dc2626)';

  const statusBg = isMatch
    ? 'rgba(22, 163, 74, 0.1)'
    : isUnder
      ? 'rgba(217, 119, 6, 0.1)'
      : 'rgba(220, 38, 38, 0.1)';

  const percentage =
    receivedQty > 0 ? Math.min(100, Math.round((gradedQty / receivedQty) * 100)) : 0;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '0.5rem',
        padding: '0.75rem 1rem',
        borderRadius: '6px',
        backgroundColor: statusBg,
        border: `1px solid ${statusColor}`,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '0.5rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          {isMatch && <CheckCircle2 size={18} color={statusColor} aria-hidden="true" />}
          {isUnder && <AlertTriangle size={18} color={statusColor} aria-hidden="true" />}
          {isOver && <AlertCircle size={18} color={statusColor} aria-hidden="true" />}
          <span style={{ fontWeight: 600, fontSize: '0.875rem', color: statusColor }}>
            {isMatch
              ? `Reconciled: ${String(gradedQty)} / ${String(receivedQty)} pieces graded`
              : isUnder
                ? `Under-allocated: ${String(gradedQty)} / ${String(receivedQty)} (${String(Math.abs(diff))} remaining)`
                : `Over-allocated: ${String(gradedQty)} / ${String(receivedQty)} (+${String(diff)} pieces over)`}
          </span>
        </div>
        <div style={{ fontSize: '0.75rem', fontWeight: 600, color: statusColor }}>
          {String(percentage)}% allocated
        </div>
      </div>

      {/* Progress bar visual */}
      <div
        style={{
          width: '100%',
          height: '6px',
          backgroundColor: 'rgba(0, 0, 0, 0.08)',
          borderRadius: '3px',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${String(Math.min(100, (gradedQty / Math.max(1, receivedQty)) * 100))}%`,
            height: '100%',
            backgroundColor: statusColor,
            transition: 'width 0.2s ease',
          }}
        />
      </div>

      {shortQtyDiscrepancy > 0 && (
        <div
          style={{
            marginTop: '0.25rem',
            paddingTop: '0.5rem',
            borderTop: '1px dashed rgba(0, 0, 0, 0.15)',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            fontSize: '0.75rem',
            color: 'var(--color-muted, #4b5563)',
          }}
        >
          <Info size={14} color="var(--color-primary, #2563eb)" aria-hidden="true" />
          <span>
            <strong>Documented Shortage:</strong> {shortQtyDiscrepancy} pcs noted.{' '}
            {shortQtyRuleText ||
              'Documented shortage; does not count against physical received pieces.'}
          </span>
        </div>
      )}
    </div>
  );
};
