import { useEffect, useState } from 'react';
import { Printer, Truck } from 'lucide-react';

import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
  Modal,
  Textarea,
} from '@/components/ui';
import { formatDate, formatDateTime } from '@/features/goods-slips/format';
import { newIdempotencyKey } from '@/features/itemization/api';
import { useAuth } from '@/features/auth/useAuth';
import { toApiError, type ApiError } from '@/lib/api/client';

import { dispatchSlipsApi, type DispatchSlipFilter } from './api';
import { dispatchIssue, localToday } from './rules';
import type { DispatchIn, DispatchSlipOut } from './types';

interface Props {
  onOpenGs: (gsId: string) => void;
}

const EMPTY_FORM = (today: string): DispatchIn => ({
  dispatch_date: today,
  transporter: '',
  docket_no: '',
  vehicle_no: '',
  remarks: '',
});

/**
 * Dispatch Slips (change plan Phase 8; AMD-19; DEC-26): Dispatch issues the goods against the
 * numbered slip, records date / transporter / docket or vehicle, and the goods slip moves on to
 * closure.
 */
export function DispatchSlipsPage({ onOpenGs }: Props) {
  const { can } = useAuth();
  const [filter, setFilter] = useState<DispatchSlipFilter>('READY');
  const [slips, setSlips] = useState<DispatchSlipOut[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [active, setActive] = useState<DispatchSlipOut | null>(null);
  const [form, setForm] = useState<DispatchIn>(EMPTY_FORM(localToday()));
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const today = localToday();

  useEffect(() => {
    let alive = true;
    dispatchSlipsApi
      .list(filter)
      .then((rows) => {
        if (alive) setSlips(rows);
      })
      .catch((err: unknown) => {
        if (alive) setError(toApiError(err));
      });
    return () => {
      alive = false;
    };
  }, [filter, reloadKey]);

  const reload = () => {
    setReloadKey((k) => k + 1);
  };

  const print = (slip: DispatchSlipOut) => {
    const win = window.open('', '_blank');
    setActionError(null);
    dispatchSlipsApi
      .print(slip.id)
      .then((out) => {
        if (win) {
          win.opener = null;
          win.location.href = out.url;
        } else {
          window.location.assign(out.url);
        }
        reload();
      })
      .catch((err: unknown) => {
        win?.close();
        setActionError(toApiError(err));
      });
  };

  const formIssue = dispatchIssue(form, today);
  const submit = () => {
    if (!active || formIssue) return;
    setBusy(true);
    setActionError(null);
    const body: DispatchIn = {
      dispatch_date: form.dispatch_date,
      transporter: form.transporter.trim(),
      docket_no: form.docket_no?.trim() || null,
      vehicle_no: form.vehicle_no?.trim() || null,
      remarks: form.remarks?.trim() || null,
    };
    dispatchSlipsApi
      .dispatch(active.id, body, newIdempotencyKey())
      .then((out) => {
        setNotice(`${out.slip_no} dispatched. ${out.gs_no} moves on to closure.`);
        setActive(null);
        reload();
      })
      .catch((err: unknown) => {
        setActionError(toApiError(err));
      })
      .finally(() => {
        setBusy(false);
      });
  };

  return (
    <div className="page">
      <h1 className="page__title flex items-center gap-2">
        <Truck size={22} aria-hidden="true" /> Dispatch Slips
      </h1>
      <p className="page__subtitle">
        Issue the goods against the slip and record the dispatch. The goods slip then moves on to
        closure.
      </p>

      <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Filter">
        {(['READY', 'DISPATCHED'] as const).map((f) => (
          <Button
            key={f}
            type="button"
            variant={filter === f ? 'primary' : 'outline'}
            aria-pressed={filter === f}
            onClick={() => {
              setSlips(null);
              setError(null);
              setFilter(f);
              setNotice(null);
            }}
          >
            {f === 'READY' ? 'To dispatch' : 'Dispatched'}
          </Button>
        ))}
      </div>

      {notice ? (
        <p
          role="status"
          className="mt-3 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200"
        >
          {notice}
        </p>
      ) : null}
      {actionError && !active ? (
        <div className="mt-3">
          <ErrorState title="The action was not completed" error={actionError} />
        </div>
      ) : null}

      <div className="mt-4">
        {error ? (
          <ErrorState
            error={error}
            onRetry={() => {
              setSlips(null);
              setError(null);
              reload();
            }}
          />
        ) : slips === null ? (
          <LoadingState label="Loading Dispatch Slips…" />
        ) : slips.length === 0 ? (
          <EmptyState
            title={filter === 'READY' ? 'Nothing to dispatch' : 'No dispatched slips'}
            hint={
              filter === 'READY'
                ? 'Dispatch Slips appear here when Accounts completes a goods slip.'
                : 'Dispatched slips are listed here.'
            }
          />
        ) : (
          <ul className="m-0 flex list-none flex-col gap-3 p-0">
            {slips.map((s) => (
              <li
                key={s.id}
                className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="m-0 flex flex-wrap items-center gap-2 font-semibold">
                      <span style={{ wordBreak: 'break-all' }}>{s.slip_no}</span>
                      <Badge variant={s.status === 'DISPATCHED' ? 'success' : 'info'}>
                        {s.status === 'DISPATCHED' ? 'Dispatched' : 'Ready'}
                      </Badge>
                    </p>
                    <p className="m-0 text-sm">
                      <button
                        type="button"
                        className="min-h-[44px] border-0 bg-transparent p-0 text-left text-sky-700 underline dark:text-sky-300"
                        onClick={() => {
                          onOpenGs(s.gs_id);
                        }}
                      >
                        {s.gs_no}
                      </button>
                      {s.party_name ? ` · ${s.party_name}` : ''}
                    </p>
                    <p className="m-0 text-xs text-slate-500">
                      {s.ac_slip_no} v{s.ac_version_no} · generated {formatDateTime(s.generated_at)}
                      {s.generated_by_name ? ` · ${s.generated_by_name}` : ''} · printed{' '}
                      {s.print_count}×
                    </p>
                    {s.status === 'DISPATCHED' ? (
                      <p className="m-0 text-xs text-slate-500">
                        Dispatched {formatDate(s.dispatch_date)} via {s.transporter}
                        {s.docket_no ? ` · docket ${s.docket_no}` : ''}
                        {s.vehicle_no ? ` · vehicle ${s.vehicle_no}` : ''}
                        {s.dispatched_by_name ? ` · ${s.dispatched_by_name}` : ''}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {can('ac_entry', 'export') ? (
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => {
                          print(s);
                        }}
                      >
                        <Printer size={16} aria-hidden="true" />{' '}
                        {s.print_count > 0 ? 'Re-print' : 'Print'}
                      </Button>
                    ) : null}
                    {s.status === 'READY' && can('dispatch', 'create') ? (
                      <Button
                        type="button"
                        variant="primary"
                        onClick={() => {
                          setActive(s);
                          setForm(EMPTY_FORM(today));
                          setActionError(null);
                          setNotice(null);
                        }}
                      >
                        <Truck size={16} aria-hidden="true" /> Mark dispatched
                      </Button>
                    ) : null}
                  </div>
                </div>
                <ul className="m-0 mt-3 flex list-none flex-col gap-1 p-0 text-sm">
                  {s.lines.map((ln) => (
                    <li
                      key={ln.id}
                      className="flex flex-wrap justify-between gap-x-3 rounded-lg bg-slate-50 px-3 py-2 dark:bg-slate-800/50"
                    >
                      <span className="min-w-0" style={{ wordBreak: 'break-word' }}>
                        #{ln.line_no} {ln.product_name} · {ln.action_label}
                      </span>
                      <span className="text-xs text-slate-600 dark:text-slate-300">
                        {ln.qty} pc(s) · Challan {ln.challan_no} ({formatDate(ln.challan_date)})
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="m-0 mt-2 text-right text-xs font-semibold">
                  Total {s.total_qty} pc(s)
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>

      <Modal
        isOpen={active !== null}
        onClose={() => {
          setActive(null);
        }}
        title={active ? `Dispatch ${active.slip_no}` : 'Dispatch'}
        footer={
          <>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setActive(null);
              }}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              disabled={busy || formIssue !== null}
              onClick={submit}
            >
              <Truck size={16} aria-hidden="true" /> {busy ? 'Dispatching…' : 'Issue & dispatch'}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <p className="m-0 text-sm">
            The goods are issued from the intermediate store and the slip is marked dispatched. This
            cannot be undone.
          </p>
          <div className="flex flex-col gap-1">
            <label htmlFor="ds-date" className="text-sm font-medium">
              Dispatch date
            </label>
            <Input
              id="ds-date"
              type="date"
              max={today}
              className="h-11"
              value={form.dispatch_date}
              onChange={(e) => {
                setForm((f) => ({ ...f, dispatch_date: e.target.value }));
              }}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="ds-transporter" className="text-sm font-medium">
              Transporter / courier
            </label>
            <Input
              id="ds-transporter"
              className="h-11"
              maxLength={120}
              value={form.transporter}
              onChange={(e) => {
                setForm((f) => ({ ...f, transporter: e.target.value }));
              }}
            />
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <label htmlFor="ds-docket" className="text-sm font-medium">
                Docket No.
              </label>
              <Input
                id="ds-docket"
                className="h-11"
                maxLength={60}
                value={form.docket_no ?? ''}
                onChange={(e) => {
                  setForm((f) => ({ ...f, docket_no: e.target.value }));
                }}
              />
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="ds-vehicle" className="text-sm font-medium">
                Vehicle No.
              </label>
              <Input
                id="ds-vehicle"
                className="h-11"
                maxLength={30}
                value={form.vehicle_no ?? ''}
                onChange={(e) => {
                  setForm((f) => ({ ...f, vehicle_no: e.target.value }));
                }}
              />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="ds-remarks" className="text-sm font-medium">
              Remarks (optional)
            </label>
            <Textarea
              id="ds-remarks"
              maxLength={1000}
              value={form.remarks ?? ''}
              onChange={(e) => {
                setForm((f) => ({ ...f, remarks: e.target.value }));
              }}
            />
          </div>
          {formIssue ? (
            <p className="m-0 text-xs text-amber-700 dark:text-amber-300" role="status">
              {formIssue}
            </p>
          ) : null}
          {actionError ? <ErrorState title="Not dispatched" error={actionError} /> : null}
        </div>
      </Modal>
    </div>
  );
}
