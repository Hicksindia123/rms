import { useCallback, useState } from 'react';
import { AlertTriangle, ArrowLeft, CheckCircle2, Printer, ShieldCheck, Undo2 } from 'lucide-react';

import { Badge, Button, ErrorState, LoadingState, Modal, Select, Textarea } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { newIdempotencyKey, toApiError, type ApiError } from '@/lib/api/client';
import { formatDateTime } from '@/features/goods-slips/format';
import { QtyStepper } from '@/features/itemization/LineParts';
import { custodyApi } from './api';
import { TransferStatusBadge } from './display';
import { countMismatches, lineTitle } from './rules';
import type { CustodyLookups, TransferDetail } from './types';

interface Props {
  transferId: string;
  onBack: () => void;
  onOpenTransfer: (id: string) => void;
  onOpenNote: (id: string) => void;
  onOpenGs?: (id: string) => void;
}

interface Loaded {
  transfer: TransferDetail;
  lookups: CustodyLookups;
}

export function TransferDetailPage({
  transferId,
  onBack,
  onOpenTransfer,
  onOpenNote,
  onOpenGs,
}: Props) {
  const fetcher = useCallback(
    () =>
      Promise.all([custodyApi.detail(transferId), custodyApi.lookups()]).then(
        ([transfer, lookups]): Loaded => ({ transfer, lookups }),
      ),
    [transferId],
  );
  const { data, error, loading, reload, setData } = useApiQuery<Loaded>(fetcher);
  const back = (
    <Button type="button" variant="ghost" onClick={onBack} className="no-print">
      <ArrowLeft size={16} aria-hidden="true" /> Transfers
    </Button>
  );
  if (error) {
    return (
      <div className="page page--narrow">
        {back}
        <h1 className="page__title">Custody transfer</h1>
        <ErrorState error={error} onRetry={reload} />
      </div>
    );
  }
  if (loading || !data) {
    return (
      <div className="page page--narrow">
        {back}
        <h1 className="page__title">Custody transfer</h1>
        <LoadingState />
      </div>
    );
  }
  const t = data.transfer;
  const update = (next: TransferDetail) => {
    setData({ ...data, transfer: next });
  };
  const sum = (key: 'qty_counted' | 'qty_accepted' | 'qty_returned') =>
    t.lines.reduce((a, l) => a + (l[key] ?? 0), 0);

  return (
    <div className="page page--narrow">
      {back}
      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
        <h1 className="page__title" style={{ margin: 0 }}>
          {t.transfer_no}
        </h1>
        <TransferStatusBadge status={t.status} inTransit={t.stock_moved} />
        {t.with_packaging ? <Badge variant="info">With packaging</Badge> : null}
      </div>
      <p className="page__subtitle" style={{ marginTop: '0.25rem' }}>
        {t.from_location_name} → {t.to_location_name}
        {t.mode_label ? ` · ${t.mode_label}` : ''}
      </p>

      {t.status === 'INITIATED' && t.stock_moved ? (
        <div className="banner" role="status" style={{ marginBottom: '1rem' }}>
          In transit — neither {t.from_location_name} nor {t.to_location_name} holds these goods
          until the count is accepted.
        </div>
      ) : null}
      {t.status === 'DISCREPANCY' ? (
        <div className="banner" role="alert" style={{ marginBottom: '1rem' }}>
          <AlertTriangle size={18} aria-hidden="true" /> Discrepancy reported — the transfer is
          frozen in transit until both parties reconcile it. {t.discrepancy_notes ?? ''}
        </div>
      ) : null}

      <dl className="kv card" style={{ padding: '1rem', marginBottom: '1rem' }}>
        {t.gs_no ? (
          <div>
            <dt>Goods slip</dt>
            <dd>
              {onOpenGs && t.gs_id ? (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    onOpenGs(t.gs_id ?? '');
                  }}
                >
                  {t.gs_no}
                </Button>
              ) : (
                t.gs_no
              )}
            </dd>
          </div>
        ) : null}
        <div>
          <dt>Initiated</dt>
          <dd>
            {t.initiated_by_name} · {formatDateTime(t.initiated_at)}
          </dd>
        </div>
        {t.accepted_by_name ? (
          <div>
            <dt>Counted by</dt>
            <dd>
              {t.accepted_by_name} · {formatDateTime(t.accepted_at)}
              {t.acceptance_label ? ` · ${t.acceptance_label}` : ''}
            </dd>
          </div>
        ) : null}
        <div>
          <dt>Quantity sent</dt>
          <dd>
            {t.total_qty === null
              ? 'Hidden until your count is submitted'
              : `${String(t.total_qty)} pcs`}
          </dd>
        </div>
        {t.status !== 'INITIATED' && t.status !== 'CANCELLED' ? (
          <div>
            <dt>Counted / accepted / returned</dt>
            <dd>
              {String(sum('qty_counted'))} / {String(sum('qty_accepted'))} /{' '}
              {String(sum('qty_returned'))}
            </dd>
          </div>
        ) : null}
        {t.cancel_reason ? (
          <div>
            <dt>Cancelled</dt>
            <dd>{t.cancel_reason}</dd>
          </div>
        ) : null}
        {t.supersedes_transfer_id ? (
          <div>
            <dt>Corrected resend of</dt>
            <dd>
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  onOpenTransfer(t.supersedes_transfer_id ?? '');
                }}
              >
                Original transfer
              </Button>
            </dd>
          </div>
        ) : null}
      </dl>

      {t.permissions.can_accept ? (
        <ReceivePanel transfer={t} lookups={data.lookups} onDone={update} />
      ) : (
        <LinesTable transfer={t} />
      )}

      {t.reconciliations.length > 0 || t.status === 'DISCREPANCY' ? (
        <ReconcilePanel
          transfer={t}
          lookups={data.lookups}
          onDone={update}
          onOpenTransfer={onOpenTransfer}
        />
      ) : null}

      <div
        style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginTop: '1rem' }}
        className="no-print"
      >
        {t.permissions.can_print ? (
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              onOpenNote(t.id);
            }}
          >
            <Printer size={16} aria-hidden="true" /> Transfer Note
          </Button>
        ) : null}
        {t.permissions.can_cancel ? <CancelButton transfer={t} onDone={update} /> : null}
      </div>
    </div>
  );
}

function LinesTable({ transfer }: { transfer: TransferDetail }) {
  return (
    <ul className="custody-lines" aria-label="Transfer lines">
      {transfer.lines.map((l) => (
        <li key={l.lot_id} className="card custody-line">
          <div className="custody-line__head">
            <strong>{lineTitle(l)}</strong>
            {l.condition_label ? <Badge variant="info">{l.condition_label}</Badge> : null}
          </div>
          <p style={{ margin: '0.25rem 0 0', fontSize: '0.875rem' }}>
            Sent {l.qty_sent === null ? '—' : String(l.qty_sent)}
            {l.qty_counted !== null ? ` · counted ${String(l.qty_counted)}` : ''}
            {l.qty_accepted ? ` · accepted ${String(l.qty_accepted)}` : ''}
            {l.qty_returned ? ` · returned ${String(l.qty_returned)}` : ''}
            {l.qty_adjusted ? ` · adjusted ${String(l.qty_adjusted)}` : ''}
          </p>
        </li>
      ))}
    </ul>
  );
}

/** Sahil's physical count (BR-21). Blind count ([IMP] setting) hides the quantity sent. */
function ReceivePanel({
  transfer,
  lookups,
  onDone,
}: {
  transfer: TransferDetail;
  lookups: CustodyLookups;
  onDone: (t: TransferDetail) => void;
}) {
  const blind = transfer.blind_count;
  const [counts, setCounts] = useState<Record<string, number>>(() =>
    Object.fromEntries(transfer.lines.map((l) => [l.lot_id, blind ? 0 : (l.qty_sent ?? 0)])),
  );
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [idemKey, setIdemKey] = useState(newIdempotencyKey);
  const mismatched = new Set(countMismatches(transfer.lines, counts));
  const accepted = lookups.acceptance_options.find((o) => o.code === 'ACCEPTED_VERIFIED');
  const discrepancy = lookups.acceptance_options.find((o) => o.code === 'DISCREPANCY');

  const submit = async (code: string) => {
    setBusy(code);
    setFailure(null);
    try {
      const next = await custodyApi.accept(
        transfer.id,
        {
          lines: transfer.lines.map((l) => ({
            lot_id: l.lot_id,
            qty_counted: counts[l.lot_id] ?? 0,
          })),
          acceptance_code: code,
          notes: notes.trim() || null,
        },
        idemKey,
      );
      onDone(next);
    } catch (err) {
      const apiErr = toApiError(err);
      setFailure(apiErr);
      if (apiErr.status >= 400 && apiErr.status < 500) setIdemKey(newIdempotencyKey());
    } finally {
      setBusy(null);
    }
  };

  return (
    <section aria-label="Count and accept">
      <h2 style={{ fontSize: '1rem', margin: '0 0 0.5rem' }}>Physical count</h2>
      {blind ? (
        <p className="page__subtitle">
          Blind count: enter what you counted; the sent quantity is shown afterwards.
        </p>
      ) : null}
      <ul className="custody-lines">
        {transfer.lines.map((l) => (
          <li
            key={l.lot_id}
            className={`card custody-line${mismatched.has(l.lot_id) ? ' custody-line--alert' : ''}`}
          >
            <div className="custody-line__head">
              <strong>{lineTitle(l)}</strong>
              {l.condition_label ? <Badge variant="info">{l.condition_label}</Badge> : null}
            </div>
            <QtyStepper
              id={`count-${l.lot_id}`}
              label={blind ? 'Counted' : `Counted (sent ${String(l.qty_sent ?? 0)})`}
              value={counts[l.lot_id] ?? 0}
              onChange={(v) => {
                setCounts((c) => ({ ...c, [l.lot_id]: v }));
              }}
            />
          </li>
        ))}
      </ul>
      <label className="form-label" htmlFor="receive-notes">
        Discrepancy details {mismatched.size > 0 ? '(required)' : '(only if the count differs)'}
      </label>
      <Textarea
        id="receive-notes"
        rows={2}
        value={notes}
        onChange={(e) => {
          setNotes(e.target.value);
        }}
      />
      {failure ? <ErrorState error={failure} title="Count not recorded" /> : null}
      <div className="sticky-submit" style={{ display: 'grid', gap: '0.5rem' }}>
        {accepted ? (
          <Button
            type="button"
            variant="primary"
            size="lg"
            isLoading={busy === accepted.code}
            disabled={busy !== null || (!blind && mismatched.size > 0)}
            onClick={() => {
              void submit(accepted.code);
            }}
          >
            <CheckCircle2 size={18} aria-hidden="true" /> {accepted.label}
          </Button>
        ) : null}
        {discrepancy ? (
          <Button
            type="button"
            variant="danger"
            size="lg"
            isLoading={busy === discrepancy.code}
            disabled={busy !== null || !notes.trim() || (!blind && mismatched.size === 0)}
            onClick={() => {
              void submit(discrepancy.code);
            }}
          >
            <AlertTriangle size={18} aria-hidden="true" /> {discrepancy.label}
          </Button>
        ) : null}
      </div>
    </section>
  );
}

/** BR-21: both parties sign the same resolution, or the RM overrides (audited). */
function ReconcilePanel({
  transfer,
  lookups,
  onDone,
  onOpenTransfer,
}: {
  transfer: TransferDetail;
  lookups: CustodyLookups;
  onDone: (t: TransferDetail) => void;
  onOpenTransfer: (id: string) => void;
}) {
  const open = transfer.reconciliations.find(
    (r) => r.status === 'PROPOSED' || r.status === 'AWAITING_RM_APPROVAL',
  );
  const [resolution, setResolution] = useState(open?.resolution_code ?? '');
  const [disposition, setDisposition] = useState(open?.difference_disposition ?? '');
  const [notes, setNotes] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [idemKey, setIdemKey] = useState(newIdempotencyKey);
  const perms = transfer.permissions;
  const canAct =
    transfer.status === 'DISCREPANCY' && (perms.reconcile_side !== null || perms.can_override);
  const needsDisposition = resolution === 'ACCEPT_COUNTED_WITH_ADJUSTMENT';

  const run = async (action: () => Promise<TransferDetail>) => {
    setBusy(true);
    setFailure(null);
    try {
      onDone(await action());
      setNotes('');
      setReason('');
      setIdemKey(newIdempotencyKey());
    } catch (err) {
      const apiErr = toApiError(err);
      setFailure(apiErr);
      if (apiErr.status >= 400 && apiErr.status < 500) setIdemKey(newIdempotencyKey());
    } finally {
      setBusy(false);
    }
  };
  const body = (override: boolean) => ({
    resolution_code: resolution,
    notes: notes.trim(),
    ...(needsDisposition ? { difference_disposition: disposition || null } : {}),
    ...(override ? { override: true } : {}),
  });

  return (
    <section aria-label="Reconciliation" style={{ marginTop: '1rem' }}>
      <h2 style={{ fontSize: '1rem', margin: '0 0 0.5rem' }}>Reconciliation</h2>
      {transfer.reconciliations.length > 0 ? (
        <ul className="custody-lines">
          {transfer.reconciliations.map((r) => (
            <li
              key={r.id}
              className={`card custody-line${r.status === 'SUPERSEDED' ? ' custody-line--muted' : ''}`}
            >
              <div className="custody-line__head">
                <strong>{r.resolution_label}</strong>
                <Badge
                  variant={
                    r.status === 'APPLIED'
                      ? 'success'
                      : r.status === 'SUPERSEDED'
                        ? 'neutral'
                        : 'warning'
                  }
                >
                  {r.status === 'AWAITING_RM_APPROVAL'
                    ? 'Awaiting RM approval'
                    : r.status.toLowerCase()}
                </Badge>
                {r.is_rm_override ? <Badge variant="danger">RM override</Badge> : null}
              </div>
              <p style={{ margin: '0.25rem 0 0', fontSize: '0.875rem' }}>{r.notes}</p>
              <p
                style={{
                  margin: '0.25rem 0 0',
                  fontSize: '0.8125rem',
                  color: 'var(--color-muted)',
                }}
              >
                Sender: {r.initiator_signed_by_name ?? 'not signed'} · Receiver:{' '}
                {r.receiver_signed_by_name ?? 'not signed'}
                {r.rm_approved_by_name
                  ? ` · RM: ${r.rm_approved_by_name} (${r.rm_reason ?? ''})`
                  : ''}
              </p>
              {r.resend_transfer_id ? (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    onOpenTransfer(r.resend_transfer_id ?? '');
                  }}
                >
                  Open corrected transfer
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      {canAct ? (
        <div className="card" style={{ padding: '1rem', display: 'grid', gap: '0.75rem' }}>
          <div>
            <label className="form-label" htmlFor="recon-resolution">
              Resolution
            </label>
            <Select
              id="recon-resolution"
              value={resolution}
              options={lookups.resolution_options.map((o) => ({ value: o.code, label: o.label }))}
              onChange={(e) => {
                setResolution(e.target.value);
              }}
            />
            {lookups.resolution_options.find((o) => o.code === resolution)?.description ? (
              <p className="page__subtitle" style={{ margin: '0.25rem 0 0' }}>
                {lookups.resolution_options.find((o) => o.code === resolution)?.description}
              </p>
            ) : null}
          </div>
          {needsDisposition ? (
            <div>
              <label className="form-label" htmlFor="recon-disposition">
                Pieces not counted
              </label>
              <Select
                id="recon-disposition"
                value={disposition}
                options={lookups.disposition_options.map((o) => ({
                  value: o.code,
                  label: o.label,
                }))}
                onChange={(e) => {
                  setDisposition(e.target.value);
                }}
              />
            </div>
          ) : null}
          <div>
            <label className="form-label" htmlFor="recon-notes">
              Notes
            </label>
            <Textarea
              id="recon-notes"
              rows={2}
              value={notes}
              onChange={(e) => {
                setNotes(e.target.value);
              }}
            />
          </div>
          {failure ? <ErrorState error={failure} title="Reconciliation not recorded" /> : null}
          <div style={{ display: 'grid', gap: '0.5rem' }}>
            {perms.reconcile_side ? (
              <Button
                type="button"
                variant="primary"
                size="lg"
                isLoading={busy}
                disabled={!resolution || !notes.trim() || (needsDisposition && !disposition)}
                onClick={() => {
                  void run(() => custodyApi.reconcile(transfer.id, body(false), idemKey));
                }}
              >
                <ShieldCheck size={18} aria-hidden="true" /> Sign as{' '}
                {perms.reconcile_side === 'INITIATOR' ? 'sender' : 'receiver'}
              </Button>
            ) : null}
            {perms.can_override ? (
              <Button
                type="button"
                variant="danger"
                isLoading={busy}
                disabled={!resolution || !notes.trim() || (needsDisposition && !disposition)}
                onClick={() => {
                  void run(() => custodyApi.reconcile(transfer.id, body(true), idemKey));
                }}
              >
                RM override (audited)
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}

      {perms.can_approve_adjustment ? (
        <div
          className="card"
          style={{ padding: '1rem', display: 'grid', gap: '0.75rem', marginTop: '0.75rem' }}
        >
          <label className="form-label" htmlFor="recon-approve">
            Approve the stock adjustment — reason
          </label>
          <Textarea
            id="recon-approve"
            rows={2}
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
            }}
          />
          <Button
            type="button"
            variant="primary"
            isLoading={busy}
            disabled={!reason.trim()}
            onClick={() => {
              void run(() => custodyApi.approve(transfer.id, reason.trim(), idemKey));
            }}
          >
            Approve adjustment
          </Button>
        </div>
      ) : null}
    </section>
  );
}

function CancelButton({
  transfer,
  onDone,
}: {
  transfer: TransferDetail;
  onDone: (t: TransferDetail) => void;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [idemKey, setIdemKey] = useState(newIdempotencyKey);
  const confirm = async () => {
    setBusy(true);
    setFailure(null);
    try {
      onDone(await custodyApi.cancel(transfer.id, reason.trim(), idemKey));
      setOpen(false);
    } catch (err) {
      const apiErr = toApiError(err);
      setFailure(apiErr);
      if (apiErr.status >= 400 && apiErr.status < 500) setIdemKey(newIdempotencyKey());
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Button
        type="button"
        variant="outline"
        onClick={() => {
          setOpen(true);
        }}
      >
        <Undo2 size={16} aria-hidden="true" /> Cancel transfer
      </Button>
      <Modal
        isOpen={open}
        onClose={() => {
          setOpen(false);
        }}
        title={`Cancel ${transfer.transfer_no}`}
        footer={
          <Button
            type="button"
            variant="danger"
            isLoading={busy}
            disabled={!reason.trim()}
            onClick={() => {
              void confirm();
            }}
          >
            Return goods to {transfer.from_location_name}
          </Button>
        }
      >
        <label className="form-label" htmlFor="cancel-reason">
          Reason
        </label>
        <Textarea
          id="cancel-reason"
          rows={3}
          value={reason}
          onChange={(e) => {
            setReason(e.target.value);
          }}
        />
        {failure ? <ErrorState error={failure} title="Not cancelled" /> : null}
      </Modal>
    </>
  );
}
