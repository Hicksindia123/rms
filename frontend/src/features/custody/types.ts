/**
 * Custody transfer engine & Step-4 handover (P3-01; DD r44–r46, BR-20..BR-22, G-08, G-09).
 * Shapes mirror backend/app/modules/custody/schemas.py.
 */

export type TransferStatus = 'INITIATED' | 'ACCEPTED' | 'DISCREPANCY' | 'RECONCILED' | 'CANCELLED';

export interface CustodyOption {
  code: string;
  label: string;
  description?: string | null;
}

export interface CustodyLookups {
  acceptance_options: CustodyOption[];
  mode_options: CustodyOption[];
  resolution_options: CustodyOption[];
  disposition_options: CustodyOption[];
  blind_count: boolean;
  statuses: TransferStatus[];
}

export interface TransferLine {
  lot_id: string;
  gs_item_id: string | null;
  line_no: number | null;
  product_code: string | null;
  product_name: string | null;
  condition_class: string;
  condition_code: string | null;
  condition_label: string | null;
  routing_hint: string | null;
  /** null while a blind count hides the quantity sent from the receiver. */
  qty_sent: number | null;
  qty_counted: number | null;
  qty_accepted: number;
  qty_returned: number;
  qty_adjusted: number;
}

export interface Reconciliation {
  id: string;
  resolution_code: string;
  resolution_label: string;
  difference_disposition: string | null;
  resend_lines: Array<{ lot_id: string; qty: number }>;
  notes: string;
  status: 'PROPOSED' | 'AWAITING_RM_APPROVAL' | 'APPLIED' | 'SUPERSEDED';
  requires_rm_approval: boolean;
  proposed_by_name: string | null;
  proposed_at: string;
  initiator_signed_by_name: string | null;
  initiator_signed_at: string | null;
  receiver_signed_by_name: string | null;
  receiver_signed_at: string | null;
  is_rm_override: boolean;
  rm_approved_by_name: string | null;
  rm_approved_at: string | null;
  rm_reason: string | null;
  applied_at: string | null;
  resend_transfer_id: string | null;
}

export interface TransferPermissions {
  can_accept: boolean;
  can_cancel: boolean;
  can_print: boolean;
  reconcile_side: 'INITIATOR' | 'RECEIVER' | null;
  can_override: boolean;
  can_approve_adjustment: boolean;
}

export interface TransferSummary {
  id: string;
  transfer_no: string;
  gs_id: string | null;
  gs_no: string | null;
  status: TransferStatus;
  purpose_code: string | null;
  with_packaging: boolean;
  stock_moved: boolean;
  mode_code: string;
  mode_label: string | null;
  from_location_code: string;
  from_location_name: string;
  to_location_code: string;
  to_location_name: string;
  initiated_by: string;
  initiated_by_name: string | null;
  initiated_at: string;
  accepted_by_name: string | null;
  accepted_at: string | null;
  acceptance_code: string | null;
  acceptance_label: string | null;
  line_count: number;
  total_qty: number | null;
  created_at: string;
}

export interface TransferDetail extends TransferSummary {
  notes: string | null;
  discrepancy_notes: string | null;
  cancel_reason: string | null;
  cancelled_at: string | null;
  resolution_code: string | null;
  reconciled_at: string | null;
  supersedes_transfer_id: string | null;
  blind_count: boolean;
  lines: TransferLine[];
  reconciliations: Reconciliation[];
  permissions: TransferPermissions;
}

export interface TransferPage {
  items: TransferSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface HandoverLine {
  lot_id: string;
  gs_item_id: string | null;
  line_no: number | null;
  product_code: string | null;
  product_name: string | null;
  condition_code: string | null;
  condition_label: string | null;
  routing_hint: string | null;
  qty: number;
}

export interface ExcludedLine {
  lot_id: string | null;
  gs_item_id: string | null;
  line_no: number | null;
  product_name: string | null;
  qty: number;
  reason_code: 'PENDING_BP' | 'NOT_ALLOWED' | 'HAZARD' | 'RM_NOT_ALLOWED';
  reason_label: string;
  condition_label: string | null;
  location_code: string | null;
  location_name: string | null;
  detail: string | null;
}

export interface HandoverPreview {
  gs_id: string;
  gs_no: string;
  gs_status: string;
  category_code: string | null;
  from_location_code: string;
  from_location_name: string;
  to_location_code: string;
  to_location_name: string;
  eligible: HandoverLine[];
  excluded: ExcludedLine[];
  blocked: { code: string; message: string } | null;
  proposal_transfer_id: string | null;
  live_transfers: TransferSummary[];
  can_initiate: boolean;
  mode_options: CustodyOption[];
  default_mode_code: string | null;
}

export interface StoreStockRow {
  lot_id: string;
  qty: number;
  gs_id: string;
  gs_no: string;
  gs_item_id: string | null;
  line_no: number | null;
  product_code: string | null;
  product_name: string | null;
  condition_class: string;
  condition_code: string | null;
  condition_label: string | null;
  routing_hint: string | null;
  requires_evaluation: boolean;
  last_packaging_check: { result_code: string; qty: number; at: string } | null;
  next_step: 'DIRECT_CLASSIFICATION' | 'AWAITING_TECHNICIAN' | 'CLASSIFIED';
  can_classify: boolean;
}

export interface StoreStock {
  location_code: string;
  location_name: string;
  rows: StoreStockRow[];
  can_classify: boolean;
  can_check_packaging: boolean;
}

export interface TransferNote {
  transfer: TransferDetail;
  layout: Record<string, unknown>;
  template_version: number;
  print_count: number;
  is_reprint: boolean;
  watermark: string | null;
}

export interface CountLine {
  lot_id: string;
  qty_counted: number;
}

export interface ReconcileBody {
  resolution_code: string;
  notes: string;
  difference_disposition?: string | null;
  override?: boolean;
}
