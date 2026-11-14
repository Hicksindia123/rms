/** P3-04 inventory API types (backend app/modules/inventory/schemas.py). */

export type StockView =
  | 'FUNCTIONAL'
  | 'NON_FUNCTIONAL'
  | 'SPARE_PARTS'
  | 'BATTERIES'
  | 'REJECTED_HOLD'
  | 'HAZARD_QUARANTINE'
  | 'PENDING_HOLD'
  | 'IN_TRANSIT';

export type AssignmentCode =
  | 'CUST_FUNCTIONAL_GOOD'
  | 'CUST_FUNCTIONAL_REPAIRED'
  | 'CUST_NON_FUNCTIONAL'
  | 'CUST_SALVAGED_PARTS';

export interface InventoryOption {
  code: string;
  label: string;
  description?: string | null;
}

export interface InventoryRef {
  id: string;
  code?: string | null;
  name: string;
}

export interface InventoryLookups {
  assignment_options: InventoryOption[];
  views: StockView[];
  products: InventoryRef[];
  part_types: InventoryOption[];
  pcb_models: InventoryRef[];
  pcb_suppliers: InventoryRef[];
  containers: InventoryRef[];
  partitions: InventoryRef[];
  battery_types: InventoryRef[];
  can_export: boolean;
  can_assign: boolean;
  can_request_adjustment: boolean;
  can_approve_adjustment: boolean;
}

export interface StockRow {
  lot_id: string;
  location_id: string;
  location_code: string;
  location_name: string;
  location_class: string;
  qty: number;
  condition_class: string;
  source_condition_code: string | null;
  is_pending: boolean;
  item_kind: string;
  gs_id: string | null;
  gs_no: string | null;
  line_no: number | null;
  product_id: string | null;
  product_code: string | null;
  product_name: string | null;
  category_code: string | null;
  part_type: string | null;
  pcb_model_name: string | null;
  pcb_supplier_name: string | null;
  battery_type_code: string | null;
  battery_type_name: string | null;
  container_code: string | null;
  partition_code: string | null;
  received_at: string | null;
  age_days: number | null;
  transfer_id: string | null;
  transfer_no: string | null;
  transfer_to_name: string | null;
  next_action_code: string | null;
  next_action_text: string | null;
  assignment_codes: string[];
}

export interface StockPage {
  view: StockView;
  items: StockRow[];
  total: number;
  total_qty: number;
  page: number;
  page_size: number;
}

export interface StockFilters {
  q?: string;
  product_id?: string;
  condition_class?: string;
  part_type?: string;
  pcb_model_id?: string;
  pcb_supplier_id?: string;
  container_id?: string;
  partition_id?: string;
  battery_type_id?: string;
  min_age_days?: number | undefined;
}

export interface Balance {
  location_id: string;
  location_code: string;
  location_name: string;
  location_class: string;
  qty: number;
}

export interface Movement {
  id: string;
  lot_id: string;
  lot_condition_class: string;
  is_ancestor: boolean;
  movement_type: string;
  qty: number;
  from_location_code: string | null;
  from_location_name: string | null;
  to_location_code: string | null;
  to_location_name: string | null;
  reference_type: string | null;
  reference_id: string | null;
  reference_no: string | null;
  reason: string | null;
  created_at: string;
  created_by_name: string | null;
}

export interface Assignment {
  id: string;
  lot_id: string;
  qty: number;
  assignment_code: string;
  assignment_label: string;
  condition_class: string;
  from_location_code: string;
  to_location_code: string;
  to_location_name: string;
  outcome: 'ALREADY_IN_PLACE' | 'TRANSFER_INITIATED';
  transfer_id: string | null;
  transfer_no: string | null;
  notes: string | null;
  created_by_name: string | null;
  created_at: string;
}

export interface StockCard {
  lot_id: string;
  condition_class: string;
  source_condition_code: string | null;
  source_condition_label: string | null;
  is_pending: boolean;
  item_kind: string;
  gs_id: string | null;
  gs_no: string | null;
  line_no: number | null;
  product_code: string | null;
  product_name: string | null;
  part_type: string | null;
  pcb_model_name: string | null;
  pcb_supplier_name: string | null;
  container_code: string | null;
  partition_code: string | null;
  lineage: string[];
  balances: Balance[];
  movements: Movement[];
  assignments: Assignment[];
}

export interface Violation {
  rule_code: string;
  guard_ref: string;
  lot_id: string;
  location_id: string;
  location_code: string;
  qty: number;
  condition_class: string;
  location_class: string;
  detail: string;
  gs_no: string | null;
  product_name: string | null;
}

export interface SegregationRun {
  id: string;
  trigger_code: string;
  run_at: string;
  violation_count: number;
}

export interface SegregationCheck {
  checked_at: string;
  violation_count: number;
  violations: Violation[];
  last_nightly_run: SegregationRun | null;
}

export type AdjustmentStatus = 'REQUESTED' | 'APPROVED' | 'REJECTED';

export interface Adjustment {
  id: string;
  lot_id: string;
  location_id: string;
  location_code: string;
  location_name: string;
  condition_class: string;
  item_kind: string;
  gs_no: string | null;
  product_name: string | null;
  part_type: string | null;
  system_qty: number;
  counted_qty: number;
  delta: number;
  current_qty: number;
  reason: string;
  status: AdjustmentStatus;
  requested_by: string;
  requested_by_name: string | null;
  requested_at: string;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_remarks: string | null;
  movement_id: string | null;
  can_decide: boolean;
}

export interface AdjustmentPage {
  items: Adjustment[];
  total: number;
  page: number;
  page_size: number;
}
