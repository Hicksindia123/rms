/**
 * DEC-73: Gate Entry for an E-Commerce Return (Return Type = E-Commerce). Labels, options, date
 * limits and file limits come from GET /ecommerce-returns/form-config; the server re-checks
 * everything. Flow: record (DRAFT, number) → upload each file to its signed URL and confirm →
 * submit (QC status decides: ticket queued with its SLA, or In Checking).
 */
import React, { useCallback, useMemo, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, RefreshCw, Trash2 } from 'lucide-react';

import { PageHeader } from '@/components/erp';
import {
  AsyncCombobox,
  Button,
  ErrorState,
  Input,
  LoadingState,
  RadioGroup,
  Select,
  Textarea,
} from '@/components/ui';
import type { ComboboxOption } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { newIdempotencyKey, toApiError, type ApiError } from '@/lib/api/client';
import { formatDate, formatDateTime } from '@/features/goods-slips/format';
import '@/features/goods-slips/gateForm.css';

import { ecomApi } from './api';
import { MediaPicker } from './MediaPicker';
import { EcomStatusChip } from './SlaChip';
import {
  ECOMMERCE_RETURN,
  OFFLINE_RETURN,
  type CreatePayload,
  type EcomReturn,
  type FormConfig,
  type MediaUpload,
  type OrderMatch,
  type ProductTypeCode,
  type QcRoutingCode,
} from './types';
import { checkImages, checkVideo, formatBytes, mimeOf, uploadAndConfirm } from './uploads';

interface Props {
  /** Switch to the offline gate form; omitted when the user cannot record offline returns. */
  onOffline?: (() => void) | undefined;
  onOpen: (id: string) => void;
}

type Errors = Record<string, string>;

interface UploadItem {
  ticket: MediaUpload;
  file: File;
  state: 'waiting' | 'uploading' | 'done' | 'failed' | 'removed';
  percent: number;
  error: string | null;
}

interface Draft {
  ret: EcomReturn;
  items: UploadItem[];
}

const PAGE_TITLE = 'E-Commerce Gate Entry';

async function retryTicket(returnId: string, it: UploadItem): Promise<MediaUpload> {
  try {
    return await ecomApi.uploadUrl(returnId, it.ticket.media.id);
  } catch (err) {
    if (toApiError(err).code !== 'MEDIA_NOT_PENDING') throw err;
    return ecomApi.addMedia(returnId, it.ticket.media.kind, {
      mime_type: it.ticket.media.mime_type,
      size_bytes: it.file.size,
      file_name: it.file.name,
    });
  }
}

export const EcommerceGateEntryPage: React.FC<Props> = ({ onOffline, onOpen }) => {
  const fetcher = useCallback(() => ecomApi.formConfig(), []);
  const query = useApiQuery<FormConfig>(fetcher);
  const [formKey, setFormKey] = useState(0);
  const [done, setDone] = useState<EcomReturn | null>(null);

  if (query.error) {
    return (
      <div className="page page--narrow">
        <h1 className="page__title">{PAGE_TITLE}</h1>
        <ErrorState error={query.error} onRetry={query.reload} title="Could not load the form" />
      </div>
    );
  }
  if (!query.data) {
    return (
      <div className="page page--narrow">
        <h1 className="page__title">{PAGE_TITLE}</h1>
        <LoadingState label="Loading form…" />
      </div>
    );
  }
  if (done) {
    return (
      <Success
        ret={done}
        onOpen={onOpen}
        onNew={() => {
          setDone(null);
          setFormKey((k) => k + 1);
        }}
      />
    );
  }
  return (
    <div className="page page--narrow" data-testid="ecom-gate-entry">
      <PageHeader title={PAGE_TITLE} subtitle="Gate Inward · E-Commerce Return" />
      <EcomForm key={formKey} cfg={query.data} onOffline={onOffline} onSubmitted={setDone} />
    </div>
  );
};

function EcomForm({
  cfg,
  onOffline,
  onSubmitted,
}: {
  cfg: FormConfig;
  onOffline?: (() => void) | undefined;
  onSubmitted: (r: EcomReturn) => void;
}) {
  const [entryDate, setEntryDate] = useState(cfg.business_today);
  const [platform, setPlatform] = useState('');
  const [orderId, setOrderId] = useState('');
  const [productType, setProductType] = useState<ProductTypeCode | ''>('');
  const [productId, setProductId] = useState('');
  const [differentDesc, setDifferentDesc] = useState('');
  const [qty, setQty] = useState('1');
  const [routing, setRouting] = useState<QcRoutingCode | ''>('');
  const [video, setVideo] = useState<File[]>([]);
  const [images, setImages] = useState<File[]>([]);
  const [errors, setErrors] = useState<Errors>({});
  const [matches, setMatches] = useState<OrderMatch[]>([]);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  // One key per record attempt: a double tap or a retry after a lost response replays it (G-16).
  const createKey = useRef(newIdempotencyKey());
  const submitKey = useRef(newIdempotencyKey());

  const orderPattern = useMemo(() => new RegExp(cfg.order_id_pattern), [cfg.order_id_pattern]);
  const labelOf = (list: { code: string; label: string }[], code: string, fallback: string) =>
    list.find((o) => o.code === code)?.label ?? fallback;
  const videoAccept = [...cfg.video.mime_types, ...cfg.video.extensions.map((e) => `.${e}`)].join(
    ',',
  );
  const imageAccept = [...cfg.images.mime_types, ...cfg.images.extensions.map((e) => `.${e}`)].join(
    ',',
  );
  const loadProducts = useCallback(async (q: string): Promise<ComboboxOption[]> => {
    const rows = await ecomApi.products(q);
    return rows.map((p) => ({ value: p.id, label: p.name, sublabel: p.code }));
  }, []);

  const checkOrder = () => {
    const id = orderId.trim();
    if (!platform || !orderPattern.test(id)) {
      setMatches([]);
      return;
    }
    ecomApi
      .orderCheck(platform, id)
      .then(setMatches)
      .catch((err: unknown) => {
        // A warning only; the server still accepts repeats (DEC-73 Q2). Log and carry on.
        console.error('Order ID check failed', err);
        setMatches([]);
      });
  };

  const validate = (): Errors => {
    const e: Errors = {};
    if (!entryDate) e.entry_date = 'The date is required';
    else if (entryDate > cfg.business_today) e.entry_date = 'The date cannot be later than today';
    else if (cfg.min_entry_date && entryDate < cfg.min_entry_date)
      e.entry_date = `The date can be at most back to ${formatDate(cfg.min_entry_date)}`;
    if (!platform) e.platform_code = 'Choose the platform';
    if (!orderId.trim()) e.order_id = 'The Order ID is required';
    else if (!orderPattern.test(orderId.trim()))
      e.order_id = 'Letters and digits only (a hyphen is allowed), 3 to 40 characters';
    if (!productType) e.product_type_code = 'Choose the product type';
    if (productType === 'COMPANY_PRODUCT' && !productId) e.product_id = 'Choose the product';
    if (productType === 'DIFFERENT_PRODUCT' && differentDesc.trim().length < 3)
      e.different_product_desc = 'Describe the item found in the packet';
    const n = Number(qty);
    if (!Number.isInteger(n) || n < 1) e.qty = 'Enter a whole number, at least 1';
    if (!routing) e.qc_routing_code = 'Choose the QC status';
    const v = checkVideo(video[0] ?? null, cfg);
    if (v) e.video = v;
    const i = checkImages(images, cfg);
    if (i) e.images = i;
    return e;
  };

  const runUploads = async (d: Draft): Promise<Draft> => {
    let items = d.items;
    const update = (index: number, patch: Partial<UploadItem>) => {
      items = items.map((it, j) => (j === index ? { ...it, ...patch } : it));
      setDraft({ ret: d.ret, items });
    };
    for (const [index, it] of items.entries()) {
      if (it.state === 'done' || it.state === 'removed') continue;
      update(index, { state: 'uploading', percent: 0, error: null });
      try {
        // A retry gets a fresh signed URL (the first one may have expired); a file the server
        // rejected (declared size / type did not match) is added again as a new file.
        const ticket = it.state === 'failed' ? await retryTicket(d.ret.id, it) : it.ticket;
        if (ticket !== it.ticket) update(index, { ticket });
        await uploadAndConfirm(d.ret.id, ticket, it.file, (percent) => {
          update(index, { percent });
        });
        update(index, { state: 'done', percent: 100 });
      } catch (err) {
        const apiErr = toApiError(err);
        console.error('E-Commerce file upload failed', {
          returnId: d.ret.id,
          file: it.file.name,
          err,
        });
        update(index, { state: 'failed', error: apiErr.message });
      }
    }
    return { ret: d.ret, items };
  };

  const submitDraft = async (d: Draft) => {
    if (d.items.some((it) => it.state === 'failed' || it.state === 'uploading')) return;
    try {
      const ret = await ecomApi.submit(d.ret.id, submitKey.current);
      onSubmitted(ret);
    } catch (err) {
      const apiErr = toApiError(err);
      console.error('E-Commerce return submit failed', { returnId: d.ret.id, err });
      setFailure(apiErr);
    }
  };

  const onRecord = async () => {
    const e = validate();
    setErrors(e);
    setFailure(null);
    if (Object.keys(e).length > 0) return;
    const videoFile = video[0];
    if (!videoFile) return;
    const payload: CreatePayload = {
      entry_date: entryDate,
      platform_code: platform,
      order_id: orderId.trim(),
      product_type_code: productType as ProductTypeCode,
      // Only the field of the chosen product type is sent.
      product_id: productType === 'COMPANY_PRODUCT' ? productId : null,
      different_product_desc: productType === 'DIFFERENT_PRODUCT' ? differentDesc.trim() : null,
      qty: Number(qty),
      qc_routing_code: routing as QcRoutingCode,
      video: {
        mime_type: mimeOf(videoFile, cfg.video),
        size_bytes: videoFile.size,
        file_name: videoFile.name,
      },
      images: images.map((f) => ({
        mime_type: mimeOf(f, cfg.images),
        size_bytes: f.size,
        file_name: f.name,
      })),
    };
    setBusy(true);
    try {
      const created = await ecomApi.create(payload, createKey.current);
      const files = [videoFile, ...images];
      const items: UploadItem[] = created.uploads.map((ticket, i) => ({
        ticket,
        file: files[i] ?? videoFile,
        state: 'waiting',
        percent: 0,
        error: null,
      }));
      const first: Draft = { ret: created.ecommerce_return, items };
      setDraft(first);
      const after = await runUploads(first);
      await submitDraft(after);
    } catch (err) {
      const apiErr = toApiError(err);
      console.error('E-Commerce return create failed', err);
      const fields = apiErr.fieldErrors;
      if (Object.keys(fields).length > 0) {
        const mapped: Errors = {};
        for (const [k, v] of Object.entries(fields)) {
          mapped[k.startsWith('images') ? 'images' : k] = v.join(' ');
        }
        setErrors(mapped);
      }
      setFailure(apiErr);
      createKey.current = newIdempotencyKey();
    } finally {
      setBusy(false);
    }
  };

  const retry = async () => {
    if (!draft) return;
    setBusy(true);
    setFailure(null);
    try {
      const after = await runUploads(draft);
      await submitDraft(after);
    } finally {
      setBusy(false);
    }
  };

  const removeImage = async (index: number) => {
    if (!draft) return;
    const it = draft.items[index];
    if (!it) return;
    setBusy(true);
    try {
      await ecomApi.discard(draft.ret.id, it.ticket.media.id);
      setDraft({
        ret: draft.ret,
        items: draft.items.map((x, j) => (j === index ? { ...x, state: 'removed' } : x)),
      });
    } catch (err) {
      console.error('Removing the image failed', err);
      setFailure(toApiError(err));
    } finally {
      setBusy(false);
    }
  };

  if (draft) {
    const failed = draft.items.some((it) => it.state === 'failed');
    return (
      <section className="space-y-4" aria-live="polite" data-testid="ecom-uploading">
        <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
          <p className="m-0 text-sm text-slate-600 dark:text-slate-300">Recorded as</p>
          <p className="m-0 text-lg font-semibold">{draft.ret.return_no}</p>
          <p className="m-0 text-sm text-slate-600 dark:text-slate-300">
            Uploading files… keep this page open.
          </p>
        </div>
        <ul className="m-0 list-none space-y-2 p-0">
          {draft.items.map((it, i) => (
            <li
              key={it.ticket.media.id}
              className="flex min-h-[44px] flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-900"
            >
              <span className="min-w-0 flex-1 truncate text-sm">
                {it.ticket.media.kind === 'PACKAGE_VIDEO' ? 'Video: ' : 'Image: '}
                {it.file.name} ({formatBytes(it.file.size)})
              </span>
              <span className="text-sm" data-testid={`upload-state-${String(i)}`}>
                {it.state === 'done' ? (
                  <CheckCircle2 className="inline h-4 w-4 text-green-600" aria-label="Uploaded" />
                ) : it.state === 'failed' ? (
                  <span className="text-red-700">Failed: {it.error}</span>
                ) : it.state === 'removed' ? (
                  'Removed'
                ) : (
                  `${String(it.percent)}%`
                )}
              </span>
              {it.state === 'failed' && it.ticket.media.kind === 'IMAGE' ? (
                <Button
                  type="button"
                  variant="ghost"
                  className="min-h-[44px]"
                  disabled={busy}
                  onClick={() => {
                    void removeImage(i);
                  }}
                >
                  <Trash2 className="h-4 w-4" aria-hidden="true" /> Remove
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
        {failure ? <ErrorState error={failure} title="Could not finish" /> : null}
        {failed || failure ? (
          <Button
            type="button"
            className="min-h-[44px] w-full"
            disabled={busy}
            onClick={() => {
              void retry();
            }}
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" /> Retry
          </Button>
        ) : null}
        <p className="text-xs text-slate-500">
          If you leave now, the return stays “{draft.ret.status_label}” and can be finished from
          E-Commerce Returns.
        </p>
      </section>
    );
  }

  const returnTypes = cfg.return_types.filter(
    (o) => o.code === ECOMMERCE_RETURN || (o.code === OFFLINE_RETURN && onOffline),
  );

  return (
    <form
      className="space-y-5"
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        void onRecord();
      }}
    >
      {returnTypes.length > 1 ? (
        <div className="space-y-2">
          <span className="form-control__label" id="ecom-return-type-label">
            Return Type
          </span>
          <div
            className="gate-return-type"
            role="radiogroup"
            aria-labelledby="ecom-return-type-label"
          >
            {returnTypes.map((o) => (
              <button
                key={o.code}
                type="button"
                role="radio"
                aria-checked={o.code === ECOMMERCE_RETURN}
                data-testid={`return-type-${o.code}`}
                className="gate-return-type__option"
                disabled={busy}
                onClick={() => {
                  if (o.code === OFFLINE_RETURN) onOffline?.();
                }}
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <div>
        <label htmlFor="ecom-entry-date" className="form-control__label">
          Date <span className="text-red-600">*</span>
        </label>
        <Input
          id="ecom-entry-date"
          type="date"
          value={entryDate}
          max={cfg.business_today}
          min={cfg.min_entry_date ?? undefined}
          error={errors.entry_date}
          disabled={busy}
          onChange={(e) => {
            setEntryDate(e.target.value);
          }}
        />
      </div>

      <div>
        <label htmlFor="ecom-platform" className="form-control__label">
          Platform <span className="text-red-600">*</span>
        </label>
        <Select
          id="ecom-platform"
          value={platform}
          placeholder="Choose platform"
          options={cfg.platforms.map((p) => ({ value: p.code, label: p.label }))}
          error={errors.platform_code}
          disabled={busy}
          onChange={(e) => {
            setPlatform(e.target.value);
            setMatches([]);
          }}
        />
      </div>

      <div>
        <label htmlFor="ecom-order-id" className="form-control__label">
          Order ID <span className="text-red-600">*</span>
        </label>
        <Input
          id="ecom-order-id"
          value={orderId}
          maxLength={40}
          autoComplete="off"
          error={errors.order_id}
          disabled={busy}
          onChange={(e) => {
            setOrderId(e.target.value);
          }}
          onBlur={checkOrder}
        />
        {matches.length > 0 ? (
          <div
            className="mt-2 flex gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100"
            role="status"
            data-testid="order-repeat-warning"
          >
            <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span>
              This order already has{' '}
              {matches.length === 1 ? 'a return' : `${String(matches.length)} returns`}:{' '}
              {matches
                .map((m) => `${m.return_no} (${formatDate(m.entry_date)}, ${m.status_label})`)
                .join('; ')}
              . You can still record another one.
            </span>
          </div>
        ) : null}
      </div>

      <div>
        <span className="form-control__label">
          Product Type <span className="text-red-600">*</span>
        </span>
        <RadioGroup
          id="ecom-product-type"
          name="product_type_code"
          value={productType}
          options={cfg.product_types.map((o) => ({ value: o.code, label: o.label }))}
          error={errors.product_type_code}
          disabled={busy}
          onChange={(v) => {
            setProductType(v as ProductTypeCode);
          }}
        />
      </div>

      {productType === 'COMPANY_PRODUCT' ? (
        <div>
          <span className="form-control__label">
            {labelOf(cfg.product_types, 'COMPANY_PRODUCT', 'Product')}{' '}
            <span className="text-red-600">*</span>
          </span>
          <AsyncCombobox
            id="ecom-product"
            name="product_id"
            ariaLabel="Product"
            placeholder="Type product name or code"
            value={productId}
            loadOptions={loadProducts}
            error={errors.product_id}
            disabled={busy}
            onChange={setProductId}
          />
        </div>
      ) : null}
      {productType === 'DIFFERENT_PRODUCT' ? (
        <div>
          <label htmlFor="ecom-different-desc" className="form-control__label">
            Different Product Description <span className="text-red-600">*</span>
          </label>
          <Textarea
            id="ecom-different-desc"
            rows={2}
            maxLength={500}
            value={differentDesc}
            placeholder="What was found in the packet"
            error={errors.different_product_desc}
            disabled={busy}
            onChange={(e) => {
              setDifferentDesc(e.target.value);
            }}
          />
        </div>
      ) : null}

      <div>
        <label htmlFor="ecom-qty" className="form-control__label">
          Qty <span className="text-red-600">*</span>
        </label>
        <Input
          id="ecom-qty"
          type="number"
          inputMode="numeric"
          min={1}
          step={1}
          value={qty}
          error={errors.qty}
          disabled={busy}
          onChange={(e) => {
            setQty(e.target.value);
          }}
        />
      </div>

      <div>
        <span className="form-control__label">
          QC Status <span className="text-red-600">*</span>
        </span>
        <RadioGroup
          id="ecom-qc-routing"
          name="qc_routing_code"
          value={routing}
          options={cfg.qc_routings.map((o) => ({ value: o.code, label: o.label }))}
          error={errors.qc_routing_code}
          helperText={
            routing === 'TICKET_RAISE'
              ? `A Ticket Handler must raise the platform ticket within ${String(cfg.ticket_sla_hours)} hours.`
              : undefined
          }
          disabled={busy}
          onChange={(v) => {
            setRouting(v as QcRoutingCode);
          }}
        />
      </div>

      <MediaPicker
        id="ecom-video"
        label="Package Opening Video"
        required
        kind="video"
        accept={videoAccept}
        files={video}
        onChange={setVideo}
        error={errors.video}
        helper={`One video from the gallery or files (${cfg.video.extensions.map((e) => `.${e}`).join(', ')}), up to ${formatBytes(cfg.video.max_bytes)}.`}
        disabled={busy}
      />
      <MediaPicker
        id="ecom-images"
        label="Images (optional)"
        kind="image"
        multiple
        accept={imageAccept}
        files={images}
        onChange={setImages}
        error={errors.images}
        helper={`Up to ${formatBytes(cfg.images.max_total_bytes)} together.`}
        disabled={busy}
      />

      {failure && Object.keys(failure.fieldErrors).length === 0 ? (
        <ErrorState error={failure} title="Could not record the return" />
      ) : null}

      <Button
        type="submit"
        className="min-h-[44px] w-full"
        disabled={busy}
        data-testid="ecom-record"
      >
        {busy ? 'Recording…' : 'Record E-Commerce Return'}
      </Button>
    </form>
  );
}

function Success({
  ret,
  onOpen,
  onNew,
}: {
  ret: EcomReturn;
  onOpen: (id: string) => void;
  onNew: () => void;
}) {
  return (
    <div className="page page--narrow space-y-4" data-testid="ecom-success">
      <PageHeader title="E-Commerce Return recorded" />
      <div className="space-y-2 rounded-xl border border-green-200 bg-green-50 p-4 dark:border-green-800 dark:bg-green-950">
        <p className="m-0 flex items-center gap-2 text-lg font-semibold">
          <CheckCircle2 className="h-5 w-5 text-green-600" aria-hidden="true" />
          {ret.return_no}
        </p>
        <p className="m-0 text-sm">
          {ret.platform_label} · Order {ret.order_id} · Qty {ret.qty}
        </p>
        <p className="m-0">
          <EcomStatusChip status={ret.status} label={ret.status_label} />
        </p>
        {ret.ticket ? (
          <p className="m-0 text-sm">
            Ticket queued for the Ticket Handlers, due by {formatDateTime(ret.ticket.sla_due_at)}.
          </p>
        ) : (
          <p className="m-0 text-sm">{ret.qc_routing_label}: the return stays open.</p>
        )}
      </div>
      <div className="flex flex-col gap-2 sm:flex-row">
        <Button
          type="button"
          variant="outline"
          className="min-h-[44px]"
          onClick={() => {
            onOpen(ret.id);
          }}
        >
          Open return
        </Button>
        <Button type="button" className="min-h-[44px]" onClick={onNew}>
          Record another
        </Button>
      </div>
    </div>
  );
}
