import { apiRequest } from '@/lib/api/client';
import type {
  RmApprovePayload,
  RmApproveResult,
  RmEditItemPayload,
  RmReviewData,
  RmReviewItem,
  RmSendBackPayload,
} from './types';

const gs = (id: string) => `/gs/${encodeURIComponent(id)}`;

export const rmReviewApi = {
  getReviewData: (gsId: string) => apiRequest<RmReviewData>(`${gs(gsId)}/rm-review`),

  editItem: (gsId: string, itemId: string, body: RmEditItemPayload, idempotencyKey: string) =>
    apiRequest<RmReviewItem>(`${gs(gsId)}/items/${encodeURIComponent(itemId)}/rm-edit`, {
      method: 'PUT',
      body,
      idempotencyKey,
    }),

  sendBack: (gsId: string, body: RmSendBackPayload, idempotencyKey: string) =>
    apiRequest<{ gs_id: string; status: string; remarks: string }>(
      `${gs(gsId)}/rm-send-back`,
      {
        method: 'POST',
        body,
        idempotencyKey,
      },
    ),

  approve: (gsId: string, body: RmApprovePayload, idempotencyKey: string) =>
    apiRequest<RmApproveResult>(`${gs(gsId)}/rm-approve`, {
      method: 'POST',
      body,
      idempotencyKey,
    }),
};
