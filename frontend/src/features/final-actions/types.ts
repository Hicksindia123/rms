/** RM Final Actions & "Replacement Slip – A/c Actions" (change plan Phase 7; AMD-16, AMD-17; G-21).
 * Mirrors backend/app/modules/final_actions/schemas.py. */

export interface FinalActionOption {
  code: string;
  label: string;
  requires_cn: boolean;
  requires_challan: boolean;
  sort_order: number;
}

export interface FinalActionAllocation {
  action_code: string;
  label: string;
  qty: number;
}

export interface OutcomeQty {
  outcome_code: string;
  outcome_label: string;
  is_wastage: boolean;
  qty: number;
}

export interface FinalActionLine {
  gs_item_id: string;
  line_no: number;
  product_id: string;
  product_code: string | null;
  product_name: string;
  counted_qty: number;
  at_departments_qty: number;
  /** G-21: counted − at departments. */
  available_qty: number;
  actioned_qty: number;
  is_balanced: boolean;
  outcomes: OutcomeQty[];
  allowed_actions: FinalActionOption[];
  current_actions: FinalActionAllocation[];
}

export interface FinalActionRevisionLine {
  line_no: number;
  action_code: string;
  action_label: string;
  qty: number;
}

export interface FinalActionRevision {
  revision_no: number;
  decided_by_name: string | null;
  decided_at: string;
  reason: string | null;
  lines: FinalActionRevisionLine[];
}

export interface AcSlipActionTotal {
  action_code: string;
  action_label: string;
  qty: number;
}

export interface AcSlipVersion {
  id: string;
  slip_no: string;
  version_no: number;
  revision_no: number;
  /** CURRENT | SUPERSEDED */
  status: string;
  finalised_at: string;
  finalised_by_name: string | null;
  superseded_at: string | null;
  superseded_by_name: string | null;
  supersede_reason: string | null;
  remarks: string | null;
  total_qty: number;
  action_totals: AcSlipActionTotal[];
  print_count: number;
}

export interface FinalActionsState {
  gs_id: string;
  gs_no: string;
  status: string;
  party_name: string | null;
  on_final_action_flow: boolean;
  can_edit: boolean;
  can_finalise: boolean;
  finalise_blockers: string[];
  current_revision_no: number;
  is_finalised: boolean;
  current_slip: AcSlipVersion | null;
  lines: FinalActionLine[];
  revisions: FinalActionRevision[];
  slips: AcSlipVersion[];
}

export interface SaveFinalActionsIn {
  lines: Array<{ gs_item_id: string; actions: Array<{ action_code: string; qty: number }> }>;
  reason?: string | null;
}

export interface AcSlipPrintOut {
  slip_id: string;
  slip_no: string;
  version_no: number;
  status: string;
  url: string;
  expires_in: number;
  print_count: number;
}

/** Per line: action code → qty being edited. */
export type Allocations = Record<string, Record<string, number>>;
