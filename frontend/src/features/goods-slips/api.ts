import { apiRequest } from '@/lib/api/client';
import type { Attachment, UploadUrlResult } from '@/features/unboxing/api';

// Shapes mirror backend/app/modules/goods_slips/schemas.py (P2-02).

export interface LookupItem {
  id: string;
  name: string;
  code?: string | null;
  state_id?: string | null;
  state_name?: string | null;
  station_id?: string | null;
  station_name?: string | null;
  is_provisional?: boolean | null;
}

export interface BackendOptionItem {
  code: string;
  label: string;
  allowed_status?: 'YES' | 'NO' | 'CONDITIONAL';
  rule_text?: string | null;
  next_action_text?: string | null;
  remarks?: string | null;
  sort_order: number;
  is_active?: boolean;
}

export interface BackendFormField {
  field_key: string;
  label: string;
  control_type: string;
  is_required: boolean;
  is_core?: boolean;
  visible_when?: unknown;
  required_when?: unknown;
  validation?: Record<string, unknown> | null;
  default_value?: unknown;
  sort_order: number;
  section?: string | null;
  help_text?: string | null;
  option_items?: BackendOptionItem[];
}

export interface BackendFormSnapshot {
  form_code: string;
  name: string;
  version_no: number;
  fields: BackendFormField[];
}

/** AMD-04: a configured gate document type (GATE_DOCUMENT option set, without NO_DOCUMENT). */
export interface GateDocumentType {
  code: string;
  label: string;
  /** Row columns the type requires: doc_no / doc_date / remarks (DD r5–r8). */
  required_fields: Array<'doc_no' | 'doc_date' | 'remarks'>;
}

export interface GateForm {
  form_version_id: string;
  snapshot: BackendFormSnapshot;
  contact_phone_pattern: string | null;
  party_state_station_autofill: boolean;
  document_types: GateDocumentType[];
  /** Business date (DEC-38: gate entry date never later than this). */
  business_today: string | null;
  /** DEC-38 `gate.max_backdate_days`; null = unlimited. */
  max_backdate_days: number | null;
}

export interface GateDocumentFile {
  id: string;
  mime_type: string;
  size_bytes: number;
  status: string;
  preview_unsupported: boolean;
  created_at: string;
}

/** AMD-04: one document row received with the consignment. */
export interface GateDocument {
  id: string;
  doc_type_code: string;
  doc_type_label: string;
  doc_no: string | null;
  doc_date: string | null;
  remarks: string | null;
  source_step: string;
  accounts_alerted_at: string | null;
  files: GateDocumentFile[];
}

export interface GateDocumentInput {
  id?: string;
  doc_type_code: string;
  doc_no?: string | null;
  doc_date?: string | null;
  remarks?: string | null;
}

export interface GoodsSlip {
  id: string;
  gs_no: string;
  status: string;
  party_id: string | null;
  party_name: string | null;
  party_is_provisional: boolean | null;
  state_name: string | null;
  station_name: string | null;
  state_station_overridden: boolean;
  delivery_mode_code: string;
  delivery_mode_label: string | null;
  courier_name: string | null;
  docket_no: string | null;
  vehicle_no: string | null;
  transporter_name: string | null;
  rep_name: string | null;
  rep_contact: string | null;
  /** AMD-03: number of cartons (box_count is the deprecated mirror). */
  carton_count: number;
  box_count: number;
  /** AMD-01 / AMD-02 (null on GS created before the change). */
  return_type_code: string | null;
  return_type_label: string | null;
  gate_entry_date: string | null;
  gate_entry_no: number | null;
  documents: GateDocument[];
  gate_document_code: string | null;
  gate_document_label: string | null;
  gate_doc_no: string | null;
  gate_doc_date: string | null;
  gate_doc_remarks: string | null;
  missing_documentation: boolean;
  has_open_pendency: boolean;
  has_discrepancy: boolean;
  has_hazard: boolean;
  has_rejections: boolean;
  cancelled_at: string | null;
  cancel_reason: string | null;
  created_at: string;
  created_by_name: string | null;
}

export interface GsWarning {
  code: string;
  message: string;
}

export interface GateInwardResult {
  goods_slip: GoodsSlip;
  warnings: GsWarning[];
  task_ids: string[];
  notified_user_count: number;
}

export interface GsListItem {
  id: string;
  gs_no: string;
  status: string;
  party_name: string | null;
  party_is_provisional: boolean | null;
  station_name: string | null;
  carton_count: number;
  box_count: number;
  return_type_code: string | null;
  gate_entry_no: number | null;
  delivery_mode_code: string;
  missing_documentation: boolean;
  has_open_pendency: boolean;
  has_discrepancy: boolean;
  has_hazard: boolean;
  has_rejections: boolean;
  created_at: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface TimelineEntry {
  at: string;
  kind: 'STATUS' | 'AUDIT';
  title: string;
  from_status: string | null;
  to_status: string | null;
  step_code: string | null;
  reason: string | null;
  changed_fields: string[] | null;
  by_name: string | null;
}

export interface GsTask {
  id: string;
  step_code: string;
  step_label: string | null;
  assigned_role_code: string | null;
  status: string;
  due_at: string | null;
  created_at: string;
}

export interface GsDetail {
  goods_slip: GoodsSlip;
  form_values: Record<string, unknown>;
  labels_snapshot: Record<string, { label: string; value: unknown; value_label?: unknown }>;
  timeline: TimelineEntry[];
  tasks: GsTask[];
  attachments: Array<{ kind: string; status: string; count: number }>;
  can_edit_gate: boolean;
  can_cancel: boolean;
}

export interface TagField {
  key: string;
  label: string;
  value: string | null;
}

export interface GsTag {
  template_code: string;
  template_version: number;
  layout: { header_title?: string; header_subtitle?: string; footer_text?: string };
  gs_id: string;
  gs_no: string;
  qr_payload: string;
  carton_count: number;
  box_count: number;
  sections: Array<{ id: string; title: string; fields: TagField[] }>;
  labels: Array<{ box_no: number; box_count: number; caption: string }>;
}

export interface CreateGsPayload {
  party_id?: string;
  provisional_party?: { name: string; state_id: string; station_id: string };
  state_id?: string;
  station_id?: string;
  transporter_id?: string;
  values: Record<string, unknown>;
  /** AMD-04 document rows (empty when `values.no_document` is true). */
  documents?: GateDocumentInput[];
}

/** AMD-06 / DEC-35: Distributor list for a state + station, with the configured fallback. */
export interface PartyLookupPage {
  items: LookupItem[];
  total: number;
  page: number;
  page_size: number;
  scope: 'STATION' | 'STATE' | 'ALL' | 'NONE';
  fallback_applied: boolean;
  fallback_setting: 'STATE' | 'ALL' | 'NONE';
}

export interface GsListQuery {
  page: number;
  q?: string;
  status?: string | string[];
  flag?: string[];
  date_from?: string;
  date_to?: string;
}

export const gsApi = {
  gateForm: () => apiRequest<GateForm>('/gs/gate-form'),
  parties: (q: string) =>
    apiRequest<LookupItem[]>('/gs/lookups/parties', { query: { q, limit: 20 } }),
  partiesByLocation: (stateId: string, stationId: string, q: string) =>
    apiRequest<PartyLookupPage>('/gs/lookups/parties/by-location', {
      query: {
        state_id: stateId,
        station_id: stationId,
        q: q || undefined,
        page: 1,
        page_size: 20,
      },
    }),
  states: () => apiRequest<LookupItem[]>('/gs/lookups/states'),
  stations: (stateId: string) =>
    apiRequest<LookupItem[]>('/gs/lookups/stations', { query: { state_id: stateId } }),
  transporters: (q: string) =>
    apiRequest<LookupItem[]>('/gs/lookups/transporters', { query: { q, limit: 20 } }),
  create: (payload: CreateGsPayload, idempotencyKey: string) =>
    apiRequest<GateInwardResult>('/gs', { method: 'POST', body: payload, idempotencyKey }),
  list: (query: GsListQuery) =>
    apiRequest<Page<GsListItem>>('/gs', {
      query: {
        page: query.page,
        page_size: 25,
        q: query.q,
        status: query.status,
        flag: query.flag,
        date_from: query.date_from,
        date_to: query.date_to,
      },
    }),
  detail: (id: string) => apiRequest<GsDetail>(`/gs/${encodeURIComponent(id)}`),
  cancel: (id: string, reason: string) =>
    apiRequest<GsDetail>(`/gs/${encodeURIComponent(id)}/cancel`, {
      method: 'POST',
      body: { reason },
    }),
  tag: (id: string) => apiRequest<GsTag>(`/gs/${encodeURIComponent(id)}/tag`),
  /** AMD-04: signed upload for one file of a gate document row. */
  gateDocUploadUrl: (
    gsId: string,
    documentId: string,
    body: { mime_type: string; size_bytes: number; file_name?: string },
  ) =>
    apiRequest<UploadUrlResult>(
      `/gs/${encodeURIComponent(gsId)}/gate-documents/${encodeURIComponent(documentId)}/files/upload-url`,
      { method: 'POST', body },
    ),
  confirmUpload: (attachmentId: string, objectPath: string) =>
    apiRequest<Attachment>(`/attachments/${encodeURIComponent(attachmentId)}/confirm`, {
      method: 'POST',
      body: { object_path: objectPath },
    }),
};
