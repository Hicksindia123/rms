import type { ItemBucket, ItemCount, ResolvedBucketField } from '@/features/itemization/api';

// Shapes mirror backend/app/modules/rm_review/schemas.py; buckets/counts reuse the itemization
// shapes (ItemBucketOut / ItemCountOut / ResolvedBucketField).
export type { ItemBucket, ItemCount };

export interface RmReviewHeader {
  id: string;
  gs_no: string;
  status: string;
  party_id: string | null;
  party_name: string | null;
  station_name: string | null;
  doc_type: string | null;
  doc_no: string | null;
  doc_date: string | null;
  transporter_name: string | null;
  docket_no: string | null;
  carton_count: number;
  counted_by: string | null;
  counted_by_name: string | null;
  category_code: string | null;
  created_at: string;
}

export interface RmReviewDocument {
  id: string;
  document_type: string;
  document_number: string | null;
  document_date: string | null;
  file_url: string | null;
  file_name: string | null;
}

export interface RmReviewCartonVideo {
  id: string;
  carton_no: number | null;
  file_url: string;
  file_name: string;
  created_at: string;
}

export interface RmReviewItem {
  item_id: string;
  product_id: string;
  sku_code: string;
  sku_name: string;
  documented_qty: number;
  received_qty: number;
  short_qty: number;
  excess_qty: number;
  allowed_buckets: ResolvedBucketField[];
  allowed_counts: ResolvedBucketField[];
  buckets: ItemBucket[];
  total_bucket_qty: number;
  is_conserved: boolean;
  counts: ItemCount[];
}

export interface RmReviewRevision {
  id: string;
  revision_no: number;
  action:
    | 'SUBMITTED'
    | 'RM_EDIT'
    | 'RM_SENT_BACK'
    | 'RM_APPROVED'
    | 'RM_ADD_LINE'
    | 'RM_REMOVE_LINE'
    | 'RM_CHANGE_PRODUCT';
  items_snapshot: Array<{
    item_id?: string;
    sku_code?: string | null;
    sku_name?: string | null;
    documented_qty: number;
    received_qty: number;
    buckets: Array<{ code: string; label?: string; qty: number }>;
  }>;
  remarks: string | null;
  created_by: string;
  created_by_name: string | null;
  created_at: string;
}

export interface TransferSlipSummary {
  id: string;
  transfer_no: string;
  status: string;
  from_location_code: string;
  to_location_code: string;
  total_lines: number;
  total_qty: number;
}

export interface RmReviewData {
  goods_slip: RmReviewHeader;
  documents: RmReviewDocument[];
  carton_videos: RmReviewCartonVideo[];
  items: RmReviewItem[];
  revisions: RmReviewRevision[];
  transfer_slip: TransferSlipSummary | null;
  all_conserved: boolean;
  can_review: boolean;
}

export interface RmEditItemPayload {
  documented_qty?: number;
  received_qty?: number;
  buckets: Array<{ field_code: string; qty: number }>;
  counts?: Array<{ count_type: string; count_value: number }>;
  remarks?: string | null;
}

export interface RmAddLinePayload {
  product_id: string;
  documented_qty: number;
  received_qty: number;
  buckets: Array<{ field_code: string; qty: number }>;
  counts?: Array<{ count_type: string; count_value: number }>;
  reason: string;
}

export interface RmRemoveLinePayload {
  reason: string;
}

export interface RmChangeProductPayload {
  product_id: string;
  documented_qty?: number;
  received_qty?: number;
  buckets: Array<{ field_code: string; qty: number }>;
  counts?: Array<{ count_type: string; count_value: number }>;
  reason: string;
}

export interface RmSendBackPayload {
  remarks: string;
}

export interface RmApprovePayload {
  remarks?: string | null;
}

export interface RmApproveResult {
  goods_slip_id: string;
  status: string;
  transfer_id: string;
  transfer_no: string;
  message: string;
}
