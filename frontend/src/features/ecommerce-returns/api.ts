import { apiRequest } from '@/lib/api/client';

import type {
  CreatePayload,
  CreateResult,
  EcomReturn,
  FormConfig,
  Media,
  MediaIn,
  MediaKind,
  MediaUpload,
  OrderMatch,
  PortalCheckQueue,
  ProductLookup,
  ResolutionIn,
  FollowUpIn,
  UnboxingQueue,
  UnboxLineIn,
  ActionSheet,
  ActionSheetList,
  RepairReturnIn,
  ReturnSettlement,
  SheetStatus,
  StoreReceipts,
  CompleteSheetIn,
  ReturnList,
  ReturnStatus,
  TicketQueue,
  TicketResponseIn,
} from './types';

const base = '/ecommerce-returns';
const one = (id: string) => `${base}/${encodeURIComponent(id)}`;
const media = (id: string, mediaId: string) => `${one(id)}/media/${encodeURIComponent(mediaId)}`;
const ticket = (id: string) => `/ecommerce-tickets/${encodeURIComponent(id)}`;

/** DEC-73. All business data flows through FastAPI (rule h). */
export const ecomApi = {
  formConfig: () => apiRequest<FormConfig>(`${base}/form-config`),
  products: (q: string) =>
    apiRequest<ProductLookup[]>(`${base}/lookups/products`, { query: { q: q.trim() || null } }),
  orderCheck: (platformCode: string, orderId: string) =>
    apiRequest<OrderMatch[]>(`${base}/order-check`, {
      query: { platform_code: platformCode, order_id: orderId },
    }),

  /** DRAFT + one signed upload per file. Idempotency-Key (G-16 pattern). */
  create: (payload: CreatePayload, idempotencyKey: string) =>
    apiRequest<CreateResult>(base, { method: 'POST', body: payload, idempotencyKey }),
  addMedia: (id: string, kind: MediaKind, file: MediaIn) =>
    apiRequest<MediaUpload>(`${one(id)}/media`, {
      method: 'POST',
      body: file,
      query: { kind },
    }),
  uploadUrl: (id: string, mediaId: string) =>
    apiRequest<MediaUpload>(`${media(id, mediaId)}/upload-url`, { method: 'POST' }),
  confirm: (id: string, mediaId: string, objectPath: string) =>
    apiRequest<Media>(`${media(id, mediaId)}/confirm`, {
      method: 'POST',
      body: { object_path: objectPath },
    }),
  discard: (id: string, mediaId: string) =>
    apiRequest<Media>(`${media(id, mediaId)}/discard`, { method: 'POST' }),
  submit: (id: string, idempotencyKey: string) =>
    apiRequest<EcomReturn>(`${one(id)}/submit`, { method: 'POST', idempotencyKey }),

  list: (q: string, status: ReturnStatus | '') =>
    apiRequest<ReturnList>(base, { query: { q: q.trim() || null, status: status || null } }),
  get: (id: string) => apiRequest<EcomReturn>(one(id)),
  downloadUrl: (mediaId: string) =>
    apiRequest<{ url: string; expires_in: number; mime_type: string }>(
      `${base}/media/${encodeURIComponent(mediaId)}/download-url`,
    ),
  void: (id: string, reason: string, idempotencyKey: string) =>
    apiRequest<EcomReturn>(`${one(id)}/void`, {
      method: 'POST',
      body: { reason },
      idempotencyKey,
    }),

  tickets: (state: 'OPEN' | 'CLOSED' | 'ALL') =>
    apiRequest<TicketQueue>('/ecommerce-tickets', { query: { state } }),
  raise: (ticketId: string, idempotencyKey: string) =>
    apiRequest<EcomReturn>(`${ticket(ticketId)}/raise`, { method: 'POST', idempotencyKey }),
  respond: (ticketId: string, body: TicketResponseIn, idempotencyKey: string) =>
    apiRequest<EcomReturn>(`${ticket(ticketId)}/response`, {
      method: 'POST',
      body,
      idempotencyKey,
    }),
  /** DEC-76: closing carries the portal resolution (Free Replacement / Refund + qty). */
  close: (ticketId: string, body: ResolutionIn, idempotencyKey: string) =>
    apiRequest<EcomReturn>(`${ticket(ticketId)}/close`, {
      method: 'POST',
      body,
      idempotencyKey,
    }),
  followUp: (ticketId: string, body: FollowUpIn, idempotencyKey: string) =>
    apiRequest<EcomReturn>(`${ticket(ticketId)}/follow-up`, {
      method: 'POST',
      body,
      idempotencyKey,
    }),
  portalChecks: () => apiRequest<PortalCheckQueue>('/ecommerce-tickets/portal-checks'),
  portalCheck: (returnId: string, body: ResolutionIn, idempotencyKey: string) =>
    apiRequest<EcomReturn>(`/ecommerce-tickets/portal-checks/${encodeURIComponent(returnId)}`, {
      method: 'POST',
      body,
      idempotencyKey,
    }),
};

const settle = '/ecommerce-settlement';

/** DEC-76: unboxing, store receipts and action sheets. */
export const settlementApi = {
  unboxing: () => apiRequest<UnboxingQueue>(`${settle}/unboxing`),
  unbox: (platformCode: string, lines: UnboxLineIn[], idempotencyKey: string) =>
    apiRequest<ActionSheet>(`${settle}/unboxing`, {
      method: 'POST',
      body: { platform_code: platformCode, lines },
      idempotencyKey,
    }),
  repairReturn: (repairId: string, body: RepairReturnIn, idempotencyKey: string) =>
    apiRequest<ReturnSettlement>(`${settle}/repairs/${encodeURIComponent(repairId)}/return`, {
      method: 'POST',
      body,
      idempotencyKey,
    }),
  receipts: (state: 'PENDING' | 'ACKNOWLEDGED' | 'ALL') =>
    apiRequest<StoreReceipts>(`${settle}/store-receipts`, { query: { state } }),
  acknowledge: (receiptIds: string[], idempotencyKey: string) =>
    apiRequest<StoreReceipts>(`${settle}/store-receipts/acknowledge`, {
      method: 'POST',
      body: { receipt_ids: receiptIds },
      idempotencyKey,
    }),
  sheets: (status: SheetStatus | '') =>
    apiRequest<ActionSheetList>(`${settle}/action-sheets`, { query: { status: status || null } }),
  sheet: (id: string) =>
    apiRequest<ActionSheet>(`${settle}/action-sheets/${encodeURIComponent(id)}`),
  complete: (id: string, body: CompleteSheetIn, idempotencyKey: string) =>
    apiRequest<ActionSheet>(`${settle}/action-sheets/${encodeURIComponent(id)}/complete`, {
      method: 'POST',
      body,
      idempotencyKey,
    }),
};
