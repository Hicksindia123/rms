/**
 * DEC-69 (Phase P9): how one Intermediate Store's analysis of a goods slip is shown. The states are
 * computed by the system (rms_private.gs_store_analysis_progress), not configurable options.
 */
import { Badge, type BadgeVariant } from '@/components/ui';

import type { StoreAnalysisStore } from './types';

const ROUTING_TEXT: Record<string, string> = {
  AWAITING_ACKNOWLEDGEMENT: 'awaiting acknowledgement',
  ROUTING_PENDING: 'routing pending',
  AT_DEPARTMENTS: 'at departments',
  READY_FOR_ANALYSIS: 'ready',
};

function analysisText(s: StoreAnalysisStore): string {
  if (s.analysis_status === 'SUBMITTED') return 'Analysis submitted';
  if (s.analysis_status === 'PENDING') return 'Ready for analysis';
  return `Not ready (${ROUTING_TEXT[s.routing_status] ?? s.routing_status})`;
}

const VARIANT: Record<StoreAnalysisStore['analysis_status'], BadgeVariant> = {
  NOT_READY: 'neutral',
  PENDING: 'warning',
  SUBMITTED: 'success',
};

export function StoreAnalysisChip({ s }: { s: StoreAnalysisStore }) {
  return (
    <Badge variant={VARIANT[s.analysis_status]}>
      {s.store_code}: {analysisText(s)}
    </Badge>
  );
}
