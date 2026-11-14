import { EmptyState, ErrorState, LoadingState } from '@/components/ui';

import type { ItemizationState } from './api';
import { ItemLineCard } from './LineParts';

/** GS detail → Items tab (read-only lines with short / excess and stocked quantities). */
export function ItemsTab({
  state,
  error,
  loading,
  onRetry,
}: {
  state: ItemizationState | null;
  error: Parameters<typeof ErrorState>[0]['error'] | null;
  loading: boolean;
  onRetry: () => void;
}) {
  if (error) return <ErrorState error={error} onRetry={onRetry} />;
  if (loading && !state) return <LoadingState />;
  if (!state || state.items.length === 0) return <EmptyState title="No item lines yet" />;
  return (
    <div>
      <p className="page__subtitle">
        {state.category_label ? `${state.category_label} · ` : ''}
        {state.totals.lines} line(s) · received {state.totals.received_qty} of{' '}
        {state.totals.documented_qty} as per document
      </p>
      <ul className="item-lines">
        {state.items.map((i) => (
          <ItemLineCard key={i.id} item={i} />
        ))}
      </ul>
    </div>
  );
}
