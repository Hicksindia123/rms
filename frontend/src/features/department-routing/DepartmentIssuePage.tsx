/**
 * DEC-55 (gap plan G2, Q5): the Intermediate Store Manager issues the pieces the Replacement
 * Manager planned, one department at a time. Issuing moves stock from the Intermediate Store to
 * the department's own location (rms_move_stock, idempotent) and creates the Department Issue Note
 * (DIN) to print. Departments have no login.
 */
import React, { useEffect, useRef, useState } from 'react';
import { PackageCheck, RefreshCw, Printer, Inbox, Eye } from 'lucide-react';
import type { IssueQueueGroup } from './types';
import { departmentRoutingApi, routingErrorMessage } from './api';
import { newIdempotencyKey } from '@/lib/api/client';

interface DepartmentIssuePageProps {
  canIssue: boolean;
  onOpenGs: (gsId: string) => void;
  onOpenPrint: (routingId: string) => void;
}

const groupKey = (g: IssueQueueGroup) => `${g.gs_id}|${g.department_field_id}`;

const IssueGroupCard: React.FC<{
  group: IssueQueueGroup;
  canIssue: boolean;
  onOpenGs: (gsId: string) => void;
  onIssued: (routingId: string) => void;
}> = ({ group, canIssue, onOpenGs, onIssued }) => {
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(group.lines.map((l) => l.id)),
  );
  const [remarks, setRemarks] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // G-16: one key per selection; a retry of the same selection reuses it (stock moves once).
  const keyRef = useRef<{ sel: string; key: string } | null>(null);

  const selectedQty = group.lines.filter((l) => selected.has(l.id)).reduce((a, l) => a + l.qty, 0);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const issue = () => {
    const ids = group.lines.filter((l) => selected.has(l.id)).map((l) => l.id);
    if (ids.length === 0) return;
    const sel = ids.join(',');
    if (keyRef.current?.sel !== sel) keyRef.current = { sel, key: newIdempotencyKey() };
    setBusy(true);
    setError(null);
    departmentRoutingApi
      .issueToDepartment(
        {
          gs_id: group.gs_id,
          department_field_id: group.department_field_id,
          plan_line_ids: ids,
          remarks: remarks.trim() || undefined,
        },
        keyRef.current.key,
      )
      .then((routing) => {
        onIssued(routing.id);
      })
      .catch((err: unknown) => {
        setError(routingErrorMessage(err));
      })
      .finally(() => {
        setBusy(false);
      });
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900 p-4 sm:p-5 space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm font-bold text-slate-900 dark:text-slate-100">
              {group.gs_no}
            </span>
            <span className="rounded-full border border-indigo-200 bg-indigo-50 px-2.5 py-0.5 text-xs font-semibold text-indigo-700 dark:border-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-300">
              → {group.department_label}
            </span>
          </div>
          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400 break-words">
            Party: {group.party_name || '—'} • planned{' '}
            {new Date(group.planned_since).toLocaleString()} • {group.total_qty} pcs
          </div>
        </div>
        <button
          type="button"
          onClick={() => {
            onOpenGs(group.gs_id);
          }}
          className="min-h-[44px] inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 text-xs font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
        >
          <Eye className="h-3.5 w-3.5" /> GS Details
        </button>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs font-medium text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-400 break-words"
        >
          {error}
        </div>
      )}

      <ul className="divide-y divide-slate-100 dark:divide-slate-800 rounded-lg border border-slate-200 dark:border-slate-800">
        {group.lines.map((l) => (
          <li key={l.id}>
            <label className="flex min-h-[44px] items-center gap-3 px-3 py-2 text-xs cursor-pointer">
              <input
                type="checkbox"
                className="h-5 w-5 shrink-0"
                checked={selected.has(l.id)}
                disabled={!canIssue || busy}
                onChange={() => {
                  toggle(l.id);
                }}
              />
              <span className="min-w-0 flex-1">
                <span className="font-semibold text-slate-900 dark:text-slate-100">
                  #{l.line_no} {l.item_name}
                </span>
                <span className="block text-slate-500 dark:text-slate-400">
                  {l.source_bucket_label ?? 'All pieces'}
                  {l.notes ? ` • ${l.notes}` : ''}
                </span>
              </span>
              <span className="shrink-0 font-bold text-slate-900 dark:text-slate-100">
                {l.qty} pcs
              </span>
            </label>
          </li>
        ))}
      </ul>

      {canIssue ? (
        <div className="flex flex-col sm:flex-row gap-2">
          <label className="sr-only" htmlFor={`issue-remarks-${groupKey(group)}`}>
            Remarks for the department
          </label>
          <input
            id={`issue-remarks-${groupKey(group)}`}
            type="text"
            value={remarks}
            onChange={(e) => {
              setRemarks(e.target.value);
            }}
            placeholder="Remarks for the department (optional)"
            className="min-h-[44px] flex-1 rounded-lg border border-slate-300 bg-white px-3 text-xs text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
          />
          <button
            type="button"
            disabled={busy || selectedQty === 0}
            onClick={issue}
            className="min-h-[44px] inline-flex items-center justify-center gap-1.5 rounded-lg bg-indigo-600 px-5 text-xs font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Printer className="h-4 w-4" />
            {busy ? 'Issuing…' : `Issue ${String(selectedQty)} pcs & print DIN`}
          </button>
        </div>
      ) : null}
    </div>
  );
};

export const DepartmentIssuePage: React.FC<DepartmentIssuePageProps> = ({
  canIssue,
  onOpenGs,
  onOpenPrint,
}) => {
  const [groups, setGroups] = useState<IssueQueueGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    departmentRoutingApi
      .getIssueQueue()
      .then((data) => {
        if (!active) return;
        setGroups(data);
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

  const reload = () => {
    setLoading(true);
    setReloadKey((k) => k + 1);
  };

  return (
    <div className="space-y-6 p-4 sm:p-6 max-w-5xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <div className="rounded-lg bg-indigo-50 p-2 dark:bg-indigo-950/50 text-indigo-600 dark:text-indigo-400">
              <PackageCheck className="h-5 w-5" />
            </div>
            <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
              Department Issue
            </h1>
          </div>
          <p className="text-xs sm:text-sm text-slate-500 dark:text-slate-400 mt-1">
            Issue the pieces the Replacement Manager planned to each department and print the
            Department Issue Note (DIN).
          </p>
        </div>
        <button
          type="button"
          onClick={reload}
          disabled={loading}
          className="min-h-[44px] self-start sm:self-auto inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {loading ? (
        <div className="rounded-xl border border-slate-200 bg-white p-12 text-center text-slate-400 dark:border-slate-800 dark:bg-slate-900 animate-pulse">
          Loading planned issues…
        </div>
      ) : error ? (
        <div
          role="alert"
          className="flex flex-col items-center gap-3 rounded-xl border border-rose-200 bg-rose-50 p-6 text-center text-xs font-semibold text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-400"
        >
          <span className="break-words">{error}</span>
          <button
            type="button"
            onClick={reload}
            className="min-h-[44px] rounded-lg border border-rose-300 bg-white px-4 text-xs font-semibold text-rose-700 hover:bg-rose-100 dark:border-rose-800 dark:bg-rose-950 dark:text-rose-300"
          >
            Retry
          </button>
        </div>
      ) : groups.length === 0 ? (
        <div className="rounded-xl border border-slate-200 bg-white p-12 text-center text-slate-500 dark:border-slate-800 dark:bg-slate-900">
          <Inbox className="mx-auto h-10 w-10 text-slate-400 mb-2" />
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            Nothing to issue
          </h3>
          <p className="text-xs text-slate-400 mt-1">
            When the Replacement Manager plans department routing, the pieces to issue appear here.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {groups.map((g) => (
            <IssueGroupCard
              key={groupKey(g)}
              group={g}
              canIssue={canIssue}
              onOpenGs={onOpenGs}
              onIssued={onOpenPrint}
            />
          ))}
        </div>
      )}
    </div>
  );
};
