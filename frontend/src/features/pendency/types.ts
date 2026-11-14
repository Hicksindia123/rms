/**
 * Types for Pendency register and clearance.
 * References: WF r7 col K, BR-20, DEC-12, G-08.
 */

export interface ClearPendencyRequest {
  resolution_action: string;
  notes: string;
}

export interface PendencyItem {
  id: string;
  gs_id: string;
  gs_no: string;
  party_name: string;
  gs_item_id?: string | null;
  line_no?: number | null;
  product_name?: string | null;
  qty: number;
  reason: string;
  sent_to?: string | null;
  blocks_gs: boolean;
  status: 'OPEN' | 'CLEARED';
  opened_by: string;
  opened_by_name: string;
  opened_at: string;
  cleared_by?: string | null;
  cleared_by_name?: string | null;
  cleared_at?: string | null;
  clearance_notes?: string | null;
  resolution_action?: string | null;
  age_days: number;
  age_hours: number;
}
