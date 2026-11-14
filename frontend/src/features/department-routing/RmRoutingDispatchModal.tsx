import React, { useRef, useState } from 'react';
import { X, Building2, AlertTriangle, ShieldCheck, Send } from 'lucide-react';
import type { GsRoutingState } from './types';
import { departmentRoutingApi, routingErrorMessage } from './api';
import { newIdempotencyKey } from '@/lib/api/client';

interface RmRoutingDispatchModalProps {
  state: GsRoutingState;
  onClose: () => void;
  onSuccess: () => void;
}

export const RmRoutingDispatchModal: React.FC<RmRoutingDispatchModalProps> = ({
  state,
  onClose,
  onSuccess,
}) => {
  // Collect all unique departments allowed across items in this GS
  const allDeptsMap = new Map<string, { field_id: string; code: string; label: string }>();
  state.items.forEach((it) => {
    it.allowed_departments.forEach((d) => {
      allDeptsMap.set(d.field_id, d);
    });
  });
  const allowedDepartments = Array.from(allDeptsMap.values());

  const [selectedDeptId, setSelectedDeptId] = useState<string>(
    allowedDepartments[0]?.field_id || '',
  );
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [remarks, setRemarks] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // G-16: one Idempotency-Key per modal opening, reused on retry so a double submit or a
  // network retry can never book stock twice.
  const idempotencyKey = useRef(newIdempotencyKey());

  const selectedDept = allowedDepartments.find((d) => d.field_id === selectedDeptId);

  // Filter items that are allowed to go to this department
  const eligibleItems = state.items.filter((it) =>
    it.allowed_departments.some((d) => d.field_id === selectedDeptId),
  );

  const handleQtyChange = (itemId: string, maxAvailable: number, valStr: string) => {
    const val = parseInt(valStr, 10);
    if (isNaN(val) || val <= 0) {
      setQuantities((prev) =>
        Object.fromEntries(Object.entries(prev).filter(([id]) => id !== itemId)),
      );
      return;
    }
    const clamped = Math.min(val, maxAvailable);
    setQuantities((prev) => ({ ...prev, [itemId]: clamped }));
  };

  const totalDispatchQty = Object.values(quantities).reduce((acc, q) => acc + q, 0);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedDeptId) {
      setError('Please select a destination department');
      return;
    }

    const lines = Object.entries(quantities)
      .filter(([, qty]) => qty > 0)
      .map(([itemId, qty]) => ({
        gs_item_id: itemId,
        qty_sent: qty,
      }));

    if (lines.length === 0) {
      setError('Please specify at least 1 item with quantity > 0');
      return;
    }

    setIsSubmitting(true);
    setError(null);

    departmentRoutingApi
      .dispatchRouting(
        {
          gs_id: state.id,
          department_field_id: selectedDeptId,
          lines,
          remarks: remarks.trim() || undefined,
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
            <div className="rounded-lg bg-indigo-50 p-2 dark:bg-indigo-950/50 text-indigo-600 dark:text-indigo-400">
              <Building2 className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                Route to Department (Issue Note)
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Goods Slip {state.gs_no} • Held at Intermediate Store
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
        <form onSubmit={handleSubmit} className="p-4 sm:p-6 space-y-5">
          {error && (
            <div className="rounded-lg bg-rose-50 p-3 text-xs font-medium text-rose-800 dark:bg-rose-950/40 dark:text-rose-400 border border-rose-200 dark:border-rose-800 flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {/* Department Selector */}
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5">
              Destination Department (Resolved Profile)
            </label>
            <select
              value={selectedDeptId}
              onChange={(e) => {
                setSelectedDeptId(e.target.value);
                setQuantities({});
              }}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            >
              {allowedDepartments.map((d) => (
                <option key={d.field_id} value={d.field_id}>
                  {d.label} ({d.code})
                </option>
              ))}
            </select>
            <p className="mt-1 text-[11px] text-slate-400">
              Only departments configured in the product's field profile are shown (AMD-10).
            </p>
          </div>

          {/* Items & Available Quantities Table */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300">
                Dispatch Quantities per Item (G-20 Enforced)
              </label>
              <span className="text-xs font-medium text-indigo-600 dark:text-indigo-400">
                Total to dispatch: {totalDispatchQty} pcs
              </span>
            </div>

            <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800 max-h-64">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 dark:bg-slate-800/60 text-slate-500 uppercase text-[10px] font-semibold sticky top-0">
                  <tr>
                    <th className="py-2 px-3">Item</th>
                    <th className="py-2 px-3 text-right">In Store</th>
                    <th className="py-2 px-3 text-right">At Dept</th>
                    <th className="py-2 px-3 text-right">Qty to Send</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {eligibleItems.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="py-4 text-center text-slate-400 italic">
                        No items in this GS are allowed for{' '}
                        {selectedDept?.label || 'this department'}
                      </td>
                    </tr>
                  ) : (
                    eligibleItems.map((it) => {
                      const avail = it.in_store_qty;
                      const isZero = avail <= 0;
                      const currentVal = quantities[it.item_id] ?? '';

                      return (
                        <tr
                          key={it.item_id}
                          className="hover:bg-slate-50/50 dark:hover:bg-slate-800/20"
                        >
                          <td className="py-2.5 px-3">
                            <div className="font-semibold text-slate-900 dark:text-slate-100">
                              #{it.line_no} {it.item_name}
                            </div>
                            {it.sku_code && (
                              <div className="text-[10px] font-mono text-slate-400">
                                {it.sku_code}
                              </div>
                            )}
                          </td>
                          <td className="py-2.5 px-3 text-right font-medium text-blue-600 dark:text-blue-400">
                            {avail}
                          </td>
                          <td className="py-2.5 px-3 text-right text-slate-400">
                            {it.at_departments_qty}
                          </td>
                          <td className="py-2.5 px-3 text-right">
                            <input
                              type="number"
                              min={1}
                              max={avail}
                              disabled={isZero}
                              value={currentVal}
                              placeholder={isZero ? '0 avail' : `Max ${String(avail)}`}
                              onChange={(e) => {
                                handleQtyChange(it.item_id, avail, e.target.value);
                              }}
                              className="w-20 rounded border border-slate-300 px-2 py-1 text-right text-xs font-semibold focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 disabled:bg-slate-100 dark:disabled:bg-slate-800/40 disabled:text-slate-400"
                            />
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Remarks */}
          <div>
            <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
              Remarks / Instructions for Department
            </label>
            <input
              type="text"
              value={remarks}
              onChange={(e) => {
                setRemarks(e.target.value);
              }}
              placeholder="e.g. Check temperature sensor calibration"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            />
          </div>

          {/* Footer Actions */}
          <div className="flex flex-col-reverse sm:flex-row items-center justify-between gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
            <div className="flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400 font-medium">
              <ShieldCheck className="h-4 w-4" />
              <span>G-20 Quantity Conservation active</span>
            </div>

            <div className="flex items-center gap-2.5 w-full sm:w-auto">
              <button
                type="button"
                onClick={onClose}
                className="w-full sm:w-auto rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isSubmitting || totalDispatchQty === 0}
                className="w-full sm:w-auto inline-flex items-center justify-center gap-1.5 rounded-lg bg-indigo-600 px-5 py-2 text-xs font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isSubmitting ? (
                  <span>Dispatching...</span>
                ) : (
                  <>
                    <Send className="h-3.5 w-3.5" />
                    <span>Dispatch Issue Note</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};
