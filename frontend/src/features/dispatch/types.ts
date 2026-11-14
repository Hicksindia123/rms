/**
 * Types for Replacement Dispatch (P3-05).
 * References: BR-19, BR-31, BR-32, DEC-26, DEC-33, §8.6.
 */

export interface DispatchQueueItem {
  gs_id: string;
  gs_no: string;
  party_id?: string | null;
  party_name: string;
  gs_item_id: string;
  line_no: number;
  product_id: string;
  product_code: string;
  product_name: string;
  action_code: string; // SEND_NEW or SEND_REPAIRED
  planned_qty: number;
  dispatched_qty: number;
  pending_qty: number;
  available_repaired_qty: number;
}

export interface DispatchCandidateLot {
  lot_id: string;
  stock_item_id: string;
  product_id: string;
  product_code: string;
  product_name: string;
  location_id: string;
  location_code: string;
  condition_class: string;
  available_qty: number;
  gs_id?: string | null;
  gs_no?: string | null;
}

export interface ReplacementDispatchLineInput {
  gs_item_id: string;
  qty: number;
  lot_id?: string | null;
}

export interface ReplacementDispatchCreateRequest {
  gs_id: string;
  dispatch_type: string; // SEND_NEW or SEND_REPAIRED
  lines: ReplacementDispatchLineInput[];
  transporter: string;
  docket_no?: string | null | undefined;
  vehicle_no?: string | null | undefined;
  ref_doc_no?: string | null | undefined;
  ref_doc_date?: string | null | undefined;
  override_reason?: string | null | undefined;
  notes?: string | null | undefined;
}

export interface ReplacementDispatchLine {
  id: string;
  dispatch_id: string;
  gs_item_id: string;
  lot_id?: string | null;
  qty: number;
  product_code: string;
  product_name: string;
  condition_class?: string | null;
}

export interface ReplacementDispatch {
  id: string;
  dispatch_no: string;
  gs_id: string;
  gs_no: string;
  party_name: string;
  dispatch_type: string;
  transporter: string;
  docket_no?: string | null;
  vehicle_no?: string | null;
  ref_doc_no?: string | null;
  ref_doc_date?: string | null;
  status: string;
  dispatched_at: string;
  dispatched_by: string;
  dispatched_by_name: string;
  override_reason?: string | null;
  notes?: string | null;
  total_qty: number;
  lines: ReplacementDispatchLine[];
}
