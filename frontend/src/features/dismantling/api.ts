import { apiRequest } from '@/lib/api/client';
import type {
  DismantleBatchCreatePayload,
  DismantleBatchDetail,
  DismantleBatchSummary,
  DismantleQueueResponse,
  DismantleRecoveryPayload,
  PcbModel,
  PcbSupplier,
  ScrapDisposePayload,
  ScrapFromLotPayload,
  ScrapRecord,
  StorageContainer,
} from './types';

export const dismantlingApi = {
  getQueue: () => apiRequest<DismantleQueueResponse>('/dismantling/queue'),

  listBatches: (params?: {
    status?: string | undefined;
    technician_profile_id?: string | undefined;
    page?: number | undefined;
    page_size?: number | undefined;
  }) =>
    apiRequest<DismantleBatchSummary[]>('/dismantling/batches', {
      query: {
        status: params?.status,
        technician_profile_id: params?.technician_profile_id,
        page: params?.page,
        page_size: params?.page_size,
      },
    }),

  getBatch: (id: string) =>
    apiRequest<DismantleBatchDetail>(`/dismantling/batches/${encodeURIComponent(id)}`),

  createBatch: (payload: DismantleBatchCreatePayload, idempotencyKey: string) =>
    apiRequest<DismantleBatchDetail>('/dismantling/batches', {
      method: 'POST',
      idempotencyKey,
      body: payload,
    }),

  recoverBatch: (batchId: string, payload: DismantleRecoveryPayload, idempotencyKey: string) =>
    apiRequest<DismantleBatchDetail>(
      `/dismantling/batches/${encodeURIComponent(batchId)}/recover`,
      {
        method: 'POST',
        idempotencyKey,
        body: payload,
      },
    ),

  listContainers: (params?: { storage_method?: string; part_type?: string }) =>
    apiRequest<StorageContainer[]>('/dismantling/containers', {
      query: {
        storage_method: params?.storage_method,
        part_type: params?.part_type,
      },
    }),

  listPcbModels: () => apiRequest<PcbModel[]>('/dismantling/pcb-models'),

  createPcbModel: (payload: { name: string; supplier_id: string; is_active?: boolean }) =>
    apiRequest<PcbModel>('/dismantling/pcb-models', {
      method: 'POST',
      body: payload,
    }),

  listPcbSuppliers: () => apiRequest<PcbSupplier[]>('/dismantling/pcb-suppliers'),

  createPcbSupplier: (payload: { name: string; is_active?: boolean }) =>
    apiRequest<PcbSupplier>('/dismantling/pcb-suppliers', {
      method: 'POST',
      body: payload,
    }),

  listScrap: (params?: {
    batch_id?: string | undefined;
    disposal_status?: string | undefined;
    page?: number | undefined;
    page_size?: number | undefined;
  }) =>
    apiRequest<ScrapRecord[]>('/scrap', {
      query: {
        batch_id: params?.batch_id,
        disposal_status: params?.disposal_status,
        page: params?.page,
        page_size: params?.page_size,
      },
    }),

  /** Quarantined hazard stock (G-05) the Spare Parts Manager may dispose (DEC-11). */
  listHazardQuarantine: () =>
    apiRequest<{
      items: {
        lot_id: string;
        gs_no?: string | null;
        product_name?: string | null;
        condition_class: string;
        location_code: string;
        qty: number;
      }[];
    }>('/inventory/stock', { query: { view: 'HAZARD_QUARANTINE', page_size: 100 } }),

  /** DEC-11 / DEC-18: mark quarantined or non-dismantleable stock as scrap. */
  markLotForDisposal: (payload: ScrapFromLotPayload, idempotencyKey: string) =>
    apiRequest<ScrapRecord>('/scrap/from-lot', {
      method: 'POST',
      idempotencyKey,
      body: payload,
    }),

  disposeScrap: (id: string, payload: ScrapDisposePayload, idempotencyKey: string) =>
    apiRequest<ScrapRecord>(`/scrap/${encodeURIComponent(id)}/dispose`, {
      method: 'POST',
      idempotencyKey,
      body: payload,
    }),
};
