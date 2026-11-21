/**
 * Phase P5 (DEC-65): the Replacement Manager's "Pending Transfer Slip" screen. Goods slips whose
 * categorisation is locked are listed with their items (read-only). The RM selects one or more
 * (or all) and generates the transfer slips: ONE slip per Intermediate Store, covering every
 * selected GS that has lines for that store. Or the RM sends an Edit Request (reason) to
 * Management / Super Admin; that GS cannot be selected until the request is resolved.
 * The second tab lists the generated slips (history, including voided ones).
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ChevronDown,
  ChevronUp,
  FileDown,
  FileText,
  Inbox,
  MessageSquareWarning,
  RefreshCw,
  Send,
} from 'lucide-react';

import { Badge, Button, Modal } from '@/components/ui';
import { PageHeader } from '@/components/erp';
import { newIdempotencyKey } from '@/lib/api/client';
import { formatDate, formatDateTime } from '@/features/goods-slips/format';

import {
  type GenerateResult,
  type PendingGs,
  type SlipStatus,
  type SlipSummary,
  slipErrorMessage,
  transferSlipsApi,
} from './api';
import { SlipStatusBadge } from './SlipStatusBadge';

interface Props {
  canGenerate: boolean;
  onOpenGs: (gsId: string) => void;
  onOpenSlip: (slipId: string) => void;
}

const card =
  'rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900';
const field =
  'min-h-[44px] w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100';

function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-center text-sm font-medium text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300"
    >
      <span className="break-words">{message}</span>
      {onRetry ? (
        <Button type="button" variant="outline" onClick={onRetry}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}

/** Pieces of the GS not yet on a live slip, per store (what a generation would hand over). */
function openQtyByStore(gs: PendingGs): Map<string, { name: string; qty: number }> {
  const out = new Map<string, { name: string; qty: number }>();
  for (const ln of gs.lines) {
    if (ln.on_slip_no || !ln.store || ln.received_qty <= 0) continue;
    const cur = out.get(ln.store.code) ?? { name: ln.store.name, qty: 0 };
    cur.qty += ln.received_qty;
    out.set(ln.store.code, cur);
  }
  return out;
}

const GsItems: React.FC<{ gs: PendingGs }> = ({ gs }) => (
  <ul
    className="divide-y divide-slate-100 rounded-lg border border-slate-200 text-xs dark:divide-slate-800 dark:border-slate-800"
    data-testid="pending-gs-items"
  >
    {gs.lines.map((ln) => (
      <li key={ln.item_id} className="px-3 py-2">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="min-w-0 font-semibold text-slate-900 dark:text-slate-100 break-words">
            #{ln.line_no} {ln.product_code ? `${ln.product_code} · ` : ''}
            {ln.product_name}
          </span>
          <span className="shrink-0 text-slate-600 dark:text-slate-300">
            Doc {ln.documented_qty} · Physical <b>{ln.received_qty}</b>
          </span>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          {ln.store ? <Badge variant="info">{ln.store.name}</Badge> : null}
          {ln.on_slip_no ? <Badge variant="neutral">On {ln.on_slip_no}</Badge> : null}
          {ln.buckets.map((b) => (
            <span
              key={`${ln.item_id}-${b.field_code ?? b.label}`}
              className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-700 dark:bg-slate-800 dark:text-slate-300"
            >
              {b.label}: {b.qty}
            </span>
          ))}
        </div>
      </li>
    ))}
  </ul>
);

/** Mounted per GS (keyed by the parent), so each request starts empty with its own key. */
const EditRequestModal: React.FC<{
  gs: PendingGs;
  onClose: () => void;
  onSent: () => void;
}> = ({ gs, onClose, onSent }) => {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const keyRef = useRef(newIdempotencyKey());

  const valid = reason.trim().length >= 3;
  const send = () => {
    setBusy(true);
    setError(null);
    transferSlipsApi
      .requestEdit(gs.gs_id, reason.trim(), keyRef.current)
      .then(() => {
        onSent();
      })
      .catch((err: unknown) => {
        setError(slipErrorMessage(err));
      })
      .finally(() => {
        setBusy(false);
      });
  };
  return (
    <Modal
      isOpen
      onClose={onClose}
      title={`Send Edit Request · ${gs.gs_no}`}
      footer={
        <>
          <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            onClick={send}
            disabled={!valid || busy}
            isLoading={busy}
          >
            Send to Management
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        <p className="text-slate-600 dark:text-slate-300">
          Management and Super Admin are notified. This goods slip stays off the transfer slips
          until they edit it or reject the request.
        </p>
        <label htmlFor="edit-request-reason" className="block font-medium">
          What should be corrected?
        </label>
        <textarea
          id="edit-request-reason"
          value={reason}
          onChange={(e) => {
            setReason(e.target.value);
          }}
          rows={4}
          maxLength={2000}
          className="w-full rounded-lg border border-slate-300 bg-white p-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
        />
        {error ? <ErrorBox message={error} /> : null}
      </div>
    </Modal>
  );
};

const PendingTab: React.FC<Props> = ({ canGenerate, onOpenGs, onOpenSlip }) => {
  const [rows, setRows] = useState<PendingGs[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [party, setParty] = useState('');
  const [store, setStore] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [result, setResult] = useState<GenerateResult | null>(null);
  const [requestFor, setRequestFor] = useState<PendingGs | null>(null);
  // G-16: one key per selection; a retry of the same selection replays the first result.
  const keyRef = useRef<{ sel: string; key: string } | null>(null);

  useEffect(() => {
    let active = true;
    transferSlipsApi
      .pending()
      .then((data) => {
        if (!active) return;
        setRows(data);
        setError(null);
        setSelected((prev) => new Set([...prev].filter((id) => data.some((g) => g.gs_id === id))));
      })
      .catch((err: unknown) => {
        if (active) setError(slipErrorMessage(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [reload]);

  const refresh = () => {
    setLoading(true);
    setReload((k) => k + 1);
  };

  const parties = useMemo(
    () =>
      [...new Map(rows.map((r) => [r.party_id ?? '', r.party_name ?? '—'])).entries()].sort(
        (a, b) => a[1].localeCompare(b[1]),
      ),
    [rows],
  );
  const stores = useMemo(
    () =>
      [
        ...new Map(rows.flatMap((r) => r.stores.map((s) => [s.code, s.name] as const))).entries(),
      ].sort(),
    [rows],
  );
  const visible = useMemo(
    () =>
      rows.filter((r) => {
        if (party && (r.party_id ?? '') !== party) return false;
        if (store && !r.stores.some((s) => s.code === store)) return false;
        const day = r.locked_at ? r.locked_at.slice(0, 10) : '';
        if (from && day < from) return false;
        if (to && day > to) return false;
        return true;
      }),
    [rows, party, store, from, to],
  );
  const selectable = visible.filter((r) => !r.open_edit_request);
  const chosen = rows.filter((r) => selected.has(r.gs_id) && !r.open_edit_request);
  const allChecked = selectable.length > 0 && selectable.every((r) => selected.has(r.gs_id));

  const plan = useMemo(() => {
    const byStore = new Map<string, { name: string; qty: number; gs: number }>();
    for (const gs of chosen) {
      for (const [code, v] of openQtyByStore(gs)) {
        const cur = byStore.get(code) ?? { name: v.name, qty: 0, gs: 0 };
        cur.qty += v.qty;
        cur.gs += 1;
        byStore.set(code, cur);
      }
    }
    return [...byStore.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [chosen]);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const toggleAll = () => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (allChecked) selectable.forEach((r) => next.delete(r.gs_id));
      else selectable.forEach((r) => next.add(r.gs_id));
      return next;
    });
  };

  const generate = () => {
    const ids = chosen.map((g) => g.gs_id).sort();
    if (ids.length === 0) return;
    const sel = ids.join(',');
    if (keyRef.current?.sel !== sel) keyRef.current = { sel, key: newIdempotencyKey() };
    setBusy(true);
    setGenError(null);
    transferSlipsApi
      .generate(ids, keyRef.current.key)
      .then((res) => {
        setConfirming(false);
        setResult(res);
        setSelected(new Set());
        keyRef.current = null;
        refresh();
      })
      .catch((err: unknown) => {
        setGenError(slipErrorMessage(err));
      })
      .finally(() => {
        setBusy(false);
      });
  };

  if (loading && rows.length === 0) {
    return (
      <div role="status" className={`${card} p-10 text-center text-slate-400 animate-pulse`}>
        Loading goods slips pending a transfer slip…
      </div>
    );
  }
  if (error) return <ErrorBox message={error} onRetry={refresh} />;

  return (
    <div className="space-y-4 pb-24">
      <div className={`${card} grid grid-cols-1 gap-3 p-3 sm:grid-cols-4`}>
        <label className="text-xs font-medium text-slate-600 dark:text-slate-300">
          Party
          <select
            className={field}
            value={party}
            onChange={(e) => {
              setParty(e.target.value);
            }}
          >
            <option value="">All parties</option>
            {parties.map(([id, name]) => (
              <option key={id || 'none'} value={id}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-medium text-slate-600 dark:text-slate-300">
          Store involved
          <select
            className={field}
            value={store}
            onChange={(e) => {
              setStore(e.target.value);
            }}
          >
            <option value="">All stores</option>
            {stores.map(([code, name]) => (
              <option key={code} value={code}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-medium text-slate-600 dark:text-slate-300">
          Locked from
          <input
            type="date"
            className={field}
            value={from}
            onChange={(e) => {
              setFrom(e.target.value);
            }}
          />
        </label>
        <label className="text-xs font-medium text-slate-600 dark:text-slate-300">
          Locked to
          <input
            type="date"
            className={field}
            value={to}
            onChange={(e) => {
              setTo(e.target.value);
            }}
          />
        </label>
      </div>

      {visible.length === 0 ? (
        <div className={`${card} p-10 text-center text-slate-500`}>
          <Inbox className="mx-auto mb-2 h-10 w-10 text-slate-400" aria-hidden="true" />
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            {rows.length === 0 ? 'No goods slip is waiting for a transfer slip' : 'No match'}
          </h3>
          <p className="mt-1 text-xs text-slate-400">
            {rows.length === 0
              ? 'Goods slips appear here when the Replacement Executive locks the categorisation.'
              : 'Change the filters to see more goods slips.'}
          </p>
        </div>
      ) : (
        <>
          {canGenerate ? (
            <label className="flex min-h-[44px] items-center gap-3 px-1 text-sm font-medium">
              <input
                type="checkbox"
                className="h-5 w-5"
                checked={allChecked}
                disabled={selectable.length === 0}
                onChange={toggleAll}
                aria-label="Select all goods slips shown"
              />
              Select all ({selectable.length})
            </label>
          ) : null}
          <ul className="space-y-3" data-testid="pending-gs-list">
            {visible.map((gs) => {
              const blocked = Boolean(gs.open_edit_request);
              const isOpen = open.has(gs.gs_id);
              return (
                <li key={gs.gs_id} className={`${card} p-3 sm:p-4`} data-testid="pending-gs">
                  <div className="flex items-start gap-3">
                    {canGenerate ? (
                      <input
                        type="checkbox"
                        className="mt-1 h-5 w-5 shrink-0"
                        checked={selected.has(gs.gs_id) && !blocked}
                        disabled={blocked}
                        onChange={() => {
                          toggle(gs.gs_id);
                        }}
                        aria-label={`Select ${gs.gs_no}`}
                      />
                    ) : null}
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          className="font-mono text-sm font-bold text-indigo-700 underline-offset-2 hover:underline dark:text-indigo-300"
                          onClick={() => {
                            onOpenGs(gs.gs_id);
                          }}
                        >
                          {gs.gs_no}
                        </button>
                        {blocked ? <Badge variant="warning">Edit requested</Badge> : null}
                        {gs.partially_on_slips ? (
                          <Badge variant="neutral">Partly on slips</Badge>
                        ) : null}
                      </div>
                      <p className="text-xs text-slate-600 dark:text-slate-300 break-words">
                        {gs.party_name ?? '—'}
                        {gs.station_name ? ` · ${gs.station_name}` : ''}
                        {gs.state_name ? `, ${gs.state_name}` : ''}
                      </p>
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        {gs.cartons ?? '—'} carton(s) · received {formatDate(gs.received_date)} ·
                        locked {formatDateTime(gs.locked_at)} · <b>{gs.physical_qty} pc</b>
                      </p>
                      <div className="flex flex-wrap gap-1.5 pt-1">
                        {gs.stores.map((s) => (
                          <Badge key={s.code} variant="info">
                            {s.name}
                          </Badge>
                        ))}
                      </div>
                      {gs.open_edit_request ? (
                        <p className="text-xs text-amber-700 dark:text-amber-300 break-words">
                          Edit request by {gs.open_edit_request.requested_by_name ?? '—'}:{' '}
                          {gs.open_edit_request.reason}
                        </p>
                      ) : null}
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="min-h-[44px]"
                      aria-expanded={isOpen}
                      onClick={() => {
                        setOpen((prev) => {
                          const next = new Set(prev);
                          if (next.has(gs.gs_id)) next.delete(gs.gs_id);
                          else next.add(gs.gs_id);
                          return next;
                        });
                      }}
                    >
                      {isOpen ? (
                        <ChevronUp className="h-4 w-4" aria-hidden="true" />
                      ) : (
                        <ChevronDown className="h-4 w-4" aria-hidden="true" />
                      )}
                      {isOpen ? 'Hide items' : 'View items'}
                    </Button>
                    {canGenerate && !blocked ? (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="min-h-[44px]"
                        onClick={() => {
                          setRequestFor(gs);
                        }}
                      >
                        <MessageSquareWarning className="h-4 w-4" aria-hidden="true" />
                        Send Edit Request
                      </Button>
                    ) : null}
                  </div>
                  {isOpen ? (
                    <div className="mt-3">
                      <GsItems gs={gs} />
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </>
      )}

      {canGenerate ? (
        // Above the phone bottom bar (56px, fixed) on narrow screens.
        <div className="sticky bottom-2 z-10 max-[640px]:bottom-[64px]">
          <div
            className={`${card} flex flex-wrap items-center justify-between gap-2 p-3 shadow-lg`}
          >
            <span className="text-sm text-slate-700 dark:text-slate-200">
              {chosen.length} goods slip(s) selected
            </span>
            <Button
              type="button"
              variant="primary"
              className="min-h-[44px]"
              disabled={chosen.length === 0}
              onClick={() => {
                setGenError(null);
                setConfirming(true);
              }}
            >
              <Send className="h-4 w-4" aria-hidden="true" />
              Generate Transfer Slip
            </Button>
          </div>
        </div>
      ) : null}

      <Modal
        isOpen={confirming}
        onClose={() => {
          if (!busy) setConfirming(false);
        }}
        title="Generate transfer slips"
        footer={
          <>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => {
                setConfirming(false);
              }}
            >
              Back
            </Button>
            <Button
              type="button"
              variant="primary"
              onClick={generate}
              disabled={busy}
              isLoading={busy}
            >
              Generate {plan.length} slip(s)
            </Button>
          </>
        }
      >
        <div className="space-y-3 text-sm">
          <p className="text-slate-600 dark:text-slate-300">
            One slip per Intermediate Store, covering the {chosen.length} selected goods slip(s).
            The goods move to “in transit” until the store acknowledges its slip.
          </p>
          <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
            {plan.map(([code, p]) => (
              <li key={code} className="flex items-center justify-between gap-2 px-3 py-2">
                <span className="font-medium">{p.name}</span>
                <span className="text-slate-600 dark:text-slate-300">
                  {p.gs} GS · {p.qty} pc
                </span>
              </li>
            ))}
          </ul>
          {genError ? <ErrorBox message={genError} /> : null}
        </div>
      </Modal>

      <Modal
        isOpen={result !== null}
        onClose={() => {
          setResult(null);
        }}
        title="Transfer slips generated"
        footer={
          <Button
            type="button"
            variant="primary"
            onClick={() => {
              setResult(null);
            }}
          >
            Done
          </Button>
        }
      >
        <ul className="space-y-2 text-sm" data-testid="generated-slips">
          {result?.slips.map((s) => (
            <li
              key={s.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 p-3 dark:border-slate-800"
            >
              <span className="min-w-0">
                <span className="block font-mono font-bold">{s.slip_no}</span>
                <span className="text-xs text-slate-500">
                  {s.store.name} · {s.relevant_qty} pc · {s.gs_count} GS
                </span>
              </span>
              <span className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="min-h-[44px]"
                  onClick={() => {
                    onOpenSlip(s.id);
                  }}
                >
                  <FileText className="h-4 w-4" aria-hidden="true" /> View
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="min-h-[44px]"
                  onClick={() => {
                    transferSlipsApi.downloadPdf(s).catch((err: unknown) => {
                      setGenError(slipErrorMessage(err));
                    });
                  }}
                >
                  <FileDown className="h-4 w-4" aria-hidden="true" /> PDF
                </Button>
              </span>
            </li>
          ))}
        </ul>
        {genError ? <ErrorBox message={genError} /> : null}
      </Modal>

      {requestFor ? (
        <EditRequestModal
          key={requestFor.gs_id}
          gs={requestFor}
          onClose={() => {
            setRequestFor(null);
          }}
          onSent={() => {
            setRequestFor(null);
            refresh();
          }}
        />
      ) : null}
    </div>
  );
};

/** Generated slips (P5) — also the store's list in P6 (the API returns only its store's slips). */
export const SlipsTab: React.FC<{
  onOpenSlip: (id: string) => void;
  initialStatus?: SlipStatus | '';
}> = ({ onOpenSlip, initialStatus = '' }) => {
  const [status, setStatus] = useState<SlipStatus | ''>(initialStatus);
  const [q, setQ] = useState('');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<SlipSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  // Loading = the last answer is for another request (no setState inside the effect body).
  const requestKey = `${status}|${query}|${String(page)}|${String(reload)}`;
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let active = true;
    transferSlipsApi
      .list({ status, q: query, page })
      .then((res) => {
        if (!active) return;
        setItems(res.items);
        setTotal(res.total);
        setError(null);
      })
      .catch((err: unknown) => {
        if (active) setError(slipErrorMessage(err));
      })
      .finally(() => {
        if (active) setLoadedKey(requestKey);
      });
    return () => {
      active = false;
    };
  }, [status, query, page, reload, requestKey]);

  const pages = Math.max(1, Math.ceil(total / 25));
  return (
    <div className="space-y-4">
      <form
        className={`${card} grid grid-cols-1 gap-3 p-3 sm:grid-cols-[1fr_2fr_auto]`}
        onSubmit={(e) => {
          e.preventDefault();
          setPage(1);
          setQuery(q);
        }}
      >
        <label className="text-xs font-medium text-slate-600 dark:text-slate-300">
          Status
          <select
            className={field}
            value={status}
            onChange={(e) => {
              setPage(1);
              setStatus(e.target.value as SlipStatus | '');
            }}
          >
            <option value="">All</option>
            <option value="GENERATED">Generated</option>
            <option value="ACKNOWLEDGED">Acknowledged</option>
            <option value="VOIDED">Voided</option>
          </select>
        </label>
        <label className="text-xs font-medium text-slate-600 dark:text-slate-300">
          Slip or GS number
          <input
            className={field}
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
            }}
            placeholder="TRF/… or GS/…"
          />
        </label>
        <Button type="submit" variant="outline" className="min-h-[44px] self-end">
          Search
        </Button>
      </form>
      {loading ? (
        <div role="status" className={`${card} p-10 text-center text-slate-400 animate-pulse`}>
          Loading transfer slips…
        </div>
      ) : error ? (
        <ErrorBox
          message={error}
          onRetry={() => {
            setReload((k) => k + 1);
          }}
        />
      ) : items.length === 0 ? (
        <div className={`${card} p-10 text-center text-sm text-slate-500`}>
          <Inbox className="mx-auto mb-2 h-10 w-10 text-slate-400" aria-hidden="true" />
          No transfer slips found.
        </div>
      ) : (
        <ul className="m-0 list-none space-y-3 p-0" data-testid="slip-list">
          {items.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => {
                  onOpenSlip(s.id);
                }}
                className={`${card} block w-full p-3 text-left hover:border-indigo-300 sm:p-4`}
              >
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm font-bold">{s.slip_no}</span>
                  <SlipStatusBadge status={s.status} />
                </span>
                <span className="mt-1 block text-xs text-slate-600 dark:text-slate-300 break-words">
                  {s.store.name} · {s.gs_nos.join(', ')}
                </span>
                <span className="mt-1 block text-xs text-slate-500">
                  {s.relevant_qty} pc for the store · {s.grand_total_qty} pc in total ·{' '}
                  {formatDateTime(s.generated_at)} · {s.generated_by_name ?? '—'}
                </span>
                {s.discrepancy_count > 0 ? (
                  <span className="mt-1 block text-xs font-semibold text-amber-700 dark:text-amber-400">
                    {s.discrepancy_count} discrepancy report(s)
                  </span>
                ) : null}
              </button>
            </li>
          ))}
        </ul>
      )}
      {pages > 1 ? (
        <div className="flex items-center justify-between gap-2">
          <Button
            type="button"
            variant="outline"
            className="min-h-[44px]"
            disabled={page <= 1}
            onClick={() => {
              setPage((p) => p - 1);
            }}
          >
            Previous
          </Button>
          <span className="text-xs text-slate-500">
            Page {page} of {pages}
          </span>
          <Button
            type="button"
            variant="outline"
            className="min-h-[44px]"
            disabled={page >= pages}
            onClick={() => {
              setPage((p) => p + 1);
            }}
          >
            Next
          </Button>
        </div>
      ) : null}
    </div>
  );
};

export const TransferSlipsPage: React.FC<Props> = (props) => {
  const [tab, setTab] = useState<'pending' | 'slips'>('pending');
  const [key, setKey] = useState(0);
  const tabBtn = (id: 'pending' | 'slips', label: string) => (
    <button
      type="button"
      role="tab"
      aria-selected={tab === id}
      onClick={() => {
        setTab(id);
      }}
      className={`min-h-[44px] flex-1 rounded-lg px-4 text-sm font-semibold sm:flex-none ${
        tab === id
          ? 'bg-indigo-600 text-white'
          : 'bg-white text-slate-700 border border-slate-300 dark:bg-slate-800 dark:text-slate-200 dark:border-slate-700'
      }`}
    >
      {label}
    </button>
  );
  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      <PageHeader
        title="Transfer Slips"
        subtitle="Select locked goods slips and generate one transfer slip per Intermediate Store."
        actions={
          <Button
            type="button"
            variant="outline"
            className="min-h-[44px]"
            onClick={() => {
              setKey((k) => k + 1);
            }}
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" /> Refresh
          </Button>
        }
      />
      <div role="tablist" className="flex gap-2">
        {tabBtn('pending', 'Pending Transfer Slip')}
        {tabBtn('slips', 'Generated slips')}
      </div>
      {tab === 'pending' ? (
        <PendingTab key={key} {...props} />
      ) : (
        <SlipsTab key={key} onOpenSlip={props.onOpenSlip} />
      )}
    </div>
  );
};
