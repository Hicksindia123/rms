import { useCallback } from 'react';
import { useApiQuery } from '@/hooks/useApiQuery';
import { inspectionApi } from './api';
import type { InspectionGsOut } from './types';

/** Statuses where inspection data can be viewed (INSPECTION onwards). */
export const INSPECTION_VISIBLE = new Set([
  'INSPECTION',
  'RM_REVIEW',
  'IN_PROCESS',
  'COMMERCIAL_RESOLUTION',
  'AWAITING_NOTIFICATION',
  'CLOSED',
]);

export function useInspection(gsId: string, enabled: boolean) {
  const fetcher = useCallback(
    () => (enabled ? inspectionApi.getGsInspection(gsId) : Promise.resolve(null)),
    [gsId, enabled],
  );
  return useApiQuery<InspectionGsOut | null>(fetcher);
}
