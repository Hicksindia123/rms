/**
 * Phase P7 (DEC-67; Q29): "Department Routing" for the Intermediate Store users. One row per goods
 * slip (party-wise) with the progress of each store the user sees; a store user sees only its own
 * stores. "To route" lists the goods slips with goods still to route; "All" every goods slip on
 * the stores. A row opens the routing view of the goods slip.
 */
import React, { useEffect, useState } from 'react';
import { ChevronRight, RefreshCw } from 'lucide-react';

import { Button, EmptyState, ErrorState, LoadingState } from '@/components/ui';
import { PageHeader } from '@/components/erp';
import { toApiError, type ApiError } from '@/lib/api/client';
import { formatDateTime } from '@/features/goods-slips/format';
import { StatusChip } from '@/features/goods-slips/display';

import { departmentRoutingApi } from './api';
import { StoreProgressChip } from './storeRoutingDisplay';
import type { StoreRoutingQueueRow } from './types';

interface Props {
  onOpenGs: (gsId: string) => void;
}

type Tab = 'pending' | 'all';

export const StoreRoutingQueuePage: React.FC<Props> = ({ onOpenGs }) => {
  const [tab, setTab] = useState<Tab>('pending');
  const [rows, setRows] = useState<StoreRoutingQueueRow[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  const [reloadKey, setReloadKey] = useState(0);

  // State changes only in the request callbacks (the triggers set `loading`).
  useEffect(() => {
    let active = true;
    departmentRoutingApi
      .getStoreQueue(tab === 'pending')
      .then((data) => {
        if (active) {
          setRows(data);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (active) setError(toApiError(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [tab, reloadKey]);

  const load = () => {
    setLoading(true);
    setReloadKey((k) => k + 1);
  };

  const tabButton = (value: Tab, label: string) => (
    <button
      type="button"
      aria-pressed={tab === value}
      onClick={() => {
        if (value !== tab) {
          setLoading(true);
          setTab(value);
        }
      }}
      className={`min-h-[44px] flex-1 rounded-lg px-4 text-sm font-semibold sm:flex-none ${
        tab === value
          ? 'bg-indigo-600 text-white'
          : 'border border-slate-300 bg-white text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200'
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6" data-testid="store-routing-queue">
      <PageHeader
        title="Department Routing"
        subtitle="Goods slips acknowledged by your Intermediate Store. Route each condition to a department; saving issues the goods (DIN)."
        actions={
          <Button type="button" variant="outline" className="min-h-[44px]" onClick={load}>
            <RefreshCw className="h-4 w-4" aria-hidden="true" /> Refresh
          </Button>
        }
      />
      <div className="flex gap-2" role="group" aria-label="Which goods slips">
        {tabButton('pending', 'To route')}
        {tabButton('all', 'All on stores')}
      </div>

      {loading ? (
        <LoadingState label="Loading goods slips…" />
      ) : error ? (
        <ErrorState error={error} onRetry={load} title="Could not load the routing queue" />
      ) : !rows || rows.length === 0 ? (
        <EmptyState
          title={tab === 'pending' ? 'Nothing to route' : 'No goods slips on your stores'}
          {...(tab === 'pending'
            ? {
                hint: 'Goods slips appear here once your store has acknowledged their transfer slip.',
              }
            : {})}
        />
      ) : (
        <ul className="m-0 list-none space-y-3 p-0" aria-label="Goods slips">
          {rows.map((r) => (
            <li key={r.gs_id}>
              <button
                type="button"
                onClick={() => {
                  onOpenGs(r.gs_id);
                }}
                className="flex min-h-[44px] w-full items-center gap-3 rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm hover:border-indigo-300 dark:border-slate-800 dark:bg-slate-900"
              >
                <div className="min-w-0 flex-1 space-y-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-slate-900 dark:text-slate-100">
                      {r.gs_no}
                    </span>
                    <StatusChip status={r.status} />
                  </div>
                  <div className="break-words text-sm text-slate-600 dark:text-slate-300">
                    {r.party_name ?? '—'}
                    {r.station_name ? ` · ${r.station_name}` : ''}
                  </div>
                  {r.since ? (
                    <div className="text-xs text-slate-500 dark:text-slate-400">
                      Acknowledged {formatDateTime(r.since)}
                    </div>
                  ) : null}
                  <div className="flex flex-wrap gap-1.5">
                    {r.stores.map((p) => (
                      <StoreProgressChip key={p.store_id} p={p} />
                    ))}
                  </div>
                </div>
                <ChevronRight className="h-5 w-5 shrink-0 text-slate-400" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};
