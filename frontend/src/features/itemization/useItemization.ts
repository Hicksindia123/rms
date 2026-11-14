import { useCallback } from 'react';

import { useApiQuery } from '@/hooks/useApiQuery';

import { itemizationApi, type ItemizationState } from './api';

/** Statuses from which a GS has Step-3 item lines worth loading (itemisation onwards). */
export const ITEMS_VISIBLE = new Set([
  'ITEMIZATION',
  'CATEGORISATION', // AMD-08 (change plan Phase 3)
  'CSR_APPROVAL_PENDING',
  'INSPECTION',
  'RM_REVIEW',
  'IN_PROCESS',
  'COMMERCIAL_RESOLUTION',
  'AWAITING_NOTIFICATION',
  'CLOSED',
]);

export function useItemization(gsId: string, enabled: boolean) {
  const fetcher = useCallback(
    () => (enabled ? itemizationApi.state(gsId) : Promise.resolve(null)),
    [gsId, enabled],
  );
  return useApiQuery<ItemizationState | null>(fetcher);
}
