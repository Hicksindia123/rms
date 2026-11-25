/**
 * Phase P9 (DEC-69): analysis by the Intermediate Store user. Shapes mirror
 * backend/app/modules/final_actions/schemas.py (StoreAnalysis*).
 */

/** Computed by the system (rms_private.gs_store_analysis_progress), not configurable options. */
export type StoreAnalysisStatus = 'NOT_READY' | 'PENDING' | 'SUBMITTED';

export interface StoreAnalysisStore {
  store_id: string;
  store_code: string;
  store_name: string;
  /** P7/P8 progress: AWAITING_ACKNOWLEDGEMENT | ROUTING_PENDING | AT_DEPARTMENTS | READY_FOR_ANALYSIS */
  routing_status: string;
  analysis_status: StoreAnalysisStatus;
  submitted_at?: string | null;
  submitted_by_name?: string | null;
  remarks?: string | null;
  total_qty?: number | null;
  /** The signed-in user acts for this store. */
  is_mine: boolean;
}

export interface AnalysisOption {
  code: string;
  label: string;
  requires_cn: boolean;
  requires_challan: boolean;
  sort_order: number;
  /** DEC-74: "Issue CN Request": the pieces go to Management, who decides the credit note. */
  is_cn_request?: boolean;
}

export interface AnalysisDecision {
  action_code: string;
  label: string;
  qty: number;
}

export interface AnalysisGroup {
  condition_field_id: string | null;
  condition_code?: string | null;
  condition_label?: string | null;
  /** G-21: pieces to decide in this item + condition. */
  qty: number;
  decisions: AnalysisDecision[];
  /** DEC-75: per current decision, pieces still free to send to Management. */
  sendable?: SendableDecision[];
  /** DEC-75: pieces of this group in an OPEN Management request. */
  management_lines?: ManagementRequestLine[];
}

export interface SendableDecision {
  action_code: string;
  label: string;
  qty: number;
  free_qty: number;
}

/** DEC-75: pieces sent for Management approval (previous action -> proposed action). */
export interface ManagementRequestLine {
  id: string;
  request_id: string;
  request_status: string;
  gs_item_id: string;
  line_no: number;
  product_name?: string | null;
  condition_field_id: string | null;
  condition_label?: string | null;
  store_id: string;
  store_name?: string | null;
  from_action_code: string;
  from_action_label: string;
  proposed_action_code: string;
  proposed_action_label: string;
  qty: number;
  requested_at: string;
  requested_by_name?: string | null;
}

/** DEC-75: the two verdicts (setting store_analysis.verdicts). */
export interface Verdict {
  label: string;
  actions: string[];
}

export interface ProposalOption {
  code: string;
  label: string;
}

export interface AnalysisOutcome {
  outcome_code: string;
  outcome_label: string;
  is_wastage: boolean;
  qty: number;
}

export interface StoreAnalysisItem {
  gs_item_id: string;
  line_no: number;
  product_code?: string | null;
  product_name: string;
  received_qty: number;
  store_id?: string | null;
  store_code?: string | null;
  store_name?: string | null;
  is_mine: boolean;
  outcomes: AnalysisOutcome[];
  options: AnalysisOption[];
  groups: AnalysisGroup[];
}

export interface ManagementApprovalRequest {
  id: string;
  store_id: string;
  store_name: string;
  reason: string;
  status: string;
  requested_at: string;
  requested_by_name?: string | null;
}

export interface StoreAnalysisGs {
  gs_id: string;
  gs_no: string;
  status: string;
  party_name?: string | null;
  station_name?: string | null;
  stores: StoreAnalysisStore[];
  items: StoreAnalysisItem[];
  submittable_store_ids: string[];
  approval_store_ids: string[];
  can_request_approval: boolean;
  open_approval_request?: ManagementApprovalRequest | null;
  approval_requests: ManagementApprovalRequest[];
  verdicts?: { allowed: Verdict; not_allowed: Verdict } | null;
  proposals?: ProposalOption[];
  request_lines?: ManagementRequestLine[];
  can_send_to_management?: boolean;
}

export interface StoreAnalysisQueueRow {
  gs_id: string;
  gs_no: string;
  status: string;
  party_name?: string | null;
  station_name?: string | null;
  since?: string | null;
  approval_requested: boolean;
  stores: StoreAnalysisStore[];
}

export interface StoreAnalysisLineIn {
  gs_item_id: string;
  condition_field_id: string | null;
  decisions: { action_code: string; qty: number }[];
}

export interface StoreAnalysisSubmitIn {
  store_id: string;
  lines: StoreAnalysisLineIn[];
  remarks?: string | null;
  /** DEC-75: pieces sent to Management with the submission. */
  management_lines?: ManagementLineIn[];
  /** Optional note for Management with those pieces. */
  management_approval_reason?: string | null;
}

export interface ManagementLineIn {
  gs_item_id: string;
  condition_field_id: string | null;
  from_action_code: string;
  proposed_action_code: string;
  qty: number;
}
