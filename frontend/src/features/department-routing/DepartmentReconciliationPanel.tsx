import React from 'react';
import {
  ShieldCheck,
  AlertTriangle,
  Layers,
  Store,
  Building2,
  CheckCircle2,
  Award,
} from 'lucide-react';
import type { GsReconciliationOut } from './types';

interface DepartmentReconciliationPanelProps {
  reconciliation: GsReconciliationOut | null;
  loading?: boolean;
  /** Load error (message incl. request id); shown with a retry button (CLAUDE.md rule h). */
  error?: string | null;
  onRefresh?: () => void;
}

const SKELETON_TILES = [0, 1, 2, 3, 4];

export const DepartmentReconciliationPanel: React.FC<DepartmentReconciliationPanelProps> = ({
  reconciliation,
  loading = false,
  error = null,
  onRefresh,
}) => {
  if (loading) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900 animate-pulse">
        <div className="h-5 w-48 bg-slate-200 dark:bg-slate-700 rounded mb-4" />
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {SKELETON_TILES.map((i) => (
            <div key={i} className="h-16 bg-slate-100 dark:bg-slate-800 rounded-lg" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        role="alert"
        className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-xs font-medium text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-400"
      >
        <span className="break-words">{error}</span>
        {onRefresh && (
          <button
            type="button"
            onClick={onRefresh}
            className="min-h-[44px] rounded-lg border border-rose-300 bg-white px-4 text-xs font-semibold text-rose-700 hover:bg-rose-100 dark:border-rose-800 dark:bg-rose-950 dark:text-rose-300"
          >
            Retry
          </button>
        )}
      </div>
    );
  }

  if (!reconciliation) {
    return null;
  }

  const {
    is_fully_reconciled,
    total_counted,
    total_in_store,
    total_at_departments,
    total_outcomes,
    total_actioned,
    items,
  } = reconciliation;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 sm:p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      {/* Header with Guard G-20 Badge */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-slate-100 dark:border-slate-800">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
              Quantity Reconciliation Panel
            </h3>
            {is_fully_reconciled ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800">
                <ShieldCheck className="h-3.5 w-3.5" />
                Conserved
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-full bg-rose-50 px-2.5 py-0.5 text-xs font-semibold text-rose-700 dark:bg-rose-950/50 dark:text-rose-400 border border-rose-200 dark:border-rose-800">
                <AlertTriangle className="h-3.5 w-3.5" />
                Imbalance Detected
              </span>
            )}
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Counted = In Store + At Departments + Terminal Outcomes + Actioned
          </p>
        </div>

        {onRefresh && (
          <button
            type="button"
            onClick={onRefresh}
            className="self-start sm:self-center text-xs font-medium text-indigo-600 hover:text-indigo-700 dark:text-indigo-400"
          >
            Refresh Reconciliation
          </button>
        )}
      </div>

      {/* Aggregate KPI Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2.5 sm:gap-4 my-4">
        {/* Counted */}
        <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-3 border border-slate-200/60 dark:border-slate-700/60">
          <div className="flex items-center gap-1.5 text-slate-500 dark:text-slate-400 text-xs font-medium">
            <Layers className="h-3.5 w-3.5 text-slate-600 dark:text-slate-300" />
            <span>Total Counted</span>
          </div>
          <div className="mt-1 text-xl sm:text-2xl font-bold text-slate-900 dark:text-slate-100">
            {total_counted}
          </div>
          <div className="text-[10px] text-slate-400 mt-0.5">Baseline (100%)</div>
        </div>

        {/* In Store */}
        <div className="rounded-lg bg-blue-50/60 dark:bg-blue-950/20 p-3 border border-blue-200/60 dark:border-blue-800/40">
          <div className="flex items-center gap-1.5 text-blue-700 dark:text-blue-300 text-xs font-medium">
            <Store className="h-3.5 w-3.5" />
            <span>In Store</span>
          </div>
          <div className="mt-1 text-xl sm:text-2xl font-bold text-blue-900 dark:text-blue-100">
            {total_in_store}
          </div>
          <div className="text-[10px] text-blue-600/80 dark:text-blue-400 mt-0.5">
            {reconciliation.total_planned
              ? `${String(reconciliation.total_planned)} planned, not issued`
              : 'Available to route'}
            {reconciliation.total_no_work
              ? ` · ${String(reconciliation.total_no_work)} no work`
              : ''}
          </div>
        </div>

        {/* At Departments */}
        <div className="rounded-lg bg-amber-50/60 dark:bg-amber-950/20 p-3 border border-amber-200/60 dark:border-amber-800/40">
          <div className="flex items-center gap-1.5 text-amber-700 dark:text-amber-300 text-xs font-medium">
            <Building2 className="h-3.5 w-3.5" />
            <span>At Departments</span>
          </div>
          <div className="mt-1 text-xl sm:text-2xl font-bold text-amber-900 dark:text-amber-100">
            {total_at_departments}
          </div>
          <div className="text-[10px] text-amber-600/80 dark:text-amber-400 mt-0.5">
            Under process
          </div>
        </div>

        {/* Terminal Outcomes */}
        <div className="rounded-lg bg-purple-50/60 dark:bg-purple-950/20 p-3 border border-purple-200/60 dark:border-purple-800/40">
          <div className="flex items-center gap-1.5 text-purple-700 dark:text-purple-300 text-xs font-medium">
            <CheckCircle2 className="h-3.5 w-3.5" />
            <span>Outcomes</span>
          </div>
          <div className="mt-1 text-xl sm:text-2xl font-bold text-purple-900 dark:text-purple-100">
            {total_outcomes}
          </div>
          <div className="text-[10px] text-purple-600/80 dark:text-purple-400 mt-0.5">
            Repaired / Wastage
          </div>
        </div>

        {/* Actioned */}
        <div className="rounded-lg bg-emerald-50/60 dark:bg-emerald-950/20 p-3 border border-emerald-200/60 dark:border-emerald-800/40 col-span-2 sm:col-span-1">
          <div className="flex items-center gap-1.5 text-emerald-700 dark:text-emerald-300 text-xs font-medium">
            <Award className="h-3.5 w-3.5" />
            <span>Actioned</span>
          </div>
          <div className="mt-1 text-xl sm:text-2xl font-bold text-emerald-900 dark:text-emerald-100">
            {total_actioned}
          </div>
          <div className="text-[10px] text-emerald-600/80 dark:text-emerald-400 mt-0.5">
            By RM decision
          </div>
        </div>
      </div>

      {/* Per-Item Reconciliation Breakdown Table */}
      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-left text-xs sm:text-sm">
          <thead className="bg-slate-50 text-slate-500 dark:bg-slate-800/40 dark:text-slate-400 uppercase text-[11px] font-semibold">
            <tr>
              <th className="py-2 px-3 rounded-l"># Line</th>
              <th className="py-2 px-3">Item Name</th>
              <th className="py-2 px-3 text-right">Counted</th>
              <th className="py-2 px-3 text-right">In Store</th>
              <th className="py-2 px-3 text-right">At Dept</th>
              <th className="py-2 px-3 text-right">Outcomes</th>
              <th className="py-2 px-3 text-right">Actioned</th>
              <th className="py-2 px-3 text-center rounded-r">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {items.map((it) => (
              <tr key={it.gs_item_id} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/30">
                <td className="py-2.5 px-3 font-mono text-xs text-slate-500">#{it.line_no}</td>
                <td className="py-2.5 px-3 font-medium text-slate-900 dark:text-slate-100">
                  <div>{it.item_name}</div>
                  {it.sku_code && (
                    <div className="text-[10px] text-slate-400 font-mono">{it.sku_code}</div>
                  )}
                </td>
                <td className="py-2.5 px-3 text-right font-semibold text-slate-900 dark:text-slate-100">
                  {it.counted_qty}
                </td>
                <td className="py-2.5 px-3 text-right text-blue-600 dark:text-blue-400 font-medium">
                  {it.in_store_qty}
                  {it.planned_qty ? (
                    <div className="text-[10px] font-normal text-amber-600 dark:text-amber-400">
                      {it.planned_qty} planned
                    </div>
                  ) : null}
                </td>
                <td className="py-2.5 px-3 text-right text-amber-600 dark:text-amber-400 font-medium">
                  {it.at_departments_qty}
                </td>
                <td className="py-2.5 px-3 text-right text-purple-600 dark:text-purple-400 font-medium">
                  {it.outcome_heads_qty}
                </td>
                <td className="py-2.5 px-3 text-right text-emerald-600 dark:text-emerald-400 font-medium">
                  {it.actioned_qty}
                </td>
                <td className="py-2.5 px-3 text-center">
                  {it.is_conserved ? (
                    <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-700 bg-emerald-50 dark:bg-emerald-950/40 dark:text-emerald-400 px-2 py-0.5 rounded-full">
                      <ShieldCheck className="h-3 w-3" />
                      100% Conserved
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-rose-700 bg-rose-50 dark:bg-rose-950/40 dark:text-rose-400 px-2 py-0.5 rounded-full">
                      <AlertTriangle className="h-3 w-3" />
                      Mismatch
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
