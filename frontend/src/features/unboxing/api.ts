import { apiRequest } from '@/lib/api/client';
import type { GateDocument, GateDocumentType } from '@/features/goods-slips/api';
import type { BackendFormSnapshot } from '@/features/goods-slips/api';

// Shapes mirror backend/app/modules/{attachments,unboxing}/schemas.py (P2-03).

export type UploadKind = 'UNBOXING_VIDEO' | 'DOC_PHOTO' | 'PARCEL_PHOTO';

export interface Attachment {
  id: string;
  gs_id: string;
  kind: string;
  mime_type: string;
  size_bytes: number;
  box_no: number | null;
  /** PENDING_UPLOAD | CONFIRMED | REJECTED */
  status: string;
  uploaded_by: string | null;
  uploaded_by_name: string | null;
  created_at: string;
  confirmed_at: string | null;
  preview_unsupported: boolean;
}

export interface SignedPutTicket {
  method: 'SIGNED_PUT';
  url: string;
  bucket: string;
  object_path: string;
}

export interface TusTicket {
  method: 'TUS';
  endpoint: string;
  token: string;
  bucket: string;
  object_path: string;
  content_type: string;
  chunk_size: number;
}

export type UploadTicket = SignedPutTicket | TusTicket;

export interface UploadUrlResult {
  attachment: Attachment;
  upload: UploadTicket;
}

/** G-02 (DEC-63): one confirmed video per carton is the only requirement. The document photo
 * counts are informational (legacy DOC_PHOTO evidence). */
export interface Checklist {
  video_ok: boolean;
  video_count: number;
  doc_photo_count: number;
  classified_doc_photo_count: number;
  parcel_photo_count: number;
  missing_documentation: boolean;
  video_per_box_required: boolean;
  /** AMD-03 / AMD-08: carton-wise progress (Carton n of N). */
  carton_count: number;
  cartons_with_video: number;
  boxes_missing_video: number[];
  missing: string[];
  ready: boolean;
}

export interface GsDocument {
  id: string;
  gs_id: string;
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
  form_version_id: string | null;
  values: Record<string, unknown>;
  labels_snapshot: Record<string, { label: string; value: unknown; value_label?: unknown }>;
  verified_by_name: string | null;
  verified_at: string | null;
  accounts_acknowledged_by_name: string | null;
  accounts_acknowledged_at: string | null;
}

/** DEC-03 Missing Document Exception: read-only history (retired by DEC-63). */
export interface MissingDocException {
  id: string;
  gs_id: string;
  gs_no: string;
  party_name: string | null;
  parcel_attachment_id: string;
  parcel_mime_type: string;
  parcel_preview_unsupported: boolean;
  remark: string;
  /** REQUESTED | APPROVED | REJECTED */
  status: string;
  requested_by_name: string | null;
  requested_at: string;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_remarks: string | null;
}

export interface UnboxingState {
  goods_slip: {
    id: string;
    gs_no: string;
    status: string;
    party_name: string | null;
    station_name: string | null;
    carton_count: number;
    box_count: number;
    missing_documentation: boolean;
    /** Q27: a document found in a carton cleared the gate's "No Documents From Party" tag. */
    missing_documentation_cleared_at?: string | null;
    gate_document_code: string | null;
    gate_document_label: string | null;
  };
  checklist: Checklist;
  attachments: Attachment[];
  documents: GsDocument[];
  exceptions: MissingDocException[];
  form_version_id: string;
  form_snapshot: BackendFormSnapshot;
  limits: {
    max_video_bytes: number;
    max_document_bytes: number;
    resumable_threshold_bytes: number;
  };
  permissions: { can_perform: boolean };
  /** AMD-04: document rows of the GS (gate + carton opening) and the configured row types. */
  gate_documents: GateDocument[];
  document_types: GateDocumentType[];
}

export interface DownloadUrl {
  url: string;
  expires_in: number;
  expires_at: string;
  mime_type: string;
}

export interface CompleteResult {
  goods_slip: UnboxingState['goods_slip'];
  task_ids: string[];
  notified_user_count: number;
}

const gs = (id: string) => `/gs/${encodeURIComponent(id)}`;

export const unboxingApi = {
  state: (gsId: string) => apiRequest<UnboxingState>(`${gs(gsId)}/unboxing`),
  start: (gsId: string) =>
    apiRequest<UnboxingState>(`${gs(gsId)}/unboxing/start`, { method: 'POST' }),
  complete: (gsId: string) =>
    apiRequest<CompleteResult>(`${gs(gsId)}/unboxing/complete`, { method: 'POST' }),
  uploadUrl: (
    gsId: string,
    body: {
      kind: UploadKind;
      mime_type: string;
      size_bytes: number;
      file_name?: string;
      box_no?: number;
    },
  ) => apiRequest<UploadUrlResult>(`${gs(gsId)}/attachments/upload-url`, { method: 'POST', body }),
  confirm: (attachmentId: string, objectPath?: string) =>
    apiRequest<Attachment>(`/attachments/${encodeURIComponent(attachmentId)}/confirm`, {
      method: 'POST',
      body: objectPath ? { object_path: objectPath } : {},
    }),
  downloadUrl: (attachmentId: string) =>
    apiRequest<DownloadUrl>(`/attachments/${encodeURIComponent(attachmentId)}/download-url`),
  remove: (attachmentId: string) =>
    apiRequest<undefined>(`/attachments/${encodeURIComponent(attachmentId)}`, {
      method: 'DELETE',
    }),
  classify: (gsId: string, attachmentId: string, values: Record<string, unknown>) =>
    apiRequest<GsDocument>(`${gs(gsId)}/documents`, {
      method: 'POST',
      body: { attachment_id: attachmentId, values },
    }),
  updateDocument: (gsId: string, docId: string, values: Record<string, unknown>) =>
    apiRequest<GsDocument>(`${gs(gsId)}/documents/${encodeURIComponent(docId)}`, {
      method: 'PATCH',
      body: { values },
    }),
  /** P3 / DEC-62: the one optional document found in a carton: a type only, photos are uploaded
   * to the row afterwards (Idempotency-Key). */
  addCartonDocument: (gsId: string, body: { doc_type_code: string }, idempotencyKey: string) =>
    apiRequest<GateDocument>(`${gs(gsId)}/carton-documents`, {
      method: 'POST',
      body,
      idempotencyKey,
    }),
  removeCartonDocument: (gsId: string, docId: string) =>
    apiRequest<undefined>(`${gs(gsId)}/carton-documents/${encodeURIComponent(docId)}`, {
      method: 'DELETE',
    }),
};
