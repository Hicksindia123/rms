import React, { useState, useEffect, useRef } from 'react';
import { X, CheckCircle2, AlertTriangle } from 'lucide-react';
import type { DepartmentRoutingOut, DepartmentOutcomeHead } from './types';
import { departmentRoutingApi, routingErrorMessage } from './api';
import { newIdempotencyKey } from '@/lib/api/client';

interface DepartmentReceiveModalProps {
  routing: DepartmentRoutingOut;
  onClose: () => void;
  onSuccess: () => void;
}

export const DepartmentReceiveModal: React.FC<DepartmentReceiveModalProps> = ({
  routing,
  onClose,
  onSuccess,
}) => {
  const [outcomeHeads, setOutcomeHeads] = useState<DepartmentOutcomeHead[]>([]);
  const [loadingHeads, setLoadingHeads] = useState(true);

  // Line receipts state: map of routing_line_id -> { outcome_head_id: string, quantity: number, remarks: string }
  const [lineReceives, setLineReceives] = useState<
    Record<string, { outcome_head_id: string; quantity: number; remarks: string }>
  >({});

  const [generalRemarks, setGeneralRemarks] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // G-16: one Idempotency-Key per modal opening, reused on retry so a double submit or a
  // network retry can never book a receipt (and its stock movement) twice.
  const idempotencyKey = useRef(newIdempotencyKey());

  useEffect(() => {
    let mounted = true;
    departmentRoutingApi
      .getOutcomeHeads(true)
      .then((heads) => {
        if (mounted) {
          setOutcomeHeads(heads);
          setLoadingHeads(false);
          // Set default outcome head (first one, e.g. REPAIRED)
          const defaultHeadId = heads[0]?.id || '';
          const initialReceives: Record<
            string,
            { outcome_head_id: string; quantity: number; remarks: string }
          > = {};
          routing.lines.forEach((ln) => {
            if (ln.qty_pending > 0) {
              initialReceives[ln.id] = {
                outcome_head_id: defaultHeadId,
                quantity: ln.qty_pending,
                remarks: '',
              };
            }
          });
          setLineReceives(initialReceives);
        }
      })
      .catch((err: unknown) => {
        if (mounted) {
          setError(routingErrorMessage(err));
          setLoadingHeads(false);
        }
      });

    return () => {
      mounted = false;
    };
  }, [routing]);

  const handleHeadChange = (lineId: string, headId: string) => {
    setLineReceives((prev) => ({
      ...prev,
      [lineId]: {
        ...(prev[lineId] || { quantity: 0, remarks: '' }),
        outcome_head_id: headId,
      },
    }));
  };

  const handleQtyChange = (lineId: string, maxPending: number, valStr: string) => {
    const val = parseInt(valStr, 10);
    const qty = isNaN(val) ? 0 : Math.max(0, Math.min(val, maxPending));
    setLineReceives((prev) => ({
      ...prev,
      [lineId]: {
        ...(prev[lineId] || { outcome_head_id: outcomeHeads[0]?.id || '', remarks: '' }),
        quantity: qty,
      },
    }));
  };

  const handleLineRemarksChange = (lineId: string, remarks: string) => {
    setLineReceives((prev) => ({
      ...prev,
      [lineId]: {
        ...(prev[lineId] || { outcome_head_id: outcomeHeads[0]?.id || '', quantity: 0 }),
        remarks,
      },
    }));
  };

  const pendingLines = routing.lines.filter((l) => l.qty_pending > 0);

  const totalReceivingQty = Object.values(lineReceives).reduce(
    (sum, item) => sum + item.quantity,
    0,
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    const linesToSubmit = Object.entries(lineReceives)
      .filter(([, data]) => data.quantity > 0)
      .map(([lineId, data]) => ({
        routing_line_id: lineId,
        outcome_head_id: data.outcome_head_id,
        quantity: data.quantity,
        remarks: data.remarks.trim() || undefined,
      }));

    if (linesToSubmit.length === 0) {
      setError('Please enter receiving quantity for at least 1 line');
      return;
    }

    setIsSubmitting(true);
    setError(null);

    departmentRoutingApi
      .receiveRouting(
        routing.id,
        {
          routing_id: routing.id,
          lines: linesToSubmit,
          remarks: generalRemarks.trim() || undefined,
        },
        idempotencyKey.current,
      )
      .then(() => {
        onSuccess();
      })
      .catch((err: unknown) => {
        setError(routingErrorMessage(err));
      })
      .finally(() => {
        setIsSubmitting(false);
      });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-3 sm:p-4 overflow-y-auto">
      <div className="relative w-full max-w-2xl rounded-2xl bg-white shadow-2xl dark:bg-slate-900 border border-slate-200 dark:border-slate-800 my-auto">
        {/* Modal Header */}
        <div className="flex items-center justify-between p-4 sm:p-6 border-b border-slate-100 dark:border-slate-800">
          <div className="flex items-center gap-2.5">
            <div className="rounded-lg bg-emerald-50 p-2 dark:bg-emerald-950/50 text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                Department Receiving & Outcome Classification
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {routing.routing_no} • {routing.department_label} ({routing.department_code})
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-200"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Modal Body */}
        <form onSubmit={handleSubmit} className="p-4 sm:p-6 space-y-4">
          {error && (
            <div className="rounded-lg bg-rose-50 p-3 text-xs font-medium text-rose-800 dark:bg-rose-950/40 dark:text-rose-400 border border-rose-200 dark:border-rose-800 flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <div className="rounded-lg bg-slate-50 dark:bg-slate-800/40 p-3 text-xs text-slate-600 dark:text-slate-300">
            <div className="font-semibold text-slate-900 dark:text-slate-100 mb-0.5">
              AMD-14 / DEC-42 / DEC-43 Receiving Guide:
            </div>
            Items can be received into terminal outcomes (Repaired, Wastage) or return to RM routing
            queue (Re-Route, Mercury Extraction). Partial receipts are allowed.
          </div>

          {loadingHeads ? (
            <div className="py-8 text-center text-xs text-slate-400 animate-pulse">
              Loading outcome classification heads...
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                <span>Pending Routing Lines</span>
                <span className="text-indigo-600 dark:text-indigo-400">
                  Receiving {totalReceivingQty} pieces
                </span>
              </div>

              <div className="space-y-3 max-h-72 overflow-y-auto pr-1">
                {pendingLines.map((ln) => {
                  const state = lineReceives[ln.id] || {
                    outcome_head_id: outcomeHeads[0]?.id || '',
                    quantity: ln.qty_pending,
                    remarks: '',
                  };

                  const selectedHead = outcomeHeads.find((h) => h.id === state.outcome_head_id);

                  return (
                    <div
                      key={ln.id}
                      className="rounded-xl border border-slate-200 dark:border-slate-800 p-3 sm:p-4 bg-white dark:bg-slate-900 space-y-3"
                    >
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                        <div>
                          <div className="font-semibold text-xs text-slate-900 dark:text-slate-100">
                            #{ln.line_no} {ln.item_name}
                          </div>
                          <div className="text-[11px] text-slate-400">
                            Sent: {ln.qty_sent} • Received: {ln.qty_received} •{' '}
                            <span className="font-medium text-amber-600 dark:text-amber-400">
                              Pending: {ln.qty_pending} pcs
                            </span>
                          </div>
                        </div>

                        {/* Quantity input */}
                        <div className="flex items-center gap-2 self-end sm:self-auto">
                          <label className="text-[11px] font-medium text-slate-500">
                            Qty to Receive:
                          </label>
                          <input
                            type="number"
                            min={0}
                            max={ln.qty_pending}
                            value={state.quantity}
                            onChange={(e) => {
                              handleQtyChange(ln.id, ln.qty_pending, e.target.value);
                            }}
                            className="w-20 rounded border border-slate-300 px-2 py-1 text-right text-xs font-bold focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                          />
                        </div>
                      </div>

                      {/* Outcome classification selector */}
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-2 border-t border-slate-100 dark:border-slate-800/80">
                        <div>
                          <label className="block text-[11px] font-medium text-slate-500 mb-1">
                            Outcome Head
                          </label>
                          <select
                            value={state.outcome_head_id}
                            onChange={(e) => {
                              handleHeadChange(ln.id, e.target.value);
                            }}
                            className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                          >
                            {outcomeHeads.map((h) => (
                              <option key={h.id} value={h.id}>
                                {h.label}{' '}
                                {h.is_wastage
                                  ? '(Wastage)'
                                  : h.returns_to_routing
                                    ? '(Re-Route)'
                                    : ''}
                              </option>
                            ))}
                          </select>
                        </div>

                        <div>
                          <label className="block text-[11px] font-medium text-slate-500 mb-1">
                            Line Remarks
                          </label>
                          <input
                            type="text"
                            placeholder="e.g. Cleaned / repaired OK"
                            value={state.remarks}
                            onChange={(e) => {
                              handleLineRemarksChange(ln.id, e.target.value);
                            }}
                            className="w-full rounded border border-slate-300 px-2.5 py-1.5 text-xs text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                          />
                        </div>
                      </div>

                      {/* Head behavior hint */}
                      {selectedHead && (
                        <div className="text-[10px] text-slate-400 flex items-center gap-1">
                          {selectedHead.is_wastage && (
                            <span className="text-rose-600 dark:text-rose-400 font-medium">
                              • Will move to SCRAP_DISPOSED
                            </span>
                          )}
                          {selectedHead.returns_to_routing && (
                            <span className="text-purple-600 dark:text-purple-400 font-medium">
                              • DEC-43: Returns to RM Routing Queue for re-direction
                            </span>
                          )}
                          {!selectedHead.is_wastage && !selectedHead.returns_to_routing && (
                            <span className="text-emerald-600 dark:text-emerald-400 font-medium">
                              • Retained in Intermediate Store for RM resolution
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* General Remarks */}
          <div>
            <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
              General Receipt Remarks
            </label>
            <input
              type="text"
              value={generalRemarks}
              onChange={(e) => {
                setGeneralRemarks(e.target.value);
              }}
              placeholder="e.g. Received from technician desk"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            />
          </div>

          {/* Footer Actions */}
          <div className="flex items-center justify-end gap-2.5 pt-3 border-t border-slate-100 dark:border-slate-800">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting || totalReceivingQty === 0}
              className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-emerald-600 px-5 py-2 text-xs font-semibold text-white shadow-sm hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSubmitting ? (
                <span>Recording Receipt...</span>
              ) : (
                <>
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  <span>Confirm Receipt ({totalReceivingQty} pcs)</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
