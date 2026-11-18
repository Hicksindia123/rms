import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowLeft, CheckCircle2, FileText, Printer, Save, Send, Truck } from 'lucide-react';

import { Badge, Button, ErrorState, Input, LoadingState, Modal, Textarea } from '@/components/ui';
import { StatusChip } from '@/features/goods-slips/display';
import { formatDate, formatDateTime } from '@/features/goods-slips/format';
import { newIdempotencyKey } from '@/features/itemization/api';
import { useAuth } from '@/features/auth/useAuth';
import { toApiError, type ApiError } from '@/lib/api/client';

import { acEntryApi, dispatchSlipsApi } from './api';
import {
  draftComplete,
  draftIssues,
  initialDrafts,
  isDirty,
  localToday,
  toDraft,
  toSaveLines,
} from './rules';
import type { AcEntryLine, AcEntryState, Drafts, LineDraft } from './types';

interface Props {
  gsId: string;
  onBack: () => void;
  onOpenGs: (gsId: string) => void;
  /** Phase 9 (AMD-20): party email / notification screen of the goods slip. */
  onOpenPartyNotification?: (gsId: string) => void;
}

/**
 * Accounts entry per action line (change plan Phase 8; AMD-18, AMD-19; DEC-22; G-22).
 * Each line shows only the fields its action flags require. Completing generates the Dispatch Slip
 * PDF for the lines that ship goods and notifies Dispatch.
 */
export function AccountsEntryPage({ gsId, onBack, onOpenGs, onOpenPartyNotification }: Props) {
  const { can } = useAuth();
  const [data, setData] = useState<AcEntryState | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [drafts, setDrafts] = useState<Drafts>({});
  const [busy, setBusy] = useState<'save' | 'complete' | 'print' | null>(null);
  const [actionError, setActionError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [completeOpen, setCompleteOpen] = useState(false);
  const [remarks, setRemarks] = useState('');
  const [reloadKey, setReloadKey] = useState(0);
  const today = localToday();

  const apply = useCallback((state: AcEntryState) => {
    setData(state);
    setDrafts(initialDrafts(state.lines));
  }, []);

  const load = useCallback(() => {
    setError(null);
    setReloadKey((k) => k + 1);
  }, []);

  useEffect(() => {
    let active = true;
    acEntryApi
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

  const dirty = useMemo(() => (data ? isDirty(data.lines, drafts) : false), [data, drafts]);
  const issues = useMemo(() => {
    if (!data) return [];
    return data.lines.flatMap((l) =>
      draftIssues(l, drafts[l.id] ?? toDraft(l), today).map(
        (m) => `Line ${String(l.line_no)} ${l.action_label}: ${m}`,
      ),
    );
  }, [data, drafts, today]);

  const back = (
    <Button type="button" variant="ghost" onClick={onBack}>
      <ArrowLeft size={16} aria-hidden="true" /> Accounts queue
    </Button>
  );

  if (error) {
    return (
      <div className="page">
        {back}
        <h1 className="page__title">Accounts Entry</h1>
        <ErrorState error={error} onRetry={load} />
      </div>
    );
  }
  if (!data) {
    return (
      <div className="page">
        {back}
        <h1 className="page__title">Accounts Entry</h1>
        <LoadingState label="Loading the Accounts entry…" />
      </div>
    );
  }

  const setField = (lineId: string, field: keyof LineDraft, value: string) => {
    setDrafts((prev) => {
      const line = data.lines.find((l) => l.id === lineId);
      const base = prev[lineId] ?? (line ? toDraft(line) : undefined);
      if (!base) return prev;
      return { ...prev, [lineId]: { ...base, [field]: value } };
    });
  };

  const save = () => {
    if (!data.ac_action_slip_id) return;
    setBusy('save');
    setActionError(null);
    setNotice(null);
    acEntryApi
      .save(
        gsId,
        { ac_action_slip_id: data.ac_action_slip_id, lines: toSaveLines(data.lines, drafts) },
        newIdempotencyKey(),
      )
      .then((state) => {
        apply(state);
        setNotice('Saved.');
      })
      .catch((err: unknown) => {
        setActionError(toApiError(err));
      })
      .finally(() => {
        setBusy(null);
      });
  };

  const complete = () => {
    if (!data.ac_action_slip_id) return;
    setBusy('complete');
    setActionError(null);
    setNotice(null);
    acEntryApi
      .complete(gsId, data.ac_action_slip_id, remarks.trim() || null, newIdempotencyKey())
      .then((state) => {
        apply(state);
        setCompleteOpen(false);
        setRemarks('');
        setNotice(
          state.dispatch_slip
            ? `Completed. Dispatch Slip ${state.dispatch_slip.slip_no} is ready and Dispatch has been notified.`
            : 'Completed. No line ships goods, so the goods slip moves on to closure.',
        );
      })
      .catch((err: unknown) => {
        setActionError(toApiError(err));
        setCompleteOpen(false);
      })
      .finally(() => {
        setBusy(null);
      });
  };

  const printSlip = () => {
    const slip = data.dispatch_slip;
    if (!slip) return;
    // Open the tab inside the click (popup blockers), then point it at the stored PDF.
    const win = window.open('', '_blank');
    setBusy('print');
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

  const editable = data.can_edit;
  const allDraftsComplete = data.lines.every((l) => draftComplete(l, drafts[l.id] ?? toDraft(l)));
  const dslip = data.dispatch_slip;

  return (
    <div className="page">
      {back}
      <div className="min-w-0">
        <h1 className="page__title" style={{ wordBreak: 'break-all' }}>
          Accounts Entry · {data.gs_no}
        </h1>
        <p className="page__subtitle flex flex-wrap items-center gap-2">
          <StatusChip status={data.gs_status} />
          {data.party_name ? <span className="text-sm">{data.party_name}</span> : null}
          {data.slip_no ? (
            <Badge variant="neutral">
              {data.slip_no} v{data.version_no}
            </Badge>
          ) : null}
          {(data.round_no ?? 1) > 1 ? (
            <Badge variant="warning">Pending re-action · round {data.round_no}</Badge>
          ) : null}
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              onOpenGs(data.gs_id);
            }}
          >
            Open goods slip
          </Button>
        </p>
      </div>

      {data.is_completed ? (
        <div
          className="mt-3 flex flex-col gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900 sm:flex-row sm:items-center sm:justify-between dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200"
          role="status"
        >
          <div className="flex items-start gap-2">
            <CheckCircle2 size={18} aria-hidden="true" className="mt-0.5 shrink-0" />
            <div>
              <p className="m-0 font-semibold">Accounts entry complete</p>
              <p className="m-0 text-xs">
                {formatDateTime(data.completed_at)}
                {data.completed_by_name ? ` · ${data.completed_by_name}` : ''}
              </p>
              {dslip ? (
                <p className="m-0 mt-1 text-xs">
                  Dispatch Slip {dslip.slip_no} · {dslip.total_qty} pc(s) ·{' '}
                  {dslip.status === 'DISPATCHED'
                    ? `dispatched ${formatDate(dslip.dispatch_date)} via ${dslip.transporter ?? ''}${
                        dslip.docket_no ? ` (${dslip.docket_no})` : ''
                      }`
                    : 'waiting for Dispatch'}
                </p>
              ) : (
                <p className="m-0 mt-1 text-xs">No line ships goods; no Dispatch Slip.</p>
              )}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {onOpenPartyNotification && can('credit_notes', 'view') ? (
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  onOpenPartyNotification(data.gs_id);
                }}
              >
                <Send size={16} aria-hidden="true" /> Notify party
              </Button>
            ) : null}
            {dslip && can('ac_entry', 'export') ? (
              <Button type="button" variant="primary" disabled={busy !== null} onClick={printSlip}>
                <Printer size={16} aria-hidden="true" />{' '}
                {dslip.print_count > 0 ? 'Re-print Dispatch Slip' : 'Print Dispatch Slip'}
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}

      {data.ac_action_slip_id === null ? (
        <div className="mt-3">
          <ErrorState
            title="No finalised A/c Actions slip"
            error={{
              message:
                'The Replacement Manager has not finalised the actions of this goods slip, or is revising them.',
            }}
            onRetry={load}
          />
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

      {data.lines.length > 0 ? (
        <>
          <p className="mt-4 text-sm text-slate-600 dark:text-slate-300">
            {data.lines_complete} of {data.lines_needing_data} line(s) needing data are entered
            {data.shipping_lines > 0
              ? ` · ${String(data.shipping_lines)} line(s) ship goods`
              : ' · no line ships goods'}
          </p>
          <div className="mt-2 flex flex-col gap-3">
            {data.lines.map((line) => (
              <EntryLineCard
                key={line.id}
                line={line}
                draft={drafts[line.id] ?? toDraft(line)}
                editable={editable}
                today={today}
                onChange={setField}
              />
            ))}
          </div>
        </>
      ) : null}

      {editable ? (
        <div className="sticky bottom-0 mt-4 flex flex-col gap-2 border-t border-slate-200 bg-white/95 py-3 sm:flex-row sm:items-center sm:justify-between dark:border-slate-800 dark:bg-slate-950/95">
          <p className="m-0 text-xs text-slate-500">
            {issues.length > 0
              ? issues[0]
              : dirty
                ? 'Unsaved changes.'
                : data.can_complete
                  ? 'Every line is entered. Complete to generate the Dispatch Slip.'
                  : 'Partial saves are fine; complete once every line is entered (G-22).'}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant={dirty ? 'primary' : 'outline'}
              disabled={!dirty || issues.length > 0 || busy !== null}
              onClick={save}
            >
              <Save size={16} aria-hidden="true" /> {busy === 'save' ? 'Saving…' : 'Save'}
            </Button>
            <Button
              type="button"
              variant={dirty ? 'outline' : 'primary'}
              disabled={!data.can_complete || dirty || !allDraftsComplete || busy !== null}
              onClick={() => {
                setCompleteOpen(true);
              }}
            >
              <FileText size={16} aria-hidden="true" /> Complete
            </Button>
          </div>
        </div>
      ) : null}

      {!data.is_completed && data.complete_blockers.length > 0 ? (
        <ul className="mt-2 list-disc pl-5 text-xs text-slate-500" aria-label="Before completing">
          {data.complete_blockers.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      ) : null}

      <Modal
        isOpen={completeOpen}
        onClose={() => {
          setCompleteOpen(false);
        }}
        title="Complete Accounts entry"
        footer={
          <>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setCompleteOpen(false);
              }}
            >
              Cancel
            </Button>
            <Button type="button" variant="primary" disabled={busy !== null} onClick={complete}>
              <Truck size={16} aria-hidden="true" />{' '}
              {busy === 'complete'
                ? 'Completing…'
                : data.shipping_lines > 0
                  ? 'Complete & generate Dispatch Slip'
                  : 'Complete'}
            </Button>
          </>
        }
      >
        <p className="text-sm">
          The entries, the A/c Actions slip and the Replacement Manager&apos;s actions are frozen
          after completion.
          {data.shipping_lines > 0
            ? ' A numbered Dispatch Slip PDF is generated for the lines that ship goods and Dispatch is notified.'
            : ' No line ships goods; the goods slip moves on to closure.'}
        </p>
        <label htmlFor="ac-complete-remarks" className="mt-2 block text-sm font-medium">
          Remarks (optional)
        </label>
        <Textarea
          id="ac-complete-remarks"
          value={remarks}
          maxLength={1000}
          onChange={(e) => {
            setRemarks(e.target.value);
          }}
        />
      </Modal>
    </div>
  );
}

function EntryLineCard({
  line,
  draft,
  editable,
  today,
  onChange,
}: {
  line: AcEntryLine;
  draft: LineDraft;
  editable: boolean;
  today: string;
  onChange: (lineId: string, field: keyof LineDraft, value: string) => void;
}) {
  const needsData = line.requires_cn || line.requires_challan;
  const complete = draftComplete(line, draft);
  const id = (f: string) => `ac-${line.id}-${f}`;
  const field = (f: keyof LineDraft, label: string, type: 'text' | 'date' | 'decimal') => (
    <div className="flex flex-col gap-1">
      <label htmlFor={id(f)} className="text-xs font-medium text-slate-600 dark:text-slate-300">
        {label}
      </label>
      <Input
        id={id(f)}
        type={type === 'date' ? 'date' : 'text'}
        inputMode={type === 'decimal' ? 'decimal' : undefined}
        max={type === 'date' ? today : undefined}
        maxLength={type === 'text' ? 60 : undefined}
        className="h-11"
        value={draft[f]}
        disabled={!editable}
        onChange={(e) => {
          onChange(line.id, f, e.target.value);
        }}
      />
    </div>
  );

  return (
    <article
      className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900"
      aria-label={`Line ${String(line.line_no)}${line.condition_label ? ` ${line.condition_label}` : ''} ${line.action_label}`}
    >
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="m-0 font-semibold" style={{ wordBreak: 'break-word' }}>
            #{line.line_no} {line.product_name}
          </p>
          <p className="m-0 text-xs text-slate-500">
            {line.product_code ? `${line.product_code} · ` : ''}
            {line.condition_label ? `${line.condition_label} · ` : ''}
            {line.action_label} · {line.qty} pc(s)
          </p>
        </div>
        {needsData ? (
          <Badge variant={complete ? 'success' : 'warning'}>
            {complete ? 'Entered' : 'Needs data'}
          </Badge>
        ) : (
          <Badge variant="neutral">No Accounts data needed</Badge>
        )}
      </header>

      {line.requires_cn ? (
        <fieldset className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
          <legend className="mb-1 text-sm font-semibold">Credit Note</legend>
          {field('cn_no', 'CN No.', 'text')}
          {field('cn_date', 'CN Date', 'date')}
          {field('cn_value', 'CN Value (₹)', 'decimal')}
        </fieldset>
      ) : null}
      {line.requires_challan ? (
        <fieldset className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
          <legend className="mb-1 text-sm font-semibold">Challan</legend>
          {field('challan_no', 'Challan No.', 'text')}
          {field('challan_date', 'Challan Date', 'date')}
        </fieldset>
      ) : null}
      {line.entered_at ? (
        <p className="m-0 mt-2 text-xs text-slate-500">
          Last entered {formatDateTime(line.entered_at)}
          {line.entered_by_name ? ` · ${line.entered_by_name}` : ''}
        </p>
      ) : null}
    </article>
  );
}
