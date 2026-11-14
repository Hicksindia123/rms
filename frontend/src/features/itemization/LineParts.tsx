import { useCallback, useEffect, useRef, useState } from 'react';
import { FileText, Minus, Plus, X } from 'lucide-react';

import { AsyncCombobox, Badge, Button, Select, Textarea } from '@/components/ui';
import type { ComboboxOption } from '@/components/ui';
import type { Attachment } from '@/features/unboxing/api';
import { DocumentImage } from '@/features/unboxing/SignedMedia';
import { toApiError, type ApiError } from '@/lib/api/client';

import {
  itemizationApi,
  type CategoryLookup,
  type ItemLine,
  type LineInput,
  type ProductLookup,
} from './api';

/** Big touch-friendly number stepper (≥ 48px targets) for counting on a phone. */
export function QtyStepper({
  id,
  label,
  value,
  onChange,
  disabled,
}: {
  id: string;
  label: string;
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
}) {
  return (
    <div className="qty-stepper">
      <label htmlFor={id} className="qty-stepper__label">
        {label}
      </label>
      <div className="qty-stepper__row">
        <button
          type="button"
          className="qty-stepper__btn"
          aria-label={`Decrease ${label}`}
          disabled={disabled || value <= 0}
          onClick={() => {
            onChange(Math.max(0, value - 1));
          }}
        >
          <Minus size={20} aria-hidden="true" />
        </button>
        <input
          id={id}
          className="qty-stepper__input"
          type="number"
          inputMode="numeric"
          min={0}
          value={Number.isFinite(value) ? value : 0}
          disabled={disabled}
          onChange={(e) => {
            const n = Number.parseInt(e.target.value, 10);
            onChange(Number.isFinite(n) && n >= 0 ? n : 0);
          }}
        />
        <button
          type="button"
          className="qty-stepper__btn"
          aria-label={`Increase ${label}`}
          disabled={disabled}
          onClick={() => {
            onChange(value + 1);
          }}
        >
          <Plus size={20} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}

/** Live short / excess badges (DEC-09: short = documented − received). */
export function QtyBadges({ documented, received }: { documented: number; received: number }) {
  // Change plan Phase 3: the documented qty is optional at counting; without one there is
  // nothing to compare against, so no short / excess is shown.
  if (documented === 0) {
    return <Badge variant="neutral">No document qty</Badge>;
  }
  const short = Math.max(documented - received, 0);
  const excess = Math.max(received - documented, 0);
  if (short === 0 && excess === 0) {
    return <Badge variant="success">Matches document</Badge>;
  }
  return (
    <span style={{ display: 'inline-flex', gap: '0.375rem', flexWrap: 'wrap' }}>
      {short > 0 ? <Badge variant="warning">Short {short}</Badge> : null}
      {excess > 0 ? <Badge variant="info">Excess {excess}</Badge> : null}
    </span>
  );
}

/** One counted line (read-only). */
export function ItemLineCard({ item, actions }: { item: ItemLine; actions?: React.ReactNode }) {
  return (
    <li className="item-line" data-testid="item-line">
      <div className="item-line__head">
        <span className="item-line__no">#{item.line_no}</span>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="item-line__name">{item.product_name ?? item.product_code}</div>
          <div className="item-line__meta">
            {item.category_name ?? item.category_code}
            {item.product_code ? ` · ${item.product_code}` : ''}
          </div>
        </div>
        {actions}
      </div>
      <dl className="item-line__qty">
        <div>
          <dt>As per document</dt>
          <dd>{item.documented_qty}</dd>
        </div>
        <div>
          <dt>Physically received</dt>
          <dd>{item.received_qty}</dd>
        </div>
        <div className="item-line__badges">
          {item.short_qty === 0 && item.excess_qty === 0 ? (
            <Badge variant="success">Matches document</Badge>
          ) : null}
          {item.short_qty > 0 ? (
            <Badge variant={item.is_short ? 'warning' : 'neutral'}>Short {item.short_qty}</Badge>
          ) : null}
          {item.excess_qty > 0 ? <Badge variant="info">Excess {item.excess_qty}</Badge> : null}
          {item.stocked_qty !== null ? (
            <Badge variant="neutral">In stock {item.stocked_qty}</Badge>
          ) : null}
        </div>
      </dl>
      {item.remarks ? <p className="item-line__remarks">{item.remarks}</p> : null}
    </li>
  );
}

/** Add / edit a line: product search, two big steppers, live badges, remarks. */
export function LineEditor({
  gsId,
  initial,
  onSaved,
  onCancel,
}: {
  gsId: string;
  initial?: ItemLine | undefined;
  onSaved: () => void;
  onCancel?: (() => void) | undefined;
}) {
  const known = useRef(new Map<string, ProductLookup>());
  const [productId, setProductId] = useState(initial?.product_id ?? '');
  const [productLabel, setProductLabel] = useState(initial?.product_name ?? '');
  const [documented, setDocumented] = useState(initial?.documented_qty ?? 0);
  const [received, setReceived] = useState(initial?.received_qty ?? 0);
  const [remarks, setRemarks] = useState(initial?.remarks ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const idPrefix = initial ? `line-${initial.id}` : 'line-new';
  // Counting search (change plan Phase 3, AMD-07): optional Category -> Sub-Category filters.
  const [categories, setCategories] = useState<CategoryLookup[]>([]);
  const [categoryId, setCategoryId] = useState('');
  const [subcategoryId, setSubcategoryId] = useState('');
  const [filterError, setFilterError] = useState<ApiError | null>(null);
  const subcategories = categories.find((c) => c.id === categoryId)?.subcategories ?? [];

  useEffect(() => {
    let live = true;
    itemizationApi
      .categories()
      .then((rows) => {
        if (live) setCategories(rows);
      })
      .catch((err: unknown) => {
        console.error('Product categories could not be loaded', err);
        if (live) setFilterError(toApiError(err));
      });
    return () => {
      live = false;
    };
  }, []);

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

  const save = async () => {
    setBusy(true);
    setError(null);
    const body: LineInput = {
      product_id: productId,
      documented_qty: documented,
      received_qty: received,
      remarks: remarks.trim() || null,
    };
    try {
      if (initial) await itemizationApi.updateItem(gsId, initial.id, body);
      else await itemizationApi.addItem(gsId, body);
      if (!initial) {
        setProductId('');
        setProductLabel('');
        setDocumented(0);
        setReceived(0);
        setRemarks('');
      }
      onSaved();
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="line-editor" data-testid="line-editor">
      <div className="line-editor__filters">
        <Select
          id={`${idPrefix}-category`}
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
          id={`${idPrefix}-subcategory`}
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
      {filterError ? (
        <p role="alert" className="form-control__error">
          Filters unavailable: {filterError.message}
          {filterError.requestId ? ` (Request ID: ${filterError.requestId})` : ''}
        </p>
      ) : null}
      <label className="form-label" htmlFor={`${idPrefix}-product`}>
        Product
      </label>
      <AsyncCombobox
        // Re-mount when the filters change so the list reloads.
        key={`${categoryId}|${subcategoryId}`}
        id={`${idPrefix}-product`}
        name="product"
        value={productId}
        loadOptions={loadOptions}
        placeholder={productLabel || 'Search name, code, category or sub-category…'}
        onChange={(value) => {
          setProductId(value);
          setProductLabel(known.current.get(value)?.name ?? '');
        }}
      />
      <div className="line-editor__steppers">
        <QtyStepper
          id={`${idPrefix}-documented`}
          label="As per document (optional)"
          value={documented}
          onChange={setDocumented}
        />
        <QtyStepper
          id={`${idPrefix}-received`}
          label="Physically received"
          value={received}
          onChange={setReceived}
        />
      </div>
      <div aria-live="polite" style={{ margin: '0.5rem 0' }}>
        <QtyBadges documented={documented} received={received} />
      </div>
      <label className="form-label" htmlFor={`${idPrefix}-remarks`}>
        Remarks (optional)
      </label>
      <Textarea
        id={`${idPrefix}-remarks`}
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
      <div className="line-editor__actions">
        {onCancel ? (
          <Button type="button" variant="secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        ) : null}
        <Button
          type="button"
          variant="primary"
          isLoading={busy}
          disabled={!productId || (documented === 0 && received === 0)}
          onClick={() => {
            void save();
          }}
        >
          {initial ? 'Save line' : 'Add line'}
        </Button>
      </div>
    </div>
  );
}

/** Document photos for counting: a side panel on desktop, a bottom sheet on phones. */
export function DocumentPanel({
  documents,
  open,
  onClose,
}: {
  documents: Attachment[];
  open: boolean;
  onClose: () => void;
}) {
  return (
    <aside
      className={`doc-panel${open ? ' doc-panel--open' : ''}`}
      aria-label="Document photos"
      data-testid="doc-panel"
    >
      <div className="doc-panel__head">
        <h2 className="unboxing__h2">
          <FileText size={18} aria-hidden="true" /> Documents ({documents.length})
        </h2>
        <button
          type="button"
          className="doc-panel__close"
          aria-label="Close documents"
          onClick={onClose}
        >
          <X size={20} aria-hidden="true" />
        </button>
      </div>
      {documents.length === 0 ? (
        <p className="page__subtitle">No document photos on this GS.</p>
      ) : (
        <div className="doc-panel__list">
          {documents.map((d, i) => (
            <DocumentImage key={d.id} attachment={d} alt={`Document photo ${String(i + 1)}`} />
          ))}
        </div>
      )}
    </aside>
  );
}
