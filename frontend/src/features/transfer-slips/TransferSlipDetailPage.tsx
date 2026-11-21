/**
 * Phase P5 (DEC-65, Q20): on-screen view of a transfer slip, the same content as its A4 PDF:
 * header, a block per goods slip, the items for this store per GS with a subtotal, the other items
 * of these GSs greyed + struck through with the store they belong to, and the totals.
 *
 * Phase P6 (DEC-66; Q12, Q13): the users of the slip's Intermediate Store acknowledge the whole
 * slip (optional remark) or report a discrepancy (remark only; the slip stays open). Each GS block
 * also sums its items per condition. The other stores' items sit behind a toggle.
 */
import React, { useEffect, useRef, useState } from 'react';
import { AlertTriangle, ArrowLeft, CheckCircle2, FileDown } from 'lucide-react';

import { Button, Modal } from '@/components/ui';
import { PageHeader } from '@/components/erp';
import { newIdempotencyKey } from '@/lib/api/client';
import { formatDate, formatDateTime } from '@/features/goods-slips/format';

import { type SlipDetail, type SlipLine, slipErrorMessage, transferSlipsApi } from './api';
import { SlipStatusBadge } from './SlipStatusBadge';

interface Props {
  slipId: string;
  onBack: () => void;
  onOpenGs: (gsId: string) => void;
  /** Label of the back button (the RM's list or the store's acknowledgement list). */
  backLabel?: string;
}

const card =
  'rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900';
const textarea =
  'w-full rounded-lg border border-slate-300 bg-white p-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100';

const LineRow: React.FC<{ ln: SlipLine; muted?: boolean }> = ({ ln, muted }) => (
  <li
    className={`flex items-start justify-between gap-3 px-3 py-2 text-xs ${
      muted ? 'text-slate-400 line-through dark:text-slate-500' : ''
    }`}
  >
    <span className="min-w-0 break-words">
      <span className="font-semibold">
        #{ln.line_no} {ln.product_code ? `${ln.product_code} · ` : ''}
        {ln.product_name}
      </span>
      <span className="block">
        {ln.bucket_label ?? '—'}
        {muted ? ` · ${ln.belongs_store_name}` : ''}
      </span>
    </span>
    <span className="shrink-0 font-bold">{ln.qty}</span>
  </li>
);

/** GS → condition → qty (DEC-66: the store checks the goods per condition). */
function byCondition(lines: SlipLine[]): { label: string; qty: number }[] {
  const out = new Map<string, number>();
  for (const ln of lines) {
    const label = ln.bucket_label ?? '—';
    out.set(label, (out.get(label) ?? 0) + ln.qty);
  }
  return [...out.entries()].map(([label, qty]) => ({ label, qty }));
}

/** Mounted per opening, so each command starts empty with its own Idempotency-Key. */
const AcknowledgeModal: React.FC<{
  slip: SlipDetail;
  mode: 'acknowledge' | 'discrepancy';
  onClose: () => void;
  onDone: (slip: SlipDetail) => void;
}> = ({ slip, mode, onClose, onDone }) => {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const keyRef = useRef(newIdempotencyKey());
  const ack = mode === 'acknowledge';
  const valid = ack || text.trim().length >= 3;

  const submit = () => {
    setBusy(true);
    setError(null);
    const call = ack
      ? transferSlipsApi.acknowledge(slip.id, text.trim() || null, keyRef.current)
      : transferSlipsApi.reportDiscrepancy(slip.id, text.trim(), keyRef.current);
    call
      .then(onDone)
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
      title={ack ? `Acknowledge ${slip.slip_no}` : `Report discrepancy · ${slip.slip_no}`}
      footer={
        <>
          <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            type="button"
            variant={ack ? 'primary' : 'danger'}
            onClick={submit}
            disabled={!valid || busy}
            isLoading={busy}
          >
            {ack ? 'Confirm receipt' : 'Send report'}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        {ack ? (
          <p className="text-slate-700 dark:text-slate-200">
            You confirm that <strong>{slip.store.name}</strong> received all{' '}
            <strong>{slip.relevant_qty} pc</strong> of this slip ({slip.gs_count} goods slip
            {slip.gs_count === 1 ? '' : 's'}). The goods move into the store; this cannot be undone.
            If anything is missing or different, cancel and report a discrepancy instead.
          </p>
        ) : (
          <p className="text-slate-700 dark:text-slate-200">
            The Replacement Manager and Management are alerted. No quantity changes; the slip stays
            open until you acknowledge it.
          </p>
        )}
        <label htmlFor="slip-ack-text" className="block font-medium">
          {ack ? 'Remark (optional)' : 'What is wrong?'}
        </label>
        <textarea
          id="slip-ack-text"
          value={text}
          onChange={(e) => {
            setText(e.target.value);
          }}
          rows={3}
          maxLength={2000}
          className={textarea}
        />
        {error ? (
          <div
            role="alert"
            className="rounded-lg bg-rose-50 p-3 text-xs text-rose-700 dark:bg-rose-950/40 dark:text-rose-300 break-words"
          >
            {error}
          </div>
        ) : null}
      </div>
    </Modal>
  );
};

export const TransferSlipDetailPage: React.FC<Props> = ({
  slipId,
  onBack,
  onOpenGs,
  backLabel = 'Transfer Slips',
}) => {
  const [slip, setSlip] = useState<SlipDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [reload, setReload] = useState(0);
  const [showOthers, setShowOthers] = useState(false);
  const [dialog, setDialog] = useState<'acknowledge' | 'discrepancy' | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    transferSlipsApi
      .detail(slipId)
      .then((d) => {
        if (active) {
          setSlip(d);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (active) setError(slipErrorMessage(err));
      });
    return () => {
      active = false;
    };
  }, [slipId, reload]);

  const back = (
    <Button type="button" variant="outline" className="min-h-[44px]" onClick={onBack}>
      <ArrowLeft className="h-4 w-4" aria-hidden="true" /> {backLabel}
    </Button>
  );

  if (error) {
    return (
      <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
        {back}
        <div
          role="alert"
          className="flex flex-col items-center gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300"
        >
          <span className="break-words">{error}</span>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              setError(null);
              setReload((k) => k + 1);
            }}
          >
            Retry
          </Button>
        </div>
      </div>
    );
  }
  if (!slip) {
    return (
      <div role="status" className="p-10 text-center text-slate-400 animate-pulse">
        Loading transfer slip…
      </div>
    );
  }

  const others = slip.lines.filter((l) => !l.is_relevant);
  const download = () => {
    setDownloading(true);
    setPdfError(null);
    transferSlipsApi
      .downloadPdf(slip)
      .catch((err: unknown) => {
        setPdfError(slipErrorMessage(err));
      })
      .finally(() => {
        setDownloading(false);
      });
  };

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6" data-testid="transfer-slip-detail">
      {back}
      <PageHeader
        title={<span className="font-mono">{slip.slip_no}</span>}
        subtitle={`${slip.store.name} · ${formatDateTime(slip.generated_at)} · ${
          slip.generated_by_name ?? '—'
        }`}
        actions={
          <Button
            type="button"
            variant="outline"
            className="min-h-[44px]"
            onClick={download}
            isLoading={downloading}
          >
            <FileDown className="h-4 w-4" aria-hidden="true" /> Download PDF
          </Button>
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <SlipStatusBadge status={slip.status} />
        {slip.void_reason ? (
          <span className="text-xs text-slate-500 break-words">{slip.void_reason}</span>
        ) : null}
      </div>
      {pdfError ? (
        <div role="alert" className="rounded-lg bg-rose-50 p-3 text-xs text-rose-700">
          {pdfError}
        </div>
      ) : null}
      {notice ? (
        <div
          role="status"
          className="flex items-start gap-2 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300"
        >
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span className="break-words">{notice}</span>
        </div>
      ) : null}

      {slip.can_acknowledge ? (
        <section
          aria-label="Acknowledge receipt"
          className={`${card} space-y-3 border-indigo-200 p-3 sm:p-4 dark:border-indigo-900`}
          data-testid="slip-ack-panel"
        >
          <p className="text-sm text-slate-700 dark:text-slate-200">
            Check the goods against this slip: <strong>{slip.relevant_qty} pc</strong> for{' '}
            {slip.store.name}. Acknowledge only when everything is received.
          </p>
          <div className="grid grid-cols-1 gap-2 sm:flex">
            <Button
              type="button"
              variant="primary"
              className="min-h-[44px]"
              onClick={() => {
                setNotice(null);
                setDialog('acknowledge');
              }}
            >
              <CheckCircle2 className="h-4 w-4" aria-hidden="true" /> Acknowledge receipt
            </Button>
            <Button
              type="button"
              variant="outline"
              className="min-h-[44px]"
              onClick={() => {
                setNotice(null);
                setDialog('discrepancy');
              }}
            >
              <AlertTriangle className="h-4 w-4" aria-hidden="true" /> Report discrepancy
            </Button>
          </div>
        </section>
      ) : null}

      {slip.acknowledged_at ? (
        <section className={`${card} p-3 text-sm`} aria-label="Acknowledgement">
          <p className="font-semibold text-emerald-700 dark:text-emerald-400">
            Acknowledged by {slip.acknowledged_by_name ?? '—'} ·{' '}
            {formatDateTime(slip.acknowledged_at)}
          </p>
          {slip.acknowledge_remarks ? (
            <p className="mt-1 text-xs text-slate-600 dark:text-slate-300 break-words">
              {slip.acknowledge_remarks}
            </p>
          ) : null}
        </section>
      ) : null}

      {slip.discrepancies.length ? (
        <section aria-labelledby="slip-discrepancies" className="space-y-2">
          <h2
            id="slip-discrepancies"
            className="text-sm font-bold text-amber-700 dark:text-amber-400"
          >
            Discrepancies reported
          </h2>
          <ul className={`${card} divide-y divide-slate-100 dark:divide-slate-800`}>
            {slip.discrepancies.map((d) => (
              <li key={d.id} className="px-3 py-2 text-xs">
                <span className="block break-words text-slate-800 dark:text-slate-100">
                  {d.remark}
                </span>
                <span className="text-slate-500">
                  {d.reported_by_name ?? '—'} · {formatDateTime(d.reported_at)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="slip-relevant" className="space-y-3">
        <h2 id="slip-relevant" className="text-sm font-bold text-slate-900 dark:text-slate-100">
          Items for this store
        </h2>
        {slip.goods_slips.map((g) => {
          const rel = slip.lines.filter((l) => l.is_relevant && l.gs_id === g.gs_id);
          const conditions = byCondition(rel);
          return (
            <div key={g.gs_id} className={`${card} overflow-hidden`}>
              <div className="border-b border-slate-100 p-3 dark:border-slate-800">
                <button
                  type="button"
                  className="min-h-[44px] font-mono text-sm font-bold text-indigo-700 hover:underline dark:text-indigo-300"
                  onClick={() => {
                    onOpenGs(g.gs_id);
                  }}
                >
                  {g.gs_no}
                </button>
                <p className="text-xs text-slate-600 dark:text-slate-300 break-words">
                  {g.party_name ?? '—'}
                  {g.station_name ? ` · ${g.station_name}` : ''}
                  {g.state_name ? `, ${g.state_name}` : ''} · {g.cartons ?? '—'} carton(s) ·
                  received {formatDate(g.received_date)}
                </p>
                {conditions.length ? (
                  <ul
                    className="mt-2 flex list-none flex-wrap gap-1.5 p-0"
                    aria-label={`${g.gs_no} by condition`}
                  >
                    {conditions.map((c) => (
                      <li
                        key={c.label}
                        className="m-0 list-none rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200"
                      >
                        {c.label}: {c.qty}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
              {rel.length ? (
                <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                  {rel.map((ln) => (
                    <LineRow key={ln.id} ln={ln} />
                  ))}
                </ul>
              ) : (
                <p className="px-3 py-2 text-xs text-slate-500">No items for this store.</p>
              )}
              <div className="flex justify-between bg-slate-50 px-3 py-2 text-xs font-bold dark:bg-slate-800/60">
                <span>Subtotal {g.gs_no}</span>
                <span>{g.relevant_qty}</span>
              </div>
            </div>
          );
        })}
      </section>

      {others.length ? (
        <section aria-labelledby="slip-others" className="space-y-2">
          <label className="flex min-h-[44px] cursor-pointer items-center gap-3 text-sm font-medium text-slate-700 dark:text-slate-200">
            <input
              type="checkbox"
              className="h-5 w-5"
              checked={showOthers}
              onChange={(e) => {
                setShowOthers(e.target.checked);
              }}
            />
            Show other items of these goods slips ({others.length})
          </label>
          {showOthers ? (
            <>
              <h2 id="slip-others" className="text-sm font-bold text-slate-500">
                Other items of these goods slips (other stores)
              </h2>
              <ul className={`${card} divide-y divide-slate-100 dark:divide-slate-800`}>
                {others.map((ln) => (
                  <LineRow key={ln.id} ln={ln} muted />
                ))}
              </ul>
            </>
          ) : null}
        </section>
      ) : null}

      <section className={`${card} divide-y divide-slate-100 text-sm dark:divide-slate-800`}>
        <div className="flex justify-between px-3 py-2 font-bold">
          <span>Total relevant qty (this store)</span>
          <span data-testid="slip-relevant-qty">{slip.relevant_qty}</span>
        </div>
        <div className="flex justify-between px-3 py-2">
          <span>Grand total (all items of included GSs)</span>
          <span data-testid="slip-grand-total">{slip.grand_total_qty}</span>
        </div>
      </section>

      {dialog ? (
        <AcknowledgeModal
          key={dialog}
          slip={slip}
          mode={dialog}
          onClose={() => {
            setDialog(null);
          }}
          onDone={(updated) => {
            setSlip(updated);
            setNotice(
              dialog === 'acknowledge'
                ? `${updated.slip_no} acknowledged. The goods are now in ${updated.store.name}.`
                : 'Discrepancy reported to the Replacement Manager and Management.',
            );
            setDialog(null);
          }}
        />
      ) : null}
    </div>
  );
};
