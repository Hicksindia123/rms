/**
 * Phase P10 (DEC-70): "Management Approval". Goods slips a store sent for approval (reason shown)
 * come first; below them every goods slip between the analysis and Accounts. A search finds any of
 * them by GS no., party or station. A row opens the goods slip for review / changes / approval.
 */
import React, { useEffect, useState } from 'react';
import { ChevronRight, RefreshCw, Search } from 'lucide-react';

import { Badge, Button, EmptyState, ErrorState, Input, LoadingState } from '@/components/ui';
import { PageHeader } from '@/components/erp';
import { toApiError, type ApiError } from '@/lib/api/client';
import { formatDateTime } from '@/features/goods-slips/format';
import { StatusChip } from '@/features/goods-slips/display';

import { managementApprovalApi } from './api';
import type { ApprovalState, QueueRow } from './types';

interface Props {
  onOpenGs: (gsId: string) => void;
}

const STATE_BADGE: Record<ApprovalState, { text: string; variant: 'success' | 'warning' } | null> =
  {
    NONE: null,
    VALID: { text: 'Approved', variant: 'success' },
    CHANGED: { text: 'Changed after approval', variant: 'warning' },
  };

const Row: React.FC<{ r: QueueRow; onOpen: () => void }> = ({ r, onOpen }) => {
  const badge = STATE_BADGE[r.approval_state];
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="flex min-h-[44px] w-full items-center gap-3 rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm hover:border-indigo-300 dark:border-slate-800 dark:bg-slate-900"
      >
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-slate-900 dark:text-slate-100">{r.gs_no}</span>
            <StatusChip status={r.status} />
            {badge ? <Badge variant={badge.variant}>{badge.text}</Badge> : null}
            {r.has_issue_cn ? <Badge variant="info">Issue CN</Badge> : null}
            {(r.cn_request_qty ?? 0) > 0 ? (
              <Badge variant="warning">Issue CN Request · {r.cn_request_qty} pcs</Badge>
            ) : null}
          </div>
          <div className="break-words text-sm text-slate-600 dark:text-slate-300">
            {r.party_name ?? '—'}
            {r.station_name ? ` · ${r.station_name}` : ''}
          </div>
          {r.request_id ? (
            <p className="break-words text-sm text-amber-900 dark:text-amber-200">
              {r.request_store_name}
              {r.requested_by_name ? ` (${r.requested_by_name})` : ''}
              {r.requested_at ? `, ${formatDateTime(r.requested_at)}` : ''}: “{r.request_reason}”
            </p>
          ) : r.since ? (
            <div className="text-xs text-slate-500 dark:text-slate-400">
              Since {formatDateTime(r.since)}
            </div>
          ) : null}
          {r.waiting_store_codes.length > 0 ? (
            <div className="text-xs text-slate-500 dark:text-slate-400">
              Waiting for the analysis of {r.waiting_store_codes.join(', ')}
            </div>
          ) : null}
        </div>
        <ChevronRight className="h-5 w-5 shrink-0 text-slate-400" aria-hidden="true" />
      </button>
    </li>
  );
};

export const ManagementApprovalQueuePage: React.FC<Props> = ({ onOpenGs }) => {
  const [rows, setRows] = useState<QueueRow[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [term, setTerm] = useState('');
  const [query, setQuery] = useState('');
  const [reloadKey, setReloadKey] = useState(0);

  // State changes only in the request callbacks (the triggers set `loading`).
  useEffect(() => {
    let active = true;
    managementApprovalApi
      .getQueue(query)
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
  }, [query, reloadKey]);

  const load = () => {
    setLoading(true);
    setReloadKey((k) => k + 1);
  };

  const requested = rows?.filter((r) => r.request_id) ?? [];
  const others = rows?.filter((r) => !r.request_id) ?? [];

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6" data-testid="management-approval-queue">
      <PageHeader
        title="Management Approval"
        subtitle="Goods slips sent by a store for approval, and every goods slip between the analysis and Accounts. Review, change any decision (incl. Issue CN) and approve."
        actions={
          <Button type="button" variant="outline" className="min-h-[44px]" onClick={load}>
            <RefreshCw className="h-4 w-4" aria-hidden="true" /> Refresh
          </Button>
        }
      />
      <form
        role="search"
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setLoading(true);
          setQuery(term);
        }}
      >
        <div className="min-w-0 flex-1">
          <Input
            aria-label="Search goods slips"
            placeholder="GS no., party or station"
            value={term}
            maxLength={100}
            className="min-h-[44px]"
            onChange={(e) => {
              setTerm(e.target.value);
            }}
          />
        </div>
        <Button type="submit" variant="outline" className="min-h-[44px] shrink-0">
          <Search className="h-4 w-4" aria-hidden="true" /> Search
        </Button>
      </form>

      {loading ? (
        <LoadingState label="Loading goods slips…" />
      ) : error ? (
        <ErrorState error={error} onRetry={load} title="Could not load the approval queue" />
      ) : !rows || rows.length === 0 ? (
        <EmptyState
          title={query ? 'No goods slip found' : 'Nothing waits for Management'}
          hint={
            query
              ? 'Only goods slips between the analysis and Accounts are listed.'
              : 'Goods slips appear here when a store sends one for approval or every store has submitted its analysis.'
          }
        />
      ) : (
        <>
          {requested.length > 0 ? (
            <section className="space-y-2">
              <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
                Sent for approval ({requested.length})
              </h2>
              <ul className="m-0 list-none space-y-3 p-0" aria-label="Sent for approval">
                {requested.map((r) => (
                  <Row
                    key={r.gs_id}
                    r={r}
                    onOpen={() => {
                      onOpenGs(r.gs_id);
                    }}
                  />
                ))}
              </ul>
            </section>
          ) : null}
          {others.length > 0 ? (
            <section className="space-y-2">
              <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
                Analysed, before Accounts ({others.length})
              </h2>
              <ul className="m-0 list-none space-y-3 p-0" aria-label="Analysed goods slips">
                {others.map((r) => (
                  <Row
                    key={r.gs_id}
                    r={r}
                    onOpen={() => {
                      onOpenGs(r.gs_id);
                    }}
                  />
                ))}
              </ul>
            </section>
          ) : null}
        </>
      )}
    </div>
  );
};
