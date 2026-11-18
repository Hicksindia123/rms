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

/** DEC-56: one condition of the item's current split (original = counting split). */
export interface ItemConditionQty {
  field_code: string;
  field_label: string;
  original_qty: number;
  current_qty: number;
}

/**
 * DEC-57 (gap plan G4): what the RM allocates — one item + one current condition. Items without a
 * condition split have one group with `condition_field_id: null`. In a Pending re-action round
 * `available_qty` is what the previous round left Pending.
 */
export interface FinalActionGroup {
  condition_field_id: string | null;
  condition_code: string | null;
  condition_label: string | null;
  current_qty: number;
  at_departments_qty: number;
  available_qty: number;
  actioned_qty: number;
  is_balanced: boolean;
  current_actions: FinalActionAllocation[];
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
  /** DEC-56: condition split after department work (empty for items without a split). */
  current_conditions?: ItemConditionQty[];
  allowed_actions: FinalActionOption[];
  /** Line total per action (all groups of the round). */
  current_actions: FinalActionAllocation[];
  /** DEC-57: per condition (absent on older payloads = one group for the whole line). */
  groups?: FinalActionGroup[];
}

export interface FinalActionRevisionLine {
  line_no: number;
  action_code: string;
  action_label: string;
  condition_label?: string | null;
  qty: number;
}

export interface FinalActionRevision {
  revision_no: number;
  round_no?: number;
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
  /** DEC-57: 1 = first decision; 2+ = re-action of Pending pieces. */
  round_no?: number;
  /** CURRENT | SUPERSEDED */
  status: string;
  /** Accounts completed this slip (G-22: frozen). */
  is_completed?: boolean;
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
  /** DEC-57: the round on screen (1 = first decision; 2+ = Pending re-action). */
  round_no?: number;
  /** Pieces the previous round left Pending (now in the Pending Hold). */
  pending_from_previous_round?: number;
  /** The re-action round waits for Accounts / dispatch of the previous round. */
  waiting_for_previous_round?: boolean;
  is_finalised: boolean;
  /** Accounts completed the current round's slip. */
  is_completed?: boolean;
  current_slip: AcSlipVersion | null;
  lines: FinalActionLine[];
  revisions: FinalActionRevision[];
  slips: AcSlipVersion[];
}

export interface SaveFinalActionsIn {
  /** One entry per item + condition group (DEC-57); no condition for items without a split. */
  lines: Array<{
    gs_item_id: string;
    condition_field_id?: string;
    actions: Array<{ action_code: string; qty: number }>;
  }>;
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

/** Per group key (see rules.groupKey): action code → qty being edited. */
export type Allocations = Record<string, Record<string, number>>;
