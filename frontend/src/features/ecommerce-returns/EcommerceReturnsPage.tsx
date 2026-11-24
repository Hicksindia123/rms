/** DEC-73: every E-Commerce Return, newest first; search by number, order id, platform, product. */
import React, { useCallback, useState } from 'react';
import { ChevronRight, Plus, RefreshCw, Search } from 'lucide-react';

import { PageHeader } from '@/components/erp';
import { Button, EmptyState, ErrorState, Input, LoadingState, Select } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { formatDate } from '@/features/goods-slips/format';

import { ecomApi } from './api';
import { EcomStatusChip, SlaChip } from './SlaChip';
import type { ReturnList, ReturnStatus } from './types';

interface Props {
  onOpen: (id: string) => void;
  /** Shown when the user may record e-commerce returns. */
  onNew?: (() => void) | undefined;
}

export const EcommerceReturnsPage: React.FC<Props> = ({ onOpen, onNew }) => {
  const [term, setTerm] = useState('');
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<ReturnStatus | ''>('');
  const fetcher = useCallback(() => ecomApi.list(q, status), [q, status]);
  const query = useApiQuery<ReturnList>(fetcher);
  // The status filter is built from the configured ECOM_RETURN_STATUS labels.
  const [statusOptions, setStatusOptions] = useState<{ code: string; label: string }[]>([]);
  if (query.data && statusOptions.length === 0 && query.data.status_options.length > 0) {
    setStatusOptions(query.data.status_options);
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6" data-testid="ecom-returns">
      <PageHeader
        title="E-Commerce Returns"
        subtitle="Returns recorded at the gate with their QC route, platform ticket and status."
        actions={
          <>
            <Button type="button" variant="outline" className="min-h-[44px]" onClick={query.reload}>
              <RefreshCw className="h-4 w-4" aria-hidden="true" /> Refresh
            </Button>
            {onNew ? (
              <Button type="button" className="min-h-[44px]" onClick={onNew}>
                <Plus className="h-4 w-4" aria-hidden="true" /> New
              </Button>
            ) : null}
          </>
        }
      />
      <form
        role="search"
        className="flex flex-col gap-2 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          setQ(term);
        }}
      >
        <div className="min-w-0 flex-1">
          <Input
            aria-label="Search e-commerce returns"
            placeholder="Return no., order ID, platform or product"
            value={term}
            maxLength={100}
            className="min-h-[44px]"
            onChange={(e) => {
              setTerm(e.target.value);
            }}
          />
        </div>
        <div className="sm:w-56">
          <Select
            aria-label="Status"
            value={status}
            className="min-h-[44px]"
            options={[
              { value: '', label: 'All statuses' },
              ...statusOptions.map((o) => ({ value: o.code, label: o.label })),
            ]}
            onChange={(e) => {
              setStatus(e.target.value as ReturnStatus | '');
            }}
          />
        </div>
        <Button type="submit" variant="outline" className="min-h-[44px] shrink-0">
          <Search className="h-4 w-4" aria-hidden="true" /> Search
        </Button>
      </form>

      {query.error ? (
        <ErrorState error={query.error} onRetry={query.reload} title="Could not load the returns" />
      ) : !query.data ? (
        <LoadingState label="Loading e-commerce returns…" />
      ) : query.data.rows.length === 0 ? (
        <EmptyState
          title={q || status ? 'No return found' : 'No e-commerce return yet'}
          hint="Returns appear here once they are recorded at the gate."
        />
      ) : (
        <ul className="m-0 list-none space-y-3 p-0" aria-label="E-commerce returns">
          {query.data.rows.map((r) => (
            <li key={r.id}>
              <button
                type="button"
                onClick={() => {
                  onOpen(r.id);
                }}
                className="flex min-h-[44px] w-full items-center gap-3 rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm hover:border-indigo-300 dark:border-slate-800 dark:bg-slate-900"
              >
                <div className="min-w-0 flex-1 space-y-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{r.return_no}</span>
                    <EcomStatusChip status={r.status} label={r.status_label} />
                    {r.ticket && !r.ticket.closed_at && r.status !== 'VOIDED' ? (
                      <SlaChip ticket={r.ticket} />
                    ) : null}
                  </div>
                  <div className="break-words text-sm text-slate-600 dark:text-slate-300">
                    {r.platform_label} · Order {r.order_id} · {formatDate(r.entry_date)}
                  </div>
                  <div className="break-words text-sm text-slate-600 dark:text-slate-300">
                    {r.product_text} · Qty {r.qty} · {r.qc_routing_label}
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
