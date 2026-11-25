/**
 * Store analysis of one goods slip by the Intermediate Store user (DEC-69, DEC-75).
 *
 * 1. Per item + current condition the user first splits the pieces into the two verdicts
 *    (Allowed / Not Allowed; labels and the actions under each come from the setting
 *    store_analysis.verdicts).
 * 2. Allowed pieces are split between the Allowed actions (Send New Pieces to Party / Send Repaired
 *    Pieces to Party). Not Allowed needs no more input.
 * 3. Optionally, pieces go to Management with a proposal (Send New Pieces / Issue CN) — with the
 *    submission or later, until Accounts completes the goods slip. Nothing selected = nothing goes
 *    to Management and the goods slip goes on to Accounts once every store has submitted.
 * Every item + condition must total its pieces (G-21). Submitting is final for the store.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeft,
  CheckCircle2,
  CircleSlash,
  ClipboardCheck,
  ExternalLink,
  Send,
  ShieldCheck,
  ThumbsUp,
  UserCheck,
} from 'lucide-react';

import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  LoadingState,
  Modal,
  QtyStepper,
  Textarea,
  toast,
} from '@/components/ui';
import { PageHeader } from '@/components/erp';
import { newIdempotencyKey, toApiError, type ApiError } from '@/lib/api/client';
import { cn } from '@/lib/utils';
import { formatDateTime } from '@/features/goods-slips/format';
import { StatusChip } from '@/features/goods-slips/display';

import { storeAnalysisApi } from './api';
import { StoreAnalysisChip } from './display';
import { ManagementPicker } from './ManagementPicker';
import { pickSummary, picksToLines, type PickRow, type Picks } from './picks';
import type {
  AnalysisGroup,
  AnalysisOption,
  ManagementRequestLine,
  StoreAnalysisGs,
  StoreAnalysisItem,
  StoreAnalysisLineIn,
} from './types';

interface Props {
  gsId: string;
  onBack: () => void;
  onOpenGs: (gsId: string) => void;
}

const groupKey = (it: StoreAnalysisItem, g: AnalysisGroup) =>
  `${it.gs_item_id}|${g.condition_field_id ?? ''}`;

type Decided = { code: string; label: string; qty: number }[];

/** Read-only decisions of a group as chips. */
const DecisionChips: React.FC<{ group: AnalysisGroup; allowed: string[] }> = ({
  group,
  allowed,
}) =>
  group.decisions.length === 0 ? (
    <span className="text-xs text-slate-500">Not decided yet</span>
  ) : (
    <div className="flex flex-wrap gap-1.5">
      {group.decisions.map((d) => (
        <Badge key={d.action_code} variant={allowed.includes(d.action_code) ? 'success' : 'danger'}>
          {d.label} · {d.qty}
        </Badge>
      ))}
    </div>
  );

/** Pieces already sent to Management for a group. */
const SentLines: React.FC<{ lines: ManagementRequestLine[] }> = ({ lines }) =>
  lines.length === 0 ? null : (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {lines.map((l) => (
        <Badge key={l.id} variant="purple">
          {l.qty} pcs {l.from_action_label} → {l.proposed_action_label} (with Management)
        </Badge>
      ))}
    </div>
  );

export const StoreAnalysisGsPage: React.FC<Props> = ({ gsId, onBack, onOpenGs }) => {
  const [data, setData] = useState<StoreAnalysisGs | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [storeId, setStoreId] = useState<string | null>(null);
  // Allowed pieces per group key (undefined = verdict not given yet).
  const [allowedQty, setAllowedQty] = useState<Record<string, number>>({});
  // Split of a verdict between its actions: `${groupKey}|${actionCode}` -> qty.
  const [split, setSplit] = useState<Record<string, number>>({});
  // Pieces sent to Management with the submission.
  const [picks, setPicks] = useState<Picks>({});
  const [confirming, setConfirming] = useState(false);
  const [remarks, setRemarks] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<ApiError | null>(null);
  const [submitted, setSubmitted] = useState<string | null>(null);
  // Sending after the submission.
  const [sendOpen, setSendOpen] = useState(false);
  const [sendPicks, setSendPicks] = useState<Picks>({});
  const [sendNote, setSendNote] = useState('');
  const [sendBusy, setSendBusy] = useState(false);
  const [sendError, setSendError] = useState<ApiError | null>(null);
  // G-16: one key per command; a retry after a network error reuses it (never submits twice).
  const submitKey = useRef(newIdempotencyKey());
  const sendKey = useRef(newIdempotencyKey());
  const [reloadKey, setReloadKey] = useState(0);

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

  const verdicts = data?.verdicts ?? null;
  const allowedCodes = useMemo(() => verdicts?.allowed.actions ?? [], [verdicts]);
  const notAllowedCodes = useMemo(() => verdicts?.not_allowed.actions ?? [], [verdicts]);
  const proposals = data?.proposals ?? [];

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

  const optsOf = (it: StoreAnalysisItem, codes: string[]): AnalysisOption[] =>
    it.options.filter((o) => codes.includes(o.code));

  /** The decisions a group currently adds up to (from the verdict + split), or null if open. */
  const decidedOf = (it: StoreAnalysisItem, g: AnalysisGroup): Decided | null => {
    const gk = groupKey(it, g);
    const a = allowedQty[gk];
    if (a === undefined) return null;
    const out: Decided = [];
    const add = (opts: AnalysisOption[], total: number): boolean => {
      if (total === 0) return true;
      if (opts.length === 0) return false;
      if (opts.length === 1 && opts[0]) {
        out.push({ code: opts[0].code, label: opts[0].label, qty: total });
        return true;
      }
      let sum = 0;
      for (const o of opts) {
        const n = split[`${gk}|${o.code}`] ?? 0;
        if (n > 0) out.push({ code: o.code, label: o.label, qty: n });
        sum += n;
      }
      return sum === total;
    };
    const okA = add(optsOf(it, allowedCodes), a);
    const okN = add(optsOf(it, notAllowedCodes), g.qty - a);
    return okA && okN ? out : null;
  };

  const openGroups = editItems.flatMap((it) =>
    it.groups.filter((g) => g.qty > 0).map((g) => ({ it, g })),
  );
  const pending = openGroups.filter(({ it, g }) => decidedOf(it, g) === null);
  const ready = openGroups.length > 0 && pending.length === 0;
  const progress = openGroups.length
    ? Math.round(((openGroups.length - pending.length) / openGroups.length) * 100)
    : 0;

  // Rows the store may send with the submission: its own decided pieces.
  const submitRows: PickRow[] = openGroups.flatMap(({ it, g }) =>
    (decidedOf(it, g) ?? []).map((d) => ({
      key: `${groupKey(it, g)}|${d.code}`,
      gs_item_id: it.gs_item_id,
      condition_field_id: g.condition_field_id,
      line_no: it.line_no,
      product_name: it.product_name,
      condition_label: g.condition_label,
      from_code: d.code,
      from_label: d.label,
      max: d.qty,
    })),
  );
  const submitPick = pickSummary(submitRows, picks);

  // Rows the store may send after the submission (its submitted stores, free pieces only).
  const sendRows: PickRow[] = data
    ? data.items
        .filter((it) => it.is_mine && it.store_id && data.approval_store_ids.includes(it.store_id))
        .flatMap((it) =>
          it.groups.flatMap((g) =>
            (g.sendable ?? [])
              .filter((s) => s.free_qty > 0)
              .map((s) => ({
                key: `${groupKey(it, g)}|${s.action_code}`,
                gs_item_id: it.gs_item_id,
                condition_field_id: g.condition_field_id,
                line_no: it.line_no,
                product_name: it.product_name,
                condition_label: g.condition_label,
                from_code: s.action_code,
                from_label: s.label,
                max: s.free_qty,
              })),
          ),
        )
    : [];
  const sendPick = pickSummary(sendRows, sendPicks);

  // Totals per action for the confirmation.
  const totals = new Map<string, { label: string; qty: number; allowed: boolean }>();
  for (const { it, g } of openGroups) {
    for (const d of decidedOf(it, g) ?? []) {
      const t = totals.get(d.code) ?? {
        label: d.label,
        qty: 0,
        allowed: allowedCodes.includes(d.code),
      };
      t.qty += d.qty;
      totals.set(d.code, t);
    }
  }
  const allowedTotal = [...totals.values()].filter((t) => t.allowed).reduce((s, t) => s + t.qty, 0);
  const notAllowedTotal = [...totals.values()]
    .filter((t) => !t.allowed)
    .reduce((s, t) => s + t.qty, 0);

  const setVerdict = (it: StoreAnalysisItem, g: AnalysisGroup, allowed: number) => {
    const gk = groupKey(it, g);
    setAllowedQty((prev) => ({ ...prev, [gk]: allowed }));
    // A new verdict split invalidates the action split and the picks of this group.
    setSplit((prev) =>
      Object.fromEntries(Object.entries(prev).filter(([k]) => !k.startsWith(`${gk}|`))),
    );
    setPicks((prev) =>
      Object.fromEntries(Object.entries(prev).filter(([k]) => !k.startsWith(`${gk}|`))),
    );
  };

  const setSplitQty = (gk: string, code: string, qty: number) => {
    setSplit((prev) => ({ ...prev, [`${gk}|${code}`]: qty }));
    setPicks((prev) =>
      Object.fromEntries(Object.entries(prev).filter(([k]) => k !== `${gk}|${code}`)),
    );
  };

  const fillSplit = (gk: string, opts: AnalysisOption[], code: string, total: number) => {
    setSplit((prev) => {
      const next = { ...prev };
      for (const o of opts) next[`${gk}|${o.code}`] = o.code === code ? total : 0;
      return next;
    });
  };

  const resetDraft = () => {
    setAllowedQty({});
    setSplit({});
    setPicks({});
    setRemarks('');
    setNote('');
  };

  const submit = () => {
    if (!activeStore) return;
    const lines: StoreAnalysisLineIn[] = openGroups.map(({ it, g }) => ({
      gs_item_id: it.gs_item_id,
      condition_field_id: g.condition_field_id,
      decisions: (decidedOf(it, g) ?? []).map((d) => ({ action_code: d.code, qty: d.qty })),
    }));
    const mlines = picksToLines(submitRows, picks);
    setBusy(true);
    setSubmitError(null);
    storeAnalysisApi
      .submit(
        gsId,
        {
          store_id: activeStore.store_id,
          lines,
          remarks: remarks.trim() || null,
          management_lines: mlines,
          management_approval_reason: mlines.length > 0 && note.trim() ? note.trim() : null,
        },
        submitKey.current,
      )
      .then((d) => {
        setData(d);
        setSubmitted(activeStore.store_name);
        resetDraft();
        setConfirming(false);
        submitKey.current = newIdempotencyKey();
        toast.success(
          'Analysis submitted',
          mlines.length > 0
            ? `${String(submitPick.pcs)} pcs sent for Management approval.`
            : `${activeStore.store_name}: your decisions are recorded.`,
        );
      })
      .catch((err: unknown) => {
        setSubmitError(toApiError(err));
      })
      .finally(() => {
        setBusy(false);
      });
  };

  const sendToManagement = () => {
    const lines = picksToLines(sendRows, sendPicks);
    if (lines.length === 0) return;
    setSendBusy(true);
    setSendError(null);
    storeAnalysisApi
      .sendToManagement(gsId, lines, sendNote.trim() || null, sendKey.current)
      .then((d) => {
        setData(d);
        setSendOpen(false);
        setSendPicks({});
        setSendNote('');
        sendKey.current = newIdempotencyKey();
        toast.success(
          'Sent for Management approval',
          `${String(sendPick.items)} item(s) · ${String(sendPick.pcs)} pcs`,
        );
      })
      .catch((err: unknown) => {
        setSendError(toApiError(err));
      })
      .finally(() => {
        setSendBusy(false);
      });
  };

  if (loading && !data) return <LoadingState label="Loading the goods slip…" />;
  if (error && !data) {
    return (
      <div className="mx-auto max-w-5xl space-y-3 p-4 sm:p-6">
        <Button type="button" variant="outline" className="min-h-[44px]" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Analysis
        </Button>
        <ErrorState error={error} onRetry={load} title="Could not load the goods slip" />
      </div>
    );
  }
  if (!data) return null;

  const allowedLabel = verdicts?.allowed.label ?? 'Allowed';
  const notAllowedLabel = verdicts?.not_allowed.label ?? 'Not Allowed';
  const sentLines = data.request_lines ?? [];
  const noteInvalid = note.trim().length > 0 && note.trim().length < 3;
  const sendNoteInvalid = sendNote.trim().length > 0 && sendNote.trim().length < 3;

  return (
    <div
      className="mx-auto max-w-5xl space-y-4 p-4 pb-28 sm:p-6 sm:pb-28"
      data-testid="store-analysis-gs"
    >
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            Analysis <span className="font-mono text-indigo-600">{data.gs_no}</span>
          </span>
        }
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
              <ExternalLink className="h-4 w-4" aria-hidden="true" /> Open goods slip
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
          className="flex items-start gap-3 rounded-2xl border border-emerald-200 bg-gradient-to-r from-emerald-50 to-white p-4 text-sm text-emerald-900"
        >
          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" aria-hidden="true" />
          <div>
            <p className="m-0 font-semibold">Analysis submitted for {submitted}</p>
            <p className="m-0 mt-1 text-emerald-800">
              {data.status === 'ANALYSIS_COMPLETED'
                ? 'Every store has submitted. The goods slip waits for Management approval.'
                : data.status === 'ACCOUNTS_PENDING'
                  ? 'Every store has submitted. The goods slip has gone to Accounts with its action sheet.'
                  : data.status === 'NOT_ALLOWED_HOLD'
                    ? 'Every store has submitted. Everything is Not Allowed, so the goods slip is on hold.'
                    : 'The goods slip waits for the other stores.'}
            </p>
          </div>
        </div>
      ) : null}

      {sentLines.some((l) => l.request_status === 'OPEN') ? (
        <section
          className="rounded-2xl border border-violet-200 bg-gradient-to-br from-violet-50 to-white p-4"
          data-testid="approval-request"
          aria-label="Waiting for Management"
        >
          <p className="m-0 flex items-center gap-2 text-sm font-semibold text-violet-900">
            <UserCheck className="h-4 w-4" aria-hidden="true" /> With Management for approval
          </p>
          <ul className="m-0 mt-2 list-none space-y-1 p-0 text-sm text-violet-900/90">
            {sentLines
              .filter((l) => l.request_status === 'OPEN')
              .map((l) => (
                <li key={l.id} className="break-words">
                  <span className="font-semibold">
                    #{l.line_no} {l.product_name}
                  </span>
                  {l.condition_label ? ` · ${l.condition_label}` : ''}: {l.qty} pcs{' '}
                  {l.from_action_label} → <strong>{l.proposed_action_label}</strong>
                  <span className="text-violet-700/80">
                    {' '}
                    · {l.requested_by_name ?? 'Store user'}, {formatDateTime(l.requested_at)}
                  </span>
                </li>
              ))}
          </ul>
        </section>
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
                resetDraft();
              }}
              className={cn(
                'min-h-[44px] rounded-xl px-4 text-sm font-semibold transition-all',
                activeStore?.store_id === s.store_id
                  ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/20'
                  : 'border border-slate-200 bg-white text-slate-700 hover:border-indigo-300',
              )}
            >
              {s.store_name}
            </button>
          ))}
        </div>
      ) : null}

      {editItems.length > 0 ? (
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span className="flex items-center gap-2 font-semibold text-slate-800">
              <ClipboardCheck className="h-4 w-4 text-indigo-600" aria-hidden="true" />
              {openGroups.length - pending.length} of {openGroups.length} decided
            </span>
            <span className="text-xs text-slate-500">
              Step 1: {allowedLabel} / {notAllowedLabel} · Step 2: what goes to the party
            </span>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
            <div
              className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-emerald-500 transition-all duration-500"
              style={{ width: `${String(progress)}%` }}
            />
          </div>
        </div>
      ) : null}

      {hasMine && data.items.some((i) => !i.is_mine) ? (
        <label className="flex min-h-[44px] cursor-pointer items-center gap-3 text-sm text-slate-700">
          <input
            type="checkbox"
            className="h-5 w-5 accent-indigo-600"
            checked={showAll}
            onChange={(e) => {
              setShowAll(e.target.checked);
            }}
          />
          Show all items of this goods slip (other stores, read-only)
        </label>
      ) : null}

      {visible.length === 0 ? (
        <EmptyState title="No items to show" />
      ) : (
        <ul className="m-0 list-none space-y-3 p-0" aria-label="Items">
          {visible.map((it) => {
            const canEdit = editable(it);
            const aOpts = optsOf(it, allowedCodes);
            const nOpts = optsOf(it, notAllowedCodes);
            return (
              <li
                key={it.gs_item_id}
                className={cn(
                  'overflow-hidden rounded-2xl border bg-white shadow-sm',
                  it.is_mine ? 'border-slate-200' : 'border-slate-200/70 opacity-75',
                )}
                data-testid={`analysis-item-${String(it.line_no)}`}
              >
                <div className="flex flex-wrap items-start justify-between gap-2 border-b border-slate-100 bg-slate-50/60 px-4 py-3">
                  <div className="min-w-0">
                    <div className="break-words text-sm font-semibold text-slate-900">
                      <span className="text-slate-400">#{it.line_no}</span>{' '}
                      {it.product_code ? (
                        <span className="font-mono text-xs text-slate-500">
                          {it.product_code} ·{' '}
                        </span>
                      ) : null}
                      {it.product_name}
                    </div>
                    <div className="mt-0.5 text-xs text-slate-500">
                      {it.received_qty} pcs received
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

                <div className="divide-y divide-slate-100">
                  {it.groups.map((g) => {
                    const gk = groupKey(it, g);
                    const a = allowedQty[gk];
                    const decided = canEdit ? decidedOf(it, g) : null;
                    const n = a === undefined ? undefined : g.qty - a;
                    const aSplit = aOpts.reduce((s, o) => s + (split[`${gk}|${o.code}`] ?? 0), 0);
                    const nSplit = nOpts.reduce((s, o) => s + (split[`${gk}|${o.code}`] ?? 0), 0);
                    return (
                      <fieldset key={gk} className="m-0 min-w-0 border-0 p-4">
                        <legend className="sr-only">
                          {g.condition_label ?? 'All pieces'} of item {it.line_no}
                        </legend>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="text-sm font-semibold text-slate-800">
                            {g.condition_label ?? 'All pieces'}
                            <span className="ml-1.5 rounded-full bg-slate-100 px-2 py-0.5 font-mono text-xs font-semibold text-slate-600">
                              {g.qty} pcs
                            </span>
                          </span>
                          {canEdit && g.qty > 0 ? (
                            decided ? (
                              <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-700">
                                <CheckCircle2 className="h-4 w-4" aria-hidden="true" /> Decided
                              </span>
                            ) : (
                              <span className="text-xs font-medium text-amber-700">To decide</span>
                            )
                          ) : null}
                        </div>

                        {!canEdit || g.qty === 0 ? (
                          <div className="mt-2">
                            <DecisionChips group={g} allowed={allowedCodes} />
                            <SentLines lines={g.management_lines ?? []} />
                          </div>
                        ) : aOpts.length + nOpts.length === 0 ? (
                          <p className="m-0 mt-2 text-xs text-slate-500">
                            No analysis options are enabled for this product.
                          </p>
                        ) : (
                          <div className="mt-3 space-y-3">
                            {/* Step 1: verdict */}
                            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                              <div
                                className={cn(
                                  'flex flex-wrap items-center justify-between gap-2 rounded-xl border-2 p-2.5 transition-colors sm:p-3',
                                  a !== undefined && a > 0
                                    ? 'border-emerald-400 bg-emerald-50/70'
                                    : 'border-slate-200 bg-white',
                                )}
                              >
                                <button
                                  type="button"
                                  disabled={aOpts.length === 0}
                                  onClick={() => {
                                    setVerdict(it, g, g.qty);
                                  }}
                                  className="flex min-h-[44px] min-w-[7.5rem] flex-1 items-center gap-2 rounded-lg border-0 bg-transparent p-0 text-left text-sm font-semibold text-emerald-800 disabled:cursor-not-allowed disabled:opacity-40"
                                  aria-label={`All ${String(g.qty)} pcs ${allowedLabel}`}
                                >
                                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-emerald-500 text-white">
                                    <ThumbsUp className="h-4 w-4" aria-hidden="true" />
                                  </span>
                                  {allowedLabel}
                                </button>
                                <QtyStepper
                                  tone="success"
                                  value={a ?? 0}
                                  max={aOpts.length === 0 ? 0 : g.qty}
                                  min={0}
                                  disabled={aOpts.length === 0}
                                  label={`${allowedLabel} pieces, ${g.condition_label ?? 'all pieces'}, item ${String(it.line_no)}`}
                                  onChange={(v) => {
                                    setVerdict(it, g, nOpts.length === 0 ? g.qty : v);
                                  }}
                                />
                              </div>
                              <div
                                className={cn(
                                  'flex flex-wrap items-center justify-between gap-2 rounded-xl border-2 p-2.5 transition-colors sm:p-3',
                                  n !== undefined && n > 0
                                    ? 'border-rose-400 bg-rose-50/70'
                                    : 'border-slate-200 bg-white',
                                )}
                              >
                                <button
                                  type="button"
                                  disabled={nOpts.length === 0}
                                  onClick={() => {
                                    setVerdict(it, g, 0);
                                  }}
                                  className="flex min-h-[44px] min-w-[7.5rem] flex-1 items-center gap-2 rounded-lg border-0 bg-transparent p-0 text-left text-sm font-semibold text-rose-800 disabled:cursor-not-allowed disabled:opacity-40"
                                  aria-label={`All ${String(g.qty)} pcs ${notAllowedLabel}`}
                                >
                                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-rose-500 text-white">
                                    <CircleSlash className="h-4 w-4" aria-hidden="true" />
                                  </span>
                                  {notAllowedLabel}
                                </button>
                                <span
                                  className="grid h-11 min-w-[3.5rem] place-items-center rounded-xl bg-white px-3 font-mono text-base font-semibold tabular-nums text-slate-900 ring-1 ring-slate-200"
                                  aria-label={`${notAllowedLabel} pieces, ${g.condition_label ?? 'all pieces'}, item ${String(it.line_no)}`}
                                >
                                  {n ?? 0}
                                </span>
                              </div>
                            </div>

                            {/* Step 2: split the Allowed pieces between its actions */}
                            {a !== undefined && a > 0 && aOpts.length > 1 ? (
                              <div className="rounded-xl bg-emerald-50/50 p-3 ring-1 ring-emerald-100">
                                <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
                                  <span className="font-semibold text-emerald-900">
                                    {allowedLabel}: what goes to the party
                                  </span>
                                  <span
                                    className={cn(
                                      'font-semibold',
                                      aSplit === a ? 'text-emerald-700' : 'text-amber-700',
                                    )}
                                  >
                                    {aSplit} of {a} pcs
                                  </span>
                                </div>
                                <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                                  {aOpts.map((o) => (
                                    <div
                                      key={o.code}
                                      className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-white p-2 ring-1 ring-emerald-100"
                                    >
                                      <button
                                        type="button"
                                        className="min-h-[44px] min-w-[8rem] flex-1 rounded-lg px-2 text-left text-sm font-semibold text-slate-800 hover:bg-emerald-50"
                                        aria-label={`All ${String(a)} allowed pcs: ${o.label}`}
                                        onClick={() => {
                                          fillSplit(gk, aOpts, o.code, a);
                                        }}
                                      >
                                        {o.label}
                                      </button>
                                      <QtyStepper
                                        tone="success"
                                        value={split[`${gk}|${o.code}`] ?? 0}
                                        max={a}
                                        label={`${o.label}, ${g.condition_label ?? 'all pieces'}, item ${String(it.line_no)}`}
                                        onChange={(v) => {
                                          setSplitQty(gk, o.code, v);
                                        }}
                                      />
                                    </div>
                                  ))}
                                </div>
                              </div>
                            ) : null}

                            {/* A configured Not Allowed verdict with several actions */}
                            {n !== undefined && n > 0 && nOpts.length > 1 ? (
                              <div className="rounded-xl bg-rose-50/50 p-3 ring-1 ring-rose-100">
                                <div className="mb-2 flex justify-between text-xs font-semibold text-rose-900">
                                  <span>{notAllowedLabel}</span>
                                  <span>
                                    {nSplit} of {n} pcs
                                  </span>
                                </div>
                                <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                                  {nOpts.map((o) => (
                                    <div
                                      key={o.code}
                                      className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-white p-2 ring-1 ring-rose-100"
                                    >
                                      <span className="text-sm font-medium text-slate-800">
                                        {o.label}
                                      </span>
                                      <QtyStepper
                                        tone="danger"
                                        value={split[`${gk}|${o.code}`] ?? 0}
                                        max={n}
                                        label={`${o.label}, ${g.condition_label ?? 'all pieces'}, item ${String(it.line_no)}`}
                                        onChange={(v) => {
                                          setSplitQty(gk, o.code, v);
                                        }}
                                      />
                                    </div>
                                  ))}
                                </div>
                              </div>
                            ) : null}
                          </div>
                        )}
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
          <p key={s.store_id} className="m-0 text-xs text-slate-500">
            {s.store_name}: submitted by {s.submitted_by_name ?? '—'}
            {s.submitted_at ? `, ${formatDateTime(s.submitted_at)}` : ''}
            {s.remarks ? ` · “${s.remarks}”` : ''}
          </p>
        ))}

      {editItems.length > 0 || data.can_send_to_management ? (
        <div className="sticky bottom-[4.5rem] z-20 sm:bottom-3 rounded-2xl border border-slate-200 bg-white/95 p-3 shadow-xl shadow-slate-900/10 backdrop-blur sm:p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <span className="flex items-center gap-2 text-sm text-slate-600">
              <ShieldCheck className="h-5 w-5 shrink-0 text-emerald-600" aria-hidden="true" />
              {editItems.length > 0
                ? ready
                  ? 'Every piece has its decision. Review and submit.'
                  : `${String(pending.length)} item condition(s) still to decide.`
                : 'You can send pieces to Management until Accounts completes this goods slip.'}
            </span>
            <div className="flex flex-col gap-2 sm:flex-row">
              {data.can_send_to_management ? (
                <Button
                  type="button"
                  variant="outline"
                  className="min-h-[44px]"
                  onClick={() => {
                    setSendError(null);
                    setSendOpen(true);
                  }}
                >
                  <Send className="h-4 w-4" aria-hidden="true" /> Send for Management approval
                </Button>
              ) : null}
              {editItems.length > 0 ? (
                <Button
                  type="button"
                  variant="primary"
                  className="min-h-[44px]"
                  disabled={!ready}
                  onClick={() => {
                    setSubmitError(null);
                    setConfirming(true);
                  }}
                >
                  <CheckCircle2 className="h-4 w-4" aria-hidden="true" /> Review & submit
                </Button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      <Modal
        isOpen={confirming}
        size="lg"
        onClose={() => {
          if (!busy) setConfirming(false);
        }}
        title="Submit the analysis"
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
              variant="primary"
              className="min-h-[44px]"
              isLoading={busy}
              disabled={noteInvalid || submitPick.missing > 0}
              onClick={submit}
            >
              {submitPick.pcs > 0 || submitPick.missing > 0
                ? 'Submit & send to Management'
                : 'Submit analysis'}
            </Button>
          </div>
        }
      >
        <div className="space-y-4 text-sm">
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-xl bg-emerald-50 p-3 ring-1 ring-emerald-100">
              <p className="m-0 text-xs font-medium text-emerald-700">{allowedLabel}</p>
              <p className="m-0 font-mono text-2xl font-bold text-emerald-900">{allowedTotal}</p>
            </div>
            <div className="rounded-xl bg-rose-50 p-3 ring-1 ring-rose-100">
              <p className="m-0 text-xs font-medium text-rose-700">{notAllowedLabel}</p>
              <p className="m-0 font-mono text-2xl font-bold text-rose-900">{notAllowedTotal}</p>
            </div>
          </div>
          <ul className="m-0 list-none divide-y divide-slate-100 rounded-xl border border-slate-200 p-0">
            {[...totals.values()].map((t) => (
              <li key={t.label} className="flex justify-between gap-2 px-3 py-2">
                <span>{t.label}</span>
                <strong className="font-mono">{t.qty} pcs</strong>
              </li>
            ))}
          </ul>

          <section aria-label="Send pieces to Management" className="space-y-2">
            <div>
              <p className="m-0 font-semibold text-slate-900">
                Send pieces for Management approval{' '}
                <span className="font-normal text-slate-500">(optional)</span>
              </p>
              <p className="m-0 mt-0.5 text-xs text-slate-500">
                Choose the pieces and propose an action. Management sees your decision and decides
                finally.
              </p>
            </div>
            <ManagementPicker
              rows={submitRows}
              proposals={proposals}
              picks={picks}
              onChange={setPicks}
            />
            {submitPick.pcs > 0 ? (
              <>
                <label
                  className="block text-xs font-medium text-slate-700"
                  htmlFor="analysis-mgmt-note"
                >
                  Note for Management (optional)
                </label>
                <Textarea
                  id="analysis-mgmt-note"
                  value={note}
                  maxLength={400}
                  rows={2}
                  onChange={(e) => {
                    setNote(e.target.value);
                  }}
                />
                {noteInvalid ? (
                  <p className="m-0 text-xs text-rose-600">
                    Write at least 3 characters, or leave it empty.
                  </p>
                ) : null}
              </>
            ) : null}
            <p
              className={cn(
                'm-0 rounded-xl p-3 text-xs',
                submitPick.pcs > 0 ? 'bg-violet-50 text-violet-900' : 'bg-slate-50 text-slate-600',
              )}
              data-testid="mgmt-summary"
            >
              {submitPick.pcs > 0
                ? `${String(submitPick.items)} item(s) · ${String(submitPick.pcs)} pcs go to Management. The goods slip waits for Management before Accounts.`
                : 'Nothing goes to Management. Once every store has submitted, the goods slip goes straight to Accounts.'}
            </p>
          </section>

          <div>
            <label className="block text-xs font-medium text-slate-700" htmlFor="analysis-remarks">
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
          </div>
          <p className="m-0 text-xs text-slate-500">
            {activeStore?.store_name}: after submitting, only Management can change these decisions.
          </p>
          {submitError ? (
            <ErrorState error={submitError} title="The analysis was not submitted" />
          ) : null}
        </div>
      </Modal>

      <Modal
        isOpen={sendOpen}
        size="lg"
        onClose={() => {
          if (!sendBusy) setSendOpen(false);
        }}
        title="Send for Management approval"
        footer={
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:min-w-full">
            <span className="text-sm font-semibold text-slate-700">
              {sendPick.items} item(s) · {sendPick.pcs} pcs
            </span>
            <div className="flex flex-col-reverse gap-2 sm:flex-row">
              <Button
                type="button"
                variant="outline"
                className="min-h-[44px]"
                disabled={sendBusy}
                onClick={() => {
                  setSendOpen(false);
                }}
              >
                Back
              </Button>
              <Button
                type="button"
                variant="primary"
                className="min-h-[44px]"
                isLoading={sendBusy}
                disabled={sendPick.pcs === 0 || sendPick.missing > 0 || sendNoteInvalid}
                onClick={sendToManagement}
              >
                <Send className="h-4 w-4" aria-hidden="true" /> Send
              </Button>
            </div>
          </div>
        }
      >
        <div className="space-y-3 text-sm">
          <p className="m-0 text-slate-600">
            Pick the pieces and propose an action. Management sees what you decided and takes the
            final decision.
            {data.status === 'ACCOUNTS_PENDING'
              ? ' The goods slip is at Accounts: sending withdraws its action sheet until Management approves.'
              : ''}
          </p>
          <ManagementPicker
            rows={sendRows}
            proposals={proposals}
            picks={sendPicks}
            onChange={setSendPicks}
          />
          <label className="block text-xs font-medium text-slate-700" htmlFor="send-note">
            Note for Management (optional)
          </label>
          <Textarea
            id="send-note"
            value={sendNote}
            maxLength={400}
            rows={2}
            onChange={(e) => {
              setSendNote(e.target.value);
            }}
          />
          {sendNoteInvalid ? (
            <p className="m-0 text-xs text-rose-600">
              Write at least 3 characters, or leave it empty.
            </p>
          ) : null}
          {sendError ? <ErrorState error={sendError} title="Nothing was sent" /> : null}
        </div>
      </Modal>
    </div>
  );
};
