export interface Technician {
  id: string;
  display_name: string;
}

export interface IntermediateLot {
  lot_id: string;
  stock_item_id: string;
  gs_id: string | null;
  gs_no: string | null;
  product_id: string;
  product_name: string;
  product_code: string;
  category_code: string;
  supports_battery: boolean;
  condition_class: string;
  source_condition_code: string | null;
  routing_hint: string | null;
  requires_evaluation: boolean;
  available_qty: number;
}

export interface BatchSummary {
  id: string;
  batch_no: string;
  technician_name: string;
  entry_by_name: string;
  status: 'ALLOTTED' | 'PARTIALLY_RECEIVED' | 'COMPLETED' | 'CANCELLED';
  age_days: number;
  allotted_at: string;
  total_qty_allotted: number;
  total_qty_received: number;
  line_count: number;
}

export interface BatchLine {
  id: string;
  batch_id: string;
  lot_id: string;
  product_name: string;
  product_code: string;
  category_code: string;
  supports_battery: boolean;
  source_condition_code: string | null;
  routing_hint: string | null;
  requires_evaluation: boolean;
  evaluation_notes: string | null;
  qty_allotted: number;
  qty_received: number;
  status: string;
}

export interface ReceivingRecord {
  id: string;
  batch_line_id: string;
  qty_received: number;
  battery_check_code: string | null;
  pieces_checked: number | null;
  batteries_installed: number | null;
  battery_type_code: string | null;
  battery_type_name: string | null;
  cleaning_code: string | null;
  functional_good_qty: number;
  functional_repaired_qty: number;
  non_good_qty: number;
  non_sellable_qty: number;
  evaluation_notes: string | null;
  technician_remarks: string | null;
  entry_by_name: string;
  received_at: string;
}

export interface BatchDetail {
  id: string;
  batch_no: string;
  technician_id: string;
  technician_name: string;
  entry_by: string;
  entry_by_name: string;
  status: 'ALLOTTED' | 'PARTIALLY_RECEIVED' | 'COMPLETED' | 'CANCELLED';
  transfer_id: string | null;
  allotted_at: string;
  completed_at: string | null;
  notes: string | null;
  total_qty_allotted: number;
  total_qty_received: number;
  lines: BatchLine[];
  receiving_records: ReceivingRecord[];
}

export interface AllotLinePayload {
  lot_id: string;
  qty: number;
}

export interface AllotBatchPayload {
  technician_id: string;
  entry_by?: string | undefined;
  notes?: string | undefined;
  lines: AllotLinePayload[];
}

export interface LineReceivePayload {
  batch_line_id: string;
  qty_receiving: number;
  battery_check_code?: string | null | undefined;
  pieces_checked?: number | null | undefined;
  batteries_installed?: number | null | undefined;
  battery_type_id?: string | null | undefined;
  cleaning_code?: string | null | undefined;
  allocations: {
    FUNCTIONAL_GOOD?: number;
    FUNCTIONAL_REPAIRED?: number;
    NON_GOOD?: number;
    NON_SELLABLE?: number;
  };
  evaluation_notes?: string | null | undefined;
  technician_remarks?: string | null | undefined;
}

export interface ReceiveBatchPayload {
  lines: LineReceivePayload[];
}

export interface BatteryReconciliationTypeRow {
  battery_type_id: string;
  battery_type_code: string;
  battery_type_name: string;
  batteries_installed: number;
  battery_stock_movements: number;
  discrepancy: number;
  ties_out: boolean;
}

export interface BatteryReconciliation {
  pieces_checked: number;
  pieces_with_battery_replaced: number;
  batteries_installed: number;
  battery_stock_movements: number;
  discrepancy: number;
  ties_out: boolean;
  by_battery_type: BatteryReconciliationTypeRow[];
}
