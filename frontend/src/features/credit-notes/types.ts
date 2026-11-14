export type CnTypeCode = 'GST_CN' | 'GENERAL_CN' | 'JV_ONLY';
export type CnStatus = 'DRAFT' | 'VERIFIED' | 'ISSUED' | 'CANCELLED';
export type PartyDocCode = 'PARTY_INVOICE' | 'PARTY_DEBIT_NOTE' | 'PARTY_NO_DOC';
export type GstPortalCode = 'GST_REFLECTED' | 'GST_NOT_REFLECTED';
export type GstReturnType = 'GSTR-1' | 'GSTR-2B';
export type RateReferenceCode = 'RATE_SALES' | 'RATE_PURCHASE';

export interface LinkedStep2Document {
  id: string;
  document_type_code: string;
  document_type_label: string;
  doc_no: string | null;
  doc_date: string | null;
  amount: number | null;
  attachment_id: string;
  file_name: string | null;
  storage_path: string | null;
}

export interface RateVerification {
  id: string;
  credit_note_line_id: string;
  reference_code: RateReferenceCode;
  reference_label: string;
  ref_doc_no: string;
  ref_doc_date: string;
  rate: number;
  notes: string | null;
  verified_by: string;
  verified_by_name: string;
  verified_at: string;
}

export interface RateVerificationResult {
  verification: RateVerification;
  sales_rate: number | null;
  purchase_rate: number | null;
  variance_percent: number | null;
  has_variance_warning: boolean;
  variance_warning_message: string | null;
}

export interface CreditNoteLine {
  id: string;
  credit_note_id: string;
  gs_item_id: string;
  line_no: number;
  product_code: string;
  product_name: string;
  lot_id: string | null;
  condition_class: string | null;
  qty: number;
  rate: number;
  tax_rate: number;
  taxable_amount: number;
  cgst_amount: number;
  sgst_amount: number;
  igst_amount: number;
  total_amount: number;
  rate_verifications: RateVerification[];
  is_rate_verified: boolean;
}

export interface CreditNoteDetail {
  id: string;
  gs_id: string;
  gs_no: string;
  party_id: string;
  party_name: string;
  party_gstin: string | null;
  party_state: string | null;
  cn_type_code: CnTypeCode;
  cn_type_label: string;
  status: CnStatus;
  party_doc_code: PartyDocCode | null;
  party_doc_label: string | null;
  party_doc_no: string | null;
  party_doc_date: string | null;
  party_doc_amount: number | null;
  party_doc_notes: string | null;
  gst_portal_code: GstPortalCode | null;
  gst_portal_label: string | null;
  gst_return_type: GstReturnType | null;
  gst_return_period: string | null;
  gst_checked_on: string | null;
  gst_evidence_attachment_id: string | null;
  cn_no: string | null;
  cn_date: string | null;
  jv_no: string | null;
  jv_date: string | null;
  taxable_value: number;
  cgst_rate: number;
  cgst_amount: number;
  sgst_rate: number;
  sgst_amount: number;
  igst_rate: number;
  igst_amount: number;
  total_value: number;
  is_inter_state: boolean;
  created_by: string;
  created_by_name: string;
  created_at: string;
  issued_by: string | null;
  issued_by_name: string | null;
  issued_at: string | null;
  cancelled_by_name: string | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  lines: CreditNoteLine[];
  linked_step2_documents: LinkedStep2Document[];
}

export interface CreditNoteListItem {
  id: string;
  gs_id: string;
  gs_no: string;
  party_id: string;
  party_name: string;
  cn_type_code: CnTypeCode;
  cn_type_label: string;
  status: CnStatus;
  party_doc_code: string | null;
  party_doc_label: string | null;
  gst_portal_code: string | null;
  gst_portal_label: string | null;
  cn_no: string | null;
  cn_date: string | null;
  jv_no: string | null;
  jv_date: string | null;
  total_qty: number;
  taxable_value: number;
  total_value: number;
  created_at: string;
  issued_at: string | null;
}

export interface CreditNoteWorkQueueItem {
  gs_id: string;
  gs_no: string;
  party_id: string;
  party_name: string;
  allowed_cn_qty: number;
  draft_cn_qty: number;
  issued_cn_qty: number;
  pending_to_credit_qty: number;
  rm_decision_date: string;
  active_credit_notes_count: number;
}

export interface CreditNoteWorkQueue {
  pending_gs: CreditNoteWorkQueueItem[];
  active_notes: CreditNoteListItem[];
}

export interface RmCnDecisionLine {
  id: string;
  decision_id: string;
  gs_item_id: string;
  line_no: number;
  product_code: string;
  product_name: string;
  decision_code: 'ALLOW_CN' | 'DENY_CN_SEND_REPLACEMENT';
  decision_label: string;
  qty: number;
}

export interface RmCnDecision {
  id: string;
  gs_id: string;
  gs_no: string;
  party_name: string;
  decision_by: string;
  decision_by_name: string;
  decision_at: string;
  deviation_reason: string | null;
  is_current: boolean;
  lines: RmCnDecisionLine[];
}

export interface RmCnDecisionPrefillLine {
  gs_item_id: string;
  line_no: number;
  product_code: string;
  product_name: string;
  received_qty: number;
  planned_action_code: string;
  planned_action_label: string;
  planned_qty: number;
  default_decision_code: 'ALLOW_CN' | 'DENY_CN_SEND_REPLACEMENT';
  allowed_qty: number;
}

export interface RmCnDecisionPrefill {
  gs_id: string;
  gs_no: string;
  party_name: string;
  is_csr: boolean;
  has_existing_decision: boolean;
  current_decision: RmCnDecision | null;
  prefill_lines: RmCnDecisionPrefillLine[];
}

export interface PrintSignatureBlock {
  label: string;
  name: string;
  role: string;
}

export interface CreditNotePrint {
  credit_note_id: string;
  gs_id: string;
  gs_no: string;
  party_name: string;
  party_gstin: string | null;
  party_station: string | null;
  party_state: string | null;
  cn_type_code: string;
  cn_type_label: string;
  voucher_no: string;
  voucher_date: string;
  voucher_type_name: string;
  party_doc_type: string | null;
  party_doc_no: string | null;
  party_doc_date: string | null;
  gst_portal_status: string | null;
  gst_return_period: string | null;
  taxable_value: number;
  cgst_amount: number;
  sgst_amount: number;
  igst_amount: number;
  total_value: number;
  is_inter_state: boolean;
  lines: Array<{
    line_no: number;
    product_code: string;
    product_name: string;
    qty: number;
    rate: number;
    tax_rate: number;
    taxable_amount: number;
    cgst_amount: number;
    sgst_amount: number;
    igst_amount: number;
    total_amount: number;
    condition_class?: string | null;
    rate_verified_doc?: string | null;
  }>;
  signature_blocks: PrintSignatureBlock[];
}
