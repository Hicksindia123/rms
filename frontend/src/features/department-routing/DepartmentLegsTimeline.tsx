import React, { useState } from 'react';
import {
  Building2,
  ChevronDown,
  ChevronRight,
  Printer,
  CheckCircle2,
  AlertCircle,
  RotateCcw,
  Clock,
} from 'lucide-react';
import type { DepartmentLegOut } from './types';

interface DepartmentLegsTimelineProps {
  legs: DepartmentLegOut[];
  onPrintRoutingNote?: (routingId: string) => void;
  onReceiveRouting?: (routingId: string) => void;
  canReceive?: boolean;
}

export const DepartmentLegsTimeline: React.FC<DepartmentLegsTimelineProps> = ({
  legs,
  onPrintRoutingNote,
  onReceiveRouting,
  canReceive = false,
}) => {
  const [expandedLegs, setExpandedLegs] = useState<Record<string, boolean>>({});

  const toggleLeg = (routingId: string) => {
    setExpandedLegs((prev) => ({ ...prev, [routingId]: !prev[routingId] }));
  };

  if (legs.length === 0) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6 text-center text-slate-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
        <Building2 className="mx-auto h-8 w-8 text-slate-400 mb-2" />
        <p className="text-sm font-medium">No department legs dispatched yet</p>
        <p className="text-xs text-slate-400 mt-1">
          Dispatched legs to repair, mercury extraction or other departments will appear here.
        </p>
      </div>
    );
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'COMPLETED':
        return (
          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800">
            <CheckCircle2 className="h-3 w-3" />
            Completed
          </span>
        );
      case 'PARTIALLY_RECEIVED':
        return (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-700 dark:bg-amber-950/40 dark:text-amber-400 border border-amber-200 dark:border-amber-800">
            <Clock className="h-3 w-3" />
            Partially Received
          </span>
        );
      case 'DISPATCHED':
      default:
        return (
          <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-xs font-semibold text-blue-700 dark:bg-blue-950/40 dark:text-blue-400 border border-blue-200 dark:border-blue-800">
            <Building2 className="h-3 w-3" />
            Dispatched
          </span>
        );
    }
  };

  return (
    <div className="space-y-4">
      {legs.map((leg) => {
        const isExpanded = expandedLegs[leg.routing_id] ?? true;
        const pending = leg.qty_pending;

        return (
          <div
            key={leg.routing_id}
            className="rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900 overflow-hidden"
          >
            {/* Header */}
            <div className="p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-100 dark:border-slate-800/80 bg-slate-50/50 dark:bg-slate-800/20">
              <div className="flex items-start gap-3">
                <button
                  type="button"
                  onClick={() => {
                    toggleLeg(leg.routing_id);
                  }}
                  className="mt-0.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                  aria-label="Toggle details"
                >
                  {isExpanded ? (
                    <ChevronDown className="h-4 w-4" />
                  ) : (
                    <ChevronRight className="h-4 w-4" />
                  )}
                </button>
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs font-bold text-slate-900 dark:text-slate-100">
                      {leg.routing_no}
                    </span>
                    <span className="text-xs font-medium text-slate-400">•</span>
                    <span className="inline-flex items-center gap-1 rounded bg-slate-100 dark:bg-slate-800 px-2 py-0.5 text-xs font-semibold text-slate-700 dark:text-slate-300">
                      {leg.department_label} ({leg.department_code})
                    </span>
                    {getStatusBadge(leg.status)}
                  </div>
                  <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                    Dispatched on {new Date(leg.dispatched_at).toLocaleString()}
                    {leg.dispatched_by_name && ` by ${leg.dispatched_by_name}`}
                  </div>
                </div>
              </div>

              {/* Progress & Actions */}
              <div className="flex items-center gap-3 self-end sm:self-center">
                <div className="text-right text-xs">
                  <div className="font-semibold text-slate-900 dark:text-slate-100">
                    {leg.qty_received} / {leg.qty_sent} Received
                  </div>
                  {pending > 0 ? (
                    <div className="text-amber-600 dark:text-amber-400 font-medium">
                      {pending} pending
                    </div>
                  ) : (
                    <div className="text-emerald-600 dark:text-emerald-400 font-medium">
                      All received
                    </div>
                  )}
                </div>

                {onPrintRoutingNote && (
                  <button
                    type="button"
                    onClick={() => {
                      onPrintRoutingNote(leg.routing_id);
                    }}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
                    title="Print Department Issue Note (DIN)"
                  >
                    <Printer className="h-3.5 w-3.5" />
                    <span>Print DIN</span>
                  </button>
                )}

                {canReceive && pending > 0 && onReceiveRouting && (
                  <button
                    type="button"
                    onClick={() => {
                      onReceiveRouting(leg.routing_id);
                    }}
                    className="inline-flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-indigo-700"
                  >
                    <span>Receive Items</span>
                  </button>
                )}
              </div>
            </div>

            {/* Expanded Body: Routing Lines & Receipts */}
            {isExpanded && (
              <div className="p-4 sm:p-5 space-y-4">
                {/* Dispatched Lines */}
                <div>
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-2">
                    Dispatched Line Items
                  </h4>
                  <div className="overflow-x-auto rounded-lg border border-slate-100 dark:border-slate-800">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-slate-50 dark:bg-slate-800/40 text-slate-500 font-medium">
                        <tr>
                          <th className="py-2 px-3">Item</th>
                          <th className="py-2 px-3">Bucket</th>
                          <th className="py-2 px-3 text-right">Sent</th>
                          <th className="py-2 px-3 text-right">Received</th>
                          <th className="py-2 px-3 text-right">Pending</th>
                          <th className="py-2 px-3">Notes</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                        {leg.lines.map((ln) => (
                          <tr key={ln.id}>
                            <td className="py-2 px-3 font-medium text-slate-900 dark:text-slate-100">
                              #{ln.line_no} {ln.item_name}
                            </td>
                            <td className="py-2 px-3 text-slate-500">
                              {ln.source_bucket_label || '—'}
                            </td>
                            <td className="py-2 px-3 text-right font-semibold text-slate-900 dark:text-slate-100">
                              {ln.qty_sent}
                            </td>
                            <td className="py-2 px-3 text-right text-emerald-600 font-medium">
                              {ln.qty_received}
                            </td>
                            <td className="py-2 px-3 text-right text-amber-600 font-medium">
                              {ln.qty_pending}
                            </td>
                            <td className="py-2 px-3 text-slate-400 text-[11px]">
                              {ln.notes || '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Receipts Leg */}
                {leg.receipts.length > 0 && (
                  <div>
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-2">
                      Department Receipts & Outcomes
                    </h4>
                    <div className="space-y-2">
                      {leg.receipts.map((rc) => (
                        <div
                          key={rc.id}
                          className="rounded-lg border border-slate-200/80 bg-slate-50/40 p-3 dark:border-slate-800 dark:bg-slate-800/40 text-xs"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-slate-200/40 dark:border-slate-700/40">
                            <div className="flex items-center gap-2">
                              <span className="font-mono font-bold text-slate-800 dark:text-slate-200">
                                {rc.receipt_no}
                              </span>
                              <span className="text-slate-400">•</span>
                              <span className="text-slate-500">
                                Received {new Date(rc.received_at).toLocaleString()}
                                {rc.received_by_name && ` by ${rc.received_by_name}`}
                              </span>
                            </div>
                            {rc.remarks && (
                              <span className="text-slate-500 italic text-[11px]">
                                "{rc.remarks}"
                              </span>
                            )}
                          </div>

                          {/* Outcome lines */}
                          <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
                            {rc.lines.map((ol) => (
                              <div
                                key={ol.id}
                                className="flex items-center justify-between rounded border bg-white p-2 dark:bg-slate-900 border-slate-200 dark:border-slate-800"
                              >
                                <div className="flex items-center gap-1.5">
                                  {ol.is_wastage ? (
                                    <span className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-semibold bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-400 border border-rose-200 dark:border-rose-800">
                                      <AlertCircle className="h-3 w-3" />
                                      Wastage
                                    </span>
                                  ) : ol.returns_to_routing ? (
                                    <span className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-semibold bg-purple-50 text-purple-700 dark:bg-purple-950/40 dark:text-purple-400 border border-purple-200 dark:border-purple-800">
                                      <RotateCcw className="h-3 w-3" />
                                      Re-Route
                                    </span>
                                  ) : (
                                    <span className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-semibold bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800">
                                      <CheckCircle2 className="h-3 w-3" />
                                      {ol.outcome_label}
                                    </span>
                                  )}
                                  <span className="font-medium text-slate-700 dark:text-slate-300">
                                    {ol.outcome_label}
                                  </span>
                                  {ol.condition_label ? (
                                    <span className="text-slate-500 dark:text-slate-400">
                                      → {ol.condition_label}
                                    </span>
                                  ) : null}
                                </div>
                                <span className="font-bold text-slate-900 dark:text-slate-100">
                                  {ol.quantity} pcs
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};
