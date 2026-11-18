import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, Plus, RefreshCw, Trash2 } from 'lucide-react';

import {
  AsyncCombobox,
  Badge,
  Button,
  Modal,
  Select,
  Textarea,
  type ComboboxOption,
} from '@/components/ui';
import {
  itemizationApi,
  newIdempotencyKey,
  type CategoryLookup,
  type ProductFields,
  type ProductLookup,
} from '@/features/itemization/api';
import { QtyBadges, QtyStepper } from '@/features/itemization/LineParts';
import { toApiError, type ApiError } from '@/lib/api/client';

import { rmReviewApi } from './api';
import type { RmReviewItem } from './types';

// ---------------------------------------------------------------------------
// 1. RmAddLineModal: product, doc qty, physical qty, condition split, reason
// ---------------------------------------------------------------------------
interface AddLineModalProps {
  gsId: string;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => Promise<void>;
}

export function RmAddLineModal({ gsId, isOpen, onClose, onSuccess }: AddLineModalProps) {
  const known = useRef(new Map<string, ProductLookup>());
  const [categories, setCategories] = useState<CategoryLookup[]>([]);
  const [categoryId, setCategoryId] = useState('');
  const [subcategoryId, setSubcategoryId] = useState('');
  const [filterError, setFilterError] = useState<ApiError | null>(null);

  const [productId, setProductId] = useState('');
  const [productLabel, setProductLabel] = useState('');
  const [documented, setDocumented] = useState(0);
  const [received, setReceived] = useState(0);
  const [reason, setReason] = useState('');

  const [fields, setFields] = useState<ProductFields | null>(null);
  const [loadingFields, setLoadingFields] = useState(false);
  const [fieldsError, setFieldsError] = useState<ApiError | null>(null);
  const [split, setSplit] = useState<Record<string, number>>({});
  const [counts, setCounts] = useState<Record<string, number>>({});

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const subcategories = categories.find((c) => c.id === categoryId)?.subcategories ?? [];

  useEffect(() => {
    let live = true;
    itemizationApi
      .categories()
      .then((rows) => {
        if (live) setCategories(rows);
      })
      .catch((err: unknown) => {
        if (live) setFilterError(toApiError(err));
      });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    if (!productId) {
      setFields(null);
      setSplit({});
      setCounts({});
      return;
    }
    let live = true;
    setLoadingFields(true);
    setFieldsError(null);
    itemizationApi
      .productFields(productId)
      .then((res) => {
        if (!live) return;
        setFields(res);
        const nextSplit: Record<string, number> = {};
        for (const b of res.allowed_buckets) {
          nextSplit[b.field_code] = 0;
        }
        const nextCounts: Record<string, number> = {};
        for (const c of res.allowed_counts) {
          nextCounts[c.field_code] = 0;
        }
        setSplit(nextSplit);
        setCounts(nextCounts);
      })
      .catch((err: unknown) => {
        if (!live) return;
        setFieldsError(toApiError(err));
      })
      .finally(() => {
        if (live) setLoadingFields(false);
      });
    return () => {
      live = false;
    };
  }, [productId]);

  const loadOptions = useCallback(
    async (q: string): Promise<ComboboxOption[]> => {
      const rows = await itemizationApi.products(q, { categoryId, subcategoryId });
      for (const p of rows) known.current.set(p.id, p);
      return rows.map((p) => ({
        value: p.id,
        label: p.name,
        sublabel: [p.category_name, p.subcategory_name, p.code].filter(Boolean).join(' · '),
      }));
    },
    [categoryId, subcategoryId],
  );

  const splitTotal = Object.values(split).reduce((a, b) => a + (Number(b) || 0), 0);
  const isConserved = fields ? splitTotal === received : received === 0;
  const isReady =
    productId.length > 0 &&
    isConserved &&
    reason.trim().length >= 1 &&
    !saving;

  const handleSave = async () => {
    if (!productId || !reason.trim()) return;
    try {
      setSaving(true);
      setError(null);
      const bucketPayload = Object.entries(split).map(([field_code, qty]) => ({
        field_code,
        qty: Number(qty) || 0,
      }));
      const countPayload = Object.entries(counts).map(([count_type, count_value]) => ({
        count_type,
        count_value: Number(count_value) || 0,
      }));
      await rmReviewApi.addLine(
        gsId,
        {
          product_id: productId,
          documented_qty: documented,
          received_qty: received,
          buckets: bucketPayload,
          counts: countPayload,
          reason: reason.trim(),
        },
        newIdempotencyKey(),
      );
      onClose();
      await onSuccess();
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Add Line in RM Review (DEC-54)">
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {/* Filters */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
          <Select
            id="add-line-category"
            aria-label="Filter by category"
            placeholder="All categories"
            options={categories.map((c) => ({ value: c.id, label: c.name }))}
            value={categoryId}
            onChange={(e) => {
              setCategoryId(e.target.value);
              setSubcategoryId('');
            }}
          />
          <Select
            id="add-line-subcategory"
            aria-label="Filter by sub-category"
            placeholder="All sub-categories"
            options={subcategories.map((c) => ({ value: c.id, label: c.name }))}
            value={subcategoryId}
            disabled={!categoryId || subcategories.length === 0}
            onChange={(e) => {
              setSubcategoryId(e.target.value);
            }}
          />
        </div>
        {filterError && (
          <p role="alert" className="form-control__error">
            Filters unavailable: {filterError.message}
          </p>
        )}

        {/* Product Search */}
        <div>
          <label className="form-label" htmlFor="add-line-product">
            Select Product *
          </label>
          <AsyncCombobox
            key={`${categoryId}|${subcategoryId}`}
            id="add-line-product"
            name="product"
            value={productId}
            loadOptions={loadOptions}
            placeholder={productLabel || 'Search product name, code…'}
            onChange={(val) => {
              setProductId(val);
              setProductLabel(known.current.get(val)?.name ?? '');
            }}
          />
        </div>

        {/* Steppers */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
          <QtyStepper
            id="add-line-doc"
            label="As per document"
            value={documented}
            onChange={setDocumented}
          />
          <QtyStepper
            id="add-line-recv"
            label="Physically received *"
            value={received}
            onChange={setReceived}
          />
        </div>
        <QtyBadges documented={documented} received={received} />

        {/* Condition Split */}
        {productId ? (
          <fieldset
            style={{
              border: '1px solid var(--color-border)',
              borderRadius: '8px',
              padding: '0.75rem 1rem',
            }}
          >
            <legend style={{ fontWeight: 600, fontSize: '0.9rem', padding: '0 0.5rem' }}>
              Condition Split (G-19)
            </legend>
            {loadingFields ? (
              <p style={{ color: 'var(--color-muted)', fontSize: '0.85rem' }}>Loading condition fields…</p>
            ) : fieldsError ? (
              <p role="alert" className="form-control__error">
                {fieldsError.message}
              </p>
            ) : fields?.allowed_buckets.length === 0 ? (
              <p style={{ color: 'var(--color-muted)', fontSize: '0.85rem' }}>
                No condition buckets configured for this product.
              </p>
            ) : (
              <>
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
                    gap: '0.75rem',
                    marginTop: '0.5rem',
                  }}
                >
                  {fields?.allowed_buckets.map((b) => (
                    <QtyStepper
                      key={b.field_code}
                      id={`add-line-bucket-${b.field_code}`}
                      label={b.field_label}
                      value={split[b.field_code] ?? 0}
                      onChange={(v) => setSplit((m) => ({ ...m, [b.field_code]: v }))}
                    />
                  ))}
                </div>
                <div style={{ marginTop: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <Badge variant={isConserved ? 'success' : 'danger'}>
                    Split {splitTotal} / Physical {received}
                  </Badge>
                  {!isConserved && (
                    <span style={{ fontSize: '0.8rem', color: '#dc2626' }}>
                      Split sum must equal physically received quantity ({received})
                    </span>
                  )}
                </div>
                {fields && fields.allowed_counts.length > 0 && (
                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
                      gap: '0.75rem',
                      marginTop: '0.75rem',
                      borderTop: '1px dashed var(--color-border)',
                      paddingTop: '0.75rem',
                    }}
                  >
                    {fields.allowed_counts.map((c) => (
                      <QtyStepper
                        key={c.field_code}
                        id={`add-line-count-${c.field_code}`}
                        label={c.field_label}
                        value={counts[c.field_code] ?? 0}
                        onChange={(v) => setCounts((m) => ({ ...m, [c.field_code]: v }))}
                      />
                    ))}
                  </div>
                )}
              </>
            )}
          </fieldset>
        ) : null}

        {/* Reason */}
        <div>
          <label className="form-label" htmlFor="add-line-reason">
            Reason for adding line * (mandatory, DEC-54)
          </label>
          <Textarea
            id="add-line-reason"
            placeholder="State reason for adding this line..."
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            required
          />
        </div>

        {error && (
          <p role="alert" className="form-control__error">
            {error.message}
          </p>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '0.5rem' }}>
          <Button type="button" variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            onClick={handleSave}
            disabled={!isReady}
          >
            <Plus size={16} style={{ marginRight: '6px' }} />
            {saving ? 'Adding Line…' : 'Add Line (RM_ADD_LINE)'}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// 2. RmChangeProductModal: change product on existing line, reason required
// ---------------------------------------------------------------------------
interface ChangeProductModalProps {
  gsId: string;
  item: RmReviewItem;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => Promise<void>;
}

export function RmChangeProductModal({
  gsId,
  item,
  isOpen,
  onClose,
  onSuccess,
}: ChangeProductModalProps) {
  const known = useRef(new Map<string, ProductLookup>());
  const [categories, setCategories] = useState<CategoryLookup[]>([]);
  const [categoryId, setCategoryId] = useState('');
  const [subcategoryId, setSubcategoryId] = useState('');

  const [productId, setProductId] = useState(item.product_id);
  const [productLabel, setProductLabel] = useState(item.sku_name);
  const [documented, setDocumented] = useState(item.documented_qty);
  const [received, setReceived] = useState(item.received_qty);
  const [reason, setReason] = useState('');

  const [fields, setFields] = useState<ProductFields | null>(null);
  const [loadingFields, setLoadingFields] = useState(false);
  const [fieldsError, setFieldsError] = useState<ApiError | null>(null);
  const [split, setSplit] = useState<Record<string, number>>({});
  const [counts, setCounts] = useState<Record<string, number>>({});

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const subcategories = categories.find((c) => c.id === categoryId)?.subcategories ?? [];

  useEffect(() => {
    let live = true;
    itemizationApi
      .categories()
      .then((rows) => {
        if (live) setCategories(rows);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    if (!productId) {
      setFields(null);
      setSplit({});
      setCounts({});
      return;
    }
    let live = true;
    setLoadingFields(true);
    setFieldsError(null);
    itemizationApi
      .productFields(productId)
      .then((res) => {
        if (!live) return;
        setFields(res);
        const nextSplit: Record<string, number> = {};
        for (const b of res.allowed_buckets) {
          nextSplit[b.field_code] = 0;
        }
        const nextCounts: Record<string, number> = {};
        for (const c of res.allowed_counts) {
          nextCounts[c.field_code] = 0;
        }
        setSplit(nextSplit);
        setCounts(nextCounts);
      })
      .catch((err: unknown) => {
        if (!live) return;
        setFieldsError(toApiError(err));
      })
      .finally(() => {
        if (live) setLoadingFields(false);
      });
    return () => {
      live = false;
    };
  }, [productId]);

  const loadOptions = useCallback(
    async (q: string): Promise<ComboboxOption[]> => {
      const rows = await itemizationApi.products(q, { categoryId, subcategoryId });
      for (const p of rows) known.current.set(p.id, p);
      return rows.map((p) => ({
        value: p.id,
        label: p.name,
        sublabel: [p.category_name, p.subcategory_name, p.code].filter(Boolean).join(' · '),
      }));
    },
    [categoryId, subcategoryId],
  );

  const splitTotal = Object.values(split).reduce((a, b) => a + (Number(b) || 0), 0);
  const isConserved = fields ? splitTotal === received : received === 0;
  const isReady =
    productId.length > 0 &&
    isConserved &&
    reason.trim().length >= 1 &&
    !saving;

  const handleSave = async () => {
    if (!productId || !reason.trim()) return;
    try {
      setSaving(true);
      setError(null);
      const bucketPayload = Object.entries(split).map(([field_code, qty]) => ({
        field_code,
        qty: Number(qty) || 0,
      }));
      const countPayload = Object.entries(counts).map(([count_type, count_value]) => ({
        count_type,
        count_value: Number(count_value) || 0,
      }));
      await rmReviewApi.changeProduct(
        gsId,
        item.item_id,
        {
          product_id: productId,
          documented_qty: documented,
          received_qty: received,
          buckets: bucketPayload,
          counts: countPayload,
          reason: reason.trim(),
        },
        newIdempotencyKey(),
      );
      onClose();
      await onSuccess();
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={`Change Product: ${item.sku_name}`}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        <div style={{ padding: '0.5rem 0.75rem', backgroundColor: 'var(--color-bg-subtle, #f3f4f6)', borderRadius: '6px', fontSize: '0.85rem' }}>
          Current Line: <strong>{item.sku_name}</strong> ({item.sku_code}) &bull; Counted: <strong>{item.received_qty}</strong>
        </div>

        {/* Filters */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
          <Select
            id="change-prod-category"
            aria-label="Filter by category"
            placeholder="All categories"
            options={categories.map((c) => ({ value: c.id, label: c.name }))}
            value={categoryId}
            onChange={(e) => {
              setCategoryId(e.target.value);
              setSubcategoryId('');
            }}
          />
          <Select
            id="change-prod-subcategory"
            aria-label="Filter by sub-category"
            placeholder="All sub-categories"
            options={subcategories.map((c) => ({ value: c.id, label: c.name }))}
            value={subcategoryId}
            disabled={!categoryId || subcategories.length === 0}
            onChange={(e) => {
              setSubcategoryId(e.target.value);
            }}
          />
        </div>

        {/* Product Search */}
        <div>
          <label className="form-label" htmlFor="change-prod-search">
            New Product *
          </label>
          <AsyncCombobox
            key={`${categoryId}|${subcategoryId}`}
            id="change-prod-search"
            name="product"
            value={productId}
            loadOptions={loadOptions}
            placeholder={productLabel || 'Search product name, code…'}
            onChange={(val) => {
              setProductId(val);
              setProductLabel(known.current.get(val)?.name ?? '');
            }}
          />
        </div>

        {/* Steppers */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
          <QtyStepper
            id="change-prod-doc"
            label="As per document"
            value={documented}
            onChange={setDocumented}
          />
          <QtyStepper
            id="change-prod-recv"
            label="Physically received *"
            value={received}
            onChange={setReceived}
          />
        </div>
        <QtyBadges documented={documented} received={received} />

        {/* Condition Split */}
        <fieldset
          style={{
            border: '1px solid var(--color-border)',
            borderRadius: '8px',
            padding: '0.75rem 1rem',
          }}
        >
          <legend style={{ fontWeight: 600, fontSize: '0.9rem', padding: '0 0.5rem' }}>
            New Condition Split (G-19)
          </legend>
          {loadingFields ? (
            <p style={{ color: 'var(--color-muted)', fontSize: '0.85rem' }}>Loading condition fields…</p>
          ) : fieldsError ? (
            <p role="alert" className="form-control__error">
              {fieldsError.message}
            </p>
          ) : fields?.allowed_buckets.length === 0 ? (
            <p style={{ color: 'var(--color-muted)', fontSize: '0.85rem' }}>
              No condition buckets configured for this product.
            </p>
          ) : (
            <>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
                  gap: '0.75rem',
                  marginTop: '0.5rem',
                }}
              >
                {fields?.allowed_buckets.map((b) => (
                  <QtyStepper
                    key={b.field_code}
                    id={`change-prod-bucket-${b.field_code}`}
                    label={b.field_label}
                    value={split[b.field_code] ?? 0}
                    onChange={(v) => setSplit((m) => ({ ...m, [b.field_code]: v }))}
                  />
                ))}
              </div>
              <div style={{ marginTop: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Badge variant={isConserved ? 'success' : 'danger'}>
                  Split {splitTotal} / Physical {received}
                </Badge>
                {!isConserved && (
                  <span style={{ fontSize: '0.8rem', color: '#dc2626' }}>
                    Split sum must equal physically received quantity ({received})
                  </span>
                )}
              </div>
              {fields && fields.allowed_counts.length > 0 && (
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
                    gap: '0.75rem',
                    marginTop: '0.75rem',
                    borderTop: '1px dashed var(--color-border)',
                    paddingTop: '0.75rem',
                  }}
                >
                  {fields.allowed_counts.map((c) => (
                    <QtyStepper
                      key={c.field_code}
                      id={`change-prod-count-${c.field_code}`}
                      label={c.field_label}
                      value={counts[c.field_code] ?? 0}
                      onChange={(v) => setCounts((m) => ({ ...m, [c.field_code]: v }))}
                    />
                  ))}
                </div>
              )}
            </>
          )}
        </fieldset>

        {/* Reason */}
        <div>
          <label className="form-label" htmlFor="change-prod-reason">
            Reason for changing product * (mandatory, DEC-54)
          </label>
          <Textarea
            id="change-prod-reason"
            placeholder="State reason for changing product..."
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            required
          />
        </div>

        {error && (
          <p role="alert" className="form-control__error">
            {error.message}
          </p>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '0.5rem' }}>
          <Button type="button" variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            onClick={handleSave}
            disabled={!isReady}
          >
            <RefreshCw size={16} style={{ marginRight: '6px' }} />
            {saving ? 'Updating Product…' : 'Change Product (RM_CHANGE_PRODUCT)'}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// 3. RmRemoveLineModal: remove line, reason required
// ---------------------------------------------------------------------------
interface RemoveLineModalProps {
  gsId: string;
  item: RmReviewItem;
  lineNo: number;
  totalLines: number;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => Promise<void>;
}

export function RmRemoveLineModal({
  gsId,
  item,
  lineNo,
  totalLines,
  isOpen,
  onClose,
  onSuccess,
}: RemoveLineModalProps) {
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const canRemove = totalLines > 1;

  const handleRemove = async () => {
    if (!reason.trim()) return;
    try {
      setSaving(true);
      setError(null);
      await rmReviewApi.removeLine(
        gsId,
        item.item_id,
        { reason: reason.trim() },
        newIdempotencyKey(),
      );
      onClose();
      await onSuccess();
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Remove Item Line (DEC-54)">
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        <div
          style={{
            padding: '0.75rem',
            backgroundColor: '#fef2f2',
            border: '1px solid #fecaca',
            borderRadius: '6px',
            color: '#991b1b',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
          }}
        >
          <AlertTriangle size={20} color="#b91c1c" />
          <div>
            Remove Line <strong>#{lineNo}. {item.sku_name}</strong> ({item.sku_code})?
            <div style={{ fontSize: '0.8rem', marginTop: '0.25rem' }}>
              Documented: {item.documented_qty} &bull; Counted: {item.received_qty}
            </div>
          </div>
        </div>

        {!canRemove ? (
          <p role="alert" className="form-control__error">
            Cannot remove the only item line on the goods slip (BR-07 requires at least one line).
          </p>
        ) : (
          <div>
            <label className="form-label" htmlFor="remove-line-reason">
              Reason for removing line * (mandatory, DEC-54)
            </label>
            <Textarea
              id="remove-line-reason"
              placeholder="Explain why this item line is being removed..."
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              required
            />
          </div>
        )}

        {error && (
          <p role="alert" className="form-control__error">
            {error.message}
          </p>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '0.5rem' }}>
          <Button type="button" variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="danger"
            onClick={handleRemove}
            disabled={!canRemove || reason.trim().length === 0 || saving}
          >
            <Trash2 size={16} style={{ marginRight: '6px' }} />
            {saving ? 'Removing Line…' : 'Remove Line (RM_REMOVE_LINE)'}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
