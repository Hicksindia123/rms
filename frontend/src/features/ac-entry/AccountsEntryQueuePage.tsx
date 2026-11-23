import { useEffect, useState } from 'react';
import { ChevronRight, FileSpreadsheet } from 'lucide-react';

import { Badge, Button, EmptyState, ErrorState, LoadingState } from '@/components/ui';
import { StatusChip } from '@/features/goods-slips/display';
import { formatDateTime } from '@/features/goods-slips/format';
import { toApiError, type ApiError } from '@/lib/api/client';

import { acEntryApi, type AcQueueTab } from './api';
import type { AcEntryQueueItem, AcHoldItem } from './types';

interface Props {
  onOpen: (gsId: string) => void;
  /** DEC-71 (Q21): a goods slip on hold opens its goods slip page (no Accounts entry). */
  onOpenGs: (gsId: string) => void;
}

const FILTERS: { id: AcQueueTab; label: string }[] = [
  { id: 'pending', label: 'To enter' },
  { id: 'completed', label: 'Completed' },
  { id: 'all', label: 'All' },
  { id: 'hold', label: 'On hold' },
];

/**
 * Accounts work queue (change plan Phase 8; AMD-18): goods slips whose Replacement Manager
 * finalised the "Replacement Slip – A/c Actions". Accounts enters CN / Challan data per line.
 */
export function AccountsEntryQueuePage({ onOpen, onOpenGs }: Props) {
  const [filter, setFilter] = useState<AcQueueTab>('pending');
  const [items, setItems] = useState<AcEntryQueueItem[] | null>(null);
  const [hold, setHold] = useState<AcHoldItem[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    const fail = (err: unknown) => {
      if (active) setError(toApiError(err));
    };
    if (filter === 'hold') {
      acEntryApi
        .hold()
        .then((rows) => {
          if (active) setHold(rows);
        })
        .catch(fail);
    } else {
      acEntryApi
        .queue(filter)
        .then((rows) => {
          if (active) setItems(rows);
        })
        .catch(fail);
    }
    return () => {
      active = false;
    };
  }, [filter, reloadKey]);

  return (
    <div className="page">
      <h1 className="page__title flex items-center gap-2">
        <FileSpreadsheet size={22} aria-hidden="true" /> Accounts Entry
      </h1>
      <p className="page__subtitle">
        Challan and Credit Note details of each goods slip&apos;s Replacement Slip. Completing it
        generates the Dispatch Slip when goods ship.
      </p>

      <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Filter">
        {FILTERS.map((f) => (
          <Button
            key={f.id}
            type="button"
            variant={filter === f.id ? 'primary' : 'outline'}
            aria-pressed={filter === f.id}
            onClick={() => {
              setItems(null);
              setHold(null);
              setError(null);
              setFilter(f.id);
            }}
          >
            {f.label}
          </Button>
        ))}
      </div>

      <div className="mt-4">
        {error ? (
          <ErrorState
            error={error}
            onRetry={() => {
              setItems(null);
              setHold(null);
              setError(null);
              setReloadKey((k) => k + 1);
            }}
          />
        ) : filter === 'hold' ? (
          hold === null ? (
            <LoadingState label="Loading the goods slips on hold…" />
          ) : hold.length === 0 ? (
            <EmptyState
              title="Nothing on hold"
              hint="A goods slip whose every decision is Not Allowed stays here, without an Accounts entry."
            />
          ) : (
            <ul className="m-0 flex list-none flex-col gap-2 p-0" aria-label="Goods slips on hold">
              {hold.map((h) => (
                <li key={h.gs_id}>
                  <button
                    type="button"
                    className="flex min-h-[44px] w-full items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm hover:border-sky-400 dark:border-slate-800 dark:bg-slate-900"
                    onClick={() => {
                      onOpenGs(h.gs_id);
                    }}
                  >
                    <div className="min-w-0">
                      <p className="m-0 flex flex-wrap items-center gap-2 font-semibold">
                        <span style={{ wordBreak: 'break-all' }}>{h.gs_no}</span>
                        <StatusChip status={h.gs_status} />
                      </p>
                      {h.party_name ? (
                        <p className="m-0 text-sm" style={{ wordBreak: 'break-word' }}>
                          {h.party_name}
                        </p>
                      ) : null}
                      <p className="m-0 text-xs text-slate-500">
                        {h.total_qty} pc(s), all Not Allowed · no Accounts entry · since{' '}
                        {formatDateTime(h.since)}
                      </p>
                    </div>
                    <ChevronRight
                      size={18}
                      aria-hidden="true"
                      className="shrink-0 text-slate-400"
                    />
                  </button>
                </li>
              ))}
            </ul>
          )
        ) : items === null ? (
          <LoadingState label="Loading the Accounts queue…" />
        ) : items.length === 0 ? (
          <EmptyState
            title={filter === 'pending' ? 'Nothing to enter' : 'No goods slips'}
            hint={
              filter === 'pending'
                ? 'Goods slips appear here when every store has analysed them and Management approval (if needed) is done.'
                : 'No goods slip matches this filter.'
            }
          />
        ) : (
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {items.map((q) => (
              <li key={q.ac_action_slip_id}>
                <button
                  type="button"
                  className="flex min-h-[44px] w-full items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm hover:border-sky-400 dark:border-slate-800 dark:bg-slate-900"
                  onClick={() => {
                    onOpen(q.gs_id);
                  }}
                >
                  <div className="min-w-0">
                    <p className="m-0 flex flex-wrap items-center gap-2 font-semibold">
                      <span style={{ wordBreak: 'break-all' }}>{q.gs_no}</span>
                      <StatusChip status={q.gs_status} />
                    </p>
                    {q.party_name ? (
                      <p className="m-0 text-sm" style={{ wordBreak: 'break-word' }}>
                        {q.party_name}
                      </p>
                    ) : null}
                    <p className="m-0 text-xs text-slate-500">
                      {q.slip_no} v{q.version_no}
                      {(q.round_no ?? 1) > 1
                        ? ` · Pending re-action (round ${String(q.round_no)})`
                        : ''}{' '}
                      · finalised {formatDateTime(q.finalised_at)}
                    </p>
                    <p className="m-0 mt-1 flex flex-wrap gap-1">
                      {q.is_completed ? (
                        <Badge variant="success">Completed</Badge>
                      ) : q.per_gs ? (
                        <Badge variant={q.lines_complete > 0 ? 'success' : 'warning'}>
                          {[
                            q.requires_challan ? 'Challan' : null,
                            q.requires_cn ? 'Credit Note' : null,
                          ]
                            .filter(Boolean)
                            .join(' + ')}{' '}
                          {q.lines_complete > 0 ? 'entered' : 'to enter'}
                        </Badge>
                      ) : (
                        <Badge variant={q.lines_complete > 0 ? 'warning' : 'neutral'}>
                          {q.lines_complete} / {q.lines_needing_data} lines entered
                        </Badge>
                      )}
                      {q.dispatch_slip_no ? (
                        <Badge variant={q.dispatch_status === 'DISPATCHED' ? 'success' : 'info'}>
                          {q.dispatch_slip_no} ·{' '}
                          {q.dispatch_status === 'DISPATCHED' ? 'Dispatched' : 'Ready'}
                        </Badge>
                      ) : null}
                    </p>
                  </div>
                  <ChevronRight size={18} aria-hidden="true" className="shrink-0 text-slate-400" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
