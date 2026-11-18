import { apiRequest } from '@/lib/api/client';
import type {
  RmAddLinePayload,
  RmApprovePayload,
  RmApproveResult,
  RmChangeProductPayload,
  RmEditItemPayload,
  RmRemoveLinePayload,
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

  addLine: (gsId: string, body: RmAddLinePayload, idempotencyKey: string) =>
    apiRequest<{ goods_slip_id: string; item_id: string; revision_no: number; status: string }>(
      `${gs(gsId)}/rm-add-line`,
      {
        method: 'POST',
        body,
        idempotencyKey,
      },
    ),

  removeLine: (gsId: string, itemId: string, body: RmRemoveLinePayload, idempotencyKey: string) =>
    apiRequest<{ goods_slip_id: string; item_id: string; revision_no: number; status: string }>(
      `${gs(gsId)}/items/${encodeURIComponent(itemId)}/rm-remove-line`,
      {
        method: 'POST',
        body,
        idempotencyKey,
      },
    ),

  changeProduct: (
    gsId: string,
    itemId: string,
    body: RmChangeProductPayload,
    idempotencyKey: string,
  ) =>
    apiRequest<{ goods_slip_id: string; item_id: string; revision_no: number; status: string }>(
      `${gs(gsId)}/items/${encodeURIComponent(itemId)}/rm-change-product`,
      {
        method: 'POST',
        body,
        idempotencyKey,
      },
    ),

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
