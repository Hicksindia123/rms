/** DEC-73: E-Commerce Returns (mirrors backend app/modules/ecommerce_returns/schemas.py). */
import type { UploadTicket } from '@/features/unboxing/api';

export type ReturnStatus =
  'DRAFT' | 'IN_CHECKING' | 'PENDING_TICKET' | 'TICKET_RAISED' | 'CLOSED' | 'VOIDED';
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
  rows: TicketRow[];
}

export interface TicketResponseIn {
  response_code: ResponseCode;
  rejection_remark?: string | null;
  claim_amount?: string | null;
}
