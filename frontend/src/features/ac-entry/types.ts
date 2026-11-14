/** Accounts entry & Dispatch Slip (change plan Phase 8; AMD-18, AMD-19; DEC-22, DEC-26; G-22).
 * Mirrors backend/app/modules/ac_entry/schemas.py. */

export interface AcEntryQueueItem {
  gs_id: string;
  gs_no: string;
  gs_status: string;
  party_name: string | null;
  ac_action_slip_id: string;
  slip_no: string;
  version_no: number;
  finalised_at: string;
  lines_total: number;
  lines_needing_data: number;
  lines_complete: number;
  is_completed: boolean;
  completed_at: string | null;
  dispatch_slip_no: string | null;
  dispatch_status: string | null;
}

export interface AcEntryLine {
  id: string;
  gs_item_id: string;
  line_no: number;
  product_code: string | null;
  product_name: string;
  action_code: string;
  action_label: string;
  qty: number;
  /** AMD-18: which fields the line takes comes from the action flags (snapshot, G-18). */
  requires_cn: boolean;
  requires_challan: boolean;
  cn_no: string | null;
  cn_date: string | null;
  /** Decimal as a string (Pydantic Decimal). */
  cn_value: string | null;
  challan_no: string | null;
  challan_date: string | null;
  is_complete: boolean;
  entered_by_name: string | null;
  entered_at: string | null;
}

export interface DispatchSlipSummary {
  id: string;
  slip_no: string;
  status: 'READY' | 'DISPATCHED';
  generated_at: string;
  dispatch_date: string | null;
  transporter: string | null;
  docket_no: string | null;
  vehicle_no: string | null;
  dispatched_at: string | null;
  total_qty: number;
  print_count: number;
}

export interface AcEntryState {
  gs_id: string;
  gs_no: string;
  gs_status: string;
  party_name: string | null;
  party_code: string | null;
  ac_action_slip_id: string | null;
  slip_no: string | null;
  version_no: number | null;
  lines: AcEntryLine[];
  lines_needing_data: number;
  lines_complete: number;
  shipping_lines: number;
  is_completed: boolean;
  completed_by_name: string | null;
  completed_at: string | null;
  can_edit: boolean;
  can_complete: boolean;
  complete_blockers: string[];
  dispatch_slip: DispatchSlipSummary | null;
}

export interface AcEntryLineIn {
  line_id: string;
  cn_no: string | null;
  cn_date: string | null;
  cn_value: string | null;
  challan_no: string | null;
  challan_date: string | null;
}

export interface SaveAcEntryIn {
  ac_action_slip_id: string;
  lines: AcEntryLineIn[];
}

export interface DispatchSlipLine {
  id: string;
  gs_item_id: string;
  line_no: number;
  product_code: string | null;
  product_name: string;
  action_code: string;
  action_label: string;
  qty: number;
  challan_no: string;
  challan_date: string;
}

export interface DispatchSlipOut extends DispatchSlipSummary {
  gs_id: string;
  gs_no: string;
  gs_status: string;
  party_name: string | null;
  ac_slip_no: string;
  ac_version_no: number;
  dispatch_remarks: string | null;
  generated_by_name: string | null;
  dispatched_by_name: string | null;
  lines: DispatchSlipLine[];
}

export interface DispatchIn {
  dispatch_date: string;
  transporter: string;
  docket_no: string | null;
  vehicle_no: string | null;
  remarks: string | null;
}

export interface DispatchSlipPrintOut {
  dispatch_slip_id: string;
  slip_no: string;
  url: string;
  expires_in: number;
  print_count: number;
}

/** Editable values of one line (form strings; '' = empty). */
export interface LineDraft {
  cn_no: string;
  cn_date: string;
  cn_value: string;
  challan_no: string;
  challan_date: string;
}

export type Drafts = Record<string, LineDraft>;
