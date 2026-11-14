import { apiRequest } from '@/lib/api/client';
import type { Attachment } from '@/features/unboxing/api';

// Shapes mirror backend/app/modules/itemization/schemas.py (P2-04).

export interface ProductLookup {
  id: string;
  code: string;
  name: string;
  uom: string;
  category_id: string;
  category_code: string;
  category_name: string;
  subcategory_id?: string | null;
  subcategory_name?: string | null;
}

/** Counting search filters (AMD-07 Category -> Sub-Category). */
export interface CategoryLookup {
  id: string;
  code: string;
  name: string;
  subcategories: Array<{ id: string; code: string; name: string }>;
}

export interface ItemLine {
  id: string;
  gs_id: string;
  line_no: number;
  product_id: string;
  product_code: string | null;
  product_name: string | null;
  category_id: string;
  category_code: string | null;
  category_name: string | null;
  documented_qty: number;
  received_qty: number;
  short_qty: number;
  excess_qty: number;
  /** DEC-09: documented > received (all categories by default). */
  is_short: boolean;
  remarks: string | null;
  lot_id: string | null;
  stocked_qty: number | null;
}

/** An option of RETURN_CATEGORY / CSR_APPROVAL as published in the step form (labels from config). */
export interface StepOption {
  code: string;
  label: string;
  /** YES | CONDITIONAL — CONDITIONAL is shown as "Requires approval". */
  allowed_status: string | null;
  rule_text: string | null;
  next_action_text: string | null;
  remarks: string | null;
}

export interface CsrDecision {
  id: string;
  gs_id: string;
  decision_code: string;
  decision_label: string;
  remarks: string | null;
  is_current: boolean;
  is_admin_action: boolean;
  decided_by: string;
  decided_by_name: string | null;
  decided_at: string;
  reopened_by: string | null;
  reopened_by_name: string | null;
  reopened_at: string | null;
  reopen_reason: string | null;
}

export interface Transfer {
  id: string;
  transfer_no: string;
  status: string;
  purpose_code: string | null;
  with_packaging: boolean;
  stock_moved: boolean;
  from_location_code: string;
  from_location_name: string;
  to_location_code: string;
  to_location_name: string;
  initiated_by_name: string | null;
  initiated_at: string;
  notes: string | null;
  lines: Array<{
    lot_id: string;
    qty_sent: number;
    line_no: number | null;
    product_name: string | null;
  }>;
}

export interface PackagingCheck {
  id: string;
  lot_id: string;
  result_code: 'OK' | 'REPLACED';
  qty_replaced: number;
  remarks: string | null;
  by: string | null;
  by_name: string | null;
  at: string;
}

export interface Lot {
  lot_id: string;
  gs_item_id: string | null;
  condition_class: string;
  is_pending: boolean;
  total_qty: number;
  balances: Array<{ location_code: string; location_name: string; qty: number }>;
  packaging_checks: PackagingCheck[];
}

export interface LineCorrection {
  id: string;
  gs_id: string;
  gs_no: string;
  gs_item_id: string;
  line_no: number;
  product_name: string | null;
  old_documented_qty: number;
  old_received_qty: number;
  new_documented_qty: number;
  new_received_qty: number;
  reason: string;
  status: string;
  requested_by: string;
  requested_by_name: string | null;
  requested_at: string;
  decided_by: string | null;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_remarks: string | null;
  applied_at: string | null;
}

export interface ItemizationGs {
  id: string;
  gs_no: string;
  status: string;
  party_name: string | null;
  station_name: string | null;
  carton_count: number;
  box_count: number;
  missing_documentation: boolean;
  category_code: string | null;
  original_category_code: string | null;
  csr_commercial_path: boolean;
  categorized_at: string | null;
}

export interface Totals {
  lines: number;
  documented_qty: number;
  received_qty: number;
  short_qty: number;
  excess_qty: number;
}

export interface ItemizationState {
  goods_slip: ItemizationGs;
  items: ItemLine[];
  totals: Totals;
  category_options: StepOption[];
  category_label: string | null;
  decision_options: StepOption[];
  current_decision: CsrDecision | null;
  decisions: CsrDecision[];
  lots: Lot[];
  transfers: Transfer[];
  corrections: LineCorrection[];
  evidence: Attachment[];
  permissions: {
    /** Counting (status ITEMIZATION): lines are a saved draft. */
    can_edit_lines: boolean;
    /** AMD-08: Counting -> CATEGORISATION. */
    can_submit_counting: boolean;
    can_categorize: boolean;
    can_decide: boolean;
    can_reopen: boolean;
    can_request_correction: boolean;
    can_decide_correction: boolean;
    can_check_packaging: boolean;
  };
}

export interface CategorizeResult {
  state: ItemizationState;
  task_ids: string[];
  notified_user_count: number;
}

export interface CsrApprovalCardData {
  goods_slip: ItemizationGs;
  items: ItemLine[];
  totals: Totals;
  category_label: string | null;
  categorized_by_name: string | null;
  evidence: Attachment[];
  decision_options: StepOption[];
}

export interface LineInput {
  product_id: string;
  documented_qty: number;
  received_qty: number;
  remarks?: string | null;
}

const gs = (id: string) => `/gs/${encodeURIComponent(id)}`;

export const itemizationApi = {
  state: (gsId: string) => apiRequest<ItemizationState>(`${gs(gsId)}/itemization`),
  products: (q: string, filters: { categoryId?: string; subcategoryId?: string } = {}) =>
    apiRequest<ProductLookup[]>('/itemization/lookups/products', {
      query: {
        q,
        limit: 20,
        category_id: filters.categoryId || undefined,
        subcategory_id: filters.subcategoryId || undefined,
      },
    }),
  categories: () => apiRequest<CategoryLookup[]>('/itemization/lookups/categories'),
  submitCounting: (gsId: string, idempotencyKey: string) =>
    apiRequest<ItemizationState>(`${gs(gsId)}/counting/submit`, {
      method: 'POST',
      idempotencyKey,
    }),
  addItem: (gsId: string, body: LineInput) =>
    apiRequest<ItemLine>(`${gs(gsId)}/items`, { method: 'POST', body }),
  updateItem: (gsId: string, itemId: string, body: Partial<LineInput>) =>
    apiRequest<ItemLine>(`${gs(gsId)}/items/${encodeURIComponent(itemId)}`, {
      method: 'PATCH',
      body,
    }),
  deleteItem: (gsId: string, itemId: string) =>
    apiRequest<undefined>(`${gs(gsId)}/items/${encodeURIComponent(itemId)}`, {
      method: 'DELETE',
    }),
  categorize: (gsId: string, category: string, remarks: string, idempotencyKey: string) =>
    apiRequest<CategorizeResult>(`${gs(gsId)}/categorize`, {
      method: 'POST',
      body: { category, remarks: remarks || null },
      idempotencyKey,
    }),
  decide: (gsId: string, decision: string, remarks: string, idempotencyKey: string) =>
    apiRequest<ItemizationState>(`${gs(gsId)}/csr-decision`, {
      method: 'POST',
      body: { decision, remarks: remarks || null },
      idempotencyKey,
    }),
  reopen: (gsId: string, reason: string) =>
    apiRequest<ItemizationState>(`${gs(gsId)}/csr-decision/reopen`, {
      method: 'POST',
      body: { reason },
    }),
  pendingCsr: () => apiRequest<CsrApprovalCardData[]>('/csr-approvals/pending'),
  requestCorrection: (
    gsId: string,
    itemId: string,
    body: { documented_qty: number; received_qty: number; reason: string },
  ) =>
    apiRequest<LineCorrection>(`${gs(gsId)}/items/${encodeURIComponent(itemId)}/corrections`, {
      method: 'POST',
      body,
    }),
  decideCorrection: (
    gsId: string,
    correctionId: string,
    decision: 'APPROVE' | 'REJECT',
    remarks: string,
    idempotencyKey: string,
  ) =>
    apiRequest<LineCorrection>(
      `${gs(gsId)}/item-corrections/${encodeURIComponent(correctionId)}/decision`,
      { method: 'POST', body: { decision, remarks: remarks || null }, idempotencyKey },
    ),
  pendingCorrections: () => apiRequest<LineCorrection[]>('/item-corrections/pending'),
  packagingCheck: (
    lotId: string,
    body: { result: 'OK' | 'REPLACED'; qty_replaced: number; remarks: string | null },
  ) =>
    apiRequest<PackagingCheck>(`/lots/${encodeURIComponent(lotId)}/packaging-check`, {
      method: 'POST',
      body,
    }),
  getCategorisation: (gsId: string) =>
    apiRequest<CategorisationStateOut>(`${gs(gsId)}/categorisation`),
  saveItemCategorisation: (
    gsId: string,
    itemId: string,
    body: {
      buckets: Array<{ field_code: string; qty: number }>;
      counts: Array<{ field_code: string; count_value: number }>;
    },
  ) =>
    apiRequest<ItemCategorisationDetail>(
      `${gs(gsId)}/items/${encodeURIComponent(itemId)}/categorisation`,
      { method: 'PUT', body },
    ),
  submitCategorisation: (
    gsId: string,
    body: { category_code?: string; remarks?: string | null },
    idempotencyKey: string,
  ) =>
    apiRequest<{ gs_id: string; status: string }>(`${gs(gsId)}/categorisation/submit`, {
      method: 'POST',
      body,
      idempotencyKey,
    }),
};

export interface ResolvedBucketField {
  field_id: string;
  field_code: string;
  label: string;
  rank: number;
}

export interface ItemBucket {
  id?: string;
  field_id?: string;
  field_code: string;
  label_snapshot?: string;
  qty: number;
}

export interface ItemCount {
  id?: string;
  field_id?: string;
  field_code?: string;
  count_type?: string;
  label_snapshot?: string;
  count_value: number;
}

export interface ItemCategorisationDetail {
  id: string;
  line_no: number;
  product_id: string;
  sku_code: string | null;
  sku_name: string | null;
  category_name: string | null;
  documented_qty: number;
  received_qty: number;
  allowed_buckets: ResolvedBucketField[];
  allowed_counts: ResolvedBucketField[];
  buckets: ItemBucket[];
  counts: ItemCount[];
  total_bucket_qty: number;
  is_conserved: boolean;
}

export interface CategorisationStateOut {
  goods_slip: {
    id: string;
    gs_no: string;
    status: string;
    counted_by?: string | null;
    created_at: string;
  };
  items: ItemCategorisationDetail[];
  all_conserved: boolean;
  can_submit: boolean;
  counted_by_id: string | null;
  is_counted_by_current_user: boolean;
}

/** A fresh key per user intent; reused when the same intent is retried after a failure. */
export function newIdempotencyKey(): string {
  return `web-${crypto.randomUUID()}`;
}
