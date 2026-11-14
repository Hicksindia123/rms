import React, { useState } from 'react';
import { Save, CheckCircle2, RotateCcw, AlertTriangle, ShieldAlert } from 'lucide-react';
import { Button } from '@/components/ui';
import { QuantityReconciliationMeter } from './QuantityReconciliationMeter';
import { HazardBanner } from './HazardBanner';
import { EnclosedOvalToggle } from './EnclosedOvalToggle';
import { ExtractionSection } from './ExtractionSection';
import { NotAllowedModal } from './NotAllowedModal';
import type {
  InspectionLineOut,
  ConditionOption,
  PrimaryExtractionType,
  InspectionDraftIn,
} from './types';

interface InspectionLineCardProps {
  line: InspectionLineOut;
  canInspect: boolean;
  canFinalise: boolean;
  canReopen: boolean;
  onSaveDraft: (lineId: string, payload: InspectionDraftIn) => Promise<void>;
  onFinaliseLine: (lineId: string) => Promise<void>;
  onReopenLine: (lineId: string, reason: string) => Promise<void>;
}

export const InspectionLineCard: React.FC<InspectionLineCardProps> = ({
  line,
  canInspect,
  canFinalise,
  canReopen,
  onSaveDraft,
  onFinaliseLine,
  onReopenLine,
}) => {
  const isEnclosedOval = line.requires_full_opening || line.category_code === 'ENCLOSED_OVAL';
  const isFinal = line.inspection_status === 'FINAL';

  // Local state for full opening confirmation
  const [fullOpeningConfirmed, setFullOpeningConfirmed] = useState<boolean>(
    line.full_opening_confirmed,
  );

  // Local state for condition allocations
  const [allocations, setAllocations] = useState<Record<string, number>>(() => {
    const map: Record<string, number> = {};
    for (const opt of line.condition_options) {
      map[opt.code] = 0;
    }
    for (const alloc of line.allocations) {
      map[alloc.condition_code] = alloc.qty;
    }
    return map;
  });

  // Local state for extraction
  const [primaryType, setPrimaryType] = useState<PrimaryExtractionType>(
    line.extraction?.primary_type ?? 'PACKAGING_EXTRACTED',
  );
  const [packagingQty, setPackagingQty] = useState<number>(
    line.extraction?.packaging_qty ?? line.received_qty,
  );
  const [containerQty, setContainerQty] = useState<number>(line.extraction?.container_qty ?? 0);

  // Warning modal state
  const [pendingOption, setPendingOption] = useState<ConditionOption | null>(null);
  const [pendingQty, setPendingQty] = useState<number>(0);

  // Reopen modal state
  const [reopenOpen, setReopenOpen] = useState(false);
  const [reopenReason, setReopenReason] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Calculate graded pieces (excluding DMT_SHORT_QTY / SHORT_QTY behavior)
  let totalGraded = 0;
  let shortQtyDiscrepancy = 0;
  let shortQtyRuleText: string | null = null;
  let hasMercuryHazard = false;
  let hazardQty = 0;

  for (const opt of line.condition_options) {
    const qty = allocations[opt.code] || 0;
    if (opt.code === 'DMT_SHORT_QTY' || opt.system_behavior === 'SHORT_QTY') {
      shortQtyDiscrepancy += qty;
      shortQtyRuleText = opt.rule_text;
    } else {
      totalGraded += qty;
    }

    if (
      opt.system_behavior === 'HAZARD' ||
      opt.code === 'PRS_BROKEN_WITH_HG' ||
      opt.code === 'EO_BODY_BROKEN_HG'
    ) {
      if (qty > 0) {
        hasMercuryHazard = true;
        hazardQty += qty;
      }
    }
  }

  const isConditionReconciled = totalGraded === line.received_qty;
  const isExtractionReconciled = packagingQty + containerQty === line.received_qty;
  const canFinaliseLineAction =
    canFinalise &&
    !isFinal &&
    isConditionReconciled &&
    isExtractionReconciled &&
    (!isEnclosedOval || fullOpeningConfirmed);

  const handleStepQty = (opt: ConditionOption, newQty: number) => {
    if (isFinal || !canInspect) return;
    if (isEnclosedOval && !fullOpeningConfirmed) return;

    const currentQty = allocations[opt.code] || 0;
    // If increasing and option is not allowed (NO / CONDITIONAL) and going from 0 to >0, warn
    if (
      newQty > currentQty &&
      currentQty === 0 &&
      (opt.allowed_status === 'NO' || opt.allowed_status === 'CONDITIONAL')
    ) {
      setPendingOption(opt);
      setPendingQty(newQty);
      return;
    }

    setAllocations((prev) => ({ ...prev, [opt.code]: Math.max(0, newQty) }));
  };

  const handleToggleFullOpening = (confirmed: boolean) => {
    setFullOpeningConfirmed(confirmed);
    if (!confirmed) {
      // Disabling or unchecking clears/blocks EO conditions (G-06, BR-14)
      const cleared: Record<string, number> = {};
      for (const opt of line.condition_options) {
        cleared[opt.code] = 0;
      }
      setAllocations(cleared);
    }
  };

  const buildPayload = (): InspectionDraftIn => {
    const allocList = line.condition_options
      .map((opt) => ({
        condition_code: opt.code,
        qty: allocations[opt.code] || 0,
      }))
      .filter((a) => a.qty > 0);

    return {
      full_opening_confirmed: fullOpeningConfirmed,
      allocations: allocList,
      extraction: {
        primary_type: primaryType,
        packaging_qty: packagingQty,
        container_qty: containerQty,
      },
    };
  };

  const handleSave = async () => {
    setSubmitting(true);
    try {
      await onSaveDraft(line.gs_item_id, buildPayload());
    } finally {
      setSubmitting(false);
    }
  };

  const handleFinalise = async () => {
    setSubmitting(true);
    try {
      // Save draft first then finalise
      await onSaveDraft(line.gs_item_id, buildPayload());
      await onFinaliseLine(line.gs_item_id);
    } finally {
      setSubmitting(false);
    }
  };

  const handleConfirmReopen = async () => {
    if (!reopenReason.trim()) return;
    setSubmitting(true);
    try {
      await onReopenLine(line.gs_item_id, reopenReason.trim());
      setReopenOpen(false);
      setReopenReason('');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="card"
      data-testid="inspection-line"
      data-line-no={line.line_no}
      style={{
        padding: '1.25rem',
        display: 'flex',
        flexDirection: 'column',
        gap: '1rem',
        borderLeft: isFinal
          ? '4px solid var(--color-success, #16a34a)'
          : hasMercuryHazard
            ? '4px solid #ef4444'
            : '4px solid var(--color-primary, #2563eb)',
      }}
    >
      {/* Line Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          flexWrap: 'wrap',
          gap: '0.75rem',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
            <span
              style={{
                fontWeight: 700,
                fontSize: '0.85rem',
                backgroundColor: 'var(--color-bg-secondary, #e2e8f0)',
                padding: '2px 8px',
                borderRadius: '4px',
              }}
            >
              Line {line.line_no}
            </span>
            <span
              style={{
                fontWeight: 700,
                fontSize: '0.75rem',
                backgroundColor: '#e0f2fe',
                color: '#0369a1',
                padding: '2px 8px',
                borderRadius: '12px',
                border: '1px solid #bae6fd',
              }}
            >
              {line.category_code}
            </span>
            <span style={{ fontWeight: 700, fontSize: '1rem' }}>
              {line.product_code} — {line.product_name}
            </span>
          </div>

          <div
            style={{
              display: 'flex',
              gap: '1rem',
              marginTop: '0.25rem',
              fontSize: '0.85rem',
              color: 'var(--color-muted, #64748b)',
            }}
          >
            <span>
              Documented: <strong>{line.documented_qty}</strong>
            </span>
            <span>
              Received: <strong>{line.received_qty}</strong>
            </span>
            {line.short_qty > 0 && (
              <span style={{ color: '#d97706', fontWeight: 600 }}>Short: {line.short_qty}</span>
            )}
            {line.excess_qty > 0 && (
              <span style={{ color: '#2563eb', fontWeight: 600 }}>Excess: +{line.excess_qty}</span>
            )}
          </div>
        </div>

        {/* Status Chip */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          {isFinal ? (
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.35rem',
                padding: '3px 10px',
                borderRadius: '16px',
                backgroundColor: '#dcfce7',
                color: '#15803d',
                fontWeight: 700,
                fontSize: '0.8rem',
              }}
            >
              <CheckCircle2 size={14} aria-hidden="true" /> Finalised
            </span>
          ) : (
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                padding: '3px 10px',
                borderRadius: '16px',
                backgroundColor: '#fef3c7',
                color: '#b45309',
                fontWeight: 700,
                fontSize: '0.8rem',
              }}
            >
              {line.inspection_status || 'Draft'}
            </span>
          )}
          {line.reopened_at && (
            <span
              style={{
                padding: '3px 8px',
                borderRadius: '16px',
                backgroundColor: '#f1f5f9',
                color: '#475569',
                fontSize: '0.75rem',
              }}
              title={line.reopen_reason || 'Reopened by RM'}
            >
              Reopened
            </span>
          )}
        </div>
      </div>

      {/* Hazard Banner if any mercury hazard is selected */}
      {hasMercuryHazard && <HazardBanner hazardQty={hazardQty} />}

      {/* Enclosed Oval protocol lock */}
      {isEnclosedOval && (
        <EnclosedOvalToggle
          idPrefix={`line-${line.gs_item_id}`}
          confirmed={fullOpeningConfirmed}
          disabled={isFinal || !canInspect}
          onChange={handleToggleFullOpening}
        />
      )}

      {/* Condition allocations grid */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#334155' }}>
          Product Condition Grading (
          {line.category_code === 'DMT'
            ? '8 Conditions'
            : line.category_code === 'PRISMATIC'
              ? '3 Conditions'
              : '4 Conditions'}
          ):
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
            gap: '0.75rem',
          }}
        >
          {line.condition_options.map((opt) => {
            const isShortDiscrepancy =
              opt.code === 'DMT_SHORT_QTY' || opt.system_behavior === 'SHORT_QTY';
            const isHazard =
              opt.system_behavior === 'HAZARD' ||
              opt.code === 'PRS_BROKEN_WITH_HG' ||
              opt.code === 'EO_BODY_BROKEN_HG';
            const isLocked = isEnclosedOval && !fullOpeningConfirmed;
            const currentQty = allocations[opt.code] || 0;

            return (
              <div
                key={opt.code}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '0.625rem 0.875rem',
                  borderRadius: '6px',
                  backgroundColor: isHazard
                    ? '#fff1f2'
                    : isShortDiscrepancy
                      ? '#f8fafc'
                      : '#ffffff',
                  border: isHazard
                    ? '1px solid #fecdd3'
                    : isShortDiscrepancy
                      ? '1px dashed #cbd5e1'
                      : '1px solid #e2e8f0',
                  opacity: isLocked ? 0.6 : 1,
                }}
              >
                <div style={{ display: 'flex', flexDirection: 'column', maxWidth: '65%' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                    <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>{opt.label}</span>
                    {isHazard && <ShieldAlert size={14} color="#e11d48" aria-hidden="true" />}
                  </div>
                  {opt.rule_text && (
                    <span style={{ fontSize: '0.75rem', color: '#64748b' }}>{opt.rule_text}</span>
                  )}
                  {opt.allowed_status !== 'YES' && (
                    <span
                      style={{
                        fontSize: '0.7rem',
                        fontWeight: 600,
                        color: opt.allowed_status === 'NO' ? '#dc2626' : '#d97706',
                      }}
                    >
                      {opt.allowed_status === 'NO' ? 'Not Allowed (Segregated)' : 'Conditional'}
                    </span>
                  )}
                </div>

                {/* Stepper */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={isFinal || !canInspect || isLocked || currentQty <= 0}
                    onClick={() => {
                      handleStepQty(opt, currentQty - 1);
                    }}
                    aria-label={`Decrease ${opt.label}`}
                    style={{ padding: '2px 8px', minWidth: '44px', height: '44px' }}
                  >
                    -
                  </Button>
                  <input
                    type="number"
                    min={0}
                    value={currentQty}
                    aria-label={`${opt.label} quantity`}
                    disabled={isFinal || !canInspect || isLocked}
                    onChange={(e) => {
                      handleStepQty(opt, Math.max(0, parseInt(e.target.value, 10) || 0));
                    }}
                    style={{
                      width: '48px',
                      height: '44px',
                      textAlign: 'center',
                      padding: '2px 4px',
                      fontSize: '0.85rem',
                      fontWeight: 600,
                      borderRadius: '4px',
                      border: '1px solid #cbd5e1',
                    }}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    disabled={isFinal || !canInspect || isLocked}
                    onClick={() => {
                      handleStepQty(opt, currentQty + 1);
                    }}
                    aria-label={`Increase ${opt.label}`}
                    style={{ padding: '2px 8px', minWidth: '44px', height: '44px' }}
                  >
                    +
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Quantity Reconciliation Meter */}
      <QuantityReconciliationMeter
        receivedQty={line.received_qty}
        gradedQty={totalGraded}
        shortQtyDiscrepancy={shortQtyDiscrepancy}
        shortQtyRuleText={shortQtyRuleText}
      />

      {/* Extraction Section */}
      <ExtractionSection
        idPrefix={`line-${line.gs_item_id}`}
        primaryType={primaryType}
        packagingQty={packagingQty}
        containerQty={containerQty}
        targetQty={line.received_qty}
        disabled={isFinal || !canInspect}
        onPrimaryTypeChange={setPrimaryType}
        onPackagingQtyChange={setPackagingQty}
        onContainerQtyChange={setContainerQty}
      />

      {/* Rejections list (if finalised and rejections were recorded) */}
      {line.rejections.length > 0 && (
        <div
          style={{
            padding: '0.75rem 1rem',
            borderRadius: '6px',
            backgroundColor: '#fef2f2',
            border: '1px solid #fecaca',
            fontSize: '0.85rem',
          }}
        >
          <div style={{ fontWeight: 700, color: '#991b1b', marginBottom: '0.25rem' }}>
            Rejections & Segregated Lots Recorded:
          </div>
          <ul style={{ margin: 0, paddingLeft: '1.25rem' }}>
            {line.rejections.map((rej) => (
              <li key={rej.id}>
                <strong>{rej.qty} pcs</strong> — {rej.condition_code} &rarr;{' '}
                <span style={{ fontWeight: 600 }}>{rej.disposition}</span>{' '}
                {rej.hazard && (
                  <span style={{ color: '#dc2626', fontWeight: 700 }}>(MERCURY HAZARD)</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Action Footer */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '0.5rem',
          paddingTop: '0.5rem',
          borderTop: '1px solid #e2e8f0',
        }}
      >
        <div style={{ fontSize: '0.8rem', color: '#64748b' }}>
          {line.inspected_by_name && <span>Inspected by {line.inspected_by_name}</span>}
        </div>

        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          {!isFinal && canInspect && (
            <>
              <Button
                type="button"
                variant="outline"
                disabled={submitting}
                onClick={() => {
                  void handleSave();
                }}
              >
                <Save size={16} aria-hidden="true" /> Save Draft
              </Button>
              <Button
                type="button"
                variant="primary"
                disabled={submitting || !canFinaliseLineAction}
                onClick={() => {
                  void handleFinalise();
                }}
                title={
                  !isConditionReconciled
                    ? 'Condition graded pieces must equal received qty'
                    : !isExtractionReconciled
                      ? 'Extraction packaging + container must equal received qty'
                      : undefined
                }
              >
                <CheckCircle2 size={16} aria-hidden="true" /> Finalise Line
              </Button>
            </>
          )}

          {isFinal && canReopen && (
            <Button
              type="button"
              variant="outline"
              disabled={submitting}
              onClick={() => {
                setReopenOpen(true);
              }}
            >
              <RotateCcw size={16} aria-hidden="true" /> Reopen Inspection
            </Button>
          )}
        </div>
      </div>

      {/* Not Allowed Modal */}
      <NotAllowedModal
        isOpen={Boolean(pendingOption)}
        option={pendingOption}
        onConfirm={() => {
          if (pendingOption) {
            setAllocations((prev) => ({ ...prev, [pendingOption.code]: pendingQty }));
          }
          setPendingOption(null);
        }}
        onCancel={() => {
          setPendingOption(null);
        }}
      />

      {/* Reopen Inspection Modal */}
      {reopenOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="reopen-title"
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '1rem',
          }}
        >
          <div
            style={{
              backgroundColor: '#ffffff',
              borderRadius: '8px',
              maxWidth: '460px',
              width: '100%',
              padding: '1.5rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '1rem',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <AlertTriangle size={22} color="#d97706" aria-hidden="true" />
              <h3 id="reopen-title" style={{ margin: 0, fontSize: '1.1rem', fontWeight: 700 }}>
                Reopen Inspection for Line {line.line_no}
              </h3>
            </div>

            <p style={{ margin: 0, fontSize: '0.85rem', color: '#4b5563', lineHeight: 1.4 }}>
              Reopening this line will cancel its finalised status, reverse segregated stock
              movements with compensating ledger entries, and reopen the inspection task for the
              verifier.
            </p>

            <div>
              <label
                htmlFor="reopen-reason-input"
                style={{
                  display: 'block',
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  marginBottom: '0.25rem',
                }}
              >
                Reopen Reason (Mandatory):
              </label>
              <textarea
                id="reopen-reason-input"
                rows={3}
                value={reopenReason}
                onChange={(e) => {
                  setReopenReason(e.target.value);
                }}
                placeholder="Reason for reopening inspection..."
                style={{
                  width: '100%',
                  padding: '0.5rem',
                  fontSize: '0.85rem',
                  borderRadius: '4px',
                  border: '1px solid #cbd5e1',
                }}
              />
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setReopenOpen(false);
                }}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="danger"
                disabled={!reopenReason.trim() || submitting}
                onClick={() => {
                  void handleConfirmReopen();
                }}
              >
                Reopen Line
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
