/**
 * Phase P10 (DEC-70; Q17, Q18): Management reviews one goods slip after the stores' analysis.
 * Every item + condition shows its decisions; Management may change any decision to any other
 * (incl. Issue CN and back), move pieces between actions, add a line (a qty on another action) or
 * remove one (qty 0). Each changed item + condition needs a reason; its pieces must still total
 * (G-21). "Save changes" writes one revision; "Approve" records the e-approval stamp (SHA-256 of
 * the goods slip's lines + decisions, computed by the server). A later change invalidates it.
 * DEC-74: pieces a store put on "Issue CN Request" are shown as requested and undecided; Management
 * decides them (Issue CN or another action) and saves before it can approve.
 */
import React, { useEffect, useRef, useState } from 'react';
import { ArrowLeft, CheckCircle2, ShieldCheck } from 'lucide-react';

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

import { managementApprovalApi } from './api';
import { ApprovalStamp } from './ApprovalStamp';
import type { ChangeIn, Decision, ManagementGs, MgmtGroup, MgmtItem } from './types';

interface Props {
  gsId: string;
  onBack: () => void;
  onOpenGs: (gsId: string) => void;
}

const card =
  'rounded-xl border border-slate-200 bg-white p-3 shadow-sm sm:p-4 dark:border-slate-800 dark:bg-slate-900';

const groupKey = (it: MgmtItem, g: MgmtGroup) => `${it.gs_item_id}|${g.condition_field_id ?? ''}`;

/** The current decisions as the editable draft: qty per `${groupKey}|${actionCode}`. A store's
 * Issue CN Request (DEC-74) is not a Management option: those pieces start undecided. */
function draftOf(d: ManagementGs): Record<string, number> {
  const out: Record<string, number> = {};
  for (const it of d.items) {
    for (const g of it.groups) {
      for (const dec of g.decisions) {
        if (!dec.is_cn_request) out[`${groupKey(it, g)}|${dec.action_code}`] = dec.qty;
      }
    }
  }
  return out;
}

const decisionsText = (ds: Decision[]) =>
  ds.length === 0 ? 'Not decided' : ds.map((d) => `${d.label} ${String(d.qty)}`).join(' · ');

export const ManagementApprovalGsPage: React.FC<Props> = ({ gsId, onBack, onOpenGs }) => {
  const [data, setData] = useState<ManagementGs | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [draft, setDraft] = useState<Record<string, number>>({});
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);
  const [approveOpen, setApproveOpen] = useState(false);
  const [remarks, setRemarks] = useState('');
  const [approving, setApproving] = useState(false);
  const [approveError, setApproveError] = useState<ApiError | null>(null);
  const [approved, setApproved] = useState(false);
  // G-16: one key per command; a retry after a network error reuses it.
  const saveKey = useRef(newIdempotencyKey());
  const approveKey = useRef(newIdempotencyKey());
  const [reloadKey, setReloadKey] = useState(0);

  const accept = (d: ManagementGs) => {
    setData(d);
    setDraft(draftOf(d));
    setReasons({});
  };

  // State changes only in the request callbacks (the triggers set `loading`).
  useEffect(() => {
    let active = true;
    managementApprovalApi
      .getGs(gsId)
      .then((d) => {
        if (active) {
          setData(d);
          setDraft(draftOf(d));
          setReasons({});
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

  if (loading && !data) return <LoadingState label="Loading the goods slip…" />;
  if (error && !data) {
    return (
      <div className="mx-auto max-w-4xl space-y-3 p-4 sm:p-6">
        <Button type="button" variant="outline" className="min-h-[44px]" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Management Approval
        </Button>
        <ErrorState error={error} onRetry={load} title="Could not load the goods slip" />
      </div>
    );
  }
  if (!data) return null;

  const qtyOf = (it: MgmtItem, g: MgmtGroup, code: string) =>
    draft[`${groupKey(it, g)}|${code}`] ?? 0;
  const total = (it: MgmtItem, g: MgmtGroup) =>
    it.options.reduce((sum, o) => sum + qtyOf(it, g, o.code), 0);
  const isChanged = (it: MgmtItem, g: MgmtGroup) => {
    const now = it.options
      .map((o) => [o.code, qtyOf(it, g, o.code)] as const)
      .filter(([, q]) => q > 0);
    const was = g.decisions
      .filter((d) => !d.is_cn_request)
      .map((d) => [d.action_code, d.qty] as const);
    const key = (xs: readonly (readonly [string, number])[]) =>
      xs
        .map(([c, q]) => `${c}:${String(q)}`)
        .sort()
        .join(',');
    return key(now) !== key(was);
  };

  const changed = data.items.flatMap((it) =>
    it.groups.filter((g) => isChanged(it, g)).map((g) => ({ it, g })),
  );
  const unbalanced = changed.filter(({ it, g }) => total(it, g) !== g.qty);
  const missingReason = changed.filter(
    ({ it, g }) => (reasons[groupKey(it, g)] ?? '').trim().length < 3,
  );
  const canSave = changed.length > 0 && unbalanced.length === 0 && missingReason.length === 0;

  const setCell = (cellKey: string, raw: string) => {
    const n = parseInt(raw, 10);
    setSaved(false);
    setDraft((prev) => {
      const rest = Object.fromEntries(Object.entries(prev).filter(([k]) => k !== cellKey));
      return isNaN(n) || n <= 0 ? rest : { ...rest, [cellKey]: n };
    });
  };

  /** DEC-74: put the store's requested pieces on the credit-note action (requires_cn flag). */
  const grantCn = (it: MgmtItem, g: MgmtGroup, code: string) => {
    const cellKey = `${groupKey(it, g)}|${code}`;
    setSaved(false);
    setDraft((prev) => ({ ...prev, [cellKey]: (prev[cellKey] ?? 0) + (g.cn_requested_qty ?? 0) }));
    setReasons((prev) =>
      (prev[groupKey(it, g)] ?? '').trim()
        ? prev
        : { ...prev, [groupKey(it, g)]: 'Issue CN Request accepted' },
    );
  };

  const fillGroup = (it: MgmtItem, g: MgmtGroup, code: string) => {
    const prefix = `${groupKey(it, g)}|`;
    setSaved(false);
    setDraft((prev) => ({
      ...Object.fromEntries(Object.entries(prev).filter(([k]) => !k.startsWith(prefix))),
      [`${prefix}${code}`]: g.qty,
    }));
  };

  const reset = () => {
    setDraft(draftOf(data));
    setReasons({});
    setSaveError(null);
  };

  const save = () => {
    const changes: ChangeIn[] = changed.map(({ it, g }) => ({
      gs_item_id: it.gs_item_id,
      condition_field_id: g.condition_field_id,
      decisions: it.options
        .map((o) => ({ action_code: o.code, qty: qtyOf(it, g, o.code) }))
        .filter((d) => d.qty > 0),
      reason: (reasons[groupKey(it, g)] ?? '').trim(),
    }));
    setSaving(true);
    setSaveError(null);
    managementApprovalApi
      .saveChanges(gsId, changes, saveKey.current)
      .then((d) => {
        accept(d);
        setSaved(true);
        setApproved(false);
        saveKey.current = newIdempotencyKey();
      })
      .catch((err: unknown) => {
        setSaveError(toApiError(err));
      })
      .finally(() => {
        setSaving(false);
      });
  };

  const approve = () => {
    setApproving(true);
    setApproveError(null);
    managementApprovalApi
      .approve(gsId, remarks.trim() || null, approveKey.current)
      .then((d) => {
        accept(d);
        setApproveOpen(false);
        setRemarks('');
        setApproved(true);
        setSaved(false);
        approveKey.current = newIdempotencyKey();
      })
      .catch((err: unknown) => {
        setApproveError(toApiError(err));
      })
      .finally(() => {
        setApproving(false);
      });
  };

  // Totals per action of the current (saved) decisions, for the approval confirmation.
  const totals = new Map<string, { label: string; qty: number }>();
  for (const it of data.items) {
    for (const g of it.groups) {
      for (const d of g.decisions) {
        const t = totals.get(d.action_code) ?? { label: d.label, qty: 0 };
        t.qty += d.qty;
        totals.set(d.action_code, t);
      }
    }
  }
  const request = data.open_request ?? null;
  const alreadyValid = data.stamp.state === 'VALID' && !request;
  const cnPending = data.cn_request_qty ?? 0;

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6" data-testid="management-approval-gs">
      <PageHeader
        title={`Management Approval · ${data.gs_no}`}
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
          <Badge
            key={s.store_id}
            variant={s.analysis_status === 'SUBMITTED' ? 'success' : 'warning'}
          >
            {s.store_code}:{' '}
            {s.analysis_status === 'SUBMITTED' ? 'analysis submitted' : 'analysis pending'}
          </Badge>
        ))}
      </div>

      {request ? (
        <div
          role="status"
          data-testid="open-request"
          className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
        >
          <p className="font-semibold">Sent for Management approval</p>
          <p className="mt-1 break-words">
            {request.requested_by_name ?? 'A store user'} ({request.store_name}),{' '}
            {formatDateTime(request.requested_at)}: “{request.reason}”
          </p>
        </div>
      ) : null}

      {approved ? (
        <div
          role="status"
          className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200"
        >
          <p className="flex items-center gap-2 font-semibold">
            <CheckCircle2 className="h-5 w-5" aria-hidden="true" /> Approved
          </p>
        </div>
      ) : null}
      {saved ? (
        <p role="status" className="text-sm font-semibold text-emerald-700 dark:text-emerald-400">
          Changes saved. Approve the goods slip to stamp them.
        </p>
      ) : null}

      <ApprovalStamp gsId={data.gs_id} stamp={data.stamp} />
      {data.stamp.state === 'NONE' ? (
        <p className="text-sm text-slate-600 dark:text-slate-300">
          Not approved by Management yet.
        </p>
      ) : null}

      {data.blocked_reason ? (
        <p className="rounded-lg bg-slate-100 p-3 text-sm text-slate-700 dark:bg-slate-800 dark:text-slate-200">
          {data.blocked_reason}
        </p>
      ) : null}
      {data.reopen_notice && data.can_edit ? (
        <p
          className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
          role="note"
          data-testid="reopen-notice"
        >
          {data.reopen_notice}
        </p>
      ) : null}
      {!data.accounts_gate.passes && data.accounts_gate.problem ? (
        <p className="text-xs text-slate-500 dark:text-slate-400" data-testid="accounts-gate">
          Before Accounts: {data.accounts_gate.problem.replace(/^DEC-\d+( \([^)]*\))?: /, '')}
        </p>
      ) : null}

      {error ? <ErrorState error={error} onRetry={load} title="Could not refresh" /> : null}

      {data.items.length === 0 ? (
        <EmptyState title="No items to show" />
      ) : (
        <ul className="m-0 list-none space-y-3 p-0" aria-label="Items">
          {data.items.map((it) => (
            <li
              key={it.gs_item_id}
              className={card}
              data-testid={`mgmt-item-${String(it.line_no)}`}
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="break-words text-sm font-semibold text-slate-900 dark:text-slate-100">
                    #{it.line_no} {it.product_code ? `${it.product_code} · ` : ''}
                    {it.product_name}
                  </div>
                  <div className="text-xs text-slate-500 dark:text-slate-400">
                    {it.received_qty} pcs
                  </div>
                </div>
                {it.store_name ? <Badge variant="neutral">{it.store_name}</Badge> : null}
              </div>
              <div className="mt-3 space-y-3">
                {it.groups.map((g) => {
                  const gk = groupKey(it, g);
                  const done = total(it, g);
                  const dirty = isChanged(it, g);
                  return (
                    <fieldset key={gk} className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800/40">
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
                        {data.can_edit ? (
                          <span
                            className={
                              done === g.qty
                                ? 'font-semibold text-emerald-700 dark:text-emerald-400'
                                : 'font-semibold text-rose-600'
                            }
                          >
                            {done} of {g.qty} decided
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
                        {dirty ? 'Was: ' : ''}
                        {decisionsText(g.decisions)}
                      </p>
                      {(g.cn_requested_qty ?? 0) > 0 ? (
                        <div
                          className="mt-2 flex flex-col gap-2 rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900 sm:flex-row sm:items-center sm:justify-between dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
                          data-testid={`cn-request-${gk}`}
                        >
                          <span className="font-semibold">
                            Store requests Issue CN for {g.cn_requested_qty} pcs: decide them below.
                          </span>
                          {data.can_edit
                            ? it.options
                                .filter((o) => o.requires_cn)
                                .slice(0, 1)
                                .map((o) => (
                                  <Button
                                    key={o.code}
                                    type="button"
                                    variant="outline"
                                    className="min-h-[44px]"
                                    onClick={() => {
                                      grantCn(it, g, o.code);
                                    }}
                                  >
                                    {o.label} {g.cn_requested_qty} pcs
                                  </Button>
                                ))
                            : null}
                        </div>
                      ) : null}
                      {data.can_edit ? (
                        <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                          {it.options.map((o) => {
                            const cellKey = `${gk}|${o.code}`;
                            return (
                              <div key={o.code} className="flex items-center justify-between gap-2">
                                <button
                                  type="button"
                                  aria-label={`All ${String(g.qty)} pcs: ${o.label}`}
                                  onClick={() => {
                                    fillGroup(it, g, o.code);
                                  }}
                                  className="min-h-[44px] min-w-0 flex-1 rounded-lg px-2 text-left text-xs text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                                >
                                  {o.label}
                                </button>
                                <input
                                  aria-label={`${o.label}, ${g.condition_label ?? 'all pieces'}, item ${String(it.line_no)}`}
                                  type="number"
                                  inputMode="numeric"
                                  min={0}
                                  max={g.qty}
                                  value={draft[cellKey] ?? ''}
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
                      ) : null}
                      {data.can_edit && dirty ? (
                        <div className="mt-2">
                          <label
                            className="block text-xs font-medium text-slate-700 dark:text-slate-300"
                            htmlFor={`reason-${gk}`}
                          >
                            Reason for this change (required)
                          </label>
                          <Textarea
                            id={`reason-${gk}`}
                            rows={2}
                            maxLength={500}
                            value={reasons[gk] ?? ''}
                            onChange={(e) => {
                              const v = e.target.value;
                              setReasons((prev) => ({ ...prev, [gk]: v }));
                            }}
                          />
                        </div>
                      ) : null}
                    </fieldset>
                  );
                })}
              </div>
            </li>
          ))}
        </ul>
      )}

      {data.can_edit ? (
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <span className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-300">
              <ShieldCheck className="h-4 w-4 shrink-0 text-emerald-600" aria-hidden="true" />
              {changed.length === 0
                ? cnPending > 0
                  ? `${String(cnPending)} pc(s) on Issue CN Request still to decide.`
                  : 'No unsaved changes.'
                : unbalanced.length > 0
                  ? `${String(unbalanced.length)} item condition(s) do not total their pieces.`
                  : missingReason.length > 0
                    ? `${String(missingReason.length)} change(s) need a reason.`
                    : `${String(changed.length)} change(s) ready to save.`}
            </span>
            <div className="flex flex-col gap-2 sm:flex-row">
              {changed.length > 0 ? (
                <Button
                  type="button"
                  variant="outline"
                  className="min-h-[44px]"
                  disabled={saving}
                  onClick={reset}
                >
                  Undo changes
                </Button>
              ) : null}
              <Button
                type="button"
                variant="outline"
                className="min-h-[44px]"
                disabled={!canSave}
                isLoading={saving}
                onClick={save}
              >
                Save changes
              </Button>
              {data.can_approve ? (
                <Button
                  type="button"
                  className="min-h-[44px]"
                  disabled={changed.length > 0 || alreadyValid || cnPending > 0}
                  onClick={() => {
                    setApproveError(null);
                    setApproveOpen(true);
                  }}
                >
                  Approve
                </Button>
              ) : null}
            </div>
          </div>
          {saveError ? <ErrorState error={saveError} title="The changes were not saved" /> : null}
        </div>
      ) : null}

      {data.revisions.length > 0 || data.approvals.length > 0 || data.requests.length > 0 ? (
        <section className="space-y-2" aria-label="History">
          <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">History</h2>
          <ul className="m-0 list-none space-y-2 p-0 text-xs text-slate-600 dark:text-slate-300">
            {data.approvals.map((a) => (
              <li key={a.id} className="break-words">
                <strong>Approval {a.approval_no}</strong> · {a.approver_name} ({a.approver_role}),{' '}
                {formatDateTime(a.approved_at)} · ref {a.short_ref}
                {a.remarks ? ` · “${a.remarks}”` : ''}
              </li>
            ))}
            {data.revisions.map((r) => (
              <li key={r.revision_no} className="break-words">
                <strong>Change (revision {r.revision_no})</strong> · {r.made_by_name ?? '—'},{' '}
                {formatDateTime(r.made_at)}
                <ul className="mt-1 list-disc space-y-0.5 pl-5">
                  {r.changes.map((c) => (
                    <li key={`${String(c.line_no)}-${c.condition_label ?? ''}`}>
                      #{c.line_no} {c.product_name}
                      {c.condition_label ? ` (${c.condition_label})` : ''}:{' '}
                      {decisionsText(c.before)} → {decisionsText(c.after)} · “{c.reason}”
                    </li>
                  ))}
                </ul>
              </li>
            ))}
            {data.requests.map((q) => (
              <li key={q.id} className="break-words">
                <strong>Request</strong> · {q.store_name}
                {q.requested_by_name ? ` (${q.requested_by_name})` : ''},{' '}
                {formatDateTime(q.requested_at)}: “{q.reason}” ·{' '}
                {q.status === 'OPEN'
                  ? 'open'
                  : `resolved${q.resolved_by_name ? ` by ${q.resolved_by_name}` : ''}`}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <Modal
        isOpen={approveOpen}
        onClose={() => {
          if (!approving) setApproveOpen(false);
        }}
        title="Approve this goods slip?"
        footer={
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="outline"
              className="min-h-[44px]"
              disabled={approving}
              onClick={() => {
                setApproveOpen(false);
              }}
            >
              Back
            </Button>
            <Button type="button" className="min-h-[44px]" isLoading={approving} onClick={approve}>
              Approve
            </Button>
          </div>
        }
      >
        <div className="space-y-3 text-sm">
          <p>
            {data.gs_no}: the decisions below are stamped. Any later change needs a new approval.
          </p>
          <ul className="m-0 list-none space-y-1 p-0">
            {[...totals.values()].map((t) => (
              <li key={t.label} className="flex justify-between gap-2">
                <span>{t.label}</span>
                <strong>{t.qty} pcs</strong>
              </li>
            ))}
          </ul>
          <p className="text-xs text-slate-500 dark:text-slate-400">{data.stamp.disclaimer}</p>
          <label
            className="block text-xs font-medium text-slate-700 dark:text-slate-300"
            htmlFor="approve-remarks"
          >
            Remarks (optional)
          </label>
          <Textarea
            id="approve-remarks"
            value={remarks}
            maxLength={500}
            rows={2}
            onChange={(e) => {
              setRemarks(e.target.value);
            }}
          />
          {approveError ? (
            <ErrorState error={approveError} title="The goods slip was not approved" />
          ) : null}
        </div>
      </Modal>
    </div>
  );
};
