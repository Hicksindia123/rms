import { apiRequest } from '@/lib/api/client';

import type {
  ManagementLineIn,
  StoreAnalysisGs,
  StoreAnalysisQueueRow,
  StoreAnalysisSubmitIn,
} from './types';

const gsPath = (gsId: string) => `/store-analysis/gs/${encodeURIComponent(gsId)}`;

/** Phase P9 (DEC-69). All business data flows through FastAPI (rule h). */
export const storeAnalysisApi = {
  /** Goods slips in the analysis stage (a store user: its own stores only). */
  getQueue: (pendingOnly: boolean) =>
    apiRequest<StoreAnalysisQueueRow[]>(
      `/store-analysis/queue?pending_only=${pendingOnly ? 'true' : 'false'}`,
    ),

  getGs: (gsId: string) => apiRequest<StoreAnalysisGs>(gsPath(gsId)),

  /** Submit the store's part (every item + condition, G-21). Idempotency-Key (G-16). */
  submit: (gsId: string, body: StoreAnalysisSubmitIn, idempotencyKey: string) =>
    apiRequest<StoreAnalysisGs>(`${gsPath(gsId)}/submit`, {
      method: 'POST',
      body,
      idempotencyKey,
    }),

  /** DEC-75: send selected pieces (item + qty + proposal) for Management approval. */
  sendToManagement: (
    gsId: string,
    lines: ManagementLineIn[],
    reason: string | null,
    idempotencyKey: string,
  ) =>
    apiRequest<StoreAnalysisGs>(`${gsPath(gsId)}/management-approval`, {
      method: 'POST',
      body: { lines, reason },
      idempotencyKey,
    }),
};
