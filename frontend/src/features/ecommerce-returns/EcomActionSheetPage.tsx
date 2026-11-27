/**
 * DEC-76: one E-Commerce Action Sheet (the "replacement slip / advice" of an e-commerce batch).
 * Printable: company, sheet no, PLATFORM, date, every order id with Qty Received and Qty Issue CN
 * (Refund → the executive's qty; Free Replacement → 0). E-Commerce Accounts enters the credit note
 * (number, date, value, remarks: the offline Accounts data, DEC-71) and completes the sheet.
 */
import React, { useCallback, useRef, useState } from 'react';
import { ArrowLeft, Printer, RefreshCw } from 'lucide-react';

import { Badge, Button, ErrorState, Input, LoadingState, Textarea } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { newIdempotencyKey, toApiError, type ApiError } from '@/lib/api/client';
import { formatDate, formatDateTime } from '@/features/goods-slips/format';

import { settlementApi } from './api';
import type { ActionSheet } from './types';

interface Props {
  sheetId: string;
  canIssueCn: boolean;
  onBack: () => void;
  onOpenReturn: (returnId: string) => void;
}

export const EcomActionSheetPage: React.FC<Props> = ({
  sheetId,
  canIssueCn,
  onBack,
  onOpenReturn,
}) => {
  const fetcher = useCallback(() => settlementApi.sheet(sheetId), [sheetId]);
  const query = useApiQuery<ActionSheet>(fetcher);

  const toolbar = (
    <div className="no-print flex flex-wrap gap-2">
      <Button type="button" variant="outline" className="min-h-[44px]" onClick={onBack}>
        <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Action sheets
      </Button>
      <Button type="button" variant="outline" className="min-h-[44px]" onClick={query.reload}>
        <RefreshCw className="h-4 w-4" aria-hidden="true" /> Refresh
      </Button>
      {query.data ? (
        <Button
          type="button"
          className="min-h-[44px]"
          data-testid="sheet-print"
          onClick={() => {
            window.print();
          }}
        >
          <Printer className="h-4 w-4" aria-hidden="true" /> Print
        </Button>
      ) : null}
    </div>
  );

  if (query.error) {
    return (
      <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
        {toolbar}
        <ErrorState error={query.error} onRetry={query.reload} title="Could not load the sheet" />
      </div>
    );
  }
  const s = query.data;
  if (!s) {
    return (
      <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
        <LoadingState label="Loading action sheet…" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6" data-testid="ecom-action-sheet">
      {toolbar}
      <article className="print-note space-y-4" aria-label={`Action sheet ${s.sheet_no}`}>
        <header className="space-y-1 text-center">
          {s.company_name ? <div className="text-sm font-semibold">{s.company_name}</div> : null}
          <h1 className="m-0 text-lg font-bold">E-Commerce Action Sheet</h1>
          <div className="text-2xl font-extrabold tracking-wide" data-testid="sheet-platform">
            {s.platform_label}
          </div>
        </header>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-xs text-slate-500">Sheet No</dt>
            <dd className="m-0 font-semibold">{s.sheet_no}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Date</dt>
            <dd className="m-0">{formatDate(s.created_at.slice(0, 10))}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Status</dt>
            <dd className="m-0">
              <Badge variant={s.status === 'COMPLETED' ? 'success' : 'warning'}>
                {s.status_label}
              </Badge>
            </dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Prepared by</dt>
            <dd className="m-0">{s.created_by_name ?? '—'}</dd>
          </div>
        </dl>

        {/* Phones: one card per order. Wider screens and print: the table. */}
        <ul className="m-0 list-none space-y-2 p-0 sm:hidden print:hidden" aria-label="Orders">
          {s.lines.map((l) => (
            <li
              key={l.return_id}
              className="rounded-lg border border-slate-200 p-3 text-sm dark:border-slate-700"
            >
              <button
                type="button"
                className="min-h-[44px] w-full border-0 bg-transparent p-0 text-left"
                onClick={() => {
                  onOpenReturn(l.return_id);
                }}
              >
                <div className="font-semibold break-words">Order {l.order_id}</div>
                <div className="break-words text-slate-600 dark:text-slate-300">
                  {l.product_text}
                </div>
                <div>
                  Qty Received <strong>{l.qty_received}</strong> · Qty Issue CN{' '}
                  <strong>{l.cn_qty}</strong>
                </div>
                <div className="text-xs text-slate-500">
                  {l.resolution_label} {l.resolution_qty} · Store {l.good_qty} · Repair{' '}
                  {l.repair_qty} · Wastage {l.wastage_qty} · {l.status_label}
                </div>
              </button>
            </li>
          ))}
        </ul>
        <div className="hidden sm:block print:block">
          <table className="print-note__table" data-testid="sheet-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Order ID</th>
                <th>Product</th>
                <th>Portal</th>
                <th>Qty Received</th>
                <th>Qty Issue CN</th>
                <th>Store / Repair / Wastage</th>
              </tr>
            </thead>
            <tbody>
              {s.lines.map((l, i) => (
                <tr key={l.return_id}>
                  <td>{i + 1}</td>
                  <td className="break-all">
                    <button
                      type="button"
                      className="border-0 bg-transparent p-0 text-left font-semibold text-indigo-700 underline dark:text-indigo-300 print:text-black print:no-underline"
                      onClick={() => {
                        onOpenReturn(l.return_id);
                      }}
                    >
                      {l.order_id}
                    </button>
                  </td>
                  <td>{l.product_text}</td>
                  <td>
                    {l.resolution_label} ({l.resolution_qty})
                  </td>
                  <td>{l.qty_received}</td>
                  <td>
                    <strong>{l.cn_qty}</strong>
                  </td>
                  <td>
                    {l.good_qty} / {l.repair_qty} / {l.wastage_qty}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th colSpan={4}>Total ({s.lines.length} order(s))</th>
                <th>{s.total_received}</th>
                <th>{s.total_cn_qty}</th>
                <th />
              </tr>
            </tfoot>
          </table>
        </div>
        <p className="m-0 text-sm sm:hidden print:hidden">
          Total: {s.lines.length} order(s) · Qty Received <strong>{s.total_received}</strong> · Qty
          Issue CN <strong>{s.total_cn_qty}</strong>
        </p>

        <section className="space-y-1 text-sm" aria-label="Credit note">
          <h2 className="m-0 text-base font-semibold">Credit note</h2>
          {s.total_cn_qty === 0 ? (
            <p className="m-0">No credit note: every order on this sheet is a free replacement.</p>
          ) : s.cn_no ? (
            <p className="m-0" data-testid="sheet-cn">
              CN No <strong>{s.cn_no}</strong> · {s.cn_date ? formatDate(s.cn_date) : ''} · ₹
              {s.cn_value}
              {s.completed_by_name ? ` · by ${s.completed_by_name}` : ''}
              {s.completed_at ? ` on ${formatDateTime(s.completed_at)}` : ''}
              {s.remarks ? ` · “${s.remarks}”` : ''}
            </p>
          ) : (
            <p className="m-0">Pending with Accounts: credit note for {s.total_cn_qty} pc(s).</p>
          )}
        </section>

        <div className="print-note__signatures">
          <div className="print-note__signature">Unboxing</div>
          <div className="print-note__signature">Accounts</div>
        </div>
      </article>

      {canIssueCn && s.status === 'PENDING_ACCOUNTS' && s.total_cn_qty > 0 ? (
        <IssueCnForm sheet={s} onDone={query.setData} />
      ) : null}
    </div>
  );
};

function IssueCnForm({ sheet, onDone }: { sheet: ActionSheet; onDone: (s: ActionSheet) => void }) {
  const [cnNo, setCnNo] = useState('');
  const [cnDate, setCnDate] = useState(sheet.business_today);
  const [cnValue, setCnValue] = useState('');
  const [remarks, setRemarks] = useState('');
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const key = useRef(newIdempotencyKey());

  const save = async () => {
    setFieldError(null);
    if (!cnNo.trim() || !cnDate || !(Number(cnValue) > 0)) {
      setFieldError('Enter the CN number, date and value');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const done = await settlementApi.complete(
        sheet.id,
        {
          cn_no: cnNo.trim(),
          cn_date: cnDate,
          cn_value: Number(cnValue).toFixed(2),
          remarks: remarks.trim() || null,
        },
        key.current,
      );
      onDone(done);
    } catch (err) {
      console.error('Issuing the credit note failed', { sheetId: sheet.id, err });
      setError(toApiError(err));
      key.current = newIdempotencyKey();
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      className="no-print space-y-3 rounded-xl border border-amber-300 bg-amber-50 p-4 dark:border-amber-700 dark:bg-amber-950"
      data-testid="sheet-issue-cn"
    >
      <h2 className="m-0 text-base font-semibold">
        Issue credit note · {sheet.total_cn_qty} pc(s)
      </h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div>
          <label htmlFor="cn-no" className="form-control__label">
            CN No <span className="text-red-600">*</span>
          </label>
          <Input
            id="cn-no"
            maxLength={60}
            value={cnNo}
            onChange={(e) => {
              setCnNo(e.target.value);
            }}
          />
        </div>
        <div>
          <label htmlFor="cn-date" className="form-control__label">
            CN Date <span className="text-red-600">*</span>
          </label>
          <Input
            id="cn-date"
            type="date"
            max={sheet.business_today}
            value={cnDate}
            onChange={(e) => {
              setCnDate(e.target.value);
            }}
          />
        </div>
        <div>
          <label htmlFor="cn-value" className="form-control__label">
            CN Value (₹) <span className="text-red-600">*</span>
          </label>
          <Input
            id="cn-value"
            type="number"
            inputMode="decimal"
            min={0.01}
            step={0.01}
            value={cnValue}
            onChange={(e) => {
              setCnValue(e.target.value);
            }}
          />
        </div>
      </div>
      <div>
        <label htmlFor="cn-remarks" className="form-control__label">
          Remarks
        </label>
        <Textarea
          id="cn-remarks"
          rows={2}
          maxLength={1000}
          value={remarks}
          onChange={(e) => {
            setRemarks(e.target.value);
          }}
        />
      </div>
      {fieldError ? (
        <p className="form-control__error m-0" role="alert">
          {fieldError}
        </p>
      ) : null}
      {error ? <ErrorState error={error} title="Could not issue the credit note" /> : null}
      <Button
        type="button"
        className="min-h-[44px] w-full sm:w-auto"
        disabled={busy}
        data-testid="sheet-complete"
        onClick={() => {
          void save();
        }}
      >
        Issue CN and complete
      </Button>
    </section>
  );
}
