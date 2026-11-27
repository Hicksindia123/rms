/**
 * DEC-73 / DEC-76: E-Commerce Executive ticket queue. Unraised tickets first by SLA due time
 * (OVERDUE flagged in-app, Q3); raise the ticket on the platform, record follow-ups and the
 * platform response (Rejected → remark, Claim Received → amount, Pending → stays open), then close
 * it with the portal resolution (Free Replacement / Refund + qty, DEC-76) so the return goes to
 * unboxing. The server enforces every rule again. DEC-51: any executive may work any ticket.
 */
import React, { useCallback, useRef, useState } from 'react';
import { ChevronRight, RefreshCw } from 'lucide-react';

import { PageHeader } from '@/components/erp';
import {
  Button,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
  Modal,
  RadioGroup,
  Textarea,
} from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { newIdempotencyKey, toApiError, type ApiError } from '@/lib/api/client';
import { formatDate, formatDateTime } from '@/features/goods-slips/format';
import '@/features/goods-slips/gateForm.css';

import { ecomApi } from './api';
import { FollowUpModal, ResolutionModal } from './ResolutionModal';
import { EcomStatusChip, SlaChip } from './SlaChip';
import type { Option, ResponseCode, TicketQueue, TicketRow } from './types';

/** Today as YYYY-MM-DD in the browser (the server checks the date again). */
function todayLocal(): string {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${String(d.getFullYear())}-${m}-${day}`;
}

interface Props {
  canEdit: boolean;
  onOpen: (returnId: string) => void;
}

type State = 'OPEN' | 'CLOSED';

export const TicketQueuePage: React.FC<Props> = ({ canEdit, onOpen }) => {
  const [state, setState] = useState<State>('OPEN');
  const fetcher = useCallback(() => ecomApi.tickets(state), [state]);
  const query = useApiQuery<TicketQueue>(fetcher);
  const [responding, setResponding] = useState<TicketRow | null>(null);
  const [closing, setClosing] = useState<TicketRow | null>(null);
  const [following, setFollowing] = useState<TicketRow | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<ApiError | null>(null);

  const act = async (row: TicketRow, work: (key: string) => Promise<unknown>) => {
    setBusyId(row.ticket.id);
    setActionError(null);
    try {
      await work(newIdempotencyKey());
      query.reload();
    } catch (err) {
      console.error('Ticket action failed', { ticketId: row.ticket.id, err });
      setActionError(toApiError(err));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6" data-testid="ecom-tickets">
      <PageHeader
        title="Platform Tickets"
        subtitle="Raise the platform ticket within the SLA, follow it up, record the platform's response and close it with what the portal shows (Free Replacement / Refund)."
        actions={
          <Button type="button" variant="outline" className="min-h-[44px]" onClick={query.reload}>
            <RefreshCw className="h-4 w-4" aria-hidden="true" /> Refresh
          </Button>
        }
      />
      <div className="gate-return-type" role="tablist" aria-label="Tickets">
        {(['OPEN', 'CLOSED'] as const).map((s) => (
          <button
            key={s}
            type="button"
            role="tab"
            aria-selected={state === s}
            aria-checked={state === s}
            className="gate-return-type__option"
            onClick={() => {
              setState(s);
            }}
          >
            {s === 'OPEN' ? 'Open' : 'Closed'}
          </button>
        ))}
      </div>
      {actionError ? <ErrorState error={actionError} title="Could not update the ticket" /> : null}

      {query.error ? (
        <ErrorState error={query.error} onRetry={query.reload} title="Could not load the tickets" />
      ) : !query.data ? (
        <LoadingState label="Loading tickets…" />
      ) : query.data.rows.length === 0 ? (
        <EmptyState
          title={state === 'OPEN' ? 'No open ticket' : 'No closed ticket'}
          hint="Tickets appear when an E-Commerce Return is recorded with QC status Ticket Raise."
        />
      ) : (
        <ul className="m-0 list-none space-y-3 p-0" aria-label="Platform tickets">
          {query.data.rows.map((r) => {
            const t = r.ticket;
            const busy = busyId === t.id;
            const final = t.response_code === 'REJECTED' || t.response_code === 'CLAIM_RECEIVED';
            return (
              <li
                key={t.id}
                className={`space-y-2 rounded-xl border bg-white p-4 shadow-sm dark:bg-slate-900 ${
                  t.sla_state === 'OVERDUE'
                    ? 'border-red-400 dark:border-red-700'
                    : 'border-slate-200 dark:border-slate-800'
                }`}
                data-testid={`ticket-${r.return_no}`}
              >
                <button
                  type="button"
                  className="flex min-h-[44px] w-full items-center gap-3 border-0 bg-transparent p-0 text-left"
                  onClick={() => {
                    onOpen(r.return_id);
                  }}
                >
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold">{r.return_no}</span>
                      <EcomStatusChip status={r.status} label={r.status_label} />
                      {state === 'OPEN' ? <SlaChip ticket={t} /> : null}
                    </div>
                    <div className="break-words text-sm text-slate-600 dark:text-slate-300">
                      {r.platform_label} · Order {r.order_id} · {formatDate(r.entry_date)}
                    </div>
                    <div className="break-words text-sm text-slate-600 dark:text-slate-300">
                      {r.product_text} · Qty {r.qty}
                    </div>
                    <div className="text-xs text-slate-500">
                      Due {formatDateTime(t.sla_due_at)}
                      {t.raised_at
                        ? ` · raised ${formatDateTime(t.raised_at)} by ${t.assigned_handler_name ?? '—'}`
                        : ''}
                      {t.response_label ? ` · ${t.response_label}` : ''}
                      {t.claim_amount ? ` ₹${t.claim_amount}` : ''}
                    </div>
                    {t.follow_up_count > 0 ? (
                      <div className="text-xs text-slate-500" data-testid="ticket-follow-ups">
                        {t.follow_up_count} follow-up(s)
                        {t.last_follow_up_at
                          ? ` · last ${formatDateTime(t.last_follow_up_at)}`
                          : ''}
                        {t.next_follow_up_on ? ` · next ${formatDate(t.next_follow_up_on)}` : ''}
                      </div>
                    ) : null}
                  </div>
                  <ChevronRight className="h-5 w-5 shrink-0 text-slate-400" aria-hidden="true" />
                </button>
                {canEdit && state === 'OPEN' ? (
                  <div className="flex flex-col gap-2 sm:flex-row">
                    {!t.raised_at ? (
                      <Button
                        type="button"
                        className="min-h-[44px]"
                        disabled={busy}
                        data-testid="ticket-raise"
                        onClick={() => {
                          void act(r, (key) => ecomApi.raise(t.id, key));
                        }}
                      >
                        Mark raised on platform
                      </Button>
                    ) : (
                      <>
                        <Button
                          type="button"
                          variant="outline"
                          className="min-h-[44px]"
                          disabled={busy}
                          data-testid="ticket-follow-up"
                          onClick={() => {
                            setFollowing(r);
                          }}
                        >
                          Follow-up
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          className="min-h-[44px]"
                          disabled={busy}
                          data-testid="ticket-respond"
                          onClick={() => {
                            setResponding(r);
                          }}
                        >
                          Record response
                        </Button>
                        <Button
                          type="button"
                          className="min-h-[44px]"
                          disabled={busy || !final}
                          title={final ? undefined : 'Record a final response first (not Pending)'}
                          data-testid="ticket-close"
                          onClick={() => {
                            setClosing(r);
                          }}
                        >
                          Close ticket
                        </Button>
                      </>
                    )}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      {closing && query.data ? (
        <ResolutionModal
          title={`Close ticket · ${closing.return_no}`}
          intro={
            <p className="m-0 text-sm text-slate-600 dark:text-slate-300">
              {closing.platform_label} · Order {closing.order_id} · {closing.product_text} · Qty{' '}
              {closing.qty}. Check the order on the portal and record what it shows.
            </p>
          }
          options={query.data.resolution_options}
          maxQty={closing.qty}
          submitLabel="Close ticket"
          onSubmit={(body, key) => ecomApi.close(closing.ticket.id, body, key)}
          onClose={() => {
            setClosing(null);
          }}
          onDone={() => {
            setClosing(null);
            query.reload();
          }}
        />
      ) : null}
      {following ? (
        <FollowUpModal
          title={`Follow-up · ${following.return_no}`}
          today={todayLocal()}
          onSubmit={(body, key) => ecomApi.followUp(following.ticket.id, body, key)}
          onClose={() => {
            setFollowing(null);
          }}
          onDone={() => {
            setFollowing(null);
            query.reload();
          }}
        />
      ) : null}
      {responding && query.data ? (
        <ResponseModal
          row={responding}
          options={query.data.response_options}
          onClose={() => {
            setResponding(null);
          }}
          onDone={() => {
            setResponding(null);
            query.reload();
          }}
        />
      ) : null}
    </div>
  );
};

function ResponseModal({
  row,
  options,
  onClose,
  onDone,
}: {
  row: TicketRow;
  options: Option[];
  onClose: () => void;
  onDone: () => void;
}) {
  const t = row.ticket;
  const [code, setCode] = useState<ResponseCode | ''>(t.response_code ?? '');
  const [remark, setRemark] = useState(t.rejection_remark ?? '');
  const [amount, setAmount] = useState(t.claim_amount ?? '');
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const key = useRef(newIdempotencyKey());

  const save = async () => {
    setFieldError(null);
    if (!code) {
      setFieldError('Choose the platform response');
      return;
    }
    if (code === 'REJECTED' && remark.trim().length < 3) {
      setFieldError('A rejection remark is required');
      return;
    }
    if (code === 'CLAIM_RECEIVED' && !(Number(amount) > 0)) {
      setFieldError('Enter the claim amount the platform granted');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await ecomApi.respond(
        t.id,
        {
          response_code: code,
          rejection_remark: code === 'REJECTED' ? remark.trim() : null,
          claim_amount: code === 'CLAIM_RECEIVED' ? Number(amount).toFixed(2) : null,
        },
        key.current,
      );
      onDone();
    } catch (err) {
      console.error('Recording the response failed', { ticketId: t.id, err });
      setError(toApiError(err));
      key.current = newIdempotencyKey();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={`Platform response · ${row.return_no}`}
      footer={
        <>
          <Button type="button" variant="outline" className="min-h-[44px]" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            className="min-h-[44px]"
            disabled={busy}
            data-testid="ticket-response-save"
            onClick={() => {
              void save();
            }}
          >
            Save response
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <RadioGroup
          id="ticket-response"
          name="response_code"
          value={code}
          options={options.map((o) => ({ value: o.code, label: o.label }))}
          onChange={(v) => {
            setCode(v as ResponseCode);
          }}
        />
        {code === 'REJECTED' ? (
          <div>
            <label htmlFor="ticket-remark" className="form-control__label">
              Rejection remark <span className="text-red-600">*</span>
            </label>
            <Textarea
              id="ticket-remark"
              rows={3}
              maxLength={1000}
              value={remark}
              onChange={(e) => {
                setRemark(e.target.value);
              }}
            />
          </div>
        ) : null}
        {code === 'CLAIM_RECEIVED' ? (
          <div>
            <label htmlFor="ticket-amount" className="form-control__label">
              Claim amount (₹) <span className="text-red-600">*</span>
            </label>
            <Input
              id="ticket-amount"
              type="number"
              inputMode="decimal"
              min={0.01}
              step={0.01}
              value={amount}
              onChange={(e) => {
                setAmount(e.target.value);
              }}
            />
          </div>
        ) : null}
        {code === 'PENDING' ? (
          <p className="m-0 text-sm text-slate-600 dark:text-slate-300">
            The ticket stays open; update it when the platform answers.
          </p>
        ) : null}
        {fieldError ? (
          <p className="form-control__error" role="alert">
            {fieldError}
          </p>
        ) : null}
        {error ? <ErrorState error={error} title="Could not save" /> : null}
      </div>
    </Modal>
  );
}
