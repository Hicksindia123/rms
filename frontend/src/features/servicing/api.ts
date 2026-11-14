import { apiRequest } from '@/lib/api/client';
import type {
  AllotBatchPayload,
  BatchDetail,
  BatchSummary,
  BatteryReconciliation,
  IntermediateLot,
  ReceiveBatchPayload,
  Technician,
} from './types';

export const servicingApi = {
  getTechnicians: () => apiRequest<Technician[]>('/servicing/technicians'),

  getIntermediateLots: () => apiRequest<IntermediateLot[]>('/servicing/intermediate-lots'),

  listBatches: (params?: {
    status?: string | undefined;
    technician_id?: string | undefined;
    page?: number | undefined;
    page_size?: number | undefined;
  }) =>
    apiRequest<BatchSummary[]>('/servicing/batches', {
      query: {
        status: params?.status,
        technician_id: params?.technician_id,
        page: params?.page,
        page_size: params?.page_size,
      },
    }),

  getBatch: (id: string) => apiRequest<BatchDetail>(`/servicing/batches/${encodeURIComponent(id)}`),

  allotBatch: (payload: AllotBatchPayload, idempotencyKey: string) =>
    apiRequest<BatchDetail>('/servicing/batches', {
      method: 'POST',
      idempotencyKey,
      body: payload,
    }),

  receiveBatch: (batchId: string, payload: ReceiveBatchPayload, idempotencyKey: string) =>
    apiRequest<BatchDetail>(`/servicing/batches/${encodeURIComponent(batchId)}/receive`, {
      method: 'POST',
      idempotencyKey,
      body: payload,
    }),

  getBatteryReconciliation: (params?: { from?: string | undefined; to?: string | undefined }) =>
    apiRequest<BatteryReconciliation>('/servicing/battery-reconciliation', {
      query: {
        from: params?.from,
        to: params?.to,
      },
    }),
};
