import { apiRequest } from '@/lib/api/client';
import type { Page } from '@/features/goods-slips/api';

// Shapes mirror backend/app/modules/unboxing/schemas.py (QueueItem, P2-03).

export interface QueueDocument {
  id: string;
  attachment_id: string;
  classification_code: string;
  classification_label: string | null;
  doc_no: string | null;
  doc_date: string | null;
  amount: string | null;
  buyer_gstin: string | null;
  seller_gstin: string | null;
  items_verified: boolean | null;
  qty_matched: boolean | null;
  party_claim_text: string | null;
  remarks: string | null;
  mime_type: string;
  preview_unsupported: boolean;
  verified_by_name: string | null;
  verified_at: string | null;
}

export interface QueueItem {
  gs_id: string;
  gs_no: string;
  status: string;
  party_name: string | null;
  station_name: string | null;
  missing_documentation: boolean;
  unboxed_at: string | null;
  documents: QueueDocument[];
}

export interface OptionItem {
  code: string;
  label: string;
}

export const accountsApi = {
  queue: (page: number, classification: string) =>
    apiRequest<Page<QueueItem>>('/accounts/document-queue', {
      query: { page, page_size: 25, classification },
    }),
  classifications: () => apiRequest<OptionItem[]>('/accounts/document-queue/classifications'),
  acknowledge: (gsId: string) =>
    apiRequest<{ gs_id: string; acknowledged: number }>(
      `/accounts/document-queue/${encodeURIComponent(gsId)}/acknowledge`,
      { method: 'POST' },
    ),
};
