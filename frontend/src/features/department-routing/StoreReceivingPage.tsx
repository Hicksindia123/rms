/**
 * Phase P8 (DEC-68): "Receive from Departments" for the Intermediate Store users. One card per goods
 * slip (party-wise) with the store's Department Issue Notes still at a department, per department:
 * sent / received / pending qty. "Receive" opens the receipt (outcome + condition after work per
 * line, partial receipts allowed); the pieces go back to the store's location, or where the
 * outcome sends them. A store user sees only its own stores; `gsId` narrows the page to one GS.
 */
import React, { useEffect, useState } from 'react';
import { Building2, CheckCircle2, Printer, RefreshCw } from 'lucide-react';

import { Button, EmptyState, ErrorState, LoadingState } from '@/components/ui';
import { PageHeader } from '@/components/erp';
import { toApiError, type ApiError } from '@/lib/api/client';
import { formatDateTime } from '@/features/goods-slips/format';
import { StatusChip } from '@/features/goods-slips/display';

import { departmentRoutingApi } from './api';
import { DepartmentReceiveModal } from './DepartmentReceiveModal';
import { StoreProgressChip } from './storeRoutingDisplay';
import type { DepartmentRoutingOut, StoreReceivingDin, StoreReceivingGs } from './types';

interface Props {
  /** Only this goods slip (the My Work item of the step). */
  gsId?: string;
  onShowAll: () => void;
  onOpenGs: (gsId: string) => void;
  onOpenPrint: (routingId: string) => void;
}

export const StoreReceivingPage: React.FC<Props> = ({ gsId, onShowAll, onOpenGs, onOpenPrint }) => {
  const [rows, setRows] = useState<StoreReceivingGs[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const [opening, setOpening] = useState<string | null>(null);
  const [openError, setOpenError] = useState<ApiError | null>(null);
  const [active, setActive] = useState<DepartmentRoutingOut | null>(null);
  const [done, setDone] = useState<string | null>(null);

  // State changes only in the request callbacks (the triggers set `loading`).
  useEffect(() => {
    let alive = true;
    departmentRoutingApi
      .getStoreReceiving(gsId)
      .then((data) => {
        if (alive) {
          setRows(data);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (alive) setError(toApiError(err));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [gsId, reloadKey]);

  const load = () => {
    setLoading(true);
    setReloadKey((k) => k + 1);
  };

  const openReceive = (din: StoreReceivingDin) => {
    setOpening(din.id);
    setOpenError(null);
    setDone(null);
    departmentRoutingApi
      .getRouting(din.id)
      .then(setActive)
      .catch((err: unknown) => {
        setOpenError(toApiError(err));
      })
      .finally(() => {
        setOpening(null);
      });
  };

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6" data-testid="store-receiving">
      <PageHeader
        title="Receive from Departments"
        subtitle="Goods your Intermediate Store sent to departments. Record what came back, the outcome and the condition; partial receipts are allowed."
        actions={
          <Button type="button" variant="outline" className="min-h-[44px]" onClick={load}>
            <RefreshCw className="h-4 w-4" aria-hidden="true" /> Refresh
          </Button>
        }
      />
      {gsId ? (
        <Button type="button" variant="outline" className="min-h-[44px]" onClick={onShowAll}>
          Show all goods slips
        </Button>
      ) : null}

      {done ? (
        <div
          role="status"
          className="flex items-start justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm font-medium text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300"
        >
          <span className="break-words">{done}</span>
          <button
            type="button"
            aria-label="Dismiss"
            onClick={() => {
              setDone(null);
            }}
            className="min-h-[44px] min-w-[44px] rounded-lg hover:bg-emerald-100 dark:hover:bg-emerald-900/40"
          >
            ✕
          </button>
        </div>
      ) : null}
      {openError ? (
        <ErrorState error={openError} title="Could not open the Department Issue Note" />
      ) : null}

      {loading ? (
        <LoadingState label="Loading goods at departments…" />
      ) : error ? (
        <ErrorState error={error} onRetry={load} title="Could not load the receiving queue" />
      ) : !rows || rows.length === 0 ? (
        <EmptyState
          title="Nothing at the departments"
          hint="Goods slips appear here when your store has routed goods to a department."
        />
      ) : (
        <ul className="m-0 list-none space-y-3 p-0" aria-label="Goods slips">
          {rows.map((r) => (
            <li
              key={r.gs_id}
              className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900"
            >
              <div className="space-y-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      onOpenGs(r.gs_id);
                    }}
                    className="min-h-[44px] font-semibold text-indigo-700 hover:underline dark:text-indigo-300"
                  >
                    {r.gs_no}
                  </button>
                  <StatusChip status={r.status} />
                </div>
                <div className="break-words text-sm text-slate-600 dark:text-slate-300">
                  {r.party_name ?? '—'}
                  {r.station_name ? ` · ${r.station_name}` : ''}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {r.stores.map((p) => (
                    <StoreProgressChip key={p.store_id} p={p} />
                  ))}
                </div>
              </div>
              <ul className="m-0 list-none space-y-2 p-0" aria-label={`Issue notes of ${r.gs_no}`}>
                {r.dins.map((d) => (
                  <li
                    key={d.id}
                    className="flex flex-col gap-3 rounded-lg bg-slate-50 p-3 sm:flex-row sm:items-center sm:justify-between dark:bg-slate-800/40"
                  >
                    <div className="min-w-0 space-y-0.5">
                      <div className="flex flex-wrap items-center gap-2 text-sm">
                        <Building2 className="h-4 w-4 text-slate-500" aria-hidden="true" />
                        <span className="font-semibold text-slate-900 dark:text-slate-100">
                          {d.department_label}
                        </span>
                        <span className="font-mono text-xs text-slate-500">{d.routing_no}</span>
                        <span className="text-xs text-slate-500">{d.store_code}</span>
                      </div>
                      <div className="text-xs text-slate-600 dark:text-slate-300">
                        Sent {d.qty_sent} · Received {d.qty_received} ·{' '}
                        <span className="font-semibold text-amber-700 dark:text-amber-400">
                          Pending {d.qty_pending}
                        </span>
                      </div>
                      <div className="text-xs text-slate-500 dark:text-slate-400">
                        Issued {formatDateTime(d.dispatched_at)}
                        {d.dispatched_by_name ? ` by ${d.dispatched_by_name}` : ''}
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        className="min-h-[44px] flex-1 sm:flex-none"
                        onClick={() => {
                          onOpenPrint(d.id);
                        }}
                      >
                        <Printer className="h-4 w-4" aria-hidden="true" /> DIN
                      </Button>
                      {d.is_mine ? (
                        <Button
                          type="button"
                          className="min-h-[44px] flex-1 sm:flex-none"
                          disabled={opening !== null}
                          onClick={() => {
                            openReceive(d);
                          }}
                        >
                          <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                          {opening === d.id ? 'Opening…' : 'Receive'}
                        </Button>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}

      {active ? (
        <DepartmentReceiveModal
          routing={active}
          storeMode
          onClose={() => {
            setActive(null);
          }}
          onSuccess={() => {
            setDone(`Receipt recorded for ${active.routing_no} (${active.department_label}).`);
            setActive(null);
            load();
          }}
        />
      ) : null}
    </div>
  );
};
