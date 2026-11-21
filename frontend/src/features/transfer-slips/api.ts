/**
 * Phase P5 (DEC-65): transfer slips + edit requests. Shapes mirror
 * backend/app/modules/transfer_slips/schemas.py.
 */
import { apiDownload, apiRequest, toApiError } from '@/lib/api/client';

export interface StoreRef {
  id: string;
  code: string;
  name: string;
}

export interface PendingBucket {
  field_code: string | null;
  label: string;
  qty: number;
}

export interface PendingLine {
  item_id: string;
  line_no: number;
  product_code: string | null;
  product_name: string;
  documented_qty: number;
  received_qty: number;
  store: StoreRef | null;
  buckets: PendingBucket[];
  on_slip_no: string | null;
}

export interface EditRequest {
  id: string;
  gs_id: string;
  gs_no: string;
  party_name: string | null;
  reason: string;
  status: 'OPEN' | 'EDITED' | 'REJECTED';
  requested_by_name: string | null;
  requested_at: string;
  resolved_by_name: string | null;
  resolved_at: string | null;
  resolution_note: string | null;
}

export interface PendingGs {
  gs_id: string;
  gs_no: string;
  party_id: string | null;
  party_name: string | null;
  station_name: string | null;
  state_name: string | null;
  cartons: number | null;
  received_date: string | null;
  locked_at: string | null;
  stores: StoreRef[];
  physical_qty: number;
  lines: PendingLine[];
  open_edit_request: EditRequest | null;
  partially_on_slips: boolean;
}

export type SlipStatus = 'GENERATED' | 'ACKNOWLEDGED' | 'VOIDED';

export interface SlipSummary {
  id: string;
  slip_no: string;
  store: StoreRef;
  status: SlipStatus;
  gs_count: number;
  gs_nos: string[];
  relevant_qty: number;
  grand_total_qty: number;
  generated_by_name: string | null;
  generated_at: string;
  voided_at: string | null;
  void_reason: string | null;
}

export interface SlipGs {
  gs_id: string;
  gs_no: string;
  party_name: string | null;
  station_name: string | null;
  state_name: string | null;
  cartons: number | null;
  received_date: string | null;
  relevant_qty: number;
  total_qty: number;
}

export interface SlipLine {
  id: string;
  gs_id: string;
  gs_item_id: string;
  line_no: number;
  product_code: string | null;
  product_name: string;
  bucket_label: string | null;
  qty: number;
  is_relevant: boolean;
  belongs_store_name: string;
}

export interface SlipDetail extends SlipSummary {
  custody_transfer_id: string;
  goods_slips: SlipGs[];
  lines: SlipLine[];
  acknowledged_by_name: string | null;
  acknowledged_at: string | null;
}

export interface GenerateResult {
  slips: SlipSummary[];
  goods_slip_ids: string[];
}

export interface SlipPage {
  items: SlipSummary[];
  total: number;
}

export interface GsTransferSlips {
  gs_id: string;
  slips: SlipSummary[];
  edit_requests: EditRequest[];
  open_edit_request: EditRequest | null;
}

/** CLAUDE.md rule h: an error message always carries the request id when the API returned one. */
export function slipErrorMessage(err: unknown): string {
  const e = toApiError(err);
  return e.requestId ? `${e.message} (Request ID: ${e.requestId})` : e.message;
}

export const transferSlipsApi = {
  pending: () => apiRequest<PendingGs[]>('/transfer-slips/pending'),

  /** One slip per Intermediate Store for the selected GSs. Stock-moving: Idempotency-Key (G-16). */
  generate: (gsIds: string[], idempotencyKey: string) =>
    apiRequest<GenerateResult>('/transfer-slips', {
      method: 'POST',
      body: { gs_ids: gsIds },
      idempotencyKey,
    }),

  list: (query: { status?: SlipStatus | ''; q?: string; page?: number }) =>
    apiRequest<SlipPage>('/transfer-slips', {
      query: {
        status: query.status || undefined,
        q: query.q?.trim() || undefined,
        page: query.page ?? 1,
        page_size: 25,
      },
    }),

  detail: (slipId: string) =>
    apiRequest<SlipDetail>(`/transfer-slips/${encodeURIComponent(slipId)}`),

  downloadPdf: (slip: { id: string; slip_no: string }) =>
    apiDownload(
      `/transfer-slips/${encodeURIComponent(slip.id)}/pdf`,
      undefined,
      `${slip.slip_no.replace(/\//g, '-')}.pdf`,
    ),

  forGs: (gsId: string) =>
    apiRequest<GsTransferSlips>(`/gs/${encodeURIComponent(gsId)}/transfer-slips`),

  requestEdit: (gsId: string, reason: string, idempotencyKey: string) =>
    apiRequest<EditRequest>(`/gs/${encodeURIComponent(gsId)}/edit-requests`, {
      method: 'POST',
      body: { reason },
      idempotencyKey,
    }),

  resolveEdit: (
    requestId: string,
    outcome: 'EDITED' | 'REJECTED',
    note: string | null,
    idempotencyKey: string,
  ) =>
    apiRequest<EditRequest>(
      `/transfer-slips/edit-requests/${encodeURIComponent(requestId)}/resolve`,
      { method: 'POST', body: { outcome, note }, idempotencyKey },
    ),
};
