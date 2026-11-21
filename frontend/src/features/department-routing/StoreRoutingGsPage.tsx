/**
 * Phase P7 (DEC-67; Q14, Q29): the Intermediate Store user routes ITS lines of one goods slip, per
 * item + current condition, to departments (labels from the DEC-59 department masters under the
 * goods slip's profile version). A condition can be split across departments. Saving is the issue:
 * one Department Issue Note (DIN) per department, the stock leaves the store now; "Issue to Store"
 * (no work) moves no stock and is ready for analysis.
 *
 * By default only the user's own items show; "Show all items of this GS" adds the other stores'
 * items read-only, with their store name.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, CheckCircle2, Printer, ShieldCheck } from 'lucide-react';

import { Badge, Button, EmptyState, ErrorState, LoadingState, Modal } from '@/components/ui';
import { PageHeader } from '@/components/erp';
import { newIdempotencyKey, toApiError, type ApiError } from '@/lib/api/client';
import { StatusChip } from '@/features/goods-slips/display';

import { departmentRoutingApi } from './api';
import { StoreProgressChip } from './storeRoutingDisplay';
import type {
  StoreRoutingGs,
  StoreRoutingItem,
  StoreRoutingLineIn,
  StoreRoutingResult,
} from './types';

interface Props {
  gsId: string;
  onBack: () => void;
  onOpenGs: (gsId: string) => void;
  onOpenPrint: (routingId: string) => void;
}

interface Row {
  key: string;
  bucketId: string | null;
  label: string;
  current: number;
  free: number;
}

/** Rows to route: the item's current conditions, or "All pieces" for an item without a split. */
function rowsFor(it: StoreRoutingItem): Row[] {
  if (it.conditions.length === 0) {
    return [
      {
        key: `${it.item_id}|`,
        bucketId: null,
        label: 'All pieces',
        current: it.received_qty,
        free: it.routable_qty,
      },
    ];
  }
  return it.conditions.map((c) => ({
    key: `${it.item_id}|${c.field_id}`,
    bucketId: c.field_id,
    label: c.field_label,
    current: c.current_qty,
    free: c.routable_qty,
  }));
}

const card =
  'rounded-xl border border-slate-200 bg-white p-3 shadow-sm sm:p-4 dark:border-slate-800 dark:bg-slate-900';

interface UndoProps {
  undoing: { id: string; reason: string } | null;
  busy: boolean;
  onStart: (id: string) => void;
  onReason: (reason: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Routed lines of an item; Q32: the store may undo its own "Issue to Store" lines. */
const RoutedLines: React.FC<{ item: StoreRoutingItem; undo: UndoProps }> = ({ item, undo }) =>
  item.routed.length === 0 ? null : (
    <ul
      className="mt-2 list-none space-y-1 p-0 text-xs text-slate-600 dark:text-slate-300"
      aria-label="Routed"
    >
      {item.routed.map((l) => {
        const canUndo = item.undoable_line_ids.includes(l.id);
        const open = undo.undoing?.id === l.id;
        return (
          <li key={l.id} className="break-words">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span>
                {l.source_bucket_label ?? 'All pieces'} → <strong>{l.department_label}</strong> ·{' '}
                {l.qty} pcs
                {l.routing_no ? ` · ${l.routing_no}` : l.is_no_work ? ' · no work' : ''}
              </span>
              {canUndo && !open ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="min-h-[44px]"
                  onClick={() => {
                    undo.onStart(l.id);
                  }}
                >
                  Undo
                </Button>
              ) : null}
            </div>
            {open ? (
              <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                <label className="sr-only" htmlFor={`undo-reason-${l.id}`}>
                  Reason for undoing
                </label>
                <input
                  id={`undo-reason-${l.id}`}
                  type="text"
                  value={undo.undoing?.reason ?? ''}
                  placeholder="Reason (required)"
                  onChange={(e) => {
                    undo.onReason(e.target.value);
                  }}
                  className="min-h-[44px] flex-1 rounded-lg border border-slate-300 bg-white px-3 text-xs text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                />
                <Button
                  type="button"
                  variant="danger"
                  className="min-h-[44px]"
                  disabled={undo.busy || (undo.undoing?.reason.trim().length ?? 0) < 3}
                  isLoading={undo.busy}
                  onClick={undo.onConfirm}
                >
                  Confirm undo
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="min-h-[44px]"
                  onClick={undo.onCancel}
                >
                  Keep
                </Button>
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );

export const StoreRoutingGsPage: React.FC<Props> = ({ gsId, onBack, onOpenGs, onOpenPrint }) => {
  const [data, setData] = useState<StoreRoutingGs | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [storeId, setStoreId] = useState<string | null>(null);
  // qty per `${itemId}|${bucketId}|${deptId}`
  const [qty, setQty] = useState<Record<string, number>>({});
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<ApiError | null>(null);
  const [result, setResult] = useState<StoreRoutingResult | null>(null);
  const [undoing, setUndoing] = useState<{ id: string; reason: string } | null>(null);
  const [undoBusy, setUndoBusy] = useState(false);
  const [undoError, setUndoError] = useState<ApiError | null>(null);

  const confirmUndo = () => {
    if (!undoing) return;
    setUndoBusy(true);
    setUndoError(null);
    departmentRoutingApi
      .undoStoreLine(undoing.id, undoing.reason.trim())
      .then((d) => {
        setData(d);
        setUndoing(null);
        setResult(null);
      })
      .catch((err: unknown) => {
        setUndoError(toApiError(err));
      })
      .finally(() => {
        setUndoBusy(false);
      });
  };
  const undoProps: UndoProps = {
    undoing,
    busy: undoBusy,
    onStart: (id) => {
      setUndoError(null);
      setUndoing({ id, reason: '' });
    },
    onReason: (reason) => {
      setUndoing((u) => (u ? { ...u, reason } : u));
    },
    onConfirm: confirmUndo,
    onCancel: () => {
      setUndoing(null);
    },
  };
  // G-16: one key per routing; a retry after a network error reuses it (never issues twice).
  const idemKey = useRef(newIdempotencyKey());

  const [reloadKey, setReloadKey] = useState(0);

  // State changes only in the request callbacks (the triggers set `loading`).
  useEffect(() => {
    let active = true;
    departmentRoutingApi
      .getStoreGs(gsId)
      .then((d) => {
        if (active) {
          setData(d);
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
  }, [gsId, reloadKey]);

  const load = () => {
    setLoading(true);
    setReloadKey((k) => k + 1);
  };

  // Stores the user may route now (a Super Admin may see several).
  const myStores = useMemo(
    () => (data ? data.stores.filter((s) => s.is_mine && s.status === 'ROUTING_PENDING') : []),
    [data],
  );
  const activeStore = myStores.find((s) => s.store_id === storeId) ?? myStores[0] ?? null;
  const hasMine = data ? data.items.some((i) => i.is_mine) : false;
  const visible = data ? data.items.filter((i) => showAll || !hasMine || i.is_mine) : [];
  const editable = (it: StoreRoutingItem) =>
    activeStore !== null &&
    it.is_mine &&
    it.store?.id === activeStore.store_id &&
    it.routable_qty > 0;

  const sums = useMemo(() => {
    const row: Record<string, number> = {};
    const item: Record<string, number> = {};
    for (const [k, v] of Object.entries(qty)) {
      const [itemId = '', bucket = ''] = k.split('|');
      row[`${itemId}|${bucket}`] = (row[`${itemId}|${bucket}`] ?? 0) + v;
      item[itemId] = (item[itemId] ?? 0) + v;
    }
    return { row, item };
  }, [qty]);

  const editItems = data ? data.items.filter(editable) : [];
  const over =
    editItems.some((it) => (sums.item[it.item_id] ?? 0) > it.routable_qty) ||
    editItems.some((it) => rowsFor(it).some((r) => (sums.row[r.key] ?? 0) > r.free));
  const total = Object.values(qty).reduce((a, b) => a + b, 0);

  const setCell = (cellKey: string, raw: string) => {
    const n = parseInt(raw, 10);
    setQty((prev) => {
      const rest = Object.fromEntries(Object.entries(prev).filter(([k]) => k !== cellKey));
      return isNaN(n) || n <= 0 ? rest : { ...rest, [cellKey]: n };
    });
  };

  const deptLabel = (deptId: string): { label: string; noWork: boolean } => {
    for (const it of editItems) {
      const d = it.allowed_departments.find((x) => x.field_id === deptId);
      if (d) return { label: d.label, noWork: d.is_no_work };
    }
    return { label: deptId, noWork: false };
  };

  const summary = useMemo(() => {
    const byDept = new Map<string, number>();
    for (const [k, v] of Object.entries(qty)) {
      const dept = k.split('|')[2] ?? '';
      byDept.set(dept, (byDept.get(dept) ?? 0) + v);
    }
    return [...byDept.entries()];
  }, [qty]);

  const submit = () => {
    if (!activeStore) return;
    const lines: StoreRoutingLineIn[] = Object.entries(qty).map(([k, v]) => {
      const [itemId = '', bucket = '', dept = ''] = k.split('|');
      return {
        gs_item_id: itemId,
        source_bucket_field_id: bucket || null,
        department_field_id: dept,
        qty: v,
      };
    });
    setBusy(true);
    setSubmitError(null);
    departmentRoutingApi
      .routeStoreGoods(gsId, { store_id: activeStore.store_id, lines }, idemKey.current)
      .then((res) => {
        setResult(res);
        setQty({});
        setConfirming(false);
        idemKey.current = newIdempotencyKey();
        load();
      })
      .catch((err: unknown) => {
        setSubmitError(toApiError(err));
      })
      .finally(() => {
        setBusy(false);
      });
  };

  if (loading && !data) return <LoadingState label="Loading the goods slip…" />;
  if (error && !data) {
    return (
      <div className="mx-auto max-w-4xl space-y-3 p-4 sm:p-6">
        <Button type="button" variant="outline" className="min-h-[44px]" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Department Routing
        </Button>
        <ErrorState error={error} onRetry={load} title="Could not load the goods slip" />
      </div>
    );
  }
  if (!data) return null;

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6" data-testid="store-routing-gs">
      <PageHeader
        title={`Department Routing · ${data.gs_no}`}
        subtitle={`${data.party_name ?? '—'}${data.station_name ? ` · ${data.station_name}` : ''}`}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" className="min-h-[44px]" onClick={onBack}>
              <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Back
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="min-h-[44px]"
              onClick={() => {
                onOpenGs(data.gs_id);
              }}
            >
              Open goods slip
            </Button>
          </div>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <StatusChip status={data.status} />
        {data.stores.map((p) => (
          <StoreProgressChip key={p.store_id} p={p} />
        ))}
      </div>

      {result ? (
        <div
          role="status"
          className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200"
        >
          <p className="flex items-center gap-2 font-semibold">
            <CheckCircle2 className="h-5 w-5" aria-hidden="true" /> Routing saved for{' '}
            {result.store.store_name}
          </p>
          <p className="mt-1">
            {result.dins.length > 0
              ? `${String(result.dins.length)} Department Issue Note(s) created; print them for the departments.`
              : 'No goods left the store.'}
            {result.no_work_qty > 0
              ? ` ${String(result.no_work_qty)} pc(s) stay in the store (no work).`
              : ''}
          </p>
          {result.dins.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-2">
              {result.dins.map((d) => (
                <Button
                  key={d.id}
                  data-testid="din-print"
                  type="button"
                  variant="outline"
                  className="min-h-[44px]"
                  onClick={() => {
                    onOpenPrint(d.id);
                  }}
                >
                  <Printer className="h-4 w-4" aria-hidden="true" /> {d.routing_no} ·{' '}
                  {d.department_label}
                </Button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {error ? <ErrorState error={error} onRetry={load} title="Could not refresh" /> : null}
      {undoError ? <ErrorState error={undoError} title="The line was not undone" /> : null}

      {myStores.length > 1 ? (
        <div className="flex flex-wrap gap-2" role="group" aria-label="Route for store">
          {myStores.map((s) => (
            <button
              key={s.store_id}
              type="button"
              aria-pressed={activeStore?.store_id === s.store_id}
              onClick={() => {
                setStoreId(s.store_id);
                setQty({});
              }}
              className={`min-h-[44px] rounded-lg px-4 text-sm font-semibold ${
                activeStore?.store_id === s.store_id
                  ? 'bg-indigo-600 text-white'
                  : 'border border-slate-300 bg-white text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200'
              }`}
            >
              {s.store_name}
            </button>
          ))}
        </div>
      ) : null}

      {hasMine && data.items.some((i) => !i.is_mine) ? (
        <label className="flex min-h-[44px] cursor-pointer items-center gap-3 text-sm text-slate-700 dark:text-slate-200">
          <input
            type="checkbox"
            className="h-5 w-5"
            checked={showAll}
            onChange={(e) => {
              setShowAll(e.target.checked);
            }}
          />
          Show all items of this GS (other stores, read-only)
        </label>
      ) : null}

      {visible.length === 0 ? (
        <EmptyState title="No items to show" />
      ) : (
        <ul className="m-0 list-none p-0 space-y-3" aria-label="Items">
          {visible.map((it) => {
            const canEdit = editable(it);
            const itemOver = (sums.item[it.item_id] ?? 0) > it.routable_qty;
            return (
              <li
                key={it.item_id}
                className={`${card} ${it.is_mine ? '' : 'opacity-70'}`}
                data-testid={`routing-item-${String(it.line_no)}`}
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="break-words text-sm font-semibold text-slate-900 dark:text-slate-100">
                      #{it.line_no} {it.sku_code ? `${it.sku_code} · ` : ''}
                      {it.item_name}
                    </div>
                    <div className="text-xs text-slate-500 dark:text-slate-400">
                      {it.received_qty} pcs · to route {it.routable_qty} · at departments{' '}
                      {it.at_departments_qty}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {it.store ? (
                      <Badge variant={it.is_mine ? 'info' : 'neutral'}>{it.store.name}</Badge>
                    ) : null}
                    {!it.acknowledged ? <Badge variant="neutral">Not acknowledged</Badge> : null}
                  </div>
                </div>
                {itemOver ? (
                  <p role="alert" className="mt-1 text-xs font-medium text-rose-600">
                    More than the {it.routable_qty} pcs still to route.
                  </p>
                ) : null}

                {canEdit ? (
                  it.allowed_departments.length === 0 ? (
                    <p className="mt-2 text-xs text-slate-500">
                      No departments are enabled for this product (Admin → Field Profiles).
                    </p>
                  ) : (
                    <div className="mt-3 space-y-3">
                      {rowsFor(it)
                        .filter((r) => r.free > 0)
                        .map((r) => {
                          const used = sums.row[r.key] ?? 0;
                          const rowOver = used > r.free;
                          return (
                            <fieldset
                              key={r.key}
                              className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800/40"
                            >
                              <legend className="sr-only">
                                {r.label} of item {it.line_no}
                              </legend>
                              <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
                                <span className="font-semibold text-slate-800 dark:text-slate-200">
                                  {r.label}
                                  <span className="font-normal text-slate-500 dark:text-slate-400">
                                    {' '}
                                    · {r.current} pcs
                                  </span>
                                </span>
                                <span
                                  className={
                                    rowOver ? 'font-semibold text-rose-600' : 'text-slate-500'
                                  }
                                >
                                  {used} of {r.free} routed
                                </span>
                              </div>
                              <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                                {it.allowed_departments.map((d) => {
                                  const cellKey = `${r.key}|${d.field_id}`;
                                  const inputId = `route-${cellKey}`;
                                  return (
                                    <div
                                      key={d.field_id}
                                      className="flex items-center justify-between gap-2"
                                    >
                                      <label
                                        htmlFor={inputId}
                                        className="min-w-0 text-xs text-slate-700 dark:text-slate-300"
                                      >
                                        {d.label}
                                        {d.is_no_work ? (
                                          <span className="block text-[10px] text-emerald-600 dark:text-emerald-400">
                                            no work · stays in store
                                          </span>
                                        ) : null}
                                      </label>
                                      <input
                                        id={inputId}
                                        type="number"
                                        inputMode="numeric"
                                        min={0}
                                        max={r.free}
                                        value={qty[cellKey] ?? ''}
                                        placeholder="0"
                                        onChange={(e) => {
                                          setCell(cellKey, e.target.value);
                                        }}
                                        className="min-h-[44px] w-20 shrink-0 rounded-lg border border-slate-300 bg-white px-2 text-right text-sm font-semibold text-slate-900 focus:border-indigo-500 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                                      />
                                    </div>
                                  );
                                })}
                              </div>
                            </fieldset>
                          );
                        })}
                    </div>
                  )
                ) : null}
                <RoutedLines item={it} undo={undoProps} />
              </li>
            );
          })}
        </ul>
      )}

      {data.dins.length > 0 ? (
        <section className={card} aria-label="Department Issue Notes">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            Department Issue Notes
          </h2>
          <ul className="mt-2 list-none p-0 space-y-2">
            {data.dins.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <span className="min-w-0 break-words">
                  <strong>{d.routing_no}</strong> · {d.department_label}
                  {d.store_code ? ` · ${d.store_code}` : ''} · sent {d.qty_sent}, back{' '}
                  {d.qty_received}
                </span>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="min-h-[44px]"
                  onClick={() => {
                    onOpenPrint(d.id);
                  }}
                >
                  <Printer className="h-4 w-4" aria-hidden="true" /> Print
                </Button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {editItems.length > 0 ? (
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <span className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-300">
              <ShieldCheck className="h-4 w-4 shrink-0 text-emerald-600" aria-hidden="true" />
              Routing {total} pcs. Saving issues the goods (DIN) and moves the stock.
            </span>
            <Button
              type="button"
              className="min-h-[44px]"
              disabled={total === 0 || over}
              onClick={() => {
                setSubmitError(null);
                setConfirming(true);
              }}
            >
              Save routing
            </Button>
          </div>
        </div>
      ) : null}

      <Modal
        isOpen={confirming}
        onClose={() => {
          if (!busy) setConfirming(false);
        }}
        title="Save routing and issue the goods?"
        footer={
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="outline"
              className="min-h-[44px]"
              disabled={busy}
              onClick={() => {
                setConfirming(false);
              }}
            >
              Back
            </Button>
            <Button type="button" className="min-h-[44px]" isLoading={busy} onClick={submit}>
              Save &amp; issue
            </Button>
          </div>
        }
      >
        <div className="space-y-3 text-sm">
          <p>
            {activeStore?.store_name}: the pieces below leave the store now, one Department Issue
            Note per department. Pieces marked “no work” stay in the store.
          </p>
          <ul className="m-0 list-none p-0 space-y-1">
            {summary.map(([dept, n]) => {
              const d = deptLabel(dept);
              return (
                <li key={dept} className="flex justify-between gap-2">
                  <span>
                    {d.label}
                    {d.noWork ? ' (no work)' : ''}
                  </span>
                  <strong>{n} pcs</strong>
                </li>
              );
            })}
          </ul>
          {submitError ? (
            <ErrorState error={submitError} title="The routing was not saved" />
          ) : null}
        </div>
      </Modal>
    </div>
  );
};
