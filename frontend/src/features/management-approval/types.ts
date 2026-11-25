/**
 * Phase P10 (DEC-70; Q17, Q18): Management approval and the e-approval stamp. Shapes mirror
 * backend/app/modules/management_approval/schemas.py.
 */

/** Computed by the system (rms_private.gs_management_approval_state), not configurable options. */
export type ApprovalState = 'NONE' | 'VALID' | 'CHANGED';

export interface ActionOption {
  code: string;
  label: string;
  requires_cn: boolean;
  requires_challan: boolean;
  sort_order: number;
}

export interface Decision {
  action_code: string;
  label: string;
  qty: number;
  /** DEC-74: a store's Issue CN Request (Management decides these pieces). */
  is_cn_request?: boolean;
}

export interface MgmtGroup {
  condition_field_id: string | null;
  condition_code?: string | null;
  condition_label?: string | null;
  /** G-21: pieces of this item + condition. */
  qty: number;
  decisions: Decision[];
  /** DEC-74: pieces still on a store's Issue CN Request. */
  cn_requested_qty?: number;
}

export interface MgmtItem {
  gs_item_id: string;
  line_no: number;
  product_code?: string | null;
  product_name: string;
  received_qty: number;
  store_code?: string | null;
  store_name?: string | null;
  options: ActionOption[];
  groups: MgmtGroup[];
}

export interface StoreProgress {
  store_id: string;
  store_code: string;
  store_name: string;
  analysis_status: string;
  submitted_at?: string | null;
  submitted_by_name?: string | null;
  remarks?: string | null;
}

export interface ApprovalRequest {
  id: string;
  store_id: string;
  store_name: string;
  reason: string;
  status: string;
  requested_at: string;
  requested_by_name?: string | null;
  resolved_at?: string | null;
  resolved_by_name?: string | null;
  approval_id?: string | null;
}

export interface Change {
  line_no: number;
  product_name: string;
  condition_label?: string | null;
  before: Decision[];
  after: Decision[];
  reason: string;
}

export interface Revision {
  revision_no: number;
  made_at: string;
  made_by_name?: string | null;
  changes: Change[];
}

export interface Approval {
  id: string;
  approval_no: number;
  approver_name: string;
  approver_role: string;
  approved_at: string;
  revision_no: number;
  snapshot_sha256: string;
  short_ref: string;
  has_issue_cn: boolean;
  remarks?: string | null;
  request_id?: string | null;
}

export interface Stamp {
  gs_id: string;
  gs_no: string;
  state: ApprovalState;
  approval?: Approval | null;
  stamp_text?: string | null;
  disclaimer: string;
}

export interface VerifyResult {
  gs_id: string;
  result: ApprovalState;
  approval?: Approval | null;
  stored_sha256?: string | null;
  current_sha256: string;
  integrity_ok: boolean;
  checked_at: string;
}

export interface ManagementGs {
  gs_id: string;
  gs_no: string;
  status: string;
  party_name?: string | null;
  station_name?: string | null;
  stores: StoreProgress[];
  items: MgmtItem[];
  /** DEC-74: pieces still on a store's Issue CN Request (approval refused while > 0). */
  cn_request_qty?: number;
  can_edit: boolean;
  can_approve: boolean;
  blocked_reason?: string | null;
  open_request?: ApprovalRequest | null;
  requests: ApprovalRequest[];
  revisions: Revision[];
  approvals: Approval[];
  stamp: Stamp;
  accounts_gate: { passes: boolean; problem?: string | null };
  /** DEC-71 (P11): saving a change reopens a goods slip at Accounts / on hold. */
  reopen_notice?: string | null;
}

export interface QueueRow {
  gs_id: string;
  gs_no: string;
  status: string;
  party_name?: string | null;
  station_name?: string | null;
  since?: string | null;
  request_id?: string | null;
  request_reason?: string | null;
  request_store_name?: string | null;
  requested_at?: string | null;
  requested_by_name?: string | null;
  approval_state: ApprovalState;
  has_issue_cn: boolean;
  /** DEC-74: pieces still on a store's Issue CN Request. */
  cn_request_qty?: number;
  waiting_store_codes: string[];
}

export interface ChangeIn {
  gs_item_id: string;
  condition_field_id: string | null;
  decisions: { action_code: string; qty: number }[];
  reason: string;
}
