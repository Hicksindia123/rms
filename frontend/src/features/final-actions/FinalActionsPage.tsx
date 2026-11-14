import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  FileText,
  History,
  Lock,
  Pencil,
  Printer,
  Save,
} from 'lucide-react';

import { Badge, Button, ErrorState, LoadingState, Modal, Textarea } from '@/components/ui';
import { StatusChip } from '@/features/goods-slips/display';
import { formatDateTime } from '@/features/goods-slips/format';
import { newIdempotencyKey } from '@/features/itemization/api';
import { toApiError, type ApiError } from '@/lib/api/client';
import { useAuth } from '@/features/auth/useAuth';

import { finalActionsApi } from './api';
import {
  allBalanced,
  initialAllocations,
  isDirty,
  lineIssue,
  lineTotal,
  parseQty,
  toSavePayload,
} from './rules';
import type { AcSlipVersion, Allocations, FinalActionLine, FinalActionsState } from './types';

interface Props {
  gsId: string;
  onBack: () => void;
}

/**
 * RM Final Actions & "Replacement Slip – A/c Actions" (change plan Phase 7; AMD-16, AMD-17;
 * DEC-41; G-21). Per item the RM splits the qty available for action across the actions of the
 * resolved profile; finalising stores a server-side PDF that Accounts and the RM can print again.
 */
export function FinalActionsPage({ gsId, onBack }: Props) {
  const { can } = useAuth();
  const [data, setData] = useState<FinalActionsState | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [allocs, setAllocs] = useState<Allocations>({});
  const [revising, setRevising] = useState(false);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState<'save' | 'finalise' | 'print' | null>(null);
  const [actionError, setActionError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [finaliseOpen, setFinaliseOpen] = useState(false);
  const [remarks, setRemarks] = useState('');
  const [showHistory, setShowHistory] = useState(false);

  const apply = useCallback((state: FinalActionsState) => {
    setData(state);
    setAllocs(initialAllocations(state.lines));
    setRevising(false);
    setReason('');
  }, []);

  const [reloadKey, setReloadKey] = useState(0);
  const load = useCallback(() => {
    setError(null);
    setReloadKey((k) => k + 1);
  }, []);

  useEffect(() => {
    let active = true;
    finalActionsApi
      .get(gsId)
      .then((s) => {
        if (active) apply(s);
      })
      .catch((err: unknown) => {
        if (active) setError(toApiError(err));
      });
    return () => {
      active = false;
    };
  }, [gsId, apply, reloadKey]);

  const dirty = useMemo(() => (data ? isDirty(data.lines, allocs) : false), [data, allocs]);
  const balanced = useMemo(() => (data ? allBalanced(data.lines, allocs) : false), [data, allocs]);

  const back = (
    <Button type="button" variant="ghost" onClick={onBack}>
      <ArrowLeft size={16} aria-hidden="true" /> Goods slip
    </Button>
  );

  if (error) {
    return (
      <div className="page">
        {back}
        <h1 className="page__title">Final Actions</h1>
        <ErrorState error={error} onRetry={load} />
      </div>
    );
  }
  if (!data) {
    return (
      <div className="page">
        {back}
        <h1 className="page__title">Final Actions</h1>
        <LoadingState label="Loading final actions…" />
      </div>
    );
  }

  const locked = data.is_finalised && !revising;
  const editable = data.can_edit && !locked;
  const canPrint = can('final_actions', 'export');

  const setQty = (itemId: string, code: string, raw: string) => {
    setAllocs((prev) => ({ ...prev, [itemId]: { ...prev[itemId], [code]: parseQty(raw) } }));
  };

  const save = () => {
    setBusy('save');
    setActionError(null);
    setNotice(null);
    finalActionsApi
      .save(gsId, toSavePayload(data.lines, allocs, revising ? reason : null), newIdempotencyKey())
      .then((state) => {
        apply(state);
        setNotice(`Saved as revision ${String(state.current_revision_no)}.`);
      })
      .catch((err: unknown) => {
        setActionError(toApiError(err));
      })
      .finally(() => {
        setBusy(null);
      });
  };

  const finalise = () => {
    setBusy('finalise');
    setActionError(null);
    setNotice(null);
    finalActionsApi
      .finalise(gsId, remarks.trim() || null, newIdempotencyKey())
      .then((state) => {
        apply(state);
        setFinaliseOpen(false);
        setRemarks('');
        const s = state.current_slip;
        setNotice(
          s
            ? `Finalised. ${s.slip_no} v${String(s.version_no)} is ready and Accounts has been notified.`
            : 'Finalised.',
        );
      })
      .catch((err: unknown) => {
        setActionError(toApiError(err));
        setFinaliseOpen(false);
      })
      .finally(() => {
        setBusy(null);
      });
  };

  const print = (slip: AcSlipVersion) => {
    // Open the tab inside the click (popup blockers), then point it at the stored PDF.
    const win = window.open('', '_blank');
    setBusy('print');
    setActionError(null);
    finalActionsApi
      .print(gsId, slip.id)
      .then((out) => {
        if (win) {
          win.opener = null;
          win.location.href = out.url;
        } else {
          window.location.assign(out.url);
        }
        load();
      })
      .catch((err: unknown) => {
        win?.close();
        setActionError(toApiError(err));
      })
      .finally(() => {
        setBusy(null);
      });
  };

  return (
    <div className="page">
      {back}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="page__title" style={{ wordBreak: 'break-all' }}>
            Final Actions · {data.gs_no}
          </h1>
          <p className="page__subtitle flex flex-wrap items-center gap-2">
            <StatusChip status={data.status} />
            {data.party_name ? <span className="text-sm">{data.party_name}</span> : null}
            {data.current_revision_no > 0 ? (
              <Badge variant="neutral">Revision {data.current_revision_no}</Badge>
            ) : null}
          </p>
        </div>
      </div>

      {!data.on_final_action_flow ? (
        <ErrorState
          title="Not available for this goods slip"
          error={{
            message:
              'This goods slip uses the earlier RM Actions screen. Open it from the goods slip page.',
          }}
        />
      ) : null}

      {data.current_slip ? (
        <div
          className="mt-3 flex flex-col gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900 sm:flex-row sm:items-center sm:justify-between dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200"
          role="status"
        >
          <div className="flex items-start gap-2">
            <CheckCircle2 size={18} aria-hidden="true" className="mt-0.5 shrink-0" />
            <div>
              <p className="m-0 font-semibold">
                Finalised on {data.current_slip.slip_no} v{data.current_slip.version_no}
              </p>
              <p className="m-0 text-xs">
                {formatDateTime(data.current_slip.finalised_at)}
                {data.current_slip.finalised_by_name
                  ? ` · ${data.current_slip.finalised_by_name}`
                  : ''}
                {` · ${String(data.current_slip.total_qty)} pc(s)`}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {canPrint ? (
              <Button
                type="button"
                variant="primary"
                disabled={busy !== null}
                onClick={() => {
                  if (data.current_slip) print(data.current_slip);
                }}
              >
                <Printer size={16} aria-hidden="true" /> Print A/c Actions slip
              </Button>
            ) : null}
            {data.can_edit && !revising ? (
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setRevising(true);
                  setNotice(null);
                }}
              >
                <Pencil size={16} aria-hidden="true" /> Revise
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}

      {notice ? (
        <p
          role="status"
          className="mt-3 rounded-lg bg-sky-50 p-3 text-sm text-sky-900 dark:bg-sky-950/40 dark:text-sky-200"
        >
          {notice}
        </p>
      ) : null}
      {actionError ? (
        <div className="mt-3">
          <ErrorState title="The action was not completed" error={actionError} />
        </div>
      ) : null}

      {revising ? (
        <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-4 dark:border-amber-900 dark:bg-amber-950/40">
          <p className="m-0 flex items-center gap-2 text-sm font-semibold text-amber-900 dark:text-amber-200">
            <AlertTriangle size={16} aria-hidden="true" /> Revising finalised actions supersedes{' '}
            {data.current_slip?.slip_no} v{data.current_slip?.version_no}. Accounts is notified.
          </p>
          <label htmlFor="fa-revise-reason" className="mt-2 block text-sm font-medium">
            Reason for the revision
          </label>
          <Textarea
            id="fa-revise-reason"
            value={reason}
            maxLength={500}
            onChange={(e) => {
              setReason(e.target.value);
            }}
            required
          />
        </div>
      ) : null}

      {data.lines.length === 0 ? (
        <p className="mt-4 text-sm text-slate-500">This goods slip has no item lines.</p>
      ) : (
        <div className="mt-4 flex flex-col gap-3">
          {data.lines.map((line) => (
            <LineCard
              key={line.gs_item_id}
              line={line}
              row={allocs[line.gs_item_id] ?? {}}
              editable={editable}
              onChange={setQty}
            />
          ))}
        </div>
      )}

      {data.on_final_action_flow && data.can_edit ? (
        <div className="sticky bottom-0 mt-4 flex flex-col gap-2 border-t border-slate-200 bg-white/95 py-3 sm:flex-row sm:items-center sm:justify-between dark:border-slate-800 dark:bg-slate-950/95">
          <p className="m-0 text-xs text-slate-500">
            {locked
              ? 'Actions are finalised. Use Revise to change them.'
              : balanced
                ? 'Every line is fully allocated (G-21).'
                : 'Each line must allocate exactly its available qty (G-21).'}
          </p>
          <div className="flex flex-wrap gap-2">
            {!locked ? (
              <Button
                type="button"
                variant={dirty ? 'primary' : 'outline'}
                disabled={!dirty || !balanced || busy !== null || (revising && !reason.trim())}
                onClick={save}
              >
                <Save size={16} aria-hidden="true" /> {busy === 'save' ? 'Saving…' : 'Save actions'}
              </Button>
            ) : null}
            {!data.is_finalised && can('final_actions', 'approve') ? (
              <Button
                type="button"
                variant={dirty ? 'outline' : 'primary'}
                disabled={!data.can_finalise || dirty || busy !== null}
                onClick={() => {
                  setFinaliseOpen(true);
                }}
              >
                <Lock size={16} aria-hidden="true" /> Finalise &amp; generate slip
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}

      {!data.is_finalised && data.finalise_blockers.length > 0 && data.can_edit ? (
        <ul className="mt-2 list-disc pl-5 text-xs text-slate-500" aria-label="Before finalising">
          {data.finalise_blockers.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      ) : null}

      <SlipVersions slips={data.slips} canPrint={canPrint} busy={busy !== null} onPrint={print} />

      {data.revisions.length > 0 ? (
        <section className="mt-6">
          <Button
            type="button"
            variant="ghost"
            aria-expanded={showHistory}
            onClick={() => {
              setShowHistory((v) => !v);
            }}
          >
            <History size={16} aria-hidden="true" /> Revision history ({data.revisions.length})
          </Button>
          {showHistory ? (
            <ol className="mt-2 flex flex-col gap-2">
              {data.revisions.map((r) => (
                <li
                  key={r.revision_no}
                  className="rounded-lg border border-slate-200 p-3 text-sm dark:border-slate-800"
                >
                  <p className="m-0 font-semibold">
                    Revision {r.revision_no} · {formatDateTime(r.decided_at)}
                    {r.decided_by_name ? ` · ${r.decided_by_name}` : ''}
                  </p>
                  {r.reason ? (
                    <p className="m-0 text-xs text-slate-500">Reason: {r.reason}</p>
                  ) : null}
                  <p className="m-0 mt-1 text-xs">
                    {r.lines
                      .map((l) => `#${String(l.line_no)} ${l.action_label} ${String(l.qty)}`)
                      .join(' · ')}
                  </p>
                </li>
              ))}
            </ol>
          ) : null}
        </section>
      ) : null}

      <Modal
        isOpen={finaliseOpen}
        onClose={() => {
          setFinaliseOpen(false);
        }}
        title="Finalise final actions"
        footer={
          <>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setFinaliseOpen(false);
              }}
            >
              Cancel
            </Button>
            <Button type="button" variant="primary" disabled={busy !== null} onClick={finalise}>
              <FileText size={16} aria-hidden="true" />{' '}
              {busy === 'finalise' ? 'Generating…' : 'Finalise & generate PDF'}
            </Button>
          </>
        }
      >
        <p className="text-sm">
          The Replacement Slip – A/c Actions PDF is generated and stored, and Accounts is notified.
          Later changes need a reason and create a new slip version.
        </p>
        <label htmlFor="fa-finalise-remarks" className="mt-2 block text-sm font-medium">
          Remarks (optional, printed on the slip)
        </label>
        <Textarea
          id="fa-finalise-remarks"
          value={remarks}
          maxLength={500}
          onChange={(e) => {
            setRemarks(e.target.value);
          }}
        />
      </Modal>
    </div>
  );
}

function LineCard({
  line,
  row,
  editable,
  onChange,
}: {
  line: FinalActionLine;
  row: Record<string, number>;
  editable: boolean;
  onChange: (itemId: string, code: string, raw: string) => void;
}) {
  const issue = lineIssue(line, row);
  const total = lineTotal(row);
  // Saved actions no longer in the profile stay visible so the RM can move their qty.
  const codes = [
    ...line.allowed_actions.map((a) => ({ code: a.code, label: a.label, allowed: true })),
    ...line.current_actions
      .filter((c) => !line.allowed_actions.some((a) => a.code === c.action_code))
      .map((c) => ({ code: c.action_code, label: c.label, allowed: false })),
  ];
  return (
    <article
      className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900"
      aria-label={`Line ${String(line.line_no)}`}
    >
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="m-0 font-semibold" style={{ wordBreak: 'break-word' }}>
            #{line.line_no} {line.product_name}
          </p>
          {line.product_code ? (
            <p className="m-0 text-xs text-slate-500">{line.product_code}</p>
          ) : null}
        </div>
        <Badge variant={issue ? 'warning' : 'success'}>
          {String(total)} / {String(line.available_qty)} allocated
        </Badge>
      </header>

      <dl className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
        <div className="rounded-lg bg-slate-50 p-2 dark:bg-slate-800/50">
          <dt className="text-slate-500">Counted</dt>
          <dd className="m-0 font-bold">{line.counted_qty}</dd>
        </div>
        <div className="rounded-lg bg-amber-50 p-2 dark:bg-amber-950/30">
          <dt className="text-amber-700 dark:text-amber-300">At dept</dt>
          <dd className="m-0 font-bold">{line.at_departments_qty}</dd>
        </div>
        <div className="rounded-lg bg-sky-50 p-2 dark:bg-sky-950/30">
          <dt className="text-sky-700 dark:text-sky-300">Available</dt>
          <dd className="m-0 font-bold">{line.available_qty}</dd>
        </div>
      </dl>

      {line.outcomes.length > 0 ? (
        <p className="mt-2 flex flex-wrap gap-1 text-xs">
          <span className="text-slate-500">Back from departments:</span>
          {line.outcomes.map((o) => (
            <Badge key={o.outcome_code} variant={o.is_wastage ? 'danger' : 'info'}>
              {o.outcome_label} {o.qty}
            </Badge>
          ))}
        </p>
      ) : null}

      {codes.length === 0 ? (
        <p className="mt-3 text-sm text-rose-700">
          No actions are configured for this product (Admin → Item Field Profiles).
        </p>
      ) : (
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {codes.map((c) => {
            const id = `fa-${line.gs_item_id}-${c.code}`;
            return (
              <label
                key={c.code}
                htmlFor={id}
                className="flex min-h-[44px] items-center justify-between gap-2 rounded-lg border border-slate-200 px-3 py-1 text-sm dark:border-slate-700"
              >
                <span className="min-w-0">
                  {c.label}
                  {!c.allowed ? (
                    <span className="block text-xs text-rose-600">No longer in the profile</span>
                  ) : null}
                </span>
                <input
                  id={id}
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  aria-label={`${c.label} qty, line ${String(line.line_no)}`}
                  className="h-11 w-20 rounded-md border border-slate-300 bg-white px-2 text-right text-base dark:border-slate-600 dark:bg-slate-800"
                  value={String(row[c.code] ?? 0)}
                  disabled={!editable || (!c.allowed && (row[c.code] ?? 0) === 0)}
                  onFocus={(e) => {
                    e.target.select();
                  }}
                  onChange={(e) => {
                    onChange(line.gs_item_id, c.code, e.target.value);
                  }}
                />
              </label>
            );
          })}
        </div>
      )}
      {issue && editable ? (
        <p className="mt-2 text-xs font-medium text-amber-700 dark:text-amber-300" role="status">
          {issue}
        </p>
      ) : null}
    </article>
  );
}

function SlipVersions({
  slips,
  canPrint,
  busy,
  onPrint,
}: {
  slips: AcSlipVersion[];
  canPrint: boolean;
  busy: boolean;
  onPrint: (slip: AcSlipVersion) => void;
}) {
  return (
    <section className="mt-6" aria-labelledby="ac-slips-title">
      <h2 id="ac-slips-title" className="text-base font-semibold">
        Replacement Slip – A/c Actions
      </h2>
      {slips.length === 0 ? (
        <p className="mt-1 text-sm text-slate-500">
          No slip yet. It is generated when the actions are finalised.
        </p>
      ) : (
        <ul className="mt-2 flex flex-col gap-2">
          {slips.map((s) => (
            <li
              key={s.id}
              className="flex flex-col gap-2 rounded-lg border border-slate-200 p-3 text-sm sm:flex-row sm:items-center sm:justify-between dark:border-slate-800"
            >
              <div className="min-w-0">
                <p className="m-0 flex flex-wrap items-center gap-2 font-semibold">
                  {s.slip_no} v{s.version_no}
                  <Badge variant={s.status === 'CURRENT' ? 'success' : 'neutral'}>
                    {s.status === 'CURRENT' ? 'Current' : 'Superseded'}
                  </Badge>
                </p>
                <p className="m-0 text-xs text-slate-500">
                  {formatDateTime(s.finalised_at)}
                  {s.finalised_by_name ? ` · ${s.finalised_by_name}` : ''} · revision{' '}
                  {s.revision_no} · {s.total_qty} pc(s) · printed {s.print_count}×
                </p>
                <p className="m-0 text-xs">
                  {s.action_totals.map((t) => `${t.action_label} ${String(t.qty)}`).join(' · ')}
                </p>
                {s.supersede_reason ? (
                  <p className="m-0 text-xs text-slate-500">Superseded: {s.supersede_reason}</p>
                ) : null}
              </div>
              {canPrint ? (
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => {
                    onPrint(s);
                  }}
                >
                  <Printer size={16} aria-hidden="true" />{' '}
                  {s.print_count > 0 ? 'Re-print' : 'Print'}
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
