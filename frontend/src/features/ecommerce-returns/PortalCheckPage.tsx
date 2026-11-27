/**
 * DEC-76: Portal Check queue of the E-Commerce Executive. Returns recorded without a ticket wait
 * here (oldest first); the executive searches the order id on the platform portal and records
 * whether it shows a Free Replacement or a Refund, with the qty and a short note. The return then
 * waits for the unboxing user. DEC-51: any executive may work any return.
 */
import React, { useCallback, useState } from 'react';
import { ChevronRight, RefreshCw } from 'lucide-react';

import { PageHeader } from '@/components/erp';
import { Button, EmptyState, ErrorState, LoadingState } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { formatDate, formatDateTime } from '@/features/goods-slips/format';

import { ecomApi } from './api';
import { ResolutionModal } from './ResolutionModal';
import type { PortalCheckQueue, PortalCheckRow } from './types';

interface Props {
  canEdit: boolean;
  onOpen: (returnId: string) => void;
}

export const PortalCheckPage: React.FC<Props> = ({ canEdit, onOpen }) => {
  const fetcher = useCallback(() => ecomApi.portalChecks(), []);
  const query = useApiQuery<PortalCheckQueue>(fetcher);
  const [checking, setChecking] = useState<PortalCheckRow | null>(null);

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6" data-testid="ecom-portal-check">
      <PageHeader
        title="Portal Check"
        subtitle="Returns without a ticket: search the order id on the portal and record whether it shows a Free Replacement or a Refund."
        actions={
          <Button type="button" variant="outline" className="min-h-[44px]" onClick={query.reload}>
            <RefreshCw className="h-4 w-4" aria-hidden="true" /> Refresh
          </Button>
        }
      />
      {query.error ? (
        <ErrorState error={query.error} onRetry={query.reload} title="Could not load the returns" />
      ) : !query.data ? (
        <LoadingState label="Loading returns…" />
      ) : query.data.rows.length === 0 ? (
        <EmptyState
          title="Nothing to check"
          hint="Returns recorded at the gate without Ticket Raise appear here."
        />
      ) : (
        <ul className="m-0 list-none space-y-3 p-0" aria-label="Returns waiting for a portal check">
          {query.data.rows.map((r) => (
            <li
              key={r.return_id}
              className="space-y-2 rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900"
              data-testid={`portal-${r.return_no}`}
            >
              <button
                type="button"
                className="flex min-h-[44px] w-full items-center gap-3 border-0 bg-transparent p-0 text-left"
                onClick={() => {
                  onOpen(r.return_id);
                }}
              >
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="font-semibold">{r.return_no}</div>
                  <div className="break-words text-sm text-slate-600 dark:text-slate-300">
                    {r.platform_label} · Order {r.order_id} · {formatDate(r.entry_date)}
                  </div>
                  <div className="break-words text-sm text-slate-600 dark:text-slate-300">
                    {r.product_text} · Qty {r.qty}
                  </div>
                  {r.submitted_at ? (
                    <div className="text-xs text-slate-500">
                      Waiting since {formatDateTime(r.submitted_at)}
                    </div>
                  ) : null}
                </div>
                <ChevronRight className="h-5 w-5 shrink-0 text-slate-400" aria-hidden="true" />
              </button>
              {canEdit ? (
                <Button
                  type="button"
                  className="min-h-[44px] w-full sm:w-auto"
                  data-testid="portal-check-record"
                  onClick={() => {
                    setChecking(r);
                  }}
                >
                  Record portal check
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {checking && query.data ? (
        <ResolutionModal
          title={`Portal check · ${checking.return_no}`}
          intro={
            <p className="m-0 text-sm text-slate-600 dark:text-slate-300">
              {checking.platform_label} · Order {checking.order_id} · {checking.product_text} · Qty{' '}
              {checking.qty}
            </p>
          }
          options={query.data.resolution_options}
          maxQty={checking.qty}
          submitLabel="Save"
          onSubmit={(body, key) => ecomApi.portalCheck(checking.return_id, body, key)}
          onClose={() => {
            setChecking(null);
          }}
          onDone={() => {
            setChecking(null);
            query.reload();
          }}
        />
      ) : null}
    </div>
  );
};
