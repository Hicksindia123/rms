/**
 * Types for Step-6 Store Issues (P3-05).
 * References: BR-19, BR-31, DEC-21, G-04.
 */

export interface StoreIssueCandidateLot {
  lot_id: string;
  stock_item_id: string;
  product_id: string;
  product_code: string;
  product_name: string;
  condition_class: string;
  available_qty: number;
  gs_id?: string | null;
  gs_no?: string | null;
}

export interface StoreIssueLineInput {
  lot_id: string;
  qty: number;
}

export interface StoreIssueCreateRequest {
  lines: StoreIssueLineInput[];
  issue_type_code?: string;
  notes?: string | null | undefined;
}

export interface StoreIssueLine {
  id: string;
  issue_id: string;
  lot_id: string;
  qty: number;
  product_code: string;
  product_name: string;
  condition_class: string;
  gs_id?: string | null;
  gs_no?: string | null;
}

export interface StoreIssue {
  id: string;
  issue_no: string;
  issue_type_code: string;
  from_location_id: string;
  from_location_name: string;
  to_location_id: string;
  to_location_name: string;
  status: string;
  custody_transfer_id?: string | null;
  notes?: string | null;
  created_at: string;
  created_by: string;
  created_by_name: string;
  acknowledged_at?: string | null;
  acknowledged_by?: string | null;
  acknowledged_by_name?: string | null;
  total_qty: number;
  lines: StoreIssueLine[];
}

export interface StoreIssuePrintLine {
  line_no: number;
  product_code: string;
  product_name: string;
  condition_class: string;
  gs_no?: string | null;
  qty: number;
}

export interface StoreIssuePrintResponse {
  issue_no: string;
  issue_date: string;
  issue_type_code: string;
  from_location: string;
  to_location: string;
  issued_by_name: string;
  acknowledged_by_name?: string | null;
  status: string;
  total_qty: number;
  notes?: string | null;
  lines: StoreIssuePrintLine[];
  signature_blocks: Array<{
    label: string;
    name: string;
    role: string;
  }>;
}
