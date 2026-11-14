import { apiRequest } from '@/lib/api/client';
import type {
  CountLine,
  CustodyLookups,
  HandoverPreview,
  ReconcileBody,
  StoreStock,
  TransferDetail,
  TransferNote,
  TransferPage,
} from './types';

export interface TransferFilters {
  status?: string;
  gs_id?: string;
  mine_to_accept?: boolean;
  page?: number;
}

export interface StockFilters {
  gs_id?: string;
  q?: string;
  condition_class?: string;
  routing_hint?: string;
}

const t = (id: string) => `/custody/transfers/${encodeURIComponent(id)}`;

/** Stock-moving commands carry an Idempotency-Key (G-16); a retry re-uses the same key. */
export const custodyApi = {
  lookups: () => apiRequest<CustodyLookups>('/custody/lookups'),
  list: (f: TransferFilters = {}) =>
    apiRequest<TransferPage>('/custody/transfers', {
      query: {
        status: f.status,
        gs_id: f.gs_id,
        mine_to_accept: f.mine_to_accept ? 'true' : undefined,
        page: f.page,
      },
    }),
  detail: (id: string) => apiRequest<TransferDetail>(t(id)),
  handoverPreview: (gsId: string) =>
    apiRequest<HandoverPreview>(`/gs/${encodeURIComponent(gsId)}/handover`),
  handover: (
    gsId: string,
    body: { lines?: Array<{ lot_id: string; qty: number }>; mode_code: string; notes?: string },
    idempotencyKey: string,
  ) =>
    apiRequest<TransferDetail>(`/gs/${encodeURIComponent(gsId)}/handover`, {
      method: 'POST',
      body,
      idempotencyKey,
    }),
  accept: (
    id: string,
    body: { lines: CountLine[]; acceptance_code: string; notes?: string | null },
    idempotencyKey: string,
  ) => apiRequest<TransferDetail>(`${t(id)}/accept`, { method: 'POST', body, idempotencyKey }),
  reconcile: (id: string, body: ReconcileBody, idempotencyKey: string) =>
    apiRequest<TransferDetail>(`${t(id)}/reconcile`, { method: 'POST', body, idempotencyKey }),
  approve: (id: string, reason: string, idempotencyKey: string) =>
    apiRequest<TransferDetail>(`${t(id)}/reconcile/approve`, {
      method: 'POST',
      body: { reason },
      idempotencyKey,
    }),
  cancel: (id: string, reason: string, idempotencyKey: string) =>
    apiRequest<TransferDetail>(`${t(id)}/cancel`, {
      method: 'POST',
      body: { reason },
      idempotencyKey,
    }),
  transferNote: (id: string) => apiRequest<TransferNote>(`${t(id)}/transfer-note`),
  /** Logs the print (print_logs) and returns the note with its reprint watermark. */
  printTransferNote: (id: string) =>
    apiRequest<TransferNote>(`${t(id)}/transfer-note/print`, { method: 'POST' }),
  storeStock: (f: StockFilters = {}) =>
    apiRequest<StoreStock>('/custody/intermediate-store/stock', {
      query: {
        gs_id: f.gs_id,
        q: f.q,
        condition_class: f.condition_class,
        routing_hint: f.routing_hint,
      },
    }),
  classify: (lotId: string, qty: number, remarks: string | null, idempotencyKey: string) =>
    apiRequest<unknown>(`/custody/lots/${encodeURIComponent(lotId)}/classify`, {
      method: 'POST',
      body: { qty, remarks },
      idempotencyKey,
    }),
  /** DEC-27 packaging check (P2-04 endpoint) on a lot received in the Intermediate Store. */
  packagingCheck: (
    lotId: string,
    body: { result: 'OK' | 'REPLACED'; qty_replaced: number; remarks: string | null },
    idempotencyKey: string,
  ) =>
    apiRequest<unknown>(`/lots/${encodeURIComponent(lotId)}/packaging-check`, {
      method: 'POST',
      body,
      idempotencyKey,
    }),
};
