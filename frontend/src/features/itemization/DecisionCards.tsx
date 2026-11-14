import { useRef, useState } from 'react';
import { Check, X } from 'lucide-react';

import { Badge, Button, Textarea } from '@/components/ui';
import { formatDateTime } from '@/features/goods-slips/format';
import type { Attachment } from '@/features/unboxing/api';
import { AttachmentThumb, VideoPlayer } from '@/features/unboxing/SignedMedia';
import { toApiError, type ApiError } from '@/lib/api/client';

import {
  itemizationApi,
  newIdempotencyKey,
  type ItemizationGs,
  type ItemLine,
  type LineCorrection,
  type StepOption,
  type Totals,
} from './api';

const APPROVE = 'CSR_APPROVED';
const REJECT = 'CSR_REJECTED_TO_RO';

/** Evidence strip: video player + document / parcel photo thumbnails. */
export function EvidenceStrip({ evidence, gsNo }: { evidence: Attachment[]; gsNo: string }) {
  const videos = evidence.filter((a) => a.kind === 'UNBOXING_VIDEO');
  const photos = evidence.filter((a) => a.kind !== 'UNBOXING_VIDEO');
  if (evidence.length === 0) return null;
  return (
    <div className="evidence-strip">
      {photos.length > 0 ? (
        <div className="evidence-grid">
          {photos.map((p, i) => (
            <AttachmentThumb key={p.id} attachment={p} alt={`${gsNo} photo ${String(i + 1)}`} />
          ))}
        </div>
      ) : null}
      {videos.map((v) => (
        <VideoPlayer key={v.id} attachment={v} />
      ))}
    </div>
  );
}

/** Compact line summary for phones: product, document vs received, short / excess. */
export function LineSummary({ items, totals }: { items: ItemLine[]; totals: Totals }) {
  return (
    <div className="line-summary">
      <ul>
        {items.map((i) => (
          <li key={i.id}>
            <span className="line-summary__name">
              #{i.line_no} {i.product_name ?? i.product_code}
            </span>
            <span className="line-summary__qty">
              {i.received_qty}/{i.documented_qty}
              {i.short_qty > 0 ? (
                <Badge variant={i.is_short ? 'warning' : 'neutral'}>−{i.short_qty}</Badge>
              ) : null}
              {i.excess_qty > 0 ? <Badge variant="info">+{i.excess_qty}</Badge> : null}
            </span>
          </li>
        ))}
      </ul>
      <p className="line-summary__total">
        {totals.lines} line(s) · received {totals.received_qty} of {totals.documented_qty} as per
        document
      </p>
    </div>
  );
}

/** G-03: the Replacement Manager approves or rejects (reason required) a Complete Sales Return. */
export function CsrDecisionCard({
  goodsSlip,
  items,
  totals,
  categoryLabel,
  categorizedBy,
  evidence,
  options,
  onDecided,
  onOpenGs,
}: {
  goodsSlip: ItemizationGs;
  items: ItemLine[];
  totals: Totals;
  categoryLabel: string | null;
  categorizedBy?: string | null | undefined;
  evidence: Attachment[];
  options: StepOption[];
  onDecided: () => void;
  onOpenGs?: ((gsId: string) => void) | undefined;
}) {
  const [remarks, setRemarks] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  // One key per decision intent, reused if the same decision is retried after a network failure.
  const keys = useRef(new Map<string, string>());
  const approve = options.find((o) => o.code === APPROVE);
  const reject = options.find((o) => o.code === REJECT);

  const decide = async (code: string) => {
    setBusy(code);
    setError(null);
    let key = keys.current.get(code);
    if (!key) {
      key = newIdempotencyKey();
      keys.current.set(code, key);
    }
    try {
      await itemizationApi.decide(goodsSlip.id, code, remarks.trim(), key);
      onDecided();
    } catch (err) {
      const apiError = toApiError(err);
      if (apiError.status >= 400 && apiError.status < 500) keys.current.delete(code);
      setError(apiError);
    } finally {
      setBusy(null);
    }
  };

  return (
    <article className="card approval-card" data-testid="csr-card">
      <div className="approval-card__head" style={{ justifyContent: 'space-between' }}>
        <div style={{ minWidth: 0 }}>
          <p style={{ margin: 0, fontWeight: 700, wordBreak: 'break-all' }}>
            {onOpenGs ? (
              <button
                type="button"
                className="dataview__link"
                onClick={() => {
                  onOpenGs(goodsSlip.id);
                }}
              >
                {goodsSlip.gs_no}
              </button>
            ) : (
              goodsSlip.gs_no
            )}
          </p>
          {goodsSlip.party_name ? (
            <p className="page__subtitle" style={{ margin: 0 }}>
              {goodsSlip.party_name}
              {goodsSlip.station_name ? ` · ${goodsSlip.station_name}` : ''}
            </p>
          ) : null}
          <p style={{ margin: '0.25rem 0 0', fontSize: '0.8125rem', color: 'var(--color-muted)' }}>
            {categorizedBy ?? ''}
            {goodsSlip.categorized_at ? ` · ${formatDateTime(goodsSlip.categorized_at)}` : ''}
          </p>
        </div>
        {categoryLabel ? <Badge variant="warning">{categoryLabel}</Badge> : null}
      </div>
      <LineSummary items={items} totals={totals} />
      <EvidenceStrip evidence={evidence} gsNo={goodsSlip.gs_no} />
      <label className="form-label" htmlFor={`csr-remarks-${goodsSlip.id}`}>
        Remarks (required to reject)
      </label>
      <Textarea
        id={`csr-remarks-${goodsSlip.id}`}
        rows={2}
        value={remarks}
        onChange={(e) => {
          setRemarks(e.target.value);
        }}
      />
      {error ? (
        <p role="alert" className="form-control__error">
          {error.message}
          {error.requestId ? ` (Request ID: ${error.requestId})` : ''}
        </p>
      ) : null}
      <div className="approval-card__actions">
        {reject ? (
          <Button
            type="button"
            variant="danger"
            isLoading={busy === REJECT}
            disabled={busy !== null || remarks.trim().length === 0}
            title={reject.rule_text ?? undefined}
            onClick={() => {
              void decide(REJECT);
            }}
          >
            <X size={16} aria-hidden="true" /> {reject.label}
          </Button>
        ) : null}
        {approve ? (
          <Button
            type="button"
            variant="primary"
            isLoading={busy === APPROVE}
            disabled={busy !== null}
            title={approve.rule_text ?? undefined}
            onClick={() => {
              void decide(APPROVE);
            }}
          >
            <Check size={16} aria-hidden="true" /> {approve.label}
          </Button>
        ) : null}
      </div>
    </article>
  );
}

/** RM decision on a post-categorisation line correction (stock is adjusted on approval). */
export function CorrectionDecisionCard({
  correction,
  onDecided,
  onOpenGs,
}: {
  correction: LineCorrection;
  onDecided: () => void;
  onOpenGs?: ((gsId: string) => void) | undefined;
}) {
  const [remarks, setRemarks] = useState('');
  const [busy, setBusy] = useState<'APPROVE' | 'REJECT' | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const keys = useRef(new Map<string, string>());

  const decide = async (decision: 'APPROVE' | 'REJECT') => {
    setBusy(decision);
    setError(null);
    let key = keys.current.get(decision);
    if (!key) {
      key = newIdempotencyKey();
      keys.current.set(decision, key);
    }
    try {
      await itemizationApi.decideCorrection(
        correction.gs_id,
        correction.id,
        decision,
        remarks.trim(),
        key,
      );
      onDecided();
    } catch (err) {
      const apiError = toApiError(err);
      if (apiError.status >= 400 && apiError.status < 500) keys.current.delete(decision);
      setError(apiError);
    } finally {
      setBusy(null);
    }
  };

  return (
    <article className="card approval-card" data-testid="correction-card">
      <p style={{ margin: 0, fontWeight: 700, wordBreak: 'break-all' }}>
        {onOpenGs ? (
          <button
            type="button"
            className="dataview__link"
            onClick={() => {
              onOpenGs(correction.gs_id);
            }}
          >
            {correction.gs_no}
          </button>
        ) : (
          correction.gs_no
        )}{' '}
        · line {correction.line_no} {correction.product_name ?? ''}
      </p>
      <p style={{ margin: '0.5rem 0' }}>
        As per document {correction.old_documented_qty} → {correction.new_documented_qty} ·
        Physically received {correction.old_received_qty} → {correction.new_received_qty}
      </p>
      <p style={{ margin: '0 0 0.5rem', whiteSpace: 'pre-wrap' }}>“{correction.reason}”</p>
      <p style={{ margin: '0 0 0.5rem', fontSize: '0.8125rem', color: 'var(--color-muted)' }}>
        {correction.requested_by_name ?? ''} · {formatDateTime(correction.requested_at)}
      </p>
      <label className="form-label" htmlFor={`corr-remarks-${correction.id}`}>
        Remarks (required to reject)
      </label>
      <Textarea
        id={`corr-remarks-${correction.id}`}
        rows={2}
        value={remarks}
        onChange={(e) => {
          setRemarks(e.target.value);
        }}
      />
      {error ? (
        <p role="alert" className="form-control__error">
          {error.message}
          {error.requestId ? ` (Request ID: ${error.requestId})` : ''}
        </p>
      ) : null}
      <div className="approval-card__actions">
        <Button
          type="button"
          variant="danger"
          isLoading={busy === 'REJECT'}
          disabled={busy !== null || remarks.trim().length === 0}
          onClick={() => {
            void decide('REJECT');
          }}
        >
          <X size={16} aria-hidden="true" /> Reject correction
        </Button>
        <Button
          type="button"
          variant="primary"
          isLoading={busy === 'APPROVE'}
          disabled={busy !== null}
          onClick={() => {
            void decide('APPROVE');
          }}
        >
          <Check size={16} aria-hidden="true" /> Approve correction
        </Button>
      </div>
    </article>
  );
}
