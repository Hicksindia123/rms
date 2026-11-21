import React, { useState, useEffect } from 'react';
import { ArrowLeft, Printer } from 'lucide-react';
import type { DepartmentRoutingOut } from './types';
import { departmentRoutingApi, routingErrorMessage } from './api';

interface DepartmentIssueNotePrintPageProps {
  routingId: string;
  onBack: () => void;
}

export const DepartmentIssueNotePrintPage: React.FC<DepartmentIssueNotePrintPageProps> = ({
  routingId,
  onBack,
}) => {
  const [routing, setRouting] = useState<DepartmentRoutingOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    departmentRoutingApi
      .getRouting(routingId)
      .then((data) => {
        if (mounted) {
          setRouting(data);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (mounted) {
          setError(routingErrorMessage(err));
          setLoading(false);
        }
      });

    return () => {
      mounted = false;
    };
  }, [routingId]);

  const handlePrint = () => {
    window.print();
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="text-sm text-slate-500 animate-pulse">Loading Department Issue Note...</div>
      </div>
    );
  }

  if (error || !routing) {
    return (
      <div className="p-6 max-w-xl mx-auto text-center space-y-4">
        <div className="text-sm text-rose-600 font-medium">{error || 'Routing not found'}</div>
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-lg bg-slate-100 hover:bg-slate-200"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>Back</span>
        </button>
      </div>
    );
  }

  const totalQtySent = routing.lines.reduce((sum, l) => sum + l.qty_sent, 0);

  return (
    <div className="min-h-screen bg-slate-100 p-4 sm:p-8 dark:bg-slate-950 print:bg-white print:p-0">
      {/* Non-printed Toolbar */}
      <div className="mx-auto max-w-4xl mb-4 flex items-center justify-between print:hidden">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-slate-100"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>Back to Details</span>
        </button>

        <button
          type="button"
          onClick={handlePrint}
          className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-indigo-700"
        >
          <Printer className="h-4 w-4" />
          <span>Print Issue Note</span>
        </button>
      </div>

      {/* Printable Sheet */}
      <div className="mx-auto max-w-4xl rounded-2xl bg-white p-6 sm:p-10 shadow-lg dark:bg-slate-900 border border-slate-200 dark:border-slate-800 print:shadow-none print:border-none print:p-6 print:m-0 text-slate-900 dark:text-slate-100">
        {/* Document Header */}
        <div className="flex flex-col sm:flex-row justify-between items-start gap-4 pb-6 border-b-2 border-slate-900 dark:border-slate-100">
          <div>
            <div className="text-xs uppercase tracking-widest font-bold text-indigo-600 dark:text-indigo-400">
              Return Management System • RMS
            </div>
            <h1 className="text-2xl font-black tracking-tight mt-1">DEPARTMENT ISSUE NOTE (DIN)</h1>
            <p className="text-xs text-slate-500 mt-0.5">
              AMD-10 Internal Transfer Document • Intermediate Store to Department
            </p>
          </div>

          <div className="text-left sm:text-right space-y-1">
            <div className="font-mono text-lg font-bold text-indigo-600 dark:text-indigo-400">
              {routing.routing_no}
            </div>
            <div className="text-xs text-slate-500">
              Date:{' '}
              <span className="font-medium text-slate-800 dark:text-slate-200">
                {new Date(routing.dispatched_at).toLocaleDateString()}
              </span>
            </div>
            <div className="text-xs text-slate-500">
              Status:{' '}
              <span className="font-semibold text-slate-800 dark:text-slate-200">
                {routing.status}
              </span>
            </div>
          </div>
        </div>

        {/* Dispatch Metadata Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 py-5 border-b border-slate-200 dark:border-slate-800 text-xs">
          <div>
            <span className="text-slate-400 block font-medium">Source Location:</span>
            <span className="font-semibold text-slate-800 dark:text-slate-200">
              {routing.store_name ?? 'Intermediate Store (FUNCTIONAL)'}
            </span>
          </div>

          <div>
            <span className="text-slate-400 block font-medium">Destination Department:</span>
            <span className="font-bold text-indigo-600 dark:text-indigo-400">
              {routing.department_label} ({routing.department_code})
            </span>
            {routing.location_name ? (
              <span className="block text-[11px] text-slate-500">
                Stock location: {routing.location_name}
              </span>
            ) : null}
          </div>

          <div>
            <span className="text-slate-400 block font-medium">Goods Slip (GS) Ref:</span>
            <span className="font-mono font-semibold text-slate-800 dark:text-slate-200">
              {routing.gs_no}
            </span>
          </div>

          <div>
            <span className="text-slate-400 block font-medium">Issued By:</span>
            <span className="font-medium text-slate-800 dark:text-slate-200">
              {routing.dispatched_by_name || '—'}
            </span>
          </div>
        </div>

        {routing.remarks && (
          <div className="py-3 px-3.5 my-4 bg-slate-50 dark:bg-slate-800/40 rounded-lg text-xs italic text-slate-600 dark:text-slate-300 border border-slate-100 dark:border-slate-800">
            <span className="font-semibold not-italic">Remarks:</span> {routing.remarks}
          </div>
        )}

        {/* Lines Table */}
        <div className="mt-4">
          <table className="w-full text-left text-xs border border-slate-200 dark:border-slate-800">
            <thead className="bg-slate-50 dark:bg-slate-800/60 text-slate-600 dark:text-slate-300 font-bold uppercase text-[11px] border-b border-slate-200 dark:border-slate-800">
              <tr>
                <th className="py-2.5 px-3 w-12 text-center">#</th>
                <th className="py-2.5 px-3">Item Description</th>
                <th className="py-2.5 px-3">Source Bucket</th>
                <th className="py-2.5 px-3 text-right w-24">Qty Sent</th>
                <th className="py-2.5 px-3">Notes / Instructions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
              {routing.lines.map((ln) => (
                <tr key={ln.id}>
                  <td className="py-2.5 px-3 text-center font-mono text-slate-500">{ln.line_no}</td>
                  <td className="py-2.5 px-3 font-semibold">
                    <div>{ln.item_name}</div>
                    {ln.sku_code && (
                      <div className="font-mono text-[10px] text-slate-400">{ln.sku_code}</div>
                    )}
                  </td>
                  <td className="py-2.5 px-3 text-slate-600 dark:text-slate-300">
                    {ln.source_bucket_label || '—'}
                  </td>
                  <td className="py-2.5 px-3 text-right font-black text-sm">{ln.qty_sent}</td>
                  <td className="py-2.5 px-3 text-slate-500 italic">{ln.notes || '—'}</td>
                </tr>
              ))}
            </tbody>
            <tfoot className="bg-slate-50 dark:bg-slate-800/40 font-bold border-t-2 border-slate-900 dark:border-slate-100">
              <tr>
                <td
                  colSpan={3}
                  className="py-2.5 px-3 text-right uppercase tracking-wider text-[11px]"
                >
                  Total Quantity Dispatched:
                </td>
                <td className="py-2.5 px-3 text-right text-base text-indigo-600 dark:text-indigo-400">
                  {totalQtySent} pcs
                </td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>

        {/* Authorization Signatures */}
        <div className="grid grid-cols-2 gap-8 mt-16 pt-8 border-t border-slate-200 dark:border-slate-800 text-xs">
          <div>
            <div className="h-14 border-b border-dashed border-slate-300 dark:border-slate-700" />
            <div className="mt-2 font-bold text-slate-800 dark:text-slate-200">
              Issued By (Intermediate Store)
            </div>
            <div className="text-[11px] text-slate-400">
              Name: {routing.dispatched_by_name || '______________________'}
            </div>
            <div className="text-[11px] text-slate-400">
              Date: {new Date(routing.dispatched_at).toLocaleDateString()}
            </div>
          </div>

          <div>
            <div className="h-14 border-b border-dashed border-slate-300 dark:border-slate-700" />
            <div className="mt-2 font-bold text-slate-800 dark:text-slate-200">
              Received By ({routing.department_label} Technician)
            </div>
            <div className="text-[11px] text-slate-400">Name: ______________________</div>
            <div className="text-[11px] text-slate-400">Date: ______________________</div>
          </div>
        </div>

        {/* Footer Note */}
        <div className="mt-12 text-center text-[10px] text-slate-400 border-t border-slate-100 dark:border-slate-800 pt-3">
          This is an official stock issue note generated under Return Management System (RMS) Guard
          G-20 reconciliation guidelines.
        </div>
      </div>
    </div>
  );
};
