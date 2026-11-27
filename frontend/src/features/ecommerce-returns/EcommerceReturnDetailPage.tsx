/**
 * DEC-73 / DEC-76: one E-Commerce Return: gate data, files (view), platform ticket with SLA and
 * follow-ups, the E-Commerce Executive's portal resolution, the settlement after unboxing (action
 * sheet, store receipts, repair, credit note) and the history. A DRAFT (upload not finished) can be
 * completed here by the E-Commerce gate user; Super Admin / Management can void it with a reason
 * until it is unboxed.
 */
import React, { useCallback, useRef, useState } from 'react';
import { ArrowLeft, Eye, RefreshCw, Trash2, Upload } from 'lucide-react';

import { PageHeader } from '@/components/erp';
import { Button, ErrorState, LoadingState, Modal, Textarea } from '@/components/ui';
import type { ErrorLike } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { newIdempotencyKey, toApiError, type ApiError } from '@/lib/api/client';
import { formatDate, formatDateTime } from '@/features/goods-slips/format';

import { ecomApi } from './api';
import { EcomStatusChip, SlaChip } from './SlaChip';
import type { EcomReturn, FormConfig, Media, MediaKind } from './types';
import { checkImages, checkVideo, formatBytes, mimeOf, uploadAndConfirm } from './uploads';

interface Props {
  returnId: string;
  canCreate: boolean;
  canVoid: boolean;
  onBack: () => void;
  /** DEC-76: open the action sheet (only for users who may see action sheets). */
  onOpenSheet?: ((sheetId: string) => void) | undefined;
}

export const EcommerceReturnDetailPage: React.FC<Props> = ({
  returnId,
  canCreate,
  canVoid,
  onBack,
  onOpenSheet,
}) => {
  const fetcher = useCallback(() => ecomApi.get(returnId), [returnId]);
  const query = useApiQuery<EcomReturn>(fetcher);
  const [viewError, setViewError] = useState<ApiError | null>(null);
  const [voidOpen, setVoidOpen] = useState(false);

  const back = (
    <Button type="button" variant="outline" className="min-h-[44px]" onClick={onBack}>
      <ArrowLeft className="h-4 w-4" aria-hidden="true" /> E-Commerce Returns
    </Button>
  );
  if (query.error) {
    return (
      <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
        {back}
        <ErrorState error={query.error} onRetry={query.reload} title="Could not load the return" />
      </div>
    );
  }
  const r = query.data;
  if (!r) {
    return (
      <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
        <LoadingState label="Loading return…" />
      </div>
    );
  }

  const openFile = async (m: Media) => {
    setViewError(null);
    try {
      const { url } = await ecomApi.downloadUrl(m.id);
      window.open(url, '_blank', 'noopener');
    } catch (err) {
      console.error('Opening the file failed', { mediaId: m.id, err });
      setViewError(toApiError(err));
    }
  };

  const facts: Array<[string, string]> = [
    ['Date', formatDate(r.entry_date)],
    ['Platform', r.platform_label],
    ['Order ID', r.order_id],
    ['Product Type', r.product_type_label],
    r.product_type_code === 'COMPANY_PRODUCT'
      ? ['Product', `${r.product_name ?? ''} (${r.product_code ?? ''})`]
      : ['Different Product', r.different_product_desc ?? ''],
    ['Qty', String(r.qty)],
    ['QC Status', r.qc_routing_label],
    [
      'Recorded',
      `${formatDateTime(r.created_at)}${r.created_by_name ? ` by ${r.created_by_name}` : ''}`,
    ],
  ];
  const live = r.media.filter((m) => m.status !== 'REJECTED');

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6" data-testid="ecom-return-detail">
      {back}
      <PageHeader
        title={r.return_no}
        subtitle={<EcomStatusChip status={r.status} label={r.status_label} />}
        actions={
          <>
            <Button type="button" variant="outline" className="min-h-[44px]" onClick={query.reload}>
              <RefreshCw className="h-4 w-4" aria-hidden="true" /> Refresh
            </Button>
            {canVoid && r.status !== 'CLOSED' && r.status !== 'VOIDED' && r.status !== 'UNBOXED' ? (
              <Button
                type="button"
                variant="danger"
                className="min-h-[44px]"
                onClick={() => {
                  setVoidOpen(true);
                }}
              >
                Void
              </Button>
            ) : null}
          </>
        }
      />

      {r.status === 'VOIDED' ? (
        <p className="rounded-lg border border-slate-300 bg-slate-50 p-3 text-sm dark:border-slate-700 dark:bg-slate-900">
          Voided {formatDateTime(r.voided_at)}: “{r.void_reason}”
        </p>
      ) : null}
      {r.status === 'IN_CHECKING' ? (
        <p className="rounded-lg border border-sky-200 bg-sky-50 p-3 text-sm text-sky-900 dark:border-sky-800 dark:bg-sky-950 dark:text-sky-100">
          Waiting for the E-Commerce Executive to check the portal (Free Replacement / Refund).
        </p>
      ) : null}
      {r.status === 'PENDING_UNBOXING' ? (
        <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100">
          Waiting for the unboxing user.
        </p>
      ) : null}

      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 rounded-xl border border-slate-200 bg-white p-4 sm:grid-cols-2 dark:border-slate-700 dark:bg-slate-900">
        {facts.map(([k, v]) => (
          <div key={k} className="min-w-0">
            <dt className="text-xs text-slate-500">{k}</dt>
            <dd className="m-0 break-words">{v}</dd>
          </div>
        ))}
      </dl>

      {r.status === 'DRAFT' && canCreate ? <FinishDraft ret={r} onChanged={query.setData} /> : null}

      <section className="space-y-2">
        <h2 className="text-base font-semibold">Files</h2>
        {viewError ? <ErrorState error={viewError} title="Could not open the file" /> : null}
        {live.length === 0 ? (
          <p className="text-sm text-slate-500">No file uploaded.</p>
        ) : (
          <ul className="m-0 list-none space-y-2 p-0">
            {live.map((m) => (
              <li
                key={m.id}
                className="flex min-h-[44px] flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-900"
              >
                <span className="min-w-0 flex-1 truncate text-sm">
                  {m.kind === 'PACKAGE_VIDEO' ? 'Package opening video' : 'Image'}
                  {m.file_name ? ` · ${m.file_name}` : ''} · {formatBytes(m.size_bytes)}
                </span>
                {m.status === 'CONFIRMED' ? (
                  <Button
                    type="button"
                    variant="ghost"
                    className="min-h-[44px]"
                    onClick={() => {
                      void openFile(m);
                    }}
                  >
                    <Eye className="h-4 w-4" aria-hidden="true" /> View
                  </Button>
                ) : (
                  <span className="text-sm text-amber-700">Not uploaded</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {r.ticket ? (
        <section className="space-y-2 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="m-0 text-base font-semibold">Platform ticket</h2>
            {r.status !== 'VOIDED' ? <SlaChip ticket={r.ticket} /> : null}
          </div>
          <p className="m-0 text-sm">SLA due {formatDateTime(r.ticket.sla_due_at)}</p>
          {r.ticket.raised_at ? (
            <p className="m-0 text-sm">
              Raised {formatDateTime(r.ticket.raised_at)} by {r.ticket.assigned_handler_name ?? '—'}
            </p>
          ) : (
            <p className="m-0 text-sm text-slate-500">Not raised yet.</p>
          )}
          {r.ticket.response_label ? (
            <p className="m-0 text-sm">
              Response: <strong>{r.ticket.response_label}</strong>
              {r.ticket.rejection_remark ? ` · “${r.ticket.rejection_remark}”` : ''}
              {r.ticket.claim_amount ? ` · Claim ₹${r.ticket.claim_amount}` : ''}
            </p>
          ) : null}
          {r.ticket.closed_at ? (
            <p className="m-0 text-sm">
              Closed {formatDateTime(r.ticket.closed_at)} by {r.ticket.closed_by_name ?? '—'}
            </p>
          ) : null}
        </section>
      ) : null}

      {r.resolution_code ? (
        <section
          className="space-y-1 rounded-xl border border-slate-200 bg-white p-4 text-sm dark:border-slate-700 dark:bg-slate-900"
          data-testid="ecom-resolution"
        >
          <h2 className="m-0 text-base font-semibold">Portal resolution</h2>
          <p className="m-0">
            <strong>{r.resolution_label}</strong> · Qty {r.resolution_qty}
            {r.resolution_note ? ` · “${r.resolution_note}”` : ''}
          </p>
          <p className="m-0 text-xs text-slate-500">
            {formatDateTime(r.resolved_at)}
            {r.resolved_by_name ? ` by ${r.resolved_by_name}` : ''}
          </p>
        </section>
      ) : null}

      {r.settlement ? (
        <section
          className="space-y-2 rounded-xl border border-slate-200 bg-white p-4 text-sm dark:border-slate-700 dark:bg-slate-900"
          data-testid="ecom-settlement"
        >
          <h2 className="m-0 text-base font-semibold">Unboxing and settlement</h2>
          <p className="m-0">
            Action sheet{' '}
            {onOpenSheet ? (
              <button
                type="button"
                className="min-h-[44px] border-0 bg-transparent p-0 font-semibold text-indigo-700 underline dark:text-indigo-300"
                onClick={() => {
                  onOpenSheet(r.settlement?.action_sheet_id ?? '');
                }}
              >
                {r.settlement.sheet_no}
              </button>
            ) : (
              <strong>{r.settlement.sheet_no}</strong>
            )}{' '}
            · {r.settlement.sheet_status === 'COMPLETED' ? 'completed' : 'pending with Accounts'} ·
            Qty Issue CN {r.settlement.cn_qty}
          </p>
          <p className="m-0">
            Store {r.settlement.good_qty} · Repair {r.settlement.repair_qty}
            {r.settlement.repair_location_name ? ` (${r.settlement.repair_location_name})` : ''} ·
            Wastage {r.settlement.wastage_qty}
            {r.settlement.unbox_note ? ` · “${r.settlement.unbox_note}”` : ''}
          </p>
          <p className="m-0 text-xs text-slate-500">
            Unboxed {formatDateTime(r.settlement.unboxed_at)}
            {r.settlement.unboxed_by_name ? ` by ${r.settlement.unboxed_by_name}` : ''}
          </p>
          {r.settlement.repair ? (
            <p className="m-0">
              Repair:{' '}
              {r.settlement.repair.status === 'RETURNED'
                ? `back ${formatDateTime(r.settlement.repair.returned_at)} · OK ${String(r.settlement.repair.qty_ok ?? 0)} · scrap ${String(r.settlement.repair.qty_scrap ?? 0)}`
                : `${String(r.settlement.repair.qty_sent)} pc(s) at ${r.settlement.repair.location_name}`}
            </p>
          ) : null}
          {r.settlement.receipts.map((x) => (
            <p key={x.id} className="m-0">
              {x.source === 'REPAIR' ? 'Repaired' : 'Good'} {x.qty} pc(s) → {x.store_name}:{' '}
              {x.status === 'ACKNOWLEDGED'
                ? `received ${formatDateTime(x.acknowledged_at)}${x.acknowledged_by_name ? ` by ${x.acknowledged_by_name}` : ''}`
                : 'waiting for the store'}
            </p>
          ))}
        </section>
      ) : null}

      <section className="space-y-2">
        <h2 className="text-base font-semibold">History</h2>
        <ol className="m-0 list-none space-y-1 p-0 text-sm">
          {r.events.map((e, i) => (
            <li key={`${e.created_at}-${String(i)}`} className="break-words">
              <span className="text-slate-500">{formatDateTime(e.created_at)}</span> ·{' '}
              {e.event_code.replace(/_/g, ' ').toLowerCase()}
              {e.actor_name ? ` · ${e.actor_name}` : ''}
            </li>
          ))}
        </ol>
      </section>

      <VoidModal
        open={voidOpen}
        ret={r}
        onClose={() => {
          setVoidOpen(false);
        }}
        onDone={(updated) => {
          setVoidOpen(false);
          query.setData(updated);
        }}
      />
    </div>
  );
};

function VoidModal({
  open,
  ret,
  onClose,
  onDone,
}: {
  open: boolean;
  ret: EcomReturn;
  onClose: () => void;
  onDone: (r: EcomReturn) => void;
}) {
  const [reason, setReason] = useState('');
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const key = useRef(newIdempotencyKey());
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      onDone(await ecomApi.void(ret.id, reason.trim(), key.current));
    } catch (err) {
      console.error('Void failed', { returnId: ret.id, err });
      setError(toApiError(err));
      key.current = newIdempotencyKey();
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title={`Void ${ret.return_no}`}
      footer={
        <>
          <Button type="button" variant="outline" className="min-h-[44px]" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="danger"
            className="min-h-[44px]"
            disabled={busy || reason.trim().length < 3}
            onClick={() => {
              void save();
            }}
          >
            Void
          </Button>
        </>
      }
    >
      <label htmlFor="ecom-void-reason" className="form-control__label">
        Reason <span className="text-red-600">*</span>
      </label>
      <Textarea
        id="ecom-void-reason"
        rows={3}
        maxLength={500}
        value={reason}
        onChange={(e) => {
          setReason(e.target.value);
        }}
      />
      {error ? <ErrorState error={error} title="Could not void" /> : null}
    </Modal>
  );
}

/** Finish a DRAFT: upload the files that are still waiting (pick them again), or add a new video,
 * then submit. */
function FinishDraft({ ret, onChanged }: { ret: EcomReturn; onChanged: (r: EcomReturn) => void }) {
  const cfgFetcher = useCallback(() => ecomApi.formConfig(), []);
  const cfg = useApiQuery<FormConfig>(cfgFetcher);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ErrorLike | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const submitKey = useRef(newIdempotencyKey());

  const reload = async () => {
    onChanged(await ecomApi.get(ret.id));
  };
  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
      await reload();
    } catch (err) {
      console.error('Finishing the e-commerce return failed', { returnId: ret.id, err });
      setError(toApiError(err));
    } finally {
      setBusy(false);
      setProgress(null);
    }
  };
  const pickAndUpload = (kind: MediaKind, pending: Media | null) => {
    const input = document.createElement('input');
    input.type = 'file';
    if (cfg.data) {
      const rule = kind === 'PACKAGE_VIDEO' ? cfg.data.video : cfg.data.images;
      input.accept = [...rule.mime_types, ...rule.extensions.map((e) => `.${e}`)].join(',');
    }
    input.onchange = () => {
      const file = input.files?.[0];
      if (!file || !cfg.data) return;
      const c = cfg.data;
      const problem = kind === 'PACKAGE_VIDEO' ? checkVideo(file, c) : checkImages([file], c);
      if (problem) {
        setError({ message: problem });
        return;
      }
      void run(async () => {
        const rule = kind === 'PACKAGE_VIDEO' ? c.video : c.images;
        const meta = { mime_type: mimeOf(file, rule), size_bytes: file.size, file_name: file.name };
        // The same file again for a waiting row (same size and type), otherwise a new row.
        const sameFile =
          pending !== null &&
          pending.size_bytes === file.size &&
          pending.mime_type === meta.mime_type;
        if (pending && !sameFile) await ecomApi.discard(ret.id, pending.id);
        const ticket = sameFile
          ? await ecomApi.uploadUrl(ret.id, pending.id)
          : await ecomApi.addMedia(ret.id, kind, meta);
        await uploadAndConfirm(ret.id, ticket, file, setProgress);
      });
    };
    input.click();
  };

  const pending = ret.media.filter((m) => m.status === 'PENDING_UPLOAD');
  const hasVideo = ret.media.some((m) => m.kind === 'PACKAGE_VIDEO' && m.status === 'CONFIRMED');
  const videoRow = ret.media.find((m) => m.kind === 'PACKAGE_VIDEO' && m.status !== 'REJECTED');

  return (
    <section
      className="space-y-3 rounded-xl border border-amber-300 bg-amber-50 p-4 dark:border-amber-700 dark:bg-amber-950"
      data-testid="ecom-finish-draft"
    >
      <h2 className="m-0 text-base font-semibold">Finish this return</h2>
      <p className="m-0 text-sm">
        The return was recorded but not submitted. Upload the package opening video (and any waiting
        image), then submit.
      </p>
      {cfg.error ? <ErrorState error={cfg.error} onRetry={cfg.reload} /> : null}
      <ul className="m-0 list-none space-y-2 p-0">
        {pending.map((m) => (
          <li key={m.id} className="flex flex-wrap items-center gap-2 text-sm">
            <span className="min-w-0 flex-1 truncate">
              {m.kind === 'PACKAGE_VIDEO' ? 'Video' : 'Image'} waiting: {m.file_name ?? ''} (
              {formatBytes(m.size_bytes)})
            </span>
            <Button
              type="button"
              variant="outline"
              className="min-h-[44px]"
              disabled={busy || !cfg.data}
              onClick={() => {
                pickAndUpload(m.kind, m);
              }}
            >
              <Upload className="h-4 w-4" aria-hidden="true" /> Choose file
            </Button>
            {m.kind === 'IMAGE' ? (
              <Button
                type="button"
                variant="ghost"
                className="min-h-[44px]"
                disabled={busy}
                onClick={() => {
                  void run(async () => {
                    await ecomApi.discard(ret.id, m.id);
                  });
                }}
              >
                <Trash2 className="h-4 w-4" aria-hidden="true" /> Remove
              </Button>
            ) : null}
          </li>
        ))}
      </ul>
      {!videoRow ? (
        <Button
          type="button"
          variant="outline"
          className="min-h-[44px]"
          disabled={busy || !cfg.data}
          onClick={() => {
            pickAndUpload('PACKAGE_VIDEO', null);
          }}
        >
          <Upload className="h-4 w-4" aria-hidden="true" /> Choose video from gallery / files
        </Button>
      ) : null}
      {progress !== null ? <p className="m-0 text-sm">Uploading… {progress}%</p> : null}
      {error ? <ErrorState error={error} title="Could not finish" /> : null}
      <Button
        type="button"
        className="min-h-[44px] w-full"
        disabled={busy || !hasVideo || pending.length > 0}
        onClick={() => {
          void run(async () => {
            await ecomApi.submit(ret.id, submitKey.current);
          });
        }}
      >
        Submit
      </Button>
    </section>
  );
}
