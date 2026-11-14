import { useCallback, useEffect, useState } from 'react';

import {
  Badge,
  Button,
  Checkbox,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
  Modal,
  Select,
} from '@/components/ui';
import { useApiQuery } from '@/hooks/useApiQuery';
import { toApiError, type ApiError } from '@/lib/api/client';

import {
  mastersApi,
  type Product,
  type ProductCategory,
  type ProductSubCategory,
  type ProductUpdateInput,
} from './api';

const PAGE_SIZE = 25;
const NO_SUB = '__none__';

/** Sub-categories of one category (active ones, plus the currently assigned one if inactive). */
function useSubcategories(categoryId: string) {
  const fetcher = useCallback(
    () =>
      categoryId
        ? mastersApi.subcategories(categoryId, true)
        : Promise.resolve([] as ProductSubCategory[]),
    [categoryId],
  );
  return useApiQuery(fetcher);
}

export function ProductsPanel({
  categories,
  canEdit,
}: {
  categories: ProductCategory[];
  canEdit: boolean;
}) {
  const [search, setSearch] = useState('');
  const [q, setQ] = useState('');
  const [categoryId, setCategoryId] = useState('');
  const [subFilter, setSubFilter] = useState('');
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Product | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Debounce the search box so typing does not fire a request per key.
  useEffect(() => {
    const t = window.setTimeout(() => {
      setQ(search.trim());
      setPage(1);
    }, 300);
    return () => {
      window.clearTimeout(t);
    };
  }, [search]);

  const filterSubs = useSubcategories(categoryId);
  const fetchProducts = useCallback(
    () =>
      mastersApi.products({
        q,
        category_id: categoryId || null,
        subcategory_id: subFilter && subFilter !== NO_SUB ? subFilter : null,
        without_subcategory: subFilter === NO_SUB,
        page,
        page_size: PAGE_SIZE,
      }),
    [q, categoryId, subFilter, page],
  );
  const products = useApiQuery(fetchProducts);
  const pages = products.data ? Math.max(1, Math.ceil(products.data.total / PAGE_SIZE)) : 1;

  return (
    <div className="masters-panel">
      <div className="filters">
        <label className="masters-field">
          <span className="form-label">Search</span>
          <Input
            id="product-search"
            type="search"
            value={search}
            placeholder="Name or code"
            maxLength={100}
            onChange={(e) => {
              setSearch(e.target.value);
            }}
          />
        </label>
        <label className="masters-field">
          <span className="form-label">Category</span>
          <Select
            id="product-filter-category"
            value={categoryId}
            placeholder="All categories"
            options={categories.map((c) => ({ value: c.id, label: c.name }))}
            onChange={(e) => {
              setCategoryId(e.target.value);
              setSubFilter('');
              setPage(1);
            }}
          />
        </label>
        <label className="masters-field">
          <span className="form-label">Sub-Category</span>
          <Select
            id="product-filter-sub"
            value={subFilter}
            placeholder="All"
            options={[
              { value: NO_SUB, label: '(No sub-category)' },
              ...(filterSubs.data ?? []).map((s) => ({ value: s.id, label: s.name })),
            ]}
            onChange={(e) => {
              setSubFilter(e.target.value);
              setPage(1);
            }}
          />
        </label>
      </div>

      {notice && (
        <p className="masters-notice" role="status">
          {notice}
        </p>
      )}

      {products.error ? (
        <ErrorState error={products.error} onRetry={products.reload} />
      ) : products.loading || !products.data ? (
        <LoadingState label="Loading products…" />
      ) : products.data.items.length === 0 ? (
        <EmptyState title="No products match" hint="Change the search or the filters." />
      ) : (
        <>
          <p className="masters-row__meta">{products.data.total} products</p>
          <ul className="masters-list">
            {products.data.items.map((p) => (
              <li key={p.id} className="masters-row">
                <div className="masters-row__main">
                  <div className="masters-row__title">
                    <span>{p.name}</span>
                    {!p.is_active && <Badge variant="neutral">Inactive</Badge>}
                  </div>
                  <div className="masters-row__meta">
                    {p.code} · {p.category_name} / {p.subcategory_name ?? '—'} · {p.uom}
                    {p.hsn_code ? ` · HSN ${p.hsn_code}` : ''}
                  </div>
                </div>
                {canEdit && (
                  <Button
                    type="button"
                    size="sm"
                    className="masters-row__action"
                    onClick={() => {
                      setNotice(null);
                      setEditing(p);
                    }}
                  >
                    Edit
                  </Button>
                )}
              </li>
            ))}
          </ul>
          <nav className="masters-pager" aria-label="Product pages">
            <Button
              type="button"
              disabled={page <= 1}
              onClick={() => {
                setPage((n) => n - 1);
              }}
            >
              Previous
            </Button>
            <span>
              Page {page} of {pages}
            </span>
            <Button
              type="button"
              disabled={page >= pages}
              onClick={() => {
                setPage((n) => n + 1);
              }}
            >
              Next
            </Button>
          </nav>
        </>
      )}

      {editing && (
        <ProductDialog
          product={editing}
          categories={categories}
          onClose={() => {
            setEditing(null);
          }}
          onSaved={(p) => {
            setEditing(null);
            setNotice(`Saved ${p.name}.`);
            products.reload();
          }}
        />
      )}
    </div>
  );
}

function ProductDialog({
  product,
  categories,
  onClose,
  onSaved,
}: {
  product: Product;
  categories: ProductCategory[];
  onClose: () => void;
  onSaved: (p: Product) => void;
}) {
  const [name, setName] = useState(product.name);
  const [categoryId, setCategoryId] = useState(product.category_id);
  const [subId, setSubId] = useState(product.subcategory_id ?? '');
  const [uom, setUom] = useState(product.uom);
  const [hsn, setHsn] = useState(product.hsn_code ?? '');
  const [active, setActive] = useState(product.is_active);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  // AMD-07: the Sub-Category list depends on the chosen Category.
  const subs = useSubcategories(categoryId);
  const subOptions = (subs.data ?? [])
    .filter((s) => s.is_active || s.id === product.subcategory_id)
    .map((s) => ({ value: s.id, label: s.is_active ? s.name : `${s.name} (inactive)` }));
  const categoryOptions = categories
    .filter((c) => c.is_active || c.id === product.category_id)
    .map((c) => ({ value: c.id, label: c.name }));

  const submit = async () => {
    setBusy(true);
    setError(null);
    const body: ProductUpdateInput = {
      name,
      category_id: categoryId,
      subcategory_id: subId || null,
      uom,
      hsn_code: hsn.trim() || null,
      is_active: active,
    };
    try {
      onSaved(await mastersApi.updateProduct(product.id, body));
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
    }
  };

  const fieldErrors = error?.fieldErrors ?? {};
  return (
    <Modal
      isOpen
      onClose={onClose}
      title={`Edit ${product.code}`}
      footer={
        <>
          <Button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            isLoading={busy}
            disabled={!name.trim() || !uom.trim()}
            onClick={() => {
              void submit();
            }}
          >
            Save
          </Button>
        </>
      }
    >
      <div className="masters-form">
        <label className="masters-field">
          <span className="form-label">
            Name<span className="required-star">*</span>
          </span>
          <Input
            id="product-name"
            value={name}
            maxLength={200}
            onChange={(e) => {
              setName(e.target.value);
            }}
          />
        </label>
        <label className="masters-field">
          <span className="form-label">
            Category<span className="required-star">*</span>
          </span>
          <Select
            id="product-category"
            value={categoryId}
            placeholder=""
            options={categoryOptions}
            onChange={(e) => {
              setCategoryId(e.target.value);
              setSubId(''); // a sub-category always belongs to its category (AMD-07)
            }}
          />
        </label>
        <label className="masters-field">
          <span className="form-label">Sub-Category</span>
          {subs.error ? (
            <ErrorState error={subs.error} onRetry={subs.reload} />
          ) : (
            <Select
              id="product-subcategory"
              value={subId}
              disabled={subs.loading}
              placeholder={subs.loading ? 'Loading…' : '(None)'}
              options={subOptions}
              error={fieldErrors.subcategory_id?.[0]}
              helperText={
                !subs.loading && subOptions.length === 0
                  ? 'This category has no sub-categories yet.'
                  : undefined
              }
              onChange={(e) => {
                setSubId(e.target.value);
              }}
            />
          )}
        </label>
        <div className="masters-form__pair">
          <label className="masters-field">
            <span className="form-label">
              UOM<span className="required-star">*</span>
            </span>
            <Input
              id="product-uom"
              value={uom}
              maxLength={20}
              onChange={(e) => {
                setUom(e.target.value);
              }}
            />
          </label>
          <label className="masters-field">
            <span className="form-label">HSN</span>
            <Input
              id="product-hsn"
              value={hsn}
              inputMode="numeric"
              maxLength={8}
              error={fieldErrors.hsn_code?.[0]}
              onChange={(e) => {
                setHsn(e.target.value.replace(/\D/g, ''));
              }}
            />
          </label>
        </div>
        <Checkbox
          id="product-active"
          label="Active"
          checked={active}
          onChange={(e) => {
            setActive(e.target.checked);
          }}
        />
        {error && <ErrorState error={error} title="Could not save" />}
      </div>
    </Modal>
  );
}
