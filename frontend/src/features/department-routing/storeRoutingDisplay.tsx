/**
 * DEC-67 (Phase P7): how one Intermediate Store's part of a goods slip is shown. The four states
 * are computed by the system (rms_private.gs_store_routing_progress), not configurable options.
 */
import { Badge, type BadgeVariant } from '@/components/ui';

import type { StoreProgress, StoreRoutingStatus } from './types';

const TEXT: Record<StoreRoutingStatus, string> = {
  AWAITING_ACKNOWLEDGEMENT: 'Awaiting acknowledgement',
  ROUTING_PENDING: 'Routing pending',
  AT_DEPARTMENTS: 'At departments',
  READY_FOR_ANALYSIS: 'Ready for analysis',
};

const VARIANT: Record<StoreRoutingStatus, BadgeVariant> = {
  AWAITING_ACKNOWLEDGEMENT: 'neutral',
  ROUTING_PENDING: 'warning',
  AT_DEPARTMENTS: 'info',
  READY_FOR_ANALYSIS: 'success',
};

export function StoreProgressChip({ p }: { p: StoreProgress }) {
  return (
    <Badge variant={VARIANT[p.status]}>
      {p.store_code}: {TEXT[p.status]}
      {p.status === 'ROUTING_PENDING' ? ` (${String(p.unrouted_qty)} pcs)` : ''}
    </Badge>
  );
}
