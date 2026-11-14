import { useCallback, useState } from 'react';
import { Plus } from 'lucide-react';

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
import { newIdempotencyKey, toApiError, type ApiError } from '@/lib/api/client';

import { mastersApi, type ProductCategory, type ProductSubCategory } from './api';

interface Props {
  categories: ProductCategory[];
  canCreate: boolean;
  canEdit: boolean;
  onChanged: () => void;
}

type Editing = { mode: 'create' } | { mode: 'edit'; sub: ProductSubCategory };

/** AMD-07: sub-category CRUD. The code and the parent category are immutable once created. */
export function SubCategoriesPanel({ categories, canCreate, canEdit, onChanged }: Props) {
  const [categoryId, setCategoryId] = useState('');
  const [showInactive, setShowInactive] = useState(false);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const fetchSubs = useCallback(
    () => mastersApi.subcategories(categoryId || null, showInactive),
    [categoryId, showInactive],
  );
  const subs = useApiQuery(fetchSubs);

  const saved = (msg: string) => {
    setEditing(null);
    setNotice(msg);
    subs.reload();
    onChanged();
  };

  return (
    <div className="masters-panel">
      <div className="filters">
        <label className="masters-field">
          <span className="form-label">Category</span>
          <Select
            id="sub-filter-category"
            value={categoryId}
            placeholder="All categories"
            options={categories.map((c) => ({ value: c.id, label: c.name }))}
            onChange={(e) => {
              setCategoryId(e.target.value);
            }}
          />
        </label>
        <div className="masters-field masters-field--check">
          <Checkbox
            id="sub-show-inactive"
            label="Show inactive"
            checked={showInactive}
            onChange={(e) => {
              setShowInactive(e.target.checked);
            }}
          />
        </div>
        {canCreate && (
          <div className="masters-field masters-field--action">
            <Button
              type="button"
              variant="primary"
              onClick={() => {
                setNotice(null);
                setEditing({ mode: 'create' });
              }}
            >
              <Plus size={16} aria-hidden="true" /> Add sub-category
            </Button>
          </div>
        )}
      </div>

      {notice && (
        <p className="masters-notice" role="status">
          {notice}
        </p>
      )}

      {subs.error ? (
        <ErrorState error={subs.error} onRetry={subs.reload} />
      ) : subs.loading || !subs.data ? (
        <LoadingState label="Loading sub-categories…" />
      ) : subs.data.length === 0 ? (
        <EmptyState
          title="No sub-categories yet"
          hint={
            canCreate
              ? 'Add one here, or import a CSV with a Sub-Category column.'
              : 'An administrator can add sub-categories.'
          }
        />
      ) : (
        <ul className="masters-list">
          {subs.data.map((s) => (
            <li key={s.id} className="masters-row">
              <div className="masters-row__main">
                <div className="masters-row__title">
                  <span>{s.name}</span>
                  <Badge variant="info">{s.code}</Badge>
                  {!s.is_active && <Badge variant="neutral">Inactive</Badge>}
                </div>
                <div className="masters-row__meta">
                  {s.category_name} · {s.product_count} products
                </div>
              </div>
              {canEdit && (
                <Button
                  type="button"
                  size="sm"
                  className="masters-row__action"
                  onClick={() => {
                    setNotice(null);
                    setEditing({ mode: 'edit', sub: s });
                  }}
                >
                  Edit
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}

      {editing && (
        <SubCategoryDialog
          editing={editing}
          categories={categories.filter((c) => c.is_active)}
          defaultCategoryId={categoryId}
          onClose={() => {
            setEditing(null);
          }}
          onSaved={saved}
        />
      )}
    </div>
  );
}

function SubCategoryDialog({
  editing,
  categories,
  defaultCategoryId,
  onClose,
  onSaved,
}: {
  editing: Editing;
  categories: ProductCategory[];
  defaultCategoryId: string;
  onClose: () => void;
  onSaved: (msg: string) => void;
}) {
  const sub = editing.mode === 'edit' ? editing.sub : null;
  const [categoryId, setCategoryId] = useState(sub?.category_id ?? defaultCategoryId);
  const [name, setName] = useState(sub?.name ?? '');
  const [code, setCode] = useState('');
  const [active, setActive] = useState(sub?.is_active ?? true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  // One key per dialog: a double submit or a retry after a network error is not applied twice (G-16).
  const [idemKey] = useState(newIdempotencyKey);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      if (sub) {
        const out = await mastersApi.updateSubcategory(sub.id, { name, is_active: active });
        onSaved(`Saved ${out.name}.`);
      } else {
        const out = await mastersApi.createSubcategory(
          { category_id: categoryId, name, ...(code.trim() ? { code: code.trim() } : {}) },
          idemKey,
        );
        onSaved(`Added ${out.name} (${out.code}) under ${out.category_name}.`);
      }
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusy(false);
    }
  };

  const valid = name.trim().length > 0 && (sub !== null || categoryId !== '');
  return (
    <Modal
      isOpen
      onClose={onClose}
      title={sub ? `Edit sub-category ${sub.code}` : 'Add sub-category'}
      footer={
        <>
          <Button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            isLoading={busy}
            disabled={!valid}
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
        {sub ? (
          <p className="masters-row__meta">
            Category: <strong>{sub.category_name}</strong> · Code: <strong>{sub.code}</strong>{' '}
            (cannot be changed)
          </p>
        ) : (
          <label className="masters-field">
            <span className="form-label">
              Category<span className="required-star">*</span>
            </span>
            <Select
              id="sub-category"
              value={categoryId}
              options={categories.map((c) => ({ value: c.id, label: c.name }))}
              onChange={(e) => {
                setCategoryId(e.target.value);
              }}
            />
          </label>
        )}
        <label className="masters-field">
          <span className="form-label">
            Name<span className="required-star">*</span>
          </span>
          <Input
            id="sub-name"
            value={name}
            maxLength={200}
            onChange={(e) => {
              setName(e.target.value);
            }}
          />
        </label>
        {!sub && (
          <label className="masters-field">
            <span className="form-label">Code (optional)</span>
            <Input
              id="sub-code"
              value={code}
              maxLength={50}
              helperText="A–Z, 0–9, _. Leave blank to derive it from the name. Cannot be changed later."
              onChange={(e) => {
                setCode(e.target.value.toUpperCase());
              }}
            />
          </label>
        )}
        {sub && (
          <Checkbox
            id="sub-active"
            label="Active"
            checked={active}
            onChange={(e) => {
              setActive(e.target.checked);
            }}
          />
        )}
        {error && <ErrorState error={error} title="Could not save" />}
      </div>
    </Modal>
  );
}
