import { useCallback, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, PackageCheck, Send } from 'lucide-react';

import { Badge, Button, ErrorState, LoadingState, Textarea } from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError, type ApiError } from '@/lib/api/client';

import {
  itemizationApi,
  newIdempotencyKey,
  type CategorisationStateOut,
  type ItemCategorisationDetail,
} from './api';

interface Props {
  gsId: string;
  onDone: () => void;
}

type Edits = Record<string, Record<string, number>>; // item_id -> field_code -> unsaved qty

/** Saved bucket quantities of one item: every allowed bucket (0 when not saved yet). */
function savedBuckets(item: ItemCategorisationDetail): Record<string, number> {
  const out: Record<string, number> = {};
  for (const b of item.allowed_buckets) {
    out[b.field_code] = item.buckets.find((x) => x.field_code === b.field_code)?.qty ?? 0;
  }
  return out;
}

/** Saved auxiliary counts of one item (AMD-11): every allowed count (0 when not saved yet). */
function savedCounts(item: ItemCategorisationDetail): Record<string, number> {
  const out: Record<string, number> = {};
  for (const c of item.allowed_counts) {
    out[c.field_code] = item.counts.find((x) => x.count_type === c.field_code)?.count_value ?? 0;
  }
  return out;
}

/** Drop the item's edits that equal the saved values; keep anything typed after the save started. */
function withoutSaved(edits: Edits, itemId: string, saved: Record<string, number>): Edits {
  const remaining = Object.fromEntries(
    Object.entries(edits[itemId] ?? {}).filter(([code, qty]) => saved[code] !== qty),
  );
  const rest = Object.fromEntries(Object.entries(edits).filter(([id]) => id !== itemId));
  return Object.keys(remaining).length ? { ...rest, [itemId]: remaining } : rest;
}

export function ItemCategorisationSection({ gsId, onDone }: Props) {
  // Validated against the backend contract (INVALID_API_RESPONSE on a mismatch, never a crash).
  const fetcher = useCallback(async () => itemizationApi.getCategorisation(gsId), [gsId]);
  const query = useApiQuery<CategorisationStateOut>(fetcher);
  const data = query.data?.goods_slip_id === gsId ? query.data : null;

  // Unsaved edits only; the displayed value is edit ?? saved, so fresh server data needs no sync.
  const [draftBuckets, setDraftBuckets] = useState<Edits>({});
  const [draftCounts, setDraftCounts] = useState<Edits>({});
  const [savingItem, setSavingItem] = useState<string | null>(null);
  const [itemError, setItemError] = useState<{ id: string; error: ApiError } | null>(null);

  const [remarks, setRemarks] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<ApiError | null>(null);

  // Idempotency-Key per save intent: reused only when the same payload is retried after a
  // network/server failure (G-16), replaced after a success or a 4xx.
  const saveKeys = useRef(new Map<string, { body: string; key: string }>());
  const submitKey = useRef<{ body: string; key: string } | null>(null);

  if (!data && query.error) {
    return (
      <ErrorState
        title="Item categorisation could not be loaded"
        error={query.error}
        onRetry={query.reload}
      />
    );
  }
  if (!data) return <LoadingState />;

  const bucketsOf = (item: ItemCategorisationDetail) => ({
    ...savedBuckets(item),
    ...(draftBuckets[item.item_id] ?? {}),
  });
  const countsOf = (item: ItemCategorisationDetail) => ({
    ...savedCounts(item),
    ...(draftCounts[item.item_id] ?? {}),
  });

  const handleBucketChange = (itemId: string, fieldCode: string, val: number) => {
    setDraftBuckets((prev) => ({
      ...prev,
      [itemId]: { ...(prev[itemId] ?? {}), [fieldCode]: Math.max(0, val) },
    }));
  };

  const handleCountChange = (itemId: string, fieldCode: string, val: number) => {
    setDraftCounts((prev) => ({
      ...prev,
      [itemId]: { ...(prev[itemId] ?? {}), [fieldCode]: Math.max(0, val) },
    }));
  };

  const saveLine = async (item: ItemCategorisationDetail) => {
    const itemId = item.item_id;
    try {
      setSavingItem(itemId);
      setItemError(null);
      const bMap = bucketsOf(item);
      const cMap = countsOf(item);

      const body = {
        buckets: item.allowed_buckets.map((b) => ({
          field_code: b.field_code,
          qty: bMap[b.field_code] ?? 0,
        })),
        counts: item.allowed_counts.map((c) => ({
          count_type: c.field_code,
          count_value: cMap[c.field_code] ?? 0,
        })),
      };
      const bodyJson = JSON.stringify(body);
      const prior = saveKeys.current.get(itemId);
      const key = prior?.body === bodyJson ? prior.key : newIdempotencyKey();
      saveKeys.current.set(itemId, { body: bodyJson, key });

      await itemizationApi.saveItemCategorisation(gsId, itemId, body, key);
      saveKeys.current.delete(itemId);

      // The save returns {item_id, status}; re-read the server state (conservation is computed
      // there) and drop only the edits that were saved; other lines and values typed meanwhile
      // are kept.
      const sentBuckets = Object.fromEntries(body.buckets.map((b) => [b.field_code, b.qty]));
      const sentCounts = Object.fromEntries(body.counts.map((c) => [c.count_type, c.count_value]));
      query.setData(await itemizationApi.getCategorisation(gsId));
      setDraftBuckets((prev) => withoutSaved(prev, itemId, sentBuckets));
      setDraftCounts((prev) => withoutSaved(prev, itemId, sentCounts));
    } catch (err) {
      const apiError = toApiError(err);
      if (apiError.status >= 400 && apiError.status < 500) saveKeys.current.delete(itemId);
      setItemError({ id: itemId, error: apiError });
    } finally {
      setSavingItem(null);
    }
  };

  const handleSubmit = async () => {
    try {
      setSubmitting(true);
      setSubmitError(null);
      const body = { category_code: 'REGULAR_RETURN', remarks: remarks.trim() || null };
      const bodyJson = JSON.stringify(body);
      if (submitKey.current?.body !== bodyJson) {
        submitKey.current = { body: bodyJson, key: newIdempotencyKey() };
      }
      await itemizationApi.submitCategorisation(gsId, body, submitKey.current.key);
      submitKey.current = null;
      onDone();
    } catch (err) {
      const apiError = toApiError(err);
      if (apiError.status >= 400 && apiError.status < 500) submitKey.current = null;
      setSubmitError(apiError);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="card unboxing__section" aria-labelledby="cat-heading" style={{ marginTop: '1.5rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
        <div>
          <h2 id="cat-heading" className="unboxing__h2" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <PackageCheck size={20} color="var(--color-primary)" />
            Item Categorisation (AMD-09)
          </h2>
          <p className="page__subtitle" style={{ margin: 0 }}>
            Distribute counted items across condition buckets. Guard G-19 requires sum of buckets = counted quantity.
          </p>
        </div>
        {data.all_conserved ? (
          <Badge variant="success">G-19 Conserved: All items match counted quantity</Badge>
        ) : (
          <Badge variant="warning">G-19 Conservation Pending</Badge>
        )}
      </div>

      {/* DEC-51: any eligible inward verifier may categorise, whoever counted. */}

      {/* Item Lines */}
      <div style={{ marginTop: '1.25rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {data.items.map((item) => {
          const bMap = bucketsOf(item);
          const cMap = countsOf(item);
          const currentTotal = Object.values(bMap).reduce((a, b) => a + b, 0);
          const isLocallyConserved = currentTotal === item.received_qty;
          const diff = currentTotal - item.received_qty;
          const isSaving = savingItem === item.item_id;
          const err = itemError?.id === item.item_id ? itemError.error : null;

          return (
            <div
              key={item.item_id}
              style={{
                border: '1px solid var(--color-border)',
                borderRadius: '8px',
                padding: '1rem',
                backgroundColor: 'var(--color-bg-card, #ffffff)',
              }}
            >
              {/* Line Header */}
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'flex-start',
                  flexWrap: 'wrap',
                  gap: '0.5rem',
                  borderBottom: '1px solid var(--color-border)',
                  paddingBottom: '0.75rem',
                  marginBottom: '0.75rem',
                }}
              >
                <div>
                  <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>
                    Line {item.line_no}: {item.sku_name || 'Unnamed Product'}
                  </div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--color-muted)' }}>
                    SKU: {item.sku_code || 'N/A'} &bull; Category: {item.category_name || 'N/A'}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: '0.85rem' }}>
                    Documented: <strong>{item.documented_qty}</strong>
                  </span>
                  <span style={{ fontSize: '0.85rem' }}>
                    Counted: <strong>{item.received_qty}</strong>
                  </span>
                  {isLocallyConserved ? (
                    <Badge variant="success">
                      <CheckCircle2 size={12} style={{ marginRight: '4px' }} />
                      Conserved ({currentTotal}/{item.received_qty})
                    </Badge>
                  ) : (
                    <Badge variant="danger">
                      <AlertCircle size={12} style={{ marginRight: '4px' }} />
                      Mismatch: {currentTotal}/{item.received_qty} ({diff > 0 ? `+${String(diff)}` : diff})
                    </Badge>
                  )}
                </div>
              </div>

              {/* Categorisation Buckets */}
              <div style={{ marginTop: '0.5rem' }}>
                <div style={{ fontWeight: 600, fontSize: '0.85rem', marginBottom: '0.5rem', color: 'var(--color-text)' }}>
                  Condition Buckets (G-19 conservation required):
                </div>
                {item.allowed_buckets.length === 0 ? (
                  <p role="alert" style={{ fontSize: '0.85rem', color: 'var(--color-danger)' }}>
                    No categorisation buckets are enabled for this product, so its counted quantity
                    cannot be categorised (G-19). Ask an administrator to enable buckets in Admin → Item
                    Field Profiles, then retry.
                  </p>
                ) : (
                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
                      gap: '0.75rem',
                    }}
                  >
                    {item.allowed_buckets.map((b) => (
                      <div
                        key={b.field_id}
                        style={{
                          display: 'flex',
                          flexDirection: 'column',
                          padding: '0.5rem 0.75rem',
                          backgroundColor: 'var(--color-bg-subtle, #f9fafb)',
                          borderRadius: '6px',
                          border: '1px solid var(--color-border)',
                        }}
                      >
                        <label
                          htmlFor={`b-${item.item_id}-${b.field_code}`}
                          style={{ fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.25rem', color: 'var(--color-text)' }}
                          title={b.field_label}
                        >
                          {b.field_label}
                        </label>
                        <input
                          id={`b-${item.item_id}-${b.field_code}`}
                          type="number"
                          min="0"
                          max={item.received_qty}
                          value={bMap[b.field_code] ?? 0}
                          onChange={(e) => {
                            handleBucketChange(item.item_id, b.field_code, parseInt(e.target.value, 10) || 0);
                          }}
                          style={{
                            padding: '0.4rem 0.5rem',
                            borderRadius: '4px',
                            border: '1px solid var(--color-border)',
                            fontSize: '0.9rem',
                            fontWeight: 600,
                            width: '100%',
                            boxSizing: 'border-box',
                          }}
                        />
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Packaging / Container / Manual Counts (Phase 4 ITEM_COUNT) */}
              {item.allowed_counts.length > 0 && (
                <div style={{ marginTop: '0.75rem', paddingTop: '0.75rem', borderTop: '1px dashed var(--color-border)' }}>
                  <div style={{ fontWeight: 600, fontSize: '0.85rem', marginBottom: '0.5rem', color: 'var(--color-text)' }}>
                    Item Auxiliary Counts (Packaging / Container / User Manual):
                  </div>
                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                      gap: '0.75rem',
                    }}
                  >
                    {item.allowed_counts.map((c) => (
                      <div
                        key={c.field_id}
                        style={{
                          display: 'flex',
                          flexDirection: 'column',
                          padding: '0.5rem 0.75rem',
                          backgroundColor: 'var(--color-bg-subtle, #f9fafb)',
                          borderRadius: '6px',
                          border: '1px solid var(--color-border)',
                        }}
                      >
                        <label
                          htmlFor={`c-${item.item_id}-${c.field_code}`}
                          style={{ fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.25rem', color: 'var(--color-text)' }}
                          title={c.field_label}
                        >
                          {c.field_label}
                        </label>
                        <input
                          id={`c-${item.item_id}-${c.field_code}`}
                          type="number"
                          min="0"
                          value={cMap[c.field_code] ?? 0}
                          onChange={(e) => {
                            handleCountChange(item.item_id, c.field_code, parseInt(e.target.value, 10) || 0);
                          }}
                          style={{
                            padding: '0.4rem 0.5rem',
                            borderRadius: '4px',
                            border: '1px solid var(--color-border)',
                            fontSize: '0.9rem',
                            fontWeight: 600,
                            width: '100%',
                            boxSizing: 'border-box',
                          }}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Line Save Button & Errors */}
              <div style={{ marginTop: '0.75rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  {err && (
                    <span role="alert" style={{ fontSize: '0.8rem', color: 'var(--color-danger)' }}>
                      {err.message}
                      {err.requestId ? ` (Request ID: ${err.requestId})` : ''}
                    </span>
                  )}
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  isLoading={isSaving}
                  onClick={() => {
                    void saveLine(item);
                  }}
                >
                  Save Line {item.line_no}
                </Button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Submission Section */}
      <div
        style={{
          marginTop: '1.5rem',
          paddingTop: '1.25rem',
          borderTop: '2px solid var(--color-border)',
        }}
      >
        <label className="form-label" htmlFor="categorisation-remarks">
          Categorisation Remarks (optional)
        </label>
        <Textarea
          id="categorisation-remarks"
          rows={2}
          value={remarks}
          placeholder="e.g. All pieces inspected and categorised as per packaging condition"
          onChange={(e) => {
            setRemarks(e.target.value);
          }}
        />
        {submitError && (
          <p role="alert" className="form-control__error" style={{ marginTop: '0.5rem' }}>
            {submitError.message}
            {submitError.requestId ? ` (Request ID: ${submitError.requestId})` : ''}
          </p>
        )}
        <div style={{ marginTop: '1rem', display: 'flex', gap: '1rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <Button
            type="button"
            variant="primary"
            isLoading={submitting}
            disabled={!data.all_conserved || !data.can_submit}
            onClick={() => {
              void handleSubmit();
            }}
          >
            <Send size={16} style={{ marginRight: '6px' }} />
            Submit Categorisation to RM Review
          </Button>
          <span style={{ fontSize: '0.85rem', color: 'var(--color-muted)' }}>
            {!data.all_conserved
              ? 'Cannot submit: Save every line with bucket quantities equal to its counted quantity.'
              : !data.can_submit
              ? 'Cannot submit: this goods slip is not open for categorisation by you.'
              : 'All lines conserved. Ready for Replacement Manager review.'}
          </span>
        </div>
      </div>
    </section>
  );
}
