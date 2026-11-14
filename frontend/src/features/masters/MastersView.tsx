import { useCallback, useState } from 'react';

import { ErrorState, LoadingState } from '@/components/ui';
import { useAuth } from '@/features/auth/useAuth';
import { useApiQuery } from '@/hooks/useApiQuery';

import { mastersApi } from './api';
import { CategoriesPanel } from './CategoriesPanel';
import { ProductImportPanel } from './ProductImportPanel';
import { ProductsPanel } from './ProductsPanel';
import { SubCategoriesPanel } from './SubCategoriesPanel';

type Tab = 'categories' | 'subcategories' | 'products' | 'import';

/**
 * Product masters (change plan 2026-11-12 Phase 1, AMD-07): Category -> Sub-Category -> Product.
 * Every value shown comes from the masters API; category guard flags are read-only here.
 */
export function MastersView() {
  const { can, me } = useAuth();
  const isSuperAdmin = me?.profile.is_super_admin ?? false;
  const canCreate = isSuperAdmin || can('masters', 'create');
  const canEdit = isSuperAdmin || can('masters', 'edit');
  const [tab, setTab] = useState<Tab>('products');

  const fetchCategories = useCallback(() => mastersApi.categories(), []);
  const categories = useApiQuery(fetchCategories);

  const tabs: Array<{ id: Tab; label: string }> = [
    { id: 'products', label: 'Products' },
    { id: 'subcategories', label: 'Sub-Categories' },
    { id: 'categories', label: 'Categories' },
    ...(canCreate ? [{ id: 'import' as const, label: 'Import CSV' }] : []),
  ];

  return (
    <div className="masters">
      <header>
        <h1 className="masters__title">Product Masters</h1>
        <p className="masters__subtitle">Category → Sub-Category → Product</p>
      </header>

      <div className="tabs tabs--wrap" role="tablist" aria-label="Product masters">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            className="tabs__tab"
            aria-selected={tab === t.id}
            onClick={() => {
              setTab(t.id);
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* A background reload (after a save) keeps the panels mounted so their success notice stays. */}
      {categories.error ? (
        <ErrorState error={categories.error} onRetry={categories.reload} />
      ) : !categories.data ? (
        <LoadingState label="Loading categories…" />
      ) : (
        <div role="tabpanel">
          {tab === 'categories' && <CategoriesPanel categories={categories.data} />}
          {tab === 'subcategories' && (
            <SubCategoriesPanel
              categories={categories.data}
              canCreate={canCreate}
              canEdit={canEdit}
              onChanged={categories.reload}
            />
          )}
          {tab === 'products' && <ProductsPanel categories={categories.data} canEdit={canEdit} />}
          {tab === 'import' && canCreate && <ProductImportPanel onApplied={categories.reload} />}
        </div>
      )}
    </div>
  );
}
