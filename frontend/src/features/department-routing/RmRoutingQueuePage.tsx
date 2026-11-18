import React, { useState, useEffect } from 'react';
import {
  Building2,
  Search,
  ShieldCheck,
  Send,
  Eye,
  RefreshCw,
  Store,
  Clock,
  ListChecks,
} from 'lucide-react';
import type { RmRoutingQueueItemOut, GsRoutingState } from './types';
import { departmentRoutingApi, routingErrorMessage } from './api';
import { RmRoutingPlanModal } from './RmRoutingPlanModal';
import { DepartmentReconciliationPanel } from './DepartmentReconciliationPanel';
import type { GsReconciliationOut } from './types';

interface RmRoutingQueuePageProps {
  /** T4: department_routing/create — the RM plans the routing (DEC-55). */
  canPlan: boolean;
  onOpenGs: (gsId: string) => void;
  onOpenPrint?: (routingId: string) => void;
  /** Change plan Phase 7 (AMD-16): open the RM final actions of a held GS. */
  onOpenFinalActions?: (gsId: string) => void;
}

export const RmRoutingQueuePage: React.FC<RmRoutingQueuePageProps> = ({
  canPlan,
  onOpenGs,
  onOpenFinalActions,
}) => {
  const [queue, setQueue] = useState<RmRoutingQueueItemOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [searchTerm, setSearchTerm] = useState('');

  // Dispatch modal state
  const [dispatchModalState, setDispatchModalState] = useState<GsRoutingState | null>(null);
  const [loadingDispatchGs, setLoadingDispatchGs] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Selected GS for reconciliation view
  const [selectedReconGsId, setSelectedReconGsId] = useState<string | null>(null);
  const [reconData, setReconData] = useState<GsReconciliationOut | null>(null);
  const [loadingRecon, setLoadingRecon] = useState(false);
  const [reconError, setReconError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    departmentRoutingApi
      .getRmRoutingQueue()
      .then((data) => {
        if (!active) return;
        setQueue(data);
        setError(null);
      })
      .catch((err: unknown) => {
        if (active) setError(routingErrorMessage(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [reloadKey]);

  const reloadQueue = () => {
    setLoading(true);
    setReloadKey((k) => k + 1);
  };

  const handleOpenDispatch = (gsId: string) => {
    setLoadingDispatchGs(true);
    setActionError(null);
    departmentRoutingApi
      .getGsRoutingState(gsId)
      .then(setDispatchModalState)
      .catch((err: unknown) => {
        setActionError(routingErrorMessage(err));
      })
      .finally(() => {
        setLoadingDispatchGs(false);
      });
  };

  const loadReconciliation = (gsId: string) => {
    setLoadingRecon(true);
    setReconError(null);
    departmentRoutingApi
      .getGsReconciliation(gsId)
      .then(setReconData)
      .catch((err: unknown) => {
        setReconData(null);
        setReconError(routingErrorMessage(err));
      })
      .finally(() => {
        setLoadingRecon(false);
      });
  };

  const handleToggleReconciliation = (gsId: string) => {
    if (selectedReconGsId === gsId) {
      setSelectedReconGsId(null);
      setReconData(null);
      setReconError(null);
      return;
    }
    setSelectedReconGsId(gsId);
    setReconData(null);
    loadReconciliation(gsId);
  };

  const term = searchTerm.toLowerCase();
  const filteredQueue = queue.filter(
    (item) =>
      item.gs_no.toLowerCase().includes(term) ||
      (item.party_name ?? '').toLowerCase().includes(term),
  );

  return (
    <div className="space-y-6 p-4 sm:p-6 max-w-7xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <div className="rounded-lg bg-indigo-50 p-2 dark:bg-indigo-950/50 text-indigo-600 dark:text-indigo-400">
              <Building2 className="h-5 w-5" />
            </div>
            <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
              RM Department Routing Queue
            </h1>
          </div>
          <p className="text-xs sm:text-sm text-slate-500 dark:text-slate-400 mt-1">
            Goods slips held at the intermediate store: plan where each condition goes. The Store
            Manager issues the planned pieces to the departments.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={reloadQueue}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Search and Filters */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
          <input
            type="text"
            placeholder="Search by GS number or party name..."
            value={searchTerm}
            onChange={(e) => {
              setSearchTerm(e.target.value);
            }}
            className="w-full rounded-lg border border-slate-300 bg-white pl-9 pr-4 py-2 text-xs text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
          />
        </div>
      </div>

      {actionError && (
        <div
          role="alert"
          className="flex items-start justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-xs font-medium text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-400"
        >
          <span className="break-words">{actionError}</span>
          <button
            type="button"
            aria-label="Dismiss error"
            onClick={() => {
              setActionError(null);
            }}
            className="min-h-[44px] min-w-[44px] rounded-lg text-rose-500 hover:bg-rose-100 dark:hover:bg-rose-900/40"
          >
            ✕
          </button>
        </div>
      )}

      {/* Main Queue List */}
      {loading ? (
        <div className="rounded-xl border border-slate-200 bg-white p-12 text-center text-slate-400 dark:border-slate-800 dark:bg-slate-900 animate-pulse">
          Loading intermediate store routing queue...
        </div>
      ) : error ? (
        <div
          role="alert"
          className="flex flex-col items-center gap-3 rounded-xl border border-rose-200 bg-rose-50 p-6 text-center text-xs font-semibold text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-400"
        >
          <span className="break-words">{error}</span>
          <button
            type="button"
            onClick={reloadQueue}
            className="min-h-[44px] rounded-lg border border-rose-300 bg-white px-4 text-xs font-semibold text-rose-700 hover:bg-rose-100 dark:border-rose-800 dark:bg-rose-950 dark:text-rose-300"
          >
            Retry
          </button>
        </div>
      ) : filteredQueue.length === 0 ? (
        <div className="rounded-xl border border-slate-200 bg-white p-12 text-center text-slate-500 dark:border-slate-800 dark:bg-slate-900">
          <Store className="mx-auto h-10 w-10 text-slate-400 mb-2" />
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            No Goods Slips Awaiting Routing
          </h3>
          <p className="text-xs text-slate-400 mt-1">
            Goods slips approved by RM and accepted by the intermediate store will appear here for
            department dispatch.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {filteredQueue.map((item) => (
            <div
              key={item.gs_id}
              className="rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900 overflow-hidden"
            >
              <div className="p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-bold text-slate-900 dark:text-slate-100">
                      {item.gs_no}
                    </span>
                    <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-700 dark:bg-blue-950/40 dark:text-blue-400 border border-blue-200 dark:border-blue-800">
                      <Store className="h-3 w-3" />
                      Held at Intermediate Store
                    </span>
                    {item.active_routings_count > 0 && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-700 dark:bg-amber-950/40 dark:text-amber-400 border border-amber-200 dark:border-amber-800">
                        <Clock className="h-3 w-3" />
                        {item.active_routings_count} active routing note
                        {item.active_routings_count > 1 ? 's' : ''}
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                    Party:{' '}
                    <span className="font-medium text-slate-700 dark:text-slate-300">
                      {item.party_name || '—'}
                    </span>
                    {' • '}Held since {new Date(item.held_since).toLocaleDateString()}
                  </div>
                  {item.planned_qty ? (
                    <div className="text-xs text-amber-700 dark:text-amber-400 mt-1">
                      {item.planned_qty} pcs planned, waiting for the store issue
                    </div>
                  ) : null}
                </div>

                {/* Quantities breakdown */}
                <div className="grid grid-cols-3 gap-2 sm:gap-4 text-center text-xs">
                  <div className="rounded-lg bg-slate-50 dark:bg-slate-800/40 p-2 sm:px-3">
                    <span className="text-[10px] text-slate-400 block font-medium">Counted</span>
                    <span className="font-bold text-slate-900 dark:text-slate-100">
                      {item.total_counted_qty}
                    </span>
                  </div>
                  <div className="rounded-lg bg-blue-50/60 dark:bg-blue-950/30 p-2 sm:px-3">
                    <span className="text-[10px] text-blue-600 block font-medium">In Store</span>
                    <span className="font-bold text-blue-900 dark:text-blue-100">
                      {item.in_store_qty}
                    </span>
                  </div>
                  <div className="rounded-lg bg-amber-50/60 dark:bg-amber-950/30 p-2 sm:px-3">
                    <span className="text-[10px] text-amber-600 block font-medium">At Dept</span>
                    <span className="font-bold text-amber-900 dark:text-amber-100">
                      {item.at_departments_qty}
                    </span>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2 self-end sm:self-center">
                  <button
                    type="button"
                    onClick={() => {
                      handleToggleReconciliation(item.gs_id);
                    }}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
                  >
                    <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" />
                    <span>
                      {selectedReconGsId === item.gs_id ? 'Hide Recon' : 'Reconciliation'}
                    </span>
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      onOpenGs(item.gs_id);
                    }}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
                  >
                    <Eye className="h-3.5 w-3.5" />
                    <span>GS Details</span>
                  </button>

                  {onOpenFinalActions ? (
                    <button
                      type="button"
                      onClick={() => {
                        onOpenFinalActions(item.gs_id);
                      }}
                      className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
                    >
                      <ListChecks className="h-3.5 w-3.5 text-indigo-600" />
                      <span>Final Actions</span>
                    </button>
                  ) : null}

                  {canPlan ? (
                    <button
                      type="button"
                      disabled={loadingDispatchGs}
                      onClick={() => {
                        handleOpenDispatch(item.gs_id);
                      }}
                      className="min-h-[44px] inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <Send className="h-3.5 w-3.5" />
                      <span>Plan Routing</span>
                    </button>
                  ) : null}
                </div>
              </div>

              {/* Inline Reconciliation Panel if opened */}
              {selectedReconGsId === item.gs_id && (
                <div className="p-4 sm:p-5 border-t border-slate-100 dark:border-slate-800 bg-slate-50/30 dark:bg-slate-900/40">
                  <DepartmentReconciliationPanel
                    reconciliation={reconData}
                    loading={loadingRecon}
                    error={reconError}
                    onRefresh={() => {
                      loadReconciliation(item.gs_id);
                    }}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Dispatch Modal */}
      {dispatchModalState && (
        <RmRoutingPlanModal
          state={dispatchModalState}
          canPlan={canPlan}
          onClose={() => {
            setDispatchModalState(null);
          }}
          onSuccess={() => {
            setDispatchModalState(null);
            reloadQueue();
          }}
        />
      )}
    </div>
  );
};
