/** DEC-73: E-Commerce Returns (mirrors backend app/modules/ecommerce_returns/schemas.py). */
import type { UploadTicket } from '@/features/unboxing/api';

export type ReturnStatus =
  | 'DRAFT'
  | 'IN_CHECKING'
  | 'PENDING_TICKET'
  | 'TICKET_RAISED'
  | 'PENDING_UNBOXING' // DEC-76: the E-Commerce Executive finished
  | 'UNBOXED' // DEC-76: on an action sheet
  | 'CLOSED'
  | 'VOIDED';
export type ProductTypeCode = 'COMPANY_PRODUCT' | 'DIFFERENT_PRODUCT';
export type QcRoutingCode = 'TICKET_RAISE' | 'ISSUE_TO_CHECKING';
export type ResponseCode = 'REJECTED' | 'CLAIM_RECEIVED' | 'PENDING';
export type MediaKind = 'PACKAGE_VIDEO' | 'IMAGE';
export type SlaState = 'ON_TIME' | 'OVERDUE' | 'RAISED_ON_TIME' | 'RAISED_LATE';

/** Stable codes the logic keys off (labels always come from the API, rule e). */
export const OFFLINE_RETURN = 'OFFLINE_RETURN';
export const ECOMMERCE_RETURN = 'ECOMMERCE_RETURN';

export interface Option {
  code: string;
  label: string;
}

export interface FormConfig {
  return_types: Option[];
  platforms: Option[];
  product_types: Option[];
  qc_routings: Option[];
  business_today: string;
  min_entry_date: string | null;
  order_id_pattern: string;
  video: { mime_types: string[]; extensions: string[]; max_bytes: number };
  images: {
    mime_types: string[];
    extensions: string[];
    max_bytes_each: number;
    max_total_bytes: number;
  };
  ticket_sla_hours: number;
}

export interface ProductLookup {
  id: string;
  code: string;
  name: string;
}

export interface OrderMatch {
  id: string;
  return_no: string;
  entry_date: string;
  platform_label: string;
  status: ReturnStatus;
  status_label: string;
}

export interface MediaIn {
  mime_type: string;
  size_bytes: number;
  file_name: string;
}

export interface CreatePayload {
  entry_date: string;
  platform_code: string;
  order_id: string;
  product_type_code: ProductTypeCode;
  product_id: string | null;
  different_product_desc: string | null;
  qty: number;
  qc_routing_code: QcRoutingCode;
  video: MediaIn;
  images: MediaIn[];
}

export interface Media {
  id: string;
  kind: MediaKind;
  mime_type: string;
  size_bytes: number;
  file_name: string | null;
  status: 'PENDING_UPLOAD' | 'CONFIRMED' | 'REJECTED';
  confirmed_at: string | null;
}

export interface MediaUpload {
  media: Media;
  upload: UploadTicket;
}

export interface Ticket {
  id: string;
  sla_due_at: string;
  sla_state: SlaState;
  minutes_to_due: number | null;
  assigned_handler_id: string | null;
  assigned_handler_name: string | null;
  raised_at: string | null;
  response_code: ResponseCode | null;
  response_label: string | null;
  rejection_remark: string | null;
  claim_amount: string | null;
  responded_at: string | null;
  responded_by_name: string | null;
  closed_at: string | null;
  closed_by_name: string | null;
  follow_up_count: number;
  last_follow_up_at: string | null;
  next_follow_up_on: string | null;
}

export interface ReturnEvent {
  event_code: string;
  from_status: string | null;
  to_status: string | null;
  details: Record<string, unknown>;
  actor_name: string | null;
  created_at: string;
}

export interface EcomReturn {
  id: string;
  return_no: string;
  entry_date: string;
  platform_code: string;
  platform_label: string;
  order_id: string;
  product_type_code: ProductTypeCode;
  product_type_label: string;
  product_id: string | null;
  product_code: string | null;
  product_name: string | null;
  different_product_desc: string | null;
  qty: number;
  qc_routing_code: QcRoutingCode;
  qc_routing_label: string;
  status: ReturnStatus;
  status_label: string;
  created_at: string;
  created_by_name: string | null;
  submitted_at: string | null;
  void_reason: string | null;
  voided_at: string | null;
  closed_at: string | null;
  resolution_code: string | null;
  resolution_label: string | null;
  resolution_qty: number | null;
  resolution_note: string | null;
  resolved_at: string | null;
  resolved_by_name: string | null;
  settlement: ReturnSettlement | null;
  media: Media[];
  ticket: Ticket | null;
  events: ReturnEvent[];
}

export interface CreateResult {
  ecommerce_return: EcomReturn;
  uploads: MediaUpload[];
}

export interface ReturnRow {
  id: string;
  return_no: string;
  entry_date: string;
  platform_label: string;
  order_id: string;
  product_text: string;
  qty: number;
  qc_routing_code: QcRoutingCode;
  qc_routing_label: string;
  status: ReturnStatus;
  status_label: string;
  created_at: string;
  ticket: Ticket | null;
}

export interface ReturnList {
  status_options: Option[];
  rows: ReturnRow[];
}

export interface TicketRow {
  return_id: string;
  return_no: string;
  entry_date: string;
  platform_label: string;
  order_id: string;
  product_text: string;
  qty: number;
  status: ReturnStatus;
  status_label: string;
  ticket: Ticket;
}

export interface TicketQueue {
  response_options: Option[];
  resolution_options: Option[];
  rows: TicketRow[];
}

export interface TicketResponseIn {
  response_code: ResponseCode;
  rejection_remark?: string | null;
  claim_amount?: string | null;
}

// --- DEC-76: E-Commerce settlement (mirrors backend app/modules/ecommerce_settlement/schemas.py) ---

/** The only portal resolution that needs a credit note (stable code, rule e). */
export const REFUND = 'REFUND';

export interface ResolutionIn {
  resolution_code: string;
  resolution_qty: number;
  resolution_note: string | null;
}

export interface FollowUpIn {
  note: string;
  next_follow_up_on: string | null;
}

export interface PortalCheckRow {
  return_id: string;
  return_no: string;
  entry_date: string;
  platform_label: string;
  order_id: string;
  product_text: string;
  qty: number;
  submitted_at: string | null;
}

export interface PortalCheckQueue {
  resolution_options: Option[];
  rows: PortalCheckRow[];
}

export interface Location {
  id: string;
  code: string;
  name: string;
}

export interface UnboxingRow {
  return_id: string;
  return_no: string;
  entry_date: string;
  platform_code: string;
  platform_label: string;
  order_id: string;
  product_text: string;
  is_company_product: boolean;
  qty: number;
  qc_routing_label: string;
  resolution_code: string;
  resolution_label: string;
  resolution_qty: number;
  resolution_note: string | null;
  resolved_at: string;
  cn_qty: number;
  store_name: string | null;
}

export interface RepairRow {
  repair_id: string;
  return_id: string;
  return_no: string;
  platform_label: string;
  order_id: string;
  product_text: string;
  location_name: string;
  qty_sent: number;
  sent_at: string;
}

export interface UnboxingQueue {
  platforms: Option[];
  buckets: Option[];
  repair_locations: Location[];
  rows: UnboxingRow[];
  repairs: RepairRow[];
}

export interface UnboxLineIn {
  return_id: string;
  good_qty: number;
  repair_qty: number;
  wastage_qty: number;
  repair_location_id: string | null;
  note: string | null;
}

export interface RepairReturnIn {
  qty_ok: number;
  qty_scrap: number;
  note: string | null;
}

export type SheetStatus = 'PENDING_ACCOUNTS' | 'COMPLETED';

export interface StoreReceiptRow {
  id: string;
  return_id: string;
  return_no: string;
  platform_label: string;
  order_id: string;
  product_code: string | null;
  product_name: string | null;
  source: 'UNBOXING' | 'REPAIR';
  source_label: string;
  store_id: string;
  store_name: string;
  from_location_name: string;
  qty: number;
  status: 'PENDING' | 'ACKNOWLEDGED';
  created_at: string;
  acknowledged_at: string | null;
  acknowledged_by_name: string | null;
  can_acknowledge: boolean;
}

export interface StoreReceipts {
  rows: StoreReceiptRow[];
}

export interface ActionSheetLine {
  return_id: string;
  return_no: string;
  entry_date: string;
  order_id: string;
  product_text: string;
  qty_received: number;
  resolution_code: string;
  resolution_label: string;
  resolution_qty: number;
  cn_qty: number;
  good_qty: number;
  repair_qty: number;
  wastage_qty: number;
  status: string;
  status_label: string;
}

export interface ActionSheet {
  id: string;
  sheet_no: string;
  platform_code: string;
  platform_label: string;
  status: SheetStatus;
  status_label: string;
  created_at: string;
  created_by_name: string | null;
  total_received: number;
  total_cn_qty: number;
  cn_no: string | null;
  cn_date: string | null;
  cn_value: string | null;
  remarks: string | null;
  completed_at: string | null;
  completed_by_name: string | null;
  company_name: string | null;
  business_today: string;
  lines: ActionSheetLine[];
}

export interface ActionSheetRow {
  id: string;
  sheet_no: string;
  platform_label: string;
  status: SheetStatus;
  status_label: string;
  created_at: string;
  orders: number;
  total_received: number;
  total_cn_qty: number;
  cn_no: string | null;
}

export interface ActionSheetList {
  status_options: Option[];
  rows: ActionSheetRow[];
}

export interface CompleteSheetIn {
  cn_no: string | null;
  cn_date: string | null;
  cn_value: string | null;
  remarks: string | null;
}

export interface ReturnSettlement {
  action_sheet_id: string;
  sheet_no: string;
  sheet_status: SheetStatus;
  good_qty: number;
  repair_qty: number;
  wastage_qty: number;
  cn_qty: number;
  unbox_note: string | null;
  unboxed_at: string;
  unboxed_by_name: string | null;
  repair_location_name: string | null;
  repair: {
    id: string;
    location_name: string;
    status: 'AT_DEPARTMENT' | 'RETURNED';
    qty_sent: number;
    qty_ok: number | null;
    qty_scrap: number | null;
    return_note: string | null;
    returned_at: string | null;
    returned_by_name: string | null;
  } | null;
  receipts: Array<{
    id: string;
    source: 'UNBOXING' | 'REPAIR';
    store_name: string;
    qty: number;
    status: 'PENDING' | 'ACKNOWLEDGED';
    acknowledged_at: string | null;
    acknowledged_by_name: string | null;
  }>;
}
