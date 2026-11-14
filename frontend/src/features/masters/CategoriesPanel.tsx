import { Badge, EmptyState } from '@/components/ui';

import type { ProductCategory } from './api';

/** Categories with their guard-relevant flags (G-05 hazard, G-06 full opening): read-only here. */
export function CategoriesPanel({ categories }: { categories: ProductCategory[] }) {
  if (categories.length === 0) {
    return <EmptyState title="No product categories" hint="Categories are created by seed.sql." />;
  }
  return (
    <ul className="masters-list">
      {categories.map((c) => (
        <li key={c.id} className="masters-row">
          <div className="masters-row__main">
            <div className="masters-row__title">
              <span>{c.name}</span>
              <Badge variant="info">{c.code}</Badge>
              {!c.is_active && <Badge variant="neutral">Inactive</Badge>}
            </div>
            <div className="masters-row__meta">
              {c.subcategory_count} sub-categories · {c.product_count} products
            </div>
            <div className="masters-row__badges">
              {c.hazard_capable && <Badge variant="warning">Hazard capable (G-05)</Badge>}
              {c.requires_full_opening && <Badge variant="warning">Full opening (G-06)</Badge>}
              {c.supports_battery && <Badge variant="default">Battery</Badge>}
              {c.supports_dismantling && <Badge variant="default">Dismantling</Badge>}
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}
