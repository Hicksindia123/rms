import { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  FileCheck2,
  Info,
  Package,
  Send,
  XCircle,
} from 'lucide-react';

import { Badge, Button, ErrorState, LoadingState } from '@/components/ui';
import { toApiError } from '@/lib/api/client';

import { creditNotesApi } from './api';
import type { RmCnDecisionPrefill, RmCnDecisionPrefillLine } from './types';

interface Props {
  gsId: string;
  onBack: () => void;
  onSubmitted?: () => void;
}

interface ItemDecisionState {
  gs_item_id: string;
  item_name: string;
  sku: string;
  received_qty: number;
  planned_action_code: string;
  planned_action_name: string;
  planned_action_qty: number;
  decision: 'ALLOW_CN' | 'DENY_CN_SEND_REPLACEMENT';
  qty: number;
}

export function RmCnDecisionPage({ gsId, onBack, onSubmitted }: Props) {
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [prefill, setPrefill] = useState<RmCnDecisionPrefill | null>(null);
  const [lines, setLines] = useState<ItemDecisionState[]>([]);
  const [deviationReason, setDeviationReason] = useState('');

  // Reset to the loading state when the Goods Slip changes (state adjusted during render,
  // not synchronously inside the effect).
  const [loadedGsId, setLoadedGsId] = useState(gsId);
  if (loadedGsId !== gsId) {
    setLoadedGsId(gsId);
    setLoading(true);
    setError(null);
  }

  const fetchData = useCallback(
    () =>
      creditNotesApi.getCnDecisionPrefill(gsId).then(
        (data) => {
          setPrefill(data);
          setLines(
            data.prefill_lines.map((l: RmCnDecisionPrefillLine) => ({
              gs_item_id: l.gs_item_id,
              item_name: l.product_name,
              sku: l.product_code,
              received_qty: l.received_qty,
              planned_action_code: l.planned_action_code,
              planned_action_name: l.planned_action_label,
              planned_action_qty: l.planned_qty,
              decision: l.default_decision_code,
              // DEC-13: one row per planned commercial outcome; default to the planned quantity.
              qty: l.planned_qty > 0 ? l.planned_qty : l.received_qty,
            })),
          );
          setLoading(false);
        },
        (err: unknown) => {
          const e = toApiError(err);
          setError(e.message);
          setLoading(false);
        },
      ),
    [gsId],
  );

  const loadData = () => {
    setLoading(true);
    setError(null);
    void fetchData();
  };

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  if (loading) {
    return <LoadingState label="Loading RM CN Decision form..." />;
  }

  if (error && !prefill) {
    return (
      <ErrorState
        title="Failed to load CN decision prefill"
        error={{ message: error }}
        onRetry={loadData}
      />
    );
  }

  if (!prefill) {
    return null;
  }

  // Check if there is any deviation from the planned action
  // ISSUE_CN -> ALLOW_CN; SEND_* -> DENY_CN_SEND_REPLACEMENT
  const hasDeviation = lines.some((line) => {
    const plannedDecision =
      line.planned_action_code === 'ISSUE_CN' ? 'ALLOW_CN' : 'DENY_CN_SEND_REPLACEMENT';
    return line.decision !== plannedDecision || line.qty !== line.planned_action_qty;
  });

  const handleDecisionToggle = (
    index: number,
    decision: 'ALLOW_CN' | 'DENY_CN_SEND_REPLACEMENT',
  ) => {
    setLines((prev) => {
      const copy = [...prev];
      const current = copy[index];
      if (!current) return prev;
      copy[index] = { ...current, decision };
      return copy;
    });
  };

  const handleQtyChange = (index: number, val: number) => {
    setLines((prev) => {
      const copy = [...prev];
      const current = copy[index];
      if (!current) return prev;
      const maxQty = current.received_qty;
      const validQty = Math.max(1, Math.min(val, maxQty));
      copy[index] = { ...current, qty: validQty };
      return copy;
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccessMsg(null);

    if (hasDeviation && !deviationReason.trim()) {
      setError(
        'A deviation reason is mandatory when diverging from the planned RM action (DEC-13).',
      );
      return;
    }

    setSubmitting(true);
    try {
      const payload = {
        lines: lines.map((l) => ({
          gs_item_id: l.gs_item_id,
          qty: l.qty,
          decision: l.decision,
        })),
        deviation_reason: hasDeviation ? deviationReason.trim() : null,
      };

      await creditNotesApi.recordCnDecision(gsId, payload);
      setSuccessMsg('Step-7 RM Credit Note decision recorded successfully.');
      if (onSubmitted) {
        setTimeout(onSubmitted, 1200);
      }
    } catch (err) {
      const e = toApiError(err);
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto p-4 md:p-6 space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b pb-4">
        <div className="flex items-center gap-3">
          <Button variant="outline" size="sm" onClick={onBack} className="gap-2">
            <ArrowLeft className="w-4 h-4" />
            Back
          </Button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground">
                Step-7: RM Credit Note Decision
              </h1>
              <Badge variant="neutral" className="font-mono text-xs">
                {prefill.gs_no}
              </Badge>
              {prefill.is_csr && (
                <Badge variant="warning" className="text-xs">
                  CSR Goods Slip
                </Badge>
              )}
            </div>
            <p className="text-xs sm:text-sm text-muted-foreground mt-0.5">
              Party: <span className="font-medium text-foreground">{prefill.party_name}</span> •
              Finalize commercial resolution per line
            </p>
          </div>
        </div>
      </div>

      {/* CSR Notice */}
      {prefill.is_csr && (
        <div className="p-3.5 rounded-lg border border-sky-200 bg-sky-50 dark:bg-sky-950/20 dark:border-sky-800 text-sky-900 dark:text-sky-300 flex items-start gap-3">
          <Info className="w-5 h-5 text-sky-600 mt-0.5 shrink-0" />
          <div className="text-xs sm:text-sm space-y-1">
            <div className="font-semibold">CSR Goods Slip Resolution</div>
            <p>
              Under CSR policies, commercial Credit Note decisions apply to intact cartons. Default
              resolution is ALLOW_CN.
            </p>
          </div>
        </div>
      )}

      {/* Messages */}
      {error && (
        <div className="p-3.5 rounded-lg border border-red-200 bg-red-50 text-red-800 dark:bg-red-950/20 dark:border-red-800 dark:text-red-300 flex items-start gap-2 text-sm">
          <XCircle className="w-4 h-4 mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {successMsg && (
        <div className="p-3.5 rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-800 dark:bg-emerald-950/20 dark:border-emerald-800 dark:text-emerald-300 flex items-start gap-2 text-sm">
          <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" />
          <span>{successMsg}</span>
        </div>
      )}

      <form onSubmit={(e) => void handleSubmit(e)} className="space-y-6">
        {/* Item Cards */}
        <div className="space-y-4">
          <div className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
            Line Items Decision
          </div>

          {lines.map((line, idx) => {
            const isPlannedAllow = line.planned_action_code === 'ISSUE_CN';
            const isCurrentAllow = line.decision === 'ALLOW_CN';
            const isLineDivergent =
              (isPlannedAllow && !isCurrentAllow) ||
              (!isPlannedAllow && isCurrentAllow) ||
              line.qty !== line.planned_action_qty;

            return (
              <div
                key={`${line.gs_item_id}-${line.planned_action_code}`}
                className={`p-4 rounded-xl border transition-all ${
                  isLineDivergent
                    ? 'border-amber-300 bg-amber-50/30 dark:border-amber-700/50 dark:bg-amber-950/10'
                    : 'border-border bg-card'
                } shadow-sm space-y-4`}
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div>
                    <div className="font-semibold text-base text-foreground flex items-center gap-2">
                      <Package className="w-4 h-4 text-primary" />
                      {line.item_name}
                    </div>
                    <div className="text-xs text-muted-foreground font-mono">
                      SKU: {line.sku || 'N/A'} • Received: {line.received_qty} pcs
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">Planned Action:</span>
                    <Badge variant="neutral" className="text-xs font-medium">
                      {line.planned_action_name || line.planned_action_code} (
                      {line.planned_action_qty} pcs)
                    </Badge>
                  </div>
                </div>

                {/* Decision Toggle */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
                  <button
                    type="button"
                    onClick={() => {
                      handleDecisionToggle(idx, 'ALLOW_CN');
                    }}
                    className={`flex items-center justify-between p-3 rounded-lg border text-left transition-all ${
                      line.decision === 'ALLOW_CN'
                        ? 'border-emerald-500 bg-emerald-50 text-emerald-950 ring-2 ring-emerald-400 dark:bg-emerald-950/30 dark:text-emerald-100'
                        : 'border-border bg-background hover:bg-muted text-foreground'
                    }`}
                  >
                    <div className="flex items-center gap-2.5">
                      <FileCheck2
                        className={`w-5 h-5 ${
                          line.decision === 'ALLOW_CN'
                            ? 'text-emerald-600'
                            : 'text-muted-foreground'
                        }`}
                      />
                      <div>
                        <div className="font-semibold text-sm">Allow Credit Note</div>
                        <div className="text-xs text-muted-foreground">
                          Commercial credit note authorized
                        </div>
                      </div>
                    </div>
                    {line.decision === 'ALLOW_CN' && (
                      <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                    )}
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      handleDecisionToggle(idx, 'DENY_CN_SEND_REPLACEMENT');
                    }}
                    className={`flex items-center justify-between p-3 rounded-lg border text-left transition-all ${
                      line.decision === 'DENY_CN_SEND_REPLACEMENT'
                        ? 'border-indigo-500 bg-indigo-50 text-indigo-950 ring-2 ring-indigo-400 dark:bg-indigo-950/30 dark:text-indigo-100'
                        : 'border-border bg-background hover:bg-muted text-foreground'
                    }`}
                  >
                    <div className="flex items-center gap-2.5">
                      <Send
                        className={`w-5 h-5 ${
                          line.decision === 'DENY_CN_SEND_REPLACEMENT'
                            ? 'text-indigo-600'
                            : 'text-muted-foreground'
                        }`}
                      />
                      <div>
                        <div className="font-semibold text-sm">Send Replacement</div>
                        <div className="text-xs text-muted-foreground">
                          Deny CN, fulfill via dispatch
                        </div>
                      </div>
                    </div>
                    {line.decision === 'DENY_CN_SEND_REPLACEMENT' && (
                      <CheckCircle2 className="w-4 h-4 text-indigo-600" />
                    )}
                  </button>
                </div>

                {/* Quantity Allocation */}
                <div className="flex items-center justify-between pt-2 border-t text-sm">
                  <label
                    htmlFor={`qty-${line.gs_item_id}-${line.planned_action_code}`}
                    className="text-xs font-medium text-muted-foreground"
                  >
                    Authorized Quantity:
                  </label>
                  <div className="flex items-center gap-2">
                    <input
                      id={`qty-${line.gs_item_id}-${line.planned_action_code}`}
                      type="number"
                      min={1}
                      max={line.received_qty}
                      value={line.qty}
                      onChange={(e) => {
                        handleQtyChange(idx, parseInt(e.target.value, 10) || 1);
                      }}
                      className="w-20 px-2 py-1 text-right font-mono text-sm border rounded bg-background text-foreground"
                    />
                    <span className="text-xs text-muted-foreground">/ {line.received_qty} pcs</span>
                  </div>
                </div>

                {/* Individual Line Divergence Warning */}
                {isLineDivergent && (
                  <div className="flex items-center gap-2 text-xs text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/30 p-2 rounded">
                    <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                    <span>
                      Diverges from planned RM action ({line.planned_action_name}). Deviation reason
                      will be recorded.
                    </span>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Global Deviation Section */}
        {hasDeviation && (
          <div className="p-4 rounded-xl border border-amber-300 bg-amber-50/70 dark:bg-amber-950/20 dark:border-amber-800 space-y-3">
            <div className="flex items-center gap-2 text-amber-900 dark:text-amber-200 font-semibold text-sm">
              <AlertTriangle className="w-4 h-4 text-amber-600" />
              Deviation Reason Required (DEC-13)
            </div>
            <p className="text-xs text-amber-800 dark:text-amber-300">
              One or more items diverge from the planned RM action. Please provide a clear
              commercial or technical justification for this change.
            </p>
            <textarea
              required
              rows={3}
              value={deviationReason}
              onChange={(e) => {
                setDeviationReason(e.target.value);
              }}
              placeholder="e.g. Technical servicing revealed unrepairable PCB damage; converting Send Repaired plan to Allow Credit Note upon customer agreement."
              className="w-full text-sm p-2.5 rounded-lg border border-amber-300 bg-background text-foreground focus:ring-2 focus:ring-amber-500"
            />
          </div>
        )}

        {/* Action Buttons */}
        <div className="flex items-center justify-end gap-3 pt-4 border-t">
          <Button type="button" variant="outline" onClick={onBack} disabled={submitting}>
            Cancel
          </Button>
          <Button
            type="submit"
            disabled={submitting}
            className="gap-2 bg-primary text-primary-foreground hover:bg-primary/90"
          >
            {submitting ? (
              <span className="animate-spin mr-2">◌</span>
            ) : (
              <CheckCircle2 className="w-4 h-4" />
            )}
            Confirm Step-7 Decision
          </Button>
        </div>
      </form>
    </div>
  );
}
