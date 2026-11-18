/**
 * Department receiving (AMD-14 / DEC-42 / DEC-43; gap plan G3 / DEC-56 Q7, Q8, Q17).
 *
 * Per routing line the receiver books one or more rows of qty + outcome + condition after work
 * (the categorisation list of the product). The item's current condition split is updated by the
 * DB; the stock goes where the outcome head says (labels and destinations come from the API).
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { X, CheckCircle2, AlertTriangle, Plus, Trash2 } from 'lucide-react';
import type {
  DepartmentOutcomeHead,
  DepartmentReceiptLineIn,
  DepartmentRoutingLineOut,
  DepartmentRoutingOut,
} from './types';
import { departmentRoutingApi, routingErrorMessage } from './api';
import { newIdempotencyKey } from '@/lib/api/client';

interface DepartmentReceiveModalProps {
  routing: DepartmentRoutingOut;
  onClose: () => void;
  onSuccess: () => void;
}

interface Split {
  key: string;
  outcome_head_id: string;
  quantity: number;
  condition_field_id: string;
  remarks: string;
}

let splitSeq = 0;
const nextKey = () => {
  splitSeq += 1;
  return `split-${String(splitSeq)}`;
};

/** DEC-56: a line routed from a condition is received with a condition after work. */
const needsCondition = (ln: DepartmentRoutingLineOut) => Boolean(ln.source_bucket_field_id);

/** Default condition after work = the condition the pieces left in, when the product lists it. */
const defaultCondition = (ln: DepartmentRoutingLineOut) =>
  (ln.condition_options ?? []).some((o) => o.field_id === ln.source_bucket_field_id)
    ? (ln.source_bucket_field_id ?? '')
    : '';

const inputCls =
  'min-h-[44px] w-full rounded-lg border border-slate-300 bg-white px-2.5 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100';

export const DepartmentReceiveModal: React.FC<DepartmentReceiveModalProps> = ({
  routing,
  onClose,
  onSuccess,
}) => {
  const [outcomeHeads, setOutcomeHeads] = useState<DepartmentOutcomeHead[]>([]);
  const [loadingHeads, setLoadingHeads] = useState(true);
  const [splits, setSplits] = useState<Record<string, Split[]>>({});
  const [generalRemarks, setGeneralRemarks] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // G-16: one Idempotency-Key per modal opening, reused on retry so a double submit or a
  // network retry can never book a receipt (and its stock movement) twice.
  const idempotencyKey = useRef(newIdempotencyKey());

  const pendingLines = useMemo(
    () => routing.lines.filter((l) => l.qty_pending > 0),
    [routing.lines],
  );

  useEffect(() => {
    let mounted = true;
    departmentRoutingApi
      .getOutcomeHeads(true)
      .then((heads) => {
        if (!mounted) return;
        setOutcomeHeads(heads);
        const defaultHeadId = heads[0]?.id ?? '';
        const initial: Record<string, Split[]> = {};
        pendingLines.forEach((ln) => {
          initial[ln.id] = [
            {
              key: nextKey(),
              outcome_head_id: defaultHeadId,
              quantity: ln.qty_pending,
              condition_field_id: defaultCondition(ln),
              remarks: '',
            },
          ];
        });
        setSplits(initial);
      })
      .catch((err: unknown) => {
        if (mounted) setError(routingErrorMessage(err));
      })
      .finally(() => {
        if (mounted) setLoadingHeads(false);
      });
    return () => {
      mounted = false;
    };
  }, [pendingLines]);

  const headById = useMemo(() => new Map(outcomeHeads.map((h) => [h.id, h])), [outcomeHeads]);

  const updateSplit = (lineId: string, key: string, patch: Partial<Split>) => {
    setSplits((prev) => ({
      ...prev,
      [lineId]: (prev[lineId] ?? []).map((s) => (s.key === key ? { ...s, ...patch } : s)),
    }));
  };

  const addSplit = (ln: DepartmentRoutingLineOut) => {
    setSplits((prev) => {
      const rows = prev[ln.id] ?? [];
      const used = rows.reduce((a, s) => a + s.quantity, 0);
      return {
        ...prev,
        [ln.id]: [
          ...rows,
          {
            key: nextKey(),
            outcome_head_id: outcomeHeads[0]?.id ?? '',
            quantity: Math.max(ln.qty_pending - used, 0),
            condition_field_id: defaultCondition(ln),
            remarks: '',
          },
        ],
      };
    });
  };

  const removeSplit = (lineId: string, key: string) => {
    setSplits((prev) => ({
      ...prev,
      [lineId]: (prev[lineId] ?? []).filter((s) => s.key !== key),
    }));
  };

  const lineUsed = (lineId: string) =>
    (splits[lineId] ?? []).reduce((a, s) => a + s.quantity, 0);

  const problems = pendingLines.flatMap((ln) => {
    const out: string[] = [];
    if (lineUsed(ln.id) > ln.qty_pending) {
      out.push(`#${String(ln.line_no)}: more than the ${String(ln.qty_pending)} pcs pending`);
    }
    if (
      needsCondition(ln) &&
      (splits[ln.id] ?? []).some((s) => s.quantity > 0 && !s.condition_field_id)
    ) {
      out.push(`#${String(ln.line_no)}: choose the condition after work`);
    }
    return out;
  });

  const totalReceivingQty = pendingLines.reduce((a, ln) => a + lineUsed(ln.id), 0);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (problems.length > 0 || totalReceivingQty === 0) return;

    const lines: DepartmentReceiptLineIn[] = pendingLines.flatMap((ln) =>
      (splits[ln.id] ?? [])
        .filter((s) => s.quantity > 0)
        .map((s) => ({
          routing_line_id: ln.id,
          outcome_head_id: s.outcome_head_id,
          quantity: s.quantity,
          condition_field_id: needsCondition(ln) ? s.condition_field_id : null,
          remarks: s.remarks.trim() || undefined,
        })),
    );

    setIsSubmitting(true);
    setError(null);
    departmentRoutingApi
      .receiveRouting(
        routing.id,
        { routing_id: routing.id, lines, remarks: generalRemarks.trim() || undefined },
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
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-3 sm:p-4 overflow-y-auto"
      role="dialog"
      aria-modal="true"
      aria-labelledby="dept-receive-title"
    >
      <div className="relative w-full max-w-2xl rounded-2xl bg-white shadow-2xl dark:bg-slate-900 border border-slate-200 dark:border-slate-800 my-auto">
        <div className="flex items-center justify-between gap-2 p-4 sm:p-6 border-b border-slate-100 dark:border-slate-800">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="rounded-lg bg-emerald-50 p-2 dark:bg-emerald-950/50 text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h3
                id="dept-receive-title"
                className="text-base font-semibold text-slate-900 dark:text-slate-100"
              >
                Receive from Department
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 break-words">
                {routing.routing_no} • {routing.department_label}
              </p>
            </div>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="min-h-[44px] min-w-[44px] inline-flex items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-200"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-4 sm:p-6 space-y-4">
          {error && (
            <div
              role="alert"
              className="rounded-lg bg-rose-50 p-3 text-xs font-medium text-rose-800 dark:bg-rose-950/40 dark:text-rose-400 border border-rose-200 dark:border-rose-800 flex items-start gap-2"
            >
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
              <span className="break-words">{error}</span>
            </div>
          )}

          <p className="rounded-lg bg-slate-50 dark:bg-slate-800/40 p-3 text-xs text-slate-600 dark:text-slate-300">
            For each line record the outcome and the condition the pieces came back in. Split a
            line when pieces came back differently. Partial receipts are allowed.
          </p>

          {loadingHeads ? (
            <div className="py-8 text-center text-xs text-slate-400 animate-pulse">
              Loading outcomes…
            </div>
          ) : pendingLines.length === 0 ? (
            <div className="py-8 text-center text-sm text-slate-500">
              Nothing is pending on this issue note.
            </div>
          ) : outcomeHeads.length === 0 ? (
            <div className="py-8 text-center text-sm text-slate-500">
              No active outcomes are configured.
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                <span>Pending lines</span>
                <span className="text-indigo-600 dark:text-indigo-400">
                  Receiving {totalReceivingQty} pcs
                </span>
              </div>

              {pendingLines.map((ln) => {
                const rows = splits[ln.id] ?? [];
                const used = lineUsed(ln.id);
                const over = used > ln.qty_pending;
                const options = ln.condition_options ?? [];
                return (
                  <section
                    key={ln.id}
                    aria-label={`Line ${String(ln.line_no)}`}
                    className="rounded-xl border border-slate-200 dark:border-slate-800 p-3 sm:p-4 space-y-3"
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <div className="min-w-0">
                        <div className="font-semibold text-sm text-slate-900 dark:text-slate-100 break-words">
                          #{ln.line_no} {ln.item_name}
                        </div>
                        <div className="text-xs text-slate-500 dark:text-slate-400">
                          {ln.source_bucket_label ? `Sent as ${ln.source_bucket_label} • ` : ''}
                          Sent {ln.qty_sent} • Received {ln.qty_received} •{' '}
                          <span className="font-medium text-amber-600 dark:text-amber-400">
                            Pending {ln.qty_pending}
                          </span>
                        </div>
                      </div>
                      <span
                        className={`text-xs ${over ? 'font-semibold text-rose-600' : 'text-slate-500'}`}
                      >
                        {used} of {ln.qty_pending} pcs
                      </span>
                    </div>

                    {needsCondition(ln) && options.length === 0 ? (
                      <p role="alert" className="text-xs font-medium text-rose-600">
                        No conditions are configured for this product (Admin → Field Profiles).
                      </p>
                    ) : null}

                    {rows.map((s, idx) => {
                      const head = headById.get(s.outcome_head_id);
                      const base = `rcv-${ln.id}-${s.key}`;
                      return (
                        <div
                          key={s.key}
                          className="rounded-lg bg-slate-50 dark:bg-slate-800/40 p-3 space-y-2"
                        >
                          <div className="grid grid-cols-1 sm:grid-cols-[6rem_1fr_1fr] gap-2">
                            <div>
                              <label
                                htmlFor={`${base}-qty`}
                                className="block text-[11px] font-medium text-slate-500 mb-1"
                              >
                                Qty
                              </label>
                              <input
                                id={`${base}-qty`}
                                type="number"
                                inputMode="numeric"
                                min={0}
                                max={ln.qty_pending}
                                value={s.quantity}
                                onChange={(e) => {
                                  const n = parseInt(e.target.value, 10);
                                  updateSplit(ln.id, s.key, {
                                    quantity: isNaN(n) ? 0 : Math.max(0, n),
                                  });
                                }}
                                className={`${inputCls} text-right font-semibold`}
                              />
                            </div>
                            <div>
                              <label
                                htmlFor={`${base}-outcome`}
                                className="block text-[11px] font-medium text-slate-500 mb-1"
                              >
                                Outcome
                              </label>
                              <select
                                id={`${base}-outcome`}
                                value={s.outcome_head_id}
                                onChange={(e) => {
                                  updateSplit(ln.id, s.key, { outcome_head_id: e.target.value });
                                }}
                                className={inputCls}
                              >
                                {outcomeHeads.map((h) => (
                                  <option key={h.id} value={h.id}>
                                    {h.label}
                                  </option>
                                ))}
                              </select>
                            </div>
                            {needsCondition(ln) ? (
                              <div>
                                <label
                                  htmlFor={`${base}-condition`}
                                  className="block text-[11px] font-medium text-slate-500 mb-1"
                                >
                                  Condition after work
                                </label>
                                <select
                                  id={`${base}-condition`}
                                  value={s.condition_field_id}
                                  onChange={(e) => {
                                    updateSplit(ln.id, s.key, {
                                      condition_field_id: e.target.value,
                                    });
                                  }}
                                  className={inputCls}
                                >
                                  <option value="">Choose…</option>
                                  {options.map((o) => (
                                    <option key={o.field_id} value={o.field_id}>
                                      {o.label}
                                    </option>
                                  ))}
                                </select>
                              </div>
                            ) : null}
                          </div>
                          <div className="flex flex-col sm:flex-row gap-2">
                            <label htmlFor={`${base}-remarks`} className="sr-only">
                              Remarks
                            </label>
                            <input
                              id={`${base}-remarks`}
                              type="text"
                              placeholder="Remarks (optional)"
                              value={s.remarks}
                              onChange={(e) => {
                                updateSplit(ln.id, s.key, { remarks: e.target.value });
                              }}
                              className={inputCls}
                            />
                            {rows.length > 1 ? (
                              <button
                                type="button"
                                aria-label={`Remove row ${String(idx + 1)} of line ${String(ln.line_no)}`}
                                onClick={() => {
                                  removeSplit(ln.id, s.key);
                                }}
                                className="min-h-[44px] min-w-[44px] inline-flex items-center justify-center rounded-lg border border-slate-300 text-slate-500 hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
                              >
                                <Trash2 className="h-4 w-4" />
                              </button>
                            ) : null}
                          </div>
                          {head ? (
                            <p className="text-[11px] text-slate-500 dark:text-slate-400">
                              {head.returns_to_routing
                                ? 'Back to the RM routing queue. '
                                : 'Ready for RM final actions. '}
                              {head.destination_location_name
                                ? `Stock goes to ${head.destination_location_name}.`
                                : ''}
                            </p>
                          ) : null}
                        </div>
                      );
                    })}

                    {used < ln.qty_pending ? (
                      <button
                        type="button"
                        onClick={() => {
                          addSplit(ln);
                        }}
                        className="min-h-[44px] inline-flex items-center gap-1.5 rounded-lg border border-dashed border-slate-300 px-3 text-xs font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
                      >
                        <Plus className="h-4 w-4" /> Split: add another outcome / condition
                      </button>
                    ) : null}
                  </section>
                );
              })}
            </div>
          )}

          {problems.length > 0 ? (
            <ul role="alert" className="text-xs font-medium text-rose-600 space-y-0.5">
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          ) : null}

          <div>
            <label
              htmlFor="rcv-general-remarks"
              className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1"
            >
              Receipt remarks
            </label>
            <input
              id="rcv-general-remarks"
              type="text"
              value={generalRemarks}
              onChange={(e) => {
                setGeneralRemarks(e.target.value);
              }}
              className={inputCls}
            />
          </div>

          <div className="flex flex-col-reverse sm:flex-row items-stretch sm:items-center justify-end gap-2.5 pt-3 border-t border-slate-100 dark:border-slate-800">
            <button
              type="button"
              onClick={onClose}
              className="min-h-[44px] rounded-lg border border-slate-300 bg-white px-4 text-xs font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting || totalReceivingQty === 0 || problems.length > 0}
              className="min-h-[44px] inline-flex items-center justify-center gap-1.5 rounded-lg bg-emerald-600 px-5 text-xs font-semibold text-white shadow-sm hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSubmitting ? (
                'Recording receipt…'
              ) : (
                <>
                  <CheckCircle2 className="h-4 w-4" />
                  <span>Confirm receipt ({totalReceivingQty} pcs)</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
