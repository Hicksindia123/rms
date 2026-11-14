import { apiRequest } from '@/lib/api/client';
import type {
  CreditNoteDetail,
  CreditNoteListItem,
  CreditNotePrint,
  CreditNoteWorkQueue,
  PartyDocCode,
  GstPortalCode,
  GstReturnType,
  CnTypeCode,
  RateReferenceCode,
  RateVerificationResult,
  RmCnDecision,
  RmCnDecisionPrefill,
} from './types';

export const creditNotesApi = {
  // Work Queue
  getWorkQueue: () => apiRequest<CreditNoteWorkQueue>('/credit-notes/work-queue'),

  // List & Register
  list: (params?: {
    gs_id?: string;
    status?: string;
    cn_type_code?: string;
    party_search?: string;
    from_date?: string;
    to_date?: string;
    limit?: number;
    offset?: number;
  }) => apiRequest<CreditNoteListItem[]>('/credit-notes', params ? { query: params } : {}),

  // Detail
  get: (id: string) => apiRequest<CreditNoteDetail>(`/credit-notes/${encodeURIComponent(id)}`),

  // Draft Creation (G-13)
  create: (payload: {
    gs_id: string;
    cn_type_code?: CnTypeCode | undefined;
    gst_portal_code?: GstPortalCode | undefined;
    lines: Array<{ gs_item_id: string; lot_id?: string | undefined; qty: number }>;
  }) =>
    apiRequest<CreditNoteDetail>('/credit-notes', {
      method: 'POST',
      body: payload,
    }),

  // Step 3: Party Document Verification (BR-33)
  verifyPartyDoc: (
    id: string,
    payload: {
      party_doc_code: PartyDocCode;
      doc_no?: string | undefined;
      doc_date?: string | undefined;
      amount?: number | undefined;
      notes?: string | undefined;
    },
  ) =>
    apiRequest<CreditNoteDetail>(`/credit-notes/${encodeURIComponent(id)}/party-document`, {
      method: 'PATCH',
      body: payload,
    }),

  // Step 4: GST Portal Verification (BR-34, G-13)
  verifyGstCheck: (
    id: string,
    payload: {
      gst_portal_code: GstPortalCode;
      return_type?: GstReturnType | undefined;
      return_period?: string | undefined;
      checked_on: string;
      evidence_attachment_id?: string | undefined;
    },
  ) =>
    apiRequest<CreditNoteDetail>(`/credit-notes/${encodeURIComponent(id)}/gst-check`, {
      method: 'PATCH',
      body: payload,
    }),

  // Step 5: Type Selection (G-13, DEC-23)
  updateType: (id: string, cn_type_code: CnTypeCode) =>
    apiRequest<CreditNoteDetail>(`/credit-notes/${encodeURIComponent(id)}/type`, {
      method: 'PATCH',
      body: { cn_type_code },
    }),

  // Split Credit Note (DEC-23)
  split: (id: string) =>
    apiRequest<{
      split_performed: boolean;
      message: string;
      original_cn_id: string;
      repaired_cn_id?: string;
      repaired_lines_count?: number;
    }>(`/credit-notes/${encodeURIComponent(id)}/split`, {
      method: 'POST',
    }),

  // Step 6: Rate Verification per line (G-14, DEC-24)
  verifyRate: (
    lineId: string,
    payload: {
      reference_code: RateReferenceCode;
      ref_doc_no: string;
      ref_doc_date: string;
      rate: number;
      notes?: string | undefined;
    },
  ) =>
    apiRequest<RateVerificationResult>(
      `/credit-note-lines/${encodeURIComponent(lineId)}/rate-verifications`,
      {
        method: 'POST',
        body: payload,
      },
    ),

  // Step 7: Issue (DEC-22, G-14)
  issue: (
    id: string,
    payload: {
      cn_no?: string | undefined;
      cn_date?: string | undefined;
      jv_no?: string | undefined;
      jv_date?: string | undefined;
    },
  ) =>
    apiRequest<CreditNoteDetail>(`/credit-notes/${encodeURIComponent(id)}/issue`, {
      method: 'POST',
      body: payload,
    }),

  // Cancel
  cancel: (id: string, reason: string) =>
    apiRequest<CreditNoteDetail>(`/credit-notes/${encodeURIComponent(id)}/cancel`, {
      method: 'POST',
      body: { reason },
    }),

  // Print Summary
  getPrint: (id: string) =>
    apiRequest<CreditNotePrint>(`/credit-notes/${encodeURIComponent(id)}/print`),

  // RM CN Decision (BR-32, DEC-13, G-13)
  getCnDecisionPrefill: (gsId: string) =>
    apiRequest<RmCnDecisionPrefill>(`/gs/${encodeURIComponent(gsId)}/cn-decision`),

  recordCnDecision: (
    gsId: string,
    payload: {
      lines: Array<{
        gs_item_id: string;
        decision: 'ALLOW_CN' | 'DENY_CN_SEND_REPLACEMENT';
        qty: number;
      }>;
      deviation_reason?: string | null | undefined;
    },
  ) =>
    apiRequest<RmCnDecision>(`/gs/${encodeURIComponent(gsId)}/cn-decision`, {
      method: 'POST',
      body: payload,
    }),
};
