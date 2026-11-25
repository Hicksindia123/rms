import React from 'react';
import { CheckCircle2, AlertCircle, Package } from 'lucide-react';
import type { PrimaryExtractionType } from './types';

interface ExtractionSectionProps {
  /** Unique per line card: element ids and the radio group name must not collide. */
  idPrefix: string;
  primaryType: PrimaryExtractionType;
  packagingQty: number;
  containerQty: number;
  targetQty: number;
  disabled?: boolean;
  onPrimaryTypeChange: (type: PrimaryExtractionType) => void;
  onPackagingQtyChange: (qty: number) => void;
  onContainerQtyChange: (qty: number) => void;
}

export const ExtractionSection: React.FC<ExtractionSectionProps> = ({
  idPrefix,
  primaryType,
  packagingQty,
  containerQty,
  targetQty,
  disabled = false,
  onPrimaryTypeChange,
  onPackagingQtyChange,
  onContainerQtyChange,
}) => {
  const sum = packagingQty + containerQty;
  const isReconciled = sum === targetQty;
  const diff = sum - targetQty;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '0.75rem',
        padding: '0.875rem 1rem',
        borderRadius: '6px',
        backgroundColor: 'var(--color-bg-secondary, #f8fafc)',
        border: '1px solid var(--color-border, #e2e8f0)',
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
          <Package size={18} color="var(--color-primary, #2a47f0)" aria-hidden="true" />
          <span style={{ fontWeight: 600, fontSize: '0.875rem' }}>Extraction Reconciliation</span>
          <span
            style={{
              fontSize: '0.75rem',
              color: 'var(--color-muted, #64748b)',
              marginLeft: '0.25rem',
            }}
          >
            (Target: {targetQty} pieces)
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
          {isReconciled ? (
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.25rem',
                fontSize: '0.75rem',
                fontWeight: 600,
                color: '#16a34a',
                backgroundColor: '#f0fdf4',
                padding: '2px 8px',
                borderRadius: '12px',
                border: '1px solid #86efac',
              }}
            >
              <CheckCircle2 size={14} aria-hidden="true" />
              Reconciled ({sum}/{targetQty})
            </span>
          ) : (
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.25rem',
                fontSize: '0.75rem',
                fontWeight: 600,
                color: diff < 0 ? '#d97706' : '#dc2626',
                backgroundColor: diff < 0 ? '#fffbeb' : '#fef2f2',
                padding: '2px 8px',
                borderRadius: '12px',
                border: `1px solid ${diff < 0 ? '#fcd34d' : '#fca5a5'}`,
              }}
            >
              <AlertCircle size={14} aria-hidden="true" />
              {diff < 0 ? `${String(Math.abs(diff))} remaining` : `+${String(diff)} over target`} (
              {String(sum)}/{String(targetQty)})
            </span>
          )}
        </div>
      </div>

      {/* Primary extraction radio */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
        <span
          style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--color-muted, #4b5563)' }}
        >
          Primary Extraction Method (Mandatory):
        </span>
        <div style={{ display: 'flex', gap: '1.5rem', alignItems: 'center' }}>
          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.35rem',
              fontSize: '0.85rem',
              cursor: disabled ? 'not-allowed' : 'pointer',
            }}
          >
            <input
              type="radio"
              name={`${idPrefix}-primary-ext`}
              value="PACKAGING_EXTRACTED"
              checked={primaryType === 'PACKAGING_EXTRACTED'}
              disabled={disabled}
              onChange={() => {
                onPrimaryTypeChange('PACKAGING_EXTRACTED');
              }}
            />
            <span>Packaging Extracted</span>
          </label>

          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.35rem',
              fontSize: '0.85rem',
              cursor: disabled ? 'not-allowed' : 'pointer',
            }}
          >
            <input
              type="radio"
              name={`${idPrefix}-primary-ext`}
              value="CONTAINER_EXTRACTED"
              checked={primaryType === 'CONTAINER_EXTRACTED'}
              disabled={disabled}
              onChange={() => {
                onPrimaryTypeChange('CONTAINER_EXTRACTED');
              }}
            />
            <span>Container Extracted</span>
          </label>
        </div>
      </div>

      {/* Inputs */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: '1rem',
          marginTop: '0.25rem',
        }}
      >
        <div>
          <label
            htmlFor={`${idPrefix}-packaging-qty`}
            style={{
              display: 'block',
              fontSize: '0.75rem',
              fontWeight: 600,
              marginBottom: '0.25rem',
            }}
          >
            Packaging Qty (pieces)
          </label>
          <input
            id={`${idPrefix}-packaging-qty`}
            type="number"
            min={0}
            value={packagingQty}
            disabled={disabled}
            onChange={(e) => {
              onPackagingQtyChange(Math.max(0, parseInt(e.target.value, 10) || 0));
            }}
            style={{
              width: '100%',
              padding: '0.375rem 0.625rem',
              fontSize: '0.875rem',
              borderRadius: '4px',
              border: '1px solid var(--color-border, #cbd5e1)',
            }}
          />
        </div>

        <div>
          <label
            htmlFor={`${idPrefix}-container-qty`}
            style={{
              display: 'block',
              fontSize: '0.75rem',
              fontWeight: 600,
              marginBottom: '0.25rem',
            }}
          >
            Container Qty (pieces)
          </label>
          <input
            id={`${idPrefix}-container-qty`}
            type="number"
            min={0}
            value={containerQty}
            disabled={disabled}
            onChange={(e) => {
              onContainerQtyChange(Math.max(0, parseInt(e.target.value, 10) || 0));
            }}
            style={{
              width: '100%',
              padding: '0.375rem 0.625rem',
              fontSize: '0.875rem',
              borderRadius: '4px',
              border: '1px solid var(--color-border, #cbd5e1)',
            }}
          />
        </div>
      </div>
    </div>
  );
};
