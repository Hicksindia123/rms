import React, { useState, useEffect } from 'react';
import { CheckCircle2, Building2, Search, RefreshCw, Printer, Clock } from 'lucide-react';
import type { ReceivingQueueItemOut, DepartmentRoutingOut } from './types';
import { departmentRoutingApi, routingErrorMessage } from './api';
import { DepartmentReceiveModal } from './DepartmentReceiveModal';

interface DepartmentReceivingQueuePageProps {
  onPrintRoutingNote?: (routingId: string) => void;
  onOpenPrint?: (routingId: string) => void;
  onOpenGs: (gsId: string) => void;
}

export const DepartmentReceivingQueuePage: React.FC<DepartmentReceivingQueuePageProps> = ({
  onPrintRoutingNote,
  onOpenPrint,
  onOpenGs,
}) => {
  const handlePrint = (routingId: string) => {
    if (onOpenPrint) onOpenPrint(routingId);
    else if (onPrintRoutingNote) onPrintRoutingNote(routingId);
  };
  const [queue, setQueue] = useState<ReceivingQueueItemOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [actionError, setActionError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');

  // Receiving modal state
  const [activeRoutingToReceive, setActiveRoutingToReceive] = useState<DepartmentRoutingOut | null>(
    null,
  );
  const [loadingRoutingDetail, setLoadingRoutingDetail] = useState(false);

  useEffect(() => {
    let active = true;
    departmentRoutingApi
      .getReceivingQueue()
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

  const handleOpenReceive = (routingId: string) => {
    setLoadingRoutingDetail(true);
    setActionError(null);
    departmentRoutingApi
      .getRouting(routingId)
      .then(setActiveRoutingToReceive)
      .catch((err: unknown) => {
        setActionError(routingErrorMessage(err));
      })
      .finally(() => {
        setLoadingRoutingDetail(false);
      });
  };

  const term = searchTerm.toLowerCase();
  const filteredQueue = queue.filter(
    (item) =>
      item.routing_no.toLowerCase().includes(term) ||
      item.gs_no.toLowerCase().includes(term) ||
      item.department_label.toLowerCase().includes(term),
  );

  return (
    <div className="space-y-6 p-4 sm:p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <div className="rounded-lg bg-emerald-50 p-2 dark:bg-emerald-950/50 text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="h-5 w-5" />
            </div>
            <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
              Department Receiving Queue
            </h1>
          </div>
          <p className="text-xs sm:text-sm text-slate-500 dark:text-slate-400 mt-1">
            Inward verifier receives processed goods back from departments into outcome heads
            (Repaired, Wastage, Re-Route).
          </p>
        </div>

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

      {/* Search */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
          <input
            type="text"
            placeholder="Search by DIN, GS number or department..."
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

      {/* Main List */}
      {loading ? (
        <div className="rounded-xl border border-slate-200 bg-white p-12 text-center text-slate-400 dark:border-slate-800 dark:bg-slate-900 animate-pulse">
          Loading department routings awaiting receipt...
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
          <CheckCircle2 className="mx-auto h-10 w-10 text-emerald-400 mb-2" />
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            All Department Routings Received
          </h3>
          <p className="text-xs text-slate-400 mt-1">
            There are currently no open or partially received department routing notes.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {filteredQueue.map((item) => (
            <div
              key={item.routing_id}
              className="rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900 p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4"
            >
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm font-bold text-slate-900 dark:text-slate-100">
                    {item.routing_no}
                  </span>
                  <span className="text-slate-300 dark:text-slate-700">•</span>
                  <button
                    type="button"
                    onClick={() => {
                      onOpenGs(item.gs_id);
                    }}
                    className="font-mono text-xs font-semibold text-indigo-600 hover:underline dark:text-indigo-400"
                  >
                    {item.gs_no}
                  </button>
                  <span className="inline-flex items-center gap-1 rounded bg-slate-100 dark:bg-slate-800 px-2 py-0.5 text-xs font-semibold text-slate-700 dark:text-slate-300">
                    <Building2 className="h-3 w-3 text-slate-500" />
                    {item.department_label} ({item.department_code})
                  </span>
                  {item.status === 'PARTIALLY_RECEIVED' ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-0.5 text-[11px] font-semibold text-amber-700 dark:bg-amber-950/40 dark:text-amber-400 border border-amber-200 dark:border-amber-800">
                      <Clock className="h-3 w-3" />
                      Partially Received
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2.5 py-0.5 text-[11px] font-semibold text-blue-700 dark:bg-blue-950/40 dark:text-blue-400 border border-blue-200 dark:border-blue-800">
                      <Clock className="h-3 w-3" />
                      Dispatched
                    </span>
                  )}
                </div>
                <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                  Dispatched on {new Date(item.dispatched_at).toLocaleString()}
                  {item.dispatched_by_name && ` by ${item.dispatched_by_name}`}
                </div>
              </div>

              {/* Quantities summary */}
              <div className="flex items-center gap-4 text-xs">
                <div className="text-right">
                  <div className="font-semibold text-slate-900 dark:text-slate-100">
                    {item.total_received} / {item.total_sent} pcs Received
                  </div>
                  <div className="text-amber-600 dark:text-amber-400 font-bold">
                    {item.total_pending} pcs pending receipt
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      handlePrint(item.routing_id);
                    }}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
                    title="Print DIN"
                  >
                    <Printer className="h-3.5 w-3.5" />
                    <span>DIN</span>
                  </button>

                  <button
                    type="button"
                    disabled={loadingRoutingDetail}
                    onClick={() => {
                      handleOpenReceive(item.routing_id);
                    }}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-emerald-700"
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    <span>Receive Goods</span>
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Receive Modal */}
      {activeRoutingToReceive && (
        <DepartmentReceiveModal
          routing={activeRoutingToReceive}
          onClose={() => {
            setActiveRoutingToReceive(null);
          }}
          onSuccess={() => {
            setActiveRoutingToReceive(null);
            reloadQueue();
          }}
        />
      )}
    </div>
  );
};
