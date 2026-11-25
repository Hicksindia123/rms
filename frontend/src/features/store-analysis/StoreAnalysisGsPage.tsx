/**
 * Phase P9 (DEC-69; Q15, Q16): the Intermediate Store user analyses ITS goods of one goods slip,
 * per item + current condition: Dispatch New Piece / Dispatch Repaired Piece / Not Allowed (labels
 * and the allowed options come from the product's field profile; Issue CN is Management's, P10).
 * DEC-74: the store may put pieces on "Issue CN Request" (with a qty); submitting sends them to
 * Management, who decides the credit note. The split of each item + condition must total its pieces (G-21). "Submit analysis" sends the
 * store's part in one go; it is final. Any user of a store on the goods slip may send it for
 * Management approval with a reason.
 *
 * By default only the user's own items show; "Show all items of this GS" adds the other stores'
 * items read-only, with their store name and decisions.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, CheckCircle2, Send, ShieldCheck } from 'lucide-react';

import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  LoadingState,
  Modal,
  Textarea,
} from '@/components/ui';
import { PageHeader } from '@/components/erp';
import { newIdempotencyKey, toApiError, type ApiError } from '@/lib/api/client';
import { formatDateTime } from '@/features/goods-slips/format';
import { StatusChip } from '@/features/goods-slips/display';

import { storeAnalysisApi } from './api';
import { StoreAnalysisChip } from './display';
import type {
  AnalysisGroup,
  StoreAnalysisGs,
  StoreAnalysisItem,
  StoreAnalysisLineIn,
} from './types';

interface Props {
  gsId: string;
  onBack: () => void;
  onOpenGs: (gsId: string) => void;
}

const card =
  'rounded-xl border border-slate-200 bg-white p-3 shadow-sm sm:p-4 dark:border-slate-800 dark:bg-slate-900';

const groupKey = (it: StoreAnalysisItem, g: AnalysisGroup) =>
  `${it.gs_item_id}|${g.condition_field_id ?? ''}`;

/** Read-only decisions of a group ("Dispatch New Piece 1 · Not Allowed 1"). */
const Decisions: React.FC<{ group: AnalysisGroup }> = ({ group }) =>
  group.decisions.length === 0 ? (
    <span className="text-slate-500 dark:text-slate-400">Not decided yet</span>
  ) : (
    <span className="text-slate-800 dark:text-slate-200">
      {group.decisions.map((d) => `${d.label} ${String(d.qty)}`).join(' · ')}
    </span>
  );

export const StoreAnalysisGsPage: React.FC<Props> = ({ gsId, onBack, onOpenGs }) => {
  const [data, setData] = useState<StoreAnalysisGs | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [storeId, setStoreId] = useState<string | null>(null);
  // qty per `${itemId}|${conditionId}|${actionCode}`
  const [qty, setQty] = useState<Record<string, number>>({});
  const [confirming, setConfirming] = useState(false);
  const [remarks, setRemarks] = useState('');
  // DEC-71 / Q36: the last store's submission sends the goods slip on to Accounts at once,
  // so a request for Management approval can go with the submission.
  const [alsoSend, setAlsoSend] = useState(false);
  const [sendReason, setSendReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<ApiError | null>(null);
  const [submitted, setSubmitted] = useState<string | null>(null);
  const [approvalOpen, setApprovalOpen] = useState(false);
  const [approvalStore, setApprovalStore] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const [approvalBusy, setApprovalBusy] = useState(false);
  const [approvalError, setApprovalError] = useState<ApiError | null>(null);
  // G-16: one key per command; a retry after a network error reuses it (never submits twice).
  const submitKey = useRef(newIdempotencyKey());
  const approvalKey = useRef(newIdempotencyKey());

  const [reloadKey, setReloadKey] = useState(0);

  // State changes only in the request callbacks (the triggers set `loading`).
  useEffect(() => {
    let active = true;
    storeAnalysisApi
      .getGs(gsId)
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

  // Stores whose part the user may submit now (a Super Admin may see several).
  const myStores = useMemo(
    () => (data ? data.stores.filter((s) => data.submittable_store_ids.includes(s.store_id)) : []),
    [data],
  );
  const activeStore = myStores.find((s) => s.store_id === storeId) ?? myStores[0] ?? null;
  const hasMine = data ? data.items.some((i) => i.is_mine) : false;
  const visible = data ? data.items.filter((i) => showAll || !hasMine || i.is_mine) : [];
  const editable = (it: StoreAnalysisItem) =>
    activeStore !== null && it.is_mine && it.store_id === activeStore.store_id;
  const editItems = data ? data.items.filter(editable) : [];

  const decided = (it: StoreAnalysisItem, g: AnalysisGroup) =>
    it.options.reduce((sum, o) => sum + (qty[`${groupKey(it, g)}|${o.code}`] ?? 0), 0);
  const openGroups = editItems.flatMap((it) =>
    it.groups.filter((g) => g.qty > 0).map((g) => ({ it, g })),
  );
  const unbalanced = openGroups.filter(({ it, g }) => decided(it, g) !== g.qty);
  const ready = openGroups.length > 0 && unbalanced.length === 0;

  // Totals per option for the confirmation (a few lines; computed on render).
  const byCode = new Map<string, { label: string; qty: number }>();
  for (const it of editItems) {
    for (const o of it.options) {
      for (const g of it.groups) {
        const n = qty[`${groupKey(it, g)}|${o.code}`] ?? 0;
        if (n > 0) {
          const t = byCode.get(o.code) ?? { label: o.label, qty: 0 };
          t.qty += n;
          byCode.set(o.code, t);
        }
      }
    }
  }
  const totals = [...byCode.values()];
  // DEC-74: pieces the store puts on "Issue CN Request" go to Management, who decides the CN.
  const cnQty = editItems.reduce(
    (sum, it) =>
      sum +
      it.options
        .filter((o) => o.is_cn_request)
        .reduce(
          (s, o) =>
            s + it.groups.reduce((n, g) => n + (qty[`${groupKey(it, g)}|${o.code}`] ?? 0), 0),
          0,
        ),
    0,
  );
  const note = sendReason.trim();
  const noteInvalid = note.length > 0 && note.length < 3;

  const setCell = (cellKey: string, raw: string) => {
    const n = parseInt(raw, 10);
    setQty((prev) => {
      const rest = Object.fromEntries(Object.entries(prev).filter(([k]) => k !== cellKey));
      return isNaN(n) || n <= 0 ? rest : { ...rest, [cellKey]: n };
    });
  };

  /** Touch shortcut: put every piece of the group on one option. */
  const fillGroup = (it: StoreAnalysisItem, g: AnalysisGroup, code: string) => {
    const prefix = `${groupKey(it, g)}|`;
    setQty((prev) => ({
      ...Object.fromEntries(Object.entries(prev).filter(([k]) => !k.startsWith(prefix))),
      [`${prefix}${code}`]: g.qty,
    }));
  };

  const submit = () => {
    if (!activeStore) return;
    const lines: StoreAnalysisLineIn[] = editItems.flatMap((it) =>
      it.groups
        .filter((g) => g.qty > 0)
        .map((g) => ({
          gs_item_id: it.gs_item_id,
          condition_field_id: g.condition_field_id,
          decisions: it.options
            .map((o) => ({ action_code: o.code, qty: qty[`${groupKey(it, g)}|${o.code}`] ?? 0 }))
            .filter((d) => d.qty > 0),
        })),
    );
    setBusy(true);
    setSubmitError(null);
    storeAnalysisApi
      .submit(
        gsId,
        {
          store_id: activeStore.store_id,
          lines,
          remarks: remarks.trim() || null,
          // DEC-74: with an Issue CN Request the note is optional; otherwise only with "Also send".
          management_approval_reason:
            cnQty > 0 ? note || null : alsoSend ? sendReason.trim() : null,
        },
        submitKey.current,
      )
      .then((d) => {
        setData(d);
        setSubmitted(activeStore.store_name);
        setQty({});
        setRemarks('');
        setAlsoSend(false);
        setSendReason('');
        setConfirming(false);
        submitKey.current = newIdempotencyKey();
      })
      .catch((err: unknown) => {
        setSubmitError(toApiError(err));
      })
      .finally(() => {
        setBusy(false);
      });
  };

  const sendForApproval = () => {
    const store = approvalStore ?? data?.approval_store_ids[0];
    if (!store) return;
    setApprovalBusy(true);
    setApprovalError(null);
    storeAnalysisApi
      .requestApproval(gsId, store, reason.trim(), approvalKey.current)
      .then((d) => {
        setData(d);
        setApprovalOpen(false);
        setReason('');
        approvalKey.current = newIdempotencyKey();
      })
      .catch((err: unknown) => {
        setApprovalError(toApiError(err));
      })
      .finally(() => {
        setApprovalBusy(false);
      });
  };

  if (loading && !data) return <LoadingState label="Loading the goods slip…" />;
  if (error && !data) {
    return (
      <div className="mx-auto max-w-4xl space-y-3 p-4 sm:p-6">
        <Button type="button" variant="outline" className="min-h-[44px]" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Analysis
        </Button>
        <ErrorState error={error} onRetry={load} title="Could not load the goods slip" />
      </div>
    );
  }
  if (!data) return null;

  const storeName = (id: string) => data.stores.find((s) => s.store_id === id)?.store_name ?? id;
  const request = data.open_approval_request ?? null;

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6" data-testid="store-analysis-gs">
      <PageHeader
        title={`Analysis · ${data.gs_no}`}
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
        {data.stores.map((s) => (
          <StoreAnalysisChip key={s.store_id} s={s} />
        ))}
      </div>

      {submitted ? (
        <div
          role="status"
          className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200"
        >
          <p className="flex items-center gap-2 font-semibold">
            <CheckCircle2 className="h-5 w-5" aria-hidden="true" /> Analysis submitted for{' '}
            {submitted}
          </p>
          <p className="mt-1">
            {data.status === 'ANALYSIS_COMPLETED'
              ? 'Every store has submitted: the goods slip waits for Management approval.'
              : data.status === 'ACCOUNTS_PENDING'
                ? 'Every store has submitted: the goods slip has gone to Accounts.'
                : data.status === 'NOT_ALLOWED_HOLD'
                  ? 'Every store has submitted: everything is Not Allowed, so the goods slip is on hold.'
                  : 'The goods slip waits for the other stores.'}
          </p>
        </div>
      ) : null}

      {request ? (
        <div
          role="status"
          className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
          data-testid="approval-request"
        >
          <p className="font-semibold">Sent for Management approval</p>
          <p className="mt-1 break-words">
            {request.requested_by_name ?? 'A store user'} ({request.store_name}),{' '}
            {formatDateTime(request.requested_at)}: “{request.reason}”
          </p>
        </div>
      ) : null}

      {error ? <ErrorState error={error} onRetry={load} title="Could not refresh" /> : null}

      {myStores.length > 1 ? (
        <div className="flex flex-wrap gap-2" role="group" aria-label="Analyse for store">
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
        <ul className="m-0 list-none space-y-3 p-0" aria-label="Items">
          {visible.map((it) => {
            const canEdit = editable(it);
            return (
              <li
                key={it.gs_item_id}
                className={`${card} ${it.is_mine ? '' : 'opacity-70'}`}
                data-testid={`analysis-item-${String(it.line_no)}`}
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="break-words text-sm font-semibold text-slate-900 dark:text-slate-100">
                      #{it.line_no} {it.product_code ? `${it.product_code} · ` : ''}
                      {it.product_name}
                    </div>
                    <div className="text-xs text-slate-500 dark:text-slate-400">
                      {it.received_qty} pcs
                      {it.outcomes.length > 0
                        ? ` · back from departments: ${it.outcomes
                            .map((o) => `${o.outcome_label} ${String(o.qty)}`)
                            .join(', ')}`
                        : ''}
                    </div>
                  </div>
                  {it.store_name ? (
                    <Badge variant={it.is_mine ? 'info' : 'neutral'}>{it.store_name}</Badge>
                  ) : null}
                </div>

                <div className="mt-3 space-y-3">
                  {it.groups.map((g) => {
                    const gk = groupKey(it, g);
                    const done = decided(it, g);
                    const balanced = done === g.qty;
                    return (
                      <fieldset
                        key={gk}
                        className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800/40"
                      >
                        <legend className="sr-only">
                          {g.condition_label ?? 'All pieces'} of item {it.line_no}
                        </legend>
                        <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
                          <span className="font-semibold text-slate-800 dark:text-slate-200">
                            {g.condition_label ?? 'All pieces'}
                            <span className="font-normal text-slate-500 dark:text-slate-400">
                              {' '}
                              · {g.qty} pcs
                            </span>
                          </span>
                          {canEdit ? (
                            <span
                              className={
                                balanced
                                  ? 'font-semibold text-emerald-700 dark:text-emerald-400'
                                  : done > g.qty
                                    ? 'font-semibold text-rose-600'
                                    : 'text-slate-500'
                              }
                            >
                              {done} of {g.qty} decided
                            </span>
                          ) : (
                            <Decisions group={g} />
                          )}
                        </div>
                        {canEdit && g.qty > 0 ? (
                          it.options.length === 0 ? (
                            <p className="mt-2 text-xs text-slate-500">
                              No analysis options are enabled for this product (Admin → Field
                              Profiles).
                            </p>
                          ) : (
                            <div
                              className={`mt-2 grid grid-cols-1 gap-2 ${
                                it.options.length > 3
                                  ? 'sm:grid-cols-2 lg:grid-cols-4'
                                  : 'sm:grid-cols-3'
                              }`}
                            >
                              {it.options.map((o) => {
                                const cellKey = `${gk}|${o.code}`;
                                return (
                                  <div
                                    key={o.code}
                                    className="flex items-center justify-between gap-2"
                                  >
                                    <button
                                      type="button"
                                      aria-label={`All ${String(g.qty)} pcs: ${o.label}`}
                                      title={
                                        o.is_cn_request
                                          ? 'Management decides the credit note for these pieces'
                                          : undefined
                                      }
                                      onClick={() => {
                                        fillGroup(it, g, o.code);
                                      }}
                                      className={`min-h-[44px] min-w-0 flex-1 rounded-lg px-2 text-left text-xs ${
                                        o.is_cn_request
                                          ? 'font-semibold text-amber-800 hover:bg-amber-50 dark:text-amber-300 dark:hover:bg-amber-950/40'
                                          : 'text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
                                      }`}
                                    >
                                      {o.label}
                                      {o.is_cn_request ? (
                                        <span className="block text-[11px] font-normal text-slate-500 dark:text-slate-400">
                                          to Management
                                        </span>
                                      ) : null}
                                    </button>
                                    <input
                                      aria-label={`${o.label}, ${g.condition_label ?? 'all pieces'}, item ${String(it.line_no)}`}
                                      type="number"
                                      inputMode="numeric"
                                      min={0}
                                      max={g.qty}
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
                          )
                        ) : null}
                      </fieldset>
                    );
                  })}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {data.stores
        .filter((s) => s.analysis_status === 'SUBMITTED')
        .map((s) => (
          <p key={s.store_id} className="text-xs text-slate-500 dark:text-slate-400">
            {s.store_name}: submitted by {s.submitted_by_name ?? '—'}
            {s.submitted_at ? `, ${formatDateTime(s.submitted_at)}` : ''}
            {s.remarks ? ` · “${s.remarks}”` : ''}
          </p>
        ))}

      {editItems.length > 0 || data.can_request_approval ? (
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            {editItems.length > 0 ? (
              <span className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-300">
                <ShieldCheck className="h-4 w-4 shrink-0 text-emerald-600" aria-hidden="true" />
                {ready
                  ? 'Every piece has its decision. Submitting is final for your store.'
                  : `${String(unbalanced.length)} item condition(s) still to decide.`}
              </span>
            ) : (
              <span className="text-xs text-slate-600 dark:text-slate-300">
                Management can review this goods slip and decide a credit note.
              </span>
            )}
            <div className="flex flex-col gap-2 sm:flex-row">
              {data.can_request_approval ? (
                <Button
                  type="button"
                  variant="outline"
                  className="min-h-[44px]"
                  onClick={() => {
                    setApprovalError(null);
                    setApprovalStore(data.approval_store_ids[0] ?? null);
                    setApprovalOpen(true);
                  }}
                >
                  <Send className="h-4 w-4" aria-hidden="true" /> Send for Management Approval
                </Button>
              ) : null}
              {editItems.length > 0 ? (
                <Button
                  type="button"
                  className="min-h-[44px]"
                  disabled={!ready}
                  onClick={() => {
                    setSubmitError(null);
                    setConfirming(true);
                  }}
                >
                  Submit analysis
                </Button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      <Modal
        isOpen={confirming}
        onClose={() => {
          if (!busy) setConfirming(false);
        }}
        title="Submit the analysis?"
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
            <Button
              type="button"
              className="min-h-[44px]"
              isLoading={busy}
              disabled={cnQty > 0 ? noteInvalid : alsoSend && sendReason.trim().length < 3}
              onClick={submit}
            >
              {cnQty > 0
                ? 'Submit & send CN request'
                : alsoSend
                  ? 'Submit & send for approval'
                  : 'Submit'}
            </Button>
          </div>
        }
      >
        <div className="space-y-3 text-sm">
          <p>
            {activeStore?.store_name}: your decisions for this goods slip. After submitting they can
            only be changed by Management.
          </p>
          <ul className="m-0 list-none space-y-1 p-0">
            {totals.map((t) => (
              <li key={t.label} className="flex justify-between gap-2">
                <span>{t.label}</span>
                <strong>{t.qty} pcs</strong>
              </li>
            ))}
          </ul>
          <label
            className="block text-xs font-medium text-slate-700 dark:text-slate-300"
            htmlFor="analysis-remarks"
          >
            Remarks (optional)
          </label>
          <Textarea
            id="analysis-remarks"
            value={remarks}
            maxLength={500}
            rows={2}
            onChange={(e) => {
              setRemarks(e.target.value);
            }}
          />
          {cnQty > 0 ? (
            <>
              <p
                className="m-0 rounded-lg bg-amber-50 p-3 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
                data-testid="cn-request-notice"
              >
                {cnQty} pc(s) go to Management as an Issue CN Request. Management decides the credit
                note (or another action) for them; the goods slip waits for that decision before
                Accounts.
                {data.open_approval_request
                  ? ' The goods slip is already waiting for Management; your request is added.'
                  : ''}
              </p>
              <label
                className="block text-xs font-medium text-slate-700 dark:text-slate-300"
                htmlFor="analysis-cn-note"
              >
                Note for Management (optional)
              </label>
              <Textarea
                id="analysis-cn-note"
                value={sendReason}
                maxLength={400}
                rows={2}
                onChange={(e) => {
                  setSendReason(e.target.value);
                }}
              />
              {noteInvalid ? (
                <p className="m-0 text-xs text-rose-600">
                  Write at least 3 characters, or leave it empty.
                </p>
              ) : null}
            </>
          ) : data.open_approval_request ? null : (
            <>
              <label className="flex min-h-[44px] cursor-pointer items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="h-5 w-5"
                  checked={alsoSend}
                  onChange={(e) => {
                    setAlsoSend(e.target.checked);
                  }}
                />
                Also send for Management approval
              </label>
              {alsoSend ? (
                <>
                  <label
                    className="block text-xs font-medium text-slate-700 dark:text-slate-300"
                    htmlFor="analysis-approval-reason"
                  >
                    Reason for Management (required)
                  </label>
                  <Textarea
                    id="analysis-approval-reason"
                    value={sendReason}
                    maxLength={500}
                    rows={2}
                    onChange={(e) => {
                      setSendReason(e.target.value);
                    }}
                  />
                </>
              ) : (
                <p className="m-0 text-xs text-slate-500">
                  Without it, the goods slip goes on to Accounts once every store has submitted.
                </p>
              )}
            </>
          )}
          {submitError ? (
            <ErrorState error={submitError} title="The analysis was not submitted" />
          ) : null}
        </div>
      </Modal>

      <Modal
        isOpen={approvalOpen}
        onClose={() => {
          if (!approvalBusy) setApprovalOpen(false);
        }}
        title="Send for Management approval"
        footer={
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="outline"
              className="min-h-[44px]"
              disabled={approvalBusy}
              onClick={() => {
                setApprovalOpen(false);
              }}
            >
              Back
            </Button>
            <Button
              type="button"
              className="min-h-[44px]"
              isLoading={approvalBusy}
              disabled={reason.trim().length < 3}
              onClick={sendForApproval}
            >
              Send
            </Button>
          </div>
        }
      >
        <div className="space-y-3 text-sm">
          <p>
            Management reviews the goods slip and may change any decision, including a credit note.
          </p>
          {data.approval_store_ids.length > 1 ? (
            <div className="flex flex-wrap gap-2" role="group" aria-label="Send as store">
              {data.approval_store_ids.map((id) => (
                <button
                  key={id}
                  type="button"
                  aria-pressed={(approvalStore ?? data.approval_store_ids[0]) === id}
                  onClick={() => {
                    setApprovalStore(id);
                  }}
                  className={`min-h-[44px] rounded-lg px-4 text-sm font-semibold ${
                    (approvalStore ?? data.approval_store_ids[0]) === id
                      ? 'bg-indigo-600 text-white'
                      : 'border border-slate-300 bg-white text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200'
                  }`}
                >
                  {storeName(id)}
                </button>
              ))}
            </div>
          ) : null}
          <label
            className="block text-xs font-medium text-slate-700 dark:text-slate-300"
            htmlFor="approval-reason"
          >
            Reason (required)
          </label>
          <Textarea
            id="approval-reason"
            value={reason}
            maxLength={500}
            rows={3}
            onChange={(e) => {
              setReason(e.target.value);
            }}
          />
          {approvalError ? (
            <ErrorState error={approvalError} title="The goods slip was not sent" />
          ) : null}
        </div>
      </Modal>
    </div>
  );
};
