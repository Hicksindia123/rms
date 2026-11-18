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
  groupIssue,
  groupKey,
  groupsOf,
  initialAllocations,
  isDirty,
  lineTotal,
  parseQty,
  toSavePayload,
} from './rules';
import type {
  AcSlipVersion,
  Allocations,
  FinalActionGroup,
  FinalActionLine,
  FinalActionsState,
} from './types';

interface Props {
  gsId: string;
  onBack: () => void;
}

/**
 * RM Final Actions & "Replacement Slip – A/c Actions" (change plan Phase 7; AMD-16, AMD-17;
 * DEC-41; G-21). Per item + current condition (gap plan G4, DEC-57) the RM splits the qty available
 * for action across the actions of the resolved profile; finalising stores a server-side PDF that
 * Accounts and the RM can print again. Pieces left Pending are re-actioned in a later round.
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

  const round = data.round_no ?? 1;
  const setQty = (key: string, code: string, raw: string) => {
    setAllocs((prev) => ({ ...prev, [key]: { ...prev[key], [code]: parseQty(raw) } }));
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
            {round > 1 ? <Badge variant="warning">Pending re-action · round {round}</Badge> : null}
          </p>
        </div>
      </div>

      {round > 1 && !data.is_finalised ? (
        <div
          className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
          role="status"
        >
          <p className="m-0 font-semibold">
            {String(data.pending_from_previous_round ?? 0)} pc(s) were left Pending in round{' '}
            {round - 1}.
          </p>
          <p className="m-0 mt-1">
            {data.waiting_for_previous_round
              ? `They can be re-actioned once Accounts has completed round ${String(round - 1)} and its Dispatch Slip (if any) is dispatched.`
              : 'They are in the Pending Hold. Choose their final action per condition; finalising sends a new A/c Actions slip to Accounts.'}
          </p>
        </div>
      ) : null}

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
                {data.is_completed ? ' · Accounts entry completed' : ''}
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
        <p className="mt-4 text-sm text-slate-500">
          {round > 1 ? 'No pieces are waiting in Pending.' : 'This goods slip has no item lines.'}
        </p>
      ) : (
        <div className="mt-4 flex flex-col gap-3">
          {data.lines.map((line) => (
            <LineCard
              key={line.gs_item_id}
              line={line}
              allocs={allocs}
              reaction={round > 1}
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
                ? 'Every line and condition is fully allocated (G-21).'
                : 'Each line must allocate exactly its available qty, per condition (G-21).'}
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
                    Revision {r.revision_no}
                    {(r.round_no ?? 1) > 1 ? ` (round ${String(r.round_no)})` : ''} ·{' '}
                    {formatDateTime(r.decided_at)}
                    {r.decided_by_name ? ` · ${r.decided_by_name}` : ''}
                  </p>
                  {r.reason ? (
                    <p className="m-0 text-xs text-slate-500">Reason: {r.reason}</p>
                  ) : null}
                  <p className="m-0 mt-1 text-xs">
                    {r.lines
                      .map(
                        (l) =>
                          `#${String(l.line_no)}${l.condition_label ? ` ${l.condition_label}` : ''} ${l.action_label} ${String(l.qty)}`,
                      )
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
          {round > 1
            ? `A new Replacement Slip – A/c Actions version for the re-actioned Pending pieces (round ${String(round)}) is generated and stored, and Accounts is notified.`
            : 'The Replacement Slip – A/c Actions PDF is generated and stored, and Accounts is notified.'}{' '}
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
  allocs,
  reaction,
  editable,
  onChange,
}: {
  line: FinalActionLine;
  allocs: Allocations;
  reaction: boolean;
  editable: boolean;
  onChange: (key: string, code: string, raw: string) => void;
}) {
  const groups = groupsOf(line);
  const total = groups.reduce(
    (sum, g) => sum + lineTotal(allocs[groupKey(line.gs_item_id, g.condition_field_id)]),
    0,
  );
  const balanced = groups.every(
    (g) =>
      groupIssue(g.available_qty, allocs[groupKey(line.gs_item_id, g.condition_field_id)]) === null,
  );
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
        <Badge variant={balanced ? 'success' : 'warning'}>
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
          <dt className="text-sky-700 dark:text-sky-300">{reaction ? 'Pending' : 'Available'}</dt>
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

      {(line.current_conditions ?? []).some((c) => c.current_qty > 0) ? (
        <p className="mt-2 flex flex-wrap gap-1 text-xs">
          <span className="text-slate-500">Current condition:</span>
          {(line.current_conditions ?? [])
            .filter((c) => c.current_qty > 0)
            .map((c) => (
              <Badge key={c.field_code} variant="neutral">
                {c.field_label} {c.current_qty}
                {c.original_qty !== c.current_qty ? ` (counted ${String(c.original_qty)})` : ''}
              </Badge>
            ))}
        </p>
      ) : null}

      {line.allowed_actions.length === 0 && line.current_actions.length === 0 ? (
        <p className="mt-3 text-sm text-rose-700">
          No actions are configured for this product (Admin → Item Field Profiles).
        </p>
      ) : (
        groups.map((g) => (
          <GroupInputs
            key={g.condition_field_id ?? 'all'}
            line={line}
            group={g}
            row={allocs[groupKey(line.gs_item_id, g.condition_field_id)] ?? {}}
            single={groups.length === 1 && !g.condition_label}
            editable={editable}
            onChange={onChange}
          />
        ))
      )}
    </article>
  );
}

/** DEC-57: the action quantities of one item + condition group. */
function GroupInputs({
  line,
  group,
  row,
  single,
  editable,
  onChange,
}: {
  line: FinalActionLine;
  group: FinalActionGroup;
  row: Record<string, number>;
  single: boolean;
  editable: boolean;
  onChange: (key: string, code: string, raw: string) => void;
}) {
  const key = groupKey(line.gs_item_id, group.condition_field_id);
  const issue = groupIssue(group.available_qty, row);
  const where = group.condition_label ? ` · ${group.condition_label}` : '';
  // Saved actions no longer in the profile stay visible so the RM can move their qty.
  const codes = [
    ...line.allowed_actions.map((a) => ({ code: a.code, label: a.label, allowed: true })),
    ...group.current_actions
      .filter((c) => !line.allowed_actions.some((a) => a.code === c.action_code))
      .map((c) => ({ code: c.action_code, label: c.label, allowed: false })),
  ];
  return (
    <section
      className={
        single ? 'mt-3' : 'mt-3 rounded-lg border border-slate-200 p-3 dark:border-slate-700'
      }
      aria-label={single ? undefined : `Line ${String(line.line_no)}${where}`}
    >
      {!single ? (
        <header className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <p className="m-0 text-sm font-semibold" style={{ wordBreak: 'break-word' }}>
            {group.condition_label ?? 'All pieces'}
          </p>
          <Badge variant={issue ? 'warning' : 'success'}>
            {String(lineTotal(row))} / {String(group.available_qty)}
          </Badge>
        </header>
      ) : null}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {codes.map((c) => {
          const id = `fa-${key}-${c.code}`;
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
                aria-label={`${c.label} qty, line ${String(line.line_no)}${where}`}
                className="h-11 w-20 rounded-md border border-slate-300 bg-white px-2 text-right text-base dark:border-slate-600 dark:bg-slate-800"
                value={String(row[c.code] ?? 0)}
                disabled={!editable || (!c.allowed && (row[c.code] ?? 0) === 0)}
                onFocus={(e) => {
                  e.target.select();
                }}
                onChange={(e) => {
                  onChange(key, c.code, e.target.value);
                }}
              />
            </label>
          );
        })}
      </div>
      {issue && editable ? (
        <p className="mt-2 text-xs font-medium text-amber-700 dark:text-amber-300" role="status">
          {issue}
        </p>
      ) : null}
    </section>
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
                  {(s.round_no ?? 1) > 1 ? (
                    <Badge variant="warning">Pending re-action · round {s.round_no}</Badge>
                  ) : null}
                  {s.is_completed ? <Badge variant="info">Accounts completed</Badge> : null}
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
