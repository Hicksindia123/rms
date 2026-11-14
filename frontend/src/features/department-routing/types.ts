/**
 * Types for Department Routing, Receiving, and G-20 Reconciliation.
 * (Change plan 2026-11-12 Phase 6; AMD-10, AMD-14, AMD-15; DEC-42, DEC-43; Guard G-20).
 */

export interface DepartmentOutcomeHead {
  id: string;
  code: string;
  label: string;
  is_wastage: boolean;
  returns_to_routing: boolean;
  sort_order: number;
  is_active: boolean;
}

export interface DepartmentRoutingLineIn {
  gs_item_id: string;
  source_bucket_field_id?: string | null | undefined;
  qty_sent: number;
  notes?: string | null | undefined;
}

export interface CreateDepartmentRoutingIn {
  gs_id: string;
  department_field_id: string;
  lines: DepartmentRoutingLineIn[];
  remarks?: string | null | undefined;
}

export interface DepartmentRoutingLineOut {
  id: string;
  routing_id: string;
  gs_item_id: string;
  line_no: number;
  item_name: string;
  sku_code?: string | null;
  source_bucket_field_id?: string | null;
  source_bucket_code?: string | null;
  source_bucket_label?: string | null;
  qty_sent: number;
  qty_received: number;
  qty_pending: number;
  notes?: string | null;
}

export interface DepartmentRoutingOut {
  id: string;
  routing_no: string;
  gs_id: string;
  gs_no: string;
  department_field_id: string;
  department_code: string;
  department_label: string;
  status: 'DISPATCHED' | 'PARTIALLY_RECEIVED' | 'COMPLETED' | 'CANCELLED';
  dispatched_at: string;
  dispatched_by?: string | null;
  dispatched_by_name?: string | null;
  remarks?: string | null;
  lines: DepartmentRoutingLineOut[];
}

export interface DepartmentReceiptLineIn {
  routing_line_id: string;
  outcome_head_id: string;
  quantity: number;
  remarks?: string | null | undefined;
}

export interface CreateDepartmentReceiptIn {
  routing_id: string;
  lines: DepartmentReceiptLineIn[];
  remarks?: string | null | undefined;
}

export interface DepartmentReceiptLineOut {
  id: string;
  receipt_id: string;
  routing_line_id: string;
  outcome_head_id: string;
  outcome_code: string;
  outcome_label: string;
  is_wastage: boolean;
  returns_to_routing: boolean;
  quantity: number;
  remarks?: string | null;
  created_at: string;
}

export interface DepartmentReceiptOut {
  id: string;
  receipt_no: string;
  routing_id: string;
  received_by?: string | null;
  received_by_name?: string | null;
  received_at: string;
  remarks?: string | null;
  lines: DepartmentReceiptLineOut[];
}

export interface ItemReconciliationOut {
  gs_item_id: string;
  line_no: number;
  item_name: string;
  sku_code?: string | null;
  counted_qty: number;
  in_store_qty: number;
  at_departments_qty: number;
  outcome_heads_qty: number;
  actioned_qty: number;
  is_conserved: boolean;
}

export interface GsReconciliationOut {
  gs_id: string;
  gs_no: string;
  is_fully_reconciled: boolean;
  total_counted: number;
  total_in_store: number;
  total_at_departments: number;
  total_outcomes: number;
  total_actioned: number;
  items: ItemReconciliationOut[];
}

export interface DepartmentLegOut {
  routing_id: string;
  routing_no: string;
  department_code: string;
  department_label: string;
  dispatched_at: string;
  dispatched_by_name?: string | null;
  status: string;
  qty_sent: number;
  qty_received: number;
  qty_pending: number;
  lines: DepartmentRoutingLineOut[];
  receipts: DepartmentReceiptOut[];
}

export interface RmRoutingQueueItemOut {
  gs_id: string;
  gs_no: string;
  party_name?: string | null;
  item_count: number;
  total_counted_qty: number;
  in_store_qty: number;
  at_departments_qty: number;
  active_routings_count: number;
  held_since: string;
}

export interface ReceivingQueueItemOut {
  routing_id: string;
  routing_no: string;
  gs_id: string;
  gs_no: string;
  department_code: string;
  department_label: string;
  status: string;
  dispatched_at: string;
  dispatched_by_name?: string | null;
  total_sent: number;
  total_received: number;
  total_pending: number;
}

export interface GsRoutingItemState {
  item_id: string;
  line_no: number;
  item_name: string;
  sku_code?: string | null;
  product_id: string;
  counted_qty: number;
  in_store_qty: number;
  at_departments_qty: number;
  outcome_heads_qty: number;
  actioned_qty: number;
  allowed_departments: Array<{
    field_id: string;
    code: string;
    label: string;
    sort_order: number;
  }>;
  buckets: Array<{
    id: string;
    field_id: string;
    field_code: string;
    field_label: string;
    qty: number;
  }>;
}

export interface GsRoutingState {
  id: string;
  gs_no: string;
  status: string;
  party_name?: string | null;
  created_at: string;
  updated_at: string;
  items: GsRoutingItemState[];
}
