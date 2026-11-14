import { useEffect, useState } from 'react';
import { AlertCircle, CheckCircle2, PackageCheck, Send, ShieldAlert } from 'lucide-react';

import { Badge, Button, ErrorState, LoadingState, Textarea } from '@/components/ui';
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

export function ItemCategorisationSection({ gsId, onDone }: Props) {
  const [data, setData] = useState<CategorisationStateOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<ApiError | null>(null);

  // Local editing state: item_id -> { buckets: Record<code, qty>, counts: Record<code, qty> }
  const [draftBuckets, setDraftBuckets] = useState<Record<string, Record<string, number>>>({});
  const [draftCounts, setDraftCounts] = useState<Record<string, Record<string, number>>>({});
  const [savingItem, setSavingItem] = useState<string | null>(null);
  const [itemError, setItemError] = useState<{ id: string; error: ApiError } | null>(null);

  const [remarks, setRemarks] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<ApiError | null>(null);

  const reload = async () => {
    try {
      setLoading(true);
      setLoadError(null);
      const res = await itemizationApi.getCategorisation(gsId);
      setData(res);

      // Initialise drafts from server data
      const initB: Record<string, Record<string, number>> = {};
      const initC: Record<string, Record<string, number>> = {};
      for (const it of res.items) {
        const itemBuckets: Record<string, number> = {};
        for (const b of it.allowed_buckets) {
          const matched = it.buckets.find((x) => x.field_code === b.field_code);
          itemBuckets[b.field_code] = matched ? matched.qty : 0;
        }
        initB[it.id] = itemBuckets;

        const itemCounts: Record<string, number> = {};
        for (const c of it.allowed_counts) {
          const matched = it.counts.find((x) => x.field_code === c.field_code);
          itemCounts[c.field_code] = matched ? matched.count_value : 0;
        }
        initC[it.id] = itemCounts;
      }
      setDraftBuckets(initB);
      setDraftCounts(initC);
    } catch (err) {
      setLoadError(toApiError(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void reload();
  }, [gsId]);

  if (loading && !data) return <LoadingState />;
  if (loadError) return <ErrorState error={loadError} onRetry={reload} />;
  if (!data) return null;

  const handleBucketChange = (itemId: string, fieldCode: string, val: number) => {
    setDraftBuckets((prev) => ({
      ...prev,
      [itemId]: {
        ...(prev[itemId] || {}),
        [fieldCode]: Math.max(0, val),
      },
    }));
  };

  const handleCountChange = (itemId: string, fieldCode: string, val: number) => {
    setDraftCounts((prev) => ({
      ...prev,
      [itemId]: {
        ...(prev[itemId] || {}),
        [fieldCode]: Math.max(0, val),
      },
    }));
  };

  const saveLine = async (item: ItemCategorisationDetail) => {
    try {
      setSavingItem(item.id);
      setItemError(null);
      const bMap = draftBuckets[item.id] || {};
      const cMap = draftCounts[item.id] || {};

      const bucketsPayload = item.allowed_buckets.map((b) => ({
        field_code: b.field_code,
        qty: bMap[b.field_code] ?? 0,
      }));
      const countsPayload = item.allowed_counts.map((c) => ({
        field_code: c.field_code,
        count_value: cMap[c.field_code] ?? 0,
      }));

      const updated = await itemizationApi.saveItemCategorisation(gsId, item.id, {
        buckets: bucketsPayload,
        counts: countsPayload,
      });

      // Update item in local data
      setData((prev) => {
        if (!prev) return null;
        const nextItems = prev.items.map((i) => (i.id === item.id ? updated : i));
        const allCons = nextItems.every((i) => i.is_conserved);
        return {
          ...prev,
          items: nextItems,
          all_conserved: allCons,
          can_submit: allCons && prev.is_counted_by_current_user,
        };
      });
    } catch (err) {
      setItemError({ id: item.id, error: toApiError(err) });
    } finally {
      setSavingItem(null);
    }
  };

  const handleSubmit = async () => {
    try {
      setSubmitting(true);
      setSubmitError(null);
      await itemizationApi.submitCategorisation(
        gsId,
        { category_code: 'REGULAR_RETURN', remarks: remarks.trim() || null },
        newIdempotencyKey(),
      );
      onDone();
    } catch (err) {
      setSubmitError(toApiError(err));
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

      {/* Same user who counted guard warning (AMD-08) */}
      {!data.is_counted_by_current_user && (
        <div
          role="alert"
          style={{
            marginTop: '1rem',
            padding: '0.75rem 1rem',
            borderRadius: '6px',
            backgroundColor: 'var(--color-warning-light, #fef3c7)',
            color: 'var(--color-warning-dark, #92400e)',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            fontSize: '0.875rem',
          }}
        >
          <ShieldAlert size={18} />
          <span>
            <strong>Authorisation Notice:</strong> Only the inward verifier who counted this slip can submit
            categorisation (AMD-08).
          </span>
        </div>
      )}

      {/* Item Lines */}
      <div style={{ marginTop: '1.25rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {data.items.map((item) => {
          const bMap = draftBuckets[item.id] || {};
          const cMap = draftCounts[item.id] || {};
          const currentTotal = Object.values(bMap).reduce((a, b) => a + (Number(b) || 0), 0);
          const isLocallyConserved = currentTotal === item.received_qty;
          const diff = currentTotal - item.received_qty;
          const isSaving = savingItem === item.id;
          const err = itemError?.id === item.id ? itemError.error : null;

          return (
            <div
              key={item.id}
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
                      Mismatch: {currentTotal}/{item.received_qty} ({diff > 0 ? `+${diff}` : diff})
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
                  <p style={{ fontSize: '0.85rem', color: 'var(--color-muted)' }}>No categorisation fields enabled for this product.</p>
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
                          htmlFor={`b-${item.id}-${b.field_code}`}
                          style={{ fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.25rem', color: 'var(--color-text)' }}
                          title={b.label}
                        >
                          {b.label}
                        </label>
                        <input
                          id={`b-${item.id}-${b.field_code}`}
                          type="number"
                          min="0"
                          max={item.received_qty}
                          value={bMap[b.field_code] ?? 0}
                          onChange={(e) => handleBucketChange(item.id, b.field_code, parseInt(e.target.value, 10) || 0)}
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
                          htmlFor={`c-${item.id}-${c.field_code}`}
                          style={{ fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.25rem', color: 'var(--color-text)' }}
                          title={c.label}
                        >
                          {c.label}
                        </label>
                        <input
                          id={`c-${item.id}-${c.field_code}`}
                          type="number"
                          min="0"
                          value={cMap[c.field_code] ?? 0}
                          onChange={(e) => handleCountChange(item.id, c.field_code, parseInt(e.target.value, 10) || 0)}
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
                    <span style={{ fontSize: '0.8rem', color: 'var(--color-danger)' }}>
                      {err.message}
                    </span>
                  )}
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  isLoading={isSaving}
                  onClick={() => void saveLine(item)}
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
          onChange={(e) => setRemarks(e.target.value)}
        />
        {submitError && (
          <p role="alert" className="form-control__error" style={{ marginTop: '0.5rem' }}>
            {submitError.message}
          </p>
        )}
        <div style={{ marginTop: '1rem', display: 'flex', gap: '1rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <Button
            type="button"
            variant="primary"
            isLoading={submitting}
            disabled={!data.all_conserved || !data.is_counted_by_current_user}
            onClick={() => void handleSubmit()}
          >
            <Send size={16} style={{ marginRight: '6px' }} />
            Submit Categorisation to RM Review
          </Button>
          <span style={{ fontSize: '0.85rem', color: 'var(--color-muted)' }}>
            {!data.all_conserved
              ? 'Cannot submit: Resolve bucket quantity mismatches across all items.'
              : !data.is_counted_by_current_user
              ? 'Cannot submit: You are not the inward verifier who counted this slip.'
              : 'All lines conserved. Ready for Replacement Manager review.'}
          </span>
        </div>
      </div>
    </section>
  );
}
