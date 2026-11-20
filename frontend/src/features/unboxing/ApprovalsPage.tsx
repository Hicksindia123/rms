import { useCallback } from 'react';

import { EmptyState, ErrorState, LoadingState } from '@/components/ui';
import { useAuth } from '@/features/auth/useAuth';
import {
  itemizationApi,
  type CsrApprovalCardData,
  type LineCorrection,
} from '@/features/itemization/api';
import { CorrectionDecisionCard, CsrDecisionCard } from '@/features/itemization/DecisionCards';
import { useApiQuery } from '@/hooks/useApiQuery';

interface Inbox {
  csr: CsrApprovalCardData[];
  corrections: LineCorrection[];
}

/**
 * Replacement Manager inbox (mobile approval cards): Complete Sales Returns (G-03, P2-04) and item
 * line corrections (P2-04), each section only for the permission that decides it. The Missing
 * Document Exception section was removed by DEC-63 (user Q8, 2026-11-20).
 */
export function ApprovalsPage({
  onOpenItemization,
}: {
  onOpenItemization: (gsId: string) => void;
}) {
  const { can } = useAuth();
  const canItemization = can('itemization', 'approve');
  const fetcher = useCallback(async (): Promise<Inbox> => {
    const [csr, corrections] = await Promise.all([
      canItemization ? itemizationApi.pendingCsr() : Promise.resolve([]),
      canItemization ? itemizationApi.pendingCorrections() : Promise.resolve([]),
    ]);
    return { csr, corrections };
  }, [canItemization]);
  const query = useApiQuery<Inbox>(fetcher);
  const data = query.data;
  const empty = !!data && data.csr.length + data.corrections.length === 0;

  return (
    <div className="page page--narrow">
      <h1 className="page__title">Approvals</h1>
      <p className="page__subtitle">Decisions waiting for you.</p>
      {query.error ? (
        <ErrorState error={query.error} onRetry={query.reload} />
      ) : query.loading && !data ? (
        <LoadingState />
      ) : !data || empty ? (
        <EmptyState title="Nothing to approve" hint="New requests also arrive in the bell." />
      ) : (
        <div className="approval-list">
          {data.csr.length > 0 ? (
            <section aria-labelledby="appr-csr">
              <h2 id="appr-csr" className="unboxing__h2">
                Complete Sales Returns ({data.csr.length})
              </h2>
              {data.csr.map((c) => (
                <CsrDecisionCard
                  key={c.goods_slip.id}
                  goodsSlip={c.goods_slip}
                  items={c.items}
                  totals={c.totals}
                  categoryLabel={c.category_label}
                  categorizedBy={c.categorized_by_name}
                  evidence={c.evidence}
                  options={c.decision_options}
                  onDecided={query.reload}
                  onOpenGs={onOpenItemization}
                />
              ))}
            </section>
          ) : null}
          {data.corrections.length > 0 ? (
            <section aria-labelledby="appr-corr">
              <h2 id="appr-corr" className="unboxing__h2">
                Item line corrections ({data.corrections.length})
              </h2>
              {data.corrections.map((c) => (
                <CorrectionDecisionCard
                  key={c.id}
                  correction={c}
                  onDecided={query.reload}
                  onOpenGs={onOpenItemization}
                />
              ))}
            </section>
          ) : null}
        </div>
      )}
    </div>
  );
}
