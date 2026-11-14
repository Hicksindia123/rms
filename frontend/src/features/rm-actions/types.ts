/**
 * Types for Step-3 a) RM item-wise actions and Replacement Slip.
 * References: WF r6, BR-19, BR-20, G-08, DEC-12, DEC-13, DEC-33.
 */

export interface RmActionItem {
  action_code: string;
  qty: number;
}

export interface RmLineActionInput {
  gs_item_id: string;
  actions: RmActionItem[];
}

export interface PendencyDetailInput {
  reason: string;
  sent_to: string;
}

export interface SaveRmActionsRequest {
  lines: RmLineActionInput[];
  reason?: string | undefined;
  override_reason?: string | undefined;
  pendency_details?: Record<string, PendencyDetailInput> | undefined;
}

export interface RmActionOption {
  code: string;
  label: string;
  allowed_status: string;
  rule_text?: string | null;
  next_action_text?: string | null;
  sort_order: number;
}

export interface RmActionAllocation {
  action_code: string;
  label: string;
  qty: number;
  reason?: string | null;
}

export interface RmActionLine {
  gs_item_id: string;
  line_no: number;
  product_id: string;
  product_code: string;
  product_name: string;
  received_qty: number;
  allowed_qty: number;
  not_allowed_qty: number;
  allocations: Array<{
    condition_code: string;
    condition_label?: string;
    qty: number;
    allowed_status?: string;
    system_behavior?: string;
  }>;
  rejections: Array<{
    condition_code: string;
    condition_label?: string;
    qty: number;
    disposition?: string;
    reason?: string;
  }>;
  current_actions: RmActionAllocation[];
  pending_qty: number;
}

export interface RmActionRevision {
  revision_no: number;
  decided_by: string;
  decided_by_name: string;
  decided_at: string;
  reason?: string | null;
  lines: Array<{
    gs_item_id: string;
    line_no: number;
    action_code: string;
    action_label: string;
    qty: number;
  }>;
}

export interface RmActionsResponse {
  gs_id: string;
  gs_no: string;
  status: string;
  current_step_code?: string;
  current_revision_no: number;
  has_open_pendency: boolean;
  can_revise: boolean;
  requires_reason_for_revision: boolean;
  lines: RmActionLine[];
  revision_history: RmActionRevision[];
  options: RmActionOption[];
}

export interface ReplacementSlipLine {
  line_no: number;
  product_code: string;
  product_name: string;
  received_qty: number;
  send_new_qty: number;
  send_repaired_qty: number;
  issue_cn_qty: number;
  not_allowed_qty: number;
  pending_bp_qty: number;
  rejected_qty: number;
  rejection_reasons: string[];
  pending_qty: number;
  remarks?: string | null;
}

export interface SignatureBlock {
  label: string;
  role: string;
  name: string;
}

export interface ReplacementSlipResponse {
  gs_id: string;
  gs_no: string;
  party_name: string;
  party_code?: string | null;
  station_name?: string | null;
  state_name?: string | null;
  date: string;
  revision_no: number;
  rm_name: string;
  prepared_by: string;
  print_count: number;
  is_reprint: boolean;
  watermark?: string | null;
  signature_blocks: SignatureBlock[];
  lines: ReplacementSlipLine[];
  totals: Record<string, number>;
  layout: Record<string, unknown>;
}

export type ReplacementSlip = ReplacementSlipResponse;

export interface LineOutcomeDetail {
  functional_good_qty: number;
  functional_repaired_qty: number;
  non_good_qty: number;
  non_sellable_qty: number;
  rejected_qty: number;
}

export interface LineDispatchedDetail {
  dispatched_new_qty: number;
  dispatched_repaired_qty: number;
  issued_main_store_qty: number;
}

export interface ResolutionBoardLine {
  gs_item_id: string;
  line_no: number;
  product_id: string;
  product_code: string;
  product_name: string;
  received_qty: number;
  current_actions: RmActionAllocation[];
  outcomes: LineOutcomeDetail;
  dispatched: LineDispatchedDetail;
  suggested_adjustments: string[];
  has_mismatch: boolean;
}

export interface ResolutionBoardResponse {
  gs_id: string;
  gs_no: string;
  status: string;
  current_step_code?: string | null;
  current_revision_no: number;
  lines: ResolutionBoardLine[];
  summary_notes: string[];
}
