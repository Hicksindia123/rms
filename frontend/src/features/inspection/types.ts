export type PrimaryExtractionType = 'PACKAGING_EXTRACTED' | 'CONTAINER_EXTRACTED';

export interface ConditionOption {
  code: string;
  label: string;
  allowed_status: string;
  system_behavior: string | null;
  rule_text: string | null;
  next_action_text: string | null;
  remarks: string | null;
  sort_order: number;
}

export interface AllocationIn {
  condition_code: string;
  qty: number;
}

export interface AllocationOut {
  id?: string;
  condition_code: string;
  qty: number;
  allowed_status?: string | null;
  system_behavior?: string | null;
  label?: string | null;
}

export interface ExtractionIn {
  primary_type: PrimaryExtractionType;
  packaging_qty: number;
  container_qty: number;
}

export interface ExtractionOut {
  id?: string;
  primary_type: PrimaryExtractionType;
  packaging_qty: number;
  container_qty: number;
  reconciled: boolean;
}

export interface RejectionOut {
  id: string;
  condition_code: string;
  qty: number;
  disposition: string;
  hazard: boolean;
  stock_movement_id?: string | null;
}

export interface InspectionLineOut {
  gs_item_id: string;
  line_no: number;
  product_id: string;
  product_code: string;
  product_name: string;
  category_id: string;
  category_code: string;
  category_name: string;
  documented_qty: number;
  received_qty: number;
  short_qty: number;
  excess_qty: number;
  requires_full_opening: boolean;
  full_opening_confirmed: boolean;
  inspection_id?: string | null;
  inspection_status: string;
  inspected_by?: string | null;
  inspected_by_name?: string | null;
  inspected_at?: string | null;
  reopened_at?: string | null;
  reopened_by_name?: string | null;
  reopen_reason?: string | null;
  condition_options: ConditionOption[];
  allocations: AllocationOut[];
  extraction?: ExtractionOut | null;
  rejections: RejectionOut[];
}

export interface InspectionTotals {
  lines_count: number;
  lines_finalised: number;
  total_received_qty: number;
  total_graded_qty: number;
  total_rejected_qty: number;
  total_hazard_qty: number;
}

export interface InspectionPermissions {
  can_inspect: boolean;
  can_finalise: boolean;
  can_reopen: boolean;
}

export interface InspectionGsOut {
  gs_id: string;
  gs_no: string;
  status: string;
  category_code?: string | null;
  has_hazard: boolean;
  has_rejections: boolean;
  lines: InspectionLineOut[];
  totals: InspectionTotals;
  permissions: InspectionPermissions;
}

export interface InspectionDraftIn {
  full_opening_confirmed: boolean;
  allocations: AllocationIn[];
  extraction?: ExtractionIn | null;
}

export interface FinaliseLineOut {
  gs_item_id: string;
  status: string;
  is_gs_finalised: boolean;
  next_status: string;
  rejections: RejectionOut[];
  lots_created: Array<Record<string, unknown>>;
}

export interface FinaliseAllOut {
  gs_id: string;
  lines_finalised: number;
  all_finalised: boolean;
  next_status: string;
}
