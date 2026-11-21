/**
 * Phase P5 (DEC-65, Q20): on-screen view of a transfer slip, the same content as its A4 PDF:
 * header, a block per goods slip, the items for this store per GS with a subtotal, the other items
 * of these GSs greyed + struck through with the store they belong to, and the totals.
 */
import React, { useEffect, useState } from 'react';
import { ArrowLeft, FileDown } from 'lucide-react';

import { Button } from '@/components/ui';
import { PageHeader } from '@/components/erp';
import { formatDate, formatDateTime } from '@/features/goods-slips/format';

import { type SlipDetail, type SlipLine, slipErrorMessage, transferSlipsApi } from './api';
import { SlipStatusBadge } from './SlipStatusBadge';

interface Props {
  slipId: string;
  onBack: () => void;
  onOpenGs: (gsId: string) => void;
}

const card =
  'rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900';

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

export const TransferSlipDetailPage: React.FC<Props> = ({ slipId, onBack, onOpenGs }) => {
  const [slip, setSlip] = useState<SlipDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [reload, setReload] = useState(0);

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
      <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Transfer Slips
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
            variant="primary"
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

      <section aria-labelledby="slip-relevant" className="space-y-3">
        <h2 id="slip-relevant" className="text-sm font-bold text-slate-900 dark:text-slate-100">
          Items for this store
        </h2>
        {slip.goods_slips.map((g) => {
          const rel = slip.lines.filter((l) => l.is_relevant && l.gs_id === g.gs_id);
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
          <h2 id="slip-others" className="text-sm font-bold text-slate-500">
            Other items of these goods slips (other stores)
          </h2>
          <ul className={`${card} divide-y divide-slate-100 dark:divide-slate-800`}>
            {others.map((ln) => (
              <LineRow key={ln.id} ln={ln} muted />
            ))}
          </ul>
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
    </div>
  );
};
