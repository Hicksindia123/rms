/**
 * DEC-55 (gap plan G2, Q3–Q6): the Replacement Manager plans where each condition of each item
 * goes — Store (no work), Cleaning, Technician / Repair, Mercury Extraction (labels from the
 * DEPARTMENT field library). Planning moves no stock: the Intermediate Store Manager issues the
 * planned pieces (DIN). "No work" pieces stay in the store and go to Final Actions.
 */
import React, { useMemo, useRef, useState } from 'react';
import { X, Building2, AlertTriangle, ShieldCheck, ClipboardList } from 'lucide-react';
import type { GsRoutingItemState, GsRoutingState, RoutingPlanLine } from './types';
import { departmentRoutingApi, routingErrorMessage } from './api';
import { newIdempotencyKey } from '@/lib/api/client';

interface RmRoutingPlanModalProps {
  state: GsRoutingState;
  /** May the user cancel open plan lines (department_routing/create)? */
  canPlan: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

interface Row {
  key: string;
  bucketId: string | null;
  label: string;
  total: number;
  free: number;
  /** DEC-56: counting-split qty when department work changed this condition. */
  original: number | null;
}

/** DEC-56: rows come from the CURRENT condition split (pieces may come back in another
 * condition after department work); the counting split is shown as "was" when it differs. */
function rowsFor(it: GsRoutingItemState): Row[] {
  if (it.conditions.length === 0) {
    return [
      {
        key: `${it.item_id}|`,
        bucketId: null,
        label: 'All pieces',
        total: it.in_store_qty,
        free: it.unplanned_qty,
        original: null,
      },
    ];
  }
  return it.conditions
    .filter((c) => c.current_qty > 0)
    .map((c) => ({
      key: `${it.item_id}|${c.field_id}`,
      bucketId: c.field_id,
      label: c.field_label,
      total: c.current_qty,
      free: c.plannable_qty,
      original: c.original_qty !== c.current_qty ? c.original_qty : null,
    }));
}

const STATUS_STYLE: Record<RoutingPlanLine['status'], string> = {
  PLANNED:
    'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-800',
  ISSUED:
    'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/40 dark:text-blue-300 dark:border-blue-800',
  NO_WORK:
    'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800',
  CANCELLED:
    'bg-slate-100 text-slate-500 border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700',
};

const STATUS_TEXT: Record<RoutingPlanLine['status'], string> = {
  PLANNED: 'Waiting for store issue',
  ISSUED: 'Issued',
  NO_WORK: 'No work – ready for final actions',
  CANCELLED: 'Cancelled',
};

export const RmRoutingPlanModal: React.FC<RmRoutingPlanModalProps> = ({
  state,
  canPlan,
  onClose,
  onSuccess,
}) => {
  // qty per `${itemId}|${bucketId}|${deptId}`
  const [qty, setQty] = useState<Record<string, number>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState<{ id: string; reason: string } | null>(null);
  const [cancelBusy, setCancelBusy] = useState(false);
  // G-16: one Idempotency-Key per modal opening, reused on retry (never plans twice).
  const idempotencyKey = useRef(newIdempotencyKey());

  const rowSums = useMemo(() => {
    const sums: Record<string, number> = {};
    for (const [k, v] of Object.entries(qty)) {
      const rowKey = k.split('|').slice(0, 2).join('|');
      sums[rowKey] = (sums[rowKey] ?? 0) + v;
    }
    return sums;
  }, [qty]);

  const itemSums = useMemo(() => {
    const sums: Record<string, number> = {};
    for (const [k, v] of Object.entries(qty)) {
      const itemId = k.split('|')[0] ?? '';
      sums[itemId] = (sums[itemId] ?? 0) + v;
    }
    return sums;
  }, [qty]);

  const overRows = state.items.flatMap((it) =>
    rowsFor(it).filter((r) => (rowSums[r.key] ?? 0) > r.free),
  );
  const overItems = state.items.filter((it) => (itemSums[it.item_id] ?? 0) > it.unplanned_qty);
  const total = Object.values(qty).reduce((a, b) => a + b, 0);
  const invalid = overRows.length > 0 || overItems.length > 0;

  const setCell = (cellKey: string, raw: string) => {
    const n = parseInt(raw, 10);
    setQty((prev) => {
      const rest = Object.fromEntries(Object.entries(prev).filter(([k]) => k !== cellKey));
      return isNaN(n) || n <= 0 ? rest : { ...rest, [cellKey]: n };
    });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (invalid || total === 0) return;
    const lines = Object.entries(qty).map(([k, v]) => {
      const [itemId = '', bucketId = '', deptId = ''] = k.split('|');
      return {
        gs_item_id: itemId,
        source_bucket_field_id: bucketId || null,
        department_field_id: deptId,
        qty: v,
      };
    });
    setIsSubmitting(true);
    setError(null);
    departmentRoutingApi
      .planRouting({ gs_id: state.id, lines }, idempotencyKey.current)
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

  const confirmCancel = () => {
    if (!cancelling || cancelling.reason.trim().length < 3) return;
    setCancelBusy(true);
    setError(null);
    departmentRoutingApi
      .cancelPlanLine(cancelling.id, cancelling.reason.trim())
      .then(() => {
        setCancelling(null);
        onSuccess();
      })
      .catch((err: unknown) => {
        setError(routingErrorMessage(err));
      })
      .finally(() => {
        setCancelBusy(false);
      });
  };

  const visibleLines = state.plan_lines.filter((l) => l.status !== 'CANCELLED');

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-3 sm:p-4 overflow-y-auto"
      role="dialog"
      aria-modal="true"
      aria-labelledby="rm-plan-title"
    >
      <div className="relative w-full max-w-3xl rounded-2xl bg-white shadow-2xl dark:bg-slate-900 border border-slate-200 dark:border-slate-800 my-auto">
        <div className="flex items-center justify-between p-4 sm:p-6 border-b border-slate-100 dark:border-slate-800">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="rounded-lg bg-indigo-50 p-2 dark:bg-indigo-950/50 text-indigo-600 dark:text-indigo-400">
              <Building2 className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h3
                id="rm-plan-title"
                className="text-base font-semibold text-slate-900 dark:text-slate-100"
              >
                Plan Department Routing
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 break-words">
                Goods Slip {state.gs_no} • the Store Manager issues the planned pieces
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

        <form onSubmit={handleSubmit} className="p-4 sm:p-6 space-y-5">
          {error && (
            <div
              role="alert"
              className="rounded-lg bg-rose-50 p-3 text-xs font-medium text-rose-800 dark:bg-rose-950/40 dark:text-rose-400 border border-rose-200 dark:border-rose-800 flex items-start gap-2"
            >
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
              <span className="break-words">{error}</span>
            </div>
          )}

          {visibleLines.length > 0 && (
            <section aria-label="Current routing plan">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-2 flex items-center gap-1.5">
                <ClipboardList className="h-4 w-4" /> Current plan
              </h4>
              <ul className="space-y-2">
                {visibleLines.map((l) => (
                  <li
                    key={l.id}
                    className="rounded-lg border border-slate-200 dark:border-slate-800 p-3 text-xs"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="min-w-0">
                        <span className="font-semibold text-slate-900 dark:text-slate-100">
                          #{l.line_no} {l.item_name}
                        </span>
                        <span className="text-slate-500 dark:text-slate-400">
                          {' '}
                          • {l.source_bucket_label ?? 'All pieces'} → {l.department_label} • {l.qty}{' '}
                          pcs
                        </span>
                        {l.routing_no ? (
                          <span className="text-slate-500 dark:text-slate-400">
                            {' '}
                            • {l.routing_no}
                          </span>
                        ) : null}
                      </div>
                      <div className="flex items-center gap-2">
                        <span
                          className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${STATUS_STYLE[l.status]}`}
                        >
                          {STATUS_TEXT[l.status]}
                        </span>
                        {canPlan &&
                        (l.status === 'PLANNED' || l.status === 'NO_WORK') &&
                        cancelling?.id !== l.id ? (
                          <button
                            type="button"
                            onClick={() => {
                              setCancelling({ id: l.id, reason: '' });
                            }}
                            className="min-h-[44px] rounded-lg border border-slate-300 px-3 text-xs font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
                          >
                            Cancel line
                          </button>
                        ) : null}
                      </div>
                    </div>
                    {cancelling?.id === l.id ? (
                      <div className="mt-2 flex flex-col sm:flex-row gap-2">
                        <label className="sr-only" htmlFor={`cancel-reason-${l.id}`}>
                          Reason for cancelling
                        </label>
                        <input
                          id={`cancel-reason-${l.id}`}
                          type="text"
                          value={cancelling.reason}
                          placeholder="Reason (required)"
                          onChange={(e) => {
                            setCancelling({ id: l.id, reason: e.target.value });
                          }}
                          className="min-h-[44px] flex-1 rounded-lg border border-slate-300 bg-white px-3 text-xs text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                        />
                        <button
                          type="button"
                          disabled={cancelBusy || cancelling.reason.trim().length < 3}
                          onClick={confirmCancel}
                          className="min-h-[44px] rounded-lg bg-rose-600 px-4 text-xs font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
                        >
                          {cancelBusy ? 'Cancelling…' : 'Confirm cancel'}
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setCancelling(null);
                          }}
                          className="min-h-[44px] rounded-lg border border-slate-300 px-4 text-xs font-medium text-slate-700 dark:border-slate-700 dark:text-slate-200"
                        >
                          Keep
                        </button>
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section aria-label="Plan new routing" className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300">
                Route per item and condition
              </h4>
              <span className="text-xs font-medium text-indigo-600 dark:text-indigo-400">
                Planning: {total} pcs
              </span>
            </div>

            {state.items.map((it) => {
              const rows = rowsFor(it);
              const itemOver = (itemSums[it.item_id] ?? 0) > it.unplanned_qty;
              return (
                <div
                  key={it.item_id}
                  className="rounded-xl border border-slate-200 dark:border-slate-800 p-3 sm:p-4"
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <div className="font-semibold text-sm text-slate-900 dark:text-slate-100 break-words">
                      #{it.line_no} {it.item_name}
                    </div>
                    <div className="text-xs text-slate-500 dark:text-slate-400">
                      In store {it.in_store_qty} • not yet planned{' '}
                      <span className="font-semibold text-slate-800 dark:text-slate-200">
                        {it.unplanned_qty}
                      </span>
                    </div>
                  </div>
                  {itemOver ? (
                    <p role="alert" className="mt-1 text-xs font-medium text-rose-600">
                      More than the {it.unplanned_qty} pcs not yet planned.
                    </p>
                  ) : null}
                  {it.allowed_departments.length === 0 ? (
                    <p className="mt-2 text-xs text-slate-500">
                      No departments are enabled for this product (Admin → Field Profiles).
                    </p>
                  ) : (
                    <div className="mt-3 space-y-3">
                      {rows.map((r) => {
                        const used = rowSums[r.key] ?? 0;
                        const over = used > r.free;
                        return (
                          <div
                            key={r.key}
                            className="rounded-lg bg-slate-50 dark:bg-slate-800/40 p-3"
                          >
                            <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
                              <span className="font-semibold text-slate-800 dark:text-slate-200">
                                {r.label}
                                <span className="font-normal text-slate-500 dark:text-slate-400">
                                  {' '}
                                  · {r.total} pcs now
                                  {r.original !== null ? ` (counted ${String(r.original)})` : ''}
                                </span>
                              </span>
                              <span
                                className={over ? 'text-rose-600 font-semibold' : 'text-slate-500'}
                              >
                                {r.free === 0
                                  ? `Fully routed (${String(r.total)} pcs)`
                                  : `${String(used)} of ${String(r.free)} free pcs`}
                              </span>
                            </div>
                            {r.free > 0 ? (
                              <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-2">
                                {it.allowed_departments.map((d) => {
                                  const cellKey = `${r.key}|${d.field_id}`;
                                  const inputId = `plan-${cellKey}`;
                                  return (
                                    <div
                                      key={d.field_id}
                                      className="flex items-center justify-between gap-2"
                                    >
                                      <label
                                        htmlFor={inputId}
                                        className="text-xs text-slate-700 dark:text-slate-300 min-w-0"
                                      >
                                        {d.label}
                                        {d.is_no_work ? (
                                          <span className="block text-[10px] text-emerald-600 dark:text-emerald-400">
                                            no work · stays in store
                                          </span>
                                        ) : null}
                                      </label>
                                      <input
                                        id={inputId}
                                        type="number"
                                        inputMode="numeric"
                                        min={0}
                                        max={r.free}
                                        value={qty[cellKey] ?? ''}
                                        placeholder="0"
                                        onChange={(e) => {
                                          setCell(cellKey, e.target.value);
                                        }}
                                        className="min-h-[44px] w-24 shrink-0 rounded-lg border border-slate-300 bg-white px-2 text-right text-sm font-semibold text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                                      />
                                    </div>
                                  );
                                })}
                              </div>
                            ) : null}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </section>

          <div className="flex flex-col-reverse sm:flex-row items-stretch sm:items-center justify-between gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
            <div className="flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400 font-medium">
              <ShieldCheck className="h-4 w-4 shrink-0" />
              <span>No stock moves until the Store Manager issues</span>
            </div>
            <div className="flex flex-col-reverse sm:flex-row gap-2.5">
              <button
                type="button"
                onClick={onClose}
                className="min-h-[44px] rounded-lg border border-slate-300 bg-white px-4 text-xs font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300"
              >
                Close
              </button>
              <button
                type="submit"
                disabled={isSubmitting || total === 0 || invalid}
                className="min-h-[44px] inline-flex items-center justify-center gap-1.5 rounded-lg bg-indigo-600 px-5 text-xs font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isSubmitting ? 'Saving…' : 'Save routing plan'}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};
