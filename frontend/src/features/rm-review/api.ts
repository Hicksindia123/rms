import { apiRequest } from '@/lib/api/client';
import type { RmApprovePayload, RmApproveResult, RmReviewData, RmSendBackPayload } from './types';

const gs = (id: string) => `/gs/${encodeURIComponent(id)}`;

export const rmReviewApi = {
  getReviewData: (gsId: string) => apiRequest<RmReviewData>(`${gs(gsId)}/rm-review`),

  // DEC-64 (Q9): the RM's edits (edit / add / remove line, change product) are retired.

  sendBack: (gsId: string, body: RmSendBackPayload, idempotencyKey: string) =>
    apiRequest<{ gs_id: string; status: string; remarks: string }>(`${gs(gsId)}/rm-send-back`, {
      method: 'POST',
      body,
      idempotencyKey,
    }),

  approve: (gsId: string, body: RmApprovePayload, idempotencyKey: string) =>
    apiRequest<RmApproveResult>(`${gs(gsId)}/rm-approve`, {
      method: 'POST',
      body,
      idempotencyKey,
    }),
};
