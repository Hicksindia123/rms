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
  /** DEC-56 Q8 / Q17: where the received pieces go (wastage -> scrap, default -> store). */
  destination_location_code?: string | null;
  destination_location_name?: string | null;
}

/** DEC-56 Q7: one condition of the product categorisation list. */
export interface ConditionOption {
  field_id: string;
  code: string;
  label: string;
}

/** DEC-56: one condition of an item's current split (original = counting split). */
export interface ItemCondition {
  field_id: string;
  field_code: string;
  field_label: string;
  original_qty: number;
  current_qty: number;
  /** Planned, at a department, or back with a final outcome. */
  committed_qty: number;
  free_qty: number;
  /** Free to plan now (never more than the item's unplanned pieces). */
  plannable_qty: number;
}

/** DEC-55 (gap plan G2): RM routing plan per item + condition; the Store Manager issues. */
export interface RoutingPlanLineIn {
  gs_item_id: string;
  source_bucket_field_id?: string | null | undefined;
  department_field_id: string;
  qty: number;
  notes?: string | null | undefined;
}

export interface CreateRoutingPlanIn {
  gs_id: string;
  lines: RoutingPlanLineIn[];
}

export type RoutingPlanStatus = 'PLANNED' | 'ISSUED' | 'NO_WORK' | 'CANCELLED';

export interface RoutingPlanLine {
  id: string;
  gs_id: string;
  gs_no: string;
  gs_item_id: string;
  line_no: number;
  item_name: string;
  sku_code?: string | null;
  source_bucket_field_id?: string | null;
  source_bucket_label?: string | null;
  department_field_id: string;
  department_code: string;
  department_label: string;
  is_no_work: boolean;
  qty: number;
  status: RoutingPlanStatus;
  notes?: string | null;
  planned_at: string;
  planned_by_name?: string | null;
  routing_id?: string | null;
  routing_no?: string | null;
  issued_at?: string | null;
  issued_by_name?: string | null;
  cancelled_at?: string | null;
  cancel_reason?: string | null;
}

export interface RoutingPlanOut {
  gs_id: string;
  lines: RoutingPlanLine[];
}

export interface StoreIssueIn {
  gs_id: string;
  department_field_id: string;
  plan_line_ids: string[];
  remarks?: string | null | undefined;
}

export interface IssueQueueGroup {
  gs_id: string;
  gs_no: string;
  party_name?: string | null;
  department_field_id: string;
  department_code: string;
  department_label: string;
  planned_since: string;
  total_qty: number;
  lines: RoutingPlanLine[];
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
  /** DEC-56 Q7: conditions the pieces may come back in (empty = routed without a condition). */
  condition_options?: ConditionOption[];
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
  /** DEC-55: where the Store issue moved the stock (older routings: Technician Bench). */
  location_code?: string | null;
  location_name?: string | null;
  lines: DepartmentRoutingLineOut[];
}

export interface DepartmentReceiptLineIn {
  routing_line_id: string;
  outcome_head_id: string;
  quantity: number;
  /** DEC-56 Q7: required when the routing line came from a condition. */
  condition_field_id?: string | null | undefined;
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
  /** DEC-56: condition before / after work and where the stock went (null before G3). */
  source_condition_field_id?: string | null;
  condition_field_id?: string | null;
  condition_code?: string | null;
  condition_label?: string | null;
  destination_location_code?: string | null;
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
  /** DEC-55: parts of in_store_qty. */
  planned_qty?: number;
  no_work_qty?: number;
  unplanned_qty?: number;
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
  total_planned?: number;
  total_no_work?: number;
  total_unplanned?: number;
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
  planned_qty?: number;
  no_work_qty?: number;
  unplanned_qty?: number;
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
  planned_qty: number;
  no_work_qty: number;
  unplanned_qty: number;
  allowed_departments: Array<{
    field_id: string;
    code: string;
    label: string;
    sort_order: number;
    /** DEC-55: "no work" department (e.g. STORE): pieces stay in the store, no issue. */
    is_no_work: boolean;
  }>;
  buckets: Array<{
    id: string;
    field_id: string;
    field_code: string;
    field_label: string;
    qty: number;
    /** DEC-55: pieces of this condition already routed / still free to plan. */
    routed_qty: number;
    plannable_qty: number;
  }>;
  /** DEC-56: the CURRENT condition split (after department work); planning works from it. */
  conditions: ItemCondition[];
}

export interface GsRoutingState {
  id: string;
  gs_no: string;
  status: string;
  party_name?: string | null;
  created_at: string;
  updated_at: string;
  items: GsRoutingItemState[];
  plan_lines: RoutingPlanLine[];
}
